// Service Worker for News Curator PWA
// Caches the app shell for offline use and serves stale-while-revalidate for API calls.

const CACHE_VERSION = "news-curator-v1";
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

// Install: pre-cache the app shell.
self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(SHELL_CACHE).then((cache) => cache.addAll(SHELL_ASSETS)).then(() => self.skipWaiting())
  );
});

// Activate: clean up old caches.
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((key) => !key.startsWith(CACHE_VERSION))
          .map((key) => caches.delete(key))
      )
    ).then(() => self.clients.claim())
  );
});

// Fetch: shell -> cache-first; API -> network-first, fall back to cache.
self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);

  // Only handle GET.
  if (event.request.method !== "GET") return;

  // API calls: network-first with cache fallback.
  if (url.pathname.startsWith("/api/")) {
    event.respondWith(
      fetch(event.request)
        .then((response) => {
          const clone = response.clone();
          caches.open(API_CACHE).then((cache) => cache.put(event.request, clone));
          return response;
        })
        .catch(() => caches.match(event.request).then((r) => r || new Response("Offline", { status: 503 })))
    );
    return;
  }

  // App shell: cache-first, then network.
  event.respondWith(
    caches.match(event.request).then((cached) => {
      if (cached) return cached;
      return fetch(event.request).then((response) => {
        if (!response || response.status !== 200) return response;
        const clone = response.clone();
        caches.open(SHELL_CACHE).then((cache) => cache.put(event.request, clone));
        return response;
      });
    })
  );
});

// Push: display notification.
self.addEventListener("push", (event) => {
  let data = { title: "News Curator", body: "New briefing available" };
  try {
    data = event.data.json();
  } catch {
    data.body = event.data ? event.data.text() : data.body;
  }
  event.waitUntil(
    self.registration.showNotification(data.title || "News Curator", {
      body: data.body,
      icon: "icons/icon-192.png",
      badge: "icons/icon-192.png",
      vibrate: [100, 50, 100],
      data: { url: "./" },
    })
  );
});

// Notification click: focus or open the app.
self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clientList) => {
      if (clientList.length > 0) return clientList[0].focus();
      return self.clients.openWindow("./");
    })
  );
});
