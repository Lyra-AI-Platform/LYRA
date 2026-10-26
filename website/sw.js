// Lyra service worker: makes the site installable and keeps styles, scripts and images ready offline.
// Pages and the API always come from the network, so signed-in pages are never served from a cache.
const STATIC = 'lyra-static-v1';

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(
  caches.keys().then((keys) => Promise.all(keys.filter((k) => k.startsWith('lyra-static-') && k !== STATIC).map((k) => caches.delete(k)))).then(() => self.clients.claim()),
));

const OFFLINE = `<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Lyra · Offline</title>
<body style="margin:0;min-height:100vh;display:grid;place-items:center;background:#14120e;color:#faf9f7;font:16px/1.5 system-ui,sans-serif;text-align:center;padding:16px">
<div><img src="/img/app/icon-192.png" width="72" height="72" alt="" style="border-radius:16px"><h1 style="font:400 2.2rem Georgia,serif;margin:16px 0 6px">You’re offline</h1>
<p style="opacity:.7;max-width:340px">Lyra needs a connection for live news, Tremor and Labs. It’ll pick up again as soon as you’re back online.</p>
<button onclick="location.reload()" style="margin-top:10px;padding:12px 20px;border:0;border-radius:10px;background:#faf9f7;color:#14120e;font-weight:600">Try again</button></div></body>`;

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.origin !== location.origin || url.pathname.startsWith('/api/')) return;

  if (e.request.mode === 'navigate') {
    e.respondWith(fetch(e.request).catch(() => new Response(OFFLINE, { headers: { 'content-type': 'text/html; charset=utf-8' } })));
    return;
  }
  // Versioned static files (?v=...): serve from cache, refresh in the background
  if (/^\/(css|js|img|fonts)\//.test(url.pathname)) {
    e.respondWith(caches.open(STATIC).then(async (cache) => {
      const hit = await cache.match(e.request);
      const fresh = fetch(e.request).then((res) => { if (res.ok) cache.put(e.request, res.clone()); return res; });
      if (hit) { e.waitUntil(fresh.catch(() => {})); return hit; }
      return fresh;
    }));
  }
});
