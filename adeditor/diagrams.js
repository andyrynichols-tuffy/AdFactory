/* Set-up and lighting diagrams for the shoot page (user, 2026-10-27): simple sketches of where the phone,
   the key light (the big circle) and the two fill panels (rectangles) go for each format, seen from above,
   plus a side view where height matters (flat lays shot straight down). Drawn in SVG with the page's colours. */
"use strict";
const DG = (() => {
  const C = { line: "rgba(255,255,255,.28)", faint: "rgba(255,255,255,.12)", text: "rgba(255,255,255,.75)", dim: "rgba(255,255,255,.45)",
    key: "#ffd60a", fill: "#64d2ff", item: "#bf5af2", phone: "#ffffff", tape: "#ff9f0a" };
  const T = (x, y, s, o = {}) => `<text x="${x}" y="${y}" fill="${o.c || C.text}" font-size="${o.size || 11}" font-weight="${o.w || 500}" text-anchor="${o.a || "middle"}">${s}</text>`;
  const beam = (x1, y1, x2, y2, c) => `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="${c}" stroke-width="1.2" stroke-dasharray="3 4" opacity=".7"/>`;
  const key = (x, y, label, tx, ty) => `${beam(x, y, tx, ty, C.key)}<circle cx="${x}" cy="${y}" r="17" fill="${C.key}" fill-opacity=".22" stroke="${C.key}" stroke-width="2"/>
    <circle cx="${x}" cy="${y}" r="6" fill="${C.key}"/>${T(x, y + 31, label, { c: C.key })}`;
  // a panel faces what it lights: its broad side turned to the target (the lit face drawn bright), like a real one
  const panel = (x, y, _deg, label, tx, ty, off) => {
    const rot = Math.atan2(ty - y, tx - x) * 180 / Math.PI - 90;   // local +y = toward the target
    return `${off ? "" : beam(x, y, tx, ty, C.fill)}<g transform="translate(${x} ${y}) rotate(${rot.toFixed(1)})">
      <rect x="-17" y="-6" width="34" height="12" rx="2" fill="${C.fill}" fill-opacity="${off ? 0 : .16}" stroke="${C.fill}" stroke-width="1.6" ${off ? 'stroke-dasharray="3 3"' : ""}/>
      ${off ? "" : `<line x1="-15" y1="6" x2="15" y2="6" stroke="#fff" stroke-width="3" stroke-linecap="round"/>`}</g>${T(x, y + 26, label, { c: C.fill })}`;
  };
  const phone = (x, y, deg, label, fov = true) => `<g transform="translate(${x} ${y}) rotate(${deg})">${fov ? `<path d="M0 -8 L-34 -70 L34 -70 Z" fill="#fff" fill-opacity=".05" stroke="${C.faint}"/>` : ""}
    <rect x="-7" y="-12" width="14" height="24" rx="3" fill="#1c1c1e" stroke="${C.phone}" stroke-width="1.6"/><circle cx="0" cy="-6" r="2" fill="${C.phone}"/></g>${T(x, y + 26, label)}`;
  const person = (x, y, label) => `<ellipse cx="${x}" cy="${y}" rx="22" ry="13" fill="${C.item}" fill-opacity=".25" stroke="${C.item}" stroke-width="2"/>
    <circle cx="${x}" cy="${y}" r="8" fill="${C.item}" fill-opacity=".6"/>${T(x, y + 28, label, { c: C.item })}`;
  const svg = (w, h, body, title) => `<figure class="mxDiagram"><svg viewBox="0 0 ${w} ${h}" role="img" aria-label="${title}">${body}</svg><figcaption>${title}</figcaption></figure>`;

  // ---------- lighting, seen from above ----------
  const LIGHT = {
    carousel: () => svg(360, 250, `
      <rect x="110" y="70" width="140" height="110" rx="4" fill="none" stroke="${C.tape}" stroke-dasharray="6 5" stroke-width="1.6"/>
      ${T(180, 64, "tape mark", { c: C.tape, size: 10 })}
      <rect x="150" y="98" width="60" height="54" rx="6" fill="${C.item}" fill-opacity=".3" stroke="${C.item}" stroke-width="2"/>${T(180, 129, "item", { c: C.item })}
      ${key(70, 70, "Key ~70%, high", 150, 110)}${panel(300, 178, -30, "Fill 1 ~30%, low", 210, 140)}${panel(300, 60, 30, "Fill 2 off / low", 240, 80, true)}
      ${phone(180, 125, 0, "", false)}${T(180, 240, "phone straight above the item (see side view)", { c: C.dim, size: 10 })}`, "Lights, from above"),
    flatlay_vo: () => svg(360, 250, `
      <rect x="95" y="40" width="170" height="150" rx="10" fill="#fff" fill-opacity=".06" stroke="${C.line}"/>${T(180, 34, "white bed", { c: C.dim, size: 10 })}
      <rect x="150" y="90" width="60" height="50" rx="6" fill="${C.item}" fill-opacity=".3" stroke="${C.item}" stroke-width="2"/>${T(180, 120, "item", { c: C.item })}
      ${key(45, 80, "Key ~60%", 150, 105)}${panel(320, 140, -90, "Fill 1 ~30%", 210, 120)}${panel(180, 20, 0, "Fill 2 low", 180, 90)}
      ${phone(180, 222, 0, "phone at the foot, angled down")}`, "Lights, from above"),
    worn: () => svg(360, 260, `
      <line x1="40" y1="40" x2="320" y2="40" stroke="${C.line}" stroke-width="3"/>${T(180, 30, "plain wall (no window behind)", { c: C.dim, size: 10 })}
      ${person(180, 105, "you, on the tape mark")}
      ${key(70, 175, "Key ~70%, chest height", 172, 112)}${panel(290, 175, -45, "Fill 1 ~35%", 190, 112)}${panel(280, 62, 120, "Fill 2 low (rim)", 195, 98)}
      ${phone(180, 232, 0, "phone on tripod, waist height")}`, "Lights, from above"),
    held: () => svg(360, 230, `
      <rect x="150" y="70" width="60" height="44" rx="6" fill="${C.item}" fill-opacity=".3" stroke="${C.item}" stroke-width="2"/>${T(180, 97, "item in hand", { c: C.item })}
      ${key(70, 92, "Key ~50%, low + close", 148, 92)}${panel(295, 92, 90, "Fill 1 ~20%", 212, 92)}${panel(180, 30, 0, "Fill 2 off", 180, 70, true)}
      ${phone(180, 192, 0, "phone in front")}`, "Lights, from above"),
    skit: () => svg(360, 250, `
      ${person(140, 90, "A")}${person(220, 90, "B")}
      ${key(180, 172, "Key ~70%", 180, 105)}${panel(75, 160, 45, "Fill ~35%", 132, 104)}${panel(285, 160, -45, "Fill ~35%", 228, 104)}
      ${phone(180, 222, 0, "phone in front")}${T(180, 20, "outside: no lights, open shade, both facing the light", { c: C.dim, size: 10 })}`, "Lights indoors, from above"),
    other: () => svg(360, 220, `${person(180, 90, "subject")}${key(80, 150, "Key ~70%", 172, 96)}${panel(280, 150, -45, "Fill ~35%", 190, 96)}
      ${panel(270, 40, 120, "Fill 2 rim / off", 195, 84)}${phone(180, 195, 0, "phone")}`, "Lights, from above"),
  };

  // ---------- set up: what goes where (and, for flat lays, the height) ----------
  const SETUP = {
    carousel: () => svg(360, 250, `
      <line x1="30" y1="215" x2="330" y2="215" stroke="${C.line}" stroke-width="2"/>${T(180, 236, "wood floor", { c: C.dim, size: 10 })}
      <rect x="140" y="204" width="80" height="10" rx="3" fill="${C.item}" fill-opacity=".5"/>${T(180, 198, "item + outfit, laid flat", { c: C.item, size: 10 })}
      <rect x="171" y="60" width="18" height="30" rx="4" fill="#1c1c1e" stroke="${C.phone}" stroke-width="1.6"/>
      <path d="M172 92 L130 200 M188 92 L230 200" stroke="${C.faint}"/>${T(225, 75, "phone straight down,", { a: "start", size: 10 })}${T(225, 89, "parallel to the floor", { a: "start", size: 10 })}
      <line x1="120" y1="75" x2="120" y2="205" stroke="${C.dim}" marker-end="url(#a)"/>${T(110, 145, "arm's length", { a: "end", size: 10, c: C.dim })}
      ${key(60, 45, "Key high, 45° down", 150, 205)}
      <defs><marker id="a" markerWidth="6" markerHeight="6" refX="3" refY="3" orient="auto"><path d="M0 0 L6 3 L0 6 Z" fill="${C.dim}"/></marker></defs>`, "Side view: height and angle")
,
    flatlay_vo: () => svg(360, 230, `
      <rect x="40" y="150" width="280" height="40" rx="8" fill="#fff" fill-opacity=".06" stroke="${C.line}"/>${T(180, 210, "bed", { c: C.dim, size: 10 })}
      <rect x="140" y="140" width="80" height="10" rx="3" fill="${C.item}" fill-opacity=".5"/>${T(180, 132, "item, smoothed flat", { c: C.item, size: 10 })}
      <rect x="290" y="55" width="16" height="28" rx="4" fill="#1c1c1e" stroke="${C.phone}" stroke-width="1.6" transform="rotate(-35 298 69)"/>
      <path d="M286 80 L170 142 M300 88 L235 145" stroke="${C.faint}"/>${T(300, 40, "phone over the foot,", { size: 10 })}${T(300, 53, "tilted down ~45°", { size: 10 })}
      ${T(110, 70, "your hand points at", { size: 10, c: C.dim })}${T(110, 84, "each detail as you say it", { size: 10, c: C.dim })}`, "Side view"),
    worn: () => svg(360, 230, `
      <line x1="40" y1="200" x2="320" y2="200" stroke="${C.line}" stroke-width="2"/>
      <rect x="230" y="40" width="14" height="160" rx="4" fill="#fff" fill-opacity=".08" stroke="${C.line}"/>${T(237, 30, "you", { c: C.item })}
      <rect x="226" y="110" width="22" height="90" rx="6" fill="${C.item}" fill-opacity=".35" stroke="${C.item}"/>${T(275, 160, "frame: waist down", { a: "start", size: 10, c: C.item })}
      <line x1="90" y1="200" x2="90" y2="125" stroke="${C.line}" stroke-width="2"/><rect x="82" y="105" width="16" height="26" rx="4" fill="#1c1c1e" stroke="${C.phone}" stroke-width="1.6"/>
      <path d="M98 112 L226 105 M98 124 L226 200" stroke="${C.faint}"/>${T(90, 218, "tripod, phone at waist height, about 6 ft away", { a: "start", size: 10, c: C.dim })}`, "Side view"),
    held: () => svg(360, 200, `
      <rect x="220" y="70" width="60" height="50" rx="8" fill="${C.item}" fill-opacity=".3" stroke="${C.item}" stroke-width="2"/>${T(250, 100, "item", { c: C.item })}
      <rect x="80" y="80" width="16" height="28" rx="4" fill="#1c1c1e" stroke="${C.phone}" stroke-width="1.6"/>
      <path d="M96 88 L220 70 M96 100 L220 120" stroke="${C.faint}"/>${T(160, 150, "close: the item fills most of the frame,", { size: 10 })}${T(160, 164, "plain background behind it", { size: 10, c: C.dim })}`, "Side view"),
    skit: () => svg(360, 200, `${person(140, 70, "A")}${person(220, 70, "B")}
      <rect x="172" y="150" width="16" height="28" rx="4" fill="#1c1c1e" stroke="${C.phone}" stroke-width="1.6"/>
      <path d="M176 150 L110 60 M184 150 L250 60" stroke="${C.faint}"/>${T(180, 194, "phone on tripod; both of you in frame, the outfit visible", { size: 10, c: C.dim })}`, "From above"),
  };
  return { light: f => (LIGHT[f] || LIGHT.other)(), setup: f => SETUP[f] ? SETUP[f]() : "" };
})();
