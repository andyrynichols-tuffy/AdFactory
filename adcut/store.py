"""The shoot file (ads/<shoot>/shoot.json): single source of truth shared by the
ad editor, the take matcher, the renderer and Claude.

A shoot = raw video files + the script (one entry per line) + takes. A take is one
attempt at one line: a range in a source file. The usable takes of each line, in
their order, form that line's stack; finished video k uses take k of every line."""
import copy
import hashlib
import json
import re
import time
import uuid
from pathlib import Path

from supercut.config import CFG, DATA_DIR, ROOT

SHOOTS_DIR = ROOT / "ads"
AD_DATA = DATA_DIR / "ads"
PROXY_DIR = AD_DATA / "proxies"
WORDS_DIR = AD_DATA / "words"      # per-source transcripts (word timings)
THUMB_DIR = AD_DATA / "thumbs"
UPLOAD_DIR = AD_DATA / "uploads"   # files dropped into the editor are copied here
CACHE_DIR = AD_DATA / "cache"      # rendered take segments
OUTPUT_DIR = Path(CFG.get("ad_output_dir") or Path.home() / "Videos" / "TikTok Shop")
# "Download" copies chosen videos here, by date, ready to post (like Meme Factory's posts)
DOWNLOAD_DIR = Path(CFG.get("ad_download_dir") or OUTPUT_DIR / "Ready to post")  # OneDriveAd Factory Outbox

for d in (SHOOTS_DIR, PROXY_DIR, WORDS_DIR, THUMB_DIR, UPLOAD_DIR, CACHE_DIR, OUTPUT_DIR, DOWNLOAD_DIR):
    d.mkdir(parents=True, exist_ok=True)

DEFAULT_STYLE = {
    # subtitles burned in from the spoken words (script spelling wins)
    "subs": {"on": True, "font": "Arial Black", "size": 84, "color": "#FFFFFF", "highlight": "#FFE14D",
             "outline": "#000000", "outline_w": 6, "uppercase": False, "y": 0.66,
             "words_per_line": 3, "karaoke": True, "pop": True},
    # hook text at the top during the first seconds (video k uses hooks[k % len])
    # playback speed: the whole video (speed), and auto pacing toward TikTok Shop pace (the
    # waffle reference runs ~5 words/s with no pauses). Auto pace mostly cuts the dead air
    # between words (pauses > 0.3s, as cut-outs you can see and undo on the trim strip) and
    # only nudges the slowest reads a little faster (max 1.1x: more sounds sped up).
    # take.speed overrides it for one clip.
    # picture: brightness (-0.3..0.3; down pulls the highlights in more than the shadows, for a
    # blown-out look) and skin smoothing (0..1, edge-preserving). take.bright adjusts one clip.
    "look": {"brightness": 0.0, "smooth": 0.0},
    "speed": 1.0,
    "pace": {"auto": True, "wps": 4.8, "max": 1.1, "pauses": True},
    # the title over a take's freeze frame (game name after the cold-open hook)
    "title": {"on": True, "y": 0.42, "preset": "meme", "font": "Impact", "size": 150, "color": "#FFFFFF",
              "box_color": "#000000", "accent": "#FFE14D", "outline_w": 10, "uppercase": True, "rotate": -4, "pop": True},
    "hook": {"on": True, "seconds": 3.0, "y": 0.2, "preset": "box", "font": "Arial Black", "size": 58,
             "color": "#000000", "box_color": "#FFFFFF", "accent": "#FE2C55", "outline_w": 0,
             "uppercase": False, "rotate": 0, "pop": True},
    # call to action over the last line, e.g. "tap the orange cart 🛒"
    "cta": {"on": False, "y": 0.8, "preset": "sticker", "font": "Arial Black", "size": 52,
            "color": "#FFFFFF", "box_color": "#FE2C55", "accent": "#FFE14D", "outline_w": 0,
            "uppercase": False, "rotate": -2, "pop": True},
    # where the product is in frame [x0, y0, x1, y1] (fractions); text moves off it
    "product_box": None,
    # when he says these words, an arrow + ring point at TikTok's orange-cart product tag
    "cart_pointer": {"on": True, "words": "orange cart, cart, basket", "seconds": 2.2, "color": "#FF8A00"},
    # alternate punch-in zoom on every other line: the classic talking-head jump cut
    "punch_in": 1.12,
    # seconds of room kept before the first word / after the last word of each take
    "pad_before": 0.08, "pad_after": 0.18,
    "voice_cleanup": False,  # rumble filter + light denoise for phone audio
    "loudness": -14,
}

DEFAULT_SHOOT = {
    "version": 1,
    "rev": 0,            # bumped on every save; stale editor saves get a 409
    "title": "",
    "created": 0,
    "product": {"name": "", "link": "", "description": "", "hashtags": "#tiktokshop #tiktokmademebuyit"},
    # the video this shoot is copying (a TikTok link and/or a saved file) + notes on
    # what to copy from it (pacing, hook, text style)
    "reference": {"url": "", "file": "", "notes": ""},
    # {id, file, name, key, duration, width, height, status, error,
    #  looks: [{t, name}] outfit changes, e.g. white from 0, olive from 205}
    "sources": [],
    # {id, text, optional, look (only takes filmed in this outfit), cut_next (a
    #  transition: cut on the motion straight into the next line)}
    "script": [],
    "script_guessed": False,
    "takes": [],         # see TAKE_FIELDS
    "hooks": [],         # hook overlay texts, cycled across the videos
    "cta": "",  # retired: no on-screen text that isn't in the script
    "style": DEFAULT_STYLE,
    "skip": [],          # video numbers (1-based) the user excluded from rendering
    # footage added later is a new batch (source.batch). mix = None (auto: decided when it
    # comes in, see takes.decide_mix), True (re-cut everything together) or False (each
    # batch makes its own videos, after the earlier ones, which stay as they were)
    "mix": None, "mix_auto": True, "batch_note": "",
    # voiceover videos: the audio is this stretch of a raw file (a separate voice recording);
    # the takes are silent visual shots under it. None = normal (each take's own sound).
    "voiceover": None,   # {"src": source id, "in": s, "out": s, "cuts": [[a, b]], "volume": 1.0}
    "voiceovers": [],    # several reads: video n uses voiceovers[(n-1) % len] (same shots, pick the best read)
    "from_inbox": False,  # made automatically from a video dropped in the inbox folder
    "assets": [],        # {id, name, file, kind (image|video), w, h, crop [x0,y0,x1,y1] fractions}
    "overlays": [],      # asset placements on lines, see assets.OVERLAY_FIELDS
    "renders": {},       # "1" -> output file path
    # posting queue (like Meme Factory's Saved): "1" -> {saved_at, sig (what video 1 was
    # when saved), posted, posted_at}
    "saved": {},
    "phone_off": [],     # raw files archived or deleted in Ad Camera (file keys): their takes stay out of the videos
}

TAKE_FIELDS = {
    "id": None, "line": None,   # line id, None = unmatched speech
    "src": None, "in": 0.0, "out": 0.0, "look": None, "alt": 0,  # which wording he used
    "text": "",                 # what was actually said
    "for_text": None,           # the script wording it was matched to (reworded line = re-fit trims)
    "words": [],                # [[text, start, end]] absolute source seconds, script spelling
    "score": 0.0,               # 0..1 match against the line
    "status": "good",           # good | close | flub | incomplete | paused | nopayoff | unmatched
    "flags": [],                # human-readable reasons
    "missing": [], "extra": [],  # words left out / added vs the script
    "usable": True,
    "order": 0,                 # position in its line's stack
    "zoom": 1.0, "pan_x": 0.5, "pan_y": 0.5, "volume": 1.0,
    "cuts": [],                 # [[a, b]] source seconds cut out of the take (pauses, ums)
    "splits": [],               # split marks (source seconds) the user placed on the trim strip
    "sfx": [],                  # [{id, name, at (source seconds), vol}] soundboard sounds on this take
    "fx": [],                   # [{id, kind, at (source seconds), dur}] effects-board effects on this take
    "quality": None,            # 0..1 how good the take is (adcut/quality.py): best ones stack first
    "eye": None,                # 0..1 eye contact with the lens over the words (None = nobody in shot)
    "variant": None,            # "alt wording" / "reworded": a different read, grouped into the same video
    "speed": None,              # this clip's speed (None = the video's speed + auto pace)
    "bright": 0.0,              # this clip's brightness on top of the video's (style.look)
    "freeze": 0.0,              # hold the last frame this long (the hook's freeze frame)
    "title": "",                # big text over the freeze frame, e.g. the game's name
    "game": None, "spice": None,  # montage shoots: which game, how spicy (0 clean .. 3 spicy)
    "user": {},                 # fields the user set by hand (kept when takes are re-matched)
}


def new_id() -> str:
    return uuid.uuid4().hex[:6]


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:48] or "shoot"


def path_for(sid: str) -> Path:
    if not re.fullmatch(r"[a-z0-9-]+", sid or ""):
        raise ValueError("bad shoot id")
    return SHOOTS_DIR / sid / "shoot.json"


def deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        out[k] = deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def normalize(s: dict) -> dict:
    s = deep_merge(DEFAULT_SHOOT, s)
    if s["cta"] == "tap the orange cart to grab yours 🛒":  # old default sticker: retired
        s["cta"] = ""
    s["style"]["cta"]["on"] = False
    if s["style"]["pace"].get("max") == 1.35:  # first auto pace sped up too much: gentler now
        s["style"]["pace"].update({"wps": 4.8, "max": 1.1, "pauses": True})
    for line in s["script"]:
        line.setdefault("id", new_id())
        line.setdefault("optional", False)
        line.setdefault("look", None)
        line.setdefault("cut_next", False)
        line.setdefault("alts", [])
        line.setdefault("product_box", None)
        line.setdefault("wait_for", None)    # "light_off": hold until the light goes out on camera
        line.setdefault("hold_after", None)
        line.setdefault("lead_in", None)
        line.setdefault("subs_off", False)   # hide captions while this line plays     # seconds of action kept before the first word (None = default)  # seconds kept after the payoff / last word (None = default)  # where the product is during this line (None = the shoot's)  # alternate wordings; a take of any of them counts
        line.setdefault("cut_offset", None)  # seconds into the next line where the cut lands (None = auto)
    for src in s["sources"]:
        src.setdefault("looks", [])
    s["takes"] = [{**copy.deepcopy(TAKE_FIELDS), **t, "id": t.get("id") or new_id()} for t in s["takes"]]
    # videos saved/posted before saving locked them: lock their takes as they are now
    missing = [k for k, m in (s.get("saved") or {}).items() if not m.get("takes")]
    if missing:
        vs = {v["n"]: v for v in videos(s)["videos"]}
        for k in sorted(missing, key=int):
            if int(k) in vs:
                s["saved"][k]["takes"] = list(vs[int(k)]["takes"])
    return s


def load(sid: str) -> dict:
    return normalize(json.loads(path_for(sid).read_text(encoding="utf-8")))


def save(sid: str, s: dict, expect_rev: int = None) -> dict:
    p = path_for(sid)
    if expect_rev is not None and p.exists():
        cur = json.loads(p.read_text(encoding="utf-8")).get("rev", 0)
        if cur != expect_rev:
            raise RevConflict(cur)
    s = normalize(s)
    s["rev"] = int(s.get("rev", 0)) + 1
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(s, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)
    return s


class RevConflict(Exception):
    pass


def update(sid: str, fn) -> dict:
    """Load, change, save: for background jobs, so they never clobber editor edits
    made while they ran (the editor reloads on the new rev)."""
    s = load(sid)
    fn(s)
    return save(sid, s)


def create(title: str) -> str:
    base = slug(title or time.strftime("shoot %b %d"))
    sid, n = base, 2
    while path_for(sid).exists():
        sid, n = f"{base}-{n}", n + 1
    save(sid, {"title": title or sid, "created": time.time()})
    return sid


def shoots() -> list:
    out = []
    for p in SHOOTS_DIR.glob("*/shoot.json"):
        try:
            s = load(p.parent.name)
        except Exception:
            continue
        out.append({"id": p.parent.name, "title": s["title"], "created": s["created"],
                    "mtime": p.stat().st_mtime, "videos": videos(s)["count"],
                    "lines": len(s["script"]), "sources": len(s["sources"]),
                    "rendered": len(s["renders"]), "product": s["product"]["name"],
                    "inbox": bool(s.get("from_inbox")), "script_guessed": bool(s.get("script_guessed")),
                    "shop": s.get("shop"),
                    "batches": len({x.get("batch", 1) for x in s["sources"]}),
                    "ready": bool(s["sources"]) and all(x.get("status") == "ready" for x in s["sources"])})
    return sorted(out, key=lambda r: -r["created"])


def source_key(path: Path) -> str:
    """Stable id for a raw file's proxy/transcript (same file added twice = reused)."""
    st = path.stat()
    return hashlib.sha1(f"{path.resolve()}|{st.st_size}".encode()).hexdigest()[:14]


# ---------- stacks -> videos ----------

def stack(s: dict, line_id: str, usable: bool = True) -> list:
    return sorted((t for t in s["takes"] if t["line"] == line_id and t["usable"] == usable),
                  key=lambda t: (t["order"], t["in"]))


def posted_videos(s: dict) -> dict:
    """{video n: [take ids]} frozen when it was saved (or posted). TikTok flags footage
    that's reused, so those takes are locked: no other video may use them."""
    have = {t["id"] for t in s["takes"]}
    out = {}
    for k, m in (s.get("saved") or {}).items():
        if m.get("takes"):
            out[int(k)] = [i for i in m["takes"] if i in have]
    return out


def locked_ids(s: dict) -> dict:
    """take id -> the posted video it's locked into."""
    return {i: n for n, ids in posted_videos(s).items() for i in ids}


PHONE_OFF = "removed on the phone"


def file_key(name: str) -> str:
    """A file name as letters and digits only, so the phone's name for a take matches the
    inbox's cleaned-up copy of it."""
    return "".join(c for c in Path(name or "").name.lower() if c.isalnum())


def apply_phone_off(s: dict) -> dict:
    """Takes from raw files archived or deleted in Ad Camera become rejects flagged PHONE_OFF
    (takes already in saved/posted videos stay there); takes from files brought back count
    again, by their own grade. Run after the list changes and after takes are re-matched.
    Returns {"files": raw files found, "off": takes kept out, "locked": takes left in saved videos}."""
    keys = set(s.get("phone_off") or [])
    srcs = {x["id"] for x in s["sources"] if file_key(x.get("name") or x.get("file")) in keys}
    locked = locked_ids(s)
    out = {"files": len(srcs), "off": 0, "locked": 0}
    for t in s["takes"]:
        if t["src"] in srcs:
            if t["id"] in locked:
                out["locked"] += 1
                continue
            t["usable"] = False
            t["user"]["usable"] = True
            if PHONE_OFF not in t["flags"]:
                t["flags"] = t["flags"] + [PHONE_OFF]
            out["off"] += 1
        elif PHONE_OFF in (t.get("flags") or []):
            t["flags"] = [f for f in t["flags"] if f != PHONE_OFF]
            t["user"].pop("usable", None)
            t["usable"] = t["status"] in ("good", "close")
    return out


def set_phone_off(s: dict, name: str, off: bool) -> dict:
    keys = set(s.get("phone_off") or [])
    (keys.add if off else keys.discard)(file_key(name))
    s["phone_off"] = sorted(keys)
    return apply_phone_off(s)


def dyn_stack(s: dict, line_id: str) -> list:
    """A line's usable takes that are still free (not locked into a posted video)."""
    locked = locked_ids(s)
    return [t for t in stack(s, line_id) if t["id"] not in locked]


def mixing(s: dict) -> bool:
    return s["mix"] if s.get("mix") is not None else s.get("mix_auto", True)


def batch_of(s: dict) -> dict:
    """take id -> its footage batch (from its raw file)."""
    b = {x["id"]: int(x.get("batch") or 1) for x in s["sources"]}
    return {t["id"]: b.get(t["src"], 1) for t in s["takes"]}


def _recipes(s: dict, keep=None):
    """[(take ids, batch)] for the free videos, in order, plus (count, limit line).
    keep(take) filters takes (e.g. only some batches, to count what they'd make)."""
    rows = [(line, [t for t in dyn_stack(s, line["id"]) if keep is None or keep(t)]) for line in s["script"]]
    bo = batch_of(s)
    batches = sorted({bo[t["id"]] for _, st in rows for t in st}) or [1]
    groups = [None] if mixing(s) or len(batches) < 2 else batches
    out, limit = [], None
    for b in groups:
        rb = [(line, [t for t in st if b is None or bo[t["id"]] == b]) for line, st in rows]
        req = [len(st) for line, st in rb if not line.get("optional")]
        count = min(req) if req else max((len(st) for _, st in rb), default=0)
        if req and b == groups[-1]:
            limit = next(line["id"] for line, st in rb if not line.get("optional") and len(st) == count)
        for di in range(count):
            out.append(([st[di]["id"] for _, st in rb if di < len(st)], b))
    return out, limit


def videos(s: dict) -> dict:
    """How many finished videos there are, and what each one is made of.
    Posted videos are frozen as they were posted; the free takes stack into the
    other videos, which keep their numbers (posting video 2 leaves videos 1 and 3 as
    they are). Required lines cap the count; optional lines are left out of videos
    once their stack runs out."""
    frozen = posted_videos(s)
    recipes, limit = _recipes(s)
    dcount = len(recipes)
    vids, n, di = [], 1, 0
    while di < dcount or any(f >= n for f in frozen):
        if n in frozen:
            vids.append({"n": n, "takes": frozen[n], "skip": n in s["skip"], "posted": True})
        elif di < dcount:
            vids.append({"n": n, "takes": recipes[di][0], "skip": n in s["skip"], "di": di, "batch": recipes[di][1]})
            di += 1
        else:  # a gap below a posted video, with no free takes left to fill it
            vids.append({"n": n, "takes": [], "skip": True, "empty": True})
        n += 1
    return {"count": len(vids), "free": dcount, "limit_line": limit, "videos": vids}


def video_takes(s: dict, n: int) -> list:
    v = videos(s)["videos"][n - 1]
    by_id = {t["id"]: t for t in s["takes"]}
    return [by_id[i] for i in v["takes"]]


def renumber(s: dict, line_id: str):
    for i, t in enumerate(stack(s, line_id)):
        t["order"] = i


# ---------- cut-outs inside a take ----------

def take_cuts(t: dict) -> list:
    """The take's cut-outs clipped to its in/out, merged and sorted."""
    out = []
    for a, b in sorted((float(a), float(b)) for a, b in t.get("cuts") or []):
        a, b = max(a, t["in"]), min(b, t.get("_src_out", t["out"]))
        if b - a < 0.02:
            continue
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def speed(s: dict, t: dict) -> float:
    """How fast a take plays: its own speed if set, else the video's speed, times the auto
    pace (slow reads sped up toward style.pace.wps words a second, never slowed down)."""
    if t.get("speed"):
        return float(t["speed"])
    st = s["style"]
    sp = float(st.get("speed") or 1.0)
    pace = st.get("pace") or {}
    if pace.get("auto"):
        cuts = take_cuts(t)
        spoken = t["out"] - t["in"] - sum(b - a for a, b in cuts)
        n = sum(1 for w in t.get("words") or []
                if t["in"] <= (w[1] + w[2]) / 2 <= t["out"] and not any(a <= (w[1] + w[2]) / 2 < b for a, b in cuts))
        if n >= 3 and spoken > 0.3:
            want = float(pace.get("wps") or 5.0) / (n / spoken)
            sp *= min(float(pace.get("max") or 1.35), max(1.0, round(want * 20) / 20))
    return round(sp, 3)


def take_len(t: dict, s: dict = None) -> float:
    """Seconds the take lasts in the video (cut-outs dropped, sped up, plus its freeze)."""
    spd = speed(s, t) if s else float(t.get("_spd") or 1.0)
    return (t["out"] - t["in"] - sum(b - a for a, b in take_cuts(t))) / spd + float(t.get("freeze") or 0)


def take_rel(t: dict, x: float) -> float:
    """Seconds into the (cut) take at source time x."""
    r = (x - t["in"])
    spd = float(t.get("_spd") or 1.0)
    for a, b in take_cuts(t):
        if x >= b:
            r -= b - a
        elif x > a:
            r -= x - a
    return r / spd


def in_cut(t: dict, x: float) -> bool:
    return any(a <= x < b for a, b in take_cuts(t))


def next_batch(s: dict) -> int:
    """Batch for files being added now: the newest one if it hasn't been cut yet (files
    arriving together), else a new one (footage added to a shoot that's already cut)."""
    bs = [int(x.get("batch") or 1) for x in s["sources"]]
    if not bs:
        return 1
    top = max(bs)
    fresh = all(x.get("status") != "ready" for x in s["sources"] if int(x.get("batch") or 1) == top)
    return top if fresh else top + 1


def voice_for(s: dict, n: int):
    """The voiceover video n uses (None = the takes' own sound)."""
    vs = [v for v in s.get("voiceovers") or [] if v]
    return vs[(n - 1) % len(vs)] if vs else s.get("voiceover")


def vo_segments(vo: dict) -> list:
    """A voiceover is one stretch of a recording, or several joined ("segments": [...],
    e.g. the first half of the script from one take and the rest from another)."""
    return vo.get("segments") or [vo]


def vo_len(vo: dict) -> float:
    """Seconds the voiceover lasts (its cut-outs dropped, all its pieces)."""
    return sum(g["out"] - g["in"] - sum(min(b, g["out"]) - max(a, g["in"]) for a, b in g.get("cuts") or [] if b > a)
               for g in vo_segments(vo))


def vo_time(vo: dict, x: float) -> float:
    """Voiceover source time -> seconds into the voiceover (cut-outs dropped)."""
    r = x - vo["in"]
    for a, b in sorted(vo.get("cuts") or []):
        r -= max(0.0, min(x, b) - a) if x > a else 0.0
    return r


def trashed() -> dict:
    """{shoot id: its sheet row name (or title)} for every shoot moved to ads/_trash, so the spreadsheet sync
    removes their rows instead of making the shoots again (adcut/sheet.py, adcut/sheetdb.py)."""
    out = {}
    for f in (SHOOTS_DIR / "_trash").glob("*/shoot.json"):
        sid = f.parent.name.rsplit("-", 1)[0]
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        out[sid] = ((d.get("sheet") or {}).get("row") or d.get("title") or "").strip().lower()
    return out
