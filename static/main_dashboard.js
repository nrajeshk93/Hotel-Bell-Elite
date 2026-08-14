/**
 * Main Dashboard filter header — Period pills + Outlet/Date chips.
 * Period clicks use document delegation so soft-nav DOM swaps stay clickable.
 */
(function (global) {
  function $(id, root) {
    if (!id) return null;
    // IDs are document-unique; Element has no getElementById.
    var el = document.getElementById(id);
    if (!el || !root || root === document) return el;
    if (root.contains && !root.contains(el)) return null;
    return el;
  }

  function parseISODate(iso) {
    if (!iso || !/^\d{4}-\d{2}-\d{2}$/.test(iso)) return null;
    var parts = iso.split('-').map(Number);
    return new Date(parts[0], parts[1] - 1, parts[2]);
  }

  function toISODate(d) {
    if (!d || isNaN(d.getTime())) return '';
    var y = d.getFullYear();
    var m = String(d.getMonth() + 1).padStart(2, '0');
    var day = String(d.getDate()).padStart(2, '0');
    return y + '-' + m + '-' + day;
  }

  function addDays(d, delta) {
    return new Date(d.getFullYear(), d.getMonth(), d.getDate() + delta);
  }

  function periodRange(period, todayIso) {
    var today = parseISODate(todayIso) || new Date();
    today = new Date(today.getFullYear(), today.getMonth(), today.getDate());
    var key = String(period || '').toLowerCase();
    if (key === 'today') return { from: today, to: today };
    if (key === 'yesterday') {
      var y = addDays(today, -1);
      return { from: y, to: y };
    }
    if (key === '7d') return { from: addDays(today, -6), to: today };
    if (key === '30d') return { from: addDays(today, -29), to: today };
    if (key === 'mtd') return { from: new Date(today.getFullYear(), today.getMonth(), 1), to: today };
    if (key === 'qtd') {
      var qMonth = Math.floor(today.getMonth() / 3) * 3;
      return { from: new Date(today.getFullYear(), qMonth, 1), to: today };
    }
    if (key === 'ytd') return { from: new Date(today.getFullYear(), 0, 1), to: today };
    return { from: addDays(today, -29), to: today };
  }

  function submitFilterForm(form) {
    if (!form) return;
    if (typeof global.deSoftSubmitForm === 'function' && global.deSoftSubmitForm(form)) return;
    if (typeof form.requestSubmit === 'function') form.requestSubmit();
    else form.submit();
  }

  function setActivePeriodPills(page, period) {
    var root = page || document.getElementById('main-dashboard-page') || document;
    root.querySelectorAll('[data-md-period]').forEach(function (pill) {
      var active = pill.getAttribute('data-md-period') === period;
      pill.classList.toggle('is-active', active);
      pill.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
  }

  function applyPeriodPill(pill) {
    if (!pill) return;
    var form = pill.closest('#md-filter-form');
    if (!form) return;
    var page = document.getElementById('main-dashboard-page') || form;
    var periodInput = $('md-period', page) || form.querySelector('[name="period"]');
    var dateFrom = $('md-date-from', page) || form.querySelector('[name="date_from"]');
    var dateTo = $('md-date-to', page) || form.querySelector('[name="date_to"]');
    var todayIso = form.getAttribute('data-today') || '';
    var period = pill.getAttribute('data-md-period') || '30d';
    var range = periodRange(period, todayIso);
    if (periodInput) periodInput.value = period;
    if (dateFrom) dateFrom.value = toISODate(range.from);
    if (dateTo) dateTo.value = toISODate(range.to);
    setActivePeriodPills(page, period);
    form.setAttribute('data-selected-period', period);
    submitFilterForm(form);
  }

  function ensurePeriodPillDelegation() {
    if (global.__mdPeriodPillsDelegated) return;
    global.__mdPeriodPillsDelegated = true;
    document.addEventListener('click', function (e) {
      var pill = e.target && e.target.closest ? e.target.closest('[data-md-period]') : null;
      if (!pill || !pill.closest('#md-filter-form')) return;
      e.preventDefault();
      e.stopPropagation();
      applyPeriodPill(pill);
    });
  }

  function bindDateRange(page, form) {
    if (!form || !global.SalesDateRangePicker || typeof global.SalesDateRangePicker.init !== 'function') {
      return;
    }
    var periodInput = $('md-period', page);
    global.SalesDateRangePicker.init({
      wrapId: 'md-date-range-wrap',
      triggerId: 'md-date-range-trigger',
      backdropId: 'md-date-range-backdrop',
      panelId: 'md-date-range-panel',
      displayId: 'md-date-range-display',
      formId: 'md-filter-form',
      fromInputId: 'md-date-from',
      toInputId: 'md-date-to',
      applyId: 'md-date-range-apply',
      prevId: 'md-cal-prev',
      nextId: 'md-cal-next',
      title0Id: 'md-cal-title0',
      title1Id: 'md-cal-title1',
      grid0Id: 'md-cal-grid0',
      grid1Id: 'md-cal-grid1',
      emptyLabel: 'Select date…',
      onBeforeSubmit: function () {
        if (periodInput) periodInput.value = 'custom';
        setActivePeriodPills(page, 'custom');
        form.setAttribute('data-selected-period', 'custom');
      }
    });

    var clearBtn = $('md-date-range-clear', page);
    if (clearBtn && clearBtn.getAttribute('data-md-clear-bound') !== '1') {
      clearBtn.setAttribute('data-md-clear-bound', '1');
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

  function escapeHtml(text) {
    return String(text == null ? '' : text)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function readDashboardData() {
    var el = document.getElementById('md-dashboard-data');
    if (!el) return null;
    try {
      return JSON.parse(el.textContent || '{}');
    } catch (e) {
      return null;
    }
  }

  function renderTopSellingList(listEl, rows) {
    if (!listEl) return;
    if (!rows || !rows.length) {
      listEl.innerHTML = '<p class="rdx-ti-empty">No menu sales in this period.</p>';
      return;
    }
    listEl.innerHTML = rows.map(function (row) {
      var sale = escapeHtml(row.sale_value_compact || '');
      var qty = escapeHtml(row.qty_display || '');
      var name = escapeHtml(row.name || 'Item');
      var rank = escapeHtml(row.rank || '');
      return (
        '<div class="rdx-ti-row">'
        + '<div class="rdx-ti-product">'
        + '<span class="rdx-ti-rank">' + rank + '</span>'
        + '<span class="rdx-ti-name">' + name + '</span>'
        + '</div>'
        + '<span class="rdx-ti-qty">' + qty + '</span>'
        + '<span class="rdx-ti-sale" title="Total sales ' + sale + '">' + sale + '</span>'
        + '</div>'
      );
    }).join('');
  }

  function applyTopItemsSort(card, sortBy) {
    if (!card) return;
    var mode = sortBy === 'revenue' ? 'revenue' : 'qty';
    var data = readDashboardData() || {};
    var rows = mode === 'revenue'
      ? (data.top_selling_items_by_revenue || data.top_selling_items || [])
      : (data.top_selling_items || []);
    var listEl = card.querySelector('[data-md-ti-list]');
    var subtitle = card.querySelector('[data-md-ti-subtitle]');
    renderTopSellingList(listEl, rows);
    if (subtitle) {
      subtitle.textContent = mode === 'revenue' ? 'By revenue' : 'By quantity sold';
    }
    card.querySelectorAll('[data-md-ti-sort]').forEach(function (btn) {
      var active = btn.getAttribute('data-md-ti-sort') === mode;
      btn.classList.toggle('is-active', active);
      btn.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
    card.setAttribute('data-md-ti-mode', mode);
  }

  function ensureTopItemsSortDelegation() {
    if (document.documentElement.getAttribute('data-md-ti-sort-bound') === '1') return;
    document.documentElement.setAttribute('data-md-ti-sort-bound', '1');
    document.addEventListener('click', function (e) {
      var btn = e.target && e.target.closest ? e.target.closest('[data-md-ti-sort]') : null;
      if (!btn) return;
      var card = btn.closest('[data-md-top-items]');
      if (!card) return;
      e.preventDefault();
      applyTopItemsSort(card, btn.getAttribute('data-md-ti-sort') || 'qty');
    });
  }

  function bindTopItemsSort(page) {
    ensureTopItemsSortDelegation();
    var card = (page || document).querySelector('[data-md-top-items]');
    if (!card) return;
    var mode = card.getAttribute('data-md-ti-mode') || 'qty';
    applyTopItemsSort(card, mode);
  }

  function initMainDashboardFilters() {
    ensurePeriodPillDelegation();
    ensureTopItemsSortDelegation();

    var page = document.getElementById('main-dashboard-page');
    if (!page) return;
    var form = $('md-filter-form', page);
    if (form) {
      // Mark for diagnostics; clicks no longer depend on per-form listeners.
      form.setAttribute('data-md-period-bound', '1');
      bindDateRange(page, form);
    }

    bindTopItemsSort(page);

    if (typeof global.initEpListboxes === 'function') {
      global.initEpListboxes();
    }
    if (typeof global.initMainDashboardCharts === 'function') {
      try {
        global.initMainDashboardCharts();
      } catch (e) {}
    }
    if (typeof global.scheduleFitKpiValues === 'function') {
      global.scheduleFitKpiValues();
    }
  }

  global.initMainDashboardFilters = initMainDashboardFilters;
  global.applyMainDashboardPeriodPill = applyPeriodPill;

  // Install delegation immediately so soft-nav can click before reinit runs.
  ensurePeriodPillDelegation();

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initMainDashboardFilters);
  } else {
    initMainDashboardFilters();
  }
})(typeof window !== 'undefined' ? window : this);
