"""HTTP API for the Ad Camera iPhone app (ios/AdCamera): the projects it can film for, and
making a new one. Footage comes back through the inbox upload (/api/inbox/upload?shoot=…),
so the camera's clips land in the shoot's own OneDrive folder and get pre-cut like any drop."""
from fastapi import APIRouter, Body, HTTPException

from . import layout, shop, store

router = APIRouter(prefix="/api/camera")
BUSY = lambda: set()  # server.py points this at the shoots with a job running


def _project(d, sid, s, busy):
    pl = shop.plan_of(s)
    p = shop.by_id(d, "products", pl["product"])
    lib = shop.by_id(d, "scripts", pl.get("script"))
    tags = {t["id"]: t["name"] for t in d["tags"]}
    return {"sid": sid, "title": s["title"], "created": s["created"],
            "stage": "posted" if pl.get("done") else shop.stage(s, sid in busy),
            "product": pl["product"], "product_name": p["name"] if p else s["product"]["name"],
            "tags": [tags[t] for t in pl["tags"] if t in tags], "due": pl["due"],
            "lines": [ln["text"] for ln in s["script"]], "clips": len(s["sources"]),
            # the project page's links: the product's TikTok Shop page, and the video being copied
            # (the shoot's reference, else the TikTok its library script was made from)
            "product_link": (p or {}).get("link") or s["product"].get("link") or None,
            "reference_url": (s.get("reference") or {}).get("url") or ((lib or {}).get("source") or {}).get("url") or None}


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


@router.get("/projects/{sid}")
def project(sid: str):
    """One project's page on the phone: its clips in Ad Factory (with thumbnails) and how
    far the edit is (videos cut, saved)."""
    try:
        s = store.load(sid)
    except (ValueError, OSError):
        raise HTTPException(404, f"no shoot {sid}")
    clips = []
    off = set(s.get("phone_off") or [])
    for x in s["sources"]:
        ready = x.get("status") == "ready" and x.get("key")
        t = min(1.0, (x.get("duration") or 2) / 2)
        clips.append({"id": x["id"], "name": x["name"], "status": x.get("status") or "", "duration": x.get("duration") or 0,
                      "batch": x.get("batch") or 1, "thumb": f"/api/thumb/{x['key']}?t={t:.1f}" if ready else None,
                      "off": store.file_key(x.get("name") or x.get("file")) in off})   # archived/deleted on the phone
    return {**_project(shop.load(), sid, s, BUSY()), "sources": clips,
            "videos": len(store.videos(s)["videos"]), "saved": len(s.get("saved") or {})}


@router.post("/projects/{sid}/takes")
def phone_take(sid: str, body: dict = Body(...)):
    """A take archived or deleted on the phone ({name, off: true}) is kept out of the videos;
    one brought back ({name, off: false}) counts again. The name is remembered, so it also
    works for a file the inbox hasn't imported yet."""
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "which take?")
    out = {}
    try:
        store.update(sid, lambda s: out.update(store.set_phone_off(s, name, bool(body.get("off")))))
    except (ValueError, OSError):
        raise HTTPException(404, f"no shoot {sid}")
    shop.changed()
    return out


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
