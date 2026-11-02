// Offline shell: the app's own files from the cache, data never (app.js keeps
// the last summary itself, behind the person's key). Bump VERSION on change.
"use strict";
const VERSION = "gd-shell-1";
const SHELL = ["./", "index.html", "app.js", "app.css", "manifest.webmanifest", "icon.svg", "icon-192.png", "icon-512.png"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(VERSION).then((cache) => cache.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(caches.keys()
    .then((keys) => Promise.all(keys.filter((key) => key !== VERSION).map((key) => caches.delete(key))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  const shell = event.request.method === "GET" && url.origin === location.origin
    && url.pathname.startsWith(new URL("./", self.registration.scope).pathname);
  if (!shell) return; // API calls go to the network untouched
  // Network first (a new version shows up at once), the cache when offline.
  event.respondWith(fetch(event.request)
    .then((response) => {
      if (response.ok) caches.open(VERSION).then((cache) => cache.put(event.request, response.clone()));
      return response;
    })
    .catch(() => caches.match(event.request).then((hit) => hit || caches.match("index.html"))));
});
