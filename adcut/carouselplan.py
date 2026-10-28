"""Carousel planning (user, 2026-10-27): decide everything before the first photo, so the shoot doesn't
turn into outfit indecision.

A carousel set on a planned day gets:
- `outfits`: one list of outfits for the whole session (2-5). Outfit N is the SAME companion pieces for every
  product in the set: for a top, the outfit's bottom + shoes (+ layer); for a pair of pants, its top + shoes.
  Suggested from basics and our own lineup, in neutral colours so the item for sale stays the star; editable.
- `texts`: the one line of on-screen text per carousel (product), in @sully.finds' formats ("Fall essential: …",
  "POV: you found the perfect …", a quote), rotated so the day's carousels don't all say the same thing; editable.
Ad Camera's carousel mode shows the current outfit and the text; the shoot page previews each carousel as its
photos come in (photo 1 carries the text)."""
from datetime import date

from . import planner, shop

# the outfit formulas: each slot is a piece of the look; the product being shot replaces its own slot
OUTFITS = [
    {"name": "Clean and light", "top": "white tee", "bottom": "light-wash jeans", "shoes": "white sneakers", "layer": ""},
    {"name": "All dark", "top": "black tee", "bottom": "black jeans", "shoes": "black sneakers", "layer": ""},
    {"name": "Cozy grey", "top": "grey hoodie", "bottom": "grey sweatpants", "shoes": "white sneakers", "layer": ""},
    {"name": "Earth tones", "top": "cream knit", "bottom": "brown pants", "shoes": "brown boots", "layer": ""},
    {"name": "Layered", "top": "white tee", "bottom": "dark jeans", "shoes": "boots", "layer": "open flannel or jacket"},
]
TEXTS = ["{Season} essential: {item}", "POV: you found the perfect {item}", "“I need a good {item} for this {season}”",
         "{Season} pick up: {item}", "{brand} {item} on TikTok Shop", "Rate this {item} fit 1-10"]
RULES = [
    "Decide the outfits before the first photo: they're listed here. Swap a piece only if you don't own it.",
    "Same outfits for every product: outfit 2 is outfit 2 for all of them. Don't restyle per product.",
    "The item for sale is the star: center it, lay it flat and smooth, companions in quieter colours.",
    "Two minutes per photo. If a look isn't working, shoot it anyway and move on: the next take is the fix.",
    "Same spot, same height, same light for every photo (tape the floor), so the carousel looks like one set.",
    "Shoot in order: all outfits for one product, or one outfit across the products, whichever means less unpacking.",
]
TOPS = ("hoodie", "henley", "sweater", "crew", "tee", "shirt", "knit", "jacket")


def kind(p: dict) -> str:
    n = f"{p.get('name', '')} {(p.get('category') or '')}".lower()
    if any(w in n for w in ("pants", "jeans", "sweatpants", "shorts", "bottom")):
        return "bottom"
    return "top" if any(w in n for w in TOPS) else "top"


def item_words(p: dict) -> str:
    """'H&M Loose-Fit Zip Hoodie - Grey Marl' -> 'grey marl zip hoodie' (colour + the item, without the brand)."""
    base, _, color = (p.get("name") or "").partition(" - ")
    brand = p.get("brand") or ""
    if brand and base.startswith(brand):
        base = base[len(brand):]
    words = [w for w in base.replace("-", " ").lower().split() if w not in ("loose", "fit", "long", "sleeve", "90s", "straight", "relaxed")]
    return " ".join(([color.lower()] if color else []) + words).strip()


def default_outfits(n: int) -> list:
    return [dict(o) for o in OUTFITS[:max(2, min(5, n))]]


def default_text(p: dict, i: int, day: str) -> str:
    season = planner.season(date.fromisoformat(day))
    t = TEXTS[i % len(TEXTS)]
    return t.replace("{Season}", season.capitalize()).replace("{season}", season).replace("{item}", item_words(p)).replace("{brand}", p.get("brand") or "")


def with_product(outfit: dict, p: dict) -> str:
    """What to lay out with this product for this outfit: the outfit minus the product's own slot."""
    k = kind(p)
    pieces = [outfit.get(s) for s in ("top", "bottom", "layer", "shoes") if s != k and outfit.get(s)]
    return ", ".join(pieces)


def for_set(day: str, s: dict) -> dict:
    """The carousel plan of one set: outfits, and per product its text and what goes with it in each outfit."""
    sh = shop.load()
    outfits = s.get("outfits") or default_outfits(3)
    texts = s.get("texts") or {}
    rows = []
    for i, it in enumerate(x for x in s["items"] if x["product"]):
        p = shop.by_id(sh, "products", it["product"]) or {}
        rows.append({"product": it["product"], "name": it["name"], "kind": kind(p),
                     "text": texts.get(it["product"]) or default_text(p, i, day),
                     "text_set": it["product"] in texts,
                     "with": [with_product(o, p) for o in outfits]})
    return {"outfits": outfits, "products": rows, "rules": RULES, "outfits_set": bool(s.get("outfits"))}


def update(day: str, set_id: str, body: dict) -> dict:
    d = planner.load()
    if day not in d["days"]:
        planner.generate(day)
        d = planner.load()
    s = next(x for x in d["days"][day]["sets"] if x["id"] == set_id)
    if "outfits" in body:
        s["outfits"] = [{k: str(o.get(k) or "").strip() for k in ("name", "top", "bottom", "shoes", "layer")} for o in body["outfits"]][:5] or None
    if "texts" in body:
        s["texts"] = {k: str(v).strip() for k, v in (body["texts"] or {}).items() if str(v).strip()}
    planner.save(d)
    return for_set(day, s)
