"""TikTok Shop content management: the accounts he runs, the products they've ordered
(samples, return windows), the script & format library, assignments in each creator's
queue, and how every posted video does (public TikTok pages, no login).

Data: ads/_shop.json (backed up with the shoots by Studio). The plan for a shoot (product,
account, creator, tags, script) lives in the shoot as `shoot.shop`; what happened to each
posted video (account, TikTok link) in `shoot.saved[n]`, next to its locked takes. Stats are
in ads/_shop_stats.json. Accounts keep a handle and the login email only: never passwords."""
import copy
import json
import random
import re
import threading
import time
from datetime import date, datetime, timedelta

from . import store

FILE = store.SHOOTS_DIR / "_shop.json"
STATS = store.SHOOTS_DIR / "_shop_stats.json"
_lock = threading.RLock()
status = {"running": False, "msg": "", "last": None}

KINDS = {
    # login = how he signs in ("email", "Google", "Apple", "phone"); passwords stay in his password manager
    "accounts": {"name": "", "handle": "", "email": "", "login": "email", "creator": None, "color": "#21a366", "notes": ""},
    "creators": {"name": "", "color": "#4dabf7", "notes": ""},
    # fills = extra {placeholders} for scripts ("benefit": "fills patchy brows")
    "products": {"name": "", "brand": "", "link": "", "image": "", "price": "", "commission": "", "category": "",
                 "fills": {}, "notes": "", "archived": False},
    # sample: free (free sample) | refundable (bought, can go back until return_by) | paid (bought to keep)
    # status: ordered | shipped | delivered | kept | returned | cancelled
    "orders": {"product": None, "account": None, "order_no": "", "ordered": "", "delivered": "", "status": "ordered",
               "sample": "free", "cost": "", "return_days": None, "return_by": "", "return_auto": False, "video_due": "", "notes": ""},
    "tags": {"name": "", "group": "Format", "description": "", "color": ""},
    "scripts": {"title": "", "text": "", "tags": [], "product": None, "notes": "", "from_shoot": None, "edited": False},
}
PLAN = {"product": None, "account": None, "creator": None, "editor": None, "tags": [], "script": None,
        "due": "", "notes": "", "assigned": None, "done": False}
GROUPS = ["Format", "Hook", "Style", "Tone"]
GROUP_COLORS = {"Format": "#4dabf7", "Hook": "#f783ac", "Style": "#ffa94d", "Tone": "#69db7c"}
STAGES = [("film", "To film"), ("precut", "Pre-cutting"), ("edit", "To edit"), ("post", "To post"), ("posted", "Posted")]

STARTER_TAGS = [
    ("Format", "Talking head", "Creator talks straight to the camera, holding or using the product. The classic TikTok Shop review."),
    ("Format", "Voiceover", "A separate voice recording over silent shots of the product in use (like MenPen). The shots can be re-filmed to match a reference."),
    ("Format", "Demo", "Shows the product doing its job, start to finish. Proof instead of claims."),
    ("Format", "Before / after", "Opens on the problem, ends on the result; the cut between them is the payoff."),
    ("Format", "Unboxing", "Opening the package on camera: first impressions and what's inside."),
    ("Format", "Try-on", "Clothes worn on camera, with fit, fabric and a few angles or outfits."),
    ("Format", "Party-game montage", "Cold-open hook, the game's title, then fast card reads and reactions that loop back to the hook (Game Night)."),
    ("Format", "Green screen", "Creator in front of a screenshot or the product page, reacting to it or pointing at it."),
    ("Format", "Skit", "A tiny acted scene where the product solves the problem."),
    ("Format", "Comparison", "This vs. that: the product next to a competitor or the old way of doing it."),
    ("Hook", "Question hook", "Opens on a question the viewer wants answered (\"why is nobody talking about…?\")."),
    ("Hook", "Problem hook", "Opens on the annoying problem the product fixes."),
    ("Hook", "Bold claim", "Opens on a strong claim or a surprising number."),
    ("Hook", "POV hook", "\"POV: …\" framing that puts the viewer in the moment."),
    ("Hook", "Cold open", "Starts on the craziest moment out of context, then shows how it got there."),
    ("Hook", "Price hook", "Leads with the deal: the price, the discount, \"under $X\"."),
    ("Style", "Fast cuts", "Pauses cut out, about 5 words a second, a cut every 1–3 s."),
    ("Style", "Eye contact", "Creator looks into the lens the whole time, no glancing off to the side."),
    ("Style", "Captions", "Word-by-word captions on screen, kept off the product and out of TikTok's buttons."),
    ("Style", "Close-ups", "Tight shots of the details: texture, tip, label, fit."),
    ("Style", "Cart pointer", "Says \"orange cart\" and an arrow points at the product tag."),
    ("Tone", "Funny", "Built around a joke or an over-the-top reaction."),
    ("Tone", "Honest review", "Pros and a con, said plainly. Trust over hype."),
    ("Tone", "Hype", "High energy and urgent (\"run, don't walk\")."),
    ("Tone", "Calm / ASMR", "Quiet, satisfying sounds and slow shots."),
    ("Tone", "Relatable", "Starts from an everyday moment the viewer has lived."),
]
PH_RX = re.compile(r"\{([A-Za-z][\w ]{0,30})\}")


def _now():
    return time.time()


def new_id():
    return store.new_id()


# ---------------------------------------------------------------- storage

def _read(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return copy.deepcopy(default)


def _write(path, d):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=1, ensure_ascii=False), encoding="utf-8")
    for i in range(5):  # OneDrive can hold the file for a moment while it syncs
        try:
            tmp.replace(path)
            return
        except PermissionError:
            time.sleep(0.3 * (i + 1))
    tmp.replace(path)


def load() -> dict:
    with _lock:
        d = _read(FILE, {})
        for k in KINDS:
            d.setdefault(k, [])
            d[k] = [{**copy.deepcopy(KINDS[k]), **x} for x in d[k]]
        d.setdefault("trash", {})
        d.setdefault("settings", {"every_hours": 6})
        if not d.get("seeded"):
            _seed(d)
            d["seeded"] = True
            _write(FILE, d)
        return d


ON_CHANGE = []  # callbacks after any change (server.py: sync the spreadsheet soon)


def changed():
    for fn in ON_CHANGE:
        try:
            fn()
        except Exception:
            pass


def save(d):
    with _lock:
        _write(FILE, d)
    changed()


def update(fn):
    with _lock:
        d = load()
        out = fn(d)
        save(d)
        return out


def by_id(d, kind, oid):
    return next((x for x in d[kind] if x["id"] == oid), None) if oid else None


def upsert(kind: str, obj: dict) -> dict:
    if kind not in KINDS:
        raise KeyError(kind)
    obj = {k: v for k, v in obj.items() if not k.startswith("_")}

    def fn(d):
        cur = by_id(d, kind, obj.get("id"))
        was = cur.get("return_by") if cur else None
        if cur:
            cur.update({k: v for k, v in obj.items() if k in KINDS[kind]}, updated=_now())
            out = cur
        else:
            out = {**copy.deepcopy(KINDS[kind]), **{k: v for k, v in obj.items() if k in KINDS[kind]},
                   "id": new_id(), "created": _now(), "updated": _now()}
            d[kind].append(out)
        if kind == "tags" and not out.get("color"):
            out["color"] = GROUP_COLORS.get(out["group"], "#adb5bd")
        if kind == "orders":
            out["_was"] = was
            _order_dates(out, obj.get("return_by") if obj.get("return_by") != was else None)
        return out
    return update(fn)


def remove(kind: str, oid: str):
    """Nothing is ever deleted: removed things move to the trash list (restorable by hand)."""
    def fn(d):
        x = by_id(d, kind, oid)
        if x:
            d[kind].remove(x)
            d["trash"].setdefault(kind, []).append({**x, "trashed": _now()})
        return {"ok": bool(x)}
    return update(fn)


# ---------------------------------------------------------------- dates

def _day(s):
    try:
        return date.fromisoformat(str(s)[:10]) if s else None
    except ValueError:
        return None


def _order_dates(o, typed=None):
    """return_by = delivered (else ordered) + return_days, unless a date was typed in. A
    worked-out date follows the delivery date when that changes."""
    if typed and typed != o.get("_was"):
        o["return_auto"] = False
    if o.get("delivered") and o.get("status") in ("ordered", "shipped"):
        o["status"] = "delivered"
    if o.get("return_days") not in (None, "") and (not o.get("return_by") or o.get("return_auto")):
        start = _day(o.get("delivered")) or _day(o.get("ordered"))
        if start:
            o["return_by"] = (start + timedelta(days=int(o["return_days"]))).isoformat()
            o["return_auto"] = True
    o.pop("_was", None)


def days_left(s):
    d = _day(s)
    return (d - date.today()).days if d else None


# ---------------------------------------------------------------- scripts

def placeholders(text: str) -> list:
    seen = []
    for m in PH_RX.finditer(text or ""):
        k = m.group(1).strip().lower()
        if k not in seen:
            seen.append(k)
    return seen


def product_fills(p) -> dict:
    if not p:
        return {}
    out = {"product": p["name"], "brand": p["brand"], "price": p["price"], "link": p["link"],
           "category": p["category"], "commission": p["commission"]}
    out.update({str(k).strip().lower(): v for k, v in (p.get("fills") or {}).items()})
    return {k: v for k, v in out.items() if v not in (None, "")}


def fill(text: str, values: dict) -> str:
    vals = {str(k).strip().lower(): v for k, v in (values or {}).items() if v not in (None, "")}
    return PH_RX.sub(lambda m: str(vals.get(m.group(1).strip().lower(), m.group(0))), text or "")


# ---------------------------------------------------------------- shoots <-> shop

def plan_of(s) -> dict:
    return {**copy.deepcopy(PLAN), **(s.get("shop") or {})}


def stage(s, busy=False) -> str:
    if not s["sources"]:
        return "film"
    if busy or not all(x.get("status") in ("ready", "error") for x in s["sources"]):
        return "precut"
    saved = s.get("saved") or {}
    if saved and all(m.get("posted") for m in saved.values()):
        return "posted"
    if saved:
        return "post"
    return "edit"


def video_product(s, n, d=None):
    """The product a video advertises: set when posting, else the shoot's; a party-game
    montage's video names its game (take.game)."""
    m = (s.get("saved") or {}).get(str(n)) or {}
    if m.get("product"):
        return m["product"]
    d = d or load()
    try:
        game = next((t.get("game") for t in store.video_takes(s, int(n)) if t.get("game")), None)
    except Exception:
        game = None
    if game:
        p = next((p for p in d["products"] if p["name"].lower() == game.lower()), None)
        if p:
            return p["id"]
    return plan_of(s)["product"]


def set_plan(sid: str, changes: dict) -> dict:
    d = load()

    def fn(s):
        pl = plan_of(s)
        pl.update({k: v for k, v in changes.items() if k in PLAN})
        s["shop"] = pl
        p = by_id(d, "products", pl["product"])
        if p and "product" in changes:  # the post text the editor shows/copies follows the product
            s["product"]["name"] = p["name"]
            if p["link"]:
                s["product"]["link"] = p["link"]
    out = store.update(sid, fn)
    changed()
    return out


def new_video(body: dict) -> dict:
    """The "New video" form: makes the shoot (script lines, product, plan, inbox folder)."""
    from . import inbox, sheet
    d = load()
    p = by_id(d, "products", body.get("product"))
    acc = by_id(d, "accounts", body.get("account"))
    text = fill(body.get("script_text") or "", {**product_fills(p), **(body.get("vars") or {})})
    title = (body.get("title") or "").strip()
    if not title:
        bits = [p["name"] if p else "New video"]
        names = [t["name"] for t in d["tags"] if t["id"] in (body.get("tags") or []) and t["group"] == "Format"]
        if names:
            bits.append(names[0])
        bits.append(datetime.now().strftime("%b %d").replace(" 0", " "))
        title = " · ".join(bits)
    script_id = body.get("script")
    if body.get("save_script") and text.strip() and not script_id:
        script_id = upsert("scripts", {"title": body.get("script_title") or title, "text": body.get("script_text"),
                                       "tags": body.get("tags") or [], "product": p["id"] if p else None})["id"]
    sid = store.create(title)
    lines, notes = sheet.parse_script(text) if text.strip() else ([], [])

    def fn(s):
        s["script"] = [{"id": store.new_id(), "text": t, "alts": [], "optional": False} for t in lines]
        if notes:
            s["reference"]["notes"] = "Directions from the script:\n" + "\n".join(f"• {n}" for n in notes)
        if body.get("reference"):
            s["reference"]["url"] = body["reference"]
        if p:
            s["product"]["name"] = p["name"]
            s["product"]["link"] = p["link"] or s["product"]["link"]
        s["shop"] = {**copy.deepcopy(PLAN), "product": p["id"] if p else None, "account": acc["id"] if acc else None,
                     "creator": body.get("creator") or (acc or {}).get("creator"), "tags": body.get("tags") or [],
                     "script": script_id, "due": body.get("due") or "", "notes": body.get("notes") or "",
                     "assigned": _now() if body.get("assign") else None}
    s = store.update(sid, fn)
    inbox.folder_for(sid, s["title"])  # footage dropped in OneDrive/<inbox>/<title> lands in this shoot
    return {"id": sid, "title": s["title"], "lines": len(lines)}


def posting(sid: str, body: dict) -> dict:
    """Posting module: which account a video went up on, its TikTok link, its product."""
    from . import render
    n = str(int(body["n"]))

    def fn(s):
        m = s["saved"].get(n)
        if m is None:
            m = s["saved"][n] = {"saved_at": _now(), "sig": render.video_sig(s, int(n))}
        if not m.get("takes"):  # saved/posted videos keep their takes (TikTok flags reused footage)
            vs = {v["n"]: v for v in store.videos(s)["videos"]}
            m["takes"] = list(vs[int(n)]["takes"]) if int(n) in vs else []
        for k in ("account", "product"):
            if k in body:
                m[k] = body[k] or None
        if "url" in body:
            url = (body["url"] or "").strip()
            mm = re.search(r"/video/(\d{8,})", url)
            m["url"] = url or None
            m["video_id"] = mm.group(1) if mm else None
        if "posted" in body:
            m["posted"] = bool(body["posted"])
            m["posted_at"] = (m.get("posted_at") or _now()) if body["posted"] else None
    s = store.update(sid, fn)
    changed()
    m = s["saved"][n]
    if m.get("url"):
        threading.Thread(target=_refresh_one, args=(m["url"],), daemon=True).start()
    return m


# ---------------------------------------------------------------- the queue

_cache = {}


def _all_shoots():
    """[(sid, shoot, info)] for every shoot, newest first; a shoot is only re-read when its
    file changed (the screens ask several times a minute). Read-only: don't modify them."""
    out = []
    for f in store.SHOOTS_DIR.glob("*/shoot.json"):
        sid = f.parent.name
        try:
            mt = f.stat().st_mtime
        except OSError:
            continue
        c = _cache.get(sid)
        if not c or c[0] != mt:
            try:
                s = store.load(sid)
            except Exception:
                continue
            c = _cache[sid] = (mt, s, {"videos": store.videos(s)["count"], "products": {}, "made": None})
        out.append((sid, c[1], c[2]))
    return sorted(out, key=lambda x: -(x[1].get("created") or 0))


def board(busy_ids=()) -> list:
    d = load()
    out = []
    for sid, s, info in _all_shoots():
        pl = plan_of(s)
        saved = s.get("saved") or {}
        st = "posted" if pl.get("done") else stage(s, sid in busy_ids)
        p = by_id(d, "products", pl["product"])
        out.append({
            "sid": sid, "title": s["title"], "created": s["created"], "stage": st,
            "product": pl["product"], "product_name": p["name"] if p else s["product"]["name"],
            "account": pl["account"], "creator": pl["creator"], "editor": pl["editor"], "tags": pl["tags"],
            "script": pl["script"], "due": pl["due"], "due_in": days_left(pl["due"]), "notes": pl["notes"],
            "assigned": pl["assigned"], "planned": bool(s.get("shop")),
            "lines": len(s["script"]), "sources": len(s["sources"]), "videos": info["videos"],
            "saved": len(saved), "posted": sum(1 for m in saved.values() if m.get("posted")),
            "thumb": _thumb(s),
        })
    return out


def _thumb(s):
    t = next((t for t in s["takes"] if t.get("usable")), None)
    key = next((x["key"] for x in s["sources"] if t and x["id"] == t["src"]), None)
    return f"/api/thumb/{key}?t={round((t['in'] + t['out']) * 5) / 10:.1f}" if key else None


def postings(d=None, stats=None) -> list:
    """Every saved video (posted or waiting) with its account, product, script, tags, stats."""
    d = d or load()
    stats = stats or load_stats()
    out = []
    for sid, s, info in _all_shoots():
        pl = plan_of(s)
        for k, m in (s.get("saved") or {}).items():
            vid = m.get("video_id")
            v = stats["videos"].get(vid) if vid else None
            snaps = (v or {}).get("snapshots") or []
            if (k, m.get("product")) not in info["products"]:
                info["products"][(k, m.get("product"))] = video_product(s, k, d)
            out.append({
                "sid": sid, "title": s["title"], "n": int(k), "posted": bool(m.get("posted")),
                "posted_at": m.get("posted_at") or (v or {}).get("created"), "saved_at": m.get("saved_at"),
                "account": m.get("account") or pl["account"], "product": info["products"][(k, m.get("product"))],
                "creator": pl["creator"], "script": pl["script"], "tags": pl["tags"],
                "url": m.get("url"), "video_id": vid, "stats": snaps[-1] if snaps else None,
                "week": _ago_delta(snaps, 7 * 86400), "desc": (v or {}).get("desc"), "error": (v or {}).get("error"),
                "external": False,
            })
    for vid, v in stats["videos"].items():  # videos tracked by link that weren't made here
        if v.get("external"):
            snaps = v.get("snapshots") or []
            out.append({"sid": None, "title": (v.get("desc") or "")[:60] or "TikTok video", "n": None, "posted": True,
                        "posted_at": v.get("created"), "account": v.get("account"), "product": v.get("product"),
                        "creator": v.get("creator"), "script": v.get("script"), "tags": v.get("tags") or [],
                        "url": v.get("url"), "video_id": vid, "stats": snaps[-1] if snaps else None,
                        "week": _ago_delta(snaps, 7 * 86400), "desc": v.get("desc"), "error": v.get("error"),
                        "external": True})
    return out


# ---------------------------------------------------------------- overview numbers

def summary() -> dict:
    """Everything the Products / Library / Overview screens show next to the raw lists."""
    d = load()
    stats = load_stats()
    posts = postings(d, stats)
    shoots = board()
    per = {"products": {}, "scripts": {}, "tags": {}, "accounts": {}, "creators": {}}

    def bump(kind, key, p):
        if not key:
            return
        x = per[kind].setdefault(key, {"videos": 0, "posted": 0, "views": 0, "likes": 0, "shares": 0, "eng": 0.0, "tracked": 0})
        x["videos"] += 1
        x["posted"] += p["posted"]
        if p["stats"]:
            x["tracked"] += 1
            x["views"] += p["stats"]["views"]
            x["likes"] += p["stats"]["likes"]
            x["shares"] += p["stats"]["shares"]
            x["eng"] += _eng(p["stats"])
    for p in posts:
        bump("products", p["product"], p)
        bump("scripts", p["script"], p)
        bump("accounts", p["account"], p)
        bump("creators", p["creator"], p)
        for t in p["tags"] or []:
            bump("tags", t, p)
    for kind in per.values():
        for x in kind.values():
            x["avg_views"] = round(x["views"] / x["tracked"]) if x["tracked"] else None
            x["eng"] = round(x["eng"] / x["tracked"], 1) if x["tracked"] else None
    made = {}
    for sid, s, info in _all_shoots():
        if info["made"] is None:  # {product: videos} for this shoot
            info["made"] = {}
            for n in range(1, info["videos"] + 1):
                pid = video_product(s, n, d)
                if pid:
                    info["made"][pid] = info["made"].get(pid, 0) + 1
            pid = plan_of(s)["product"]
            if pid and not info["made"]:
                info["made"][pid] = 0  # planned, nothing made yet
        for pid, k in info["made"].items():
            m = made.setdefault(pid, {"shoots": 0, "videos": 0})
            m["shoots"] += 1
            m["videos"] += k
    scripts_used = {}
    for b in shoots:
        if b["script"]:
            scripts_used[b["script"]] = scripts_used.get(b["script"], 0) + 1
    return {"per": per, "made": made, "scripts_used": scripts_used, "alerts": alerts(d, posts, shoots),
            "accounts": {a["id"]: account_numbers(stats, a) for a in d["accounts"]}}


def _when(n):
    return ("today" if n == 0 else "tomorrow" if n == 1 else f"in {n} days" if n > 0
            else "was yesterday" if n == -1 else f"was {-n} days ago")


def alerts(d, posts, shoots) -> list:
    out = []
    posted_on = {(p["product"], p["account"]) for p in posts if p["posted"]}
    for o in d["orders"]:
        if o["status"] in ("returned", "cancelled", "kept"):
            continue
        p = by_id(d, "products", o["product"])
        name = p["name"] if p else "a product"
        left = days_left(o["return_by"])
        if o["sample"] == "refundable" and left is not None and -3 <= left <= 7:
            out.append({"kind": "return", "level": "bad" if left <= 2 else "warn", "order": o["id"], "days": left,
                        "text": f"{name}: last day to return {_when(left)}"})
        due = days_left(o["video_due"])
        if due is not None and due <= 7 and (o["product"], o["account"]) not in posted_on:
            out.append({"kind": "due", "level": "bad" if due <= 2 else "warn", "order": o["id"], "days": due,
                        "text": f"{name}: video due {_when(due)}"})
    for b in shoots:
        if b["planned"] and b["stage"] == "film" and b["due_in"] is not None and b["due_in"] <= 3:
            out.append({"kind": "film", "level": "warn", "sid": b["sid"], "days": b["due_in"], "text": f"{b['title']}: filming due {_when(b['due_in'])}"})
    return sorted(out, key=lambda a: a["days"])


# ---------------------------------------------------------------- analytics (public TikTok pages)

def load_stats() -> dict:
    st = _read(STATS, {})
    st.setdefault("videos", {})
    st.setdefault("accounts", {})
    return st


def _eng(s):
    return round(100 * (s["likes"] + s["comments"] + s["shares"] + s["saves"]) / s["views"], 1) if s and s.get("views") else 0.0


def _ago_delta(snaps, seconds):
    if not snaps:
        return None
    cut = time.time() - seconds
    old = [s for s in snaps if s["t"] <= cut]
    base = old[-1] if old else snaps[0]
    return {k: snaps[-1].get(k, 0) - base.get(k, 0) for k in ("views", "likes", "followers") if k in snaps[-1]}


def account_numbers(stats, a) -> dict:
    snaps = (stats["accounts"].get((a.get("handle") or "").lstrip("@").lower()) or {}).get("snapshots") or []
    last = snaps[-1] if snaps else None
    daily = {}
    for s in snaps:  # one point a day for the sparkline
        daily[time.strftime("%Y-%m-%d", time.localtime(s["t"]))] = s["followers"]
    return {"followers": last["followers"] if last else None, "likes": last["likes"] if last else None,
            "videos": last["videos"] if last else None, "week": _ago_delta(snaps, 7 * 86400),
            "series": list(daily.items())[-60:], "checked": last["t"] if last else None,
            "error": (stats["accounts"].get((a.get("handle") or "").lstrip("@").lower()) or {}).get("error")}


def _snap(rec, values, cap=500):
    rec.setdefault("snapshots", []).append({"t": round(_now()), **values})
    rec["snapshots"] = rec["snapshots"][-cap:]


def _refresh_one(url, extra=None):
    from supercut import analytics
    try:
        v = analytics.fetch_video(url)
    except Exception as e:
        with _lock:
            st = load_stats()
            mm = re.search(r"/video/(\d{8,})", url)
            if mm:
                st["videos"].setdefault(mm.group(1), {"url": url})["error"] = str(e)[:200]
                _write(STATS, st)
        return None
    with _lock:
        st = load_stats()
        rec = st["videos"].setdefault(v["video_id"], {})
        rec.update(url=v["url"], handle=v["handle"], desc=v["desc"], created=v["created"], error=None, **(extra or {}))
        _snap(rec, v["stats"])
        _write(STATS, st)
    try:
        analytics.save_cover(v["video_id"], v["cover"])
    except Exception:
        pass
    return v


def track(url: str, account=None) -> dict:
    """A video posted outside the app, tracked by its link (counts toward the account)."""
    v = _refresh_one(url, {"external": True, "account": account})
    if not v:
        raise ValueError("couldn't read that TikTok link (is the video public?)")
    return {"video_id": v["video_id"], "desc": v["desc"]}


def refresh(pause=(3.0, 7.0)):
    """One gentle pass: each account's public profile, then each linked video's page."""
    from supercut import analytics
    if status["running"]:
        return
    status.update(running=True, msg="checking TikTok…")
    try:
        d = load()
        for a in d["accounts"]:
            h = (a.get("handle") or "").lstrip("@").lower()
            if not h:
                continue
            status["msg"] = f"@{h}"
            try:
                n = analytics.fetch_account(h)
                err = None
            except Exception as e:
                n, err = None, str(e)[:200]
            with _lock:
                st = load_stats()
                rec = st["accounts"].setdefault(h, {})
                rec["error"] = err
                if n:
                    _snap(rec, n)
                _write(STATS, st)
            time.sleep(random.uniform(*pause))
        urls = [p["url"] for p in postings(d) if p.get("url")]
        for i, u in enumerate(urls):
            status["msg"] = f"video {i + 1}/{len(urls)}"
            _refresh_one(u)
            time.sleep(random.uniform(*pause))
        status["last"] = _now()
        with _lock:
            _write(STATS, {**load_stats(), "last": status["last"]})
    finally:
        status.update(running=False, msg="")


def start_background():
    def loop():
        time.sleep(600)  # not right at startup (Studio restarts the app after updates)
        while True:
            every = (load().get("settings") or {}).get("every_hours", 6)
            last = load_stats().get("last") or 0
            if time.time() - last >= every * 3600:
                try:
                    refresh()
                except Exception as e:
                    status["msg"] = f"last check failed: {e}"
            time.sleep(900)
    threading.Thread(target=loop, daemon=True, name="shop-stats").start()


def analytics_view(account=None) -> dict:
    """The Analytics screen: totals, top videos, products x channels, scripts, formats, creators."""
    d = load()
    stats = load_stats()
    posts = [p for p in postings(d, stats) if p["posted"] and (not account or p["account"] == account)]
    tracked = [p for p in posts if p["stats"]]
    tot = {k: sum(p["stats"][k] for p in tracked) for k in ("views", "likes", "comments", "shares", "saves")}
    accs = [a for a in d["accounts"] if not account or a["id"] == account]
    nums = {a["id"]: account_numbers(stats, a) for a in accs}
    followers = sum(n["followers"] or 0 for n in nums.values())
    fweek = sum((n["week"] or {}).get("followers", 0) for n in nums.values())

    def group(key, multi=False):
        rows = {}
        for p in posts:
            for k in ((p[key] or []) if multi else [p[key]]):
                if not k:
                    continue
                x = rows.setdefault(k, {"id": k, "videos": 0, "tracked": 0, "views": 0, "likes": 0, "shares": 0, "eng": 0.0, "best": None})
                x["videos"] += 1
                if p["stats"]:
                    x["tracked"] += 1
                    x["views"] += p["stats"]["views"]
                    x["likes"] += p["stats"]["likes"]
                    x["shares"] += p["stats"]["shares"]
                    x["eng"] += _eng(p["stats"])
                    if not x["best"] or p["stats"]["views"] > x["best"]["views"]:
                        x["best"] = {"views": p["stats"]["views"], "sid": p["sid"], "n": p["n"], "url": p["url"]}
        for x in rows.values():
            x["avg_views"] = round(x["views"] / x["tracked"]) if x["tracked"] else None
            x["eng"] = round(x["eng"] / x["tracked"], 1) if x["tracked"] else None
        return sorted(rows.values(), key=lambda x: -(x["avg_views"] or 0))
    matrix = {}
    for p in posts:
        if p["product"] and p["account"]:
            c = matrix.setdefault(p["product"], {}).setdefault(p["account"], {"videos": 0, "views": 0, "tracked": 0})
            c["videos"] += 1
            if p["stats"]:
                c["tracked"] += 1
                c["views"] += p["stats"]["views"]
    top = sorted(tracked, key=lambda p: -p["stats"]["views"])[:12]
    for p in top:
        p["eng"] = _eng(p["stats"])
    untracked = [p for p in posts if not p["url"]]
    return {"totals": {**tot, "videos": len(posts), "tracked": len(tracked), "followers": followers, "followers_week": fweek,
                       "eng": round(sum(_eng(p["stats"]) for p in tracked) / len(tracked), 1) if tracked else None,
                       "week_views": sum((p["week"] or {}).get("views", 0) for p in tracked)},
            "accounts": nums, "per_account": group("account"), "top": top, "matrix": matrix,
            "products": group("product"), "scripts": group("script"), "tags": group("tags", True), "creators": group("creator"),
            "untracked": [{"sid": p["sid"], "n": p["n"], "title": p["title"]} for p in untracked],
            "status": {**status, "last": load_stats().get("last")}}


# ---------------------------------------------------------------- first run

def _camel(t):
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", t).strip()


def _seed(d):
    """Starter format/tag library, plus the products and scripts of the shoots made so far."""
    for g, name, desc in STARTER_TAGS:
        d["tags"].append({**copy.deepcopy(KINDS["tags"]), "id": new_id(), "name": name, "group": g, "description": desc,
                          "color": GROUP_COLORS[g], "created": _now(), "updated": _now()})
    tag = {t["name"]: t["id"] for t in d["tags"]}
    known = {
        "menpen": ["Voiceover", "Close-ups", "Eye contact", "Captions"],
        "manpen": ["Voiceover", "Close-ups", "Eye contact", "Captions"],
        "game-night": ["Party-game montage", "Cold open", "Fast cuts", "Funny"],
        "": ["Talking head", "Fast cuts", "Captions"],
    }

    def product(name, brand=""):
        p = next((p for p in d["products"] if p["name"].lower() == name.lower()), None)
        if not p:
            p = {**copy.deepcopy(KINDS["products"]), "id": new_id(), "name": name, "brand": brand, "created": _now(), "updated": _now()}
            d["products"].append(p)
        return p
    for r in sorted(store.shoots(), key=lambda r: r["created"]):
        sid = r["id"]
        if sid.startswith(("test-", "shoot-")):
            continue
        s = store.load(sid)
        if sid == "game-night":
            for g in sorted({t.get("game") for t in s["takes"] if t.get("game")}):
                product(g)
            names = known["game-night"]
            pid = None
        else:
            name = s["product"]["name"] or _camel(s["title"])
            brand = next((b for b in ("Old Navy", "Dude Wipes", "MenPen") if name.lower().startswith(b.lower())), "")
            p = product(name, brand)
            if s["product"]["link"] and not p["link"]:
                p["link"] = s["product"]["link"]
            pid = p["id"]
            names = next((v for k, v in known.items() if k and sid.startswith(k)), known[""])
        lines = (s.get("sheet") or {}).get("lines") or s.get("script_notes") or [l["text"] for l in s["script"]]
        script_id = None
        if sid != "game-night" and len(lines) >= 2 and not s.get("script_guessed") and not str(lines[0]).startswith("Shot "):
            script_id = new_id()
            d["scripts"].append({**copy.deepcopy(KINDS["scripts"]), "id": script_id, "title": s["title"], "text": "\n".join(lines),
                                 "tags": [tag[n] for n in names if n in tag], "product": pid, "from_shoot": sid,
                                 "created": s["created"] or _now(), "updated": _now()})

        def fn(x, pid=pid, names=names, script_id=script_id):
            pl = plan_of(x)
            pl.update(product=pl["product"] or pid, script=pl["script"] or script_id,
                      tags=pl["tags"] or [tag[n] for n in names if n in tag])
            x["shop"] = pl
        store.update(sid, fn)


def adopt_sheet():
    """Every row of the Scripts & Links sheet is a library script too (its shoot linked to
    it), kept in step with the sheet unless the script was edited here."""
    from . import sheet
    path = sheet.find()
    if not path:
        return 0
    try:
        rows = sheet.rows(path)
    except Exception:  # open in Excel / half-synced: next pass
        return 0
    by_row = {}
    for sid, s, _ in _all_shoots():
        name = ((s.get("sheet") or {}).get("row") or "").strip().lower()
        if name:
            by_row[name] = (sid, s)
    n = 0
    for row in rows:
        if not row["script"].strip() or row["shoot"].lower() not in by_row:
            continue
        sid, s = by_row[row["shoot"].lower()]
        d = load()
        cur = next((x for x in d["scripts"] if x.get("from_shoot") == sid), None)
        if cur and (cur["text"] == row["script"] or cur.get("edited")):
            continue
        pl = plan_of(s)
        sc = upsert("scripts", {**(cur or {}), "title": cur["title"] if cur else s["title"], "text": row["script"],
                                "product": (cur or {}).get("product") or pl["product"], "tags": (cur or {}).get("tags") or pl["tags"],
                                "from_shoot": sid, "notes": (cur or {}).get("notes") or "From the Scripts & Links sheet"})
        if pl["script"] != sc["id"]:
            store.update(sid, lambda x, i=sc["id"]: x.__setitem__("shop", {**plan_of(x), "script": i}))
        n += 1
    return n
