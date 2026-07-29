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

  function makeLocalOrderNo() {
    var d = new Date();
    var yy = String(d.getFullYear()).slice(-2);
    var mm = String(d.getMonth() + 1);
    if (mm.length < 2) mm = '0' + mm;
    var suffix = uuid().replace(/-/g, '').slice(0, 8).toUpperCase();
    return 'ORD-L-' + yy + mm + '-' + suffix;
  }

  function saveCatalog(snapshot) {
    var row = {
      id: CATALOG_KEY,
      savedAt: new Date().toISOString(),
      floor: snapshot.floor || null,
      menuItems: snapshot.menuItems || null,
      menuCategories: snapshot.menuCategories || null
    };
    return withStore(STORE_CATALOG, 'readwrite', function (store) {
      return idbReq(store.put(row));
    }).catch(function () {
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

    flushInflight = listOutbox()
      .then(function (rows) {
        rows = (rows || []).slice().sort(function (a, b) {
          return (a.id || 0) - (b.id || 0);
        });
        var flushed = 0;
        var authExpired = false;

        function next(i) {
          if (i >= rows.length) {
            return listOutbox().then(function (left) {
              return { flushed: flushed, remaining: left.length, authExpired: authExpired };
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
                        authExpired: true
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
                      error: err
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

  global.HbePosOffline = {
    isOnline: isOnline,
    uuid: uuid,
    makeLocalOrderNo: makeLocalOrderNo,
    resolveInvoiceApi: resolveInvoiceApi,
    saveCatalog: saveCatalog,
    loadCatalog: loadCatalog,
    saveDraft: saveDraft,
    loadDraft: loadDraft,
    enqueueOutbox: enqueueOutbox,
    listOutbox: listOutbox,
    flushOutbox: flushOutbox,
    postInvoice: postInvoice,
    tryPostWithConflictRetry: tryPostWithConflictRetry
  };
})(typeof window !== 'undefined' ? window : this);
