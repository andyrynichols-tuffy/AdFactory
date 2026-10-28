"""Render an edit file to a 1080x1920 TikTok MP4.

Layout (3 bands of 640px): caption | video | subtitles.
Each clip renders to a cached segment (re-renders after tweaks only redo
changed clips); segments are concatenated, then captions and subtitles are
burned in with one ASS file, and audio is loudness-normalized."""
import hashlib
import json
import re
import subprocess
import time
from pathlib import Path

from . import edl as edlmod
from . import library
from .caption import caption_frames, effective_style
from .config import CACHE_DIR, FFMPEG, FFPROBE, FONTS_DIR, RENDERS_DIR
from .sfx import HIT, LIBRARY, sfx_file
from .ingest import video_encoder_args

W, H, BAND, FPS = 1080, 1920, 640, 30


# ---------- ASS subtitles ----------

def ass_color(hex_rgb: str, alpha: int = 0) -> str:
    h = hex_rgb.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def ass_time(t: float) -> str:
    t = max(0.0, t)
    cs = int(round(t * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def ass_escape(s: str) -> str:
    return s.replace("\\", "/").replace("{", "(").replace("}", ")").replace("\n", "\\N")


def style_line(name, st, align=5):
    bold = -1
    return (f"Style: {name},{st['font']},{st['size']},{ass_color(st['color'])},{ass_color(st['color'])},"
            f"{ass_color(st['outline'])},&H80000000,{bold},0,0,0,100,100,0,0,1,{st['outline_w']},0,"
            f"{align},70,70,0,1")


def build_ass(edl: dict) -> str:
    st = edl["style"]
    cap, sub = st["caption"], st["subs"]
    sub_y = int(2 * BAND + BAND * sub["y"])
    hi = ass_color(sub["highlight"])
    events = []

    def add(t0, t1, style, text):
        if t1 > t0:
            events.append(f"Dialogue: 0,{ass_time(t0)},{ass_time(t1)},{style},,0,0,0,,{text}")

    # (captions are drawn as images, see caption_runs)

    # subtitles: one event per active word for the karaoke highlight
    t = 0.0
    for c in edl["clips"]:
        d = (c["out"] - c["in"]) / c["speed"]
        for cue in library.clip_cues(c, sub["words_per_line"]):
            words = [w[0].upper() if sub["uppercase"] else w[0] for w in cue["words"]]
            c0 = t + cue["start"] / c["speed"]
            c1 = min(t + d, t + cue["end"] / c["speed"])
            pos = f"{{\\an5\\pos(540,{sub_y})}}"
            if not sub["karaoke"] or not words:
                text = cue["text"].upper() if sub["uppercase"] else cue["text"]
                add(c0, c1, "Subs", pos + ass_escape(text))
                continue
            for i in range(len(words)):
                w0 = c0 if i == 0 else t + cue["words"][i][1] / c["speed"]
                w1 = c1 if i == len(words) - 1 else t + cue["words"][i + 1][1] / c["speed"]
                pop = "\\fscx112\\fscy112" if sub["pop"] else ""
                parts = [f"{{\\c{hi}{pop}}}{ass_escape(w)}{{\\r}}" if j == i else ass_escape(w)
                         for j, w in enumerate(words)]
                add(w0, min(w1, c1), "Subs", pos + " ".join(parts))
        t += d

    return "\n".join([
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}",
        "WrapStyle: 0", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        style_line("Caption", cap), style_line("Subs", sub), "",
        "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        *events, "",
    ])


def caption_runs(edl: dict) -> list:
    """[(t0, t1, text, style)] merging consecutive clips with the same caption+style.
    Title-card buffers show nothing, except in rankings, where the list stays up and
    already highlights the entry that's coming."""
    t, runs, k = 0.0, [], 0
    ranking = edlmod.post_kind(edl) == "ranking"
    for c in edl["clips"]:
        d = (c["out"] - c["in"]) / c["speed"]
        if c.get("card") and not ranking:
            text, st = "", {}
        else:
            text, st = edlmod.caption_for(edl, k, c)
        if not c.get("card"):
            k += 1
        if runs and runs[-1][2] == text and runs[-1][3] == st:
            runs[-1][1] = t + d
        else:
            runs.append([t, t + d, text, st])
        t += d
    return [r for r in runs if r[2]]


def counter_runs(edl: dict) -> list:
    """An on-screen tally (style.counter = {"text": "Brody count: *{n}*", "style": {...}}):
    each clip's "marks" (seconds from its in-point) bump the count by one, right on the word."""
    cs = edl["style"].get("counter")
    if not cs:
        return []
    from .caption import effective_style
    t, marks = 0.0, []
    for c in edl["clips"]:
        marks += [t + m / c["speed"] for m in c.get("marks") or []]
        t += (c["out"] - c["in"]) / c["speed"]
    st = effective_style(edl["style"]["caption"], cs.get("style"))
    edges = [0.0] + sorted(marks) + [t]
    start = int(cs.get("start", 0))
    return [(edges[n], edges[n + 1], cs.get("text", "{n}").format(n=start + n), st)
            for n in range(len(edges) - 1) if edges[n + 1] > edges[n] and (n or not cs.get("hide_zero"))]


def sfx_events(edl: dict) -> list:
    """[(start_time, name, volume)]: cut sounds at clip boundaries plus per-clip cues,
    shifted so each sound's hit lands on its mark."""
    tr = edl["style"]["transition"]
    t, events = 0.0, []
    for i, c in enumerate(edl["clips"]):
        if i and c.get("transition") != "none" and tr.get("sfx") in LIBRARY:
            events.append((t - HIT.get(tr["sfx"], 0), tr["sfx"], tr["sfx_volume"]))
        for cue in c.get("sfx") or []:
            at = t + cue["at"] / c["speed"]
            events.append((at - HIT.get(cue["name"], 0), cue["name"], cue.get("volume", 0.8),
                           cue.get("dur"), cue.get("fade")))
        t += (c["out"] - c["in"]) / c["speed"]
    return [(max(0.0, e[0]), *e[1:]) if len(e) > 3 else (max(0.0, e[0]), e[1], e[2], None, None) for e in events]


# ---------- video ----------

def ffcolor(hex_rgb: str) -> str:
    return "0x" + hex_rgb.lstrip("#")


def filter_path(p: Path) -> str:
    return "'" + str(p).replace("\\", "/").replace(":", "\\:") + "'"


_audio_cache = {}


def has_audio(src: str) -> bool:
    if src not in _audio_cache:
        out = subprocess.run([FFPROBE, "-v", "error", "-select_streams", "a", "-show_entries",
                              "stream=index", "-of", "csv=p=0", src], capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
        _audio_cache[src] = bool(out.strip())
    return _audio_cache[src]


def video_duration(p: Path) -> float:
    out = subprocess.run([FFPROBE, "-v", "error", "-select_streams", "v:0", "-count_packets",
                          "-show_entries", "stream=nb_read_packets,r_frame_rate", "-of", "csv=p=0", str(p)],
                         capture_output=True, text=True).stdout.strip().split(",")
    try:
        num, den = out[0].split("/")
        return int(out[1]) * int(den) / int(num)
    except (ValueError, IndexError, ZeroDivisionError):
        return 0.0


_seg_locks, _seg_locks_guard = {}, __import__("threading").Lock()


def render_segment(clip: dict, style: dict, first: bool = False) -> Path:
    """One clip as a finished segment (cached by content). Safe to call from several threads:
    the same segment twice in one post is built once."""
    key = json.dumps([clip, style, first], sort_keys=True, default=str)
    with _seg_locks_guard:
        lock = _seg_locks.setdefault(key, __import__("threading").Lock())
    with lock:
        return _render_segment(clip, style, first)


def _render_segment(clip: dict, style: dict, first: bool = False) -> Path:
    ep = library.episode(clip["episode"])
    src = ep["source"]
    bgs, tr = style["background"], style["transition"]
    flash = tr["flash"] and not first
    square = style.get("layout") == "square"  # fan-edit look: 1:1 picture, black above and below
    key = json.dumps([src, clip["in"], clip["out"], clip["zoom"], clip["pan_x"], clip["pan_y"],
                      clip["speed"], clip["volume"], style["top_bg"], style["mid_bg"], style["bottom_bg"],
                      bgs, flash, clip.get("fade", 0), tr.get("audio_fade", 0.04), 3]
                     + (["sq"] if square else []))
    out = CACHE_DIR / f"seg_{hashlib.sha1(key.encode()).hexdigest()[:16]}.mp4"
    if out.exists():
        return out
    sp, dur = clip["speed"], clip["out"] - clip["in"]
    odur = dur / sp
    mid_h, mid_y = (W, (H - W) // 2) if square else (BAND, BAND)
    zw = max(2, int(W * clip["zoom"] * (16 / 9 if square else 1)) // 2 * 2)
    fg = (f"scale={zw}:-2,crop=w=min(iw\\,{W}):h=min(ih\\,{mid_h}):"
          f"x=(iw-ow)*{clip['pan_x']}:y=(ih-oh)*{clip['pan_y']}[v];")
    src_v = f"[0:v:0]setpts=(PTS-STARTPTS)/{sp},fps={FPS},setsar=1"
    if bgs["mode"] == "blur" and not square:
        # blurred, saturated, darkened copy of the clip fills the whole 9:16 frame
        fc = (f"{src_v},split=2[s1][s2];"
              f"[s1]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,boxblur=10:2,"
              f"eq=saturation={bgs['saturation']},scale={W}:{H},"
              f"drawbox=x=0:y=0:w=iw:h=ih:color={ffcolor(bgs.get('tint', '#000000'))}@{bgs['darken']}:t=fill[bg];"
              f"[s2]{fg}")
    else:
        fc = (f"color=c={ffcolor(style['mid_bg'])}:s={W}x{H}:r={FPS}:d={odur:.3f},"
              f"drawbox=x=0:y=0:w={W}:h={BAND}:color={ffcolor(style['top_bg'])}:t=fill,"
              f"drawbox=x=0:y={2 * BAND}:w={W}:h={BAND}:color={ffcolor(style['bottom_bg'])}:t=fill[bg];"
              f"{src_v}," + fg)
    fc += f"[bg][v]overlay=x=(W-w)/2:y={mid_y}+({mid_h}-h)/2:shortest=1"
    if flash:
        fc += (f"[base];color=c=white:s={W}x{H}:r={FPS}:d=0.25,format=rgba,"
               f"fade=t=out:st=0:d=0.22:alpha=1,colorchannelmixer=aa=0.8[fl];"
               f"[base][fl]overlay=eof_action=pass")
    if clip.get("fade"):  # title card: quick fade in and out
        f = clip["fade"]
        fc += f",fade=t=in:st=0:d={f:.3f},fade=t=out:st={max(0, odur - f):.3f}:d={f:.3f}"
    fc += ",format=yuv420p[vout];"
    inputs = ["-ss", f"{clip['in']:.3f}", "-t", f"{dur:.3f}", "-i", src]
    # soft audio edges (style.transition.audio_fade): cuts between clips don't click or jump
    af = min(float(tr.get("audio_fade", 0.04)), odur / 3)
    af_in = af if af > 0.04 else 0.02
    if has_audio(src):
        fc += (f"[0:a:0]asetpts=PTS-STARTPTS,atempo={sp},volume={clip['volume']},aresample=48000,"
               f"afade=t=in:d={af_in:.3f},afade=t=out:st={max(0, odur - af):.3f}:d={af:.3f}[aout]")
    else:
        inputs += ["-f", "lavfi", "-t", f"{odur:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
        fc += "[1:a]anull[aout]"
    tmp = out.with_suffix(".tmp.mp4")
    cmd = [FFMPEG, "-y", "-hide_banner", "-loglevel", "error", *inputs, "-filter_complex", fc,
           "-map", "[vout]", "-map", "[aout]", *video_encoder_args("final"), "-g", str(FPS),
           "-c:a", "aac", "-b:a", "192k", "-ac", "2", "-ar", "48000", "-t", f"{odur:.3f}", str(tmp)]
    subprocess.run(cmd, check=True)
    tmp.replace(out)
    return out


def export_clips(name: str, min_seconds: float = 0, progress=print) -> list:
    """Render each clip (optionally only those longer than min_seconds) as its own video."""
    edl = edlmod.load(name)
    out_dir = RENDERS_DIR / f"{edlmod.safe_name(name)}_clips"
    out_dir.mkdir(exist_ok=True)
    outs = []
    for i, c in enumerate(edl["clips"], 1):
        if (c["out"] - c["in"]) / c["speed"] <= min_seconds:
            continue
        single = {**edl, "clips": [c]}
        out = out_dir / f"clip{i:02d}_{re.sub(r'[^a-z0-9]+', '-', (c.get('caption') or 'clip').lower()).strip('-')[:40]}.mp4"
        progress(f"clip {i} -> {out.name}")
        render(name, edl=single, out=out, work_suffix=f"clip{i}")
        outs.append(out)
    return outs


def render(name: str, progress=lambda done, total, msg: None, edl: dict = None,
           out: Path = None, work_suffix: str = "") -> Path:
    edl = edl or edlmod.load(name)
    problems = edlmod.check(edl)
    if problems:
        raise ValueError("; ".join(problems))
    if not edl["clips"]:
        raise ValueError("no clips")
    edl = {**edl, "clips": edlmod.timeline(edl)}  # title-card buffers inserted between clips
    work = CACHE_DIR / f"work_{edlmod.safe_name(name)}{work_suffix}"
    work.mkdir(exist_ok=True)
    total = len(edl["clips"]) + 1
    from concurrent.futures import ThreadPoolExecutor
    from . import resources
    n_workers = resources.workers()  # several at once when the PC is free; 1 while PlayOn records
    done = [0]

    def seg(ic):
        i, c = ic
        s = render_segment(c, edl["style"], first=(i == 0 or c.get("transition") == "none"))
        done[0] += 1
        progress(done[0], total, f"clip {done[0]}/{len(edl['clips'])}")
        return s
    with ThreadPoolExecutor(n_workers) as pool:
        segs = list(pool.map(seg, enumerate(edl["clips"])))
    # time everything by the segments' real lengths (frame rounding adds up over a montage)
    clips = []
    for c, s in zip(edl["clips"], segs):
        real = video_duration(s)
        clips.append({**c, "out": c["in"] + real * c["speed"]} if real else c)
    edl = {**edl, "clips": clips}
    progress(total - 1, total, "captions, subtitles, audio")
    (work / "list.txt").write_text("".join(f"file '{s.as_posix()}'\n" for s in segs), encoding="utf-8")
    joined = work / "joined.mp4"
    subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0",
                    "-i", str(work / "list.txt"), "-c", "copy", str(joined)], check=True)
    ass = work / "overlay.ass"
    ass.write_text(build_ass(edl), encoding="utf-8")
    out = out or RENDERS_DIR / f"{edlmod.safe_name(name)}_{time.strftime('%Y%m%d-%H%M%S')}.mp4"
    lufs = edl["style"]["audio"]["loudness"]
    inputs, chain, last = ["-i", str(joined)], [], "[0:v]"
    chain.append(f"{last}ass=filename={filter_path(ass)}:fontsdir={filter_path(FONTS_DIR)}[s0]")
    last = "[s0]"
    for old in [*work.glob("caption_*.png"), *work.glob("context_*.png")]:
        old.unlink()
    for i, (t0, t1, text, st) in enumerate(caption_runs(edl), 1):
        # pop-in frames; the last frame is held until the caption ends
        for f, img in enumerate(caption_frames(text, st)):
            img.save(work / f"caption_{i}_{f:02d}.png")
        inputs += ["-framerate", str(FPS), "-i", str(work / f"caption_{i}_%02d.png")]
        chain.append(f"[{i}:v]setpts=PTS-STARTPTS+{t0:.3f}/TB[cap{i}]")
        chain.append(f"{last}[cap{i}]overlay=0:{int(st.get('layer_y', 0))}:eof_action=repeat:enable='between(t,{t0:.3f},{t1:.3f})'[c{i}]")
        last = f"[c{i}]"
    for j, (t0, t1, text, st) in enumerate(counter_runs(edl)):
        for f, img in enumerate(caption_frames(text, st)):
            img.save(work / f"caption_n{j}_{f:02d}.png")
        k = inputs.count("-i")
        inputs += ["-framerate", str(FPS), "-i", str(work / f"caption_n{j}_%02d.png")]
        chain.append(f"[{k}:v]setpts=PTS-STARTPTS+{t0:.3f}/TB[cnt{j}]")
        chain.append(f"{last}[cnt{j}]overlay=0:{int(st.get('layer_y', 0))}:eof_action=repeat:enable='between(t,{t0:.3f},{t1:.3f})'[n{j}]")
        last = f"[n{j}]"
    # ranking entries: setup line at the top of the bottom band, fading in with the clip
    t = 0.0
    for j, c in enumerate(edl["clips"]):
        d = (c["out"] - c["in"]) / c["speed"]
        ctx = None if c.get("card") else edlmod.context_for(edl, c)
        if ctx:
            img = caption_frames(ctx[0], {**ctx[1], "anim": "fade"})
            for f, im in enumerate(img):
                im.save(work / f"context_{j}_{f:02d}.png")
            k = inputs.count("-i")
            inputs += ["-framerate", str(FPS), "-i", str(work / f"context_{j}_%02d.png")]
            chain.append(f"[{k}:v]setpts=PTS-STARTPTS+{t:.3f}/TB[ctx{j}]")
            chain.append(f"{last}[ctx{j}]overlay=0:{2 * BAND}:eof_action=repeat:enable='between(t,{t:.3f},{t + d:.3f})'[x{j}]")
            last = f"[x{j}]"
        t += d
    # sound effects mixed under the program audio, then loudness-normalized
    events = sfx_events(edl)
    mixed = []
    for name in sorted({e[1] for e in events}):
        mine = [(s, v, d, f) for s, n, v, d, f in events if n == name]
        k = inputs.count("-i")  # index of the input about to be added
        inputs += ["-i", str(sfx_file(name))]
        chain.append(f"[{k}:a]asplit={len(mine)}" + "".join(f"[{name}{j}]" for j in range(len(mine))))
        for j, (s, v, d, f) in enumerate(mine):
            ms = int(s * 1000)
            shape = ""
            if d:  # trimmed to the card, fading in/out with it
                f = f or 0
                shape = f"atrim=0:{d:.3f},afade=t=in:d={f:.3f},afade=t=out:st={max(0, d - f):.3f}:d={f:.3f},"
            chain.append(f"[{name}{j}]{shape}volume={v},adelay={ms}|{ms}[m{len(mixed)}]")
            mixed.append(f"[m{len(mixed)}]")
    if mixed:
        chain.append("[0:a]" + "".join(mixed) + f"amix=inputs={len(mixed) + 1}:normalize=0:duration=first,"
                     f"loudnorm=I={lufs}:TP=-1.5:LRA=11[aout]")
    else:
        chain.append(f"[0:a]loudnorm=I={lufs}:TP=-1.5:LRA=11[aout]")
    subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", *inputs,
                    "-filter_complex", ";".join(chain), "-map", last, "-map", "[aout]",
                    *video_encoder_args("final"),
                    "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", str(out)], check=True)
    progress(total, total, "done")
    return out
