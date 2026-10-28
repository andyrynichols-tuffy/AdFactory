"""Exact commercial breaks in a recording (PlayOn keeps the streaming ads in).

Three signals, combined:
- Black frames with silence: streaming ads are separated by a beat of black + silence.
- Ad rhythm: inside a break those black beats come every ~15/30/45/60 s (spot lengths).
  A run of them at that rhythm is a break, even when no ad says a keyword.
- Ad copy in the transcript (ads.py: side-effect lists, brands, URLs) confirms a break and
  catches the rare one without clean black edges.
Break edges sit on the black beats themselves, so cuts are frame-exact. When an edge can't
be pinned to black, it errs toward KEEPING footage and the break is marked for review.
Nothing is ever deleted: results are ranges saved per episode (DATA_DIR/ads/<id>.json) that
thumbnails, search and clip picking skip.

CLI: python -m supercut.adscan <episode-id or prefix> [--force]"""
import json
import re
import subprocess
import sys
from pathlib import Path

from .config import DATA_DIR, FFMPEG, PROXY_DIR

OUT_DIR = DATA_DIR / "ads"
VERSION = 3
SPOT = 15.0            # ad lengths are multiples of 15 s
SPOT_TOL = 1.6         # seconds of slack per gap (encoders, fades)
MAX_SPOTS = 6          # a gap up to 90 s can be one long ad
MIN_BREAK = 14.0
# Copy that only ads say. The broad list in ads.py also matches dialogue ("$5", "40% off",
# "a favor"), so on its own it never hides footage: those breaks go to the review list.
STRONG_RX = re.compile("|".join([
    r"ask your doctor", r"tell your doctor", r"side effects", r"allergic reactions?", r"\bprescription\b",
    r"\bterms apply\b", r"\.com\b", r"\bdot com\b", r"\bAPR\b", r"\bclinically\b", r"\bget checked\b",
    r"\b(?:Dupixent|Caplyta|Kaplita|Nurtec|Leqembi|Tremfya|Trimphia|Trampaya|Skyrizi|Rinvoq|Ozempic|Jardiance|Vanguard|Fidelity|SoFi)\b",
]), re.I)


def _detect(src: Path) -> tuple:
    """(black [(start, end)], silence [(start, end)]) from one ffmpeg pass."""
    r = subprocess.run([FFMPEG, "-hide_banner", "-nostats", "-i", str(src),
                        "-vf", "blackdetect=d=0.08:pix_th=0.10", "-af", "silencedetect=n=-45dB:d=0.15",
                        "-f", "null", "-"], capture_output=True, text=True, errors="replace",
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    black = [(float(a), float(b)) for a, b in re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", r.stderr)]
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", r.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", r.stderr)]
    return black, list(zip(starts, ends))


def _beats(black, silence):
    """Black frames that also go quiet: the seams between ads (and into/out of a break)."""
    out = []
    for a, b in black:
        if any(s < b + 0.3 and e > a - 0.3 for s, e in silence):
            out.append((a, b))
    return out


def _spot_gap(g: float) -> bool:
    k = round(g / SPOT)
    return 1 <= k <= MAX_SPOTS and abs(g - k * SPOT) <= SPOT_TOL


def _chains(beats):
    """Runs of beats at ad rhythm: [[beat, beat, ...]] with >= 2 spot-length gaps."""
    chains, cur = [], [beats[0]] if beats else []
    for b in beats[1:]:
        gap = b[0] - cur[-1][1]       # from the end of one seam to the start of the next
        gap2 = b[0] - cur[-1][0]      # start to start (some encoders count the seam in the spot)
        if _spot_gap(gap) or _spot_gap(gap2):
            cur.append(b)
        else:
            if len(cur) >= 3:
                chains.append(cur)
            cur = [b]
    if len(cur) >= 3:
        chains.append(cur)
    return chains


def _norm(t: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", (t or "").lower()))


_REPEATS = {"key": None, "map": {}}


def _repeats() -> dict:
    """Normalized transcript line (>= 25 chars) -> the episodes it's said in. Ads repeat word for
    word across recordings; dialogue doesn't (built once per change to the index)."""
    from . import library
    eps = library.episodes()
    key = tuple(sorted((x["id"], x.get("duration")) for x in eps))
    if _REPEATS["key"] == key:
        return _REPEATS["map"]
    m = {}
    for x in eps:
        try:
            e = library.episode(x["id"])
        except Exception:
            continue
        for s in e["segments"]:
            n = _norm(s.get("text"))
            if len(n) >= 25:
                m.setdefault(n, set()).add(x["id"])
    _REPEATS.update(key=key, map=m)
    return m


def _repeated_lines(eid, segs, a, b) -> tuple:
    """(lines in [a, b] also said in another episode, lines long enough to tell)."""
    m = _repeats()
    lines = [_norm(s.get("text")) for s in segs if a - 1 <= s["start"] <= b + 1]
    lines = [n for n in lines if len(n) >= 25]
    return sum(1 for n in lines if len(m.get(n, ())) > 1 or (m.get(n) and eid not in m[n])), len(lines)


def scan(eid: str, force: bool = False) -> dict:
    from . import ads, library
    out = OUT_DIR / f"{eid}.json"
    if out.exists() and not force:
        d = json.loads(out.read_text(encoding="utf-8"))
        if d.get("version") == VERSION:
            return d
    e = library.episode(eid)
    old = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
    if old.get("beats") is not None and not force:   # the slow part (one ffmpeg pass) is kept between versions
        beats = [tuple(b) for b in old["beats"]]
    else:
        black, silence = _detect(PROXY_DIR / f"{eid}.mp4")
        beats = _beats(black, silence)
    segs = e["segments"]
    adlines = [s for s in segs if ads.AD_RX.search(s.get("text", ""))]
    showlines = [s for s in segs if not ads.AD_RX.search(s.get("text", "")) and "commercial break" not in s.get("text", "")]
    breaks = []
    # 1) ad rhythm: the break runs from the first seam's start to the last seam's end
    for ch in _chains(beats):
        a, b = ch[0][0], ch[-1][1]
        if b - a < MIN_BREAK:
            continue
        hits = sum(1 for s in adlines if a - 2 <= s["start"] <= b + 2)
        breaks.append({"start": round(a, 3), "end": round(b, 3), "spots": len(ch) - 1, "ad_lines": hits,
                       "how": "rhythm" + ("+copy" if hits else ""), "sure": True, "apply": True})
    # 2) ad copy with no rhythm run around it: pin its edges to the nearest seams that don't cut a show line
    for a, b in ads.ad_breaks(segs, e["duration"]):
        if any(x["start"] - 5 <= (a + b) / 2 <= x["end"] + 5 for x in breaks):
            continue
        core = [s for s in adlines if a <= s["start"] <= b]
        if not core:
            continue
        c0, c1 = min(s["start"] for s in core), max(s["end"] for s in core)
        prev_show = max((s["end"] for s in showlines if s["end"] <= c0 + 0.1), default=0.0)
        next_show = min((s["start"] for s in showlines if s["start"] >= c1 - 0.1), default=e["duration"])
        lo = [bt for bt in beats if prev_show - 0.2 <= bt[0] <= c0]
        hi = [bt for bt in beats if c1 <= bt[1] <= next_show + 0.2]
        start = lo[0][0] if lo else None
        end = hi[-1][1] if hi else None
        sure = start is not None and end is not None
        strong = sum(1 for s in core if STRONG_RX.search(s["text"]))
        # unsure edges keep footage: start no earlier than the ad copy, end no later than it
        breaks.append({"start": round(start if start is not None else c0, 3), "end": round(end if end is not None else c1, 3),
                       "spots": 0, "ad_lines": len(core), "strong": strong, "how": "copy" + ("+seams" if sure else ""), "sure": sure,
                       "apply": sure and strong >= 2})
    breaks.sort(key=lambda x: x["start"])
    # never inside a show line: trim an edge that would eat dialogue, and flag it
    for br in breaks:
        for s in showlines:
            if s["start"] < br["end"] and s["end"] > br["start"] and not (br["start"] <= s["start"] and s["end"] <= br["end"] and br["how"].startswith("rhythm")):
                if s["start"] < br["start"] < s["end"]:
                    br["start"], br["sure"] = round(s["end"], 3), False
                if s["start"] < br["end"] < s["end"]:
                    br["end"], br["sure"] = round(s["start"], 3), False
    for br in breaks:  # an unsure edge on a rhythm break still hides only the rhythm part; copy-only + unsure = review
        if not br["sure"] and not br["how"].startswith("rhythm"):
            br["apply"] = False
    # the third signal for copy-only breaks: the same words in other recordings = an ad;
    # weak keywords nobody else says = dialogue ("Do I hear $10?"), dropped
    for br in breaks:
        if br["how"].startswith("rhythm"):
            continue
        rep, n = _repeated_lines(eid, segs, br["start"], br["end"])
        br["repeated"] = rep
        if rep >= 2 or (n and rep / n >= 0.5 and rep >= 1):
            br["apply"], br["how"] = True, br["how"] + "+repeats"   # edges stay on the ad copy (or seams): show footage is kept
        elif rep == 0 and not br.get("strong"):
            br["rejected"] = "dialogue"
    breaks = [b for b in breaks if b["end"] - b["start"] >= 5]
    for br in breaks:  # a person's call on a break survives rescans
        for ob in old.get("breaks", []):
            if (ob.get("approved") or ob.get("rejected") == "person") and ob["start"] < br["end"] and br["start"] < ob["end"]:
                br["approved"], br["rejected"] = ob.get("approved"), ob.get("rejected")
                if br.get("rejected"):
                    br["apply"] = False
    d = {"version": VERSION, "episode": eid, "duration": e["duration"], "breaks": breaks,
         "beats": [[round(a, 3), round(b, 3)] for a, b in beats]}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(d, indent=1), encoding="utf-8")
    return d


def load(eid: str, review: bool = False):
    """The breaks that are hidden everywhere (None = not scanned yet); review=True: the
    ones that need a person's look instead (never hidden until approved)."""
    f = OUT_DIR / f"{eid}.json"
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if d.get("version") != VERSION:
        return None
    return [b for b in d["breaks"] if bool(b.get("apply") or b.get("approved")) != review and not b.get("rejected")]


def review_list() -> list:
    """Every break waiting for a person, newest recordings' shows first."""
    from . import library
    meta = {x["id"]: x for x in library.episodes()}
    out = []
    for f in sorted(OUT_DIR.glob("*.json")):  # only the scan results; transcripts just for the few to review
        x = meta.get(f.stem)
        if not x:
            continue
        for b in load(x["id"], review=True) or []:
            out.append({"episode": x["id"], "show": x["show"], "title": x["title"], "start": b["start"], "end": b["end"],
                        "how": b["how"], "lines": _lines(x["id"], b["start"], b["end"])})
    return out


def _lines(eid, a, b):
    from . import library
    return [s["text"] for s in library.episode(eid)["segments"] if a - 1 <= s["start"] <= b + 1][:8]


def decide(eid: str, start: float, is_ad: bool):
    """A person's call on one break: an ad (hide it) or the show (never hide it)."""
    f = OUT_DIR / f"{eid}.json"
    d = json.loads(f.read_text(encoding="utf-8"))
    for b in d["breaks"]:
        if abs(b["start"] - start) < 0.01:
            b["approved"], b["rejected"] = bool(is_ad), (None if is_ad else "person")
    f.write_text(json.dumps(d, indent=1), encoding="utf-8")


if __name__ == "__main__":
    from . import library, resources
    resources.install()
    force = "--force" in sys.argv
    pre = [a for a in sys.argv[1:] if not a.startswith("--")][0]
    for ep in [x["id"] for x in library.episodes() if x["id"].startswith(pre)]:
        d = scan(ep, force)
        mm = lambda t: f"{int(t // 60)}:{t % 60:04.1f}"
        print(ep, " | ".join(f"{mm(b['start'])}-{mm(b['end'])} ({b['end'] - b['start']:.0f}s {b['how']}{' DROPPED' if b.get('rejected') else '' if b['apply'] else ' REVIEW'})" for b in d["breaks"]), flush=True)
