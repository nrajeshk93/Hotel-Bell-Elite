/**
 * Offline Sign In unlock — local PBKDF2 verifier in IndexedDB.
 * After a successful online login on this device, the same username/password
 * can unlock the cached app shell when the server is unreachable.
 * Never stores plaintext passwords.
 */
(function (global) {
  'use strict';

  var DB_NAME = 'hbe_offline_auth';
  var DB_VERSION = 1;
  var STORE = 'verifiers';
  var ITERATIONS = 120000;
  var HOME_PATH = '/home';
  var SESSION_FLAG = 'hbe_offline_session';

  var dbPromise = null;
  var _dbgQueue = [];

  // #region agent log
  function dbgLog(hypothesisId, location, message, data) {
    var payload = {
      sessionId: '74a6ba',
      runId: 'post-fix',
      hypothesisId: hypothesisId,
      location: location,
      message: message,
      data: data || {},
      timestamp: Date.now()
    };
    function send() {
      return fetch('http://127.0.0.1:7764/ingest/3c15e9d7-8289-4a1b-877f-c72ceeda0753', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Debug-Session-Id': '74a6ba' },
        body: JSON.stringify(payload)
      }).then(function () {
        return true;
      }).catch(function () {
        return false;
      });
    }
    send().then(function (ok) {
      if (ok) return;
      _dbgQueue.push(payload);
      try {
        global.sessionStorage.setItem('hbe_dbg_74a6ba', JSON.stringify(_dbgQueue.slice(-20)));
      } catch (err) {}
    });
  }
  function dbgFlush() {
    var queued = _dbgQueue.slice();
    try {
      var raw = global.sessionStorage.getItem('hbe_dbg_74a6ba');
      if (raw) queued = queued.concat(JSON.parse(raw) || []);
    } catch (err) {}
    _dbgQueue = [];
    try {
      global.sessionStorage.removeItem('hbe_dbg_74a6ba');
    } catch (err2) {}
    queued.forEach(function (payload) {
      fetch('http://127.0.0.1:7764/ingest/3c15e9d7-8289-4a1b-877f-c72ceeda0753', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Debug-Session-Id': '74a6ba' },
        body: JSON.stringify(payload)
      }).catch(function () {});
    });
  }
  if (global.addEventListener) {
    global.addEventListener('online', dbgFlush);
  }
  // #endregion

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
        if (!db.objectStoreNames.contains(STORE)) {
          db.createObjectStore(STORE, { keyPath: 'username' });
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

  function normUsername(value) {
    return String(value || '')
      .trim()
      .toLowerCase();
  }

  function bytesToB64(buf) {
    var bytes = buf instanceof ArrayBuffer ? new Uint8Array(buf) : buf;
    var s = '';
    for (var i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i]);
    return btoa(s);
  }

  function b64ToBytes(b64) {
    var s = atob(String(b64 || ''));
    var out = new Uint8Array(s.length);
    for (var i = 0; i < s.length; i++) out[i] = s.charCodeAt(i);
    return out;
  }

  function timingSafeEqual(a, b) {
    var aa = String(a || '');
    var bb = String(b || '');
    var len = Math.max(aa.length, bb.length);
    var diff = aa.length ^ bb.length;
    for (var i = 0; i < len; i++) {
      diff |= (aa.charCodeAt(i) || 0) ^ (bb.charCodeAt(i) || 0);
    }
    return diff === 0;
  }

  function deriveHash(password, saltBytes) {
    if (!global.crypto || !global.crypto.subtle) {
      return Promise.reject(new Error('Web Crypto unavailable'));
    }
    var enc = new TextEncoder();
    return global.crypto.subtle
      .importKey('raw', enc.encode(String(password || '')), 'PBKDF2', false, ['deriveBits'])
      .then(function (keyMaterial) {
        return global.crypto.subtle.deriveBits(
          {
            name: 'PBKDF2',
            salt: saltBytes,
            iterations: ITERATIONS,
            hash: 'SHA-256'
          },
          keyMaterial,
          256
        );
      })
      .then(function (bits) {
        return bytesToB64(bits);
      });
  }

  function putVerifier(record) {
    return openDb().then(function (db) {
      return new Promise(function (resolve, reject) {
        var tx = db.transaction(STORE, 'readwrite');
        tx.oncomplete = function () {
          resolve(true);
        };
        tx.onerror = function () {
          reject(tx.error || new Error('put failed'));
        };
        tx.objectStore(STORE).put(record);
      });
    });
  }

  function getVerifier(username) {
    var key = normUsername(username);
    if (!key) return Promise.resolve(null);
    return openDb().then(function (db) {
      return idbReq(db.transaction(STORE, 'readonly').objectStore(STORE).get(key));
    });
  }

  function clearAllVerifiers() {
    return openDb()
      .then(function (db) {
        var tx = db.transaction(STORE, 'readwrite');
        tx.objectStore(STORE).clear();
        return new Promise(function (resolve, reject) {
          tx.oncomplete = function () {
            resolve(true);
          };
          tx.onerror = function () {
            reject(tx.error || new Error('clear failed'));
          };
        });
      })
      .catch(function () {
        return false;
      });
  }

  function saveCredentials(username, password) {
    var key = normUsername(username);
    if (!key || !password) return Promise.resolve(false);
    if (!global.crypto || !global.crypto.getRandomValues) {
      return Promise.resolve(false);
    }
    var salt = new Uint8Array(16);
    global.crypto.getRandomValues(salt);
    return deriveHash(password, salt)
      .then(function (hashB64) {
        return putVerifier({
          username: key,
          saltB64: bytesToB64(salt),
          hashB64: hashB64,
          iterations: ITERATIONS,
          homePath: HOME_PATH,
          updatedAt: Date.now()
        });
      })
      .then(function () {
        return true;
      })
      .catch(function () {
        return false;
      });
  }

  function verifyCredentials(username, password) {
    return getVerifier(username)
      .then(function (row) {
        if (!row || !row.saltB64 || !row.hashB64) return false;
        var salt = b64ToBytes(row.saltB64);
        return deriveHash(password, salt).then(function (hashB64) {
          return timingSafeEqual(hashB64, row.hashB64);
        });
      })
      .catch(function () {
        return false;
      });
  }

  function hasAnyCredentials() {
    return openDb()
      .then(function (db) {
        return idbReq(db.transaction(STORE, 'readonly').objectStore(STORE).count());
      })
      .then(function (n) {
        return Number(n || 0) > 0;
      })
      .catch(function () {
        return false;
      });
  }

  function isBrowserOffline() {
    return typeof navigator !== 'undefined' && navigator.onLine === false;
  }

  function markOfflineSession() {
    try {
      global.sessionStorage.setItem(SESSION_FLAG, '1');
    } catch (err) {}
  }

  function clearOfflineSessionFlag() {
    try {
      global.sessionStorage.removeItem(SESSION_FLAG);
    } catch (err) {}
  }

  function htmlLooksLikeAppShell(html) {
    var body = String(html || '');
    if (!body) return false;
    if (body.indexOf('login-panel') !== -1 || body.indexOf('login-shell') !== -1) {
      return false;
    }
    return body.indexOf('de-app-shell') !== -1 || body.indexOf('ep-workspace') !== -1;
  }

  function resolveAppCacheName() {
    return new Promise(function (resolve) {
      function fromKeys() {
        if (!global.caches || !caches.keys) {
          resolve('hbe-app-offline');
          return;
        }
        caches.keys().then(function (keys) {
          var best = '';
          var bestN = -1;
          (keys || []).forEach(function (key) {
            var m = String(key).match(/^hbe-app-v(\d+)$/);
            if (!m) return;
            var n = parseInt(m[1], 10);
            if (n > bestN) {
              bestN = n;
              best = key;
            }
          });
          resolve(best || 'hbe-app-offline');
        }).catch(function () {
          resolve('hbe-app-offline');
        });
      }

      var worker =
        global.navigator &&
        global.navigator.serviceWorker &&
        global.navigator.serviceWorker.controller;
      if (!worker || !worker.postMessage) {
        fromKeys();
        return;
      }
      var done = false;
      var timer = setTimeout(function () {
        if (done) return;
        done = true;
        fromKeys();
      }, 800);
      try {
        var channel = new MessageChannel();
        channel.port1.onmessage = function (event) {
          if (done) return;
          done = true;
          clearTimeout(timer);
          var ver = String((event.data && event.data.cacheVersion) || '').trim();
          resolve(ver || 'hbe-app-offline');
        };
        worker.postMessage({ type: 'GET_CACHE_VERSION' }, [channel.port2]);
      } catch (err) {
        clearTimeout(timer);
        fromKeys();
      }
    });
  }

  function putCachedHtml(path, html) {
    if (!global.caches || !htmlLooksLikeAppShell(html)) return Promise.resolve(false);
    var key = String(path || HOME_PATH);
    return resolveAppCacheName()
      .then(function (name) {
        return caches.open(name || 'hbe-app-offline').then(function (cache) {
          var res = new Response(html, {
            status: 200,
            statusText: 'OK',
            headers: {
              'Content-Type': 'text/html; charset=utf-8',
              'X-Hbe-Offline-Shell': '1'
            }
          });
          return Promise.all([
            cache.put(key, res.clone()),
            cache.put(new Request(key, { credentials: 'same-origin' }), res)
          ]).then(function () {
            return true;
          });
        });
      })
      .catch(function () {
        return false;
      });
  }

  function readCachedHtml(path) {
    if (!global.caches || !caches.match) return Promise.resolve(null);
    var key = String(path || '');
    return caches
      .match(key)
      .then(function (res) {
        if (res) return res;
        return caches.match(new Request(key, { credentials: 'same-origin' }));
      })
      .then(function (res) {
        if (!res) return null;
        return res.text().then(function (html) {
          if (!htmlLooksLikeAppShell(html)) return null;
          return { path: key, html: html };
        });
      })
      .catch(function () {
        return null;
      });
  }

  function findCachedAppShell() {
    var paths = [HOME_PATH, '/point-of-sale/invoice', '/bar-point-of-sale/invoice'];
    var i = 0;
    function next() {
      if (i >= paths.length) return Promise.resolve(null);
      var path = paths[i++];
      return readCachedHtml(path).then(function (found) {
        return found || next();
      });
    }
    return next();
  }

  function replaceDocument(html) {
    try {
      global.document.open();
      global.document.write(html);
      global.document.close();
      return true;
    } catch (err) {
      return false;
    }
  }

  /**
   * Open cached workspace without relying on a network navigation
   * (which shows Chrome's ERR_INTERNET_DISCONNECTED dinosaur).
   */
  function goHome() {
    markOfflineSession();
    // #region agent log
    dbgLog('C', 'offline_auth.js:goHome:entry', 'goHome called', {
      online: typeof navigator !== 'undefined' ? navigator.onLine : null,
      hasSW: !!(global.navigator && global.navigator.serviceWorker && global.navigator.serviceWorker.controller)
    });
    // #endregion
    return findCachedAppShell().then(function (found) {
      // #region agent log
      dbgLog('C', 'offline_auth.js:goHome:result', 'cached shell lookup', {
        found: !!(found && found.html),
        path: (found && found.path) || null,
        htmlLen: found && found.html ? found.html.length : 0
      });
      // #endregion
      if (found && found.html) {
        try {
          global.history.replaceState(null, '', found.path || HOME_PATH);
        } catch (err) {}
        if (replaceDocument(found.html)) return true;
      }
      return false;
    });
  }

  function showNotice(el, message) {
    if (!el) return;
    el.textContent = String(message || '');
    el.hidden = !message;
  }

  function loginLooksSuccessful(res, html) {
    try {
      var url = String((res && res.url) || '');
      if (url.indexOf('/home') !== -1) return true;
      if (url.indexOf('/change-password') !== -1 || url.indexOf('change_password') !== -1) {
        return true;
      }
    } catch (err) {}
    return htmlLooksLikeAppShell(html);
  }

  function tryServerLogin(form) {
    var action = (form && form.getAttribute('action')) || '/login';
    var fd = new FormData(form);
    return fetch(action, {
      method: 'POST',
      body: fd,
      credentials: 'same-origin',
      redirect: 'follow',
      headers: { Accept: 'text/html' }
    }).then(function (res) {
      return res.text().then(function (html) {
        return { res: res, html: html };
      });
    });
  }

  function bindLoginForm(form, opts) {
    opts = opts || {};
    var notice = opts.noticeEl || null;
    if (!form || form.getAttribute('data-hbe-offline-auth') === '1') return;
    form.setAttribute('data-hbe-offline-auth', '1');

    var MSG_OFFLINE_READY =
      "You're offline. You can still sign in with your password on this device.";
    var MSG_OFFLINE_NEED_ONLINE =
      "You're offline. Sign in once while online on this device to enable offline access.";
    var MSG_BAD = 'Invalid username or password.';
    var MSG_NO_LOCAL =
      "Offline sign-in isn't set up on this device yet. Connect once, sign in, then try again offline.";
    var MSG_NO_SHELL =
      'Password OK, but no cached workspace is on this device yet. Connect, sign in, open Home once, then try offline again.';

    function syncBanner() {
      if (!notice) return;
      if (!isBrowserOffline()) {
        if (
          notice.textContent === MSG_OFFLINE_READY ||
          notice.textContent === MSG_OFFLINE_NEED_ONLINE ||
          notice.textContent === MSG_NO_LOCAL ||
          notice.textContent === MSG_BAD ||
          notice.textContent === MSG_NO_SHELL
        ) {
          notice.hidden = true;
        }
        return;
      }
      hasAnyCredentials().then(function (has) {
        showNotice(notice, has ? MSG_OFFLINE_READY : MSG_OFFLINE_NEED_ONLINE);
      });
    }

    form.addEventListener('submit', function (event) {
      event.preventDefault();
      var userInput = form.querySelector('#username, [name="username"]');
      var passInput = form.querySelector('#password, [name="password"]');
      var username = userInput ? userInput.value : '';
      var password = passInput ? passInput.value : '';
      var submitBtn = form.querySelector('button[type="submit"], .login-btn');
      if (submitBtn) submitBtn.disabled = true;
      // #region agent log
      dbgLog('D', 'offline_auth.js:submit', 'login submit', {
        offline: isBrowserOffline(),
        path: String((global.location && global.location.pathname) || ''),
        hasUser: !!String(username || '').trim(),
        swCtrl: !!(global.navigator && global.navigator.serviceWorker && global.navigator.serviceWorker.controller)
      });
      // #endregion

      function done() {
        if (submitBtn) submitBtn.disabled = false;
      }

      function unlockLocal() {
        return verifyCredentials(username, password).then(function (ok) {
          // #region agent log
          dbgLog('C', 'offline_auth.js:unlockLocal', 'local verify result', { ok: !!ok });
          // #endregion
          if (!ok) {
            return hasAnyCredentials().then(function (has) {
              showNotice(notice, has ? MSG_BAD : MSG_NO_LOCAL);
              done();
            });
          }
          return goHome().then(function (opened) {
            // #region agent log
            dbgLog('C', 'offline_auth.js:unlockLocal:nav', 'goHome opened', { opened: !!opened });
            dbgFlush();
            // #endregion
            if (opened) return;
            showNotice(notice, MSG_NO_SHELL);
            done();
          });
        });
      }

      if (isBrowserOffline()) {
        unlockLocal().catch(function () {
          showNotice(notice, MSG_NO_LOCAL);
          done();
        });
        return;
      }

      tryServerLogin(form)
        .then(function (payload) {
          var res = payload.res;
          var html = payload.html;
          if (loginLooksSuccessful(res, html)) {
            return saveCredentials(username, password).then(function () {
              clearOfflineSessionFlag();
              var dest = HOME_PATH;
              try {
                var u = String(res.url || '');
                if (u.indexOf('/change-password') !== -1) dest = '/change-password';
                else if (u.indexOf('/home') !== -1) dest = '/home';
              } catch (err) {}
              var warm =
                dest === HOME_PATH || dest.indexOf('/home') !== -1
                  ? putCachedHtml(HOME_PATH, html)
                  : Promise.resolve(false);
              return warm.then(function () {
                global.location.assign(dest);
              });
            });
          }
          if (!replaceDocument(html)) {
            showNotice(notice, MSG_BAD);
            done();
          }
        })
        .catch(function () {
          /* Server unreachable — fall back to local unlock. */
          unlockLocal().catch(function () {
            showNotice(notice, MSG_NO_LOCAL);
            done();
          });
        });
    });

    global.addEventListener('offline', syncBanner);
    global.addEventListener('online', syncBanner);
    syncBanner();
  }

  function bindLogoutClearing(root) {
    var scope = root || global.document;
    if (!scope || !scope.addEventListener) return;
    if (scope.documentElement && scope.documentElement.getAttribute('data-hbe-offline-logout') === '1') {
      return;
    }
    if (scope.documentElement) {
      scope.documentElement.setAttribute('data-hbe-offline-logout', '1');
    }

    function maybeClear(href) {
      var h = String(href || '');
      if (h.indexOf('/logout') === -1) return;
      /* Keep local unlock verifiers so staff can sign in offline again;
         only drop the ephemeral offline-session marker. */
      clearOfflineSessionFlag();
    }

    scope.addEventListener(
      'click',
      function (event) {
        var t = event.target;
        if (!t || !t.closest) return;
        var a = t.closest('a[href*="logout"], button[formaction*="logout"], .de-logout-btn');
        if (!a) return;
        maybeClear(a.getAttribute('href') || a.getAttribute('formaction') || '/logout');
        if (!isBrowserOffline()) return;
        /* Avoid hard-nav to /logout while offline (Chrome dinosaur page). */
        event.preventDefault();
        event.stopPropagation();
        // #region agent log
        dbgLog('A-fix', 'offline_auth.js:logout', 'offline logout → /', {
          path: String((global.location && global.location.pathname) || '')
        });
        // #endregion
        try {
          global.location.replace('/');
        } catch (err) {
          global.location.href = '/';
        }
      },
      true
    );
  }

  global.HbeOfflineAuth = {
    saveCredentials: saveCredentials,
    verifyCredentials: verifyCredentials,
    hasAnyCredentials: hasAnyCredentials,
    clearAllVerifiers: clearAllVerifiers,
    clearOfflineSessionFlag: clearOfflineSessionFlag,
    putCachedHtml: putCachedHtml,
    findCachedAppShell: findCachedAppShell,
    goHome: goHome,
    bindLoginForm: bindLoginForm,
    bindLogoutClearing: bindLogoutClearing,
    isBrowserOffline: isBrowserOffline
  };

  if (global.document && global.document.readyState === 'loading') {
    global.document.addEventListener('DOMContentLoaded', function () {
      bindLogoutClearing(global.document);
    });
  } else if (global.document) {
    bindLogoutClearing(global.document);
  }
})(typeof window !== 'undefined' ? window : this);
