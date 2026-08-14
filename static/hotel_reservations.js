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
    selectedRoomId: '',
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
    checkoutOnly: false
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
        '₹ ' +
        n.toLocaleString('en-IN', {
          maximumFractionDigits: 0
        })
      );
    } catch (e) {
      return '₹ ' + String(Math.round(n));
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
      var coverage = String(sync.coverage || '').trim();
      text.textContent =
        'Last synced from Asia Tech at ' +
        syncedAt +
        (coverage ? '. ' + coverage : '');
      scheduleSyncBannerHide();
      return;
    }
    if (source === 'asia_tech') {
      banner.hidden = false;
      banner.removeAttribute('hidden');
      banner.classList.remove('is-error');
      banner.classList.add('is-ok', 'is-visible');
      text.textContent =
        String(sync.coverage || '').trim() || 'Last synced from Asia Tech';
      scheduleSyncBannerHide();
      return;
    }
    hideSyncBanner();
  }

  function statusClass(status) {
    return 'is-' + String(status || 'upcoming').replace(/\s+/g, '_');
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
        '<tr class="hres-empty-row"><td colspan="6">' +
        escapeHtml(emptyMsg) +
        '</td></tr>';
      return;
    }
    body.innerHTML = state.rows
      .map(function (row) {
        var selected =
          state.selectedId && state.selectedId === row.id ? ' is-selected' : '';
        return (
          '<tr data-res-id="' +
          escapeAttr(row.id) +
          '" data-sort-row class="' +
          selected.trim() +
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
          '<div class="hres-guest-meta">' +
          escapeHtml(row.mobile || '') +
          (row.email ? ' · ' + escapeHtml(row.email) : '') +
          '</div></div></div></td>' +
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
          '">' +
          escapeHtml(row.statusLabel || row.status) +
          '</span></td>' +
          '<td><div class="hres-row-actions">' +
          '<button type="button" class="hres-icon-btn" data-hres-view title="View">' +
          '<svg viewBox="0 0 24 24"><path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7S1 12 1 12z"/><circle cx="12" cy="12" r="3"/></svg>' +
          '</button>' +
          '<button type="button" class="hres-icon-btn" data-hres-more title="More">' +
          '<svg viewBox="0 0 24 24"><circle cx="12" cy="5" r="1.5"/><circle cx="12" cy="12" r="1.5"/><circle cx="12" cy="19" r="1.5"/></svg>' +
          '</button>' +
          '</div></td></tr>'
        );
      })
      .join('');
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
    var rows = Array.prototype.slice.call(tbody.querySelectorAll('tr[data-sort-row]'));
    var ascending = state.sortAsc;
    rows.sort(function (a, b) {
      var av = cellSortValue(a, colIndex, type);
      var bv = cellSortValue(b, colIndex, type);
      var cmp = 0;
      if (type === 'number') cmp = av - bv;
      else cmp = String(av).localeCompare(String(bv), undefined, { numeric: true, sensitivity: 'base' });
      return ascending ? cmp : -cmp;
    });
    rows.forEach(function (row) {
      tbody.appendChild(row);
    });
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

  function renderRoomGrid(reservation) {
    var grid = document.getElementById('hres-room-grid');
    var assignBtn = document.getElementById('hres-assign-btn');
    if (!grid) return;
    var rooms = roomsForReservation(reservation);
    var canAssign = reservation && reservation.status !== 'checked_out';
    if (state.selectedRoomId) {
      var stillValid = rooms.some(function (room) {
        return sameId(room.id, state.selectedRoomId);
      });
      if (!stillValid) state.selectedRoomId = '';
    }
    if (!rooms.length) {
      grid.innerHTML =
        '<div class="hres-room-empty">No rooms available for these dates.</div>';
      if (assignBtn) assignBtn.disabled = true;
      return;
    }
    grid.innerHTML = rooms
      .map(function (room) {
        var selected = sameId(state.selectedRoomId, room.id) ? ' is-selected' : '';
        var status = String(room.status || 'vacant').toLowerCase();
        var badge = status === 'vacant' ? 'VACANT' : 'AVAILABLE';
        return (
          '<button type="button" class="hres-room-option' +
          selected +
          '" data-room-id="' +
          escapeAttr(room.id) +
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
          '</button>'
        );
      })
      .join('');
    if (assignBtn) {
      assignBtn.disabled = !(canAssign && state.selectedRoomId);
    }
    syncAssignRoomLabel(rooms);
  }

  function findRoomById(roomId) {
    var rooms = state.vacantRooms || [];
    var i;
    for (i = 0; i < rooms.length; i++) {
      if (sameId(rooms[i].id, roomId)) return rooms[i];
    }
    return null;
  }

  function syncAssignRoomLabel(rooms) {
    var label = document.getElementById('hres-assign-room-label');
    if (!label) return;
    var list = rooms || state.vacantRooms || [];
    var room = null;
    var i;
    for (i = 0; i < list.length; i++) {
      if (sameId(list[i].id, state.selectedRoomId)) {
        room = list[i];
        break;
      }
    }
    if (!room) room = findRoomById(state.selectedRoomId);
    if (!room) {
      label.textContent = 'Select a room';
      return;
    }
    label.textContent =
      'Room ' +
      (room.number || '') +
      (room.roomTypeLabel || room.roomType
        ? ' · ' + (room.roomTypeLabel || room.roomType)
        : '');
  }

  function openAssignModal() {
    var modal = document.getElementById('hres-assign-modal');
    if (!modal) return;
    modal.hidden = false;
    modal.setAttribute('aria-hidden', 'false');
    var assignBtn = document.getElementById('hres-assign-btn');
    var row = findRow(state.selectedId);
    if (assignBtn) {
      assignBtn.disabled = !(
        state.selectedRoomId &&
        row &&
        row.status !== 'checked_out'
      );
    }
    syncAssignRoomLabel(roomsForReservation(row));
  }

  function closeAssignModal() {
    var modal = document.getElementById('hres-assign-modal');
    if (!modal) return;
    modal.hidden = true;
    modal.setAttribute('aria-hidden', 'true');
  }

  function openDetail(row) {
    var panel = document.getElementById('hres-detail');
    if (!panel || !row) return;
    closeAssignModal();
    state.selectedId = row.id;
    state.selectedRoomId = '';
    panel.hidden = false;

    var avatar = document.getElementById('hres-detail-avatar');
    var guest = document.getElementById('hres-detail-guest');
    var booking = document.getElementById('hres-detail-booking');
    var status = document.getElementById('hres-detail-status');
    var dl = document.getElementById('hres-detail-dl');
    var payment = document.getElementById('hres-detail-payment');
    var amount = document.getElementById('hres-detail-amount');

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
    renderRoomGrid(row);
    document.querySelectorAll('#hres-table-body tr[data-res-id]').forEach(function (tr) {
      tr.classList.toggle('is-selected', tr.getAttribute('data-res-id') === row.id);
    });
  }

  function closeDetail() {
    closeAssignModal();
    var panel = document.getElementById('hres-detail');
    if (panel) panel.hidden = true;
    state.selectedId = '';
    state.selectedRoomId = '';
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
        '<tr class="hres-empty-row"><td colspan="6">Loading reservations…</td></tr>';
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
          if (row) openDetail(row);
          else closeDetail();
        }
      })
      .catch(function () {
        if (gen !== state.loadGen) return;
        if (body) {
          body.innerHTML =
            '<tr class="hres-empty-row"><td colspan="6">Could not load reservations.</td></tr>';
        }
        paintSyncBanner(
          { error: 'Could not load reservations from the server.' },
          'stub',
          opts
        );
        showToast('Could not load reservations');
      });
  }

  function openEditModal(row) {
    var modal = document.getElementById('hres-edit-modal');
    var title = document.getElementById('hres-edit-title');
    if (!modal) return;
    var isEdit = !!(row && row.id);
    if (title) title.textContent = isEdit ? 'Edit Reservation' : 'New Reservation';
    document.getElementById('hres-edit-id').value = isEdit ? row.id : '';
    document.getElementById('hres-edit-guest').value = isEdit ? row.guestName || '' : '';
    document.getElementById('hres-edit-mobile').value = isEdit ? row.mobile || '' : '';
    document.getElementById('hres-edit-email').value = isEdit ? row.email || '' : '';
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
    document.getElementById('hres-edit-status').value = isEdit
      ? row.status || 'upcoming'
      : 'upcoming';
    fillMealPlanSelect(isEdit ? row.mealPlan : '');
    document.getElementById('hres-edit-notes').value = isEdit
      ? row.specialNotes || ''
      : '';
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
  }

  function saveEditForm(event) {
    event.preventDefault();
    var root = pageRoot();
    if (!root) return;
    var id = filterValue('hres-edit-id');
    var payload = {
      guestName: filterValue('hres-edit-guest'),
      mobile: filterValue('hres-edit-mobile'),
      email: filterValue('hres-edit-email'),
      checkInDate: filterValue('hres-edit-checkin'),
      checkOutDate: filterValue('hres-edit-checkout'),
      guests: Number(filterValue('hres-edit-guests') || 1),
      amount: Number(filterValue('hres-edit-amount') || 0),
      source: filterValue('hres-edit-source') || 'direct',
      status: filterValue('hres-edit-status') || 'upcoming',
      mealPlan: filterValue('hres-edit-meal'),
      specialNotes: filterValue('hres-edit-notes')
    };
    if (!payload.guestName || !payload.checkInDate || !payload.checkOutDate) {
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
    if (!root || !state.selectedId || !state.selectedRoomId) return;
    var assignBtn = document.getElementById('hres-assign-btn');
    if (assignBtn) assignBtn.disabled = true;
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
        body: JSON.stringify({ roomId: state.selectedRoomId })
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
        loadReservations({ silent: true });
      })
      .catch(function (err) {
        showToast((err && err.message) || 'Could not assign room');
        if (assignBtn) assignBtn.disabled = false;
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
    if (search) {
      var searchTimer = null;
      search.addEventListener('input', function () {
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

      var roomOpt = event.target.closest('.hres-room-option[data-room-id]');
      if (roomOpt) {
        event.preventDefault();
        state.selectedRoomId = roomOpt.getAttribute('data-room-id') || '';
        var row = findRow(state.selectedId);
        renderRoomGrid(row);
        openAssignModal();
        return;
      }

      var assignBtn = event.target.closest('#hres-assign-btn');
      if (assignBtn) {
        event.preventDefault();
        assignSelectedRoom();
        return;
      }

      var editBtn = event.target.closest('#hres-edit-btn');
      if (editBtn) {
        event.preventDefault();
        closeAssignModal();
        openEditModal(findRow(state.selectedId));
        return;
      }

      var viewBtn = event.target.closest('[data-hres-view]');
      var moreBtn = event.target.closest('[data-hres-more]');
      var tr = event.target.closest('tr[data-res-id]');
      if (viewBtn || moreBtn || tr) {
        var id =
          (tr && tr.getAttribute('data-res-id')) ||
          (viewBtn &&
            viewBtn.closest('tr') &&
            viewBtn.closest('tr').getAttribute('data-res-id')) ||
          '';
        if (id) {
          event.preventDefault();
          var found = findRow(id);
          if (found) openDetail(found);
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
    if (form) form.addEventListener('submit', saveEditForm);

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

  function initHotelReservationsPage() {
    var root = pageRoot();
    if (!root) return;
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
