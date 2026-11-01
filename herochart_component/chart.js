// A page's hero: one main chart with the facts that explain it on both sides, tied to their points by
// leader lines, and thin "linked" strips from the neighbouring stages of the loop on the same time axis.
// One cursor runs through every panel. Python (herochart.py) sends a spec; nothing here knows about
// HRV or kilometres -- panels are trend / bars / lines, facts are text with an optional anchor.

const DAY = 864e5;
const STRIP = 60;      // height of one linked strip, px
const GAP = 14;        // vertical gap between panels, px
const PAD = { l: 38, r: 52, t: 10, b: 22 };

const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function frame(W, H, x0, x1, y0, y1, axis) {
  const pad = { ...PAD, b: axis ? PAD.b : 4 };
  const X = (t) => pad.l + (t - x0) / (x1 - x0) * (W - pad.l - pad.r);
  const Y = (v) => pad.t + (1 - (v - y0) / (y1 - y0)) * (H - pad.t - pad.b);
  return { W, H, X, Y, pad, x0, x1, y0, y1 };
}

function grid(f, ticks, fmt, theme) {
  let g = "";
  for (let i = 0; i <= ticks; i++) {
    const v = f.y0 + (f.y1 - f.y0) * i / ticks, y = f.Y(v);
    g += `<line x1="${f.pad.l}" x2="${f.W - f.pad.r}" y1="${y}" y2="${y}" stroke="${theme.grid}"/>` +
      `<text x="${f.pad.l - 6}" y="${y + 3}" text-anchor="end">${fmt(v)}</text>`;
  }
  return g;
}

function monthAxis(f, months) {
  let g = "";
  const d = new Date(f.x0); d.setDate(1); d.setMonth(d.getMonth() + 1);
  const span = (f.x1 - f.x0) / DAY, step = span > 420 ? 3 : span > 240 ? 2 : 1;
  for (; d.getTime() < f.x1; d.setMonth(d.getMonth() + step)) {
    const x = f.X(d.getTime());
    g += `<text x="${x}" y="${f.H - 5}" text-anchor="middle">${months[d.getMonth()]}${d.getMonth() === 0 ? " " + d.getFullYear() : ""}</text>`;
  }
  return g;
}

function path(points, f) {
  let d = "", on = false;
  for (const [t, v] of points) {
    if (v == null) { on = false; continue; }
    d += `${on ? "L" : "M"}${f.X(t).toFixed(1)},${f.Y(v).toFixed(1)}`; on = true;
  }
  return d;
}

const fmtNum = (v, decimals, lang) => {
  if (v == null || Number.isNaN(v)) return "—";
  const s = Number(v).toFixed(decimals ?? 0);
  return lang === "pl" ? s.replace(".", ",") : s;
};

function nearest(points, t, tol) {
  let best = null, bd = Infinity;
  for (const p of points) { const d = Math.abs(p[0] - t); if (d < bd) { bd = d; best = p; } }
  return best && bd <= tol ? best : null;
}

// ---- panel painters: each returns { svg, anchors(t, v) -> [x, y], hover(t) -> rows }
const PAINT = {
  trend(p, f, theme, lang) {
    let s = "";
    if (p.band && p.band.length) {
      const top = p.band.map(([t, , hi]) => `${f.X(t).toFixed(1)},${f.Y(hi).toFixed(1)}`);
      const bottom = p.band.slice().reverse().map(([t, lo]) => `${f.X(t).toFixed(1)},${f.Y(lo).toFixed(1)}`);
      s += `<polygon points="${top.concat(bottom).join(" ")}" fill="${theme.band}"/>`;
      if (p.band_label) { const [t, , hi] = p.band[p.band.length - 1]; s += `<text x="${f.X(t) + 6}" y="${f.Y(hi) + 10}" style="fill:${theme.bandText}">${esc(p.band_label)}</text>`; }
    }
    for (const [t, v] of p.points || []) if (v != null) s += `<circle cx="${f.X(t).toFixed(1)}" cy="${f.Y(v).toFixed(1)}" r="2.5" fill="${p.color || theme.series}" opacity=".42"/>`;
    if (p.smooth) s += `<path d="${path(p.smooth, f)}" fill="none" stroke="${p.color || theme.series}" stroke-width="${p.strip ? 2 : 2.6}" stroke-linejoin="round"/>`;
    for (const [t, color] of p.ticks || []) s += `<line x1="${f.X(t)}" x2="${f.X(t)}" y1="${f.Y(f.y0)}" y2="${f.Y(f.y0) - 12}" stroke="${color}" stroke-width="2"/>`;
    const last = (p.points || []).filter((q) => q[1] != null).slice(-1)[0];
    if (last && p.end) s += `<circle cx="${f.X(last[0])}" cy="${f.Y(last[1])}" r="${p.strip ? 3.5 : 5}" fill="${p.end_color || p.color || theme.series}" stroke="${theme.page}" stroke-width="2"/>` +
      (p.strip ? "" : `<text x="${f.X(last[0]) + 9}" y="${f.Y(last[1]) + 4}" style="fill:${theme.ink};font-weight:700">${esc(p.end)}</text>`);
    return {
      svg: s,
      hover: (t) => {
        const rows = [], a = nearest(p.points || [], t, 1.5 * DAY), b = p.smooth && nearest(p.smooth, t, 1.5 * DAY);
        if (a && a[1] != null) rows.push([p.name, fmtNum(a[1], p.decimals, lang) + (p.unit ? " " + p.unit : "")]);
        if (b && b[1] != null && p.smooth_name) rows.push([p.smooth_name, fmtNum(b[1], (p.decimals ?? 0) + 1, lang) + (p.unit ? " " + p.unit : "")]);
        return rows;
      },
    };
  },
  bars(p, f, theme, lang) {
    let s = "";
    const width = (p.width_days || 7) * DAY, bw = (f.X(f.x0 + width) - f.X(f.x0)) * 0.72;
    for (const [a, z, label] of p.gaps || []) {
      const xa = f.X(a), xz = f.X(z);
      s += `<rect x="${xa}" width="${Math.max(0, xz - xa)}" y="${f.pad.t}" height="${f.H - f.pad.t - f.pad.b}" fill="${theme.gap}"/>`;
      if (label) s += `<text x="${(xa + xz) / 2}" y="${f.pad.t + (f.H - f.pad.t - f.pad.b) * 0.45}" text-anchor="middle" style="fill:${theme.gapText};font-size:11.5px;letter-spacing:.1em">${esc(label)}</text>`;
    }
    for (const [t, values] of p.bars || []) {
      let base = 0;
      values.forEach((v, i) => {
        if (!v) return;
        const y0 = f.Y(base), y1 = f.Y(base + v);
        s += `<rect x="${f.X(t) + 1}" width="${bw}" y="${y1}" height="${Math.max(0, y0 - y1)}" rx="2" fill="${(p.colors || [])[i] || theme.series}"/>`;
        base += v;
      });
    }
    if (p.bracket) {
      const [a, z] = p.bracket, xa = f.X(a), xz = f.X(z) + bw, y = f.Y(f.y1);
      s += `<path d="M${xa},${y + 8} L${xa},${y} L${xz},${y} L${xz},${y + 8}" fill="none" stroke="${theme.accent}" stroke-width="1.2"/>`;
    }
    return {
      svg: s, bw,
      hover: (t) => {
        const bar = (p.bars || []).find(([b]) => t >= b && t < b + width);
        if (!bar) return [];
        return [[p.period || "", new Date(bar[0]).toLocaleDateString(lang === "pl" ? "pl-PL" : "en-GB", { day: "numeric", month: "short" })]]
          .concat(bar[1].map((v, i) => [(p.names || [])[i] || "", fmtNum(v, p.decimals ?? 1, lang) + (p.unit ? " " + p.unit : "")]))
          .filter(([k]) => k);
      },
    };
  },
  lines(p, f, theme, lang) {
    const id = "clip" + Math.random().toString(36).slice(2, 8);
    let s = `<clipPath id="${id}"><rect x="${f.pad.l}" y="${f.pad.t}" width="${f.W - f.pad.l - f.pad.r}" height="${f.H - f.pad.t - f.pad.b}"/></clipPath>`;
    for (const h of p.hlines || []) s += `<line x1="${f.pad.l}" x2="${f.W - f.pad.r}" y1="${f.Y(h.v)}" y2="${f.Y(h.v)}" stroke="${h.color}" stroke-dasharray="${h.dash ? "3 4" : ""}" opacity=".7"/>`;
    for (const l of p.lines || []) {
      s += `<path clip-path="url(#${id})" d="${path(l.points, f)}" fill="none" stroke="${l.color || theme.series}" stroke-width="${l.width || 2}" opacity="${l.opacity ?? 1}" stroke-linejoin="round"/>`;
      const last = l.points.filter((q) => q[1] != null).slice(-1)[0];
      if (last && l.end && !p.strip) s += `<text x="${f.X(last[0]) + 8}" y="${Math.min(f.H - f.pad.b, Math.max(f.pad.t + 8, f.Y(last[1]) + 4))}" style="fill:${l.end_color || l.color};font-weight:${l.width > 2 ? 700 : 400}">${esc(l.end)}</text>`;
    }
    for (const [t, v] of p.markers || []) s += `<circle cx="${f.X(t)}" cy="${f.Y(v)}" r="4" fill="${theme.series}" stroke="${theme.page}" stroke-width="2"/>`;
    return {
      svg: s,
      hover: (t) => (p.lines || []).map((l) => { const q = nearest(l.points, t, 1.5 * DAY); return q && q[1] != null && l.name ? [l.name, fmtNum(q[1], p.decimals, lang) + (p.unit ? " " + p.unit : "")] : null; }).filter(Boolean),
    };
  },
};

function satHTML(sat, text) {
  return `<div class="g">${esc(sat.group)}</div><div class="h">${esc(sat.head)}</div>` +
    (sat.text ? `<div class="t">${esc(sat.text)}</div>` : "") +
    (sat.go ? `<a class="go">${esc(sat.go.label || text.open)} →</a>` : "");
}

export function render(stage, args, opts) {
  const { spec, theme, text } = args;
  const root = document.documentElement.style;
  for (const [k, v] of Object.entries({ ink: theme.ink, ink2: theme.ink2, muted: theme.muted, faint: theme.faint, edge: theme.edge, accent: theme.accent, raise: theme.raise }))
    root.setProperty("--" + k, v);
  const narrow = (stage.clientWidth || window.innerWidth) < 860;
  root.setProperty("--side", narrow ? "0px" : (spec.side || 230) + "px");
  const [x0, x1] = spec.x;
  const main = spec.panels.find((p) => !p.strip), strips = spec.panels.filter((p) => p.strip);
  const sats = spec.satellites || [];

  stage.innerHTML = `<div class="grid hero"><div class="col l"></div><div class="chart main"></div><div class="col r"></div></div>` +
    strips.map((p, i) => `<div class="grid strip" style="margin-top:${GAP}px"><div class="strip-l"><div class="g">${esc(p.label?.group)}</div>` +
      `<div class="h">${esc(p.label?.head)}</div><div class="t">${esc(p.label?.note)}</div></div><div class="chart s${i}"></div>` +
      `<div class="strip-r">${p.why ? `<b>${esc(text.link)}:</b> ${esc(p.why)}` : ""}</div></div>`).join("") +
    `<svg class="leaders"></svg><div class="tip"></div>`;
  const colL = stage.querySelector(".col.l"), colR = stage.querySelector(".col.r");
  sats.forEach((sat, i) => {
    const el = document.createElement("div");
    el.className = "sat"; el.dataset.i = i; el.innerHTML = satHTML(sat, text);
    const go = el.querySelector(".go"); if (go) go.onclick = () => opts.onGo(sat.go);
    (sat.side === "l" ? colL : colR).appendChild(el);
  });

  // One screen: the main chart takes what the window leaves after the strips.
  const stripsH = strips.length * (STRIP + GAP);
  const mainH = Math.round(Math.max(spec.min_height || 240, Math.min(spec.max_height || 560, opts.available - stripsH)));
  const hosts = [];
  const draw = (host, p, H) => {
    const W = host.clientWidth || 600;
    const f = frame(W, H, x0, x1, p.y[0], p.y[1], !p.strip);
    const painted = PAINT[p.kind](p, f, theme, text.lang);
    const fmt = (v) => fmtNum(v, p.tick_decimals ?? 0, text.lang) + (p.tick_unit || "");
    host.innerHTML = `<svg width="${W}" height="${H}" style="display:block;overflow:visible">${grid(f, p.strip ? 1 : 4, fmt, theme)}` +
      `${p.strip ? "" : monthAxis(f, text.months)}<g class="${opts.animate ? "wipe" : ""}">${painted.svg}</g>` +
      `<line class="cur" y1="${f.pad.t}" y2="${H - f.pad.b}" stroke="${theme.ink}" stroke-opacity=".35" style="display:none"/></svg>`;
    hosts.push({ host, f, hover: painted.hover, p });
    return f;
  };
  const mf = main ? draw(stage.querySelector(".chart.main"), main, mainH) : null;
  strips.forEach((p, i) => draw(stage.querySelector(".chart.s" + i), p, STRIP));

  // Leader lines: from the side of a fact's headline, level to the chart edge, then to its point.
  const svg = stage.querySelector("svg.leaders"), sb = stage.getBoundingClientRect();
  svg.setAttribute("width", sb.width); svg.setAttribute("height", stage.scrollHeight);
  if (mf && !narrow) {
    const cb = stage.querySelector(".chart.main").getBoundingClientRect();
    let lines = "";
    stage.querySelectorAll(".sat").forEach((el) => {
      const sat = sats[+el.dataset.i]; if (!sat.anchor) return;
      const ax = cb.left - sb.left + mf.X(sat.anchor.t), ay = cb.top - sb.top + mf.Y(sat.anchor.v);
      const h = el.querySelector(".h").getBoundingClientRect(), left = sat.side === "l";
      const sx = left ? h.right - sb.left + 10 : h.left - sb.left - 10, sy = h.top - sb.top + Math.min(h.height / 2, 11);
      const ex = left ? cb.left - sb.left + 6 : cb.right - sb.left - 6;
      lines += `<polyline points="${sx},${sy} ${ex},${sy} ${ax},${ay}" fill="none" stroke="${theme.ink}" stroke-opacity=".5" stroke-width="1"/>` +
        `<circle cx="${sx}" cy="${sy}" r="2" fill="${theme.ink}"/><circle cx="${ax}" cy="${ay}" r="4.5" fill="${theme.page}" stroke="${theme.ink}" stroke-width="1.5"/>`;
    });
    svg.innerHTML = lines;
  }

  // One cursor for every panel, one tooltip listing them all.
  const tip = stage.querySelector(".tip");
  for (const { host, f } of hosts) {
    host.onmousemove = (e) => {
      const r = host.getBoundingClientRect(), t = f.x0 + (e.clientX - r.left - f.pad.l) / (f.W - f.pad.l - f.pad.r) * (f.x1 - f.x0);
      const day = new Date(t).toLocaleDateString(text.lang === "pl" ? "pl-PL" : "en-GB", { day: "numeric", month: "long", year: "numeric" });
      const rows = [`<b>${day}</b>`];
      for (const o of hosts) {
        const cur = o.host.querySelector(".cur"), X = o.f.X(t);
        cur.style.display = ""; cur.setAttribute("x1", X); cur.setAttribute("x2", X);
        for (const [k, v] of o.hover(t)) rows.push(`${esc(k)}: <b>${esc(v)}</b>`);
      }
      tip.innerHTML = rows.join("<br>"); tip.style.opacity = 1;
      const left = e.clientX - sb.left + 14, top = e.clientY - sb.top + 14;
      tip.style.left = Math.min(left, sb.width - tip.offsetWidth - 8) + "px"; tip.style.top = top + "px";
    };
    host.onmouseleave = () => { tip.style.opacity = 0; hosts.forEach((o) => (o.host.querySelector(".cur").style.display = "none")); };
  }
  return stage.scrollHeight + 4;
}
