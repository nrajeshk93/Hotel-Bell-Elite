/**
 * Shared POS customer bill HTML — thermal Spice-style receipt for Restaurant + Bar.
 */
(function (global) {
  'use strict';

  var DEFAULT_RECEIPT_CONFIG = {
    business_name: 'SPICE MULTICUISINE',
    address: 'Gurudwara Lane, Aberdeen bazar, Sri Vijaya Puram, Andaman & Nicobar 744101',
    gst: '35AAANFH8592H1ZS',
    logo_url: '/static/pos/spice-receipt-logo.jpg',
    user_label: 'RESTAURANT'
  };

  var BAR_RECEIPT_CONFIG = {
    business_name: 'IRISH BARREL HOUSE BAR',
    address: 'Gurudwara Lane, Aberdeen bazar, Sri Vijaya Puram, Andaman & Nicobar 744101',
    gst: '35AAANFH8592H1ZS',
    logo_url: '/static/pos/irish-barrel-house-logo.png',
    user_label: 'BAR'
  };

  var ORDER_TYPE_LABELS = {
    dine_in: 'Dine In',
    takeaway: 'Takeaway',
    delivery: 'Delivery'
  };

  var CGST_RATE = 0.025;
  var UGST_RATE = 0.025;
  var VAT_RATE = 0.1;

  function getPosReceiptConfig(outlet) {
    var key = String(outlet || '').trim().toLowerCase();
    var fallback = key === 'bar' ? BAR_RECEIPT_CONFIG : DEFAULT_RECEIPT_CONFIG;
    if (typeof document === 'undefined') return fallback;
    var el = document.getElementById('pos-receipt-config-data');
    if (!el) return fallback;
    try {
      var parsed = JSON.parse(el.textContent || '{}');
      if (parsed && typeof parsed === 'object') {
        return {
          business_name: parsed.business_name || fallback.business_name,
          address: parsed.address || fallback.address,
          gst: parsed.gst || fallback.gst,
          logo_url: parsed.logo_url || fallback.logo_url,
          user_label: parsed.user_label || fallback.user_label
        };
      }
    } catch (e) {}
    return fallback;
  }

  function escapeHtml(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function formatThermalAmount(n) {
    var v = Math.round((Number(n) || 0) * 100) / 100;
    return v.toFixed(2);
  }

  function formatLegacyMoney(n) {
    var v = Math.round((Number(n) || 0) * 100) / 100;
    return '₹' + v.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  function formatAdjHint(type, value) {
    var n = Number(value);
    if (isNaN(n) || n <= 0) return '';
    if (type === 'inr') return '(₹' + n.toFixed(n % 1 ? 2 : 0) + ')';
    return '(' + n + '%)';
  }

  function formatLegacyDate(d) {
    var months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    return d.getDate() + ' ' + months[d.getMonth()] + ' ' + d.getFullYear();
  }

  function formatLegacyTime(d) {
    var h = d.getHours();
    var m = d.getMinutes();
    var ap = h >= 12 ? 'PM' : 'AM';
    var h12 = h % 12 || 12;
    return h12 + ':' + (m < 10 ? '0' : '') + m + ' ' + ap;
  }

  function formatSpiceDate(d) {
    var months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    var day = d.getDate();
    var mon = months[d.getMonth()];
    var year = d.getFullYear();
    var h = d.getHours();
    var m = d.getMinutes();
    var ap = h >= 12 ? 'PM' : 'AM';
    var h12 = h % 12 || 12;
    return day + '-' + mon + '-' + year + ' ' + h12 + ':' + (m < 10 ? '0' : '') + m + ' ' + ap;
  }

  function resolveBillDate(invoice, opts) {
    if (opts && opts.now instanceof Date && !isNaN(opts.now.getTime())) return opts.now;
    var raw = String(
      (invoice && (invoice.saved_at || invoice.created_at || invoice.order_date)) || ''
    ).trim();
    if (!raw) return new Date();
    var normalized = raw.indexOf('T') >= 0 ? raw : raw.replace(' ', 'T');
    var parsed = new Date(normalized);
    return !isNaN(parsed.getTime()) ? parsed : new Date();
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
      total: Number(
        invoice && invoice.grand_total != null
          ? invoice.grand_total
          : invoice && invoice.total != null
            ? invoice.total
            : 0
      )
    };
  }

  function buildItemRows(lines, amountFormatter) {
    // Category/variant (e.g. MAIN COURSE) is for staff on screen only — not on printed bills.
    return (lines || [])
      .map(function (line) {
        var qty = Number(line.qty) || 0;
        var rate = Number(line.rate) || 0;
        var amt = line.line_total != null ? Number(line.line_total) : rate * qty;
        return (
          '<tr><td class="name">' +
          escapeHtml(line.name) +
          '</td><td class="qty">' +
          qty +
          '</td><td class="rate">' +
          amountFormatter(rate) +
          '</td><td class="amt">' +
          amountFormatter(amt) +
          '</td></tr>'
        );
      })
      .join('');
  }

  function buildLegacyCustomerBillHtml(invoice, opts) {
    opts = opts || {};
    var now = resolveBillDate(invoice, opts);
    var orderNo = (invoice && invoice.order_no) || '—';
    var table = (invoice && (invoice.table_label || invoice.table)) || '—';
    var orderTypeValue = (invoice && invoice.order_type) || 'dine_in';
    var orderType =
      (invoice && invoice.order_type_label) ||
      ORDER_TYPE_LABELS[orderTypeValue] ||
      orderTypeValue;
    var customerName = (invoice && invoice.customer_name) || '';
    var customerMobile = (invoice && invoice.customer_mobile) || '';
    var lines = invoice && Array.isArray(invoice.lines) ? invoice.lines : [];
    var totals = normalizeTotals(invoice);
    var rows = buildItemRows(lines, formatLegacyMoney);
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
      escapeHtml(formatLegacyDate(now) + ' ' + formatLegacyTime(now)) +
      '</span></div>' +
      custRow +
      '</div>' +
      '<table class="items"><thead><tr><th>Item</th><th class="qty">Qty</th><th class="rate">Rate</th><th class="amt">Amt</th></tr></thead>' +
      '<tbody>' +
      (rows || '<tr><td colspan="4" style="text-align:center;color:#555">No items</td></tr>') +
      '</tbody></table>' +
      '<div class="totals">' +
      '<div><span>Subtotal</span><span>' +
      formatLegacyMoney(totals.subtotal) +
      '</span></div>' +
      (Number(totals.discount) > 0 || Number(totals.discountValue) > 0
        ? '<div><span>Discount' +
          (discHint ? ' ' + discHint : '') +
          '</span><span>-' +
          formatLegacyMoney(totals.discount) +
          '</span></div>'
        : '') +
      '<div><span>CGST (' +
      CGST_RATE * 100 +
      '%)</span><span>' +
      formatLegacyMoney(totals.cgst) +
      '</span></div>' +
      '<div><span>UGST (' +
      UGST_RATE * 100 +
      '%)</span><span>' +
      formatLegacyMoney(totals.ugst) +
      '</span></div>' +
      (Number(totals.vat) > 0
        ? '<div><span>VAT (' +
          VAT_RATE * 100 +
          '%)</span><span>' +
          formatLegacyMoney(totals.vat) +
          '</span></div>'
        : '') +
      (Number(totals.service) > 0 || Number(totals.serviceValue) > 0
        ? '<div><span>Service Charge' +
          (svcHint ? ' ' + svcHint : '') +
          '</span><span>' +
          formatLegacyMoney(totals.service) +
          '</span></div>'
        : '') +
      (Number(totals.tip) > 0
        ? '<div><span>Tip</span><span>' + formatLegacyMoney(totals.tip) + '</span></div>'
        : '') +
      '<div><span>Round Off</span><span>' +
      formatLegacyMoney(totals.roundOff) +
      '</span></div>' +
      '<div class="grand"><span>Total</span><span>' +
      formatLegacyMoney(totals.total) +
      '</span></div>' +
      '</div>' +
      '<div class="foot">Thank you for dining with us!</div>' +
      '</body></html>'
    );
  }

  function buildReceiptsSection(invoice, totals) {
    var payments = invoice && Array.isArray(invoice.payments) ? invoice.payments : [];
    if (!payments.length) return '';
    var rows = payments
      .map(function (pay) {
        var label =
          pay.payment_method_label ||
          String(pay.payment_method || 'Cash')
            .replace(/_/g, ' ')
            .replace(/\b\w/g, function (c) {
              return c.toUpperCase();
            });
        return (
          '<tr><td class="pay-mode">' +
          escapeHtml(label) +
          '</td><td class="pay-amt">' +
          formatThermalAmount(pay.amount) +
          '</td></tr>'
        );
      })
      .join('');
    return (
      '<div class="receipts">' +
      '<div class="section-title">RECEIPTS</div>' +
      '<table class="receipts-table"><thead><tr><th>PAY MODE</th><th class="pay-amt">AMOUNT</th></tr></thead>' +
      '<tbody>' +
      rows +
      '</tbody></table>' +
      '<div class="receipts-total">' +
      formatThermalAmount(totals.total) +
      '</div></div>'
    );
  }

  function buildSpiceCustomerBillHtml(invoice, opts) {
    opts = opts || {};
    var cfg = getPosReceiptConfig(resolveOutlet(invoice, opts));
    var now = resolveBillDate(invoice, opts);
    var orderNo = (invoice && invoice.order_no) || '—';
    var table = (invoice && (invoice.table_label || invoice.table)) || '—';
    var lines = invoice && Array.isArray(invoice.lines) ? invoice.lines : [];
    var totals = normalizeTotals(invoice);
    var rows = buildItemRows(lines, formatThermalAmount);
    var logoUrl = escapeHtml(cfg.logo_url || DEFAULT_RECEIPT_CONFIG.logo_url);

    return (
      '<!DOCTYPE html><html><head><meta charset="utf-8"><title>Bill ' +
      escapeHtml(orderNo) +
      '</title><style>' +
      'body{font-family:"Courier New",monospace;padding:12px 10px;color:#111;width:340px;margin:0 auto;font-size:12px;line-height:1.35}' +
      '.logo{display:block;margin:0 auto 8px;max-width:260px;height:auto}' +
      '.brand{font-size:14px;font-weight:700;text-align:center;letter-spacing:.06em;margin:0 0 4px}' +
      '.addr,.gst-no{font-size:11px;text-align:center;margin:0 0 3px}' +
      '.rule{border:0;border-top:1px dashed #333;margin:8px 0}' +
      '.meta{font-size:12px;margin:0 0 8px}' +
      '.meta div{display:flex;justify-content:space-between;margin:2px 0;gap:8px}' +
      'table.items{width:100%;border-collapse:collapse;font-size:11px;margin:0 0 8px}' +
      'table.items th{text-align:left;font-size:10px;font-weight:700;padding:3px 0;border-bottom:1px solid #333;text-transform:uppercase}' +
      'table.items td{padding:3px 0;border-bottom:1px dashed #ddd;vertical-align:top}' +
      'table.items td.qty,table.items th.qty{width:28px;text-align:center}' +
      'table.items td.rate,table.items th.rate{width:56px;text-align:right}' +
      'table.items td.amt,table.items th.amt{width:64px;text-align:right}' +
      '.variant{font-size:10px;color:#555}' +
      '.totals{font-size:12px;margin:0 0 8px}' +
      '.totals div{display:flex;justify-content:space-between;margin:2px 0}' +
      '.totals .grand{font-size:14px;font-weight:700;border-top:1px solid #333;margin-top:4px;padding-top:4px}' +
      '.section-title{text-align:center;font-weight:700;font-size:12px;margin:8px 0 4px;letter-spacing:.04em}' +
      '.receipts{margin-top:4px}' +
      'table.receipts-table{width:100%;border-collapse:collapse;font-size:12px}' +
      'table.receipts-table th{font-size:10px;font-weight:700;text-align:left;padding:2px 0;border-bottom:1px solid #333;text-transform:uppercase}' +
      'table.receipts-table td{padding:3px 0;border-bottom:1px dashed #ddd}' +
      'table.receipts-table .pay-amt,table.receipts-table th.pay-amt{text-align:right;width:80px}' +
      '.receipts-total{text-align:right;font-weight:700;margin-top:4px;font-size:13px}' +
      '.user{margin-top:10px;font-size:11px}' +
      '@media print{body{width:auto;margin:0;padding:8px 6px}}' +
      '</style></head><body>' +
      '<img class="logo" src="' +
      logoUrl +
      '" alt="' +
      escapeHtml(cfg.business_name) +
      '">' +
      '<div class="brand">' +
      escapeHtml(cfg.business_name) +
      '</div>' +
      '<div class="addr">' +
      escapeHtml(cfg.address) +
      '</div>' +
      '<div class="gst-no">GST ' +
      escapeHtml(cfg.gst) +
      '</div>' +
      '<hr class="rule">' +
      '<div class="meta">' +
      '<div><span>Invoice</span><span>' +
      escapeHtml(orderNo) +
      '</span></div>' +
      '<div><span>Date</span><span>' +
      escapeHtml(formatSpiceDate(now)) +
      '</span></div>' +
      '<div><span>Table</span><span>' +
      escapeHtml(table) +
      '</span></div>' +
      '</div>' +
      '<hr class="rule">' +
      '<table class="items"><thead><tr><th>Items</th><th class="qty">Qty</th><th class="rate">Rate</th><th class="amt">Amount</th></tr></thead>' +
      '<tbody>' +
      (rows || '<tr><td colspan="4" style="text-align:center;color:#555">No items</td></tr>') +
      '</tbody></table>' +
      '<hr class="rule">' +
      '<div class="totals">' +
      '<div><span>Sub-Total</span><span>' +
      formatThermalAmount(totals.subtotal) +
      '</span></div>' +
      (Number(totals.discount) > 0 || Number(totals.discountValue) > 0
        ? '<div><span>Discount</span><span>-' +
          formatThermalAmount(totals.discount) +
          '</span></div>'
        : '') +
      '<div><span>CGST @ ' +
      CGST_RATE * 100 +
      '%</span><span>' +
      formatThermalAmount(totals.cgst) +
      '</span></div>' +
      '<div><span>UGST @ ' +
      UGST_RATE * 100 +
      '%</span><span>' +
      formatThermalAmount(totals.ugst) +
      '</span></div>' +
      (Number(totals.vat) > 0
        ? '<div><span>VAT @ ' +
          VAT_RATE * 100 +
          '%</span><span>' +
          formatThermalAmount(totals.vat) +
          '</span></div>'
        : '') +
      (Number(totals.service) > 0 || Number(totals.serviceValue) > 0
        ? '<div><span>Service Charge</span><span>' +
          formatThermalAmount(totals.service) +
          '</span></div>'
        : '') +
      (Number(totals.tip) > 0
        ? '<div><span>Tip</span><span>' + formatThermalAmount(totals.tip) + '</span></div>'
        : '') +
      '<div><span>Round-Off</span><span>' +
      formatThermalAmount(totals.roundOff) +
      '</span></div>' +
      '<div class="grand"><span>Total</span><span>' +
      formatThermalAmount(totals.total) +
      '</span></div>' +
      '</div>' +
      buildReceiptsSection(invoice, totals) +
      '<div class="user">User : ' +
      escapeHtml(cfg.user_label || 'RESTAURANT') +
      '</div>' +
      '</body></html>'
    );
  }

  function resolveOutlet(invoice, opts) {
    if (opts && opts.outlet) return String(opts.outlet).toLowerCase();
    if (invoice && invoice.outlet) return String(invoice.outlet).toLowerCase();
    return 'restaurant';
  }

  function buildPosCustomerBillHtml(invoice, opts) {
    opts = opts || {};
    // Restaurant and Bar share the same thermal layout; branding comes from receipt config.
    return buildSpiceCustomerBillHtml(invoice, opts);
  }

  global.getPosReceiptConfig = getPosReceiptConfig;
  global.buildPosCustomerBillHtml = buildPosCustomerBillHtml;
})(typeof window !== 'undefined' ? window : globalThis);
