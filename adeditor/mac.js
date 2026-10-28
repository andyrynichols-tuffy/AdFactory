/* macOS look (mac.css): labels read like a Mac app, so the decorative emoji in front of button labels,
   headings and table headers are dropped as the page renders. A button that is only an emoji keeps it,
   and anything marked translate="no" (names, scripts, captions: user content) is left alone. */
"use strict";
(function () {
  const LEAD = /^\s*(?:[\p{Extended_Pictographic}\u{1F1E6}-\u{1F1FF}][\u{FE0F}\u{200D}\p{Extended_Pictographic}]*\s*)+/u;
  const SEL = "button, h1, h2, h3, h4, th, summary, .secHead, .skpi span, .tbar b, dialog label";
  function clean(n) {
    const p = n.parentElement;
    if (!p || p.closest("[translate=no], textarea, input, #work, #bottom") || !p.closest(SEL)) return;
    const v = n.nodeValue, t = v.replace(LEAD, "");
    if (t !== v && t.trim()) n.nodeValue = (v.match(/^\s*/)[0]) + t;
  }
  function walk(root) {
    if (root.nodeType === 3) return clean(root);
    if (root.nodeType !== 1) return;
    const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    for (let n = w.nextNode(); n; n = w.nextNode()) clean(n);
  }
  const go = () => {
    walk(document.body);
    new MutationObserver(ms => { for (const m of ms) m.type === "characterData" ? clean(m.target) : m.addedNodes.forEach(walk); })
      .observe(document.body, { childList: true, subtree: true, characterData: true });
  };
  if (document.body) go(); else document.addEventListener("DOMContentLoaded", go);
})();
