"""Script builder: paste a TikTok link, get its script and shot list, with the product-specific
bits marked so the same script works for another product.

Local: the video is downloaded (yt-dlp) into AD_DATA/refs/<id>/, transcribed on this PC
(faster-whisper, like raw footage), cut into shots where the picture cuts (ffmpeg scene
detection, a still per shot), and the product details are guessed by rules (names the video
keeps saying, prices, deals, sizes, materials, product words). A library script keeps the
lines, the marks and the shots; its text is the template ({product}, {price}, {feature 1}…).
AI (✨, adcut/ai.py) is only used when asked: find the details, describe the shots, fill in
the blanks for another product, rewrite the script in another tone."""
import hashlib
import json
import re
import subprocess
import threading
import time
import uuid
from datetime import date

from supercut.config import FFMPEG
from supercut.ingest import probe

from . import ai, shop, store

REFS = store.AD_DATA / "refs"
JOBS = {}
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _job(kind, work) -> dict:
    jid = uuid.uuid4().hex[:8]
    job = JOBS[jid] = {"id": jid, "kind": kind, "state": "running", "msg": "starting…", "result": None,
                       "error": None, "started": time.time()}

    def run():
        try:
            job["result"] = work(job)
            job["state"] = "done"
        except Exception as e:  # shown in the app
            job.update(state="error", error=str(e)[:400])
    threading.Thread(target=run, daemon=True, name=f"script-{kind}").start()
    return job


def busy() -> list:
    return [j["kind"] for j in JOBS.values() if j["state"] == "running"]


# ---------------------------------------------------------------- the video

def _direct(url: str, folder):
    """The way the Analytics page reader sees TikTok: the public page names the video file,
    which downloads with that page's cookies."""
    import http.cookiejar
    import urllib.request
    from supercut import analytics
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    hdr = {"User-Agent": analytics.UA, "Accept-Language": "en-US,en;q=0.9", "Referer": "https://www.tiktok.com/"}
    r = op.open(urllib.request.Request(url, headers=hdr), timeout=30)
    final, html = r.geturl(), r.read().decode("utf-8", "replace")
    item = analytics._scope(html).get("webapp.video-detail", {}).get("itemInfo", {}).get("itemStruct", {})
    v = item.get("video") or {}
    urls = [v.get("playAddr"), v.get("downloadAddr")] + [
        u for b in v.get("bitrateInfo") or [] for u in (b.get("PlayAddr") or {}).get("UrlList") or []]
    for u in [u for u in urls if u]:
        try:
            data = op.open(urllib.request.Request(u, headers={**hdr, "Range": "bytes=0-"}), timeout=90).read()
        except Exception:
            continue
        if len(data) > 50_000:
            f = folder / "video.mp4"
            f.write_bytes(data)
            m = analytics.VIDEO_RX.search(final) or analytics.VIDEO_RX.search(url)
            author = item.get("author") or {}
            return f, {"video_id": str(item.get("id") or ""), "author": author.get("nickname") or "",
                       "handle": author.get("uniqueId") or (m.group(1) if m else ""), "desc": item.get("desc") or "",
                       "url": f"https://www.tiktok.com/@{author.get('uniqueId') or (m.group(1) if m else '')}/video/{item.get('id')}"
                       if item.get("id") else final}
    raise RuntimeError("TikTok didn't hand over the video file")


def download(url: str, folder):
    """The video + what TikTok says about it (direct first, yt-dlp if that fails)."""
    folder.mkdir(parents=True, exist_ok=True)
    try:
        return _direct(url, folder)
    except Exception as first:
        try:
            import yt_dlp
        except ImportError:
            raise RuntimeError(f"couldn't download that video ({first})")
    opts = {"outtmpl": str(folder / "video.%(ext)s"), "format": "b[ext=mp4]/b", "quiet": True, "no_warnings": True,
            "noplaylist": True, "ffmpeg_location": str(FFMPEG), "overwrites": True}
    try:
        with yt_dlp.YoutubeDL(opts) as y:
            info = y.extract_info(url, download=True)
    except Exception as e:
        raise RuntimeError("couldn't download that video (is it public?)") from e
    f = next((p for p in folder.glob("video.*") if p.suffix != ".part"), None)
    if not f:
        raise RuntimeError("couldn't download that video (is it public?)")
    return f, {"video_id": str(info.get("id") or ""), "author": info.get("uploader") or info.get("creator") or "",
               "handle": info.get("uploader_id") or "", "desc": info.get("description") or info.get("title") or "",
               "url": info.get("webpage_url") or url}


def find_cuts(path, dur, threshold=0.28) -> list:
    """Shot boundaries [(start, end)] where the picture cuts."""
    out = subprocess.run([str(FFMPEG), "-hide_banner", "-nostats", "-i", str(path), "-an", "-vf",
                          f"select='gt(scene,{threshold})',showinfo", "-f", "null", "-"],
                         capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW).stderr
    cuts = []
    for m in re.finditer(r"pts_time:([\d.]+)", out):
        t = float(m.group(1))
        if 0.4 < t < dur - 0.3 and (not cuts or t - cuts[-1] >= 0.5):
            cuts.append(round(t, 2))
    b = [0.0] + cuts + [round(dur, 2)]
    return list(zip(b, b[1:]))


def still(path, t, dst):
    subprocess.run([str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{t:.2f}", "-i", str(path),
                    "-frames:v", "1", "-vf", "scale=360:-2", "-q:v", "4", str(dst)], creationflags=NO_WINDOW)


def to_lines(words, cuts=()) -> list:
    """Words -> spoken lines: a sentence, a long pause or a cut in the picture ends a line
    (TikTok scripts are written shot by shot)."""
    lines, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        cut = nxt and any(w[2] - 0.1 <= c <= nxt[1] + 0.15 for c in cuts)
        end = w[0][-1:] in ".!?" or (nxt and nxt[1] - w[2] > 0.7) or cut or len(cur) >= 22 or not nxt
        if end:
            lines.append({"text": " ".join(x[0] for x in cur).replace(" ,", ","), "t0": cur[0][1], "t1": cur[-1][2]})
            cur = []
    out = []  # a word or two cut off from its sentence ("But" / "And") joins the next line
    for l in lines:
        if out and len(out[-1]["text"].split()) < 3 and out[-1]["text"][-1:] not in ".!?":
            out[-1] = {"text": out[-1]["text"] + " " + l["text"], "t0": out[-1]["t0"], "t1": l["t1"]}
        else:
            out.append(l)
    if len(out) > 1 and len(out[-1]["text"].split()) < 3:  # ...and a last word or two joins the line before
        out[-2:] = [{"text": out[-2]["text"] + " " + out[-1]["text"], "t0": out[-2]["t0"], "t1": out[-1]["t1"]}]
    return out


# ---------------------------------------------------------------- guessing the product details

SKIP_CAPS = {"i", "i'm", "i've", "i'd", "i'll", "ok", "okay", "tiktok", "god", "oh", "yes", "no", "so", "and", "but",
             "the", "this", "that", "it", "it's", "you", "your", "you're", "we", "my", "they", "if", "a", "like",
             "amazon", "target", "walmart", "mr", "mrs", "ms", "usa", "us", "america", "american", "christmas",
             "halloween", "thanksgiving", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}
# everyday words that only have a capital because a sentence starts with them
COMMON = set("""because when what why how wait stop then now here there just also even every everyone don't let's look
show apply camera okay ok so and but or if once after before while since until though although yes no hey hi guys
you're it's that's this these those they we our my your his her their its one two three first next last finally
today tonight tomorrow listen honestly literally seriously obviously plus also again still only really very super
get got go going make made take put use try tap click grab run buy shop check see watch let give keep turn add hold
fill brush blend rub open close pull push pour wash dry wear pick""".split())
GENERIC_TAGS = {"fyp", "foryou", "foryoupage", "tiktokshop", "tiktokmademebuyit", "viral", "tiktokshopfinds", "ad",
                "sponsored", "musthave", "giftideas", "deals", "sale", "fy", "trending", "creatorsearchinsights"}
FEATURES = ["water-resistant", "water resistant", "waterproof", "sweat-resistant", "sweat resistant", "sweatproof",
            "smudge-proof", "long-lasting", "long lasting", "cordless", "rechargeable", "wireless", "flameless",
            "leak-proof", "leakproof", "stainless steel", "organic", "vegan", "cruelty-free", "unscented", "flushable",
            "non-toxic", "hypoallergenic", "adjustable", "foldable", "portable", "machine washable", "wrinkle-free",
            "breathable", "stretchy", "high-waisted", "high waisted", "relaxed fit", "slim fit", "oversized",
            "lightweight", "heavyweight", "insulated", "noise-cancelling", "noise cancelling", "dishwasher safe",
            "100% cotton", "cotton", "linen", "waffle", "fleece", "denim", "leather", "silicone", "ceramic", "bamboo",
            "super thin tip", "thin tip", "brush", "aroma diffuser", "diffuser"]
ITEMS = ["eyebrow pencil", "eyebrow pen", "brow pencil", "pencil", "wipes", "candle", "shirt", "t-shirt", "tee",
         "henley", "thermals", "thermal", "pants", "sweatpants", "joggers", "cardigan", "flannel", "beanie", "boots",
         "sandals", "pajamas", "robe", "boxers", "jeans", "shorts", "dress", "leggings", "hoodie", "sweater", "sweatshirt", "jacket",
         "shoes", "sneakers", "slippers", "socks", "bag", "backpack", "bottle", "water bottle", "tumbler", "mug",
         "serum", "cream", "lotion", "moisturizer", "cleanser", "shampoo", "conditioner", "mascara", "lipstick",
         "lip oil", "lip gloss", "foundation", "concealer", "sunscreen", "perfume", "cologne", "deodorant", "charger",
         "phone case", "lamp", "vacuum", "organizer", "pillow", "blanket", "sheets", "towel", "pan",
         "knife", "board game", "card game", "toy", "gummies", "supplement", "vitamins", "protein", "tea", "coffee", "pen"]
RULES = [
    ("price", r"\$\s?\d[\d,]*(?:\.\d{2})?|\b\d+(?:\.\d{2})?\s?(?:dollars|bucks)\b"),
    ("deal", r"\b\d{1,3}\s?(?:%|percent)\s?off\b|\bbuy one,? get one(?: free)?\b|\bBOGO\b|\bfree shipping\b|\bon sale\b"),
    ("spec", r"\b\d+(?:\.\d+)?\s?(?:oz|ounces?|ml|liters?|inch(?:es)?|ft|feet|lbs?|pounds?|pack|count|pcs|pieces?|"
             r"colors?|scents?|shades?|hours?|mah|watts?)\b"),
]


def _cap_runs(text):
    """Runs of Capitalized / CamelCase words (names). A lone capital at the start of a sentence
    doesn't count ("Stop", "This"); two capitals in a row or CamelCase do ("Old Navy", "MenPen")."""
    out = []
    for m in re.finditer(r"[A-Z][\w'&-]*(?:\s+[A-Z][\w'&-]*)*", text):
        spans = [(x.start() + m.start(), x.end() + m.start()) for x in re.finditer(r"\S+", m.group(0))]
        before = text[:m.start()].rstrip()
        at_start = not before or before[-1] in ".!?\"“:[("
        word = lambda s: text[s[0]:s[1]].lower().strip(".,!?:;\"”'")
        raw = lambda s: text[s[0]:s[1]].strip(".,!?:;\"”'")
        spans = [s for s in spans if not (len(raw(s)) > 1 and raw(s).isupper())] if all(
            len(raw(s)) > 1 and raw(s).isupper() for s in spans) else spans  # ALL-CAPS = emphasis, not a name
        if at_start and spans and word(spans[0]) in COMMON:
            spans, at_start = spans[1:], False
        while spans and word(spans[0]).removesuffix("'s") in SKIP_CAPS:
            spans, at_start = spans[1:], False
        while spans and word(spans[-1]).removesuffix("'s") in SKIP_CAPS:
            spans = spans[:-1]
        if not spans or (at_start and len(spans) == 1 and not re.search(r"[a-z][A-Z]", text[spans[0][0]:spans[0][1]])):
            continue
        a, b = spans[0][0], spans[-1][1]
        while b > a and text[b - 1] in ".,!?:;\"”'":
            b -= 1
        if text[b - 2:b] == "'s":
            b -= 2
        if b - a > 1:
            out.append((a, b, text[a:b]))
    return out


def guess_marks(lines, desc="") -> list:
    """[{line, a, b, slot}] for the bits that belong to this product."""
    tags = {t.lower() for t in re.findall(r"#(\w+)", desc or "")} - GENERIC_TAGS
    desc_words = set(re.findall(r"[a-z]{4,}", re.sub(r"#\w+", "", (desc or "").lower())))
    found = []  # (line, a, b, kind, text)
    counts = {}
    d = shop.load()
    known = {p["name"].lower() for p in d["products"]} | {p["brand"].lower() for p in d["products"] if p.get("brand")}
    item_words = {w.split()[-1].rstrip("s") for w in ITEMS}
    for i, l in enumerate(lines):
        text = re.sub(r"\[[^\]]*\]", lambda m: " " * len(m.group(0)), l["text"])  # [directions] aren't said
        names = [(a, b, ph, "name") for a, b, ph in _cap_runs(text)]
        ws = list(re.finditer(r"[\w'&-]+", text))
        for n in (3, 2, 1):  # names from the caption's hashtags, said in lowercase ("dude wipes" = #dudewipes)
            for k in range(len(ws) - n + 1):
                a, b = ws[k].start(), ws[k + n - 1].end()
                if re.sub(r"\W", "", text[a:b].lower()) in tags and not any(a < y and b > x for x, y, *_ in names):
                    low = text[a:b].lower()
                    # a lowercase hashtag that names a kind of thing ("baggy sweatpants") is the item, not a brand
                    kind = "item" if low not in known and low.split()[-1].rstrip("s") in item_words else "name"
                    names.append((a, b, text[a:b], kind))
        for a, b, ph, kind in names:
            found.append((i, a, b, kind, ph))
            if kind == "name":
                counts[ph.lower()] = counts.get(ph.lower(), 0) + 1
    names = sorted({f[4].lower() for f in found if f[3] == "name"},
                   key=lambda n: -(counts[n] + 3 * (n.replace(" ", "") in tags) + (n in desc_words)))
    known_products = {p["name"].lower() for p in d["products"]}
    known_brands = {p["brand"].lower() for p in d["products"] if p.get("brand")}

    def kind(n):  # a name we know, or "… by <name>", says which it is
        if n in known_products:
            return "product"
        if n in known_brands or any(re.search(r"\bby\s+" + re.escape(n) + r"\b", l["text"], re.I) for l in lines):
            return "brand"
        return None
    name_slot, used = {}, set()
    for n in sorted(names, key=lambda n: kind(n) is None):
        k = kind(n) or ("product" if "product" not in used else "brand" if "brand" not in used else None)
        name_slot[n] = k if k and k not in used else f"name {len(name_slot) + 1}"
        used.add(name_slot[n])
    for i, l in enumerate(lines):
        said = re.sub(r"\[[^\]]*\]", lambda m: " " * len(m.group(0)), l["text"])
        low = said.lower()
        for slot, rx in RULES:
            for m in re.finditer(rx, said, re.I):
                found.append((i, m.start(), m.end(), slot, m.group(0)))
        for kind, words in (("feature", FEATURES), ("item", ITEMS)):
            for w in sorted(words, key=len, reverse=True):
                for m in re.finditer(r"(?<![\w-])" + re.escape(w) + r"s?(?![\w-])", low):
                    found.append((i, m.start(), m.end(), kind, l["text"][m.start():m.end()]))
    marks, taken, slot_of = [], {}, {}
    order = {"name": 0, "price": 1, "deal": 1, "spec": 2, "feature": 3, "item": 4}
    for i, a, b, kind, txt in sorted(found, key=lambda f: (order[f[3]], -(f[2] - f[1]), f[0], f[1])):
        if any(a < y and b > x for x, y in taken.get(i, [])):
            continue
        key = txt.lower().rstrip("s") if kind == "item" else txt.lower()
        if kind == "name":
            slot = name_slot[txt.lower()]
        elif key in slot_of:
            slot = slot_of[key]
        else:
            same = [s for s in slot_of.values() if s.startswith(kind)]
            slot = kind if kind in ("price", "deal", "item") and not same else f"{kind} {len(same) + 1}"
        slot_of[key] = slot
        taken.setdefault(i, []).append((a, b))
        marks.append({"line": i, "a": a, "b": b, "slot": slot})
    return sorted(marks, key=lambda m: (m["line"], m["a"]))


def compile_text(lines, marks) -> str:
    """The template: each marked bit becomes {its slot}."""
    out = []
    for i, l in enumerate(lines):
        t, pos, s = l["text"], 0, ""
        for m in sorted((m for m in marks if m["line"] == i), key=lambda m: m["a"]):
            if m["a"] < pos:
                continue
            s += t[pos:m["a"]] + "{" + m["slot"] + "}"
            pos = m["b"]
        out.append(s + t[pos:])
    return "\n".join(out)


def originals(lines, marks) -> dict:
    """{slot: what the original video said}"""
    out = {}
    for m in marks:
        out.setdefault(m["slot"], lines[m["line"]]["text"][m["a"]:m["b"]])
    return out


def reconcile(s) -> dict:
    """Lines + marks that match the script's text. Scripts typed in (or edited in the sheet or
    rewritten) get them from their {placeholders}: each one shows what it said before."""
    lines, marks = s.get("lines") or [], s.get("marks") or []
    if lines and compile_text(lines, marks) == s["text"]:
        return s
    orig = originals(lines, marks)
    old = {l["text"]: l for l in lines}
    new_lines, new_marks = [], []
    for raw in [x for x in (s["text"] or "").split("\n") if x.strip()]:
        out, pos = "", 0
        for m in shop.PH_RX.finditer(raw):
            out += raw[pos:m.start()]
            slot = m.group(1).strip().lower()
            a = len(out)
            out += orig.get(slot) or "{" + slot + "}"
            new_marks.append({"line": len(new_lines), "a": a, "b": len(out), "slot": slot})
            pos = m.end()
        out += raw[pos:]
        was = old.get(out) or {}
        new_lines.append({"text": out, "t0": was.get("t0"), "t1": was.get("t1")})
    return {**s, "lines": new_lines, "marks": new_marks}


# ---------------------------------------------------------------- link -> library script

def from_link(url: str, title: str = "") -> dict:
    def work(job):
        rid = hashlib.sha1(url.strip().encode()).hexdigest()[:10]
        folder = REFS / rid
        job["msg"] = "downloading the video…"
        if (folder / "meta.json").exists() and (folder / "video.mp4").exists():  # pasted before: reuse it
            f, meta = folder / "video.mp4", json.loads((folder / "meta.json").read_text(encoding="utf-8"))
        else:
            f, meta = download(url.strip(), folder)
        rid2 = meta["video_id"] or rid
        same = next((x for x in shop.load()["scripts"] if rid2 and (x.get("source") or {}).get("video_id") == rid2), None)
        if same:  # this video was made into a script already: that one (its marks and edits are kept)
            return {"script": same["id"], "reused": True}
        dur = probe(f)["duration"]
        job["msg"] = "listening to it (transcribing)…"
        wfile = folder / "words.json"
        if wfile.exists():
            words = json.loads(wfile.read_text(encoding="utf-8"))
        else:
            from .takes import transcribe_words
            words = transcribe_words(f, lambda m: job.update(msg=f"transcribing… {m.split(': ', 1)[-1]}"))
            wfile.write_text(json.dumps(words), encoding="utf-8")
        job["msg"] = "finding the shots…"
        spans = find_cuts(f, dur)
        lines = to_lines(words, [a for a, _ in spans[1:]])
        shots = []
        for k, (a, b) in enumerate(spans):
            still(f, (a + b) / 2, folder / f"shot{k}.jpg")
            said = " ".join(w[0] for w in words if a <= (w[1] + w[2]) / 2 < b)
            shots.append({"t0": a, "t1": b, "said": said, "desc": "", "img": f"shot{k}.jpg"})
        marks = guess_marks(lines, meta["desc"])
        try:
            from . import productlink
            tagged = productlink.video_products(meta["url"])
        except Exception:
            tagged = []
        mine = next((m for m in (productlink.match({"product_id": x["product_id"], "name": x["title"]}, shop.load()["products"])
                                 for x in tagged) if m), None) if tagged else None
        (folder / "meta.json").write_text(json.dumps({**meta, "duration": dur, "file": f.name}, ensure_ascii=False), encoding="utf-8")
        name = title.strip() or (f"@{meta['handle']}" if meta["handle"] else "TikTok") + f" · {date.today().strftime('%b %d').replace(' 0', ' ')}"
        rec = shop.upsert("scripts", {
            "title": name, "text": compile_text(lines, marks), "lines": lines, "marks": marks, "shots": shots,
            "source": {"ref": folder.name, "url": meta["url"], "video_id": rid2, "author": meta["author"],
                       "handle": meta["handle"], "desc": meta["desc"], "duration": dur, "products": tagged},
            "product": mine,
            "notes": f"From {meta['url']}"})
        return {"script": rec["id"]}
    return _job("from-link", work)


def save_marks(sid: str, body: dict) -> dict:
    d = shop.load()
    s = shop.by_id(d, "scripts", sid)
    if not s:
        raise KeyError(sid)
    lines = body.get("lines", s.get("lines") or [])
    marks = [m for m in body.get("marks", s.get("marks") or []) if 0 <= m["line"] < len(lines) and m["a"] < m["b"]]
    patch = {"id": sid, "lines": lines, "marks": marks, "text": compile_text(lines, marks)}
    for k in ("shots", "title", "tags", "notes"):
        if k in body:
            patch[k] = body[k]
    return shop.upsert("scripts", patch)


def products_by_delivery(d=None):
    """Products, most recently delivered (else ordered) first, then the rest, newest first.
    Returns (products, {product id: that date})."""
    d = d or shop.load()
    last = {}
    for o in d["orders"]:
        t = o.get("delivered") or o.get("ordered") or ""
        if t and t > last.get(o["product"], ""):
            last[o["product"]] = t
    ps = [p for p in d["products"] if not p.get("archived")]
    dated = sorted((p for p in ps if p["id"] in last), key=lambda p: last[p["id"]], reverse=True)
    rest = sorted((p for p in ps if p["id"] not in last), key=lambda p: -(p.get("created") or 0))
    return dated + rest, last


# ---------------------------------------------------------------- ✨ AI (only when asked)

def _script_for_ai(s) -> str:
    return "\n".join(f"{i + 1}. {l['text']}" for i, l in enumerate(s.get("lines") or []))


def ai_marks(sid: str) -> dict:
    def work(job):
        s = shop.by_id(shop.load(), "scripts", sid)
        job["msg"] = "✨ asking Claude which bits are about the product…"
        out = ai.ask_json(
            "This is the transcript of a TikTok Shop ad, one numbered line each:\n\n" + _script_for_ai(s) +
            (f"\n\nThe video's caption: {s['source'].get('desc')}" if (s.get("source") or {}).get("desc") else "") +
            "\n\nMark every exact piece of text that is specific to THIS product (its name, brand, product type, "
            "features, materials, sizes, prices, deals, colors/scents, claims only this product makes), so the script "
            "could be reused for a different product by swapping just those pieces. Give each piece a short slot name "
            "(product, brand, item, price, deal, feature 1, feature 2, spec 1…; the same thing gets the same slot). "
            'JSON: [{"line": <line number>, "text": "<exact text from that line>", "slot": "<slot>"}]')
        lines, marks = s["lines"], []
        for m in out:
            i = int(m["line"]) - 1
            if not (0 <= i < len(lines)) or not m.get("text"):
                continue
            a = lines[i]["text"].find(m["text"])
            if a < 0:
                a = lines[i]["text"].lower().find(m["text"].lower())
            if a >= 0 and not any(x["line"] == i and a < x["b"] and a + len(m["text"]) > x["a"] for x in marks):
                marks.append({"line": i, "a": a, "b": a + len(m["text"]), "slot": str(m.get("slot") or "detail").strip().lower()})
        return {"marks": sorted(marks, key=lambda m: (m["line"], m["a"]))}
    return _job("ai-marks", work)


def ai_describe(sid: str) -> dict:
    def work(job):
        s = shop.by_id(shop.load(), "scripts", sid)
        folder = REFS / s["source"]["ref"]
        job["msg"] = "✨ asking Claude to describe each shot…"
        listing = "\n".join(f"Shot {k + 1} ({x['t0']:.1f}-{x['t1']:.1f}s), still: {x['img']}, said: {x['said'] or '(nothing)'}"
                            for k, x in enumerate(s["shots"]))
        out = ai.ask_json(
            "These are the shots of a TikTok Shop ad (a still from the middle of each is in this folder):\n" + listing +
            "\n\nLook at each still and write a short shot-list entry a creator could film from: framing (close-up, "
            "selfie, hands only…), what the person does with the product, and any on-screen text. One line each. "
            'JSON: [{"shot": <number>, "desc": "..."}]', cwd=folder, tools=("Read",), timeout=420)
        shots = s["shots"]
        for x in out:
            k = int(x["shot"]) - 1
            if 0 <= k < len(shots):
                shots[k]["desc"] = str(x.get("desc") or "").strip()
        shop.upsert("scripts", {"id": sid, "shots": shots})
        return {"shots": shots}
    return _job("ai-describe", work)


def ai_fill(sid: str, pid: str, known: dict) -> dict:
    def work(job):
        d = shop.load()
        s, p = shop.by_id(d, "scripts", sid), shop.by_id(d, "products", pid)
        orig = originals(s.get("lines") or [], s.get("marks") or []) or {k: "" for k in shop.placeholders(s["text"])}
        todo = [k for k in orig if not known.get(k)]
        job["msg"] = f"✨ asking Claude to fill in the script for {p['name']}…"
        info = "; ".join(f"{k}: {v}" for k, v in {"name": p["name"], "brand": p["brand"], "category": p["category"],
                                                    "price": p["price"], "notes": p["notes"], **(p.get("fills") or {})}.items() if v)
        out = ai.ask_json(
            "A TikTok Shop script template:\n\n" + s["text"] + "\n\nWhat each blank said for the original product:\n" +
            "\n".join(f"{{{k}}} = {v}" for k, v in orig.items()) + f"\n\nThe new product: {info}\n" +
            ("Already filled: " + "; ".join(f"{{{k}}} = {v}" for k, v in known.items() if v) + "\n" if any(known.values()) else "") +
            "\nWrite what each remaining blank should say for the new product, the same length and style as the "
            "original, only true-sounding claims a product like this would make (no medical claims), US English. "
            f"Blanks to fill: {', '.join(todo)}. JSON object: {{\"<blank>\": \"<text>\"}}")
        return {"fills": {k: str(v) for k, v in out.items() if k in todo}}
    return _job("ai-fill", work)


def ai_rewrite(text: str, how: str) -> dict:
    def work(job):
        job["msg"] = "✨ asking Claude to rewrite it…"
        out = ai.ask(
            "Rewrite this TikTok Shop video script " + how.strip() + ".\n\n" + text +
            "\n\nRules: keep it about as long (it's a short video), one spoken line per line, keep every {placeholder} "
            "exactly as written (they're filled in later), keep [stage directions] in brackets, US English, TikTok Shop "
            "safe (no medical or guaranteed-result claims, no profanity). Answer with only the new script.")
        out = re.sub(r"^```\w*\n?|```$", "", out.strip()).strip()
        return {"text": out}
    return _job("ai-rewrite", work)
