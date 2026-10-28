"""Ad Factory's engine (copied from MemeSupercut's Studio): keeps the app running and up to date.

- Starts each app if nothing answers on its port (or adopts the copy that's already running).
- Revives an app that stops (a few seconds later; backs off if it keeps failing).
- Updates without reinstalling: when an app's Python code changes on disk it restarts that
  app, but only once the app says it isn't busy (/api/busy: no render, index, Ask Claude
  job or overnight batch in progress). Page files (html/js/css) need no restart; the shell
  just reloads that tab.
Every app logs to %USERPROFILE%\\MemeSupercutData\\logs\\<app>.log."""
import json
import os
import re
import socket
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = ROOT / ".venv" / "Scripts" / "python.exe"
LOGS = Path.home() / "MemeSupercutData" / "logs"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

APPS = [
    {"id": "ads", "name": "Ad Factory", "port": 8770, "path": "/",
     "cmd": [str(PY), "-u", "-m", "adcut", "serve"],
     "code": ["adcut", "adkit", "config.json"], "web": ["adeditor"]},  # settings are read at start
]
CODE_EXT = {".py", ".cs"}
WEB_EXT = {".html", ".js", ".css"}


def _newest(paths, exts) -> float:
    t = 0.0
    for rel in paths:
        p = ROOT / rel
        files = [p] if p.is_file() else (f for f in p.rglob("*") if f.suffix in exts and "__pycache__" not in f.parts)
        for f in files:
            try:
                t = max(t, f.stat().st_mtime)
            except OSError:
                pass
    return t


def _listening(port) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _get(port, path, timeout=3):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=timeout) as r:
        return json.loads(r.read() or b"{}")


def _port_pid(port):
    out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True, creationflags=NO_WINDOW).stdout
    for line in out.splitlines():
        m = re.match(rf"\s*TCP\s+(?:0\.0\.0\.0|127\.0\.0\.1):{port}\s+\S+\s+LISTENING\s+(\d+)", line)
        if m:
            return int(m[1])
    return None


def _started_at(pid) -> float:
    """When a process started (so we know whether it already runs the latest code)."""
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL("kernel32")
    k.OpenProcess.restype = wintypes.HANDLE
    h = k.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return 0.0
    c, e, kt, ut = (wintypes.FILETIME() for _ in range(4))
    ok = k.GetProcessTimes(h, ctypes.byref(c), ctypes.byref(e), ctypes.byref(kt), ctypes.byref(ut))
    k.CloseHandle(h)
    if not ok:
        return 0.0
    ft = (c.dwHighDateTime << 32) | c.dwLowDateTime
    return ft / 1e7 - 11644473600  # FILETIME -> unix seconds


def _kill_tree(pid):
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, creationflags=NO_WINDOW)


class App:
    def __init__(self, spec):
        self.__dict__.update(spec)
        self.proc = None
        self.started = 0.0          # when the running copy started
        self.state = "starting"     # starting | up | updating | waiting | down
        self.note = ""
        self.restarts = 0           # bumps whenever the page should be reloaded
        self.web_seen = _newest(self.web, WEB_EXT)
        self.fails = 0
        self.retry_at = 0.0

    def info(self):
        return {"id": self.id, "name": self.name, "url": f"http://127.0.0.1:{self.port}{self.path}",
                "state": self.state, "note": self.note, "reload": self.restarts}

    def start(self):
        LOGS.mkdir(parents=True, exist_ok=True)
        log = open(LOGS / f"{self.id}.log", "ab")
        log.write(f"\n===== Ad Factory starting {self.name} {time.strftime('%Y-%m-%d %H:%M:%S')} =====\n".encode())
        log.flush()
        self.proc = subprocess.Popen(self.cmd, cwd=ROOT, stdout=log, stderr=log, stdin=subprocess.DEVNULL,
                                     creationflags=NO_WINDOW)
        self.started = time.time()
        self.state, self.note = "starting", ""

    def stop(self):
        pid = (self.proc.pid if self.proc and self.proc.poll() is None else None) or _port_pid(self.port)
        if pid:
            _kill_tree(pid)
        for _ in range(40):  # wait for the port to free up
            if not _listening(self.port):
                break
            time.sleep(0.25)
        self.proc = None

    def busy(self):
        try:
            return _get(self.port, "/api/busy").get("why") or []
        except Exception:
            return []  # older copy without /api/busy, or not answering: nothing to protect

    def tick(self):
        up = _listening(self.port)
        if up and self.state in ("starting", "down"):
            self.state, self.fails = "up", 0
            if not self.started:  # adopted a copy that was already running
                pid = _port_pid(self.port)
                self.started = _started_at(pid) if pid else 0.0
        if not up and self.state != "updating":
            dead = self.proc is None or self.proc.poll() is not None
            if dead and (self.state != "starting" or time.time() - self.started > 5):
                if self.state != "down":  # just went down: try again soon, backing off if it keeps failing
                    self.fails += 1
                    self.state, self.note = "down", "restarting…"
                    self.retry_at = time.time() + min(30, 2 * self.fails)
                elif time.time() >= self.retry_at:
                    self.start()
            return
        # code changed since this copy started -> update when it's free
        if up and _newest(self.code, CODE_EXT) > self.started + 1:
            why = self.busy()
            if why:
                self.state, self.note = "waiting", "update ready after: " + ", ".join(why)
                return
            self.state, self.note = "updating", "updating…"
            self.stop()
            self.start()
            self.restarts += 1
            return
        if self.state == "waiting":
            self.state, self.note = "up", ""
        # page files changed: the shell reloads the tab
        w = _newest(self.web, WEB_EXT)
        if w > self.web_seen:
            self.web_seen = w
            self.restarts += 1


class Supervisor:
    """ids = which apps this window runs (just Ad Factory here). versions = also save code versions
    and back them up to GitHub (adapp/versions.py)."""
    def __init__(self, ids=None, versions=True):
        self.apps = [App(s) for s in APPS if ids is None or s["id"] in ids]
        self.versions = versions
        self._stop = False

    def adopt_or_start(self):
        for a in self.apps:
            if not _listening(a.port):
                a.start()

    def run(self):
        from . import versions
        self.adopt_or_start()
        n = 0
        while not self._stop:
            n += 1
            if self.versions and n % 5 == 0:  # every ~10 s: save settled changes as versions (adapp/versions.py)
                try:
                    versions.snapshot()
                except Exception as e:
                    self.versions_error = str(e)
            for a in self.apps:
                try:
                    a.tick()
                except Exception as e:  # never let one app's hiccup stop the others
                    a.note = f"supervisor: {e}"
            time.sleep(2)

    def status(self):
        return [a.info() for a in self.apps]

    def restart(self, app_id=None):
        for a in self.apps:
            if app_id in (None, a.id):
                a.state, a.note = "updating", "restarting…"
                a.stop()
                a.start()
                a.restarts += 1

    def shutdown(self):
        self._stop = True
        for a in self.apps:
            a.stop()
