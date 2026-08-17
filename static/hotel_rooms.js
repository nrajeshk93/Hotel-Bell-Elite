/**
 * Hotel → Rooms floor board.
 * Soft-nav safe: expose window.initHotelRoomsPage and re-bind idempotently.
 */
(function (global) {
  'use strict';

  var ROOMS_API = '/hotel/api/rooms';
  var STATUS_KEYS = ['vacant', 'occupied', 'reserved', 'dirty', 'out_of_order'];
  var STATUS_LABELS = {
    vacant: 'Vacant',
    occupied: 'Occupied',
    reserved: 'Reserved',
    dirty: 'Dirty',
    out_of_order: 'Out of order'
  };
  var TYPE_PILLS = [
    { key: 'premium_deluxe_balcony', label: 'Deluxe with Balcony' },
    { key: 'premium_without_balcony', label: 'Premium Room' },
    { key: 'premium_suite_tub', label: 'Suite Room' }
  ];
  var currentLayout = { floors: [], rooms: [] };
  var openMenu = null;
  var boundRoot = null;
  var roomMenuScrollGuardUntil = 0;

  function $(sel, root) {
    return (root || document).querySelector(sel);
  }

  function $all(sel, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(sel));
  }

  function normalize(value) {
    return String(value || '').trim().toLowerCase();
  }

  function escapeHtml(str) {
    return String(str || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function apiHeaders(extra) {
    var headers = {
      Accept: 'application/json',
      'X-Requested-With': 'XMLHttpRequest'
    };
    if (extra) {
      Object.keys(extra).forEach(function (k) {
        headers[k] = extra[k];
      });
    }
    return headers;
  }

  function resolveApi() {
    var el = document.getElementById('hotel-rooms-page');
    var api = (el && el.getAttribute('data-hotel-rooms-api')) || '/hotel/api/rooms';
    ROOMS_API = String(api).replace(/\/$/, '') || '/hotel/api/rooms';
    return ROOMS_API;
  }

  function mapStatus(status) {
    var s = normalize(status).replace(/\s+/g, '_').replace(/-/g, '_');
    if (s === 'available' || s === 'free' || s === 'clean') return 'vacant';
    if (s === 'ooo' || s === 'oos' || s === 'out_of_service') return 'out_of_order';
    if (STATUS_KEYS.indexOf(s) === -1) return 'vacant';
    return s;
  }

  function floorNameById(floors, floorId) {
    var i;
    for (i = 0; i < (floors || []).length; i++) {
      if (floors[i].id === floorId) return floors[i].name || floors[i].id;
    }
    return floorId || 'Floor';
  }

  function staySearchText(stay) {
    if (!stay || typeof stay !== 'object') return '';
    var parts = [
      stay.guestName || stay.guest_name,
      stay.firstName || stay.first_name,
      stay.lastName || stay.last_name,
      stay.mobile,
      stay.email,
      stay.agencyName || stay.agency_name,
      stay.bookingNumber || stay.booking_number
    ];
    var extras = stay.additionalGuests || stay.additional_guests || [];
    if (Array.isArray(extras)) {
      extras.forEach(function (guest) {
        if (!guest || typeof guest !== 'object') return;
        parts.push(guest.name || guest.guestName || guest.guest_name || '');
      });
    }
    return parts
      .map(function (part) {
        return String(part || '').trim();
      })
      .filter(Boolean)
      .join(' ');
  }

  function guestDisplayName(stay) {
    if (!stay || typeof stay !== 'object') return '';
    var name = String(stay.guestName || stay.guest_name || '').trim();
    if (name) return name;
    var parts = [
      stay.title,
      stay.firstName || stay.first_name,
      stay.lastName || stay.last_name
    ]
      .map(function (part) {
        return String(part || '').trim();
      })
      .filter(Boolean);
    return parts.join(' ');
  }

  /** Own guest first; empty rooms fall back to the billing primary, then any peer. */
  function guestNameForBoardRoom(room, allRooms) {
    return guestDisplayName(guestStayForBoardRoom(room, allRooms));
  }

  function guestStayForBoardRoom(room, allRooms) {
    var own = room && room.stay && typeof room.stay === 'object' ? room.stay : null;
    if (guestDisplayName(own)) return own;
    var groupId = room && room.mergeGroupId ? String(room.mergeGroupId) : '';
    if (!groupId) return own;
    var rooms = allRooms || [];
    var primaryStay = null;
    var peerStay = own;
    var i;
    for (i = 0; i < rooms.length; i++) {
      var peer = rooms[i];
      if (!peer || peer.id === room.id) continue;
      if (String(peer.mergeGroupId || '') !== groupId) continue;
      var stay = peer.stay && typeof peer.stay === 'object' ? peer.stay : null;
      var isPrimary = !!(peer.isMergePrimary && !peer.isMergeMember);
      if (isPrimary && guestDisplayName(stay)) {
        primaryStay = stay;
      }
      if (guestDisplayName(stay) && !guestDisplayName(peerStay)) {
        peerStay = stay;
      } else if (!peerStay && stay) {
        peerStay = stay;
      }
    }
    if (primaryStay) return primaryStay;
    return peerStay;
  }

  function formatGuestTipDate(iso) {
    var raw = String(iso || '').trim().slice(0, 10);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(raw)) return '';
    var parts = raw.split('-');
    var y = Number(parts[0]);
    var m = Number(parts[1]);
    var d = Number(parts[2]);
    var months = [
      'Jan',
      'Feb',
      'Mar',
      'Apr',
      'May',
      'Jun',
      'Jul',
      'Aug',
      'Sep',
      'Oct',
      'Nov',
      'Dec'
    ];
    if (!y || !m || !d || m < 1 || m > 12) return raw;
    return String(d).padStart(2, '0') + ' ' + months[m - 1] + ' ' + y;
  }

  function formatGuestTipPhone(stay) {
    if (!stay || typeof stay !== 'object') return '';
    var mobile = String(stay.mobile || '').trim();
    if (!mobile) return '';
    var country = String(stay.mobileCountry || stay.mobile_country || '').trim();
    if (country && mobile.indexOf('+') !== 0) {
      return (country.charAt(0) === '+' ? country : '+' + country) + ' ' + mobile;
    }
    return mobile;
  }

  function formatGuestTipParty(stay) {
    if (!stay || typeof stay !== 'object') return '';
    var adults = Number(stay.adults);
    var children = Number(stay.children);
    if (!isFinite(adults) || adults < 0) adults = 0;
    if (!isFinite(children) || children < 0) children = 0;
    if (!adults && !children) return '';
    var parts = [];
    if (adults) parts.push(adults + (adults === 1 ? ' Adult' : ' Adults'));
    if (children) parts.push(children + (children === 1 ? ' Child' : ' Children'));
    return parts.join(' · ');
  }

  function isVipStay(stay) {
    if (!stay || typeof stay !== 'object') return false;
    var vip = stay.vipStatus != null ? stay.vipStatus : stay.vip_status;
    if (vip === true || vip === 1 || vip === '1') return true;
    var text = String(vip || '').trim().toLowerCase();
    return text === 'vip' || text === 'yes' || text === 'true';
  }

  function guestTipRowHtml(iconSvg, label, value) {
    if (!value) return '';
    return (
      '<div class="hotel-room-guest-tip-row">' +
      '<span class="hotel-room-guest-tip-ico" aria-hidden="true">' +
      iconSvg +
      '</span>' +
      '<span class="hotel-room-guest-tip-label">' +
      escapeHtml(label) +
      '</span>' +
      '<span class="hotel-room-guest-tip-value">' +
      escapeHtml(value) +
      '</span>' +
      '</div>'
    );
  }

  function guestTipHtml(stay, guestName) {
    var name = String(guestName || guestDisplayName(stay) || '').trim();
    if (!name) return '';
    var checkIn = formatGuestTipDate(
      stay && (stay.checkInDate || stay.check_in_date)
    );
    var checkOutRaw = stay && (stay.checkOutDate || stay.check_out_date || stay.expectedCheckOut);
    var checkOut = formatGuestTipDate(checkOutRaw);
    if (checkOut) {
      var outTime = String(
        (stay && (stay.checkOutTime || stay.check_out_time)) || '11:00 AM'
      ).trim();
      checkOut = checkOut + ' (' + outTime + ')';
    }
    var party = formatGuestTipParty(stay);
    var phone = formatGuestTipPhone(stay);
    var booking = String(
      (stay && (stay.bookingNumber || stay.booking_number)) || ''
    ).trim();
    var vip = isVipStay(stay);
    var icoCal =
      '<svg viewBox="0 0 24 24"><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/></svg>';
    var icoClock =
      '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8"/><path d="M12 8v5l3 2"/></svg>';
    var icoPeople =
      '<svg viewBox="0 0 24 24"><circle cx="9" cy="8" r="3"/><path d="M3 19c0-3 2.5-5 6-5s6 2 6 5"/><circle cx="17" cy="9" r="2.5"/><path d="M16 19c.5-2 2-3.5 4.5-3.5"/></svg>';
    var icoPhone =
      '<svg viewBox="0 0 24 24"><path d="M8 3h3l1 4-2 1a12 12 0 0 0 5 5l1-2 4 1v3a2 2 0 0 1-2 2A14 14 0 0 1 6 5a2 2 0 0 1 2-2z"/></svg>';
    var icoId =
      '<svg viewBox="0 0 24 24"><rect x="3" y="5" width="18" height="14" rx="2"/><circle cx="9" cy="12" r="2.2"/><path d="M13.5 10.5h5M13.5 13.5h4"/></svg>';
    var rows =
      guestTipRowHtml(icoCal, 'Check-in', checkIn) +
      guestTipRowHtml(icoClock, 'Check-out', checkOut) +
      guestTipRowHtml(icoPeople, 'Guests', party) +
      guestTipRowHtml(icoPhone, 'Phone', phone) +
      guestTipRowHtml(icoId, 'Booking ID', booking);
    return (
      '<div class="hotel-room-guest-tip" role="tooltip">' +
      '<div class="hotel-room-guest-tip-card">' +
      '<div class="hotel-room-guest-tip-head">' +
      '<span class="hotel-room-guest-tip-avatar" aria-hidden="true">' +
      '<svg viewBox="0 0 24 24"><circle cx="12" cy="9" r="3.2"/><path d="M6.5 18.5c1.6-2.6 3.7-3.8 5.5-3.8s3.9 1.2 5.5 3.8"/></svg>' +
      '</span>' +
      '<div class="hotel-room-guest-tip-title">' +
      '<span class="hotel-room-guest-tip-name">' +
      escapeHtml(name) +
      '</span>' +
      (vip ? '<span class="hotel-room-guest-tip-vip">VIP</span>' : '') +
      '</div>' +
      '</div>' +
      (rows
        ? '<div class="hotel-room-guest-tip-rows">' + rows + '</div>'
        : '') +
      '</div>' +
      '</div>'
    );
  }

  function clearGuestTipPosition(tip) {
    if (!tip) return;
    tip.classList.remove(
      'hotel-room-guest-tip--fixed',
      'hotel-room-guest-tip--left',
      'hotel-room-guest-tip--measuring'
    );
    tip.style.top = '';
    tip.style.left = '';
    tip.style.right = '';
    tip.style.bottom = '';
    tip.style.transform = '';
    tip.style.width = '';
  }

  function positionGuestTip(tile) {
    if (!tile) return;
    var tip = tile.querySelector('.hotel-room-guest-tip');
    if (!tip) return;
    var rect = tile.getBoundingClientRect();
    tip.classList.add('hotel-room-guest-tip--fixed', 'hotel-room-guest-tip--measuring');
    tip.classList.remove('hotel-room-guest-tip--left');
    tip.style.left = '0px';
    tip.style.top = '0px';
    tip.style.right = 'auto';
    tip.style.transform = 'none';
    tip.style.width = '';
    var tipRect = tip.getBoundingClientRect();
    var tipW = tipRect.width || 292;
    var tipH = tipRect.height || 220;
    var gap = 12;
    var pad = 8;
    var placeLeft = rect.right + gap + tipW > window.innerWidth - pad;
    if (placeLeft && rect.left - gap - tipW < pad) {
      // Prefer the side with more room when both sides are tight.
      placeLeft = rect.left > window.innerWidth - rect.right;
    }
    var left = placeLeft ? rect.left - gap - tipW : rect.right + gap;
    left = Math.max(pad, Math.min(left, window.innerWidth - tipW - pad));
    var top = rect.top + rect.height / 2 - tipH / 2;
    top = Math.max(pad, Math.min(top, window.innerHeight - tipH - pad));
    if (placeLeft) tip.classList.add('hotel-room-guest-tip--left');
    tip.classList.remove('hotel-room-guest-tip--measuring');
    tip.style.left = Math.round(left) + 'px';
    tip.style.top = Math.round(top) + 'px';
    tip.style.width = Math.round(tipW) + 'px';
  }

  function showToast(message, isError) {
    var toast = document.getElementById('hotel-rooms-toast');
    if (!toast) return;
    toast.textContent = message || '';
    toast.hidden = !message;
    toast.classList.toggle('is-error', !!isError);
    if (!message) return;
    clearTimeout(showToast._timer);
    showToast._timer = setTimeout(function () {
      toast.hidden = true;
      toast.textContent = '';
    }, 2800);
  }

  function restoreRoomMenuHome(menu) {
    if (!menu) return;
    var home = menu.__hotelMenuHome;
    if (home && home.isConnected && menu.parentNode !== home) {
      try {
        home.appendChild(menu);
      } catch (err) {}
    } else if ((!home || !home.isConnected) && menu.parentNode) {
      /* Tile was re-rendered while menu was portaled — drop the orphan. */
      try {
        menu.parentNode.removeChild(menu);
      } catch (err) {}
    }
    menu.__hotelMenuHome = null;
    menu.__hotelMenuTile = null;
    menu.__menuBtn = null;
  }

  function closeRoomMenu() {
    $all('.hotel-room-menu').forEach(function (menu) {
      menu.hidden = true;
      menu.setAttribute('hidden', '');
      menu.classList.remove('is-fixed-open');
      menu.style.position = '';
      menu.style.top = '';
      menu.style.left = '';
      menu.style.right = '';
      menu.style.bottom = '';
      menu.style.inset = '';
      menu.style.zIndex = '';
      restoreRoomMenuHome(menu);
    });
    $all('.hotel-room-more[aria-expanded="true"]').forEach(function (btn) {
      btn.setAttribute('aria-expanded', 'false');
    });
    $all('.hotel-room-tile.is-menu-open').forEach(function (tile) {
      tile.classList.remove('is-menu-open');
    });
    openMenu = null;
    document.__hotelRoomsOpenMenu = null;
  }

  function positionRoomMenu(btn, menu) {
    var rect = btn.getBoundingClientRect();
    menu.style.position = 'fixed';
    menu.style.right = 'auto';
    menu.style.bottom = 'auto';
    menu.style.zIndex = '5000';
    menu.classList.add('is-fixed-open');

    var pad = 8;
    var width = menu.offsetWidth || 168;
    var height = menu.offsetHeight || 190;
    var left = rect.right - width;
    if (left < pad) left = pad;
    if (left + width > window.innerWidth - pad) {
      left = Math.max(pad, window.innerWidth - width - pad);
    }
    var top = rect.bottom + 4;
    if (top + height > window.innerHeight - pad) {
      top = Math.max(pad, rect.top - height - 4);
    }
    menu.style.left = left + 'px';
    menu.style.top = top + 'px';
  }

  function resolveRoomMenu(tile, moreBtn) {
    var portaled =
      (openMenu && openMenu.__hotelMenuTile === tile && openMenu) ||
      (document.__hotelRoomsOpenMenu &&
        document.__hotelRoomsOpenMenu.__hotelMenuTile === tile &&
        document.__hotelRoomsOpenMenu);
    if (portaled && portaled.isConnected) return portaled;
    var local =
      (tile && tile.querySelector('.hotel-room-menu')) ||
      (moreBtn &&
        moreBtn.parentElement &&
        moreBtn.parentElement.querySelector('.hotel-room-menu'));
    if (local) return local;
    /* Recreate if a prior portal/orphan cleanup removed the menu node. */
    var home = moreBtn && moreBtn.parentElement;
    if (!home) return null;
    var menu = document.createElement('div');
    menu.className = 'hotel-room-menu';
    menu.setAttribute('role', 'menu');
    menu.hidden = true;
    menu.setAttribute('hidden', '');
    home.appendChild(menu);
    return menu;
  }

  function openRoomMenu(btn, menu) {
    closeRoomMenu();
    if (!btn || !menu) return;
    var tile = btn.closest('[data-room-tile]');
    if (tile) {
      var room = findRoomInLayout(tile.getAttribute('data-id'));
      if (room) {
        menu.innerHTML = roomMenuHtml(room, mapStatus(room.status));
      }
    }
    /* Portal out of the tile so overflow / later tiles / transforms cannot clip it. */
    menu.__hotelMenuHome = menu.parentNode;
    menu.__hotelMenuTile = tile;
    menu.__menuBtn = btn;
    var host = document.getElementById('de-fs-app') || document.body;
    host.appendChild(menu);
    if (tile) tile.classList.add('is-menu-open');
    menu.hidden = false;
    menu.removeAttribute('hidden');
    btn.setAttribute('aria-expanded', 'true');
    openMenu = menu;
    document.__hotelRoomsOpenMenu = menu;
    positionRoomMenu(btn, menu);
    /* Opening can nudge layout/scroll; ignore that brief scroll so the menu stays open. */
    roomMenuScrollGuardUntil = Date.now() + 450;
  }

  function tileForRoomMenu(menu) {
    if (!menu) return null;
    if (menu.__hotelMenuTile && menu.__hotelMenuTile.isConnected) return menu.__hotelMenuTile;
    if (menu.__hotelMenuHome) return menu.__hotelMenuHome.closest('[data-room-tile]');
    return menu.closest('[data-room-tile]');
  }

  function paintKpis(root, counts) {
    var data = counts || {};
    var metaHint = {
      vacant: 'ready to sell',
      occupied: 'in house',
      dirty: 'housekeeping'
    };
    $all('.hotel-kpi', root).forEach(function (card) {
      var key = card.getAttribute('data-kpi');
      var el = card.querySelector('[data-kpi-value]');
      if (!el || !key) return;
      var n = Number(data[key] != null ? data[key] : 0);
      if (!isFinite(n) || n < 0) n = 0;
      el.textContent = String(n);
      var meta = card.querySelector('[data-kpi-meta]');
      if (meta) {
        if (key === 'total') {
          meta.textContent = 'On property';
        } else if (key === 'expected_checkout') {
          meta.textContent = 'Selected date';
        } else if (metaHint[key]) {
          meta.textContent = n + (n === 1 ? ' room · ' : ' rooms · ') + metaHint[key];
        }
      }
      if (key === 'dirty') {
        card.hidden = n <= 0;
        if (n <= 0 && card.classList.contains('is-active')) {
          global.setTimeout(function () {
            if (statusFilterValue(root) === 'dirty') setStatusFilter(root, 'all');
          }, 0);
        }
      }
    });
  }

  function emptyCounts() {
    var counts = { total: 0, expected_checkout: 0 };
    STATUS_KEYS.forEach(function (k) {
      counts[k] = 0;
    });
    return counts;
  }

  function roomCheckOutISO(room) {
    var stay = room && room.stay && typeof room.stay === 'object' ? room.stay : null;
    if (!stay) return '';
    return toDateISO(stay.checkOutDate || stay.check_out_date || stay.expectedCheckOut || '');
  }

  function isExpectedCheckoutRoom(room, dateIso) {
    if (!room) return false;
    if (mapStatus(room.status) !== 'occupied') return false;
    var day = toDateISO(dateIso) || todayISO();
    var checkOut = roomCheckOutISO(room);
    return !!(checkOut && checkOut === day);
  }

  function tileIsExpectedCheckout(tile, dateIso) {
    if (!tile) return false;
    var day = toDateISO(dateIso) || todayISO();
    var effective = mapStatus(
      tile.getAttribute('data-effective-status') ||
        tile.getAttribute('data-inventory-status') ||
        tile.getAttribute('data-status')
    );
    if (effective !== 'occupied') return false;
    var checkOut = toDateISO(tile.getAttribute('data-check-out'));
    return !!(checkOut && checkOut === day);
  }

  /* Board guest tip defaults expected checkout to 11:00 AM when stay has no time. */
  var DEFAULT_CHECK_OUT_TIME = '11:00';

  function parseClockToMinutes(value) {
    var raw = String(value || '').trim();
    if (!raw) return null;
    var m24 = raw.match(/^(\d{1,2}):(\d{2})$/);
    if (m24) {
      var h24 = Number(m24[1]);
      var min24 = Number(m24[2]);
      if (h24 > 23 || min24 > 59) return null;
      return h24 * 60 + min24;
    }
    var m12 = raw.match(/^(\d{1,2}):(\d{2})\s*([AaPp][Mm])$/);
    if (!m12) return null;
    var hour = Number(m12[1]);
    var minute = Number(m12[2]);
    var ap = m12[3].toUpperCase();
    if (hour < 1 || hour > 12 || minute > 59) return null;
    if (ap === 'AM') {
      if (hour === 12) hour = 0;
    } else if (hour !== 12) {
      hour += 12;
    }
    return hour * 60 + minute;
  }

  function isCheckoutTimePassed(checkOutTime) {
    var due = parseClockToMinutes(checkOutTime);
    if (due == null) due = parseClockToMinutes(DEFAULT_CHECK_OUT_TIME);
    var now = new Date();
    return now.getHours() * 60 + now.getMinutes() >= due;
  }

  function occupiedCheckoutIsOverdue(checkOut, dateIso, checkOutTime) {
    var day = toDateISO(dateIso) || todayISO();
    var out = toDateISO(checkOut);
    if (!out) return false;
    if (out < day) return true;
    if (out > day) return false;
    /* Same calendar day as board as-of. */
    var today = todayISO();
    if (day < today) return true;
    if (day > today) return false;
    return isCheckoutTimePassed(checkOutTime);
  }

  function tileIsOverdueAttention(tile, dateIso) {
    if (!tile) return false;
    var day = toDateISO(dateIso) || todayISO();
    var effective = mapStatus(
      tile.getAttribute('data-effective-status') ||
        tile.getAttribute('data-inventory-status') ||
        tile.getAttribute('data-status')
    );
    var checkIn = toDateISO(tile.getAttribute('data-check-in'));
    var checkOut = toDateISO(tile.getAttribute('data-check-out'));
    var checkOutTime = tile.getAttribute('data-check-out-time') || '';
    if (effective === 'occupied') {
      return occupiedCheckoutIsOverdue(checkOut, day, checkOutTime);
    }
    if (effective === 'reserved') {
      return !!(checkIn && checkIn < day);
    }
    return false;
  }

  function tileIsCheckoutDueToday(tile, dateIso) {
    if (!tileIsExpectedCheckout(tile, dateIso)) return false;
    return !tileIsOverdueAttention(tile, dateIso);
  }

  function syncTileAttention(tile, dateIso) {
    if (!tile) return '';
    var day = toDateISO(dateIso) || todayISO();
    var effective = mapStatus(
      tile.getAttribute('data-effective-status') ||
        tile.getAttribute('data-inventory-status') ||
        tile.getAttribute('data-status')
    );
    var reason = '';
    var dueToday = false;
    if (effective === 'occupied') {
      var checkOut = toDateISO(tile.getAttribute('data-check-out'));
      var checkOutTime = tile.getAttribute('data-check-out-time') || '';
      if (occupiedCheckoutIsOverdue(checkOut, day, checkOutTime)) {
        reason = 'Overdue checkout';
      } else if (checkOut && checkOut === day) {
        dueToday = true;
        reason = 'Due for checkout';
      }
    } else if (effective === 'reserved') {
      var checkIn = toDateISO(tile.getAttribute('data-check-in'));
      if (checkIn && checkIn < day) reason = 'Overdue arrival';
    }
    var overdue = reason === 'Overdue checkout' || reason === 'Overdue arrival';
    tile.classList.toggle('hotel-room-tile--attention', overdue);
    tile.setAttribute('data-attention', overdue ? '1' : '0');
    tile.classList.toggle('hotel-room-tile--checkout-due', dueToday);
    tile.setAttribute('data-checkout-due', dueToday ? '1' : '0');
    var label = String(tile.getAttribute('aria-label') || '');
    label = label
      .replace(/, Overdue checkout$/i, '')
      .replace(/, Overdue arrival$/i, '')
      .replace(/, Due for checkout$/i, '');
    if (reason) label = label + ', ' + reason;
    if (label) tile.setAttribute('aria-label', label);
    return reason;
  }

  function computeCounts(rooms) {
    var counts = emptyCounts();
    (rooms || []).forEach(function (room) {
      counts.total += 1;
      var status = mapStatus(room.status);
      counts[status] = (counts[status] || 0) + 1;
    });
    return counts;
  }

  function computeCountsFromTiles(root) {
    var counts = emptyCounts();
    var day = dateFilterValue(root);
    $all('[data-room-tile]', root).forEach(function (tile) {
      counts.total += 1;
      var status = mapStatus(
        tile.getAttribute('data-effective-status') || tile.getAttribute('data-status')
      );
      counts[status] = (counts[status] || 0) + 1;
      if (tileIsExpectedCheckout(tile, day)) {
        counts.expected_checkout += 1;
      }
    });
    return counts;
  }

  /** Count every physical room (including hidden merge members) for KPIs. */
  function computePhysicalRoomCounts(root, layout, dateIso) {
    var rooms = (layout && layout.rooms) || [];
    if (!rooms.length) return computeCountsFromTiles(root);
    var counts = emptyCounts();
    var day = dateIso || dateFilterValue(root);
    rooms.forEach(function (room) {
      counts.total += 1;
      var stay = room.stay && typeof room.stay === 'object' ? room.stay : null;
      var checkIn = stay ? String(stay.checkInDate || stay.check_in_date || '').slice(0, 10) : '';
      var checkOut = stay
        ? String(stay.checkOutDate || stay.check_out_date || stay.expectedCheckOut || '').slice(0, 10)
        : '';
      var status = effectiveStatusForDate(room.status, checkIn, checkOut, day, todayISO());
      counts[status] = (counts[status] || 0) + 1;
      if (isExpectedCheckoutRoom(room, day)) {
        counts.expected_checkout += 1;
      }
    });
    return counts;
  }

  function toDateISO(value) {
    var raw = String(value || '').trim();
    if (!raw) return '';
    if (/^\d{4}-\d{2}-\d{2}/.test(raw)) return raw.slice(0, 10);
    var dmy = raw.match(/^(\d{1,2})[\/\-.](\d{1,2})[\/\-.](\d{4})$/);
    if (dmy) {
      return (
        dmy[3] +
        '-' +
        String(dmy[2]).padStart(2, '0') +
        '-' +
        String(dmy[1]).padStart(2, '0')
      );
    }
    return '';
  }

  function stayCoversDate(checkIn, checkOut, dateIso, todayIso) {
    var day = toDateISO(dateIso);
    var inDate = toDateISO(checkIn);
    var outDate = toDateISO(checkOut);
    var today = toDateISO(todayIso) || todayISO();
    if (!day) return true;
    if (!inDate) {
      /* No stay window — inventory occupancy only applies on today. */
      return day === today;
    }
    if (day < inDate) return false;
    /* Include checkout day — guest remains in-house until FO checks them out. */
    if (outDate) return day <= outDate;
    /* Open-ended stay: in-house through today; future arrivals without checkout = 1 night. */
    if (inDate > today) return day === inDate;
    return day <= today;
  }

  function effectiveStatusForDate(inventoryStatus, checkIn, checkOut, dateIso, todayIso) {
    var inventory = mapStatus(inventoryStatus);
    var day = toDateISO(dateIso) || todayISO();
    var today = toDateISO(todayIso) || todayISO();

    /* Dirty is a same-day housekeeping state — future nights assume cleaned. */
    if (inventory === 'dirty') {
      return day === today ? 'dirty' : 'vacant';
    }
    if (inventory === 'out_of_order') return inventory;

    /* Checked-in guests stay Occupied until FO checkout — ignore date window. */
    if (inventory === 'occupied') return 'occupied';

    if (inventory === 'reserved') {
      if (stayCoversDate(checkIn, checkOut, day, today)) return 'reserved';
      return 'vacant';
    }
    return inventory;
  }

  function effectiveStatusForTile(tile, dateIso) {
    var inventory =
      tile.getAttribute('data-inventory-status') || tile.getAttribute('data-status') || 'vacant';
    return effectiveStatusForDate(
      inventory,
      tile.getAttribute('data-check-in'),
      tile.getAttribute('data-check-out'),
      dateIso,
      todayISO()
    );
  }

  function applyTileEffectiveStatus(tile, status) {
    var next = mapStatus(status);
    STATUS_KEYS.forEach(function (key) {
      tile.classList.remove('hotel-room-tile--' + key);
    });
    tile.classList.add('hotel-room-tile--' + next);
    tile.setAttribute('data-status', next);
    tile.setAttribute('data-effective-status', next);
    var badge = tile.querySelector('.hotel-room-badge');
    if (badge) badge.textContent = STATUS_LABELS[next] || next;
    syncTileSubtitle(tile);
  }

  function syncTileSubtitle(tile) {
    if (!tile) return;
    var typeEl = tile.querySelector('.hotel-room-type');
    if (!typeEl) return;
    var effective = mapStatus(
      tile.getAttribute('data-effective-status') || tile.getAttribute('data-status')
    );
    var guestName = String(tile.getAttribute('data-guest-name') || '').trim();
    var typeLabel = String(tile.getAttribute('data-room-type-label') || '').trim();
    if (guestName && (effective === 'occupied' || effective === 'reserved')) {
      typeEl.textContent = guestName;
      typeEl.classList.add('hotel-room-type--guest');
    } else {
      typeEl.textContent = typeLabel;
      typeEl.classList.remove('hotel-room-type--guest');
    }
  }

  function refreshEffectiveStatuses(root, dateIso) {
    $all('[data-room-tile]', root).forEach(function (tile) {
      applyTileEffectiveStatus(tile, effectiveStatusForTile(tile, dateIso));
      syncTileAttention(tile, dateIso);
    });
  }

  function statusFilterLabel(key) {
    if (!key || key === 'all') return 'All statuses';
    if (key === 'expected_checkout') return 'Expected Check Out';
    return STATUS_LABELS[key] || key;
  }

  function normalizeFilterKey(key) {
    var raw = normalize(key).replace(/\s+/g, '_').replace(/-/g, '_');
    if (!raw || raw === 'all') return 'all';
    if (raw === 'expected_checkout') return 'expected_checkout';
    return mapStatus(raw);
  }

  function syncStatusListbox(root, key) {
    var want = normalizeFilterKey(key);
    var input = $('#hotel-rooms-status-filter', root);
    if (input) input.value = want;
    var listbox = $('#hotel-rooms-status-listbox', root);
    if (!listbox) return;
    var valueEl = $('#hotel-rooms-status-value', root);
    if (valueEl) valueEl.textContent = statusFilterLabel(want);
    $all('.se-filter-listbox-option', listbox).forEach(function (opt) {
      var on = (opt.getAttribute('data-value') || '') === want;
      opt.classList.toggle('is-selected', on);
      opt.setAttribute('aria-selected', on ? 'true' : 'false');
    });
  }

  function syncKpiSelection(root) {
    var current = statusFilterValue(root) || 'all';
    $all('.hotel-kpi[data-kpi]', root).forEach(function (card) {
      var key = card.getAttribute('data-kpi') || '';
      var active = key === 'total' ? current === 'all' : key === current;
      card.classList.toggle('is-active', active);
      card.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
  }

  function setStatusFilter(root, key) {
    var want = normalizeFilterKey(key);
    syncStatusListbox(root, want);
    syncKpiSelection(root);
    applyFilters(root);
  }

  function renderTypePills(root) {
    var wrap = $('#hotel-floor-pills', root);
    if (!wrap) return;
    var active = '';
    var current = wrap.querySelector('.hotel-floor-pill.is-active');
    if (current) active = current.getAttribute('data-type') || '';
    var html =
      '<button type="button" class="hotel-floor-pill' +
      (active === '' ? ' is-active' : '') +
      '" data-type="" role="tab" aria-selected="' +
      (active === '' ? 'true' : 'false') +
      '">All Rooms</button>';
    TYPE_PILLS.forEach(function (item) {
      var isActive = active === item.key;
      html +=
        '<button type="button" class="hotel-floor-pill' +
        (isActive ? ' is-active' : '') +
        '" data-type="' +
        escapeHtml(item.key) +
        '" role="tab" aria-selected="' +
        (isActive ? 'true' : 'false') +
        '">' +
        escapeHtml(item.label) +
        '</button>';
    });
    wrap.innerHTML = html;
  }

  function roomMenuHtml(room, activeStatus) {
    var status = mapStatus(activeStatus || (room && room.status));
    var isMember = !!(room && room.isMergeMember);
    var isPrimary = !!(room && room.isMergePrimary);
    var inGroup = !!(
      (room && room.mergeGroupId) ||
      isMember ||
      isPrimary
    );
    var canTransfer = status === 'occupied' && !!(room && room.stay);
    var items = [];
    if (!isMember) {
      items.push(
        '<button type="button" class="hotel-room-menu-item" role="menuitem" data-room-action="merge">Merge Rooms</button>'
      );
    }
    if (canTransfer) {
      items.push(
        '<button type="button" class="hotel-room-menu-item" role="menuitem" data-room-action="extend">Extend Stay</button>'
      );
      items.push(
        '<button type="button" class="hotel-room-menu-item" role="menuitem" data-room-action="transfer">Room Transfer</button>'
      );
    }
    if (inGroup) {
      items.push(
        '<button type="button" class="hotel-room-menu-item" role="menuitem" data-room-action="unmerge">Unmerge Room</button>'
      );
    }
    if (isPrimary) {
      items.push(
        '<button type="button" class="hotel-room-menu-item" role="menuitem" data-room-action="unmerge-group">Unmerge All</button>'
      );
      items.push(
        '<button type="button" class="hotel-room-menu-item" role="menuitem" data-room-action="checkout-group">Check out all</button>'
      );
    }
    if (isMember) {
      items.push(
        '<button type="button" class="hotel-room-menu-item" role="menuitem" data-room-action="set-primary">Make Primary</button>'
      );
    }
    if (items.length) {
      items.push('<div class="hotel-room-menu-sep" role="separator"></div>');
    }
    items = items.concat(
      STATUS_KEYS.map(function (key) {
        /* Dirty rooms: offer Cleaned (→ vacant) instead of Dirty / Vacant. */
        if (status === 'dirty' && key === 'vacant') return '';
        if (status === 'occupied' && (key === 'occupied' || key === 'vacant')) return '';
        /* Already vacant — redundant to show Vacant as a status action. */
        if (key === 'vacant' && status === 'vacant') return '';
        /* Occupied is set via check-in, not the status menu. */
        if (key === 'occupied') return '';
        if (key === 'dirty' && status === 'dirty') {
          return (
            '<button type="button" class="hotel-room-menu-item" role="menuitem" data-room-action="vacant">Cleaned</button>'
          );
        }
        if (key === 'reserved' && status === 'reserved') {
          return (
            '<button type="button" class="hotel-room-menu-item" role="menuitem" data-room-action="vacant">Un Reserved</button>'
          );
        }
        var selected = key === status ? ' is-current' : '';
        var label = key === 'reserved' ? 'Reserve' : STATUS_LABELS[key];
        return (
          '<button type="button" class="hotel-room-menu-item' +
          selected +
          '" role="menuitem" data-room-action="' +
          key +
          '">' +
          escapeHtml(label) +
          '</button>'
        );
      }).filter(Boolean)
    );
    return items.join('');
  }

  function roomNumberSortKey(value) {
    var raw = String(value || '');
    var m = raw.match(/\d+/);
    return m ? Number(m[0]) : 0;
  }

  function sortRoomsByNumber(list) {
    return (Array.isArray(list) ? list.slice() : []).sort(function (a, b) {
      var an = roomNumberSortKey(a && a.number);
      var bn = roomNumberSortKey(b && b.number);
      if (an !== bn) return an - bn;
      return String((a && a.number) || '').localeCompare(
        String((b && b.number) || ''),
        undefined,
        { numeric: true }
      );
    });
  }

  function roomBoardTileHtml(room, allRooms) {
    if (!room) return '';
    var status = mapStatus(room.status);
    var stay = room.stay && typeof room.stay === 'object' ? room.stay : null;
    var tipStay = guestStayForBoardRoom(room, allRooms) || stay;
    var checkIn = tipStay
      ? String(tipStay.checkInDate || tipStay.check_in_date || '').slice(0, 10)
      : '';
    var checkOut = tipStay
      ? String(
          tipStay.checkOutDate ||
            tipStay.check_out_date ||
            tipStay.expectedCheckOut ||
            ''
        ).slice(0, 10)
      : '';
    var checkOutTime = tipStay
      ? String(tipStay.checkOutTime || tipStay.check_out_time || '').trim()
      : '';
    if (!checkOutTime) checkOutTime = DEFAULT_CHECK_OUT_TIME;
    var guestSearch = staySearchText(tipStay || stay);
    var guestName = guestDisplayName(tipStay) || guestNameForBoardRoom(room, allRooms);
    if (guestName && guestSearch.indexOf(guestName) === -1) {
      guestSearch = (guestName + ' ' + guestSearch).trim();
    }
    var typeLabel = room.roomTypeLabel || room.roomType || '';
    var showGuestSubtitle =
      !!guestName && (status === 'occupied' || status === 'reserved');
    var subtitle = showGuestSubtitle ? guestName : typeLabel;
    var isMember = !!room.isMergeMember;
    var isPrimary = !!(room.isMergePrimary && !isMember);
    var isMerged = !!(room.mergeGroupId || isPrimary || isMember);
    var partners = Array.isArray(room.mergePartnerNumbers)
      ? room.mergePartnerNumbers
      : [];
    if (
      (!partners.length || partners.length < 1) &&
      Array.isArray(room.mergePartners) &&
      room.mergePartners.length
    ) {
      partners = room.mergePartners
        .map(function (p) {
          return p && (p.number || p.roomNumber || '');
        })
        .filter(Boolean);
    }
    var mergeCount = 1;
    if (isMerged) {
      if (isPrimary && partners.length) {
        mergeCount = Math.max(1, 1 + partners.length);
      } else if (Array.isArray(room.mergePartnerNumbers)) {
        mergeCount = Math.max(1, 1 + room.mergePartnerNumbers.length);
      }
    }
    var displayNumber = room.number;
    var searchNumbers = [String(room.number || '')]
      .concat(
        isPrimary
          ? partners.map(function (n) {
              return String(n || '');
            })
          : []
      )
      .filter(Boolean)
      .join(' ');
    var mergeTagText = '';
    if (isMerged) {
      if (isMember) {
        mergeTagText =
          room.mergeLabel ||
          ('Bill: ' +
            (room.billingRoomNumber ||
              (stay && stay.billingRoomId) ||
              '—'));
      } else {
        mergeTagText = 'Merged bill';
      }
    }
    var ariaLabel =
      'Room ' +
      displayNumber +
      (guestName ? ', ' + guestName : '') +
      (isMerged ? ', merged billing' : '') +
      ', ' +
      (STATUS_LABELS[status] || status);
    return (
      '<article class="hotel-room-tile hotel-room-tile--' +
      status +
      (isMerged ? ' hotel-room-tile--merged' : '') +
      (isMember ? ' hotel-room-tile--merge-member' : '') +
      (guestName ? ' hotel-room-tile--has-guest' : '') +
      '" data-room-tile data-id="' +
      escapeHtml(room.id) +
      '" data-number="' +
      escapeHtml(room.number) +
      '" data-search-numbers="' +
      escapeHtml(searchNumbers) +
      '" data-floor="' +
      escapeHtml(room.floorId || '') +
      '" data-type="' +
      escapeHtml(room.roomType || '') +
      '" data-room-type-label="' +
      escapeHtml(typeLabel) +
      '" data-inventory-status="' +
      status +
      '" data-status="' +
      status +
      '" data-effective-status="' +
      status +
      '" data-check-in="' +
      escapeHtml(checkIn) +
      '" data-check-out="' +
      escapeHtml(checkOut) +
      '" data-check-out-time="' +
      escapeHtml(checkOutTime) +
      '" data-guest-search="' +
      escapeHtml(guestSearch) +
      '" data-guest-name="' +
      escapeHtml(guestName) +
      '" data-merge="' +
      (isMerged ? '1' : '0') +
      '" data-merge-count="' +
      mergeCount +
      '" data-merge-member="' +
      (isMember ? '1' : '0') +
      '" data-merge-primary="' +
      (isPrimary ? '1' : '0') +
      '" aria-label="' +
      escapeHtml(ariaLabel) +
      '" tabindex="0">' +
      '<div class="hotel-room-tile-top">' +
      '<span class="hotel-room-icon" aria-hidden="true">' +
      '<svg viewBox="0 0 24 24"><path d="M3 12h18v7H3z"/><path d="M5 12V8a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v4"/><path d="M8 15h.01M16 15h.01"/></svg>' +
      '</span>' +
      '<button type="button" class="hotel-room-more" aria-label="Room actions" aria-haspopup="menu" aria-expanded="false">' +
      '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="5" r="1.5"/><circle cx="12" cy="12" r="1.5"/><circle cx="12" cy="19" r="1.5"/></svg>' +
      '</button>' +
      '<div class="hotel-room-menu" role="menu" hidden>' +
      roomMenuHtml(room, status) +
      '</div>' +
      '</div>' +
      '<div class="hotel-room-number">' +
      escapeHtml(displayNumber) +
      '</div>' +
      '<div class="hotel-room-type' +
      (showGuestSubtitle ? ' hotel-room-type--guest' : '') +
      '">' +
      escapeHtml(subtitle) +
      '</div>' +
      (mergeTagText
        ? '<div class="hotel-room-merge-tag">' +
          escapeHtml(mergeTagText) +
          '</div>'
        : '') +
      '<div class="hotel-room-tile-foot">' +
      '<span class="hotel-room-badge">' +
      escapeHtml(STATUS_LABELS[status] || status) +
      '</span>' +
      '</div>' +
      (guestName ? guestTipHtml(tipStay, guestName) : '') +
      '</article>'
    );
  }

  function stayReservationDisplayId(stay) {
    if (!stay || typeof stay !== 'object') return '';
    var booking = String(stay.bookingNumber || stay.booking_number || '').trim();
    var rid = String(
      stay.reservationId ||
        stay.reservation_id ||
        stay.reservationBookingId ||
        stay.reservation_booking_id ||
        ''
    ).trim();
    if (!rid) return '';
    if (booking && rid.toLowerCase() === booking.toLowerCase()) return '';
    if (/^BK\d{8,}$/i.test(rid)) return '';
    return rid;
  }

  function mergeGroupReservationId(groupRooms, allRooms) {
    var rooms = groupRooms || [];
    var i;
    for (i = 0; i < rooms.length; i++) {
      var room = rooms[i];
      var stay = guestStayForBoardRoom(room, allRooms) || (room && room.stay);
      var rid = stayReservationDisplayId(stay);
      if (rid) return rid;
      rid = stayReservationDisplayId(room && room.stay);
      if (rid) return rid;
    }
    return '';
  }

  function mergeGroupBookingName(groupRooms, allRooms) {
    var primary =
      (groupRooms || []).find(function (r) {
        return r && r.isMergePrimary && !r.isMergeMember;
      }) ||
      (groupRooms || [])[0];
    if (!primary) return 'Booking';
    var tipStay = guestStayForBoardRoom(primary, allRooms) || primary.stay;
    var name = guestDisplayName(tipStay) || guestNameForBoardRoom(primary, allRooms);
    if (name) return name;
    var stay = primary.stay && typeof primary.stay === 'object' ? primary.stay : null;
    var booking = stay && (stay.bookingNumber || stay.booking_number);
    if (booking) return String(booking);
    return 'Room ' + (primary.number || 'Booking');
  }

  function mergeGroupSectionTitle(groupRooms, allRooms) {
    var name = mergeGroupBookingName(groupRooms, allRooms);
    var rid = mergeGroupReservationId(groupRooms, allRooms);
    if (rid && String(name || '').toLowerCase() !== rid.toLowerCase()) {
      return String(name || 'Booking') + ' (' + rid + ')';
    }
    return name;
  }

  function renderFloor(root, layout) {
    var floorEl = $('#hotel-rooms-floor', root);
    if (!floorEl) return;
    closeRoomMenu();
    var view = floorEl.getAttribute('data-view') || 'grid';
    var floors = layout.floors || [];
    var rooms = layout.rooms || [];

    if (!rooms.length) {
      floorEl.innerHTML =
        '<div class="hotel-rooms-empty" role="status">' +
        '<h2>No rooms configured</h2>' +
        '<p>Room inventory will appear here once seeded.</p>' +
        '</div>';
      floorEl.setAttribute('data-view', view);
      return;
    }

    var mergeGroups = {};
    var standalone = [];
    rooms.forEach(function (room) {
      if (!room) return;
      var gid = String(room.mergeGroupId || '').trim();
      if (gid) {
        if (!mergeGroups[gid]) mergeGroups[gid] = [];
        mergeGroups[gid].push(room);
      } else {
        standalone.push(room);
      }
    });

    var mergeSectionList = Object.keys(mergeGroups)
      .map(function (gid) {
        var groupRooms = sortRoomsByNumber(mergeGroups[gid]);
        var primary =
          groupRooms.find(function (r) {
            return r && r.isMergePrimary && !r.isMergeMember;
          }) || groupRooms[0];
        return {
          id: gid,
          title: mergeGroupSectionTitle(groupRooms, rooms),
          rooms: groupRooms,
          primaryId: primary && primary.id ? String(primary.id) : '',
          numbers: groupRooms
            .map(function (r) {
              return r && r.number ? String(r.number) : '';
            })
            .filter(Boolean)
            .join(', '),
          anchor: roomNumberSortKey(primary && primary.number)
        };
      })
      .filter(function (sec) {
        return sec.rooms.length > 0;
      })
      .sort(function (a, b) {
        if (a.anchor !== b.anchor) return a.anchor - b.anchor;
        return String(a.id).localeCompare(String(b.id));
      });

    var floorSections = [];
    var seen = {};
    floors.forEach(function (f) {
      if (!f || !f.id || seen[f.id]) return;
      seen[f.id] = true;
      floorSections.push({ id: f.id, title: f.name || f.id, rooms: [] });
    });
    standalone.forEach(function (room) {
      var fid = room.floorId || '_unassigned';
      if (!seen[fid]) {
        seen[fid] = true;
        floorSections.push({
          id: fid,
          title: floorNameById(floors, fid) || 'Unassigned',
          rooms: []
        });
      }
    });
    floorSections.forEach(function (sec) {
      sec.rooms = sortRoomsByNumber(
        standalone.filter(function (r) {
          return (r.floorId || '_unassigned') === sec.id;
        })
      );
    });
    floorSections = floorSections.filter(function (sec) {
      return sec.rooms.length > 0;
    });

    var html = '';
    mergeSectionList.forEach(function (sec) {
      html +=
        '<section class="hotel-floor-section hotel-merge-section" data-floor-section="merge:' +
        escapeHtml(sec.id) +
        '" data-merge-section="' +
        escapeHtml(sec.id) +
        '">' +
        '<div class="hotel-merge-section-head">' +
        '<h2 class="hotel-floor-section-title">Merged Room — ' +
        escapeHtml(sec.title) +
        '</h2>' +
        (sec.primaryId
          ? '<button type="button" class="hotel-merge-checkout-all" data-merge-checkout="' +
            escapeHtml(sec.primaryId) +
            '" data-merge-rooms="' +
            escapeHtml(sec.numbers || '') +
            '">Check out all</button>'
          : '') +
        '</div>' +
        '<div class="hotel-merge-box">' +
        '<div class="hotel-rooms-grid">';
      sec.rooms.forEach(function (room) {
        html += roomBoardTileHtml(room, rooms);
      });
      html += '</div></div></section>';
    });

    floorSections.forEach(function (sec) {
      html +=
        '<section class="hotel-floor-section" data-floor-section="' +
        escapeHtml(sec.id) +
        '">' +
        '<h2 class="hotel-floor-section-title">' +
        escapeHtml(sec.title) +
        '</h2>' +
        '<div class="hotel-rooms-grid">';
      sec.rooms.forEach(function (room) {
        html += roomBoardTileHtml(room, rooms);
      });
      html += '</div></section>';
    });

    floorEl.innerHTML = html;
    floorEl.setAttribute('data-view', view);
  }

  function activeTypePill(root) {
    var pill = $('#hotel-floor-pills .hotel-floor-pill.is-active', root);
    return pill ? pill.getAttribute('data-type') || '' : '';
  }

  function statusFilterValue(root) {
    var value = normalize(($('#hotel-rooms-status-filter', root) || {}).value).replace(
      /\s+/g,
      '_'
    );
    if (!value || value === 'all') return '';
    if (value === 'expected_checkout') return 'expected_checkout';
    return value;
  }

  function todayISO() {
    if (typeof global.hotelDateTodayISO === 'function') {
      return global.hotelDateTodayISO();
    }
    var d = new Date();
    var m = String(d.getMonth() + 1).padStart(2, '0');
    var day = String(d.getDate()).padStart(2, '0');
    return d.getFullYear() + '-' + m + '-' + day;
  }

  function roomsDateInput(root) {
    return $('#hotel-rooms-date-filter', root);
  }

  function syncDateChipDisplay(root) {
    var input = roomsDateInput(root);
    if (!input) return;
    if (!String(input.value || '').trim()) {
      if (typeof global.setHotelDateValue === 'function') {
        global.setHotelDateValue(input, todayISO());
      } else {
        input.value = todayISO();
      }
    } else if (typeof global.syncHotelDateChip === 'function') {
      global.syncHotelDateChip(input);
    }
  }

  function dateFilterValue(root) {
    var input = roomsDateInput(root);
    if (!input) return '';
    var value = String(input.value || '').trim();
    if (!value) {
      value = todayISO();
      if (typeof global.setHotelDateValue === 'function') {
        global.setHotelDateValue(input, value);
      } else {
        input.value = value;
      }
    } else {
      syncDateChipDisplay(root);
    }
    return value;
  }

  function applyFilters(root) {
    var type = normalize(activeTypePill(root));
    var status = statusFilterValue(root);
    var q = normalize(($('#hotel-rooms-search', root) || {}).value);
    var dateIso = dateFilterValue(root);
    var visibleBySection = {};

    refreshEffectiveStatuses(root, dateIso);
    paintKpis(root, computePhysicalRoomCounts(root, currentLayout, dateIso));
    syncKpiSelection(root);

    $all('[data-room-tile]', root).forEach(function (tile) {
      var show = true;
      var effective = normalize(
        tile.getAttribute('data-effective-status') || tile.getAttribute('data-status')
      );
      if (type && normalize(tile.getAttribute('data-type')) !== type) show = false;
      if (status === 'expected_checkout') {
        if (!tileIsExpectedCheckout(tile, dateIso)) show = false;
      } else if (status && effective !== status) {
        show = false;
      }
      if (q) {
        var number = normalize(
          tile.getAttribute('data-search-numbers') || tile.getAttribute('data-number')
        );
        var typeLabel = normalize(
          tile.getAttribute('data-room-type-label') ||
            (tile.querySelector('.hotel-room-type') || {}).textContent
        );
        var guest = normalize(tile.getAttribute('data-guest-search'));
        if (
          number.indexOf(q) === -1 &&
          typeLabel.indexOf(q) === -1 &&
          guest.indexOf(q) === -1
        ) {
          show = false;
        }
      }
      tile.hidden = !show;
      tile.classList.toggle('is-hidden', !show);
      var section = tile.closest('[data-floor-section]');
      if (section) {
        var sid = section.getAttribute('data-floor-section') || '';
        if (show) visibleBySection[sid] = true;
      }
    });

    $all('[data-floor-section]', root).forEach(function (section) {
      var sid = section.getAttribute('data-floor-section') || '';
      var showSection = !!visibleBySection[sid];
      section.hidden = !showSection;
      section.classList.toggle('is-hidden', !showSection);
    });
  }

  function setView(root, view) {
    var floorEl = $('#hotel-rooms-floor', root);
    if (!floorEl) return;
    var next = view === 'list' ? 'list' : 'grid';
    floorEl.setAttribute('data-view', next);
    $all('.hotel-view-btn', root).forEach(function (btn) {
      var active = btn.getAttribute('data-view') === next;
      btn.classList.toggle('is-active', active);
      btn.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
  }

  function applyLayout(root, payload) {
    currentLayout = {
      floors: (payload && payload.floors) || [],
      rooms: (payload && payload.rooms) || []
    };
    renderTypePills(root);
    renderFloor(root, currentLayout);
    applyFilters(root);
  }

  function loadRooms(root) {
    resolveApi();
    return fetch(ROOMS_API, {
      method: 'GET',
      credentials: 'same-origin',
      headers: apiHeaders(),
      cache: 'no-store'
    })
      .then(function (resp) {
        return resp.json().then(function (data) {
          return { ok: resp.ok, data: data };
        });
      })
      .then(function (result) {
        if (!result.ok || !result.data || !result.data.ok) {
          throw new Error((result.data && result.data.error) || 'Failed to load rooms.');
        }
        applyLayout(root, result.data);
      })
      .catch(function (err) {
        showToast(err.message || 'Failed to load rooms.', true);
      });
  }

  function addDaysISO(iso, days) {
    var parts = String(iso || '').split('-');
    if (parts.length !== 3) return '';
    var d = new Date(
      Number(parts[0]),
      Number(parts[1]) - 1,
      Number(parts[2]) + Number(days || 0)
    );
    if (isNaN(d.getTime())) return '';
    return (
      d.getFullYear() +
      '-' +
      String(d.getMonth() + 1).padStart(2, '0') +
      '-' +
      String(d.getDate()).padStart(2, '0')
    );
  }

  function reservationRangesOverlap(aIn, aOut, bIn, bOut) {
    var aStart = toDateISO(aIn);
    var aEnd = toDateISO(aOut);
    var bStart = toDateISO(bIn);
    var bEnd = toDateISO(bOut);
    if (!aStart || !aEnd || !bStart || !bEnd) return false;
    /* Inclusive checkout day — same coverage as stayCoversDate. */
    return aStart <= bEnd && bStart <= aEnd;
  }

  function splitGuestName(fullName) {
    var raw = String(fullName || '').trim().replace(/\s+/g, ' ');
    if (!raw) return { guestName: '', firstName: '', lastName: '' };
    var parts = raw.split(' ');
    if (parts.length === 1) {
      return { guestName: raw, firstName: parts[0], lastName: '' };
    }
    return {
      guestName: raw,
      firstName: parts[0],
      lastName: parts.slice(1).join(' ')
    };
  }

  function setBoardFormDate(form, name, iso) {
    var input = form && (form.elements[name] || null);
    if (!input) return;
    var value = toDateISO(iso) || '';
    if (typeof global.setHotelDateValue === 'function') {
      global.setHotelDateValue(input, value);
    } else {
      input.value = value;
    }
  }

  function boardReserveSelectedIds(form) {
    if (!form) return [];
    var raw = form.getAttribute('data-selected-room-ids') || '';
    if (!raw) return [];
    return raw.split(',').map(function (id) {
      return String(id || '').trim();
    }).filter(Boolean);
  }

  function setBoardReserveSelectedIds(form, ids) {
    if (!form) return;
    var unique = [];
    (ids || []).forEach(function (id) {
      var key = String(id || '').trim();
      if (key && unique.indexOf(key) === -1) unique.push(key);
    });
    form.setAttribute('data-selected-room-ids', unique.join(','));
  }

  function stayWindowFromStay(stay) {
    if (!stay || typeof stay !== 'object') return null;
    var checkIn = toDateISO(stay.checkInDate || stay.check_in_date);
    var checkOut = toDateISO(stay.checkOutDate || stay.check_out_date);
    if (!checkIn) return null;
    if (!checkOut) checkOut = addDaysISO(checkIn, 1);
    return { checkIn: checkIn, checkOut: checkOut };
  }

  function roomAvailableForBoardReserve(room, fromIso, toIso) {
    if (!room) return false;
    var status = mapStatus(room.status);
    var from = toDateISO(fromIso);
    var to = toDateISO(toIso);
    if (!from || !to || to <= from) return false;
    if (status === 'out_of_order') return false;
    /* Dirty is same-day housekeeping — future From dates treat inventory as cleaned. */
    if (status === 'dirty' && from <= todayISO()) return false;

    var windows = [];
    var stayWin = stayWindowFromStay(room.stay);
    if (stayWin) windows.push(stayWin);
    var upcoming =
      (room.upcomingStay && typeof room.upcomingStay === 'object'
        ? room.upcomingStay
        : null) ||
      (room.upcoming_stay && typeof room.upcoming_stay === 'object'
        ? room.upcoming_stay
        : null);
    var upcomingWin = stayWindowFromStay(upcoming);
    if (upcomingWin) windows.push(upcomingWin);

    for (var i = 0; i < windows.length; i++) {
      if (
        reservationRangesOverlap(
          from,
          to,
          windows[i].checkIn,
          windows[i].checkOut
        )
      ) {
        return false;
      }
    }
    return true;
  }

  function boardRoomOptionLabel(room) {
    var number = room.number || room.roomNumber || room.id || '';
    var typeLabel = room.roomTypeLabel || room.roomType || '';
    return ('Room ' + number + (typeLabel ? ' · ' + typeLabel : '')).trim();
  }

  function boardRoomsSelectionSummary(form) {
    var selected = boardReserveSelectedIds(form);
    if (!selected.length) return '';
    var rooms = (currentLayout && currentLayout.rooms) || [];
    var names = selected.map(function (id) {
      var room = null;
      for (var i = 0; i < rooms.length; i++) {
        if (rooms[i] && String(rooms[i].id) === String(id)) {
          room = rooms[i];
          break;
        }
      }
      return room ? 'Room ' + (room.number || room.roomNumber || id) : id;
    });
    return names.length <= 2 ? names.join(', ') : names.length + ' rooms selected';
  }

  function syncBoardRoomsTriggerLabel(form) {
    var search = document.getElementById('hr-board-reserve-rooms-search');
    var menu = document.getElementById('hr-board-reserve-rooms-menu');
    if (!search) return;
    var menuOpen = !!(menu && !menu.hidden);
    /* While searching, keep the typed query; otherwise show selection summary. */
    if (menuOpen && search.getAttribute('data-searching') === '1') return;
    var summary = boardRoomsSelectionSummary(form);
    search.value = summary;
    search.classList.toggle('is-placeholder', !summary);
    search.placeholder = 'Select rooms…';
  }

  function closeBoardRoomsMenu(form) {
    var wrap = document.getElementById('hr-board-reserve-rooms-select');
    var trigger = document.getElementById('hr-board-reserve-rooms-trigger');
    var menu = document.getElementById('hr-board-reserve-rooms-menu');
    var search = document.getElementById('hr-board-reserve-rooms-search');
    if (menu) {
      menu.hidden = true;
      menu.setAttribute('hidden', '');
    }
    if (trigger) trigger.classList.remove('is-open');
    if (search) {
      search.setAttribute('aria-expanded', 'false');
      search.removeAttribute('data-searching');
    }
    if (wrap) wrap.classList.remove('is-open');
    syncBoardRoomsTriggerLabel(form || document.getElementById('hr-board-reserve-form'));
    applyBoardRoomsSearchFilter();
  }

  function openBoardRoomsMenu(opts) {
    opts = opts || {};
    var wrap = document.getElementById('hr-board-reserve-rooms-select');
    var trigger = document.getElementById('hr-board-reserve-rooms-trigger');
    var menu = document.getElementById('hr-board-reserve-rooms-menu');
    var search = document.getElementById('hr-board-reserve-rooms-search');
    var form = document.getElementById('hr-board-reserve-form');
    if (!menu || !trigger) return;
    menu.hidden = false;
    menu.removeAttribute('hidden');
    trigger.classList.add('is-open');
    if (wrap) wrap.classList.add('is-open');
    if (search) {
      search.setAttribute('aria-expanded', 'true');
      if (opts.clearForSearch) {
        search.setAttribute('data-searching', '1');
        search.value = '';
        search.classList.add('is-placeholder');
      }
    }
    applyBoardRoomsSearchFilter();
    try {
      menu.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    } catch (err) {
      /* ignore */
    }
    if (search && opts.focus !== false) {
      setTimeout(function () {
        search.focus();
        if (opts.clearForSearch) search.select();
      }, 0);
    }
  }

  function toggleBoardRoomsMenu() {
    var menu = document.getElementById('hr-board-reserve-rooms-menu');
    if (!menu) return;
    if (menu.hidden) openBoardRoomsMenu({ clearForSearch: false });
    else closeBoardRoomsMenu(document.getElementById('hr-board-reserve-form'));
  }

  function boardRoomsSearchQuery() {
    var search = document.getElementById('hr-board-reserve-rooms-search');
    var menu = document.getElementById('hr-board-reserve-rooms-menu');
    if (!search || !menu || menu.hidden) return '';
    if (search.getAttribute('data-searching') !== '1') return '';
    return normalize(search.value);
  }

  function roomMatchesBoardSearch(room, query) {
    if (!query) return true;
    var label = normalize(boardRoomOptionLabel(room));
    var number = normalize(room.number || room.roomNumber || '');
    var typeLabel = normalize(room.roomTypeLabel || room.roomType || '');
    var id = normalize(room.id || '');
    return (
      label.indexOf(query) !== -1 ||
      number.indexOf(query) !== -1 ||
      typeLabel.indexOf(query) !== -1 ||
      id.indexOf(query) !== -1
    );
  }

  function applyBoardRoomsSearchFilter() {
    var optionsEl = document.getElementById('hr-board-reserve-rooms-options');
    var emptyEl = document.getElementById('hr-board-reserve-rooms-empty');
    if (!optionsEl) return;
    var query = boardRoomsSearchQuery();
    var available = (optionsEl.__boardAvailableRooms || []).slice();
    var visible = 0;
    $all('.hr-board-rooms-option', optionsEl).forEach(function (row) {
      var input = row.querySelector('input[type="checkbox"]');
      var id = input ? String(input.value || '') : '';
      var room = null;
      for (var i = 0; i < available.length; i++) {
        if (available[i] && String(available[i].id) === id) {
          room = available[i];
          break;
        }
      }
      var show = room ? roomMatchesBoardSearch(room, query) : !query;
      row.hidden = !show;
      if (show) {
        row.removeAttribute('hidden');
        visible += 1;
      } else {
        row.setAttribute('hidden', '');
      }
    });
    if (emptyEl) {
      if (!available.length) {
        emptyEl.textContent = 'No rooms available for these dates.';
        emptyEl.hidden = false;
        emptyEl.removeAttribute('hidden');
      } else if (!visible) {
        emptyEl.textContent = 'No rooms match your search.';
        emptyEl.hidden = false;
        emptyEl.removeAttribute('hidden');
      } else {
        emptyEl.hidden = true;
        emptyEl.setAttribute('hidden', '');
      }
    }
  }

  function refreshBoardReserveRoomOptions(form) {
    if (!form) return;
    var fromInput = form.elements.reserveFrom || $('#hr-board-reserve-from', form);
    var toInput = form.elements.reserveTo || $('#hr-board-reserve-to', form);
    var fromIso = toDateISO(fromInput && fromInput.value);
    var toIso = toDateISO(toInput && toInput.value);
    var optionsEl = document.getElementById('hr-board-reserve-rooms-options');
    var emptyEl = document.getElementById('hr-board-reserve-rooms-empty');
    if (!optionsEl) return;

    var selected = boardReserveSelectedIds(form);
    var available = [];
    ((currentLayout && currentLayout.rooms) || []).forEach(function (room) {
      if (roomAvailableForBoardReserve(room, fromIso, toIso)) available.push(room);
    });
    available.sort(function (a, b) {
      var an = String(a.number || a.roomNumber || a.id || '');
      var bn = String(b.number || b.roomNumber || b.id || '');
      return an.localeCompare(bn, undefined, { numeric: true });
    });

    var keep = selected.filter(function (id) {
      return available.some(function (room) {
        return String(room.id) === String(id);
      });
    });
    setBoardReserveSelectedIds(form, keep);
    optionsEl.__boardAvailableRooms = available;

    if (!available.length) {
      optionsEl.innerHTML = '';
      if (emptyEl) {
        emptyEl.textContent = 'No rooms available for these dates.';
        emptyEl.hidden = false;
        emptyEl.removeAttribute('hidden');
      }
      syncBoardRoomsTriggerLabel(form);
      syncBoardReserveSaveEnabled(form);
      return;
    }
    optionsEl.innerHTML = available
      .map(function (room) {
        var id = String(room.id || '');
        var checked = keep.indexOf(id) !== -1;
        return (
          '<label class="hr-board-rooms-option' +
          (checked ? ' is-selected' : '') +
          '" role="option" aria-selected="' +
          (checked ? 'true' : 'false') +
          '">' +
          '<input type="checkbox" value="' +
          escapeHtml(id) +
          '"' +
          (checked ? ' checked' : '') +
          '>' +
          '<span>' +
          escapeHtml(boardRoomOptionLabel(room)) +
          '</span></label>'
        );
      })
      .join('');
    applyBoardRoomsSearchFilter();
    syncBoardRoomsTriggerLabel(form);
    syncBoardReserveSaveEnabled(form);
  }

  function boardReserveMobileDigits(form) {
    var mobileInput =
      (form && ($('#hr-board-reserve-mobile', form) || form.elements.mobile)) || null;
    if (!mobileInput) return '';
    return String(mobileInput.value || '').replace(/\D/g, '').slice(0, 10);
  }

  function syncBoardReserveSaveEnabled(form) {
    var saveBtn = document.getElementById('hr-board-reserve-save');
    if (!saveBtn) return;
    var digits = boardReserveMobileDigits(form);
    var guestName = form && form.elements.guestName
      ? String(form.elements.guestName.value || '').trim()
      : '';
    var rooms = boardReserveSelectedIds(form);
    var ok = digits.length === 10 && !!guestName && rooms.length > 0;
    saveBtn.disabled = !ok;
    saveBtn.setAttribute('aria-disabled', ok ? 'false' : 'true');
    if (ok) {
      saveBtn.removeAttribute('title');
    } else {
      saveBtn.title = 'Enter mobile, guest name, and select rooms';
    }
  }

  function setBoardReservePartyPanel(form, party) {
    var next = party === 'agency' ? 'agency' : 'guest';
    $all('[data-reserve-party]', form).forEach(function (btn) {
      var active = btn.getAttribute('data-reserve-party') === next;
      btn.classList.toggle('is-active', active);
      btn.setAttribute('aria-selected', active ? 'true' : 'false');
    });
    $all('[data-reserve-panel]', form).forEach(function (panel) {
      var show = panel.getAttribute('data-reserve-panel') === next;
      panel.hidden = !show;
      if (show) panel.removeAttribute('hidden');
      else panel.setAttribute('hidden', '');
    });
  }

  function syncBoardAgencyBillingHint(form) {
    var hint = $('#hr-board-reserve-agency-billing-hint', form);
    var nameEl = $('#hr-board-reserve-agency-billing-name', form);
    var billing = form && form.elements.agencyBilling;
    var agencyName = form && form.elements.agencyName
      ? String(form.elements.agencyName.value || '').trim()
      : '';
    if (!hint) return;
    var show = !!(billing && billing.checked);
    hint.hidden = !show;
    if (show) hint.removeAttribute('hidden');
    else hint.setAttribute('hidden', '');
    if (nameEl) nameEl.textContent = agencyName || 'Agency Name';
  }

  function bindBoardReservePartyToggle(form) {
    if (!form || form.getAttribute('data-party-toggle-bound') === '1') return;
    form.setAttribute('data-party-toggle-bound', '1');
    form.addEventListener('click', function (event) {
      var btn = event.target.closest('[data-reserve-party]');
      if (!btn || !form.contains(btn)) return;
      event.preventDefault();
      setBoardReservePartyPanel(form, btn.getAttribute('data-reserve-party'));
    });
  }

  function bindBoardAgencyBilling(form) {
    if (!form || form.getAttribute('data-agency-billing-bound') === '1') return;
    form.setAttribute('data-agency-billing-bound', '1');
    form.addEventListener('change', function (event) {
      if (event.target && event.target.name === 'agencyBilling') {
        syncBoardAgencyBillingHint(form);
      }
    });
    form.addEventListener('input', function (event) {
      if (event.target && event.target.name === 'agencyName') {
        syncBoardAgencyBillingHint(form);
      }
    });
  }

  function parseBoardAgencies(root) {
    try {
      var raw = root && root.getAttribute('data-agencies');
      var list = raw ? JSON.parse(raw) : [];
      return Array.isArray(list) ? list : [];
    } catch (err) {
      return [];
    }
  }

  function filterBoardAgencies(agencies, query) {
    var q = String(query || '').trim().toLowerCase();
    var list = (agencies || []).filter(function (agency) {
      return agency && String(agency.name || '').trim();
    });
    if (!q) return list;
    return list.filter(function (agency) {
      var name = String(agency.name || '').toLowerCase();
      var gst = String(agency.gst || '').toLowerCase();
      var address = String(agency.address || '').toLowerCase();
      return name.indexOf(q) !== -1 || gst.indexOf(q) !== -1 || address.indexOf(q) !== -1;
    });
  }

  function fillBoardAgencyFields(form, agency) {
    if (!form || !agency) return;
    if (form.elements.agencyName) form.elements.agencyName.value = agency.name || '';
    if (form.elements.agencyGst) form.elements.agencyGst.value = agency.gst || '';
    if (form.elements.agencyAddress) form.elements.agencyAddress.value = agency.address || '';
    syncBoardAgencyBillingHint(form);
  }

  function bindBoardAgencySuggest(root, form) {
    if (!form) return;
    var nameInput = $('#hr-board-reserve-agency-name', form) || form.elements.agencyName;
    var box = $('#hr-board-reserve-agency-suggest', form);
    if (!nameInput || !box) return;
    if (nameInput.getAttribute('data-agency-pick-bound') === '1') return;
    nameInput.setAttribute('data-agency-pick-bound', '1');
    nameInput.setAttribute('autocomplete', 'off');
    nameInput.removeAttribute('list');

    var timer = null;
    var results = [];
    var activeIndex = -1;

    function closeSuggest() {
      box.hidden = true;
      box.innerHTML = '';
      nameInput.setAttribute('aria-expanded', 'false');
      activeIndex = -1;
      results = [];
    }

    function applyAgency(agency, fromPick) {
      if (!agency) return;
      fillBoardAgencyFields(form, agency);
      closeSuggest();
      if (fromPick) showToast('Agency details loaded.');
    }

    function renderSuggest(list) {
      results = list || [];
      if (!results.length) {
        closeSuggest();
        return;
      }
      if (activeIndex < 0 || activeIndex >= results.length) activeIndex = 0;
      box.hidden = false;
      nameInput.setAttribute('aria-expanded', 'true');
      box.innerHTML = results
        .map(function (agency, idx) {
          var meta = String(agency.gst || agency.address || '').trim();
          return (
            '<button type="button" class="hr-board-customer-opt' +
            (idx === activeIndex ? ' is-active' : '') +
            '" role="option" data-agency-index="' +
            idx +
            '">' +
            '<span class="hr-board-customer-opt-mobile">' +
            escapeHtml(agency.name || '') +
            '</span>' +
            (meta
              ? '<span class="hr-board-customer-opt-name">' + escapeHtml(meta) + '</span>'
              : '') +
            '</button>'
          );
        })
        .join('');
    }

    function showForQuery(query) {
      renderSuggest(filterBoardAgencies(parseBoardAgencies(root), query));
    }

    function refreshFromApi() {
      var api = root && root.getAttribute('data-agencies-api');
      if (!api) return;
      fetch(api, { credentials: 'same-origin', headers: apiHeaders() })
        .then(function (resp) {
          return resp.json().then(function (data) {
            return { ok: resp.ok, data: data };
          });
        })
        .then(function (result) {
          if (!result.ok || !result.data || !result.data.ok || !Array.isArray(result.data.agencies)) {
            return;
          }
          try {
            root.setAttribute('data-agencies', JSON.stringify(result.data.agencies));
          } catch (err) {}
          if (document.activeElement === nameInput) showForQuery(nameInput.value);
        })
        .catch(function () {});
    }

    nameInput.addEventListener('focus', function () {
      showForQuery(nameInput.value);
      refreshFromApi();
    });
    nameInput.addEventListener('click', function () {
      showForQuery(nameInput.value);
    });
    nameInput.addEventListener('input', function () {
      if (timer) clearTimeout(timer);
      timer = setTimeout(function () {
        showForQuery(nameInput.value);
      }, 120);
    });
    nameInput.addEventListener('keydown', function (event) {
      if (box.hidden || !results.length) return;
      if (event.key === 'ArrowDown') {
        event.preventDefault();
        activeIndex = (activeIndex + 1) % results.length;
        renderSuggest(results);
      } else if (event.key === 'ArrowUp') {
        event.preventDefault();
        activeIndex = (activeIndex - 1 + results.length) % results.length;
        renderSuggest(results);
      } else if (event.key === 'Enter' && activeIndex >= 0) {
        event.preventDefault();
        applyAgency(results[activeIndex], true);
      } else if (event.key === 'Escape') {
        closeSuggest();
      }
    });
    box.addEventListener('mousedown', function (event) {
      var btn = event.target.closest('[data-agency-index]');
      if (!btn) return;
      event.preventDefault();
      var idx = Number(btn.getAttribute('data-agency-index'));
      if (!isNaN(idx) && results[idx]) applyAgency(results[idx], true);
    });
    nameInput.addEventListener('blur', function () {
      var needle = String(nameInput.value || '').trim().toLowerCase();
      if (needle) {
        var agencies = parseBoardAgencies(root);
        for (var i = 0; i < agencies.length; i += 1) {
          if (String(agencies[i].name || '').trim().toLowerCase() === needle) {
            fillBoardAgencyFields(form, agencies[i]);
            break;
          }
        }
      }
      setTimeout(closeSuggest, 150);
    });
    document.addEventListener('click', function (event) {
      if (!form.contains(event.target)) closeSuggest();
    });
  }

  function bindBoardReserveCustomerSuggest(root, form) {
    if (!form) return;
    var mobileInput = $('#hr-board-reserve-mobile', form) || form.elements.mobile;
    var nameInput = $('#hr-board-reserve-guest-name', form) || form.elements.guestName;
    var box = $('#hr-board-reserve-customer-suggest', form);
    if (!mobileInput || !box) return;
    if (form.getAttribute('data-customer-suggest-bound') === '1') return;
    form.setAttribute('data-customer-suggest-bound', '1');

    var timer = null;
    var results = [];
    var activeIndex = -1;

    function closeSuggest() {
      box.hidden = true;
      box.innerHTML = '';
      mobileInput.setAttribute('aria-expanded', 'false');
      activeIndex = -1;
      results = [];
    }

    function applyCustomer(customer) {
      if (!customer) return;
      var mobile = String(customer.mobile || '').replace(/\D/g, '').slice(0, 10);
      var name = String(customer.name || customer.first_name || '').trim();
      var email = String(customer.email || '').trim();
      if (mobile) mobileInput.value = mobile;
      if (name && nameInput) nameInput.value = name;
      var emailInput = $('#hr-board-reserve-email', form) || form.elements.email;
      if (email && emailInput) emailInput.value = email;
      closeSuggest();
      syncBoardReserveSaveEnabled(form);
      showToast('Customer details loaded.');
    }

    function renderSuggest(list) {
      results = list || [];
      if (!results.length) {
        closeSuggest();
        return;
      }
      if (activeIndex < 0 || activeIndex >= results.length) activeIndex = 0;
      box.hidden = false;
      mobileInput.setAttribute('aria-expanded', 'true');
      box.innerHTML = results
        .map(function (c, idx) {
          return (
            '<button type="button" class="hr-board-customer-opt' +
            (idx === activeIndex ? ' is-active' : '') +
            '" role="option" data-customer-index="' +
            idx +
            '">' +
            '<span class="hr-board-customer-opt-mobile">' +
            escapeHtml(c.mobile || '') +
            '</span>' +
            '<span class="hr-board-customer-opt-name">' +
            escapeHtml(c.name || c.first_name || '—') +
            '</span></button>'
          );
        })
        .join('');
    }

    function runSearch() {
      var api =
        (root && root.getAttribute('data-customers-api')) || '/hotel/api/customers';
      var digits = String(mobileInput.value || '').replace(/\D/g, '');
      if (digits.length < 2) {
        closeSuggest();
        return;
      }
      fetch(api + '?q=' + encodeURIComponent(digits), {
        credentials: 'same-origin',
        headers: apiHeaders()
      })
        .then(function (resp) {
          return resp.json().then(function (data) {
            return { ok: resp.ok, data: data };
          });
        })
        .then(function (result) {
          if (!result.ok || !result.data || !result.data.ok) {
            closeSuggest();
            return;
          }
          renderSuggest(result.data.customers || []);
        })
        .catch(function () {
          closeSuggest();
        });
    }

    mobileInput.addEventListener('input', function () {
      var digits = String(mobileInput.value || '').replace(/\D/g, '').slice(0, 10);
      if (mobileInput.value !== digits) mobileInput.value = digits;
      syncBoardReserveSaveEnabled(form);
      if (timer) clearTimeout(timer);
      timer = setTimeout(runSearch, 280);
    });
    mobileInput.addEventListener('keydown', function (event) {
      if (box.hidden || !results.length) return;
      if (event.key === 'ArrowDown') {
        event.preventDefault();
        activeIndex = (activeIndex + 1) % results.length;
        renderSuggest(results);
      } else if (event.key === 'ArrowUp') {
        event.preventDefault();
        activeIndex = (activeIndex - 1 + results.length) % results.length;
        renderSuggest(results);
      } else if (event.key === 'Enter' && activeIndex >= 0) {
        event.preventDefault();
        applyCustomer(results[activeIndex]);
      } else if (event.key === 'Escape') {
        closeSuggest();
      }
    });
    box.addEventListener('mousedown', function (event) {
      var opt = event.target.closest('[data-customer-index]');
      if (!opt) return;
      event.preventDefault();
      var idx = Number(opt.getAttribute('data-customer-index'));
      if (!isNaN(idx)) applyCustomer(results[idx]);
    });
    document.addEventListener('click', function (event) {
      if (!form.contains(event.target)) closeSuggest();
    });
  }

  function bindBoardRoomsMultiSelect(form) {
    if (!form || form.getAttribute('data-rooms-multi-bound') === '1') return;
    form.setAttribute('data-rooms-multi-bound', '1');
    form.addEventListener('change', function (event) {
      var input = event.target;
      if (!input || input.type !== 'checkbox') return;
      if (!input.closest('#hr-board-reserve-rooms-options')) return;
      var selected = boardReserveSelectedIds(form);
      var id = String(input.value || '');
      var idx = selected.indexOf(id);
      if (input.checked && idx === -1) selected.push(id);
      if (!input.checked && idx !== -1) selected.splice(idx, 1);
      setBoardReserveSelectedIds(form, selected);
      var row = input.closest('.hr-board-rooms-option');
      if (row) {
        row.classList.toggle('is-selected', !!input.checked);
        row.setAttribute('aria-selected', input.checked ? 'true' : 'false');
      }
      /* Keep searching; don't overwrite the query with the summary while open. */
      var search = document.getElementById('hr-board-reserve-rooms-search');
      if (search && search.getAttribute('data-searching') === '1') {
        /* leave typed query */
      } else {
        syncBoardRoomsTriggerLabel(form);
      }
      syncBoardReserveSaveEnabled(form);
    });
    var search = document.getElementById('hr-board-reserve-rooms-search');
    if (search && search.getAttribute('data-bound') !== '1') {
      search.setAttribute('data-bound', '1');
      search.addEventListener('focus', function () {
        openBoardRoomsMenu({ clearForSearch: true, focus: false });
      });
      search.addEventListener('click', function (event) {
        event.stopPropagation();
        openBoardRoomsMenu({ clearForSearch: true, focus: false });
      });
      search.addEventListener('input', function () {
        search.setAttribute('data-searching', '1');
        search.classList.toggle('is-placeholder', !String(search.value || '').trim());
        openBoardRoomsMenu({ clearForSearch: false, focus: false });
        applyBoardRoomsSearchFilter();
      });
      search.addEventListener('keydown', function (event) {
        if (event.key === 'Escape') {
          event.preventDefault();
          event.stopPropagation();
          closeBoardRoomsMenu(form);
          search.blur();
        } else if (event.key === 'ArrowDown') {
          event.preventDefault();
          openBoardRoomsMenu({ clearForSearch: false, focus: false });
        }
      });
    }
    var trigger = document.getElementById('hr-board-reserve-rooms-trigger');
    if (trigger && trigger.getAttribute('data-chevron-bound') !== '1') {
      trigger.setAttribute('data-chevron-bound', '1');
      trigger.addEventListener('click', function (event) {
        if (event.target && event.target.closest('#hr-board-reserve-rooms-search')) return;
        event.preventDefault();
        event.stopPropagation();
        var menu = document.getElementById('hr-board-reserve-rooms-menu');
        if (menu && !menu.hidden) closeBoardRoomsMenu(form);
        else openBoardRoomsMenu({ clearForSearch: true });
      });
    }
  }

  function syncBoardReserveToMinDate(form) {
    if (!form) return;
    var fromInput = form.elements.reserveFrom || $('#hr-board-reserve-from', form);
    var toInput = form.elements.reserveTo || $('#hr-board-reserve-to', form);
    var fromChip = document.getElementById('hr-board-reserve-from-chip');
    var toChip = document.getElementById('hr-board-reserve-to-chip');
    var today = todayISO();
    var fromIso = toDateISO(fromInput && fromInput.value);
    if (fromChip) {
      fromChip.setAttribute('data-min-date', today);
      fromChip.removeAttribute('data-max-date');
    }
    if (!toChip) return;
    if (fromIso && fromIso < today) {
      setBoardFormDate(form, 'reserveFrom', today);
      fromIso = today;
    }
    /* To must be strictly after From (e.g. From 15 → To min 16). */
    var toMin = addDaysISO(fromIso || today, 1) || today;
    if (toMin < today) toMin = today;
    toChip.setAttribute('data-min-date', toMin);
    var toIso = toDateISO(toInput && toInput.value);
    if (!toIso || toIso < toMin) {
      setBoardFormDate(form, 'reserveTo', toMin);
    }
  }

  function bindBoardReserveDateChanges(form) {
    if (!form || form.getAttribute('data-date-change-bound') === '1') return;
    form.setAttribute('data-date-change-bound', '1');
    form.addEventListener('change', function (event) {
      var name = event.target && event.target.name;
      if (name === 'reserveFrom' || name === 'reserveTo') {
        if (name === 'reserveFrom') syncBoardReserveToMinDate(form);
        refreshBoardReserveRoomOptions(form);
      }
    });
    form.addEventListener('input', function (event) {
      var name = event.target && event.target.name;
      if (name === 'guestName' || name === 'mobile') {
        syncBoardReserveSaveEnabled(form);
      }
    });
  }

  function closeBoardReserveModal() {
    var modal = document.getElementById('hr-board-reserve-modal');
    if (!modal) return;
    closeBoardRoomsMenu(document.getElementById('hr-board-reserve-form'));
    modal.hidden = true;
    modal.setAttribute('hidden', '');
    modal.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('hr-board-reserve-open');
  }

  function openBoardReserveModal(root) {
    var modal = document.getElementById('hr-board-reserve-modal');
    var form = document.getElementById('hr-board-reserve-form');
    if (!modal || !form) {
      showToast('Reserve form unavailable.', true);
      return;
    }

    var fromDate = dateFilterValue(root) || todayISO();
    var today = todayISO();
    if (fromDate < today) fromDate = today;
    var toDate = addDaysISO(fromDate, 1);
    setBoardFormDate(form, 'reserveFrom', fromDate);
    setBoardFormDate(form, 'reserveTo', toDate);
    setBoardReserveSelectedIds(form, []);
    syncBoardReserveToMinDate(form);

    if (form.elements.mobile) form.elements.mobile.value = '';
    if (form.elements.email) form.elements.email.value = '';
    if (form.elements.guestName) form.elements.guestName.value = '';
    if (form.elements.agencyName) form.elements.agencyName.value = '';
    if (form.elements.agencyGst) form.elements.agencyGst.value = '';
    if (form.elements.agencyAddress) form.elements.agencyAddress.value = '';
    if (form.elements.agencyBilling) form.elements.agencyBilling.checked = false;

    if (typeof global.initHotelDatePickers === 'function') {
      global.initHotelDatePickers(modal);
    }

    bindBoardReservePartyToggle(form);
    bindBoardAgencyBilling(form);
    bindBoardReserveCustomerSuggest(root, form);
    bindBoardAgencySuggest(root, form);
    bindBoardRoomsMultiSelect(form);
    bindBoardReserveDateChanges(form);
    setBoardReservePartyPanel(form, 'guest');
    syncBoardAgencyBillingHint(form);
    refreshBoardReserveRoomOptions(form);
    syncBoardReserveSaveEnabled(form);

    modal.hidden = false;
    modal.removeAttribute('hidden');
    modal.setAttribute('aria-hidden', 'false');
    document.body.classList.add('hr-board-reserve-open');

    var mobileFocus = $('#hr-board-reserve-mobile', form);
    if (mobileFocus) {
      setTimeout(function () {
        mobileFocus.focus();
      }, 30);
    }
  }

  function submitBoardReserveForm(root, form) {
    var mobile = boardReserveMobileDigits(form);
    if (mobile.length !== 10) {
      showToast('Mobile number must be exactly 10 digits.', true);
      if (form.elements.mobile) form.elements.mobile.focus();
      return;
    }
    var fromInput = form.elements.reserveFrom || $('#hr-board-reserve-from', form);
    var toInput = form.elements.reserveTo || $('#hr-board-reserve-to', form);
    var checkInDate = toDateISO(fromInput && fromInput.value);
    var checkOutDate = toDateISO(toInput && toInput.value);
    if (!checkInDate) {
      showToast('From date is required.', true);
      return;
    }
    if (!checkOutDate) checkOutDate = addDaysISO(checkInDate, 1);
    if (checkOutDate <= checkInDate) {
      showToast('To date must be after the From date.', true);
      return;
    }

    var guestRaw = form.elements.guestName
      ? String(form.elements.guestName.value || '').trim()
      : '';
    if (!guestRaw) {
      showToast('Guest name is required.', true);
      return;
    }
    var roomIds = boardReserveSelectedIds(form);
    if (!roomIds.length) {
      showToast('Select at least one room.', true);
      return;
    }

    var email = form.elements.email ? String(form.elements.email.value || '').trim() : '';
    var agencyName = form.elements.agencyName
      ? String(form.elements.agencyName.value || '').trim()
      : '';
    var agencyGst = form.elements.agencyGst
      ? String(form.elements.agencyGst.value || '').trim()
      : '';
    var agencyAddress = form.elements.agencyAddress
      ? String(form.elements.agencyAddress.value || '').trim()
      : '';
    var agencyBilling = !!(form.elements.agencyBilling && form.elements.agencyBilling.checked);
    if (agencyBilling && !agencyName) {
      showToast('Agency name is required for agency billing.', true);
      return;
    }
    var additionalRequests = form.elements.additionalRequests
      ? String(form.elements.additionalRequests.value || '').trim()
      : '';

    var names = splitGuestName(guestRaw);
    var stay = {
      checkInDate: checkInDate,
      checkOutDate: checkOutDate,
      guestName: names.guestName,
      firstName: names.firstName,
      lastName: names.lastName,
      mobile: mobile,
      mobileCountry: '+91',
      email: email,
      agencyName: agencyName,
      agencyGst: agencyGst,
      agencyAddress: agencyAddress,
      agencyBilling: agencyBilling,
      additionalRequests: additionalRequests
    };
    if (agencyBilling && agencyName) {
      stay.invoiceTo = agencyName;
      stay.billingName = agencyName;
    }
    if (roomIds.length > 1 && !String(stay.reservationId || '').trim()) {
      stay.reservationId = 'RSV-' + Date.now();
    }

    var saveBtn = document.getElementById('hr-board-reserve-save');
    if (saveBtn) saveBtn.disabled = true;
    closeBoardRoomsMenu(form);

    var chain = Promise.resolve();
    var reservedCount = 0;
    roomIds.forEach(function (roomId) {
      chain = chain.then(function () {
        return fetch(roomDetailApi(roomId), {
          method: 'PUT',
          credentials: 'same-origin',
          headers: apiHeaders({ 'Content-Type': 'application/json' }),
          body: JSON.stringify({
            action: 'reserve',
            checkInDate: checkInDate,
            checkOutDate: checkOutDate,
            stay: stay
          })
        })
          .then(function (resp) {
            return resp.json().then(function (data) {
              return { ok: resp.ok, data: data };
            });
          })
          .then(function (result) {
            if (!result.ok || !result.data || !result.data.ok) {
              var label = roomId;
              var room = findRoomInLayout(roomId);
              if (room) label = 'Room ' + (room.number || room.roomNumber || roomId);
              throw new Error(
                (result.data && result.data.error) ||
                  'Failed to reserve ' + label + '.'
              );
            }
            reservedCount += 1;
          });
      });
    });

    chain
      .then(function () {
        if (roomIds.length < 2) return;
        var primaryId = roomIds[0];
        var mergeChain = Promise.resolve();
        roomIds.slice(1).forEach(function (memberId) {
          mergeChain = mergeChain.then(function () {
            return fetch(roomDetailApi(primaryId), {
              method: 'PUT',
              credentials: 'same-origin',
              headers: apiHeaders({ 'Content-Type': 'application/json' }),
              body: JSON.stringify({
                action: 'merge_rooms',
                fromRoomId: memberId,
                toRoomId: primaryId
              })
            })
              .then(function (resp) {
                return resp.json().then(function (data) {
                  return { ok: resp.ok, data: data };
                });
              })
              .then(function (result) {
                if (result.ok && result.data && result.data.ok) return;
                var err = String((result.data && result.data.error) || '');
                if (/already billed|already.*merge/i.test(err)) return;
                throw new Error(err || 'Failed to merge reserved rooms.');
              });
          });
        });
        return mergeChain;
      })
      .then(function () {
        closeBoardReserveModal();
        return loadRooms(root);
      })
      .then(function () {
        showToast(
          reservedCount === 1
            ? '1 room reserved.'
            : reservedCount + ' rooms reserved.'
        );
      })
      .catch(function (err) {
        showToast(err.message || 'Failed to reserve rooms.', true);
        return loadRooms(root).then(function () {
          refreshBoardReserveRoomOptions(form);
          syncBoardReserveSaveEnabled(form);
        });
      })
      .then(function () {
        syncBoardReserveSaveEnabled(form);
      });
  }

  function roomDetailApi(roomId) {
    return '/hotel/api/rooms/' + encodeURIComponent(roomId || '');
  }

  function findRoomInLayout(roomId) {
    var rooms = (currentLayout && currentLayout.rooms) || [];
    var i;
    for (i = 0; i < rooms.length; i++) {
      if (rooms[i] && String(rooms[i].id) === String(roomId)) return rooms[i];
    }
    return null;
  }

  function closeMergeModal() {
    var form = document.getElementById('hr-merge-form');
    closeMergeRoomsMenu(form);
    var modal = document.getElementById('hr-merge-modal');
    if (!modal) return;
    modal.hidden = true;
    modal.setAttribute('hidden', '');
    modal.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('hr-merge-open');
  }

  function mergeSelectedIds(form) {
    if (!form) return [];
    var raw = form.getAttribute('data-selected-room-ids') || '';
    if (!raw) return [];
    return raw.split(',').map(function (id) {
      return String(id || '').trim();
    }).filter(Boolean);
  }

  function setMergeSelectedIds(form, ids) {
    if (!form) return;
    var unique = [];
    (ids || []).forEach(function (id) {
      var key = String(id || '').trim();
      if (key && unique.indexOf(key) === -1) unique.push(key);
    });
    form.setAttribute('data-selected-room-ids', unique.join(','));
  }

  function mergeRoomOptionLabel(room) {
    var number = room.number || room.roomNumber || room.id || '';
    var typeLabel = room.roomTypeLabel || room.roomType || '';
    var status = STATUS_LABELS[mapStatus(room.status)] || '';
    var bits = ['Room ' + number];
    if (typeLabel) bits.push(typeLabel);
    if (status) bits.push(status);
    if (room.isMergePrimary) bits.push('primary');
    return bits.join(' · ');
  }

  function mergeRoomsSelectionSummary(form) {
    var selected = mergeSelectedIds(form);
    if (!selected.length) return '';
    var rooms = (currentLayout && currentLayout.rooms) || [];
    var names = selected.map(function (id) {
      var room = null;
      for (var i = 0; i < rooms.length; i++) {
        if (rooms[i] && String(rooms[i].id) === String(id)) {
          room = rooms[i];
          break;
        }
      }
      return room ? 'Room ' + (room.number || room.roomNumber || id) : id;
    });
    return names.length <= 2 ? names.join(', ') : names.length + ' rooms selected';
  }

  function syncMergeRoomsTriggerLabel(form) {
    var search = document.getElementById('hr-merge-rooms-search');
    var menu = document.getElementById('hr-merge-rooms-menu');
    if (!search) return;
    var menuOpen = !!(menu && !menu.hidden);
    if (menuOpen && search.getAttribute('data-searching') === '1') return;
    var summary = mergeRoomsSelectionSummary(form);
    search.value = summary;
    search.classList.toggle('is-placeholder', !summary);
    search.placeholder = 'Select rooms…';
  }

  function syncMergeSaveEnabled(form) {
    var saveBtn = document.getElementById('hr-merge-save');
    if (!saveBtn) return;
    var ok = mergeSelectedIds(form).length > 0;
    saveBtn.disabled = !ok;
    saveBtn.setAttribute('aria-disabled', ok ? 'false' : 'true');
    if (ok) saveBtn.removeAttribute('title');
    else saveBtn.title = 'Select rooms to merge';
  }

  function closeMergeRoomsMenu(form) {
    var wrap = document.getElementById('hr-merge-rooms-select');
    var trigger = document.getElementById('hr-merge-rooms-trigger');
    var menu = document.getElementById('hr-merge-rooms-menu');
    var search = document.getElementById('hr-merge-rooms-search');
    if (menu) {
      menu.hidden = true;
      menu.setAttribute('hidden', '');
    }
    if (trigger) trigger.classList.remove('is-open');
    if (search) {
      search.setAttribute('aria-expanded', 'false');
      search.removeAttribute('data-searching');
    }
    if (wrap) wrap.classList.remove('is-open');
    syncMergeRoomsTriggerLabel(form || document.getElementById('hr-merge-form'));
    applyMergeRoomsSearchFilter();
  }

  function openMergeRoomsMenu(opts) {
    opts = opts || {};
    var wrap = document.getElementById('hr-merge-rooms-select');
    var trigger = document.getElementById('hr-merge-rooms-trigger');
    var menu = document.getElementById('hr-merge-rooms-menu');
    var search = document.getElementById('hr-merge-rooms-search');
    if (!menu || !trigger) return;
    menu.hidden = false;
    menu.removeAttribute('hidden');
    trigger.classList.add('is-open');
    if (wrap) wrap.classList.add('is-open');
    if (search) {
      search.setAttribute('aria-expanded', 'true');
      if (opts.clearForSearch) {
        search.setAttribute('data-searching', '1');
        search.value = '';
        search.classList.add('is-placeholder');
      }
    }
    applyMergeRoomsSearchFilter();
    try {
      menu.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    } catch (err) {
      /* ignore */
    }
    if (search && opts.focus !== false) {
      setTimeout(function () {
        search.focus();
        if (opts.clearForSearch) search.select();
      }, 0);
    }
  }

  function mergeRoomsSearchQuery() {
    var search = document.getElementById('hr-merge-rooms-search');
    var menu = document.getElementById('hr-merge-rooms-menu');
    if (!search || !menu || menu.hidden) return '';
    if (search.getAttribute('data-searching') !== '1') return '';
    return normalize(search.value);
  }

  function applyMergeRoomsSearchFilter() {
    var optionsEl = document.getElementById('hr-merge-rooms-options');
    var emptyEl = document.getElementById('hr-merge-rooms-empty');
    if (!optionsEl) return;
    var query = mergeRoomsSearchQuery();
    var available = (optionsEl.__mergeAvailableRooms || []).slice();
    var visible = 0;
    $all('.hr-board-rooms-option', optionsEl).forEach(function (row) {
      var input = row.querySelector('input[type="checkbox"]');
      var id = input ? String(input.value || '') : '';
      var room = null;
      for (var i = 0; i < available.length; i++) {
        if (available[i] && String(available[i].id) === id) {
          room = available[i];
          break;
        }
      }
      var show = room ? roomMatchesBoardSearch(room, query) : !query;
      row.hidden = !show;
      if (show) visible += 1;
    });
    if (emptyEl) {
      if (!available.length) {
        emptyEl.textContent = 'No rooms available to merge.';
        emptyEl.hidden = false;
        emptyEl.removeAttribute('hidden');
      } else if (!visible) {
        emptyEl.textContent = 'No rooms match your search.';
        emptyEl.hidden = false;
        emptyEl.removeAttribute('hidden');
      } else {
        emptyEl.hidden = true;
        emptyEl.setAttribute('hidden', '');
      }
    }
  }

  function refreshMergeRoomOptions(form, primaryId) {
    if (!form) return;
    var optionsEl = document.getElementById('hr-merge-rooms-options');
    var emptyEl = document.getElementById('hr-merge-rooms-empty');
    if (!optionsEl) return;
    var selected = mergeSelectedIds(form);
    var available = [];
    ((currentLayout && currentLayout.rooms) || []).forEach(function (room) {
      if (!room) return;
      if (String(room.id) === String(primaryId)) return;
      if (room.isMergeMember) return;
      available.push(room);
    });
    available.sort(function (a, b) {
      var an = String(a.number || a.roomNumber || a.id || '');
      var bn = String(b.number || b.roomNumber || b.id || '');
      return an.localeCompare(bn, undefined, { numeric: true });
    });
    var keep = selected.filter(function (id) {
      return available.some(function (room) {
        return String(room.id) === String(id);
      });
    });
    setMergeSelectedIds(form, keep);
    optionsEl.__mergeAvailableRooms = available;
    if (!available.length) {
      optionsEl.innerHTML = '';
      if (emptyEl) {
        emptyEl.textContent = 'No rooms available to merge.';
        emptyEl.hidden = false;
        emptyEl.removeAttribute('hidden');
      }
      syncMergeRoomsTriggerLabel(form);
      syncMergeSaveEnabled(form);
      return;
    }
    optionsEl.innerHTML = available
      .map(function (room) {
        var id = String(room.id || '');
        var checked = keep.indexOf(id) !== -1;
        return (
          '<label class="hr-board-rooms-option' +
          (checked ? ' is-selected' : '') +
          '" role="option" aria-selected="' +
          (checked ? 'true' : 'false') +
          '">' +
          '<input type="checkbox" value="' +
          escapeHtml(id) +
          '"' +
          (checked ? ' checked' : '') +
          '>' +
          '<span>' +
          escapeHtml(mergeRoomOptionLabel(room)) +
          '</span></label>'
        );
      })
      .join('');
    applyMergeRoomsSearchFilter();
    syncMergeRoomsTriggerLabel(form);
    syncMergeSaveEnabled(form);
  }

  function bindMergeRoomsMultiSelect(form) {
    if (!form || form.getAttribute('data-merge-rooms-bound') === '1') return;
    form.setAttribute('data-merge-rooms-bound', '1');
    form.addEventListener('change', function (event) {
      var input = event.target;
      if (!input || input.type !== 'checkbox') return;
      if (!input.closest('#hr-merge-rooms-options')) return;
      var selected = mergeSelectedIds(form);
      var id = String(input.value || '');
      var idx = selected.indexOf(id);
      if (input.checked && idx === -1) selected.push(id);
      if (!input.checked && idx !== -1) selected.splice(idx, 1);
      setMergeSelectedIds(form, selected);
      var row = input.closest('.hr-board-rooms-option');
      if (row) {
        row.classList.toggle('is-selected', !!input.checked);
        row.setAttribute('aria-selected', input.checked ? 'true' : 'false');
      }
      var search = document.getElementById('hr-merge-rooms-search');
      if (!(search && search.getAttribute('data-searching') === '1')) {
        syncMergeRoomsTriggerLabel(form);
      }
      syncMergeSaveEnabled(form);
    });
    var search = document.getElementById('hr-merge-rooms-search');
    if (search && search.getAttribute('data-bound') !== '1') {
      search.setAttribute('data-bound', '1');
      search.addEventListener('focus', function () {
        openMergeRoomsMenu({ clearForSearch: true, focus: false });
      });
      search.addEventListener('click', function (event) {
        event.stopPropagation();
        openMergeRoomsMenu({ clearForSearch: true, focus: false });
      });
      search.addEventListener('input', function () {
        search.setAttribute('data-searching', '1');
        search.classList.toggle('is-placeholder', !String(search.value || '').trim());
        openMergeRoomsMenu({ clearForSearch: false, focus: false });
        applyMergeRoomsSearchFilter();
      });
      search.addEventListener('keydown', function (event) {
        if (event.key === 'Escape') {
          event.preventDefault();
          event.stopPropagation();
          closeMergeRoomsMenu(form);
          search.blur();
        } else if (event.key === 'ArrowDown') {
          event.preventDefault();
          openMergeRoomsMenu({ clearForSearch: false, focus: false });
        }
      });
    }
    var trigger = document.getElementById('hr-merge-rooms-trigger');
    if (trigger && trigger.getAttribute('data-chevron-bound') !== '1') {
      trigger.setAttribute('data-chevron-bound', '1');
      trigger.addEventListener('click', function (event) {
        if (event.target && event.target.closest('#hr-merge-rooms-search')) return;
        event.preventDefault();
        event.stopPropagation();
        var menu = document.getElementById('hr-merge-rooms-menu');
        if (menu && !menu.hidden) closeMergeRoomsMenu(form);
        else openMergeRoomsMenu({ clearForSearch: true });
      });
    }
  }

  function openMergeModal(fromRoomId) {
    var modal = document.getElementById('hr-merge-modal');
    var form = document.getElementById('hr-merge-form');
    var primaryInput = document.getElementById('hr-merge-primary');
    var primaryHidden = document.getElementById('hr-merge-primary-id');
    if (!modal || !form) {
      showToast('Merge form unavailable.', true);
      return;
    }
    var source = findRoomInLayout(fromRoomId);
    if (!source) {
      showToast('Room not found.', true);
      return;
    }
    if (source.isMergeMember) {
      showToast('This room is already a merge member. Unmerge it first.', true);
      return;
    }
    bindMergeRoomsMultiSelect(form);
    if (primaryHidden) primaryHidden.value = source.id || '';
    if (primaryInput) {
      primaryInput.value =
        'Room ' +
        (source.number || '') +
        (source.roomTypeLabel ? ' — ' + source.roomTypeLabel : '');
    }
    var note = document.getElementById('hr-merge-note');
    if (note) note.value = '';
    setMergeSelectedIds(form, []);
    refreshMergeRoomOptions(form, source.id);
    if (!((document.getElementById('hr-merge-rooms-options') || {}).__mergeAvailableRooms || []).length) {
      showToast('No other rooms available to merge.', true);
    }
    modal.hidden = false;
    modal.removeAttribute('hidden');
    modal.setAttribute('aria-hidden', 'false');
    document.body.classList.add('hr-merge-open');
    try {
      var search = document.getElementById('hr-merge-rooms-search');
      if (search) search.focus();
    } catch (err) {}
  }

  function submitMergeForm(form) {
    var primaryId =
      (document.getElementById('hr-merge-primary-id') || {}).value || '';
    var roomIds = mergeSelectedIds(form);
    if (!primaryId || !roomIds.length) {
      showToast('Select at least one room to merge.', true);
      return;
    }
    var note = (form.note && form.note.value) || '';
    var saveBtn = document.getElementById('hr-merge-save');
    if (saveBtn) saveBtn.disabled = true;
    closeMergeRoomsMenu(form);
    var page = document.getElementById('hotel-rooms-page');
    var chain = Promise.resolve();
    var mergedCount = 0;
    var lastPrimary = null;
    roomIds.forEach(function (fromId) {
      chain = chain.then(function () {
        return fetch(roomDetailApi(fromId), {
          method: 'PUT',
          credentials: 'same-origin',
          headers: apiHeaders({ 'Content-Type': 'application/json' }),
          body: JSON.stringify({
            action: 'merge_rooms',
            fromRoomId: fromId,
            toRoomId: primaryId,
            note: note
          })
        })
          .then(function (resp) {
            return resp.json().then(function (data) {
              return { ok: resp.ok, data: data };
            });
          })
          .then(function (result) {
            if (!result.ok || !result.data || !result.data.ok) {
              throw new Error(
                (result.data && result.data.error) || 'Merge failed.'
              );
            }
            mergedCount += 1;
            lastPrimary = result.data.primaryRoom || result.data.room || lastPrimary;
          });
      });
    });
    chain
      .then(function () {
        closeMergeModal();
        var primaryNumber =
          (lastPrimary && lastPrimary.number) ||
          ((findRoomInLayout(primaryId) || {}).number) ||
          primaryId;
        showToast(
          mergedCount === 1
            ? 'Rooms merged. Billing is on Room ' + primaryNumber + '.'
            : mergedCount +
                ' rooms merged. Billing is on Room ' +
                primaryNumber +
                '.'
        );
        return loadRooms(page);
      })
      .catch(function (err) {
        showToast(err.message || 'Merge failed.', true);
        return loadRooms(page);
      })
      .finally(function () {
        syncMergeSaveEnabled(form);
        if (saveBtn) saveBtn.disabled = mergeSelectedIds(form).length === 0;
      });
  }

  function closeTransferModal() {
    var modal = document.getElementById('hr-transfer-modal');
    if (!modal) return;
    if (typeof global.closeAllEpListboxes === 'function') {
      global.closeAllEpListboxes();
    }
    modal.hidden = true;
    modal.setAttribute('hidden', '');
    modal.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('hr-transfer-open');
  }

  function guestLabelForRoom(room) {
    var stay = room && room.stay && typeof room.stay === 'object' ? room.stay : null;
    if (!stay) return '—';
    var name =
      String(stay.guestName || '').trim() ||
      [stay.firstName, stay.lastName]
        .map(function (part) {
          return String(part || '').trim();
        })
        .filter(Boolean)
        .join(' ');
    var mobile = String(stay.mobile || '').trim();
    if (name && mobile) return name + ' · ' + mobile;
    return name || mobile || 'In-house guest';
  }

  function resetTransferListbox(value, label) {
    if (typeof global.resetEpListbox === 'function') {
      global.resetEpListbox('hr-transfer-to', value, label);
      return;
    }
    var input = document.getElementById('hr-transfer-to');
    if (input) input.value = value;
  }

  function fillTransferVacantOptions(listboxRoot, rooms, currentId) {
    if (!listboxRoot) return 0;
    var optionsWrap =
      listboxRoot.querySelector('.ep-listbox-options') ||
      listboxRoot.querySelector('.se-filter-listbox');
    if (!optionsWrap) return 0;

    var vacant = (rooms || [])
      .filter(function (room) {
        if (!room || !room.id) return false;
        if (String(room.id) === String(currentId)) return false;
        if (mapStatus(room.status) !== 'vacant') return false;
        if (room.isMergeMember) return false;
        return true;
      })
      .sort(function (a, b) {
        return String(a.number || '').localeCompare(String(b.number || ''), undefined, {
          numeric: true
        });
      });

    optionsWrap.innerHTML = '';
    function addOption(value, label, selected) {
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className =
        'se-filter-listbox-option' + (selected ? ' is-selected' : '');
      btn.setAttribute('role', 'option');
      btn.setAttribute('data-value', value);
      btn.setAttribute('data-label', label);
      btn.setAttribute('data-name', String(label || '').toLowerCase());
      btn.setAttribute('aria-selected', selected ? 'true' : 'false');
      btn.textContent = label;
      optionsWrap.appendChild(btn);
    }

    if (!vacant.length) {
      addOption('', 'No vacant rooms available', true);
      resetTransferListbox('', 'No vacant rooms available');
      return 0;
    }

    vacant.forEach(function (room) {
      var label =
        'Room ' +
        (room.number || '') +
        (room.roomTypeLabel ? ' — ' + room.roomTypeLabel : '');
      addOption(room.id, label, false);
    });
    resetTransferListbox('', 'Select vacant room…');
    return vacant.length;
  }

  function openTransferModal(fromRoomId) {
    var modal = document.getElementById('hr-transfer-modal');
    var form = document.getElementById('hr-transfer-form');
    var fromInput = document.getElementById('hr-transfer-from');
    var guestInput = document.getElementById('hr-transfer-guest');
    var toInput = document.getElementById('hr-transfer-to');
    var listbox = document.getElementById('hr-transfer-to-listbox');
    var fromHidden = document.getElementById('hr-transfer-from-id');
    if (!modal || !form || !toInput || !listbox) {
      showToast('Transfer form unavailable.', true);
      return;
    }
    var source = findRoomInLayout(fromRoomId);
    if (!source) {
      showToast('Room not found.', true);
      return;
    }
    if (mapStatus(source.status) !== 'occupied' || !source.stay) {
      showToast('Check in a guest before transferring rooms.', true);
      return;
    }
    if (fromHidden) fromHidden.value = source.id || '';
    if (fromInput) {
      fromInput.value =
        'Room ' +
        (source.number || '') +
        (source.roomTypeLabel ? ' — ' + source.roomTypeLabel : '');
    }
    if (guestInput) guestInput.value = guestLabelForRoom(source);

    if (typeof global.initEpListboxes === 'function') {
      global.initEpListboxes();
    }
    if (typeof global.rebindEpListbox === 'function') {
      Array.from(modal.querySelectorAll('[data-se-listbox]')).forEach(function (lb) {
        global.rebindEpListbox(lb);
      });
      listbox = document.getElementById('hr-transfer-to-listbox');
    }

    fillTransferVacantOptions(
      listbox,
      (currentLayout && currentLayout.rooms) || [],
      source.id
    );
    modal.hidden = false;
    modal.removeAttribute('hidden');
    modal.setAttribute('aria-hidden', 'false');
    document.body.classList.add('hr-transfer-open');
    try {
      var trigger = listbox && listbox.querySelector('.se-filter-chip-trigger');
      if (trigger) trigger.focus();
    } catch (err) {}
  }

  function submitTransferForm(form) {
    var fromId =
      (document.getElementById('hr-transfer-from-id') || {}).value || '';
    var toId = (form.toRoomId && form.toRoomId.value) || '';
    if (!fromId || !toId) {
      showToast('Select a vacant room to transfer to.', true);
      return;
    }
    var saveBtn = document.getElementById('hr-transfer-save');
    if (saveBtn) saveBtn.disabled = true;
    var page = document.getElementById('hotel-rooms-page');
    fetch(roomDetailApi(fromId), {
      method: 'PUT',
      credentials: 'same-origin',
      headers: apiHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({
        action: 'transfer',
        toRoomId: toId,
        note: ''
      })
    })
      .then(function (resp) {
        return resp.json().then(function (data) {
          return { ok: resp.ok, data: data };
        });
      })
      .then(function (result) {
        if (!result.ok || !result.data || !result.data.ok) {
          throw new Error((result.data && result.data.error) || 'Transfer failed.');
        }
        closeTransferModal();
        var toRoom = result.data.toRoom || result.data.room;
        showToast(
          'Guest transferred to Room ' +
            ((toRoom && toRoom.number) || toId) +
            '.'
        );
        return loadRooms(page);
      })
      .catch(function (err) {
        showToast(err.message || 'Transfer failed.', true);
      })
      .finally(function () {
        if (saveBtn) saveBtn.disabled = false;
      });
  }

  function prettyStayDate(iso) {
    var value = toDateISO(iso);
    if (!value) return '—';
    var parts = value.split('-');
    if (parts.length !== 3) return value;
    var months = [
      'Jan',
      'Feb',
      'Mar',
      'Apr',
      'May',
      'Jun',
      'Jul',
      'Aug',
      'Sep',
      'Oct',
      'Nov',
      'Dec'
    ];
    return (
      Number(parts[2]) +
      ' ' +
      (months[Number(parts[1]) - 1] || '') +
      ' ' +
      parts[0]
    );
  }

  function nightsBetweenISO(checkIn, checkOut) {
    var a = toDateISO(checkIn);
    var b = toDateISO(checkOut);
    if (!a || !b) return 1;
    var aParts = a.split('-').map(Number);
    var bParts = b.split('-').map(Number);
    var start = new Date(aParts[0], aParts[1] - 1, aParts[2]);
    var end = new Date(bParts[0], bParts[1] - 1, bParts[2]);
    if (isNaN(start.getTime()) || isNaN(end.getTime())) return 1;
    var days = Math.round((end.getTime() - start.getTime()) / 86400000);
    return Math.max(1, days);
  }

  function syncExtendNightsLabel() {
    var form = document.getElementById('hr-extend-form');
    var nightsEl = document.getElementById('hr-extend-nights');
    if (!form || !nightsEl) return;
    var checkIn = form.getAttribute('data-checkin') || '';
    var checkOutInput = document.getElementById('hr-extend-checkout');
    var checkOut = toDateISO(checkOutInput && checkOutInput.value);
    var nights = nightsBetweenISO(checkIn, checkOut);
    nightsEl.textContent = nights + (nights === 1 ? ' night' : ' nights');
  }

  function closeExtendModal() {
    var modal = document.getElementById('hr-extend-modal');
    if (!modal) return;
    if (typeof global.closeHotelDatePickers === 'function') {
      global.closeHotelDatePickers();
    }
    modal.hidden = true;
    modal.setAttribute('hidden', '');
    modal.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('hr-extend-open');
    var form = document.getElementById('hr-extend-form');
    if (form) {
      form.removeAttribute('data-checkin');
      form.__hrExtendStay = null;
    }
  }

  function fillExtendModal(room) {
    var modal = document.getElementById('hr-extend-modal');
    var form = document.getElementById('hr-extend-form');
    var roomIdInput = document.getElementById('hr-extend-room-id');
    var roomInput = document.getElementById('hr-extend-room');
    var guestInput = document.getElementById('hr-extend-guest');
    var checkInInput = document.getElementById('hr-extend-checkin');
    var checkOutInput = document.getElementById('hr-extend-checkout');
    if (!modal || !form || !checkOutInput) {
      showToast('Extend form unavailable.', true);
      return;
    }
    var stay = room && room.stay && typeof room.stay === 'object' ? room.stay : null;
    if (mapStatus(room && room.status) !== 'occupied' || !stay) {
      showToast('Check in a guest before extending stay.', true);
      return;
    }
    var checkIn = toDateISO(stay.checkInDate || stay.check_in_date || '');
    var checkOut = toDateISO(
      stay.checkOutDate || stay.check_out_date || stay.expectedCheckOut || ''
    );
    if (!checkIn) {
      showToast('Check-in date is missing for this stay.', true);
      return;
    }
    if (!checkOut || checkOut <= checkIn) {
      checkOut = addDaysISO(checkIn, Math.max(1, Number(stay.nights) || 1));
    }
    if (roomIdInput) roomIdInput.value = room.id || '';
    if (roomInput) roomInput.value = 'Room ' + (room.number || '');
    if (guestInput) guestInput.value = guestLabelForRoom(room);
    if (checkInInput) checkInInput.value = prettyStayDate(checkIn);
    form.setAttribute('data-checkin', checkIn);
    form.__hrExtendStay = Object.assign({}, stay);
    if (typeof global.setHotelDateValue === 'function') {
      global.setHotelDateValue(checkOutInput, checkOut);
    } else {
      checkOutInput.value = checkOut;
    }
    if (typeof global.initHotelDatePickers === 'function') {
      global.initHotelDatePickers(modal);
    }
    if (typeof global.syncHotelDateChip === 'function') {
      global.syncHotelDateChip(checkOutInput);
    }
    syncExtendNightsLabel();
    if (checkOutInput.getAttribute('data-hr-extend-bound') !== '1') {
      checkOutInput.setAttribute('data-hr-extend-bound', '1');
      checkOutInput.addEventListener('change', syncExtendNightsLabel);
    }
    modal.hidden = false;
    modal.removeAttribute('hidden');
    modal.setAttribute('aria-hidden', 'false');
    document.body.classList.add('hr-extend-open');
    setTimeout(function () {
      try {
        var chip = modal.querySelector('#hr-extend-checkout-chip') || checkOutInput;
        if (chip && typeof chip.focus === 'function') chip.focus();
      } catch (err) {}
    }, 40);
  }

  function openExtendModal(roomId) {
    var source = findRoomInLayout(roomId);
    if (!source) {
      showToast('Room not found.', true);
      return;
    }
    if (mapStatus(source.status) !== 'occupied' || !source.stay) {
      showToast('Check in a guest before extending stay.', true);
      return;
    }
    /* Prefill from board cache, then refresh from API for latest stay. */
    fillExtendModal(source);
    fetch(roomDetailApi(roomId), {
      method: 'GET',
      credentials: 'same-origin',
      headers: apiHeaders()
    })
      .then(function (resp) {
        return resp.json().then(function (data) {
          return { ok: resp.ok, data: data };
        });
      })
      .then(function (result) {
        if (!result.ok || !result.data || !result.data.ok || !result.data.room) {
          return;
        }
        var modal = document.getElementById('hr-extend-modal');
        if (!modal || modal.hidden) return;
        fillExtendModal(result.data.room);
      })
      .catch(function () {});
  }

  function submitExtendForm(form) {
    var roomId = (document.getElementById('hr-extend-room-id') || {}).value || '';
    var checkIn = form.getAttribute('data-checkin') || '';
    var checkOutInput = document.getElementById('hr-extend-checkout');
    var checkOut = toDateISO(checkOutInput && checkOutInput.value);
    var stay = form.__hrExtendStay ? Object.assign({}, form.__hrExtendStay) : null;
    if (!roomId || !stay) {
      showToast('Stay details unavailable.', true);
      return;
    }
    if (!checkOut) {
      showToast('Choose a check-out date.', true);
      return;
    }
    if (!checkIn || checkOut <= checkIn) {
      showToast('Check-out must be after check-in.', true);
      return;
    }
    var nights = nightsBetweenISO(checkIn, checkOut);
    stay.checkInDate = checkIn;
    stay.checkOutDate = checkOut;
    stay.nights = nights;
    var saveBtn = document.getElementById('hr-extend-save');
    if (saveBtn) saveBtn.disabled = true;
    var page = document.getElementById('hotel-rooms-page');
    fetch(roomDetailApi(roomId), {
      method: 'PUT',
      credentials: 'same-origin',
      headers: apiHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ action: 'checkin', stay: stay })
    })
      .then(function (resp) {
        return resp.json().then(function (data) {
          return { ok: resp.ok, data: data };
        });
      })
      .then(function (result) {
        if (!result.ok || !result.data || !result.data.ok) {
          throw new Error(
            (result.data && result.data.error) || 'Could not update stay.'
          );
        }
        closeExtendModal();
        showToast(
          'Stay extended to ' + prettyStayDate(checkOut) + ' (' + nights + (nights === 1 ? ' night' : ' nights') + ').'
        );
        return loadRooms(page);
      })
      .catch(function (err) {
        showToast(err.message || 'Could not update stay.', true);
      })
      .finally(function () {
        if (saveBtn) saveBtn.disabled = false;
      });
  }

  function putRoomAction(roomId, payload, successMessage) {
    var page = document.getElementById('hotel-rooms-page');
    return fetch(roomDetailApi(roomId), {
      method: 'PUT',
      credentials: 'same-origin',
      headers: apiHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(payload || {})
    })
      .then(function (resp) {
        return resp.json().then(function (data) {
          return { ok: resp.ok, data: data };
        });
      })
      .then(function (result) {
        if (!result.ok || !result.data || !result.data.ok) {
          throw new Error((result.data && result.data.error) || 'Action failed.');
        }
        showToast(successMessage || 'Room updated.');
        return loadRooms(page);
      })
      .catch(function (err) {
        showToast(err.message || 'Action failed.', true);
      });
  }

  function checkoutMergeGroup(roomId, roomNumbers) {
    if (!roomId) return;
    var nums = String(roomNumbers || '').trim();
    if (!nums) {
      var room = findRoomInLayout(roomId);
      var gid = room && String(room.mergeGroupId || '').trim();
      if (gid) {
        nums = (currentLayout.rooms || [])
          .filter(function (r) {
            return r && String(r.mergeGroupId || '').trim() === gid;
          })
          .map(function (r) {
            return r.number ? String(r.number) : '';
          })
          .filter(Boolean)
          .join(', ');
      }
    }
    var msg =
      'Check out all rooms in this merge' +
      (nums ? ' (' + nums + ')' : '') +
      '? Each occupied room will be marked dirty.';
    if (!window.confirm(msg)) return;
    putRoomAction(roomId, { action: 'checkout_group' }, 'All merged rooms checked out.');
  }

  function handleRoomMenuAction(page, tile, action) {
    var roomId = tile && tile.getAttribute('data-id');
    if (!roomId || !action) return;
    if (action === 'reserved') {
      openQuickReserveModal(roomId);
      return;
    }
    if (STATUS_KEYS.indexOf(action) !== -1) {
      setRoomStatus(page, roomId, action);
      return;
    }
    if (action === 'merge') {
      openMergeModal(roomId);
      return;
    }
    if (action === 'extend') {
      openExtendModal(roomId);
      return;
    }
    if (action === 'transfer') {
      openTransferModal(roomId);
      return;
    }
    if (action === 'unmerge') {
      if (
        !window.confirm(
          'Unmerge this room from the shared bill? This room will bill on its own.'
        )
      ) {
        return;
      }
      putRoomAction(
        roomId,
        { action: 'unmerge_rooms', scope: 'one' },
        'Room unmerged.'
      );
      return;
    }
    if (action === 'unmerge-group') {
      if (
        !window.confirm(
          'Unmerge all rooms in this billing group? Each room will bill on its own.'
        )
      ) {
        return;
      }
      putRoomAction(
        roomId,
        { action: 'unmerge_rooms', scope: 'group' },
        'Merge group cleared.'
      );
      return;
    }
    if (action === 'checkout-group') {
      checkoutMergeGroup(roomId);
      return;
    }
    if (action === 'set-primary') {
      if (
        !window.confirm(
          'Make this room the billing primary? The shared folio and invoice will move here.'
        )
      ) {
        return;
      }
      putRoomAction(
        roomId,
        { action: 'set_merge_primary' },
        'This room is now the billing primary.'
      );
    }
  }

  function setRoomStatus(root, roomId, nextStatus, opts) {
    if (!roomId || !nextStatus) return;
    resolveApi();
    var status = mapStatus(nextStatus);
    var room = findRoomInLayout(roomId);
    var current = mapStatus(room && room.status);
    if (status === 'dirty' && (current === 'occupied' || (room && room.stay))) {
      if (
        !window.confirm(
          'Mark this room Dirty? The guest will be checked out and the stay cleared.'
        )
      ) {
        return;
      }
    }
    var body = { roomId: roomId, status: status };
    if (status === 'reserved') {
      var asOf = dateFilterValue(root);
      var checkIn =
        (opts && opts.checkInDate && toDateISO(opts.checkInDate)) || asOf;
      var checkOut =
        (opts && opts.checkOutDate && toDateISO(opts.checkOutDate)) ||
        addDaysISO(checkIn, 1);
      body.checkInDate = checkIn;
      body.checkOutDate = checkOut;
      body.asOf = asOf;
      if (opts && opts.guestName) {
        body.guestName = opts.guestName;
        if (opts.firstName) body.firstName = opts.firstName;
        if (opts.lastName) body.lastName = opts.lastName;
      }
    }
    fetch(ROOMS_API, {
      method: 'PUT',
      credentials: 'same-origin',
      headers: apiHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(body)
    })
      .then(function (resp) {
        return resp.json().then(function (data) {
          return { ok: resp.ok, data: data };
        });
      })
      .then(function (result) {
        if (!result.ok || !result.data || !result.data.ok) {
          throw new Error((result.data && result.data.error) || 'Failed to update room.');
        }
        applyLayout(root, result.data);
        showToast('Room updated to ' + (STATUS_LABELS[status] || status) + '.');
      })
      .catch(function (err) {
        showToast(err.message || 'Failed to update room.', true);
      });
  }

  function syncQuickReserveNightsLabel() {
    var nightsEl = document.getElementById('hr-quick-reserve-nights');
    var fromInput = document.getElementById('hr-quick-reserve-from');
    var toInput = document.getElementById('hr-quick-reserve-to');
    if (!nightsEl) return;
    var from = toDateISO(fromInput && fromInput.value);
    var to = toDateISO(toInput && toInput.value);
    var nights = nightsBetweenISO(from, to);
    nightsEl.textContent = nights + (nights === 1 ? ' night' : ' nights');
  }

  function syncQuickReserveToMinDate() {
    var fromInput = document.getElementById('hr-quick-reserve-from');
    var toInput = document.getElementById('hr-quick-reserve-to');
    if (!fromInput || !toInput) return;
    var from = toDateISO(fromInput.value);
    if (!from) return;
    var minTo = addDaysISO(from, 1);
    toInput.setAttribute('min', minTo);
    var to = toDateISO(toInput.value);
    if (!to || to <= from) {
      if (typeof global.setHotelDateValue === 'function') {
        global.setHotelDateValue(toInput, minTo);
      } else {
        toInput.value = minTo;
      }
      if (typeof global.syncHotelDateChip === 'function') {
        global.syncHotelDateChip(toInput);
      }
    }
    syncQuickReserveNightsLabel();
  }

  function closeQuickReserveModal() {
    var modal = document.getElementById('hr-quick-reserve-modal');
    if (!modal) return;
    if (typeof global.closeHotelDatePickers === 'function') {
      global.closeHotelDatePickers();
    }
    modal.hidden = true;
    modal.setAttribute('hidden', '');
    modal.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('hr-quick-reserve-open');
  }

  function openQuickReserveModal(roomId) {
    var page = document.getElementById('hotel-rooms-page');
    var modal = document.getElementById('hr-quick-reserve-modal');
    var form = document.getElementById('hr-quick-reserve-form');
    var roomIdInput = document.getElementById('hr-quick-reserve-room-id');
    var guestInput = document.getElementById('hr-quick-reserve-guest-name');
    var titleEl = document.getElementById('hr-quick-reserve-title');
    var fromInput = document.getElementById('hr-quick-reserve-from');
    var toInput = document.getElementById('hr-quick-reserve-to');
    if (!modal || !form || !fromInput || !toInput) {
      showToast('Reserve form unavailable.', true);
      return;
    }
    var room = findRoomInLayout(roomId);
    if (!room) {
      showToast('Room not found.', true);
      return;
    }
    var current = mapStatus(room.status);
    if (current === 'occupied') {
      showToast('Occupied rooms cannot be reserved from the board.', true);
      return;
    }
    var fromDate = dateFilterValue(page) || todayISO();
    var today = todayISO();
    if (fromDate < today) fromDate = today;
    var toDate = addDaysISO(fromDate, 1);
    if (roomIdInput) roomIdInput.value = room.id || roomId;
    if (titleEl) {
      titleEl.textContent = room.number
        ? 'Reserve Room ' + room.number
        : 'Reserve Room';
    }
    if (guestInput) {
      guestInput.value = guestDisplayName(room.stay) || '';
    }
    if (typeof global.setHotelDateValue === 'function') {
      global.setHotelDateValue(fromInput, fromDate);
      global.setHotelDateValue(toInput, toDate);
    } else {
      fromInput.value = fromDate;
      toInput.value = toDate;
    }
    if (typeof global.initHotelDatePickers === 'function') {
      global.initHotelDatePickers(modal);
    }
    if (typeof global.syncHotelDateChip === 'function') {
      global.syncHotelDateChip(fromInput);
      global.syncHotelDateChip(toInput);
    }
    syncQuickReserveToMinDate();
    if (form.getAttribute('data-hr-quick-reserve-dates-bound') !== '1') {
      form.setAttribute('data-hr-quick-reserve-dates-bound', '1');
      fromInput.addEventListener('change', syncQuickReserveToMinDate);
      toInput.addEventListener('change', syncQuickReserveNightsLabel);
    }
    modal.hidden = false;
    modal.removeAttribute('hidden');
    modal.setAttribute('aria-hidden', 'false');
    document.body.classList.add('hr-quick-reserve-open');
    setTimeout(function () {
      try {
        if (guestInput && typeof guestInput.focus === 'function') guestInput.focus();
      } catch (err) {}
    }, 40);
  }

  function submitQuickReserveForm() {
    var page = document.getElementById('hotel-rooms-page');
    var roomId = (document.getElementById('hr-quick-reserve-room-id') || {}).value || '';
    var guestInput = document.getElementById('hr-quick-reserve-guest-name');
    var fromInput = document.getElementById('hr-quick-reserve-from');
    var toInput = document.getElementById('hr-quick-reserve-to');
    var guestRaw = guestInput ? String(guestInput.value || '').trim() : '';
    var checkInDate = toDateISO(fromInput && fromInput.value);
    var checkOutDate = toDateISO(toInput && toInput.value);
    if (!roomId) {
      showToast('Room is missing.', true);
      return;
    }
    if (!guestRaw) {
      showToast('Guest name is required.', true);
      if (guestInput) guestInput.focus();
      return;
    }
    if (!checkInDate) {
      showToast('From date is required.', true);
      return;
    }
    if (!checkOutDate) checkOutDate = addDaysISO(checkInDate, 1);
    if (checkOutDate <= checkInDate) {
      showToast('To date must be after the From date.', true);
      return;
    }
    var names = splitGuestName(guestRaw);
    var saveBtn = document.getElementById('hr-quick-reserve-save');
    if (saveBtn) saveBtn.disabled = true;
    closeQuickReserveModal();
    setRoomStatus(page, roomId, 'reserved', {
      checkInDate: checkInDate,
      checkOutDate: checkOutDate,
      guestName: names.guestName,
      firstName: names.firstName,
      lastName: names.lastName
    });
    if (saveBtn) saveBtn.disabled = false;
  }

  function openRoomDetail(tile, root) {
    if (!tile) return;
    var roomId = tile.getAttribute('data-id') || '';
    if (!roomId) return;
    var url = '/hotel/rooms/' + encodeURIComponent(roomId);
    var checkIn = toDateISO(tile.getAttribute('data-check-in') || '');
    var boardDate = toDateISO(dateFilterValue(root) || '') || todayISO();
    var asOf = boardDate;
    if (checkIn && checkIn > boardDate) asOf = checkIn;
    if (asOf) url += '?date=' + encodeURIComponent(asOf);
    if (typeof window.deNavigateWithTransition === 'function') {
      window.deNavigateWithTransition(url);
    } else {
      window.location.href = url;
    }
  }

  function bindEvents(root) {
    if (!root || root.__hotelRoomsBound) return;
    root.__hotelRoomsBound = true;

    root.addEventListener(
      'pointerenter',
      function (event) {
        var tile = event.target.closest('.hotel-room-tile--has-guest');
        if (!tile || !root.contains(tile)) return;
        positionGuestTip(tile);
      },
      true
    );

    root.addEventListener(
      'pointerleave',
      function (event) {
        var tile = event.target.closest('.hotel-room-tile--has-guest');
        if (!tile || !root.contains(tile)) return;
        var related = event.relatedTarget;
        if (related && tile.contains(related)) return;
        clearGuestTipPosition(tile.querySelector('.hotel-room-guest-tip'));
      },
      true
    );

    root.addEventListener('click', function (event) {
      var reserveBtn = event.target.closest('#hotel-rooms-quick-reservations');
      if (reserveBtn && root.contains(reserveBtn)) {
        event.preventDefault();
        if (typeof global.deNavigateWithTransition === 'function') {
          global.deNavigateWithTransition('/hotel/reservations');
        } else {
          global.location.href = '/hotel/reservations';
        }
        return;
      }

      var roomsTrigger = event.target.closest('#hr-board-reserve-rooms-trigger');
      if (roomsTrigger && root.contains(roomsTrigger)) {
        /* Handled by bindBoardRoomsMultiSelect (combobox input + chevron). */
        return;
      }

      var kpiCard = event.target.closest('.hotel-kpi[data-kpi]');
      if (kpiCard && root.contains(kpiCard)) {
        event.preventDefault();
        var kpiKey = kpiCard.getAttribute('data-kpi') || 'total';
        if (kpiKey === 'total') {
          setStatusFilter(root, 'all');
        } else {
          var current = statusFilterValue(root);
          setStatusFilter(root, current === kpiKey ? 'all' : kpiKey);
        }
        return;
      }

      var floorPill = event.target.closest('.hotel-floor-pill');
      if (floorPill && root.contains(floorPill)) {
        $all('.hotel-floor-pill', root).forEach(function (btn) {
          var active = btn === floorPill;
          btn.classList.toggle('is-active', active);
          btn.setAttribute('aria-selected', active ? 'true' : 'false');
        });
        applyFilters(root);
        return;
      }

      var viewBtn = event.target.closest('.hotel-view-btn');
      if (viewBtn && root.contains(viewBtn)) {
        setView(root, viewBtn.getAttribute('data-view'));
        return;
      }

      var moreBtn = event.target.closest('.hotel-room-more');
      if (moreBtn && root.contains(moreBtn)) {
        event.preventDefault();
        event.stopPropagation();
        var tile = moreBtn.closest('[data-room-tile]');
        var menu = resolveRoomMenu(tile, moreBtn);
        var menuOpen =
          !!(menu && !menu.hidden && menu.classList.contains('is-fixed-open'));
        if (menuOpen) {
          closeRoomMenu();
        } else {
          openRoomMenu(moreBtn, menu);
        }
        return;
      }

      var tileClick = event.target.closest('[data-room-tile]');
      if (
        tileClick &&
        root.contains(tileClick) &&
        !event.target.closest('.hotel-room-menu') &&
        !event.target.closest('.hotel-room-more')
      ) {
        event.preventDefault();
        event.stopPropagation();
        closeRoomMenu();
        openRoomDetail(tileClick, root);
        return;
      }
    });

    root.addEventListener('keydown', function (event) {
      var kpiCard = event.target.closest('.hotel-kpi[data-kpi]');
      if (kpiCard && root.contains(kpiCard) && (event.key === 'Enter' || event.key === ' ')) {
        event.preventDefault();
        kpiCard.click();
        return;
      }

      var tile = event.target.closest('[data-room-tile]');
      if (!tile || !root.contains(tile)) return;
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        closeRoomMenu();
        openRoomDetail(tile, root);
      } else if (event.key === 'Escape') {
        closeRoomMenu();
      }
    });

    var search = $('#hotel-rooms-search', root);
    if (search) {
      search.addEventListener('input', function () {
        applyFilters(root);
      });
    }

    var dateInput = roomsDateInput(root);
    if (dateInput && !String(dateInput.value || '').trim()) {
      if (typeof global.setHotelDateValue === 'function') {
        global.setHotelDateValue(dateInput, todayISO());
      } else {
        dateInput.value = todayISO();
      }
    }
    if (typeof global.initHotelDatePickers === 'function') {
      global.initHotelDatePickers(root);
    }
    syncDateChipDisplay(root);
    if (dateInput && dateInput.getAttribute('data-hr-filter-bound') !== '1') {
      dateInput.setAttribute('data-hr-filter-bound', '1');
      dateInput.addEventListener('change', function () {
        applyFilters(root);
      });
    }

    var mergeForm = document.getElementById('hr-merge-form');
    if (mergeForm && mergeForm.getAttribute('data-hr-merge-bound') !== '1') {
      mergeForm.setAttribute('data-hr-merge-bound', '1');
      mergeForm.addEventListener('submit', function (event) {
        event.preventDefault();
        submitMergeForm(mergeForm);
      });
    }

    var transferForm = document.getElementById('hr-transfer-form');
    if (transferForm && transferForm.getAttribute('data-hr-transfer-bound') !== '1') {
      transferForm.setAttribute('data-hr-transfer-bound', '1');
      transferForm.addEventListener('submit', function (event) {
        event.preventDefault();
        submitTransferForm(transferForm);
      });
    }

    var extendForm = document.getElementById('hr-extend-form');
    if (extendForm && extendForm.getAttribute('data-hr-extend-bound') !== '1') {
      extendForm.setAttribute('data-hr-extend-bound', '1');
      extendForm.addEventListener('submit', function (event) {
        event.preventDefault();
        submitExtendForm(extendForm);
      });
    }

    var quickReserveForm = document.getElementById('hr-quick-reserve-form');
    if (quickReserveForm && quickReserveForm.getAttribute('data-hr-quick-reserve-bound') !== '1') {
      quickReserveForm.setAttribute('data-hr-quick-reserve-bound', '1');
      quickReserveForm.addEventListener('submit', function (event) {
        event.preventDefault();
        submitQuickReserveForm();
      });
    }

    var boardReserveForm = document.getElementById('hr-board-reserve-form');
    if (boardReserveForm && boardReserveForm.getAttribute('data-hr-board-reserve-bound') !== '1') {
      boardReserveForm.setAttribute('data-hr-board-reserve-bound', '1');
      boardReserveForm.addEventListener('submit', function (event) {
        event.preventDefault();
        submitBoardReserveForm(root, boardReserveForm);
      });
    }

    /* Menu is portaled to body — one document listener, latest handlers via globals
       so soft-nav script reloads cannot leave the menu stuck open. */
    if (!document.__hotelRoomsMenuDocBound) {
      document.__hotelRoomsMenuDocBound = true;
      document.addEventListener('click', function (event) {
        if (typeof global.__hotelRoomsOnDocClick === 'function') {
          global.__hotelRoomsOnDocClick(event);
        }
      });
      window.addEventListener(
        'scroll',
        function () {
          if (typeof global.__hotelRoomsOnDocScroll === 'function') {
            global.__hotelRoomsOnDocScroll();
          }
        },
        true
      );
      window.addEventListener('resize', function () {
        if (typeof global.__hotelRoomsOnDocScroll === 'function') {
          global.__hotelRoomsOnDocScroll({ force: true });
        }
      });
      document.addEventListener('keydown', function (event) {
        if (event.key !== 'Escape') return;
        if (typeof global.__hotelRoomsOnDocEscape === 'function') {
          global.__hotelRoomsOnDocEscape(event);
        }
      });
    }
  }

  function onHotelRoomsDocClick(event) {
    var mergeCheckout = event.target.closest('[data-merge-checkout]');
    if (mergeCheckout) {
      event.preventDefault();
      event.stopPropagation();
      closeRoomMenu();
      checkoutMergeGroup(
        mergeCheckout.getAttribute('data-merge-checkout'),
        mergeCheckout.getAttribute('data-merge-rooms')
      );
      return;
    }
    var actionBtn = event.target.closest('.hotel-room-menu [data-room-action]');
    if (actionBtn) {
      event.preventDefault();
      event.stopPropagation();
      var menu = actionBtn.closest('.hotel-room-menu');
      var tile = tileForRoomMenu(menu);
      var page = document.getElementById('hotel-rooms-page');
      var nextAction = actionBtn.getAttribute('data-room-action');
      closeRoomMenu();
      if (page && tile && nextAction) {
        handleRoomMenuAction(page, tile, nextAction);
      }
      return;
    }
    var mergeClose = event.target.closest('[data-hr-merge-close]');
    if (mergeClose) {
      event.preventDefault();
      closeMergeModal();
      return;
    }
    var transferClose = event.target.closest('[data-hr-transfer-close]');
    if (transferClose) {
      event.preventDefault();
      closeTransferModal();
      return;
    }
    var extendClose = event.target.closest('[data-hr-extend-close]');
    if (extendClose) {
      event.preventDefault();
      closeExtendModal();
      return;
    }
    var quickReserveClose = event.target.closest('[data-hr-quick-reserve-close]');
    if (quickReserveClose) {
      event.preventDefault();
      closeQuickReserveModal();
      return;
    }
    var boardReserveClose = event.target.closest('[data-hr-board-reserve-close]');
    if (boardReserveClose) {
      event.preventDefault();
      closeBoardReserveModal();
      return;
    }
    var mergeModal = document.getElementById('hr-merge-modal');
    if (mergeModal && !mergeModal.hidden && event.target === mergeModal) {
      closeMergeModal();
      return;
    }
    if (mergeModal && !mergeModal.hidden) {
      var mergeRoomsSelect = document.getElementById('hr-merge-rooms-select');
      if (
        mergeRoomsSelect &&
        !mergeRoomsSelect.contains(event.target) &&
        document.getElementById('hr-merge-rooms-menu') &&
        !document.getElementById('hr-merge-rooms-menu').hidden
      ) {
        closeMergeRoomsMenu(document.getElementById('hr-merge-form'));
      }
    }
    var transferModal = document.getElementById('hr-transfer-modal');
    if (transferModal && !transferModal.hidden && event.target === transferModal) {
      closeTransferModal();
      return;
    }
    var extendModal = document.getElementById('hr-extend-modal');
    if (extendModal && !extendModal.hidden && event.target === extendModal) {
      closeExtendModal();
      return;
    }
    var quickReserveModal = document.getElementById('hr-quick-reserve-modal');
    if (quickReserveModal && !quickReserveModal.hidden && event.target === quickReserveModal) {
      closeQuickReserveModal();
      return;
    }
    var boardReserveModal = document.getElementById('hr-board-reserve-modal');
    if (boardReserveModal && !boardReserveModal.hidden && event.target === boardReserveModal) {
      closeBoardReserveModal();
      return;
    }
    if (boardReserveModal && !boardReserveModal.hidden) {
      var roomsSelect = document.getElementById('hr-board-reserve-rooms-select');
      if (
        roomsSelect &&
        !roomsSelect.contains(event.target) &&
        document.getElementById('hr-board-reserve-rooms-menu') &&
        !document.getElementById('hr-board-reserve-rooms-menu').hidden
      ) {
        closeBoardRoomsMenu(document.getElementById('hr-board-reserve-form'));
      }
    }
    var open =
      document.__hotelRoomsOpenMenu ||
      document.querySelector('.hotel-room-menu.is-fixed-open');
    if (!open) return;
    if (event.target.closest('.hotel-room-menu') || event.target.closest('.hotel-room-more')) {
      return;
    }
    closeRoomMenu();
  }

  function onHotelRoomsDocEscape() {
    var boardReserveModal = document.getElementById('hr-board-reserve-modal');
    if (boardReserveModal && !boardReserveModal.hidden) {
      var roomsMenu = document.getElementById('hr-board-reserve-rooms-menu');
      if (roomsMenu && !roomsMenu.hidden) {
        closeBoardRoomsMenu(document.getElementById('hr-board-reserve-form'));
        return;
      }
      closeBoardReserveModal();
      return;
    }
    var transferModal = document.getElementById('hr-transfer-modal');
    if (transferModal && !transferModal.hidden) {
      closeTransferModal();
      return;
    }
    var extendModal = document.getElementById('hr-extend-modal');
    if (extendModal && !extendModal.hidden) {
      if (typeof global.closeHotelDatePickers === 'function') {
        global.closeHotelDatePickers();
      }
      closeExtendModal();
      return;
    }
    var quickReserveModal = document.getElementById('hr-quick-reserve-modal');
    if (quickReserveModal && !quickReserveModal.hidden) {
      if (typeof global.closeHotelDatePickers === 'function') {
        global.closeHotelDatePickers();
      }
      closeQuickReserveModal();
      return;
    }
    var mergeModal = document.getElementById('hr-merge-modal');
    if (mergeModal && !mergeModal.hidden) {
      var mergeRoomsMenu = document.getElementById('hr-merge-rooms-menu');
      if (mergeRoomsMenu && !mergeRoomsMenu.hidden) {
        closeMergeRoomsMenu(document.getElementById('hr-merge-form'));
        return;
      }
      closeMergeModal();
      return;
    }
    if (
      document.__hotelRoomsOpenMenu ||
      document.querySelector('.hotel-room-menu.is-fixed-open')
    ) {
      closeRoomMenu();
    }
  }

  function onHotelRoomsDocScroll(opts) {
    opts = opts || {};
    if (!opts.force && Date.now() < roomMenuScrollGuardUntil) return;
    if (
      document.__hotelRoomsOpenMenu ||
      document.querySelector('.hotel-room-menu.is-fixed-open')
    ) {
      closeRoomMenu();
    }
    $all('.hotel-room-guest-tip--fixed').forEach(clearGuestTipPosition);
  }

  global.closeHotelRoomMenu = closeRoomMenu;
  global.__hotelRoomsOnDocClick = onHotelRoomsDocClick;
  global.__hotelRoomsOnDocEscape = onHotelRoomsDocEscape;
  global.__hotelRoomsOnDocScroll = onHotelRoomsDocScroll;
  global.__hotelRoomsClearGuestTip = clearGuestTipPosition;

  global.hotelRoomsStatusChanged = function () {
    var root = document.getElementById('hotel-rooms-page');
    if (!root) return;
    syncKpiSelection(root);
    applyFilters(root);
  };

  function initHotelRoomsPage() {
    var root = document.getElementById('hotel-rooms-page');
    if (!root) return;
    boundRoot = root;
    global.closeHotelRoomMenu = closeRoomMenu;
    global.__hotelRoomsOnDocClick = onHotelRoomsDocClick;
    global.__hotelRoomsOnDocEscape = onHotelRoomsDocEscape;
    global.__hotelRoomsOnDocScroll = onHotelRoomsDocScroll;
    global.__hotelRoomsClearGuestTip = clearGuestTipPosition;
    closeRoomMenu();
    resolveApi();
    bindEvents(root);
    if (typeof global.initSuFilterListboxes === 'function') {
      global.initSuFilterListboxes();
    }
    /* Re-sync overdue pulse after standard checkout time passes without a reload. */
    if (root.__hotelAttentionTimer) {
      clearInterval(root.__hotelAttentionTimer);
    }
    root.__hotelAttentionTimer = setInterval(function () {
      if (!root.isConnected) {
        clearInterval(root.__hotelAttentionTimer);
        root.__hotelAttentionTimer = null;
        return;
      }
      if (document.hidden) return;
      refreshEffectiveStatuses(root, dateFilterValue(root));
    }, 60000);
    loadRooms(root);
  }

  global.initHotelRoomsPage = initHotelRoomsPage;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initHotelRoomsPage);
  } else {
    initHotelRoomsPage();
  }
})(window);
