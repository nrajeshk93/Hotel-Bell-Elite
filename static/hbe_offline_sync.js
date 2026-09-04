/**
 * Hotel Bell Elite — offline↔online sync orchestrator.
 * Single path: purge runtime caches → flush outbox → refresh menu/floor → UI.
 * Does not change online save/KOT/settle business rules; only reconnect hygiene.
 */
(function (global) {
  'use strict';

  var SYNC_EVENT = 'hbe:online-sync';
  var PERIOD_MS = 45000;
  var inflight = null;
  var periodTimer = null;
  var chipEl = null;

  function offlineApi() {
    return global.HbePosOffline || null;
  }

  function isOnline() {
    var api = offlineApi();
    if (api && typeof api.isOnline === 'function') return api.isOnline();
    return !(typeof navigator !== 'undefined' && navigator.onLine === false);
  }

  function askServiceWorker(type, timeoutMs) {
    return new Promise(function (resolve) {
      var worker =
        (global.navigator &&
          global.navigator.serviceWorker &&
          global.navigator.serviceWorker.controller) ||
        null;
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
      }, timeoutMs || 3000);
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

  function clearSoftNav() {
    try {
      if (typeof global.clearSoftNavPrefetch === 'function') {
        global.clearSoftNavPrefetch();
      }
    } catch (e) {}
  }

  function outletApiBase(outlet) {
    return outlet === 'bar' ? '/bar-point-of-sale' : '/point-of-sale';
  }

  function fetchJson(url) {
    return fetch(url, {
      credentials: 'same-origin',
      cache: 'no-store',
      headers: { Accept: 'application/json', 'X-Requested-With': 'XMLHttpRequest' }
    }).then(function (res) {
      if (!res || !res.ok) return null;
      return res.json().catch(function () {
        return null;
      });
    });
  }

  function refreshMenuCatalog() {
    var api = offlineApi();
    if (!api || typeof api.saveCatalog !== 'function') {
      return Promise.resolve({ ok: false });
    }
    /* Refresh the outlet for the open POS page (catalog store is single-key). */
    var outlet = currentPageOutlet();
    var base = outletApiBase(outlet);
    return Promise.all([
      fetchJson(base + '/api/menu/items'),
      fetchJson(base + '/api/menu/categories')
    ]).then(function (pair) {
      var itemsBody = pair[0];
      var catsBody = pair[1];
      if (!itemsBody || !itemsBody.ok || !Array.isArray(itemsBody.items)) {
        return { ok: false };
      }
      if (!catsBody || !catsBody.ok || !Array.isArray(catsBody.categories)) {
        return { ok: false };
      }
      return api
        .saveCatalog({
          menuItems: itemsBody.items,
          menuCategories: catsBody.categories
        })
        .then(function () {
          return { ok: true, outlet: outlet };
        });
    });
  }

  function currentPageOutlet() {
    var api = offlineApi();
    if (api && typeof api.currentOutlet === 'function') return api.currentOutlet();
    var el =
      document.getElementById('pos-invoice-page') ||
      document.getElementById('pos-tables-page');
    if (el) {
      var o = String(el.getAttribute('data-pos-outlet') || '').toLowerCase();
      if (o === 'bar') return 'bar';
    }
    var path = (global.location && global.location.pathname) || '';
    return path.indexOf('/bar-point-of-sale') === 0 ? 'bar' : 'restaurant';
  }

  function refreshFloorFromServer() {
    var api = offlineApi();
    var outlet = currentPageOutlet();
    var url = outletApiBase(outlet) + '/api/floor';
    return fetchJson(url).then(function (data) {
      if (!data || data.ok === false) {
        return { ok: false, data: null };
      }
      if (api && typeof api.persistFloorSnapshot === 'function') {
        try {
          api.persistFloorSnapshot(data, outlet);
        } catch (e) {}
      }
      return { ok: true, data: data, outlet: outlet };
    });
  }

  function flushOutbox() {
    var api = offlineApi();
    if (!api || typeof api.flushOutbox !== 'function' || !isOnline()) {
      return Promise.resolve({ flushed: 0, skipped: true });
    }
    return api.flushOutbox({}).catch(function () {
      return { flushed: 0, error: 'network', failed: true };
    });
  }

  function ensureSyncChip() {
    if (chipEl && chipEl.isConnected) return chipEl;
    var shell =
      document.querySelector('.de-app-shell') ||
      document.getElementById('ep-workspace') ||
      document.body;
    if (!shell) return null;
    chipEl = document.getElementById('hbe-sync-chip');
    if (!chipEl) {
      chipEl = document.createElement('div');
      chipEl.id = 'hbe-sync-chip';
      chipEl.className = 'hbe-sync-chip';
      chipEl.setAttribute('role', 'status');
      chipEl.setAttribute('aria-live', 'polite');
      chipEl.hidden = true;
      shell.appendChild(chipEl);
    }
    return chipEl;
  }

  function setSyncChip(state, text) {
    var chip = ensureSyncChip();
    if (!chip) return;
    chip.classList.remove('is-syncing', 'is-pending', 'is-ok', 'is-err');
    if (!state) {
      chip.hidden = true;
      chip.textContent = '';
      return;
    }
    chip.hidden = false;
    chip.classList.add('is-' + state);
    chip.textContent = text || '';
  }

  function updatePendingChip() {
    var api = offlineApi();
    if (!api || typeof api.listOutbox !== 'function') {
      if (isOnline()) setSyncChip(null);
      return Promise.resolve();
    }
    return api.listOutbox().then(function (rows) {
      var n = (rows || []).length;
      if (!isOnline()) {
        setSyncChip(
          'pending',
          n
            ? 'Offline — ' + n + ' order' + (n === 1 ? '' : 's') + ' pending sync'
            : 'Offline — POS orders save on this device'
        );
        return;
      }
      if (n > 0) {
        setSyncChip(
          'pending',
          n + ' order' + (n === 1 ? '' : 's') + ' waiting to sync'
        );
      } else {
        setSyncChip(null);
      }
    });
  }

  function emitSync(detail) {
    try {
      global.dispatchEvent(new CustomEvent(SYNC_EVENT, { detail: detail || {} }));
    } catch (e) {}
    try {
      var api = offlineApi();
      if (api && typeof api.notifyChange === 'function') {
        api.notifyChange('sync', detail || {});
      }
    } catch (e2) {}
  }

  /**
   * Full reconnect pipeline. Safe to call often; coalesces overlapping runs.
   * keepSnapshotOnFailure: do not wipe floor snapshots if flush/floor fetch fails.
   */
  function runReconnect(opts) {
    opts = opts || {};
    if (!isOnline()) {
      updatePendingChip();
      return Promise.resolve({ ok: false, offline: true });
    }
    if (inflight) return inflight;

    setSyncChip('syncing', 'Syncing offline orders…');
    clearSoftNav();

    inflight = askServiceWorker('PURGE_DATA_CACHES', 3000)
      .catch(function () {
        return false;
      })
      .then(function () {
        return flushOutbox();
      })
      .then(function (flushSummary) {
        var failed = !!(flushSummary && (flushSummary.failed || flushSummary.error));
        var authExpired = !!(flushSummary && flushSummary.authExpired);
        return refreshMenuCatalog()
          .catch(function () {
            return { ok: false };
          })
          .then(function (menuSummary) {
            return refreshFloorFromServer()
              .catch(function () {
                return { ok: false };
              })
              .then(function (floorSummary) {
                var detail = {
                  source: opts.source || 'orchestrator',
                  flushed: (flushSummary && flushSummary.flushed) || 0,
                  remaining: (flushSummary && flushSummary.remaining) || 0,
                  flushFailed: failed,
                  authExpired: authExpired,
                  menuOk: !!(menuSummary && menuSummary.ok),
                  floorOk: !!(floorSummary && floorSummary.ok),
                  floor: floorSummary && floorSummary.data,
                  outlet: floorSummary && floorSummary.outlet
                };
                emitSync(detail);
                if (authExpired) {
                  setSyncChip('err', 'Session expired — sign in to sync');
                } else if (failed && detail.flushed === 0) {
                  setSyncChip('err', 'Sync paused — will retry');
                  updatePendingChip();
                } else if (detail.flushed > 0) {
                  setSyncChip(
                    'ok',
                    detail.flushed === 1
                      ? 'Synced 1 offline order'
                      : 'Synced ' + detail.flushed + ' offline orders'
                  );
                  setTimeout(function () {
                    updatePendingChip();
                  }, 2500);
                } else {
                  updatePendingChip();
                }
                return Object.assign({ ok: !failed && !authExpired }, detail);
              });
          });
      })
      .then(
        function (result) {
          inflight = null;
          return result;
        },
        function (err) {
          inflight = null;
          setSyncChip('err', 'Sync error — will retry');
          throw err;
        }
      );

    return inflight;
  }

  function bind() {
    if (global.__hbeOfflineSyncBound) return;
    global.__hbeOfflineSyncBound = true;

    global.addEventListener('online', function () {
      runReconnect({ source: 'online' });
    });
    global.addEventListener('offline', function () {
      updatePendingChip();
    });
    document.addEventListener('visibilitychange', function () {
      if (document.hidden) return;
      if (isOnline()) runReconnect({ source: 'visible' });
      else updatePendingChip();
    });

    if (periodTimer) clearInterval(periodTimer);
    periodTimer = setInterval(function () {
      if (!isOnline()) {
        updatePendingChip();
        return;
      }
      var api = offlineApi();
      if (!api || typeof api.listOutbox !== 'function') return;
      api.listOutbox().then(function (rows) {
        if (rows && rows.length) runReconnect({ source: 'interval' });
        else updatePendingChip();
      });
    }, PERIOD_MS);

    updatePendingChip();
  }

  /* Minimal chip styles (no separate CSS file required). */
  function injectChipStyles() {
    if (document.getElementById('hbe-sync-chip-style')) return;
    var style = document.createElement('style');
    style.id = 'hbe-sync-chip-style';
    style.textContent =
      '.hbe-sync-chip{position:fixed;left:50%;bottom:18px;transform:translateX(-50%);' +
      'z-index:9999;padding:8px 14px;border-radius:999px;font:600 12px/1.3 system-ui,sans-serif;' +
      'box-shadow:0 6px 20px rgba(0,0,0,.18);background:#111827;color:#fff;max-width:90vw;' +
      'text-align:center;pointer-events:none}' +
      '.hbe-sync-chip.is-pending{background:#92400e}' +
      '.hbe-sync-chip.is-syncing{background:#1d4ed8}' +
      '.hbe-sync-chip.is-ok{background:#047857}' +
      '.hbe-sync-chip.is-err{background:#b91c1c}';
    (document.head || document.documentElement).appendChild(style);
  }

  global.HbeOfflineSync = {
    runReconnect: runReconnect,
    updatePendingChip: updatePendingChip,
    refreshMenuCatalog: refreshMenuCatalog,
    refreshFloorFromServer: refreshFloorFromServer,
    SYNC_EVENT: SYNC_EVENT
  };

  function boot() {
    injectChipStyles();
    bind();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})(typeof window !== 'undefined' ? window : this);
