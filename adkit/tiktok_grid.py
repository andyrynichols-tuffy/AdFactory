"""Read every video on a public TikTok profile (no login, no developer app).

TikTok's profile page loads its video grid with scripts, so a plain download only gets the
account totals. This opens the profile in an off-screen browser window (pywebview = the Edge
engine Windows already has), scrolls it like a person would, and reads each grid tile:
video link + the view count shown on it. Per-video likes/comments/shares/saves still come
from each video's own public page (supercut/analytics.py).

Runs as its own short-lived process (a window needs its own main thread):
    python -m supercut.tiktok_grid <handle>      -> prints JSON [{"video_id", "url", "views"}]"""
import json
import sys
import threading
import time
from pathlib import Path

SCRAPE_JS = r"""
(() => {
  const out = {};
  document.querySelectorAll('a[href*="/video/"], a[href*="/photo/"]').forEach(a => {
    const m = a.href.match(/\/@([\w.]+)\/(?:video|photo)\/(\d{8,})/);  // picture carousels live at /photo/
    if (!m) return;
    const kind = a.href.includes("/photo/") ? "photo" : "video";
    const views = (a.querySelector('[data-e2e="video-views"]') || {}).textContent || "";
    const img = a.querySelector('img');
    out[m[2]] = {video_id: m[2], handle: m[1], kind, url: `https://www.tiktok.com/@${m[1]}/video/${m[2]}`, views_text: views.trim(),
                 cover: img ? img.src : "", alt: img ? (img.alt || "") : ""};
  });
  return JSON.stringify({items: Object.values(out), height: document.body.scrollHeight,
                         blocked: !!document.querySelector('#captcha-verify-container, .captcha_verify_container')});
})()
"""


def _num(text):
    t = (text or "").strip().upper().replace(",", "")
    mult = 1000 if t.endswith("K") else 1_000_000 if t.endswith("M") else 1
    try:
        return int(float(t.rstrip("KM")) * mult)
    except ValueError:
        return None


def scrape(handle: str, expect: int = 0, timeout: float = 90) -> dict:
    import webview
    handle = handle.lstrip("@")
    result = {"items": [], "error": None}

    def work(win):
        try:
            time.sleep(6)
            seen, still = {}, 0
            t0 = time.time()
            while time.time() - t0 < timeout:
                data = json.loads(win.evaluate_js(SCRAPE_JS) or "{}")
                if data.get("blocked"):
                    result["error"] = "TikTok asked for a captcha; try again later"
                    break
                before = len(seen)
                for it in data.get("items", []):
                    seen[it["video_id"]] = it
                if expect and len(seen) >= expect:
                    break
                still = still + 1 if len(seen) == before else 0
                if still >= 4:  # nothing new after several scrolls: that's everything
                    break
                win.evaluate_js("window.scrollBy(0, 2400)")
                time.sleep(2.5)
            result["items"] = [{**it, "views": _num(it.pop("views_text", ""))} for it in seen.values()]
        except Exception as e:  # noqa: BLE001
            result["error"] = str(e)
        finally:
            win.destroy()

    # A real window parked off-screen, not a hidden one: TikTok only loads grid tiles that are
    # "on screen", and a hidden window never is.
    win = webview.create_window("tiktok", f"https://www.tiktok.com/@{handle}", hidden=False, x=-4000, y=0,
                                width=1280, height=1600, focus=False)
    webview.start(work, win, private_mode=False,
                  storage_path=str(STORAGE))
    return result


STORAGE = Path.home() / "MemeSupercutData" / "tiktok-webview"


def login_window():
    """A visible window on TikTok's login page, sharing the hidden window's storage: the user
    signs in themselves (the app never sees the password), then closes it. TikTok only shows
    a profile's video grid to signed-in visitors, and this remembers the sign-in."""
    import webview
    webview.create_window("Sign in to TikTok (close this window when you're signed in)",
                          "https://www.tiktok.com/login", width=520, height=820)
    webview.start(private_mode=False, storage_path=str(STORAGE))


def signed_in() -> bool:
    """Whether the remembered TikTok session exists (a session cookie in the window's storage)."""
    import sqlite3
    for db in STORAGE.rglob("Cookies"):
        try:
            con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro&immutable=1", uri=True)
            n = con.execute("SELECT COUNT(*) FROM cookies WHERE host_key LIKE '%tiktok.com' "
                            "AND name IN ('sessionid', 'sessionid_ss', 'sid_tt')").fetchone()[0]
            con.close()
            if n:
                return True
        except sqlite3.Error:
            pass
    return False


if __name__ == "__main__":
    if sys.argv[1] == "--login":
        login_window()
    elif sys.argv[1] == "--signed-in":
        print(json.dumps({"signed_in": signed_in()}))
    else:
        h = sys.argv[1]
        exp = int(sys.argv[2]) if len(sys.argv) > 2 else 0
        tmo = float(sys.argv[3]) if len(sys.argv) > 3 else 90  # long profiles (competitor tracking) scroll longer
        print(json.dumps(scrape(h, exp, tmo)))
