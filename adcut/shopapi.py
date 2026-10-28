"""HTTP API for the TikTok Shop side (adcut/shop.py): accounts, creators, products, orders,
the script & format library, the creators' queue, posting links and analytics."""
import os
import threading
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import FileResponse

from . import ai, auth, competitors, productlink, scriptgen, sheetdb, shop, store

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


@router.post("/products/from-link")
def product_from_link(body: dict = Body(...)):
    """Product details from a TikTok Shop product link, a TikTok video (its tagged product) or a shop page."""
    try:
        return productlink.lookup(body.get("url") or "", shop.load()["products"])
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # TikTok said no / timed out
        raise HTTPException(502, f"Couldn't read that page ({type(e).__name__}). Try again in a moment.")


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


# ---------- script builder: TikTok link -> script + shot list (adcut/scriptgen.py) ----------

@router.post("/scriptgen/link")
def scriptgen_link(body: dict = Body(...)):
    url = (body.get("url") or "").strip()
    if "tiktok.com" not in url:
        raise HTTPException(400, "paste a TikTok link")
    return scriptgen.from_link(url, body.get("title") or "")


@router.get("/scriptgen/jobs/{jid}")
def scriptgen_job(jid: str):
    j = scriptgen.JOBS.get(jid)
    if not j:
        raise HTTPException(404, "no such job")
    return j


@router.get("/scriptgen/script/{sid}")
def scriptgen_script(sid: str):
    """A library script for the builder: lines + marks in step with its text."""
    s = shop.by_id(shop.load(), "scripts", sid)
    if not s:
        raise HTTPException(404, "no such script")
    r = scriptgen.reconcile(s)
    if r is not s:
        shop.upsert("scripts", {"id": sid, "lines": r["lines"], "marks": r["marks"]})
    return {**r, "_placeholders": shop.placeholders(r["text"]), "_originals": scriptgen.originals(r["lines"], r["marks"])}


@router.post("/scriptgen/{sid}/marks")
def scriptgen_marks(sid: str, body: dict = Body(...)):
    try:
        return scriptgen.save_marks(sid, body)
    except KeyError:
        raise HTTPException(404, "no such script")


@router.post("/scriptgen/{sid}/guess")
def scriptgen_guess(sid: str):
    """The local guess again (after editing lines)."""
    s = shop.by_id(shop.load(), "scripts", sid)
    if not s:
        raise HTTPException(404, "no such script")
    return {"marks": scriptgen.guess_marks(s.get("lines") or [], (s.get("source") or {}).get("desc", ""))}


@router.get("/scriptgen/products")
def scriptgen_products():
    ps, last = scriptgen.products_by_delivery()
    return [{"id": p["id"], "name": p["name"], "delivered": last.get(p["id"])} for p in ps]


@router.get("/scriptgen/ref/{ref}/{name}")
def scriptgen_file(ref: str, name: str):
    f = scriptgen.REFS / ref / name
    if not ref.isalnum() or "/" in name or "\\" in name or not f.is_file():
        raise HTTPException(404, "no such file")
    return FileResponse(f)


@router.get("/ai/status")
def ai_status(request: Request, fresh: int = 0):
    st = ai.status(bool(fresh))
    return {"available": bool(st["installed"] and st["signed_in"]), "installed": st["installed"],
            "signed_in": st["signed_in"], "help": None if st["signed_in"] else ai.SIGN_IN,
            "local": not auth.remote(request)}


@router.post("/ai/login")
def ai_login(request: Request):
    if auth.remote(request):
        raise HTTPException(400, "sign in on the PC that runs Ad Factory")
    try:
        ai.open_login()
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@router.post("/ai/{what}")
def ai_run(what: str, body: dict = Body(...)):
    """✨ AI, only when asked: marks / describe / fill / rewrite."""
    if what == "marks":
        return scriptgen.ai_marks(body["script"])
    if what == "describe":
        return scriptgen.ai_describe(body["script"])
    if what == "fill":
        return scriptgen.ai_fill(body["script"], body["product"], body.get("known") or {})
    if what == "rewrite":
        if not (body.get("text") or "").strip() or not (body.get("how") or "").strip():
            raise HTTPException(400, "nothing to rewrite")
        return scriptgen.ai_rewrite(body["text"], body["how"])
    raise HTTPException(404, what)


# ---------- competitor tracker (adcut/competitors.py): estimates from public counters ----------

@router.get("/competitors/all")
def competitors_all():
    return {"profiles": competitors.summary(), "status": competitors.status}


@router.post("/competitors/add")
def competitors_add(body: dict = Body(...)):
    try:
        r = competitors.add(body.get("handle") or "")
    except ValueError as e:
        raise HTTPException(400, str(e))
    threading.Thread(target=competitors.refresh, kwargs={"only": r["handle"]}, daemon=True).start()
    return r


@router.post("/competitors/{handle}/remove")
def competitors_remove(handle: str):
    competitors.remove(handle)
    return {"ok": True}


@router.post("/competitors/{handle}/refresh")
def competitors_refresh(handle: str):
    threading.Thread(target=competitors.refresh, kwargs={"only": handle}, daemon=True).start()
    return {"ok": True}


@router.get("/competitors/{handle}/view")
def competitors_view(handle: str, days: int = 7):
    try:
        return competitors.view(handle, days)
    except KeyError:
        raise HTTPException(404, f"not tracking @{handle}")


# ---------- daily planner (adcut/planner.py): a @sully.finds-style day ----------
from . import planner  # noqa: E402


@router.get("/planner/settings")
def planner_settings():
    d, sh = planner.load(), shop.load()
    st = d["settings"]
    week = st.get("batch_week") or (planner.BATCH_WEEK if st.get("carousels") else planner.BATCH_WEEK_VIDEO)
    return {"settings": d["settings"], "formats": planner.FORMATS, "weekdays": planner.WEEKDAYS, "week": week,
            "accounts": [{"id": a["id"], "name": a["name"], "handle": a["handle"]} for a in sh["accounts"]]}


@router.post("/planner/settings")
def planner_save(body: dict = Body(...)):
    return planner.set_settings(body)


@router.get("/planner/day/{day}")
def planner_day(day: str):
    return planner.get(day)


@router.post("/planner/day/{day}/rebuild")
def planner_rebuild(day: str):
    return planner.generate(day)


@router.post("/planner/day/{day}/mark")
def planner_mark(day: str, body: dict = Body(...)):
    return planner.mark(day, int(body["k"]), bool(body.get("done")))


@router.post("/planner/day/{day}/set/{set_id}")
def planner_set(day: str, set_id: str, body: dict = Body(...)):
    return planner.set_example(day, set_id, str(body.get("example") or ""))


@router.get("/planner/day/{day}/scripts/{set_id}")
def planner_scripts(day: str, set_id: str):
    """The complete script for each product in a set: what's in its Ad Camera project, else what it will be."""
    plan = planner.get(day)
    s = next(x for x in plan["sets"] if x["id"] == set_id)
    out = []
    posts = [x for x in plan["posts"] if x["set"] == s["id"]]
    for it in s["items"]:
        if not it["product"]:
            continue
        vs = sorted({x.get("variant", 0) for x in posts if x["product"] == it["product"]}) or [0]
        for v in vs:
            pr = next((x for x in s.get("projects") or [] if x["product"] == it["product"] and x.get("variant", 0) == v), None)
            lines = [ln["text"] for ln in store.load(pr["sid"])["script"]] if pr else planner.script_for(day, s, it["product"], plan, variant=v)
            takes = sum(1 for x in posts if x["product"] == it["product"] and x.get("variant", 0) == v) or it["takes"]
            out.append({"product": it["product"], "name": it["name"], "variant": v, "versions": len(vs), "takes": takes, "lines": lines})
    return out


@router.get("/planner/live/{day}")
def planner_live(day: str):
    """Posts from any batch that go live on this date."""
    return planner.going_live(day)


@router.get("/planner/day/{day}/carousel/{set_id}")
def carousel_plan(day: str, set_id: str):
    from . import carouselplan
    s = next(x for x in planner.get(day)["sets"] if x["id"] == set_id)
    return carouselplan.for_set(day, s)


@router.post("/planner/day/{day}/carousel/{set_id}")
def carousel_plan_save(day: str, set_id: str, body: dict = Body(...)):
    from . import carouselplan
    return carouselplan.update(day, set_id, body)


@router.get("/example")
def example(url: str):
    from . import examples
    try:
        return examples.get(url)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/example/{vid}/{name}")
def example_image(vid: str, name: str):
    from . import examples
    try:
        return FileResponse(examples.image(vid, name), headers={"Cache-Control": "max-age=604800"})
    except FileNotFoundError:
        raise HTTPException(404, "not there")


# ---------- posting kit (adcut/postkit.py): a folder + description per post, videos rendered in ----------
from . import postkit  # noqa: E402


@router.get("/planner/day/{day}/kit")
def kit(day: str):
    return {"posts": postkit.posts(day), "job": postkit.JOB, "folder": str(postkit.kit_dir(day))}


@router.post("/planner/day/{day}/kit/build")
def kit_build(day: str):
    return postkit.build(day)


@router.put("/planner/day/{day}/kit/{k}/photo")
async def kit_photo(day: str, k: int, request: Request, name: str = "photo.jpg"):
    return {"saved": postkit.add_photo(day, k, name, await request.body())}


@router.get("/planner/day/{day}/kit/{k}/file/{name}")
def kit_file(day: str, k: int, name: str):
    try:
        return FileResponse(postkit.file_path(day, k, name), filename=name)
    except FileNotFoundError:
        raise HTTPException(404, "not there")


@router.post("/planner/day/{day}/kit/{k}/open")
def kit_open(day: str, k: int):
    """Open the post's folder on this PC (Explorer)."""
    import os
    f = Path(postkit.posts(day)[k]["folder"])
    f.mkdir(parents=True, exist_ok=True)
    os.startfile(str(f))
    return {"ok": True}


@router.get("/planner/days")
def planner_days():
    return planner.days()


@router.post("/planner/day/{day}/block")
def planner_block(day: str, body: dict = Body(...)):
    return planner.mark_block(day, str(body["key"]), bool(body.get("done")))


@router.post("/planner/day/{day}/projects")
def planner_projects(day: str, body: dict = Body(...)):
    return {"made": planner.make_projects(day, body["set"])}
