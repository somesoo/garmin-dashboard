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
 * activities per zoom level, the animation, and the interaction.
 */

export const MIN_ZOOM = 1;
export const MAX_ZOOM = 160;

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
  const sphere = { type: "Sphere" };

  const state = {
    world: null,
    graticule: null,
    graticuleStep: null,
    activities: [],
    clusters: [],
    theme: {
      ocean: "#cfe0f1", oceanLight: "#e8f1fa", land: "#e6e3d8", coast: "#b3b0a4",
      border: "#c6c3b7", graticule: "rgba(120,140,160,0.22)", surface: "#fcfcfb",
      ink: "#0b0b0b", glow: "#2a78d6",
      ramp: ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"],
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
    projection
      .translate([state.size.w / 2, state.size.h / 2])
      .scale(radius())
      .rotate([-state.rot.lon, -state.rot.lat]);
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
    const grid = Math.max(0.0015, (26 * 180) / (Math.PI * radius()));
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

    ctx.beginPath();
    path(graticule());
    ctx.strokeStyle = state.theme.graticule;
    ctx.lineWidth = 0.6;
    ctx.stroke();

    if (state.world) {
      ctx.beginPath();
      path(state.world.borders);
      ctx.strokeStyle = state.theme.border;
      ctx.lineWidth = 0.6;
      ctx.stroke();
    }

    // Places, far side first so the near ones sit on top.
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
      const glow = ctx.createRadialGradient(item.x, item.y, r * 0.6, item.x, item.y, r * 3);
      glow.addColorStop(0, rgba(state.theme.glow, 0.28 * fade));
      glow.addColorStop(1, rgba(state.theme.glow, 0));
      ctx.beginPath();
      ctx.arc(item.x, item.y, r * 3, 0, 2 * Math.PI);
      ctx.fillStyle = glow;
      ctx.fill();

      ctx.beginPath();
      ctx.arc(item.x, item.y, item.i === state.hover ? r * 1.3 : r, 0, 2 * Math.PI);
      ctx.fillStyle = rampColor(
        state.theme.ramp,
        0.25 + 0.75 * Math.sqrt(item.cluster.count / state.maxCount)
      );
      ctx.globalAlpha = fade;
      ctx.fill();
      ctx.lineWidth = item.i === state.hover ? 2 : 1;
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
      (state.spin && !state.dragging) ||
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
    } else if (state.spin && !state.dragging) {
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
      state.activities = (activities || []).map((a, index) => ({
        ...a,
        ts: a.ts == null ? index : a.ts,
      }));
      rebin();
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
