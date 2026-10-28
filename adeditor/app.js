/* Ad Factory editor: shoots -> script + raw footage -> take stacks -> videos. */
"use strict";
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
const fmt = t => { t = Math.max(0, t); const m = Math.floor(t / 60); return `${m}:${(t % 60).toFixed(1).padStart(4, "0")}`; };
const newId = () => Math.random().toString(16).slice(2, 8);
const W = 1080, H = 1920;

const S = {
  sid: null, shoot: null, sel: null, vid: 1,
  hist: [], fut: [], lastKey: null, lastAt: 0,
  dirty: false, saving: false, job: null,
  presets: {}, fonts: { system: [], custom: [] },
  words: {},          // source key -> words
  scriptChanged: false,
};
const video = $("#video");

async function api(path, opts = {}) {
  if (opts.json !== undefined) {
    opts = { ...opts, method: opts.method || "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(opts.json) };
  }
  const r = await fetch(path, opts);
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch (e) { /* not json */ }
    const err = new Error(msg); err.status = r.status; throw err;
  }
  return r.headers.get("content-type")?.includes("json") ? r.json() : r;
}
let toastT;
function toast(msg, ms = 2600) {
  const t = $("#toast"); t.textContent = msg; t.hidden = false;
  clearTimeout(toastT); toastT = setTimeout(() => (t.hidden = true), ms);
}
const LS = {
  get: (k, d) => { try { return JSON.parse(localStorage.getItem("ad_" + k)) ?? d; } catch (e) { return d; } },
  set: (k, v) => { try { localStorage.setItem("ad_" + k, JSON.stringify(v)); } catch (e) { /* private mode */ } },
};

// ---------- model helpers (mirror adcut/store.py) ----------
const sh = () => S.shoot;
const lines = () => sh().script;
const takeById = id => sh().takes.find(t => t.id === id);
const srcById = id => sh().sources.find(s => s.id === id);
const lineIdx = id => lines().findIndex(l => l.id === id);
const stack = (lineId, usable = true) => sh().takes.filter(t => t.line === lineId && t.usable === usable)
  .sort((a, b) => a.order - b.order || a.in - b.in);
// saved (and posted) videos are frozen: their takes are locked (TikTok flags reused footage)
function postedVideos() {
  const out = {};
  for (const [k, m] of Object.entries(sh()?.saved || {})) {
    if (m.takes?.length) out[+k] = m.takes.map(takeById).filter(Boolean);
  }
  return out;
}
function lockedMap() { const m = {}; for (const [n, ts] of Object.entries(postedVideos())) ts.forEach(t => (m[t.id] = +n)); return m; }
const lockedIn = t => t && lockedMap()[t.id];
const freeStack = lineId => { const lk = lockedMap(); return stack(lineId).filter(t => !lk[t.id]); };
// footage added later is a new batch: unless the shoot mixes them, each batch makes its
// own videos (after the earlier ones). Mirrors store._recipes / store.videos.
const mixing = () => sh().mix ?? sh().mix_auto ?? true;
function batchOf() {
  const b = Object.fromEntries(sh().sources.map(x => [x.id, +x.batch || 1]));
  return t => b[t.src] || 1;
}
function videos() {
  const frozen = postedVideos(), bo = batchOf();
  const rows = lines().map(l => [l, freeStack(l.id)]);
  const batches = [...new Set(rows.flatMap(([, st]) => st.map(bo)))].sort((a, b) => a - b);
  const groups = mixing() || batches.length < 2 ? [null] : batches;
  const recipes = []; let limit = null;
  for (const b of groups) {
    const rb = rows.map(([l, st]) => [l, b == null ? st : st.filter(t => bo(t) === b)]);
    const req = rb.filter(([l]) => !l.optional).map(([, st]) => st.length);
    const count = req.length ? Math.min(...req) : Math.max(0, ...rb.map(([, st]) => st.length));
    if (req.length && b === groups[groups.length - 1]) limit = rb.find(([l, st]) => !l.optional && st.length === count)?.[0] || null;
    for (let di = 0; di < count; di++) recipes.push({ takes: rb.filter(([, st]) => di < st.length).map(([, st]) => st[di]), batch: b });
  }
  const free = recipes.length;
  const vids = [], maxF = Math.max(0, ...Object.keys(frozen).map(Number));
  for (let n = 1, di = 0; di < free || n <= maxF; n++) {
    if (frozen[n]) vids.push({ n, takes: frozen[n], skip: sh().skip.includes(n), posted: true });
    else if (di < free) { vids.push({ n, takes: recipes[di].takes, skip: sh().skip.includes(n), di, batch: recipes[di].batch }); di++; }
    else vids.push({ n, takes: [], skip: true, empty: true });
  }
  return { count: vids.length, free, limit, vids };
}
const takeInVideo = (lineId, n = S.vid) => videos().vids[n - 1]?.takes.find(t => t.line === lineId) || stack(lineId)[0];
function locked(t, what = "change") {
  const n = lockedIn(t);
  if (n) toast(`🔒 Locked: this take is in ${savedOf(n)?.posted ? "posted" : "saved"} video ${n}. TikTok flags reused footage, so it can't ${what}. (Unsave the video to unlock it.)`, 4500);
  return !!n;
}
const sel = () => (sh() ? takeById(S.sel) : null);
// cut-outs inside a take (pauses he trimmed away): [[a, b]] source seconds
function cutsOf(t) {
  const out = [];
  for (const [a0, b0] of [...(t.cuts || [])].sort((x, y) => x[0] - y[0])) {
    const a = Math.max(a0, t.in), b = Math.min(b0, t.out);
    if (b - a < 0.02) continue;
    if (out.length && a <= out[out.length - 1][1]) out[out.length - 1][1] = Math.max(out[out.length - 1][1], b);
    else out.push([a, b]);
  }
  return out;
}
const dur = t => (t.out - t.in - cutsOf(t).reduce((a, [x, y]) => a + y - x, 0)) / spd(t) + (+t.freeze || 0);
const takeRel = (t, x) => cutsOf(t).reduce((r, [a, b]) => r - (x >= b ? b - a : x > a ? x - a : 0), x - t.in) / spd(t);
const inCut = (t, x) => cutsOf(t).find(([a, b]) => x >= a && x < b);
function srcAt(t, rel) {  // seconds into the cut take -> source time
  let x = t.in + rel * spd(t);
  for (const [a, b] of cutsOf(t)) if (x >= a) x += b - a; else break;
  return Math.min(x, t.out);
}
function posOf(t) { // where a take is: {n: its video, good, spare, posted, k}
  const v = videos().vids.find(x => x.takes.includes(t));
  if (v) return { k: v.n - 1, n: v.n, good: true, posted: !!v.posted };
  const i = freeStack(t.line).indexOf(t);
  if (i >= 0) return { k: i, n: null, good: true, spare: true };
  return { k: stack(t.line, false).indexOf(t), n: null, good: false };
}

// ---------- undo / save ----------
const snapshot = () => JSON.stringify(strip(sh()));
const strip = s => Object.fromEntries(Object.entries(s).filter(([k]) => !k.startsWith("_")));
function commit(fn, { key = null, board = true, left = false } = {}) {
  const now = Date.now();
  if (!(key && key === S.lastKey && now - S.lastAt < 1500)) { S.hist.push(snapshot()); S.fut = []; if (S.hist.length > 200) S.hist.shift(); }
  S.lastKey = key; S.lastAt = now;
  fn(sh());
  S.dirty = true; scheduleSave();
  if (board) renderBoard();
  if (left) renderLeft();
  renderInspector(); renderTransport(); showIdle();
}
function restore(json) { const rev = sh().rev; S.shoot = { ...JSON.parse(json), rev }; S.dirty = true; scheduleSave(); renderAllWork(); }
function undo() { if (!S.hist.length) return; S.fut.push(snapshot()); restore(S.hist.pop()); }
function redo() { if (!S.fut.length) return; S.hist.push(snapshot()); restore(S.fut.pop()); }
let saveT;
function scheduleSave() { $("#saveState").textContent = "…"; clearTimeout(saveT); saveT = setTimeout(save, 600); }
async function save() {
  if (S.saving) { scheduleSave(); return; }
  S.saving = true;
  try {
    const r = await api(`/api/shoots/${S.sid}`, { method: "PUT", json: strip(sh()) });
    sh().rev = r.rev; S.dirty = false; S.sigs = r._sigs || S.sigs; renderPicks(); refreshPreviews();
    $("#saveState").textContent = "Saved";
  } catch (e) {
    if (e.status === 409) { toast("This shoot was updated in the background; reloaded."); await reload(); }
    else { $("#saveState").textContent = "Save failed"; toast("Save failed: " + e.message); }
  } finally { S.saving = false; }
}
async function flushSave() { clearTimeout(saveT); if (S.dirty) await save(); }

// ---------- home ----------
async function showHome() {
  showHomeTab(LS.get("homeTab", "today"));
  renderInbox();
  S.sid = null; S.shoot = null; pause();
  history.replaceState(null, "", "#");
  $("#home").hidden = false; $("#work").hidden = true; $("#bottom").hidden = true; $("#review").hidden = true; RV.sid = null;
  for (const id of ["backBtn", "crumbs", "histBtns", "folderBtn", "modeSeg"]) $("#" + id).hidden = true;
  $("#jobBox").hidden = true; $("#saveState").textContent = "";
  const list = await api("/api/shoots");
  $("#shootGrid").innerHTML = list.length ? list.map(r => `
    <div class="shoot" data-id="${r.id}">
      <h3 translate="no">${esc(r.title)}</h3>
      <div><span class="big">${r.videos}</span> videos</div>
      <div class="meta">${r.lines} script lines · ${r.sources} raw file${r.sources === 1 ? "" : "s"} · ${r.rendered} rendered</div>
      ${r.product ? `<div class="meta">🛒 ${esc(r.product)}</div>` : ""}
      ${r.shop && typeof accChip === "function" && (r.shop.account || r.shop.creator) ? `<div class="meta">${accChip(r.shop.account)} ${who(r.shop.creator)}</div>` : ""}
      ${!r.ready && r.sources ? '<div class="meta pending">⏳ pre-cutting…</div>' : r.inbox && !seenShoots().includes(r.id) ? '<div class="meta newb">📥 NEW from the inbox</div>' : ""}
      <div class="meta">${new Date(r.created * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric" })}</div>
      <div class="cardModes"><button data-open="review">👁 Review</button><button data-open="edit">✏️ Edit</button></div>
      <div class="cardModes">
        <button data-script="${r.id}" class="${r.lines ? "" : "warnbtn"}" title="${r.lines ? (r.script_guessed ? "Script figured out from the footage: check or replace it" : "The script") : "Add the script"}">${r.lines ? `📝 Script · ${r.lines} line${r.lines === 1 ? "" : "s"}${r.script_guessed ? " (auto)" : ""}` : "📝 Add script"}</button>
        <button data-addvid="${r.id}" title="Add raw videos to this shoot (they go into its OneDrive inbox folder)">⬆ Add videos</button></div>
      ${r.batches > 1 ? `<div class="meta">📹 ${r.batches} batches of footage</div>` : ""}
      <button class="del" data-del="${r.id}" title="Move this shoot to ads/_trash (raw files and videos are kept)">Delete</button>
    </div>`).join("") : `<div class="empty">No shoots yet. Name one above and hit <b>＋ New shoot</b>.</div>`;
}
$("#shootGrid").addEventListener("click", async e => {
  const del = e.target.closest("[data-del]");
  if (del) {
    e.stopPropagation();
    if (confirm("Delete this shoot? (Raw files and rendered videos are kept.)")) { await api(`/api/shoots/${del.dataset.del}/trash`, { json: {} }); showHome(); }
    return;
  }
  const sc = e.target.closest("[data-script]");
  if (sc) { e.stopPropagation(); openScriptBox(sc.dataset.script); return; }
  const av = e.target.closest("[data-addvid]");
  if (av) { e.stopPropagation(); HD.shoot = av.dataset.addvid; $("#hdFiles").click(); return; }
  const card = e.target.closest(".shoot");
  if (!card) return;
  const how = e.target.closest("[data-open]")?.dataset.open || (touchy() ? "review" : defaultMode());
  if (how === "review") openReview(card.dataset.id); else openShoot(card.dataset.id);
});
async function newShoot() {
  const r = await api("/api/shoots", { json: { title: $("#newTitle").value.trim() } });
  $("#newTitle").value = "";
  openShoot(r.id);
}
$("#newShoot").onclick = newShoot;
$("#newTitle").addEventListener("keydown", e => { if (e.key === "Enter") newShoot(); });
$("#backBtn").onclick = async () => { if (S.sid) await flushSave(); showHome(); };

// ---------- open a shoot ----------
async function openShoot(sid) {
  markSeen(sid);
  S.sid = sid; S.hist = []; S.fut = []; S.sel = null; S.vid = 1;
  history.replaceState(null, "", "#" + sid);
  await reload();
  $("#home").hidden = true; $("#work").hidden = false; $("#bottom").hidden = false; $("#review").hidden = true; RV.sid = null;
  for (const id of ["backBtn", "crumbs", "histBtns", "folderBtn"]) $("#" + id).hidden = false;
  setMode("edit");
  // first visit: open the step that needs doing
  if (!sh().sources.length) { $("#secRaw").open = true; }
  applyPanes();
}
async function reload() {
  const s = await api(`/api/shoots/${S.sid}`);
  S.job = s._job; S.sigs = s._sigs || {}; S.shoot = strip(s); S.dirty = false;
  if (S.sel && !sel()) S.sel = null;
  await Promise.all(sh().sources.filter(x => x.key && !S.words[x.key]).map(async x => { S.words[x.key] = await api(`/api/words/${x.key}`); }));
  renderAllWork(); renderJob(); refreshPreviews();
}
function renderAllWork() {
  $("#titleIn").value = sh().title;
  renderLeft(); renderBoard(); renderInspector(); renderTransport(); renderTrim(); renderGuides(); showIdle();
}
$("#titleIn").addEventListener("input", e => commit(s => (s.title = e.target.value), { key: "title", board: false }));

// poll: background job progress + edits made elsewhere (another tab, Claude)
setInterval(async () => {
  if (!S.sid || S.saving) return;
  try {
    const r = await api(`/api/shoots/${S.sid}/rev`);
    const hadJob = S.job;
    S.job = r.job; renderJob();
    if ((hadJob && !r.job) || (r.rev !== sh().rev && !S.dirty)) {
      if (hadJob && !r.job) {
        const j = await api(`/api/jobs/${hadJob.id}`).catch(() => null);
        if (j?.state === "error") toast("⚠ " + j.error, 8000);
        else if (j?.kind === "download") downloadedToast(j);
        else if (j) toast("✓ Takes found", 4000);
        if (j?.kind === "process") S.scriptChanged = false;
      }
      await reload();
    }
  } catch (e) { /* server restarting */ }
}, 1500);
function renderJob() {
  const j = S.job;
  $("#jobBox").hidden = !j;
  if (j) {
    $("#jobBox .bar i").style.width = `${Math.round(100 * (j.done + 0.3) / Math.max(1, j.total))}%`;
    $("#jobMsg").textContent = j.msg;
  }
  $("#process").disabled = $("#rematch").disabled = !!j;
  renderPicks();
}

// ---------- left: reference ----------
function renderLeft() { renderRef(); renderAssets(); renderScript(); renderSources(); renderPost(); renderTextPanel(); }
function renderRef() {
  const r = sh().reference;
  if (document.activeElement !== $("#refUrl")) $("#refUrl").value = r.url;
  if (document.activeElement !== $("#refNotes")) $("#refNotes").value = r.notes;
  const v = $("#refVideo"), want = r.file ? `/api/shoots/${S.sid}/reference?f=${encodeURIComponent(r.file)}` : "";
  v.hidden = !r.file;
  if (r.file && v.dataset.src !== want) { v.dataset.src = want; v.src = want; }
  $("#refDropMsg").textContent = r.file ? `✓ ${r.file.split(/[\\/]/).pop()} · drop another to replace` : "Drop the reference video here";
  $("#refSum").textContent = r.url || r.file ? "✓ added" : "";
}
$("#refUrl").addEventListener("input", e => commit(s => (s.reference.url = e.target.value.trim()), { key: "refurl", board: false }));
$("#refUrl").addEventListener("change", renderRef);
$("#refNotes").addEventListener("input", e => commit(s => (s.reference.notes = e.target.value), { key: "refnotes", board: false }));
$("#refOpen").onclick = () => { const u = sh().reference.url; if (u) window.open(u, "_blank", "noopener"); else toast("Paste a link first"); };
$("#refPathBtn").onclick = async () => {
  const p = prompt("Path to the reference video file:");
  if (!p) return;
  await flushSave();
  try { await api(`/api/shoots/${S.sid}/reference-path`, { json: { path: p } }); await reload(); } catch (e) { toast(e.message); }
};

// ---------- left: script ----------
function renderScript() {
  const ls = lines();
  $("#scriptSum").textContent = ls.length ? `${ls.length} line${ls.length === 1 ? "" : "s"}${sh().script_guessed ? " · guessed" : ""}` : "";
  const ol = $("#scriptList");
  if (ol.contains(document.activeElement) && ol.children.length === ls.length) return; // typing: keep focus
  const looks = allLooks();
  ol.innerHTML = ls.map((l, i) => `<li data-id="${l.id}" class="${l.optional ? "opt" : ""}">
      <textarea rows="1" placeholder="What he says in this line">${esc(l.text)}</textarea>
      <span class="lacts"><button data-act="opt" class="${l.optional ? "on" : ""}" title="Optional line: videos still get made when this line runs out of takes (it's left out of those)">opt</button>
      <button data-act="del" title="Remove this line">✕</button></span>
      ${(l.alts || []).map((a, j) => `<div class="altrow"><span class="muted">or</span>
        <textarea rows="1" data-alt="${j}" placeholder="another way he says it">${esc(a)}</textarea>
        <button data-act="altdel" data-j="${j}" title="Remove this wording">✕</button></div>`).join("")}
      <div class="lopts">
        <button data-act="alt" title="He says this line more than one way? Add the other wording: takes of either count, and the videos get a mix">＋ alt wording</button>
        ${looks.length ? `<select data-act="look" title="Only use takes filmed in this outfit">
          <option value="">any outfit</option>${looks.map(k => `<option ${k === l.look ? "selected" : ""}>${esc(k)}</option>`).join("")}</select>` : ""}
        <select data-act="lead" title="Start this line earlier, to show what he does before he speaks (opening, sniffing, a reveal)">
          ${[[null, "⏪ start on the words"], [0.5, "⏪ 0.5s before"], [1, "⏪ 1s before"], [1.5, "⏪ 1.5s before"], [2, "⏪ 2s before"], [3, "⏪ 3s before"]].map(([v, txt]) => `<option value="${v ?? ""}" ${String(l.lead_in ?? "") === String(v ?? "") ? "selected" : ""}>${txt}</option>`).join("")}</select>
        <button data-act="wait" class="${l.wait_for ? "on" : ""}" title="The payoff is something you see after the words (blowing the candle out): hold the take until the light goes out, and reject takes where it stays lit">💡 wait for it to go out</button>
        ${l.wait_for ? `<select data-act="hold" title="How long to keep rolling after it goes out">
          ${[[null, "then 0.7s"], [0.3, "then 0.3s"], [0.5, "then 0.5s"], [1, "then 1s"], [1.5, "then 1.5s"], [2, "then 2s"]].map(([v, txt]) => `<option value="${v ?? ""}" ${String(l.hold_after ?? "") === String(v ?? "") ? "selected" : ""}>${txt}</option>`).join("")}</select>` : ""}
        ${i < ls.length - 1 ? `<button data-act="cut" class="${l.cut_next ? "on" : ""}" title="Transition: cut on the motion (a pull, spin, cover…) straight into the next line. Both sides are lined up on the next line's first word.">✂ cut into next</button>` : ""}
      </div>
      ${l.cut_next ? `<div class="lopts cutrow"><span class="muted">cut lands</span>
        <input type="range" data-act="cutoff" min="0" max="0.8" step="0.05" value="${cutOff(l)}">
        <span class="val">${cutOff(l).toFixed(2)}s</span>
        <span class="muted" title="seconds into the next line's first word">${l.cut_offset == null ? "(auto: biggest motion)" : `<button data-act="cutauto" class="linkish">auto</button>`}</span></div>` : ""}
      </li>`).join("")
    || `<li class="muted" style="display:block">No script yet. Paste it, add lines, or hit <b>Find takes</b> and the lines he repeated become the script.</li>`;
  $$("textarea", ol).forEach(autoGrow);
  $("#rematch").classList.toggle("primary", S.scriptChanged);
}
function autoGrow(ta) { ta.style.height = "auto"; ta.style.height = ta.scrollHeight + 2 + "px"; }
// script edits re-match on their own a moment after you stop typing, so reworded
// lines pick up their words again (no need to hit ↻ Re-match)
let rematchT = null;
function markScriptChanged() {
  S.scriptChanged = true; $("#rematch").classList.add("primary");
  if (!sh()?.sources.some(x => x.status === "ready")) return;
  clearTimeout(rematchT);
  rematchT = setTimeout(async () => {
    if ($("#scriptList").contains(document.activeElement) && Date.now() - S.lastAt < 1400) { markScriptChanged(); return; }
    if (S.job) { markScriptChanged(); return; }
    $("#saveState").textContent = "Re-matching takes…";
    await runProcess();
  }, 1500);
}
const allLooks = () => [...new Set(sh().sources.flatMap(x => (x.looks || []).map(m => m.name)).filter(Boolean))];
const cutOff = l => +(l.cut_offset ?? l.cut_offset_auto ?? 0.3);
$("#scriptList").addEventListener("change", e => {
  const li = e.target.closest("li[data-id]"); if (!li) return;
  if (e.target.dataset.act === "lead") {
    commit(s => { s.script.find(l => l.id === li.dataset.id).lead_in = e.target.value === "" ? null : +e.target.value; }, { left: true });
    markScriptChanged(); return;
  }
  if (e.target.dataset.act === "hold") {
    commit(s => { s.script.find(l => l.id === li.dataset.id).hold_after = e.target.value === "" ? null : +e.target.value; }, { left: true });
    markScriptChanged(); return;
  }
  if (e.target.dataset.act !== "look") return;
  commit(s => { s.script.find(l => l.id === li.dataset.id).look = e.target.value || null; }, { left: true });
  markScriptChanged();
});
$("#scriptList").addEventListener("input", e => {
  const li = e.target.closest("li[data-id]"); if (!li) return;
  if (e.target.dataset.act === "cutoff") {
    const v = +e.target.value; e.target.nextElementSibling.textContent = v.toFixed(2) + "s";
    commit(s => { s.script.find(l => l.id === li.dataset.id).cut_offset = v; }, { key: "cutoff" + li.dataset.id, board: false });
    markScriptChanged(); return;
  }
  if (e.target.tagName !== "TEXTAREA") return;
  if (e.target.dataset.alt !== undefined) {
    autoGrow(e.target); markScriptChanged();
    const j = +e.target.dataset.alt;
    commit(s => { s.script.find(l => l.id === li.dataset.id).alts[j] = e.target.value; }, { key: `alt${li.dataset.id}${j}` });
    return;
  }
  autoGrow(e.target);
  commit(s => { s.script.find(l => l.id === li.dataset.id).text = e.target.value; s.script_guessed = false; }, { key: "line" + li.dataset.id });
  markScriptChanged();
});
$("#scriptList").addEventListener("click", e => {
  const b = e.target.closest("button[data-act]"); if (!b) return;
  const id = b.closest("li").dataset.id;
  if (b.dataset.act === "opt") { commit(s => { const l = s.script.find(l => l.id === id); l.optional = !l.optional; }, { left: true }); }
  if (b.dataset.act === "wait") { commit(s => { const l = s.script.find(l => l.id === id); l.wait_for = l.wait_for ? null : "light_off"; }, { left: true }); markScriptChanged(); }
  if (b.dataset.act === "alt") { commit(s => { const l = s.script.find(l => l.id === id); (l.alts = l.alts || []).push(""); }, { left: true }); $(`#scriptList li[data-id="${id}"] textarea[data-alt]:last-of-type`)?.focus(); }
  if (b.dataset.act === "altdel") { commit(s => { s.script.find(l => l.id === id).alts.splice(+b.dataset.j, 1); }, { left: true }); markScriptChanged(); }
  if (b.dataset.act === "cut") { commit(s => { const l = s.script.find(l => l.id === id); l.cut_next = !l.cut_next; }, { left: true }); markScriptChanged(); }
  if (b.dataset.act === "cutauto") { commit(s => { s.script.find(l => l.id === id).cut_offset = null; }, { left: true }); markScriptChanged(); }
  if (b.dataset.act === "del") removeLine(id);
});
$("#addLine").onclick = () => {
  commit(s => s.script.push({ id: newId(), text: "", optional: false }), { left: true });
  const tas = $$("#scriptList textarea"); tas[tas.length - 1]?.focus();
};
$("#pasteScript").onclick = () => { $("#pasteBox").hidden = false; $("#pasteText").value = lines().map(l => l.text).join("\n"); $("#pasteText").focus(); };
$("#pasteCancel").onclick = () => ($("#pasteBox").hidden = true);
$("#pasteOk").onclick = () => {
  let rows = $("#pasteText").value.split(/\n+/).map(x => x.trim()).filter(Boolean);
  if ($("#pasteSentences").checked) rows = rows.flatMap(r => r.length > 90 ? r.split(/(?<=[.!?])\s+(?=[A-Z0-9"“])/) : [r]).map(x => x.trim()).filter(Boolean);
  rows = rows.map(r => r.replace(/^(\d+[.)]|[-*•])\s*/, "")); // strip "1." / bullets
  commit(s => {
    const old = s.script;
    s.script = rows.map((text, i) => ({ id: old[i]?.id || newId(), text, optional: old[i]?.optional || false }));
    const ids = new Set(s.script.map(l => l.id));
    s.takes.forEach(t => { if (t.line && !ids.has(t.line)) { t.line = null; t.usable = false; t.status = "unmatched"; } });
    s.script_guessed = false;
  }, { left: true });
  $("#pasteBox").hidden = true;
  S.scriptChanged = true; renderScript();
  if (sh().sources.some(x => x.status === "ready")) toast("Script set. Hit ↻ Re-match takes to sort the takes by it.");
};
$("#rematch").onclick = () => runProcess();

// ---------- left: raw footage ----------
function renderSources() {
  const ss = sh().sources;
  $("#rawSum").textContent = ss.length ? `${ss.length} file${ss.length === 1 ? "" : "s"}` : "";
  $("#srcList").innerHTML = ss.map(x => {
    const st = x.status === "ready" ? `<span class="st ready">✓ ${fmt(x.duration)} · ${x.width}×${x.height}</span>`
      : x.status === "error" ? `<span class="st err" title="${esc(x.error)}">⚠ ${esc((x.error || "").slice(0, 80))}</span>`
      : `<span class="st">${S.job ? "working…" : "new: hit Find takes"}</span>`;
    const looks = (x.looks || []).map((m, i) => ({ ...m, i })).sort((a, b) => a.t - b.t);
    const lk = x.status !== "ready" ? "" : `<div class="looks" data-src="${x.id}">
      <span class="muted" title="If he changes outfits during the shoot, mark when. Script lines can then ask for one outfit.">👕 Outfits:</span>
      ${looks.map(m => `<span class="look" data-i="${m.i}"><input class="lkname" value="${esc(m.name)}" placeholder="name"> from
        <input class="lktime mono" value="${fmt(m.t)}" title="m:ss"><button data-lkdel title="Remove">✕</button></span>`).join("")}
      <button data-lkadd title="Add an outfit change at the frame showing in the preview">＋ change here</button></div>`;
    return `<li><span class="nm" title="${esc(x.file)}">${esc(x.name)}</span>${st}<button data-rm="${x.id}" title="Remove from this shoot (the file itself is kept)">✕</button>${lk}</li>`;
  }).join("");
  const fresh = ss.some(x => x.status !== "ready");
  $("#process").textContent = fresh ? "Find takes" : "↻ Find takes again";
  $("#process").classList.toggle("primary", fresh || !sh().takes.length);
}
const parseTime = v => { const p = String(v).trim().split(":").map(Number); return p.length > 1 ? p[0] * 60 + p[1] : p[0]; };
function editLooks(srcId, fn) {
  commit(s => { const x = s.sources.find(x => x.id === srcId); x.looks = x.looks || []; fn(x.looks, x); }, { board: false });
  markScriptChanged(); renderSources(); renderScript();
}
$("#srcList").addEventListener("click", e => {
  const box = e.target.closest(".looks"); if (!box) return;
  const id = box.dataset.src;
  if (e.target.closest("[data-lkadd]")) {
    const src = srcById(id);
    const here = video.dataset.src === `/proxy/${src.key}.mp4` ? video.currentTime : 0;
    editLooks(id, L => L.push({ t: Math.round(here * 10) / 10, name: `outfit ${L.length + 1}` }));
  }
  if (e.target.closest("[data-lkdel]")) editLooks(id, L => L.splice(+e.target.closest(".look").dataset.i, 1));
});
$("#srcList").addEventListener("change", e => {
  const box = e.target.closest(".looks"); if (!box) return;
  const i = +e.target.closest(".look").dataset.i;
  if (e.target.classList.contains("lkname")) editLooks(box.dataset.src, L => (L[i].name = e.target.value.trim()));
  if (e.target.classList.contains("lktime")) editLooks(box.dataset.src, L => (L[i].t = Math.max(0, parseTime(e.target.value) || 0)));
});
$("#srcList").addEventListener("click", async e => {
  const b = e.target.closest("[data-rm]"); if (!b) return;
  if (!confirm("Remove this file and its takes from the shoot? (The file itself is kept.)")) return;
  await flushSave(); await api(`/api/shoots/${S.sid}/sources/${b.dataset.rm}`, { method: "DELETE" }); await reload();
});
$("#rawPathBtn").onclick = async () => {
  const p = prompt("Path to a raw video file, or a folder of them:\n(tip: Shift+right-click the file in Explorer → Copy as path)");
  if (!p) return;
  await flushSave();
  try { const r = await api(`/api/shoots/${S.sid}/sources`, { json: { paths: [p] } }); toast(`Added ${r.added} file(s)`); await reload(); } catch (e) { toast(e.message, 5000); }
};
$("#process").onclick = () => runProcess();
async function runProcess() {
  await flushSave();
  if (!sh().sources.length) { toast("Add the raw footage first"); return; }
  try { S.job = await api(`/api/shoots/${S.sid}/process`, { json: {} }); renderJob(); } catch (e) { toast(e.message); }
}
function dropZone(el, kind) {
  el.addEventListener("dragover", e => { if (e.dataTransfer.types.includes("Files")) { e.preventDefault(); el.classList.add("over"); } });
  el.addEventListener("dragleave", () => el.classList.remove("over"));
  el.addEventListener("drop", async e => {
    e.preventDefault(); el.classList.remove("over");
    const ok = f => /^video\//.test(f.type) || /\.(mov|mp4|m4v|mkv|webm|avi)$/i.test(f.name) || (kind === "asset" && (/^image\//.test(f.type) || /\.(png|jpe?g|webp|gif)$/i.test(f.name)));
    const files = [...e.dataTransfer.files].filter(ok);
    if (!files.length) { toast(kind === "asset" ? "Drop images or video clips" : "Drop video files"); return; }
    await flushSave();
    for (const [i, f] of (kind === "reference" ? files.slice(0, 1) : files).entries()) {
      $("#jobBox").hidden = false; $("#jobMsg").textContent = `copying ${f.name} (${i + 1}/${files.length}, ${(f.size / 1e6).toFixed(0)} MB)…`;
      try { await fetch(`/api/shoots/${S.sid}/upload?kind=${kind}&name=${encodeURIComponent(f.name)}`, { method: "PUT", body: f }); }
      catch (err) { toast("Upload failed: " + err.message); }
    }
    $("#jobBox").hidden = !S.job;
    await reload();
    if (kind === "source") toast("Added. Hit Find takes when everything's in.");
    if (kind === "asset") toast("Added. Hit ＋ Place on a line to show it in the videos.");
  });
}
dropZone($("#rawDrop"), "source");
dropZone($("#refDrop"), "reference");
dropZone($("#assetDrop"), "asset");

// ---------- left: product + text ----------
function renderPost() {
  const p = sh().product;
  for (const [id, k] of [["pName", "name"], ["pLink", "link"], ["pDesc", "description"], ["pTags", "hashtags"]])
    if (document.activeElement !== $("#" + id)) $("#" + id).value = p[k];
  $("#postSum").textContent = p.name || "";
}
for (const [id, k] of [["pName", "name"], ["pLink", "link"], ["pDesc", "description"], ["pTags", "hashtags"]])
  $("#" + id).addEventListener("input", e => commit(s => (s.product[k] = e.target.value), { key: "p" + k, board: false }));
async function copyText(t, what) { try { await navigator.clipboard.writeText(t); toast(`Copied ${what}`); } catch (e) { prompt("Copy:", t); } }
$("#copyPost").onclick = () => { const p = sh().product; copyText(`${p.description} ${p.hashtags}`.trim(), "description"); };
$("#copyLink").onclick = () => copyText(sh().product.link, "link");

const getPath = (o, path) => path.split(".").reduce((a, k) => a?.[k], o);
function setPath(o, path, v) { const ks = path.split("."); const last = ks.pop(); ks.reduce((a, k) => a[k], o)[last] = v; }
function renderTextPanel() {
  if (document.activeElement !== $("#hooks")) $("#hooks").value = sh().hooks.join("\n");
  for (const el of $$("#secText [data-path]")) {
    const v = getPath(sh(), el.dataset.path);
    if (el.type === "checkbox") el.checked = !!v; else if (document.activeElement !== el) el.value = v;
    if (el.type === "range") el.nextElementSibling.textContent = (+v).toFixed(el.step < 1 ? 2 : 0);
  }
}
$("#hooks").addEventListener("input", e => commit(s => (s.hooks = e.target.value.split("\n").map(x => x.trim()).filter(Boolean)), { key: "hooks", board: false }));
$("#secText").addEventListener("input", e => {
  const el = e.target; const path = el.dataset.path; if (!path) return;
  let v = el.type === "checkbox" ? el.checked : el.type === "range" || el.type === "number" ? +el.value : el.value;
  commit(s => {
    if (path.endsWith(".preset")) { // switching preset pulls in its look
      const box = path.split(".").slice(0, -1).join(".");
      const keep = { on: getPath(s, box).on, seconds: getPath(s, box).seconds, y: getPath(s, box).y };
      setPath(s, box, { ...getPath(s, box), ...S.presets[v], ...keep, preset: v });
    } else setPath(s, path, v);
  }, { key: path, board: false });
  if (el.type === "range") el.nextElementSibling.textContent = (+v).toFixed(el.step < 1 ? 2 : 0);
  lastOv = null; showIdle();
});

// ---------- board ----------
let showRejects = LS.get("rejects", true), showOther = LS.get("other", false);
$("#showRejects").checked = showRejects; $("#showOther").checked = showOther;
$("#showRejects").onchange = e => { showRejects = e.target.checked; LS.set("rejects", showRejects); renderBoard(); };
$("#showOther").onchange = e => { showOther = e.target.checked; LS.set("other", showOther); renderBoard(); };

const thumbUrl = t => { const src = srcById(t.src); return src?.key ? `/api/thumb/${src.key}?t=${(Math.round((t.in + t.out) * 5) / 10).toFixed(1)}` : ""; };
const STATUS = { good: "good", close: "reworded", flub: "flub", incomplete: "cut off", paused: "paused", nopayoff: "stayed lit", unmatched: "other" };
function card(t, k, { good, spare }) {
  const lockN = lockedIn(t);
  const cls = ["card", good ? "" : "rej", spare ? "spare" : "", t.id === S.sel ? "sel" : "", lockN ? "locked" : ""].join(" ");
  return `<div class="${cls}" draggable="${lockN ? "false" : "true"}" data-id="${t.id}" title="${esc(t.text)}${t.flags.length ? "\n• " + esc(t.flags.join("\n• ")) : ""}">
    <img loading="lazy" src="${thumbUrl(t)}" alt="">
    <div class="cb"><div class="cbtop"><span class="badge b-${t.status}">${STATUS[t.status] || t.status}</span>
      <span class="du">${t.look ? esc(t.look) + " · " : ""}${dur(t).toFixed(1)}s</span></div>
      <div class="ct">${esc(t.text)}</div></div>
    <button class="pl" data-play="${t.id}" title="Play this take">▶︎</button>
    ${lockN ? `<span class="lockb card" title="In saved video ${lockN}: locked so the footage isn't reused">🔒</span>` : ""}
    ${t.line && !lockN ? (good ? `<button class="rj" data-rej="${t.id}" title="Reject this take (U)">✕ Reject</button>`
                     : `<button class="rj ok" data-rej="${t.id}" title="Put this take back in its line's stack (U)">↩ Use</button>`) : ""}
    ${t.line && !lockN ? swapSelect(t, good, k) : ""}</div>`;
}
function renderBoard() {
  if (!sh()) return;
  const v = videos();
  if (S.vid > v.count) S.vid = Math.max(1, v.count);
  $("#vidCount").textContent = v.count;
  $("#vidWord").textContent = v.count === 1 ? "video" : "videos";
  $("#crumbMeta").textContent = `${v.count} video${v.count === 1 ? "" : "s"} · ${lines().length} line${lines().length === 1 ? "" : "s"} · ${sh().sources.length} raw file${sh().sources.length === 1 ? "" : "s"}`;
  const ls = lines();
  if (v.limit && ls.length > 1) {
    const most = Math.max(...ls.map(l => freeStack(l.id).length));
    $("#limitMsg").textContent = most > v.free ? `Line ${lineIdx(v.limit.id) + 1} only has ${v.free} free good take${v.free === 1 ? "" : "s"}; the other lines have up to ${most}` : "";
  } else $("#limitMsg").textContent = "";
  $("#countBox").title = $("#limitMsg").textContent || "How many finished videos the take stacks make";
  $("#countBox").classList.toggle("limited", !!$("#limitMsg").textContent);
  const grid = $("#grid");
  const ready = sh().sources.some(x => x.status === "ready");
  if (!ready || (!ls.length && !sh().takes.length)) {
    grid.innerHTML = `<div class="empty">${sh().sources.length ? "Hit <b>Find takes</b> (left) to sort the footage into stacks." : "Start on the left: add the <b>script</b> (optional), drop in the <b>raw footage</b>, then hit <b>Find takes</b>."}</div>`;
    return;
  }
  const stacks = ls.map(l => freeStack(l.id));
  const lk = lockedMap();
  const maxFree = Math.max(0, ...stacks.map(st => st.length));
  const cols = `var(--rowh-w) repeat(${ls.length}, var(--colw))`;
  const out = [`<div class="bgrid" style="grid-template-columns:${cols}">`];
  out.push(`<div class="bh corner">Video ↓ · Line →</div>`);
  ls.forEach((l, i) => {
    const lim = v.limit?.id === l.id && ls.length > 1;
    const nLocked = stack(l.id).length - stacks[i].length;
    out.push(`<div class="bh" title="${esc(l.text)}"><button class="icon ldel" data-ldel="${l.id}" title="Remove line ${i + 1} from the script and every video">✕</button><span class="ln">Line ${i + 1}<span class="cnt ${lim ? "lim" : ""}" title="${lim ? "This line limits how many videos you get" : "good takes still free"}">${stacks[i].length} good${nLocked ? ` · ${nLocked}🔒` : ""}</span>
        ${l.look ? `<span class="tagx">👕 ${esc(l.look)}</span>` : ""}${l.cut_next ? '<span class="tagx" title="cuts on the motion into the next line">✂</span>' : ""}${l.optional ? '<span class="tagx warn">opt</span>' : ""}${l.wait_for ? '<span class="tagx" title="held until the light goes out">💡</span>' : ""}${(l.alts || []).filter(Boolean).length ? `<span class="tagx" title="${esc(l.alts.join("\n"))}">+${l.alts.filter(Boolean).length} wording</span>` : ""}</span>
      <span class="lt">${esc(l.text) || '<i class="muted">(empty line)</i>'}</span></div>`);
  });
  const rowHead = vid => {
    const n = vid.n, total = vid.takes.reduce((a2, t) => a2 + dur(t), 0), sv = savedOf(n);
    return `<div class="rh ${n === S.vid ? "cur" : ""} ${vid.skip && !vid.empty ? "skip" : ""} ${vid.posted ? "posted" : ""}" data-vid="${n}" title="${vid.posted ? `${sv?.posted ? "Posted" : "Saved"}: its takes are locked (unsave to free them)` : `Preview video ${n}`}">
      <div class="rhtop"><b>Video ${n}</b>${vid.posted ? ` <span class="lockb" title="${sv?.posted ? "Posted" : "Saved"}: locked">🔒</span>` : ""}</div>
      ${vid.batch > 1 ? `<div class="rhnote game" title="Made from footage added later (kept separate from the earlier videos)">📹 added footage${vid.batch > 2 ? " #" + (vid.batch - 1) : ""}</div>` : ""}
      ${(() => { const g = vid.takes.find(t => t.game)?.game, sp = Math.max(-1, ...vid.takes.map(t => t.spice ?? -1));
        const fl = safetyOf(vid.takes.map(t => capText(t)).join(" "));
        return (g || sp >= 0 ? `<div class="rhnote game">${g ? `🎲 ${esc(g)}` : ""}${sp >= 0 ? ` · ${SPICE[sp] || sp}` : ""}</div>` : "") + (fl.length ? `<div class="rhnote">${safetyChip(fl)}</div>` : ""); })()}
      ${(() => { const odd = vid.takes.filter(t => t.variant); return odd.length ? `<div class="rhnote" title="${esc(odd.map(t => `Line ${lineIdx(t.line) + 1}: ${t.variant} — “${t.text}”`).join("\n"))}">🎭 different read · line ${odd.map(t => lineIdx(t.line) + 1).join(", ")}</div>` : ""; })()}
      <span class="rhbtns"><button class="icon star ${sv ? "on" : ""}" data-vstar="${n}" title="${sv?.posted ? "Posted (untick Posted to unlock)" : sv ? "Saved to your posting queue (click to unsave)" : "Save to your posting queue"}">${sv ? "★" : "☆"}</button><button class="icon" data-vplay="${n}" title="Play video ${n} from where you left it">${P.on && P.mode === "video" && n === S.vid ? "⏸︎" : "▶︎"}</button><button class="icon" data-vrestart="${n}" title="Start video ${n} over and play">⏮︎</button></span>
      <span class="vs">${vid.empty ? "no free takes" : fmt(total)} ${vid.posted ? (sv?.posted ? `posted${sv.posted_at ? " " + fmtDate(sv.posted_at) : ""}` : "saved") : renderMark(n)}</span></div>`;
  };
  for (const vid of v.vids) {
    out.push(rowHead(vid));
    ls.forEach(l => {
      const t = vid.takes.find(x => x.line === l.id);
      const cls = `cells cell ${vid.n === S.vid ? "cur" : ""} ${vid.posted ? "lockedcell" : ""}`;
      out.push(`<div class="${cls}" data-line="${l.id}" data-usable="1" ${vid.posted ? 'data-locked="1"' : ""}>${t ? card(t, vid.n - 1, { good: true, spare: false })
        : `<span class="hole">${vid.posted ? "—" : l.optional ? "— (optional)" : "drop a take"}</span>`}</div>`);
    });
  }
  // spare rows: free takes beyond what makes a full video
  for (let k = v.free; k < Math.max(maxFree, v.vids.length ? 0 : 1); k++) {
    out.push(`<div class="rh spare" title="Spare takes: not enough good takes of every line to make another video"><span class="muted">spare ${k - v.free + 1}</span></div>`);
    ls.forEach((l, i) => {
      const t = stacks[i][k];
      out.push(`<div class="cells cell sparecell" data-line="${l.id}" data-usable="1">${t ? card(t, k, { good: true, spare: !l.optional }) : ""}</div>`);
    });
  }
  if (showRejects) {
    out.push(`<div class="rh rejh"><b>Rejects</b><span class="vs">flubs · cut off · paused</span></div>`);
    ls.forEach(l => out.push(`<div class="cells cell rej" data-line="${l.id}" data-usable="0">${stack(l.id, false).map(t => card(t, 0, { good: false })).join("") || '<span class="hole">none</span>'}</div>`));
  }
  if (showOther) {
    const other = sh().takes.filter(t => !t.line).sort((x, y) => x.src.localeCompare(y.src) || x.in - y.in);
    out.push(`<div class="rh rejh"><b>Other speech</b><span class="vs">${other.length} · drag onto a line</span></div>
      <div class="cells cell rej other" data-line="" data-usable="0" style="grid-column: 2 / span ${ls.length}">${other.map(t => card(t, 0, { good: false })).join("")}</div>`);
  }
  out.push("</div>");
  const sx = grid.scrollLeft, sy = grid.scrollTop;
  grid.innerHTML = out.join("");
  grid.scrollLeft = sx; grid.scrollTop = sy;
}
// live time tracker on the board: a playhead through the cell that's playing
function boardPlayhead(it) {
  const cardEl = it && $(`#grid .card[data-id="${it.t.id}"]`);
  $$("#grid .bph").forEach(x => { if (x.parentElement !== cardEl) x.remove(); });
  if (!cardEl) return;
  let ph = cardEl.querySelector(".bph");
  if (!ph) { ph = document.createElement("i"); ph.className = "bph"; cardEl.appendChild(ph); }
  ph.style.left = `${clamp(takeRel(it.t, srcNow()) / dur(it.t), 0, 1) * 100}%`;
}
// selection follows playback without re-rendering the whole board
function followPlayback(t) {
  if (!t || S.sel === t.id) return;
  S.sel = t.id;
  $$("#grid .card.sel").forEach(x => x.classList.remove("sel"));
  const el = $(`#grid .card[data-id="${t.id}"]`);
  if (el) { el.classList.add("sel"); el.scrollIntoView({ block: "nearest", inline: "nearest" }); }
  renderInspector(); renderTrim();
}
$("#grid").addEventListener("click", e => {
  if (e.target.closest("select")) return;  // the swap dropdown: leave it open
  const ld = e.target.closest("[data-ldel]");
  if (ld) { e.stopPropagation(); removeLine(ld.dataset.ldel); return; }
  const rj = e.target.closest("[data-rej]");
  if (rj) { e.stopPropagation(); toggleUsable(takeById(rj.dataset.rej)); return; }
  const pl = e.target.closest("[data-play]");
  if (pl) { e.stopPropagation(); select(pl.dataset.play, false); play("take"); return; }
  const vs = e.target.closest("[data-vstar]");
  if (vs) { e.stopPropagation(); toggleSaved(+vs.dataset.vstar); return; }
  const vp = e.target.closest("[data-vplay]"), vr = e.target.closest("[data-vrestart]");
  if (vp) { e.stopPropagation(); const n = +vp.dataset.vplay; (P.on && P.mode === "video" && n === S.vid) ? pause() : playVideo(n); return; }
  if (vr) { e.stopPropagation(); playVideo(+vr.dataset.vrestart, 0); return; }
  const vh = e.target.closest(".rh[data-vid]");
  if (vh) { selectVideo(+vh.dataset.vid); return; }
  const c = e.target.closest(".card");
  if (c) select(c.dataset.id);
});
$("#grid").addEventListener("dblclick", e => { const c = e.target.closest(".card"); if (c) { select(c.dataset.id, false); play("take"); } });

// drag & drop between/within stacks
let dragId = null;
$("#grid").addEventListener("dragstart", e => {
  const c = e.target.closest(".card"); if (!c) return;
  if (lockedIn(takeById(c.dataset.id))) { e.preventDefault(); locked(takeById(c.dataset.id), "move"); return; }
  dragId = c.dataset.id; e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", dragId);
});
$("#grid").addEventListener("dragover", e => {
  if (!dragId) return;
  const cells = e.target.closest(".cells"); if (!cells) return;
  e.preventDefault();
  $$(".over, .dragover", $("#grid")).forEach(x => x.classList.remove("over", "dragover"));
  cells.classList.add("over");
  e.target.closest(".card")?.classList.add("dragover");
});
$("#grid").addEventListener("dragend", () => { dragId = null; $$(".over, .dragover").forEach(x => x.classList.remove("over", "dragover")); });
$("#grid").addEventListener("drop", e => {
  const cells = e.target.closest(".cells"); if (!cells || !dragId) return;
  e.preventDefault();
  if (cells.dataset.locked) { toast("🔒 That video is saved: its takes are locked"); dragId = null; return; }
  const before = e.target.closest(".card")?.dataset.id;
  moveTake(dragId, cells.dataset.line || null, cells.dataset.usable === "1", before !== dragId ? before : undefined);
  dragId = null;
});
function moveTake(id, lineId, usable, beforeId) {
  if (locked(takeById(id), "move")) return;
  commit(s => {
    const t = s.takes.find(x => x.id === id);
    const was = [t.line, t.usable];
    if (!lineId) usable = false;
    t.line = lineId; t.usable = usable;
    t.user.line = true; t.user.usable = true;
    if (lineId && t.status === "unmatched") { t.status = "close"; t.flags = ["moved here by hand"]; }
    if (!lineId) t.status = "unmatched";
    const group = s.takes.filter(x => x.line === lineId && x.usable === usable && x !== t).sort((a, b) => a.order - b.order || a.in - b.in);
    const at = beforeId ? group.findIndex(x => x.id === beforeId) : -1;
    group.splice(at < 0 ? group.length : at, 0, t);
    group.forEach((x, i) => { x.order = i; x.user.order = true; });
    const old = s.takes.filter(x => x.line === was[0] && x.usable === was[1]).sort((a, b) => a.order - b.order);
    old.forEach((x, i) => (x.order = i));
  });
}
function toggleUsable(t = sel()) {
  if (locked(t, "be rejected")) return;
  if (!t || !t.line) return;
  const usable = !t.usable;
  moveTake(t.id, t.line, usable, undefined);
  toast(usable ? "✓ Back in the stack" : "✗ Moved to rejects");
}

// ---------- selection ----------
function select(id, cue = true) {
  S.sel = id;
  S.playScope = "take";  // working on a take: Space plays just it
  const t = sel();
  if (t?.line) { const p = posOf(t); if (p.n) S.vid = p.n; }
  pause();
  renderBoard(); renderInspector(); renderTransport(); renderTrim();
  if (cue) showIdle();
  $(`.card[data-id="${id}"]`)?.scrollIntoView({ block: "nearest", inline: "nearest" });
}
function selectVideo(n) {
  const v = videos(); if (!v.count) return;
  S.playScope = "video";
  S.vid = clamp(n, 1, v.count);
  const t = sel();
  // keep the selection on the same line, now in this video
  if (t?.line) { const x = v.vids[S.vid - 1]?.takes.find(k => k.line === t.line); if (x) S.sel = x.id; }
  else S.sel = v.vids[S.vid - 1].takes[0]?.id ?? null;
  pause(); renderBoard(); renderInspector(); renderTransport(); renderTrim(); showIdle();
}
function moveSel(dx, dy) {
  const t = sel();
  if (!t) { const first = videos().vids[0]?.takes[0]; if (first) select(first.id); return; }
  if (dx) {
    const row = t.line ? [...stack(t.line), ...(showRejects ? stack(t.line, false) : [])] : sh().takes.filter(x => !x.line);
    const i = row.indexOf(t), nx = row[clamp(i + dx, 0, row.length - 1)];
    if (nx) select(nx.id);
  }
  if (dy && t.line) {
    const li = clamp(lineIdx(t.line) + dy, 0, lines().length - 1), p = posOf(t);
    const lid2 = lines()[li].id, st = stack(lid2);
    const nx = (p.n && videos().vids[p.n - 1]?.takes.find(k => k.line === lid2)) || st[Math.min(p.k, st.length - 1)];
    if (nx) select(nx.id);
  }
}

// ---------- inspector ----------
function saidHtml(t) {
  const extra = new Set(t.extra || []);
  const norm = w => w.toLowerCase().replace(/[^a-z0-9']/g, "");
  return t.text.split(/\s+/).map(w => extra.has(norm(w)) ? `<span class="x" title="not in the script">${esc(w)}</span>` : esc(w)).join(" ");
}
function renderInspector() {
  const el = $("#inspector");
  const t = sel();
  const typing = document.activeElement && ["capEdit", "lineEdit", "titleEdit"].includes(document.activeElement.id) && el.contains(document.activeElement);
  if (typing && el.dataset.tid === (t?.id || "")) return;  // don't wipe what you're typing
  el.dataset.tid = t?.id || "";
  if (!t) {
    el.innerHTML = `<h3>Tips</h3><p class="hint">Click a take to check it; double-click to play it. <b>U</b> moves it in or out of the stack.<br><br>
      The first good take of every line makes <b>video 1</b>, the second makes <b>video 2</b>… Drag takes to choose which ones pair up.<br><br>
      Hooks (⑤ on the left) rotate across the videos, so they don't all open the same way.</p>`;
    return;
  }
  const line = lines().find(l => l.id === t.line);
  const p = t.line ? posOf(t) : null;
  const where = !t.line ? "Other speech" : p.good ? `Line ${lineIdx(t.line) + 1}${p.n ? ` → video ${p.n}${p.posted ? " 🔒 posted" : ""}` : " (spare)"}` : `Line ${lineIdx(t.line) + 1} · rejected`;
  const src = srcById(t.src);
  el.innerHTML = `
    <h3>${esc(where)} <span class="badge b-${t.status}">${STATUS[t.status] || t.status}</span></h3>
    ${t.line ? `<div class="big2"><button class="yes ${t.usable ? "on" : ""}" data-act="use">✓ Usable</button><button class="no ${!t.usable ? "on" : ""}" data-act="rej">✗ Reject</button></div>` : ""}
    ${t.quality != null ? `<div class="qline" title="How the take ranks for video 1: clean read, no ums or rewording, looking into the lens">Quality <b>${Math.round(t.quality * 100)}</b>${t.eye != null ? ` · eye contact <b>${Math.round(t.eye * 100)}%</b>` : ""}${t.variant ? ` · 🎭 ${esc(t.variant)}` : ""}</div>` : ""}
    <div class="qline">${safetyChip(safetyOf(capText(t)), true)}</div>
    <h3>Captions <span class="muted" style="font-weight:400">(what shows on screen · fix words here)</span></h3>
    <textarea id="capEdit" rows="3" placeholder="No captions on this take">${esc(capText(t))}</textarea>
    ${t.user?.words ? `<div class="hint">Edited by hand · <button class="linkish" data-act="capReset">back to the transcript</button></div>` : ""}
    ${t.flags.length ? `<ul class="flags">${t.flags.map(f => `<li>${esc(f)}</li>`).join("")}</ul>` : ""}
    ${line ? `<h3>Script line ${lineIdx(line.id) + 1}</h3><textarea id="lineEdit" rows="2" title="Edits the script line for every take (takes re-match a moment after you stop typing)">${esc(line.text)}</textarea>${t.missing?.length ? `<div class="hint">Skipped: ${esc(t.missing.join(" "))}</div>` : ""}` : ""}
    ${t.line ? `<div class="row" style="margin-top:10px"><label class="lbl">Use in</label>${swapSelect(t, posOf(t).good, posOf(t).k, true)}</div>` : ""}
    <div class="row" style="margin-top:10px"><label class="lbl">Line</label><select data-act="line">
      ${lines().map((l, i) => `<option value="${l.id}" ${l.id === t.line ? "selected" : ""}>${i + 1}. ${esc(l.text.slice(0, 40))}</option>`).join("")}
      <option value="" ${!t.line ? "selected" : ""}>Other speech (not used)</option></select></div>
    <h3>Trim</h3>
    <div class="row nudge"><label class="lbl">Start ${t.in.toFixed(2)}</label><button data-n="in:-0.05">−</button><button data-n="in:0.05">＋</button>
      <label class="lbl" style="margin-left:8px">End ${t.out.toFixed(2)}</label><button data-n="out:-0.05">−</button><button data-n="out:0.05">＋</button></div>
    <h3>Speed</h3>
    <div class="row"><label class="lbl">This clip</label><select data-act="speed" title="Speed this clip up (pitch stays natural)">
      <option value="" ${!+t.speed ? "selected" : ""}>auto · ${autoSpd(t).toFixed(2)}×</option>
      ${[1, 1.05, 1.1, 1.15, 1.2, 1.25, 1.3, 1.4, 1.5].map(v => `<option value="${v}" ${+t.speed === v ? "selected" : ""}>${v.toFixed(2)}×</option>`).join("")}</select></div>
    <div class="row"><label class="lbl">Whole video</label><select data-act="vspeed" title="Base speed for every clip">
      ${[1, 1.05, 1.1, 1.15, 1.2, 1.25, 1.3].map(v => `<option value="${v}" ${(+sh().style.speed || 1) === v ? "selected" : ""}>${v.toFixed(2)}×</option>`).join("")}</select>
      <label class="chk" title="Speed slow reads up toward TikTok Shop pace (${sh().style.pace?.wps || 5} words a second, like the reference), up to ${sh().style.pace?.max || 1.1}×, after cutting the pauses"><input type="checkbox" data-act="autopace" ${sh().style.pace?.auto ? "checked" : ""}> auto pace</label></div>
    <h3>Look</h3>
    <div class="row"><label class="lbl">Brightness</label><input type="range" data-look="brightness" min="-0.3" max="0.2" step="0.01" value="${+sh().style.look?.brightness || 0}"><span class="val">${(+sh().style.look?.brightness || 0).toFixed(2)}</span></div>
    <div class="row"><label class="lbl">Skin smoothing</label><input type="range" data-look="smooth" min="0" max="1" step="0.05" value="${+sh().style.look?.smooth || 0}"><span class="val">${(+sh().style.look?.smooth || 0).toFixed(2)}</span></div>
    <div class="row"><label class="lbl">This clip</label><input type="range" data-f="bright" min="-0.3" max="0.3" step="0.01" value="${+t.bright || 0}"><span class="val">${(+t.bright || 0).toFixed(2)}</span></div>
    <p class="hint">Brightness and smoothing apply to the whole video; "This clip" nudges just this one. The smooth preview and the download show them exactly.</p>
    <h3>Freeze frame</h3>
    <div class="row"><label class="lbl">Hold the end</label><select data-act="freeze" title="Freeze on the last frame (the cold-open hook), then carry on">
      ${[...new Set([0, 0.5, 0.8, 1, 1.2, 1.5, 2, 2.3, 2.5, 3, +t.freeze || 0])].sort((a, b) => a - b).map(v => `<option value="${v}" ${(+t.freeze || 0) === v ? "selected" : ""}>${v ? v + "s" : "off"}</option>`).join("")}</select></div>
    ${+t.freeze ? `<div class="row"><label class="lbl">Title</label><input id="titleEdit" type="text" value="${esc(t.title || "")}" placeholder="e.g. the game's name"></div>` : ""}
    <h3>Framing</h3>
    <div class="row"><label class="lbl">Zoom</label><input type="range" data-f="zoom" min="1" max="2" step="0.02" value="${t.zoom}"><span class="val">${t.zoom.toFixed(2)}</span></div>
    <div class="row"><label class="lbl">Left / right</label><input type="range" data-f="pan_x" min="0" max="1" step="0.01" value="${t.pan_x}"><span class="val">${t.pan_x.toFixed(2)}</span></div>
    <div class="row"><label class="lbl">Up / down</label><input type="range" data-f="pan_y" min="0" max="1" step="0.01" value="${t.pan_y}"><span class="val">${t.pan_y.toFixed(2)}</span></div>
    <div class="row"><label class="lbl">Volume</label><input type="range" data-f="volume" min="0" max="2" step="0.05" value="${t.volume}"><span class="val">${t.volume.toFixed(2)}</span></div>
    <div class="row"><button data-act="frameAll" title="Use this zoom and position for every take of this line">Apply framing to the whole line</button></div>
    <p class="hint mono">${esc(src?.name || "")} @ ${fmt(t.in)}</p>`;
  $$("#capEdit, #lineEdit", el).forEach(autoGrow);
}
$("#inspector").addEventListener("click", e => {
  const t = sel(); if (!t) return;
  const b = e.target.closest("button"); if (!b) return;
  if (b.dataset.act === "capReset") { resetCaptions(t); return; }
  if (b.dataset.act === "use" && !t.usable) toggleUsable(t);
  if (b.dataset.act === "rej" && t.usable) toggleUsable(t);
  if (b.dataset.act === "frameAll") commit(s => s.takes.filter(x => x.line === t.line).forEach(x => { x.zoom = t.zoom; x.pan_x = t.pan_x; x.pan_y = t.pan_y; x.user.zoom = x.user.pan_x = x.user.pan_y = true; }));
  if (b.dataset.n) { const [k, d] = b.dataset.n.split(":"); setTrim(t, k, t[k] + +d, "nudge"); }
});
$("#inspector").addEventListener("change", e => {
  const t = sel(); if (!t) return;
  if (e.target.dataset.act === "speed") { commit(s => { const x = s.takes.find(x => x.id === t.id); x.speed = e.target.value ? +e.target.value : null; x.user.speed = !!e.target.value; }); renderInspector(); return; }
  if (e.target.dataset.act === "vspeed") { commit(s => { s.style.speed = +e.target.value; }); renderInspector(); return; }
  if (e.target.dataset.act === "autopace") { commit(s => { s.style.pace = { ...(s.style.pace || {}), auto: e.target.checked }; }); renderInspector(); return; }
  if (e.target.dataset.act === "freeze") { commit(s => { const x = s.takes.find(x => x.id === t.id); x.freeze = +e.target.value; x.user.freeze = true; }); renderInspector(); return; }
  if (e.target.dataset.act !== "line") return;
  const lineId = e.target.value || null;
  moveTake(t.id, lineId, !!lineId, undefined);
});
$("#inspector").addEventListener("input", e => {
  if (e.target.id === "capEdit") { autoGrow(e.target); setCaptions(sel(), e.target.value); return; }
  if (e.target.id === "titleEdit") { const t = sel(); commit(s => { const x = s.takes.find(x => x.id === t.id); x.title = e.target.value; x.user.title = true; }, { key: "title" + t.id, board: false }); return; }
  if (e.target.id === "lineEdit") {
    const t = sel(); autoGrow(e.target);
    commit(s => { s.script.find(l => l.id === t.line).text = e.target.value; s.script_guessed = false; }, { key: "line" + t.line, board: false, left: true });
    markScriptChanged(); return;
  }
  if (e.target.dataset.look) {
    const k = e.target.dataset.look, v = +e.target.value; e.target.nextElementSibling.textContent = v.toFixed(2);
    commit(s => { s.style.look = { ...(s.style.look || {}), [k]: v }; }, { key: "look" + k, board: false });
    showIdle(); return;
  }
  const t = sel(), f = e.target.dataset.f; if (!t || !f) return;
  if (locked(t, "be reframed")) { renderInspector(); return; }
  const v = +e.target.value; e.target.nextElementSibling.textContent = v.toFixed(2);
  commit(s => { const x = s.takes.find(x => x.id === t.id); x[f] = v; x.user[f] = true; }, { key: f + t.id, board: false });
});
function setTrim(t, k, v, key, board = true) {
  if (locked(t, "be re-trimmed")) return t[k];
  const src = srcById(t.src);
  v = clamp(v, 0, src?.duration || 1e9);
  if (k === "in") v = Math.min(v, t.out - 0.2); else v = Math.max(v, t.in + 0.2);
  commit(s => { const x = s.takes.find(x => x.id === t.id); x[k] = Math.round(v * 1000) / 1000; x.user[k] = true; }, { key: key + k + t.id, board });
  renderTrim();
  return v;
}

// ---------- preview ----------
function fitStage() {
  // the preview fills the right pane (its width and height)
  const pane = $("#right"), head = pane.querySelector(".paneHead");
  const w = pane.clientWidth - 24, hgt = pane.clientHeight - (head?.offsetHeight || 46) - 18;
  const sc = Math.max(0.05, Math.min(w / W, hgt / H));
  $("#stage").style.transform = `scale(${sc})`;
  $("#stageWrap").style.height = H * sc + "px";
  $("#stageWrap").style.width = W * sc + "px";
  $("#stageWrap").style.margin = "0 auto";
}
window.addEventListener("resize", fitStage);

function ensureSource(t) {
  const src = srcById(t.src);
  const want = `/proxy/${src.key}.mp4`;
  if (video.dataset.src === want) return Promise.resolve();
  video.dataset.src = want; video.src = want;
  return new Promise(res => video.addEventListener("loadedmetadata", res, { once: true }));
}
function layoutVideo(t) {
  const vw = video.videoWidth || 1080, vh = video.videoHeight || 1920;
  const li = lineIdx(t.line), punch = li % 2 === 1 ? (+sh().style.punch_in || 1) : 1;
  const z = t.zoom * punch;
  const k = Math.max(W / vw, H / vh) * z;
  const w = vw * k, h = vh * k;
  Object.assign(video.style, { width: w + "px", height: h + "px", left: -(w - W) * t.pan_x + "px", top: -(h - H) * t.pan_y + "px" });
  video.volume = clamp(t.volume, 0, 1);
  video.playbackRate = spd(t); video.preservesPitch = true;
  const lb = (+sh().style.look?.brightness || 0) + (+t.bright || 0);  // live: close to the render's curve
  video.style.filter = lb ? `brightness(${1 + lb * 0.8}) contrast(${1 - Math.min(0, lb) * 0.15})` : "";
}
// items for the current preview: the selected video's takes, with offsets
function items(mode) {
  if (mode === "take") { const t = sel(); return t ? [{ t, off: 0 }] : []; }
  const v = videos().vids[S.vid - 1]; if (!v) return [];
  let off = 0;
  return v.takes.map(t => { const it = { t, off }; off += dur(t); return it; });
}
const P = { on: false, mode: "video", list: [], i: 0, loop: false };
S.vpos = {};  // video number -> where you left it (seconds into the video)
const vTotal = list => list.reduce((a, x) => a + dur(x.t), 0);
function locate(list, vt) {  // video time -> which take, and where in its source
  let i = list.findIndex(x => vt < x.off + dur(x.t) - 0.001);
  if (i < 0) i = list.length - 1;
  return { i, at: srcAt(list[i].t, clamp(vt - list[i].off, 0, Math.max(0, dur(list[i].t) - 0.03))) };
}
const curVt = () => { const it = P.list[P.i]; if (it && !P.pv && P.held != null) return it.off + dur(it.t) - (+it.t.freeze || 0) + (P.extra || 0); if (it && P.pv) return it.off + clamp(video.currentTime - P.pv.segs[P.i].off, 0, dur(it.t)); return it ? it.off + clamp(takeRel(it.t, video.currentTime), 0, dur(it.t)) : 0; };

// the video: from where you left it (or a given point)
async function playVideo(n = S.vid, from = null) {
  if (n !== S.vid) selectVideo(n);
  S.playScope = "video";
  const list = items("video"); if (!list.length) return;
  let vt = from ?? S.vpos[S.vid] ?? 0;
  if (vt >= vTotal(list) - 0.1) vt = 0;  // at the end: start over
  const { i, at } = locate(list, vt);
  const pv = pvMatch(list, S.pv[S.vid]);
  Object.assign(P, { on: true, mode: "video", list, i, loop: false, pv });
  playIcons();
  if (pv) await cuePv(i, at); else await cue(i, true, at);
  tick();
}
// the selected clip: once, on a loop, or then carry on through the video
async function playClip(how = "once", t = sel()) {
  if (!t) { toast("Click a take first"); return; }
  const here = video.currentTime;
  const inside = video.dataset.src === `/proxy/${srcById(t.src).key}.mp4` && here > t.in && here < t.out - 0.15;
  if (how === "continue") {
    const list = items("video"), j = list.findIndex(x => x.t.id === t.id);
    if (j >= 0) return playVideo(S.vid, list[j].off + (inside ? here - t.in : 0));
    how = "once";  // a spare or rejected take isn't in this video: just play it
  }
  if (P.pv) await leavePv();
  Object.assign(P, { on: true, mode: "take", list: [{ t, off: 0 }], i: 0, loop: how === "loop", pv: null });
  playIcons();
  await cue(0, true, inside ? here : null);
  tick();
}
function play(mode = "video") { return mode === "take" ? playClip("once") : playVideo(); }
function pause() {
  const vt = P.pv ? curVt() : null;
  P.on = false; video.pause(); playIcons();
  if (P.pv) { P.pv = null; seekVideo(vt, true); }  // back on the proxy, same frame, ready to edit
}
function playIcons() {
  const vid = P.on && P.mode === "video";
  $("#playVid").textContent = vid ? "⏸︎" : "▶︎";
  $("#clipOnce").classList.toggle("on", P.on && P.mode === "take" && !P.loop);
  $("#clipLoop").classList.toggle("on", P.on && P.mode === "take" && P.loop);
  $$("#grid [data-vplay]").forEach(b => { b.textContent = vid && +b.dataset.vplay === S.vid ? "⏸︎" : "▶︎"; });
}
async function cue(i, start, at = null) {
  const it = P.list[i]; P.i = i;
  if (start && P.mode === "video") followPlayback(it.t);
  await ensureSource(it.t);
  layoutVideo(it.t);
  video.currentTime = at ?? it.t.in;
  if (start) await video.play().catch(() => {});
}
async function tick() {
  if (!P.on) return;
  if (P.pv) return tickPv();
  const it = P.list[P.i];
  const gap = inCut(it.t, video.currentTime);
  if (gap && gap[1] < it.t.out - 0.02) video.currentTime = gap[1];  // skip what he cut out
  else if ((video.currentTime >= it.t.out - 0.02 || video.ended || gap) && +it.t.freeze > 0 && (P.held == null || performance.now() - P.held < it.t.freeze * 1000)) {
    if (P.held == null) { P.held = performance.now(); video.pause(); }
    P.extra = (performance.now() - P.held) / 1000;  // freeze frame: hold, then carry on
  }
  else if (video.currentTime >= it.t.out - 0.02 || video.ended || gap) {
    P.held = null; P.extra = 0;
    if (P.mode === "take") {
      if (P.loop) await cue(0, true);
      else { pause(); return; }  // stays on this clip
    } else if (P.i + 1 < P.list.length) await cue(P.i + 1, true);
    else { pause(); S.vpos[S.vid] = 0; showIdle(); return; }
  }
  drawOverlay(P.list[P.i], P.list);
  sfxCrossings();
  requestAnimationFrame(tick);
}
// jump anywhere in the video (scrub bar, J / L); keeps playing if it was
async function seekVideo(vt, scrub = false) {
  const list = items("video"); if (!list.length) return;
  vt = clamp(vt, 0, vTotal(list) - 0.03);
  const { i, at } = locate(list, vt);
  S.vpos[S.vid] = vt; S.playScope = "video";
  if (P.on && P.pv && !scrub) { video.currentTime = P.pv.segs[i].off + takeRel(list[i].t, at); return; }
  if (P.on && P.mode === "video" && !scrub) { if (i !== P.i || Math.abs(video.currentTime - at) > 0.05) await cue(i, true, at); return; }
  if (P.on) pause();
  P.list = list; P.mode = "video";
  followPlayback(list[i].t);
  if (P.i !== i || video.dataset.src !== `/proxy/${srcById(list[i].t.src).key}.mp4`) { P.i = i; await ensureSource(list[i].t); }
  P.i = i;
  layoutVideo(list[i].t);
  seekPreview(at);
  S.idleFor = list[i].t.id;
  drawVbar(vt);
}
async function showIdle() {
  if (P.on || !sh()) return;
  const t = sel() || videos().vids[S.vid - 1]?.takes[0];
  $("#stageEmpty").hidden = !!t;
  if (!t) { $("#hookImg").hidden = $("#ctaImg").hidden = true; $("#subs").innerHTML = ""; return; }
  const list = items("video"), it = list.find(x => x.t.id === t.id) || { t, off: 0 };
  P.list = list.length ? list : [it]; P.i = Math.max(0, P.list.indexOf(it));
  await ensureSource(t);
  if (P.on) return;  // playback started meanwhile: it owns the frame
  layoutVideo(t);
  const at = (t.words?.[0]?.[1] ?? t.in) + 0.25;
  const near = video.currentTime >= t.in - 3 && video.currentTime <= t.out + 3;
  if (!scrubbing && !hovering && (S.idleFor !== t.id || !near)) video.currentTime = Math.min(at, t.out - 0.05);
  S.idleFor = t.id;
  drawOverlay(it, P.list);
}
video.addEventListener("seeked", () => { if (!P.on && P.list[P.i]) drawOverlay(P.list[P.i], P.list); });

// overlays: hook (start), CTA (last line), karaoke subtitles
let lastOv = null;
const capUrl = (text, st) => st?.preset === "deluxe"
  ? `/api/hookcard.png?text=${encodeURIComponent(text)}&style=${encodeURIComponent(JSON.stringify(st))}`
  : `/api/caption.png?text=${encodeURIComponent(text)}&style=${encodeURIComponent(JSON.stringify({ ...st, y: 0.5 }))}`;
function setOv(img, text, st, show, yFrac = st.y) {
  if (!show || !text) { img.hidden = true; img.dataset.k = ""; return; }
  const url = capUrl(text, st);
  if (img.dataset.k !== url) { img.dataset.k = url; img.src = url; img.classList.remove("pop"); void img.offsetWidth; if (st.pop) img.classList.add("pop"); }
  img.style.top = (H * yFrac - 320) + "px";
  img.hidden = false;
}
function drawOverlay(it, list, local = video.currentTime) {
  const s = sh(), st = s.style, t = it.t;
  const extra = P.on ? (P.extra || 0) : 0;  // seconds into the take's freeze frame
  const vt = it.off + clamp(takeRel(t, local), 0, dur(t)) + extra;
  const frz = +t.freeze || 0, onFreeze = frz > 0 && (extra > 0 || (!P.on && takeRel(t, local) >= dur(t) - frz - 0.05));
  const showTitle = !!(st.title?.on !== false && t.title && onFreeze), dancing = st.title?.anim === "dance";
  const ti = titleImg();
  if (dancing) {  // the game-show logo card (adcut/titlefx.card), not a caption
    const url = `/api/title.png?text=${encodeURIComponent(t.title || "")}&style=${encodeURIComponent(JSON.stringify(st.title || {}))}`;
    if (showTitle && ti.dataset.k !== url) { ti.dataset.k = url; ti.src = url; }
    ti.hidden = !showTitle; ti.classList.remove("pop");
  } else setOv(ti, t.title, { ...st.title, y: 0.5 }, showTitle, st.title?.y ?? 0.42);
  if (showTitle && dancing) {  // same keyframes as adcut/titlefx.py
    const e = extra > 0 ? extra : 0, [x, y, r, sc] = titleDance(e, H * (st.title?.y ?? 0.42));
    Object.assign(ti.style, { left: (x - W / 2) + "px", top: (y - 320) + "px", transform: `rotate(${r}deg) scale(${sc})` });
  } else if (ti.style.transform) Object.assign(ti.style, { left: "", transform: "" });
  const hooks = s.hooks.filter(h => h.trim());
  const hook = hooks.length ? hooks[(S.vid - 1) % hooks.length] : "";
  setOv($("#hookImg"), hook, st.hook, st.hook.on && vt < st.hook.seconds, hookY(st, hook.length < 24 ? 1 : hook.length < 52 ? 2 : 3, list[0]?.t.line));
  $("#ctaImg").hidden = true;  // retired: nothing on screen that isn't in the script
  drawSubs(t, local);
  const total = list.reduce((a, x) => a + dur(x.t), 0);
  if (P.mode === "video" || !P.on) { S.vpos[S.vid] = vt; drawVbar(vt); }
  drawAssets(it, list, vt, total);
  drawCart(it, list, vt, total);
  if (renderGuides.line !== t.line) { renderGuides.line = t.line; renderGuides(); }
  boardPlayhead(P.on || P.list.includes(it) ? it : null);
  $("#timeDisp").innerHTML = `<span class="tdLabel">${P.mode === "take" && P.on ? "Take" : `Video ${S.vid}`}</span>${P.pv ? ` <span class="pvTag" title="Playing the pre-rendered preview">⚡ smooth</span>` : ""} ${fmt(vt)} / ${fmt(total)} <span class="tdLabel">Source</span> ${fmt(local)}`;
}
function cueGroups(words, per) {
  const out = []; let cur = [];
  words.forEach((w, i) => { cur.push(w); if (cur.length >= per || /[.!?,]$/.test(w[0]) || i === words.length - 1) { out.push(cur); cur = []; } });
  return out;
}
function drawSubs(t, time) {
  const sub = S.subPreview ? { ...sh().style.subs, ...S.subPreview } : sh().style.subs, box = $("#subs");
  const hidden = lines().find(l => l.id === t.line)?.subs_off && !S.subPreview;
  if (!sub.on || hidden || !t.words?.length) { box.innerHTML = ""; return; }
  const groups = cueGroups(t.words.filter(w => !inCut(t, (w[1] + w[2]) / 2)), sub.words_per_line);
  if (!groups.length) { box.innerHTML = ""; return; }
  let gi = groups.findIndex((g, i) => time < (groups[i + 1]?.[0][1] ?? 1e9));
  if (gi < 0) gi = groups.length - 1;
  const g = groups[gi];
  const stroke = !sub.box && sub.outline_w ? `-webkit-text-stroke:${sub.outline_w * 2}px ${sub.outline};paint-order:stroke fill;` : "";
  const shadow = !sub.box && sub.shadow ? `text-shadow:0 ${sub.shadow * 2}px ${sub.shadow * 3}px rgba(0,0,0,.75);` : "";
  box.style.cssText = `top:${H * subsY({ ...sh().style, subs: sub }, t.line)}px;right:200px;left:60px;font:${sub.bold === false ? 600 : 900} ${sub.size}px '${sub.font}';color:${sub.color};${stroke}${shadow}`;
  box.classList.toggle("boxed", !!sub.box);
  if (sub.box) box.style.setProperty("--subbox", hexA(sub.box, sub.box_alpha ?? 0.6));
  box.innerHTML = g.map((w, i) => {
    const on = sub.karaoke && time >= w[1] && (i === g.length - 1 || time < g[i + 1][1]);
    const txt = sub.uppercase ? w[0].toUpperCase() : w[0];
    return `<span class="w" style="${on ? `color:${sub.highlight};${sub.pop ? "transform:scale(1.1)" : ""}` : ""}">${esc(txt)}</span>`;
  }).join(" ");
}

function renderTransport() {
  if (!sh()) return;
  const v = videos();
  $("#vidPos").textContent = v.count ? `Video ${S.vid} / ${v.count}` : "no videos";
  renderVbar();
  // Download renders the video first whenever it changed, so there's no separate Render step
  const r = sh().renders[S.vid], sv = savedOf(S.vid), posted = videos().vids[S.vid - 1]?.posted;
  $("#rendered").innerHTML = !v.count ? "" : `
    <button id="dlOne" ${S.job ? "disabled" : ""} title="Make the finished video and save it (+ a .txt to paste into TikTok) to the Outbox (OneDrive)">⬇ Download</button>
    <button id="starOne" class="${sv ? "on" : ""}" title="${sv ? "Saved: its takes are locked to this video (click to unsave and free them)" : "Save to your posting queue; locks its takes so no other video reuses the footage"}">${sv ? "★ Saved 🔒" : "☆ Save"}</button>
    ${sv ? `<label class="chk" title="Mark as posted to TikTok (its takes are already locked because it is saved)"><input type="checkbox" id="postedOne" ${sv.posted ? "checked" : ""}> Posted</label>` : ""}
    ${r?.downloaded ? `<span class="muted" title="${esc(r.downloaded)}">⬇ in the Outbox</span>` : ""}`;
}
$("#rendered").addEventListener("click", async e => {
  if (e.target.id === "dlOne") await startDownload([S.vid]);
  if (e.target.closest("#starOne")) toggleSaved(S.vid);
});
$("#rendered").addEventListener("change", e => {
  if (e.target.id === "postedOne") { const n = S.vid; setPosted(n, e.target.checked); if (e.target.checked) flushSave().then(() => postDialog(S.sid, n)); }
});
$("#folderBtn").onclick = () => api(`/api/shoots/${S.sid}/open-folder?which=downloads`, { json: {} }).catch(e => toast(e.message));
$("#playVid").onclick = () => (P.on && P.mode === "video" ? pause() : playVideo());
$("#restartVid").onclick = () => playVideo(S.vid, 0);
$("#clipOnce").onclick = () => (P.on && P.mode === "take" && !P.loop ? pause() : playClip("once"));
$("#clipLoop").onclick = () => (P.on && P.mode === "take" && P.loop ? pause() : playClip("loop"));
$("#clipOn").onclick = () => playClip("continue");
$("#prevVid").onclick = () => selectVideo(S.vid - 1);
$("#nextVid").onclick = () => selectVideo(S.vid + 1);
$("#undo").onclick = undo; $("#redo").onclick = redo;

// ---------- trim strip ----------
// A viewport onto the whole raw file: S.tv = {t0, t1} is what's visible (zoom = its
// span, scrolling = moving it). Fit = the selected take plus a little either side.
let TW = null, scrubbing = false; // {t, t0, t1, w, dur}
const xOf = t => ((t - TW.t0) / (TW.t1 - TW.t0)) * TW.w;
const tOf = x => TW.t0 + (x / TW.w) * (TW.t1 - TW.t0);
const fitView = t => { const pad = Math.max(1.5, dur(t) * 0.5); return { t0: t.in - pad, t1: t.out + pad }; };
let trimTimer = null;
function scheduleTrim() { if (!trimTimer) trimTimer = setTimeout(() => { trimTimer = null; renderTrim(); }, 16); }
function renderTrim() {
  const el = $("#trim"), t = sel();
  if (!t) { el.innerHTML = ""; $("#trimLabel").textContent = "Select a take"; TW = null; $("#trimScroll").hidden = true; $("#trimZoomLbl").textContent = ""; return; }
  const src = srcById(t.src), D = src.duration || t.out + 5;
  if (S.trimFor !== t.id) { S.trimFor = t.id; S.tv = fitView(t); }
  let { t0, t1 } = S.tv;
  const span = Math.min(t1 - t0, D);
  if (t0 < 0) { t0 = 0; t1 = span; }
  if (t1 > D) { t1 = D; t0 = Math.max(0, D - span); }
  S.tv = { t0, t1 };
  TW = { t, t0, t1, w: el.clientWidth, dur: D };
  $("#trimLabel").innerHTML = `<b>${dur(t).toFixed(2)}s</b> · ${fmt(t.in)} → ${fmt(t.out)} in ${esc(src.name)}`;
  $("#trimZoomLbl").textContent = span >= 60 ? `${(span / 60).toFixed(1)} min` : `${span.toFixed(span < 10 ? 1 : 0)}s`;
  const words = (S.words[src.key] || []).filter(w => w[2] > t0 && w[1] < t1);
  const others = sh().takes.filter(x => x.src === t.src && x.id !== t.id && x.out > t0 && x.in < t1);
  const pxPerS = TW.w / (t1 - t0);
  const step = [0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300].find(v => v * pxPerS >= 70) || 600;
  const ticks = [];
  for (let v = Math.ceil(t0 / step) * step; v <= t1; v += step) ticks.push(`<span class="tick" style="left:${xOf(v) + 2}px">${fmt(v).replace(/\.\d$/, step < 1 ? "$&" : "")}</span>`);
  el.innerHTML = ticks.join("") +
    others.map(o => `<div class="other" style="left:${xOf(o.in)}px;width:${xOf(o.out) - xOf(o.in)}px" title="another take${o.line ? ` (line ${lineIdx(o.line) + 1})` : ""}"></div>`).join("") +
    words.map(w => { const wpx = Math.max(3, xOf(w[2]) - xOf(w[1]));
      return `<span class="word ${w[1] >= t.in && w[2] <= t.out ? (inCut(t, (w[1] + w[2]) / 2) ? "gone" : "in") : ""}" style="left:${xOf(w[1])}px;width:${wpx}px" title="${esc(w[0])}">${wpx >= 16 ? esc(w[0]) : ""}</span>`; }).join("") +
    pieceBoxes(t) +
    cutsOf(t).map(([a, b], ci) => `<div class="cutbox" data-ci="${ci}" style="left:${xOf(a)}px;width:${Math.max(3, xOf(b) - xOf(a))}px" title="Cut out (${(b - a).toFixed(2)}s). Click to put it back."></div>`).join("") +
    (t.splits || []).filter(x => x > t.in && x < t.out).map(x => `<div class="splitmark" style="left:${xOf(x)}px" title="Split ${fmt(x)}"></div>`).join("") +
    `<div class="range" style="left:${xOf(t.in)}px;width:${xOf(t.out) - xOf(t.in)}px"></div>
     <div class="handle" data-h="in" style="left:${xOf(t.in) - 7}px"></div><div class="handle" data-h="out" style="left:${xOf(t.out) - 7}px"></div>
     <div class="ph" style="left:${xOf(srcNow())}px"></div>` +
    (t.fx || []).map(c => `<div class="fxchip" data-fx="${c.id}" style="left:${xOf(c.at)}px;width:${Math.max(18, xOf(c.at + (c.dur || 2)) - xOf(c.at))}px" title="${esc(fxLabel(c.kind))} · drag to move · click for length / remove">${fxEmoji(c.kind)}</div>`).join("") +
    (t.sfx || []).map(c => { const a = c.at - soundHit(c.name), b = a + soundDur(c.name);
      return `<div class="sfxchip" data-sx="${c.id}" style="left:${xOf(a)}px;width:${Math.max(14, xOf(b) - xOf(a))}px" title="${esc(soundLabel(c.name))} · ${soundDur(c.name).toFixed(1)}s · drag to move · click for volume / remove">
        <i class="hitline" style="left:${xOf(c.at) - xOf(a)}px"></i><span class="em" style="left:${xOf(c.at) - xOf(a)}px">${soundEmoji(c.name)}</span></div>`; }).join("");
  // file scrollbar: thumb = what's visible, mark = the take
  const sc = $("#trimScroll"); sc.hidden = false;
  const SW = sc.clientWidth, X = v => (v / D) * SW;
  const th = sc.querySelector(".thumb");
  th.style.left = Math.min(SW - 24, X(t0)) + "px"; th.style.width = Math.max(24, X(t1) - X(t0)) + "px";
  const cm = sc.querySelector(".clipmark");
  cm.style.left = X(t.in) + "px"; cm.style.width = Math.max(2, X(t.out) - X(t.in)) + "px";
}
function zoomTrim(factor, tc = null) {
  if (!S.tv || !TW) return;
  const { t0, t1 } = S.tv, span = t1 - t0, ns = clamp(span * factor, 1, 600);
  tc ??= (t0 + t1) / 2;
  const nt0 = tc - (tc - t0) * (ns / span);
  S.tv = { t0: nt0, t1: nt0 + ns }; scheduleTrim();
}
function panTrim(dt) { if (S.tv) { S.tv = { t0: S.tv.t0 + dt, t1: S.tv.t1 + dt }; scheduleTrim(); } }
$("#trimZoom").addEventListener("click", e => {
  const z = e.target.closest("button[data-z]")?.dataset.z; if (!z || !sel()) return;
  if (z === "fit") { S.tv = fitView(sel()); scheduleTrim(); } else zoomTrim(z === "in" ? 0.6 : 1 / 0.6);
});
$("#trim").addEventListener("wheel", e => {
  if (!TW) return;
  e.preventDefault();
  const rect = $("#trim").getBoundingClientRect();
  if (e.ctrlKey || e.metaKey) zoomTrim(Math.exp(e.deltaY * 0.0025), tOf(e.clientX - rect.left));
  else panTrim((Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.deltaY) * (TW.t1 - TW.t0) / TW.w);
}, { passive: false });
$("#trimScroll").addEventListener("pointerdown", e => {
  if (!TW || !S.tv) return;
  const sc = $("#trimScroll"), rect = sc.getBoundingClientRect(), span = S.tv.t1 - S.tv.t0;
  const tAt = x => (x - rect.left) / rect.width * TW.dur;
  let grab;
  if (e.target.classList.contains("thumb")) grab = tAt(e.clientX) - S.tv.t0;
  else { grab = span / 2; S.tv = { t0: tAt(e.clientX) - grab, t1: tAt(e.clientX) - grab + span }; scheduleTrim(); }
  sc.setPointerCapture(e.pointerId);
  const mv = ev => { const a = tAt(ev.clientX) - grab; S.tv = { t0: a, t1: a + span }; scheduleTrim(); };
  const up = () => { sc.removeEventListener("pointermove", mv); sc.removeEventListener("pointerup", up); };
  sc.addEventListener("pointermove", mv); sc.addEventListener("pointerup", up);
});
new ResizeObserver(() => { if (TW) scheduleTrim(); }).observe($("#trim"));
function snapTo(time, which, alt) {
  if (LS.get("snap", true) === !!alt || !TW) return time;  // the 🧲 toggle; Alt flips it
  const words = S.words[srcById(TW.t.src).key] || [];
  const st = sh().style;
  let best = time, bd = 0.12;
  for (const w of words) {
    const edge = which === "in" ? w[1] - st.pad_before : w[2] + st.pad_after;
    if (Math.abs(edge - time) < bd) { bd = Math.abs(edge - time); best = edge; }
  }
  return best;
}
$("#trim").addEventListener("mousedown", e => {
  if (!TW) return;
  const rect = $("#trim").getBoundingClientRect();
  const h = e.target.closest(".handle")?.dataset.h;
  const t = TW.t;
  S.playScope = "take";
  const chip = e.target.closest(".sfxchip");
  if (chip) { sfxChipGesture(e, chip, rect); return; }
  const fchip = e.target.closest(".fxchip");
  if (fchip) { fxChipGesture(e, fchip, rect); return; }
  if (lockedIn(sel()) && (h || e.shiftKey || S.cutMode || e.target.closest(".cutbox, .piece"))) { locked(sel(), "be re-trimmed"); return; }
  const cb = e.target.closest(".cutbox"), pc = e.target.closest(".piece");
  if (!h && (cb || pc || S.cutMode || e.shiftKey)) { cutGesture(e, rect, cb, pc); return; }
  if (h) {
    pause(); scrubbing = true;
    const move = ev => {
      const v = setTrim(sel(), h, snapTo(tOf(ev.clientX - rect.left), h, ev.altKey), "drag", false);
      seekPreview(h === "in" ? v : Math.max(v - 0.04, sel().in));  // the frame right at the marker
    };
    const up = () => { window.removeEventListener("mousemove", move); window.removeEventListener("mouseup", up);
      S.lastKey = null; scrubbing = false; renderBoard(); };
    window.addEventListener("mousemove", move); window.addEventListener("mouseup", up);
    return;
  }
  pause(); scrubbing = true;
  const seek = ev => { seekPreview(clamp(tOf(ev.clientX - rect.left), TW.t0, TW.t1)); $("#trim .ph").style.left = xOf(video.currentTime) + "px"; };
  seek(e);
  const up = () => { window.removeEventListener("mousemove", seek); window.removeEventListener("mouseup", up); scrubbing = false; };
  window.addEventListener("mousemove", seek); window.addEventListener("mouseup", up);
  void t;
});
video.addEventListener("timeupdate", () => {
  const ph = $("#trim .ph"); if (!ph || !TW) return;
  const t = srcNow();
  ph.style.left = xOf(t) + "px";
  if (P.on && TW.t === sel() && (t > TW.t1 || t < TW.t0)) { const span = TW.t1 - TW.t0; S.tv = { t0: t - span * 0.1, t1: t + span * 0.9 }; scheduleTrim(); }
});

// ---------- keys ----------
document.addEventListener("keydown", e => {
  if (!S.sid) return;
  const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName) && document.activeElement.type !== "range" && document.activeElement.type !== "checkbox";
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z" && !typing) { e.preventDefault(); e.shiftKey ? redo() : undo(); return; }
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "y" && !typing) { e.preventDefault(); redo(); return; }
  if (typing) return;
  if (e.key === " ") {  // Space = what you're working on; Shift+Space = the other one
    e.preventDefault();
    const scope = S.playScope || "video";
    if (P.on) pause(); else play(e.shiftKey ? (scope === "take" ? "video" : "take") : scope);
  }
  else if (e.key === "Home") { e.preventDefault(); playVideo(S.vid, 0); }
  else if (e.key === "s" || e.key === "S") splitHere();
  else if (e.key === "c" || e.key === "C") $("#cutMode").click();
  else if (e.key === "j" || e.key === "J") seekVideo(curVt() - 2);
  else if (e.key === "l" || e.key === "L") seekVideo(curVt() + 2);
  else if (e.key === "u" || e.key === "U" || e.key === "x" || e.key === "Delete") toggleUsable();
  else if (e.key === "ArrowLeft") { e.preventDefault(); moveSel(-1, 0); }
  else if (e.key === "ArrowRight") { e.preventDefault(); moveSel(1, 0); }
  else if (e.key === "ArrowUp") { e.preventDefault(); moveSel(0, -1); }
  else if (e.key === "ArrowDown") { e.preventDefault(); moveSel(0, 1); }
  else if (e.key === "[") selectVideo(S.vid - 1);
  else if (e.key === "]") selectVideo(S.vid + 1);
  else if (e.key === "Escape" && !$("#cropWin").hidden) { $("#cropWin").hidden = true; CROP = null; }
  else if (e.key === "Escape") { S.sel = null; renderBoard(); renderInspector(); renderTrim(); showIdle(); }
});

// ---------- boot ----------
// language: the button says which one is on; its menu lists them (i18n.js)
$("#langBtn").textContent = `🌐 ${{ en: "English", pt: "Português" }[LANG] || "English"} ▾`;
$("#langBtn").onclick = e => { e.stopPropagation(); $("#langMenu").hidden = !$("#langMenu").hidden; };
$$("#langMenu [data-lang]").forEach(b => {
  const on = b.dataset.lang === LANG;
  b.classList.toggle("on", on); b.setAttribute("aria-checked", on);
  b.onclick = () => (on ? ($("#langMenu").hidden = true) : setLang(b.dataset.lang));
});
document.addEventListener("click", e => { if (!e.target.closest(".langPick")) $("#langMenu").hidden = true; });
document.addEventListener("keydown", e => { if (e.key === "Escape") $("#langMenu").hidden = true; });
(async function boot() {
  [S.presets, S.fonts, S.sounds, S.fxKinds] = await Promise.all([api("/api/presets"), api("/api/fonts"), api("/api/sounds").catch(() => []), api("/api/fx").catch(() => [])]);
  const presetNames = ["deluxe", "box", "sticker", "meme", "neon", "story", "news"].filter(p => p === "deluxe" || S.presets[p]);
  $$(".presetSel").forEach(s => (s.innerHTML = presetNames.map(p => `<option>${p}</option>`).join("")));
  $$(".fontSel").forEach(s => (s.innerHTML = [...S.fonts.system, ...S.fonts.custom.map(f => f.name)].map(f => `<option>${esc(f)}</option>`).join("")));
  const fontCss = S.fonts.custom.map(f => `@font-face{font-family:'${f.name}';src:url('${f.url}')}`).join("");
  if (fontCss) document.head.insertAdjacentHTML("beforeend", `<style>${fontCss}</style>`);
  const sid = location.hash.slice(1);
  if (sid.startsWith("review/")) { try { await openReview(sid.slice(7)); return; } catch (e) { console.warn("could not open review", sid, e); } }
  else if (sid) { try { await openShoot(sid); return; } catch (e) { console.warn("could not open shoot", sid, e); } }
  showHome();
})();
// links to a shoot (#id) work without a reload, and Back returns to the list
window.addEventListener("hashchange", async () => {
  const h = location.hash.slice(1);
  if (h.startsWith("review/")) { if (h.slice(7) !== RV.sid) openReview(h.slice(7)).catch(() => showHome()); return; }
  const sid = h;
  if (sid && sid !== S.sid) { await flushSave(); openShoot(sid).catch(() => showHome()); }
  else if (!sid && (S.sid || RV.sid)) { if (S.sid) await flushSave(); showHome(); }
});


// ---------- assets: screenshots / photos / clips placed on lines ----------
const normWord = w => String(w || "").toLowerCase().replace(/’/g, "'")
  .replace(/n't\b/g, " not").replace(/'ve\b/g, " have").replace(/'re\b/g, " are").replace(/'ll\b/g, " will").replace(/'m\b/g, " am").replace(/'d\b/g, " would")
  .replace(/[^a-z0-9]/g, "");
const assetById = id => (sh().assets || []).find(a => a.id === id);
const assetUrl = a => `/api/shoots/${S.sid}/assets/${a.id}/preview.png?c=${encodeURIComponent(JSON.stringify(a.crop || null))}`;
const POS = { "↖": o => ({ x: 0.05, y: 0.09 }), "↗": o => ({ x: 0.95 - o.w, y: 0.09 }), "⬆": o => ({ x: (1 - o.w) / 2, y: 0.09 }),
  "⊙": o => ({ x: (1 - o.w) / 2, y: 0.3 }), "↙": o => ({ x: 0.05, y: 0.5 }), "↘": o => ({ x: 0.95 - o.w, y: 0.5 }) };
const OV_DEFAULT = { at_word: null, at_occ: 0, hold: "line", x: 0.05, y: 0.09, w: 0.46, radius: 28, border: 0, shadow: true, pop: true };
let openPlace = null;  // placement shown expanded in the panel (and highlighted on the preview)

function renderAssets() {
  const as = sh().assets || [], ovs = sh().overlays || [];
  $("#assetSum").textContent = as.length ? `${as.length} · ${ovs.length} placed` : "";
  const hasRef = !!sh().reference.file;
  $("#grabRef").disabled = !hasRef;
  $("#grabRef").title = hasRef ? "Save the frame showing in the reference video above as an image, then crop it"
    : "Drop the reference video file into ① first (TikTok: Share → Download video)";
  const list = $("#assetList");
  if (list.contains(document.activeElement) && document.activeElement.type === "text") return;
  list.innerHTML = as.map(a => {
    const mine = ovs.filter(o => o.asset === a.id);
    return `<li data-a="${a.id}">
      <div class="ahead"><img src="${assetUrl(a)}" alt="" title="${esc(a.name)}">
        <div class="ameta"><input class="aname" value="${esc(a.name)}" title="Name">
          <span class="muted">${a.kind === "video" ? "clip" : "image"} · ${mine.length ? `on ${mine.map(o => "line " + (lineIdx(o.line) + 1)).join(", ")}` : "not placed yet"}</span>
          <div class="aacts">${a.kind === "image" ? `<button data-act="crop">✂ Crop</button>` : ""}
            <button data-act="place" class="${mine.length ? "" : "primary"}">＋ Place on a line</button>
            <button data-act="adel" class="icon dangerish" title="Remove this asset">🗑</button></div></div></div>
      ${mine.map(placeHtml).join("")}</li>`;
  }).join("");
}
function placeHtml(o) {
  const line = lines().find(l => l.id === o.line);
  const words = line ? line.text.split(/\s+/).filter(Boolean) : [];
  const opts = words.map((w, i) => ({ w, occ: words.slice(0, i).filter(x => normWord(x) === normWord(w)).length }));
  const hold = String(o.hold);
  const open = openPlace === o.id;
  const when = o.at_word ? `“${esc(o.at_word.replace(/[^\w']/g, ""))}”` : "line start";
  return `<div class="place ${open ? "open" : ""}" data-o="${o.id}">
    <div class="phead" data-act="toggle"><b>Line ${lineIdx(o.line) + 1}</b> <span class="muted">from ${when} · ${hold === "line" ? "to line end" : hold === "video" ? "to the end" : hold + "s"}</span>${assetCoversProduct(o) ? '<span class="warnx" title="It covers the product area; drag it aside">⚠ on the product</span>' : ""}<span class="spacer"></span><span class="muted">${open ? "▾" : "▸"}</span></div>
    ${open ? `
    <div class="row"><label class="lbl">Line</label><select data-f="line">${lines().map((l, i) => `<option value="${l.id}" ${l.id === o.line ? "selected" : ""}>${i + 1}. ${esc(l.text.slice(0, 34))}</option>`).join("")}</select></div>
    <div class="row"><label class="lbl">Pops in on</label><select data-f="word"><option value="">the start of the line</option>
      ${opts.map(x => `<option value="${esc(x.w)}|${x.occ}" ${o.at_word && normWord(x.w) === normWord(o.at_word) && x.occ === (o.at_occ || 0) ? "selected" : ""}>“${esc(x.w)}”${x.occ ? ` (${x.occ + 1}${["", "nd", "rd"][x.occ] || "th"})` : ""}</option>`).join("")}</select></div>
    <div class="row"><label class="lbl">Stays</label><select data-f="hold">
      <option value="line" ${hold === "line" ? "selected" : ""}>until the line ends</option>
      <option value="video" ${hold === "video" ? "selected" : ""}>until the video ends</option>
      ${[0.8, 1, 1.5, 2, 3, 4, 6].map(n => `<option value="${n}" ${hold === String(n) ? "selected" : ""}>for ${n}s</option>`).join("")}</select></div>
    <div class="row"><label class="lbl">Position</label><span class="seg">${Object.keys(POS).map(k => `<button data-pos="${k}" class="icon" title="Snap to ${k}">${k}</button>`).join("")}</span></div>
    <div class="row"><label class="lbl">Size</label><input type="range" data-f="w" min="0.12" max="1" step="0.01" value="${o.w}"><span class="val">${Math.round(o.w * 100)}%</span></div>
    <div class="row"><label class="lbl">Corners</label><input type="range" data-f="radius" min="0" max="80" step="2" value="${o.radius}"><span class="val">${o.radius}</span></div>
    <div class="row"><label class="chk"><input type="checkbox" data-f="shadow" ${o.shadow ? "checked" : ""}> Shadow</label>
      <label class="chk"><input type="checkbox" data-f="border" ${o.border ? "checked" : ""}> White border</label>
      <label class="chk"><input type="checkbox" data-f="pop" ${o.pop ? "checked" : ""}> Pop in</label></div>
    <div class="row"><span class="hint" style="margin:0">Drag it on the preview to move it; drag its corner to resize.</span><span class="spacer"></span><button data-act="odel" class="dangerish">Remove</button></div>` : ""}
  </div>`;
}
function editOv(id, fn, key) {
  commit(s => { const o = s.overlays.find(o => o.id === id); if (o) fn(o); }, { board: false, key });
  renderAssets(); showIdle();
}
$("#assetList").addEventListener("click", e => {
  const li = e.target.closest("li[data-a]"); if (!li) return;
  const a = assetById(li.dataset.a);
  const act = e.target.closest("[data-act]")?.dataset.act;
  const pl = e.target.closest(".place")?.dataset.o;
  if (act === "crop") openCrop(a);
  if (act === "adel") {
    if (!confirm(`Remove “${a.name}”${(sh().overlays || []).some(o => o.asset === a.id) ? " and its placements" : ""}?`)) return;
    commit(s => { s.assets = s.assets.filter(x => x.id !== a.id); s.overlays = s.overlays.filter(o => o.asset !== a.id); }, { board: false });
    renderAssets(); showIdle();
  }
  if (act === "place") {
    const lineId = sel()?.line || lines()[0]?.id;
    if (!lineId) { toast("Add the script first"); return; }
    const id = newId();
    commit(s => s.overlays.push({ ...OV_DEFAULT, id, asset: a.id, line: lineId }), { board: false });
    openPlace = id; renderAssets();
    // show it: jump the preview to that line in the current video
    const t = takeInVideo(lineId);
    if (t) select(t.id); else showIdle();
  }
  if (act === "toggle") {
    openPlace = openPlace === pl ? null : pl; renderAssets();
    const o = (sh().overlays || []).find(x => x.id === pl);
    if (o && openPlace) { const t = takeInVideo(o.line); if (t && sel()?.line !== o.line) select(t.id); else showIdle(); }
  }
  if (act === "odel") { commit(s => { s.overlays = s.overlays.filter(o => o.id !== pl); }, { board: false }); renderAssets(); showIdle(); }
  const pos = e.target.closest("[data-pos]")?.dataset.pos;
  if (pos) editOv(pl, o => Object.assign(o, POS[pos](o)));
});
$("#assetList").addEventListener("input", e => {
  const pl = e.target.closest(".place")?.dataset.o, f = e.target.dataset.f;
  if (e.target.classList.contains("aname")) {
    const id = e.target.closest("li").dataset.a;
    commit(s => { s.assets.find(a => a.id === id).name = e.target.value; }, { board: false, key: "aname" + id });
    return;
  }
  if (!pl || !(f === "w" || f === "radius")) return;
  const v = +e.target.value;
  e.target.nextElementSibling.textContent = f === "w" ? Math.round(v * 100) + "%" : v;
  commit(s => { const o = s.overlays.find(o => o.id === pl); o[f] = v; }, { board: false, key: f + pl });
  showIdle();
});
$("#assetList").addEventListener("change", e => {
  const pl = e.target.closest(".place")?.dataset.o, f = e.target.dataset.f; if (!pl || !f) return;
  if (f === "line") {
    editOv(pl, o => { o.line = e.target.value; o.at_word = null; o.at_occ = 0; });
    const t = takeInVideo(e.target.value);  // show that line in the preview
    if (t) select(t.id);
  }
  if (f === "word") editOv(pl, o => { const [w, occ] = e.target.value ? e.target.value.split("|") : [null, 0]; o.at_word = w; o.at_occ = +occ; });
  if (f === "hold") editOv(pl, o => { o.hold = ["line", "video"].includes(e.target.value) ? e.target.value : +e.target.value; });
  if (f === "shadow" || f === "pop") editOv(pl, o => { o[f] = e.target.checked; });
  if (f === "border") editOv(pl, o => { o.border = e.target.checked ? 10 : 0; });
});

// when each placement shows, in video time (mirrors adcut/assets.py timings)
function assetTimes(list, total) {
  const out = [];
  for (const o of sh().overlays || []) {
    const a = assetById(o.asset), it = list.find(x => x.t.line === o.line);
    if (!a || !it) continue;
    const tk = it.t;
    let start = tk.in;
    if (o.at_word) {
      const hits = (tk.words || []).filter(w => normWord(w[0]) === normWord(o.at_word));
      if (hits.length) start = Math.max(tk.in, hits[Math.min(o.at_occ || 0, hits.length - 1)][1]);
    }
    const t0 = it.off + takeRel(tk, start);
    const t1 = o.hold === "line" ? it.off + dur(tk) : o.hold === "video" ? total : t0 + +o.hold;
    out.push({ o, a, t0, t1: Math.min(t1, total), line: o.line });
  }
  return out;
}
function drawAssets(it, list, vt, total) {
  const layer = $("#assetLayer"), seen = new Set();
  for (const x of assetTimes(list, total)) {
    // playing: only while it's on; paused: show everything on this line so it can be placed
    const live = vt >= x.t0 - 0.01 && vt < x.t1;
    const show = P.on ? live : (x.line === it.t.line || live);
    if (!show) continue;
    seen.add(x.o.id);
    let el = layer.querySelector(`[data-o="${x.o.id}"]`);
    const src = x.a.kind === "video" ? `/api/shoots/${S.sid}/assets/${x.a.id}/file` : assetUrl(x.a);
    if (!el) {
      el = document.createElement("div"); el.className = "asel"; el.dataset.o = x.o.id;
      el.innerHTML = (x.a.kind === "video" ? `<video muted loop playsinline autoplay></video>` : `<img alt="">`) + `<span class="rs" title="Drag to resize"></span>`;
      layer.appendChild(el);
      if (x.o.pop && P.on) { el.classList.add("pop"); }
    }
    const m = el.firstElementChild;
    if (m.dataset.src !== src) { m.dataset.src = src; m.src = src; }
    const o = x.o;
    Object.assign(el.style, { left: W * o.x + "px", top: H * o.y + "px", width: W * o.w + "px" });
    Object.assign(m.style, { borderRadius: o.radius + "px", border: o.border ? `${o.border}px solid #fff` : "none",
      boxShadow: o.shadow ? "0 14px 40px rgba(0,0,0,.5)" : "none" });
    el.classList.toggle("ghost", !P.on && !live);
    el.classList.toggle("focus", openPlace === o.id);
  }
  for (const el of [...layer.children]) if (!seen.has(el.dataset.o)) el.remove();
}
// drag to move / corner to resize, on the preview
$("#assetLayer").addEventListener("pointerdown", e => {
  const el = e.target.closest(".asel"); if (!el || P.on) return;
  e.preventDefault();
  const id = el.dataset.o, o0 = { ...(sh().overlays || []).find(o => o.id === id) };
  const scale = $("#stage").getBoundingClientRect().width / W;
  const resize = e.target.classList.contains("rs");
  const sx = e.clientX, sy = e.clientY;
  if (openPlace !== id) { openPlace = id; renderAssets(); }
  try { el.setPointerCapture(e.pointerId); } catch (err) { /* synthetic pointer */ }
  const mv = ev => {
    const dx = (ev.clientX - sx) / scale / W, dy = (ev.clientY - sy) / scale / H;
    commit(s => {
      const o = s.overlays.find(o => o.id === id);
      if (resize) o.w = clamp(o0.w + dx, 0.08, 1.2);
      else { o.x = clamp(o0.x + dx, -0.5, 1); o.y = clamp(o0.y + dy, -0.3, 1); }
    }, { board: false, key: "drag" + id });
    showIdle();
  };
  const up = () => { el.removeEventListener("pointermove", mv); el.removeEventListener("pointerup", up); S.lastKey = null; renderAssets(); };
  el.addEventListener("pointermove", mv); el.addEventListener("pointerup", up);
});

// grab a frame from the reference video, paste a screenshot
$("#grabRef").onclick = async () => {
  const v = $("#refVideo");
  if (!sh().reference.file) { toast("Drop the reference video file into ① first"); return; }
  v.pause();
  await flushSave();
  try {
    const r = await api(`/api/shoots/${S.sid}/assets/grab`, { json: { t: v.currentTime || 0 } });
    await reload();
    openCrop(assetById(r.asset.id));
  } catch (e) { toast(e.message, 5000); }
};
async function uploadAsset(file, name) {
  await flushSave();
  const r = await fetch(`/api/shoots/${S.sid}/upload?kind=asset&name=${encodeURIComponent(name || file.name || "pasted.png")}`, { method: "PUT", body: file });
  if (!r.ok) { toast("Couldn't add that: " + ((await r.json().catch(() => ({}))).detail || r.statusText)); return null; }
  const j = await r.json();
  await reload();
  return j.asset;
}
document.addEventListener("paste", async e => {
  if (!S.sid) return;
  const typing = /^(INPUT|TEXTAREA)$/.test(document.activeElement.tagName);
  const f = [...(e.clipboardData?.files || [])].find(x => /^image\//.test(x.type));
  if (!f || typing) return;
  e.preventDefault();
  $("#secAssets").open = true;
  const a = await uploadAsset(f, `screenshot-${new Date().toTimeString().slice(0, 8).replace(/:/g, "")}.png`);
  if (a) toast("Screenshot added to ② Assets. Crop it or place it on a line.");
});

// ---------- crop window ----------
let CROP = null; // {asset, box: [x0,y0,x1,y1] fractions}
function openCrop(a) {
  if (!a || a.kind !== "image") return;
  CROP = { asset: a.id, box: a.crop ? [...a.crop] : null };
  const img = $("#cropImg");
  img.onload = drawCrop;
  img.src = `/api/shoots/${S.sid}/assets/${a.id}/file`;
  $("#cropWin").hidden = false;
}
function drawCrop() {
  const b = CROP?.box, box = $("#cropBox"), img = $("#cropImg");
  if (!b) { box.hidden = true; return; }
  box.hidden = false;
  Object.assign(box.style, { left: img.offsetLeft + b[0] * img.clientWidth + "px", top: img.offsetTop + b[1] * img.clientHeight + "px",
    width: (b[2] - b[0]) * img.clientWidth + "px", height: (b[3] - b[1]) * img.clientHeight + "px" });
}
$("#cropArea").addEventListener("pointerdown", e => {
  if (!CROP) return;
  e.preventDefault();
  const img = $("#cropImg"), r = img.getBoundingClientRect();
  const fx = x => clamp((x - r.left) / r.width, 0, 1), fy = y => clamp((y - r.top) / r.height, 0, 1);
  const b = CROP.box, inBox = b && e.target === $("#cropBox");
  const x0 = fx(e.clientX), y0 = fy(e.clientY), start = b ? [...b] : null;
  try { $("#cropArea").setPointerCapture(e.pointerId); } catch (err) { /* synthetic pointer */ }
  const mv = ev => {
    const x = fx(ev.clientX), y = fy(ev.clientY);
    if (inBox) { // move the box
      const w = start[2] - start[0], h = start[3] - start[1];
      const nx = clamp(start[0] + x - x0, 0, 1 - w), ny = clamp(start[1] + y - y0, 0, 1 - h);
      CROP.box = [nx, ny, nx + w, ny + h];
    } else CROP.box = [Math.min(x0, x), Math.min(y0, y), Math.max(x0, x), Math.max(y0, y)];
    drawCrop();
  };
  const up = () => { $("#cropArea").removeEventListener("pointermove", mv); $("#cropArea").removeEventListener("pointerup", up);
    if (CROP.box && (CROP.box[2] - CROP.box[0] < 0.02 || CROP.box[3] - CROP.box[1] < 0.02)) { CROP.box = start; drawCrop(); } };
  $("#cropArea").addEventListener("pointermove", mv); $("#cropArea").addEventListener("pointerup", up);
});
$("#cropArea").addEventListener("dblclick", () => { if (CROP) { CROP.box = null; drawCrop(); } });
$("#cropReset").onclick = () => { CROP.box = null; drawCrop(); };
$("#cropCancel").onclick = () => { $("#cropWin").hidden = true; CROP = null; };
$("#cropOk").onclick = () => {
  const { asset, box } = CROP;
  commit(s => { s.assets.find(a => a.id === asset).crop = box ? box.map(v => Math.round(v * 10000) / 10000) : null; }, { board: false });
  $("#cropWin").hidden = true; CROP = null;
  $$("#assetLayer .asel").forEach(el => el.remove());
  renderAssets(); showIdle();
};
window.addEventListener("resize", drawCrop);

// ---------- collapsible side panes (remembered), like the meme editor ----------
function applyPanes() {
  const lc = LS.get("leftCollapsed", false), rc = LS.get("rightCollapsed", false);
  document.body.classList.toggle("lc", lc);
  document.body.classList.toggle("rc", rc);
  $$(".paneToggle").forEach(b => {
    const left = b.dataset.pane === "left", shut = left ? lc : rc;
    b.textContent = left ? (shut ? "»" : "«") : (shut ? "«" : "»");
    b.title = shut ? "Expand this panel" : "Collapse this panel";
  });
  requestAnimationFrame(() => { fitStage(); if (TW) scheduleTrim(); });
}
$$(".paneToggle").forEach(b => b.addEventListener("click", e => {
  e.stopPropagation();
  const key = b.dataset.pane === "left" ? "leftCollapsed" : "rightCollapsed";
  LS.set(key, !LS.get(key, false)); applyPanes();
}));
["left", "right"].forEach(side => $("#" + side).addEventListener("click", e => {
  const key = side === "left" ? "leftCollapsed" : "rightCollapsed";
  if (LS.get(key, false) && !e.target.closest(".paneToggle")) { LS.set(key, false); applyPanes(); }
}));


// ---------- TikTok's UI, the safe area and the product (mirrors adcut/layout.py) ----------
const UI_ZONES = {
  "top tabs": [0.0, 0.0, 1.0, 0.075],
  "like / comment / share": [0.835, 0.40, 1.0, 0.87],
  "caption + username": [0.0, 0.80, 0.835, 1.0],
  "orange cart tag": [0.03, 0.745, 0.62, 0.795],
};
const SAFE = [0.04, 0.085, 0.82, 0.735], CART_TAG = UI_ZONES["orange cart tag"];
function boxOverlap(a, b) {
  const w = Math.min(a[2], b[2]) - Math.max(a[0], b[0]), h = Math.min(a[3], b[3]) - Math.max(a[1], b[1]);
  return w <= 0 || h <= 0 ? 0 : (w * h) / Math.max(1e-6, (a[2] - a[0]) * (a[3] - a[1]));
}
function placeBand(yPref, bandH, product, x0 = SAFE[0], x1 = SAFE[2]) {
  const lo = SAFE[1] + bandH / 2, hi = SAFE[3] - bandH / 2, cl = y => Math.min(hi, Math.max(lo, y));
  const y = cl(yPref);
  if (!product) return y;
  const band = c => [x0, c - bandH / 2, x1, c + bandH / 2];
  if (boxOverlap(band(y), product) === 0) return y;
  const cands = [cl(product[3] + 0.012 + bandH / 2), cl(product[1] - 0.012 - bandH / 2), y];
  return cands.sort((a, b) => (Math.round(boxOverlap(band(a), product) * 1000) - Math.round(boxOverlap(band(b), product) * 1000)) || Math.abs(a - yPref) - Math.abs(b - yPref))[0];
}
const productFor = (st, lineId) => lines().find(l => l.id === lineId)?.product_box || st.product_box;
const subsY = (st, lineId) => placeBand(st.subs.y, st.subs.size * 1.35 / 1920, productFor(st, lineId));
const hookY = (st, n, lineId) => placeBand(st.hook.y, (st.hook.size * 1.25 * n + 40) / 1920, productFor(st, lineId), 0.06, 0.82);
const curLine = () => (P.list[P.i]?.t || sel())?.line;

// guides: TikTok's buttons / caption / product tag + the safe area + the product box
function renderGuides() {
  const on = LS.get("guides", false);
  $("#guidesBtn").classList.toggle("on", on);
  const g = $("#uiGuides"); g.hidden = !on;
  const px = b => `left:${b[0] * W}px;top:${b[1] * H}px;width:${(b[2] - b[0]) * W}px;height:${(b[3] - b[1]) * H}px`;
  if (on) g.innerHTML = `<div class="safe" style="${px(SAFE)}"><span>safe for text</span></div>` +
    Object.entries(UI_ZONES).map(([k, b]) => `<div class="zone ${k === "orange cart tag" ? "cart" : ""}" style="${px(b)}"><span>${k === "orange cart tag" ? "🛒 product tag" : k}</span></div>`).join("") +
    `<div class="rail">${["♥", "💬", "🔖", "↪"].map(i => `<i>${i}</i>`).join("")}</div>`;
  const lid = curLine(), own = lines().find(l => l.id === lid)?.product_box;
  const pb = sh() && productFor(sh().style, lid), el = $("#prodBox");
  el.hidden = !pb || (!on && !marking);
  if (pb) { el.style.cssText = px(pb); el.querySelector("span").textContent = own ? `product · line ${lineIdx(lid) + 1}` : "product · every line"; }
  $("#clearProd").hidden = !pb;
  $("#allProd").hidden = !own;
  $("#markProd").classList.toggle("on", marking);
  $("#markProd").textContent = marking ? "📦 Drag around the product…" : pb ? `📦 Product area ✓${lid ? ` (line ${lineIdx(lid) + 1})` : ""}` : "📦 Product area";
}
let marking = false;
$("#guidesBtn").onclick = () => { LS.set("guides", !LS.get("guides", false)); renderGuides(); };
$("#markProd").onclick = () => { marking = !marking; $("#markLayer").hidden = !marking; pause(); renderGuides(); };
$("#clearProd").onclick = () => {
  const lid = curLine();
  commit(s => { const l = s.script.find(l => l.id === lid); if (l?.product_box) l.product_box = null; else s.style.product_box = null; }, { board: false });
  renderGuides(); showIdle();
};
$("#allProd").onclick = () => {  // this line's box for every line
  const lid = curLine(), b = lines().find(l => l.id === lid)?.product_box; if (!b) return;
  commit(s => { s.style.product_box = b; s.script.forEach(l => { l.product_box = null; }); }, { board: false });
  renderGuides(); showIdle(); toast("Using this product area for every line");
};
$("#markLayer").addEventListener("pointerdown", e => {
  e.preventDefault();
  const r = $("#stage").getBoundingClientRect();
  const fx = x => clamp((x - r.left) / r.width, 0, 1), fy = y => clamp((y - r.top) / r.height, 0, 1);
  const x0 = fx(e.clientX), y0 = fy(e.clientY);
  try { $("#markLayer").setPointerCapture(e.pointerId); } catch (err) { /* synthetic pointer */ }
  const mv = ev => {
    const b = [Math.min(x0, fx(ev.clientX)), Math.min(y0, fy(ev.clientY)), Math.max(x0, fx(ev.clientX)), Math.max(y0, fy(ev.clientY))];
    const lid = curLine(), bb = b.map(v => Math.round(v * 1000) / 1000);
    commit(s => { const l = s.script.find(l => l.id === lid);
      if (l) l.product_box = bb; else s.style.product_box = bb;
      if (!s.style.product_box) s.style.product_box = bb;  // first one marked = the default for every line
    }, { board: false, key: "prodbox" });
    renderGuides(); showIdle();
  };
  const up = () => { $("#markLayer").removeEventListener("pointermove", mv); $("#markLayer").removeEventListener("pointerup", up);
    marking = false; $("#markLayer").hidden = true; S.lastKey = null; renderGuides(); renderAssets();
    toast(`Product area saved for line ${lineIdx(curLine()) + 1}. Subtitles stay off it. (Lines you don't mark use the first one.)`, 4500); };
  $("#markLayer").addEventListener("pointermove", mv); $("#markLayer").addEventListener("pointerup", up);
});

// orange cart pointer (mirrors adcut/pointer.py): starts on the spoken trigger words
function cartTimes(list, total) {
  const cp = sh().style.cart_pointer;
  if (!cp?.on) return [];
  const phrases = cp.words.split(",").map(p => p.trim().split(/\s+/).map(normWord).filter(Boolean)).filter(p => p.length).sort((a, b) => b.length - a.length);
  const out = [];
  for (const it of list) {
    const ws = (it.t.words || []).map(w => [normWord(w[0]), w[1]]);
    let best = null;
    for (const ph of phrases) {
      for (let i = 0; i + ph.length <= ws.length; i++) {
        if (ph.every((p, j) => ws[i + j][0] === p)) { if (best === null || ws[i][1] < best) best = ws[i][1]; break; }
      }
    }
    if (best !== null) { const a = it.off + Math.max(0, takeRel(it.t, best)); out.push([a, Math.min(total, a + +cp.seconds)]); }
  }
  return out;
}
function drawCart(it, list, vt, total) {
  $("#cartPtr").hidden = true;
  drawFx(it, list, vt, total);
}
function drawCartOld(it, list, vt, total) {
  const el = $("#cartPtr"), cp = sh().style.cart_pointer;
  const on = cartTimes(P.mode === "take" && P.on ? [it] : list, total).some(([a, b]) => vt >= a && vt < b);
  if (on && el.hidden) { el.classList.remove("go"); void el.offsetWidth; el.classList.add("go"); }
  el.hidden = !on;
  if (on) {
    el.style.setProperty("--cp", cp.color || "#FF8A00");
    const b = CART_TAG;
    Object.assign(el.querySelector(".ring").style, { left: b[0] * W - 14 + "px", top: b[1] * H - 12 + "px", width: (b[2] - b[0]) * W + 28 + "px", height: (b[3] - b[1]) * H + 24 + "px" });
    Object.assign(el.querySelector(".arrow").style, { left: b[0] * W - 14 + 150 - 52 + "px", top: b[1] * H - 12 - 18 - 150 + "px" });
  }
}
// warn when an asset sits on the product
function assetCoversProduct(o) {
  const pb = sh().style.product_box, a = assetById(o.asset); if (!pb || !a) return false;
  const c = a.crop || [0, 0, 1, 1], ar = ((c[3] - c[1]) * a.h) / ((c[2] - c[0]) * a.w);
  const box = [o.x, o.y, o.x + o.w, o.y + (o.w * W * ar) / H];
  return boxOverlap(pb, box) > 0.2;
}

$("#rejTake").onclick = () => { const t = sel(); if (!t) { toast("Click a take first"); return; } toggleUsable(t); };


// ---------- preview follows the mouse on the trim strip ----------
// One seek in flight at a time (the newest position wins), so the frame keeps up
// with a fast drag instead of queueing stale seeks.
let hovering = false, seekBusy = false, seekWant = null, hoverBack = null;
function seekPreview(t) {
  seekWant = t;
  if (seekBusy) return;
  seekBusy = true;
  video.currentTime = t;
}
video.addEventListener("seeked", () => {
  seekBusy = false;
  if (seekWant !== null && Math.abs(video.currentTime - seekWant) > 0.02) { const t = seekWant; seekWant = null; seekPreview(t); }
  else seekWant = null;
});
$("#trim").addEventListener("mousemove", e => {
  if (!TW || P.on || scrubbing || e.buttons) return;
  if (!hovering) { hovering = true; hoverBack = video.currentTime; }
  const r = $("#trim").getBoundingClientRect();
  seekPreview(clamp(tOf(e.clientX - r.left), TW.t0, TW.t1));
  $("#trim .ph").style.left = xOf(seekWant ?? video.currentTime) + "px";
});
$("#trim").addEventListener("mouseleave", () => {
  if (!hovering) return;
  hovering = false;
  if (!P.on && !scrubbing && hoverBack !== null) seekPreview(hoverBack);  // back to where you were
  hoverBack = null;
});
// a click on the strip sets where you were (so leaving doesn't undo the scrub)
$("#trim").addEventListener("mouseup", () => { if (hovering) hoverBack = seekWant ?? video.currentTime; });


// ---------- pick videos and download them (like Meme Factory's posts) ----------
S.pick = new Set();
function renderState(n) {
  const r = sh()?.renders[n];
  if (!r?.file) return "none";
  return !r.sig || (S.sigs?.[n] && r.sig !== S.sigs[n]) ? "stale" : "fresh";
}
function renderMark(n) {  // just whether it is in the Outbox
  return sh().renders[n]?.downloaded ? '<span class="dl" title="Downloaded to the Outbox (OneDrive)">⬇</span>' : "";
}
function renderPicks() {}  // (multi-pick download retired: use ⬇ per video or Saved → Download all)
async function startDownload(nums) {
  if (!nums.length) return;
  await flushSave();
  try { S.job = await api(`/api/shoots/${S.sid}/download`, { json: { videos: nums } }); renderJob(); }
  catch (e) { toast(e.message); }
}
function downloadedToast(j, sid = S.sid) {
  const t = $("#toast");
  t.innerHTML = `✓ ${esc(j.msg)} <button id="toastOpen">📂 Open folder</button>`;
  t.hidden = false;
  clearTimeout(toastT); toastT = setTimeout(() => (t.hidden = true), 9000);
  $("#toastOpen").onclick = () => api(`/api/shoots/${sid}/open-folder?which=downloads`, { json: {} });
  S.pick.clear();
}


// ---------- whole-video scrub bar ----------
function renderVbar() {
  const bar = $("#vbar"), list = sh() ? items("video") : [];
  const tot = vTotal(list);
  bar.hidden = !list.length;
  if (!list.length) return;
  bar.innerHTML = list.map((x, i) => `<div class="vseg" style="flex:${dur(x.t) / tot} 0 0" title="Line ${lineIdx(x.t.line) + 1}: ${esc(x.t.text)}"><span>${lineIdx(x.t.line) + 1}</span></div>`).join("")
    + sfxEvents(list).map(ev => `<b class="vsfx" style="left:${clamp(ev.vt / tot, 0, 1) * 100}%;width:${clamp(soundDur(ev.name) / tot, 0, 1) * 100}%" title="${esc(soundLabel(ev.name))} · ${soundDur(ev.name).toFixed(1)}s"><span>${soundEmoji(ev.name)}</span></b>`).join("")
    + `<i class="vph"></i><span class="vtime mono"></span>`;
  drawVbar(S.vpos[S.vid] || 0);
}
function drawVbar(vt) {
  const bar = $("#vbar"), list = P.mode === "video" || !P.on ? P.list : items("video");
  const tot = vTotal(list.length ? list : items("video")); if (!tot) return;
  const ph = bar.querySelector(".vph"); if (!ph) return;
  ph.style.left = `${clamp(vt / tot, 0, 1) * 100}%`;
  bar.querySelector(".vtime").textContent = `${fmt(vt)} / ${fmt(tot)}`;
  const i = locate(items("video"), vt).i;
  $$("#vbar .vseg").forEach((el, k) => el.classList.toggle("cur", k === i));
}
$("#vbar").addEventListener("pointerdown", e => {
  const bar = $("#vbar"), list = items("video"); if (!list.length) return;
  const r = bar.getBoundingClientRect(), tot = vTotal(list);
  const vtAt = x => clamp((x - r.left) / r.width, 0, 1) * tot;
  const wasPlaying = P.on && P.mode === "video";
  try { bar.setPointerCapture(e.pointerId); } catch (err) { /* synthetic pointer */ }
  scrubbing = true;
  seekVideo(vtAt(e.clientX), true);
  const mv = ev => seekVideo(vtAt(ev.clientX), true);
  const up = ev => {
    bar.removeEventListener("pointermove", mv); bar.removeEventListener("pointerup", up);
    scrubbing = false;
    if (wasPlaying) playVideo(S.vid, vtAt(ev.clientX));
  };
  bar.addEventListener("pointermove", mv); bar.addEventListener("pointerup", up);
});

// 🧲 snapping on/off for the trim strip (remembered)
function renderSnap() { const on = LS.get("snap", true); $("#snapBtn").classList.toggle("on", on); $("#snapBtn").textContent = on ? "🧲 Snap to words" : "🧲 Snap off"; }
$("#snapBtn").onclick = () => { LS.set("snap", !LS.get("snap", true)); renderSnap(); };
renderSnap();


// ---------- resizable side panes (drag their inner edge; remembered) ----------
function applyWidths() {
  const lw = LS.get("lw", null), rw = LS.get("rw", null);
  if (lw) document.body.style.setProperty("--lw", lw + "px"); else document.body.style.removeProperty("--lw");
  if (rw) document.body.style.setProperty("--rw", rw + "px"); else document.body.style.removeProperty("--rw");
}
$$(".resizer").forEach(el => el.addEventListener("pointerdown", e => {
  e.preventDefault(); e.stopPropagation();
  const side = el.dataset.pane, key = side === "left" ? "lw" : "rw";
  try { el.setPointerCapture(e.pointerId); } catch (err) { /* synthetic pointer */ }
  document.body.classList.add("resizing");
  const mv = ev => {
    const w = side === "left" ? ev.clientX : window.innerWidth - ev.clientX;
    LS.set(key, Math.round(clamp(w, 200, Math.min(1100, window.innerWidth - 420))));
    applyWidths(); fitStage(); if (TW) scheduleTrim();
  };
  const up = () => { el.removeEventListener("pointermove", mv); el.removeEventListener("pointerup", up); document.body.classList.remove("resizing"); };
  el.addEventListener("pointermove", mv); el.addEventListener("pointerup", up);
}));
$$(".resizer").forEach(el => el.addEventListener("dblclick", () => { LS.set(el.dataset.pane === "left" ? "lw" : "rw", null); applyWidths(); fitStage(); }));
new ResizeObserver(() => fitStage()).observe($("#right"));
applyWidths();

// take details drawer beside the stacks
function applyInsp() {
  const shut = LS.get("inspShut", false);
  document.body.classList.toggle("inspShut", shut);
  $("#inspToggle").textContent = shut ? "«" : "»";
  $("#inspToggle").title = shut ? "Show the take details" : "Hide the take details";
}
$("#inspToggle").onclick = e => { e.stopPropagation(); LS.set("inspShut", !LS.get("inspShut", false)); applyInsp(); };
$("#inspWrap").addEventListener("click", () => { if (LS.get("inspShut", false)) { LS.set("inspShut", false); applyInsp(); } });
applyInsp();


// ---------- cutting out pauses inside a take ----------
S.cutMode = false;
function setCuts(t, fn, key = null) {
  if (locked(t, "be cut")) return;
  commit(s => { const x = s.takes.find(x => x.id === t.id); x.cuts = fn(cutsOf(x)).map(([a, b]) => [Math.round(a * 1000) / 1000, Math.round(b * 1000) / 1000]); x.user.cuts = true; }, { key });
  renderTrim(); renderVbar();
}
// drag = cut that bit out; click a red cut-out = put it back; click a piece between splits = cut it
function cutGesture(e, rect, cb, pc) {
  const t = sel(); if (!t) return;
  pause();
  const x0 = e.clientX, t0 = tOf(e.clientX - rect.left);
  let moved = false;
  const box = document.createElement("div"); box.className = "cutsel"; $("#trim").appendChild(box);
  const mv = ev => {
    if (Math.abs(ev.clientX - x0) < 3) return;
    moved = true;
    const t1 = tOf(ev.clientX - rect.left);
    box.style.left = xOf(Math.min(t0, t1)) + "px"; box.style.width = Math.abs(xOf(t1) - xOf(t0)) + "px";
    seekPreview(clamp(t1, TW.t0, TW.t1));
  };
  const up = ev => {
    window.removeEventListener("mousemove", mv); window.removeEventListener("mouseup", up); box.remove();
    if (!moved) {
      if (cb) { const ci = +cb.dataset.ci; setCuts(t, cs => cs.filter((_, i) => i !== ci)); toast("Put back"); }
      else if (pc) { const a = +pc.dataset.a, b = +pc.dataset.b; setCuts(t, cs => [...cs, [a, b]]); toast(`Cut out ${(b - a).toFixed(2)}s`); }
      return;
    }
    const t1 = tOf(ev.clientX - rect.left);
    const a = clamp(Math.min(t0, t1), t.in, t.out), b = clamp(Math.max(t0, t1), t.in, t.out);
    if (b - a >= 0.04) { setCuts(t, cs => [...cs, [a, b]]); toast(`Cut out ${(b - a).toFixed(2)}s. Click the red block to put it back.`); }
  };
  window.addEventListener("mousemove", mv); window.addEventListener("mouseup", up);
}
// split marks: pieces between them (and the take's ends) become clickable to cut out
function pieceBoxes(t) {
  const sp = (t.splits || []).filter(x => x > t.in && x < t.out).sort((a, b) => a - b);
  if (!sp.length) return "";
  const pts = [t.in, ...sp, t.out];
  return pts.slice(0, -1).map((a, i) => {
    const b = pts[i + 1];
    if (cutsOf(t).some(([x, y]) => x <= a + 0.01 && y >= b - 0.01)) return "";
    return `<div class="piece" data-a="${a}" data-b="${b}" style="left:${xOf(a)}px;width:${xOf(b) - xOf(a)}px" title="Click to cut this piece out (${(b - a).toFixed(2)}s)"></div>`;
  }).join("");
}
function splitHere() {
  const t = sel(); if (!t) { toast("Click a take first"); return; }
  const x = video.currentTime;
  if (!(x > t.in + 0.03 && x < t.out - 0.03)) { toast("Put the playhead inside the take first (click the strip)"); return; }
  commit(s => { const k = s.takes.find(k => k.id === t.id); k.splits = [...(k.splits || []), Math.round(x * 1000) / 1000]; });
  renderTrim();
  toast("Split. Make another, then click the piece between them to cut it out.");
}
// cut every pause between words longer than `gap`, leaving `keep` of breath either side
function tightenTake(t, gap = 0.3, keep = 0.1) {
  const ws = (S.words[srcById(t.src).key] || []).filter(w => w[1] >= t.in - 0.01 && w[2] <= t.out + 0.01);
  const add = [];
  for (let i = 1; i < ws.length; i++) {
    const a = ws[i - 1][2] + keep, b = ws[i][1] - keep;
    if (ws[i][1] - ws[i - 1][2] > gap && b - a >= 0.06) add.push([a, b]);
  }
  return add;
}
$("#tightenOne").onclick = () => {
  const t = sel(); if (!t) { toast("Click a take first"); return; }
  const add = tightenTake(t);
  if (!add.length) { toast("No pauses longer than 0.3s in this take"); return; }
  setCuts(t, cs => [...cs, ...add]);
  toast(`Cut ${add.length} pause${add.length === 1 ? "" : "s"} (${add.reduce((a, [x, y]) => a + y - x, 0).toFixed(2)}s)`);
};
$("#tightenAll").onclick = () => {
  let n = 0, secs = 0;
  commit(s => {
    const lk = lockedMap();
    for (const x of s.takes) {
      if (!x.usable || !x.line || lk[x.id]) continue;
      const add = tightenTake(x);
      if (!add.length) continue;
      x.cuts = [...cutsOf(x), ...add]; x.user.cuts = true;
      n += add.length; secs += add.reduce((a, [p, q]) => a + q - p, 0);
    }
  });
  renderTrim(); renderVbar();
  toast(n ? `Cut ${n} pauses across every usable take (${secs.toFixed(1)}s). Undo with Ctrl+Z.` : "No pauses longer than 0.3s found");
};
$("#cutMode").onclick = () => { S.cutMode = !S.cutMode; $("#cutMode").classList.toggle("on", S.cutMode); document.body.classList.toggle("cutting", S.cutMode); };
$("#splitBtn").onclick = splitHere;


// ---------- swap a take into a chosen video ----------
// A reject swapped into video k takes that slot and the take that was there goes to
// the rejects; a good / spare take trades places with whatever is in video k.
function swapSelect(t, good, k, wide = false) {
  const here = posOf(t).n, opts = [];
  for (const vid of videos().vids) {
    if (vid.n === here || vid.posted) continue;
    const occ = vid.takes.find(x => x.line === t.line);
    opts.push(`<option value="${vid.n}">${good ? "Move to" : "Swap into"} video ${vid.n}${occ ? "" : " (empty)"}</option>`);
  }
  if (!opts.length) return "";
  return `<select class="swapSel ${wide ? "wide" : ""}" data-swap="${t.id}" title="${good ? "Trade places with the take in another video" : "Use this take in a video (the take there goes to the rejects)"}">
    <option value="">⇄ ${good ? "Move to video…" : "Use in video…"}</option>${opts.join("")}</select>`;
}
function swapInto(id, v) {
  const t0 = takeById(id); if (!t0 || !t0.line || locked(t0, "move")) return;
  const target = videos().vids[v - 1];
  if (target?.posted) { toast(`🔒 Video ${v} is saved: its takes are locked`); renderBoard(); return; }
  const occId = target?.takes.find(x => x.line === t0.line)?.id;
  const lineId = t0.line;
  let msg = "";
  commit(s => {
    const t = s.takes.find(x => x.id === id);
    const st = s.takes.filter(x => x.line === lineId && x.usable).sort((a, b) => a.order - b.order || a.in - b.in);
    const occ = occId ? st.find(x => x.id === occId) : null;
    if (t.usable) {  // trade places
      const from = st.indexOf(t);
      const to = occ ? st.indexOf(occ) : -1;
      if (occ) { st[from] = occ; st[to] = t; } else { st.splice(from, 1); st.push(t); }
      msg = occ ? `Moved to video ${v}; that video's take swapped places with it` : `Moved to the end of the stack`;
    } else {  // a reject comes in, the take that was there goes out
      t.usable = true; t.user.usable = true;
      if (t.status === "nopayoff" || t.status === "flub" || t.status === "incomplete" || t.status === "paused") t.flags = [...t.flags, "used anyway"];
      if (occ) { occ.usable = false; occ.user.usable = true; st[st.indexOf(occ)] = t; msg = `Now in video ${v}; the take that was there went to the rejects`; }
      else { st.push(t); msg = `Now in video ${st.length}`; }
    }
    st.forEach((x, i) => { x.order = i; x.user.order = true; });
    s.takes.filter(x => x.line === lineId && !x.usable).sort((a, b) => a.order - b.order).forEach((x, i) => (x.order = i));
  });
  S.vid = clamp(v, 1, Math.max(1, videos().count));
  renderBoard(); renderInspector(); renderTransport(); showIdle();
  toast(msg);
}
document.addEventListener("change", e => {
  const sel2 = e.target.closest("select.swapSel");
  if (!sel2 || !sel2.value) return;
  swapInto(sel2.dataset.swap, +sel2.value);
});


// ---------- saving videos to the posting queue (like Meme Factory's Saved) ----------
const savedOf = n => (sh()?.saved || {})[n];
function toggleSaved(n) {
  const on = !savedOf(n);
  if (!on && savedOf(n)?.posted && !confirm(`Video ${n} is marked posted. Unsave it and unlock its takes so other videos can use them?`)) return;
  const ids = (videos().vids[n - 1]?.takes || []).map(t => t.id);  // what video n is right now
  commit(s => {
    s.saved = s.saved || {};
    if (on) s.saved[n] = { saved_at: Date.now() / 1000, sig: S.sigs?.[n] || null, posted: false, posted_at: null, takes: ids };
    else delete s.saved[n];
  });
  toast(on ? `★ Video ${n} saved: its ${ids.length} takes are locked to it (home → Saved)` : `Video ${n} unsaved: its takes are free again`, 4000);
}
function setPosted(n, posted) {
  const ids = (videos().vids[n - 1]?.takes || []).map(t => t.id);  // what video n is right now
  commit(s => { s.saved = s.saved || {}; const m = s.saved[n] || (s.saved[n] = { saved_at: Date.now() / 1000, sig: S.sigs?.[n] || null });
    if (!m.takes?.length) m.takes = ids;  // saving already locked it; posting keeps it locked
    m.posted = posted; m.posted_at = posted ? Date.now() / 1000 : null; });
  toast(posted ? `🔒 Video ${n} marked posted` : `Video ${n} marked not posted (still saved, so its takes stay locked)`, 4000);
}

// home: Shoots | Saved
let savedRows = [];
const PAGE = {  // sidebar section -> page title + one line of what it's for
  today: ["Today", "The shoot day, block by block"], planner: ["Shoot Days", "Sets, lighting, takes and posting times"],
  products: ["Lineup", "Products, colourways, orders and samples"], analytics: ["Our Accounts", "Followers, views and what's working"],
  competitors: ["Competitors", "What other creators post and probably sell"], shoots: ["Shoots", "Raw footage in, finished videos out"],
  saved: ["Posting", "Saved videos to post, and posted ones"], library: ["Scripts", "Script library, formats and style tags"],
  queue: ["Queue", "Every video from idea to posted"], overview: ["Overview", ""],
};
function showHomeTab(tab) {
  if (tab === "overview" || ![...$$(".sideNav [data-home]")].some(b => b.dataset.home === tab)) tab = "today";
  LS.set("homeTab", tab);
  $$(".sideNav [data-home]").forEach(b => b.classList.toggle("on", b.dataset.home === tab));
  const [title, sub] = PAGE[tab] || [tab, ""];
  $("#pageTitle").textContent = title; $("#pageSub").textContent = sub; document.title = `${title} · Ad Factory`;
  $("#newVideoBtn").hidden = !["planner", "products", "queue", "library"].includes(tab);
  $("#home").scrollTop = 0; $(".homeBox").scrollTop = 0;
  $("#homeShoots").hidden = $("#shootsHead").hidden = tab !== "shoots";
  $("#homeSaved").hidden = $("#savedHead").hidden = tab !== "saved";
  $$(".shopPane").forEach(p => (p.hidden = p.dataset.pane !== tab));  // shop.js: Overview, Queue, Products, Analytics, Library
  if (typeof PANES !== "undefined" && PANES[tab]) PANES[tab]().catch(e => toast("Couldn't load: " + e.message));
  loadSaved();
}
$$(".sideNav [data-home]").forEach(b => b.onclick = () => showHomeTab(b.dataset.home));
const savedFilter = () => LS.get("savedFilter", "todo");
$$(".savedfilter button").forEach(b => b.onclick = () => { LS.set("savedFilter", b.dataset.f); renderSaved(); });
async function loadSaved() {
  try { savedRows = await api("/api/saved"); } catch (e) { savedRows = []; }
  renderSaved();
}
function savedList(f = savedFilter()) {
  const todo = savedRows.filter(r => !r.posted), done = savedRows.filter(r => r.posted).sort((a, b) => (b.posted_at || 0) - (a.posted_at || 0));
  return f === "todo" ? todo : f === "done" ? done : [...todo, ...done];
}
const fmtDate = t => new Date(t * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric" });
function renderSaved() {
  const f = savedFilter(), list = savedList(f);
  $("#savedCount").textContent = savedList("todo").length || "";
  $("#cntTodo").textContent = savedList("todo").length;
  $("#cntDone").textContent = savedList("done").length;
  $$(".savedfilter button").forEach(b => b.classList.toggle("on", b.dataset.f === f));
  $("#dlAllSaved").hidden = !(f === "todo" && list.length);
  $("#dlAllSaved").textContent = `⬇ Download all (${list.length})`;
  $("#savedList").innerHTML = list.map(r => `<li class="saved ${r.posted ? "done" : ""}" data-sid="${r.sid}" data-n="${r.n}">
      ${r.thumb ? `<img loading="lazy" data-act="open" src="${r.thumb}" alt="">` : `<div class="noimg" data-act="open"></div>`}
      <div class="sbody">
        <div class="scap" data-act="open"><b translate="no">${esc(r.title)}</b> · video ${r.n} <span class="muted">${r.duration ? fmt(r.duration) : ""}</span></div>
        <div class="sfrom">${r.product ? `🛒 ${esc(r.product)} · ` : ""}${typeof accChip === "function" && r.account ? accChip(r.account) + " · " : ""}saved ${fmtDate(r.saved_at)}${r.posted && r.posted_at ? ` · posted ${fmtDate(r.posted_at)}` : ""}${r.downloaded ? " · ⬇ downloaded" : ""}${r.views != null ? ` · <b>${num(r.views)}</b> views` : ""}</div>
        ${!r.exists ? '<div class="warnx">⚠ this video no longer exists (the stacks got shorter)</div>' : r.changed ? '<div class="warnx">⚠ changed since you saved it</div>' : ""}
        <div class="sacts">
          <label class="chk"><input type="checkbox" data-act="posted" ${r.posted ? "checked" : ""}> Posted</label>
          ${r.posted ? `<button data-act="tiktok" title="Which account it went up on, and its TikTok link (for Analytics)">${r.url ? "📊 Link ✓" : "🔗 Add TikTok link"}</button>` : ""}
          <button data-act="copy" ${r.description || r.hashtags ? "" : "disabled"} title="Copy the TikTok description + hashtags">⧉ Copy desc.</button>
          ${r.link ? `<button data-act="link" title="Copy the TikTok Shop link">⧉ Link</button>` : ""}
          ${r.rendered ? `<a class="btnlink" href="/api/output/${r.sid}/${r.n}" target="_blank" title="Watch the last render${r.fresh ? "" : " (out of date)"}">▶︎ Watch</a>` : ""}
          <button data-act="download" ${r.exists ? "" : "disabled"} title="Save the video (+ .txt) to the Outbox (OneDrive)">⬇</button>
          <button data-act="open" title="Open this video in its shoot">Open</button>
          <button data-act="unsave" class="ghost" title="Remove from Saved">☆ unsave</button>
        </div>
      </div></li>`).join("")
    || `<p class="hint">${f === "done" ? "Nothing marked posted yet." : f === "todo" ? "Nothing waiting. Save videos with ☆ in a shoot to queue them here." : "No saved videos yet."}</p>`;
}
$("#savedList").addEventListener("click", async e => {
  const li = e.target.closest("li.saved"); if (!li) return;
  const sid = li.dataset.sid, n = +li.dataset.n, r = savedRows.find(x => x.sid === sid && x.n === n);
  const act = e.target.closest("[data-act]")?.dataset.act;
  if (act === "open") { await openShoot(sid); selectVideo(n); }
  if (act === "copy") copyText(`${r.description} ${r.hashtags}`.trim(), "description");
  if (act === "link") copyText(r.link, "link");
  if (act === "unsave") { await api(`/api/shoots/${sid}/saved`, { json: { n, saved: false } }); loadSaved(); }
  if (act === "download") homeDownload([[sid, n]]);
  if (act === "tiktok") postDialog(sid, n);
});
$("#savedList").addEventListener("change", async e => {
  if (e.target.dataset.act !== "posted") return;
  const li = e.target.closest("li.saved");
  await api(`/api/shoots/${li.dataset.sid}/saved`, { json: { n: +li.dataset.n, posted: e.target.checked } });
  loadSaved();
  if (e.target.checked) postDialog(li.dataset.sid, +li.dataset.n);  // which account + its TikTok link
});
$("#dlAllSaved").onclick = () => homeDownload(savedList("todo").filter(r => r.exists).map(r => [r.sid, r.n]));
$("#openPosting").onclick = async () => {
  const any = savedRows[0]?.sid || (await api("/api/shoots"))[0]?.id;
  if (any) api(`/api/shoots/${any}/open-folder?which=downloads`, { json: {} });
};
// downloads from the home page: one job per shoot (they run one after another)
async function homeDownload(pairs) {
  const by = {};
  pairs.forEach(([sid, n]) => (by[sid] = by[sid] || []).push(n));
  const jobs = [];
  for (const [sid, nums] of Object.entries(by)) {
    try { jobs.push(await api(`/api/shoots/${sid}/download`, { json: { videos: nums } })); } catch (err) { toast(err.message); }
  }
  if (!jobs.length) return;
  $("#jobBox").hidden = false;
  const poll = setInterval(async () => {
    const st = await Promise.all(jobs.map(j => api(`/api/jobs/${j.id}`).catch(() => ({ state: "error" }))));
    const live = st.find(j => j.state === "running" || j.state === "queued");
    $("#jobMsg").textContent = live ? live.msg : "";
    $("#jobBox .bar i").style.width = `${Math.round(100 * st.filter(j => j.state === "done").length / st.length)}%`;
    if (!live) {
      clearInterval(poll); $("#jobBox").hidden = true;
      const err = st.find(j => j.state === "error");
      if (err) toast("⚠ " + (err.error || "download failed"), 8000);
      else downloadedToast({ msg: `${pairs.length} video(s) saved to the Outbox` }, st[0]?.shoot || pairs[0][0]);
      loadSaved();
    }
  }, 1200);
}


// ---------- inbox: videos dropped in the cloud folder show up here pre-cut ----------
const seenShoots = () => LS.get("seenShoots", []);
function markSeen(sid) { const s = seenShoots(); if (!s.includes(sid)) { s.push(sid); LS.set("seenShoots", s.slice(-500)); } }
async function renderInbox() {
  let r;
  try { r = await api("/api/inbox"); } catch (e) { return; }
  const waiting = r.items.filter(x => x.status !== "done");
  $("#inboxBar").innerHTML = `
    <div class="ibHead"><b>📥 Inbox</b> <span class="mono ibPath" title="${esc(r.dir)}">${esc(r.dir)}</span>
      <span class="spacer"></span>
      <button data-ib="open" title="Open the inbox folder">📂 Open inbox</button>
      <button data-ib="scan" title="Look for new videos now (it also checks every 30 seconds)">↻ Check now</button>
      <button data-ib="dir" title="Use a different folder (e.g. Google Drive later)">Change…</button></div>
    ${await (async () => { try { const sh2 = await api("/api/sheet"); return sh2.path ? `<div class="ibBody muted ibSheet">📋 <b>Scripts &amp; Links</b> sheet: ${sh2.rows} upcoming shoot${sh2.rows === 1 ? "" : "s"} kept in sync${sh2.error ? ` · ⚠ ${esc(sh2.error)}` : ""}. Add a row (shoot name, link and/or script) and its shoot appears here.</div>` : ""; } catch { return ""; } })()}
    <div class="ibBody muted ${waiting.length || r.error ? "" : "idle"}">${waiting.length
      ? waiting.map(x => `⏳ ${esc(x.name)}${x.folder ? ` (${x.files} videos)` : ""}: waiting for it to finish syncing, then pre-cutting`).join("<br>")
      : r.error ? `⚠ ${esc(r.error)}`
      : `Drop raw videos in this folder from any device (OneDrive app on a phone, onedrive.com, or this PC). A video on its own becomes a shoot; a <b>subfolder</b> of videos becomes one shoot named after it. They're pre-cut here automatically${r.last_scan ? ` (last checked ${new Date(r.last_scan * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })})` : ""}.`}
      ${!r.icloud && r.dir.includes("iCloudDrive") ? `<div class="ibWarn">iCloud Drive isn't set up on this PC yet: install <b>iCloud for Windows</b> (Microsoft Store), sign in and turn on iCloud Drive. Then hit <b>Change…</b> and pick <span class="mono">${esc(r.dir.includes("iCloudDrive") ? r.dir : "C:\\Users\\…\\iCloudDrive\\Ad Factory Inbox")}</span>.</div>` : ""}</div>`;
}
$("#inboxBar").addEventListener("click", async e => {
  const act = e.target.closest("[data-ib]")?.dataset.ib; if (!act) return;
  if (act === "open") api("/api/inbox/open", { json: {} }).catch(err => toast(err.message));
  if (act === "scan") { await api("/api/inbox/scan", { json: {} }); toast("Checking the inbox…"); setTimeout(() => { renderInbox(); refreshHome(); }, 1500); }
  if (act === "dir") {
    const cur = (await api("/api/inbox")).dir;
    const p = prompt("Folder to watch for new raw videos\n(iCloud Drive is usually C:\\Users\\<you>\\iCloudDrive; Google Drive is usually G:\\My Drive):", cur);
    if (!p || p === cur) return;
    try { await api("/api/inbox/dir", { json: { path: p } }); toast("Inbox folder changed"); renderInbox(); } catch (err) { toast(err.message, 6000); }
  }
});
// keep the home page fresh: new shoots from the inbox and their progress appear on their own
async function refreshHome() {
  if (S.sid || $("#home").hidden) return;
  const grid = $("#shootGrid"), y = $("#home").scrollTop;
  const list = await api("/api/shoots").catch(() => null); if (!list) return;
  const sig = JSON.stringify(list.map(r => [r.id, r.videos, r.ready, r.sources, r.product, r.lines, r.script_guessed, r.batches]));
  if (sig !== refreshHome.sig) { refreshHome.sig = sig; await showHome(); $("#home").scrollTop = y; }
  renderInbox();
}
setInterval(refreshHome, 5000);


// ---------- soundboard: drag a sound onto a take ----------
S.sounds = S.sounds || [];
const soundOf = n => (S.sounds || []).find(x => x.name === n);
const soundEmoji = n => soundOf(n)?.emoji || "🔊";
const soundLabel = n => soundOf(n)?.label || n;
function hear(name, vol = 0.8) {
  try { const a = new Audio(`/api/sound/${name}.wav`); a.volume = clamp(vol, 0, 1); a.play().catch(() => {}); } catch (e) { /* no audio */ }
}
function renderSfxPanel() {
  const groups = [...new Set(S.sounds.map(x => x.group))];
  $("#sfxPanel").innerHTML = `<div class="sfxHead"><b>🔊 Soundboard</b>
      <span class="muted">Drag a sound onto the take in the strip below (or onto the video bar). Click a sound to hear it.</span>
      <span class="spacer"></span><button id="sfxClose" class="icon" title="Close">✕</button></div>
    ${groups.map(g => `<div class="sfxGroup"><div class="sfxG">${esc(g)}</div><div class="sfxTiles">
      ${S.sounds.filter(x => x.group === g).map(x => `<div class="sfxTile" draggable="true" data-sfx="${x.name}" title="Drag onto the strip · click to hear">
        <span class="em">${x.emoji}</span><span class="lb">${esc(x.label)}</span></div>`).join("")}</div></div>`).join("")}
    <p class="hint">All sounds are made by the app itself, so they're free to use in your videos.</p>`;
}
$("#sfxBtn").onclick = () => {
  const p = $("#sfxPanel"); p.hidden = !p.hidden; $("#sfxBtn").classList.toggle("on", !p.hidden);
  if (!p.hidden) renderSfxPanel();
};
$("#sfxPanel").addEventListener("click", e => {
  if (e.target.closest("#sfxClose")) { $("#sfxPanel").hidden = true; $("#sfxBtn").classList.remove("on"); return; }
  const tile = e.target.closest(".sfxTile"); if (tile) hear(tile.dataset.sfx);
});
$("#sfxPanel").addEventListener("dragstart", e => {
  const tile = e.target.closest(".sfxTile"); if (!tile) return;
  e.dataTransfer.setData("text/x-sfx", tile.dataset.sfx); e.dataTransfer.effectAllowed = "copy";
});
const isSfxDrag = e => [...(e.dataTransfer?.types || [])].includes("text/x-sfx");
function addSfx(t, name, at) {
  if (!t || locked(t, "get new sounds")) return;
  commit(s => { const x = s.takes.find(k => k.id === t.id); x.sfx = [...(x.sfx || []), { id: newId(), name, at: Math.round(at * 1000) / 1000, vol: 0.8 }]; x.user.sfx = true; });
  hear(name);
  renderTrim(); renderVbar();
  toast(`${soundEmoji(name)} ${soundLabel(name)} added at ${fmt(at)}. Drag it to move; click it for volume.`);
}
// drop on the trim strip: on the selected take, where you let go
$("#trim").addEventListener("dragover", e => {
  if (!isSfxDrag(e) || !TW) return;
  e.preventDefault(); e.dataTransfer.dropEffect = "copy";
  let ln = $("#trim .sfxdrop"); if (!ln) { ln = document.createElement("div"); ln.className = "sfxdrop"; $("#trim").appendChild(ln); }
  ln.style.left = (e.clientX - $("#trim").getBoundingClientRect().left) + "px";
});
$("#trim").addEventListener("dragleave", () => $("#trim .sfxdrop")?.remove());
$("#trim").addEventListener("drop", e => {
  if (!isSfxDrag(e) || !TW) return;
  e.preventDefault(); $("#trim .sfxdrop")?.remove();
  const name = e.dataTransfer.getData("text/x-sfx"), t = sel();
  const at = tOf(e.clientX - $("#trim").getBoundingClientRect().left);
  if (!t) { toast("Click a take first"); return; }
  if (at < t.in || at > t.out) { toast("Drop it inside the take (the pink part of the strip)"); return; }
  if (inCut(t, at)) { toast("That bit is cut out; drop it somewhere else"); return; }
  addSfx(t, name, at);
});
// drop on the video bar: whichever take is at that moment of the video
$("#vbar").addEventListener("dragover", e => { if (isSfxDrag(e)) { e.preventDefault(); e.dataTransfer.dropEffect = "copy"; } });
$("#vbar").addEventListener("drop", e => {
  if (!isSfxDrag(e)) return;
  e.preventDefault();
  const list = items("video"); if (!list.length) return;
  const r = $("#vbar").getBoundingClientRect(), vt = clamp((e.clientX - r.left) / r.width, 0, 1) * vTotal(list);
  const { i, at } = locate(list, vt);
  addSfx(list[i].t, e.dataTransfer.getData("text/x-sfx"), at);
});
// a sound chip: drag to move it, click for volume / hear / remove
function sfxChipGesture(e, chip, rect) {
  const t = sel(), id = chip.dataset.sx, c0 = (t?.sfx || []).find(x => x.id === id); if (!c0) return;
  const x0 = e.clientX, at0 = c0.at, grab = tOf(x0 - rect.left); let moved = false;
  const mv = ev => {
    if (Math.abs(ev.clientX - x0) < 3) return;
    if (!moved && locked(t, "change its sounds")) { up(); return; }
    moved = true;
    const at = clamp(at0 + tOf(ev.clientX - rect.left) - grab, t.in, t.out - 0.02);
    commit(s => { const k = s.takes.find(k => k.id === t.id).sfx.find(x => x.id === id); k.at = Math.round(at * 1000) / 1000; }, { board: false, key: "sfxmove" + id });
    chip.style.left = xOf(at - soundHit(c0.name)) + "px";
  };
  const up = () => {
    window.removeEventListener("mousemove", mv); window.removeEventListener("mouseup", up);
    S.lastKey = null;
    if (moved) { renderTrim(); renderVbar(); } else openSfxPop(t, id, chip);
  };
  window.addEventListener("mousemove", mv); window.addEventListener("mouseup", up);
}
function openSfxPop(t, id, chip) {
  const c = t.sfx.find(x => x.id === id), pop = $("#sfxPop"), r = chip.getBoundingClientRect();
  pop.innerHTML = `<b>${soundEmoji(c.name)} ${esc(soundLabel(c.name))}</b> <span class="muted">at ${fmt(c.at)}</span>
    <div class="row"><label class="lbl">Volume</label><input type="range" id="sfxVol" min="0" max="1.5" step="0.05" value="${c.vol}"><span class="val">${Math.round(c.vol * 100)}%</span></div>
    <div class="row"><button id="sfxHear">▶︎ Hear</button><span class="spacer"></span><button id="sfxDel" class="dangerish">🗑 Remove</button><button id="sfxDone">Done</button></div>`;
  pop.hidden = false;
  pop.style.left = Math.max(8, Math.min(window.innerWidth - 270, r.left - 120)) + "px";
  pop.style.top = (r.top - pop.offsetHeight - 10) + "px";
  pop.dataset.t = t.id; pop.dataset.c = id;
}
$("#sfxPop").addEventListener("input", e => {
  if (e.target.id !== "sfxVol") return;
  const pop = $("#sfxPop"), t = takeById(pop.dataset.t), v = +e.target.value;
  if (locked(t, "change its sounds")) return;
  e.target.nextElementSibling.textContent = Math.round(v * 100) + "%";
  commit(s => { s.takes.find(k => k.id === t.id).sfx.find(x => x.id === pop.dataset.c).vol = v; }, { board: false, key: "sfxvol" + pop.dataset.c });
});
$("#sfxPop").addEventListener("click", e => {
  const pop = $("#sfxPop"), t = takeById(pop.dataset.t), c = t?.sfx?.find(x => x.id === pop.dataset.c);
  if (e.target.id === "sfxHear" && c) hear(c.name, c.vol);
  if (e.target.id === "sfxDel" && c) {
    if (locked(t, "change its sounds")) return;
    commit(s => { const k = s.takes.find(k => k.id === t.id); k.sfx = k.sfx.filter(x => x.id !== c.id); });
    pop.hidden = true; renderTrim(); renderVbar(); toast("Sound removed");
  }
  if (e.target.id === "sfxDone") pop.hidden = true;
});
document.addEventListener("mousedown", e => { if (!e.target.closest("#sfxPop, .sfxchip")) $("#sfxPop").hidden = true; });
// sound events in video time for a list of takes (mirrors adcut/sounds.py events)
function sfxEvents(list) {
  const out = [];
  for (const it of list) for (const c of it.t.sfx || []) {
    if (c.at < it.t.in || c.at >= it.t.out || inCut(it.t, c.at)) continue;
    const hit = soundOf(c.name)?.hit || 0;
    out.push({ vt: it.off + takeRel(it.t, c.at) - hit, hit, name: c.name, vol: c.vol ?? 0.8 });
  }
  return out;
}
// preview: fire each sound as the playhead passes its start
function sfxCrossings() {
  const vt = curVt();
  if (P.lastVt == null || vt < P.lastVt - 0.05 || vt - P.lastVt > 1) { P.lastVt = vt - 0.001; }
  for (const ev of sfxEvents(P.list)) if (Math.max(ev.vt, 0) > P.lastVt && Math.max(ev.vt, 0) <= vt) hear(ev.name, ev.vol);
  P.lastVt = vt;
}


// ---------- effects board: TikTok Shop pointers, flash, caption styles ----------
S.fxKinds = S.fxKinds || [];
const fxOf = k => (S.fxKinds || []).find(x => x.kind === k);
const fxEmoji = k => fxOf(k)?.emoji || "✨";
const fxLabel = k => fxOf(k)?.label || k;
function hexA(hex, a) { const h = hex.replace("#", ""); return `rgba(${parseInt(h.slice(0, 2), 16)},${parseInt(h.slice(2, 4), 16)},${parseInt(h.slice(4, 6), 16)},${a})`; }
const SUB_PRESETS = [
  { id: "classic", label: "Classic", s: { on: true, font: "Arial Black", size: 84, color: "#FFFFFF", highlight: "#FFE14D", outline: "#000000", outline_w: 6, shadow: 0, box: null, uppercase: false, words_per_line: 3, karaoke: true, pop: true, bold: true } },
  { id: "bold_yellow", label: "Bold yellow", s: { on: true, font: "Impact", size: 100, color: "#FFE14D", highlight: "#FFFFFF", outline: "#000000", outline_w: 7, shadow: 0, box: null, uppercase: true, words_per_line: 2, karaoke: true, pop: true, bold: true } },
  { id: "tiktok_red", label: "TikTok red", s: { on: true, font: "Arial Black", size: 84, color: "#FFFFFF", highlight: "#FE2C55", outline: "#000000", outline_w: 5, shadow: 0, box: null, uppercase: false, words_per_line: 3, karaoke: true, pop: true, bold: true } },
  { id: "boxed", label: "Black box", s: { on: true, font: "Arial Black", size: 72, color: "#FFFFFF", highlight: "#FFE14D", outline: "#000000", outline_w: 0, shadow: 0, box: "#000000", box_alpha: 0.6, box_pad: 16, uppercase: false, words_per_line: 3, karaoke: true, pop: false, bold: true } },
  { id: "white_box", label: "White box", s: { on: true, font: "Arial Black", size: 70, color: "#111111", highlight: "#FE2C55", outline: "#000000", outline_w: 0, shadow: 0, box: "#FFFFFF", box_alpha: 0.95, box_pad: 16, uppercase: false, words_per_line: 3, karaoke: true, pop: false, bold: true } },
  { id: "clean", label: "Clean", s: { on: true, font: "Segoe UI Semibold", size: 74, color: "#FFFFFF", highlight: "#25F4EE", outline: "#000000", outline_w: 0, shadow: 3, box: null, uppercase: false, words_per_line: 4, karaoke: true, pop: false, bold: false } },
  { id: "one_word", label: "One word", s: { on: true, font: "Impact", size: 132, color: "#FFFFFF", highlight: "#FFE14D", outline: "#000000", outline_w: 8, shadow: 0, box: null, uppercase: true, words_per_line: 1, karaoke: true, pop: true, bold: true } },
  { id: "neon", label: "Neon", s: { on: true, font: "Segoe UI Black", size: 84, color: "#FFFFFF", highlight: "#25F4EE", outline: "#FF2BD6", outline_w: 4, shadow: 0, box: null, uppercase: true, words_per_line: 3, karaoke: true, pop: true, bold: true } },
  { id: "off", label: "No captions", s: { on: false } },
];
let fxHover = null;  // the effect being previewed on the stage (hovered tile)
function subTile(p) {
  const s = { ...sh().style.subs, ...p.s };
  if (s.on === false) return `<div class="subTile" data-sub="${p.id}"><div class="subSample off">no captions</div><span class="lb">${p.label}</span></div>`;
  const stroke = !s.box && s.outline_w ? `-webkit-text-stroke:${Math.max(1, s.outline_w / 3)}px ${s.outline};paint-order:stroke fill;` : "";
  const shadow = !s.box && s.shadow ? `text-shadow:0 2px 3px rgba(0,0,0,.8);` : "";
  const box = s.box ? `background:${hexA(s.box, s.box_alpha ?? 0.6)};padding:1px 5px;border-radius:4px;` : "";
  const words = ["Like", "a", "pie"].map(w => s.uppercase ? w.toUpperCase() : w);
  return `<div class="subTile" data-sub="${p.id}" title="Hover to preview on the video; click to use">
    <div class="subSample"><span style="font:${s.bold === false ? 600 : 900} ${Math.round(s.size / 4.2)}px '${s.font}';color:${s.color};${stroke}${shadow}${box}">${words[0]} <span style="color:${s.highlight}">${words[1]}</span> ${words[2]}</span></div>
    <span class="lb">${p.label}</span></div>`;
}
function renderFxPanel() {
  if (!sh()) return;
  const groups = [...new Set(S.fxKinds.map(x => x.group))];
  const cp = sh().style.cart_pointer || {}, cur = cp.on === false ? "off" : (cp.kind || "arrow");
  const line = lines().find(l => l.id === sel()?.line);
  $("#fxPanel").innerHTML = `<div class="sfxHead"><b>✨ Effects</b>
      <span class="muted">Hover anything to preview it on the video. Drag an effect onto the strip below (or the video bar) to place it.</span>
      <span class="spacer"></span><button id="fxClose" class="icon" title="Close">✕</button></div>
    ${groups.map(g => `<div class="sfxGroup"><div class="sfxG">${esc(g)}</div><div class="sfxTiles">
      ${S.fxKinds.filter(x => x.group === g).map(x => `<div class="sfxTile fxTile" draggable="true" data-fxk="${x.kind}" title="Hover to preview · drag onto the strip">
        <span class="em">${x.emoji}</span><span class="lb">${esc(x.label)}</span></div>`).join("")}</div></div>`).join("")}
    <div class="sfxGroup"><div class="sfxG">When he says "orange cart" (automatic)</div><div class="sfxTiles">
      ${S.fxKinds.filter(x => x.group.startsWith("Point")).map(x => `<div class="sfxTile autoTile ${cur === x.kind ? "on" : ""}" data-auto="${x.kind}" title="Hover to preview · click to use this for the automatic pointer"><span class="em">${x.emoji}</span><span class="lb">${esc(x.label)}</span></div>`).join("")}
      <div class="sfxTile autoTile ${cur === "off" ? "on" : ""}" data-auto="off" title="No automatic pointer"><span class="em">🚫</span><span class="lb">Off</span></div></div>
      <p class="hint">Triggered by: <b>${esc(cp.words || "")}</b> (change the words in ⑥ Text on the video)</p></div>
    <div class="sfxGroup"><div class="sfxG">Caption style</div><div class="subTiles">${SUB_PRESETS.map(subTile).join("")}</div>
      <div class="row" style="margin-top:6px">${line ? `<label class="chk"><input type="checkbox" id="subsOffLine" ${line.subs_off ? "checked" : ""}> Hide captions on line ${lineIdx(line.id) + 1} <span class="muted">(${esc(line.text.slice(0, 40))})</span></label>` : `<span class="muted">Select a take to hide captions on its line.</span>`}</div></div>`;
}
$("#fxBtn").onclick = () => {
  const p = $("#fxPanel"); p.hidden = !p.hidden; $("#fxBtn").classList.toggle("on", !p.hidden);
  if (!p.hidden) { $("#sfxPanel").hidden = true; $("#sfxBtn").classList.remove("on"); renderFxPanel(); }
};
$("#sfxBtn").addEventListener("click", () => { $("#fxPanel").hidden = true; $("#fxBtn").classList.remove("on"); });
// hover = live preview on the stage
$("#fxPanel").addEventListener("mouseover", e => {
  const ft = e.target.closest("[data-fxk], [data-auto]"), st = e.target.closest("[data-sub]");
  const k = ft ? (ft.dataset.fxk || ft.dataset.auto) : null;
  if (k && k !== "off") { if (fxHover !== k) { fxHover = k; fxHoverStart = performance.now(); refreshPreview(); } }
  else if (fxHover) { fxHover = null; refreshPreview(); }
  const p = st && SUB_PRESETS.find(x => x.id === st.dataset.sub);
  if (p) { if (S.subPreview !== p.s) { S.subPreview = p.s; refreshPreview(); } }
  else if (S.subPreview) { S.subPreview = null; refreshPreview(); }
});
$("#fxPanel").addEventListener("mouseleave", () => { fxHover = null; S.subPreview = null; refreshPreview(); });
let fxHoverStart = 0;
function refreshPreview() { const it = P.list[P.i]; if (it) drawOverlay(it, P.list); }
setInterval(() => { if (fxHover && !P.on) refreshPreview(); }, 120);  // keep the hovered effect animating
$("#fxPanel").addEventListener("click", e => {
  if (e.target.closest("#fxClose")) { $("#fxPanel").hidden = true; $("#fxBtn").classList.remove("on"); fxHover = null; S.subPreview = null; refreshPreview(); return; }
  const a = e.target.closest("[data-auto]");
  if (a) {
    const k = a.dataset.auto;
    commit(s => { s.style.cart_pointer = { ...s.style.cart_pointer, on: k !== "off", ...(k !== "off" ? { kind: k } : {}) }; }, { board: false });
    renderFxPanel(); toast(k === "off" ? "No automatic pointer" : `“Orange cart” now shows: ${fxLabel(k)}`);
  }
  const st = e.target.closest("[data-sub]");
  if (st) {
    const p = SUB_PRESETS.find(x => x.id === st.dataset.sub);
    commit(s => { s.style.subs = { ...s.style.subs, ...p.s }; }, { board: false });
    S.subPreview = null; renderFxPanel(); renderTextPanel(); refreshPreview(); toast(`Captions: ${p.label}`);
  }
});
$("#fxPanel").addEventListener("change", e => {
  if (e.target.id !== "subsOffLine") return;
  const lid = sel()?.line; if (!lid) return;
  commit(s => { s.script.find(l => l.id === lid).subs_off = e.target.checked; }, { left: true });
  refreshPreview();
});
$("#fxPanel").addEventListener("dragstart", e => {
  const tile = e.target.closest("[data-fxk]"); if (!tile) return;
  e.dataTransfer.setData("text/x-fx", tile.dataset.fxk); e.dataTransfer.effectAllowed = "copy";
});
const isFxDrag = e => [...(e.dataTransfer?.types || [])].includes("text/x-fx");
function addFx(t, kind, at) {
  if (!t || locked(t, "get new effects")) return;
  const d = fxOf(kind)?.dur || 2;
  commit(s => { const x = s.takes.find(k => k.id === t.id); x.fx = [...(x.fx || []), { id: newId(), kind, at: Math.round(at * 1000) / 1000, dur: d }]; x.user.fx = true; });
  renderTrim(); renderVbar(); refreshPreview();
  toast(`${fxEmoji(kind)} ${fxLabel(kind)} added at ${fmt(at)}. Drag it to move; click it to change its length.`);
}
$("#trim").addEventListener("dragover", e => { if (isFxDrag(e) && TW) { e.preventDefault(); e.dataTransfer.dropEffect = "copy"; } });
$("#trim").addEventListener("drop", e => {
  if (!isFxDrag(e) || !TW) return;
  e.preventDefault();
  const t = sel(), at = tOf(e.clientX - $("#trim").getBoundingClientRect().left);
  if (!t) { toast("Click a take first"); return; }
  if (at < t.in || at > t.out) { toast("Drop it inside the take (the pink part of the strip)"); return; }
  addFx(t, e.dataTransfer.getData("text/x-fx"), at);
});
$("#vbar").addEventListener("dragover", e => { if (isFxDrag(e)) { e.preventDefault(); e.dataTransfer.dropEffect = "copy"; } });
$("#vbar").addEventListener("drop", e => {
  if (!isFxDrag(e)) return;
  e.preventDefault();
  const list = items("video"); if (!list.length) return;
  const r = $("#vbar").getBoundingClientRect(), vt = clamp((e.clientX - r.left) / r.width, 0, 1) * vTotal(list);
  const { i, at } = locate(list, vt);
  addFx(list[i].t, e.dataTransfer.getData("text/x-fx"), at);
});
function fxChipGesture(e, chip, rect) {
  const t = sel(), id = chip.dataset.fx, c0 = (t?.fx || []).find(x => x.id === id); if (!c0) return;
  const x0 = e.clientX; let moved = false;
  const mv = ev => {
    if (Math.abs(ev.clientX - x0) < 3) return;
    if (!moved && locked(t, "change its effects")) { up(); return; }
    moved = true;
    const at = clamp(tOf(ev.clientX - rect.left), t.in, t.out - 0.05);
    commit(s => { s.takes.find(k => k.id === t.id).fx.find(x => x.id === id).at = Math.round(at * 1000) / 1000; }, { board: false, key: "fxmove" + id });
    chip.style.left = xOf(at) + "px";
  };
  const up = () => {
    window.removeEventListener("mousemove", mv); window.removeEventListener("mouseup", up);
    S.lastKey = null;
    if (moved) { renderTrim(); renderVbar(); } else openFxPop(t, id, chip);
  };
  window.addEventListener("mousemove", mv); window.addEventListener("mouseup", up);
}
function openFxPop(t, id, chip) {
  const c = t.fx.find(x => x.id === id), pop = $("#sfxPop"), r = chip.getBoundingClientRect();
  pop.innerHTML = `<b>${fxEmoji(c.kind)} ${esc(fxLabel(c.kind))}</b> <span class="muted">at ${fmt(c.at)}</span>
    <div class="row"><label class="lbl">Length</label><input type="range" id="fxDur" min="0.3" max="5" step="0.1" value="${c.dur}"><span class="val">${(+c.dur).toFixed(1)}s</span></div>
    <div class="row"><span class="spacer"></span><button id="fxDel" class="dangerish">🗑 Remove</button><button id="sfxDone">Done</button></div>`;
  pop.hidden = false;
  pop.style.left = Math.max(8, Math.min(window.innerWidth - 270, r.left - 60)) + "px";
  pop.style.top = (r.top - pop.offsetHeight - 10) + "px";
  pop.dataset.t = t.id; pop.dataset.fx = id; pop.dataset.c = "";
}
$("#sfxPop").addEventListener("input", e => {
  if (e.target.id !== "fxDur") return;
  const pop = $("#sfxPop"), t = takeById(pop.dataset.t), v = +e.target.value;
  if (locked(t, "change its effects")) return;
  e.target.nextElementSibling.textContent = v.toFixed(1) + "s";
  commit(s => { s.takes.find(k => k.id === t.id).fx.find(x => x.id === pop.dataset.fx).dur = v; }, { board: false, key: "fxdur" + pop.dataset.fx });
  renderTrim();
});
$("#sfxPop").addEventListener("click", e => {
  if (e.target.id !== "fxDel") return;
  const pop = $("#sfxPop"), t = takeById(pop.dataset.t);
  if (locked(t, "change its effects")) return;
  commit(s => { const k = s.takes.find(k => k.id === t.id); k.fx = k.fx.filter(x => x.id !== pop.dataset.fx); });
  pop.hidden = true; renderTrim(); renderVbar(); refreshPreview(); toast("Effect removed");
});
document.addEventListener("mousedown", e => { if (!e.target.closest("#sfxPop, .fxchip, .sfxchip")) $("#sfxPop").hidden = true; });

// which effects are on screen at video time vt (mirrors adcut/fx.py events)
function fxActive(it, list, vt, total) {
  const on = [];
  for (const x of P.mode === "take" && P.on ? [it] : list) for (const e of x.t.fx || []) {
    if (e.at < x.t.in || e.at >= x.t.out || inCut(x.t, e.at)) continue;
    const a = x.off + takeRel(x.t, e.at), b = Math.min(total, a + (+e.dur || 2));
    if (vt >= a && vt < b) on.push({ kind: e.kind, since: vt - a });
  }
  const cp = sh().style.cart_pointer || {};
  for (const [a, b] of cartTimes(P.mode === "take" && P.on ? [it] : list, total))
    if (vt >= a && vt < b) on.push({ kind: cp.kind || "arrow", since: vt - a });
  if (fxHover) on.push({ kind: fxHover, since: ((performance.now() - fxHoverStart) / 1000) % 2.2 });
  return on;
}
const TAGBOX = () => { const b = CART_TAG; return { l: b[0] * W - 14, t: b[1] * H - 12, w: (b[2] - b[0]) * W + 28, h: (b[3] - b[1]) * H + 24 }; };
function drawFx(it, list, vt, total) {
  const layer = $("#fxLayer"), on = fxActive(it, list, vt, total), seen = new Set();
  const g = TAGBOX(), col = sh().style.cart_pointer?.color || "#FF8A00";
  for (const a of on) {
    seen.add(a.kind);
    let el = layer.querySelector(`[data-k="${a.kind}"]`);
    if (!el) {
      el = document.createElement("div"); el.dataset.k = a.kind; el.className = `fx fx-${a.kind}`;
      el.innerHTML = {
        arrow: `<i class="ring"></i><i class="arrowShape"></i>`, ring: `<i class="ring"></i>`,
        tap: `<i class="ring thin"></i><i class="finger">👇</i><i class="ripple"></i>`, spotlight: `<i class="hole"></i>`,
        shine: `<i class="frame"><i class="band"></i></i>`,
        scribble: `<svg viewBox="0 0 100 100" preserveAspectRatio="none"><path d="M10,52 C10,8 90,4 92,48 C94,92 14,96 8,56 C6,40 30,22 60,18" /></svg>`,
        flash: ``,
      }[a.kind] || "";
      layer.appendChild(el);
    }
    el.style.setProperty("--cp", col);
    el.style.setProperty("--l", g.l + "px"); el.style.setProperty("--t", g.t + "px"); el.style.setProperty("--w", g.w + "px"); el.style.setProperty("--h", g.h + "px");
    el.style.setProperty("--since", a.since.toFixed(2));
  }
  for (const el of [...layer.children]) if (!seen.has(el.dataset.k)) el.remove();
}

const soundDur = n => soundOf(n)?.dur || 1;
const soundHit = n => soundOf(n)?.hit || 0;

// ---------- pre-rendered previews: each video as one continuous small file ----------
// The server renders every video's footage (framing, cut-outs, volume) into one file so
// playback runs straight through instead of seeking at every take; subtitles, assets,
// effects and sounds stay live on top. Stale (footage edited since) = live playback.
S.pv = {};
let pvT = null;
async function refreshPreviews() {
  const sid = S.sid; if (!sid) return;
  clearTimeout(pvT);
  try { const r = await api(`/api/shoots/${sid}/previews`); if (sid === S.sid) S.pv = r; } catch { return; }
  if (Object.values(S.pv).some(x => x.state === "building")) pvT = setTimeout(refreshPreviews, 2500);
}
const near = (a, b) => Math.abs(a - b) < 0.002;
function pvMatch(list, info) {
  if (!info || info.state !== "ready" || info.segs.length !== list.length) return null;
  const st = sh().style;
  const ok = list.every(({ t }, k) => {
    const g = info.segs[k], c = cutsOf(t), punch = lineIdx(t.line) % 2 === 1 ? (+st.punch_in || 1) : 1;
    return g.id === t.id && g.src === t.src && near(g.in, t.in) && near(g.out, t.out) && near(g.zoom, t.zoom * punch)
      && near(g.pan_x, t.pan_x) && near(g.pan_y, t.pan_y) && near(g.volume, t.volume) && near(g.freeze || 0, +t.freeze || 0) && near(g.speed || 1, spd(t))
      && g.cuts.length === c.length && g.cuts.every(([a, b], j) => near(a, c[j][0]) && near(b, c[j][1]));
  });
  return ok ? info : null;
}
async function cuePv(i, at) {
  const pv = P.pv, it = P.list[i]; P.i = i;
  followPlayback(it.t);
  if (video.dataset.src !== pv.url) {
    video.dataset.src = pv.url; video.src = pv.url;
    await new Promise(res => video.addEventListener("loadedmetadata", res, { once: true }));
  }
  Object.assign(video.style, { width: W + "px", height: H + "px", left: "0px", top: "0px", filter: "" });
  video.volume = 1; video.playbackRate = 1;  // the preview is already sped up (and has the look baked in)
  video.currentTime = pv.segs[i].off + takeRel(it.t, at);
  await video.play().catch(() => {});
}
async function leavePv() { P.pv = null; await ensureSource(P.list[P.i].t); }
function tickPv() {
  const pv = P.pv, pt = video.currentTime, segs = pv.segs, end = segs[segs.length - 1].off + segs[segs.length - 1].len;
  if (video.ended || pt >= end - 0.02) { P.pv = null; pause(); S.vpos[S.vid] = 0; showIdle(); return; }
  let i = segs.length - 1; while (i > 0 && segs[i].off > pt + 0.001) i--;
  if (i !== P.i) { P.i = i; followPlayback(P.list[i].t); }
  const it = P.list[i], spoken = dur(it.t) - (+it.t.freeze || 0);
  P.extra = Math.max(0, pt - segs[i].off - spoken);
  drawOverlay(it, P.list, srcAt(it.t, clamp(pt - segs[i].off, 0, spoken)));
  sfxCrossings();
  requestAnimationFrame(tick);
}
// where in the source the picture is (the preview file's time mapped back while it plays)
function srcNow() {
  if (!P.pv) return video.currentTime;
  const it = P.list[P.i], g = P.pv.segs[P.i];
  return it && g ? srcAt(it.t, clamp(video.currentTime - g.off, 0, dur(it.t))) : video.currentTime;
}

// remove a line from the script and so from every video; its takes go to "Other speech"
function removeLine(id) {
  const i = lineIdx(id), l = lines()[i]; if (!l) return;
  const ts = sh().takes.filter(t => t.line === id), lk = lockedMap();
  const nLocked = ts.filter(t => lk[t.id]).length;
  const msg = `Remove line ${i + 1} (“${l.text.slice(0, 60)}”) from every video?`
    + (ts.length ? ` Its ${ts.length} take(s) move to “Other speech”.` : "")
    + (nLocked ? ` ${nLocked} of them are in saved/posted videos, which stay as they were.` : "")
    + " (Undo brings it back.)";
  if (!confirm(msg)) return;
  commit(s => {
    const prev = s.script[i - 1];
    if (prev?.cut_next && i === s.script.length - 1) prev.cut_next = false;  // nothing left to cut into
    s.script = s.script.filter(x => x.id !== id);
    s.takes.forEach(t => { if (t.line === id && !lk[t.id]) { t.line = null; t.usable = false; t.status = "unmatched"; } });
  }, { left: true });
  markScriptChanged();
}

// ---------- captions: the take's words as they show on screen, editable ----------
// Each word keeps its timing, so fixing a word ("slapped" -> "slept") keeps the karaoke
// in sync; adding or removing words spreads the new ones over the same stretch of time.
const capWords = t => (t.words || []).map((w, i) => ({ w, i })).filter(({ w }) => { const m = (w[1] + w[2]) / 2; return m >= t.in && m <= t.out && !inCut(t, m); });
const capText = t => capWords(t).map(x => x.w[0]).join(" ");
function setCaptions(t, text) {
  if (!t) return;
  const vis = capWords(t), toks = text.trim().split(/\s+/).filter(Boolean);
  commit(s => {
    const x = s.takes.find(k => k.id === t.id);
    if (!x.user.words && !x.words_orig) x.words_orig = JSON.parse(JSON.stringify(x.words));
    const keep = x.words.filter((_, i) => !vis.some(v => v.i === i));
    let nw;
    if (toks.length === vis.length) nw = vis.map((v, j) => [toks[j], v.w[1], v.w[2]]);
    else {
      const a = vis.length ? vis[0].w[1] : x.in + 0.1, b = vis.length ? vis[vis.length - 1].w[2] : x.out - 0.1;
      // spread over the spoken time (cut-outs skipped), weighted by word length
      const tot = toks.reduce((n, w) => n + w.length + 1, 0) || 1, span = takeRel(x, b) - takeRel(x, a);
      let acc = 0;
      nw = toks.map(w => { const r0 = takeRel(x, a) + span * acc / tot; acc += w.length + 1; const r1 = takeRel(x, a) + span * acc / tot;
        return [w, Math.round(srcAt(x, r0) * 1000) / 1000, Math.round(srcAt(x, Math.max(r0, r1 - 0.02)) * 1000) / 1000]; });
    }
    x.words = [...keep, ...nw].sort((p, q) => p[1] - q[1]);
    x.text = x.words.map(w => w[0]).join(" ");
    x.user.words = x.user.text = true;
  }, { key: "caps" + t.id, board: false });
}
function resetCaptions(t) {
  commit(s => {
    const x = s.takes.find(k => k.id === t.id);
    if (x.words_orig) { x.words = x.words_orig; x.text = x.words.map(w => w[0]).join(" "); }
    delete x.words_orig; delete x.user.words; delete x.user.text;
  }, { board: false });
}

// the title over a freeze frame (made on first use, sits above the subtitles)
function titleImg() {
  let img = document.getElementById("titleImg");
  if (!img) { img = document.createElement("img"); img.id = "titleImg"; img.className = $("#hookImg").className; img.hidden = true; $("#hookImg").after(img); }
  return img;
}

// ---------- speed: per clip, the whole video, and auto pace (mirrors store.speed) ----------
function spd(t) {
  if (+t.speed) return +t.speed;
  const st = sh()?.style || {}, pace = st.pace || {};
  let sp = +st.speed || 1;
  if (pace.auto) {
    const cs = cutsOf(t), spoken = t.out - t.in - cs.reduce((a, [x, y]) => a + y - x, 0);
    const n = (t.words || []).filter(w => { const m = (w[1] + w[2]) / 2; return m >= t.in && m <= t.out && !cs.some(([a, b]) => m >= a && m < b); }).length;
    if (n >= 3 && spoken > 0.3) sp *= Math.min(+pace.max || 1.1, Math.max(1, Math.round(((+pace.wps || 4.8) / (n / spoken)) * 20) / 20));
  }
  return Math.round(sp * 1000) / 1000;
}
const autoSpd = t => spd({ ...t, speed: null });

// ---------- TikTok Shop safety (word lists from adcut/safety.py) ----------
S.safety = null;
api("/api/safety").then(r => {
  S.safety = Object.entries(r).map(([cat, v]) => ({ cat, level: v.level, rx: new RegExp("\\b(" + v.patterns.join("|") + ")\\b", "gi") }));
  if (sh()) { renderBoard(); renderInspector(); }
}).catch(() => {});
function safetyOf(text) {
  if (!S.safety || !text) return [];
  return S.safety.map(r => ({ cat: r.cat, level: r.level, words: [...new Set((text.match(r.rx) || []).map(w => w.toLowerCase()))] })).filter(f => f.words.length);
}
const safetyLevel = fl => fl.some(f => f.level === "unsafe") ? "unsafe" : fl.length ? "caution" : null;
function safetyChip(fl, long = false) {
  const lv = safetyLevel(fl); if (!lv) return long ? `<span class="safe ok" title="No flagged words in the captions">✓ Shop-safe</span>` : "";
  const cats = [...new Set(fl.filter(f => f.level === lv).map(f => f.cat))].join(", ");
  const tip = fl.map(f => `${f.cat} (${f.level}): ${f.words.join(", ")}`).join("\n");
  return `<span class="safe ${lv}" title="${esc(tip)}">⚠ ${lv === "unsafe" ? "not Shop-safe" : "check"}: ${esc(cats)}</span>`;
}
const SPICE = ["clean", "🌶", "🌶🌶", "🌶🌶🌶"];

// ---------- home: drop raw videos straight into the OneDrive inbox ----------
// From the web link too: files go up in 16 MB pieces (the link caps a request at 100 MB)
// into the inbox folder named after the shoot, then the inbox pre-cuts them as usual.
const HD = { files: [] };
const isVideo = f => /^video\//.test(f.type) || /\.(mov|mp4|m4v|mkv|webm|avi)$/i.test(f.name);
function hdShow(which) { for (const k of ["Idle", "Ask", "Prog"]) $(`#homeDrop .hd${k}`).hidden = k !== which; }
async function hdChoose(files) {
  HD.files = [...files].filter(isVideo);
  if (!HD.files.length) { toast("Drop video files"); return; }
  let folders = [];
  try { folders = await api("/api/inbox/folders"); } catch { }
  $("#hdFolders").innerHTML = folders.map(f => `<option value="${esc(f)}">`).join("");
  const stem = HD.files[0].name.replace(/\.[^.]+$/, "");
  $("#hdFolder").value = HD.files.length > 1 ? "" : stem;
  hdShow("Ask"); $("#hdFolder").focus(); $("#hdFolder").select();
}
async function hdUpload(shoot = null) {
  const folder = shoot ? "" : $("#hdFolder").value.trim();
  if (!folder && !shoot) { toast("Give the shoot a name"); $("#hdFolder").focus(); return; }
  $("#homeDrop").scrollIntoView({ behavior: "smooth", block: "nearest" });
  hdShow("Prog");
  // phones: keep the screen awake and warn before leaving while it uploads
  let lock = null;
  try { lock = await navigator.wakeLock?.request("screen"); } catch { }
  const stay = e => { e.preventDefault(); e.returnValue = ""; };
  window.addEventListener("beforeunload", stay);
  const PIECE = 16 * 1024 * 1024, total = HD.files.reduce((a, f) => a + f.size, 0);
  let sent = 0;
  try {
    for (const [i, f] of HD.files.entries()) {
      let off = 0, tries = 0;
      while (off < f.size || f.size === 0) {
        const end = Math.min(f.size, off + PIECE);
        $("#hdMsg").textContent = `Uploading ${f.name} (${i + 1}/${HD.files.length}) · ${Math.round((sent + off) / total * 100)}%`;
        $("#hdFill").style.width = ((sent + off) / total * 100) + "%";
        if (!S.sid) { $("#jobBox").hidden = false; $("#jobMsg").textContent = $("#hdMsg").textContent; $("#jobBox .bar i").style.width = $("#hdFill").style.width; }
        const q = `name=${encodeURIComponent(f.name)}&folder=${encodeURIComponent(folder)}&shoot=${encodeURIComponent(shoot || "")}&offset=${off}&total=${f.size}`;
        let r;
        try { r = await fetch(`/api/inbox/upload?${q}`, { method: "PUT", body: f.slice(off, end) }); }
        catch (err) { if (++tries > 5) throw err; await new Promise(res => setTimeout(res, 2000 * tries)); continue; }
        if (r.status === 409) { off = (await r.json()).size; continue; }  // resume where the PC has it up to
        if (r.status === 401) throw new Error("signed out: reload the page and sign in");
        if (!r.ok) { if (++tries > 5) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText); await new Promise(res => setTimeout(res, 2000 * tries)); continue; }
        tries = 0; off = end;
        if (f.size === 0) break;
      }
      sent += f.size;
    }
    $("#hdFill").style.width = "100%";
    toast(shoot ? "Added to the shoot. Pre-cutting starts in a moment." : `Uploaded to the inbox (“${folder}”). Pre-cutting starts in a moment.`, 5000);
  } catch (err) { toast("Upload stopped: " + err.message + ". Drop the same file again to pick up where it left off.", 8000); }
  window.removeEventListener("beforeunload", stay);
  try { await lock?.release(); } catch { }
  hdShow("Idle"); HD.files = [];
  if (!S.sid) $("#jobBox").hidden = true;
  renderInbox(); setTimeout(refreshHome, 2500);
}
{
  const z = $("#homeDrop");
  z.addEventListener("dragover", e => { if (e.dataTransfer.types.includes("Files")) { e.preventDefault(); z.classList.add("over"); } });
  z.addEventListener("dragleave", () => z.classList.remove("over"));
  z.addEventListener("drop", e => { e.preventDefault(); z.classList.remove("over"); hdChoose(e.dataTransfer.files); });
  $("#hdPick").onclick = () => $("#hdFiles").click();
  $("#hdFiles").onchange = e => {
    const files = e.target.files; e.target.value = "";
    if (HD.shoot) { HD.files = [...files].filter(isVideo); const sid = HD.shoot; HD.shoot = null; if (HD.files.length) hdUpload(sid); return; }
    hdChoose(files);
  };
  $("#hdGo").onclick = hdUpload;
  $("#hdFolder").addEventListener("keydown", e => { if (e.key === "Enter") hdUpload(); if (e.key === "Escape") hdShow("Idle"); });
  $("#hdCancel").onclick = () => { HD.files = []; hdShow("Idle"); };
}

// phones/tablets: no drag and drop, so it's one big "upload videos" button
if (matchMedia("(pointer: coarse)").matches) {
  document.body.classList.add("touch");
  $(".hdTitle").textContent = "📲 Upload raw videos";
  $("#hdPick").textContent = "Choose videos";
  $(".hdSub").textContent = "From Photos or Files. They go into the OneDrive inbox and get pre-cut automatically.";
}

// ---------- review mode: the finished videos, to watch, download, save and post ----------
// A simple page for checking videos (phones open shoots here); ✏️ Edit is the full editor.
const RV = { sid: null, data: null, job: null };
const touchy = () => matchMedia("(pointer: coarse)").matches || innerWidth < 760;
const fmtDur = s => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}`;
function setMode(mode) {
  $("#modeSeg").hidden = false;
  $$("#modeSeg button").forEach(b => b.classList.toggle("on", b.dataset.mode === mode));
}
async function openReview(sid) {
  markSeen(sid);
  if (S.sid) { await flushSave(); pause(); S.sid = null; S.shoot = null; }
  RV.sid = sid;
  history.replaceState(null, "", "#review/" + sid);
  $("#home").hidden = true; $("#work").hidden = true; $("#bottom").hidden = true; $("#review").hidden = false;
  for (const id of ["crumbs", "histBtns", "folderBtn"]) $("#" + id).hidden = true;
  $("#backBtn").hidden = false; $("#saveState").textContent = "";
  setMode("review");
  await loadReview();
}
async function loadReview() {
  const sid = RV.sid; if (!sid) return;
  const d = await api(`/api/shoots/${sid}/review`); if (RV.sid !== sid) return;
  RV.data = d; renderReview();
  if (d.job && !RV.job) watchJob(d.job.id);
}
function rvChips(v) {
  const c = [];
  if (v.voice) c.push(`<span class="chip" title="This video's voiceover">🎙 ${esc(v.voice)}</span>`);
  if (v.posted) c.push(`<span class="chip done">✓ Posted</span>`); else if (v.saved) c.push(`<span class="chip">★ Saved</span>`);
  if (v.game) c.push(`<span class="chip">🎲 ${esc(v.game)}${v.spice != null ? " · " + (SPICE[v.spice] || v.spice) : ""}</span>`);
  if (v.safety === "unsafe") c.push(`<span class="safe unsafe">⚠ not Shop-safe: ${esc(v.safety_cats.filter(x => x !== "alcohol").join(", ") || v.safety_cats.join(", "))}</span>`);
  else if (v.safety === "caution") c.push(`<span class="safe caution">⚠ check: ${esc(v.safety_cats.join(", "))}</span>`);
  else c.push(`<span class="safe ok">✓ Shop-safe</span>`);
  if (v.odd_lines.length) c.push(`<span class="chip warn" title="He read these lines differently in this video">🎭 different read · line ${v.odd_lines.join(", ")}</span>`);
  if (v.downloaded) c.push(`<span class="chip">⬇ in Outbox</span>`);
  return c.join("");
}
function renderReview() {
  const d = RV.data; if (!d) return;
  $("#rvTitle").textContent = d.title;
  $("#rvMeta").innerHTML = `${d.videos.length} video${d.videos.length === 1 ? "" : "s"}${d.product ? ` · 🛒 ${esc(d.product)}` : ""}${d.link ? ` · <a href="${esc(d.link)}" target="_blank" rel="noopener">product link</a>` : ""}`;
  const stale = d.videos.filter(v => !v.fresh);
  $("#rvMakeAll").hidden = !stale.length || !!RV.job;
  $("#rvMakeAll").textContent = `▶ Get ${stale.length === d.videos.length ? "all" : stale.length} video${stale.length === 1 ? "" : "s"} ready`;
  $("#rvCopyCap").hidden = !d.caption;
  $("#rvGrid").innerHTML = d.videos.map(v => {
    const src = `/api/output/${d.id}/${v.n}?v=${v.sig}`;
    const player = v.rendered
      ? `<video class="rvVid" src="${src}" poster="${v.thumb || ""}" controls playsinline preload="none"></video>`
      : `<div class="rvVid empty" style="${v.thumb ? `background-image:url('${v.thumb}')` : ""}"><span>Not made yet</span></div>`;
    return `<div class="rvCard ${v.posted ? "posted" : ""}" data-n="${v.n}">
      <div class="rvTop"><b>Video ${v.n}</b> <span class="muted">${fmtDur(v.duration)}</span></div>
      ${player}
      ${v.rendered && !v.fresh ? `<div class="rvStale">Changed since this was made · <button data-rv="make">Remake</button></div>` : ""}
      <div class="rvChips">${rvChips(v)}</div>
      <div class="rvBtns">
        ${v.rendered && v.fresh
          ? `<a class="btn primary" href="/api/output/${d.id}/${v.n}?dl=1&v=${v.sig}" download>⬇ Download</a>
             ${navigator.canShare ? `<button data-rv="share" title="Save to Photos / share">📲 Save to Photos</button>` : ""}`
          : `<button class="primary" data-rv="make">▶ Make video</button>`}
        <button data-rv="outbox" title="Save it to the OneDrive Outbox with the caption text">📂 To Outbox</button>
        <button data-rv="save" class="${v.saved ? "on" : ""}" title="${v.locked ? "Saved: its clips are locked to this video" : "Save to the posting queue (locks its clips)"}">${v.saved ? "★ Saved" : "☆ Save"}</button>
        <button data-rv="posted" class="${v.posted ? "on" : ""}">${v.posted ? "✓ Posted" : "Mark posted"}</button>
      </div>
    </div>`;
  }).join("") || `<div class="empty">No videos yet${d.job ? " (pre-cutting…)" : ""}.</div>`;
}
async function watchJob(jid) {
  RV.job = jid; renderReview();
  for (;;) {
    let j;
    try { j = await api(`/api/jobs/${jid}`); } catch { break; }
    $("#rvJob").textContent = j.state === "running" || j.state === "queued" ? `⏳ ${j.msg}` : j.state === "error" ? `⚠ ${j.error}` : j.msg || "";
    if (j.state !== "running" && j.state !== "queued") break;
    await new Promise(r => setTimeout(r, 1500));
  }
  RV.job = null; await loadReview();
}
async function rvMake(nums) {
  try { const j = await api(`/api/shoots/${RV.sid}/render`, { json: { videos: nums } }); watchJob(j.id); }
  catch (e) { toast(e.status === 409 ? "Already working on this shoot. Try again in a moment." : e.message, 4000); }
}
$("#rvMakeAll").onclick = () => rvMake(RV.data.videos.filter(v => !v.fresh).map(v => v.n));
$("#rvCopyCap").onclick = async () => { try { await navigator.clipboard.writeText(RV.data.caption); toast("Caption copied"); } catch { prompt("Copy the caption:", RV.data.caption); } };
$("#rvGrid").addEventListener("click", async e => {
  const b = e.target.closest("[data-rv]"); if (!b) return;
  const n = +b.closest(".rvCard").dataset.n, v = RV.data.videos.find(x => x.n === n), act = b.dataset.rv;
  if (act === "make") return rvMake([n]);
  if (act === "outbox") {
    try { const j = await api(`/api/shoots/${RV.sid}/download`, { json: { videos: [n] } }); toast("Saving to the OneDrive Outbox…"); watchJob(j.id); }
    catch (err) { toast(err.status === 409 ? "Already working on this shoot. Try again in a moment." : err.message, 4000); }
    return;
  }
  if (act === "share") {
    b.disabled = true; b.textContent = "Preparing…";
    try {
      const blob = await (await fetch(`/api/output/${RV.sid}/${n}?v=${v.sig}`)).blob();
      const file = new File([blob], `${RV.data.title} - video ${String(n).padStart(2, "0")}.mp4`, { type: "video/mp4" });
      if (navigator.canShare({ files: [file] })) await navigator.share({ files: [file] });
      else toast("This browser can't share files: use ⬇ Download");
    } catch (err) { if (err.name !== "AbortError") toast(err.message); }
    renderReview(); return;
  }
  if (act === "save") {
    if (v.saved && !confirm(`Unsave video ${n}? Its clips get unlocked and can move to other videos.`)) return;
    await api(`/api/shoots/${RV.sid}/saved`, { json: { n, saved: !v.saved } }); return loadReview();
  }
  if (act === "posted") { await api(`/api/shoots/${RV.sid}/saved`, { json: { n, posted: !v.posted } }); if (!v.posted) postDialog(RV.sid, n); return loadReview(); }
});
$("#modeSeg").addEventListener("click", async e => {
  const m = e.target.closest("[data-mode]")?.dataset.mode; if (!m) return;
  const sid = S.sid || RV.sid; if (!sid) return;
  LS.set("openMode", m);
  if (m === "review") openReview(sid);
  else {
    if (touchy() && !confirm("The editor is made for a computer. Open it anyway?")) { setMode("review"); return; }
    $("#review").hidden = true; RV.sid = null; openShoot(sid);
  }
});
const defaultMode = () => LS.get("openMode", touchy() ? "review" : "edit");

// ---------- old + new footage: keep apart or mix ----------
function renderMixBar() {
  let el = document.getElementById("mixBar");
  const s = sh(), nb = new Set((s?.sources || []).map(x => +x.batch || 1)).size;
  const montage = s && !s.takes.some(t => t.usable && t.line && !t.user?.manual);  // hand-built: batches don't apply
  if (!s || nb < 2 || montage) { if (el) el.hidden = true; return; }
  if (!el || !$("#grid").contains(el)) { el?.remove(); el = document.createElement("div"); el.id = "mixBar"; $("#grid").prepend(el); }
  el.hidden = false;
  const lk = Object.keys(lockedMap()).length;
  el.innerHTML = `<span>📹 This shoot has footage added later.</span>
    <select id="mixSel" title="How new footage is used">
      <option value="auto" ${s.mix == null ? "selected" : ""}>Auto: ${s.mix_auto === false ? "kept separate" : "mixed together"}</option>
      <option value="sep" ${s.mix === false ? "selected" : ""}>Keep separate (earlier videos stay as they are)</option>
      <option value="mix" ${s.mix === true ? "selected" : ""}>Mix old & new (re-cut everything${lk ? ", saved clips stay locked" : ""})</option>
    </select>${s.batch_note ? `<span class="muted">${esc(s.batch_note)}</span>` : ""}`;
}
document.addEventListener("change", e => {
  if (e.target.id !== "mixSel") return;
  const v = e.target.value;
  commit(s => { s.mix = v === "auto" ? null : v === "mix"; });
  renderMixBar();
  toast(v === "mix" ? "Mixing old and new footage: the videos are re-cut together" : v === "sep" ? "Each batch of footage makes its own videos" : "Back to automatic");
});
{ const _rb = renderBoard; renderBoard = function () { _rb(); renderMixBar(); }; }

// ---------- the script, from the shoots page ----------
async function openScriptBox(sid) {
  const r = await api(`/api/shoots/${sid}/script`);
  let dlg = document.getElementById("scriptDlg");
  if (!dlg) {
    dlg = document.createElement("dialog"); dlg.id = "scriptDlg";
    dlg.innerHTML = `<form method="dialog"><h3>📝 Script</h3>
      <p class="muted" id="sdHint"></p>
      <textarea id="sdText" rows="14" placeholder="One line per line of the script, e.g.&#10;Stop spending designer prices…&#10;Because Old Navy just dropped…"></textarea>
      <div class="sdBtns"><button value="cancel">Cancel</button><button id="sdSave" value="save" class="primary">Save script</button></div></form>`;
    document.body.appendChild(dlg);
  }
  $("#sdText").value = r.lines.join("\n");
  $("#sdHint").textContent = r.guessed ? "This was figured out from the footage. Fix it or paste the real script; the takes get re-matched when you save."
    : r.lines.length ? "One line per line. Saving re-matches the takes." : "Paste the script, one line per line. Not word-perfect is fine: a take counts if the whole line gets said.";
  dlg.onclose = async () => {
    if (dlg.returnValue !== "save") return;
    try { const x = await api(`/api/shoots/${sid}/script`, { json: { text: $("#sdText").value } }); toast(`Script saved (${x.lines} lines)${r.ready ? ": re-matching the takes" : ""}`); }
    catch (e) { toast(e.message); }
    setTimeout(refreshHome, 800);
  };
  dlg.showModal(); $("#sdText").focus();
}

// ---------- the title dance (mirrors adcut/titlefx.py) ----------
const TD = { BEAT: 60 / 168 / 2, SPOTS: [[400, 430, -10], [680, 700, 9], [420, 1000, -7], [660, 1180, 10], [430, 820, -9], [650, 520, 7], [460, 1100, -5], [620, 760, 6]],
  SLAM: [1.55, 1.3, 1.08, 0.94, 0.98, 1.02, 1.0] };
function titleDance(e, landY) {
  const ease = u => 1 - (1 - clamp(u, 0, 1)) ** 3, land = TD.BEAT * 8, home = [W / 2, landY, 0];
  if (e < land) {
    const k = Math.floor(e / TD.BEAT), prev = k ? TD.SPOTS[k - 1] : home, cur = TD.SPOTS[k], u = ease((e - k * TD.BEAT) / 0.07);
    let pop = 1.14 - 0.14 * ease((e - k * TD.BEAT) / 0.1);
    if (k === 0) pop *= 0.55 + 0.45 * ease(e / 0.1);
    return [0, 1, 2].map(j => prev[j] + (cur[j] - prev[j]) * u).concat(pop);
  }
  const f = Math.floor((e - land) * 30), u = ease((e - land) / 0.06), last = TD.SPOTS[TD.SPOTS.length - 1];
  return [0, 1, 2].map(j => last[j] + (home[j] - last[j]) * u).concat(f < TD.SLAM.length ? TD.SLAM[f] : 1);
}

// ---------- review: zoom the cards (pinch, Ctrl+scroll / trackpad pinch, or − / +) ----------
const RVZ = { min: 96, max: 560 };
function rvSize(w, save = true) {
  w = clamp(Math.round(w), RVZ.min, RVZ.max);
  RV.w = w;
  $("#rvGrid").style.setProperty("--rvw", w + "px");
  $("#rvGrid").classList.toggle("tiny", w < 170);
  if (save) LS.set("rvW", w);
}
rvSize(+LS.get("rvW", touchy() ? 330 : 270), false);
$("#rvSmaller").onclick = () => rvSize(RV.w / 1.25);
$("#rvBigger").onclick = () => rvSize(RV.w * 1.25);
$("#review").addEventListener("wheel", e => {  // trackpad pinch arrives as Ctrl+wheel
  if (!e.ctrlKey) return;
  e.preventDefault();
  rvSize(RV.w * Math.exp(-e.deltaY * 0.003));
}, { passive: false });
{
  let p0 = null;
  const dist = t => Math.hypot(t[0].clientX - t[1].clientX, t[0].clientY - t[1].clientY);
  const g = $("#rvGrid");
  g.addEventListener("touchstart", e => { if (e.touches.length === 2) p0 = { d: dist(e.touches), w: RV.w }; }, { passive: true });
  g.addEventListener("touchmove", e => {
    if (e.touches.length !== 2 || !p0) return;
    e.preventDefault();  // our pinch resizes the cards instead of zooming the page
    rvSize(p0.w * dist(e.touches) / p0.d);
  }, { passive: false });
  g.addEventListener("touchend", e => { if (e.touches.length < 2) p0 = null; });
}
