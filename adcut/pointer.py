"""When he says "orange cart" (or "cart", "basket"…), point at the spot where TikTok
shows the product tag: a pulsing ring around it and a bouncing arrow above it.
No words on screen: the line itself is the call to action."""
import math

from PIL import Image, ImageDraw, ImageFilter

from .layout import CART_TAG
from . import store
from .takes import tokens

W, H, FPS = 1080, 1920, 30
# drawn on a strip of the frame around the tag (keeps the PNGs small)
Y0, Y1 = int(0.60 * H), int(0.82 * H)


def _phrases(style: dict) -> list:
    return [tokens(p) for p in style["cart_pointer"]["words"].split(",") if tokens(p)]


def find(take: dict, style: dict):
    """Source time of the first trigger phrase said in this take, else None."""
    flat = []  # (token, word start) for every token of every word
    for w in take["words"]:
        for t in tokens(w[0]):
            flat.append((t, w[1]))
    best = None
    for ph in sorted(_phrases(style), key=len, reverse=True):  # "orange cart" before "cart"
        n = len(ph)
        for i in range(len(flat) - n + 1):
            if [t for t, _ in flat[i:i + n]] == ph:
                if best is None or flat[i][1] < best:
                    best = flat[i][1]
                break
    return best


def timings(s: dict, parts: list, total: float) -> list:
    """[(t0, t1)] in video time, at most one per line."""
    cp = s["style"]["cart_pointer"]
    if not cp.get("on"):
        return []
    out = []
    for tk, t0 in parts:
        at = find(tk, s["style"])
        if at is None:
            continue
        a = t0 + max(0.0, store.take_rel(tk, at))
        out.append((a, min(total, a + float(cp["seconds"]))))
    return out


def _hex(h, a=255):
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), a)


def frames(style: dict, seconds: float) -> list:
    """RGBA frames for the strip [Y0, Y1]: ring pulses, arrow bobs, both pop in."""
    col = style["cart_pointer"].get("color", "#FF8A00")
    x0, y0, x1, y1 = CART_TAG[0] * W - 14, CART_TAG[1] * H - 12 - Y0, CART_TAG[2] * W + 14, CART_TAG[3] * H + 12 - Y0
    ax = x0 + 150  # the arrow points at the cart icon end of the tag (left side)
    out = []
    n = max(1, int(seconds * FPS))
    for f in range(n):
        t = f / FPS
        intro = min(1.0, t / 0.18)
        img = Image.new("RGBA", (W, Y1 - Y0), (0, 0, 0, 0))
        glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
        g = ImageDraw.Draw(glow)
        pulse = 0.5 + 0.5 * math.sin(t * 2 * math.pi * 1.6)
        grow = 6 * pulse
        g.rounded_rectangle([x0 - grow, y0 - grow, x1 + grow, y1 + grow], radius=30, outline=_hex(col, int(230 * intro)), width=12)
        img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(10)))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([x0 - grow, y0 - grow, x1 + grow, y1 + grow], radius=30,
                            outline=(255, 255, 255, int(255 * intro)), width=6)
        # arrow above the tag, bobbing down toward it
        bob = 18 * abs(math.sin(t * 2 * math.pi * 1.4))
        tip = y0 - 18 + bob - (1 - intro) * 40
        s = 1.0
        pts = [(ax, tip), (ax - 52 * s, tip - 62 * s), (ax - 20 * s, tip - 62 * s), (ax - 20 * s, tip - 150 * s),
               (ax + 20 * s, tip - 150 * s), (ax + 20 * s, tip - 62 * s), (ax + 52 * s, tip - 62 * s)]
        sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(sh).polygon([(x + 6, y + 10) for x, y in pts], fill=(0, 0, 0, int(140 * intro)))
        img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(8)), (0, 0))
        d = ImageDraw.Draw(img)
        d.polygon(pts, fill=_hex(col, int(255 * intro)), outline=(255, 255, 255, int(255 * intro)), width=6)
        out.append(img)
    return out
