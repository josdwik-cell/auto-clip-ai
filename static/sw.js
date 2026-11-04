const CACHE='auto-clip-ai-v1';
const CORE=['/','/static/style.css','/static/app.js','/static/manifest.webmanifest','/static/icon.svg'];
self.addEventListener('install',e=>e.waitUntil(caches.open(CACHE).then(c=>c.addAll(CORE))));
self.addEventListener('activate',e=>e.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k!==CACHE).map(k=>caches.delete(k))))));
self.addEventListener('fetch',e=>{
  const u=new URL(e.request.url);
  if(e.request.method!=='GET' || u.pathname.startsWith('/api/') || u.pathname.startsWith('/outputs/')) return;
  e.respondWith(caches.match(e.request).then(hit=>hit || fetch(e.request).then(res=>{
    const copy=res.clone(); caches.open(CACHE).then(c=>c.put(e.request,copy)); return res;
  }).catch(()=>caches.match('/'))));
});
