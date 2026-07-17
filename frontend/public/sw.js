// Service worker khusus untuk Web Push notification (booking baru, pembayaran diterima,
// komplain baru, kamar perlu dibersihkan) — sengaja minimal, TIDAK melakukan asset caching
// apa pun, supaya tidak mengganggu app shell React (CRA) yang sudah jalan tanpa SW selama ini.

self.addEventListener("install", (event) => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("push", (event) => {
  let data = { title: "Pelangi Homestay", body: "", url: "/" };
  try {
    if (event.data) data = { ...data, ...event.data.json() };
  } catch (e) {
    if (event.data) data.body = event.data.text();
  }
  event.waitUntil(
    Promise.all([
      self.registration.showNotification(data.title || "Pelangi Homestay", {
        body: data.body || "",
        icon: "/icon-192.png",
        badge: "/badge-96.png",
        data: { url: data.url || "/" },
      }),
      // Relay ke tab yang sedang terbuka/fokus supaya bisa mainkan suara alert kustom
      // (showNotification saja sering senyap/tidak kedengaran kalau notif OS di-mute).
      self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clients) => {
        for (const client of clients) client.postMessage({ type: "pms-push", ...data });
      }),
    ])
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = event.notification.data?.url || "/";
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clients) => {
      for (const client of clients) {
        if ("focus" in client) {
          client.navigate(url);
          return client.focus();
        }
      }
      return self.clients.openWindow(url);
    })
  );
});
