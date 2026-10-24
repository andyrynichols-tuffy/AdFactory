"""Ad editor backend: shoots, raw-file intake, background take matching and renders."""
import io
import json
import os
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from supercut import fonts as fontsmod
from supercut.caption import PRESETS, render_caption
from supercut.config import FFMPEG, FONTS_DIR, ROOT
from supercut.ingest import VIDEO_EXTS

from . import assets as assetmod
from . import inbox
from . import fx as fxmod
from . import sounds as soundsmod
from . import auth, preview, render, safety, sheet, shop, shopapi, store, takes, tunnel

EDITOR_DIR = ROOT / "adeditor"
app = FastAPI(title="Ad Factory")
JOBS = {}
GPU = threading.Lock()  # one transcribe/render at a time
app.include_router(shopapi.router)  # the TikTok Shop side: products, accounts, library, queue, analytics
shopapi.BUSY = lambda: {j["shoot"] for j in JOBS.values() if j.get("state") in ("queued", "running")}


@app.middleware("http")
async def login_wall(request, call_next):
    """Visitors through the web link sign in once (adcut/auth.py); this PC never has to."""
    if request.url.path in ("/login", "/favicon.ico") or not auth.remote(request) or auth.signed_in(request):
        return await call_next(request)
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": "sign in first"}, status_code=401)
    return RedirectResponse("/login", status_code=303)


@app.get("/login")
def login_page():
    return HTMLResponse(auth.LOGIN_HTML.replace("{err}", ""))


@app.post("/login")
async def login(request: Request):
    from urllib.parse import parse_qs
    pw = parse_qs((await request.body()).decode("utf-8", "replace")).get("password", [""])[0]
    tok = auth.try_login(request, pw)
    if not tok or tok == "wait":
        msg = "Too many tries. Wait 10 minutes." if tok == "wait" else "Wrong password."
        return HTMLResponse(auth.LOGIN_HTML.replace("{err}", f'<div class="err">{msg}</div>'), status_code=401)
    r = RedirectResponse("/", status_code=303)
    r.set_cookie(auth.COOKIE, tok, max_age=auth.DAYS * 86400, httponly=True, secure=True, samesite="lax")
    return r


@app.middleware("http")
async def no_cache(request, call_next):
    resp = await call_next(request)
    if not request.url.path.startswith(("/proxy", "/previews", "/outputs", "/api/thumb", "/api/caption.png")):
        resp.headers["Cache-Control"] = "no-cache"
    return resp


def _sid(sid):
    try:
        if store.path_for(sid).exists():
            return sid
    except ValueError:
        pass
    raise HTTPException(404, f"no shoot {sid}")


# ---------- shoots ----------

@app.get("/api/shoots")
def list_shoots():
    rows = store.shoots()
    for r in rows:
        try:
            pl = shop.plan_of(store.load(r["id"]))
            r.update(shop={k: pl[k] for k in ("product", "account", "creator", "editor", "tags", "script", "due")})
        except Exception:
            r["shop"] = None
    return rows


@app.post("/api/shoots")
def new_shoot(body: dict = Body(...)):
    return {"id": store.create(body.get("title", "").strip())}


@app.get("/api/shoots/{sid}")
def get_shoot(sid: str):
    s = store.load(_sid(sid))
    sigs = {str(v["n"]): render.video_sig(s, v["n"]) for v in store.videos(s)["videos"]}
    return {**s, "_videos": store.videos(s), "_job": _job_for(sid), "_sigs": sigs}


@app.get("/api/shoots/{sid}/rev")
def shoot_rev(sid: str):
    return {"rev": store.load(_sid(sid))["rev"], "job": _job_for(sid)}


@app.put("/api/shoots/{sid}")
def put_shoot(sid: str, body: dict = Body(...)):
    body = {k: v for k, v in body.items() if not k.startswith("_")}
    try:
        s = store.save(_sid(sid), body, expect_rev=body.get("rev"))
    except store.RevConflict as e:
        raise HTTPException(409, f"changed elsewhere (rev {e})")
    return {"rev": s["rev"], "_videos": store.videos(s),
            "_sigs": {str(v["n"]): render.video_sig(s, v["n"]) for v in store.videos(s)["videos"]}}


@app.post("/api/shoots/{sid}/trash")
def trash_shoot(sid: str):
    """Moves the shoot folder to ads/_trash (raw files and renders are untouched)."""
    src = store.path_for(_sid(sid)).parent
    dst = store.SHOOTS_DIR / "_trash" / f"{sid}-{int(time.time())}"
    dst.parent.mkdir(exist_ok=True)
    shutil.move(str(src), str(dst))
    return {"ok": True}


# ---------- raw files + reference ----------

def _add_sources(sid: str, files: list):
    def fn(s):
        have = {x["file"] for x in s["sources"]}
        b = store.next_batch(s)
        for f in files:
            if str(f) not in have:
                s["sources"].append({"id": store.new_id(), "file": str(f), "name": f.name,
                                     "status": "new", "error": None, "batch": b})
    store.update(sid, fn)


@app.post("/api/shoots/{sid}/sources")
def add_sources(sid: str, body: dict = Body(...)):
    """Add raw files by path (a folder adds every video in it)."""
    files = []
    for raw in body.get("paths", []):
        p = Path(raw.strip().strip('"'))
        if p.is_dir():
            files += sorted(f for f in p.iterdir() if f.suffix.lower() in VIDEO_EXTS)
        elif p.is_file() and p.suffix.lower() in VIDEO_EXTS:
            files.append(p)
        else:
            raise HTTPException(400, f"not a video file or folder: {p}")
    _add_sources(_sid(sid), files)
    return {"added": len(files)}


@app.delete("/api/shoots/{sid}/sources/{src_id}")
def remove_source(sid: str, src_id: str):
    def fn(s):
        s["sources"] = [x for x in s["sources"] if x["id"] != src_id]
        s["takes"] = [t for t in s["takes"] if t["src"] != src_id]
    store.update(_sid(sid), fn)
    return {"ok": True}


@app.put("/api/shoots/{sid}/upload")
async def upload(sid: str, name: str, request: Request, kind: str = "source"):
    """Files dropped onto the editor stream here (raw footage or the reference video)."""
    _sid(sid)
    folder = store.UPLOAD_DIR / sid
    folder.mkdir(parents=True, exist_ok=True)
    safe = "".join(c for c in Path(name).name if c not in '<>:"/\\|?*') or "video.mp4"
    if kind == "asset":
        folder = folder / "assets"
        folder.mkdir(exist_ok=True)
        stem, ext = Path(safe).stem, Path(safe).suffix
        dst, n = folder / safe, 2
        while dst.exists():  # pasted screenshots all arrive as "image.png"
            dst, n = folder / f"{stem}-{n}{ext}", n + 1
    else:
        dst = folder / (("reference-" if kind == "reference" else "") + safe)
    with open(dst, "wb") as f:
        async for chunk in request.stream():
            f.write(chunk)
    if kind == "reference":
        store.update(sid, lambda s: s["reference"].update(file=str(dst)))
    elif kind == "asset":
        try:
            a = assetmod.describe(dst)
        except Exception as e:
            dst.unlink(missing_ok=True)
            raise HTTPException(400, str(e))
        store.update(sid, lambda s: s["assets"].append(a))
        return {"file": str(dst), "asset": a}
    else:
        _add_sources(sid, [dst])
    return {"file": str(dst)}


@app.post("/api/shoots/{sid}/reference-path")
def reference_path(sid: str, body: dict = Body(...)):
    p = Path(body.get("path", "").strip().strip('"'))
    if not p.is_file():
        raise HTTPException(400, f"no such file: {p}")
    store.update(_sid(sid), lambda s: s["reference"].update(file=str(p)))
    return {"ok": True}


@app.post("/api/shoots/{sid}/assets/grab")
def grab_frame(sid: str, body: dict = Body(...)):
    """Save one frame of the reference video (or a raw file: body.src = source id) as
    an image asset, e.g. the screenshot he points at. body.t = seconds."""
    s = store.load(_sid(sid))
    if body.get("src"):
        src = next((x for x in s["sources"] if x["id"] == body["src"]), None)
        video = src and src["file"]
    else:
        video = s["reference"]["file"]
    if not video or not Path(video).is_file():
        raise HTTPException(400, "load the reference video file first (① Video to copy)")
    t = float(body.get("t", 0))
    folder = store.UPLOAD_DIR / sid / "assets"
    folder.mkdir(parents=True, exist_ok=True)
    dst = folder / f"frame-{int(t * 1000):07d}-{store.new_id()}.png"
    try:
        assetmod.frame_at(Path(video), t).save(dst)
    except ValueError as e:
        raise HTTPException(400, str(e))
    a = assetmod.describe(dst, f"frame at {int(t // 60)}:{t % 60:04.1f}")
    store.update(sid, lambda s: s["assets"].append(a))
    return {"asset": a}


def _asset(sid, aid):
    a = next((a for a in store.load(_sid(sid))["assets"] if a["id"] == aid), None)
    if not a or not Path(a["file"]).is_file():
        raise HTTPException(404, "no such asset")
    return a


@app.get("/api/shoots/{sid}/assets/{aid}/preview.png")
def asset_preview(sid: str, aid: str):
    """The asset as it will appear (crop applied; first frame for video)."""
    return FileResponse(assetmod.preview_png(_asset(sid, aid)), media_type="image/png")


@app.get("/api/shoots/{sid}/assets/{aid}/file")
def asset_file(sid: str, aid: str):
    return FileResponse(_asset(sid, aid)["file"])


@app.get("/api/shoots/{sid}/reference")
def reference_file(sid: str):
    f = store.load(_sid(sid))["reference"]["file"]
    if not f or not Path(f).is_file():
        raise HTTPException(404, "no reference file")
    return FileResponse(f)


@app.get("/api/thumb/{key}")
def thumb(key: str, t: float):
    out = store.THUMB_DIR / f"{key}_{t:.2f}.jpg"
    if not out.exists():
        subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{t:.2f}",
                        "-i", str(store.PROXY_DIR / f"{key}.mp4"), "-frames:v", "1",
                        "-vf", "scale=180:-2", "-q:v", "4", str(out)], check=True)
    return FileResponse(out, media_type="image/jpeg", headers={"Cache-Control": "max-age=604800"})


@app.get("/api/words/{key}")
def words(key: str, t0: float = 0, t1: float = 1e9):
    return [w for w in takes.words_for(key) if w[2] >= t0 and w[1] <= t1]


# ---------- background jobs ----------

def _job_for(sid):
    live = [j for j in JOBS.values() if j["shoot"] == sid and j["state"] in ("queued", "running")]
    return live[-1] if live else None


@app.get("/studio-theme.css")
def studio_theme():
    """The shared Studio design system (shared/studio-theme.css), loaded last by every app."""
    return FileResponse(ROOT / "shared" / "studio-theme.css", media_type="text/css", headers={"Cache-Control": "no-cache"})


@app.get("/api/busy")
def busy():
    """For Studio (studio/): don't restart this app for an update while it's mid-job."""
    why = [j["kind"] for j in JOBS.values() if j.get("state") in ("queued", "running")]
    return {"busy": bool(why), "why": why}


def _start(sid: str, kind: str, work) -> dict:
    if _job_for(sid):
        raise HTTPException(409, "already working on this shoot")
    jid = uuid.uuid4().hex[:8]
    job = JOBS[jid] = {"id": jid, "shoot": sid, "kind": kind, "state": "queued", "msg": "waiting…",
                       "done": 0, "total": 1, "error": None, "started": time.time()}

    def run():
        with GPU:
            job["state"] = "running"
            try:
                work(job)
                job["state"] = "done"
            except Exception as e:  # shown in the editor
                job.update(state="error", error=str(e))
    threading.Thread(target=run, daemon=True).start()
    return job


@app.get("/api/shoots/{sid}/script")
def get_script(sid: str):
    s = store.load(_sid(sid))
    return {"lines": [l["text"] for l in s["script"]], "guessed": bool(s.get("script_guessed")),
            "ready": any(x["status"] == "ready" for x in s["sources"])}


@app.post("/api/shoots/{sid}/script")
def set_script(sid: str, body: dict = Body(...)):
    """The script from the shoots page: one line per line. Lines that didn't change keep
    their settings (outfit, transition, optional...); then the takes are re-matched."""
    texts = [t.strip() for t in str(body.get("text", "")).splitlines() if t.strip()]

    def fn(s):
        old = list(s["script"])
        by_text = {l["text"].strip(): l for l in old}
        new = []
        for i, t in enumerate(texts):
            l = by_text.pop(t, None) or (old[i] if len(old) == len(texts) and old[i]["text"].strip() not in texts else None)
            new.append({**(l or {"id": store.new_id(), "alts": [], "optional": False}), "text": t})
        s["script"] = new
        s["script_guessed"] = False
    s = store.update(_sid(sid), fn)
    if texts and any(x["status"] == "ready" for x in s["sources"]) and not _job_for(sid):
        _start(sid, "process", _process_work(sid, {}))
    return {"lines": len(texts)}


@app.post("/api/shoots/{sid}/process")
def process(sid: str, body: dict = Body(default={})):
    """Prep new raw files (preview copy + transcript), guess the script if there is
    none, then (re)match takes. body.guess = re-guess the script from the footage."""
    _sid(sid)
    return _start(sid, "process", _process_work(sid, body))


def _process_work(sid: str, body: dict):
    def work(job):
        s = store.load(sid)
        todo = [x for x in s["sources"] if x["status"] != "ready"]
        job["total"] = len(todo) + 1
        for i, src in enumerate(todo):
            job.update(done=i, msg=f"{src['name']}: starting")
            try:
                info = takes.prepare_source(Path(src["file"]), lambda m: job.update(msg=m))
                patch = {**info, "status": "ready", "error": None}
            except Exception as e:
                patch = {"status": "error", "error": str(e)}
            store.update(sid, lambda s: next(x for x in s["sources"] if x["id"] == src["id"]).update(patch))
        job.update(done=len(todo), msg="finding takes")

        def fn(s):
            ready = [(x["id"], takes.words_for(x["key"])) for x in s["sources"] if x["status"] == "ready"]
            if body.get("guess") or not [l for l in s["script"] if l["text"].strip()]:
                s["script"] = takes.guess_script(ready)
                s["script_guessed"] = True
            takes.match(s)
            takes.decide_mix(s)
        store.update(sid, fn)
        job.update(done=job["total"], msg="done")
    return work


# ---------- inbox: videos dropped in the cloud folder get pre-cut automatically ----------
PENDING = set()  # shoots the inbox wants processed while a job was already running


def _inbox_process(sid: str):
    try:
        _start(sid, "process", _process_work(sid, {}))
        PENDING.discard(sid)
    except HTTPException:
        PENDING.add(sid)


def _inbox_tick(_=None):
    for sid in list(PENDING):
        if not _job_for(sid):
            _inbox_process(sid)
    try:
        sheet.sync(_inbox_process)  # the "Scripts & Links" spreadsheet: a shoot per row
        if sheet.STATE.get("synced") and sheet.STATE.get("synced") != _ADOPTED.get("at"):
            _ADOPTED["at"] = sheet.STATE["synced"]
            shop.adopt_sheet()  # ...and a library script per row
    except Exception as e:  # noqa: BLE001  (shown on the home page)
        sheet.STATE["error"] = str(e)
    inbox.tick(_inbox_process)


_ADOPTED = {"at": None}


@app.get("/api/sheet")
def sheet_status():
    return sheet.STATE


@app.on_event("startup")
def _start_inbox():
    def loop():
        while True:
            _inbox_tick()
            time.sleep(30)
    threading.Thread(target=loop, daemon=True, name="inbox").start()
    shop.start_background()  # TikTok numbers for the accounts + posted videos, every few hours
    tunnel.start(int(os.environ.get("ADCUT_PORT", "8770")))  # the web link (adcut/tunnel.py)


@app.get("/api/weblink")
def weblink():
    """The current web link for the editor (changes when the PC restarts)."""
    return tunnel.state


@app.get("/api/inbox")
def inbox_status():
    d = inbox.inbox_dir()
    return {"dir": str(d), "exists": d.is_dir(), "icloud": (Path.home() / "iCloudDrive").is_dir(),
            "items": inbox.items(), **inbox.STATE}


@app.post("/api/inbox/dir")
def inbox_set_dir(body: dict = Body(...)):
    p = Path(body.get("path", "").strip().strip('"'))
    if not str(p) or not (p.is_dir() or p.parent.is_dir()):
        raise HTTPException(400, f"not a folder: {p}")
    p.mkdir(exist_ok=True)
    return {"dir": str(inbox.set_inbox_dir(str(p)))}


@app.post("/api/inbox/open")
def inbox_open():
    return {"dir": str(inbox.open_folder())}


def _clean_name(x: str) -> str:
    return "".join(c for c in Path(x or "").name if c not in '<>:"/\\|?*').strip(" .")


@app.get("/api/inbox/folders")
def inbox_folders():
    """Shoot folders already in the inbox (to drop more videos into one)."""
    d = inbox.inbox_dir()
    return sorted((e.name for e in d.iterdir() if e.is_dir() and not e.name.startswith(".")), key=str.lower) if d.is_dir() else []


@app.put("/api/inbox/upload")
async def inbox_upload(request: Request, name: str, offset: int = 0, total: int = 0, folder: str = "", shoot: str = ""):
    """Videos dropped on the home page go into the OneDrive inbox (folder = the shoot's
    name), so they're pre-cut like anything else dropped there. They come in pieces
    (the web link caps a request at 100 MB): each piece is appended at `offset`, and the
    file only gets its real name once all `total` bytes are in, so the inbox never picks
    up half a video. A piece that doesn't line up says where to resume (409)."""
    fname, sub = _clean_name(name), _clean_name(folder)
    if Path(fname).suffix.lower() not in VIDEO_EXTS:
        raise HTTPException(400, "only video files go in the inbox")
    if shoot:  # added to a shoot: its own OneDrive folder (made and linked if needed)
        d = inbox.folder_for(_sid(shoot), store.load(shoot)["title"])
        sub = d.name
    else:
        d = inbox.inbox_dir() / sub if sub else inbox.inbox_dir()
    d.mkdir(parents=True, exist_ok=True)
    part = d / f".{fname}.uploading"
    have = part.stat().st_size if part.exists() else 0
    if offset == 0:
        have = 0
    elif offset != have:
        return JSONResponse({"size": have}, status_code=409)
    with open(part, "wb" if offset == 0 else "ab") as f:
        async for chunk in request.stream():
            f.write(chunk)
    size = part.stat().st_size
    if total and size >= total:
        dst, n = d / fname, 2
        while dst.exists():
            dst, n = d / f"{Path(fname).stem} ({n}){Path(fname).suffix}", n + 1
        part.replace(dst)
        threading.Thread(target=_inbox_tick, daemon=True).start()
        return {"size": size, "done": True, "file": dst.name, "folder": sub}
    return {"size": size, "done": False}


@app.post("/api/inbox/scan")
def inbox_scan():
    threading.Thread(target=_inbox_tick, daemon=True).start()
    return {"ok": True}


@app.post("/api/shoots/{sid}/render")
def start_render(sid: str, body: dict = Body(default={})):
    """Render the given video numbers (default: every video not skipped)."""
    s = store.load(_sid(sid))
    nums = body.get("videos") or [v["n"] for v in store.videos(s)["videos"] if not v["skip"]]
    if not nums:
        raise HTTPException(400, "no videos to render")

    def work(job):
        job["total"] = len(nums)
        for i, n in enumerate(nums):
            job.update(done=i, msg=f"video {n} ({i + 1}/{len(nums)})")
            render.render_and_record(sid, n, lambda m: job.update(msg=m))
        job.update(done=len(nums), msg=f"{len(nums)} video(s) ready")
    return _start(sid, "render", work)


@app.post("/api/shoots/{sid}/download")
def start_download(sid: str, body: dict = Body(...)):
    """Save the chosen videos to the Outbox (rendering any that are out of date)."""
    s = store.load(_sid(sid))
    have = {v["n"] for v in store.videos(s)["videos"]}
    nums = [int(n) for n in body.get("videos", []) if int(n) in have]
    if not nums:
        raise HTTPException(400, "pick at least one video")

    def work(job):
        job["total"], job["files"] = len(nums), []
        for i, n in enumerate(nums):
            job.update(done=i, msg=f"video {n} ({i + 1}/{len(nums)})")
            job["files"].append(str(render.download_video(sid, n, lambda m: job.update(msg=m))))
        job["folder"] = str(Path(job["files"][-1]).parent)
        job.update(done=len(nums), msg=f"⬇ {len(nums)} video(s) saved to {Path(job['folder']).name}")
    return _start(sid, "download", work)


@app.get("/api/saved")
def saved_list():
    """Every saved video across all shoots (the posting queue)."""
    out = []
    shopd, stats = shop.load(), shop.load_stats()
    for row in store.shoots():
        s = store.load(row["id"])
        count = store.videos(s)["count"]
        for k, m in (s.get("saved") or {}).items():
            n = int(k)
            exists = n <= count
            takes = store.video_takes(s, n) if exists else []
            first = takes[0] if takes else None
            key = next((x["key"] for x in s["sources"] if first and x["id"] == first["src"]), None)
            r = s["renders"].get(k) or {}
            sig = render.video_sig(s, n) if exists else None
            out.append({
                "sid": row["id"], "title": s["title"], "n": n, "exists": exists,
                "saved_at": m.get("saved_at", 0), "posted": bool(m.get("posted")), "posted_at": m.get("posted_at"),
                "changed": bool(exists and m.get("sig") and m["sig"] != sig),
                "duration": round(sum(store.take_len(t, s) for t in takes), 1),
                "thumb": f"/api/thumb/{key}?t={round((first['in'] + first['out']) * 5) / 10:.1f}" if key else None,
                "rendered": bool(r.get("file") and Path(r["file"]).is_file()), "fresh": bool(r.get("sig") and r.get("sig") == sig),
                "downloaded": r.get("downloaded"),
                "product": s["product"]["name"], "link": s["product"]["link"],
                "description": s["product"]["description"], "hashtags": s["product"]["hashtags"],
                "account": m.get("account") or shop.plan_of(s)["account"], "url": m.get("url"),
                "product_id": shop.video_product(s, n, shopd), "views": ((stats["videos"].get(m.get("video_id") or "") or {}).get("snapshots") or [{}])[-1].get("views"),
            })
    return sorted(out, key=lambda r: (r["title"].lower(), r["n"]))


@app.post("/api/shoots/{sid}/saved")
def set_saved(sid: str, body: dict = Body(...)):
    """body: {n, saved?: bool, posted?: bool}"""
    n = str(int(body["n"]))

    def fn(s):
        m = s["saved"].get(n)
        if "saved" in body:
            if body["saved"]:
                vs = {v["n"]: v for v in store.videos(s)["videos"]}
                s["saved"][n] = {**(m or {}), "saved_at": (m or {}).get("saved_at") or time.time(), "sig": render.video_sig(s, int(n)),
                                 "takes": (m or {}).get("takes") or (list(vs[int(n)]["takes"]) if int(n) in vs else [])}
            else:
                s["saved"].pop(n, None)
        if "posted" in body:
            m = s["saved"].setdefault(n, {"saved_at": time.time(), "sig": render.video_sig(s, int(n))})
            if not m.get("takes"):
                # freeze it: these takes are now locked to this video (TikTok flags reuse)
                vs = {v["n"]: v for v in store.videos(s)["videos"]}
                m["takes"] = list(vs[int(n)]["takes"]) if int(n) in vs else []
            m["posted"] = bool(body["posted"])
            m["posted_at"] = time.time() if body["posted"] else None
    s = store.update(_sid(sid), fn)
    return {"saved": s["saved"]}


@app.get("/api/jobs/{jid}")
def job_status(jid: str):
    if jid not in JOBS:
        raise HTTPException(404, "no such job")
    return JOBS[jid]


# ---------- misc ----------

@app.get("/api/hookcard.png")
def hookcard_png(text: str, style: str = "{}"):
    """The deluxe text hook (adcut/titlefx.hook_card) on a 1080x640 band, for the editor."""
    from PIL import Image
    from . import titlefx
    card = titlefx.hook_card(text, json.loads(style))
    band = Image.new("RGBA", (1080, 640), (0, 0, 0, 0))
    band.alpha_composite(card, ((1080 - card.width) // 2, max(0, (640 - card.height) // 2)))
    buf = io.BytesIO()
    band.save(buf, "PNG")
    return Response(buf.getvalue(), media_type="image/png", headers={"Cache-Control": "max-age=86400"})


@app.get("/api/title.png")
def title_png(text: str, style: str = "{}"):
    """The game-show title card (adcut/titlefx.card), for the editor preview."""
    from . import titlefx
    buf = io.BytesIO()
    titlefx.card(text, json.loads(style)).save(buf, "PNG")
    return Response(buf.getvalue(), media_type="image/png", headers={"Cache-Control": "max-age=86400"})


@app.get("/api/caption.png")
def caption_png(text: str, style: str):
    buf = io.BytesIO()
    render_caption(text, {**json.loads(style), "y": 0.5}).save(buf, "PNG")
    return Response(buf.getvalue(), media_type="image/png", headers={"Cache-Control": "max-age=86400"})


@app.get("/api/sounds")
def sounds_list():
    """The soundboard (all synthesized here: free to use)."""
    return soundsmod.catalog()


@app.get("/api/fx")
def fx_list():
    """The effects board (TikTok Shop pointers, flash)."""
    return fxmod.catalog()


@app.get("/api/sound/{name}.wav")
def sound_wav(name: str):
    try:
        return FileResponse(soundsmod.sound_file(name), media_type="audio/wav", headers={"Cache-Control": "max-age=86400"})
    except KeyError:
        raise HTTPException(404, "no such sound")


@app.get("/api/presets")
def presets():
    return PRESETS


@app.get("/api/fonts")
def fonts():
    return fontsmod.available()


@app.post("/api/shoots/{sid}/open-folder")
def open_folder(sid: str, which: str = "renders"):
    s = store.load(_sid(sid))
    if which == "downloads":
        import datetime
        today = store.DOWNLOAD_DIR / datetime.date.today().isoformat()
        folder = today if today.is_dir() else store.DOWNLOAD_DIR
    else:
        folder = render.output_path(s, sid, 1).parent
    os.startfile(folder)
    return {"folder": str(folder)}


@app.get("/api/output/{sid}/{n}")
def output_video(sid: str, n: int, dl: int = 0):
    """The rendered video (dl=1: as a download named "<shoot> - video NN.mp4")."""
    s = store.load(_sid(sid))
    r = s["renders"].get(str(n))
    if not r or not Path(r["file"]).is_file():
        raise HTTPException(404, "not rendered")
    name = f"{render._safe(s['title'] or sid)} - video {n:02d}.mp4" if dl else None
    return FileResponse(r["file"], media_type="video/mp4", filename=name)


@app.get("/api/shoots/{sid}/review")
def review(sid: str):
    """Review mode: every video of a shoot, ready to watch, download, save or post."""
    s = store.load(_sid(sid))
    srcs = {x["id"]: x for x in s["sources"]}
    order = {l["id"]: i for i, l in enumerate(s["script"])}
    out = []
    for v in store.videos(s)["videos"]:
        n = v["n"]
        if v.get("empty"):
            continue
        takes = store.video_takes(s, n)
        r = s["renders"].get(str(n)) or {}
        sig = render.video_sig(s, n)
        m = s["saved"].get(str(n)) or {}
        first = takes[0] if takes else None
        key = srcs.get(first["src"], {}).get("key") if first else None
        text = " ".join(" ".join(w[0] for w in t["words"] if t["in"] <= (w[1] + w[2]) / 2 <= t["out"]
                                 and not store.in_cut(t, (w[1] + w[2]) / 2)) for t in takes)
        flags = safety.check(text)
        odd = [order.get(t["line"], 0) + 1 for t in takes if t.get("variant")]
        out.append({
            "n": n, "duration": round(sum(store.take_len(t, s) for t in takes), 1), "skip": v.get("skip"),
            "rendered": bool(r.get("file") and Path(r["file"]).is_file()), "fresh": bool(r.get("sig") and r["sig"] == sig),
            "sig": (r.get("sig") or "")[:12], "downloaded": r.get("downloaded"),
            "saved": bool(m), "posted": bool(m.get("posted")), "locked": bool(m.get("takes")),
            "thumb": f"/api/thumb/{key}?t={round((first['in'] + first['out']) * 5) / 10:.1f}" if key else None,
            "safety": safety.level(flags), "safety_cats": sorted({f["cat"] for f in flags}),
            "game": next((t.get("game") for t in takes if t.get("game")), None),
            "spice": max((t.get("spice") for t in takes if t.get("spice") is not None), default=None),
            "odd_lines": odd, "text": text,
            "voice": next((f.split(":")[0] for t in takes[:1] for f in t.get("flags") or [] if " + " in f),
                          (store.voice_for(s, n) or {}).get("label")),
        })
    p = s["product"]
    return {"id": sid, "title": s["title"], "product": p.get("name"), "link": p.get("link"),
            "caption": "\n\n".join(x for x in (p.get("description", "").strip(), p.get("hashtags", "").strip()) if x),
            "videos": out, "job": _job_for(sid)}


@app.get("/api/safety")
def safety_rules():
    """TikTok Shop safety word lists (adcut/safety.py), checked live in the editor."""
    return safety.rules_json()


@app.get("/api/shoots/{sid}/previews")
def previews(sid: str):
    """Each video pre-rendered for smooth editor playback (builds stale ones in the background)."""
    return preview.status(_sid(sid))


preview.PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/previews", StaticFiles(directory=preview.PREVIEW_DIR), name="previews")
app.mount("/proxy", StaticFiles(directory=store.PROXY_DIR), name="proxy")
app.mount("/fonts", StaticFiles(directory=FONTS_DIR), name="fonts")


@app.get("/")
def index():
    return FileResponse(EDITOR_DIR / "index.html")


app.mount("/", StaticFiles(directory=EDITOR_DIR), name="editor")
