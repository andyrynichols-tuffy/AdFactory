"""Ask Claude from the editor: requests queue up in projects/_requests.json and a worker
runs each one through the Claude Code CLI (`claude -p`) in this repo, one at a time.
The run follows CLAUDE.md like an interactive session would; it may write posts, run
checks and render, but never commits, deletes or posts anywhere."""
import json
import os
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path

from . import edl as edlmod
from .config import PROJECTS_DIR

ROOT = Path(__file__).resolve().parents[1]
FILE = PROJECTS_DIR / "_requests.json"
LOCK = threading.Lock()
WAKE = threading.Event()
PROCS = {}  # request id -> running Popen

PROMPT = """You are working in the Meme Factory repo (read CLAUDE.md first and follow it,
including the episode notes, voice and style rules, and the user's saved preferences).
The user sent this request from the editor's "Ask Claude" box:

---
{text}
---
{context}
Do the work end to end: find the moments, write the posts (edit.json) in a sensible
project with tags, run `check`, and fix problems. Rendering is optional (only if asked).
Rules for this unattended run: never run git, never delete or overwrite the user's
existing posts unless the request says to, never post or upload anything, never install
software. Finish with a short plain-text summary for the user: what you made (post names
and one line each), anything you couldn't find, and anything they should check by eye."""

ALLOWED = ["Read", "Write", "Edit", "Glob", "Grep", "TodoWrite",
           "Bash(.venv/Scripts/python.exe:*)", "Bash(.venv\\Scripts\\python.exe:*)",
           "Bash(ls:*)", "Bash(cat:*)", "Bash(grep:*)", "Bash(head:*)", "Bash(tail:*)"]
DENIED = ["Bash(git:*)", "Bash(rm:*)", "Bash(del:*)", "Bash(curl:*)", "WebFetch", "WebSearch"]


def claude_exe():
    """The Claude Code CLI, wherever the installer put it."""
    hit = shutil.which("claude")
    if hit:
        return hit
    home = Path(os.environ.get("USERPROFILE", Path.home()))
    for p in (home / ".local" / "bin" / "claude.exe", home / "AppData" / "Roaming" / "npm" / "claude.cmd",
              home / ".claude" / "local" / "claude.exe"):
        if p.exists():
            return str(p)
    # the copy the Claude desktop app keeps (newest version it has downloaded)
    def ver(p):
        try:
            return tuple(int(x) for x in p.parts[-3].split("."))
        except ValueError:
            return (0,)
    bundled = sorted((home / "AppData" / "Roaming" / "Claude" / "claude-code").glob("*/*/claude.exe"), key=ver)
    # ...or, for the Microsoft Store version of the desktop app, under Local\Claude-Data\claude_<id>
    bundled += sorted((home / "AppData" / "Local" / "Claude-Data").glob("claude_*/claude-code/*/*/claude.exe"), key=ver)
    return str(max(bundled, key=ver)) if bundled else None


def status() -> dict:
    exe = claude_exe()
    ver = None
    if exe:
        try:
            ver = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=20).stdout.strip()
        except Exception:
            ver = None
    # runs outside the desktop app need their own sign-in (made once with /login)
    signed_in = False
    if exe:
        try:
            out = subprocess.run([exe, "auth", "status"], capture_output=True, text=True, timeout=30,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
            signed_in = bool(json.loads(out).get("loggedIn"))
        except Exception:
            signed_in = False
    return {"installed": bool(exe), "path": exe, "version": ver, "signed_in": signed_in}


def load() -> list:
    try:
        return json.loads(FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return []


def _save(rows: list):
    tmp = FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(FILE)


def _update(rid: str, **kw):
    with LOCK:
        rows = load()
        for r in rows:
            if r["id"] == rid:
                r.update(kw)
        _save(rows)


def add(text: str, context: str = "") -> dict:
    r = {"id": uuid.uuid4().hex[:8], "text": text.strip(), "context": context.strip(), "created": time.time(),
         "status": "queued", "log": [], "summary": "", "posts": [], "error": None}
    with LOCK:
        rows = load()
        rows.insert(0, r)
        _save(rows)
    WAKE.set()
    return r


def cancel(rid: str):
    p = PROCS.get(rid)
    if p:
        p.kill()
    _update(rid, status="cancelled", finished=time.time())


def _snapshot() -> dict:
    return {p.parent.name: p.stat().st_mtime for p in PROJECTS_DIR.glob("*/edit.json")}


def _run(r: dict):
    exe = claude_exe()
    if not exe:
        _update(r["id"], status="error", error="Claude Code isn't installed on this computer yet.")
        return
    before = _snapshot()
    ctx = f"\nWhat the user was looking at when they asked: {r['context']}\n" if r.get("context") else ""
    # the prompt goes in on stdin (multi-line text doesn't survive .cmd argument parsing)
    prompt = PROMPT.format(text=r["text"], context=ctx)
    cmd = [exe, "-p", "--output-format", "stream-json", "--verbose",
           "--permission-mode", "acceptEdits",
           "--allowedTools", *ALLOWED, "--disallowedTools", *DENIED]
    _update(r["id"], status="working", started=time.time())
    log, summary = [], ""
    try:
        p = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.PIPE,
                             text=True, encoding="utf-8", errors="replace",
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        PROCS[r["id"]] = p
        p.stdin.write(prompt)
        p.stdin.close()
        last = 0.0
        for line in p.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except ValueError:
                log.append(line[:300])
                continue
            if ev.get("type") == "assistant":
                for part in (ev.get("message") or {}).get("content") or []:
                    if part.get("type") == "text" and part["text"].strip():
                        log.append(part["text"].strip()[:600])
                    elif part.get("type") == "tool_use":
                        inp = part.get("input") or {}
                        what = inp.get("description") or inp.get("file_path") or inp.get("pattern") or inp.get("command", "")
                        log.append(f"· {part.get('name')}: {str(what)[:140]}")
            elif ev.get("type") == "result":
                summary = ev.get("result") or ""
                if ev.get("is_error"):
                    r["error"] = summary or "the run failed"
                    if "not logged in" in summary.lower():
                        r["error"] = ("Claude Code isn't signed in for runs outside the desktop app. Sign in once: "
                                      "see the yellow note at the top of this window.")
            if time.time() - last > 1.5:  # keep the file light: throttle progress writes
                _update(r["id"], log=log[-40:])
                last = time.time()
        p.wait()
        after = _snapshot()
        posts = sorted(n for n, m in after.items() if before.get(n) != m and not n.startswith("_"))
        cancelled = next((x for x in load() if x["id"] == r["id"]), {}).get("status") == "cancelled"
        if cancelled:
            return
        ok = p.returncode == 0 and not r.get("error")
        _update(r["id"], status="done" if ok else "error", log=log[-40:], summary=summary, posts=posts,
                error=None if ok else (r.get("error") or f"Claude exited with code {p.returncode}"), finished=time.time())
    except Exception as e:
        _update(r["id"], status="error", error=str(e), log=log[-40:], finished=time.time())
    finally:
        PROCS.pop(r["id"], None)


def _worker():
    # anything left "working" from a crash or restart goes back in the queue
    with LOCK:
        rows = load()
        for r in rows:
            if r["status"] == "working":
                r["status"] = "queued"
        _save(rows)
    while True:
        nxt = next((r for r in reversed(load()) if r["status"] == "queued"), None)  # oldest first
        if nxt and not (claude_exe() and status()["signed_in"]):  # not set up yet: requests wait
            WAKE.wait(60)
            WAKE.clear()
            continue
        if nxt:
            _run(nxt)
            continue
        WAKE.wait(30)
        WAKE.clear()


_started = False


_lock_handle = None


def start():
    """Run the worker in exactly one editor process (a second server, e.g. a test copy,
    just shows the queue): whoever holds the lock file does the work."""
    global _started, _lock_handle
    if _started:
        return
    _started = True
    try:
        import msvcrt
        from .config import DATA_DIR
        _lock_handle = open(DATA_DIR / "asks.lock", "a+")
        msvcrt.locking(_lock_handle.fileno(), msvcrt.LK_NBLCK, 1)
    except (OSError, ImportError):
        return  # another editor is already the worker
    threading.Thread(target=_worker, daemon=True).start()
