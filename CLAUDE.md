# Ad Factory: playbook for Claude

TikTok Shop content management: planning shoot days, TikTok analytics (ours and competitors'), and
turning raw footage into ads (the editor is one module), plus the **Ad Camera** iPhone app in `ios/`.
**Its own repo since 2026-10-27 (user):** split out of `andyrynichols-tuffy/MemeSupercut`, history kept.
Meme Factory and PlayOn Queue stay there; this repo shares no code with it.

## Layout

- `adcut/`: the Ad Factory server and logic (`python -m adcut serve` → http://127.0.0.1:8770).
- `adeditor/`: its web pages. `adapp/`: the desktop app (window + tray) that runs it.
- `adkit/`: Ad Factory's own copies of the helpers it used to borrow from MemeSupercut's `supercut/`
  (config, ingest/ffmpeg/whisper, captions, fonts, sounds, TikTok fetchers, `resources`, Claude CLI).
  They're copies: a fix here doesn't reach Meme Factory, and the other way round.
- `ads/`: shoots (`ads/<shoot>/shoot.json`) and shop data (`ads/_shop.json`, `_shop_stats.json`).
- `ios/`: Ad Camera (SwiftUI). Built on the MacBook with Xcode; see `ios/README.md`.
- `config.json`: `data_dir` is still `%USERPROFILE%\MemeSupercutData` (proxies, uploads, renders in its `ads/`
  folder), so nothing had to move in the split.

## The app (adapp/)

`pythonw -m adapp` (Desktop / Start menu / Startup shortcuts: `python -m adapp --install`) is its own window on
:8770 plus a tray icon. `adapp/supervisor.py` starts Ad Factory, revives it if it stops, and **auto-updates**: when
its .py files change it restarts it once `/api/busy` says it's free (add new long-running jobs to that endpoint).
Page files need no restart. Logs: `%USERPROFILE%\MemeSupercutData\logs\ads.log`. Ad Camera and the web link talk to
:8770; the phone reaches it at https://tuffy.tailb24038.ts.net:8770 (Tailscale). On the Mac: Safari → that link →
File → Add to Dock.
**Versions (adapp/versions.py):** code changes are committed ~20 s after they settle ("Update: <files>"), shoots and
shop data at most every 30 min ("Content: …"). Every ~10 min it syncs with GitHub (`andyrynichols-tuffy/AdFactory`):
brings in what's new there (e.g. a PR merged from the Mac) only when a trial merge shows no clash and none of those
files has unsaved edits here, then pushes; problems go to `logs\backup-adfactory.log`. Commit your own work with a
real message when it's a meaningful change. `adapp/` itself isn't auto-reloaded: quit it from the tray and start it again.

**Sharing the PC with PlayOn (adkit/resources.py).** PlayOn records in real time on this PC; starving it leaves
broken recordings. Every process calls `resources.install()` at startup (below-normal priority, idle while PlayOn
records). Whisper/GPU work goes through `resources.gpu_slot()` + `yield_to_playon()`: one GPU job at a time across
every app on the PC (the lock file `MemeSupercutData\gpu.lock`, shared with Meme Factory's copy), paused while PlayOn
records. New heavy code must use these too.

Windows PowerShell 5.1 mangles UTF-8 (emoji!). **Edit JSON with the Write/Edit tools, never with PowerShell
Set-Content/ConvertTo-Json.**

## Ad Factory (separate tool: TikTok Shop ads from raw footage)

**Mainly for planning shoot days and TikTok analytics, ours and competitors' (user, 2026-10-27).** macOS-style
window (adeditor/mac.css over the Studio theme copied into shared/, Ad Factory only; mac.js drops decorative emoji from labels):
sidebar Plan (Today = the day as a runbook with ticks per block, Shoot Days = planner, Lineup = products in rotation
by item × colourway) · Analytics (Our Accounts, Competitors) · Production (Shoots = editor, Posting, Scripts, Queue).
Keep new UI sleek: system font, neutral greys, one blue accent, no emoji in labels. Sidebar collapses to an icon rail; the language picker
and Ad Camera / spreadsheet status sit at its foot (no title bar on the main screens). Icon: white shopping bag + play
on a pink→violet squircle (adapp/make_icon). **Shoot page** (Shoot Days → Open Shoot): numbered steps (set up, lighting,
the example to copy = `set.example`, default per format from the @sully.finds study, embedded; pieces; film / photos;
after) with per-project progress. **Posting Kit** (Shoot Days → Posting Kit, `adcut/postkit.py`): one folder per post
in `<Outbox>/<date> posts/NN HH.MM <format> - <product>/` with video.mp4 (fresh render of video k of the project) or
the carousel's photos, + description.txt (Sully-style "I'm 6'2 185 wearing size L🤝 #brand #item…", "wearing" only on
worn/skit posts); status per post film → footage in → ready → scheduled. **Batch days (user, 2026-10-27; settings `mode: "batch"`):** one format per shoot day (`batch_week`; without carousel
access `BATCH_WEEK_VIDEO`: Mon skit+other, Wed worn, Thu flat-lay, Fri held), each batch fills its format's posting
slots for the next 7 days (`planner._batch`, `day_slots`): dated posts, a product's takes on different days, every
day a spread of products; the batch day ends with "Schedule this batch" (posting kit = `<Outbox>/<day> batch/`).
`carousels: false` until TikTok gives the accounts photo posts (slow rollout): their share goes to the videos.
Script versions (`planner.VARIANTS`, all from his transcripts): take r of a product uses version r % n, one Ad Camera
project per product + version. Carousels (when on): one photo pool per product (`c1-c3` cover poses + `o1…` outfits),
remixed by `carousel_combo` into several carousels over the week. `adcut/deals.py` reads each listing twice a day:
a real discount turns on his sale lines, free shipping alone adds "with free shipping". **Scripts are @sully.finds' own** (user: equivalent content, not thin templates): each format's
template in `planner.TEMPLATES` is copied from the transcript of the example it links, products swapped in, written in
full per product (`planner.script_for`, no blanks left). `[deal]` / `[nodeal]` lines pick his sale claims only when the
product has a real deal (product fills `deal`, `store price`). **Carousels are 2-5 photos, each a different
outfit laid flat around the item for sale** (user). Ad Camera: voice commands all start with "Ad Camera" (action, cut, scrap that / keep within ~6 s
after cut (kept by default), next line, last line, teleprompter on/off; "cut" alone is common in clothing scripts), Apple Watch remote, and **Shoot carousels**: several carousel projects × N outfits,
switch product or outfit freely, each photo → `PUT /api/camera/photo?shoot=&outfit=` → that carousel's kit folder. Sidebar shows Ad Camera's last
check-in (`/api/camera/status`). Code:
`adcut/shop.py` (+ `shopapi.py`, `/api/shop/*`), `adeditor/shop.js` + `shop.css`. Data in `ads/_shop.json`
(accounts, creators, products, orders, tags, scripts; removed things go to its `trash`, never deleted),
stats in `ads/_shop_stats.json`. Accounts = name + handle + login email only, **never passwords**. Orders:
which account ordered it, sample kind (free / refundable / paid), delivered, `return_by` (worked out from
`return_days`), `video_due`; Overview alerts when a return window or a free-sample video is due. A shoot's
plan is `shoot.shop` (product, account, creator, editor = who picked it up, tags, script, due); a posted
video's account / TikTok link / product are in `shoot.saved[n]` (Posting tab, Review and the editor ask
after "Posted"). "＋ New video" = tags + library script with `{placeholders}` (filled from the product and its
`fills`) + product + channel (pre-fills its usual creator) + raw files → a shoot with its inbox folder;
"Send to queue" assigns it. Library scripts also come from the Scripts & Links sheet rows (`adopt_sheet`;
edited ones aren't overwritten). **The Scripts & Links spreadsheet is the shared database (user, 2026-10-24;
`adcut/sheetdb.py`):** two-way sync every ~30 s and ~3 s after an app change. First tab = one row per video
(+ Product/Account/Creator/Tags/Due/Notes both ways, Stage/Videos/Posted app-written), then tabs Products,
People, Accounts, Tags, Script library, Orders, Posted videos; rows keyed by the ID column, tabs linked by
names. Cell-level 3-way merge against AD_DATA/sheetdb.json (sheet wins on conflict; a never-synced empty cell
never clears app data); deleted rows → app trash. Backups before each write in AD_DATA/sheet-backups. When
changing app data by hand, the next pass pushes it to the sheet; edit the sheet and the app follows.
**Portuguese (Brazil) interface (user, 2026-10-25, for the husband):** only the interface changes language; scripts,
captions, names and tags stay English (TikTok Shop US). `adeditor/i18n.js` translates text as it renders (whole
strings, then known pieces + number patterns, title/placeholder hints, toasts, confirm/alert) from
`adeditor/i18n-pt.js`; anything inside `translate="no"` is left alone (mark new user-content spots that way). The 🌐
button (top bar) switches per device; a pt browser starts in Portuguese; the web sign-in page follows Accept-Language.
**When adding UI text, add its pt-BR to i18n-pt.js** (`tools/i18n_missing.py` lists what's missing).
**Product links (user, 2026-10-26; `adcut/productlink.py`, `/api/shop/products/from-link`):** a TikTok Shop product
link, a TikTok video (the product tagged in it: item `anchors` type 33) or any shop page → name (short version of
TikTok's search-stuffed title), brand (shop name), category, price, link, picture, specs as script fill-ins. The
product and script forms fill in from a link; every product needs a TikTok Shop link (Products flags the rest,
"🔗 Link it", Overview alert). **New video → "⚡ Start from links"**: product link (+ "is this your MenPen?" when it
only matches by brand) + video to copy (its script, reused if that video was done before; **its key words start as
the video said them** (user, 2026-10-26): the script stays exactly the same unless they're changed, swapped for the
product's details with "⇄ Swap", or rewritten with ✨ AI; same in the builder) → "📷 Ready to shoot" =
queue + Ad Camera's project list (the camera lists every shoot with its script lines).
**Shoot-day flow (user, 2026-10-27; `planner.shoot_order`):** a batch day's projects have a filming order (set by set,
items in plan order) with what to lay out and what changed since the last one ("Add Cozy Cashmere", "Swap to the …",
"New setup: …"). Ad Camera opens each planned project with that setup card, and after a take shows "Next project"
(or "Ad Camera, next project"). The camera pings `/api/camera/now?shoot=`; the Mac's shoot page polls it with
`/api/shop/planner/order/<day>` and marks Now filming / Up next while takes tick in.
**Script builder (user, 2026-10-25; `adcut/scriptgen.py`, `adeditor/scriptbuilder.js`):** Library → "🔗 From a
TikTok link": download (the page's own video address like analytics.fetch_video; yt-dlp fallback, which TikTok
currently blocks without impersonation) into AD_DATA/refs/<id>/, local whisper transcript, shots from ffmpeg scene
cuts (a still each), lines split at sentences/pauses/cuts, product details guessed by rules (`guess_marks`: repeated
names, hashtags, known products/brands, "by X", prices, deals, sizes, materials, product words). A script keeps
`lines`, `marks` [{line, a, b, slot}] and `shots`; its `text` is the template ({product}, {feature 1}…), so New video
fills it. "Make it for another product" lists products by latest delivery. ✨ AI buttons (`adcut/ai.py`, `claude -p`
via the desktop app's bundled CLI, which needs a one-time `claude auth login`): find details, describe shots, fill
blanks for a product, rewrite (quick styles + Tone/Hook/Style tags + free text; {blanks}/[directions] kept).
**Competitor tracker (user, 2026-10-27; `adcut/competitors.py`, Analytics → 🕵️ Competitors, `ads/_competitors.json`):**
daily, per tracked handle: the profile grid (views per video; `adkit/tiktok_grid.py` with a longer scroll), each new
video's page once (tagged products), each product's page ("sold_count" + min price via `productlink.tiktok_product`).
Est. sales = sold-count growth × price, split across that creator's videos by views gained: an upper bound (the count
covers everyone selling it), no history before tracking, no clicks/conversion (Kalodata-style tools estimate the same way).
Analytics reads public pages (adkit/analytics fetchers) every 6 h:
account followers + each linked video's numbers, per account or all, by product × channel, script, tag, creator.

**🗓 Planner (user, 2026-10-27; `adcut/planner.py`, `adeditor/planner.js`, data `ads/_planner.json`):** a daily plan
built the way @sully.finds works (study: `docs/sully-finds-study.md`): ~20 posts per channel on weekdays (Saturday
light), a format mix (carousels 25% for reach, flat-lay voiceover 30%, worn faceless 20%, held 10%, skit 10%, other
5%), each format shot as one *set* (one setup, product after product, a few near-identical takes each, one script
template from `seed_templates()`), then edit, research and posts spread over 3–8 pm, around gym and meals. Two
channels share products, never footage (his POV "I'm 6'1…" / hers "He's 6'1…"). "📷 Make N Ad Camera projects"
turns a set into one shoot per product (`make_projects`, vars season/who/item/height/size). Settings: posts per
weekday, mix, takes, day times, channels, product lineup (blank = every product with a TikTok Shop link).

**Ad Camera iPhone app (user, 2026-10-25; `ios/AdCamera`, SwiftUI + AVFoundation, setup in `ios/README.md`):**
films takes straight into a project (pick one, or make one: product + script + style tags). Every take →
"Ad Studio" album in Photos + background upload into the shoot's OneDrive inbox folder
(`/api/inbox/upload?shoot=`; a retry of a finished file isn't duplicated). TikTok defaults: **back camera** (user,
2026-10-25), vertical 4K30 SDR (HDR off) HEVC, front camera (if flipped) unmirrored, WB held per take; teleprompter of the script lines; TikTok UI zones from
`layout.UI_ZONES`. API: `adcut/cameraapi.py` (`/api/camera/projects`), `POST /login` with Accept: application/json
returns the cookie token. The phone reaches Ad Factory at https://tuffy.tailb24038.ts.net:8770 (`tailscale serve
--bg --https=8770 http://127.0.0.1:8770`). Built on the husband's MacBook with Xcode (free Apple ID: re-run every
7 days); written on Windows, so compile errors get fixed on the Mac. UI strings: pt-BR in `Localizable.xcstrings`.

`adcut/` + `adeditor/`, started with `start-ad-editor.bat` → http://127.0.0.1:8770. A shoot
(`ads/<shoot>/shoot.json`) = raw files + script lines + takes. Every attempt at a line is a
take, graded good / close (reworded or "um", still usable) / flub (restarted) / incomplete /
paused (mid-line pause: checking the script?). Usable takes stack per line; video k = take k
of every line, so the line with the fewest good takes sets the video count. Scripts don't
need to be word-perfect: a take counts if the whole line got said. Outfit changes are marked
per raw file (`source.looks`), and a line can require one (`line.look`). `line.cut_next` = a
transition: it cuts on the motion into the next line, with both sides lined up on the next
line's first word plus `cut_offset` (auto = motion peak). Assets (screenshots/clips, `assets`)
are placed on lines via `overlays`, popping in on a chosen word. Renders + post.txt go
to `~/Videos/TikTok Shop/<shoot title>/`. Inbox: videos dropped in `OneDrive\Ad Factory Inbox`
(`ad_inbox_dir` in config.json; `adcut/inbox.py`) become shoots and get pre-cut automatically.
It runs in its own app (adapp/, above), which restarts it after adcut code changes. **Web link:** the editor starts a free Cloudflare quick tunnel (adcut/tunnel.py,
cloudflared via winget) and writes the current https link to OneDrive as "Ad Factory - web link" (.url/.txt)
each start (quick-tunnel links change on restart). Web visitors sign in (adcut/auth.py; password set
with python -m adcut password, copy in AD_DATA/login.txt, never in OneDrive); this PC needs no login. **Review mode** (`#review/<shoot>`, `/api/shoots/<id>/review`): each video as
a card to watch, download (to the device, or Save to Photos), send to the Outbox, save and mark posted;
"Get videos ready" renders stale ones. Phones open shoots there; the home page has a big upload button
that drops files into the OneDrive inbox (`/api/inbox/upload`, 16 MB pieces). He reviews on the web,
edits only on a computer. **Adding footage to a cut shoot** (source.batch; card "⬆ Add videos" uploads into the shoot's
own inbox folder, `inbox.folder_for`): `takes.decide_mix` keeps a new batch separate (its own videos after the
old ones, which stay put) when old and new each make whole videos (or old ones are saved/posted); otherwise it
re-cuts everything together. `shoot.mix` (editor bar) overrides: true = mix, false = keep separate. Locked takes
never move. Shoot cards also have "📝 Script" (`/api/shoots/<id>/script`; saving re-matches).
**Scripts & Links sheet** (OneDrive/Documents/scripts & links.xlsx, `adcut/sheet.py`): one row per upcoming
shoot (Shoot | Link | Script), synced every 30s into a shoot + inbox folder; [directions] go to notes; a shoot
remembers its row (`shoot.sheet.row`) so renaming it is fine; hand-edited scripts aren't overwritten.
**Voiceover videos** (`shoot.voiceover` = {src, in, out, cuts}): the sound is a separate voice recording, the
takes are silent shots (volume 0) whose `words` are the VO words mapped onto them (captions). Recreate the
reference's shots from the visuals take, cut where the reference cuts relative to its VO lines (MenPen 1). CLI: `python -m adcut board <shoot>` / `match` / `render`.
Editor playback uses pre-rendered previews (`adcut/preview.py`, 540x960, rebuilt in the
background whenever a video's footage changes; subs/assets/fx/sounds stay live). Transition
cuts are timed per video pair on their shared motion. Captions = take `words` (editable in
the Selected take pane; `user.words` keeps them through re-matches). Unscripted footage
(Game Night) = generic "Card N" lines with hand-placed manual takes, one video per tier.
Stacks are ranked best-first (`takes.rank_stacks`, `adcut/quality.py`: match score, no ums/rewording,
no long pauses, eye contact via OpenCV face/eye detection), so video 1 is the best video. Minority
reads (rare alt wording, heavy rewording) are pushed together into the last videos and the row
shows "🎭 different read". User-reordered lines and locked takes keep their order.
**Pacing (user, 2026-10-18):** TikTok Shop videos must move fast. `style.pace` auto-speeds slow takes
toward ~5 words/s (the waffle reference: 220 words in 43.5s, no pauses), max 1.35x; `style.speed` =
whole video, `take.speed` = one clip. Saved/posted takes are pinned (`speed: 1.0`) so they don't change.
**Shop safety:** `adcut/safety.py` flags captions (sexual/profanity/drugs = not Shop-safe, alcohol =
check); rows and the take pane show it. Prefer Shop-safe videos; one product link per video.
**Game night / party-game montages (user, 2026-10-18):** group videos by game first (one product per
video), then spice (`take.game`, `take.spice` 0-3, safest first). Each video = a cold-open hook (an
out-of-context crazy line, zoomed on whoever said it, `freeze` ~1s with `title` = the game name),
then a 20-40s montage of card reads + reactions that ends on the hook's moment in full (the loop back).
Lines are "Hook (cold open)" + "Card N"; takes are manual; `style.pace.auto` off.

**Ad editing rules (user, 2026-10-17):**
- Text never covers the product much. `style.product_box` marks it; subtitles and hooks
  auto-move above/below it (`adcut/layout.py`). Assets shouldn't cover it either.
- Keep everything out of TikTok's UI: top tabs, the right-hand like/comment/share rail,
  the bottom caption/username block and the orange-cart product tag (`layout.UI_ZONES`).
- When he *says* "orange cart"/"cart"/"basket", point at the cart area (`style.cart_pointer`:
  arrow + ring where TikTok shows the product tag). That's the only addition allowed.
- Never add elements that aren't in the script: no "click the orange cart!" stickers or
  CTA windows. Hooks only if the user writes them.
- Sound effects (`take.sfx`, soundboard in `adcut/sounds.py`, all synthesized = free to use)
  are the user's call: they drag them on. Don't add sounds unless asked. Same for the effects
  board (`take.fx`, `adcut/fx.py`: TikTok Shop pointers, spotlight, flash) and caption
  styles (`style.subs` presets, `line.subs_off`); `style.cart_pointer.kind` picks the auto pointer.
- Saved (☆) and posted videos are frozen: `saved[n].takes` locks those takes to video n
  so no other video reuses the footage (TikTok flags reuse). Never move/trim/reuse a
  locked take; unsaving is the only unlock.
