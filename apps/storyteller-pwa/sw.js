// Service Worker for Storyteller PWA
const CACHE_VERSION = "storyteller-v1";
const SHELL_CACHE = `${CACHE_VERSION}-shell`;
const API_CACHE = `${CACHE_VERSION}-api`;

const SHELL_ASSETS = [
  "./",
  "./index.html",
  "./style.css",
  "./app.js",
  "./manifest.json",
  "./icons/icon.svg",
  "./icons/icon-192.png",
  "./icons/icon-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(SHELL_CACHE).then((c) => c.addAll(SHELL_ASSETS)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => !k.startsWith(CACHE_VERSION)).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") return;
  var url = new URL(event.request.url);

  // API calls: network-first, cache fallback.
  if (url.pathname.startsWith("/api/")) {
    event.respondWith(
      fetch(event.request).then((response) => {
        var clone = response.clone();
        caches.open(API_CACHE).then((c) => c.put(event.request, clone));
        return response;
      }).catch(() => caches.match(event.request).then((r) => r || new Response("Offline", { status: 503 })))
    );
    return;
  }

  // Pollinations images: cache-first (they are deterministic URLs).
  if (url.hostname === "image.pollinations.ai") {
    event.respondWith(
      caches.match(event.request).then((cached) => cached || fetch(event.request).then((response) => {
        if (response && response.status === 200) {
          var clone = response.clone();
          caches.open(SHELL_CACHE).then((c) => c.put(event.request, clone));
        }
        return response;
      }))
    );
    return;
  }

  // App shell: cache-first.
  event.respondWith(
    caches.match(event.request).then((cached) => cached || fetch(event.request).then((response) => {
      if (response && response.status === 200) {
        var clone = response.clone();
        caches.open(SHELL_CACHE).then((c) => c.put(event.request, clone));
      }
      return response;
    }))
  );
});
