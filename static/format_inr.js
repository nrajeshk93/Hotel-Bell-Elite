/**
 * Indian numbering (lakhs/crores) for currency display across the app.
 * Inputs should use formatAmountRaw() — no grouping commas.
 * KPI cards always show whole rupees (no decimals).
 */
(function (global) {
  'use strict';

  function formatIndianGroupedInteger(absInt) {
    const digits = String(Math.abs(Math.round(absInt)));
    if (digits.length <= 3) return digits;
    const last3 = digits.slice(-3);
    let rest = digits.slice(0, -3);
    const groups = [];
    while (rest.length > 2) {
      groups.unshift(rest.slice(-2));
      rest = rest.slice(0, -2);
    }
    if (rest) groups.unshift(rest);
    return groups.join(',') + ',' + last3;
  }

  function formatNum(value, dec) {
    const places = dec === undefined ? 0 : dec;
    const n = Number(value || 0);
    const neg = n < 0;
    const abs = Math.abs(n);
    if (places <= 0) {
      return (neg ? '−' : '') + formatIndianGroupedInteger(abs);
    }
    const fixed = abs.toFixed(places);
    const parts = fixed.split('.');
    return (neg ? '−' : '') + formatIndianGroupedInteger(parts[0]) + '.' + parts[1];
  }

  function formatInr(value, dec) {
    const places = dec === undefined ? 0 : dec;
    const n = Number(value || 0);
    const neg = n < 0;
    return (neg ? '−' : '') + '₹' + formatNum(Math.abs(n), places);
  }

  /** KPI / summary card amounts — always whole rupees. */
  function formatKpiInr(value) {
    return formatInr(value, 0);
  }

  function formatAmountRaw(value) {
    const amount = Number(value || 0);
    return Number.isInteger(amount) ? String(amount) : amount.toFixed(2);
  }

  function isKpiAmountNode(el) {
    return !!(
      el &&
      el.classList &&
      (el.classList.contains('pl-summary-value') ||
        el.classList.contains('kpi-val') ||
        el.classList.contains('hbe-kpi-value') ||
        el.classList.contains('sr-kpi-value') ||
        el.classList.contains('md-kpi-value') ||
        el.classList.contains('rdx-kpi-value') ||
        el.classList.contains('pos-kpi-value') ||
        el.classList.contains('tips-payout-metric-value') ||
        el.classList.contains('hotel-kpi-value') ||
        el.classList.contains('st-stock-kpi-value') ||
        el.hasAttribute('data-kpi-value'))
    );
  }

  /** Format a money node: KPI cards → 0 decimals; table cells → 2. */
  function formatAmountNode(el, amount) {
    if (!el) return '';
    const raw = amount != null ? amount : el.getAttribute('data-amount');
    const places = isKpiAmountNode(el) ? 0 : 2;
    const text = formatInr(raw, places);
    el.textContent = text;
    return text;
  }

  const KPI_VALUE_SELECTOR = [
    '.kpi-val:not(.kpi-val--action)',
    '.pl-summary-value',
    '.hbe-kpi-value',
    '.sr-kpi-value',
    '.md-kpi-value',
    '.rdx-kpi-value',
    '.pos-kpi-value',
    '.tips-payout-metric-value',
  ].join(',');

  function fitKpiValues(root) {
    const scope = root && root.querySelectorAll ? root : document;
    scope.querySelectorAll(KPI_VALUE_SELECTOR).forEach(function (el) {
      el.style.fontSize = '';
      el.style.whiteSpace = 'nowrap';
      const computed = window.getComputedStyle(el);
      let size = parseFloat(computed.fontSize) || 28;
      const min = 11;
      const available = Math.max(0, el.clientWidth || el.parentElement?.clientWidth || 0);

      function contentWidth() {
        try {
          const range = document.createRange();
          range.selectNodeContents(el);
          const width = range.getBoundingClientRect().width;
          range.detach();
          return width;
        } catch (e) {
          return el.scrollWidth;
        }
      }

      // Shrink until the amount fits the available width (Range avoids overflow:hidden false fits).
      while (size > min && available > 0 && contentWidth() > available + 1) {
        size -= 1;
        el.style.fontSize = size + 'px';
      }
      if (available > 0 && contentWidth() > available + 1) {
        el.style.whiteSpace = 'normal';
      }
    });
  }

  let fitTimer = null;
  function scheduleFitKpiValues(root) {
    if (fitTimer) window.clearTimeout(fitTimer);
    fitTimer = window.setTimeout(function () {
      fitTimer = null;
      fitKpiValues(root && root.querySelectorAll ? root : document);
    }, 50);
  }

  if (typeof document !== 'undefined') {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', scheduleFitKpiValues);
    } else {
      scheduleFitKpiValues();
    }
    window.addEventListener('resize', scheduleFitKpiValues);
  }

  global.formatIndianGroupedInteger = formatIndianGroupedInteger;
  global.formatNum = formatNum;
  global.formatInr = formatInr;
  global.fmtInr = formatInr;
  global.formatKpiInr = formatKpiInr;
  global.formatAmountRaw = formatAmountRaw;
  global.isKpiAmountNode = isKpiAmountNode;
  global.formatAmountNode = formatAmountNode;
  global.fitKpiValues = fitKpiValues;
  global.scheduleFitKpiValues = scheduleFitKpiValues;
})(typeof window !== 'undefined' ? window : globalThis);
