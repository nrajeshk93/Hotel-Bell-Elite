/**
 * Sales Report — client search, sort, date/status/outlet filters.
 * Soft-nav safe: window.initSalesReportPage / window.srStatusChanged / window.srOutletChanged.
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

  function syncGroupVisibility(page) {
    $all('tr.sr-group-header', page).forEach(function (header) {
      var gid = header.getAttribute('data-group') || '';
      var items = $all('tr.sr-row[data-group="' + gid + '"]', page);
      var anyVisible = items.some(function (row) {
        return row.style.display !== 'none' && !row.hidden;
      });
      header.style.display = anyVisible ? '' : 'none';
    });
  }

  function currentKpiFilter(page) {
    return String(page.getAttribute('data-kpi-filter') || 'total').toLowerCase();
  }

  function applyRowFilters(page) {
    var input = $('#sr-search', page);
    var needle = String((input && input.value) || '')
      .trim()
      .toLowerCase();
    var kpi = currentKpiFilter(page);
    $all('tr.sr-row', page).forEach(function (row) {
      var hay = String(row.getAttribute('data-search') || '').toLowerCase();
      var searchOk = !needle || hay.indexOf(needle) !== -1;
      var status = String(row.getAttribute('data-status') || '').toLowerCase();
      var kpiOk = kpi === 'total' || !kpi || status === kpi;
      row.style.display = searchOk && kpiOk ? '' : 'none';
    });
    syncGroupVisibility(page);
    updateVisibleCount(page);
  }

  function syncKpiSelection(page) {
    var kpi = currentKpiFilter(page);
    $all('.kot-kpi[data-kpi]', page).forEach(function (card) {
      var on = String(card.getAttribute('data-kpi') || '') === kpi;
      card.classList.toggle('is-active', on);
      card.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
  }

  function setKpiFilter(page, kpi) {
    var next = String(kpi || 'total').toLowerCase();
    if (currentKpiFilter(page) === next && next !== 'total') {
      next = 'total';
    }
    page.setAttribute('data-kpi-filter', next);
    syncKpiSelection(page);
    applyRowFilters(page);
  }

  function bindKpiFilter(page) {
    if (!page || page.id !== 'kot-report-page') return;
    if (page.getAttribute('data-kpi-bound') === '1') return;
    page.setAttribute('data-kpi-bound', '1');
    page.setAttribute('data-kpi-filter', 'total');
    syncKpiSelection(page);

    page.addEventListener('click', function (event) {
      var card = event.target.closest('.kot-kpi[data-kpi]');
      if (!card || !page.contains(card)) return;
      event.preventDefault();
      setKpiFilter(page, card.getAttribute('data-kpi') || 'total');
    });
    page.addEventListener('keydown', function (event) {
      if (event.key !== 'Enter' && event.key !== ' ') return;
      var card = event.target.closest('.kot-kpi[data-kpi]');
      if (!card || !page.contains(card)) return;
      event.preventDefault();
      setKpiFilter(page, card.getAttribute('data-kpi') || 'total');
    });
  }

  function bindClientSearch(page) {
    var input = $('#sr-search', page);
    if (!input || input.getAttribute('data-sr-bound') === '1') return;
    input.setAttribute('data-sr-bound', '1');
    input.addEventListener('input', function () {
      applyRowFilters(page);
    });
    applyRowFilters(page);
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

      function compare(a, b) {
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
      }

      var groups = [];
      var current = null;
      Array.prototype.forEach.call(tbody.rows, function (row) {
        if (row.classList.contains('sr-group-header')) {
          current = { header: row, items: [] };
          groups.push(current);
          return;
        }
        if (row.classList.contains('sr-row')) {
          if (!current) {
            current = { header: null, items: [] };
            groups.push(current);
          }
          current.items.push(row);
        }
      });

      if (groups.length && groups[0].header) {
        groups.forEach(function (group) {
          group.items.sort(compare);
          if (group.header) tbody.appendChild(group.header);
          group.items.forEach(function (row) {
            tbody.appendChild(row);
          });
        });
      } else {
        var rows = Array.prototype.slice.call(tbody.rows);
        rows.sort(compare);
        rows.forEach(function (row) {
          tbody.appendChild(row);
        });
      }
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
    var outlet = $('#sr-outlet', form);
    if (outlet && (outlet.value === 'all' || !outlet.value)) {
      outlet.removeAttribute('name');
    }
    var agency = $('#sr-agency', form);
    if (agency && (agency.value === 'all' || !agency.value)) {
      agency.removeAttribute('name');
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
    var singleDay = page.getAttribute('data-report-kind') === 'meal-plan';
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
      singleDay: singleDay,
      onBeforeSubmit: function () {
        if (singleDay && dateFrom && dateTo && dateFrom.value) {
          dateTo.value = dateFrom.value;
          dateTo.setAttribute('name', 'date_to');
        }
        if (dateFrom && !dateFrom.value) dateFrom.removeAttribute('name');
        if (dateTo && !dateTo.value) dateTo.removeAttribute('name');
        var status = $('#sr-status', form);
        if (status && (status.value === 'all' || !status.value)) {
          status.removeAttribute('name');
        }
        var outlet = $('#sr-outlet', form);
        if (outlet && (outlet.value === 'all' || !outlet.value)) {
          outlet.removeAttribute('name');
        }
        var agency = $('#sr-agency', form);
        if (agency && (agency.value === 'all' || !agency.value)) {
          agency.removeAttribute('name');
        }
      }
    });

    var todayBtn = $('#sr-date-range-today', page);
    if (todayBtn && todayBtn.getAttribute('data-sr-today-bound') !== '1') {
      todayBtn.setAttribute('data-sr-today-bound', '1');
      todayBtn.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        var wrap = $('#sr-date-range-wrap', page);
        var today = String(
          (wrap && wrap.getAttribute('data-max-date')) || ''
        ).trim();
        if (!today) return;
        if (dateFrom) {
          dateFrom.value = today;
          dateFrom.setAttribute('name', 'date_from');
        }
        if (dateTo) {
          dateTo.value = today;
          dateTo.setAttribute('name', 'date_to');
        }
        prepareAndSubmit(form);
      });
    }

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

  function srOutletChanged() {
    var form = document.getElementById('sr-filter-form');
    if (form) prepareAndSubmit(form);
  }

  function srAgencyChanged() {
    var form = document.getElementById('sr-filter-form');
    if (form) prepareAndSubmit(form);
  }

  function findSalesReportPage() {
    return (
      document.getElementById('sales-report-page') ||
      document.getElementById('meal-plan-report-page') ||
      document.getElementById('kot-report-page') ||
      document.querySelector('[data-sales-report]')
    );
  }

  function initSalesReportPage() {
    var page = findSalesReportPage();
    if (!page) return;
    formatAmounts(page);
    bindKpiFilter(page);
    bindClientSearch(page);
    bindSort(page);
    bindStatusFilter(page);
    bindDateRange(page);
    if (typeof global.initEpListboxes === 'function') {
      global.initEpListboxes();
    }
    updateVisibleCount(page);
    bindAgencyBillingLiveRefresh(page);
  }

  /** Agency billing mutates as invoices settle — refresh when returning to the tab/page. */
  function bindAgencyBillingLiveRefresh(page) {
    if (!page || page.getAttribute('data-report-kind') !== 'agency') return;
    if (page.getAttribute('data-sr-live-refresh-bound') === '1') return;
    page.setAttribute('data-sr-live-refresh-bound', '1');
    var lastHiddenAt = 0;

    function softReload() {
      if (typeof global.deSoftRefresh === 'function') {
        global.deSoftRefresh(window.location.href);
      } else {
        window.location.reload();
      }
    }

    document.addEventListener('visibilitychange', function () {
      if (document.hidden) {
        lastHiddenAt = Date.now();
        return;
      }
      if (!findSalesReportPage()) return;
      if (lastHiddenAt && Date.now() - lastHiddenAt > 1500) softReload();
    });

    global.addEventListener('pageshow', function (ev) {
      if (ev && ev.persisted) softReload();
    });
  }

  global.srStatusChanged = srStatusChanged;
  global.srOutletChanged = srOutletChanged;
  global.srAgencyChanged = srAgencyChanged;
  global.initSalesReportPage = initSalesReportPage;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initSalesReportPage);
  } else if (!global.__deSoftNavInProgress) {
    initSalesReportPage();
  }
})(typeof window !== 'undefined' ? window : this);
