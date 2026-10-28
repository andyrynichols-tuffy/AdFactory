"""Analytics: how every video on the TikTok account does, linked (both ways) to posts made here.

No TikTok developer app. Sources:
- the account's video list: the profile's video grid, read in a hidden browser window that's
  signed into TikTok once (supercut/tiktok_grid.py; TikTok only shows the grid signed-in);
- each video's numbers (views, likes, comments, shares, saves) from its public page;
- account totals (followers, likes, video count) from the public profile.
Everything is refreshed every few hours, politely (one page at a time, with pauses), and
every snapshot is kept so growth over time is visible.

Every video on the account is tracked whether or not it came from this app. A video can be
linked to the post it came from, from either side (video -> pick post, post -> pick video
or paste its link); likely pairs are suggested by matching the TikTok caption against the
post's description and the dates, and confident ones are linked automatically.
Data: projects/_analytics.json  {"videos": {video_id: {...}}, "account": ..., "settings": ...}.
The numbers also feed the taste report (top performers)."""
import functools
import json
import random
import re
import subprocess
import sys
import threading
import time
import urllib.request
from difflib import SequenceMatcher

from .config import DATA_DIR, PROJECTS_DIR

FILE = PROJECTS_DIR / "_analytics.json"
COVERS = DATA_DIR / "tiktok-covers"  # local copies: TikTok's cover links expire within hours
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/141.0 Safari/537.36")
VIDEO_RX = re.compile(r"tiktok\.com/@([\w.]+)/video/(\d{8,})")
_lock = threading.Lock()
status = {"running": False, "msg": "", "last": None, "grid": None}
SUGGEST_AT, AUTO_AT = 0.45, 0.85  # match scores: show a suggestion / link without asking


# ---------------------------------------------------------------- storage

def load() -> dict:
    try:
        d = json.loads(FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        d = {}
    d.setdefault("videos", {})
    d.setdefault("account", {"handle": "", "snapshots": []})
    d.setdefault("settings", {"every_hours": 6})
    if d.get("posts"):  # v1 kept one entry per linked post: move them under their video
        for name, p in d.pop("posts").items():
            m = VIDEO_RX.search(p.get("url") or "")
            vid = p.get("video_id") or (m.group(2) if m else None)
            if vid:
                d["videos"][vid] = {"url": p.get("url"), "desc": p.get("tiktok_desc", ""), "created": p.get("created"),
                                    "snapshots": p.get("snapshots") or [], "post": name, "error": p.get("error")}
        save(d)
    d.pop("posts", None)
    return d


def save(d):
    FILE.write_text(json.dumps(d, indent=1, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------- reading TikTok

def _get(url: str) -> tuple:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.geturl(), r.read().decode("utf-8", "replace")


def _scope(html: str) -> dict:
    m = re.search(r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        raise ValueError("TikTok didn't return the page data (try again later)")
    return json.loads(m.group(1)).get("__DEFAULT_SCOPE__", {})


def _num(v) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def fetch_video(url: str) -> dict:
    """Stats + identity of one public TikTok video (short vm./t/ links are followed)."""
    final, html = _get(url.strip())
    m = VIDEO_RX.search(final) or VIDEO_RX.search(url)
    item = _scope(html).get("webapp.video-detail", {}).get("itemInfo", {}).get("itemStruct", {})
    if not item:
        raise ValueError("That link doesn't look like a public TikTok video")
    st = item.get("stats") or {}
    return {
        "url": f"https://www.tiktok.com/@{m.group(1)}/video/{m.group(2)}" if m else final,
        "video_id": item.get("id") or (m.group(2) if m else ""),
        "handle": (item.get("author") or {}).get("uniqueId") or (m.group(1) if m else ""),
        "desc": item.get("desc", ""), "created": _num(item.get("createTime")),
        "cover": (item.get("video") or {}).get("cover") or (item.get("video") or {}).get("originCover") or "",
        "stats": {"views": _num(st.get("playCount")), "likes": _num(st.get("diggCount")),
                  "comments": _num(st.get("commentCount")), "shares": _num(st.get("shareCount")),
                  "saves": _num(st.get("collectCount"))},
    }


def fetch_account(handle: str) -> dict:
    _, html = _get(f"https://www.tiktok.com/@{handle.lstrip('@')}")
    u = _scope(html).get("webapp.user-detail", {}).get("userInfo", {})
    st = u.get("stats") or {}
    if not u:
        raise ValueError("Couldn't read that profile")
    return {"followers": _num(st.get("followerCount")), "likes": _num(st.get("heartCount") or st.get("heart")),
            "videos": _num(st.get("videoCount"))}


def grid(handle: str, expect: int = 0) -> dict:
    """Every video on the profile, from the signed-in hidden window (own process: a window
    needs its own main thread)."""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    out = subprocess.run([sys.executable, "-m", "adkit.tiktok_grid", handle, str(expect)],
                         capture_output=True, text=True, timeout=240, creationflags=flags).stdout
    try:
        return json.loads(out.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"items": [], "error": "couldn't read the profile's videos"}


def signed_in() -> bool:
    from . import tiktok_grid
    return tiktok_grid.signed_in()


def open_login():
    """The one-time 'sign in to TikTok' window (the user signs in; we never see it)."""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen([sys.executable, "-m", "adkit.tiktok_grid", "--login"], creationflags=flags)


# ---------------------------------------------------------------- linking (both directions)

def _add_video(d, v: dict):
    rec = d["videos"].setdefault(v["video_id"], {"snapshots": [], "post": None, "first_seen": time.time()})
    rec.update(url=v["url"], desc=v.get("desc") or rec.get("desc", "") or v.get("alt", ""),
               created=v.get("created") or rec.get("created"))
    if v.get("cover"):
        rec["cover"] = v["cover"]  # TikTok's signed cover link: shown while it lasts
    return rec


def link(name: str, url: str) -> dict:
    """Post -> video: connect a post to its TikTok video by link (checks it, first snapshot)."""
    v = fetch_video(url)
    with _lock:
        d = load()
        rec = _add_video(d, v)
        for other in d["videos"].values():  # one video per post
            if other is not rec and other.get("post") == name:
                other["post"] = None
        rec["post"] = name
        rec["snapshots"].append({"t": time.time(), **v["stats"]})
        rec.pop("error", None)
        if not d["account"].get("handle") and v["handle"]:
            d["account"]["handle"] = v["handle"]
        save(d)
    return v


def link_video(video_id: str, name):
    """Video -> post (or None to unlink). Returns the video's record."""
    with _lock:
        d = load()
        rec = d["videos"].get(video_id)
        if rec is None:
            raise KeyError("unknown video")
        if name:
            for other in d["videos"].values():
                if other is not rec and other.get("post") == name:
                    other["post"] = None
        rec["post"] = name or None
        rec["dismissed"] = [] if name else rec.get("dismissed", [])
        save(d)
        return rec


def unlink(name: str):
    """Disconnect a post from its video (the video itself stays tracked: it's on the account)."""
    with _lock:
        d = load()
        for rec in d["videos"].values():
            if rec.get("post") == name:
                rec["post"] = None
        save(d)


def dismiss(video_id: str, name: str):
    """'Not this one' on a suggestion, so it isn't suggested again."""
    with _lock:
        d = load()
        rec = d["videos"].get(video_id)
        if rec is not None:
            rec.setdefault("dismissed", [])
            if name not in rec["dismissed"]:
                rec["dismissed"].append(name)
            save(d)


def set_external(video_id: str, external: bool):
    """'Not made in Studio': a video made elsewhere. It's never suggested or auto-linked to a post
    (and loses its link if it had one); Analytics can filter by it."""
    with _lock:
        d = load()
        rec = d["videos"].get(video_id)
        if rec is None:
            raise KeyError("unknown video")
        rec["external"] = bool(external)
        if external:
            rec["post"] = None
        save(d)
        return rec


def forget(video_id: str):
    """Stop tracking a video (e.g. deleted from TikTok)."""
    with _lock:
        d = load()
        d["videos"].pop(video_id, None)
        d.setdefault("ignored", [])
        if video_id not in d["ignored"]:
            d["ignored"].append(video_id)  # the profile grid would only bring it back
        save(d)


def by_post() -> dict:
    """post name -> its video record (with 'video_id')."""
    return {r["post"]: {**r, "video_id": vid} for vid, r in load()["videos"].items() if r.get("post")}


# ---------------------------------------------------------------- matching

def _words(s: str) -> str:
    s = re.sub(r"#\w+", " ", (s or "").lower())
    return " ".join(re.findall(r"[a-z0-9']+", s))


@functools.lru_cache(maxsize=50000)
def _text_score(vd: str, texts: tuple) -> float:
    """Best text match (cached: Analytics recomputes every suggestion on each load)."""
    return max((SequenceMatcher(None, vd, t).ratio() for t in texts if t), default=0.0)


def _score(video: dict, post: dict) -> float:
    """How likely `video` is `post`: caption/description text match, nudged by the dates."""
    vd = _words(video.get("desc"))
    if not vd:
        return 0.0
    s = _text_score(vd, (_words(post.get("description")), _words(post.get("caption")), _words(post.get("title"))))
    vt, pt = video.get("created") or 0, post.get("posted_at") or 0
    if vt and pt:
        days = abs(vt - pt) / 86400
        s += 0.1 if days < 2 else -0.1 if days > 30 else 0
    return round(min(1.0, s), 3)


def suggestions(d: dict, posts_meta: dict) -> dict:
    """video_id -> (post name, score) for unlinked videos, best unclaimed match each."""
    taken = {r["post"] for r in d["videos"].values() if r.get("post")}
    pool = {n: m for n, m in posts_meta.items() if n not in taken and not m.get("deleted")}
    out = {}
    for vid, rec in d["videos"].items():
        if rec.get("post") or rec.get("external"):
            continue
        no = set(rec.get("dismissed") or [])
        scored = sorted(((_score(rec, m), n) for n, m in pool.items() if n not in no), reverse=True)
        if scored and scored[0][0] >= SUGGEST_AT:
            second = scored[1][0] if len(scored) > 1 else 0
            out[vid] = (scored[0][1], scored[0][0], scored[0][0] - second)
    return out


def auto_link(posts_meta: dict) -> list:
    """Link the confident pairs without asking. Returns [(post name, video created)]."""
    linked = []
    with _lock:
        d = load()
        used = set()
        for vid, (name, score, margin) in suggestions(d, posts_meta).items():
            if score >= AUTO_AT and margin >= 0.15 and name not in used:
                d["videos"][vid]["post"] = name
                used.add(name)
                linked.append((name, d["videos"][vid].get("created")))
        if linked:
            save(d)
    return linked


# ---------------------------------------------------------------- refresh

def refresh(posts_meta_fn=None, on_link=None):
    """One polite pass: the account's video list, then every video's numbers, then the account,
    then auto-linking. posts_meta_fn() -> {name: post summary}; on_link(name, created) marks a
    newly linked post as posted."""
    if status["running"]:
        return
    status.update(running=True, msg="starting")
    try:
        handle = load()["account"].get("handle")
        acct = None
        if handle:
            status["msg"] = "account"
            try:
                acct = fetch_account(handle)
            except Exception:
                acct = None
            status["msg"] = "reading your videos"
            g = grid(handle, (acct or {}).get("videos", 0))
            status["grid"] = {"t": time.time(), "found": len(g.get("items", [])), "error": g.get("error"),
                              "expected": (acct or {}).get("videos")}
            with _lock:
                d = load()
                skip = set(d.get("ignored") or [])
                for it in g.get("items", []):
                    # only this account's own videos: the profile page also shows other people's
                    # (reposts, suggestions), and anything removed here stays removed
                    if it["video_id"] in skip or (it.get("handle") or "").lower() != handle.lower():
                        continue
                    _add_video(d, {**it, "desc": d["videos"].get(it["video_id"], {}).get("desc", "")})
                save(d)
            for it in g.get("items", []):  # the grid's cover links are fresh right now
                if it["video_id"] in d["videos"]:
                    save_cover(it["video_id"], it.get("cover"))
        d = load()
        vids = list(d["videos"])
        for i, vid in enumerate(vids):
            url = d["videos"][vid].get("url")
            if not url:
                continue
            status["msg"] = f"video {i + 1}/{len(vids)}"
            try:
                v = fetch_video(url)
                save_cover(vid, v.get("cover"))  # outside the lock: it's a download
                with _lock:
                    d2 = load()
                    if vid in d2["videos"] and handle and (v.get("handle") or "").lower() not in ("", handle.lower()):
                        d2["videos"].pop(vid)  # someone else's video: drop it for good
                        d2.setdefault("ignored", []).append(vid)
                        save(d2)
                    elif vid in d2["videos"]:
                        rec = _add_video(d2, v)
                        rec["snapshots"].append({"t": time.time(), **v["stats"]})
                        rec.pop("error", None)
                        save(d2)
            except Exception as e:  # deleted/private video, network blip: note it, carry on
                with _lock:
                    d2 = load()
                    if vid in d2["videos"]:
                        d2["videos"][vid]["error"] = str(e)[:160]
                        save(d2)
            time.sleep(random.uniform(4, 9))
        if acct:
            with _lock:
                d2 = load()
                d2["account"]["snapshots"].append({"t": time.time(), **acct})
                save(d2)
        if posts_meta_fn:
            for name, created in auto_link(posts_meta_fn()):
                if on_link:
                    on_link(name, created)
        status["last"] = time.time()
    finally:
        status.update(running=False, msg="")


# ---------------------------------------------------------------- reporting

def _latest(snaps):
    return snaps[-1] if snaps else None


def _ago(snaps, seconds):
    """The last snapshot at least `seconds` old (for 24h / 7d growth)."""
    cut = time.time() - seconds
    old = [s for s in snaps if s["t"] <= cut]
    return old[-1] if old else None


def engagement(s) -> float:
    return round(100 * (s["likes"] + s["comments"] + s["shares"] + s["saves"]) / s["views"], 1) if s and s["views"] else 0.0


def cover_file(video_id: str):
    return COVERS / f"{video_id}.jpg"


def save_cover(video_id: str, url: str) -> bool:
    """Keep a local copy of a video's cover (once; TikTok's signed links stop working)."""
    f = cover_file(video_id)
    if f.exists() or not url:
        return f.exists()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": "https://www.tiktok.com/"})
        with urllib.request.urlopen(req, timeout=20) as r:
            data = r.read()
        if len(data) < 500:
            return False
        COVERS.mkdir(parents=True, exist_ok=True)
        f.write_bytes(data)
        return True
    except Exception:
        return False


def _post_card(name, m):
    return {"name": name, "title": m.get("title") or name, "caption": (m.get("caption") or "").replace("*", ""),
            "description": m.get("description", ""), "hashtags": m.get("hashtags", ""), "kind": m.get("kind"),
            "duration": m.get("duration"), "episodes": m.get("episodes_label", ""), "batch": m.get("batch"),
            "video": m.get("render"), "thumb": f"/api/posts/{name}/thumb.jpg?v={m.get('mtime', 0)}",
            "posted": bool(m.get("posted")), "posted_at": m.get("posted_at")}


def summary(posts_meta: dict) -> dict:
    """Everything the Analytics page shows. posts_meta: name -> post summary (from the editor)."""
    d = load()
    sugg = suggestions(d, posts_meta)
    rows = []
    for vid, r in d["videos"].items():
        snaps = r.get("snapshots") or []
        last, day = _latest(snaps), _ago(snaps, 86400)
        post = r.get("post")
        s = sugg.get(vid)
        rows.append({
            "video_id": vid, "url": r.get("url"), "desc": r.get("desc", ""), "created": r.get("created"),
            "cover": f"/api/analytics/cover/{vid}.jpg" if cover_file(vid).exists() else r.get("cover"),
            "error": r.get("error"), "external": bool(r.get("external")),
            "stats": {k: last[k] for k in ("views", "likes", "comments", "shares", "saves")} if last else None,
            "engagement": engagement(last), "views_24h": (last["views"] - day["views"]) if last and day else None,
            "trend": [x["views"] for x in snaps][-30:], "updated": last["t"] if last else None,
            "post": _post_card(post, posts_meta.get(post, {})) if post else None,
            "suggest": {**_post_card(s[0], posts_meta.get(s[0], {})), "score": s[1]} if s else None,
        })
    linked = {r["post"]["name"] for r in rows if r["post"]}
    unlinked_posts = sorted((_post_card(n, m) for n, m in posts_meta.items()
                             if m.get("posted") and n not in linked and not m.get("deleted")),
                            key=lambda u: -(u["posted_at"] or 0))
    # every post, for the 'link to post' picker (newest first)
    picker = sorted(({"name": n, "title": m.get("title") or n, "caption": (m.get("caption") or "").replace("*", ""),
                      "thumb": f"/api/posts/{n}/thumb.jpg?v={m.get('mtime', 0)}", "posted": bool(m.get("posted")),
                      "batch": m.get("batch"), "mtime": m.get("mtime", 0), "linked": n in linked}
                     for n, m in posts_meta.items() if not m.get("deleted")), key=lambda p: -p["mtime"])
    acct = d["account"]
    return {"rows": rows, "unlinked": unlinked_posts, "posts": picker,
            "account": {"handle": acct.get("handle"), "latest": _latest(acct.get("snapshots") or []),
                        "day": _ago(acct.get("snapshots") or [], 86400)},
            "status": status, "every_hours": d["settings"]["every_hours"], "signed_in": signed_in()}


def set_handle(handle: str):
    with _lock:
        d = load()
        d["account"]["handle"] = handle.strip().lstrip("@")
        save(d)


def top_performers(n=8) -> list:
    """For the taste report: best posts (linked videos) by views and engagement."""
    out = []
    for name, r in by_post().items():
        last = _latest(r.get("snapshots") or [])
        if last:
            out.append((name, last["views"], engagement(last)))
    return sorted(out, key=lambda x: -x[1])[:n]


def format_breakdown() -> list:
    """For the taste report: how each kind of Studio post does on TikTok, best first.
    [(format, posts, median views, median engagement %)]. Formats = post type + look +
    the project's style word ("universal", "fan-edit style"...). Also flags burst posting."""
    from statistics import median
    from . import edl
    groups, times = {}, []
    for name, r in by_post().items():
        last = _latest(r.get("snapshots") or [])
        if not last:
            continue
        try:
            e = edl.load(name)
        except Exception:
            continue
        st = e.get("style") or {}
        cap = st.get("caption") if isinstance(st.get("caption"), dict) else {}
        style = (e.get("batch") or "").split("·")[-1].strip() if "·" in (e.get("batch") or "") else ""
        n = len(e.get("clips") or [])
        key = " · ".join(x for x in (e.get("kind") or "single", f"{n} clip{'s' * (n != 1)}" if e.get("kind") == "montage" else "",
                                     cap.get("preset") or "", st.get("layout") or "", style) if x)
        groups.setdefault(key, []).append((last["views"], engagement(last)))
        times.append((r.get("created") or 0, last["views"]))
    out = [(k, len(v), int(median(x[0] for x in v)), round(median(x[1] for x in v), 1)) for k, v in groups.items()]
    times.sort()
    burst = [v for i, (t, v) in enumerate(times) if (i and t - times[i - 1][0] < 1800) or (i + 1 < len(times) and times[i + 1][0] - t < 1800)]
    spaced = [v for (t, v) in times if all(abs(t - u) >= 1800 for (u, _) in times if u != t)]
    if burst and spaced:
        out.append((f"(posted within 30 min of another post: median {int(median(burst))} views vs {int(median(spaced))} when spaced out)", len(burst), 0, 0))
    return sorted(out, key=lambda x: -x[2])


def start_background(posts_meta_fn=None, on_link=None):
    """Refresh every few hours while the editor runs (the first pass a minute after start)."""
    def loop():
        time.sleep(60)
        while True:
            d = load()
            last = max((s["t"] for r in d["videos"].values() for s in r.get("snapshots") or []), default=0)
            if (d["videos"] or d["account"].get("handle")) and time.time() - last > d["settings"]["every_hours"] * 3600:
                try:
                    refresh(posts_meta_fn, on_link)
                except Exception:
                    pass
            time.sleep(900)
    threading.Thread(target=loop, daemon=True, name="analytics").start()
