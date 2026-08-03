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

  /** ~80mm thermal character width (Consolas ~9.5pt). */
  var KOT_COLS = 42;

  function kotRule() {
    return '------------------------------------------'.slice(0, KOT_COLS);
  }

  function kotPad(left, right) {
    left = String(left == null ? '' : left);
    right = String(right == null ? '' : right);
    var gap = KOT_COLS - left.length - right.length;
    if (gap < 1) {
      left = left.slice(0, Math.max(0, KOT_COLS - right.length - 1));
      gap = Math.max(1, KOT_COLS - left.length - right.length);
    }
    var spaces = '';
    for (var i = 0; i < gap; i++) spaces += ' ';
    return left + spaces + right;
  }

  function kotCenter(text) {
    text = String(text == null ? '' : text);
    if (text.length >= KOT_COLS) return text.slice(0, KOT_COLS);
    var pad = Math.floor((KOT_COLS - text.length) / 2);
    var spaces = '';
    for (var i = 0; i < pad; i++) spaces += ' ';
    return spaces + text;
  }

  function kotTableNo(label) {
    var raw = String(label == null ? '' : label).trim();
    var m = raw.match(/(\d+)\s*$/);
    if (m) return m[1];
    return raw.replace(/^table\s*/i, '').trim() || raw || '—';
  }

  function kotFormatDate(d) {
    var dt = d instanceof Date ? d : new Date();
    var months = [
      'Jan',
      'Feb',
      'Mar',
      'Apr',
      'May',
      'Jun',
      'Jul',
      'Aug',
      'Sep',
      'Oct',
      'Nov',
      'Dec'
    ];
    var day = String(dt.getDate()).padStart(2, '0');
    var mon = months[dt.getMonth()] || '';
    var year = dt.getFullYear();
    var h = dt.getHours();
    var m = dt.getMinutes();
    var ampm = h >= 12 ? 'PM' : 'AM';
    h = h % 12;
    if (!h) h = 12;
    return (
      day +
      '-' +
      mon +
      '-' +
      year +
      ' ' +
      h +
      ':' +
      String(m).padStart(2, '0') +
      ' ' +
      ampm
    );
  }

  function getKotReceiptMeta(outlet) {
    var o = resolveOutlet(outlet);
    var cfg =
      typeof global.getPosReceiptConfig === 'function'
        ? global.getPosReceiptConfig(o)
        : null;
    if (!cfg && typeof document !== 'undefined') {
      try {
        var el = document.getElementById('pos-receipt-config-data');
        if (el) cfg = JSON.parse(el.textContent || '{}');
      } catch (e) {
        cfg = null;
      }
    }
    cfg = cfg || {};
    return {
      brand: 'HOTEL BELL ELITE',
      business:
        cfg.business_name ||
        (o === 'bar' ? 'IRISH BARREL HOUSE BAR' : 'SPICE MULTICUISINE'),
      userLabel: cfg.user_label || (o === 'bar' ? 'BAR' : 'RESTAURANT'),
      kitchenLabel: o === 'bar' ? 'BAR' : 'KITCHEN'
    };
  }

  /**
   * Compact 80mm ORDER TICKET layout (plain text — no markup tags).
   * Prefer formatKotTicketEscPos for thermal printers (full paper width).
   */
  function formatKotTicketText(opts) {
    opts = opts || {};
    var meta = getKotReceiptMeta(opts.menuOutlet || opts.outlet);
    var orderNo = opts.orderNo || '—';
    var orderType = opts.orderType || 'Dine In';
    var tableNo = kotTableNo(opts.tableLabel);
    var when = opts.when instanceof Date ? opts.when : new Date();
    var items = Array.isArray(opts.items) ? opts.items : [];
    var isResend = !!opts.resend;
    var rule = kotRule();
    var lines = [
      kotCenter(meta.brand),
      kotCenter(String(meta.business).toUpperCase()),
      rule,
      'Order No. : ' + orderNo,
      'Order Type : ' + orderType,
      'Date : ' + kotFormatDate(when),
      'Table No. : ' + tableNo,
      'Kitchen : ' + meta.kitchenLabel,
      'User : ' + meta.userLabel,
      rule
    ];
    if (isResend) {
      lines.push(kotCenter('REPRINT / RESEND'));
      lines.push(rule);
    }
    lines.push(kotCenter('ORDER TICKET'));
    lines.push(rule);
    lines.push(kotPad('Items', 'Qty'));
    lines.push(rule);
    var totalQty = 0;
    items.forEach(function (it) {
      var qty = Number(it.qty) || 0;
      totalQty += qty;
      var name = String(it.name || '')
        .trim()
        .toUpperCase();
      lines.push(kotPad(name, String(qty)));
      if (it.variant) lines.push('  ' + String(it.variant).trim());
      if (it.notes) lines.push('  Note: ' + String(it.notes).trim());
    });
    lines.push(rule);
    lines.push(kotPad('Total Items', String(totalQty)));
    lines.push(rule);
    lines.push('');
    return lines.join('\n');
  }

  function escPosEncodeAscii(str) {
    var s = String(str == null ? '' : str);
    var out = '';
    for (var i = 0; i < s.length; i++) {
      var c = s.charCodeAt(i);
      out += c < 128 ? s.charAt(i) : '?';
    }
    return out;
  }

  function toBase64Binary(binStr) {
    if (typeof btoa !== 'function') return '';
    return btoa(String(binStr || ''));
  }

  /**
   * ESC/POS bytes for 80mm kitchen printers — full width, no GDI wrap.
   * Works with existing Hotel Print Agent (contentType: escpos).
   */
  function formatKotTicketEscPos(opts) {
    opts = opts || {};
    var ESC = '\x1b';
    var GS = '\x1d';
    var meta = getKotReceiptMeta(opts.menuOutlet || opts.outlet);
    var orderNo = opts.orderNo || '—';
    var orderType = opts.orderType || 'Dine In';
    var tableNo = kotTableNo(opts.tableLabel);
    var when = opts.when instanceof Date ? opts.when : new Date();
    var items = Array.isArray(opts.items) ? opts.items : [];
    var isResend = !!opts.resend;
    var rule = kotRule();
    var parts = [];

    function raw(s) {
      parts.push(s);
    }
    function line(s) {
      parts.push(escPosEncodeAscii(s) + '\n');
    }
    function center(on) {
      raw(ESC + 'a' + (on ? '\x01' : '\x00'));
    }
    function bold(on) {
      raw(ESC + 'E' + (on ? '\x01' : '\x00'));
    }
    function doubleH(on) {
      /* GS ! n — bit 0/4 double height/width */
      raw(GS + '!' + (on ? '\x11' : '\x00'));
    }

    raw(ESC + '@'); /* initialize */
    center(true);
    bold(true);
    line(meta.brand);
    line(String(meta.business).toUpperCase());
    bold(false);
    center(false);
    line(rule);
    line('Order No. : ' + orderNo);
    line('Order Type : ' + orderType);
    line('Date : ' + kotFormatDate(when));
    bold(true);
    doubleH(true);
    line('Table No. : ' + tableNo);
    doubleH(false);
    bold(false);
    line('Kitchen : ' + meta.kitchenLabel);
    line('User : ' + meta.userLabel);
    line(rule);
    if (isResend) {
      center(true);
      bold(true);
      line('REPRINT / RESEND');
      bold(false);
      center(false);
      line(rule);
    }
    center(true);
    bold(true);
    line('ORDER TICKET');
    bold(false);
    center(false);
    line(rule);
    bold(true);
    line(kotPad('Items', 'Qty'));
    bold(false);
    line(rule);
    var totalQty = 0;
    items.forEach(function (it) {
      var qty = Number(it.qty) || 0;
      totalQty += qty;
      var name = String(it.name || '')
        .trim()
        .toUpperCase();
      bold(true);
      line(kotPad(name, String(qty)));
      bold(false);
      if (it.variant) line('  ' + String(it.variant).trim());
      if (it.notes) line('  Note: ' + String(it.notes).trim());
    });
    line(rule);
    bold(true);
    line(kotPad('Total Items', String(totalQty)));
    bold(false);
    line(rule);
    raw('\n\n');
    /* Partial cut if supported; ignored by printers that don't. */
    raw(GS + 'V' + '\x01');
    return parts.join('');
  }

  /**
   * Send a KOT slip to the Restaurant or Bar KOT printer via Hotel Print
   * Agent (silent — no Chrome print dialog).
   * Prefers ESC/POS for full-width thermal output on existing EXE builds.
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

    var kot = opts.kot || null;
    var text =
      opts.text ||
      (kot ? formatKotTicketText(kot) : '');
    var escposB64 = '';
    if (kot) {
      try {
        escposB64 = toBase64Binary(formatKotTicketEscPos(kot));
      } catch (e) {
        escposB64 = '';
      }
    }

    if (!html && !text && !escposB64) {
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

    var job = {
      printerRole: role,
      documentType: 'kot',
      copies: opts.copies || 1,
      jobId: opts.jobId || undefined,
      idempotencyKey: opts.idempotencyKey || opts.jobId || undefined
    };
    if (escposB64) {
      job.contentType = 'escpos';
      job.contentEncoding = 'base64';
      job.content = escposB64;
    } else if (text) {
      job.contentType = 'text';
      job.contentEncoding = 'utf8';
      job.content = String(text);
    } else {
      job.contentType = opts.contentType || 'html';
      job.contentEncoding = 'utf8';
      job.content = html;
    }

    // #region agent log
    (function (payload) {
      var body = JSON.stringify(payload);
      fetch('http://127.0.0.1:7764/ingest/3c15e9d7-8289-4a1b-877f-c72ceeda0753',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'42fa9a'},body:body}).catch(function(){});
      fetch('/api/hbe-agent-debug',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-Requested-With':'XMLHttpRequest'},body:body}).catch(function(){});
    })({sessionId:'42fa9a',runId:'post-fix',hypothesisId:'G',location:'pos_printers.js:printKotHtml.attempt',message:'calling HotelPrintAgent.print',data:{role:role,contentType:job.contentType,contentEncoding:job.contentEncoding,textLen:text?String(text).length:0,escposLen:escposB64?escposB64.length:0,textPreview:text?String(text).slice(0,100):''},timestamp:Date.now()});
    // #endregion

    return global.HotelPrintAgent.print(job)
      .then(function (data) {
        // #region agent log
        (function (payload) {
          var body = JSON.stringify(payload);
          fetch('http://127.0.0.1:7764/ingest/3c15e9d7-8289-4a1b-877f-c72ceeda0753',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'42fa9a'},body:body}).catch(function(){});
          fetch('/api/hbe-agent-debug',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-Requested-With':'XMLHttpRequest'},body:body}).catch(function(){});
        })({sessionId:'42fa9a',runId:'post-fix',hypothesisId:'G',location:'pos_printers.js:printKotHtml.ok',message:'agent print ok',data:{role:role,printerName:data&&data.printerName,jobId:data&&data.jobId,contentType:job.contentType},timestamp:Date.now()});
        // #endregion
        return { via: 'agent', data: data };
      })
      .catch(function (err) {
        /* If RAW/ESC-POS rejected by driver, fall back to plain text once. */
        if (job.contentType === 'escpos' && text) {
          // #region agent log
          (function (payload) {
            var body = JSON.stringify(payload);
            fetch('http://127.0.0.1:7764/ingest/3c15e9d7-8289-4a1b-877f-c72ceeda0753',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'42fa9a'},body:body}).catch(function(){});
            fetch('/api/hbe-agent-debug',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-Requested-With':'XMLHttpRequest'},body:body}).catch(function(){});
          })({sessionId:'42fa9a',runId:'post-fix',hypothesisId:'G',location:'pos_printers.js:printKotHtml.escposFallback',message:'escpos failed, trying text',data:{err:err&&err.message},timestamp:Date.now()});
          // #endregion
          return global.HotelPrintAgent.print({
            printerRole: role,
            documentType: 'kot',
            contentType: 'text',
            contentEncoding: 'utf8',
            content: String(text),
            copies: opts.copies || 1,
            jobId: (opts.jobId || 'kot') + '-txt',
            idempotencyKey: ((opts.idempotencyKey || opts.jobId || '') + '-txt') || undefined
          })
            .then(function (data) {
              return { via: 'agent', data: data, fallback: 'text' };
            })
            .catch(function (err2) {
              return fail(err2 || err);
            });
        }
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
    formatKotTicketText: formatKotTicketText,
    formatKotTicketEscPos: formatKotTicketEscPos,
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
