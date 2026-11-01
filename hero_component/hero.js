// The hero page's canvas: one run in the middle, the day's facts laid out in the free space around it.
//
// Layout is a search, not a grid. The track is rasterised onto an 8 px occupancy grid with a casing
// around it, a distance transform gives every cell its distance to the track, and each fact (in
// priority order) takes the free rectangle that hugs the track closest -- with several close edges
// scoring best, which pulls text into the bends and inside the loop. Facts tied to a place on the run
// (the start, a stop, the kilometre of a drift) also want to be near that place and get a leader line.
// What does not fit is left out: the screen decides how many facts it can carry.

const GS = 8;

// How many facts a screen of this width carries (trivia counts as one).
export function capacity(width) {
  return width >= 1400 ? 12 : width >= 1200 ? 10 : width >= 1000 ? 8 : 6;
}

const merc = (lat, lon) => [lon, -Math.log(Math.tan(Math.PI / 4 + lat * Math.PI / 360)) * 180 / Math.PI];

function projection(points, box) {
  let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
  for (const [la, lo] of points) {
    const [x, y] = merc(la, lo);
    x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y);
  }
  const k = Math.min(box.w / Math.max(x1 - x0, 1e-9), box.h / Math.max(y1 - y0, 1e-9));
  const mx = (x0 + x1) / 2, my = (y0 + y1) / 2;
  return (la, lo) => { const [x, y] = merc(la, lo); return [box.x + box.w / 2 + (x - mx) * k, box.y + box.h / 2 + (y - my) * k]; };
}

function zoneOf(hr, edges) {
  if (hr == null || !edges) return 1;
  let z = 0;
  while (z < edges.length && hr >= edges[z]) z++;
  return z;
}

function factNode(f, opts, text) {
  const el = document.createElement("div");
  el.className = "fact" + (f.big ? " big" : "");
  el.innerHTML = `<div class="g">${f.group}</div><div class="h">${f.head}</div><div class="t">${f.text}</div>`;
  if (f.trivia) {
    const b = document.createElement("button");
    b.className = "reroll"; b.textContent = text.reroll;
    b.onclick = (e) => { e.stopPropagation(); opts.onReroll(); };
    el.appendChild(b);
  }
  if (f.go) el.onclick = () => opts.onGo(f.go);
  return el;
}

function legendHTML(theme, text, zones) {
  const z = zones || [];
  const labels = [`< ${z[0]}`, `${z[0]}–${z[1] - 1}`, `${z[1]}–${z[2] - 1}`, `${z[2]}–${z[3] - 1}`, `≥ ${z[3]}`];
  return `<span>${text.legend}</span>` + (zones ? theme.zones.map((c, i) =>
    `<span><i style="background:${c}"></i>Z${i + 1} ${labels[i]}</span>`).join("") : "") +
    `<span><i class="ring"></i>${text.stop}</span>`;
}

export function render(stage, args, opts) {
  const { payload, theme, text } = args;
  const W = Math.max(320, stage.clientWidth || window.innerWidth);
  const narrow = W < 720;
  const root = document.documentElement.style;
  root.setProperty("--ink", theme.ink); root.setProperty("--muted", theme.muted);
  root.setProperty("--faint", theme.faint); root.setProperty("--accent", theme.accent);

  const layer = stage.querySelector("#layer"), cv = stage.querySelector("#cv"), svg = stage.querySelector("#ln");
  layer.innerHTML = ""; svg.innerHTML = "";
  const head = document.createElement("div");
  head.className = "headline";
  head.innerHTML = `<div class="d">${payload.date}</div><h1>${payload.headline}</h1>` + (payload.meta ? `<div class="m">${payload.meta}</div>` : "");
  if (narrow) head.style.maxWidth = "100%";
  layer.appendChild(head);
  const hr = { w: head.offsetWidth, h: head.offsetHeight };

  // Facts in priority order, trivia (one at a time, rotating) last, cut to what this screen carries.
  const pool = payload.trivia || [];
  const facts = payload.facts.slice(0, capacity(W) - (pool.length ? 1 : 0));
  if (pool.length) facts.push({ ...pool[opts.trivia % pool.length], trivia: true });

  const run = payload.run && payload.run.pts && payload.run.pts.length > 1 ? payload.run : null;
  const H = narrow ? 0 : Math.round(Math.min(900, Math.max(600, W * 0.6)));
  const mapTop = narrow ? hr.h + 20 : Math.max(hr.h + 24, 0);
  const mapH = narrow ? Math.round(Math.min(380, W * 0.8)) : H - mapTop - 40;
  const box = narrow ? { x: 8, y: mapTop, w: W - 16, h: mapH } : { x: W * 0.2, y: mapTop, w: W * 0.6, h: mapH };

  const legend = document.createElement("div");
  legend.className = "legend";
  legend.innerHTML = legendHTML(theme, text, run && run.zones);
  layer.appendChild(legend);

  let height;
  let P = [], proj = null, total = 0;
  if (run) {
    proj = projection(run.pts, box);
    P = run.pts.map((p) => proj(p[0], p[1]));
    total = run.pts[run.pts.length - 1][3] || 0;
  }
  const atKm = (km) => { const i = run.pts.findIndex((p) => p[3] >= km); return P[i < 0 ? P.length - 1 : i]; };
  const anchorOf = (f) => !run || !f.anchor ? null
    : f.anchor.lat != null ? proj(f.anchor.lat, f.anchor.lon) : atKm(f.anchor.km);

  if (narrow) {
    legend.style.top = mapTop + mapH + 6 + "px";
    const list = document.createElement("div");
    list.className = "list";
    list.style.top = mapTop + mapH + 40 + "px";
    for (const f of facts) list.appendChild(factNode(f, opts, text));
    layer.appendChild(list);
    height = mapTop + mapH + 40 + list.offsetHeight + 16;
  } else {
    height = H;
    legend.style.top = H - 22 + "px";
  }
  stage.style.height = height + "px";
  const d = window.devicePixelRatio || 1;
  cv.width = W * d; cv.height = height * d; cv.style.width = W + "px"; cv.style.height = height + "px";
  svg.setAttribute("width", W); svg.setAttribute("height", height);
  const ctx = cv.getContext("2d"); ctx.setTransform(d, 0, 0, d, 0, 0); ctx.clearRect(0, 0, W, height);

  if (!narrow) {
    placeFacts({ W, H, facts, head: hr, run, P, atKm, anchorOf, box, layer, svg, theme, opts, text });
  }
  if (run) drawRun(ctx, run, P, atKm, total, proj, theme, opts.animate);
  return height;
}

function placeFacts({ W, H, facts, head, run, P, atKm, anchorOf, box, layer, svg, theme, opts, text }) {
  const cols = Math.ceil(W / GS), rows = Math.ceil(H / GS), N = cols * rows;
  // occ: where nothing may go (track casing, headline, placed facts); text: placed text only, which
  // a leader line must not cross.
  const occ = new Uint8Array(N), text_ = new Uint8Array(N), dist = new Float32Array(N).fill(1e9);
  const mark = (x, y, w, h) => {
    for (let r = Math.max(0, Math.floor(y / GS)); r < Math.min(rows, Math.ceil((y + h) / GS)); r++)
      for (let c = Math.max(0, Math.floor(x / GS)); c < Math.min(cols, Math.ceil((x + w) / GS)); c++) occ[r * cols + c] = 1;
  };
  const disc = (x, y, rad) => mark(x - rad, y - rad, 2 * rad, 2 * rad);
  const markText = (x, y, w, h) => {
    for (let r = Math.max(0, Math.floor(y / GS)); r < Math.min(rows, Math.ceil((y + h) / GS)); r++)
      for (let c = Math.max(0, Math.floor(x / GS)); c < Math.min(cols, Math.ceil((x + w) / GS)); c++) text_[r * cols + c] = 1;
  };
  // Does the straight line from (x0, y0) to (x1, y1) run over text already on the canvas?
  const crossesText = (x0, y0, x1, y1) => {
    const n = Math.ceil(Math.hypot(x1 - x0, y1 - y0) / GS);
    for (let i = 1; i < n; i++) {
      const c = Math.floor((x0 + (x1 - x0) * i / n) / GS), r = Math.floor((y0 + (y1 - y0) * i / n) / GS);
      if (c >= 0 && r >= 0 && c < cols && r < rows && text_[r * cols + c]) return true;
    }
    return false;
  };
  if (run) {
    for (let i = 1; i < P.length; i++) {
      const [ax, ay] = P[i - 1], [bx, by] = P[i], n = Math.max(1, Math.ceil(Math.hypot(bx - ax, by - ay) / 4));
      for (let j = 0; j <= n; j++) {
        const x = ax + (bx - ax) * j / n, y = ay + (by - ay) * j / n;
        disc(x, y, 14);
        const c = Math.floor(x / GS), r = Math.floor(y / GS);
        if (c >= 0 && r >= 0 && c < cols && r < rows) dist[r * cols + c] = 0;
      }
    }
    const total = run.pts[run.pts.length - 1][3] || 0;
    for (let km = 1; km < total; km++) disc(...atKm(km), 14);
  } else {
    // No run to hug: the facts gather around the middle of the canvas instead.
    for (let r = Math.floor(H * 0.45 / GS); r < Math.ceil(H * 0.55 / GS); r++)
      for (let c = Math.floor(W * 0.45 / GS); c < Math.ceil(W * 0.55 / GS); c++) dist[r * cols + c] = 0;
  }
  mark(0, 0, head.w + 24, head.h + 16);
  markText(0, 0, head.w, head.h);
  mark(0, H - 30, W, 30);
  // Chamfer distance transform, two passes (px).
  const D1 = GS, D2 = GS * Math.SQRT2;
  for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++) {
    const i = r * cols + c; let v = dist[i];
    if (c > 0) v = Math.min(v, dist[i - 1] + D1);
    if (r > 0) { v = Math.min(v, dist[i - cols] + D1); if (c > 0) v = Math.min(v, dist[i - cols - 1] + D2); if (c < cols - 1) v = Math.min(v, dist[i - cols + 1] + D2); }
    dist[i] = v;
  }
  for (let r = rows - 1; r >= 0; r--) for (let c = cols - 1; c >= 0; c--) {
    const i = r * cols + c; let v = dist[i];
    if (c < cols - 1) v = Math.min(v, dist[i + 1] + D1);
    if (r < rows - 1) { v = Math.min(v, dist[i + cols] + D1); if (c < cols - 1) v = Math.min(v, dist[i + cols + 1] + D2); if (c > 0) v = Math.min(v, dist[i + cols - 1] + D2); }
    dist[i] = v;
  }
  const dAt = (x, y) => dist[Math.min(rows - 1, Math.max(0, Math.floor(y / GS))) * cols + Math.min(cols - 1, Math.max(0, Math.floor(x / GS)))];
  let sat;
  const buildSat = () => {
    sat = new Int32Array((cols + 1) * (rows + 1));
    for (let r = 0; r < rows; r++) { let acc = 0; for (let c = 0; c < cols; c++) { acc += occ[r * cols + c]; sat[(r + 1) * (cols + 1) + c + 1] = sat[r * (cols + 1) + c + 1] + acc; } }
  };
  const busy = (c, r, w, h) => {
    if (c < 0 || r < 0 || c + w > cols || r + h > rows) return true;
    const a = cols + 1;
    return sat[(r + h) * a + c + w] - sat[r * a + c + w] - sat[(r + h) * a + c] + sat[r * a + c] > 0;
  };
  const tcx = box.x + box.w / 2, tcy = box.y + box.h / 2;
  let lines = "", order = 0;
  for (const f of facts) {
    const anchor = anchorOf(f);
    const el = factNode(f, opts, text);
    layer.appendChild(el);
    // Every width competes: a narrower block right next to its place beats a wide one far away.
    let placed = null, best = Infinity;
    const widths = (f.big ? [[250, 2], [220, 2], [190, 2]] : [[220, 2], [190, 2], [170, 2]]).concat([[160, 1], [140, 1]]);
    const top = widths[0][0];
    buildSat();
    for (const [w, m] of widths) {
      el.style.width = w + "px";
      const h = el.offsetHeight, wc = Math.ceil(w / GS), hc = Math.ceil(h / GS);
      for (let r = 0; r <= rows - hc; r++) for (let c = 0; c <= cols - wc; c++) {
        if (busy(c - m, r - m, wc + 2 * m, hc + 2 * m)) continue;
        const x = c * GS, y = r * GS, cx = x + w / 2, cy = y + h / 2;
        const e = [dAt(x - 4, cy), dAt(x + w + 4, cy), dAt(cx, y - 4), dAt(cx, y + h + 4),
                   dAt(x, y), dAt(x + w, y), dAt(x, y + h), dAt(x + w, y + h)].sort((a, b) => a - b);
        let s = e[0] + 0.45 * e[1] + 0.2 * e[2] + 0.6 * (top - w);
        if (anchor) {
          // Near its place on the run, and never with the leader line across another fact's text.
          const nx = Math.min(Math.max(anchor[0], x), x + w), ny = Math.min(Math.max(anchor[1], y), y + h);
          s += 2.2 * Math.hypot(anchor[0] - nx, anchor[1] - ny);
          if (crossesText(nx, ny, anchor[0], anchor[1])) s += 600;
        } else if (f.side) s += ({ r: cx < tcx, l: cx > tcx, t: cy > tcy, b: cy < tcy }[f.side] ? 160 : 0);
        if (s < best) { best = s; placed = { x, y, w, h }; }
      }
    }
    if (!placed) { el.remove(); continue; }
    Object.assign(el.style, { left: placed.x + "px", top: placed.y + "px", width: placed.w + "px" });
    mark(placed.x, placed.y, placed.w, placed.h);
    markText(placed.x, placed.y, placed.w, placed.h);
    // The text hangs toward the track: when the track is nearer on the right, align right.
    if (dAt(placed.x + placed.w + 6, placed.y + placed.h / 2) < dAt(placed.x - 6, placed.y + placed.h / 2)) el.classList.add("r");
    const delay = opts.animate ? 250 + order * 70 : 0; order++;
    setTimeout(() => el.classList.add("on"), delay);
    if (anchor) {
      // Beside the block: the line leaves from the headline's side. Above or below it: from the
      // block's own edge, so it never runs through the block's text.
      const hb = el.querySelector(".h").getBoundingClientRect(), sb = layer.getBoundingClientRect();
      const L = hb.left - sb.left, R = hb.right - sb.left, T = hb.top - sb.top, B = hb.bottom - sb.top;
      let sx, sy;
      if (anchor[0] < L || anchor[0] > R) {
        sx = anchor[0] < L ? L - 8 : R + 8;
        sy = Math.min(Math.max(anchor[1], T), B);
      } else {
        sx = anchor[0];
        sy = anchor[1] < placed.y ? placed.y - 6 : placed.y + placed.h + 6;
      }
      lines += `<line x1="${sx}" y1="${sy}" x2="${anchor[0]}" y2="${anchor[1]}" stroke="${theme.ink}" stroke-width="1" opacity=".75"/>` +
        `<circle cx="${anchor[0]}" cy="${anchor[1]}" r="4" fill="${theme.page}" stroke="${theme.ink}" stroke-width="1.5"/>`;
    }
  }
  svg.innerHTML = lines;
}

function drawRun(ctx, run, P, atKm, total, proj, theme, animate) {
  const zones = run.zones;
  const frame = (upto) => {
    ctx.save();
    ctx.clearRect(0, 0, ctx.canvas.width, ctx.canvas.height);
    ctx.globalAlpha = run.dim ? 0.45 : 1;
    ctx.lineCap = ctx.lineJoin = "round";
    const n = Math.max(2, Math.floor(upto * P.length));
    ctx.strokeStyle = theme.page; ctx.lineWidth = 9;
    ctx.beginPath(); for (let i = 0; i < n; i++) i ? ctx.lineTo(...P[i]) : ctx.moveTo(...P[i]); ctx.stroke();
    ctx.lineWidth = 5;
    for (let i = 1; i < n; i++) {
      ctx.strokeStyle = theme.zones[zoneOf(run.pts[i][2], zones)];
      ctx.beginPath(); ctx.moveTo(...P[i - 1]); ctx.lineTo(...P[i]); ctx.stroke();
    }
    if (upto >= 1) {
      ctx.font = '600 10px "Source Sans Pro", -apple-system, sans-serif';
      ctx.textAlign = "center"; ctx.textBaseline = "middle";
      for (let km = 1; km < total; km++) {
        const [x, y] = atKm(km);
        ctx.fillStyle = theme.page; ctx.beginPath(); ctx.arc(x, y, 8, 0, 7); ctx.fill();
        ctx.strokeStyle = theme.edge; ctx.lineWidth = 1; ctx.stroke();
        ctx.fillStyle = theme.ink; ctx.fillText(km, x, y + 0.5);
      }
      for (const [la, lo, s] of run.stops) {
        const [x, y] = proj(la, lo);
        ctx.strokeStyle = theme.ink; ctx.lineWidth = 1.5;
        ctx.beginPath(); ctx.arc(x, y, 5 + Math.min(s, 120) / 8, 0, 7); ctx.stroke();
      }
    }
    ctx.globalAlpha = 1; ctx.fillStyle = theme.ink;
    ctx.beginPath(); ctx.arc(...P[0], 4, 0, 7); ctx.fill();
    ctx.restore();
  };
  const reduced = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (!animate || reduced) { frame(1); return; }
  const t0 = performance.now(), dur = 1100;
  const step = (now) => {
    const k = Math.min(1, (now - t0) / dur);
    frame(1 - Math.pow(1 - k, 3));
    if (k < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}
