"""Render finished video k of a shoot: take k of every line, back to back, full-frame
1080x1920, with karaoke subtitles, the hook text up top for the first seconds and
the call to action over the last line. Take segments are cached, so re-rendering
after a tweak only redoes what changed."""
import hashlib
import json
import re
import subprocess
import time
from pathlib import Path

from adkit.caption import caption_frames
from adkit.config import FFMPEG, FONTS_DIR
from adkit.ingest import video_encoder_args
from adkit.render import ass_color, ass_escape, ass_time, filter_path, style_line, video_duration

from . import assets, fx, layout, pointer, sounds, store, titlefx

W, H, FPS = 1080, 1920, 30
CAP_H = 640  # caption images are 1080x640 (supercut.caption); placed by their centre


def take_zoom(s: dict, take: dict, line_index: int) -> float:
    punch = float(s["style"].get("punch_in") or 1.0)
    return take["zoom"] * (punch if line_index % 2 else 1.0)


def render_take(s: dict, take: dict, zoom: float) -> Path:
    src = next(x for x in s["sources"] if x["id"] == take["src"])
    st = s["style"]
    dur = take["out"] - take["in"]
    cuts = store.take_cuts(take)
    key = json.dumps([src["file"], take["in"], take["out"], zoom, take["pan_x"], take["pan_y"],
                      take["volume"], st["voice_cleanup"], cuts, float(take.get("freeze") or 0),
                      store.speed(s, take), s["style"].get("look"), take.get("bright"), 4])
    out = store.CACHE_DIR / f"take_{hashlib.sha1(key.encode()).hexdigest()[:16]}.mp4"
    if out.exists():
        return out
    zw, zh = int(W * zoom) // 2 * 2, int(H * zoom) // 2 * 2
    # cut-outs (pauses he trimmed away): drop those frames and that audio
    skip = "+".join(f"between(t,{a - take['in']:.3f},{b - take['in']:.3f})" for a, b in cuts)
    vsel = f"select='not({skip})',setpts=N/({FPS}*TB)," if cuts else ""
    asel = f"aselect='not({skip})',asetpts=N/SR/TB," if cuts else ""
    olen = store.take_len(take, s)
    spd = store.speed(s, take)
    vfast = f"setpts=PTS/{spd},fps={FPS}," if spd != 1 else ""
    afast = f"atempo={spd}," if spd != 1 else ""
    frz = float(take.get("freeze") or 0)
    hold = f"tpad=stop_mode=clone:stop_duration={frz + 0.1:.3f}," if frz else ""  # freeze frame
    vf = (f"[0:v:0]fps={FPS},{vsel}{vfast}scale={zw}:{zh}:force_original_aspect_ratio=increase:force_divisible_by=2,"
          f"crop={W}:{H}:x=(iw-ow)*{take['pan_x']}:y=(ih-oh)*{take['pan_y']},setsar=1,{look_vf(s, take)}{hold}format=yuv420p[v]")
    clean = "highpass=f=80,afftdn=nf=-25," if st["voice_cleanup"] else ""
    af = (f"[0:a:0]asetpts=PTS-STARTPTS,{asel}{afast}{clean}volume={take['volume']},aresample=48000,"
          f"afade=t=in:d=0.015,afade=t=out:st={max(0, olen - frz - 0.03):.3f}:d=0.03"
          f"{f',apad=pad_dur={frz + 0.1:.3f}' if frz else ''}[a]")
    tmp = out.with_suffix(".tmp.mp4")
    subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{take['in']:.3f}",
                    "-t", f"{dur:.3f}", "-i", src["file"], "-filter_complex", f"{vf};{af}",
                    "-map", "[v]", "-map", "[a]", *video_encoder_args("final"), "-g", str(FPS),
                    "-c:a", "aac", "-b:a", "192k", "-ac", "2", "-ar", "48000", "-t", f"{olen:.3f}", str(tmp)],
                   check=True)
    tmp.replace(out)
    return out


def cues(words: list, per_line: int) -> list:
    """Group a take's words into subtitle lines of a few words (breaking early at
    sentence ends). Times stay absolute source seconds."""
    out, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        if len(cur) >= per_line or re.search(r"[.!?,]$", w[0]) or i == len(words) - 1:
            out.append(cur)
            cur = []
    return out


def subs_style_line(sub: dict) -> str:
    """The subtitle style: outline, or a box behind the words (sub.box = color), plus an
    optional drop shadow. Wraps short of TikTok's like/comment/share rail."""
    col, out = ass_color(sub["color"]), ass_color(sub.get("outline", "#000000"))
    bold = -1 if sub.get("bold", True) else 0
    if sub.get("box"):
        alpha = int(255 * (1 - float(sub.get("box_alpha", 0.6))))
        boxc = ass_color(sub["box"], alpha)
        border, outline_w, shadow, outc, back = 3, int(sub.get("box_pad", 16)), 0, boxc, boxc
    else:
        border, outline_w = 1, sub.get("outline_w", 6)
        shadow, outc, back = int(sub.get("shadow", 0)), out, ass_color("#000000", 120)
    return (f"Style: Subs,{sub['font']},{sub['size']},{col},{col},{outc},{back},{bold},0,0,0,100,100,0,0,"
            f"{border},{outline_w},{shadow},5,60,200,0,1")


def build_ass(s: dict, parts: list) -> str:
    """parts = [(take, t0 in the video)]"""
    sub = s["style"]["subs"]
    by_line = {l["id"]: l for l in s["script"]}
    hi = ass_color(sub["highlight"])
    events = []
    y = 0

    def add(a, b, text):
        if b > a:
            events.append(f"Dialogue: 0,{ass_time(a)},{ass_time(b)},Subs,,0,0,0,,{{\\an5\\pos(540,{y})}}{text}")

    if sub["on"]:
        for take, t0 in parts:
            if by_line.get(take["line"], {}).get("subs_off"):
                continue  # captions hidden on this line
            # inside TikTok's safe area and off the product (which moves line to line)
            y = int(H * layout.subs_y(s["style"], by_line.get(take["line"])))
            end = t0 + take["out"] - take["in"] - float(take.get("freeze") or 0)  # no subs on the freeze
            rel = lambda t, take=take, t0=t0: t0 + store.take_rel(take, t)
            # words he cut out don't get subtitles
            groups = cues([w for w in take["words"] if not store.in_cut(take, (w[1] + w[2]) / 2)], int(sub["words_per_line"]))
            for gi, g in enumerate(groups):
                words = [w[0].upper() if sub["uppercase"] else w[0] for w in g]
                c0 = max(t0, rel(g[0][1])) if gi else t0
                c1 = min(end, rel(groups[gi + 1][0][1])) if gi + 1 < len(groups) else end
                if not sub["karaoke"]:
                    add(c0, c1, ass_escape(" ".join(words)))
                    continue
                for i in range(len(words)):
                    w0 = c0 if i == 0 else rel(g[i][1])
                    w1 = c1 if i == len(words) - 1 else rel(g[i + 1][1])
                    pop = "\\fscx110\\fscy110" if sub["pop"] else ""
                    text = " ".join(f"{{\\c{hi}{pop}}}{ass_escape(x)}{{\\r}}" if j == i else ass_escape(x)
                                    for j, x in enumerate(words))
                    add(max(c0, w0), min(w1, c1), text)
    return "\n".join([
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}",
        "WrapStyle: 0", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        subs_style_line(sub), "",
        "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        *events, "",
    ])


def overlays(s: dict, n: int, parts: list, total: float) -> list:
    """[(t0, t1, text, caption style, y)] text cards: the user's hook at the start.
    (No call-to-action stickers: nothing goes on screen that isn't in the script.)"""
    st, out = s["style"], []
    hooks = [h for h in s["hooks"] if h.strip()]
    if st["hook"]["on"] and hooks:
        text = hooks[(n - 1) % len(hooks)]
        lines = 1 if len(text) < 24 else 2 if len(text) < 52 else 3
        out.append((0.0, min(total, float(st["hook"]["seconds"])), text,
                    {**st["hook"], "y": 0.5},
                    layout.hook_y(st, lines, next((l for l in s["script"] if parts and l["id"] == parts[0][0]["line"]), None))))
    # a take's title (the game's name) over its freeze frame
    tst = st.get("title") or {}
    for take, t0 in parts:
        frz = float(take.get("freeze") or 0)
        if take.get("title", "").strip() and frz and tst.get("on", True):
            t1 = t0 + take["out"] - take["in"]
            out.append((t1 - frz, t1, take["title"], {**tst, "y": 0.5}, float(tst.get("y", 0.42))))
    return out


def output_path(s: dict, sid: str, n: int) -> Path:
    folder = store.OUTPUT_DIR / re.sub(r'[<>:"/\\|?*]+', "", s["title"] or sid).strip()
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{sid}-v{n:02d}.mp4"


def render_video(sid: str, n: int, progress=lambda msg: None) -> Path:
    s = store.load(sid)
    takes = store.video_takes(s, n)
    if not takes:
        raise ValueError(f"video {n} has no takes")
    order = {l["id"]: i for i, l in enumerate(s["script"])}
    segs, parts, t = [], [], 0.0
    for take in takes:
        progress(f"video {n}: line {order[take['line']] + 1}")
        seg = render_take(s, take, take_zoom(s, take, order[take["line"]]))
        real = video_duration(seg) or (take["out"] - take["in"])
        segs.append(seg)
        parts.append(({**take, "out": take["in"] + real, "cuts": store.take_cuts(take), "_src_out": take["out"],
                       "_spd": store.speed(s, take)}, t))
        t += real
    work = store.CACHE_DIR / f"work_{sid}_{n}"
    work.mkdir(exist_ok=True)
    (work / "list.txt").write_text("".join(f"file '{p.as_posix()}'\n" for p in segs), encoding="utf-8")
    joined = work / "joined.mp4"
    subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0",
                    "-i", str(work / "list.txt"), "-c", "copy", str(joined)], check=True)
    ass = work / "subs.ass"
    ass.write_text(build_ass(s, parts), encoding="utf-8")
    inputs = ["-i", str(joined)]
    chain, last = [], "[0:v]"
    for old in list(work.glob("ov_*.png")) + list(work.glob("as_*.png")):  # (ov_ = text cards, incl. the title dance)
        old.unlink()

    def nxt():
        return inputs.count("-i")  # index of the input about to be added

    # assets (screenshots, product shots, b-roll) sit on the video, under the text
    for j, (ov, a, t0, t1) in enumerate(assets.timings(s, parts, t)):
        k = nxt()
        x, y, wpx = int(W * ov["x"]), int(H * ov["y"]), max(16, int(W * ov["w"]))
        if a["kind"] == "image":
            img, pad = assets.styled(assets.cropped(a), ov, wpx)
            for f, fr in enumerate(assets.pop_frames(img, ov["pop"])):
                fr.save(work / f"as_{j}_{f:02d}.png")
            inputs += ["-framerate", str(FPS), "-i", str(work / f"as_{j}_%02d.png")]
            chain.append(f"[{k}:v]setpts=PTS-STARTPTS+{t0:.3f}/TB[a{j}]")
            chain.append(f"{last}[a{j}]overlay={x - pad}:{y - pad}:eof_action=repeat:"
                         f"enable='between(t,{t0:.3f},{t1:.3f})'[av{j}]")
        else:
            c = a.get("crop")
            crop = f"crop=iw*{c[2] - c[0]:.4f}:ih*{c[3] - c[1]:.4f}:iw*{c[0]:.4f}:ih*{c[1]:.4f}," if c else ""
            inputs += ["-stream_loop", "-1", "-i", a["file"]]
            chain.append(f"[{k}:v]{crop}scale={wpx}:-2,fps={FPS},setpts=PTS-STARTPTS+{t0:.3f}/TB[a{j}]")
            chain.append(f"{last}[a{j}]overlay={x}:{y}:eof_action=pass:"
                         f"enable='between(t,{t0:.3f},{t1:.3f})'[av{j}]")
        last = f"[av{j}]"
    # effects board (TikTok Shop pointers, flash) + the automatic "orange cart" pointer
    for old in list(work.glob("cp_*.png")) + list(work.glob("fx_*.png")):
        old.unlink()
    for j, (t0, t1, kind) in enumerate(fx.events(s, parts, t)):
        frs, ox, oy, hold = fx.frames(kind, t1 - t0, s["style"].get("cart_pointer", {}).get("color", "#FF8A00"))
        for f, fr in enumerate(frs):
            fr.save(work / f"fx_{j}_{f:03d}.png")
        k = nxt()
        inputs += ["-framerate", str(FPS), "-i", str(work / f"fx_{j}_%03d.png")]
        chain.append(f"[{k}:v]setpts=PTS-STARTPTS+{t0:.3f}/TB[p{j}]")
        chain.append(f"{last}[p{j}]overlay={ox}:{oy}:eof_action={'repeat' if hold else 'pass'}"
                     f":enable='between(t,{t0:.3f},{t1:.3f})'[pv{j}]")
        last = f"[pv{j}]"
    # captions go over the effects (a spotlight dims the video, not the words)
    chain.append(f"{last}ass=filename={filter_path(ass)}:fontsdir={filter_path(FONTS_DIR)}[s0]")
    last = "[s0]"
    for i, (t0, t1, text, cst, y) in enumerate(overlays(s, n, parts, t), 1):
        if cst.get("preset") == "deluxe":  # the text hook card: pops in, shine sweep (adcut/titlefx.py)
            for f, img in enumerate(titlefx.hook_frames(text, cst, t1 - t0, H * max(0.17, y))):
                img.save(work / f"ov_{i}_{f:03d}.png")
            k = nxt()
            inputs += ["-framerate", str(FPS), "-i", str(work / f"ov_{i}_%03d.png")]
            chain.append(f"[{k}:v]setpts=PTS-STARTPTS+{t0:.3f}/TB[o{i}]")
            chain.append(f"{last}[o{i}]overlay=0:0:eof_action=repeat:enable='between(t,{t0:.3f},{t1:.3f})'[c{i}]")
            last = f"[c{i}]"
            continue
        if cst.get("anim") == "dance":  # the title dances on the jingle's beats, then lands (adcut/titlefx.py)
            for f, img in enumerate(titlefx.frames(titlefx.card(text, cst), t1 - t0, H * y)):
                img.save(work / f"ov_{i}_{f:03d}.png")
            k = nxt()
            inputs += ["-framerate", str(FPS), "-i", str(work / f"ov_{i}_%03d.png")]
            chain.append(f"[{k}:v]setpts=PTS-STARTPTS+{t0:.3f}/TB[o{i}]")
            chain.append(f"{last}[o{i}]overlay=0:0:eof_action=repeat:enable='between(t,{t0:.3f},{t1:.3f})'[c{i}]")
            last = f"[c{i}]"
            continue
        for f, img in enumerate(caption_frames(text, cst)):
            img.save(work / f"ov_{i}_{f:02d}.png")
        k = nxt()
        inputs += ["-framerate", str(FPS), "-i", str(work / f"ov_{i}_%02d.png")]
        oy = int(H * y - CAP_H / 2)
        chain.append(f"[{k}:v]setpts=PTS-STARTPTS+{t0:.3f}/TB[o{i}]")
        chain.append(f"{last}[o{i}]overlay=0:{oy}:eof_action=repeat:enable='between(t,{t0:.3f},{t1:.3f})'[c{i}]")
        last = f"[c{i}]"
    # soundboard sounds, mixed under his voice, then loudness-normalized together
    mixed = []
    for j, (t0, name, vol) in enumerate(sounds.events(parts, t)):
        k = nxt()
        inputs += ["-i", str(sounds.sound_file(name))]
        ms = int(t0 * 1000)
        chain.append(f"[{k}:a]aresample=48000,aformat=channel_layouts=stereo,volume={vol},adelay={ms}|{ms}[sf{j}]")
        mixed.append(f"[sf{j}]")
    lufs = s['style']['loudness']
    voice = "[0:a]"
    vo = store.voice_for(s, n)
    if vo:  # voiceover video: the voice recording is the sound, the shots are silent
        k = nxt()
        a, f = vo_filter(s, k, t, vo=vo)
        inputs += a
        chain.append(f)
        voice = "[vo]"
    if mixed:
        chain.append(voice + "".join(mixed) + f"amix=inputs={len(mixed) + 1}:normalize=0:duration=first,"
                     f"loudnorm=I={lufs}:TP=-1.5:LRA=11[aout]")
    else:
        chain.append(f"{voice}loudnorm=I={lufs}:TP=-1.5:LRA=11[aout]")
    out = output_path(s, sid, n)
    progress(f"video {n}: subtitles, text, audio")
    subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", *inputs,
                    "-filter_complex", ";".join(chain), "-map", last, "-map", "[aout]",
                    *video_encoder_args("final"), "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
                    "-t", f"{t:.3f}", "-movflags", "+faststart", str(out)], check=True)
    write_post_text(s, sid)
    return out


def write_post_text(s: dict, sid: str):
    """post.txt next to the videos: what to paste into TikTok + which product to tag."""
    p = s["product"]
    folder = output_path(s, sid, 1).parent
    lines = [f"PRODUCT: {p['name']}", f"TIKTOK SHOP LINK: {p['link']}", "",
             "(In TikTok: Add link → Products → search the product above, or paste the link.)", "",
             "DESCRIPTION:", f"{p['description']} {p['hashtags']}".strip(), ""]
    (folder / "post.txt").write_text("\n".join(lines), encoding="utf-8")


# ---------- render bookkeeping + download ----------

def video_sig(s: dict, n: int) -> str:
    """Fingerprint of everything that goes into video n: when it changes, the last
    render is out of date."""
    takes = [{k: v for k, v in t.items() if k not in ("user", "order", "flags", "score")} for t in store.video_takes(s, n)]
    lines = [{k: l.get(k) for k in ("id", "look", "cut_next", "cut_offset", "product_box")} for l in s["script"]]
    key = json.dumps([takes, s["style"], s["hooks"], s["overlays"], s["assets"], lines, n, store.voice_for(s, n)],
                     sort_keys=True, default=str)
    return hashlib.sha1(key.encode()).hexdigest()[:12]


def render_and_record(sid: str, n: int, progress=lambda msg: None) -> Path:
    s = store.load(sid)
    sig = video_sig(s, n)
    out = render_video(sid, n, progress)
    store.update(sid, lambda s: s["renders"].update({str(n): {**s["renders"].get(str(n), {}),
                                                              "file": str(out), "at": time.time(), "sig": sig}}))
    return out


def fresh_render(sid: str, n: int, progress=lambda msg: None) -> Path:
    """The video's render, re-rendering first if it has none or it changed since."""
    s = store.load(sid)
    r = s["renders"].get(str(n)) or {}
    if r.get("file") and Path(r["file"]).is_file() and r.get("sig") == video_sig(s, n):
        return Path(r["file"])
    return render_and_record(sid, n, progress)


def _safe(text: str, limit: int = 70) -> str:
    t = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', " ", text or "")
    t = re.sub(r"\s+", " ", t).strip(" .")
    return t[:limit].rstrip(" .") or "video"


def download_video(sid: str, n: int, progress=lambda msg: None) -> Path:
    """Copy video n into <download dir>/<YYYY-MM-DD>/ as "<shoot> - video NN.mp4",
    with a .txt of what to paste into TikTok (description, hashtags, product link)."""
    import datetime
    import shutil
    src = fresh_render(sid, n, progress)
    s = store.load(sid)
    day = store.DOWNLOAD_DIR / datetime.date.today().isoformat()
    day.mkdir(parents=True, exist_ok=True)
    base = f"{_safe(s['title'] or sid)} - video {n:02d}"
    dest, k = day / f"{base}.mp4", 2
    while dest.exists() and dest.stat().st_size != src.stat().st_size:
        dest, k = day / f"{base} ({k}).mp4", k + 1
    shutil.copy2(src, dest)
    p = s["product"]
    text = "\n\n".join(x for x in (f"{p['description']}".strip(), p["hashtags"].strip()) if x)
    extra = [f"Product to tag: {p['name']}" if p["name"] else "", f"TikTok Shop link: {p['link']}" if p["link"] else ""]
    dest.with_suffix(".txt").write_text("\n\n".join(x for x in [text, "\n".join(e for e in extra if e)] if x) + "\n", encoding="utf-8")
    store.update(sid, lambda s: s["renders"].setdefault(str(n), {}).update(downloaded=str(dest), downloaded_at=time.time()))
    return dest


def vo_filter(s: dict, k: int, total: float, label: str = "vo", vo: dict = None) -> tuple:
    """(ffmpeg input args, filter) for a voiceover (default: the shoot's) as input k, cut, padded to total."""
    vo = vo or s["voiceover"]
    clean = "highpass=f=80,afftdn=nf=-25," if s["style"].get("voice_cleanup") else ""
    args, filts, labs = [], [], []
    for j, g in enumerate(store.vo_segments(vo)):  # each piece: its own input, cut, then joined in order
        src = next(x for x in s["sources"] if x["id"] == g["src"])
        skip = "+".join(f"between(t,{a - g['in']:.3f},{b - g['in']:.3f})" for a, b in g.get("cuts") or [])
        sel = f"aselect='not({skip})',asetpts=N/SR/TB," if skip else ""
        args += ["-ss", f"{g['in']:.3f}", "-t", f"{g['out'] - g['in']:.3f}", "-i", src["file"]]
        filts.append(f"[{k + j}:a:0]asetpts=PTS-STARTPTS,{sel}{clean}volume={g.get('volume', vo.get('volume', 1.0))},"
                     f"aresample=48000,aformat=channel_layouts=stereo[{label}p{j}]")
        labs.append(f"[{label}p{j}]")
    join = f"{''.join(labs)}concat=n={len(labs)}:v=0:a=1," if len(labs) > 1 else labs[0]
    if len(labs) > 1:
        filt = ";".join(filts) + f";{join}apad,atrim=end={total:.3f}[{label}]"
    else:
        filt = filts[0].replace(f"[{label}p0]", f",apad,atrim=end={total:.3f}[{label}]")
    return args, filt


def look_vf(s: dict, take: dict, scale: float = 1.0, tag: str = "") -> str:
    """Brightness + skin smoothing for one take, as a filter chain to splice in (ends with ',')."""
    lk = s["style"].get("look") or {}
    b = float(lk.get("brightness") or 0) + float(take.get("bright") or 0)
    sm = float(lk.get("smooth") or 0)
    out = ""
    if abs(b) > 0.001:
        hi = min(1.0, 1 + b)  # down: highlights come in the most (that's what reads as blown out)
        out += f"curves=all='0/0 0.5/{0.5 + 0.6 * b:.3f} 1/{hi:.3f}',"
    if sm > 0.001:
        sig = (3 + 9 * sm) * scale
        out += (f"split[lk{tag}a][lk{tag}b];[lk{tag}b]bilateral=sigmaS={sig:.2f}:sigmaR={0.03 + 0.07 * sm:.3f}[lk{tag}c];"
                f"[lk{tag}a][lk{tag}c]blend=all_mode=normal:all_opacity={min(1.0, 0.45 + 0.55 * sm):.2f},")
    return out
