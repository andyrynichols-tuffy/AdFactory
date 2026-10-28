"""Ingest episodes: probe, make an editor proxy, transcribe with word timings,
detect scene cuts and loud moments. Writes one JSON index per episode."""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

from .config import CFG, FFMPEG, FFPROBE, INDEX_DIR, PROXY_DIR

VIDEO_EXTS = {".mkv", ".mp4", ".m4v", ".avi", ".mov", ".webm", ".ts", ".wmv"}
SR = 16000


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def episode_id(show: str, path: Path) -> str:
    m = re.search(r"[sS](\d{1,2})[ ._-]?[eE](\d{1,3})", path.stem) or re.search(r"(\d{1,2})x(\d{2})", path.stem)
    tag = f"s{int(m.group(1)):02d}e{int(m.group(2)):02d}" if m else slug(path.stem)[:40]
    return f"{slug(show)}_{tag}"


def probe(path: Path) -> dict:
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=True,
    ).stdout
    info = json.loads(out)
    v = next((s for s in info["streams"] if s["codec_type"] == "video"), {})
    return {
        "duration": float(info["format"]["duration"]),
        "width": v.get("width"),
        "height": v.get("height"),
    }


def has_nvenc() -> bool:
    if CFG.get("encoder") == "x264":
        return False
    r = subprocess.run([FFMPEG, "-hide_banner", "-f", "lavfi", "-i", "color=s=256x256:d=0.1",
                        "-c:v", "h264_nvenc", "-f", "null", "-"], capture_output=True)
    return r.returncode == 0


_NVENC = None


def video_encoder_args(quality: str = "final") -> list:
    global _NVENC
    if _NVENC is None:
        _NVENC = has_nvenc()
    cq = {"proxy": 28, "final": 19}[quality]
    if _NVENC:
        return ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", str(cq), "-b:v", "0"]
    return ["-c:v", "libx264", "-preset", "veryfast" if quality == "proxy" else "medium", "-crf", str(cq - 1)]


def make_proxy(src: Path, dst: Path):
    # 480p, keyframe every second so the editor seeks instantly.
    cmd = [FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-i", str(src),
           "-map", "0:v:0", "-map", "0:a:0?", "-vf", "scale=-2:480,fps=30",
           *video_encoder_args("proxy"), "-g", "30", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "96k", "-ac", "2", "-movflags", "+faststart", str(dst)]
    subprocess.run(cmd, check=True)


def decode_audio(src: Path) -> np.ndarray:
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-i", str(src), "-map", "0:a:0",
           "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32)


def scene_cuts(src: Path, threshold: float = 0.3) -> list:
    cmd = [FFMPEG, "-hide_banner", "-i", str(src), "-map", "0:v:0",
           "-vf", f"scale=320:-2,select='gt(scene,{threshold})',showinfo", "-f", "null", "-"]
    err = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace").stderr
    return [round(float(t), 3) for t in re.findall(r"pts_time:([\d.]+)", err)]


def energy_profile(audio: np.ndarray, hop: float = 0.5):
    """RMS loudness per half second plus local peaks (laughs, yelling, crashes)."""
    n = int(SR * hop)
    frames = len(audio) // n
    if frames == 0:
        return [], []
    rms = np.sqrt((audio[: frames * n].reshape(frames, n) ** 2).mean(axis=1) + 1e-10)
    db = 20 * np.log10(rms)
    loud = db > np.percentile(db, 10)  # ignore near-silence when scaling
    z = (db - db[loud].mean()) / (db[loud].std() + 1e-6)
    # Broadcast audio is compressed, so global loudness barely varies. Score each
    # frame against its ~30s neighbourhood instead and keep the top few percent
    # (yelling, laugh bursts, crashes) as local maxima at least 3s apart.
    win = int(30 / hop)
    pad = np.pad(db, win // 2, mode="edge")
    local = np.array([np.median(pad[i:i + win]) for i in range(frames)])
    spike = db - local
    thresh = np.percentile(spike[loud], 97)
    peaks = []
    for i in np.argsort(-spike):
        if spike[i] < thresh:
            break
        t = round(i * hop, 1)
        if loud[i] and all(abs(t - p) > 3 for p in peaks):
            peaks.append(t)
    return [round(float(x), 2) for x in z], sorted(peaks)


def _add_cuda_dll_dirs():
    if os.name != "nt":
        return
    import site
    for sp in site.getsitepackages():
        for sub in ("nvidia/cublas/bin", "nvidia/cudnn/bin", "nvidia/cuda_runtime/bin"):
            p = Path(sp) / sub
            if p.exists():
                os.add_dll_directory(str(p))
                os.environ["PATH"] = str(p) + os.pathsep + os.environ["PATH"]


_MODEL = None


def whisper_model():
    global _MODEL
    if _MODEL is None:
        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
        _add_cuda_dll_dirs()
        from faster_whisper import WhisperModel
        try:
            _MODEL = WhisperModel(CFG["whisper_model"], device="cuda", compute_type="float16")
            print(f"  whisper: {CFG['whisper_model']} on GPU")
        except Exception as e:  # no CUDA -> slower CPU fallback
            print(f"  whisper: GPU unavailable ({e}); using CPU 'small'")
            _MODEL = WhisperModel("small", device="cpu", compute_type="int8")
    return _MODEL


def transcribe(audio: np.ndarray) -> list:
    from . import resources
    with resources.gpu_slot(print):
        segs, _ = whisper_model().transcribe(
            audio, language="en", word_timestamps=True, vad_filter=True,
            condition_on_previous_text=False,
        )
        done = []
        for s in segs:  # whisper works lazily, one piece per segment: pause between pieces if PlayOn records
            resources.yield_to_playon(print)
            done.append(s)
    words = [[w.word.strip(), round(w.start, 2), round(w.end, 2)]
             for s in done for w in (s.words or []) if w.word.strip()]
    # Re-split into sentence-sized lines (whisper segments run long), also
    # breaking on long pauses -- these lines are the units Claude picks from.
    out, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        if nxt is None or re.search(r"[.!?]$", w[0]) or nxt[1] - w[2] > 1.0 or len(cur) >= 30:
            out.append({"start": cur[0][1], "end": cur[-1][2], "text": " ".join(x[0] for x in cur), "words": cur})
            cur = []
    return out


def incomplete_reason(src: Path):
    """Why this file shouldn't be ingested yet (None = looks like a full episode)."""
    try:
        with open(src, "rb"):
            pass
    except PermissionError:
        return "locked (still being recorded?)"
    if time.time() - src.stat().st_mtime < 300:
        return "modified in the last 5 min (still being recorded?)"
    try:
        dur = probe(src)["duration"]
    except Exception:
        return "unreadable/truncated file"
    min_min = CFG.get("min_episode_minutes", 20)
    if dur < min_min * 60:
        return f"only {dur / 60:.1f} min long (< {min_min} min, looks incomplete)"
    return None


def ingest_file(src: Path, show: str, force: bool = False) -> str:
    eid = episode_id(show, src)
    idx_path = INDEX_DIR / f"{eid}.json"
    if idx_path.exists() and not force:
        print(f"[skip] {eid} already indexed")
        return eid
    problem = incomplete_reason(src)
    if problem:
        print(f"[skip] {eid}: {problem}")
        return None
    print(f"[ingest] {eid}  <- {src.name}")
    t0 = time.time()
    meta = probe(src)
    proxy = PROXY_DIR / f"{eid}.mp4"
    if force or not proxy.exists():
        print("  proxy...")
        make_proxy(src, proxy)
    print("  audio + loudness...")
    audio = decode_audio(src)
    energy, peaks = energy_profile(audio)
    print("  scene cuts...")
    cuts = scene_cuts(proxy)
    print("  transcribing...")
    segments = transcribe(audio)
    index = {
        "id": eid, "show": show, "title": src.stem, "source": str(src.resolve()),
        **meta, "segments": segments, "scenes": cuts,
        "energy_hop": 0.5, "energy": energy, "peaks": peaks,
    }
    idx_path.write_text(json.dumps(index), encoding="utf-8")
    print(f"  done in {time.time() - t0:.0f}s: {len(segments)} lines, {len(cuts)} cuts, {len(peaks)} peaks")
    return eid


def reanalyze(eid: str):
    """Recompute loudness peaks for an indexed episode without re-transcribing."""
    p = INDEX_DIR / f"{eid}.json"
    index = json.loads(p.read_text(encoding="utf-8"))
    index["energy"], index["peaks"] = energy_profile(decode_audio(Path(index["source"])))
    p.write_text(json.dumps(index), encoding="utf-8")
    print(f"{eid}: {len(index['peaks'])} peaks")


def guess_show(f: Path, root: Path) -> str:
    # "Show Name - s01e01 - Title.mp4" (PlayOn, Sonarr, Plex style)
    m = re.match(r"(.+?)\s*-\s*[sS]\d{1,2}[eE]\d{1,3}", f.stem)
    if m:
        return m.group(1).strip()
    # otherwise the first folder under the root that isn't "Season N"
    for part in f.relative_to(root).parts[:-1] if f != root else []:
        if not re.match(r"(?i)season\s*\d+|s\d+$", part):
            return part
    return root.name if root.is_dir() else f.parent.name


def scan_inbox(root: Path = None) -> list:
    """Every video in the inbox folder with its status: "indexed", "new" (complete and
    ready to ingest) or "skip" (looks incomplete; reason says why)."""
    root = Path(root or CFG["inbox_dir"])
    out = []
    if not root.is_dir():
        return out
    for f in sorted(root.rglob("*")):
        if f.suffix.lower() not in VIDEO_EXTS:
            continue
        show = guess_show(f, root)
        eid = episode_id(show, f)
        row = {"file": str(f), "name": f.name, "show": show, "episode": eid, "mtime": f.stat().st_mtime}
        if (INDEX_DIR / f"{eid}.json").exists():
            row["status"] = "indexed"
        else:
            reason = incomplete_reason(f)
            row.update(status="skip" if reason else "new", reason=reason)
        out.append(row)
    return out


def ingest(path: str, show: str = None, force: bool = False):
    p = Path(path)
    files = [p] if p.is_file() else sorted(f for f in p.rglob("*") if f.suffix.lower() in VIDEO_EXTS)
    if not files:
        sys.exit(f"No video files found in {p}")
    for f in files:
        try:
            ingest_file(f, show or guess_show(f, p), force)
        except subprocess.CalledProcessError as e:
            print(f"  FAILED {f.name}: {e}")
