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
 * Two faces, one renderer: below FLAT_ZOOM an orthographic globe, above it a
 * flat Web Mercator map in a rounded frame with OpenStreetMap raster tiles
 * underneath. The switch happens once the sphere already
 * fills the frame, with the scale matched at the centre, so zooming in reads as
 * the globe flattening rather than a cut. Tiles are the only thing fetched from
 * the internet; offline the flat map falls back to the vendored land outline.
 *
 * The heat layer: past HEAT_ZOOM the globe is at city scale and the start
 * markers give way to the tracks themselves, each stretch coloured and
 * thickened by how many distinct activities ran through it. Counting happens
 * here, not in Python, so changing the sport filter sends a list of ids and the
 * browser recounts -- the tracks themselves arrive once, as a cached file.
 */

export const MIN_ZOOM = 1;
// Street level: at 40000x a kilometre is a couple of thousand pixels and the
// tiles are at their most detailed level.
export const MAX_ZOOM = 40000;
// Where the globe turns into a flat map: the sphere fills the frame by then,
// so no limb disappears at the switch.
export const FLAT_ZOOM = 4;
// Where the tracks take over from the start markers, and where spinning stops
// (a turning globe at city scale is a map sliding out from under the cursor).
export const HEAT_ZOOM = 14;
const SPIN_ZOOM = FLAT_ZOOM;
const FRAME_RADIUS = 26;

// The OpenStreetMap standard tiles: open, no key (CARTO's raster basemaps now
// answer every request with an "API key required" image). The attribution in
// index.html is a condition of use. One style serves both themes; the canvas
// filter mutes it on light and inverts it on dark, so the heat tracks stay the
// loudest thing on the map.
const TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const TILE_FILTER = {
  light: "saturate(0.35) brightness(1.04) contrast(0.92)",
  dark: "invert(1) hue-rotate(180deg) saturate(0.3) brightness(0.82) contrast(0.9)",
};
const TILE_MAX_Z = 19;
const TILE_CACHE = 600;

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
  const ortho = d3.geoOrthographic().clipAngle(90).precision(0.4);
  const mercator = d3.geoMercator().precision(0.4);
  // Tracks are dense already; adaptive resampling on tens of thousands of
  // points per frame would buy nothing visible and cost the frame rate.
  const orthoTrack = d3.geoOrthographic().clipAngle(90).precision(0);
  const mercatorTrack = d3.geoMercator().precision(0);
  let projection = ortho;
  let trackProjection = orthoTrack;
  const path = d3.geoPath(ortho, ctx);
  const trackPath = d3.geoPath(orthoTrack, ctx);
  const sphere = { type: "Sphere" };
  const tiles = new Map();

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
      tiles: "light",
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
    binKey: null,
    // Markers dim while the zoom moves and come back once it settles.
    markerAlpha: 1,
    zoomedAt: -1e9,
    frame: null,
    last: 0,
    size: { w: 600, h: 600, dpr: 1 },
  };
  const onPick = options.onPick || function () {};
  const onHover = options.onHover || function () {};
  const onZoom = options.onZoom || function () {};

  const baseRadius = () => Math.min(state.size.w, state.size.h) / 2 - 6;
  const radius = () => baseRadius() * state.zoom;

  const flat = () => state.zoom >= FLAT_ZOOM;

  function aim() {
    const centre = [state.size.w / 2, state.size.h / 2];
    if (flat()) {
      // Mercator draws a radian of longitude as s px and stretches latitude by
      // 1/cos: s = R*cos(lat) gives the centre the same scale the globe had.
      const s = radius() * Math.cos(state.rot.lat * RAD);
      for (const p of [mercator, mercatorTrack]) {
        p.rotate([-state.rot.lon, 0]).center([0, state.rot.lat]).scale(s).translate(centre)
          // Without a clip the land outline at street scale has vertices
          // millions of pixels away, which canvas fills unreliably.
          .clipExtent([[-20, -20], [state.size.w + 20, state.size.h + 20]]);
      }
      projection = mercator;
      trackProjection = mercatorTrack;
    } else {
      for (const p of [ortho, orthoTrack]) {
        p.translate(centre).scale(radius()).rotate([-state.rot.lon, -state.rot.lat]);
      }
      projection = ortho;
      trackProjection = orthoTrack;
    }
    path.projection(projection);
    trackPath.projection(trackProjection);
  }

  // Front of the sphere: d3 clips paths for us, but a marker is drawn by hand
  // and has to be told whether it is behind the globe. On the flat map
  // everything is in front; off-canvas markers are skipped by position.
  function depth(lon, lat) {
    if (flat()) return 1;
    const c = d3.geoDistance([lon, lat], [state.rot.lon, state.rot.lat]);
    return Math.cos(c);
  }

  /* -------------------------------------------------------------- tiles */

  function tileStyle() {
    return TILE_FILTER[state.theme.tiles] ? state.theme.tiles : null;
  }

  // The filter is applied when drawing, so both themes share one cache.
  function tileKey(z, x, y) {
    return `${z}/${x}/${y}`;
  }

  function requestTile(z, x, y) {
    const key = tileKey(z, x, y);
    let entry = tiles.get(key);
    if (entry) return entry;
    const img = new Image();
    img.crossOrigin = "anonymous";
    entry = { img, ok: false };
    img.onload = () => {
      entry.ok = true;
      kick();
    };
    img.src = TILE_URL.replace("{z}", z).replace("{x}", x).replace("{y}", y);
    tiles.set(key, entry);
    // Oldest first out; what is on screen was requested last.
    while (tiles.size > TILE_CACHE) tiles.delete(tiles.keys().next().value);
    return entry;
  }

  /* Raster tiles under the flat map. Positions come straight from Web
     Mercator tile maths (the same spherical Mercator d3 draws), and a tile
     still in flight is stood in for by the nearest loaded ancestor, so a zoom
     step blurs for a moment instead of flashing the ocean. */
  function drawTiles() {
    const style = tileStyle();
    if (!style) return;
    const { w, h } = state.size;
    const world = 2 * Math.PI * mercator.scale();
    // One level finer on a retina screen: OSM tiles are 256 px only.
    const sharp = state.size.dpr > 1 ? 1 : 0;
    const z = Math.max(0, Math.min(TILE_MAX_Z, Math.round(Math.log2(world / 256)) + sharp));
    const n = 2 ** z;
    const size = world / n;
    const lat = state.rot.lat * RAD;
    const cx = ((state.rot.lon + 180) / 360) * n;
    const cy = ((1 - Math.log(Math.tan(lat) + 1 / Math.cos(lat)) / Math.PI) / 2) * n;
    const x0 = Math.floor(cx - w / 2 / size);
    const x1 = Math.floor(cx + w / 2 / size);
    const y0 = Math.max(0, Math.floor(cy - h / 2 / size));
    const y1 = Math.min(n - 1, Math.floor(cy + h / 2 / size));
    ctx.save();
    ctx.filter = TILE_FILTER[style];
    for (let ty = y0; ty <= y1; ty++) {
      for (let tx = x0; tx <= x1; tx++) {
        const wx = ((tx % n) + n) % n;
        const sx = w / 2 + (tx - cx) * size;
        const sy = h / 2 + (ty - cy) * size;
        const entry = requestTile(z, wx, ty);
        if (entry.ok) {
          ctx.drawImage(entry.img, sx, sy, size + 0.5, size + 0.5);
          continue;
        }
        for (let dz = 1; dz <= Math.min(6, z); dz++) {
          const parent = tiles.get(tileKey(z - dz, wx >> dz, ty >> dz));
          if (!parent || !parent.ok) continue;
          const part = parent.img.naturalWidth / 2 ** dz;
          const ox = wx - ((wx >> dz) << dz);
          const oy = ty - ((ty >> dz) << dz);
          ctx.drawImage(parent.img, ox * part, oy * part, part, part, sx, sy, size + 0.5, size + 0.5);
          break;
        }
      }
    }
    ctx.restore();
  }

  function frame() {
    const { w, h } = state.size;
    ctx.beginPath();
    if (ctx.roundRect) ctx.roundRect(0.5, 0.5, w - 1, h - 1, FRAME_RADIUS);
    else ctx.rect(0.5, 0.5, w - 1, h - 1);
  }

  /* -------------------------------------------------------- clustering */

  // Markers are grouped so they never overlap: the grid is whatever 26 px is
  // worth in degrees. Zoom in and a city falls apart into its parks, then into
  // single activities -- and a single activity is a link straight to that
  // activity.
  //
  // The grid moves in whole levels, one per doubling of zoom, and each level
  // halves the cells of the one before. Re-binning on every wheel event (a
  // continuous grid) reshuffled the groups dozens of times a second and the
  // markers jumped; with nested levels a group only ever splits into its own
  // parts, and the split happens while the markers are dimmed for the zoom.
  function rebin(force = false) {
    const level = Math.max(0, Math.floor(Math.log2(state.zoom)));
    const key = `${level}:${baseRadius()}`;
    if (!force && key === state.binKey) return;
    state.binKey = key;
    const grid = Math.max(0.0002, (26 * 180) / (Math.PI * baseRadius() * 2 ** level));
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
    rebin(true);
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
    if (flat()) {
      // On the map a start is an annotation, not a bubble: a small dot, and a
      // group only as big as its number needs.
      return cluster.count === 1 ? 3.5 : 7 + Math.min(4, Math.log2(cluster.count));
    }
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

    if (flat()) {
      drawFlat();
      ctx.restore();
      return;
    }

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
    drawMarkers();
    ctx.restore();

    // The rim reads as an edge, not as a cut-off.
    ctx.beginPath();
    path(sphere);
    ctx.strokeStyle = rgba(state.theme.glow, 0.25);
    ctx.lineWidth = 1;
    ctx.stroke();
    ctx.restore();
  }

  function drawFlat() {
    frame();
    ctx.fillStyle = state.theme.ocean;
    ctx.fill();
    ctx.save();
    frame();
    ctx.clip();
    // Vendored outline first: it is what stays when the tiles cannot load.
    if (state.world) {
      ctx.beginPath();
      path(state.world.land);
      ctx.fillStyle = state.theme.land;
      ctx.fill();
    }
    drawTiles();
    drawHeat();
    drawMarkers();
    ctx.restore();
    frame();
    ctx.strokeStyle = rgba(state.theme.glow, 0.25);
    ctx.lineWidth = 1;
    ctx.stroke();
  }

  function drawMarkers() {
    const { w, h } = state.size;
    // Places, far side first so the near ones sit on top.
    const street = state.heat && heatAlpha() >= 1;
    const visible = [];
    for (let i = 0; i < state.clusters.length; i++) {
      const cluster = state.clusters[i];
      const d = depth(cluster.lon, cluster.lat);
      if (d <= 0.02) continue;
      const p = projection([cluster.lon, cluster.lat]);
      if (!p || p[0] < -40 || p[0] > w + 40 || p[1] < -40 || p[1] > h + 40) continue;
      visible.push({ i, x: p[0], y: p[1], depth: d, cluster });
    }
    visible.sort((a, b) => a.depth - b.depth);
    const alpha = state.markerAlpha;
    if (alpha <= 0.01) return;
    if (flat()) {
      drawAnnotations(visible, alpha);
      return;
    }
    for (const item of visible) {
      const r = markerRadius(item.cluster);
      const fade = Math.min(1, item.depth * 4);
      if (!street) {
        const glow = ctx.createRadialGradient(item.x, item.y, r * 0.6, item.x, item.y, r * 3);
        glow.addColorStop(0, rgba(state.theme.glow, 0.28 * fade * alpha));
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
      ctx.globalAlpha = fade * alpha;
      ctx.fill();
      ctx.lineWidth = street ? 2 : item.i === state.hover ? 2 : 1;
      ctx.strokeStyle = rgba(state.theme.surface, 0.85);
      ctx.stroke();
      ctx.globalAlpha = 1;
    }
  }

  // Starts on the flat map: a dot with a halo in the surface colour for one
  // activity, a small disc with its count for a group. No glow -- the tiles
  // and the heat tracks are the picture, the starts only annotate it.
  function drawAnnotations(visible, alpha) {
    const t = state.theme;
    ctx.save();
    ctx.globalAlpha = alpha;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.font = '600 10px "Source Sans Pro", -apple-system, "Segoe UI", sans-serif';
    for (const item of visible) {
      const hover = item.i === state.hover;
      const r = markerRadius(item.cluster) * (hover ? 1.25 : 1);
      ctx.beginPath();
      ctx.arc(item.x, item.y, r, 0, 2 * Math.PI);
      ctx.lineWidth = 1.6;
      ctx.strokeStyle = rgba(t.surface, 0.9);
      if (item.cluster.count === 1) {
        ctx.fillStyle = rgba(t.ink, hover ? 0.95 : 0.7);
        ctx.fill();
        ctx.stroke();
        continue;
      }
      ctx.fillStyle = rgba(t.glow, hover ? 0.95 : 0.78);
      ctx.fill();
      ctx.stroke();
      ctx.fillStyle = "#ffffff";
      ctx.fillText(item.cluster.count > 99 ? "99+" : String(item.cluster.count), item.x, item.y + 0.5);
    }
    ctx.restore();
  }

  /* ------------------------------------------------------------- motion */

  const ZOOM_SETTLE_MS = 220;
  const markerTarget = (now) => (now - state.zoomedAt < ZOOM_SETTLE_MS ? 0.08 : 1);

  function needsFrame() {
    return (
      state.fly !== null ||
      state.zoomTo !== null ||
      (state.spin && !state.dragging && state.zoom < SPIN_ZOOM) ||
      state.dirty ||
      Math.abs(markerTarget(performance.now()) - state.markerAlpha) > 0.01 ||
      performance.now() - state.zoomedAt < ZOOM_SETTLE_MS
    );
  }

  function tick(now) {
    const dt = Math.min(0.06, (now - state.last) / 1000) || 0;
    state.last = now;

    const target = markerTarget(now);
    if (Math.abs(target - state.markerAlpha) > 0.01) {
      // Out fast (they should be gone by the second wheel event), back gently.
      const rate = target < state.markerAlpha ? 18 : 6;
      state.markerAlpha += (target - state.markerAlpha) * Math.min(1, dt * rate);
      state.dirty = true;
    } else if (state.markerAlpha !== target) {
      state.markerAlpha = target;
      state.dirty = true;
    }

    if (state.zoomTo) {
      state.zoomedAt = now;
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
    // Dimmed for a zoom: nothing to point at until they are back.
    if (state.markerAlpha < 0.5) return -1;
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

  /* Zoom keeping the place under the cursor under the cursor. (Recentring on
     that place instead made every wheel event a jump -- a trackpad sends
     dozens a second.) The rotation is nudged until the point lands back under
     the pointer; two or three passes are exact to a fraction of a pixel, also
     across the globe-to-flat switch. */
  function setZoom(next, cursor) {
    const clamped = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, next));
    if (clamped === state.zoom) return;
    const pinned = cursor ? under(cursor.x, cursor.y) : null;
    state.zoom = clamped;
    state.zoomedAt = performance.now();
    if (pinned) {
      for (let pass = 0; pass < 3; pass++) {
        const now = under(cursor.x, cursor.y);
        if (!now) break;
        state.rot.lon = wrapLon(state.rot.lon + deltaLon(now.lon, pinned.lon));
        state.rot.lat = Math.max(-85, Math.min(85, state.rot.lat + pinned.lat - now.lat));
      }
      state.fly = null;
    }
    state.zoomTo = null;
    rebin();
    onZoom(state.zoom);
    kick();
  }

  let pointer = null;
  // Touch screens: two fingers on the canvas are a pinch.
  const touches = new Map();
  let pinch = null;
  const spread = () => {
    const [a, b] = [...touches.values()];
    return { d: Math.hypot(a.x - b.x, a.y - b.y), x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
  };
  canvas.addEventListener("pointerdown", (event) => {
    canvas.setPointerCapture(event.pointerId);
    if (event.pointerType === "touch") {
      touches.set(event.pointerId, { x: event.offsetX, y: event.offsetY });
      if (touches.size === 2) {
        pinch = { ...spread(), zoom: state.zoom };
        pointer = null;
        return;
      }
    }
    pointer = { x: event.offsetX, y: event.offsetY, moved: 0 };
    state.dragging = true;
  });
  canvas.addEventListener("pointermove", (event) => {
    if (touches.has(event.pointerId)) touches.set(event.pointerId, { x: event.offsetX, y: event.offsetY });
    if (pinch && touches.size === 2) {
      const now = spread();
      setZoom(pinch.zoom * (now.d / Math.max(1, pinch.d)), { x: now.x, y: now.y });
      return;
    }
    if (pointer) {
      const dx = event.offsetX - pointer.x;
      const dy = event.offsetY - pointer.y;
      pointer.moved += Math.abs(dx) + Math.abs(dy);
      pointer.x = event.offsetX;
      pointer.y = event.offsetY;
      if (flat()) {
        // The map follows the hand exactly: a pixel is 1/R radians of
        // latitude and 1/(R cos lat) of longitude at the centre.
        const k = 180 / (radius() * Math.PI);
        state.rot.lon = wrapLon(state.rot.lon - (dx * k) / Math.cos(state.rot.lat * RAD));
        state.rot.lat = Math.max(-85, Math.min(85, state.rot.lat + dy * k));
      } else {
        // Degrees per pixel follow the radius, so dragging feels the same at
        // every zoom instead of flinging the globe across the ocean.
        const k = (180 / (radius() * Math.PI)) * 2;
        state.rot.lon = wrapLon(state.rot.lon - dx * k);
        state.rot.lat = Math.max(-85, Math.min(85, state.rot.lat + dy * k));
      }
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
    touches.delete(event.pointerId);
    if (touches.size < 2) pinch = null;
    if (!pointer) {
      state.dragging = false;
      return;
    }
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
      let dy = event.deltaY;
      if (event.deltaMode === 1) dy *= 16;
      else if (event.deltaMode === 2) dy *= state.size.h;
      // A trackpad pinch arrives as ctrl+wheel with small deltas; a mouse
      // notch as ~100 at once, capped so one notch is one step, not a leap.
      const k = event.ctrlKey ? 0.012 : 0.002;
      dy = Math.max(-120, Math.min(120, dy));
      setZoom(state.zoom * Math.exp(-dy * k), { x: event.offsetX, y: event.offsetY });
    },
    { passive: false }
  );
  // Safari reports a trackpad pinch as gesture events, not as wheel.
  let gesture = null;
  const local = (event) => {
    const box = canvas.getBoundingClientRect();
    return { x: event.clientX - box.left, y: event.clientY - box.top };
  };
  canvas.addEventListener("gesturestart", (event) => {
    event.preventDefault();
    gesture = { zoom: state.zoom, at: local(event) };
  });
  canvas.addEventListener("gesturechange", (event) => {
    event.preventDefault();
    if (gesture) setZoom(gesture.zoom * event.scale, gesture.at);
  });
  canvas.addEventListener("gestureend", (event) => {
    event.preventDefault();
    gesture = null;
  });
  canvas.addEventListener("dblclick", (event) => {
    setZoom(state.zoom * 2.2, { x: event.offsetX, y: event.offsetY });
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
    flat,
    under,
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
