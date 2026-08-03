/**
 * Sales Report — client search, sort, date/status filters.
 * Soft-nav safe: window.initSalesReportPage / window.srStatusChanged.
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

  function updateVisibleCount(page) {
    var countEl = $('#sr-entry-count', page);
    if (!countEl) return;
    var rows = $all('tr.sr-row', page);
    var visible = rows.filter(function (row) {
      return row.style.display !== 'none' && !row.hidden;
    }).length;
    countEl.textContent =
      visible + ' entr' + (visible === 1 ? 'y' : 'ies');
  }

  function bindClientSearch(page) {
    var input = $('#sr-search', page);
    if (!input || input.getAttribute('data-sr-bound') === '1') return;
    input.setAttribute('data-sr-bound', '1');
    function apply() {
      var needle = String(input.value || '')
        .trim()
        .toLowerCase();
      $all('tr.sr-row', page).forEach(function (row) {
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
    var table = $('#sr-table', page);
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
    var status = $('#sr-status', form);
    if (status && (status.value === 'all' || !status.value)) {
      status.removeAttribute('name');
    }
    var dateFrom = $('#sr-date-from', form);
    var dateTo = $('#sr-date-to', form);
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

  function bindStatusFilter(page) {
    var form = $('#sr-filter-form', page);
    if (!form) return;
  }

  function bindDateRange(page) {
    var form = $('#sr-filter-form', page);
    if (
      !form ||
      !global.SalesDateRangePicker ||
      typeof global.SalesDateRangePicker.init !== 'function'
    ) {
      return;
    }
    if (form.getAttribute('data-sr-date-bound') === '1') return;
    form.setAttribute('data-sr-date-bound', '1');

    var dateFrom = $('#sr-date-from', form);
    var dateTo = $('#sr-date-to', form);
    global.SalesDateRangePicker.init({
      wrapId: 'sr-date-range-wrap',
      triggerId: 'sr-date-range-trigger',
      backdropId: 'sr-date-range-backdrop',
      panelId: 'sr-date-range-panel',
      displayId: 'sr-date-range-display',
      formId: 'sr-filter-form',
      fromInputId: 'sr-date-from',
      toInputId: 'sr-date-to',
      applyId: 'sr-date-range-apply',
      prevId: 'sr-cal-prev',
      nextId: 'sr-cal-next',
      title0Id: 'sr-cal-title0',
      title1Id: 'sr-cal-title1',
      grid0Id: 'sr-cal-grid0',
      grid1Id: 'sr-cal-grid1',
      emptyLabel: 'Select date…',
      onBeforeSubmit: function () {
        if (dateFrom && !dateFrom.value) dateFrom.removeAttribute('name');
        if (dateTo && !dateTo.value) dateTo.removeAttribute('name');
        var status = $('#sr-status', form);
        if (status && (status.value === 'all' || !status.value)) {
          status.removeAttribute('name');
        }
      }
    });

    var clearBtn = $('#sr-date-range-clear', page);
    if (clearBtn && clearBtn.getAttribute('data-sr-clear-bound') !== '1') {
      clearBtn.setAttribute('data-sr-clear-bound', '1');
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

  function srStatusChanged() {
    var form = document.getElementById('sr-filter-form');
    if (form) prepareAndSubmit(form);
  }

  function initSalesReportPage() {
    var page = document.getElementById('sales-report-page');
    if (!page) return;
    formatAmounts(page);
    bindClientSearch(page);
    bindSort(page);
    bindStatusFilter(page);
    bindDateRange(page);
    if (typeof global.initEpListboxes === 'function') {
      global.initEpListboxes();
    }
    updateVisibleCount(page);
  }

  global.srStatusChanged = srStatusChanged;
  global.initSalesReportPage = initSalesReportPage;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initSalesReportPage);
  } else if (!global.__deSoftNavInProgress) {
    initSalesReportPage();
  }
})(typeof window !== 'undefined' ? window : this);
