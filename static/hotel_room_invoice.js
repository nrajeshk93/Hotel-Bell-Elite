/**
 * Hotel Bell Elite — branded room stay invoice preview / print.
 */
(function (global) {
  'use strict';

  var HOTEL = {
    name: 'HOTEL BELL ELITE',
    tagline: 'COMFORT. ELEGANCE. HOSPITALITY.',
    address: 'Gurudwara Line, Aberdeen Bazar, Port Blair - 744101, Andaman India',
    phone: '03192218267',
    email: 'hotelbellelite@gmail.com',
    website: 'www.hotelbellelite.in',
    gst: '35AANFH8592H1ZS',
    markUrl: '/static/hbe_mark_form.png'
  };

  var CGST_RATE = 0.025;
  var UGST_RATE = 0.025;
  var SGST_RATE = UGST_RATE;
  var CSS_HREF = '/static/hotel_room_invoice.css?v=6';

  function absoluteAssetUrl(path) {
    var raw = String(path || '').trim();
    if (!raw) return '';
    if (/^(https?:|data:|blob:)/i.test(raw)) return raw;
    try {
      if (global.location && global.location.origin) {
        if (raw.charAt(0) === '/') return global.location.origin + raw;
        return new URL(raw, global.location.href).href;
      }
    } catch (err) {}
    return raw;
  }

  var ONES = [
    '',
    'One',
    'Two',
    'Three',
    'Four',
    'Five',
    'Six',
    'Seven',
    'Eight',
    'Nine',
    'Ten',
    'Eleven',
    'Twelve',
    'Thirteen',
    'Fourteen',
    'Fifteen',
    'Sixteen',
    'Seventeen',
    'Eighteen',
    'Nineteen'
  ];
  var TENS = [
    '',
    '',
    'Twenty',
    'Thirty',
    'Forty',
    'Fifty',
    'Sixty',
    'Seventy',
    'Eighty',
    'Ninety'
  ];

  function escapeHtml(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function toDateISO(value) {
    var raw = String(value || '').trim();
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

  function todayISO() {
    var d = new Date();
    return (
      d.getFullYear() +
      '-' +
      String(d.getMonth() + 1).padStart(2, '0') +
      '-' +
      String(d.getDate()).padStart(2, '0')
    );
  }

  function prettyDate(iso) {
    var parts = String(toDateISO(iso) || '').split('-');
    if (parts.length !== 3) return String(iso || '—');
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
    var mi = Number(parts[1]) - 1;
    if (mi < 0 || mi > 11) return String(iso || '—');
    return (
      String(Number(parts[2])).padStart(2, '0') +
      '-' +
      months[mi] +
      '-' +
      parts[0]
    );
  }

  function money(n) {
    var num = Number(n);
    if (!isFinite(num)) num = 0;
    return num.toLocaleString('en-IN', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    });
  }

  function twoDigitWords(n) {
    n = Number(n) || 0;
    if (n < 20) return ONES[n];
    var t = Math.floor(n / 10);
    var o = n % 10;
    return (TENS[t] + (o ? ' ' + ONES[o] : '')).trim();
  }

  function threeDigitWords(n) {
    n = Number(n) || 0;
    if (!n) return '';
    var h = Math.floor(n / 100);
    var r = n % 100;
    var out = '';
    if (h) out += ONES[h] + ' Hundred';
    if (r) out += (out ? ' ' : '') + twoDigitWords(r);
    return out;
  }

  function amountInWords(amount) {
    var n = Math.round(Number(amount || 0));
    if (!isFinite(n) || n < 0) n = 0;
    if (n === 0) return 'Zero Only';

    var crore = Math.floor(n / 10000000);
    n %= 10000000;
    var lakh = Math.floor(n / 100000);
    n %= 100000;
    var thousand = Math.floor(n / 1000);
    n %= 1000;
    var hundred = n;

    var parts = [];
    if (crore) parts.push(threeDigitWords(crore) + ' Crore');
    if (lakh) parts.push(threeDigitWords(lakh) + ' Lakh');
    if (thousand) parts.push(threeDigitWords(thousand) + ' Thousand');
    if (hundred) parts.push(threeDigitWords(hundred));
    return parts.join(' ') + ' Only';
  }

  function guestDisplayName(stay) {
    if (!stay) return 'Guest';
    var name = String(stay.guestName || '').trim();
    if (name) return name;
    return (
      [stay.firstName, stay.lastName].filter(Boolean).join(' ').trim() || 'Guest'
    );
  }

  function billToBlock(stay) {
    var agencyBilling = !!(stay && stay.agencyBilling && stay.agencyName);
    var name = agencyBilling
      ? String(stay.invoiceTo || stay.billingName || stay.agencyName || '').trim() ||
        guestDisplayName(stay)
      : guestDisplayName(stay);
    var address = agencyBilling
      ? String(stay.agencyAddress || stay.address || '').trim()
      : String(stay.address || '').trim();
    var phone = String(stay.mobile || stay.phone || '').trim();
    if (phone && stay.mobileCountry) {
      phone = String(stay.mobileCountry).trim() + ' ' + phone;
    }
    var email = String(stay.email || '').trim();
    var gst = agencyBilling ? String(stay.agencyGst || stay.agency_gst || '').trim() : '';
    return {
      name: name,
      address: address,
      phone: phone,
      email: email,
      gst: gst,
      agencyBilling: agencyBilling
    };
  }

  function isLiveInHouseStay(room, stay) {
    var status = String((room && room.status) || '').trim().toLowerCase();
    // Only currently in-house rooms should accrue calendar overstay vs "today".
    if (status === 'occupied' || status === 'checked_in' || status === 'due_out') {
      return true;
    }
    // Checked-out / vacant / imported ledger snapshots must keep booked nights only.
    if (
      status === 'checked_out' ||
      status === 'vacant' ||
      status === 'available' ||
      status === 'dirty' ||
      status === 'maintenance'
    ) {
      return false;
    }
    if (stay && (stay.invoiceGenerated || stay.source === 'room_sales_import')) {
      return false;
    }
    if (room && (room.importedFrom || room.status === 'checked_out')) {
      return false;
    }
    return false;
  }

  function overstayNightsFromStay(stay, room) {
    var fromStay = Number(stay && stay.overstayNights);
    if (isFinite(fromStay) && fromStay > 0) return Math.floor(fromStay);
    // Do not invent overstay lines for historical invoices by comparing checkout to today.
    if (!isLiveInHouseStay(room, stay)) return 0;
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

  function billableNightsFromStay(stay, room) {
    var booked = Math.max(1, Number((stay && stay.nights) || 1));
    var fromStay = Number(stay && stay.billableNights);
    if (isFinite(fromStay) && fromStay >= booked) return Math.floor(fromStay);
    return Math.max(1, booked + overstayNightsFromStay(stay, room));
  }

  function buildInvoiceLines(room) {
    var stay = (room && room.stay) || {};
    var lines = [];
    var checkIn = toDateISO(stay.checkInDate || stay.check_in_date);
    var nights = Math.max(1, Number(stay.nights || 1));
    var overstayNights = overstayNightsFromStay(stay, room);
    var billableNights = billableNightsFromStay(stay, room);
    var roomRate = Math.max(0, Number(stay.roomRate || 0));
    var nightlyRates = Array.isArray(stay.nightlyRates) ? stay.nightlyRates : [];
    var nightlyByDate = {};
    nightlyRates.forEach(function (row) {
      if (!row) return;
      var day = toDateISO(row.date);
      if (!day) return;
      nightlyByDate[day] = {
        roomRate: Math.max(0, Number(row.roomRate != null ? row.roomRate : 0)),
        ratePlan: String(row.ratePlan || '').trim()
      };
    });
    var roomLabel =
      (room && (room.roomTypeLabel || room.roomType)) ||
      'Room Tariff';
    roomLabel = String(roomLabel).replace(/_/g, ' ');
    if (roomLabel && !/tariff|room/i.test(roomLabel)) {
      roomLabel = roomLabel + ' Tariff';
    } else if (!/tariff/i.test(roomLabel)) {
      roomLabel = roomLabel + (roomLabel ? ' ' : '') + 'Tariff';
    }

    function nightRateFor(index, nightDate) {
      if (nightDate && nightlyByDate[nightDate]) {
        return nightlyByDate[nightDate].roomRate;
      }
      if (nightlyRates.length) {
        var row =
          index < nightlyRates.length
            ? nightlyRates[index]
            : nightlyRates[nightlyRates.length - 1];
        if (row) return Math.max(0, Number(row.roomRate || 0));
      }
      return roomRate;
    }

    function nightPlanFor(index, nightDate) {
      if (nightDate && nightlyByDate[nightDate] && nightlyByDate[nightDate].ratePlan) {
        return nightlyByDate[nightDate].ratePlan;
      }
      if (nightlyRates.length) {
        var row =
          index < nightlyRates.length
            ? nightlyRates[index]
            : nightlyRates[nightlyRates.length - 1];
        if (row && row.ratePlan) return String(row.ratePlan);
      }
      return String(stay.ratePlan || '').trim();
    }

    if ((roomRate > 0 || nightlyRates.length) && checkIn) {
      for (var i = 0; i < billableNights; i++) {
        var nightDate = addDaysISO(checkIn, i);
        var isOverstay = i >= nights;
        var nightRate = nightRateFor(i, nightDate);
        if (!(nightRate > 0)) continue;
        var plan = nightPlanFor(i, nightDate);
        var desc = isOverstay ? roomLabel + ' (Overstay)' : roomLabel;
        if (plan) desc += ' · ' + plan;
        lines.push({
          description: desc,
          date: nightDate,
          qty: 1,
          rate: nightRate,
          amount: nightRate
        });
      }
    } else if (roomRate > 0) {
      lines.push({
        description: roomLabel,
        date: checkIn,
        qty: billableNights,
        rate: roomRate,
        amount: Math.round(roomRate * billableNights * 100) / 100
      });
    }

    var extras = [
      { label: 'Extra Bed', amount: Number(stay.extraBedAmount || 0) },
      { label: 'Early Check-in', amount: Number(stay.earlyCheckinAmount || 0) },
      { label: 'Late Check-out', amount: Number(stay.lateCheckoutAmount || 0) }
    ];
    extras.forEach(function (row) {
      if (!(row.amount > 0)) return;
      lines.push({
        description: row.label,
        date: checkIn,
        qty: 1,
        rate: row.amount,
        amount: row.amount
      });
    });

    var folio = Array.isArray(stay.folioCharges) ? stay.folioCharges : [];
    var restaurant = 0;
    var bar = 0;
    folio.forEach(function (item) {
      if (!item) return;
      var amount = Number(item.amount || 0);
      if (!(amount > 0)) return;
      var kind = String(item.kind || '').toLowerCase();
      var at = toDateISO(item.at) || checkIn;
      if (kind === 'restaurant_room_transfer') {
        restaurant += amount;
        return;
      }
      if (kind === 'bar_room_transfer') {
        bar += amount;
        return;
      }
      lines.push({
        description: item.label || 'Other Charge',
        date: at,
        qty: 1,
        rate: amount,
        amount: amount
      });
    });
    if (restaurant > 0) {
      lines.push({
        description: 'Restaurant Room Transfer',
        date: checkIn,
        qty: 1,
        rate: Math.round(restaurant * 100) / 100,
        amount: Math.round(restaurant * 100) / 100
      });
    }
    if (bar > 0) {
      lines.push({
        description: 'Bar Room Transfer',
        date: checkIn,
        qty: 1,
        rate: Math.round(bar * 100) / 100,
        amount: Math.round(bar * 100) / 100
      });
    }

    return lines;
  }

  function iconPin() {
    return (
      '<svg class="hri-contact-ico" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 21s7-4.35 7-10a7 7 0 1 0-14 0c0 5.65 7 10 7 10z" fill="none" stroke="currentColor" stroke-width="1.8"/><circle cx="12" cy="11" r="2.2" fill="none" stroke="currentColor" stroke-width="1.8"/></svg>'
    );
  }
  function iconPhone() {
    return (
      '<svg class="hri-contact-ico" viewBox="0 0 24 24" aria-hidden="true"><path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1.9.3 1.8.6 2.6a2 2 0 0 1-.5 2.1L8.1 9.9a16 16 0 0 0 6 6l1.5-1.1a2 2 0 0 1 2.1-.4c.8.3 1.7.5 2.6.6a2 2 0 0 1 1.7 1.9z" fill="none" stroke="currentColor" stroke-width="1.8"/></svg>'
    );
  }
  function iconMail() {
    return (
      '<svg class="hri-contact-ico" viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="2" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="m3 7 9 6 9-6" fill="none" stroke="currentColor" stroke-width="1.8"/></svg>'
    );
  }
  function iconWeb() {
    return (
      '<svg class="hri-contact-ico" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M3 12h18M12 3c3 3.5 3 14.5 0 18M12 3c-3 3.5-3 14.5 0 18" fill="none" stroke="currentColor" stroke-width="1.8"/></svg>'
    );
  }
  function iconDoc() {
    return (
      '<svg class="hri-contact-ico" viewBox="0 0 24 24" aria-hidden="true"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M14 3v5h5M9 13h6M9 17h4" fill="none" stroke="currentColor" stroke-width="1.8"/></svg>'
    );
  }
  function iconUser() {
    return (
      '<svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="8" r="3.5" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M5 19c1.5-3.5 4-5 7-5s5.5 1.5 7 5" fill="none" stroke="currentColor" stroke-width="1.8"/></svg>'
    );
  }

  function hotelInvoiceRoomLabel(room) {
    var stay = room && room.stay && typeof room.stay === 'object' ? room.stay : {};
    var label =
      (stay && (stay.mergeRoomLabel || stay.merge_room_label)) ||
      (room && (room.mergeRoomLabel || room.mergeLabel || room.numberDisplay)) ||
      '';
    label = String(label || '').trim();
    if (label && label.toLowerCase().indexOf('bill:') !== 0) return label;
    var numbers = stay.mergeRoomNumbers || stay.merge_room_numbers || room.mergeRoomNumbers;
    if (Array.isArray(numbers) && numbers.length) {
      var cleaned = [];
      numbers.forEach(function (n) {
        var s = String(n || '').trim();
        if (s && cleaned.indexOf(s) === -1) cleaned.push(s);
      });
      if (cleaned.length) return cleaned.join(' + ');
    }
    if (
      room &&
      room.isMergePrimary &&
      Array.isArray(room.mergePartnerNumbers) &&
      room.mergePartnerNumbers.length
    ) {
      return (
        String(room.number || '').trim() +
        ' + ' +
        room.mergePartnerNumbers
          .map(function (n) {
            return String(n || '').trim();
          })
          .filter(Boolean)
          .join(' + ')
      );
    }
    return String((room && room.number) || '').trim();
  }

  function buildHotelRoomInvoiceHtml(room, opts) {
    opts = opts || {};
    var stay = (room && room.stay) || {};
    var lines = buildInvoiceLines(room);
    var subtotal = Math.round(
      lines.reduce(function (sum, row) {
        return sum + Number(row.amount || 0);
      }, 0) * 100
    ) / 100;
    if (!(subtotal > 0) && stay.estimatedTotal != null && !(Number(stay.discountAmount) > 0)) {
      subtotal = Math.round(Number(stay.estimatedTotal || 0) * 100) / 100;
    }
    if (stay.estimatedTotal != null && Number(stay.discountAmount) > 0) {
      var grossFromStay =
        Math.round(
          (Number(stay.estimatedTotal || 0) + Number(stay.discountAmount || 0)) * 100
        ) / 100;
      if (grossFromStay > subtotal) subtotal = grossFromStay;
    }
    var discountType = stay.discountType || stay.discount_type || 'pct';
    var discountValue = Number(
      stay.discountValue != null ? stay.discountValue : stay.discount_value || 0
    );
    var discount =
      stay.discountAmount != null
        ? Math.round(Number(stay.discountAmount || 0) * 100) / 100
        : 0;
    if (!(discount > 0) && discountValue > 0) {
      if (discountType === 'inr') {
        discount = Math.min(subtotal, discountValue);
      } else {
        discount = Math.round(subtotal * (Math.min(100, discountValue) / 100) * 100) / 100;
      }
    }
    if (discount > subtotal) discount = subtotal;
    /* Stay amounts are tax-inclusive — extract CGST/UGST; total stays inclusive. */
    var inclusive = Math.round(Math.max(0, subtotal - discount) * 100) / 100;
    var factor = 1 + CGST_RATE + UGST_RATE;
    var taxable =
      factor > 0 ? Math.round((inclusive / factor) * 100) / 100 : inclusive;
    var cgst = Math.round(taxable * CGST_RATE * 100) / 100;
    var ugst = Math.round((inclusive - taxable - cgst) * 100) / 100;
    if (ugst < 0) ugst = 0;
    var total = inclusive;

    /* Invoice line amounts shown as taxable (exclusive) so tax rows add cleanly. */
    if (factor > 0) {
      lines = lines.map(function (row) {
        var amt = Math.round(Number(row.amount || 0) * 100) / 100;
        var rate = Math.round(Number(row.rate || 0) * 100) / 100;
        return Object.assign({}, row, {
          amount: Math.round((amt / factor) * 100) / 100,
          rate: rate > 0 ? Math.round((rate / factor) * 100) / 100 : rate
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

    var checkIn = toDateISO(stay.checkInDate || stay.check_in_date);
    var checkOut = toDateISO(stay.checkOutDate || stay.check_out_date);
    var invoiceDate =
      toDateISO(stay.invoiceGeneratedAt) ||
      toDateISO(opts.invoiceDate) ||
      toDateISO(new Date().toISOString().slice(0, 10));
    var invoiceNo = String(stay.invoiceNumber || '—').trim() || '—';
    var bookingNo = String(stay.bookingNumber || '—').trim() || '—';
    var adults = Math.max(1, Number(stay.adults || 1));
    var children = Math.max(0, Number(stay.children || 0));
    var guestsLabel =
      adults +
      ' Adult' +
      (adults === 1 ? '' : 's') +
      (children
        ? ' · ' + children + ' Child' + (children === 1 ? '' : 'ren')
        : '');
    var billTo = billToBlock(stay);
    var roomNumber = hotelInvoiceRoomLabel(room);
    var roomNumberSingle = (room && room.number) || '';

    var minRows = 4;
    var rowsHtml = lines
      .map(function (row, idx) {
        return (
          '<tr class="hri-line">' +
          '<td class="center">' +
          (idx + 1) +
          '</td>' +
          '<td>' +
          escapeHtml(row.description) +
          (roomNumberSingle && /tariff/i.test(row.description)
            ? ' <span class="muted">(Room ' +
              escapeHtml(roomNumberSingle) +
              ')</span>'
            : '') +
          '</td>' +
          '<td>' +
          escapeHtml(prettyDate(row.date)) +
          '</td>' +
          '<td class="center">' +
          escapeHtml(String(row.qty || 1)) +
          '</td>' +
          '<td class="num">' +
          money(row.rate) +
          '</td>' +
          '<td class="num">' +
          money(row.amount) +
          '</td>' +
          '</tr>'
        );
      })
      .join('');
    for (var pad = lines.length; pad < minRows; pad++) {
      rowsHtml +=
        '<tr class="hri-pad-row"><td class="center">&nbsp;</td><td></td><td></td><td></td><td></td><td></td></tr>';
    }

    var mastheadHtml =
      '<div class="hri-header">' +
      '<div class="hri-brand">' +
      '<img class="hri-mark" src="' +
      escapeHtml(absoluteAssetUrl(HOTEL.markUrl)) +
      '" alt="Hotel Bell Elite">' +
      '<div class="hri-brand-copy">' +
      '<h1 class="hri-brand-name">' +
      escapeHtml(HOTEL.name) +
      '</h1>' +
      '<div class="hri-brand-rule" aria-hidden="true"><span class="hri-brand-rule-ornament"></span></div>' +
      '<p class="hri-brand-tag">' +
      escapeHtml(HOTEL.tagline) +
      '</p></div></div>' +
      '<div class="hri-contact">' +
      '<div class="hri-contact-row">' +
      iconPin() +
      '<span>' +
      escapeHtml(HOTEL.address) +
      '</span></div>' +
      '<div class="hri-contact-row">' +
      iconPhone() +
      '<span>' +
      escapeHtml(HOTEL.phone) +
      '</span></div>' +
      '<div class="hri-contact-row">' +
      iconMail() +
      '<span>' +
      escapeHtml(HOTEL.email) +
      '</span></div>' +
      '<div class="hri-contact-row">' +
      iconWeb() +
      '<span>' +
      escapeHtml(HOTEL.website) +
      '</span></div>' +
      '<div class="hri-contact-row">' +
      iconDoc() +
      '<span><strong>GST:</strong> ' +
      escapeHtml(HOTEL.gst) +
      '</span></div>' +
      '</div></div>' +
      '<div class="hri-meta-row">' +
      '<div><h2 class="hri-title">INVOICE</h2>' +
      '<ul class="hri-meta-list">' +
      '<li><span class="k">Invoice No.</span><span class="v">' +
      escapeHtml(invoiceNo) +
      '</span></li>' +
      '<li><span class="k">Invoice Date</span><span class="v">' +
      escapeHtml(prettyDate(invoiceDate)) +
      '</span></li>' +
      '<li><span class="k">Booking No.</span><span class="v">' +
      escapeHtml(bookingNo) +
      '</span></li>' +
      '<li><span class="k">Room' +
      (roomNumber.indexOf('+') >= 0 ? 's' : '') +
      '</span><span class="v">' +
      escapeHtml(roomNumber || '—') +
      '</span></li>' +
      '<li><span class="k">Check In</span><span class="v">' +
      escapeHtml(prettyDate(checkIn)) +
      '</span></li>' +
      '<li><span class="k">Check Out</span><span class="v">' +
      escapeHtml(prettyDate(checkOut)) +
      '</span></li>' +
      '<li><span class="k">Guests</span><span class="v">' +
      escapeHtml(guestsLabel) +
      '</span></li>' +
      '</ul></div>' +
      '<aside class="hri-billto"><div class="hri-billto-head">' +
      iconUser() +
      ' Bill To</div><div class="hri-billto-body">' +
      '<div class="name">' +
      escapeHtml(billTo.name) +
      '</div>' +
      (billTo.address
        ? '<div class="muted">' + escapeHtml(billTo.address) + '</div>'
        : '') +
      (billTo.gst
        ? '<div class="muted"><strong>GST:</strong> ' + escapeHtml(billTo.gst) + '</div>'
        : '') +
      (billTo.phone
        ? '<div class="muted">Phone: ' + escapeHtml(billTo.phone) + '</div>'
        : '') +
      (billTo.email
        ? '<div class="muted">Email: ' + escapeHtml(billTo.email) + '</div>'
        : '') +
      '</div></aside></div>';

    var footerHtml =
      '<div class="hri-bottom">' +
      '<section class="hri-notes"><div class="hri-notes-head">' +
      iconDoc() +
      ' Notes</div><div class="hri-notes-body">Thank you for staying with us. We look forward to welcoming you again.</div></section>' +
      '<section class="hri-totals">' +
      '<div class="hri-totals-row"><span class="k">Subtotal</span><span class="v">' +
      money(subtotal) +
      '</span></div>' +
      (discount > 0
        ? '<div class="hri-totals-row"><span class="k">Discount' +
          (discountType === 'pct' && discountValue > 0
            ? ' (' + discountValue + '%)'
            : '') +
          '</span><span class="v">−' +
          money(discount) +
          '</span></div>'
        : '') +
      '<div class="hri-totals-row"><span class="k">CGST (2.5%)</span><span class="v">' +
      money(cgst) +
      '</span></div>' +
      '<div class="hri-totals-row"><span class="k">UGST (2.5%)</span><span class="v">' +
      money(ugst) +
      '</span></div>' +
      '<div class="hri-totals-row is-total"><span class="k">Total Amount (₹)</span><span class="v">' +
      money(total) +
      '</span></div>' +
      '<div class="hri-words">Amount in Words: <strong>' +
      escapeHtml(amountInWords(total)) +
      '</strong></div>' +
      '</section></div>' +
      '<div class="hri-thanks">Thank You &amp; Safe Travels!</div>' +
      '<div class="hri-values">' +
      '<div class="hri-value"><div class="hri-value-ico"><svg viewBox="0 0 24 24"><path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/></svg></div>Comfortable Stay</div>' +
      '<div class="hri-value"><div class="hri-value-ico"><svg viewBox="0 0 24 24"><polygon points="12 2 15 9 22 9 17 14 19 21 12 17 5 21 7 14 2 9 9 9"/></svg></div>Quality Service</div>' +
      '<div class="hri-value"><div class="hri-value-ico"><svg viewBox="0 0 24 24"><path d="M5 16c0-4 3-7 7-7s7 3 7 7"/><path d="M8 9V6a4 4 0 0 1 8 0v3"/><path d="M4 16h16v4H4z"/></svg></div>Memorable Experience</div>' +
      '<div class="hri-value"><div class="hri-value-ico"><svg viewBox="0 0 24 24"><path d="M20 13c0 5-3.5 7.5-8 10-4.5-2.5-8-5-8-10V6l8-3 8 3z"/></svg></div>We Value You</div>' +
      '</div>' +
      '<div class="hri-sign"><div class="hri-sign-box"><div class="hri-sign-line"></div><div class="hri-sign-title">Authorised Signatory</div><div class="hri-sign-sub">Hotel Bell Elite</div></div></div>';

    return (
      '<!doctype html><html lang="en"><head><meta charset="utf-8">' +
      '<meta name="viewport" content="width=device-width,initial-scale=1">' +
      '<title>Invoice ' +
      escapeHtml(invoiceNo) +
      ' | Hotel Bell Elite</title>' +
      '<link rel="stylesheet" href="' +
      absoluteAssetUrl(CSS_HREF) +
      '">' +
      '<style>.muted{color:#5b6b7c;font-weight:500}</style>' +
      '</head><body>' +
      '<div class="hri-toolbar">' +
      '<button type="button" onclick="window.close()">Close</button>' +
      '<button type="button" class="hri-print" onclick="window.print()">Print Invoice</button>' +
      '</div>' +
      '<article class="hri-sheet">' +
      '<table class="hri-doc">' +
      '<thead>' +
      '<tr><td colspan="6" class="hri-doc-masthead">' +
      mastheadHtml +
      '</td></tr>' +
      '<tr class="hri-colhead">' +
      '<th class="center" style="width:58px">Sl. No.</th>' +
      '<th>Description</th>' +
      '<th style="width:110px">Date</th>' +
      '<th class="center" style="width:56px">Qty</th>' +
      '<th class="num" style="width:100px">Rate (₹)</th>' +
      '<th class="num" style="width:110px">Amount (₹)</th>' +
      '</tr>' +
      '</thead>' +
      '<tbody>' +
      rowsHtml +
      '</tbody>' +
      '<tfoot>' +
      '<tr><td colspan="6" class="hri-doc-foot">' +
      footerHtml +
      '</td></tr>' +
      '</tfoot>' +
      '</table>' +
      '</article></body></html>'
    );
  }

  function openHotelRoomInvoice(room, opts) {
    opts = opts || {};
    if (!room || !room.stay) return false;
    var html = buildHotelRoomInvoiceHtml(room, opts);
    var autoPrint = opts.autoPrint === true;
    try {
      var win = global.open('', '_blank', 'width=920,height=1100');
      if (win) {
        win.document.open();
        win.document.write(html);
        win.document.close();
        win.focus();
        if (autoPrint) {
          setTimeout(function () {
            try {
              win.print();
            } catch (err) {}
          }, 350);
        }
        return true;
      }
    } catch (err) {}

    try {
      var blob = new Blob([html], { type: 'text/html' });
      var url = URL.createObjectURL(blob);
      var blobWin = global.open(url, '_blank', 'width=920,height=1100');
      if (blobWin) {
        setTimeout(function () {
          try {
            blobWin.focus();
            if (autoPrint) blobWin.print();
          } catch (err) {}
          setTimeout(function () {
            URL.revokeObjectURL(url);
          }, 60000);
        }, 300);
        return true;
      }
      URL.revokeObjectURL(url);
    } catch (err) {}

    return false;
  }

  global.buildHotelRoomInvoiceHtml = buildHotelRoomInvoiceHtml;
  global.openHotelRoomInvoice = openHotelRoomInvoice;
  global.hotelInvoiceRoomLabel = hotelInvoiceRoomLabel;
  global.hotelRoomInvoiceAmountInWords = amountInWords;
})(window);
