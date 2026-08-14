/**
 * Manager Insight — Period pills + Duration date range.
 * Soft-nav safe: window.initManagerInsightReportPage.
 */
(function (global) {
  'use strict';

  function $(sel, root) {
    return (root || document).querySelector(sel);
  }

  function $all(sel, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(sel));
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
    return { from: new Date(today.getFullYear(), today.getMonth(), 1), to: today };
  }

  function formatAmounts(root) {
    $all('.pl-amount[data-amount]', root).forEach(function (el) {
      if (typeof global.formatAmountNode === 'function') {
        global.formatAmountNode(el);
        return;
      }
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
      el.textContent = format(el.getAttribute('data-amount'));
    });
  }

  function prepareAndSubmit(form) {
    if (!form) return;
    if (typeof global.deNavigateFormWithTransition === 'function') {
      global.deNavigateFormWithTransition(form);
      return;
    }
    form.submit();
  }

  function setActivePeriodPills(page, period) {
    var root = page || document.getElementById('manager-insight-report-page') || document;
    $all('[data-mi-period]', root).forEach(function (pill) {
      var active = pill.getAttribute('data-mi-period') === period;
      pill.classList.toggle('is-active', active);
      pill.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
  }

  function applyPeriodPill(pill) {
    if (!pill) return;
    var form = pill.closest('#mi-filter-form');
    if (!form) return;
    var page = document.getElementById('manager-insight-report-page') || form;
    var periodInput = $('#mi-period', form);
    var dateFrom = $('#mi-date-from', form);
    var dateTo = $('#mi-date-to', form);
    var todayIso = form.getAttribute('data-today') || '';
    var period = pill.getAttribute('data-mi-period') || 'mtd';
    var range = periodRange(period, todayIso);
    if (periodInput) periodInput.value = period;
    if (dateFrom) dateFrom.value = toISODate(range.from);
    if (dateTo) dateTo.value = toISODate(range.to);
    setActivePeriodPills(page, period);
    form.setAttribute('data-selected-period', period);
    prepareAndSubmit(form);
  }

  function ensurePeriodPillDelegation() {
    if (global.__miPeriodPillsDelegated) return;
    global.__miPeriodPillsDelegated = true;
    document.addEventListener('click', function (e) {
      var pill = e.target && e.target.closest ? e.target.closest('[data-mi-period]') : null;
      if (!pill || !pill.closest('#mi-filter-form')) return;
      e.preventDefault();
      e.stopPropagation();
      applyPeriodPill(pill);
    });
  }

  function markPeriodCustom(form, page) {
    var periodInput = $('#mi-period', form);
    if (periodInput) periodInput.value = 'custom';
    setActivePeriodPills(page, 'custom');
    form.setAttribute('data-selected-period', 'custom');
  }

  function bindDateRange(page) {
    var form = $('#mi-filter-form', page);
    if (!form || form.getAttribute('data-mi-date-bound') === '1') return;
    form.setAttribute('data-mi-date-bound', '1');
    if (!global.SalesDateRangePicker || typeof global.SalesDateRangePicker.init !== 'function') {
      return;
    }

    var dateFrom = $('#mi-date-from', form);
    var dateTo = $('#mi-date-to', form);
    global.SalesDateRangePicker.init({
      wrapId: 'mi-date-range-wrap',
      triggerId: 'mi-date-range-trigger',
      backdropId: 'mi-date-range-backdrop',
      panelId: 'mi-date-range-panel',
      displayId: 'mi-date-range-display',
      formId: 'mi-filter-form',
      fromInputId: 'mi-date-from',
      toInputId: 'mi-date-to',
      applyId: 'mi-date-range-apply',
      prevId: 'mi-cal-prev',
      nextId: 'mi-cal-next',
      title0Id: 'mi-cal-title0',
      title1Id: 'mi-cal-title1',
      grid0Id: 'mi-cal-grid0',
      grid1Id: 'mi-cal-grid1',
      emptyLabel: 'Select date…',
      onBeforeSubmit: function () {
        markPeriodCustom(form, page);
      }
    });

    var todayBtn = $('#mi-date-range-today', page);
    if (todayBtn && todayBtn.getAttribute('data-mi-today-bound') !== '1') {
      todayBtn.setAttribute('data-mi-today-bound', '1');
      todayBtn.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        var wrap = $('#mi-date-range-wrap', page);
        var today = String(
          (wrap && wrap.getAttribute('data-max-date')) || ''
        ).trim();
        if (!today) return;
        if (dateFrom) dateFrom.value = today;
        if (dateTo) dateTo.value = today;
        markPeriodCustom(form, page);
        prepareAndSubmit(form);
      });
    }

    var clearBtn = $('#mi-date-range-clear', page);
    if (clearBtn && clearBtn.getAttribute('data-mi-clear-bound') !== '1') {
      clearBtn.setAttribute('data-mi-clear-bound', '1');
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

  function initManagerInsightReportPage() {
    var page = document.getElementById('manager-insight-report-page');
    if (!page) return;
    formatAmounts(page);
    ensurePeriodPillDelegation();
    bindDateRange(page);
  }

  global.initManagerInsightReportPage = initManagerInsightReportPage;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initManagerInsightReportPage);
  } else {
    initManagerInsightReportPage();
  }
})(typeof window !== 'undefined' ? window : this);
