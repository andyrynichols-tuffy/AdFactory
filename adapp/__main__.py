"""Ad Factory as its own desktop app (user, 2026-10-27): split out of Studio.

    .venv\\Scripts\\pythonw.exe -m adapp           open Ad Factory
    .venv\\Scripts\\pythonw.exe -m adapp --tray    start in the tray (what Windows runs at sign-in)
    .venv\\Scripts\\python.exe -m adapp --install  Desktop / Start menu / Startup shortcuts + the icon

One window on http://127.0.0.1:8770 (the same server the Ad Camera iPhone app and the phone / Mac web
link talk to), plus a tray icon. Its own supervisor (studio/supervisor.py, just the "ads" app) starts the
server, revives it if it stops and restarts it after code changes once /api/busy says it's free.
Closing the window keeps it running in the tray (inbox, spreadsheet sync, analytics, competitor checks,
Ad Camera uploads); "Quit" in the tray menu stops it. A second launch brings the open window forward."""
import ctypes
import os
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from studio.supervisor import LOGS, Supervisor, _listening  # noqa: E402

PORT, CONTROL_PORT = 8770, 8761
TITLE, APP_ID = "Ad Factory", "MemeSupercut.AdFactory"
ICON_ICO, ICON_PNG, ICON_TRAY = HERE / "adfactory.ico", HERE / "adfactory.png", HERE / "adfactory-tray.png"
WEB_ICON = ROOT / "adeditor" / "app-icon.png"  # the Mac's Safari "Add to Dock" / home-screen icon


def make_icon(force=False):
    """A macOS-style app icon: a graphite squircle with a white viewfinder (Ad Camera's job) and a
    blue record dot. The tray gets the glyph alone, white, so it reads on a dark taskbar."""
    if all(p.exists() for p in (ICON_ICO, ICON_PNG, ICON_TRAY, WEB_ICON)) and not force:
        return
    from PIL import Image, ImageDraw, ImageFilter
    N = 1024

    def glyph(d, s, off=(0, 0), white=(255, 255, 255, 255)):
        ox, oy = off
        w = int(56 * s)
        L, T, R, B = ox + 300 * s, oy + 300 * s, ox + 724 * s, oy + 724 * s
        k = 110 * s  # viewfinder corners
        for (x, y, dx, dy) in ((L, T, 1, 1), (R, T, -1, 1), (L, B, 1, -1), (R, B, -1, -1)):
            d.line((x, y + dy * k, x, y), fill=white, width=w)
            d.line((x, y, x + dx * k, y), fill=white, width=w)
            r = w / 2
            for px, py in ((x, y + dy * k), (x + dx * k, y), (x, y)):
                d.ellipse((px - r, py - r, px + r, py + r), fill=white)
        c, r = ox + 512 * s, 92 * s
        d.ellipse((c - r, oy + 512 * s - r, c + r, oy + 512 * s + r), fill=(10, 132, 255, 255))

    # the squircle, a soft vertical gradient, a hairline highlight and a drop shadow
    img = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    shadow = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((100, 118, 924, 942), radius=186, fill=(0, 0, 0, 120))
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(22)))
    grad = Image.new("RGBA", (N, N))
    gd = ImageDraw.Draw(grad)
    for y in range(N):
        v = int(68 - 40 * y / N)
        gd.line((0, y, N, y), fill=(v, v, v + 2, 255))
    mask = Image.new("L", (N, N), 0)
    ImageDraw.Draw(mask).rounded_rectangle((100, 100, 924, 924), radius=186, fill=255)
    img.paste(grad, (0, 0), mask)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((100, 100, 924, 924), radius=186, outline=(255, 255, 255, 36), width=4)
    glyph(d, 1.0)
    big = img.resize((512, 512), Image.LANCZOS)
    big.save(ICON_PNG)
    big.save(WEB_ICON)
    tray = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    glyph(ImageDraw.Draw(tray), 1.6, off=(-307, -307))
    tray = tray.resize((64, 64), Image.LANCZOS)
    tray.save(ICON_TRAY)
    sizes = [16, 24, 32, 48, 64, 128, 256]
    frames = [(tray if n <= 24 else big).resize((n, n), Image.LANCZOS) for n in sizes]
    frames[-1].save(ICON_ICO, sizes=[(n, n) for n in sizes], append_images=frames[:-1])


def install():
    """Desktop + Start menu shortcuts (open the window) and a Startup one (tray only), like Studio's."""
    import subprocess
    make_icon(force=True)
    pyw = ROOT / ".venv" / "Scripts" / "pythonw.exe"
    appdata = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    desktop = Path(os.environ["USERPROFILE"]) / "Desktop"
    for d in (Path(os.environ["USERPROFILE"]) / "OneDrive" / "Desktop",):
        if d.exists():
            desktop = d
    links = [(desktop / "Ad Factory.lnk", "-m adapp"), (appdata / "Ad Factory.lnk", "-m adapp"),
             (appdata / "Startup" / "Ad Factory.lnk", "-m adapp --tray")]
    for lnk, args in links:
        ps = (f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{lnk}');$s.TargetPath='{pyw}';"
              f"$s.Arguments='{args}';$s.WorkingDirectory='{ROOT}';$s.IconLocation='{ICON_ICO}';$s.Description='Ad Factory';$s.Save()")
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True)
        print("made", lnk)


def already_running() -> bool:
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{CONTROL_PORT}/show", timeout=2).read()
        return True
    except Exception:
        return False


def set_window_icon():
    u = ctypes.windll.user32
    u.FindWindowW.restype = ctypes.c_void_p
    u.LoadImageW.restype = ctypes.c_void_p
    hwnd = u.FindWindowW(None, TITLE)
    if not hwnd:
        return
    for size, which in ((16, 0), (48, 1)):
        h = u.LoadImageW(None, str(ICON_ICO), 1, size, size, 0x10)
        if h:
            u.SendMessageW(ctypes.c_void_p(hwnd), 0x80, which, ctypes.c_void_p(h))


class Api:
    def __init__(self, sup):
        self._sup = sup

    def status(self):
        return self._sup.status()

    def restart(self):
        threading.Thread(target=self._sup.restart, daemon=True).start()
        return True


def main():
    if "--install" in sys.argv:
        return install()
    tray_only = "--tray" in sys.argv
    if already_running():
        return
    make_icon()
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass
    from supercut import resources
    resources.install()

    import webview
    sup = Supervisor(ids=["ads"], versions=False)  # Studio keeps saving code versions for the whole repo
    threading.Thread(target=sup.run, daemon=True, name="supervisor").start()
    if not tray_only:  # open on the app itself, not an error page, when the server is still starting
        for _ in range(60):
            if _listening(PORT):
                break
            time.sleep(0.5)

    webview.settings["ALLOW_DOWNLOADS"] = True
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
    win = webview.create_window(TITLE, url=f"http://127.0.0.1:{PORT}/", js_api=Api(sup), width=1360, height=880,
                                min_size=(900, 600), hidden=tray_only, background_color="#1E1E1E", text_select=True)
    state = {"quitting": False}

    def show():
        win.show()
        win.restore()
        set_window_icon()

    def on_closing():
        if state["quitting"]:
            return True
        win.hide()
        return False

    win.events.closing += on_closing
    win.events.shown += lambda: set_window_icon()

    class Control(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/show":
                show()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *a):
            pass

    threading.Thread(target=HTTPServer(("127.0.0.1", CONTROL_PORT), Control).serve_forever, daemon=True).start()

    import pystray
    from PIL import Image

    def quit_all(icon, _):
        state["quitting"] = True
        icon.stop()
        sup.shutdown()
        win.destroy()

    menu = pystray.Menu(
        pystray.MenuItem("Open Ad Factory", lambda i, _: show(), default=True),
        pystray.MenuItem("Restart Ad Factory", lambda i, _: threading.Thread(target=sup.restart, daemon=True).start()),
        pystray.MenuItem("Open logs folder", lambda i, _: os.startfile(str(LOGS))),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit Ad Factory", quit_all),
    )
    pystray.Icon("AdFactory", Image.open(ICON_TRAY), TITLE, menu).run_detached()
    webview.start(gui="edgechromium", private_mode=False,
                  storage_path=str(Path.home() / "MemeSupercutData" / "adfactory-webview"))


if __name__ == "__main__":
    main()
