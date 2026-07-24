/**
 * POS Invoice Ledger — filters, sort, view modal, delete.
 */
(function (global) {
  'use strict';

  function $(sel, root) {
    return (root || document).querySelector(sel);
  }

  function $all(sel, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(sel));
  }

  function formatMoney(n) {
    if (typeof global.formatInr === 'function') {
      return global.formatInr(n, 2);
    }
    var v = Number(n);
    if (isNaN(v)) v = 0;
    return '₹' + v.toFixed(2);
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
      el.textContent = formatMoney(el.getAttribute('data-amount'));
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
          av = String(av).toLowerCase();
          bv = String(bv).toLowerCase();
          if (av < bv) return dir === 'asc' ? -1 : 1;
          if (av > bv) return dir === 'asc' ? 1 : -1;
          return 0;
        });
        rows.forEach(function (row) {
          tbody.appendChild(row);
        });
      });
    });
  }

  function bindOrderTypeFilter(page) {
    var form = $('#pos-il-filter-form', page);
    var hidden = $('#pos-il-order-type', page);
    var list = $('#pos-il-order-type-list', page);
    var valueEl = $('#pos-il-order-type-value', page);
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
      emptyLabel: 'Date',
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

  function closeViewModal() {
    var modal = document.getElementById('pos-il-view-modal');
    if (modal) modal.hidden = true;
  }

  function openViewModal(invoiceId) {
    var modal = document.getElementById('pos-il-view-modal');
    var body = document.getElementById('pos-il-view-body');
    var title = document.getElementById('pos-il-view-title');
    if (!modal || !body) return;
    modal.hidden = false;
    body.innerHTML = '<p class="pos-il-modal-loading">Loading…</p>';
    if (title) title.textContent = 'Invoice';

    fetch('/point-of-sale/api/invoices/' + encodeURIComponent(invoiceId), {
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
        if (title) title.textContent = inv.order_no || 'Invoice';
        var lines = inv.lines || [];
        var linesHtml = lines
          .map(function (line) {
            var name = line.name || '—';
            if (line.variant) name += ' · ' + line.variant;
            return (
              '<tr>' +
              '<td>' +
              name +
              '</td>' +
              '<td class="is-num">' +
              formatMoney(line.rate) +
              '</td>' +
              '<td class="is-num">' +
              line.qty +
              '</td>' +
              '<td class="is-num">' +
              formatMoney(line.line_total) +
              '</td>' +
              '</tr>'
            );
          })
          .join('');
        body.innerHTML =
          '<div class="pos-il-detail-meta">' +
          '<div><div class="pos-il-detail-label">Customer</div><div class="pos-il-detail-value">' +
          (inv.customer_name || '—') +
          '</div></div>' +
          '<div><div class="pos-il-detail-label">Mobile</div><div class="pos-il-detail-value">' +
          (inv.customer_mobile || '—') +
          '</div></div>' +
          '<div><div class="pos-il-detail-label">Order type</div><div class="pos-il-detail-value">' +
          (inv.order_type_label || inv.order_type || '—') +
          '</div></div>' +
          '<div><div class="pos-il-detail-label">Table</div><div class="pos-il-detail-value">' +
          (inv.table_label || inv.table || '—') +
          '</div></div>' +
          '<div><div class="pos-il-detail-label">Date</div><div class="pos-il-detail-value">' +
          (inv.order_date || '—') +
          '</div></div>' +
          '<div><div class="pos-il-detail-label">Saved</div><div class="pos-il-detail-value">' +
          (inv.saved_at || '—') +
          '</div></div>' +
          '</div>' +
          '<table class="pos-il-detail-lines"><thead><tr><th>Item</th><th class="is-num">Rate</th><th class="is-num">Qty</th><th class="is-num">Amount</th></tr></thead><tbody>' +
          (linesHtml || '<tr><td colspan="4">No line items</td></tr>') +
          '</tbody></table>' +
          '<div class="pos-il-detail-totals">' +
          '<div class="pos-il-detail-totals-row"><span>Subtotal</span><span>' +
          formatMoney(inv.subtotal) +
          '</span></div>' +
          '<div class="pos-il-detail-totals-row"><span>Discount</span><span>' +
          formatMoney(inv.discount) +
          '</span></div>' +
          '<div class="pos-il-detail-totals-row"><span>GST</span><span>' +
          formatMoney(inv.gst) +
          '</span></div>' +
          '<div class="pos-il-detail-totals-row"><span>Service</span><span>' +
          formatMoney(inv.service) +
          '</span></div>' +
          '<div class="pos-il-detail-totals-row"><span>Tip</span><span>' +
          formatMoney(inv.tip) +
          '</span></div>' +
          '<div class="pos-il-detail-totals-row is-grand"><span>Total</span><span>' +
          formatMoney(inv.grand_total) +
          '</span></div>' +
          '</div>';
      })
      .catch(function () {
        body.innerHTML = '<p class="pos-il-modal-error">Could not load invoice.</p>';
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
      var delBtn = ev.target.closest('.pos-il-delete-btn');
      if (!delBtn) return;
      var id = delBtn.getAttribute('data-invoice-id');
      var orderNo = delBtn.getAttribute('data-order-no') || id;
      if (!window.confirm('Delete invoice ' + orderNo + '?')) return;
      delBtn.disabled = true;
      fetch('/point-of-sale/api/invoices/' + encodeURIComponent(id) + '/delete', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { Accept: 'application/json' }
      })
        .then(function (res) {
          return res.json().then(function (data) {
            return { ok: res.ok, data: data || {} };
          });
        })
        .then(function (result) {
          if (!result.ok || !result.data.ok) {
            toast((result.data && result.data.error) || 'Could not delete invoice.');
            delBtn.disabled = false;
            return;
          }
          var row = page.querySelector('tr.pos-il-row[data-invoice-id="' + id + '"]');
          if (row) row.remove();
          updateVisibleCount(page);
          toast('Invoice ' + orderNo + ' deleted.');
          window.setTimeout(function () {
            window.location.reload();
          }, 400);
        })
        .catch(function () {
          toast('Could not delete invoice.');
          delBtn.disabled = false;
        });
    });

    var modal = document.getElementById('pos-il-view-modal');
    if (modal && modal.getAttribute('data-bound') !== '1') {
      modal.setAttribute('data-bound', '1');
      modal.addEventListener('click', function (ev) {
        if (ev.target.closest('[data-pos-il-close]')) closeViewModal();
      });
      document.addEventListener('keydown', function (ev) {
        if (ev.key === 'Escape' && modal && !modal.hidden) closeViewModal();
      });
    }
  }

  function initPosInvoiceLedgerPage() {
    var page = document.getElementById('pos-invoice-ledger-page');
    if (!page) return;
    formatAmounts(document);
    bindClientSearch(page);
    bindSort(page);
    bindOrderTypeFilter(page);
    bindDateRange(page);
    bindActions(page);
    if (typeof global.initEpListboxes === 'function') {
      global.initEpListboxes();
    }
    updateVisibleCount(page);
  }

  global.initPosInvoiceLedgerPage = initPosInvoiceLedgerPage;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initPosInvoiceLedgerPage);
  } else if (!global.__deSoftNavInProgress) {
    initPosInvoiceLedgerPage();
  }
})(typeof window !== 'undefined' ? window : this);
