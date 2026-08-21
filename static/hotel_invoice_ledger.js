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

  function ledgerPageFrom(el) {
    if (el && el.closest) {
      var found = el.closest('[data-hotel-invoice-ledger]');
      if (found) return found;
    }
    return document.querySelector('[data-hotel-invoice-ledger]');
  }

  function ledgerPrefix(page) {
    return (page && page.getAttribute('data-ledger-prefix')) || 'hil';
  }

  function isRoomTransferLedger(page) {
    page = page || ledgerPageFrom();
    return !!(page && page.getAttribute('data-room-transfer-ledger') === '1');
  }

  function isPosRoomTransferRow(row) {
    return (
      String((row && row.getAttribute('data-invoice-source')) || '').toLowerCase() ===
      'pos_room_transfer'
    );
  }

  function $id(page, name) {
    if (!page) return null;
    return page.querySelector('#' + ledgerPrefix(page) + '-' + name);
  }

  function ledgerForm(page) {
    return $id(page, 'filter-form') || (page && page.querySelector('form.hil-ledger-form'));
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

  function actionApiUrl(page, attr, invoiceNumber) {
    var base = (page && page.getAttribute(attr)) || '';
    if (!base) return '';
    var encoded = String(invoiceNumber || '')
      .split('/')
      .map(function (part) {
        return encodeURIComponent(part);
      })
      .join('/');
    return String(base).replace('__ID__', encoded);
  }

  function updateVisibleCount(page) {
    var countEl = $id(page, 'entry-count');
    if (!countEl) return;
    var rows = $all('tr.hil-row', page);
    var visible = rows.filter(function (row) {
      return row.style.display !== 'none';
    }).length;
    countEl.textContent = visible + ' entr' + (visible === 1 ? 'y' : 'ies');
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
      var format =
        typeof global.formatInr === 'function'
          ? function (n) {
              return global.formatInr(n, places);
            }
          : function (n) {
              var v = Number(n);
              if (isNaN(v)) v = 0;
              return (
                '₹' +
                v.toLocaleString('en-IN', {
                  minimumFractionDigits: places,
                  maximumFractionDigits: places
                })
              );
            };
      el.textContent = format(el.getAttribute('data-amount'));
    });
    if (typeof global.scheduleFitKpiValues === 'function') {
      global.scheduleFitKpiValues(root);
    }
  }

  function bindSort(page) {
    var table = $id(page, 'table');
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

  function statusFilterValue(page) {
    var input = $id(page, 'status');
    var val = input ? String(input.value || 'all').trim().toLowerCase() : 'all';
    return val || 'all';
  }

  var STATUS_FILTER_LABELS = {
    all: 'All statuses',
    open: 'Un Settled',
    settled: 'Settled',
    cancelled: 'Cancelled'
  };

  function statusFilterLabels(page) {
    var labels = Object.assign({}, STATUS_FILTER_LABELS);
    if (isRoomTransferLedger(page)) {
      labels.cancelled = 'Invoice Generated';
    }
    return labels;
  }

  function syncStatusListbox(page, key) {
    var want = key || 'all';
    var hidden = $id(page, 'status');
    if (hidden) hidden.value = want;
    var valueEl = $id(page, 'status-value');
    if (valueEl) {
      var labels = statusFilterLabels(page);
      valueEl.textContent = labels[want] || labels.all;
    }
    var list = $id(page, 'status-list');
    if (!list) return;
    $all('.se-filter-listbox-option', list).forEach(function (opt) {
      var on = (opt.getAttribute('data-value') || '') === want;
      opt.classList.toggle('is-selected', on);
      opt.setAttribute('aria-selected', on ? 'true' : 'false');
    });
  }

  function syncKpiSelection(page) {
    var current = statusFilterValue(page);
    $all('.hil-kpi[data-hil-kpi]', page).forEach(function (card) {
      var key = card.getAttribute('data-hil-kpi') || 'all';
      var active = key === 'all' ? current === 'all' : key === current;
      card.classList.toggle('is-active', active);
      card.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
  }

  function setStatusFilter(page, key) {
    var want = String(key || 'all').trim().toLowerCase();
    if (['all', 'open', 'settled', 'cancelled'].indexOf(want) < 0) {
      want = 'all';
    }
    syncStatusListbox(page, want);
    syncKpiSelection(page);
    var form = $id(page, 'filter-form');
    if (form) prepareAndSubmit(form);
  }

  function bindKpiFilters(page) {
    if (page.getAttribute('data-hil-kpi-bound') === '1') return;
    page.setAttribute('data-hil-kpi-bound', '1');
    syncKpiSelection(page);
    page.addEventListener('click', function (ev) {
      var card = ev.target.closest('.hil-kpi[data-hil-kpi]');
      if (!card || !page.contains(card)) return;
      ev.preventDefault();
      var kpiKey = card.getAttribute('data-hil-kpi') || 'all';
      if (kpiKey === 'all') {
        setStatusFilter(page, 'all');
        return;
      }
      var current = statusFilterValue(page);
      setStatusFilter(page, current === kpiKey ? 'all' : kpiKey);
    });
    page.addEventListener('keydown', function (ev) {
      var card = ev.target.closest('.hil-kpi[data-hil-kpi]');
      if (!card || !page.contains(card)) return;
      if (ev.key !== 'Enter' && ev.key !== ' ') return;
      ev.preventDefault();
      card.click();
    });
  }

  function bindClientSearch(page) {
    var input = $id(page, 'search');
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
      syncSelection(page);
    }
    input.addEventListener('input', applySearch);
    applySearch();
  }

  function applyInvoiceTab(tab) {
    if (!tab) return false;
    var page = ledgerPageFrom(tab);
    var form = $id(page, 'filter-form');
    var hidden = $id(page, 'invoice');
    var tabs = $id(page, 'invoice-tabs');
    if (!form || !hidden || !tabs) return false;
    var val = tab.getAttribute('data-value') || 'all';
    if (String(hidden.value || '') === val) return false;
    hidden.value = val;
    $all('.pl-kind-filter-tab', tabs).forEach(function (btn) {
      var on = btn === tab;
      btn.classList.toggle('is-active', on);
      btn.setAttribute('aria-selected', on ? 'true' : 'false');
    });
    prepareAndSubmit(form);
    return false;
  }

  function applyOutletTab(tab) {
    if (!tab) return false;
    var page = ledgerPageFrom(tab);
    var form = $id(page, 'filter-form');
    var hidden = $id(page, 'outlet');
    var tabs = $id(page, 'outlet-tabs');
    if (!form || !hidden || !tabs) return false;
    var val = tab.getAttribute('data-value') || 'all';
    if (String(hidden.value || '') === val) return false;
    hidden.value = val;
    $all('.pl-kind-filter-tab', tabs).forEach(function (btn) {
      var on = btn === tab;
      btn.classList.toggle('is-active', on);
      btn.setAttribute('aria-selected', on ? 'true' : 'false');
    });
    prepareAndSubmit(form);
    return false;
  }

  function bindStatusFilter(page) {
    var form = $id(page, 'filter-form');
    var list = $id(page, 'status-list');
    if (!form || !list || list.getAttribute('data-bound') === '1') return;
    list.setAttribute('data-bound', '1');
    list.addEventListener('click', function (ev) {
      var btn = ev.target.closest('.se-filter-listbox-option');
      if (!btn) return;
      var hidden = $id(page, 'status');
      var valueEl = $id(page, 'status-value');
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
    var page = ledgerPageFrom(form);
    var dateFrom = $id(page, 'date-from') || form.querySelector('[name="date_from"]');
    var dateTo = $id(page, 'date-to') || form.querySelector('[name="date_to"]');
    if (dateFrom && !dateFrom.value) dateFrom.removeAttribute('name');
    if (dateTo && !dateTo.value) dateTo.removeAttribute('name');
    var status = $id(page, 'status') || form.querySelector('[name="status"]');
    if (status && (status.value === 'all' || !status.value)) {
      status.removeAttribute('name');
    }
    var invoice = $id(page, 'invoice') || form.querySelector('[name="invoice"]');
    if (invoice && (invoice.value === 'all' || !invoice.value)) {
      invoice.removeAttribute('name');
    }
    var outlet = $id(page, 'outlet') || form.querySelector('[name="outlet"]');
    if (outlet && (outlet.value === 'all' || !outlet.value)) {
      outlet.removeAttribute('name');
    }
    var skipSoftNav =
      window !== window.top || !!form.querySelector('input[name="popup"]');
    if (!skipSoftNav && typeof global.deNavigateWithTransition === 'function') {
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
    var form = $id(page, 'filter-form');
    if (
      !form ||
      !global.SalesDateRangePicker ||
      typeof global.SalesDateRangePicker.init !== 'function'
    ) {
      return;
    }
    if (form.getAttribute('data-date-bound') === '1') return;
    form.setAttribute('data-date-bound', '1');
    var dateFrom = $id(page, 'date-from');
    var dateTo = $id(page, 'date-to');
    var prefix = ledgerPrefix(page);
    global.SalesDateRangePicker.init({
      wrapId: prefix + '-date-range-wrap',
      triggerId: prefix + '-date-range-trigger',
      backdropId: prefix + '-date-range-backdrop',
      panelId: prefix + '-date-range-panel',
      displayId: prefix + '-date-range-display',
      formId: prefix + '-filter-form',
      fromInputId: prefix + '-date-from',
      toInputId: prefix + '-date-to',
      applyId: prefix + '-date-range-apply',
      prevId: prefix + '-cal-prev',
      nextId: prefix + '-cal-next',
      title0Id: prefix + '-cal-title0',
      title1Id: prefix + '-cal-title1',
      grid0Id: prefix + '-cal-grid0',
      grid1Id: prefix + '-cal-grid1',
      emptyLabel: 'Select date…',
      onBeforeSubmit: function () {
        if (dateFrom && !dateFrom.value) dateFrom.removeAttribute('name');
        if (dateTo && !dateTo.value) dateTo.removeAttribute('name');
        var status = $id(page, 'status');
        if (status && (status.value === 'all' || !status.value)) {
          status.removeAttribute('name');
        }
        var invoice = $id(page, 'invoice');
        if (invoice && (invoice.value === 'all' || !invoice.value)) {
          invoice.removeAttribute('name');
        }
      }
    });
    var clearBtn = $id(page, 'date-range-clear');
    if (clearBtn && clearBtn.getAttribute('data-hil-clear-bound') !== '1') {
      clearBtn.setAttribute('data-hil-clear-bound', '1');
      clearBtn.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        var clearUrl = form.getAttribute('data-clear-url') || form.action || '';
        if (!clearUrl) return;
        var skipSoftNav =
          window !== window.top || !!form.querySelector('input[name="popup"]');
        if (!skipSoftNav && typeof global.deNavigateWithTransition === 'function') {
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
        var invoice = result.data.invoice || {};
        var source = String(invoice.source || '').toLowerCase();
        var openFn =
          source === 'fb_combined_transfer' &&
          typeof global.openFbCombinedTransferInvoice === 'function'
            ? global.openFbCombinedTransferInvoice
            : global.openHotelRoomInvoice;
        var opened = openFn(result.data.room, {
          autoPrint: !!autoPrint,
          invoiceNumber: invoice.invoice_number || '',
          invoiceStatus: invoice.status || '',
          cancelReason: invoice.cancel_reason || ''
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

  function settleSelectedUrl(page) {
    return (
      (page && page.getAttribute('data-settle-selected-url')) ||
      '/hotel/invoice-ledger/api/settle-selected'
    );
  }

  function rowBalance(row) {
    var n = Number(row && row.getAttribute('data-balance'));
    return isFinite(n) ? n : 0;
  }

  function selectableRows(page) {
    return $all('tr.hil-row.is-open', page).filter(function (row) {
      if (row.style.display === 'none') return false;
      var check = row.querySelector('.hil-row-check');
      return !!(check && !check.disabled);
    });
  }

  function checkedRows(page) {
    return $all('tr.hil-row.is-open', page).filter(function (row) {
      var check = row.querySelector('.hil-row-check');
      return !!(check && check.checked);
    });
  }

  function syncSelection(page) {
    var rows = selectableRows(page);
    var checked = checkedRows(page);
    var visibleChecked = rows.filter(function (row) {
      var check = row.querySelector('.hil-row-check');
      return !!(check && check.checked);
    });
    $all('tr.hil-row', page).forEach(function (row) {
      var check = row.querySelector('.hil-row-check');
      row.classList.toggle('is-selected', !!(check && check.checked));
    });
    var selectAll = $id(page, 'select-all');
    if (selectAll) {
      var allOn = rows.length > 0 && visibleChecked.length === rows.length;
      selectAll.checked = allOn;
      selectAll.indeterminate = visibleChecked.length > 0 && !allOn;
      selectAll.disabled = rows.length === 0;
    }
    var bar = $id(page, 'selection-bar');
    var countEl = $id(page, 'select-count');
    var totalEl = $id(page, 'select-total');
    var settleBtn = $id(page, 'settle-selected');
    var count = checked.length;
    var total = checked.reduce(function (sum, row) {
      return sum + rowBalance(row);
    }, 0);
    if (countEl) {
      countEl.textContent =
        count + ' invoice' + (count === 1 ? '' : 's') + ' selected';
    }
    if (totalEl) {
      totalEl.setAttribute('data-amount', String(total));
      if (typeof global.formatAmountNode === 'function') {
        global.formatAmountNode(totalEl);
      } else {
        totalEl.textContent = '₹' + total.toFixed(2);
      }
    }
    if (settleBtn) settleBtn.disabled = count === 0;
    if (bar) {
      if (count > 0) {
        bar.hidden = false;
        bar.removeAttribute('hidden');
      } else {
        bar.hidden = true;
        bar.setAttribute('hidden', '');
      }
    }
  }

  function clearSelection(page) {
    $all('.hil-row-check', page).forEach(function (check) {
      check.checked = false;
    });
    syncSelection(page);
  }

  function bindSelection(page) {
    if (isRoomTransferLedger(page)) return;
    if (page.getAttribute('data-hil-select-bound') === '1') return;
    page.setAttribute('data-hil-select-bound', '1');
    var selectAll = $id(page, 'select-all');
    if (selectAll) {
      selectAll.addEventListener('click', function (ev) {
        ev.stopPropagation();
      });
      selectAll.addEventListener('change', function () {
        var on = !!selectAll.checked;
        selectableRows(page).forEach(function (row) {
          var check = row.querySelector('.hil-row-check');
          if (check) check.checked = on;
        });
        syncSelection(page);
      });
    }
    page.addEventListener('click', function (ev) {
      var check = ev.target.closest
        ? ev.target.closest('.hil-row-check, [id$="-select-all"], .cp-col-check')
        : null;
      if (check && page.contains(check)) ev.stopPropagation();
    });
    page.addEventListener('change', function (ev) {
      var check = ev.target.closest ? ev.target.closest('.hil-row-check') : null;
      if (!check || !page.contains(check)) return;
      syncSelection(page);
    });
    var clearBtn = $id(page, 'clear-selection');
    var closeBtn = $id(page, 'bulk-bar-close');
    function onClear(ev) {
      ev.preventDefault();
      ev.stopPropagation();
      clearSelection(page);
    }
    if (clearBtn) clearBtn.addEventListener('click', onClear);
    if (closeBtn) closeBtn.addEventListener('click', onClear);
    var settleBtn = $id(page, 'settle-selected');
    if (settleBtn) {
      settleBtn.addEventListener('click', function (ev) {
        ev.preventDefault();
        ev.stopPropagation();
        openSettleSelected(page);
      });
    }
    syncSelection(page);
  }

  function refreshLedgerAfterSettle() {
    if (typeof global.deInvalidateSoftNavCacheByPath === 'function') {
      try {
        global.deInvalidateSoftNavCacheByPath('/hotel/invoice-ledger');
        global.deInvalidateSoftNavCacheByPath('/hotel/room-transfer-invoices');
        global.deInvalidateSoftNavCacheByPath('/hotel/credit');
        global.deInvalidateSoftNavCacheByPath('/reports/sales');
      } catch (eInv) {}
    }
    var page = ledgerPageFrom();
    var form = ledgerForm(page);
    var url = window.location.pathname + (window.location.search || '');
    if (form) {
      var status = $id(page, 'status') || form.querySelector('[name="status"]');
      if (status && (status.value === 'all' || !status.value)) {
        status.removeAttribute('name');
      }
      var qs = new URLSearchParams(new FormData(form)).toString();
      url = form.action + (qs ? '?' + qs : '');
    }
    var skipSoftNav =
      window !== window.top || (form && form.querySelector('input[name="popup"]'));
    if (!skipSoftNav && typeof global.deSoftRefresh === 'function') {
      global.deSoftRefresh(url);
      return;
    }
    if (!skipSoftNav && typeof global.deNavigateWithTransition === 'function') {
      global.deNavigateWithTransition(url);
      return;
    }
    window.location.href = url;
  }

  function openSettleSelected(page) {
    if (isRoomTransferLedger(page)) return;
    var rows = checkedRows(page);
    if (!rows.length) {
      toast('Select at least one unsettled invoice.');
      return;
    }
    var items = [];
    for (var i = 0; i < rows.length; i++) {
      var row = rows[i];
      var invoiceNumber = row.getAttribute('data-invoice-number') || '';
      var balance = rowBalance(row);
      if (!invoiceNumber || !(balance > 0.009)) continue;
      items.push({
        invoiceNumber: invoiceNumber,
        settleUrl: settleApiUrl(page, invoiceNumber),
        roomLabel: row.getAttribute('data-room-number') || '—',
        guestName: row.getAttribute('data-guest-name') || '',
        balance: balance,
        allowCredit: row.getAttribute('data-allow-credit') === '1'
      });
    }
    if (!items.length) {
      toast('Selected invoices are already settled.');
      return;
    }
    if (typeof global.bindHotelSettleModal === 'function') {
      global.bindHotelSettleModal();
    }
    if (typeof global.openHotelSettleModal !== 'function') {
      toast('Payment dialog is unavailable.');
      return;
    }
    if (items.length === 1) {
      openSettleFromRow(page, rows[0]);
      return;
    }
    var opened = global.openHotelSettleModal({
      items: items,
      settleSelectedUrl: settleSelectedUrl(page),
      allowCredit: items.every(function (item) {
        return !!item.allowCredit;
      }),
      onSuccess: function (data) {
        var paid = (data && data.paid_count) || items.length;
        toast(
          paid === 1
            ? 'Payment recorded.'
            : 'Payment recorded for ' + paid + ' invoices.'
        );
        refreshLedgerAfterSettle();
      }
    });
    if (!opened) toast('Could not open payment dialog.');
  }

  function openSettleFromRow(page, row) {
    if (!row) return;
    if (isRoomTransferLedger(page) || isPosRoomTransferRow(row)) return;
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
          allowCredit: !!result.data.allow_credit,
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
      if (
        ev.target.closest &&
        ev.target.closest('.hil-row-check, [id$="-select-all"], .cp-col-check, [id$="-selection-bar"]')
      ) {
        return;
      }
      var viewBtn = ev.target.closest('.hil-view-btn');
      if (viewBtn) {
        ev.preventDefault();
        openInvoice(page, viewBtn.getAttribute('data-invoice-number'), false);
        return;
      }
      var editBtn = ev.target.closest('.hil-edit-btn');
      if (editBtn) {
        ev.preventDefault();
        ev.stopPropagation();
        reopenInvoiceForEdit(page, editBtn);
        return;
      }
      var cancelBtn = ev.target.closest('.hil-cancel-btn');
      if (cancelBtn) {
        ev.preventDefault();
        ev.stopPropagation();
        openVoidInvoiceModal(cancelBtn);
        return;
      }
      var printBtn = ev.target.closest('.hil-print-btn');
      if (printBtn) {
        ev.preventDefault();
        openInvoice(page, printBtn.getAttribute('data-invoice-number'), true);
        return;
      }
      if (ev.target.closest('.pl-col-actions')) return;

      if (isRoomTransferLedger(page)) return;

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
      if (isRoomTransferLedger(page)) return;
      if (ev.key !== 'Enter' && ev.key !== ' ') return;
      var settleBtn = ev.target.closest('[data-hil-settle], .hil-status-settle');
      if (!settleBtn) return;
      var row = settleBtn.closest('tr.hil-row.is-open');
      if (!row || !page.contains(row)) return;
      ev.preventDefault();
      openSettleFromRow(page, row);
    });
  }

  var pendingVoidInvoice = null;

  function voidInvoiceModalEl(page) {
    page = page || ledgerPageFrom();
    return $id(page, 'void-modal') || document.querySelector('.hil-void-modal');
  }

  function closeVoidInvoiceModal() {
    var page = ledgerPageFrom();
    var modal = voidInvoiceModalEl(page);
    if (!modal) return;
    modal.hidden = true;
    modal.setAttribute('hidden', '');
    pendingVoidInvoice = null;
    var reason = $id(page, 'void-reason');
    var err = $id(page, 'void-error');
    var confirmBtn = $id(page, 'void-confirm');
    if (reason) reason.value = '';
    if (err) {
      err.hidden = true;
      err.textContent = '';
    }
    if (confirmBtn) confirmBtn.disabled = false;
  }

  function openVoidInvoiceModal(btn) {
    if (!btn) return;
    var invoiceNumber = btn.getAttribute('data-invoice-number');
    if (!invoiceNumber) return;
    pendingVoidInvoice = { invoiceNumber: invoiceNumber, btn: btn };
    var page = ledgerPageFrom(btn);
    var modal = voidInvoiceModalEl(page);
    var lead = $id(page, 'void-lead');
    var reason = $id(page, 'void-reason');
    var err = $id(page, 'void-error');
    if (lead) {
      lead.textContent =
        'Cancel ' + invoiceNumber + '? Enter a reason. This cannot be undone.';
    }
    if (reason) reason.value = '';
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
    if (!pendingVoidInvoice || !pendingVoidInvoice.invoiceNumber) return;
    var page = ledgerPageFrom(pendingVoidInvoice.btn);
    var reasonEl = $id(page, 'void-reason');
    var err = $id(page, 'void-error');
    var confirmBtn = $id(page, 'void-confirm');
    var reason = reasonEl ? String(reasonEl.value || '').trim() : '';
    if (!reason) {
      if (err) {
        err.hidden = false;
        err.textContent = 'Enter a reason for cancellation.';
      }
      if (reasonEl) reasonEl.focus();
      return;
    }
    var invoiceNumber = pendingVoidInvoice.invoiceNumber;
    var url = actionApiUrl(page, 'data-cancel-api-base', invoiceNumber);
    if (!url) {
      if (err) {
        err.hidden = false;
        err.textContent = 'Cancel endpoint is unavailable.';
      }
      return;
    }
    if (confirmBtn) confirmBtn.disabled = true;
    fetch(url, {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
        'X-Requested-With': 'XMLHttpRequest'
      },
      body: JSON.stringify({ reason: reason })
    })
      .then(function (resp) {
        return resp.json().then(function (data) {
          return { ok: resp.ok, data: data || {} };
        });
      })
      .then(function (result) {
        if (!result.ok || !result.data.ok) {
          throw new Error(
            (result.data && result.data.error) || 'Could not cancel invoice.'
          );
        }
        closeVoidInvoiceModal();
        toast('Invoice ' + invoiceNumber + ' cancelled.');
        refreshLedgerAfterSettle();
      })
      .catch(function (errObj) {
        if (err) {
          err.hidden = false;
          err.textContent = errObj.message || 'Could not cancel invoice.';
        }
        if (confirmBtn) confirmBtn.disabled = false;
      });
  }

  function bindVoidInvoiceModal() {
    var modal = voidInvoiceModalEl();
    if (!modal || modal.getAttribute('data-hil-void-bound') === '1') return;
    modal.setAttribute('data-hil-void-bound', '1');
    modal.addEventListener('click', function (event) {
      if (event.target.closest('[data-hil-void-close]')) {
        closeVoidInvoiceModal();
        return;
      }
      if (event.target.closest('[id$="-void-confirm"]')) {
        submitVoidInvoiceModal();
      }
    });
  }

  function reopenInvoiceForEdit(page, btn) {
    var invoiceNumber = btn && btn.getAttribute('data-invoice-number');
    if (!invoiceNumber) return;
    var url = actionApiUrl(page, 'data-reopen-api-base', invoiceNumber);
    if (!url) {
      toast('Edit endpoint is unavailable.');
      return;
    }
    if (btn) btn.disabled = true;
    fetch(url, {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
        'X-Requested-With': 'XMLHttpRequest'
      },
      body: '{}'
    })
      .then(function (resp) {
        return resp.json().then(function (data) {
          return { ok: resp.ok, data: data || {} };
        });
      })
      .then(function (result) {
        if (!result.ok || !result.data.ok) {
          throw new Error(
            (result.data && result.data.error) || 'Could not open invoice for editing.'
          );
        }
        var editUrl = result.data.edit_url;
        if (!editUrl) {
          throw new Error('Could not open invoice for editing.');
        }
        if (typeof global.deNavigateWithTransition === 'function') {
          global.deNavigateWithTransition(editUrl);
          return;
        }
        window.location.href = editUrl;
      })
      .catch(function (err) {
        toast(err.message || 'Could not open invoice for editing.');
      })
      .then(function () {
        if (btn) btn.disabled = false;
      });
  }

  function hilStatusChanged() {
    var form = ledgerForm(ledgerPageFrom());
    if (form) prepareAndSubmit(form);
  }

  function hilInvoiceChanged() {
    var form = ledgerForm(ledgerPageFrom());
    if (form) prepareAndSubmit(form);
  }

  function initHotelInvoiceLedgerPage() {
    var page = document.querySelector('[data-hotel-invoice-ledger]');
    if (!page) return;
    formatAmounts(page);
    bindKpiFilters(page);
    bindClientSearch(page);
    bindSort(page);
    bindStatusFilter(page);
    bindDateRange(page);
    bindActions(page);
    if (!isRoomTransferLedger(page)) bindSelection(page);
    bindVoidInvoiceModal();
    if (typeof global.bindHotelSettleModal === 'function') {
      global.bindHotelSettleModal();
    }
    if (typeof global.initEpListboxes === 'function') {
      global.initEpListboxes();
    }
    updateVisibleCount(page);
  }

  global.hilStatusChanged = hilStatusChanged;
  global.hilInvoiceChanged = hilInvoiceChanged;
  global.hilInvoiceTabClick = applyInvoiceTab;
  global.hilOutletTabClick = applyOutletTab;
  global.initHotelInvoiceLedgerPage = initHotelInvoiceLedgerPage;
  global.hilSettleClick = function (btn) {
    var page = ledgerPageFrom(btn);
    var row = btn && btn.closest ? btn.closest('tr.hil-row.is-open') : null;
    if (!page || !row) return false;
    if (isRoomTransferLedger(page) || isPosRoomTransferRow(row)) return false;
    openSettleFromRow(page, row);
    return false;
  };
  global.hilEditClick = function (btn) {
    var page = ledgerPageFrom(btn);
    if (!page || !btn) return false;
    reopenInvoiceForEdit(page, btn);
    return false;
  };
  global.hilCancelClick = function (btn) {
    if (!btn) return false;
    openVoidInvoiceModal(btn);
    return false;
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initHotelInvoiceLedgerPage);
  } else if (!global.__deSoftNavInProgress) {
    initHotelInvoiceLedgerPage();
  }
})(typeof window !== 'undefined' ? window : this);
