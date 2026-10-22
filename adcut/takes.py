"""Raw footage -> takes.

1. prepare_source: editor proxy + word-timed transcript per raw file (cached by file).
2. guess_script: no script pasted? Lines said several times are the script.
3. match: find every attempt at every script line, grade it (good / close / flub /
   incomplete / paused) and stack the usable ones in the order they were filmed."""
import json
import re
import subprocess
from difflib import SequenceMatcher
from pathlib import Path

from supercut.config import FFMPEG
from supercut.ingest import decode_audio, probe, video_encoder_args, whisper_model

from . import store

# ---------- per-source prep ----------


def make_proxy(src: Path, dst: Path):
    # short side 540, keyframe every half second so stacks of takes seek fast
    vf = "scale='if(gt(iw,ih),-2,540)':'if(gt(iw,ih),540,-2)',fps=30"
    tmp = dst.with_suffix(".tmp.mp4")
    subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-i", str(src),
                    "-map", "0:v:0", "-map", "0:a:0?", "-vf", vf, *video_encoder_args("proxy"), "-g", "15",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k", "-ac", "2",
                    "-movflags", "+faststart", str(tmp)], check=True)
    tmp.replace(dst)


# Whisper quietly "cleans up" speech; a prompt full of disfluencies makes it keep
# the ums, restarts and repeats that tell a flubbed take from a clean one.
FILLER_PROMPT = "Umm, so, uh, I mean, like, wait, sorry, let me, let me start over. Okay, um, hmm."


def speech_chunks(audio, sr: int = 16000) -> list:
    """(start, end) seconds of each stretch of speech between pauses. Each is
    transcribed on its own: fed the whole shoot, Whisper merges or drops takes that
    repeat the same words (it thinks it's looping)."""
    from faster_whisper.vad import VadOptions, get_speech_timestamps
    ts = get_speech_timestamps(audio, VadOptions(min_silence_duration_ms=500, speech_pad_ms=200))
    chunks = []
    for t in ts:
        a, b = t["start"] / sr, t["end"] / sr
        if chunks and a - chunks[-1][1] < 0.3:
            chunks[-1][1] = b
        else:
            chunks.append([a, b])
    return chunks


def transcribe_words(src: Path, progress=print) -> list:
    audio = decode_audio(src)
    from supercut import resources
    sr, model, out = 16000, whisper_model(), []
    chunks = speech_chunks(audio)
    with resources.gpu_slot(progress):  # one GPU job at a time on the PC, never while PlayOn records
        for n, (a, b) in enumerate(chunks):
            resources.yield_to_playon(progress)
            if n % 20 == 0:
                progress(f"{src.name}: transcribing {n + 1}/{len(chunks)}")
            segs, _ = model.transcribe(
                audio[int(a * sr):int(b * sr)], language="en", word_timestamps=True, vad_filter=False,
                condition_on_previous_text=False, initial_prompt=FILLER_PROMPT,
            )
            out += [[w.word.strip(), round(a + w.start, 2), round(a + w.end, 2), round(w.probability, 2)]
                    for s in segs for w in (s.words or []) if w.word.strip()]
    return out


def prepare_source(path: Path, progress=print) -> dict:
    """Probe + proxy + transcript for one raw file (skips work already cached)."""
    key = store.source_key(path)
    meta = probe(path)
    proxy = store.PROXY_DIR / f"{key}.mp4"
    if not proxy.exists():
        progress(f"{path.name}: making preview copy")
        make_proxy(path, proxy)
    wfile = store.WORDS_DIR / f"{key}.json"
    if not wfile.exists():
        wfile.write_text(json.dumps(transcribe_words(path, progress)), encoding="utf-8")
    return {"key": key, **meta}


def words_for(key: str) -> list:
    p = store.WORDS_DIR / f"{key}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


# ---------- text normalizing ----------

_ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen " \
        "fifteen sixteen seventeen eighteen nineteen".split()
_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()


def num_words(n: int) -> list:
    if n < 20:
        return [_ONES[n]]
    if n < 100:
        return [_TENS[n // 10]] + (num_words(n % 10) if n % 10 else [])
    if n < 1000:
        return num_words(n // 100) + ["hundred"] + (num_words(n % 100) if n % 100 else [])
    for size, name in ((10 ** 9, "billion"), (10 ** 6, "million"), (1000, "thousand")):
        if n >= size:
            return num_words(n // size) + [name] + (num_words(n % size) if n % size else [])
    return [str(n)]


CONTRACTIONS = {"n't": " not", "'ve": " have", "'re": " are", "'ll": " will", "'m": " am", "'d": " would"}


def tokens(text: str) -> list:
    """Comparable tokens: lowercase, no punctuation, digits spelled out, contractions
    opened, so "24/7" matches "twenty four seven" and "I've" matches "I have"."""
    out = []
    text = text.lower().replace("’", "'").replace("%", " percent").replace("&", " and ").replace("$", " ")
    text = re.sub(r"\b(can|won)'t\b", lambda m: {"can": "can not", "won": "will not"}[m.group(1)], text)
    text = re.sub(r"(n't|'ve|'re|'ll|'m|'d)\b", lambda m: CONTRACTIONS[m.group(1)], text)
    for raw in re.split(r"[\s\-/]+", text):
        w = re.sub(r"[^a-z0-9']", "", raw).strip("'")
        if not w:
            continue
        if w.isdigit() and len(w) < 10:
            out += num_words(int(w))
        else:  # numbers glued to other characters ("6'2") are numbers too
            for piece in re.findall(r"[a-z]+(?:'[a-z]+)?|\d+", w):
                out += num_words(int(piece)) if piece.isdigit() and len(piece) < 10 else [piece]
    return out


# Restart words = he stopped and fixed it: the take is a flub. Hesitations are only
# flagged (a little natural "um" can even help engagement).
RESTARTS = {"sorry", "wait", "oops", "ugh", "shoot", "dang", "crap", "whoops", "restart", "redo"}
RESTART_PHRASES = ["start over", "hold on", "let me start", "let me try", "one more time",
                   "what is it", "what was it", "from the top", "take two"]
HESITATIONS = {"um", "umm", "uh", "uhh", "uhm", "erm", "hmm", "mm"}
FILLERS = RESTARTS | HESITATIONS


# ---------- units ----------

def units(words: list, gap: float = 0.35) -> list:
    """Split a source's words at pauses and sentence ends: the building blocks a
    take is made of. Each unit = {i0, i1 (inclusive word indexes), toks}."""
    out, start = [], 0
    for i, w in enumerate(words):
        nxt = words[i + 1] if i + 1 < len(words) else None
        if nxt is None or nxt[1] - w[2] > gap or re.search(r"[.!?]$", w[0]):
            out.append({"i0": start, "i1": i})
            start = i + 1
    for u in out:
        u["toks"] = tokens(" ".join(w[0] for w in words[u["i0"]:u["i1"] + 1]))
    return [u for u in out if u["toks"]]


def ratio(a: list, b: list) -> float:
    """Word-level similarity, or letter-level when that's higher, so Whisper spelling
    the same words two ways ("Waffle Knit" / "WaffleNet") still counts as a match."""
    r = SequenceMatcher(None, a, b, autojunk=False).ratio()
    if r < 0.95:
        r = max(r, 0.97 * SequenceMatcher(None, "".join(a), "".join(b), autojunk=False).ratio())
    return r


def split_restarts(words: list, us: list, starts: list) -> list:
    """Split a unit where he starts the same line over without pausing ("stop
    spending…, stop spending…"): at a word where a line's opening words begin again
    and the unit also began with them, or where a line's opening comes up two or
    more times ("and they're running out… but they're running, but they're running
    out of stock…"). starts = each line's first 3 tokens."""
    wt = [tokens(w[0]) for w in words]
    out = []
    for u in us:
        cuts = [u["i0"]]
        opens = {}  # line opening -> word positions where it begins inside this unit
        for i in range(u["i0"], u["i1"] + 1):
            ahead = [t for k in range(i, min(i + 4, u["i1"] + 1)) for t in wt[k]][:3]
            if len(ahead) == 3 and ahead in starts:
                opens.setdefault(tuple(ahead), []).append(i)
        for i in range(u["i0"] + 1, u["i1"] + 1):
            ahead = [t for k in range(i, min(i + 4, u["i1"] + 1)) for t in wt[k]][:3]
            head = [t for k in range(cuts[-1], min(cuts[-1] + 4, i)) for t in wt[k]][:3]
            again = len(opens.get(tuple(ahead), [])) >= 2  # same opening twice in one breath = restarts
            if len(ahead) == 3 and ahead in starts and (ahead == head or again):
                cuts.append(i)
        for a, b in zip(cuts, cuts[1:] + [u["i1"] + 1]):
            toks = [t for k in range(a, b) for t in wt[k]]
            if toks:
                out.append({"i0": a, "i1": b - 1, "toks": toks})
    return out


# ---------- script guessing ----------

def _after_restarts(ws: list) -> list:
    """Keep the last attempt when he restarts mid-take: "and it's from this old brand,
    and it's from this new brand…" -> "and it's from this new brand…"."""
    while len(ws) > 3:
        t = [tokens(w[0]) for w in ws]
        head = [x for k in range(min(3, len(ws))) for x in t[k]][:2]
        cut = next((j for j in range(1, len(ws) - 1) if [x for k in range(j, min(j + 3, len(ws))) for x in t[k]][:2] == head), None)
        if not cut:
            break
        ws = ws[cut:]
    return ws


def _stutters(toks: list) -> bool:
    """A repeated word pair ("carpenter, carpenter design") = a fumbled attempt."""
    pairs = list(zip(toks, toks[1:]))
    return len(pairs) != len(set(pairs)) or any(a == b for a, b in pairs)


def guess_script(sources: list) -> list:
    """Lines said more than once, in the order they were first said. sources =
    [(src_id, words)]. Falls back to every sentence when nothing repeats."""
    utts = []
    for sid, words in sources:
        for u in units(words, gap=0.7):
            ws = _after_restarts(words[u["i0"]:u["i1"] + 1])
            toks = tokens(" ".join(w[0] for w in ws))
            if len(toks) >= 3:
                utts.append({"toks": toks, "text": " ".join(w[0] for w in ws), "t": ws[0][1], "src": sid})
    clusters = []
    for u in utts:
        best, best_r = None, 0.68
        for c in clusters:
            r = ratio(u["toks"], c["rep"]["toks"])
            if r > best_r:
                best, best_r = c, r
        if best:
            best["members"].append(u)
            # representative = the cleanest-looking member (most like the others, no fillers)
            best["rep"] = max(best["members"], key=lambda m: (
                not (set(m["toks"]) & FILLERS), not _stutters(m["toks"]),
                sum(ratio(m["toks"], o["toks"]) for o in best["members"])))
        else:
            clusters.append({"rep": u, "members": [u]})
    lines = [c for c in clusters if len(c["members"]) >= 2] or clusters
    out = []
    for c in lines:
        head = c["rep"]["toks"][:4]
        # same opening (allowing "want"/"wanted") = another way of saying that line
        twin = next((l for l in out if len(head) == 4 and len(l["_head"]) == 4 and
                     SequenceMatcher(None, "".join(head), "".join(l["_head"])).ratio() >= 0.88), None)
        if twin:  # "It's also an aroma diffuser… smells great" / "…keeps your home smelling nice"
            twin["alts"].append(_tidy(c["rep"]["text"]))
        else:
            out.append({"id": store.new_id(), "text": _tidy(c["rep"]["text"]), "alts": [], "optional": False, "_head": head})
    for l in out:
        l.pop("_head")
    # a line that's the ending of another ("…not one, but three of these?" / "Three of
    # these?") was filmed as its own beat: trim it off the longer line so they don't overlap
    for a in out:
        ta = tokens(a["text"])
        for b in out:
            tb = tokens(b["text"])
            if a is not b and 2 <= len(tb) < len(ta) - 2 and ta[-len(tb):] == tb:
                words = a["text"].split()
                keep, got = len(words), 0
                while keep > 0 and got < len(tb):
                    keep -= 1
                    got += len(tokens(words[keep]))
                if keep >= 2:
                    a["text"] = " ".join(words[:keep]).rstrip(" ,.;")
                    a["text"] += ","
    return out


def _tidy(text: str) -> str:
    text = text.strip()
    return text[:1].upper() + text[1:]


# ---------- matching ----------

def _score(span_toks, line_toks):
    sm = SequenceMatcher(None, span_toks, line_toks, autojunk=False)
    matched = sum(b.size for b in sm.get_matching_blocks())
    return 2 * matched / (len(span_toks) + len(line_toks)), sm, matched


def _script_words(words: list, line_text: str) -> list:
    """The take's timed words, re-spelled from the script where they line up (brand
    names, capitals, punctuation) so subtitles read like the script."""
    script = line_text.split()
    a = ["".join(tokens(w[0])) for w in words]
    b = ["".join(tokens(w)) for w in script]
    out = [[w[0], w[1], w[2]] for w in words]
    respaced = []  # (i0, i1, new words) for misheard phrases with a different word count
    for op, i0, i1, j0, j1 in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal" or (op == "replace" and i1 - i0 == j1 - j0):
            for k in range(i1 - i0):
                out[i0 + k][0] = script[j0 + k]
        elif op == "replace" and SequenceMatcher(None, "".join(a[i0:i1]), "".join(b[j0:j1])).ratio() >= 0.6:
            # "Lay it off" heard for "light off": script words, spread over the same time
            t0, t1, n = words[i0][1], words[i1 - 1][2], j1 - j0
            respaced.append((i0, i1, [[script[j0 + k], round(t0 + (t1 - t0) * k / n, 2),
                                       round(t0 + (t1 - t0) * (k + 1) / n, 2)] for k in range(n)]))
    for i0, i1, new in reversed(respaced):
        out[i0:i1] = new
    return out


def respell(stoks: list, ltoks: list) -> list:
    """Swap transcript words that are near-misses of script words (or of two script
    words run together: "wafflenet" ~ "waffle knit") for the script's spelling."""
    vocab = set(ltoks)
    pairs = {a + b: [a, b] for a, b in zip(ltoks, ltoks[1:])}
    short = len(ltoks) <= 2  # exclamations ("Ow!"): Whisper hears "how" / "wow"
    out = []
    for t in stoks:
        if t in vocab or (len(t) < 4 and not short):
            out.append(t)
            continue
        best, br = [t], 0.74 if short else 0.8
        for cand, rep in [(v, [v]) for v in vocab if len(v) >= (2 if short else 4)] + list(pairs.items()):
            r = SequenceMatcher(None, t, cand, autojunk=False).ratio()
            if r > br:
                best, br = rep, r
        out += best
    return out


def grade(span_words: list, line: dict) -> dict:
    ltoks = tokens(line["text"])
    stoks = respell(tokens(" ".join(w[0] for w in span_words)), ltoks)
    score, sm, matched = _score(stoks, ltoks)
    missing, extra = [], []
    for op, i0, i1, j0, j1 in sm.get_opcodes():
        if op in ("delete", "replace"):
            extra += stoks[i0:i1]
        if op in ("insert", "replace"):
            missing += ltoks[j0:j1]
    recall = matched / max(1, len(ltoks))
    said, ref = " ".join(stoks), " ".join(ltoks)
    restarts = sorted(set(extra) & RESTARTS) + [p for p in RESTART_PHRASES if p in said and p not in ref]
    hesitations = sorted(set(extra) & HESITATIONS)
    # The script doesn't have to be word perfect: paraphrases and ad-libs are fine as
    # long as the line gets said all the way through (its last words are there).
    tail = ltoks[-min(3, len(ltoks)):]
    tail_hit = SequenceMatcher(None, stoks[-max(6, len(tail) * 2):], tail, autojunk=False)
    ends_ok = sum(b.size for b in tail_hit.get_matching_blocks()) >= max(1, len(tail) - 1)
    gaps = [b[1] - a[2] for a, b in zip(span_words, span_words[1:])]
    max_gap = max(gaps, default=0)
    flags = []
    if restarts:
        status = "flub"
        flags.append("restarted: " + ", ".join(f"“{f}”" for f in restarts))
    elif recall < 0.55 or not ends_ok:
        status = "incomplete"
        flags.append("stopped before the end of the line" if not ends_ok
                     else f"only {round(recall * 100)}% of the line")
    elif max_gap > 1.0:
        status = "paused"
        flags.append(f"paused {max_gap:.1f}s mid-line (checking the script?)")
    elif missing or extra or hesitations:
        status = "close"  # usable: reworded a bit, still the whole line
        if hesitations:
            flags.append("hesitated: " + ", ".join(f"“{h}”" for h in hesitations))
        if len(missing) + len(extra) > 0:
            flags.append(f"reworded ({len(missing)} skipped, {len(extra)} added)")
    else:
        status = "good"
    return {"score": round(score, 3), "status": status, "flags": flags,
            "missing": missing, "extra": extra, "usable": status in ("good", "close")}


def variants(line: dict) -> list:
    """The line's wording plus any alternate wordings he tried (line["alts"]): a take
    of any of them counts for the line, so videos can differ in wording too."""
    return [t for t in [line.get("text", "")] + list(line.get("alts") or []) if t.strip()]


def split_line_pairs(words: list, us: list, lines: list, line_toks: dict) -> list:
    """Split a unit where he ran one script line straight into the next without a
    pause ("because Old Navy just dropped…", or the two halves of a transition), so
    each half lands in its own line's stack."""
    wt = [tokens(w[0]) for w in words]
    pairs = [(ta, tb) for a, b in zip(lines, lines[1:])
             for ta in line_toks[a["id"]] for tb in line_toks[b["id"]] if ta and tb]
    out = []
    for u in us:
        n = u["i1"] - u["i0"] + 1
        best = None
        if n >= 2:
            for la, lb in pairs:
                whole = max(ratio(u["toks"], la), ratio(u["toks"], lb))
                for cut in range(1, n):
                    left = [t for k in range(u["i0"], u["i0"] + cut) for t in wt[k]]
                    right = [t for k in range(u["i0"] + cut, u["i1"] + 1) for t in wt[k]]
                    ra, rb = ratio(left, la), ratio(right, lb)
                    # split when both halves read as their lines and, together, better
                    # than the whole thing does as either one ("lid off, light on, | lid on")
                    # …or when it runs into the opening words of the next line, which he
                    # then finishes after a pause ("lid off, light on, LID ON" … "light off")
                    opens_next = ra >= 0.85 and len(right) >= 2 and ratio(right, lb[:len(right)]) >= 0.9
                    if opens_next:
                        rb = max(rb, 0.6)
                    if (opens_next or (ra >= 0.6 and rb >= 0.6 and (ra + rb) / 2 > whole + 0.02)) and (best is None or ra + rb > best[0]):
                        best = (ra + rb, cut, left, right)
        if best:
            _, cut, left, right = best
            out.append({"i0": u["i0"], "i1": u["i0"] + cut - 1, "toks": left})
            out.append({"i0": u["i0"] + cut, "i1": u["i1"], "toks": right})
        else:
            out.append(u)
    return out


_motion_cache = {}


def motion_curve(key: str, t0: float, t1: float):
    """Frame-to-frame change (30/s) over [t0, t1] of a source's proxy; value k is the
    change into frame k+1, i.e. at t0 + (k+1)/30."""
    ck = (key, round(t0, 2), round(t1, 2))
    if ck not in _motion_cache:
        import numpy as np
        w, h, fps = 36, 64, 30
        raw = subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-ss", f"{t0:.3f}", "-t", f"{t1 - t0:.3f}",
                              "-i", str(store.PROXY_DIR / f"{key}.mp4"), "-vf", f"fps={fps},scale={w}:{h},format=gray",
                              "-f", "rawvideo", "-"], capture_output=True).stdout
        frames = np.frombuffer(raw, np.uint8)[: len(raw) // (w * h) * w * h].reshape(-1, h, w).astype(np.int16)
        _motion_cache[ck] = np.abs(np.diff(frames, axis=0)).mean(axis=(1, 2)) if len(frames) >= 3 else np.zeros(0)
    return _motion_cache[ck]


def motion_peak(key: str, t0: float, t1: float) -> float:
    """Time of the biggest frame-to-frame change in [t0, t1] of a source's proxy:
    the moment of a pull / whip / grab, where a transition cut hides best."""
    c = motion_curve(key, t0, t1)
    return t0 + (int(c.argmax()) + 1) / 30 if len(c) else t0


def pair_offset(kb: str, wb: float, ka: str, wa: float, span: float = 0.8) -> float:
    """Where to cut between one take and the next (seconds after the next line's first
    word, the same on both sides so the speech carries over): the moment both pictures
    move most, so the pull on one side flows into the motion on the other."""
    import numpy as np
    b, a = motion_curve(kb, wb, wb + span), motion_curve(ka, wa, wa + span)
    n = min(len(b), len(a))
    if n < 3:
        return None
    # normalise each side so a busy background on one doesn't drown the other
    score = b[:n] / (b[:n].max() or 1) + a[:n] / (a[:n].max() or 1)
    lo = 3  # not right on the word: let the move get going
    return (lo + int(np.argmax(score[lo:])) + 1) / 30


def align_transitions(s: dict, after_cut_of: dict):
    """For each "cut into next" line: line both sides up on the first word of the
    next line, cut_offset seconds in (default: where the motion peaks, measured on
    the takes), so the pull and the word both carry across the cut."""
    srcs = {x["id"]: x for x in s["sources"]}
    for line in s["script"]:
        nxt = after_cut_of.get(line["id"])
        if not nxt:
            continue
        before = [t for t in s["takes"] if t["line"] == line["id"] and t.get("_next_word") is not None]
        after = [t for t in s["takes"] if t["line"] == nxt and t["words"]]
        nline = next((l for l in s["script"] if l["id"] == nxt), None)
        first = (tokens(nline["text"]) or [""])[0] if nline else ""

        def w0(t):  # the next line's first word in this take (skip a stray "but"/"so" he added)
            for w in t["words"][:3]:
                if (tokens(w[0]) or [""])[0] == first:
                    return w[1]
            return t["words"][0][1]
        if line.get("cut_offset") is None:
            peaks = [motion_peak(srcs[t["src"]]["key"], t["_next_word"], t["_next_word"] + 0.8) - t["_next_word"]
                     for t in before[:8]]
            peaks += [motion_peak(srcs[t["src"]]["key"], w0(t), w0(t) + 0.8) - w0(t)
                      for t in after[:8]]
            off = sorted(peaks)[len(peaks) // 2] if peaks else 0.0
            line["cut_offset_auto"] = round(min(0.6, max(0.0, off)) * 20) / 20
        off = line["cut_offset"] if line.get("cut_offset") is not None else line.get("cut_offset_auto", 0.0)
        offs = {}
        if line.get("cut_offset") is None:
            # take k of this line meets take k of the next one in video k: cut each pair
            # on its own shared motion instead of one average for every video
            key = lambda t: (list(srcs).index(t["src"]) if t["src"] in srcs else 0, t["in"])
            ub = sorted((t for t in before if t["usable"]), key=key)
            ua = sorted((t for t in after if t["usable"]), key=key)
            for tb, ta in zip(ub, ua):
                o = pair_offset(srcs[tb["src"]]["key"], tb["_next_word"], srcs[ta["src"]]["key"], w0(ta))
                if o is not None:
                    offs[id(tb)] = offs[id(ta)] = min(0.6, o)
        for t in before:
            if not t["user"].get("out"):
                t["out"] = round(t["_next_word"] + offs.get(id(t), off), 3)
        for t in after:
            if not t["user"].get("in"):
                t["in"] = round(w0(t) + offs.get(id(t), off), 3)
    for t in s["takes"]:
        t.pop("_next_word", None)


def look_at(src: dict, t: float):
    """The outfit/look he's wearing at time t in this source (None = not set)."""
    cur = None
    for m in sorted(src.get("looks") or [], key=lambda m: m["t"]):
        if m["t"] <= t + 0.01:
            cur = m["name"]
    return cur


def match(s: dict, progress=print) -> dict:
    """Rebuild s["takes"] from the transcripts and the script, carrying over anything
    the user set by hand on takes that cover the same moment."""
    st = s["style"]
    lines = s["script"]
    line_toks = {l["id"]: [tokens(v) for v in variants(l)] for l in lines}  # per variant
    after_cut = {b["id"] for a, b in zip(lines, lines[1:]) if a.get("cut_next")}
    new = []
    for src in s["sources"]:
        if src.get("status") != "ready":
            continue
        words = words_for(src["key"])
        starts = [vt[:3] for l in lines for vt in line_toks[l["id"]] if len(vt) >= 3]
        us = split_line_pairs(words, split_restarts(words, units(words), starts), lines, line_toks)
        looks = [look_at(src, words[u["i0"]][1]) for u in us]
        cands = []
        for a in range(len(us)):
            toks = []
            for b in range(a, min(a + 6, len(us))):
                if b > a and words[us[b]["i0"]][1] - words[us[b - 1]["i1"]][2] > 3:
                    break  # a long silence = between takes, never inside one
                toks = toks + us[b]["toks"]
                if words[us[b]["i1"]][2] - words[us[a]["i0"]][1] > 30:
                    break
                for l in lines:
                    vts = [vt for vt in line_toks[l["id"]] if vt and len(toks) <= 2.2 * len(vt) + 4]
                    if not vts:
                        continue
                    if l.get("look") and looks[a] != l["look"]:
                        continue  # filmed in the other outfit
                    sc = max(ratio(toks, vt) for vt in vts)
                    if sc >= 0.45:
                        cands.append((sc, -(b - a), a, b, l["id"]))
        taken = [False] * len(us)
        picks = []
        for sc, _, a, b, lid in sorted(cands, reverse=True):
            if any(taken[a:b + 1]):
                continue
            for k in range(a, b + 1):
                taken[k] = True
            picks.append((a, b, lid))
        # leftover speech (chit-chat, "okay rolling"): kept as unmatched takes
        for k, u in enumerate(us):
            if not taken[k] and len(u["toks"]) >= 2:
                picks.append((k, k, None))
        by_line = {l["id"]: l for l in lines}
        for a, b, lid in picks:
            i0, i1 = us[a]["i0"], us[b]["i1"]
            if lid in after_cut:
                # "…not one, but | BUT three of these": drop lead-in words that
                # aren't in the line, or the word gets said twice across the cut
                lt = {t for vt in line_toks[lid] for t in vt}
                while i0 < i1 and lt and not set(tokens(words[i0][0])) & lt:
                    i0 += 1
            span = words[i0:i1 + 1]
            prev_end = words[i0 - 1][2] if i0 > 0 else 0.0
            next_start = words[i1 + 1][1] if i1 + 1 < len(words) else src["duration"]
            line = by_line.get(lid) or {}
            # transitions: the cut lands on the motion, i.e. exactly where the next
            # words start (or right after the last word), and the line after starts
            # tight on its first word so the motion carries across the cut
            pad_in = 0.03 if lid in after_cut else st["pad_before"]
            if line.get("lead_in"):  # show what happens before he speaks (a sniff, a reveal)
                pad_in = max(pad_in, float(line["lead_in"]))
            pad_out = 0.0 if line.get("cut_next") else st["pad_after"]
            t_in = max(prev_end + 0.02, span[0][1] - pad_in, 0.0)
            next_word = None
            if line.get("cut_next") and i1 + 1 < len(words) and next_start - span[-1][2] < 0.6:
                t_out = next_word = next_start  # moved onto the motion by align_transitions
            else:
                t_out = min(next_start - 0.02, span[-1][2] + max(pad_out, 0.04), src["duration"])
            take = {**store.TAKE_FIELDS, "id": store.new_id(), "line": lid, "src": src["id"],
                    "in": round(t_in, 3), "out": round(t_out, 3), "look": looks[a],
                    "text": " ".join(w[0] for w in span), "user": {}, "_next_word": next_word,
                    "_limit": next_start}  # how far a "wait for it" take may run
            if lid:
                # grade against whichever wording he went for
                said = tokens(" ".join(w[0] for w in span))
                vs = variants(line)
                vi = max(range(len(vs)), key=lambda i: ratio(said, tokens(vs[i])))
                take.update(grade(span, {"text": vs[vi]}), alt=vi, for_text=vs[vi])
                take["words"] = _script_words(span, vs[vi])
            else:
                take.update(status="unmatched", usable=False, flags=["not a script line"],
                            words=[[w[0], w[1], w[2]] for w in span])
            new.append(take)
    new.sort(key=lambda t: (t["src"], t["in"]))
    from . import payoff
    payoff.apply(s, new)  # "wait for the candle to go out" lines
    align_transitions({**s, "takes": new}, {a["id"]: b["id"] for a, b in zip(lines, lines[1:]) if a.get("cut_next")})
    _keep_ids(s, s["takes"], new)
    _carry_over(s["takes"], new)
    s["takes"] = new + [t for t in s["takes"] if t["user"].get("manual") and not t.get("_covered")]
    for t in s["takes"]:
        t.pop("_covered", None)
    for l in lines:
        _order_line(s, l["id"])
    _order_line(s, None)
    rank_stacks(s, progress)
    auto_tighten(s)
    return s


def _overlap(a, b) -> float:
    inter = min(a["out"], b["out"]) - max(a["in"], b["in"])
    return inter / max(0.01, min(a["out"] - a["in"], b["out"] - b["in"]))


def _keep_ids(s: dict, old: list, new: list):
    """Re-matched takes keep the id of the old take covering the same moment, so saved
    and posted videos still point at the right takes. Takes locked into a posted video
    come back exactly as they were (same trim, same line): the post can't change."""
    locked = store.locked_ids(s)
    used = set()
    for o in sorted(old, key=lambda o: o["id"] not in locked):  # locked takes first
        if o["user"].get("manual"):
            continue  # hand-built clips are kept as they are (their id stays theirs alone)
        cands = [n for n in new if n["src"] == o["src"] and id(n) not in used]
        hit = max(cands, key=lambda n: _overlap(n, o), default=None)
        if hit is None or _overlap(hit, o) < 0.5:
            if o["id"] in locked:
                new.append({k: v for k, v in o.items() if not k.startswith("_")})
                used.add(id(new[-1]))
            continue
        used.add(id(hit))
        if o["id"] in locked:
            hit.clear()
            hit.update({k: v for k, v in o.items() if not k.startswith("_")})
        else:
            hit["id"] = o["id"]


def _carry_over(old: list, new: list):
    for o in old:
        if not o["user"] or o["user"].get("manual"):
            continue  # hand-built clips (montages, hooks) stay exactly as they are
        hit = max((n for n in new if n["src"] == o["src"]), key=lambda n: _overlap(n, o), default=None)
        if hit is None or _overlap(hit, o) < 0.5:
            continue
        o["_covered"] = True
        # the line was reworded since: let the take re-fit the new words instead of
        # keeping the old trim (words that were cut off come back in)
        reworded = "for_text" in o and o.get("for_text") != hit.get("for_text")
        for k, v in o["user"].items():
            if k in ("manual",) or (reworded and k in ("in", "out", "words", "text")):
                continue
            if k in ("in", "out", "usable", "line", "order", "zoom", "pan_x", "pan_y", "volume", "cuts", "splits", "sfx", "fx",
                     "words", "text", "freeze", "title", "speed"):  # words = captions he corrected
                hit[k] = o[k]
                hit["user"][k] = True


def _order_line(s: dict, line_id):
    """Usable takes in shooting order (unless the user dragged them), then rejects."""
    mine = [t for t in s["takes"] if t["line"] == line_id]
    srcs = {src["id"]: i for i, src in enumerate(s["sources"])}
    for usable in (True, False):
        group = [t for t in mine if t["usable"] == usable]
        group.sort(key=lambda t: (t["order"] if t["user"].get("order") else 1e9,
                                  srcs.get(t["src"], 0), t["in"]))
        for i, t in enumerate(group):
            t["order"] = i


def rank_stacks(s: dict, progress=print):
    """Best takes first, so video 1 is the best video the footage can make: each take is
    scored (clean read, no ums or rewording, looking into the lens; adcut/quality.py) and
    every line's free takes stack best-first. Takes where he tried a different read (an
    alternate wording, or reworded it a lot) are kept together instead: they go to the
    same video(s), at the end of the stack, so one video is the "other read" and the rest
    stay consistent. Lines the user re-ordered by hand keep their order."""
    from . import quality
    srcs = {x["id"]: x for x in s["sources"]}
    usable = [t for t in s["takes"] if t["line"] and t["usable"]]
    keys = {srcs[t["src"]]["key"] for t in usable if t["src"] in srcs}
    for i, k in enumerate(sorted(keys)):
        if not (quality.GAZE_DIR / f"{k}-v{quality.VERSION}.npy").exists():
            progress(f"checking eye contact ({i + 1}/{len(keys)})")
    for t in usable:
        if t["src"] in srcs:
            t.update(quality.score(t, srcs[t["src"]]["key"], FILLERS, tokens))
    locked = store.locked_ids(s)
    free = {l["id"]: [t for t in usable if t["line"] == l["id"] and t["id"] not in locked] for l in s["script"]}
    req = [len(v) for l in s["script"] if not l.get("optional") for v in [free[l["id"]]]]
    n = min(req) if req else 0
    for l in s["script"]:
        mine = free[l["id"]]
        if not mine or any(t["user"].get("order") for t in mine):
            continue
        # an alternate wording is only a "different read" when it's the minority: if he
        # mostly says it the other way, that way is the line's normal read
        from collections import Counter
        # (and a wording he uses in a third or more of the takes is a normal read too)
        count = Counter(t.get("alt", 0) for t in mine)
        for t in mine:
            rare = count[t.get("alt", 0)] < len(mine) / 3
            if t.get("variant") == "alt wording" and not rare:
                t["variant"] = None
            elif not t.get("variant") and rare:
                t["variant"] = "alt wording"
        best = lambda ts: sorted(ts, key=lambda t: -t.get("quality", 0))
        main, odd = best([t for t in mine if not t.get("variant")]), best([t for t in mine if t.get("variant")])
        # the other reads fill the last videos (all lines' odd takes line up there)
        k = max(0, min(len(main), (n or len(mine)) - len(odd)))
        ordered = main[:k] + odd + main[k:]
        held = sorted((t for t in s["takes"] if t["line"] == l["id"] and t["usable"] and t["id"] in locked),
                      key=lambda t: t["order"])
        for i, t in enumerate(held + ordered):
            t["order"] = i


def auto_tighten(s: dict, gap: float = 0.3, keep: float = 0.12):
    """Auto pace: cut the pauses between words (> gap, leaving keep on each side) out of
    every usable take, like the editor's Tighten. Only takes whose cut-outs the user hasn't
    touched, and never locked ones; re-matching redoes them."""
    if not ((s["style"].get("pace") or {}).get("auto") and (s["style"]["pace"].get("pauses", True))):
        return
    locked = store.locked_ids(s)
    for t in s["takes"]:
        if not t["usable"] or not t["line"] or t["id"] in locked or t["user"].get("cuts") or t["user"].get("manual"):
            continue
        ws = [w for w in t["words"] if t["in"] - 0.01 <= w[1] and w[2] <= t["out"] + 0.01]
        t["cuts"] = list(t.get("cuts") or []) + [[round(a[2] + keep, 3), round(b[1] - keep, 3)] for a, b in zip(ws, ws[1:])
                     if b[1] - a[2] > gap and (b[1] - keep) - (a[2] + keep) >= 0.06]


def decide_mix(s: dict):
    """New footage came in (a new batch). If the old footage already makes complete videos
    (or some are saved/posted) and the new footage makes complete videos on its own, keep
    them apart: the old videos stay as they were and the new ones come after. If either
    side can't make a whole video alone (the new takes fill in lines the old ones were
    missing), re-cut everything together. The user's own choice (s["mix"]) always wins."""
    batches = sorted({int(x.get("batch") or 1) for x in s["sources"] if x.get("status") == "ready"})
    if len(batches) < 2:
        s["mix_auto"], s["batch_note"] = True, ""
        return
    newest = batches[-1]
    bo = store.batch_of(s)
    keep_mix = s.get("mix")
    s["mix"] = True  # count each side as one pool
    old_n = len(store._recipes(s, lambda t: bo[t["id"]] != newest)[0]) + len(store.posted_videos(s))
    new_n = len(store._recipes(s, lambda t: bo[t["id"]] == newest)[0])
    s["mix"] = keep_mix
    if old_n and new_n:
        s["mix_auto"] = False
        s["batch_note"] = (f"New footage makes {new_n} video{'s' if new_n != 1 else ''} of its own, so it's kept "
                           f"separate: the earlier videos stay as they were.")
    else:
        s["mix_auto"] = True
        s["batch_note"] = ("New footage filled in what the earlier footage was missing, so everything was re-cut together."
                           if not old_n else "New footage can't make a whole video on its own, so it's mixed in with the earlier takes.")
