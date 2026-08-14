/**
 * Invoice Ledger date/time display: 31 July 26 or 31 July 26 15:49.
 */
(function (global) {
  'use strict';

  var MONTHS = [
    'January',
    'February',
    'March',
    'April',
    'May',
    'June',
    'July',
    'August',
    'September',
    'October',
    'November',
    'December',
  ];

  function parseReportDatetime(value) {
    if (value == null) return null;
    var text = String(value).trim();
    if (!text || text === '—' || text === '-' || text === 'never') return null;
    text = text.replace('T', ' ');
    var datePart = text.slice(0, 10);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(datePart)) return null;
    var year = Number(datePart.slice(0, 4));
    var month = Number(datePart.slice(5, 7));
    var day = Number(datePart.slice(8, 10));
    if (!year || month < 1 || month > 12 || day < 1) return null;
    var hasTime = text.length > 10;
    var hour = 0;
    var minute = 0;
    if (hasTime) {
      var timePart = text.slice(11, 16);
      if (!/^\d{2}:\d{2}$/.test(timePart)) return { day: day, month: month, year: year, hasTime: false };
      hour = Number(timePart.slice(0, 2));
      minute = Number(timePart.slice(3, 5));
    }
    return {
      day: day,
      month: month,
      year: year,
      hour: hour,
      minute: minute,
      hasTime: hasTime,
    };
  }

  function formatReportDate(value, empty) {
    var parsed = parseReportDatetime(value);
    if (!parsed) {
      var text = value == null ? '' : String(value).trim();
      return text || (empty == null ? '—' : empty);
    }
    return parsed.day + ' ' + MONTHS[parsed.month - 1] + ' ' + String(parsed.year).slice(-2);
  }

  function formatReportTime(value, empty) {
    var parsed = parseReportDatetime(value);
    if (!parsed || !parsed.hasTime) return empty == null ? '' : empty;
    var hour = parsed.hour < 10 ? '0' + parsed.hour : String(parsed.hour);
    var minute = parsed.minute < 10 ? '0' + parsed.minute : String(parsed.minute);
    return hour + ':' + minute;
  }

  function formatReportDatetime(value, empty) {
    var parsed = parseReportDatetime(value);
    if (!parsed) {
      var text = value == null ? '' : String(value).trim();
      return text || (empty == null ? '—' : empty);
    }
    var label = formatReportDate(value, empty);
    if (parsed.hasTime) return label + ' ' + formatReportTime(value);
    return label;
  }

  global.formatReportDate = formatReportDate;
  global.formatReportTime = formatReportTime;
  global.formatReportDatetime = formatReportDatetime;
})(typeof window !== 'undefined' ? window : this);
