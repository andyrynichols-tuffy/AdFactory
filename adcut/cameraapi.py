"""HTTP API for the Ad Camera iPhone app (ios/AdCamera): the projects it can film for, and
making a new one. Footage comes back through the inbox upload (/api/inbox/upload?shoot=…),
so the camera's clips land in the shoot's own OneDrive folder and get pre-cut like any drop."""
from fastapi import APIRouter, Body, HTTPException

from fastapi import Request

from . import layout, planner, postkit, shop, store

router = APIRouter(prefix="/api/camera")
BUSY = lambda: set()  # server.py points this at the shoots with a job running
CAROUSELS = {}  # shoot id -> planner info, refreshed with each project list
LAST = {"seen": 0.0, "upload": 0.0, "shoot": ""}  # when the phone last asked for projects / sent a take (shown in the sidebar)


@router.get("/status")
def status():
    return LAST


def _project(d, sid, s, busy):
    pl = shop.plan_of(s)
    p = shop.by_id(d, "products", pl["product"])
    tags = {t["id"]: t["name"] for t in d["tags"]}
    return {"sid": sid, "title": s["title"], "created": s["created"],
            "stage": "posted" if pl.get("done") else shop.stage(s, sid in busy),
            "product": pl["product"], "product_name": p["name"] if p else s["product"]["name"],
            "tags": [tags[t] for t in pl["tags"] if t in tags], "due": pl["due"],
            "lines": [ln["text"] for ln in s["script"]], "clips": len(s["sources"]),
            "carousel": (CAROUSELS.get(sid) or {}).get("format") == "carousel",
            "outfits": postkit.outfits_for(sid) if (CAROUSELS.get(sid) or {}).get("format") == "carousel" else [],
            **_carousel_plan(sid)}


def _carousel_plan(sid):
    """Carousel mode's guide: the session's outfits (what to lay with this product in each) + its on-screen text."""
    ix = CAROUSELS.get(sid)
    if not ix or ix["format"] != "carousel":
        return {}
    from . import carouselplan
    try:
        s = next(x for x in planner.get(ix["day"])["sets"] if x["id"] == ix["set"])
        cp = carouselplan.for_set(ix["day"], s)
        row = next(r for r in cp["products"] if r["product"] == ix["product"])
    except StopIteration:
        return {}
    return {"carousel_text": row["text"], "carousel_set": ix["day"] + "/" + ix["set"],
            "outfit_plan": [{"name": o.get("name") or f"Outfit {i + 1}", "with": w} for i, (o, w) in enumerate(zip(cp["outfits"], row["with"]))]}


@router.get("/projects")
def projects():
    """Everything the camera needs in one go: projects (newest first), and what a new
    one can be made from (products, library scripts, tags, accounts). Also TikTok's UI
    zones, so the viewfinder's guides match adcut/layout.py."""
    import time
    LAST["seen"] = time.time()
    d, busy = shop.load(), BUSY()
    CAROUSELS.clear()
    CAROUSELS.update(planner.project_index())
    return {
        "projects": [_project(d, sid, s, busy) for sid, s, _ in shop._all_shoots()],
        "products": [{"id": p["id"], "name": p["name"], "brand": p["brand"]}
                     for p in d["products"] if not p.get("archived")],
        "scripts": [{"id": x["id"], "title": x["title"], "text": x["text"], "product": x.get("product"),
                     "tags": x.get("tags") or []} for x in d["scripts"]],
        "tags": [{"id": t["id"], "name": t["name"], "group": t["group"]} for t in d["tags"]],
        "accounts": [{"id": a["id"], "name": a["name"], "handle": a["handle"]} for a in d["accounts"]],
        "zones": layout.UI_ZONES, "safe": layout.SAFE,
    }


@router.get("/projects/{sid}")
def project(sid: str):
    """One project's page on the phone: its clips in Ad Factory (with thumbnails) and how
    far the edit is (videos cut, saved)."""
    try:
        s = store.load(sid)
    except (ValueError, OSError):
        raise HTTPException(404, f"no shoot {sid}")
    clips = []
    for x in s["sources"]:
        ready = x.get("status") == "ready" and x.get("key")
        t = min(1.0, (x.get("duration") or 2) / 2)
        clips.append({"id": x["id"], "name": x["name"], "status": x.get("status") or "", "duration": x.get("duration") or 0,
                      "batch": x.get("batch") or 1, "thumb": f"/api/thumb/{x['key']}?t={t:.1f}" if ready else None})
    return {**_project(shop.load(), sid, s, BUSY()), "sources": clips,
            "videos": len(store.videos(s)["videos"]), "saved": len(s.get("saved") or {})}


@router.post("/projects")
def new_project(body: dict = Body(...)):
    """New project from the phone: product + script + style tags (+ account), the same as
    the home page's "＋ New video"."""
    if not (body.get("title") or body.get("product") or body.get("script_text")):
        raise HTTPException(400, "pick a product or a script, or give it a name")
    r = shop.new_video(body)
    d = shop.load()
    s = next(s for sid, s, _ in shop._all_shoots() if sid == r["id"])
    return _project(d, r["id"], s, BUSY())


@router.put("/photo")
async def photo(request: Request, shoot: str, outfit: int, name: str = "photo.jpg"):
    """Carousel mode: one photo = one outfit with one product; it goes into that product's carousel
    folder in the day's posting kit (adcut/postkit.py) as outfit-N."""
    import time
    LAST.update(upload=time.time(), shoot=shoot)
    try:
        return postkit.add_outfit_photo(shoot, outfit, name, await request.body())
    except LookupError as e:
        raise HTTPException(404, str(e))
