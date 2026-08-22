/**
 * Hotel → Reservations manager (Asia Tech).
 * Soft-nav safe: expose window.initHotelReservationsPage.
 */
(function (global) {
  'use strict';

  var state = {
    page: 1,
    pageSize: 'all',
    selectedId: '',
    selectedRoomIds: [],
    rows: [],
    vacantRooms: [],
    pagination: null,
    loadGen: 0,
    bound: false,
    autoRefreshTimer: null,
    syncBannerTimer: null,
    sortKey: '',
    sortAsc: true,
    kpiFilter: 'total',
    checkoutOnly: false,
    editBaseline: ''
  };

  var KPI_FILTERS = {
    total: { status: 'all', label: 'All Statuses', checkoutOnly: false },
    revenue: { status: 'all', label: 'All Statuses', checkoutOnly: false },
    checked_in: { status: 'checked_in', label: 'Checked In', checkoutOnly: false },
    upcoming: { status: 'upcoming', label: 'Upcoming', checkoutOnly: false },
    checked_out: { status: 'checked_out', label: 'Checked Out', checkoutOnly: true }
  };

  var AUTO_REFRESH_MS = 30 * 60 * 1000;
  var SYNC_BANNER_MS = 10 * 1000;

  function stopAutoRefresh() {
    if (state.autoRefreshTimer) {
      clearInterval(state.autoRefreshTimer);
      state.autoRefreshTimer = null;
    }
  }

  function startAutoRefresh() {
    stopAutoRefresh();
    state.autoRefreshTimer = setInterval(function () {
      if (!pageRoot()) {
        stopAutoRefresh();
        return;
      }
      // Bypass 60s server cache so Asia Tech data stays fresh.
      loadReservations({ silent: true, refresh: true });
    }, AUTO_REFRESH_MS);
  }

  function $(sel, root) {
    return (root || document).querySelector(sel);
  }

  function pageRoot() {
    return document.getElementById('hotel-reservations-page');
  }

  function apiBase(root) {
    return (
      (root && root.getAttribute('data-reservations-api')) ||
      '/hotel/api/reservations'
    );
  }

  function escapeHtml(text) {
    return String(text == null ? '' : text)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function escapeAttr(text) {
    return escapeHtml(text).replace(/'/g, '&#39;');
  }

  function formatInr(amount) {
    var n = Number(amount) || 0;
    try {
      return (
        '₹\u00a0' +
        n.toLocaleString('en-IN', {
          maximumFractionDigits: 0
        })
      );
    } catch (e) {
      return '₹\u00a0' + String(Math.round(n));
    }
  }

  function formatDisplayDate(iso) {
    var s = String(iso || '').slice(0, 10);
    var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s);
    if (!m) return s || '—';
    return m[3] + '/' + m[2] + '/' + m[1];
  }

  function formatTime(t) {
    var raw = String(t || '').trim();
    if (!raw) return '';
    var m = /^(\d{1,2}):(\d{2})/.exec(raw);
    if (!m) return raw;
    var h = parseInt(m[1], 10);
    var min = m[2];
    var ampm = h >= 12 ? 'PM' : 'AM';
    var h12 = h % 12 || 12;
    return h12 + ':' + min + ' ' + ampm;
  }

  function showToast(message) {
    var el = document.getElementById('hres-toast');
    if (!el) return;
    el.textContent = message;
    el.hidden = false;
    clearTimeout(showToast._timer);
    showToast._timer = setTimeout(function () {
      el.hidden = true;
    }, 2600);
  }

  function filterValue(id) {
    var el = document.getElementById(id);
    return el ? String(el.value || '').trim() : '';
  }

  var MEAL_PLAN_CODES = ['EP', 'CP', 'MAP', 'AP', 'AI', 'BB'];
  var MEAL_PLAN_LABELS = {
    EP: 'EP · Room only',
    CP: 'CP · Breakfast',
    MAP: 'MAP · Breakfast & dinner',
    AP: 'AP · All meals',
    AI: 'AI · All inclusive',
    BB: 'BB · Bed & breakfast'
  };

  function mealPlanCodeFromStored(value) {
    var text = String(value || '').trim();
    if (!text || text.indexOf(',') >= 0) return '';
    var first = text.split('·')[0].trim().toUpperCase();
    for (var i = 0; i < MEAL_PLAN_CODES.length; i++) {
      if (first === MEAL_PLAN_CODES[i]) return MEAL_PLAN_CODES[i];
    }
    return '';
  }

  function splitGuestTitleName(full) {
    var text = String(full || '').trim().replace(/\s+/g, ' ');
    if (!text) return { title: '', name: '' };
    var m = /^(Mr|Mrs|Ms|Miss|Dr|Mx)\.?\s+(.+)$/i.exec(text);
    if (!m) return { title: '', name: text };
    var key = String(m[1] || '').toLowerCase();
    var titleMap = {
      mr: 'Mr',
      mrs: 'Mrs',
      ms: 'Ms',
      miss: 'Ms',
      dr: 'Dr',
      mx: 'Mx'
    };
    return {
      title: titleMap[key] || '',
      name: String(m[2] || '').trim()
    };
  }

  function joinGuestTitleName(title, name) {
    var guest = String(name || '').trim().replace(/\s+/g, ' ');
    var honorific = String(title || '').trim();
    if (!honorific) return guest;
    if (!guest) return honorific;
    return honorific + '. ' + guest;
  }

  function fillGuestTitleSelect(title) {
    var value = String(title || '').trim();
    var label = value || 'Select';
    if (typeof window.resetEpListbox === 'function') {
      window.resetEpListbox('hres-edit-guest-title', value, label);
      return;
    }
    var hidden = document.getElementById('hres-edit-guest-title');
    if (hidden) hidden.value = value;
  }

  var STATUS_EDIT_LABELS = {
    upcoming: 'Upcoming',
    checked_in: 'Checked In',
    checked_out: 'Checked Out',
    cancelled: 'Cancelled'
  };

  function fillEditListbox(fieldId, value, labels, emptyLabel) {
    var key = String(value || '').trim();
    var label = (key && labels[key]) || emptyLabel || 'Select';
    if (!key) key = '';
    if (typeof window.resetEpListbox === 'function') {
      window.resetEpListbox(fieldId, key, label);
      return;
    }
    var hidden = document.getElementById(fieldId);
    if (hidden) hidden.value = key;
  }

  function fillMealPlanSelect(stored) {
    var root = document.getElementById('hres-edit-meal-listbox');
    var wrap =
      (root && (root.querySelector('.ep-listbox-options') || root.querySelector('.se-filter-listbox'))) ||
      null;
    if (wrap) {
      var extras = wrap.querySelectorAll('.se-filter-listbox-option[data-custom="1"]');
      for (var i = 0; i < extras.length; i++) extras[i].remove();
    }
    var text = String(stored || '').trim();
    if (!text) {
      if (typeof window.resetEpListbox === 'function') {
        window.resetEpListbox('hres-edit-meal', '', 'Select meal plan');
      } else {
        var empty = document.getElementById('hres-edit-meal');
        if (empty) empty.value = '';
      }
      return;
    }
    var code = mealPlanCodeFromStored(text);
    var value = code || text;
    var label = (code && MEAL_PLAN_LABELS[code]) || text;
    if (!code && wrap) {
      var opt = document.createElement('button');
      opt.type = 'button';
      opt.className = 'se-filter-listbox-option';
      opt.setAttribute('role', 'option');
      opt.setAttribute('data-value', text);
      opt.setAttribute('data-label', text);
      opt.setAttribute('data-name', text.toLowerCase());
      opt.setAttribute('data-custom', '1');
      opt.setAttribute('aria-selected', 'false');
      opt.textContent = text;
      wrap.appendChild(opt);
    }
    if (typeof window.resetEpListbox === 'function') {
      window.resetEpListbox('hres-edit-meal', value, label);
    } else {
      var hidden = document.getElementById('hres-edit-meal');
      if (hidden) hidden.value = value;
    }
  }

  function dateFilterRange(root) {
    root = root || pageRoot();
    var fromEl =
      (root && root.querySelector('#hres-date-from')) ||
      document.getElementById('hres-date-from');
    var toEl =
      (root && root.querySelector('#hres-date-to')) ||
      document.getElementById('hres-date-to');
    var from = fromEl ? String(fromEl.value || '').trim().slice(0, 10) : '';
    var to = toEl ? String(toEl.value || '').trim().slice(0, 10) : '';
    if (from && !to) to = from;
    if (to && !from) from = to;
    return { from: from, to: to };
  }

  function setDateRangeFilteredClass() {
    var host = document.querySelector('#hres-date-range-host .se-filter-chip--date-range');
    if (!host) return;
    var range = dateFilterRange();
    host.classList.toggle('is-filtered', !!(range.from && range.to));
  }

  function paintKpis(kpis) {
    kpis = kpis || {};
    var map = {
      total: String(kpis.total != null ? kpis.total : 0),
      checked_in: String(kpis.checked_in != null ? kpis.checked_in : 0),
      upcoming: String(kpis.upcoming != null ? kpis.upcoming : 0),
      checked_out: String(kpis.checked_out != null ? kpis.checked_out : 0),
      revenue: formatInr(kpis.revenue)
    };
    Object.keys(map).forEach(function (key) {
      var card = document.querySelector('.hres-kpi[data-kpi="' + key + '"]');
      if (!card) return;
      var val = card.querySelector('[data-kpi-value]');
      if (val) val.textContent = map[key];
      var meta = card.querySelector('[data-kpi-meta]');
      if (!meta) return;
      if (key === 'revenue' || key === 'total') {
        meta.textContent = 'selected date';
        return;
      }
      var n = parseInt(map[key], 10);
      if (isNaN(n)) n = 0;
      meta.textContent = n + (n === 1 ? ' room' : ' rooms');
    });
  }

  function paintKpiActive() {
    var root = pageRoot();
    var cards = (root || document).querySelectorAll('.hres-kpi[data-kpi]');
    cards.forEach(function (card) {
      var on = card.getAttribute('data-kpi') === state.kpiFilter;
      card.classList.toggle('is-active', on);
      card.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
  }

  function setStatusFilter(value, label) {
    var root = pageRoot();
    var hidden =
      (root && root.querySelector('#hres-status-filter')) ||
      document.getElementById('hres-status-filter');
    var display =
      (root && root.querySelector('#hres-status-value')) ||
      document.getElementById('hres-status-value');
    var list =
      (root && root.querySelector('#hres-status-list')) ||
      document.getElementById('hres-status-list');
    if (hidden) hidden.value = value;
    if (display) display.textContent = label || value;
    if (list) {
      list.querySelectorAll('.se-filter-listbox-option').forEach(function (opt) {
        var on = opt.getAttribute('data-value') === value;
        opt.classList.toggle('is-selected', on);
        opt.setAttribute('aria-selected', on ? 'true' : 'false');
      });
    }
  }

  function applyKpiFilter(key) {
    var want = String(key || 'total');
    if (!KPI_FILTERS[want]) want = 'total';
    if (
      state.kpiFilter === want &&
      want !== 'total' &&
      want !== 'revenue'
    ) {
      want = 'total';
    }
    var spec = KPI_FILTERS[want];
    state.kpiFilter = want;
    state.checkoutOnly = !!(spec && spec.checkoutOnly);
    setStatusFilter(spec.status, spec.label);
    paintKpiActive();
    loadReservations();
  }

  function syncKpiFromStatusFilter() {
    var status = filterValue('hres-status-filter') || 'all';
    state.checkoutOnly = false;
    if (status === 'all') state.kpiFilter = 'total';
    else if (KPI_FILTERS[status]) state.kpiFilter = status;
    else state.kpiFilter = '';
    paintKpiActive();
  }

  function formatSyncStamp(iso) {
    var raw = String(iso || '').trim();
    if (!raw) return '';
    var d = new Date(raw.indexOf('T') >= 0 ? raw : raw.replace(' ', 'T'));
    if (isNaN(d.getTime())) return raw;
    function pad(n) {
      return String(n).padStart(2, '0');
    }
    return (
      pad(d.getDate()) +
      '/' +
      pad(d.getMonth() + 1) +
      '/' +
      d.getFullYear() +
      ' ' +
      pad(d.getHours()) +
      ':' +
      pad(d.getMinutes()) +
      ':' +
      pad(d.getSeconds())
    );
  }

  function clearSyncBannerTimer() {
    if (state.syncBannerTimer) {
      clearTimeout(state.syncBannerTimer);
      state.syncBannerTimer = null;
    }
  }

  function hideSyncBanner() {
    var banner = document.getElementById('hres-sync-banner');
    var text = document.getElementById('hres-sync-banner-text');
    clearSyncBannerTimer();
    if (banner) {
      banner.setAttribute('hidden', 'hidden');
      banner.hidden = true;
      banner.classList.remove('is-error', 'is-ok', 'is-visible');
    }
    if (text) text.textContent = '';
  }

  function scheduleSyncBannerHide() {
    clearSyncBannerTimer();
    state.syncBannerTimer = setTimeout(function () {
      state.syncBannerTimer = null;
      hideSyncBanner();
    }, SYNC_BANNER_MS);
  }

  function paintSyncBanner(sync, mode, opts) {
    var banner = document.getElementById('hres-sync-banner');
    var text = document.getElementById('hres-sync-banner-text');
    if (!banner || !text) return;
    sync = sync || {};
    opts = opts || {};
    var error = String(sync.error || '').trim();
    var syncedAt = formatSyncStamp(sync.synced_at);
    var source = String(sync.source || mode || '').toLowerCase();
    if (error) {
      banner.hidden = false;
      banner.removeAttribute('hidden');
      banner.classList.remove('is-ok');
      banner.classList.add('is-error', 'is-visible');
      text.textContent = error;
      scheduleSyncBannerHide();
      return;
    }
    if (!opts.refresh) {
      return;
    }
    if (source === 'asia_tech' && syncedAt) {
      banner.hidden = false;
      banner.removeAttribute('hidden');
      banner.classList.remove('is-error');
      banner.classList.add('is-ok', 'is-visible');
      text.textContent = 'Synced from Asia Tech · ' + syncedAt;
      scheduleSyncBannerHide();
      return;
    }
    if (source === 'asia_tech') {
      banner.hidden = false;
      banner.removeAttribute('hidden');
      banner.classList.remove('is-error');
      banner.classList.add('is-ok', 'is-visible');
      text.textContent = 'Synced from Asia Tech';
      scheduleSyncBannerHide();
      return;
    }
    hideSyncBanner();
  }

  function statusClass(status) {
    return 'is-' + String(status || 'upcoming').replace(/\s+/g, '_');
  }

  function reservationStatusKey(row) {
    return String((row && row.status) || '')
      .trim()
      .toLowerCase()
      .replace(/\s+/g, '_');
  }

  function canAssignReservation(row) {
    if (!row) return false;
    var status = reservationStatusKey(row);
    return status !== 'cancelled' && status !== 'checked_out';
  }

  function reservationIsAssigned(row) {
    if (!row) return false;
    if (reservationStatusKey(row) === 'checked_in') return true;
    if (row.roomAssigned) return true;
    if (row.roomNumber) return true;
    if (Array.isArray(row.roomNumbers) && row.roomNumbers.length) return true;
    if (Array.isArray(row.roomIds) && row.roomIds.length) return true;
    if (row.roomId) return true;
    return false;
  }

  function reservationAssignmentBucket(row) {
    var assigned = assignedRoomCount(row);
    var total = reservationTotalRooms(row);
    var status = reservationStatusKey(row);
    // In-house guests always belong under Room assigned / partial — never Needs room.
    if (status === 'checked_in' && assigned <= 0) return 'assigned';
    if (assigned <= 0) return 'unassigned';
    if (assigned < total) return 'partial';
    return 'assigned';
  }

  function reservationRoomLabel(row) {
    var numbers = [];
    var seen = {};
    function pushNum(value) {
      var text = String(value || '').trim();
      if (!text || seen[text]) return;
      seen[text] = true;
      numbers.push(text);
    }
    if (Array.isArray(row && row.roomNumbers)) {
      row.roomNumbers.forEach(pushNum);
    }
    pushNum(row && row.roomNumber);
    numbers.sort(function (a, b) {
      var na = parseInt(a, 10);
      var nb = parseInt(b, 10);
      if (isFinite(na) && isFinite(nb) && String(na) === a && String(nb) === b) {
        return na - nb;
      }
      return String(a).localeCompare(String(b), undefined, {
        numeric: true,
        sensitivity: 'base'
      });
    });
    var typeLabel = String((row && (row.roomTypeLabel || row.roomType)) || '').trim();
    var total = reservationTotalRooms(row);
    var assigned = numbers.length || assignedRoomCount(row);
    var prefix = '';
    if (assigned > 0 && assigned < total) {
      prefix = assigned + ' of ' + total + ' rooms · ';
    }
    if (numbers.length) {
      var roomsText =
        numbers.length === 1
          ? 'Room ' + numbers[0]
          : numbers.length + ' rooms · ' + numbers.join(', ');
      return prefix + roomsText + (typeLabel ? ' · ' + typeLabel : '');
    }
    if (typeLabel) return prefix + typeLabel;
    if (prefix) return prefix.replace(/\s·\s$/, '');
    return reservationIsAssigned(row) ? 'Room assigned' : '';
  }

  function guestMetaLabel(row) {
    var bucket = reservationAssignmentBucket(row);
    if (bucket === 'assigned' || bucket === 'partial') {
      return (
        reservationRoomLabel(row) ||
        (bucket === 'partial'
          ? 'Partially assigned'
          : reservationStatusKey(row) === 'checked_in'
            ? 'Checked in'
            : 'Room assigned')
      );
    }
    var mobile = String((row && row.mobile) || '').trim();
    var email = String((row && row.email) || '').trim();
    if (/^n\/?a$/i.test(mobile)) mobile = '';
    if (/^n\/?a$/i.test(email)) email = '';
    if (mobile && email) return mobile + ' · ' + email;
    if (mobile) return mobile;
    if (email) return email;
    return 'Unassigned';
  }

  function renderRowHtml(row) {
    var selected =
      state.selectedId && state.selectedId === row.id ? ' is-selected' : '';
    var statusKey = reservationStatusKey(row);
    var cancelled = statusKey === 'cancelled';
    var bucket = reservationAssignmentBucket(row);
    var meta = guestMetaLabel(row);
    var metaClass =
      bucket === 'assigned'
        ? ' is-assigned'
        : bucket === 'partial'
          ? ' is-partial'
          : ' is-unassigned';
    var rowClass =
      bucket === 'assigned'
        ? ' is-assigned'
        : bucket === 'partial'
          ? ' is-partial'
          : ' is-unassigned';
    return (
      '<tr data-res-id="' +
      escapeAttr(row.id) +
      '" data-status="' +
      escapeAttr(statusKey || 'upcoming') +
      '" data-assigned="' +
      escapeAttr(bucket) +
      '" data-sort-row class="' +
      (selected.trim() + (cancelled ? ' is-cancelled' : '') + rowClass).trim() +
      '">' +
      '<td data-sort-value="' +
      escapeAttr(String(row.guestName || '').toLowerCase()) +
      '"><div class="hres-guest">' +
      '<div class="hres-avatar">' +
      escapeHtml(row.initials || '?') +
      '</div>' +
      '<div class="hres-guest-copy">' +
      '<div class="hres-guest-name">' +
      escapeHtml(row.guestName || 'Guest') +
      '</div>' +
      '<div class="hres-guest-id">#' +
      escapeHtml(row.bookingId || row.id) +
      '</div>' +
      '<div class="hres-guest-meta' +
      metaClass +
      '" title="' +
      escapeAttr(meta) +
      '">' +
      escapeHtml(meta) +
      '</div></div></div></td>' +
      '<td data-sort-value="' +
      escapeAttr(String(reservationTotalRooms(row))) +
      '"><div class="hres-rooms"><strong>' +
      escapeHtml(String(reservationTotalRooms(row))) +
      '</strong></div></td>' +
      '<td data-sort-value="' +
      escapeAttr(String(row.checkInDate || '') + ' ' + String(row.checkInTime || '')) +
      '"><div class="hres-datetime"><strong>' +
      escapeHtml(formatDisplayDate(row.checkInDate)) +
      '</strong><span>' +
      escapeHtml(formatTime(row.checkInTime)) +
      '</span></div></td>' +
      '<td data-sort-value="' +
      escapeAttr(String(row.checkOutDate || '') + ' ' + String(row.checkOutTime || '')) +
      '"><div class="hres-datetime"><strong>' +
      escapeHtml(formatDisplayDate(row.checkOutDate)) +
      '</strong><span>' +
      escapeHtml(formatTime(row.checkOutTime)) +
      '</span></div></td>' +
      '<td data-sort-value="' +
      escapeAttr(String(row.amount == null ? 0 : row.amount)) +
      '"><div class="hres-price"><strong>' +
      escapeHtml(formatInr(row.amount)) +
      '</strong><span>' +
      escapeHtml(String(row.nights || 1)) +
      ' Night' +
      (Number(row.nights) === 1 ? '' : 's') +
      '</span></div></td>' +
      '<td data-sort-value="' +
      escapeAttr(String(row.statusLabel || row.status || '').toLowerCase()) +
      '"><span class="hres-status-pill ' +
      statusClass(row.status) +
      '"' +
      (cancelled ? ' aria-disabled="true"' : '') +
      '>' +
      escapeHtml(row.statusLabel || row.status) +
      '</span></td>' +
      '<td><div class="hres-row-actions">' +
      '<button type="button" class="hres-icon-btn" data-hres-view title="View">' +
      '<svg viewBox="0 0 24 24"><path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7S1 12 1 12z"/><circle cx="12" cy="12" r="3"/></svg>' +
      '</button>' +
      '</div></td></tr>'
    );
  }

  function renderGroupHeader(label, count, groupKey) {
    return (
      '<tr class="hres-group-row" data-hres-group="' +
      escapeAttr(groupKey) +
      '" aria-hidden="false">' +
      '<td colspan="7"><div class="hres-group-label">' +
      escapeHtml(label) +
      '<span class="hres-group-count">' +
      escapeHtml(String(count)) +
      '</span></div></td></tr>'
    );
  }

  function renderRows(rows) {
    var body = document.getElementById('hres-table-body');
    if (!body) return;
    state.rows = Array.isArray(rows) ? rows : [];
    if (!state.rows.length) {
      var q = filterValue('hres-search');
      var needle = String(q || '').trim();
      var idish = /FDR\d{6,}/i.test(needle) || /^\d{10,}$/.test(needle);
      var emptyMsg = idish
        ? 'Asia Tech did not send ' +
          needle +
          '. Their feed only includes bookings created or updated in the last 10 days. Open that booking in Asia Tech, save it once, then Refresh.'
        : 'No reservations match these filters.';
      body.innerHTML =
        '<tr class="hres-empty-row"><td colspan="7">' +
        escapeHtml(emptyMsg) +
        '</td></tr>';
      return;
    }
    var unassigned = [];
    var partial = [];
    var assigned = [];
    state.rows.forEach(function (row) {
      var bucket = reservationAssignmentBucket(row);
      if (bucket === 'assigned') assigned.push(row);
      else if (bucket === 'partial') partial.push(row);
      else unassigned.push(row);
    });
    var html = '';
    if (unassigned.length) {
      html += renderGroupHeader('Needs room', unassigned.length, 'unassigned');
      html += unassigned.map(renderRowHtml).join('');
    }
    if (partial.length) {
      html += renderGroupHeader('Partially assigned', partial.length, 'partial');
      html += partial.map(renderRowHtml).join('');
    }
    if (assigned.length) {
      html += renderGroupHeader('Room assigned', assigned.length, 'assigned');
      html += assigned.map(renderRowHtml).join('');
    }
    body.innerHTML = html;
    applyTableSort(false);
  }

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

  function applyTableSort(toggle) {
    var table = document.querySelector('#hotel-reservations-page table.hres-table');
    if (!table) return;
    var tbody = table.tBodies[0];
    if (!tbody) return;
    var headers = Array.prototype.slice.call(table.querySelectorAll('th.pl-sortable'));
    var th = null;
    if (state.sortKey) {
      for (var i = 0; i < headers.length; i++) {
        if (headers[i].getAttribute('data-sort') === state.sortKey) {
          th = headers[i];
          break;
        }
      }
    }
    if (!th) return;
    if (toggle) state.sortAsc = !state.sortAsc;
    var type = th.getAttribute('data-sort-type') || 'text';
    var colIndex = Array.prototype.indexOf.call(th.parentNode.children, th);
    if (colIndex < 0) return;
    var ascending = state.sortAsc;
    function sortRows(list) {
      list.sort(function (a, b) {
        var av = cellSortValue(a, colIndex, type);
        var bv = cellSortValue(b, colIndex, type);
        var cmp = 0;
        if (type === 'number') cmp = av - bv;
        else
          cmp = String(av).localeCompare(String(bv), undefined, {
            numeric: true,
            sensitivity: 'base'
          });
        return ascending ? cmp : -cmp;
      });
      return list;
    }
    var unassignedHeader = tbody.querySelector('tr.hres-group-row[data-hres-group="unassigned"]');
    var partialHeader = tbody.querySelector('tr.hres-group-row[data-hres-group="partial"]');
    var assignedHeader = tbody.querySelector('tr.hres-group-row[data-hres-group="assigned"]');
    var unassigned = sortRows(
      Array.prototype.slice.call(
        tbody.querySelectorAll('tr[data-sort-row][data-assigned="unassigned"]')
      )
    );
    var partial = sortRows(
      Array.prototype.slice.call(
        tbody.querySelectorAll('tr[data-sort-row][data-assigned="partial"]')
      )
    );
    var assigned = sortRows(
      Array.prototype.slice.call(
        tbody.querySelectorAll('tr[data-sort-row][data-assigned="assigned"]')
      )
    );
    var frag = document.createDocumentFragment();
    if (unassignedHeader) frag.appendChild(unassignedHeader);
    unassigned.forEach(function (row) {
      frag.appendChild(row);
    });
    if (partialHeader) frag.appendChild(partialHeader);
    partial.forEach(function (row) {
      frag.appendChild(row);
    });
    if (assignedHeader) frag.appendChild(assignedHeader);
    assigned.forEach(function (row) {
      frag.appendChild(row);
    });
    tbody.appendChild(frag);
    headers.forEach(function (header) {
      header.classList.remove('is-sorted-asc', 'is-sorted-desc');
      header.setAttribute('aria-sort', 'none');
    });
    th.classList.add(ascending ? 'is-sorted-asc' : 'is-sorted-desc');
    th.setAttribute('aria-sort', ascending ? 'ascending' : 'descending');
  }

  function bindTableSort(root) {
    var table = (root || document).querySelector('table.hres-table');
    if (!table || table.getAttribute('data-hres-sort-bound') === '1') return;
    table.setAttribute('data-hres-sort-bound', '1');
    var headers = Array.prototype.slice.call(table.querySelectorAll('th.pl-sortable'));
    headers.forEach(function (th) {
      th.addEventListener('click', function (event) {
        event.preventDefault();
        event.stopPropagation();
        var key = th.getAttribute('data-sort') || '';
        if (!key) return;
        if (state.sortKey === key) applyTableSort(true);
        else {
          state.sortKey = key;
          state.sortAsc = true;
          applyTableSort(false);
        }
      });
      th.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          th.click();
        }
      });
    });
  }

  function renderPagination(pagination) {
    var meta = document.getElementById('hres-pagination-meta');
    if (!meta) return;
    state.pagination = pagination || null;
    var total = pagination && pagination.total != null ? Number(pagination.total) : 0;
    meta.textContent =
      total + ' reservation' + (total === 1 ? '' : 's');
  }

  function sameId(a, b) {
    return String(a == null ? '' : a) === String(b == null ? '' : b);
  }

  function todayIso() {
    var d = new Date();
    var m = d.getMonth() + 1;
    var day = d.getDate();
    return (
      d.getFullYear() +
      '-' +
      (m < 10 ? '0' : '') +
      m +
      '-' +
      (day < 10 ? '0' : '') +
      day
    );
  }

  function stayWindow(stay) {
    if (!stay || typeof stay !== 'object') return null;
    var checkIn = String(stay.checkInDate || stay.check_in_date || '').slice(0, 10);
    var checkOut = String(stay.checkOutDate || stay.check_out_date || '').slice(0, 10);
    if (!checkIn) return null;
    if (!checkOut) {
      var parts = /^(\d{4})-(\d{2})-(\d{2})$/.exec(checkIn);
      if (!parts) return { checkIn: checkIn, checkOut: checkIn };
      var next = new Date(
        Number(parts[1]),
        Number(parts[2]) - 1,
        Number(parts[3]) + 1
      );
      var nm = next.getMonth() + 1;
      var nd = next.getDate();
      checkOut =
        next.getFullYear() +
        '-' +
        (nm < 10 ? '0' : '') +
        nm +
        '-' +
        (nd < 10 ? '0' : '') +
        nd;
    }
    return { checkIn: checkIn, checkOut: checkOut };
  }

  function rangesOverlap(aIn, aOut, bIn, bOut) {
    return aIn && aOut && bIn && bOut && aIn <= bOut && bIn <= aOut;
  }

  function roomAvailableForReservation(room, reservation) {
    if (!room || !reservation) return false;
    var status = String(room.status || 'vacant').toLowerCase();
    var cin = String(reservation.checkInDate || '').slice(0, 10);
    var cout = String(reservation.checkOutDate || '').slice(0, 10);
    if (!cin || !cout || cout <= cin) return false;
    if (status === 'out_of_order') return false;
    if (reservation.roomId && sameId(room.id, reservation.roomId)) return true;
    if (status === 'dirty' && cin <= todayIso()) return false;
    var stayWin = stayWindow(room.stay);
    if (
      stayWin &&
      rangesOverlap(cin, cout, stayWin.checkIn, stayWin.checkOut)
    ) {
      return false;
    }
    var upcomingWin = stayWindow(room.upcomingStay || room.upcoming_stay);
    if (
      upcomingWin &&
      rangesOverlap(cin, cout, upcomingWin.checkIn, upcomingWin.checkOut)
    ) {
      return false;
    }
    return true;
  }

  function roomsForReservation(reservation) {
    var all = state.vacantRooms || [];
    if (!reservation) return all;
    return all.filter(function (room) {
      return roomAvailableForReservation(room, reservation);
    });
  }

  function findRow(id) {
    var i;
    for (i = 0; i < state.rows.length; i++) {
      if (sameId(state.rows[i].id, id)) return state.rows[i];
    }
    return null;
  }

  function reservationTotalRooms(row) {
    var n = Number(row && row.totalRooms);
    if (!isFinite(n) || n < 1) return 1;
    return Math.floor(n);
  }

  function assignedRoomIds(row) {
    var ids = [];
    var seen = {};
    function push(id) {
      var text = String(id == null ? '' : id).trim();
      if (!text || seen[text]) return;
      seen[text] = true;
      ids.push(text);
    }
    var list = (row && row.roomIds) || [];
    if (Array.isArray(list)) {
      list.forEach(push);
    }
    if (row && row.roomId) push(row.roomId);
    return ids;
  }

  function assignedRoomCount(row) {
    var ids = assignedRoomIds(row);
    if (ids.length) return ids.length;
    var numbers = [];
    var seen = {};
    function pushNum(value) {
      var text = String(value == null ? '' : value).trim();
      if (!text || seen[text]) return;
      seen[text] = true;
      numbers.push(text);
    }
    var list = (row && row.roomNumbers) || [];
    if (Array.isArray(list)) {
      list.forEach(pushNum);
    }
    if (row && row.roomNumber) pushNum(row.roomNumber);
    return numbers.length;
  }

  function reservationRoomCap(row) {
    return Math.max(0, reservationTotalRooms(row) - assignedRoomCount(row));
  }

  function selectedRoomIds() {
    return Array.isArray(state.selectedRoomIds) ? state.selectedRoomIds : [];
  }

  function pruneSelectedRoomIds(rooms) {
    var list = rooms || [];
    state.selectedRoomIds = selectedRoomIds().filter(function (id) {
      return list.some(function (room) {
        return sameId(room.id, id);
      });
    });
    return selectedRoomIds();
  }

  function toggleSelectedRoom(roomId, reservation) {
    var cap = reservationRoomCap(reservation);
    if (cap <= 0) {
      showToast('All rooms for this booking are already assigned.');
      return false;
    }
    var ids = selectedRoomIds().slice();
    var idx = -1;
    var i;
    for (i = 0; i < ids.length; i++) {
      if (sameId(ids[i], roomId)) {
        idx = i;
        break;
      }
    }
    if (idx >= 0) {
      ids.splice(idx, 1);
    } else if (ids.length >= cap) {
      if (cap === 1 && assignedRoomCount(reservation) === 0) {
        ids = [roomId];
      } else {
        showToast(
          cap <= 0
            ? 'All rooms for this booking are already assigned.'
            : 'You can select at most ' + cap + ' more rooms.'
        );
        return false;
      }
    } else {
      ids.push(roomId);
    }
    state.selectedRoomIds = ids;
    return true;
  }

  function setAssignButtonsDisabled(disabled) {
    var enabled = !disabled;
    document.querySelectorAll('#hres-assign-btn, .hres-assign-submit').forEach(function (btn) {
      btn.disabled = !!disabled;
    });
    var headerBtn = document.getElementById('hres-assign-card-btn');
    if (headerBtn) {
      headerBtn.hidden = !enabled;
      if (enabled) headerBtn.removeAttribute('hidden');
      else headerBtn.setAttribute('hidden', 'hidden');
    }
  }

  function renderRoomGrid(reservation) {
    var grid = document.getElementById('hres-room-grid');
    var assignCard = document.querySelector('.hres-assign-card');
    if (!grid) return;
    var canAssign = canAssignReservation(reservation);
    var remaining = reservationRoomCap(reservation);
    var totalRooms = reservationTotalRooms(reservation);
    var assignedCount = assignedRoomCount(reservation);
    if (assignCard) {
      assignCard.hidden = !canAssign;
      assignCard.setAttribute('aria-hidden', canAssign ? 'false' : 'true');
    }
    if (!canAssign) {
      grid.innerHTML = '';
      setAssignButtonsDisabled(true);
      state.selectedRoomIds = [];
      return;
    }
    if (remaining <= 0) {
      grid.innerHTML =
        '<div class="hres-room-empty">All ' +
        totalRooms +
        ' rooms are assigned</div>';
      setAssignButtonsDisabled(true);
      state.selectedRoomIds = [];
      syncAssignRoomLabel([], reservation);
      return;
    }
    var rooms = roomsForReservation(reservation);
    var ids = pruneSelectedRoomIds(rooms);
    if (!rooms.length) {
      grid.innerHTML =
        '<div class="hres-room-empty">No rooms available for these dates.</div>';
      setAssignButtonsDisabled(true);
      return;
    }
    grid.innerHTML = rooms
      .map(function (room) {
        var selected = ids.some(function (id) {
          return sameId(id, room.id);
        })
          ? ' is-selected'
          : '';
        var primary =
          assignedCount === 0 && ids.length && sameId(ids[0], room.id)
            ? ' is-primary'
            : '';
        var status = String(room.status || 'vacant').toLowerCase();
        var badge = status === 'vacant' ? 'VACANT' : 'AVAILABLE';
        var primaryBadge = primary
          ? '<span class="hres-room-primary">PRIMARY</span>'
          : '';
        return (
          '<button type="button" class="hres-room-option' +
          selected +
          primary +
          '" data-room-id="' +
          escapeAttr(room.id) +
          '" aria-pressed="' +
          (selected ? 'true' : 'false') +
          '">' +
          '<strong>' +
          escapeHtml(room.number || '') +
          '</strong>' +
          '<span>' +
          escapeHtml(room.roomTypeLabel || room.roomType || 'Room') +
          '</span>' +
          '<span class="hres-room-vacant">' +
          escapeHtml(badge) +
          '</span>' +
          primaryBadge +
          '</button>'
        );
      })
      .join('');
    setAssignButtonsDisabled(!(canAssign && ids.length));
    syncAssignRoomLabel(rooms, reservation);
  }

  function paintRoomSelection(reservation) {
    var grid = document.getElementById('hres-room-grid');
    var row = reservation || findRow(state.selectedId);
    var ids = selectedRoomIds();
    if (grid) {
      grid.querySelectorAll('.hres-room-option[data-room-id]').forEach(function (btn) {
        var id = btn.getAttribute('data-room-id') || '';
        var isSel = ids.some(function (item) {
          return sameId(item, id);
        });
        var isPrimary = !!(
          assignedRoomCount(row) === 0 &&
          isSel &&
          ids.length &&
          sameId(ids[0], id)
        );
        btn.classList.toggle('is-selected', isSel);
        btn.classList.toggle('is-primary', isPrimary);
        btn.setAttribute('aria-pressed', isSel ? 'true' : 'false');
        var badge = btn.querySelector('.hres-room-primary');
        if (isPrimary && !badge) {
          badge = document.createElement('span');
          badge.className = 'hres-room-primary';
          badge.textContent = 'PRIMARY';
          btn.appendChild(badge);
        } else if (!isPrimary && badge) {
          badge.parentNode.removeChild(badge);
        }
      });
    }
    setAssignButtonsDisabled(!(canAssignReservation(row) && ids.length));
    syncAssignRoomLabel(null, row);
  }

  function findRoomById(roomId) {
    var rooms = state.vacantRooms || [];
    var i;
    for (i = 0; i < rooms.length; i++) {
      if (sameId(rooms[i].id, roomId)) return rooms[i];
    }
    return null;
  }

  function syncAssignRoomLabel(rooms, reservation) {
    var labels = [
      document.getElementById('hres-assign-room-label'),
      document.getElementById('hres-assign-summary')
    ].filter(Boolean);
    var hint = document.getElementById('hres-assign-hint');
    var row = reservation || findRow(state.selectedId);
    var totalRooms = reservationTotalRooms(row);
    var assignedCount = assignedRoomCount(row);
    var cap = reservationRoomCap(row);
    var ids = selectedRoomIds();
    if (hint) {
      if (assignedCount > 0 && cap <= 0) {
        hint.textContent = 'All ' + totalRooms + ' rooms are assigned';
      } else if (assignedCount > 0) {
        hint.textContent =
          assignedCount +
          ' of ' +
          totalRooms +
          ' rooms assigned · select up to ' +
          cap +
          ' more';
      } else {
        hint.textContent =
          cap > 1
            ? 'Select up to ' + cap + ' rooms, then Assign Room'
            : 'Select a room, then Assign Room';
      }
    }
    if (!labels.length) return;
    if (assignedCount > 0 && cap <= 0) {
      labels.forEach(function (el) {
        el.textContent = 'All ' + totalRooms + ' rooms are assigned';
      });
      return;
    }
    if (!ids.length) {
      labels.forEach(function (el) {
        el.textContent =
          assignedCount > 0
            ? 'Select up to ' + cap + ' more'
            : cap > 1
              ? 'Select rooms'
              : 'Select a room';
      });
      return;
    }
    var list = rooms || roomsForReservation(row) || state.vacantRooms || [];
    var primary = null;
    var i;
    if (assignedCount === 0) {
      for (i = 0; i < list.length; i++) {
        if (sameId(list[i].id, ids[0])) {
          primary = list[i];
          break;
        }
      }
      if (!primary) primary = findRoomById(ids[0]);
    }
    var text =
      assignedCount > 0
        ? ids.length + ' of ' + cap + ' more selected'
        : ids.length + ' of ' + cap + ' rooms selected';
    if (primary) {
      text +=
        ' · Primary: Room ' +
        (primary.number || '') +
        (primary.roomTypeLabel || primary.roomType
          ? ' · ' + (primary.roomTypeLabel || primary.roomType)
          : '');
    }
    labels.forEach(function (el) {
      el.textContent = text;
    });
  }

  function openAssignModal() {
    var modal = document.getElementById('hres-assign-modal');
    if (!modal) return;
    var row = findRow(state.selectedId);
    if (!canAssignReservation(row)) {
      closeAssignModal();
      showToast('Cancelled reservations cannot be assigned a room.');
      return;
    }
    modal.hidden = false;
    modal.setAttribute('aria-hidden', 'false');
    setAssignButtonsDisabled(
      !(selectedRoomIds().length && canAssignReservation(row))
    );
    syncAssignRoomLabel(roomsForReservation(row), row);
  }

  function closeAssignModal() {
    var modal = document.getElementById('hres-assign-modal');
    if (!modal) return;
    modal.hidden = true;
    modal.setAttribute('aria-hidden', 'true');
  }

  function paintReservationDetail(row, ids) {
    if (!row || !ids) return;
    var avatar = document.getElementById(ids.avatar);
    var guest = document.getElementById(ids.guest);
    var booking = document.getElementById(ids.booking);
    var status = document.getElementById(ids.status);
    var dl = document.getElementById(ids.dl);
    var payment = document.getElementById(ids.payment);
    var amount = document.getElementById(ids.amount);

    if (avatar) avatar.textContent = row.initials || '?';
    if (guest) guest.textContent = row.guestName || 'Guest';
    if (booking) booking.textContent = '#' + (row.bookingId || row.id);
    if (status) {
      status.className = 'hres-status-pill ' + statusClass(row.status);
      status.textContent = row.statusLabel || row.status;
    }
    if (payment) {
      payment.textContent = row.paymentStatusLabel || row.paymentStatus || 'Pending';
      payment.className =
        'hres-payment-pill' +
        (row.paymentStatus === 'paid' ? '' : ' is-pending');
    }
    if (amount) amount.textContent = formatInr(row.amount);
    if (dl) {
      var fields = [
        ['Phone', row.mobile || '—'],
        ['Email', row.email || '—'],
        ['Guests', String(row.guests || 1)],
        ['Check In', formatDisplayDate(row.checkInDate) + ' ' + formatTime(row.checkInTime)],
        ['Check Out', formatDisplayDate(row.checkOutDate) + ' ' + formatTime(row.checkOutTime)],
        ['Nights', String(row.nights || 1)],
        ['Meal Plan', row.mealPlan || '—'],
        ['Total Amount', formatInr(row.amount)],
        ['Source', row.sourceLabel || row.source || '—'],
        ['Total Room', String(row.totalRooms || 1)],
        [
          'Assigned Room',
          reservationIsAssigned(row) ? reservationRoomLabel(row) || 'Assigned' : 'Unassigned'
        ],
        ['Special Notes', row.specialNotes || '—']
      ];
      dl.innerHTML = fields
        .map(function (pair) {
          var span = pair[0] === 'Special Notes' ? ' class="hres-detail-span"' : '';
          return (
            '<div' +
            span +
            '><dt>' +
            escapeHtml(pair[0]) +
            '</dt><dd>' +
            escapeHtml(pair[1]) +
            '</dd></div>'
          );
        })
        .join('');
    }
  }

  var DETAIL_MODAL_IDS = {
    avatar: 'hres-detail-avatar',
    guest: 'hres-detail-guest',
    booking: 'hres-detail-booking',
    status: 'hres-detail-status',
    dl: 'hres-detail-dl',
    payment: 'hres-detail-payment',
    amount: 'hres-detail-amount'
  };

  var ASSIGN_DETAIL_IDS = {
    avatar: 'hres-assign-avatar',
    guest: 'hres-assign-guest',
    booking: 'hres-assign-booking',
    status: 'hres-assign-status',
    dl: 'hres-assign-dl',
    payment: 'hres-assign-payment',
    amount: 'hres-assign-amount'
  };

  function openDetail(row) {
    var panel = document.getElementById('hres-detail');
    if (!panel || !row) return;
    closeAssignModal();
    state.selectedId = row.id;
    panel.hidden = false;
    panel.setAttribute('aria-hidden', 'false');
    paintReservationDetail(row, DETAIL_MODAL_IDS);
    document.querySelectorAll('#hres-table-body tr[data-res-id]').forEach(function (tr) {
      tr.classList.toggle('is-selected', tr.getAttribute('data-res-id') === row.id);
    });
  }

  function closeDetail() {
    closeAssignModal();
    var panel = document.getElementById('hres-detail');
    if (panel) {
      panel.hidden = true;
      panel.setAttribute('aria-hidden', 'true');
    }
  }

  function openAssignPanel(row, opts) {
    var panel = document.getElementById('hres-assign-panel');
    if (!panel || !row) return;
    opts = opts || {};
    closeDetail();
    closeAssignModal();
    state.selectedId = row.id;
    state.selectedRoomIds = [];
    panel.hidden = false;
    paintReservationDetail(row, ASSIGN_DETAIL_IDS);
    /* Keep modal payment chips in sync when assign modal is used later */
    paintReservationDetail(row, {
      payment: 'hres-detail-payment',
      amount: 'hres-detail-amount'
    });
    renderRoomGrid(row);
    document.querySelectorAll('#hres-table-body tr[data-res-id]').forEach(function (tr) {
      tr.classList.toggle('is-selected', tr.getAttribute('data-res-id') === row.id);
    });
    if (opts.scroll !== false) {
      requestAnimationFrame(function () {
        panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
      });
    }
  }

  function closeAssignPanel() {
    closeAssignModal();
    var panel = document.getElementById('hres-assign-panel');
    if (panel) panel.hidden = true;
    state.selectedId = '';
    state.selectedRoomIds = [];
    document.querySelectorAll('#hres-table-body tr.is-selected').forEach(function (tr) {
      tr.classList.remove('is-selected');
    });
  }

  function loadReservations(opts) {
    var root = pageRoot();
    if (!root) return;
    opts = opts || {};
    if (opts.page) state.page = opts.page;
    var gen = ++state.loadGen;
    var params = new URLSearchParams();
    params.set('page', '1');
    params.set('page_size', 'all');
    var q = filterValue('hres-search');
    var status = filterValue('hres-status-filter') || 'all';
    var range = dateFilterRange(root);
    if (q) params.set('q', q);
    if (state.checkoutOnly) {
      params.set('status', 'all');
      params.set('checkout_only', '1');
    } else if (status) {
      params.set('status', status);
    }
    if (range.from) params.set('date_from', range.from);
    if (range.to) params.set('date_to', range.to);
    if (opts.refresh) params.set('refresh', '1');

    var body = document.getElementById('hres-table-body');
    if (body && !opts.silent) {
      body.innerHTML =
        '<tr class="hres-empty-row"><td colspan="7">Loading reservations…</td></tr>';
    }

    fetch(apiBase(root) + '?' + params.toString(), {
      credentials: 'same-origin',
      headers: { Accept: 'application/json' },
      cache: 'no-store'
    })
      .then(function (resp) {
        return resp.json().then(function (data) {
          return { ok: resp.ok, data: data };
        });
      })
      .then(function (result) {
        if (gen !== state.loadGen) return;
        if (!result.ok || !result.data || !result.data.ok) {
          throw new Error((result.data && result.data.error) || 'Load failed');
        }
        paintKpis(result.data.kpis);
        paintSyncBanner(result.data.sync, result.data.mode, opts);
        state.vacantRooms = Array.isArray(result.data.vacantRooms)
          ? result.data.vacantRooms
          : [];
        renderRows(result.data.reservations || []);
        renderPagination(result.data.pagination || null);
        if (state.selectedId) {
          var row = findRow(state.selectedId);
          var assignPanel = document.getElementById('hres-assign-panel');
          var detailPanel = document.getElementById('hres-detail');
          if (row) {
            if (assignPanel && !assignPanel.hidden) {
              openAssignPanel(row, { scroll: false });
            } else if (detailPanel && !detailPanel.hidden) {
              openDetail(row);
            } else {
              document
                .querySelectorAll('#hres-table-body tr[data-res-id]')
                .forEach(function (tr) {
                  tr.classList.toggle(
                    'is-selected',
                    tr.getAttribute('data-res-id') === row.id
                  );
                });
            }
          } else {
            closeAssignPanel();
            closeDetail();
          }
        }
      })
      .catch(function () {
        if (gen !== state.loadGen) return;
        if (body) {
          body.innerHTML =
            '<tr class="hres-empty-row"><td colspan="7">Could not load reservations.</td></tr>';
        }
        paintSyncBanner(
          { error: 'Could not load reservations from the server.' },
          'stub',
          opts
        );
        showToast('Could not load reservations');
      });
  }

  function sanitizeContactDisplay(value) {
    var text = String(value || '').trim();
    if (!text || /^n\/?a$/i.test(text)) return '';
    return text;
  }

  function collectEditFormSnapshot() {
    return [
      filterValue('hres-edit-guest-title'),
      filterValue('hres-edit-guest'),
      filterValue('hres-edit-mobile'),
      filterValue('hres-edit-email'),
      filterValue('hres-edit-checkin'),
      filterValue('hres-edit-checkout'),
      filterValue('hres-edit-guests'),
      filterValue('hres-edit-amount'),
      filterValue('hres-edit-source'),
      filterValue('hres-edit-total-rooms'),
      filterValue('hres-edit-status'),
      filterValue('hres-edit-meal'),
      filterValue('hres-edit-notes')
    ].join('\u0001');
  }

  function syncEditSaveVisibility() {
    var btn = document.getElementById('hres-edit-save');
    if (!btn) return;
    var dirty = collectEditFormSnapshot() !== state.editBaseline;
    if (dirty) {
      btn.hidden = false;
      btn.removeAttribute('aria-hidden');
    } else {
      btn.hidden = true;
      btn.setAttribute('aria-hidden', 'true');
    }
  }

  global.hresEditFormChanged = function () {
    syncEditSaveVisibility();
  };

  function openEditModal(row) {
    var modal = document.getElementById('hres-edit-modal');
    var title = document.getElementById('hres-edit-title');
    if (!modal) return;
    var isEdit = !!(row && row.id);
    if (title) title.textContent = isEdit ? 'Edit Reservation' : 'New Reservation';
    document.getElementById('hres-edit-id').value = isEdit ? row.id : '';
    var parts = splitGuestTitleName(isEdit ? row.guestName || '' : '');
    fillGuestTitleSelect(parts.title);
    document.getElementById('hres-edit-guest').value = parts.name;
    document.getElementById('hres-edit-mobile').value = isEdit
      ? sanitizeContactDisplay(row.mobile)
      : '';
    document.getElementById('hres-edit-email').value = isEdit
      ? sanitizeContactDisplay(row.email)
      : '';
    document.getElementById('hres-edit-checkin').value = isEdit
      ? String(row.checkInDate || '').slice(0, 10)
      : '';
    document.getElementById('hres-edit-checkout').value = isEdit
      ? String(row.checkOutDate || '').slice(0, 10)
      : '';
    document.getElementById('hres-edit-guests').value = isEdit ? row.guests || 2 : 2;
    document.getElementById('hres-edit-amount').value = isEdit ? row.amount || 0 : 0;
    document.getElementById('hres-edit-source').value = isEdit
      ? row.source || 'direct'
      : 'direct';
    document.getElementById('hres-edit-total-rooms').value = isEdit
      ? row.totalRooms || 1
      : 1;
    fillEditListbox(
      'hres-edit-status',
      isEdit ? row.status || 'upcoming' : 'upcoming',
      STATUS_EDIT_LABELS,
      'Select status'
    );
    fillMealPlanSelect(isEdit ? row.mealPlan : '');
    document.getElementById('hres-edit-notes').value = isEdit
      ? row.specialNotes || ''
      : '';
    state.editBaseline = collectEditFormSnapshot();
    syncEditSaveVisibility();
    modal.hidden = false;
    modal.setAttribute('aria-hidden', 'false');
  }

  function closeEditModal() {
    var modal = document.getElementById('hres-edit-modal');
    if (!modal) return;
    if (typeof window.closeAllEpListboxes === 'function') {
      window.closeAllEpListboxes();
    }
    modal.hidden = true;
    modal.setAttribute('aria-hidden', 'true');
    state.editBaseline = '';
    syncEditSaveVisibility();
  }

  function saveEditForm(event) {
    event.preventDefault();
    var root = pageRoot();
    if (!root) return;
    var id = filterValue('hres-edit-id');
    var payload = {
      guestName: joinGuestTitleName(
        filterValue('hres-edit-guest-title'),
        filterValue('hres-edit-guest')
      ),
      mobile: filterValue('hres-edit-mobile'),
      email: filterValue('hres-edit-email'),
      checkInDate: filterValue('hres-edit-checkin'),
      checkOutDate: filterValue('hres-edit-checkout'),
      guests: Number(filterValue('hres-edit-guests') || 1),
      amount: Number(filterValue('hres-edit-amount') || 0),
      source: filterValue('hres-edit-source') || 'direct',
      totalRooms: Number(filterValue('hres-edit-total-rooms') || 1),
      status: filterValue('hres-edit-status') || 'upcoming',
      mealPlan: filterValue('hres-edit-meal'),
      specialNotes: filterValue('hres-edit-notes')
    };
    if (!filterValue('hres-edit-guest') || !payload.checkInDate || !payload.checkOutDate) {
      showToast('Guest name and dates are required');
      return;
    }
    var url = apiBase(root) + (id ? '/' + encodeURIComponent(id) : '');
    var method = id ? 'PUT' : 'POST';
    fetch(url, {
      method: method,
      credentials: 'same-origin',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(payload)
    })
      .then(function (resp) {
        return resp.json().then(function (data) {
          return { ok: resp.ok, data: data };
        });
      })
      .then(function (result) {
        if (!result.ok || !result.data || !result.data.ok) {
          throw new Error((result.data && result.data.error) || 'Save failed');
        }
        closeEditModal();
        showToast(id ? 'Reservation updated' : 'Reservation created');
        if (result.data.reservation && result.data.reservation.id) {
          state.selectedId = result.data.reservation.id;
        }
        loadReservations({ silent: true });
      })
      .catch(function (err) {
        showToast((err && err.message) || 'Could not save reservation');
      });
  }

  function assignSelectedRoom() {
    var root = pageRoot();
    var ids = selectedRoomIds();
    if (!root || !state.selectedId || !ids.length) return;
    var row = findRow(state.selectedId);
    if (!canAssignReservation(row)) {
      showToast('Cancelled reservations cannot be assigned a room.');
      closeAssignModal();
      return;
    }
    setAssignButtonsDisabled(true);
    fetch(
      apiBase(root) +
        '/' +
        encodeURIComponent(state.selectedId) +
        '/assign',
      {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          Accept: 'application/json',
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ roomIds: ids, roomId: ids[0] })
      }
    )
      .then(function (resp) {
        return resp.json().then(function (data) {
          return { ok: resp.ok, data: data };
        });
      })
      .then(function (result) {
        if (!result.ok || !result.data || !result.data.ok) {
          throw new Error((result.data && result.data.error) || 'Assign failed');
        }
        showToast('Room assigned');
        closeAssignModal();
        if (typeof global.deNavigateWithTransition === 'function') {
          global.deNavigateWithTransition('/hotel/rooms');
        } else {
          global.location.href = '/hotel/rooms';
        }
      })
      .catch(function (err) {
        showToast((err && err.message) || 'Could not assign room');
        setAssignButtonsDisabled(false);
      });
  }

  function bindOnce(root) {
    if (!root || root.getAttribute('data-hres-bound') === '1') return;
    root.setAttribute('data-hres-bound', '1');

    global.hresStatusChanged = function () {
      syncKpiFromStatusFilter();
      loadReservations();
    };

    var search = document.getElementById('hres-search');
    var searchChip = document.getElementById('hres-search-chip');
    if (search) {
      var searchTimer = null;
      var syncSearchChip = function () {
        if (searchChip) {
          searchChip.classList.toggle('is-active', !!(search.value || '').trim());
        }
      };
      syncSearchChip();
      search.addEventListener('input', function () {
        syncSearchChip();
        clearTimeout(searchTimer);
        searchTimer = setTimeout(function () {
          loadReservations({ silent: true });
        }, 250);
      });
    }

    root.addEventListener('click', function (event) {
      var kpiCard = event.target.closest('.hres-kpi[data-kpi]');
      if (kpiCard && root.contains(kpiCard)) {
        event.preventDefault();
        applyKpiFilter(kpiCard.getAttribute('data-kpi') || 'total');
        return;
      }

      var refresh = event.target.closest('#hres-refresh-btn');
      if (refresh) {
        event.preventDefault();
        loadReservations({ refresh: true });
        showToast('Refreshing from Asia Tech…');
        return;
      }

      var newBtn = event.target.closest('#hres-new-btn');
      if (newBtn) {
        event.preventDefault();
        openEditModal(null);
        return;
      }

      var closeDetailBtn = event.target.closest('#hres-detail-close');
      if (closeDetailBtn) {
        event.preventDefault();
        closeDetail();
        return;
      }

      var closeAssignPanelBtn = event.target.closest('#hres-assign-panel-close');
      if (closeAssignPanelBtn) {
        event.preventDefault();
        closeAssignPanel();
        return;
      }

      var detailOverlay = event.target.closest('#hres-detail');
      if (detailOverlay && event.target === detailOverlay) {
        event.preventDefault();
        closeDetail();
        return;
      }

      var editClose = event.target.closest('[data-hres-edit-close]');
      if (editClose) {
        event.preventDefault();
        closeEditModal();
        return;
      }

      var assignClose = event.target.closest('[data-hres-assign-close]');
      if (assignClose) {
        event.preventDefault();
        closeAssignModal();
        return;
      }

      var assignOverlay = event.target.closest('#hres-assign-modal');
      if (assignOverlay && event.target === assignOverlay) {
        event.preventDefault();
        closeAssignModal();
        return;
      }

      var assignBtn = event.target.closest('#hres-assign-btn, .hres-assign-submit');
      if (assignBtn) {
        event.preventDefault();
        assignSelectedRoom();
        return;
      }

      var editBtn = event.target.closest('#hres-edit-btn, .hres-edit-submit');
      if (editBtn) {
        event.preventDefault();
        closeAssignModal();
        openEditModal(findRow(state.selectedId));
        return;
      }

      var cancelledStatus = event.target.closest(
        '.hres-status-pill.is-cancelled, tr.is-cancelled td[data-sort-value="cancelled"]'
      );
      if (cancelledStatus && !event.target.closest('[data-hres-view]')) {
        event.preventDefault();
        event.stopPropagation();
        return;
      }

      var viewBtn = event.target.closest('[data-hres-view]');
      if (viewBtn) {
        var viewTr = viewBtn.closest('tr[data-res-id]');
        var viewId = (viewTr && viewTr.getAttribute('data-res-id')) || '';
        if (viewId) {
          event.preventDefault();
          event.stopPropagation();
          var viewRow = findRow(viewId);
          if (viewRow) openDetail(viewRow);
        }
        return;
      }

      var tr = event.target.closest('tr[data-res-id]');
      if (tr) {
        var id = tr.getAttribute('data-res-id') || '';
        if (id) {
          event.preventDefault();
          var found = findRow(id);
          if (!found) return;
          if (reservationAssignmentBucket(found) === 'assigned') {
            closeDetail();
            closeAssignPanel();
            state.selectedId = found.id;
            document
              .querySelectorAll('#hres-table-body tr[data-res-id]')
              .forEach(function (rowEl) {
                rowEl.classList.toggle(
                  'is-selected',
                  rowEl.getAttribute('data-res-id') === found.id
                );
              });
            openEditModal(found);
          } else {
            openAssignPanel(found);
          }
        }
      }
    });

    root.addEventListener('keydown', function (event) {
      if (event.key === 'Escape') {
        var assignModal = document.getElementById('hres-assign-modal');
        if (assignModal && !assignModal.hidden) {
          event.preventDefault();
          closeAssignModal();
          return;
        }
        var editModal = document.getElementById('hres-edit-modal');
        if (editModal && !editModal.hidden) {
          event.preventDefault();
          closeEditModal();
          return;
        }
        var detailModal = document.getElementById('hres-detail');
        if (detailModal && !detailModal.hidden) {
          event.preventDefault();
          closeDetail();
          return;
        }
      }
      var kpiCard = event.target.closest('.hres-kpi[data-kpi]');
      if (
        kpiCard &&
        root.contains(kpiCard) &&
        (event.key === 'Enter' || event.key === ' ')
      ) {
        event.preventDefault();
        applyKpiFilter(kpiCard.getAttribute('data-kpi') || 'total');
      }
    });

    var form = document.getElementById('hres-edit-form');
    if (form) {
      form.addEventListener('submit', saveEditForm);
      form.addEventListener('input', syncEditSaveVisibility);
      form.addEventListener('change', syncEditSaveVisibility);
    }

    var clearBtn = document.getElementById('hres-date-range-clear');
    if (clearBtn && clearBtn.getAttribute('data-hres-clear-bound') !== '1') {
      clearBtn.setAttribute('data-hres-clear-bound', '1');
      clearBtn.addEventListener('click', function (event) {
        event.preventDefault();
        event.stopPropagation();
        var fromEl = document.getElementById('hres-date-from');
        var toEl = document.getElementById('hres-date-to');
        var display = document.getElementById('hres-date-range-display');
        var wrap = document.getElementById('hres-date-range-wrap');
        var panel = document.getElementById('hres-date-range-panel');
        var trigger = document.getElementById('hres-date-range-trigger');
        if (fromEl) fromEl.value = '';
        if (toEl) toEl.value = '';
        if (display) display.textContent = 'Select date…';
        if (wrap) wrap.classList.remove('open');
        if (panel) panel.setAttribute('hidden', 'hidden');
        if (trigger) trigger.setAttribute('aria-expanded', 'false');
        if (global.SalesDateRangePicker && typeof global.SalesDateRangePicker.clearPanelPosition === 'function') {
          global.SalesDateRangePicker.clearPanelPosition(panel);
        }
        setDateRangeFilteredClass();
        loadReservations({ silent: true });
      });
    }
    setDateRangeFilteredClass();
  }

  function initDateRangePicker() {
    if (!global.SalesDateRangePicker || typeof global.SalesDateRangePicker.init !== 'function') {
      return;
    }
    global.SalesDateRangePicker.init({
      wrapId: 'hres-date-range-wrap',
      triggerId: 'hres-date-range-trigger',
      backdropId: 'hres-date-range-backdrop',
      panelId: 'hres-date-range-panel',
      displayId: 'hres-date-range-display',
      fromInputId: 'hres-date-from',
      toInputId: 'hres-date-to',
      applyId: 'hres-date-range-apply',
      prevId: 'hres-cal-prev',
      nextId: 'hres-cal-next',
      title0Id: 'hres-cal-title0',
      title1Id: 'hres-cal-title1',
      grid0Id: 'hres-cal-grid0',
      grid1Id: 'hres-cal-grid1',
      emptyLabel: 'Select date…',
      onApply: function () {
        setDateRangeFilteredClass();
        loadReservations({ silent: true });
      }
    });
    if (typeof global.SalesDateRangePicker.syncChipDisplays === 'function') {
      global.SalesDateRangePicker.syncChipDisplays();
    }
  }

  function onRoomGridClickCapture(event) {
    var roomOpt =
      event.target &&
      event.target.closest &&
      event.target.closest('.hres-room-option[data-room-id]');
    if (!roomOpt) return;
    var root = pageRoot();
    if (!root || !root.contains(roomOpt)) return;
    event.preventDefault();
    event.stopPropagation();
    if (typeof event.stopImmediatePropagation === 'function') {
      event.stopImmediatePropagation();
    }
    closeAssignModal();
    var selectedRow = findRow(state.selectedId);
    if (!canAssignReservation(selectedRow)) {
      showToast('Cancelled reservations cannot be assigned a room.');
      return;
    }
    toggleSelectedRoom(roomOpt.getAttribute('data-room-id') || '', selectedRow);
    paintRoomSelection(selectedRow);
  }

  function bindRoomGridCapture() {
    if (global._hresRoomCapture) {
      document.removeEventListener('click', global._hresRoomCapture, true);
    }
    global._hresRoomCapture = onRoomGridClickCapture;
    document.addEventListener('click', onRoomGridClickCapture, true);
  }

  function initHotelReservationsPage() {
    var root = pageRoot();
    if (!root) return;
    bindRoomGridCapture();
    bindOnce(root);
    initDateRangePicker();
    bindTableSort(root);
    paintKpiActive();
    if (typeof global.initEpListboxes === 'function') {
      global.initEpListboxes();
    }
    loadReservations();
    startAutoRefresh();
  }

  global.initHotelReservationsPage = initHotelReservationsPage;
  global.stopHotelReservationsAutoRefresh = stopAutoRefresh;
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initHotelReservationsPage);
  } else {
    initHotelReservationsPage();
  }
})(window);
