const NAME='ashare-quant-shell-v1-2-3';
const ASSETS=['./','./index.html','./manifest.webmanifest','./assets/icon.svg'];
self.addEventListener('install',e=>e.waitUntil(caches.open(NAME).then(c=>c.addAll(ASSETS)).then(()=>self.skipWaiting())));
self.addEventListener('activate',e=>e.waitUntil(caches.keys().then(names=>Promise.all(names.filter(n=>n!==NAME).map(n=>caches.delete(n)))).then(()=>self.clients.claim())));
self.addEventListener('fetch',e=>{
 const u=new URL(e.request.url);
 if(e.request.method!=='GET'||u.origin!==self.location.origin)return;
 // No caching of public price/signal data: never pass stale prices off as current.
 if(u.pathname.includes('/data/')){e.respondWith(fetch(e.request,{cache:'no-store'}));return}
 e.respondWith(fetch(e.request).catch(()=>caches.match(e.request)));
});
