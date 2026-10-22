"""Extra visuals for a shoot: screenshots, product photos, b-roll clips. Each asset
can be placed on a script line ("overlays"), starting when he says a chosen word
("these") and staying to the end of the line, the end of the video or N seconds.
Every video gets the placement, timed to its own take of that line."""
import hashlib
import io
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from supercut.config import FFMPEG
from supercut.ingest import probe

from . import store
from .takes import tokens

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}
POP = [0.6, 0.85, 1.05, 1.08, 1.03, 1.0]  # scale per frame @30fps

OVERLAY_FIELDS = {
    "id": None, "asset": None, "line": None,
    "at_word": None, "at_occ": 0,  # start when this word is said (None = line start)
    "hold": "line",                # "line" | "video" | seconds (number)
    "x": 0.06, "y": 0.1, "w": 0.46,  # top-left corner + width, fractions of the 1080x1920 frame
    "radius": 28, "border": 0, "shadow": True, "pop": True,
}


def asset_kind(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in IMAGE_EXTS:
        return "image"
    if ext in VIDEO_EXTS:
        return "video"
    raise ValueError(f"{path.name}: not an image or video")


def describe(path: Path, name: str = None) -> dict:
    kind = asset_kind(path)
    if kind == "image":
        with Image.open(path) as im:
            w, h = im.size
    else:
        meta = probe(path)
        w, h = meta["width"], meta["height"]
    return {"id": store.new_id(), "name": name or path.name, "file": str(path), "kind": kind,
            "w": w, "h": h, "crop": None}


def frame_at(video: Path, t: float) -> Image.Image:
    png = subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-ss", f"{t:.3f}", "-i", str(video),
                          "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True).stdout
    if not png:
        raise ValueError("couldn't read a frame there")
    return Image.open(io.BytesIO(png)).convert("RGB")


def cropped(asset: dict) -> Image.Image:
    """The asset image with its crop applied (crop = [x0, y0, x1, y1] fractions)."""
    im = Image.open(asset["file"]).convert("RGBA")
    c = asset.get("crop")
    if c:
        W, H = im.size
        im = im.crop((int(c[0] * W), int(c[1] * H), int(c[2] * W), int(c[3] * H)))
    return im


def preview_png(asset: dict) -> Path:
    key = hashlib.sha1(f"{asset['file']}|{asset.get('crop')}".encode()).hexdigest()[:16]
    out = store.THUMB_DIR / f"asset_{key}.png"
    if not out.exists():
        if asset["kind"] == "image":
            im = cropped(asset)
        else:
            im = frame_at(Path(asset["file"]), 0.5).convert("RGBA")
        im.thumbnail((720, 720))
        im.save(out)
    return out


def styled(img: Image.Image, ov: dict, width: int) -> tuple:
    """Resize + rounded corners + white border + drop shadow. Returns (image, pad):
    pad = shadow margin around the picture, so it can be placed at (x - pad, y - pad)."""
    h = max(2, round(img.height * width / img.width))
    img = img.convert("RGBA").resize((width, h), Image.LANCZOS)
    b = int(ov.get("border") or 0)
    if b:
        framed = Image.new("RGBA", (width + 2 * b, h + 2 * b), (255, 255, 255, 255))
        framed.alpha_composite(img, (b, b))
        img = framed
    r = int(ov.get("radius") or 0)
    if r:
        mask = Image.new("L", img.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, img.width - 1, img.height - 1], radius=r, fill=255)
        img.putalpha(Image.composite(img.getchannel("A"), mask, mask))
    pad = 40 if ov.get("shadow") else 0
    out = Image.new("RGBA", (img.width + 2 * pad, img.height + 2 * pad), (0, 0, 0, 0))
    if pad:
        sh = Image.new("RGBA", out.size, (0, 0, 0, 0))
        sh.paste((0, 0, 0, 120), (pad, pad + 10, pad + img.width, pad + img.height + 10), img.getchannel("A"))
        out.alpha_composite(sh.filter(ImageFilter.GaussianBlur(14)))
    out.alpha_composite(img, (pad, pad))
    return out, pad


def pop_frames(img: Image.Image, on: bool) -> list:
    if not on:
        return [img]
    frames = []
    for s in POP:
        f = Image.new("RGBA", img.size, (0, 0, 0, 0))
        if s == 1.0:
            frames.append(img)
            continue
        sw, sh = max(1, int(img.width * s)), max(1, int(img.height * s))
        sc = img.resize((sw, sh), Image.BICUBIC)
        if s > 1:  # overshoot: crop back to the canvas around the centre
            l, t = (sw - img.width) // 2, (sh - img.height) // 2
            f.alpha_composite(sc.crop((l, t, l + img.width, t + img.height)))
        else:
            f.alpha_composite(sc, ((img.width - sw) // 2, (img.height - sh) // 2))
        if s < 0.9:
            f.putalpha(f.getchannel("A").point(lambda v, s=s: int(v * (s - 0.3) / 0.7)))
        frames.append(f)
    return frames


def start_time(take: dict, ov: dict) -> float:
    """Source time in this take when the overlay's word is said (else the take start)."""
    word = "".join(tokens(ov.get("at_word") or ""))
    if word:
        hits = [w for w in take["words"] if "".join(tokens(w[0])) == word]
        occ = int(ov.get("at_occ") or 0)
        if hits:
            return max(take["in"], hits[min(occ, len(hits) - 1)][1])
    return take["in"]


def timings(s: dict, parts: list, total: float) -> list:
    """[(overlay, asset, t0, t1)] in video time. parts = [(take, video t0)]."""
    by_asset = {a["id"]: a for a in s.get("assets", [])}
    out = []
    for ov in s.get("overlays", []):
        a = by_asset.get(ov.get("asset"))
        hit = next(((tk, t0) for tk, t0 in parts if tk["line"] == ov.get("line")), None)
        if not a or not hit:
            continue  # this video doesn't have that line (optional line ran out)
        tk, t0 = hit
        start = t0 + store.take_rel(tk, start_time(tk, ov))
        hold = ov.get("hold", "line")
        end = (t0 + tk["out"] - tk["in"]) if hold == "line" else total if hold == "video" else start + float(hold)
        if end > start + 0.05:
            out.append(({**OVERLAY_FIELDS, **ov}, a, start, min(end, total)))
    return out
