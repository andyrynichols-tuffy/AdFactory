"""TikTok Shop safety: flags words in a take's captions that TikTok Shop content rules
don't allow (sexual content, profanity, drugs) or treat with caution (alcohol, which a
drinking game is full of). The editor shows ⚠ on the take and its video row; montage cuts
pick the clean takes first. Word lists only: a person still has the final say."""
import re

# category -> (level, patterns). "unsafe" = keep it off Shop videos; "caution" = check it.
RULES = {
    "sexual": ("unsafe", [
        r"sex\w*", r"penis\w*", r"vagina\w*", r"dick\w*", r"cock\w*", r"puss(y|ies)", r"boobs?", r"tits?", r"titty",
        r"nipples?", r"areolas?", r"naked", r"nude", r"porn\w*", r"horny", r"orgasm\w*", r"blow ?jobs?", r"handjobs?",
        r"hook(ed|ing)? up", r"slept with", r"sleep with", r"masturbat\w*", r"anal", r"doggy", r"condoms?", r"smegma",
        r"g ?-?spot", r"threesomes?", r"kinky", r"tied up", r"butthole", r"ass(hole)?", r"intercourse", r"virgins?",
        r"golden shower", r"blumpkin", r"penetration", r"strip(per|ping)?", r"booty call", r"fetish\w*", r"giving head",
        r"uncut", r"bottom in a doggy", r"stis?", r"abortions?", r"skinny ?dipping"]),
    "profanity": ("unsafe", [r"fuck\w*", r"shit\w*", r"bitch\w*", r"bastards?", r"wtf", r"motherf\w*", r"damn\w*"]),
    "drugs": ("unsafe", [r"weed", r"cocaine", r"molly", r"edibles?", r"stoned", r"vap(e|ing)"]),
    "alcohol": ("caution", [r"drink(s|ing)?", r"drunk", r"alcohol\w*", r"bender", r"hang ?over", r"hungover", r"beers?",
                            r"wine", r"vodka", r"tequila", r"whiskey", r"shots", r"wasted", r"tipsy", r"booze"]),
}
_RX = {cat: (lvl, re.compile(r"\b(" + "|".join(p) + r")\b", re.I)) for cat, (lvl, p) in RULES.items()}


def check(text: str) -> list:
    """[{cat, level, words}] for one caption text (empty = clean)."""
    out = []
    for cat, (lvl, rx) in _RX.items():
        hits = sorted({m.group(0).lower() for m in rx.finditer(text or "")})
        if hits:
            out.append({"cat": cat, "level": lvl, "words": hits})
    return out


def level(flags: list):
    """'unsafe' / 'caution' / None for a list of check() results."""
    lv = {f["level"] for f in flags}
    return "unsafe" if "unsafe" in lv else "caution" if lv else None


def rules_json() -> dict:
    """For the editor, which checks live as captions are edited."""
    return {cat: {"level": lvl, "patterns": p} for cat, (lvl, p) in RULES.items()}
