"""Effects board: visual effects dropped onto a take at a moment (take["fx"]), plus the
automatic "orange cart" pointer (style.cart_pointer, which uses one of these kinds).
Most point at the spot where TikTok shows the TikTok Shop product tag.

Each kind renders RGBA frames at 30fps and says where they go and whether the last
frame holds (so a 3s spotlight is a 5-frame fade-in held, not 90 frames)."""
import math
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from supercut.fonts import EMOJI_FONT

from . import pointer, store
from .layout import CART_TAG

W, H, FPS = 1080, 1920, 30
SY0, SY1 = pointer.Y0, pointer.Y1  # strip around the tag

CATALOG = [
    # kind, label, emoji, group, default seconds
    ("arrow", "Bouncing arrow", "⬇️", "Point at the TikTok Shop tag", 2.2),
    ("ring", "Pulse ring", "⭕", "Point at the TikTok Shop tag", 2.2),
    ("tap", "Tapping finger", "👇", "Point at the TikTok Shop tag", 2.2),
    ("spotlight", "Spotlight", "🔦", "Point at the TikTok Shop tag", 2.2),
    ("shine", "Shine sweep", "💫", "Point at the TikTok Shop tag", 2.0),
    ("scribble", "Circle it", "✍️", "Point at the TikTok Shop tag", 2.2),
    ("flash", "Flash", "⚡", "Moments", 0.35),
]
KINDS = {c[0]: c for c in CATALOG}


def catalog() -> list:
    return [{"kind": k, "label": lab, "emoji": e, "group": g, "dur": d} for k, lab, e, g, d in CATALOG]


def _hex(h, a=255):
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), a)


def _tag_box(pad=14):
    """The product tag, in strip coordinates."""
    return (CART_TAG[0] * W - pad, CART_TAG[1] * H - pad + 2 - SY0, CART_TAG[2] * W + pad, CART_TAG[3] * H + pad - SY0)


def _strip():
    return Image.new("RGBA", (W, SY1 - SY0), (0, 0, 0, 0))


def _ring(img, box, col, t, intro, width=6):
    glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    g = ImageDraw.Draw(glow)
    grow = 6 * (0.5 + 0.5 * math.sin(t * 2 * math.pi * 1.6))
    x0, y0, x1, y1 = box
    rr = [x0 - grow, y0 - grow, x1 + grow, y1 + grow]
    g.rounded_rectangle(rr, radius=30, outline=_hex(col, int(230 * intro)), width=14)
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(10)))
    ImageDraw.Draw(img).rounded_rectangle(rr, radius=30, outline=(255, 255, 255, int(255 * intro)), width=width)


@lru_cache(maxsize=4)
def _finger(size: int):
    f = ImageFont.truetype(str(EMOJI_FONT), 109)
    im = Image.new("RGBA", (140, 140), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((10, 0), "👇", font=f, embedded_color=True)
    im = im.crop(im.getbbox())
    return im.resize((size, int(size * im.height / im.width)), Image.LANCZOS)


def frames(kind: str, seconds: float, color: str = "#FF8A00"):
    """-> (frames, x, y, hold_last)"""
    n = max(1, int(seconds * FPS))
    box = _tag_box()
    x0, y0, x1, y1 = box
    if kind == "arrow":
        return pointer.frames({"cart_pointer": {"color": color}}, seconds), 0, SY0, False
    if kind == "ring":
        out = []
        for f in range(n):
            t = f / FPS
            img = _strip()
            _ring(img, box, color, t, min(1.0, t / 0.18))
            out.append(img)
        return out, 0, SY0, False
    if kind == "tap":
        out, fin = [], _finger(150)
        tipx, tipy = x0 + 130, (y0 + y1) / 2
        for f in range(n):
            t = f / FPS
            img = _strip()
            _ring(img, box, color, t, min(1.0, t / 0.18), 4)
            ph = (t % 0.6) / 0.6  # one tap every 0.6s
            press = math.sin(min(1, ph / 0.35) * math.pi) if ph < 0.35 else 0
            d = ImageDraw.Draw(img)
            if ph < 0.6:  # ripple from the tap
                r = 10 + 70 * ph
                d.ellipse([tipx - r, tipy - r, tipx + r, tipy + r], outline=(255, 255, 255, int(220 * (1 - ph))), width=5)
            # finger tip (bottom of the 👇) presses down onto the tag, then lifts
            img.alpha_composite(fin, (int(tipx - fin.width * 0.42), int(tipy - fin.height + 6 - 34 * (1 - press))))
            out.append(img)
        return out, 0, SY0, False
    if kind == "spotlight":
        hole = (x0, y0 + SY0, x1, y1 + SY0)
        mask = Image.new("L", (W, H), 0)
        ImageDraw.Draw(mask).rounded_rectangle(hole, radius=34, fill=255)
        mask = mask.filter(ImageFilter.GaussianBlur(14))
        base = Image.new("RGBA", (W, H), (0, 0, 0, 170))
        base.putalpha(Image.eval(mask, lambda v: int(170 * (1 - v / 255))))
        ImageDraw.Draw(base).rounded_rectangle(hole, radius=34, outline=(255, 255, 255, 230), width=5)
        out = []
        for a in (0.2, 0.45, 0.7, 0.9, 1.0):
            fr = base.copy()
            fr.putalpha(fr.getchannel("A").point(lambda v, a=a: int(v * a)))
            out.append(fr)
        return out, 0, 0, True
    if kind == "shine":
        out = []
        bw, bh = int(x1 - x0), int(y1 - y0)
        clip = Image.new("L", (bw, bh), 0)
        ImageDraw.Draw(clip).rounded_rectangle([0, 0, bw - 1, bh - 1], radius=28, fill=255)
        for f in range(n):
            t = f / FPS
            img = _strip()
            d = ImageDraw.Draw(img)
            d.rounded_rectangle(box, radius=28, outline=_hex(color, 255), width=6)
            ph = (t % 0.9) / 0.9
            band = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
            cx = -120 + ph * (bw + 240)
            bd = ImageDraw.Draw(band)
            bd.polygon([(cx - 40, bh), (cx + 10, 0), (cx + 70, 0), (cx + 20, bh)], fill=(255, 255, 255, 170))
            band = band.filter(ImageFilter.GaussianBlur(6))
            band.putalpha(Image.composite(band.getchannel("A"), Image.new("L", band.size, 0), clip))
            img.alpha_composite(band, (int(x0), int(y0)))
            out.append(img)
        return out, 0, SY0, False
    if kind == "scribble":
        out = []
        cx, cy, rx, ry = (x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 2 + 26, (y1 - y0) / 2 + 22
        rx = min(rx, cx - 12)  # keep the stroke on screen
        pts = []
        for i in range(121):  # a bit more than a full turn, wobbly like a marker
            a = -math.pi * 0.9 + i / 120 * 2 * math.pi * 1.08
            w = 1 + 0.035 * math.sin(2 * a + 0.6) + 0.02 * math.sin(3 * a + 2.1) + 0.012 * (i / 120)
            pts.append((cx + rx * w * math.cos(a), cy + ry * w * math.sin(a)))
        steps = 14  # drawn in over ~0.45s, then held
        for f in range(steps + 1):
            img = _strip()
            k = max(2, int(len(pts) * f / steps))
            ImageDraw.Draw(img).line(pts[:k], fill=_hex("#FFE14D"), width=11, joint="curve")
            out.append(img)
        return out, 0, SY0, True
    if kind == "flash":
        out = []
        for f in range(max(2, n)):
            a = max(0.0, 1 - f / max(1, n - 1))
            out.append(Image.new("RGBA", (W, H), (255, 255, 255, int(210 * a ** 1.5))))
        return out, 0, 0, False
    raise KeyError(kind)


def events(s: dict, parts: list, total: float) -> list:
    """[(t0, t1, kind)] in video time: effects placed on takes + the automatic
    orange-cart pointer (style.cart_pointer.kind)."""
    out = []
    for tk, t0 in parts:
        end = tk.get("_src_out", tk["out"])
        for e in tk.get("fx") or []:
            at = float(e["at"])
            if e.get("kind") not in KINDS or not (tk["in"] <= at < end) or store.in_cut(tk, at):
                continue
            a = t0 + store.take_rel(tk, at)
            out.append((a, min(total, a + float(e.get("dur") or KINDS[e["kind"]][4])), e["kind"]))
    cp = s["style"].get("cart_pointer") or {}
    kind = cp.get("kind") or "arrow"
    for a, b in pointer.timings(s, parts, total):
        out.append((a, b, kind if kind in KINDS else "arrow"))
    # darkening layers first, so pointers drawn after them stay bright
    return sorted(out, key=lambda e: (e[2] not in ("spotlight", "flash"), e[0]))
