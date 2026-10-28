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
NOT_FILLS = {"manufacturer", "region of origin", "country of origin", "place of origin", "warranty", "warranty type",
             "warranty duration", "model", "model number", "certification", "certifications", "net weight", "quantity",
             "quantity per pack", "item weight", "gtin", "upc", "ean", "sku", "california prop 65"}


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
        if (k and v and k != "brand" and k not in NOT_FILLS and not re.search(r"dangerous|hazard|battery|prop 65|compliance", k)
                and v.lower() not in ("none", "no", "n/a", "na", "other") and len(fills) < MAX_FILLS):
            fills[k] = v
    link = (meta.get("og:url") or final).split("?")[0]
    sold = re.search(r'"sold_count":"?(\d+)', page)  # items sold since listing, all sellers' creators together
    low = re.search(r'"min_sku_price":"([\d.]+)"', page)
    return {"name": title, "brand": _title_case(brand) if brand else "", "category": cats[-1].get("category_name", "") if cats else "",
            "price": _json_str(price.group(1)) if price else "", "link": link, "image": meta.get("og:image", ""),
            "notes": meta.get("og:description") or meta.get("description") or "", "fills": fills, "product_id": pid,
            "sold": int(sold.group(1)) if sold else None, "min_price": float(low.group(1)) if low else None}


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


def short_name(title: str) -> str:
    """TikTok Shop titles are search-stuffed ("Men's Eyebrow & Beard Filler Pen - Coconut & Castor Oil
    Infused, …"): keep the part before the first " - ", "|", "," or "(", at most 8 words."""
    s = re.split(r"\s[-–|]\s|[,(|]", title or "", maxsplit=1)[0].strip()
    return " ".join(s.split()[:8]) or (title or "")[:60]


def is_shop_link(link: str) -> bool:
    """A TikTok Shop product link (what a product needs to be tagged in a video)."""
    return bool(link) and "tiktok.com" in link and bool(PRODUCT_RX.search(link))


def product_id_of(link: str) -> str:
    m = PRODUCT_RX.search(link or "")
    return m.group(1) if m else ""


def match(found: dict, products: list):
    """The product already in the app that this is (same TikTok product id, else same name)."""
    pid = found.get("product_id") or product_id_of(found.get("link"))
    for p in products:
        if pid and product_id_of(p.get("link")) == pid:
            return p["id"]
    names = {found.get("name", "").lower(), found.get("short", "").lower()} - {""}
    return next((p["id"] for p in products if p["name"].lower() in names), None)


def _norm(s) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _words(s) -> set:
    return {w for w in re.findall(r"[a-z0-9]+", (s or "").lower()) if len(w) > 2}


def similar(found: dict, products: list):
    """A product already in the app that's probably this one, by brand ("MenPens" ≈ your "MenPen";
    "Old Navy … Waffle T-Shirt" ≈ your "Old Navy Waffle"). For asking, never for linking on its own."""
    brand = _norm(found.get("brand"))
    if len(brand) < 4:
        return None
    fw = _words(found.get("name")) | _words(found.get("short"))
    best, score = None, 0
    for p in products:
        pn, pb = _norm(p["name"]), _norm(p.get("brand"))
        if not (pn.startswith(brand.rstrip("s")) or (len(pn) >= 4 and brand.startswith(pn)) or pb == brand):
            continue
        extra = len((_words(p["name"]) - _words(found.get("brand"))) & fw)
        sc = 1 + 2 * extra if (extra or pn.rstrip("s") == brand.rstrip("s")) else 0
        if sc > score:
            best, score = p["id"], sc
    return best


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


def lookup(url: str, products: list) -> dict:
    """from_link + a short name for each + which existing product it is."""
    r = from_link(url)
    for f in r["products"]:
        f["short"] = short_name(f["name"])
        f["existing"] = match(f, products)
        f["similar"] = None if f["existing"] else similar(f, products)
    return r
