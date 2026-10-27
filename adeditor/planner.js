/* 🗓 Planner (adcut/planner.py): the day as shoot sets, edit, research and a posting window, built the
   way @sully.finds works (docs/sully-finds-study.md). Each set can become Ad Camera projects. */
"use strict";
const PL = { day: null, plan: null, cfg: null };
const todayIso = () => { const d = new Date(); return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10); };
const addDays = (iso, n) => { const d = new Date(iso + "T12:00"); d.setDate(d.getDate() + n); return d.toISOString().slice(0, 10); };
const mins = m => m >= 60 ? `${Math.floor(m / 60)}h ${String(Math.round(m % 60)).padStart(2, "0")}m` : `${Math.round(m)} min`;
const KIND = { gym: ["🏋️", "#ff8787"], meal: ["🍽", "#ffd43b"], shoot: ["🎬", "#21a366"], edit: ["✂️", "#74c0fc"], research: ["🔎", "#b197fc"], post: ["📤", "#25f4ee"] };
const FMT_ICON = { carousel: "🖼", flatlay_vo: "👉", worn: "👖", held: "✋", skit: "🎭", other: "✨" };

async function renderPlanner() {
  const el = $("#panePlanner");
  PL.day = LS.get("planDay", "") || todayIso();
  if (PL.day < todayIso()) PL.day = todayIso();
  await shopLoad();
  [PL.plan, PL.cfg] = await Promise.all([api(`/api/shop/planner/day/${PL.day}`), api("/api/shop/planner/settings")]);
  const p = PL.plan;
  const shoot = p.sets.reduce((a, s) => a + s.minutes, 0), edit = p.sets.reduce((a, s) => a + s.edit_minutes, 0);
  const done = p.posts.filter(x => x.done).length;
  const dayName = new Date(PL.day + "T12:00").toLocaleDateString(window.LANG === "pt" ? "pt-BR" : "en-US", { weekday: "long", month: "short", day: "numeric" });
  el.innerHTML = `<div class="tbar"><button data-pd="-1" title="Previous day">◀</button><input type="date" id="planDate" value="${PL.day}" min="${todayIso()}"><button data-pd="1" title="Next day">▶</button>
      <button data-pd="0">Today</button><b class="plDay">${esc(dayName)}</b><span class="spacer"></span>
      <button data-go="plrebuild" title="Make the day again from the settings (posted marks are kept)">↻ Rebuild the day</button><button data-go="plsettings">⚙ Planner settings</button></div>
    ${!PL.cfg.accounts.length ? `<div class="sc setup"><b>Add your TikTok accounts first</b><p class="muted">The planner makes a day per channel (yours and his). Analytics → ⚙ Accounts.</p></div>` : ""}
    <div class="kpiRow">
      <div class="sc skpi"><span>Posts</span><b>${p.posts.length}</b><em>${p.posts_per_channel} per channel × ${p.channels} · ${done} posted</em></div>
      <div class="sc skpi"><span>Shooting</span><b>${mins(shoot)}</b><em>${p.sets.length} sets, one setup each</em></div>
      <div class="sc skpi"><span>Editing</span><b>${mins(edit)}</b><em>carousels + checking the pre-cuts</em></div>
      <div class="sc skpi"><span>Posting</span><b>${esc(PL.cfg.settings.day.post_from)}–${esc(PL.cfg.settings.day.post_to)}</b><em>${p.season} lineup</em></div></div>
    <div class="plGrid">
      <div><h3 class="secHead">The day</h3><ol class="plTime">${p.blocks.map(b => `<li class="k-${b.kind}" style="--c:${KIND[b.kind]?.[1] || "#888"}" ${b.set ? `data-goto="${b.set}"` : ""}>
          <span class="plT">${b.start}<br><span class="muted">${b.end}</span></span><span class="plB"><span>${KIND[b.kind]?.[0] || ""}</span> <span>${esc(b.title)}</span></span></li>`).join("")}</ol></div>
      <div><h3 class="secHead">Shoot sets <span class="muted">one setup each, product after product</span></h3>
        ${p.sets.map(s => { const n = s.items.filter(i => i.product).length, sc = byId("scripts", s.script);
          return `<div class="sc plSet" id="set-${s.id}"><div class="qt"><b>${FMT_ICON[s.format] || ""} ${esc(s.label)}</b><span class="muted"><span translate="no">${esc(s.channel_name)}</span> · <span>${s.pov === "me" ? "your POV" : "partner POV"}</span></span></div>
            <div class="muted small">📍 ${esc(s.setup)} · ${s.posts} posts · ~${mins(s.minutes)}</div>
            <div class="hint">${esc(s.tip)}</div>
            <ul class="plItems">${s.items.map(i => `<li><span translate="no">${esc(i.name)}</span> <b>× ${i.takes}</b></li>`).join("")}</ul>
            ${sc ? `<div class="qm muted">📝 <span translate="no">${esc(sc.title)}</span></div>` : ""}
            <div class="qa">${s.projects?.length ? `<span class="okx">✓ ${s.projects.length} project${s.projects.length === 1 ? "" : "s"} in Ad Camera</span>` :
              `<button class="primary" data-mkset="${s.id}" ${n ? "" : "disabled"} title="One project per product, with the script and how many takes">📷 Make ${n} Ad Camera project${n === 1 ? "" : "s"}</button>`}</div></div>`; }).join("") || `<p class="muted">No posts planned for this day.</p>`}</div></div>
    <h3 class="secHead">Posting schedule <span class="muted">tick each one once it's up</span></h3>
    <div class="tblWrap"><table class="tbl"><thead><tr><th></th><th>Time</th><th>Channel</th><th>Format</th><th>Product</th></tr></thead><tbody>
      ${p.posts.map((x, k) => `<tr class="${x.done ? "closed" : ""}"><td><input type="checkbox" data-mark="${k}" ${x.done ? "checked" : ""}></td><td>${x.time}</td>
        <td>${accChip(x.channel) || "–"}</td><td>${FMT_ICON[x.format] || ""} ${esc((PL.cfg.formats.find(f => f.key === x.format) || {}).label || x.format)}</td><td translate="no">${esc(x.name)}</td></tr>`).join("")}</tbody></table></div>`;
}
$("#panePlanner").addEventListener("click", async e => {
  const pd = e.target.closest("[data-pd]");
  if (pd) { const n = +pd.dataset.pd; LS.set("planDay", n ? addDays(PL.day, n) : todayIso()); return renderPlanner(); }
  const go = e.target.closest("[data-go]")?.dataset.go;
  if (go === "plrebuild") { await api(`/api/shop/planner/day/${PL.day}/rebuild`, { json: {} }); toast("Day rebuilt"); return renderPlanner(); }
  if (go === "plsettings") return plannerSettings();
  const mk = e.target.closest("[data-mkset]");
  if (mk) {
    mk.disabled = true; mk.textContent = "⏳ making projects…";
    try { const r = await api(`/api/shop/planner/day/${PL.day}/projects`, { json: { set: mk.dataset.mkset } }); toast(`📷 ${r.made.length} project${r.made.length === 1 ? "" : "s"} ready in Ad Camera (and the Queue)`, 5000); }
    catch (err) { toast(err.message, 6000); }
    return renderPlanner();
  }
  const g = e.target.closest("[data-goto]"); if (g) $(`#set-${g.dataset.goto}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
});
$("#panePlanner").addEventListener("change", async e => {
  if (e.target.id === "planDate") { LS.set("planDay", e.target.value || todayIso()); return renderPlanner(); }
  if (e.target.dataset.mark != null) { await api(`/api/shop/planner/day/${PL.day}/mark`, { json: { k: +e.target.dataset.mark, done: e.target.checked } }); e.target.closest("tr").classList.toggle("closed", e.target.checked); }
});

async function plannerSettings() {
  const cfg = await api("/api/shop/planner/settings"), st = cfg.settings;
  const chans = Object.fromEntries((st.channels || []).map(c => [c.account, c]));
  const lineup = new Set(st.lineup || []);
  const dlg = document.createElement("dialog"); dlg.className = "shopDlg plDlg";
  const num = (k, v, w = 60) => `<input type="number" min="0" data-k="${k}" value="${v}" style="width:${w}px">`;
  dlg.innerHTML = `<form><h3>⚙ Planner settings</h3>
    <p class="muted">Defaults follow @sully.finds: ~20 posts a channel on weekdays, Saturday light, posting 3–8 pm, carousels for reach, near-identical takes per product.</p>
    <h4>Posts per channel</h4><div class="plRow">${cfg.weekdays.map(w => `<label>${w}<br>${num("posts." + w, st.posts[w], 52)}</label>`).join("")}</div>
    <h4>Format mix <span class="fhint">% of each channel's posts · takes per product</span></h4>
    <table class="tbl plMix">${cfg.formats.map(f => `<tr><td>${FMT_ICON[f.key] || ""} ${esc(f.label)}<div class="muted small">${esc(f.tip)}</div></td><td>${num("mix." + f.key, st.mix[f.key])} %</td><td>× ${num("takes." + f.key, st.takes[f.key], 48)}</td></tr>`).join("")}</table>
    <h4>The day</h4>
    <div class="plRow"><label>Start ${tIn("day.start", st.day.start)}</label><label>End ${tIn("day.end", st.day.end)}</label>
      <label>Post from ${tIn("day.post_from", st.day.post_from)}</label><label>to ${tIn("day.post_to", st.day.post_to)}</label>
      <label>Setup per set ${num("day.setup_min", st.day.setup_min, 52)} min</label><label>Research ${num("day.research_min", st.day.research_min, 52)} min</label></div>
    <div class="plRow"><label>🏋️ Gym at ${tIn("day.gym.at", st.day.gym.at)}</label><label>for ${num("day.gym.min", st.day.gym.min, 52)} min</label></div>
    <div class="plRow plMeals">${st.day.meals.map((m, i) => `<label>🍽 <input data-meal="${i}" data-f="name" value="${esc(m.name)}" style="width:90px"> at <input type="time" data-meal="${i}" data-f="at" value="${m.at}"> for <input type="number" data-meal="${i}" data-f="min" value="${m.min}" style="width:52px"> min</label>`).join("")}</div>
    <h4>Channels</h4>
    ${cfg.accounts.map(a => { const c = chans[a.id] || {}; return `<div class="plRow plChan" data-acc="${a.id}"><label class="chk"><input type="checkbox" data-f="on" ${!st.channels.length || chans[a.id] ? "checked" : ""}> <b translate="no">${esc(a.name)}</b></label>
      <label>POV <select data-f="pov"><option value="me" ${c.pov !== "partner" ? "selected" : ""}>his own ("I'm 6'1…")</option><option value="partner" ${c.pov === "partner" ? "selected" : ""}>yours ("He's 6'1…")</option></select></label>
      <label>Height <input data-f="height" value="${esc(c.height || "")}" placeholder="6'1 160" style="width:90px"></label>
      <label>Sizes <input data-f="size_bottom" value="${esc(c.size_bottom || "")}" placeholder="32x32" style="width:70px"> <input data-f="size_top" value="${esc(c.size_top || "")}" placeholder="L" style="width:44px"></label></div>`; }).join("") || `<p class="muted">No accounts yet.</p>`}
    <h4>Product lineup <span class="fhint">none ticked = every product with a TikTok Shop link</span></h4>
    <div class="plLineup">${products().map(p => `<label class="chk"><input type="checkbox" data-lineup="${p.id}" ${lineup.has(p.id) ? "checked" : ""}> <span translate="no">${esc(p.name)}</span></label>`).join("")}</div>
    <div class="sdBtns"><span class="spacer"></span><button type="button" data-close>Cancel</button><button class="primary" data-save>Save + rebuild the day</button></div></form>`;
  document.body.appendChild(dlg);
  $("[data-close]", dlg).onclick = () => dlg.close();
  $("form", dlg).onsubmit = e => e.preventDefault();
  $("[data-save]", dlg).onclick = async () => {
    const out = { posts: {}, mix: {}, takes: {}, day: { gym: {}, meals: [] } };
    $$("[data-k]", dlg).forEach(i => {
      const path = i.dataset.k.split("."), v = i.type === "number" ? Number(i.value || 0) : i.value;
      let o = out; path.slice(0, -1).forEach(p => (o = o[p] ||= {})); o[path.at(-1)] = v;
    });
    st.day.meals.forEach((_, i) => out.day.meals.push({ name: $(`[data-meal="${i}"][data-f=name]`, dlg).value, at: $(`[data-meal="${i}"][data-f=at]`, dlg).value, min: +$(`[data-meal="${i}"][data-f=min]`, dlg).value || 0 }));
    out.channels = $$(".plChan", dlg).filter(r => $("[data-f=on]", r).checked).map(r => ({ account: r.dataset.acc, pov: $("[data-f=pov]", r).value,
      height: $("[data-f=height]", r).value.trim(), size_bottom: $("[data-f=size_bottom]", r).value.trim(), size_top: $("[data-f=size_top]", r).value.trim() }));
    out.lineup = $$("[data-lineup]", dlg).filter(i => i.checked).map(i => i.dataset.lineup);
    await api("/api/shop/planner/settings", { json: out });
    await api(`/api/shop/planner/day/${PL.day}/rebuild`, { json: {} });
    dlg.close(); toast("Saved: the day is rebuilt"); renderPlanner();
  };
  dlg.onclose = () => dlg.remove();
  dlg.showModal();
}
function tIn(k, v) { return `<input type="time" data-k="${k}" value="${esc(v)}">`; }
PANES.planner = renderPlanner;
