/* Hotel Bell Elite — whole-app shell service worker.
 * Network-first everywhere we intercept so online stays fast/fresh.
 * Cache Storage is a fallback for offline + brief disconnects.
 * Floor APIs are never cached — occupancy must not go stale.
 * POS menu GETs stay network-first; mutation APIs are not intercepted. */
var CACHE_VERSION = 'hbe-app-v19';
var OFFLINE_LOGIN_URL = '/static/offline_login.html?v=10';
var OFFLINE_AUTH_URL = '/static/offline_auth.js?v=12';
var CRITICAL_STATIC_ALIASES = {
  '/static/offline_auth.js': [
    '/static/offline_auth.js?v=12',
    '/static/offline_auth.js?v=11',
    '/static/offline_auth.js?v=10',
    '/static/offline_auth.js?v=9',
    '/static/offline_auth.js?v=8',
    '/static/offline_auth.js'
  ],
  '/static/de_pwa.js': [
    '/static/de_pwa.js?v=14',
    '/static/de_pwa.js?v=13',
    '/static/de_pwa.js'
  ],
  '/static/offline_login.html': [
    OFFLINE_LOGIN_URL,
    '/static/offline_login.html?v=10',
    '/static/offline_login.html?v=9',
    '/static/offline_login.html'
  ]
};
var PRECACHE = [
  '/home',
  '/point-of-sale/invoice',
  '/bar-point-of-sale/invoice',
  '/login',
  OFFLINE_LOGIN_URL,
  '/static/offline_login.html',
  OFFLINE_AUTH_URL,
  '/static/login_premium.css?v=12',
  '/static/login_hero.jpg?v=2',
  '/static/hbe_mark_sm.png',
  '/static/hbe_mark_form_sm.png?v=3',
  '/static/hbe_logo_sm.png',
  '/static/hbe_logo_sm.webp',
  '/static/manifest.webmanifest',
  '/static/de_workspace_shell.css?v=55',
  '/static/hbe_home_premium.css?v=20',
  '/static/ep_form_listbox.css?v=29',
  '/static/hbe_table_scroll.css?v=2',
  '/static/hbe_kpi.css?v=13',
  '/static/hbe_app_toast.css?v=1',
  '/static/reports_page_scroll.css?v=5',
  '/static/pos_invoice.css?v=52',
  '/static/pos_invoice.js?v=148',
  '/static/pos_offline.js?v=5',
  '/static/ep_form_listbox.js?v=66',
  '/static/de_workspace_nav.js?v=46',
  '/static/de_workspace_transitions.js?v=193',
  '/static/hbe_table_scroll.js?v=10',
  '/static/hbe_app_toast.js?v=3',
  '/static/print_agent.js?v=7',
  '/static/de_pwa.js?v=14',
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
      }).then(function () {
        /* Stale login shells often request older ?v= query strings.
           Mirror critical files under every known alias so offline Sign In works. */
        return Promise.all(
          Object.keys(CRITICAL_STATIC_ALIASES).map(function (pathOnly) {
            var aliases = CRITICAL_STATIC_ALIASES[pathOnly];
            function loadFirst(i) {
              if (i >= aliases.length) return Promise.resolve(null);
              return cache.match(aliases[i]).then(function (hit) {
                return hit || loadFirst(i + 1);
              });
            }
            return loadFirst(0).then(function (res) {
              if (!res) return;
              return Promise.all(
                aliases.map(function (alias) {
                  return cache.put(alias, res.clone()).catch(function () {});
                })
              );
            });
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
  if (!event || !event.data) return;
  if (event.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
    return;
  }
  if (event.data.type === 'GET_CACHE_VERSION') {
    var port = event.ports && event.ports[0];
    if (port) {
      port.postMessage({ cacheVersion: CACHE_VERSION });
    }
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

function isAuthOrSystemPath(url) {
  var p = url.pathname;
  if (p === '/login' || p.indexOf('/login/') === 0) return true;
  if (p === '/logout' || p.indexOf('/logout/') === 0) return true;
  if (p === '/sw.js') return true;
  return false;
}

function isWorkspaceHtml(url, req) {
  if (url.origin !== self.location.origin) return false;
  if (url.pathname.indexOf('/static/') === 0) return false;
  if (url.pathname.indexOf('/api/') !== -1) return false;
  if (isAuthOrSystemPath(url)) return false;
  if (url.searchParams.get('partial') === 'main') return true;
  var accept = '';
  try {
    accept = String(req.headers.get('Accept') || req.headers.get('accept') || '');
  } catch (e) {}
  if (req.mode === 'navigate') return true;
  if (accept.indexOf('text/html') !== -1) return true;
  return false;
}

function isAppCachedStatic(url) {
  if (url.origin !== self.location.origin) return false;
  if (url.pathname.indexOf('/static/') !== 0) return false;
  if (url.pathname.indexOf('/static/pos_') === 0) return true;
  var key = url.pathname + (url.search || '');
  if (PRECACHE.indexOf(key) !== -1 || PRECACHE.indexOf(url.pathname) !== -1) return true;
  /* Runtime network-first for page CSS/JS — keeps offline soft-nav usable. */
  if (/\.(css|js)$/i.test(url.pathname)) return true;
  if (/\.(png|ico|webp|svg|jpe?g)$/i.test(url.pathname) && url.pathname.indexOf('/static/') === 0) {
    return true;
  }
  return false;
}

self.addEventListener('fetch', function (event) {
  var req = event.request;

  var url;
  try {
    url = new URL(req.url);
  } catch (e) {
    return;
  }

  if (req.method !== 'GET') {
    /* Form POST to Sign In is mode=navigate. If offline_auth failed to bind,
       the browser POSTs /login and Chrome shows the dinosaur unless we catch it. */
    var loginPostNav =
      req.mode === 'navigate' &&
      (url.pathname === '/login' || url.pathname === '/');
    if (loginPostNav && String(req.method || '').toUpperCase() === 'POST') {
      event.respondWith(
        fetch(req)
          .then(function (res) {
            return res;
          })
          .catch(function () {
            return matchLoginShellOffline().then(function (login) {
              return login || offlineNavigateFallback();
            });
          })
      );
      return;
    }
    return;
  }

  var loginNav = req.mode === 'navigate' && url.pathname === '/login';
  /* Do NOT intercept /logout. SW re-fetch loses Sec-Fetch-Mode: navigate,
     Flask returns 204 (prefetch guard) and the session is never cleared. */
  var logoutNav = req.mode === 'navigate' && url.pathname === '/logout';

  /* Floor: network-only while online; offline fallback only. Never put into Cache API. */
  if (isFloorApi(url)) {
    event.respondWith(networkOnlyFloor(req));
    return;
  }

  if (isApiGet(url)) {
    event.respondWith(networkFirst(req));
    return;
  }

  if (logoutNav) {
    return;
  }

  /* GET /login navigate: offline login shell (POST /login stays network-only). */
  if (loginNav) {
    event.respondWith(networkFirstHtml(req));
    return;
  }

  if (isWorkspaceHtml(url, req)) {
    event.respondWith(networkFirstHtml(req));
    return;
  }

  if (url.pathname.indexOf('/static/') === 0) {
    if (isAppCachedStatic(url)) {
      event.respondWith(networkFirstStatic(req));
    }
  }
});

function networkOnlyFloor(req) {
  /* GET: network-first with cache fallback so offline Tables can show layout.
     Occupancy may be slightly stale offline — better than an empty floor. */
  if (req.method && String(req.method).toUpperCase() !== 'GET') {
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
  return fetch(req, { cache: 'no-store' })
    .then(function (res) {
      if (res && res.ok) {
        var copy = res.clone();
        caches.open(CACHE_VERSION).then(function (cache) {
          cache.put(req, copy);
          try {
            cache.put(new URL(req.url).pathname, res.clone());
          } catch (e) {}
        });
      }
      return res;
    })
    .catch(function () {
      return caches.match(req).then(function (cached) {
        if (cached) return cached;
        try {
          return caches.match(new URL(req.url).pathname).then(function (byPath) {
            return (
              byPath ||
              Response.json(
                { ok: false, error: 'offline', offline: true },
                { status: 503 }
              )
            );
          });
        } catch (e2) {
          return Response.json(
            { ok: false, error: 'offline', offline: true },
            { status: 503 }
          );
        }
      });
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

function putHtmlCache(cache, req, res) {
  cache.put(req, res.clone());
  try {
    var u = new URL(req.url);
    var pathKey = u.pathname + (u.search || '');
    cache.put(pathKey, res.clone());
    var isPartial = u.searchParams.get('partial') === 'main';
    if (isPartial) {
      cache.put(u.pathname + '?partial=main', res.clone());
      /* Never overwrite the bare navigate URL with a main-only fragment —
         that painted /home without the left sidebar after login. */
      return;
    }
    /* Bare path fallback for navigate without query (POS + home + sign-in). */
    if (
      u.pathname === '/' ||
      u.pathname === '/login' ||
      u.pathname === '/home' ||
      u.pathname === '/point-of-sale/invoice' ||
      u.pathname === '/bar-point-of-sale/invoice'
    ) {
      cache.put(u.pathname, res.clone());
    }
  } catch (e) {}
}

function isLoginShellPath(pathname) {
  return pathname === '/' || pathname === '/login';
}

function responseLooksLikeModernOfflineLogin(res) {
  if (!res) return Promise.resolve(false);
  return res
    .clone()
    .text()
    .then(function (html) {
      if (!html) return false;
      if (html.indexOf('Reconnect to sign in') !== -1) return false;
      if (html.indexOf('offline_auth.js') === -1) return false;
      if (html.indexOf('login-panel') === -1 && html.indexOf('login-shell') === -1) {
        return false;
      }
      return true;
    })
    .catch(function () {
      return false;
    });
}

function syntheticOfflineLoginResponse() {
  var html =
    '<!doctype html><html lang="en"><head><meta charset="utf-8">' +
    '<meta name="viewport" content="width=device-width,initial-scale=1">' +
    '<title>Hotel Bell Elite — Sign In</title>' +
    '<link rel="stylesheet" href="/static/login_premium.css?v=12">' +
    '</head><body class="login-page"><div class="login-shell"><main class="login-panel">' +
    '<div class="login-panel-card"><div class="login-panel-head">' +
    '<h2 class="login-panel-title">Hotel Bell Elite</h2>' +
    '<p class="login-panel-sub">Sign in to access your account</p></div>' +
    '<div id="login-offline-notice" class="login-notice">You\'re offline. You can still sign in with your password on this device.</div>' +
    '<form method="POST" action="/login" class="login-form" id="login-form">' +
    '<div class="form-group"><label for="username">Username</label>' +
    '<input type="text" id="username" name="username" autocomplete="username" required></div>' +
    '<div class="form-group"><label for="password">Password</label>' +
    '<input type="password" id="password" name="password" autocomplete="current-password" required></div>' +
    '<button type="submit" class="login-btn">Sign In</button></form></div></main></div>' +
    '<script src="/static/de_pwa.js?v=14"><\/script>' +
    '<script src="' +
    OFFLINE_AUTH_URL +
    '"><\/script>' +
    '<script>(function(){var n=document.getElementById("login-offline-notice");var f=document.getElementById("login-form");if(f&&!f.getAttribute("data-hbe-offline-capture")){f.setAttribute("data-hbe-offline-capture","1");f.addEventListener("submit",function(e){e.preventDefault();e.stopPropagation();if(window.HbeOfflineAuth&&window.HbeOfflineAuth.handleLoginSubmit){window.HbeOfflineAuth.handleLoginSubmit(f,{noticeEl:n});}else if(n){n.hidden=false;n.textContent="Sign-in script didn\'t load. Reconnect once, refresh, then try offline again.";}},true);}if(window.HbeOfflineAuth&&f){window.HbeOfflineAuth.bindLoginForm(f,{noticeEl:n});}})();<\/script>' +
    '</body></html>';
  return new Response(html, {
    status: 200,
    headers: { 'Content-Type': 'text/html; charset=utf-8', 'X-Hbe-Offline-Shell': 'synthetic' }
  });
}

function matchLoginShellOffline() {
  /* Prefer version-busted shell so CDN/SW cannot keep the old
     "Reconnect to sign in" HTML that blocks offline Sign In. */
  var keys = [OFFLINE_LOGIN_URL, '/static/offline_login.html'];
  function fromKeys(i) {
    if (i >= keys.length) {
      return matchLegacyLoginShell().then(function (legacy) {
        return legacy || syntheticOfflineLoginResponse();
      });
    }
    return caches.match(keys[i]).then(function (shell) {
      if (!shell) return fromKeys(i + 1);
      return responseLooksLikeModernOfflineLogin(shell).then(function (ok) {
        return ok ? shell : fromKeys(i + 1);
      });
    });
  }
  return fromKeys(0);
}

function matchLegacyLoginShell() {
  var keys = ['/login', '/'];
  function next(i) {
    if (i >= keys.length) return Promise.resolve(null);
    return caches.match(keys[i]).then(function (cached) {
      if (!cached) return next(i + 1);
      return responseLooksLikeModernOfflineLogin(cached).then(function (ok) {
        return ok ? cached : next(i + 1);
      });
    });
  }
  return next(0);
}

function matchHtmlCache(req) {
  return caches.match(req).then(function (cached) {
    if (cached) return cached;
    try {
      var u = new URL(req.url);
      var pathKey = u.pathname + (u.search || '');
      var wantsPartial = u.searchParams.get('partial') === 'main';
      return caches.match(pathKey).then(function (byPath) {
        if (byPath) return byPath;
        if (wantsPartial) {
          return caches.match(u.pathname + '?partial=main').then(function (partial) {
            /* Prefer partial for soft-nav; fall back to full page if needed. */
            return partial || caches.match(u.pathname);
          });
        }
        /* Full navigations must not use a partial=main snapshot. */
        return caches.match(u.pathname);
      });
    } catch (e) {
      return null;
    }
  });
}

function offlineNavigateFallback() {
  return matchLoginShellOffline().then(function (login) {
    if (login) return login;
    return new Response(
      '<!doctype html><html lang="en"><head><meta charset="utf-8">' +
        '<meta name="viewport" content="width=device-width,initial-scale=1">' +
        '<title>Hotel Bell Elite</title></head><body style="font-family:system-ui;padding:24px">' +
        '<h1>You\'re offline</h1>' +
        '<p>Open Sign In and unlock with your password, or reconnect to load the workspace.</p>' +
        '<p><a href="/">Go to Sign In</a></p>' +
        '</body></html>',
      {
        status: 503,
        statusText: 'Offline',
        headers: { 'Content-Type': 'text/html; charset=utf-8' }
      }
    );
  });
}

function networkFirstHtml(req) {
  var pathname = '/';
  try {
    pathname = new URL(req.url).pathname;
  } catch (e) {}
  return fetch(req, { cache: 'no-store' })
    .then(function (res) {
      if (res && res.ok) {
        var copy = res.clone();
        caches.open(CACHE_VERSION).then(function (cache) {
          putHtmlCache(cache, req, copy);
        });
      }
      return res;
    })
    .catch(function () {
      /* Sign-in: prefer a real login shell, never a stale /home snapshot. */
      if (isLoginShellPath(pathname)) {
        return matchLoginShellOffline().then(function (login) {
          return login || offlineNavigateFallback();
        });
      }
      return matchHtmlCache(req).then(function (cached) {
        if (cached) return cached;
        return caches.match('/home').then(function (home) {
          return home || caches.match('/point-of-sale/invoice').then(function (pos) {
            return pos || offlineNavigateFallback();
          });
        });
      });
    });
}

function matchStaticCache(req) {
  var pathKey = '';
  var pathOnly = '';
  var fullUrl = '';
  try {
    var u = new URL(req.url);
    pathKey = u.pathname + (u.search || '');
    pathOnly = u.pathname;
    fullUrl = u.href;
  } catch (e) {}
  return caches.match(req).then(function (hit) {
    if (hit) return { hit: hit, via: 'request' };
    if (!pathKey) return { hit: null, via: 'none' };
    return caches.match(pathKey).then(function (byPath) {
      if (byPath) return { hit: byPath, via: 'pathKey' };
      function tryAliases() {
        var aliases = CRITICAL_STATIC_ALIASES[pathOnly];
        if (!aliases || !aliases.length) {
          if (!fullUrl || fullUrl === pathKey) return Promise.resolve({ hit: null, via: 'none' });
          return caches.match(fullUrl).then(function (byHref) {
            return { hit: byHref || null, via: byHref ? 'href' : 'none' };
          });
        }
        function next(i) {
          if (i >= aliases.length) return Promise.resolve({ hit: null, via: 'none' });
          return caches.match(aliases[i]).then(function (aliasHit) {
            if (aliasHit) return { hit: aliasHit, via: 'alias:' + aliases[i] };
            return next(i + 1);
          });
        }
        return next(0);
      }
      return tryAliases();
    });
  });
}

function networkFirstStatic(req) {
  var pathKey = '';
  try {
    var u = new URL(req.url);
    pathKey = u.pathname + (u.search || '');
  } catch (e) {}

  return fetch(req, { cache: 'no-cache' })
    .then(function (res) {
      /* Stylesheet requests are often mode=no-cors (opaque, !ok). Still cache
         a CORS re-fetch by URL so offline document.write shells stay styled. */
      if (res && res.ok) {
        var copy = res.clone();
        caches.open(CACHE_VERSION).then(function (cache) {
          cache.put(req, copy);
          if (pathKey) cache.put(pathKey, res.clone());
        });
        return res;
      }
      if (res && res.type === 'opaque' && pathKey) {
        fetch(pathKey, { credentials: 'same-origin', cache: 'no-cache' })
          .then(function (corsRes) {
            if (!corsRes || !corsRes.ok) return;
            caches.open(CACHE_VERSION).then(function (cache) {
              cache.put(pathKey, corsRes.clone());
              cache.put(req, corsRes.clone());
            });
          })
          .catch(function () {});
      }
      return res;
    })
    .catch(function () {
      return matchStaticCache(req).then(function (found) {
        return found.hit || Response.error();
      });
    });
}
