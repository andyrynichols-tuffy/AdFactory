"""Daily planner (Ad Factory → 🗓 Planner): a day built the way @sully.finds works (docs/sully-finds-study.md).

One day = posts per channel (≈20 on weekdays) split by a format mix (carousels for reach, flat-lay
voiceover videos, worn faceless, held item, skit…), each format shot as one *set* (one setup, product after
product, a few near-identical takes each, one script template), then edit, research, and posting slots
spread over the evening window, around gym and meals. Two channels share the products but never footage:
each channel has its own takes (and its own POV wording: "I'm 6'1…" vs "He's 6'1…").
Data: ads/_planner.json {settings, days: {date: plan}}."""
import copy
import json
import math
import threading
from datetime import date, datetime, timedelta

from . import shop, store

FILE = store.SHOOTS_DIR / "_planner.json"
_lock = threading.Lock()
WEARS = {"Men's Jeans": "bottom", "Men's Pants": "bottom"}  # product category -> which size applies (default top)
WORN = {"worn", "skit"}  # formats where the product is on the person
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
FORMATS = [  # share = % of a channel's posts; takes = near-identical takes per product; minutes per take
    {"key": "carousel", "label": "Flat-lay carousel", "setup": "Wood floor, top-down", "share": 25, "takes": 1,
     "take_min": 3.0, "edit_min": 2.0, "tip": "5-7 photos of the item laid flat, one line of on-image text. Brings the reach."},
    {"key": "flatlay_vo", "label": "Flat-lay voiceover video", "setup": "White bed or couch, hand pointing", "share": 30, "takes": 3,
     "take_min": 1.0, "edit_min": 0.7, "tip": "One take, ~20 s, read the sale script while pointing at the item."},
    {"key": "worn", "label": "Worn, faceless", "setup": "Bedroom, waist-down", "share": 20, "takes": 3,
     "take_min": 2.0, "edit_min": 0.7, "tip": "Wear it, film waist-down, say your height and size."},
    {"key": "held", "label": "Holding the item", "setup": "Hand-held close-up (shoes, gadgets, tags)", "share": 10, "takes": 2,
     "take_min": 1.0, "edit_min": 0.7, "tip": "\"I think I just found the perfect…\" Good for side products."},
    {"key": "skit", "label": "Two-person skit / POV", "setup": "Outside or by the car, both of you", "share": 10, "takes": 2,
     "take_min": 2.5, "edit_min": 1.0, "tip": "\"Wait, where'd you get those?\" The same exchange for each product."},
    {"key": "other", "label": "Brand deal / trend / no-product", "setup": "Anything", "share": 5, "takes": 1,
     "take_min": 5.0, "edit_min": 3.0, "tip": "A brand deal or a non-product post that can go wide."},
]
DEFAULTS = {
    "posts": {"mon": 20, "tue": 20, "wed": 20, "thu": 20, "fri": 20, "sat": 5, "sun": 20},
    "mix": {f["key"]: f["share"] for f in FORMATS},
    "takes": {f["key"]: f["takes"] for f in FORMATS},
    "day": {"start": "07:30", "end": "22:00", "post_from": "15:00", "post_to": "20:00", "setup_min": 10,
            "research_min": 30, "gym": {"at": "08:00", "min": 75},
            "meals": [{"name": "Breakfast", "at": "09:20", "min": 20}, {"name": "Lunch", "at": "12:30", "min": 30},
                      {"name": "Dinner", "at": "18:30", "min": 40}]},
    "channels": [],   # [{account, pov: "me" | "partner", height, size_top, size_bottom}]
    "lineup": [],     # product ids in rotation (blank = every product with a TikTok Shop link)
    "scripts": {},    # format -> library script id
}


def _t(s):
    h, m = map(int, s.split(":"))
    return h * 60 + m


def _s(m):
    m = int(round(m))
    return f"{m // 60:02d}:{m % 60:02d}"


def load() -> dict:
    try:
        d = json.loads(FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        d = {}
    d["settings"] = store.deep_merge(DEFAULTS, d.get("settings") or {})
    d.setdefault("days", {})
    return d


def save(d):
    with _lock:
        tmp = FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(FILE)


def set_settings(changes: dict) -> dict:
    d = load()
    d["settings"] = store.deep_merge(d["settings"], changes)
    for k in ("lineup", "channels", "meals"):  # lists are replaced, not merged
        if k in changes:
            d["settings"][k] = changes[k]
    if "day" in changes and "meals" in changes["day"]:
        d["settings"]["day"]["meals"] = changes["day"]["meals"]
    save(d)
    return d["settings"]


def season(day: date) -> str:
    return {12: "winter", 1: "winter", 2: "winter", 3: "spring", 4: "spring", 5: "spring",
            6: "summer", 7: "summer", 8: "summer"}.get(day.month, "fall")


def _split(n, mix):
    """n posts by the mix's shares (largest remainders), keys in FORMATS order."""
    tot = sum(max(0, mix.get(f["key"], 0)) for f in FORMATS) or 1
    raw = {f["key"]: n * max(0, mix.get(f["key"], 0)) / tot for f in FORMATS}
    out = {k: int(v) for k, v in raw.items()}
    for k in sorted(raw, key=lambda k: -(raw[k] - out[k]))[: n - sum(out.values())]:
        out[k] += 1
    return out


def _lineup(st, sh):
    from .productlink import is_shop_link
    ps = {p["id"]: p for p in sh["products"] if not p.get("archived")}
    ids = [i for i in st["lineup"] if i in ps] or [i for i, p in ps.items() if is_shop_link(p.get("link"))] or list(ps)
    return [ps[i] for i in ids]


def _channels(st, sh):
    chans = [c for c in st["channels"] if shop.by_id(sh, "accounts", c.get("account"))]
    if not chans:  # every account, one POV each (the first is "me")
        chans = [{"account": a["id"], "pov": "me"} for a in sh["accounts"]]  # each person films and talks about themselves
    return chans or [{"account": None, "pov": "me"}]


def generate(day_iso: str) -> dict:
    """A fresh plan for one date (kept: which posts are already marked done)."""
    d, sh = load(), shop.load()
    st = d["settings"]
    day = date.fromisoformat(day_iso)
    n = int(st["posts"].get(WEEKDAYS[day.weekday()], 0))
    lineup, chans = _lineup(st, sh), _channels(st, sh)
    fmt = {f["key"]: f for f in FORMATS}
    sets, posts = [], []
    offset = (day.toordinal() * 7) % max(1, len(lineup))  # a different starting product each day
    for ci, ch in enumerate(chans):
        acc = shop.by_id(sh, "accounts", ch.get("account"))
        counts = _split(n, st["mix"])
        skip = set(ch.get("cant_wear") or [])  # products this channel's person can't wear (too big…)
        wearable = [p for p in lineup if p["id"] not in skip] or lineup
        for key, cnt in counts.items():
            if not cnt:
                continue
            f = fmt[key]
            takes = max(1, int(st["takes"].get(key, f["takes"])))
            k_products = max(1, math.ceil(cnt / takes))
            items, left = [], cnt
            pool = wearable if key in WORN else lineup
            for j in range(k_products):
                p = pool[(offset + ci * 3 + j + len(sets)) % len(pool)] if pool else None
                t = min(takes, left)
                left -= t
                pid = p["id"] if p else None
                same = next((it for it in items if it["product"] == pid), None)  # short lineup: more takes, not a repeat row
                if same:
                    same["takes"] += t
                else:
                    items.append({"product": pid, "name": p["name"] if p else "(pick a product)", "takes": t})
            sid = f"{key}-{ci}"
            sets.append({"id": sid, "format": key, "label": f["label"], "setup": f["setup"], "tip": f["tip"],
                         "channel": ch.get("account"), "channel_name": (acc or {}).get("name") or f"Channel {ci + 1}",
                         "pov": ch.get("pov", "me"), "items": items, "posts": cnt,
                         "script": st["scripts"].get(key), "minutes": round(st["day"]["setup_min"] + cnt * f["take_min"]),
                         "edit_minutes": round(cnt * f["edit_min"]), "projects": []})
            for it in items:
                for _ in range(it["takes"]):
                    posts.append({"set": sid, "format": key, "channel": ch.get("account"), "product": it["product"],
                                  "name": it["name"], "done": False})
    # same-setup sets of both channels are shot back to back
    order = {f["key"]: i for i, f in enumerate(FORMATS)}
    sets.sort(key=lambda s: (order[s["format"]], s["channel"] or ""))
    # posting slots: spread over the window, channels interleaved, near-identical takes apart
    by_ch = {}
    for p in posts:
        by_ch.setdefault(p["channel"], []).append(p)
    for ch_id, lst in by_ch.items():  # deal the formats out in turn so the evening mixes them (and repeats sit apart)
        groups = {}
        for p in lst:
            groups.setdefault(p["format"], []).append(p)
        dealt = []
        while any(groups.values()):
            for g in list(groups.values()):
                if g:
                    dealt.append(g.pop(0))
        by_ch[ch_id] = dealt
    a, b = _t(st["day"]["post_from"]), _t(st["day"]["post_to"])
    for lst in by_ch.values():
        gap = (b - a) / max(1, len(lst))
        for k, p in enumerate(lst):
            p["time"] = _s(a + gap * k + gap / 2)
    posts = sorted(posts, key=lambda p: (p["time"], p["channel"] or ""))
    old = d["days"].get(day_iso) or {}
    done = {(p["set"], p["product"], k) for k, p in enumerate(old.get("posts") or []) if p.get("done")}
    for k, p in enumerate(posts):
        p["done"] = (p["set"], p["product"], k) in done
    plan = {"date": day_iso, "season": season(day), "posts_per_channel": n, "channels": len(chans),
            "sets": sets, "posts": posts, "blocks": _blocks(st, sets, len(posts)), "generated": datetime.now().isoformat(timespec="minutes")}
    for s in sets:  # projects made earlier for this set stay linked
        s["projects"] = next((x.get("projects", []) for x in old.get("sets") or [] if x["id"] == s["id"]), [])
    d["days"][day_iso] = plan
    save(d)
    return plan


def _blocks(st, sets, n_posts):
    """The day as blocks: fixed ones (gym, meals), then shoots, edit, research, around them; posting window."""
    day = st["day"]
    fixed = [{"kind": "gym", "title": "Gym", "start": _t(day["gym"]["at"]), "end": _t(day["gym"]["at"]) + day["gym"]["min"]}] \
        if day.get("gym") and day["gym"].get("min") else []
    fixed += [{"kind": "meal", "title": m["name"], "start": _t(m["at"]), "end": _t(m["at"]) + m["min"]} for m in day["meals"]]
    post_from, post_to = _t(day["post_from"]), _t(day["post_to"])
    work = [{"kind": "shoot", "title": f"Shoot: {s['label']} · {s['channel_name']}", "min": s["minutes"], "set": s["id"]} for s in sets]
    edit = sum(s["edit_minutes"] for s in sets)
    work.append({"kind": "edit", "title": f"Edit + review ({n_posts} posts: carousels assembled, videos checked)", "min": edit})
    work.append({"kind": "research", "title": "Research: Analytics, competitor tracker, next lineup", "min": day["research_min"]})
    busy = sorted(fixed, key=lambda x: x["start"])
    out, t = list(fixed), _t(day["start"])
    for w in work:
        need = w["min"]
        while need > 0:  # fill free time, split around fixed blocks and the posting window
            nxt = min([x for x in busy if x["end"] > t] + [{"start": 10 ** 6, "end": 10 ** 6}], key=lambda x: x["start"])
            if nxt["start"] <= t:
                t = nxt["end"]
                continue
            if nxt["start"] - t < min(need, 20):  # too short a gap to start a block in: go past it
                t = nxt["end"]
                continue
            stop = min(nxt["start"], t + need)
            out.append({"kind": w["kind"], "title": w["title"], "start": t, "end": stop, **({"set": w["set"]} if w.get("set") else {})})
            need -= stop - t
            t = stop
    out.append({"kind": "post", "title": f"Posting window: {n_posts} posts, one every ~{max(1, round((post_to - post_from) / max(1, n_posts / max(1, len({s['channel'] for s in sets})))))} min per channel",
                "start": post_from, "end": post_to})
    out.sort(key=lambda x: (x["start"], x["kind"] != "post"))
    for x in out:
        x["start"], x["end"] = _s(x["start"]), _s(x["end"])
    return out


def get(day_iso: str) -> dict:
    d = load()
    return d["days"].get(day_iso) or generate(day_iso)


def mark(day_iso: str, k: int, done: bool) -> dict:
    d = load()
    plan = d["days"].get(day_iso)
    if plan and 0 <= k < len(plan["posts"]):
        plan["posts"][k]["done"] = bool(done)
        save(d)
    return plan


def make_projects(day_iso: str, set_id: str) -> list:
    """One Ad Camera project per product in the set (its takes = the script, filmed that many times)."""
    d, sh = load(), shop.load()
    plan = d["days"].get(day_iso) or generate(day_iso)
    s = next(x for x in plan["sets"] if x["id"] == set_id)
    chan = next((c for c in _channels(d["settings"], sh) if c.get("account") == s["channel"]), {})
    sc = shop.by_id(sh, "scripts", s.get("script"))
    label = datetime.fromisoformat(day_iso).strftime("%b %d").replace(" 0", " ")
    made = []
    for it in s["items"]:
        if not it["product"]:
            continue
        p = shop.by_id(sh, "products", it["product"]) or {}
        # size: the channel's own (one usual size) or else the sample's tag size, with how it wears (M fitted, L looser)
        own = chan.get("size_bottom") if WEARS.get(p.get("category"), "top") == "bottom" else chan.get("size_top")
        size = own or (p.get("fills") or {}).get("size") or ""
        fit_note = "" if own else {"S": "for a more fitted look", "M": "for a more fitted look", "L": "for a looser fit", "XL": "for a looser fit"}.get(size.upper(), "")
        f = p.get("fills") or {}
        base, _, color = (p.get("name") or "").partition(" - ")  # "H&M Zip Hoodie - Grey Marl" -> said as "… in grey marl"
        plural = WEARS.get(p.get("category"), "top") == "bottom"
        brand = p.get("brand") or ""
        spoken = base[len(brand):].strip() if brand and base.startswith(brand) else base  # the brand is said on its own
        vars_ = {"season": plan["season"], "who": "I'm" if s["pov"] == "me" else "He's",
                 "product": (f"{spoken} in {color.lower()}" if color else spoken), "item": (f.get("style") or p.get("category") or "").lower(),
                 "height": chan.get("height") or "", "size": size, "fit note": fit_note,
                 "it": "them" if plural else "it", "it fits": "they fit" if plural else "it fits", "It is": "They're" if plural else "It's",
                 "It has": "They've got" if plural else "It's got", "This is": "These are" if plural else "This is"}
        r = shop.new_video({"product": it["product"], "account": s["channel"], "script": sc["id"] if sc else None,
                            "script_text": sc["text"] if sc else "", "vars": vars_, "assign": True,
                            "title": f"{label} · {s['label']} · {it['name'][:28]}",
                            "notes": f"{s['setup']}. {it['takes']} take{'s' if it['takes'] != 1 else ''}, near-identical. {s['tip']}"})
        made.append({"sid": r["id"], "title": r["title"], "product": it["product"]})
    s["projects"] = s.get("projects", []) + made
    d["days"][day_iso] = plan
    save(d)
    return made


# ---------------------------------------------------------------- script templates (our own wording)

TEMPLATES = [  # {it}/{It is}/{This is}… follow the item: "it" for a top, "they" for pants (see make_projects).
    # No "on sale" / "free shipping" claims: TikTok prices often sit above the tag. Add them per video when true.
    ("flatlay_vo", "Sale news (flat-lay voiceover)",
     "{brand} finally has their {product} on TikTok Shop.\n"
     "{It has} that {feature 1} that goes with literally any fit.\n"
     "You can grab {it} for {price} right now.\n"
     "I'll leave the link right here before your size sells out."),
    ("worn", "Height + size (worn, faceless)",
     "Just in time for this {season}: the {brand} {product}.\n"
     "{who} {height}, wearing a size {size} {fit note}, and this is exactly how {it fits}.\n"
     "The {feature 1} goes with everything.\n"
     "{It is} on TikTok Shop right now, link's right here."),
    ("held", "I just found the perfect one (held item)",
     "I think I just found the perfect {item} for this {season}.\n"
     "{This is} the {brand} {product}, and the {feature 1} is honestly so good.\n"
     "{It is} on TikTok Shop, link's right here."),
    ("skit", "Where'd you get those? (two-person skit)",
     "A: Wait, I love your {item}. Where'd you get {it}?\n"
     "B: {brand}. I got {it} on TikTok Shop.\n"
     "A: For real? How much?\n"
     "B: {price}. The link's right there.\n"
     "A: Okay, send it to me."),
    ("carousel", "On-image text (carousel)",
     "{season} essential: {item}\n"
     "[or] POV: you found the perfect {item} for any fit\n"
     "[or] \"I need a good {item} for this {season}\""),
]


def seed_templates():
    """The planner's scripts, once: in the library (tagged), linked per format."""
    d, sh = load(), shop.load()
    have = {s["title"]: s["id"] for s in sh["scripts"]}
    tag = {t["name"]: t["id"] for t in sh["tags"]}
    tags = {"flatlay_vo": ["Demo", "Price hook"], "worn": ["Try-on"], "held": ["Demo"], "skit": ["Skit", "Funny"], "carousel": ["Price hook"]}
    for key, title, text in TEMPLATES:
        sid = have.get(title)
        if sid and (shop.by_id(sh, "scripts", sid) or {}).get("notes", "").startswith("Planner template"):
            shop.upsert("scripts", {"id": sid, "text": text})  # keep the library copy in step with the template
        sid = sid or shop.upsert("scripts", {"title": title, "text": text, "tags": [tag[n] for n in tags.get(key, []) if n in tag],
                                                          "notes": "Planner template, modelled on @sully.finds (docs/sully-finds-study.md)"})["id"]
        d["settings"]["scripts"].setdefault(key, sid)
    save(d)
    return d["settings"]["scripts"]
