"""Top-band caption images (Pillow): color emoji, *emphasis* words, style
presets (box / meme / sticker / neon / news), rotation, and a pop-in animation."""
import re
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .fonts import EMOJI_FONT, font_file

W, BAND = 1080, 640
MAX_W = 940
EMOJI_RX = re.compile(
    "([\U0001F000-\U0001FAFF☀-➿⬀-⯿⌀-⏿]"
    "(?:[️‍\U0001F3FB-\U0001F3FF]|[\U0001F000-\U0001FAFF☀-➿])*)"
)

# Defaults applied when a preset is chosen (editor) or when a clip switches preset.
PRESETS = {
    "box":     {"font": "Arial Black", "size": 60, "color": "#000000", "box_color": "#FFFFFF",
                "accent": "#E0218A", "outline_w": 0, "uppercase": False, "rotate": 0},
    "meme":    {"font": "Impact", "size": 74, "color": "#FFFFFF", "outline": "#000000",
                "accent": "#FFE14D", "outline_w": 7, "uppercase": True, "rotate": 0},
    "sticker": {"font": "Arial Black", "size": 58, "color": "#FFFFFF", "box_color": "#FF3D8B",
                "accent": "#FFE14D", "outline_w": 0, "uppercase": False, "rotate": -3},
    "neon":    {"font": "Segoe UI Black", "size": 66, "color": "#FFFFFF", "accent": "#FF4FD8",
                "outline_w": 0, "uppercase": True, "rotate": 0},
    "news":    {"font": "Arial Black", "size": 54, "color": "#111111", "box_color": "#FFFFFF",
                "accent": "#E0102F", "outline_w": 0, "uppercase": False, "rotate": 0, "label": "BREAKING"},
    # understated, for storylined posts (one consistent voice across beats)
    "story":   {"font": "Segoe UI Semibold", "size": 54, "color": "#FFFFFF", "box_color": "#000000",
                "box_opacity": 0.55, "accent": "#FFFFFF", "outline_w": 0, "uppercase": False, "rotate": 0,
                "anim": "fade"},
    "tweet":   {"font": "Segoe UI Regular", "size": 46, "color": "#0F1419", "box_color": "#FFFFFF",
                "accent": "#0F1419", "outline_w": 0, "uppercase": False, "rotate": 0, "anim": "fade",
                "name": "bestie", "handle": "@bestie", "avatar_color": "#FF5FA2"},
    # fan-edit compilations: small white serif over the video (TikTok "Classic" look),
    # a soft dark edge for legibility; layer_y moves the 640px caption layer onto the picture
    "fan":     {"font": "Georgia", "size": 46, "color": "#FFFFFF", "outline": "#000000", "accent": "#FFFFFF",
                "outline_w": 2, "uppercase": False, "rotate": 0, "pop": False, "y": 0.5, "layer_y": 760},
    # countdown list for ranking posts (title + numbered rows that fill in per clip)
    "ranking": {"font": "Arial Black", "size": 50, "color": "#FFFFFF", "outline": "#000000",
                "accent": "#FFE14D", "box_color": "#FFE14D", "outline_w": 5, "uppercase": False,
                "rotate": 0, "anim": "reveal", "label_font": "Arial Black", "top": 120},
}
FADE_CURVE = [0.15, 0.4, 0.65, 0.85, 1.0]  # alpha per frame @30fps
POP_CURVE = [0.55, 0.82, 1.06, 1.12, 1.07, 1.03, 1.0]  # scale per frame @30fps


def effective_style(base: dict, override: dict = None) -> dict:
    """Project caption style + optional per-clip override. Switching preset in an
    override pulls in that preset's defaults first."""
    if not override:
        return base
    st = dict(base)
    if override.get("preset") and override["preset"] != base.get("preset"):
        st.update(PRESETS.get(override["preset"], {}))
    st.update(override)
    return st


def hex_rgba(h: str, a: int = 255):
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), a)


@lru_cache(maxsize=48)
def _font(path: str, size: int):
    return ImageFont.truetype(path, size)


def _runs(text: str):
    out, pos = [], 0
    for m in EMOJI_RX.finditer(text):
        if m.start() > pos:
            out.append((False, text[pos:m.start()]))
        out.append((True, m.group(0)))
        pos = m.end()
    if pos < len(text):
        out.append((False, text[pos:]))
    return out


class _Typesetter:
    def __init__(self, st):
        self.size = int(st["size"])
        self.tfont = _font(str(font_file(st["font"])), self.size)
        self.efont = _font(str(EMOJI_FONT), int(self.size * 0.9)) if EMOJI_FONT.exists() else self.tfont
        self.d = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
        asc, desc = self.tfont.getmetrics()
        self.asc = asc
        self.line_h = int((asc + desc) * 1.12)
        self.space = self.d.textlength(" ", font=self.tfont)

    def width(self, word):
        return sum(self.d.textlength(c, font=self.efont if e else self.tfont) for e, c in _runs(word))

    def words(self, text, upper):
        """[[(word, emphasized)]] per paragraph. *word* or *two words* = emphasis."""
        text = text.upper() if upper else text
        paras = []
        for para in text.split("\n"):
            out, emph = [], False
            for tok in para.split():
                # every '*' toggles emphasis, wherever it sits ("*58 in gay years*)")
                parts, any_emph = tok.split("*"), False
                for j, part in enumerate(parts):
                    if j:
                        emph = not emph
                    if part and emph:
                        any_emph = True
                clean = "".join(parts)
                if clean:
                    out.append((clean, any_emph))
            paras.append(out)
        return paras

    def wrap(self, paras, max_w):
        lines = []
        for words in paras:
            cur, cw = [], 0
            for w in words:
                ww = self.width(w[0])
                add = ww + (self.space if cur else 0)
                if cur and cw + add > max_w:
                    lines.append(cur)
                    cur, cw = [w], ww
                else:
                    cur.append(w)
                    cw += add
            lines.append(cur)
        # avoid a lonely last word (or emoji) when it can be balanced
        if len(lines) >= 2 and len(lines[-1]) == 1 and len(lines[-2]) > 2:
            lines[-1].insert(0, lines[-2].pop())
        return lines

    def line_width(self, line):
        return sum(self.width(w) for w, _ in line) + self.space * max(0, len(line) - 1)

    def draw_line(self, d, x, y, line, fill, emph_fill, stroke=0, stroke_fill=(0, 0, 0, 255)):
        for i, (word, emph) in enumerate(line):
            col = emph_fill if emph else fill
            for is_emoji, chunk in _runs(word):
                if is_emoji:
                    ey = y + (self.asc - self.efont.getmetrics()[0]) * 0.6
                    d.text((x, ey), chunk, font=self.efont, embedded_color=True)
                    x += d.textlength(chunk, font=self.efont)
                else:
                    d.text((x, y), chunk, font=self.tfont, fill=col, stroke_width=stroke, stroke_fill=stroke_fill)
                    x += d.textlength(chunk, font=self.tfont)
            x += self.space


def _shadow(layer, offset=(0, 10), radius=10, alpha=0.55):
    a = layer.getchannel("A").point(lambda v: int(v * alpha))
    sh = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    sh.putalpha(a)
    sh = sh.filter(ImageFilter.GaussianBlur(radius))
    out = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    out.alpha_composite(sh, offset)
    out.alpha_composite(layer)
    return out


def _gradient(w: int, h: int, colors: list) -> Image.Image:
    """Horizontal multi-stop gradient."""
    row = Image.new("RGBA", (w, 1))
    px = row.load()
    n = len(colors) - 1 or 1
    for x in range(w):
        f = x / max(1, w - 1) * n
        i = min(int(f), n - 1) if len(colors) > 1 else 0
        a, b = colors[i], colors[min(i + 1, len(colors) - 1)]
        t = f - i
        px[x, 0] = tuple(int(a[k] + (b[k] - a[k]) * t) for k in range(4))
    return row.resize((w, h))


def _avatar_photo(name, size: int):
    """A profile photo (file in the data dir, e.g. "avatar.png") cut to a circle."""
    if not name:
        return None
    from .config import DATA_DIR
    p = DATA_DIR / name
    if not p.exists():
        return None
    big = size * 4  # supersample for a smooth circle edge
    im = Image.open(p).convert("RGBA").resize((big, big), Image.LANCZOS)
    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, big - 1, big - 1], fill=255)
    im.putalpha(mask)
    return im.resize((size, size), Image.LANCZOS)


def _tweet_card(text: str, st: dict, ts: "_Typesetter", cy: int) -> Image.Image:
    """Generic social-post card: avatar circle, display name, @handle, plain body text.
    Deliberately unbranded (no platform logo or verification mark)."""
    dark = st.get("theme") == "dark"
    card = hex_rgba("#16181C" if dark else st.get("box_color", "#FFFFFF"))
    body_col = hex_rgba("#E7E9EA" if dark else st["color"])
    muted = hex_rgba("#71767B" if dark else "#536471")
    k = float(st.get("card_scale", 1.0))  # shrinks the whole card (margins, avatar, name)
    r = lambda v: int(round(v * k))
    cw = r(W - 140)
    x0, pad, av, rad = (W - cw) // 2, r(40), r(84), r(30)
    x1 = x0 + cw
    lines = ts.wrap(ts.words(text, st.get("uppercase")), x1 - x0 - 2 * pad)
    body_h = ts.line_h * len(lines)
    card_h = pad + av + r(18) + body_h + pad - r(8)
    top = max(8, min(BAND - card_h - 16, cy - card_h // 2))
    layer = Image.new("RGBA", (W, BAND), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    stripe = st.get("stripe")  # optional gradient bar along the card's top edge
    if stripe:
        sh = int(st.get("stripe_h", 9))
        grad = _gradient(x1 - x0, card_h, [hex_rgba(c) for c in stripe])
        mask = Image.new("L", (x1 - x0, card_h), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, x1 - x0 - 1, card_h - 1], radius=rad, fill=255)
        layer.paste(grad, (x0, top), mask)
        d.rounded_rectangle([x0, top + sh, x1, top + card_h], radius=rad, fill=card)
        d.rectangle([x0, top + sh + rad, x1, top + card_h - rad], fill=card)
    else:
        d.rounded_rectangle([x0, top, x1, top + card_h], radius=rad, fill=card)
    # avatar: colored circle with an emoji, or the name's initial
    ax, ay = x0 + pad, top + pad
    name = st.get("name", "bestie") or "bestie"
    photo = _avatar_photo(st.get("avatar_image"), av)
    if not photo:
        d.ellipse([ax, ay, ax + av, ay + av], fill=hex_rgba(st.get("avatar_color", "#FF5FA2")))
    if photo:
        layer.paste(photo, (ax, ay), photo)
    elif st.get("avatar_emoji") and EMOJI_FONT.exists():
        ef = _font(str(EMOJI_FONT), r(46))
        ew = d.textlength(st["avatar_emoji"], font=ef)
        d.text((ax + (av - ew) / 2, ay + r(10)), st["avatar_emoji"], font=ef, embedded_color=True)
    else:
        init_font = _font(str(font_file("Segoe UI")), r(44))
        iw = d.textlength(name[0].upper(), font=init_font)
        d.text((ax + (av - iw) / 2, ay + r(12)), name[0].upper(), font=init_font, fill=(255, 255, 255, 255))
    nf = _font(str(font_file("Segoe UI")), r(38))
    hf = _font(str(font_file("Segoe UI Regular")), r(34))
    d.text((ax + av + r(22), ay + r(2)), name, font=nf, fill=body_col)
    d.text((ax + av + r(22), ay + r(46)), st.get("handle", "@bestie"), font=hf, fill=muted)
    by = ay + av + r(18)
    for i, line in enumerate(lines):
        ts.draw_line(d, x0 + pad, by + i * ts.line_h, line, body_col, hex_rgba(st.get("accent", st["color"])))
    return _shadow(layer, (0, 10), 18, 0.35)


def _fit_font(d, text, name, size, max_w, min_size=22):
    while size > min_size and d.textlength(text, font=_font(str(font_file(name)), size)) > max_w:
        size -= 2
    return _font(str(font_file(name)), size)


def _metal(stops, periods) -> Image.Image:
    """Full-band metallic fill: each region (y0, y1, period) repeats the gradient stops
    vertically, so every text line gets its own highlight-to-shadow sheen."""
    cols = [hex_rgba(c) for c in stops]
    n = len(cols) - 1
    col = Image.new("RGBA", (1, BAND))
    px = col.load()
    for y in range(BAND):
        base, per = next(((a, p) for a, b, p in periods if a <= y < b), (0, BAND))
        f = ((y - base) / per) % 1.0 * n
        i = min(int(f), n - 1)
        a, b, t = cols[i], cols[i + 1], f - int(f)
        px[0, y] = tuple(int(a[k] + (b[k] - a[k]) * t) for k in range(4))
    return col.resize((W, BAND))


def _ranking(text: str, st: dict, reveal_now: bool = True) -> Image.Image:
    """Title plus a numbered list (1 at the top). Entries in `shown` are filled in, `now`
    is highlighted; the rest show just their number. Starts below TikTok's top tabs.
    Show themes can add a backing panel with a metallic border (`panel`) and metallic
    lettering (`metal` = gradient stops) for numbers, *emphasis* and the highlight."""
    items, now, shown = st.get("items") or [], int(st.get("now") or 0), set(st.get("shown") or [])
    if not reveal_now:
        shown.discard(now)
    layer = Image.new("RGBA", (W, BAND), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    metal = st.get("metal")  # e.g. ["#FFF0C2", "#D9AE5B", "#9C7128", "#F3D98E"]
    mask = Image.new("RGBA", (W, BAND), (0, 0, 0, 0))  # what gets the metallic fill
    md = ImageDraw.Draw(mask)
    ON, OFF = (255, 255, 255, 255), (0, 0, 0, 0)
    fill, accent = hex_rgba(st["color"]), hex_rgba(st.get("accent", "#FFE14D"))
    ocol, stroke = hex_rgba(st.get("outline", "#000000")), int(st.get("outline_w", 5))
    top = int(st.get("top", 120))
    # title: up to 2 lines, shrinks to fit
    size = int(st["size"])
    while True:
        ts = _Typesetter({**st, "size": size})
        lines = ts.wrap(ts.words(text, st.get("uppercase")), MAX_W - (60 if st.get("panel") else 0))
        if len(lines) <= 2 or size <= 32:
            break
        size -= 3
    title_h = ts.line_h * len(lines)
    y0 = top + title_h + (34 if st.get("panel") else 18)
    n = len(items)
    cols = 1 if n <= 5 else 2
    per = max(1, -(-n // cols))
    row_h = min(int(st.get("row_max", 76)), (BAND - 8 - y0 - (16 if st.get("panel") else 0)) // per) if n else 0
    list_bottom = y0 + per * row_h
    periods = [(top, top + title_h, ts.line_h), (y0, list_bottom + 4, row_h or 60)]
    if st.get("panel"):
        # dark backing card with a thin metallic border and art-deco diamonds
        px0, py0, px1, py1 = 26, top - 26, W - 26, min(BAND - 6, list_bottom + 14)
        pc = hex_rgba(st.get("panel_color", "#0B0B0D"), int(255 * float(st.get("panel_opacity", 0.72))))
        d.rounded_rectangle([px0, py0, px1, py1], radius=18, fill=pc)
        (md if metal else d).rounded_rectangle([px0, py0, px1, py1], radius=18, outline=ON if metal else accent, width=3)
        (md if metal else d).rounded_rectangle([px0 + 9, py0 + 9, px1 - 9, py1 - 9], radius=12, outline=ON if metal else accent, width=1)
        for cx_, cy_ in ((W // 2, py0), (W // 2, py1)):
            (md if metal else d).polygon([(cx_, cy_ - 11), (cx_ + 11, cy_), (cx_, cy_ + 11), (cx_ - 11, cy_)], fill=ON if metal else accent)
        # rule under the title with a centre diamond
        ry = top + title_h + 12
        g = md if metal else d
        g.line([(W // 2 - 300, ry), (W // 2 - 16, ry)], fill=ON if metal else accent, width=2)
        g.line([(W // 2 + 16, ry), (W // 2 + 300, ry)], fill=ON if metal else accent, width=2)
        g.polygon([(W // 2, ry - 7), (W // 2 + 7, ry), (W // 2, ry + 7), (W // 2 - 7, ry)], fill=ON if metal else accent)
        periods.append((py0 - 2, py1 + 3, py1 - py0 + 5))
    for i, line in enumerate(lines):
        lw = ts.line_width(line)
        x, y = (W - lw) / 2, top + i * ts.line_h
        if metal:  # outlined white title; *emphasis* gets the metal
            ts.draw_line(d, x, y, line, fill, fill, stroke, ocol)
            ts.draw_line(md, x, y, line, OFF, ON)
        else:
            ts.draw_line(d, x, y, line, fill, accent, stroke, ocol)
    late = []  # drawn on top of the metal (the highlighted row's dark text)
    if n:
        col_w = (W - 100) // cols
        nsize = int(row_h * float(st.get("row_fill", 0.62)))
        nfont = _font(str(font_file(st.get("num_font", st["font"]))), nsize)
        nw = d.textlength(f"{n}.", font=nfont) + 18  # numbers right-align in this column
        # one label size for every row: the largest that fits the longest label
        lname = st.get("label_font", st["font"])
        lsize = min([_fit_font(d, t, lname, nsize, col_w - nw - 24).size for t in items if t] or [nsize])
        lf = _font(str(font_file(lname)), lsize)
        # numbers match the labels (a touch larger), so rows read as one line
        nfont = _font(str(font_file(st.get("num_font", st["font"]))), min(nsize, int(lsize * 1.12)))
        nw = d.textlength(f"{n}.", font=nfont) + 18
        hl = hex_rgba(st.get("box_color", "#FFE14D"), 235)
        dark = hex_rgba(st.get("highlight_text", "#111111"))
        for k in range(1, n + 1):
            c, r = (k - 1) // per, (k - 1) % per
            x, y = 50 + c * col_w, y0 + r * row_h
            num = f"{k}."
            # number and label share one baseline, centred on the row by the label's cap height
            cap = -d.textbbox((0, 0), "H", font=lf, anchor="ls")[1]
            base = y + row_h / 2 + cap / 2
            nxy, NA = (x + nw - 14, base), "rs"
            label = items[k - 1] if k in shown else ""
            lxy, LA = (x + nw, base), "ls"
            if k == now and k in shown and metal and st.get("highlight", "box") == "text":
                # current entry: number and label both in the metal, with a small diamond
                d.text(nxy, num, font=nfont, anchor=NA, fill=ocol, stroke_width=max(1, stroke - 1), stroke_fill=ocol)
                md.text(nxy, num, font=nfont, anchor=NA, fill=ON)
                if label:
                    d.text(lxy, label, font=lf, anchor=LA, fill=ocol, stroke_width=max(1, stroke - 1), stroke_fill=ocol)
                    md.text(lxy, label, font=lf, anchor=LA, fill=ON)
                dx, dy = x - 20, base - cap / 2
                md.polygon([(dx, dy - 7), (dx + 7, dy), (dx, dy + 7), (dx - 7, dy)], fill=ON)
                continue
            if k == now and k in shown:
                box = [x - 10, y + 3, x + col_w - 14, y + row_h - 3]
                if metal:
                    md.rounded_rectangle(box, radius=12, fill=ON)
                else:
                    d.rounded_rectangle(box, radius=14, fill=hl)
                late.append((nxy, num, nfont, NA))
                if label:
                    late.append((lxy, label, lf, LA))
                continue
            if metal:
                d.text(nxy, num, font=nfont, anchor=NA, fill=ocol, stroke_width=max(1, stroke - 2), stroke_fill=ocol)
                md.text(nxy, num, font=nfont, anchor=NA, fill=ON)
            else:
                d.text(nxy, num, font=nfont, anchor=NA, fill=accent, stroke_width=max(0, stroke - 1), stroke_fill=ocol)
            if label:
                d.text(lxy, label, font=lf, anchor=LA, fill=fill, stroke_width=max(0, stroke - 1), stroke_fill=ocol)
    if metal:
        layer.alpha_composite(Image.composite(_metal(metal, periods), Image.new("RGBA", (W, BAND), (0, 0, 0, 0)), mask.getchannel("A")))
    d = ImageDraw.Draw(layer)
    for (xy, t, f, a) in late:
        d.text(xy, t, font=f, anchor=a, fill=dark if metal else (17, 17, 17, 255))
    return _shadow(layer, (0, 6), 8, 0.45)


def _context(text: str, st: dict) -> Image.Image:
    """Setup line for a ranking entry (what's going on / who she's talking about), drawn at
    the top of the bottom band above the subtitles. *word* = accent."""
    layer = Image.new("RGBA", (W, BAND), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    size = int(st.get("size", 40))
    while True:
        ts = _Typesetter({**st, "size": size})
        lines = ts.wrap(ts.words(text, st.get("uppercase")), W - 140)
        if len(lines) <= 2 or size <= 28:
            break
        size -= 2
    top = int(st.get("top", 34))
    for i, line in enumerate(lines):
        lw = ts.line_width(line)
        ts.draw_line(d, (W - lw) / 2, top + i * ts.line_h, line, hex_rgba(st.get("color", "#FFFFFF")),
                     hex_rgba(st.get("accent", "#FFE14D")), int(st.get("outline_w", 3)), hex_rgba(st.get("outline", "#000000")))
    return _shadow(layer, (0, 4), 6, 0.5)


def render_caption(text: str, st: dict) -> Image.Image:
    preset = st.get("preset", "box")
    if preset == "ranking":
        return _ranking(text, st)
    if preset == "context":
        return _context(text, st)
    ts = _Typesetter(st)
    pad_box = preset in ("box", "sticker", "news")
    lines = ts.wrap(ts.words(text, st.get("uppercase")), MAX_W - (80 if pad_box else 0))
    widths = [ts.line_width(l) for l in lines]
    block_w, block_h = max(widths or [0]), ts.line_h * len(lines)
    cx, cy = W // 2, int(BAND * st.get("y", 0.55))
    top = cy - block_h // 2
    fill, accent = hex_rgba(st["color"]), hex_rgba(st.get("accent", "#FF5FA2"))
    stroke, ocol = int(st.get("outline_w", 0)), hex_rgba(st.get("outline", "#000000"))
    box_col = hex_rgba(st.get("box_color", "#FFFFFF"))
    layer = Image.new("RGBA", (W, BAND), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)

    if preset == "box":
        for i, (line, lw) in enumerate(zip(lines, widths)):
            y = top + i * ts.line_h
            d.rounded_rectangle([cx - lw / 2 - 26, y - 6, cx + lw / 2 + 26, y + ts.line_h + 4],
                                radius=int(ts.size * 0.3), fill=box_col)
        for i, (line, lw) in enumerate(zip(lines, widths)):
            ts.draw_line(d, cx - lw / 2, top + i * ts.line_h, line, fill, accent, stroke, ocol)
        layer = _shadow(layer, (0, 6), 8, 0.35)

    elif preset == "sticker":
        px, py = 40, 26
        d.rounded_rectangle([cx - block_w / 2 - px, top - py, cx + block_w / 2 + px, top + block_h + py],
                            radius=int(ts.size * 0.45), fill=box_col, outline=(255, 255, 255, 255), width=6)
        for i, (line, lw) in enumerate(zip(lines, widths)):
            ts.draw_line(d, cx - lw / 2, top + i * ts.line_h, line, fill, accent, 3, (0, 0, 0, 90))
        layer = _shadow(layer, (6, 14), 12, 0.6)

    elif preset == "fan":
        for i, (line, lw) in enumerate(zip(lines, widths)):
            ts.draw_line(d, cx - lw / 2, top + i * ts.line_h, line, fill, accent, stroke, hex_rgba(st.get("outline", "#000000"), 150))
        layer = _shadow(layer, (0, 2), 4, 0.55)

    elif preset == "meme":
        for i, (line, lw) in enumerate(zip(lines, widths)):
            ts.draw_line(d, cx - lw / 2, top + i * ts.line_h, line, fill, accent, max(stroke, 6), ocol)
        layer = _shadow(layer, (0, 8), 6, 0.5)

    elif preset == "neon":
        glow = Image.new("RGBA", (W, BAND), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow)
        for i, (line, lw) in enumerate(zip(lines, widths)):
            ts.draw_line(gd, cx - lw / 2, top + i * ts.line_h, line, accent, accent, 6, accent)
        halo = glow.filter(ImageFilter.GaussianBlur(18))
        layer.alpha_composite(halo)
        layer.alpha_composite(halo)
        layer.alpha_composite(glow.filter(ImageFilter.GaussianBlur(5)))
        d = ImageDraw.Draw(layer)
        for i, (line, lw) in enumerate(zip(lines, widths)):
            ts.draw_line(d, cx - lw / 2, top + i * ts.line_h, line, fill, (255, 255, 160, 255), 2, accent)

    elif preset == "news":
        px, py = 34, 18
        x0, x1 = cx - block_w / 2 - px, cx + block_w / 2 + px
        d.rectangle([x0, top - py, x1, top + block_h + py], fill=box_col)
        d.rectangle([x0, top - py, x0 + 14, top + block_h + py], fill=accent)
        label = st.get("label", "BREAKING")
        if label:
            lf = _font(str(font_file(st["font"])), int(ts.size * 0.55))
            lw = d.textlength(label.upper(), font=lf)
            lh = int(ts.size * 0.85)
            d.rectangle([x0, top - py - lh, x0 + lw + 36, top - py], fill=accent)
            d.text((x0 + 18, top - py - lh + lh * 0.12), label.upper(), font=lf, fill=(255, 255, 255, 255))
        for i, (line, lw) in enumerate(zip(lines, widths)):
            ts.draw_line(d, cx - lw / 2 + 7, top + i * ts.line_h, line, fill, accent, stroke, ocol)
        layer = _shadow(layer, (0, 10), 10, 0.5)

    elif preset == "story":
        a = int(255 * float(st.get("box_opacity", 0.55)))
        bc = hex_rgba(st.get("box_color", "#000000"), a)
        for i, (line, lw) in enumerate(zip(lines, widths)):
            y = top + i * ts.line_h
            d.rounded_rectangle([cx - lw / 2 - 22, y - 4, cx + lw / 2 + 22, y + ts.line_h + 2],
                                radius=int(ts.size * 0.32), fill=bc)
        for i, (line, lw) in enumerate(zip(lines, widths)):
            ts.draw_line(d, cx - lw / 2, top + i * ts.line_h, line, fill, accent)

    elif preset == "tweet":
        layer = _tweet_card(text, st, ts, cy)

    rot = float(st.get("rotate", 0) or 0)
    if rot:
        layer = layer.rotate(rot, resample=Image.BICUBIC, center=(cx, cy))
    return layer


def caption_frames(text: str, st: dict) -> list:
    """Pop-in animation frames (last frame = resting caption)."""
    img = render_caption(text, st)
    if not st.get("pop", True):
        return [img]
    if st.get("preset") == "ranking":
        # the list stays put; only the new entry fades in (over ~1/3 s)
        before = _ranking(text, st, reveal_now=False)
        return [Image.blend(before, img, a) for a in (0.0, 0.0, 0.15, 0.35, 0.6, 0.8, 0.92)] + [img]
    if st.get("anim") == "fade":
        # calm entrance: fade up while drifting 14px upward
        frames = []
        for a in FADE_CURVE:
            f = Image.new("RGBA", (W, BAND), (0, 0, 0, 0))
            f.alpha_composite(img, (0, int(14 * (1 - a))))
            f.putalpha(f.getchannel("A").point(lambda v, a=a: int(v * a)))
            frames.append(f)
        frames[-1] = img
        return frames
    cx, cy = W // 2, int(BAND * st.get("y", 0.55))
    frames = []
    # "slam": drops in big and lands with a little bounce (title cards on a hit)
    curve = [2.4, 1.8, 1.35, 1.08, 0.93, 0.97, 1.02, 1.0] if st.get("anim") == "slam" else POP_CURVE
    for s in curve:
        if s == 1.0:
            frames.append(img)
            continue
        sw, sh = int(W * s), int(BAND * s)
        scaled = img.resize((sw, sh), Image.BICUBIC)
        f = Image.new("RGBA", (W, BAND), (0, 0, 0, 0))
        f.alpha_composite(scaled.crop((max(0, int(cx * s - cx)), max(0, int(cy * s - cy)),
                                       min(sw, int(cx * s - cx) + W), min(sh, int(cy * s - cy) + BAND))),
                          (max(0, int(cx - cx * s)), max(0, int(cy - cy * s))))
        if s < 0.9:
            f.putalpha(f.getchannel("A").point(lambda v, s=s: int(v * (s - 0.4) / 0.6)))
        elif s > 1.5:  # slam: fades in while it falls
            f.putalpha(f.getchannel("A").point(lambda v, s=s: int(v * max(0.25, (2.6 - s) / 1.1))))
        frames.append(f)
    return frames
