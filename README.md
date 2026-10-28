# Ad Factory

TikTok Shop content management: shoot-day planning, analytics (ours and competitors'), an editor that turns raw
footage into finished ads, and **Ad Camera**, the iPhone app that films straight into a project.

Split out of `andyrynichols-tuffy/MemeSupercut` on 2026-10-27 (history kept). See `CLAUDE.md` for how it all works.

## Running it (on the PC)

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\pythonw.exe -m adapp            # the desktop app: window + tray, keeps Ad Factory running
.venv\Scripts\python.exe -m adapp --install   # Desktop / Start menu / Startup shortcuts
```

Or just the server: `.venv\Scripts\python.exe -m adcut serve` → http://127.0.0.1:8770
(`start-ad-editor.bat` does the same).

`config.json` points at the data folder (`data_dir`) and the OneDrive inbox/outbox folders.

## Ad Camera (iPhone)

`ios/AdCamera.xcodeproj`, built on the Mac with Xcode. Setup and the 7-day re-install: `ios/README.md`.
