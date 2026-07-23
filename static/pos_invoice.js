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
  var customerCache = [];
  var customerCacheQuery = '';
  var customerSearchTimer = null;
  var GST_RATE = 0.05;
  var DEFAULT_SERVICE_PCT = 0;
  var MIN_QUERY = 2;
  var NOTES_MAX = 200;
  var INV_MODALS = ['custom', 'discount', 'service', 'tip', 'coupon'];

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
    serviceType: 'pct',
    serviceValue: DEFAULT_SERVICE_PCT,
    couponCode: '',
    activeIndex: -1,
    customerActiveIndex: -1,
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
    menuCatalogStatus = 'loading';
    var itemsPayload = null;
    var categoriesPayload = null;
    var failed = false;

    fetch(MENU_ITEMS_API, {
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
          if (typeof done === 'function') done(false);
          return;
        }
        if (!result || !result.ok || !Array.isArray(result.data.categories)) {
          menuCatalog.length = 0;
          menuCatalogById = {};
          menuCatalogStatus = 'error';
          if (typeof done === 'function') done(false);
          return;
        }
        categoriesPayload = result.data.categories;
        buildMenuCatalog(itemsPayload, categoriesPayload);
        if (typeof done === 'function') done(true);
      })
      .catch(function () {
        menuCatalog.length = 0;
        menuCatalogById = {};
        menuCatalogStatus = 'error';
        if (typeof done === 'function') done(false);
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

  function searchCustomersByMobile(q) {
    var digits = digitsOnly(q, 10);
    if (digits.length < MIN_QUERY) return [];
    if (customerCacheQuery === digits) return customerCache.slice();
    return customerCache.filter(function (c) {
      return String(c.mobile || '').indexOf(digits) === 0;
    }).slice(0, 8);
  }

  function fetchCustomersByMobile(q, done) {
    var digits = digitsOnly(q, 10);
    if (digits.length < MIN_QUERY) {
      customerCache = [];
      customerCacheQuery = '';
      if (done) done([]);
      return;
    }
    fetch(CUSTOMERS_API + '?q=' + encodeURIComponent(digits), {
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
        customerCacheQuery = digits;
        if (done) done(customerCache.slice());
      })
      .catch(function () {
        customerCache = [];
        customerCacheQuery = '';
        if (done) done([]);
      });
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
    var svcHint = $('#pos-inv-sum-service-hint', page);
    if (svcHint) svcHint.textContent = formatAdjHint(t.serviceType, t.serviceValue) || '';
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
      updateCloseTableButton(page);
      return;
    }

    if (empty) empty.hidden = true;

    body.innerHTML = state.lines
      .map(function (line) {
        var amt = (Number(line.rate) || 0) * (Number(line.qty) || 0);
        var pendingQty = pendingKotQty(line);
        return (
          '<tr data-line-id="' +
          escapeHtml(line.uid) +
          '">' +
          '<td><div class="pos-inv-item-cell">' +
          '<div class="pos-inv-item-thumb">' +
          (line.emoji ? escapeHtml(line.emoji) : '🍽️') +
          '</div>' +
          '<div><div class="pos-inv-item-name">' +
          escapeHtml(line.name) +
          '</div>' +
          (line.variant
            ? '<div class="pos-inv-item-variant">' + escapeHtml(line.variant) + '</div>'
            : '') +
          (pendingQty > 0
            ? '<span class="pos-inv-item-kot-tag" title="Not yet sent to kitchen">' +
              (pendingQty === Number(line.qty) ? 'New' : '+' + pendingQty + ' new') +
              '</span>'
            : '') +
          '</div></div></td>' +
          '<td class="pos-inv-col-qty"><div class="pos-inv-qty">' +
          '<button type="button" data-qty="-1" aria-label="Decrease quantity">−</button>' +
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
          '<td class="pos-inv-col-act">' +
          '<button type="button" class="pos-inv-del" data-del aria-label="Remove item">' +
          '<svg viewBox="0 0 24 24"><path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6M14 11v6"/></svg>' +
          '</button></td></tr>'
        );
      })
      .join('');

    renderSummary(page);
    updateKotBar(page);
    updateCloseTableButton(page);
  }

  function updateKotBar(page) {
    var btn = $('#pos-inv-send-kot', page);
    var status = $('#pos-inv-kot-status', page);
    var countEl = $('#pos-inv-send-kot-count', page);
    if (!btn) return;
    var pending = pendingKotLines();
    var pendingItems = pending.length;
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
          return (
            '<tr><td class="qty">' +
            entry.qty +
            '</td><td class="name">' +
            escapeHtml(line.name) +
            (line.variant ? '<div class="variant">' + escapeHtml(line.variant) + '</div>' : '') +
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

  /** Customer-facing bill — distinct from the kitchen KOT ticket above. Prints
   *  every line on the order (not just pending-KOT items) with rates, amounts,
   *  discount/GST/service/tip and the grand total. Prefers the persisted
   *  invoice (server totals + order no) so the printed bill always matches
   *  what was actually saved. */
  function printCustomerBill(page, invoice) {
    try {
      var win = global.open('', '_blank', 'width=420,height=680');
      if (!win) {
        toast('Could not open the bill window. Check your pop-up blocker.');
        return;
      }
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

      var html =
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
        '</style></head><body>' +
        '<h1>Hotel Bell Elite</h1>' +
        '<div class="sub">Customer Bill</div>' +
        '<div class="meta">' +
        '<div><span>Order</span><span>' + escapeHtml(orderNo) + '</span></div>' +
        '<div><span>Table</span><span>' + escapeHtml(table) + '</span></div>' +
        '<div><span>Type</span><span>' + escapeHtml(orderType) + '</span></div>' +
        '<div><span>Date</span><span>' + formatDate(now) + ' ' + formatTime(now) + '</span></div>' +
        custRow +
        '</div>' +
        '<table class="items"><thead><tr><th>Item</th><th class="qty">Qty</th><th class="rate">Rate</th><th class="amt">Amt</th></tr></thead>' +
        '<tbody>' + rows + '</tbody></table>' +
        '<div class="totals">' +
        '<div><span>Subtotal</span><span>' + money(totals.subtotal) + '</span></div>' +
        '<div><span>Discount' + (discHint ? ' ' + discHint : '') + '</span><span>-' + money(totals.discount) + '</span></div>' +
        '<div><span>GST (' + (GST_RATE * 100) + '%)</span><span>' + money(totals.gst) + '</span></div>' +
        '<div><span>Service Charge' + (svcHint ? ' ' + svcHint : '') + '</span><span>' + money(totals.service) + '</span></div>' +
        '<div><span>Tip</span><span>' + money(totals.tip) + '</span></div>' +
        '<div><span>Round Off</span><span>' + money(totals.roundOff) + '</span></div>' +
        '<div class="grand"><span>Total</span><span>' + money(totals.total) + '</span></div>' +
        '</div>' +
        '<div class="foot">Thank you for dining with us!</div>' +
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

    /* A KOT send persists the order (same as Save) and is the event that flips
       the table to occupied — see save_pos_invoice()'s kot_send handling. Once
       this session already owns a saved/resumed invoice (state.invoiceId), the
       table's own "occupied" status is this very order and must never block it. */
    var orderType = fieldValue('pos-inv-order-type-header', page) || fieldValue('pos-inv-order-type', page) || 'dine_in';
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
        printCustomerBill(page, invoice);
        toast('Bill ready for ' + ((invoice && invoice.order_no) || state.orderNo) + '.');
      })
      .catch(function () {
        toast('Could not generate the bill. Check your connection and try again.');
      })
      .then(function () {
        if (btn) btn.disabled = false;
        updateCloseTableButton(page);
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
        sentQty: 0
      });
    }
    renderLines(page);
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

  function populateTables(page, tablesIn, opts) {
    var list = $('#pos-inv-table-list', page);
    var input = $('#pos-inv-table', page);
    if (!list || !input) return;
    /* Floor data hasn't come back from the API yet — show a status row instead
       of leaving the panel blank, so the chip never looks unresponsive while it
       opens correctly but has nothing to render yet. */
    if (opts && opts.loading && !(tablesIn && tablesIn.length)) {
      list.innerHTML = '<div class="se-filter-listbox-status" role="presentation">Loading tables…</div>';
      return;
    }
    var tables = (tablesIn || loadFloorTablesSync()).slice().sort(function (a, b) {
      return String(a.name || '').localeCompare(String(b.name || ''), undefined, { numeric: true });
    });
    var pref = queryParam('table').trim();
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
        sentQty: Number(line.sent_qty) || 0
      };
    });

    var orderEl = $('#pos-inv-meta-order-no', page);
    if (orderEl) orderEl.textContent = state.orderNo;

    var nameEl = $('#pos-inv-customer-name', page);
    if (nameEl) nameEl.value = invoice.customer_name || '';
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

  function updateCloseTableButton(page) {
    var btn = $('#pos-inv-close-table', page);
    if (!btn) return;
    var orderType = fieldValue('pos-inv-order-type-header', page) || fieldValue('pos-inv-order-type', page) || 'dine_in';
    var table = fieldValue('pos-inv-table', page);
    btn.hidden = !(orderType === 'dine_in' && !!table && !!state.invoiceId);
  }

  /** Reset the on-screen session to a fresh, blank order — used after Close &
   *  Free Table so staff isn't left staring at a closed bill. */
  function resetOrderSession(page) {
    state.lines = [];
    state.discountType = 'pct';
    state.discountValue = 0;
    state.tipAmount = 0;
    state.serviceType = 'pct';
    state.serviceValue = DEFAULT_SERVICE_PCT;
    state.couponCode = '';
    state.orderNo = '';
    state.lineSeq = 0;
    state.invoiceId = null;
    state.tableForOrder = '';
    state.customerActiveIndex = -1;
    state.adjDraft = { discount: 'pct', service: 'pct' };
    initMeta(page);
    var nameEl = $('#pos-inv-customer-name', page);
    if (nameEl) nameEl.value = '';
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

  function closeAndFreeTable(page) {
    if (!state.invoiceId) return;
    var table = fieldValue('pos-inv-table', page) || 'this table';
    if (!global.confirm('Close this bill and free ' + table + ' for new guests?')) return;
    var btn = $('#pos-inv-close-table', page);
    if (btn) btn.disabled = true;
    fetch(INVOICE_API + '/' + encodeURIComponent(state.invoiceId) + '/close', {
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
            return { ok: res.ok, data: data };
          });
      })
      .then(function (result) {
        if (!result.ok || !result.data.ok) {
          toast((result.data && result.data.error) || 'Could not close the bill.');
          return;
        }
        toast(table + ' is now available.');
        resetOrderSession(page);
      })
      .catch(function () {
        toast('Could not close the bill. Check your connection and try again.');
      })
      .then(function () {
        if (btn) btn.disabled = false;
        updateCloseTableButton(page);
      });
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

  function openTipModal(page) {
    openInvModal(page, 'tip');
    var amount = $('#pos-inv-tip-amount', page);
    if (amount) {
      amount.value = String(state.tipAmount || 0);
      amount.focus();
      amount.select();
    }
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

  function applyTipModal(page) {
    var amountEl = $('#pos-inv-tip-amount', page);
    var n = amountEl ? Number(amountEl.value) : 0;
    if (isNaN(n) || n < 0) n = 0;
    state.tipAmount = n;
    closeInvModal(page, 'tip');
    renderSummary(page);
    toast(n ? 'Tip set to ' + money(n) : 'Tip cleared.');
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
    return {
      orderNo: state.orderNo,
      savedAt: new Date().toISOString(),
      orderType: fieldValue('pos-inv-order-type-header', page) || fieldValue('pos-inv-order-type', page) || 'dine_in',
      table: fieldValue('pos-inv-table', page),
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
          kotSentQty: Number(line.sentQty) || 0
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

  function saveOrder(page) {
    if (!state.lines.length) {
      toast('Add at least one item before saving.');
      var search = $('#pos-inv-search', page);
      if (search) search.focus();
      return;
    }

    /* Client-side belt on top of the server check in save_pos_invoice() — catches a
       table that was occupied by someone else after this page's floor snapshot loaded.
       Skipped once this session already owns a saved/resumed invoice (state.invoiceId):
       the table's own "occupied" status is then this very order, so it must never
       block Save/Send-KOT against it — only starting a brand-new bill is blocked. */
    var orderType = fieldValue('pos-inv-order-type-header', page) || fieldValue('pos-inv-order-type', page) || 'dine_in';
    if (orderType === 'dine_in' && !state.invoiceId && tableBlocksNewBill(selectedTableStatus(page))) {
      toast('This table is occupied. Choose another table or resume its order from the picker.');
      return;
    }

    var customerName = fieldValue('pos-inv-customer-name', page);
    if (!customerName) {
      toast('Enter customer name before saving.');
      var nameEl = $('#pos-inv-customer-name', page);
      if (nameEl) nameEl.focus();
      return;
    }

    if (!state.orderNo) {
      initMeta(page);
    }

    var payload = collectOrderPayload(page);
    var saveBtn = $('#pos-inv-save', page) || page.querySelector('[data-inv-action="save"]');
    if (saveBtn) saveBtn.disabled = true;

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
          toast((result.data && result.data.error) || 'Could not save invoice.');
          return;
        }
        var invoice = result.data.invoice;
        var orderNo = (invoice && invoice.order_no) || payload.orderNo;
        if (invoice) {
          state.invoiceId = invoice.id;
          state.tableForOrder = invoice.table_label || invoice.table || state.tableForOrder;
        }
        toast('Order ' + orderNo + ' saved.');
      })
      .catch(function () {
        toast('Could not save invoice. Check your connection and try again.');
      })
      .then(function () {
        if (saveBtn) saveBtn.disabled = false;
        updateCloseTableButton(page);
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
    if (action === 'close-table') {
      closeAndFreeTable(page);
      return;
    }
    if (action === 'print') {
      toast('Print is not available yet.');
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
    if (action === 'share') {
      toast('Share is not available yet.');
      return;
    }
    if (action === 'hold') {
      closeMoreMenu(page);
      toast('Order hold is not available yet.');
      return;
    }
    if (action === 'clear') {
      closeMoreMenu(page);
      state.lines = [];
      renderLines(page);
      toast('All items cleared.');
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
    toast('Customer details filled.');
  }

  function closeCustomerSuggest(page) {
    var box = $('#pos-inv-customer-suggest', page);
    var input = $('#pos-inv-customer-mobile', page);
    if (box) {
      box.hidden = true;
      box.innerHTML = '';
    }
    if (input) input.setAttribute('aria-expanded', 'false');
    state.customerActiveIndex = -1;
  }

  function renderCustomerSuggest(page, results) {
    var box = $('#pos-inv-customer-suggest', page);
    var input = $('#pos-inv-customer-mobile', page);
    if (!box) return;
    if (!results.length) {
      closeCustomerSuggest(page);
      return;
    }
    box.hidden = false;
    if (input) input.setAttribute('aria-expanded', 'true');
    box.innerHTML = results
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

    var mobile = $('#pos-inv-customer-mobile', page);
    if (mobile) {
      mobile.addEventListener('input', function () {
        mobile.value = digitsOnly(mobile.value, 10);
        if (customerSearchTimer) clearTimeout(customerSearchTimer);
        var query = mobile.value;
        if (digitsOnly(query, 10).length < MIN_QUERY) {
          closeCustomerSuggest(page);
          return;
        }
        customerSearchTimer = setTimeout(function () {
          fetchCustomersByMobile(query, function (matches) {
            if (digitsOnly(mobile.value, 10) !== digitsOnly(query, 10)) return;
            if (!matches.length) {
              closeCustomerSuggest(page);
              return;
            }
            state.customerActiveIndex = 0;
            renderCustomerSuggest(page, matches);
          });
        }, 180);
      });

      mobile.addEventListener('keydown', function (e) {
        var box = $('#pos-inv-customer-suggest', page);
        var open = box && !box.hidden;
        var items = open ? box.querySelectorAll('.pos-inv-customer-opt') : [];
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
          renderCustomerSuggest(page, searchCustomersByMobile(mobile.value));
          return;
        }
        if (e.key === 'ArrowUp') {
          e.preventDefault();
          state.customerActiveIndex = Math.max(0, state.customerActiveIndex - 1);
          renderCustomerSuggest(page, searchCustomersByMobile(mobile.value));
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

    if (!document.__posInvCustomerDocBound) {
      document.__posInvCustomerDocBound = true;
      document.addEventListener('click', function (e) {
        var root = document.getElementById('pos-invoice-page');
        if (!root) return;
        if (e.target.closest('#pos-inv-mobile-wrap')) return;
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
      if (e.target.closest('[data-del]')) {
        state.lines = state.lines.filter(function (l) {
          return l.uid !== id;
        });
        renderLines(page);
        return;
      }
      var qtyBtn = e.target.closest('[data-qty]');
      if (qtyBtn) {
        var delta = Number(qtyBtn.getAttribute('data-qty')) || 0;
        line.qty = Math.max(1, (Number(line.qty) || 1) + delta);
        /* Never claim more units were sent to the kitchen than currently on the line. */
        if ((Number(line.sentQty) || 0) > line.qty) line.sentQty = line.qty;
        renderLines(page);
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
    });

    page.addEventListener('keydown', function (e) {
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
      state.serviceType = 'pct';
      state.serviceValue = DEFAULT_SERVICE_PCT;
      state.couponCode = '';
      state.orderNo = '';
      state.lineSeq = 0;
      state.invoiceId = null;
      state.tableForOrder = '';
      state.customerActiveIndex = -1;
      state.adjDraft = { discount: 'pct', service: 'pct' };
    }

    populateTables(page, loadFloorTablesSync(), { loading: !floorTablesLoaded });
    initMeta(page);
    bindSearch(page);
    bindLines(page);
    bindHeader(page);
    bindModal(page);
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

    /* Arriving with ?table=... (Tables page tile tap, or the header picker) —
       resume that table's open order inline instead of always starting blank.
       No-ops quietly when the table is available (no open order to find). */
    var prefTable = queryParam('table').trim();
    if (freshMount && prefTable) {
      resumeOrderForTable(page, prefTable, { silent: true });
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
    if (search && !queryParam('table')) {
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
  } else {
    initPosInvoicePage();
  }
})(window);
