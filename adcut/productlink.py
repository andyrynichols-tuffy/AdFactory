"""Product details from a link (Products → ＋ Product → "Fill in from a link").

- a TikTok Shop product page (shop.tiktok.com/…/pdp/…, tiktok.com/view/product/<id>, short links):
  title, price, category, shop (brand), specs (as script fill-ins), description, picture;
- a TikTok video: the product(s) tagged in it (its "anchors"), each read from its product page;
- any other shop page: the standard tags (Open Graph, schema.org Product).
Public pages only, read the way the Analytics reader does (no login)."""
import html as htmlmod
import json
import re

from supercut import analytics

VIDEO_ID_RX = re.compile(r"/video/(\d{8,})")  # short links can land on tiktok.com/@/video/<id>
PRODUCT_RX = re.compile(r"(?:/pdp/(?:[^/?#]+/)?|/view/product/|product_id=)(\d{12,})")
MAX_FILLS = 8


def _meta(page: str) -> dict:
    out = {}
    for m in re.finditer(r'<meta[^>]+(?:property|name)="([^"]+)"[^>]+content="([^"]*)"', page):
        out.setdefault(m.group(1).lower(), htmlmod.unescape(m.group(2)))
    return out


def _json_str(s: str) -> str:
    try:
        return json.loads(f'"{s}"')
    except ValueError:
        return s


def _array(page: str, key: str):
    """The JSON array right after "key": in the page's data."""
    i = page.find(f'"{key}":[')
    if i < 0:
        return None
    try:
        return json.JSONDecoder().raw_decode(page, i + len(key) + 3)[0]
    except ValueError:
        return None


def _title_case(s: str) -> str:
    return s if any(c.isupper() for c in s) else s.title()


def tiktok_product(url: str) -> dict:
    final, page = analytics._get(url)
    meta = _meta(page)
    pid = (PRODUCT_RX.search(final) or PRODUCT_RX.search(url))
    pid = pid.group(1) if pid else ""
    m = re.search(r'"product_id":"%s"[^{}]{0,300}?"title":"((?:[^"\\]|\\.)*)"' % re.escape(pid), page) if pid else None
    title = _json_str(m.group(1)) if m else re.sub(r"\s*-\s*TikTok Shop$", "", meta.get("og:title", ""))
    if not title:
        raise ValueError("That page doesn't look like a TikTok Shop product")
    price = re.search(r'"real_price":"((?:[^"\\]|\\.)*)"', page)
    shop_name = re.search(r'"shop_name":"((?:[^"\\]|\\.)*)"', page)
    cats = _array(page, "categories") or []
    specs = _array(page, "specifications") or []
    brand = next((s.get("value", "") for s in specs if str(s.get("name", "")).lower() == "brand"), "")
    shop = _json_str(shop_name.group(1)) if shop_name else ""
    if shop and (not brand or brand.lower() == shop.lower()):
        brand = shop  # the shop's own spelling ("Old Navy", not "old navy")
    fills = {}
    for s in specs:
        k, v = str(s.get("name", "")).strip().lower(), str(s.get("value", "")).strip()
        if k and v and k != "brand" and len(fills) < MAX_FILLS:
            fills[k] = v
    link = (meta.get("og:url") or final).split("?")[0]
    return {"name": title, "brand": _title_case(brand) if brand else "", "category": cats[-1].get("category_name", "") if cats else "",
            "price": _json_str(price.group(1)) if price else "", "link": link, "image": meta.get("og:image", ""),
            "notes": meta.get("og:description") or meta.get("description") or "", "fills": fills, "product_id": pid}


def other_product(url: str) -> dict:
    """Any shop page: schema.org Product (JSON-LD) or Open Graph tags."""
    final, page = analytics._get(url)
    meta = _meta(page)
    out = {"name": "", "brand": "", "category": "", "price": "", "link": final, "image": meta.get("og:image", ""),
           "notes": meta.get("og:description") or meta.get("description") or "", "fills": {}}
    for m in re.finditer(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', page, re.S):
        try:
            data = json.loads(m.group(1))
        except ValueError:
            continue
        for d in data if isinstance(data, list) else data.get("@graph", [data]):
            if isinstance(d, dict) and "Product" in str(d.get("@type")):
                b = d.get("brand")
                offers = d.get("offers") or {}
                offers = offers[0] if isinstance(offers, list) and offers else offers
                img = d.get("image")
                out.update(name=d.get("name") or "", brand=(b.get("name") if isinstance(b, dict) else b) or "",
                           category=d.get("category") or "", notes=d.get("description") or out["notes"],
                           price=f"${offers.get('price')}" if isinstance(offers, dict) and offers.get("price") else "",
                           image=(img[0] if isinstance(img, list) and img else img) or out["image"])
                break
    out["name"] = out["name"] or meta.get("og:title", "")
    if not out["name"]:
        raise ValueError("Couldn't find a product on that page")
    return out


def video_products(url: str) -> list:
    """The products tagged in a TikTok video: [{product_id, title, url}]."""
    final, page = analytics._get(url)
    item = analytics._scope(page).get("webapp.video-detail", {}).get("itemInfo", {}).get("itemStruct", {})
    if not item:
        raise ValueError("That link doesn't look like a public TikTok video")
    found = []
    for a in item.get("anchors") or []:
        try:
            extra = json.loads(a.get("extra") or "[]")
        except ValueError:
            continue
        for x in extra if isinstance(extra, list) else [extra]:
            if not isinstance(x, dict) or x.get("type") != 33:
                continue
            try:
                info = json.loads(x.get("extra") or "{}")
            except ValueError:
                info = {}
            pid = str(info.get("product_id") or x.get("id") or "")
            if pid and pid not in {f["product_id"] for f in found}:
                found.append({"product_id": pid, "title": info.get("title") or x.get("keyword") or "",
                              "url": f"https://www.tiktok.com/view/product/{pid}", "image": info.get("cover_url") or ""})
    return found


def from_link(url: str) -> dict:
    """{"products": [...], "from_video": bool}"""
    url = url.strip()
    if not re.match(r"https?://", url):
        raise ValueError("Paste a full link (https://…)")
    if "tiktok.com" in url and (VIDEO_ID_RX.search(url) or re.search(r"//(vm|vt)\.tiktok\.com/|tiktok\.com/t/", url)):
        final, _ = analytics._get(url)  # short links: see where they go
        if VIDEO_ID_RX.search(final):
            tagged = video_products(final)
            if not tagged:
                raise ValueError("No product is tagged in that video")
            out = []
            for t in tagged[:4]:
                try:
                    out.append(tiktok_product(t["url"]))
                except Exception:
                    out.append({"name": t["title"], "brand": "", "category": "", "price": "", "link": t["url"],
                                "image": t["image"], "notes": "", "fills": {}, "product_id": t["product_id"]})
            return {"products": out, "from_video": True}
        url = final
    if "tiktok.com" in url and PRODUCT_RX.search(url):
        return {"products": [tiktok_product(url)], "from_video": False}
    return {"products": [other_product(url)], "from_video": False}
