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

  /** Primary tile may be an empty shell after merge — pull guest from members. */
  function guestNameForBoardRoom(room, allRooms) {
    return guestDisplayName(guestStayForBoardRoom(room, allRooms));
  }

  function guestStayForBoardRoom(room, allRooms) {
    var own = room && room.stay && typeof room.stay === 'object' ? room.stay : null;
    if (guestDisplayName(own)) return own;
    var groupId = room && room.mergeGroupId ? String(room.mergeGroupId) : '';
    if (!groupId) return own;
    var rooms = allRooms || [];
    var best = own;
    for (var i = 0; i < rooms.length; i++) {
      var peer = rooms[i];
      if (!peer || peer.id === room.id) continue;
      if (String(peer.mergeGroupId || '') !== groupId) continue;
      var peerStay = peer.stay && typeof peer.stay === 'object' ? peer.stay : null;
      if (guestDisplayName(peerStay)) return peerStay;
      if (!best && peerStay) best = peerStay;
    }
    return best;
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
    $all('.hotel-kpi', root).forEach(function (card) {
      var key = card.getAttribute('data-kpi');
      var el = card.querySelector('[data-kpi-value]');
      if (!el || !key) return;
      el.textContent = String(data[key] != null ? data[key] : 0);
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
    if (!room || room.isMergeMember) return false;
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
  }

  function refreshEffectiveStatuses(root, dateIso) {
    $all('[data-room-tile]', root).forEach(function (tile) {
      applyTileEffectiveStatus(tile, effectiveStatusForTile(tile, dateIso));
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
        /* Occupied is only offered from Vacant — already-occupied is redundant. */
        if (key === 'occupied' && status !== 'vacant') return '';
        if (key === 'dirty' && status === 'dirty') {
          return (
            '<button type="button" class="hotel-room-menu-item" role="menuitem" data-room-action="vacant">Cleaned</button>'
          );
        }
        var selected = key === status ? ' is-current' : '';
        return (
          '<button type="button" class="hotel-room-menu-item' +
          selected +
          '" role="menuitem" data-room-action="' +
          key +
          '">' +
          escapeHtml(STATUS_LABELS[key]) +
          '</button>'
        );
      }).filter(Boolean)
    );
    return items.join('');
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

    var sections = [];
    var seen = {};
    floors.forEach(function (f) {
      if (!f || !f.id || seen[f.id]) return;
      seen[f.id] = true;
      sections.push({ id: f.id, title: f.name || f.id, rooms: [] });
    });
    rooms.forEach(function (room) {
      var fid = room.floorId || '_unassigned';
      if (!seen[fid]) {
        seen[fid] = true;
        sections.push({
          id: fid,
          title: floorNameById(floors, fid) || 'Unassigned',
          rooms: []
        });
      }
    });
    sections.forEach(function (sec) {
      sec.rooms = rooms.filter(function (r) {
        return (r.floorId || '_unassigned') === sec.id;
      });
    });
    sections = sections.filter(function (sec) {
      return sec.rooms.length > 0;
    });

    var html = '';
    sections.forEach(function (sec) {
      html +=
        '<section class="hotel-floor-section" data-floor-section="' +
        escapeHtml(sec.id) +
        '">' +
        '<h2 class="hotel-floor-section-title">' +
        escapeHtml(sec.title) +
        '</h2>' +
        '<div class="hotel-rooms-grid">';
      sec.rooms.forEach(function (room) {
        /* Members share the primary tile — hide them on the board. */
        if (room.isMergeMember) return;
        var status = mapStatus(room.status);
        var stay = room.stay && typeof room.stay === 'object' ? room.stay : null;
        var tipStay = guestStayForBoardRoom(room, rooms) || stay;
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
        var guestSearch = staySearchText(tipStay || stay);
        var guestName = guestDisplayName(tipStay) || guestNameForBoardRoom(room, rooms);
        if (guestName && guestSearch.indexOf(guestName) === -1) {
          guestSearch = (guestName + ' ' + guestSearch).trim();
        }
        var isMerged = !!(room.mergeGroupId || room.isMergePrimary);
        var partners = Array.isArray(room.mergePartnerNumbers)
          ? room.mergePartnerNumbers
          : [];
        var displayNumber =
          room.isMergePrimary && room.mergeLabel
            ? room.mergeLabel
            : room.isMergePrimary && partners.length
              ? String(room.number || '') + ' + ' + partners.join(' + ')
              : room.number;
        var searchNumbers = [String(room.number || '')]
          .concat(partners.map(function (n) {
            return String(n || '');
          }))
          .filter(Boolean)
          .join(' ');
        var ariaLabel =
          'Room ' +
          displayNumber +
          (guestName ? ', ' + guestName : '') +
          ', ' +
          (STATUS_LABELS[status] || status);
        html +=
          '<article class="hotel-room-tile hotel-room-tile--' +
          status +
          (isMerged ? ' hotel-room-tile--merged' : '') +
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
          '" data-guest-search="' +
          escapeHtml(guestSearch) +
          '" data-guest-name="' +
          escapeHtml(guestName) +
          '" data-merge="' +
          (isMerged ? '1' : '0') +
          '" data-merge-member="0" data-merge-primary="' +
          (room.isMergePrimary ? '1' : '0') +
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
          '<div class="hotel-room-number' +
          (isMerged ? ' hotel-room-number--merged' : '') +
          '">' +
          escapeHtml(displayNumber) +
          '</div>' +
          '<div class="hotel-room-type">' +
          escapeHtml(room.roomTypeLabel || room.roomType || '') +
          '</div>' +
          (isMerged
            ? '<div class="hotel-room-merge-tag">Merged bill</div>'
            : '') +
          '<span class="hotel-room-badge">' +
          escapeHtml(STATUS_LABELS[status] || status) +
          '</span>' +
          (guestName ? guestTipHtml(tipStay, guestName) : '') +
          '</article>';
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
        var typeLabel = normalize((tile.querySelector('.hotel-room-type') || {}).textContent);
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
    var modal = document.getElementById('hr-merge-modal');
    if (!modal) return;
    modal.hidden = true;
    modal.setAttribute('hidden', '');
    modal.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('hr-merge-open');
  }

  function closeTransferModal() {
    var modal = document.getElementById('hr-transfer-modal');
    if (!modal) return;
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

  function openTransferModal(fromRoomId) {
    var modal = document.getElementById('hr-transfer-modal');
    var form = document.getElementById('hr-transfer-form');
    var fromInput = document.getElementById('hr-transfer-from');
    var guestInput = document.getElementById('hr-transfer-guest');
    var toSelect = document.getElementById('hr-transfer-to');
    var hint = document.getElementById('hr-transfer-hint');
    var fromHidden = document.getElementById('hr-transfer-from-id');
    if (!modal || !form || !toSelect) {
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
    var note = document.getElementById('hr-transfer-note');
    if (note) note.value = '';
    toSelect.innerHTML = '';
    var placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = 'Select vacant room…';
    toSelect.appendChild(placeholder);
    var count = 0;
    ((currentLayout && currentLayout.rooms) || []).forEach(function (room) {
      if (!room) return;
      if (String(room.id) === String(source.id)) return;
      if (mapStatus(room.status) !== 'vacant') return;
      if (room.isMergeMember) return;
      var opt = document.createElement('option');
      opt.value = room.id;
      opt.textContent =
        'Room ' +
        (room.number || '') +
        (room.roomTypeLabel ? ' — ' + room.roomTypeLabel : '');
      toSelect.appendChild(opt);
      count += 1;
    });
    if (hint) {
      hint.textContent = count
        ? 'Only vacant rooms are listed. Source room becomes Dirty after transfer.'
        : 'No vacant rooms available for transfer.';
      hint.classList.toggle('is-error', !count);
    }
    modal.hidden = false;
    modal.removeAttribute('hidden');
    modal.setAttribute('aria-hidden', 'false');
    document.body.classList.add('hr-transfer-open');
    try {
      toSelect.focus();
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
    var note = (form.note && form.note.value) || '';
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

  function openMergeModal(fromRoomId) {
    var modal = document.getElementById('hr-merge-modal');
    var form = document.getElementById('hr-merge-form');
    var fromInput = document.getElementById('hr-merge-from');
    var toSelect = document.getElementById('hr-merge-to');
    var hint = document.getElementById('hr-merge-hint');
    var fromHidden = document.getElementById('hr-merge-from-id');
    if (!modal || !form || !toSelect) {
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
    if (fromHidden) fromHidden.value = source.id || '';
    if (fromInput) {
      fromInput.value =
        'Room ' +
        (source.number || '') +
        (source.roomTypeLabel ? ' — ' + source.roomTypeLabel : '');
    }
    var note = document.getElementById('hr-merge-note');
    if (note) note.value = '';
    toSelect.innerHTML = '';
    var placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = 'Select primary room…';
    toSelect.appendChild(placeholder);
    var count = 0;
    ((currentLayout && currentLayout.rooms) || []).forEach(function (room) {
      if (!room) return;
      if (String(room.id) === String(source.id)) return;
      if (room.isMergeMember) return;
      var opt = document.createElement('option');
      opt.value = room.id;
      opt.textContent =
        'Room ' +
        (room.number || '') +
        (room.roomTypeLabel ? ' — ' + room.roomTypeLabel : '') +
        (STATUS_LABELS[mapStatus(room.status)]
          ? ' · ' + STATUS_LABELS[mapStatus(room.status)]
          : '') +
        (room.isMergePrimary ? ' (primary)' : '');
      toSelect.appendChild(opt);
      count += 1;
    });
    if (hint) {
      hint.textContent = count
        ? 'Any rooms can be merged onto one primary bill. Unmerge does not split the bill back.'
        : 'No other rooms available to merge into.';
      hint.classList.toggle('is-error', !count);
    }
    modal.hidden = false;
    modal.removeAttribute('hidden');
    modal.setAttribute('aria-hidden', 'false');
    document.body.classList.add('hr-merge-open');
    try {
      toSelect.focus();
    } catch (err) {}
  }

  function submitMergeForm(form) {
    var fromId =
      (document.getElementById('hr-merge-from-id') || {}).value || '';
    var toId = (form.toRoomId && form.toRoomId.value) || '';
    if (!fromId || !toId) {
      showToast('Select a primary room to merge into.', true);
      return;
    }
    var note = (form.note && form.note.value) || '';
    var saveBtn = document.getElementById('hr-merge-save');
    if (saveBtn) saveBtn.disabled = true;
    var page = document.getElementById('hotel-rooms-page');
    fetch(roomDetailApi(fromId), {
      method: 'PUT',
      credentials: 'same-origin',
      headers: apiHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({
        action: 'merge_rooms',
        fromRoomId: fromId,
        toRoomId: toId,
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
          throw new Error((result.data && result.data.error) || 'Merge failed.');
        }
        closeMergeModal();
        var primary = result.data.primaryRoom || result.data.room;
        showToast(
          'Rooms merged. Billing is on Room ' +
            ((primary && primary.number) || toId) +
            '.'
        );
        return loadRooms(page);
      })
      .catch(function (err) {
        showToast(err.message || 'Merge failed.', true);
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

  function handleRoomMenuAction(page, tile, action) {
    var roomId = tile && tile.getAttribute('data-id');
    if (!roomId || !action) return;
    if (STATUS_KEYS.indexOf(action) !== -1) {
      setRoomStatus(page, roomId, action);
      return;
    }
    if (action === 'merge') {
      openMergeModal(roomId);
      return;
    }
    if (action === 'transfer') {
      openTransferModal(roomId);
      return;
    }
    if (action === 'unmerge') {
      if (
        !window.confirm(
          'Unmerge this room from the shared bill? Folio charges stay on the primary.'
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
          'Unmerge all rooms in this billing group? Folio charges stay on the primary.'
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

  function setRoomStatus(root, roomId, nextStatus) {
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
      body.checkInDate = asOf;
      body.checkOutDate = addDaysISO(asOf, 1);
      body.asOf = asOf;
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
        var roomId = tileClick.getAttribute('data-id') || '';
        if (!roomId) return;
        var url = '/hotel/rooms/' + encodeURIComponent(roomId);
        if (typeof window.deNavigateWithTransition === 'function') {
          window.deNavigateWithTransition(url);
        } else {
          window.location.href = url;
        }
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
        var roomId = tile.getAttribute('data-id') || '';
        if (!roomId) return;
        var url = '/hotel/rooms/' + encodeURIComponent(roomId);
        if (typeof window.deNavigateWithTransition === 'function') {
          window.deNavigateWithTransition(url);
        } else {
          window.location.href = url;
        }
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
    var mergeModal = document.getElementById('hr-merge-modal');
    if (mergeModal && !mergeModal.hidden && event.target === mergeModal) {
      closeMergeModal();
      return;
    }
    var transferModal = document.getElementById('hr-transfer-modal');
    if (transferModal && !transferModal.hidden && event.target === transferModal) {
      closeTransferModal();
      return;
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
    var transferModal = document.getElementById('hr-transfer-modal');
    if (transferModal && !transferModal.hidden) {
      closeTransferModal();
      return;
    }
    var mergeModal = document.getElementById('hr-merge-modal');
    if (mergeModal && !mergeModal.hidden) {
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
    loadRooms(root);
  }

  global.initHotelRoomsPage = initHotelRoomsPage;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initHotelRoomsPage);
  } else {
    initHotelRoomsPage();
  }
})(window);
