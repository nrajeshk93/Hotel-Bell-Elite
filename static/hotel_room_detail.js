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

  function pageRoot() {
    return document.getElementById('hotel-room-detail-page');
  }

  function dash(value) {
    var text = String(value == null ? '' : value).trim();
    return text || '—';
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
    var menu = $('#hrd-more-menu', root);
    var btn = $('#hrd-more-btn', root);
    if (menu) {
      menu.hidden = true;
      menu.setAttribute('hidden', '');
    }
    if (btn) btn.setAttribute('aria-expanded', 'false');
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

  function guestInitials(stay) {
    var first = ((stay && stay.firstName) || '').trim();
    var last = ((stay && stay.lastName) || '').trim();
    var name = ((stay && stay.guestName) || '').trim();
    if (first || last) {
      return ((first.charAt(0) || '') + (last.charAt(0) || '')).toUpperCase() || 'G';
    }
    if (name) {
      var parts = name.split(/\s+/);
      return (
        (parts[0].charAt(0) || '') +
        ((parts[1] && parts[1].charAt(0)) || '')
      ).toUpperCase();
    }
    return 'G';
  }

  function paintGuestPanels(root, room) {
    var stay = (room && room.stay) || null;
    var occupied = mapStatus(room && room.status) === 'occupied' && !!stay;
    var number = (room && room.number) || root.getAttribute('data-room-number') || '';

    var emptyGuest = $('#hrd-guest-empty', root);
    var guestFilled = $('#hrd-guest-filled', root);
    setVisible(emptyGuest, !occupied);
    setVisible(guestFilled, occupied);

    var guestCard = $('#hrd-guest-card', root);
    if (guestCard) {
      if (occupied) {
        guestCard.removeAttribute('data-action');
        guestCard.removeAttribute('role');
        guestCard.removeAttribute('tabindex');
        guestCard.removeAttribute('aria-label');
      } else {
        guestCard.setAttribute('data-action', 'checkin');
        guestCard.setAttribute('role', 'button');
        guestCard.setAttribute('tabindex', '0');
        guestCard.setAttribute('aria-label', 'Start check-in');
      }
    }
    setVisible($('#hrd-edit-guest', root), occupied);

    if (occupied && stay) {
      var avatar = $('#hrd-guest-avatar', root);
      if (avatar) avatar.textContent = guestInitials(stay);
      var nameEl = $('#hrd-guest-name', root);
      if (nameEl) nameEl.textContent = dash(stay.guestName || (stay.firstName + ' ' + stay.lastName));
      var metaEl = $('#hrd-guest-meta', root);
      if (metaEl) metaEl.textContent = 'In-house · Room ' + number;
      var bookingEl = $('#hrd-guest-booking', root);
      if (bookingEl) bookingEl.textContent = dash(stay.bookingNumber);
      var statusEl = $('#hrd-guest-status', root);
      if (statusEl) statusEl.textContent = 'Checked in';
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

    var hasId = !!(
      occupied &&
      stay &&
      (stay.idType || stay.idDocumentName || stay.idNumber)
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
    }

    var agencyName = root.querySelector('[data-agency-name]');
    var agencyGst = root.querySelector('[data-agency-gst]');
    var agencyAddress = root.querySelector('[data-agency-address]');
    var agencyBilling = root.querySelector('[data-agency-billing]');
    var hasAgency = !!(
      occupied &&
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
        agencyBilling.textContent = stay.agencyBilling
          ? 'Invoice to ' + dash(stay.invoiceTo || stay.billingName || stay.agencyName)
          : 'Guest';
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

  function chargeLinesFromStay(stay) {
    var bookedNights = Math.max(1, Number((stay && stay.nights) || 1));
    var overstayNights = overstayNightsFromStay(stay);
    var billableNights = Math.max(
      1,
      Number((stay && stay.billableNights) || bookedNights + overstayNights)
    );
    var roomRate = Math.max(0, Number((stay && stay.roomRate) || 0));
    var bookedCharges = Math.round(roomRate * bookedNights * 100) / 100;
    var overstayCharges =
      Math.round(roomRate * Math.max(0, billableNights - bookedNights) * 100) /
      100;
    var lines = [];
    if (bookedCharges > 0) {
      lines.push({ label: 'Room Charges', amount: bookedCharges });
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
    var restaurant = 0;
    var bar = 0;
    var otherFolio = [];
    folio.forEach(function (item) {
      if (!item) return;
      var amount = Number(item.amount || 0);
      if (!(amount > 0)) return;
      var kind = String(item.kind || '').toLowerCase();
      if (kind === 'restaurant_room_transfer') restaurant += amount;
      else if (kind === 'bar_room_transfer') bar += amount;
      else {
        otherFolio.push({
          label: item.label || 'Other Charge',
          amount: amount
        });
      }
    });
    if (restaurant > 0) {
      lines.push({
        label: 'Restaurant Room Transfer',
        amount: Math.round(restaurant * 100) / 100
      });
    }
    if (bar > 0) {
      lines.push({
        label: 'Bar Room Transfer',
        amount: Math.round(bar * 100) / 100
      });
    }
    otherFolio.forEach(function (row) {
      lines.push(row);
    });
    return lines;
  }

  function stayMoneySummary(stay) {
    var lines = chargeLinesFromStay(stay);
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
    var taxable = Math.round(Math.max(0, subtotal - discount) * 100) / 100;
    var cgst = Math.round(taxable * CGST_RATE * 100) / 100;
    var ugst = Math.round(taxable * UGST_RATE * 100) / 100;
    var computedEstimated = Math.round((taxable + cgst + ugst) * 100) / 100;
    /* Prefer live recompute so overstay nights update even if stay payload is stale. */
    var estimated = computedEstimated;
    if (
      stay &&
      stay.estimatedTotal != null &&
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
      balance: balance
    };
  }

  function formatDiscountHint(type, value) {
    var n = Number(value);
    if (!isFinite(n) || n <= 0) return '';
    if (String(type || '').toLowerCase() === 'inr') return '(₹' + n + ')';
    return '(' + n + '%)';
  }

  function paintEstimatedCharges(root, room) {
    var emptyEl = $('#hrd-charges-empty', root);
    var bodyEl = $('#hrd-charges-body', root);
    var listEl = $('#hrd-charges-list', root);
    if (!emptyEl || !bodyEl || !listEl) return;

    var stay = (room && room.stay) || null;
    var occupied = mapStatus(room && room.status) === 'occupied' && !!stay;
    var invoiceNoEl = $('#hrd-charges-invoice-no', root);
    var actionsEl = $('#hrd-charges-actions', root);
    var genBtn = $('#hrd-generate-invoice', root);
    var payBtn = $('#hrd-record-payment', root);

    if (!occupied) {
      listEl.innerHTML = '';
      setVisible(emptyEl, true);
      setVisible(bodyEl, false);
      if (invoiceNoEl) {
        invoiceNoEl.hidden = true;
        invoiceNoEl.textContent = '';
        invoiceNoEl.removeAttribute('role');
        invoiceNoEl.removeAttribute('tabindex');
        invoiceNoEl.removeAttribute('title');
        invoiceNoEl.classList.remove('is-clickable');
      }
      if (actionsEl) actionsEl.hidden = true;
      if (genBtn) genBtn.hidden = true;
      if (payBtn) payBtn.hidden = true;
      return;
    }

    var summary = stayMoneySummary(stay);
    var lines = summary.lines;
    var estimated = summary.estimated;
    var advance = summary.advance;
    var balance = summary.balance;
    var invoiceGenerated = !!(stay.invoiceGenerated || stay.invoiceNumber);
    var invoiceNumber = String(stay.invoiceNumber || '').trim();

    if (invoiceNoEl) {
      if (invoiceGenerated && invoiceNumber) {
        invoiceNoEl.hidden = false;
        invoiceNoEl.textContent = 'Invoice ' + invoiceNumber;
        invoiceNoEl.setAttribute('role', 'button');
        invoiceNoEl.setAttribute('tabindex', '0');
        invoiceNoEl.setAttribute('title', 'View invoice');
        invoiceNoEl.classList.add('is-clickable');
      } else {
        invoiceNoEl.hidden = true;
        invoiceNoEl.textContent = '';
        invoiceNoEl.removeAttribute('role');
        invoiceNoEl.removeAttribute('tabindex');
        invoiceNoEl.removeAttribute('title');
        invoiceNoEl.classList.remove('is-clickable');
      }
    }

    if (!lines.length && estimated <= 0) {
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
      if (payBtn) payBtn.hidden = true;
      return;
    }

    listEl.innerHTML = lines
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

    var discRow = root.querySelector('[data-charges-discount-row]');
    var discHint = root.querySelector('[data-charges-discount-hint]');
    var discEl = root.querySelector('[data-charges-discount]');
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
    if (cgstEl) cgstEl.textContent = moneyText(summary.cgst);
    if (ugstEl) ugstEl.textContent = moneyText(summary.ugst);
    if (totalEl) totalEl.textContent = moneyText(estimated);
    if (advanceEl) advanceEl.textContent = moneyText(advance);
    if (balanceEl) balanceEl.textContent = moneyText(balance);

    setVisible(emptyEl, false);
    setVisible(bodyEl, true);

    if (actionsEl) actionsEl.hidden = false;
    var isMember = !!(
      room.isMergeMember ||
      (stay && (stay.mergeRole === 'member' || stay.billingRoomId))
    );
    if (isMember) {
      if (genBtn) genBtn.hidden = true;
      if (payBtn) payBtn.hidden = true;
      var billNo = room.billingRoomNumber || stay.billingRoomId || '';
      if (emptyEl && (!lines.length || estimated <= 0)) {
        emptyEl.textContent =
          'Billing is on Room ' + (billNo || '—') + '. Open that room to invoice.';
        setVisible(emptyEl, true);
        setVisible(bodyEl, false);
      }
    } else {
      if (genBtn) genBtn.hidden = invoiceGenerated;
      if (payBtn) payBtn.hidden = !(invoiceGenerated && balance > 0);
    }
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
      reservedBtn.textContent = 'Reserved';
      reservedBtn.setAttribute('data-set-status', 'reserved');
      reservedBtn.classList.toggle('is-current', s === 'reserved');
    }
    if (oooBtn) {
      oooBtn.hidden = false;
      oooBtn.textContent = 'Out of order';
      oooBtn.setAttribute('data-set-status', 'out_of_order');
      oooBtn.classList.toggle('is-current', s === 'out_of_order');
    }

    if (vacantBtn) {
      vacantBtn.textContent = 'Vacant';
      vacantBtn.setAttribute('data-set-status', 'vacant');
      vacantBtn.classList.toggle('is-current', s === 'vacant');
      vacantBtn.hidden = s === 'occupied' || s === 'dirty';
    }
    if (occupiedBtn) {
      occupiedBtn.textContent = 'Occupied';
      occupiedBtn.setAttribute('data-set-status', 'occupied');
      occupiedBtn.classList.toggle('is-current', false);
      /* Only vacant rooms can be marked Occupied from the menu. */
      occupiedBtn.hidden = s !== 'vacant';
      if (occupiedBtn.hidden) occupiedBtn.setAttribute('hidden', '');
      else occupiedBtn.removeAttribute('hidden');
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
    var unmergeBtn = $('#hrd-menu-unmerge', root);
    var unmergeGroupBtn = $('#hrd-menu-unmerge-group', root);
    var primaryBtn = $('#hrd-menu-set-primary', root);
    var isMember = !!(room && room.isMergeMember);
    var isPrimary = !!(room && room.isMergePrimary);
    var inGroup = !!(
      (room && room.mergeGroupId) ||
      isMember ||
      isPrimary
    );

    if (mergeBtn) mergeBtn.hidden = isMember;
    if (unmergeBtn) unmergeBtn.hidden = !inGroup;
    if (unmergeGroupBtn) unmergeGroupBtn.hidden = !isPrimary;
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
    /* Prefer inventory Occupied so checked-in rooms never paint Vacant. */
    var displayStatus = occupied ? 'occupied' : status;
    var badge = $('[data-room-status-badge]', root);
    if (badge) {
      badge.textContent = STATUS_LABELS[displayStatus] || displayStatus;
      badge.className = 'hrd-status-badge hrd-status-badge--' + displayStatus;
    }

    var statusEl = $('[data-kpi-status]', root);
    if (statusEl) statusEl.textContent = STATUS_LABELS[displayStatus] || displayStatus;

    /* Housekeeping card: Dirty while pending clean; otherwise show real room status. */
    var hkStatus = dirty && !occupied ? 'dirty' : displayStatus;
    var hk = $('[data-kpi-hk]', root);
    if (hk) hk.textContent = STATUS_LABELS[hkStatus] || hkStatus;
    var hkIcon = $('[data-hk-icon]', root);
    if (hkIcon) {
      hkIcon.className =
        'hrd-kpi-icon hrd-kpi-icon--' +
        (hkStatus === 'dirty' ? 'rose' : hkStatus === 'occupied' ? 'orange' : 'blue');
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

    var checkinBtn = $('#hrd-new-checkin', root);
    if (checkinBtn) {
      if (occupied) {
        checkinBtn.innerHTML =
          '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="m16 17 5-5-5-5"/><path d="M21 12H9"/></svg>' +
          'Check Out';
        checkinBtn.setAttribute('data-action', 'checkout');
      } else {
        checkinBtn.innerHTML =
          '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>' +
          'New Check-in';
        checkinBtn.setAttribute('data-action', 'checkin');
      }
    }

    var reserveBtn = $('#hrd-reserve', root);
    if (reserveBtn) {
      var showReserve = inventory !== 'occupied';
      setVisible(reserveBtn, showReserve);
      if (showReserve) {
        var reserveLabel = inventory === 'reserved' ? 'Edit Reservation' : 'Reserve';
        reserveBtn.innerHTML =
          '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M8 5V3M16 5V3M3 10h18"/></svg>' +
          reserveLabel;
        reserveBtn.setAttribute('data-action', 'reserve');
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
    if (status === 'dirty' && (current === 'occupied' || hasStay)) {
      var okDirty = global.confirm(
        'Mark this room Dirty? The guest will be checked out and the stay cleared.'
      );
      if (!okDirty) return Promise.resolve(null);
    }
    var body = { status: status };
    if (status === 'reserved') {
      var asOf = headerAsOfDate(root);
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
    if (isPrimary) {
      var partners = (lastRoom.mergePartnerNumbers || []).join(', ');
      var okGroup = global.confirm(
        'This is the billing primary' +
          (partners ? ' (merged with Room ' + partners + ')' : '') +
          '. Check out will clear all merged rooms. Continue?'
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
    return fetch(api, {
      method: 'PUT',
      credentials: 'same-origin',
      headers: apiHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ action: 'checkout' })
    })
      .then(function (resp) {
        return resp.json().then(function (data) {
          return { ok: resp.ok, data: data };
        });
      })
      .then(function (result) {
        if (!result.ok || !result.data || !result.data.ok) {
          throw new Error((result.data && result.data.error) || 'Checkout failed.');
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
    var list = box.querySelector('.se-filter-listbox');
    box.classList.remove('is-open');
    if (trigger) trigger.setAttribute('aria-expanded', 'false');
    if (list) {
      list.hidden = true;
      list.scrollTop = 0;
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
    var list = box.querySelector('.se-filter-listbox');
    box.classList.add('is-open');
    if (trigger) trigger.setAttribute('aria-expanded', 'true');
    if (list) list.hidden = false;
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

  function refreshInvoiceSplitOptions(modal) {
    invoiceSplitRows(modal).forEach(function (row) {
      var list = row.querySelector('.se-filter-listbox');
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
      if (!option || !list.contains(option)) return;
      e.preventDefault();
      var value = option.getAttribute('data-value') || '';
      var label = (option.textContent || '').trim();
      hidden.value = value;
      if (valueEl) valueEl.textContent = label || 'Select mode…';
      list.querySelectorAll('.se-filter-listbox-option').forEach(function (opt) {
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

  function openInvoiceModal(root, mode) {
    var modal = $('#hrd-invoice-modal', root) || document.getElementById('hrd-invoice-modal');
    if (!modal) return;
    var stay = (lastRoom && lastRoom.stay) || null;
    if (!stay) {
      showToast('No guest stay on this room.', true);
      return;
    }
    var summary = stayMoneySummary(stay);
    var isPay = mode === 'payment';
    if (isPay && !(stay.invoiceGenerated || stay.invoiceNumber)) {
      showToast('Generate the invoice before recording payment.', true);
      return;
    }
    if (isPay && !(summary.balance > 0)) {
      showToast('Balance due is already settled.');
      return;
    }
    if (!isPay && (stay.invoiceGenerated || stay.invoiceNumber)) {
      showToast('Invoice already generated.');
      return;
    }
    if (!summary.lines.length && summary.estimated <= 0) {
      showToast('No charges to invoice yet.', true);
      return;
    }

    var modeEl = $('#hrd-invoice-mode', modal);
    if (modeEl) modeEl.value = isPay ? 'payment' : 'generate';
    var titleEl = $('#hrd-invoice-title', modal);
    var subEl = $('#hrd-invoice-subtitle', modal);
    var saveBtn = $('#hrd-invoice-save', modal);
    if (titleEl) titleEl.textContent = isPay ? 'Record Payment' : 'Generate Invoice';
    if (subEl) {
      subEl.textContent = isPay
        ? 'Split payment toward the balance'
        : 'Lock charges and optionally collect payment';
    }
    if (saveBtn) saveBtn.textContent = isPay ? 'Record Payment' : 'Generate Invoice';

    var linesEl = $('#hrd-invoice-lines', modal);
    if (linesEl) {
      linesEl.innerHTML = summary.lines
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
    var discRow = $('#hrd-invoice-discount-row', modal);
    var discHint = $('#hrd-invoice-discount-hint', modal);
    var discEl = $('#hrd-invoice-discount', modal);
    var cgstEl = $('#hrd-invoice-cgst', modal);
    var ugstEl = $('#hrd-invoice-ugst', modal);
    var totalEl = $('#hrd-invoice-total', modal);
    var advanceEl = $('#hrd-invoice-advance', modal);
    var balanceEl = $('#hrd-invoice-balance', modal);
    var showDisc = Number(summary.discount) > 0;
    if (discRow) discRow.hidden = !showDisc;
    if (discHint) {
      discHint.textContent = showDisc
        ? formatDiscountHint(summary.discountType, summary.discountValue)
        : '';
    }
    if (discEl) discEl.textContent = showDisc ? '−' + moneyText(summary.discount) : '—';
    if (cgstEl) cgstEl.textContent = moneyText(summary.cgst);
    if (ugstEl) ugstEl.textContent = moneyText(summary.ugst);
    if (totalEl) totalEl.textContent = moneyText(summary.estimated);
    if (advanceEl) advanceEl.textContent = moneyText(summary.advance);
    if (balanceEl) balanceEl.textContent = moneyText(summary.balance);

    var noteEl = $('#hrd-invoice-note', modal);
    if (noteEl) noteEl.value = '';
    invoiceAllowCredit = stayHasAgency(stay);
    resetInvoiceSplits(modal, summary.balance);
    var hintEl = $('#hrd-invoice-hint', modal);
    if (hintEl) {
      hintEl.textContent = invoiceAllowCredit
        ? 'Agency stay: Credit is available. Split across modes or pay any amount up to the balance.'
        : 'Split across modes or pay any amount up to the balance. Guest stays checked in.';
    }

    modal.hidden = false;
    modal.setAttribute('aria-hidden', 'false');
    var firstAmount = modal.querySelector('.hrd-invoice-split-amount');
    if (firstAmount) {
      try {
        firstAmount.focus();
        firstAmount.select();
      } catch (err) {}
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
    var noteEl = $('#hrd-invoice-note', modal);
    var note = String((noteEl && noteEl.value) || '').trim();
    var collected = collectInvoicePaymentSplits(modal);
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
            payment_splits: collected.splits,
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
        if (mode === 'payment') {
          showToast('Payment recorded' + (inv ? ' on ' + inv : '') + '.');
        } else {
          showToast(
            (inv ? 'Invoice ' + inv + ' generated.' : 'Invoice generated.') +
              (collected.total > 0 ? ' Payment recorded.' : '')
          );
          if (
            typeof global.openHotelRoomInvoice === 'function' &&
            result.data.room
          ) {
            if (!global.openHotelRoomInvoice(result.data.room, { autoPrint: false })) {
              showToast('Invoice saved. Allow pop-ups to view the print preview.');
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

  function defaultRateFor(root) {
    var type = root.getAttribute('data-room-type') || '';
    return DEFAULT_RATES[type] != null ? DEFAULT_RATES[type] : 4500;
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

  function syncTotals(form) {
    if (!form) return;
    var nights = Math.max(1, Number(form.nights.value || 1));
    var rate = Math.max(0, Number(form.roomRate.value || 0));
    var advance = Math.max(0, Number(form.advancePaid.value || 0));
    var extras = specialChargeExtrasTotal(form);
    var total = Math.round((rate * nights + extras) * 100) / 100;
    var balance = Math.max(0, Math.round((total - advance) * 100) / 100);
    form.totalRate.value = String(total);
    form.balanceAmount.value = String(balance);
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
    var billing = form.elements.agencyBilling;
    var nameInput = form.elements.agencyName;
    var hint = form.querySelector(
      '#hrd-ci-agency-billing-hint, #hrd-reserve-agency-billing-hint, .hrd-agency-billing-hint'
    );
    var nameEl = form.querySelector(
      '#hrd-ci-agency-billing-name, #hrd-reserve-agency-billing-name'
    );
    var checked = !!(billing && billing.checked);
    var agencyName = nameInput ? String(nameInput.value || '').trim() : '';
    if (nameEl) nameEl.textContent = agencyName || 'Agency Name';
    if (hint) {
      if (checked) {
        hint.hidden = false;
        hint.removeAttribute('hidden');
      } else {
        hint.hidden = true;
        hint.setAttribute('hidden', '');
      }
    }
    if (nameInput) {
      nameInput.required = checked;
    }
  }

  function bindAgencyBilling(form) {
    if (!form || form.getAttribute('data-agency-billing-bound') === '1') return;
    form.setAttribute('data-agency-billing-bound', '1');
    var billing = form.elements.agencyBilling;
    var nameInput = form.elements.agencyName;
    if (billing) {
      billing.addEventListener('change', function () {
        syncAgencyBillingHint(form);
        if (billing.checked && nameInput && !String(nameInput.value || '').trim()) {
          nameInput.focus();
        }
      });
    }
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
    var ratePlanTrigger = document.getElementById('hrd-ci-rate-plan-trigger');
    if (ratePlanTrigger) ratePlanTrigger.disabled = locked;
    $all(
      '#hrd-ci-early-checkin, #hrd-ci-late-checkout, #hrd-ci-extra-bed, #hrd-ci-early-checkin-edit, #hrd-ci-late-checkout-edit, #hrd-ci-extra-bed-edit',
      form
    ).forEach(function (el) {
      el.disabled = locked;
    });
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
      var raw = sessionStorage.getItem(key);
      if (!raw) return null;
      var data = JSON.parse(raw);
      return data && typeof data === 'object' ? data : null;
    } catch (err) {
      return null;
    }
  }

  function writeCheckinDraft(root, stay, meta) {
    var key = checkinDraftKey(root);
    if (!key || !stay) return;
    meta = meta || {};
    var open =
      meta.open != null
        ? !!meta.open
        : document.body.classList.contains('hrd-checkin-open');
    try {
      sessionStorage.setItem(
        key,
        JSON.stringify({
          savedAt: Date.now(),
          open: open,
          stay: stay
        })
      );
    } catch (err) {}
  }

  function clearCheckinDraft(root) {
    var key = checkinDraftKey(root);
    if (!key) return;
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
        writeCheckinDraft(root, collectStay(form), { open: true });
      } catch (err) {}
    }, 280);
  }

  function applyStayDraft(form, stay) {
    if (!form || !stay) return;
    checkinDraftApplying = true;
    try {
      setFormText(form, 'firstName', stay.firstName || '');
      setFormText(form, 'lastName', stay.lastName || '');
      setFormText(form, 'mobile', stay.mobile || '');
      setFormText(form, 'email', stay.email || '');
      setFormText(form, 'address', stay.address || '');
      setFormText(form, 'city', stay.city || '');
      setFormText(form, 'state', stay.state || '');
      setFormText(form, 'pin', stay.pin || '');
      setFormText(form, 'agencyName', stay.agencyName || '');
      setFormText(form, 'agencyGst', stay.agencyGst || '');
      setFormText(form, 'agencyAddress', stay.agencyAddress || '');
      setFormText(form, 'nights', stay.nights != null ? stay.nights : '1');
      setFormText(form, 'roomRate', stay.roomRate != null ? stay.roomRate : '');
      setFormText(form, 'advancePaid', stay.advancePaid != null ? stay.advancePaid : '0');
      setFormText(form, 'paymentReference', stay.paymentReference || '');
      setFormText(form, 'additionalRequests', stay.additionalRequests || '');
      if (form.elements.agencyBilling) {
        form.elements.agencyBilling.checked = !!stay.agencyBilling;
      }

      resetListboxValue('hrd-ci-title', stay.title || '', 'Select');
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
      resetListboxValue(
        'hrd-ci-rate-plan',
        stay.ratePlan || 'EP',
        RATE_PLAN_LABELS[stay.ratePlan] || stay.ratePlan || 'EP — Room Only'
      );
      resetListboxValue('hrd-ci-payment', stay.paymentMethod || '', 'Select');

      setFormDate(form, 'dateOfBirth', stay.dateOfBirth || '');
      setFormDate(form, 'bookingDate', stay.bookingDate || '');
      setFormDate(form, 'checkInDate', stay.checkInDate || '');
      setFormDate(form, 'checkOutDate', stay.checkOutDate || '');
      setFormTime(form, 'checkInTime', stay.checkInTime || '');

      syncCustomerNameFromPersonal(form);
      if (stay.idDocumentPath) {
        setIdDocumentUi(form, {
          path: stay.idDocumentPath,
          url: stay.idDocumentPath,
          mime: stay.idDocumentMime || '',
          displayName: stay.idDocumentName || '',
          originalName: stay.idDocumentName || '',
          storedName: stay.idDocumentName || ''
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

      syncAgencyBillingHint(form);
      syncTotals(form);
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
      if (!name && !idType && !path) return;
      guests.push({
        name: name,
        idType: idType,
        idDocumentName: displayName || stored,
        idDocumentPath: path,
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
    var displayName = doc.displayName || doc.originalName || '';
    if (pathInput) pathInput.value = doc.path || doc.url || '';
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
        : 'Upload ID document (JPG, PNG, HEIC, PDF)';
    }
    syncExtraGuestViewBtn(row, !!(pathInput && pathInput.value));
  }

  function uploadExtraGuestDocument(root, row, file) {
    if (!root || !row || !file) {
      return Promise.reject(new Error('missing file'));
    }
    var api =
      (root.getAttribute('data-id-document-upload-api') || '').trim() ||
      '/hotel/api/id-documents';
    var uploadBtn = row.querySelector('[data-hrd-upload]');
    if (uploadBtn) {
      uploadBtn.classList.add('is-busy');
      uploadBtn.disabled = true;
    }
    var body = new FormData();
    body.append('file', file, file.name);
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
        setExtraGuestDocumentUi(row, result.data.document);
        showToast('ID document uploaded and compressed.');
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

  function addExtraGuestRow(form, guest) {
    var host = extraGuestsHost(form);
    if (!host) return;
    guest = guest || {};
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
      '.jpg,.jpeg,.png,.heic,.heif,.pdf,image/jpeg,image/png,image/heic,image/heif,application/pdf';
    fileInput.hidden = true;
    fileInput.setAttribute('data-extra-guest-file', '1');

    var pathInput = document.createElement('input');
    pathInput.type = 'hidden';
    pathInput.setAttribute('data-extra-guest-doc-path', '1');
    pathInput.value = guest.idDocumentPath || '';
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
    uploadBtn.title = 'Upload ID document (JPG, PNG, HEIC, PDF)';
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
    if (guest.idDocumentName) {
      nameEl.textContent = guest.idDocumentName;
      nameEl.hidden = false;
    }
    typeWrap.appendChild(nameEl);

    row.appendChild(nameField);
    row.appendChild(typeWrap);
    host.appendChild(row);

    if (typeof global.initEpListboxes === 'function') {
      global.initEpListboxes();
    }

    if (guest.idDocumentPath) {
      syncExtraGuestViewBtn(row, true);
      if (uploadBtn) uploadBtn.classList.add('is-filled');
    }

    syncAdultsFromGuests(form);
    scheduleCheckinDraftSave(pageRoot(), form);
    setTimeout(function () {
      nameInput.focus();
    }, 20);
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

  function fillCheckinFromGuest(form, guest) {
    if (!form || !guest) return;
    var title = String(guest.title || '').trim();
    if (title) resetListbox('hrd-ci-title', title, title);
    setFormText(form, 'firstName', guest.firstName || guest.first_name || '');
    setFormText(form, 'lastName', guest.lastName || guest.last_name || '');
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
    if (form.elements.agencyBilling) {
      form.elements.agencyBilling.checked = !!(guest.agencyBilling || guest.agency_billing);
    }
    syncAgencyBillingHint(form);
    scheduleCheckinDraftSave(pageRoot(), form);
  }

  function bindMobileGuestLookup(root, form) {
    if (!form) return;
    var mobileInput = form.elements.mobile || $('#hrd-ci-mobile', form);
    if (!mobileInput) return;
    form._hrdLastGuestLookup = '';
    if (form.getAttribute('data-guest-lookup-bound') === '1') return;
    form.setAttribute('data-guest-lookup-bound', '1');
    var lookupTimer = null;

    function runLookup() {
      var api =
        (root && root.getAttribute('data-guest-lookup-api')) ||
        '/hotel/api/guests/lookup';
      var mobile = String(mobileInput.value || '').trim();
      var digits = mobile.replace(/\D/g, '');
      if (digits.length < 8) return;
      if (digits === form._hrdLastGuestLookup) return;
      form._hrdLastGuestLookup = digits;
      fetch(api + '?mobile=' + encodeURIComponent(mobile), {
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
          fillCheckinFromGuest(form, result.data.guest);
          showToast('Returning guest details loaded.');
        })
        .catch(function () {});
    }

    mobileInput.addEventListener('input', function () {
      if (lookupTimer) clearTimeout(lookupTimer);
      lookupTimer = setTimeout(runLookup, 450);
    });
    mobileInput.addEventListener('blur', function () {
      if (lookupTimer) clearTimeout(lookupTimer);
      runLookup();
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
    ['hrd-ci-agency-datalist', 'hrd-reserve-agency-datalist'].forEach(function (listId) {
      var list = document.getElementById(listId);
      if (!list) return;
      list.innerHTML = '';
      (agencies || []).forEach(function (agency) {
        if (!agency || !agency.name) return;
        var opt = document.createElement('option');
        opt.value = agency.name;
        opt.setAttribute('data-gst', agency.gst || '');
        opt.setAttribute('data-address', agency.address || '');
        list.appendChild(opt);
      });
    });
    if (root) {
      try {
        root.setAttribute('data-agencies', JSON.stringify(agencies || []));
      } catch (err) {}
    }
  }

  function fillAgencyFieldsFromMaster(form, agency) {
    if (!form || !agency) return;
    setFormText(form, 'agencyName', agency.name || '');
    setFormText(form, 'agencyGst', agency.gst || '');
    setFormText(form, 'agencyAddress', agency.address || '');
    syncAgencyBillingHint(form);
  }

  function bindAgencyMasterControls(root, form) {
    if (!form) return;
    var nameInput =
      form.elements.agencyName ||
      $('#hrd-ci-agency-name', form) ||
      $('#hrd-reserve-agency-name', form);
    if (nameInput && nameInput.getAttribute('data-agency-pick-bound') !== '1') {
      nameInput.setAttribute('data-agency-pick-bound', '1');
      nameInput.addEventListener('change', function () {
        var typed = String(nameInput.value || '').trim().toLowerCase();
        if (!typed) return;
        var agencies = parseAgenciesData(root);
        for (var i = 0; i < agencies.length; i += 1) {
          if (String(agencies[i].name || '').trim().toLowerCase() === typed) {
            fillAgencyFieldsFromMaster(form, agencies[i]);
            return;
          }
        }
      });
    }

    var btn = form.querySelector('[data-hrd-agency-master]') || $('#hrd-ci-agency-master-btn', form);
    if (!btn || btn.getAttribute('data-agency-master-bound') === '1') return;
    btn.setAttribute('data-agency-master-bound', '1');
    btn.addEventListener('click', function () {
      var name = form.elements.agencyName
        ? String(form.elements.agencyName.value || '').trim()
        : '';
      var gst = form.elements.agencyGst
        ? String(form.elements.agencyGst.value || '').trim()
        : '';
      var address = form.elements.agencyAddress
        ? String(form.elements.agencyAddress.value || '').trim()
        : '';
      var masterUrl =
        (root && root.getAttribute('data-agency-master-url')) || '/agencies';
      if (!name) {
        if (typeof global.deSoftNavigate === 'function') {
          global.deSoftNavigate(masterUrl);
        } else {
          window.location.href = masterUrl;
        }
        return;
      }
      var createUrl =
        (root && root.getAttribute('data-agency-create-url')) || '/agencies/create';
      fetch(createUrl, {
        method: 'POST',
        credentials: 'same-origin',
        headers: apiHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({ name: name, gst: gst, address: address })
      })
        .then(function (resp) {
          return resp.json().then(function (data) {
            return { ok: resp.ok, data: data };
          });
        })
        .then(function (result) {
          if (!result.ok || !result.data || !result.data.ok) {
            showToast(
              (result.data && result.data.error) || 'Could not save agency.',
              true
            );
            return;
          }
          if (result.data.agencies) {
            syncAgencyDatalist(root, result.data.agencies);
          }
          if (result.data.agency) {
            fillAgencyFieldsFromMaster(form, result.data.agency);
          }
          showToast('Saved to Agency Master.');
        })
        .catch(function () {
          showToast('Could not save agency.', true);
        });
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
      uploadBtn.title = 'Upload ID document (JPG, PNG, HEIC, PDF)';
    }
    syncIdDocumentViewBtn(form, false);
  }

  function setIdDocumentUi(form, doc) {
    if (!form) return;
    var uploadName = $('#hrd-ci-id-upload-name', form);
    var uploadBtn = $('#hrd-ci-id-upload-btn', form);
    var name = (doc && (doc.displayName || doc.originalName)) || '';
    var path = (doc && doc.urlPath) || '';
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
        : 'Upload ID document (JPG, PNG, HEIC, PDF)';
    }
    syncIdDocumentViewBtn(form, !!path);
  }

  function viewIdDocument(form, pathOverride) {
    if (!form && !pathOverride) return;
    var url =
      pathOverride ||
      (form && form.elements.idDocumentPath && form.elements.idDocumentPath.value) ||
      '';
    if (!url) {
      showToast('Upload an ID document first.', true);
      return;
    }
    try {
      window.open(url, '_blank', 'noopener,noreferrer');
    } catch (err) {
      showToast('Could not open the document.', true);
    }
  }

  function uploadIdDocument(root, form, file) {
    if (!root || !form || !file) {
      return Promise.reject(new Error('missing file'));
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
    body.append('file', file, file.name);
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
        setIdDocumentUi(form, result.data.document);
        showToast('ID document uploaded and compressed.');
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
        var file = fileInput.files && fileInput.files[0];
        if (!file) return;
        uploadIdDocument(root, form, file).finally(function () {
          /* Allow re-selecting the same file name later. */
          fileInput.value = '';
        });
      });
    }
  }

  function openCheckinModal(root, opts) {
    opts = opts || {};
    var editing = !!opts.edit;
    var staySource =
      opts.stay ||
      (editing && lastRoom && lastRoom.stay ? lastRoom.stay : null);
    var modal = $('#hrd-checkin-modal', root);
    var form = $('#hrd-checkin-form', root);
    if (!modal || !form) {
      showToast('Check-in form unavailable.', true);
      return;
    }
    if (editing && !staySource) {
      showToast('No guest stay to edit.', true);
      return;
    }
    form.reset();
    form.setAttribute('data-edit-mode', editing ? '1' : '0');
    var today = todayISO();
    form.bookingNumber.value = 'Auto generated';
    setFormDate(form, 'bookingDate', today);
    setFormDate(form, 'checkInDate', today);
    form.nights.value = '1';
    setFormDate(form, 'checkOutDate', addDaysISO(today, 1));
    form.roomRate.value = String(defaultRateFor(root));
    form.advancePaid.value = '0';
    setFormDate(form, 'dateOfBirth', '');
    if (form.elements.agencyName) form.elements.agencyName.value = '';
    if (form.elements.agencyGst) form.elements.agencyGst.value = '';
    if (form.elements.agencyAddress) form.elements.agencyAddress.value = '';
    if (form.elements.agencyBilling) form.elements.agencyBilling.checked = false;
    clearAllSpecialCharges(form);
    clearIdDocumentFields(form);
    clearExtraGuests(form);
    bindAgencyBilling(form);
    syncAgencyBillingHint(form);
    bindMobileGuestLookup(root, form);
    bindAgencyMasterControls(root, form);
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
    resetListbox('hrd-ci-rate-plan', 'EP', 'EP — Room Only');
    resetListbox('hrd-ci-payment', '', 'Select');
    syncTotals(form);

    var roomLabel = $('#hrd-ci-room-label', root);
    if (roomLabel) {
      var number = root.getAttribute('data-room-number') || '';
      var typeLabel = root.getAttribute('data-room-type-label') || '';
      roomLabel.value = number
        ? number + (typeLabel ? ' - ' + typeLabel : '')
        : typeLabel || '';
    }

    var uploadName = $('#hrd-ci-id-upload-name', form) || $('.hrd-upload-text', form);
    var uploadBtn = $('#hrd-ci-id-upload-btn', form);
    if (uploadName) {
      uploadName.textContent = '';
      uploadName.hidden = true;
    }
    if (uploadBtn) {
      uploadBtn.classList.remove('is-filled', 'is-busy');
      uploadBtn.disabled = false;
      uploadBtn.title = 'Upload ID document (JPG, PNG, HEIC, PDF)';
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
      applyStayDraft(form, staySource);
      if (staySource.bookingNumber && form.bookingNumber) {
        form.bookingNumber.value = staySource.bookingNumber;
      }
    } else {
      var draft = readCheckinDraft(root);
      if (draft && draft.stay) {
        applyStayDraft(form, draft.stay);
      }
    }

    /* New check-in: default to current time (draft/stay may leave it blank). Still editable. */
    if (!editing) {
      var timeInput = form.elements.checkInTime;
      if (!timeInput || !String(timeInput.value || '').trim()) {
        setFormTime(form, 'checkInTime', nowTime());
      }
    }

    setInvoiceLockedFormFields(form, staySource || (lastRoom && lastRoom.stay) || null);

    var titleEl = $('#hrd-checkin-title', root);
    if (titleEl) titleEl.textContent = editing ? 'Edit Guest' : 'New Check-In';
    var saveBtn = $('#hrd-checkin-save', root);
    if (saveBtn) saveBtn.textContent = editing ? 'Save Changes' : 'Check-In';

    modal.hidden = false;
    modal.removeAttribute('hidden');
    modal.setAttribute('aria-hidden', 'false');
    document.body.classList.add('hrd-checkin-open');
    try {
      writeCheckinDraft(root, collectStay(form), { open: true });
    } catch (err) {}
    if (global.deFullscreen && typeof global.deFullscreen.reinit === 'function') {
      global.deFullscreen.reinit();
    } else if (global.deFullscreen && typeof global.deFullscreen.updateUi === 'function') {
      global.deFullscreen.updateUi();
    }
    setTimeout(function () {
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
      writeCheckinDraft(root, collectStay(form), meta || { open: true });
    } catch (err) {}
  }

  function closeCheckinModal(root, opts) {
    opts = opts || {};
    root = root || pageRoot();
    closeSpecialChargeModal(root);
    var modal = root && $('#hrd-checkin-modal', root);
    var form = root && $('#hrd-checkin-form', root);
    if (form && !opts.skipDraft) flushCheckinDraft(root, form, { open: false });
    if (form) form.setAttribute('data-edit-mode', '0');
    if (!modal) return;
    if (typeof global.closeHotelDatePickers === 'function') {
      global.closeHotelDatePickers();
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

  function closeReserveModal(root) {
    root = root || pageRoot();
    var modal = root && $('#hrd-reserve-modal', root);
    if (!modal) return;
    if (typeof global.closeHotelDatePickers === 'function') {
      global.closeHotelDatePickers();
    }
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

  function splitGuestName(fullName) {
    var raw = String(fullName || '').trim().replace(/\s+/g, ' ');
    if (!raw) {
      return { guestName: '', firstName: '', lastName: '' };
    }
    var parts = raw.split(' ');
    return {
      guestName: raw,
      firstName: parts[0] || '',
      lastName: parts.slice(1).join(' ')
    };
  }

  function openReserveModal(root) {
    var modal = $('#hrd-reserve-modal', root);
    var form = $('#hrd-reserve-form', root);
    if (!modal || !form) {
      showToast('Reserve form unavailable.', true);
      return;
    }
    if (mapStatus(root.getAttribute('data-room-status')) === 'occupied') {
      showToast('Check out the guest before reserving this room.', true);
      return;
    }

    var asOf = headerAsOfDate(root);
    var stay = lastRoom && lastRoom.stay && typeof lastRoom.stay === 'object' ? lastRoom.stay : null;
    var fromDate =
      toDateISO(stay && (stay.checkInDate || stay.check_in_date)) || asOf;
    var toDate =
      toDateISO(stay && (stay.checkOutDate || stay.check_out_date)) ||
      addDaysISO(fromDate, 1);
    if (toDate && fromDate && toDate <= fromDate) {
      toDate = addDaysISO(fromDate, 1);
    }

    setFormDate(form, 'reserveFrom', fromDate);
    setFormDate(form, 'reserveTo', toDate);

    var guestName =
      (stay && (stay.guestName || stay.guest_name)) ||
      [stay && stay.firstName, stay && stay.lastName].filter(Boolean).join(' ').trim() ||
      '';
    setFormText(form, 'guestName', guestName);
    setFormText(form, 'mobile', (stay && stay.mobile) || '');
    setFormText(form, 'email', (stay && stay.email) || '');
    setFormText(form, 'agencyName', (stay && stay.agencyName) || '');
    setFormText(form, 'agencyGst', (stay && stay.agencyGst) || '');
    setFormText(form, 'agencyAddress', (stay && stay.agencyAddress) || '');
    var billing = form.elements.agencyBilling;
    if (billing) billing.checked = !!(stay && stay.agencyBilling);

    bindDateChipPickers(modal);
    bindAgencyBilling(form);
    bindAgencyMasterControls(root, form);
    bindReservePartyToggle(form);
    syncAgencyBillingHint(form);
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
  }

  function submitReservation(root, form) {
    var api = root.getAttribute('data-room-api') || '';
    if (!api) {
      showToast('Room API unavailable.', true);
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

    var guestRaw = form.elements.guestName
      ? String(form.elements.guestName.value || '').trim()
      : '';
    var mobile = form.elements.mobile ? String(form.elements.mobile.value || '').trim() : '';
    var email = form.elements.email ? String(form.elements.email.value || '').trim() : '';
    if (!guestRaw) {
      showToast('Guest name is required.', true);
      return;
    }
    if (!mobile) {
      showToast('Mobile number is required.', true);
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
    var agencyBilling = !!(form.elements.agencyBilling && form.elements.agencyBilling.checked);
    if (agencyBilling && !agencyName) {
      showToast('Agency name is required for agency billing.', true);
      return;
    }

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
      agencyBilling: agencyBilling
    };
    if (agencyBilling && agencyName) {
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
        closeReserveModal(root);
        paintRoom(root, result.data.room);
        showToast('Room reserved.');
      })
      .catch(function (err) {
        showToast(err.message || 'Failed to reserve room.', true);
      })
      .then(function () {
        if (saveBtn) saveBtn.disabled = false;
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
    var modal = root && $('#hrd-merge-modal', root);
    if (!modal) return;
    modal.hidden = true;
    modal.setAttribute('hidden', '');
    modal.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('hrd-merge-open');
  }

  function fillMergeRoomOptions(listbox, rooms, currentId) {
    if (!listbox) return 0;
    var options = listbox.querySelector('.se-filter-listbox-options') || listbox;
    options.innerHTML = '';
    function addOption(value, label, selected) {
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'se-filter-listbox-option' + (selected ? ' is-selected' : '');
      btn.setAttribute('role', 'option');
      btn.setAttribute('data-value', value);
      btn.setAttribute('data-label', label);
      btn.setAttribute('aria-selected', selected ? 'true' : 'false');
      btn.textContent = label;
      options.appendChild(btn);
    }
    var candidates = (rooms || []).filter(function (room) {
      if (!room) return false;
      if (String(room.id) === String(currentId)) return false;
      if (room.isMergeMember) return false;
      return true;
    });
    addOption('', 'Select primary room', true);
    candidates.forEach(function (room) {
      var statusLabel = STATUS_LABELS[mapStatus(room.status)] || mapStatus(room.status);
      var label =
        'Room ' +
        (room.number || '') +
        (room.roomTypeLabel ? ' — ' + room.roomTypeLabel : '') +
        (statusLabel ? ' · ' + statusLabel : '') +
        (room.isMergePrimary ? ' (primary)' : '');
      addOption(room.id, label, false);
    });
    resetListbox('hrd-merge-to', '', 'Select primary room');
    return candidates.length;
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
    var number = root.getAttribute('data-room-number') || '';
    var fromInput = $('#hrd-merge-from', root);
    if (fromInput) fromInput.value = 'Room ' + number;
    var note = $('#hrd-merge-note', root);
    if (note) note.value = '';
    var hint = $('#hrd-merge-hint', root);
    resetListbox('hrd-merge-to', '', 'Loading rooms…');
    if (hint) {
      hint.textContent =
        'Any rooms can be merged onto one primary bill. Unmerge does not split the bill back.';
      hint.classList.remove('is-error');
    }
    if (typeof global.initEpListboxes === 'function') global.initEpListboxes();
    if (typeof global.rebindEpListbox === 'function') {
      Array.from(modal.querySelectorAll('[data-se-listbox]')).forEach(function (lb) {
        global.rebindEpListbox(lb);
      });
    }
    var listbox = $('#hrd-merge-to-listbox', root);
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
        var count = fillMergeRoomOptions(listbox, data.rooms || [], currentId);
        if (hint && !count) {
          hint.textContent = 'No other rooms available to merge into.';
          hint.classList.add('is-error');
        }
      })
      .catch(function (err) {
        resetListbox('hrd-merge-to', '', 'Could not load rooms');
        if (hint) {
          hint.textContent = err.message || 'Could not load rooms.';
          hint.classList.add('is-error');
        }
        showToast(err.message || 'Could not load rooms.', true);
      });
  }

  function submitMerge(root, form) {
    var toRoomId = (form.toRoomId && form.toRoomId.value) || '';
    if (!toRoomId) {
      showToast('Select a primary room to merge into.', true);
      return Promise.reject(new Error('validation'));
    }
    var api = root.getAttribute('data-room-api') || '';
    if (!api) {
      showToast('Room API unavailable.', true);
      return Promise.reject(new Error('missing api'));
    }
    var saveBtn = $('#hrd-merge-save', root);
    if (saveBtn) saveBtn.disabled = true;
    var note = (form.note && form.note.value) || '';
    var fromRoomId = root.getAttribute('data-room-id') || '';

    return fetch(api, {
      method: 'PUT',
      credentials: 'same-origin',
      headers: apiHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({
        action: 'merge_rooms',
        fromRoomId: fromRoomId,
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
          throw new Error((result.data && result.data.error) || 'Merge failed.');
        }
        closeMergeModal(root);
        var primary = result.data.primaryRoom || result.data.room;
        showToast(
          'Rooms merged. Billing is on Room ' +
            ((primary && primary.number) || toRoomId) +
            '.'
        );
        if (primary && primary.id) {
          navigateTo('/hotel/rooms/' + encodeURIComponent(primary.id));
        } else if (result.data.memberRoom) {
          paintRoom(root, result.data.memberRoom);
        }
        return result.data;
      })
      .catch(function (err) {
        if (err.message !== 'validation') {
          showToast(err.message || 'Merge failed.', true);
        }
        throw err;
      })
      .finally(function () {
        if (saveBtn) saveBtn.disabled = false;
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
        ? 'Unmerge all rooms in this billing group? Folio charges stay on the primary.'
        : 'Unmerge this room from the shared bill? Folio charges stay on the primary.';
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

    function val(name) {
      var el = form.elements[name];
      return el ? String(el.value || '').trim() : '';
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
      idDocumentName: displayName || stored,
      idDocumentPath: val('idDocumentPath'),
      idDocumentMime: val('idDocumentMime'),
      additionalGuests: collectExtraGuests(form),
      agencyName: val('agencyName'),
      agencyGst: val('agencyGst'),
      agencyAddress: val('agencyAddress'),
      agencyBilling: !!(form.elements.agencyBilling && form.elements.agencyBilling.checked),
      bookingNumber: '',
      bookingDate: val('bookingDate'),
      checkInDate: val('checkInDate'),
      checkInTime: val('checkInTime'),
      checkOutDate: val('checkOutDate'),
      nights: Number(val('nights') || 1),
      adults: Number(val('adults') || 1),
      children: Number(val('children') || 0),
      ratePlan: val('ratePlan'),
      roomRate: Number(val('roomRate') || 0),
      totalRate: Number(val('totalRate') || 0),
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
    var stay = collectStay(form);
    var editing = form && form.getAttribute('data-edit-mode') === '1';
    if (editing && lastRoom && lastRoom.stay) {
      var prev = lastRoom.stay;
      stay.bookingNumber = prev.bookingNumber || stay.bookingNumber || '';
      stay.folioCharges = Array.isArray(prev.folioCharges) ? prev.folioCharges : [];
      stay.checkedInAt = prev.checkedInAt || '';
      stay.transferCount = prev.transferCount || 0;
      stay.transferHistory = Array.isArray(prev.transferHistory)
        ? prev.transferHistory
        : [];
    }
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
    if (stay.agencyBilling && !stay.agencyName) {
      showToast('Agency Name is required for Agency Billing.', true);
      return Promise.reject(new Error('validation'));
    }
    if (stay.agencyBilling) {
      stay.invoiceTo = stay.agencyName;
      stay.billingName = stay.agencyName;
    } else {
      stay.invoiceTo = '';
      stay.billingName = '';
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
        closeCheckinModal(root, { skipDraft: true });
        paintRoom(root, result.data.room);
        showToast(editing ? 'Guest details updated.' : 'Guest checked in successfully.');
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

    var genInvoice = event.target.closest('#hrd-generate-invoice');
    if (genInvoice && root.contains(genInvoice)) {
      event.preventDefault();
      event.stopPropagation();
      var roomId = root.getAttribute('data-room-id') || '';
      if (!roomId) return;
      navigateTo('/hotel/rooms/' + encodeURIComponent(roomId) + '/invoice');
      return;
    }

    var viewInvoice = event.target.closest('#hrd-charges-invoice-no');
    if (viewInvoice && root.contains(viewInvoice) && !viewInvoice.hidden) {
      event.preventDefault();
      event.stopPropagation();
      if (lastRoom && lastRoom.stay && typeof global.openHotelRoomInvoice === 'function') {
        if (!global.openHotelRoomInvoice(lastRoom, { autoPrint: false })) {
          showToast('Allow pop-ups to view the invoice.', true);
        }
      } else {
        showToast('Invoice preview unavailable.', true);
      }
      return;
    }

    var recordPay = event.target.closest('#hrd-record-payment');
    if (recordPay && root.contains(recordPay)) {
      event.preventDefault();
      event.stopPropagation();
      var payRoomId = root.getAttribute('data-room-id') || '';
      if (!payRoomId) return;
      navigateTo(
        '/hotel/rooms/' + encodeURIComponent(payRoomId) + '/invoice?settle=1'
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
    if (!openSplitList) {
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

    var mergeModal = $('#hrd-merge-modal', root);
    if (mergeModal && !mergeModal.hidden && event.target === mergeModal) {
      event.preventDefault();
      event.stopPropagation();
      closeMergeModal(root);
      return;
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
      if (willOpen) {
        menu.hidden = false;
        menu.removeAttribute('hidden');
        moreBtn.setAttribute('aria-expanded', 'true');
      }
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
      var checkinForm = $('#hrd-checkin-form', root);
      var guestRow = viewDocBtn.closest('[data-extra-guest]');
      if (guestRow) {
        var guestPath =
          guestRow.querySelector('[data-extra-guest-doc-path]');
        viewIdDocument(
          checkinForm,
          guestPath ? String(guestPath.value || '').trim() : ''
        );
      } else {
        viewIdDocument(checkinForm);
      }
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
        openCheckinModal(root, { edit: true });
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
      if (actionBtn.closest('#hrd-checkin-modal') || actionBtn.closest('#hrd-transfer-modal') || actionBtn.closest('#hrd-merge-modal') || actionBtn.closest('#hrd-reserve-modal') || actionBtn.closest('#hrd-invoice-modal')) {
        return;
      }
      event.preventDefault();
      event.stopPropagation();
      closeMoreMenu(root);
      var action = actionBtn.getAttribute('data-action');
      if (action === 'checkin') {
        if (mapStatus(root.getAttribute('data-room-status')) === 'occupied') {
          showToast('Guest already checked in. Use Check Out first.');
          return;
        }
        openCheckinModal(root);
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
      if (action === 'set-primary') {
        setMergePrimary(root);
        return;
      }
      if (action === 'reserve') {
        openReserveModal(root);
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
      event.target.id === 'hrd-charges-invoice-no' &&
      !event.target.hidden
    ) {
      event.preventDefault();
      if (lastRoom && lastRoom.stay && typeof global.openHotelRoomInvoice === 'function') {
        global.openHotelRoomInvoice(lastRoom, { autoPrint: false });
      }
      return;
    }
    if (event.key === 'Escape') {
      /* Close open date picker first, then listbox, then modal. */
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
      var transferModal = $('#hrd-transfer-modal', root);
      if (transferModal && !transferModal.hidden) {
        event.preventDefault();
        closeTransferModal(root);
        return;
      }
      var mergeModal = $('#hrd-merge-modal', root);
      if (mergeModal && !mergeModal.hidden) {
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
      name === 'checkOutDate'
    ) {
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
      syncTotals(form);
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
      var file = event.target.files && event.target.files[0];
      if (!guestRow || !file) return;
      uploadExtraGuestDocument(root, guestRow, file).finally(function () {
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
    var transferForm = $('#hrd-transfer-form', root);
    if (transferForm && event.target === transferForm) {
      event.preventDefault();
      event.stopPropagation();
      submitTransfer(root, transferForm);
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
    document.__hotelRoomDetailDocBound = true;
  }

  function loadRoomIfNeeded(root) {
    var api = root.getAttribute('data-room-api') || '';
    if (!api) return;
    fetch(api, {
      method: 'GET',
      credentials: 'same-origin',
      headers: apiHeaders()
    })
      .then(function (resp) {
        return resp.json();
      })
      .then(function (data) {
        if (data && data.ok && data.room) paintRoom(root, data.room);
      })
      .catch(function () {});
  }

  function initHotelRoomDetailPage() {
    bindDocumentDelegation();
    var root = pageRoot();
    if (!root) return;
    var main = root.closest('.de-main-wrapper');
    if (main) main.classList.remove('is-soft-nav-loading');
    document.documentElement.classList.remove('de-soft-navigating');

    if (typeof global.initEpListboxes === 'function') {
      global.initEpListboxes();
    }

    loadHotelTaxRates(function () {
      if (lastRoom) paintRoom(root, lastRoom);
    });

    bindDateChipPickers(root);
    var headerDate = $('#hrd-header-date', root);
    if (headerDate && !String(headerDate.value || '').trim()) {
      if (typeof global.setHotelDateValue === 'function') {
        global.setHotelDateValue(headerDate, todayISO());
      } else {
        headerDate.value = todayISO();
      }
    } else if (headerDate && typeof global.syncHotelDateChip === 'function') {
      global.syncHotelDateChip(headerDate);
    }
    if (headerDate && headerDate.getAttribute('data-hrd-kpi-bound') !== '1') {
      headerDate.setAttribute('data-hrd-kpi-bound', '1');
      headerDate.addEventListener('change', function () {
        if (lastRoom) paintRoom(root, lastRoom);
      });
    }

    var status = mapStatus(root.getAttribute('data-room-status'));
    paintRoom(root, {
      status: status,
      id: root.getAttribute('data-room-id'),
      number: root.getAttribute('data-room-number'),
      roomType: root.getAttribute('data-room-type'),
      roomTypeLabel: root.getAttribute('data-room-type-label'),
      stay: lastRoom && lastRoom.id === root.getAttribute('data-room-id') ? lastRoom.stay : null
    });
    loadRoomIfNeeded(root);

    /* Refresh / soft-nav: restore open check-in sheet with draft fields. */
    var pendingDraft = readCheckinDraft(root);
    if (
      pendingDraft &&
      pendingDraft.open &&
      mapStatus(root.getAttribute('data-room-status')) !== 'occupied'
    ) {
      openCheckinModal(root);
    }
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
  }

  global.initHotelRoomDetailPage = initHotelRoomDetailPage;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initHotelRoomDetailPage);
  } else {
    initHotelRoomDetailPage();
  }
})(window);
