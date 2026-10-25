/* Interface language. English is what the code is written in; Portuguese (Brazil) comes from
   i18n-pt.js. Text is translated as it appears on screen: a whole UI string first, then known
   pieces inside longer text (numbers and names stay), plus title/placeholder hints, toasts and
   confirm boxes. Anything marked translate="no" (scripts, captions, names, tags: the videos are
   for TikTok Shop US, so content stays English) is left alone. The 🌐 button switches. */
"use strict";
(function () {
  const saved = (() => { try { return JSON.parse(localStorage.getItem("ad_lang")); } catch (e) { return null; } })();
  const lang = saved || (/^pt/i.test(navigator.language || "") ? "pt" : "en");
  window.LANG = lang;
  document.documentElement.lang = lang === "pt" ? "pt-BR" : "en";
  window.setLang = l => { try { localStorage.setItem("ad_lang", JSON.stringify(l)); } catch (e) { } location.reload(); };
  window.tr = s => s;
  if (lang !== "pt" || !window.I18N_PT) return;

  const D = window.I18N_PT.exact;
  const PAT = window.I18N_PT.patterns.map(([r, s]) => [new RegExp(r, "g"), s]);
  const reEsc = s => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  // pieces that can sit inside longer text: several words, or punctuation, or a long word
  const frags = Object.keys(D).filter(k => k.length >= 4 && (/[\s·:;,.()“”"…→]/.test(k) || k.length >= 8))
    .sort((a, b) => b.length - a.length);
  const FR = frags.length ? new RegExp("(?<![A-Za-zÀ-ÿ])(?:" + frags.map(reEsc).join("|") + ")(?![A-Za-zÀ-ÿ])", "g") : null;

  function tr(s) {
    if (s == null) return s;
    s = String(s);
    if (!/[A-Za-z]{2}/.test(s)) return s;
    const t = s.trim();
    const hit = D[t] ?? D[t.replace(/\s+/g, " ")];
    if (hit != null) return s.replace(t, hit);
    let out = FR ? s.replace(FR, m => D[m] ?? m) : s;
    for (const [r, rep] of PAT) out = out.replace(r, rep);
    return out;
  }
  window.tr = tr;

  const SKIP = "script,style,textarea,code,[translate=no],.notranslate";
  const ATTRS = ["title", "placeholder", "aria-label", "data-tip"];
  function attrs(el) {
    if (el.closest("[translate=no]")) return;
    for (const a of ATTRS) {
      const v = el.getAttribute(a);
      if (v && (a !== "data-tip" || el.closest("dialog,.sbDlg") === null || true)) {
        const t = tr(v);
        if (t !== v) el.setAttribute(a, t);
      }
    }
  }
  function text(n) {
    const p = n.parentElement;
    if (!p || p.closest(SKIP)) return;
    const v = n.nodeValue, t = tr(v);
    if (t !== v) n.nodeValue = t;
  }
  function walk(root) {
    if (root.nodeType === 3) return text(root);
    if (root.nodeType !== 1) return;
    if (root.matches?.("[title],[placeholder],[aria-label]")) attrs(root);
    root.querySelectorAll?.("[title],[placeholder],[aria-label]").forEach(attrs);
    if (root.closest?.(SKIP)) return;
    const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    for (let n = w.nextNode(); n; n = w.nextNode()) text(n);
  }
  const go = () => {
    walk(document.body);
    new MutationObserver(ms => {
      for (const m of ms) {
        if (m.type === "characterData") text(m.target);
        else if (m.type === "attributes") attrs(m.target);
        else m.addedNodes.forEach(walk);
      }
    }).observe(document.body, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ["title", "placeholder", "aria-label"] });
  };
  if (document.body) go(); else document.addEventListener("DOMContentLoaded", go);
  const A = window.alert.bind(window), C = window.confirm.bind(window), P = window.prompt.bind(window);
  window.alert = m => A(tr(m));
  window.confirm = m => C(tr(m));
  window.prompt = (m, d) => P(tr(m), d);
})();
