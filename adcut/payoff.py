"""Lines whose payoff is something you see after the words, not the words themselves:
"But you can blow it out" only works if the candle then goes out on camera.

line["wait_for"] = "light_off": after the last word, watch the frame for the warm
glow of a flame / LED / bulb to disappear. The take is held until a beat after it
goes out (line["hold_after"], default 0.7s); a take where it never goes out is
rejected ("stayed lit"). Detection is per take and cached."""
import subprocess

import numpy as np

from adkit.config import FFMPEG

from . import store

W, H, FPS = 135, 240, 10
WINDOW = 4.0  # seconds after the words to watch for it
_cache = {}


def _frames(key: str, t0: float, t1: float):
    raw = subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-ss", f"{t0:.2f}", "-t", f"{max(0.2, t1 - t0):.2f}",
                          "-i", str(store.PROXY_DIR / f"{key}.mp4"), "-vf", f"fps={FPS},scale={W}:{H}",
                          "-pix_fmt", "rgb24", "-f", "rawvideo", "-"], capture_output=True).stdout
    n = len(raw) // (W * H * 3)
    return np.frombuffer(raw, np.uint8)[: n * W * H * 3].reshape(n, H, W, 3).astype(np.int16)


def glow(fr) -> np.ndarray:
    """Warm bright pixels per frame (a lit flame/LED: bright, yellow-orange, not white
    wax, not pink glass)."""
    r, g, b = fr[..., 0], fr[..., 1], fr[..., 2]
    m = (r > 200) & (g > 150) & (r - b > 80) & (g - b > 40)
    return m.reshape(len(fr), -1).sum(1)


def light_off(key: str, t_start: float, t_words_end: float, t_limit: float):
    """Source time the light goes out after the words (None = it didn't, or there was
    no light to begin with: returns (time | None, reason))."""
    ck = (key, round(t_start, 2), round(t_words_end, 2), round(t_limit, 2))
    if ck in _cache:
        return _cache[ck]
    t1 = min(t_limit, t_words_end + WINDOW)
    fr = _frames(key, t_start, t1)
    c = glow(fr)
    k = int((t_words_end - t_start) * FPS)
    before, after = c[:max(1, k)], c[k:]
    base = float(np.median(before)) if len(before) else 0.0
    if base < 12:
        res = (None, "no light seen while he said it")
    else:
        thr = min(12.0, 0.4 * base)
        res = (None, "stayed lit")
        run = 0
        for i, v in enumerate(after):
            run = run + 1 if v <= thr else 0
            if run >= 3:  # dark for 0.3s
                res = (t_words_end + (i - 2) / FPS, None)
                break
    _cache[ck] = res
    return res


def apply(s: dict, takes: list):
    """Hold "wait for it" takes until the payoff, reject the ones without it."""
    lines = {l["id"]: l for l in s["script"] if l.get("wait_for") == "light_off"}
    srcs = {x["id"]: x for x in s["sources"]}
    for t in takes:
        line = lines.get(t["line"])
        if not line or not t["words"] or t["user"].get("out"):
            continue
        end = t["words"][-1][2]
        limit = t.pop("_limit", None) or end + WINDOW
        at, why = light_off(srcs[t["src"]]["key"], t["in"], end, limit)
        if at is not None:
            hold = line.get("hold_after")
            t["out"] = round(min(limit - 0.05, at + (0.7 if hold is None else float(hold))), 3)
            t["flags"] = t["flags"] + [f"goes out {at - end:.1f}s after the line"]
        elif t["usable"] or t["status"] in ("good", "close"):
            t["status"], t["usable"] = "nopayoff", False
            t["flags"] = t["flags"] + [f"{why}: the candle has to go out on camera"]
    for t in takes:
        t.pop("_limit", None)
