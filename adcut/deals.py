"""Deal check (user, 2026-10-27: "I'm not going to the effort to look"): twice a day, each product's public TikTok
Shop page is read for a real discount (a crossed-out original price above the sale price) and free shipping. When
there is one, the product's fills get `deal` ("40% off with free shipping") and `store price` (the original), so the
planner's scripts use @sully.finds' sale lines; when it ends they go back to the no-sale lines. Free shipping on its
own (`free shipping` = "1") isn't a deal: it only adds his "with free shipping" where it fits. Only deals this
check set are ever cleared (a deal typed in by hand is left alone). One page at a time, with pauses."""
import re
import threading
import time

from adkit import analytics as an

from . import shop

STATE = {"running": False, "last": 0.0, "msg": "", "found": {}}
EVERY = 12 * 3600
PRICE_RX = re.compile(r'"price":\{([^{}]*"sale_price_decimal"[^{}]*)\}')  # one size option's own price block
NUM = lambda block, keys: [float(m.group(1)) for k in keys for m in re.finditer(r'"%s"\s*:\s*"?\$?([\d]+\.?\d*)' % k, block)]


def read(url: str) -> dict:
    """{sale, original, free_shipping} from a TikTok Shop product page: only the listing's own size options are
    read (the page also shows other products, with their own prices)."""
    _, html = an._get(url)
    blocks = PRICE_RX.findall(html)
    sale = [x for b in blocks for x in NUM(b, ("sale_price_decimal",))]
    orig = [x for b in blocks for x in NUM(b, ("origin_price_decimal", "original_price_decimal", "origin_price_format", "original_price_format", "original_price"))]
    free = '"free_shipping":true' in html.replace(" ", "") and '"label_type":"PRODUCT_FREE_SHIPPING"' in html.replace("\\", "")
    return {"sale": min(sale) if sale else None, "original": max(orig) if orig else None, "free_shipping": free}


def deal_text(info: dict) -> tuple:
    s, o = info.get("sale"), info.get("original")
    parts, store = [], ""
    if s and o and o > s * 1.05:
        pct = round(100 * (1 - s / o))
        parts.append("over half off" if pct >= 50 else f"{pct}% off")
        store = f"${o:.0f}" if o == int(o) else f"${o:.2f}"
    if parts and info.get("free_shipping"):
        parts.append("with free shipping")
    return " ".join(parts), store


def check(pause=(4, 8)):
    """One pass over every product with a TikTok Shop link (the same listing is read once)."""
    import random
    from .productlink import is_shop_link
    STATE.update(running=True, msg="checking deals…")
    try:
        products = [p for p in shop.load()["products"] if not p.get("archived") and is_shop_link(p.get("link"))]
        seen = {}
        for p in products:
            url = p["link"]
            if url not in seen:
                try:
                    seen[url] = read(url)
                except Exception as e:
                    seen[url] = {"error": str(e)}
                time.sleep(random.uniform(*pause))
            info = seen[url]
            if info.get("error"):
                continue
            text, store = deal_text(info)  # a deal = a real discount; free shipping alone isn't one
            f = dict(p.get("fills") or {})
            auto = f.get("deal_auto") == "1"
            if text:
                f.update({"deal": text, "store price": store or f.get("store price", ""), "deal_auto": "1"})
            elif auto:  # the deal this check found has ended
                for k in ("deal", "store price", "deal_auto"):
                    f.pop(k, None)
            if info.get("free_shipping"):
                f["free shipping"] = "1"
            else:
                f.pop("free shipping", None)
            if f != (p.get("fills") or {}):
                shop.upsert("products", {"id": p["id"], "fills": f})
            STATE["found"][p["id"]] = text
        STATE.update(last=time.time(), msg=f"{sum(1 for v in STATE['found'].values() if v)} products on a deal")
    finally:
        STATE["running"] = False


def busy() -> list:
    return ["deal check"] if STATE["running"] else []


def start_background():
    def loop():
        time.sleep(120)
        while True:
            try:
                check()
            except Exception as e:
                STATE["msg"] = f"deal check stopped: {e}"
            time.sleep(EVERY)
    threading.Thread(target=loop, daemon=True, name="deals").start()
