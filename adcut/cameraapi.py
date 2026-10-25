"""HTTP API for the Ad Camera iPhone app (ios/AdCamera): the projects it can film for, and
making a new one. Footage comes back through the inbox upload (/api/inbox/upload?shoot=…),
so the camera's clips land in the shoot's own OneDrive folder and get pre-cut like any drop."""
from fastapi import APIRouter, Body, HTTPException

from . import layout, shop

router = APIRouter(prefix="/api/camera")
BUSY = lambda: set()  # server.py points this at the shoots with a job running


def _project(d, sid, s, busy):
    pl = shop.plan_of(s)
    p = shop.by_id(d, "products", pl["product"])
    tags = {t["id"]: t["name"] for t in d["tags"]}
    return {"sid": sid, "title": s["title"], "created": s["created"],
            "stage": "posted" if pl.get("done") else shop.stage(s, sid in busy),
            "product": pl["product"], "product_name": p["name"] if p else s["product"]["name"],
            "tags": [tags[t] for t in pl["tags"] if t in tags], "due": pl["due"],
            "lines": [ln["text"] for ln in s["script"]], "clips": len(s["sources"])}


@router.get("/projects")
def projects():
    """Everything the camera needs in one go: projects (newest first), and what a new
    one can be made from (products, library scripts, tags, accounts). Also TikTok's UI
    zones, so the viewfinder's guides match adcut/layout.py."""
    d, busy = shop.load(), BUSY()
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
