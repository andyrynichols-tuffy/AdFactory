"""Competitor tracker (Analytics → Competitors): what other creators' TikTok Shop videos probably sell.

Estimated the way the paid tools (Kalodata and the like) do it, from public counters only, once a day:
- each tracked profile's video grid (views per video, from the signed-in off-screen window the
  Analytics reader uses), plus each new video's page once (when it was posted, its tagged products);
- each tagged product's page: its public "items sold" count and price.
A product's sold count going up × its price = its sales that day; that's split across the profile's
videos tagging it by how many views each gained. The count is the product's total across everyone who
sells it, so for a popular product this is an upper bound for the creator, never his real share. No
history before tracking starts; nothing about clicks or conversion (only the seller/creator sees those).
Data: ads/_competitors.json."""
import json
import random
import re
import threading
import time

from supercut.config import ROOT

from . import productlink, store

FILE = store.SHOOTS_DIR / "_competitors.json"
_lock = threading.Lock()
status = {"running": False, "msg": "", "last": None}
WINDOW_DAYS = 30  # videos younger than this are followed


def load() -> dict:
    try:
        d = json.loads(FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        d = {}
    d.setdefault("profiles", {})   # handle -> {added, last, videos: {id: {...}}}
    d.setdefault("products", {})   # product id -> {title, price, link, snaps: [{t, sold}]}
    d.setdefault("settings", {"every_hours": 24})
    return d


def save(d):
    with _lock:
        tmp = FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        tmp.replace(FILE)


def add(handle: str) -> dict:
    h = handle.strip().lstrip("@").lower()
    if not re.fullmatch(r"[\w.]{2,40}", h):
        raise ValueError("That doesn't look like a TikTok handle")
    d = load()
    d["profiles"].setdefault(h, {"added": time.time(), "last": None, "videos": {}})
    save(d)
    return {"handle": h}


def remove(handle: str):
    d = load()
    d.setdefault("removed", {})[handle] = d["profiles"].pop(handle, None)  # kept, not deleted
    save(d)


def seed(handle: str, pages: list):
    """Video details already read elsewhere (the @sully.finds study), so the first pass needn't re-read them."""
    d = load()
    p = d["profiles"].setdefault(handle, {"added": time.time(), "last": None, "videos": {}})
    for r in pages:
        v = p["videos"].setdefault(r["id"], {"snaps": []})
        v.update(created=r["created"], desc=r.get("desc", ""), carousel=bool(r.get("images")),
                 products=[x["id"] for x in r.get("products") or []])
        for x in r.get("products") or []:
            d["products"].setdefault(x["id"], {"title": x.get("title") or "", "snaps": []})
        st = r.get("stats") or {}
        if st.get("playCount") is not None and not v["snaps"]:
            v["snaps"].append({"t": round(time.time()), "views": int(st["playCount"])})
    save(d)


def _video_page(url):
    from supercut import analytics as an
    _, html = an._get(url)
    item = an._scope(html).get("webapp.video-detail", {}).get("itemInfo", {}).get("itemStruct", {})
    prods = []
    for a in item.get("anchors") or []:
        try:
            for x in json.loads(a.get("extra") or "[]"):
                if isinstance(x, dict) and x.get("type") == 33:
                    info = json.loads(x.get("extra") or "{}")
                    prods.append((str(info.get("product_id") or x.get("id")), info.get("title") or x.get("keyword") or ""))
        except ValueError:
            pass
    return {"created": int(item.get("createTime") or 0), "desc": item.get("desc", ""),
            "carousel": bool((item.get("imagePost") or {}).get("images")), "products": prods,
            "views": int((item.get("stats") or {}).get("playCount") or 0)}


def _grid(handle, expect):
    """The profile's newest ~expect video tiles (views each), scrolled in its own process."""
    import subprocess
    import sys
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    out = subprocess.run([sys.executable, "-m", "supercut.tiktok_grid", handle, str(expect), "900"],
                         capture_output=True, text=True, timeout=1100, creationflags=flags, cwd=str(ROOT)).stdout
    try:
        return json.loads(out.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"items": []}


def refresh(only=None, pause=(3.0, 6.0)):
    """One daily pass (gentle: one page at a time)."""
    from supercut import analytics as an
    if status["running"]:
        return
    status.update(running=True, msg="starting…")
    try:
        d = load()
        cut = time.time() - WINDOW_DAYS * 86400
        for h, p in list(d["profiles"].items()):
            if only and h != only:
                continue
            status["msg"] = f"@{h}: reading the profile"
            recent = sum(1 for v in p["videos"].values() if v.get("created", 0) >= cut)
            g = _grid(h, expect=min(1200, int(recent * 1.15) + 60) if recent else 900)
            now = round(time.time())
            for it in g.get("items") or []:
                v = p["videos"].get(it["video_id"])
                if v is None:  # new: read its page once
                    status["msg"] = f"@{h}: new video {it['video_id']}"
                    try:
                        info = _video_page(it["url"])
                    except Exception:
                        continue
                    if info["created"] and info["created"] < cut:
                        continue
                    v = p["videos"][it["video_id"]] = {"created": info["created"], "desc": info["desc"], "carousel": info["carousel"],
                                                        "products": [pid for pid, _ in info["products"]], "snaps": []}
                    for pid, title in info["products"]:
                        d["products"].setdefault(pid, {"title": title, "snaps": []})
                    time.sleep(random.uniform(*pause))
                views = it.get("views")
                if views is not None and v.get("created", 0) >= cut:
                    v["snaps"].append({"t": now, "views": views})
                    v["snaps"] = v["snaps"][-90:]
            p["last"] = now
            save(d)
        # the products these videos tag: their public sold count
        wanted = {pid for p in d["profiles"].values() for v in p["videos"].values()
                  if v.get("created", 0) >= cut for pid in v.get("products") or []}
        for n, pid in enumerate(sorted(wanted)):
            status["msg"] = f"products {n + 1}/{len(wanted)}"
            try:
                info = productlink.tiktok_product(f"https://www.tiktok.com/view/product/{pid}")
            except Exception:
                continue
            rec = d["products"].setdefault(pid, {"snaps": []})
            rec.update(title=productlink.short_name(info["name"]) or rec.get("title", ""), full=info["name"], link=info["link"],
                       price=info["min_price"], price_text=info["price"], image=info["image"], brand=info["brand"])
            if info["sold"] is not None:
                rec["snaps"].append({"t": round(time.time()), "sold": info["sold"]})
                rec["snaps"] = rec["snaps"][-90:]
            if n % 10 == 0:
                save(d)
            time.sleep(random.uniform(*pause))
        d["last"] = time.time()
        save(d)
        status["last"] = d["last"]
    finally:
        status.update(running=False, msg="")


def busy() -> list:
    return ["competitors"] if status["running"] else []


def start_background():
    def loop():
        time.sleep(1800)
        while True:
            d = load()
            if d["profiles"] and time.time() - (d.get("last") or 0) >= d["settings"].get("every_hours", 24) * 3600:
                try:
                    refresh()
                except Exception as e:
                    status["msg"] = f"last check failed: {e}"
            time.sleep(1800)
    threading.Thread(target=loop, daemon=True, name="competitors").start()


# ---------------------------------------------------------------- the estimates

def _delta(snaps, key, since):
    """Growth of a counter since `since` (from the first snapshot at/after it, if older ones are missing)."""
    if len(snaps) < 2:
        return None
    base = [s for s in snaps if s["t"] <= since]
    a = base[-1] if base else snaps[0]
    return max(0, snaps[-1][key] - a[key]) if snaps[-1]["t"] > a["t"] else None


def view(handle: str, days: int = 7) -> dict:
    d = load()
    p = d["profiles"].get(handle)
    if not p:
        raise KeyError(handle)
    since = time.time() - days * 86400
    vids = p["videos"]
    gain = {vid: (_delta(v.get("snaps") or [], "views", since) or 0) for vid, v in vids.items()}
    by_product = {}
    for vid, v in vids.items():
        for pid in v.get("products") or []:
            by_product.setdefault(pid, []).append(vid)
    products, vid_rev = [], {}
    for pid, vs in by_product.items():
        pr = d["products"].get(pid) or {}
        sold = _delta(pr.get("snaps") or [], "sold", since)
        rev = round(sold * pr["price"], 2) if sold is not None and pr.get("price") else None
        total = sum(gain[x] for x in vs)
        for x in vs:  # his videos share the product's sales by the views each gained
            if rev is not None:
                vid_rev[x] = vid_rev.get(x, 0) + (rev * gain[x] / total if total else rev / len(vs))
        products.append({"id": pid, "title": pr.get("title") or pid, "link": pr.get("link"), "price": pr.get("price_text"),
                         "videos": len(vs), "view_gain": total, "sold": sold, "est_revenue": rev,
                         "sold_total": (pr.get("snaps") or [{}])[-1].get("sold"), "tracked_since": (pr.get("snaps") or [{}])[0].get("t")})
    products.sort(key=lambda x: -(x["est_revenue"] or 0))
    videos = [{"id": vid, "url": f"https://www.tiktok.com/@{handle}/video/{vid}", "desc": v.get("desc", "")[:90], "created": v.get("created"),
               "carousel": v.get("carousel"), "views": (v.get("snaps") or [{}])[-1].get("views"), "view_gain": gain[vid],
               "est_revenue": round(vid_rev[vid], 2) if vid in vid_rev else None, "products": v.get("products") or []}
              for vid, v in vids.items()]
    videos.sort(key=lambda x: (-(x["est_revenue"] or 0), -(x["view_gain"] or 0)))
    est = [x["est_revenue"] for x in products if x["est_revenue"] is not None]
    return {"handle": handle, "days": days, "videos_tracked": len(vids), "products_tracked": len(by_product),
            "est_revenue": round(sum(est), 2) if est else None, "posted": sum(1 for v in vids.values() if v.get("created", 0) >= since),
            "products": products[:40], "videos": videos[:40], "last": p.get("last"), "status": dict(status),
            "history_days": round((time.time() - min([s["t"] for pr in d["products"].values() for s in pr.get("snaps") or []] or [time.time()])) / 86400, 1)}


def summary() -> list:
    d = load()
    return [{"handle": h, "videos": len(p["videos"]), "last": p.get("last")} for h, p in d["profiles"].items()]
