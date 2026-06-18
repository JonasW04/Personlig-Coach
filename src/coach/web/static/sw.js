const CACHE = "coach-v25";
const SHELL = [
  ".",
  "index.html",
  "coach.css",
  "coach.data.js",
  "coach.icons.js",
  "coach.screens.js",
  "coach.js",
  "manifest.webmanifest",
  "icon.svg",
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const { request } = e;
  // Never cache the chat API or non-GET requests — always hit the network.
  if (request.method !== "GET" || new URL(request.url).pathname.startsWith("/api/")) {
    return;
  }
  // Stale-While-Revalidate strategy: serve from cache immediately, fetch fresh in background.
  e.respondWith(
    caches.open(CACHE).then((cache) => {
      return cache.match(request).then((cached) => {
        const fetched = fetch(request)
          .then((resp) => {
            cache.put(request, resp.clone());
            return resp;
          })
          .catch(() => cached); // fallback to cached on network failure
        return cached || fetched;
      });
    })
  );
});

self.addEventListener("push", (e) => {
  let data = {};
  if (e.data) {
    try {
      data = e.data.json();
    } catch {
      data = { body: e.data.text() };
    }
  }

  const title = data.title || "Coach";
  const options = {
    body: data.body || "New report ready.",
    icon: "icon.svg",
    badge: "icon.svg",
    tag: data.tag || "coach-report",
    data: { url: data.url || "/" },
  };
  e.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const url = new URL(e.notification.data?.url || "/", self.location.origin).href;
  e.waitUntil(
    clients.matchAll({ type: "window", includeUncontrolled: true }).then((clientList) => {
      for (const client of clientList) {
        if (client.url.startsWith(self.location.origin) && "focus" in client) {
          return client.navigate(url).then(() => client.focus());
        }
      }
      if (clients.openWindow) return clients.openWindow(url);
      return undefined;
    })
  );
});
