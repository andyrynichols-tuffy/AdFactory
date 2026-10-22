"""The inbox: a folder (in iCloud Drive, later maybe Google Drive) that he drops raw
videos into from his phone or any computer. The editor watches it and pre-cuts
everything that lands there, so it's ready when he opens the editor.

  <inbox>/IMG_1234.MOV          -> its own shoot, named after the file
  <inbox>/Candle/clip1.mov ...  -> one shoot named "Candle" with every video in it
                                   (more files added later join that shoot)

A file is picked up once it has stopped growing (synced). It's copied to this PC
first (cloud files may only be placeholders until read), then Find takes runs."""
import json
import os
import shutil
import threading
import time
from pathlib import Path

from supercut.config import CFG, CONFIG_FILE
from supercut.ingest import VIDEO_EXTS

from . import store

LEDGER = store.AD_DATA / "inbox.json"  # what's been picked up: file key -> shoot
SETTLE = 20       # seconds a file must stay the same size before it's taken
_sizes = {}       # path -> (size, first seen at that size)
_lock = threading.Lock()
STATE = {"last_scan": None, "last_msg": "", "error": None}


def default_dir() -> Path:
    icloud = Path.home() / "iCloudDrive"
    if icloud.is_dir():
        return icloud / "Ad Factory Inbox"
    return store.OUTPUT_DIR / "Inbox"


def inbox_dir() -> Path:
    cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8")) if CONFIG_FILE.exists() else {}
    return Path(cfg.get("ad_inbox_dir") or CFG.get("ad_inbox_dir") or default_dir())


def set_inbox_dir(path: str) -> Path:
    cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8")) if CONFIG_FILE.exists() else {}
    cfg["ad_inbox_dir"] = str(Path(path))
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return inbox_dir()


def _ledger() -> dict:
    return json.loads(LEDGER.read_text(encoding="utf-8")) if LEDGER.exists() else {"files": {}, "folders": {}}


def _save_ledger(d: dict):
    LEDGER.write_text(json.dumps(d, indent=1), encoding="utf-8")


def _key(f: Path) -> str:
    st = f.stat()
    return f"{f.resolve()}|{st.st_size}"


def _settled(f: Path) -> bool:
    """Done syncing: same size for SETTLE seconds (and not empty)."""
    try:
        size = f.stat().st_size
    except OSError:
        return False
    now = time.time()
    prev = _sizes.get(str(f))
    if not prev or prev[0] != size:
        _sizes[str(f)] = (size, now)
        return False
    return size > 0 and now - prev[1] >= SETTLE


def _videos_in(folder: Path) -> list:
    return sorted(f for f in folder.iterdir() if f.is_file() and f.suffix.lower() in VIDEO_EXTS and not f.name.startswith("."))


def items() -> list:
    """What's in the inbox and where each thing stands."""
    root, led = inbox_dir(), _ledger()
    out = []
    if not root.is_dir():
        return out
    for e in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if e.name.startswith("."):
            continue
        files = [e] if e.is_file() and e.suffix.lower() in VIDEO_EXTS else _videos_in(e) if e.is_dir() else []
        if not files:
            continue
        done = [f for f in files if _safe_key(f) in led["files"]]
        shoot = (led["folders"].get(str(e.resolve())) if e.is_dir() else
                 led["files"].get(_safe_key(e), {}).get("shoot"))
        out.append({"name": e.name, "folder": e.is_dir(), "files": len(files), "done": len(done),
                    "shoot": shoot, "status": "done" if len(done) == len(files) else "waiting"})
    return out


def _safe_key(f: Path):
    try:
        return _key(f)
    except OSError:
        return None


def tick(start_process):
    """One pass: pick up settled new files and hand each shoot to start_process(sid)
    (the editor's Find takes job). Safe to call often."""
    if not _lock.acquire(blocking=False):
        return
    try:
        root = inbox_dir()
        STATE["last_scan"] = time.time()
        if not root.is_dir():
            root.mkdir(parents=True, exist_ok=True)
        led = _ledger()
        for e in sorted(root.iterdir(), key=lambda p: p.name.lower()):
            if e.name.startswith("."):
                continue
            if e.is_file() and e.suffix.lower() in VIDEO_EXTS:
                group, files = None, [e]
            elif e.is_dir():
                group, files = e, _videos_in(e)
            else:
                continue
            new = [f for f in files if _safe_key(f) and _safe_key(f) not in led["files"]]
            if not new or not all(_settled(f) for f in new):
                continue
            if group is not None and str(group.resolve()) in led["folders"] and store.path_for(led["folders"][str(group.resolve())]).exists():
                sid = led["folders"][str(group.resolve())]
            else:
                sid = store.create((group or e).stem if group is None else group.name)
                store.update(sid, lambda s: s.update(from_inbox=True))
                if group is not None:
                    led["folders"][str(group.resolve())] = sid
            dest_dir = store.UPLOAD_DIR / sid
            dest_dir.mkdir(parents=True, exist_ok=True)
            added = []
            for f in new:
                STATE["last_msg"] = f"copying {f.name} from the inbox"
                dest = dest_dir / f.name
                shutil.copy2(f, dest)  # reading it also makes the cloud download it
                added.append(dest)
                led["files"][_key(f)] = {"shoot": sid, "at": time.time()}

            def add(s):
                have = {x["file"] for x in s["sources"]}
                b = store.next_batch(s)
                for d in added:
                    if str(d) not in have:
                        s["sources"].append({"id": store.new_id(), "file": str(d), "name": d.name, "status": "new",
                                             "error": None, "batch": b})
            store.update(sid, add)
            _save_ledger(led)
            STATE["last_msg"] = f"pre-cutting {', '.join(f.name for f in new)}"
            start_process(sid)
        STATE["error"] = None
    except Exception as ex:  # shown on the home page; next tick retries
        STATE["error"] = str(ex)
    finally:
        _lock.release()


def open_folder():
    d = inbox_dir()
    d.mkdir(parents=True, exist_ok=True)
    os.startfile(d)
    return d


def folder_for(sid: str, title: str) -> Path:
    """The inbox folder whose videos go into this shoot (made and linked if it has none),
    so videos added to a shoot from the web land in the right OneDrive folder."""
    led = _ledger()
    for path, s in led["folders"].items():
        if s == sid and Path(path).is_dir():
            return Path(path)
    root = inbox_dir()
    root.mkdir(parents=True, exist_ok=True)
    base = "".join(c for c in (title or sid) if c not in '<>:"/\\|?*').strip(" .") or sid
    d, k = root / base, 2
    while d.exists() and str(d.resolve()) in led["folders"]:  # taken by another shoot
        d, k = root / f"{base} ({k})", k + 1
    d.mkdir(exist_ok=True)
    led["folders"][str(d.resolve())] = sid
    _save_ledger(led)
    return d
