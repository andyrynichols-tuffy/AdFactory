# Ad Camera (iPhone)

Films TikTok Shop videos straight into an Ad Factory project. Pick a project (or make one:
product + script + style tags), then stop and start as often as you like: every take goes
into that project. Each take is saved to the **Ad Studio** album in Photos and uploaded into
the project's OneDrive inbox folder through Ad Factory, where it gets pre-cut like any drop.

- Camera defaults for TikTok: vertical, 4K 30 fps, SDR (HDR off), HEVC, standard
  stabilization, smooth autofocus, white balance held during a take, front camera unmirrored.
  Change them in Settings; "Back to the TikTok defaults" resets them.
- Teleprompter with the project's script, up by the front lens (tap = next line).
- TikTok UI guides (top tabs, like rail, caption block, cart tag) from `adcut/layout.py`.
- Tap to focus, hold for AE/AF lock, pinch to zoom, ± brightness, mic meter (external mics work).
- Volume buttons start/stop recording; optional 3/5/10 s countdown.
- Uploads keep going with the phone locked; with no connection they wait and retry.
- Interface in English or Portuguese (Brazil), following the phone's language.

Server side: `adcut/cameraapi.py` (`/api/camera/projects`), the inbox upload
(`/api/inbox/upload?shoot=…`) and `POST /login` with `Accept: application/json`.
The phone reaches Ad Factory at `https://tuffy.tailb24038.ts.net:8770` (Tailscale serve,
tailnet only), so the Tailscale app must be on and signed in to the same account.

## Installing on an iPhone from the MacBook (free Apple ID)

One-time:
1. On the Mac, install **Xcode** from the App Store (free, large download). Open it once
   and let it install its components (include iOS).
2. Get this folder onto the Mac: clone `andyrynichols-tuffy/MemeSupercut` from GitHub
   (GitHub Desktop is easiest), or copy the `ios` folder over.
3. Xcode → Settings → Accounts → **+** → Apple ID: sign in with the iPhone owner's Apple ID.
4. Open `ios/AdCamera.xcodeproj`. Click **AdCamera** (blue icon, top left) → target
   **AdCamera** → **Signing & Capabilities** → Team: pick the Apple ID ("Personal Team").
   If it says the bundle identifier is taken, change `com.andyrynichols.adcamera` to
   something unique (e.g. add `.andy`).
5. Plug the iPhone into the Mac with a cable, unlock it, tap **Trust**.
6. On the iPhone: Settings → Privacy & Security → **Developer Mode** → on (it restarts).
7. In Xcode's top bar pick the iPhone as the run destination, then press **▶ Run**.
8. First launch only: on the iPhone, Settings → General → VPN & Device Management →
   the Apple ID under "Developer App" → **Trust**. Open Ad Camera again.

Every 7 days (free Apple ID apps expire): plug in, press **▶ Run** again. Takes and settings
are kept. A paid Apple Developer account ($99/yr) removes the 7-day limit and allows TestFlight.

In the app: Settings → sign in with the Ad Factory web password (the one in
`AD_DATA/login.txt` on the PC). Allow Camera, Microphone and Photos when asked.

## Fixing build errors

This was written on Windows and never compiled. If Xcode shows errors, the quickest fix is
Claude Code on the Mac (Claude desktop app → Code): open this repo and ask it to build
`ios/AdCamera.xcodeproj` with `xcodebuild` and fix the errors. Or copy the errors to Claude
on the PC.
