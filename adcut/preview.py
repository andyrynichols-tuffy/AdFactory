"""Editor previews: each video pre-rendered as one small continuous file (540x960, framed,
cut-outs dropped, the show audio at each take's volume), so the editor plays it straight
through instead of seeking the proxy at every take and cut. Subtitles, assets, effects and
sounds stay live in the editor, so a preview only goes stale when the footage changes.

Each take's length is rounded to whole frames and the segment offsets are returned, so the
editor maps preview time back to source time take by take (no drift over a long video)."""
import hashlib
import json
import os
import queue
import subprocess
import threading
import time
from pathlib import Path

from supercut.config import FFMPEG, FFPROBE
from supercut.ingest import video_encoder_args

from . import store
from .render import look_vf

PW, PH, FPS = 540, 960, 30
VERSION = 1
PREVIEW_DIR = store.AD_DATA / "previews"
_q = queue.Queue()
_pending = set()
_failed = {}
_lock = threading.Lock()
_audio = {}


def _zoom(s, t, line_ids):
    punch = float(s["style"].get("punch_in") or 1.0)
    i = line_ids.index(t["line"]) if t["line"] in line_ids else 0
    return t["zoom"] * (punch if i % 2 else 1.0)


def spec(s: dict, n: int) -> list:
    """What video n's footage is made of: per take, the fields that change its picture/sound."""
    line_ids = [l["id"] for l in s["script"]]
    out = []
    for t in store.video_takes(s, n):
        out.append({"id": t["id"], "src": t["src"], "in": t["in"], "out": t["out"], "cuts": store.take_cuts(t),
                    "zoom": round(_zoom(s, t, line_ids), 4), "pan_x": t["pan_x"], "pan_y": t["pan_y"],
                    "volume": t["volume"], "freeze": float(t.get("freeze") or 0), "speed": store.speed(s, t),
                    "look": s["style"].get("look"), "bright": float(t.get("bright") or 0)})
    return out


def _name(sid, n, sp, vo=None):
    h = hashlib.sha1(json.dumps([VERSION, sp, vo]).encode()).hexdigest()[:12]
    return f"{sid}-v{n}-{h}.mp4"


def _segs(sp):
    off, out = 0.0, []
    for t in sp:
        frames = max(1, round(((t["out"] - t["in"] - sum(b - a for a, b in t["cuts"])) / t.get("speed", 1)
                              + t.get("freeze", 0)) * FPS))
        out.append({**t, "off": round(off, 4), "len": frames / FPS, "frames": frames})
        off += frames / FPS
    return out


def _has_audio(path):
    if path not in _audio:
        r = subprocess.run([FFPROBE, "-v", "error", "-select_streams", "a",
                            "-show_entries", "stream=index", "-of", "csv=p=0", path], capture_output=True, text=True)
        _audio[path] = bool(r.stdout.strip())
    return _audio[path]


def build(s: dict, sp: list, dst: Path, vo: dict = None):
    srcs = {x["id"]: x for x in s["sources"]}
    args, parts, labels = [], [], []
    for k, t in enumerate(_segs(sp)):
        proxy = str(store.PROXY_DIR / f"{srcs[t['src']]['key']}.mp4")
        args += ["-ss", f"{t['in']:.3f}", "-t", f"{t['out'] - t['in']:.3f}", "-i", proxy]
        skip = "+".join(f"between(t,{a - t['in']:.3f},{b - t['in']:.3f})" for a, b in t["cuts"])
        vsel = f"select='not({skip})',setpts=N/({FPS}*TB)," if skip else ""
        asel = f"aselect='not({skip})',asetpts=N/SR/TB," if skip else ""
        spd = t.get("speed", 1)
        vsel += f"setpts=PTS/{spd},fps={FPS}," if spd != 1 else ""
        asel += f"atempo={spd}," if spd != 1 else ""
        zw, zh = int(PW * t["zoom"]) // 2 * 2, int(PH * t["zoom"]) // 2 * 2
        end = t["frames"] / FPS
        parts.append(f"[{k}:v:0]fps={FPS},{vsel}scale={zw}:{zh}:force_original_aspect_ratio=increase,"
                     f"crop={PW}:{PH}:x=(iw-ow)*{t['pan_x']}:y=(ih-oh)*{t['pan_y']},setsar=1,"
                     f"{look_vf(s, t, PW / 1080, str(k))}format=yuv420p,"
                     f"tpad=stop_mode=clone:stop_duration={1 + t.get('freeze', 0):.3f},trim=end_frame={t['frames']},setpts=PTS-STARTPTS[v{k}]")
        if _has_audio(proxy):
            parts.append(f"[{k}:a:0]asetpts=PTS-STARTPTS,{asel}volume={t['volume']},aresample=48000,"
                         f"aformat=channel_layouts=stereo,apad,atrim=end={end:.4f},asetpts=PTS-STARTPTS[a{k}]")
        else:
            parts.append(f"anullsrc=r=48000:cl=stereo,atrim=end={end:.4f}[a{k}]")
        labels.append(f"[v{k}][a{k}]")
    parts.append(f"{''.join(labels)}concat=n={len(labels)}:v=1:a=1[v][a]")
    alab = "[a]"
    if vo:  # the voice recording replaces the shots' own sound
        from .render import vo_filter
        prox = [{**x, "file": str(store.PROXY_DIR / f"{x['key']}.mp4")} for x in s["sources"] if x.get("key")]
        a, f = vo_filter({**s, "sources": prox},
                         len(labels), sum(t["frames"] for t in _segs(sp)) / FPS, vo=vo)
        args += a
        parts.append(f)
        parts.append("[a]anullsink")  # the shots' own (silent) sound isn't used
        alab = "[vo]"
    tmp = dst.with_suffix(f".{os.getpid()}-{threading.get_ident()}.tmp.mp4")  # never shared by two builds
    subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", *args, "-filter_complex", ";".join(parts),
                    "-map", "[v]", "-map", alab, *video_encoder_args("proxy"), "-g", "15", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(tmp)],
                   check=True, capture_output=True)
    tmp.replace(dst)


def _worker():
    while True:
        sid, n, name = _q.get()
        try:
            s = store.load(sid)
            sp = spec(s, n)
            if _name(sid, n, sp, store.voice_for(s, n)) == name:  # still what the video is
                build(s, sp, PREVIEW_DIR / name, store.voice_for(s, n))
                for old in PREVIEW_DIR.glob(f"{sid}-v{n}-*.mp4"):
                    if old.name != name:
                        old.unlink(missing_ok=True)
        except Exception as e:  # noqa: BLE001  (a broken preview just means live playback)
            _failed[name] = (time.time(), str(e)[-300:])
        finally:
            with _lock:
                _pending.discard(name)


threading.Thread(target=_worker, daemon=True, name="previews").start()


def status(sid: str) -> dict:
    """Every video's preview: ready (url + segment offsets) or queued for building."""
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    s = store.load(sid)
    out = {}
    for v in store.videos(s)["videos"]:
        n = v["n"]
        if not v["takes"]:
            continue
        sp = spec(s, n)
        name = _name(sid, n, sp, store.voice_for(s, n))
        if (PREVIEW_DIR / name).exists():
            out[n] = {"state": "ready", "url": f"/previews/{name}", "segs": _segs(sp)}
        elif name in _failed and time.time() - _failed[name][0] < 30:  # retried after a bit
            out[n] = {"state": "failed", "error": _failed[name][1]}
        else:
            with _lock:
                if name not in _pending:
                    _pending.add(name)
                    _q.put((sid, n, name))
            out[n] = {"state": "building"}
    return out
