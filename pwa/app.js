// The dashboard on a phone. Every number comes from the server's summary
// (summary.py); this file only lays it out and keeps the last copy offline.
"use strict";

const STORE = {
  token: "gd_token",
  lang: "gd_lang",
  summary: (lang) => `gd_summary_${lang}`,
  etag: (lang) => `gd_etag_${lang}`,
};
const API = "../summary";

const WORDS = {
  pl: {
    refresh: "Odśwież", today: "Dziś", sleep: "Sen", hrv: "HRV", rhr: "Tętno spoczynkowe", steps: "Kroki",
    readiness: "Gotowość", vo2max: "VO2max", body_battery: "Body Battery",
    week: "tydzień", norm: "norma", below: "poniżej normy", above: "powyżej normy", within: "w normie",
    recovery: "Regeneracja", running: "Bieganie", trends: "90 dni", workouts: "Ostatnie treningi",
    hrv_chart: "HRV noc po nocy, średnia 7 nocy i pas normy", sleep_chart: "Długość snu",
    km_chart: "Kilometry biegu tygodniowo", data_from: "dane z", offline: "offline — ostatnia kopia",
    online: "aktualne", setup_title: "Połącz z dashboardem",
    setup_text: "Na komputerze: Konto (imię w prawym górnym rogu) → „Utwórz klucz do odczytu”. Wklej go tutaj — zostaje tylko na tym telefonie.",
    setup_button: "Połącz", bad_key: "Klucz nie działa (odwołany albo literówka).", no_data: "Brak danych — jeszcze nic nie przyszło.",
    key_revoked: "Klucz został odwołany — połącz ponownie.", disconnect: "Rozłącz", min: "min", km: "km",
    sports: { running: "Bieg", treadmill_running: "Bieżnia", walking: "Spacer", hiking: "Wędrówka", cycling: "Rower",
      strength_training: "Siła", lap_swimming: "Pływanie", yoga: "Joga" },
  },
  en: {
    refresh: "Refresh", today: "Today", sleep: "Sleep", hrv: "HRV", rhr: "Resting HR", steps: "Steps",
    readiness: "Readiness", vo2max: "VO2max", body_battery: "Body Battery",
    week: "week", norm: "normal", below: "below normal", above: "above normal", within: "within normal",
    recovery: "Recovery", running: "Running", trends: "90 days", workouts: "Recent workouts",
    hrv_chart: "HRV night by night, 7-night mean and the normal band", sleep_chart: "Sleep length",
    km_chart: "Running kilometres per week", data_from: "data from", offline: "offline — last copy",
    online: "up to date", setup_title: "Connect to the dashboard",
    setup_text: "On the computer: Account (your name, top right) → “Make a read key”. Paste it here — it stays on this phone only.",
    setup_button: "Connect", bad_key: "The key does not work (revoked or mistyped).", no_data: "No data yet — nothing has arrived.",
    key_revoked: "The key was revoked — connect again.", disconnect: "Disconnect", min: "min", km: "km",
    sports: { running: "Run", treadmill_running: "Treadmill", walking: "Walk", hiking: "Hike", cycling: "Ride",
      strength_training: "Strength", lap_swimming: "Swim", yoga: "Yoga" },
  },
};

const state = { lang: read(STORE.lang) || ((navigator.language || "pl").slice(0, 2) === "en" ? "en" : "pl"), online: true };

function read(key) { try { return localStorage.getItem(key); } catch { return null; } }
function write(key, value) { try { value === null ? localStorage.removeItem(key) : localStorage.setItem(key, value); } catch { /* private mode */ } }
function w(key) { return WORDS[state.lang][key]; }

// Append and return the child (DOM append returns nothing).
function add(parent, child) { parent.append(child); return child; }

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}

// Headlines carry <em> around the number (facts.py). Everything else is text.
function rich(text) {
  const span = el("span");
  const safe = String(text || "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  span.innerHTML = safe.replace(/&lt;em&gt;/g, "<em>").replace(/&lt;\/em&gt;/g, "</em>").replace(/&lt;b&gt;|&lt;\/b&gt;/g, "");
  return span;
}

function hm(hours) {
  if (hours === null || hours === undefined) return "—";
  const total = Math.round(hours * 60);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}
function num(value, digits = 0) {
  if (value === null || value === undefined) return "—";
  return Number(value).toLocaleString(state.lang === "pl" ? "pl-PL" : "en-GB", { maximumFractionDigits: digits, minimumFractionDigits: digits });
}
function when(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString(state.lang === "pl" ? "pl-PL" : "en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}
function day(iso) {
  if (!iso) return "";
  return new Date(iso).toLocaleDateString(state.lang === "pl" ? "pl-PL" : "en-GB", { weekday: "short", day: "numeric", month: "short" });
}

// ------------------------------------------------------------------ data

async function load(force = false) {
  const token = read(STORE.token);
  if (!token) return renderSetup();
  const cached = read(STORE.summary(state.lang));
  if (cached && !force) render(JSON.parse(cached));
  try {
    const headers = { Authorization: `Bearer ${token}` };
    const etag = read(STORE.etag(state.lang));
    if (etag && cached) headers["If-None-Match"] = etag;
    const response = await fetch(`${API}?lang=${state.lang}`, { headers, cache: "no-store" });
    state.online = true;
    if (response.status === 304 && cached) return render(JSON.parse(cached));
    if (response.status === 401) {
      if (cached) { render(JSON.parse(cached), w("key_revoked")); return; }
      write(STORE.token, null);
      return renderSetup(w("bad_key"));
    }
    if (!response.ok) throw new Error(String(response.status));
    const data = await response.json();
    write(STORE.summary(state.lang), JSON.stringify(data));
    write(STORE.etag(state.lang), response.headers.get("ETag"));
    render(data);
  } catch (error) {
    state.online = false;
    if (cached) render(JSON.parse(cached));
    else renderSetup(w("no_data"));
  }
}

// ------------------------------------------------------------------ views

function renderSetup(message) {
  document.getElementById("who").textContent = "Dashboard";
  document.getElementById("status").textContent = "";
  const main = document.getElementById("main");
  main.replaceChildren();
  const box = el("section", "setup");
  box.append(el("div", "headline", w("setup_title")), el("p", "status", w("setup_text")));
  const input = el("input");
  input.type = "password"; input.autocomplete = "off"; input.placeholder = "gd_…"; input.spellcheck = false;
  const button = el("button", "link primary", w("setup_button"));
  button.type = "button";
  button.onclick = () => {
    const value = input.value.trim();
    if (!value.startsWith("gd_")) return renderSetup(w("bad_key"));
    write(STORE.token, value);
    load(true);
  };
  box.append(input, button);
  if (message) box.append(el("div", "error", message));
  main.append(box);
}

function render(data, warning) {
  const main = document.getElementById("main");
  main.replaceChildren();
  document.getElementById("who").textContent = data.name || "Dashboard";
  const status = document.getElementById("status");
  status.replaceChildren();
  const dot = el("span", state.online ? "dot" : "dot off");
  status.append(dot, document.createTextNode(`${state.online ? w("online") : w("offline")} · ${w("data_from")} ${when(data.built_at)}`));
  if (warning) main.append(el("div", "error", warning));
  if (data.empty) { main.append(el("p", "status", w("no_data"))); return; }

  const stories = data.stories || {};
  if (stories.recovery && stories.recovery.headline) add(main, el("div", "headline")).append(rich(stories.recovery.headline));
  main.append(el("h2", null, w("today")), todayTiles(data.today || {}));

  for (const [key, title] of [["recovery", w("recovery")], ["sleep", w("sleep")], ["running", w("running")]]) {
    const story = stories[key];
    if (!story || (!story.headline && !(story.cards || []).length)) continue;
    main.append(el("h2", null, title));
    if (key !== "recovery" && story.headline) add(main, el("div", "headline")).append(rich(story.headline));
    const cards = el("div", "cards");
    for (const card of story.cards || []) {
      const node = el("div", "card");
      node.append(el("div", "group", card.group));
      add(node, el("div", "head")).append(rich(card.head));
      if (card.text) add(node, el("div", "text")).append(rich(card.text));
      cards.append(node);
    }
    main.append(cards);
  }

  const s = data.series || {};
  main.append(el("h2", null, w("trends")));
  if ((s.hrv_last_night || []).some((v) => v !== null)) {
    main.append(chart(w("hrv_chart"), lineChart(s.day, s.hrv_last_night, s.hrv_last_night_roll7, s.hrv_baseline_low, s.hrv_baseline_high, "ms")));
  }
  if ((s.sleep_h || []).some((v) => v !== null)) main.append(chart(w("sleep_chart"), barChart(s.day, s.sleep_h, hm)));
  const weeks = data.weeks || {};
  if ((weeks.km || []).length) main.append(chart(w("km_chart"), barChart(weeks.week, weeks.km, (v) => `${num(v, 0)} km`)));

  if ((data.activities || []).length) {
    main.append(el("h2", null, w("workouts")));
    const list = el("div", "list");
    for (const a of data.activities) {
      const row = el("div", "row");
      const left = el("div");
      left.append(el("div", null, WORDS[state.lang].sports[a.sport] || a.name || a.sport), el("div", "meta", day(a.start)));
      const right = el("div", "right");
      const main_line = a.km ? `${num(a.km, 1)} ${w("km")}` : `${a.minutes || "—"} ${w("min")}`;
      right.append(el("div", null, main_line));
      right.append(el("div", "meta", [a.pace ? `${a.pace} /km` : null, a.avg_hr ? `${a.avg_hr} bpm` : null].filter(Boolean).join(" · ")));
      row.append(left, right);
      list.append(row);
    }
    main.append(list);
  }
  const off = el("button", "link", w("disconnect"));
  off.type = "button";
  off.style.marginTop = "28px";
  off.onclick = () => { write(STORE.token, null); renderSetup(); };
  main.append(off);
}

function tile(label, value, note, warn) {
  const node = el("div", "tile");
  node.append(el("div", "label", label), el("div", "value", value));
  if (note) node.append(el("div", warn ? "note warn" : "note", note));
  return node;
}

function against(value, low, high) {
  if (value === null || low === null || high === null || low === undefined) return [null, false];
  if (value < low) return [w("below"), true];
  if (value > high) return [w("above"), false];
  return [w("within"), false];
}

function todayTiles(t) {
  const grid = el("div", "grid");
  if (t.sleep) grid.append(tile(w("sleep"), hm(t.sleep.hours), t.sleep.week_mean ? `${w("week")} ${hm(t.sleep.week_mean)}` : null));
  if (t.hrv) {
    const [word, warn] = against(t.hrv.value, t.hrv.low, t.hrv.high);
    grid.append(tile(`${w("hrv")}${t.hrv.kind === "sdnn" ? " (SDNN)" : ""}`, `${num(t.hrv.value)} ms`,
      word ? `${word} ${num(t.hrv.low)}–${num(t.hrv.high)}` : (t.hrv.week_mean ? `${w("week")} ${num(t.hrv.week_mean)}` : null), warn));
  }
  if (t.rhr) {
    const [word] = against(t.rhr.value, t.rhr.low, t.rhr.high);
    grid.append(tile(w("rhr"), `${num(t.rhr.value)}`, word ? `${word} ${t.rhr.low}–${t.rhr.high}` : null, t.rhr.value > t.rhr.high));
  }
  if (t.steps) grid.append(tile(w("steps"), num(t.steps.value), t.steps.week_mean ? `${w("week")} ${num(t.steps.week_mean)}` : null));
  if (t.readiness) grid.append(tile(w("readiness"), num(t.readiness.value)));
  if (t.bb_wake) grid.append(tile(w("body_battery"), num(t.bb_wake.value)));
  if (t.vo2max) grid.append(tile(w("vo2max"), num(t.vo2max.value, 1)));
  return grid;
}

// ------------------------------------------------------------------ charts (inline SVG, flat colours)

const SVG = "http://www.w3.org/2000/svg";
function svg(tag, attrs) {
  const node = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  return node;
}
function chart(caption, figure) {
  const box = el("div", "chart");
  box.append(figure, el("div", "caption", caption));
  const gap = el("div"); gap.style.height = "10px";
  const wrap = el("div"); wrap.append(box, gap);
  return wrap;
}

function scale(values, pad = 0.08) {
  const real = values.filter((v) => v !== null && v !== undefined);
  let lo = Math.min(...real), hi = Math.max(...real);
  if (lo === hi) { lo -= 1; hi += 1; }
  const span = hi - lo;
  return [lo - span * pad, hi + span * pad];
}

function lineChart(days, values, smooth, low, high, unit) {
  const W = 340, H = 150, L = 4, R = 36, T = 8, B = 18;
  const n = days.length;
  const [lo, hi] = scale([...values, ...(low || []), ...(high || [])]);
  const x = (i) => L + (W - L - R) * (n <= 1 ? 0 : i / (n - 1));
  const y = (v) => T + (H - T - B) * (1 - (v - lo) / (hi - lo));
  const root = svg("svg", { viewBox: `0 0 ${W} ${H}`, role: "img" });
  if (low && high) {
    let path = "";
    const top = [], bottom = [];
    days.forEach((_, i) => { if (low[i] !== null && high[i] !== null) { top.push([x(i), y(high[i])]); bottom.push([x(i), y(low[i])]); } });
    if (top.length > 1) {
      path = "M" + top.map((p) => p.join(",")).join("L") + "L" + bottom.reverse().map((p) => p.join(",")).join("L") + "Z";
      root.append(svg("path", { d: path, fill: "var(--band)", stroke: "none" }));
    }
  }
  values.forEach((v, i) => { if (v !== null) root.append(svg("circle", { cx: x(i), cy: y(v), r: 1.8, fill: "rgba(250,250,250,0.35)" })); });
  if (smooth) {
    const points = smooth.map((v, i) => (v === null ? null : `${x(i)},${y(v)}`)).filter(Boolean);
    if (points.length > 1) root.append(svg("polyline", { points: points.join(" "), fill: "none", stroke: "var(--accent)", "stroke-width": 2 }));
    const last = [...smooth].reverse().find((v) => v !== null);
    if (last !== undefined) {
      const label = svg("text", { x: W - R + 4, y: y(last) + 4, fill: "var(--text)", "font-size": 11 });
      label.textContent = `${num(last)} ${unit}`;
      root.append(label);
    }
  }
  axisDates(root, days, x, H);
  return root;
}

function barChart(days, values, format) {
  const W = 340, H = 130, L = 4, R = 4, T = 14, B = 18;
  const n = days.length;
  const real = values.filter((v) => v !== null);
  const hi = Math.max(...real, 1);
  const width = Math.max(1, (W - L - R) / n - 1.5);
  const x = (i) => L + (W - L - R) * (i / n);
  const root = svg("svg", { viewBox: `0 0 ${W} ${H}`, role: "img" });
  values.forEach((v, i) => {
    if (v === null) return;
    const h = (H - T - B) * (v / hi);
    root.append(svg("rect", { x: x(i), y: H - B - h, width, height: h, fill: i === n - 1 ? "var(--accent)" : "rgba(57,135,229,0.45)", rx: 1 }));
  });
  const last = [...values].reverse().find((v) => v !== null);
  if (last !== undefined) {
    const label = svg("text", { x: W - R, y: 11, fill: "var(--text)", "font-size": 11, "text-anchor": "end" });
    label.textContent = format(last);
    root.append(label);
  }
  axisDates(root, days, (i) => x(i) + width / 2, H);
  return root;
}

function axisDates(root, days, x, H) {
  if (!days || days.length < 2) return;
  for (const i of [0, Math.floor((days.length - 1) / 2), days.length - 1]) {
    const label = svg("text", { x: x(i), y: H - 4, fill: "var(--muted)", "font-size": 10,
      "text-anchor": i === 0 ? "start" : i === days.length - 1 ? "end" : "middle" });
    label.textContent = new Date(days[i]).toLocaleDateString(state.lang === "pl" ? "pl-PL" : "en-GB", { day: "numeric", month: "short" });
    root.append(label);
  }
}

// ------------------------------------------------------------------ start

function chrome() {
  document.documentElement.lang = state.lang;
  document.getElementById("refresh").textContent = w("refresh");
  document.getElementById("lang").textContent = state.lang === "pl" ? "EN" : "PL";
}

(function pairFromLink() {
  // A link from the Account page may carry the key in the fragment: it never
  // reaches a server log, and is wiped from the address bar at once.
  const match = location.hash.match(/token=(gd_[A-Za-z0-9_-]+)/);
  if (match) {
    write(STORE.token, match[1]);
    history.replaceState(null, "", location.pathname + location.search);
  }
})();

document.getElementById("refresh").onclick = () => load(true);
document.getElementById("lang").onclick = () => {
  state.lang = state.lang === "pl" ? "en" : "pl";
  write(STORE.lang, state.lang);
  chrome();
  load();
};
window.addEventListener("online", () => load(true));
window.addEventListener("offline", () => { state.online = false; load(); });
document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") load(); });
chrome();
load();
if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
