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

// the language picker lives at the bottom of the sidebar (no title bar on the main screens)
(function () {
  const move = () => { const lp = document.querySelector("#topbar .langPick"), sheet = document.getElementById("sheetChip");
    if (lp && sheet) sheet.before(lp); };
  if (document.readyState !== "loading") move(); else document.addEventListener("DOMContentLoaded", move);
})();

// collapsible sidebar (remembered on this device)
(function () {
  const set = on => {
    document.getElementById("home")?.classList.toggle("sideCollapsed", on);
    const b = document.getElementById("sideToggle");
    if (b) b.title = b.ariaLabel = on ? "Show the sidebar" : "Hide the sidebar";
    try { localStorage.setItem("sideCollapsed", on ? "1" : ""); } catch (e) { }
  };
  const init = () => {
    let on = false; try { on = !!localStorage.getItem("sideCollapsed"); } catch (e) { }
    set(on);
    document.getElementById("sideToggle")?.addEventListener("click", () => set(!document.getElementById("home").classList.contains("sideCollapsed")));
  };
  if (document.readyState !== "loading") init(); else document.addEventListener("DOMContentLoaded", init);
})();

// photos open in a viewer over the page, never in place of the app (data-lb = a group to step through);
// links to other sites always open in a new tab (the Ad Factory window sends them to the browser)
(function () {
  let box = null, list = [], at = 0;
  const show = () => { box.querySelector("img").src = list[at]; box.querySelector(".lbN").textContent = `${at + 1} / ${list.length}`; };
  const close = () => { box?.remove(); box = null; };
  document.addEventListener("click", e => {
    const a = e.target.closest?.("a[data-lb]");
    if (a) {
      e.preventDefault();
      list = [...document.querySelectorAll(`a[data-lb="${a.dataset.lb}"]`)].map(x => x.href);
      at = Math.max(0, list.indexOf(a.href));
      box = document.createElement("div");
      box.className = "lightbox";
      box.innerHTML = `<button class="lbX" aria-label="Close">✕</button><button class="lbP" aria-label="Previous">‹</button><img alt=""><button class="lbNx" aria-label="Next">›</button><span class="lbN"></span>`;
      box.onclick = ev => {
        if (ev.target.closest(".lbP")) { at = (at - 1 + list.length) % list.length; return show(); }
        if (ev.target.closest(".lbNx")) { at = (at + 1) % list.length; return show(); }
        if (ev.target === box || ev.target.closest(".lbX")) close();
      };
      document.body.appendChild(box);
      show();
      return;
    }
    const ext = e.target.closest?.("a[href^='http']");
    if (ext && new URL(ext.href).host !== location.host && ext.target !== "_blank") { ext.target = "_blank"; ext.rel = "noopener"; }
  }, true);
  document.addEventListener("keydown", e => {
    if (!box) return;
    if (e.key === "Escape") close();
    if (e.key === "ArrowLeft") { at = (at - 1 + list.length) % list.length; show(); }
    if (e.key === "ArrowRight") { at = (at + 1) % list.length; show(); }
  });
})();
