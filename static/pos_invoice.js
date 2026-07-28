/**
 * Point of Sale — Invoice billing (search-first UI).
 * Soft-nav safe: expose window.initPosInvoicePage and re-bind idempotently.
 * Menu catalog loads from /point-of-sale/api/menu/items (Settings → Menu).
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

  function makeOrderNo(d) {
    var yy = String(d.getFullYear()).slice(-2);
    var mm = String(d.getMonth() + 1);
    if (mm.length < 2) mm = '0' + mm;
    var seq = String(40 + (d.getMinutes() % 50));
    return 'ORD-' + yy + mm + '-' + seq.padStart(4, '0');
  }

  function queryParam(name) {
    try {
      return new URLSearchParams(global.location.search).get(name) || '';
    } catch (err) {
      return '';
    }
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

  function loadFloorTables(done) {
    if (floorTablesLoaded && Array.isArray(floorTablesCache) && floorTablesCache.length) {
      if (typeof done === 'function') done(floorTablesCache);
      /* Stale-while-revalidate: refresh in background for next visit. */
      fetch(FLOOR_API, {
        credentials: 'same-origin',
        headers: { Accept: 'application/json' }
      })
        .then(function (res) {
          return res.json().then(function (data) {
            return { ok: res.ok && data && data.ok, data: data };
          });
        })
        .then(function (result) {
          if (result.ok && Array.isArray(result.data.tables)) {
            floorTablesCache = result.data.tables;
          }
        })
        .catch(function () {});
      return;
    }
    fetch(FLOOR_API, {
      credentials: 'same-origin',
      headers: { Accept: 'application/json' }
    })
      .then(function (res) {
        return res.json().then(function (data) {
          return { ok: res.ok && data && data.ok, data: data };
        });
      })
      .then(function (result) {
        if (result.ok && Array.isArray(result.data.tables)) {
          floorTablesCache = result.data.tables;
        } else {
          floorTablesCache = emptyFloorTables();
        }
        floorTablesLoaded = true;
        if (typeof done === 'function') done(floorTablesCache);
      })
      .catch(function () {
        floorTablesCache = emptyFloorTables();
        floorTablesLoaded = true;
        if (typeof done === 'function') done(floorTablesCache);
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

  function normalizeMenuItem(raw, categoryName) {
    return {
      id: String(raw.id),
      name: raw.name || '',
      code: raw.code || '',
      barcode: raw.barcode || '',
      category: categoryName || '',
      variant: raw.variant || '',
      rate: Number(raw.rate) || 0,
      emoji: '🍽️'
    };
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

    menuCatalogInflight = fetch(MENU_ITEMS_API, {
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
        return fetch(MENU_CATEGORIES_API, {
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
        if (failed) {
          menuCatalog.length = 0;
          menuCatalogById = {};
          menuCatalogStatus = 'error';
          return false;
        }
        if (!result || !result.ok || !Array.isArray(result.data.categories)) {
          menuCatalog.length = 0;
          menuCatalogById = {};
          menuCatalogStatus = 'error';
          return false;
        }
        categoriesPayload = result.data.categories;
        buildMenuCatalog(itemsPayload, categoriesPayload);
        return true;
      })
      .catch(function () {
        menuCatalog.length = 0;
        menuCatalogById = {};
        menuCatalogStatus = 'error';
        return false;
      })
      .then(function (ok) {
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
      return 'No menu items configured. Add items in Restaurant Settings → Menu.';
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

    var subtotal = 0;
    state.lines.forEach(function (line) {
      subtotal += (Number(line.rate) || 0) * (Number(line.qty) || 0);
    });
    var discount = calcAdjAmount(subtotal, discountType, discountValue);
    var afterDiscount = Math.max(0, subtotal - discount);
    var gst = afterDiscount * GST_RATE;
    var service = calcAdjAmount(afterDiscount, serviceType, serviceValue);
    var tip = Number(tipAmount) || 0;
    if (tip < 0) tip = 0;
    var beforeRound = afterDiscount + gst + service + tip;
    var rounded = Math.round(beforeRound);
    var roundOff = Math.round((rounded - beforeRound) * 100) / 100;
    return {
      subtotal: subtotal,
      discount: discount,
      discountType: discountType,
      discountValue: Number(discountValue) || 0,
      gst: gst,
      service: service,
      serviceType: serviceType,
      serviceValue: Number(serviceValue) || 0,
      tip: tip,
      roundOff: roundOff,
      total: rounded
    };
  }

  function formatAdjHint(type, value) {
    var n = Number(value);
    if (isNaN(n) || n <= 0) return '';
    if (type === 'inr') return '(₹' + n.toFixed(n % 1 ? 2 : 0) + ')';
    return '(' + n + '%)';
  }

  function renderSummary(page) {
    var t = calcTotals();
    var map = {
      'pos-inv-sum-subtotal': t.subtotal,
      'pos-inv-sum-discount': t.discount,
      'pos-inv-sum-gst': t.gst,
      'pos-inv-sum-service': t.service,
      'pos-inv-sum-tip': t.tip,
      'pos-inv-sum-round': t.roundOff,
      'pos-inv-sum-total': t.total
    };
    Object.keys(map).forEach(function (id) {
      var el = $('#' + id, page);
      if (el) el.textContent = money(map[id]);
    });
    var discHint = $('#pos-inv-sum-discount-hint', page);
    if (discHint) discHint.textContent = formatAdjHint(t.discountType, t.discountValue);
    var discRow = $('#pos-inv-sum-discount-row', page);
    if (discRow) {
      var showDiscount = Number(t.discount) > 0 || Number(t.discountValue) > 0;
      discRow.hidden = !showDiscount;
    }
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

    body.innerHTML = state.lines
      .map(function (line) {
        var amt = (Number(line.rate) || 0) * (Number(line.qty) || 0);
        var pendingQty = pendingKotQty(line);
        var sentQty = lineKitchenSentQty(line);
        var lockReduce = !isAdmin && sentQty > 0;
        var canDecrease = !lockReduce || Number(line.qty) > sentQty;
        var canDelete = !lockReduce;
        var lineNotes = String(line.notes || '').trim();
        return (
          '<tr data-line-id="' +
          escapeHtml(line.uid) +
          '">' +
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
          (canDecrease ? '' : ' disabled title="Only an administrator can reduce quantity after KOT"') +
          '>−</button>' +
          '<span>' +
          line.qty +
          '</span>' +
          '<button type="button" data-qty="1" aria-label="Increase quantity">+</button>' +
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
          (lineNotes ? ' title="' + escapeHtml(lineNotes) + '"' : ' title="Add customised note"') +
          '>' +
          '<svg viewBox="0 0 24 24"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>' +
          '</button>' +
          '<button type="button" class="pos-inv-del" data-del aria-label="Remove item"' +
          (canDelete ? '' : ' disabled title="Only an administrator can remove items after KOT"') +
          '>' +
          '<svg viewBox="0 0 24 24"><path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6M14 11v6"/></svg>' +
          '</button></div></td></tr>'
        );
      })
      .join('');

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

  function printKotTicket(page, pending) {
    try {
      var win = global.open('', '_blank', 'width=380,height=600');
      if (!win) return;
      var now = new Date();
      var table = fieldValue('pos-inv-table', page) || '—';
      var orderTypeValue =
        fieldValue('pos-inv-order-type-header', page) || fieldValue('pos-inv-order-type', page) || 'dine_in';
      var orderType = ORDER_TYPE_LABELS[orderTypeValue] || orderTypeValue;
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
      var html =
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
        '<h1>KITCHEN ORDER TOKEN</h1>' +
        '<div class="meta">' +
        '<div><span>Order</span><span>' + escapeHtml(state.orderNo || '—') + '</span></div>' +
        '<div><span>Table</span><span>' + escapeHtml(table) + '</span></div>' +
        '<div><span>Type</span><span>' + escapeHtml(orderType) + '</span></div>' +
        '<div><span>Time</span><span>' + formatDate(now) + ' ' + formatTime(now) + '</span></div>' +
        '</div>' +
        '<table><tbody>' + rows + '</tbody></table>' +
        '<div class="foot">-- Confirmed for kitchen --</div>' +
        '</body></html>';
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
    } catch (err) {
      /* Printing is best-effort only — order state below is unaffected. */
    }
  }

  /** Customer-facing bill HTML — same layout used by Print and Send to Customer. */
  function buildCustomerBillHtml(page, invoice) {
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
        // Line notes are kitchen-only (KOT) — never print on the customer bill.
        return (
          '<tr><td class="name">' +
          escapeHtml(line.name) +
          (line.variant ? '<div class="variant">' + escapeHtml(line.variant) + '</div>' : '') +
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
      '<div><span>GST (' +
      GST_RATE * 100 +
      '%)</span><span>' +
      money(totals.gst) +
      '</span></div>' +
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
      if (!openBillPrintPage(html, { autoPrint: opts.autoPrint !== false })) {
        toast('Could not open the print page. Check your pop-up blocker.');
      }
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

  function sendKot(page) {
    var pending = pendingKotLines();
    if (!pending.length) {
      toast('Nothing new to send — kitchen is already up to date.');
      return;
    }

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

    var payload = collectOrderPayload(page);
    payload.kotSend = true;
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

    fetch(INVOICE_API, {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(payload)
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
        if (!result.ok || !result.data.ok) {
          toast((result.data && result.data.error) || 'Could not send KOT.');
          return;
        }
        var invoice = result.data.invoice;
        if (invoice) {
          state.invoiceId = invoice.id;
          state.tableForOrder = invoice.table_label || invoice.table || state.tableForOrder;
        }
        clearDirtyAfterPersist(epochAtStart, page);
        if (!state.dirty) cancelAutosaveTimer();
        printKotTicket(page, pending);
        pending.forEach(function (entry) {
          entry.line.sentQty = Number(entry.line.qty) || 0;
        });
        var count = pending.length;
        renderLines(page);
        toast('KOT sent to kitchen for ' + count + (count === 1 ? ' item.' : ' items.'));
      })
      .catch(function () {
        toast('Could not send KOT. Check your connection and try again.');
      })
      .then(function () {
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
    if (!state.lines.length) {
      toast('Add at least one item before sending the bill.');
      var search = $('#pos-inv-search', page);
      if (search) search.focus();
      return;
    }

    var customerName = fieldValue('pos-inv-customer-name', page);
    if (!customerName) {
      toast('Enter customer name before sending the bill.');
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

    var payload = collectOrderPayload(page);
    /* Marks the order so Kitchen Order Tokens can disable Resend after the
       customer bill has been generated / printed. Sticky once set on server. */
    payload.customerBill = true;
    var epochAtStart = dirtyEpoch;
    var btn = $('#pos-inv-send-customer', page) || page.querySelector('[data-inv-action="send"]');
    if (btn) btn.disabled = true;

    fetch(INVOICE_API, {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(payload)
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
        if (!result.ok || !result.data.ok) {
          toast((result.data && result.data.error) || 'Could not generate the bill.');
          return;
        }
        var invoice = result.data.invoice;
        if (invoice) {
          state.invoiceId = invoice.id;
          state.tableForOrder = invoice.table_label || invoice.table || state.tableForOrder;
        }
        clearDirtyAfterPersist(epochAtStart, page);
        if (!state.dirty) cancelAutosaveTimer();
        printCustomerBill(page, invoice);
        toast('Bill ready for ' + ((invoice && invoice.order_no) || state.orderNo) + '.');
      })
      .catch(function () {
        toast('Could not generate the bill. Check your connection and try again.');
      })
      .then(function () {
        if (btn) btn.disabled = false;
        updateSettleBillButton(page);
      });
  }

  function addItem(page, item, qty) {
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
    } else {
      state.lineSeq += 1;
      state.lines.push({
        uid: 'L' + state.lineSeq,
        menuId: item.id || null,
        name: item.name,
        variant: item.variant || item.category || '',
        rate: Number(item.rate) || 0,
        qty: qty || 1,
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
          escapeHtml(item.code) +
          ' · ' +
          escapeHtml(item.category) +
          (item.variant ? ' · ' + escapeHtml(item.variant) : '') +
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

  function applyPreferredTable(page, tableName) {
    var name = String(tableName || '').trim();
    if (!name) return;
    setListboxValue('pos-inv-table', name, name);
    state.resumeTableValue = name;
    state.resumeTableLabel = name;
    if (!state.tableForOrder) state.tableForOrder = name;
  }

  function populateTables(page, tablesIn, opts) {
    var list = $('#pos-inv-table-list', page);
    var input = $('#pos-inv-table', page);
    if (!list || !input) return;
    var pref = queryParam('table').trim();
    /* Floor data hasn't come back from the API yet — show a status row instead
       of leaving the panel blank, so the chip never looks unresponsive while it
       opens correctly but has nothing to render yet. */
    if (opts && opts.loading && !(tablesIn && tablesIn.length)) {
      list.innerHTML = '<div class="se-filter-listbox-status" role="presentation">Loading tables…</div>';
      /* Still bind ?table= so early Save/KOT cannot post a dine-in bill with no table. */
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
      if (pref && (name.toLowerCase() === pref.toLowerCase() || ('table ' + name).toLowerCase() === pref.toLowerCase())) {
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
        var name = String(t.name || '');
        return name.toLowerCase() === pref.toLowerCase() || ('table ' + name).toLowerCase() === pref.toLowerCase();
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
    if (selected) state.tableForOrder = selected;
  }

  function posInvOrderTypeChanged(root, value, label) {
    var page = document.getElementById('pos-invoice-page');
    if (!page) return;
    var display = label || ORDER_TYPE_LABELS[value] || value;
    setListboxValue('pos-inv-order-type-header', value, display);
  }

  function initMeta(page) {
    var now = new Date();
    var dateEl = $('#pos-inv-meta-date', page);
    var timeEl = $('#pos-inv-meta-time', page);
    var orderEl = $('#pos-inv-meta-order-no', page);
    if (dateEl) dateEl.textContent = formatDate(now);
    if (timeEl) timeEl.textContent = formatTime(now);
    if (!state.orderNo) state.orderNo = makeOrderNo(now);
    if (orderEl) orderEl.textContent = state.orderNo;
    syncOrderTypeMeta(page);
  }

  /** Load this session's in-progress state from a persisted invoice — the core
   *  of "resume this table's order" (Tables tile tap, or picking an occupied
   *  table from this page's own picker). Overwrites lines/customer/totals. */
  function hydrateFromInvoice(page, invoice) {
    if (!invoice) return;
    state.invoiceId = invoice.id;
    state.orderNo = invoice.order_no || state.orderNo;
    state.tableForOrder = invoice.table_label || invoice.table || '';
    state.discountType = invoice.discount_type || 'pct';
    state.discountValue = Number(invoice.discount_value) || 0;
    state.serviceType = invoice.service_type || 'pct';
    state.serviceValue = Number(invoice.service_value) || 0;
    state.tipAmount = Number(invoice.tip_amount) || 0;
    state.couponCode = invoice.coupon_code || '';
    state.lineSeq = 0;
    state.lines = (invoice.lines || []).map(function (line) {
      state.lineSeq += 1;
      return {
        uid: 'L' + state.lineSeq,
        menuId: line.menu_item_id || null,
        name: line.name,
        variant: line.variant || '',
        rate: Number(line.rate) || 0,
        qty: Number(line.qty) || 0,
        emoji: '🍽️',
        sentQty: Number(line.sent_qty) || 0,
        notes: String(line.notes || '').trim()
      };
    });

    var orderEl = $('#pos-inv-meta-order-no', page);
    if (orderEl) orderEl.textContent = state.orderNo;

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

    if (state.tableForOrder) {
      setListboxValue('pos-inv-table', state.tableForOrder, state.tableForOrder);
      state.resumeTableValue = state.tableForOrder;
      state.resumeTableLabel = state.tableForOrder;
    }

    state.dirty = false;
    if (autosaveTimer) {
      clearTimeout(autosaveTimer);
      autosaveTimer = null;
    }
    renderLines(page);
    toast('Resumed order ' + state.orderNo + '.');
  }

  /** Shared lookup: is there an open dine-in order for this table? Used by both
   *  the initial ?table= page load and the header table picker's resume flow. */
  function resumeOrderForTable(page, tableName, opts) {
    var name = String(tableName || '').trim();
    if (!name) return;
    fetch(INVOICE_BY_TABLE_API + '?table=' + encodeURIComponent(name), {
      credentials: 'same-origin',
      headers: { Accept: 'application/json' }
    })
      .then(function (res) {
        return res.json().catch(function () {
          return {};
        });
      })
      .then(function (data) {
        if (data && data.ok && data.invoice) {
          hydrateFromInvoice(page, data.invoice);
          return;
        }
        if (opts && typeof opts.notFound === 'function') opts.notFound();
      })
      .catch(function () {
        if (opts && typeof opts.notFound === 'function') opts.notFound();
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
    if (!value) {
      state.resumeTableValue = '';
      state.resumeTableLabel = 'Select table…';
      return;
    }
    var status = selectedTableStatus(page);
    if (!tableBlocksNewBill(status)) {
      state.resumeTableValue = value;
      state.resumeTableLabel = label;
      /* Table chosen after items were added — kick autosave so leave/resume works. */
      if (state.lines.length) markOrderDirty(page);
      return;
    }
    var switchingTable = String(value).toLowerCase() !== String(state.tableForOrder || '').toLowerCase();
    if (switchingTable && state.lines.length) {
      var ok = global.confirm(
        'Switch to the open order for ' + value + '? Unsaved items in the current order will be discarded.'
      );
      if (!ok) {
        setListboxValue('pos-inv-table', prevValue, prevLabel);
        return;
      }
    }
    state.resumeTableValue = value;
    state.resumeTableLabel = label;
    resumeOrderForTable(page, value, {
      notFound: function () {
        toast(value + ' is marked occupied but has no active order. Ask a manager to free it on the Tables page.');
        setListboxValue('pos-inv-table', prevValue, prevLabel);
        state.resumeTableValue = prevValue;
        state.resumeTableLabel = prevLabel;
      }
    });
  }

  function updateSettleBillButton(page) {
    var btn = $('#pos-inv-settle-bill', page) || $('#pos-inv-close-table', page);
    if (!btn) return;
    btn.hidden = !(state.invoiceId && state.lines && state.lines.length);
  }

  /** Reset the on-screen session to a fresh, blank order — used after Settle
   *  Bill so staff isn't left staring at a closed bill. */
  function resetOrderSession(page) {
    state.lines = [];
    state.discountType = 'pct';
    state.discountValue = 0;
    state.tipAmount = 0;
    state.tipEmployeeId = '';
    state.tipNote = '';
    state.tipPayrollId = null;
    state.serviceType = 'pct';
    state.serviceValue = DEFAULT_SERVICE_PCT;
    state.couponCode = '';
    state.orderNo = '';
    state.lineSeq = 0;
    state.invoiceId = null;
    state.tableForOrder = '';
    state.customerActiveIndex = -1;
    state.dirty = false;
    cancelAutosaveTimer();
    state.adjDraft = { discount: 'pct', service: 'pct' };
    initMeta(page);
    var nameEl = $('#pos-inv-customer-name', page);
    if (nameEl) nameEl.value = DEFAULT_AUTOSAVE_CUSTOMER;
    var mobileEl = $('#pos-inv-customer-mobile', page);
    if (mobileEl) mobileEl.value = '';
    var notesEl = $('#pos-inv-notes', page);
    if (notesEl) {
      notesEl.value = '';
      updateNotesCount(page);
    }
    setListboxValue('pos-inv-table', '', 'Select table…');
    state.resumeTableValue = '';
    state.resumeTableLabel = 'Select table…';
    renderLines(page);
    loadFloorTables(function (tables) {
      populateTables(page, tables, { loading: false });
      if (typeof global.initEpListboxes === 'function') global.initEpListboxes();
    });
  }

  var POS_PAYMENT_METHODS = [
    ['cash', 'Cash'],
    ['upi', 'UPI'],
    ['card', 'Card'],
    ['room_transfer', 'Room Transfer'],
    ['bank_transfer', 'Bank Transfer']
  ];
  var POS_METHODS_REQUIRING_TXN = { bank_transfer: true };
  try {
    var methodsEl = document.getElementById('pos-inv-payment-methods-data');
    if (methodsEl) {
      var parsedMethods = JSON.parse(methodsEl.textContent || '[]');
      if (parsedMethods && parsedMethods.length) POS_PAYMENT_METHODS = parsedMethods;
    }
  } catch (err) {}

  function settleMoneyLabel(value) {
    var n = Math.round((Number(value) || 0) * 100) / 100;
    return money(n);
  }

  function settleBillTotal() {
    return Math.round((Number(calcTotals().total) || 0) * 100) / 100;
  }

  function setSettleError(message) {
    var el = document.getElementById('pos-inv-settle-error');
    if (!el) return;
    if (message) {
      el.textContent = message;
      el.classList.add('is-visible');
    } else {
      el.textContent = '';
      el.classList.remove('is-visible');
    }
  }

  function closeSettleModal() {
    var modal = document.getElementById('pos-inv-settle-modal');
    if (!modal || modal.hidden) return;
    closeAllSettleSplitListboxes();
    modal.hidden = true;
    modal.setAttribute('hidden', '');
    setSettleError('');
  }

  function settleSplitRows() {
    var root = document.getElementById('pos-inv-settle-splits');
    if (!root) return [];
    return Array.prototype.slice.call(
      root.querySelectorAll('.rt-split-row, .pos-inv-settle-split-row')
    );
  }

  function settleMethodLabel(method) {
    var key = String(method || '');
    for (var i = 0; i < POS_PAYMENT_METHODS.length; i++) {
      if (POS_PAYMENT_METHODS[i][0] === key) return POS_PAYMENT_METHODS[i][1];
    }
    return key ? key : 'Select mode…';
  }

  function settleRowMethodValue(row) {
    if (!row) return '';
    var hidden = row.querySelector('.pos-inv-settle-method-input');
    return hidden ? String(hidden.value || '') : '';
  }

  function settleUsedMethods(exceptRow) {
    var used = {};
    settleSplitRows().forEach(function (row) {
      if (row === exceptRow) return;
      var method = settleRowMethodValue(row);
      if (method) used[method] = true;
    });
    return used;
  }

  function settleMethodOptionsHtml(selected, exceptRow) {
    var used = settleUsedMethods(exceptRow);
    return POS_PAYMENT_METHODS.map(function (pair) {
      var value = pair[0];
      var label = pair[1];
      if (used[value] && value !== selected) return '';
      var on = value === selected;
      return (
        '<button type="button" class="se-filter-listbox-option' +
        (on ? ' is-selected' : '') +
        '" role="option" data-value="' +
        escapeHtml(value) +
        '" aria-selected="' +
        (on ? 'true' : 'false') +
        '">' +
        escapeHtml(label) +
        '</button>'
      );
    }).join('');
  }

  function closeSettleSplitListbox(root) {
    if (!root) return;
    var trigger = root.querySelector('.se-filter-chip-trigger');
    var list = root.querySelector('.se-filter-listbox');
    root.classList.remove('is-open');
    if (trigger) trigger.setAttribute('aria-expanded', 'false');
    if (list) {
      list.hidden = true;
      list.scrollTop = 0;
    }
  }

  function closeAllSettleSplitListboxes(except) {
    var root = document.getElementById('pos-inv-settle-splits');
    if (!root) return;
    root.querySelectorAll('[data-se-listbox].is-open').forEach(function (box) {
      if (box !== except) closeSettleSplitListbox(box);
    });
  }

  function openSettleSplitListbox(root) {
    if (!root || root.classList.contains('is-disabled')) return;
    closeAllSettleSplitListboxes(root);
    var trigger = root.querySelector('.se-filter-chip-trigger');
    var list = root.querySelector('.se-filter-listbox');
    root.classList.add('is-open');
    if (trigger) trigger.setAttribute('aria-expanded', 'true');
    if (list) {
      list.hidden = false;
      var selected =
        list.querySelector('[aria-selected="true"]') ||
        list.querySelector('.se-filter-listbox-option');
      if (selected && selected.focus) {
        try {
          selected.focus({ preventScroll: true });
        } catch (err) {
          selected.focus();
        }
      }
    }
  }

  function refreshSettleOptionAvailability() {
    settleSplitRows().forEach(function (row) {
      var listbox = row.querySelector('[data-se-listbox]');
      var list = row.querySelector('.se-filter-listbox');
      var selected = settleRowMethodValue(row);
      if (list) list.innerHTML = settleMethodOptionsHtml(selected, row);
      if (listbox && listbox.classList.contains('is-open')) {
        var selectedOpt =
          list &&
          (list.querySelector('[aria-selected="true"]') ||
            list.querySelector('.se-filter-listbox-option'));
        if (selectedOpt && selectedOpt.focus) {
          try {
            selectedOpt.focus({ preventScroll: true });
          } catch (err) {
            selectedOpt.focus();
          }
        }
      }
      syncSettleRowState(row);
    });
    var addBtn = document.getElementById('pos-inv-settle-add-split');
    if (addBtn) addBtn.disabled = settleSplitRows().length >= POS_PAYMENT_METHODS.length;
  }

  function bindSettleSplitListbox(row) {
    var root = row && row.querySelector('[data-se-listbox]');
    if (!root || root.getAttribute('data-bound') === '1') return;
    root.setAttribute('data-bound', '1');
    var trigger = root.querySelector('.se-filter-chip-trigger');
    var list = root.querySelector('.se-filter-listbox');
    var hidden = root.querySelector('.pos-inv-settle-method-input');
    var valueEl = root.querySelector('.se-filter-chip-value');
    if (!trigger || !list || !hidden) return;

    trigger.addEventListener('click', function (e) {
      e.preventDefault();
      e.stopPropagation();
      if (root.classList.contains('is-open')) closeSettleSplitListbox(root);
      else openSettleSplitListbox(root);
    });
    trigger.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowDown' || e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        openSettleSplitListbox(root);
      } else if (e.key === 'Escape') {
        closeSettleSplitListbox(root);
      }
    });
    list.addEventListener('click', function (e) {
      var option = e.target.closest('.se-filter-listbox-option');
      if (!option || !list.contains(option)) return;
      e.preventDefault();
      var value = option.getAttribute('data-value') || '';
      var label = (option.textContent || '').trim();
      hidden.value = value;
      if (valueEl) {
        valueEl.textContent = label || 'Select mode…';
        valueEl.classList.toggle('staff-supplier-placeholder', !value);
      }
      list.querySelectorAll('.se-filter-listbox-option').forEach(function (opt) {
        var on = opt === option;
        opt.classList.toggle('is-selected', on);
        opt.setAttribute('aria-selected', on ? 'true' : 'false');
      });
      closeSettleSplitListbox(root);
      syncSettleRowState(row);
      refreshSettleOptionAvailability();
      refreshSettleBalance();
    });
  }

  function syncSettleRowState(row) {
    if (!row) return;
    var txn = row.querySelector('.pos-inv-settle-txn');
    var method = settleRowMethodValue(row);
    var needsTxn = !!POS_METHODS_REQUIRING_TXN[method];
    row.classList.toggle('is-bank', needsTxn);
    if (txn) {
      txn.hidden = !needsTxn;
      if (!needsTxn) txn.value = '';
    }
  }

  function updateSettleRemoveButtons() {
    var rows = settleSplitRows();
    var multi = rows.length > 1;
    rows.forEach(function (row) {
      var removeBtn = row.querySelector('.pos-inv-settle-remove');
      var amountInput = row.querySelector('.pos-inv-settle-amount');
      if (removeBtn) removeBtn.hidden = !multi;
      if (amountInput) {
        amountInput.hidden = !multi;
        amountInput.required = multi;
      }
      row.classList.toggle('is-multi', multi);
      syncSettleRowState(row);
    });
  }

  function roundSettleMoney(value) {
    return Math.round((Number(value) || 0) * 100) / 100;
  }

  function syncRemainingSettleAmount(changedRow) {
    var rows = settleSplitRows();
    if (rows.length < 2) return;
    var target = settleBillTotal();
    if (!(target > 0)) return;

    function amountRaw(row) {
      var input = row.querySelector('.pos-inv-settle-amount');
      return input ? String(input.value || '').trim() : '';
    }
    function setAmount(row, value) {
      var input = row.querySelector('.pos-inv-settle-amount');
      if (!input) return;
      input.value = value > 0 ? String(value) : '';
    }

    if (rows.length === 2) {
      var first = rows[0];
      var second = rows[1];
      if (!changedRow) {
        var firstRaw = amountRaw(first);
        var secondRaw = amountRaw(second);
        var firstAmt = Number(firstRaw);
        var secondAmt = Number(secondRaw);
        if (firstRaw && isFinite(firstAmt) && firstAmt > 0 && !secondRaw) {
          setAmount(second, roundSettleMoney(target - firstAmt));
        } else if (secondRaw && isFinite(secondAmt) && secondAmt > 0 && !firstRaw) {
          setAmount(first, roundSettleMoney(target - secondAmt));
        }
        return;
      }
      var otherRow = changedRow === first ? second : first;
      var raw = amountRaw(changedRow);
      var amount = Number(raw);
      if (!raw || !isFinite(amount) || amount <= 0) {
        setAmount(otherRow, 0);
        return;
      }
      setAmount(otherRow, roundSettleMoney(target - amount));
      return;
    }

    var lastRow = rows[rows.length - 1];
    if (changedRow && changedRow === lastRow) return;
    var others = 0;
    var hasEarlierAmount = false;
    for (var i = 0; i < rows.length - 1; i++) {
      var rawEarlier = amountRaw(rows[i]);
      var amountEarlier = Number(rawEarlier);
      if (rawEarlier && isFinite(amountEarlier) && amountEarlier > 0) {
        hasEarlierAmount = true;
        others += amountEarlier;
      }
    }
    if (!hasEarlierAmount) {
      setAmount(lastRow, 0);
      return;
    }
    setAmount(lastRow, roundSettleMoney(target - others));
  }

  function allSettleModesSelected() {
    var rows = settleSplitRows();
    if (!rows.length) return false;
    for (var i = 0; i < rows.length; i++) {
      if (!settleRowMethodValue(rows[i])) return false;
    }
    return true;
  }

  function settleSplitsMatchTotal() {
    var rows = settleSplitRows();
    var target = settleBillTotal();
    if (!rows.length) return false;
    if (target <= 0) return allSettleModesSelected();
    if (!allSettleModesSelected()) return false;
    if (rows.length === 1) return true;
    var total = 0;
    var complete = true;
    rows.forEach(function (row) {
      var amountInput = row.querySelector('.pos-inv-settle-amount');
      var raw = amountInput ? String(amountInput.value || '').trim() : '';
      var amount = Number(raw);
      if (!raw || !isFinite(amount) || amount <= 0) complete = false;
      total += isFinite(amount) ? amount : 0;
    });
    return complete && Math.abs(total - target) <= 0.001;
  }

  function syncSettleSubmitEnabled() {
    var submitBtn = document.getElementById('pos-inv-settle-submit');
    if (!submitBtn) return;
    var rows = settleSplitRows();
    var target = settleBillTotal();
    var ok = target <= 0 ? allSettleModesSelected() : settleSplitsMatchTotal();
    if (ok) {
      rows.forEach(function (row) {
        var method = settleRowMethodValue(row);
        var txnInput = row.querySelector('.pos-inv-settle-txn');
        if (POS_METHODS_REQUIRING_TXN[method] && !(txnInput && txnInput.value.trim())) {
          ok = false;
        }
      });
    }
    rows.forEach(function (row) {
      var listbox = row.querySelector('.pos-inv-settle-method-listbox');
      if (listbox) {
        listbox.classList.toggle('is-incomplete', !settleRowMethodValue(row));
      }
    });
    submitBtn.disabled = !ok;
  }

  function refreshSettleBalance() {
    var rows = settleSplitRows();
    var multi = rows.length > 1;
    var balanceEl = document.getElementById('pos-inv-settle-balance');
    var splitTotalEl = document.getElementById('pos-inv-settle-split-total');
    var splitTargetEl = document.getElementById('pos-inv-settle-split-target');
    if (balanceEl) balanceEl.hidden = !multi;
    var total = 0;
    var allFilled = true;
    var modesSelected = true;
    rows.forEach(function (row) {
      if (!settleRowMethodValue(row)) modesSelected = false;
      var amountInput = row.querySelector('.pos-inv-settle-amount');
      var raw = amountInput ? String(amountInput.value || '').trim() : '';
      var amount = Number(raw);
      if (multi && (!raw || !isFinite(amount) || amount <= 0)) allFilled = false;
      total += isFinite(amount) ? amount : 0;
    });
    var target = settleBillTotal();
    if (splitTotalEl) {
      splitTotalEl.setAttribute('data-amount', String(total));
      splitTotalEl.textContent = settleMoneyLabel(total);
    }
    if (splitTargetEl) {
      splitTargetEl.setAttribute('data-amount', String(target));
      splitTargetEl.textContent = settleMoneyLabel(target);
    }
    if (balanceEl) {
      var mismatch =
        multi && (!allFilled || !modesSelected || Math.abs(total - target) > 0.001);
      balanceEl.classList.toggle('is-mismatch', mismatch);
    }
    syncSettleSubmitEnabled();
  }

  function syncSingleSettleAmount() {
    var rows = settleSplitRows();
    if (rows.length !== 1) {
      syncRemainingSettleAmount(null);
      refreshSettleBalance();
      return;
    }
    var amountInput = rows[0].querySelector('.pos-inv-settle-amount');
    if (amountInput) amountInput.value = String(settleBillTotal() || '');
    refreshSettleBalance();
  }

  function addSettleSplitRow(preferredMethod, amount) {
    var root = document.getElementById('pos-inv-settle-splits');
    if (!root) return;
    if (settleSplitRows().length >= POS_PAYMENT_METHODS.length) return;
    var method = preferredMethod == null ? '' : String(preferredMethod || '');
    if (method && settleUsedMethods(null)[method]) method = '';
    var label = settleMethodLabel(method);
    var uid = 'pos-settle-split-' + Date.now() + '-' + Math.floor(Math.random() * 1000);
    var row = document.createElement('div');
    row.className = 'rt-split-row pos-inv-settle-split-row';
    row.innerHTML =
      '<div class="se-filter-chip se-filter-chip--payment se-filter-chip--listbox ep-form-listbox staff-expense-payment-listbox pos-inv-settle-method-listbox" data-se-listbox>' +
      '<div class="se-filter-chip-control">' +
      '<span class="se-filter-chip-icon" aria-hidden="true">' +
      '<svg viewBox="0 0 24 24" width="18" height="18"><rect x="2" y="5" width="20" height="14" rx="2"/><path d="M2 10h20"/></svg>' +
      '</span>' +
      '<input type="hidden" class="pos-inv-settle-method-input" value="' +
      escapeHtml(method) +
      '">' +
      '<button type="button" class="se-filter-chip-trigger" id="' +
      uid +
      '-trigger" aria-haspopup="listbox" aria-expanded="false" aria-controls="' +
      uid +
      '-list" aria-label="Payment mode">' +
      '<span class="se-filter-chip-value' +
      (method ? '' : ' staff-supplier-placeholder') +
      '">' +
      escapeHtml(label) +
      '</span>' +
      '</button>' +
      '<span class="se-filter-chip-chev" aria-hidden="true">' +
      '<svg viewBox="0 0 24 24" width="16" height="16"><polyline points="6 9 12 15 18 9"/></svg>' +
      '</span>' +
      '</div>' +
      '<div class="se-filter-listbox" id="' +
      uid +
      '-list" role="listbox" aria-label="Payment mode" hidden>' +
      settleMethodOptionsHtml(method, null) +
      '</div>' +
      '</div>' +
      '<input class="staff-input pos-inv-settle-amount rt-split-amount" type="number" min="0.01" step="0.01" placeholder="Amount" aria-label="Mode amount" value="' +
      escapeHtml(amount == null ? '' : amount) +
      '">' +
      '<input class="staff-input pos-inv-settle-txn rt-split-txn" type="text" placeholder="Txn / UTR ID" aria-label="Transaction ID" hidden autocomplete="off">' +
      '<button type="button" class="pos-inv-settle-remove rt-split-remove" aria-label="Remove payment mode" hidden>&times;</button>';
    root.appendChild(row);

    var amountInput = row.querySelector('.pos-inv-settle-amount');
    var txnInput = row.querySelector('.pos-inv-settle-txn');
    var removeBtn = row.querySelector('.pos-inv-settle-remove');
    bindSettleSplitListbox(row);
    if (amountInput) {
      amountInput.addEventListener('input', function () {
        syncRemainingSettleAmount(row);
        refreshSettleBalance();
      });
    }
    if (txnInput) txnInput.addEventListener('input', syncSettleSubmitEnabled);
    if (removeBtn) {
      removeBtn.addEventListener('click', function () {
        if (settleSplitRows().length <= 1) return;
        closeAllSettleSplitListboxes();
        row.remove();
        updateSettleRemoveButtons();
        refreshSettleOptionAvailability();
        syncSingleSettleAmount();
      });
    }
    syncSettleRowState(row);
    updateSettleRemoveButtons();
    refreshSettleOptionAvailability();
    refreshSettleBalance();
  }

  function resetSettleSplits() {
    closeAllSettleSplitListboxes();
    var root = document.getElementById('pos-inv-settle-splits');
    if (root) root.innerHTML = '';
    addSettleSplitRow('', '');
    syncSingleSettleAmount();
  }

  function collectSettleSplits() {
    var splits = [];
    var invalid = '';
    var rows = settleSplitRows();
    var target = settleBillTotal();
    rows.forEach(function (row) {
      if (invalid) return;
      var amountInput = row.querySelector('.pos-inv-settle-amount');
      var txnInput = row.querySelector('.pos-inv-settle-txn');
      var method = settleRowMethodValue(row);
      var amount = rows.length === 1 ? target : Number(amountInput && amountInput.value);
      var transactionId = txnInput ? txnInput.value.trim() : '';
      if (!method) {
        invalid = 'Select a payment mode for each row.';
        return;
      }
      if (target > 0 && (!amount || amount <= 0)) {
        invalid = 'Enter a valid amount for each payment mode.';
        return;
      }
      if (POS_METHODS_REQUIRING_TXN[method] && !transactionId) {
        invalid = 'Transaction ID is required for bank transfer.';
        return;
      }
      splits.push({
        payment_method: method,
        amount: amount || 0,
        transaction_id: transactionId
      });
    });
    if (invalid) return { splits: [], error: invalid };
    var splitSum = splits.reduce(function (sum, item) {
      return sum + Number(item.amount || 0);
    }, 0);
    if (Math.abs(splitSum - target) > 0.001) {
      return {
        splits: [],
        error: 'Modes total must equal the bill total before settling.'
      };
    }
    return { splits: splits, error: '' };
  }

  function todayIsoLocal() {
    var d = new Date();
    var y = d.getFullYear();
    var m = d.getMonth() + 1;
    var day = d.getDate();
    return (
      y +
      '-' +
      (m < 10 ? '0' : '') +
      m +
      '-' +
      (day < 10 ? '0' : '') +
      day
    );
  }

  function settleClearanceDate() {
    return todayIsoLocal();
  }

  function openSettleBillModal(page) {
    if (!state.invoiceId) {
      toast('Save the order before settling the bill.');
      return;
    }
    if (!state.lines.length) {
      toast('Add at least one item before settling.');
      return;
    }
    var modal = document.getElementById('pos-inv-settle-modal');
    if (!modal) return;
    setSettleError('');
    var total = settleBillTotal();
    var orderNo = state.orderNo || '—';
    var table = fieldValue('pos-inv-table', page) || '';
    var totalEl = document.getElementById('pos-inv-settle-total');
    if (totalEl) {
      totalEl.setAttribute('data-amount', String(total));
      totalEl.textContent = settleMoneyLabel(total);
    }
    var metaEl = document.getElementById('pos-inv-settle-alloc-meta');
    if (metaEl) metaEl.textContent = orderNo;
    var allocBody = document.getElementById('pos-inv-settle-alloc-body');
    if (allocBody) {
      allocBody.innerHTML =
        '<tr>' +
        '<td><div class="cp-alloc-order"><span class="cp-alloc-code">' +
        escapeHtml(orderNo) +
        '</span>' +
        (table
          ? '<span class="cp-alloc-supplier">' + escapeHtml(table) + '</span>'
          : '') +
        '</div></td>' +
        '<td class="pl-col-amount"><span class="cp-alloc-total-value">' +
        escapeHtml(settleMoneyLabel(total)) +
        '</span></td>' +
        '<td class="pl-col-amount"><input class="cp-alloc-input" type="number" value="' +
        escapeHtml(total) +
        '" disabled aria-label="Pay now amount"></td>' +
        '</tr>';
    }
    var notesEl = document.getElementById('pos-inv-settle-notes');
    if (notesEl) notesEl.value = '';
    resetSettleSplits();
    modal.hidden = false;
    modal.removeAttribute('hidden');
    var firstTrigger = modal.querySelector('.pos-inv-settle-method-listbox .se-filter-chip-trigger');
    if (firstTrigger) firstTrigger.focus();
  }

  function submitSettleBill(page) {
    if (!state.invoiceId) return;
    var collected = collectSettleSplits();
    if (collected.error) {
      setSettleError(collected.error);
      syncSettleSubmitEnabled();
      return;
    }
    var notesEl = document.getElementById('pos-inv-settle-notes');
    var submitBtn = document.getElementById('pos-inv-settle-submit');
    var headerBtn = $('#pos-inv-settle-bill', page) || $('#pos-inv-close-table', page);
    if (submitBtn) submitBtn.disabled = true;
    if (headerBtn) headerBtn.disabled = true;
    setSettleError('');

    /* Stamp the clearance day server-side — no date picker in the UI. */
    var payload = {
      payment_date: settleClearanceDate(),
      notes: notesEl ? notesEl.value.trim() : '',
      payment_splits: collected.splits
    };

    fetch(INVOICE_API + '/' + encodeURIComponent(state.invoiceId) + '/settle', {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(payload)
    })
      .then(function (res) {
        return res
          .json()
          .catch(function () {
            return {};
          })
          .then(function (data) {
            return { ok: res.ok, data: data };
          });
      })
      .then(function (result) {
        if (!result.ok || !result.data.ok) {
          setSettleError(
            (result.data && result.data.error) || 'Could not settle the bill.'
          );
          return;
        }
        closeSettleModal();
        var table = fieldValue('pos-inv-table', page);
        toast(
          table
            ? 'Bill settled. ' + table + ' is now available.'
            : 'Bill settled successfully.'
        );
        resetOrderSession(page);
      })
      .catch(function () {
        setSettleError('Could not settle the bill. Check your connection and try again.');
      })
      .then(function () {
        if (submitBtn) syncSettleSubmitEnabled();
        if (headerBtn) headerBtn.disabled = false;
        updateSettleBillButton(page);
      });
  }

  function bindSettleBillModal(page) {
    var modal = document.getElementById('pos-inv-settle-modal');
    if (!modal || modal.getAttribute('data-bound') === '1') return;
    modal.setAttribute('data-bound', '1');

    modal.addEventListener('click', function (event) {
      if (event.target.closest('[data-settle-close]')) {
        closeSettleModal();
        return;
      }
      if (!event.target.closest('[data-se-listbox]')) {
        closeAllSettleSplitListboxes();
      }
      if (event.target.closest('#pos-inv-settle-add-split')) {
        event.preventDefault();
        if (settleSplitRows().length >= POS_PAYMENT_METHODS.length) return;
        addSettleSplitRow('', '');
        syncRemainingSettleAmount(null);
        updateSettleRemoveButtons();
        refreshSettleBalance();
        return;
      }
      if (event.target.closest('#pos-inv-settle-submit')) {
        event.preventDefault();
        submitSettleBill(page || document.getElementById('pos-invoice-page'));
      }
    });

    if (!document.__posSettleEscBound) {
      document.__posSettleEscBound = true;
      document.addEventListener('keydown', function (event) {
        if (event.key !== 'Escape') return;
        var open = document.getElementById('pos-inv-settle-modal');
        if (!open || open.hidden) return;
        var openList = open.querySelector('[data-se-listbox].is-open');
        if (openList) {
          closeSettleSplitListbox(openList);
          return;
        }
        closeSettleModal();
      });
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
      preview.textContent = 'Discount: ' + money(t.discount);
    } else if (kind === 'service') {
      preview.textContent = 'Service charge: ' + money(t.service);
    }
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
    syncAdjTypeUi(page, 'discount', state.discountType);
    if (amount) {
      amount.value = String(state.discountValue || 0);
      amount.focus();
      amount.select();
    }
    updateAdjPreview(page, 'discount');
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
    var n = amountEl ? Number(amountEl.value) : 0;
    if (isNaN(n) || n < 0) n = 0;
    var type = state.adjDraft.discount || 'pct';
    if (type === 'pct' && n > 100) n = 100;
    state.discountType = type;
    state.discountValue = n;
    closeInvModal(page, 'discount');
    renderSummary(page);
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
    closeInvModal(page, 'coupon');
    if (code) {
      renderSummary(page);
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
          variant: line.variant || '',
          rate: Number(line.rate) || 0,
          qty: Number(line.qty) || 0,
          emoji: line.emoji || '',
          kotSentQty: Number(line.sentQty) || 0,
          notes: String(line.notes || '').trim()
        };
      }),
      discountType: state.discountType,
      discountValue: state.discountValue,
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

  /** Autosave / leave-flush only for dine-in carts with a table and at least one
   *  line. Empty carts are never POSTed (avoids wiping a server order). */
  function shouldAutosave(page) {
    if (!page || !state.lines.length) return false;
    var orderType =
      fieldValue('pos-inv-order-type-header', page) || fieldValue('pos-inv-order-type', page) || 'dine_in';
    if (orderType !== 'dine_in') return false;
    if (!fieldValue('pos-inv-table', page)) return false;
    if (!state.invoiceId && tableBlocksNewBill(selectedTableStatus(page))) return false;
    return true;
  }

  function cancelAutosaveTimer() {
    if (autosaveTimer) {
      clearTimeout(autosaveTimer);
      autosaveTimer = null;
    }
  }

  function markOrderDirty(page) {
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

  function persistOrder(page, opts) {
    opts = opts || {};
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

    if (saveInflight) {
      return saveInflight.then(function () {
        if (state.dirty || opts.force) return persistOrder(page, opts);
        return { ok: true, skipped: true };
      });
    }

    var payload = collectOrderPayload(page);
    payload.customerName = customerName;
    var epochAtStart = dirtyEpoch;

    var saveBtn = null;
    if (!silent) {
      saveBtn = $('#pos-inv-save', page) || page.querySelector('[data-inv-action="save"]');
      if (saveBtn) saveBtn.disabled = true;
    }

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

    saveInflight = fetch(INVOICE_API, fetchOpts)
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
        if (!result.ok || !result.data.ok) {
          if (!silent) {
            toast((result.data && result.data.error) || 'Could not save invoice.');
          }
          return { ok: false, error: (result.data && result.data.error) || 'save failed' };
        }
        var invoice = result.data.invoice;
        var orderNo = (invoice && invoice.order_no) || payload.orderNo;
        if (invoice) {
          state.invoiceId = invoice.id;
          state.tableForOrder = invoice.table_label || invoice.table || state.tableForOrder;
        }
        clearDirtyAfterPersist(epochAtStart, page);
        if (toastOnSuccess) toast('Order ' + orderNo + ' saved.');
        return { ok: true, invoice: invoice };
      })
      .catch(function () {
        if (!silent) toast('Could not save invoice. Check your connection and try again.');
        return { ok: false, error: 'network' };
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
      saveOrder(page);
      return;
    }
    if (action === 'send-kot') {
      sendKot(page);
      return;
    }
    if (action === 'settle-bill' || action === 'close-table') {
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
      toast('Order hold is not available yet.');
      return;
    }
    if (action === 'clear') {
      closeMoreMenu(page);
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
        markOrderDirty(page);
        toast('Unsent items cleared. Kitchen-sent items were kept.');
      } else {
        state.dirty = false;
        cancelAutosaveTimer();
        toast('All items cleared.');
      }
      renderLines(page);
      return;
    }
    if (action === 'duplicate') {
      closeMoreMenu(page);
      toast('Duplicate order is not available yet.');
      return;
    }
    if (action === 'discount') {
      openDiscountModal(page);
      return;
    }
    if (action === 'service') {
      openServiceModal(page);
      return;
    }
    if (action === 'tip') {
      openTipModal(page);
      return;
    }
    if (action === 'coupon') {
      openCouponModal(page);
      return;
    }
    if (action === 'add-custom') {
      openCustomModal(page);
      return;
    }
    if (action === 'note-templates') {
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
      if (e.target.closest('[data-line-note]')) {
        openLineNoteModal(page, line);
        return;
      }
      if (e.target.closest('[data-del]')) {
        if (lineHasKitchenSent(line) && !canEditKitchenSentLines(page)) {
          toast('Only an administrator can remove items after they were sent to the kitchen.');
          return;
        }
        state.lines = state.lines.filter(function (l) {
          return l.uid !== id;
        });
        renderLines(page);
        if (state.lines.length) markOrderDirty(page);
        else {
          state.dirty = false;
          cancelAutosaveTimer();
        }
        return;
      }
      var qtyBtn = e.target.closest('[data-qty]');
      if (qtyBtn) {
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

    if (page.getAttribute('data-header-bound') === '1') return;
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

    var editOrder = $('#pos-inv-edit-order-no', page);
    if (editOrder) {
      editOrder.addEventListener('click', function () {
        var next = global.prompt('Order number', state.orderNo);
        if (next === null) return;
        next = String(next).trim();
        if (!next) return;
        state.orderNo = next;
        var el = $('#pos-inv-meta-order-no', page);
        if (el) el.textContent = next;
      });
    }

    page.addEventListener('click', function (e) {
      var actionEl = e.target.closest('[data-inv-action]');
      if (actionEl && page.contains(actionEl)) {
        handleAction(page, actionEl.getAttribute('data-inv-action'));
      }
      if (!e.target.closest('.pos-inv-more-wrap')) {
        closeMoreMenu(page);
      }
    });

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
      if (t.id === 'pos-inv-discount-amount') updateAdjPreview(page, 'discount');
      if (t.id === 'pos-inv-service-amount') updateAdjPreview(page, 'service');
      if (t.id === 'pos-inv-line-note-text') updateLineNoteCount(page);
    });

    page.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') {
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
  }

  function initPosInvoicePage() {
    var page = document.getElementById('pos-invoice-page');
    if (!page) return;

    /* Soft-nav remounts DOM — clear bind flags on fresh nodes; keep line state only on same session page */
    var freshMount = page.getAttribute('data-inv-mounted') !== '1';
    if (freshMount) {
      page.setAttribute('data-inv-mounted', '1');
      state.lines = [];
      state.discountType = 'pct';
      state.discountValue = 0;
      state.tipAmount = 0;
      state.tipEmployeeId = '';
      state.tipNote = '';
      state.tipPayrollId = null;
      state.serviceType = 'pct';
      state.serviceValue = DEFAULT_SERVICE_PCT;
      state.couponCode = '';
      state.orderNo = '';
      state.lineSeq = 0;
      state.invoiceId = null;
      state.tableForOrder = '';
      state.customerActiveIndex = -1;
      state.dirty = false;
      cancelAutosaveTimer();
      state.adjDraft = { discount: 'pct', service: 'pct' };
    }

    registerInvoiceLeaveHooks();
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
    updateNotesCount(page);

    if (typeof global.initEpListboxes === 'function') {
      global.initEpListboxes();
    }

    loadFloorTables(function (tables) {
      populateTables(page, tables, { loading: false });
      if (typeof global.initEpListboxes === 'function') {
        global.initEpListboxes();
      }
    });

    /* Arriving with ?invoice=... (Tables Invoice hub View) loads that bill.
       ?table=... still resumes the open dine-in order for a floor tile tap. */
    var prefInvoice = queryParam('invoice').trim();
    var prefTable = queryParam('table').trim();
    if (freshMount && prefTable) {
      applyPreferredTable(page, prefTable);
    }
    if (freshMount && prefInvoice) {
      resumeOrderById(page, prefInvoice);
    } else if (freshMount && prefTable) {
      resumeOrderForTable(page, prefTable, {
        silent: true,
        notFound: function () {
          /* No open bill yet — keep the floor tile's table selected for the new order. */
          applyPreferredTable(page, prefTable);
        }
      });
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

    var search = $('#pos-inv-search', page);
    if (search && !prefInvoice && !prefTable) {
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
