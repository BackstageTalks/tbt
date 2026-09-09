// previous shell cache: blinq-shell-v656
const CACHE='blinq-shell-v657';
const SHELL=['/','/index.html','/styles.css','/app.js','/auth.js','/manifest.webmanifest','/assets/blinq_logo.svg','/assets/blinq_app_192.png','/assets/blinq_app_512.png'];
self.addEventListener('install',event=>{event.waitUntil(caches.open(CACHE).then(cache=>cache.addAll(SHELL)).then(()=>self.skipWaiting()));});
self.addEventListener('activate',event=>{event.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(key=>key!==CACHE).map(key=>caches.delete(key)))).then(()=>self.clients.claim()));});
self.addEventListener('fetch',event=>{
  const req=event.request;if(req.method!=='GET')return;
  const url=new URL(req.url);if(url.origin!==location.origin)return;
  if(url.pathname.startsWith('/api/')||url.pathname.endsWith('.json')){event.respondWith(fetch(req).catch(()=>caches.match(req)));return;}
  if(req.mode==='navigate'){
    event.respondWith(fetch(req).then(res=>{const copy=res.clone();caches.open(CACHE).then(c=>c.put('/index.html',copy));return res;}).catch(()=>caches.match('/index.html')));return;
  }
  event.respondWith(caches.match(req).then(hit=>hit||fetch(req).then(res=>{if(res.ok){const copy=res.clone();caches.open(CACHE).then(c=>c.put(req,copy));}return res;})));
});
