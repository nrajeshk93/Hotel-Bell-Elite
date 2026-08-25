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
  var CSS_HREF = '/static/hotel_room_invoice.css?v=10';

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

  /* Production nginx caches /static/ for a long time. Invoice previews must not
     depend on a stale stylesheet — prefer an inline copy fetched with no-store. */
  var _invoiceCssText = '';
  var _invoiceCssTextPromise = null;

  function invoiceStylesheetHtml(cssText) {
    if (cssText) {
      return (
        '<style id="hri-invoice-css">' +
        String(cssText).replace(/<\/style/gi, '<\\/style') +
        '</style>'
      );
    }
    return (
      '<link rel="stylesheet" href="' + absoluteAssetUrl(CSS_HREF) + '">'
    );
  }

  function fetchInvoiceCssText() {
    if (_invoiceCssText) return Promise.resolve(_invoiceCssText);
    if (_invoiceCssTextPromise) return _invoiceCssTextPromise;
    _invoiceCssTextPromise = fetch(absoluteAssetUrl(CSS_HREF), {
      cache: 'no-store',
      credentials: 'same-origin'
    })
      .then(function (resp) {
        if (!resp.ok) throw new Error('invoice css fetch failed');
        return resp.text();
      })
      .then(function (text) {
        _invoiceCssText = String(text || '');
        return _invoiceCssText;
      })
      .catch(function () {
        _invoiceCssTextPromise = null;
        return '';
      });
    return _invoiceCssTextPromise;
  }

  function withInlineInvoiceCss(html) {
    return fetchInvoiceCssText().then(function (cssText) {
      if (!cssText) return html;
      var styleTag = invoiceStylesheetHtml(cssText);
      if (/<link\s+rel=["']stylesheet["'][^>]*>/i.test(html)) {
        return html.replace(/<link\s+rel=["']stylesheet["'][^>]*>/i, styleTag);
      }
      return html.replace(/<\/head>/i, styleTag + '</head>');
    });
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

  function cancelledInvoiceParts(room, opts) {
    opts = opts || {};
    var stay = (room && room.stay) || {};
    var status = String(
      opts.invoiceStatus ||
        opts.status ||
        stay.invoiceStatus ||
        stay.invoice_status ||
        ''
    )
      .trim()
      .toLowerCase();
    if (status !== 'cancelled') {
      return { isCancelled: false, mark: '', metaItems: '' };
    }
    var reason = String(
      opts.cancelReason ||
        opts.cancel_reason ||
        stay.cancelReason ||
        stay.cancel_reason ||
        ''
    ).trim();
    return {
      isCancelled: true,
      mark:
        '<div class="hri-cancelled-watermark" aria-hidden="true"><span>Cancelled</span></div>',
      metaItems:
        '<li><span class="k">Status</span><span class="v">Cancelled</span></li>' +
        (reason
          ? '<li><span class="k">Reason</span><span class="v">' +
            escapeHtml(reason) +
            '</span></li>'
          : '')
    };
  }

  function folioChargeDisplayLabel(item) {
    var kind = String((item && item.kind) || '').toLowerCase();
    var base =
      kind === 'bar_room_transfer'
        ? 'Bar Room Transfer'
        : kind === 'restaurant_room_transfer'
          ? 'Restaurant Room Transfer'
          : '';
    var stored = String((item && item.label) || '').trim();
    if (!base) {
      var dateIso = String(
        (item && (item.serviceDate || item.service_date)) || ''
      ).trim();
      var dateLabel = '';
      if (dateIso && dateIso.length >= 10) {
        try {
          var parts = dateIso.slice(0, 10).split('-');
          var d = new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]));
          dateLabel = d.toLocaleDateString('en-IN', {
            day: 'numeric',
            month: 'short',
            year: '2-digit'
          });
        } catch (err) {
          dateLabel = dateIso.slice(0, 10);
        }
      }
      var label = stored || 'Other Charge';
      return dateLabel ? label + ' · ' + dateLabel : label;
    }
    var invoiceNo = String(
      (item &&
        (item.orderNo ||
          item.order_no ||
          item.invoiceNumber ||
          item.invoiceNo)) ||
        ''
    ).trim();
    if (!invoiceNo && stored) {
      var match = stored.match(/\b(?:ORD|INV)[-A-Za-z0-9]+/i);
      if (match) invoiceNo = match[0];
      else if (stored.indexOf(base) === 0) {
        invoiceNo = stored
          .slice(base.length)
          .replace(/^\s*[·•|—–-]+\s*/, '')
          .trim();
      }
    }
    if (!invoiceNo) {
      var rawId = String(
        (item && (item.invoiceId || item.invoice_id)) || ''
      ).trim();
      if (rawId && rawId.length <= 24) invoiceNo = rawId;
    }
    return invoiceNo ? base + ' · ' + invoiceNo : stored || base;
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

  function billToBlock(stay, kind) {
    var flags = stayAgencyBillFlags(stay);
    var useAgency = kind === 'fb' ? flags.fb : flags.room;
    var agencyBilling = !!(stay && useAgency && stay.agencyName);
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

  function roundInvoiceMoney(n) {
    return Math.round(Number(n || 0) * 100) / 100;
  }

  /** Merge consecutive tariff nights that share description + unit rate. */
  function groupConsecutiveTariffNights(nightRows, roomsCount) {
    var rooms = Math.max(1, Math.floor(Number(roomsCount) || 1));
    var out = [];
    var cur = null;
    (nightRows || []).forEach(function (row) {
      if (!row) return;
      var rate = roundInvoiceMoney(row.rate);
      var desc = String(row.description || '');
      var day = row.date || '';
      if (cur && cur.description === desc && cur.rate === rate) {
        cur.qty += 1;
        cur.nights = cur.qty;
        cur.dateEnd = day;
        cur.amount = roundInvoiceMoney(cur.rate * cur.qty * rooms);
        return;
      }
      if (cur) out.push(cur);
      cur = {
        description: desc,
        date: day,
        dateEnd: day,
        qty: 1,
        nights: 1,
        rooms: rooms,
        rate: rate,
        amount: roundInvoiceMoney(rate * rooms),
        lineKind: 'tariff'
      };
    });
    if (cur) out.push(cur);
    return out;
  }

  function lineDateLabel(row) {
    var startIso = toDateISO(row && row.date);
    var endIso = toDateISO(row && row.dateEnd);
    var start = prettyDate(row && row.date);
    if (endIso && startIso && endIso !== startIso) {
      return start + ' – ' + prettyDate(row.dateEnd);
    }
    return start;
  }

  function normalizeRatePlan(value) {
    return String(value || '')
      .trim()
      .toLowerCase();
  }

  function ratesMatch(a, b) {
    return Math.abs(Number(a || 0) - Number(b || 0)) <= 0.02;
  }

  function plansMatch(a, b) {
    var left = normalizeRatePlan(a);
    var right = normalizeRatePlan(b);
    /* Empty plan on either side is treated as compatible (folio lines rarely store plan). */
    if (!left || !right) return true;
    return left === right;
  }

  function isMergeStayFolio(item) {
    if (!item) return false;
    var src = String(item.source || '').toLowerCase();
    return src === 'merged_room_rate' || src === 'room_merge';
  }

  function primaryTariffKey(stay) {
    stay = stay || {};
    var rate = Math.max(0, Number(stay.roomRate || 0));
    var plan = normalizeRatePlan(stay.ratePlan);
    var mergeRates = Array.isArray(stay.mergeRoomRates) ? stay.mergeRoomRates : [];
    for (var i = 0; i < mergeRates.length; i++) {
      var row = mergeRates[i];
      if (!row || !(row.isPrimary || row.is_primary)) continue;
      rate = Math.max(0, Number(row.roomRate != null ? row.roomRate : rate));
      plan = normalizeRatePlan(row.ratePlan || plan);
      break;
    }
    return { rate: roundInvoiceMoney(rate), plan: plan };
  }

  function mergeFolioEffectiveRate(item, billableNights) {
    var amount = Number((item && item.amount) || 0);
    var nights = Math.max(1, Math.floor(Number(billableNights) || 1));
    if (!(amount > 0)) return 0;
    return roundInvoiceMoney(amount / nights);
  }

  function mergeMemberMatchesPrimary(stay, item, billableNights, primary) {
    stay = stay || {};
    primary = primary || primaryTariffKey(stay);
    var mergeRates = Array.isArray(stay.mergeRoomRates) ? stay.mergeRoomRates : [];
    var rid = String((item && (item.sourceRoomId || item.source_room_id)) || '').trim();
    var num = String(
      (item && (item.sourceRoomNumber || item.source_room_number)) || ''
    ).trim();
    for (var i = 0; i < mergeRates.length; i++) {
      var row = mergeRates[i];
      if (!row || row.isPrimary || row.is_primary) continue;
      var rowId = String(row.roomId || row.room_id || '').trim();
      var rowNum = String(row.number || row.roomNumber || '').trim();
      var idMatch = rid && rowId && rid === rowId;
      var numMatch = num && rowNum && num === rowNum;
      if (!idMatch && !numMatch) continue;
      var rowRate = Math.max(0, Number(row.roomRate != null ? row.roomRate : 0));
      var rowPlan = normalizeRatePlan(row.ratePlan);
      if (rowRate > 0 && ratesMatch(rowRate, primary.rate) && plansMatch(rowPlan, primary.plan)) {
        return true;
      }
      /* Rate row found but does not match — still allow folio amount fallback. */
      break;
    }
    var eff = mergeFolioEffectiveRate(item, billableNights);
    if (ratesMatch(eff, primary.rate)) return true;
    /* Absorb lines sometimes store a flat stay total equal to rate × nights. */
    var amount = Number((item && item.amount) || 0);
    var expected = roundInvoiceMoney(primary.rate * Math.max(1, billableNights));
    if (ratesMatch(amount, expected) || ratesMatch(amount, primary.rate)) return true;
    return false;
  }

  /**
   * Rooms that share the primary tariff + meal plan fold into one print line.
   * Returns 1 (primary) + matching merge members.
   */
  function matchingMergeRoomCount(room) {
    var stay = (room && room.stay) || {};
    var primary = primaryTariffKey(stay);
    if (!(primary.rate > 0)) return 1;
    var billableNights = billableNightsFromStay(stay, room);
    var counted = {};
    var extra = 0;

    function mark(key) {
      key = String(key || '').trim();
      if (!key || counted[key]) return;
      counted[key] = true;
      extra += 1;
    }

    var mergeRates = Array.isArray(stay.mergeRoomRates) ? stay.mergeRoomRates : [];
    mergeRates.forEach(function (row) {
      if (!row || row.isPrimary || row.is_primary) return;
      var rowRate = Math.max(0, Number(row.roomRate != null ? row.roomRate : 0));
      var rowPlan = normalizeRatePlan(row.ratePlan);
      if (!(rowRate > 0) || !ratesMatch(rowRate, primary.rate) || !plansMatch(rowPlan, primary.plan)) {
        return;
      }
      mark(row.roomId || row.room_id || row.number || row.roomNumber);
    });

    /* Always also scan folio so absorb lines fold even when mergeRoomRates is incomplete. */
    var folio = Array.isArray(stay.folioCharges) ? stay.folioCharges : [];
    folio.forEach(function (item) {
      if (!isMergeStayFolio(item)) return;
      if (!mergeMemberMatchesPrimary(stay, item, billableNights, primary)) return;
      mark(
        item.sourceRoomId ||
          item.source_room_id ||
          item.sourceRoomNumber ||
          item.source_room_number ||
          item.id
      );
    });

    return 1 + extra;
  }

  function shouldFoldMergeFolioLine(stay, item, billableNights, primary) {
    if (!isMergeStayFolio(item)) return false;
    return mergeMemberMatchesPrimary(stay, item, billableNights, primary);
  }

  function buildInvoiceLines(room) {
    var stay = (room && room.stay) || {};
    var lines = [];
    var checkIn = toDateISO(stay.checkInDate || stay.check_in_date);
    var nights = Math.max(1, Number(stay.nights || 1));
    var overstayNights = overstayNightsFromStay(stay, room);
    var billableNights = billableNightsFromStay(stay, room);
    var roomRate = Math.max(0, Number(stay.roomRate || 0));
    var primaryKey = primaryTariffKey(stay);
    if (primaryKey.rate > 0) roomRate = primaryKey.rate;
    var roomsCount = matchingMergeRoomCount(room);
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
      (stay.chargeLabels && stay.chargeLabels.room) ||
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
      return String(stay.ratePlan || primaryKey.plan || '').trim();
    }

    if ((roomRate > 0 || nightlyRates.length) && checkIn) {
      var nightRows = [];
      for (var i = 0; i < billableNights; i++) {
        var nightDate = addDaysISO(checkIn, i);
        var isOverstay = i >= nights;
        var nightRate = nightRateFor(i, nightDate);
        if (!(nightRate > 0)) continue;
        var plan = nightPlanFor(i, nightDate);
        var desc = isOverstay ? roomLabel + ' (Overstay)' : roomLabel;
        if (plan) desc += ' · ' + plan;
        nightRows.push({
          description: desc,
          date: nightDate,
          rate: nightRate
        });
      }
      lines = lines.concat(groupConsecutiveTariffNights(nightRows, roomsCount));
    } else if (roomRate > 0) {
      lines.push({
        description: roomLabel,
        date: checkIn,
        qty: billableNights,
        nights: billableNights,
        rooms: roomsCount,
        rate: roomRate,
        amount: roundInvoiceMoney(roomRate * billableNights * roomsCount),
        lineKind: 'tariff'
      });
    }

    var extras = [
      {
        key: 'extra_bed',
        label: 'Extra Bed',
        amount: Number(stay.extraBedAmount || 0),
        nights: Math.max(1, Math.floor(Number(stay.extraBedNights || billableNights || 1))),
        rooms: Math.max(1, Math.floor(Number(stay.extraBedQty || 1)))
      },
      {
        key: 'early_checkin',
        label: 'Early Check-in',
        amount: Number(stay.earlyCheckinAmount || 0),
        nights: Math.max(1, Math.floor(Number(stay.earlyCheckinNights || 1))),
        rooms: Math.max(1, Math.floor(Number(stay.earlyCheckinQty || 1)))
      },
      {
        key: 'late_checkout',
        label: 'Late Check-out',
        amount: Number(stay.lateCheckoutAmount || 0),
        nights: Math.max(1, Math.floor(Number(stay.lateCheckoutNights || 1))),
        rooms: Math.max(1, Math.floor(Number(stay.lateCheckoutQty || 1)))
      }
    ];
    var chargeLabels =
      stay.chargeLabels && typeof stay.chargeLabels === 'object'
        ? stay.chargeLabels
        : {};
    extras.forEach(function (row) {
      if (!(row.amount > 0)) return;
      var unit = roundInvoiceMoney(
        row.amount / Math.max(1, Number(row.nights || 1) * Number(row.rooms || 1))
      );
      lines.push({
        description: chargeLabels[row.key] || row.label,
        date: checkIn,
        qty: 1,
        nights: row.nights,
        rooms: row.rooms,
        rate: unit,
        amount: row.amount,
        lineKind: 'other'
      });
    });

    var folio = Array.isArray(stay.folioCharges) ? stay.folioCharges : [];
    folio.forEach(function (item) {
      if (!item) return;
      var kind = String(item.kind || '').toLowerCase();
      if (kind === 'restaurant_room_transfer' || kind === 'bar_room_transfer') return;
      var amount = Number(item.amount || 0);
      if (!(amount > 0)) return;
      if (shouldFoldMergeFolioLine(stay, item, billableNights, primaryKey)) {
        return;
      }
      var at = toDateISO(item.at) || checkIn;
      var src = String(item.source || '').toLowerCase();
      var isMergeRate = src === 'merged_room_rate';
      var isMergeAbsorb = src === 'room_merge';
      var lineNights = isMergeRate || isMergeAbsorb ? billableNights : 1;
      var lineRooms = 1;
      var lineRate =
        isMergeRate || isMergeAbsorb
          ? roundInvoiceMoney(amount / Math.max(1, billableNights))
          : roundInvoiceMoney(amount / Math.max(1, lineNights * lineRooms));
      lines.push({
        description: folioChargeDisplayLabel(item),
        date: at,
        qty: 1,
        nights: lineNights,
        rooms: lineRooms,
        rate: lineRate,
        amount: amount,
        lineKind: 'other'
      });
    });

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

  function invoiceHistoryEntry(stay, invoiceNumber, kind) {
    if (!stay || !invoiceNumber) return null;
    var target = String(invoiceNumber).trim();
    var raw = (stay.invoiceHistory || stay.invoice_history) || [];
    if (Array.isArray(raw)) {
      for (var i = 0; i < raw.length; i++) {
        var item = raw[i];
        if (!item) continue;
        var inv = String(item.invoiceNumber || item.invoice_number || '').trim();
        var entryKind = String(item.kind || 'hotel').toLowerCase();
        if (inv === target && (!kind || entryKind === kind)) {
          return item;
        }
      }
    }
    if (kind === 'hotel' || !kind) {
      if (target === String(stay.invoiceNumber || '').trim()) {
        return {
          kind: 'hotel',
          invoiceNumber: target,
          generatedAt: stay.invoiceGeneratedAt || '',
          snapshotStay: null
        };
      }
    }
    if (kind === 'fb') {
      if (
        target ===
        String(stay.fbTransferInvoiceNumber || stay.fb_transfer_invoice_number || '').trim()
      ) {
        return {
          kind: 'fb',
          invoiceNumber: target,
          generatedAt: stay.fbTransferInvoiceGeneratedAt || '',
          snapshotStay: null
        };
      }
      if (target === String(stay.invoiceNumber || '').trim()) {
        return {
          kind: 'fb',
          invoiceNumber: target,
          generatedAt:
            stay.fbTransferInvoiceGeneratedAt || stay.invoiceGeneratedAt || '',
          snapshotStay: null
        };
      }
    }
    return null;
  }

  function roomWithInvoiceSnapshot(room, invoiceNumber, kind) {
    if (!room || !invoiceNumber) return room;
    var stay = room.stay || {};
    var entry = invoiceHistoryEntry(stay, invoiceNumber, kind);
    if (entry && entry.snapshotStay && typeof entry.snapshotStay === 'object') {
      return Object.assign({}, room, { stay: entry.snapshotStay });
    }
    if (kind === 'fb') {
      var folio = Array.isArray(stay.folioCharges) ? stay.folioCharges : [];
      var lines = folio.filter(function (line) {
        if (!line) return false;
        var inv = String(
          line.invoicedInvoiceNumber || line.invoiced_invoice_number || ''
        ).trim();
        return inv === String(invoiceNumber).trim();
      });
      if (lines.length) {
        var snapStay = Object.assign({}, stay, {
          folioCharges: lines.map(function (line) {
            return Object.assign({}, line);
          }),
          fbTransferTotal: lines.reduce(function (sum, line) {
            return sum + Number(line.amount || 0);
          }, 0)
        });
        return Object.assign({}, room, { stay: snapStay });
      }
    }
    return room;
  }

  function invoiceClosingHtml() {
    return (
      '<div class="hri-closing">' +
      '<div class="hri-thanks">Thank You &amp; Safe Travels!</div>' +
      '<div class="hri-values">' +
      '<div class="hri-value"><div class="hri-value-ico"><svg viewBox="0 0 24 24"><path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/></svg></div>Comfortable Stay</div>' +
      '<div class="hri-value"><div class="hri-value-ico"><svg viewBox="0 0 24 24"><polygon points="12 2 15 9 22 9 17 14 19 21 12 17 5 21 7 14 2 9 9 9"/></svg></div>Quality Service</div>' +
      '<div class="hri-value"><div class="hri-value-ico"><svg viewBox="0 0 24 24"><path d="M5 16c0-4 3-7 7-7s7 3 7 7"/><path d="M8 9V6a4 4 0 0 1 8 0v3"/><path d="M4 16h16v4H4z"/></svg></div>Memorable Experience</div>' +
      '<div class="hri-value"><div class="hri-value-ico"><svg viewBox="0 0 24 24"><path d="M20 13c0 5-3.5 7.5-8 10-4.5-2.5-8-5-8-10V6l8-3 8 3z"/></svg></div>We Value You</div>' +
      '</div>' +
      '<div class="hri-sign"><div class="hri-sign-box"><div class="hri-sign-line"></div><div class="hri-sign-title">Authorised Signatory</div><div class="hri-sign-sub">Hotel Bell Elite</div></div></div>' +
      '</div>'
    );
  }

  function buildHotelRoomInvoiceHtml(room, opts) {
    opts = opts || {};
    var invNo = String(opts.invoiceNumber || '').trim();
    if (invNo) {
      room = roomWithInvoiceSnapshot(room, invNo, 'hotel');
      var entry = invoiceHistoryEntry((room && room.stay) || {}, invNo, 'hotel');
      if (entry && entry.generatedAt && !opts.invoiceDate) {
        opts.invoiceDate = entry.generatedAt;
      }
    }
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
      toDateISO(opts.invoiceDate) ||
      toDateISO(stay.invoiceGeneratedAt) ||
      toDateISO(new Date().toISOString().slice(0, 10));
    var invoiceNo = String(
      opts.invoiceNumber || stay.invoiceNumber || '—'
    ).trim() || '—';
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
    var cancelled = cancelledInvoiceParts(room, opts);

    var minRows = 4;
    function lineNightsDisplay(row) {
      if (row && row.nights != null && isFinite(Number(row.nights))) {
        return String(Math.max(0, Math.floor(Number(row.nights))));
      }
      if (row && row.lineKind === 'tariff' && row.qty != null) {
        return String(Math.max(0, Math.floor(Number(row.qty) || 0)));
      }
      return '—';
    }
    function lineRoomsDisplay(row) {
      if (row && row.rooms != null && isFinite(Number(row.rooms))) {
        return String(Math.max(0, Math.floor(Number(row.rooms))));
      }
      if (row && row.lineKind === 'tariff') return '1';
      return '—';
    }
    var rowsHtml = lines
      .map(function (row, idx) {
        return (
          '<tr class="hri-line">' +
          '<td class="center">' +
          (idx + 1) +
          '</td>' +
          '<td>' +
          escapeHtml(row.description) +
          '</td>' +
          '<td class="center">' +
          escapeHtml(lineNightsDisplay(row)) +
          '</td>' +
          '<td class="center">' +
          escapeHtml(lineRoomsDisplay(row)) +
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
      cancelled.metaItems +
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

    var totalsHtml =
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
      '</section></div>';

    return (
      '<!doctype html><html lang="en"><head><meta charset="utf-8">' +
      '<meta name="viewport" content="width=device-width,initial-scale=1">' +
      '<title>Invoice ' +
      escapeHtml(invoiceNo) +
      ' | Hotel Bell Elite</title>' +
      invoiceStylesheetHtml('') +
      '<style>.muted{color:#5b6b7c;font-weight:500}</style>' +
      '</head><body' +
      (cancelled.isCancelled ? ' class="is-cancelled"' : '') +
      '>' +
      '<div class="hri-toolbar">' +
      '<button type="button" onclick="window.close()">Close</button>' +
      '<button type="button" class="hri-print" onclick="window.print()">Print Invoice</button>' +
      '</div>' +
      '<article class="hri-sheet">' +
      cancelled.mark +
      '<div class="hri-sheet-body">' +
      '<table class="hri-doc">' +
      '<thead>' +
      '<tr><td colspan="6" class="hri-doc-masthead">' +
      mastheadHtml +
      '</td></tr>' +
      '<tr class="hri-colhead">' +
      '<th class="center" style="width:58px">Sl. No.</th>' +
      '<th>Description</th>' +
      '<th class="center" style="width:72px">Nights</th>' +
      '<th class="center" style="width:72px">Rooms</th>' +
      '<th class="num" style="width:100px">Rate (₹)</th>' +
      '<th class="num" style="width:110px">Amount (₹)</th>' +
      '</tr>' +
      '</thead>' +
      '<tbody>' +
      rowsHtml +
      '</tbody>' +
      '<tfoot>' +
      '<tr><td colspan="6" class="hri-doc-foot">' +
      totalsHtml +
      '</td></tr>' +
      '</tfoot>' +
      '</table>' +
      '</div>' +
      invoiceClosingHtml() +
      '</article></body></html>'
    );
  }

  function closeHtmlPreviewOverlay() {
    var existing = document.getElementById('hri-preview-overlay');
    if (existing) existing.remove();
  }

  function openHtmlPreviewOverlay(html, title, autoPrint) {
    closeHtmlPreviewOverlay();
    var overlay = document.createElement('div');
    overlay.id = 'hri-preview-overlay';
    overlay.className = 'hri-preview-overlay';
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    overlay.innerHTML =
      '<div class="hri-preview-shell">' +
      '<header class="hri-preview-toolbar">' +
      '<strong class="hri-preview-title">' +
      escapeHtml(title || 'Invoice') +
      '</strong>' +
      '<div class="hri-preview-actions">' +
      '<button type="button" class="hri-preview-print">Print</button>' +
      '<button type="button" class="hri-preview-close">Close</button>' +
      '</div></header>' +
      '<iframe class="hri-preview-frame" title="Invoice preview"></iframe>' +
      '</div>';
    document.body.appendChild(overlay);
    var frame = overlay.querySelector('.hri-preview-frame');
    if (frame) frame.srcdoc = html;
    var closeBtn = overlay.querySelector('.hri-preview-close');
    if (closeBtn) {
      closeBtn.addEventListener('click', closeHtmlPreviewOverlay);
    }
    var printBtn = overlay.querySelector('.hri-preview-print');
    if (printBtn) {
      printBtn.addEventListener('click', function () {
        try {
          if (frame && frame.contentWindow) frame.contentWindow.print();
        } catch (err) {}
      });
    }
    overlay.addEventListener('click', function (event) {
      if (event.target === overlay) closeHtmlPreviewOverlay();
    });
    document.addEventListener(
      'keydown',
      function onEsc(event) {
        if (event.key !== 'Escape') return;
        closeHtmlPreviewOverlay();
        document.removeEventListener('keydown', onEsc);
      },
      { once: true }
    );
    if (autoPrint) {
      setTimeout(function () {
        try {
          if (frame && frame.contentWindow) frame.contentWindow.print();
        } catch (err) {}
      }, 400);
    }
    return true;
  }

  function openHtmlInPreviewWindow(html, opts) {
    opts = opts || {};
    var autoPrint = opts.autoPrint === true;
    var title = String(opts.title || 'Invoice').trim() || 'Invoice';

    function present(finalHtml) {
      try {
        var blob = new Blob([finalHtml], { type: 'text/html;charset=utf-8' });
        var url = URL.createObjectURL(blob);
        var blobWin = global.open(url, '_blank', 'noopener,noreferrer,width=920,height=1100');
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

      try {
        var win = global.open('', '_blank', 'width=920,height=1100');
        if (win) {
          win.document.open();
          win.document.write(finalHtml);
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

      return openHtmlPreviewOverlay(finalHtml, title, autoPrint);
    }

    /* Show immediately with linked CSS, then refresh with inlined no-store CSS
       so production Cloudflare/nginx year-long static caches cannot pin an old look. */
    var shown = present(html);
    withInlineInvoiceCss(html).then(function (finalHtml) {
      if (!finalHtml || finalHtml === html) return;
      var frame = document.querySelector('#hri-preview-overlay .hri-preview-frame');
      if (frame) {
        frame.srcdoc = finalHtml;
        return;
      }
    });
    return shown;
  }

  function openHotelRoomInvoice(room, opts) {
    opts = opts || {};
    if (!room || !room.stay) return false;
    var html = buildHotelRoomInvoiceHtml(room, opts);
    var invNo =
      String(opts.invoiceNumber || (room.stay && room.stay.invoiceNumber) || '').trim() ||
      'Invoice';
    return openHtmlInPreviewWindow(html, {
      autoPrint: opts.autoPrint === true,
      title: invNo
    });
  }

  function fbTransferLinesFromStay(stay) {
    var folio = Array.isArray(stay && stay.folioCharges) ? stay.folioCharges : [];
    var checkIn = toDateISO(stay && (stay.checkInDate || stay.check_in_date));
    var lines = [];
    folio.forEach(function (item) {
      if (!item) return;
      var kind = String(item.kind || '').toLowerCase();
      if (kind !== 'restaurant_room_transfer' && kind !== 'bar_room_transfer') return;
      var amount = Number(item.amount || 0);
      if (!(amount > 0)) return;
      amount = Math.round(amount * 100) / 100;
      var gst = Math.round(Number(item.gst || item.gstAmount || 0) * 100) / 100;
      var vat = Math.round(Number(item.vat || item.vatAmount || 0) * 100) / 100;
      var sub = Math.round(Number(item.subtotal || 0) * 100) / 100;
      var exclusive = amount;
      if (gst > 0.009 || vat > 0.009 || sub > 0.009) {
        exclusive =
          sub > 0.009
            ? sub
            : Math.max(0, Math.round((amount - gst - vat) * 100) / 100);
      }
      lines.push({
        description: folioChargeDisplayLabel(item),
        date: toDateISO(item.at || item.createdAt || item.created_at) || checkIn,
        qty: 1,
        rate: exclusive,
        amount: exclusive,
        gst: gst,
        vat: vat,
        inclusive: amount,
        taxCgstPct: item.taxCgstPct != null ? Number(item.taxCgstPct) : null,
        taxUgstPct: item.taxUgstPct != null ? Number(item.taxUgstPct) : null,
        vatPct: item.vatPct != null ? Number(item.vatPct) : null
      });
    });
    return lines;
  }

  function buildFbCombinedTransferInvoiceHtml(room, opts) {
    opts = opts || {};
    var invNo = String(opts.invoiceNumber || '').trim();
    if (invNo) {
      room = roomWithInvoiceSnapshot(room, invNo, 'fb');
      var entry = invoiceHistoryEntry((room && room.stay) || {}, invNo, 'fb');
      if (entry && entry.generatedAt && !opts.invoiceDate) {
        opts.invoiceDate = entry.generatedAt;
      }
    }
    var stay = (room && room.stay) || {};
    var lines = fbTransferLinesFromStay(stay);
    var subtotal = Math.round(
      lines.reduce(function (sum, row) {
        return sum + Number(row.amount || 0);
      }, 0) * 100
    ) / 100;
    var gstTotal = Math.round(
      lines.reduce(function (sum, row) {
        return sum + Number(row.gst || 0);
      }, 0) * 100
    ) / 100;
    var vatTotal = Math.round(
      lines.reduce(function (sum, row) {
        return sum + Number(row.vat || 0);
      }, 0) * 100
    ) / 100;
    var inclusive = Math.round(
      lines.reduce(function (sum, row) {
        return sum + Number(row.inclusive != null ? row.inclusive : row.amount || 0);
      }, 0) * 100
    ) / 100;
    if (!(inclusive > 0) && stay.fbTransferTotal != null) {
      inclusive = Math.round(Number(stay.fbTransferTotal || 0) * 100) / 100;
    }
    if (!(subtotal > 0) && inclusive > 0 && !(gstTotal > 0) && !(vatTotal > 0)) {
      subtotal = inclusive;
    }
    var cgst = 0;
    var ugst = 0;
    if (gstTotal > 0.009) {
      var cPct = null;
      var uPct = null;
      lines.forEach(function (row) {
        if (cPct == null && row.taxCgstPct != null) cPct = Number(row.taxCgstPct);
        if (uPct == null && row.taxUgstPct != null) uPct = Number(row.taxUgstPct);
      });
      var cFrac = cPct != null && uPct != null && cPct + uPct > 0 ? cPct / (cPct + uPct) : 0.5;
      cgst = Math.round(gstTotal * cFrac * 100) / 100;
      ugst = Math.round((gstTotal - cgst) * 100) / 100;
      if (ugst < 0) ugst = 0;
    }
    var total = inclusive > 0 ? inclusive : Math.round((subtotal + gstTotal + vatTotal) * 100) / 100;

    var invoiceNo =
      String(
        opts.invoiceNumber ||
          stay.fbTransferInvoiceNumber ||
          stay.fb_transfer_invoice_number ||
          '—'
      ).trim() || '—';
    var invoiceDate =
      toDateISO(opts.invoiceDate) ||
      toDateISO(stay.fbTransferInvoiceGeneratedAt) ||
      toDateISO(stay.invoiceGeneratedAt) ||
      toDateISO(opts.invoiceDate) ||
      toDateISO(new Date().toISOString().slice(0, 10));
    var hotelInv = String(stay.invoiceNumber || '').trim();
    var bookingNo = String(stay.bookingNumber || '—').trim() || '—';
    var checkIn = toDateISO(stay.checkInDate || stay.check_in_date);
    var checkOut = toDateISO(stay.checkOutDate || stay.check_out_date);
    var adults = Math.max(1, Number(stay.adults || 1));
    var children = Math.max(0, Number(stay.children || 0));
    var guestsLabel =
      adults +
      ' Adult' +
      (adults === 1 ? '' : 's') +
      (children
        ? ' · ' + children + ' Child' + (children === 1 ? '' : 'ren')
        : '');
    var billTo = billToBlock(stay, 'fb');
    var roomNumber = hotelInvoiceRoomLabel(room);
    var cancelled = cancelledInvoiceParts(room, opts);

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
      '<div><h2 class="hri-title">TAX INVOICE</h2>' +
      '<ul class="hri-meta-list">' +
      '<li><span class="k">Invoice No.</span><span class="v">' +
      escapeHtml(invoiceNo) +
      '</span></li>' +
      cancelled.metaItems +
      (hotelInv
        ? '<li><span class="k">Hotel Invoice</span><span class="v">' +
          escapeHtml(hotelInv) +
          '</span></li>'
        : '') +
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
      '<li><span class="k">Bill Type</span><span class="v">F&amp;B Room Transfers</span></li>' +
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

    var vatPctLabel = '';
    lines.forEach(function (row) {
      if (!vatPctLabel && row.vatPct != null && isFinite(Number(row.vatPct))) {
        vatPctLabel = String(Math.round(Number(row.vatPct) * 100) / 100);
      }
    });
    var taxRowsHtml = '';
    if (cgst > 0.009 || ugst > 0.009) {
      taxRowsHtml +=
        '<div class="hri-totals-row"><span class="k">CGST</span><span class="v">' +
        money(cgst) +
        '</span></div>' +
        '<div class="hri-totals-row"><span class="k">UGST</span><span class="v">' +
        money(ugst) +
        '</span></div>';
    }
    if (vatTotal > 0.009) {
      taxRowsHtml +=
        '<div class="hri-totals-row"><span class="k">VAT' +
        (vatPctLabel ? ' (' + vatPctLabel + '%)' : '') +
        '</span><span class="v">' +
        money(vatTotal) +
        '</span></div>';
    }
    var notesBody =
      vatTotal > 0.009 && !(cgst > 0.009 || ugst > 0.009)
        ? 'Restaurant and bar bills transferred to this room stay. Tax follows each POS invoice (VAT shown when applicable).'
        : 'Restaurant and bar bills transferred to this room stay. Tax follows each POS invoice.';

    var totalsHtml =
      '<div class="hri-bottom">' +
      '<section class="hri-notes"><div class="hri-notes-head">' +
      iconDoc() +
      ' Notes</div><div class="hri-notes-body">' +
      notesBody +
      '</div></section>' +
      '<section class="hri-totals">' +
      '<div class="hri-totals-row"><span class="k">Subtotal</span><span class="v">' +
      money(subtotal) +
      '</span></div>' +
      taxRowsHtml +
      '<div class="hri-totals-row is-total"><span class="k">Total Amount (₹)</span><span class="v">' +
      money(total) +
      '</span></div>' +
      '<div class="hri-words">Amount in Words: <strong>' +
      escapeHtml(amountInWords(total)) +
      '</strong></div>' +
      '</section></div>';

    return (
      '<!doctype html><html lang="en"><head><meta charset="utf-8">' +
      '<meta name="viewport" content="width=device-width,initial-scale=1">' +
      '<title>Tax Invoice ' +
      escapeHtml(invoiceNo) +
      ' | Hotel Bell Elite</title>' +
      invoiceStylesheetHtml('') +
      '<style>.muted{color:#5b6b7c;font-weight:500}</style>' +
      '</head><body' +
      (cancelled.isCancelled ? ' class="is-cancelled"' : '') +
      '>' +
      '<div class="hri-toolbar">' +
      '<button type="button" onclick="window.close()">Close</button>' +
      '<button type="button" class="hri-print" onclick="window.print()">Print Invoice</button>' +
      '</div>' +
      '<article class="hri-sheet">' +
      cancelled.mark +
      '<div class="hri-sheet-body">' +
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
      totalsHtml +
      '</td></tr>' +
      '</tfoot>' +
      '</table>' +
      '</div>' +
      invoiceClosingHtml() +
      '</article></body></html>'
    );
  }

  function openFbCombinedTransferInvoice(room, opts) {
    opts = opts || {};
    if (!room || !room.stay) return false;
    var html = buildFbCombinedTransferInvoiceHtml(room, opts);
    var invNo =
      String(
        opts.invoiceNumber ||
          room.stay.fbTransferInvoiceNumber ||
          room.stay.invoiceNumber ||
          ''
      ).trim() || 'F&B Invoice';
    return openHtmlInPreviewWindow(html, {
      autoPrint: opts.autoPrint === true,
      title: invNo
    });
  }

  /* Warm CSS cache so the first invoice open can inline current styles quickly. */
  if (typeof global.fetch === 'function') {
    try {
      fetchInvoiceCssText();
    } catch (err) {}
  }

  global.buildHotelRoomInvoiceHtml = buildHotelRoomInvoiceHtml;
  global.buildFbCombinedTransferInvoiceHtml = buildFbCombinedTransferInvoiceHtml;
  global.buildHotelRoomInvoiceLines = buildInvoiceLines;
  global.groupConsecutiveHotelInvoiceTariffNights = groupConsecutiveTariffNights;
  global.openHotelRoomInvoice = openHotelRoomInvoice;
  global.openFbCombinedTransferInvoice = openFbCombinedTransferInvoice;
  global.openHtmlInPreviewWindow = openHtmlInPreviewWindow;
  global.closeHtmlPreviewOverlay = closeHtmlPreviewOverlay;
  global.hotelInvoiceRoomLabel = hotelInvoiceRoomLabel;
  global.hotelFolioChargeDisplayLabel = folioChargeDisplayLabel;
  global.hotelRoomInvoiceAmountInWords = amountInWords;
})(window);
