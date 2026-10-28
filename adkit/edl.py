"""The edit file (projects/<name>/edit.json): single source of truth shared by
Claude, the editor app and the renderer."""
import copy
import json
import re
import uuid

from .config import PROJECTS_DIR

DEFAULT_STYLE = {
    "top_bg": "#000000",
    "mid_bg": "#000000",
    "bottom_bg": "#000000",
    # background: "blur" fills the frame with a blurred, darkened copy of the clip
    "background": {"mode": "blur", "darken": 0.35, "saturation": 1.35, "tint": "#000000"},
    # cut indicator between clips
    # card = optional title-card buffer between clips (montages), e.g.
    # {"episode": "gilmore-girls_s01e03", "in": 195.6, "dur": 0.5, "sfx": "lala", "sfx_volume": 0.8}
    # replaces the flash/whoosh at each cut; "volume" > 0 also keeps the card's own audio.
    "transition": {"flash": True, "sfx": "whoosh", "sfx_volume": 0.5, "card": None},
    "caption": {
        "preset": "box",  # box | meme | sticker | neon | news   (see caption.PRESETS)
        "font": "Arial Black", "size": 60, "color": "#000000", "outline": "#000000",
        "outline_w": 0, "uppercase": False, "y": 0.55, "box_color": "#FFFFFF",
        "accent": "#E0218A", "rotate": 0, "pop": True, "label": "BREAKING",
    },
    "subs": {
        "font": "Impact", "size": 84, "color": "#FFFFFF", "highlight": "#FFE14D",
        "outline": "#000000", "outline_w": 6, "uppercase": True, "y": 0.30,
        "words_per_line": 3, "karaoke": True, "pop": True,
    },
    "audio": {"loudness": -14},
}

DEFAULT_EDL = {
    "version": 1,
    "title": "",
    # post type: "single" (one clip), "montage" (several clips, optional title-card
    # buffer) or "ranking" (a countdown list in the top band). None = inferred.
    "kind": None,
    # source episodes picked when the post was created (the clips' episodes count too)
    "episodes": [],
    # ranking posts: {"title": "Ranking ...", "order": "down" | "up", "look": {style overrides}}
    # each clip is one entry; its label is clip.rank_label
    "ranking": None,
    "batch": None,      # group label in the editor's Projects list (None = inferred from name)
    "archived": False,  # hidden in the collapsed "Archived" group
    "starred": False,   # "Saved": user wants to post this one (Saved tab = posting queue)
    "posted": False,    # user has posted it to TikTok
    "posted_at": None,  # unix time it was marked posted
    # 👎 the user doesn't like it: re-edit it (dislike_note says why) or bin it. Disliked posts
    # leave the posting queue; Claude treats them as the first ones to fix.
    "disliked": False, "dislike_note": "", "disliked_at": None,
    # 👍 liked: "I like it, keep it for later", NOT in the posting queue (that's starred/Save)
    "liked": False, "liked_at": None,
    "deleted": False,   # in the recycle bin (restorable until emptied)
    "deleted_at": None,
    # TikTok description to copy/paste. desc_for = the caption the description was
    # written for; when the caption changes, desc_stale flags it for a rewrite.
    # desc_manual = the user wrote/edited it by hand, so it is never flagged.
    "post": {"description": "", "hashtags": "", "desc_for": None, "desc_stale": False, "desc_manual": False},
    "caption": "",
    "style": DEFAULT_STYLE,
    "clips": [],
}

CLIP_FIELDS = {
    "id": None, "episode": None, "in": 0.0, "out": 0.0,
    "caption": None,  # overrides global caption during this clip; *word* = emphasis
    "caption_style": None,  # optional partial override of style.caption, e.g. {"preset": "news"}
    "subs": None,     # None = auto from transcript; else [{start,end,text}] relative to in-point
    "zoom": 1.0, "pan_x": 0.5, "pan_y": 0.5, "speed": 1.0, "volume": 1.0,
    "transition": None,  # None = project cut effect before this clip; "none" = seamless continuation
    "sfx": None,         # [{"at": secs from in-point, "name": "boom", "volume": 0.8}]
    "rank_label": None,  # ranking posts: this entry's short label in the list
    "rank_context": None,  # ranking posts: one-line setup shown above the subtitles
    "marks": None,       # [secs from in-point] where style.counter ticks up (supercut tallies)
    "note": "",
}


def safe_name(name: str) -> str:
    n = re.sub(r"[^A-Za-z0-9 _-]+", "", name).strip().replace(" ", "-")
    if not n:
        raise ValueError("bad project name")
    return n


def path_for(name: str):
    return PROJECTS_DIR / safe_name(name) / "edit.json"


def deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        out[k] = deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def normalize(edl: dict) -> dict:
    edl = deep_merge(DEFAULT_EDL, edl)
    clips = []
    for c in edl["clips"]:
        c = {**CLIP_FIELDS, **c}
        c["id"] = c["id"] or uuid.uuid4().hex[:6]
        c["in"], c["out"] = float(c["in"]), float(c["out"])
        clips.append(c)
    edl["clips"] = clips
    edl["kind"] = post_kind(edl)
    if edl["kind"] == "ranking":
        edl["ranking"] = {**RANKING_DEFAULT, **(edl.get("ranking") or {})}
    post, cap = edl["post"], post_caption(edl)
    if post["description"] and post.get("desc_for") is None:
        post["desc_for"] = cap  # older posts: assume the description matches today's caption
    post["desc_stale"] = bool(post["description"]) and not post.get("desc_manual") and post["desc_for"] != cap
    return edl


KINDS = ("single", "montage", "ranking")
RANKING_DEFAULT = {"title": "", "order": "down", "look": {}}


def post_kind(edl: dict) -> str:
    k = edl.get("kind")
    if k in KINDS:
        return k
    if edl.get("ranking"):
        return "ranking"
    card = ((edl.get("style") or {}).get("transition") or {}).get("card") or {}
    return "montage" if card.get("episode") or len(edl.get("clips") or []) > 1 else "single"


def rank_numbers(edl: dict) -> list:
    """Rank shown for each clip: "down" counts N..1 (best last), "up" counts 1..N."""
    n = len(edl["clips"])
    down = (edl.get("ranking") or {}).get("order", "down") != "up"
    return [n - i if down else i + 1 for i in range(n)]


def ranking_style(edl: dict, upto: int, base: dict = None) -> dict:
    """Caption style for the ranking list while clip `upto` (0-based) plays: every entry
    played so far is revealed and the current one highlighted. upto = -1 shows the empty
    list (intro)."""
    from .caption import PRESETS
    r = edl.get("ranking") or {}
    ranks = rank_numbers(edl)
    labels = [""] * len(ranks)
    for c, k in zip(edl["clips"], ranks):
        labels[k - 1] = c.get("rank_label") or ""
    st = {**PRESETS["ranking"], **(r.get("look") or {}), "preset": "ranking", "items": labels,
          "now": ranks[upto] if 0 <= upto < len(ranks) else 0,
          "shown": sorted(ranks[:upto + 1]) if upto >= 0 else []}
    if base:
        st["pop"] = base.get("pop", True)
    return st


def context_for(edl: dict, clip: dict):
    """(text, style) of a ranking entry's setup line, or None."""
    if post_kind(edl) != "ranking" or not clip.get("rank_context"):
        return None
    look = {**(edl.get("ranking") or {}).get("look", {})}
    metal = look.get("metal") or []
    return clip["rank_context"], {"preset": "context", "font": look.get("label_font", "Arial Black"), "size": 46,
                                  "color": "#FFFFFF", "accent": metal[1] if len(metal) > 1 else look.get("accent", "#FFE14D"),
                                  "outline": look.get("outline", "#000000"), "outline_w": 3, "uppercase": False}


def caption_for(edl: dict, i: int, clip: dict) -> tuple:
    """(text, style) of the top band during clip i of edl["clips"] (one rule for the
    renderer, the editor preview and thumbnails)."""
    from .caption import effective_style
    if post_kind(edl) == "ranking":
        return (edl.get("ranking") or {}).get("title") or " ", ranking_style(edl, i)
    return (clip.get("caption") or edl["caption"]), effective_style(edl["style"]["caption"], clip.get("caption_style"))


def post_caption(edl: dict) -> str:
    """The caption a post shows (first clip caption, else the top-level caption)."""
    if edl.get("ranking") and post_kind(edl) == "ranking":
        return edl["ranking"].get("title") or ""
    return next((c["caption"] for c in edl["clips"] if c.get("caption")), edl.get("caption") or "")


def set_description(name: str, text: str) -> dict:
    """Write a fresh description for the post's current caption (clears the stale flag)."""
    e = load(name)
    e["post"]["description"] = text
    e["post"]["desc_for"] = post_caption(e)
    e["post"]["desc_manual"] = False
    return save(name, e)


def stale_descriptions() -> list:
    out = []
    for name in projects():
        e = load(name)
        if e["post"]["desc_stale"] and not e.get("archived") and not e.get("deleted"):
            c = e["clips"][0] if e["clips"] else {}
            out.append({"name": name, "caption": post_caption(e), "was_for": e["post"]["desc_for"],
                        "description": e["post"]["description"], "note": c.get("note", "")})
    return out


def load(name: str) -> dict:
    raw = json.loads(path_for(name).read_text(encoding="utf-8"))
    edl = normalize(raw)
    if any(not c.get("id") for c in raw.get("clips", [])):
        save(name, edl)  # persist newly assigned clip ids so they stay stable
    return edl


def save(name: str, edl: dict) -> dict:
    p = path_for(name)
    p.parent.mkdir(parents=True, exist_ok=True)
    edl = normalize(edl)
    p.write_text(json.dumps(edl, indent=2, ensure_ascii=False), encoding="utf-8")
    return edl


def create(name: str, title: str = "") -> dict:
    p = path_for(name)
    if p.exists():
        return load(name)
    return save(name, {"title": title or name})


def projects() -> list:
    return sorted(p.parent.name for p in PROJECTS_DIR.glob("*/edit.json"))


def infer_batch(name: str) -> str:
    """Fallback group for projects without an explicit batch: name minus its trailing
    -NN-slug, e.g. rhoslc-pol-03-climate -> rhoslc-pol."""
    m = re.match(r"(.+?)-\d{2}(?:-|$)", name)
    return m.group(1) if m else "supercuts"


# Projects = batches of drafted posts. Each post's edit.json names its project in
# "batch"; this manifest holds per-project metadata (tags describing humor/visual style).
MANIFEST = PROJECTS_DIR / "_projects.json"


def load_manifest() -> dict:
    if MANIFEST.exists():
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    return {}


def save_project_meta(batch: str, tags: list = None, note: str = None) -> dict:
    """Create or update a project's metadata (keeps its original creation time)."""
    import time
    m = load_manifest()
    meta = m.get(batch, {"created": time.time(), "tags": [], "note": ""})
    if tags is not None:
        meta["tags"] = tags
    if note is not None:
        meta["note"] = note
    m[batch] = meta
    MANIFEST.write_text(json.dumps(m, indent=2, ensure_ascii=False), encoding="utf-8")
    return meta


_summary_cache = {}  # post name -> (mtime, summary without render)


def project_summaries() -> list:
    """Metadata for the editor's grouped Projects list (unchanged posts come from a cache;
    the renders folder is listed once)."""
    from .config import RENDERS_DIR
    latest = {}
    for r in RENDERS_DIR.glob("*_2*.mp4"):  # timestamped final renders: <post>_YYYYMMDD-HHMMSS.mp4
        post = r.name.rsplit("_", 1)[0]
        if post not in latest or r.name > latest[post]:
            latest[post] = r.name
    out = []
    for p in PROJECTS_DIR.glob("*/edit.json"):
        name = p.parent.name
        st = p.stat()
        hit = _summary_cache.get(name)
        if hit and hit[0] == st.st_mtime:
            out.append({**hit[1], "render": f"/renders/{latest[name]}" if name in latest else None})
            continue
        try:
            e = load(name)
        except Exception:
            continue
        summary = {
            "description": (e.get("post") or {}).get("description", ""),
            "desc_stale": bool((e.get("post") or {}).get("desc_stale")),
            "name": p.parent.name, "title": e["title"] or p.parent.name,
            "batch": e.get("batch") or infer_batch(p.parent.name),
            "archived": bool(e.get("archived")),
            "starred": bool(e.get("starred")),
            "posted": bool(e.get("posted")), "posted_at": e.get("posted_at"),
            "disliked": bool(e.get("disliked")), "dislike_note": e.get("dislike_note") or "",
            "liked": bool(e.get("liked")),
            "deleted": bool(e.get("deleted")), "deleted_at": e.get("deleted_at"),
            "created": st.st_ctime, "mtime": st.st_mtime,
            "kind": e["kind"],
            "episodes": sorted({c["episode"] for c in e["clips"]} | set(e.get("episodes") or [])),
            "clips": len(e["clips"]), "duration": round(duration(e), 1),
            "caption": next((c["caption"] for c in e["clips"] if c.get("caption")), e["caption"]),
        }
        _summary_cache[name] = (st.st_mtime, summary)
        out.append({**summary, "render": f"/renders/{latest[name]}" if name in latest else None})
    return out


def check(edl: dict) -> list:
    """Return a list of problems (empty = OK)."""
    from . import library
    problems = []
    card = (edl["style"].get("transition") or {}).get("card") or {}
    if card.get("episode"):
        try:
            library.episode(card["episode"])
        except KeyError as e:
            problems.append(f"title card: {e}")
        from .sfx import LIBRARY as _lib
        if card.get("sfx") and card["sfx"] not in _lib:
            problems.append(f"title card: unknown sfx '{card['sfx']}'")
    for i, c in enumerate(edl["clips"], 1):
        try:
            ep = library.episode(c["episode"])
        except KeyError as e:
            problems.append(f"clip {i}: {e}")
            continue
        if not (0 <= c["in"] < c["out"] <= ep["duration"] + 0.1):
            problems.append(f"clip {i}: bad range {c['in']}-{c['out']} (episode is {ep['duration']:.1f}s)")
        if c["out"] - c["in"] > 20:
            problems.append(f"clip {i}: {c['out'] - c['in']:.1f}s long; too long for a supercut?")
        if not 0.5 <= c["speed"] <= 2:
            problems.append(f"clip {i}: speed must be 0.5-2")
        from .sfx import LIBRARY
        for cue in c.get("sfx") or []:
            if cue.get("name") not in LIBRARY:
                problems.append(f"clip {i}: unknown sfx '{cue.get('name')}' (have: {', '.join(LIBRARY)})")
    return problems


def timeline(edl: dict) -> list:
    """The clips as rendered: with a title-card segment inserted before every clip that
    isn't a seamless continuation, when the project has a card buffer set."""
    card = (edl["style"].get("transition") or {}).get("card") or {}
    if not card.get("episode"):
        return edl["clips"]
    out = []
    for i, c in enumerate(edl["clips"]):
        if i and c.get("transition") != "none":
            t0, dur = float(card.get("in", 0)), float(card.get("dur", 0.5))
            fade = min(float(card.get("fade", 0.12)), dur / 2)
            out.append({**CLIP_FIELDS, "id": f"card{i}", "card": True, "fade": fade, "episode": card["episode"],
                        "in": t0, "out": t0 + dur,
                        "zoom": float(card.get("zoom", 1.0)), "volume": float(card.get("volume", 0.0)),
                        "subs": [], "transition": "none",
                        "sfx": [{"at": float(card.get("sound_offset", 0.033)), "name": card["sfx"],
                                 "volume": float(card.get("sfx_volume", 0.8)),
                                 "dur": dur - float(card.get("sound_offset", 0.033)), "fade": fade}]
                        if card.get("sfx") else None})
            c = {**c, "transition": "none"}  # the card replaces the flash/whoosh
        out.append(c)
    return out


def duration(edl: dict) -> float:
    return sum((c["out"] - c["in"]) / c["speed"] for c in timeline(edl))
