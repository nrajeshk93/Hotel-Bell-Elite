/**
 * Indian numbering (lakhs/crores) for currency display across the app.
 * Inputs should use formatAmountRaw() — no grouping commas.
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

  function formatAmountRaw(value) {
    const amount = Number(value || 0);
    return Number.isInteger(amount) ? String(amount) : amount.toFixed(2);
  }

  global.formatIndianGroupedInteger = formatIndianGroupedInteger;
  global.formatNum = formatNum;
  global.formatInr = formatInr;
  global.fmtInr = formatInr;
  global.formatAmountRaw = formatAmountRaw;
})(typeof window !== 'undefined' ? window : globalThis);
