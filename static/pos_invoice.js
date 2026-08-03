/**
 * Point of Sale — Invoice billing (search-first UI).
 * Soft-nav safe: expose window.initPosInvoicePage and re-bind idempotently.
 * Menu catalog loads from /point-of-sale/api/menu/items (Restaurant → Menu).
 * Tables load from /point-of-sale/api/floor (same SQLite layout as Tables/Settings).
 */
(function (global) {
  'use strict';

  var FLOOR_API = '/point-of-sale/api/floor';
  var MENU_ITEMS_API = '/point-of-sale/api/menu/items';
  var MENU_CATEGORIES_API = '/point-of-sale/api/menu/categories';
  var CUSTOMERS_API = '/point-of-sale/api/customers';
  var LEGACY_FLOOR_KEY = 'hbe_pos_floor_demo';
  var INVOICE_API = '/point-of-sale/api/invoices';
  var INVOICE_BY_TABLE_API = '/point-of-sale/api/invoices/by-table';

  function resolvePosApiBase() {
    var el =
      document.getElementById('pos-invoice-page') ||
      document.querySelector('[data-pos-api-base]');
    var base = (el && el.getAttribute('data-pos-api-base')) || '';
    if (!base) {
      base =
        (window.location.pathname || '').indexOf('/bar-point-of-sale') === 0
          ? '/bar-point-of-sale'
          : '/point-of-sale';
    }
    return String(base).replace(/\/$/, '') || '/point-of-sale';
  }

  function resolvePosOutlet() {
    var el =
      document.getElementById('pos-invoice-page') ||
      document.querySelector('[data-pos-outlet]');
    var outlet = (el && el.getAttribute('data-pos-outlet')) || '';
    if (!outlet) {
      outlet =
        (window.location.pathname || '').indexOf('/bar-point-of-sale') === 0
          ? 'bar'
          : 'restaurant';
    }
    return outlet;
  }

  function syncPosApiPaths() {
    var base = resolvePosApiBase();
    FLOOR_API = base + '/api/floor';
    MENU_ITEMS_API = base + '/api/menu/items';
    MENU_CATEGORIES_API = base + '/api/menu/categories';
    CUSTOMERS_API = base + '/api/customers';
    INVOICE_API = base + '/api/invoices';
    INVOICE_BY_TABLE_API = base + '/api/invoices/by-table';
  }

  var floorTablesCache = null;
  var floorTablesLoaded = false;
  var menuCatalog = [];
  var menuCatalogById = {};
  var menuCatalogStatus = 'idle';
  var menuCatalogInflight = null;
  var customerCache = [];
  var customerCacheQuery = '';
  var customerSearchTimer = null;
  var GST_RATE = 0.05;
  var CGST_RATE = 0.025;
  var UGST_RATE = 0.025;
  var VAT_RATE = 0.1;
  var taxRatesLoaded = false;
  var taxRatesInflight = null;

  function parseTaxPctField(values, namedKey, legacyIndex, defaultPct) {
    var src = values && typeof values === 'object' ? values : {};
    var field = src[namedKey];
    if (field == null) field = src['f' + legacyIndex];
    var raw = field && typeof field === 'object' ? field.value : field;
    if (raw === '' || raw == null) return defaultPct;
    var n = Number(raw);
    if (!isFinite(n) || n < 0) n = defaultPct;
    if (n > 100) n = 100;
    return n;
  }

  function taxRatesFromApiPayload(data) {
    if (data && data.taxRates && typeof data.taxRates === 'object') {
      var tr = data.taxRates;
      var cgst =
        tr.cgst != null
          ? Number(tr.cgst)
          : tr.cgst_pct != null
            ? Number(tr.cgst_pct) / 100
            : NaN;
      var ugst =
        tr.ugst != null
          ? Number(tr.ugst)
          : tr.ugst_pct != null
            ? Number(tr.ugst_pct) / 100
            : NaN;
      var vat =
        tr.vat != null
          ? Number(tr.vat)
          : tr.vat_pct != null
            ? Number(tr.vat_pct) / 100
            : NaN;
      if (isFinite(cgst) || isFinite(ugst) || isFinite(vat)) {
        return {
          cgst: isFinite(cgst) ? cgst : 0.025,
          ugst: isFinite(ugst) ? ugst : 0.025,
          vat: isFinite(vat) ? vat : 0.1,
          cgst_pct: (isFinite(cgst) ? cgst : 0.025) * 100,
          ugst_pct: (isFinite(ugst) ? ugst : 0.025) * 100,
          vat_pct: (isFinite(vat) ? vat : 0.1) * 100
        };
      }
    }
    if (data && data.settings) return taxRatesFromSettings(data.settings);
    return null;
  }

  function taxRatesFromSettings(settings) {
    var panels = settings && settings.panels && typeof settings.panels === 'object' ? settings.panels : {};
    var taxes = panels.taxes;
    var values = {};
    if (taxes && typeof taxes === 'object' && !Array.isArray(taxes)) {
      values = taxes.values && typeof taxes.values === 'object' ? taxes.values : taxes;
    } else if (Array.isArray(taxes)) {
      var idx = 0;
      taxes.forEach(function (field) {
        if (!field || typeof field !== 'object' || field.kind === 'listbox') return;
        values['f' + idx] = field;
        idx += 1;
      });
    }
    var cgstPct = parseTaxPctField(values, 'cgst_pct', 0, 2.5);
    var ugstPct = parseTaxPctField(values, 'ugst_pct', 1, 2.5);
    var vatPct = parseTaxPctField(values, 'vat_pct', 2, 10);
    return {
      cgst_pct: cgstPct,
      ugst_pct: ugstPct,
      vat_pct: vatPct,
      cgst: cgstPct / 100,
      ugst: ugstPct / 100,
      vat: vatPct / 100
    };
  }

  function applyTaxRates(rates) {
    if (!rates) return;
    if (rates.cgst != null && isFinite(Number(rates.cgst))) CGST_RATE = Number(rates.cgst);
    if (rates.ugst != null && isFinite(Number(rates.ugst))) UGST_RATE = Number(rates.ugst);
    if (rates.vat != null && isFinite(Number(rates.vat))) VAT_RATE = Number(rates.vat);
    GST_RATE = CGST_RATE + UGST_RATE;
    taxRatesLoaded = true;
    try {
      global.HBE_POS_TAX_RATES = {
        cgst: CGST_RATE,
        ugst: UGST_RATE,
        vat: VAT_RATE,
        cgst_pct: CGST_RATE * 100,
        ugst_pct: UGST_RATE * 100,
        vat_pct: VAT_RATE * 100
      };
    } catch (err) {}
  }

  function loadTaxRates(done) {
    if (taxRatesInflight) {
      taxRatesInflight.then(function () {
        if (typeof done === 'function') done(true);
      });
      return taxRatesInflight;
    }
    var url = resolvePosApiBase() + '/api/settings';
    taxRatesInflight = fetch(url, {
      method: 'GET',
      credentials: 'same-origin',
      headers: { Accept: 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
      cache: 'no-store'
    })
      .then(function (res) {
        return res.json().catch(function () {
          return {};
        });
      })
      .then(function (data) {
        var rates = taxRatesFromApiPayload(data);
        if (rates) applyTaxRates(rates);
        return taxRatesLoaded;
      })
      .catch(function () {
        return taxRatesLoaded;
      })
      .then(function (ok) {
        taxRatesInflight = null;
        if (typeof done === 'function') done(!!ok);
        return ok;
      });
    return taxRatesInflight;
  }

  function refreshTaxRatesAndSummary(page) {
    loadTaxRates(function () {
      if (page) {
        renderSummary(page);
        renderLines(page);
      }
    });
  }

  var LIQUOR_CATEGORY_RE =
    /\b(liquou?r|alcohol|whisky|whiskey|beer|wine|vodka|gin|rum|brandy|spirit|spirits|imfl|cocktail|cocktails|shots?|scotch|tequila|champagne|cider|liqueur|aperitif)\b/i;
  var DEFAULT_SERVICE_PCT = 0;
  var MIN_QUERY = 2;
  var NOTES_MAX = 200;
  var INV_MODALS = ['custom', 'line-note', 'discount', 'service', 'tip', 'coupon'];
  /* Debounced plain-save after line edits so soft-nav back to Tables does not
     drop unsaved dine-in items. Guest is the default first name (editable);
     silent autosave may send Guest in the payload when the field is blank,
     but must not overwrite the input while staff are typing. */
  var AUTOSAVE_DELAY_MS = 450;
  var DEFAULT_AUTOSAVE_CUSTOMER = 'Guest';
  var autosaveTimer = null;
  var saveInflight = null;
  /* Bumps on every local edit so an in-flight save cannot clear dirty and
     drop a name/mobile change that happened after the request started. */
  var dirtyEpoch = 0;
  var offlineFlushBound = false;

  var ORDER_TYPE_LABELS = {
    dine_in: 'Dine In',
    takeaway: 'Takeaway',
    delivery: 'Delivery'
  };

  /* Same status vocabulary as pos_tables.js — floor status is the single source
     of truth for both the Tables page and this picker. */
  var TABLE_STATUS_LABELS = {
    occupied: 'Occupied',
    reserved: 'Reserved',
    cleaning: 'Cleaning',
    inactive: 'Inactive',
    blocked: 'Inactive'
  };

  function mapTableStatus(status) {
    var s = String(status || '').trim().toLowerCase();
    if (s === 'blocked') return 'inactive';
    return s || 'available';
  }

  /* Only "occupied" blocks starting a new bill — reserved/cleaning/inactive stay
     selectable, matching the Tables page's own click-through behavior. */
  function tableBlocksNewBill(status) {
    return status === 'occupied';
  }

  var state = {
    lines: [],
    discountType: 'pct',
    discountValue: 0,
    /* Empty = whole-bill discount; otherwise only these line uids contribute. */
    discountLineUids: [],
    discountReason: '',
    /* null | 'discount' | 'coupon' — checkbox selection before existing modals. */
    discountSelectMode: null,
    discountSelectDraft: [],
    tipAmount: 0,
    tipEmployeeId: '',
    tipNote: '',
    tipPayrollId: null,
    serviceType: 'pct',
    serviceValue: DEFAULT_SERVICE_PCT,
    couponCode: '',
    activeIndex: -1,
    customerActiveIndex: -1,
    customerSuggestMode: '',
    orderNo: '',
    localId: '',
    lineSeq: 0,
    /* Set once this session's order has a real DB row (first Save or first KOT
       send). Resuming an occupied table's order also sets this — it is what
       lets Save/Send-KOT proceed against a table the floor shows as occupied,
       because it's this very invoice's table. */
    invoiceId: null,
    tableForOrder: '',
    resumeTableValue: '',
    resumeTableLabel: 'Select table…',
    /* True when local lines/meta differ from the last successful persist. */
    dirty: false,
    /* True after Generate Invoice (customer_bill_sent) — cart edits are locked. */
    invoiceGenerated: false,
    adjDraft: {
      discount: 'pct',
      service: 'pct'
    }
  };

  function $(sel, root) {
    return (root || document).querySelector(sel);
  }

  function escapeHtml(str) {
    return String(str || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function money(n) {
    var v = Math.round((Number(n) || 0) * 100) / 100;
    return '₹' + v.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  function formatDate(d) {
    var months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    return d.getDate() + ' ' + months[d.getMonth()] + ' ' + d.getFullYear();
  }

  function formatTime(d) {
    var h = d.getHours();
    var m = d.getMinutes();
    var ap = h >= 12 ? 'PM' : 'AM';
    var h12 = h % 12 || 12;
    return h12 + ':' + (m < 10 ? '0' : '') + m + ' ' + ap;
  }

  function offlineApi() {
    return global.HbePosOffline || null;
  }

  function ensureLocalId() {
    if (state.localId) return state.localId;
    var api = offlineApi();
    state.localId = api && api.uuid ? api.uuid() : String(Date.now());
    return state.localId;
  }

  function indianFiscalYearLabel(d) {
    var dt = d instanceof Date ? d : new Date();
    var year = dt.getFullYear();
    var month = dt.getMonth() + 1;
    var startYear = month >= 4 ? year : year - 1;
    return startYear + '-' + String(startYear + 1).slice(-2);
  }

  function noteOutletOrderSeq(orderNo) {
    /* Keep a high-water mark after the server confirms SPC|INV/{n}/{fy}.
       Client drafts must never mint from this — they use provisional hex ids. */
    var text = String(orderNo || '').trim();
    var spc = /^SPC\/(\d+)\/(\d{4}-\d{2})$/i.exec(text);
    if (spc) {
      var spcKey = 'hbe_pos_spc_seq_' + spc[2];
      var spcN = parseInt(spc[1], 10) || 0;
      if (spcN >= 1) {
        try {
          var spcCur = parseInt(localStorage.getItem(spcKey) || '0', 10) || 0;
          if (spcN > spcCur) localStorage.setItem(spcKey, String(spcN));
        } catch (e) {}
      }
      return;
    }
    var inv = /^INV\/(\d+)\/(\d{4}-\d{2})$/i.exec(text);
    if (!inv) return;
    var invKey = 'hbe_pos_inv_seq_' + inv[2];
    var invN = parseInt(inv[1], 10) || 0;
    if (invN < 1) return;
    try {
      var invCur = parseInt(localStorage.getItem(invKey) || '0', 10) || 0;
      if (invN > invCur) localStorage.setItem(invKey, String(invN));
    } catch (e2) {}
  }

  function randomOrderSuffix() {
    try {
      if (global.crypto && typeof global.crypto.getRandomValues === 'function') {
        var buf = new Uint8Array(3);
        global.crypto.getRandomValues(buf);
        var hex = '';
        for (var i = 0; i < buf.length; i += 1) {
          hex += ('0' + buf[i].toString(16)).slice(-2);
        }
        return hex.toUpperCase();
      }
    } catch (e) {}
    return String(Date.now()).slice(-6).toUpperCase();
  }

  /** True when the server has assigned SPC|INV/{n}/{fy} (not a client draft). */
  function isConfirmedOutletOrderNo(orderNo) {
    var text = String(orderNo || '').trim();
    return (
      /^SPC\/\d+\/\d{4}-\d{2}$/i.test(text) || /^INV\/\d+\/\d{4}-\d{2}$/i.test(text)
    );
  }

  function formatOrderNoDisplay(orderNo) {
    var text = String(orderNo || '').trim();
    if (!text || !isConfirmedOutletOrderNo(text)) return 'Draft';
    return text;
  }

  function syncOrderNoMeta(page) {
    var orderEl =
      (page && $('#pos-inv-meta-order-no', page)) ||
      document.getElementById('pos-inv-meta-order-no');
    if (orderEl) orderEl.textContent = formatOrderNoDisplay(state.orderNo);
  }

  /** Client draft only — server replaces with the next sequential SPC|INV/{n}/{fy}
   *  on first save. Never mint sequential numbers in the browser (refresh must
   *  not burn or change the official series). */
  function makeOrderNo(d) {
    var outlet = resolvePosOutlet();
    var when = d instanceof Date ? d : new Date();
    var fy = indianFiscalYearLabel(when);
    var suffix = randomOrderSuffix();
    if (outlet === 'restaurant') {
      return 'SPC/' + suffix + '/' + fy;
    }
    if (outlet === 'bar') {
      return 'INV/' + suffix + '/' + fy;
    }
    var api = offlineApi();
    if (api && typeof api.makeLocalOrderNo === 'function') {
      return api.makeLocalOrderNo();
    }
    var yy = String(when.getFullYear()).slice(-2);
    var mm = String(when.getMonth() + 1);
    if (mm.length < 2) mm = '0' + mm;
    return 'ORD-L-' + yy + mm + '-' + suffix;
  }

  function isBrowserOnline() {
    var api = offlineApi();
    if (api && typeof api.isOnline === 'function') return api.isOnline();
    return !(typeof navigator !== 'undefined' && navigator.onLine === false);
  }

  function updateOfflineBanner() {
    var banner = document.getElementById('pos-inv-offline-banner');
    if (!banner) return;
    var offline = !isBrowserOnline();
    banner.hidden = !offline;
    if (offline) {
      banner.textContent = 'Offline — changes sync when you are back online.';
    }
  }

  function mirrorDraft(page, payload) {
    var api = offlineApi();
    if (!api || typeof api.saveDraft !== 'function') return;
    ensureLocalId();
    api.saveDraft(state.localId, {
      invoiceId: state.invoiceId,
      orderNo: state.orderNo,
      payload: payload || collectOrderPayload(page),
      dirty: !!state.dirty
    });
  }

  function queueOfflineSave(page, payload, opts) {
    opts = opts || {};
    var api = offlineApi();
    ensureLocalId();
    payload = Object.assign({}, payload || {});
    payload.clientLocalId = state.localId;
    if (!payload.orderNo) {
      payload.orderNo = state.orderNo || makeOrderNo(new Date());
      state.orderNo = payload.orderNo;
    }
    var epochAtStart = opts.epochAtStart != null ? opts.epochAtStart : dirtyEpoch;
    var silent = !!opts.silent;
    return Promise.resolve()
      .then(function () {
        if (api && typeof api.saveDraft === 'function') {
          return api.saveDraft(state.localId, {
            invoiceId: state.invoiceId,
            orderNo: state.orderNo,
            payload: payload,
            dirty: true
          });
        }
      })
      .then(function () {
        if (api && typeof api.enqueueOutbox === 'function') {
          return api.enqueueOutbox({ localId: state.localId, payload: payload });
        }
      })
      .then(function () {
        clearDirtyAfterPersist(epochAtStart, page);
        if (!silent && opts.toastOnSuccess !== false) {
          toast('Order ' + payload.orderNo + ' saved offline. Will sync when online.');
        } else if (silent) {
          /* keep quiet for autosave */
        }
        syncFloorOccupancyAfterSave(page, payload, null);
        updateSettleBillButton(page);
        return { ok: true, offline: true, invoice: null, payload: payload };
      });
  }

  function flushOfflineOutbox() {
    var api = offlineApi();
    if (!api || typeof api.flushOutbox !== 'function' || !isBrowserOnline()) {
      return Promise.resolve({ flushed: 0 });
    }
    return api.flushOutbox({
      onSynced: function (localId, invoice, payload) {
        if (localId && localId === state.localId && invoice) {
          state.invoiceId = invoice.id;
          state.orderNo = invoice.order_no || (payload && payload.orderNo) || state.orderNo;
          noteOutletOrderSeq(state.orderNo);
          syncOrderNoMeta(document.getElementById('pos-invoice-page'));
          state.tableForOrder =
            invoice.table_label || invoice.table || state.tableForOrder;
          if (
            (payload && payload.customerBill) ||
            (invoice && invoice.customer_bill_sent)
          ) {
            markInvoiceGenerated(document.getElementById('pos-invoice-page'), invoice);
          } else {
            updateSettleBillButton(document.getElementById('pos-invoice-page'));
          }
          syncFloorOccupancyAfterSave(
            document.getElementById('pos-invoice-page'),
            payload,
            invoice
          );
        } else if (payload) {
          syncFloorOccupancyAfterSave(
            document.getElementById('pos-invoice-page'),
            payload,
            invoice
          );
        }
        if (localId && api.saveDraft) {
          api.saveDraft(localId, {
            invoiceId: invoice && invoice.id,
            orderNo: (invoice && invoice.order_no) || (payload && payload.orderNo) || '',
            payload: payload || {},
            dirty: false
          });
        }
      }
    }).then(function (summary) {
      if (summary && summary.authExpired) {
        toast('Session expired; reconnect to sync offline invoices.');
      } else if (summary && summary.flushed > 0) {
        toast(
          summary.flushed === 1
            ? 'Synced 1 offline invoice.'
            : 'Synced ' + summary.flushed + ' offline invoices.'
        );
      } else if (summary && summary.error && summary.flushed === 0) {
        /* Leave draft; user can retry when online. */
      }
      updateSettleBillButton(document.getElementById('pos-invoice-page'));
      return summary;
    });
  }

  function bindOfflineSyncListeners() {
    if (offlineFlushBound) return;
    offlineFlushBound = true;
    global.addEventListener('online', function () {
      updateOfflineBanner();
      flushOfflineOutbox();
      var page = document.getElementById('pos-invoice-page');
      if (page) syncSelectedTableOrderFromServer(page);
    });
    global.addEventListener('offline', function () {
      updateOfflineBanner();
    });
  }

  var tableOrderSyncBound = false;
  function bindTableOrderSyncListeners() {
    if (tableOrderSyncBound) return;
    tableOrderSyncBound = true;
    function pullIfVisible() {
      if (document.visibilityState && document.visibilityState === 'hidden') return;
      var page = document.getElementById('pos-invoice-page');
      if (!page) return;
      syncSelectedTableOrderFromServer(page);
    }
    document.addEventListener('visibilitychange', pullIfVisible);
    global.addEventListener('focus', pullIfVisible);
    global.addEventListener('pageshow', pullIfVisible);
  }

  function queryParam(name) {
    try {
      return new URLSearchParams(global.location.search).get(name) || '';
    } catch (err) {
      return '';
    }
  }

  function resumeStorageKey() {
    return 'hbe_pos_invoice_resume_' + resolvePosOutlet();
  }

  function readStoredResumeContext() {
    var keys = [resumeStorageKey()];
    var i;
    for (i = 0; i < keys.length; i += 1) {
      try {
        var raw = sessionStorage.getItem(keys[i]) || localStorage.getItem(keys[i]);
        if (!raw) continue;
        var parsed = JSON.parse(raw);
        if (!parsed || typeof parsed !== 'object') continue;
        var table = String(parsed.table || '').trim();
        var invoiceId = String(parsed.invoiceId || '').trim();
        if (!table && !invoiceId) continue;
        return { table: table, invoiceId: invoiceId };
      } catch (err) {}
    }
    return null;
  }

  function clearInvoiceResumeContext() {
    var key = resumeStorageKey();
    try {
      sessionStorage.removeItem(key);
    } catch (err) {}
    try {
      localStorage.removeItem(key);
    } catch (err2) {}
    try {
      var url = new URL(global.location.href);
      var path = String(url.pathname || '');
      if (path.indexOf('/invoice') === -1 || path.indexOf('invoice-ledger') !== -1) return;
      var had = url.searchParams.has('table') || url.searchParams.has('invoice');
      url.searchParams.delete('table');
      url.searchParams.delete('invoice');
      if (!had) return;
      var next = url.pathname + (url.searchParams.toString() ? '?' + url.searchParams.toString() : '') + url.hash;
      global.history.replaceState(global.history.state, '', next);
    } catch (err3) {}
  }

  /** Keep ?table= / ?invoice= (and storage) in sync so a browser refresh
   *  reopens the same dine-in bill instead of a blank Create Invoice page. */
  function persistInvoiceResumeContext() {
    var table = String(state.tableForOrder || state.resumeTableValue || '').trim();
    var invoiceId = state.invoiceId ? String(state.invoiceId) : '';
    if (!table && !invoiceId) {
      clearInvoiceResumeContext();
      return;
    }
    var payload = JSON.stringify({
      table: table,
      invoiceId: invoiceId,
      outlet: resolvePosOutlet(),
      at: Date.now()
    });
    var key = resumeStorageKey();
    try {
      sessionStorage.setItem(key, payload);
    } catch (err) {}
    try {
      localStorage.setItem(key, payload);
    } catch (err2) {}
    try {
      var url = new URL(global.location.href);
      var path = String(url.pathname || '');
      if (path.indexOf('/invoice') === -1 || path.indexOf('invoice-ledger') !== -1) return;
      if (table) url.searchParams.set('table', table);
      else url.searchParams.delete('table');
      if (invoiceId) url.searchParams.set('invoice', invoiceId);
      else url.searchParams.delete('invoice');
      var qs = url.searchParams.toString();
      var next = url.pathname + (qs ? '?' + qs : '') + url.hash;
      var cur = global.location.pathname + global.location.search + global.location.hash;
      if (next !== cur) {
        global.history.replaceState(
          Object.assign({}, global.history.state || {}, { deSoftNav: true }),
          '',
          next
        );
      }
    } catch (err3) {}
  }

  function resolveResumePrefs() {
    var prefInvoice = queryParam('invoice').trim();
    var prefTable = queryParam('table').trim();
    if (!prefInvoice && !prefTable) {
      var stored = readStoredResumeContext();
      if (stored) {
        prefInvoice = stored.invoiceId || '';
        prefTable = stored.table || '';
      }
    }
    return { invoiceId: prefInvoice, table: prefTable };
  }

  function restoreResumeOrder(page, prefs) {
    prefs = prefs || resolveResumePrefs();
    var prefInvoice = String((prefs && prefs.invoiceId) || '').trim();
    var prefTable = String((prefs && prefs.table) || '').trim();
    if (prefTable) applyPreferredTable(page, prefTable);

    function resumeTableFallback() {
      if (!prefTable) return;
      applyPreferredTable(page, prefTable);
      resumeOrderForTable(page, prefTable, {
        silent: true,
        notFound: function () {
          applyPreferredTable(page, prefTable);
        }
      });
    }

    if (prefInvoice) {
      resumeOrderById(page, prefInvoice, {
        notFound: resumeTableFallback
      });
      return;
    }
    if (prefTable) resumeTableFallback();
  }

  function emptyFloorTables() {
    return [];
  }

  function loadFloorTablesSync() {
    if (floorTablesCache && floorTablesCache.length) return floorTablesCache;
    clearLegacyFloorCache();
    return emptyFloorTables();
  }

  function clearLegacyFloorCache() {
    try {
      localStorage.removeItem(LEGACY_FLOOR_KEY);
    } catch (err) {
      /* ignore */
    }
  }

  function rememberFloorCatalog(floorData) {
    var api = offlineApi();
    if (!api || !api.loadCatalog || !api.saveCatalog) return;
    api.loadCatalog().then(function (snap) {
      api.saveCatalog({
        floor: floorData,
        menuItems: snap && snap.menuItems,
        menuCategories: snap && snap.menuCategories
      });
    });
  }

  function applyFloorTablesToUi(page, tables) {
    if (!page || !Array.isArray(tables)) return;
    var keep =
      fieldValue('pos-inv-table', page) ||
      String(state.tableForOrder || '').trim() ||
      String(state.resumeTableValue || '').trim();
    /* Prefer in-place badge updates so the chip never flashes back to
       "Select table…" (full rebuild + listbox rebind was clearing it). */
    if (updateFloorTableStatusBadges(page, tables)) {
      if (keep) {
        state.tableForOrder = keep;
        state.resumeTableValue = keep;
        setListboxValue(
          'pos-inv-table',
          keep,
          state.resumeTableLabel && state.resumeTableLabel !== 'Select table…'
            ? state.resumeTableLabel
            : keep
        );
      }
      return;
    }
    populateTables(page, tables, { loading: false, preserveTable: keep });
  }

  /** Update OCCUPIED badges without wiping options or the selected chip. */
  function updateFloorTableStatusBadges(page, tables) {
    var list = $('#pos-inv-table-list', page);
    if (!list || !Array.isArray(tables)) return false;
    var options = list.querySelectorAll('.se-filter-listbox-option[data-value]');
    if (!options.length) return false;

    var byName = {};
    tables.forEach(function (t) {
      var key = String(t.name || '').trim().toLowerCase();
      if (key) byName[key] = mapTableStatus(t.status);
    });

    options.forEach(function (opt) {
      var name = String(opt.getAttribute('data-value') || '').trim();
      var key = name.toLowerCase();
      if (!byName.hasOwnProperty(key)) return;
      var status = byName[key];
      var blocked = tableBlocksNewBill(status);
      var baseLabel = opt.getAttribute('data-label') || name;
      var statusText = blocked ? TABLE_STATUS_LABELS[status] || status : '';
      opt.setAttribute('data-status', status);
      opt.classList.toggle('is-occupied', blocked);
      if (blocked) {
        opt.setAttribute('title', 'Occupied — tap to resume its open order.');
      } else {
        opt.removeAttribute('title');
      }
      var textEl = opt.querySelector('.se-filter-listbox-option-text');
      if (textEl) textEl.textContent = baseLabel;
      var statusEl = opt.querySelector('.se-filter-listbox-option-status');
      if (statusText) {
        if (!statusEl) {
          statusEl = document.createElement('span');
          statusEl.className = 'se-filter-listbox-option-status';
          opt.appendChild(statusEl);
        }
        statusEl.textContent = statusText;
      } else if (statusEl) {
        statusEl.remove();
      }
    });
    return true;
  }

  /** Instantly flip a table to occupied in the in-memory picker (optimistic). */
  function markFloorTableOccupiedLocal(tableName) {
    var needle = String(tableName || '').trim().toLowerCase();
    if (!needle || !Array.isArray(floorTablesCache)) return false;
    var changed = false;
    for (var i = 0; i < floorTablesCache.length; i++) {
      var name = String(floorTablesCache[i].name || '').trim().toLowerCase();
      if (name === needle) {
        var cur = mapTableStatus(floorTablesCache[i].status);
        if (cur !== 'occupied') {
          floorTablesCache[i].status = 'occupied';
          changed = true;
        }
        break;
      }
    }
    return changed;
  }

  function markFloorTableAvailableLocal(tableName) {
    var needle = String(tableName || '').trim().toLowerCase();
    if (!needle || !Array.isArray(floorTablesCache)) return false;
    var changed = false;
    for (var i = 0; i < floorTablesCache.length; i++) {
      var name = String(floorTablesCache[i].name || '').trim().toLowerCase();
      if (name === needle) {
        if (mapTableStatus(floorTablesCache[i].status) !== 'available') {
          floorTablesCache[i].status = 'available';
          changed = true;
        }
        break;
      }
    }
    return changed;
  }

  /**
   * Force-refresh floor from network (bypass SW/HTTP/memory cache) and update the
   * table picker immediately. Used after save/settle so OCCUPIED badges stay live.
   */
  function refreshFloorTables(page, opts) {
    opts = opts || {};
    var preserve =
      opts.preserveTable ||
      (page && fieldValue('pos-inv-table', page)) ||
      String(state.tableForOrder || '').trim() ||
      String(state.resumeTableValue || '').trim();
    var url = FLOOR_API + (FLOOR_API.indexOf('?') === -1 ? '?' : '&') + '_ts=' + Date.now();
    return fetch(url, {
      credentials: 'same-origin',
      cache: 'no-store',
      headers: {
        Accept: 'application/json',
        'Cache-Control': 'no-cache',
        Pragma: 'no-cache'
      }
    })
      .then(function (res) {
        return res.json().then(function (data) {
          return { ok: res.ok && data && data.ok, data: data };
        });
      })
      .then(function (result) {
        if (!result.ok || !Array.isArray(result.data.tables)) {
          throw new Error('floor refresh failed');
        }
        floorTablesCache = result.data.tables;
        floorTablesLoaded = true;
        rememberFloorCatalog(result.data);
        if (page) {
          applyFloorTablesToUi(page, floorTablesCache);
          if (preserve) {
            state.tableForOrder = preserve;
            state.resumeTableValue = preserve;
            var match = floorTablesCache.find(function (t) {
              return tableNameMatches(t.name || '', preserve);
            });
            var label = match
              ? String(match.name || preserve) +
                (match.seats != null ? ' (' + match.seats + ' Seats)' : '')
              : preserve;
            state.resumeTableLabel = label;
            setListboxValue('pos-inv-table', match ? match.name : preserve, label);
          }
        }
        if (typeof opts.done === 'function') opts.done(floorTablesCache);
        return floorTablesCache;
      })
      .catch(function () {
        if (typeof opts.done === 'function') opts.done(floorTablesCache || []);
        return floorTablesCache || [];
      });
  }

  function syncFloorOccupancyAfterSave(page, payload, invoice) {
    var orderType =
      (payload && payload.orderType) ||
      (invoice && (invoice.order_type || invoice.orderType)) ||
      '';
    var table =
      (invoice && (invoice.table_label || invoice.table)) ||
      (payload && payload.table) ||
      state.tableForOrder ||
      state.resumeTableValue ||
      (page && fieldValue('pos-inv-table', page)) ||
      '';
    table = String(table || '').trim();
    if (String(orderType).toLowerCase() !== 'dine_in' || !table) {
      return;
    }
    state.tableForOrder = table;
    state.resumeTableValue = table;
    var billGenerated =
      !!(payload && (payload.customerBill || payload.customer_bill)) ||
      !!(invoice && (invoice.customer_bill_sent || invoice.customerBillSent)) ||
      !!state.invoiceGenerated;
    if (billGenerated) {
      markFloorTableAvailableLocal(table);
    } else {
      markFloorTableOccupiedLocal(table);
    }
    if (page && floorTablesCache) {
      applyFloorTablesToUi(page, floorTablesCache);
      setListboxValue(
        'pos-inv-table',
        table,
        state.resumeTableLabel && state.resumeTableLabel !== 'Select table…'
          ? state.resumeTableLabel
          : table
      );
    }
    refreshFloorTables(page, { preserveTable: table });
  }

  function loadFloorTables(done) {
    if (floorTablesLoaded && Array.isArray(floorTablesCache) && floorTablesCache.length) {
      if (typeof done === 'function') done(floorTablesCache);
      /* Stale-while-revalidate: refresh and update the open picker when status changes. */
      refreshFloorTables(document.getElementById('pos-invoice-page'), {
        done: function (tables) {
          if (typeof done === 'function') done(tables);
        }
      });
      return;
    }
    fetch(FLOOR_API + (FLOOR_API.indexOf('?') === -1 ? '?' : '&') + '_ts=' + Date.now(), {
      credentials: 'same-origin',
      cache: 'no-store',
      headers: {
        Accept: 'application/json',
        'Cache-Control': 'no-cache',
        Pragma: 'no-cache'
      }
    })
      .then(function (res) {
        return res.json().then(function (data) {
          return { ok: res.ok && data && data.ok, data: data };
        });
      })
      .then(function (result) {
        if (result.ok && Array.isArray(result.data.tables)) {
          floorTablesCache = result.data.tables;
          rememberFloorCatalog(result.data);
        } else {
          throw new Error('floor fetch failed');
        }
        floorTablesLoaded = true;
        if (typeof done === 'function') done(floorTablesCache);
      })
      .catch(function () {
        var api = offlineApi();
        if (!api || !api.loadCatalog) {
          floorTablesCache = emptyFloorTables();
          floorTablesLoaded = true;
          if (typeof done === 'function') done(floorTablesCache);
          return;
        }
        api.loadCatalog().then(function (snap) {
          if (snap && snap.floor && Array.isArray(snap.floor.tables)) {
            floorTablesCache = snap.floor.tables;
          } else {
            floorTablesCache = emptyFloorTables();
          }
          floorTablesLoaded = true;
          if (typeof done === 'function') done(floorTablesCache);
        });
      });
  }

  function toast(msg) {
    var el = $('#pos-inv-toast');
    if (!el) return;
    el.hidden = false;
    el.textContent = msg;
    el.classList.add('is-visible');
    clearTimeout(toast._t);
    toast._t = setTimeout(function () {
      el.classList.remove('is-visible');
      setTimeout(function () {
        el.hidden = true;
      }, 200);
    }, 2200);
  }

  function menuCatalogUrl(path) {
    var url = path || MENU_ITEMS_API;
    var outlet = resolvePosOutlet();
    var include = outlet === 'bar' ? 'restaurant' : 'bar';
    url += (url.indexOf('?') === -1 ? '?' : '&') + 'include_outlets=' + include;
    return url;
  }

  function normalizeMenuItem(raw, categoryName) {
    var category = categoryName || '';
    var kind = String((raw && raw.item_kind) || 'food')
      .trim()
      .toLowerCase();
    var menuType = String((raw && raw.menu_type) || '')
      .trim()
      .toLowerCase();
    if (kind === 'liquour' || kind === 'alcohol' || kind === 'bar') kind = 'liquor';
    if (menuType === 'liquour' || menuType === 'alcohol') menuType = 'liquor';
    var liquor = kind === 'liquor' || menuType === 'liquor' || isLiquorCategory(category);
    var outlet = String((raw && raw.outlet) || 'restaurant')
      .trim()
      .toLowerCase();
    if (outlet !== 'bar') outlet = 'restaurant';
    return {
      id: String(raw.id),
      name: raw.name || '',
      code: raw.code || '',
      barcode: raw.barcode || '',
      category: category,
      variant: raw.variant || '',
      rate: Number(raw.rate) || 0,
      menuType: menuType,
      itemKind: liquor ? 'liquor' : 'food',
      isLiquor: liquor,
      outlet: outlet,
      emoji: liquor || outlet === 'bar' ? '🍸' : '🍽️'
    };
  }

  function isLiquorCategory(name) {
    return LIQUOR_CATEGORY_RE.test(String(name || '').trim());
  }

  function isLiquorLine(line) {
    if (!line) return false;
    if (line.isLiquor === true || line.itemKind === 'liquor') return true;
    if (line.isLiquor === false && line.itemKind === 'food') return false;
    if (line.menuId) {
      var menu = findMenuItem(line.menuId);
      if (menu) {
        if (menu.isLiquor || menu.itemKind === 'liquor') return true;
        if (menu.itemKind === 'food') return false;
      }
    }
    var cat = line.category || '';
    if (!cat) cat = line.variant || '';
    return isLiquorCategory(cat);
  }

  function buildMenuCatalog(rawItems, categories) {
    var byCategory = {};
    (categories || []).forEach(function (cat) {
      if (!cat || cat.id == null) return;
      byCategory[String(cat.id)] = cat.name || '';
    });
    menuCatalog.length = 0;
    menuCatalogById = {};
    (rawItems || []).forEach(function (raw) {
      if (!raw || raw.is_active === false) return;
      var item = normalizeMenuItem(raw, byCategory[String(raw.category_id)] || '');
      menuCatalog.push(item);
      menuCatalogById[item.id] = item;
    });
    menuCatalogStatus = menuCatalog.length ? 'ready' : 'empty';
  }

  function findMenuItem(menuId) {
    return menuCatalogById[String(menuId || '')] || null;
  }

  function loadMenuCatalog(done) {
    if (menuCatalogStatus === 'ready' && menuCatalog.length) {
      if (typeof done === 'function') done(true);
      return;
    }
    if (menuCatalogInflight) {
      menuCatalogInflight.then(function (ok) {
        if (typeof done === 'function') done(ok);
      });
      return;
    }
    menuCatalogStatus = 'loading';
    var itemsPayload = null;
    var categoriesPayload = null;
    var failed = false;

    function applyCachedMenu() {
      var api = offlineApi();
      if (!api || !api.loadCatalog) return Promise.resolve(false);
      return api.loadCatalog().then(function (snap) {
        if (
          snap &&
          Array.isArray(snap.menuItems) &&
          snap.menuItems.length &&
          Array.isArray(snap.menuCategories)
        ) {
          buildMenuCatalog(snap.menuItems, snap.menuCategories);
          return menuCatalogStatus === 'ready';
        }
        return false;
      });
    }

    menuCatalogInflight = fetch(menuCatalogUrl(MENU_ITEMS_API), {
      credentials: 'same-origin',
      headers: { Accept: 'application/json' }
    })
      .then(function (res) {
        return res.json().then(function (data) {
          return { ok: res.ok && data && data.ok, data: data };
        });
      })
      .then(function (result) {
        if (!result.ok || !Array.isArray(result.data.items)) {
          failed = true;
          return null;
        }
        itemsPayload = result.data.items;
        return fetch(menuCatalogUrl(MENU_CATEGORIES_API), {
          credentials: 'same-origin',
          headers: { Accept: 'application/json' }
        });
      })
      .then(function (res) {
        if (failed) return null;
        if (!res) return null;
        return res.json().then(function (data) {
          return { ok: res.ok && data && data.ok, data: data };
        });
      })
      .then(function (result) {
        if (failed) return applyCachedMenu();
        if (!result || !result.ok || !Array.isArray(result.data.categories)) {
          return applyCachedMenu();
        }
        categoriesPayload = result.data.categories;
        buildMenuCatalog(itemsPayload, categoriesPayload);
        var api = offlineApi();
        if (api && api.loadCatalog && api.saveCatalog) {
          api.loadCatalog().then(function (snap) {
            api.saveCatalog({
              floor: snap && snap.floor,
              menuItems: itemsPayload,
              menuCategories: categoriesPayload
            });
          });
        }
        return menuCatalogStatus === 'ready' || menuCatalogStatus === 'empty';
      })
      .catch(function () {
        return applyCachedMenu();
      })
      .then(function (ok) {
        if (!ok) {
          menuCatalog.length = 0;
          menuCatalogById = {};
          menuCatalogStatus = 'error';
        }
        menuCatalogInflight = null;
        if (typeof done === 'function') done(!!ok);
        return !!ok;
      });
  }

  function suggestEmptyMessage(query) {
    if (menuCatalogStatus === 'loading' || menuCatalogStatus === 'idle') return 'Loading menu…';
    if (menuCatalogStatus === 'error') {
      return 'Could not load menu. Refresh or try again later.';
    }
    if (menuCatalogStatus === 'empty' || !menuCatalog.length) {
      return 'No menu items configured. Add items under Restaurant → Menu.';
    }
    return 'No menu items match your search.';
  }

  function searchMenu(q) {
    var query = String(q || '').trim().toLowerCase();
    if (query.length < MIN_QUERY) return [];
    if (menuCatalogStatus === 'loading' || menuCatalogStatus === 'idle' || menuCatalogStatus === 'error' || !menuCatalog.length) {
      return [];
    }
    return menuCatalog.filter(function (item) {
      return (
        item.name.toLowerCase().indexOf(query) !== -1 ||
        item.code.toLowerCase().indexOf(query) !== -1 ||
        String(item.barcode).indexOf(query) !== -1 ||
        item.category.toLowerCase().indexOf(query) !== -1 ||
        (item.variant && item.variant.toLowerCase().indexOf(query) !== -1)
      );
    }).slice(0, 8);
  }

  function customerQueryKey(q) {
    var digits = digitsOnly(q, 10);
    if (digits.length >= MIN_QUERY) return digits;
    return String(q || '').trim().toLowerCase();
  }

  function searchCustomersLocal(q) {
    var key = customerQueryKey(q);
    if (key.length < MIN_QUERY) return [];
    if (customerCacheQuery === key) return customerCache.slice();
    var digits = digitsOnly(q, 10);
    if (digits.length >= MIN_QUERY) {
      return customerCache
        .filter(function (c) {
          return String(c.mobile || '').indexOf(digits) === 0;
        })
        .slice(0, 8);
    }
    return customerCache
      .filter(function (c) {
        return String(c.name || '')
          .toLowerCase()
          .indexOf(key) !== -1;
      })
      .slice(0, 8);
  }

  function fetchCustomers(q, done) {
    var key = customerQueryKey(q);
    if (key.length < MIN_QUERY) {
      customerCache = [];
      customerCacheQuery = '';
      if (done) done([]);
      return;
    }
    fetch(CUSTOMERS_API + '?q=' + encodeURIComponent(String(q || '').trim()), {
      credentials: 'same-origin',
      headers: { Accept: 'application/json' }
    })
      .then(function (res) {
        if (!res.ok) throw new Error('customer search failed');
        return res.json();
      })
      .then(function (payload) {
        var list = (payload && payload.customers) || [];
        customerCache = Array.isArray(list) ? list : [];
        customerCacheQuery = key;
        if (done) done(customerCache.slice());
      })
      .catch(function () {
        customerCache = [];
        customerCacheQuery = '';
        if (done) done([]);
      });
  }

  /* Back-compat aliases used by older call sites / parallel edits. */
  function searchCustomersByMobile(q) {
    return searchCustomersLocal(q);
  }
  function fetchCustomersByMobile(q, done) {
    return fetchCustomers(q, done);
  }

  function digitsOnly(str, maxLen) {
    var d = String(str || '').replace(/\D/g, '');
    if (maxLen) d = d.slice(0, maxLen);
    return d;
  }

  function normalizeDiscountLineUids(uids) {
    var out = [];
    (uids || []).forEach(function (uid) {
      var key = String(uid || '').trim();
      if (key && out.indexOf(key) === -1) out.push(key);
    });
    return out;
  }

  function pruneDiscountLineUids() {
    var live = {};
    state.lines.forEach(function (line) {
      live[String(line.uid || '')] = true;
    });
    state.discountLineUids = normalizeDiscountLineUids(state.discountLineUids).filter(function (uid) {
      return !!live[uid];
    });
    /* All lines selected ≡ whole-bill scope. */
    if (state.discountLineUids.length && state.discountLineUids.length >= state.lines.length) {
      state.discountLineUids = [];
    }
  }

  function discountBaseForLines(lineUids) {
    var scoped = normalizeDiscountLineUids(lineUids);
    var base = 0;
    state.lines.forEach(function (line) {
      var lineTotal = (Number(line.rate) || 0) * (Number(line.qty) || 0);
      if (!scoped.length || scoped.indexOf(String(line.uid || '')) !== -1) {
        base += lineTotal;
      }
    });
    return base;
  }

  function calcAdjAmount(base, type, value) {
    var n = Number(value);
    if (isNaN(n) || n < 0) n = 0;
    if (type === 'inr') return Math.min(Math.max(0, base), n);
    if (n > 100) n = 100;
    return Math.max(0, base) * (n / 100);
  }

  function calcTotals(override) {
    var o = override || {};
    var discountType = o.discountType != null ? o.discountType : state.discountType;
    var discountValue = o.discountValue != null ? o.discountValue : state.discountValue;
    var serviceType = o.serviceType != null ? o.serviceType : state.serviceType;
    var serviceValue = o.serviceValue != null ? o.serviceValue : state.serviceValue;
    var tipAmount = o.tipAmount != null ? o.tipAmount : state.tipAmount;
    var discountLineUids =
      o.discountLineUids != null ? o.discountLineUids : state.discountLineUids;

    var subtotal = 0;
    var barAlcoholSubtotal = 0;
    state.lines.forEach(function (line) {
      var lineTotal = (Number(line.rate) || 0) * (Number(line.qty) || 0);
      subtotal += lineTotal;
      /* VAT applies only to Bar Alcohol — bar-outlet liquor lines. */
      if (lineMenuOutlet(line) === 'bar' && isLiquorLine(line)) {
        barAlcoholSubtotal += lineTotal;
      }
    });
    var scopedUids = normalizeDiscountLineUids(discountLineUids);
    var discountBase = scopedUids.length ? discountBaseForLines(scopedUids) : subtotal;
    var discount = calcAdjAmount(discountBase, discountType, discountValue);
    if (discount > subtotal) discount = subtotal;
    var afterDiscount = Math.max(0, subtotal - discount);
    var barShare = subtotal > 0 ? barAlcoholSubtotal / subtotal : 0;
    var barAfter = afterDiscount * barShare;
    var foodAfter = Math.max(0, afterDiscount - barAfter);
    var cgst = foodAfter * CGST_RATE;
    var ugst = foodAfter * UGST_RATE;
    var gst = cgst + ugst;
    var vat = barAfter * VAT_RATE;
    var service = calcAdjAmount(afterDiscount, serviceType, serviceValue);
    var tip = Number(tipAmount) || 0;
    if (tip < 0) tip = 0;
    var beforeRound = afterDiscount + gst + vat + service + tip;
    var rounded = Math.round(beforeRound);
    var roundOff = Math.round((rounded - beforeRound) * 100) / 100;
    return {
      subtotal: subtotal,
      discount: discount,
      discountType: discountType,
      discountValue: Number(discountValue) || 0,
      discountLineUids: scopedUids,
      discountItemCount: scopedUids.length,
      liquorSubtotal: barAlcoholSubtotal,
      barSubtotal: barAlcoholSubtotal,
      cgst: cgst,
      ugst: ugst,
      gst: gst,
      vat: vat,
      service: service,
      serviceType: serviceType,
      serviceValue: Number(serviceValue) || 0,
      tip: tip,
      roundOff: roundOff,
      total: rounded
    };
  }

  function formatAdjHint(type, value, itemCount) {
    var n = Number(value);
    if (isNaN(n) || n <= 0) return '';
    var base = type === 'inr' ? '(₹' + n.toFixed(n % 1 ? 2 : 0) + ')' : '(' + n + '%)';
    var count = Number(itemCount) || 0;
    if (count > 0) return base + ' · ' + count + (count === 1 ? ' item' : ' items');
    return base;
  }

  function formatTaxRateLabel(rate) {
    var pct = Number(rate) * 100;
    if (!isFinite(pct) || pct < 0) pct = 0;
    pct = Math.round(pct * 1000) / 1000;
    var text = String(pct);
    if (text.indexOf('.') !== -1) {
      text = text.replace(/\.?0+$/, '');
    }
    return '(' + text + '%)';
  }

  function renderSummary(page) {
    var t = calcTotals();
    var map = {
      'pos-inv-sum-subtotal': t.subtotal,
      'pos-inv-sum-discount': t.discount,
      'pos-inv-sum-cgst': t.cgst,
      'pos-inv-sum-ugst': t.ugst,
      'pos-inv-sum-vat': t.vat,
      'pos-inv-sum-service': t.service,
      'pos-inv-sum-tip': t.tip,
      'pos-inv-sum-round': t.roundOff,
      'pos-inv-sum-total': t.total
    };
    Object.keys(map).forEach(function (id) {
      var el = $('#' + id, page);
      if (el) el.textContent = money(map[id]);
    });
    var cgstRateEl = $('#pos-inv-sum-cgst-rate', page);
    if (cgstRateEl) cgstRateEl.textContent = formatTaxRateLabel(CGST_RATE);
    var ugstRateEl = $('#pos-inv-sum-ugst-rate', page);
    if (ugstRateEl) ugstRateEl.textContent = formatTaxRateLabel(UGST_RATE);
    var vatRateEl = $('#pos-inv-sum-vat-rate', page);
    if (vatRateEl) vatRateEl.textContent = formatTaxRateLabel(VAT_RATE);
    var discHint = $('#pos-inv-sum-discount-hint', page);
    if (discHint) {
      discHint.textContent = formatAdjHint(t.discountType, t.discountValue, t.discountItemCount);
    }
    var discRow = $('#pos-inv-sum-discount-row', page);
    if (discRow) {
      var showDiscount = Number(t.discount) > 0 || Number(t.discountValue) > 0;
      discRow.hidden = !showDiscount;
    }
    var vatRow = $('#pos-inv-sum-vat-row', page);
    if (vatRow) vatRow.hidden = !(Number(t.vat) > 0);
    var svcHint = $('#pos-inv-sum-service-hint', page);
    if (svcHint) svcHint.textContent = formatAdjHint(t.serviceType, t.serviceValue) || '';
    var svcRow = $('#pos-inv-sum-service-row', page);
    if (svcRow) {
      var showService = Number(t.service) > 0 || Number(t.serviceValue) > 0;
      svcRow.hidden = !showService;
    }
    var tipRow = $('#pos-inv-sum-tip-row', page);
    if (tipRow) tipRow.hidden = !(Number(t.tip) > 0);
  }

  function canEditKitchenSentLines(page) {
    var root = page || document.getElementById('pos-invoice-page');
    return !!(root && root.getAttribute('data-pos-is-admin') === '1');
  }

  function lineKitchenSentQty(line) {
    return Math.max(0, Number(line && line.sentQty) || 0);
  }

  function lineHasKitchenSent(line) {
    return lineKitchenSentQty(line) > 0;
  }

  function renderLines(page) {
    var body = $('#pos-inv-lines-body', page);
    var empty = $('#pos-inv-empty', page);
    if (!body) return;

    if (!state.lines.length) {
      body.innerHTML = '';
      if (empty) empty.hidden = false;
      renderSummary(page);
      updateKotBar(page);
      updateSettleBillButton(page);
      return;
    }

    if (empty) empty.hidden = true;
    var isAdmin = canEditKitchenSentLines(page);
    var locked = !!state.invoiceGenerated;
    var selecting = !!state.discountSelectMode;
    var draftSet = {};
    (state.discountSelectDraft || []).forEach(function (uid) {
      draftSet[String(uid)] = true;
    });

    body.innerHTML = state.lines
      .map(function (line) {
        var amt = (Number(line.rate) || 0) * (Number(line.qty) || 0);
        var pendingQty = pendingKotQty(line);
        var sentQty = lineKitchenSentQty(line);
        var lockReduce = locked || (!isAdmin && sentQty > 0);
        var canDecrease = !locked && (!lockReduce || Number(line.qty) > sentQty);
        var canDelete = !locked && !(!isAdmin && sentQty > 0);
        var lineNotes = String(line.notes || '').trim();
        var checked = !!draftSet[String(line.uid)];
        return (
          '<tr data-line-id="' +
          escapeHtml(line.uid) +
          (checked ? '" class="is-discount-checked"' : '"') +
          '>' +
          (selecting
            ? '<td class="pos-inv-col-select">' +
              '<input type="checkbox" class="pos-inv-line-check" data-discount-check aria-label="Select ' +
              escapeHtml(line.name) +
              ' for discount"' +
              (checked ? ' checked' : '') +
              '>' +
              '</td>'
            : '') +
          '<td><div class="pos-inv-item-cell">' +
          '<div><div class="pos-inv-item-name">' +
          escapeHtml(line.name) +
          '</div>' +
          (line.variant
            ? '<div class="pos-inv-item-variant">' + escapeHtml(line.variant) + '</div>'
            : '') +
          (lineNotes
            ? '<div class="pos-inv-item-note" title="' +
              escapeHtml(lineNotes) +
              '">' +
              escapeHtml(lineNotes) +
              '</div>'
            : '') +
          (pendingQty > 0
            ? '<span class="pos-inv-item-kot-tag" title="Not yet sent to kitchen">' +
              (pendingQty === Number(line.qty) ? 'New' : '+' + pendingQty + ' new') +
              '</span>'
            : sentQty > 0
              ? '<span class="pos-inv-item-kot-tag is-sent" title="Sent to kitchen">Sent</span>'
              : '') +
          '</div></div></td>' +
          '<td class="pos-inv-col-qty"><div class="pos-inv-qty">' +
          '<button type="button" data-qty="-1" aria-label="Decrease quantity"' +
          (canDecrease && !selecting ? '' : ' disabled title="' + (selecting ? 'Finish item selection first' : locked ? 'Invoice locked — settle to continue' : 'Only an administrator can reduce quantity after KOT') + '"') +
          '>−</button>' +
          '<span>' +
          line.qty +
          '</span>' +
          '<button type="button" data-qty="1" aria-label="Increase quantity"' +
          (locked || selecting ? ' disabled title="' + (selecting ? 'Finish item selection first' : 'Invoice locked — settle to continue') + '"' : '') +
          '>+</button>' +
          '</div></td>' +
          '<td class="pos-inv-col-rate"><span class="pos-inv-rate">' +
          money(line.rate) +
          '</span></td>' +
          '<td class="pos-inv-col-amt"><span class="pos-inv-amt">' +
          money(amt) +
          '</span></td>' +
          '<td class="pos-inv-col-act"><div class="pos-inv-act-btns">' +
          '<button type="button" class="pos-inv-note-btn' +
          (lineNotes ? ' is-active' : '') +
          '" data-line-note aria-label="Customise item"' +
          (locked || selecting ? ' disabled title="' + (locked ? 'Invoice locked — settle to continue' : 'Finish item selection first') + '"' : '') +
          (lineNotes ? ' title="' + escapeHtml(lineNotes) + '"' : locked || selecting ? '' : ' title="Add customised note"') +
          '>' +
          '<svg viewBox="0 0 24 24"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>' +
          '</button>' +
          '<button type="button" class="pos-inv-del" data-del aria-label="Remove item"' +
          (canDelete && !selecting ? '' : ' disabled title="' + (selecting ? 'Finish item selection first' : locked ? 'Invoice locked — settle to continue' : 'Only an administrator can remove items after KOT') + '"') +
          '>' +
          '<svg viewBox="0 0 24 24"><path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6M14 11v6"/></svg>' +
          '</button></div></td></tr>'
        );
      })
      .join('');

    syncDiscountSelectUi(page);
    renderSummary(page);
    updateKotBar(page);
    updateSettleBillButton(page);
  }

  function updateKotBar(page) {
    var btn = $('#pos-inv-send-kot', page);
    var status = $('#pos-inv-kot-status', page);
    var countEl = $('#pos-inv-send-kot-count', page);
    if (!btn) return;
    var pending = pendingKotLines();
    var pendingItems = pending.length;
    /* Appear only when there are items yet to send — same idea as Tables KOT banner. */
    btn.hidden = pendingItems === 0;
    btn.disabled = pendingItems === 0;
    btn.classList.toggle('is-pending', pendingItems > 0);
    if (countEl) {
      countEl.hidden = pendingItems === 0;
      countEl.textContent = String(pendingItems);
    }
    if (status) {
      status.classList.toggle('is-pending', pendingItems > 0);
      if (!state.lines.length) {
        status.textContent = 'Add items to send a KOT.';
      } else if (pendingItems > 0) {
        status.textContent =
          pendingItems + (pendingItems === 1 ? ' item' : ' items') + ' not yet sent to the kitchen.';
      } else {
        status.textContent = 'All items sent to the kitchen.';
      }
    }
  }

  function buildKotTicketHtml(page, pending, opts) {
    opts = opts || {};
    var now = new Date();
    var table = fieldValue('pos-inv-table', page) || '—';
    var orderTypeValue =
      fieldValue('pos-inv-order-type-header', page) || fieldValue('pos-inv-order-type', page) || 'dine_in';
    var orderType = ORDER_TYPE_LABELS[orderTypeValue] || orderTypeValue;
    var isBar = opts.menuOutlet === 'bar';
    var heading = isBar ? 'BAR ORDER TOKEN' : 'KITCHEN ORDER TOKEN';
    var foot = isBar ? '-- Confirmed for bar --' : '-- Confirmed for kitchen --';
    var rows = pending
      .map(function (entry) {
        var line = entry.line;
        var note = String(line.notes || '').trim();
        return (
          '<tr><td class="qty">' +
          entry.qty +
          '</td><td class="name">' +
          escapeHtml(line.name) +
          (line.variant ? '<div class="variant">' + escapeHtml(line.variant) + '</div>' : '') +
          (note ? '<div class="note">' + escapeHtml(note) + '</div>' : '') +
          '</td></tr>'
        );
      })
      .join('');
    return (
      '<!DOCTYPE html><html><head><meta charset="utf-8"><title>KOT ' +
      escapeHtml(state.orderNo || '') +
      '</title><style>' +
      'body{font-family:"Courier New",monospace;padding:16px;color:#111;width:300px;margin:0 auto}' +
      'h1{font-size:16px;margin:0 0 4px;text-align:center;letter-spacing:.04em}' +
      '.meta{font-size:12px;margin-bottom:10px;border-bottom:1px dashed #333;padding-bottom:8px}' +
      '.meta div{display:flex;justify-content:space-between;margin:2px 0}' +
      'table{width:100%;border-collapse:collapse;font-size:13px}' +
      'td{padding:4px 0;border-bottom:1px dashed #ddd;vertical-align:top}' +
      'td.qty{width:34px;font-weight:700}' +
      '.variant{font-size:11px;color:#555}' +
      '.note{font-size:11px;color:#111;font-style:italic;margin-top:2px}' +
      '.foot{margin-top:12px;text-align:center;font-size:11px;color:#555}' +
      '</style></head><body>' +
      '<h1>' +
      heading +
      '</h1>' +
      '<div class="meta">' +
      '<div><span>Order</span><span>' +
      escapeHtml(state.orderNo || '—') +
      '</span></div>' +
      '<div><span>Table</span><span>' +
      escapeHtml(table) +
      '</span></div>' +
      '<div><span>Type</span><span>' +
      escapeHtml(orderType) +
      '</span></div>' +
      '<div><span>Time</span><span>' +
      formatDate(now) +
      ' ' +
      formatTime(now) +
      '</span></div>' +
      '</div>' +
      '<table><tbody>' +
      rows +
      '</tbody></table>' +
      '<div class="foot">' +
      foot +
      '</div>' +
      '</body></html>'
    );
  }

  /** Plain-text KOT for Hotel Print Agent thermal printers (no HTML/CSS). */
  function buildKotTicketText(page, pending, opts) {
    opts = opts || {};
    var now = new Date();
    var table = fieldValue('pos-inv-table', page) || '—';
    var orderTypeValue =
      fieldValue('pos-inv-order-type-header', page) || fieldValue('pos-inv-order-type', page) || 'dine_in';
    var orderType = ORDER_TYPE_LABELS[orderTypeValue] || orderTypeValue;
    var isBar = opts.menuOutlet === 'bar';
    var heading = isBar ? 'BAR ORDER TOKEN' : 'KITCHEN ORDER TOKEN';
    var foot = isBar ? '-- Confirmed for bar --' : '-- Confirmed for kitchen --';
    var lines = [
      heading,
      '--------------------------------',
      'Order: ' + (state.orderNo || '—'),
      'Table: ' + table,
      'Type:  ' + orderType,
      'Time:  ' + formatDate(now) + ' ' + formatTime(now),
      '--------------------------------'
    ];
    (pending || []).forEach(function (entry) {
      var line = entry.line || {};
      var note = String(line.notes || '').trim();
      lines.push(String(entry.qty || 0) + ' x ' + String(line.name || ''));
      if (line.variant) lines.push('    ' + String(line.variant));
      if (note) lines.push('    Note: ' + note);
    });
    lines.push('--------------------------------');
    lines.push(foot);
    lines.push('');
    return lines.join('\n');
  }

  function printKotTicketBrowser(html) {
    // #region agent log
    (function (payload) {
      var body = JSON.stringify(payload);
      fetch('http://127.0.0.1:7764/ingest/3c15e9d7-8289-4a1b-877f-c72ceeda0753',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'42fa9a'},body:body}).catch(function(){});
      fetch('/api/hbe-agent-debug',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-Requested-With':'XMLHttpRequest'},body:body}).catch(function(){});
    })({sessionId:'42fa9a',hypothesisId:'A_C',location:'pos_invoice.js:printKotTicketBrowser',message:'browser KOT print invoked',data:{htmlLen:(html&&html.length)||0,hasBody:!!(html&&html.indexOf('<body>')>=0),titleMatch:!!(html&&/title>KOT/.test(html))},timestamp:Date.now()});
    // #endregion
    var win = global.open('', '_blank', 'width=380,height=600');
    if (!win) return;
    win.document.write(html);
    win.document.close();
    win.focus();
    setTimeout(function () {
      try {
        win.print();
      } catch (err) {
        /* Best-effort print; ignore if the browser blocks it. */
      }
    }, 250);
  }

  function lineMenuOutlet(line) {
    if (!line) return 'restaurant';
    var raw = String(line.outlet || '').trim().toLowerCase();
    if (raw === 'bar') return 'bar';
    if (raw === 'restaurant') return 'restaurant';
    var menu = findMenuItem(line.menuId || line.menu_item_id);
    if (menu && String(menu.outlet || '').toLowerCase() === 'bar') return 'bar';
    return 'restaurant';
  }

  function printKotTicket(page, pending) {
    try {
      if (!pending || !pending.length) return;
      var restaurantPending = [];
      var barPending = [];
      pending.forEach(function (entry) {
        if (lineMenuOutlet(entry.line) === 'bar') barPending.push(entry);
        else restaurantPending.push(entry);
      });

      var groups = [];
      if (restaurantPending.length) {
        groups.push({ menuOutlet: 'restaurant', entries: restaurantPending });
      }
      if (barPending.length) {
        groups.push({ menuOutlet: 'bar', entries: barPending });
      }

      var canAgent =
        global.hbePosPrinterPrefs &&
        typeof global.hbePosPrinterPrefs.printKotHtml === 'function';
      var hasHotelAgent =
        typeof global.HotelPrintAgent === 'object' &&
        typeof global.HotelPrintAgent.print === 'function';
      var baseId = String(state.invoiceId || state.orderNo || Date.now());

      // #region agent log
      (function (payload) {
        var body = JSON.stringify(payload);
        fetch('http://127.0.0.1:7764/ingest/3c15e9d7-8289-4a1b-877f-c72ceeda0753',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'42fa9a'},body:body}).catch(function(){});
        fetch('/api/hbe-agent-debug',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-Requested-With':'XMLHttpRequest'},body:body}).catch(function(){});
      })({sessionId:'42fa9a',runId:'pre-fix',hypothesisId:'A_D',location:'pos_invoice.js:printKotTicket',message:'printKotTicket entry',data:{canAgent:!!canAgent,hasHotelAgent:!!hasHotelAgent,groupCount:groups.length,pendingCount:pending.length,scriptHint:(document.querySelector('script[src*="pos_invoice.js"]')||{}).src||'',printersHint:(document.querySelector('script[src*="pos_printers.js"]')||{}).src||''},timestamp:Date.now()});
      // #endregion

      if (!canAgent) {
        toast(
          'Hotel Print Agent is required for silent KOT printing. Install and open it on this PC.'
        );
        return;
      }

      groups.forEach(function (group, idx) {
        var html = buildKotTicketHtml(page, group.entries, {
          menuOutlet: group.menuOutlet
        });
        var text = buildKotTicketText(page, group.entries, {
          menuOutlet: group.menuOutlet
        });
        var jobId = 'kot-' + group.menuOutlet + '-' + baseId + '-' + Date.now() + '-' + idx;
        global.hbePosPrinterPrefs
          .printKotHtml(html, {
            menuOutlet: group.menuOutlet,
            jobId: jobId,
            text: text,
            allowBrowserFallback: false
          })
          .then(function (result) {
            // #region agent log
            (function (payload) {
              var body = JSON.stringify(payload);
              fetch('http://127.0.0.1:7764/ingest/3c15e9d7-8289-4a1b-877f-c72ceeda0753',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'42fa9a'},body:body}).catch(function(){});
              fetch('/api/hbe-agent-debug',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-Requested-With':'XMLHttpRequest'},body:body}).catch(function(){});
            })({sessionId:'42fa9a',runId:'post-fix',hypothesisId:'F',location:'pos_invoice.js:printKotTicket.result',message:'printKotHtml result',data:{via:result&&result.via,err:result&&result.error&&result.error.message,role:group.menuOutlet,htmlLen:(html&&html.length)||0,textLen:(text&&text.length)||0,textPreview:String(text||'').slice(0,80)},timestamp:Date.now()});
            // #endregion
            if (result && result.via === 'failed') {
              toast(
                (result.error && result.error.message) ||
                  'KOT print failed. Open Hotel Print Agent and map Restaurant / Bar KOT.'
              );
            }
          });
      });
    } catch (err) {
      /* Printing is best-effort only — order state below is unaffected. */
    }
  }

  /** Customer-facing bill HTML — same layout used by Print and Send to Customer. */
  function buildCustomerBillHtml(page, invoice) {
    var now = new Date();
    var outlet = (page && page.getAttribute('data-pos-outlet')) || 'restaurant';
    var lines =
      invoice && Array.isArray(invoice.lines) && invoice.lines.length
        ? invoice.lines
        : state.lines;
    var totals = invoice
      ? normalizeTotals(invoice)
      : calcTotals();
    var billData = invoice
      ? Object.assign({}, invoice)
      : {
          outlet: outlet,
          order_no: state.orderNo || '—',
          table_label: fieldValue('pos-inv-table', page) || '—',
          order_type:
            fieldValue('pos-inv-order-type-header', page) ||
            fieldValue('pos-inv-order-type', page) ||
            'dine_in',
          customer_name: fieldValue('pos-inv-customer-name', page) || '',
          customer_mobile: digitsOnly(fieldValue('pos-inv-customer-mobile', page), 10) || '',
          lines: lines,
          discount_type: totals.discountType,
          discount_value: totals.discountValue,
          service_type: totals.serviceType,
          service_value: totals.serviceValue,
          subtotal: totals.subtotal,
          discount: totals.discount,
          gst: totals.gst,
          vat: totals.vat,
          cgst: totals.cgst,
          ugst: totals.ugst,
          service: totals.service,
          tip: totals.tip,
          round_off: totals.roundOff,
          grand_total: totals.total,
          payments: []
        };
    if (!billData.outlet) billData.outlet = outlet;
    if (!Array.isArray(billData.lines)) billData.lines = lines;
    if (typeof global.buildPosCustomerBillHtml === 'function') {
      return global.buildPosCustomerBillHtml(billData, { now: now, outlet: outlet });
    }
    return buildCustomerBillHtmlLegacy(page, invoice);
  }

  function normalizeTotals(invoice) {
    var gst = Number(invoice && invoice.gst != null ? invoice.gst : 0);
    return {
      discountType: invoice && invoice.discount_type,
      discountValue: invoice && invoice.discount_value,
      serviceType: invoice && invoice.service_type,
      serviceValue: invoice && invoice.service_value,
      subtotal: Number(invoice && invoice.subtotal != null ? invoice.subtotal : 0),
      discount: Number(invoice && invoice.discount != null ? invoice.discount : 0),
      gst: gst,
      vat: Number(invoice && invoice.vat != null ? invoice.vat : 0),
      cgst: invoice && invoice.cgst != null ? Number(invoice.cgst) : gst / 2,
      ugst: invoice && invoice.ugst != null ? Number(invoice.ugst) : gst / 2,
      service: Number(invoice && invoice.service != null ? invoice.service : 0),
      tip: Number(invoice && invoice.tip != null ? invoice.tip : 0),
      roundOff: Number(invoice && invoice.round_off != null ? invoice.round_off : 0),
      total: Number(invoice && invoice.grand_total != null ? invoice.grand_total : 0)
    };
  }

  /** Fallback if pos_customer_bill.js is not loaded. */
  function buildCustomerBillHtmlLegacy(page, invoice) {
    var now = new Date();
    var orderNo = (invoice && invoice.order_no) || state.orderNo || '—';
    var table = (invoice && (invoice.table_label || invoice.table)) || fieldValue('pos-inv-table', page) || '—';
    var orderTypeValue =
      (invoice && invoice.order_type) ||
      fieldValue('pos-inv-order-type-header', page) ||
      fieldValue('pos-inv-order-type', page) ||
      'dine_in';
    var orderType = ORDER_TYPE_LABELS[orderTypeValue] || orderTypeValue;
    var customerName = (invoice && invoice.customer_name) || fieldValue('pos-inv-customer-name', page) || '';
    var customerMobile =
      (invoice && invoice.customer_mobile) || digitsOnly(fieldValue('pos-inv-customer-mobile', page), 10) || '';
    var lines =
      invoice && Array.isArray(invoice.lines) && invoice.lines.length
        ? invoice.lines
        : state.lines;
    var totals = invoice
      ? {
          discountType: invoice.discount_type,
          discountValue: invoice.discount_value,
          serviceType: invoice.service_type,
          serviceValue: invoice.service_value,
          subtotal: invoice.subtotal,
          discount: invoice.discount,
          gst: invoice.gst,
          vat: invoice.vat,
          cgst: Number(invoice.gst || 0) / 2,
          ugst: Number(invoice.gst || 0) / 2,
          service: invoice.service,
          tip: invoice.tip,
          roundOff: invoice.round_off,
          total: invoice.grand_total
        }
      : calcTotals();

    var rows = lines
      .map(function (line) {
        var qty = Number(line.qty) || 0;
        var rate = Number(line.rate) || 0;
        var amt = line.line_total != null ? Number(line.line_total) : rate * qty;
        // Line notes and category/variant are staff-only — never print on customer bill.
        return (
          '<tr><td class="name">' +
          escapeHtml(line.name) +
          '</td><td class="qty">' +
          qty +
          '</td><td class="rate">' +
          money(rate) +
          '</td><td class="amt">' +
          money(amt) +
          '</td></tr>'
        );
      })
      .join('');

    var discHint = formatAdjHint(totals.discountType, totals.discountValue);
    var svcHint = formatAdjHint(totals.serviceType, totals.serviceValue);
    var custRow = customerName
      ? '<div><span>Customer</span><span>' +
        escapeHtml(customerName) +
        (customerMobile ? ' · +91 ' + escapeHtml(customerMobile) : '') +
        '</span></div>'
      : '';

    return (
      '<!DOCTYPE html><html><head><meta charset="utf-8"><title>Bill ' +
      escapeHtml(orderNo) +
      '</title><style>' +
      'body{font-family:"Courier New",monospace;padding:16px;color:#111;width:340px;margin:0 auto}' +
      'h1{font-size:16px;margin:0 0 4px;text-align:center;letter-spacing:.04em}' +
      '.sub{font-size:11px;text-align:center;color:#555;margin-bottom:10px}' +
      '.meta{font-size:12px;margin-bottom:10px;border-bottom:1px dashed #333;padding-bottom:8px}' +
      '.meta div{display:flex;justify-content:space-between;margin:2px 0;gap:8px}' +
      'table.items{width:100%;border-collapse:collapse;font-size:12px}' +
      'table.items th{text-align:left;font-size:11px;border-bottom:1px solid #333;padding:4px 0}' +
      'table.items td{padding:4px 0;border-bottom:1px dashed #ddd;vertical-align:top}' +
      'table.items td.qty,table.items th.qty{width:30px;text-align:center}' +
      'table.items td.rate,table.items th.rate,table.items td.amt,table.items th.amt{width:64px;text-align:right}' +
      '.variant{font-size:10px;color:#555}' +
      '.totals{margin-top:10px;font-size:12px}' +
      '.totals div{display:flex;justify-content:space-between;margin:2px 0}' +
      '.totals .grand{font-size:15px;font-weight:700;border-top:1px solid #333;margin-top:6px;padding-top:6px}' +
      '.foot{margin-top:14px;text-align:center;font-size:11px;color:#555}' +
      '@media print{body{width:auto;margin:0}}' +
      '</style></head><body>' +
      '<h1>Hotel Bell Elite</h1>' +
      '<div class="sub">Customer Bill</div>' +
      '<div class="meta">' +
      '<div><span>Order</span><span>' +
      escapeHtml(orderNo) +
      '</span></div>' +
      '<div><span>Table</span><span>' +
      escapeHtml(table) +
      '</span></div>' +
      '<div><span>Type</span><span>' +
      escapeHtml(orderType) +
      '</span></div>' +
      '<div><span>Date</span><span>' +
      formatDate(now) +
      ' ' +
      formatTime(now) +
      '</span></div>' +
      custRow +
      '</div>' +
      '<table class="items"><thead><tr><th>Item</th><th class="qty">Qty</th><th class="rate">Rate</th><th class="amt">Amt</th></tr></thead>' +
      '<tbody>' +
      (rows ||
        '<tr><td colspan="4" style="text-align:center;color:#555">No items</td></tr>') +
      '</tbody></table>' +
      '<div class="totals">' +
      '<div><span>Subtotal</span><span>' +
      money(totals.subtotal) +
      '</span></div>' +
      (Number(totals.discount) > 0 || Number(totals.discountValue) > 0
        ? '<div><span>Discount' +
          (discHint ? ' ' + discHint : '') +
          '</span><span>-' +
          money(totals.discount) +
          '</span></div>'
        : '') +
      '<div><span>CGST (' +
      CGST_RATE * 100 +
      '%)</span><span>' +
      money(totals.cgst != null ? totals.cgst : Number(totals.gst || 0) / 2) +
      '</span></div>' +
      '<div><span>UGST (' +
      UGST_RATE * 100 +
      '%)</span><span>' +
      money(totals.ugst != null ? totals.ugst : Number(totals.gst || 0) / 2) +
      '</span></div>' +
      (Number(totals.vat) > 0
        ? '<div><span>VAT (' +
          VAT_RATE * 100 +
          '%)</span><span>' +
          money(totals.vat) +
          '</span></div>'
        : '') +
      (Number(totals.service) > 0 || Number(totals.serviceValue) > 0
        ? '<div><span>Service Charge' +
          (svcHint ? ' ' + svcHint : '') +
          '</span><span>' +
          money(totals.service) +
          '</span></div>'
        : '') +
      (Number(totals.tip) > 0
        ? '<div><span>Tip</span><span>' + money(totals.tip) + '</span></div>'
        : '') +
      '<div><span>Round Off</span><span>' +
      money(totals.roundOff) +
      '</span></div>' +
      '<div class="grand"><span>Total</span><span>' +
      money(totals.total) +
      '</span></div>' +
      '</div>' +
      '<div class="foot">Thank you for dining with us!</div>' +
      '</body></html>'
    );
  }

  function closeInAppPrintPage() {
    var overlay = document.getElementById('pos-inapp-print-page');
    if (overlay && overlay.parentNode) overlay.parentNode.removeChild(overlay);
  }

  /** Fullscreen-safe print page inside the workspace. */
  function openInAppPrintPage(html, opts) {
    opts = opts || {};
    var autoPrint = opts.autoPrint !== false;
    closeInAppPrintPage();
    var host = document.getElementById('de-fs-app') || document.body;
    var overlay = document.createElement('div');
    overlay.id = 'pos-inapp-print-page';
    overlay.className = 'pos-inapp-print-page';
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    overlay.setAttribute('aria-label', 'Print page');
    overlay.innerHTML =
      '<div class="pos-inapp-print-toolbar">' +
      '<span class="pos-inapp-print-title">Print page</span>' +
      '<div class="pos-inapp-print-actions">' +
      '<button type="button" class="pos-inapp-print-btn" data-pos-inapp-print>Print</button>' +
      '<button type="button" class="pos-inapp-print-btn pos-inapp-print-btn--ghost" data-pos-inapp-close>Close</button>' +
      '</div></div>' +
      '<iframe class="pos-inapp-print-frame" title="Print page"></iframe>';
    host.appendChild(overlay);

    var frame = overlay.querySelector('iframe');
    var idoc =
      frame && (frame.contentDocument || (frame.contentWindow && frame.contentWindow.document));
    if (!idoc) {
      closeInAppPrintPage();
      return false;
    }
    idoc.open();
    idoc.write(html);
    idoc.close();

    function doPrint() {
      try {
        if (frame.contentWindow) {
          frame.contentWindow.focus();
          frame.contentWindow.print();
        }
      } catch (err) {}
    }

    overlay.addEventListener('click', function (event) {
      if (event.target.closest('[data-pos-inapp-close]')) {
        closeInAppPrintPage();
        return;
      }
      if (event.target.closest('[data-pos-inapp-print]')) {
        doPrint();
      }
    });
    document.addEventListener(
      'keydown',
      function onEsc(ev) {
        if (ev.key !== 'Escape') return;
        document.removeEventListener('keydown', onEsc);
        closeInAppPrintPage();
      },
      { once: true }
    );
    if (autoPrint) setTimeout(doPrint, 300);
    return true;
  }

  function openBillPrintPage(html, opts) {
    opts = opts || {};
    var autoPrint = opts.autoPrint !== false;
    var width = opts.width || 420;
    var height = opts.height || 680;

    try {
      var win = global.open('', '_blank', 'width=' + width + ',height=' + height);
      if (win) {
        try {
          win.document.open();
          win.document.write(html);
          win.document.close();
          win.focus();
          if (autoPrint) {
            setTimeout(function () {
              try {
                win.print();
              } catch (err) {}
            }, 250);
          }
          return true;
        } catch (err) {
          try {
            win.close();
          } catch (closeErr) {}
        }
      }
    } catch (err) {}

    try {
      var blob = new Blob([html], { type: 'text/html' });
      var url = URL.createObjectURL(blob);
      var blobWin = global.open(url, '_blank', 'width=' + width + ',height=' + height);
      if (blobWin) {
        setTimeout(function () {
          try {
            blobWin.focus();
            if (autoPrint) blobWin.print();
          } catch (err) {}
          setTimeout(function () {
            URL.revokeObjectURL(url);
          }, 60000);
        }, 300);
        return true;
      }
      URL.revokeObjectURL(url);
    } catch (err) {}

    return openInAppPrintPage(html, { autoPrint: autoPrint });
  }

  /** Customer-facing bill — distinct from the kitchen KOT ticket above. */
  function printCustomerBill(page, invoice, opts) {
    opts = opts || {};
    try {
      var html = buildCustomerBillHtml(page, invoice);
      var outlet = (page && page.getAttribute('data-pos-outlet')) || undefined;
      var wantAuto = opts.autoPrint !== false;
      var jobId =
        'inv-' +
        String(
          (invoice && (invoice.id || invoice.order_no)) ||
            state.invoiceId ||
            state.orderNo ||
            Date.now()
        ) +
        '-' +
        Date.now();
      var prefs = global.hbePosPrinterPrefs;
      var canAgent =
        prefs && typeof prefs.printInvoiceHtml === 'function';

      function browserPrint(autoPrint) {
        if (!openBillPrintPage(html, { autoPrint: !!autoPrint })) {
          toast('Could not open the print page. Check your pop-up blocker.');
        }
      }

      if (!wantAuto) {
        /* Manual Print: open preview on the click gesture, also send to billing. */
        browserPrint(false);
        if (canAgent) {
          prefs.printInvoiceHtml(html, {
            outlet: outlet,
            jobId: jobId,
            browserPrint: function () {}
          });
        }
        return;
      }

      /* Settle auto-print: silent via Restaurant Invoice printer — no Chrome dialog. */
      if (canAgent) {
        prefs
          .printInvoiceHtml(html, {
            outlet: outlet,
            jobId: jobId,
            allowBrowserFallback: false
          })
          .then(function (result) {
            if (result && result.via === 'failed') {
              toast(
                (result.error && result.error.message) ||
                  'Bill print failed. Open Hotel Print Agent and map Restaurant Invoice.'
              );
            }
          });
        return;
      }
      toast(
        'Hotel Print Agent is required for silent bill printing. Install and open it on this PC.'
      );
    } catch (err) {
      toast('Could not open the print page.');
    }
  }

  function openToolbarPrintPage(page) {
    if (!state.lines.length) {
      toast('Add at least one item before printing.');
      var search = $('#pos-inv-search', page);
      if (search) search.focus();
      return;
    }
    /* Land on the print page; staff print from there (or browser print). */
    printCustomerBill(page, null, { autoPrint: false });
  }

  function syncKotSentFromInvoice(invoice) {
    if (!invoice || !Array.isArray(invoice.lines)) return;
    invoice.lines.forEach(function (serverLine) {
      var name = String(serverLine.name || '').trim();
      var rate = Number(serverLine.rate) || 0;
      var sent = Number(serverLine.sent_qty != null ? serverLine.sent_qty : serverLine.kotSentQty) || 0;
      state.lines.forEach(function (local) {
        if (String(local.name || '').trim() === name && Number(local.rate) === rate) {
          local.sentQty = sent;
        }
      });
    });
  }

  /** After Generate Invoice, use the dedicated send-kot endpoint (cart is locked). */
  function sendKotForGeneratedInvoice(page, pending) {
    if (!isBrowserOnline()) {
      toast('Send to Kitchen requires an internet connection after the invoice is generated.');
      return Promise.resolve();
    }
    if (!state.invoiceId) {
      toast('Sync required before sending to kitchen. Reconnect to the network.');
      return Promise.resolve();
    }

    var btn = $('#pos-inv-send-kot', page);
    if (btn) btn.disabled = true;

    return fetch(INVOICE_API + '/' + encodeURIComponent(state.invoiceId) + '/send-kot', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { Accept: 'application/json' }
    })
      .then(function (res) {
        return res
          .json()
          .catch(function () {
            return {};
          })
          .then(function (data) {
            return { ok: res.ok && !!(data && data.ok), data: data || {} };
          });
      })
      .then(function (result) {
        if (!result.ok) {
          toast((result.data && result.data.error) || 'Could not send KOT.');
          return;
        }
        syncKotSentFromInvoice(result.data.invoice);
        if (
          !global.hbePosPrinterPrefs ||
          global.hbePosPrinterPrefs.shouldAutoPrintKot(
            (page && page.getAttribute('data-pos-outlet')) || undefined
          )
        ) {
          printKotTicket(page, pending);
        }
        var count = pending.length;
        renderLines(page);
        toast('KOT sent to kitchen for ' + count + (count === 1 ? ' item.' : ' items.'));
      })
      .catch(function () {
        toast('Could not send KOT. Check your connection and try again.');
      })
      .then(function () {
        if (btn) btn.disabled = false;
        updateKotBar(page);
      });
  }

  function sendKot(page) {
    var pending = pendingKotLines();
    if (!pending.length) {
      toast('Nothing new to send — kitchen is already up to date.');
      return;
    }
    if (state.invoiceGenerated && state.invoiceId) {
      sendKotForGeneratedInvoice(page, pending);
      return;
    }
    if (guardInvoiceLocked()) return;

    var customerName = fieldValue('pos-inv-customer-name', page);
    if (!customerName) {
      toast('Enter customer name before sending to the kitchen.');
      var nameEl = $('#pos-inv-customer-name', page);
      if (nameEl) nameEl.focus();
      return;
    }

    /* A KOT send persists the order (same as Save). Dine-in saves claim the
       table as occupied — see save_pos_invoice(). Once this session already
       owns a saved/resumed invoice (state.invoiceId), the table's own
       "occupied" status is this very order and must never block it. */
    var orderType = fieldValue('pos-inv-order-type-header', page) || fieldValue('pos-inv-order-type', page) || 'dine_in';
    if (orderType === 'dine_in' && !fieldValue('pos-inv-table', page)) {
      toast('Select a table before sending to the kitchen.');
      var tableTrigger = $('#pos-inv-table-trigger', page) || document.getElementById('pos-inv-table-trigger');
      if (tableTrigger) tableTrigger.focus();
      return;
    }
    if (orderType === 'dine_in' && !state.invoiceId && tableBlocksNewBill(selectedTableStatus(page))) {
      toast('This table is occupied by another order. Choose another table or resume its order from the picker.');
      return;
    }

    if (!state.orderNo) initMeta(page);
    ensureLocalId();

    var payload = collectOrderPayload(page);
    payload.kotSend = true;
    payload.clientLocalId = state.localId;
    var pendingUids = {};
    pending.forEach(function (entry) {
      pendingUids[entry.line.uid] = true;
    });
    payload.lines.forEach(function (line) {
      if (pendingUids[line.uid]) line.kotSentQty = line.qty;
    });
    var epochAtStart = dirtyEpoch;

    var btn = $('#pos-inv-send-kot', page);
    if (btn) btn.disabled = true;

    function finishKotSuccess(invoice) {
      if (invoice) {
        state.invoiceId = invoice.id;
        state.tableForOrder = invoice.table_label || invoice.table || state.tableForOrder;
        if (invoice.order_no) {
          state.orderNo = invoice.order_no;
          noteOutletOrderSeq(invoice.order_no);
        }
        syncOrderNoMeta(page);
      }
      clearDirtyAfterPersist(epochAtStart, page);
      if (!state.dirty) cancelAutosaveTimer();
      syncFloorOccupancyAfterSave(page, payload, invoice);
      if (
        !global.hbePosPrinterPrefs ||
        global.hbePosPrinterPrefs.shouldAutoPrintKot(
          (page && page.getAttribute('data-pos-outlet')) || undefined
        )
      ) {
        printKotTicket(page, pending);
      }
      pending.forEach(function (entry) {
        entry.line.sentQty = Number(entry.line.qty) || 0;
      });
      var count = pending.length;
      renderLines(page);
      toast(
        isBrowserOnline()
          ? 'KOT sent to kitchen for ' + count + (count === 1 ? ' item.' : ' items.')
          : 'KOT printed offline for ' + count + (count === 1 ? ' item.' : ' items.') + ' Will sync when online.'
      );
    }

    function runKotSave() {
      if (!isBrowserOnline()) {
        return queueOfflineSave(page, payload, {
          silent: true,
          toastOnSuccess: false,
          epochAtStart: epochAtStart
        }).then(function (outcome) {
          if (outcome && outcome.ok) finishKotSuccess(null);
          else toast('Could not save KOT offline.');
        });
      }
      var api = offlineApi();
      var post =
        api && api.tryPostWithConflictRetry
          ? api.tryPostWithConflictRetry(payload)
          : fetch(INVOICE_API, {
              method: 'POST',
              credentials: 'same-origin',
              headers: {
                Accept: 'application/json',
                'Content-Type': 'application/json'
              },
              body: JSON.stringify(payload)
            }).then(function (res) {
              return res
                .json()
                .then(function (data) {
                  return { ok: res.ok && !!(data && data.ok), data: data || {} };
                })
                .catch(function () {
                  return { ok: false, data: {} };
                });
            });
      return post
        .then(function (result) {
          if (!result.ok || !(result.data && result.data.ok)) {
            return queueOfflineSave(page, payload, {
              silent: true,
              toastOnSuccess: false,
              epochAtStart: epochAtStart
            }).then(function (outcome) {
              if (outcome && outcome.ok) finishKotSuccess(null);
              else toast((result.data && result.data.error) || 'Could not send KOT.');
            });
          }
          finishKotSuccess(result.data.invoice);
          mirrorDraft(page, payload);
        })
        .catch(function () {
          return queueOfflineSave(page, payload, {
            silent: true,
            toastOnSuccess: false,
            epochAtStart: epochAtStart
          }).then(function (outcome) {
            if (outcome && outcome.ok) finishKotSuccess(null);
            else toast('Could not send KOT. Check your connection and try again.');
          });
        });
    }

    runKotSave().then(function () {
      if (btn) btn.disabled = false;
      updateKotBar(page);
    });
  }

  /** "Send to Customer" — generates the customer-facing bill. Distinct from
   *  sendKot() above: this never touches kitchen KOT state, it persists the
   *  order (same save path as Save/Send to Kitchen, so the bill always shows a
   *  stable, saved order number) and then opens a print-ready bill with every
   *  line, discount/GST/service/tip and the grand total. Does not close or
   *  free the table — that stays a separate, explicit action. */
  function sendToCustomer(page) {
    if (guardInvoiceLocked()) return;
    if (!state.lines.length) {
      toast('Add at least one item before generating the invoice.');
      var search = $('#pos-inv-search', page);
      if (search) search.focus();
      return;
    }

    var customerName = fieldValue('pos-inv-customer-name', page);
    if (!customerName) {
      toast('Enter customer name before generating the invoice.');
      var nameEl = $('#pos-inv-customer-name', page);
      if (nameEl) nameEl.focus();
      return;
    }

    /* Same client-side belt as Save/Send to Kitchen — see sendKot() for why
       state.invoiceId exempts a session that already owns this table's order. */
    var orderType = fieldValue('pos-inv-order-type-header', page) || fieldValue('pos-inv-order-type', page) || 'dine_in';
    if (orderType === 'dine_in' && !state.invoiceId && tableBlocksNewBill(selectedTableStatus(page))) {
      toast('This table is occupied by another order. Choose another table or resume its order from the picker.');
      return;
    }

    if (!state.orderNo) initMeta(page);
    ensureLocalId();

    var payload = collectOrderPayload(page);
    /* Marks the order so Kitchen Order Tokens can disable Resend after the
       customer bill has been generated / printed. Sticky once set on server. */
    payload.customerBill = true;
    payload.clientLocalId = state.localId;
    var epochAtStart = dirtyEpoch;
    var btn = $('#pos-inv-send-customer', page) || page.querySelector('[data-inv-action="send"]');
    if (btn) btn.disabled = true;

    function finishCustomerBill(invoice) {
      if (invoice) {
        state.invoiceId = invoice.id;
        state.tableForOrder = invoice.table_label || invoice.table || state.tableForOrder;
        if (invoice.order_no) {
          state.orderNo = invoice.order_no;
          noteOutletOrderSeq(invoice.order_no);
        }
        syncOrderNoMeta(page);
      }
      clearDirtyAfterPersist(epochAtStart, page);
      if (!state.dirty) cancelAutosaveTimer();
      syncFloorOccupancyAfterSave(page, payload, invoice);
      markInvoiceGenerated(page, invoice);
      printCustomerBill(page, invoice || null);
      toast(
        'Invoice generated for ' +
          ((invoice && invoice.order_no) || state.orderNo) +
          (isBrowserOnline() ? '. Settle the bill to continue.' : ' (offline — will sync).')
      );
    }

    function runCustomerSave() {
      if (!isBrowserOnline()) {
        return queueOfflineSave(page, payload, {
          silent: true,
          toastOnSuccess: false,
          epochAtStart: epochAtStart
        }).then(function (outcome) {
          if (outcome && outcome.ok) finishCustomerBill(null);
          else toast('Could not save bill offline.');
        });
      }
      var api = offlineApi();
      var post =
        api && api.tryPostWithConflictRetry
          ? api.tryPostWithConflictRetry(payload)
          : fetch(INVOICE_API, {
              method: 'POST',
              credentials: 'same-origin',
              headers: {
                Accept: 'application/json',
                'Content-Type': 'application/json'
              },
              body: JSON.stringify(payload)
            }).then(function (res) {
              return res
                .json()
                .then(function (data) {
                  return { ok: res.ok && !!(data && data.ok), data: data || {} };
                })
                .catch(function () {
                  return { ok: false, data: {} };
                });
            });
      return post
        .then(function (result) {
          if (!result.ok || !(result.data && result.data.ok)) {
            return queueOfflineSave(page, payload, {
              silent: true,
              toastOnSuccess: false,
              epochAtStart: epochAtStart
            }).then(function (outcome) {
              if (outcome && outcome.ok) finishCustomerBill(null);
              else toast((result.data && result.data.error) || 'Could not generate the bill.');
            });
          }
          finishCustomerBill(result.data.invoice);
          mirrorDraft(page, payload);
        })
        .catch(function () {
          return queueOfflineSave(page, payload, {
            silent: true,
            toastOnSuccess: false,
            epochAtStart: epochAtStart
          }).then(function (outcome) {
            if (outcome && outcome.ok) finishCustomerBill(null);
            else toast('Could not generate the bill. Check your connection and try again.');
          });
        });
    }

    runCustomerSave().then(function () {
      if (btn) btn.disabled = false;
      updateSettleBillButton(page);
    });
  }

  function addItem(page, item, qty) {
    if (guardInvoiceLocked()) return;
    var existing = null;
    var i;
    for (i = 0; i < state.lines.length; i++) {
      if (state.lines[i].menuId && item.id && state.lines[i].menuId === item.id) {
        existing = state.lines[i];
        break;
      }
    }
    if (existing) {
      existing.qty += qty || 1;
      if (!existing.outlet) {
        existing.outlet =
          String(item.outlet || '').toLowerCase() === 'bar' ? 'bar' : 'restaurant';
      }
    } else {
      state.lineSeq += 1;
      state.lines.push({
        uid: 'L' + state.lineSeq,
        menuId: item.id || null,
        name: item.name,
        category: item.category || '',
        variant: item.variant || item.category || '',
        rate: Number(item.rate) || 0,
        qty: qty || 1,
        isLiquor: !!item.isLiquor || item.itemKind === 'liquor' || isLiquorCategory(item.category),
        itemKind: item.itemKind === 'liquor' || item.isLiquor ? 'liquor' : 'food',
        outlet: String(item.outlet || '').toLowerCase() === 'bar' ? 'bar' : 'restaurant',
        emoji: item.emoji || '🍽️',
        /* KOT is not fired on add — sentQty tracks how much of this line has
           already been confirmed to the kitchen so only the delta re-KOTs. */
        sentQty: 0,
        notes: ''
      });
    }
    renderLines(page);
    markOrderDirty(page);
  }

  function pendingKotQty(line) {
    var pending = (Number(line.qty) || 0) - (Number(line.sentQty) || 0);
    return pending > 0 ? pending : 0;
  }

  function pendingKotLines() {
    var out = [];
    state.lines.forEach(function (line) {
      var qty = pendingKotQty(line);
      if (qty > 0) out.push({ line: line, qty: qty });
    });
    return out;
  }

  function closeSuggest(page) {
    var box = $('#pos-inv-suggest', page);
    var input = $('#pos-inv-search', page);
    if (box) {
      box.hidden = true;
      box.innerHTML = '';
    }
    if (input) input.setAttribute('aria-expanded', 'false');
    state.activeIndex = -1;
  }

  function renderSuggest(page, results, query) {
    var box = $('#pos-inv-suggest', page);
    var input = $('#pos-inv-search', page);
    if (!box) return;

    if (!results.length) {
      box.hidden = false;
      box.innerHTML =
        '<div class="pos-inv-suggest-empty">' +
        escapeHtml(suggestEmptyMessage(query)) +
        '</div>';
      if (input) input.setAttribute('aria-expanded', 'true');
      state.activeIndex = -1;
      return;
    }

    box.hidden = false;
    if (input) input.setAttribute('aria-expanded', 'true');
    box.innerHTML = results
      .map(function (item, idx) {
        var metaParts = [item.code, item.category];
        if (item.variant) metaParts.push(item.variant);
        if (item.outlet === 'bar') metaParts.push('Bar');
        if (item.outlet === 'restaurant' && resolvePosOutlet() === 'bar') {
          metaParts.push('Restaurant');
        }
        return (
          '<button type="button" class="pos-inv-suggest-item' +
          (idx === state.activeIndex ? ' is-active' : '') +
          '" role="option" data-menu-id="' +
          escapeHtml(item.id) +
          '" id="pos-inv-opt-' +
          idx +
          '">' +
          '<span class="pos-inv-suggest-thumb">' +
          escapeHtml(item.emoji || '🍽️') +
          '</span>' +
          '<span class="pos-inv-suggest-copy">' +
          '<span class="pos-inv-suggest-name">' +
          escapeHtml(item.name) +
          '</span>' +
          '<span class="pos-inv-suggest-meta">' +
          escapeHtml(metaParts.filter(Boolean).join(' · ')) +
          '</span></span>' +
          '<span class="pos-inv-suggest-price">' +
          money(item.rate) +
          '</span></button>'
        );
      })
      .join('');
  }

  function selectSuggestion(page, menuId) {
    var item = findMenuItem(menuId);
    if (!item) return;
    addItem(page, item, 1);
    var input = $('#pos-inv-search', page);
    var clearBtn = $('#pos-inv-search-clear', page);
    if (input) {
      input.value = '';
      input.focus();
    }
    if (clearBtn) clearBtn.hidden = true;
    closeSuggest(page);
  }

  function syncOrderTypeMeta(page) {
    var header = $('#pos-inv-order-type-header', page);
    if (!header) return;
    var value = (header && header.value) || fieldValue('pos-inv-order-type-header', page) || 'dine_in';
    var label = ORDER_TYPE_LABELS[value] || value;
    setListboxValue('pos-inv-order-type-header', value, label);
  }

  function setListboxValue(fieldId, value, label) {
    if (typeof global.resetEpListbox === 'function') {
      global.resetEpListbox(fieldId, value, label);
      return;
    }
    var input = document.getElementById(fieldId);
    if (input) input.value = value || '';
    var root = document.getElementById(fieldId + '-listbox');
    if (!root) return;
    var valueEl = root.querySelector('.se-filter-chip-value');
    if (valueEl) {
      valueEl.textContent = label || value || '';
      valueEl.classList.toggle('is-placeholder', !value);
    }
  }

  function resolvePreferredTable(page, opts) {
    opts = opts || {};
    if (opts.preserveTable) return String(opts.preserveTable || '').trim();
    var current =
      fieldValue('pos-inv-table', page) ||
      String(state.tableForOrder || '').trim() ||
      String(state.resumeTableValue || '').trim();
    if (current) return current;
    var fromQuery = queryParam('table').trim();
    if (fromQuery) return fromQuery;
    var stored = readStoredResumeContext();
    return stored && stored.table ? stored.table : '';
  }

  function tableNameMatches(name, pref) {
    if (!name || !pref) return false;
    var a = String(name).trim().toLowerCase();
    var b = String(pref).trim().toLowerCase();
    return a === b || ('table ' + a) === b || a === ('table ' + b);
  }

  function applyPreferredTable(page, tableName) {
    var name = String(tableName || '').trim();
    if (!name) return;
    setListboxValue('pos-inv-table', name, name);
    state.resumeTableValue = name;
    state.resumeTableLabel = name;
    if (!state.tableForOrder) state.tableForOrder = name;
    persistInvoiceResumeContext();
  }

  function populateTables(page, tablesIn, opts) {
    var list = $('#pos-inv-table-list', page);
    var input = $('#pos-inv-table', page);
    if (!list || !input) return;
    /* Prefer the live selection over stale ?table= in the URL. After item add /
       autosave we refresh occupancy badges — that must not jump the chip back
       to Table 1 from an old query param. */
    var pref = resolvePreferredTable(page, opts);
    /* Floor data hasn't come back from the API yet — show a status row instead
       of leaving the panel blank, so the chip never looks unresponsive while it
       opens correctly but has nothing to render yet. */
    if (opts && opts.loading && !(tablesIn && tablesIn.length)) {
      list.innerHTML = '<div class="se-filter-listbox-status" role="presentation">Loading tables…</div>';
      /* Still bind a preferred table so early Save/KOT cannot post a dine-in bill with no table. */
      if (pref) applyPreferredTable(page, pref);
      return;
    }
    var tables = (tablesIn || loadFloorTablesSync()).slice().sort(function (a, b) {
      return String(a.name || '').localeCompare(String(b.name || ''), undefined, { numeric: true });
    });
    var selected = '';
    var selectedLabel = 'Select table…';
    var html = '';
    tables.forEach(function (t) {
      var name = String(t.name || 'Table');
      var seats = t.seats != null ? t.seats : '';
      var status = mapTableStatus(t.status);
      var blocked = tableBlocksNewBill(status);
      var baseLabel = seats !== '' ? name + ' (' + seats + ' Seats)' : name;
      var statusText = blocked ? (TABLE_STATUS_LABELS[status] || status) : '';
      var on = false;
      /* Occupied tables stay selectable — picking one resumes its open order
         instead of starting a new bill; see posInvTableChanged(). */
      if (pref && tableNameMatches(name, pref)) {
        on = true;
        selected = name;
        selectedLabel = baseLabel;
      }
      html +=
        '<button type="button" class="se-filter-listbox-option' +
        (on ? ' is-selected' : '') +
        (blocked ? ' is-occupied' : '') +
        '" role="option" data-value="' +
        escapeHtml(name) +
        '" data-name="' +
        escapeHtml(name.toLowerCase()) +
        '" data-label="' +
        escapeHtml(baseLabel) +
        '" data-status="' +
        escapeHtml(status) +
        '" aria-selected="' +
        (on ? 'true' : 'false') +
        '"' +
        (blocked ? ' title="Occupied — tap to resume its open order."' : '') +
        '>' +
        '<span class="se-filter-listbox-option-text">' + escapeHtml(baseLabel) + '</span>' +
        (statusText ? '<span class="se-filter-listbox-option-status">' + escapeHtml(statusText) + '</span>' : '') +
        '</button>';
    });
    if (pref) {
      var matched = tables.some(function (t) {
        return tableNameMatches(t.name || '', pref);
      });
      if (!matched) {
        selected = pref;
        selectedLabel = pref;
        html +=
          '<button type="button" class="se-filter-listbox-option is-selected" role="option" data-value="' +
          escapeHtml(pref) +
          '" data-name="' +
          escapeHtml(pref.toLowerCase()) +
          '" data-label="' +
          escapeHtml(pref) +
          '" aria-selected="true">' +
          escapeHtml(pref) +
          '</button>';
      }
    }
    list.innerHTML = html;
    setListboxValue('pos-inv-table', selected, selectedLabel);
    state.resumeTableValue = selected;
    state.resumeTableLabel = selectedLabel;
    if (selected) {
      state.tableForOrder = selected;
    } else if (pref) {
      /* Keep prior order table if rebuild failed to match — never blank the chip. */
      state.tableForOrder = pref;
      state.resumeTableValue = pref;
      state.resumeTableLabel = pref;
      setListboxValue('pos-inv-table', pref, pref);
    }
  }

  function posInvOrderTypeChanged(root, value, label) {
    var page = document.getElementById('pos-invoice-page');
    if (!page) return;
    if (guardInvoiceLocked()) return;
    var display = label || ORDER_TYPE_LABELS[value] || value;
    setListboxValue('pos-inv-order-type-header', value, display);
  }

  function initMeta(page) {
    var now = new Date();
    var dateEl = $('#pos-inv-meta-date', page);
    var timeEl = $('#pos-inv-meta-time', page);
    if (dateEl) dateEl.textContent = formatDate(now);
    if (timeEl) timeEl.textContent = formatTime(now);
    if (!state.orderNo) state.orderNo = makeOrderNo(now);
    syncOrderNoMeta(page);
    syncOrderTypeMeta(page);
  }

  /** Load this session's in-progress state from a persisted invoice — the core
   *  of "resume this table's order" (Tables tile tap, or picking an occupied
   *  table from this page's own picker). Overwrites lines/customer/totals. */
  function hydrateFromInvoice(page, invoice, opts) {
    if (!invoice) return;
    opts = opts || {};
    state.invoiceId = invoice.id;
    state.orderNo = invoice.order_no || state.orderNo;
    noteOutletOrderSeq(state.orderNo);
    state.tableForOrder = invoice.table_label || invoice.table || '';
    state.discountType = invoice.discount_type || 'pct';
    state.discountValue = Number(invoice.discount_value) || 0;
    state.discountLineUids = normalizeDiscountLineUids(
      invoice.discount_line_uids || invoice.discountLineUids || []
    );
    state.discountReason = String(
      invoice.discount_reason || invoice.discountReason || ''
    ).trim();
    state.discountSelectMode = null;
    state.discountSelectDraft = [];
    state.serviceType = invoice.service_type || 'pct';
    state.serviceValue = Number(invoice.service_value) || 0;
    state.tipAmount = Number(invoice.tip_amount) || 0;
    state.couponCode = invoice.coupon_code || '';
    state.lineSeq = 0;
    state.lines = (invoice.lines || []).map(function (line, idx) {
      var persistedUid = String(line.uid || line.line_uid || '').trim();
      if (persistedUid) {
        var match = /^L(\d+)$/i.exec(persistedUid);
        if (match) state.lineSeq = Math.max(state.lineSeq, Number(match[1]) || 0);
      } else {
        state.lineSeq += 1;
        persistedUid = 'L' + state.lineSeq;
      }
      var menu = findMenuItem(line.menu_item_id || line.menuId);
      var category = (menu && menu.category) || line.category || '';
      var liquor =
        (menu && (menu.isLiquor || menu.itemKind === 'liquor')) ||
        line.item_kind === 'liquor' ||
        line.itemKind === 'liquor' ||
        isLiquorCategory(category) ||
        isLiquorCategory(line.variant);
      var lineOutlet = String(
        line.outlet || (menu && menu.outlet) || ''
      )
        .trim()
        .toLowerCase();
      if (lineOutlet !== 'bar') lineOutlet = 'restaurant';
      return {
        uid: persistedUid,
        menuId: line.menu_item_id || line.menuId || null,
        name: line.name,
        category: category,
        variant: line.variant || '',
        rate: Number(line.rate) || 0,
        qty: Number(line.qty) || 0,
        isLiquor: liquor,
        itemKind: liquor ? 'liquor' : 'food',
        outlet: lineOutlet,
        emoji: '🍽️',
        sentQty: Number(line.sent_qty) || 0,
        notes: String(line.notes || '').trim()
      };
    });
    pruneDiscountLineUids();

    syncOrderNoMeta(page);

    var nameEl = $('#pos-inv-customer-name', page);
    if (nameEl) nameEl.value = invoice.customer_name || DEFAULT_AUTOSAVE_CUSTOMER;
    var mobileEl = $('#pos-inv-customer-mobile', page);
    if (mobileEl) mobileEl.value = invoice.customer_mobile || '';
    var notesEl = $('#pos-inv-notes', page);
    if (notesEl) {
      notesEl.value = invoice.notes || '';
      updateNotesCount(page);
    }
    if (invoice.captain) setListboxValue('pos-inv-captain', invoice.captain, invoice.captain);

    var orderType = invoice.order_type || 'dine_in';
    var typeLabel = ORDER_TYPE_LABELS[orderType] || orderType;
    setListboxValue('pos-inv-order-type-header', orderType, typeLabel);

    state.invoiceGenerated = !!(invoice.customer_bill_sent);

    if (state.tableForOrder) {
      setListboxValue('pos-inv-table', state.tableForOrder, state.tableForOrder);
      state.resumeTableValue = state.tableForOrder;
      state.resumeTableLabel = state.tableForOrder;
      if (!state.invoiceGenerated) {
        markFloorTableOccupiedLocal(state.tableForOrder);
        if (page && floorTablesCache) applyFloorTablesToUi(page, floorTablesCache);
      }
    }

    state.dirty = false;
    if (autosaveTimer) {
      clearTimeout(autosaveTimer);
      autosaveTimer = null;
    }
    renderLines(page);
    syncInvoiceGeneratedUi(page);
    persistInvoiceResumeContext();
    if (!opts.silent) {
      toast(
        state.invoiceGenerated
          ? 'Resumed invoice ' + state.orderNo + ' (locked — settle to continue).'
          : 'Resumed order ' + state.orderNo + '.'
      );
    }
  }

  /** Shared lookup: is there an open dine-in order for this table? Used by both
   *  the initial ?table= page load and the header table picker's resume flow. */
  function resumeOrderForTable(page, tableName, opts) {
    var name = String(tableName || '').trim();
    if (!name) return;
    opts = opts || {};
    fetch(INVOICE_BY_TABLE_API + '?table=' + encodeURIComponent(name) + '&_ts=' + Date.now(), {
      credentials: 'same-origin',
      cache: 'no-store',
      headers: {
        Accept: 'application/json',
        'Cache-Control': 'no-cache',
        Pragma: 'no-cache'
      }
    })
      .then(function (res) {
        return res.json().catch(function () {
          return {};
        });
      })
      .then(function (data) {
        if (data && data.ok && data.invoice) {
          hydrateFromInvoice(page, data.invoice, { silent: !!opts.silent });
          return;
        }
        if (typeof opts.notFound === 'function') opts.notFound();
      })
      .catch(function () {
        if (typeof opts.notFound === 'function') opts.notFound();
      });
  }

  /**
   * Pull the open bill for the selected table from the server.
   * Skips when local edits are pending so we do not clobber an in-progress cart.
   * Repairs the common cross-terminal case: floor still says Available while
   * another browser already autosaved lines onto this table.
   */
  function syncSelectedTableOrderFromServer(page, opts) {
    opts = opts || {};
    if (!page || state.invoiceGenerated) return;
    if (state.dirty && state.lines.length) return;
    var table = String(
      state.tableForOrder ||
        state.resumeTableValue ||
        fieldValue('pos-inv-table', page) ||
        ''
    ).trim();
    if (!table) return;
    resumeOrderForTable(page, table, {
      silent: opts.silent !== false,
      notFound: opts.notFound
    });
  }

  /** Resume any saved invoice by id — Tables Invoice hub "View". */
  function resumeOrderById(page, invoiceId, opts) {
    var id = String(invoiceId || '').trim();
    if (!id) return;
    fetch(INVOICE_API + '/' + encodeURIComponent(id), {
      credentials: 'same-origin',
      headers: { Accept: 'application/json' }
    })
      .then(function (res) {
        return res
          .json()
          .then(function (data) {
            return { ok: res.ok, data: data || {} };
          })
          .catch(function () {
            return { ok: false, data: {} };
          });
      })
      .then(function (result) {
        if (result.ok && result.data && result.data.ok && result.data.invoice) {
          hydrateFromInvoice(page, result.data.invoice);
          return;
        }
        toast((result.data && result.data.error) || 'Could not open that invoice.');
        if (opts && typeof opts.notFound === 'function') opts.notFound();
      })
      .catch(function () {
        toast('Could not open that invoice. Check your connection.');
        if (opts && typeof opts.notFound === 'function') opts.notFound();
      });
  }

  /** Picking an occupied table from the header chip resumes its open order
   *  inline rather than starting a new bill for a different party. */
  function posInvTableChanged(root, value, label) {
    var page = document.getElementById('pos-invoice-page');
    if (!page) return;

    var prevValue = state.resumeTableValue;
    var prevLabel = state.resumeTableLabel;
    var status = value ? selectedTableStatus(page) : '';

    if (state.invoiceGenerated) {
      var current = state.resumeTableValue || state.tableForOrder || '';
      if (!value || String(value).toLowerCase() === String(current).toLowerCase()) {
        return;
      }
      var lockedStatus = selectedTableStatus(page);
      if (tableBlocksNewBill(lockedStatus)) {
        state.resumeTableValue = value;
        state.resumeTableLabel = label;
        resumeOrderForTable(page, value, {
          notFound: function () {
            resetOrderSession(page, { tableValue: value, tableLabel: label });
          }
        });
        return;
      }
      // Generated bill stays on its table; open a blank session on the free table.
      resetOrderSession(page, { tableValue: value, tableLabel: label });
      return;
    }

    if (!value) {
      state.resumeTableValue = '';
      state.resumeTableLabel = 'Select table…';
      return;
    }
    status = selectedTableStatus(page);
    if (!tableBlocksNewBill(status)) {
      var hasExistingOrder = !!(state.invoiceId || state.orderNo || state.tableForOrder);
      var switchingAway =
        hasExistingOrder &&
        String(value).toLowerCase() !== String(state.tableForOrder || '').toLowerCase();
      if (switchingAway) {
        // Leave current order on its table (flush if dirty), then open a blank bill.
        // No confirm — staff expect the chip change to apply immediately.
        var assignFree = function () {
          resetOrderSession(page, { tableValue: value, tableLabel: label });
          /* Another terminal may already have an open bill even if the floor
             badge still says available — probe before staying on a blank draft. */
          syncSelectedTableOrderFromServer(page, { silent: false });
        };
        flushLeavingTableOrder(page, { silent: true }).then(assignFree, assignFree);
        return;
      }
      state.resumeTableValue = value;
      state.resumeTableLabel = label;
      state.tableForOrder = value;
      persistInvoiceResumeContext();
      /* Table chosen after items were added — kick autosave so leave/resume works. */
      if (state.lines.length) {
        markOrderDirty(page);
        return;
      }
      /* Floor lag / other browser: always ask by-table even when badge is free. */
      syncSelectedTableOrderFromServer(page, { silent: false });
      return;
    }
    var switchingTable = String(value).toLowerCase() !== String(state.tableForOrder || '').toLowerCase();
    function startBlankOnTable() {
      /* Stale Occupied with no open bill — free the local badge so autosave can run. */
      markFloorTableAvailableLocal(value);
      refreshFloorTables(page, { preserveTable: value });
      resetOrderSession(page, { tableValue: value, tableLabel: label });
    }
    function resumeOccupied() {
      state.resumeTableValue = value;
      state.resumeTableLabel = label;
      resumeOrderForTable(page, value, {
        notFound: startBlankOnTable
      });
    }
    /* Save current bill on its table first, then load the destination order. */
    if (switchingTable && state.lines.length) {
      flushLeavingTableOrder(page, { silent: true }).then(resumeOccupied, resumeOccupied);
      return;
    }
    resumeOccupied();
  }

  function updateSettleBillButton(page) {
    var btn = $('#pos-inv-settle-bill', page) || $('#pos-inv-close-table', page);
    if (!btn) return;
    btn.hidden = !(
      state.invoiceGenerated &&
      state.invoiceId &&
      state.lines &&
      state.lines.length
    );
  }

  function guardInvoiceLocked(actionLabel) {
    if (!state.invoiceGenerated) return false;
    toast(
      actionLabel
        ? 'Invoice already generated. Settle the bill to continue.'
        : 'Invoice already generated. Settle the bill to continue.'
    );
    return true;
  }

  function syncInvoiceGeneratedUi(page) {
    if (!page) page = document.getElementById('pos-invoice-page');
    if (!page) return;
    page.classList.toggle('is-invoice-generated', !!state.invoiceGenerated);

    var genBtn = $('#pos-inv-send-customer', page) || page.querySelector('[data-inv-action="send"]');
    if (genBtn) {
      genBtn.hidden = !!state.invoiceGenerated;
      genBtn.disabled = !!state.invoiceGenerated;
    }

    var search = $('#pos-inv-search', page);
    if (search) {
      search.disabled = !!state.invoiceGenerated;
      search.readOnly = !!state.invoiceGenerated;
      if (state.invoiceGenerated) search.blur();
    }

    var lockSelectors = [
      '#pos-inv-customer-name',
      '#pos-inv-customer-mobile',
      '#pos-inv-notes',
      '#pos-inv-captain-trigger',
      '#pos-inv-order-type-header-trigger',
      '#pos-inv-save',
      '#pos-inv-more-btn'
    ];
    lockSelectors.forEach(function (sel) {
      var el = $(sel, page) || document.querySelector(sel);
      if (el) el.disabled = !!state.invoiceGenerated;
    });

    /* Table picker stays clickable — staff can open the list and jump to another
       table's open order even while the current bill is locked until settle. */
    var tableTrigger = $('#pos-inv-table-trigger', page);
    if (tableTrigger) tableTrigger.disabled = false;

    var sendKotBtn = $('#pos-inv-send-kot', page);
    if (sendKotBtn) {
      var hasPendingKot = pendingKotLines().length > 0;
      sendKotBtn.disabled = !hasPendingKot;
    }

    page.querySelectorAll('[data-inv-action="discount"], [data-inv-action="service"], [data-inv-action="tip"], [data-inv-action="coupon"], [data-inv-action="add-custom"], [data-inv-action="clear"], [data-inv-action="duplicate"], [data-inv-action="hold"]').forEach(function (el) {
      el.disabled = !!state.invoiceGenerated;
      if (state.invoiceGenerated) el.setAttribute('aria-disabled', 'true');
      else el.removeAttribute('aria-disabled');
    });

    updateSettleBillButton(page);
    renderLines(page);
  }

  function markInvoiceGenerated(page, invoice) {
    state.invoiceGenerated = true;
    if (invoice && invoice.id) state.invoiceId = invoice.id;
    cancelAutosaveTimer();
    state.dirty = false;
    syncInvoiceGeneratedUi(page);
    persistInvoiceResumeContext();
    /* Floor tile frees on Generate Invoice — do not wait for Settle. */
    var table = String(
      (invoice && (invoice.table_label || invoice.table)) ||
        state.tableForOrder ||
        state.resumeTableValue ||
        (page && fieldValue('pos-inv-table', page)) ||
        ''
    ).trim();
    if (table) {
      markFloorTableAvailableLocal(table);
      if (page && floorTablesCache) applyFloorTablesToUi(page, floorTablesCache);
      refreshFloorTables(page, { preserveTable: table });
    }
  }

  /** Reset the on-screen session to a fresh, blank order — used after Settle
   *  Bill so staff isn't left staring at a closed bill. */
  function resetOrderSession(page, opts) {
    opts = opts || {};
    var nextTable = opts.tableValue != null ? String(opts.tableValue) : '';
    var nextLabel = opts.tableLabel != null ? String(opts.tableLabel) : (nextTable || 'Select table…');
    state.lines = [];
    state.discountType = 'pct';
    state.discountValue = 0;
    state.discountLineUids = [];
    state.discountReason = '';
    state.discountSelectMode = null;
    state.discountSelectDraft = [];
    state.tipAmount = 0;
    state.tipEmployeeId = '';
    state.tipNote = '';
    state.tipPayrollId = null;
    state.serviceType = 'pct';
    state.serviceValue = DEFAULT_SERVICE_PCT;
    state.couponCode = '';
    state.orderNo = '';
    state.localId = '';
    state.lineSeq = 0;
    state.invoiceId = null;
    state.invoiceGenerated = false;
    state.tableForOrder = '';
    state.customerActiveIndex = -1;
    state.dirty = false;
    cancelAutosaveTimer();
    state.adjDraft = { discount: 'pct', service: 'pct' };
    initMeta(page);
    var nameEl = $('#pos-inv-customer-name', page);
    if (nameEl) {
      nameEl.value = DEFAULT_AUTOSAVE_CUSTOMER;
      nameEl.disabled = false;
    }
    var mobileEl = $('#pos-inv-customer-mobile', page);
    if (mobileEl) {
      mobileEl.value = '';
      mobileEl.disabled = false;
    }
    var notesEl = $('#pos-inv-notes', page);
    if (notesEl) {
      notesEl.value = '';
      notesEl.disabled = false;
      updateNotesCount(page);
    }
    setListboxValue('pos-inv-table', nextTable, nextLabel || 'Select table…');
    state.resumeTableValue = nextTable;
    state.resumeTableLabel = nextLabel || 'Select table…';
    if (nextTable) {
      state.tableForOrder = nextTable;
      persistInvoiceResumeContext();
    } else {
      clearInvoiceResumeContext();
    }
    renderLines(page);
    syncInvoiceGeneratedUi(page);
    loadFloorTables(function (tables) {
      populateTables(page, tables, { loading: false });
      if (nextTable) {
        setListboxValue('pos-inv-table', nextTable, nextLabel || nextTable);
        state.resumeTableValue = nextTable;
        state.resumeTableLabel = nextLabel || nextTable;
        persistInvoiceResumeContext();
      }
      if (typeof global.initEpListboxes === 'function') global.initEpListboxes();
    });
  }

  function settleBillTotal() {
    return Math.round((Number(calcTotals().total) || 0) * 100) / 100;
  }

  function closeSettleModal() {
    if (typeof global.closePosSettleModal === 'function') {
      global.closePosSettleModal();
    }
  }

  function openSettleBillModal(page) {
    if (!isBrowserOnline()) {
      toast('Settle Bill requires an internet connection.');
      return;
    }
    if (state.invoiceGenerated && !state.invoiceId) {
      toast('Sync required before settle. Reconnect to the network.');
      return;
    }
    if (!state.invoiceGenerated) {
      toast('Generate the invoice before settling the bill.');
      return;
    }
    if (!state.invoiceId) {
      toast('Save the order before settling the bill.');
      return;
    }
    if (!state.lines.length) {
      toast('Add at least one item before settling.');
      return;
    }
    if (typeof global.openPosSettleModal !== 'function') {
      toast('Settle dialog is not available.');
      return;
    }
    var headerBtn = $('#pos-inv-settle-bill', page) || $('#pos-inv-close-table', page);
    global.openPosSettleModal({
      invoiceId: state.invoiceId,
      orderNo: state.orderNo || '—',
      tableLabel: fieldValue('pos-inv-table', page) || '',
      grandTotal: settleBillTotal(),
      apiBase: (INVOICE_API || '').replace(/\/api\/invoices\/?$/, '') || undefined,
      onSettled: function (settledInvoice, meta) {
        var outlet = (page && page.getAttribute('data-pos-outlet')) || undefined;
        if (
          global.hbePosPrinterPrefs &&
          global.hbePosPrinterPrefs.shouldAutoPrintReceiptOnSettle(outlet)
        ) {
          printCustomerBill(page, settledInvoice, { autoPrint: true });
        }
        var table = (meta && meta.tableLabel) || fieldValue('pos-inv-table', page);
        if (table && markFloorTableAvailableLocal(table)) {
          applyFloorTablesToUi(page, floorTablesCache);
        }
        refreshFloorTables(page);
        toast(
          table
            ? 'Bill settled. ' + table + ' is now available.'
            : 'Bill settled successfully.'
        );
        resetOrderSession(page);
        if (headerBtn) headerBtn.disabled = false;
        updateSettleBillButton(page);
      }
    });
  }

  function bindSettleBillModal(page) {
    if (typeof global.bindPosSettleModal === 'function') {
      global.bindPosSettleModal();
    }
  }
  function clearMoreMenuPosition(menu) {
    if (!menu) return;
    menu.removeAttribute('data-pos-fixed');
    menu.style.position = '';
    menu.style.top = '';
    menu.style.left = '';
    menu.style.right = '';
    menu.style.minWidth = '';
    menu.style.zIndex = '';
  }

  function positionMoreMenu(page) {
    var btn = $('#pos-inv-more-btn', page);
    var menu = $('#pos-inv-more-menu', page);
    if (!btn || !menu || menu.hidden) return;
    var rect = btn.getBoundingClientRect();
    var width = Math.max(180, Math.ceil(rect.width));
    /* Prefer right-align under the trigger; if that would cover neighbors, clamp to viewport */
    var left = Math.min(
      Math.max(8, rect.right - width),
      Math.max(8, window.innerWidth - width - 8)
    );
    menu.setAttribute('data-pos-fixed', '1');
    menu.style.position = 'fixed';
    menu.style.top = (rect.bottom + 6) + 'px';
    menu.style.left = left + 'px';
    menu.style.right = 'auto';
    menu.style.minWidth = width + 'px';
    menu.style.zIndex = '10120';
  }

  function closeMoreMenu(page) {
    var menu = $('#pos-inv-more-menu', page);
    var btn = $('#pos-inv-more-btn', page);
    if (menu) {
      menu.hidden = true;
      clearMoreMenuPosition(menu);
    }
    if (btn) btn.setAttribute('aria-expanded', 'false');
  }

  function closeInvoiceListboxes() {
    if (typeof global.closeAllEpListboxes === 'function') {
      global.closeAllEpListboxes();
      return;
    }
    var page = document.getElementById('pos-invoice-page');
    if (!page) return;
    page.querySelectorAll('[data-se-listbox].is-open').forEach(function (root) {
      root.classList.remove('is-open');
      var trigger = root.querySelector('.se-filter-chip-trigger');
      var list = root.querySelector('.se-filter-listbox');
      if (trigger) trigger.setAttribute('aria-expanded', 'false');
      if (list) list.hidden = true;
    });
  }

  function openMoreMenu(page) {
    var menu = $('#pos-inv-more-menu', page);
    var btn = $('#pos-inv-more-btn', page);
    if (!menu || !btn) return;
    closeInvoiceListboxes();
    menu.hidden = false;
    btn.setAttribute('aria-expanded', 'true');
    positionMoreMenu(page);
  }

  function modalId(kind) {
    return 'pos-inv-' + kind + '-modal';
  }

  function closeInvModal(page, kind) {
    var modal = $('#' + modalId(kind), page);
    if (modal) modal.hidden = true;
  }

  function closeAllInvModals(page) {
    persistLineNoteFromModal(page);
    INV_MODALS.forEach(function (kind) {
      closeInvModal(page, kind);
    });
  }

  function openInvModal(page, kind) {
    closeAllInvModals(page);
    var modal = $('#' + modalId(kind), page);
    if (!modal) return;
    modal.hidden = false;
  }

  function updateLineNoteCount(page) {
    var textEl = $('#pos-inv-line-note-text', page);
    var countEl = $('#pos-inv-line-note-count', page);
    if (!countEl) return;
    var len = textEl ? String(textEl.value || '').length : 0;
    countEl.textContent = len + ' / ' + NOTES_MAX;
  }

  function openLineNoteModal(page, line) {
    if (!line) return;
    var uidEl = $('#pos-inv-line-note-uid', page);
    var textEl = $('#pos-inv-line-note-text', page);
    if (uidEl) uidEl.value = line.uid || '';
    if (textEl) {
      textEl.value = String(line.notes || '');
      textEl.setAttribute('maxlength', String(NOTES_MAX));
    }
    updateLineNoteCount(page);
    openInvModal(page, 'line-note');
    if (textEl) {
      setTimeout(function () {
        textEl.focus();
        textEl.setSelectionRange(textEl.value.length, textEl.value.length);
      }, 0);
    }
  }

  function applyLineNoteModal(page, clear) {
    var uidEl = $('#pos-inv-line-note-uid', page);
    var textEl = $('#pos-inv-line-note-text', page);
    var uid = uidEl ? String(uidEl.value || '') : '';
    if (!uid) {
      closeInvModal(page, 'line-note');
      return;
    }
    var line = null;
    var i;
    for (i = 0; i < state.lines.length; i++) {
      if (state.lines[i].uid === uid) {
        line = state.lines[i];
        break;
      }
    }
    if (!line) {
      closeInvModal(page, 'line-note');
      return;
    }
    var notes = clear ? '' : String(textEl ? textEl.value || '' : '').trim().slice(0, NOTES_MAX);
    var prev = String(line.notes || '').trim();
    line.notes = notes;
    closeInvModal(page, 'line-note');
    if (prev === notes) {
      renderLines(page);
      return;
    }
    renderLines(page);
    markOrderDirty(page);
    toast(notes ? 'Item note saved.' : 'Item note cleared.');
  }

  function persistLineNoteFromModal(page) {
    var modal = $('#' + modalId('line-note'), page);
    if (!modal || modal.hidden) return;
    applyLineNoteModal(page, false);
  }

  function syncAdjTypeUi(page, kind, type) {
    state.adjDraft[kind] = type === 'inr' ? 'inr' : 'pct';
    var modal = $('#' + modalId(kind), page);
    if (!modal) return;
    modal.querySelectorAll('[data-inv-adj-for="' + kind + '"]').forEach(function (btn) {
      btn.classList.toggle('is-active', btn.getAttribute('data-inv-adj-type') === state.adjDraft[kind]);
    });
    var label = $('#pos-inv-' + kind + '-amount-label', page);
    if (label) {
      label.textContent = state.adjDraft[kind] === 'inr' ? 'Amount (₹)' : 'Amount (%)';
    }
    updateAdjPreview(page, kind);
    if (kind === 'discount') syncDiscountReasonUi(page);
  }

  var DISCOUNT_REASON_PCT = 15;

  function effectiveDiscountPercent(type, value) {
    var n = Number(value);
    if (isNaN(n) || n <= 0) return 0;
    if (type === 'pct') return Math.min(100, n);
    var scoped = normalizeDiscountLineUids(state.discountLineUids);
    var base = scoped.length ? discountBaseForLines(scoped) : 0;
    if (!(base > 0)) {
      var sub = calcTotals({ discountType: 'pct', discountValue: 0 }).subtotal;
      base = Number(sub) || 0;
    }
    if (!(base > 0)) return 0;
    var amount = calcAdjAmount(base, 'inr', n);
    if (amount > base) amount = base;
    return Math.round((amount / base) * 10000) / 100;
  }

  function ensureDiscountReasonField() {
    var field = document.getElementById('pos-inv-discount-reason-field');
    if (field) return field;
    var preview = document.getElementById('pos-inv-discount-preview');
    var actions = document.querySelector('#pos-inv-discount-modal .pos-inv-modal-actions');
    if (!preview || !actions) return null;
    field = document.createElement('label');
    field.className = 'pos-inv-field';
    field.id = 'pos-inv-discount-reason-field';
    field.setAttribute('hidden', '');
    field.innerHTML =
      '<span>Reason <span class="pos-inv-summary-muted" id="pos-inv-discount-reason-hint">(required over 15%)</span></span>' +
      '<input type="text" id="pos-inv-discount-reason" maxlength="200" placeholder="Why is this discount over 15%?" autocomplete="off" disabled>';
    preview.insertAdjacentElement('afterend', field);
    return field;
  }

  function discountNeedsReason(type, value) {
    var n = Number(value);
    if (isNaN(n) || n <= 0) return false;
    if ((type || 'pct') === 'pct') return n > DISCOUNT_REASON_PCT;
    return effectiveDiscountPercent('inr', n) > DISCOUNT_REASON_PCT;
  }

  function syncDiscountReasonUi(page) {
    var field = ensureDiscountReasonField();
    var reasonEl = document.getElementById('pos-inv-discount-reason');
    var amountEl =
      (page && page.querySelector ? page.querySelector('#pos-inv-discount-amount') : null) ||
      document.getElementById('pos-inv-discount-amount');
    if (!field || !reasonEl) return;
    var type = (state.adjDraft && state.adjDraft.discount) || 'pct';
    var raw = amountEl ? String(amountEl.value || '').trim() : '';
    var value = raw === '' ? 0 : Number(raw);
    if (isNaN(value) || value < 0) value = 0;
    var needs = discountNeedsReason(type, value);
    reasonEl.disabled = !needs;
    reasonEl.required = needs;
    field.classList.toggle('is-shown', needs);
    field.classList.toggle('is-required', needs);
    field.classList.toggle('is-enabled', needs);
    /* Inline !important beats cached CSS that only has display:none. */
    if (needs) {
      field.removeAttribute('hidden');
      field.style.setProperty('display', 'flex', 'important');
      field.style.setProperty('flex-direction', 'column', 'important');
      field.style.setProperty('gap', '6px', 'important');
      field.style.setProperty('margin-bottom', '14px', 'important');
    } else {
      field.setAttribute('hidden', '');
      field.style.setProperty('display', 'none', 'important');
      reasonEl.value = '';
    }
    if (needs && !String(reasonEl.value || '').trim() && state.discountReason) {
      reasonEl.value = state.discountReason;
    }
  }

  function updateAdjPreview(page, kind) {
    var amountEl = $('#pos-inv-' + kind + '-amount', page);
    var preview = $('#pos-inv-' + kind + '-preview', page);
    if (!amountEl || !preview) return;
    var type = state.adjDraft[kind] || 'pct';
    var value = Number(amountEl.value);
    if (isNaN(value) || value < 0) value = 0;
    var override = {};
    if (kind === 'discount') {
      override.discountType = type;
      override.discountValue = value;
    } else if (kind === 'service') {
      override.serviceType = type;
      override.serviceValue = value;
    }
    var t = calcTotals(override);
    if (kind === 'discount') {
      var scopeHint =
        t.discountItemCount > 0
          ? ' on ' + t.discountItemCount + (t.discountItemCount === 1 ? ' item' : ' items')
          : '';
      preview.textContent = 'Discount: ' + money(t.discount) + scopeHint;
      syncDiscountReasonUi(page);
    } else if (kind === 'service') {
      preview.textContent = 'Service charge: ' + money(t.service);
    }
  }

  function syncDiscountSelectUi(page) {
    var root = page || document.getElementById('pos-invoice-page');
    if (!root) return;
    var selecting = !!state.discountSelectMode;
    root.classList.toggle('is-discount-selecting', selecting);
    var bar = $('#pos-inv-discount-select-bar', root);
    if (bar) bar.hidden = !selecting;
    var selectTh = root.querySelector('#pos-inv-table-lines thead .pos-inv-col-select');
    if (selectTh) selectTh.hidden = !selecting;
    var copy = $('#pos-inv-discount-select-copy', root);
    if (copy) {
      var n = (state.discountSelectDraft || []).length;
      var kind = state.discountSelectMode === 'coupon' ? 'coupon' : 'discount';
      copy.textContent =
        n > 0
          ? n + (n === 1 ? ' item' : ' items') + ' selected for ' + kind
          : 'Select items for ' + kind;
    }
    var cont = $('#pos-inv-discount-select-continue', root);
    if (cont) cont.disabled = !(state.discountSelectDraft || []).length;
  }

  function exitDiscountSelectMode(page, opts) {
    var keepRender = opts && opts.keepRender;
    state.discountSelectMode = null;
    state.discountSelectDraft = [];
    if (!keepRender) renderLines(page || document.getElementById('pos-invoice-page'));
    else syncDiscountSelectUi(page || document.getElementById('pos-invoice-page'));
  }

  function beginDiscountSelectMode(page, mode) {
    if (!state.lines.length) {
      toast('Add items before applying a ' + (mode === 'coupon' ? 'coupon' : 'discount') + '.');
      return;
    }
    state.discountSelectMode = mode === 'coupon' ? 'coupon' : 'discount';
    pruneDiscountLineUids();
    if (state.discountLineUids.length) {
      state.discountSelectDraft = state.discountLineUids.slice();
    } else {
      state.discountSelectDraft = state.lines.map(function (line) {
        return String(line.uid);
      });
    }
    renderLines(page);
    var bar = $('#pos-inv-discount-select-bar', page);
    if (bar) {
      try {
        bar.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      } catch (err) {}
    }
  }

  function setDiscountSelectAll(page, selected) {
    if (selected) {
      state.discountSelectDraft = state.lines.map(function (line) {
        return String(line.uid);
      });
    } else {
      state.discountSelectDraft = [];
    }
    renderLines(page);
  }

  function toggleDiscountSelectUid(page, uid, force) {
    var key = String(uid || '');
    if (!key) return;
    var draft = normalizeDiscountLineUids(state.discountSelectDraft);
    var idx = draft.indexOf(key);
    var shouldSelect = force == null ? idx === -1 : !!force;
    if (shouldSelect && idx === -1) draft.push(key);
    if (!shouldSelect && idx !== -1) draft.splice(idx, 1);
    state.discountSelectDraft = draft;
    renderLines(page);
  }

  function continueDiscountSelectMode(page) {
    var draft = normalizeDiscountLineUids(state.discountSelectDraft);
    if (!draft.length) {
      toast('Select at least one item.');
      return;
    }
    var mode = state.discountSelectMode;
    state.discountLineUids = draft.slice();
    /* Selecting every line keeps whole-bill semantics. */
    if (state.discountLineUids.length >= state.lines.length) {
      state.discountLineUids = [];
    }
    exitDiscountSelectMode(page);
    if (mode === 'coupon') openCouponModal(page);
    else openDiscountModal(page);
  }

  function openCustomModal(page) {
    openInvModal(page, 'custom');
    var name = $('#pos-inv-custom-name', page);
    var rate = $('#pos-inv-custom-rate', page);
    if (name) {
      name.value = '';
      name.focus();
    }
    if (rate) rate.value = '0';
  }

  function closeCustomModal(page) {
    closeInvModal(page, 'custom');
  }

  function openDiscountModal(page) {
    openInvModal(page, 'discount');
    var amount = $('#pos-inv-discount-amount', page);
    var reasonEl = $('#pos-inv-discount-reason', page);
    syncAdjTypeUi(page, 'discount', state.discountType || 'pct');
    if (amount) {
      /* Always start blank — staff must enter the discount each time. */
      amount.value = '';
      amount.focus();
    }
    if (reasonEl) reasonEl.value = '';
    updateAdjPreview(page, 'discount');
    syncDiscountReasonUi(page);
  }

  function openServiceModal(page) {
    openInvModal(page, 'service');
    var amount = $('#pos-inv-service-amount', page);
    syncAdjTypeUi(page, 'service', state.serviceType);
    if (amount) {
      amount.value = String(state.serviceValue || 0);
      amount.focus();
      amount.select();
    }
    updateAdjPreview(page, 'service');
  }

  function tipConfig(page) {
    var root = page || document.getElementById('pos-invoice-page');
    if (!root) return {};
    return {
      company: root.getAttribute('data-tip-company') || 'HBE',
      location: root.getAttribute('data-tip-location') || 'Restaurant',
      addUrl: root.getAttribute('data-tip-add-url') || '/sales_update/add_tip',
      editUrl: root.getAttribute('data-tip-edit-url') || '/sales_update/edit_tip',
      deleteUrl: root.getAttribute('data-tip-delete-url') || '/sales_update/delete_tip'
    };
  }

  function setTipError(page, msg) {
    var err = $('#pos-inv-tip-error', page);
    if (!err) return;
    if (msg) {
      err.textContent = msg;
      err.hidden = false;
      err.classList.add('is-visible');
    } else {
      err.textContent = '';
      err.hidden = true;
      err.classList.remove('is-visible');
    }
  }

  function todayIsoLocal() {
    var d = new Date();
    var m = String(d.getMonth() + 1);
    var day = String(d.getDate());
    if (m.length < 2) m = '0' + m;
    if (day.length < 2) day = '0' + day;
    return d.getFullYear() + '-' + m + '-' + day;
  }

  function bindZeroClearAmountInput(input) {
    if (!input || input.getAttribute('data-zero-clear-bound') === '1') return;
    input.setAttribute('data-zero-clear-bound', '1');
    function clearZero() {
      if (Number(input.value || 0) === 0) input.value = '';
    }
    input.addEventListener('focus', clearZero);
    input.addEventListener('click', clearZero);
    input.addEventListener('blur', function () {
      if (String(input.value || '').trim() === '') input.value = '0';
    });
  }

  function openTipModal(page) {
    openInvModal(page, 'tip');
    setTipError(page, '');
    var amount = $('#pos-inv-tip-amount', page);
    var note = $('#pos-inv-tip-note', page);
    var emp = $('#pos-inv-tip-employee', page);
    bindZeroClearAmountInput(amount);
    if (amount) {
      amount.value = String(state.tipAmount || 0);
    }
    if (note) note.value = state.tipNote || '';
    if (typeof global.initEpListboxes === 'function') {
      try {
        global.initEpListboxes();
      } catch (err) {}
    }
    if (emp && typeof global.resetEpListbox === 'function') {
      var label = 'Select employee…';
      if (state.tipEmployeeId) {
        var opt = document.querySelector(
          '#pos-inv-tip-employee-list .se-filter-listbox-option[data-value="' +
            String(state.tipEmployeeId).replace(/"/g, '\\"') +
            '"]'
        );
        if (opt) {
          label =
            opt.getAttribute('data-label') ||
            (opt.textContent || '').replace(/\s+/g, ' ').trim() ||
            label;
        }
      }
      global.resetEpListbox('pos-inv-tip-employee', state.tipEmployeeId || '', label);
    } else if (emp) {
      emp.value = state.tipEmployeeId || '';
    }
    if (amount) {
      amount.focus();
    }
  }

  function persistTipToPayroll(page, amount, employeeId, note) {
    var cfg = tipConfig(page);
    var payload = {
      company: cfg.company,
      location: cfg.location,
      date: todayIsoLocal(),
      employee_id: employeeId,
      amount: amount,
      description: note || (state.orderNo ? 'POS tip ' + state.orderNo : 'POS tip')
    };
    var url = cfg.addUrl;
    var methodBody = payload;
    if (state.tipPayrollId) {
      url = cfg.editUrl;
      methodBody = Object.assign({}, payload, { id: state.tipPayrollId });
    }
    return fetch(url, {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json',
        'X-Requested-With': 'XMLHttpRequest'
      },
      body: JSON.stringify(methodBody)
    }).then(function (r) {
      return r.json().then(function (data) {
        return { ok: r.ok, data: data };
      });
    });
  }

  function deleteTipFromPayroll(page) {
    if (!state.tipPayrollId) return Promise.resolve({ ok: true, data: { ok: true } });
    var cfg = tipConfig(page);
    return fetch(cfg.deleteUrl, {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json',
        'X-Requested-With': 'XMLHttpRequest'
      },
      body: JSON.stringify({
        id: state.tipPayrollId,
        company: cfg.company,
        location: cfg.location,
        date: todayIsoLocal()
      })
    }).then(function (r) {
      return r.json().then(function (data) {
        return { ok: r.ok, data: data };
      });
    });
  }

  function applyTipModal(page) {
    var amountEl = $('#pos-inv-tip-amount', page);
    var noteEl = $('#pos-inv-tip-note', page);
    var empEl = $('#pos-inv-tip-employee', page);
    var applyBtn = $('#pos-inv-tip-apply', page);
    var n = amountEl ? Number(amountEl.value) : 0;
    if (isNaN(n) || n < 0) n = 0;
    var employeeId = empEl ? String(empEl.value || '').trim() : '';
    var note = noteEl ? String(noteEl.value || '').trim() : '';
    setTipError(page, '');

    if (n > 0 && !employeeId) {
      setTipError(page, 'Please select an employee for this tip.');
      return;
    }

    function finishLocal() {
      state.tipAmount = n;
      state.tipEmployeeId = n > 0 ? employeeId : '';
      state.tipNote = n > 0 ? note : '';
      if (n <= 0) state.tipPayrollId = null;
      closeInvModal(page, 'tip');
      renderSummary(page);
      toast(n ? 'Tip set to ' + money(n) : 'Tip cleared.');
    }

    if (applyBtn) applyBtn.disabled = true;

    var req;
    if (n > 0) {
      req = persistTipToPayroll(page, n, Number(employeeId), note);
    } else if (state.tipPayrollId) {
      req = deleteTipFromPayroll(page);
    } else {
      req = Promise.resolve({ ok: true, data: { ok: true } });
    }

    req
      .then(function (res) {
        if (!res.ok || !res.data || !res.data.ok) {
          throw new Error((res.data && res.data.error) || 'Could not save tip to payroll.');
        }
        if (n > 0) {
          if (res.data.tip_id) state.tipPayrollId = res.data.tip_id;
        } else {
          state.tipPayrollId = null;
        }
        finishLocal();
      })
      .catch(function (err) {
        setTipError(page, err.message || 'Could not save tip to payroll.');
      })
      .then(function () {
        if (applyBtn) applyBtn.disabled = false;
      });
  }

  function openCouponModal(page) {
    openInvModal(page, 'coupon');
    var code = $('#pos-inv-coupon-code', page);
    if (code) {
      code.value = state.couponCode || '';
      code.focus();
      code.select();
    }
  }

  function applyDiscountModal(page) {
    var amountEl = $('#pos-inv-discount-amount', page);
    var reasonEl = $('#pos-inv-discount-reason', page);
    var n = amountEl ? Number(amountEl.value) : 0;
    if (isNaN(n) || n < 0) n = 0;
    var type = state.adjDraft.discount || 'pct';
    if (type === 'pct' && n > 100) n = 100;
    var reason = reasonEl ? String(reasonEl.value || '').trim() : '';
    if (discountNeedsReason(type, n)) {
      if (!reason) {
        toast('Enter a reason for discounts over ' + DISCOUNT_REASON_PCT + '%.');
        syncDiscountReasonUi(page);
        if (reasonEl && !reasonEl.disabled) {
          reasonEl.focus();
        }
        return;
      }
    } else {
      reason = '';
    }
    state.discountType = type;
    state.discountValue = n;
    state.discountReason = reason;
    if (!n) {
      state.discountLineUids = [];
      state.discountReason = '';
    } else {
      pruneDiscountLineUids();
    }
    closeInvModal(page, 'discount');
    renderSummary(page);
    markOrderDirty(page);
    toast(n ? 'Discount applied.' : 'Discount cleared.');
  }

  function applyServiceModal(page) {
    var amountEl = $('#pos-inv-service-amount', page);
    var n = amountEl ? Number(amountEl.value) : 0;
    if (isNaN(n) || n < 0) n = 0;
    var type = state.adjDraft.service || 'pct';
    if (type === 'pct' && n > 100) n = 100;
    state.serviceType = type;
    state.serviceValue = n;
    closeInvModal(page, 'service');
    renderSummary(page);
    toast(n ? 'Service charge updated.' : 'Service charge cleared.');
  }

  function applyCouponModal(page) {
    var codeEl = $('#pos-inv-coupon-code', page);
    var code = codeEl ? String(codeEl.value || '').trim() : '';
    state.couponCode = code;
    pruneDiscountLineUids();
    closeInvModal(page, 'coupon');
    if (code) {
      renderSummary(page);
      markOrderDirty(page);
      toast('Coupon code saved. Validation is not configured yet.');
    } else {
      renderSummary(page);
      toast('Coupon cleared.');
    }
  }

  function fieldValue(fieldId, page) {
    var el = $('#' + fieldId, page) || document.getElementById(fieldId);
    return el ? String(el.value || '').trim() : '';
  }

  function collectOrderPayload(page) {
    var totals = calcTotals();
    var notesEl = $('#pos-inv-notes', page);
    var table =
      fieldValue('pos-inv-table', page) ||
      String(state.tableForOrder || '').trim() ||
      queryParam('table').trim();
    return {
      orderNo: state.orderNo,
      outlet: resolvePosOutlet(),
      savedAt: new Date().toISOString(),
      orderType: fieldValue('pos-inv-order-type-header', page) || fieldValue('pos-inv-order-type', page) || 'dine_in',
      table: table,
      captain: fieldValue('pos-inv-captain', page),
      customerName: fieldValue('pos-inv-customer-name', page),
      customerMobile: digitsOnly(fieldValue('pos-inv-customer-mobile', page), 10),
      notes: notesEl ? String(notesEl.value || '').trim() : '',
      lines: state.lines.map(function (line) {
        return {
          uid: line.uid,
          menuId: line.menuId,
          name: line.name,
          category: line.category || '',
          variant: line.variant || '',
          rate: Number(line.rate) || 0,
          qty: Number(line.qty) || 0,
          isLiquor: !!line.isLiquor || isLiquorLine(line),
          outlet: lineMenuOutlet(line),
          emoji: line.emoji || '',
          kotSentQty: Number(line.sentQty) || 0,
          notes: String(line.notes || '').trim()
        };
      }),
      discountType: state.discountType,
      discountValue: state.discountValue,
      discountLineUids: state.discountLineUids.slice(),
      discountReason: state.discountReason || '',
      serviceType: state.serviceType,
      serviceValue: state.serviceValue,
      tipAmount: state.tipAmount,
      couponCode: state.couponCode,
      totals: totals
    };
  }

  function selectedTableStatus(page) {
    var name = fieldValue('pos-inv-table', page);
    if (!name) return '';
    var tables = floorTablesCache || [];
    for (var i = 0; i < tables.length; i++) {
      if (String(tables[i].name || '').toLowerCase() === name.toLowerCase()) {
        return mapTableStatus(tables[i].status);
      }
    }
    return '';
  }

  /** Autosave open carts so line edits/deletes survive refresh.
   *  Dine-in needs a table; takeaway/delivery only after a server invoice exists.
   *  Empty carts use softDeleteSavedInvoice instead of POSTing zero lines. */
  function shouldAutosave(page) {
    if (state.invoiceGenerated) return false;
    if (!page || !state.lines.length) return false;
    var orderType =
      fieldValue('pos-inv-order-type-header', page) || fieldValue('pos-inv-order-type', page) || 'dine_in';
    if (orderType === 'dine_in') {
      if (!fieldValue('pos-inv-table', page)) return false;
      if (!state.invoiceId && tableBlocksNewBill(selectedTableStatus(page))) return false;
      return true;
    }
    return !!state.invoiceId;
  }

  function cancelAutosaveTimer() {
    if (autosaveTimer) {
      clearTimeout(autosaveTimer);
      autosaveTimer = null;
    }
  }

  /** Drop local binding to a removed server invoice; keep table selected for a fresh bill. */
  function abandonSavedInvoiceLocally(page) {
    var table = String(
      state.tableForOrder ||
        state.resumeTableValue ||
        (page && fieldValue('pos-inv-table', page)) ||
        ''
    ).trim();
    state.invoiceId = null;
    state.orderNo = '';
    state.localId = '';
    state.lineSeq = 0;
    state.dirty = false;
    cancelAutosaveTimer();
    if (page) initMeta(page);
    if (table) {
      markFloorTableAvailableLocal(table);
      state.tableForOrder = table;
      state.resumeTableValue = table;
      persistInvoiceResumeContext();
      if (page && floorTablesCache) {
        applyFloorTablesToUi(page, floorTablesCache);
      }
      if (page) refreshFloorTables(page, { preserveTable: table });
    } else {
      clearInvoiceResumeContext();
    }
  }

  /** When the cart is emptied, soft-delete the saved invoice so refresh does not restore it. */
  function softDeleteSavedInvoice(page) {
    var id = state.invoiceId;
    if (!id) {
      abandonSavedInvoiceLocally(page);
      return Promise.resolve({ ok: true, skipped: true });
    }
    cancelAutosaveTimer();
    if (!isBrowserOnline()) {
      toast('Reconnect to remove this order from the server. It may reappear until then.');
      abandonSavedInvoiceLocally(page);
      return Promise.resolve({ ok: false, offline: true });
    }
    return fetch(INVOICE_API + '/' + encodeURIComponent(id) + '/delete', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { Accept: 'application/json' }
    })
      .then(function (res) {
        return res
          .json()
          .then(function (data) {
            return { ok: res.ok && !!(data && data.ok), data: data || {} };
          })
          .catch(function () {
            return { ok: false, data: {} };
          });
      })
      .then(function (result) {
        if (!result.ok) {
          toast((result.data && result.data.error) || 'Could not remove order.');
          return result;
        }
        abandonSavedInvoiceLocally(page);
        return { ok: true };
      })
      .catch(function () {
        toast('Could not remove order.');
        return { ok: false };
      });
  }

  /** Persist remaining lines, or soft-delete when the cart is empty. */
  function persistAfterLineChange(page) {
    pruneDiscountLineUids();
    renderLines(page);
    if (state.lines.length) markOrderDirty(page);
    else softDeleteSavedInvoice(page);
  }

  function markOrderDirty(page) {
    if (state.invoiceGenerated) return;
    dirtyEpoch += 1;
    state.dirty = true;
    scheduleAutosave(page);
  }

  function clearDirtyAfterPersist(epochAtStart, page) {
    if (dirtyEpoch !== epochAtStart) {
      /* Edits landed while the request was in flight — keep dirty and retry. */
      state.dirty = true;
      scheduleAutosave(page);
      return;
    }
    state.dirty = false;
  }

  function scheduleAutosave(page) {
    cancelAutosaveTimer();
    if (!shouldAutosave(page)) return;
    autosaveTimer = setTimeout(function () {
      autosaveTimer = null;
      if (!state.dirty || !shouldAutosave(page)) return;
      persistOrder(page, { silent: true });
    }, AUTOSAVE_DELAY_MS);
  }

  function ensureDefaultCustomerName(page) {
    var nameEl = $('#pos-inv-customer-name', page);
    if (nameEl && !String(nameEl.value || '').trim()) {
      nameEl.value = DEFAULT_AUTOSAVE_CUSTOMER;
    }
  }

  /** Immediate persist of dirty dine-in lines (soft-nav leave / pagehide). */
  function flushDirtyOrder(page, opts) {
    cancelAutosaveTimer();
    if (!page || !state.dirty || !state.lines.length) {
      return Promise.resolve({ ok: true, skipped: true });
    }
    if (!shouldAutosave(page)) {
      return Promise.resolve({ ok: true, skipped: true });
    }
    return persistOrder(page, Object.assign({ silent: true }, opts || {}));
  }

  /** Persist the open cart on the table it belongs to — not the picker value the
   *  user just clicked (listbox updates the field before change handlers run). */
  function flushLeavingTableOrder(page, opts) {
    opts = opts || {};
    cancelAutosaveTimer();
    if (!page || !state.dirty || !state.lines.length) {
      return Promise.resolve({ ok: true, skipped: true });
    }
    if (state.invoiceGenerated) {
      return Promise.resolve({ ok: true, skipped: true });
    }
    var leaveTable = String(state.tableForOrder || state.resumeTableValue || '').trim();
    if (!leaveTable) {
      return Promise.resolve({ ok: true, skipped: true });
    }
    return persistOrder(page, Object.assign({ silent: true, tableOverride: leaveTable }, opts));
  }

  function persistOrder(page, opts) {
    opts = opts || {};
    if (state.invoiceGenerated && !opts.allowGenerated) {
      if (!opts.silent) guardInvoiceLocked();
      return Promise.resolve({ ok: false, locked: true });
    }
    var silent = !!opts.silent;
    var requireCustomer = opts.requireCustomer !== false && !silent;
    var toastOnSuccess = opts.toastOnSuccess != null ? !!opts.toastOnSuccess : !silent;
    var keepalive = !!opts.keepalive;

    if (!state.lines.length) {
      if (!silent) {
        toast('Add at least one item before saving.');
        var search = $('#pos-inv-search', page);
        if (search) search.focus();
      }
      return Promise.resolve({ ok: false, skipped: true });
    }

    var orderType =
      fieldValue('pos-inv-order-type-header', page) || fieldValue('pos-inv-order-type', page) || 'dine_in';
    if (orderType === 'dine_in' && !fieldValue('pos-inv-table', page)) {
      if (!silent) {
        toast('Select a table before saving.');
        var tableTrigger = $('#pos-inv-table-trigger', page) || document.getElementById('pos-inv-table-trigger');
        if (tableTrigger) tableTrigger.focus();
      }
      return Promise.resolve({ ok: false, skipped: true });
    }
    if (orderType === 'dine_in' && !state.invoiceId && tableBlocksNewBill(selectedTableStatus(page))) {
      if (!silent) {
        toast('This table is occupied. Choose another table or resume its order from the picker.');
      }
      return Promise.resolve({ ok: false, blocked: true });
    }

    var customerName = fieldValue('pos-inv-customer-name', page);
    if (!customerName) {
      if (requireCustomer) {
        toast('Enter customer name before saving.');
        var nameEl = $('#pos-inv-customer-name', page);
        if (nameEl) nameEl.focus();
        return Promise.resolve({ ok: false, skipped: true });
      }
      /* Payload-only fallback — do not write into the input (would clobber typing). */
      customerName = DEFAULT_AUTOSAVE_CUSTOMER;
    }

    if (!state.orderNo) initMeta(page);
    ensureLocalId();

    if (saveInflight) {
      return saveInflight.then(function () {
        if (state.dirty || opts.force) return persistOrder(page, opts);
        return { ok: true, skipped: true };
      });
    }

    var payload = collectOrderPayload(page);
    if (opts.tableOverride) payload.table = String(opts.tableOverride).trim();
    payload.customerName = customerName;
    payload.clientLocalId = state.localId;
    var epochAtStart = dirtyEpoch;

    var saveBtn = null;
    if (!silent) {
      saveBtn = $('#pos-inv-save', page) || page.querySelector('[data-inv-action="save"]');
      if (saveBtn) saveBtn.disabled = true;
    }

    if (!isBrowserOnline()) {
      saveInflight = queueOfflineSave(page, payload, {
        silent: silent,
        toastOnSuccess: toastOnSuccess,
        epochAtStart: epochAtStart
      })
        .then(function (outcome) {
          if (saveBtn) saveBtn.disabled = false;
          updateSettleBillButton(page);
          saveInflight = null;
          return outcome;
        });
      return saveInflight;
    }

    var api = offlineApi();
    var postFn =
      api && typeof api.tryPostWithConflictRetry === 'function'
        ? function (body) {
            return api.tryPostWithConflictRetry(body).then(function (result) {
              if (result.payloadUsed && result.payloadUsed.orderNo) {
                state.orderNo = result.payloadUsed.orderNo;
              }
              return result;
            });
          }
        : null;

    var networkPromise;
    if (postFn) {
      networkPromise = postFn(payload);
    } else {
      var fetchOpts = {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          Accept: 'application/json',
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(payload)
      };
      if (keepalive) fetchOpts.keepalive = true;
      networkPromise = fetch(INVOICE_API, fetchOpts)
        .then(function (res) {
          return res
            .json()
            .then(function (data) {
              return { ok: res.ok && !!(data && data.ok), data: data || {}, status: res.status };
            })
            .catch(function () {
              return { ok: false, data: {}, status: res.status };
            });
        });
    }

    saveInflight = networkPromise
      .then(function (result) {
        if (!result.ok || !(result.data && result.data.ok)) {
          if (result.authExpired) {
            if (!silent) toast('Session expired; reconnect to sync.');
            return { ok: false, error: 'auth' };
          }
          /* Network-shaped failure → queue offline. */
          if (!result.status || result.status >= 500 || result.network) {
            return queueOfflineSave(page, payload, {
              silent: silent,
              toastOnSuccess: toastOnSuccess,
              epochAtStart: epochAtStart
            });
          }
          if (!silent) {
            toast((result.data && result.data.error) || 'Could not save invoice.');
          } else if (result.status && result.status >= 400 && result.status < 500) {
            /* Surface validation errors during autosave (e.g. kitchen-line protection)
               so a deleted line that failed to persist is not silently restored on refresh. */
            toast((result.data && result.data.error) || 'Could not save invoice.');
          }
          return { ok: false, error: (result.data && result.data.error) || 'save failed' };
        }
        var invoice = result.data.invoice;
        var orderNo = (invoice && invoice.order_no) || payload.orderNo;
        if (invoice) {
          state.invoiceId = invoice.id;
          state.tableForOrder = invoice.table_label || invoice.table || state.tableForOrder;
          if (invoice.order_no) {
            state.orderNo = invoice.order_no;
            noteOutletOrderSeq(invoice.order_no);
          }
          syncOrderNoMeta(page);
          persistInvoiceResumeContext();
        }
        clearDirtyAfterPersist(epochAtStart, page);
        mirrorDraft(page, payload);
        syncFloorOccupancyAfterSave(page, payload, invoice);
        if (toastOnSuccess) toast('Order ' + orderNo + ' saved.');
        return { ok: true, invoice: invoice };
      })
      .catch(function () {
        return queueOfflineSave(page, payload, {
          silent: silent,
          toastOnSuccess: toastOnSuccess,
          epochAtStart: epochAtStart
        });
      })
      .then(function (outcome) {
        if (saveBtn) saveBtn.disabled = false;
        updateSettleBillButton(page);
        return outcome;
      })
      .then(
        function (outcome) {
          saveInflight = null;
          return outcome;
        },
        function (err) {
          saveInflight = null;
          throw err;
        }
      );

    return saveInflight;
  }

  function saveOrder(page) {
    persistOrder(page, { silent: false, requireCustomer: true, toastOnSuccess: true });
  }

  function registerInvoiceLeaveHooks() {
    /* Bridge to the latest IIFE so soft-nav script ?v= bumps do not stack
       duplicate handlers against orphaned closures. */
    global.__dePosInvoiceFlushDirty = function () {
      var page = document.getElementById('pos-invoice-page');
      if (!page) return Promise.resolve();
      return flushDirtyOrder(page, { silent: true });
    };
    global.__dePosInvoiceOnPageHide = function () {
      var page = document.getElementById('pos-invoice-page');
      if (!page || !state.dirty) return;
      flushDirtyOrder(page, { silent: true, keepalive: true });
    };
    if (global.__dePosInvoiceLeaveHooksBound) return;
    global.__dePosInvoiceLeaveHooksBound = true;

    var handlers = (global.__deBeforeSoftNavHandlers = global.__deBeforeSoftNavHandlers || []);
    handlers.push(function () {
      if (typeof global.__dePosInvoiceFlushDirty === 'function') {
        return global.__dePosInvoiceFlushDirty();
      }
    });

    global.addEventListener('pagehide', function () {
      if (typeof global.__dePosInvoiceOnPageHide === 'function') {
        global.__dePosInvoiceOnPageHide();
      }
    });
  }

  function handleAction(page, action) {
    if (!action) return;
    if (action === 'save') {
      if (guardInvoiceLocked()) return;
      saveOrder(page);
      return;
    }
    if (action === 'send-kot') {
      sendKot(page);
      return;
    }
    if (action === 'settle-bill' || action === 'close-table') {
      if (state.invoiceGenerated && !state.invoiceId) {
        toast('Sync required before settle. Reconnect to the network.');
        return;
      }
      openSettleBillModal(page);
      return;
    }
    if (action === 'print') {
      openToolbarPrintPage(page);
      return;
    }
    if (action === 'pdf') {
      toast('PDF download is not available yet.');
      return;
    }
    if (action === 'send') {
      sendToCustomer(page);
      return;
    }
    if (action === 'hold') {
      closeMoreMenu(page);
      if (guardInvoiceLocked()) return;
      toast('Order hold is not available yet.');
      return;
    }
    if (action === 'clear') {
      closeMoreMenu(page);
      if (guardInvoiceLocked()) return;
      var kept = [];
      if (!canEditKitchenSentLines(page)) {
        kept = state.lines.filter(function (line) {
          return lineHasKitchenSent(line);
        });
      }
      if (kept.length && kept.length === state.lines.length) {
        toast('Only an administrator can clear items after they were sent to the kitchen.');
        return;
      }
      state.lines = kept;
      if (state.lines.length) {
        toast('Unsent items cleared. Kitchen-sent items were kept.');
      } else {
        toast('All items cleared.');
      }
      persistAfterLineChange(page);
      return;
    }
    if (action === 'duplicate') {
      closeMoreMenu(page);
      if (guardInvoiceLocked()) return;
      toast('Duplicate order is not available yet.');
      return;
    }
    if (action === 'discount') {
      if (guardInvoiceLocked()) return;
      beginDiscountSelectMode(page, 'discount');
      return;
    }
    if (action === 'service') {
      if (guardInvoiceLocked()) return;
      openServiceModal(page);
      return;
    }
    if (action === 'tip') {
      if (guardInvoiceLocked()) return;
      openTipModal(page);
      return;
    }
    if (action === 'coupon') {
      if (guardInvoiceLocked()) return;
      beginDiscountSelectMode(page, 'coupon');
      return;
    }
    if (action === 'add-custom') {
      if (guardInvoiceLocked()) return;
      openCustomModal(page);
      return;
    }
    if (action === 'note-templates') {
      if (guardInvoiceLocked()) return;
      var notes = $('#pos-inv-notes', page);
      if (notes) {
        var snippet = 'Less spicy · Serve hot';
        var next = (notes.value ? notes.value + '\n' : '') + snippet;
        if (next.length > NOTES_MAX) next = next.slice(0, NOTES_MAX);
        notes.value = next;
        updateNotesCount(page);
        toast('Note template added.');
      }
    }
  }

  function updateNotesCount(page) {
    var notes = $('#pos-inv-notes', page);
    var count = $('#pos-inv-notes-count', page);
    if (!notes || !count) return;
    var len = String(notes.value || '').length;
    count.textContent = len + ' / ' + NOTES_MAX;
  }

  function fillCustomer(page, customer) {
    if (!customer) return;
    var name = $('#pos-inv-customer-name', page);
    var mobile = $('#pos-inv-customer-mobile', page);
    if (name) name.value = customer.name || '';
    if (mobile) mobile.value = digitsOnly(customer.mobile, 10);
    closeCustomerSuggest(page);
    if (state.lines.length || state.invoiceId) markOrderDirty(page);
    toast('Customer details filled.');
  }

  function customerSuggestTargets(page, mode) {
    if (mode === 'name') {
      return {
        box: $('#pos-inv-customer-name-suggest', page),
        input: $('#pos-inv-customer-name', page)
      };
    }
    return {
      box: $('#pos-inv-customer-suggest', page),
      input: $('#pos-inv-customer-mobile', page)
    };
  }

  function closeCustomerSuggest(page) {
    ['mobile', 'name'].forEach(function (mode) {
      var t = customerSuggestTargets(page, mode);
      if (t.box) {
        t.box.hidden = true;
        t.box.innerHTML = '';
      }
      if (t.input) t.input.setAttribute('aria-expanded', 'false');
    });
    state.customerActiveIndex = -1;
    state.customerSuggestMode = '';
  }

  function renderCustomerSuggest(page, results, mode) {
    mode = mode || state.customerSuggestMode || 'mobile';
    state.customerSuggestMode = mode;
    var other = mode === 'name' ? 'mobile' : 'name';
    var otherT = customerSuggestTargets(page, other);
    if (otherT.box) {
      otherT.box.hidden = true;
      otherT.box.innerHTML = '';
    }
    if (otherT.input) otherT.input.setAttribute('aria-expanded', 'false');

    var t = customerSuggestTargets(page, mode);
    if (!t.box) return;
    if (!results.length) {
      closeCustomerSuggest(page);
      return;
    }
    t.box.hidden = false;
    if (t.input) t.input.setAttribute('aria-expanded', 'true');
    t.box.innerHTML = results
      .map(function (c, idx) {
        return (
          '<button type="button" class="pos-inv-customer-opt' +
          (idx === state.customerActiveIndex ? ' is-active' : '') +
          '" role="option" data-customer-id="' +
          escapeHtml(c.id) +
          '">' +
          '<span class="pos-inv-customer-opt-name">' +
          escapeHtml(c.name) +
          '</span>' +
          '<span class="pos-inv-customer-opt-meta">+91 ' +
          escapeHtml(c.mobile) +
          '</span></button>'
        );
      })
      .join('');
  }

  function selectCustomer(page, customerId) {
    if (!customerId) return;
    var match = null;
    for (var i = 0; i < customerCache.length; i++) {
      if (String(customerCache[i].id) === String(customerId)) {
        match = customerCache[i];
        break;
      }
    }
    if (!match) return;
    fillCustomer(page, match);
  }

  function bindNotes(page) {
    var notes = $('#pos-inv-notes', page);
    if (!notes || notes.getAttribute('data-bound') === '1') return;
    notes.setAttribute('data-bound', '1');
    notes.setAttribute('maxlength', String(NOTES_MAX));
    notes.addEventListener('input', function () {
      updateNotesCount(page);
    });
    updateNotesCount(page);
  }

  function bindCustomer(page) {
    var card = $('.pos-inv-customer-card', page);
    if (!card || card.getAttribute('data-bound') === '1') return;
    card.setAttribute('data-bound', '1');

    card.addEventListener('click', function (e) {
      var opt = e.target.closest('.pos-inv-customer-opt');
      if (opt) {
        e.preventDefault();
        selectCustomer(page, opt.getAttribute('data-customer-id'));
      }
    });

    function bindCustomerField(input, mode) {
      if (!input) return;

      input.addEventListener('input', function () {
        if (mode === 'mobile') input.value = digitsOnly(input.value, 10);
        /* Persist name/mobile edits for open carts and resumed invoices so a
           renamed Guest sticks on the order and in Customer Master. */
        if (state.lines.length || state.invoiceId) markOrderDirty(page);
        if (customerSearchTimer) clearTimeout(customerSearchTimer);
        var query = String(input.value || '').trim();
        if (customerQueryKey(query).length < MIN_QUERY) {
          closeCustomerSuggest(page);
          return;
        }
        customerSearchTimer = setTimeout(function () {
          fetchCustomers(query, function (matches) {
            var current = String(input.value || '').trim();
            if (mode === 'mobile') {
              if (digitsOnly(current, 10) !== digitsOnly(query, 10)) return;
            } else if (current.toLowerCase() !== query.toLowerCase()) {
              return;
            }
            if (!matches.length) {
              closeCustomerSuggest(page);
              return;
            }
            state.customerActiveIndex = 0;
            renderCustomerSuggest(page, matches, mode);
          });
        }, 180);
      });

      input.addEventListener('keydown', function (e) {
        var t = customerSuggestTargets(page, mode);
        var open = t.box && !t.box.hidden;
        var items = open ? t.box.querySelectorAll('.pos-inv-customer-opt') : [];
        if (e.key === 'Escape') {
          if (open) {
            e.preventDefault();
            closeCustomerSuggest(page);
          }
          return;
        }
        if (!open || !items.length) return;
        if (e.key === 'ArrowDown') {
          e.preventDefault();
          state.customerActiveIndex = Math.min(items.length - 1, state.customerActiveIndex + 1);
          renderCustomerSuggest(page, searchCustomersLocal(input.value), mode);
          return;
        }
        if (e.key === 'ArrowUp') {
          e.preventDefault();
          state.customerActiveIndex = Math.max(0, state.customerActiveIndex - 1);
          renderCustomerSuggest(page, searchCustomersLocal(input.value), mode);
          return;
        }
        if (e.key === 'Enter') {
          e.preventDefault();
          var idx = state.customerActiveIndex >= 0 ? state.customerActiveIndex : 0;
          var btn = items[idx];
          if (btn) selectCustomer(page, btn.getAttribute('data-customer-id'));
        }
      });
    }

    bindCustomerField($('#pos-inv-customer-mobile', page), 'mobile');
    bindCustomerField($('#pos-inv-customer-name', page), 'name');

    if (!document.__posInvCustomerDocBound) {
      document.__posInvCustomerDocBound = true;
      document.addEventListener('click', function (e) {
        var root = document.getElementById('pos-invoice-page');
        if (!root) return;
        if (e.target.closest('#pos-inv-mobile-wrap') || e.target.closest('#pos-inv-name-wrap')) return;
        closeCustomerSuggest(root);
      });
    }
  }

  function bindSearch(page) {
    var wrap = $('#pos-inv-search-wrap', page);
    var input = $('#pos-inv-search', page);
    var clearBtn = $('#pos-inv-search-clear', page);
    if (!wrap || !input || wrap.getAttribute('data-bound') === '1') return;
    wrap.setAttribute('data-bound', '1');

    function refreshClear() {
      if (clearBtn) clearBtn.hidden = !String(input.value || '').length;
    }

    input.addEventListener('input', function () {
      refreshClear();
      var q = input.value;
      if (String(q).trim().length < MIN_QUERY) {
        closeSuggest(page);
        return;
      }
      state.activeIndex = 0;
      renderSuggest(page, searchMenu(q), q);
    });

    input.addEventListener('keydown', function (e) {
      var box = $('#pos-inv-suggest', page);
      var open = box && !box.hidden;
      var items = open ? box.querySelectorAll('.pos-inv-suggest-item') : [];
      if (e.key === 'Escape') {
        if (open) {
          e.preventDefault();
          closeSuggest(page);
        }
        return;
      }
      if (!open || !items.length) {
        if (e.key === 'Enter') e.preventDefault();
        return;
      }
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        state.activeIndex = Math.min(items.length - 1, state.activeIndex + 1);
        renderSuggest(page, searchMenu(input.value), input.value);
        return;
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        state.activeIndex = Math.max(0, state.activeIndex - 1);
        renderSuggest(page, searchMenu(input.value), input.value);
        return;
      }
      if (e.key === 'Enter') {
        e.preventDefault();
        var idx = state.activeIndex >= 0 ? state.activeIndex : 0;
        var btn = items[idx];
        if (btn) selectSuggestion(page, btn.getAttribute('data-menu-id'));
      }
    });

    wrap.addEventListener('click', function (e) {
      var opt = e.target.closest('.pos-inv-suggest-item');
      if (opt) {
        e.preventDefault();
        selectSuggestion(page, opt.getAttribute('data-menu-id'));
        return;
      }
      if (e.target.closest('#pos-inv-search-clear')) {
        input.value = '';
        refreshClear();
        closeSuggest(page);
        input.focus();
      }
    });

    if (!document.__posInvSuggestDocBound) {
      document.__posInvSuggestDocBound = true;
      document.addEventListener('click', function (e) {
        var root = document.getElementById('pos-invoice-page');
        if (!root) return;
        if (e.target.closest('#pos-inv-search-wrap')) return;
        closeSuggest(root);
      });
    }
  }

  function bindLines(page) {
    var body = $('#pos-inv-lines-body', page);
    if (!body || body.getAttribute('data-bound') === '1') return;
    body.setAttribute('data-bound', '1');
    body.addEventListener('click', function (e) {
      var row = e.target.closest('tr[data-line-id]');
      if (!row) return;
      var id = row.getAttribute('data-line-id');
      var line = null;
      var i;
      for (i = 0; i < state.lines.length; i++) {
        if (state.lines[i].uid === id) {
          line = state.lines[i];
          break;
        }
      }
      if (!line) return;
      if (state.discountSelectMode) {
        var checkEl = e.target.closest('[data-discount-check]');
        if (checkEl || e.target === row || e.target.closest('td')) {
          if (e.target.closest('[data-qty], [data-del], [data-line-note]')) return;
          var force = checkEl ? !!checkEl.checked : null;
          if (checkEl) {
            /* Native checkbox already toggled; sync draft to its new state. */
            toggleDiscountSelectUid(page, id, !!checkEl.checked);
          } else {
            toggleDiscountSelectUid(page, id, force);
          }
        }
        return;
      }
      if (e.target.closest('[data-line-note]')) {
        if (guardInvoiceLocked()) return;
        openLineNoteModal(page, line);
        return;
      }
      if (e.target.closest('[data-del]')) {
        if (guardInvoiceLocked()) return;
        if (lineHasKitchenSent(line) && !canEditKitchenSentLines(page)) {
          toast('Only an administrator can remove items after they were sent to the kitchen.');
          return;
        }
        state.lines = state.lines.filter(function (l) {
          return l.uid !== id;
        });
        persistAfterLineChange(page);
        return;
      }
      var qtyBtn = e.target.closest('[data-qty]');
      if (qtyBtn) {
        if (guardInvoiceLocked()) return;
        if (qtyBtn.disabled) return;
        var delta = Number(qtyBtn.getAttribute('data-qty')) || 0;
        var nextQty = Math.max(1, (Number(line.qty) || 1) + delta);
        var sentQty = lineKitchenSentQty(line);
        if (delta < 0 && sentQty > 0 && !canEditKitchenSentLines(page) && nextQty < sentQty) {
          toast('Only an administrator can reduce quantity below the amount already sent to kitchen.');
          return;
        }
        line.qty = nextQty;
        /* Never claim more units were sent to the kitchen than currently on the line. */
        if ((Number(line.sentQty) || 0) > line.qty) line.sentQty = line.qty;
        renderLines(page);
        markOrderDirty(page);
      }
    });
  }

  function bindHeader(page) {
    /* Soft-nav may reload a newer pos_invoice.js — refresh bridge closures each init. */
    document.__posInvOnListboxOpen = function (e) {
      var root = e && e.detail && e.detail.root;
      var pageRoot = document.getElementById('pos-invoice-page');
      if (!pageRoot) return;
      if (root && !pageRoot.contains(root)) return;
      closeMoreMenu(pageRoot);
    };
    global.posInvCloseMoreMenu = closeMoreMenu;
    global.posInvPositionMoreMenu = positionMoreMenu;
    global.posInvCloseCustomerSuggest = closeCustomerSuggest;
    global.posInvCloseAllModals = closeAllInvModals;

    if (page.getAttribute('data-header-bound') !== '1') {
      page.setAttribute('data-header-bound', '1');
      var moreBtn = $('#pos-inv-more-btn', page);
      if (moreBtn) {
        moreBtn.addEventListener('click', function (e) {
          e.stopPropagation();
          var menu = $('#pos-inv-more-menu', page);
          if (!menu) return;
          if (menu.hidden) openMoreMenu(page);
          else closeMoreMenu(page);
        });
      }
    }

    if (!document.__posInvActionClickBound) {
      document.__posInvActionClickBound = true;
      document.addEventListener('click', function (e) {
        var pageRoot = document.getElementById('pos-invoice-page');
        if (!pageRoot) return;
        var actionEl = e.target.closest('[data-inv-action]');
        if (actionEl && pageRoot.contains(actionEl)) {
          handleAction(pageRoot, actionEl.getAttribute('data-inv-action'));
        }
        if (!e.target.closest('.pos-inv-more-wrap')) {
          closeMoreMenu(pageRoot);
        }
      });
    }

    if (!document.__posInvMoreDocBound) {
      document.__posInvMoreDocBound = true;
      document.addEventListener('keydown', function (e) {
        if (e.key !== 'Escape') return;
        var root = document.getElementById('pos-invoice-page');
        if (!root) return;
        if (typeof global.posInvCloseMoreMenu === 'function') {
          global.posInvCloseMoreMenu(root);
        }
        if (typeof global.posInvCloseCustomerSuggest === 'function') {
          global.posInvCloseCustomerSuggest(root);
        }
        if (typeof global.posInvCloseAllModals === 'function') {
          global.posInvCloseAllModals(root);
        } else {
          closeAllInvModals(root);
        }
      });
      document.addEventListener('ep-listbox-opened', function (e) {
        if (typeof document.__posInvOnListboxOpen === 'function') {
          document.__posInvOnListboxOpen(e);
        }
      });
      window.addEventListener('resize', function () {
        var root = document.getElementById('pos-invoice-page');
        if (root && typeof global.posInvPositionMoreMenu === 'function') {
          global.posInvPositionMoreMenu(root);
        }
      });
      document.addEventListener('scroll', function () {
        var root = document.getElementById('pos-invoice-page');
        if (root && typeof global.posInvPositionMoreMenu === 'function') {
          global.posInvPositionMoreMenu(root);
        }
      }, true);
    }
  }

  function bindModal(page) {
    if (page.getAttribute('data-modals-bound') === '1') return;
    page.setAttribute('data-modals-bound', '1');

    page.addEventListener('click', function (e) {
      var closeEl = e.target.closest('[data-inv-modal-close]');
      if (closeEl && page.contains(closeEl)) {
        var kind = closeEl.getAttribute('data-inv-modal-close') || 'custom';
        if (kind === 'line-note') {
          persistLineNoteFromModal(page);
          return;
        }
        closeInvModal(page, kind);
        return;
      }
      var typeBtn = e.target.closest('[data-inv-adj-type][data-inv-adj-for]');
      if (typeBtn && page.contains(typeBtn)) {
        syncAdjTypeUi(
          page,
          typeBtn.getAttribute('data-inv-adj-for'),
          typeBtn.getAttribute('data-inv-adj-type')
        );
      }
    });

    page.addEventListener('input', function (e) {
      var t = e.target;
      if (!t || !page.contains(t)) return;
      if (t.id === 'pos-inv-discount-amount') {
        updateAdjPreview(page, 'discount');
        syncDiscountReasonUi(page);
      }
      if (t.id === 'pos-inv-service-amount') updateAdjPreview(page, 'service');
      if (t.id === 'pos-inv-line-note-text') updateLineNoteCount(page);
    });
    page.addEventListener('change', function (e) {
      var t = e.target;
      if (!t || !page.contains(t)) return;
      if (t.id === 'pos-inv-discount-amount') {
        updateAdjPreview(page, 'discount');
        syncDiscountReasonUi(page);
      }
    });
    page.addEventListener('keyup', function (e) {
      var t = e.target;
      if (!t || !page.contains(t)) return;
      if (t.id === 'pos-inv-discount-amount') syncDiscountReasonUi(page);
    });

    page.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') {
        if (state.discountSelectMode) {
          e.preventDefault();
          exitDiscountSelectMode(page);
          return;
        }
        var lineNoteModal = $('#' + modalId('line-note'), page);
        if (lineNoteModal && !lineNoteModal.hidden) {
          e.preventDefault();
          persistLineNoteFromModal(page);
          return;
        }
      }
      if (e.key !== 'Enter') return;
      var t = e.target;
      if (!t || !page.contains(t)) return;
      if (t.id === 'pos-inv-discount-amount') {
        e.preventDefault();
        applyDiscountModal(page);
      } else if (t.id === 'pos-inv-service-amount') {
        e.preventDefault();
        applyServiceModal(page);
      } else if (t.id === 'pos-inv-tip-amount') {
        e.preventDefault();
        applyTipModal(page);
      } else if (t.id === 'pos-inv-coupon-code') {
        e.preventDefault();
        applyCouponModal(page);
      }
    });

    var customSave = $('#pos-inv-custom-save', page);
    if (customSave) {
      customSave.addEventListener('click', function () {
        var nameEl = $('#pos-inv-custom-name', page);
        var rateEl = $('#pos-inv-custom-rate', page);
        var name = nameEl ? String(nameEl.value || '').trim() : '';
        var rate = rateEl ? Number(rateEl.value) : 0;
        if (!name) {
          toast('Enter an item name.');
          if (nameEl) nameEl.focus();
          return;
        }
        if (isNaN(rate) || rate < 0) rate = 0;
        addItem(page, { id: null, name: name, variant: 'Custom', rate: rate, emoji: '✏️' }, 1);
        closeCustomModal(page);
        var search = $('#pos-inv-search', page);
        if (search) search.focus();
      });
    }

    var lineNoteClear = $('#pos-inv-line-note-clear', page);
    if (lineNoteClear) {
      lineNoteClear.addEventListener('click', function () {
        var textEl = $('#pos-inv-line-note-text', page);
        if (textEl) textEl.value = '';
        updateLineNoteCount(page);
        applyLineNoteModal(page, true);
      });
    }

    var discountApply = $('#pos-inv-discount-apply', page);
    if (discountApply) discountApply.addEventListener('click', function () { applyDiscountModal(page); });
    var serviceApply = $('#pos-inv-service-apply', page);
    if (serviceApply) serviceApply.addEventListener('click', function () { applyServiceModal(page); });
    var tipApply = $('#pos-inv-tip-apply', page);
    if (tipApply) tipApply.addEventListener('click', function () { applyTipModal(page); });
    var couponApply = $('#pos-inv-coupon-apply', page);
    if (couponApply) couponApply.addEventListener('click', function () { applyCouponModal(page); });

    var selectAllBtn = $('#pos-inv-discount-select-all', page);
    if (selectAllBtn) {
      selectAllBtn.addEventListener('click', function () { setDiscountSelectAll(page, true); });
    }
    var selectClearBtn = $('#pos-inv-discount-select-clear', page);
    if (selectClearBtn) {
      selectClearBtn.addEventListener('click', function () { setDiscountSelectAll(page, false); });
    }
    var selectCancelBtn = $('#pos-inv-discount-select-cancel', page);
    if (selectCancelBtn) {
      selectCancelBtn.addEventListener('click', function () { exitDiscountSelectMode(page); });
    }
    var selectContinueBtn = $('#pos-inv-discount-select-continue', page);
    if (selectContinueBtn) {
      selectContinueBtn.addEventListener('click', function () { continueDiscountSelectMode(page); });
    }
  }

  function initPosInvoicePage() {
    syncPosApiPaths();
    closeInAppPrintPage();
    var page = document.getElementById('pos-invoice-page');
    if (!page) return;

    /* Immersive billing: unpin rail; enter/restore fullscreen when preferred. */
    try {
      if (typeof global.setDeSidebarPinned === 'function') {
        global.setDeSidebarPinned(false);
      }
    } catch (ePin) {}
    try {
      if (global.deFullscreen) {
        if (typeof global.deFullscreen.enter === 'function' && !global.deFullscreen.isActive()) {
          global.deFullscreen.enter().catch(function () {});
        } else if (typeof global.deFullscreen.restoreIfNeeded === 'function') {
          global.deFullscreen.restoreIfNeeded();
        }
        if (typeof global.deFullscreen.reinit === 'function') {
          global.deFullscreen.reinit();
        }
      }
    } catch (eFs) {}

    /* Soft-nav remounts DOM — clear bind flags on fresh nodes; keep line state only on same session page */
    var freshMount = page.getAttribute('data-inv-mounted') !== '1';
    if (freshMount) {
      page.removeAttribute('data-header-bound');
      page.removeAttribute('data-modals-bound');
      page.setAttribute('data-inv-mounted', '1');
      state.lines = [];
      state.discountType = 'pct';
      state.discountValue = 0;
      state.discountLineUids = [];
      state.discountReason = '';
      state.discountSelectMode = null;
      state.discountSelectDraft = [];
      state.tipAmount = 0;
      state.tipEmployeeId = '';
      state.tipNote = '';
      state.tipPayrollId = null;
      state.serviceType = 'pct';
      state.serviceValue = DEFAULT_SERVICE_PCT;
      state.couponCode = '';
      state.orderNo = '';
      state.localId = '';
      state.lineSeq = 0;
      state.invoiceId = null;
      state.invoiceGenerated = false;
      state.tableForOrder = '';
      state.customerActiveIndex = -1;
      state.dirty = false;
      cancelAutosaveTimer();
      state.adjDraft = { discount: 'pct', service: 'pct' };
    }

    ensureLocalId();
    bindOfflineSyncListeners();
    bindTableOrderSyncListeners();
    updateOfflineBanner();
    flushOfflineOutbox();
    registerInvoiceLeaveHooks();

    /* Resolve resume prefs before floor populate so sync cache callbacks keep the chip. */
    var resumePrefs = resolveResumePrefs();
    if (freshMount && resumePrefs.table) {
      state.tableForOrder = resumePrefs.table;
      state.resumeTableValue = resumePrefs.table;
      state.resumeTableLabel = resumePrefs.table;
    }

    populateTables(page, loadFloorTablesSync(), { loading: !floorTablesLoaded });
    initMeta(page);
    if (freshMount) ensureDefaultCustomerName(page);
    bindSearch(page);
    bindLines(page);
    bindHeader(page);
    bindModal(page);
    bindSettleBillModal(page);
    bindNotes(page);
    bindCustomer(page);
    renderLines(page);
    syncInvoiceGeneratedUi(page);
    updateNotesCount(page);

    if (typeof global.initEpListboxes === 'function') {
      global.initEpListboxes();
    }

    loadFloorTables(function (tables) {
      var keep =
        String(state.tableForOrder || '').trim() ||
        String(state.resumeTableValue || '').trim() ||
        (resumePrefs && resumePrefs.table) ||
        '';
      populateTables(page, tables, { loading: false, preserveTable: keep || undefined });
      if (keep) applyPreferredTable(page, keep);
      if (typeof global.initEpListboxes === 'function') {
        global.initEpListboxes();
      }
      /* Floor arrived after first paint — re-check open bill for the selected table. */
      if (keep && !state.invoiceId && !state.lines.length) {
        syncSelectedTableOrderFromServer(page);
      }
    });

    /* Arriving with ?invoice=... / ?table=... (or stored resume) reloads the open bill.
       Also re-check when soft-nav remounts with an empty cart so another terminal's
       autosave is visible without a full reload. */
    if (resumePrefs.invoiceId || resumePrefs.table) {
      if (freshMount || (!state.invoiceId && !state.lines.length)) {
        restoreResumeOrder(page, resumePrefs);
      }
    } else if (!state.invoiceId && !state.lines.length) {
      syncSelectedTableOrderFromServer(page);
    }

    loadMenuCatalog(function () {
      var searchInput = $('#pos-inv-search', page);
      if (!searchInput) return;
      var q = String(searchInput.value || '').trim();
      if (q.length >= MIN_QUERY) {
        state.activeIndex = 0;
        renderSuggest(page, searchMenu(q), q);
      }
    });

    loadTaxRates(function () {
      renderSummary(page);
    });

    if (page.getAttribute('data-pos-tax-rates-bound') !== '1') {
      page.setAttribute('data-pos-tax-rates-bound', '1');
      global.addEventListener('hbe-pos-tax-rates-changed', function (ev) {
        var detail = ev && ev.detail;
        if (detail && detail.taxRates) {
          applyTaxRates(detail.taxRates);
          renderSummary(page);
          renderLines(page);
          return;
        }
        if (detail && detail.settings) {
          applyTaxRates(taxRatesFromSettings(detail.settings));
          renderSummary(page);
          renderLines(page);
          return;
        }
        refreshTaxRatesAndSummary(page);
      });
    }

    var search = $('#pos-inv-search', page);
    if (search && !(resumePrefs.invoiceId || resumePrefs.table)) {
      /* Prefer search focus for billing flow */
      try {
        search.focus({ preventScroll: true });
      } catch (err) {
        search.focus();
      }
    }
  }

  global.initPosInvoicePage = initPosInvoicePage;
  global.posInvOrderTypeChanged = posInvOrderTypeChanged;
  global.posInvTableChanged = posInvTableChanged;
  global.HBE_POS_MENU_CATALOG = menuCatalog;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initPosInvoicePage);
  } else if (!global.__deSoftNavInProgress) {
    /* Soft-nav: deWorkspaceReinit calls init once after scripts load — avoid double floor/menu fetch. */
    initPosInvoicePage();
  }
})(window);
