/**
 * Customer Insights Report — client search, sort, date/channel/status filters.
 * Soft-nav safe: window.initCustomerInsightsReportPage / cir*Changed.
 */
(function (global) {
  'use strict';

  function $(sel, root) {
    return (root || document).querySelector(sel);
  }

  function $all(sel, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(sel));
  }

  function formatAmounts(root) {
    function format(n, decimals) {
      var dec = decimals == null ? 2 : decimals;
      if (typeof global.formatInr === 'function') {
        return global.formatInr(n, dec);
      }
      var v = Number(n);
      if (isNaN(v)) v = 0;
      return (
        '₹' +
        v.toLocaleString('en-IN', {
          minimumFractionDigits: dec,
          maximumFractionDigits: dec
        })
      );
    }
    $all('.pl-amount[data-amount]', root).forEach(function (el) {
      if (typeof global.formatAmountNode === 'function') {
        global.formatAmountNode(el);
        return;
      }
      var isKpi = el.classList.contains('pl-summary-value');
      el.textContent = format(el.getAttribute('data-amount'), isKpi ? 0 : 2);
    });
    if (typeof global.scheduleFitKpiValues === 'function') {
      global.scheduleFitKpiValues(root);
    }
  }

  function updateVisibleCount(page) {
    var countEl = $('#cir-entry-count', page);
    if (!countEl) return;
    var rows = $all('tr.cir-row', page);
    var visible = rows.filter(function (row) {
      return row.style.display !== 'none' && !row.hidden;
    }).length;
    countEl.textContent =
      visible + ' customer' + (visible === 1 ? '' : 's');
  }

  function bindClientSearch(page) {
    var input = $('#cir-search', page);
    if (!input || input.getAttribute('data-cir-bound') === '1') return;
    input.setAttribute('data-cir-bound', '1');
    function apply() {
      var needle = String(input.value || '')
        .trim()
        .toLowerCase();
      $all('tr.cir-row', page).forEach(function (row) {
        var hay = String(row.getAttribute('data-search') || '').toLowerCase();
        var match = !needle || hay.indexOf(needle) !== -1;
        row.style.display = match ? '' : 'none';
      });
      updateVisibleCount(page);
    }
    input.addEventListener('input', apply);
    apply();
  }

  function bindSort(page) {
    var table = $('#cir-table', page);
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
      headers.forEach(function (h) {
        h.setAttribute('aria-sort', 'none');
      });
      th.setAttribute('aria-sort', ascending ? 'ascending' : 'descending');
    }

    headers.forEach(function (th) {
      th.addEventListener('click', function () {
        sortBy(th);
      });
      th.addEventListener('keydown', function (ev) {
        if (ev.key === 'Enter' || ev.key === ' ') {
          ev.preventDefault();
          sortBy(th);
        }
      });
    });
  }

  function prepareAndSubmit(form) {
    if (!form) return;
    var status = $('#cir-status', form);
    if (status && (status.value === 'all' || !status.value)) {
      status.removeAttribute('name');
    }
    var channel = $('#cir-channel', form);
    if (channel && (channel.value === 'all' || !channel.value)) {
      channel.removeAttribute('name');
    }
    var dateFrom = $('#cir-date-from', form);
    var dateTo = $('#cir-date-to', form);
    if (dateFrom && !dateFrom.value) dateFrom.removeAttribute('name');
    if (dateTo && !dateTo.value) dateTo.removeAttribute('name');
    var qs = new URLSearchParams(new FormData(form)).toString();
    var url = form.action + (qs ? '?' + qs : '');
    if (typeof global.deNavigateWithTransition === 'function') {
      global.deNavigateWithTransition(url);
      return;
    }
    window.location.href = url;
  }

  function bindDateRange(page) {
    var form = $('#cir-filter-form', page);
    if (!form) return;
    var wrap = document.getElementById('cir-date-range-wrap');
    if (wrap && wrap.getAttribute('data-sdr-bound') === '1') {
      return;
    }
    if (
      !global.SalesDateRangePicker ||
      typeof global.SalesDateRangePicker.init !== 'function'
    ) {
      if (!form.getAttribute('data-cir-date-retry')) {
        form.setAttribute('data-cir-date-retry', '1');
        window.setTimeout(function () {
          form.removeAttribute('data-cir-date-retry');
          bindDateRange(page);
        }, 0);
      }
      return;
    }

    var dateFrom = $('#cir-date-from', form);
    var dateTo = $('#cir-date-to', form);
    global.SalesDateRangePicker.init({
      wrapId: 'cir-date-range-wrap',
      triggerId: 'cir-date-range-trigger',
      backdropId: 'cir-date-range-backdrop',
      panelId: 'cir-date-range-panel',
      displayId: 'cir-date-range-display',
      formId: 'cir-filter-form',
      fromInputId: 'cir-date-from',
      toInputId: 'cir-date-to',
      applyId: 'cir-date-range-apply',
      prevId: 'cir-cal-prev',
      nextId: 'cir-cal-next',
      title0Id: 'cir-cal-title0',
      title1Id: 'cir-cal-title1',
      grid0Id: 'cir-cal-grid0',
      grid1Id: 'cir-cal-grid1',
      emptyLabel: 'Select date…',
      onBeforeSubmit: function () {
        if (dateFrom && !dateFrom.value) dateFrom.removeAttribute('name');
        if (dateTo && !dateTo.value) dateTo.removeAttribute('name');
        var status = $('#cir-status', form);
        if (status && (status.value === 'all' || !status.value)) {
          status.removeAttribute('name');
        }
        var channel = $('#cir-channel', form);
        if (channel && (channel.value === 'all' || !channel.value)) {
          channel.removeAttribute('name');
        }
      }
    });

    var clearBtn = $('#cir-date-range-clear', page);
    if (clearBtn && clearBtn.getAttribute('data-cir-clear-bound') !== '1') {
      clearBtn.setAttribute('data-cir-clear-bound', '1');
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

  function submitFilterForm() {
    var form = document.getElementById('cir-filter-form');
    if (form) prepareAndSubmit(form);
  }

  function cirStatusChanged() {
    submitFilterForm();
  }

  function cirChannelChanged() {
    submitFilterForm();
  }

  function initCustomerInsightsReportPage() {
    var page = document.getElementById('customer-insights-report-page');
    if (!page) return;
    formatAmounts(page);
    bindClientSearch(page);
    bindSort(page);
    bindDateRange(page);
    if (typeof global.initEpListboxes === 'function') {
      global.initEpListboxes();
    }
    updateVisibleCount(page);
  }

  global.cirStatusChanged = cirStatusChanged;
  global.cirChannelChanged = cirChannelChanged;
  global.initCustomerInsightsReportPage = initCustomerInsightsReportPage;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initCustomerInsightsReportPage);
  } else {
    initCustomerInsightsReportPage();
  }
})(typeof window !== 'undefined' ? window : this);
