// Service worker do painel: mostra o aviso de pedido novo mesmo com o painel fechado.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', event => event.waitUntil(self.clients.claim()));
self.addEventListener('push', event => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch { data = {body: event.data ? event.data.text() : ''}; }
  event.waitUntil(self.registration.showNotification(data.title || 'SeuComércioAqui', {
    body: data.body || '', icon: '/static/icon-192.png', badge: '/static/icon-192.png', tag: data.tag || 'pedido',
    renotify: true, requireInteraction: true, vibrate: [200, 100, 200, 100, 300], data: {url: data.url || '/painel'}
  }));
});
self.addEventListener('notificationclick', event => {
  event.notification.close();
  const target = event.notification.data && event.notification.data.url || '/painel';
  event.waitUntil(self.clients.matchAll({type: 'window', includeUncontrolled: true}).then(list => {
    for (const client of list) if (new URL(client.url).pathname.startsWith('/painel')) return client.focus();
    return self.clients.openWindow(target);
  }));
});
