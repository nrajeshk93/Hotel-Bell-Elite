/**
 * Hotel Bell Elite — browser bridge to the local Hotel Print Agent.
 *
 * Works from cloud https://belleliteaccounts.com (and local dev):
 * 1) Pairs with SaaS (/api/print-agent/browser-pair) to get the agent API key
 * 2) Calls http://127.0.0.1:4567 with CORS + credentials headers
 * 3) Prints by printerRole — browser never needs Windows printer names
 */
(function (global) {
  'use strict';

  var DEFAULT_PORT = 4567;
  var STORAGE_KEY = 'hbe.printAgent';
  var statusCache = { at: 0, data: null };
  var pairPromise = null;

  function loadStore() {
    try {
      return JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}') || {};
    } catch (e) {
      return {};
    }
  }

  function saveStore(patch) {
    var cur = loadStore();
    Object.keys(patch || {}).forEach(function (k) {
      cur[k] = patch[k];
    });
    localStorage.setItem(STORAGE_KEY, JSON.stringify(cur));
    return cur;
  }

  function baseUrl() {
    var store = loadStore();
    var port = Number(store.port || DEFAULT_PORT) || DEFAULT_PORT;
    return 'http://127.0.0.1:' + port;
  }

  function headers(extra) {
    var store = loadStore();
    var h = {
      Accept: 'application/json',
      'Content-Type': 'application/json'
    };
    if (store.apiKey) h['X-Print-Agent-Key'] = store.apiKey;
    if (store.token) h.Authorization = 'Bearer ' + store.token;
    if (extra) {
      Object.keys(extra).forEach(function (k) {
        h[k] = extra[k];
      });
    }
    return h;
  }

  function fetchLocal(path, options) {
    var opts = options || {};
    return fetch(baseUrl() + path, {
      method: opts.method || 'GET',
      headers: headers(opts.headers),
      body: opts.body ? JSON.stringify(opts.body) : undefined,
      mode: 'cors',
      cache: 'no-store',
      credentials: 'omit'
    }).then(function (resp) {
      return resp.json().then(function (data) {
        return { ok: resp.ok, status: resp.status, data: data };
      });
    });
  }

  function fetchSaas(path, options) {
    var opts = options || {};
    return fetch(path, {
      method: opts.method || 'GET',
      credentials: 'same-origin',
      headers: {
        Accept: 'application/json',
        'X-Requested-With': 'XMLHttpRequest'
      },
      cache: 'no-store'
    }).then(function (resp) {
      return resp.json().then(function (data) {
        return { ok: resp.ok, status: resp.status, data: data };
      });
    });
  }

  /** Pull API key from cloud so https://belleliteaccounts.com can authorize localhost prints. */
  function ensurePaired(force) {
    var store = loadStore();
    if (!force && store.apiKey) {
      return Promise.resolve(store);
    }
    if (pairPromise && !force) return pairPromise;

    pairPromise = fetchSaas('/api/print-agent/browser-pair')
      .then(function (result) {
        if (!result.ok || !result.data || !result.data.ok || !result.data.apiKey) {
          throw new Error(
            (result.data && result.data.error) ||
              'Print Agent is not paired. Install Hotel Print Agent on this PC and Register it.'
          );
        }
        return saveStore({
          apiKey: result.data.apiKey,
          agentId: result.data.agentId || '',
          port: result.data.port || DEFAULT_PORT,
          deviceName: result.data.deviceName || '',
          mappedPrinters: result.data.mappedPrinters || {},
          pairedAt: Date.now()
        });
      })
      .finally(function () {
        pairPromise = null;
      });

    return pairPromise;
  }

  function enrichStatus(data) {
    var store = loadStore();
    var out = data && typeof data === 'object' ? Object.assign({}, data) : { ok: false };
    if (!out.deviceName && store.deviceName) out.deviceName = store.deviceName;
    if ((!out.printers || !Object.keys(out.printers).length) && store.mappedPrinters) {
      out.printers = store.mappedPrinters;
    }
    return out;
  }

  function getStatus(force) {
    var now = Date.now();
    if (!force && statusCache.data && now - statusCache.at < 5000) {
      return Promise.resolve(statusCache.data);
    }
    return ensurePaired(false)
      .catch(function () {
        return loadStore();
      })
      .then(function () {
        return fetchLocal('/status');
      })
      .then(function (result) {
        if (result.ok && result.data) {
          var data = enrichStatus(result.data);
          statusCache = { at: Date.now(), data: data };
          return data;
        }
        statusCache = { at: Date.now(), data: { ok: false } };
        return { ok: false, error: (result.data && result.data.error) || 'Agent offline' };
      })
      .catch(function () {
        /* Local agent offline — fall back to last paired device + mapped printers. */
        var store = loadStore();
        if (store.apiKey && (store.deviceName || store.mappedPrinters)) {
          var fallback = enrichStatus({
            ok: true,
            offline: true,
            deviceName: store.deviceName || '',
            printers: store.mappedPrinters || {}
          });
          statusCache = { at: Date.now(), data: fallback };
          return fallback;
        }
        statusCache = { at: Date.now(), data: { ok: false, offline: true } };
        return { ok: false, offline: true };
      });
  }

  function print(job) {
    if (!job || !job.content) {
      return Promise.reject(new Error('Print content is required.'));
    }
    var payload = {
      printerRole: job.printerRole || 'billing',
      documentType: job.documentType || 'receipt',
      contentType: job.contentType || 'html',
      contentEncoding: job.contentEncoding || 'utf8',
      content: job.content,
      copies: job.copies || 1,
      jobId: job.jobId || undefined,
      idempotencyKey: job.idempotencyKey || job.jobId || undefined
    };

    return ensurePaired(false)
      .then(function () {
        return getStatus(true);
      })
      .then(function (status) {
        if (!status || !status.ok) {
          throw new Error(
            'Print Agent is not running on this PC. Open Hotel Print Agent from the system tray.'
          );
        }
        return fetchLocal('/print', { method: 'POST', body: payload });
      })
      .then(function (result) {
        if (result.status === 401) {
          // Key rotated — re-pair once
          return ensurePaired(true).then(function () {
            return fetchLocal('/print', { method: 'POST', body: payload });
          });
        }
        return result;
      })
      .then(function (result) {
        if (!result.ok || !result.data || result.data.ok === false) {
          throw new Error((result.data && result.data.error) || 'Print failed.');
        }
        return result.data;
      });
  }

  function testPrint(printerRole) {
    return ensurePaired(false)
      .then(function () {
        return fetchLocal('/test-print', {
          method: 'POST',
          body: { printerRole: printerRole || 'billing' }
        });
      })
      .then(function (result) {
        if (!result.ok || !result.data || !result.data.ok) {
          throw new Error((result.data && result.data.error) || 'Test print failed.');
        }
        return result.data;
      });
  }

  function configure(options) {
    return saveStore(options || {});
  }

  // Warm pair shortly after cloud pages load (non-blocking).
  if (typeof document !== 'undefined') {
    var warm = function () {
      ensurePaired(false).catch(function () {});
    };
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', warm);
    } else {
      setTimeout(warm, 800);
    }
  }

  global.HotelPrintAgent = {
    getStatus: getStatus,
    print: print,
    testPrint: testPrint,
    configure: configure,
    ensurePaired: ensurePaired,
    baseUrl: baseUrl
  };
})(window);
