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
      : `<button class="primary" data-mkset="${s.id}" ${n ? "" : "disabled"} title="One project per product, with the script and how many takes">Send ${n} to Ad Camera</button>`}</footer>`}
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
      <button data-go="plrebuild" title="Make the day again from the settings (ticks and Ad Camera projects are kept)">Rebuild Day</button>
      <button data-go="plsettings">Settings</button>
    </div>
    ${!PL.cfg.accounts.length ? `<div class="mxBanner">Add your TikTok accounts first (Our Accounts → Accounts): the planner makes a day per channel.</div>` : ""}
    <div class="mxDayHead"><h2>${esc(dayName(PL.day))}</h2>
      <div class="mxStats"><span><b>${p.posts.length}</b> posts</span><span><b>${p.sets.length}</b> setups</span><span><b>${mins(shoot)}</b> shooting</span><span><b>${mins(edit)}</b> editing</span>${ends ? `<span>done by <b>${ends}</b></span>` : ""}</div></div>
    <div class="mxCols">
      <div class="mxSide">
        <div class="mxLabel">Schedule</div>
        <ol class="mxAgenda">${p.blocks.map(b => `<li class="k-${b.kind}" ${b.set ? `data-goto="${b.set}"` : ""}>
          <span class="t">${b.start}</span><span class="w">${esc(shortTitle(b, p))}</span><span class="d muted">${mins(span(b))}</span></li>`).join("")}</ol>
        <details class="mxPosts"><summary>Posting times <span class="muted">${p.posts.length} posts, ${set.day.post_from}–${set.day.post_to}</span></summary>
          <table class="mxList"><tbody>${p.posts.map((x, k) => `<tr class="${x.done ? "closed" : ""}"><td><input type="checkbox" data-mark="${k}" ${x.done ? "checked" : ""} title="${set.day.schedule !== false ? "Scheduled" : "Posted"}"></td>
            <td class="num">${x.time}</td><td>${esc((PL.cfg.formats.find(f => f.key === x.format) || {}).label || x.format)}</td><td translate="no" class="muted">${esc(x.name)}</td></tr>`).join("")}</tbody></table></details>
      </div>
      <div class="mxMain">${p.sets.map(s => setCard(s)).join("") || `<div class="mxEmpty">Nothing planned this day. Posts per channel for this weekday are set to 0 in Settings.</div>`}</div>
    </div>`;
}
$("#panePlanner").addEventListener("click", async e => {
  const d = e.target.closest("[data-day]"); if (d) { LS.set("planDay", d.dataset.day); return renderPlanner(); }
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
