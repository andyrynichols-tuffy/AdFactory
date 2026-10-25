/* Script builder (adcut/scriptgen.py): a TikTok link -> its script + shot list, with the
   product-specific bits marked so the script works for any product. ✨ AI buttons (find the
   details, describe the shots, fill the blanks, rewrite) only run when pressed. */
"use strict";
const SB = { s: null, prods: [], dlg: null, saveT: null, ai: null };
const SLOT_COLORS = ["#ffa94d", "#74c0fc", "#b197fc", "#63e6be", "#ff8787", "#ffd43b", "#f783ac", "#a9e34b"];
const slotColor = slot => SLOT_COLORS[[...String(slot)].reduce((a, c) => (a * 31 + c.charCodeAt(0)) >>> 0, 7) % SLOT_COLORS.length];
const sleep = ms => new Promise(r => setTimeout(r, ms));

async function sbJob(job, onMsg) {
  while (job.state === "running") {
    onMsg?.(job.msg);
    await sleep(1200);
    job = await api(`/api/shop/scriptgen/jobs/${job.id}`);
  }
  if (job.state === "error") throw new Error(job.error);
  return job.result;
}
async function aiReady() {
  if (SB.ai === null) SB.ai = (await api("/api/shop/ai/status").catch(() => ({ available: false }))).available;
  return SB.ai;
}

// ---------- Library → 🔗 From a TikTok link ----------
async function scriptFromLink() {
  const dlg = document.createElement("dialog"); dlg.className = "shopDlg";
  dlg.innerHTML = `<form><h3>🔗 Script from a TikTok</h3>
    <p class="muted">Paste a TikTok Shop video's link. The app downloads it, writes down what's said (on this PC), splits it into shots where the picture cuts, and marks the bits that are about that product, so the script works for other products too.</p>
    <label class="fld">TikTok link<input name="url" type="url" required placeholder="https://www.tiktok.com/@…/video/…"></label>
    <label class="fld">Name <span class="fhint">optional</span><input name="title" placeholder="e.g. Old Navy thermals · sale hook"></label>
    <div class="sbProg" hidden></div>
    <div class="sdBtns"><span class="spacer"></span><button type="button" data-close>Cancel</button><button class="primary" data-go>Make the script</button></div></form>`;
  document.body.appendChild(dlg);
  const f = $("form", dlg), go = $("[data-go]", dlg), prog = $(".sbProg", dlg);
  $("[data-close]", dlg).onclick = () => dlg.close();
  f.onsubmit = async e => {
    e.preventDefault();
    prog.hidden = false; go.disabled = true; prog.textContent = "⏳ starting…";
    try {
      const job = await api("/api/shop/scriptgen/link", { json: { url: f.elements.url.value.trim(), title: f.elements.title.value.trim() } });
      const r = await sbJob(job, m => (prog.textContent = "⏳ " + m));
      dlg.close();
      await shopLoad(); if (LS.get("homeTab") === "library") renderLibrary();
      openBuilder(r.script);
    } catch (err) { prog.textContent = "⚠ " + err.message; go.disabled = false; }
  };
  dlg.onclose = () => dlg.remove();
  dlg.showModal();
}

// ---------- the builder ----------
async function openBuilder(sid) {
  if (!SHOP.d) await shopLoad();
  const [s, prods] = await Promise.all([api(`/api/shop/scriptgen/script/${sid}`), api("/api/shop/scriptgen/products"), aiReady()]);
  SB.s = s; SB.prods = prods;
  const src = s.source;
  const dlg = SB.dlg = document.createElement("dialog"); dlg.className = "shopDlg sbDlg";
  const aiOff = SB.ai ? "" : 'disabled title="Claude Code isn\'t set up on this PC"';
  dlg.innerHTML = `<div class="sbHead"><input class="sbTitle" value="${esc(s.title)}" title="Script name">
      ${src ? `<a href="${esc(src.url)}" target="_blank" rel="noopener" class="muted">${src.handle ? "@" + esc(src.handle) : "TikTok"} ↗</a>` : `<span class="muted">typed-in script</span>`}
      <span class="spacer"></span><button type="button" data-act="rewrite" class="aiBtn" ${aiOff}>✨ AI: rewrite…</button><button type="button" data-act="close" class="primary">Done</button></div>
    <div class="sbGrid ${src ? "" : "noVideo"}">
      ${src ? `<div class="sbLeft"><video class="sbVid" src="/api/shop/scriptgen/ref/${esc(src.ref)}/video.mp4" controls playsinline preload="metadata"></video>
        <div class="sbShotHead"><b>Shot list</b> <span class="muted">${s.shots.length} shots</span><span class="spacer"></span>
          <button type="button" data-act="describe" class="aiBtn" ${aiOff}>✨ AI: describe shots</button></div>
        <ol class="sbShots"></ol></div>` : ""}
      <div class="sbRight">
        <div class="sbBar"><span class="muted"><b>Highlighted</b> = about this product. Select words to mark more; click a highlight to rename or unmark it.</span><span class="spacer"></span>
          <button type="button" data-act="guess" title="Mark them again with the app's own rules">↺ Re-guess</button>
          <button type="button" data-act="aimarks" class="aiBtn" ${aiOff}>✨ AI: find product details</button></div>
        <div class="sbLines"></div>
        <div class="sbSlots"></div>
        <details class="sbTagsBox"><summary>Formats &amp; tags <span class="muted sbTagN"></span></summary><div class="tagPick sbTags"></div></details>
        <div class="sbAdapt"><h4>Make it for another product</h4>
          <select class="sbProd"><option value="">— pick a product (latest deliveries first) —</option>${prods.map(p => `<option value="${p.id}">${esc(p.name)}${p.delivered ? ` · delivered ${shortDate(p.delivered)}` : ""}</option>`).join("")}</select>
          <div class="sbFills"></div><div class="sbPreview"></div>
          <div class="row sbAdaptBtns" hidden><button type="button" data-act="aifill" class="aiBtn" ${aiOff}>✨ AI: fill the blanks</button><span class="spacer"></span>
            <button type="button" data-act="savefor">Save script for this product</button><button type="button" data-act="video" class="primary">＋ Video</button></div>
          <div class="sbAiMsg muted"></div></div>
      </div></div>
    <div class="sbPop" hidden></div>`;
  document.body.appendChild(dlg);
  sbRender();
  tagPicker($(".sbTags", dlg), s.tags || [], () => ({ product: s.product, script: s.id }));
  $(".sbTags", dlg).addEventListener("change", e => { SB.s.tags = [...$(".sbTags", dlg)._sel]; $(".sbTagN", dlg).textContent = SB.s.tags.length || ""; sbSave(); });
  $(".sbTagN", dlg).textContent = (s.tags || []).length || "";
  $(".sbTitle", dlg).addEventListener("input", e => { SB.s.title = e.target.value; sbSave(); });
  dlg.addEventListener("click", sbClick);
  dlg.addEventListener("input", e => {
    if (e.target.dataset.desc != null) { SB.s.shots[+e.target.dataset.desc].desc = e.target.value; sbSave(); }
    if (e.target.dataset.slot != null) sbPreview();
  });
  $(".sbProd", dlg).onchange = sbAdapt;
  const lines = $(".sbLines", dlg);
  lines.addEventListener("mouseup", () => setTimeout(sbSelected, 10));
  lines.addEventListener("touchend", () => setTimeout(sbSelected, 300));
  const vid = $(".sbVid", dlg);
  if (vid) vid.addEventListener("timeupdate", () => {
    const t = vid.currentTime;
    $$(".sbShots li", dlg).forEach((li, k) => li.classList.toggle("now", SB.s.shots[k].t0 <= t && t < SB.s.shots[k].t1));
    $$(".sbLn", dlg).forEach((ln, i) => { const l = SB.s.lines[i]; ln.classList.toggle("now", l.t0 != null && l.t0 <= t && t <= l.t1 + 0.2); });
  });
  dlg.onclose = async () => { clearTimeout(SB.saveT); await sbSaveNow(); dlg.remove(); SB.dlg = null; shopRefresh(); };
  dlg.addEventListener("cancel", e => { if (!$(".sbPop", dlg).hidden) { e.preventDefault(); sbPopHide(); } });
  dlg.showModal();
}

function sbRender() {
  const s = SB.s, dlg = SB.dlg;
  $(".sbLines", dlg).innerHTML = s.lines.map((l, i) => {
    let h = "", pos = 0;
    for (const m of s.marks.filter(m => m.line === i).sort((a, b) => a.a - b.a)) {
      if (m.a < pos) continue;
      if (m.a > pos) h += `<span data-o="${pos}">${esc(l.text.slice(pos, m.a))}</span>`;
      h += `<mark data-m="${s.marks.indexOf(m)}" data-o="${m.a}" style="--c:${slotColor(m.slot)}">${esc(l.text.slice(m.a, m.b))}<sup contenteditable="false">${esc(m.slot)}</sup></mark>`;
      pos = m.b;
    }
    if (pos < l.text.length) h += `<span data-o="${pos}">${esc(l.text.slice(pos))}</span>`;
    return `<div class="sbLn" data-i="${i}"><span class="sbT" ${l.t0 != null ? `data-seek="${l.t0}" title="Play from here"` : ""}>${l.t0 != null ? fmt(l.t0) : ""}</span><div class="sbTx" data-i="${i}">${h}</div></div>`;
  }).join("") || `<p class="muted">No spoken lines found.</p>`;
  const orig = {};
  for (const m of s.marks) (orig[m.slot] ||= { text: s.lines[m.line].text.slice(m.a, m.b), n: 0 }).n++;
  $(".sbSlots", dlg).innerHTML = Object.keys(orig).length ? `<span class="muted">Blanks:</span> ` + Object.entries(orig).map(([k, v]) =>
    `<button type="button" class="slotChip" data-slot-chip="${esc(k)}" style="--c:${slotColor(k)}" title="Rename"><code>{${esc(k)}}</code> ${esc(v.text)}${v.n > 1 ? ` ×${v.n}` : ""}</button>`).join("")
    : `<span class="muted">Nothing marked yet: select words in the script to make them blanks.</span>`;
  if (s.source) {
    $(".sbShots", dlg).innerHTML = s.shots.map((x, k) => `<li data-k="${k}">
      <img src="/api/shop/scriptgen/ref/${esc(s.source.ref)}/${esc(x.img)}" data-seek="${x.t0}" alt="" title="Play this shot" loading="lazy">
      <div><div class="muted small">Shot ${k + 1} · ${fmt(x.t0)}–${fmt(x.t1)}</div>
        <div class="said">${x.said ? esc(x.said) : '<i class="muted">(no talking)</i>'}</div>
        <textarea rows="2" data-desc="${k}" placeholder="What's on screen: framing, what they do, any text">${esc(x.desc || "")}</textarea></div></li>`).join("");
  }
  sbAdapt(true);
}

// selection offsets inside a line (the slot labels don't count)
function sbOff(tx, node, off) {
  let el = node.nodeType === 3 ? node.parentElement : node;
  if (el.closest("sup")) { const mk = el.closest("mark"); return +mk.dataset.o + mk.firstChild.textContent.length; }
  if (el === tx) {
    const kids = [...tx.children];
    return off >= kids.length ? SB.s.lines[+tx.dataset.i].text.length : +kids[off].dataset.o;
  }
  const seg = el.closest("[data-o]");
  return +seg.dataset.o + (node.nodeType === 3 ? off : 0);
}
function sbSelected() {
  const sel = getSelection();
  if (!sel.rangeCount || sel.isCollapsed) return;
  const r = sel.getRangeAt(0);
  const ta = (r.startContainer.nodeType === 3 ? r.startContainer.parentElement : r.startContainer).closest(".sbTx");
  const tb = (r.endContainer.nodeType === 3 ? r.endContainer.parentElement : r.endContainer).closest(".sbTx");
  if (!ta || ta !== tb) { toast("Select words within one line"); return; }
  const i = +ta.dataset.i, text = SB.s.lines[i].text;
  let a = sbOff(ta, r.startContainer, r.startOffset), b = sbOff(ta, r.endContainer, r.endOffset);
  if (a > b) [a, b] = [b, a];
  while (a < b && /[\s.,!?;:"“”]/.test(text[a])) a++;
  while (b > a && /[\s.,!?;:"“”]/.test(text[b - 1])) b--;
  while (a > 0 && /[\w'’-]/.test(text[a - 1])) a--;  // whole words
  while (b < text.length && /[\w'’-]/.test(text[b])) b++;
  if (a >= b) return;
  const part = text.slice(a, b), same = SB.s.marks.find(m => SB.s.lines[m.line].text.slice(m.a, m.b).toLowerCase() === part.toLowerCase());
  const guess = same?.slot || (/\$|\bdollars?\b/i.test(part) ? "price" : /%|\boff\b/i.test(part) ? "deal" : `feature ${new Set(SB.s.marks.filter(m => m.slot.startsWith("feature")).map(m => m.slot)).size + 1}`);
  sbPop(r.getBoundingClientRect(), `<b>Make “${esc(part)}” a blank</b>
    <div class="row"><input class="sbSlotIn" list="sbSlotList" value="${esc(guess)}"><button type="button" class="primary" data-pop="add">Mark</button></div>
    ${sbSlotList()}<div class="muted small">Same words in other lines get marked too.</div>`, { i, a, b, part });
}
function sbSlotList() {
  const have = [...new Set(SB.s.marks.map(m => m.slot))];
  const n = k => have.filter(x => x.startsWith(k)).length + 1;
  return `<datalist id="sbSlotList">${[...have, "product", "brand", "item", "price", "deal", `feature ${n("feature")}`, `spec ${n("spec")}`, "benefit", "scent", "color", "size"]
    .filter((v, k, a) => a.indexOf(v) === k).map(v => `<option value="${esc(v)}">`).join("")}</datalist>`;
}
function sbPop(rect, html, data) {
  const pop = $(".sbPop", SB.dlg), d = SB.dlg.getBoundingClientRect();
  pop.innerHTML = html + `<button type="button" class="sbPopX" data-pop="x" title="Close">×</button>`;
  pop.hidden = false; pop._data = data;
  const w = pop.offsetWidth;
  pop.style.left = clamp(rect.left - d.left, 8, d.width - w - 8) + "px";
  pop.style.top = (rect.bottom - d.top + 8 + SB.dlg.scrollTop) + "px";
  $("input", pop)?.focus(); $("input", pop)?.select();
  $("input", pop)?.addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); $("[data-pop].primary", pop)?.click(); } });
}
function sbPopHide() { const p = $(".sbPop", SB.dlg); if (p) p.hidden = true; }

function sbAddMark({ i, a, b, part }, slot) {
  const s = SB.s, low = part.toLowerCase();
  const free = (li, x, y) => !s.marks.some(m => m.line === li && x < m.b && y > m.a);
  s.marks = s.marks.filter(m => !(m.line === i && a < m.b && b > m.a));  // the new mark replaces what it overlaps
  s.marks.push({ line: i, a, b, slot });
  s.lines.forEach((l, li) => {  // the same words elsewhere get the same blank
    let k = l.text.toLowerCase().indexOf(low);
    while (k >= 0) {
      const edge = (x, y) => !/[\w]/.test(l.text[x - 1] || " ") && !/[\w]/.test(l.text[y] || " ");
      if (edge(k, k + part.length) && free(li, k, k + part.length)) s.marks.push({ line: li, a: k, b: k + part.length, slot });
      k = l.text.toLowerCase().indexOf(low, k + 1);
    }
  });
  s.marks.sort((x, y) => x.line - y.line || x.a - y.a);
  sbRender(); sbSave();
}

async function sbClick(e) {
  const s = SB.s, dlg = SB.dlg;
  const seek = e.target.closest("[data-seek]"), vid = $(".sbVid", dlg);
  if (seek && vid) { vid.currentTime = +seek.dataset.seek + 0.01; vid.play(); return; }
  const pop = e.target.closest("[data-pop]");
  if (pop) {
    const p = $(".sbPop", dlg), data = p._data, val = ($(".sbSlotIn", p)?.value || "").trim().toLowerCase().replace(/[{}]/g, "");
    if (pop.dataset.pop === "x") return sbPopHide();
    if (pop.dataset.pop === "add" && val) { sbPopHide(); getSelection().removeAllRanges(); return sbAddMark(data, val); }
    if (pop.dataset.pop === "rename" && val) {
      for (const m of s.marks) if (m.slot === data.slot) m.slot = val;
      sbPopHide(); sbRender(); return sbSave();
    }
    if (pop.dataset.pop === "unmark") { s.marks.splice(data.k, 1); sbPopHide(); sbRender(); return sbSave(); }
    if (pop.dataset.pop === "unmarkall") { s.marks = s.marks.filter(m => m.slot !== data.slot); sbPopHide(); sbRender(); return sbSave(); }
    return;
  }
  const mk = e.target.closest("mark[data-m]");
  if (mk && getSelection().isCollapsed) {
    const k = +mk.dataset.m, m = s.marks[k], n = s.marks.filter(x => x.slot === m.slot).length;
    return sbPop(mk.getBoundingClientRect(), `<b>Blank <code>{${esc(m.slot)}}</code></b>
      <div class="row"><input class="sbSlotIn" list="sbSlotList" value="${esc(m.slot)}"><button type="button" class="primary" data-pop="rename">Rename</button></div>${sbSlotList()}
      <div class="row"><button type="button" data-pop="unmark">Unmark this one</button>${n > 1 ? `<button type="button" data-pop="unmarkall">Unmark all ${n}</button>` : ""}</div>`, { k, slot: m.slot });
  }
  const chip = e.target.closest("[data-slot-chip]");
  if (chip) {
    const slot = chip.dataset.slotChip;
    return sbPop(chip.getBoundingClientRect(), `<b>Rename <code>{${esc(slot)}}</code></b>
      <div class="row"><input class="sbSlotIn" list="sbSlotList" value="${esc(slot)}"><button type="button" class="primary" data-pop="rename">Rename</button></div>${sbSlotList()}
      <div class="row"><button type="button" data-pop="unmarkall">Unmark it everywhere</button></div>`, { slot });
  }
  if (!e.target.closest(".sbPop")) sbPopHide();
  const act = e.target.closest("[data-act]")?.dataset.act; if (!act) return;
  const msg = $(".sbAiMsg", dlg), busy = (btn, on) => { btn.disabled = on; btn.classList.toggle("working", on); };
  const btn = e.target.closest("[data-act]");
  if (act === "close") return dlg.close();
  if (act === "guess") {
    if (s.marks.length && !confirm("Replace the highlights with the app's guess?")) return;
    s.marks = (await api(`/api/shop/scriptgen/${s.id}/guess`, { json: {} })).marks; sbRender(); return sbSave();
  }
  if (act === "aimarks" || act === "describe") {
    busy(btn, true); msg.textContent = "";
    try {
      const r = await sbJob(await api(`/api/shop/ai/${act === "aimarks" ? "marks" : "describe"}`, { json: { script: s.id } }), m => (btn.textContent = m));
      if (r.marks) { s.marks = r.marks; toast(`✨ ${r.marks.length} product details marked`); }
      if (r.shots) { s.shots = r.shots; toast("✨ Shot list written"); }
      sbRender(); sbSave();
    } catch (err) { toast("✨ AI: " + err.message, 7000); }
    btn.textContent = act === "aimarks" ? "✨ AI: find product details" : "✨ AI: describe shots"; busy(btn, false);
    return;
  }
  if (act === "rewrite") { await sbSaveNow(); return rewriteDlg(s.id); }
  const pid = $(".sbProd", dlg).value, p = byId("products", pid);
  if (act === "aifill" && p) {
    busy(btn, true);
    try {
      const known = sbFills();
      const r = await sbJob(await api("/api/shop/ai/fill", { json: { script: s.id, product: pid, known } }), m => (msg.textContent = m));
      for (const [k, v] of Object.entries(r.fills || {})) { const i = $(`.sbFills [data-slot="${CSS.escape(k)}"]`, dlg); if (i && !i.value.trim()) i.value = v; }
      msg.textContent = "✨ Filled in by Claude: check them before saving."; sbPreview();
    } catch (err) { msg.textContent = "⚠ " + err.message; }
    busy(btn, false); return;
  }
  if ((act === "savefor" || act === "video") && p) {
    await sbSaveNow();
    const fills = sbFills(), text = sbFill(s.text, fills);
    const saved = await api("/api/shop/scripts", { json: { title: `${s.title} · ${p.name}`, text, product: p.id, tags: s.tags || [], from_template: s.id, notes: `Made from “${s.title}”` } });
    toast(`Saved “${saved.title}” to the library`);
    if (act === "video") { dlg.close(); await shopLoad(); newVideo({ script: saved.id, product: p.id, tags: s.tags || [] }); }
  }
}
const sbFill = (text, vals) => text.replace(/\{([A-Za-z][\w ]{0,30})\}/g, (m, k) => (vals[k.trim().toLowerCase()] || "").trim() || m);
function sbFills() { return Object.fromEntries($$(".sbFills [data-slot]", SB.dlg).map(i => [i.dataset.slot, i.value.trim()])); }

function sbAdapt(keep) {
  const dlg = SB.dlg, s = SB.s, p = byId("products", $(".sbProd", dlg).value);
  $(".sbAdaptBtns", dlg).hidden = !p;
  if (!p) { $(".sbFills", dlg).innerHTML = ""; $(".sbPreview", dlg).innerHTML = ""; return; }
  const typed = keep === true ? sbFills() : {};
  const orig = {};
  for (const m of s.marks) orig[m.slot] ??= s.lines[m.line].text.slice(m.a, m.b);
  for (const k of shop_placeholders(s.text)) orig[k] ??= "";
  const auto = { product: p.name, brand: p.brand, price: p.price, category: p.category, commission: p.commission, ...(p.fills || {}) };
  $(".sbFills", dlg).innerHTML = Object.entries(orig).map(([k, was]) => `<label class="nvFill"><code style="color:${slotColor(k)}">{${esc(k)}}</code>
    <input data-slot="${esc(k)}" value="${esc(typed[k] ?? auto[k] ?? "")}" placeholder="${was ? `was: ${esc(was)}` : "type it"}"></label>`).join("");
  sbPreview();
}
const shop_placeholders = text => [...new Set([...String(text).matchAll(/\{([A-Za-z][\w ]{0,30})\}/g)].map(m => m[1].trim().toLowerCase()))];
function sbPreview() {
  const vals = sbFills();
  $(".sbPreview", SB.dlg).innerHTML = esc(SB.s.text).replace(/\{([A-Za-z][\w ]{0,30})\}/g, (m, k) => {
    const v = (vals[k.trim().toLowerCase()] || "").trim();
    return v ? `<b style="color:${slotColor(k.trim().toLowerCase())}">${v}</b>` : `<code class="blank">${m}</code>`;
  }).replace(/\n/g, "<br>");
}

function sbSave() { clearTimeout(SB.saveT); SB.saveT = setTimeout(sbSaveNow, 700); }
async function sbSaveNow() {
  clearTimeout(SB.saveT);
  const s = SB.s; if (!s) return;
  try {
    const r = await api(`/api/shop/scriptgen/${s.id}/marks`, { json: { marks: s.marks, lines: s.lines, shots: s.shots, title: s.title, tags: s.tags || [] } });
    s.text = r.text; if (SB.dlg) sbPreview();
  } catch (err) { toast("Couldn't save: " + err.message); }
}

// ---------- ✨ AI rewrite (from the builder or a library card) ----------
const QUICK = ["funnier", "more zen and calm", "shorter and punchier", "more urgent", "more honest and down-to-earth", "more relatable", "with a stronger hook"];
async function rewriteDlg(sid) {
  await shopLoad(); await aiReady();
  const s = byId("scripts", sid);
  const tags = SHOP.d.tags.filter(t => ["Tone", "Hook", "Style"].includes(t.group));
  const dlg = document.createElement("dialog"); dlg.className = "shopDlg rwDlg";
  dlg.innerHTML = `<form><h3>✨ AI: rewrite “${esc(s.title)}”</h3>
    <p class="muted">Claude rewrites the wording; {blanks} and [directions] stay as they are. Nothing changes until you save.</p>
    <div class="rwChips">${QUICK.map(q => `<button type="button" class="tag" data-q="${esc(q)}" style="--c:#b197fc">${esc(q)}</button>`).join("")}
      ${tags.map(t => `<button type="button" class="tag" data-t="${t.id}" data-tip="${esc(t.description)}" style="--c:${esc(t.color)}">${esc(t.name)}</button>`).join("")}</div>
    <input class="rwHow" placeholder="…or say how, e.g. like a sarcastic best friend, for dads, in 15 seconds">
    <div class="rwGrid"><div><div class="muted small">Now</div><div class="rwNow">${esc(s.text).replace(/\n/g, "<br>")}</div></div>
      <div><div class="muted small">Rewritten</div><textarea class="rwOut" rows="14" placeholder="Pick a style or type one, then ✨ Rewrite"></textarea></div></div>
    <div class="rwMsg muted"></div>
    <div class="sdBtns"><button type="button" data-close>Cancel</button><span class="spacer"></span>
      <button type="button" class="aiBtn" data-go ${SB.ai ? "" : 'disabled title="Claude Code isn\'t set up on this PC"'}>✨ Rewrite</button>
      <button type="button" data-save="new" disabled>Save as a new script</button><button type="button" data-save="replace" class="primary" disabled>Replace this script</button></div></form>`;
  document.body.appendChild(dlg);
  const how = () => {
    const picked = [...$$(".rwChips .tag.on", dlg)].map(b => b.dataset.q || (t => `in a “${t.name}” style (${t.description})`)(byId("tags", b.dataset.t)));
    const typed = $(".rwHow", dlg).value.trim();
    return [...picked, typed].filter(Boolean).join(", and ");
  };
  const label = () => [...[...$$(".rwChips .tag.on", dlg)].map(b => b.dataset.q || byId("tags", b.dataset.t)?.name), $(".rwHow", dlg).value.trim()].filter(Boolean).join(" + ");
  $(".rwChips", dlg).onclick = e => { const b = e.target.closest(".tag"); if (b) b.classList.toggle("on"); };
  $("[data-close]", dlg).onclick = () => dlg.close();
  $("form", dlg).onsubmit = e => e.preventDefault();
  $(".rwHow", dlg).addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); $("[data-go]", dlg).click(); } });
  $(".rwOut", dlg).addEventListener("input", () => $$("[data-save]", dlg).forEach(b => (b.disabled = !$(".rwOut", dlg).value.trim())));
  $("[data-go]", dlg).onclick = async () => {
    const h = how(); if (!h) { toast("Pick a style or type one"); return; }
    const go = $("[data-go]", dlg), msg = $(".rwMsg", dlg);
    go.disabled = true; go.classList.add("working");
    try {
      const r = await sbJob(await api("/api/shop/ai/rewrite", { json: { text: s.text, how: h } }), m => (msg.textContent = m));
      $(".rwOut", dlg).value = r.text; msg.textContent = "✨ Written by Claude: edit it here if you like.";
      $$("[data-save]", dlg).forEach(b => (b.disabled = false));
    } catch (err) { msg.textContent = "⚠ " + err.message; }
    go.disabled = false; go.classList.remove("working");
  };
  dlg.addEventListener("click", async e => {
    const sv = e.target.closest("[data-save]"); if (!sv) return;
    const text = $(".rwOut", dlg).value.trim(); if (!text) return;
    if (sv.dataset.save === "new") {
      const n = await api("/api/shop/scripts", { json: { title: `${s.title} · ${label() || "rewrite"}`, text, product: s.product, tags: s.tags || [], from_template: s.id, notes: `✨ AI rewrite of “${s.title}”: ${how()}` } });
      toast(`Saved “${n.title}”`);
    } else {
      await api("/api/shop/scripts", { json: { ...s, text, edited: true } });
      toast("Script replaced");
    }
    dlg.close();
    await shopLoad();
    if (SB.dlg) {  // reopen the builder on the new text (without saving the old lines over it)
      const id = SB.s.id; SB.s = null; SB.dlg.close(); openBuilder(id);
    } else if (LS.get("homeTab") === "library") renderLibrary();
  });
  dlg.onclose = () => dlg.remove();
  dlg.showModal();
}
