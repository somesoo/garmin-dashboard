import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { runInNewContext } from "node:vm";
import { createGlobe } from "../ui/components/globe/globe.js";
import { createTileCache } from "../ui/components/globe/tiles.js";

function harness(context) {
  const requests = [];
  const timers = new Map();
  const previousImage = globalThis.Image;
  let sequence = 0;
  let changes = 0;
  globalThis.Image = class {
    set src(value) {
      this.url = value;
      requests.push(this);
    }
  };
  context.after(() => {
    if (previousImage === undefined) delete globalThis.Image;
    else globalThis.Image = previousImage;
  });
  context.mock.method(globalThis, "setTimeout", (callback, delay) => {
    assert.equal(delay, 220);
    timers.set(++sequence, callback);
    return sequence;
  });
  context.mock.method(globalThis, "clearTimeout", (identifier) => timers.delete(identifier));
  return {
    cache: createTileCache(() => changes++),
    requests,
    changes: () => changes,
    settle() {
      for (const [identifier, callback] of [...timers]) {
        timers.delete(identifier);
        callback();
      }
    },
  };
}

function renderer(context) {
  const loader = harness(context);
  const vendor = {};
  for (const name of ["d3-array", "d3-geo"]) {
    runInNewContext(readFileSync(new URL(`../ui/components/globe/vendor/${name}.min.js`, import.meta.url), "utf8"), vendor);
  }
  const previousWindow = globalThis.window;
  globalThis.window = { d3: vendor.d3 };
  context.after(() => {
    if (previousWindow === undefined) delete globalThis.window;
    else globalThis.window = previousWindow;
  });
  const previousAnimation = globalThis.requestAnimationFrame;
  globalThis.requestAnimationFrame = () => 1;
  context.after(() => {
    if (previousAnimation === undefined) delete globalThis.requestAnimationFrame;
    else globalThis.requestAnimationFrame = previousAnimation;
  });
  const drawing = new Proxy({}, { get: (target, key) => target[key] ?? (() => {}) });
  const globe = createGlobe({
    getContext: () => drawing,
    addEventListener() {},
    style: {},
  });
  globe.setSpin(false);
  globe.resize(600, 400, 1);
  return { ...loader, globe };
}

test("visible tiles wait for settling and use the canonical URL and origin referrer", (context) => {
  const { cache, requests, settle } = harness(context);
  cache.setVisible([[12, 2286, 1345]]);
  assert.equal(requests.length, 0);
  settle();
  assert.equal(requests.length, 1);
  assert.equal(requests[0].url, "https://tile.openstreetmap.org/12/2286/1345.png");
  assert.equal(requests[0].referrerPolicy, "strict-origin");
  assert.equal(requests[0].crossOrigin, "anonymous");
  assert.equal(cache.get(12, 2286, 1345).ok, false);
  requests[0].onload();
  assert.equal(cache.get(12, 2286, 1345).ok, true);
});

test("camera motion replaces the pending viewport instead of prefetching", (context) => {
  const { cache, requests, settle } = harness(context);
  cache.setVisible([[12, 1, 1]]);
  cache.setVisible([[13, 2, 2]]);
  settle();
  assert.deepEqual(requests.map((image) => image.url), ["https://tile.openstreetmap.org/13/2/2.png"]);
});

test("returning to the sphere cancels scheduled downloads", (context) => {
  const { cache, requests, settle } = harness(context);
  cache.setVisible([[12, 1, 1]]);
  cache.setVisible([]);
  settle();
  assert.equal(requests.length, 0);
});

test("at most four requests run concurrently and successful loads drain the queue", (context) => {
  const { cache, requests, settle, changes } = harness(context);
  cache.setVisible(Array.from({ length: 10 }, (_, column) => [12, column, 1]));
  settle();
  assert.equal(requests.length, 4);
  for (let completed = 0; completed < 10; completed++) {
    requests[completed].onload();
    assert.ok(requests.length - completed - 1 <= 4);
  }
  assert.equal(requests.length, 10);
  assert.equal(changes(), 10);
});

test("changing viewport drops queued old tiles even while requests are in flight", (context) => {
  const { cache, requests, settle } = harness(context);
  cache.setVisible(Array.from({ length: 10 }, (_, column) => [12, column, 1]));
  settle();
  cache.setVisible([[13, 20, 2]]);
  requests[0].onload();
  assert.equal(requests.length, 4);
  settle();
  assert.equal(requests.length, 5);
  assert.equal(requests[4].url, "https://tile.openstreetmap.org/13/20/2.png");
});

test("repeat views reuse decoded images without duplicate downloads", (context) => {
  const { cache, requests, settle } = harness(context);
  cache.setVisible([[12, 1, 1], [12, 1, 1]]);
  settle();
  requests[0].onload();
  cache.setVisible([]);
  cache.setVisible([[12, 1, 1]]);
  settle();
  assert.equal(requests.length, 1);
});

test("a denied or failed request stops the queue and prevents retry storms", (context) => {
  const { cache, requests, settle } = harness(context);
  cache.setVisible(Array.from({ length: 10 }, (_, column) => [12, column, 1]));
  settle();
  requests[0].onerror();
  requests[1].onload();
  assert.equal(requests.length, 4);
  cache.setVisible([[13, 20, 2]]);
  settle();
  assert.equal(requests.length, 4);
  assert.equal(cache.get(12, 0, 1).ok, false);
  assert.equal(cache.get(12, 1, 1).ok, true);
});

test("the renderer cancels flat-map requests when returning to the globe", (context) => {
  const { globe, requests, settle } = renderer(context);
  globe.jumpTo(21, 52, 250);
  globe.drawOnce();
  globe.jumpTo(21, 52, 1);
  globe.drawOnce();
  settle();
  assert.equal(requests.length, 0);
});

test("animated flights do not download intermediate map views", (context) => {
  const { globe, requests, settle } = renderer(context);
  globe.jumpTo(21, 52, 250);
  globe.flyTo(17, 51, 500);
  globe.drawOnce();
  settle();
  assert.equal(requests.length, 0);
});

test("Retina rendering reuses the same OSM zoom level and tiles", (context) => {
  const { globe, requests, settle } = renderer(context);
  globe.jumpTo(21, 52, 250);
  globe.drawOnce();
  settle();
  for (let completed = 0; completed < requests.length; completed++) requests[completed].onload();
  const loaded = requests.length;
  assert.ok(loaded > 0);
  globe.resize(600, 400, 2);
  globe.drawOnce();
  settle();
  assert.equal(requests.length, loaded);
});
