'use strict';

self.addEventListener('push', event => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch { data = {}; }
  const title = String(data.title || 'BlinQ');
  const body = String(data.body || 'Nová BlinQ informácia.');
  const url = String(data.url || '/#predictions');
  const type = String(data.type || 'info');
  event.waitUntil(self.registration.showNotification(title, {
    body,
    icon: '/assets/blinq_favi.png',
    badge: '/assets/blinq_favi.png',
    tag: String(data.tag || `blinq-${type}`),
    renotify: type === 'live_watch' || type === 'alert',
    data: {url, type},
  }));
});

self.addEventListener('notificationclick', event => {
  event.notification.close();
  const target = new URL(String(event.notification?.data?.url || '/#predictions'), self.location.origin).href;
  event.waitUntil((async () => {
    const windows = await clients.matchAll({type: 'window', includeUncontrolled: true});
    for (const client of windows) {
      if ('focus' in client) {
        try { await client.navigate(target); } catch {}
        return client.focus();
      }
    }
    return clients.openWindow ? clients.openWindow(target) : undefined;
  })());
});
