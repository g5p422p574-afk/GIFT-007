const CACHE_NAME = "gift-v3";

// Only cache static assets and the public home page.
// NEVER cache /orders/, /uploads/, /admin/, /profile/, /cart/,
// /login/, /register/, /store/ — those contain sensitive data.
const PRE_CACHE = [
  "/",
  "/offline.html",
  "/static/style.css",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png",
];

// Path prefixes that are SAFE to cache at runtime (only static assets).
const CACHEABLE_PREFIXES = [
  "/static/",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(PRE_CACHE).catch(() => {});
    }).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k))
      );
    }).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // Only handle GET requests to our own origin
  if (request.method !== "GET" || !url.protocol.startsWith("http")) return;

  // ── Navigation requests (page loads) ──
  // Cache only the home page.  All other pages must go to network
  // (both for freshness and to avoid caching sensitive data).
  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request)
        .then((response) => {
          // Only cache the root page; never cache /orders/, /admin/, etc.
          if (url.pathname === "/" && response.status === 200) {
            const clone = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(request, clone));
          }
          return response;
        })
        .catch(() => {
          return caches.match(request).then((cached) => {
            return cached || caches.match("/offline.html");
          });
        })
    );
    return;
  }

  // ── Sub-resource requests (CSS, JS, images, fonts) ──
  const isCacheable = CACHEABLE_PREFIXES.some((prefix) =>
    url.pathname.startsWith(prefix)
  );

  if (isCacheable) {
    event.respondWith(
      caches.match(request).then((cached) => {
        const fetchPromise = fetch(request).then((response) => {
          if (response && response.status === 200) {
            const clone = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(request, clone));
          }
          return response;
        }).catch(() => {});

        return cached || fetchPromise;
      })
    );
  }
  // All other requests (including /uploads/, /orders/, etc.) — network only,
  // never cached.
});
