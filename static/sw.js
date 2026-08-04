/* Hotel Bell Elite — POS offline service worker (v4).
 * Floor APIs are never cached — occupancy must update immediately after save.
 * Invoice HTML is network-first so workspace chrome (sidebar modules) is not stuck. */
var CACHE_VERSION = 'hbe-pos-v10';
var PRECACHE = [
  '/point-of-sale/invoice',
  '/static/manifest.webmanifest',
  '/static/de_workspace_shell.css?v=45',
  '/static/ep_form_listbox.css?v=21',
  '/static/pos_invoice.css?v=51',
  '/static/pos_invoice.js?v=105',
  '/static/pos_offline.js?v=4',
  '/static/ep_form_listbox.js?v=47',
  '/static/de_workspace_nav.js?v=39',
  '/static/de_workspace_transitions.js?v=122',
  '/static/de_pwa.js?v=4',
  '/static/pwa-icon-192.png',
  '/static/pwa-icon-512.png',
  '/static/favicon-32.png'
];

/* Menu catalog only — never floor (occupied status must not go stale). */
var API_CACHE_PATHS = [
  '/point-of-sale/api/menu/items',
  '/point-of-sale/api/menu/categories',
  '/bar-point-of-sale/api/menu/items',
  '/bar-point-of-sale/api/menu/categories'
];

var FLOOR_API_PATHS = [
  '/point-of-sale/api/floor',
  '/bar-point-of-sale/api/floor'
];

self.addEventListener('install', function (event) {
  event.waitUntil(
    caches.open(CACHE_VERSION).then(function (cache) {
      return cache.addAll(PRECACHE).catch(function () {
        /* Precache best-effort — individual URLs may 302 to login. */
        return Promise.all(
          PRECACHE.map(function (url) {
            return cache.add(url).catch(function () {});
          })
        );
      });
    }).then(function () {
      return self.skipWaiting();
    })
  );
});

self.addEventListener('activate', function (event) {
  event.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(
        keys.map(function (key) {
          if (key !== CACHE_VERSION) return caches.delete(key);
        })
      );
    }).then(function () {
      return self.clients.claim();
    })
  );
});

self.addEventListener('message', function (event) {
  if (event && event.data && event.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});

function isApiGet(url) {
  if (url.origin !== self.location.origin) return false;
  return API_CACHE_PATHS.some(function (path) {
    return url.pathname === path;
  });
}

function isFloorApi(url) {
  if (url.origin !== self.location.origin) return false;
  return FLOOR_API_PATHS.some(function (path) {
    return url.pathname === path;
  });
}

function isPosInvoiceHtml(url) {
  if (url.origin !== self.location.origin) return false;
  return (
    url.pathname === '/point-of-sale/invoice' ||
    url.pathname === '/bar-point-of-sale/invoice'
  );
}

self.addEventListener('fetch', function (event) {
  var req = event.request;
  if (req.method !== 'GET') return;

  var url;
  try {
    url = new URL(req.url);
  } catch (e) {
    return;
  }

  /* Floor: network-only while online; offline fallback only. Never put into Cache API. */
  if (isFloorApi(url)) {
    event.respondWith(networkOnlyFloor(req));
    return;
  }

  if (isApiGet(url)) {
    event.respondWith(networkFirst(req));
    return;
  }

  /* Invoice shell/sidebar must not stick on an old HTML snapshot. */
  if (isPosInvoiceHtml(url)) {
    event.respondWith(networkFirstHtml(req));
    return;
  }

  if (url.pathname.indexOf('/static/') === 0) {
    event.respondWith(cacheFirst(req));
  }
});

function networkOnlyFloor(req) {
  return fetch(req, { cache: 'no-store' })
    .then(function (res) {
      return res;
    })
    .catch(function () {
      return Response.json(
        { ok: false, error: 'offline', offline: true },
        { status: 503 }
      );
    });
}

function networkFirst(req) {
  return fetch(req)
    .then(function (res) {
      if (res && res.ok) {
        var copy = res.clone();
        caches.open(CACHE_VERSION).then(function (cache) {
          cache.put(req, copy);
        });
      }
      return res;
    })
    .catch(function () {
      return caches.match(req).then(function (cached) {
        return cached || Response.json({ ok: false, error: 'offline', offline: true }, { status: 503 });
      });
    });
}

function networkFirstHtml(req) {
  return fetch(req, { cache: 'no-store' })
    .then(function (res) {
      if (res && res.ok) {
        var copyReq = res.clone();
        var copyPath = res.clone();
        caches.open(CACHE_VERSION).then(function (cache) {
          cache.put(req, copyReq);
          /* Keep a bare offline fallback for navigate without query. */
          try {
            var u = new URL(req.url);
            if (u.pathname === '/point-of-sale/invoice' || u.pathname === '/bar-point-of-sale/invoice') {
              cache.put(u.pathname, copyPath);
            }
          } catch (e) {}
        });
      }
      return res;
    })
    .catch(function () {
      return caches.match(req).then(function (cached) {
        if (cached) return cached;
        return caches.match('/point-of-sale/invoice').then(function (fallback) {
          return fallback || Response.error();
        });
      });
    });
}

function cacheFirst(req) {
  return caches.match(req).then(function (cached) {
    if (cached) {
      fetch(req)
        .then(function (res) {
          if (res && res.ok) {
            caches.open(CACHE_VERSION).then(function (cache) {
              cache.put(req, res);
            });
          }
        })
        .catch(function () {});
      return cached;
    }
    return fetch(req)
      .then(function (res) {
        if (res && res.ok) {
          var copy = res.clone();
          caches.open(CACHE_VERSION).then(function (cache) {
            cache.put(req, copy);
          });
        }
        return res;
      })
      .catch(function () {
        if (req.mode === 'navigate') {
          return caches.match('/point-of-sale/invoice');
        }
        return Response.error();
      });
  });
}
