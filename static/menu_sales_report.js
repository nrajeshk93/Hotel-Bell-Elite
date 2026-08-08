/**
 * Menu Sales Report — client search, sort, date/outlet/category/status filters.
 * Soft-nav safe: window.initMenuSalesReportPage / msr*Changed.
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
    var countEl = $('#msr-entry-count', page);
    if (!countEl) return;
    var rows = $all('tr.msr-row', page);
    var visible = rows.filter(function (row) {
      return row.style.display !== 'none' && !row.hidden;
    }).length;
    countEl.textContent =
      visible + ' item' + (visible === 1 ? '' : 's');
  }

  function bindClientSearch(page) {
    var input = $('#msr-search', page);
    if (!input || input.getAttribute('data-msr-bound') === '1') return;
    input.setAttribute('data-msr-bound', '1');
    function apply() {
      var needle = String(input.value || '')
        .trim()
        .toLowerCase();
      $all('tr.msr-row', page).forEach(function (row) {
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
    var table = $('#msr-table', page);
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
    var status = $('#msr-status', form);
    if (status && (status.value === 'all' || !status.value)) {
      status.removeAttribute('name');
    }
    var outlet = $('#msr-outlet', form);
    if (outlet && (outlet.value === 'all' || !outlet.value)) {
      outlet.removeAttribute('name');
    }
    var category = $('#msr-category', form);
    if (category && !category.value) {
      category.removeAttribute('name');
    }
    var dateFrom = $('#msr-date-from', form);
    var dateTo = $('#msr-date-to', form);
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
    var form = $('#msr-filter-form', page);
    if (!form) return;
    var wrap = document.getElementById('msr-date-range-wrap');
    // SalesDateRangePicker sets data-sdr-bound on the wrap; only skip when already bound.
    if (wrap && wrap.getAttribute('data-sdr-bound') === '1') {
      return;
    }
    if (
      !global.SalesDateRangePicker ||
      typeof global.SalesDateRangePicker.init !== 'function'
    ) {
      // Soft-nav may evaluate this script before sales_date_range.js finishes.
      if (!form.getAttribute('data-msr-date-retry')) {
        form.setAttribute('data-msr-date-retry', '1');
        window.setTimeout(function () {
          form.removeAttribute('data-msr-date-retry');
          bindDateRange(page);
        }, 0);
      }
      return;
    }

    var dateFrom = $('#msr-date-from', form);
    var dateTo = $('#msr-date-to', form);
    global.SalesDateRangePicker.init({
      wrapId: 'msr-date-range-wrap',
      triggerId: 'msr-date-range-trigger',
      backdropId: 'msr-date-range-backdrop',
      panelId: 'msr-date-range-panel',
      displayId: 'msr-date-range-display',
      formId: 'msr-filter-form',
      fromInputId: 'msr-date-from',
      toInputId: 'msr-date-to',
      applyId: 'msr-date-range-apply',
      prevId: 'msr-cal-prev',
      nextId: 'msr-cal-next',
      title0Id: 'msr-cal-title0',
      title1Id: 'msr-cal-title1',
      grid0Id: 'msr-cal-grid0',
      grid1Id: 'msr-cal-grid1',
      emptyLabel: 'Select date…',
      onBeforeSubmit: function () {
        if (dateFrom && !dateFrom.value) dateFrom.removeAttribute('name');
        if (dateTo && !dateTo.value) dateTo.removeAttribute('name');
        var status = $('#msr-status', form);
        if (status && (status.value === 'all' || !status.value)) {
          status.removeAttribute('name');
        }
        var outlet = $('#msr-outlet', form);
        if (outlet && (outlet.value === 'all' || !outlet.value)) {
          outlet.removeAttribute('name');
        }
        var category = $('#msr-category', form);
        if (category && !category.value) {
          category.removeAttribute('name');
        }
      }
    });

    var clearBtn = $('#msr-date-range-clear', page);
    if (clearBtn && clearBtn.getAttribute('data-msr-clear-bound') !== '1') {
      clearBtn.setAttribute('data-msr-clear-bound', '1');
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
    var form = document.getElementById('msr-filter-form');
    if (form) prepareAndSubmit(form);
  }

  function msrStatusChanged() {
    submitFilterForm();
  }

  function msrOutletChanged() {
    // Reset category when outlet changes — options are outlet-scoped.
    var category = document.getElementById('msr-category');
    if (category) category.value = '';
    submitFilterForm();
  }

  function msrCategoryChanged() {
    submitFilterForm();
  }

  function initMenuSalesReportPage() {
    var page = document.getElementById('menu-sales-report-page');
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

  global.msrStatusChanged = msrStatusChanged;
  global.msrOutletChanged = msrOutletChanged;
  global.msrCategoryChanged = msrCategoryChanged;
  global.initMenuSalesReportPage = initMenuSalesReportPage;

  // Soft-nav runs this script while __deSoftNavInProgress is true (DOM already
  // swapped). Always bind when the page is present — do not wait for reinit.
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initMenuSalesReportPage);
  } else {
    initMenuSalesReportPage();
  }
})(typeof window !== 'undefined' ? window : this);
