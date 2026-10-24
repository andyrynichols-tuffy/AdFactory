/* TikTok Shop side of Ad Factory (adcut/shop.py): Overview, the creators' Queue, Products &
   orders, Analytics per account, the Script & format library, the New video form and the
   posting dialog. Uses app.js's helpers ($, api, esc, toast, LS, copyText…). */
"use strict";
const SHOP = { d: null, board: [], an: null };
const shopLoad = async () => (SHOP.d = await api("/api/shop"));
const byId = (kind, id) => (id && SHOP.d?.[kind]?.find(x => x.id === id)) || null;
const num = v => v == null ? "–" : v >= 1e6 ? (v / 1e6).toFixed(1).replace(/\.0$/, "") + "M" : v >= 1e4 ? Math.round(v / 1e3) + "K"
  : v >= 1e3 ? (v / 1e3).toFixed(1).replace(/\.0$/, "") + "K" : String(v);
const plus = v => v ? `<span class="${v > 0 ? "up" : "down"}">${v > 0 ? "+" : ""}${num(v)}</span>` : "";
const dleft = n => n == null ? "" : n < 0 ? `${-n} day${n === -1 ? "" : "s"} ago` : n === 0 ? "today" : n === 1 ? "tomorrow" : `in ${n} days`;
const ago = t => { if (!t) return "never"; const m = (Date.now() / 1000 - t) / 60; return m < 2 ? "just now" : m < 90 ? `${Math.round(m)} min ago` : m < 48 * 60 ? `${Math.round(m / 60)} h ago` : `${Math.round(m / 1440)} days ago`; };
const shortDate = s => s ? new Date(s + "T12:00").toLocaleDateString(undefined, { month: "short", day: "numeric" }) : "";
const SAMPLE = { free: "🎁 Free sample", refundable: "↩ Refundable", paid: "💳 Bought" };
const ORDER_ST = { ordered: "Ordered", shipped: "Shipped", delivered: "Delivered", kept: "Kept", returned: "Returned", cancelled: "Cancelled" };
const LOGIN = { email: "Email", Google: "Google", Apple: "Apple", phone: "Phone number", other: "Other" };

// ---------- little pieces ----------
function tagChip(id, { on = false, btn = false } = {}) {
  const t = byId("tags", id); if (!t) return "";
  const tag = btn ? "button" : "span";
  return `<${tag} ${btn ? 'type="button"' : ""} class="tag ${on ? "on" : ""}" data-tag="${t.id}" data-tip="${esc(t.description || t.name)}" style="--c:${esc(t.color || "#adb5bd")}">${esc(t.name)}</${tag}>`;
}
const tagsRow = (ids, max = 99) => (ids || []).slice(0, max).map(id => tagChip(id)).join("") + ((ids || []).length > max ? `<span class="muted">+${ids.length - max}</span>` : "");
const accChip = id => { const a = byId("accounts", id); return a ? `<span class="acc" style="--c:${esc(a.color)}" data-tip="${esc(a.handle ? "@" + a.handle.replace(/^@/, "") : a.name)}">${esc(a.name || "@" + a.handle)}</span>` : ""; };
const who = id => { const c = byId("creators", id); return c ? `<span class="who" style="--c:${esc(c.color)}"><i>${esc(c.name.slice(0, 1).toUpperCase())}</i>${esc(c.name)}</span>` : ""; };
const prodName = id => byId("products", id)?.name || "";
const opts = (list, val, label = x => x.name, none = "—") => `<option value="">${none}</option>` + list.map(x => `<option value="${x.id}" ${x.id === val ? "selected" : ""}>${esc(label(x))}</option>`).join("");
const accLabel = a => `${a.name || ""}${a.handle ? ` (@${a.handle.replace(/^@/, "")})` : ""}`.trim();
const products = () => (SHOP.d.products || []).filter(p => !p.archived).sort((a, b) => a.name.localeCompare(b.name));
const allGroups = () => [...new Set([...(SHOP.d.groups || []), ...SHOP.d.tags.map(t => t.group)])];
const me = () => LS.get("me", "");

// hover (or tap) a tag for what it means
const TIP = document.createElement("div"); TIP.id = "tip"; TIP.hidden = true; document.body.appendChild(TIP);
function showTip(el) {
  const host = el.closest("dialog[open]") || document.body;  // an open dialog sits above everything else
  if (TIP.parentNode !== host) host.appendChild(TIP);
  TIP.textContent = el.dataset.tip; TIP.hidden = false;
  const r = el.getBoundingClientRect(), w = Math.min(300, innerWidth - 20);
  TIP.style.maxWidth = w + "px";
  const tw = TIP.offsetWidth, th = TIP.offsetHeight;
  TIP.style.left = clamp(r.left + r.width / 2 - tw / 2, 10, innerWidth - tw - 10) + "px";
  TIP.style.top = (r.top - th - 8 < 6 ? r.bottom + 8 : r.top - th - 8) + "px";
}
document.addEventListener("mouseover", e => { const el = e.target.closest?.("[data-tip]"); if (el && el.dataset.tip) showTip(el); else TIP.hidden = true; });
document.addEventListener("touchstart", e => { const el = e.target.closest?.("[data-tip]"); if (el && el.dataset.tip) { showTip(el); clearTimeout(showTip.t); showTip.t = setTimeout(() => (TIP.hidden = true), 3500); } }, { passive: true });
document.addEventListener("scroll", () => (TIP.hidden = true), true);

function tagPicker(el, sel = []) {
  el._sel = new Set(sel);
  el.innerHTML = allGroups().map(g => {
    const ts = SHOP.d.tags.filter(t => t.group === g).sort((a, b) => a.name.localeCompare(b.name));
    return ts.length ? `<div class="tpGroup"><span class="tpG">${esc(g)}</span>${ts.map(t => tagChip(t.id, { on: el._sel.has(t.id), btn: true })).join("")}</div>` : "";
  }).join("") || `<span class="muted">No tags yet: add some in Library → Formats & tags.</span>`;
  el.onclick = e => {
    const c = e.target.closest("[data-tag]"); if (!c) return;
    e.preventDefault();
    const id = c.dataset.tag;
    if (el._sel.has(id)) el._sel.delete(id); else el._sel.add(id);
    c.classList.toggle("on", el._sel.has(id));
    el.dispatchEvent(new Event("change", { bubbles: true }));
  };
}

// ---------- a generic form in a dialog ----------
function fieldHtml(f, v) {
  const lab = `${esc(f.label)}${f.hint ? ` <span class="fhint">${esc(f.hint)}</span>` : ""}`;
  const cls = `fld ${f.wide ? "wide" : ""}`;
  const req = f.required ? "required" : "";
  if (f.type === "select") return `<label class="${cls}">${lab}<select name="${f.k}" ${req}>${f.none === false ? "" : `<option value="">${esc(f.none || "—")}</option>`}${f.options.map(([val, l]) => `<option value="${esc(val)}" ${String(val) === String(v ?? f.def ?? "") ? "selected" : ""}>${esc(l)}</option>`).join("")}</select></label>`;
  if (f.type === "textarea") return `<label class="${cls}">${lab}<textarea name="${f.k}" rows="${f.rows || 3}" placeholder="${esc(f.placeholder || "")}" ${req}>${esc(v ?? "")}</textarea></label>`;
  if (f.type === "fills") return `<label class="${cls}">${lab}<textarea name="${f.k}" rows="${f.rows || 3}" placeholder="${esc(f.placeholder || "")}">${esc(Object.entries(v || {}).map(([a, b]) => `${a}: ${b}`).join("\n"))}</textarea></label>`;
  if (f.type === "check") return `<label class="chk ${f.wide ? "wide" : ""}"><input type="checkbox" name="${f.k}" ${v ? "checked" : ""}> ${lab}</label>`;
  if (f.type === "tags") return `<div class="${cls} wide"><span>${lab}</span><div class="tagPick" data-tagpick="${f.k}"></div></div>`;
  if (f.type === "note") return `<p class="hint wide">${f.label}</p>`;
  return `<label class="${cls}">${lab}<input name="${f.k}" type="${f.type || "text"}" value="${esc(v ?? f.def ?? "")}" placeholder="${esc(f.placeholder || "")}" ${f.list ? `list="${f.k}List"` : ""} ${req}>${f.list ? `<datalist id="${f.k}List">${f.list.map(x => `<option value="${esc(x)}">`).join("")}</datalist>` : ""}</label>`;
}
function readFields(form, fields, base) {
  const out = { ...base };
  for (const f of fields) {
    if (f.type === "note") continue;
    if (f.type === "tags") { out[f.k] = [...form.querySelector(`[data-tagpick="${f.k}"]`)._sel]; continue; }
    const el = form.elements[f.k]; if (!el) continue;
    if (f.type === "check") out[f.k] = el.checked;
    else if (f.type === "number") out[f.k] = el.value === "" ? null : Number(el.value);
    else if (f.type === "fills") out[f.k] = Object.fromEntries(el.value.split("\n").map(l => l.split(/:(.*)/s)).filter(x => x[0].trim() && x[1]?.trim()).map(x => [x[0].trim().toLowerCase(), x[1].trim()]));
    else out[f.k] = el.value.trim() || (f.type === "select" ? null : "");
  }
  return out;
}
function formDlg(title, fields, val = {}, o = {}) {
  return new Promise(res => {
    const dlg = document.createElement("dialog"); dlg.className = "shopDlg";
    dlg.innerHTML = `<form method="dialog"><h3>${esc(title)}</h3>${o.hint ? `<p class="muted">${o.hint}</p>` : ""}
      <div class="fgrid">${fields.map(f => fieldHtml(f, val[f.k])).join("")}</div>
      <div class="sdBtns">${o.remove ? `<button type="button" data-close="remove" class="ghost danger">${esc(o.remove)}</button>` : ""}<span class="spacer"></span>
        <button type="button" data-close="cancel">Cancel</button><button value="save" class="primary">${esc(o.ok || "Save")}</button></div></form>`;
    document.body.appendChild(dlg);
    $$("[data-tagpick]", dlg).forEach(el => tagPicker(el, val[el.dataset.tagpick] || []));
    const form = $("form", dlg);
    $$("[data-close]", dlg).forEach(b => (b.onclick = () => dlg.close(b.dataset.close)));
    dlg.onclose = () => {
      const v = dlg.returnValue, out = v === "save" ? readFields(form, fields, val) : v === "remove" ? "remove" : null;
      dlg.remove(); res(out);
    };
    dlg.showModal();
    form.querySelector("input:not([type=checkbox]),textarea,select")?.focus();
  });
}

// ---------- the forms ----------
const F = {
  accounts: () => [
    { k: "name", label: "Name", placeholder: "what you call it, e.g. Main shop", required: true },
    { k: "handle", label: "TikTok handle", placeholder: "@handle", hint: "reads its public numbers" },
    { k: "email", label: "Login email", type: "email", placeholder: "the email it's signed up with" },
    { k: "login", label: "Signs in with", type: "select", options: Object.entries(LOGIN), none: false, def: "email" },
    { k: "creator", label: "Usual creator", type: "select", options: SHOP.d.creators.map(c => [c.id, c.name]), hint: "pre-filled on new videos" },
    { k: "color", label: "Color", type: "color", def: "#21a366" },
    { k: "notes", label: "Notes", type: "textarea", wide: true, placeholder: "niche, shop/affiliate details…" },
    { k: "", type: "note", label: "🔒 No passwords here: keep those in your password manager. The handle is only used to read the account's public TikTok page." }],
  creators: () => [
    { k: "name", label: "Name", required: true }, { k: "color", label: "Color", type: "color", def: "#4dabf7" },
    { k: "notes", label: "Notes", type: "textarea", wide: true }],
  products: () => [
    { k: "name", label: "Product name", required: true, wide: true, placeholder: "what to search when tagging it in TikTok" },
    { k: "brand", label: "Brand" }, { k: "category", label: "Category", list: [...new Set(SHOP.d.products.map(p => p.category).filter(Boolean))] },
    { k: "link", label: "TikTok Shop link", type: "url", wide: true },
    { k: "image", label: "Picture (image link)", type: "url", wide: true },
    { k: "price", label: "Price", placeholder: "$19.99" }, { k: "commission", label: "Commission", placeholder: "15%" },
    { k: "fills", label: "Script fill-ins", type: "fills", wide: true, rows: 3, hint: "one per line: name: text",
      placeholder: "benefit: fills in patchy brows in seconds\ndeal: buy one get one" },
    { k: "notes", label: "Notes", type: "textarea", wide: true },
    { k: "archived", label: "Archived (no longer promoting it)", type: "check", wide: true }],
  orders: () => [
    { k: "product", label: "Product", type: "select", options: products().map(p => [p.id, p.name]), required: true, wide: true },
    { k: "account", label: "Ordered on account", type: "select", options: SHOP.d.accounts.map(a => [a.id, accLabel(a)]), required: true },
    { k: "sample", label: "Kind", type: "select", none: false, options: [["free", "🎁 Free sample"], ["refundable", "↩ Refundable sample (can go back)"], ["paid", "💳 Bought, keeping it"]] },
    { k: "status", label: "Status", type: "select", none: false, options: Object.entries(ORDER_ST) },
    { k: "order_no", label: "Order number" },
    { k: "ordered", label: "Ordered", type: "date" }, { k: "delivered", label: "Delivered", type: "date" },
    { k: "return_days", label: "Return window (days)", type: "number", hint: "counted from delivery" },
    { k: "return_by", label: "Last day to return", type: "date", hint: "non-refundable after; blank = worked out" },
    { k: "video_due", label: "Video due by", type: "date", hint: "free-sample deadline" },
    { k: "cost", label: "Cost", placeholder: "$0" },
    { k: "notes", label: "Notes", type: "textarea", wide: true }],
  scripts: () => [
    { k: "title", label: "Title", required: true, wide: true },
    { k: "text", label: "Script", type: "textarea", rows: 12, wide: true, required: true,
      hint: "one line per line; {product} {brand} {price} and your own like {benefit} get filled in", placeholder: "Stop scrolling if you've got patchy brows.\n{product} fills them in in seconds…\n[point at the brow]" },
    { k: "product", label: "Product (optional)", type: "select", options: products().map(p => [p.id, p.name]), hint: "blank = works for any product" },
    { k: "tags", label: "Formats & tags", type: "tags" },
    { k: "notes", label: "Notes", type: "textarea", wide: true }],
  tags: () => [
    { k: "name", label: "Name", required: true },
    { k: "group", label: "Group", list: allGroups(), def: "Format", hint: "Format, Hook, Style, Tone or your own" },
    { k: "description", label: "What it means (shown on hover)", type: "textarea", wide: true, rows: 3, required: true },
    { k: "color", label: "Color", type: "color", def: "#4dabf7" }],
};
const NOUN = { accounts: "account", creators: "person", products: "product", orders: "order", scripts: "script", tags: "tag" };
async function editThing(kind, obj = {}, extra = {}) {
  if (!SHOP.d) await shopLoad();
  const isNew = !obj.id;
  const v = await formDlg(`${isNew ? "＋ New" : "Edit"} ${NOUN[kind]}`, F[kind](), obj, { remove: isNew ? null : "Remove", ...extra });
  if (!v) return null;
  if (v === "remove") {
    if (!confirm(`Remove this ${NOUN[kind]}? (It's kept in the trash in ads/_shop.json.)`)) return null;
    await api(`/api/shop/${kind}/${obj.id}`, { method: "DELETE" }); toast("Removed"); await shopRefresh(); return null;
  }
  if (kind === "tags" && !v.group) v.group = "Format";
  if (kind === "scripts" && obj.id && v.text !== obj.text) v.edited = true;  // the sheet no longer overwrites it
  const saved = await api(`/api/shop/${kind}`, { json: v });
  toast(`Saved ${NOUN[kind]}`); await shopRefresh(); return saved;
}
async function listDlg(kind, title, hint) {
  await shopLoad();
  const dlg = document.createElement("dialog"); dlg.className = "shopDlg";
  const draw = () => {
    const list = SHOP.d[kind];
    dlg.innerHTML = `<form method="dialog"><h3>${esc(title)}</h3><p class="muted">${hint}</p>
      <ul class="mgrList">${list.map(x => `<li><span class="dot" style="background:${esc(x.color || "#888")}"></span><b>${esc(x.name || x.handle)}</b>
        <span class="muted">${kind === "accounts" ? esc([x.handle && "@" + x.handle.replace(/^@/, ""), x.email].filter(Boolean).join(" · ")) : ""}
        ${kind === "accounts" && x.creator ? " · usually " + esc(byId("creators", x.creator)?.name || "") : ""}</span>
        <span class="spacer"></span><button type="button" data-edit="${x.id}">Edit</button></li>`).join("") || `<li class="muted">None yet.</li>`}</ul>
      <div class="sdBtns"><button type="button" data-add>＋ Add ${NOUN[kind]}</button><span class="spacer"></span><button value="close" class="primary">Done</button></div></form>`;
  };
  draw(); document.body.appendChild(dlg);
  dlg.onclick = async e => {
    const ed = e.target.closest("[data-edit]"), add = e.target.closest("[data-add]");
    if (!ed && !add) return;
    dlg.close("edit");
    await editThing(kind, ed ? byId(kind, ed.dataset.edit) : {});
    await shopLoad(); draw(); dlg.showModal();
  };
  dlg.onclose = () => { if (dlg.returnValue !== "edit") { dlg.remove(); shopRefresh(); } };
  dlg.showModal();
}
async function shopRefresh() { await shopLoad(); const t = LS.get("homeTab", "overview"); if (PANES[t]) PANES[t](); }

// ---------- New video ----------
function scriptOptions(productId, tags) {
  const score = s => (s.product && s.product === productId ? 10 : 0) + (s.tags || []).filter(t => tags.includes(t)).length + (s.product ? 0 : 1);
  const list = [...SHOP.d.scripts].sort((a, b) => score(b) - score(a) || a.title.localeCompare(b.title));
  return `<option value="">✍ Write a new script</option>` + list.map(s => `<option value="${s.id}">${esc(s.title)}${s.product ? ` · ${esc(prodName(s.product))}` : ""}${s._placeholders?.length ? " · {fill-ins}" : ""}</option>`).join("");
}
async function newVideo(pre = {}) {
  await shopLoad();
  const d = SHOP.d;
  const dlg = document.createElement("dialog"); dlg.className = "shopDlg nvDlg";
  dlg.innerHTML = `<form method="dialog"><h3>＋ New video</h3>
    <p class="muted">Fill in what you know; everything is optional. <b>Send to queue</b> assigns it to the creator to film; dropping in raw videos gets it pre-cut automatically.</p>
    <div class="nvGrid">
      <div class="nvCol">
        <div class="nvRow"><label class="fld">Product<select name="product">${opts(products(), pre.product, p => p.name, "— pick a product —")}</select></label>
          <button type="button" class="nvAddP" title="Add a product">＋</button></div>
        <label class="fld">Channel (TikTok account)<select name="account">${opts(d.accounts, pre.account, accLabel, d.accounts.length ? "— pick an account —" : "— no accounts yet (Analytics → Accounts) —")}</select></label>
        <label class="fld">Creator (who's in it)<select name="creator">${opts(d.creators, pre.creator, c => c.name, d.creators.length ? "— pick a person —" : "— nobody yet (Queue → People) —")}</select></label>
        <div class="fld">Style <span class="fhint">optional · hover a tag for what it means</span><div class="tagPick" data-tagpick="tags"></div></div>
        <label class="fld">Video to copy <span class="fhint">TikTok link, optional</span><input name="reference" type="url" placeholder="https://www.tiktok.com/…" value="${esc(pre.reference || "")}"></label>
      </div>
      <div class="nvCol">
        <label class="fld">Script<select name="script"></select></label>
        <div class="nvFills"></div>
        <textarea name="script_text" rows="9" placeholder="Type or paste the script, one line per line. [Directions in brackets] go to the notes, not the captions."></textarea>
        <label class="chk nvSave"><input type="checkbox" name="save_script" checked> <span>Save to the script library</span></label>
        <label class="fld">Raw videos <span class="fhint">optional: or drop them in later</span><input type="file" name="files" multiple accept="video/*,.mov,.mp4,.m4v"></label>
        <div class="nvRow"><label class="fld">Due<input type="date" name="due" value="${esc(pre.due || "")}"></label>
          <label class="fld">Title <span class="fhint">optional</span><input name="title" placeholder="product · format · date"></label></div>
        <label class="fld">Notes for the creator<textarea name="notes" rows="2" placeholder="angle, outfit, props…"></textarea></label>
      </div>
    </div>
    <div class="sdBtns"><button type="button" data-close="cancel">Cancel</button><span class="spacer"></span>
      <button value="assign" title="Put it in the creator's queue to film">📋 Send to queue</button>
      <button value="open" class="primary" title="Make the shoot now and open the editor">Create &amp; edit</button></div></form>`;
  document.body.appendChild(dlg);
  const f = $("form", dlg), el = n => f.elements[n];
  $("[data-close]", dlg).onclick = () => dlg.close("cancel");
  f.addEventListener("keydown", e => { if (e.key === "Enter" && e.target.tagName === "INPUT") e.preventDefault(); });
  const pick = $("[data-tagpick]", dlg);
  tagPicker(pick, pre.tags || []);
  let lib = null;  // the library script picked (its text as it was)
  const fillsFor = () => {
    const p = byId("products", el("product").value);
    const base = p ? { product: p.name, brand: p.brand, price: p.price, link: p.link, category: p.category, commission: p.commission, ...(p.fills || {}) } : {};
    return Object.fromEntries(Object.entries(base).filter(([, v]) => v));
  };
  const keep = {};  // fill-ins typed here
  const drawFills = () => {
    $$(".nvFills input", dlg).forEach(i => (keep[i.dataset.ph] = i.value));
    const phs = [...new Set([...el("script_text").value.matchAll(/\{([A-Za-z][\w ]{0,30})\}/g)].map(m => m[1].trim().toLowerCase()))];
    const auto = fillsFor();
    $(".nvFills", dlg).innerHTML = phs.length ? `<div class="fhint">Fill-ins (from the product where it has them):</div>` + phs.map(k =>
      `<label class="nvFill ${auto[k] || keep[k] ? "" : "need"}"><code>{${esc(k)}}</code><input data-ph="${esc(k)}" value="${esc(keep[k] ?? auto[k] ?? "")}" placeholder="${auto[k] ? "" : "type it"}"></label>`).join("") : "";
    const changed = !lib || el("script_text").value !== lib.text;
    $(".nvSave", dlg).hidden = !changed || !el("script_text").value.trim();
    $(".nvSave span", dlg).textContent = lib ? "Save as a new script in the library" : "Save to the script library";
  };
  const drawScripts = () => { const v = el("script").value; el("script").innerHTML = scriptOptions(el("product").value, [...pick._sel]); el("script").value = v; };
  el("product").onchange = () => { drawScripts(); drawFills(); };
  el("account").onchange = () => { const a = byId("accounts", el("account").value); if (a?.creator && !el("creator").dataset.touched) el("creator").value = a.creator; };
  el("creator").onchange = () => (el("creator").dataset.touched = "1");
  pick.addEventListener("change", drawScripts);
  el("script").onchange = () => {
    lib = byId("scripts", el("script").value);
    if (lib) {
      el("script_text").value = lib.text;
      if (!el("product").value && lib.product) { el("product").value = lib.product; drawScripts(); el("script").value = lib.id; }
      if (!pick._sel.size && lib.tags?.length) tagPicker(pick, lib.tags);
    }
    drawFills();
  };
  el("script_text").addEventListener("input", drawFills);
  $(".nvAddP", dlg).onclick = async () => {
    dlg.close("keep");
    const p = await editThing("products", {});
    await shopLoad(); dlg.showModal();
    if (p) { el("product").innerHTML = opts(products(), p.id, x => x.name, "— pick a product —"); el("product").onchange(); }
  };
  drawScripts();
  if (pre.script) { el("script").value = pre.script; el("script").onchange(); }
  if (pre.account) el("account").onchange();
  drawFills();
  dlg.onclose = async () => {
    const how = dlg.returnValue;
    if (how === "keep") return;
    if (how !== "assign" && how !== "open") { dlg.remove(); return; }
    const vars = Object.fromEntries($$(".nvFills input", dlg).map(i => [i.dataset.ph, i.value.trim()]).filter(x => x[1]));
    const text = el("script_text").value, files = [...el("files").files];
    const body = {
      product: el("product").value || null, account: el("account").value || null, creator: el("creator").value || null,
      tags: [...pick._sel], reference: el("reference").value.trim(), script: lib && text === lib.text ? lib.id : null,
      script_text: text, vars, save_script: !$(".nvSave", dlg).hidden && el("save_script").checked,
      due: el("due").value, notes: el("notes").value.trim(), title: el("title").value.trim(), assign: how === "assign",
    };
    dlg.remove();
    try {
      const r = await api("/api/shop/new/video", { json: body });
      if (files.length) {
        showHomeTab("queue");
        HD.files = files.filter(isVideo);
        toast(`“${r.title}” made. Uploading the raw videos; it gets pre-cut automatically.`, 5000);
        if (HD.files.length) hdUpload(r.id);
      } else if (how === "open") openShoot(r.id);
      else { toast(`📋 “${r.title}” is in ${byId("creators", body.creator)?.name ? byId("creators", body.creator).name + "'s" : "the"} queue`, 4000); showHomeTab("queue"); }
    } catch (e) { toast("Couldn't make it: " + e.message, 6000); }
  };
  dlg.showModal();
}

// ---------- the posting dialog: which account, which product, the TikTok link ----------
async function postDialog(sid, n, posted = true) {
  await shopLoad();
  const rows = await api("/api/shop/postings/all").catch(() => []);
  const r = rows.find(x => x.sid === sid && x.n === n) || {};
  const v = await formDlg(`📤 Video ${n} posted`, [
    { k: "account", label: "Posted on", type: "select", options: SHOP.d.accounts.map(a => [a.id, accLabel(a)]), none: SHOP.d.accounts.length ? "— which account? —" : "— add accounts in Analytics —" },
    { k: "product", label: "Product linked", type: "select", options: products().map(p => [p.id, p.name]) },
    { k: "url", label: "TikTok link", type: "url", wide: true, placeholder: "paste it once it's up (Share → Copy link)", hint: "its views etc. update every few hours" },
    { k: "posted", label: "Posted", type: "check" }],
    { account: r.account, product: r.product, url: r.url || "", posted }, { ok: "Save" });
  if (!v) return;
  await api(`/api/shop/posting/${sid}`, { json: { n, account: v.account, product: v.product, url: v.url, posted: v.posted } });
  toast(v.url ? "Saved: its numbers show up in Analytics shortly" : "Saved. Add the TikTok link any time (Posting tab).", 4000);
  if (!$("#home").hidden) { loadSaved(); shopRefresh(); }
}

// ---------- Overview ----------
async function renderOverview() {
  const el = $("#paneOverview");
  const [d, board] = await Promise.all([shopLoad(), api("/api/shop/board/all").catch(() => [])]);
  SHOP.board = board;
  const sm = d.summary, cnt = k => board.filter(b => b.stage === k && b.planned).length;
  const setup = !d.accounts.length || !d.creators.length;
  el.innerHTML = `
    ${setup ? `<div class="sc setup"><b>Set up the shop side</b>
      <p class="muted">Add the TikTok accounts he manages and the people who film, then products and orders. Logins stay with you: only the handle and login email are kept here, never passwords.</p>
      <div class="row"><button data-go="accounts" class="${d.accounts.length ? "" : "primary"}">＋ Accounts (${d.accounts.length})</button>
        <button data-go="creators" class="${d.creators.length ? "" : "primary"}">＋ People who film (${d.creators.length})</button>
        <button data-go="products">🛍 Products (${products().length})</button></div></div>` : ""}
    <div class="ovGrid">
      <div class="sc"><h3>Needs attention</h3>${sm.alerts.length ? `<ul class="alerts">${sm.alerts.map(a => `<li class="${a.level}" data-alert="${a.order || a.sid}" data-kind="${a.kind}">${a.kind === "return" ? "↩" : a.kind === "due" ? "🎬" : "📋"} ${esc(a.text)}</li>`).join("")}</ul>` : `<p class="muted">Nothing due. Return windows closing within a week and free-sample videos that are due show up here.</p>`}</div>
      <div class="sc"><h3>Pipeline</h3><div class="pipe">${d.stages.map(([k, l]) => `<button data-stage="${k}"><b>${k === "posted" ? board.filter(b => b.stage === k).length : cnt(k)}</b><span>${l}</span></button>`).join("")}</div>
        <p class="hint">Raw videos dropped in are pre-cut automatically; anyone can pick one up from the Queue to finish it.</p></div>
    </div>
    <h3 class="secHead">Accounts <button class="linkish" data-go="accounts">manage</button></h3>
    <div class="accGrid">${d.accounts.map(a => { const n = sm.accounts[a.id] || {}, p = sm.per.accounts[a.id] || {};
      return `<div class="sc accCard" data-acc="${a.id}" style="--c:${esc(a.color)}"><div class="accTop"><span class="dot"></span><b>${esc(a.name)}</b>
        <span class="muted">${a.handle ? "@" + esc(a.handle.replace(/^@/, "")) : "no handle"}</span></div>
        <div class="kpis"><div><b>${num(n.followers)}</b><span>followers ${plus(n.week?.followers)}</span></div>
          <div><b>${p.posted || 0}</b><span>posted here</span></div><div><b>${num(p.avg_views)}</b><span>avg views</span></div></div>
        ${n.error ? `<div class="warnx">⚠ ${esc(n.error)}</div>` : ""}${a.creator ? `<div class="muted">usually ${who(a.creator)}</div>` : ""}</div>`; }).join("") || `<p class="muted">No accounts yet.</p>`}</div>`;
  el.onclick = async e => {
    const go = e.target.closest("[data-go]")?.dataset.go;
    if (go === "accounts") return listDlg("accounts", "TikTok accounts", "The accounts he runs. Handle = for the public numbers; login email = which login it is. No passwords.");
    if (go === "creators") return listDlg("creators", "People who film", "Everyone who can be in a video or edit one. Each has a queue.");
    if (go === "products") return showHomeTab("products");
    const st = e.target.closest("[data-stage]"); if (st) { LS.set("queueFocus", st.dataset.stage); return showHomeTab("queue"); }
    const acc = e.target.closest("[data-acc]"); if (acc) { LS.set("anAcc", acc.dataset.acc); return showHomeTab("analytics"); }
    const al = e.target.closest("[data-alert]");
    if (al) { if (al.dataset.kind === "film") openShoot(al.dataset.alert); else editThing("orders", byId("orders", al.dataset.alert)); }
  };
}

// ---------- Queue ----------
function stageActs(b) {
  const pick = b.editor ? `<button data-act="handoff" title="Stop editing so someone else can pick it up">✂ ${esc(byId("creators", b.editor)?.name || "someone")} is editing</button>`
    : `<button data-act="pickup" class="primary" title="Say you're finishing this one">✂ Pick up</button>`;
  const A = {
    film: `<button data-act="script">📝 Script</button><button data-act="addvid" class="primary">⬆ Add raw videos</button>`,
    precut: `<span class="muted">⏳ pre-cutting the takes…</span>`,
    edit: `${pick}<button data-act="edit">✏️ Edit</button><button data-act="review">👁 Review</button>`,
    post: `<button data-act="review" class="primary">👁 Review &amp; post</button><button data-act="edit">✏️ Edit</button>`,
    posted: `<button data-act="review">👁 Videos</button><button data-act="stats">📊</button>`,
  };
  return A[b.stage] || "";
}
async function renderQueue() {
  const el = $("#paneQueue");
  const [d, board] = await Promise.all([shopLoad(), api("/api/shop/board/all")]);
  SHOP.board = board;
  const whoF = LS.get("queueWho", ""), all = LS.get("queueAll", false), focus = LS.get("queueFocus", "");
  LS.set("queueFocus", "");
  const rows = board.filter(b => (all || b.planned) && (!whoF || (whoF === "none" ? !b.creator : b.creator === whoF || b.editor === whoF)));
  el.innerHTML = `<div class="tbar">
      <span class="seg chips">${[["", "Everyone"], ...d.creators.map(c => [c.id, c.name]), ["none", "Unassigned"]].map(([v, l]) => `<button data-who="${v}" class="${whoF === v ? "on" : ""}">${esc(l)}</button>`).join("")}</span>
      <button data-go="people" title="Add or edit the people who film">⚙ People</button>
      <label class="chk" title="Pick-up marks things as edited by you">I'm <select id="meSel">${opts(d.creators, me(), c => c.name, "— who are you? —")}</select></label>
      <span class="spacer"></span><label class="chk"><input type="checkbox" id="qAll" ${all ? "checked" : ""}> test / unplanned shoots</label>
      <button class="primary" data-go="assign">📋 Assign a video</button></div>
    <div class="kanban">${d.stages.map(([k, l]) => { const col = rows.filter(b => b.stage === k).sort((a, b) => (a.due || "9").localeCompare(b.due || "9") || b.created - a.created);
      return `<section class="kcol ${focus === k ? "focus" : ""}" data-col="${k}"><h4>${l} <span class="cnt">${col.length}</span></h4>${col.map(b => `
        <div class="qcard" data-sid="${b.sid}">
          ${b.thumb ? `<img loading="lazy" src="${b.thumb}" alt="">` : ""}
          <div class="qt"><b>${esc(b.title)}</b>${b.due ? `<span class="due ${b.due_in != null && b.due_in < 0 ? "late" : b.due_in != null && b.due_in <= 2 ? "soon" : ""}">due ${shortDate(b.due)}</span>` : ""}</div>
          <div class="qm">${b.product_name ? `🛍 ${esc(b.product_name)}` : `<span class="muted">no product</span>`} ${accChip(b.account)} ${who(b.creator)}</div>
          ${b.tags?.length ? `<div class="qtags">${tagsRow(b.tags, 4)}</div>` : ""}
          ${b.notes ? `<div class="qnote">${esc(b.notes)}</div>` : ""}
          <div class="qm muted">${b.lines} lines · ${b.sources} raw · ${b.videos} videos${b.saved ? ` · ☆${b.saved}` : ""}${b.posted ? ` · ✓${b.posted} posted` : ""}</div>
          <div class="qa">${stageActs(b)}<button data-act="plan" title="Product, account, creator, tags, due date">⋯</button></div>
        </div>`).join("") || `<p class="muted kempty">—</p>`}</section>`; }).join("")}</div>`;
  el.querySelector(".kcol.focus")?.scrollIntoView({ block: "nearest", inline: "start" });
}
async function planDlg(sid) {
  const b = SHOP.board.find(x => x.sid === sid) || {};
  const v = await formDlg(`⋯ ${b.title || "Plan"}`, [
    { k: "product", label: "Product", type: "select", options: products().map(p => [p.id, p.name]) },
    { k: "account", label: "Channel", type: "select", options: SHOP.d.accounts.map(a => [a.id, accLabel(a)]) },
    { k: "creator", label: "Creator (in the video)", type: "select", options: SHOP.d.creators.map(c => [c.id, c.name]) },
    { k: "editor", label: "Editing it", type: "select", options: SHOP.d.creators.map(c => [c.id, c.name]), none: "— nobody yet —" },
    { k: "script", label: "Script (library)", type: "select", options: SHOP.d.scripts.map(s => [s.id, s.title]), wide: true },
    { k: "tags", label: "Formats & tags", type: "tags" },
    { k: "due", label: "Due", type: "date" },
    { k: "done", label: "Finished (move to Posted)", type: "check" },
    { k: "notes", label: "Notes", type: "textarea", wide: true }], b);
  if (!v) return;
  await api(`/api/shop/plan/${sid}`, { json: { product: v.product, account: v.account, creator: v.creator, editor: v.editor, script: v.script, tags: v.tags, due: v.due, done: v.done, notes: v.notes } });
  toast("Saved"); shopRefresh();
}
$("#paneQueue").addEventListener("click", async e => {
  const w = e.target.closest("[data-who]"); if (w) { LS.set("queueWho", w.dataset.who); return renderQueue(); }
  const go = e.target.closest("[data-go]")?.dataset.go;
  if (go === "people") return listDlg("creators", "People who film", "Everyone who can be in a video or edit one. Each has a queue.");
  if (go === "assign") return newVideo({ creator: LS.get("queueWho", "") && LS.get("queueWho", "") !== "none" ? LS.get("queueWho", "") : "" });
  const card = e.target.closest(".qcard"); if (!card) return;
  const sid = card.dataset.sid, act = e.target.closest("[data-act]")?.dataset.act;
  if (act === "plan") return planDlg(sid);
  if (act === "script") return openScriptBox(sid);
  if (act === "addvid") { HD.shoot = sid; return $("#hdFiles").click(); }
  if (act === "pickup") {
    let m = me();
    if (!m) { toast("Pick who you are first (I'm …)"); $("#meSel").focus(); return; }
    await api(`/api/shop/plan/${sid}`, { json: { editor: m } }); toast(`✂ It's yours: ${byId("creators", m)?.name}`); return renderQueue();
  }
  if (act === "handoff") { await api(`/api/shop/plan/${sid}`, { json: { editor: null } }); toast("Free for anyone to pick up"); return renderQueue(); }
  if (act === "edit") return openShoot(sid);
  if (act === "review") return openReview(sid);
  if (act === "stats") { LS.set("anAcc", ""); return showHomeTab("analytics"); }
  if (!act && !e.target.closest("button,select,input")) return touchy() ? openReview(sid) : openShoot(sid);
});
$("#paneQueue").addEventListener("change", e => {
  if (e.target.id === "meSel") { LS.set("me", e.target.value); toast(e.target.value ? `Hi ${byId("creators", e.target.value)?.name}` : "OK"); }
  if (e.target.id === "qAll") { LS.set("queueAll", e.target.checked); renderQueue(); }
});

// ---------- Products & orders ----------
async function renderProducts() {
  const el = $("#paneProducts");
  const d = await shopLoad(), sm = d.summary;
  const tab = LS.get("prodTab", "products"), q = (LS.get("prodQ", "") || "").toLowerCase(), arch = LS.get("prodArch", false);
  const ordersOf = pid => d.orders.filter(o => o.product === pid);
  const ptags = {};
  for (const b of (SHOP.board.length ? SHOP.board : await api("/api/shop/board/all").then(x => (SHOP.board = x))))
    if (b.product) for (const t of b.tags || []) (ptags[b.product] ||= {})[t] = ((ptags[b.product] || {})[t] || 0) + 1;
  const orderLine = o => { const a = byId("accounts", o.account);
    const open = !["returned", "cancelled", "kept"].includes(o.status);
    const ret = o.sample === "refundable" && open && o._return_left != null ? `<span class="${o._return_left <= 2 ? "late" : o._return_left <= 7 ? "soon" : ""}">return by ${shortDate(o.return_by)} (${dleft(o._return_left)})</span>` : "";
    const due = o.video_due && open ? `<span class="${o._due_left != null && o._due_left <= 2 ? "late" : ""}">video due ${shortDate(o.video_due)}</span>` : "";
    return `<li data-order="${o.id}">${a ? accChip(a.id) : '<span class="muted">no account</span>'} ${SAMPLE[o.sample] || ""} · ${ORDER_ST[o.status] || o.status} ${ret} ${due}</li>`; };
  const head = `<div class="tbar"><span class="seg chips"><button data-ptab="products" class="${tab === "products" ? "on" : ""}">🛍 Products</button>
      <button data-ptab="orders" class="${tab === "orders" ? "on" : ""}">📦 Orders &amp; samples <span class="cnt">${d.orders.length}</span></button></span>
      ${tab === "products" ? `<input id="prodQ" placeholder="Search products" value="${esc(LS.get("prodQ", ""))}"><label class="chk"><input type="checkbox" id="prodArch" ${arch ? "checked" : ""}> archived</label>` : ""}
      <span class="spacer"></span><button data-go="order">＋ Log an order</button><button class="primary" data-go="product">＋ Product</button></div>`;
  if (tab === "orders") {
    const rank = o => ["returned", "cancelled", "kept"].includes(o.status) ? 1e6 : Math.min(o._return_left ?? 1e5, o._due_left ?? 1e5);
    const list = [...d.orders].sort((a, b) => rank(a) - rank(b));
    el.innerHTML = head + `<div class="tblWrap"><table class="tbl"><thead><tr><th>Product</th><th>Account</th><th>Kind</th><th>Status</th><th>Ordered</th><th>Delivered</th><th>Last day to return</th><th>Video due</th><th>Order #</th><th></th></tr></thead><tbody>
      ${list.map(o => { const open = !["returned", "cancelled", "kept"].includes(o.status);
        return `<tr data-order="${o.id}" class="${open ? "" : "closed"}"><td><b>${esc(prodName(o.product) || "?")}</b></td><td>${accChip(o.account)}</td><td>${SAMPLE[o.sample] || ""}</td>
        <td><select data-ost="${o.id}">${Object.entries(ORDER_ST).map(([k, l]) => `<option value="${k}" ${o.status === k ? "selected" : ""}>${l}</option>`).join("")}</select></td>
        <td>${shortDate(o.ordered)}</td><td>${shortDate(o.delivered)}</td>
        <td class="${open && o.sample === "refundable" && o._return_left != null ? (o._return_left <= 2 ? "late" : o._return_left <= 7 ? "soon" : "") : ""}">${o.return_by ? `${shortDate(o.return_by)} <span class="muted">${open ? dleft(o._return_left) : ""}</span>` : ""}</td>
        <td class="${open && o._due_left != null && o._due_left <= 2 ? "late" : ""}">${o.video_due ? `${shortDate(o.video_due)} <span class="muted">${open ? dleft(o._due_left) : ""}</span>` : ""}</td>
        <td class="mono">${esc(o.order_no)}</td><td><button data-edit-order="${o.id}">Edit</button></td></tr>`; }).join("")
        || `<tr><td colspan="10" class="muted">No orders yet. Log each sample or purchase: which account ordered it, when it arrived, and the last day it can go back.</td></tr>`}
      </tbody></table></div>`;
    return;
  }
  const list = d.products.filter(p => (arch || !p.archived) && (!q || `${p.name} ${p.brand} ${p.category}`.toLowerCase().includes(q))).sort((a, b) => a.name.localeCompare(b.name));
  el.innerHTML = head + `<div class="prodGrid">${list.map(p => { const m = sm.made[p.id] || {}, per = sm.per.products[p.id] || {}, os = ordersOf(p.id);
    const tg = Object.entries(ptags[p.id] || {}).sort((a, b) => b[1] - a[1]).map(x => x[0]);
    const nScripts = d.scripts.filter(s => s.product === p.id).length;
    return `<div class="sc prod ${p.archived ? "arch" : ""}" data-prod="${p.id}">
      <div class="pTop">${p.image ? `<img src="${esc(p.image)}" alt="" loading="lazy" onerror="this.remove()">` : `<div class="pImg">🛍</div>`}
        <div><b>${esc(p.name)}</b><div class="muted">${esc([p.brand, p.category, p.price, p.commission && p.commission + " commission"].filter(Boolean).join(" · "))}</div>
        ${p.link ? `<a href="${esc(p.link)}" target="_blank" rel="noopener" class="muted">Shop link ↗</a>` : ""}</div></div>
      <div class="kpis"><div><b>${m.videos || 0}</b><span>videos made</span></div><div><b>${per.posted || 0}</b><span>posted</span></div>
        <div><b>${num(per.views || null)}</b><span>views</span></div><div><b>${nScripts}</b><span>scripts</span></div></div>
      ${tg.length ? `<div class="qtags">${tagsRow(tg, 5)}</div>` : ""}
      ${os.length ? `<ul class="orders">${os.map(orderLine).join("")}</ul>` : `<div class="muted small">No orders logged.</div>`}
      <div class="qa"><button data-act="edit">Edit</button><button data-act="order">＋ Order</button><button data-act="scripts">📝 Scripts</button><button data-act="video" class="primary">＋ Video</button></div></div>`; }).join("")
    || `<p class="muted">No products${q ? " match" : " yet"}.</p>`}</div>`;
}
$("#paneProducts").addEventListener("click", async e => {
  const t = e.target.closest("[data-ptab]"); if (t) { LS.set("prodTab", t.dataset.ptab); return renderProducts(); }
  const go = e.target.closest("[data-go]")?.dataset.go;
  if (go === "product") return editThing("products", {});
  if (go === "order") { if (!SHOP.d.accounts.length) toast("Add the accounts first (Analytics → Accounts) so orders can say which one ordered", 5000); return editThing("orders", { sample: "free", status: "ordered", ordered: new Date().toISOString().slice(0, 10) }); }
  const eo = e.target.closest("[data-edit-order]"); if (eo) return editThing("orders", byId("orders", eo.dataset.editOrder));
  const li = e.target.closest("li[data-order]"); if (li) return editThing("orders", byId("orders", li.dataset.order));
  const card = e.target.closest("[data-prod]"); if (!card) return;
  const p = byId("products", card.dataset.prod), act = e.target.closest("[data-act]")?.dataset.act;
  if (act === "edit") return editThing("products", p);
  if (act === "order") return editThing("orders", { product: p.id, sample: "free", status: "ordered", ordered: new Date().toISOString().slice(0, 10) });
  if (act === "video") return newVideo({ product: p.id });
  if (act === "scripts") { LS.set("libTab", "scripts"); LS.set("libProd", p.id); return showHomeTab("library"); }
});
$("#paneProducts").addEventListener("input", e => {
  if (e.target.id === "prodQ") { LS.set("prodQ", e.target.value); clearTimeout(renderProducts.t); renderProducts.t = setTimeout(async () => { await renderProducts(); const i = $("#prodQ"); i.focus(); i.setSelectionRange(i.value.length, i.value.length); }, 250); }
});
$("#paneProducts").addEventListener("change", async e => {
  if (e.target.id === "prodArch") { LS.set("prodArch", e.target.checked); return renderProducts(); }
  if (e.target.dataset.ost) { const o = byId("orders", e.target.dataset.ost); await api("/api/shop/orders", { json: { ...o, status: e.target.value } }); toast("Saved"); renderProducts(); }
});

// ---------- Analytics ----------
function spark(series) {
  if (!series || series.length < 2) return "";
  const ys = series.map(x => x[1]), lo = Math.min(...ys), hi = Math.max(...ys), w = 160, h = 34;
  const pts = ys.map((y, i) => `${(i / (ys.length - 1) * w).toFixed(1)},${(h - 3 - (hi === lo ? 0.5 : (y - lo) / (hi - lo)) * (h - 6)).toFixed(1)}`).join(" ");
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}"><polyline points="${pts}" fill="none" stroke="currentColor" stroke-width="2"/></svg>`;
}
function perfTable(rows, label, cell, empty) {
  const top = Math.max(1, ...rows.map(r => r.avg_views || 0));
  return `<div class="tblWrap"><table class="tbl perf"><thead><tr><th>${label}</th><th>Videos</th><th>Avg views</th><th></th><th>Engagement</th><th>Best</th></tr></thead><tbody>
    ${rows.map(r => `<tr><td>${cell(r.id)}</td><td>${r.videos}${r.tracked < r.videos ? ` <span class="muted" title="videos with a TikTok link">(${r.tracked} linked)</span>` : ""}</td>
      <td><b>${num(r.avg_views)}</b></td><td class="barc"><i style="width:${Math.round(100 * (r.avg_views || 0) / top)}%"></i></td>
      <td>${r.eng != null ? r.eng + "%" : "–"}</td><td>${r.best?.url ? `<a href="${esc(r.best.url)}" target="_blank" rel="noopener">${num(r.best.views)} ↗</a>` : ""}</td></tr>`).join("")
    || `<tr><td colspan="6" class="muted">${empty}</td></tr>`}</tbody></table></div>`;
}
async function renderAnalytics() {
  const el = $("#paneAnalytics");
  const d = await shopLoad();
  let acc = LS.get("anAcc", ""); if (acc && !byId("accounts", acc)) acc = "";
  const an = SHOP.an = await api(`/api/shop/analytics/view?account=${acc}`);
  const t = an.totals, a = byId("accounts", acc), st = an.status;
  const scopeName = a ? a.name : "All accounts";
  el.innerHTML = `<div class="tbar"><span class="seg chips"><button data-acc="" class="${acc ? "" : "on"}">All accounts</button>
      ${d.accounts.map(x => `<button data-acc="${x.id}" class="${acc === x.id ? "on" : ""}" style="--c:${esc(x.color)}"><span class="dot"></span>${esc(x.name)}</button>`).join("")}</span>
      <button data-go="accounts">⚙ Accounts</button><span class="spacer"></span>
      <span class="muted">${st.running ? `checking TikTok… ${esc(st.msg || "")}` : `updated ${ago(st.last)}`}</span><button data-go="refresh" ${st.running ? "disabled" : ""} title="Read the public numbers now (one page at a time)">↻ Check now</button></div>
    ${!d.accounts.length ? `<div class="sc setup"><b>Add the accounts he manages</b><p class="muted">Each account's public TikTok page gives followers and likes; each posted video's link gives its views, likes, comments, shares and saves. No logins needed, and no passwords are kept.</p><button class="primary" data-go="accounts">＋ Add accounts</button></div>` : ""}
    ${a ? `<div class="sc accHead" style="--c:${esc(a.color)}"><span class="dot"></span><b>${esc(a.name)}</b>
        ${a.handle ? `<a href="https://www.tiktok.com/@${esc(a.handle.replace(/^@/, ""))}" target="_blank" rel="noopener">@${esc(a.handle.replace(/^@/, ""))} ↗</a>` : '<span class="muted">no handle: add one to read its numbers</span>'}
        ${a.email ? `<span class="muted">· signs in with ${esc(LOGIN[a.login] || a.login || "email")}: ${esc(a.email)}</span>` : ""} ${a.creator ? `· usually ${who(a.creator)}` : ""}
        <span class="spacer"></span>${spark(an.accounts[a.id]?.series)}<button data-edit-acc="${a.id}">Edit</button>
        ${a.notes ? `<div class="muted wide">${esc(a.notes)}</div>` : ""}${an.accounts[a.id]?.error ? `<div class="warnx wide">⚠ ${esc(an.accounts[a.id].error)}</div>` : ""}</div>` : ""}
    <div class="kpiRow">
      <div class="sc skpi"><span>Followers</span><b>${num(t.followers || null)}</b><em>${plus(t.followers_week)} this week</em></div>
      <div class="sc skpi"><span>Views</span><b>${num(t.views)}</b><em>${plus(t.week_views)} this week</em></div>
      <div class="sc skpi"><span>Videos posted</span><b>${t.videos}</b><em>${t.tracked} with a link</em></div>
      <div class="sc skpi"><span>Engagement</span><b>${t.eng != null ? t.eng + "%" : "–"}</b><em>likes+comments+shares+saves ÷ views</em></div>
      <div class="sc skpi"><span>Likes · Shares</span><b>${num(t.likes)} · ${num(t.shares)}</b><em>${num(t.saves)} saves</em></div></div>
    ${an.untracked.length ? `<div class="sc"><b>${an.untracked.length} posted video${an.untracked.length === 1 ? " has" : "s have"} no TikTok link yet</b> <span class="muted">paste each one's link to see how it does</span>
      <ul class="untracked">${an.untracked.slice(0, 12).map(u => `<li>${esc(u.title)} · video ${u.n} <button data-link="${u.sid}|${u.n}">Add link</button></li>`).join("")}</ul></div>` : ""}
    ${!acc && d.accounts.length ? `<h3 class="secHead">By account</h3><div class="tblWrap"><table class="tbl"><thead><tr><th>Account</th><th>Followers</th><th>This week</th><th>Posted here</th><th>Avg views</th><th>Engagement</th><th></th></tr></thead><tbody>
      ${d.accounts.map(x => { const n = an.accounts[x.id] || {}, p = an.per_account.find(r => r.id === x.id) || {};
        return `<tr><td>${accChip(x.id)}</td><td><b>${num(n.followers)}</b></td><td>${plus(n.week?.followers) || "–"}</td><td>${p.videos || 0}</td><td>${num(p.avg_views)}</td><td>${p.eng != null ? p.eng + "%" : "–"}</td><td>${spark(n.series)}</td></tr>`; }).join("")}</tbody></table></div>` : ""}
    <h3 class="secHead">Top videos · ${esc(scopeName)}</h3>
    <div class="topVids">${an.top.map(p => `<a class="tv sc" href="${esc(p.url)}" target="_blank" rel="noopener">
        ${p.video_id ? `<img src="/api/shop/cover/${p.video_id}.jpg" alt="" loading="lazy" onerror="this.replaceWith(Object.assign(document.createElement('div'),{className:'noimg'}))">` : '<div class="noimg"></div>'}
        <div><b>${num(p.stats.views)}</b> views · ${p.eng}%<div class="muted">${esc(p.title)}${p.n ? " · " + p.n : ""}</div>
        <div class="qm">${accChip(p.account)} ${p.product ? "🛍 " + esc(prodName(p.product)) : ""}</div><div class="qtags">${tagsRow(p.tags, 3)}</div></div></a>`).join("")
      || `<p class="muted">No numbers yet. Mark videos posted (Posting tab or Review) and paste their TikTok links; numbers are read every few hours.</p>`}</div>
    ${!acc ? `<h3 class="secHead">Products × channels <span class="muted">avg views per video (videos)</span></h3>${matrixTable(an, d)}` : `<h3 class="secHead">Products on this account</h3>${perfTable(an.products, "Product", id => esc(prodName(id) || "?"), "No posted videos with a product yet.")}`}
    <h3 class="secHead">Scripts</h3>${perfTable(an.scripts, "Script", id => esc(byId("scripts", id)?.title || "?"), "Videos made from a library script show up here.")}
    <h3 class="secHead">Formats &amp; tags</h3>${perfTable(an.tags, "Tag", id => tagChip(id), "Tag videos (New video → Style, or ⋯ on a queue card) to compare formats.")}
    <h3 class="secHead">Creators</h3>${perfTable(an.creators, "Creator", id => who(id), "Set who's in each video to compare.")}
    <div class="sc trackBox"><b>Track a video made elsewhere</b> <span class="muted">it counts toward the account's numbers</span>
      <div class="row"><input id="trackUrl" type="url" placeholder="https://www.tiktok.com/@…/video/…"><select id="trackAcc">${opts(d.accounts, acc, accLabel, "— account —")}</select><button data-go="track">Track</button></div></div>`;
}
function matrixTable(an, d) {
  const accs = d.accounts, prods = Object.keys(an.matrix);
  if (!prods.length || !accs.length) return `<p class="muted">Shows which product does best on which account once posted videos have an account, a product and a link.</p>`;
  const top = Math.max(1, ...prods.flatMap(p => accs.map(a => { const c = an.matrix[p][a.id]; return c?.tracked ? c.views / c.tracked : 0; })));
  return `<div class="tblWrap"><table class="tbl matrix"><thead><tr><th>Product</th>${accs.map(a => `<th>${accChip(a.id)}</th>`).join("")}</tr></thead><tbody>
    ${prods.map(p => `<tr><td><b>${esc(prodName(p) || "?")}</b></td>${accs.map(a => { const c = an.matrix[p][a.id]; if (!c) return "<td></td>";
      const avg = c.tracked ? Math.round(c.views / c.tracked) : null;
      return `<td style="--k:${avg ? (0.12 + 0.6 * avg / top).toFixed(2) : 0}"><b>${num(avg)}</b> <span class="muted">(${c.videos})</span></td>`; }).join("")}</tr>`).join("")}</tbody></table></div>`;
}
$("#paneAnalytics").addEventListener("click", async e => {
  const a = e.target.closest("[data-acc]"); if (a) { LS.set("anAcc", a.dataset.acc); return renderAnalytics(); }
  const ea = e.target.closest("[data-edit-acc]"); if (ea) return editThing("accounts", byId("accounts", ea.dataset.editAcc));
  const ln = e.target.closest("[data-link]"); if (ln) { const [sid, n] = ln.dataset.link.split("|"); return postDialog(sid, +n); }
  const go = e.target.closest("[data-go]")?.dataset.go;
  if (go === "accounts") return listDlg("accounts", "TikTok accounts", "The accounts he runs. Handle = for the public numbers; login email = which login it is. No passwords.");
  if (go === "refresh") { await api("/api/shop/analytics/refresh", { json: {} }); toast("Checking TikTok, one page at a time…"); setTimeout(renderAnalytics, 1500); setTimeout(renderAnalytics, 20000); return; }
  if (go === "track") {
    const url = $("#trackUrl").value.trim(); if (!url) return;
    try { const r = await api("/api/shop/analytics/track", { json: { url, account: $("#trackAcc").value || null } }); toast("Tracking: " + (r.desc || r.video_id).slice(0, 60)); renderAnalytics(); }
    catch (err) { toast(err.message, 6000); }
  }
});

// ---------- Library: scripts + formats & tags ----------
async function renderLibrary() {
  const el = $("#paneLibrary");
  const d = await shopLoad(), sm = d.summary;
  const tab = LS.get("libTab", "scripts"), q = (LS.get("libQ", "") || "").toLowerCase(), prod = LS.get("libProd", "");
  const head = `<div class="tbar"><span class="seg chips"><button data-ltab="scripts" class="${tab === "scripts" ? "on" : ""}">📝 Scripts <span class="cnt">${d.scripts.length}</span></button>
      <button data-ltab="tags" class="${tab === "tags" ? "on" : ""}">🏷 Formats &amp; tags <span class="cnt">${d.tags.length}</span></button></span>
      ${tab === "scripts" ? `<input id="libQ" placeholder="Search scripts" value="${esc(LS.get("libQ", ""))}"><select id="libProd">${opts(products(), prod, p => p.name, "Any product")}</select>` : ""}
      <span class="spacer"></span><button class="primary" data-go="${tab === "scripts" ? "script" : "tag"}">＋ ${tab === "scripts" ? "Script" : "Tag"}</button></div>`;
  if (tab === "tags") {
    el.innerHTML = head + `<p class="muted">Tags describe a video's format, hook, style and tone. Pick them on a new video; Analytics compares how each one does. Hover a tag anywhere to see what it means.</p>` +
      allGroups().map(g => { const ts = d.tags.filter(t => t.group === g).sort((a, b) => a.name.localeCompare(b.name));
        return ts.length ? `<h3 class="secHead">${esc(g)}</h3><div class="tagList">${ts.map(t => { const p = sm.per.tags[t.id] || {};
          return `<div class="tagRow" data-tagedit="${t.id}">${tagChip(t.id)}<span class="tdesc">${esc(t.description)}</span>
            <span class="muted tnum">${p.videos ? `${p.videos} video${p.videos === 1 ? "" : "s"}${p.avg_views != null ? ` · ${num(p.avg_views)} avg views` : ""}` : ""}</span><button data-tagedit="${t.id}">Edit</button></div>`; }).join("")}</div>` : ""; }).join("");
    return;
  }
  const list = d.scripts.filter(s => (!prod || s.product === prod || !s.product) && (!q || `${s.title} ${s.text}`.toLowerCase().includes(q)))
    .sort((a, b) => (b.updated || 0) - (a.updated || 0));
  el.innerHTML = head + `<p class="muted">Scripts with <code>{product}</code>, <code>{brand}</code>, <code>{price}</code> or your own <code>{fill-ins}</code> work for any product: they're filled in when you make a video. Rows from the Scripts &amp; Links sheet land here too.</p>
    <div class="scriptGrid">${list.map(s => { const p = sm.per.scripts[s.id] || {}, used = sm.scripts_used[s.id] || 0;
      const lines = s.text.split("\n").filter(l => l.trim());
      return `<div class="sc script" data-script="${s.id}"><div class="qt"><b>${esc(s.title)}</b>${s.product ? `<span class="muted">🛍 ${esc(prodName(s.product))}</span>` : `<span class="muted">any product</span>`}</div>
        <div class="stext">${lines.slice(0, 4).map(l => `<div>${esc(l).replace(/\{([^}]+)\}/g, '<code>{$1}</code>').replace(/\[([^\]]+)\]/g, '<i class="muted">[$1]</i>')}</div>`).join("")}${lines.length > 4 ? `<div class="muted">+${lines.length - 4} more lines</div>` : ""}</div>
        ${s.tags?.length ? `<div class="qtags">${tagsRow(s.tags, 5)}</div>` : ""}
        <div class="qm muted">${used} shoot${used === 1 ? "" : "s"} · ${p.posted || 0} posted${p.avg_views != null ? ` · ${num(p.avg_views)} avg views` : ""}${s.from_shoot && !s.edited ? " · from the sheet" : ""}</div>
        <div class="qa"><button data-act="edit">Edit</button><button data-act="copy">⧉ Copy</button><button data-act="video" class="primary">＋ Video from this</button></div></div>`; }).join("")
      || `<p class="muted">No scripts${q || prod ? " match" : " yet"}.</p>`}</div>`;
}
$("#paneLibrary").addEventListener("click", async e => {
  const t = e.target.closest("[data-ltab]"); if (t) { LS.set("libTab", t.dataset.ltab); return renderLibrary(); }
  const go = e.target.closest("[data-go]")?.dataset.go;
  if (go === "script") return editThing("scripts", { product: LS.get("libProd", "") || null, tags: [] });
  if (go === "tag") return editThing("tags", { group: "Format" });
  const te = e.target.closest("[data-tagedit]"); if (te) return editThing("tags", byId("tags", te.dataset.tagedit));
  const card = e.target.closest("[data-script]"); if (!card) return;
  const s = byId("scripts", card.dataset.script), act = e.target.closest("[data-act]")?.dataset.act;
  if (act === "edit" || (!act && !e.target.closest("button,a"))) return editThing("scripts", s);
  if (act === "copy") return copyText(s.text, "script");
  if (act === "video") return newVideo({ script: s.id, product: s.product, tags: s.tags });
});
$("#paneLibrary").addEventListener("input", e => {
  if (e.target.id === "libQ") { LS.set("libQ", e.target.value); clearTimeout(renderLibrary.t); renderLibrary.t = setTimeout(async () => { await renderLibrary(); const i = $("#libQ"); i.focus(); i.setSelectionRange(i.value.length, i.value.length); }, 250); }
});
$("#paneLibrary").addEventListener("change", e => { if (e.target.id === "libProd") { LS.set("libProd", e.target.value); renderLibrary(); } });

const PANES = { overview: renderOverview, queue: renderQueue, products: renderProducts, analytics: renderAnalytics, library: renderLibrary };
$("#newVideoBtn").onclick = () => newVideo();
// the Queue keeps up with uploads / pre-cuts finishing
setInterval(() => { if (!$("#home").hidden && LS.get("homeTab", "overview") === "queue" && !document.querySelector("dialog[open]")) renderQueue().catch(() => { }); }, 15000);
