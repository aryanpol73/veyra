// Web Push handlers, imported into the Workbox service worker (vite.config.ts -> workbox.importScripts).
// Runs even when no Veyra tab is open: the browser wakes the worker when a push arrives.
self.addEventListener("push", (event) => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch (e) { data = { body: event.data && event.data.text() }; }
  const title = data.title || "Veyra";
  const critical = data.priority === "critical";
  event.waitUntil(
    self.registration.showNotification(title, {
      body: data.body || "Something changed in your competitive intelligence.",
      icon: "/pwa-192.png",
      badge: "/badge-96.png",
      tag: data.tag || "veyra",
      renotify: true,
      requireInteraction: critical, // critical alerts stay on screen until dismissed (where supported)
      data: { url: data.url || "/" },
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = new URL((event.notification.data && event.notification.data.url) || "/", self.location.origin).href;
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((wins) => {
      for (const w of wins) {
        if (new URL(w.url).origin === self.location.origin && "focus" in w) {
          w.navigate(target);
          return w.focus();
        }
      }
      return self.clients.openWindow(target);
    }),
  );
});

// Browser rotated the subscription (rare): re-subscribe with the same server key and tell the server.
self.addEventListener("pushsubscriptionchange", (event) => {
  event.waitUntil((async () => {
    const key = event.oldSubscription && event.oldSubscription.options.applicationServerKey;
    if (!key) return;
    const sub = await self.registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: key });
    await fetch("/api/push/subscribe", {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-Veyra": "1" },
      body: JSON.stringify(sub.toJSON()),
    });
  })());
});
