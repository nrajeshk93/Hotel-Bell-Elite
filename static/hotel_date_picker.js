/**
 * Shared hotel date pill + custom calendar.
 * Markup: .hotel-date[data-hotel-date] with trigger, hidden input, panel.
 */
(function (global) {
  'use strict';

  var MONTH_LONG = [
    'January', 'February', 'March', 'April', 'May', 'June',
    'July', 'August', 'September', 'October', 'November', 'December'
  ];

  function todayISO() {
    var d = new Date();
    var m = String(d.getMonth() + 1).padStart(2, '0');
    var day = String(d.getDate()).padStart(2, '0');
    return d.getFullYear() + '-' + m + '-' + day;
  }

  function parseISODate(iso) {
    var text = String(iso || '').trim();
    if (!/^\d{4}-\d{2}-\d{2}$/.test(text)) return null;
    var y = Number(text.slice(0, 4));
    var m = Number(text.slice(5, 7));
    var d = Number(text.slice(8, 10));
    if (!y || m < 1 || m > 12 || d < 1 || d > 31) return null;
    return { y: y, m: m, d: d, iso: text };
  }

  function toISODate(y, m, d) {
    return (
      y +
      '-' +
      String(m).padStart(2, '0') +
      '-' +
      String(d).padStart(2, '0')
    );
  }

  function formatDateLabel(iso) {
    var parsed = parseISODate(iso);
    if (!parsed) return '';
    return (
      String(parsed.d).padStart(2, '0') +
      '/' +
      String(parsed.m).padStart(2, '0') +
      '/' +
      parsed.y
    );
  }

  function emptyLabelFor(chip) {
    var input = chip && chip.querySelector('.hotel-date-input, input[type="hidden"]');
    var fromData = input && input.getAttribute('data-empty-label');
    return fromData || 'dd/mm/yyyy';
  }

  function syncDisplay(chip) {
    if (!chip) return;
    var input = chip.querySelector('.hotel-date-input, input.hotel-date-input, input[type="hidden"]');
    var valueEl = chip.querySelector('.hotel-date-value');
    if (!input || !valueEl) return;
    var iso = String(input.value || '').trim();
    var label = formatDateLabel(iso);
    if (label) {
      valueEl.textContent = label;
      valueEl.classList.remove('is-placeholder');
    } else {
      valueEl.textContent = emptyLabelFor(chip);
      valueEl.classList.add('is-placeholder');
    }
  }

  function getView(chip) {
    if (!chip.__hotelDateView) {
      chip.__hotelDateView = { year: 0, month: 0, mode: 'days', decadeStart: 0 };
    }
    return chip.__hotelDateView;
  }

  function setViewFromISO(chip, iso) {
    var parsed = parseISODate(iso) || parseISODate(todayISO());
    var view = getView(chip);
    view.year = parsed.y;
    view.month = parsed.m;
    view.mode = 'days';
    view.decadeStart = Math.floor(parsed.y / 12) * 12;
  }

  function setPickerMode(chip, mode) {
    var view = getView(chip);
    view.mode = mode || 'days';
    if (view.mode === 'years' && !view.decadeStart) {
      view.decadeStart = Math.floor(view.year / 12) * 12;
    }
    renderPicker(chip);
  }

  function syncDowVisibility(chip, mode) {
    var dow = chip.querySelector('[data-hotel-date-dow], .hotel-date-dow');
    if (!dow) return;
    var show = mode === 'days';
    dow.hidden = !show;
    if (show) dow.removeAttribute('hidden');
    else dow.setAttribute('hidden', '');
  }

  function renderDays(chip) {
    var title = chip.querySelector('[data-hotel-date-title]');
    var grid = chip.querySelector('[data-hotel-date-grid]');
    var input = chip.querySelector('.hotel-date-input, input[type="hidden"]');
    if (!title || !grid) return;
    var view = getView(chip);
    if (!view.year || !view.month) setViewFromISO(chip, input && input.value);
    title.textContent = MONTH_LONG[view.month - 1] + ' ' + view.year;
    title.setAttribute('aria-label', 'Select year');
    title.title = 'Click to select year';

    var selected = String((input && input.value) || '');
    var today = todayISO();
    var first = new Date(view.year, view.month - 1, 1);
    var startPad = (first.getDay() + 6) % 7;
    var daysInMonth = new Date(view.year, view.month, 0).getDate();
    var prevDays = new Date(view.year, view.month - 1, 0).getDate();
    var html = '';
    var cells = 42;
    for (var i = 0; i < cells; i++) {
      var dayNum;
      var y = view.year;
      var m = view.month;
      var muted = false;
      if (i < startPad) {
        dayNum = prevDays - startPad + i + 1;
        m -= 1;
        if (m < 1) {
          m = 12;
          y -= 1;
        }
        muted = true;
      } else if (i >= startPad + daysInMonth) {
        dayNum = i - (startPad + daysInMonth) + 1;
        m += 1;
        if (m > 12) {
          m = 1;
          y += 1;
        }
        muted = true;
      } else {
        dayNum = i - startPad + 1;
      }
      var iso = toISODate(y, m, dayNum);
      var cls = 'hotel-date-day';
      if (muted) cls += ' is-muted';
      if (iso === selected) cls += ' is-selected';
      if (iso === today) cls += ' is-today';
      html +=
        '<button type="button" class="' +
        cls +
        '" data-date="' +
        iso +
        '" aria-label="' +
        (formatDateLabel(iso) || iso) +
        '"' +
        (iso === selected ? ' aria-current="date"' : '') +
        '>' +
        dayNum +
        '</button>';
    }
    grid.className = 'hotel-date-grid';
    grid.innerHTML = html;
  }

  function renderMonths(chip) {
    var title = chip.querySelector('[data-hotel-date-title]');
    var grid = chip.querySelector('[data-hotel-date-grid]');
    var input = chip.querySelector('.hotel-date-input, input[type="hidden"]');
    if (!title || !grid) return;
    var view = getView(chip);
    var selected = parseISODate(input && input.value);
    title.textContent = String(view.year);
    title.setAttribute('aria-label', 'Select year');
    title.title = 'Click to select year';
    var html = '';
    for (var m = 1; m <= 12; m += 1) {
      var cls = 'hotel-date-period';
      if (selected && selected.y === view.year && selected.m === m) cls += ' is-selected';
      if (!selected && view.month === m) cls += ' is-current';
      html +=
        '<button type="button" class="' +
        cls +
        '" data-month="' +
        m +
        '">' +
        MONTH_LONG[m - 1].slice(0, 3) +
        '</button>';
    }
    grid.className = 'hotel-date-grid hotel-date-grid--months';
    grid.innerHTML = html;
  }

  function renderYears(chip) {
    var title = chip.querySelector('[data-hotel-date-title]');
    var grid = chip.querySelector('[data-hotel-date-grid]');
    var input = chip.querySelector('.hotel-date-input, input[type="hidden"]');
    if (!title || !grid) return;
    var view = getView(chip);
    var selected = parseISODate(input && input.value);
    var thisYear = new Date().getFullYear();
    if (!view.decadeStart) {
      view.decadeStart = Math.floor(view.year / 12) * 12;
    }
    var start = view.decadeStart;
    var end = start + 11;
    title.textContent = start + ' – ' + end;
    title.setAttribute('aria-label', 'Year range');
    title.title = 'Year range';
    var html = '';
    for (var y = start; y <= end; y += 1) {
      var cls = 'hotel-date-period';
      if (selected && selected.y === y) cls += ' is-selected';
      if (y === thisYear) cls += ' is-today';
      if (y === view.year) cls += ' is-current';
      html +=
        '<button type="button" class="' +
        cls +
        '" data-year="' +
        y +
        '">' +
        y +
        '</button>';
    }
    grid.className = 'hotel-date-grid hotel-date-grid--years';
    grid.innerHTML = html;
  }

  function renderPicker(chip) {
    var view = getView(chip);
    var mode = view.mode || 'days';
    var cal = chip.querySelector('.hotel-date-cal');
    if (cal) {
      cal.classList.toggle('is-months', mode === 'months');
      cal.classList.toggle('is-years', mode === 'years');
    }
    syncDowVisibility(chip, mode);
    if (mode === 'years') renderYears(chip);
    else if (mode === 'months') renderMonths(chip);
    else renderDays(chip);
  }

  function renderCalendar(chip) {
    var view = getView(chip);
    view.mode = 'days';
    renderPicker(chip);
  }

  function closeChip(chip) {
    if (!chip) return;
    var panel = chip.querySelector('.hotel-date-panel');
    var backdrop = chip.querySelector('.hotel-date-backdrop');
    var trigger = chip.querySelector('.hotel-date-trigger');
    chip.classList.remove('is-open');
    clearFixedPanel(chip);
    if (panel) {
      panel.hidden = true;
      panel.setAttribute('hidden', '');
    }
    if (backdrop) {
      backdrop.hidden = true;
      backdrop.setAttribute('hidden', '');
    }
    if (trigger) trigger.setAttribute('aria-expanded', 'false');
  }

  function closeAll(except) {
    document.querySelectorAll('.hotel-date.is-open').forEach(function (chip) {
      if (chip !== except) closeChip(chip);
    });
  }

  function positionPanel(chip) {
    chip.classList.remove('panel-align-right');
    var panel = chip.querySelector('.hotel-date-panel');
    var trigger = chip.querySelector('.hotel-date-trigger');
    if (!panel || !trigger) return;

    var useFixed =
      chip.hasAttribute('data-hotel-date-fixed') ||
      !!(chip.closest('.hrd-modal-body, .hrd-modal, .hrd-dialog-body'));

    if (!useFixed) {
      var rect = chip.getBoundingClientRect();
      var width = Math.min(312, window.innerWidth - 24);
      if (rect.left + width > window.innerWidth - 12) {
        chip.classList.add('panel-align-right');
      }
      panel.style.position = '';
      panel.style.top = '';
      panel.style.left = '';
      panel.style.right = '';
      panel.style.width = '';
      return;
    }

    chip.classList.add('is-fixed-panel');
    panel.style.position = 'fixed';
    panel.style.width = Math.min(312, window.innerWidth - 24) + 'px';
    /* Measure after making visible */
    var tRect = trigger.getBoundingClientRect();
    var panelH = panel.offsetHeight || 360;
    var top = tRect.bottom + 8;
    if (top + panelH > window.innerHeight - 12) {
      top = Math.max(12, tRect.top - panelH - 8);
    }
    var left = tRect.left;
    var width = Math.min(312, window.innerWidth - 24);
    if (left + width > window.innerWidth - 12) {
      left = Math.max(12, window.innerWidth - width - 12);
    }
    panel.style.top = Math.round(top) + 'px';
    panel.style.left = Math.round(left) + 'px';
    panel.style.right = 'auto';
  }

  function clearFixedPanel(chip) {
    if (!chip) return;
    chip.classList.remove('is-fixed-panel', 'panel-align-right');
    var panel = chip.querySelector('.hotel-date-panel');
    if (!panel) return;
    panel.style.position = '';
    panel.style.top = '';
    panel.style.left = '';
    panel.style.right = '';
    panel.style.width = '';
  }

  function openChip(chip) {
    if (!chip) return;
    var panel = chip.querySelector('.hotel-date-panel');
    var backdrop = chip.querySelector('.hotel-date-backdrop');
    var trigger = chip.querySelector('.hotel-date-trigger');
    var input = chip.querySelector('.hotel-date-input, input[type="hidden"]');
    if (!panel) return;
    closeAll(chip);
    closeAllTimeChips(null);
    setViewFromISO(chip, input && input.value);
    renderPicker(chip);
    chip.classList.add('is-open');
    panel.hidden = false;
    panel.removeAttribute('hidden');
    if (backdrop) {
      backdrop.hidden = false;
      backdrop.removeAttribute('hidden');
    }
    if (trigger) trigger.setAttribute('aria-expanded', 'true');
    positionPanel(chip);
  }

  function toggleChip(chip) {
    if (!chip) return;
    if (chip.classList.contains('is-open')) closeChip(chip);
    else openChip(chip);
  }

  function setValue(chip, iso, opts) {
    opts = opts || {};
    if (!chip) return;
    var input = chip.querySelector('.hotel-date-input, input[type="hidden"]');
    if (!input) return;
    var next = String(iso || '').trim();
    if (next && !parseISODate(next)) return;
    input.value = next;
    syncDisplay(chip);
    if (opts.close !== false) closeChip(chip);
    if (typeof opts.onChange === 'function') opts.onChange(input.value, chip);
    try {
      input.dispatchEvent(new Event('change', { bubbles: true }));
      input.dispatchEvent(new Event('input', { bubbles: true }));
    } catch (err) {}
  }

  function bindChip(chip) {
    if (!chip || chip.getAttribute('data-hotel-date-bound') === '1') return;
    chip.setAttribute('data-hotel-date-bound', '1');
    syncDisplay(chip);

    var trigger = chip.querySelector('.hotel-date-trigger');
    if (trigger) {
      trigger.addEventListener('click', function (event) {
        event.preventDefault();
        event.stopPropagation();
        toggleChip(chip);
      });
    }

    var prev = chip.querySelector('[data-hotel-date-prev]');
    var next = chip.querySelector('[data-hotel-date-next]');
    var grid = chip.querySelector('[data-hotel-date-grid]');
    var titleBtn = chip.querySelector('[data-hotel-date-title]');
    var todayBtn = chip.querySelector('[data-hotel-date-today]');
    var clearBtn = chip.querySelector('[data-hotel-date-clear]');
    var backdrop = chip.querySelector('.hotel-date-backdrop');

    if (titleBtn) {
      titleBtn.addEventListener('click', function (event) {
        event.preventDefault();
        event.stopPropagation();
        var view = getView(chip);
        if (view.mode === 'years') return;
        view.decadeStart = Math.floor(view.year / 12) * 12;
        setPickerMode(chip, 'years');
      });
    }

    if (prev) {
      prev.addEventListener('click', function (event) {
        event.preventDefault();
        event.stopPropagation();
        var view = getView(chip);
        if (view.mode === 'years') {
          view.decadeStart = (view.decadeStart || Math.floor(view.year / 12) * 12) - 12;
          renderPicker(chip);
          return;
        }
        if (view.mode === 'months') {
          view.year -= 1;
          renderPicker(chip);
          return;
        }
        view.month -= 1;
        if (view.month < 1) {
          view.month = 12;
          view.year -= 1;
        }
        renderPicker(chip);
      });
    }
    if (next) {
      next.addEventListener('click', function (event) {
        event.preventDefault();
        event.stopPropagation();
        var view = getView(chip);
        if (view.mode === 'years') {
          view.decadeStart = (view.decadeStart || Math.floor(view.year / 12) * 12) + 12;
          renderPicker(chip);
          return;
        }
        if (view.mode === 'months') {
          view.year += 1;
          renderPicker(chip);
          return;
        }
        view.month += 1;
        if (view.month > 12) {
          view.month = 1;
          view.year += 1;
        }
        renderPicker(chip);
      });
    }
    if (grid) {
      grid.addEventListener('click', function (event) {
        var yearBtn = event.target.closest('[data-year]');
        if (yearBtn && grid.contains(yearBtn)) {
          event.preventDefault();
          event.stopPropagation();
          var viewY = getView(chip);
          viewY.year = Number(yearBtn.getAttribute('data-year'));
          setPickerMode(chip, 'months');
          return;
        }
        var monthBtn = event.target.closest('[data-month]');
        if (monthBtn && grid.contains(monthBtn)) {
          event.preventDefault();
          event.stopPropagation();
          var viewM = getView(chip);
          viewM.month = Number(monthBtn.getAttribute('data-month'));
          setPickerMode(chip, 'days');
          return;
        }
        var dayBtn = event.target.closest('.hotel-date-day');
        if (!dayBtn || !grid.contains(dayBtn)) return;
        event.preventDefault();
        event.stopPropagation();
        setValue(chip, dayBtn.getAttribute('data-date'));
      });
    }
    if (todayBtn) {
      todayBtn.addEventListener('click', function (event) {
        event.preventDefault();
        event.stopPropagation();
        setValue(chip, todayISO());
      });
    }
    if (clearBtn) {
      clearBtn.addEventListener('click', function (event) {
        event.preventDefault();
        event.stopPropagation();
        setValue(chip, '');
      });
    }
    if (backdrop) {
      backdrop.addEventListener('click', function () {
        closeChip(chip);
      });
    }
  }

  function initHotelDatePickers(scope) {
    var root = scope || document;
    root.querySelectorAll('[data-hotel-date]').forEach(bindChip);
  }

  function syncHotelDateChip(inputOrId) {
    var input =
      typeof inputOrId === 'string' ? document.getElementById(inputOrId) : inputOrId;
    if (!input) return;
    var chip = input.closest('[data-hotel-date]');
    if (chip) syncDisplay(chip);
  }

  function setHotelDateValue(inputOrId, iso) {
    var input =
      typeof inputOrId === 'string' ? document.getElementById(inputOrId) : inputOrId;
    if (!input) return;
    var chip = input.closest('[data-hotel-date]');
    if (chip) setValue(chip, iso, { close: false });
    else {
      input.value = iso || '';
    }
  }

  function closeHotelDatePickers() {
    closeAll(null);
  }

  if (!document.__hotelDatePickerDocBound) {
    document.__hotelDatePickerDocBound = true;
    document.addEventListener('keydown', function (event) {
      if (event.key !== 'Escape') return;
      closeAll(null);
    });
  }

  global.initHotelDatePickers = initHotelDatePickers;
  global.syncHotelDateChip = syncHotelDateChip;
  global.setHotelDateValue = setHotelDateValue;
  global.closeHotelDatePickers = closeHotelDatePickers;
  global.hotelDateTodayISO = todayISO;
  global.formatHotelDateLabel = formatDateLabel;

  /* —— Hotel time pill (12h display, HH:MM 24h value) —— */

  function pad2(n) {
    return String(n).padStart(2, '0');
  }

  function parseTimeValue(text) {
    var raw = String(text || '').trim();
    var m = raw.match(/^(\d{1,2}):(\d{2})$/);
    if (!m) return null;
    var h = Number(m[1]);
    var min = Number(m[2]);
    if (h < 0 || h > 23 || min < 0 || min > 59) return null;
    return { h: h, m: min };
  }

  function toTimeValue(h, min) {
    return pad2(h) + ':' + pad2(min);
  }

  function formatTimeLabel(text) {
    var parsed = parseTimeValue(text);
    if (!parsed) return '';
    var period = parsed.h >= 12 ? 'PM' : 'AM';
    var hour12 = parsed.h % 12;
    if (hour12 === 0) hour12 = 12;
    return pad2(hour12) + ':' + pad2(parsed.m) + ' ' + period;
  }

  function nowTimeValue() {
    var d = new Date();
    return toTimeValue(d.getHours(), d.getMinutes());
  }

  function emptyTimeLabelFor(chip) {
    var input = chip && chip.querySelector('.hotel-time-input, input[type="hidden"]');
    return (input && input.getAttribute('data-empty-label')) || '--:-- --';
  }

  function syncTimeDisplay(chip) {
    if (!chip) return;
    var input = chip.querySelector('.hotel-time-input, input[type="hidden"]');
    var valueEl = chip.querySelector('.hotel-date-value');
    if (!input || !valueEl) return;
    var label = formatTimeLabel(input.value);
    if (label) {
      valueEl.textContent = label;
      valueEl.classList.remove('is-placeholder');
    } else {
      valueEl.textContent = emptyTimeLabelFor(chip);
      valueEl.classList.add('is-placeholder');
    }
  }

  function getTimeDraft(chip) {
    if (!chip.__hotelTimeDraft) {
      chip.__hotelTimeDraft = { hour12: 12, minute: 0, period: 'AM' };
    }
    return chip.__hotelTimeDraft;
  }

  function draftFromValue(chip, value) {
    var parsed = parseTimeValue(value) || parseTimeValue(nowTimeValue());
    var draft = getTimeDraft(chip);
    var period = parsed.h >= 12 ? 'PM' : 'AM';
    var hour12 = parsed.h % 12;
    if (hour12 === 0) hour12 = 12;
    draft.hour12 = hour12;
    draft.minute = parsed.m;
    draft.period = period;
    return draft;
  }

  function draftToValue(draft) {
    var hour12 = Number(draft.hour12) || 12;
    var minute = Number(draft.minute) || 0;
    var period = draft.period === 'PM' ? 'PM' : 'AM';
    var h = hour12 % 12;
    if (period === 'PM') h += 12;
    return toTimeValue(h, minute);
  }

  function minuteOptionsFor(selectedMinute) {
    var opts = [];
    var i;
    for (i = 0; i < 60; i += 5) opts.push(i);
    var sel = Number(selectedMinute);
    if (!isNaN(sel) && sel >= 0 && sel <= 59 && opts.indexOf(sel) === -1) {
      opts.push(sel);
      opts.sort(function (a, b) {
        return a - b;
      });
    }
    return opts;
  }

  function fillTimeColumn(host, values, selected, formatter) {
    if (!host) return;
    host.innerHTML = '';
    values.forEach(function (val) {
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'hotel-time-opt' + (String(val) === String(selected) ? ' is-selected' : '');
      btn.setAttribute('data-value', String(val));
      btn.textContent = formatter ? formatter(val) : String(val);
      host.appendChild(btn);
    });
  }

  function renderTimeWheels(chip) {
    var draft = getTimeDraft(chip);
    var hourHost = chip.querySelector('[data-hotel-time-hour]');
    var minuteHost = chip.querySelector('[data-hotel-time-minute]');
    var periodHost = chip.querySelector('[data-hotel-time-period]');
    var hours = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12];
    fillTimeColumn(hourHost, hours, draft.hour12, function (v) {
      return pad2(v);
    });
    fillTimeColumn(minuteHost, minuteOptionsFor(draft.minute), draft.minute, function (v) {
      return pad2(v);
    });
    fillTimeColumn(periodHost, ['AM', 'PM'], draft.period, null);
    [hourHost, minuteHost, periodHost].forEach(function (host) {
      if (!host) return;
      var selected = host.querySelector('.hotel-time-opt.is-selected');
      if (selected && typeof selected.scrollIntoView === 'function') {
        try {
          selected.scrollIntoView({ block: 'center', inline: 'nearest' });
        } catch (err) {
          selected.scrollIntoView(true);
        }
      }
    });
  }

  function closeTimeChip(chip) {
    if (!chip) return;
    var panel = chip.querySelector('.hotel-time-panel, .hotel-date-panel');
    var backdrop = chip.querySelector('.hotel-time-backdrop, .hotel-date-backdrop');
    var trigger = chip.querySelector('.hotel-date-trigger');
    chip.classList.remove('is-open', 'is-fixed-panel');
    if (panel) {
      panel.hidden = true;
      panel.setAttribute('hidden', '');
      panel.style.position = '';
      panel.style.top = '';
      panel.style.left = '';
      panel.style.right = '';
      panel.style.width = '';
    }
    if (backdrop) {
      backdrop.hidden = true;
      backdrop.setAttribute('hidden', '');
    }
    if (trigger) trigger.setAttribute('aria-expanded', 'false');
  }

  function closeAllTimeChips(except) {
    document.querySelectorAll('[data-hotel-time].is-open').forEach(function (chip) {
      if (chip !== except) closeTimeChip(chip);
    });
  }

  function positionTimePanel(chip) {
    if (!chip) return;
    var panel = chip.querySelector('.hotel-time-panel, .hotel-date-panel');
    var trigger = chip.querySelector('.hotel-date-trigger');
    if (!panel || !trigger) return;
    var inModal = !!chip.closest('#hrd-checkin-modal, #hrd-transfer-modal, #hrd-reserve-modal, .hrd-modal, [role="dialog"]');
    if (!inModal) return;
    chip.classList.add('is-fixed-panel');
    panel.style.position = 'fixed';
    panel.style.width = Math.min(280, window.innerWidth - 24) + 'px';
    var tRect = trigger.getBoundingClientRect();
    var panelH = panel.offsetHeight || 320;
    var top = tRect.bottom + 8;
    if (top + panelH > window.innerHeight - 12) {
      top = Math.max(12, tRect.top - panelH - 8);
    }
    var left = tRect.left;
    var width = Math.min(280, window.innerWidth - 24);
    if (left + width > window.innerWidth - 12) {
      left = Math.max(12, window.innerWidth - width - 12);
    }
    panel.style.top = Math.round(top) + 'px';
    panel.style.left = Math.round(left) + 'px';
    panel.style.right = 'auto';
  }

  function setTimeValue(chip, value, opts) {
    opts = opts || {};
    if (!chip) return;
    var input = chip.querySelector('.hotel-time-input, input[type="hidden"]');
    if (!input) return;
    var next = String(value || '').trim();
    if (next && !parseTimeValue(next)) return;
    input.value = next;
    syncTimeDisplay(chip);
    if (opts.close !== false) closeTimeChip(chip);
    try {
      input.dispatchEvent(new Event('change', { bubbles: true }));
      input.dispatchEvent(new Event('input', { bubbles: true }));
    } catch (err) {}
  }

  function applyDraft(chip, opts) {
    setTimeValue(chip, draftToValue(getTimeDraft(chip)), opts || { close: false });
  }

  function openTimeChip(chip) {
    if (!chip) return;
    var panel = chip.querySelector('.hotel-time-panel, .hotel-date-panel');
    var backdrop = chip.querySelector('.hotel-time-backdrop, .hotel-date-backdrop');
    var trigger = chip.querySelector('.hotel-date-trigger');
    var input = chip.querySelector('.hotel-time-input, input[type="hidden"]');
    if (!panel) return;
    closeAll(null);
    closeAllTimeChips(chip);
    draftFromValue(chip, input && input.value);
    renderTimeWheels(chip);
    chip.classList.add('is-open');
    panel.hidden = false;
    panel.removeAttribute('hidden');
    if (backdrop) {
      backdrop.hidden = false;
      backdrop.removeAttribute('hidden');
    }
    if (trigger) trigger.setAttribute('aria-expanded', 'true');
    positionTimePanel(chip);
  }

  function toggleTimeChip(chip) {
    if (!chip || chip.classList.contains('is-disabled')) return;
    var trigger = chip.querySelector('.hotel-date-trigger');
    if (trigger && trigger.disabled) return;
    if (chip.classList.contains('is-open')) closeTimeChip(chip);
    else openTimeChip(chip);
  }

  function bindTimeChip(chip) {
    if (!chip || chip.getAttribute('data-hotel-time-bound') === '1') return;
    chip.setAttribute('data-hotel-time-bound', '1');
    syncTimeDisplay(chip);

    var trigger = chip.querySelector('.hotel-date-trigger');
    if (trigger) {
      trigger.addEventListener('click', function (event) {
        event.preventDefault();
        event.stopPropagation();
        toggleTimeChip(chip);
      });
    }

    var hourHost = chip.querySelector('[data-hotel-time-hour]');
    var minuteHost = chip.querySelector('[data-hotel-time-minute]');
    var periodHost = chip.querySelector('[data-hotel-time-period]');
    var nowBtn = chip.querySelector('[data-hotel-time-now]');
    var clearBtn = chip.querySelector('[data-hotel-time-clear]');
    var backdrop = chip.querySelector('.hotel-time-backdrop, .hotel-date-backdrop');

    function onColClick(host, key, transform) {
      if (!host) return;
      host.addEventListener('click', function (event) {
        var opt = event.target.closest('.hotel-time-opt');
        if (!opt || !host.contains(opt)) return;
        event.preventDefault();
        event.stopPropagation();
        var draft = getTimeDraft(chip);
        draft[key] = transform ? transform(opt.getAttribute('data-value')) : opt.getAttribute('data-value');
        renderTimeWheels(chip);
        applyDraft(chip, { close: false });
      });
    }

    onColClick(hourHost, 'hour12', function (v) {
      return Number(v);
    });
    onColClick(minuteHost, 'minute', function (v) {
      return Number(v);
    });
    onColClick(periodHost, 'period', function (v) {
      return v === 'PM' ? 'PM' : 'AM';
    });

    if (nowBtn) {
      nowBtn.addEventListener('click', function (event) {
        event.preventDefault();
        event.stopPropagation();
        setTimeValue(chip, nowTimeValue(), { close: true });
      });
    }
    if (clearBtn) {
      clearBtn.addEventListener('click', function (event) {
        event.preventDefault();
        event.stopPropagation();
        setTimeValue(chip, '', { close: true });
      });
    }
    if (backdrop) {
      backdrop.addEventListener('click', function (event) {
        event.preventDefault();
        event.stopPropagation();
        closeTimeChip(chip);
      });
    }
  }

  function initHotelTimePickers(scope) {
    var root = scope || document;
    root.querySelectorAll('[data-hotel-time]').forEach(function (chip) {
      if (chip.getAttribute('data-hotel-time-bound') === '1') {
        syncTimeDisplay(chip);
        return;
      }
      bindTimeChip(chip);
    });
  }

  function setHotelTimeValue(inputOrId, value) {
    var input =
      typeof inputOrId === 'string' ? document.getElementById(inputOrId) : inputOrId;
    if (!input) return;
    var chip = input.closest('[data-hotel-time]');
    if (chip) setTimeValue(chip, value, { close: false });
    else input.value = value || '';
  }

  function closeHotelTimePickers() {
    closeAllTimeChips(null);
  }

  if (!document.__hotelTimePickerDocBound) {
    document.__hotelTimePickerDocBound = true;
    document.addEventListener('keydown', function (event) {
      if (event.key !== 'Escape') return;
      closeAllTimeChips(null);
    });
  }

  global.initHotelTimePickers = initHotelTimePickers;
  global.setHotelTimeValue = setHotelTimeValue;
  global.closeHotelTimePickers = closeHotelTimePickers;
  global.formatHotelTimeLabel = formatTimeLabel;
})(window);
