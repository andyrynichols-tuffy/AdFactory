"""The "Scripts & Links" spreadsheet in OneDrive: one row per upcoming shoot (Shoot | Link |
Script). The editor checks it every 30s (when it changes) and keeps a shoot per row: the
reference link, the script split into lines ([stage directions] go to the shoot's notes),
the product, and an inbox folder named after the shoot so footage dropped there lands in it.
A script the user edited in the editor is never overwritten from the sheet."""
import hashlib
import json
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from . import inbox, store

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
STATE = {"path": None, "mtime": None, "rows": 0, "error": None, "synced": None}
NAMES = ("scripts & links.xlsx", "scripts and links.xlsx")


def find() -> Path:
    """The sheet: config ad_sheet, else "Scripts & Links.xlsx" anywhere near the inbox."""
    cfg = json.loads(inbox.CONFIG_FILE.read_text(encoding="utf-8")) if inbox.CONFIG_FILE.exists() else {}
    if cfg.get("ad_sheet") and Path(cfg["ad_sheet"]).is_file():
        return Path(cfg["ad_sheet"])
    root = inbox.inbox_dir().parent
    found = []
    for d in (root, root / "Documents", inbox.inbox_dir()):
        if d.is_dir():
            for f in d.iterdir():
                n = f.name.lower()
                if f.suffix.lower() == ".xlsx" and "script" in n and "link" in n and not n.startswith("~$"):
                    found.append(f)
    return max(found, key=lambda f: f.stat().st_mtime) if found else None  # moved / renamed: still found


def rows(path: Path) -> list:
    """[{shoot, link, script}] from the first sheet (header row: Shoot / Link / Script)."""
    z = zipfile.ZipFile(path)
    ss = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", NS):
            ss.append("".join(t.text or "" for t in si.iter("{%s}t" % NS["m"])))
    sheet = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
    links = {}  # cell -> hyperlink target (a link shown as text)
    rel = "xl/worksheets/_rels/sheet1.xml.rels"
    if rel in z.namelist():
        targets = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read(rel))}
        hl = sheet.find("m:hyperlinks", NS)
        for h in (hl if hl is not None else []):
            links[h.get("ref")] = targets.get(h.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"))
    table = []
    for row in sheet.iter("{%s}row" % NS["m"]):
        cells = {}
        for c in row.findall("m:c", NS):
            col = re.sub(r"\d", "", c.get("r"))
            v, t, isv = c.find("m:v", NS), c.get("t"), c.find("m:is", NS)
            if t == "s" and v is not None:
                val = ss[int(v.text)]
            elif isv is not None:
                val = "".join(x.text or "" for x in isv.iter("{%s}t" % NS["m"]))
            else:
                val = v.text if v is not None else ""
            cells[col] = (val or "").strip() or (links.get(c.get("r")) or "")
        table.append(cells)
    if not table:
        return []
    head = {k: v.lower() for k, v in table[0].items()}
    col = lambda word, default: next((k for k, v in head.items() if word in v), default)
    cs, cl, ct = col("shoot", "A"), col("link", "B"), col("script", "C")
    out = []
    for r in table[1:]:
        name = re.sub(r"\s+", " ", r.get(cs, "")).strip()
        if name:
            out.append({"shoot": name, "link": r.get(cl, "").strip(), "script": r.get(ct, "").strip()})
    return out


def parse_script(text: str):
    """Script text -> (spoken lines, notes). [Bracketed] bits are directions, not lines;
    a sentence broken across rows is joined back up."""
    notes = [m.strip() for m in re.findall(r"\[([^\]]+)\]", text)]
    spoken = re.sub(r"\[[^\]]+\]", "\n", text).replace("”", '"').replace("“", '"').replace("’", "'")
    spoken = re.sub(r"\s*\n\s*", " ", spoken).strip()
    parts = re.split(r'(?<=[.!?])["”]?\s+(?=[A-Z"“\[])', spoken)
    lines = [p.strip(' "') for p in parts if p.strip(' "')]
    return lines, notes


def _sig(row) -> str:
    return hashlib.sha1(json.dumps([row["link"], row["script"]]).encode()).hexdigest()[:12]


def sync(start_process=None) -> dict:
    """Make/refresh a shoot per row. Returns STATE."""
    path = find()
    STATE["path"] = str(path) if path else None
    if not path:
        STATE["error"] = "no “Scripts & Links” spreadsheet found in OneDrive"
        return STATE
    mtime = path.stat().st_mtime
    if STATE["mtime"] == mtime:
        return STATE
    try:
        table = rows(path)
    except Exception as e:  # half-saved / locked by Excel: next pass retries
        STATE["error"] = f"couldn't read the spreadsheet yet: {e}"
        return STATE
    by_title = {r["title"].strip().lower(): r["id"] for r in store.shoots()}
    for r in store.shoots():  # a shoot remembers its row, so renaming it in the editor is fine
        row_name = (store.load(r["id"]).get("sheet") or {}).get("row")
        if row_name:
            by_title[row_name.strip().lower()] = r["id"]
    for row in table:
        sid = by_title.get(row["shoot"].lower())
        if not sid:
            sid = store.create(row["shoot"])
            by_title[row["shoot"].lower()] = sid
        lines, notes = parse_script(row["script"]) if row["script"] else ([], [])
        sig = _sig(row)
        changed = {"script": False}

        def fn(s, row=row, lines=lines, notes=notes, sig=sig):
            m = s.setdefault("sheet", {})
            if m.get("sig") == sig:
                return
            if row["link"]:
                s["reference"]["url"] = row["link"]
            if notes:
                s["reference"]["notes"] = "Directions from the script:\n" + "\n".join(f"• {n}" for n in notes)
            mine = [l["text"] for l in s["script"]]
            hand_edited = mine and mine != m.get("lines") and not s.get("script_guessed")
            if lines and not hand_edited:
                keep = {l["text"]: l for l in s["script"]}
                s["script"] = [keep.get(t) or {"id": store.new_id(), "text": t, "alts": [], "optional": False} for t in lines]
                s["script_guessed"] = False
                changed["script"] = True
            m.update(sig=sig, lines=[l["text"] for l in s["script"]], row=row["shoot"])
        s = store.update(sid, fn)
        inbox.folder_for(sid, s["title"])  # footage dropped in OneDrive/<inbox>/<shoot> goes to this shoot
        if changed["script"] and start_process and any(x["status"] == "ready" for x in s["sources"]):
            start_process(sid)  # footage is already in: re-match it against the new script
    STATE.update(mtime=mtime, rows=len(table), error=None, synced=__import__("time").time())
    return STATE
