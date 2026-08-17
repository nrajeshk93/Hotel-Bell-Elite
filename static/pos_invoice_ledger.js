/**
 * POS Invoice Ledger — filters, sort, view modal, delete.
 */
(function (global) {
  'use strict';

  function resolvePosApiBase() {
    var el = document.querySelector('[data-pos-api-base]');
    var base = (el && el.getAttribute('data-pos-api-base')) || '';
    if (!base) {
      base =
        (window.location.pathname || '').indexOf('/bar-point-of-sale') === 0
          ? '/bar-point-of-sale'
          : '/point-of-sale';
    }
    return String(base).replace(/\/$/, '') || '/point-of-sale';
  }


  function $(sel, root) {
    return (root || document).querySelector(sel);
  }

  function $all(sel, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(sel));
  }

  function formatMoney(n) {
    var v = Number(n);
    if (isNaN(v)) v = 0;
    return v.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  function toast(msg) {
    if (typeof global.showToast === 'function') {
      global.showToast(msg);
      return;
    }
    window.alert(msg);
  }

  function formatAmounts(root) {
    $all('.pl-amount[data-amount]', root).forEach(function (el) {
      if (typeof global.formatAmountNode === 'function') {
        global.formatAmountNode(el);
        return;
      }
      var isKpi =
        typeof global.isKpiAmountNode === 'function'
          ? global.isKpiAmountNode(el)
          : el.classList.contains('pl-summary-value');
      var places = isKpi ? 0 : 2;
      var v = Number(el.getAttribute('data-amount'));
      if (isNaN(v)) v = 0;
      if (typeof global.formatInr === 'function') {
        el.textContent = global.formatInr(v, places);
      } else {
        el.textContent = v.toLocaleString('en-IN', {
          minimumFractionDigits: places,
          maximumFractionDigits: places
        });
      }
    });
    if (typeof global.scheduleFitKpiValues === 'function') {
      global.scheduleFitKpiValues(root);
    }
  }

  function updateVisibleCount(page) {
    var countEl = $('#pos-il-entry-count', page);
    if (!countEl) return;
    var rows = $all('tr.pos-il-row', page);
    var visible = rows.filter(function (row) {
      return row.style.display !== 'none';
    }).length;
    countEl.textContent = visible + ' entr' + (visible === 1 ? 'y' : 'ies');
  }

  function bindClientSearch(page) {
    var input = $('#pos-il-search', page);
    if (!input || input.getAttribute('data-bound') === '1') return;
    input.setAttribute('data-bound', '1');
    var searchChip = input.closest('.pl-search-chip');
    function applySearch() {
      var q = String(input.value || '')
        .trim()
        .toLowerCase();
      if (searchChip) searchChip.classList.toggle('is-active', !!q);
      $all('tr.pos-il-row', page).forEach(function (row) {
        var hay = row.getAttribute('data-search') || '';
        row.style.display = !q || hay.indexOf(q) !== -1 ? '' : 'none';
      });
      updateVisibleCount(page);
    }
    input.addEventListener('input', applySearch);
    applySearch();
  }

  function bindSort(page) {
    var table = $('#pos-il-table', page);
    if (!table || table.getAttribute('data-sort-bound') === '1') return;
    table.setAttribute('data-sort-bound', '1');
    var tbody = table.querySelector('tbody');
    if (!tbody) return;

    $all('th.pl-sortable', table).forEach(function (th) {
      th.addEventListener('click', function () {
        var key = th.getAttribute('data-sort') || '';
        var numeric = th.getAttribute('data-sort-type') === 'number';
        var current = th.getAttribute('aria-sort');
        var dir = current === 'ascending' ? 'desc' : 'asc';
        $all('th.pl-sortable', table).forEach(function (h) {
          h.setAttribute('aria-sort', 'none');
        });
        th.setAttribute('aria-sort', dir === 'asc' ? 'ascending' : 'descending');
        var rows = $all('tr.pos-il-row', tbody);
        rows.sort(function (a, b) {
          var aCell = a.children[
            Array.prototype.indexOf.call(th.parentNode.children, th)
          ];
          var bCell = b.children[
            Array.prototype.indexOf.call(th.parentNode.children, th)
          ];
          var av = aCell ? aCell.getAttribute('data-sort-value') || aCell.textContent : '';
          var bv = bCell ? bCell.getAttribute('data-sort-value') || bCell.textContent : '';
          if (numeric) {
            av = Number(av) || 0;
            bv = Number(bv) || 0;
            return dir === 'asc' ? av - bv : bv - av;
          }
          av = String(av).trim();
          bv = String(bv).trim();
          // Numeric-aware compare so SPC/26-27/99 sorts before SPC/26-27/708.
          var cmp = av.localeCompare(bv, undefined, {
            numeric: true,
            sensitivity: 'base',
          });
          return dir === 'asc' ? cmp : -cmp;
        });
        rows.forEach(function (row) {
          tbody.appendChild(row);
        });
      });
    });
  }

  function bindListboxFilter(page, opts) {
    var form = $('#pos-il-filter-form', page);
    var hidden = $(opts.hiddenId, page);
    var list = $(opts.listId, page);
    var valueEl = $(opts.valueId, page);
    if (!form || !hidden || !list || list.getAttribute('data-bound') === '1') return;
    list.setAttribute('data-bound', '1');
    list.addEventListener('click', function (ev) {
      var btn = ev.target.closest('.se-filter-listbox-option');
      if (!btn) return;
      var val = btn.getAttribute('data-value') || 'all';
      hidden.value = val;
      if (valueEl) valueEl.textContent = btn.textContent.trim();
      $all('.se-filter-listbox-option', list).forEach(function (opt) {
        var on = opt === btn;
        opt.classList.toggle('is-selected', on);
        opt.setAttribute('aria-selected', on ? 'true' : 'false');
      });
      form.submit();
    });
  }

  function bindOrderTypeFilter(page) {
    bindListboxFilter(page, {
      hiddenId: '#pos-il-order-type',
      listId: '#pos-il-order-type-list',
      valueId: '#pos-il-order-type-value'
    });
  }

  function bindSettlementFilter(page) {
    bindListboxFilter(page, {
      hiddenId: '#pos-il-settlement',
      listId: '#pos-il-settlement-list',
      valueId: '#pos-il-settlement-value'
    });
  }

  function bindDateRange(page) {
    var form = $('#pos-il-filter-form', page);
    if (!form || !global.SalesDateRangePicker || typeof global.SalesDateRangePicker.init !== 'function') {
      return;
    }
    if (form.getAttribute('data-date-bound') === '1') return;
    form.setAttribute('data-date-bound', '1');
    var dateFrom = $('#pos-il-date-from', page);
    var dateTo = $('#pos-il-date-to', page);
    global.SalesDateRangePicker.init({
      wrapId: 'pos-il-date-range-wrap',
      triggerId: 'pos-il-date-range-trigger',
      backdropId: 'pos-il-date-range-backdrop',
      panelId: 'pos-il-date-range-panel',
      displayId: 'pos-il-date-range-display',
      formId: 'pos-il-filter-form',
      fromInputId: 'pos-il-date-from',
      toInputId: 'pos-il-date-to',
      applyId: 'pos-il-date-range-apply',
      prevId: 'pos-il-cal-prev',
      nextId: 'pos-il-cal-next',
      title0Id: 'pos-il-cal-title0',
      title1Id: 'pos-il-cal-title1',
      grid0Id: 'pos-il-cal-grid0',
      grid1Id: 'pos-il-cal-grid1',
      emptyLabel: 'Select…',
      onBeforeSubmit: function () {
        if (dateFrom && !dateFrom.value) dateFrom.removeAttribute('name');
        if (dateTo && !dateTo.value) dateTo.removeAttribute('name');
      }
    });
    var clearBtn = $('#pos-il-date-range-clear', page);
    if (clearBtn && clearBtn.getAttribute('data-pos-il-clear-bound') !== '1') {
      clearBtn.setAttribute('data-pos-il-clear-bound', '1');
      clearBtn.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        var clearUrl = form.getAttribute('data-clear-url') || form.action || '';
        if (clearUrl) window.location.href = clearUrl;
      });
    }
  }

  var GST_RATE = 0.05;
  var CGST_RATE = 0.025;
  var UGST_RATE = 0.025;
  var ORDER_TYPE_LABELS = {
    dine_in: 'Dine In',
    takeaway: 'Takeaway',
    delivery: 'Delivery'
  };

  function escapeHtml(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function formatAdjHint(type, value) {
    var n = Number(value);
    if (isNaN(n) || n <= 0) return '';
    if (type === 'inr') return '(₹' + n.toFixed(n % 1 ? 2 : 0) + ')';
    return '(' + n + '%)';
  }

  function billDateLabel(invoice) {
    var raw = String((invoice && (invoice.saved_at || invoice.created_at || invoice.order_date)) || '').trim();
    if (!raw) return new Date().toLocaleString();
    var normalized = raw.indexOf('T') >= 0 ? raw : raw.replace(' ', 'T');
    var parsed = new Date(normalized);
    if (!isNaN(parsed.getTime())) return parsed.toLocaleString();
    return raw;
  }

  /** Same customer-bill HTML used when printing from POS / Tables. */
  function buildCustomerBillHtml(invoice) {
    if (typeof global.buildPosCustomerBillHtml === 'function') {
      return global.buildPosCustomerBillHtml(invoice, {});
    }
    return buildCustomerBillHtmlLegacy(invoice);
  }

  function buildCustomerBillHtmlLegacy(invoice) {
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
    var discHint = formatAdjHint(invoice && invoice.discount_type, invoice && invoice.discount_value);
    var svcHint = formatAdjHint(invoice && invoice.service_type, invoice && invoice.service_value);
    var custRow = customerName
      ? '<div><span>Customer</span><span>' +
        escapeHtml(customerName) +
        (customerMobile ? ' · +91 ' + escapeHtml(customerMobile) : '') +
        '</span></div>'
      : '';
    var rows = lines
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
          formatMoney(rate) +
          '</td><td class="amt">' +
          formatMoney(amt) +
          '</td></tr>'
        );
      })
      .join('');

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
      escapeHtml(billDateLabel(invoice)) +
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
      formatMoney(invoice && invoice.subtotal) +
      '</span></div>' +
      (Number(invoice && invoice.discount) > 0 || Number(invoice && invoice.discount_value) > 0
        ? '<div><span>Discount' +
          (discHint ? ' ' + discHint : '') +
          '</span><span>-' +
          formatMoney(invoice && invoice.discount) +
          '</span></div>'
        : '') +
      '<div><span>CGST (' +
      CGST_RATE * 100 +
      '%)</span><span>' +
      formatMoney(Number(invoice && invoice.gst ? invoice.gst : 0) / 2) +
      '</span></div>' +
      '<div><span>UGST (' +
      UGST_RATE * 100 +
      '%)</span><span>' +
      formatMoney(Number(invoice && invoice.gst ? invoice.gst : 0) / 2) +
      '</span></div>' +
      (Number(invoice && invoice.vat) > 0
        ? '<div><span>VAT (10%)</span><span>' +
          formatMoney(invoice.vat) +
          '</span></div>'
        : '') +
      (Number(invoice && invoice.service) > 0 || Number(invoice && invoice.service_value) > 0
        ? '<div><span>Service Charge' +
          (svcHint ? ' ' + svcHint : '') +
          '</span><span>' +
          formatMoney(invoice && invoice.service) +
          '</span></div>'
        : '') +
      (Number(invoice && invoice.tip) > 0
        ? '<div><span>Tip</span><span>' + formatMoney(invoice && invoice.tip) + '</span></div>'
        : '') +
      '<div><span>Round Off</span><span>' +
      formatMoney(invoice && invoice.round_off) +
      '</span></div>' +
      '<div class="grand"><span>Total</span><span>' +
      formatMoney(invoice && invoice.grand_total) +
      '</span></div>' +
      '</div>' +
      '<div class="foot">Thank you for dining with us!</div>' +
      '</body></html>'
    );
  }

  var currentViewedInvoice = null;

  function resolveLedgerOutlet(invoice) {
    var page = document.getElementById('pos-invoice-ledger-page');
    var fromPage = page && page.getAttribute('data-pos-outlet');
    var fromInv = invoice && invoice.outlet;
    var fromPath =
      (window.location.pathname || '').indexOf('/bar-point-of-sale') === 0
        ? 'bar'
        : 'restaurant';
    return String(fromInv || fromPage || fromPath || 'restaurant')
      .trim()
      .toLowerCase();
  }

  function getViewedInvoice() {
    var modal = document.getElementById('pos-il-view-modal');
    if (modal && modal.__posIlInvoice) return modal.__posIlInvoice;
    return currentViewedInvoice;
  }

  function setViewedInvoice(invoice) {
    currentViewedInvoice = invoice || null;
    var modal = document.getElementById('pos-il-view-modal');
    if (modal) modal.__posIlInvoice = invoice || null;
  }

  function printBillViaBrowserFrame() {
    var frame = document.getElementById('pos-il-bill-frame');
    if (!frame || !frame.contentWindow) return false;
    try {
      frame.contentWindow.focus();
      frame.contentWindow.print();
      return true;
    } catch (err) {
      return false;
    }
  }

  function closeViewModal() {
    var modal = document.getElementById('pos-il-view-modal');
    var printBtn = document.getElementById('pos-il-view-print');
    if (modal) modal.hidden = true;
    if (printBtn) printBtn.hidden = true;
    setViewedInvoice(null);
  }

  function printViewedBill() {
    var invoice = getViewedInvoice();
    if (!invoice) {
      toast('Load a bill before printing.');
      return;
    }

    var html = '';
    try {
      html = buildCustomerBillHtml(invoice);
    } catch (err) {
      toast('Could not build the bill for printing.');
      return;
    }

    var outlet = resolveLedgerOutlet(invoice);
    var prefs = global.hbePosPrinterPrefs;
    var canAgent =
      prefs &&
      typeof prefs.printInvoiceHtml === 'function' &&
      global.HotelPrintAgent &&
      typeof global.HotelPrintAgent.print === 'function';

    if (!canAgent) {
      if (printBillViaBrowserFrame()) {
        toast('Print Agent unavailable — opened browser print.');
        return;
      }
      toast(
        'Hotel Print Agent is required for bill printing. Install and open it on this PC.'
      );
      return;
    }

    var jobId =
      'ledger-' +
      String(invoice.id || invoice.order_no || Date.now()) +
      '-' +
      Date.now();

    var printPromise = Promise.resolve();
    if (typeof global.HotelPrintAgent.ensurePaired === 'function') {
      printPromise = global.HotelPrintAgent.ensurePaired(true).catch(function () {
        return null;
      });
    }

    printPromise
      .then(function () {
        return prefs.printInvoiceHtml(html, {
          outlet: outlet,
          jobId: jobId,
          invoice: invoice,
          allowBrowserFallback: false
        });
      })
      .then(function (result) {
        if (result && result.via === 'agent') {
          toast('Sent to printer.');
          return;
        }
        var errMsg =
          (result && result.error && result.error.message) ||
          'Bill print failed. Open Hotel Print Agent and map the Invoice printer.';
        if (printBillViaBrowserFrame()) {
          toast(errMsg + ' Opened browser print as fallback.');
          return;
        }
        toast(errMsg);
      })
      .catch(function (err) {
        var msg =
          (err && err.message) ||
          'Bill print failed. Check Hotel Print Agent.';
        if (printBillViaBrowserFrame()) {
          toast(msg + ' Opened browser print as fallback.');
          return;
        }
        toast(msg);
      });
  }

  function openViewModal(invoiceId) {
    var modal = document.getElementById('pos-il-view-modal');
    var body = document.getElementById('pos-il-view-body');
    var title = document.getElementById('pos-il-view-title');
    var printBtn = document.getElementById('pos-il-view-print');
    if (!modal || !body) return;
    modal.hidden = false;
    if (printBtn) printBtn.hidden = true;
    setViewedInvoice(null);
    body.innerHTML = '<p class="pos-il-modal-loading">Loading…</p>';
    if (title) title.textContent = 'Customer Bill';

    fetch(resolvePosApiBase() + '/api/invoices/' + encodeURIComponent(invoiceId), {
      credentials: 'same-origin',
      headers: { Accept: 'application/json' }
    })
      .then(function (res) {
        return res.json().then(function (data) {
          return { ok: res.ok, data: data || {} };
        });
      })
      .then(function (result) {
        if (!result.ok || !result.data.ok || !result.data.invoice) {
          body.innerHTML =
            '<p class="pos-il-modal-error">' +
            ((result.data && result.data.error) || 'Could not load invoice.') +
            '</p>';
          return;
        }
        var inv = result.data.invoice;
        setViewedInvoice(inv);
        if (title) title.textContent = inv.order_no || 'Customer Bill';
        body.innerHTML =
          '<iframe class="pos-il-bill-frame" id="pos-il-bill-frame" title="Customer bill"></iframe>';
        var frame = document.getElementById('pos-il-bill-frame');
        var idoc =
          frame &&
          (frame.contentDocument ||
            (frame.contentWindow && frame.contentWindow.document));
        if (!idoc) {
          body.innerHTML = '<p class="pos-il-modal-error">Could not open bill view.</p>';
          return;
        }
        idoc.open();
        idoc.write(buildCustomerBillHtml(inv));
        idoc.close();
        if (printBtn) printBtn.hidden = false;
      })
      .catch(function () {
        body.innerHTML = '<p class="pos-il-modal-error">Could not load invoice.</p>';
      });
  }

  function openSettleFromUnsettledRow(row) {
    if (!row) return;
    var invoiceId = row.getAttribute('data-invoice-id');
    if (!invoiceId) return;
    if (typeof global.bindPosSettleModal === 'function') {
      global.bindPosSettleModal();
    }
    if (typeof global.openPosSettleModal !== 'function') {
      toast('Settle dialog is not available.');
      return;
    }
    global.openPosSettleModal({
      invoiceId: invoiceId,
      orderNo: row.getAttribute('data-order-no') || '—',
      tableLabel: row.getAttribute('data-table') || '',
      grandTotal: row.getAttribute('data-grand-total'),
      apiBase: resolvePosApiBase(),
      onSettled: function (_settledInvoice, meta) {
        var table = (meta && meta.tableLabel) || row.getAttribute('data-table') || '';
        toast(
          table
            ? 'Bill settled. ' + table + ' is now available.'
            : 'Bill settled successfully.'
        );
        window.setTimeout(function () {
          window.location.reload();
        }, 400);
      }
    });
  }

  function bindActions(page) {
    if (page.getAttribute('data-actions-bound') === '1') return;
    page.setAttribute('data-actions-bound', '1');

    page.addEventListener('click', function (ev) {
      var viewBtn = ev.target.closest('.pos-il-view-btn');
      if (viewBtn) {
        openViewModal(viewBtn.getAttribute('data-invoice-id'));
        return;
      }
      var voidBtn = ev.target.closest('.pos-il-delete-btn, .pos-il-cancel-btn');
      if (voidBtn) {
        ev.preventDefault();
        ev.stopPropagation();
        if (voidBtn.disabled) return;
        openVoidInvoiceModal(voidBtn);
        return;
      }

      var unsettledRow = ev.target.closest('tr.pos-il-row.is-unsettled');
      if (unsettledRow && page.contains(unsettledRow) && !ev.target.closest('.pl-col-actions')) {
        ev.preventDefault();
        openSettleFromUnsettledRow(unsettledRow);
      }
    });

    page.addEventListener('keydown', function (ev) {
      if (ev.key !== 'Enter' && ev.key !== ' ') return;
      var row = ev.target.closest('tr.pos-il-row.is-unsettled');
      if (!row || row !== ev.target) return;
      ev.preventDefault();
      openSettleFromUnsettledRow(row);
    });

    var modal = document.getElementById('pos-il-view-modal');
    if (modal && modal.getAttribute('data-bound') !== '1') {
      modal.setAttribute('data-bound', '1');
      modal.addEventListener('click', function (ev) {
        if (ev.target.closest('#pos-il-view-print')) {
          ev.preventDefault();
          printViewedBill();
          return;
        }
        if (ev.target.closest('[data-pos-il-close]')) closeViewModal();
      });
      document.addEventListener('keydown', function (ev) {
        if (ev.key === 'Escape' && modal && !modal.hidden) closeViewModal();
      });
    }
    var printBtn = document.getElementById('pos-il-view-print');
    if (printBtn && printBtn.getAttribute('data-bound') !== '1') {
      printBtn.setAttribute('data-bound', '1');
      printBtn.addEventListener('click', function (ev) {
        ev.preventDefault();
        ev.stopPropagation();
        printViewedBill();
      });
    }

    bindVoidInvoiceModal();
  }

  var pendingVoidInvoice = null;

  function voidInvoiceModalEl() {
    return document.getElementById('pos-il-void-modal');
  }

  function closeVoidInvoiceModal() {
    var modal = voidInvoiceModalEl();
    if (!modal) return;
    modal.hidden = true;
    modal.setAttribute('hidden', '');
    pendingVoidInvoice = null;
    var reason = document.getElementById('pos-il-void-reason');
    var err = document.getElementById('pos-il-void-error');
    var confirmBtn = document.getElementById('pos-il-void-confirm');
    if (reason) reason.value = '';
    if (err) {
      err.hidden = true;
      err.textContent = '';
    }
    if (confirmBtn) confirmBtn.disabled = false;
  }

  function openVoidInvoiceModal(btn) {
    if (!btn) return;
    var invoiceId = btn.getAttribute('data-invoice-id');
    if (!invoiceId) return;
    var mode = btn.getAttribute('data-void-mode') || 'cancel';
    var orderNo = btn.getAttribute('data-order-no') || 'this invoice';
    pendingVoidInvoice = {
      id: String(invoiceId),
      orderNo: orderNo,
      mode: mode,
      btn: btn
    };
    var modal = voidInvoiceModalEl();
    var title = document.getElementById('pos-il-void-title');
    var lead = document.getElementById('pos-il-void-lead');
    var reasonLabel = document.getElementById('pos-il-void-reason-label');
    var reason = document.getElementById('pos-il-void-reason');
    var err = document.getElementById('pos-il-void-error');
    var confirmLabel = document.getElementById('pos-il-void-confirm-label');
    var isDelete = mode === 'delete';
    if (title) title.textContent = isDelete ? 'Delete Draft' : 'Cancel Invoice';
    if (lead) {
      lead.textContent = isDelete
        ? 'Delete draft ' + orderNo + '? Enter a reason. This cannot be undone.'
        : 'Cancel ' + orderNo + '? Enter a reason. This cannot be undone.';
    }
    if (reasonLabel) {
      reasonLabel.textContent = isDelete
        ? 'Reason for deletion'
        : 'Reason for cancellation';
    }
    if (reason) {
      reason.value = '';
      reason.placeholder = isDelete
        ? 'Why is this draft being deleted?'
        : 'Why is this invoice being cancelled?';
    }
    if (confirmLabel) {
      confirmLabel.textContent = isDelete ? 'Delete Draft' : 'Cancel Invoice';
    }
    if (err) {
      err.hidden = true;
      err.textContent = '';
    }
    if (modal) {
      modal.hidden = false;
      modal.removeAttribute('hidden');
    }
    window.setTimeout(function () {
      if (reason) reason.focus();
    }, 30);
  }

  function submitVoidInvoiceModal() {
    if (!pendingVoidInvoice || !pendingVoidInvoice.id) return;
    var reasonEl = document.getElementById('pos-il-void-reason');
    var err = document.getElementById('pos-il-void-error');
    var confirmBtn = document.getElementById('pos-il-void-confirm');
    var reason = reasonEl ? String(reasonEl.value || '').trim() : '';
    if (!reason) {
      if (err) {
        err.hidden = false;
        err.textContent =
          pendingVoidInvoice.mode === 'delete'
            ? 'Enter a reason for deletion.'
            : 'Enter a reason for cancellation.';
      }
      if (reasonEl) reasonEl.focus();
      return;
    }
    var invoiceId = pendingVoidInvoice.id;
    var orderNo = pendingVoidInvoice.orderNo;
    var mode = pendingVoidInvoice.mode;
    var btn = pendingVoidInvoice.btn;
    var page = document.getElementById('pos-invoice-ledger-page');
    if (confirmBtn) confirmBtn.disabled = true;
    if (btn) btn.disabled = true;
    fetch(
      resolvePosApiBase() +
        '/api/invoices/' +
        encodeURIComponent(invoiceId) +
        '/delete',
      {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          Accept: 'application/json',
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ reason: reason })
      }
    )
      .then(function (res) {
        return res
          .json()
          .catch(function () {
            return {};
          })
          .then(function (data) {
            return { ok: res.ok, data: data || {} };
          });
      })
      .then(function (result) {
        if (!result.ok || !result.data.ok) {
          var msg =
            (result.data && result.data.error) ||
            (mode === 'delete'
              ? 'Could not delete invoice.'
              : 'Could not cancel invoice.');
          if (err) {
            err.hidden = false;
            err.textContent = msg;
          } else {
            toast(msg);
          }
          return;
        }
        closeVoidInvoiceModal();
        var resultMode = result.data.mode || mode;
        toast(
          resultMode === 'deleted'
            ? 'Invoice ' + orderNo + ' deleted.'
            : 'Invoice ' + orderNo + ' cancelled.'
        );
        if (page) {
          var row = page.querySelector(
            'tr.pos-il-row[data-invoice-id="' + invoiceId + '"]'
          );
          if (row && resultMode === 'deleted') {
            row.remove();
            updateVisibleCount(page);
          }
        }
        window.setTimeout(function () {
          window.location.reload();
        }, 400);
      })
      .catch(function () {
        var msg =
          mode === 'delete'
            ? 'Could not delete invoice. Check your connection.'
            : 'Could not cancel invoice. Check your connection.';
        if (err) {
          err.hidden = false;
          err.textContent = msg;
        } else {
          toast(msg);
        }
      })
      .then(function () {
        if (confirmBtn) confirmBtn.disabled = false;
        if (btn) btn.disabled = false;
      });
  }

  function bindVoidInvoiceModal() {
    var modal = voidInvoiceModalEl();
    if (!modal || modal.getAttribute('data-bound') === '1') return;
    modal.setAttribute('data-bound', '1');
    modal.addEventListener('click', function (event) {
      if (event.target.closest('[data-pos-il-void-close]')) {
        event.preventDefault();
        closeVoidInvoiceModal();
        return;
      }
      if (event.target.closest('#pos-il-void-confirm')) {
        event.preventDefault();
        submitVoidInvoiceModal();
      }
    });
    var reason = document.getElementById('pos-il-void-reason');
    if (reason) {
      reason.addEventListener('keydown', function (event) {
        if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
          event.preventDefault();
          submitVoidInvoiceModal();
        }
      });
    }
    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape' && modal && !modal.hidden) {
        closeVoidInvoiceModal();
      }
    });
  }

  function initPosInvoiceLedgerPage() {
    var page = document.getElementById('pos-invoice-ledger-page');
    if (!page) return;
    formatAmounts(document);
    bindClientSearch(page);
    bindSort(page);
    bindOrderTypeFilter(page);
    bindSettlementFilter(page);
    bindDateRange(page);
    bindActions(page);
    if (typeof global.bindPosSettleModal === 'function') {
      global.bindPosSettleModal();
    }
    if (typeof global.initEpListboxes === 'function') {
      global.initEpListboxes();
    }
    updateVisibleCount(page);
  }

  global.initPosInvoiceLedgerPage = initPosInvoiceLedgerPage;
  global.__posIlPrintViewedBill = printViewedBill;

  /* Soft-nav safe: one document listener always calls the latest print handler. */
  if (!global.__posIlPrintDelegated) {
    global.__posIlPrintDelegated = true;
    document.addEventListener(
      'click',
      function (ev) {
        var btn = ev.target && ev.target.closest
          ? ev.target.closest('#pos-il-view-print')
          : null;
        if (!btn) return;
        ev.preventDefault();
        if (typeof global.__posIlPrintViewedBill === 'function') {
          global.__posIlPrintViewedBill();
        }
      },
      true
    );
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initPosInvoiceLedgerPage);
  } else if (!global.__deSoftNavInProgress) {
    initPosInvoiceLedgerPage();
  }
})(typeof window !== 'undefined' ? window : this);
