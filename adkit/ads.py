"""Find commercial breaks in recordings (PlayOn keeps the streaming ads).

Ad copy is unmistakable in the transcript: drug side-effect lists, APR offers, URLs,
"only at", brand names. Clusters of such lines mark a break; the whole break (with the
music and silence between the lines) is excluded from search, transcripts and the
soundboard scan."""
import re

AD_RX = re.compile("|".join([
    r"ask your doctor", r"side effects", r"tell your doctor", r"call your doctor", r"allergic reactions?",
    r"\bAPR\b", r"\d+ ?%", r"\$\s?\d", r"\.com\b", r"\bdot com\b", r"\bterms apply\b", r"\bvisit\b",
    r"\bonly at\b", r"\bavailable (?:at|now|in)\b", r"\bshop (?:now|at)\b", r"\bsave (?:up to|big|thousands)\b",
    r"\bsavings\b", r"\bdealer\b", r"\bbonus cash\b", r"\bfinancing\b", r"\bprescription\b", r"\bsymptoms\b",
    r"\bintroducing\b", r"\bnew\b.*\b(?:collection|flavor|formula)\b", r"\bfree (?:shipping|delivery|trial)\b",
    r"\bdownload the\b", r"\bthe app\b", r"\bsubscribe\b", r"\bpowered by\b", r"\bnumber one\b",
    r"\bclinically\b", r"\bdermatologist\b.*\brecommended\b", r"\btreatment\b", r"\bmortgage\b",
    r"\binsurance (?:company|plan)\b", r"\bbrand\b", r"\bget (?:yours|it) (?:today|now)\b",
    # brands that keep turning up in these recordings
    r"\b(?:Fidelity|Dupixent|Dupixin|Dewpixin|Tampax|Tide|JCPenney|J\.?C\.? Penney|Sephora|Chipotle|Clorox|"
    r"Nissan|Hyundai|SoFi|Ford|Reliant|Rooms ?(?:2|To) ?Go|Living Spaces|Favor|H-?E-?B|Nordic Naturals|"
    r"Nurtec|Caplyta|Kaplita|Capilita|Leqembi|LeCambi|Dove Men|Head (?:&|and) Shoulders|Icy ?Hot|Jolie|"
    r"Tinder|Choice ?Hotels|Secret|Walmart\+|Target|Peacock|Prime Video|Breck)\b",
]), re.I)


def ad_breaks(segments: list, duration: float) -> list:
    """[(start, end)] commercial breaks, from clusters of ad-like transcript lines."""
    hits = [s for s in segments if AD_RX.search(s.get("text", ""))]
    breaks = []
    for s in sorted(hits, key=lambda s: s["start"]):
        if breaks and s["start"] - breaks[-1][1] < 40:
            breaks[-1][1] = s["end"]
            breaks[-1][2] += 1
        else:
            breaks.append([s["start"], s["end"], 1])
    show = sorted((s for s in segments if not AD_RX.search(s.get("text", ""))), key=lambda s: s["start"])
    out = []
    for a, b, n in breaks:
        if n < 2 and b - a < 6:
            continue
        # widen over the silence/music around the copy, but never into a show line
        prev = max((s["end"] for s in show if s["end"] <= a and not (a <= s["start"] <= b)), default=0.0)
        nxt = min((s["start"] for s in show if s["start"] >= b), default=duration)
        a, b = max(0.0, a - 25, prev), min(duration, b + 10, nxt)
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(round(a, 2), round(b, 2)) for a, b in out]


def in_ad(t: float, breaks: list) -> bool:
    return any(a <= t <= b for a, b in breaks)
