/**
 * Hotel → Room Onboarding detail page.
 * Soft-nav safe: document-level delegation (script may load once and skip on revisit).
 */
(function (global) {
  'use strict';

  var STATUS_LABELS = {
    vacant: 'Vacant',
    occupied: 'Occupied',
    reserved: 'Reserved',
    dirty: 'Dirty',
    out_of_order: 'Out of order'
  };
  var STATUS_SUBTITLES = {
    vacant: 'Ready for check-in',
    occupied: 'Occupied by Guest',
    reserved: 'Reserved for Arrival',
    dirty: 'Waiting for Cleaning',
    out_of_order: 'Out of service'
  };
  var DEFAULT_RATES = {
    premium_without_balcony: 3500,
    premium_deluxe_balcony: 4500,
    premium_suite_tub: 7500
  };
  var AIRPORT_PICKUP_RATE = 1500;

  var CGST_RATE = 0.025;
  var UGST_RATE = 0.025;
  var GSTIN_RE = /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$/;

  function normalizeGstin(value) {
    return String(value || '')
      .replace(/\s+/g, '')
      .toUpperCase();
  }

  function isValidGstin(value) {
    var gst = normalizeGstin(value);
    return !gst || GSTIN_RE.test(gst);
  }

  function bindAgencyGstInput(input) {
    if (!input || input.getAttribute('data-gstin-bound') === '1') return;
    input.setAttribute('data-gstin-bound', '1');
    input.setAttribute('maxlength', '15');
    input.setAttribute('spellcheck', 'false');
    input.addEventListener('input', function () {
      var cleaned = normalizeGstin(input.value).replace(/[^0-9A-Z]/g, '');
      if (cleaned.length > 15) cleaned = cleaned.slice(0, 15);
      if (input.value !== cleaned) input.value = cleaned;
      input.classList.toggle('is-invalid', !!cleaned && !isValidGstin(cleaned));
    });
    input.addEventListener('blur', function () {
      var gst = normalizeGstin(input.value);
      input.value = gst;
      input.classList.toggle('is-invalid', !!gst && !isValidGstin(gst));
    });
  }

  function agencyGstValidationError(form) {
    if (!form || !form.elements.agencyGst) return '';
    var gst = normalizeGstin(form.elements.agencyGst.value);
    form.elements.agencyGst.value = gst;
    if (gst && !isValidGstin(gst)) {
      return 'GST must be a valid 15-character GSTIN (e.g. 35AANFH8592H1ZS).';
    }
    return '';
  }

  function applyTaxRates(rates) {
    if (!rates || typeof rates !== 'object') return;
    if (rates.cgst != null && isFinite(Number(rates.cgst))) {
      CGST_RATE = Number(rates.cgst);
    } else if (rates.cgst_pct != null && isFinite(Number(rates.cgst_pct))) {
      CGST_RATE = Number(rates.cgst_pct) / 100;
    }
    if (rates.ugst != null && isFinite(Number(rates.ugst))) {
      UGST_RATE = Number(rates.ugst);
    } else if (rates.ugst_pct != null && isFinite(Number(rates.ugst_pct))) {
      UGST_RATE = Number(rates.ugst_pct) / 100;
    }
  }

  function applyTariffRates(rates) {
    if (!rates || typeof rates !== 'object') return;
    function money(key, fallback) {
      var n = Number(rates[key]);
      return isFinite(n) && n >= 0 ? n : fallback;
    }
    DEFAULT_RATES.premium_without_balcony = money(
      'premium_without_balcony',
      DEFAULT_RATES.premium_without_balcony
    );
    DEFAULT_RATES.premium_deluxe_balcony = money(
      'premium_deluxe_balcony',
      DEFAULT_RATES.premium_deluxe_balcony
    );
    DEFAULT_RATES.premium_suite_tub = money(
      'premium_suite_tub',
      DEFAULT_RATES.premium_suite_tub
    );
    AIRPORT_PICKUP_RATE = money('airport_pickup', AIRPORT_PICKUP_RATE);
    if (SPECIAL_CHARGES) {
      if (SPECIAL_CHARGES.earlyCheckin) {
        SPECIAL_CHARGES.earlyCheckin.defaultRate = money(
          'early_checkin',
          SPECIAL_CHARGES.earlyCheckin.defaultRate
        );
      }
      if (SPECIAL_CHARGES.lateCheckout) {
        SPECIAL_CHARGES.lateCheckout.defaultRate = money(
          'late_checkout',
          SPECIAL_CHARGES.lateCheckout.defaultRate
        );
      }
      if (SPECIAL_CHARGES.extraBed) {
        SPECIAL_CHARGES.extraBed.defaultRate = money(
          'extra_mattress',
          SPECIAL_CHARGES.extraBed.defaultRate
        );
      }
    }
  }

  function loadHotelTaxRates(done) {
    fetch('/hotel/api/settings', {
      credentials: 'same-origin',
      headers: { Accept: 'application/json' },
      cache: 'no-store'
    })
      .then(function (resp) {
        if (!resp.ok) throw new Error('tax rates');
        return resp.json();
      })
      .then(function (data) {
        if (data && data.ok && data.taxRates) applyTaxRates(data.taxRates);
        if (data && data.ok && data.tariffRates) applyTariffRates(data.tariffRates);
        if (typeof done === 'function') done();
      })
      .catch(function () {
        if (typeof done === 'function') done();
      });
  }

  var lastRoom = null;

  function $(sel, root) {
    return (root || document).querySelector(sel);
  }

  function $all(sel, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(sel));
  }

  function normalize(value) {
    return String(value || '')
      .trim()
      .toLowerCase()
      .replace(/\s+/g, '_')
      .replace(/-/g, '_');
  }

  function mapStatus(status) {
    var s = normalize(status);
    if (s === 'available' || s === 'free' || s === 'clean') return 'vacant';
    if (s === 'ooo' || s === 'oos') return 'out_of_order';
    if (!STATUS_LABELS[s]) return 'vacant';
    return s;
  }

  function checkinBlockedReason(room, root) {
    var status = mapStatus(
      (room && (room.inventoryStatus || room.status)) ||
        (root && root.getAttribute('data-room-status')) ||
        ''
    );
    if (status === 'dirty') {
      return 'Room is dirty. Mark it Cleaned before check-in.';
    }
    return '';
  }

  function pageRoot() {
    return document.getElementById('hotel-room-detail-page');
  }

  function dash(value) {
    var text = String(value == null ? '' : value).trim();
    return text || '—';
  }

  function stayAgencyBillFlags(stay) {
    if (!stay || typeof stay !== 'object') return { room: false, fb: false };
    var hasRoom =
      Object.prototype.hasOwnProperty.call(stay, 'agencyRoomBilling') ||
      Object.prototype.hasOwnProperty.call(stay, 'agency_room_billing');
    var hasFb =
      Object.prototype.hasOwnProperty.call(stay, 'agencyFbBilling') ||
      Object.prototype.hasOwnProperty.call(stay, 'agency_fb_billing');
    if (hasRoom || hasFb) {
      return {
        room: !!(stay.agencyRoomBilling || stay.agency_room_billing),
        fb: !!(stay.agencyFbBilling || stay.agency_fb_billing)
      };
    }
    var legacy = !!(stay.agencyBilling || stay.agency_billing);
    return { room: legacy, fb: legacy };
  }

  function formAgencyBillFlags(form) {
    if (!form || !form.elements) return { room: false, fb: false };
    var roomEl = form.elements.agencyRoomBilling;
    var fbEl = form.elements.agencyFbBilling;
    if (roomEl || fbEl) {
      return {
        room: !!(roomEl && roomEl.checked),
        fb: !!(fbEl && fbEl.checked)
      };
    }
    var on = !!(form.elements.agencyBilling && form.elements.agencyBilling.checked);
    return { room: on, fb: on };
  }

  function setFormAgencyBillFlags(form, stay) {
    if (!form || !form.elements) return;
    var flags = stayAgencyBillFlags(stay);
    if (form.elements.agencyRoomBilling) {
      form.elements.agencyRoomBilling.checked = !!flags.room;
    }
    if (form.elements.agencyFbBilling) {
      form.elements.agencyFbBilling.checked = !!flags.fb;
    }
    if (form.elements.agencyBilling) {
      form.elements.agencyBilling.checked = !!(flags.room || flags.fb);
    }
  }

  function clearFormAgencyBillFlags(form) {
    if (!form || !form.elements) return;
    ['agencyRoomBilling', 'agencyFbBilling', 'agencyBilling'].forEach(function (name) {
      if (form.elements[name]) form.elements[name].checked = false;
    });
  }

  function collectFormAgencyBilling(form) {
    var flags = formAgencyBillFlags(form);
    return {
      agencyRoomBilling: flags.room,
      agencyFbBilling: flags.fb,
      agencyBilling: !!(flags.room || flags.fb)
    };
  }

  function toggleAgencyBillingHint(hint, show) {
    if (!hint) return;
    hint.hidden = !show;
    if (show) hint.removeAttribute('hidden');
    else hint.setAttribute('hidden', '');
  }

  function guestNameWithoutTitle(value) {
    return String(value || '')
      .trim()
      .replace(/^(Mr|Mrs|Ms|Miss|Dr|Mx)\.?\s+/i, '')
      .replace(/\s+/g, ' ')
      .trim();
  }

  function idDocumentPersonName(source) {
    if (source && typeof source === 'object') {
      var first = String(source.firstName || source.first_name || '').trim();
      var last = String(source.lastName || source.last_name || '').trim();
      var joined = [first, last].filter(Boolean).join(' ');
      if (joined) return joined;
      return guestNameWithoutTitle(
        source.guestName || source.guest_name || source.name || ''
      );
    }
    return guestNameWithoutTitle(source);
  }

  function idDocumentDisplayLabel(name, idType, storedName) {
    var person = idDocumentPersonName(name);
    var type = String(idType || '').replace(/\s+/g, ' ').trim();
    var parts = [];
    if (person) parts.push(person);
    if (type) parts.push(type);
    if (parts.length) return parts.join(' ') + '.pdf';
    var stored = String(storedName || '').trim();
    if (
      stored &&
      !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.(webp|pdf)$/i.test(
        stored
      ) &&
      !/^[0-9a-f]{32}\.(webp|pdf)$/i.test(stored)
    ) {
      return stored;
    }
    return stored;
  }

  function setIdDocumentNameLink(dd, label, path) {
    if (!dd) return;
    dd.innerHTML = '';
    var text = dash(label);
    if (path && text && text !== '—') {
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'hrd-id-doc-link';
      btn.setAttribute('data-hrd-id-view', '1');
      btn.setAttribute('data-id-path', path);
      btn.setAttribute('aria-label', 'View ' + text);
      btn.title = text;
      btn.textContent = text;
      dd.appendChild(btn);
      return;
    }
    dd.textContent = text;
  }

  function checkinGuestFullName(form) {
    if (!form) return '';
    var first = form.elements.firstName && form.elements.firstName.value;
    var last = form.elements.lastName && form.elements.lastName.value;
    var joined = [first, last].filter(Boolean).join(' ').trim();
    if (joined) return joined;
    if (form.elements.idNumber && form.elements.idNumber.value) {
      return guestNameWithoutTitle(form.elements.idNumber.value);
    }
    return idDocumentPersonName((lastRoom && lastRoom.stay) || null);
  }

  function checkinIdType(form) {
    if (!form || !form.elements.idType) return '';
    return String(form.elements.idType.value || '').trim();
  }

  function extraGuestIdMeta(row) {
    var nameInput = row && row.querySelector('[data-extra-guest-name]');
    var typeInput = row && row.querySelector('[data-extra-guest-id-type]');
    return {
      name: nameInput ? String(nameInput.value || '').trim() : '',
      idType: typeInput ? String(typeInput.value || '').trim() : ''
    };
  }

  function guestCardDisplayName(stay) {
    if (!stay || typeof stay !== 'object') return '';
    var name = String(stay.guestName || stay.guest_name || '').trim();
    if (name) return name;
    return [stay.title, stay.firstName || stay.first_name, stay.lastName || stay.last_name]
      .map(function (part) {
        return String(part || '').trim();
      })
      .filter(Boolean)
      .join(' ');
  }

  function readRoomBootstrap(root) {
    var node =
      (root && $('#hrd-room-bootstrap', root)) ||
      document.getElementById('hrd-room-bootstrap');
    if (!node) return null;
    try {
      var parsed = JSON.parse(node.textContent || '');
      return parsed && typeof parsed === 'object' ? parsed : null;
    } catch (err) {
      return null;
    }
  }

  function stayReservationDisplayId(stay) {
    if (!stay) return '';
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

  function todayISO() {
    if (typeof global.hotelDateTodayISO === 'function') {
      return global.hotelDateTodayISO();
    }
    var d = new Date();
    var m = String(d.getMonth() + 1).padStart(2, '0');
    var day = String(d.getDate()).padStart(2, '0');
    return d.getFullYear() + '-' + m + '-' + day;
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
    if (!inDate) return day === today;
    if (day < inDate) return false;
    /* Include checkout day — guest remains in-house until FO checks them out. */
    if (outDate) return day <= outDate;
    if (inDate > today) return day === inDate;
    return day <= today;
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

  function existingReservationWindow(room) {
    var stay = room && room.stay && typeof room.stay === 'object' ? room.stay : null;
    if (!stay) return null;
    var checkIn = toDateISO(stay.checkInDate || stay.check_in_date);
    var checkOut = toDateISO(stay.checkOutDate || stay.check_out_date);
    if (!checkIn) return null;
    if (!checkOut) checkOut = addDaysISO(checkIn, 1);
    return { checkIn: checkIn, checkOut: checkOut };
  }

  function effectiveStatusForDate(inventoryStatus, checkIn, checkOut, dateIso, todayIso) {
    var inventory = mapStatus(inventoryStatus);
    var day = toDateISO(dateIso) || todayISO();
    var today = toDateISO(todayIso) || todayISO();
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

  function headerAsOfDate(root) {
    var headerDate = $('#hrd-header-date', root);
    var value = headerDate ? String(headerDate.value || '').trim() : '';
    return toDateISO(value) || todayISO();
  }

  function prettyDateISO(iso) {
    var parts = String(iso || '').split('-');
    if (parts.length !== 3) return String(iso || '');
    var months = [
      'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
      'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'
    ];
    var mi = Number(parts[1]) - 1;
    if (mi < 0 || mi >= 12) return String(iso || '');
    return Number(parts[2]) + ' ' + months[mi] + ' ' + parts[0];
  }

  function formatTimeLabel12h(raw) {
    var text = String(raw || '').trim();
    if (!text) return '';
    if (typeof global.formatHotelTimeLabel === 'function') {
      var labeled = global.formatHotelTimeLabel(text);
      if (labeled) return labeled;
    }
    var m = text.match(/^(\d{1,2}):(\d{2})\s*(AM|PM)?$/i);
    if (!m) return text;
    var h = Number(m[1]);
    var min = m[2];
    var period = (m[3] || '').toUpperCase();
    if (!period) {
      if (h === 0) {
        h = 12;
        period = 'AM';
      } else if (h === 12) {
        period = 'PM';
      } else if (h > 12) {
        h -= 12;
        period = 'PM';
      } else {
        period = 'AM';
      }
    }
    return String(h).padStart(2, '0') + ':' + min + ' ' + period;
  }

  function timeFromCheckedInAt(raw) {
    var text = String(raw || '').trim();
    if (!text) return '';
    var m = text.match(/(\d{1,2}):(\d{2})(?::\d{2})?/);
    if (!m) return '';
    return (
      String(Number(m[1])).padStart(2, '0') +
      ':' +
      m[2]
    );
  }

  function formatStayDateTime(dateRaw, timeRaw, fallbackTime) {
    var dateIso = toDateISO(dateRaw);
    if (!dateIso) return '';
    var dateLabel = prettyDateISO(dateIso);
    var timeLabel = formatTimeLabel12h(timeRaw || fallbackTime || '');
    if (dateLabel && timeLabel) return dateLabel + ', ' + timeLabel;
    return dateLabel || timeLabel || '';
  }

  function checkoutDueDismissKey(roomId, dateIso) {
    return 'hrd-checkout-due-dismiss:' + String(roomId || '') + ':' + String(dateIso || '');
  }

  function isCheckoutDueDismissed(roomId, dateIso) {
    try {
      return sessionStorage.getItem(checkoutDueDismissKey(roomId, dateIso)) === '1';
    } catch (err) {
      return false;
    }
  }

  function dismissCheckoutDueBanner(roomId, dateIso) {
    try {
      sessionStorage.setItem(checkoutDueDismissKey(roomId, dateIso), '1');
    } catch (err) {
      /* ignore quota / private mode */
    }
  }

  function paintCheckoutDueBanner(root, stillCheckedIn, checkOutDate, asOf) {
    var banner = $('#hrd-checkout-due', root);
    if (!banner) return;
    var roomId =
      (root && root.getAttribute('data-room-id')) ||
      (lastRoom && lastRoom.id) ||
      '';
    /* Exact expected check-out day only (not the night before). */
    var checkoutToday = !!(
      stillCheckedIn &&
      checkOutDate &&
      checkOutDate === asOf
    );
    var show =
      checkoutToday && !isCheckoutDueDismissed(roomId, asOf);
    var sub = $('#hrd-checkout-due-sub', root);
    if (sub) {
      sub.textContent =
        'Guest is expected to check out today · ' +
        prettyDateISO(checkOutDate || asOf);
    }
    setVisible(banner, show);
  }

  function stayWindow(stay) {
    if (!stay || typeof stay !== 'object') {
      return { checkIn: '', checkOut: '' };
    }
    return {
      checkIn: stay.checkInDate || stay.check_in_date || '',
      checkOut:
        stay.checkOutDate || stay.check_out_date || stay.expectedCheckOut || ''
    };
  }

  function viewRoomForDate(room, asOf) {
    var inventory = mapStatus(room && room.status);
    var window = stayWindow(room && room.stay);
    var effective = effectiveStatusForDate(
      inventory,
      window.checkIn,
      window.checkOut,
      asOf,
      todayISO()
    );
    var view = {};
    if (room) {
      Object.keys(room).forEach(function (key) {
        view[key] = room[key];
      });
    }
    view.status = effective;
    view.inventoryStatus = inventory;
    return view;
  }

  function nowTime() {
    var d = new Date();
    return (
      String(d.getHours()).padStart(2, '0') +
      ':' +
      String(d.getMinutes()).padStart(2, '0')
    );
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

  function showToast(message, isError) {
    var root = pageRoot();
    var toast = (root && $('#hrd-toast', root)) || document.getElementById('hrd-toast');
    if (!toast) return;
    toast.textContent = message || '';
    toast.hidden = !message;
    toast.classList.toggle('is-error', !!isError);
    if (!message) return;
    clearTimeout(showToast._timer);
    showToast._timer = setTimeout(function () {
      toast.hidden = true;
      toast.textContent = '';
    }, 3200);
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

  function closeMoreMenu(root) {
    root = root || pageRoot();
    if (!root) return;
    var menu = $('#hrd-more-menu', root) || document.getElementById('hrd-more-menu');
    var btn = $('#hrd-more-btn', root) || document.getElementById('hrd-more-btn');
    if (menu) {
      menu.hidden = true;
      menu.setAttribute('hidden', '');
      menu.classList.remove('is-fixed-open');
      menu.style.position = '';
      menu.style.top = '';
      menu.style.left = '';
      menu.style.right = '';
      menu.style.bottom = '';
      menu.style.zIndex = '';
    }
    if (btn) btn.setAttribute('aria-expanded', 'false');
  }

  function positionMoreMenu(btn, menu) {
    if (!btn || !menu) return;
    var rect = btn.getBoundingClientRect();
    var menuWidth = Math.max(168, menu.offsetWidth || 168);
    var left = Math.round(rect.right - menuWidth);
    var top = Math.round(rect.bottom + 6);
    if (left < 8) left = 8;
    if (left + menuWidth > window.innerWidth - 8) {
      left = Math.max(8, window.innerWidth - menuWidth - 8);
    }
    if (top + (menu.offsetHeight || 200) > window.innerHeight - 8) {
      top = Math.max(8, Math.round(rect.top - (menu.offsetHeight || 200) - 6));
    }
    menu.style.position = 'fixed';
    menu.style.top = top + 'px';
    menu.style.left = left + 'px';
    menu.style.right = 'auto';
    menu.style.bottom = 'auto';
    menu.style.zIndex = '12000';
    menu.classList.add('is-fixed-open');
  }

  function openMoreMenu(root) {
    root = root || pageRoot();
    if (!root) return;
    var menu = $('#hrd-more-menu', root);
    var btn = $('#hrd-more-btn', root);
    if (!menu || !btn) return;
    menu.hidden = false;
    menu.removeAttribute('hidden');
    btn.setAttribute('aria-expanded', 'true');
    positionMoreMenu(btn, menu);
  }

  function setVisible(el, show) {
    if (!el) return;
    if (show) {
      el.hidden = false;
      el.removeAttribute('hidden');
      el.classList.remove('is-hidden');
    } else {
      el.hidden = true;
      el.setAttribute('hidden', '');
      el.classList.add('is-hidden');
    }
  }

  function paintGuestPanels(root, room) {
    var stay = (room && room.stay) || null;
    var inventory = mapStatus(
      (room && room.inventoryStatus) || (room && room.status)
    );
    var occupied = inventory === 'occupied' && !!stay;
    var reserved = inventory === 'reserved' && !!stay;
    var dirty = inventory === 'dirty';
    var canStartCheckin = !occupied && !reserved && !dirty && inventory !== 'out_of_order';
    var showGuest = occupied || reserved;
    var number = (room && room.number) || root.getAttribute('data-room-number') || '';

    var emptyGuest = $('#hrd-guest-empty', root);
    var guestFilled = $('#hrd-guest-filled', root);
    setVisible(emptyGuest, !showGuest);
    setVisible(guestFilled, showGuest);

    var guestCard = $('#hrd-guest-card', root);
    if (guestCard) {
      if (showGuest) {
        guestCard.removeAttribute('data-action');
        guestCard.removeAttribute('role');
        guestCard.removeAttribute('tabindex');
        guestCard.removeAttribute('aria-label');
      } else if (canStartCheckin) {
        guestCard.setAttribute('data-action', 'checkin');
        guestCard.setAttribute('role', 'button');
        guestCard.setAttribute('tabindex', '0');
        guestCard.setAttribute('aria-label', 'Start check-in');
      } else {
        guestCard.removeAttribute('data-action');
        guestCard.removeAttribute('role');
        guestCard.removeAttribute('tabindex');
        guestCard.removeAttribute('aria-label');
      }
    }
    setVisible($('#hrd-edit-guest', root), showGuest);
    setVisible($('#hrd-start-checkout', root), occupied);
    setVisible($('#hrd-start-checkin-reserved', root), reserved);
    setVisible($('#hrd-start-checkin', root), canStartCheckin);
    var emptyTitle = $('#hrd-guest-empty-title', root);
    var emptySub = $('#hrd-guest-empty-sub', root);
    if (emptyTitle) {
      emptyTitle.textContent = dirty ? 'Room is dirty' : 'No guest checked-in';
    }
    if (emptySub) {
      emptySub.textContent = dirty
        ? 'Mark it Cleaned from the room menu before check-in.'
        : 'Click “Start Check-In” to add guest details';
    }

    if (showGuest && stay) {
      var nameEl = $('#hrd-guest-name', root);
      if (nameEl) nameEl.textContent = dash(guestCardDisplayName(stay));
      var metaEl = $('#hrd-guest-meta', root);
      if (metaEl) {
        metaEl.textContent = occupied
          ? 'In-house · Room ' + number
          : 'Reserved · Room ' + number;
      }
      var bookingEl = $('#hrd-guest-booking', root);
      if (bookingEl) bookingEl.textContent = dash(stay.bookingNumber);
      var reservationId = stayReservationDisplayId(stay);
      var reservationWrap = $('#hrd-guest-reservation-wrap', root);
      var reservationEl = $('#hrd-guest-reservation', root);
      if (reservationEl) reservationEl.textContent = dash(reservationId);
      setVisible(reservationWrap, !!reservationId);
      var mobileEl = $('#hrd-guest-mobile', root);
      if (mobileEl) {
        mobileEl.textContent = dash(
          (stay.mobileCountry ? stay.mobileCountry + ' ' : '') + (stay.mobile || '')
        );
      }
      var emailEl = $('#hrd-guest-email', root);
      if (emailEl) emailEl.textContent = dash(stay.email);
      var checkInEl = $('#hrd-guest-checkin', root);
      if (checkInEl) {
        checkInEl.textContent = dash(
          formatStayDateTime(
            stay.checkInDate || stay.check_in_date,
            stay.checkInTime ||
              stay.check_in_time ||
              timeFromCheckedInAt(stay.checkedInAt || stay.checked_in_at)
          )
        );
      }
      var checkOutEl = $('#hrd-guest-checkout', root);
      if (checkOutEl) {
        checkOutEl.textContent = dash(
          formatStayDateTime(
            stay.checkOutDate ||
              stay.check_out_date ||
              stay.expectedCheckOut,
            stay.checkOutTime || stay.check_out_time,
            '11:00'
          )
        );
      }
    }

    var extraGuests = Array.isArray(stay && stay.additionalGuests)
      ? stay.additionalGuests
      : [];
    var primaryDocPath = stayDocumentUrl(stay);
    var hasId = !!(
      showGuest &&
      stay &&
      (
        stay.idType ||
        stay.idDocumentName ||
        stay.idNumber ||
        primaryDocPath ||
        extraGuests.length
      )
    );
    setVisible($('#hrd-id-empty', root), !hasId);
    setVisible($('#hrd-id-filled', root), hasId);
    if (hasId) {
      var idType = $('#hrd-id-type', root);
      if (idType) idType.textContent = dash(stay.idType);
      var idNumber = $('#hrd-id-number', root);
      if (idNumber) {
        idNumber.textContent = dash(
          stay.guestName ||
            [stay.firstName, stay.lastName].filter(Boolean).join(' ').trim() ||
            stay.idNumber
        );
      }
      var docRow = $('#hrd-id-doc-row', root);
      var docName = $('#hrd-id-doc-name', root);
      var fileLabel = idDocumentDisplayLabel(stay, stay.idType, stay.idDocumentName);
      if (docRow) docRow.hidden = false;
      if (docName) {
        setIdDocumentNameLink(
          docName,
          fileLabel || (primaryDocPath ? 'Uploaded' : ''),
          primaryDocPath
        );
      }
    }
    var extraList = $('#hrd-id-extra-list', root);
    if (extraList) {
      extraList.innerHTML = '';
      var extrasToShow = showGuest ? extraGuests : [];
      extrasToShow.forEach(function (guest, idx) {
        if (!guest) return;
        var gName = String(guest.name || guest.guestName || '').trim();
        var gType = String(guest.idType || '').trim();
        var gPath = stayDocumentUrl(guest);
        var gFile = idDocumentDisplayLabel(guest, gType, guest.idDocumentName);
        if (!gName && !gType && !gPath && !gFile) return;
        var row = document.createElement('dl');
        row.className = 'hrd-dl hrd-dl--id-row hrd-id-extra-row';
        function cell(label, value) {
          var wrap = document.createElement('div');
          var dt = document.createElement('dt');
          dt.textContent = label;
          var dd = document.createElement('dd');
          dd.textContent = dash(value);
          wrap.appendChild(dt);
          wrap.appendChild(dd);
          return wrap;
        }
        row.appendChild(cell('Customer Name', gName || 'Guest ' + (idx + 2)));
        row.appendChild(cell('ID Type', gType));
        var docCell = document.createElement('div');
        var docDt = document.createElement('dt');
        docDt.textContent = 'ID Document';
        var docLine = document.createElement('div');
        docLine.className = 'hrd-id-extra-doc';
        var docDd = document.createElement('dd');
        setIdDocumentNameLink(
          docDd,
          gFile || (gPath ? 'Uploaded' : ''),
          gPath
        );
        docLine.appendChild(docDd);
        docCell.appendChild(docDt);
        docCell.appendChild(docLine);
        row.appendChild(docCell);
        extraList.appendChild(row);
      });
      extraList.hidden = !extraList.children.length;
    }

    var agencyName = root.querySelector('[data-agency-name]');
    var agencyGst = root.querySelector('[data-agency-gst]');
    var agencyAddress = root.querySelector('[data-agency-address]');
    var agencyBilling = root.querySelector('[data-agency-billing]');
    var hasAgency = !!(
      showGuest &&
      stay &&
      (
        String(stay.agencyName || '').trim() ||
        String(stay.agencyGst || '').trim() ||
        String(stay.agencyAddress || '').trim()
      )
    );
    setVisible($('#hrd-agency-card', root), hasAgency);
    if (hasAgency) {
      if (agencyName) agencyName.textContent = dash(stay.agencyName);
      if (agencyGst) agencyGst.textContent = dash(stay.agencyGst);
      if (agencyAddress) agencyAddress.textContent = dash(stay.agencyAddress);
      if (agencyBilling) {
        var flags = stayAgencyBillFlags(stay);
        agencyBilling.textContent =
          'Room: ' +
          (flags.room ? 'agency' : 'guest') +
          ' · F&B: ' +
          (flags.fb ? 'agency' : 'guest');
      }
    } else {
      if (agencyName) agencyName.textContent = '—';
      if (agencyGst) agencyGst.textContent = '—';
      if (agencyAddress) agencyAddress.textContent = '—';
      if (agencyBilling) agencyBilling.textContent = '—';
    }

    paintEstimatedCharges(root, room);
  }

  function overstayNightsFromStay(stay) {
    var fromStay = Number(stay && stay.overstayNights);
    if (isFinite(fromStay) && fromStay > 0) return Math.floor(fromStay);
    var outIso = toDateISO(
      stay &&
        (stay.checkOutDate || stay.check_out_date || stay.expectedCheckOut)
    );
    var today = todayISO();
    if (!outIso || !today || today <= outIso) return 0;
    var outParts = String(outIso).split('-');
    var todayParts = String(today).split('-');
    if (outParts.length !== 3 || todayParts.length !== 3) return 0;
    var outDate = new Date(
      Number(outParts[0]),
      Number(outParts[1]) - 1,
      Number(outParts[2])
    );
    var todayDate = new Date(
      Number(todayParts[0]),
      Number(todayParts[1]) - 1,
      Number(todayParts[2])
    );
    var diff = Math.round((todayDate - outDate) / 86400000);
    return diff > 0 ? diff : 0;
  }

  function sumNightlyRateSlice(nightlyRates, startIdx, count, fallbackRate) {
    if (!Array.isArray(nightlyRates) || !nightlyRates.length || !(count > 0)) {
      return null;
    }
    var sum = 0;
    var last = Math.max(0, Number(fallbackRate || 0));
    for (var i = 0; i < count; i++) {
      var idx = startIdx + i;
      var row = idx < nightlyRates.length ? nightlyRates[idx] : null;
      if (row && row.roomRate != null) {
        last = Math.max(0, Number(row.roomRate || 0));
      } else if (nightlyRates.length) {
        last = Math.max(
          0,
          Number(nightlyRates[Math.min(idx, nightlyRates.length - 1)].roomRate || last)
        );
      }
      sum += last;
    }
    return Math.round(sum * 100) / 100;
  }

  function isFbTransferFolio(item) {
    var kind = String((item && item.kind) || '').toLowerCase();
    return kind === 'restaurant_room_transfer' || kind === 'bar_room_transfer';
  }

  function fbChargeLinesFromStay(stay) {
    var folio = Array.isArray(stay && stay.folioCharges) ? stay.folioCharges : [];
    var lines = [];
    var labelFn = global.hotelFolioChargeDisplayLabel;
    folio.forEach(function (item) {
      if (!item || !isFbTransferFolio(item)) return;
      var amount = Number(item.amount || 0);
      if (!(amount > 0)) return;
      lines.push({
        label:
          typeof labelFn === 'function'
            ? labelFn(item)
            : item.label || 'Room Transfer',
        amount: Math.round(amount * 100) / 100,
        orderNo: String(item.orderNo || item.order_no || '').trim(),
        subtotal: Number(item.subtotal || 0),
        gst: Number(item.gst || item.gstAmount || 0),
        vat: Number(item.vat || item.vatAmount || 0),
        taxCgstPct: item.taxCgstPct != null ? Number(item.taxCgstPct) : null,
        taxUgstPct: item.taxUgstPct != null ? Number(item.taxUgstPct) : null,
        vatPct: item.vatPct != null ? Number(item.vatPct) : null
      });
    });
    return lines;
  }

  function chargeLinesFromStay(stay, room) {
    var bookedNights = Math.max(1, Number((stay && stay.nights) || 1));
    var overstayNights = overstayNightsFromStay(stay);
    var billableNights = Math.max(
      1,
      Number((stay && stay.billableNights) || bookedNights + overstayNights)
    );
    var mergeRates = Array.isArray(stay && stay.mergeRoomRates)
      ? stay.mergeRoomRates
      : [];
    function mergeChargesFor(roomId, number) {
      var rid = String(roomId || '').trim();
      var num = String(number || '').trim();
      for (var i = 0; i < mergeRates.length; i++) {
        var row = mergeRates[i];
        if (!row) continue;
        var match =
          (rid && String(row.roomId || '') === rid) ||
          (num && String(row.number || '') === num);
        if (!match) continue;
        var nightlySum = sumNightlyRateSlice(
          row.nightlyRates,
          0,
          billableNights,
          row.roomRate
        );
        if (nightlySum != null) return nightlySum;
        return Math.round(Math.max(0, Number(row.roomRate || 0)) * billableNights * 100) / 100;
      }
      return null;
    }
    var primaryMerge = null;
    for (var mi = 0; mi < mergeRates.length; mi++) {
      if (mergeRates[mi] && mergeRates[mi].isPrimary) {
        primaryMerge = mergeRates[mi];
        break;
      }
    }
    var roomRate = Math.max(0, Number((stay && stay.roomRate) || 0));
    if (primaryMerge && primaryMerge.roomRate != null) {
      roomRate = Math.max(0, Number(primaryMerge.roomRate || 0));
    }
    var primaryNightly =
      (primaryMerge && primaryMerge.nightlyRates) ||
      (stay && stay.nightlyRates) ||
      [];
    var bookedFromNightly = sumNightlyRateSlice(
      primaryNightly,
      0,
      bookedNights,
      roomRate
    );
    var overstayFromNightly = sumNightlyRateSlice(
      primaryNightly,
      bookedNights,
      Math.max(0, billableNights - bookedNights),
      roomRate
    );
    var bookedCharges =
      bookedFromNightly != null
        ? bookedFromNightly
        : Math.round(roomRate * bookedNights * 100) / 100;
    var overstayCharges =
      overstayFromNightly != null
        ? overstayFromNightly
        : Math.round(roomRate * Math.max(0, billableNights - bookedNights) * 100) /
          100;
    var lines = [];
    if (bookedCharges > 0) {
      var roomLabel = 'Room Charges';
      var isMergePrimary =
        !!(room && room.isMergePrimary) ||
        String((stay && stay.mergeRole) || '').toLowerCase() === 'primary';
      var roomNumber = String(
        (room && (room.number || room.roomNumber)) || ''
      ).trim();
      if (isMergePrimary && roomNumber) {
        roomLabel = 'Room ' + roomNumber + ' — stay charges';
      }
      lines.push({ label: roomLabel, amount: bookedCharges });
    }
    if (overstayCharges > 0) {
      lines.push({
        label:
          'Overstay (' +
          overstayNights +
          ' night' +
          (overstayNights === 1 ? '' : 's') +
          ')',
        amount: overstayCharges
      });
    }
    var extras = [
      { label: 'Extra Bed', amount: Number((stay && stay.extraBedAmount) || 0) },
      { label: 'Early Check-in', amount: Number((stay && stay.earlyCheckinAmount) || 0) },
      { label: 'Late Check-out', amount: Number((stay && stay.lateCheckoutAmount) || 0) }
    ];
    extras.forEach(function (row) {
      if (row.amount > 0) lines.push(row);
    });

    var folio = Array.isArray(stay && stay.folioCharges) ? stay.folioCharges : [];
    folio.forEach(function (item) {
      if (!item || isFbTransferFolio(item)) return;
      var amount = Number(item.amount || 0);
      if (!(amount > 0)) return;
      var src = String(item.source || '');
      if (src === 'merged_room_rate' || src === 'room_merge') {
        var mergedNow =
          !!(room && room.isMergePrimary) ||
          String((stay && stay.mergeRole) || '').toLowerCase() === 'primary';
        if (!mergedNow) return;
        var override = mergeChargesFor(
          item.sourceRoomId,
          item.sourceRoomNumber
        );
        if (override != null) {
          amount = override;
        }
      }
      if (!(amount > 0)) return;
      var labelFn = global.hotelFolioChargeDisplayLabel;
      lines.push({
        label:
          typeof labelFn === 'function'
            ? labelFn(item)
            : item.label || 'Other Charge',
        amount: Math.round(amount * 100) / 100
      });
    });
    return lines;
  }

  function folioLineInvoicedNo(item) {
    return String(
      (item && (item.invoicedInvoiceNumber || item.invoiced_invoice_number)) || ''
    ).trim();
  }

  function invoiceHistoryEntries(stay) {
    var raw = (stay && (stay.invoiceHistory || stay.invoice_history)) || [];
    if (!Array.isArray(raw)) raw = [];
    var out = [];
    var seen = {};
    raw.forEach(function (item) {
      if (!item) return;
      var inv = String(item.invoiceNumber || item.invoice_number || '').trim();
      if (!inv || seen[inv]) return;
      seen[inv] = true;
      out.push({
        kind: String(item.kind || 'hotel').toLowerCase(),
        invoiceNumber: inv,
        generatedAt: item.generatedAt || item.generated_at || '',
        estimatedTotal: Math.round(Number(item.estimatedTotal || 0) * 100) / 100
      });
    });
    var primaryHbe = String((stay && stay.invoiceNumber) || '').trim();
    if (primaryHbe && !seen[primaryHbe]) {
      out.unshift({
        kind: 'hotel',
        invoiceNumber: primaryHbe,
        generatedAt: (stay && stay.invoiceGeneratedAt) || '',
        estimatedTotal: Math.round(
          Number(
            (stay && stay.hotelInvoicedEstimatedTotal) ||
              (stay && stay.estimatedTotal) ||
              0
          ) * 100
        ) / 100
      });
    }
    var primaryFbe = String(
      (stay && (stay.fbTransferInvoiceNumber || stay.fb_transfer_invoice_number)) || ''
    ).trim();
    if (primaryFbe && !seen[primaryFbe]) {
      out.push({
        kind: 'fb',
        invoiceNumber: primaryFbe,
        generatedAt: (stay && stay.fbTransferInvoiceGeneratedAt) || '',
        estimatedTotal: Math.round(Number((stay && stay.fbTransferTotal) || 0) * 100) / 100
      });
    }
    return out;
  }

  function pendingFbChargeLinesFromStay(stay) {
    var all = fbChargeLinesFromStay(stay);
    var hasFbe = invoiceHistoryEntries(stay).some(function (entry) {
      return entry.kind === 'fb';
    });
    if (!hasFbe) return all;
    var folio = Array.isArray(stay && stay.folioCharges) ? stay.folioCharges : [];
    var lines = [];
    var labelFn = global.hotelFolioChargeDisplayLabel;
    folio.forEach(function (item) {
      if (!item || !isFbTransferFolio(item) || folioLineInvoicedNo(item)) return;
      var amount = Number(item.amount || 0);
      if (!(amount > 0)) return;
      lines.push({
        label:
          typeof labelFn === 'function'
            ? labelFn(item)
            : item.label || 'Room Transfer',
        amount: Math.round(amount * 100) / 100,
        orderNo: String(item.orderNo || item.order_no || '').trim(),
        subtotal: Number(item.subtotal || 0),
        gst: Number(item.gst || item.gstAmount || 0),
        vat: Number(item.vat || item.vatAmount || 0),
        taxCgstPct: item.taxCgstPct != null ? Number(item.taxCgstPct) : null,
        taxUgstPct: item.taxUgstPct != null ? Number(item.taxUgstPct) : null,
        vatPct: item.vatPct != null ? Number(item.vatPct) : null
      });
    });
    return lines;
  }

  /** Prefer POS invoice tax on each transfer line; never invent hotel CGST/UGST. */
  function summarizeFbChargeLines(rawLines) {
    var rows = Array.isArray(rawLines) ? rawLines : [];
    var fbInclusive = 0;
    var fbGst = 0;
    var fbVat = 0;
    var fbExclusive = 0;
    var hasPosTax = false;
    var vatPctSum = 0;
    var vatPctN = 0;
    var cgstPct = null;
    var ugstPct = null;
    rows.forEach(function (row) {
      var inclusive = Math.round(Number(row.amount || 0) * 100) / 100;
      var gst = Math.round(Number(row.gst || 0) * 100) / 100;
      var vat = Math.round(Number(row.vat || 0) * 100) / 100;
      var sub = Math.round(Number(row.subtotal || 0) * 100) / 100;
      fbInclusive = Math.round((fbInclusive + inclusive) * 100) / 100;
      if (gst > 0.009 || vat > 0.009 || sub > 0.009) {
        hasPosTax = true;
        fbGst = Math.round((fbGst + gst) * 100) / 100;
        fbVat = Math.round((fbVat + vat) * 100) / 100;
        if (!(sub > 0.009)) {
          sub = Math.round((inclusive - gst - vat) * 100) / 100;
          if (sub < 0) sub = 0;
        }
        fbExclusive = Math.round((fbExclusive + sub) * 100) / 100;
        if (vat > 0.009 && row.vatPct != null && isFinite(Number(row.vatPct))) {
          vatPctSum += Number(row.vatPct);
          vatPctN += 1;
        } else if (vat > 0.009 && sub > 0.009) {
          vatPctSum += (vat / sub) * 100;
          vatPctN += 1;
        }
        if (cgstPct == null && row.taxCgstPct != null && isFinite(Number(row.taxCgstPct))) {
          cgstPct = Number(row.taxCgstPct);
        }
        if (ugstPct == null && row.taxUgstPct != null && isFinite(Number(row.taxUgstPct))) {
          ugstPct = Number(row.taxUgstPct);
        }
      } else {
        fbExclusive = Math.round((fbExclusive + inclusive) * 100) / 100;
      }
    });
    var fbCgst = 0;
    var fbUgst = 0;
    if (hasPosTax) {
      if (fbGst > 0.009) {
        var cFrac =
          cgstPct != null && ugstPct != null && cgstPct + ugstPct > 0
            ? cgstPct / (cgstPct + ugstPct)
            : 0.5;
        fbCgst = Math.round(fbGst * cFrac * 100) / 100;
        fbUgst = Math.round((fbGst - fbCgst) * 100) / 100;
        if (fbUgst < 0) fbUgst = 0;
      }
    } else {
      /* Legacy lines without POS tax — keep prior inclusive total, no fake GST. */
      fbExclusive = fbInclusive;
    }
    var lines = rows.map(function (row) {
      var inclusive = Math.round(Number(row.amount || 0) * 100) / 100;
      var gst = Math.round(Number(row.gst || 0) * 100) / 100;
      var vat = Math.round(Number(row.vat || 0) * 100) / 100;
      var sub = Math.round(Number(row.subtotal || 0) * 100) / 100;
      var display = inclusive;
      if (gst > 0.009 || vat > 0.009 || sub > 0.009) {
        display = sub > 0.009 ? sub : Math.max(0, Math.round((inclusive - gst - vat) * 100) / 100);
      }
      return Object.assign({}, row, { amount: display });
    });
    return {
      lines: lines,
      fbTotal: fbInclusive,
      fbCgst: fbCgst,
      fbUgst: fbUgst,
      fbVat: fbVat,
      fbVatPct: vatPctN ? Math.round((vatPctSum / vatPctN) * 100) / 100 : null,
      fbCgstPct: cgstPct,
      fbUgstPct: ugstPct,
      fbBalance: fbInclusive
    };
  }

  function pendingHotelChargeLinesFromStay(stay, room) {
    var primary = String(
      (stay &&
        (stay.invoiceNumber ||
          stay.billedInvoiceNumber ||
          stay.billed_invoice_number)) ||
        ''
    ).trim();
    if (!primary) return chargeLinesFromStay(stay, room);
    var lines = [];
    var bookedNights = Math.max(1, Number((stay && stay.nights) || 1));
    var overstayNights = overstayNightsFromStay(stay);
    var billableNights = Math.max(
      1,
      Number((stay && stay.billableNights) || bookedNights + overstayNights)
    );
    /* Match backend: missing/zero night snapshot means "fully invoiced for nights". */
    var invoicedNights = Math.max(
      0,
      Math.floor(Number((stay && stay.hotelInvoicedBillableNights) || 0))
    );
    if (invoicedNights <= 0) {
      invoicedNights = billableNights;
    }
    var hasHotelSnap =
      Number((stay && stay.hotelInvoicedBillableNights) || 0) > 0 ||
      Number((stay && stay.hotelInvoicedEstimatedTotal) || 0) > 0 ||
      Number((stay && stay.hotelInvoicedExtraBedAmount) || 0) > 0 ||
      Number((stay && stay.hotelInvoicedEarlyCheckinAmount) || 0) > 0 ||
      Number((stay && stay.hotelInvoicedLateCheckoutAmount) || 0) > 0;
    if (billableNights > invoicedNights) {
      var roomRate = Math.max(0, Number((stay && stay.roomRate) || 0));
      var primaryNightly = (stay && stay.nightlyRates) || [];
      var fullRoom = sumNightlyRateSlice(primaryNightly, 0, billableNights, roomRate);
      if (fullRoom == null) fullRoom = Math.round(roomRate * billableNights * 100) / 100;
      var lockedRoom = sumNightlyRateSlice(primaryNightly, 0, invoicedNights, roomRate);
      if (lockedRoom == null) lockedRoom = Math.round(roomRate * invoicedNights * 100) / 100;
      var delta = Math.round((fullRoom - lockedRoom) * 100) / 100;
      if (delta > 0.009) {
        var extraNights = billableNights - invoicedNights;
        lines.push({
          label:
            'Overstay (' +
            extraNights +
            ' night' +
            (extraNights === 1 ? '' : 's') +
            ')',
          amount: delta
        });
      }
    }
    var snapFields = [
      ['extraBedAmount', 'hotelInvoicedExtraBedAmount', 'Extra Bed'],
      ['earlyCheckinAmount', 'hotelInvoicedEarlyCheckinAmount', 'Early Check-in'],
      ['lateCheckoutAmount', 'hotelInvoicedLateCheckoutAmount', 'Late Check-out']
    ];
    snapFields.forEach(function (row) {
      var current = Math.round(Number((stay && stay[row[0]]) || 0) * 100) / 100;
      /* Legacy invoices without snapshots: do not invent pending extras. */
      var snap = hasHotelSnap
        ? Math.round(Number((stay && stay[row[1]]) || 0) * 100) / 100
        : current;
      var delta = Math.round((current - snap) * 100) / 100;
      if (delta > 0.009) lines.push({ label: row[2], amount: delta });
    });
    var folio = Array.isArray(stay && stay.folioCharges) ? stay.folioCharges : [];
    var labelFn = global.hotelFolioChargeDisplayLabel;
    folio.forEach(function (item) {
      if (!item || isFbTransferFolio(item) || folioLineInvoicedNo(item)) return;
      var amount = Number(item.amount || 0);
      if (!(amount > 0)) return;
      /*
       * Legacy / merge absorb lines may lack invoicedInvoiceNumber even though
       * the HBE was minted covering them. When no hotel snapshots exist, treat
       * pre-invoice folio as already billed so checkout is not blocked.
       */
      if (!hasHotelSnap) return;
      lines.push({
        label:
          typeof labelFn === 'function'
            ? labelFn(item)
            : item.label || 'Other Charge',
        amount: Math.round(amount * 100) / 100
      });
    });
    return lines;
  }

  function stayHasPendingCharges(stay, room) {
    if (!stay) return false;
    var pendingHotel = pendingHotelChargeLinesFromStay(stay, room);
    var pendingFb = pendingFbChargeLinesFromStay(stay);
    var hotelAmt = pendingHotel.reduce(function (sum, row) {
      return sum + Number(row.amount || 0);
    }, 0);
    var fbAmt = pendingFb.reduce(function (sum, row) {
      return sum + Number(row.amount || 0);
    }, 0);
    return hotelAmt > 0.009 || fbAmt > 0.009;
  }

  function renderInvoiceHistoryLinks(container, entries, kind, stay) {
    if (!container) return;
    var filtered = (entries || []).filter(function (entry) {
      return entry.kind === kind;
    });
    if (!filtered.length) {
      container.innerHTML = '';
      return;
    }
    container.innerHTML = filtered
      .map(function (entry) {
        var unpaid = unpaidAmountForInvoice(stay, entry.invoiceNumber, kind);
        var amountLabel = moneyText(entry.estimatedTotal);
        if (unpaid != null && Math.abs(unpaid - Number(entry.estimatedTotal || 0)) > 0.009) {
          amountLabel =
            moneyText(entry.estimatedTotal) +
            ' · due ' +
            moneyText(unpaid);
        } else if (unpaid != null && unpaid <= 0.009) {
          amountLabel = moneyText(entry.estimatedTotal) + ' · paid';
        }
        return (
          '<p class="hrd-charges-invoice-no is-clickable" role="button" tabindex="0" data-invoice-kind="' +
          escapeHtml(kind) +
          '" data-invoice-number="' +
          escapeHtml(entry.invoiceNumber) +
          '" title="View invoice">Invoice ' +
          escapeHtml(entry.invoiceNumber) +
          ' · ' +
          amountLabel +
          '</p>'
        );
      })
      .join('');
  }

  function unpaidAmountForInvoice(stay, invoiceNumber, kind) {
    var inv = String(invoiceNumber || '').trim();
    if (!stay || !inv) return null;
    if (kind === 'fb') {
      var folio = Array.isArray(stay.folioCharges) ? stay.folioCharges : [];
      var total = 0;
      folio.forEach(function (line) {
        if (!line || !isFbTransferFolio(line)) return;
        if (folioLineInvoicedNo(line) !== inv) return;
        if (line.settled || line.paid) return;
        total += Number(line.amount || 0);
      });
      return Math.round(total * 100) / 100;
    }
    return null;
  }

  function chargeLinesHtml(lines) {
    return (lines || [])
      .map(function (row) {
        return (
          '<li><span class="hrd-charge-label">' +
          escapeHtml(row.label) +
          '</span><span class="hrd-charge-amount">' +
          moneyText(row.amount) +
          '</span></li>'
        );
      })
      .join('');
  }

  function stayMoneySummary(stay, room) {
    var lines = chargeLinesFromStay(stay, room);
    var subtotal = Math.round(
      lines.reduce(function (sum, row) {
        return sum + Number(row.amount || 0);
      }, 0) * 100
    ) / 100;
    var discountType = (stay && (stay.discountType || stay.discount_type)) || 'pct';
    var discountValue = Number(
      stay && (stay.discountValue != null ? stay.discountValue : stay.discount_value)
    );
    if (!isFinite(discountValue)) discountValue = 0;
    var discount = Math.round(Number((stay && stay.discountAmount) || 0) * 100) / 100;
    if (discount > subtotal) discount = subtotal;
    /* Room rate and stay lines are tax-inclusive — extract CGST/UGST from the total. */
    var inclusive = Math.round(Math.max(0, subtotal - discount) * 100) / 100;
    var factor = 1 + CGST_RATE + UGST_RATE;
    var taxable =
      factor > 0 ? Math.round((inclusive / factor) * 100) / 100 : inclusive;
    var cgst = Math.round(taxable * CGST_RATE * 100) / 100;
    var ugst = Math.round((inclusive - taxable - cgst) * 100) / 100;
    if (ugst < 0) ugst = 0;
    var computedEstimated = inclusive;
    /* Show exclusive line amounts so CGST/UGST add to the estimated total. */
    if (factor > 0) {
      lines = lines.map(function (row) {
        var amt = Math.round(Number(row.amount || 0) * 100) / 100;
        return Object.assign({}, row, {
          amount: Math.round((amt / factor) * 100) / 100
        });
      });
      subtotal = Math.round(
        lines.reduce(function (sum, row) {
          return sum + Number(row.amount || 0);
        }, 0) * 100
      ) / 100;
      if (discount > 0) {
        discount = Math.round((discount / factor) * 100) / 100;
        if (discount > subtotal) discount = subtotal;
      }
    }
    /* Prefer live recompute so overstay nights update even if stay payload is stale. */
    var estimated = computedEstimated;
    if (
      stay &&
      stay.estimatedTotal != null &&
      !stay.independentBilling &&
      !(Number(stay.overstayNights) > 0 || overstayNightsFromStay(stay) > 0)
    ) {
      estimated = Math.round(Number(stay.estimatedTotal || 0) * 100) / 100;
    }
    var advance = Math.max(0, Number((stay && stay.advancePaid) || 0));
    var balance = Math.max(0, Math.round((estimated - advance) * 100) / 100);
    if (
      stay &&
      stay.balanceAmount != null &&
      !(Number(stay.overstayNights) > 0 || overstayNightsFromStay(stay) > 0)
    ) {
      balance = Math.round(Number(stay.balanceAmount || 0) * 100) / 100;
    }
    var fbLinesRaw = fbChargeLinesFromStay(stay);
    var fbMoney = summarizeFbChargeLines(fbLinesRaw);
    var fbLines = fbMoney.lines;
    var fbTotal = fbMoney.fbTotal;
    if (stay && stay.fbTransferTotal != null && !(fbTotal > 0)) {
      fbTotal = Math.round(Number(stay.fbTransferTotal || 0) * 100) / 100;
    }
    var fbCgst = fbMoney.fbCgst;
    var fbUgst = fbMoney.fbUgst;
    var fbVat = fbMoney.fbVat;
    var fbBalance =
      stay && stay.fbTransferBalance != null
        ? Math.round(Number(stay.fbTransferBalance || 0) * 100) / 100
        : fbTotal;
    if (!isFinite(fbBalance)) fbBalance = fbTotal;
    /* Always hotel due + F&B due so the combined row stays in sync. */
    var combinedBalance = Math.round((Number(balance) + Number(fbBalance)) * 100) / 100;
    if (!isFinite(combinedBalance)) combinedBalance = 0;
    return {
      lines: lines,
      subtotal: subtotal,
      discount: discount,
      discountType: discountType,
      discountValue: discountValue,
      taxable: taxable,
      cgst: cgst,
      ugst: ugst,
      estimated: estimated,
      advance: advance,
      balance: balance,
      fbLines: fbLines,
      fbTotal: fbTotal,
      fbCgst: fbCgst,
      fbUgst: fbUgst,
      fbVat: fbVat,
      fbVatPct: fbMoney.fbVatPct,
      fbCgstPct: fbMoney.fbCgstPct,
      fbUgstPct: fbMoney.fbUgstPct,
      fbBalance: fbBalance,
      combinedBalance: combinedBalance
    };
  }

  function formatTaxInclHint(pct) {
    if (pct == null || !isFinite(Number(pct))) return '';
    var n = Math.round(Number(pct) * 100) / 100;
    if (!(n > 0)) return '';
    return '(' + n + '% incl.)';
  }

  function paintFbTaxRows(opts) {
    opts = opts || {};
    var cgst = Number(opts.fbCgst || 0);
    var ugst = Number(opts.fbUgst || 0);
    var vat = Number(opts.fbVat || 0);
    var showGst = cgst > 0.009 || ugst > 0.009;
    var showVat = vat > 0.009;
    if (opts.cgstRow) opts.cgstRow.hidden = !showGst;
    if (opts.ugstRow) opts.ugstRow.hidden = !showGst;
    if (opts.vatRow) opts.vatRow.hidden = !showVat;
    if (opts.cgstEl) opts.cgstEl.textContent = showGst ? moneyText(cgst) : '—';
    if (opts.ugstEl) opts.ugstEl.textContent = showGst ? moneyText(ugst) : '—';
    if (opts.vatEl) opts.vatEl.textContent = showVat ? moneyText(vat) : '—';
    if (opts.cgstHint) {
      opts.cgstHint.textContent = showGst
        ? formatTaxInclHint(opts.fbCgstPct != null ? opts.fbCgstPct : CGST_RATE * 100) ||
          '(incl.)'
        : '';
    }
    if (opts.ugstHint) {
      opts.ugstHint.textContent = showGst
        ? formatTaxInclHint(opts.fbUgstPct != null ? opts.fbUgstPct : UGST_RATE * 100) ||
          '(incl.)'
        : '';
    }
    if (opts.vatHint) {
      opts.vatHint.textContent = showVat ? formatTaxInclHint(opts.fbVatPct) || '(incl.)' : '';
    }
  }

  function formatDiscountHint(type, value) {
    var n = Number(value);
    if (!isFinite(n) || n <= 0) return '';
    if (String(type || '').toLowerCase() === 'inr') return '(₹' + n + ')';
    return '(' + n + '%)';
  }

  function setClickableInvoiceNo(el, invoiceNumber, options) {
    options = options || {};
    if (!el) return;
    var no = String(invoiceNumber || '').trim();
    if (!no) {
      el.hidden = true;
      el.textContent = '';
      el.removeAttribute('role');
      el.removeAttribute('tabindex');
      el.removeAttribute('title');
      el.removeAttribute('data-invoice-kind');
      el.classList.remove('is-clickable');
      return;
    }
    var prefix = options.prefix != null ? String(options.prefix) : 'Invoice ';
    el.hidden = false;
    el.textContent = options.text != null ? String(options.text) : prefix + no;
    el.setAttribute('role', 'button');
    el.setAttribute('tabindex', '0');
    el.setAttribute('title', options.title || 'View invoice');
    if (options.kind) {
      el.setAttribute('data-invoice-kind', options.kind);
    } else {
      el.removeAttribute('data-invoice-kind');
    }
    el.classList.add('is-clickable');
  }

  function invoiceKindFromEl(el) {
    if (!el) return 'hotel';
    var kind = String(el.getAttribute('data-invoice-kind') || '').trim().toLowerCase();
    if (kind === 'hotel' || kind === 'fb') return kind;
    var id = el.id || '';
    if (id === 'hrd-charges-fb-invoice-no' || id === 'hrd-invoice-fb-no') return 'fb';
    return 'hotel';
  }

  function invoiceNumberFromEl(el) {
    if (!el) return '';
    var fromAttr = String(el.getAttribute('data-invoice-number') || '').trim();
    if (fromAttr) return fromAttr;
    return String(el.textContent || '')
      .trim()
      .replace(/^Invoice\s+/i, '')
      .replace(/\s·.*$/, '')
      .trim();
  }

  function invoiceLedgerApiUrl(invoiceNumber) {
    return (
      '/hotel/invoice-ledger/api/' +
      String(invoiceNumber || '')
        .split('/')
        .map(function (part) {
          return encodeURIComponent(part);
        })
        .join('/')
    );
  }

  function openRoomInvoicePreview(kind, invoiceNumber) {
    if (!lastRoom || !lastRoom.stay) {
      showToast('Invoice preview unavailable.', true);
      return false;
    }
    var inv = String(invoiceNumber || '').trim();
    if (inv) {
      fetch(invoiceLedgerApiUrl(inv), {
        credentials: 'same-origin',
        headers: { Accept: 'application/json' }
      })
        .then(function (resp) {
          return resp.json().then(function (data) {
            return { ok: resp.ok, data: data || {} };
          });
        })
        .then(function (result) {
          if (!result.ok || !result.data.ok || !result.data.room) {
            showToast(
              (result.data && result.data.error) || 'Could not load invoice.',
              true
            );
            return;
          }
          var invoice = result.data.invoice || {};
          var source = String(invoice.source || '').toLowerCase();
          var useFb =
            kind === 'fb' ||
            source === 'fb_combined_transfer' ||
            /^FBE\//i.test(inv);
          var openFn = useFb
            ? global.openFbCombinedTransferInvoice
            : global.openHotelRoomInvoice;
          if (typeof openFn !== 'function') {
            showToast('Invoice preview is unavailable.', true);
            return;
          }
          var opened = openFn(result.data.room, {
            autoPrint: false,
            invoiceNumber: inv,
            invoiceStatus: invoice.status || '',
            cancelReason: invoice.cancel_reason || ''
          });
          if (!opened) {
            showToast('Could not open invoice preview.', true);
          }
        })
        .catch(function () {
          showToast('Could not load invoice.', true);
        });
      return true;
    }
    var ok = false;
    var opts = { autoPrint: false };
    if (kind === 'fb') {
      if (typeof global.openFbCombinedTransferInvoice === 'function') {
        ok = global.openFbCombinedTransferInvoice(lastRoom, opts);
      }
    } else if (typeof global.openHotelRoomInvoice === 'function') {
      ok = global.openHotelRoomInvoice(lastRoom, opts);
    }
    if (!ok) showToast('Could not open invoice preview.', true);
    return ok;
  }

  function paintEstimatedCharges(root, room) {
    var emptyEl = $('#hrd-charges-empty', root);
    var bodyEl = $('#hrd-charges-body', root);
    var listEl = $('#hrd-charges-list', root);
    if (!emptyEl || !bodyEl || !listEl) return;

    var stay = (room && room.stay) || null;
    var occupied = mapStatus(room && room.status) === 'occupied' && !!stay;
    var invoiceNoEl = $('#hrd-charges-invoice-no', root);
    var fbInvoiceNoElEarly = $('#hrd-charges-fb-invoice-no', root);
    var actionsEl = $('#hrd-charges-actions', root);
    var genBtn = $('#hrd-generate-invoice', root);
    var genHotelBtn = $('#hrd-generate-hotel-invoice', root);
    var genFbBtn = $('#hrd-generate-fb-invoice', root);
    var payBtn = $('#hrd-record-payment', root);

    if (!occupied) {
      listEl.innerHTML = '';
      setVisible(emptyEl, true);
      setVisible(bodyEl, false);
      setClickableInvoiceNo(invoiceNoEl, '');
      setClickableInvoiceNo(fbInvoiceNoElEarly, '');
      if (actionsEl) actionsEl.hidden = true;
      if (genBtn) genBtn.hidden = true;
      if (genHotelBtn) {
        genHotelBtn.hidden = true;
        genHotelBtn.disabled = true;
      }
      if (genFbBtn) {
        genFbBtn.hidden = true;
        genFbBtn.disabled = true;
      }
      if (payBtn) payBtn.hidden = true;
      return;
    }

    var summary = stayMoneySummary(stay, room);
    var lines = summary.lines;
    var estimated = summary.estimated;
    var advance = summary.advance;
    var balance = summary.balance;
    var invoiceGenerated = !!(
      stay.invoiceGenerated ||
      stay.invoiceNumber ||
      stay.billedInvoiceGenerated ||
      stay.billedInvoiceNumber
    );
    var invoiceNumber = String(
      stay.invoiceNumber || stay.billedInvoiceNumber || ''
    ).trim();

    if (invoiceNoEl) {
      setClickableInvoiceNo(invoiceNoEl, '');
    }

    var history = invoiceHistoryEntries(stay);
    var hasPending = stayHasPendingCharges(stay, room);
    var pendingHotelLines = invoiceGenerated
      ? pendingHotelChargeLinesFromStay(stay, room)
      : lines;
    /* Always use pending F&B lines (uninvoiced transfers). Using summary.fbLines
       after an FBE already exists incorrectly keeps "Generate Additional F&B"
       visible when nothing is left to invoice. */
    var pendingFbLines = pendingFbChargeLinesFromStay(stay);
    var invoicedSection = $('#hrd-charges-invoiced-section', root);
    var pendingSection = $('#hrd-charges-pending-section', root);
    var pendingListEl = $('#hrd-charges-pending-list', root);
    var invoicedHistoryEl = $('#hrd-charges-invoiced-history', root);
    var fbInvoicedSection = $('#hrd-charges-fb-invoiced-section', root);
    var fbPendingSection = $('#hrd-charges-fb-pending-section', root);
    var fbPendingListEl = $('#hrd-charges-fb-pending-list', root);
    var fbInvoicedHistoryEl = $('#hrd-charges-fb-invoiced-history', root);
    var hotelHistory = history.filter(function (entry) {
      return entry.kind === 'hotel';
    });
    var fbHistory = history.filter(function (entry) {
      return entry.kind === 'fb';
    });

    if (!lines.length && estimated <= 0 && !pendingHotelLines.length && !pendingFbLines.length) {
      listEl.innerHTML = '';
      var isMemberEarly = !!(
        room.isMergeMember ||
        (stay && (stay.mergeRole === 'member' || stay.billingRoomId))
      );
      if (isMemberEarly) {
        emptyEl.textContent =
          'Billing is on Room ' +
          (room.billingRoomNumber || stay.billingRoomId || '—') +
          '. Open that room to invoice.';
      } else {
        emptyEl.textContent = emptyEl.getAttribute('data-default-empty') || emptyEl.textContent;
      }
      setVisible(emptyEl, true);
      setVisible(bodyEl, false);
      if (actionsEl) actionsEl.hidden = true;
      if (genBtn) genBtn.hidden = true;
      if (genHotelBtn) {
        genHotelBtn.hidden = true;
        genHotelBtn.disabled = true;
      }
      if (genFbBtn) {
        genFbBtn.hidden = true;
        genFbBtn.disabled = true;
      }
      if (payBtn) payBtn.hidden = true;
      return;
    }

    if (invoiceGenerated && hotelHistory.length) {
      if (invoicedSection) invoicedSection.hidden = false;
      renderInvoiceHistoryLinks(invoicedHistoryEl, history, 'hotel', stay);
      listEl.hidden = true;
      if (pendingSection) pendingSection.hidden = !(pendingHotelLines.length > 0);
      if (pendingListEl) pendingListEl.innerHTML = chargeLinesHtml(pendingHotelLines);
    } else {
      if (invoicedSection) invoicedSection.hidden = true;
      if (pendingSection) pendingSection.hidden = true;
      listEl.hidden = false;
      listEl.innerHTML = chargeLinesHtml(lines);
    }

    var discRow = root.querySelector('[data-charges-discount-row]');
    var discHint = root.querySelector('[data-charges-discount-hint]');
    var discEl = root.querySelector('[data-charges-discount]');
    var subtotalEl = root.querySelector('[data-charges-subtotal]');
    var cgstEl = root.querySelector('[data-charges-cgst]');
    var ugstEl = root.querySelector('[data-charges-ugst]');
    var totalEl = root.querySelector('[data-charges-total]');
    var advanceEl = root.querySelector('[data-charges-advance]');
    var balanceEl = root.querySelector('[data-charges-balance]');
    var showDisc = Number(summary.discount) > 0;
    if (discRow) discRow.hidden = !showDisc;
    if (discHint) {
      discHint.textContent = showDisc
        ? formatDiscountHint(summary.discountType, summary.discountValue)
        : '';
    }
    if (discEl) discEl.textContent = showDisc ? '−' + moneyText(summary.discount) : '—';
    if (subtotalEl) subtotalEl.textContent = moneyText(summary.subtotal);
    if (cgstEl) cgstEl.textContent = moneyText(summary.cgst);
    if (ugstEl) ugstEl.textContent = moneyText(summary.ugst);
    if (totalEl) totalEl.textContent = moneyText(estimated);
    if (advanceEl) advanceEl.textContent = moneyText(advance);
    if (balanceEl) balanceEl.textContent = moneyText(balance);

    var fbSection = $('#hrd-charges-fb-section', root);
    var fbListEl = $('#hrd-charges-fb-list', root);
    var fbInvoiceNoEl = $('#hrd-charges-fb-invoice-no', root);
    var fbCgstEl = root.querySelector('[data-charges-fb-cgst]');
    var fbUgstEl = root.querySelector('[data-charges-fb-ugst]');
    var fbVatEl = root.querySelector('[data-charges-fb-vat]');
    var fbTotalEl = root.querySelector('[data-charges-fb-total]');
    var fbBalanceEl = root.querySelector('[data-charges-fb-balance]');
    var fbCgstRow =
      root.querySelector('[data-charges-fb-cgst-row]') ||
      (fbCgstEl && fbCgstEl.closest('div'));
    var fbUgstRow =
      root.querySelector('[data-charges-fb-ugst-row]') ||
      (fbUgstEl && fbUgstEl.closest('div'));
    var fbVatRow =
      root.querySelector('[data-charges-fb-vat-row]') ||
      (fbVatEl && fbVatEl.closest('div'));
    var fbTotalRow = fbTotalEl && fbTotalEl.closest('div');
    var fbBalanceRow = fbBalanceEl && fbBalanceEl.closest('div');
    var fbBalanceDt = fbBalanceRow && fbBalanceRow.querySelector('dt');
    var fbCgstHint = root.querySelector('[data-charges-fb-cgst-hint]');
    var fbUgstHint = root.querySelector('[data-charges-fb-ugst-hint]');
    var fbVatHint = root.querySelector('[data-charges-fb-vat-hint]');
    var combinedEl = $('#hrd-charges-combined', root);
    var combinedBalanceEl = root.querySelector('[data-charges-combined-balance]');
    var fbLines = summary.fbLines || [];
    var fbTotal = Number(summary.fbTotal);
    if (!isFinite(fbTotal)) fbTotal = 0;
    var fbBalance = Number(summary.fbBalance);
    if (!isFinite(fbBalance)) fbBalance = 0;
    var combinedBalance = Number(summary.combinedBalance);
    if (!isFinite(combinedBalance)) {
      combinedBalance = Math.round((Number(balance) + fbBalance) * 100) / 100;
    }
    var fbInvoiceNumber = String(
      (stay && (stay.fbTransferInvoiceNumber || stay.fb_transfer_invoice_number)) || ''
    ).trim();
    var hasFbHistory = fbHistory.length > 0;
    if (fbSection && fbListEl) {
      if (fbLines.length || fbTotal > 0 || hasFbHistory || pendingFbLines.length) {
        fbSection.hidden = false;
        if (hasFbHistory) {
          if (fbInvoicedSection) fbInvoicedSection.hidden = false;
          renderInvoiceHistoryLinks(fbInvoicedHistoryEl, history, 'fb', stay);
          fbListEl.hidden = true;
          if (fbInvoiceNoEl) setClickableInvoiceNo(fbInvoiceNoEl, '');
          if (fbPendingSection) fbPendingSection.hidden = !(pendingFbLines.length > 0);
          if (fbPendingListEl) fbPendingListEl.innerHTML = chargeLinesHtml(pendingFbLines);
          /* Invoiced links + pending lines already break down F&B. Hide the old
             Total/CGST footer; unpaid F&B is shown in Combined Checkout Due. */
          if (fbCgstRow) fbCgstRow.hidden = true;
          if (fbUgstRow) fbUgstRow.hidden = true;
          if (fbVatRow) fbVatRow.hidden = true;
          if (fbTotalRow) fbTotalRow.hidden = true;
          if (fbBalanceRow) {
            var showFbDue = fbBalance > 0.009;
            fbBalanceRow.hidden = !showFbDue;
            if (fbBalanceDt) fbBalanceDt.textContent = 'Unpaid F&B Due';
            if (fbBalanceEl) {
              fbBalanceEl.textContent = showFbDue ? moneyText(fbBalance) : '—';
            }
          }
        } else {
          if (fbInvoicedSection) fbInvoicedSection.hidden = true;
          if (fbPendingSection) fbPendingSection.hidden = true;
          fbListEl.hidden = false;
          fbListEl.innerHTML = chargeLinesHtml(fbLines);
          if (fbInvoiceNoEl) {
            setClickableInvoiceNo(fbInvoiceNoEl, fbInvoiceNumber, { kind: 'fb' });
          }
          if (fbTotalRow) fbTotalRow.hidden = false;
          if (fbBalanceRow) fbBalanceRow.hidden = false;
          if (fbBalanceDt) fbBalanceDt.textContent = 'F&B Balance';
          paintFbTaxRows({
            cgstRow: fbCgstRow,
            ugstRow: fbUgstRow,
            vatRow: fbVatRow,
            cgstEl: fbCgstEl,
            ugstEl: fbUgstEl,
            vatEl: fbVatEl,
            cgstHint: fbCgstHint,
            ugstHint: fbUgstHint,
            vatHint: fbVatHint,
            fbCgst: summary.fbCgst,
            fbUgst: summary.fbUgst,
            fbVat: summary.fbVat,
            fbCgstPct: summary.fbCgstPct,
            fbUgstPct: summary.fbUgstPct,
            fbVatPct: summary.fbVatPct
          });
          if (fbTotalEl) fbTotalEl.textContent = moneyText(fbTotal);
          if (fbBalanceEl) fbBalanceEl.textContent = moneyText(fbBalance);
        }
      } else {
        fbSection.hidden = true;
        fbListEl.innerHTML = '';
        if (fbInvoicedSection) fbInvoicedSection.hidden = true;
        if (fbPendingSection) fbPendingSection.hidden = true;
        if (fbInvoiceNoEl) setClickableInvoiceNo(fbInvoiceNoEl, '');
      }
    }
    if (combinedEl) {
      var hotelDue = Math.round(Number(balance) * 100) / 100;
      if (!isFinite(hotelDue)) hotelDue = 0;
      var fbDue = Math.round(Number(fbBalance) * 100) / 100;
      if (!isFinite(fbDue)) fbDue = 0;
      combinedBalance = Math.round((hotelDue + fbDue) * 100) / 100;
      var showCombined =
        hasFbHistory ||
        fbLines.length > 0 ||
        fbTotal > 0 ||
        fbDue > 0;
      combinedEl.hidden = !showCombined;
      var combinedHotelEl = root.querySelector('[data-charges-combined-hotel]');
      var combinedFbEl = root.querySelector('[data-charges-combined-fb]');
      if (combinedHotelEl) {
        combinedHotelEl.textContent = showCombined ? moneyText(hotelDue) : '—';
      }
      if (combinedFbEl) {
        combinedFbEl.textContent = showCombined ? moneyText(fbDue) : '—';
      }
      if (combinedBalanceEl) {
        combinedBalanceEl.textContent = showCombined ? moneyText(combinedBalance) : '—';
      }
    }

    setVisible(emptyEl, false);
    setVisible(bodyEl, true);

    if (actionsEl) actionsEl.hidden = false;
    var isMember = !!(
      room.isMergeMember ||
      (stay && (stay.mergeRole === 'member' || stay.billingRoomId))
    );
    var billedViaPrimary = !!(
      (stay && (stay.billedInvoiceGenerated || stay.billedInvoiceNumber)) ||
      (stay &&
        (stay.billedFbTransferInvoiceGenerated || stay.billedFbTransferInvoiceNumber))
    );
    var mergeNums = Array.isArray(stay && stay.mergeRoomNumbers)
      ? stay.mergeRoomNumbers
      : [];
    var sharedMergeAlreadyInvoiced = !!(
      mergeNums.length > 1 &&
      (stay.invoiceGenerated || stay.invoiceNumber || billedViaPrimary)
    );
    /* Merged primary still needs Generate Additional when charges are pending. */
    var mergeBlocksGenerate =
      isMember ||
      billedViaPrimary ||
      (sharedMergeAlreadyInvoiced && !hasPending);
    if (mergeBlocksGenerate) {
      if (genBtn) genBtn.hidden = true;
      if (genHotelBtn) {
        genHotelBtn.hidden = true;
        genHotelBtn.disabled = true;
      }
      if (genFbBtn) {
        genFbBtn.hidden = true;
        genFbBtn.disabled = true;
      }
      if (payBtn) {
        /* Members / billed-via-primary never pay here; successor holding the
           shared merge invoice can still settle an open balance. */
        payBtn.hidden = !(
          sharedMergeAlreadyInvoiced &&
          !isMember &&
          !billedViaPrimary &&
          summary.combinedBalance > 0
        );
      }
      var billNo = room.billingRoomNumber || stay.billingRoomId || '';
      if (isMember && emptyEl && (!lines.length || estimated <= 0)) {
        emptyEl.textContent =
          'Billing is on Room ' + (billNo || '—') + '. Open that room to invoice.';
        setVisible(emptyEl, true);
        setVisible(bodyEl, false);
      }
    } else {
      var hasHotelToInvoice =
        invoiceGenerated
          ? pendingHotelLines.length > 0
          : lines.length > 0 || estimated > 0;
      var hasFbToInvoice = pendingFbLines.length > 0;
      var hotelAlreadyInvoiced = !!(invoiceGenerated || hotelHistory.length);
      var fbAlreadyInvoiced = fbHistory.length > 0;
      if (genBtn) genBtn.hidden = true;
      setGenerateInvoiceButton(
        genHotelBtn,
        hasHotelToInvoice,
        hotelAlreadyInvoiced
          ? 'Generate Additional Room Invoice'
          : 'Generate Room Invoice'
      );
      setGenerateInvoiceButton(
        genFbBtn,
        hasFbToInvoice,
        fbAlreadyInvoiced
          ? 'Generate Additional F&B Invoice'
          : 'Generate F&B Invoice'
      );
      if (payBtn) {
        payBtn.hidden = !(
          (invoiceGenerated || fbAlreadyInvoiced) &&
          summary.combinedBalance > 0
        );
      }
    }
  }

  function setGenerateInvoiceButton(btn, visible, labelText) {
    if (!btn) return;
    btn.hidden = !visible;
    btn.disabled = !visible;
    if (!visible) {
      btn.setAttribute('aria-hidden', 'true');
      return;
    }
    btn.removeAttribute('aria-hidden');
    var svg = btn.querySelector('svg');
    btn.innerHTML = (svg ? svg.outerHTML : '') + ' ' + labelText;
  }

  function escapeHtml(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function paintStatusMenu(root, status) {
    /* Match Rooms board ⋮ menu: no "Set" prefix; hide current/illogical options. */
    var vacantBtn = $('#hrd-menu-status-vacant', root);
    var occupiedBtn = $('#hrd-menu-status-occupied', root);
    var reservedBtn = $('#hrd-menu-status-reserved', root);
    var dirtyBtn = $('#hrd-menu-status-dirty', root);
    var oooBtn = $('#hrd-menu-status-out_of_order', root);
    var s = mapStatus(status);

    if (reservedBtn) {
      reservedBtn.hidden = false;
      reservedBtn.removeAttribute('hidden');
      if (s === 'reserved') {
        reservedBtn.textContent = 'Un Reserved';
        reservedBtn.setAttribute('data-set-status', 'vacant');
        reservedBtn.removeAttribute('data-action');
        reservedBtn.classList.remove('is-current');
      } else if (s === 'occupied') {
        /* Occupied rooms only accept non-overlapping future reservations. */
        reservedBtn.textContent = 'Reserve';
        reservedBtn.removeAttribute('data-set-status');
        reservedBtn.setAttribute('data-action', 'reserve');
        reservedBtn.classList.remove('is-current');
      } else {
        reservedBtn.textContent = 'Reserve';
        reservedBtn.setAttribute('data-set-status', 'reserved');
        reservedBtn.removeAttribute('data-action');
        reservedBtn.classList.remove('is-current');
      }
    }
    if (oooBtn) {
      /* Only vacant rooms can be marked Out of order (after checkout / free inventory). */
      var showOoo = s === 'vacant' || s === 'out_of_order';
      oooBtn.hidden = !showOoo;
      if (oooBtn.hidden) oooBtn.setAttribute('hidden', '');
      else oooBtn.removeAttribute('hidden');
      oooBtn.textContent = 'Out of order';
      oooBtn.setAttribute('data-set-status', 'out_of_order');
      oooBtn.classList.toggle('is-current', s === 'out_of_order');
    }

    if (vacantBtn) {
      vacantBtn.textContent = 'Vacant';
      vacantBtn.setAttribute('data-set-status', 'vacant');
      vacantBtn.classList.toggle('is-current', false);
      vacantBtn.hidden = s === 'occupied' || s === 'dirty' || s === 'vacant';
      if (vacantBtn.hidden) vacantBtn.setAttribute('hidden', '');
      else vacantBtn.removeAttribute('hidden');
    }
    if (occupiedBtn) {
      occupiedBtn.textContent = 'Occupied';
      occupiedBtn.setAttribute('data-set-status', 'occupied');
      occupiedBtn.classList.toggle('is-current', false);
      /* Occupied is set via check-in, not the status menu. */
      occupiedBtn.hidden = true;
      occupiedBtn.setAttribute('hidden', '');
    }
    if (dirtyBtn) {
      if (s === 'dirty') {
        dirtyBtn.hidden = false;
        dirtyBtn.removeAttribute('hidden');
        dirtyBtn.textContent = 'Cleaned';
        dirtyBtn.setAttribute('data-set-status', 'vacant');
        dirtyBtn.classList.remove('is-current');
      } else {
        dirtyBtn.hidden = false;
        dirtyBtn.removeAttribute('hidden');
        dirtyBtn.textContent = 'Dirty';
        dirtyBtn.setAttribute('data-set-status', 'dirty');
        dirtyBtn.classList.toggle('is-current', s === 'dirty');
      }
    }
  }

  function paintMergeChrome(root, room) {
    var banner = $('#hrd-merge-banner', root);
    var mergeBtn = $('#hrd-menu-merge', root);
    var extendBtn = $('#hrd-menu-extend', root);
    var unmergeBtn = $('#hrd-menu-unmerge', root);
    var unmergeGroupBtn = $('#hrd-menu-unmerge-group', root);
    var checkoutGroupBtn = $('#hrd-menu-checkout-group', root);
    var primaryBtn = $('#hrd-menu-set-primary', root);
    var isMember = !!(room && room.isMergeMember);
    var isPrimary = !!(room && room.isMergePrimary);
    var inGroup = !!(
      (room && room.mergeGroupId) ||
      isMember ||
      isPrimary
    );
    var occupied = mapStatus(room && room.status) === 'occupied' && !!(room && room.stay);

    if (mergeBtn) mergeBtn.hidden = isMember;
    if (extendBtn) extendBtn.hidden = !occupied;
    if (unmergeBtn) unmergeBtn.hidden = !inGroup;
    if (unmergeGroupBtn) unmergeGroupBtn.hidden = !isPrimary;
    if (checkoutGroupBtn) checkoutGroupBtn.hidden = !isPrimary || !occupied;
    if (primaryBtn) primaryBtn.hidden = !isMember;

    paintStatusMenu(root, mapStatus(room && room.status));

    if (!banner) return;
    if (!inGroup) {
      banner.hidden = true;
      banner.innerHTML = '';
      return;
    }
    banner.hidden = false;
    if (isMember) {
      var bill = room.billingRoomNumber || room.billingRoomId || '—';
      var billId = room.billingRoomId || '';
      banner.innerHTML =
        '<span>Billing on <strong>Room ' +
        escapeHtml(bill) +
        '</strong>.</span>' +
        (billId
          ? ' <a href="/hotel/rooms/' +
            encodeURIComponent(billId) +
            '" data-hrd-merge-link>Open primary</a>'
          : '');
      banner.className = 'hrd-merge-banner hrd-merge-banner--member';
    } else {
      var partners = Array.isArray(room.mergePartnerNumbers)
        ? room.mergePartnerNumbers
        : [];
      var label =
        partners.length > 0
          ? 'Merged with Room ' + partners.join(', Room ')
          : room.mergeLabel || 'Merged rooms';
      banner.textContent = label + ' — shared invoice on this room.';
      banner.className = 'hrd-merge-banner hrd-merge-banner--primary';
    }
  }

  function paintRoom(root, room) {
    if (!root || !room) return;
    lastRoom = room;
    var asOf = headerAsOfDate(root);
    var view = viewRoomForDate(room, asOf);
    var inventory = mapStatus(room.status);
    var status = mapStatus(view.status);
    root.setAttribute('data-room-status', inventory);
    root.setAttribute('data-effective-status', status);
    if (room.number) root.setAttribute('data-room-number', room.number);
    if (room.roomType) root.setAttribute('data-room-type', room.roomType);
    if (room.roomTypeLabel) {
      root.setAttribute('data-room-type-label', room.roomTypeLabel);
    }
    root.setAttribute('data-merge-member', room.isMergeMember ? '1' : '0');
    root.setAttribute('data-merge-primary', room.isMergePrimary ? '1' : '0');

    var dirty = inventory === 'dirty' || status === 'dirty';
    var occupied = inventory === 'occupied' || status === 'occupied';
    var reserved = inventory === 'reserved' && !!(room && room.stay);
    /* Prefer inventory Occupied so checked-in rooms never paint Vacant.
       Future reserved stays stay Reserved on this page even when today is vacant. */
    var displayStatus = occupied ? 'occupied' : reserved ? 'reserved' : status;
    var badge = $('[data-room-status-badge]', root);
    if (badge) {
      badge.textContent = STATUS_LABELS[displayStatus] || displayStatus;
      badge.className = 'hrd-status-badge hrd-status-badge--' + displayStatus;
    }

    var statusEl = $('[data-kpi-status]', root);
    if (statusEl) statusEl.textContent = STATUS_LABELS[displayStatus] || displayStatus;

    /* Housekeeping card: only Cleaned or Dirty (not room occupancy). */
    var hkStatus = dirty ? 'dirty' : 'cleaned';
    var hk = $('[data-kpi-hk]', root);
    if (hk) hk.textContent = hkStatus === 'dirty' ? 'Dirty' : 'Cleaned';
    var hkIcon = $('[data-hk-icon]', root);
    if (hkIcon) {
      hkIcon.className =
        'hbe-kpi-icon hbe-kpi-icon--' + (hkStatus === 'dirty' ? 'red' : 'green') + ' hrd-kpi-icon';
    }
    setVisible($('#hrd-mark-clean', root), dirty && !occupied);
    paintMergeChrome(root, room);
    setVisible($('#hrd-mark-dirty', root), !dirty && !occupied);

    var adults = occupied && view.stay ? Number(view.stay.adults || 1) : 0;
    var children = occupied && view.stay ? Number(view.stay.children || 0) : 0;
    var guestCount = occupied ? Math.max(1, adults + children) : 0;
    var guestEl = $('[data-kpi-guests]', root);
    if (guestEl) guestEl.textContent = String(guestCount);
    var guestSub = $('[data-kpi-guests-sub]', root);
    if (guestSub) {
      guestSub.textContent = occupied
        ? 'Adults ' + adults + ' · Children ' + children
        : 'No guests in-house';
    }

    var checkOutDate =
      occupied && view.stay
        ? toDateISO(view.stay.checkOutDate || view.stay.check_out_date || '')
        : '';
    var checkoutDue = !!(occupied && checkOutDate && checkOutDate <= asOf);
    var checkoutCount = checkoutDue ? 1 : 0;
    var checkoutEl = $('[data-kpi-checkout]', root);
    if (checkoutEl) checkoutEl.textContent = String(checkoutCount);
    var checkoutSub = $('[data-kpi-checkout-sub]', root);
    if (checkoutSub) {
      if (!occupied) {
        checkoutSub.textContent = 'No checkout due';
      } else if (checkoutDue) {
        checkoutSub.textContent =
          checkOutDate === asOf ? 'Due for checkout today' : 'Checkout overdue';
      } else if (checkOutDate) {
        checkoutSub.textContent = 'Expected ' + prettyDateISO(checkOutDate);
      } else {
        checkoutSub.textContent = 'No expected checkout date';
      }
    }
    var stayCheckOutDate = toDateISO(
      (room.stay &&
        (room.stay.checkOutDate || room.stay.check_out_date || '')) ||
        ''
    );
    paintCheckoutDueBanner(
      root,
      inventory === 'occupied',
      stayCheckOutDate,
      asOf
    );

    var reserveBtn = $('#hrd-reserve', root);
    var reserveNewBtn = $('#hrd-reserve-new', root);
    if (reserveBtn) {
      /* Vacant/reserved: edit or create. Occupied: future dates only (upcomingStay). */
      var showReserve = true;
      setVisible(reserveBtn, showReserve);
      if (showReserve) {
        var reserveLabel =
          inventory === 'reserved'
            ? 'Edit Reservation'
            : inventory === 'occupied'
              ? 'Reserve'
              : 'Reserve';
        reserveBtn.innerHTML =
          '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M8 5V3M16 5V3M3 10h18"/></svg>' +
          reserveLabel;
        reserveBtn.setAttribute('data-action', 'reserve');
      }
    }
    if (reserveNewBtn) {
      setVisible(reserveNewBtn, inventory === 'reserved');
      if (inventory === 'reserved') {
        reserveNewBtn.innerHTML =
          '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>' +
          'New Reservation';
        reserveNewBtn.setAttribute('data-action', 'reserve-new');
      }
    }

    var startBtn = $('#hrd-start-checkin', root);
    if (startBtn) {
      startBtn.textContent = 'Start Check-In';
      startBtn.setAttribute('data-action', 'checkin');
    }

    paintGuestPanels(root, view);
  }

  function setStatus(root, nextStatus, successMessage) {
    var api = root.getAttribute('data-room-api') || '';
    var status = mapStatus(nextStatus);
    if (!api) {
      showToast('Room API unavailable.', true);
      return Promise.reject(new Error('missing api'));
    }
    var current = mapStatus(lastRoom && lastRoom.status);
    var hasStay = !!(lastRoom && lastRoom.stay);
    if (status === 'reserved' && current === 'occupied') {
      openReserveModal(root, { mode: 'edit' });
      return Promise.resolve(null);
    }
    if (status === 'dirty' && (current === 'occupied' || hasStay)) {
      var okDirty = global.confirm(
        'Mark this room Dirty? The guest will be checked out and the stay cleared.'
      );
      if (!okDirty) return Promise.resolve(null);
    }
    var body = { status: status };
    if (status === 'reserved') {
      var asOf = todayISO();
      body.checkInDate = asOf;
      body.checkOutDate = addDaysISO(asOf, 1);
      body.asOf = asOf;
    }
    return fetch(api, {
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
        paintRoom(root, result.data.room);
        var toastMsg =
          successMessage ||
          'Room updated to ' + (STATUS_LABELS[status] || status) + '.';
        if (
          status === 'dirty' &&
          (current === 'occupied' || hasStay) &&
          !successMessage
        ) {
          toastMsg = 'Guest checked out. Room is dirty.';
        }
        showToast(toastMsg);
        return result.data.room;
      })
      .catch(function (err) {
        showToast(err.message || 'Failed to update room.', true);
        throw err;
      });
  }

  function stayNeedsInvoiceForCheckout(room) {
    var stay = (room && room.stay) || null;
    if (!stay) return false;
    var mergeNums = Array.isArray(stay.mergeRoomNumbers) ? stay.mergeRoomNumbers : [];
    var hotelHistory = invoiceHistoryEntries(stay).filter(function (entry) {
      return entry.kind === 'hotel';
    });
    if (
      (room && room.isMergeMember) ||
      stay.mergeRole === 'member' ||
      stay.billingRoomId ||
      stay.billedInvoiceGenerated ||
      stay.billedInvoiceNumber ||
      (mergeNums.length > 1 &&
        (stay.invoiceGenerated || stay.invoiceNumber || hotelHistory.length))
    ) {
      return false;
    }
    if (!(stay.invoiceGenerated || stay.invoiceNumber || hotelHistory.length)) {
      return true;
    }
    return stayHasPendingCharges(stay, room);
  }

  function putRoomAction(root, body) {
    var api = root.getAttribute('data-room-api') || '';
    if (!api) {
      return Promise.reject(new Error('Room API unavailable.'));
    }
    return fetch(api, {
      method: 'PUT',
      credentials: 'same-origin',
      headers: apiHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(body)
    }).then(function (resp) {
      return resp.json().then(function (data) {
        return { ok: resp.ok, data: data };
      });
    });
  }

  function openCheckoutInvoiceModal(root) {
    var modal =
      (root && $('#hrd-checkout-invoice-modal', root)) ||
      document.getElementById('hrd-checkout-invoice-modal');
    if (!modal) {
      showToast('Generate Invoice to check out', true);
      return;
    }
    var stay = (lastRoom && lastRoom.stay) || null;
    var hotelHistory = invoiceHistoryEntries(stay).filter(function (entry) {
      return entry.kind === 'hotel';
    });
    var hasHotelInvoice = !!(
      stay &&
      (stay.invoiceGenerated ||
        stay.invoiceNumber ||
        stay.billedInvoiceGenerated ||
        stay.billedInvoiceNumber ||
        hotelHistory.length)
    );
    var needsAdditional = !!(hasHotelInvoice && stayHasPendingCharges(stay, lastRoom));
    var titleEl = modal.querySelector('#hrd-checkout-invoice-title');
    if (titleEl) {
      titleEl.textContent = needsAdditional
        ? 'Generate Additional Invoice to check out'
        : 'Generate Invoice to check out';
    }
    var go = $('#hrd-checkout-invoice-go', modal);
    var roomId = (root && root.getAttribute('data-room-id')) || '';
    if (go) {
      go.textContent = needsAdditional
        ? 'Generate Additional Invoice'
        : 'Generate Invoice';
      go.setAttribute(
        'href',
        roomId
          ? '/hotel/rooms/' + encodeURIComponent(roomId) + '/invoice?kind=hotel'
          : '#'
      );
    }
    modal.hidden = false;
    modal.setAttribute('aria-hidden', 'false');
    var closeBtn = modal.querySelector('[data-hrd-checkout-invoice-close]');
    if (closeBtn && typeof closeBtn.focus === 'function') closeBtn.focus();
  }

  function closeCheckoutInvoiceModal(root) {
    var modal =
      (root && $('#hrd-checkout-invoice-modal', root)) ||
      document.getElementById('hrd-checkout-invoice-modal');
    if (!modal) return;
    modal.hidden = true;
    modal.setAttribute('aria-hidden', 'true');
  }

  function checkoutGuest(root) {
    var api = root.getAttribute('data-room-api') || '';
    if (!api) {
      showToast('Room API unavailable.', true);
      return Promise.reject(new Error('missing api'));
    }
    var stay = (lastRoom && lastRoom.stay) || null;
    var balance = stay ? Number(stay.balanceAmount || 0) : 0;
    var isMember = !!(lastRoom && lastRoom.isMergeMember);
    var isPrimary = !!(lastRoom && lastRoom.isMergePrimary);
    if (stayNeedsInvoiceForCheckout(lastRoom)) {
      openCheckoutInvoiceModal(root);
      return Promise.resolve(null);
    }
    if (isPrimary) {
      var partners = (lastRoom.mergePartnerNumbers || []).join(', ');
      var okGroup = global.confirm(
        'This is the billing primary' +
          (partners ? ' (merged with Room ' + partners + ')' : '') +
          '. Checkout applies to this room only. Continue?'
      );
      if (!okGroup) return Promise.resolve(null);
    } else if (isMember) {
      var okMember = global.confirm(
        'This room will leave the shared bill on Room ' +
          (lastRoom.billingRoomNumber || '—') +
          '. Continue checkout?'
      );
      if (!okMember) return Promise.resolve(null);
    } else if (balance > 0.009) {
      var ok = global.confirm(
        'Balance due ' + moneyText(balance) + ' — check out anyway?'
      );
      if (!ok) return Promise.resolve(null);
    }
    return putRoomAction(root, { action: 'checkout' })
      .then(function (result) {
        if (!result.ok || !result.data || !result.data.ok) {
          var errMsg =
            (result.data && result.data.error) || 'Checkout failed.';
          if (/generate invoice to check out|additional invoice/i.test(errMsg)) {
            openCheckoutInvoiceModal(root);
            return null;
          }
          throw new Error(errMsg);
        }
        paintRoom(root, result.data.room);
        showToast('Guest checked out. Room is dirty.');
        return result.data.room;
      })
      .catch(function (err) {
        showToast(err.message || 'Checkout failed.', true);
        throw err;
      });
  }

  function checkoutMergeGroup(root) {
    var api = root.getAttribute('data-room-api') || '';
    if (!api) {
      showToast('Room API unavailable.', true);
      return Promise.reject(new Error('missing api'));
    }
    if (stayNeedsInvoiceForCheckout(lastRoom)) {
      openCheckoutInvoiceModal(root);
      return Promise.resolve(null);
    }
    var partners = ((lastRoom && lastRoom.mergePartnerNumbers) || []).join(', ');
    var here = (lastRoom && lastRoom.number) || '';
    var rooms = [here].concat(partners ? partners.split(/,\s*/) : []).filter(Boolean);
    var ok = global.confirm(
      'Check out all rooms in this merge' +
        (rooms.length ? ' (' + rooms.join(', ') + ')' : '') +
        '? Each occupied room will be marked dirty.'
    );
    if (!ok) return Promise.resolve(null);
    return putRoomAction(root, { action: 'checkout_group' })
      .then(function (result) {
        if (!result.ok || !result.data || !result.data.ok) {
          var errMsg =
            (result.data && result.data.error) || 'Checkout failed.';
          if (/generate invoice to check out|additional invoice/i.test(errMsg)) {
            openCheckoutInvoiceModal(root);
            return null;
          }
          throw new Error(errMsg);
        }
        paintRoom(root, result.data.room);
        showToast('All merged rooms checked out. Rooms are dirty.');
        return result.data.room;
      })
      .catch(function (err) {
        showToast(err.message || 'Checkout failed.', true);
        throw err;
      });
  }

  function closeInvoiceModal(root) {
    var modal = $('#hrd-invoice-modal', root) || document.getElementById('hrd-invoice-modal');
    if (!modal) return;
    modal.hidden = true;
    modal.setAttribute('aria-hidden', 'true');
    invoicePayBalanceMax = 0;
  }

  var HRD_INVOICE_METHODS_BASE = [
    ['cash', 'Cash'],
    ['upi', 'UPI'],
    ['card', 'Card'],
    ['bank_transfer', 'Bank Transfer']
  ];
  var HRD_INVOICE_TXN_METHODS = { bank_transfer: true };
  var invoicePayBalanceMax = 0;
  var invoiceAllowCredit = false;

  function stayHasAgency(stay) {
    return !!(stay && String(stay.agencyName || stay.agency_name || '').trim());
  }

  function invoicePaymentMethods() {
    var methods = HRD_INVOICE_METHODS_BASE.slice();
    if (invoiceAllowCredit) methods.push(['credit', 'Credit']);
    return methods;
  }

  function invoiceSplitRows(modal) {
    var root = $('#hrd-invoice-splits', modal);
    if (!root) return [];
    return Array.prototype.slice.call(root.querySelectorAll('.hrd-invoice-split-row'));
  }

  function invoiceMethodLabel(method) {
    var key = String(method || '');
    var methods = invoicePaymentMethods();
    for (var i = 0; i < methods.length; i++) {
      if (methods[i][0] === key) return methods[i][1];
    }
    return key || 'Select mode…';
  }

  function invoiceRowMethod(row) {
    var hidden = row && row.querySelector('.hrd-invoice-method-input');
    return hidden ? String(hidden.value || '') : '';
  }

  function invoiceUsedMethods(modal, exceptRow) {
    var used = {};
    invoiceSplitRows(modal).forEach(function (row) {
      if (row === exceptRow) return;
      var method = invoiceRowMethod(row);
      if (method) used[method] = true;
    });
    return used;
  }

  function invoiceMethodOptionsHtml(modal, selected, exceptRow) {
    var used = invoiceUsedMethods(modal, exceptRow);
    return invoicePaymentMethods()
      .map(function (pair) {
        var value = pair[0];
        var label = pair[1];
        if (used[value] && value !== selected) return '';
        var on = value === selected;
        return (
          '<button type="button" class="se-filter-listbox-option' +
          (on ? ' is-selected' : '') +
          '" role="option" data-value="' +
          escapeHtml(value) +
          '" aria-selected="' +
          (on ? 'true' : 'false') +
          '">' +
          escapeHtml(label) +
          '</button>'
        );
      })
      .join('');
  }

  function closeInvoiceSplitListbox(box) {
    if (!box) return;
    var trigger = box.querySelector('.se-filter-chip-trigger');
    var list =
      (box.__hrdPortaledList && box.__hrdPortaledList.isConnected
        ? box.__hrdPortaledList
        : null) || box.querySelector('.se-filter-listbox');
    box.classList.remove('is-open');
    if (trigger) trigger.setAttribute('aria-expanded', 'false');
    if (list) {
      list.hidden = true;
      list.scrollTop = 0;
      restoreInvoiceSplitListboxPanel(box, list);
    }
  }

  function restoreInvoiceSplitListboxPanel(box, list) {
    if (!list) return;
    var home = list.__hrdPortalHome;
    if (home && home.isConnected) {
      home.appendChild(list);
    } else if (box && box.isConnected) {
      box.appendChild(list);
    }
    list.classList.remove('ep-listbox-portaled');
    list.removeAttribute('data-hrd-invoice-listbox-portaled');
    list.__hrdPortalHome = null;
    if (box) box.__hrdPortaledList = null;
    list.style.position = '';
    list.style.left = '';
    list.style.right = '';
    list.style.top = '';
    list.style.bottom = '';
    list.style.width = '';
    list.style.minWidth = '';
    list.style.maxHeight = '';
    list.style.zIndex = '';
  }

  function positionInvoiceSplitListboxPanel(box, list) {
    if (!box || !list) return;
    var control = box.querySelector('.se-filter-chip-control') || box;
    var rect = control.getBoundingClientRect();
    var width = Math.max(rect.width, 160);
    var left = Math.min(rect.left, Math.max(8, window.innerWidth - width - 8));
    var spaceBelow = window.innerHeight - rect.bottom - 12;
    var spaceAbove = rect.top - 12;
    var openUp = spaceBelow < 200 && spaceAbove > spaceBelow;
    var maxHeight = Math.min(260, Math.max(160, openUp ? spaceAbove : spaceBelow));
    var host = document.getElementById('de-fs-app') || document.body;
    if (!list.__hrdPortalHome) list.__hrdPortalHome = list.parentNode;
    if (host && list.parentNode !== host) host.appendChild(list);
    list.classList.add('ep-listbox-portaled');
    list.setAttribute('data-hrd-invoice-listbox-portaled', '1');
    box.__hrdPortaledList = list;
    list.style.position = 'fixed';
    list.style.left = left + 'px';
    list.style.right = 'auto';
    list.style.width = width + 'px';
    list.style.minWidth = width + 'px';
    list.style.maxHeight = maxHeight + 'px';
    list.style.zIndex = '12050';
    if (openUp) {
      list.style.top = 'auto';
      list.style.bottom = window.innerHeight - rect.top + 6 + 'px';
    } else {
      list.style.bottom = 'auto';
      list.style.top = rect.bottom + 6 + 'px';
    }
  }

  function closeAllInvoiceSplitListboxes(modal, except) {
    invoiceSplitRows(modal).forEach(function (row) {
      var box = row.querySelector('[data-se-listbox]');
      if (box && box !== except) closeInvoiceSplitListbox(box);
    });
  }

  function openInvoiceSplitListbox(modal, box) {
    if (!box) return;
    closeAllInvoiceSplitListboxes(modal, box);
    var trigger = box.querySelector('.se-filter-chip-trigger');
    var list =
      (box.__hrdPortaledList && box.__hrdPortaledList.isConnected
        ? box.__hrdPortaledList
        : null) || box.querySelector('.se-filter-listbox');
    box.classList.add('is-open');
    if (trigger) trigger.setAttribute('aria-expanded', 'true');
    if (list) {
      list.hidden = false;
      positionInvoiceSplitListboxPanel(box, list);
    }
  }

  function syncInvoiceSplitRowState(row) {
    if (!row) return;
    var txn = row.querySelector('.hrd-invoice-split-txn');
    var method = invoiceRowMethod(row);
    var needsTxn = !!HRD_INVOICE_TXN_METHODS[method];
    row.classList.toggle('is-bank', needsTxn);
    if (txn) {
      txn.hidden = !needsTxn;
      if (!needsTxn) txn.value = '';
    }
  }

  function updateInvoiceSplitRemoveButtons(modal) {
    var rows = invoiceSplitRows(modal);
    var multi = rows.length > 1;
    rows.forEach(function (row) {
      var removeBtn = row.querySelector('.hrd-invoice-split-remove');
      if (removeBtn) removeBtn.hidden = !multi;
      row.classList.toggle('is-multi', multi);
      syncInvoiceSplitRowState(row);
    });
    var addBtn = $('#hrd-invoice-add-split', modal);
    if (addBtn) addBtn.disabled = rows.length >= invoicePaymentMethods().length;
  }

  function invoiceSplitListboxPanel(box) {
    if (!box) return null;
    if (box.__hrdPortaledList && box.__hrdPortaledList.isConnected) {
      return box.__hrdPortaledList;
    }
    return box.querySelector('.se-filter-listbox');
  }

  function refreshInvoiceSplitOptions(modal) {
    invoiceSplitRows(modal).forEach(function (row) {
      var box = row.querySelector('[data-se-listbox]');
      var list = invoiceSplitListboxPanel(box);
      var selected = invoiceRowMethod(row);
      if (list) list.innerHTML = invoiceMethodOptionsHtml(modal, selected, row);
      syncInvoiceSplitRowState(row);
    });
  }

  function invoiceSplitsTotal(modal) {
    var total = 0;
    invoiceSplitRows(modal).forEach(function (row) {
      var input = row.querySelector('.hrd-invoice-split-amount');
      var amount = Number(input && input.value);
      if (isFinite(amount) && amount > 0) total += amount;
    });
    return Math.round(total * 100) / 100;
  }

  function refreshInvoiceSplitBalance(modal) {
    var wrap = $('#hrd-invoice-split-balance', modal);
    var totalEl = $('#hrd-invoice-split-total', modal);
    var targetEl = $('#hrd-invoice-split-target', modal);
    var total = invoiceSplitsTotal(modal);
    var target = Math.round(Number(invoicePayBalanceMax || 0) * 100) / 100;
    if (totalEl) {
      totalEl.textContent = moneyText(total);
      totalEl.setAttribute('data-amount', String(total));
    }
    if (targetEl) {
      targetEl.textContent = moneyText(target);
      targetEl.setAttribute('data-amount', String(target));
    }
    if (wrap) wrap.hidden = invoiceSplitRows(modal).length < 2 && !(total > 0);
  }

  function syncInvoiceRemainingAmount(modal, changedRow) {
    var rows = invoiceSplitRows(modal);
    if (rows.length < 2) return;
    var target = Math.round(Number(invoicePayBalanceMax || 0) * 100) / 100;
    if (!(target > 0)) return;

    function amountRaw(row) {
      var input = row.querySelector('.hrd-invoice-split-amount');
      return input ? String(input.value || '').trim() : '';
    }
    function setAmount(row, value) {
      var input = row.querySelector('.hrd-invoice-split-amount');
      if (!input) return;
      input.value = value > 0 ? String(Math.round(value * 100) / 100) : '';
    }

    if (rows.length === 2) {
      var first = rows[0];
      var second = rows[1];
      if (!changedRow) {
        var firstRaw = amountRaw(first);
        var secondRaw = amountRaw(second);
        if (firstRaw && isFinite(Number(firstRaw)) && Number(firstRaw) > 0 && !secondRaw) {
          setAmount(second, target - Number(firstRaw));
        } else if (secondRaw && isFinite(Number(secondRaw)) && Number(secondRaw) > 0 && !firstRaw) {
          setAmount(first, target - Number(secondRaw));
        }
        return;
      }
      var otherRow = changedRow === first ? second : first;
      var raw = amountRaw(changedRow);
      var amount = Number(raw);
      if (!raw || !isFinite(amount) || amount <= 0) {
        setAmount(otherRow, 0);
        return;
      }
      setAmount(otherRow, target - amount);
      return;
    }

    var lastRow = rows[rows.length - 1];
    if (changedRow && changedRow === lastRow) return;
    var others = 0;
    var hasEarlier = false;
    for (var i = 0; i < rows.length - 1; i++) {
      var rawEarlier = amountRaw(rows[i]);
      var amountEarlier = Number(rawEarlier);
      if (rawEarlier && isFinite(amountEarlier) && amountEarlier > 0) {
        hasEarlier = true;
        others += amountEarlier;
      }
    }
    setAmount(lastRow, hasEarlier ? target - others : 0);
  }

  function bindInvoiceSplitListbox(modal, row) {
    var box = row && row.querySelector('[data-se-listbox]');
    if (!box || box.getAttribute('data-bound') === '1') return;
    box.setAttribute('data-bound', '1');
    box.__epListboxBound = true;
    var trigger = box.querySelector('.se-filter-chip-trigger');
    var list = box.querySelector('.se-filter-listbox');
    var hidden = box.querySelector('.hrd-invoice-method-input');
    var valueEl = box.querySelector('.se-filter-chip-value');
    if (!trigger || !list || !hidden) return;

    trigger.addEventListener('click', function (e) {
      e.preventDefault();
      e.stopPropagation();
      if (box.classList.contains('is-open')) closeInvoiceSplitListbox(box);
      else openInvoiceSplitListbox(modal, box);
    });
    list.addEventListener('click', function (e) {
      var option = e.target.closest('.se-filter-listbox-option');
      var activeList =
        (box.__hrdPortaledList && box.__hrdPortaledList.isConnected
          ? box.__hrdPortaledList
          : null) || list;
      if (!option || !activeList.contains(option)) return;
      e.preventDefault();
      var value = option.getAttribute('data-value') || '';
      var label = (option.textContent || '').trim();
      hidden.value = value;
      if (valueEl) valueEl.textContent = label || 'Select mode…';
      activeList.querySelectorAll('.se-filter-listbox-option').forEach(function (opt) {
        var on = opt === option;
        opt.classList.toggle('is-selected', on);
        opt.setAttribute('aria-selected', on ? 'true' : 'false');
      });
      closeInvoiceSplitListbox(box);
      syncInvoiceSplitRowState(row);
      refreshInvoiceSplitOptions(modal);
      refreshInvoiceSplitBalance(modal);
    });
  }

  function addInvoiceSplitRow(modal, preferredMethod, amount) {
    var root = $('#hrd-invoice-splits', modal);
    if (!root) return;
    if (invoiceSplitRows(modal).length >= invoicePaymentMethods().length) return;
    var method = preferredMethod == null ? '' : String(preferredMethod || '');
    if (method && invoiceUsedMethods(modal, null)[method]) method = '';
    if (!method) {
      var methods = invoicePaymentMethods();
      for (var i = 0; i < methods.length; i++) {
        if (!invoiceUsedMethods(modal, null)[methods[i][0]]) {
          method = methods[i][0];
          break;
        }
      }
    }
    var label = invoiceMethodLabel(method);
    var uid = 'hrd-inv-split-' + Date.now() + '-' + Math.floor(Math.random() * 1000);
    var row = document.createElement('div');
    row.className = 'hrd-invoice-split-row';
    row.innerHTML =
      '<div class="se-filter-chip se-filter-chip--listbox ep-form-listbox hrd-invoice-method-listbox" data-se-listbox>' +
      '<div class="se-filter-chip-control">' +
      '<span class="se-filter-chip-icon" aria-hidden="true">' +
      '<svg viewBox="0 0 24 24"><rect x="2" y="5" width="20" height="14" rx="2"/><path d="M2 10h20"/></svg>' +
      '</span>' +
      '<input type="hidden" class="hrd-invoice-method-input" value="' +
      escapeHtml(method) +
      '">' +
      '<button type="button" class="se-filter-chip-trigger" id="' +
      uid +
      '-trigger" aria-haspopup="listbox" aria-expanded="false" aria-controls="' +
      uid +
      '-list" aria-label="Payment mode">' +
      '<span class="se-filter-chip-value">' +
      escapeHtml(label) +
      '</span>' +
      '</button>' +
      '<span class="se-filter-chip-chev" aria-hidden="true">' +
      '<svg viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg>' +
      '</span>' +
      '</div>' +
      '<div class="se-filter-listbox" id="' +
      uid +
      '-list" role="listbox" aria-label="Payment mode" hidden>' +
      invoiceMethodOptionsHtml(modal, method, null) +
      '</div>' +
      '</div>' +
      '<input class="hrd-invoice-split-amount" type="number" min="0" step="0.01" placeholder="Amount" aria-label="Mode amount" value="' +
      escapeHtml(amount == null || amount === '' ? '' : amount) +
      '">' +
      '<input class="hrd-invoice-split-txn" type="text" placeholder="Txn / UTR ID" aria-label="Transaction ID" hidden autocomplete="off">' +
      '<button type="button" class="hrd-invoice-split-remove" aria-label="Remove payment mode" hidden>&times;</button>';
    root.appendChild(row);

    var amountInput = row.querySelector('.hrd-invoice-split-amount');
    var removeBtn = row.querySelector('.hrd-invoice-split-remove');
    bindInvoiceSplitListbox(modal, row);
    if (amountInput) {
      amountInput.addEventListener('input', function () {
        syncInvoiceRemainingAmount(modal, row);
        refreshInvoiceSplitBalance(modal);
      });
    }
    if (removeBtn) {
      removeBtn.addEventListener('click', function () {
        if (invoiceSplitRows(modal).length <= 1) return;
        closeAllInvoiceSplitListboxes(modal);
        row.remove();
        updateInvoiceSplitRemoveButtons(modal);
        refreshInvoiceSplitOptions(modal);
        refreshInvoiceSplitBalance(modal);
      });
    }
    syncInvoiceSplitRowState(row);
    updateInvoiceSplitRemoveButtons(modal);
    refreshInvoiceSplitOptions(modal);
    refreshInvoiceSplitBalance(modal);
  }

  function resetInvoiceSplits(modal, balance) {
    var root = $('#hrd-invoice-splits', modal);
    if (!root) return;
    root.innerHTML = '';
    invoicePayBalanceMax = Math.max(0, Math.round(Number(balance || 0) * 100) / 100);
    addInvoiceSplitRow(
      modal,
      'cash',
      invoicePayBalanceMax > 0 ? String(invoicePayBalanceMax) : '0'
    );
    refreshInvoiceSplitBalance(modal);
  }

  function openInvoiceModal(root, mode, opts) {
    opts = opts || {};
    var modal = $('#hrd-invoice-modal', root) || document.getElementById('hrd-invoice-modal');
    if (!modal) {
      showToast('Invoice dialog is unavailable on this page.', true);
      return;
    }
    var stay = (lastRoom && lastRoom.stay) || null;
    if (!stay) {
      showToast('No guest stay on this room.', true);
      return;
    }
    var summary = stayMoneySummary(stay, lastRoom);
    var isPay = mode === 'payment';
    var invoiceKind = String(opts.kind || 'all').toLowerCase();
    if (invoiceKind !== 'hotel' && invoiceKind !== 'fb') invoiceKind = 'all';
    var invoiceGenerated = !!(stay.invoiceGenerated || stay.invoiceNumber);
    var fbHistory = invoiceHistoryEntries(stay).filter(function (entry) {
      return entry.kind === 'fb';
    });
    var fbGenerated = fbHistory.length > 0;
    var hasPending = stayHasPendingCharges(stay, lastRoom);
    if (isPay && !invoiceGenerated && !fbGenerated) {
      showToast('Generate the invoice before recording payment.', true);
      return;
    }
    if (!isPay && invoiceKind === 'hotel' && invoiceGenerated) {
      var pendingHotelOnly = pendingHotelChargeLinesFromStay(stay, lastRoom);
      if (!pendingHotelOnly.length) {
        showToast('No pending room charges to invoice.');
        return;
      }
    }
    if (!isPay && invoiceKind === 'fb') {
      var pendingFbOnly = pendingFbChargeLinesFromStay(stay);
      if (!pendingFbOnly.length) {
        showToast('No pending F&B transfers to invoice.');
        return;
      }
    }
    if (!isPay && invoiceKind === 'all' && invoiceGenerated && !hasPending) {
      showToast('Invoice already generated.');
      return;
    }
    var modalHotelLines =
      isPay || (!invoiceGenerated && invoiceKind !== 'fb')
        ? summary.lines
        : pendingHotelChargeLinesFromStay(stay, lastRoom);
    /* Generate F&B must use pending transfers only — never roll prior FBE totals. */
    var fbModalMoney = null;
    var modalFbLines;
    if (!isPay && invoiceKind !== 'hotel') {
      fbModalMoney = summarizeFbChargeLines(pendingFbChargeLinesFromStay(stay));
      modalFbLines = fbModalMoney.lines;
    } else if (isPay) {
      modalFbLines = summary.fbLines || [];
    } else {
      modalFbLines = [];
    }
    if (!isPay && invoiceKind === 'hotel') {
      modalFbLines = [];
      fbModalMoney = null;
    }
    if (!isPay && invoiceKind === 'fb') {
      modalHotelLines = [];
    }
    var hasHotelCharges =
      modalHotelLines.length > 0 ||
      (invoiceKind !== 'fb' && !invoiceGenerated && summary.estimated > 0);
    var hasFbCharges =
      modalFbLines.length > 0 ||
      (invoiceKind !== 'hotel' &&
        !fbGenerated &&
        ((fbModalMoney && fbModalMoney.fbTotal > 0) || summary.fbTotal > 0));
    if (!isPay && (invoiceGenerated || fbGenerated) && hasPending) {
      hasHotelCharges = modalHotelLines.length > 0;
      hasFbCharges = modalFbLines.length > 0;
    }
    if (!hasHotelCharges && !hasFbCharges) {
      showToast(isPay ? 'No balance due.' : 'No charges to invoice yet.', true);
      return;
    }
    if (isPay && !(summary.combinedBalance > 0)) {
      showToast('Balance due is already settled.');
      return;
    }

    var modeEl = $('#hrd-invoice-mode', modal);
    if (modeEl) modeEl.value = isPay ? 'payment' : 'generate';
    var kindEl = $('#hrd-invoice-kind', modal);
    if (kindEl) kindEl.value = isPay ? 'all' : invoiceKind;
    var titleEl = $('#hrd-invoice-title', modal);
    var saveBtn = $('#hrd-invoice-save', modal);
    var generateLabel = 'Generate Invoice';
    if (!isPay) {
      if (invoiceKind === 'hotel') {
        generateLabel = invoiceGenerated
          ? 'Generate Additional Room Invoice'
          : 'Generate Room Invoice';
      } else if (invoiceKind === 'fb') {
        generateLabel = fbGenerated
          ? 'Generate Additional F&B Invoice'
          : 'Generate F&B Invoice';
      } else if ((invoiceGenerated || fbGenerated) && hasPending) {
        generateLabel = 'Generate Additional Invoice';
      }
    }
    if (titleEl) titleEl.textContent = isPay ? 'Record Payment' : generateLabel;
    if (saveBtn) saveBtn.textContent = isPay ? 'Record Payment' : generateLabel;

    var hotelBlock = $('#hrd-invoice-hotel-block', modal);
    var linesEl = $('#hrd-invoice-lines', modal);
    if (linesEl) {
      linesEl.innerHTML = chargeLinesHtml(modalHotelLines);
    }
    if (hotelBlock) {
      hotelBlock.hidden = !isPay && invoiceKind === 'fb';
    }
    var discRow = $('#hrd-invoice-discount-row', modal);
    var discHint = $('#hrd-invoice-discount-hint', modal);
    var discEl = $('#hrd-invoice-discount', modal);
    var subtotalEl = $('#hrd-invoice-subtotal', modal);
    var cgstEl = $('#hrd-invoice-cgst', modal);
    var ugstEl = $('#hrd-invoice-ugst', modal);
    var totalEl = $('#hrd-invoice-total', modal);
    var advanceEl = $('#hrd-invoice-advance', modal);
    var balanceEl = $('#hrd-invoice-balance', modal);
    var showDisc = Number(summary.discount) > 0 && invoiceKind !== 'fb';
    if (discRow) discRow.hidden = !showDisc;
    if (discHint) {
      discHint.textContent = showDisc
        ? formatDiscountHint(summary.discountType, summary.discountValue)
        : '';
    }
    if (discEl) discEl.textContent = showDisc ? '−' + moneyText(summary.discount) : '—';
    if (subtotalEl) subtotalEl.textContent = moneyText(summary.subtotal);
    if (cgstEl) cgstEl.textContent = moneyText(summary.cgst);
    if (ugstEl) ugstEl.textContent = moneyText(summary.ugst);
    if (totalEl) totalEl.textContent = moneyText(summary.estimated);
    if (advanceEl) advanceEl.textContent = moneyText(summary.advance);
    if (balanceEl) balanceEl.textContent = moneyText(summary.balance);

    var fbBlock = $('#hrd-invoice-fb-block', modal);
    var fbLinesEl = $('#hrd-invoice-fb-lines', modal);
    var fbNoEl = $('#hrd-invoice-fb-no', modal);
    var fbCgstEl = $('#hrd-invoice-fb-cgst', modal);
    var fbUgstEl = $('#hrd-invoice-fb-ugst', modal);
    var fbVatEl = $('#hrd-invoice-fb-vat', modal);
    var fbTotalEl = $('#hrd-invoice-fb-total', modal);
    var fbBalEl = $('#hrd-invoice-fb-balance', modal);
    var fbCgstRow = $('#hrd-invoice-fb-cgst-row', modal);
    var fbUgstRow = $('#hrd-invoice-fb-ugst-row', modal);
    var fbVatRow = $('#hrd-invoice-fb-vat-row', modal);
    var fbCgstHint = $('#hrd-invoice-fb-cgst-hint', modal);
    var fbUgstHint = $('#hrd-invoice-fb-ugst-hint', modal);
    var fbVatHint = $('#hrd-invoice-fb-vat-hint', modal);
    var combinedRow = $('#hrd-invoice-combined-row', modal);
    var combinedBalEl = $('#hrd-invoice-combined-balance', modal);
    var hotelNoEl = $('#hrd-invoice-hotel-no', modal);
    if (hotelNoEl) {
      var hbeNo = String(stay.invoiceNumber || '').trim();
      if (hbeNo && isPay) {
        setClickableInvoiceNo(hotelNoEl, hbeNo, {
          prefix: '',
          text: hbeNo,
          kind: 'hotel'
        });
      } else {
        setClickableInvoiceNo(hotelNoEl, '');
      }
    }
    if (fbBlock && fbLinesEl) {
      var fbLines = modalFbLines;
      var showFb =
        !(!isPay && invoiceKind === 'hotel') &&
        (fbLines.length > 0 ||
          (!fbGenerated &&
            ((fbModalMoney && fbModalMoney.fbTotal > 0) || summary.fbTotal > 0)) ||
          (isPay && summary.fbTotal > 0));
      fbBlock.hidden = !showFb;
      if (showFb) {
        fbLinesEl.innerHTML = chargeLinesHtml(fbLines);
        var fbNo = String(
          stay.fbTransferInvoiceNumber || stay.fb_transfer_invoice_number || ''
        ).trim();
        if (fbNoEl) {
          setClickableInvoiceNo(fbNoEl, isPay && fbNo ? fbNo : '', { kind: 'fb' });
        }
        var fbMoney = !isPay && fbModalMoney ? fbModalMoney : summary;
        paintFbTaxRows({
          cgstRow: fbCgstRow,
          ugstRow: fbUgstRow,
          vatRow: fbVatRow,
          cgstEl: fbCgstEl,
          ugstEl: fbUgstEl,
          vatEl: fbVatEl,
          cgstHint: fbCgstHint,
          ugstHint: fbUgstHint,
          vatHint: fbVatHint,
          fbCgst: fbMoney.fbCgst,
          fbUgst: fbMoney.fbUgst,
          fbVat: fbMoney.fbVat,
          fbCgstPct: fbMoney.fbCgstPct,
          fbUgstPct: fbMoney.fbUgstPct,
          fbVatPct: fbMoney.fbVatPct
        });
        if (fbTotalEl) fbTotalEl.textContent = moneyText(fbMoney.fbTotal);
        if (fbBalEl) {
          fbBalEl.textContent = moneyText(
            !isPay && fbModalMoney ? fbModalMoney.fbBalance : summary.fbBalance
          );
        }
      }
    }
    if (combinedRow) {
      var showCombined =
        isPay ||
        (invoiceKind === 'all' && hasHotelCharges && hasFbCharges);
      combinedRow.hidden = !showCombined;
      if (combinedBalEl) {
        combinedBalEl.textContent = showCombined
          ? moneyText(summary.combinedBalance)
          : '—';
      }
    }

    var payTarget =
      invoiceKind === 'hotel'
        ? summary.balance
        : invoiceKind === 'fb'
          ? summary.fbBalance
          : summary.combinedBalance;
    invoiceAllowCredit = stayHasAgency(stay);
    var payField = modal.querySelector('.hrd-invoice-pay-field');
    var skipPaymentOnGenerate = !isPay && invoiceKind === 'fb';
    if (payField) payField.hidden = skipPaymentOnGenerate;
    if (skipPaymentOnGenerate) {
      resetInvoiceSplits(modal, 0);
    } else {
      resetInvoiceSplits(modal, isPay || payTarget > 0 ? payTarget : 0);
    }
    var noteEl = $('#hrd-invoice-note', modal);
    if (noteEl) noteEl.value = '';
    var hintEl = $('#hrd-invoice-hint', modal);
    if (hintEl) {
      if (skipPaymentOnGenerate) {
        hintEl.hidden = true;
        hintEl.textContent = '';
      } else {
        hintEl.hidden = false;
        hintEl.textContent = invoiceAllowCredit
          ? 'Agency stay: Credit is available. Split across modes or pay any amount up to the balance.'
          : 'Split across modes or pay any amount up to the balance. Guest stays checked in.';
      }
    }
    modal.hidden = false;
    modal.setAttribute('aria-hidden', 'false');
    if (!skipPaymentOnGenerate) {
      var firstAmount = modal.querySelector('.hrd-invoice-split-amount');
      if (firstAmount) {
        try {
          firstAmount.focus();
          firstAmount.select();
        } catch (err) {}
      }
    }
  }

  function collectInvoicePaymentSplits(modal) {
    var splits = [];
    var rows = invoiceSplitRows(modal);
    for (var i = 0; i < rows.length; i++) {
      var row = rows[i];
      var method = invoiceRowMethod(row);
      var amountInput = row.querySelector('.hrd-invoice-split-amount');
      var txnInput = row.querySelector('.hrd-invoice-split-txn');
      var amount = Math.round(Number((amountInput && amountInput.value) || 0) * 100) / 100;
      if (!(amount > 0) && rows.length === 1) {
        continue;
      }
      if (!(amount > 0)) {
        return { error: 'Enter a valid amount for each payment mode.' };
      }
      if (!method) {
        return { error: 'Select a payment mode for each row.' };
      }
      var reference = String((txnInput && txnInput.value) || '').trim();
      if (method === 'bank_transfer' && !reference) {
        return { error: 'Transaction ID is required for bank transfer.' };
      }
      splits.push({
        payment_method: method,
        amount: amount,
        transaction_id: reference,
        reference: reference
      });
    }
    var total = Math.round(
      splits.reduce(function (sum, s) {
        return sum + Number(s.amount || 0);
      }, 0) * 100
    ) / 100;
    if (total - invoicePayBalanceMax > 0.009) {
      return {
        error:
          'Modes total ' +
          moneyText(total) +
          ' exceeds balance due ' +
          moneyText(invoicePayBalanceMax) +
          '.'
      };
    }
    return { splits: splits, total: total };
  }

  function submitInvoiceModal(root) {
    var modal = $('#hrd-invoice-modal', root) || document.getElementById('hrd-invoice-modal');
    var api = root.getAttribute('data-room-api') || '';
    if (!modal || !api) {
      showToast('Room API unavailable.', true);
      return Promise.reject(new Error('missing api'));
    }
    var modeEl = $('#hrd-invoice-mode', modal);
    var mode = String((modeEl && modeEl.value) || 'generate');
    var kindEl = $('#hrd-invoice-kind', modal);
    var invoiceKind = String((kindEl && kindEl.value) || 'all').toLowerCase();
    if (invoiceKind !== 'hotel' && invoiceKind !== 'fb') invoiceKind = 'all';
    var noteEl = $('#hrd-invoice-note', modal);
    var note = String((noteEl && noteEl.value) || '').trim();
    var skipPaymentOnGenerate = mode !== 'payment' && invoiceKind === 'fb';
    var collected = skipPaymentOnGenerate
      ? { splits: [], total: 0 }
      : collectInvoicePaymentSplits(modal);
    if (collected.error) {
      showToast(collected.error, true);
      return Promise.reject(new Error(collected.error));
    }
    if (mode === 'payment' && !(collected.total > 0)) {
      showToast('Enter a payment amount.', true);
      return Promise.reject(new Error('amount required'));
    }

    var body =
      mode === 'payment'
        ? {
            action: 'record_payment',
            payment_splits: collected.splits,
            note: note
          }
        : {
            action: 'generate_invoice',
            invoice_kind: invoiceKind,
            payment_splits: skipPaymentOnGenerate ? [] : collected.splits,
            note: note
          };
    var saveBtn = $('#hrd-invoice-save', modal);
    if (saveBtn) saveBtn.disabled = true;

    return fetch(api, {
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
          throw new Error((result.data && result.data.error) || 'Could not save invoice payment.');
        }
        paintRoom(root, result.data.room);
        closeInvoiceModal(root);
        var inv =
          (result.data.room &&
            result.data.room.stay &&
            result.data.room.stay.invoiceNumber) ||
          '';
        var fbInv =
          (result.data.fbInvoice && result.data.fbInvoice.invoiceNumber) ||
          (result.data.room &&
            result.data.room.stay &&
            result.data.room.stay.fbTransferInvoiceNumber) ||
          '';
        if (mode === 'payment') {
          showToast('Payment recorded' + (inv ? ' on ' + inv : '') + '.');
        } else {
          var hotelInv =
            (result.data.hotelInvoice && result.data.hotelInvoice.invoiceNumber) ||
            inv ||
            '';
          var msg = 'Invoice generated.';
          if (result.data.minted && hotelInv) {
            msg = 'Room invoice ' + hotelInv + ' generated.';
          }
          if (result.data.fbMinted && fbInv) {
            msg =
              (result.data.minted ? msg + ' ' : '') +
              'F&B invoice ' +
              fbInv +
              ' generated.';
          }
          if (collected.total > 0) msg += ' Payment recorded.';
          showToast(msg);
          if (
            result.data.minted &&
            typeof global.openHotelRoomInvoice === 'function' &&
            result.data.room
          ) {
            if (
              !global.openHotelRoomInvoice(result.data.room, {
                autoPrint: false,
                invoiceNumber: hotelInv || undefined
              })
            ) {
              showToast('Invoice saved. Could not open print preview.');
            }
          }
          if (
            result.data.fbMinted &&
            fbInv &&
            typeof global.openFbCombinedTransferInvoice === 'function' &&
            result.data.room
          ) {
            if (
              !global.openFbCombinedTransferInvoice(result.data.room, {
                autoPrint: false,
                invoiceNumber: fbInv
              })
            ) {
              showToast('F&B invoice saved. Could not open print preview.');
            }
          }
        }
        return result.data.room;
      })
      .catch(function (err) {
        showToast(err.message || 'Could not save invoice payment.', true);
        throw err;
      })
      .then(
        function (room) {
          if (saveBtn) saveBtn.disabled = false;
          return room;
        },
        function (err) {
          if (saveBtn) saveBtn.disabled = false;
          throw err;
        }
      );
  }

  function defaultRateForType(typeOrLabel) {
    var key = String(typeOrLabel || '').trim();
    if (key && DEFAULT_RATES[key] != null) return DEFAULT_RATES[key];
    var normalized = key.toLowerCase();
    var byLabel = {
      'premium room': 'premium_without_balcony',
      'deluxe with balcony': 'premium_deluxe_balcony',
      'suite room': 'premium_suite_tub',
      suite: 'premium_suite_tub',
      deluxe: 'premium_deluxe_balcony'
    };
    var mapped = byLabel[normalized];
    if (mapped && DEFAULT_RATES[mapped] != null) return DEFAULT_RATES[mapped];
    return 4500;
  }

  function defaultRateFor(root) {
    var type = (root && root.getAttribute('data-room-type')) || '';
    return defaultRateForType(type);
  }

  function positiveRoomRate(value) {
    if (value == null || value === '') return null;
    var n = Number(value);
    if (!isFinite(n) || n <= 0) return null;
    return Math.round(n * 100) / 100;
  }

  var SPECIAL_CHARGES = {
    earlyCheckin: {
      key: 'earlyCheckin',
      title: 'Early Check-in Charges',
      subtitle: 'Record additional charges for early check-in',
      toast: 'Early check-in charge added.',
      rateLabel: 'Charge amount',
      defaultRate: 500,
      showQty: false,
      showNights: false,
      checkboxId: 'hrd-ci-early-checkin',
      summaryId: 'hrd-ci-early-checkin-summary',
      editId: 'hrd-ci-early-checkin-edit',
      fields: {
        qty: 'earlyCheckinQty',
        rate: 'earlyCheckinRate',
        nights: 'earlyCheckinNights',
        amount: 'earlyCheckinAmount',
        note: 'earlyCheckinNote'
      }
    },
    lateCheckout: {
      key: 'lateCheckout',
      title: 'Late Check-out Charges',
      subtitle: 'Record additional charges for late check-out',
      toast: 'Late check-out charge added.',
      rateLabel: 'Charge amount',
      defaultRate: 500,
      showQty: false,
      showNights: false,
      checkboxId: 'hrd-ci-late-checkout',
      summaryId: 'hrd-ci-late-checkout-summary',
      editId: 'hrd-ci-late-checkout-edit',
      fields: {
        qty: 'lateCheckoutQty',
        rate: 'lateCheckoutRate',
        nights: 'lateCheckoutNights',
        amount: 'lateCheckoutAmount',
        note: 'lateCheckoutNote'
      }
    },
    extraBed: {
      key: 'extraBed',
      title: 'Extra Bed Charges',
      subtitle: 'Record additional charges for extra bed',
      toast: 'Extra bed charge added.',
      rateLabel: 'Rate (per night)',
      defaultRate: 1000,
      showQty: true,
      showNights: true,
      checkboxId: 'hrd-ci-extra-bed',
      summaryId: 'hrd-ci-extra-bed-summary',
      editId: 'hrd-ci-extra-bed-edit',
      fields: {
        qty: 'extraBedQty',
        rate: 'extraBedRate',
        nights: 'extraBedNights',
        amount: 'extraBedAmount',
        note: 'extraBedNote'
      }
    }
  };

  function specialChargeExtrasTotal(form) {
    if (!form) return 0;
    var total = 0;
    Object.keys(SPECIAL_CHARGES).forEach(function (key) {
      var amountName = SPECIAL_CHARGES[key].fields.amount;
      total += Math.max(0, Number((form.elements[amountName] && form.elements[amountName].value) || 0));
    });
    return total;
  }

  function parsedRoomRate(value) {
    if (value == null || value === '') return null;
    var n = Number(value);
    if (!isFinite(n) || n < 0) return null;
    return Math.round(n * 100) / 100;
  }

  function syncCompactNightlySeed(row) {
    if (!row || row.querySelector('[data-nightly-host]')) return;
    var rateEl = row.querySelector('[data-merge-room-rate]');
    var planEl = row.querySelector('[data-merge-rate-plan]');
    if (!rateEl && !planEl) return;
    var rate = Math.max(0, Number((rateEl && rateEl.value) || 0));
    var plan = planEl ? String(planEl.value || '') : '';
    var existing = [];
    try {
      var raw = row.getAttribute('data-nightly-seed');
      if (raw) existing = JSON.parse(raw) || [];
    } catch (err) {
      existing = [];
    }
    if (!Array.isArray(existing) || !existing.length) return;
    var next = existing.map(function (night) {
      return {
        date: night && night.date,
        roomRate: rate,
        ratePlan: plan
      };
    });
    try {
      row.setAttribute('data-nightly-seed', JSON.stringify(next));
    } catch (err2) {}
  }

  function syncTotals(form) {
    if (!form) return;
    $all('.hrd-ci-rate-room', form).forEach(function (row) {
      syncCompactNightlySeed(row);
      var nightly = collectNightlyRatesFromRoomEl(row);
      var rateHidden = row.querySelector('[data-merge-room-rate]');
      var planHidden = row.querySelector('[data-merge-rate-plan]');
      if (nightly.length && row.querySelector('[data-nightly-host]')) {
        if (rateHidden) rateHidden.value = String(nightly[0].roomRate);
        if (planHidden) planHidden.value = nightly[0].ratePlan || '';
      }
    });
    var rateSum = collectMergeNightlyRateSum(form);
    var primaryRate = primaryMergeRoomRate(form);
    var hiddenRate = form.elements.roomRate || $('#hrd-ci-room-rate', form);
    if (hiddenRate) hiddenRate.value = String(primaryRate);
    var hiddenPlan = form.elements.ratePlan || $('#hrd-ci-rate-plan', form);
    if (hiddenPlan) hiddenPlan.value = primaryMergeRatePlan(form) || '';
    var advance = Math.max(0, Number(form.advancePaid.value || 0));
    var extras = specialChargeExtrasTotal(form) + otherCustomChargesTotal(form);
    var total = Math.round((rateSum + extras) * 100) / 100;
    var balance = Math.max(0, Math.round((total - advance) * 100) / 100);
    form.totalRate.value = String(total);
    form.balanceAmount.value = String(balance);
  }

  function ratePlanListboxHtml(fid, selected, opts) {
    opts = opts || {};
    var plan = String(selected || '').trim().toUpperCase();
    if (plan && !RATE_PLAN_LABELS[plan]) plan = '';
    var hasValue = !!RATE_PLAN_LABELS[plan];
    var display = hasValue ? RATE_PLAN_LABELS[plan] : 'Select';
    var locked = !!opts.locked;
    var nightDate = opts.nightDate || '';
    var labelText = opts.label || 'Rate Plan';
    var planAttr = nightDate ? 'data-nightly-rate-plan' : 'data-merge-rate-plan';
    var keys = ['EP', 'CP', 'MAP', 'AP'];
    var options = keys
      .map(function (key) {
        var optLabel = RATE_PLAN_LABELS[key] || key;
        var on = hasValue && key === plan;
        return (
          '<button type="button" class="se-filter-listbox-option' +
          (on ? ' is-selected' : '') +
          '" role="option" data-value="' +
          key +
          '" data-label="' +
          escapeHtml(optLabel) +
          '" data-name="' +
          escapeHtml(String(optLabel).toLowerCase()) +
          '" aria-selected="' +
          (on ? 'true' : 'false') +
          '"' +
          (locked ? ' disabled' : '') +
          '>' +
          escapeHtml(optLabel) +
          '</button>'
        );
      })
      .join('');
    return (
      '<div class="se-filter-chip se-filter-chip--payment se-filter-chip--listbox ep-form-listbox hrd-form-listbox hrd-ci-rate-plan-listbox' +
      (locked ? ' is-locked is-disabled' : '') +
      '" data-se-listbox data-se-listbox-change="hrdCiMergeRatePlanChanged" id="' +
      fid +
      '-listbox">' +
      '<label class="se-filter-chip-label" id="' +
      fid +
      '-label" for="' +
      fid +
      '-trigger">' +
      escapeHtml(labelText) +
      '</label>' +
      '<div class="se-filter-chip-control">' +
      '<span class="se-filter-chip-icon" aria-hidden="true">' +
      '<svg viewBox="0 0 24 24"><rect x="2" y="5" width="20" height="14" rx="2"/><path d="M2 10h20"/></svg>' +
      '</span>' +
      '<input type="hidden" id="' +
      fid +
      '" ' +
      planAttr +
      (nightDate ? ' data-night-date="' + escapeHtml(nightDate) + '"' : '') +
      ' value="' +
      escapeHtml(hasValue ? plan : '') +
      '">' +
      '<button type="button" class="se-filter-chip-trigger" id="' +
      fid +
      '-trigger" aria-haspopup="listbox" aria-expanded="false" aria-controls="' +
      fid +
      '-list" aria-labelledby="' +
      fid +
      '-label ' +
      fid +
      '-value"' +
      (locked ? ' disabled' : '') +
      '>' +
      '<span class="se-filter-chip-value' +
      (hasValue ? '' : ' is-placeholder') +
      '" id="' +
      fid +
      '-value">' +
      escapeHtml(display) +
      '</span>' +
      '</button>' +
      '<span class="se-filter-chip-chev" aria-hidden="true">' +
      '<svg viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg>' +
      '</span>' +
      '</div>' +
      '<div class="se-filter-listbox" id="' +
      fid +
      '-list" role="listbox" aria-labelledby="' +
      fid +
      '-label" hidden>' +
      '<div class="ep-listbox-options">' +
      options +
      '</div></div></div>'
    );
  }

  function mergeRateRoomLabel(row) {
    var number = String((row && row.number) || '').trim();
    var typeLabel = String(
      (row && (row.roomTypeLabel || row.roomType || row.label)) || ''
    ).trim();
    if (number && typeLabel) return number + ' - ' + typeLabel;
    return number || typeLabel || 'Room';
  }

  function hotelBusinessTodayISO(root) {
    /* Past-night locks must follow real calendar today, not the board header
       as-of date (staff often scrub that while editing an in-house stay). */
    return todayISO();
  }

  function billableNightDates(checkIn, nights) {
    var start = toDateISO(checkIn);
    var count = Math.max(1, Number(nights || 1) || 1);
    if (!start) return [];
    var dates = [];
    for (var i = 0; i < count; i++) {
      var day = addDaysISO(start, i);
      if (day) dates.push(day);
    }
    return dates;
  }

  function formatNightDateLabel(iso) {
    var parts = String(iso || '').split('-');
    if (parts.length !== 3) return String(iso || '');
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
    var m = Number(parts[1]) - 1;
    var day = Number(parts[2]);
    var mon = months[m] || parts[1];
    return day + ' ' + mon + ' ' + parts[0];
  }

  function nightlyPlanCode(plan) {
    var key = String(plan || '').trim().toUpperCase();
    if (!RATE_PLAN_LABELS[key]) return '';
    return key;
  }

  function nightlyRowSummaryText(plan, rate) {
    var code = nightlyPlanCode(plan);
    if (!code) return moneyText(rate);
    return code + ' · ' + moneyText(rate);
  }

  function refreshNightlyRowSummary(row) {
    if (!row) return;
    var summary = row.querySelector('.hrd-ci-nightly-summary');
    if (!summary) return;
    var planEl = row.querySelector('[data-nightly-rate-plan]');
    var rateEl = row.querySelector('[data-nightly-room-rate]');
    var plan = planEl ? String(planEl.value || '') : '';
    var rate = rateEl ? Number(rateEl.value || 0) : 0;
    summary.textContent = nightlyRowSummaryText(plan, rate);
  }

  function nightlyToggleChevHtml() {
    return (
      '<span class="hrd-ci-nightly-chev" aria-hidden="true">' +
      '<svg viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg>' +
      '</span>'
    );
  }

  function ensureLockedNightlyHeader(row, locked) {
    if (!row) return;
    var dateWrap = row.querySelector('.hrd-ci-nightly-date');
    if (!dateWrap) return;
    if (locked) {
      if (dateWrap.tagName !== 'BUTTON') {
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = dateWrap.className;
        btn.setAttribute('data-nightly-toggle', '1');
        btn.setAttribute('aria-expanded', 'false');
        while (dateWrap.firstChild) btn.appendChild(dateWrap.firstChild);
        dateWrap.parentNode.replaceChild(btn, dateWrap);
        dateWrap = btn;
      } else {
        dateWrap.setAttribute('data-nightly-toggle', '1');
      }
      if (!dateWrap.querySelector('.hrd-ci-nightly-summary')) {
        var summary = document.createElement('span');
        summary.className = 'hrd-ci-nightly-summary';
        var lockEl = dateWrap.querySelector('.hrd-ci-nightly-lock');
        if (lockEl) dateWrap.insertBefore(summary, lockEl);
        else dateWrap.appendChild(summary);
      }
      if (!dateWrap.querySelector('.hrd-ci-nightly-chev')) {
        dateWrap.insertAdjacentHTML('beforeend', nightlyToggleChevHtml());
      }
      if (!dateWrap.querySelector('.hrd-ci-nightly-lock')) {
        var tip = document.createElement('span');
        tip.className = 'hrd-ci-nightly-lock';
        tip.textContent = 'Past · locked';
        var chev = dateWrap.querySelector('.hrd-ci-nightly-chev');
        if (chev) dateWrap.insertBefore(tip, chev);
        else dateWrap.appendChild(tip);
      }
      refreshNightlyRowSummary(row);
      dateWrap.setAttribute(
        'aria-expanded',
        row.classList.contains('is-collapsed') ? 'false' : 'true'
      );
    } else if (dateWrap.tagName === 'BUTTON') {
      var div = document.createElement('div');
      div.className = 'hrd-ci-nightly-date';
      var main = dateWrap.querySelector('.hrd-ci-nightly-date-main');
      if (main) div.appendChild(main);
      dateWrap.parentNode.replaceChild(div, dateWrap);
    }
  }

  function buildNightlyRatesForRoom(existing, dates, defaultRate, defaultPlan) {
    var byDate = {};
    (Array.isArray(existing) ? existing : []).forEach(function (item) {
      if (!item) return;
      var day = String(item.date || '').slice(0, 10);
      if (!day) return;
      byDate[day] = {
        roomRate: Math.max(0, Number(item.roomRate != null ? item.roomRate : item.room_rate || 0)),
        ratePlan: String(item.ratePlan || item.rate_plan || defaultPlan || '')
      };
    });
    var prevRate = Math.max(0, Number(defaultRate || 0));
    var prevPlan = defaultPlan || '';
    return dates.map(function (day) {
      var hit = byDate[day];
      var rate = hit && hit.roomRate != null ? hit.roomRate : prevRate;
      var plan = hit && hit.ratePlan ? hit.ratePlan : prevPlan;
      if (plan && !RATE_PLAN_LABELS[plan]) plan = prevPlan || '';
      prevRate = rate;
      prevPlan = plan;
      return { date: day, roomRate: rate, ratePlan: plan };
    });
  }

  function collectNightlyRatesFromRoomEl(row) {
    if (!row) return [];
    var fromDom = $all('.hrd-ci-nightly-row', row).map(function (nightRow) {
      var date = nightRow.getAttribute('data-night-date') || '';
      var rateEl = nightRow.querySelector('[data-nightly-room-rate]');
      var planEl = nightRow.querySelector('[data-nightly-rate-plan]');
      return {
        date: date,
        roomRate: Math.max(0, Number((rateEl && rateEl.value) || 0)),
        ratePlan: planEl ? String(planEl.value || '') : ''
      };
    });
    if (fromDom.length) return fromDom;
    syncCompactNightlySeed(row);
    try {
      var raw = row.getAttribute('data-nightly-seed');
      if (raw) {
        var parsed = JSON.parse(raw);
        if (Array.isArray(parsed) && parsed.length) return parsed;
      }
    } catch (err) {}
    return [];
  }

  function nightlyRatesHtml(roomKey, nightlyRates, today) {
    if (!nightlyRates || !nightlyRates.length) {
      return '<p class="hrd-ci-nightly-empty">Set check-in and nights to edit per-night rates.</p>';
    }
    return (
      '<div class="hrd-ci-nightly-list" role="list">' +
      nightlyRates
        .map(function (night, nIdx) {
          var nightDate = toDateISO(night.date) || String(night.date || '').slice(0, 10);
          var locked = !!(nightDate && today && nightDate < today);
          var plan = nightlyPlanCode(night.ratePlan);
          var rate = Math.max(0, Number(night.roomRate || 0));
          var fid =
            'hrd-ci-rate-plan-' +
            String(roomKey || 'room').replace(/[^\w-]/g, '') +
            '-n' +
            nIdx;
          var dateMain =
            '<div class="hrd-ci-nightly-date-main">' +
            '<span class="hrd-ci-nightly-date-label">Night</span>' +
            '<strong>' +
            escapeHtml(formatNightDateLabel(nightDate)) +
            '</strong>' +
            '</div>';
          var header = locked
            ? '<button type="button" class="hrd-ci-nightly-date" data-nightly-toggle aria-expanded="false">' +
              dateMain +
              '<span class="hrd-ci-nightly-summary">' +
              escapeHtml(nightlyRowSummaryText(plan, rate)) +
              '</span>' +
              '<span class="hrd-ci-nightly-lock">Past · locked</span>' +
              nightlyToggleChevHtml() +
              '</button>'
            : '<div class="hrd-ci-nightly-date">' + dateMain + '</div>';
          return (
            '<div class="hrd-ci-nightly-row' +
            (locked ? ' is-locked is-collapsed' : '') +
            '" role="listitem" data-night-date="' +
            escapeHtml(nightDate || '') +
            '" data-locked="' +
            (locked ? '1' : '0') +
            '">' +
            header +
            '<div class="hrd-ci-nightly-fields">' +
            ratePlanListboxHtml(fid, plan, {
              nightDate: nightDate,
              locked: locked,
              label: 'Meal plan'
            }) +
            '<label class="hrd-field hrd-ci-nightly-rate-field">' +
            '<span>Room rate</span>' +
            '<span class="hrd-input-affix"><span>₹</span>' +
            '<input type="number" min="0.01" step="0.01" required data-nightly-room-rate data-night-date="' +
            escapeHtml(nightDate || '') +
            '" placeholder="0" value="' +
            escapeHtml(rate > 0 ? String(rate) : '') +
            '"' +
            (locked ? ' readonly disabled' : '') +
            '></span>' +
            '</label>' +
            '</div></div>'
          );
        })
        .join('') +
      '</div>'
    );
  }

  function collectMergeNightlyRateSum(form) {
    if (!form) return 0;
    var rooms = $all('.hrd-ci-rate-room', form);
    if (rooms.length) {
      var sum = 0;
      var nightCount = Math.max(1, Number(form.nights && form.nights.value) || 1);
      rooms.forEach(function (row) {
        var nightly = collectNightlyRatesFromRoomEl(row);
        if (nightly.length) {
          nightly.forEach(function (n) {
            sum += Math.max(0, Number(n.roomRate || 0));
          });
          return;
        }
        var rateEl = row.querySelector('[data-merge-room-rate]');
        sum += Math.max(0, Number((rateEl && rateEl.value) || 0)) * nightCount;
      });
      return Math.round(sum * 100) / 100;
    }
    return Math.max(0, Number((form.elements.roomRate && form.elements.roomRate.value) || 0));
  }

  function primaryNightlyPick(form, attr) {
    if (!form) return null;
    var primary =
      form.querySelector('.hrd-ci-rate-room[data-merge-primary="1"]') ||
      form.querySelector('.hrd-ci-rate-room');
    if (!primary) return null;
    var rows = $all('.hrd-ci-nightly-row', primary);
    var pick = null;
    for (var i = 0; i < rows.length; i++) {
      if (rows[i].getAttribute('data-locked') !== '1') {
        pick = rows[i];
        break;
      }
    }
    if (!pick && rows.length) pick = rows[0];
    if (!pick) return null;
    if (attr === 'rate') {
      var rateEl = pick.querySelector('[data-nightly-room-rate]');
      return rateEl ? Math.max(0, Number(rateEl.value || 0)) : 0;
    }
    var planEl = pick.querySelector('[data-nightly-rate-plan]');
    return planEl ? String(planEl.value || '') : '';
  }

  function primaryMergeRoomRate(form) {
    if (!form) return 0;
    var fromNight = primaryNightlyPick(form, 'rate');
    if (fromNight != null && !isNaN(fromNight)) return fromNight;
    var primary = form.querySelector(
      '.hrd-ci-rate-room[data-merge-primary="1"] [data-merge-room-rate]'
    );
    if (primary) return Math.max(0, Number(primary.value || 0));
    var first = form.querySelector('[data-merge-room-rate]');
    if (first) return Math.max(0, Number(first.value || 0));
    return Math.max(0, Number((form.elements.roomRate && form.elements.roomRate.value) || 0));
  }

  function firstMissingRoomRateInput(form) {
    if (!form) return null;
    var nodes = $all('[data-nightly-room-rate], [data-merge-room-rate]', form);
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      if (el.disabled) continue;
      if (el.closest && el.closest('.hrd-ci-nightly-row.is-locked')) continue;
      var raw = String(el.value || '').trim();
      var amount = Number(raw);
      if (!raw || !isFinite(amount) || amount <= 0) return el;
    }
    var hidden = form.elements.roomRate || $('#hrd-ci-room-rate', form);
    if (!nodes.length && hidden && !hidden.disabled) {
      var hiddenRaw = String(hidden.value || '').trim();
      var hiddenAmount = Number(hiddenRaw);
      if (!hiddenRaw || !isFinite(hiddenAmount) || hiddenAmount <= 0) return hidden;
    }
    return null;
  }

  function firstMissingMealPlanInput(form) {
    if (!form) return null;
    var nodes = $all('[data-nightly-rate-plan], [data-merge-rate-plan]', form);
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      if (el.disabled) continue;
      if (el.closest && el.closest('.hrd-ci-nightly-row.is-locked')) continue;
      var plan = String(el.value || '').trim().toUpperCase();
      if (!RATE_PLAN_LABELS[plan]) return el;
    }
    return null;
  }

  function primaryMergeRatePlan(form) {
    if (!form) return '';
    var fromNight = primaryNightlyPick(form, 'plan');
    if (fromNight) return fromNight;
    var primary = form.querySelector(
      '.hrd-ci-rate-room[data-merge-primary="1"] [data-merge-rate-plan]'
    );
    if (primary) return String(primary.value || '');
    var first = form.querySelector('[data-merge-rate-plan]');
    if (first) return String(first.value || '');
    return '';
  }

  function stripStayMealPlans(stay) {
    if (!stay) return stay;
    var next = Object.assign({}, stay);
    next.ratePlan = '';
    if (Array.isArray(stay.nightlyRates)) {
      next.nightlyRates = stay.nightlyRates.map(function (night) {
        return Object.assign({}, night || {}, { ratePlan: '' });
      });
    }
    if (Array.isArray(stay.mergeRoomRates)) {
      next.mergeRoomRates = stay.mergeRoomRates.map(function (row) {
        var copy = Object.assign({}, row || {}, { ratePlan: '' });
        if (Array.isArray(row && row.nightlyRates)) {
          copy.nightlyRates = row.nightlyRates.map(function (night) {
            return Object.assign({}, night || {}, { ratePlan: '' });
          });
        }
        return copy;
      });
    }
    return next;
  }

  function collectMergeRoomRates(form) {
    if (!form) return [];
    return $all('.hrd-ci-rate-room', form).map(function (row) {
      var nightly = collectNightlyRatesFromRoomEl(row);
      var rateEl = row.querySelector('[data-merge-room-rate]');
      var planEl = row.querySelector('[data-merge-rate-plan]');
      var firstNight = nightly[0] || null;
      return {
        roomId: row.getAttribute('data-room-id') || '',
        number: row.getAttribute('data-room-number') || '',
        roomType: row.getAttribute('data-room-type') || '',
        roomTypeLabel: row.getAttribute('data-room-type-label') || '',
        ratePlan: firstNight
          ? firstNight.ratePlan
          : planEl
            ? String(planEl.value || '')
            : '',
        roomRate: firstNight
          ? firstNight.roomRate
          : Math.max(0, Number((rateEl && rateEl.value) || 0)),
        nightlyRates: nightly,
        isPrimary: row.getAttribute('data-merge-primary') === '1'
      };
    });
  }

  function applyNightlyRowLocks(form) {
    if (!form) return;
    var today = todayISO();
    $all('.hrd-ci-nightly-row', form).forEach(function (row) {
      var nightDate = toDateISO(row.getAttribute('data-night-date') || '');
      var locked = !!(nightDate && today && nightDate < today);
      var wasLocked = row.getAttribute('data-locked') === '1';
      row.classList.toggle('is-locked', locked);
      row.setAttribute('data-locked', locked ? '1' : '0');
      if (locked) {
        if (!wasLocked || !row.hasAttribute('data-user-expanded')) {
          row.classList.add('is-collapsed');
        }
        ensureLockedNightlyHeader(row, true);
      } else {
        row.classList.remove('is-collapsed');
        row.removeAttribute('data-user-expanded');
        ensureLockedNightlyHeader(row, false);
        var lockLabel = row.querySelector('.hrd-ci-nightly-lock');
        if (lockLabel) lockLabel.remove();
        var summary = row.querySelector('.hrd-ci-nightly-summary');
        if (summary) summary.remove();
        var chev = row.querySelector('.hrd-ci-nightly-chev');
        if (chev) chev.remove();
      }
      $all('[data-nightly-room-rate]', row).forEach(function (el) {
        el.disabled = locked;
        el.readOnly = locked;
      });
      $all('.hrd-ci-rate-plan-listbox', row).forEach(function (lb) {
        lb.classList.toggle('is-locked', locked);
        lb.classList.toggle('is-disabled', locked);
        var trigger = lb.querySelector('.se-filter-chip-trigger');
        if (trigger) trigger.disabled = locked;
      });
    });
  }

  function rebuildCheckinNightlyLists(root, form) {
    if (!form) return;
    root = root || pageRoot();
    var dates = billableNightDates(form.checkInDate && form.checkInDate.value, form.nights && form.nights.value);
    var today = hotelBusinessTodayISO(root);
    $all('.hrd-ci-rate-room', form).forEach(function (row, idx) {
      var existing = collectNightlyRatesFromRoomEl(row);
      if (!existing.length) {
        try {
          var raw = row.getAttribute('data-nightly-seed');
          if (raw) existing = JSON.parse(raw) || [];
        } catch (err) {
          existing = [];
        }
      }
      var defaultRate = Math.max(
        0,
        Number(
          (existing[0] && existing[0].roomRate) ||
            (row.querySelector('[data-merge-room-rate]') &&
              row.querySelector('[data-merge-room-rate]').value) ||
            0
        )
      );
      var defaultPlan =
        (existing[0] && existing[0].ratePlan) ||
        (row.querySelector('[data-merge-rate-plan]') &&
          row.querySelector('[data-merge-rate-plan]').value) ||
        '';
      var nightly = buildNightlyRatesForRoom(existing, dates, defaultRate, defaultPlan);
      try {
        row.setAttribute('data-nightly-seed', JSON.stringify(nightly));
      } catch (err2) {}
      var listHost = row.querySelector('[data-nightly-host]');
      if (listHost) {
        var roomKey = row.getAttribute('data-room-id') || row.getAttribute('data-room-number') || idx;
        listHost.innerHTML = nightlyRatesHtml(roomKey, nightly, today);
      }
      var compactRate = row.querySelector(
        '.hrd-ci-nightly-block--compact [data-merge-room-rate]'
      );
      if (compactRate && document.activeElement !== compactRate) {
        compactRate.value = String(
          (nightly[0] && nightly[0].roomRate) != null
            ? nightly[0].roomRate
            : defaultRate
        );
      }
      var compactPlan = row.querySelector(
        '.hrd-ci-nightly-block--compact [data-merge-rate-plan]'
      );
      if (compactPlan) {
        compactPlan.value =
          (nightly[0] && nightly[0].ratePlan) || defaultPlan || '';
      }
    });
    if (typeof global.initEpListboxes === 'function') {
      global.initEpListboxes();
    }
    if (typeof global.rebindEpListbox === 'function') {
      $all('[data-se-listbox]', form).forEach(function (lb) {
        global.rebindEpListbox(lb);
      });
    }
    applyNightlyRowLocks(form);
    syncTotals(form);
  }

  function buildCheckinRateRooms(root, form, opts) {
    opts = opts || {};
    var wrap = $('#hrd-ci-rate-rooms', form) || $('#hrd-ci-rate-rooms', root);
    if (!wrap || !form) return;
    var stay = opts.stay || null;
    var savedRates = Array.isArray(stay && stay.mergeRoomRates)
      ? stay.mergeRoomRates
      : [];
    function savedFor(roomId, number) {
      for (var i = 0; i < savedRates.length; i++) {
        var row = savedRates[i];
        if (!row) continue;
        if (roomId && String(row.roomId || '') === String(roomId)) return row;
        if (number && String(row.number || '') === String(number)) return row;
      }
      return null;
    }

    var rooms = [];
    var primaryId = root.getAttribute('data-room-id') || '';
    var primaryNumber = root.getAttribute('data-room-number') || '';
    var primaryTypeKey = root.getAttribute('data-room-type') || '';
    var primaryTypeLabel =
      root.getAttribute('data-room-type-label') || primaryTypeKey || '';
    if (lastRoom) {
      primaryId = lastRoom.id || primaryId;
      primaryNumber = lastRoom.number || primaryNumber;
      primaryTypeKey = lastRoom.roomType || primaryTypeKey;
      primaryTypeLabel =
        lastRoom.roomTypeLabel || lastRoom.roomType || primaryTypeLabel;
    }
    var primarySaved = savedFor(primaryId, primaryNumber);
    var primaryFromSaved = parsedRoomRate(primarySaved && primarySaved.roomRate);
    var primaryFromStay = parsedRoomRate(stay && stay.roomRate);
    var pageIsMergePrimary = !!(lastRoom && lastRoom.isMergePrimary);
    var pageIsMergeMember = !!(lastRoom && lastRoom.isMergeMember);
    var pageNightly =
      (primarySaved && primarySaved.nightlyRates) ||
      (!pageIsMergeMember && stay && stay.nightlyRates) ||
      [];
    rooms.push({
      roomId: primaryId,
      number: primaryNumber,
      roomType: primaryTypeKey,
      roomTypeLabel: primaryTypeLabel,
      ratePlan:
        (primarySaved && primarySaved.ratePlan) ||
        (pageIsMergeMember ? '' : stay && stay.ratePlan) ||
        '',
      /* Stay prices are typed in this form — never fall back to Hotel Settings. */
      roomRate:
        primaryFromSaved != null
          ? primaryFromSaved
          : !pageIsMergeMember && primaryFromStay != null
            ? primaryFromStay
            : 0,
      nightlyRates: Array.isArray(pageNightly) ? pageNightly : [],
      isPrimary: pageIsMergePrimary || !pageIsMergeMember
    });

    var partners =
      (lastRoom && Array.isArray(lastRoom.mergePartners) && lastRoom.mergePartners) ||
      [];
    if (!partners.length && lastRoom && Array.isArray(lastRoom.mergePartnerNumbers)) {
      partners = lastRoom.mergePartnerNumbers.map(function (n) {
        return { number: n, id: '', roomTypeLabel: '', roomType: '' };
      });
    }
    /* Primary check-in/edit lists every merged room's tariff. Member rooms
       only show this room's tariff — not the rest of the group. */
    if (pageIsMergePrimary) {
      partners.forEach(function (peer) {
        if (!peer) return;
        var pid = peer.id || peer.roomId || '';
        var pnum = peer.number || '';
        if (pid && String(pid) === String(primaryId)) return;
        if (pnum && String(pnum) === String(primaryNumber)) return;
        var saved = savedFor(pid, pnum);
        var peerType = peer.roomType || '';
        var peerLabel = peer.roomTypeLabel || peer.roomType || '';
        var savedRate = parsedRoomRate(saved && saved.roomRate);
        rooms.push({
          roomId: pid,
          number: pnum,
          roomType: peerType,
          roomTypeLabel: peerLabel,
          ratePlan: (saved && saved.ratePlan) || '',
          roomRate: savedRate != null ? savedRate : 0,
          nightlyRates: (saved && saved.nightlyRates) || [],
          isPrimary: false
        });
      });
    }

    var dates = billableNightDates(
      (form.checkInDate && form.checkInDate.value) || (stay && stay.checkInDate),
      (form.nights && form.nights.value) || (stay && stay.nights) || 1
    );
    var today = hotelBusinessTodayISO(root);

    wrap.innerHTML = rooms
      .map(function (row, idx) {
        var plan = row.ratePlan || '';
        var rate = Math.max(0, Number(row.roomRate || 0));
        var nightly = buildNightlyRatesForRoom(row.nightlyRates, dates, rate, plan);
        var roomKey = String(row.roomId || row.number || idx).replace(/[^\w-]/g, '');
        var seed = '';
        try {
          seed = escapeHtml(JSON.stringify(nightly));
        } catch (err) {
          seed = '';
        }
        var showNightlyEditor = !!(row.isPrimary || rooms.length === 1);
        var rateValue = rate > 0 ? String(rate) : '';
        var nightlyBlock = showNightlyEditor
          ? '<div class="hrd-ci-nightly-block">' +
            '<p class="hrd-ci-nightly-heading">Nightly rates &amp; Meal plan</p>' +
            '<div data-nightly-host>' +
            nightlyRatesHtml(roomKey, nightly, today) +
            '</div></div>'
          : '<div class="hrd-ci-nightly-block hrd-ci-nightly-block--compact">' +
            '<p class="hrd-ci-nightly-heading">Tariff</p>' +
            '<div class="hrd-ci-nightly-fields">' +
            ratePlanListboxHtml('hrd-ci-merge-plan-' + roomKey, plan, {
              label: 'Meal plan'
            }) +
            '<label class="hrd-field hrd-ci-nightly-rate-field">' +
            '<span>Room rate</span>' +
            '<span class="hrd-input-affix"><span>₹</span>' +
            '<input type="number" min="0.01" step="0.01" required inputmode="decimal" data-merge-room-rate placeholder="0" value="' +
            escapeHtml(rateValue) +
            '"></span></label></div></div>';
        return (
          '<div class="hrd-ci-rate-room" data-room-id="' +
          escapeHtml(row.roomId || '') +
          '" data-room-number="' +
          escapeHtml(row.number || '') +
          '" data-room-type="' +
          escapeHtml(row.roomType || '') +
          '" data-room-type-label="' +
          escapeHtml(row.roomTypeLabel || '') +
          '" data-merge-primary="' +
          (row.isPrimary ? '1' : '0') +
          '" data-nightly-seed="' +
          seed +
          '">' +
          (rooms.length > 1
            ? '<p class="hrd-ci-rate-room-title">Room ' +
              escapeHtml(row.number || String(idx + 1)) +
              (row.isPrimary ? ' (Primary)' : '') +
              '</p>'
            : '') +
          '<label class="hrd-field">' +
          '<span>Room Number</span>' +
          '<input type="text" readonly value="' +
          escapeHtml(mergeRateRoomLabel(row)) +
          '">' +
          '</label>' +
          (showNightlyEditor
            ? '<input type="hidden" data-merge-room-rate value="' +
              escapeHtml(String(rate)) +
              '">' +
              '<input type="hidden" data-merge-rate-plan value="' +
              escapeHtml(plan) +
              '">'
            : '') +
          nightlyBlock +
          '</div>'
        );
      })
      .join('');

    if (typeof global.initEpListboxes === 'function') {
      global.initEpListboxes();
    }
    if (typeof global.rebindEpListbox === 'function') {
      $all('[data-se-listbox]', wrap).forEach(function (lb) {
        global.rebindEpListbox(lb);
      });
    }
    applyNightlyRowLocks(form);
    syncTotals(form);
  }

  function moneyText(n) {
    var v = Math.round(Number(n || 0) * 100) / 100;
    return '₹' + v.toLocaleString('en-IN', { minimumFractionDigits: 0, maximumFractionDigits: 2 });
  }

  function clearSpecialCharge(form, kind) {
    var cfg = SPECIAL_CHARGES[kind];
    if (!form || !cfg) return;
    var f = cfg.fields;
    if (form.elements[f.qty]) form.elements[f.qty].value = '';
    if (form.elements[f.rate]) form.elements[f.rate].value = '';
    if (form.elements[f.nights]) form.elements[f.nights].value = '';
    if (form.elements[f.amount]) form.elements[f.amount].value = '0';
    if (form.elements[f.note]) form.elements[f.note].value = '';
    var summary = form.querySelector('#' + cfg.summaryId);
    var editBtn = form.querySelector('#' + cfg.editId);
    if (summary) {
      summary.hidden = true;
      summary.textContent = '';
    }
    if (editBtn) editBtn.hidden = true;
    syncTotals(form);
  }

  function clearAllSpecialCharges(form) {
    Object.keys(SPECIAL_CHARGES).forEach(function (kind) {
      clearSpecialCharge(form, kind);
    });
  }

  function applySpecialCharge(form, kind, data) {
    var cfg = SPECIAL_CHARGES[kind];
    if (!form || !cfg || !data) return;
    var qty = cfg.showQty ? Math.max(1, Number(data.qty || 1)) : 1;
    var rate = Math.max(0, Number(data.rate || 0));
    var nights = cfg.showNights ? Math.max(1, Number(data.nights || 1)) : 1;
    var amount = Math.round(qty * rate * nights * 100) / 100;
    var note = String(data.note || '').trim();
    var f = cfg.fields;
    if (form.elements[f.qty]) form.elements[f.qty].value = String(qty);
    if (form.elements[f.rate]) form.elements[f.rate].value = String(rate);
    if (form.elements[f.nights]) form.elements[f.nights].value = String(nights);
    if (form.elements[f.amount]) form.elements[f.amount].value = String(amount);
    if (form.elements[f.note]) form.elements[f.note].value = note;
    var summary = form.querySelector('#' + cfg.summaryId);
    var editBtn = form.querySelector('#' + cfg.editId);
    if (summary) {
      summary.hidden = false;
      if (cfg.showQty || cfg.showNights) {
        summary.textContent =
          qty +
          ' × ' +
          moneyText(rate) +
          (cfg.showNights
            ? ' × ' + nights + ' night' + (nights === 1 ? '' : 's')
            : '') +
          ' = ' +
          moneyText(amount);
      } else {
        summary.textContent = moneyText(amount) + (note ? ' · ' + note : '');
      }
    }
    if (editBtn) editBtn.hidden = false;
    syncTotals(form);
  }

  function syncSpecialChargeDialogAmount(dialogForm) {
    if (!dialogForm) return;
    var qty = Math.max(1, Number(dialogForm.elements.qty.value || 1));
    var rate = Math.max(0, Number(dialogForm.elements.rate.value || 0));
    var nights = Math.max(1, Number(dialogForm.elements.nights.value || 1));
    dialogForm.elements.amount.value = String(Math.round(qty * rate * nights * 100) / 100);
  }

  function openSpecialChargeModal(root, kind, opts) {
    opts = opts || {};
    var cfg = SPECIAL_CHARGES[kind];
    var modal = $('#hrd-special-charge-modal', root);
    var checkinForm = $('#hrd-checkin-form', root);
    var dialogForm = $('#hrd-special-charge-form', root);
    if (!cfg || !modal || !dialogForm || !checkinForm) return;
    var stayNights = Math.max(1, Number(checkinForm.nights.value || 1));
    var f = cfg.fields;
    var existingQty = Number((checkinForm.elements[f.qty] && checkinForm.elements[f.qty].value) || 0);
    var existingRate = Number((checkinForm.elements[f.rate] && checkinForm.elements[f.rate].value) || 0);
    var existingNights = Number((checkinForm.elements[f.nights] && checkinForm.elements[f.nights].value) || 0);
    var existingNote = (checkinForm.elements[f.note] && checkinForm.elements[f.note].value) || '';
    dialogForm.elements.chargeKind.value = kind;
    dialogForm.elements.qty.value = String(existingQty > 0 ? existingQty : 1);
    dialogForm.elements.rate.value = String(existingRate > 0 ? existingRate : cfg.defaultRate);
    dialogForm.elements.nights.value = String(
      existingNights > 0 ? existingNights : cfg.showNights ? stayNights : 1
    );
    dialogForm.elements.note.value = existingNote;
    var titleEl = $('#hrd-special-charge-title', modal);
    var subEl = $('#hrd-special-charge-sub', modal);
    var rateLabel = $('#hrd-special-charge-rate-label', modal);
    if (titleEl) titleEl.textContent = cfg.title;
    if (subEl) subEl.textContent = cfg.subtitle;
    if (rateLabel) rateLabel.innerHTML = cfg.rateLabel + ' <em>*</em>';
    var qtyField = modal.querySelector('[data-hrd-charge-qty-field]');
    var nightsField = modal.querySelector('[data-hrd-charge-nights-field]');
    if (qtyField) qtyField.hidden = !cfg.showQty;
    if (nightsField) nightsField.hidden = !cfg.showNights;
    syncSpecialChargeDialogAmount(dialogForm);
    modal._hrdChargeKind = kind;
    modal._hrdOpenedFromCheck = !!opts.fromCheck;
    modal.hidden = false;
    modal.removeAttribute('hidden');
    modal.setAttribute('aria-hidden', 'false');
    setTimeout(function () {
      var rateInput = dialogForm.elements.rate;
      if (rateInput) {
        rateInput.focus();
        rateInput.select();
      }
    }, 40);
  }

  function closeSpecialChargeModal(root, opts) {
    opts = opts || {};
    root = root || pageRoot();
    var modal = root && $('#hrd-special-charge-modal', root);
    if (!modal || modal.hidden) return;
    var kind = modal._hrdChargeKind || '';
    var cfg = SPECIAL_CHARGES[kind];
    var checkinForm = $('#hrd-checkin-form', root);
    var checkbox = cfg && checkinForm && $('#' + cfg.checkboxId, checkinForm);
    var openedFromCheck = !!modal._hrdOpenedFromCheck;
    modal.hidden = true;
    modal.setAttribute('hidden', '');
    modal.setAttribute('aria-hidden', 'true');
    modal._hrdOpenedFromCheck = false;
    if (opts.cancel && openedFromCheck && checkbox && cfg) {
      var amountName = cfg.fields.amount;
      var amount = Number((checkinForm.elements[amountName] && checkinForm.elements[amountName].value) || 0);
      if (!(amount > 0)) {
        checkbox.checked = false;
        clearSpecialCharge(checkinForm, kind);
      }
    }
    modal._hrdChargeKind = '';
  }

  function saveSpecialCharge(root) {
    var checkinForm = $('#hrd-checkin-form', root);
    var dialogForm = $('#hrd-special-charge-form', root);
    if (!checkinForm || !dialogForm) return;
    var kind = String(dialogForm.elements.chargeKind.value || '').trim();
    var cfg = SPECIAL_CHARGES[kind];
    if (!cfg) return;
    var qty = cfg.showQty ? Math.max(1, Number(dialogForm.elements.qty.value || 1)) : 1;
    var rate = Math.max(0, Number(dialogForm.elements.rate.value || 0));
    var nights = cfg.showNights ? Math.max(1, Number(dialogForm.elements.nights.value || 1)) : 1;
    if (!(rate > 0)) {
      showToast('Enter the charge amount.', true);
      return;
    }
    applySpecialCharge(checkinForm, kind, {
      qty: qty,
      rate: rate,
      nights: nights,
      note: dialogForm.elements.note.value || ''
    });
    var checkbox = $('#' + cfg.checkboxId, checkinForm);
    if (checkbox) checkbox.checked = true;
    var modal = $('#hrd-special-charge-modal', root);
    if (modal) modal._hrdOpenedFromCheck = false;
    closeSpecialChargeModal(root);
    showToast(cfg.toast);
    scheduleCheckinDraftSave(root, checkinForm);
  }

  /* Back-compat aliases used by older call sites. */
  function clearExtraBedCharge(form) {
    clearSpecialCharge(form, 'extraBed');
  }
  function openExtraBedModal(root, opts) {
    openSpecialChargeModal(root, 'extraBed', opts);
  }
  function closeExtraBedModal(root, opts) {
    closeSpecialChargeModal(root, opts);
  }
  function saveExtraBedCharge(root) {
    saveSpecialCharge(root);
  }

  var OTHER_CHARGE_SOURCE = 'checkin_special';

  function readOtherCustomCharges(form) {
    var el = form && ($('#hrd-ci-other-charges-json', form) || form.elements.otherCustomChargesJson);
    if (!el) return [];
    try {
      var raw = JSON.parse(el.value || '[]');
      return Array.isArray(raw) ? raw : [];
    } catch (err) {
      return [];
    }
  }

  function writeOtherCustomCharges(form, list) {
    var el = form && ($('#hrd-ci-other-charges-json', form) || form.elements.otherCustomChargesJson);
    if (!el) return;
    el.value = JSON.stringify(Array.isArray(list) ? list : []);
  }

  function otherCustomChargesTotal(form) {
    return readOtherCustomCharges(form).reduce(function (sum, row) {
      return sum + Math.max(0, Number(row.amount || 0));
    }, 0);
  }

  function otherChargeRowSummaryText(charge) {
    if (!charge) return '';
    var qty = Math.max(1, Number(charge.qty || 1));
    var rate = Math.max(0, Number(charge.rate || 0));
    var amount = Math.max(0, Number(charge.amount || qty * rate));
    return moneyText(amount);
  }

  function otherChargeRowHtml(row, idx) {
    var topic = String(row.topic || row.label || '').trim();
    var dateLabel = formatNightDateLabel(row.serviceDate);
    var qty = Math.max(1, Number(row.qty || 1));
    var rate = Math.max(0, Number(row.rate || 0));
    var amount = Math.max(0, Number(row.amount || qty * rate));
    return (
      '<div class="hrd-ci-nightly-row hrd-other-charge-row is-collapsed" role="listitem" data-other-charge-index="' +
      idx +
      '">' +
      '<button type="button" class="hrd-ci-nightly-date" data-other-charge-toggle aria-expanded="false">' +
      '<div class="hrd-ci-nightly-date-main">' +
      '<span class="hrd-ci-nightly-date-label hrd-other-charge-topic-label">' +
      escapeHtml(topic || 'Other') +
      '</span>' +
      '<strong>' +
      escapeHtml(dateLabel || '—') +
      '</strong>' +
      '</div>' +
      '<span class="hrd-ci-nightly-summary">' +
      escapeHtml(otherChargeRowSummaryText(row)) +
      '</span>' +
      '<span class="hrd-ci-nightly-lock">' +
      escapeHtml(qty + ' × ' + moneyText(rate)) +
      '</span>' +
      nightlyToggleChevHtml() +
      '</button>' +
      '<div class="hrd-ci-nightly-fields hrd-other-charge-fields">' +
      '<label class="hrd-field hrd-other-charge-detail-topic">' +
      '<span>Topic</span>' +
      '<span class="hrd-other-charge-readonly">' +
      escapeHtml(topic || '—') +
      '</span></label>' +
      '<label class="hrd-field"><span>Quantity</span><span class="hrd-other-charge-readonly">' +
      escapeHtml(String(qty)) +
      '</span></label>' +
      '<label class="hrd-field"><span>Price</span><span class="hrd-other-charge-readonly">' +
      escapeHtml(moneyText(rate)) +
      '</span></label>' +
      '<label class="hrd-field"><span>Total</span><span class="hrd-other-charge-readonly">' +
      escapeHtml(moneyText(amount)) +
      '</span></label>' +
      '<div class="hrd-other-charge-actions">' +
      '<button type="button" class="hrd-other-charge-action" data-hrd-other-edit="' +
      idx +
      '">Edit</button>' +
      '<button type="button" class="hrd-other-charge-action hrd-other-charge-action--danger" data-hrd-other-remove="' +
      idx +
      '">Remove</button>' +
      '</div></div></div>'
    );
  }

  function newOtherChargeId() {
    return 'fc' + String(Math.abs((Date.now() + Math.random() * 1e6) | 0)).slice(0, 8);
  }

  function folioLinesFromOtherCharges(list) {
    return (list || []).map(function (row) {
      var qty = Math.max(1, Number(row.qty || 1));
      var rate = Math.max(0, Number(row.rate || 0));
      var amount = Math.round(qty * rate * 100) / 100;
      return {
        id: row.id || newOtherChargeId(),
        kind: 'other',
        source: OTHER_CHARGE_SOURCE,
        label: String(row.topic || row.label || 'Other Charge').trim().slice(0, 120) || 'Other Charge',
        serviceDate: String(row.serviceDate || '').slice(0, 10),
        qty: qty,
        rate: rate,
        amount: amount,
        note: '',
        settled: false
      };
    }).filter(function (line) {
      return line.amount > 0 && line.label;
    });
  }

  function attachFolioChargesToStay(stay, form) {
    if (!stay || !form) return stay;
    var prev = (lastRoom && lastRoom.stay && lastRoom.stay.folioCharges) || [];
    var editing = form.getAttribute('data-edit-mode') === '1';
    var kept = editing
      ? prev.filter(function (line) {
          return String((line && line.source) || '') !== OTHER_CHARGE_SOURCE;
        })
      : [];
    stay.folioCharges = kept.concat(folioLinesFromOtherCharges(readOtherCustomCharges(form)));
    return stay;
  }

  function syncOtherChargeUi(form) {
    if (!form) return;
    var list = readOtherCustomCharges(form);
    var otherBox = $('#hrd-ci-other', form);
    var addBtn = $('#hrd-ci-other-add', form);
    var listEl = $('#hrd-ci-other-list', form);
    if (otherBox && list.length > 0) otherBox.checked = true;
    if (addBtn) addBtn.hidden = !(otherBox && otherBox.checked);
    if (listEl) listEl.hidden = !list.length;
  }

  function renderOtherChargeList(form) {
    if (!form) return;
    var listEl = $('#hrd-ci-other-list', form);
    if (!listEl) return;
    var list = readOtherCustomCharges(form);
    listEl.innerHTML = list.map(otherChargeRowHtml).join('');
    syncOtherChargeUi(form);
  }

  function clearOtherCustomCharges(form) {
    if (!form) return;
    writeOtherCustomCharges(form, []);
    var otherBox = $('#hrd-ci-other', form);
    if (otherBox) otherBox.checked = false;
    renderOtherChargeList(form);
    syncTotals(form);
  }

  function restoreOtherChargesFromFolio(form, stay) {
    if (!form) return;
    var folio = Array.isArray(stay && stay.folioCharges) ? stay.folioCharges : [];
    var others = folio
      .filter(function (line) {
        return String((line && line.source) || '') === OTHER_CHARGE_SOURCE;
      })
      .map(function (line) {
        var qty = Math.max(1, Number(line.qty || 1));
        var rate = Math.max(0, Number(line.rate || 0));
        var amount = Math.max(0, Number(line.amount || qty * rate));
        return {
          id: line.id || newOtherChargeId(),
          topic: String(line.label || '').trim(),
          serviceDate: String(line.serviceDate || '').slice(0, 10),
          qty: qty,
          rate: rate || (qty ? amount / qty : amount),
          amount: amount
        };
      });
    writeOtherCustomCharges(form, others);
    var otherBox = $('#hrd-ci-other', form);
    if (otherBox) otherBox.checked = others.length > 0;
    renderOtherChargeList(form);
  }

  function otherChargeStayWindow(form) {
    var checkIn =
      (form.checkInDate && form.checkInDate.value) ||
      (form.elements.checkInDate && form.elements.checkInDate.value) ||
      todayISO();
    var checkOut =
      (form.checkOutDate && form.checkOutDate.value) ||
      (form.elements.checkOutDate && form.elements.checkOutDate.value) ||
      addDaysISO(checkIn, 1);
    var min = checkIn || todayISO();
    var max = addDaysISO(checkOut, -1);
    if (max < min) max = min;
    return { min: min, max: max };
  }

  function syncOtherChargeDialogAmount(dialogForm) {
    if (!dialogForm) return;
    var qty = Math.max(1, Number(dialogForm.elements.qty.value || 1));
    var rate = Math.max(0, Number(dialogForm.elements.rate.value || 0));
    dialogForm.elements.amount.value = String(Math.round(qty * rate * 100) / 100);
  }

  function applyOtherChargeDateBounds(root, form) {
    var win = otherChargeStayWindow(form);
    var chip = root && $('#hrd-other-service-date-chip', root);
    if (!chip) return;
    chip.setAttribute('data-min-date', win.min);
    chip.setAttribute('data-max-date', win.max);
  }

  function openOtherChargeModal(root, opts) {
    opts = opts || {};
    root = root || pageRoot();
    var modal = root && $('#hrd-other-charge-modal', root);
    var checkinForm = root && $('#hrd-checkin-form', root);
    var dialogForm = root && $('#hrd-other-charge-form', root);
    if (!modal || !dialogForm || !checkinForm) return;
    var editIndex =
      opts.editIndex != null && opts.editIndex !== '' ? Number(opts.editIndex) : -1;
    var list = readOtherCustomCharges(checkinForm);
    var existing = editIndex >= 0 && list[editIndex] ? list[editIndex] : null;
    var win = otherChargeStayWindow(checkinForm);
    applyOtherChargeDateBounds(root, checkinForm);
    dialogForm.elements.editIndex.value = editIndex >= 0 ? String(editIndex) : '';
    dialogForm.elements.topic.value = existing ? existing.topic || existing.label || '' : '';
    dialogForm.elements.qty.value = String(existing ? existing.qty || 1 : 1);
    dialogForm.elements.rate.value = String(existing ? existing.rate || 0 : 0);
    var seedDate =
      (existing && existing.serviceDate) || win.min || todayISO();
    if (seedDate < win.min) seedDate = win.min;
    if (seedDate > win.max) seedDate = win.max;
    setFormDate(dialogForm, 'otherServiceDate', seedDate);
    syncOtherChargeDialogAmount(dialogForm);
    var titleEl = $('#hrd-other-charge-title', modal);
    if (titleEl) titleEl.textContent = existing ? 'Edit Other Charge' : 'Other Special Request';
    modal._hrdOpenedFromCheck = !!opts.fromCheck;
    modal.hidden = false;
    modal.removeAttribute('hidden');
    modal.setAttribute('aria-hidden', 'false');
    if (typeof global.initHotelDatePickers === 'function') {
      global.initHotelDatePickers(modal);
    }
    setTimeout(function () {
      var topicInput = dialogForm.elements.topic;
      if (topicInput) {
        topicInput.focus();
        if (typeof topicInput.select === 'function') topicInput.select();
      }
    }, 40);
  }

  function closeOtherChargeModal(root, opts) {
    opts = opts || {};
    root = root || pageRoot();
    var modal = root && $('#hrd-other-charge-modal', root);
    if (!modal || modal.hidden) return;
    var checkinForm = root && $('#hrd-checkin-form', root);
    var openedFromCheck = !!modal._hrdOpenedFromCheck;
    modal.hidden = true;
    modal.setAttribute('hidden', '');
    modal.setAttribute('aria-hidden', 'true');
    modal._hrdOpenedFromCheck = false;
    if (opts.cancel && openedFromCheck && checkinForm) {
      var list = readOtherCustomCharges(checkinForm);
      var otherBox = $('#hrd-ci-other', checkinForm);
      if (!list.length && otherBox) otherBox.checked = false;
      syncOtherChargeUi(checkinForm);
    }
  }

  function saveOtherChargeModal(root) {
    root = root || pageRoot();
    var checkinForm = root && $('#hrd-checkin-form', root);
    var dialogForm = root && $('#hrd-other-charge-form', root);
    if (!checkinForm || !dialogForm) return;
    var topic = String(dialogForm.elements.topic.value || '').trim();
    var serviceDate = String(
      (dialogForm.elements.otherServiceDate && dialogForm.elements.otherServiceDate.value) ||
        ''
    ).trim();
    var qty = Math.max(1, Number(dialogForm.elements.qty.value || 1));
    var rate = Math.max(0, Number(dialogForm.elements.rate.value || 0));
    var win = otherChargeStayWindow(checkinForm);
    if (!topic) {
      showToast('Enter a topic for this charge.', true);
      return;
    }
    if (!serviceDate) {
      showToast('Select a service date.', true);
      return;
    }
    if (serviceDate < win.min || serviceDate > win.max) {
      showToast('Service date must be within the stay.', true);
      return;
    }
    if (!(rate > 0)) {
      showToast('Enter a price greater than zero.', true);
      return;
    }
    var amount = Math.round(qty * rate * 100) / 100;
    var editIndexRaw = String(dialogForm.elements.editIndex.value || '').trim();
    var editIndex = editIndexRaw === '' ? -1 : Number(editIndexRaw);
    var list = readOtherCustomCharges(checkinForm).slice();
    var row = {
      id: editIndex >= 0 && list[editIndex] && list[editIndex].id ? list[editIndex].id : newOtherChargeId(),
      topic: topic,
      serviceDate: serviceDate,
      qty: qty,
      rate: rate,
      amount: amount
    };
    if (editIndex >= 0 && editIndex < list.length) list[editIndex] = row;
    else list.push(row);
    writeOtherCustomCharges(checkinForm, list);
    var otherBox = $('#hrd-ci-other', checkinForm);
    if (otherBox) otherBox.checked = true;
    renderOtherChargeList(checkinForm);
    closeOtherChargeModal(root);
    syncTotals(checkinForm);
    showToast(editIndex >= 0 ? 'Other charge updated.' : 'Other charge added.');
    scheduleCheckinDraftSave(root, checkinForm);
  }

  function resetListbox(fieldId, value, label) {
    if (typeof global.resetEpListbox === 'function') {
      global.resetEpListbox(fieldId, value, label);
      return;
    }
    var input = document.getElementById(fieldId);
    if (input) input.value = value;
  }

  function openNativeDatePicker(input) {
    if (!input || input.disabled || input.readOnly) return;
    try {
      if (typeof input.showPicker === 'function') {
        input.showPicker();
        return;
      }
    } catch (err) {}
    try {
      input.focus();
      input.click();
    } catch (err2) {}
  }

  function bindDateChipPickers(scope) {
    if (typeof global.initHotelDatePickers === 'function') {
      global.initHotelDatePickers(scope || document);
    }
    if (typeof global.initHotelTimePickers === 'function') {
      global.initHotelTimePickers(scope || document);
    }
    if (!scope) return;
    /* Legacy native time chips (if any remain outside hotel-time). */
    scope.querySelectorAll('.ep-time-chip').forEach(function (chip) {
      if (chip.getAttribute('data-hrd-date-bound') === '1') return;
      chip.setAttribute('data-hrd-date-bound', '1');
      var control = chip.querySelector('.se-filter-chip-control');
      var input = chip.querySelector('input.ep-date-input, input[type="time"]');
      if (!control || !input) return;
      control.addEventListener('click', function (event) {
        if (event.target === input) return;
        event.preventDefault();
        openNativeDatePicker(input);
      });
    });
  }

  function setFormDate(form, name, iso) {
    var input = form && form.elements ? form.elements[name] : null;
    if (!input) return;
    if (typeof global.setHotelDateValue === 'function') {
      global.setHotelDateValue(input, iso);
    } else {
      input.value = iso || '';
    }
  }

  function setFormTime(form, name, time) {
    var input = form && form.elements ? form.elements[name] : null;
    if (!input) return;
    if (typeof global.setHotelTimeValue === 'function') {
      global.setHotelTimeValue(input, time);
    } else {
      input.value = time || '';
    }
  }

  function syncAgencyBillingHint(form) {
    if (!form) return;
    var flags = formAgencyBillFlags(form);
    var nameInput = form.elements.agencyName;
    var agencyName = nameInput ? String(nameInput.value || '').trim() : '';
    var label = agencyName || 'Agency Name';
    form
      .querySelectorAll(
        '#hrd-ci-agency-room-billing-name, #hrd-reserve-agency-room-billing-name, #hrd-ci-agency-fb-billing-name, #hrd-reserve-agency-fb-billing-name'
      )
      .forEach(function (el) {
        el.textContent = label;
      });
    toggleAgencyBillingHint(
      form.querySelector(
        '#hrd-ci-agency-room-billing-hint, #hrd-reserve-agency-room-billing-hint'
      ),
      flags.room
    );
    toggleAgencyBillingHint(
      form.querySelector('#hrd-ci-agency-fb-billing-hint, #hrd-reserve-agency-fb-billing-hint'),
      flags.fb
    );
    if (nameInput) {
      nameInput.required = !!(flags.room || flags.fb);
    }
  }

  function bindAgencyBilling(form) {
    if (!form || form.getAttribute('data-agency-billing-bound') === '1') return;
    form.setAttribute('data-agency-billing-bound', '1');
    var nameInput = form.elements.agencyName;
    form.addEventListener('change', function (event) {
      var name = event.target && event.target.name;
      if (
        name !== 'agencyRoomBilling' &&
        name !== 'agencyFbBilling' &&
        name !== 'agencyBilling'
      ) {
        return;
      }
      syncAgencyBillingHint(form);
      var flags = formAgencyBillFlags(form);
      if ((flags.room || flags.fb) && nameInput && !String(nameInput.value || '').trim()) {
        nameInput.focus();
      }
    });
    if (nameInput) {
      nameInput.addEventListener('input', function () {
        syncAgencyBillingHint(form);
      });
    }
  }

  function setFormText(form, name, value) {
    var el = form && form.elements ? form.elements[name] : null;
    if (!el) return;
    el.value = value == null ? '' : String(value);
  }

  function setInvoiceLockedFormFields(form, stay) {
    if (!form) return;
    var locked = !!(stay && (stay.invoiceGenerated || stay.invoiceNumber));
    form.setAttribute('data-invoice-locked', locked ? '1' : '0');
    var names = [
      'roomRate',
      'nights',
      'advancePaid',
      'paymentReference',
      'extraBedQty',
      'extraBedRate',
      'extraBedNights',
      'extraBedNote',
      'earlyCheckinQty',
      'earlyCheckinRate',
      'earlyCheckinNights',
      'earlyCheckinNote',
      'lateCheckoutQty',
      'lateCheckoutRate',
      'lateCheckoutNights',
      'lateCheckoutNote'
    ];
    names.forEach(function (name) {
      var el = form.elements[name];
      if (!el) return;
      el.readOnly = locked;
    });
    if (form.elements.totalRate) form.elements.totalRate.readOnly = true;
    var paymentTrigger = document.getElementById('hrd-ci-payment-trigger');
    if (paymentTrigger) paymentTrigger.disabled = locked;
    $all('[data-merge-room-rate], [data-nightly-room-rate]', form).forEach(function (el) {
      el.disabled = locked || el.closest('.hrd-ci-nightly-row.is-locked');
      el.readOnly = locked || el.closest('.hrd-ci-nightly-row.is-locked');
    });
    $all('.hrd-ci-rate-plan-listbox .se-filter-chip-trigger', form).forEach(function (el) {
      var nightLocked = el.closest('.hrd-ci-nightly-row.is-locked');
      el.disabled = locked || !!nightLocked;
      var lb = el.closest('.hrd-ci-rate-plan-listbox');
      if (lb) {
        lb.classList.toggle('is-disabled', locked || !!nightLocked);
      }
    });
    $all(
      '#hrd-ci-early-checkin, #hrd-ci-late-checkout, #hrd-ci-extra-bed, #hrd-ci-early-checkin-edit, #hrd-ci-late-checkout-edit, #hrd-ci-extra-bed-edit',
      form
    ).forEach(function (el) {
      el.disabled = locked;
    });
    if (!locked) applyNightlyRowLocks(form);
  }

  var CHECKIN_DRAFT_PREFIX = 'hrd-checkin-draft:';
  var checkinDraftTimer = null;
  var checkinDraftApplying = false;
  var RATE_PLAN_LABELS = {
    EP: 'EP — Room Only',
    CP: 'CP — Breakfast',
    MAP: 'MAP — Breakfast + Dinner',
    AP: 'AP — All Meals'
  };

  global.hrdCiMergeRatePlanChanged = function () {
    var root = pageRoot();
    var form = root && $('#hrd-checkin-form', root);
    if (!form) return;
    $all('.hrd-ci-rate-plan-listbox', form).forEach(function (lb) {
      var hidden = lb.querySelector('[data-nightly-rate-plan], [data-merge-rate-plan]');
      var plan = String((hidden && hidden.value) || '').trim().toUpperCase();
      if (RATE_PLAN_LABELS[plan]) lb.classList.remove('is-invalid');
    });
    syncTotals(form);
    scheduleCheckinDraftSave(root, form);
  };

  function countryNameFromMobileOption(listboxRoot, option) {
    if (option && option.getAttribute) {
      var fromOption = String(
        option.getAttribute('data-country') || ''
      ).replace(/\s+/g, ' ').trim();
      if (fromOption) return fromOption;
      var title = option.querySelector && option.querySelector('.ep-listbox-option-title');
      fromOption = String((title && title.textContent) || '').replace(/\s+/g, ' ').trim();
      if (fromOption) return fromOption;
    }
    var list =
      (listboxRoot && listboxRoot.__epPortaledList) ||
      document.getElementById('hrd-ci-mobile-country-list');
    if (!list || !list.querySelector) return '';
    var selected =
      list.querySelector('.se-filter-listbox-option.is-selected') ||
      list.querySelector('.se-filter-listbox-option[aria-selected="true"]');
    if (!selected) return '';
    return String(
      selected.getAttribute('data-country') ||
      ((selected.querySelector('.ep-listbox-option-title') || {}).textContent) ||
      ''
    ).replace(/\s+/g, ' ').trim();
  }

  function nationalityFromCountryName(countryName) {
    var name = String(countryName || '').trim();
    if (!name) return '';
    if (/^india$/i.test(name) || /^indian$/i.test(name)) return 'Indian';
    return name;
  }

  function syncNationalityFromMobileCountry(listboxRoot, option) {
    var countryName = countryNameFromMobileOption(listboxRoot, option);
    if (!countryName) return;
    var nationality = nationalityFromCountryName(countryName);
    resetListbox('hrd-ci-nationality', nationality, nationality);
    resetListbox('hrd-ci-country', countryName, countryName);
  }

  global.hrdCiMobileCountryChanged = function (listboxRoot, _value, _label, option) {
    syncNationalityFromMobileCountry(listboxRoot, option);
    var root = pageRoot();
    var form = root && $('#hrd-checkin-form', root);
    if (form) scheduleCheckinDraftSave(root, form);
  };

  function checkinDraftKey(root) {
    var roomId = (root && root.getAttribute('data-room-id')) || '';
    return roomId ? CHECKIN_DRAFT_PREFIX + roomId : '';
  }

  function listboxDisplayLabel(fieldId, value, fallback) {
    var list = document.getElementById(fieldId + '-list');
    if (list && value != null && value !== '') {
      var options = list.querySelectorAll('.se-filter-listbox-option');
      for (var i = 0; i < options.length; i += 1) {
        if (String(options[i].getAttribute('data-value') || '') === String(value)) {
          return (
            options[i].getAttribute('data-label') ||
            options[i].textContent ||
            fallback ||
            value
          );
        }
      }
    }
    return fallback || value || '';
  }

  function resetListboxValue(fieldId, value, fallbackLabel) {
    var next = value == null ? '' : String(value);
    var label = next
      ? listboxDisplayLabel(fieldId, next, fallbackLabel || next)
      : fallbackLabel || 'Select';
    resetListbox(fieldId, next, label);
  }

  function readCheckinDraft(root) {
    var key = checkinDraftKey(root);
    if (!key) return null;
    try {
      var raw = localStorage.getItem(key);
      if (!raw) {
        /* Migrate drafts saved before localStorage switch. */
        raw = sessionStorage.getItem(key);
        if (raw) {
          localStorage.setItem(key, raw);
          sessionStorage.removeItem(key);
        }
      }
      if (!raw) return null;
      var data = JSON.parse(raw);
      return data && typeof data === 'object' ? data : null;
    } catch (err) {
      return null;
    }
  }

  function checkinDraftMetaFromForm(form) {
    if (!form) return { edit: false, idOnly: false };
    return {
      edit: form.getAttribute('data-edit-mode') === '1',
      idOnly: form.getAttribute('data-id-only') === '1'
    };
  }

  function mergeCheckinDraftMeta(meta, form) {
    meta = meta || {};
    var fromForm = checkinDraftMetaFromForm(form);
    return {
      open:
        meta.open != null
          ? !!meta.open
          : document.body.classList.contains('hrd-checkin-open'),
      edit: meta.edit != null ? !!meta.edit : fromForm.edit,
      idOnly: meta.idOnly != null ? !!meta.idOnly : fromForm.idOnly
    };
  }

  function writeCheckinDraft(root, stay, meta, form) {
    var key = checkinDraftKey(root);
    if (!key || !stay) return;
    var merged = mergeCheckinDraftMeta(meta, form);
    try {
      localStorage.setItem(
        key,
        JSON.stringify({
          savedAt: Date.now(),
          open: merged.open,
          edit: merged.edit,
          idOnly: merged.idOnly,
          stay: stay
        })
      );
    } catch (err) {}
  }

  function clearCheckinDraft(root) {
    var key = checkinDraftKey(root);
    if (!key) return;
    try {
      localStorage.removeItem(key);
    } catch (err) {}
    try {
      sessionStorage.removeItem(key);
    } catch (err) {}
  }

  function scheduleCheckinDraftSave(root, form) {
    if (checkinDraftApplying) return;
    root = root || pageRoot();
    form = form || (root && $('#hrd-checkin-form', root));
    if (!root || !form) return;
    if (document.body.classList.contains('hrd-checkin-open') === false) return;
    if (checkinDraftTimer) clearTimeout(checkinDraftTimer);
    checkinDraftTimer = setTimeout(function () {
      checkinDraftTimer = null;
      if (checkinDraftApplying) return;
      try {
        writeCheckinDraft(
          root,
          attachFolioChargesToStay(collectStay(form), form),
          { open: true },
          form
        );
      } catch (err) {}
    }, 280);
  }

  function applyStayDraft(form, stay) {
    if (!form || !stay) return;
    checkinDraftApplying = true;
    try {
      var names = resolveGuestPersonalNames(stay);
      setFormText(form, 'firstName', names.firstName);
      setFormText(form, 'lastName', names.lastName);
      setFormText(form, 'mobile', stay.mobile || stay.phone || '');
      setFormText(form, 'email', stay.email || '');
      setFormText(form, 'address', stay.address || '');
      setFormText(form, 'city', stay.city || '');
      setFormText(form, 'state', stay.state || '');
      setFormText(form, 'pin', stay.pin || '');
      setFormText(form, 'agencyName', stay.agencyName || '');
      setFormText(form, 'agencyGst', stay.agencyGst || '');
      setFormText(form, 'agencyAddress', stay.agencyAddress || '');
      setFormText(form, 'nights', stay.nights != null ? stay.nights : '1');
      setFormText(form, 'advancePaid', stay.advancePaid != null ? stay.advancePaid : '0');
      setFormText(form, 'paymentReference', stay.paymentReference || '');
      setFormText(
        form,
        'additionalRequests',
        stay.additionalRequests ||
          stay.additional_requests ||
          stay.specialNotes ||
          stay.special_notes ||
          stay.notes ||
          ''
      );
      setFormAgencyBillFlags(form, stay);

      resetListboxValue(
        'hrd-ci-title',
        names.title || stay.title || '',
        names.title || stay.title || 'Select'
      );
      resetListboxValue('hrd-ci-gender', stay.gender || '', 'Select');
      resetListboxValue(
        'hrd-ci-nationality',
        stay.nationality || 'Indian',
        stay.nationality || 'Indian'
      );
      resetListboxValue(
        'hrd-ci-mobile-country',
        stay.mobileCountry || '+91',
        stay.mobileCountry || '+91'
      );
      resetListboxValue(
        'hrd-ci-country',
        stay.country || 'India',
        stay.country || 'India'
      );
      resetListboxValue('hrd-ci-purpose', stay.purposeOfVisit || '', 'Select');
      resetListboxValue(
        'hrd-ci-vip',
        stay.vipStatus || 'Regular',
        stay.vipStatus || 'Regular'
      );
      resetListboxValue(
        'hrd-ci-returning',
        stay.returningGuest || 'No',
        stay.returningGuest || 'No'
      );
      resetListboxValue('hrd-ci-id-type', stay.idType || '', 'Select');
      resetListboxValue(
        'hrd-ci-adults',
        String(stay.adults != null ? stay.adults : 1),
        String(stay.adults != null ? stay.adults : 1)
      );
      resetListboxValue(
        'hrd-ci-children',
        String(stay.children != null ? stay.children : 0),
        String(stay.children != null ? stay.children : 0)
      );
      resetListboxValue('hrd-ci-payment', stay.paymentMethod || '', 'Select');

      setFormDate(form, 'dateOfBirth', stay.dateOfBirth || '');
      setFormDate(form, 'bookingDate', stay.bookingDate || '');
      setFormDate(form, 'checkInDate', stay.checkInDate || '');
      setFormDate(form, 'checkOutDate', stay.checkOutDate || '');
      setFormTime(form, 'checkInTime', stay.checkInTime || '');
      setFormTime(form, 'checkOutTime', stay.checkOutTime || stay.check_out_time || '');

      buildCheckinRateRooms(pageRoot(), form, {
        stay: stay
      });

      syncCustomerNameFromPersonal(form);
      if (stayDocumentUrl(stay) || stay.idDocumentPath || stay.idDocumentName) {
        setIdDocumentUi(form, {
          urlPath: stayDocumentUrl(stay),
          path: stay.idDocumentPath,
          url: stay.idDocumentPath,
          mime: stay.idDocumentMime || '',
          displayName: idDocumentDisplayLabel(stay, stay.idType, stay.idDocumentName),
          originalName: stay.idDocumentName || '',
          storedName:
            storedIdDocumentName(stay.idDocumentStoredName) ||
            storedIdDocumentName(stay.idDocumentName) ||
            stay.idDocumentName ||
            ''
        });
      } else {
        clearIdDocumentFields(form);
      }

      clearExtraGuests(form);
      (stay.additionalGuests || []).forEach(function (guest) {
        addExtraGuestRow(form, guest);
      });

      var special = Array.isArray(stay.specialRequests) ? stay.specialRequests : [];
      $all('input[name="specialRequests"]', form).forEach(function (box) {
        box.checked = special.indexOf(box.value) !== -1;
      });

      clearAllSpecialCharges(form);
      if (stay.earlyCheckinAmount || stay.earlyCheckinRate) {
        applySpecialCharge(form, 'earlyCheckin', {
          qty: stay.earlyCheckinQty || 1,
          rate: stay.earlyCheckinRate || 0,
          nights: stay.earlyCheckinNights || 1,
          note: stay.earlyCheckinNote || ''
        });
      }
      if (stay.lateCheckoutAmount || stay.lateCheckoutRate) {
        applySpecialCharge(form, 'lateCheckout', {
          qty: stay.lateCheckoutQty || 1,
          rate: stay.lateCheckoutRate || 0,
          nights: stay.lateCheckoutNights || 1,
          note: stay.lateCheckoutNote || ''
        });
      }
      if (stay.extraBedAmount || stay.extraBedRate) {
        applySpecialCharge(form, 'extraBed', {
          qty: stay.extraBedQty || 1,
          rate: stay.extraBedRate || 0,
          nights: stay.extraBedNights || 1,
          note: stay.extraBedNote || ''
        });
      }

      restoreOtherChargesFromFolio(form, stay);

      syncAgencyBillingHint(form);
      syncTotals(form);
      syncCheckinReservationIdField(form, stay);
      scheduleFormFieldAutosize(form);
    } finally {
      checkinDraftApplying = false;
    }
  }

  function syncCustomerNameFromPersonal(form) {
    if (!form || !form.elements.idNumber) return;
    var first = form.elements.firstName
      ? String(form.elements.firstName.value || '').trim()
      : '';
    var last = form.elements.lastName
      ? String(form.elements.lastName.value || '').trim()
      : '';
    form.elements.idNumber.value = [first, last].filter(Boolean).join(' ');
    autosizeFormField(form.elements.idNumber);
  }

  var EXTRA_GUEST_ID_TYPES = [
    { value: '', label: 'Select' },
    { value: 'Aadhaar', label: 'Aadhaar' },
    { value: 'Passport', label: 'Passport' },
    { value: 'Driving License', label: 'Driving License' },
    { value: 'Voter ID', label: 'Voter ID' },
    { value: 'Other', label: 'Other' }
  ];
  var extraGuestIdSeq = 0;

  function buildExtraGuestIdTypeListbox(index, selected) {
    extraGuestIdSeq += 1;
    var fid = 'hrd-ci-guest-' + extraGuestIdSeq + '-id-type';
    var selectedValue = String(selected || '');
    var display = 'Select';
    EXTRA_GUEST_ID_TYPES.forEach(function (opt) {
      if (opt.value === selectedValue) display = opt.label;
    });
    var hasValue = !!selectedValue;
    var wrap = document.createElement('div');
    wrap.className = 'hrd-id-type-listbox';
    var optionsHtml = EXTRA_GUEST_ID_TYPES.map(function (opt) {
      var isSel = opt.value === selectedValue;
      return (
        '<button type="button" class="se-filter-listbox-option' +
        (isSel ? ' is-selected' : '') +
        '" role="option" data-value="' +
        opt.value +
        '" data-name="' +
        opt.label.toLowerCase() +
        '" data-label="' +
        opt.label +
        '" aria-selected="' +
        (isSel ? 'true' : 'false') +
        '">' +
        opt.label +
        '</button>'
      );
    }).join('');
    wrap.innerHTML =
      '<div class="se-filter-chip se-filter-chip--payment se-filter-chip--listbox ep-form-listbox ep-header-field-listbox hrd-form-listbox" data-se-listbox id="' +
      fid +
      '-listbox">' +
      '<label class="se-filter-chip-label" id="' +
      fid +
      '-label" for="' +
      fid +
      '-trigger">ID Type</label>' +
      '<div class="se-filter-chip-control">' +
      '<span class="se-filter-chip-icon" aria-hidden="true">' +
      '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="2" y="5" width="20" height="14" rx="2"/><path d="M2 10h20"/></svg>' +
      '</span>' +
      '<input type="hidden" id="' +
      fid +
      '" data-extra-guest-id-type="1" value="' +
      selectedValue.replace(/"/g, '&quot;') +
      '" aria-label="Guest ' +
      index +
      ' ID type">' +
      '<button type="button" class="se-filter-chip-trigger" id="' +
      fid +
      '-trigger" aria-haspopup="listbox" aria-expanded="false" aria-controls="' +
      fid +
      '-list" aria-labelledby="' +
      fid +
      '-label ' +
      fid +
      '-value">' +
      '<span class="se-filter-chip-value' +
      (hasValue ? '' : ' is-placeholder') +
      '" id="' +
      fid +
      '-value">' +
      display +
      '</span>' +
      '</button>' +
      '<span class="se-filter-chip-chev" aria-hidden="true">' +
      '<svg viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg>' +
      '</span>' +
      '</div>' +
      '<div class="se-filter-listbox" id="' +
      fid +
      '-list" role="listbox" aria-labelledby="' +
      fid +
      '-label" hidden>' +
      '<div class="ep-listbox-options">' +
      optionsHtml +
      '</div>' +
      '</div>' +
      '</div>';
    return wrap;
  }

  function extraGuestsHost(form) {
    return form && (form.querySelector('#hrd-ci-extra-guests') || null);
  }

  function clearExtraGuests(form) {
    var host = extraGuestsHost(form);
    if (host) host.innerHTML = '';
    syncAdultsFromGuests(form);
  }

  function syncAdultsFromGuests(form) {
    if (!form) return;
    var host = extraGuestsHost(form);
    var extraCount = host ? host.querySelectorAll('[data-extra-guest]').length : 0;
    var total = Math.max(1, 1 + extraCount);
    resetListbox('hrd-ci-adults', String(total), String(total));
    if (form.elements.adults) form.elements.adults.value = String(total);
  }

  function collectExtraGuests(form) {
    var host = extraGuestsHost(form);
    if (!host) return [];
    var rows = Array.from(host.querySelectorAll('[data-extra-guest]'));
    var guests = [];
    rows.forEach(function (row) {
      var nameInput = row.querySelector('[data-extra-guest-name]');
      var typeSelect = row.querySelector('[data-extra-guest-id-type]');
      var pathInput = row.querySelector('[data-extra-guest-doc-path]');
      var mimeInput = row.querySelector('[data-extra-guest-doc-mime]');
      var storedInput = row.querySelector('[data-extra-guest-doc-stored]');
      var nameEl = row.querySelector('[data-extra-guest-doc-name]');
      var name = nameInput ? String(nameInput.value || '').trim() : '';
      var idType = typeSelect ? String(typeSelect.value || '').trim() : '';
      var path = pathInput ? String(pathInput.value || '').trim() : '';
      var mime = mimeInput ? String(mimeInput.value || '').trim() : '';
      var stored = storedInput ? String(storedInput.value || '').trim() : '';
      var displayName = nameEl ? String(nameEl.textContent || '').trim() : '';
      var label = idDocumentDisplayLabel(name, idType, displayName || stored);
      var docPath =
        idDocumentViewUrl(path) ||
        idDocumentViewUrl(stored) ||
        idDocumentViewUrl(displayName);
      if (!name && !idType && !docPath && !displayName) return;
      guests.push({
        name: name,
        idType: idType,
        idDocumentName: label || displayName || stored,
        idDocumentPath: docPath,
        idDocumentStoredName: storedIdDocumentName(stored) || storedIdDocumentName(docPath) || '',
        idDocumentMime: mime
      });
    });
    return guests;
  }

  function syncExtraGuestViewBtn(row, hasDoc) {
    if (!row) return;
    var viewBtn = row.querySelector('[data-hrd-id-view]');
    if (!viewBtn) return;
    var ready = !!hasDoc;
    viewBtn.hidden = !ready;
    viewBtn.disabled = !ready;
    viewBtn.classList.toggle('is-ready', ready);
  }

  function setExtraGuestDocumentUi(row, doc) {
    if (!row || !doc) return;
    var pathInput = row.querySelector('[data-extra-guest-doc-path]');
    var mimeInput = row.querySelector('[data-extra-guest-doc-mime]');
    var storedInput = row.querySelector('[data-extra-guest-doc-stored]');
    var nameEl = row.querySelector('[data-extra-guest-doc-name]');
    var uploadBtn = row.querySelector('[data-hrd-upload]');
    var meta = extraGuestIdMeta(row);
    var displayName =
      idDocumentDisplayLabel(meta.name, meta.idType, doc.displayName || doc.originalName || '') ||
      doc.displayName ||
      doc.originalName ||
      '';
    if (pathInput) pathInput.value = doc.urlPath || doc.path || doc.url || '';
    if (mimeInput) mimeInput.value = doc.mime || '';
    if (storedInput) storedInput.value = doc.storedName || '';
    if (nameEl) {
      nameEl.textContent = displayName;
      nameEl.hidden = !displayName;
    }
    if (uploadBtn) {
      uploadBtn.classList.add('is-filled');
      uploadBtn.title = displayName
        ? 'Uploaded: ' + displayName
        : 'Upload ID (PDF, or photos combined into one PDF)';
    }
    syncExtraGuestViewBtn(row, !!(pathInput && pathInput.value));
  }

  function idUploadFileExt(name) {
    var text = String(name || '').toLowerCase();
    var dot = text.lastIndexOf('.');
    return dot >= 0 ? text.slice(dot) : '';
  }

  function classifyIdUploadFiles(fileList) {
    var files = Array.prototype.slice.call(fileList || []);
    var pdfs = [];
    var images = [];
    var imageExt = {
      '.jpg': 1,
      '.jpeg': 1,
      '.png': 1,
      '.heic': 1,
      '.heif': 1,
      '.webp': 1
    };
    files.forEach(function (file) {
      if (!file) return;
      var ext = idUploadFileExt(file.name);
      var mime = String(file.type || '').toLowerCase();
      if (ext === '.pdf' || mime === 'application/pdf') pdfs.push(file);
      else if (imageExt[ext] || mime.indexOf('image/') === 0) images.push(file);
      else throw new Error('Only JPG, JPEG, PNG, HEIC, and PDF files are allowed.');
    });
    if (!pdfs.length && !images.length) {
      throw new Error('Choose an ID document to upload.');
    }
    if (pdfs.length && images.length) {
      throw new Error('Upload either one PDF or photo files, not both.');
    }
    if (pdfs.length > 1) {
      throw new Error('Upload a single PDF, or photo files to combine into one PDF.');
    }
    if (images.length > 8) {
      throw new Error('You can combine at most 8 photos into one ID PDF.');
    }
    return { files: pdfs.length ? pdfs : images, pdfs: pdfs, images: images };
  }

  function idUploadSuccessMessage(doc, imageCount) {
    var pages = Number((doc && doc.pageCount) || imageCount || 1);
    if (pages > 1) return pages + ' photos combined into one PDF.';
    return 'ID saved as PDF.';
  }

  function uploadExtraGuestDocument(root, row, files) {
    files = Array.prototype.slice.call(files || []);
    if (!root || !row || !files.length) {
      return Promise.reject(new Error('missing file'));
    }
    var classified;
    try {
      classified = classifyIdUploadFiles(files);
    } catch (err) {
      showToast(err.message || 'Could not upload ID document.', true);
      return Promise.reject(err);
    }
    var api =
      (root.getAttribute('data-id-document-upload-api') || '').trim() ||
      '/hotel/api/id-documents';
    var uploadBtn = row.querySelector('[data-hrd-upload]');
    if (uploadBtn) {
      uploadBtn.classList.add('is-busy');
      uploadBtn.disabled = true;
    }
    var extraMeta = extraGuestIdMeta(row);
    var body = new FormData();
    classified.files.forEach(function (file) {
      body.append('file', file, file.name);
    });
    body.append('guestName', extraMeta.name);
    body.append('idType', extraMeta.idType);
    return fetch(api, {
      method: 'POST',
      credentials: 'same-origin',
      headers: apiHeaders(),
      body: body
    })
      .then(function (resp) {
        return resp.json().then(function (data) {
          return { ok: resp.ok, data: data };
        });
      })
      .then(function (result) {
        if (!result.ok || !result.data || !result.data.ok || !result.data.document) {
          throw new Error(
            (result.data && result.data.error) || 'Upload failed.'
          );
        }
        var extraLabel = idDocumentDisplayLabel(
          extraMeta.name,
          extraMeta.idType,
          result.data.document.displayName
        );
        if (extraLabel) result.data.document.displayName = extraLabel;
        setExtraGuestDocumentUi(row, result.data.document);
        showToast(idUploadSuccessMessage(result.data.document, classified.images.length));
        if (lastRoom && lastRoom.stay) {
          var form = $('#hrd-checkin-form', root);
          if (form) lastRoom.stay.additionalGuests = collectExtraGuests(form);
          paintGuestPanels(pageRoot() || root, lastRoom);
          persistOccupiedStay(pageRoot() || root);
        }
        return result.data.document;
      })
      .catch(function (err) {
        showToast(err.message || 'Could not upload ID document.', true);
        throw err;
      })
      .finally(function () {
        if (uploadBtn) {
          uploadBtn.classList.remove('is-busy');
          uploadBtn.disabled = false;
        }
      });
  }

  function addExtraGuestRow(form, guest, opts) {
    var host = extraGuestsHost(form);
    if (!host) return;
    guest = guest || {};
    opts = opts || {};
    var index = host.querySelectorAll('[data-extra-guest]').length + 2;
    var row = document.createElement('div');
    row.className = 'hrd-form-grid hrd-form-grid--2 hrd-guest-line';
    row.setAttribute('data-extra-guest', '1');

    var nameField = document.createElement('div');
    nameField.className = 'hrd-field hrd-field--customer-name';
    nameField.innerHTML = '<span>Customer Name</span>';
    var nameInput = document.createElement('input');
    nameInput.type = 'text';
    nameInput.placeholder = 'Customer name';
    nameInput.autocomplete = 'name';
    nameInput.setAttribute('data-extra-guest-name', '1');
    nameInput.setAttribute('aria-label', 'Guest ' + index + ' name');
    nameInput.value = guest.name || '';
    nameField.appendChild(nameInput);

    var typeWrap = document.createElement('div');
    typeWrap.className = 'hrd-field hrd-field--id-type-actions';
    var typeRow = document.createElement('div');
    typeRow.className = 'hrd-id-type-row';

    var typeListbox = buildExtraGuestIdTypeListbox(index, guest.idType || '');

    var actions = document.createElement('div');
    actions.className = 'hrd-id-type-actions';
    var fileInput = document.createElement('input');
    fileInput.type = 'file';
    fileInput.className = 'hrd-id-upload-input';
    fileInput.accept =
      '.jpg,.jpeg,.png,.heic,.heif,.webp,.pdf,image/jpeg,image/png,image/heic,image/heif,image/webp,application/pdf';
    fileInput.multiple = true;
    fileInput.hidden = true;
    fileInput.setAttribute('data-extra-guest-file', '1');

    var pathInput = document.createElement('input');
    pathInput.type = 'hidden';
    pathInput.setAttribute('data-extra-guest-doc-path', '1');
    pathInput.value = stayDocumentUrl(guest) || guest.idDocumentPath || '';
    var mimeInput = document.createElement('input');
    mimeInput.type = 'hidden';
    mimeInput.setAttribute('data-extra-guest-doc-mime', '1');
    mimeInput.value = guest.idDocumentMime || '';
    var storedInput = document.createElement('input');
    storedInput.type = 'hidden';
    storedInput.setAttribute('data-extra-guest-doc-stored', '1');
    storedInput.value = guest.idDocumentStoredName || '';

    var uploadBtn = document.createElement('button');
    uploadBtn.type = 'button';
    uploadBtn.className = 'hrd-id-upload-btn';
    uploadBtn.setAttribute('data-hrd-upload', '1');
    uploadBtn.title = 'Upload ID (PDF, or photos combined into one PDF)';
    uploadBtn.setAttribute('aria-label', 'Upload guest ' + index + ' ID document');
    uploadBtn.innerHTML =
      '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 16V6"/><path d="m8 10 4-4 4 4"/><path d="M4 18h16"/></svg>';

    var viewBtn = document.createElement('button');
    viewBtn.type = 'button';
    viewBtn.className = 'hrd-id-view-btn';
    viewBtn.setAttribute('data-hrd-id-view', '1');
    viewBtn.title = 'View uploaded ID document';
    viewBtn.setAttribute('aria-label', 'View guest ' + index + ' ID document');
    viewBtn.disabled = true;
    viewBtn.hidden = true;
    viewBtn.innerHTML =
      '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7S1 12 1 12z"/><circle cx="12" cy="12" r="3"/></svg>';

    var removeBtn = document.createElement('button');
    removeBtn.type = 'button';
    removeBtn.className = 'hrd-extra-guest-remove';
    removeBtn.setAttribute('data-hrd-remove-guest', '1');
    removeBtn.setAttribute('aria-label', 'Remove guest ' + index);
    removeBtn.title = 'Remove guest';
    removeBtn.innerHTML =
      '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18 6 6 18M6 6l12 12"/></svg>';

    actions.appendChild(fileInput);
    actions.appendChild(pathInput);
    actions.appendChild(mimeInput);
    actions.appendChild(storedInput);
    actions.appendChild(uploadBtn);
    actions.appendChild(viewBtn);
    actions.appendChild(removeBtn);

    typeRow.appendChild(typeListbox);
    typeRow.appendChild(actions);
    typeWrap.appendChild(typeRow);
    var nameEl = document.createElement('span');
    nameEl.className = 'hrd-id-upload-name hrd-upload-text';
    nameEl.setAttribute('data-extra-guest-doc-name', '1');
    nameEl.hidden = true;
    if (guest.idDocumentName || guest.idDocumentPath) {
      nameEl.textContent = idDocumentDisplayLabel(
        guest.name,
        guest.idType,
        guest.idDocumentName
      );
      nameEl.hidden = !nameEl.textContent;
    }
    typeWrap.appendChild(nameEl);

    row.appendChild(nameField);
    row.appendChild(typeWrap);
    host.appendChild(row);

    if (typeof global.initEpListboxes === 'function') {
      global.initEpListboxes();
    }

    if (stayDocumentUrl(guest) || guest.idDocumentPath || guest.idDocumentName) {
      syncExtraGuestViewBtn(row, true);
      if (uploadBtn) uploadBtn.classList.add('is-filled');
    }

    syncAdultsFromGuests(form);
    scheduleCheckinDraftSave(pageRoot(), form);
    scheduleFormFieldAutosize(form);
    if (!(opts && opts.focus === false)) {
      setTimeout(function () {
        nameInput.focus();
      }, 20);
    }
  }

  function renumberExtraGuests(form) {
    var host = extraGuestsHost(form);
    if (!host) return;
    Array.from(host.querySelectorAll('[data-extra-guest]')).forEach(function (row, i) {
      var n = i + 2;
      var nameInput = row.querySelector('[data-extra-guest-name]');
      if (nameInput) nameInput.setAttribute('aria-label', 'Guest ' + n + ' name');
      var typeInput = row.querySelector('[data-extra-guest-id-type]');
      if (typeInput) typeInput.setAttribute('aria-label', 'Guest ' + n + ' ID type');
      var removeBtn = row.querySelector('[data-hrd-remove-guest]');
      if (removeBtn) removeBtn.setAttribute('aria-label', 'Remove guest ' + n);
    });
  }

  function fieldAutosizeSizer() {
    var sizer = document.getElementById('hrd-field-autosize-sizer');
    if (sizer) return sizer;
    sizer = document.createElement('span');
    sizer.id = 'hrd-field-autosize-sizer';
    sizer.className = 'hrd-field-autosize-sizer';
    sizer.setAttribute('aria-hidden', 'true');
    document.body.appendChild(sizer);
    return sizer;
  }

  function autosizeFormField(input) {
    if (!input || input.disabled) return;
    var type = String(input.type || 'text').toLowerCase();
    if (
      type === 'hidden' ||
      type === 'file' ||
      type === 'checkbox' ||
      type === 'radio' ||
      type === 'number' ||
      type === 'date' ||
      type === 'time' ||
      type === 'button' ||
      type === 'submit'
    ) {
      return;
    }
    if (input.closest('.ep-form-listbox, .hotel-date, .ep-time-chip, .hrd-input-affix')) {
      return;
    }
    var field = input.closest('.hrd-field');
    if (!field) return;
    input.style.width = '';
    if (input.tagName === 'TEXTAREA') {
      input.style.height = 'auto';
      input.style.height = Math.max(76, input.scrollHeight) + 'px';
      return;
    }
    if (field.classList.contains('hrd-field--customer-mobile')) return;
    if (input.closest('#hrd-ci-id-proof .hrd-guest-line')) {
      input.style.width = '';
      field.classList.remove('hrd-field--grow');
      return;
    }
    if (
      type !== 'text' &&
      type !== 'email' &&
      type !== 'tel' &&
      type !== 'search' &&
      type !== ''
    ) {
      return;
    }
    var value = String(input.value || '').trim();
    if (!field.classList.contains('hrd-field--grow') || !field._hrdCellW) {
      field._hrdCellW = input.clientWidth;
    }
    var cellW = field._hrdCellW || input.clientWidth;
    if (!value || !cellW) {
      field.classList.remove('hrd-field--grow');
      return;
    }
    var sizer = fieldAutosizeSizer();
    var cs = window.getComputedStyle(input);
    sizer.style.font = cs.font;
    sizer.style.letterSpacing = cs.letterSpacing;
    sizer.style.textTransform = cs.textTransform;
    sizer.textContent = input.value;
    var pad =
      (parseFloat(cs.paddingLeft) || 0) + (parseFloat(cs.paddingRight) || 0);
    var border =
      (parseFloat(cs.borderLeftWidth) || 0) +
      (parseFloat(cs.borderRightWidth) || 0);
    var need = Math.ceil(sizer.getBoundingClientRect().width) + pad + border + 8;
    field.classList.toggle('hrd-field--grow', need > cellW + 4);
  }

  function refreshFormFieldAutosize(form) {
    if (!form) return;
    Array.prototype.forEach.call(
      form.querySelectorAll('.hrd-field input, .hrd-field textarea'),
      autosizeFormField
    );
  }

  function scheduleFormFieldAutosize(form) {
    if (!form) return;
    var run = function () {
      refreshFormFieldAutosize(form);
    };
    if (typeof requestAnimationFrame === 'function') {
      requestAnimationFrame(run);
    } else {
      setTimeout(run, 0);
    }
  }

  function bindFormFieldAutosize(form) {
    if (!form) return;
    if (form.getAttribute('data-field-autosize-bound') === '1') {
      scheduleFormFieldAutosize(form);
      return;
    }
    form.setAttribute('data-field-autosize-bound', '1');
    form.addEventListener('input', function (event) {
      var target = event.target;
      if (target && target.closest && target.closest('.hrd-field')) {
        autosizeFormField(target);
      }
    });
    form._hrdRefreshFieldAutosize = function () {
      refreshFormFieldAutosize(form);
    };
    window.addEventListener('resize', function () {
      Array.prototype.forEach.call(form.querySelectorAll('.hrd-field'), function (field) {
        field._hrdCellW = 0;
        field.classList.remove('hrd-field--grow');
      });
      refreshFormFieldAutosize(form);
    });
    scheduleFormFieldAutosize(form);
  }

  function normalizeGuestCompareName(guest) {
    guest = guest || {};
    var first = String(guest.firstName || guest.first_name || '').trim();
    var last = String(guest.lastName || guest.last_name || '').trim();
    var guestName = String(
      guest.guestName || guest.guest_name || guest.name || ''
    ).trim();
    if (!first && !last && guestName) {
      var split = splitGuestName(guestName);
      first = split.firstName || first;
      last = split.lastName || last;
    } else if (first || last) {
      var joinedSplit = splitGuestName([first, last].filter(Boolean).join(' '));
      first = joinedSplit.firstName || first;
      last = joinedSplit.lastName || last;
    }
    var joined = [first, last].filter(Boolean).join(' ').replace(/\s+/g, ' ').trim();
    if (!joined) joined = guestName.replace(/\s+/g, ' ').trim();
    return joined
      .toLowerCase()
      .replace(/^(mr|mrs|ms|miss|dr|mx)\.?\s+/, '');
  }

  function guestNamesMatch(guest, firstName, lastName, guestName) {
    var typed = normalizeGuestCompareName({
      firstName: firstName,
      lastName: lastName,
      guestName: guestName
    });
    if (!typed) return true;
    var saved = normalizeGuestCompareName(guest);
    return !!saved && saved === typed;
  }

  function fillCheckinFromGuest(form, guest) {
    if (!form || !guest) return;
    var names = resolveGuestPersonalNames(guest);
    var title = names.title || String(guest.title || '').trim();
    if (title) resetListbox('hrd-ci-title', title, title);
    setFormText(form, 'firstName', names.firstName);
    setFormText(form, 'lastName', names.lastName);
    syncCustomerNameFromPersonal(form);
    var gender = String(guest.gender || '').trim();
    if (gender) resetListbox('hrd-ci-gender', gender, gender);
    if (guest.dateOfBirth || guest.date_of_birth) {
      setFormDate(form, 'dateOfBirth', guest.dateOfBirth || guest.date_of_birth);
    }
    var nationality = String(guest.nationality || '').trim();
    if (nationality) resetListbox('hrd-ci-nationality', nationality, nationality);
    var countryCode = String(guest.mobileCountry || guest.mobile_country || '+91').trim() || '+91';
    resetListbox('hrd-ci-mobile-country', countryCode, countryCode);
    setFormText(form, 'email', guest.email || '');
    setFormText(form, 'address', guest.address || '');
    setFormText(form, 'city', guest.city || '');
    setFormText(form, 'state', guest.state || '');
    var country = String(guest.country || '').trim();
    if (country) resetListbox('hrd-ci-country', country, country);
    setFormText(form, 'pin', guest.pin || guest.postalCode || '');
    var purpose = String(guest.purposeOfVisit || guest.purpose_of_visit || '').trim();
    if (purpose) resetListbox('hrd-ci-purpose', purpose, purpose);
    var vip = String(guest.vipStatus || guest.vip_status || '').trim();
    if (vip) resetListbox('hrd-ci-vip', vip, vip);
    resetListbox('hrd-ci-returning', 'Yes', 'Yes');
    var idType = String(guest.idType || guest.id_type || '').trim();
    if (idType) resetListbox('hrd-ci-id-type', idType, idType);
    setFormText(form, 'agencyName', guest.agencyName || guest.agency_name || '');
    setFormText(form, 'agencyGst', guest.agencyGst || guest.agency_gst || '');
    setFormText(form, 'agencyAddress', guest.agencyAddress || guest.agency_address || '');
    setFormAgencyBillFlags(form, guest);
    syncAgencyBillingHint(form);
    if (stayDocumentUrl(guest) || guest.idDocumentPath || guest.idDocumentName) {
      setIdDocumentUi(form, {
        urlPath: stayDocumentUrl(guest),
        path: guest.idDocumentPath,
        url: guest.idDocumentPath,
        mime: guest.idDocumentMime || '',
        displayName: idDocumentDisplayLabel(guest, guest.idType, guest.idDocumentName),
        originalName: guest.idDocumentName || '',
        storedName:
          storedIdDocumentName(guest.idDocumentStoredName) ||
          storedIdDocumentName(guest.idDocumentName) ||
          guest.idDocumentName ||
          ''
      });
    }
    if (Array.isArray(guest.additionalGuests)) {
      clearExtraGuests(form);
      guest.additionalGuests.forEach(function (extra) {
        addExtraGuestRow(form, extra, { focus: false });
      });
    }
    scheduleCheckinDraftSave(pageRoot(), form);
    scheduleFormFieldAutosize(form);
  }

  function bindMobileGuestLookup(root, form) {
    if (!form) return;
    var mobileInput = form.elements.mobile || $('#hrd-ci-mobile', form);
    if (!mobileInput) return;
    form._hrdLastGuestLookup = '';
    if (form.getAttribute('data-guest-lookup-bound') === '1') {
      return;
    }
    form.setAttribute('data-guest-lookup-bound', '1');
    var lookupTimer = null;
    var firstInput = form.elements.firstName || $('#hrd-ci-first-name', form);
    var lastInput = form.elements.lastName || $('#hrd-ci-last-name', form);

    function currentLookupKey(digits) {
      var first = firstInput ? String(firstInput.value || '').trim() : '';
      var last = lastInput ? String(lastInput.value || '').trim() : '';
      return digits + '|' + normalizeGuestCompareName({ firstName: first, lastName: last });
    }

    function runLookup() {
      if (form.getAttribute('data-edit-mode') === '1') return;
      var api =
        (root && root.getAttribute('data-guest-lookup-api')) ||
        '/hotel/api/guests/lookup';
      var mobile = String(mobileInput.value || '').trim();
      var digits = mobile.replace(/\D/g, '');
      if (digits.length < 8) return;
      var first = firstInput ? String(firstInput.value || '').trim() : '';
      var last = lastInput ? String(lastInput.value || '').trim() : '';
      var cacheKey = currentLookupKey(digits);
      if (cacheKey === form._hrdLastGuestLookup) return;
      form._hrdLastGuestLookup = cacheKey;
      var url =
        api +
        '?mobile=' +
        encodeURIComponent(mobile) +
        '&firstName=' +
        encodeURIComponent(first) +
        '&lastName=' +
        encodeURIComponent(last);
      fetch(url, {
        credentials: 'same-origin',
        headers: apiHeaders()
      })
        .then(function (resp) {
          return resp.json().then(function (data) {
            return { ok: resp.ok, data: data };
          });
        })
        .then(function (result) {
          if (!result.ok || !result.data || !result.data.found || !result.data.guest) {
            return;
          }
          var guest = result.data.guest;
          var liveFirst = firstInput ? String(firstInput.value || '').trim() : '';
          var liveLast = lastInput ? String(lastInput.value || '').trim() : '';
          var namesOk =
            result.data.nameMatch !== false &&
            guestNamesMatch(guest, liveFirst, liveLast);
          if (!namesOk) return;
          fillCheckinFromGuest(form, guest);
          showToast('Returning guest details loaded.');
        })
        .catch(function () {});
    }

    form._hrdRunGuestLookup = function () {
      form._hrdLastGuestLookup = '';
      runLookup();
    };

    function scheduleLookup() {
      if (lookupTimer) clearTimeout(lookupTimer);
      lookupTimer = setTimeout(runLookup, 450);
    }

    mobileInput.addEventListener('input', scheduleLookup);
    mobileInput.addEventListener('blur', function () {
      if (lookupTimer) clearTimeout(lookupTimer);
      runLookup();
    });
    [firstInput, lastInput].forEach(function (input) {
      if (!input) return;
      input.addEventListener('input', scheduleLookup);
      input.addEventListener('blur', function () {
        if (lookupTimer) clearTimeout(lookupTimer);
        runLookup();
      });
    });
  }

  function bindCheckinCustomerSuggest(root, form) {
    if (!form) return;
    var mobileInput = form.elements.mobile || $('#hrd-ci-mobile', form);
    var box = $('#hrd-ci-customer-suggest', form);
    if (!mobileInput || !box) return;
    if (form.getAttribute('data-ci-customer-suggest-bound') === '1') return;
    form.setAttribute('data-ci-customer-suggest-bound', '1');

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
      var address = String(customer.address || '').trim();
      if (mobile) {
        mobileInput.value = mobile;
      }
      if (name) {
        var parts = resolveGuestPersonalNames({ guestName: name, name: name });
        if (parts.title) resetListbox('hrd-ci-title', parts.title, parts.title);
        setFormText(form, 'firstName', parts.firstName);
        setFormText(form, 'lastName', parts.lastName);
        syncCustomerNameFromPersonal(form);
      }
      if (email) setFormText(form, 'email', email);
      if (address) setFormText(form, 'address', address);
      closeSuggest();
      scheduleCheckinDraftSave(pageRoot(), form);
      scheduleFormFieldAutosize(form);
      showToast('Customer details loaded.');
      if (typeof form._hrdRunGuestLookup === 'function') {
        form._hrdRunGuestLookup();
      }
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
            '<button type="button" class="hrd-customer-opt' +
            (idx === activeIndex ? ' is-active' : '') +
            '" role="option" data-customer-index="' +
            idx +
            '">' +
            '<span class="hrd-customer-opt-mobile">' +
            escapeHtml(c.mobile || '') +
            '</span>' +
            '<span class="hrd-customer-opt-name">' +
            escapeHtml(c.name || c.first_name || '—') +
            '</span></button>'
          );
        })
        .join('');
    }

    function runSearch() {
      var api =
        (root && root.getAttribute('data-customers-api')) ||
        '/hotel/api/customers';
      var digits = String(mobileInput.value || '').replace(/\D/g, '').slice(0, 10);
      if (mobileInput.value !== digits) mobileInput.value = digits;
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
      if (timer) clearTimeout(timer);
      timer = setTimeout(runSearch, 220);
    });
    mobileInput.addEventListener('paste', function (event) {
      event.preventDefault();
      var text = '';
      try {
        text = (event.clipboardData || window.clipboardData).getData('text') || '';
      } catch (err) {
        text = '';
      }
      mobileInput.value = String(text).replace(/\D/g, '').slice(0, 10);
      if (timer) clearTimeout(timer);
      timer = setTimeout(runSearch, 220);
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
      var btn = event.target.closest('[data-customer-index]');
      if (!btn) return;
      event.preventDefault();
      var idx = Number(btn.getAttribute('data-customer-index'));
      if (!isNaN(idx) && results[idx]) applyCustomer(results[idx]);
    });
    mobileInput.addEventListener('blur', function () {
      setTimeout(closeSuggest, 150);
    });
    document.addEventListener('click', function (event) {
      if (!form.contains(event.target)) closeSuggest();
    });
  }

  function reserveMobileDigits(form) {
    var mobileInput =
      (form && ($('#hrd-reserve-mobile', form) || form.elements.mobile)) || null;
    if (!mobileInput) return '';
    return String(mobileInput.value || '').replace(/\D/g, '').slice(0, 10);
  }

  function syncReserveSaveEnabled(root, form) {
    var saveBtn =
      (root && $('#hrd-reserve-save', root)) ||
      document.getElementById('hrd-reserve-save');
    if (!saveBtn) return;
    var digits = reserveMobileDigits(form);
    var ok = digits.length === 10;
    saveBtn.disabled = !ok;
    saveBtn.setAttribute('aria-disabled', ok ? 'false' : 'true');
    if (ok) {
      saveBtn.removeAttribute('title');
    } else {
      saveBtn.title = 'Enter a 10-digit mobile number to save';
    }
  }

  function bindReserveCustomerSuggest(root, form) {
    if (!form) return;
    var mobileInput = $('#hrd-reserve-mobile', form) || form.elements.mobile;
    var nameInput = $('#hrd-reserve-guest-name', form) || form.elements.guestName;
    var box = $('#hrd-reserve-customer-suggest', form);
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
      var emailInput = $('#hrd-reserve-email', form) || form.elements.email;
      if (email && emailInput) emailInput.value = email;
      closeSuggest();
      syncReserveSaveEnabled(root, form);
      scheduleFormFieldAutosize(form);
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
            '<button type="button" class="hrd-customer-opt' +
            (idx === activeIndex ? ' is-active' : '') +
            '" role="option" data-customer-index="' +
            idx +
            '">' +
            '<span class="hrd-customer-opt-mobile">' +
            escapeHtml(c.mobile || '') +
            '</span>' +
            '<span class="hrd-customer-opt-name">' +
            escapeHtml(c.name || c.first_name || '—') +
            '</span></button>'
          );
        })
        .join('');
    }

    function runSearch() {
      var api =
        (root && root.getAttribute('data-customers-api')) ||
        '/hotel/api/customers';
      var q = String(mobileInput.value || '').trim();
      var digits = q.replace(/\D/g, '');
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

    function normalizeMobileAndSync() {
      var digits = String(mobileInput.value || '').replace(/\D/g, '').slice(0, 10);
      if (mobileInput.value !== digits) mobileInput.value = digits;
      syncReserveSaveEnabled(root, form);
      return digits;
    }

    mobileInput.addEventListener('input', function () {
      normalizeMobileAndSync();
      if (timer) clearTimeout(timer);
      timer = setTimeout(runSearch, 220);
    });
    mobileInput.addEventListener('paste', function (event) {
      event.preventDefault();
      var text = '';
      try {
        text = (event.clipboardData || window.clipboardData).getData('text') || '';
      } catch (err) {
        text = '';
      }
      mobileInput.value = String(text).replace(/\D/g, '').slice(0, 10);
      syncReserveSaveEnabled(root, form);
      if (timer) clearTimeout(timer);
      timer = setTimeout(runSearch, 220);
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
      var btn = event.target.closest('[data-customer-index]');
      if (!btn) return;
      event.preventDefault();
      var idx = Number(btn.getAttribute('data-customer-index'));
      if (!isNaN(idx) && results[idx]) applyCustomer(results[idx]);
    });
    mobileInput.addEventListener('blur', function () {
      normalizeMobileAndSync();
      setTimeout(closeSuggest, 150);
    });
    document.addEventListener('click', function (event) {
      if (!form.contains(event.target)) closeSuggest();
    });
  }

  function parseAgenciesData(root) {
    try {
      var raw = root && root.getAttribute('data-agencies');
      var list = raw ? JSON.parse(raw) : [];
      return Array.isArray(list) ? list : [];
    } catch (err) {
      return [];
    }
  }

  function syncAgencyDatalist(root, agencies) {
    if (root) {
      try {
        root.setAttribute('data-agencies', JSON.stringify(agencies || []));
      } catch (err) {}
    }
  }

  function filterAgencies(agencies, query) {
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

  function findAgencyByName(agencies, typed) {
    var needle = String(typed || '').trim().toLowerCase();
    if (!needle) return null;
    for (var i = 0; i < (agencies || []).length; i += 1) {
      if (String(agencies[i].name || '').trim().toLowerCase() === needle) {
        return agencies[i];
      }
    }
    return null;
  }

  function refreshAgenciesFromApi(root, done) {
    var local = parseAgenciesData(root);
    var api = root && root.getAttribute('data-agencies-api');
    if (!api) {
      if (done) done(local);
      return;
    }
    fetch(api, {
      credentials: 'same-origin',
      headers: apiHeaders()
    })
      .then(function (resp) {
        return resp.json().then(function (data) {
          return { ok: resp.ok, data: data };
        });
      })
      .then(function (result) {
        if (result.ok && result.data && result.data.ok && Array.isArray(result.data.agencies)) {
          syncAgencyDatalist(root, result.data.agencies);
          if (done) done(result.data.agencies);
          return;
        }
        if (done) done(local);
      })
      .catch(function () {
        if (done) done(local);
      });
  }

  function fillAgencyFieldsFromMaster(form, agency) {
    if (!form || !agency) return;
    setFormText(form, 'agencyName', agency.name || '');
    setFormText(form, 'agencyGst', agency.gst || '');
    setFormText(form, 'agencyAddress', agency.address || '');
    syncAgencyBillingHint(form);
    scheduleFormFieldAutosize(form);
  }

  function agencyMasterPayload(form) {
    var name = form && form.elements.agencyName
      ? String(form.elements.agencyName.value || '').trim()
      : '';
    var gst = form && form.elements.agencyGst
      ? normalizeGstin(form.elements.agencyGst.value)
      : '';
    var address = form && form.elements.agencyAddress
      ? String(form.elements.agencyAddress.value || '').trim()
      : '';
    if (gst && !isValidGstin(gst)) gst = '';
    return { name: name, gst: gst, address: address };
  }

  function syncAgencyMasterFromForm(root, form, opts) {
    opts = opts || {};
    if (!form) return;
    var payload = agencyMasterPayload(form);
    if (!payload.name) return;
    var key = JSON.stringify(payload);
    if (form._hrdAgencyMasterSyncKey === key) return;
    var createUrl =
      (root && root.getAttribute('data-agency-create-url')) || '/agencies/create';
    form._hrdAgencyMasterSyncKey = key;
    fetch(createUrl, {
      method: 'POST',
      credentials: 'same-origin',
      headers: apiHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(payload)
    })
      .then(function (resp) {
        return resp.json().then(function (data) {
          return { ok: resp.ok, data: data };
        });
      })
      .then(function (result) {
        if (!result.ok || !result.data || !result.data.ok) {
          form._hrdAgencyMasterSyncKey = '';
          if (opts.toast) {
            showToast(
              (result.data && result.data.error) || 'Could not save agency.',
              true
            );
          }
          return;
        }
        if (result.data.agencies) {
          syncAgencyDatalist(root, result.data.agencies);
        }
        if (opts.toast) showToast('Saved to Agency Master.');
      })
      .catch(function () {
        form._hrdAgencyMasterSyncKey = '';
        if (opts.toast) showToast('Could not save agency.', true);
      });
  }

  function bindAgencyMasterSync(root, form) {
    if (!form || form.getAttribute('data-agency-sync-bound') === '1') return;
    form.setAttribute('data-agency-sync-bound', '1');
    ['agencyName', 'agencyGst', 'agencyAddress'].forEach(function (fieldName) {
      var input = form.elements[fieldName];
      if (!input) return;
      input.addEventListener('blur', function () {
        syncAgencyMasterFromForm(root, form, { toast: false });
      });
    });
  }

  function bindAgencySuggest(root, form, nameInput) {
    if (!form || !nameInput) return;
    if (nameInput.getAttribute('data-agency-pick-bound') === '1') return;
    nameInput.setAttribute('data-agency-pick-bound', '1');
    nameInput.setAttribute('autocomplete', 'off');
    nameInput.removeAttribute('list');

    var boxId = nameInput.getAttribute('aria-controls');
    var box =
      (boxId && document.getElementById(boxId)) ||
      (nameInput.closest('.hrd-field') &&
        nameInput.closest('.hrd-field').querySelector('.hrd-customer-suggest')) ||
      $('#hrd-ci-agency-suggest', form) ||
      $('#hrd-reserve-agency-suggest', form);

    var timer = null;
    var results = [];
    var activeIndex = -1;

    function closeSuggest() {
      if (box) {
        box.hidden = true;
        box.innerHTML = '';
      }
      nameInput.setAttribute('aria-expanded', 'false');
      activeIndex = -1;
      results = [];
    }

    function applyAgency(agency, fromPick) {
      if (!agency) return;
      fillAgencyFieldsFromMaster(form, agency);
      closeSuggest();
      if (fromPick) showToast('Agency details loaded.');
    }

    function renderSuggest(list) {
      results = list || [];
      if (!box || !results.length) {
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
            '<button type="button" class="hrd-customer-opt' +
            (idx === activeIndex ? ' is-active' : '') +
            '" role="option" data-agency-index="' +
            idx +
            '">' +
            '<span class="hrd-customer-opt-mobile">' +
            escapeHtml(agency.name || '') +
            '</span>' +
            (meta
              ? '<span class="hrd-customer-opt-name">' + escapeHtml(meta) + '</span>'
              : '') +
            '</button>'
          );
        })
        .join('');
    }

    function showForQuery(query) {
      renderSuggest(filterAgencies(parseAgenciesData(root), query));
    }

    nameInput.addEventListener('focus', function () {
      showForQuery(nameInput.value);
      refreshAgenciesFromApi(root, function () {
        if (document.activeElement === nameInput) showForQuery(nameInput.value);
      });
    });
    nameInput.addEventListener('click', function () {
      showForQuery(nameInput.value);
    });
    nameInput.addEventListener('input', function () {
      if (timer) clearTimeout(timer);
      timer = setTimeout(function () {
        showForQuery(nameInput.value);
      }, 120);
      syncAgencyBillingHint(form);
    });
    nameInput.addEventListener('keydown', function (event) {
      if (!box || box.hidden || !results.length) return;
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
    if (box) {
      box.addEventListener('mousedown', function (event) {
        var btn = event.target.closest('[data-agency-index]');
        if (!btn) return;
        event.preventDefault();
        var idx = Number(btn.getAttribute('data-agency-index'));
        if (!isNaN(idx) && results[idx]) applyAgency(results[idx], true);
      });
    }
    nameInput.addEventListener('blur', function () {
      var match = findAgencyByName(parseAgenciesData(root), nameInput.value);
      if (match) fillAgencyFieldsFromMaster(form, match);
      setTimeout(closeSuggest, 150);
    });
    document.addEventListener('click', function (event) {
      if (!form.contains(event.target)) closeSuggest();
    });
  }

  var hrdAgencyMasterAbort = null;

  function buildAgencyEmbedUrl(url) {
    try {
      var parsed = new URL(url, window.location.origin);
      if (parsed.origin !== window.location.origin) return url;
      parsed.searchParams.set('embed', '1');
      return parsed.pathname + parsed.search + parsed.hash;
    } catch (err) {
      if (String(url).indexOf('embed=1') !== -1) return url;
      return url + (String(url).indexOf('?') === -1 ? '?' : '&') + 'embed=1';
    }
  }

  function ensureAgencyMasterModalDom() {
    var modal = document.getElementById('md-master-modal');
    if (modal) return modal;
    var host =
      (pageRoot() && pageRoot().parentNode) ||
      document.querySelector('.de-main-wrapper') ||
      document.body;
    modal = document.createElement('div');
    modal.className = 'modal-backdrop md-master-modal';
    modal.id = 'md-master-modal';
    modal.setAttribute('aria-hidden', 'true');
    modal.innerHTML =
      '<div class="md-master-dialog" role="dialog" aria-modal="true" aria-labelledby="md-master-modal-title">' +
      '<header class="md-master-dialog-hdr">' +
      '<h2 class="md-master-dialog-title" id="md-master-modal-title">Agency Master</h2>' +
      '<button type="button" class="md-master-modal-close" id="md-master-modal-close" aria-label="Close Agency Master">' +
      '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>' +
      '</button></header>' +
      '<div class="md-master-dialog-body">' +
      '<div class="md-master-modal-loading" id="md-master-modal-loading" hidden>' +
      '<span class="md-master-modal-spinner" aria-hidden="true"></span>' +
      '<span>Loading Agency Master…</span></div>' +
      '<div class="md-master-modal-inject" id="md-master-modal-inject" hidden></div>' +
      '<div class="md-master-modal-empty" id="md-master-modal-empty" hidden>' +
      '<p class="md-master-modal-empty-title">Could not open Agency Master</p>' +
      '<p class="md-master-modal-empty-copy">Check your access, then try again.</p>' +
      '</div></div></div>';
    host.appendChild(modal);
    return modal;
  }

  function setAgencyMasterPanel(el, show) {
    if (!el) return;
    el.hidden = !show;
    el.classList.toggle('is-md-panel-visible', !!show);
  }

  function closeHrdAgencyMasterModal() {
    if (hrdAgencyMasterAbort) {
      try {
        hrdAgencyMasterAbort.abort();
      } catch (err) {}
      hrdAgencyMasterAbort = null;
    }
    if (typeof global.closeMasterModal === 'function') {
      global.closeMasterModal();
      return;
    }
    var modal = document.getElementById('md-master-modal');
    if (!modal) return;
    modal.classList.remove('open');
    modal.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('md-master-modal-open');
    var inject = document.getElementById('md-master-modal-inject');
    if (inject) inject.innerHTML = '';
    setAgencyMasterPanel(document.getElementById('md-master-modal-loading'), false);
    setAgencyMasterPanel(document.getElementById('md-master-modal-empty'), false);
    setAgencyMasterPanel(inject, false);
    try {
      document.dispatchEvent(new CustomEvent('md-master-modal-closed'));
    } catch (err) {}
  }

  function paintHrdAgencyMasterHtml(html) {
    var inject = document.getElementById('md-master-modal-inject');
    var loading = document.getElementById('md-master-modal-loading');
    var empty = document.getElementById('md-master-modal-empty');
    var titleEl = document.getElementById('md-master-modal-title');
    if (!inject) return false;
    var doc = new DOMParser().parseFromString(html, 'text/html');
    var fragment =
      doc.querySelector('.md-master-embed') ||
      doc.querySelector('.main-wrapper') ||
      doc.body;
    if (!fragment) {
      setAgencyMasterPanel(loading, false);
      setAgencyMasterPanel(inject, false);
      setAgencyMasterPanel(empty, true);
      return false;
    }
    inject.innerHTML = fragment === doc.body ? fragment.innerHTML : fragment.outerHTML;
    inject.querySelectorAll('form[data-md-full-nav]').forEach(function (form) {
      form.removeAttribute('data-md-full-nav');
      form.setAttribute('data-md-embed-form', '1');
    });
    var embedRoot = inject.querySelector('[data-md-modal-title]');
    if (titleEl && embedRoot) {
      var nextTitle = String(embedRoot.getAttribute('data-md-modal-title') || '').trim();
      if (nextTitle) titleEl.textContent = nextTitle;
    }
    inject.querySelectorAll('script').forEach(function (oldScript) {
      var script = document.createElement('script');
      Array.prototype.slice.call(oldScript.attributes).forEach(function (attr) {
        script.setAttribute(attr.name, attr.value);
      });
      script.textContent = oldScript.textContent;
      oldScript.parentNode.replaceChild(script, oldScript);
    });
    setAgencyMasterPanel(loading, false);
    setAgencyMasterPanel(empty, false);
    setAgencyMasterPanel(inject, true);
    bindHrdAgencyMasterEmbedNav(inject);
    try {
      if (typeof global.initEpListboxes === 'function') global.initEpListboxes();
    } catch (err) {}
    try {
      if (typeof global.initHbeTableScroll === 'function') global.initHbeTableScroll();
    } catch (err) {}
    return true;
  }

  function loadHrdAgencyMasterEmbed(url) {
    var loading = document.getElementById('md-master-modal-loading');
    var empty = document.getElementById('md-master-modal-empty');
    var inject = document.getElementById('md-master-modal-inject');
    var fetchUrl = buildAgencyEmbedUrl(url);
    if (hrdAgencyMasterAbort) {
      try {
        hrdAgencyMasterAbort.abort();
      } catch (err) {}
    }
    hrdAgencyMasterAbort = new AbortController();
    setAgencyMasterPanel(empty, false);
    setAgencyMasterPanel(inject, false);
    setAgencyMasterPanel(loading, true);
    if (inject) {
      inject.innerHTML = '';
      inject.__hrdAgencyNavBound = false;
    }
    return fetch(fetchUrl, {
      credentials: 'same-origin',
      headers: { Accept: 'text/html' },
      signal: hrdAgencyMasterAbort.signal
    })
      .then(function (resp) {
        if (!resp.ok) throw new Error('fetch failed');
        return resp.text();
      })
      .then(function (html) {
        paintHrdAgencyMasterHtml(html);
      })
      .catch(function (err) {
        if (err && err.name === 'AbortError') return;
        setAgencyMasterPanel(loading, false);
        setAgencyMasterPanel(inject, false);
        setAgencyMasterPanel(empty, true);
      });
  }

  function bindHrdAgencyMasterEmbedNav(inject) {
    if (!inject || inject.__hrdAgencyNavBound) return;
    inject.__hrdAgencyNavBound = true;
    inject.addEventListener('click', function (e) {
      var link = e.target && e.target.closest ? e.target.closest('a[href]') : null;
      if (!link || !inject.contains(link)) return;
      if (link.hasAttribute('download')) return;
      if (link.target && link.target !== '_self') return;
      if (link.hasAttribute('data-de-no-soft-nav')) return;
      var href = link.getAttribute('href');
      if (!href || href.charAt(0) === '#') return;
      e.preventDefault();
      e.stopPropagation();
      loadHrdAgencyMasterEmbed(href);
    });
    inject.addEventListener('submit', function (e) {
      var form = e.target;
      if (!form || form.tagName !== 'FORM' || !inject.contains(form)) return;
      e.preventDefault();
      var action = form.getAttribute('action') || '/agencies';
      var method = String(form.getAttribute('method') || form.method || 'get').toLowerCase();
      if (method === 'get') {
        try {
          var getUrl = new URL(action, window.location.origin);
          new FormData(form).forEach(function (value, key) {
            if (value != null && String(value) !== '') getUrl.searchParams.set(key, value);
          });
          loadHrdAgencyMasterEmbed(getUrl.pathname + getUrl.search);
        } catch (err) {
          loadHrdAgencyMasterEmbed(action);
        }
        return;
      }
      var body;
      try {
        body = e.submitter ? new FormData(form, e.submitter) : new FormData(form);
      } catch (err) {
        body = new FormData(form);
      }
      if (!body.get('embed')) body.set('embed', '1');
      var loading = document.getElementById('md-master-modal-loading');
      var empty = document.getElementById('md-master-modal-empty');
      setAgencyMasterPanel(empty, false);
      setAgencyMasterPanel(inject, false);
      setAgencyMasterPanel(loading, true);
      if (hrdAgencyMasterAbort) {
        try {
          hrdAgencyMasterAbort.abort();
        } catch (err) {}
      }
      hrdAgencyMasterAbort = new AbortController();
      fetch(buildAgencyEmbedUrl(action), {
        method: 'POST',
        body: body,
        credentials: 'same-origin',
        headers: { Accept: 'text/html' },
        redirect: 'follow',
        signal: hrdAgencyMasterAbort.signal
      })
        .then(function (resp) {
          if (!resp.ok && resp.status !== 400) throw new Error('post failed');
          return resp.text();
        })
        .then(function (html) {
          paintHrdAgencyMasterHtml(html);
        })
        .catch(function (err) {
          if (err && err.name === 'AbortError') return;
          setAgencyMasterPanel(loading, false);
          setAgencyMasterPanel(inject, false);
          setAgencyMasterPanel(empty, true);
        });
    });
  }

  function bindHrdAgencyMasterModalChrome(modal) {
    if (!modal || modal.getAttribute('data-hrd-agency-modal-bound') === '1') return;
    modal.setAttribute('data-hrd-agency-modal-bound', '1');
    modal.addEventListener('click', function (e) {
      if (e.target === modal) closeHrdAgencyMasterModal();
    });
    var closeBtn = document.getElementById('md-master-modal-close');
    if (closeBtn) {
      closeBtn.addEventListener('click', function (e) {
        e.preventDefault();
        closeHrdAgencyMasterModal();
      });
    }
  }

  function openAgencyMasterPopup(root, opts) {
    opts = opts || {};
    var masterUrl =
      (root && root.getAttribute('data-agency-master-url')) || '/agencies';
    if (opts.focusForm) {
      try {
        var parsed = new URL(masterUrl, window.location.origin);
        parsed.searchParams.set('focus', 'form');
        masterUrl = parsed.pathname + parsed.search;
      } catch (err) {
        masterUrl =
          masterUrl + (masterUrl.indexOf('?') === -1 ? '?' : '&') + 'focus=form';
      }
    }

    var modal = ensureAgencyMasterModalDom();
    bindHrdAgencyMasterModalChrome(modal);

    /* Prefer shared Masters helper when already loaded — do not re-init
       (re-init closed the modal and stacked embed click listeners). */
    if (typeof global.openMasterModal === 'function') {
      global.openMasterModal('Agency Master', masterUrl, 'agency');
      if (modal.classList.contains('open')) return true;
    }

    /* Self-contained fallback — never navigate away from check-in. */
    if (typeof global.closeMasterModal !== 'function') {
      global.closeMasterModal = closeHrdAgencyMasterModal;
    }
    modal.classList.add('open');
    modal.setAttribute('aria-hidden', 'false');
    document.body.classList.add('md-master-modal-open');
    loadHrdAgencyMasterEmbed(masterUrl);
    return true;
  }

  function bindAgencyMasterControls(root, form) {
    if (!form) return;
    bindAgencyGstInput(
      form.elements.agencyGst ||
        $('#hrd-ci-agency-gst', form) ||
        $('#hrd-reserve-agency-gst', form)
    );
    var nameInput =
      form.elements.agencyName ||
      $('#hrd-ci-agency-name', form) ||
      $('#hrd-reserve-agency-name', form);
    bindAgencySuggest(root, form, nameInput);
    bindAgencyMasterSync(root, form);

    var btn = form.querySelector('[data-hrd-agency-master]') || $('#hrd-ci-agency-master-btn', form);
    if (!btn || btn.getAttribute('data-agency-master-bound') === '1') return;
    btn.setAttribute('data-agency-master-bound', '1');
    btn.addEventListener('click', function (event) {
      event.preventDefault();
      event.stopPropagation();
      var gstError = agencyGstValidationError(form);
      if (gstError) {
        showToast(gstError, true);
        try {
          form.elements.agencyGst.focus();
          form.elements.agencyGst.select();
        } catch (err) {}
        return;
      }
      openAgencyMasterPopup(root);
    });
  }

  function syncIdDocumentViewBtn(form, hasDoc) {
    var viewBtn = form && $('#hrd-ci-id-view-btn', form);
    if (!viewBtn) return;
    var ready = !!hasDoc;
    viewBtn.hidden = !ready;
    viewBtn.disabled = !ready;
    viewBtn.classList.toggle('is-ready', ready);
  }

  function clearIdDocumentFields(form) {
    if (!form) return;
    var fileInput = form.querySelector('#hrd-ci-id-document') || form.querySelector('input[name="idDocument"]');
    if (fileInput) fileInput.value = '';
    if (form.elements.idDocumentPath) form.elements.idDocumentPath.value = '';
    if (form.elements.idDocumentMime) form.elements.idDocumentMime.value = '';
    if (form.elements.idDocumentStoredName) form.elements.idDocumentStoredName.value = '';
    var uploadName = $('#hrd-ci-id-upload-name', form) || $('.hrd-upload-text', form);
    var uploadBtn = $('#hrd-ci-id-upload-btn', form);
    if (uploadName) {
      uploadName.textContent = '';
      uploadName.hidden = true;
    }
    if (uploadBtn) {
      uploadBtn.classList.remove('is-filled', 'is-busy');
      uploadBtn.disabled = false;
      uploadBtn.title = 'Upload ID (PDF, or photos combined into one PDF)';
    }
    syncIdDocumentViewBtn(form, false);
  }

  function setIdDocumentUi(form, doc) {
    if (!form) return;
    var uploadName = $('#hrd-ci-id-upload-name', form);
    var uploadBtn = $('#hrd-ci-id-upload-btn', form);
    var name = (doc && (doc.displayName || doc.originalName)) || '';
    var path = (doc && (doc.urlPath || doc.path || doc.url)) || '';
    if (form.elements.idDocumentPath) {
      form.elements.idDocumentPath.value = path;
    }
    if (form.elements.idDocumentMime) {
      form.elements.idDocumentMime.value = (doc && doc.mime) || '';
    }
    if (form.elements.idDocumentStoredName) {
      form.elements.idDocumentStoredName.value = (doc && doc.storedName) || '';
    }
    if (uploadName) {
      if (name) {
        uploadName.textContent = name;
        uploadName.hidden = false;
      } else {
        uploadName.textContent = '';
        uploadName.hidden = true;
      }
    }
    if (uploadBtn) {
      uploadBtn.classList.toggle('is-filled', !!path);
      uploadBtn.title = name
        ? name
        : 'Upload ID (PDF, or photos combined into one PDF)';
    }
    syncIdDocumentViewBtn(form, !!path);
  }

  function storedIdDocumentName(value) {
    var text = String(value || '').trim();
    if (!text) return '';
    text = text.split('?')[0].split('#')[0].replace(/\\/g, '/').replace(/\/+$/, '');
    if (/\/(raw|content)$/i.test(text)) {
      text = text.replace(/\/(raw|content)$/i, '');
    }
    var viewAt = text.indexOf('/id-documents/view/');
    if (viewAt !== -1) {
      text = text.slice(viewAt + '/id-documents/view/'.length);
    } else {
      var apiAt = text.indexOf('/id-documents/');
      if (apiAt !== -1) text = text.slice(apiAt + '/id-documents/'.length);
      else text = text.split('/').pop() || '';
    }
    var file = String(text.split('/').pop() || '').trim();
    if (
      /^[A-Za-z0-9._ -]+\.(webp|pdf|jpe?g|png|heic|heif)$/i.test(file) &&
      file.indexOf('..') === -1
    ) {
      return file;
    }
    if (
      /^[0-9a-f]{32}$/i.test(file) ||
      /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(file)
    ) {
      return file;
    }
    return '';
  }

  function idDocumentApiBase() {
    var root = pageRoot();
    var api =
      (root && root.getAttribute('data-id-document-upload-api')) ||
      '/hotel/api/id-documents';
    return String(api || '').replace(/\/+$/, '') || '/hotel/api/id-documents';
  }

  function idDocumentViewUrl(path) {
    var stored = storedIdDocumentName(path);
    if (!stored) return '';
    return idDocumentApiBase() + '/view/' + encodeURIComponent(stored) + '/raw';
  }

  function idDocumentAliasName(file) {
    return String(file || '')
      .replace(/\s+/g, '_')
      .replace(/[^A-Za-z0-9._-]/g, '');
  }

  function uuidDocumentStems(stem) {
    var text = String(stem || '').trim();
    if (!text) return [];
    var stems = [text];
    var compact = text.replace(/-/g, '');
    if (/^[0-9a-f]{32}$/i.test(compact)) {
      stems.push(compact.toLowerCase());
      stems.push(
        compact.slice(0, 8) +
          '-' +
          compact.slice(8, 12) +
          '-' +
          compact.slice(12, 16) +
          '-' +
          compact.slice(16, 20) +
          '-' +
          compact.slice(20)
      );
    }
    var seen = {};
    return stems.filter(function (item) {
      if (!item || seen[item]) return false;
      seen[item] = true;
      return true;
    });
  }

  function stayDocumentUrl(stay) {
    if (!stay) return '';
    return (
      idDocumentViewUrl(stay.idDocumentPath || stay.id_document_path || '') ||
      idDocumentViewUrl(stay.idDocumentStoredName || stay.id_document_stored_name || '') ||
      idDocumentViewUrl(stay.idDocumentName || stay.id_document_name || '')
    );
  }

  function pushIdDocumentUrl(list, seen, value) {
    var names = {};
    var files = [];
    function addName(file) {
      file = String(file || '').trim();
      if (!file || names[file]) return;
      names[file] = true;
      files.push(file);
    }
    addName(storedIdDocumentName(value));
    addName(idDocumentAliasName(storedIdDocumentName(value)));
    files.slice().forEach(function (file) {
      var dot = file.lastIndexOf('.');
      var stem = dot > 0 ? file.slice(0, dot) : file;
      var ext = dot > 0 ? file.slice(dot) : '';
      uuidDocumentStems(stem).forEach(function (variant) {
        if (ext) addName(variant + ext);
        ['.pdf', '.webp', '.jpg', '.jpeg', '.png'].forEach(function (other) {
          addName(variant + other);
        });
      });
    });
    files.forEach(function (file) {
      var url = idDocumentViewUrl(file);
      if (url && !seen[url]) {
        seen[url] = true;
        list.push(url);
      }
      var legacy = idDocumentApiBase() + '/' + encodeURIComponent(file);
      if (legacy && !seen[legacy]) {
        seen[legacy] = true;
        list.push(legacy);
      }
    });
  }

  function idDocumentCandidateUrls(root, pathOverride) {
    var urls = [];
    var seen = {};
    pushIdDocumentUrl(urls, seen, pathOverride);
    var stay = (lastRoom && lastRoom.stay) || null;
    if (stay) {
      pushIdDocumentUrl(urls, seen, stay.idDocumentPath || stay.id_document_path);
      pushIdDocumentUrl(urls, seen, stay.idDocumentStoredName);
      pushIdDocumentUrl(urls, seen, stay.idDocumentName);
    }
    var form = root && $('#hrd-checkin-form', root);
    if (form) {
      pushIdDocumentUrl(
        urls,
        seen,
        form.elements.idDocumentPath && form.elements.idDocumentPath.value
      );
      pushIdDocumentUrl(
        urls,
        seen,
        form.elements.idDocumentStoredName && form.elements.idDocumentStoredName.value
      );
      var uploadName = $('#hrd-ci-id-upload-name', form);
      if (uploadName) pushIdDocumentUrl(urls, seen, uploadName.textContent);
    }
    var cardName = root && $('#hrd-id-doc-name', root);
    if (cardName) pushIdDocumentUrl(urls, seen, cardName.textContent);
    var draft = readCheckinDraft(root);
    var draftStay = draft && draft.stay;
    if (draftStay) {
      pushIdDocumentUrl(urls, seen, draftStay.idDocumentPath);
      pushIdDocumentUrl(urls, seen, draftStay.idDocumentStoredName);
      pushIdDocumentUrl(urls, seen, draftStay.idDocumentName);
    }
    return urls;
  }

  function revokeIdPreviewBlob() {
    var modal = document.getElementById('hrd-id-preview-modal');
    if (modal && modal.__hrdBlobUrl) {
      try {
        URL.revokeObjectURL(modal.__hrdBlobUrl);
      } catch (err) {}
      modal.__hrdBlobUrl = '';
    }
  }

  function closeIdDocumentPreview() {
    var modal = document.getElementById('hrd-id-preview-modal');
    if (!modal) return;
    revokeIdPreviewBlob();
    modal.hidden = true;
    modal.setAttribute('aria-hidden', 'true');
    var body = document.getElementById('hrd-id-preview-body');
    if (body) body.innerHTML = '';
    if (modal.__hrdPreviewHome && modal.parentNode === document.body) {
      modal.__hrdPreviewHome.appendChild(modal);
    }
    modal.__hrdPreviewHome = null;
  }

  function renderIdDocumentBlob(body, blob, ctype, mimeHint, url) {
    revokeIdPreviewBlob();
    var modal = document.getElementById('hrd-id-preview-modal');
    var blobUrl = URL.createObjectURL(blob);
    if (modal) modal.__hrdBlobUrl = blobUrl;
    var isPdf =
      /pdf/i.test(ctype || '') ||
      /pdf/i.test(mimeHint || '') ||
      /pdf/i.test(blob.type || '') ||
      /\.pdf(\?|$)/i.test(url || '');
    if (isPdf) {
      body.innerHTML =
        '<iframe class="hrd-id-preview-frame" title="Guest ID document" src="' +
        blobUrl +
        '"></iframe>';
      return;
    }
    body.innerHTML =
      '<img class="hrd-id-preview-image" alt="Guest ID document" src="' +
      blobUrl +
      '">';
  }

  function fetchIdDocumentBlob(url) {
    return fetch(url, {
      credentials: 'same-origin',
      headers: {
        Accept: 'application/pdf,image/*,application/octet-stream,*/*',
        'X-Requested-With': 'XMLHttpRequest'
      },
      cache: 'no-store'
    }).then(function (resp) {
      if (!resp.ok) throw new Error('missing');
      var ctype = String(resp.headers.get('Content-Type') || '')
        .split(';')[0]
        .trim()
        .toLowerCase();
      return resp.blob().then(function (blob) {
        return blob.slice(0, 8).arrayBuffer().then(function (buf) {
          var bytes = new Uint8Array(buf);
          var head = '';
          for (var i = 0; i < bytes.length; i++) {
            head += String.fromCharCode(bytes[i]);
          }
          var isPdf = head.indexOf('%PDF') === 0;
          var blobType = String(blob.type || '').toLowerCase();
          var isHtml =
            !isPdf &&
            (blobType.indexOf('html') !== -1 ||
              ctype.indexOf('text/html') !== -1 ||
              head.indexOf('<!') === 0 ||
              head.toLowerCase().indexOf('<html') === 0);
          if (isHtml) throw new Error('html');
          if (
            !isPdf &&
            ctype &&
            !/^image\//.test(ctype) &&
            ctype.indexOf('pdf') === -1 &&
            ctype !== 'application/octet-stream' &&
            ctype !== 'binary/octet-stream'
          ) {
            throw new Error('bad-type');
          }
          return {
            blob: blob,
            ctype: isPdf ? 'application/pdf' : ctype || blobType,
            url: url
          };
        });
      });
    });
  }

  function loadIdDocumentIntoPreview(urls, mimeHint) {
    var body = document.getElementById('hrd-id-preview-body');
    var addBtn = document.getElementById('hrd-id-preview-add');
    if (!body) return;
    if (!urls.length) {
      body.innerHTML =
        '<p class="hrd-id-preview-empty">No ID document uploaded for this guest. Use Add Guest ID to attach a photo or PDF.</p>';
      if (addBtn) addBtn.hidden = false;
      return;
    }
    body.innerHTML = '<p class="hrd-id-preview-empty">Loading ID document…</p>';
    if (addBtn) addBtn.hidden = true;
    var index = 0;
    function next() {
      if (index >= urls.length) {
        body.innerHTML =
          '<p class="hrd-id-preview-empty">Could not load the ID document. Upload it again from Add Guest ID — the file name on the card is not enough if the image was not saved to storage.</p>';
        if (addBtn) addBtn.hidden = false;
        return;
      }
      var url = urls[index++];
      fetchIdDocumentBlob(url)
        .then(function (result) {
          renderIdDocumentBlob(
            body,
            result.blob,
            result.ctype,
            mimeHint,
            result.url
          );
        })
        .catch(function () {
          next();
        });
    }
    next();
  }

  function openIdDocumentPreview(ref) {
    ref = ref || {};
    var modal = document.getElementById('hrd-id-preview-modal');
    var body = document.getElementById('hrd-id-preview-body');
    var sub = document.getElementById('hrd-id-preview-sub');
    var addBtn = document.getElementById('hrd-id-preview-add');
    var root = pageRoot();
    var urls = Array.isArray(ref.urls) ? ref.urls.slice() : [];
    if (!urls.length && (ref.url || ref.path)) {
      pushIdDocumentUrl(urls, {}, ref.url || ref.path);
    }
    if (!urls.length) urls = idDocumentCandidateUrls(root, ref.url || ref.path || '');
    if (!modal || !body) {
      if (urls[0]) {
        try {
          window.open(urls[0], '_blank', 'noopener,noreferrer');
        } catch (err) {}
      } else {
        showToast('No ID document uploaded for this guest.', true);
      }
      return;
    }
    var label = String(ref.name || '').trim();
    if (sub) sub.textContent = label && !storedIdDocumentName(label) ? label : '';
    if (addBtn) addBtn.hidden = !!urls.length;
    if (modal.parentNode !== document.body) {
      modal.__hrdPreviewHome = modal.parentNode;
      document.body.appendChild(modal);
    }
    modal.hidden = false;
    modal.setAttribute('aria-hidden', 'false');
    loadIdDocumentIntoPreview(urls, ref.mime || '');
  }

  function currentStayIdDocumentRef(root, pathOverride) {
    var stay = (lastRoom && lastRoom.stay) || null;
    var form = root && $('#hrd-checkin-form', root);
    var draft = readCheckinDraft(root);
    var draftStay = draft && draft.stay;
    return {
      urls: idDocumentCandidateUrls(root, pathOverride),
      mime:
        (stay && stay.idDocumentMime) ||
        (form && form.elements.idDocumentMime && form.elements.idDocumentMime.value) ||
        (draftStay && draftStay.idDocumentMime) ||
        '',
      name:
        (stay && stay.idDocumentName) ||
        (draftStay && draftStay.idDocumentName) ||
        ''
    };
  }

  function viewIdDocument(form, pathOverride) {
    openIdDocumentPreview(currentStayIdDocumentRef(pageRoot(), pathOverride));
  }

  function persistOccupiedStay(root) {
    root = root || pageRoot();
    if (!root || !lastRoom || !lastRoom.stay) return Promise.resolve();
    if (mapStatus(lastRoom.status || root.getAttribute('data-room-status')) !== 'occupied') {
      return Promise.resolve();
    }
    var api = root.getAttribute('data-room-api') || '';
    if (!api) return Promise.resolve();
    return fetch(api, {
      method: 'PUT',
      credentials: 'same-origin',
      headers: apiHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ action: 'checkin', stay: lastRoom.stay })
    })
      .then(function (resp) {
        return resp.json().then(function (data) {
          return { ok: resp.ok, data: data };
        });
      })
      .then(function (result) {
        if (result.ok && result.data && result.data.ok && result.data.room) {
          paintRoom(root, result.data.room);
        }
      })
      .catch(function () {});
  }

  function uploadIdDocument(root, form, files) {
    files = Array.prototype.slice.call(files || []);
    if (!root || !form || !files.length) {
      return Promise.reject(new Error('missing file'));
    }
    var classified;
    try {
      classified = classifyIdUploadFiles(files);
    } catch (err) {
      showToast(err.message || 'Could not upload ID document.', true);
      return Promise.reject(err);
    }
    var api =
      (root.getAttribute('data-id-document-upload-api') || '').trim() ||
      '/hotel/api/id-documents';
    var uploadBtn = $('#hrd-ci-id-upload-btn', form);
    if (uploadBtn) {
      uploadBtn.classList.add('is-busy');
      uploadBtn.disabled = true;
    }
    var body = new FormData();
    classified.files.forEach(function (file) {
      body.append('file', file, file.name);
    });
    body.append('guestName', checkinGuestFullName(form));
    body.append('idType', checkinIdType(form));
    return fetch(api, {
      method: 'POST',
      credentials: 'same-origin',
      headers: apiHeaders(),
      body: body
    })
      .then(function (resp) {
        return resp.json().then(function (data) {
          return { ok: resp.ok, data: data };
        });
      })
      .then(function (result) {
        if (!result.ok || !result.data || !result.data.ok || !result.data.document) {
          throw new Error(
            (result.data && result.data.error) || 'Upload failed.'
          );
        }
        var primaryLabel = idDocumentDisplayLabel(
          checkinGuestFullName(form),
          checkinIdType(form),
          result.data.document.displayName
        );
        if (primaryLabel) result.data.document.displayName = primaryLabel;
        setIdDocumentUi(form, result.data.document);
        if (lastRoom && lastRoom.stay) {
          lastRoom.stay.idDocumentPath =
            result.data.document.urlPath || result.data.document.storedName || '';
          lastRoom.stay.idDocumentName =
            result.data.document.displayName ||
            result.data.document.originalName ||
            lastRoom.stay.idDocumentName ||
            '';
          lastRoom.stay.idDocumentStoredName = result.data.document.storedName || '';
          lastRoom.stay.idDocumentMime = result.data.document.mime || '';
          paintGuestPanels(pageRoot() || root, lastRoom);
          persistOccupiedStay(pageRoot() || root);
        }
        showToast(idUploadSuccessMessage(result.data.document, classified.images.length));
        scheduleCheckinDraftSave(root, form);
        return result.data.document;
      })
      .catch(function (err) {
        clearIdDocumentFields(form);
        showToast(err.message || 'Could not upload ID document.', true);
        throw err;
      })
      .finally(function () {
        if (uploadBtn) {
          uploadBtn.classList.remove('is-busy');
          uploadBtn.disabled = false;
        }
      });
  }

  function bindIdDocumentUpload(root, form) {
    if (!form || form.getAttribute('data-id-upload-bound') === '1') return;
    form.setAttribute('data-id-upload-bound', '1');
    var btn = $('#hrd-ci-id-upload-btn', form);
    var fileInput =
      form.querySelector('#hrd-ci-id-document') ||
      form.querySelector('input[name="idDocument"]');
    if (btn && fileInput) {
      btn.addEventListener('click', function (event) {
        event.preventDefault();
        event.stopPropagation();
        if (btn.disabled) return;
        try {
          fileInput.click();
        } catch (err) {}
      });
    }
    if (fileInput) {
      fileInput.addEventListener('change', function () {
        var files = fileInput.files;
        if (!files || !files.length) return;
        uploadIdDocument(root, form, files).finally(function () {
          /* Allow re-selecting the same file name later. */
          fileInput.value = '';
        });
      });
    }
  }

  function mealPlanToRatePlan(value) {
    var text = String(value || '').trim();
    if (!text) return '';
    text = text.split(',')[0].trim();
    var first = text.split('·')[0].trim().toUpperCase();
    var map = { EP: 'EP', CP: 'CP', MAP: 'MAP', AP: 'AP', AI: 'AP', BB: 'CP' };
    if (map[first]) return map[first];
    var lowered = text.toLowerCase();
    if (lowered.indexOf('all meal') >= 0 || lowered.indexOf('all inclusive') >= 0) return 'AP';
    if (lowered.indexOf('breakfast') >= 0 && lowered.indexOf('dinner') >= 0) return 'MAP';
    if (lowered.indexOf('breakfast') >= 0) return 'CP';
    if (lowered.indexOf('room only') >= 0) return 'EP';
    return '';
  }

  function refreshCheckinFromReservationApi(root, form, stay, opts) {
    var rid = String(
      (stay && (stay.reservationId || stay.reservation_id || stay.reservationBookingId)) ||
        ''
    ).trim();
    if (!rid || !form || !root) return;
    var editing = !!(opts && opts.editing);
    var preserveForm = !!(opts && opts.preserveForm);
    fetch('/hotel/api/reservations/' + encodeURIComponent(rid), {
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
        if (!result.ok || !result.data || !result.data.ok || !result.data.reservation) {
          return;
        }
        if (!document.body.classList.contains('hrd-checkin-open')) return;
        var res = result.data.reservation;
        var enriched = Object.assign({}, stay || {});
        if (res.id) enriched.reservationId = String(res.id);
        if (res.bookingId || res.id) {
          enriched.reservationBookingId = String(res.bookingId || res.id);
        }
        /* In-progress draft restore: keep typed fields; only sync booking ids. */
        if (preserveForm) {
          syncCheckinReservationIdField(form, enriched);
          return;
        }
        var plan = mealPlanToRatePlan(res.mealPlan || res.meal_plan);
        if (!editing) {
          enriched = stripStayMealPlans(enriched);
        }
        if (plan) {
          enriched.ratePlan = plan;
        }
        var amount = Number(res.amount || 0);
        var nights = Math.max(
          1,
          Number(res.nights || enriched.nights || 1) || 1
        );
        if (amount > 0) {
          enriched.roomRate = Math.round((amount / nights) * 100) / 100;
        }
        var notes = String(res.specialNotes || res.special_notes || '').trim();
        if (notes && !String(enriched.additionalRequests || '').trim()) {
          enriched.additionalRequests = notes;
        }
        if (Array.isArray(enriched.mergeRoomRates) && enriched.mergeRoomRates.length) {
          enriched.mergeRoomRates = enriched.mergeRoomRates.map(function (row) {
            var next = Object.assign({}, row || {});
            if (plan) next.ratePlan = plan;
            if (amount > 0 && next.isPrimary) next.roomRate = enriched.roomRate;
            return next;
          });
        }
        buildCheckinRateRooms(root, form, {
          stay: enriched
        });
        syncCheckinReservationIdField(form, enriched);
        if (
          enriched.additionalRequests &&
          form.elements.additionalRequests &&
          !String(form.elements.additionalRequests.value || '').trim()
        ) {
          form.elements.additionalRequests.value = enriched.additionalRequests;
        }
        scheduleFormFieldAutosize(form);
        syncTotals(form);
        try {
          writeCheckinDraft(root, collectStay(form), { open: true }, form);
        } catch (err) {}
      })
      .catch(function () {});
  }

  function syncCheckinReservationIdField(form, stay) {
    if (!form) return;
    var field = form.querySelector('#hrd-ci-reservation-id-field');
    var input =
      form.elements.reservationBookingId ||
      form.querySelector('#hrd-ci-reservation-id');
    var internal =
      form.elements.reservationId ||
      form.querySelector('#hrd-ci-reservation-id-internal');
    var reservationId = String(
      (stay && (stay.reservationId || stay.reservation_id)) || ''
    ).trim();
    var bookingId = String(
      (stay &&
        (stay.reservationBookingId ||
          stay.reservation_booking_id ||
          stay.bookingId ||
          stay.booking_id)) ||
        ''
    ).trim();
    if (!bookingId) bookingId = reservationId;
    /* Never treat local BK… bookingNumber as the provider reservation id. */
    if (
      bookingId &&
      /^BK\d+/i.test(bookingId) &&
      stay &&
      String(stay.bookingNumber || '') === bookingId
    ) {
      bookingId = reservationId;
    }
    if (internal) internal.value = reservationId;
    if (input) input.value = bookingId;
    if (!field) return;
    var show = !!bookingId;
    setVisible(field, show);
    field.setAttribute('aria-hidden', show ? 'false' : 'true');
  }

  function openAddGuestIdModal(root) {
    root = root || pageRoot();
    var status = mapStatus(
      (lastRoom && lastRoom.status) || (root && root.getAttribute('data-room-status'))
    );
    if (status !== 'occupied') {
      showToast('Check in the guest first to add ID details.', true);
      return;
    }
    openCheckinModal(root, { edit: true, idOnly: true });
  }

  function openCheckinModal(root, opts) {
    opts = opts || {};
    var editing = !!opts.edit;
    var extending = !!opts.extend;
    if (extending) editing = true;
    var staySource =
      opts.stay ||
      (editing && lastRoom && lastRoom.stay ? lastRoom.stay : null);
    if (
      !staySource &&
      lastRoom &&
      lastRoom.stay &&
      mapStatus(lastRoom.status || (root && root.getAttribute('data-room-status'))) ===
        'reserved'
    ) {
      staySource = lastRoom.stay;
    }
    var modal = $('#hrd-checkin-modal', root);
    var form = $('#hrd-checkin-form', root);
    if (!modal || !form) {
      showToast('Check-in form unavailable.', true);
      return;
    }
    if (editing && !staySource) {
      showToast(extending ? 'No guest checked in to extend.' : 'No guest stay to edit.', true);
      return;
    }
    if (!editing) {
      var blocked = checkinBlockedReason(lastRoom, root);
      if (blocked) {
        showToast(blocked, true);
        return;
      }
    }
    form.reset();
    if (form.elements.ratePlan) form.elements.ratePlan.value = '';
    form.setAttribute('data-edit-mode', editing ? '1' : '0');
    form.setAttribute('data-id-only', opts.idOnly ? '1' : '0');
    modal.classList.toggle('is-id-only', !!opts.idOnly);
    var today = todayISO();
    form.bookingNumber.value = 'Auto generated';
    setFormDate(form, 'bookingDate', today);
    setFormDate(form, 'checkInDate', today);
    form.nights.value = '1';
    setFormDate(form, 'checkOutDate', addDaysISO(today, 1));
    form.advancePaid.value = '0';
    setFormDate(form, 'dateOfBirth', '');
    if (form.elements.agencyName) form.elements.agencyName.value = '';
    if (form.elements.agencyGst) form.elements.agencyGst.value = '';
    if (form.elements.agencyAddress) form.elements.agencyAddress.value = '';
    clearFormAgencyBillFlags(form);
    clearAllSpecialCharges(form);
    clearOtherCustomCharges(form);
    clearIdDocumentFields(form);
    clearExtraGuests(form);
    bindAgencyBilling(form);
    syncAgencyBillingHint(form);
    bindMobileGuestLookup(root, form);
    bindCheckinCustomerSuggest(root, form);
    bindAgencyMasterControls(root, form);
    bindFormFieldAutosize(form);
    bindIdDocumentUpload(root, form);
    syncAgencyDatalist(root, parseAgenciesData(root));
    syncCustomerNameFromPersonal(form);
    if (typeof global.initHotelDatePickers === 'function') {
      global.initHotelDatePickers(modal);
    }
    if (typeof global.initHotelTimePickers === 'function') {
      global.initHotelTimePickers(modal);
    }

    resetListbox('hrd-ci-title', '', 'Select');
    resetListbox('hrd-ci-gender', '', 'Select');
    resetListbox('hrd-ci-nationality', 'Indian', 'Indian');
    resetListbox('hrd-ci-mobile-country', '+91', '+91');
    resetListbox('hrd-ci-country', 'India', 'India');
    resetListbox('hrd-ci-purpose', '', 'Select');
    resetListbox('hrd-ci-vip', 'Regular', 'Regular');
    resetListbox('hrd-ci-returning', 'No', 'No');
    resetListbox('hrd-ci-id-type', '', 'Select');
    resetListbox('hrd-ci-adults', '1', '1');
    resetListbox('hrd-ci-children', '0', '0');
    resetListbox('hrd-ci-payment', '', 'Select');
    var stayForRates = staySource;
    if (!editing && stayForRates) {
      stayForRates = stripStayMealPlans(stayForRates);
    }
    buildCheckinRateRooms(root, form, {
      stay: stayForRates || null
    });

    var uploadName = $('#hrd-ci-id-upload-name', form) || $('.hrd-upload-text', form);
    var uploadBtn = $('#hrd-ci-id-upload-btn', form);
    if (uploadName) {
      uploadName.textContent = '';
      uploadName.hidden = true;
    }
    if (uploadBtn) {
      uploadBtn.classList.remove('is-filled', 'is-busy');
      uploadBtn.disabled = false;
      uploadBtn.title = 'Upload ID (PDF, or photos combined into one PDF)';
    }
    if (typeof global.initEpListboxes === 'function') {
      global.initEpListboxes();
    }
    /* Clone-rebind strips stacked click handlers left by soft-nav script upgrades. */
    if (typeof global.rebindEpListbox === 'function') {
      Array.from(modal.querySelectorAll('[data-se-listbox]')).forEach(function (lb) {
        global.rebindEpListbox(lb);
      });
    }
    bindDateChipPickers(modal);

    if (staySource) {
      var resumeDraft = readCheckinDraft(root);
      /* Prefer open draft (refresh) or any new-check-in draft over reserved stay seed. */
      if (
        resumeDraft &&
        resumeDraft.stay &&
        (resumeDraft.open || !editing)
      ) {
        applyStayDraft(
          form,
          !editing ? stripStayMealPlans(resumeDraft.stay) : resumeDraft.stay
        );
      } else {
        applyStayDraft(form, !editing ? stripStayMealPlans(staySource) : staySource);
      }
      if (staySource.bookingNumber && form.bookingNumber) {
        form.bookingNumber.value = staySource.bookingNumber;
      }
    } else {
      var draft = readCheckinDraft(root);
      if (draft && draft.stay) {
        applyStayDraft(form, stripStayMealPlans(draft.stay));
      }
    }

    /* Reserved stay notes win over an empty draft / blank field. */
    if (form.elements.additionalRequests) {
      var currentNotes = String(form.elements.additionalRequests.value || '').trim();
      if (!currentNotes) {
        var reservedStay =
          staySource ||
          (lastRoom &&
          mapStatus(lastRoom.status || root.getAttribute('data-room-status')) ===
            'reserved'
            ? lastRoom.stay
            : null);
        var reservedNotes = String(
          (reservedStay &&
            (reservedStay.additionalRequests ||
              reservedStay.additional_requests ||
              reservedStay.specialNotes ||
              reservedStay.special_notes ||
              reservedStay.notes)) ||
            ''
        ).trim();
        if (reservedNotes) form.elements.additionalRequests.value = reservedNotes;
      }
    }

    var draftForPreserve = readCheckinDraft(root);
    /* Only skip reservation rate refresh when restoring an open draft (page refresh). */
    var preserveForm = !!(
      draftForPreserve &&
      draftForPreserve.open &&
      draftForPreserve.stay
    );

    syncCheckinReservationIdField(
      form,
      staySource ||
        (lastRoom && lastRoom.stay && mapStatus(lastRoom.status) === 'reserved'
          ? lastRoom.stay
          : null)
    );
    refreshCheckinFromReservationApi(
      root,
      form,
      staySource ||
        (lastRoom && lastRoom.stay && mapStatus(lastRoom.status) === 'reserved'
          ? lastRoom.stay
          : null),
      { editing: editing, preserveForm: preserveForm }
    );

    /* New check-in: default to current time (draft/stay may leave it blank). Still editable. */
    if (!editing) {
      var timeInput = form.elements.checkInTime;
      if (!timeInput || !String(timeInput.value || '').trim()) {
        setFormTime(form, 'checkInTime', nowTime());
      }
      var checkOutTimeInput = form.elements.checkOutTime;
      if (!checkOutTimeInput || !String(checkOutTimeInput.value || '').trim()) {
        setFormTime(form, 'checkOutTime', '11:00');
      }
    } else {
      var editOutTime = form.elements.checkOutTime;
      if (editOutTime && !String(editOutTime.value || '').trim()) {
        setFormTime(form, 'checkOutTime', '11:00');
      }
    }

    setInvoiceLockedFormFields(form, staySource || (lastRoom && lastRoom.stay) || null);

    var titleEl = $('#hrd-checkin-title', root);
    if (titleEl) {
      titleEl.textContent = opts.idOnly
        ? 'Add Guest ID'
        : extending
          ? 'Extend Stay'
          : editing
            ? 'Edit Guest'
            : 'New Check-In';
    }
    var saveBtn = $('#hrd-checkin-save', root);
    if (saveBtn) {
      saveBtn.textContent = opts.idOnly
        ? 'Save'
        : extending
          ? 'Save Stay'
          : editing
            ? 'Save Changes'
            : 'Check-In';
    }

    modal.hidden = false;
    modal.removeAttribute('hidden');
    modal.setAttribute('aria-hidden', 'false');
    document.body.classList.add('hrd-checkin-open');
    scheduleFormFieldAutosize(form);
    try {
      writeCheckinDraft(root, collectStay(form), { open: true, edit: editing, idOnly: !!opts.idOnly }, form);
    } catch (err) {}
    if (global.deFullscreen && typeof global.deFullscreen.reinit === 'function') {
      global.deFullscreen.reinit();
    } else if (global.deFullscreen && typeof global.deFullscreen.updateUi === 'function') {
      global.deFullscreen.updateUi();
    }
    setTimeout(function () {
      if (opts.idOnly) {
        var idTypeTrigger =
          form.querySelector('#hrd-ci-id-type-trigger') ||
          form.querySelector('#hrd-ci-id-type [data-se-trigger]');
        if (idTypeTrigger && typeof idTypeTrigger.focus === 'function') {
          idTypeTrigger.focus();
          return;
        }
        var addGuest = form.querySelector('#hrd-ci-add-guest');
        if (addGuest && typeof addGuest.focus === 'function') {
          addGuest.focus();
          return;
        }
      }
      if (extending) {
        var nightsField = form.querySelector('#hrd-ci-nights') || form.elements.nights;
        var outField =
          form.querySelector('#hrd-ci-checkout-date') || form.elements.checkOutDate;
        if (nightsField && typeof nightsField.focus === 'function') {
          nightsField.focus();
          if (typeof nightsField.select === 'function') nightsField.select();
          return;
        }
        if (outField && typeof outField.focus === 'function') {
          outField.focus();
          return;
        }
      }
      var mobile = form.querySelector('#hrd-ci-mobile') || form.elements.mobile;
      if (mobile) mobile.focus();
    }, 40);
  }

  function flushCheckinDraft(root, form, meta) {
    if (checkinDraftTimer) {
      clearTimeout(checkinDraftTimer);
      checkinDraftTimer = null;
    }
    if (checkinDraftApplying || !root || !form) return;
    try {
      writeCheckinDraft(root, collectStay(form), meta || { open: true }, form);
    } catch (err) {}
  }

  function closeCheckinModal(root, opts) {
    opts = opts || {};
    root = root || pageRoot();
    closeSpecialChargeModal(root);
    var modal = root && $('#hrd-checkin-modal', root);
    var form = root && $('#hrd-checkin-form', root);
    if (form && !opts.skipDraft) flushCheckinDraft(root, form, { open: false });
    if (form) {
      form.setAttribute('data-edit-mode', '0');
      form.setAttribute('data-id-only', '0');
    }
    if (!modal) return;
    modal.classList.remove('is-id-only');
    if (typeof global.closeHotelDatePickers === 'function') {
      global.closeHotelDatePickers();
    }
    if (typeof global.closeHotelTimePickers === 'function') {
      global.closeHotelTimePickers();
    }
    if (typeof global.closeAllEpListboxes === 'function') {
      global.closeAllEpListboxes();
    }
    var titleEl = $('#hrd-checkin-title', root);
    if (titleEl) titleEl.textContent = 'New Check-In';
    var saveBtn = $('#hrd-checkin-save', root);
    if (saveBtn) saveBtn.textContent = 'Check-In';
    modal.hidden = true;
    modal.setAttribute('hidden', '');
    modal.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('hrd-checkin-open');
  }

  function closeTransferModal(root) {
    root = root || pageRoot();
    var modal = root && $('#hrd-transfer-modal', root);
    if (!modal) return;
    if (typeof global.closeAllEpListboxes === 'function') {
      global.closeAllEpListboxes();
    }
    modal.hidden = true;
    modal.setAttribute('hidden', '');
    modal.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('hrd-transfer-open');
  }

  function syncExtendNightsLabel(root) {
    root = root || pageRoot();
    var form = root && $('#hrd-extend-form', root);
    var nightsEl = root && $('#hrd-extend-nights', root);
    if (!form || !nightsEl) return;
    var checkIn = form.getAttribute('data-checkin') || '';
    var checkOutInput = $('#hrd-extend-checkout', root);
    var checkOut = toDateISO(checkOutInput && checkOutInput.value);
    var nights = nightsBetweenISO(checkIn, checkOut);
    nightsEl.textContent = nights + (nights === 1 ? ' night' : ' nights');
  }

  function closeExtendModal(root) {
    root = root || pageRoot();
    var modal = root && $('#hrd-extend-modal', root);
    if (!modal) return;
    if (typeof global.closeHotelDatePickers === 'function') {
      global.closeHotelDatePickers();
    }
    modal.hidden = true;
    modal.setAttribute('hidden', '');
    modal.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('hrd-extend-open');
    var form = $('#hrd-extend-form', root);
    if (form) {
      form.removeAttribute('data-checkin');
      form.__hrdExtendStay = null;
    }
  }

  function fillExtendModal(root, room) {
    root = root || pageRoot();
    var modal = root && $('#hrd-extend-modal', root);
    var form = root && $('#hrd-extend-form', root);
    var checkOutInput = root && $('#hrd-extend-checkout', root);
    if (!modal || !form || !checkOutInput) {
      showToast('Extend form unavailable.', true);
      return false;
    }
    var stay = room && room.stay && typeof room.stay === 'object' ? room.stay : null;
    if (mapStatus(room && room.status) !== 'occupied' || !stay) {
      showToast('Check in a guest before extending stay.', true);
      return false;
    }
    var checkIn = toDateISO(stay.checkInDate || stay.check_in_date || '');
    var checkOut = toDateISO(
      stay.checkOutDate || stay.check_out_date || stay.expectedCheckOut || ''
    );
    if (!checkIn) {
      showToast('Check-in date is missing for this stay.', true);
      return false;
    }
    if (!checkOut || checkOut <= checkIn) {
      checkOut = addDaysISO(checkIn, Math.max(1, Number(stay.nights) || 1));
    }
    var roomIdInput = $('#hrd-extend-room-id', root);
    var roomInput = $('#hrd-extend-room', root);
    var guestInput = $('#hrd-extend-guest', root);
    var checkInInput = $('#hrd-extend-checkin', root);
    if (roomIdInput) roomIdInput.value = room.id || root.getAttribute('data-room-id') || '';
    if (roomInput) {
      var typeLabel =
        room.roomTypeLabel ||
        room.roomType ||
        root.getAttribute('data-room-type-label') ||
        '';
      roomInput.value =
        'Room ' +
        (room.number || root.getAttribute('data-room-number') || '') +
        (typeLabel ? ' — ' + typeLabel : '');
    }
    if (guestInput) {
      guestInput.value = dash(
        stay.guestName ||
          stay.guest_name ||
          ((stay.firstName || '') + ' ' + (stay.lastName || '')).trim()
      );
    }
    if (checkInInput) checkInInput.value = prettyDateISO(checkIn);
    form.setAttribute('data-checkin', checkIn);
    form.__hrdExtendStay = Object.assign({}, stay);
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
    syncExtendNightsLabel(root);
    if (checkOutInput.getAttribute('data-hrd-extend-bound') !== '1') {
      checkOutInput.setAttribute('data-hrd-extend-bound', '1');
      checkOutInput.addEventListener('change', function () {
        syncExtendNightsLabel(pageRoot());
      });
    }
    modal.hidden = false;
    modal.removeAttribute('hidden');
    modal.setAttribute('aria-hidden', 'false');
    document.body.classList.add('hrd-extend-open');
    setTimeout(function () {
      try {
        var chip =
          modal.querySelector('#hrd-extend-checkout-chip') || checkOutInput;
        if (chip && typeof chip.focus === 'function') chip.focus();
      } catch (err) {}
    }, 40);
    return true;
  }

  function openExtendModal(root) {
    root = root || pageRoot();
    if (!root) return;
    if (mapStatus(root.getAttribute('data-room-status')) !== 'occupied') {
      showToast('No guest checked in to extend.', true);
      return;
    }
    var source =
      lastRoom && lastRoom.stay
        ? lastRoom
        : {
            id: root.getAttribute('data-room-id') || '',
            number: root.getAttribute('data-room-number') || '',
            status: root.getAttribute('data-room-status') || '',
            stay: null
          };
    if (!(source && source.stay)) {
      showToast('No guest checked in to extend.', true);
      return;
    }
    if (!fillExtendModal(root, source)) return;
    var api = root.getAttribute('data-room-api') || '';
    if (!api) return;
    fetch(api, {
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
        var modal = $('#hrd-extend-modal', root);
        if (!modal || modal.hidden) return;
        lastRoom = result.data.room;
        fillExtendModal(root, result.data.room);
      })
      .catch(function () {});
  }

  function submitExtendForm(root, form) {
    root = root || pageRoot();
    form = form || (root && $('#hrd-extend-form', root));
    if (!root || !form) {
      showToast('Extend form unavailable.', true);
      return Promise.reject(new Error('missing form'));
    }
    var roomId =
      (($('#hrd-extend-room-id', root) || {}).value || '').trim() ||
      root.getAttribute('data-room-id') ||
      '';
    var checkIn = form.getAttribute('data-checkin') || '';
    var checkOutInput = $('#hrd-extend-checkout', root);
    var checkOut = toDateISO(checkOutInput && checkOutInput.value);
    var stay = form.__hrdExtendStay ? Object.assign({}, form.__hrdExtendStay) : null;
    if (!roomId || !stay) {
      showToast('Stay details unavailable.', true);
      return Promise.reject(new Error('missing stay'));
    }
    if (!checkOut) {
      showToast('Choose a check-out date.', true);
      return Promise.reject(new Error('validation'));
    }
    if (!checkIn || checkOut <= checkIn) {
      showToast('Check-out must be after check-in.', true);
      return Promise.reject(new Error('validation'));
    }
    var nights = nightsBetweenISO(checkIn, checkOut);
    stay.checkInDate = checkIn;
    stay.checkOutDate = checkOut;
    stay.nights = nights;
    var api = root.getAttribute('data-room-api') || '';
    if (!api) {
      showToast('Room API unavailable.', true);
      return Promise.reject(new Error('missing api'));
    }
    var saveBtn = $('#hrd-extend-save', root);
    if (saveBtn) saveBtn.disabled = true;
    return fetch(api, {
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
        closeExtendModal(root);
        paintRoom(root, result.data.room);
        showToast(
          'Stay extended to ' +
            prettyDateISO(checkOut) +
            ' (' +
            nights +
            (nights === 1 ? ' night' : ' nights') +
            ').'
        );
        return result.data.room;
      })
      .catch(function (err) {
        if (err.message !== 'validation') {
          showToast(err.message || 'Could not update stay.', true);
        }
        return Promise.reject(err);
      })
      .finally(function () {
        if (saveBtn) saveBtn.disabled = false;
      });
  }

  function closeReserveModal(root) {
    root = root || pageRoot();
    var modal = root && $('#hrd-reserve-modal', root);
    if (!modal) return;
    if (typeof global.closeHotelDatePickers === 'function') {
      global.closeHotelDatePickers();
    }
    var form = $('#hrd-reserve-form', root);
    if (form) {
      form.removeAttribute('data-reserve-mode');
      form.removeAttribute('data-existing-reserve-from');
      form.removeAttribute('data-existing-reserve-to');
    }
    var title = $('#hrd-reserve-title', modal) || $('#hrd-reserve-title', root);
    if (title) title.textContent = 'Reserve Room';
    modal.hidden = true;
    modal.setAttribute('hidden', '');
    modal.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('hrd-reserve-open');
  }

  function setReservePartyPanel(form, party) {
    if (!form) return;
    var want = party === 'agency' ? 'agency' : 'guest';
    var toggle = form.querySelector('#hrd-reserve-party-toggle');
    if (toggle) {
      $all('[data-reserve-party]', toggle).forEach(function (btn) {
        var on = (btn.getAttribute('data-reserve-party') || '') === want;
        btn.classList.toggle('is-active', on);
        btn.setAttribute('aria-selected', on ? 'true' : 'false');
      });
    }
    $all('[data-reserve-panel]', form).forEach(function (panel) {
      var on = (panel.getAttribute('data-reserve-panel') || '') === want;
      if (on) {
        panel.hidden = false;
        panel.removeAttribute('hidden');
      } else {
        panel.hidden = true;
        panel.setAttribute('hidden', '');
      }
    });
  }

  function bindReservePartyToggle(form) {
    if (!form || form.getAttribute('data-reserve-party-bound') === '1') return;
    form.setAttribute('data-reserve-party-bound', '1');
    var toggle = form.querySelector('#hrd-reserve-party-toggle');
    if (!toggle) return;
    toggle.addEventListener('click', function (event) {
      var btn = event.target.closest('[data-reserve-party]');
      if (!btn || !toggle.contains(btn)) return;
      event.preventDefault();
      setReservePartyPanel(form, btn.getAttribute('data-reserve-party') || 'guest');
    });
  }

  function honorificFromToken(token) {
    var m = /^(Mr|Mrs|Ms|Miss|Dr|Mx)\.?$/i.exec(String(token || '').trim());
    if (!m) return '';
    var key = String(m[1] || '').toLowerCase();
    var map = {
      mr: 'Mr',
      mrs: 'Mrs',
      ms: 'Ms',
      miss: 'Ms',
      dr: 'Dr',
      mx: 'Mx'
    };
    return map[key] || '';
  }

  function splitGuestTitlePrefix(full) {
    var text = String(full || '').trim().replace(/\s+/g, ' ');
    if (!text) return { title: '', name: '' };
    var m = /^(Mr|Mrs|Ms|Miss|Dr|Mx)\.?\s+(.+)$/i.exec(text);
    if (!m) return { title: '', name: text };
    return {
      title: honorificFromToken(m[1]),
      name: String(m[2] || '').trim()
    };
  }

  function splitGuestName(fullName) {
    var titled = splitGuestTitlePrefix(fullName);
    var raw = titled.name;
    if (!raw) {
      var onlyTitle = honorificFromToken(fullName);
      if (onlyTitle) {
        return { guestName: '', firstName: '', lastName: '', title: onlyTitle };
      }
      return { guestName: '', firstName: '', lastName: '', title: '' };
    }
    var parts = raw.split(' ');
    return {
      guestName: raw,
      firstName: parts[0] || '',
      lastName: parts.slice(1).join(' '),
      title: titled.title || ''
    };
  }

  /** Recover title / first / last when APIs store "Mr." in firstName or only guestName. */
  function resolveGuestPersonalNames(source) {
    source = source || {};
    var title = honorificFromToken(source.title) || '';
    var first = String(source.firstName || source.first_name || '').trim();
    var last = String(source.lastName || source.last_name || '').trim();
    var guestName = String(
      source.guestName || source.guest_name || source.name || ''
    ).trim();

    var firstWasTitle = false;
    var firstHon = honorificFromToken(first);
    if (firstHon) {
      title = title || firstHon;
      first = '';
      firstWasTitle = true;
    }

    if ((firstWasTitle || (!first && !last)) && guestName) {
      var fromGuest = splitGuestName(guestName);
      title = title || fromGuest.title;
      first = fromGuest.firstName || first;
      last = fromGuest.lastName || last;
    } else if (!firstWasTitle && first) {
      var fromFirst = splitGuestName(first);
      if (fromFirst.title || fromFirst.lastName) {
        title = title || fromFirst.title;
        first = fromFirst.firstName || first;
        if (fromFirst.lastName && !last) last = fromFirst.lastName;
      }
    }

    if (!first && last) {
      var fromLast = splitGuestName(last);
      title = title || fromLast.title;
      first = fromLast.firstName || last;
      last = fromLast.lastName || first;
    } else if (first && !last) {
      last = first;
    }

    if (first && !last) last = first;
    return {
      title: title,
      firstName: first,
      lastName: last || first || ''
    };
  }

  function openReserveModal(root, opts) {
    opts = opts || {};
    var mode = opts.mode === 'new' ? 'new' : 'edit';
    var modal = $('#hrd-reserve-modal', root);
    var form = $('#hrd-reserve-form', root);
    if (!modal || !form) {
      showToast('Reserve form unavailable.', true);
      return;
    }
    var roomStatus = mapStatus(
      (lastRoom && lastRoom.status) || root.getAttribute('data-room-status')
    );
    var occupiedWindow =
      roomStatus === 'occupied' ? existingReservationWindow(lastRoom) : null;
    var upcomingWindow =
      lastRoom && lastRoom.upcomingStay
        ? existingReservationWindow({ stay: lastRoom.upcomingStay })
        : null;

    var today = todayISO();
    var asOf = today;
    var existingWindow =
      roomStatus === 'reserved' ? existingReservationWindow(lastRoom) : null;
    var stay =
      mode === 'new'
        ? null
        : roomStatus === 'occupied'
          ? null
          : lastRoom && lastRoom.stay && typeof lastRoom.stay === 'object'
            ? lastRoom.stay
            : null;
    var fromDate;
    var toDate;
    if (occupiedWindow) {
      /* Queue upcomingStay after the in-house window (inclusive checkout day). */
      fromDate = addDaysISO(occupiedWindow.checkOut, 1);
      if (!fromDate || fromDate < today) fromDate = addDaysISO(today, 1);
      if (upcomingWindow) {
        var afterUpcoming = addDaysISO(upcomingWindow.checkOut, 1);
        if (afterUpcoming && afterUpcoming > fromDate) fromDate = afterUpcoming;
      }
      toDate = addDaysISO(fromDate, 1);
      mode = 'new';
    } else if (mode === 'new' && existingWindow) {
      /* Start after the current reserved window so New Reservation is not the same dates. */
      fromDate = addDaysISO(existingWindow.checkOut, 1);
      if (asOf && asOf > fromDate) fromDate = asOf;
      toDate = addDaysISO(fromDate, 1);
    } else {
      fromDate =
        toDateISO(stay && (stay.checkInDate || stay.check_in_date)) || asOf;
      toDate =
        toDateISO(stay && (stay.checkOutDate || stay.check_out_date)) ||
        addDaysISO(fromDate, 1);
    }
    if (toDate && fromDate && toDate <= fromDate) {
      toDate = addDaysISO(fromDate, 1);
    }

    form.setAttribute('data-reserve-mode', mode);
    if (occupiedWindow) {
      form.setAttribute('data-occupied-reserve-from', occupiedWindow.checkIn);
      form.setAttribute('data-occupied-reserve-to', occupiedWindow.checkOut);
    } else {
      form.removeAttribute('data-occupied-reserve-from');
      form.removeAttribute('data-occupied-reserve-to');
    }
    if (existingWindow) {
      form.setAttribute('data-existing-reserve-from', existingWindow.checkIn);
      form.setAttribute('data-existing-reserve-to', existingWindow.checkOut);
    } else {
      form.removeAttribute('data-existing-reserve-from');
      form.removeAttribute('data-existing-reserve-to');
    }
    setFormDate(form, 'reserveFrom', fromDate);
    setFormDate(form, 'reserveTo', toDate);

    function applyReserveBlockedDates() {
      var fromInput = form.elements.reserveFrom || $('#hrd-reserve-from', form);
      var toInput = form.elements.reserveTo || $('#hrd-reserve-to', form);
      var blocked = [];
      if (occupiedWindow) {
        blocked.push({ from: occupiedWindow.checkIn, to: occupiedWindow.checkOut });
      }
      if (mode === 'new' && existingWindow) {
        blocked.push({ from: existingWindow.checkIn, to: existingWindow.checkOut });
      }
      if (upcomingWindow && !occupiedWindow) {
        blocked.push({ from: upcomingWindow.checkIn, to: upcomingWindow.checkOut });
      }
      if (typeof global.setHotelDateBlockedRanges === 'function') {
        global.setHotelDateBlockedRanges(fromInput, blocked);
        global.setHotelDateBlockedRanges(toInput, blocked);
      } else {
        [fromInput, toInput].forEach(function (input) {
          if (!input) return;
          var chip = input.closest('[data-hotel-date]');
          if (!chip) return;
          if (blocked.length) {
            chip.setAttribute(
              'data-blocked-ranges',
              blocked
                .map(function (row) {
                  return row.from + ':' + row.to;
                })
                .join(',')
            );
          } else {
            chip.removeAttribute('data-blocked-ranges');
          }
        });
      }
      if (occupiedWindow) {
        [fromInput, toInput].forEach(function (input, idx) {
          if (!input) return;
          var chip = input.closest('[data-hotel-date]');
          if (!chip) return;
          chip.setAttribute(
            'data-min-date',
            idx === 0 ? fromDate : addDaysISO(fromDate, 1)
          );
        });
      } else {
        [fromInput, toInput].forEach(function (input) {
          if (!input) return;
          var chip = input.closest('[data-hotel-date]');
          if (chip) chip.removeAttribute('data-min-date');
        });
      }
    }
    applyReserveBlockedDates();

    var guestName =
      occupiedWindow
        ? ''
        : (stay && (stay.guestName || stay.guest_name)) ||
          [stay && stay.firstName, stay && stay.lastName].filter(Boolean).join(' ').trim() ||
          '';
    setFormText(form, 'guestName', guestName);
    var mobileSeed = occupiedWindow
      ? ''
      : String((stay && stay.mobile) || '').replace(/\D/g, '').slice(0, 10);
    setFormText(form, 'mobile', mobileSeed);
    setFormText(form, 'email', occupiedWindow ? '' : (stay && stay.email) || '');
    setFormText(form, 'agencyName', occupiedWindow ? '' : (stay && stay.agencyName) || '');
    setFormText(form, 'agencyGst', occupiedWindow ? '' : (stay && stay.agencyGst) || '');
    setFormText(
      form,
      'agencyAddress',
      occupiedWindow ? '' : (stay && stay.agencyAddress) || ''
    );
    setFormText(
      form,
      'additionalRequests',
      occupiedWindow
        ? ''
        : (stay &&
            (stay.additionalRequests ||
              stay.additional_requests ||
              stay.specialNotes ||
              stay.special_notes ||
              stay.notes)) ||
          ''
    );
    setFormAgencyBillFlags(form, occupiedWindow ? null : stay);

    var title = $('#hrd-reserve-title', modal) || $('#hrd-reserve-title', root);
    if (title) {
      title.textContent = occupiedWindow
        ? 'Reserve Future Stay'
        : mode === 'new'
          ? 'New Reservation'
          : 'Reserve Room';
    }

    bindDateChipPickers(modal);
    applyReserveBlockedDates();
    bindAgencyBilling(form);
    bindAgencyMasterControls(root, form);
    bindFormFieldAutosize(form);
    bindReservePartyToggle(form);
    bindReserveCustomerSuggest(root, form);
    syncAgencyBillingHint(form);
    syncReserveSaveEnabled(root, form);
    var preferAgency = !!(
      stay &&
      String(stay.agencyName || '').trim() &&
      !guestName
    );
    setReservePartyPanel(form, preferAgency ? 'agency' : 'guest');

    modal.hidden = false;
    modal.removeAttribute('hidden');
    modal.setAttribute('aria-hidden', 'false');
    document.body.classList.add('hrd-reserve-open');
    scheduleFormFieldAutosize(form);
    setTimeout(function () {
      var mobileFocus = $('#hrd-reserve-mobile', form);
      if (mobileFocus && !preferAgency) mobileFocus.focus();
    }, 30);
  }

  function submitReservation(root, form) {
    var api = root.getAttribute('data-room-api') || '';
    if (!api) {
      showToast('Room API unavailable.', true);
      return;
    }
    var mobile = reserveMobileDigits(form);
    if (form.elements.mobile) form.elements.mobile.value = mobile;
    syncReserveSaveEnabled(root, form);
    if (mobile.length !== 10) {
      showToast('Mobile number must be exactly 10 digits.', true);
      if (form.elements.mobile) form.elements.mobile.focus();
      return;
    }
    var fromInput = form.elements.reserveFrom || $('#hrd-reserve-from', root);
    var toInput = form.elements.reserveTo || $('#hrd-reserve-to', root);
    var checkInDate = toDateISO(fromInput && fromInput.value);
    var checkOutDate = toDateISO(toInput && toInput.value);
    if (!checkInDate) {
      showToast('From date is required.', true);
      return;
    }
    if (!checkOutDate) {
      checkOutDate = addDaysISO(checkInDate, 1);
    }
    if (checkOutDate <= checkInDate) {
      showToast('To date must be after from date.', true);
      return;
    }

    var occupiedFrom = form.getAttribute('data-occupied-reserve-from') || '';
    var occupiedTo = form.getAttribute('data-occupied-reserve-to') || '';
    if (
      occupiedFrom &&
      occupiedTo &&
      reservationRangesOverlap(checkInDate, checkOutDate, occupiedFrom, occupiedTo)
    ) {
      showToast(
        "Room is occupied for these dates. Choose dates after the current guest's checkout.",
        true
      );
      return;
    }
    var roomStatusNow = mapStatus(
      (lastRoom && lastRoom.status) || root.getAttribute('data-room-status')
    );
    if (roomStatusNow === 'occupied' && checkInDate <= todayISO()) {
      showToast('For an occupied room, reserve a future check-in date only.', true);
      return;
    }

    var guestRaw = form.elements.guestName
      ? String(form.elements.guestName.value || '').trim()
      : '';
    var email = form.elements.email ? String(form.elements.email.value || '').trim() : '';
    if (!guestRaw) {
      showToast('Guest name is required.', true);
      return;
    }

    var names = splitGuestName(guestRaw);
    var agencyName = form.elements.agencyName
      ? String(form.elements.agencyName.value || '').trim()
      : '';
    var agencyGst = form.elements.agencyGst
      ? String(form.elements.agencyGst.value || '').trim()
      : '';
    var agencyAddress = form.elements.agencyAddress
      ? String(form.elements.agencyAddress.value || '').trim()
      : '';
    var agencyFlags = formAgencyBillFlags(form);
    if ((agencyFlags.room || agencyFlags.fb) && !agencyName) {
      showToast('Agency name is required for agency billing.', true);
      return;
    }
    var reserveGstError = agencyGstValidationError(form);
    if (reserveGstError) {
      showToast(reserveGstError, true);
      var reserveGstInput = form.elements.agencyGst;
      if (reserveGstInput) {
        try {
          reserveGstInput.focus();
          reserveGstInput.select();
        } catch (err) {}
      }
      return;
    }
    agencyGst = normalizeGstin(agencyGst);

    var replaceMode = form.getAttribute('data-reserve-mode') === 'new';
    var roomStatus = mapStatus(
      (lastRoom && lastRoom.status) || root.getAttribute('data-room-status')
    );
    var existingFrom =
      form.getAttribute('data-existing-reserve-from') ||
      (existingReservationWindow(lastRoom) || {}).checkIn ||
      '';
    var existingTo =
      form.getAttribute('data-existing-reserve-to') ||
      (existingReservationWindow(lastRoom) || {}).checkOut ||
      '';
    if (
      replaceMode &&
      roomStatus === 'reserved' &&
      reservationRangesOverlap(checkInDate, checkOutDate, existingFrom, existingTo)
    ) {
      showToast(
        'These dates are already reserved. Use Edit Reservation to change the guest, or pick dates after the current stay.',
        true
      );
      return;
    }
    if (replaceMode && roomStatus === 'reserved') {
      var okReplace = global.confirm(
        'This will clear the current reservation and save a new one for different dates. Continue?'
      );
      if (!okReplace) return;
    }

    var additionalRequests = form.elements.additionalRequests
      ? String(form.elements.additionalRequests.value || '').trim()
      : '';

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
      agencyRoomBilling: agencyFlags.room,
      agencyFbBilling: agencyFlags.fb,
      agencyBilling: !!(agencyFlags.room || agencyFlags.fb),
      additionalRequests: additionalRequests
    };
    if (agencyFlags.room && agencyName) {
      stay.invoiceTo = agencyName;
      stay.billingName = agencyName;
    }

    var saveBtn = $('#hrd-reserve-save', root);
    if (saveBtn) saveBtn.disabled = true;

    fetch(api, {
      method: 'PUT',
      credentials: 'same-origin',
      headers: apiHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({
        action: 'reserve',
        checkInDate: checkInDate,
        checkOutDate: checkOutDate,
        replace: !!replaceMode,
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
          throw new Error((result.data && result.data.error) || 'Failed to reserve room.');
        }
        form.removeAttribute('data-reserve-mode');
        closeReserveModal(root);
        paintRoom(root, result.data.room);
        var savedStatus = mapStatus(
          (result.data.room && result.data.room.status) || roomStatus
        );
        showToast(
          savedStatus === 'occupied' && result.data.room && result.data.room.upcomingStay
            ? 'Future stay reserved.'
            : replaceMode
              ? 'Reservation replaced.'
              : 'Room reserved.'
        );
      })
      .catch(function (err) {
        showToast(err.message || 'Failed to reserve room.', true);
      })
      .then(function () {
        syncReserveSaveEnabled(root, form);
      });
  }

  function fillVacantRoomOptions(listboxRoot, rooms, currentId) {
    if (!listboxRoot) return 0;
    var optionsWrap =
      listboxRoot.querySelector('.ep-listbox-options') ||
      listboxRoot.querySelector('.se-filter-listbox');
    if (!optionsWrap) return 0;

    var vacant = (rooms || [])
      .filter(function (room) {
        if (!room || !room.id) return false;
        if (String(room.id) === String(currentId)) return false;
        return mapStatus(room.status) === 'vacant';
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
      resetListbox('hrd-transfer-to', '', 'No vacant rooms available');
      return 0;
    }

    addOption('', 'Select vacant room', true);
    vacant.forEach(function (room) {
      var label =
        'Room ' +
        (room.number || '') +
        (room.roomTypeLabel ? ' — ' + room.roomTypeLabel : '');
      addOption(room.id, label, false);
    });
    resetListbox('hrd-transfer-to', '', 'Select vacant room');
    return vacant.length;
  }

  function openTransferModal(root) {
    var modal = $('#hrd-transfer-modal', root);
    var form = $('#hrd-transfer-form', root);
    if (!modal || !form) {
      showToast('Transfer form unavailable.', true);
      return;
    }
    if (mapStatus(root.getAttribute('data-room-status')) !== 'occupied') {
      showToast('Check in a guest before transferring rooms.', true);
      return;
    }

    var number = root.getAttribute('data-room-number') || '';
    var typeLabel = root.getAttribute('data-room-type-label') || '';
    var fromInput = $('#hrd-transfer-from', root);
    if (fromInput) {
      fromInput.value =
        'Room ' + number + (typeLabel ? ' — ' + typeLabel : '');
    }
    var guestInput = $('#hrd-transfer-guest', root);
    var stay = (lastRoom && lastRoom.stay) || null;
    if (guestInput) {
      guestInput.value = stay
        ? dash(stay.guestName || (stay.firstName + ' ' + stay.lastName).trim())
        : '—';
    }
    var note = $('#hrd-transfer-note', root);
    if (note) note.value = '';
    var hint = $('#hrd-transfer-hint', root);
    resetListbox('hrd-transfer-to', '', 'Loading vacant rooms…');
    if (hint) {
      if (lastRoom && (lastRoom.isMergeMember || lastRoom.isMergePrimary)) {
        var billHint = lastRoom.isMergePrimary
          ? 'This is the billing primary — transfer keeps shared billing and remaps merged rooms.'
          : 'This room is merged with Room ' +
            (lastRoom.billingRoomNumber || '—') +
            ' — transfer will keep shared billing.';
        hint.textContent = billHint + ' Only vacant rooms are listed.';
      } else {
        hint.textContent = 'Only vacant rooms are listed.';
      }
      hint.classList.remove('is-error');
    }

    if (typeof global.initEpListboxes === 'function') {
      global.initEpListboxes();
    }
    if (typeof global.rebindEpListbox === 'function') {
      Array.from(modal.querySelectorAll('[data-se-listbox]')).forEach(function (lb) {
        global.rebindEpListbox(lb);
      });
    }
    /* Re-query after clone-rebind so option fills target the live node. */
    var listbox = $('#hrd-transfer-to-listbox', root);

    modal.hidden = false;
    modal.removeAttribute('hidden');
    modal.setAttribute('aria-hidden', 'false');
    document.body.classList.add('hrd-transfer-open');

    var roomsApi = root.getAttribute('data-rooms-api') || '/hotel/api/rooms';
    var currentId = root.getAttribute('data-room-id') || '';
    fetch(roomsApi, {
      method: 'GET',
      credentials: 'same-origin',
      headers: apiHeaders()
    })
      .then(function (resp) {
        return resp.json();
      })
      .then(function (data) {
        if (!data || !data.ok) {
          throw new Error((data && data.error) || 'Could not load rooms.');
        }
        var count = fillVacantRoomOptions(listbox, data.rooms || [], currentId);
        if (hint) {
          if (!count) {
            hint.textContent = 'No vacant rooms available for transfer.';
            hint.classList.add('is-error');
          } else {
            hint.textContent =
              count + ' vacant room' + (count === 1 ? '' : 's') + ' available.';
            hint.classList.remove('is-error');
          }
        }
        var trigger = listbox && listbox.querySelector('.se-filter-chip-trigger');
        if (trigger) trigger.focus();
      })
      .catch(function (err) {
        resetListbox('hrd-transfer-to', '', 'Could not load rooms');
        if (hint) {
          hint.textContent = err.message || 'Could not load vacant rooms.';
          hint.classList.add('is-error');
        }
        showToast(err.message || 'Could not load vacant rooms.', true);
      });
  }

  function submitTransfer(root, form) {
    var toRoomId = (form.toRoomId && form.toRoomId.value) || '';
    if (!toRoomId) {
      showToast('Select a vacant room to transfer to.', true);
      return Promise.reject(new Error('validation'));
    }
    var api = root.getAttribute('data-room-api') || '';
    if (!api) {
      showToast('Room API unavailable.', true);
      return Promise.reject(new Error('missing api'));
    }
    var saveBtn = $('#hrd-transfer-save', root);
    if (saveBtn) saveBtn.disabled = true;
    var note = (form.note && form.note.value) || '';

    return fetch(api, {
      method: 'PUT',
      credentials: 'same-origin',
      headers: apiHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({
        action: 'transfer',
        toRoomId: toRoomId,
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
        closeTransferModal(root);
        var toRoom = result.data.toRoom || result.data.room;
        var toNumber = (toRoom && toRoom.number) || '';
        showToast(
          'Guest transferred to Room ' + (toNumber || toRoomId) + '.'
        );
        if (toRoom && toRoom.id) {
          navigateTo('/hotel/rooms/' + encodeURIComponent(toRoom.id));
        } else {
          paintRoom(root, result.data.fromRoom || { status: 'dirty' });
        }
        return result.data;
      })
      .catch(function (err) {
        if (err.message !== 'validation') {
          showToast(err.message || 'Transfer failed.', true);
        }
        throw err;
      })
      .finally(function () {
        if (saveBtn) saveBtn.disabled = false;
      });
  }

  function closeMergeModal(root) {
    var form = root && $('#hrd-merge-form', root);
    closeHrdMergeRoomsMenu(root, form);
    var modal = root && $('#hrd-merge-modal', root);
    if (!modal) return;
    modal.hidden = true;
    modal.setAttribute('hidden', '');
    modal.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('hrd-merge-open');
  }

  function hrdMergeSelectedIds(form) {
    if (!form) return [];
    var raw = form.getAttribute('data-selected-room-ids') || '';
    if (!raw) return [];
    return raw
      .split(',')
      .map(function (id) {
        return String(id || '').trim();
      })
      .filter(Boolean);
  }

  function setHrdMergeSelectedIds(form, ids) {
    if (!form) return;
    var unique = [];
    (ids || []).forEach(function (id) {
      var key = String(id || '').trim();
      if (key && unique.indexOf(key) === -1) unique.push(key);
    });
    form.setAttribute('data-selected-room-ids', unique.join(','));
  }

  function hrdMergeRoomOptionLabel(room) {
    var number = room.number || room.roomNumber || room.id || '';
    var typeLabel = room.roomTypeLabel || room.roomType || '';
    var status = STATUS_LABELS[mapStatus(room.status)] || '';
    var bits = ['Room ' + number];
    if (typeLabel) bits.push(typeLabel);
    if (status) bits.push(status);
    if (room.isMergePrimary) bits.push('primary');
    return bits.join(' · ');
  }

  function hrdMergeRoomsSelectionSummary(form, roomsCache) {
    var selected = hrdMergeSelectedIds(form);
    if (!selected.length) return '';
    var rooms = roomsCache || [];
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

  function syncHrdMergeRoomsTriggerLabel(root, form) {
    var search = $('#hrd-merge-rooms-search', root);
    var menu = $('#hrd-merge-rooms-menu', root);
    if (!search) return;
    var menuOpen = !!(menu && !menu.hidden);
    if (menuOpen && search.getAttribute('data-searching') === '1') return;
    var optionsEl = $('#hrd-merge-rooms-options', root);
    var roomsCache = (optionsEl && optionsEl.__mergeAvailableRooms) || [];
    var summary = hrdMergeRoomsSelectionSummary(form, roomsCache);
    search.value = summary;
    search.classList.toggle('is-placeholder', !summary);
    search.placeholder = 'Select rooms…';
  }

  function syncHrdMergeSaveEnabled(root, form) {
    var saveBtn = $('#hrd-merge-save', root);
    if (!saveBtn) return;
    var ok = hrdMergeSelectedIds(form).length > 0;
    saveBtn.disabled = !ok;
    saveBtn.setAttribute('aria-disabled', ok ? 'false' : 'true');
    if (ok) saveBtn.removeAttribute('title');
    else saveBtn.title = 'Select rooms to merge';
  }

  function closeHrdMergeRoomsMenu(root, form) {
    var wrap = $('#hrd-merge-rooms-select', root);
    var trigger = $('#hrd-merge-rooms-trigger', root);
    var menu = $('#hrd-merge-rooms-menu', root);
    var search = $('#hrd-merge-rooms-search', root);
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
    syncHrdMergeRoomsTriggerLabel(root, form || $('#hrd-merge-form', root));
    applyHrdMergeRoomsSearchFilter(root);
  }

  function openHrdMergeRoomsMenu(root, opts) {
    opts = opts || {};
    var wrap = $('#hrd-merge-rooms-select', root);
    var trigger = $('#hrd-merge-rooms-trigger', root);
    var menu = $('#hrd-merge-rooms-menu', root);
    var search = $('#hrd-merge-rooms-search', root);
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
    applyHrdMergeRoomsSearchFilter(root);
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

  function applyHrdMergeRoomsSearchFilter(root) {
    var optionsEl = $('#hrd-merge-rooms-options', root);
    var emptyEl = $('#hrd-merge-rooms-empty', root);
    var search = $('#hrd-merge-rooms-search', root);
    var menu = $('#hrd-merge-rooms-menu', root);
    if (!optionsEl) return;
    var query = '';
    if (search && menu && !menu.hidden && search.getAttribute('data-searching') === '1') {
      query = normalize(search.value);
    }
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
      var show = true;
      if (query && room) {
        var label = normalize(hrdMergeRoomOptionLabel(room));
        var number = normalize(room.number || room.roomNumber || '');
        var typeLabel = normalize(room.roomTypeLabel || room.roomType || '');
        show =
          label.indexOf(query) !== -1 ||
          number.indexOf(query) !== -1 ||
          typeLabel.indexOf(query) !== -1 ||
          normalize(room.id || '').indexOf(query) !== -1;
      } else if (query && !room) {
        show = false;
      }
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

  function fillMergeRoomOptions(root, form, rooms, currentId) {
    var optionsEl = $('#hrd-merge-rooms-options', root);
    var emptyEl = $('#hrd-merge-rooms-empty', root);
    if (!optionsEl) return 0;
    var selected = hrdMergeSelectedIds(form);
    var available = (rooms || []).filter(function (room) {
      if (!room) return false;
      if (String(room.id) === String(currentId)) return false;
      if (room.isMergeMember) return false;
      return true;
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
    setHrdMergeSelectedIds(form, keep);
    optionsEl.__mergeAvailableRooms = available;
    if (!available.length) {
      optionsEl.innerHTML = '';
      if (emptyEl) {
        emptyEl.textContent = 'No rooms available to merge.';
        emptyEl.hidden = false;
        emptyEl.removeAttribute('hidden');
      }
      syncHrdMergeRoomsTriggerLabel(root, form);
      syncHrdMergeSaveEnabled(root, form);
      return 0;
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
          escapeHtml(hrdMergeRoomOptionLabel(room)) +
          '</span></label>'
        );
      })
      .join('');
    applyHrdMergeRoomsSearchFilter(root);
    syncHrdMergeRoomsTriggerLabel(root, form);
    syncHrdMergeSaveEnabled(root, form);
    return available.length;
  }

  function bindHrdMergeRoomsMultiSelect(root, form) {
    if (!form || form.getAttribute('data-merge-rooms-bound') === '1') return;
    form.setAttribute('data-merge-rooms-bound', '1');
    form.addEventListener('change', function (event) {
      var input = event.target;
      if (!input || input.type !== 'checkbox') return;
      if (!input.closest('#hrd-merge-rooms-options')) return;
      var selected = hrdMergeSelectedIds(form);
      var id = String(input.value || '');
      var idx = selected.indexOf(id);
      if (input.checked && idx === -1) selected.push(id);
      if (!input.checked && idx !== -1) selected.splice(idx, 1);
      setHrdMergeSelectedIds(form, selected);
      var row = input.closest('.hr-board-rooms-option');
      if (row) {
        row.classList.toggle('is-selected', !!input.checked);
        row.setAttribute('aria-selected', input.checked ? 'true' : 'false');
      }
      var search = $('#hrd-merge-rooms-search', root);
      if (!(search && search.getAttribute('data-searching') === '1')) {
        syncHrdMergeRoomsTriggerLabel(root, form);
      }
      syncHrdMergeSaveEnabled(root, form);
    });
    var search = $('#hrd-merge-rooms-search', root);
    if (search && search.getAttribute('data-bound') !== '1') {
      search.setAttribute('data-bound', '1');
      search.addEventListener('focus', function () {
        openHrdMergeRoomsMenu(root, { clearForSearch: true, focus: false });
      });
      search.addEventListener('click', function (event) {
        event.stopPropagation();
        openHrdMergeRoomsMenu(root, { clearForSearch: true, focus: false });
      });
      search.addEventListener('input', function () {
        search.setAttribute('data-searching', '1');
        search.classList.toggle('is-placeholder', !String(search.value || '').trim());
        openHrdMergeRoomsMenu(root, { clearForSearch: false, focus: false });
        applyHrdMergeRoomsSearchFilter(root);
      });
      search.addEventListener('keydown', function (event) {
        if (event.key === 'Escape') {
          event.preventDefault();
          event.stopPropagation();
          closeHrdMergeRoomsMenu(root, form);
          search.blur();
        } else if (event.key === 'ArrowDown') {
          event.preventDefault();
          openHrdMergeRoomsMenu(root, { clearForSearch: false, focus: false });
        }
      });
    }
    var trigger = $('#hrd-merge-rooms-trigger', root);
    if (trigger && trigger.getAttribute('data-chevron-bound') !== '1') {
      trigger.setAttribute('data-chevron-bound', '1');
      trigger.addEventListener('click', function (event) {
        if (event.target && event.target.closest('#hrd-merge-rooms-search')) return;
        event.preventDefault();
        event.stopPropagation();
        var menu = $('#hrd-merge-rooms-menu', root);
        if (menu && !menu.hidden) closeHrdMergeRoomsMenu(root, form);
        else openHrdMergeRoomsMenu(root, { clearForSearch: true });
      });
    }
  }

  function openMergeModal(root) {
    var modal = $('#hrd-merge-modal', root);
    var form = $('#hrd-merge-form', root);
    if (!modal || !form) {
      showToast('Merge form unavailable.', true);
      return;
    }
    if (lastRoom && lastRoom.isMergeMember) {
      showToast('This room is already a merge member. Unmerge first.', true);
      return;
    }
    bindHrdMergeRoomsMultiSelect(root, form);
    var number = root.getAttribute('data-room-number') || '';
    var typeLabel =
      (lastRoom && (lastRoom.roomTypeLabel || lastRoom.roomType)) || '';
    var primaryInput = $('#hrd-merge-primary', root);
    if (primaryInput) {
      primaryInput.value =
        'Room ' + number + (typeLabel ? ' — ' + typeLabel : '');
    }
    var note = $('#hrd-merge-note', root);
    if (note) note.value = '';
    setHrdMergeSelectedIds(form, []);
    syncHrdMergeSaveEnabled(root, form);
    var optionsEl = $('#hrd-merge-rooms-options', root);
    if (optionsEl) optionsEl.innerHTML = '';
    var emptyEl = $('#hrd-merge-rooms-empty', root);
    if (emptyEl) {
      emptyEl.textContent = 'Loading rooms…';
      emptyEl.hidden = false;
      emptyEl.removeAttribute('hidden');
    }
    syncHrdMergeRoomsTriggerLabel(root, form);
    modal.hidden = false;
    modal.removeAttribute('hidden');
    modal.setAttribute('aria-hidden', 'false');
    document.body.classList.add('hrd-merge-open');

    var roomsApi = root.getAttribute('data-rooms-api') || '/hotel/api/rooms';
    var currentId = root.getAttribute('data-room-id') || '';
    fetch(roomsApi, {
      method: 'GET',
      credentials: 'same-origin',
      headers: apiHeaders()
    })
      .then(function (resp) {
        return resp.json();
      })
      .then(function (data) {
        if (!data || !data.ok) {
          throw new Error((data && data.error) || 'Could not load rooms.');
        }
        var count = fillMergeRoomOptions(root, form, data.rooms || [], currentId);
        if (!count) {
          showToast('No other rooms available to merge.', true);
        }
      })
      .catch(function (err) {
        if (emptyEl) {
          emptyEl.textContent = err.message || 'Could not load rooms.';
          emptyEl.hidden = false;
          emptyEl.removeAttribute('hidden');
        }
        showToast(err.message || 'Could not load rooms.', true);
      });
  }

  function submitMerge(root, form) {
    var primaryId = root.getAttribute('data-room-id') || '';
    var roomIds = hrdMergeSelectedIds(form);
    if (!primaryId || !roomIds.length) {
      showToast('Select at least one room to merge.', true);
      return Promise.reject(new Error('validation'));
    }
    var saveBtn = $('#hrd-merge-save', root);
    if (saveBtn) saveBtn.disabled = true;
    closeHrdMergeRoomsMenu(root, form);
    var note = (form.note && form.note.value) || '';
    var chain = Promise.resolve();
    var mergedCount = 0;
    var lastPrimary = null;
    roomIds.forEach(function (fromId) {
      chain = chain.then(function () {
        return fetch('/hotel/api/rooms/' + encodeURIComponent(fromId), {
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
            lastPrimary =
              result.data.primaryRoom || result.data.room || lastPrimary;
          });
      });
    });
    return chain
      .then(function () {
        closeMergeModal(root);
        var primary = lastPrimary;
        showToast(
          mergedCount === 1
            ? 'Rooms merged. Billing is on Room ' +
                ((primary && primary.number) ||
                  root.getAttribute('data-room-number') ||
                  primaryId) +
                '.'
            : mergedCount +
                ' rooms merged. Billing is on Room ' +
                ((primary && primary.number) ||
                  root.getAttribute('data-room-number') ||
                  primaryId) +
                '.'
        );
        if (primary) {
          paintRoom(root, primary);
        } else {
          return loadRoomIfNeeded(root);
        }
        return primary;
      })
      .catch(function (err) {
        if (err.message !== 'validation') {
          showToast(err.message || 'Merge failed.', true);
        }
        throw err;
      })
      .finally(function () {
        syncHrdMergeSaveEnabled(root, form);
      });
  }

  function unmergeRoom(root, scope) {
    var api = root.getAttribute('data-room-api') || '';
    if (!api) {
      showToast('Room API unavailable.', true);
      return Promise.reject(new Error('missing api'));
    }
    var scopeKey = scope === 'group' ? 'group' : 'one';
    var msg =
      scopeKey === 'group'
        ? 'Unmerge all rooms in this billing group? Each room will bill on its own.'
        : 'Unmerge this room from the shared bill? This room will bill on its own.';
    if (!global.confirm(msg)) return Promise.resolve(null);
    return fetch(api, {
      method: 'PUT',
      credentials: 'same-origin',
      headers: apiHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ action: 'unmerge_rooms', scope: scopeKey })
    })
      .then(function (resp) {
        return resp.json().then(function (data) {
          return { ok: resp.ok, data: data };
        });
      })
      .then(function (result) {
        if (!result.ok || !result.data || !result.data.ok) {
          throw new Error((result.data && result.data.error) || 'Unmerge failed.');
        }
        paintRoom(root, result.data.room);
        showToast('Rooms unmerged.');
        return result.data.room;
      })
      .catch(function (err) {
        showToast(err.message || 'Unmerge failed.', true);
        throw err;
      });
  }

  function setMergePrimary(root) {
    var api = root.getAttribute('data-room-api') || '';
    if (!api) {
      showToast('Room API unavailable.', true);
      return Promise.reject(new Error('missing api'));
    }
    if (
      !global.confirm(
        'Make this room the billing primary? The shared folio and invoice will move here.'
      )
    ) {
      return Promise.resolve(null);
    }
    return fetch(api, {
      method: 'PUT',
      credentials: 'same-origin',
      headers: apiHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ action: 'set_merge_primary' })
    })
      .then(function (resp) {
        return resp.json().then(function (data) {
          return { ok: resp.ok, data: data };
        });
      })
      .then(function (result) {
        if (!result.ok || !result.data || !result.data.ok) {
          throw new Error((result.data && result.data.error) || 'Could not change primary.');
        }
        paintRoom(root, result.data.room);
        showToast('This room is now the billing primary.');
        return result.data.room;
      })
      .catch(function (err) {
        showToast(err.message || 'Could not change primary.', true);
        throw err;
      });
  }

  function collectStay(form) {
    var special = $all('input[name="specialRequests"]:checked', form).map(function (el) {
      return el.value;
    });
    var stored =
      (form.elements.idDocumentStoredName && form.elements.idDocumentStoredName.value) ||
      '';
    var displayNameEl = $('#hrd-ci-id-upload-name', form);
    var displayName = displayNameEl
      ? String(displayNameEl.textContent || '').split(' · ')[0].trim()
      : '';
    var docPath =
      idDocumentViewUrl(val('idDocumentPath')) ||
      idDocumentViewUrl(stored) ||
      idDocumentViewUrl(displayName);
    var docLabel = idDocumentDisplayLabel(
      {
        firstName: val('firstName'),
        lastName: val('lastName'),
        guestName: val('idNumber')
      },
      val('idType'),
      displayName || stored
    );

    function val(name) {
      var el = form.elements[name];
      if (!el) {
        el = form.querySelector('[name="' + name + '"]');
      }
      /* Named radio groups return a RadioNodeList — prefer .value when present. */
      if (el && typeof el.value === 'string') return String(el.value || '').trim();
      if (el && el.length && el[0]) return String(el[0].value || '').trim();
      return '';
    }

    return {
      title: val('title'),
      firstName: val('firstName'),
      lastName: val('lastName'),
      gender: val('gender'),
      dateOfBirth: val('dateOfBirth'),
      nationality: val('nationality'),
      mobileCountry: val('mobileCountry') || '+91',
      mobile: val('mobile'),
      email: val('email'),
      address: val('address'),
      city: val('city'),
      state: val('state'),
      country: val('country'),
      pin: val('pin'),
      purposeOfVisit: val('purposeOfVisit'),
      vipStatus: val('vipStatus'),
      returningGuest: val('returningGuest'),
      idType: val('idType'),
      idNumber: val('idNumber'),
      idDocumentName: docLabel || displayName || stored,
      idDocumentPath: docPath,
      idDocumentStoredName:
        storedIdDocumentName(stored) || storedIdDocumentName(docPath) || '',
      idDocumentMime: val('idDocumentMime'),
      additionalGuests: collectExtraGuests(form),
      agencyName: val('agencyName'),
      agencyGst: val('agencyGst'),
      agencyAddress: val('agencyAddress'),
      agencyRoomBilling: collectFormAgencyBilling(form).agencyRoomBilling,
      agencyFbBilling: collectFormAgencyBilling(form).agencyFbBilling,
      agencyBilling: collectFormAgencyBilling(form).agencyBilling,
      bookingNumber: '',
      reservationId: val('reservationId'),
      reservationBookingId: val('reservationBookingId'),
      bookingDate: val('bookingDate'),
      checkInDate: val('checkInDate'),
      checkInTime: val('checkInTime'),
      checkOutDate: val('checkOutDate'),
      checkOutTime: val('checkOutTime') || '11:00',
      nights: Number(val('nights') || 1),
      adults: Number(val('adults') || 1),
      children: Number(val('children') || 0),
      ratePlan: primaryMergeRatePlan(form),
      roomRate: primaryMergeRoomRate(form),
      totalRate: Number(val('totalRate') || 0),
      mergeRoomRates: collectMergeRoomRates(form),
      nightlyRates: (function () {
        var rows = collectMergeRoomRates(form);
        if (lastRoom && lastRoom.isMergeMember) {
          return Array.isArray(lastRoom.stay && lastRoom.stay.nightlyRates)
            ? lastRoom.stay.nightlyRates
            : [];
        }
        var primary = null;
        for (var i = 0; i < rows.length; i++) {
          if (rows[i] && rows[i].isPrimary) {
            primary = rows[i];
            break;
          }
        }
        if (!primary) primary = rows[0] || null;
        return (primary && primary.nightlyRates) || [];
      })(),
      paymentMethod: val('paymentMethod'),
      advancePaid: Number(val('advancePaid') || 0),
      paymentReference: val('paymentReference'),
      balanceAmount: Number(val('balanceAmount') || 0),
      specialRequests: special,
      additionalRequests: val('additionalRequests'),
      earlyCheckinQty: Number(val('earlyCheckinQty') || 0) || null,
      earlyCheckinRate: Number(val('earlyCheckinRate') || 0) || null,
      earlyCheckinNights: Number(val('earlyCheckinNights') || 0) || null,
      earlyCheckinAmount: Number(val('earlyCheckinAmount') || 0),
      earlyCheckinNote: val('earlyCheckinNote'),
      lateCheckoutQty: Number(val('lateCheckoutQty') || 0) || null,
      lateCheckoutRate: Number(val('lateCheckoutRate') || 0) || null,
      lateCheckoutNights: Number(val('lateCheckoutNights') || 0) || null,
      lateCheckoutAmount: Number(val('lateCheckoutAmount') || 0),
      lateCheckoutNote: val('lateCheckoutNote'),
      extraBedQty: Number(val('extraBedQty') || 0) || null,
      extraBedRate: Number(val('extraBedRate') || 0) || null,
      extraBedNights: Number(val('extraBedNights') || 0) || null,
      extraBedAmount: Number(val('extraBedAmount') || 0),
      extraBedNote: val('extraBedNote')
    };
  }

  function submitCheckin(root, form) {
    var editing = form && form.getAttribute('data-edit-mode') === '1';
    /* Stamp actual FO check-in time at submit — not when the modal was opened. */
    if (!editing) {
      var stamped = nowTime();
      setFormTime(form, 'checkInTime', stamped);
    }

    var stay = collectStay(form);
    if ((!stay.firstName || !stay.lastName) && (stay.firstName || stay.lastName || stay.guestName)) {
      var nameParts = splitGuestName(
        [stay.firstName, stay.lastName, stay.guestName].filter(Boolean).join(' ')
      );
      stay.firstName = stay.firstName || nameParts.firstName;
      stay.lastName = stay.lastName || nameParts.lastName;
      if (stay.firstName && !stay.lastName) stay.lastName = stay.firstName;
    }
    if (lastRoom && lastRoom.stay) {
      var prevStay = lastRoom.stay;
      if (!stay.reservationId) {
        stay.reservationId = prevStay.reservationId || '';
      }
      if (!stay.reservationBookingId) {
        stay.reservationBookingId = prevStay.reservationBookingId || '';
      }
    }
    if (editing && lastRoom && lastRoom.stay) {
      var prev = lastRoom.stay;
      stay.bookingNumber = prev.bookingNumber || stay.bookingNumber || '';
      stay.reservationId = prev.reservationId || stay.reservationId || '';
      stay.reservationBookingId =
        prev.reservationBookingId || stay.reservationBookingId || '';
      stay.checkedInAt = prev.checkedInAt || '';
      stay.transferCount = prev.transferCount || 0;
      stay.transferHistory = Array.isArray(prev.transferHistory)
        ? prev.transferHistory
        : [];
      if (!stay.idDocumentPath && (prev.idDocumentPath || prev.idDocumentName)) {
        stay.idDocumentPath = stayDocumentUrl(prev) || prev.idDocumentPath || '';
        stay.idDocumentName = stay.idDocumentName || prev.idDocumentName || '';
        stay.idDocumentMime = stay.idDocumentMime || prev.idDocumentMime || '';
      }
    }
    attachFolioChargesToStay(stay, form);
    if (!stay.firstName || !stay.lastName) {
      showToast('First name and last name are required.', true);
      return Promise.reject(new Error('validation'));
    }
    if (!stay.mobile) {
      showToast('Mobile number is required.', true);
      return Promise.reject(new Error('validation'));
    }
    if (!stay.checkInDate) {
      showToast('Check-in date is required.', true);
      return Promise.reject(new Error('validation'));
    }
    if (form.getAttribute('data-id-only') !== '1') {
      var missingRate = firstMissingRoomRateInput(form);
      if (missingRate) {
        showToast('Room rate is required.', true);
        $all('[data-nightly-room-rate], [data-merge-room-rate]', form).forEach(function (el) {
          el.classList.remove('is-invalid');
        });
        missingRate.classList.add('is-invalid');
        missingRate.setAttribute('aria-invalid', 'true');
        try {
          missingRate.focus();
          if (typeof missingRate.select === 'function') missingRate.select();
        } catch (err) {}
        return Promise.reject(new Error('validation'));
      }
      var missingPlan = firstMissingMealPlanInput(form);
      if (missingPlan) {
        showToast('Meal plan is required.', true);
        $all('.hrd-ci-rate-plan-listbox', form).forEach(function (lb) {
          lb.classList.remove('is-invalid');
        });
        var planBox =
          (missingPlan.closest && missingPlan.closest('.hrd-ci-rate-plan-listbox')) ||
          null;
        if (planBox) planBox.classList.add('is-invalid');
        var trigger = planBox && planBox.querySelector('.se-filter-chip-trigger');
        try {
          if (trigger) trigger.focus();
        } catch (err) {}
        return Promise.reject(new Error('validation'));
      }
    }
    if (stay.checkInDate > todayISO()) {
      showToast('Future date check-in is not allowed.', true);
      return Promise.reject(new Error('validation'));
    }
    if ((stay.agencyRoomBilling || stay.agencyFbBilling) && !stay.agencyName) {
      showToast('Agency Name is required for Agency Billing.', true);
      return Promise.reject(new Error('validation'));
    }
    var gstError = agencyGstValidationError(form);
    if (gstError) {
      showToast(gstError, true);
      var gstInput = form.elements.agencyGst;
      if (gstInput) {
        try {
          gstInput.focus();
          gstInput.select();
        } catch (err) {}
      }
      return Promise.reject(new Error('validation'));
    }
    stay.agencyGst = form.elements.agencyGst
      ? normalizeGstin(form.elements.agencyGst.value)
      : stay.agencyGst;
    if (stay.agencyRoomBilling) {
      stay.invoiceTo = stay.agencyName;
      stay.billingName = stay.agencyName;
    } else {
      stay.invoiceTo = '';
      stay.billingName = '';
    }
    if (stay.agencyName) {
      syncAgencyMasterFromForm(root, form, { toast: false });
    }

    var api = root.getAttribute('data-room-api') || '';
    if (!api) {
      showToast('Room API unavailable.', true);
      return Promise.reject(new Error('missing api'));
    }

    var saveBtn = $('#hrd-checkin-save', root);
    if (saveBtn) saveBtn.disabled = true;

    return fetch(api, {
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
            (result.data && result.data.error) ||
              (editing ? 'Could not update guest.' : 'Check-in failed.')
          );
        }
        clearCheckinDraft(root);
        var idOnly = form.getAttribute('data-id-only') === '1';
        closeCheckinModal(root, { skipDraft: true });
        paintRoom(root, result.data.room);
        showToast(
          idOnly
            ? 'Guest ID saved.'
            : editing
              ? 'Guest details updated.'
              : 'Guest checked in successfully.'
        );
        return result.data.room;
      })
      .catch(function (err) {
        if (err.message !== 'validation') {
          showToast(
            err.message || (editing ? 'Could not update guest.' : 'Check-in failed.'),
            true
          );
        }
        throw err;
      })
      .finally(function () {
        if (saveBtn) saveBtn.disabled = false;
      });
  }

  function navigateTo(url) {
    if (typeof global.deNavigateWithTransition === 'function') {
      global.deNavigateWithTransition(url);
    } else {
      global.location.href = url;
    }
  }

  function handlePageClick(event) {
    var root = pageRoot();
    if (!root) return;

    /* Shared workspace fullscreen control — same as Rooms / POS; do not intercept. */
    if (event.target.closest('.de-fullscreen-btn')) return;

    /* Expense Ledger–style listboxes / hotel date chips — do not intercept. */
    if (event.target.closest('[data-se-listbox], .se-filter-listbox, .se-filter-chip-trigger, .ep-date-chip, [data-hotel-date], [data-hotel-time]')) {
      return;
    }

    var addGuestBtn = event.target.closest('[data-hrd-add-guest]');
    if (addGuestBtn && root.contains(addGuestBtn)) {
      event.preventDefault();
      event.stopPropagation();
      var checkinFormForGuest = $('#hrd-checkin-form', root);
      if (checkinFormForGuest) {
        addExtraGuestRow(checkinFormForGuest);
      }
      return;
    }

    var removeGuestBtn = event.target.closest('[data-hrd-remove-guest]');
    if (removeGuestBtn && root.contains(removeGuestBtn)) {
      event.preventDefault();
      event.stopPropagation();
      var guestRow = removeGuestBtn.closest('[data-extra-guest]');
      var guestForm = $('#hrd-checkin-form', root);
      if (guestRow) guestRow.remove();
      if (guestForm) {
        renumberExtraGuests(guestForm);
        syncAdultsFromGuests(guestForm);
        scheduleCheckinDraftSave(root, guestForm);
      }
      return;
    }

    var specialChargeClose = event.target.closest('[data-hrd-special-charge-close]');
    if (specialChargeClose && root.contains(specialChargeClose)) {
      event.preventDefault();
      event.stopPropagation();
      closeSpecialChargeModal(root, { cancel: true });
      return;
    }

    var otherChargeClose = event.target.closest('[data-hrd-other-charge-close]');
    if (otherChargeClose && root.contains(otherChargeClose)) {
      event.preventDefault();
      event.stopPropagation();
      closeOtherChargeModal(root, { cancel: true });
      return;
    }

    var otherAddBtn = event.target.closest('[data-hrd-other-add]');
    if (otherAddBtn && root.contains(otherAddBtn)) {
      event.preventDefault();
      event.stopPropagation();
      openOtherChargeModal(root, { fromCheck: false });
      return;
    }

    var otherEditBtn = event.target.closest('[data-hrd-other-edit]');
    if (otherEditBtn && root.contains(otherEditBtn)) {
      event.preventDefault();
      event.stopPropagation();
      var editIdx = otherEditBtn.getAttribute('data-hrd-other-edit');
      openOtherChargeModal(root, { editIndex: editIdx, fromCheck: false });
      return;
    }

    var otherRemoveBtn = event.target.closest('[data-hrd-other-remove]');
    if (otherRemoveBtn && root.contains(otherRemoveBtn)) {
      event.preventDefault();
      event.stopPropagation();
      var removeIdx = Number(otherRemoveBtn.getAttribute('data-hrd-other-remove'));
      var checkinFormOther = $('#hrd-checkin-form', root);
      if (checkinFormOther && !isNaN(removeIdx)) {
        var otherList = readOtherCustomCharges(checkinFormOther).slice();
        if (removeIdx >= 0 && removeIdx < otherList.length) {
          otherList.splice(removeIdx, 1);
          writeOtherCustomCharges(checkinFormOther, otherList);
          renderOtherChargeList(checkinFormOther);
          syncTotals(checkinFormOther);
          scheduleCheckinDraftSave(root, checkinFormOther);
        }
      }
      return;
    }

    var otherChargeModal = $('#hrd-other-charge-modal', root);
    if (otherChargeModal && !otherChargeModal.hidden && event.target === otherChargeModal) {
      event.preventDefault();
      event.stopPropagation();
      closeOtherChargeModal(root, { cancel: true });
      return;
    }

    var specialChargeEdit = event.target.closest('[data-hrd-special-charge-edit]');
    if (specialChargeEdit && root.contains(specialChargeEdit)) {
      event.preventDefault();
      event.stopPropagation();
      var editKind = specialChargeEdit.getAttribute('data-hrd-special-charge-edit');
      if (editKind) openSpecialChargeModal(root, editKind, { fromCheck: false });
      return;
    }

    var specialChargeModal = $('#hrd-special-charge-modal', root);
    if (specialChargeModal && !specialChargeModal.hidden && event.target === specialChargeModal) {
      event.preventDefault();
      event.stopPropagation();
      closeSpecialChargeModal(root, { cancel: true });
      return;
    }

    var closeBtn = event.target.closest('[data-hrd-checkin-close]');
    if (closeBtn && root.contains(closeBtn)) {
      event.preventDefault();
      event.stopPropagation();
      closeCheckinModal(root);
      return;
    }

    var nightlyToggle = event.target.closest('[data-nightly-toggle]');
    if (nightlyToggle && root.contains(nightlyToggle)) {
      event.preventDefault();
      event.stopPropagation();
      var nightRow = nightlyToggle.closest('.hrd-ci-nightly-row');
      if (nightRow && nightRow.classList.contains('is-locked')) {
        var nowCollapsed = nightRow.classList.toggle('is-collapsed');
        nightlyToggle.setAttribute('aria-expanded', nowCollapsed ? 'false' : 'true');
        if (nowCollapsed) nightRow.removeAttribute('data-user-expanded');
        else nightRow.setAttribute('data-user-expanded', '1');
        refreshNightlyRowSummary(nightRow);
      }
      return;
    }

    var otherChargeToggle = event.target.closest('[data-other-charge-toggle]');
    if (otherChargeToggle && root.contains(otherChargeToggle)) {
      event.preventDefault();
      event.stopPropagation();
      var chargeRow = otherChargeToggle.closest('.hrd-other-charge-row');
      if (chargeRow) {
        var chargeCollapsed = chargeRow.classList.toggle('is-collapsed');
        otherChargeToggle.setAttribute('aria-expanded', chargeCollapsed ? 'false' : 'true');
      }
      return;
    }

    var checkinSave = event.target.closest('#hrd-checkin-save');
    if (checkinSave && root.contains(checkinSave)) {
      event.preventDefault();
      event.stopPropagation();
      var checkinFormSave = $('#hrd-checkin-form', root);
      if (checkinFormSave) submitCheckin(root, checkinFormSave);
      return;
    }

    var transferClose = event.target.closest('[data-hrd-transfer-close]');
    if (transferClose && root.contains(transferClose)) {
      event.preventDefault();
      event.stopPropagation();
      closeTransferModal(root);
      return;
    }

    var extendClose = event.target.closest('[data-hrd-extend-close]');
    if (extendClose && root.contains(extendClose)) {
      event.preventDefault();
      event.stopPropagation();
      closeExtendModal(root);
      return;
    }

    var mergeClose = event.target.closest('[data-hrd-merge-close]');
    if (mergeClose && root.contains(mergeClose)) {
      event.preventDefault();
      event.stopPropagation();
      closeMergeModal(root);
      return;
    }

    var mergeLink = event.target.closest('[data-hrd-merge-link]');
    if (mergeLink && root.contains(mergeLink)) {
      event.preventDefault();
      event.stopPropagation();
      navigateTo(mergeLink.getAttribute('href') || '/hotel/rooms');
      return;
    }

    var reserveClose = event.target.closest('[data-hrd-reserve-close]');
    if (reserveClose && root.contains(reserveClose)) {
      event.preventDefault();
      event.stopPropagation();
      closeReserveModal(root);
      return;
    }

    var invoiceClose = event.target.closest('[data-hrd-invoice-close]');
    if (invoiceClose) {
      event.preventDefault();
      event.stopPropagation();
      closeInvoiceModal(root);
      return;
    }

    var checkoutInvoiceClose = event.target.closest('[data-hrd-checkout-invoice-close]');
    if (checkoutInvoiceClose) {
      event.preventDefault();
      event.stopPropagation();
      closeCheckoutInvoiceModal(root);
      return;
    }

    var checkoutInvoiceGo = event.target.closest('#hrd-checkout-invoice-go');
    if (checkoutInvoiceGo) {
      event.preventDefault();
      event.stopPropagation();
      var goHref = checkoutInvoiceGo.getAttribute('href') || '';
      var goRoomId = root.getAttribute('data-room-id') || '';
      closeCheckoutInvoiceModal(root);
      navigateTo(
        goHref && goHref !== '#'
          ? goHref
          : goRoomId
            ? '/hotel/rooms/' +
              encodeURIComponent(goRoomId) +
              '/invoice?kind=hotel'
            : ''
      );
      return;
    }

    var genInvoice = event.target.closest(
      '#hrd-generate-hotel-invoice, #hrd-generate-fb-invoice, #hrd-generate-invoice'
    );
    if (genInvoice && root.contains(genInvoice)) {
      event.preventDefault();
      event.stopPropagation();
      var kind = String(
        genInvoice.getAttribute('data-invoice-kind') || ''
      ).toLowerCase();
      if (kind !== 'hotel' && kind !== 'fb' && kind !== 'all') {
        if (genInvoice.id === 'hrd-generate-fb-invoice') kind = 'fb';
        else if (genInvoice.id === 'hrd-generate-hotel-invoice') kind = 'hotel';
        else kind = 'all';
      }
      /* Room invoice uses the POS-style folio page (custom charges / edits).
         F&B generate stays on the compact modal. */
      if (kind === 'fb') {
        openInvoiceModal(root, 'generate', { kind: 'fb' });
        return;
      }
      var genRoomId = root.getAttribute('data-room-id') || '';
      if (!genRoomId) {
        showToast('Room is unavailable.', true);
        return;
      }
      navigateTo(
        '/hotel/rooms/' +
          encodeURIComponent(genRoomId) +
          '/invoice?kind=hotel'
      );
      return;
    }

    var viewInvoice = event.target.closest(
      '#hrd-charges-invoice-no, #hrd-charges-fb-invoice-no, #hrd-invoice-hotel-no, #hrd-invoice-fb-no, .hrd-charges-invoiced-history .hrd-charges-invoice-no'
    );
    if (viewInvoice && root.contains(viewInvoice) && !viewInvoice.hidden) {
      event.preventDefault();
      event.stopPropagation();
      openRoomInvoicePreview(
        invoiceKindFromEl(viewInvoice),
        invoiceNumberFromEl(viewInvoice)
      );
      return;
    }

    var recordPay = event.target.closest('#hrd-record-payment');
    if (recordPay && root.contains(recordPay)) {
      event.preventDefault();
      event.stopPropagation();
      var payHref = recordPay.getAttribute('href') || '';
      var payRoomId = root.getAttribute('data-room-id') || '';
      navigateTo(
        payHref ||
          (payRoomId
            ? '/hotel/rooms/' +
              encodeURIComponent(payRoomId) +
              '/invoice?kind=hotel&settle=1'
            : '')
      );
      return;
    }

    var addSplit = event.target.closest('#hrd-invoice-add-split');
    if (addSplit) {
      event.preventDefault();
      event.stopPropagation();
      var invModal = $('#hrd-invoice-modal', root) || document.getElementById('hrd-invoice-modal');
      if (invModal && !invModal.hidden) {
        addInvoiceSplitRow(invModal, '', '');
        syncInvoiceRemainingAmount(invModal, null);
        refreshInvoiceSplitBalance(invModal);
      }
      return;
    }

    var openSplitList = event.target.closest('#hrd-invoice-splits [data-se-listbox].is-open');
    var portaledSplitList = event.target.closest(
      '.se-filter-listbox[data-hrd-invoice-listbox-portaled="1"]'
    );
    if (!openSplitList && !portaledSplitList) {
      var invModalCloseLists =
        $('#hrd-invoice-modal', root) || document.getElementById('hrd-invoice-modal');
      if (invModalCloseLists && !invModalCloseLists.hidden) {
        closeAllInvoiceSplitListboxes(invModalCloseLists);
      }
    }

    var modal = $('#hrd-checkin-modal', root);
    if (modal && !modal.hidden && event.target === modal) {
      event.preventDefault();
      event.stopPropagation();
      closeCheckinModal(root);
      return;
    }

    var transferModal = $('#hrd-transfer-modal', root);
    if (transferModal && !transferModal.hidden && event.target === transferModal) {
      event.preventDefault();
      event.stopPropagation();
      closeTransferModal(root);
      return;
    }

    var extendModal = $('#hrd-extend-modal', root);
    if (extendModal && !extendModal.hidden && event.target === extendModal) {
      event.preventDefault();
      event.stopPropagation();
      closeExtendModal(root);
      return;
    }

    var mergeModal = $('#hrd-merge-modal', root);
    if (mergeModal && !mergeModal.hidden && event.target === mergeModal) {
      event.preventDefault();
      event.stopPropagation();
      closeMergeModal(root);
      return;
    }
    if (mergeModal && !mergeModal.hidden) {
      var mergeRoomsSelect = $('#hrd-merge-rooms-select', root);
      var mergeRoomsMenu = $('#hrd-merge-rooms-menu', root);
      if (
        mergeRoomsSelect &&
        mergeRoomsMenu &&
        !mergeRoomsMenu.hidden &&
        !mergeRoomsSelect.contains(event.target)
      ) {
        closeHrdMergeRoomsMenu(root, $('#hrd-merge-form', root));
      }
    }

    var reserveModal = $('#hrd-reserve-modal', root);
    if (reserveModal && !reserveModal.hidden && event.target === reserveModal) {
      event.preventDefault();
      event.stopPropagation();
      closeReserveModal(root);
      return;
    }

    var invoiceModal = $('#hrd-invoice-modal', root) || document.getElementById('hrd-invoice-modal');
    if (invoiceModal && !invoiceModal.hidden && event.target === invoiceModal) {
      event.preventDefault();
      event.stopPropagation();
      closeInvoiceModal(root);
      return;
    }

    var back = event.target.closest('[data-hrd-back]');
    if (back) {
      event.preventDefault();
      event.stopPropagation();
      navigateTo(back.getAttribute('href') || '/hotel/rooms');
      return;
    }

    var moreBtn = event.target.closest('#hrd-more-btn');
    if (moreBtn && root.contains(moreBtn)) {
      event.preventDefault();
      event.stopPropagation();
      var menu = $('#hrd-more-menu', root);
      if (!menu) return;
      var willOpen = menu.hidden || menu.hasAttribute('hidden');
      closeMoreMenu(root);
      if (willOpen) openMoreMenu(root);
      return;
    }

    var uploadZone = event.target.closest('[data-hrd-upload]');
    if (uploadZone && root.contains(uploadZone)) {
      event.preventDefault();
      event.stopPropagation();
      if (uploadZone.disabled) return;
      var fileInput =
        uploadZone.querySelector('input[type="file"]') ||
        (uploadZone.closest('.hrd-id-type-actions') &&
          uploadZone.closest('.hrd-id-type-actions').querySelector('input[type="file"]')) ||
        (uploadZone.parentElement &&
          uploadZone.parentElement.querySelector('input[type="file"]'));
      if (fileInput) {
        try {
          fileInput.click();
        } catch (err) {}
      }
      return;
    }

    var viewDocBtn = event.target.closest('[data-hrd-id-view]');
    if (viewDocBtn && root.contains(viewDocBtn)) {
      event.preventDefault();
      event.stopPropagation();
      if (viewDocBtn.disabled) return;
      var pathAttr = String(viewDocBtn.getAttribute('data-id-path') || '').trim();
      var checkinForm = $('#hrd-checkin-form', root);
      var guestRow = viewDocBtn.closest('[data-extra-guest]');
      if (guestRow && !pathAttr) {
        var guestPath = guestRow.querySelector('[data-extra-guest-doc-path]');
        pathAttr = guestPath ? String(guestPath.value || '').trim() : '';
      }
      viewIdDocument(checkinForm, pathAttr);
      return;
    }

    var previewClose = event.target.closest('[data-hrd-id-preview-close]');
    var previewModal = document.getElementById('hrd-id-preview-modal');
    if (
      previewClose ||
      (previewModal && !previewModal.hidden && event.target === previewModal)
    ) {
      event.preventDefault();
      event.stopPropagation();
      closeIdDocumentPreview();
      return;
    }
    var previewAdd = event.target.closest('#hrd-id-preview-add');
    if (previewAdd) {
      event.preventDefault();
      event.stopPropagation();
      closeIdDocumentPreview();
      openAddGuestIdModal(root);
      return;
    }

    var statusItem = event.target.closest('[data-set-status]');
    if (statusItem && root.contains(statusItem)) {
      event.preventDefault();
      event.stopPropagation();
      closeMoreMenu(root);
      setStatus(root, statusItem.getAttribute('data-set-status'));
      return;
    }

    var markClean = event.target.closest('#hrd-mark-clean');
    if (markClean && root.contains(markClean)) {
      event.preventDefault();
      event.stopPropagation();
      setStatus(root, 'vacant', 'Room marked clean.');
      return;
    }

    var markDirty = event.target.closest('#hrd-mark-dirty');
    if (markDirty && root.contains(markDirty)) {
      event.preventDefault();
      event.stopPropagation();
      setStatus(root, 'dirty', 'Housekeeping: room marked dirty.');
      return;
    }

    var checkoutDueBtn = event.target.closest('[data-hrd-checkout-due]');
    if (checkoutDueBtn && root.contains(checkoutDueBtn)) {
      event.preventDefault();
      event.stopPropagation();
      var dueAction = checkoutDueBtn.getAttribute('data-hrd-checkout-due');
      if (dueAction === 'dismiss') {
        dismissCheckoutDueBanner(
          root.getAttribute('data-room-id') || (lastRoom && lastRoom.id) || '',
          headerAsOfDate(root)
        );
        setVisible($('#hrd-checkout-due', root), false);
        return;
      }
      if (dueAction === 'extend') {
        if (mapStatus(root.getAttribute('data-room-status')) !== 'occupied') {
          showToast('No guest checked in to extend.', true);
          return;
        }
        openExtendModal(root);
        return;
      }
      if (dueAction === 'checkout') {
        checkoutGuest(root);
        return;
      }
    }

    var actionBtn = event.target.closest('[data-action]');
    if (actionBtn && root.contains(actionBtn)) {
      /* Ignore clicks inside an already-open modal form controls that aren't actions. */
      if (actionBtn.closest('#hrd-checkin-modal') || actionBtn.closest('#hrd-transfer-modal') || actionBtn.closest('#hrd-extend-modal') || actionBtn.closest('#hrd-merge-modal') || actionBtn.closest('#hrd-reserve-modal') || actionBtn.closest('#hrd-invoice-modal')) {
        return;
      }
      event.preventDefault();
      event.stopPropagation();
      closeMoreMenu(root);
      var action = actionBtn.getAttribute('data-action');
      if (action === 'checkin') {
        var blockedCheckin = checkinBlockedReason(lastRoom, root);
        if (blockedCheckin) {
          showToast(blockedCheckin, true);
          return;
        }
        if (mapStatus(root.getAttribute('data-room-status')) === 'occupied') {
          showToast('Guest already checked in. Use Check Out first.');
          return;
        }
        openCheckinModal(root);
        return;
      }
      if (action === 'add-guest-id') {
        openAddGuestIdModal(root);
        return;
      }
      if (action === 'extend') {
        if (mapStatus(root.getAttribute('data-room-status')) !== 'occupied') {
          showToast('No guest checked in to extend.', true);
          return;
        }
        openExtendModal(root);
        return;
      }
      if (action === 'edit-guest') {
        if (mapStatus(root.getAttribute('data-room-status')) !== 'occupied') {
          showToast('No guest checked in to edit.', true);
          return;
        }
        openCheckinModal(root, { edit: true });
        return;
      }
      if (action === 'checkout') {
        checkoutGuest(root);
        return;
      }
      if (action === 'transfer') {
        openTransferModal(root);
        return;
      }
      if (action === 'merge') {
        openMergeModal(root);
        return;
      }
      if (action === 'unmerge') {
        unmergeRoom(root, 'one');
        return;
      }
      if (action === 'unmerge-group') {
        unmergeRoom(root, 'group');
        return;
      }
      if (action === 'checkout-group') {
        checkoutMergeGroup(root);
        return;
      }
      if (action === 'set-primary') {
        setMergePrimary(root);
        return;
      }
      if (action === 'reserve') {
        openReserveModal(root, { mode: 'edit' });
        return;
      }
      if (action === 'reserve-new') {
        openReserveModal(root, { mode: 'new' });
        return;
      }
    }

    var stub = event.target.closest('[data-stub]');
    if (stub && root.contains(stub)) {
      event.preventDefault();
      event.stopPropagation();
      closeMoreMenu(root);
      showToast(stub.getAttribute('data-stub') || 'Coming soon');
      return;
    }

    if (!event.target.closest('.hrd-more-wrap')) {
      closeMoreMenu(root);
    }
  }

  function handleKeydown(event) {
    var root = pageRoot();
    if (!root) return;
    if (
      (event.key === 'Enter' || event.key === ' ') &&
      event.target &&
      event.target.classList &&
      event.target.classList.contains('hrd-charges-invoice-no') &&
      event.target.classList.contains('is-clickable') &&
      !event.target.hidden
    ) {
      event.preventDefault();
      openRoomInvoicePreview(
        invoiceKindFromEl(event.target),
        invoiceNumberFromEl(event.target)
      );
      return;
    }
    var invoicePreviewIds = [
      'hrd-charges-invoice-no',
      'hrd-invoice-hotel-no',
      'hrd-charges-fb-invoice-no',
      'hrd-invoice-fb-no'
    ];
    if (
      (event.key === 'Enter' || event.key === ' ') &&
      event.target &&
      invoicePreviewIds.indexOf(event.target.id) !== -1 &&
      !event.target.hidden
    ) {
      event.preventDefault();
      openRoomInvoicePreview(
        invoiceKindFromEl(event.target),
        invoiceNumberFromEl(event.target)
      );
      return;
    }
    if (event.key === 'Escape') {
      /* Close open date picker first, then listbox, then modal. */
      var agencyMasterModal = document.getElementById('md-master-modal');
      if (agencyMasterModal && agencyMasterModal.classList.contains('open')) {
        event.preventDefault();
        event.stopPropagation();
        closeHrdAgencyMasterModal();
        return;
      }
      var idPreviewModal = document.getElementById('hrd-id-preview-modal');
      if (idPreviewModal && !idPreviewModal.hidden) {
        event.preventDefault();
        event.stopPropagation();
        closeIdDocumentPreview();
        return;
      }
      if (document.querySelector('[data-hotel-date].is-open')) {
        if (typeof global.closeHotelDatePickers === 'function') {
          global.closeHotelDatePickers();
        }
        event.preventDefault();
        event.stopPropagation();
        return;
      }
      /* Let an open Title/VIP/etc. menu close first; don't dismiss the whole modal. */
      if (document.querySelector('[data-se-listbox].is-open')) {
        if (typeof global.closeAllEpListboxes === 'function') {
          global.closeAllEpListboxes();
        }
        event.preventDefault();
        event.stopPropagation();
        return;
      }
      var specialChargeModal = $('#hrd-special-charge-modal', root);
      if (specialChargeModal && !specialChargeModal.hidden) {
        event.preventDefault();
        closeSpecialChargeModal(root, { cancel: true });
        return;
      }
      var otherChargeModal = $('#hrd-other-charge-modal', root);
      if (otherChargeModal && !otherChargeModal.hidden) {
        event.preventDefault();
        closeOtherChargeModal(root, { cancel: true });
        return;
      }
      var transferModal = $('#hrd-transfer-modal', root);
      if (transferModal && !transferModal.hidden) {
        event.preventDefault();
        closeTransferModal(root);
        return;
      }
      var extendModal = $('#hrd-extend-modal', root);
      if (extendModal && !extendModal.hidden) {
        event.preventDefault();
        closeExtendModal(root);
        return;
      }
      var mergeModal = $('#hrd-merge-modal', root);
      if (mergeModal && !mergeModal.hidden) {
        var mergeRoomsMenu = $('#hrd-merge-rooms-menu', root);
        if (mergeRoomsMenu && !mergeRoomsMenu.hidden) {
          event.preventDefault();
          closeHrdMergeRoomsMenu(root, $('#hrd-merge-form', root));
          return;
        }
        event.preventDefault();
        closeMergeModal(root);
        return;
      }
      var reserveModal = $('#hrd-reserve-modal', root);
      if (reserveModal && !reserveModal.hidden) {
        event.preventDefault();
        closeReserveModal(root);
        return;
      }
      var checkoutInvoiceModal =
        $('#hrd-checkout-invoice-modal', root) ||
        document.getElementById('hrd-checkout-invoice-modal');
      if (checkoutInvoiceModal && !checkoutInvoiceModal.hidden) {
        event.preventDefault();
        closeCheckoutInvoiceModal(root);
        return;
      }
      var invoiceModal = $('#hrd-invoice-modal', root) || document.getElementById('hrd-invoice-modal');
      if (invoiceModal && !invoiceModal.hidden) {
        event.preventDefault();
        closeInvoiceModal(root);
        return;
      }
      var modal = $('#hrd-checkin-modal', root);
      if (modal && !modal.hidden) {
        event.preventDefault();
        closeCheckinModal(root);
      }
      return;
    }
    if (event.key === 'Enter' || event.key === ' ') {
      var card = event.target.closest('#hrd-guest-card[data-action="checkin"]');
      if (card && root.contains(card) && event.target === card) {
        event.preventDefault();
        openCheckinModal(root);
      }
    }
  }

  function handleInput(event) {
    var root = pageRoot();
    if (!root) return;
    var specialChargeForm = $('#hrd-special-charge-form', root);
    if (specialChargeForm && specialChargeForm.contains(event.target)) {
      var scName = event.target.name;
      if (scName === 'qty' || scName === 'rate' || scName === 'nights') {
        syncSpecialChargeDialogAmount(specialChargeForm);
      }
      return;
    }
    var otherChargeForm = $('#hrd-other-charge-form', root);
    if (otherChargeForm && otherChargeForm.contains(event.target)) {
      var ocName = event.target.name;
      if (ocName === 'qty' || ocName === 'rate') {
        syncOtherChargeDialogAmount(otherChargeForm);
      }
      return;
    }
    var form = $('#hrd-checkin-form', root);
    if (!form || !form.contains(event.target)) return;
    var name = event.target.name;
    if (name === 'firstName' || name === 'lastName') {
      syncCustomerNameFromPersonal(form);
    }
    if (
      name === 'nights' ||
      name === 'roomRate' ||
      name === 'advancePaid' ||
      name === 'checkInDate' ||
      name === 'checkOutDate' ||
      event.target.getAttribute('data-merge-room-rate') != null ||
      event.target.getAttribute('data-nightly-room-rate') != null
    ) {
      if (
        event.target.getAttribute('data-merge-room-rate') != null ||
        event.target.getAttribute('data-nightly-room-rate') != null ||
        name === 'roomRate'
      ) {
        event.target.classList.remove('is-invalid');
        event.target.removeAttribute('aria-invalid');
      }
      if (name === 'nights' || name === 'checkInDate') {
        var nights = Math.max(1, Number(form.nights.value || 1));
        if (form.checkInDate.value) {
          setFormDate(form, 'checkOutDate', addDaysISO(form.checkInDate.value, nights));
        }
      } else if (name === 'checkOutDate' && form.checkInDate.value && form.checkOutDate.value) {
        var a = new Date(form.checkInDate.value);
        var b = new Date(form.checkOutDate.value);
        if (!isNaN(a) && !isNaN(b) && b > a) {
          var diff = Math.round((b - a) / 86400000);
          form.nights.value = String(Math.max(1, diff));
        }
      }
      if (
        name === 'nights' ||
        name === 'checkInDate' ||
        name === 'checkOutDate'
      ) {
        rebuildCheckinNightlyLists(root, form);
      } else {
        syncTotals(form);
      }
    }
    scheduleCheckinDraftSave(root, form);
  }

  function handleChange(event) {
    var root = pageRoot();
    if (!root) return;
    var form = $('#hrd-checkin-form', root);
    if (!form || !form.contains(event.target)) return;
    if (event.target.name === 'idDocument') {
      /* Handled by bindIdDocumentUpload (compress + store). */
      return;
    }
    if (event.target.matches('[data-extra-guest-file]')) {
      var guestRow = event.target.closest('[data-extra-guest]');
      var files = event.target.files;
      if (!guestRow || !files || !files.length) return;
      uploadExtraGuestDocument(root, guestRow, files).finally(function () {
        event.target.value = '';
        scheduleCheckinDraftSave(root, form);
      });
      return;
    }
    if (event.target.matches('[data-hrd-special-charge]')) {
      var kind = event.target.getAttribute('data-hrd-special-charge');
      if (event.target.checked) {
        openSpecialChargeModal(root, kind, { fromCheck: true });
      } else if (kind) {
        clearSpecialCharge(form, kind);
      }
    }
    if (event.target.matches('[data-hrd-other-toggle]')) {
      if (event.target.checked) {
        openOtherChargeModal(root, { fromCheck: true });
      } else {
        var otherList = readOtherCustomCharges(form);
        if (otherList.length) {
          var ok = true;
          try {
            ok = window.confirm('Remove all other special request charges?');
          } catch (err) {}
          if (!ok) {
            event.target.checked = true;
            return;
          }
          clearOtherCustomCharges(form);
        }
        scheduleCheckinDraftSave(root, form);
      }
    }
    if (
      event.target.getAttribute('data-merge-rate-plan') != null ||
      event.target.getAttribute('data-merge-room-rate') != null
    ) {
      syncTotals(form);
    }
    scheduleCheckinDraftSave(root, form);
  }

  function handleSubmit(event) {
    var root = pageRoot();
    if (!root) return;
    var checkinForm = $('#hrd-checkin-form', root);
    if (checkinForm && event.target === checkinForm) {
      event.preventDefault();
      event.stopPropagation();
      submitCheckin(root, checkinForm);
      return;
    }
    var specialChargeForm = $('#hrd-special-charge-form', root);
    if (specialChargeForm && event.target === specialChargeForm) {
      event.preventDefault();
      event.stopPropagation();
      saveSpecialCharge(root);
      return;
    }
    var otherChargeForm = $('#hrd-other-charge-form', root);
    if (otherChargeForm && event.target === otherChargeForm) {
      event.preventDefault();
      event.stopPropagation();
      saveOtherChargeModal(root);
      return;
    }
    var transferForm = $('#hrd-transfer-form', root);
    if (transferForm && event.target === transferForm) {
      event.preventDefault();
      event.stopPropagation();
      submitTransfer(root, transferForm);
      return;
    }
    var extendForm = $('#hrd-extend-form', root);
    if (extendForm && event.target === extendForm) {
      event.preventDefault();
      event.stopPropagation();
      submitExtendForm(root, extendForm);
      return;
    }
    var mergeForm = $('#hrd-merge-form', root);
    if (mergeForm && event.target === mergeForm) {
      event.preventDefault();
      event.stopPropagation();
      submitMerge(root, mergeForm);
      return;
    }
    var reserveForm = $('#hrd-reserve-form', root);
    if (reserveForm && event.target === reserveForm) {
      event.preventDefault();
      event.stopPropagation();
      submitReservation(root, reserveForm);
      return;
    }
    var invoiceForm = $('#hrd-invoice-form', root) || document.getElementById('hrd-invoice-form');
    if (invoiceForm && event.target === invoiceForm) {
      event.preventDefault();
      event.stopPropagation();
      submitInvoiceModal(root);
    }
  }

  function bindDocumentDelegation() {
    if (document.__hotelRoomDetailClickHandler) {
      document.removeEventListener('click', document.__hotelRoomDetailClickHandler, true);
    }
    if (document.__hotelRoomDetailKeyHandler) {
      document.removeEventListener('keydown', document.__hotelRoomDetailKeyHandler, true);
    }
    if (document.__hotelRoomDetailInputHandler) {
      document.removeEventListener('input', document.__hotelRoomDetailInputHandler, true);
    }
    if (document.__hotelRoomDetailChangeHandler) {
      document.removeEventListener('change', document.__hotelRoomDetailChangeHandler, true);
    }
    if (document.__hotelRoomDetailSubmitHandler) {
      document.removeEventListener('submit', document.__hotelRoomDetailSubmitHandler, true);
    }

    document.__hotelRoomDetailClickHandler = handlePageClick;
    document.__hotelRoomDetailKeyHandler = handleKeydown;
    document.__hotelRoomDetailInputHandler = handleInput;
    document.__hotelRoomDetailChangeHandler = handleChange;
    document.__hotelRoomDetailSubmitHandler = handleSubmit;

    document.addEventListener('click', handlePageClick, true);
    document.addEventListener('keydown', handleKeydown, true);
    document.addEventListener('input', handleInput, true);
    document.addEventListener('change', handleChange, true);
    document.addEventListener('submit', handleSubmit, true);
    if (!document.__hotelRoomDetailScrollBound) {
      document.__hotelRoomDetailScrollBound = true;
      window.addEventListener(
        'scroll',
        function () {
          var root = pageRoot();
          if (!root) return;
          var menu = $('#hrd-more-menu', root);
          var btn = $('#hrd-more-btn', root);
          if (!menu || !btn || menu.hidden || menu.hasAttribute('hidden')) return;
          positionMoreMenu(btn, menu);
        },
        true
      );
      window.addEventListener('resize', function () {
        var root = pageRoot();
        if (!root) return;
        var menu = $('#hrd-more-menu', root);
        var btn = $('#hrd-more-btn', root);
        if (!menu || !btn || menu.hidden || menu.hasAttribute('hidden')) return;
        positionMoreMenu(btn, menu);
      });
    }
    document.__hotelRoomDetailDocBound = true;
  }

  function maybeRestoreCheckinDraft(root) {
    var pendingDraft = readCheckinDraft(root);
    if (!pendingDraft || !pendingDraft.open) return;

    var status = mapStatus(root.getAttribute('data-room-status'));
    var editing = !!pendingDraft.edit;
    var idOnly = !!pendingDraft.idOnly;

    if (editing || idOnly) {
      if (status !== 'occupied' && status !== 'dirty') return;
      if (!(lastRoom && lastRoom.stay)) return;
      openCheckinModal(root, { edit: true, idOnly: idOnly });
      return;
    }

    /* New check-in draft: only restore when the room can still accept check-in. */
    if (status === 'occupied' || status === 'dirty') return;
    openCheckinModal(root);
  }

  function consumeExtendStayQuery() {
    try {
      var url = new URL(window.location.href);
      if (url.searchParams.get('extend') !== '1') return false;
      url.searchParams.delete('extend');
      var next = url.pathname + (url.search || '') + (url.hash || '');
      if (window.history && typeof window.history.replaceState === 'function') {
        window.history.replaceState({}, '', next);
      }
      return true;
    } catch (err) {
      return /[?&]extend=1(?:&|$)/.test(String(window.location.search || ''));
    }
  }

  function maybeOpenExtendStay(root) {
    if (!consumeExtendStayQuery()) return;
    root = root || pageRoot();
    if (!root) return;
    if (mapStatus(root.getAttribute('data-room-status')) !== 'occupied') {
      showToast('No guest checked in to extend.', true);
      return;
    }
    if (!(lastRoom && lastRoom.stay)) {
      showToast('No guest checked in to extend.', true);
      return;
    }
    openExtendModal(root);
  }

  function loadRoomIfNeeded(root, done) {
    var api = root.getAttribute('data-room-api') || '';
    if (!api) {
      maybeOpenExtendStay(root);
      if (typeof done === 'function') done();
      return;
    }
    fetch(api, {
      method: 'GET',
      credentials: 'same-origin',
      headers: apiHeaders()
    })
      .then(function (resp) {
        return resp.json().then(function (data) {
          return { status: resp.status, data: data };
        });
      })
      .then(function (payload) {
        var data = payload && payload.data;
        if (data && data.ok && data.room) {
          paintRoom(root, data.room);
        }
        maybeOpenExtendStay(root);
        if (typeof done === 'function') done();
      })
      .catch(function () {
        maybeOpenExtendStay(root);
        if (typeof done === 'function') done();
      });
  }

  function initHotelRoomDetailPage() {
    bindDocumentDelegation();
    var root = pageRoot();
    var main = (root && root.closest('.de-main-wrapper')) || document.querySelector('.de-main-wrapper');
    if (main) main.classList.remove('is-soft-nav-loading');
    document.documentElement.classList.remove('de-soft-navigating');
    if (!root) return;
    if (typeof global.initEpListboxes === 'function') {
      global.initEpListboxes();
    }

    loadHotelTaxRates(function () {
      if (lastRoom) paintRoom(root, lastRoom);
    });

    bindDateChipPickers(root);
    var headerDate = $('#hrd-header-date', root);
    var today = todayISO();
    if (headerDate) {
      if (typeof global.setHotelDateValue === 'function') {
        global.setHotelDateValue(headerDate, today);
      } else {
        headerDate.value = today;
      }
      if (typeof global.syncHotelDateChip === 'function') {
        global.syncHotelDateChip(headerDate);
      }
      var headerChip = headerDate.closest('[data-hotel-date]');
      if (headerChip) {
        headerChip.classList.add('hrd-header-date--fixed');
        var headerTrigger = headerChip.querySelector('.hotel-date-trigger');
        if (headerTrigger) {
          headerTrigger.setAttribute('aria-disabled', 'true');
          headerTrigger.removeAttribute('aria-haspopup');
          headerTrigger.tabIndex = -1;
        }
      }
    }

    var bootRoom = readRoomBootstrap(root);
    if (bootRoom && (bootRoom.id || bootRoom.status || bootRoom.stay)) {
      paintRoom(root, bootRoom);
    } else {
      var status = mapStatus(root.getAttribute('data-room-status'));
      paintRoom(root, {
        status: status,
        id: root.getAttribute('data-room-id'),
        number: root.getAttribute('data-room-number'),
        roomType: root.getAttribute('data-room-type'),
        roomTypeLabel: root.getAttribute('data-room-type-label'),
        stay:
          lastRoom &&
          String(lastRoom.id || '') === String(root.getAttribute('data-room-id') || '')
            ? lastRoom.stay
            : null
      });
    }
    loadRoomIfNeeded(root, function () {
      maybeRestoreCheckinDraft(root);
    });
  }

  function flushOpenCheckinDraftOnUnload() {
    var root = pageRoot();
    if (!root || !document.body.classList.contains('hrd-checkin-open')) return;
    var form = $('#hrd-checkin-form', root);
    if (!form) return;
    flushCheckinDraft(root, form, { open: true });
  }

  if (!document.__hotelRoomDetailUnloadBound) {
    document.__hotelRoomDetailUnloadBound = true;
    window.addEventListener('pagehide', flushOpenCheckinDraftOnUnload);
    window.addEventListener('beforeunload', flushOpenCheckinDraftOnUnload);
    document.addEventListener('visibilitychange', function () {
      if (document.visibilityState === 'hidden') flushOpenCheckinDraftOnUnload();
    });
  }

  if (!document.__hrdAgencyMasterModalBound) {
    document.__hrdAgencyMasterModalBound = true;
    document.addEventListener('md-master-modal-closed', function () {
      var root = pageRoot();
      if (!root) return;
      refreshAgenciesFromApi(root);
    });
  }

  global.initHotelRoomDetailPage = initHotelRoomDetailPage;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initHotelRoomDetailPage);
  } else {
    initHotelRoomDetailPage();
  }
})(window);
