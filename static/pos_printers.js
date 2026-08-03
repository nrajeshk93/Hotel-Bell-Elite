/**
 * Per-PC POS printer preferences (localStorage).
 * Source of truth for auto-print behavior — not shared across machines.
 */
(function (global) {
  'use strict';

  var STORAGE_PREFIX = 'hbe_pos_printers_v1_';

  var DEFAULTS = {
    stationName: '',
    receiptPrinterLabel: '',
    kitchenPrinterLabel: '',
    barKotPrinterLabel: '',
    restaurantKotPrinterLabel: '',
    autoPrintKot: true,
    autoPrintReceiptOnSettle: false
  };

  function normalizeOutlet(outlet) {
    var o = String(outlet || '').trim().toLowerCase();
    if (o === 'bar') return 'bar';
    return 'restaurant';
  }

  function resolveOutlet(outlet) {
    if (outlet) return normalizeOutlet(outlet);
    var el =
      document.getElementById('pos-settings-page') ||
      document.getElementById('pos-invoice-page') ||
      document.getElementById('pos-tables-page') ||
      document.querySelector('[data-pos-outlet]');
    var attr = (el && el.getAttribute('data-pos-outlet')) || '';
    if (attr) return normalizeOutlet(attr);
    return (window.location.pathname || '').indexOf('/bar-point-of-sale') === 0
      ? 'bar'
      : 'restaurant';
  }

  function storageKey(outlet) {
    return STORAGE_PREFIX + resolveOutlet(outlet);
  }

  function coercePrefs(raw) {
    var src = raw && typeof raw === 'object' ? raw : {};
    return {
      stationName: String(src.stationName != null ? src.stationName : DEFAULTS.stationName),
      receiptPrinterLabel: String(
        src.receiptPrinterLabel != null ? src.receiptPrinterLabel : DEFAULTS.receiptPrinterLabel
      ),
      kitchenPrinterLabel: String(
        src.kitchenPrinterLabel != null ? src.kitchenPrinterLabel : DEFAULTS.kitchenPrinterLabel
      ),
      barKotPrinterLabel: String(
        src.barKotPrinterLabel != null ? src.barKotPrinterLabel : DEFAULTS.barKotPrinterLabel
      ),
      restaurantKotPrinterLabel: String(
        src.restaurantKotPrinterLabel != null
          ? src.restaurantKotPrinterLabel
          : DEFAULTS.restaurantKotPrinterLabel
      ),
      autoPrintKot:
        src.autoPrintKot != null ? !!src.autoPrintKot : DEFAULTS.autoPrintKot,
      autoPrintReceiptOnSettle:
        src.autoPrintReceiptOnSettle != null
          ? !!src.autoPrintReceiptOnSettle
          : DEFAULTS.autoPrintReceiptOnSettle
    };
  }

  function get(outlet) {
    try {
      var raw = localStorage.getItem(storageKey(outlet));
      if (!raw) return coercePrefs(null);
      return coercePrefs(JSON.parse(raw));
    } catch (e) {
      return coercePrefs(null);
    }
  }

  function set(outlet, prefs) {
    var next = coercePrefs(Object.assign({}, get(outlet), prefs || {}));
    try {
      localStorage.setItem(storageKey(outlet), JSON.stringify(next));
    } catch (e) {
      /* Quota / private mode — ignore. */
    }
    return next;
  }

  function shouldAutoPrintKot(outlet) {
    return !!get(outlet).autoPrintKot;
  }

  function shouldAutoPrintReceiptOnSettle(outlet) {
    return !!get(outlet).autoPrintReceiptOnSettle;
  }

  /** Print Agent role for KOT slips — Restaurant KOT (kitchen1) or Bar KOT (bar). */
  function kotPrinterRole(outlet) {
    return resolveOutlet(outlet) === 'bar' ? 'bar' : 'kitchen1';
  }

  /**
   * Send a KOT HTML slip to the Restaurant or Bar KOT printer via Hotel Print
   * Agent (silent — no Chrome print dialog).
   * Set opts.allowBrowserFallback = true only when a browser dialog is OK.
   */
  function printKotHtml(html, opts) {
    opts = opts || {};
    var role =
      opts.printerRole ||
      kotPrinterRole(opts.menuOutlet != null ? opts.menuOutlet : opts.outlet);
    var allowBrowser = opts.allowBrowserFallback === true;
    var browserPrint =
      typeof opts.browserPrint === 'function' ? opts.browserPrint : function () {};

    function fail(err) {
      var error =
        err && err.message
          ? err
          : new Error(
              'Print Agent did not print. Open Hotel Print Agent and map the KOT printer.'
            );
      // #region agent log
      (function (payload) {
        var body = JSON.stringify(payload);
        fetch('http://127.0.0.1:7764/ingest/3c15e9d7-8289-4a1b-877f-c72ceeda0753',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'42fa9a'},body:body}).catch(function(){});
        fetch('/api/hbe-agent-debug',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-Requested-With':'XMLHttpRequest'},body:body}).catch(function(){});
      })({sessionId:'42fa9a',hypothesisId:'B_D',location:'pos_printers.js:printKotHtml.fail',message:'printKotHtml fail',data:{role:role,allowBrowser:!!allowBrowser,err:error&&error.message,htmlLen:(html&&html.length)||0},timestamp:Date.now()});
      // #endregion
      if (allowBrowser) {
        browserPrint();
        return { via: 'browser', error: error };
      }
      return { via: 'failed', error: error };
    }

    if (!html && !(opts.text && String(opts.text).trim())) {
      return Promise.resolve(fail(new Error('Nothing to print.')));
    }
    if (
      typeof global.HotelPrintAgent !== 'object' ||
      typeof global.HotelPrintAgent.print !== 'function'
    ) {
      return Promise.resolve(
        fail(
          new Error(
            'Print Agent is not loaded. Refresh the page, or open Hotel Print Agent on this PC.'
          )
        )
      );
    }

    // #region agent log
    (function (payload) {
      var body = JSON.stringify(payload);
      fetch('http://127.0.0.1:7764/ingest/3c15e9d7-8289-4a1b-877f-c72ceeda0753',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'42fa9a'},body:body}).catch(function(){});
      fetch('/api/hbe-agent-debug',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-Requested-With':'XMLHttpRequest'},body:body}).catch(function(){});
    })({sessionId:'42fa9a',runId:'post-fix',hypothesisId:'F',location:'pos_printers.js:printKotHtml.attempt',message:'calling HotelPrintAgent.print',data:{role:role,allowBrowser:!!allowBrowser,htmlLen:(html&&html.length)||0,contentType:opts.text?'text':(opts.contentType||'html'),textLen:opts.text?String(opts.text).length:0,textPreview:opts.text?String(opts.text).slice(0,120):''},timestamp:Date.now()});
    // #endregion

    return global.HotelPrintAgent.print({
      printerRole: role,
      documentType: 'kot',
      /* Prefer plain text — agent HtmlToPlain left <style> CSS on thermal printers. */
      contentType: opts.text ? 'text' : opts.contentType || 'html',
      contentEncoding: 'utf8',
      content: opts.text ? String(opts.text) : html,
      copies: opts.copies || 1,
      jobId: opts.jobId || undefined,
      idempotencyKey: opts.idempotencyKey || opts.jobId || undefined
    })
      .then(function (data) {
        // #region agent log
        (function (payload) {
          var body = JSON.stringify(payload);
          fetch('http://127.0.0.1:7764/ingest/3c15e9d7-8289-4a1b-877f-c72ceeda0753',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'42fa9a'},body:body}).catch(function(){});
          fetch('/api/hbe-agent-debug',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-Requested-With':'XMLHttpRequest'},body:body}).catch(function(){});
        })({sessionId:'42fa9a',runId:'post-fix',hypothesisId:'F',location:'pos_printers.js:printKotHtml.ok',message:'agent print ok',data:{role:role,printerName:data&&data.printerName,jobId:data&&data.jobId,contentType:opts.text?'text':(opts.contentType||'html'),textLen:opts.text?String(opts.text).length:0},timestamp:Date.now()});
        // #endregion
        return { via: 'agent', data: data };
      })
      .catch(function (err) {
        return fail(err);
      });
  }

  /** Print Agent role for guest invoices — Restaurant / Bar Invoice (billing). */
  function invoicePrinterRole(/* outlet */) {
    return 'billing';
  }

  /**
   * Silent invoice/bill print via Hotel Print Agent (billing role).
   * Set opts.allowBrowserFallback = true to open Chrome print as a last resort.
   */
  function printInvoiceHtml(html, opts) {
    opts = opts || {};
    var role = invoicePrinterRole(opts.outlet);
    var allowBrowser = opts.allowBrowserFallback === true;
    var browserPrint =
      typeof opts.browserPrint === 'function' ? opts.browserPrint : function () {};

    function fail(err) {
      var error =
        err && err.message
          ? err
          : new Error(
              'Print Agent did not print. Open Hotel Print Agent and map the Invoice printer.'
            );
      if (allowBrowser) {
        browserPrint();
        return { via: 'browser', error: error };
      }
      return { via: 'failed', error: error };
    }

    if (!html) {
      return Promise.resolve(fail(new Error('Nothing to print.')));
    }
    if (
      typeof global.HotelPrintAgent !== 'object' ||
      typeof global.HotelPrintAgent.print !== 'function'
    ) {
      return Promise.resolve(
        fail(
          new Error(
            'Print Agent is not loaded. Refresh the page, or open Hotel Print Agent on this PC.'
          )
        )
      );
    }

    return global.HotelPrintAgent.print({
      printerRole: role,
      documentType: opts.documentType || 'receipt',
      contentType: 'html',
      contentEncoding: 'utf8',
      content: html,
      copies: opts.copies || 1,
      jobId: opts.jobId || undefined,
      idempotencyKey: opts.idempotencyKey || opts.jobId || undefined
    })
      .then(function (data) {
        return { via: 'agent', data: data };
      })
      .catch(function (err) {
        return fail(err);
      });
  }

  /** Apply stored prefs onto Printers panel fields marked data-pos-pc-printer. */
  function applyToPanel(panel, outlet) {
    if (!panel) return;
    var prefs = get(outlet);
    panel.querySelectorAll('[data-pos-pc-printer]').forEach(function (el) {
      var key = el.getAttribute('data-pos-pc-printer');
      if (!key || !(key in prefs)) return;
      if (el.type === 'checkbox') el.checked = !!prefs[key];
      else el.value = prefs[key] != null ? String(prefs[key]) : '';
    });
  }

  /** Read Printers panel fields into localStorage. */
  function saveFromPanel(panel, outlet) {
    if (!panel) return get(outlet);
    var patch = {};
    panel.querySelectorAll('[data-pos-pc-printer]').forEach(function (el) {
      var key = el.getAttribute('data-pos-pc-printer');
      if (!key) return;
      if (el.type === 'checkbox') patch[key] = !!el.checked;
      else patch[key] = el.value != null ? String(el.value) : '';
    });
    return set(outlet, patch);
  }

  function rolePrinter(printers, role) {
    if (!printers || typeof printers !== 'object') return '';
    var v = printers[role];
    if (v == null || v === '') {
      var key = Object.keys(printers).find(function (k) {
        return String(k).toLowerCase() === String(role).toLowerCase();
      });
      v = key != null ? printers[key] : '';
    }
    return String(v != null ? v : '').trim();
  }

  /**
   * Map Hotel Print Agent role → Windows printer names onto the Printers panel
   * fields (labels match EXE roles: Restaurant KOT, Invoice, Bar KOT).
   */
  function prefsFromAgentStatus(status, outlet) {
    var printers = (status && status.printers) || {};
    var o = resolveOutlet(outlet);
    var station = String(
      (status && (status.deviceName || status.DeviceName)) || ''
    ).trim();
    var kitchen1 = rolePrinter(printers, 'kitchen1');
    var billing = rolePrinter(printers, 'billing');
    var bar = rolePrinter(printers, 'bar');
    var patch = {
      stationName: station,
      /* Invoice field is data-pos-pc-printer="kitchenPrinterLabel" in the UI. */
      kitchenPrinterLabel: billing
    };
    if (o === 'bar') {
      /* Primary KOT field labeled "Bar KOT" → receiptPrinterLabel. */
      patch.receiptPrinterLabel = bar;
      patch.restaurantKotPrinterLabel = kitchen1;
      patch.barKotPrinterLabel = bar;
    } else {
      /* Primary KOT field labeled "Restaurant KOT" → receiptPrinterLabel. */
      patch.receiptPrinterLabel = kitchen1;
      patch.restaurantKotPrinterLabel = kitchen1;
      patch.barKotPrinterLabel = bar;
    }
    return patch;
  }

  function setAgentSyncStatus(panel, state) {
    if (!panel) return;
    var el = panel.querySelector('[data-pos-agent-sync-status]');
    if (!el) return;
    var ok = state && state.ok;
    var msg = (state && state.message) || '';
    el.hidden = !msg;
    el.textContent = msg;
    el.classList.toggle('is-ok', ok === true);
    el.classList.toggle('is-error', ok === false);
    el.classList.toggle('is-pending', ok == null);
  }

  function setPanelFieldsFromAgent(panel, fromAgent) {
    panel.querySelectorAll('[data-pos-pc-printer]').forEach(function (el) {
      if (el.type === 'checkbox') return;
      if (fromAgent) {
        el.readOnly = true;
        el.setAttribute('data-from-agent', '1');
        el.title = 'Configured in Hotel Print Agent — change mappings in the desktop app';
      } else {
        el.readOnly = false;
        el.removeAttribute('data-from-agent');
        el.removeAttribute('title');
      }
    });
  }

  /**
   * Pull station name + role printers from the local Hotel Print Agent EXE
   * (http://127.0.0.1:4567/status) and fill the Printers panel.
   */
  function syncFromAgent(panel, outlet, opts) {
    opts = opts || {};
    if (!panel) return Promise.resolve(null);
    outlet = resolveOutlet(outlet);

    if (
      typeof global.HotelPrintAgent !== 'object' ||
      typeof global.HotelPrintAgent.getStatus !== 'function'
    ) {
      setAgentSyncStatus(panel, {
        ok: false,
        message: 'Print Agent bridge not loaded on this page.'
      });
      setPanelFieldsFromAgent(panel, false);
      return Promise.resolve(null);
    }

    setAgentSyncStatus(panel, { ok: null, message: 'Reading Hotel Print Agent…' });

    var prep = Promise.resolve();
    if (
      opts.force &&
      typeof global.HotelPrintAgent.ensurePaired === 'function'
    ) {
      prep = global.HotelPrintAgent.ensurePaired(true).catch(function () {
        return null;
      });
    }

    return prep
      .then(function () {
        return global.HotelPrintAgent.getStatus(true);
      })
      .then(function (status) {
        var hasMapping =
          status &&
          ((status.printers && Object.keys(status.printers).length) ||
            status.deviceName);
        if (!status || (!status.ok && !hasMapping)) {
          setAgentSyncStatus(panel, {
            ok: false,
            message:
              'Hotel Print Agent is not running on this PC. Open it from the system tray, map printers, then Refresh.'
          });
          setPanelFieldsFromAgent(panel, false);
          return null;
        }

        var patch = prefsFromAgentStatus(status, outlet);
        set(outlet, patch);
        applyToPanel(panel, outlet);
        setPanelFieldsFromAgent(panel, true);

        var live = !!(status.ok && !status.offline);
        var bits = [];
        if (patch.stationName) bits.push(patch.stationName);
        bits.push(live ? 'live from agent' : 'last known mapping');
        setAgentSyncStatus(panel, {
          ok: live,
          message:
            (live ? 'From Hotel Print Agent' : 'Agent offline') +
            (bits.length ? ' · ' + bits.join(' · ') : '')
        });
        return patch;
      })
      .catch(function () {
        setAgentSyncStatus(panel, {
          ok: false,
          message:
            'Could not reach Hotel Print Agent. Open the EXE on this PC and try Refresh.'
        });
        setPanelFieldsFromAgent(panel, false);
        return null;
      });
  }

  function bindPanel(page) {
    if (!page) return;
    var panel = page.querySelector('[data-panel="printers"]');
    if (!panel || panel.getAttribute('data-pos-pc-printers-bound') === '1') return;
    panel.setAttribute('data-pos-pc-printers-bound', '1');
    var outlet = resolveOutlet(
      page.getAttribute('data-pos-outlet') || resolveOutlet()
    );
    applyToPanel(panel, outlet);
    syncFromAgent(panel, outlet, { force: true });

    var refreshBtn = panel.querySelector('[data-pos-agent-refresh]');
    if (refreshBtn && refreshBtn.getAttribute('data-bound') !== '1') {
      refreshBtn.setAttribute('data-bound', '1');
      refreshBtn.addEventListener('click', function () {
        refreshBtn.disabled = true;
        syncFromAgent(panel, outlet, { force: true }).finally(function () {
          refreshBtn.disabled = false;
        });
      });
    }

    function persist() {
      /* Agent-synced fields are read-only; only persist manual overrides when offline. */
      if (panel.querySelector('[data-pos-pc-printer][data-from-agent="1"]')) return;
      saveFromPanel(panel, outlet);
      var status = document.getElementById('pos-set-save-status');
      if (status) {
        status.textContent = 'Saved on this PC';
        status.hidden = false;
        status.classList.remove('is-error');
      }
    }

    panel.addEventListener('change', function (e) {
      var t = e.target;
      if (!t || !t.matches('[data-pos-pc-printer]')) return;
      persist();
    });
    panel.addEventListener('input', function (e) {
      var t = e.target;
      if (!t || !t.matches('[data-pos-pc-printer]')) return;
      if (t.type === 'checkbox') return;
      persist();
    });
  }

  global.hbePosPrinterPrefs = {
    get: get,
    set: set,
    resolveOutlet: resolveOutlet,
    shouldAutoPrintKot: shouldAutoPrintKot,
    shouldAutoPrintReceiptOnSettle: shouldAutoPrintReceiptOnSettle,
    kotPrinterRole: kotPrinterRole,
    printKotHtml: printKotHtml,
    invoicePrinterRole: invoicePrinterRole,
    printInvoiceHtml: printInvoiceHtml,
    applyToPanel: applyToPanel,
    saveFromPanel: saveFromPanel,
    syncFromAgent: syncFromAgent,
    bindPanel: bindPanel,
    DEFAULTS: DEFAULTS
  };
})(window);
