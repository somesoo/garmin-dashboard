const TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const CACHE_SIZE = 600;
const MAX_LOADING = 4;
const SETTLE_MS = 220;

export function tileKey(zoom, column, row) {
  return `${zoom}/${column}/${row}`;
}

export function createTileCache(onChange) {
  const entries = new Map();
  let viewport = "";
  let timer = null;
  let pending = [];
  let loading = 0;
  let failed = false;

  function load() {
    while (!failed && loading < MAX_LOADING && pending.length) {
      const [zoom, column, row] = pending.shift();
      const key = tileKey(zoom, column, row);
      if (entries.has(key)) continue;
      const image = new Image();
      image.crossOrigin = "anonymous";
      image.referrerPolicy = "strict-origin";
      const entry = { img: image, ok: false };
      entries.set(key, entry);
      loading += 1;
      image.onload = () => {
        entry.ok = true;
        loading -= 1;
        load();
        onChange();
      };
      image.onerror = () => {
        loading -= 1;
        failed = true;
        pending = [];
        clearTimeout(timer);
        onChange();
      };
      image.src = TILE_URL.replace("{z}", zoom).replace("{x}", column).replace("{y}", row);
      while (entries.size > CACHE_SIZE) {
        const oldest = entries.keys().next().value;
        entries.delete(oldest);
      }
    }
  }

  return {
    get(zoom, column, row) {
      const key = tileKey(zoom, column, row);
      const entry = entries.get(key);
      if (entry) {
        entries.delete(key);
        entries.set(key, entry);
      }
      return entry;
    },
    setVisible(coordinates) {
      const next = coordinates.map((coordinate) => tileKey(...coordinate)).join(";");
      if (next === viewport) return;
      viewport = next;
      clearTimeout(timer);
      pending = [];
      if (failed || !coordinates.length) return;
      timer = setTimeout(() => {
        pending = coordinates.filter((coordinate) => !entries.has(tileKey(...coordinate)));
        load();
      }, SETTLE_MS);
    },
  };
}
