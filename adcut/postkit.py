"""Posting kit for a planned day (user, 2026-10-27): once the takes are in, do as much of the posting
work as possible. Every post in the day's posting schedule gets its own folder,

    <Outbox>/<date> posts/NN HH.MM <format> - <product>/
        video.mp4          the finished video (rendered with its captions), for video posts
        photo-1.jpg …      the carousel's 2-5 photos (a different outfit around the item in each), uploaded from the Mac or phone
        description.txt    what to paste into TikTok: the description, the product to tag and its link

and progress is tracked per post: footage in → video ready / photos in → description ready → scheduled.
Post k of a (set, product) is video k of that product's Ad Camera project (its takes, in order).
Descriptions follow @sully.finds: the wearer's height + the size they're wearing + a few hashtags."""
import re
import shutil
import threading
from datetime import date
from pathlib import Path

from . import planner, render, shop, store

PHOTO_EXT = {".jpg", ".jpeg", ".png", ".heic", ".webp"}
JOB = {"running": False, "msg": "", "day": None, "done": 0, "total": 0, "error": None}
TAGS = [("hoodie", "#hoodie #ziphoodie"), ("henley", "#henley"), ("sweater", "#sweater #knitsweater"), ("sweatpants", "#sweatpants"),
        ("jeans", "#jeans"), ("carpenter", "#carpenterjeans"), ("waffle", "#waffleknit"), ("crew", "#crewneck"), ("baggy", "#baggyjeans"),
        ("loose", "#loosefit"), ("muslin", "#buttonup"), ("shirt", "#shirt"), ("tee", "#tee")]


def _safe(t, n=60):
    t = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', " ", t or "")
    return re.sub(r"\s+", " ", t).strip(" .")[:n].rstrip(" .")


def kit_dir(day: str) -> Path:
    return store.OUTPUT_DIR / f"{day} posts"


def hashtags(p: dict) -> str:
    name = f"{p.get('name', '')} {(p.get('fills') or {}).get('style', '')}".lower()
    brand = re.sub(r"[^a-z0-9]", "", (p.get("brand") or "").lower().replace("&", "and"))
    brand = {"handm": "hm"}.get(brand, brand)
    tags = [f"#{brand}"] if brand else []
    for word, tag in TAGS:
        if word in name:
            tags += [t for t in tag.split() if t not in tags]
    return " ".join((tags + ["#tiktokshop", "#tiktokmademebuyit"])[:6])


def description(post: dict, chan: dict, p: dict) -> str:
    size = (p.get("fills") or {}).get("size") or ""
    who = "I'm" if chan.get("pov", "me") == "me" else "He's"
    height = chan.get("height") or ""
    worn = post.get("format") in planner.WORN  # only say "wearing" when it's being worn on camera
    line = f"{who} {height} wearing size {size}🤝" if height and size and worn else ""
    return " ".join(x for x in (line, hashtags(p)) if x)


def posts(day: str) -> list:
    """The day's posts in posting order, each tied to its project, video number and folder."""
    plan = planner.get(day)
    sh = shop.load()
    st = planner.load()["settings"]
    chans = {c.get("account"): c for c in planner._channels(st, sh)}
    seen, out = {}, []
    root = kit_dir(day)
    for k, x in enumerate(plan["posts"]):
        s = next((y for y in plan["sets"] if y["id"] == x["set"]), None)
        proj = next((pr for pr in (s or {}).get("projects") or [] if pr["product"] == x["product"]), None)
        nth = seen[(x["set"], x["product"])] = seen.get((x["set"], x["product"]), 0) + 1
        p = shop.by_id(sh, "products", x["product"]) or {}
        carousel = x["format"] == "carousel"
        label = (s or {}).get("label") or x["format"]
        folder = root / _safe(f"{k + 1:02d} {x['time'].replace(':', '.')} {label} - {x['name']}", 90)
        item = {"k": k, "n": k + 1, "time": x["time"], "format": x["format"], "label": label, "name": x["name"],
                "product": x["product"], "link": p.get("link") or "", "set": x["set"], "sid": proj["sid"] if proj else None,
                "video": nth, "carousel": carousel, "folder": str(folder), "scheduled": bool(x.get("done")),
                "description": description(x, chans.get(x["channel"], {}), p)}
        item.update(_state(item))
        out.append(item)
    return out


def _state(item) -> dict:
    """Where this post is: footage, video / photos, description."""
    f = Path(item["folder"])
    photos = sorted(q.name for q in f.glob("*") if q.suffix.lower() in PHOTO_EXT) if f.is_dir() else []
    st = {"photos": photos, "video_file": (f / "video.mp4").is_file(), "desc_file": (f / "description.txt").is_file(),
          "takes": 0, "stage": "film", "videos": 0}
    if item["sid"]:
        try:
            s = store.load(item["sid"])
            st["takes"] = len(s["sources"])
            st["stage"] = shop.stage(s)
            st["videos"] = store.videos(s)["count"] if s["sources"] else 0
        except Exception:
            pass
    if item["carousel"]:
        st["step"] = "scheduled" if item["scheduled"] else "ready" if photos else "photos"
    else:
        st["step"] = ("scheduled" if item["scheduled"] else "ready" if st["video_file"]
                      else "render" if st["videos"] >= item["video"] else "precut" if st["takes"] else "film")
    return st


def write_text(item, day: str):
    f = Path(item["folder"])
    f.mkdir(parents=True, exist_ok=True)
    lines = [f"POST {item['n']} · {item['time']} · {item['label']}", f"PRODUCT: {item['name']}",
             f"TIKTOK SHOP LINK: {item['link']}", "", "DESCRIPTION (paste into TikTok):", item["description"], ""]
    if item["carousel"]:
        lines += ["CAROUSEL: the 2-5 photos in this folder, in order (each a different outfit around the item).",
                  "On-image text, one line on the first photo:",
                  f"  {planner.season(date.fromisoformat(day)).capitalize()} essential: {item['name'].split(' - ')[0]}", ""]
    lines += ["Tag the product: Add link → Products → search it, or paste the link above."]
    (f / "description.txt").write_text("\n".join(lines), encoding="utf-8")


def build(day: str):
    """Make every post's folder and description; render and copy the videos whose footage is in."""
    if JOB["running"]:
        return JOB
    JOB.update(running=True, day=day, msg="starting…", done=0, error=None)

    def work():
        try:
            items = posts(day)
            JOB["total"] = len(items)
            for i, it in enumerate(items):
                JOB.update(done=i, msg=f"post {it['n']} of {len(items)}")
                write_text(it, day)
                if not it["carousel"] and it["sid"] and it["videos"] >= it["video"]:
                    out = render.fresh_render(it["sid"], it["video"], lambda m: JOB.update(msg=f"post {it['n']}: {m}"))
                    shutil.copy2(out, Path(it["folder"]) / "video.mp4")
            JOB.update(done=len(items), msg="posting kit ready")
        except Exception as e:
            JOB.update(error=str(e), msg=f"stopped: {e}")
        finally:
            JOB["running"] = False
    threading.Thread(target=work, daemon=True, name="postkit").start()
    return JOB


def busy() -> list:
    return ["posting kit"] if JOB["running"] else []


def add_photo(day: str, k: int, name: str, data: bytes) -> str:
    it = posts(day)[k]
    f = Path(it["folder"])
    f.mkdir(parents=True, exist_ok=True)
    ext = Path(name).suffix.lower() if Path(name).suffix.lower() in PHOTO_EXT else ".jpg"
    n = len([q for q in f.glob("photo-*")]) + 1
    dest = f / f"photo-{n}{ext}"
    dest.write_bytes(data)
    if not (f / "description.txt").exists():
        write_text(it, day)
    return dest.name


def file_path(day: str, k: int, name: str) -> Path:
    f = Path(posts(day)[k]["folder"]) / Path(name).name
    if not f.is_file():
        raise FileNotFoundError(name)
    return f
