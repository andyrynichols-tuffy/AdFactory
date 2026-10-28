"""Read the transcript index: list episodes, search lines, build subtitle cues."""
import json
import re
from functools import lru_cache

from .config import INDEX_DIR


@lru_cache(maxsize=64)
def _load(eid: str, mtime: float) -> dict:
    return json.loads((INDEX_DIR / f"{eid}.json").read_text(encoding="utf-8"))


def episode(eid: str) -> dict:
    p = INDEX_DIR / f"{eid}.json"
    if not p.exists():
        raise KeyError(f"unknown episode '{eid}' (run: python -m supercut episodes)")
    e = _load(eid, p.stat().st_mtime)
    from .adscan import OUT_DIR as _ADS
    try:
        ads_key = (_ADS / f"{eid}.json").stat().st_mtime
    except OSError:
        ads_key = None
    if "ads" not in e or e.get("_ads_key") != ads_key:  # commercial breaks: exact (adscan.py) when scanned, else rough (ads.py)
        from .ads import ad_breaks
        from .adscan import load as exact_breaks
        e["_ads_key"] = ads_key
        exact = exact_breaks(eid)  # once scanned, only its breaks count (the rough list mistakes "40% off" in dialogue for an ad)
        e["ads"] = [(x["start"], x["end"]) for x in exact] if exact is not None else ad_breaks(e["segments"], e["duration"])
    return e


def tighten(clip: dict, lo: float = 5.0, hi: float = 7.0) -> dict:
    """Montage-length clip: keep the ending (the punchline) and as much of the lead-up as
    fits in `hi` seconds, starting on a word (or a scene cut just before it)."""
    sp = clip.get("speed", 1.0)
    if (clip["out"] - clip["in"]) / sp <= hi:
        return clip
    e = episode(clip["episode"])
    out = clip["out"]
    words = sorted(w[1] for s in e["segments"] if s["end"] > clip["in"] and s["start"] < out
                   for w in s.get("words", []) if clip["in"] <= w[1] < out - 1.0)
    fits = [w for w in words if (out - (w - 0.15)) / sp <= hi]
    t_in = (fits[0] - 0.15) if fits else out - hi * sp
    cuts = [c for c in e.get("scenes", []) if t_in - 0.3 <= c <= t_in + 0.05]
    if cuts:
        t_in = max(cuts)
    return {**clip, "in": round(max(clip["in"], t_in), 2)}


def snap_cuts(clip: dict, lead: float = 0.9, tail: float = 1.2) -> dict:
    """Move a clip's edges onto the episode's own scene cuts when one is close, so cuts
    between clips land where the show already cuts (no jump mid-shot). Never trims words:
    the in-point only moves to a cut before the first word, the out-point to a cut after
    the last word."""
    e = episode(clip["episode"])
    words = [w for s in e["segments"] if s["end"] > clip["in"] and s["start"] < clip["out"]
             for w in s.get("words", []) if clip["in"] - 0.05 <= w[1] < clip["out"]]
    first = min((w[1] for w in words), default=clip["in"] + 0.3)
    last = max((w[2] for w in words), default=clip["out"] - 0.3)
    scenes = e.get("scenes", [])
    # never pick up the line after the wanted one: the out-point stays before the next word
    nxt = min((w[1] for s in e["segments"] if s["end"] > last for w in s.get("words", []) if w[1] > last + 0.05),
              default=e["duration"])
    stop = nxt - 0.08
    prev = max((w[2] for s in e["segments"] if s["start"] < first for w in s.get("words", []) if w[2] < first - 0.05),
               default=0.0)
    ins = [c for c in scenes if max(clip["in"] - lead, prev) <= c <= min(first - 0.05, clip["in"] + 0.35)]
    outs = [c for c in scenes if max(last + 0.15, clip["out"] - 0.25) <= c <= min(clip["out"] + tail, stop)]
    t_in = min(ins, key=lambda c: abs(c - clip["in"])) if ins else clip["in"]
    t_out = min(outs) if outs else min(clip["out"], max(stop, last + 0.1))
    # a frame inside the cut so no sliver of the neighbouring shot shows
    return {**clip, "in": round(t_in + (0.04 if ins else 0), 2), "out": round(t_out - (0.04 if outs else 0), 2)}


def in_ads(e: dict, t0: float, t1: float = None, margin: float = 0.0) -> bool:
    t1 = t0 if t1 is None else t1
    return any(a - margin < t1 and t0 < b + margin for a, b in e.get("ads", []))


_META = {}  # index file -> ((mtime, size), {id, show, title, duration})


def episodes() -> list:
    """Every indexed episode's id/show/title/duration. Reading each transcript takes ~20s for
    all of them, so the basics are cached (memory + index/_meta.json) per file mtime+size."""
    import json
    cache_file = INDEX_DIR.parent / "index_meta.json"
    if not _META and cache_file.exists():
        try:
            _META.update({k: (tuple(v[0]), v[1]) for k, v in json.loads(cache_file.read_text(encoding="utf-8")).items()})
        except (ValueError, OSError):
            pass
    out, changed = [], False
    for p in sorted(INDEX_DIR.glob("*.json")):
        st = p.stat()
        sig = (st.st_mtime, st.st_size)
        hit = _META.get(p.name)
        if not hit or tuple(hit[0]) != sig:
            e = episode(p.stem)
            hit = (sig, {"id": e["id"], "show": e["show"], "title": e["title"], "duration": e["duration"]})
            _META[p.name] = hit
            changed = True
        out.append(hit[1])
    if changed:
        try:
            cache_file.write_text(json.dumps({k: [list(v[0]), v[1]] for k, v in _META.items()}), encoding="utf-8")
        except OSError:
            pass
    return out


def search(pattern: str, show: str = None, limit: int = 200) -> list:
    """Regex (case-insensitive) over transcript lines. Returns line hits with context."""
    rx = re.compile(pattern, re.I)
    hits = []
    only = set(show.split(",")) if show and "," in show else None  # a list of episode ids
    for meta in episodes():
        if only is not None:
            if meta["id"] not in only:
                continue
        elif show and show.lower() not in meta["show"].lower() and show.lower() not in meta["id"]:
            continue
        ep = episode(meta["id"])
        segs = ep["segments"]
        for i, s in enumerate(segs):
            if rx.search(s["text"]) and not in_ads(ep, s["start"], s["end"]):
                hits.append({
                    "episode": meta["id"], "start": s["start"], "end": s["end"], "text": s["text"],
                    "before": segs[i - 1]["text"] if i else "",
                    "after": segs[i + 1]["text"] if i + 1 < len(segs) else "",
                })
                if len(hits) >= limit:
                    return hits
    return hits


def words_between(eid: str, t0: float, t1: float) -> list:
    words = []
    for s in episode(eid)["segments"]:
        if s["end"] < t0 or s["start"] > t1:
            continue
        for w, ws, we in s["words"]:
            mid = (ws + we) / 2
            if t0 - 0.05 <= mid <= t1 + 0.05:
                # whisper splits "10,000" / "alcohol-free" / "100%" into separate tokens
                if words and re.match(r"^[,.\-%']", w) and ws - words[-1][2] < 0.3:
                    words[-1] = [words[-1][0] + w, words[-1][1], we]
                else:
                    words.append([w, ws, we])
    return words


def scenes_between(eid: str, t0: float, t1: float) -> list:
    return [t for t in episode(eid)["scenes"] if t0 <= t <= t1]


def auto_cues(eid: str, t_in: float, t_out: float, words_per_line: int = 4) -> list:
    """Chunk transcript words into short punchy subtitle lines.
    Times are relative to the clip's in-point (source seconds, before speed)."""
    words = words_between(eid, t_in, t_out)
    cues, cur = [], []

    def flush():
        if cur:
            cues.append({
                "start": round(max(0.0, cur[0][1] - t_in), 2),
                "end": round(min(t_out, cur[-1][2]) - t_in, 2),
                "text": " ".join(w[0] for w in cur),
                "words": [[w[0], round(max(0.0, w[1] - t_in), 2), round(min(t_out, w[2]) - t_in, 2)] for w in cur],
            })
            cur.clear()

    for w in words:
        if cur and (len(cur) >= words_per_line or w[1] - cur[-1][2] > 0.6):
            flush()
        cur.append(w)
        if re.search(r"[.!?]$", w[0]):
            flush()
    flush()
    # hold each line until the next starts (no flicker between words)
    for a, b in zip(cues, cues[1:]):
        if 0 < b["start"] - a["end"] < 0.5:
            a["end"] = b["start"]
    return cues


def manual_cues(subs: list) -> list:
    """User-edited lines [{start,end,text}] -> cues with evenly spread word timings."""
    cues = []
    for s in subs:
        toks = s["text"].split()
        if not toks:
            continue
        step = (s["end"] - s["start"]) / len(toks)
        words = [[t, round(s["start"] + i * step, 2), round(s["start"] + (i + 1) * step, 2)] for i, t in enumerate(toks)]
        cues.append({"start": s["start"], "end": s["end"], "text": s["text"], "words": words})
    return cues


def clip_cues(clip: dict, words_per_line: int = 4) -> list:
    if clip.get("subs") is not None:
        return manual_cues(clip["subs"])
    return auto_cues(clip["episode"], clip["in"], clip["out"], words_per_line)


def transcript_text(eid: str, t0: float = 0, t1: float = 1e9) -> str:
    """Compact timestamped transcript, for Claude to read when picking moments."""
    e = episode(eid)
    peaks = e.get("peaks", [])
    lines, shown = [], set()
    for s in e["segments"]:
        if s["end"] < t0 or s["start"] > t1:
            continue
        brk = next(((a, b) for a, b in e.get("ads", []) if a < s["end"] and s["start"] < b), None)
        if brk:  # commercials: one marker line instead of the ad copy
            if brk not in shown:
                shown.add(brk)
                lines.append(f"[{brk[0]:.1f}-{brk[1]:.1f}] ---- commercial break ----")
            continue
        loud = " *LOUD*" if any(s["start"] - 1 <= p <= s["end"] + 2 for p in peaks) else ""
        lines.append(f"[{s['start']:.1f}-{s['end']:.1f}]{loud} {s['text']}")
    return "\n".join(lines)
