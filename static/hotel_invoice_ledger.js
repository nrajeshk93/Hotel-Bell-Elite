/**
 * Hotel Invoice Ledger — client search, filters, View/Print via openHotelRoomInvoice.
 * Soft-nav safe: expose window.initHotelInvoiceLedgerPage.
 */
(function (global) {
  'use strict';

  function $(sel, root) {
    return (root || document).querySelector(sel);
  }

  function $all(sel, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(sel));
  }

  function toast(msg) {
    if (typeof global.showToast === 'function') {
      global.showToast(msg);
      return;
    }
    window.alert(msg);
  }

  function invoiceApiUrl(page, invoiceNumber) {
    var base =
      (page && page.getAttribute('data-invoice-api-base')) ||
      '/hotel/invoice-ledger/api/__ID__';
    var encoded = String(invoiceNumber || '')
      .split('/')
      .map(function (part) {
        return encodeURIComponent(part);
      })
      .join('/');
    return String(base).replace('__ID__', encoded);
  }

  function updateVisibleCount(page) {
    var countEl = $('#hil-entry-count', page);
    if (!countEl) return;
    var rows = $all('tr.hil-row', page);
    var visible = rows.filter(function (row) {
      return row.style.display !== 'none';
    }).length;
    countEl.textContent = visible + ' entr' + (visible === 1 ? 'y' : 'ies');
  }

  function formatAmounts(root) {
    var format =
      typeof global.formatInr === 'function'
        ? function (n) {
            return global.formatInr(n, 2);
          }
        : function (n) {
            var v = Number(n);
            if (isNaN(v)) v = 0;
            return (
              '₹' +
              v.toLocaleString('en-IN', {
                minimumFractionDigits: 2,
                maximumFractionDigits: 2
              })
            );
          };
    $all('.pl-amount[data-amount]', root).forEach(function (el) {
      el.textContent = format(el.getAttribute('data-amount'));
    });
    if (typeof global.scheduleFitKpiValues === 'function') {
      global.scheduleFitKpiValues(root);
    }
  }

  function bindSort(page) {
    var table = $('#hil-table', page);
    if (!table || table.getAttribute('data-sort-bound') === '1') return;
    table.setAttribute('data-sort-bound', '1');
    var tbody = table.tBodies[0];
    if (!tbody) return;
    var headers = $all('th.pl-sortable', table);
    var activeKey = '';
    var ascending = true;

    function cellSortValue(row, colIndex, type) {
      var cell = row.cells[colIndex];
      if (!cell) return type === 'number' ? 0 : '';
      var raw = cell.getAttribute('data-sort-value');
      if (raw == null || raw === '') raw = (cell.textContent || '').trim();
      if (type === 'number') {
        var n = Number(raw);
        return isFinite(n) ? n : 0;
      }
      return String(raw).toLowerCase();
    }

    function sortBy(th) {
      var key = th.getAttribute('data-sort') || '';
      var type = th.getAttribute('data-sort-type') || 'text';
      var colIndex = Array.prototype.indexOf.call(th.parentNode.children, th);
      if (colIndex < 0) return;

      if (activeKey === key) ascending = !ascending;
      else {
        activeKey = key;
        ascending = true;
      }

      var rows = Array.prototype.slice.call(tbody.rows);
      rows.sort(function (a, b) {
        var av = cellSortValue(a, colIndex, type);
        var bv = cellSortValue(b, colIndex, type);
        var cmp = 0;
        if (type === 'number') cmp = av - bv;
        else {
          cmp = String(av).localeCompare(String(bv), undefined, {
            numeric: true,
            sensitivity: 'base'
          });
        }
        return ascending ? cmp : -cmp;
      });
      rows.forEach(function (row) {
        tbody.appendChild(row);
      });

      headers.forEach(function (header) {
        header.classList.remove('is-sorted-asc', 'is-sorted-desc');
        header.setAttribute('aria-sort', 'none');
      });
      th.classList.add(ascending ? 'is-sorted-asc' : 'is-sorted-desc');
      th.setAttribute('aria-sort', ascending ? 'ascending' : 'descending');
    }

    headers.forEach(function (th) {
      th.addEventListener('click', function () {
        sortBy(th);
      });
      th.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          sortBy(th);
        }
      });
    });
  }

  function bindClientSearch(page) {
    var input = $('#hil-search', page);
    if (!input || input.getAttribute('data-bound') === '1') return;
    input.setAttribute('data-bound', '1');
    var searchChip = input.closest('.pl-search-chip');
    function applySearch() {
      var q = String(input.value || '')
        .trim()
        .toLowerCase();
      if (searchChip) searchChip.classList.toggle('is-active', !!q);
      $all('tr.hil-row', page).forEach(function (row) {
        var hay = row.getAttribute('data-search') || '';
        row.style.display = !q || hay.indexOf(q) !== -1 ? '' : 'none';
      });
      updateVisibleCount(page);
    }
    input.addEventListener('input', applySearch);
    applySearch();
  }

  function bindStatusFilter(page) {
    var form = $('#hil-filter-form', page);
    var list = $('#hil-status-list', page);
    if (!form || !list || list.getAttribute('data-bound') === '1') return;
    list.setAttribute('data-bound', '1');
    list.addEventListener('click', function (ev) {
      var btn = ev.target.closest('.se-filter-listbox-option');
      if (!btn) return;
      var hidden = $('#hil-status', page);
      var valueEl = $('#hil-status-value', page);
      var val = btn.getAttribute('data-value') || 'all';
      if (hidden) hidden.value = val;
      if (valueEl) {
        valueEl.textContent =
          btn.getAttribute('data-label') || btn.textContent.trim();
      }
      $all('.se-filter-listbox-option', list).forEach(function (opt) {
        var on = opt === btn;
        opt.classList.toggle('is-selected', on);
        opt.setAttribute('aria-selected', on ? 'true' : 'false');
      });
      prepareAndSubmit(form);
    });
  }

  function prepareAndSubmit(form) {
    if (!form) return;
    var dateFrom = $('#hil-date-from', form);
    var dateTo = $('#hil-date-to', form);
    if (dateFrom && !dateFrom.value) dateFrom.removeAttribute('name');
    if (dateTo && !dateTo.value) dateTo.removeAttribute('name');
    var status = $('#hil-status', form);
    if (status && (status.value === 'all' || !status.value)) {
      status.removeAttribute('name');
    }
    if (typeof global.deNavigateWithTransition === 'function') {
      var action = form.getAttribute('action') || window.location.pathname;
      var params = new URLSearchParams();
      $all('input[name]', form).forEach(function (input) {
        if (!input.name || input.disabled) return;
        if (input.type === 'hidden' || input.type === 'text' || input.type === 'search') {
          if (input.value) params.set(input.name, input.value);
        }
      });
      var qs = params.toString();
      var url = qs ? action + (action.indexOf('?') >= 0 ? '&' : '?') + qs : action;
      global.deNavigateWithTransition(url);
      return;
    }
    form.submit();
  }

  function bindDateRange(page) {
    var form = $('#hil-filter-form', page);
    if (
      !form ||
      !global.SalesDateRangePicker ||
      typeof global.SalesDateRangePicker.init !== 'function'
    ) {
      return;
    }
    if (form.getAttribute('data-date-bound') === '1') return;
    form.setAttribute('data-date-bound', '1');
    var dateFrom = $('#hil-date-from', page);
    var dateTo = $('#hil-date-to', page);
    global.SalesDateRangePicker.init({
      wrapId: 'hil-date-range-wrap',
      triggerId: 'hil-date-range-trigger',
      backdropId: 'hil-date-range-backdrop',
      panelId: 'hil-date-range-panel',
      displayId: 'hil-date-range-display',
      formId: 'hil-filter-form',
      fromInputId: 'hil-date-from',
      toInputId: 'hil-date-to',
      applyId: 'hil-date-range-apply',
      prevId: 'hil-cal-prev',
      nextId: 'hil-cal-next',
      title0Id: 'hil-cal-title0',
      title1Id: 'hil-cal-title1',
      grid0Id: 'hil-cal-grid0',
      grid1Id: 'hil-cal-grid1',
      emptyLabel: 'Select date…',
      onBeforeSubmit: function () {
        if (dateFrom && !dateFrom.value) dateFrom.removeAttribute('name');
        if (dateTo && !dateTo.value) dateTo.removeAttribute('name');
        var status = $('#hil-status', form);
        if (status && (status.value === 'all' || !status.value)) {
          status.removeAttribute('name');
        }
      }
    });
    var clearBtn = $('#hil-date-range-clear', page);
    if (clearBtn && clearBtn.getAttribute('data-hil-clear-bound') !== '1') {
      clearBtn.setAttribute('data-hil-clear-bound', '1');
      clearBtn.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        var clearUrl = form.getAttribute('data-clear-url') || form.action || '';
        if (!clearUrl) return;
        if (typeof global.deNavigateWithTransition === 'function') {
          global.deNavigateWithTransition(clearUrl);
          return;
        }
        window.location.href = clearUrl;
      });
    }
  }

  function openInvoice(page, invoiceNumber, autoPrint) {
    if (!invoiceNumber) return;
    var url = invoiceApiUrl(page, invoiceNumber);
    fetch(url, {
      credentials: 'same-origin',
      headers: { Accept: 'application/json' }
    })
      .then(function (res) {
        return res.json().then(function (data) {
          return { ok: res.ok, data: data || {} };
        });
      })
      .then(function (result) {
        if (!result.ok || !result.data.ok || !result.data.room) {
          toast((result.data && result.data.error) || 'Could not load invoice.');
          return;
        }
        if (typeof global.openHotelRoomInvoice !== 'function') {
          toast('Invoice printer is unavailable.');
          return;
        }
        var opened = global.openHotelRoomInvoice(result.data.room, {
          autoPrint: !!autoPrint
        });
        if (!opened) {
          toast('Allow pop-ups to view or print the invoice.');
        }
      })
      .catch(function () {
        toast('Could not load invoice.');
      });
  }

  function settleApiUrl(page, invoiceNumber) {
    var base =
      (page && page.getAttribute('data-settle-api-base')) ||
      '/hotel/invoice-ledger/api/__ID__/settle';
    var encoded = String(invoiceNumber || '')
      .split('/')
      .map(function (part) {
        return encodeURIComponent(part);
      })
      .join('/');
    return String(base).replace('__ID__', encoded);
  }

  function refreshLedgerAfterSettle() {
    var form = document.getElementById('hil-filter-form');
    var url = window.location.pathname + (window.location.search || '');
    if (form) {
      var status = $('#hil-status', form);
      if (status && (status.value === 'all' || !status.value)) {
        status.removeAttribute('name');
      }
      var qs = new URLSearchParams(new FormData(form)).toString();
      url = form.action + (qs ? '?' + qs : '');
    }
    if (typeof global.deNavigateWithTransition === 'function') {
      global.deNavigateWithTransition(url);
      return;
    }
    window.location.href = url;
  }

  function openSettleFromRow(page, row) {
    if (!row) return;
    var invoiceNumber = row.getAttribute('data-invoice-number') || '';
    if (!invoiceNumber) {
      toast('Invoice not found.');
      return;
    }
    if (typeof global.bindHotelSettleModal === 'function') {
      global.bindHotelSettleModal();
    }
    if (typeof global.openHotelSettleModal !== 'function') {
      toast('Payment dialog is unavailable.');
      return;
    }
    var loadUrl = invoiceApiUrl(page, invoiceNumber);
    fetch(loadUrl, {
      credentials: 'same-origin',
      headers: { Accept: 'application/json', 'X-Requested-With': 'XMLHttpRequest' }
    })
      .then(function (res) {
        return res.json().then(function (data) {
          return { ok: res.ok, data: data || {} };
        });
      })
      .then(function (result) {
        if (!result.ok || !result.data.ok || !result.data.room) {
          toast((result.data && result.data.error) || 'Could not load invoice.');
          return;
        }
        var invoice = result.data.invoice || {};
        var balance = Number(
          invoice.balance_amount != null
            ? invoice.balance_amount
            : (result.data.room.stay && result.data.room.stay.balanceAmount) || 0
        );
        if (!(balance > 0.009) || invoice.status === 'settled') {
          toast('Invoice is already settled.');
          return;
        }
        var opened = global.openHotelSettleModal({
          room: result.data.room,
          balance: balance,
          invoiceNumber: invoice.invoice_number || invoiceNumber,
          settleUrl: settleApiUrl(page, invoice.invoice_number || invoiceNumber),
          onSuccess: function () {
            toast('Payment recorded.');
            refreshLedgerAfterSettle();
          }
        });
        if (!opened) toast('Could not open payment dialog.');
      })
      .catch(function () {
        toast('Could not load invoice.');
      });
  }

  function bindActions(page) {
    if (page.getAttribute('data-actions-bound') === '1') return;
    page.setAttribute('data-actions-bound', '1');
    page.addEventListener('click', function (ev) {
      var viewBtn = ev.target.closest('.hil-view-btn');
      if (viewBtn) {
        ev.preventDefault();
        openInvoice(page, viewBtn.getAttribute('data-invoice-number'), false);
        return;
      }
      var printBtn = ev.target.closest('.hil-print-btn');
      if (printBtn) {
        ev.preventDefault();
        openInvoice(page, printBtn.getAttribute('data-invoice-number'), true);
        return;
      }
      if (ev.target.closest('.pl-col-actions')) return;

      var settleBtn = ev.target.closest('[data-hil-settle], .hil-status-settle');
      if (settleBtn) {
        var settleRow = settleBtn.closest('tr.hil-row.is-open');
        if (settleRow && page.contains(settleRow)) {
          ev.preventDefault();
          ev.stopPropagation();
          openSettleFromRow(page, settleRow);
        }
        return;
      }
      var openRow = ev.target.closest('tr.hil-row.is-open');
      if (openRow && page.contains(openRow)) {
        ev.preventDefault();
        openSettleFromRow(page, openRow);
      }
    });
    page.addEventListener('keydown', function (ev) {
      if (ev.key !== 'Enter' && ev.key !== ' ') return;
      var settleBtn = ev.target.closest('[data-hil-settle], .hil-status-settle');
      if (!settleBtn) return;
      var row = settleBtn.closest('tr.hil-row.is-open');
      if (!row || !page.contains(row)) return;
      ev.preventDefault();
      openSettleFromRow(page, row);
    });
  }

  function hilStatusChanged() {
    var form = document.getElementById('hil-filter-form');
    if (form) prepareAndSubmit(form);
  }

  function initHotelInvoiceLedgerPage() {
    var page = document.getElementById('hotel-invoice-ledger-page');
    if (!page) return;
    formatAmounts(page);
    bindClientSearch(page);
    bindSort(page);
    bindStatusFilter(page);
    bindDateRange(page);
    bindActions(page);
    if (typeof global.bindHotelSettleModal === 'function') {
      global.bindHotelSettleModal();
    }
    if (typeof global.initEpListboxes === 'function') {
      global.initEpListboxes();
    }
    updateVisibleCount(page);
  }

  global.hilStatusChanged = hilStatusChanged;
  global.initHotelInvoiceLedgerPage = initHotelInvoiceLedgerPage;
  global.hilSettleClick = function (btn) {
    var page = document.getElementById('hotel-invoice-ledger-page');
    var row = btn && btn.closest ? btn.closest('tr.hil-row.is-open') : null;
    if (!page || !row) return false;
    openSettleFromRow(page, row);
    return false;
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initHotelInvoiceLedgerPage);
  } else if (!global.__deSoftNavInProgress) {
    initHotelInvoiceLedgerPage();
  }
})(typeof window !== 'undefined' ? window : this);
