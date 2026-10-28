"""Paths and settings (copied from MemeSupercut's supercut/config.py). Heavy media lives outside
OneDrive (see DATA_DIR): the same data folder as before the split, so nothing had to move."""
import json
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROJECTS_DIR = ROOT / "ads"  # Meme Factory's projects/ isn't here; the copied helpers that look there find nothing
FONTS_DIR = ROOT / "fonts"
EDITOR_DIR = ROOT / "adeditor"
CONFIG_FILE = ROOT / "config.json"

_defaults = {
    # Proxies, transcripts, render cache and renders. Kept out of OneDrive so
    # gigabytes of video don't sync.
    "data_dir": str(Path.home() / "MemeSupercutData"),
    "whisper_model": "large-v3-turbo",
    "encoder": "auto",  # auto | nvenc | x264
    # where "Download" in the editor saves finished videos (sub-foldered by date)
    "download_dir": str(Path.home() / "Videos" / "AndyFromBoyStory"),
    "min_episode_minutes": 20,
    # where new recordings land (PlayOn); "Check for new episodes" scans it
    "inbox_dir": str(Path.home() / "Videos" / "PlayOn"),  # shorter files are treated as incomplete recordings and skipped
}


def load_config() -> dict:
    cfg = dict(_defaults)
    if CONFIG_FILE.exists():
        cfg.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
    else:
        CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return cfg


CFG = load_config()
DATA_DIR = Path(CFG["data_dir"])
INDEX_DIR = DATA_DIR / "index"
PROXY_DIR = DATA_DIR / "proxies"
CACHE_DIR = DATA_DIR / "cache"
RENDERS_DIR = DATA_DIR / "renders"

for d in (FONTS_DIR, INDEX_DIR, PROXY_DIR, CACHE_DIR, RENDERS_DIR):
    d.mkdir(parents=True, exist_ok=True)


def tool(name: str) -> str:
    """Locate ffmpeg/ffprobe even if PATH wasn't refreshed after install."""
    found = shutil.which(name)
    if found:
        return found
    winget = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
    for p in winget.glob(f"Gyan.FFmpeg*/*/bin/{name}.exe"):
        return str(p)
    raise FileNotFoundError(f"{name} not found; install ffmpeg (winget install Gyan.FFmpeg)")


FFMPEG = tool("ffmpeg")
FFPROBE = tool("ffprobe")
