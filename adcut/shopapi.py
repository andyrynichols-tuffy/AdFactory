"""HTTP API for the TikTok Shop side (adcut/shop.py): accounts, creators, products, orders,
the script & format library, the creators' queue, posting links and analytics."""
import os
import threading
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import FileResponse

from . import auth, sheetdb, shop, store

router = APIRouter(prefix="/api/shop")
BUSY = lambda: set()  # server.py points this at the shoots with a job running
WAKE = None           # server.py: the event that runs a spreadsheet pass now


@router.get("/sheet/status")
def sheet_status(request: Request):
    st = dict(sheetdb.STATUS)
    st["name"] = Path(st["path"]).name.replace("^0", "&") if st.get("path") else None
    st["local"] = not auth.remote(request)
    st["tabs"] = [t for _, t, _, _ in sheetdb.TABS] + [sheetdb.POSTED_TAB]
    return st


@router.post("/sheet/sync")
def sheet_sync():
    if WAKE:
        WAKE.set()
    return {"ok": True}


@router.post("/sheet/open")
def sheet_open(request: Request):
    """Opens the spreadsheet in Excel on this PC (not from the web link)."""
    if auth.remote(request) or not sheetdb.STATUS.get("path"):
        raise HTTPException(400, "open it from OneDrive on this device")
    os.startfile(sheetdb.STATUS["path"])
    return {"ok": True}


@router.get("")
def everything():
    d = shop.load()
    for o in d["orders"]:
        o["_return_left"] = shop.days_left(o["return_by"])
        o["_due_left"] = shop.days_left(o["video_due"])
    for x in d["scripts"]:
        x["_placeholders"] = shop.placeholders(x["text"])
    return {**{k: d[k] for k in shop.KINDS}, "groups": shop.GROUPS, "stages": shop.STAGES,
            "settings": d["settings"], "summary": shop.summary()}


@router.post("/{kind}")
def save_one(kind: str, body: dict = Body(...)):
    if kind not in shop.KINDS:
        raise HTTPException(404, f"no {kind}")
    return shop.upsert(kind, body)


@router.delete("/{kind}/{oid}")
def remove_one(kind: str, oid: str):
    if kind not in shop.KINDS:
        raise HTTPException(404, f"no {kind}")
    return shop.remove(kind, oid)


@router.get("/board/all")
def board():
    return shop.board(BUSY())


@router.post("/new/video")
def new_video(body: dict = Body(...)):
    return shop.new_video(body)


@router.post("/plan/{sid}")
def plan(sid: str, body: dict = Body(...)):
    if not store.path_for(sid).exists():
        raise HTTPException(404, f"no shoot {sid}")
    return shop.plan_of(shop.set_plan(sid, body))


@router.get("/postings/all")
def postings():
    return shop.postings()


@router.post("/posting/{sid}")
def posting(sid: str, body: dict = Body(...)):
    if not store.path_for(sid).exists():
        raise HTTPException(404, f"no shoot {sid}")
    return shop.posting(sid, body)


@router.get("/analytics/view")
def analytics(account: str = ""):
    return shop.analytics_view(account or None)


@router.post("/analytics/refresh")
def refresh():
    threading.Thread(target=shop.refresh, daemon=True).start()
    return {"ok": True}


@router.post("/analytics/track")
def track(body: dict = Body(...)):
    try:
        return shop.track(body.get("url", ""), body.get("account"))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/cover/{vid}.jpg")
def cover(vid: str):
    from supercut import analytics as an
    f = an.cover_file(vid)
    if not vid.isdigit() or not f.exists():
        raise HTTPException(404, "no cover")
    return FileResponse(f, headers={"Cache-Control": "max-age=86400"})
