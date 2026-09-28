/* Written into every static copy as sw.js by tools/build_static_site.py, which fills in
   the version and the file list. Keeps the pages and the baked years on the phone, so
   the public app and the app a device hands out both open with no network at all.

   Network first, so a rebuilt site is seen as soon as the phone is online; the copy kept
   here when the network is gone, or too slow to be worth waiting for. */
const CACHE = "sakina-1f731835ba49";
const FILES = [
    "/",
    "/countdown/",
    "/data/2026.json",
    "/data/2027.json",
    "/device/icon-128.png",
    "/device/icon-256.png",
    "/device/icon-32.png",
    "/device/",
    "/device/manifest.webmanifest",
    "/device/countdown/",
    "/device/settings/",
    "/static/Amiri-Bold.ttf",
    "/static/Amiri.ttf",
    "/static/app.css",
    "/static/app.js",
    "/static/config.js",
    "/static/icon-128.png",
    "/static/icon-256.png",
    "/static/icon-32.png",
    "/static/manifest.webmanifest"
];
const NETWORK_WAIT_MS = 3000;

self.addEventListener("install", (event) => {
    event.waitUntil(caches.open(CACHE)
        .then((cache) => cache.addAll(FILES))
        .then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
    event.waitUntil(caches.keys()
        .then((keys) => Promise.all(keys.filter((key) => key !== CACHE)
                                        .map((key) => caches.delete(key))))
        .then(() => self.clients.claim()));
});

/* /d/<name>/... is device/... under another address - see _redirects. */
async function kept(request) {
    const found = await caches.match(request, { ignoreSearch: true });
    if (found) return found;
    const owner = new URL(request.url).pathname.match(/^\/d\/[^/]+\/(.*)$/);
    return owner ? caches.match(`/device/${owner[1]}`, { ignoreSearch: true }) : undefined;
}

async function answer(request) {
    const network = fetch(request).then((response) => {
        if (response.ok) {
            const copy = response.clone();
            caches.open(CACHE).then((cache) => cache.put(request, copy));
        }
        return response;
    });
    network.catch(() => {});
    const late = new Promise((resolve) => setTimeout(resolve, NETWORK_WAIT_MS, null));
    const first = await Promise.race([network, late]).catch(() => null);
    if (first) return first;
    return (await kept(request)) || network;
}

self.addEventListener("fetch", (event) => {
    const request = event.request;
    if (request.method !== "GET") return;
    if (new URL(request.url).origin !== self.location.origin) return;
    event.respondWith(answer(request));
});
