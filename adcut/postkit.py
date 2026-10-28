"""Posting kit for a planned shoot day (user, 2026-10-27): once the takes are in, do as much of the posting work as
possible, and keep each batch together so nothing gets lost. Every post the day's batch fills gets its own folder,

    <Outbox>/<shoot day> batch/<date> <HH.MM> <format> - <product>/
        video.mp4          the finished video (rendered with its captions), for video posts
        1-c2.jpg, 2-o1.jpg… a carousel's photos in order, copied from the product's photo pool
        description.txt    what to paste into TikTok: the description, the product to tag and its link

Carousels: each product has one photo pool per batch, `_pool/<product>/` (c1-c3 = cover poses: folded left,
folded right, laid flat; o1…oN = the session's outfits), filled by Ad Camera's carousel mode (or photos dropped on
the Mac). The planner remixes each pool into several carousels over the week (planner.carousel_combo), each with a
fresh cover and its own text. Progress per post: film → footage in → ready → scheduled. Post k of a (set, product)
is video k of that product's Ad Camera project. Descriptions follow @sully.finds: height + size + a few hashtags."""
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
SLOT_RX = re.compile(r"^(c\d|o\d+)\.")


def _safe(t, n=60):
    t = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', " ", t or "")
    return re.sub(r"\s+", " ", t).strip(" .")[:n].rstrip(" .")


def kit_dir(day: str) -> Path:
    mode = (planner.load()["days"].get(day) or {}).get("mode", "daily")
    return store.OUTPUT_DIR / (f"{day} batch" if mode == "batch" else f"{day} posts")


def pool_dir(day: str, product_name: str) -> Path:
    return kit_dir(day) / "_pool" / _safe(product_name, 70)


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


def pool_photos(day: str, product_name: str) -> dict:
    """{slot: file name} of a product's photo pool (c1.jpg, o2.jpg…)."""
    f = pool_dir(day, product_name)
    out = {}
    if f.is_dir():
        for q in f.iterdir():
            m = SLOT_RX.match(q.name)
            if m and q.suffix.lower() in PHOTO_EXT:
                out[m.group(1)] = q.name
    return out


def posts(day: str) -> list:
    """The day's posts (for a batch: the coming week's, dated) in posting order, each tied to its project, video
    number or carousel photos, and folder."""
    from . import carouselplan
    plan = planner.get(day)
    sh = shop.load()
    st = planner.load()["settings"]
    chans = {c.get("account"): c for c in planner._channels(st, sh)}
    seen, out, root = {}, [], kit_dir(day)
    pools = {}
    for k, x in enumerate(plan["posts"]):
        s = next((y for y in plan["sets"] if y["id"] == x["set"]), None)
        unit = x.get("unit", x["product"])
        proj = next((pr for pr in (s or {}).get("projects") or []
                     if pr.get("unit", pr["product"]) == unit and pr.get("variant", 0) == x.get("variant", 0)), None)
        nth = seen[(x["set"], unit, x.get("variant", 0))] = seen.get((x["set"], unit, x.get("variant", 0)), 0) + 1
        p = shop.by_id(sh, "products", x["product"]) or {}
        carousel = x["format"] == "carousel"
        label = (s or {}).get("label") or x["format"]
        when = x.get("date") or day
        folder = root / _safe(f"{when} {x['time'].replace(':', '.')} {label} - {x['name']}", 110)
        item = {"k": k, "n": k + 1, "date": when, "variant": x.get("variant", 0), "time": x["time"], "format": x["format"], "label": label, "name": x["name"],
                "product": x["product"], "link": p.get("link") or "", "set": x["set"], "sid": proj["sid"] if proj else None,
                "video": x.get("take") or nth, "carousel": carousel, "folder": str(folder), "scheduled": bool(x.get("done")),
                "description": description(x, chans.get(x["channel"], {}), p)}
        if carousel:
            if x["product"] not in pools:
                pools[x["product"]] = pool_photos(day, x["name"])
            combo = x.get("photos") or ["c1", "o1", "o2", "o3"]
            texts = (s or {}).get("texts") or {}
            key = f"{x['product']}#{item['video']}"
            item.update(combo=combo, pool=pools[x["product"]], text_key=key,
                        text=texts.get(key) or carouselplan.default_text(p, k, day))
        item.update(_state(item))
        out.append(item)
    return out


def _state(item) -> dict:
    """Where this post is: footage, video / photos, description."""
    f = Path(item["folder"])
    st = {"video_file": (f / "video.mp4").is_file(), "desc_file": (f / "description.txt").is_file(), "takes": 0, "stage": "film", "videos": 0}
    if item["carousel"]:
        have = [c for c in item["combo"] if c in item["pool"]]
        st["photos"] = [item["pool"][c] for c in have]
        st["step"] = "scheduled" if item["scheduled"] else "ready" if len(have) == len(item["combo"]) else "photos"
        return st
    st["photos"] = []
    if item["sid"]:
        try:
            s = store.load(item["sid"])
            st["takes"] = len(s["sources"])
            st["stage"] = shop.stage(s)
            st["videos"] = store.videos(s)["count"] if s["sources"] else 0
        except Exception:
            pass
    st["step"] = ("scheduled" if item["scheduled"] else "ready" if st["video_file"]
                  else "render" if st["videos"] >= item["video"] else "precut" if st["takes"] else "film")
    return st


def write_text(item, day: str):
    f = Path(item["folder"])
    f.mkdir(parents=True, exist_ok=True)
    when = date.fromisoformat(item["date"]).strftime("%a %b %d").replace(" 0", " ")
    lines = [f"POST {item['n']} · {when} {item['time']} · {item['label']}", f"PRODUCT: {item['name']}",
             f"TIKTOK SHOP LINK: {item['link']}", "", "DESCRIPTION (paste into TikTok):", item["description"], ""]
    if item["carousel"]:
        lines += [f"CAROUSEL: the {len(item['combo'])} photos in this folder, in order (photo 1 is the cover).",
                  "On-image text, one line on the cover:", f"  {item['text']}", ""]
    lines += ["Tag the product: Add link → Products → search it, or paste the link above.",
              "Schedule it in TikTok Studio for the date and time above."]
    (f / "description.txt").write_text("\n".join(lines), encoding="utf-8")


def _copy_carousel(item, day):
    """The carousel's photos from its product's pool into its folder, numbered in order."""
    f = Path(item["folder"])
    for q in f.glob("*"):
        if q.suffix.lower() in PHOTO_EXT:
            q.unlink()
    pool = pool_dir(day, item["name"])
    for i, slot in enumerate(item["combo"], 1):
        name = item["pool"].get(slot)
        if name:
            shutil.copy2(pool / name, f / f"{i}-{name}")


def build(day: str):
    """Make every post's folder and description; carousels get their photos from the pools; videos whose
    footage is in get rendered and copied."""
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
                if it["carousel"]:
                    _copy_carousel(it, day)
                elif it["sid"] and it["videos"] >= it["video"]:
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


def _next_free_slot(day: str, it: dict) -> str:
    """Where a photo dropped on a carousel goes: the first of its combo's photos missing from the pool."""
    for slot in it["combo"]:
        if slot not in it["pool"]:
            return slot
    n = max([int(c[1:]) for c in it["pool"] if c.startswith("o")] + [0]) + 1
    return f"o{n}"


def save_slot(day: str, product_name: str, slot: str, name: str, data: bytes) -> str:
    f = pool_dir(day, product_name)
    f.mkdir(parents=True, exist_ok=True)
    for old in f.glob(f"{slot}.*"):
        old.unlink()
    ext = Path(name).suffix.lower() if Path(name).suffix.lower() in PHOTO_EXT else ".jpg"
    (f / f"{slot}{ext}").write_bytes(data)
    return f"{slot}{ext}"


def add_photo(day: str, k: int, name: str, data: bytes) -> str:
    """A photo dropped on a post on the Mac (videos: into its folder; carousels: into its pool, first missing photo)."""
    it = posts(day)[k]
    if it["carousel"]:
        return save_slot(day, it["name"], _next_free_slot(day, it), name, data)
    f = Path(it["folder"])
    f.mkdir(parents=True, exist_ok=True)
    ext = Path(name).suffix.lower() if Path(name).suffix.lower() in PHOTO_EXT else ".jpg"
    dest = f / f"photo-{len(list(f.glob('photo-*'))) + 1}{ext}"
    dest.write_bytes(data)
    return dest.name


def file_path(day: str, k: int, name: str) -> Path:
    it = posts(day)[k]
    for base in (Path(it["folder"]), pool_dir(day, it["name"])):
        f = base / Path(name).name
        if f.is_file():
            return f
    raise FileNotFoundError(name)


def _pool_of(sid: str):
    ix = planner.project_index().get(sid)
    if not ix or ix["format"] != "carousel":
        return None, None
    name = (shop.by_id(shop.load(), "products", ix["product"]) or {}).get("name", "")
    return ix["day"], name


def outfits_for(sid: str) -> list:
    """Which photo slots of this carousel project's pool are already in (Ad Camera shows them done)."""
    day, name = _pool_of(sid)
    return sorted(pool_photos(day, name)) if day else []


def add_outfit_photo(sid: str, slot, name: str, data: bytes) -> dict:
    """Ad Camera's carousel mode: one photo of the product's pool (c1-c3 = cover poses, o1… = outfits; an old
    numeric outfit: 0 = the first cover, N = outfit N). A retake replaces it."""
    day, pname = _pool_of(sid)
    if not day:
        raise LookupError("not a planned carousel project")
    if isinstance(slot, int) or str(slot).isdigit():
        slot = "c1" if int(slot) == 0 else f"o{int(slot)}"
    saved = save_slot(day, pname, str(slot), name, data)
    return {"saved": saved, "outfits": outfits_for(sid)}
