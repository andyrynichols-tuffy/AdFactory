"""Where things may go on a 9:16 TikTok frame.

TikTok draws its own UI over the video: tabs at the top, the like/comment/share rail
on the right, the caption/username/sound block at the bottom and, on TikTok Shop
videos, the orange-cart product tag just above the username. Our text stays out of
all of that, and off the product (style.product_box, marked by the user).
All boxes are [x0, y0, x1, y1] fractions of the frame. Mirrored in adeditor/app.js."""

UI_ZONES = {
    "top tabs": [0.0, 0.0, 1.0, 0.075],
    "like / comment / share": [0.835, 0.40, 1.0, 0.87],
    "caption + username": [0.0, 0.80, 0.835, 1.0],
    "orange cart tag": [0.03, 0.745, 0.62, 0.795],
}
SAFE = [0.04, 0.085, 0.82, 0.735]  # what's left: text lives in here
CART_TAG = UI_ZONES["orange cart tag"]


def overlap(a, b) -> float:
    """Overlap area of two boxes as a fraction of a's area."""
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    if w <= 0 or h <= 0:
        return 0.0
    return w * h / max(1e-6, (a[2] - a[0]) * (a[3] - a[1]))


def place_band(y_pref: float, band_h: float, product=None, x0=None, x1=None) -> float:
    """Centre y for a horizontal text band of height band_h (fraction of frame height):
    as close to y_pref as possible, inside the safe area, and off the product box.
    Falls back to whichever spot covers the product least."""
    x0 = SAFE[0] if x0 is None else x0
    x1 = SAFE[2] if x1 is None else x1
    lo, hi = SAFE[1] + band_h / 2, SAFE[3] - band_h / 2
    clamp = lambda y: min(hi, max(lo, y))
    y = clamp(y_pref)
    if not product:
        return y
    band = lambda yc: [x0, yc - band_h / 2, x1, yc + band_h / 2]
    if overlap(band(y), product) == 0:
        return y
    gap = 0.012
    cands = [clamp(product[3] + gap + band_h / 2), clamp(product[1] - gap - band_h / 2), y]
    return min(cands, key=lambda c: (round(overlap(band(c), product), 3), abs(c - y_pref)))


def product_for(style: dict, line: dict = None):
    """The product area for a line: its own (the product moves around) or the shoot's."""
    return (line or {}).get("product_box") or style.get("product_box")


def subs_y(style: dict, line: dict = None) -> float:
    sub = style["subs"]
    band = sub["size"] * 1.35 / 1920
    return place_band(sub["y"], band, product_for(style, line))


def hook_y(style: dict, lines: int = 2, line: dict = None) -> float:
    hk = style["hook"]
    band = (hk["size"] * 1.25 * lines + 40) / 1920
    return place_band(hk["y"], band, product_for(style, line), 0.06, 0.82)
