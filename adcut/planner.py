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
import re
import threading
from datetime import date, datetime, timedelta

from . import shop, store

FILE = store.SHOOTS_DIR / "_planner.json"
_lock = threading.Lock()
WEARS = {"Men's Jeans": "bottom", "Men's Pants": "bottom"}  # product category -> which size applies (default top)
WORN = {"worn", "skit"}  # formats where the product is on the person
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
FORMATS = [  # lighting notes are for the kit: one large round key light + two rectangle fill panels.
    # share = % of a channel's posts; takes = near-identical takes per product; minutes per take
    {"key": "carousel", "label": "Flat-lay carousel", "setup": "Wood floor, top-down", "share": 25, "takes": 1,
     "take_min": 15.0, "edit_min": 3.0, "light_min": 15, "light": "Key (circle) high above one end of the outfit, angled down at 45°, ~70%. Fill panel 1 low on the opposite side, ~30%, to soften shadows. Fill panel 2 off, or low across the far end if the floor looks uneven. Room lights off, all three at 5600K. Phone straight above; lock exposure and white balance; same spot every carousel.",
     "example": "https://www.tiktok.com/@sully.finds/photo/7690393439048961311",
     "tip": "2-5 photos, each a different outfit laid flat around the item for sale (it's the star of every photo), one line of on-image text. Brings the reach."},
    {"key": "flatlay_vo", "label": "Flat-lay voiceover video", "setup": "White bed or couch, hand pointing", "share": 30, "takes": 3,
     "take_min": 1.0, "edit_min": 0.7, "light_min": 10, "light": "Key (circle) at 45° to one side of the bed, above it, ~60%. Fill panel 1 on the other side, ~30%. Fill panel 2 above or behind the bed, low, so the white sheets light evenly. Tap to lock, then drop exposure a touch so the whites don't blow out. Don't move anything between takes.",
     "example": "https://www.tiktok.com/@sully.finds/video/7690604593834757407",
     "tip": "One take, ~20 s, read the sale script while pointing at the item."},
    {"key": "worn", "label": "Worn, faceless", "setup": "Bedroom, waist-down", "share": 20, "takes": 3,
     "take_min": 2.0, "edit_min": 0.7, "light_min": 15, "light": "Key (circle) in front at 45°, center at chest height, tilted down toward the waist, ~70%. Fill panel 1 on the other side, ~35%, so the fabric shows. Fill panel 2 behind and to the side, low, as a rim light that outlines the fit against the background. Never a window behind you. Tape a mark on the floor so every take matches.",
     "example": "https://www.tiktok.com/@sully.finds/video/7697808464344648991",
     "tip": "Wear it, film waist-down, say your height and size."},
    {"key": "held", "label": "Holding the item", "setup": "Hand-held close-up (shoes, gadgets, tags)", "share": 10, "takes": 2,
     "take_min": 1.0, "edit_min": 0.7, "light_min": 8, "light": "Key (circle) close and low to one side, grazing across the item, ~50%, so the knit or waffle texture pops. Fill panel 1 opposite, ~20%. Fill panel 2 off. Keep your hand and phone from shadowing the item; plain background.",
     "example": "https://www.tiktok.com/@sully.finds/video/7700700082219339039",
     "tip": "\"I think I just found the perfect…\" Good for side products."},
    {"key": "skit", "label": "Two-person skit / POV", "setup": "Outside or by the car, both of you", "share": 10, "takes": 2,
     "take_min": 2.5, "edit_min": 1.0, "light_min": 10, "light": "Outside: no lights; open shade (the shady side of the house or car) or golden hour, both of you facing the light. Inside: key (circle) in front between you, ~70%; one fill panel at 45° on each side, ~35%, so both of you are lit the same.",
     "example": "https://www.tiktok.com/@sully.finds/video/7699977637917183263",
     "tip": "\"Wait, where'd you get those?\" The same exchange for each product."},
    {"key": "other", "label": "My new favorite (extra)", "setup": "Anything", "share": 5, "takes": 1,
     "take_min": 5.0, "edit_min": 3.0, "light_min": 10, "light": "Match the setup it borrows: key (circle) at 45°, fill panel opposite at about half power, second panel as rim or off. All at 5600K, room lights off.",
     "example": "https://www.tiktok.com/@sully.finds/video/7700043209048739103",
     "tip": "His 'new favorite' script on one product, the fifth kind of post in the mix."},
]
DEFAULTS = {
    "posts": {"mon": 20, "tue": 20, "wed": 20, "thu": 20, "fri": 20, "sat": 5, "sun": 20},
    "mix": {f["key"]: f["share"] for f in FORMATS},
    "takes": {f["key"]: f["takes"] for f in FORMATS},
    "day": {"start": "07:30", "end": "22:00", "post_from": "15:00", "post_to": "20:00", "setup_min": 10,
            "research_min": 30, "gym": {"at": "08:00", "min": 75},
            "schedule": True, "schedule_min": 1.5,
            "prep_min": 30,  # pull the day's pieces, steam, de-lint, remove tags, set up the floor + bed  # schedule the day's posts in TikTok Studio right after editing
            "meals": [{"name": "Breakfast", "at": "09:20", "min": 20}, {"name": "Lunch", "at": "12:30", "min": 30},
                      {"name": "Dinner", "at": "18:30", "min": 40}]},
    "channels": [],   # [{account, pov: "me" | "partner", height, size_top, size_bottom}]
    "lineup": [],     # product ids in rotation (blank = every product with a TikTok Shop link)
    "scripts": {},    # format -> library script id
    "mode": "batch",  # "batch": one format per shoot day, its posts scheduled over the next week; "daily": each day shoots its own posts
    "carousels": False,  # the account can post photo carousels (TikTok's slow rollout): off = videos fill their slots
    "batch_week": None,  # weekday -> formats shot that day (None = BATCH_WEEK)
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
    for k in ("lineup", "channels", "meals", "batch_week"):  # replaced whole, not merged
        if k in changes:
            d["settings"][k] = changes[k]
    if "day" in changes and "meals" in changes["day"]:
        d["settings"]["day"]["meals"] = changes["day"]["meals"]
    save(d)
    return d["settings"]


def season(day: date) -> str:
    return {12: "winter", 1: "winter", 2: "winter", 3: "spring", 4: "spring", 5: "spring",
            6: "summer", 7: "summer", 8: "summer"}.get(day.month, "fall")


def _mix(st) -> dict:
    """The format mix in use: without carousel access (a slow TikTok rollout), carousels get nothing and the
    video formats share their posts (_split normalises the shares)."""
    m = dict(st["mix"])
    if not st.get("carousels", False):
        m["carousel"] = 0
    return m


def _split(n, mix):
    """n posts by the mix's shares (largest remainders), keys in FORMATS order."""
    tot = sum(max(0, mix.get(f["key"], 0)) for f in FORMATS) or 1
    raw = {f["key"]: n * max(0, mix.get(f["key"], 0)) / tot for f in FORMATS}
    out = {k: int(v) for k, v in raw.items()}
    for k in sorted(raw, key=lambda k: -(raw[k] - out[k]))[: n - sum(out.values())]:
        out[k] += 1
    return out


def _mins(st, key, which):
    """Minutes per post for a format: the settings' override (minutes: {key: {take_min, edit_min}}) or the default."""
    return float(((st.get("minutes") or {}).get(key) or {}).get(which) or next(f[which] for f in FORMATS if f["key"] == key))


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
    if st.get("mode", "batch") == "batch":
        return _finish(d, st, day_iso, day, *_batch(st, sh, day, d["days"].get(day_iso) or {}))
    n = int(st["posts"].get(WEEKDAYS[day.weekday()], 0))
    lineup, chans = _lineup(st, sh), _channels(st, sh)
    fmt = {f["key"]: f for f in FORMATS}
    sets, posts = [], []
    offset = (day.toordinal() * 7) % max(1, len(lineup))  # a different starting product each day
    for ci, ch in enumerate(chans):
        acc = shop.by_id(sh, "accounts", ch.get("account"))
        counts = _split(n, _mix(st))
        skip = set(ch.get("cant_wear") or [])  # products this channel's person can't wear (too big…)
        wearable = [p for p in lineup if p["id"] not in skip] or lineup
        if counts.get("carousel") and lineup:  # one carousel per product (they're shot together, one clothing type)
            from .carouselplan import kind
            s0 = (offset + ci * 3) % len(lineup)
            types = sum(1 for x in lineup if kind(x) == kind(lineup[s0]))
            if counts["carousel"] > types:
                counts["flatlay_vo"] = counts.get("flatlay_vo", 0) + counts["carousel"] - types
                counts["carousel"] = types
        for key, cnt in counts.items():
            if not cnt:
                continue
            f = fmt[key]
            takes = max(1, int(st["takes"].get(key, f["takes"])))
            k_products = max(1, math.ceil(cnt / takes))
            items, left = [], cnt
            pool = wearable if key in WORN else lineup
            start = offset + ci * 3 + len(sets)
            if key == "carousel" and pool:  # one clothing type per carousel shoot: the same extra pieces all session (user)
                from .carouselplan import kind
                k0 = kind(pool[start % len(pool)])
                same = [x for x in pool[start % len(pool):] + pool[:start % len(pool)] if kind(x) == k0]
                pool, start = same or pool, 0
            for j in range(k_products):
                p = pool[(start + j) % len(pool)] if pool else None
                t = cnt // k_products + (1 if j < cnt % k_products else 0)  # even split: 4 posts = 2 + 2, not 3 + 1
                left -= t
                pid = p["id"] if p else None
                same = next((it for it in items if it["product"] == pid), None)  # short lineup: more takes, not a repeat row
                if same:
                    same["takes"] += t
                else:
                    items.append({"product": pid, "name": p["name"] if p else "(pick a product)", "takes": t})
            sid = f"{key}-{ci}"
            sets.append({"id": sid, "format": key, "label": f["label"], "setup": f["setup"], "tip": f["tip"], "light": f["light"], "example": (st.get("examples") or {}).get(key) or f.get("example", ""), "light_min": round(_mins(st, key, "light_min")),
                         "channel": ch.get("account"), "channel_name": (acc or {}).get("name") or f"Channel {ci + 1}",
                         "pov": ch.get("pov", "me"), "items": items, "posts": cnt,
                         "script": st["scripts"].get(key), "minutes": round(_mins(st, key, "light_min") + cnt * _mins(st, key, "take_min")),
                         "edit_minutes": round(cnt * _mins(st, key, "edit_min")), "projects": []})
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
    for p in posts:
        p["date"] = day_iso
    return _finish(d, st, day_iso, day, sets, posts, (day_iso, day_iso), [s["format"] for s in sets])


def _finish(d, st, day_iso, day, sets, posts, window, fmts):
    """Shared by daily and batch days: keep ticks, projects, examples and carousel plans across a rebuild."""
    old = d["days"].get(day_iso) or {}
    done = {(p["set"], p["product"], p.get("date"), p["time"]) for p in old.get("posts") or [] if p.get("done")}
    for p in posts:
        p["done"] = (p["set"], p["product"], p.get("date"), p["time"]) in done
    batch = st.get("mode", "batch") == "batch"
    plan = {"date": day_iso, "season": season(day), "mode": "batch" if batch else "daily", "window": list(window), "formats": fmts,
            "posts_per_channel": int(st["posts"].get(WEEKDAYS[day.weekday()], 0)), "channels": len(_channels(st, shop.load())),
            "sets": sets, "posts": posts, "blocks": _blocks(st, sets, len(posts), batch=batch, window=window),
            "generated": datetime.now().isoformat(timespec="minutes")}
    plan["blocks_done"] = [k for k in old.get("blocks_done") or [] if any(block_key(b) == k for b in plan["blocks"])]
    for s in sets:  # projects made earlier for this set stay linked, and an example picked for this day
        prev = next((x for x in old.get("sets") or [] if x["id"] == s["id"]), {})
        have = {(it["product"], s.get("variant", 0)) for it in s["items"]}
        s["projects"] = [pr for pr in prev.get("projects", []) if (pr["product"], pr.get("variant", 0)) in have]  # this set's products, this version
        if prev.get("example_set"):
            s["example"], s["example_set"] = prev["example"], True
        for k in ("outfits", "texts"):  # the carousel plan (adcut/carouselplan.py) survives a rebuild
            if prev.get(k):
                s[k] = prev[k]
    d["days"][day_iso] = plan
    save(d)
    return plan


def _blocks(st, sets, n_posts, batch=False, window=None):
    """The day as blocks: fixed ones (gym, meals), then shoots, edit, research, around them; posting window."""
    day = st["day"]
    fixed = [{"kind": "gym", "title": "Gym", "start": _t(day["gym"]["at"]), "end": _t(day["gym"]["at"]) + day["gym"]["min"]}] \
        if day.get("gym") and day["gym"].get("min") else []
    fixed += [{"kind": "meal", "title": m["name"], "start": _t(m["at"]), "end": _t(m["at"]) + m["min"]} for m in day["meals"]]
    post_from, post_to = _t(day["post_from"]), _t(day["post_to"])
    work = [{"kind": "prep", "title": "Prep: pull the day's pieces, steam, de-lint, tags off, set up the floor + bed",
             "min": int(day.get("prep_min", 30))}] if day.get("prep_min", 30) else []
    work += [{"kind": "shoot", "title": f"Shoot: {s['label']} · {s['channel_name']}", "min": s["minutes"], "set": s["id"]} for s in sets]
    edit = sum(s["edit_minutes"] for s in sets)
    work.append({"kind": "edit", "title": f"Edit + review ({n_posts} posts: carousels assembled, videos checked)", "min": edit})
    sched = day.get("schedule", True)
    if sched:  # posts go out on their own at their times: one sitting instead of an evening of posting
        span = f", {_short(window[0])} to {_short(window[1])}" if batch and window else ""
        work.append({"kind": "post", "title": f"Schedule this batch: {n_posts} posts in TikTok Studio{span} (dates and times in the posting kit)",
                     "min": math.ceil(n_posts * float(day.get("schedule_min", 1.5)))})
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
    if batch:
        pass  # a batch is scheduled for the coming days; what goes live today came from earlier batches
    elif sched:
        out.append({"kind": "live", "title": f"Scheduled posts go live: {n_posts}, nothing to do", "start": post_from, "end": post_to})
    else:
        out.append({"kind": "post", "title": f"Posting window: {n_posts} posts, one every ~{max(1, round((post_to - post_from) / max(1, n_posts / max(1, len({s['channel'] for s in sets})))))} min per channel",
                    "start": post_from, "end": post_to})
    out.sort(key=lambda x: (x["start"], x["kind"] not in ("post", "live")))
    for x in out:
        x["start"], x["end"] = _s(x["start"]), _s(x["end"])
    return out


def _short(iso: str) -> str:
    return date.fromisoformat(iso).strftime("%a %b %d").replace(" 0", " ")


def block_key(b: dict) -> str:
    """A block's identity for check-offs: kind + set (or title) + start, so a rebuild keeps the ticks that still apply."""
    return f"{b['kind']}|{b.get('set') or b['title']}|{b['start']}"


def mark_block(day_iso: str, key: str, done: bool) -> dict:
    d = load()
    plan = d["days"].get(day_iso)
    if plan:
        have = [k for k in plan.get("blocks_done") or [] if k != key]
        plan["blocks_done"] = have + ([key] if done else [])
        save(d)
    return plan


def set_example(day_iso: str, set_id: str, url: str) -> dict:
    """The video to copy for one set on one day (blank = back to the format's default)."""
    if day_iso not in load()["days"]:
        generate(day_iso)
    d = load()
    plan = d["days"][day_iso]
    s = next(x for x in plan["sets"] if x["id"] == set_id)
    fmt = next(f for f in FORMATS if f["key"] == s["format"])
    s["example"], s["example_set"] = (url.strip(), True) if url.strip() else ((d["settings"].get("examples") or {}).get(s["format"]) or fmt.get("example", ""), False)
    save(d)
    return s


def project_index() -> dict:
    """{shoot id: {day, set, format}} for every project the planner made (Ad Camera's carousel mode)."""
    out = {}
    for day, plan in load()["days"].items():
        for s in plan.get("sets") or []:
            for pr in s.get("projects") or []:
                out[pr["sid"]] = {"day": day, "set": s["id"], "format": s["format"], "product": pr["product"]}
    return out


def days() -> list:
    """Every planned day, oldest first: posts, sets, Ad Camera projects made, what's ticked off."""
    out = []
    for k, p in sorted(load()["days"].items()):
        out.append({"date": k, "posts": len(p.get("posts") or []), "sets": len(p.get("sets") or []),
                    "projects": sum(len(s.get("projects") or []) for s in p.get("sets") or []),
                    "posted": sum(1 for x in p.get("posts") or [] if x.get("done")),
                    "blocks": len(p.get("blocks") or []), "blocks_done": len(p.get("blocks_done") or [])})
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


def _vars(plan, s, chan, p) -> dict:
    """Everything a script template can ask for, for one product on one channel."""
    own = chan.get("size_bottom") if WEARS.get(p.get("category"), "top") == "bottom" else chan.get("size_top")
    size = own or (p.get("fills") or {}).get("size") or ""
    fit_note = "" if own else {"S": "for a more fitted look", "M": "for a more fitted look", "L": "for a looser fit", "XL": "for a looser fit"}.get(size.upper(), "")
    f = p.get("fills") or {}
    base, _, color = (p.get("name") or "").partition(" - ")  # "H&M Zip Hoodie - Grey Marl" -> said as "… in grey marl"
    plural = WEARS.get(p.get("category"), "top") == "bottom"
    brand = p.get("brand") or ""
    spoken = base[len(brand):].strip() if brand and base.startswith(brand) else base  # the brand is said on its own
    feature = f.get("feature 1") or f.get("material") or f.get("fit") or f.get("style") or "fit"
    noun = (f.get("style") or "").lower().split()[-1:] or [(p.get("category") or "piece").lower().split()[-1]]
    noun = " ".join((f.get("style") or "").lower().split()[-2:]) if plural or len((f.get("style") or "").split()) > 1 else noun[0]
    second = next((c for c in (f.get("feature 2"), f.get("fit"), f.get("material"), f.get("style"))
                   if c and c.lower() not in feature.lower() and feature.lower() not in c.lower()), "easy fit")
    return {**shop.product_fills(p), "season": plan["season"], "who": "I'm" if s["pov"] == "me" else "He's",
            "product": (f"{spoken} in {color.lower()}" if color else spoken), "item": (f.get("style") or p.get("category") or "piece").lower(),
            "height": chan.get("height") or "", "size": size, "fit note": fit_note, "feature 1": feature,
            "feature 2": second, "the feature": f"that {feature}", "brand": brand or "this brand",
            "color": (color or f.get("color") or "").lower() or "new", "deal": f.get("deal") or "", "store price": f.get("store price") or "way more",
            "with free shipping": " with free shipping" if f.get("free shipping") == "1" else " ",
            "and shipping is free": ", and shipping is free right now" if f.get("free shipping") == "1" else " ",
            "this pair": "this pair" if plural else "this one", "that item": f"{'those' if plural else 'that'} {noun}",
            "those must have been": "Those must have been" if plural else "That must have been",
            "this is": "These are" if plural else "This is",
            "price": p.get("price") or "a great price",
            "it": "them" if plural else "it", "it fits": "they fit" if plural else "it fits", "It is": "They're" if plural else "It's",
            "It has": "They've got" if plural else "It's got", "This is": "These are" if plural else "This is"}


def _tidy(line: str) -> str:
    """Last resort for a blank nothing could fill: drop it and the gap it leaves (never hand over '{…}')."""
    line = shop.PH_RX.sub("", line)
    line = re.sub(r"\s+([,.!?])", r"\1", re.sub(r"\s{2,}", " ", line)).strip()
    return re.sub(r"^(wearing a size|in|the)\s*[,.]", "", line).strip()


def script_for(day_iso: str, s: dict, product_id: str, plan=None, variant: int = 0) -> list:
    """The complete script for one product in one set, line by line, nothing left to fill in.
    Carousels: the carousel's one line of on-screen text (adcut/carouselplan.py)."""
    d, sh = load(), shop.load()
    plan = plan or d["days"].get(day_iso) or generate(day_iso)
    p = shop.by_id(sh, "products", product_id) or {}
    if s["format"] == "carousel":
        from . import carouselplan
        row = next((r for r in carouselplan.for_set(day_iso, s)["products"] if r["product"] == product_id), None)
        return [row["text"]] if row else []
    chan = next((c for c in _channels(d["settings"], sh) if c.get("account") == s["channel"]), {})
    ids = [x for x in s.get("scripts") or [] if x] or [s.get("script")]
    sc = shop.by_id(sh, "scripts", ids[variant % len(ids)])
    v = _vars(plan, s, chan, p)
    deal = bool(v.get("deal"))
    lines = []
    for ln in (sc["text"] if sc else "").splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("[or]") or (ln.startswith("[deal]") and not deal) or (ln.startswith("[nodeal]") and deal):
            continue
        lines.append(shop.fill(re.sub(r"^\[(no)?deal\]\s*", "", ln), v))
    return [_tidy(ln) for ln in lines if _tidy(ln)]


def make_projects(day_iso: str, set_id: str) -> list:
    """Ad Camera projects for a set: one per product, with this week's version of the script, filmed as many times
    as the product posts (near-identical takes, posted on different days)."""
    d = load()
    plan = d["days"].get(day_iso) or generate(day_iso)
    s = next(x for x in plan["sets"] if x["id"] == set_id)
    label = datetime.fromisoformat(day_iso).strftime("%b %d").replace(" 0", " ")
    ids = [x for x in s.get("scripts") or [] if x] or [s.get("script")]
    made = []
    v = s.get("variant", 0)
    done = {pr["product"] for pr in s.get("projects") or [] if pr.get("variant", 0) == v}
    for it in s["items"]:
        if not it["product"] or it["product"] in done:
            continue
        lines = script_for(day_iso, s, it["product"], plan, variant=v)
        r = shop.new_video({"product": it["product"], "account": s["channel"], "script": ids[v % len(ids)],
                            "script_text": "\n".join(lines), "assign": True,
                            "title": f"{label} · {s['label']} · {it['name'][:28]}",
                            "notes": f"{s['setup']}. {it['takes']} take{'s' if it['takes'] != 1 else ''}, near-identical. {s['tip']}\nLighting: {s.get('light', '')}"})
        made.append({"sid": r["id"], "title": r["title"], "product": it["product"], "variant": v})
    s["projects"] = s.get("projects", []) + made
    d["days"][day_iso] = plan
    save(d)
    return made


# ---------------------------------------------------------------- script templates (our own wording)

TEMPLATES = [  # @sully.finds' own scripts, copied from the example each format links (study transcripts), with
    # only the product swapped in. Lines starting [deal] are used only when the product has a real deal
    # (product fill "deal", e.g. "over half off with free shipping"), [nodeal] lines only when it doesn't:
    # no made-up sale claims (TikTok Shop pulls misleading ones).
    ("flatlay_vo", "Sale news (flat-lay voiceover)",  # example 7690604593834757407, 387K views
     "[deal] {brand} is finally dumping their {item} on their TikTok shop.\n"
     "[nodeal] {brand} finally put their {item} on their TikTok shop.\n"
     "You're gonna get that super nice {feature 1} as well as the {feature 2}, and I just love this {color} colorway, it's gonna be perfect for this {season} season.\n"
     "{who} {height}, rocking a size {size}.\n"
     "[deal] These are selling out quick since they're {deal}, so if you wanna see if your size is still available, I'll leave a link down below.\n"
     "[nodeal] These are selling out quick{and shipping is free}, so if you wanna see if your size is still available, I'll leave a link down below."),
    ("worn", "Height + size (worn, faceless)",  # example 7697808464344648991, 79K views
     "[deal] {brand} is finally dumping their {item} on their TikTok shop.\n"
     "[nodeal] {brand} finally put their {item} on their TikTok shop.\n"
     "[deal] Just don't drop {store price} in store when you can pick {them} up for {deal} on TikTok.\n"
     "{This is} their {product}, so you're definitely going to get that {feature 1} with {this pair}.\n"
     "{who} {height}, rocking a size {size} in {this pair} {fit note}.\n"
     "So I'd definitely recommend going true to size, but their most popular sizes are going quick.\n"
     "So if you're seeing this in time and your size is still available, I definitely wouldn't miss out on {this pair}."),
    ("held", "Official shop is on TikTok (held item)",  # example 7700700082219339039
     "[deal] {brand}'s official shop is finally on TikTok and they're dumping all of their {item} just in time for this {season} season.\n"
     "[nodeal] {brand}'s official shop is finally on TikTok and they just put their {item} on there, just in time for this {season} season.\n"
     "[deal] Just don't drop {store price} in store when you can pick {them} up for way cheaper on here.\n"
     "You get that super nice {feature 1} as well as the {feature 2}.\n"
     "There are multiple different colors to choose from.\n"
     "So if you want to see if your size is still available in {this pair}, I'll leave a link down below."),
    ("skit", "Where'd you get those? (two-person skit)",  # example 7699977637917183263
     "A: Wait, I love {that item}, where'd you get {it} from?\n"
     "B: Oh, I just got {this pair} from {brand}, why?\n"
     "A: {brand}? {those must have been} so expensive, though.\n"
     "[deal] B: No, no, no, I got {it} on their TikTok shop, they're {deal} right now.\n"
     "[nodeal] B: No, no, no, I got {it} on their TikTok shop for {price}{with free shipping}.\n"
     "A: Wait, that's actually such a good deal.\n"
     "B: Just check out {the feature} and the {feature 2}.\n"
     "A: Yeah, I actually love {that item}. You gotta drop the link.\n"
     "B: If you guys want to get yours, I'll leave a link down below.\n"
     "A: Bet, thank you."),
    ("other", "My new favorite (extra slot)",  # example 7700043209048739103
     "{this is} definitely my new favorite {item} from {brand}.\n"
     "You get that super nice {feature 1} you can pair with any outfit, as well as the {feature 2}.\n"
     "[deal] These are selling out quick, though, so if you want to get yours {deal}, I'll leave a link down below.\n"
     "[nodeal] These are selling out quick, though, so if you want to get yours{with free shipping}, I'll leave a link down below."),
    ("carousel", "On-image text (carousel)",
     "{season} essential: {item}\n"
     "[or] POV: you found the perfect {item} for any fit\n"
     "[or] \"I need a good {item} for this {season}\""),
]


VARIANTS = {  # extra versions of a format's script, each from another of his videos of that kind
    "flatlay_vo": [
        ("Sale news (flat-lay voiceover) · B",  # 7691425634404289822
         "[deal] {brand} is finally dumping their {item} on their TikTok shop.\n"
         "[nodeal] {brand} finally put their {item} on their TikTok shop.\n"
         "You're gonna get that {feature 1} that pairs perfectly with any outfit and that {feature 2}.\n"
         "{who} {height}, rocking a size {size}.\n"
         "[deal] The only problem is these are selling out quick since they're {deal}, so if you wanna see if your size is still available, I'll leave a link below.\n"
         "[nodeal] The only problem is these are selling out quick, so if you wanna see if your size is still available, I'll leave a link below."),
        ("Sale news (flat-lay voiceover) · C",  # 7698164462607453470
         "These are easily my new favorite {item} from {brand}.\n"
         "You get that {feature 1} you can match with almost any outfit, as well as the {feature 2}.\n"
         "{who} {height}, rocking a size {size} in {this pair} for reference.\n"
         "[deal] They are selling out quick though, since they're {deal}, so if you want to see if your size is still available, I'll leave a link down below.\n"
         "[nodeal] They are selling out quick though, so if you want to see if your size is still available, I'll leave a link down below."),
    ],
    "worn": [
        ("Height + size (worn, faceless) · B",  # 7697808086051900703
         "The {color} on {this pair} from {brand} is honestly so clean.\n"
         "{This is} their {product}, and with that {feature 1}, you can mix and match with any outfit.\n"
         "{this is} the perfect {item} for this {season} season.\n"
         "{who} {height}, rocking a size {size} {fit note}, but a lot of their top selling sizes are going quick.\n"
         "So if you're seeing this and your size is still available, I definitely wouldn't miss out on {this pair}."),
        ("Height + size (worn, faceless) · C",  # 7696311170466073886
         "{this is} probably my new favorite {item} from {brand}.\n"
         "{This is} their {product}, so you get that {feature 2} without it looking sloppy.\n"
         "And I just love the {feature 1}, and this {color} colorway is gonna be perfect for this {season} season.\n"
         "{who} {height}, rocking a size {size}, so you could definitely go true to size.\n"
         "I'll leave a link down below."),
    ],
    "held": [
        ("Official shop is on TikTok (held item) · B",  # his "I think I just found the perfect…" videos
         "I think I just found the perfect {item} for this {season}.\n"
         "{This is} the {brand} {product}, and the {feature 1} is honestly so good.\n"
         "You also get the {feature 2}, and there are multiple colors to choose from.\n"
         "It's on their TikTok shop, I'll leave a link right here."),
    ],
    "skit": [
        ("Where'd you get those? (two-person skit) · B",  # 7694048488501284127
         "A: Wait, I love {that item}, but does that tag say {brand}?\n"
         "B: Yeah, it does, why?\n"
         "A: You spent that much in store?\n"
         "B: No, I got {it} for {price}{with free shipping} on their TikTok shop.\n"
         "A: No way, that's actually such a good deal.\n"
         "B: Right, and look at the {feature 1}, I had to get {it}.\n"
         "A: Okay, you gotta drop the link.\n"
         "B: I'll leave a link down below for you guys."),
    ],
}


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
        d["settings"]["scripts"][key] = sid  # the planner's formats always use their current template
        ids = [sid]
        for vtitle, vtext in VARIANTS.get(key, []):
            vid = have.get(vtitle)
            if vid and (shop.by_id(sh, "scripts", vid) or {}).get("notes", "").startswith("Planner template"):
                shop.upsert("scripts", {"id": vid, "text": vtext})
            vid = vid or shop.upsert("scripts", {"title": vtitle, "text": vtext, "tags": [tag[n] for n in tags.get(key, []) if n in tag],
                                                 "notes": "Planner template (a version), copied from @sully.finds (docs/sully-finds-study.md)"})["id"]
            ids.append(vid)
        d["settings"].setdefault("script_variants", {})[key] = ids
    save(d)
    return d["settings"]["scripts"]


# ---------------------------------------------------------------- batch days (user, 2026-10-27)
# One format per shoot day, scheduled right after the batch: a batch fills its format's posting slots for the
# next WINDOW days (until the same weekday comes round again). Carousels: one photo pool per product (3 cover poses
# + the session's outfits), remixed into several carousels over the week, each with a fresh cover and its own text,
# the way @sully.finds stretches photos (~1.5 uses per photo, reused within about 8 days).

WINDOW = 7
BATCH_WEEK = {"mon": ["skit", "other"], "tue": [], "wed": ["carousel"], "thu": ["flatlay_vo"], "fri": ["worn", "held"],
              "sat": [], "sun": []}
BATCH_WEEK_VIDEO = {"mon": ["skit", "other"], "tue": [], "wed": ["worn"], "thu": ["flatlay_vo"], "fri": ["held"],
                    "sat": [], "sun": []}   # no carousel access yet: the videos get the days
COVERS = [("c1", "Cover: folded, leg to the left"), ("c2", "Cover: folded, leg to the right"), ("c3", "Cover: laid flat")]
CAROUSEL_SIZES = [6, 2, 5, 6, 7, 6, 2, 5]   # his mix: a quarter are quick 2-photo ones, the rest 5-7
COVER_MIN, OUTFIT_MIN = 1.0, 3.0            # a cover pose is quick; restyling an outfit isn't


def day_slots(st, day: date, chan: dict) -> list:
    """[(time, format)] for one channel on one date: the day's posts per channel split by the mix, dealt out
    across the posting window so the formats alternate (the same dealing the daily plan uses)."""
    n = int(st["posts"].get(WEEKDAYS[day.weekday()], 0))
    counts = _split(n, _mix(st))
    groups = {k: [k] * c for k, c in counts.items() if c}
    dealt = []
    while any(groups.values()):
        for g in list(groups.values()):
            if g:
                dealt.append(g.pop(0))
    a, b = _t(st["day"]["post_from"]), _t(st["day"]["post_to"])
    gap = (b - a) / max(1, len(dealt))
    return [(_s(a + gap * k + gap / 2), f) for k, f in enumerate(dealt)]


VERSION_START = date(2026, 10, 26)  # the week version A is used; then B, C, A…


def week_version(day: date, n: int) -> int:
    """Which version of a format's script a batch uses: one per week, rotating (user, 2026-10-27: one project per
    product, filmed as many times as it posts; the wording changes week to week, not take to take)."""
    return ((day - VERSION_START).days // 7) % max(1, n)


def carousel_combo(i: int, n_outfits: int) -> list:
    """The photos of a product's i-th carousel: a cover pose, then outfits rotated so no two are alike."""
    size = min(CAROUSEL_SIZES[i % len(CAROUSEL_SIZES)], 1 + n_outfits)
    k = max(1, size - 1)
    start = i % max(1, n_outfits)
    return [COVERS[i % len(COVERS)][0]] + [f"o{(start + j) % n_outfits + 1}" for j in range(k)]


def _batch(st, sh, day: date, old: dict):
    """Sets and dated posts for a batch shoot day."""
    from . import carouselplan
    week = st.get("batch_week") or (BATCH_WEEK if st.get("carousels", False) else BATCH_WEEK_VIDEO)
    fmts = [f for f in week.get(WEEKDAYS[day.weekday()], []) if f in {x["key"] for x in FORMATS}
            and (f != "carousel" or st.get("carousels", False))]
    lineup, chans = _lineup(st, sh), _channels(st, sh)
    fmt = {f["key"]: f for f in FORMATS}
    window = [day + timedelta(i) for i in range(1, WINDOW + 1)]
    sets, posts = [], []
    oldsets = {x["id"]: x for x in old.get("sets") or []}
    for ci, ch in enumerate(chans):
        acc = shop.by_id(sh, "accounts", ch.get("account"))
        skip = set(ch.get("cant_wear") or [])
        wearable = [p for p in lineup if p["id"] not in skip] or lineup
        offset = (day.toordinal() * 5 + ci * 3) % max(1, len(lineup))
        for key in fmts:
            slots = [(dd, t) for dd in window for t, fk in day_slots(st, dd, ch) if fk == key]
            if not slots or not lineup:
                continue
            f = fmt[key]
            base = {"format": key, "setup": f["setup"], "tip": f["tip"], "light": f["light"], "light_min": round(_mins(st, key, "light_min")),
                    "example": (st.get("examples") or {}).get(key) or f.get("example", ""), "channel": ch.get("account"),
                    "channel_name": (acc or {}).get("name") or f"Channel {ci + 1}", "pov": ch.get("pov", "me"),
                    "script": st["scripts"].get(key), "scripts": (st.get("script_variants") or {}).get(key) or [st["scripts"].get(key)],
                    "projects": []}
            if key == "carousel":  # one set per clothing type (same extra pieces all session), every product in it
                kinds = []
                for p in lineup:
                    k0 = carouselplan.kind(p)
                    if k0 not in kinds:
                        kinds.append(k0)
                rot = lineup[offset:] + lineup[:offset]
                order = [p for k0 in kinds for p in rot if carouselplan.kind(p) == k0]
                per = {p["id"]: 0 for p in order}
                for i in range(len(slots)):
                    per[order[i % len(order)]["id"]] += 1
                for k0 in kinds:
                    ps = [p for p in order if carouselplan.kind(p) == k0 and per[p["id"]]]
                    if not ps:
                        continue
                    sid = f"carousel-{k0}-{ci}"
                    prev = oldsets.get(sid) or {}
                    n_out = len(prev.get("outfits") or []) or 3
                    items = [{"product": p["id"], "name": p["name"], "takes": per[p["id"]]} for p in ps]
                    photos = len(ps) * (len(COVERS) + n_out)
                    sets.append({**base, "id": sid, "label": f"{f['label']} · {'tops' if k0 == 'top' else 'bottoms'}", "kind": k0,
                                 "items": items, "posts": sum(i["takes"] for i in items), "photos": photos,
                                 "minutes": round(_mins(st, key, "light_min") + len(ps) * (len(COVERS) * COVER_MIN + n_out * OUTFIT_MIN)),
                                 "edit_minutes": round(sum(i["takes"] for i in items) * _mins(st, key, "edit_min"))})
                carousel_sets = [s for s in sets if s["format"] == "carousel" and s["channel"] == ch.get("account")]
                entries = []
                for r in range(max(per.values() or [0])):  # round-robin, so one product's carousels land on different days
                    for p in order:
                        if r < per[p["id"]]:
                            s = next(x for x in carousel_sets if any(i["product"] == p["id"] for i in x["items"]))
                            n_out = len((oldsets.get(s["id"]) or {}).get("outfits") or []) or 3
                            entries.append((s, p, r, carousel_combo(r, n_out)))
                for (dd, t), (s, p, r, combo) in zip(slots, entries):
                    posts.append({"set": s["id"], "format": key, "channel": ch.get("account"), "product": p["id"], "name": p["name"],
                                  "date": dd.isoformat(), "time": t, "take": r + 1, "photos": combo, "done": False})
                continue
            pool = wearable if key in WORN else lineup
            pool = pool[offset % len(pool):] + pool[:offset % len(pool)]
            takes = max(1, int(st["takes"].get(key, f["takes"])))
            k_products = min(len(pool), max(1, math.ceil(len(slots) / takes)))
            cnt = len(slots)
            items = [{"product": pool[j]["id"], "name": pool[j]["name"], "takes": cnt // k_products + (1 if j < cnt % k_products else 0)}
                     for j in range(k_products)]
            sid = f"{key}-{ci}"
            ver = week_version(day, len([x for x in base["scripts"] if x]) or 1)
            sets.append({**base, "id": sid, "label": f["label"], "items": items, "posts": cnt, "variant": ver,
                         "minutes": round(_mins(st, key, "light_min") + cnt * _mins(st, key, "take_min")),
                         "edit_minutes": round(cnt * _mins(st, key, "edit_min"))})
            entries = [(it, r) for r in range(max(i["takes"] for i in items)) for it in items if r < it["takes"]]
            for (dd, t), (it, r) in zip(slots, entries):  # take r of a product = video r + 1 of its project
                posts.append({"set": sid, "format": key, "channel": ch.get("account"), "product": it["product"], "name": it["name"],
                              "date": dd.isoformat(), "time": t, "variant": ver, "take": r + 1, "done": False})
    posts.sort(key=lambda p: (p["date"], p["time"], p["channel"] or ""))
    return sets, posts, (window[0].isoformat(), window[-1].isoformat()), fmts


def going_live(day_iso: str) -> list:
    """Posts scheduled from any batch that go live on this date (what to expect on TikTok today)."""
    out = []
    for k, p in load()["days"].items():
        for i, x in enumerate(p.get("posts") or []):
            if x.get("date") == day_iso:
                out.append({**x, "batch": k, "k": i})
    return sorted(out, key=lambda x: x["time"])
