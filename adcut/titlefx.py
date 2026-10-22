"""The game-title dance over a hook's freeze frame: the title hops to a new spot on every
beat of the jingle (adcut/sounds._jingle: 168 bpm eighth notes), then slams into place on
the last, held note and stays there until the music's done. The editor runs the same
keyframes (app.js titleDance) so the preview matches the render."""
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H, FPS = 1080, 1920, 30
BEAT = 60 / 168 / 2          # one eighth note of the jingle
LAND = BEAT * 8              # the held last note
# where the title's centre sits on each beat (frame px) and its tilt; all inside TikTok's
# safe area (clear of the right-hand rail and the caption block at the bottom)
SPOTS = [(400, 430, -10), (680, 700, 9), (420, 1000, -7), (660, 1180, 10),
         (430, 820, -9), (650, 520, 7), (460, 1100, -5), (620, 760, 6)]
SLAM = [1.55, 1.3, 1.08, 0.94, 0.98, 1.02, 1.0]  # scale per frame on the landing


def _ease(u):
    return 1 - (1 - min(1.0, max(0.0, u))) ** 3


def at(e: float, land_y: float):
    """(centre x, centre y, rotation, scale) e seconds into the freeze."""
    home = (W / 2, land_y, 0.0)
    if e < LAND:
        k = int(e / BEAT)
        prev = SPOTS[k - 1] if k else (W / 2, land_y, 0)
        cur = SPOTS[k]
        u = _ease((e - k * BEAT) / 0.07)  # a quick slide into each spot
        x, y, r = (p + (c - p) * u for p, c in zip(prev, cur))
        pop = 1.14 - 0.14 * _ease((e - k * BEAT) / 0.1)  # little bump on the beat
        if k == 0:
            pop *= 0.55 + 0.45 * _ease(e / 0.1)  # first appearance pops in
        return x, y, r, pop
    f = int((e - LAND) * FPS)
    u = _ease((e - LAND) / 0.06)
    last = SPOTS[-1]
    x, y, r = (p + (c - p) * u for p, c in zip(last, home))
    return x, y, r, SLAM[f] if f < len(SLAM) else 1.0


def frames(card: Image.Image, seconds: float, land_y: float) -> list:
    """Full-frame RGBA images (30/s) of the dancing title card (a 1080x640 caption image)."""
    bbox = card.getbbox() or (0, 0, card.width, card.height)
    title = card.crop(bbox)
    out = []
    for i in range(max(1, int(round(seconds * FPS)))):
        x, y, r, sc = at(i / FPS, land_y)
        sc = min(sc, (W - 48) / title.width)  # even the slam stays inside the frame
        t = title.resize((max(1, int(title.width * sc)), max(1, int(title.height * sc))), Image.BICUBIC)
        t = t.rotate(-r, resample=Image.BICUBIC, expand=True)
        f = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        x = min(max(x, t.width / 2 + 24), W - t.width / 2 - 24)  # always fully on screen
        f.paste(t, (int(x - t.width / 2), int(y - t.height / 2)), t)
        out.append(f)
    return out


# ---------- the title card: a game-show logo, not a caption ----------
FONTS = {"rockwell": r"C:\Windows\Fonts\ROCKEB.TTF", "snap": r"C:\Windows\Fonts\SNAP____.TTF",
         "impact": r"C:\Windows\Fonts\impact.ttf"}


def _hex(c):
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def card(text: str, st: dict = None) -> Image.Image:
    """1080x640 RGBA, the title centred: gradient fill, thick dark outline, a 3D extrude
    and a soft shadow. Long titles go on two lines ("THIS OR" / "THAT")."""
    st = st or {}
    font_path = FONTS.get(st.get("title_font", "rockwell"), FONTS["rockwell"])
    top, bottom = _hex(st.get("fill_top", "#FFF27A")), _hex(st.get("fill_bottom", "#FF9F1C"))
    edge, deep = _hex(st.get("edge", "#1B0B3A")), _hex(st.get("extrude", "#7B2FF7"))
    words = text.upper().split()
    lines = [text.upper()] if len(text) <= 9 or len(words) < 2 else [" ".join(words[:-1]), words[-1]]
    size = int(st.get("title_size", 172 if len(lines) == 1 else 140))
    font = ImageFont.truetype(font_path, size)
    stroke, depth, gap = max(8, size // 14), max(10, size // 11), int(size * 0.08)
    d0 = ImageDraw.Draw(Image.new("L", (1, 1)))
    boxes = [d0.textbbox((0, 0), l, font=font, stroke_width=stroke) for l in lines]
    while max(b[2] - b[0] for b in boxes) > 1000 and size > 60:  # fit the width
        size -= 6
        font = ImageFont.truetype(font_path, size)
        stroke, depth, gap = max(8, size // 14), max(10, size // 11), int(size * 0.08)
        boxes = [d0.textbbox((0, 0), l, font=font, stroke_width=stroke) for l in lines]
    w = max(b[2] - b[0] for b in boxes) + depth + 40
    h = sum(b[3] - b[1] for b in boxes) + gap * (len(lines) - 1) + depth + 40
    mask = Image.new("L", (w, h), 0)      # letters
    outline = Image.new("L", (w, h), 0)   # letters + stroke
    md, od = ImageDraw.Draw(mask), ImageDraw.Draw(outline)
    y = 20
    for l, b in zip(lines, boxes):
        x = 20 + (w - 40 - depth - (b[2] - b[0])) // 2 - b[0]
        md.text((x, y - b[1]), l, font=font, fill=255)
        od.text((x, y - b[1]), l, font=font, fill=255, stroke_width=stroke, stroke_fill=255)
        y += b[3] - b[1] + gap
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    shadow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    shadow.paste((0, 0, 0, 150), (depth + 6, depth + 10), outline)
    out.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(9)))
    for k in range(depth, 0, -1):  # extrude: stacked copies, darker the deeper
        f = 0.55 + 0.45 * (1 - k / depth)
        layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        layer.paste((*[int(c * f) for c in deep], 255), (k, k), outline)
        out.alpha_composite(layer)
    face = Image.new("RGBA", (w, h), (*edge, 255))
    out.paste(face, (0, 0), outline)  # the outline
    grad = Image.new("RGBA", (w, h))
    gd = ImageDraw.Draw(grad)
    for yy in range(h):
        u = yy / max(1, h - 1)
        gd.line([(0, yy), (w, yy)], fill=tuple(int(a + (b - a) * u) for a, b in zip(top, bottom)) + (255,))
    out.paste(grad, (0, 0), mask)  # the gradient letters
    shine = Image.new("RGBA", (w, h), (255, 255, 255, 0))  # a glossy top highlight
    sd = ImageDraw.Draw(shine)
    sd.rectangle([0, 0, w, int(h * 0.38)], fill=(255, 255, 255, 70))
    hl = Image.new("L", (w, h), 0)
    hl.paste(mask, (0, 0))
    out.alpha_composite(Image.composite(shine, Image.new("RGBA", (w, h), (0, 0, 0, 0)), hl))
    band = Image.new("RGBA", (W, 640), (0, 0, 0, 0))
    band.alpha_composite(out.crop((0, 0, min(w, W), min(h, 640))), ((W - min(w, W)) // 2, (640 - min(h, 640)) // 2))
    return band


# ---------- the text hook: a crisp card that pops in, then a shine sweeps across ----------
HOOK_FONT = r"C:\Windows\Fonts\ariblk.ttf"


def hook_card(text: str, st: dict = None) -> Image.Image:
    """White rounded card, heavy black type, the *starred* words on a red highlight, soft
    shadow, slight tilt. Returns the card alone (RGBA, tight)."""
    st = st or {}
    size = int(st.get("hook_size", 78))
    font = ImageFont.truetype(st.get("hook_font", HOOK_FONT), size)
    accent = _hex(st.get("accent", "#FE2C55"))
    words = text.upper().split()
    keys = {i for i, w in enumerate(words) if w.startswith("*") or w.endswith("*")}
    words = [w.strip("*") for w in words]
    if not keys and len(words) > 1:  # no stars: the longest word carries the joke
        keys = {max(range(len(words)), key=lambda i: len(words[i]))}
    d0 = ImageDraw.Draw(Image.new("L", (1, 1)))
    space = d0.textlength(" ", font=font)
    # wrap into lines of at most ~14 characters
    lines, cur = [], []
    for i, w in enumerate(words):
        if cur and len(" ".join(words[j] for j in cur + [i])) > 14:
            lines.append(cur); cur = []
        cur.append(i)
    lines.append(cur)
    asc, desc = font.getmetrics()
    lh = asc + desc
    padx, pady, gap = 46, 30, 10
    widths = [sum(d0.textlength(words[i], font=font) for i in l) + space * (len(l) - 1) + (28 if keys & set(l) else 0) for l in lines]
    w, h = int(max(widths) + padx * 2), int(lh * len(lines) + gap * (len(lines) - 1) + pady * 2)
    card = Image.new("RGBA", (w + 60, h + 70), (0, 0, 0, 0))
    sh = Image.new("RGBA", card.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle([30, 40, 30 + w, 40 + h], 34, fill=(0, 0, 0, 120))
    card.alpha_composite(sh.filter(ImageFilter.GaussianBlur(14)))
    dr = ImageDraw.Draw(card)
    dr.rounded_rectangle([30, 30, 30 + w, 30 + h], 34, fill=(255, 255, 255, 255))
    y = 30 + pady
    for l, lw in zip(lines, widths):
        x = 30 + (w - lw) / 2
        for i in l:
            tw = d0.textlength(words[i], font=font)
            if i in keys:  # the highlight behind the key word
                dr.rounded_rectangle([x - 4, y - 2, x + tw + 24, y + lh - 2], 14, fill=(*accent, 255))
                dr.text((x + 10, y), words[i], font=font, fill=(255, 255, 255, 255))
                x += tw + 28 + space
            else:
                dr.text((x, y), words[i], font=font, fill=(17, 17, 17, 255))
                x += tw + space
        y += lh + gap
    return card.rotate(float(st.get("rotate", -2)), resample=Image.BICUBIC, expand=True)


POP = [0.35, 0.7, 1.0, 1.12, 1.08, 1.02, 0.99, 1.0]


def hook_frames(text: str, st: dict, seconds: float, y: float) -> list:
    """Full-frame RGBA frames: pop in, a gloss sweep at ~0.45s, a gentle settle, hold."""
    card = hook_card(text, st)
    shine_w = card.width // 4
    out = []
    for i in range(max(1, int(round(seconds * FPS)))):
        e = i / FPS
        sc = POP[i] if i < len(POP) else 1.0 + 0.012 * __import__("math").sin(2 * 3.14159 * 0.8 * (e - 0.3))
        c = card.resize((max(1, int(card.width * sc)), max(1, int(card.height * sc))), Image.BICUBIC)
        if 0.4 <= e <= 0.85:  # a diagonal shine passing over the card
            u = (e - 0.4) / 0.45
            band = Image.new("L", c.size, 0)
            bx = int(-shine_w + u * (c.width + 2 * shine_w))
            ImageDraw.Draw(band).polygon([(bx, 0), (bx + shine_w, 0), (bx + shine_w - c.height // 2, c.height), (bx - c.height // 2, c.height)], fill=110)
            alpha = c.getchannel("A")
            band = Image.composite(band, Image.new("L", c.size, 0), alpha.point(lambda v: 255 if v > 200 else 0))
            white = Image.new("RGBA", c.size, (255, 255, 255, 0))
            white.putalpha(band.filter(ImageFilter.GaussianBlur(6)))
            c = c.copy(); c.alpha_composite(white)
        if i < 3:  # fade in with the pop
            c.putalpha(c.getchannel("A").point(lambda v, i=i: int(v * (0.35 + 0.3 * i))))
        f = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        f.paste(c, (int(W / 2 - c.width / 2), int(y - c.height / 2)), c)
        out.append(f)
    return out
