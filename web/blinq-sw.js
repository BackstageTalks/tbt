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

// Push payload URLs are not trusted navigation destinations.
function safeNotificationTarget(value) {
  const fallback = new URL('/#predictions', self.location.origin).href;
  try {
    const target = new URL(String(value || '/#predictions'), self.location.origin);
    if (target.origin !== self.location.origin ||
        (target.protocol !== 'https:' && target.protocol !== 'http:') ||
        target.username || target.password) return fallback;
    return target.href;
  } catch {
    return fallback;
  }
}

self.addEventListener('notificationclick', event => {
  event.notification.close();
  const target = safeNotificationTarget(event.notification?.data?.url);
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
