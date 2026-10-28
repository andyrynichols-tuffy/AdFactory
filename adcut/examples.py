"""The example to copy on a shoot page (Shoot Days → Open Shoot): a TikTok link, read once from its public
page and kept locally (TikTok's signed image links stop working), so the page shows it without TikTok's
embed widget, which doesn't fit a narrow column. Photo posts (carousels) keep every photo; videos keep
the cover, and the page plays them with TikTok's resizable player."""
import json
import re
import urllib.request

from adkit import analytics as an

from . import store

DIR = store.AD_DATA / "examples"
ID_RX = re.compile(r"/(?:video|photo)/(\d+)")


def _save(url: str, dest) -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": an.UA, "Referer": "https://www.tiktok.com/"})
        with urllib.request.urlopen(req, timeout=20) as r:
            data = r.read()
        if len(data) < 500:
            return False
        dest.write_bytes(data)
        return True
    except Exception:
        return False


def get(url: str) -> dict:
    """{id, kind: video|photos, desc, images: [file names]} for a TikTok link, read once and cached."""
    m = ID_RX.search(url or "")
    if not m:
        raise ValueError("not a TikTok video or photo link")
    vid = m.group(1)
    folder = DIR / vid
    meta = folder / "example.json"
    if meta.exists():
        return json.loads(meta.read_text(encoding="utf-8"))
    final, html = an._get(f"https://www.tiktok.com/@_/video/{vid}")  # photo posts read through /video/ too
    item = an._scope(html).get("webapp.video-detail", {}).get("itemInfo", {}).get("itemStruct", {})
    if not item:
        raise ValueError("couldn't read that TikTok")
    folder.mkdir(parents=True, exist_ok=True)
    photos = (item.get("imagePost") or {}).get("images") or []
    images = []
    if photos:
        for i, ph in enumerate(photos[:10], 1):
            urls = (ph.get("imageURL") or {}).get("urlList") or []
            if urls and _save(urls[0], folder / f"{i}.jpg"):
                images.append(f"{i}.jpg")
    else:
        v = item.get("video") or {}
        if _save(v.get("cover") or v.get("originCover") or "", folder / "cover.jpg"):
            images.append("cover.jpg")
    out = {"id": vid, "kind": "photos" if photos else "video", "desc": item.get("desc", ""),
           "author": (item.get("author") or {}).get("uniqueId", ""), "images": images}
    meta.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out


def image(vid: str, name: str):
    f = DIR / re.sub(r"\D", "", vid) / re.sub(r"[^\w.]", "", name)
    if not f.is_file():
        raise FileNotFoundError(name)
    return f
