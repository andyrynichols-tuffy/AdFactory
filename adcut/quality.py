"""How good a take is, so the best ones stack into video 1: the line said cleanly
(match score, no ums, not reworded, no long pauses) while looking into the camera
(a frontal face with both eyes level and centred, not turned off to the side to check
the script). Eye contact is measured once per raw file (4 frames a second of its proxy,
cached) and averaged over each take's words."""
import json
import subprocess

import numpy as np

from supercut.config import FFMPEG, FFPROBE

from . import store

VERSION = 1
FPS = 4
GAZE_DIR = store.AD_DATA / "gaze"
_mem = {}


def _detectors():
    import cv2
    d = cv2.data.haarcascades
    return (cv2, cv2.CascadeClassifier(d + "haarcascade_frontalface_alt2.xml"),
            cv2.CascadeClassifier(d + "haarcascade_eye_tree_eyeglasses.xml"),
            cv2.CascadeClassifier(d + "haarcascade_profileface.xml"))


def _frame_score(cv2, face, eye, prof, g):
    """1 = looking into the lens, ~0 = turned away, nan = nobody in shot."""
    fs = face.detectMultiScale(g, 1.1, 5, minSize=(40, 40))
    if len(fs):
        x, y, w, h = max(fs, key=lambda f: f[2] * f[3])
        roi = g[y: y + int(h * 0.6), x: x + w]
        es = eye.detectMultiScale(roi, 1.1, 4, minSize=(max(8, w // 10), max(8, w // 10)))
        if len(es) >= 2:
            es = sorted(es, key=lambda e: e[2] * e[3])[-2:]
            mid = sum(e[0] + e[2] / 2 for e in es) / 2
            asym = abs(mid - w / 2) / w           # head turned: eyes slide off-centre
            tilt = abs((es[0][1] - es[1][1])) / w  # looking down at a phone/script tilts too
            return float(max(0.0, 1 - asym * 4 - tilt * 2))
        return 0.6  # face toward camera, eyes not clear (blink, glasses glare)
    if len(prof.detectMultiScale(g, 1.1, 4)) or len(prof.detectMultiScale(cv2.flip(g, 1), 1.1, 4)):
        return 0.1  # side-on
    return float("nan")


def gaze_track(key: str) -> np.ndarray:
    """Per-frame (4/s) eye-contact score for a raw file's proxy, cached on disk."""
    if key in _mem:
        return _mem[key]
    GAZE_DIR.mkdir(parents=True, exist_ok=True)
    f = GAZE_DIR / f"{key}-v{VERSION}.npy"
    if f.exists():
        _mem[key] = np.load(f)
        return _mem[key]
    proxy = store.PROXY_DIR / f"{key}.mp4"
    wh = subprocess.run([FFPROBE, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                         "-of", "json", str(proxy)], capture_output=True, text=True).stdout
    st = json.loads(wh)["streams"][0]
    w = 270 if st["width"] <= st["height"] else 480
    h = int(round(st["height"] * w / st["width"] / 2)) * 2
    cv2, face, eye, prof = _detectors()
    p = subprocess.Popen([FFMPEG, "-hide_banner", "-loglevel", "error", "-i", str(proxy), "-vf",
                          f"fps={FPS},scale={w}:{h},format=gray", "-f", "rawvideo", "-"], stdout=subprocess.PIPE)
    out, n = [], w * h
    while True:
        b = p.stdout.read(n)
        if len(b) < n:
            break
        out.append(_frame_score(cv2, face, eye, prof, np.frombuffer(b, np.uint8).reshape(h, w)))
    p.wait()
    arr = np.array(out, dtype=np.float32)
    np.save(f, arr)
    _mem[key] = arr
    return arr


def eye_contact(key: str, t0: float, t1: float):
    """Average eye contact over [t0, t1] seconds, or None when nobody's in shot."""
    try:
        g = gaze_track(key)
    except Exception:  # noqa: BLE001  (no OpenCV / bad proxy: just don't rank on it)
        return None
    seg = g[max(0, int(t0 * FPS)): max(int(t0 * FPS) + 1, int(np.ceil(t1 * FPS)))]
    seg = seg[~np.isnan(seg)]
    return float(seg.mean()) if len(seg) else None


def score(t: dict, key: str, fillers: set, tokens) -> dict:
    """{quality 0..1, eye 0..1|None, variant label|None} for one take."""
    ws = [w for w in t["words"] if t["in"] - 0.05 <= w[1] <= t["out"]] or t["words"]
    extra = t.get("extra") or []
    fill = sum(1 for x in extra if x in fillers)
    rew = len(t.get("missing") or []) + len(extra) - fill
    gaps = [b[1] - a[2] for a, b in zip(ws, ws[1:])]
    fluency = max(0.0, 1 - 0.2 * fill - 0.08 * rew - (0.25 if max(gaps, default=0) > 0.6 else 0))
    eye = eye_contact(key, ws[0][1], ws[-1][2]) if ws else None
    q = 0.3 * float(t.get("score") or 0) + 0.25 * fluency + 0.35 * (0.7 if eye is None else eye) \
        + 0.1 * (t["status"] == "good")
    variant = "alt wording" if t.get("alt") else "reworded" if rew >= 3 else None
    return {"quality": round(q, 3), "eye": None if eye is None else round(eye, 2), "variant": variant}
