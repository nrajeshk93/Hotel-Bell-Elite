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
    bound: false
  };

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

  function dateFilterIso(root) {
    var hidden =
      document.getElementById('hres-date-filter') ||
      (root && root.querySelector('#hres-date-filter'));
    if (hidden && hidden.value) return String(hidden.value).slice(0, 10);
    return '';
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

  function statusClass(status) {
    return 'is-' + String(status || 'upcoming').replace(/\s+/g, '_');
  }

  function renderRows(rows) {
    var body = document.getElementById('hres-table-body');
    if (!body) return;
    state.rows = Array.isArray(rows) ? rows : [];
    if (!state.rows.length) {
      body.innerHTML =
        '<tr class="hres-empty-row"><td colspan="6">No reservations match these filters.</td></tr>';
      return;
    }
    body.innerHTML = state.rows
      .map(function (row) {
        var selected =
          state.selectedId && state.selectedId === row.id ? ' is-selected' : '';
        return (
          '<tr data-res-id="' +
          escapeAttr(row.id) +
          '" class="' +
          selected.trim() +
          '">' +
          '<td><div class="hres-guest">' +
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
          '<td><div class="hres-datetime"><strong>' +
          escapeHtml(formatDisplayDate(row.checkInDate)) +
          '</strong><span>' +
          escapeHtml(formatTime(row.checkInTime)) +
          '</span></div></td>' +
          '<td><div class="hres-datetime"><strong>' +
          escapeHtml(formatDisplayDate(row.checkOutDate)) +
          '</strong><span>' +
          escapeHtml(formatTime(row.checkOutTime)) +
          '</span></div></td>' +
          '<td><div class="hres-price"><strong>' +
          escapeHtml(formatInr(row.amount)) +
          '</strong><span>' +
          escapeHtml(String(row.nights || 1)) +
          ' Night' +
          (Number(row.nights) === 1 ? '' : 's') +
          '</span></div></td>' +
          '<td><span class="hres-status-pill ' +
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
  }

  function renderPagination(pagination) {
    var meta = document.getElementById('hres-pagination-meta');
    if (!meta) return;
    state.pagination = pagination || null;
    var total = pagination && pagination.total != null ? Number(pagination.total) : 0;
    meta.textContent =
      total + ' reservation' + (total === 1 ? '' : 's');
  }

  function findRow(id) {
    var i;
    for (i = 0; i < state.rows.length; i++) {
      if (state.rows[i].id === id) return state.rows[i];
    }
    return null;
  }

  function renderRoomGrid(reservation) {
    var grid = document.getElementById('hres-room-grid');
    var assignBtn = document.getElementById('hres-assign-btn');
    if (!grid) return;
    var rooms = state.vacantRooms || [];
    if (!rooms.length) {
      grid.innerHTML =
        '<div class="hres-room-empty">No vacant rooms available right now.</div>';
      if (assignBtn) assignBtn.disabled = true;
      return;
    }
    grid.innerHTML = rooms
      .map(function (room) {
        var selected =
          state.selectedRoomId && state.selectedRoomId === room.id
            ? ' is-selected'
            : '';
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
          '<span class="hres-room-vacant">VACANT</span>' +
          '</button>'
        );
      })
      .join('');
    if (assignBtn) {
      assignBtn.disabled = !(
        state.selectedRoomId &&
        reservation &&
        reservation.status !== 'checked_out'
      );
    }
  }

  function openDetail(row) {
    var panel = document.getElementById('hres-detail');
    if (!panel || !row) return;
    state.selectedId = row.id;
    state.selectedRoomId = row.roomId || '';
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
        ['Total Amount', formatInr(row.amount)],
        ['Source', row.sourceLabel || row.source || '—']
      ];
      dl.innerHTML = fields
        .map(function (pair) {
          return (
            '<div><dt>' +
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
    var source = filterValue('hres-source-filter') || 'all';
    var onDate = dateFilterIso(root);
    if (q) params.set('q', q);
    if (status) params.set('status', status);
    if (source) params.set('source', source);
    if (onDate) params.set('date', onDate);

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
    modal.hidden = false;
    modal.setAttribute('aria-hidden', 'false');
  }

  function closeEditModal() {
    var modal = document.getElementById('hres-edit-modal');
    if (!modal) return;
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
      status: filterValue('hres-edit-status') || 'upcoming'
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
      loadReservations();
    };
    global.hresSourceChanged = function () {
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
      var refresh = event.target.closest('#hres-refresh-btn');
      if (refresh) {
        event.preventDefault();
        loadReservations();
        showToast('Refreshed');
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

      var roomOpt = event.target.closest('.hres-room-option[data-room-id]');
      if (roomOpt) {
        event.preventDefault();
        state.selectedRoomId = roomOpt.getAttribute('data-room-id') || '';
        var row = findRow(state.selectedId);
        renderRoomGrid(row);
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

    var form = document.getElementById('hres-edit-form');
    if (form) form.addEventListener('submit', saveEditForm);

    /* Date picker change — hotel date field dispatches input/change on hidden iso */
    root.addEventListener('change', function (event) {
      var t = event.target;
      if (!t) return;
      if (
        t.id === 'hres-date-filter' ||
        (t.closest && t.closest('#hres-date-filter-chip'))
      ) {
        loadReservations({ silent: true });
      }
    });
    root.addEventListener('hotel-date-change', function () {
      loadReservations({ silent: true });
    });
  }

  function initHotelReservationsPage() {
    var root = pageRoot();
    if (!root) return;
    bindOnce(root);
    if (typeof global.initEpListboxes === 'function') {
      global.initEpListboxes();
    }
    if (typeof global.initHotelDatePickers === 'function') {
      global.initHotelDatePickers(root);
    }
    loadReservations();
  }

  global.initHotelReservationsPage = initHotelReservationsPage;
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initHotelReservationsPage);
  } else {
    initHotelReservationsPage();
  }
})(window);
