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
   * Agent. opts.menuOutlet / opts.printerRole selects the destination.
   * Falls back to opts.browserPrint when the agent is offline.
   */
  function printKotHtml(html, opts) {
    opts = opts || {};
    var role =
      opts.printerRole ||
      kotPrinterRole(opts.menuOutlet != null ? opts.menuOutlet : opts.outlet);
    var browserPrint =
      typeof opts.browserPrint === 'function' ? opts.browserPrint : function () {};

    if (
      !html ||
      typeof global.HotelPrintAgent !== 'object' ||
      typeof global.HotelPrintAgent.print !== 'function'
    ) {
      browserPrint();
      return Promise.resolve({ via: 'browser' });
    }

    return global.HotelPrintAgent.print({
      printerRole: role,
      documentType: 'kot',
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
      .catch(function () {
        browserPrint();
        return { via: 'browser' };
      });
  }

  /** Print Agent role for guest invoices — Restaurant / Bar Invoice (billing). */
  function invoicePrinterRole(/* outlet */) {
    return 'billing';
  }

  /**
   * Send a guest invoice HTML slip to the station’s Restaurant/Bar Invoice
   * (billing) printer via Hotel Print Agent. Falls back to opts.browserPrint
   * when the agent is offline.
   */
  function printInvoiceHtml(html, opts) {
    opts = opts || {};
    var role = invoicePrinterRole(opts.outlet);
    var browserPrint =
      typeof opts.browserPrint === 'function' ? opts.browserPrint : function () {};

    if (
      !html ||
      typeof global.HotelPrintAgent !== 'object' ||
      typeof global.HotelPrintAgent.print !== 'function'
    ) {
      browserPrint();
      return Promise.resolve({ via: 'browser' });
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
      .catch(function () {
        browserPrint();
        return { via: 'browser' };
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

  function bindPanel(page) {
    if (!page) return;
    var panel = page.querySelector('[data-panel="printers"]');
    if (!panel || panel.getAttribute('data-pos-pc-printers-bound') === '1') return;
    panel.setAttribute('data-pos-pc-printers-bound', '1');
    var outlet = resolveOutlet(
      page.getAttribute('data-pos-outlet') || resolveOutlet()
    );
    applyToPanel(panel, outlet);

    function persist() {
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
    bindPanel: bindPanel,
    DEFAULTS: DEFAULTS
  };
})(window);
