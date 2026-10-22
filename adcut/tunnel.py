"""The editor's web link: a free Cloudflare quick tunnel (cloudflared, no account) to
http://127.0.0.1:8770, started with the editor. Quick-tunnel addresses change every time a
tunnel starts, so cloudflared runs detached from the editor: restarting the editor (Studio
does that for updates) keeps the same tunnel and link. The current link is written to
OneDrive (next to the Ad Factory Inbox) as "Ad Factory - web link" (.url shortcut + .txt)
and kept in AD_DATA/tunnel.json. Visitors through the link sign in with the web password
(adcut/auth.py)."""
import json
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

from . import inbox, store

STATE = store.AD_DATA / "tunnel.json"
LOG = store.AD_DATA / "tunnel.log"
EXE_GUESSES = [Path(r"C:\Program Files (x86)\cloudflared\cloudflared.exe"), Path(r"C:\Program Files\cloudflared\cloudflared.exe")]
URL_RX = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
state = {"url": None, "status": "off", "since": None}


def exe():
    found = shutil.which("cloudflared")
    return found or next((str(p) for p in EXE_GUESSES if p.exists()), None)


def _publish(url: str):
    state.update(url=url, status="on", since=state.get("since") or time.time())
    STATE.write_text(json.dumps(state), encoding="utf-8")
    folder = inbox.inbox_dir().parent  # OneDrive, next to the Inbox / Outbox
    try:
        (folder / "Ad Factory - web link.url").write_text(f"[InternetShortcut]\nURL={url}\n", encoding="utf-8")
        (folder / "Ad Factory - web link.txt").write_text(
            "Ad Factory editor on the web\n\n"
            f"    {url}\n\n"
            "Open it in any browser and sign in with the Ad Factory password.\n"
            "The link stays the same while this PC is on; after a reboot it changes and this file has the new one.\n"
            f"(updated {time.strftime('%Y-%m-%d %H:%M')})\n", encoding="utf-8")
    except OSError:
        pass


def _alive(url) -> bool:
    """The tunnel answers from the outside (the sign-in page is public)."""
    import urllib.request
    for _ in range(3):
        try:
            with urllib.request.urlopen(f"{url}/login", timeout=10) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(3)
    return False


def _kill_ours(port):
    """Stop a dead tunnel to this editor (never Meme Factory's, which points at another port)."""
    subprocess.run(["powershell", "-NoProfile", "-Command",
                    "Get-CimInstance Win32_Process -Filter \"Name='cloudflared.exe'\" | "
                    f"Where-Object {{ $_.CommandLine -like '*127.0.0.1:{port}*' }} | "
                    "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"],
                   capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _launch(path, port):
    """Start cloudflared detached from the editor (via `start`). Returns the new link."""
    LOG.touch()
    mark = LOG.stat().st_size
    subprocess.Popen(["cmd", "/c", "start", "", "/b", path, "tunnel", "--url", f"http://127.0.0.1:{port}",
                      "--no-autoupdate", "--logfile", str(LOG)],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    for _ in range(90):
        time.sleep(1)
        with open(LOG, encoding="utf-8", errors="replace") as f:
            f.seek(mark)
            m = URL_RX.search(f.read())
        if m:
            return m.group(0)
    return None


def _run(port: int):
    path = exe()
    if not path:
        state["status"] = "cloudflared not installed"
        return
    try:
        prev = json.loads(STATE.read_text(encoding="utf-8")).get("url")
    except (OSError, ValueError):
        prev = None
    if prev and _alive(prev):  # the tunnel outlived an editor restart: keep the same link
        _publish(prev)
    while True:
        if not state.get("url") or not _alive(state["url"]):
            state.update(status="starting", url=None, since=None)
            _kill_ours(port)
            url = _launch(path, port)
            if url:
                time.sleep(5)  # a new quick tunnel takes a moment to answer
                _publish(url)
            else:
                state["status"] = "couldn't start"
        time.sleep(60)


def start(port: int = 8770):
    threading.Thread(target=_run, args=(port,), daemon=True, name="tunnel").start()
