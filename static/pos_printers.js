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
    /**
     * Printer-safe emphasis. Many Windows/RAW thermal stacks ignore GS ! alone;
     * ESC ! bit flags are more widely honored (Champ / RP series).
     * opts: { bold, doubleH, doubleW }
     */
    function textStyle(opts) {
      opts = opts || {};
      var n = 0;
      if (opts.bold) n |= 0x08;
      if (opts.doubleH) n |= 0x10;
      if (opts.doubleW) n |= 0x20;
      raw(ESC + '!' + String.fromCharCode(n));
      /* Mirror with GS ! for firmwares that prefer it. */
      var w = opts.doubleW ? 1 : 0;
      var h = opts.doubleH ? 1 : 0;
      raw(GS + '!' + String.fromCharCode((w << 4) | h));
      if (opts.bold) raw(ESC + 'E' + '\x01');
      else raw(ESC + 'E' + '\x00');
    }

    raw(ESC + '@'); /* initialize */
    center(true);
    textStyle({ bold: true });
    line(meta.brand);
    /* Spice / outlet: larger + bold (double width & height). */
    textStyle({ bold: true, doubleH: true, doubleW: true });
    line(String(meta.business).toUpperCase());
    textStyle({});
    center(false);
    line(rule);
    line('Order No. : ' + orderNo);
    line('Order Type : ' + orderType);
    line('Date : ' + kotFormatDate(when));
    /* Table No: normal size, bold only (no double). */
    textStyle({ bold: true });
    line('Table No. : ' + tableNo);
    textStyle({});
    line('Kitchen : ' + meta.kitchenLabel);
    line('User : ' + meta.userLabel);
    line(rule);
    if (isResend) {
      center(true);
      textStyle({ bold: true });
      line('REPRINT / RESEND');
      textStyle({});
      center(false);
      line(rule);
    }
    center(true);
    textStyle({ bold: true });
    line('ORDER TICKET');
    textStyle({});
    center(false);
    line(rule);
    textStyle({ bold: true });
    line(kotPad('Items', 'Qty'));
    textStyle({});
    line(rule);
    var totalQty = 0;
    items.forEach(function (it) {
      var qty = Number(it.qty) || 0;
      totalQty += qty;
      var name = String(it.name || '')
        .trim()
        .toUpperCase();
      textStyle({ bold: true });
      line(kotPad(name, String(qty)));
      textStyle({});
      if (it.variant) line('  ' + String(it.variant).trim());
      if (it.notes) line('  Note: ' + String(it.notes).trim());
    });
    line(rule);
    textStyle({ bold: true });
    line(kotPad('Total Items', String(totalQty)));
    textStyle({});
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


    return global.HotelPrintAgent.print(job)
      .then(function (data) {
        return { via: 'agent', data: data };
      })
      .catch(function (err) {
        /* If RAW/ESC-POS rejected by driver, fall back to plain text once. */
        if (job.contentType === 'escpos' && text) {
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

  function billAmt(n) {
    var v = Math.round((Number(n) || 0) * 100) / 100;
    return v.toFixed(2);
  }

  function billPadLeft(s, width) {
    s = String(s == null ? '' : s);
    if (s.length >= width) return s.slice(-width);
    var pad = '';
    for (var i = 0; i < width - s.length; i++) pad += ' ';
    return pad + s;
  }

  function billWrap(text, width) {
    var words = String(text || '')
      .replace(/\s+/g, ' ')
      .trim()
      .split(' ');
    var lines = [];
    var cur = '';
    words.forEach(function (w) {
      if (!w) return;
      if (!cur) {
        cur = w;
        return;
      }
      if ((cur + ' ' + w).length <= width) {
        cur += ' ' + w;
      } else {
        lines.push(cur);
        cur = w;
      }
    });
    if (cur) lines.push(cur);
    return lines.length ? lines : [''];
  }

  function billActiveTaxRates() {
    var rates = global.HBE_POS_TAX_RATES;
    if (!rates || typeof rates !== 'object') {
      return { cgst: 0.025, ugst: 0.025, vat: 0.1 };
    }
    return {
      cgst: rates.cgst != null && isFinite(Number(rates.cgst)) ? Number(rates.cgst) : 0.025,
      ugst: rates.ugst != null && isFinite(Number(rates.ugst)) ? Number(rates.ugst) : 0.025,
      vat: rates.vat != null && isFinite(Number(rates.vat)) ? Number(rates.vat) : 0.1
    };
  }

  function billNormalizeTotals(invoice) {
    var gst = Number(invoice && invoice.gst != null ? invoice.gst : 0);
    return {
      subtotal: Number(invoice && invoice.subtotal != null ? invoice.subtotal : 0),
      discount: Number(invoice && invoice.discount != null ? invoice.discount : 0),
      gst: gst,
      vat: Number(invoice && invoice.vat != null ? invoice.vat : 0),
      cgst: invoice && invoice.cgst != null ? Number(invoice.cgst) : gst / 2,
      ugst: invoice && invoice.ugst != null ? Number(invoice.ugst) : gst / 2,
      service: Number(invoice && invoice.service != null ? invoice.service : 0),
      tip: Number(invoice && invoice.tip != null ? invoice.tip : 0),
      roundOff: Number(invoice && invoice.round_off != null ? invoice.round_off : 0),
      total: Number(
        invoice && invoice.grand_total != null
          ? invoice.grand_total
          : invoice && invoice.total != null
            ? invoice.total
            : 0
      )
    };
  }

  function billResolveDate(invoice) {
    var raw = String(
      (invoice && (invoice.saved_at || invoice.created_at || invoice.order_date)) || ''
    ).trim();
    if (!raw) return new Date();
    var normalized = raw.indexOf('T') >= 0 ? raw : raw.replace(' ', 'T');
    var parsed = new Date(normalized);
    return !isNaN(parsed.getTime()) ? parsed : new Date();
  }

  function billItemRows(name, qty, rate, amt) {
    var right =
      billPadLeft(String(qty), 3) +
      ' ' +
      billPadLeft(billAmt(rate), 7) +
      ' ' +
      billPadLeft(billAmt(amt), 8);
    var nameWidth = Math.max(8, KOT_COLS - right.length - 1);
    var nm = String(name || '')
      .trim()
      .toUpperCase();
    var rows = [];
    if (nm.length <= nameWidth) {
      rows.push(kotPad(nm, right));
      return rows;
    }
    /* Wrap long names; amounts stay on the first line. */
    var chunks = billWrap(nm, nameWidth);
    rows.push(kotPad(chunks[0], right));
    for (var i = 1; i < chunks.length; i++) {
      rows.push(String(chunks[i]).slice(0, KOT_COLS));
    }
    return rows;
  }

  function billPaymentLabel(pay) {
    if (pay && pay.payment_method_label) return String(pay.payment_method_label);
    var raw = String((pay && pay.payment_method) || 'Cash')
      .replace(/_/g, ' ')
      .trim();
    if (!raw) return 'Cash';
    var lower = raw.toLowerCase();
    if (lower === 'upi') return 'UPI';
    if (lower === 'card') return 'Card';
    if (lower === 'cash') return 'Cash';
    return raw.replace(/\b\w/g, function (c) {
      return c.toUpperCase();
    });
  }

  /**
   * Plain-text Spice-style guest bill for thermal printers (no HTML/CSS).
   */
  function formatCustomerBillText(invoice, opts) {
    opts = opts || {};
    invoice = invoice || {};
    var o = resolveOutlet(opts.outlet || invoice.outlet);
    var meta = getKotReceiptMeta(o);
    var cfg =
      typeof global.getPosReceiptConfig === 'function'
        ? global.getPosReceiptConfig(o)
        : {};
    var totals = billNormalizeTotals(invoice);
    var rates = billActiveTaxRates();
    var when = billResolveDate(invoice);
    var orderNo = invoice.order_no || '—';
    var table = invoice.table_label || invoice.table || '—';
    var lines = Array.isArray(invoice.lines) ? invoice.lines : [];
    var rule = kotRule();
    var out = [];

    out.push(kotCenter(String(meta.business || cfg.business_name || '').toUpperCase()));
    billWrap(cfg.address || '', KOT_COLS).forEach(function (ln) {
      out.push(kotCenter(ln));
    });
    var taxLine = 'GST ' + (cfg.gst || '');
    if (cfg.fssai) taxLine += ' | FSSAI ' + cfg.fssai;
    billWrap(taxLine, KOT_COLS).forEach(function (ln) {
      out.push(kotCenter(ln));
    });
    out.push(rule);
    out.push(kotPad('Invoice', String(orderNo)));
    out.push(kotPad('Date', kotFormatDate(when)));
    out.push(kotPad('Table', String(table)));
    out.push(rule);
    out.push(
      kotPad(
        'ITEMS',
        billPadLeft('QTY', 3) + ' ' + billPadLeft('RATE', 7) + ' ' + billPadLeft('AMOUNT', 8)
      )
    );
    out.push(rule);
    if (!lines.length) {
      out.push(kotCenter('No items'));
    } else {
      lines.forEach(function (line) {
        var qty = Number(line.qty) || 0;
        var rate = Number(line.rate) || 0;
        var amt = line.line_total != null ? Number(line.line_total) : rate * qty;
        billItemRows(line.name, qty, rate, amt).forEach(function (row) {
          out.push(row);
        });
      });
    }
    out.push(rule);
    out.push(kotPad('Sub-Total', billAmt(totals.subtotal)));
    if (Number(totals.discount) > 0) {
      out.push(kotPad('Discount', '-' + billAmt(totals.discount)));
    }
    out.push(kotPad('CGST @ ' + rates.cgst * 100 + '%', billAmt(totals.cgst)));
    out.push(kotPad('UGST @ ' + rates.ugst * 100 + '%', billAmt(totals.ugst)));
    if (Number(totals.vat) > 0) {
      out.push(kotPad('VAT @ ' + rates.vat * 100 + '%', billAmt(totals.vat)));
    }
    if (Number(totals.service) > 0) {
      out.push(kotPad('Service Charge', billAmt(totals.service)));
    }
    if (Number(totals.tip) > 0) {
      out.push(kotPad('Tip', billAmt(totals.tip)));
    }
    if (Math.abs(Number(totals.roundOff) || 0) >= 0.005) {
      out.push(kotPad('Round-Off', billAmt(totals.roundOff)));
    }
    out.push(rule);
    out.push(kotPad('TOTAL', billAmt(totals.total)));
    var payments = Array.isArray(invoice.payments) ? invoice.payments : [];
    if (payments.length) {
      out.push(rule);
      out.push(kotCenter('RECEIPTS'));
      payments.forEach(function (pay) {
        out.push(kotPad(billPaymentLabel(pay), billAmt(pay.amount)));
      });
    }
    out.push('');
    out.push('User : ' + (cfg.user_label || meta.userLabel || 'RESTAURANT'));
    out.push('');
    return out.join('\n');
  }

  /** ESC/POS bytes for 80mm guest invoice — avoids HTML/CSS dump on thermal. */
  function formatCustomerBillEscPos(invoice, opts) {
    opts = opts || {};
    invoice = invoice || {};
    var ESC = '\x1b';
    var GS = '\x1d';
    var o = resolveOutlet(opts.outlet || invoice.outlet);
    var meta = getKotReceiptMeta(o);
    var cfg =
      typeof global.getPosReceiptConfig === 'function'
        ? global.getPosReceiptConfig(o)
        : {};
    var totals = billNormalizeTotals(invoice);
    var rates = billActiveTaxRates();
    var when = billResolveDate(invoice);
    var orderNo = invoice.order_no || '—';
    var table = invoice.table_label || invoice.table || '—';
    var items = Array.isArray(invoice.lines) ? invoice.lines : [];
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
    function textStyle(styleOpts) {
      styleOpts = styleOpts || {};
      var n = 0;
      if (styleOpts.bold) n |= 0x08;
      if (styleOpts.doubleH) n |= 0x10;
      if (styleOpts.doubleW) n |= 0x20;
      raw(ESC + '!' + String.fromCharCode(n));
      var w = styleOpts.doubleW ? 1 : 0;
      var h = styleOpts.doubleH ? 1 : 0;
      raw(GS + '!' + String.fromCharCode((w << 4) | h));
      if (styleOpts.bold) raw(ESC + 'E' + '\x01');
      else raw(ESC + 'E' + '\x00');
    }

    raw(ESC + '@');
    center(true);
    textStyle({ bold: true, doubleH: true });
    line(String(meta.business || cfg.business_name || '').toUpperCase());
    textStyle({});
    billWrap(cfg.address || '', KOT_COLS).forEach(function (ln) {
      line(ln);
    });
    var taxLine = 'GST ' + (cfg.gst || '');
    if (cfg.fssai) taxLine += ' | FSSAI ' + cfg.fssai;
    billWrap(taxLine, KOT_COLS).forEach(function (ln) {
      line(ln);
    });
    center(false);
    line(rule);
    line(kotPad('Invoice', String(orderNo)));
    line(kotPad('Date', kotFormatDate(when)));
    textStyle({ bold: true });
    line(kotPad('Table', String(table)));
    textStyle({});
    line(rule);
    textStyle({ bold: true });
    line(
      kotPad(
        'ITEMS',
        billPadLeft('QTY', 3) + ' ' + billPadLeft('RATE', 7) + ' ' + billPadLeft('AMOUNT', 8)
      )
    );
    textStyle({});
    line(rule);
    if (!items.length) {
      center(true);
      line('No items');
      center(false);
    } else {
      items.forEach(function (it) {
        var qty = Number(it.qty) || 0;
        var rate = Number(it.rate) || 0;
        var amt = it.line_total != null ? Number(it.line_total) : rate * qty;
        billItemRows(it.name, qty, rate, amt).forEach(function (row) {
          line(row);
        });
      });
    }
    line(rule);
    line(kotPad('Sub-Total', billAmt(totals.subtotal)));
    if (Number(totals.discount) > 0) {
      line(kotPad('Discount', '-' + billAmt(totals.discount)));
    }
    line(kotPad('CGST @ ' + rates.cgst * 100 + '%', billAmt(totals.cgst)));
    line(kotPad('UGST @ ' + rates.ugst * 100 + '%', billAmt(totals.ugst)));
    if (Number(totals.vat) > 0) {
      line(kotPad('VAT @ ' + rates.vat * 100 + '%', billAmt(totals.vat)));
    }
    if (Number(totals.service) > 0) {
      line(kotPad('Service Charge', billAmt(totals.service)));
    }
    if (Number(totals.tip) > 0) {
      line(kotPad('Tip', billAmt(totals.tip)));
    }
    if (Math.abs(Number(totals.roundOff) || 0) >= 0.005) {
      line(kotPad('Round-Off', billAmt(totals.roundOff)));
    }
    line(rule);
    textStyle({ bold: true, doubleH: true });
    line(kotPad('TOTAL', billAmt(totals.total)));
    textStyle({});
    var payments = Array.isArray(invoice.payments) ? invoice.payments : [];
    if (payments.length) {
      line(rule);
      center(true);
      textStyle({ bold: true });
      line('RECEIPTS');
      textStyle({});
      center(false);
      payments.forEach(function (pay) {
        line(kotPad(billPaymentLabel(pay), billAmt(pay.amount)));
      });
    }
    line('');
    line('User : ' + (cfg.user_label || meta.userLabel || 'RESTAURANT'));
    raw('\n\n');
    raw(GS + 'V' + '\x01');
    return parts.join('');
  }

  /**
   * Silent invoice/bill print via Hotel Print Agent (billing role).
   * Prefers ESC/POS (same path as KOT) — HTML contentType is printed as raw
   * text by some agent builds and dumps CSS onto the thermal paper.
   * Set opts.allowBrowserFallback = true to open Chrome print as a last resort.
   */
  function printInvoiceHtml(html, opts) {
    opts = opts || {};
    var role = invoicePrinterRole(opts.outlet);
    var allowBrowser = opts.allowBrowserFallback === true;
    var browserPrint =
      typeof opts.browserPrint === 'function' ? opts.browserPrint : function () {};
    var invoice = opts.invoice || opts.bill || null;

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

    if (!html && !invoice) {
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

    var text = '';
    var escposB64 = '';
    if (invoice) {
      try {
        text = formatCustomerBillText(invoice, { outlet: opts.outlet });
      } catch (e) {
        text = '';
      }
      try {
        escposB64 = toBase64Binary(formatCustomerBillEscPos(invoice, { outlet: opts.outlet }));
      } catch (e2) {
        escposB64 = '';
      }
    }

    var job = {
      printerRole: role,
      documentType: opts.documentType || 'receipt',
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
    } else if (html) {
      /* Last resort — may dump CSS on older agents; prefer passing opts.invoice. */
      job.contentType = 'html';
      job.contentEncoding = 'utf8';
      job.content = html;
    } else {
      return Promise.resolve(fail(new Error('Nothing to print.')));
    }

    return global.HotelPrintAgent.print(job)
      .then(function (data) {
        return { via: 'agent', data: data };
      })
      .catch(function (err) {
        if (job.contentType === 'escpos' && text) {
          return global.HotelPrintAgent.print({
            printerRole: role,
            documentType: opts.documentType || 'receipt',
            contentType: 'text',
            contentEncoding: 'utf8',
            content: String(text),
            copies: opts.copies || 1,
            jobId: (opts.jobId || 'inv') + '-txt',
            idempotencyKey:
              (opts.idempotencyKey || opts.jobId || '') + '-txt' || undefined
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

  /**
   * Local KOT simulation: build a thermal-width PDF and trigger browser download
   * (typically ~/Downloads). Used to verify layout before silent Print Agent jobs.
   */
  function downloadKotTicketPdf(opts, filename) {
    opts = opts || {};
    var meta = getKotReceiptMeta(opts.menuOutlet || opts.outlet);
    var orderNo = String(opts.orderNo || '—');
    var orderType = String(opts.orderType || 'Dine In');
    var tableNo = kotTableNo(opts.tableLabel);
    var when = opts.when instanceof Date ? opts.when : new Date();
    var items = Array.isArray(opts.items) ? opts.items : [];
    var isResend = !!opts.resend;
    var rule = kotRule();
    var pageW = 226.77; /* 80mm */
    var margin = 14;
    var contentW = pageW - margin * 2;
    var rows = [];

    function add(text, font, size, align) {
      rows.push({
        text: String(text == null ? '' : text),
        font: font || 'F1',
        size: size || 9,
        align: align || 'left'
      });
    }
    function addGap(h) {
      rows.push({ gap: h || 4 });
    }

    add(meta.brand, 'F2', 11, 'center');
    add(String(meta.business).toUpperCase(), 'F2', 15, 'center'); /* +size, bold */
    addGap(3);
    add(rule, 'F1', 8, 'left');
    add('Order No. : ' + orderNo, 'F1', 9, 'left');
    add('Order Type : ' + orderType, 'F1', 9, 'left');
    add('Date : ' + kotFormatDate(when), 'F1', 9, 'left');
    add('Table No. : ' + tableNo, 'F2', 11, 'left'); /* bold, not double-size */
    add('Kitchen : ' + meta.kitchenLabel, 'F1', 9, 'left');
    add('User : ' + meta.userLabel, 'F1', 9, 'left');
    add(rule, 'F1', 8, 'left');
    if (isResend) {
      add('REPRINT / RESEND', 'F2', 10, 'center');
      add(rule, 'F1', 8, 'left');
    }
    add('ORDER TICKET', 'F2', 11, 'center');
    add(rule, 'F1', 8, 'left');
    add(kotPad('Items', 'Qty'), 'F2', 9, 'left');
    add(rule, 'F1', 8, 'left');
    var totalQty = 0;
    items.forEach(function (it) {
      var qty = Number(it.qty) || 0;
      totalQty += qty;
      add(
        kotPad(
          String(it.name || '')
            .trim()
            .toUpperCase(),
          String(qty)
        ),
        'F2',
        9,
        'left'
      );
      if (it.variant) add('  ' + String(it.variant).trim(), 'F1', 8, 'left');
      if (it.notes) add('  Note: ' + String(it.notes).trim(), 'F1', 8, 'left');
    });
    add(rule, 'F1', 8, 'left');
    add(kotPad('Total Items', String(totalQty)), 'F2', 9, 'left');
    add(rule, 'F1', 8, 'left');

    var y = 0;
    var lineHs = [];
    rows.forEach(function (r) {
      if (r.gap) {
        lineHs.push(r.gap);
        y += r.gap;
        return;
      }
      var h = (r.size || 9) * 1.25;
      lineHs.push(h);
      y += h;
    });
    var pageH = Math.max(200, margin * 2 + y + 16);

    function esc(s) {
      return String(s)
        .replace(/\\/g, '\\\\')
        .replace(/\(/g, '\\(')
        .replace(/\)/g, '\\)');
    }

    var stream = 'BT\n';
    var cursor = pageH - margin;
    rows.forEach(function (r, idx) {
      var h = lineHs[idx];
      if (r.gap) {
        cursor -= h;
        return;
      }
      cursor -= h;
      var font = r.font === 'F2' ? '/F2' : '/F1';
      var size = r.size || 9;
      var x = margin;
      if (r.align === 'center') {
        /* Approximate center using average char width ~0.5*size for Helvetica. */
        var approx = String(r.text).length * size * 0.5;
        x = Math.max(margin, (pageW - approx) / 2);
      }
      /* Use Tm (absolute), not Td — relative Td stacked Y and pushed lines off-page. */
      stream +=
        font +
        ' ' +
        size +
        ' Tf\n1 0 0 1 ' +
        x.toFixed(2) +
        ' ' +
        cursor.toFixed(2) +
        ' Tm\n(' +
        esc(r.text) +
        ') Tj\n';
    });
    stream += 'ET';

    var objects = [];
    function obj(body) {
      objects.push(body);
      return objects.length;
    }
    var iFont1 = obj('<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>');
    var iFont2 = obj('<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>');
    var iContent = obj(
      '<< /Length ' + stream.length + ' >>\nstream\n' + stream + '\nendstream'
    );
    var iPage = obj(
      '<< /Type /Page /Parent 0 0 R /MediaBox [0 0 ' +
        pageW.toFixed(2) +
        ' ' +
        pageH.toFixed(2) +
        '] /Contents ' +
        iContent +
        ' 0 R /Resources << /Font << /F1 ' +
        iFont1 +
        ' 0 R /F2 ' +
        iFont2 +
        ' 0 R >> >> >>'
    );
    var iPages = obj('<< /Type /Pages /Kids [' + iPage + ' 0 R] /Count 1 >>');
    var iCatalog = obj('<< /Type /Catalog /Pages ' + iPages + ' 0 R >>');
    /* Fix page parent ref */
    objects[iPage - 1] = objects[iPage - 1].replace(
      '/Parent 0 0 R',
      '/Parent ' + iPages + ' 0 R'
    );

    var pdf = '%PDF-1.4\n';
    var xref = [];
    objects.forEach(function (body, i) {
      xref.push(pdf.length);
      pdf += i + 1 + ' 0 obj\n' + body + '\nendobj\n';
    });
    var xrefStart = pdf.length;
    pdf += 'xref\n0 ' + (objects.length + 1) + '\n';
    pdf += '0000000000 65535 f \n';
    xref.forEach(function (off) {
      pdf += String(off).padStart(10, '0') + ' 00000 n \n';
    });
    pdf +=
      'trailer\n<< /Size ' +
      (objects.length + 1) +
      ' /Root ' +
      iCatalog +
      ' 0 R >>\nstartxref\n' +
      xrefStart +
      '\n%%EOF';

    var bin = new Uint8Array(pdf.length);
    for (var i = 0; i < pdf.length; i++) bin[i] = pdf.charCodeAt(i) & 0xff;
    var blob = new Blob([bin], { type: 'application/pdf' });
    var url = URL.createObjectURL(blob);
    var safeOrder = orderNo.replace(/[^\w.\-]+/g, '_');
    var name =
      filename ||
      'KOT-' + safeOrder + '-' + Date.now() + '.pdf';
    var a = document.createElement('a');
    a.href = url;
    a.download = name;
    a.rel = 'noopener';
    document.body.appendChild(a);
    a.click();
    setTimeout(function () {
      try {
        document.body.removeChild(a);
      } catch (e) {}
      try {
        URL.revokeObjectURL(url);
      } catch (e2) {}
    }, 1500);


    return { ok: true, filename: name, bytes: bin.length };
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
    formatCustomerBillText: formatCustomerBillText,
    formatCustomerBillEscPos: formatCustomerBillEscPos,
    downloadKotTicketPdf: downloadKotTicketPdf,
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
