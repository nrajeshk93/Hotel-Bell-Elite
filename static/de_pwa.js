/**
 * Register the Hotel Bell Elite app shell service worker once per browser session.
 * Cache version bumps activate via skipWaiting; do not force page reloads —
 * that made Settings / soft-nav feel like a multi-second stall.
 *
 * Cache cleanup must keep the *current* SW CACHE_VERSION (never hardcode an
 * old cache name — that deleted the live cache and caused thrash).
 * Also drops legacy hbe-pos-* caches after the hbe-app migration.
 */
(function () {
  'use strict';
  if (!('serviceWorker' in navigator)) return;
  if (window.__dePwaRegistered) return;
  window.__dePwaRegistered = true;

  var CACHE_PREFIXES = ['hbe-app-', 'hbe-pos-'];

  function askCacheVersion(worker) {
    return new Promise(function (resolve) {
      if (!worker) {
        resolve('');
        return;
      }
      var done = false;
      var timer = setTimeout(function () {
        if (done) return;
        done = true;
        resolve('');
      }, 1500);
      var channel = new MessageChannel();
      channel.port1.onmessage = function (event) {
        if (done) return;
        done = true;
        clearTimeout(timer);
        resolve(String((event.data && event.data.cacheVersion) || '').trim());
      };
      try {
        worker.postMessage({ type: 'GET_CACHE_VERSION' }, [channel.port2]);
      } catch (e) {
        clearTimeout(timer);
        resolve('');
      }
    });
  }

  function isManagedCacheKey(key) {
    var s = String(key);
    for (var i = 0; i < CACHE_PREFIXES.length; i++) {
      if (s.indexOf(CACHE_PREFIXES[i]) === 0) return true;
    }
    return false;
  }

  function pruneStaleAppCaches(keepName) {
    if (typeof caches === 'undefined' || !caches.keys) {
      return Promise.resolve();
    }
    return caches.keys().then(function (keys) {
      return Promise.all(
        keys.map(function (key) {
          if (!isManagedCacheKey(key)) return;
          if (keepName && key === keepName) return;
          return caches.delete(key);
        })
      );
    });
  }

  function resolveActiveCacheVersion(reg) {
    var worker =
      (navigator.serviceWorker && navigator.serviceWorker.controller) ||
      (reg && reg.active) ||
      (reg && reg.waiting) ||
      (reg && reg.installing) ||
      null;
    return askCacheVersion(worker).then(function (version) {
      if (version) return version;
      /* Fallback: newest hbe-app-vN (prefer) or legacy hbe-pos-vN. */
      if (typeof caches === 'undefined' || !caches.keys) return '';
      return caches.keys().then(function (keys) {
        var best = '';
        var bestN = -1;
        var bestPref = '';
        (keys || []).forEach(function (key) {
          var m = String(key).match(/^(hbe-app|hbe-pos)-v(\d+)$/);
          if (!m) return;
          var pref = m[1];
          var n = parseInt(m[2], 10);
          var better =
            !best ||
            (pref === 'hbe-app' && bestPref !== 'hbe-app') ||
            (pref === bestPref && n > bestN);
          if (better) {
            bestN = n;
            best = key;
            bestPref = pref;
          }
        });
        return best;
      });
    });
  }

  function register() {
    var onAuthShell =
      /\/(login)?$/.test(window.location.pathname || '') ||
      String(window.location.pathname || '').indexOf('offline_login') !== -1;

    if (onAuthShell && !window.__hbeSwReloadBound) {
      window.__hbeSwReloadBound = true;
      navigator.serviceWorker.addEventListener('controllerchange', function () {
        if (window.__hbeSwReloaded) return;
        /* Reloading while offline paints Chrome's dinosaur on /login. */
        if (typeof navigator !== 'undefined' && navigator.onLine === false) return;
        window.__hbeSwReloaded = true;
        try {
          window.location.reload();
        } catch (e) {}
      });
    }

    navigator.serviceWorker
      .register('/sw.js', { scope: '/' })
      .then(function (reg) {
        resolveActiveCacheVersion(reg)
          .then(function (keep) {
            return pruneStaleAppCaches(keep);
          })
          .catch(function () {});
        if (reg && typeof reg.update === 'function') {
          try {
            reg.update();
          } catch (e) {}
        }
        if (reg && reg.waiting) {
          try {
            reg.waiting.postMessage({ type: 'SKIP_WAITING' });
          } catch (e) {}
        }
        if (reg) {
          reg.addEventListener('updatefound', function () {
            var installing = reg.installing;
            if (!installing) return;
            installing.addEventListener('statechange', function () {
              if (installing.state === 'installed' && navigator.serviceWorker.controller) {
                try {
                  installing.postMessage({ type: 'SKIP_WAITING' });
                } catch (e) {}
              }
            });
          });
        }
      })
      .catch(function () {
        /* Ignore — HTTPS / localhost required; silent in unsupported hosts. */
      });
  }

  /* Test/helpers: expose prune helper without registering twice. */
  window.__dePwaPruneStaleAppCaches = pruneStaleAppCaches;
  window.__dePwaPruneStalePosCaches = pruneStaleAppCaches;

  if (document.readyState === 'complete') {
    register();
  } else {
    window.addEventListener('load', register);
  }
})();
