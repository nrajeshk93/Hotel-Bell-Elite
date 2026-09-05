/**
 * Register the Hotel Bell Elite app shell service worker once per browser session.
 *
 * New workers skipWaiting + claim. A controllerchange reload runs only when
 * this page already had a worker (an actual update), so first install does
 * not stall Sign In / Settings. Cache cleanup keeps the live CACHE_VERSION.
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
      if (typeof caches === 'undefined' || !caches.keys) return '';
      return caches.keys().then(function (keys) {
        var best = '';
        var bestN = -1;
        var bestPref = '';
        (keys || []).forEach(function (key) {
          var hashed = String(key).match(/^(hbe-app)-([a-f0-9]{8,})$/);
          if (hashed) {
            if (bestPref !== 'hbe-app-hash') {
              best = key;
              bestPref = 'hbe-app-hash';
              bestN = 0;
            }
            return;
          }
          var m = String(key).match(/^(hbe-app|hbe-pos)-v(\d+)$/);
          if (!m) return;
          var pref = m[1];
          var n = parseInt(m[2], 10);
          var better =
            bestPref === 'hbe-app-hash'
              ? false
              : !best ||
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

  function bindReloadOnUpdate() {
    if (window.__hbeSwReloadBound) return;
    window.__hbeSwReloadBound = true;
    var hadController = !!(
      navigator.serviceWorker && navigator.serviceWorker.controller
    );
    navigator.serviceWorker.addEventListener('controllerchange', function () {
      if (!hadController) {
        hadController = true;
        return;
      }
      if (window.__hbeSwReloaded) return;
      /* Localhost / LAN: skip forced reload — digests change often during
         edits and would otherwise refresh the tab in a loop. Prod keeps one
         reload when a new worker claims. */
      try {
        var host = (window.location && window.location.hostname) || '';
        if (
          host === 'localhost' ||
          host === '127.0.0.1' ||
          host === '0.0.0.0' ||
          host.indexOf('192.168.') === 0 ||
          host.indexOf('10.') === 0
        ) {
          hadController = true;
          return;
        }
      } catch (eHost) {}
      window.__hbeSwReloaded = true;
      try {
        try{ if(typeof window.clearSoftNavPrefetch==='function') window.clearSoftNavPrefetch(); }catch(_e){}
        location.reload();
      } catch (e) {}
    });
  }

  function checkForUpdate(reg) {
    /* Never hard-reload from build.json alone. While static files change,
       cacheVersion flips every request and a reload-before-SW-activates loop
       refreshes the app forever. Only ask the SW to update; one reload happens
       from controllerchange after the new worker claims (bindReloadOnUpdate). */
    if (reg && typeof reg.update === 'function') {
      try {
        reg.update();
      } catch (e) {}
    }
    if (typeof fetch !== 'function') return;
    fetch('/hbe-build.json', { cache: 'no-store', credentials: 'same-origin' })
      .then(function (resp) {
        if (!resp || !resp.ok) return null;
        return resp.json();
      })
      .then(function (data) {
        var remote = data && data.cacheVersion ? String(data.cacheVersion) : '';
        if (!remote) return;
        var worker =
          (navigator.serviceWorker && navigator.serviceWorker.controller) ||
          (reg && reg.active) ||
          null;
        return askCacheVersion(worker).then(function (local) {
          if (!local || !remote || local === remote) return;
          try {
            if (reg && reg.update) reg.update();
          } catch (e2) {}
          if (reg && reg.waiting) {
            try {
              reg.waiting.postMessage({ type: 'SKIP_WAITING' });
            } catch (e3) {}
          }
          /* Intentionally no location.reload() here. */
        });
      })
      .catch(function () {});
  }


  function askServiceWorker(type, timeoutMs) {
    return new Promise(function (resolve) {
      var worker =
        (navigator.serviceWorker && navigator.serviceWorker.controller) || null;
      if (!worker || typeof MessageChannel === 'undefined') {
        resolve(false);
        return;
      }
      var settled = false;
      var channel = new MessageChannel();
      var timer = setTimeout(function () {
        if (settled) return;
        settled = true;
        resolve(false);
      }, timeoutMs || 2500);
      channel.port1.onmessage = function (event) {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        resolve(!!(event && event.data && event.data.ok));
      };
      try {
        worker.postMessage({ type: type }, [channel.port2]);
      } catch (e) {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        resolve(false);
      }
    });
  }

  function clearFloorSnapshots() {
    try {
      if (typeof sessionStorage !== 'undefined') {
        sessionStorage.removeItem('hbe_pos_floor_snapshot');
        sessionStorage.removeItem('hbe_pos_floor_snapshot_bar');
        sessionStorage.removeItem('hbe_pos_floor_snapshot_local');
        sessionStorage.removeItem('hbe_pos_floor_snapshot_bar_local');
      }
    } catch (e) {}
    try {
      if (typeof localStorage !== 'undefined') {
        localStorage.removeItem('hbe_pos_floor_snapshot');
        localStorage.removeItem('hbe_pos_floor_snapshot_bar');
      }
    } catch (e2) {}
  }

  /**
   * Offline→online: drop soft-nav HTML, SW runtime HTML/API leftovers, and
   * floor snapshots so the next paint is from the live server + IndexedDB sync.
   */
  function onReconnectFresh() {
    if (window.HbeOfflineSync && typeof window.HbeOfflineSync.runReconnect === 'function') {
      return window.HbeOfflineSync.runReconnect({ source: 'de_pwa' });
    }
    /* Fallback if sync module not on this page (login shell). */
    try {
      if (typeof window.clearSoftNavPrefetch === 'function') {
        window.clearSoftNavPrefetch();
      }
    } catch (e) {}
    clearFloorSnapshots();
    return askServiceWorker('PURGE_DATA_CACHES', 3000).finally(function () {
      try {
        window.dispatchEvent(
          new CustomEvent('hbe:online-sync', { detail: { source: 'de_pwa' } })
        );
      } catch (e2) {}
    });
  }

  function bindOnlineFreshSync() {
    if (window.__hbeOnlineFreshBound) return;
    window.__hbeOnlineFreshBound = true;
    /* POS pages own reconnect via HbeOfflineSync.bind; elsewhere still purge. */
    window.addEventListener('online', function () {
      if (window.HbeOfflineSync && window.__hbeOfflineSyncBound) return;
      onReconnectFresh();
    });
  }

  function register() {
    bindReloadOnUpdate();
    bindOnlineFreshSync();

    navigator.serviceWorker
      .register('/sw.js', { scope: '/', updateViaCache: 'none' })
      .then(function (reg) {
        resolveActiveCacheVersion(reg)
          .then(function (keep) {
            return pruneStaleAppCaches(keep);
          })
          .catch(function () {});
        checkForUpdate(reg);
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
        function onVisible() {
          if (document.visibilityState && document.visibilityState !== 'visible') {
            return;
          }
          checkForUpdate(reg);
        }
        document.addEventListener('visibilitychange', onVisible);
        window.addEventListener('focus', onVisible);
        window.addEventListener('pageshow', onVisible);
        window.setInterval(onVisible, 15000);
      })
      .catch(function () {
        /* Ignore — HTTPS / localhost required; silent in unsupported hosts. */
      });
  }

  window.__dePwaPruneStaleAppCaches = pruneStaleAppCaches;
  window.__dePwaPruneStalePosCaches = pruneStaleAppCaches;
  window.__hbeOnReconnectFresh = onReconnectFresh;

  if (document.readyState === 'complete') {
    register();
  } else {
    window.addEventListener('load', register);
  }
})();
