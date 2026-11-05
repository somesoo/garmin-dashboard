// The dashboard itself as an installed app, with its own window and no address
// bar. Android gives a home-screen icon that window only when the manifest's
// start_url sits inside the scope of a service worker that has a fetch handler
// -- the manifest and the Apple meta tags alone buy a bookmark, nothing more.
// The phone app's worker (sw.js) covers only /api/app/, so the dashboard needs
// its own; it is served from there too, and claims "/" through the
// Service-Worker-Allowed header the API sends with it (api.py).
//
// Streamlit is a live WebSocket app, so nothing here caches data. The one
// cached thing is the page shell, and only so that tapping the icon with no
// network answers something instead of failing. Bump VERSION on change.
"use strict";
const VERSION = "gd-dashboard-1";
const SHELL = "/";

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(VERSION).then((cache) => cache.add(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  // Only this app's own caches: the phone app keeps its "gd-shell-*" next door.
  event.waitUntil(caches.keys()
    .then((keys) => Promise.all(keys.filter((key) => key.startsWith("gd-dashboard") && key !== VERSION)
      .map((key) => caches.delete(key))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  // The page itself and nothing else: Streamlit's assets, its WebSocket and
  // everything under /api (the phone app has its own worker) go to the network
  // untouched.
  if (request.method !== "GET" || request.mode !== "navigate") return;
  const url = new URL(request.url);
  if (url.origin !== location.origin || url.pathname.startsWith("/api/")) return;
  // Network first -- a cached dashboard would be a lie about today's numbers.
  event.respondWith(fetch(request)
    .then((response) => {
      if (response.ok) {
        const copy = response.clone();
        caches.open(VERSION).then((cache) => cache.put(SHELL, copy));
      }
      return response;
    })
    .catch(() => caches.match(SHELL).then((hit) => hit || Response.error())));
});
