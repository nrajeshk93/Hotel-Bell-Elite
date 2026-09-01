/**
 * Unit Insight Report — client search, column sort, date/outlet/status filters.
 */
(function (global) {
  'use strict';

  function $(sel, root) {
    return (root || document).querySelector(sel);
  }

  function $all(sel, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(sel));
  }

  function updateVisibleCount(page) {
    var countEl = $('#uir-entry-count', page);
    if (!countEl) return;
    var rows = $all('tr.uir-row', page);
    var visible = rows.filter(function (row) {
      return row.style.display !== 'none' && !row.hidden;
    }).length;
    countEl.textContent = visible + ' product' + (visible === 1 ? '' : 's');
  }

  function bindClientSearch(page) {
    var input = $('#uir-search', page);
    if (!input || input.getAttribute('data-uir-bound') === '1') return;
    input.setAttribute('data-uir-bound', '1');
    function apply() {
      var needle = String(input.value || '').trim();
      $all('tr.uir-row', page).forEach(function (row) {
        var hay = String(row.getAttribute('data-search') || '');
        var score = needle ? global.hbeBestSearchScore([hay], needle) : 0;
        row.style.display = !needle || score >= 0 ? '' : 'none';
      });
      updateVisibleCount(page);
    }
    input.addEventListener('input', apply);
    apply();
  }

  function bindSort(page) {
    var table = $('#uir-table', page);
    if (!table || table.getAttribute('data-sort-bound') === '1') return;
    table.setAttribute('data-sort-bound', '1');
    var tbody = table.tBodies[0];
    if (!tbody) return;
    var headers = $all('th.pl-sortable', table);
    var activeKey = '';
    var ascending = true;

    function cellSortValue(row, colIndex, type) {
      var cell = row.cells[colIndex];
      if (!cell) return '';
      if (type === 'number') {
        var raw = cell.getAttribute('data-sort-value');
        var num = parseFloat(raw);
        return isNaN(num) ? 0 : num;
      }
      return String(cell.getAttribute('data-sort-value') || cell.textContent || '').toLowerCase();
    }

    function sortRows(key, colIndex, type) {
      var rows = $all('tr.uir-row', tbody);
      rows.sort(function (a, b) {
        var av = cellSortValue(a, colIndex, type);
        var bv = cellSortValue(b, colIndex, type);
        if (type === 'number') {
          return ascending ? av - bv : bv - av;
        }
        if (av < bv) return ascending ? -1 : 1;
        if (av > bv) return ascending ? 1 : -1;
        return 0;
      });
      var frag = document.createDocumentFragment();
      rows.forEach(function (row) { frag.appendChild(row); });
      tbody.appendChild(frag);
    }

    headers.forEach(function (th) {
      th.addEventListener('click', function () {
        var key = th.getAttribute('data-sort') || '';
        var colIndex = th.cellIndex;
        var type = th.getAttribute('data-sort-type') || 'text';
        if (activeKey === key) ascending = !ascending;
        else {
          activeKey = key;
          ascending = true;
        }
        headers.forEach(function (header) {
          header.setAttribute('aria-sort', 'none');
        });
        th.setAttribute('aria-sort', ascending ? 'ascending' : 'descending');
        sortRows(key, colIndex, type);
      });
    });
  }

  function submitFilterForm() {
    var form = document.getElementById('uir-filter-form');
    if (!form) return;
    if (typeof global.deNavigateWithTransition === 'function') {
      var params = new URLSearchParams(new FormData(form));
      var url = form.getAttribute('action') || window.location.pathname;
      var qs = params.toString();
      global.deNavigateWithTransition(qs ? url + '?' + qs : url);
      return;
    }
    form.submit();
  }

  function bindDateRange(page) {
    var form = $('#uir-filter-form', page);
    if (!form) return;
    var wrap = document.getElementById('uir-date-range-wrap');
    if (wrap && wrap.getAttribute('data-sdr-bound') === '1') {
      return;
    }
    if (
      !global.SalesDateRangePicker ||
      typeof global.SalesDateRangePicker.init !== 'function'
    ) {
      if (!form.getAttribute('data-uir-date-retry')) {
        form.setAttribute('data-uir-date-retry', '1');
        window.setTimeout(function () {
          form.removeAttribute('data-uir-date-retry');
          bindDateRange(page);
        }, 0);
      }
      return;
    }

    global.SalesDateRangePicker.init({
      wrapId: 'uir-date-range-wrap',
      triggerId: 'uir-date-range-trigger',
      backdropId: 'uir-date-range-backdrop',
      panelId: 'uir-date-range-panel',
      displayId: 'uir-date-range-display',
      formId: 'uir-filter-form',
      fromInputId: 'uir-date-from',
      toInputId: 'uir-date-to',
      applyId: 'uir-date-range-apply',
      prevId: 'uir-cal-prev',
      nextId: 'uir-cal-next',
      title0Id: 'uir-cal-title0',
      title1Id: 'uir-cal-title1',
      grid0Id: 'uir-cal-grid0',
      grid1Id: 'uir-cal-grid1',
      emptyLabel: 'Select date…',
      onApply: function () {
        submitFilterForm();
      }
    });

    var clearBtn = $('#uir-date-range-clear', page);
    if (clearBtn && clearBtn.getAttribute('data-uir-clear-bound') !== '1') {
      clearBtn.setAttribute('data-uir-clear-bound', '1');
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

  function uirStatusChanged() {
    submitFilterForm();
  }

  function uirOutletChanged() {
    submitFilterForm();
  }

  function initUnitInsightsReportPage() {
    var page = document.getElementById('unit-insights-report-page');
    if (!page) return;
    bindClientSearch(page);
    bindSort(page);
    bindDateRange(page);
    if (typeof global.initEpListboxes === 'function') {
      global.initEpListboxes();
    }
    updateVisibleCount(page);
  }

  global.uirStatusChanged = uirStatusChanged;
  global.uirOutletChanged = uirOutletChanged;
  global.initUnitInsightsReportPage = initUnitInsightsReportPage;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initUnitInsightsReportPage);
  } else {
    initUnitInsightsReportPage();
  }
})(typeof window !== 'undefined' ? window : this);
