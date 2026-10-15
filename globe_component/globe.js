/* Orthographic globe on a 2D canvas.
 *
 * The whole animation lives in the browser: the server sends the activities
 * once per warehouse build, the world outline is a static file the browser
 * caches, and rotation is a requestAnimationFrame loop. The server is involved
 * again only when someone clicks a place.
 *
 * Projection and clipping are d3-geo's (vendored next to this file, never a
 * CDN). That is a deliberate reversal of a hand-rolled version: clipping a
 * polygon to the visible hemisphere is not the small problem it looks like.
 * When an outline leaves the disc it has to come back around the horizon the
 * right way, and neither "take the shorter arc" nor "keep the heading at the
 * crossing" is correct -- Africa and Eurasia are a single polygon wrapping
 * more than half the horizon, and those rules tear wedges out of the globe or
 * flood it with land, depending on which one you pick. d3-geo does the real
 * spherical clip.
 *
 * What stays local is everything d3 has no opinion about: the clustering of
 * activities per zoom level, the heat layer of GPS tracks, the animation, and
 * the interaction.
 *
 * The heat layer: past HEAT_ZOOM the globe is at city scale and the start
 * markers give way to the tracks themselves, each stretch coloured and
 * thickened by how many distinct activities ran through it. Counting happens
 * here, not in Python, so changing the sport filter sends a list of ids and the
 * browser recounts -- the tracks themselves arrive once, as a cached file.
 */

export const MIN_ZOOM = 1;
// Street level: at 3000x a kilometre is a few hundred pixels.
export const MAX_ZOOM = 3000;
// Where the tracks take over from the start markers, and where spinning stops
// (a turning globe at city scale is a map sliding out from under the cursor).
export const HEAT_ZOOM = 14;
const SPIN_ZOOM = 6;

// Pass-count classes: lower bound and base line width in px.
// Width carries as much of the class as colour does: neighbouring steps of one
// blue ramp are close, a 1 px thread against a 5 px band is not.
export const HEAT_CLASSES = [
  { from: 1, label: "1×", width: 1.2 },
  { from: 2, label: "2–3×", width: 2.0 },
  { from: 4, label: "4–7×", width: 2.9 },
  { from: 8, label: "8–15×", width: 3.9 },
  { from: 16, label: "16× i więcej", width: 5.0 },
];
const CELL_M = 20;

const RAD = Math.PI / 180;

function wrapLon(lon) {
  return ((lon + 540) % 360) - 180;
}

function deltaLon(from, to) {
  let d = to - from;
  while (d > 180) d -= 360;
  while (d < -180) d += 360;
  return d;
}

function hexToRgb(hex) {
  const h = hex.replace("#", "");
  return [
    parseInt(h.slice(0, 2), 16),
    parseInt(h.slice(2, 4), 16),
    parseInt(h.slice(4, 6), 16),
  ];
}

function rgba(hex, alpha) {
  const [r, g, b] = hexToRgb(hex);
  return `rgba(${r},${g},${b},${alpha})`;
}

function rampColor(ramp, t) {
  const clamped = Math.max(0, Math.min(1, t));
  const pos = clamped * (ramp.length - 1);
  const i = Math.min(ramp.length - 2, Math.floor(pos));
  const f = pos - i;
  const a = hexToRgb(ramp[i]);
  const b = hexToRgb(ramp[i + 1]);
  return `rgb(${Math.round(a[0] + (b[0] - a[0]) * f)},${Math.round(
    a[1] + (b[1] - a[1]) * f
  )},${Math.round(a[2] + (b[2] - a[2]) * f)})`;
}

export function createGlobe(canvas, options = {}) {
  const d3 = window.d3;
  if (!d3 || !d3.geoOrthographic) throw new Error("vendor/d3-geo nie zaladowane");

  const ctx = canvas.getContext("2d");
  const projection = d3.geoOrthographic().clipAngle(90).precision(0.4);
  const path = d3.geoPath(projection, ctx);
  // Tracks are dense already; adaptive resampling on tens of thousands of
  // points per frame would buy nothing visible and cost the frame rate.
  const trackProjection = d3.geoOrthographic().clipAngle(90).precision(0);
  const trackPath = d3.geoPath(trackProjection, ctx);
  const sphere = { type: "Sphere" };

  const state = {
    world: null,
    graticule: null,
    graticuleStep: null,
    allActivities: [],
    activities: [],
    selected: null,
    tracks: null,
    heat: null,
    clusters: [],
    theme: {
      ocean: "#cfe0f1", oceanLight: "#e8f1fa", land: "#e6e3d8", coast: "#b3b0a4",
      border: "#c6c3b7", graticule: "rgba(120,140,160,0.22)", surface: "#fcfcfb",
      ink: "#0b0b0b", glow: "#2a78d6",
      ramp: ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"],
      heat: ["#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"],
      casing: "rgba(255,255,255,0.92)",
    },
    rot: { lon: 20, lat: 35 },
    zoom: 1,
    zoomTo: null,
    fly: null,
    spin: true,
    speed: 9, // degrees per second at full-globe zoom
    dragging: false,
    hover: -1,
    dirty: true,
    maxCount: 1,
    frame: null,
    last: 0,
    size: { w: 600, h: 600, dpr: 1 },
  };
  const onPick = options.onPick || function () {};
  const onHover = options.onHover || function () {};
  const onZoom = options.onZoom || function () {};

  const baseRadius = () => Math.min(state.size.w, state.size.h) / 2 - 6;
  const radius = () => baseRadius() * state.zoom;

  function aim() {
    for (const p of [projection, trackProjection]) {
      p.translate([state.size.w / 2, state.size.h / 2])
        .scale(radius())
        .rotate([-state.rot.lon, -state.rot.lat]);
    }
  }

  // Front of the sphere: d3 clips paths for us, but a marker is drawn by hand
  // and has to be told whether it is behind the globe.
  function depth(lon, lat) {
    const c = d3.geoDistance([lon, lat], [state.rot.lon, state.rot.lat]);
    return Math.cos(c);
  }

  /* -------------------------------------------------------- clustering */

  // Markers are grouped so they never overlap: the grid is whatever 26 px is
  // worth in degrees at the current zoom. Zoom in and a city falls apart into
  // its parks, then into single activities -- and a single activity is a link
  // straight to that activity.
  function rebin() {
    const grid = Math.max(0.0002, (26 * 180) / (Math.PI * radius()));
    const buckets = new Map();
    for (const activity of state.activities) {
      const key =
        Math.round(activity.lat / grid) + "," + Math.round(activity.lon / grid);
      let bucket = buckets.get(key);
      if (!bucket) {
        bucket = { lat: 0, lon: 0, count: 0, ids: [], newest: activity };
        buckets.set(key, bucket);
      }
      bucket.lat += activity.lat;
      bucket.lon += activity.lon;
      bucket.count += 1;
      bucket.ids.push(activity.id);
      if ((activity.ts || 0) > (bucket.newest.ts || 0)) bucket.newest = activity;
    }
    state.clusters = [];
    for (const [key, bucket] of buckets) {
      state.clusters.push({
        key,
        lat: bucket.lat / bucket.count,
        lon: bucket.lon / bucket.count,
        count: bucket.count,
        ids: bucket.ids,
        activity: bucket.count === 1 ? bucket.newest : null,
        name: bucket.newest.place || bucket.newest.name || "—",
        last: bucket.newest.date || "",
      });
    }
    state.maxCount = Math.max(1, ...state.clusters.map((c) => c.count));
  }

  /* --------------------------------------------------------------- heat */

  function applySelection() {
    const keep = state.selected;
    state.activities = keep
      ? state.allActivities.filter((a) => keep.has(a.id))
      : state.allActivities.slice();
    rebin();
    computeHeat();
  }

  // Grid cell of a point. Longitude cells widen with latitude, using the
  // latitude band's cosine so the grid is stable inside one city.
  const DLAT = CELL_M / 111320;
  function cellKey(lat, lon) {
    const band = Math.cos((Math.floor(lat) + 0.5) * RAD);
    const dlon = DLAT / Math.max(band, 0.1);
    const i = Math.floor(lat / DLAT);
    const j = Math.floor(lon / dlon);
    return (i + 1e6) * 1e8 + (j + 5e7);
  }

  /* How many distinct activities pass through every ~20 m cell, then each
     track segment drawn in the class of its busier end. Same method as the
     Python side used: densify to half a cell, count per activity once, and
     spread each count to the 3x3 neighbourhood so a few metres of GPS offset
     does not split one corridor into parallel threads. */
  function computeHeat() {
    if (!state.tracks) {
      state.heat = null;
      return;
    }
    const ids = state.selected ? [...state.selected] : [...state.tracks.keys()];
    const counts = new Map();
    const step = CELL_M / 2;
    for (const id of ids) {
      const t = state.tracks.get(id);
      if (!t) continue;
      const cells = new Set();
      for (let k = 0; k + 3 < t.length; k += 2) {
        const la0 = t[k], lo0 = t[k + 1], la1 = t[k + 2], lo1 = t[k + 3];
        const dy = (la1 - la0) * 111320;
        const dx = (lo1 - lo0) * 111320 * Math.cos(la0 * RAD);
        const n = Math.max(1, Math.ceil(Math.hypot(dx, dy) / step));
        for (let s = 0; s < n; s++) {
          const f = s / n;
          cells.add(cellKey(la0 + (la1 - la0) * f, lo0 + (lo1 - lo0) * f));
        }
      }
      if (t.length >= 2) cells.add(cellKey(t[t.length - 2], t[t.length - 1]));
      for (const key of cells) {
        for (let di = -1; di <= 1; di++) {
          for (let dj = -1; dj <= 1; dj++) {
            const k2 = key + di * 1e8 + dj;
            counts.set(k2, (counts.get(k2) || 0) + 1);
          }
        }
      }
    }

    const classes = HEAT_CLASSES.map(() => ({ type: "MultiLineString", coordinates: [] }));
    const casing = { type: "MultiLineString", coordinates: [] };
    const classOf = (n) => {
      let c = 0;
      for (let x = 0; x < HEAT_CLASSES.length; x++) if (n >= HEAT_CLASSES[x].from) c = x;
      return c;
    };
    for (const id of ids) {
      const t = state.tracks.get(id);
      if (!t || t.length < 4) continue;
      const line = [];
      for (let k = 0; k < t.length; k += 2) line.push([t[k + 1], t[k]]);
      casing.coordinates.push(line);
      let run = null;
      let runClass = -1;
      for (let k = 0; k + 3 < t.length; k += 2) {
        const a = counts.get(cellKey(t[k], t[k + 1])) || 1;
        const b = counts.get(cellKey(t[k + 2], t[k + 3])) || 1;
        const c = classOf(Math.max(a, b));
        if (c !== runClass) {
          run = [[t[k + 1], t[k]]];
          classes[c].coordinates.push(run);
          runClass = c;
        }
        run.push([t[k + 3], t[k + 2]]);
      }
    }
    state.heat = { classes, casing };
  }

  function heatAlpha() {
    // Fade in over a doubling of zoom rather than popping in at one step.
    return Math.max(0, Math.min(1, (state.zoom - HEAT_ZOOM / 2) / (HEAT_ZOOM / 2)));
  }

  function drawHeat() {
    const alpha = heatAlpha();
    if (!state.heat || alpha <= 0) return;
    // Lines thicken a little as the street grows under them.
    const k = Math.max(0.75, Math.min(1.35, Math.log10(state.zoom) / 2.2));
    const widest = HEAT_CLASSES[HEAT_CLASSES.length - 1].width * k;
    ctx.save();
    ctx.globalAlpha = alpha;
    ctx.lineJoin = "round";
    ctx.lineCap = "round";
    // White casing under everything: it separates the tracks from the land
    // and from each other where two classes meet.
    ctx.beginPath();
    trackPath(state.heat.casing);
    ctx.strokeStyle = state.theme.casing;
    ctx.lineWidth = widest + 2.5;
    ctx.stroke();
    HEAT_CLASSES.forEach((cls, index) => {
      const geometry = state.heat.classes[index];
      if (!geometry.coordinates.length) return;
      ctx.beginPath();
      trackPath(geometry);
      ctx.strokeStyle = state.theme.heat[Math.min(index, state.theme.heat.length - 1)];
      ctx.lineWidth = cls.width * k;
      ctx.stroke();
    });
    ctx.restore();
  }

  /* -------------------------------------------------------------- paint */

  function graticule() {
    // Finer graticule as the globe fills with one region: 20 degree cells are
    // invisible at street scale and 1 degree cells are noise at globe scale.
    const step = state.zoom > 24 ? 1 : state.zoom > 6 ? 5 : 20;
    if (step !== state.graticuleStep) {
      state.graticuleStep = step;
      state.graticule = d3.geoGraticule().step([step, step])();
    }
    return state.graticule;
  }

  function markerRadius(cluster) {
    if (state.heat && heatAlpha() >= 1) {
      // At street scale a start is a small handle on its track, not a blob.
      return cluster.count === 1 ? 4 : 5 + Math.min(4, Math.log2(cluster.count));
    }
    const share = Math.sqrt(cluster.count / state.maxCount);
    return (4 + 10 * share) * (Math.min(baseRadius(), 320) / 300);
  }

  function draw() {
    const { w, h, dpr } = state.size;
    aim();
    const R = radius();
    const cx = w / 2;
    const cy = h / 2;

    ctx.save();
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, w, h);

    // The sphere as a lit ball, not a flat disc.
    const shade = ctx.createRadialGradient(
      cx - R * 0.35, cy - R * 0.4, R * 0.1, cx, cy, R
    );
    shade.addColorStop(0, state.theme.oceanLight || state.theme.ocean);
    shade.addColorStop(1, state.theme.ocean);
    ctx.beginPath();
    path(sphere);
    ctx.fillStyle = shade;
    ctx.fill();

    ctx.save();
    ctx.beginPath();
    path(sphere);
    ctx.clip();

    if (state.world) {
      ctx.beginPath();
      path(state.world.land);
      ctx.fillStyle = state.theme.land;
      ctx.fill();
      ctx.strokeStyle = state.theme.coast;
      ctx.lineWidth = 0.7;
      ctx.stroke();
    }

    // At street scale a meridian is just a stray straight line through town.
    if (state.zoom < HEAT_ZOOM * 2) {
      ctx.beginPath();
      path(graticule());
      ctx.strokeStyle = state.theme.graticule;
      ctx.lineWidth = 0.6;
      ctx.stroke();
    }

    if (state.world) {
      ctx.beginPath();
      path(state.world.borders);
      ctx.strokeStyle = state.theme.border;
      ctx.lineWidth = 0.6;
      ctx.stroke();
    }

    drawHeat();

    // Places, far side first so the near ones sit on top.
    const street = state.heat && heatAlpha() >= 1;
    const visible = [];
    for (let i = 0; i < state.clusters.length; i++) {
      const cluster = state.clusters[i];
      const d = depth(cluster.lon, cluster.lat);
      if (d <= 0.02) continue;
      const p = projection([cluster.lon, cluster.lat]);
      if (!p) continue;
      visible.push({ i, x: p[0], y: p[1], depth: d, cluster });
    }
    visible.sort((a, b) => a.depth - b.depth);
    for (const item of visible) {
      const r = markerRadius(item.cluster);
      const fade = Math.min(1, item.depth * 4);
      if (!street) {
        const glow = ctx.createRadialGradient(item.x, item.y, r * 0.6, item.x, item.y, r * 3);
        glow.addColorStop(0, rgba(state.theme.glow, 0.28 * fade));
        glow.addColorStop(1, rgba(state.theme.glow, 0));
        ctx.beginPath();
        ctx.arc(item.x, item.y, r * 3, 0, 2 * Math.PI);
        ctx.fillStyle = glow;
        ctx.fill();
      }

      ctx.beginPath();
      ctx.arc(item.x, item.y, item.i === state.hover ? r * 1.3 : r, 0, 2 * Math.PI);
      ctx.fillStyle = street
        ? state.theme.ink
        : rampColor(state.theme.ramp, 0.25 + 0.75 * Math.sqrt(item.cluster.count / state.maxCount));
      ctx.globalAlpha = fade;
      ctx.fill();
      ctx.lineWidth = street ? 2 : item.i === state.hover ? 2 : 1;
      ctx.strokeStyle = rgba(state.theme.surface, 0.85);
      ctx.stroke();
      ctx.globalAlpha = 1;
    }
    ctx.restore();

    // The rim reads as an edge, not as a cut-off.
    ctx.beginPath();
    path(sphere);
    ctx.strokeStyle = rgba(state.theme.glow, 0.25);
    ctx.lineWidth = 1;
    ctx.stroke();
    ctx.restore();
  }

  /* ------------------------------------------------------------- motion */

  function needsFrame() {
    return (
      state.fly !== null ||
      state.zoomTo !== null ||
      (state.spin && !state.dragging && state.zoom < SPIN_ZOOM) ||
      state.dirty
    );
  }

  function tick(now) {
    const dt = Math.min(0.06, (now - state.last) / 1000) || 0;
    state.last = now;

    if (state.zoomTo) {
      const k = Math.min(1, dt * 4);
      state.zoom *= Math.pow(state.zoomTo / state.zoom, k);
      if (Math.abs(state.zoomTo / state.zoom - 1) < 0.01) {
        state.zoom = state.zoomTo;
        state.zoomTo = null;
      }
      rebin();
      onZoom(state.zoom);
      state.dirty = true;
    }
    if (state.fly) {
      const k = Math.min(1, dt * 3.2);
      const dLon = deltaLon(state.rot.lon, state.fly.lon);
      const dLat = state.fly.lat - state.rot.lat;
      state.rot.lon = wrapLon(state.rot.lon + dLon * k);
      state.rot.lat += dLat * k;
      if (Math.abs(dLon) < 0.25 && Math.abs(dLat) < 0.25) {
        state.rot.lon = state.fly.lon;
        state.rot.lat = state.fly.lat;
        state.fly = null;
      }
      state.dirty = true;
    } else if (state.spin && !state.dragging && state.zoom < SPIN_ZOOM) {
      // Slower as the globe fills with one region: 9 deg/s at street level
      // would be a blur.
      state.rot.lon = wrapLon(state.rot.lon + (state.speed / Math.sqrt(state.zoom)) * dt);
      state.dirty = true;
    }

    if (state.dirty) {
      draw();
      state.dirty = false;
    }
    state.frame = needsFrame() ? requestAnimationFrame(tick) : null;
  }

  function kick() {
    state.dirty = true;
    if (state.frame === null) {
      state.last = performance.now();
      state.frame = requestAnimationFrame(tick);
    }
  }

  /* -------------------------------------------------------- interaction */

  function hit(x, y) {
    aim();
    let best = -1;
    let bestDepth = -1;
    for (let i = 0; i < state.clusters.length; i++) {
      const cluster = state.clusters[i];
      const d = depth(cluster.lon, cluster.lat);
      if (d <= 0.02) continue;
      const p = projection([cluster.lon, cluster.lat]);
      if (!p) continue;
      const r = Math.max(10, markerRadius(cluster) * 1.5);
      if ((p[0] - x) ** 2 + (p[1] - y) ** 2 <= r * r && d > bestDepth) {
        best = i;
        bestDepth = d;
      }
    }
    return best;
  }

  // The point under the cursor, so zooming pulls that spot to the centre
  // instead of drifting away from it.
  function under(x, y) {
    aim();
    const point = projection.invert([x, y]);
    if (!point || !isFinite(point[0]) || !isFinite(point[1])) return null;
    return { lon: point[0], lat: point[1] };
  }

  function setZoom(next, anchor) {
    const clamped = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, next));
    if (clamped === state.zoom) return;
    if (anchor) {
      state.rot.lon = anchor.lon;
      state.rot.lat = Math.max(-85, Math.min(85, anchor.lat));
      state.fly = null;
    }
    state.zoom = clamped;
    state.zoomTo = null;
    rebin();
    onZoom(state.zoom);
    kick();
  }

  let pointer = null;
  canvas.addEventListener("pointerdown", (event) => {
    canvas.setPointerCapture(event.pointerId);
    pointer = { x: event.offsetX, y: event.offsetY, moved: 0 };
    state.dragging = true;
  });
  canvas.addEventListener("pointermove", (event) => {
    if (pointer) {
      const dx = event.offsetX - pointer.x;
      const dy = event.offsetY - pointer.y;
      pointer.moved += Math.abs(dx) + Math.abs(dy);
      pointer.x = event.offsetX;
      pointer.y = event.offsetY;
      // Degrees per pixel follow the radius, so dragging feels the same at
      // every zoom instead of flinging the globe across the ocean.
      const k = (180 / (radius() * Math.PI)) * 2;
      state.rot.lon = wrapLon(state.rot.lon - dx * k);
      state.rot.lat = Math.max(-85, Math.min(85, state.rot.lat + dy * k));
      state.fly = null;
      kick();
      return;
    }
    const index = hit(event.offsetX, event.offsetY);
    if (index !== state.hover) {
      state.hover = index;
      canvas.style.cursor = index >= 0 ? "pointer" : "grab";
      kick();
    }
    onHover(index >= 0 ? state.clusters[index] : null, event.offsetX, event.offsetY);
  });
  const release = (event) => {
    if (!pointer) return;
    const tapped = pointer.moved < 5;
    pointer = null;
    state.dragging = false;
    if (tapped) {
      const index = hit(event.offsetX, event.offsetY);
      if (index >= 0) onPick(state.clusters[index]);
    }
    kick();
  };
  canvas.addEventListener("pointerup", release);
  canvas.addEventListener("pointercancel", release);
  canvas.addEventListener("pointerleave", () => {
    if (state.hover !== -1) {
      state.hover = -1;
      onHover(null, 0, 0);
      kick();
    }
  });
  canvas.addEventListener(
    "wheel",
    (event) => {
      event.preventDefault();
      setZoom(state.zoom * Math.exp(-event.deltaY * 0.0016), under(event.offsetX, event.offsetY));
    },
    { passive: false }
  );
  canvas.addEventListener("dblclick", (event) => {
    setZoom(state.zoom * 2.2, under(event.offsetX, event.offsetY));
  });

  /* ---------------------------------------------------------------- api */

  return {
    resize(w, h, dpr) {
      state.size = { w, h, dpr };
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
      canvas.style.width = w + "px";
      canvas.style.height = h + "px";
      rebin();
      kick();
    },
    setWorld(world) {
      state.world = world;
      kick();
    },
    setActivities(activities) {
      state.allActivities = (activities || []).map((a, index) => ({
        ...a,
        ts: a.ts == null ? index : a.ts,
      }));
      applySelection();
      kick();
    },
    /* Tracks as {id: [lat0, lon0, dlat, dlon, ...]} in 1e-5 degree integers,
       delta-encoded (see globe.tracks_url). Decoded once into flat
       [lat, lon, lat, lon, ...] arrays. */
    setTracks(encoded) {
      const tracks = new Map();
      for (const [id, flat] of Object.entries(encoded || {})) {
        const out = new Float64Array(flat.length);
        let lat = 0;
        let lon = 0;
        for (let k = 0; k < flat.length; k += 2) {
          lat += flat[k];
          lon += flat[k + 1];
          out[k] = lat / 1e5;
          out[k + 1] = lon / 1e5;
        }
        tracks.set(Number(id), out);
      }
      state.tracks = tracks;
      computeHeat();
      kick();
    },
    /* Activity ids the filters keep; null keeps everything. */
    setSelection(ids) {
      const next = ids ? new Set(ids.map(Number)) : null;
      const same =
        (next === null && state.selected === null) ||
        (next && state.selected && next.size === state.selected.size &&
          [...next].every((id) => state.selected.has(id)));
      if (same) return;
      state.selected = next;
      applySelection();
      kick();
    },
    setTheme(theme) {
      Object.assign(state.theme, theme || {});
      kick();
    },
    setSpin(spin) {
      state.spin = !!spin;
      kick();
    },
    setSpeed(speed) {
      state.speed = speed;
    },
    setZoom,
    zoom() {
      return state.zoom;
    },
    zoomBy(factor) {
      setZoom(state.zoom * factor, null);
    },
    flyTo(lon, lat, zoom) {
      state.fly = { lon: wrapLon(lon), lat: Math.max(-85, Math.min(85, lat)) };
      if (zoom) state.zoomTo = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, zoom));
      kick();
    },
    jumpTo(lon, lat, zoom) {
      state.rot = { lon: wrapLon(lon), lat: Math.max(-85, Math.min(85, lat)) };
      state.fly = null;
      if (zoom) {
        state.zoom = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, zoom));
        rebin();
        onZoom(state.zoom);
      }
      kick();
    },
    rotation() {
      return { ...state.rot };
    },
    clusters() {
      return state.clusters;
    },
    drawOnce() {
      draw();
    },
  };
}
