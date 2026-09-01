/**
 * POS offline store — IndexedDB catalog, drafts, and sync outbox.
 * Exposed as window.HbePosOffline.
 */
(function (global) {
  'use strict';

  var DB_NAME = 'hbe_pos_offline';
  var DB_VERSION = 1;
  var STORE_CATALOG = 'catalog';
  var STORE_DRAFTS = 'drafts';
  var STORE_OUTBOX = 'outbox';
  var CATALOG_KEY = 'snapshot';
  /* Offline drafts/outbox are not kept forever (plan: finite window). */
  var MAX_OFFLINE_AGE_MS = 7 * 24 * 60 * 60 * 1000;

  var dbPromise = null;
  var flushInflight = null;

  function openDb() {
    if (dbPromise) return dbPromise;
    if (!global.indexedDB) {
      dbPromise = Promise.reject(new Error('IndexedDB unavailable'));
      return dbPromise;
    }
    dbPromise = new Promise(function (resolve, reject) {
      var req = global.indexedDB.open(DB_NAME, DB_VERSION);
      req.onupgradeneeded = function (event) {
        var db = event.target.result;
        if (!db.objectStoreNames.contains(STORE_CATALOG)) {
          db.createObjectStore(STORE_CATALOG, { keyPath: 'id' });
        }
        if (!db.objectStoreNames.contains(STORE_DRAFTS)) {
          db.createObjectStore(STORE_DRAFTS, { keyPath: 'localId' });
        }
        if (!db.objectStoreNames.contains(STORE_OUTBOX)) {
          db.createObjectStore(STORE_OUTBOX, { keyPath: 'id', autoIncrement: true });
        }
      };
      req.onsuccess = function () {
        resolve(req.result);
      };
      req.onerror = function () {
        reject(req.error || new Error('IndexedDB open failed'));
      };
    });
    return dbPromise;
  }

  function idbReq(req) {
    return new Promise(function (resolve, reject) {
      req.onsuccess = function () {
        resolve(req.result);
      };
      req.onerror = function () {
        reject(req.error || new Error('IndexedDB request failed'));
      };
    });
  }

  function withStore(storeName, mode, fn) {
    return openDb().then(function (db) {
      return new Promise(function (resolve, reject) {
        var tx = db.transaction(storeName, mode);
        var store = tx.objectStore(storeName);
        var done = false;
        function finish(err, result) {
          if (done) return;
          done = true;
          if (err) reject(err);
          else resolve(result);
        }
        try {
          Promise.resolve(fn(store)).then(
            function (result) {
              tx.oncomplete = function () {
                finish(null, result);
              };
              tx.onerror = function () {
                finish(tx.error || new Error('IndexedDB transaction failed'));
              };
              tx.onabort = function () {
                finish(tx.error || new Error('IndexedDB transaction aborted'));
              };
            },
            function (err) {
              try {
                tx.abort();
              } catch (e) {}
              finish(err);
            }
          );
        } catch (err) {
          finish(err);
        }
      });
    });
  }

  function isOnline() {
    return !(typeof navigator !== 'undefined' && navigator.onLine === false);
  }

  function offlineEntryAgeMs(iso) {
    var t = Date.parse(String(iso || ''));
    if (!isFinite(t)) return 0;
    return Date.now() - t;
  }

  function isOfflineEntryExpired(iso) {
    return offlineEntryAgeMs(iso) > MAX_OFFLINE_AGE_MS;
  }

  /**
   * Drop outbox + draft rows older than MAX_OFFLINE_AGE_MS.
   * Returns { outbox, drafts } counts removed.
   */
  function pruneExpiredOfflineData() {
    return Promise.all([
      withStore(STORE_OUTBOX, 'readwrite', function (store) {
        return idbReq(store.getAll()).then(function (rows) {
          var removed = 0;
          var ops = [];
          (rows || []).forEach(function (row) {
            if (!row || !isOfflineEntryExpired(row.createdAt)) return;
            removed += 1;
            ops.push(idbReq(store.delete(row.id)));
          });
          return Promise.all(ops).then(function () {
            return removed;
          });
        });
      }).catch(function () {
        return 0;
      }),
      withStore(STORE_DRAFTS, 'readwrite', function (store) {
        return idbReq(store.getAll()).then(function (rows) {
          var removed = 0;
          var ops = [];
          (rows || []).forEach(function (row) {
            if (!row) return;
            var stamp = row.updatedAt || row.createdAt;
            if (!isOfflineEntryExpired(stamp)) return;
            removed += 1;
            ops.push(idbReq(store.delete(row.localId)));
          });
          return Promise.all(ops).then(function () {
            return removed;
          });
        });
      }).catch(function () {
        return 0;
      })
    ]).then(function (counts) {
      return { outbox: counts[0] || 0, drafts: counts[1] || 0 };
    });
  }

  function uuid() {
    if (global.crypto && typeof global.crypto.randomUUID === 'function') {
      return global.crypto.randomUUID();
    }
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function (c) {
      var r = (Math.random() * 16) | 0;
      var v = c === 'x' ? r : (r & 0x3) | 0x8;
      return v.toString(16);
    });
  }

  function makeLocalOrderNo(outlet) {
    var d = new Date();
    var resolved = String(outlet || '').trim().toLowerCase();
    if (!resolved && typeof document !== 'undefined') {
      var el =
        document.getElementById('pos-invoice-page') ||
        document.querySelector('[data-pos-outlet]');
      if (el) resolved = String(el.getAttribute('data-pos-outlet') || '').trim().toLowerCase();
    }
    if (!resolved && typeof window !== 'undefined') {
      var path = String((window.location && window.location.pathname) || '');
      resolved = path.indexOf('/bar-point-of-sale') === 0 ? 'bar' : 'restaurant';
    }
    var year = d.getFullYear();
    var month = d.getMonth() + 1;
    var startYear = month >= 4 ? year : year - 1;
    var fy = startYear + '-' + String(startYear + 1).slice(-2);
    var suffix = uuid().replace(/-/g, '').slice(0, 6).toUpperCase();
    if (resolved === 'restaurant') {
      /* Offline draft; server replaces with SPC/{n}/{fy} on first successful sync. */
      return 'SPC/' + suffix + '/' + fy;
    }
    if (resolved === 'bar') {
      /* Offline draft; server replaces with INV/{n}/{fy} on first successful sync. */
      return 'INV/' + suffix + '/' + fy;
    }
    var yy = String(d.getFullYear()).slice(-2);
    var mm = String(d.getMonth() + 1);
    if (mm.length < 2) mm = '0' + mm;
    var offlineSuffix = uuid().replace(/-/g, '').slice(0, 8).toUpperCase();
    return 'ORD-L-' + yy + mm + '-' + offlineSuffix;
  }

  function saveCatalog(snapshot) {
    snapshot = snapshot || {};
    return loadCatalog()
      .catch(function () {
        return null;
      })
      .then(function (existing) {
        existing = existing || {};
        var row = {
          id: CATALOG_KEY,
          savedAt: new Date().toISOString(),
          floor: Object.prototype.hasOwnProperty.call(snapshot, 'floor')
            ? snapshot.floor
            : existing.floor || null,
          menuItems: Object.prototype.hasOwnProperty.call(snapshot, 'menuItems')
            ? snapshot.menuItems
            : existing.menuItems || null,
          menuCategories: Object.prototype.hasOwnProperty.call(snapshot, 'menuCategories')
            ? snapshot.menuCategories
            : existing.menuCategories || null,
          customers: Object.prototype.hasOwnProperty.call(snapshot, 'customers')
            ? snapshot.customers
            : existing.customers || []
        };
        return withStore(STORE_CATALOG, 'readwrite', function (store) {
          return idbReq(store.put(row));
        });
      })
      .catch(function () {
        return null;
      });
  }

  function loadCatalog() {
    return withStore(STORE_CATALOG, 'readonly', function (store) {
      return idbReq(store.get(CATALOG_KEY));
    }).catch(function () {
      return null;
    });
  }

  function saveDraft(localId, draft) {
    if (!localId) return Promise.resolve(null);
    var row = Object.assign({}, draft || {}, {
      localId: localId,
      updatedAt: new Date().toISOString()
    });
    return withStore(STORE_DRAFTS, 'readwrite', function (store) {
      return idbReq(store.put(row));
    }).catch(function () {
      return null;
    });
  }

  function loadDraft(localId) {
    if (!localId) return Promise.resolve(null);
    return withStore(STORE_DRAFTS, 'readonly', function (store) {
      return idbReq(store.get(localId));
    }).catch(function () {
      return null;
    });
  }

  function enqueueOutbox(entry) {
    var row = {
      localId: entry.localId || '',
      payload: entry.payload || {},
      createdAt: new Date().toISOString(),
      attempts: 0,
      lastError: ''
    };
    return withStore(STORE_OUTBOX, 'readwrite', function (store) {
      return idbReq(store.add(row));
    }).catch(function () {
      return null;
    });
  }

  function listOutbox() {
    return withStore(STORE_OUTBOX, 'readonly', function (store) {
      return idbReq(store.getAll());
    })
      .then(function (rows) {
        return Array.isArray(rows) ? rows : [];
      })
      .catch(function () {
        return [];
      });
  }

  function removeOutbox(id) {
    return withStore(STORE_OUTBOX, 'readwrite', function (store) {
      return idbReq(store.delete(id));
    }).catch(function () {
      return null;
    });
  }

  function pendingEntryMatches(row, payload, localId, orderNo) {
    if (localId && String((row && row.localId) || '').trim() === localId) return true;
    if (!orderNo) return false;
    var on = String((payload && (payload.orderNo || payload.order_no)) || '')
      .trim()
      .toLowerCase();
    return on === orderNo;
  }

  /** Remove unsynced draft/outbox rows by localId and/or orderNo. */
  function discardPending(opts) {
    opts = opts || {};
    var localId = String(opts.localId || '').trim();
    var orderNo = String(opts.orderNo || '')
      .trim()
      .toLowerCase();
    if (!localId && !orderNo) {
      return Promise.resolve({ drafts: 0, outbox: 0, removed: 0 });
    }
    return Promise.all([
      withStore(STORE_DRAFTS, 'readwrite', function (store) {
        return idbReq(store.getAll()).then(function (rows) {
          var removed = 0;
          var ops = [];
          (rows || []).forEach(function (row) {
            if (!pendingEntryMatches(row, row && row.payload, localId, orderNo)) return;
            removed += 1;
            ops.push(idbReq(store.delete(row.localId)));
          });
          return Promise.all(ops).then(function () {
            return removed;
          });
        });
      }).catch(function () {
        return 0;
      }),
      withStore(STORE_OUTBOX, 'readwrite', function (store) {
        return idbReq(store.getAll()).then(function (rows) {
          var removed = 0;
          var ops = [];
          (rows || []).forEach(function (row) {
            if (!pendingEntryMatches(row, row && row.payload, localId, orderNo)) return;
            removed += 1;
            ops.push(idbReq(store.delete(row.id)));
          });
          return Promise.all(ops).then(function () {
            return removed;
          });
        });
      }).catch(function () {
        return 0;
      })
    ]).then(function (counts) {
      var summary = {
        drafts: counts[0] || 0,
        outbox: counts[1] || 0,
        removed: (counts[0] || 0) + (counts[1] || 0)
      };
      if (summary.removed) {
        notifyChange('invoice', {
          discarded: true,
          localId: localId,
          orderNo: orderNo
        });
      }
      return summary;
    });
  }

  function updateOutboxError(id, attempts, lastError) {
    return withStore(STORE_OUTBOX, 'readwrite', function (store) {
      return idbReq(store.get(id)).then(function (row) {
        if (!row) return null;
        row.attempts = attempts;
        row.lastError = String(lastError || '');
        return idbReq(store.put(row));
      });
    }).catch(function () {
      return null;
    });
  }

  function resolveInvoiceApi(payload) {
    var outlet = '';
    if (payload && typeof payload === 'object') {
      outlet = String(payload.outlet || payload.posOutlet || '').trim().toLowerCase();
    }
    if (!outlet && typeof document !== 'undefined') {
      var el =
        document.getElementById('pos-invoice-page') ||
        document.querySelector('[data-pos-outlet], [data-pos-api-base]');
      if (el) {
        outlet = String(el.getAttribute('data-pos-outlet') || '').trim().toLowerCase();
        var base = String(el.getAttribute('data-pos-api-base') || '').replace(/\/$/, '');
        if (base) return base + '/api/invoices';
      }
    }
    if (!outlet && typeof window !== 'undefined') {
      if (String(window.location.pathname || '').indexOf('/bar-point-of-sale') === 0) {
        outlet = 'bar';
      }
    }
    if (outlet === 'bar') return '/bar-point-of-sale/api/invoices';
    return '/point-of-sale/api/invoices';
  }

  function postInvoice(payload, keepalive) {
    var opts = {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(payload)
    };
    if (keepalive) opts.keepalive = true;
    return fetch(resolveInvoiceApi(payload), opts).then(function (res) {
      var redirectedToLogin =
        res.redirected && String(res.url || '').indexOf('/login') !== -1;
      return res
        .json()
        .catch(function () {
          return {};
        })
        .then(function (data) {
          var errText = (data && data.error) || '';
          return {
            ok: res.ok && !!(data && data.ok),
            status: res.status,
            authExpired: res.status === 401 || res.status === 403 || redirectedToLogin,
            conflict:
              res.status === 409 ||
              /unique|order.?no|already exists/i.test(String(errText)),
            data: data || {}
          };
        });
    });
  }

  function tryPostWithConflictRetry(payload) {
    return postInvoice(payload).then(function (result) {
      if (result.ok || result.authExpired || !result.conflict) return result;
      var retryPayload = Object.assign({}, payload, { orderNo: makeLocalOrderNo() });
      return postInvoice(retryPayload).then(function (retry) {
        retry.payloadUsed = retryPayload;
        return retry;
      });
    });
  }

  /**
   * Drain outbox FIFO. onSynced(localId, invoice, payload) after each success.
   */
  function flushOutbox(opts) {
    opts = opts || {};
    if (!isOnline()) {
      return Promise.resolve({ flushed: 0, remaining: 0, skipped: true });
    }
    if (flushInflight) return flushInflight;

    flushInflight = pruneExpiredOfflineData()
      .then(function (pruned) {
        return listOutbox().then(function (rows) {
          return { pruned: pruned, rows: rows };
        });
      })
      .then(function (ctx) {
        var rows = (ctx.rows || []).slice().sort(function (a, b) {
          return (a.id || 0) - (b.id || 0);
        });
        var flushed = 0;
        var authExpired = false;
        var pruned = ctx.pruned || { outbox: 0, drafts: 0 };

        function next(i) {
          if (i >= rows.length) {
            return listOutbox().then(function (left) {
              return {
                flushed: flushed,
                remaining: left.length,
                authExpired: authExpired,
                pruned: pruned
              };
            });
          }
          var row = rows[i];
          var payload = Object.assign({}, row.payload || {});
          if (row.localId && !payload.clientLocalId) {
            payload.clientLocalId = row.localId;
          }

          return tryPostWithConflictRetry(payload)
            .catch(function () {
              return { ok: false, network: true, data: {} };
            })
            .then(function (result) {
              if (result.authExpired) {
                authExpired = true;
                return updateOutboxError(row.id, (row.attempts || 0) + 1, 'session expired').then(
                  function () {
                    return listOutbox().then(function (left) {
                      return {
                        flushed: flushed,
                        remaining: left.length,
                        authExpired: true,
                        pruned: pruned
                      };
                    });
                  }
                );
              }
              if (!result.ok) {
                var err =
                  (result.data && result.data.error) ||
                  (result.network ? 'network' : 'save failed');
                return updateOutboxError(row.id, (row.attempts || 0) + 1, err).then(function () {
                  return listOutbox().then(function (left) {
                    return {
                      flushed: flushed,
                      remaining: left.length,
                      authExpired: authExpired,
                      error: err,
                      pruned: pruned
                    };
                  });
                });
              }
              flushed += 1;
              var usedPayload = result.payloadUsed || payload;
              if (typeof opts.onSynced === 'function') {
                try {
                  opts.onSynced(row.localId, result.data.invoice || null, usedPayload);
                } catch (e) {}
              }
              return removeOutbox(row.id).then(function () {
                return next(i + 1);
              });
            });
        }

        return next(0);
      })
      .then(
        function (summary) {
          flushInflight = null;
          return summary;
        },
        function (err) {
          flushInflight = null;
          throw err;
        }
      );

    return flushInflight;
  }

  function listDrafts() {
    return withStore(STORE_DRAFTS, "readonly", function (store) {
      return idbReq(store.getAll());
    })
      .then(function (rows) {
        return Array.isArray(rows) ? rows : [];
      })
      .catch(function () {
        return [];
      });
  }

  function normalizeOutlet(value) {
    var o = String(value || "").trim().toLowerCase();
    if (o === "bar") return "bar";
    if (o === "restaurant") return "restaurant";
    return "";
  }

  function currentOutlet() {
    if (typeof document !== "undefined") {
      var el =
        document.getElementById("pos-invoice-page") ||
        document.getElementById("pos-tables-page") ||
        document.getElementById("pos-invoice-ledger-page") ||
        document.querySelector("[data-pos-outlet]");
      if (el) {
        var fromEl = normalizeOutlet(el.getAttribute("data-pos-outlet"));
        if (fromEl) return fromEl;
      }
    }
    if (typeof window !== "undefined") {
      return String((window.location && window.location.pathname) || "").indexOf("/bar-point-of-sale") === 0
        ? "bar"
        : "restaurant";
    }
    return "restaurant";
  }

  function floorSnapshotKey(outlet) {
    return normalizeOutlet(outlet) === "bar"
      ? "hbe_pos_floor_snapshot_bar"
      : "hbe_pos_floor_snapshot";
  }

  var LOCAL_CHANNEL_NAME = "hbe-pos-local";
  var LOCAL_PING_KEY = "hbe_pos_local_ping";
  var localChannel = null;
  try {
    if (typeof BroadcastChannel !== "undefined") {
      localChannel = new BroadcastChannel(LOCAL_CHANNEL_NAME);
    }
  } catch (eChan) {}

  function notifyChange(kind, detail) {
    var msg = { kind: kind || "change", at: Date.now(), detail: detail || {} };
    try {
      if (localChannel) localChannel.postMessage(msg);
    } catch (ePost) {}
    try {
      if (typeof localStorage !== "undefined") {
        localStorage.setItem(LOCAL_PING_KEY, JSON.stringify(msg));
      }
    } catch (ePing) {}
  }

  function onChange(handler) {
    if (typeof handler !== "function") return function () {};
    function fromChannel(ev) {
      handler((ev && ev.data) || {});
    }
    function fromStorage(ev) {
      if (!ev || ev.key !== LOCAL_PING_KEY || !ev.newValue) return;
      try {
        handler(JSON.parse(ev.newValue));
      } catch (eParse) {}
    }
    if (localChannel) localChannel.addEventListener("message", fromChannel);
    if (typeof window !== "undefined") {
      window.addEventListener("storage", fromStorage);
    }
    return function () {
      if (localChannel) localChannel.removeEventListener("message", fromChannel);
      if (typeof window !== "undefined") {
        window.removeEventListener("storage", fromStorage);
      }
    };
  }

  function persistFloorSnapshot(floor, outlet) {
    if (!floor || !Array.isArray(floor.tables)) return floor;
    var key = floorSnapshotKey(outlet || currentOutlet());
    var blob = JSON.stringify({
      areas: Array.isArray(floor.areas) ? floor.areas : [],
      tables: floor.tables,
      savedAt: Date.now()
    });
    try {
      if (typeof sessionStorage !== "undefined") sessionStorage.setItem(key, blob);
    } catch (eSess) {}
    try {
      if (typeof localStorage !== "undefined") localStorage.setItem(key + "_local", blob);
    } catch (eLoc) {}
    return floor;
  }

  function readFloorSnapshot(outlet) {
    var key = floorSnapshotKey(outlet || currentOutlet());
    var parsed = null;
    function tryParse(raw) {
      if (!raw) return null;
      try {
        var data = JSON.parse(raw);
        if (data && Array.isArray(data.tables)) return data;
      } catch (eRead) {}
      return null;
    }
    try {
      if (typeof sessionStorage !== "undefined") parsed = tryParse(sessionStorage.getItem(key));
    } catch (eS) {}
    if (parsed) return parsed;
    try {
      if (typeof localStorage !== "undefined") parsed = tryParse(localStorage.getItem(key + "_local"));
    } catch (eL) {}
    return parsed;
  }

  function stampOf(row, payload) {
    var iso =
      (payload && (payload.savedAt || payload.saved_at)) ||
      (row && (row.updatedAt || row.createdAt)) ||
      "";
    var t = Date.parse(String(iso || ""));
    return isFinite(t) ? t : 0;
  }

  function pendingOrders() {
    return Promise.all([listOutbox(), listDrafts()]).then(function (pair) {
      var byId = {};
      function consider(localId, payload, row, invoiceId) {
        if (!payload || typeof payload !== "object") return;
        var lines = payload.lines;
        if (!Array.isArray(lines) || !lines.length) return;
        var id = String(localId || (row && row.localId) || "").trim();
        if (!id) {
          id =
            "anon-" +
            String(payload.orderNo || "") +
            "-" +
            String(payload.table || payload.table_label || "");
        }
        var stamp = stampOf(row, payload);
        var prev = byId[id];
        if (prev && prev._stamp > stamp) return;
        byId[id] = {
          localId: id,
          payload: payload,
          invoiceId: invoiceId || (row && row.invoiceId) || null,
          createdAt: (row && (row.updatedAt || row.createdAt)) || payload.savedAt || "",
          _stamp: stamp
        };
      }
      (pair[1] || []).forEach(function (row) {
        consider(row && row.localId, row && row.payload, row, row && row.invoiceId);
      });
      (pair[0] || []).forEach(function (row) {
        consider(row && row.localId, row && row.payload, row, null);
      });
      return Object.keys(byId).map(function (k) {
        return byId[k];
      });
    });
  }

  function findPendingForTable(tableName, outlet) {
    var needle = String(tableName || "").trim().toLowerCase();
    var want = normalizeOutlet(outlet) || currentOutlet();
    if (!needle) return Promise.resolve(null);
    return pendingOrders().then(function (orders) {
      var hit = null;
      orders.forEach(function (order) {
        var payload = order.payload || {};
        var ot = String(payload.orderType || payload.order_type || "dine_in").toLowerCase();
        if (ot !== "dine_in") return;
        if (!!(payload.customerBill || payload.customer_bill)) return;
        var table = String(payload.table || payload.table_label || "").trim().toLowerCase();
        if (table !== needle) return;
        var out = normalizeOutlet(payload.outlet || payload.posOutlet) || want;
        if (out !== want) return;
        if (!hit || order._stamp >= hit._stamp) hit = order;
      });
      return hit;
    });
  }

  function applyPendingToFloor(floor, outlet) {
    var areas = (floor && Array.isArray(floor.areas) && floor.areas) || [];
    var tables = ((floor && floor.tables) || []).map(function (t) {
      return Object.assign({}, t);
    });
    var want = normalizeOutlet(outlet) || currentOutlet() || "restaurant";
    return pendingOrders().then(function (orders) {
      var byTable = {};
      orders.forEach(function (order) {
        var payload = order.payload || {};
        var ot = String(payload.orderType || payload.order_type || "dine_in").toLowerCase();
        if (ot !== "dine_in") return;
        var table = String(payload.table || payload.table_label || "").trim();
        if (!table) return;
        var out = normalizeOutlet(payload.outlet || payload.posOutlet) || want;
        if (out !== want) return;
        var key = table.toLowerCase();
        if (!byTable[key] || order._stamp >= byTable[key]._stamp) {
          byTable[key] = order;
        }
      });
      Object.keys(byTable).forEach(function (key) {
        var order = byTable[key];
        var payload = order.payload || {};
        var bill = !!(payload.customerBill || payload.customer_bill);
        var guest = String(payload.customerName || payload.customer_name || "").trim();
        tables.forEach(function (t) {
          if (String(t.name || "").trim().toLowerCase() !== key) return;
          var st = String(t.status || "").trim().toLowerCase();
          if (st === "inactive" || st === "blocked") return;
          if (bill) {
            if (st === "occupied") {
              t.status = "available";
              t.customerName = "";
              t.customer_name = "";
            }
            return;
          }
          t.status = "occupied";
          if (guest) {
            t.customerName = guest;
            t.customer_name = guest;
          }
          if (!t.occupiedSince && !t.occupied_since) {
            t.occupiedSince = payload.savedAt || order.createdAt || new Date().toISOString();
          }
        });
      });
      return { areas: areas, tables: tables };
    });
  }

  function patchFloorOccupancy(tableName, status, extra, outlet) {
    extra = extra || {};
    var needle = String(tableName || "").trim().toLowerCase();
    if (!needle) return Promise.resolve(null);
    var want = normalizeOutlet(outlet) || currentOutlet();
    function apply(floor) {
      if (!floor || !Array.isArray(floor.tables)) return null;
      var next = {
        areas: Array.isArray(floor.areas) ? floor.areas : [],
        tables: floor.tables.map(function (t) {
          t = Object.assign({}, t);
          if (String(t.name || "").trim().toLowerCase() !== needle) return t;
          var st = String(t.status || "").trim().toLowerCase();
          if (st === "inactive" || st === "blocked") return t;
          t.status = status;
          if (status === "occupied") {
            if (extra.customerName) {
              t.customerName = extra.customerName;
              t.customer_name = extra.customerName;
            }
            t.occupiedSince =
              t.occupiedSince || extra.occupiedSince || new Date().toISOString();
          } else if (status === "available") {
            t.customerName = "";
            t.customer_name = "";
          }
          return t;
        })
      };
      persistFloorSnapshot(next, want);
      return next;
    }
    var local = readFloorSnapshot(want);
    var patched = apply(local);
    return loadCatalog()
      .then(function (snap) {
        var floor = (snap && snap.floor) || local;
        var next = apply(floor) || patched;
        if (next) {
          return saveCatalog({ floor: next }).then(function () {
            return next;
          });
        }
        return patched;
      })
      .catch(function () {
        return patched;
      });
  }

  function normalizeCustomer(customer) {
    if (!customer || typeof customer !== "object") return null;
    var name = String(
      customer.name || customer.customerName || customer.first_name || customer.customer_name || ""
    ).trim();
    var mobile = String(customer.mobile || customer.customerMobile || customer.customer_mobile || "")
      .replace(/\D/g, "")
      .slice(0, 10);
    if (!name && mobile.length < 2) return null;
    return {
      id: customer.id || (mobile ? "m:" + mobile : "n:" + name.toLowerCase()),
      name: name,
      first_name: name,
      mobile: mobile
    };
  }

  function rememberCustomer(customer) {
    var row = normalizeCustomer(customer);
    if (!row) return Promise.resolve(null);
    return loadCatalog().then(function (snap) {
      var list = ((snap && snap.customers) || []).slice();
      var idx = -1;
      var i;
      if (row.mobile.length === 10) {
        for (i = 0; i < list.length; i++) {
          if (String(list[i].mobile || "") === row.mobile) {
            idx = i;
            break;
          }
        }
      }
      if (idx < 0 && row.name) {
        var needle = row.name.toLowerCase();
        for (i = 0; i < list.length; i++) {
          if (
            String(list[i].name || list[i].first_name || "").trim().toLowerCase() === needle &&
            !String(list[i].mobile || "")
          ) {
            idx = i;
            break;
          }
        }
      }
      if (idx >= 0) {
        list[idx] = Object.assign({}, list[idx], row, {
          name: row.name || list[idx].name,
          first_name: row.name || list[idx].first_name,
          mobile: row.mobile || list[idx].mobile
        });
      } else {
        list.push(row);
      }
      return saveCatalog({ customers: list }).then(function () {
        notifyChange("customers", { name: row.name, mobile: row.mobile });
        return row;
      });
    });
  }

  function listSavedCustomers() {
    return loadCatalog().then(function (snap) {
      return ((snap && snap.customers) || []).slice();
    });
  }

  function searchSavedCustomers(q) {
    var query = String(q || "").trim();
    var digits = String(q || "").replace(/\D/g, "").slice(0, 10);
    return listSavedCustomers().then(function (list) {
      if (digits.length >= 2) {
        return list
          .filter(function (c) {
            return String(c.mobile || "").indexOf(digits) === 0;
          })
          .slice(0, 8);
      }
      if (query.length < 2) return [];
      var key = query.toLowerCase();
      return list
        .map(function (c) {
          var name = String(c.name || c.first_name || "");
          var score =
            typeof window !== "undefined" && typeof window.hbeBestSearchScore === "function"
              ? window.hbeBestSearchScore([name], key)
              : name.toLowerCase().indexOf(key);
          return { c: c, score: score };
        })
        .filter(function (row) {
          return row.score >= 0;
        })
        .sort(function (a, b) {
          return (
            b.score - a.score ||
            String(a.c.name || "").localeCompare(String(b.c.name || ""))
          );
        })
        .slice(0, 8)
        .map(function (row) {
          return row.c;
        });
    });
  }

  global.HbePosOffline = {
    isOnline: isOnline,
    uuid: uuid,
    makeLocalOrderNo: makeLocalOrderNo,
    resolveInvoiceApi: resolveInvoiceApi,
    saveCatalog: saveCatalog,
    loadCatalog: loadCatalog,
    saveDraft: saveDraft,
    loadDraft: loadDraft,
    listDrafts: listDrafts,
    enqueueOutbox: enqueueOutbox,
    listOutbox: listOutbox,
    discardPending: discardPending,
    flushOutbox: flushOutbox,
    pruneExpiredOfflineData: pruneExpiredOfflineData,
    MAX_OFFLINE_AGE_MS: MAX_OFFLINE_AGE_MS,
    postInvoice: postInvoice,
    tryPostWithConflictRetry: tryPostWithConflictRetry,
    notifyChange: notifyChange,
    onChange: onChange,
    persistFloorSnapshot: persistFloorSnapshot,
    readFloorSnapshot: readFloorSnapshot,
    pendingOrders: pendingOrders,
    findPendingForTable: findPendingForTable,
    applyPendingToFloor: applyPendingToFloor,
    patchFloorOccupancy: patchFloorOccupancy,
    rememberCustomer: rememberCustomer,
    listSavedCustomers: listSavedCustomers,
    searchSavedCustomers: searchSavedCustomers
  };
})(typeof window !== 'undefined' ? window : this);
