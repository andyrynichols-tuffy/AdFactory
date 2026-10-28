/* Planner (adcut/planner.py): shoot days built the way @sully.finds works (docs/sully-finds-study.md).
   Today = the current shoot day as a runbook (tick blocks off, see what each one needs).
   Shoot Days = plan and adjust days: sets, lighting, items × takes, scripts, posting times. */
"use strict";
const PL = { day: null, plan: null, cfg: null, days: [], sel: null };
const todayIso = () => { const d = new Date(); return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10); };
const addDays = (iso, n) => { const d = new Date(iso + "T12:00"); d.setDate(d.getDate() + n); return d.toISOString().slice(0, 10); };
const mins = m => m >= 60 ? `${Math.floor(m / 60)} h ${String(Math.round(m % 60)).padStart(2, "0")} m` : `${Math.round(m)} min`;
const loc = () => (window.LANG === "pt" ? "pt-BR" : "en-US");
const dayName = (iso, o = { weekday: "long", month: "long", day: "numeric" }) => new Date(iso + "T12:00").toLocaleDateString(loc(), o);
const toMin = s => { const [h, m] = String(s || "0:0").split(":").map(Number); return h * 60 + m; };
const span = b => toMin(b.end) - toMin(b.start);
const KIND_LABEL = { gym: "Gym", meal: "Meal", shoot: "Shoot", edit: "Edit", research: "Research", post: "Schedule", live: "Live", prep: "Prep" };
const bkey = b => `${b.kind}|${b.set || b.title}|${b.start}`;
function shortTitle(b, p) {  // the agenda line: what it is, without the plan's long description
  if (b.kind === "shoot") return p.sets.find(s => s.id === b.set)?.label || b.title;
  return { prep: "Prep", edit: "Edit and review", research: "Research", live: "Posts go live" }[b.kind]
    || (b.kind === "post" ? `Schedule ${p.posts.length} posts` : b.title);
}
const colorOf = name => (name || "").split(" - ")[1] || "";
const baseOf = name => (name || "").split(" - ")[0];

// lighting notes are sentences: "Key (circle) …", "Fill panel 1 …", "Fill panel 2 …", then general notes
function lightTable(light) {
  if (!light) return "";
  const rows = [], notes = [];
  light = (window.tr || (s => s))(light);  // the whole note translates as one string, so split after
  for (const s of light.split(/(?<=[.;])\s+(?=[A-ZÀ-Ú])/)) {
    const m = s.match(/^(Key \(circle\)|Fill panel 1|Fill panel 2|Luz principal \(círculo\)|Painel 1|Painel 2)\s*(.*)$/);
    m ? rows.push([m[1].replace("Key (circle)", "Key light").replace("Luz principal (círculo)", "Luz principal"), m[2]]) : notes.push(s);
  }
  return `<div class="mxLight">${rows.length ? `<table class="mxKV">${rows.map(([k, v]) => `<tr><th>${esc(k)}</th><td>${esc(v)}</td></tr>`).join("")}</table>` : ""}
    ${notes.length ? `<p class="mxNote">${esc(notes.join(" "))}</p>` : ""}</div>`;
}
function setCard(s, opts = {}) {
  const n = s.items.filter(i => i.product).length, sc = byId("scripts", s.script);
  const fmt = (PL.cfg?.formats || []).find(f => f.key === s.format) || {};
  return `<section class="mxCard" id="set-${s.id}">
    <header class="mxCardHead"><div><h3>${esc(s.label)}</h3><div class="muted">${esc(s.setup)}</div></div>
      <div class="mxMeta"><span>${s.posts} posts</span><span>${mins(s.minutes)}</span></div></header>
    <div class="mxCardBody">
      <div class="mxField"><div class="mxLabel">Pieces</div>
        <table class="mxList"><tbody>${s.items.map(i => { const p = byId("products", i.product);
          return `<tr><td translate="no">${esc(baseOf(i.name))}</td><td translate="no" class="muted">${esc(colorOf(i.name))}</td><td class="muted">${esc(p?.fills?.size || "")}</td><td class="num">${i.takes} <span>${i.takes === 1 ? "take" : "takes"}</span></td></tr>`; }).join("")}</tbody></table></div>
      <div class="mxField"><div class="mxLabel">Lighting <span class="muted">· ${s.light_min} min to set up</span></div>${lightTable(s.light)}</div>
      <div class="mxField"><div class="mxLabel">How</div><p class="mxNote">${esc(fmt.tip || s.tip || "")}</p>
        ${sc ? `<p class="mxNote muted">Script: <span translate="no">${esc(sc.title)}</span></p>` : ""}</div>
    </div>
    ${opts.actions === false ? "" : `<footer class="mxCardFoot">${s.projects?.length
      ? `<span class="mxOk">${s.projects.length} ${s.projects.length === 1 ? "project" : "projects"} ready in Ad Camera</span>`
      : `<button data-mkset="${s.id}" ${n ? "" : "disabled"} title="One project per product, with the script and how many takes">Send ${n} to Ad Camera</button>`}
      <button class="primary" data-open-set="${s.id}" title="Step-by-step instructions, the example to copy, and how filming is going">Open Shoot ›</button></footer>`}
  </section>`;
}

// ---------- Shoot Days ----------
async function renderPlanner() {
  const el = $("#panePlanner");
  await shopLoad();
  [PL.days, PL.cfg] = await Promise.all([api("/api/shop/planner/days"), api("/api/shop/planner/settings")]);
  const upcoming = PL.days.filter(d => d.date >= todayIso());
  PL.day = LS.get("planDay", "") || upcoming[0]?.date || todayIso();
  if (PL.day < todayIso() && upcoming.length) PL.day = upcoming[0].date;
  PL.plan = await api(`/api/shop/planner/day/${PL.day}`);
  const openSet = LS.get("planOpen", ""), view = LS.get("planView", "plan");
  if (openSet && PL.plan.sets.some(s => s.id === openSet)) return renderShoot(openSet);
  const p = PL.plan, set = PL.cfg.settings;
  const shoot = p.sets.reduce((a, s) => a + s.minutes, 0), edit = p.sets.reduce((a, s) => a + s.edit_minutes, 0);
  const work = p.blocks.filter(b => !["gym", "meal", "live"].includes(b.kind)), ends = work.length ? work.at(-1).end : "";
  const strip = [...new Set([...upcoming.map(d => d.date), PL.day])].sort();
  el.innerHTML = `
    <div class="mxBar">
      <div class="mxSeg" role="tablist">${strip.map(d => { const x = PL.days.find(y => y.date === d);
        return `<button data-day="${d}" class="${d === PL.day ? "on" : ""}" role="tab"><b>${esc(dayName(d, { weekday: "short" }))}</b> ${esc(dayName(d, { month: "short", day: "numeric" }))}${x?.projects ? `<i class="sdot ok" title="Projects in Ad Camera"></i>` : ""}</button>`; }).join("")}</div>
      <label class="mxAdd">Plan a day <input type="date" id="planDate" min="${todayIso()}" value=""></label>
      <span class="spacer"></span>
      <div class="mxSeg">${[["plan", "Plan"], ["kit", "Posting Kit"]].map(([k, l]) => `<button data-pview="${k}" class="${view === k ? "on" : ""}">${l}</button>`).join("")}</div>
      <button data-go="plrebuild" title="Make the day again from the settings (ticks and Ad Camera projects are kept)">Rebuild Day</button>
      <button data-go="plsettings">Settings</button>
    </div>
    ${!PL.cfg.accounts.length ? `<div class="mxBanner">Add your TikTok accounts first (Our Accounts → Accounts): the planner makes a day per channel.</div>` : ""}
    <div class="mxDayHead"><h2>${esc(dayName(PL.day))}</h2>
      <div class="mxStats"><span><b>${p.posts.length}</b> posts</span><span><b>${p.sets.length}</b> setups</span><span><b>${mins(shoot)}</b> shooting</span><span><b>${mins(edit)}</b> editing</span>${ends ? `<span>done by <b>${ends}</b></span>` : ""}</div></div>
    ${view === "kit" ? `<div id="kitBox"></div>` : `<div class="mxCols">
      <div class="mxSide">
        <div class="mxLabel">Schedule</div>
        <ol class="mxAgenda">${p.blocks.map(b => `<li class="k-${b.kind}" ${b.set ? `data-goto="${b.set}"` : ""}>
          <span class="t">${b.start}</span><span class="w">${esc(shortTitle(b, p))}</span><span class="d muted">${mins(span(b))}</span></li>`).join("")}</ol>
        <details class="mxPosts"><summary>Posting times <span class="muted">${p.posts.length} posts, ${set.day.post_from}–${set.day.post_to}</span></summary>
          <table class="mxList"><tbody>${p.posts.map((x, k) => `<tr class="${x.done ? "closed" : ""}"><td><input type="checkbox" data-mark="${k}" ${x.done ? "checked" : ""} title="${set.day.schedule !== false ? "Scheduled" : "Posted"}"></td>
            <td class="num">${x.time}</td><td>${esc((PL.cfg.formats.find(f => f.key === x.format) || {}).label || x.format)}</td><td translate="no" class="muted">${esc(x.name)}</td></tr>`).join("")}</tbody></table></details>
      </div>
      <div class="mxMain">${p.sets.map(s => setCard(s)).join("") || `<div class="mxEmpty">Nothing planned this day. Posts per channel for this weekday are set to 0 in Settings.</div>`}</div>
    </div>`}`;
  if (view === "kit") renderKit($("#kitBox"), PL.day);
}
$("#panePlanner").addEventListener("click", async e => {
  const d = e.target.closest("[data-day]"); if (d) { LS.set("planDay", d.dataset.day); LS.set("planOpen", ""); return renderPlanner(); }
  const pv = e.target.closest("[data-pview]"); if (pv) { LS.set("planView", pv.dataset.pview); return renderPlanner(); }
  const os = e.target.closest("[data-open-set]"); if (os) { LS.set("planOpen", os.dataset.openSet); $("#home .homeBox").scrollTop = 0; return renderPlanner(); }
  if (e.target.closest("[data-go=shootback]")) { LS.set("planOpen", ""); return renderPlanner(); }
  if (e.target.closest("[data-go=example]")) { const v = $("#exampleUrl")?.value || ""; await api(`/api/shop/planner/day/${PL.day}/set/${LS.get("planOpen", "")}`, { json: { example: v } }); toast(v ? "Example saved for this shoot" : "Back to the default example"); return renderPlanner(); }
  if (await carouselClick(e)) return;
  if (kitClick(e, PL.day, renderPlanner)) return;
  const go = e.target.closest("[data-go]")?.dataset.go;
  if (go === "plrebuild") { await api(`/api/shop/planner/day/${PL.day}/rebuild`, { json: {} }); toast("Day rebuilt"); return renderPlanner(); }
  if (go === "plsettings") return plannerSettings();
  const mk = e.target.closest("[data-mkset]"); if (mk) return makeSet(mk, renderPlanner);
  const g = e.target.closest("[data-goto]"); if (g) $(`#set-${g.dataset.goto}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
});
$("#panePlanner").addEventListener("change", async e => {
  if (e.target.id === "planDate" && e.target.value) { LS.set("planDay", e.target.value); await api(`/api/shop/planner/day/${e.target.value}`); return renderPlanner(); }
  if (e.target.dataset.mark != null) markPost(PL.day, e.target);
});
async function makeSet(btn, then) {
  btn.disabled = true; btn.textContent = "Sending…";
  try { const r = await api(`/api/shop/planner/day/${PL.day}/projects`, { json: { set: btn.dataset.mkset } }); toast(`${r.made.length} ready in Ad Camera (and the Queue)`, 4000); }
  catch (err) { toast(err.message, 6000); }
  then();
}
async function markPost(day, box) {
  await api(`/api/shop/planner/day/${day}/mark`, { json: { k: +box.dataset.mark, done: box.checked } });
  box.closest("tr")?.classList.toggle("closed", box.checked);
}

// ---------- one shoot, step by step (for the Mac, next to the phone running Ad Camera) ----------
const tiktokId = url => (String(url || "").match(/\/(?:video|photo)\/(\d+)/) || [])[1];
async function renderShoot(setId) {
  const el = $("#panePlanner"), p = PL.plan, s = p.sets.find(x => x.id === setId);
  const kit = await api(`/api/shop/planner/day/${PL.day}/kit`).catch(() => ({ posts: [] }));
  PL.kit = kit.posts;
  const mine = kit.posts.filter(x => x.set === s.id), sc = byId("scripts", s.script);
  const carousel = s.format === "carousel", vid = tiktokId(s.example);
  if (carousel) return renderCarouselShoot(el, s, mine).then(showExample);
  const ticks = new Set(LS.get(`steps:${PL.day}:${s.id}`, []));
  const step = (k, title, body) => `<li class="mxStep ${ticks.has(k) ? "done" : ""}"><label class="mxStepHead"><input type="checkbox" data-step="${k}" ${ticks.has(k) ? "checked" : ""}><b>${title}</b></label><div class="mxStepBody">${body}</div></li>`;
  const filmed = mine.filter(x => !["film", "photos"].includes(x.step)).length;
  el.innerHTML = `
    <div class="mxBar"><button data-go="shootback">‹ ${esc(dayName(PL.day, { weekday: "long", month: "short", day: "numeric" }))}</button><span class="spacer"></span>
      ${s.projects?.length || carousel ? "" : `<button class="primary" data-mkset="${s.id}">Send ${s.items.filter(i => i.product).length} to Ad Camera</button>`}</div>
    <div class="mxDayHead"><h2>${esc(s.label)}</h2>
      <div class="mxStats"><span>${esc(s.setup)}</span><span><b>${s.posts}</b> posts</span><span><b>${mins(s.minutes)}</b></span>
        <span><b>${filmed}</b> of ${mine.length} ${carousel ? "carousels in" : "filmed"}</span></div></div>
    <div class="mxCols wide">
      <ol class="mxSteps">
        ${step("setup", "Set up", `<p class="mxNote">${esc(s.setup)}.</p><p class="mxNote muted">${esc(s.tip)}</p><div class="mxDiagrams">${DG.setup(s.format)}</div>`)}
        ${step("light", `Light it <span class="muted">· ${s.light_min} min</span>`, `<div class="mxDiagrams">${DG.light(s.format)}</div>${lightTable(s.light)}`)}
        ${step("example", "Watch the example", `<p class="mxNote">Copy its framing, pacing and how the item is shown${carousel ? ", and the one line of on-image text" : ""}.</p>
          ${s.example ? `<p class="mxNote"><a href="${esc(s.example)}" target="_blank" rel="noopener">Open the example on TikTok ↗</a></p>` : `<p class="mxNote muted">No example yet: paste a TikTok link below.</p>`}
          <div class="row"><input id="exampleUrl" placeholder="Paste a different TikTok link for this shoot" value="${s.example_set ? esc(s.example) : ""}"><button data-go="example">Use</button></div>`)}
        ${step("pieces", carousel ? "Pull the item and the outfits around it" : "Lay out the pieces", `<table class="mxList"><tbody>${s.items.map(i => { const pr = byId("products", i.product);
          return `<tr><td translate="no">${esc(baseOf(i.name))}</td><td translate="no" class="muted">${esc(colorOf(i.name))}</td><td class="muted">${esc(pr?.fills?.size || "")}</td><td class="num">${i.takes} <span>${carousel ? (i.takes === 1 ? "carousel" : "carousels") : (i.takes === 1 ? "take" : "takes")}</span></td></tr>`; }).join("")}</tbody></table>
          ${carousel ? `<p class="mxNote muted">Each carousel needs 2–5 different outfits that all star its item: have the other pieces (tops, bottoms, shoes, layers) ready to rotate around it.</p>` : ""}`)}
        ${carousel
          ? step("film", "Shoot the carousels", `<p class="mxNote">For each carousel: lay the item flat in an outfit and take the photo straight down (phone parallel to the floor). Restyle it in a different outfit for the next photo, 2–5 photos in all. The item stays the star of every photo; only the pieces around it change.</p>
              <p class="mxNote">In Ad Camera tap <b>Shoot carousels</b>, pick these carousels and how many outfits: it walks you through every outfit with every product (all outfits for one product, or one outfit across the products), and each photo lands in its carousel's folder below. Say <b>“Ad Camera, action”</b> to take a photo hands-free.</p>
              <p class="mxNote muted">Photos taken another way: drop them on their carousel below, in order.</p>
              ${mine.map(x => kitPhotoRow(x)).join("")}`)
          : step("film", "Film in Ad Camera", `<p class="mxNote">On the iPhone open each project below in Ad Camera. Say <b>“Ad Camera, action”</b> to start and <b>“Ad Camera, cut”</b> to stop, or use the Apple Watch. Film the takes back to back, then swap to the next colour.</p>
              ${s.projects?.length ? `<table class="mxList"><tbody>${s.projects.map(pr => { const ps = mine.filter(x => x.sid === pr.sid), it = s.items.find(i => i.product === pr.product) || { takes: 0 }, have = ps[0]?.takes || 0;
                return `<tr><td translate="no">${esc(colorOf(prodName(pr.product)) || prodName(pr.product))}</td><td class="num">${have} of ${it.takes} <span>takes in</span></td><td>${have >= it.takes ? `<span class="mxPill ok">Filmed</span>` : have ? `<span class="mxPill wait">Filming</span>` : `<span class="mxPill">To film</span>`}</td><td class="num"><button data-open="${esc(pr.sid)}">Open</button></td></tr>`; }).join("")}</tbody></table>`
                : `<p class="mxNote muted">Send this setup to Ad Camera first (button at the top).</p>`}
              ${sc ? `<details class="mxScript"><summary>The script <span class="muted" translate="no">${esc(sc.title)}</span></summary><pre translate="no">${esc(sc.text)}</pre></details>` : ""}`)}
        ${step("after", carousel ? "When the photos are in" : "When the takes are in", carousel
          ? `<p class="mxNote">Open <b>Posting Kit</b> (Shoot Days) and press <b>Prepare Posting Kit</b>: each carousel's folder gets its description and on-image text line next to its photos.</p>`
          : `<p class="mxNote">Ad Factory pre-cuts every take and puts the captions on. Then open <b>Posting Kit</b> (Shoot Days) and press <b>Prepare Posting Kit</b>: each post gets its own folder with the finished video and its description, ready to schedule.</p>`)}
      </ol>
      <div class="mxSide">
        ${vid ? `<div class="mxLabel">The example</div><div id="exampleBox" data-ex="${esc(s.example)}"></div>` : ""}
        <div class="mxLabel">This shoot's posts</div>
        <ul class="mxRows">${mine.map(x => `<li class="nohover"><span class="num">${x.time}</span> <span translate="no">${esc(colorOf(x.name) || x.name)}</span> ${stepPill(x.step)}</li>`).join("")}</ul>
      </div>
    </div>`;
  showExample();
}
// the example to copy, as itself: a photo post's photos side by side, or a video in TikTok's resizable player
async function showExample() {
  const box = $("#exampleBox"); if (!box) return;
  const ex = await api(`/api/shop/example?url=${encodeURIComponent(box.dataset.ex)}`).catch(() => null);
  if (!ex) { box.innerHTML = `<p class="mxNote muted">Couldn't load the example here: open it on TikTok.</p>`; return; }
  box.innerHTML = ex.kind === "photos"
    ? `<div class="mxExStrip">${ex.images.map((f, i) => `<a href="/api/shop/example/${ex.id}/${f}" target="_blank" rel="noopener"><img src="/api/shop/example/${ex.id}/${f}" alt="Photo ${i + 1}" loading="lazy"><span>${i + 1}</span></a>`).join("")}</div>
       <p class="mxNote muted">${ex.images.length} photos${ex.author ? ` · @${esc(ex.author)}` : ""}</p>`
    : `<div class="mxPlayer"><iframe src="https://www.tiktok.com/player/v1/${ex.id}?description=0&music_info=0&rel=0&native_context_menu=0&closed_caption=0" allow="fullscreen; encrypted-media" loading="lazy" title="Example video"></iframe></div>`;
}
const STEP = { film: ["To film", ""], photos: ["Needs photos", ""], precut: ["Pre-cutting", "wait"], render: ["Footage in", "wait"], ready: ["Ready to post", "ok"], scheduled: ["Scheduled", "done"] };
const stepPill = s => { const [l, c] = STEP[s] || [s, ""]; return `<span class="mxPill ${c}">${l}</span>`; };
const kitPhotoRow = x => `<div class="mxDrop" data-photo-k="${x.k}"><div><b>Post ${x.n}</b> <span class="muted">${x.time} · <span translate="no">${esc(colorOf(x.name) || x.name)}</span></span></div>
  <div class="muted">${x.photos.length ? `${x.photos.length} of 2–5 photos in · ` : "Drop 2–5 photos here, or "}<label class="linkish">choose<input type="file" accept="image/*" multiple hidden data-photo-pick="${x.k}"></label></div></div>`;

// ---------- carousel shoots: plan the outfits and the on-screen text first, then watch each carousel fill in ----------
async function renderCarouselShoot(el, s, mine) {
  const cp = PL.cp = await api(`/api/shop/planner/day/${PL.day}/carousel/${s.id}`);
  const ticks = new Set(LS.get(`steps:${PL.day}:${s.id}`, []));
  const step = (k, title, body) => `<li class="mxStep ${ticks.has(k) ? "done" : ""}"><label class="mxStepHead"><input type="checkbox" data-step="${k}" ${ticks.has(k) ? "checked" : ""}><b>${title}</b></label><div class="mxStepBody">${body}</div></li>`;
  const n = cp.outfits.length, filled = mine.filter(x => x.photos.length).length, vid = tiktokId(s.example);
  el.innerHTML = `
    <div class="mxBar"><button data-go="shootback">‹ ${esc(dayName(PL.day, { weekday: "long", month: "short", day: "numeric" }))}</button></div>
    <div class="mxDayHead"><h2>${esc(s.label)}</h2>
      <div class="mxStats"><span>${esc(s.setup)}</span><span><b>${cp.products.length}</b> carousels × (cover + <b>${n}</b> outfits) = <b>${cp.products.length * (n + 1)}</b> photos</span><span><b>${mins(s.minutes)}</b></span><span><b>${filled}</b> of ${mine.length} started</span></div></div>
    <div class="mxRules"><b>Stay on track</b><ul>${cp.rules.map(r => `<li>${esc(r)}</li>`).join("")}</ul></div>
    <ol class="mxSteps">
      ${step("setup", "Set up", `<p class="mxNote">${esc(s.setup)}. Tape a rectangle on the floor where every item goes, so each photo is framed the same.</p><div class="mxDiagrams">${DG.setup(s.format)}</div>`)}
      ${step("light", `Light it <span class="muted">· ${s.light_min} min</span>`, `<div class="mxDiagrams">${DG.light(s.format)}</div>${lightTable(s.light)}`)}
      ${step("example", "Look at the example", `${vid ? `<div id="exampleBox" data-ex="${esc(s.example)}"></div>` : ""}
        <div><p class="mxNote">Copy how the item sits in the frame and the size and place of the text.</p>
        ${s.example ? `<p class="mxNote"><a href="${esc(s.example)}" target="_blank" rel="noopener">Open the example on TikTok ↗</a></p>` : ""}
        <div class="row"><input id="exampleUrl" placeholder="Paste a different TikTok link for this shoot" value="${s.example_set ? esc(s.example) : ""}"><button data-go="example">Use</button></div></div></div>`)}
      ${step("outfits", `The outfits <span class="muted">· already picked, the same for every product</span>`, `
        ${cp.kind ? `<p class="mxNote">A ${cp.kind === "top" ? "tops" : "bottoms"} shoot: pull these extra pieces once, they stay the same for every product.</p>` : ""}
        <div class="row"><span class="muted">How many</span><div class="mxSeg">${[2, 3, 4, 5].map(k => `<button data-ocount="${k}" class="${k === n ? "on" : ""}">${k}</button>`).join("")}</div></div>
        <div class="mxOutfitCards">${cp.outfits.map((o, i) => `<div class="mxOutfit"><div class="mxOutfitN">${i + 1}</div><div><b>${esc(o.name || "Outfit " + (i + 1))}</b>
          <div class="muted">${esc(cp.kind ? cp.extras[i] : [o.top, o.bottom, o.shoes, o.layer].filter(Boolean).join(" · "))}</div></div>
          <button data-oswap="${i}" title="Use a different ready-made outfit here">Swap</button></div>`).join("")}</div>
        <p class="mxNote muted">Each product takes its own place in the look (a top replaces the top, pants replace the bottom); Ad Camera tells you what to lay with each one. Don't own a piece? Swap the outfit, or <button class="linkish" data-go="oedit">change a piece</button>.</p>
        <div id="outfitEdit" hidden><table class="mxList mxOutfits"><thead><tr><th></th><th>Name</th><th>Top</th><th>Bottom</th><th>Shoes</th><th>Layer</th></tr></thead><tbody>
          ${cp.outfits.map((o, i) => `<tr data-oi="${i}"><td class="num">${i + 1}</td>${["name", "top", "bottom", "shoes", "layer"].map(k => `<td><input data-of="${k}" value="${esc(o[k] || "")}" placeholder="${k === "layer" ? "optional" : ""}"></td>`).join("")}</tr>`).join("")}</tbody></table>
          <div class="row"><span class="spacer"></span><button class="primary" data-go="outfitsave">Save Outfits</button></div></div>`)}
      ${step("text", "The on-screen text", `<p class="mxNote muted">One line on the first photo of each carousel. Varied on purpose so the day's carousels don't all say the same thing.</p>
        <table class="mxList"><tbody>${cp.products.map(r => `<tr><td translate="no" class="muted" style="width:34%">${esc(r.name)}</td><td><input data-ctext="${r.product}" value="${esc(r.text)}" translate="no"></td></tr>`).join("")}</tbody></table>
        <div class="row"><span class="spacer"></span><button class="primary" data-go="textsave">Save Text</button></div>`)}
      ${step("film", "Shoot", `<p class="mxNote">In Ad Camera tap <b>Shoot carousels</b>, pick these carousels and <b>${n}</b> outfits. Each carousel starts with its cover (the item on its own), then one photo per outfit; it shows what to lay out with each product and moves through every combination. Say <b>“Ad Camera, action”</b> for each photo.</p>
        <p class="mxNote muted">The previews below fill in as the photos arrive. Photos taken another way: drop them on their carousel.</p>`)}
      ${step("after", "When the photos are in", `<p class="mxNote">Check each preview, then <b>Posting Kit</b> → <b>Prepare Posting Kit</b>. Each carousel's folder has its photos in order and its text and description.</p>`)}
    </ol>
    <h3 class="secHead">Carousels <span class="muted">live preview, updates as photos come in</span></h3>
    <div class="mxCarousels" id="carouselPreviews">${carouselPreviews(cp, mine)}</div>`;
  clearInterval(PL.poll);
  PL.poll = setInterval(async () => {  // new photos pop in while Ad Camera is shooting
    const box = $("#carouselPreviews");
    if (!box || LS.get("planOpen", "") !== s.id) return clearInterval(PL.poll);
    const k = await api(`/api/shop/planner/day/${PL.day}/kit`).catch(() => null); if (!k) return;
    const now = k.posts.filter(x => x.set === s.id), sig = JSON.stringify(now.map(x => x.photos));
    if (sig !== PL.photoSig) { PL.photoSig = sig; PL.kit = k.posts; box.innerHTML = carouselPreviews(PL.cp, now); }
  }, 5000);
  PL.photoSig = JSON.stringify(mine.map(x => x.photos));
}
function carouselPreviews(cp, mine) {
  return mine.map(x => {
    const r = cp.products.find(y => y.product === x.product) || { text: "", with: [] };
    const byOutfit = i => x.photos.find(f => f.startsWith(`outfit-${i + 1}.`));
    const extra = x.photos.filter(f => !f.startsWith("outfit-"));
    const slides = [{ photo: x.photos.find(f => f.startsWith("outfit-0.")), label: "Cover", with: "", cover: true }]
      .concat(cp.outfits.map((o, i) => ({ photo: byOutfit(i), label: `${i + 1}. ${o.name || "Outfit " + (i + 1)}`, with: r.with[i] || "" })))
      .concat(extra.map(f => ({ photo: f, label: "Added", with: "" })));
    const got = slides.filter(z => z.photo).length, want = cp.outfits.length + 1;
    return `<div class="mxCar" data-photo-k="${x.k}">
      <div class="mxCarHead"><b translate="no">${esc(colorOf(x.name) || x.name)}</b><span class="muted">${x.time} · ${got} of ${want}</span></div>
      <div class="mxCarStrip">${slides.map((z, i) => `<div class="mxSlide ${z.photo ? "has" : ""}">
        ${z.photo ? `<img src="/api/shop/planner/day/${PL.day}/kit/${x.k}/file/${encodeURIComponent(z.photo)}" alt="" loading="lazy">` : `<div class="mxSlot"><b>${esc(z.label)}</b><span>${z.cover ? "the item on its own" : "with " + esc(z.with)}</span></div>`}
        ${i === 0 && r.text ? `<div class="mxOnText" translate="no">${esc(r.text)}</div>` : ""}<span class="mxSlideN">${i + 1}</span></div>`).join("")}</div>
      <div class="mxCarFoot muted">${baseOf(x.name) ? `<span translate="no">${esc(baseOf(x.name))}</span> · ` : ""}<label class="linkish">add photos<input type="file" accept="image/*" multiple hidden data-photo-pick="${x.k}"></label></div></div>`;
  }).join("");
}
async function carouselClick(e) {
  const go = e.target.closest("[data-go]")?.dataset.go, sid = LS.get("planOpen", "");
  const read = () => $$(".mxOutfits tbody tr").map(tr => Object.fromEntries($$("[data-of]", tr).map(i => [i.dataset.of, i.value])));
  if (go === "outfitmore" || go === "outfitless") {
    const o = read(), base = ["Clean and light", "All dark", "Cozy grey", "Earth tones", "Layered"];
    if (go === "outfitmore") o.push({ name: base[o.length] || `Outfit ${o.length + 1}`, top: "", bottom: "", shoes: "", layer: "" }); else o.pop();
    await api(`/api/shop/planner/day/${PL.day}/carousel/${sid}`, { json: { outfits: o } }); renderPlanner(); return true;
  }
  const oc = e.target.closest("[data-ocount]");
  if (oc) { await api(`/api/shop/planner/day/${PL.day}/carousel/${sid}`, { json: { count: +oc.dataset.ocount } }); renderPlanner(); return true; }
  const sw = e.target.closest("[data-oswap]");
  if (sw) { await api(`/api/shop/planner/day/${PL.day}/carousel/${sid}`, { json: { swap: +sw.dataset.oswap } }); renderPlanner(); return true; }
  if (go === "oedit") { $("#outfitEdit").hidden = !$("#outfitEdit").hidden; return true; }
  if (go === "outfitsave") { await api(`/api/shop/planner/day/${PL.day}/carousel/${sid}`, { json: { outfits: read() } }); toast("Outfits saved: Ad Camera shows them while shooting"); renderPlanner(); return true; }
  if (go === "textsave") {
    const texts = Object.fromEntries($$("[data-ctext]").map(i => [i.dataset.ctext, i.value]));
    await api(`/api/shop/planner/day/${PL.day}/carousel/${sid}`, { json: { texts } }); toast("On-screen text saved"); renderPlanner(); return true;
  }
  return false;
}

// ---------- posting kit: one folder per post, progress from footage to scheduled ----------
async function renderKit(box, day) {
  const kit = await api(`/api/shop/planner/day/${day}/kit`), job = kit.job, ps = kit.posts;
  const n = k => ps.filter(x => x.step === k).length;
  PL.kit = ps;
  box.innerHTML = `
    <div class="mxStats" style="margin-bottom:12px"><span><b>${ps.length - n("film") - n("photos")}</b> of ${ps.length} filmed</span><span><b>${n("ready")}</b> ready to post</span><span><b>${n("scheduled")}</b> scheduled</span>
      <span class="muted">folder: <span translate="no">${esc(kit.folder)}</span></span></div>
    <div class="mxBar"><button class="primary" data-go="kitbuild" ${job.running ? "disabled" : ""} title="A folder + description for every post; renders and copies each video whose footage is in">Prepare Posting Kit</button>
      ${job.running || job.msg ? `<span class="muted">${esc(job.msg || "")}</span>` : ""}</div>
    <div class="tblWrap"><table class="tbl mxKit"><thead><tr><th></th><th>Time</th><th>Post</th><th>Status</th><th>Description</th><th></th></tr></thead><tbody>
      ${ps.map(x => `<tr class="${x.scheduled ? "closed" : ""}"><td><input type="checkbox" data-mark="${x.k}" ${x.scheduled ? "checked" : ""} title="Scheduled"></td>
        <td class="num">${x.time}</td><td><b>${esc(x.label)}</b><div class="muted" translate="no">${esc(x.name)}</div></td><td>${stepPill(x.step)}</td>
        <td class="desc" translate="no">${esc(x.description)}</td>
        <td class="num acts"><button data-copy="${x.k}" title="Copy the description">Copy</button>
          ${x.video_file ? `<a class="btnlike" href="/api/shop/planner/day/${day}/kit/${x.k}/file/video.mp4" download>Video</a>` : ""}
          ${x.carousel ? `<label class="btnlike">Photos${x.photos.length ? ` (${x.photos.length})` : ""}<input type="file" accept="image/*" multiple hidden data-photo-pick="${x.k}"></label>` : ""}
          <button data-kitopen="${x.k}" title="Open this post's folder on the PC">Folder</button></td></tr>`).join("")}</tbody></table></div>`;
  if (job.running) setTimeout(() => { if (document.body.contains(box)) renderKit(box, day); }, 3000);
}
function kitClick(e, day, again) {
  const go = e.target.closest("[data-go]")?.dataset.go;
  if (go === "kitbuild") { api(`/api/shop/planner/day/${day}/kit/build`, { json: {} }).then(() => { toast("Preparing the posting kit…"); again(); }); return true; }
  const c = e.target.closest("[data-copy]");
  if (c) { const x = (PL.kit || []).find(y => y.k === +c.dataset.copy); navigator.clipboard?.writeText(x?.description || "").then(() => toast("Description copied")); return true; }
  const o = e.target.closest("[data-kitopen]"); if (o) { api(`/api/shop/planner/day/${day}/kit/${o.dataset.kitopen}/open`, { json: {} }).catch(err => toast(err.message)); return true; }
  const sh = e.target.closest("[data-open]"); if (sh) { openShoot(sh.dataset.open); return true; }
  return false;
}
async function uploadPhotos(day, k, files) {
  let n = 0;
  for (const f of files) {
    await fetch(`/api/shop/planner/day/${day}/kit/${k}/photo?name=${encodeURIComponent(f.name)}`, { method: "PUT", body: f });
    n++; toast(`Photo ${n} of ${files.length} saved`);
  }
}
document.addEventListener("change", async e => {
  const k = e.target.dataset?.photoPick; if (k == null || !e.target.files?.length) return;
  await uploadPhotos(PL.day, +k, [...e.target.files]); PANES[LS.get("homeTab", "today")]?.();
});
document.addEventListener("dragover", e => { const z = e.target.closest?.("[data-photo-k]"); if (z) { e.preventDefault(); z.classList.add("over"); } });
document.addEventListener("dragleave", e => e.target.closest?.("[data-photo-k]")?.classList.remove("over"));
document.addEventListener("drop", async e => {
  const z = e.target.closest?.("[data-photo-k]"); if (!z) return;
  e.preventDefault(); z.classList.remove("over");
  const files = [...e.dataTransfer.files].filter(f => f.type.startsWith("image/"));
  if (files.length) { await uploadPhotos(PL.day, +z.dataset.photoK, files); renderPlanner(); }
});
$("#panePlanner").addEventListener("change", e => {
  const st = e.target.dataset.step; if (st == null) return;
  const key = `steps:${PL.day}:${LS.get("planOpen", "")}`, have = new Set(LS.get(key, []));
  e.target.checked ? have.add(st) : have.delete(st); LS.set(key, [...have]);
  e.target.closest(".mxStep")?.classList.toggle("done", e.target.checked);
});

// ---------- Today: the shoot day as a runbook ----------
async function renderToday() {
  const el = $("#paneToday");
  const [d] = await Promise.all([shopLoad()]);
  [PL.days, PL.cfg] = await Promise.all([api("/api/shop/planner/days"), api("/api/shop/planner/settings")]);
  const today = todayIso(), planned = PL.days.filter(x => x.date >= today && x.projects + x.blocks_done > 0);
  const day = planned[0]?.date;
  const alerts = (d.summary?.alerts || []).slice(0, 5);
  const alertBox = alerts.length ? `<div class="mxGroup"><div class="mxLabel">Needs attention</div><ul class="mxRows">${alerts.map(a => `<li class="lvl-${a.level}" data-alert="${a.order || a.sid || ""}" data-kind="${a.kind}">${esc(a.text)}</li>`).join("")}</ul></div>` : "";
  if (!day) {
    el.innerHTML = `<div class="mxEmpty"><h2>No shoot day planned</h2><p class="muted">Plan one in Shoot Days and send its sets to Ad Camera; it shows up here as a step-by-step runbook.</p>
      <button class="primary" data-go="toplanner">Open Shoot Days</button></div>${alertBox}`;
    return;
  }
  PL.day = day; PL.plan = await api(`/api/shop/planner/day/${day}`);
  const p = PL.plan, done = new Set(p.blocks_done || []);
  const isToday = day === today, now = new Date().getHours() * 60 + new Date().getMinutes();
  const work = p.blocks.filter(b => b.kind !== "live");
  const current = isToday ? work.find(b => toMin(b.end) > now && !done.has(bkey(b))) : work.find(b => !done.has(bkey(b)));
  const sel = work.find(b => bkey(b) === PL.sel) || current || work[0];
  const tickable = work.filter(b => !["gym", "meal"].includes(b.kind)), nDone = tickable.filter(b => done.has(bkey(b))).length;
  el.innerHTML = `
    <div class="mxDayHead"><h2>${isToday ? "Today" : "Next shoot day"} <span class="muted">· ${esc(dayName(day))}</span></h2>
      <div class="mxStats"><span><b>${nDone}</b> of ${tickable.length} steps done</span><span><b>${p.posts.length}</b> posts</span>
        <span><b>${p.sets.reduce((a, s) => a + s.projects.length, 0)}</b> projects in Ad Camera</span></div>
      <div class="mxProgress"><i style="width:${Math.round(100 * nDone / Math.max(1, tickable.length))}%"></i></div></div>
    <div class="mxCols">
      <div class="mxSide">
        <ol class="mxAgenda tick">${work.map(b => { const k = bkey(b), t = !["gym", "meal"].includes(b.kind);
          return `<li class="k-${b.kind} ${done.has(k) ? "done" : ""} ${b === current ? "now" : ""} ${b === sel ? "sel" : ""}" data-sel="${esc(k)}">
            ${t ? `<input type="checkbox" data-block="${esc(k)}" ${done.has(k) ? "checked" : ""} aria-label="Done">` : `<span class="nob"></span>`}
            <span class="t">${b.start}</span><span class="w">${esc(shortTitle(b, p))}</span><span class="d muted">${mins(span(b))}</span></li>`; }).join("")}</ol>
        ${alertBox}
      </div>
      <div class="mxMain">${sel ? blockDetail(sel, p) : ""}</div>
    </div>`;
}
function blockDetail(b, p) {
  const head = `<div class="mxDetailHead"><span class="mxKind k-${b.kind}">${KIND_LABEL[b.kind] || b.kind}</span><h3>${esc(b.kind === "shoot" ? shortTitle(b, p) : b.title)}</h3><span class="muted">${b.start}–${b.end}</span></div>`;
  if (b.kind === "shoot") { const s = p.sets.find(x => x.id === b.set); return head + (s ? setCard(s) : ""); }
  if (b.kind === "prep") {  // every piece the day uses, grouped by item, with its size
    const seen = new Map();
    for (const s of p.sets) for (const i of s.items) if (i.product && !seen.has(i.product)) seen.set(i.product, i.name);
    return head + `<section class="mxCard"><div class="mxCardBody"><div class="mxField"><div class="mxLabel">Pull, steam, de-lint, tags off</div>
      <table class="mxList"><tbody>${[...seen].map(([id, name]) => `<tr><td translate="no">${esc(baseOf(name))}</td><td translate="no" class="muted">${esc(colorOf(name))}</td><td class="muted">${esc(byId("products", id)?.fills?.size || "")}</td></tr>`).join("")}</tbody></table></div>
      <div class="mxField"><div class="mxLabel">Set up</div><p class="mxNote">${[...new Set(p.sets.map(s => s.setup))].map(esc).join(" · ")}</p>
        <p class="mxNote muted">Lights: key light (circle) + two fill panels, all at 5600K, room lights off.</p></div></div></section>`;
  }
  if (b.kind === "edit") {
    const projects = p.sets.flatMap(s => s.projects.map(x => ({ ...x, set: s.label })));
    return head + `<section class="mxCard"><div class="mxCardBody"><div class="mxField"><div class="mxLabel">The day's projects</div>
      ${projects.length ? `<table class="mxList"><tbody>${projects.map(x => `<tr class="link" data-open="${esc(x.sid)}"><td>${esc(x.set)}</td><td translate="no" class="muted">${esc(x.title.split(" · ").slice(2).join(" · "))}</td><td class="num">Open ›</td></tr>`).join("")}</tbody></table>`
        : `<p class="mxNote muted">Send the sets to Ad Camera first (Shoot Days).</p>`}</div>
      <p class="mxNote muted">Carousels: assemble the photos with the on-image text. Videos: raw takes land in the shoot and get pre-cut; check them and keep the best.</p></div></section>`;
  }
  if (b.kind === "post") return head + `<section class="mxCard"><div class="mxCardBody"><div class="mxField"><div class="mxLabel">Schedule in TikTok Studio · tick each one once it's scheduled</div>
      <table class="mxList"><tbody>${p.posts.map((x, k) => `<tr class="${x.done ? "closed" : ""}"><td><input type="checkbox" data-mark="${k}" ${x.done ? "checked" : ""}></td><td class="num">${x.time}</td>
        <td>${esc((PL.cfg.formats.find(f => f.key === x.format) || {}).label || x.format)}</td><td translate="no" class="muted">${esc(x.name)}</td></tr>`).join("")}</tbody></table></div>
      <p class="mxNote muted">Check the TikTok Shop product link is on each scheduled post before it goes live.</p></div></section>`;
  if (b.kind === "research") return head + `<section class="mxCard"><div class="mxCardBody"><p class="mxNote">How yesterday's posts did, what competitors posted and sold, and what to put in the next lineup.</p>
      <div class="mxBtns"><button data-go="toanalytics">Our Accounts</button><button data-go="tocompetitors">Competitors</button><button data-go="toplanner">Plan the next day</button></div></div></section>`;
  return head;
}
$("#paneToday").addEventListener("click", async e => {
  const go = e.target.closest("[data-go]")?.dataset.go;
  if (go) return showHomeTab({ toplanner: "planner", toanalytics: "analytics", tocompetitors: "competitors" }[go]);
  const o = e.target.closest("[data-open]"); if (o) return openShoot(o.dataset.open);
  const mk = e.target.closest("[data-mkset]"); if (mk) return makeSet(mk, renderToday);
  const al = e.target.closest("[data-alert]");
  if (al) { if (al.dataset.kind === "link") { LS.set("prodNeedLink", true); return showHomeTab("products"); } return al.dataset.kind === "film" ? openShoot(al.dataset.alert) : editThing("orders", byId("orders", al.dataset.alert)); }
  const r = e.target.closest("[data-sel]"); if (r && !e.target.matches("input")) { PL.sel = r.dataset.sel; renderToday(); }
});
$("#paneToday").addEventListener("change", async e => {
  const b = e.target.dataset.block;
  if (b != null) { await api(`/api/shop/planner/day/${PL.day}/block`, { json: { key: b, done: e.target.checked } }); return renderToday(); }
  if (e.target.dataset.mark != null) markPost(PL.day, e.target);
});

// ---------- Settings ----------
async function plannerSettings() {
  const cfg = await api("/api/shop/planner/settings"), st = cfg.settings;
  const chans = Object.fromEntries((st.channels || []).map(c => [c.account, c]));
  const lineup = new Set(st.lineup || []);
  const dlg = document.createElement("dialog"); dlg.className = "shopDlg plDlg mxSheet";
  const num = (k, v, w = 60) => `<input type="number" min="0" data-k="${k}" value="${v}" style="width:${w}px">`;
  dlg.innerHTML = `<form><h3>Planner Settings</h3>
    <p class="muted">Defaults follow @sully.finds: ~20 posts a channel on weekdays, Saturday light, posting 3–8 pm, carousels for reach, near-identical takes per product.</p>
    <h4>Posts per channel</h4><div class="plRow">${cfg.weekdays.map(w => `<label>${w}<br>${num("posts." + w, st.posts[w], 52)}</label>`).join("")}</div>
    <h4>Formats <span class="fhint">% of each channel's posts · takes per product · minutes</span></h4>
    <table class="tbl plMix"><thead><tr><th></th><th>Mix</th><th>Takes</th><th>Lights</th><th>Shoot</th><th>Edit</th></tr></thead>${cfg.formats.map(f => `<tr><td><b>${esc(f.label)}</b><div class="muted small">${esc(f.tip)}</div></td><td>${num("mix." + f.key, st.mix[f.key])} %</td><td>× ${num("takes." + f.key, st.takes[f.key], 48)}</td>
      <td>${num("minutes." + f.key + ".light_min", st.minutes?.[f.key]?.light_min ?? f.light_min, 48)} min</td><td>${num("minutes." + f.key + ".take_min", st.minutes?.[f.key]?.take_min ?? f.take_min, 52)} min</td><td>${num("minutes." + f.key + ".edit_min", st.minutes?.[f.key]?.edit_min ?? f.edit_min, 52)} min</td></tr>`).join("")}</table>
    <h4>The day</h4>
    <div class="plRow"><label>Start ${tIn("day.start", st.day.start)}</label><label>End ${tIn("day.end", st.day.end)}</label>
      <label>Post from ${tIn("day.post_from", st.day.post_from)}</label><label>to ${tIn("day.post_to", st.day.post_to)}</label>
      <label>Prep ${num("day.prep_min", st.day.prep_min ?? 30, 52)} min</label><label>Research ${num("day.research_min", st.day.research_min, 52)} min</label></div>
    <div class="plRow"><label class="chk"><input type="checkbox" data-k="day.schedule" ${st.day.schedule !== false ? "checked" : ""}> Schedule posts ahead in TikTok Studio</label>
      <label>${num("day.schedule_min", st.day.schedule_min ?? 1.5, 52)} min per post</label></div>
    <div class="plRow"><label>Gym at ${tIn("day.gym.at", st.day.gym.at)}</label><label>for ${num("day.gym.min", st.day.gym.min, 52)} min</label></div>
    <div class="plRow plMeals">${st.day.meals.map((m, i) => `<label><input data-meal="${i}" data-f="name" value="${esc(m.name)}" style="width:90px"> at <input type="time" data-meal="${i}" data-f="at" value="${m.at}"> for <input type="number" data-meal="${i}" data-f="min" value="${m.min}" style="width:52px"> min</label>`).join("")}</div>
    <h4>Channels</h4>
    ${cfg.accounts.map(a => { const c = chans[a.id] || {}; return `<div class="plRow plChan" data-acc="${a.id}"><label class="chk"><input type="checkbox" data-f="on" ${!st.channels.length || chans[a.id] ? "checked" : ""}> <b translate="no">${esc(a.name)}</b></label>
      <label>POV <select data-f="pov"><option value="me" ${c.pov !== "partner" ? "selected" : ""}>the wearer talks ("I'm 6'1…")</option><option value="partner" ${c.pov === "partner" ? "selected" : ""}>someone else talks ("He's 6'1…")</option></select></label>
      <label>Height <input data-f="height" value="${esc(c.height || "")}" placeholder="6'1 160" style="width:90px"></label>
      <label>Sizes <input data-f="size_bottom" value="${esc(c.size_bottom || "")}" placeholder="32x32" style="width:70px"> <input data-f="size_top" value="${esc(c.size_top || "")}" placeholder="L" style="width:44px"></label>
      <details class="plCant"><summary>Can't wear (${(c.cant_wear || []).length})</summary>${products().map(p => `<label class="chk"><input type="checkbox" data-cant="${p.id}" ${(c.cant_wear || []).includes(p.id) ? "checked" : ""}> <span translate="no">${esc(p.name)}</span></label>`).join("")}</details></div>`; }).join("") || `<p class="muted">No accounts yet.</p>`}
    <h4>Product lineup <span class="fhint">none ticked = every product with a TikTok Shop link</span></h4>
    <div class="plLineup">${products().map(p => `<label class="chk"><input type="checkbox" data-lineup="${p.id}" ${lineup.has(p.id) ? "checked" : ""}> <span translate="no">${esc(p.name)}</span></label>`).join("")}</div>
    <div class="sdBtns"><span class="spacer"></span><button type="button" data-close>Cancel</button><button class="primary" data-save>Save and Rebuild Day</button></div></form>`;
  document.body.appendChild(dlg);
  $("[data-close]", dlg).onclick = () => dlg.close();
  $("form", dlg).onsubmit = e => e.preventDefault();
  $("[data-save]", dlg).onclick = async () => {
    const out = { posts: {}, mix: {}, takes: {}, day: { gym: {}, meals: [] } };
    $$("[data-k]", dlg).forEach(i => {
      const path = i.dataset.k.split("."), v = i.type === "checkbox" ? i.checked : i.type === "number" ? Number(i.value || 0) : i.value;
      let o = out; path.slice(0, -1).forEach(p => (o = o[p] ||= {})); o[path.at(-1)] = v;
    });
    st.day.meals.forEach((_, i) => out.day.meals.push({ name: $(`[data-meal="${i}"][data-f=name]`, dlg).value, at: $(`[data-meal="${i}"][data-f=at]`, dlg).value, min: +$(`[data-meal="${i}"][data-f=min]`, dlg).value || 0 }));
    out.channels = $$(".plChan", dlg).filter(r => $("[data-f=on]", r).checked).map(r => ({ account: r.dataset.acc, pov: $("[data-f=pov]", r).value,
      height: $("[data-f=height]", r).value.trim(), size_bottom: $("[data-f=size_bottom]", r).value.trim(), size_top: $("[data-f=size_top]", r).value.trim(), cant_wear: $$("[data-cant]", r).filter(i => i.checked).map(i => i.dataset.cant) }));
    out.lineup = $$("[data-lineup]", dlg).filter(i => i.checked).map(i => i.dataset.lineup);
    await api("/api/shop/planner/settings", { json: out });
    await api(`/api/shop/planner/day/${PL.day}/rebuild`, { json: {} });
    dlg.close(); toast("Saved: the day is rebuilt"); renderPlanner();
  };
  dlg.onclose = () => dlg.remove();
  dlg.showModal();
}
function tIn(k, v) { return `<input type="time" data-k="${k}" value="${esc(v)}">`; }
// ---------- Lineup: what's in rotation, item by item with its colourways (the full product list is one click away) ----------
const lineSeg = v => `<div class="mxBar"><div class="mxSeg">${[["rotation", "In Rotation"], ["all", "All Products and Orders"]].map(([k, l]) => `<button data-lview="${k}" class="${v === k ? "on" : ""}">${l}</button>`).join("")}</div>
  <span class="spacer"></span>${v === "rotation" ? `<button data-go="plsettings" title="Pick which products the planner rotates through">Edit Rotation</button>` : ""}</div>`;
async function renderLineup() {
  const el = $("#paneProducts"), view = LS.get("lineupView", "rotation");
  if (view !== "rotation") return renderProducts();
  await shopLoad();
  PL.cfg = await api("/api/shop/planner/settings");
  const st = PL.cfg.settings, all = products(), ids = new Set(st.lineup || []);
  const rot = ids.size ? all.filter(p => ids.has(p.id)) : all.filter(p => isShopLink(p.link));
  const groups = new Map();
  for (const p of rot) { const k = baseOf(p.name); if (!groups.has(k)) groups.set(k, []); groups.get(k).push(p); }
  const cant = pid => (st.channels || []).filter(c => (c.cant_wear || []).includes(pid)).map(c => byId("accounts", c.account)?.name).filter(Boolean);
  el.innerHTML = lineSeg(view) + `
    <div class="mxStats" style="margin-bottom:14px"><span><b>${groups.size}</b> items</span><span><b>${rot.length}</b> colourways</span>
      <span>every colourway gets its own posts, the way @sully.finds lists them</span></div>
    <div class="tblWrap"><table class="tbl mxRot"><thead><tr><th>Item</th><th>Colourways</th><th>TikTok price</th><th></th></tr></thead><tbody>
    ${[...groups].map(([name, ps]) => { const p0 = ps[0], no = [...new Set(ps.flatMap(p => cant(p.id)))];
      return `<tr><td><b translate="no">${esc(name)}</b><div class="muted">${esc(p0.brand || "")}${no.length ? ` · not worn on ${esc(no.join(", "))}` : ""}</div></td>
        <td>${ps.map(p => `<span class="mxChip" data-edit-prod="${p.id}" translate="no">${esc(colorOf(p.name) || "one colour")} <span class="muted">${esc(p.fills?.size || "")}</span></span>`).join("")}</td>
        <td class="num">${esc(p0.price || "–")}</td><td class="num">${p0.link ? `<a href="${esc(p0.link)}" target="_blank" rel="noopener">TikTok Shop ↗</a>` : ""}</td></tr>`; }).join("")
      || `<tr><td colspan="4" class="muted">Nothing in rotation yet: products with a TikTok Shop link rotate automatically, or pick them in Edit Rotation.</td></tr>`}</tbody></table></div>`;
}
$("#paneProducts").addEventListener("click", e => {
  const v = e.target.closest("[data-lview]"); if (v) { LS.set("lineupView", v.dataset.lview); return renderLineup(); }
  if (e.target.closest("[data-go=plsettings]")) return plannerSettings();
  const ep = e.target.closest("[data-edit-prod]"); if (ep && LS.get("lineupView", "rotation") === "rotation") editThing("products", byId("products", ep.dataset.editProd));
});
const _renderProducts = renderProducts;  // shop.js re-renders the full list itself (filters, tabs): keep the view switch on top
renderProducts = async function () { await _renderProducts(); if (LS.get("lineupView", "rotation") !== "rotation") $("#paneProducts").insertAdjacentHTML("afterbegin", lineSeg("all")); };
// ---------- sidebar: is the Ad Camera app connected? ----------
async function camStatus() {
  const s = await api("/api/camera/status").catch(() => null), el = $("#camStat"); if (!s || !el) return;
  const last = Math.max(s.seen || 0, s.upload || 0), fresh = last && Date.now() / 1000 - last < 600;
  el.innerHTML = `<i class="sdot ${fresh ? "ok" : ""}"></i>Ad Camera <span class="muted">${last ? (s.upload && s.upload >= s.seen ? "take received " : "synced ") + ago(last) : "not connected yet"}</span>`;
}
camStatus(); setInterval(camStatus, 60000);
PANES.products = renderLineup;
PANES.planner = renderPlanner;
PANES.today = renderToday;
