/**
 * Hotel Bell Elite — browser bridge to the local Hotel Print Agent.
 *
 * Works from cloud https://belleliteaccounts.com (and local dev):
 * 1) Probes http://127.0.0.1:4567 so this PC's agent wins over another station
 * 2) Pairs with SaaS (/api/print-agent/browser-pair?agentId=…) for the API key
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

  function sleep(ms) {
    return new Promise(function (resolve) {
      setTimeout(resolve, ms);
    });
  }

  /**
   * Ask the loopback agent who it is (no SaaS key required for /status).
   * Retries briefly — EXE can take a moment after Windows logon / tray start.
   */
  function probeLocalAgent(attempts) {
    var total = typeof attempts === 'number' ? attempts : 1;
    var tryOnce = function () {
      return fetch(baseUrl() + '/status', {
        method: 'GET',
        headers: { Accept: 'application/json' },
        mode: 'cors',
        cache: 'no-store',
        credentials: 'omit'
      }).then(function (resp) {
        return resp.json().then(function (data) {
          return { ok: resp.ok, status: resp.status, data: data || {} };
        });
      });
    };

    var run = function (left) {
      return tryOnce().then(
        function (result) {
          if (result.ok && result.data && result.data.ok !== false) {
            return result;
          }
          if (left <= 1) return result;
          return sleep(350).then(function () {
            return run(left - 1);
          });
        },
        function () {
          if (left <= 1) {
            return { ok: false, status: 0, data: { ok: false, offline: true } };
          }
          return sleep(350).then(function () {
            return run(left - 1);
          });
        }
      );
    };

    return run(Math.max(1, total));
  }

  function agentIdFromStatus(data) {
    if (!data || typeof data !== 'object') return '';
    return String(data.agentId || data.agent_id || '').trim();
  }

  function pairUrl(agentId) {
    var qs = [];
    if (agentId) qs.push('agentId=' + encodeURIComponent(agentId));
    return '/api/print-agent/browser-pair' + (qs.length ? '?' + qs.join('&') : '');
  }

  /** Pull API key from cloud so https://belleliteaccounts.com can authorize localhost prints. */
  function ensurePaired(force) {
    var store = loadStore();
    if (!force && store.apiKey && store.agentId) {
      return Promise.resolve(store);
    }
    if (pairPromise && !force) return pairPromise;

    pairPromise = probeLocalAgent(force ? 3 : 2)
      .then(function (local) {
        var localId = agentIdFromStatus(local && local.data);
        var preferId = localId || String(store.agentId || '').trim();
        return fetchSaas(pairUrl(preferId)).then(function (result) {
          /* Local agent found but SaaS has no row for that id — fall back to latest. */
          if (
            (!result.ok || !result.data || !result.data.ok || !result.data.apiKey) &&
            preferId
          ) {
            return fetchSaas(pairUrl(''));
          }
          return result;
        });
      })
      .catch(function () {
        return fetchSaas(pairUrl(String(store.agentId || '').trim()));
      })
      .then(function (result) {
        if (!result.ok || !result.data || !result.data.ok || !result.data.apiKey) {
          throw new Error(
            (result.data && result.data.error) ||
              'Print Agent is not paired. Install Hotel Print Agent on this PC, Register it, and leave it running in the tray.'
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
    var id = agentIdFromStatus(out);
    if (id && id !== store.agentId) {
      saveStore({ agentId: id });
    }
    return out;
  }

  function getStatus(force) {
    var now = Date.now();
    if (!force && statusCache.data && now - statusCache.at < 5000) {
      return Promise.resolve(statusCache.data);
    }
    return ensurePaired(!!force)
      .catch(function () {
        return loadStore();
      })
      .then(function () {
        return probeLocalAgent(force ? 3 : 2).then(function (probed) {
          if (probed.ok && probed.data) {
            return probed;
          }
          return fetchLocal('/status');
        });
      })
      .then(function (result) {
        if (result.ok && result.data && result.data.ok !== false) {
          var data = enrichStatus(result.data);
          /* Keep SaaS mapping fresh for this PC's agent id. */
          if (force && agentIdFromStatus(data)) {
            ensurePaired(true).catch(function () {});
          }
          statusCache = { at: Date.now(), data: data };
          return data;
        }
        statusCache = { at: Date.now(), data: { ok: false } };
        return { ok: false, error: (result.data && result.data.error) || 'Agent offline' };
      })
      .catch(function () {
        /* Local agent unreachable — keep last known mapping for Settings UI only.
           ok:false so print() never treats this as a live agent. */
        var store = loadStore();
        var fallback = {
          ok: false,
          offline: true,
          deviceName: store.deviceName || '',
          printers: store.mappedPrinters || {}
        };
        statusCache = { at: Date.now(), data: fallback };
        return fallback;
      });
  }

  function printLocal(job) {
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
      .catch(function () {
        return loadStore();
      })
      .then(function () {
        return probeLocalAgent(2);
      })
      .then(function (result) {
        if (!result.ok || !result.data || result.data.ok === false) {
          throw new Error(
            'Print Agent is not running on this PC. Open Hotel Print Agent, leave it in the system tray (enable Start with Windows), then try again.'
          );
        }
        statusCache = { at: Date.now(), data: enrichStatus(result.data) };
        return fetchLocal('/print', { method: 'POST', body: payload });
      })
      .then(function (result) {
        if (result.status === 401) {
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

  var queueConfig = { loaded: false, serverPrintQueue: true, printQueuePrimary: true };
  var queueConfigPromise = null;

  function loadQueueConfig(force) {
    if (queueConfig.loaded && !force) {
      return Promise.resolve(queueConfig);
    }
    if (queueConfigPromise && !force) {
      return queueConfigPromise;
    }
    queueConfigPromise = fetchSaas('/api/print-agent/config')
      .then(function (result) {
        if (result.ok && result.data && result.data.ok) {
          queueConfig.serverPrintQueue = result.data.serverPrintQueue !== false;
          queueConfig.printQueuePrimary = result.data.printQueuePrimary !== false;
        }
        queueConfig.loaded = true;
        return queueConfig;
      })
      .catch(function () {
        queueConfig.loaded = true;
        return queueConfig;
      })
      .finally(function () {
        queueConfigPromise = null;
      });
    return queueConfigPromise;
  }

  function serverQueueEnabled() {
    return queueConfig.serverPrintQueue !== false;
  }

  function queuePrimaryEnabled() {
    return queueConfig.printQueuePrimary !== false;
  }

  function pollJobStatus(jobId, attempts) {
    var left = typeof attempts === 'number' ? attempts : 12;
    function step() {
      return fetch('/api/print-jobs/' + encodeURIComponent(jobId), {
        method: 'GET',
        credentials: 'same-origin',
        headers: { Accept: 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
        cache: 'no-store'
      })
        .then(function (resp) {
          return resp.json().then(function (data) {
            return { ok: resp.ok, data: data || {} };
          });
        })
        .then(function (result) {
          var job = (result.data && result.data.job) || {};
          var status = String(job.status || '').toUpperCase();
          if (status === 'PRINTED') {
            return { ok: true, via: 'queue', job: job };
          }
          if (status === 'FAILED') {
            throw new Error(job.error || job.error_message || 'Print job failed.');
          }
          if (left <= 1) {
            var agent = String(job.agentId || job.agent_id || '').trim();
            if (!agent && (status === 'QUEUED' || status === 'CREATED' || !status)) {
              throw new Error(
                job.error ||
                  job.error_message ||
                  'No Print Agent online. Open Hotel Print Agent on this PC.'
              );
            }
            return { ok: true, via: 'queue', pending: true, job: job };
          }
          left -= 1;
          return sleep(500).then(step);
        });
    }
    return step();
  }

  function submitJob(job) {
    if (!job) {
      return Promise.reject(new Error('Print job is required.'));
    }
    var body = {
      jobId: job.jobId || undefined,
      idempotencyKey: job.idempotencyKey || job.jobId || undefined,
      printerRole: job.printerRole || 'billing',
      documentType: job.documentType || 'receipt',
      documentId: job.documentId || job.document_id || 0,
      locationId: job.locationId || job.location_id || job.outlet || '',
      copies: job.copies || 1,
      contentType: job.contentType || undefined,
      contentEncoding: job.contentEncoding || undefined,
      content: job.content || undefined,
      resend: !!job.resend,
      items: job.items || undefined
    };
    return fetch('/api/print-jobs', {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
        'X-Requested-With': 'XMLHttpRequest'
      },
      body: JSON.stringify(body),
      cache: 'no-store'
    })
      .then(function (resp) {
        return resp.json().then(function (data) {
          return { ok: resp.ok, status: resp.status, data: data || {} };
        });
      })
      .then(function (result) {
        if (!result.ok || !result.data || result.data.ok === false) {
          throw new Error((result.data && result.data.error) || 'Could not queue print job.');
        }
        var queued = (result.data && result.data.job) || {};
        var jobId = queued.jobId || queued.job_id || body.jobId;
        if (!jobId) {
          return { ok: true, via: 'queue', job: queued };
        }
        return pollJobStatus(jobId, 12);
      });
  }

  function queuedJobHasAgent(result) {
    var queued = (result && result.job) || {};
    return String(queued.agentId || queued.agent_id || '').trim() !== '';
  }

  function printLocalIfPossible(job, err) {
    if (!job || !job.content) {
      return Promise.reject(
        err ||
          new Error(
            'Print Agent is not running on this PC. Open Hotel Print Agent and leave it in the tray.'
          )
      );
    }
    return printLocal(job).then(function (data) {
      data.via = 'local';
      return data;
    });
  }

  function print(job) {
    return loadQueueConfig(false).then(function (cfg) {
      /* Prefer the EXE on this PC (127.0.0.1:4567). The server queue only
         prints when a Print Agent is registered in SaaS; otherwise jobs sit
         QUEUED forever and look like a successful KOT. */
      return probeLocalAgent(2)
        .then(function (probed) {
          if (probed.ok && probed.data && probed.data.ok !== false) {
            return printLocalIfPossible(job);
          }
          if (cfg.printQueuePrimary === false) {
            return printLocalIfPossible(job);
          }
          return submitJob(job).then(function (result) {
            if (result && result.pending && !queuedJobHasAgent(result)) {
              return printLocalIfPossible(job);
            }
            return result;
          });
        })
        .catch(function (err) {
          if (cfg.printQueuePrimary === false) {
            return printLocalIfPossible(job, err);
          }
          return submitJob(job)
            .then(function (result) {
              if (result && result.pending && !queuedJobHasAgent(result)) {
                return printLocalIfPossible(job, err);
              }
              return result;
            })
            .catch(function (queueErr) {
              return printLocalIfPossible(job, queueErr || err);
            });
        });
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
      loadQueueConfig(false).catch(function () {});
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
    printLocal: printLocal,
    submitJob: submitJob,
    serverQueueEnabled: serverQueueEnabled,
    queuePrimaryEnabled: queuePrimaryEnabled,
    loadQueueConfig: loadQueueConfig,
    testPrint: testPrint,
    configure: configure,
    ensurePaired: ensurePaired,
    probeLocalAgent: probeLocalAgent,
    baseUrl: baseUrl
  };
})(window);
