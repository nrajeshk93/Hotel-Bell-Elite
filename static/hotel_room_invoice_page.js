/**
 * Hotel room invoice finalize — POS Create Invoice chrome.
 * Soft-nav safe: window.initHotelRoomInvoicePage
 */
(function (global) {
  'use strict';

  var CGST_RATE = 0.025;
  var UGST_RATE = 0.025;
  var DISCOUNT_REASON_PCT = 15;
  var METHODS_REQUIRING_TXN = { bank_transfer: true };

  var PAY_METHODS = [
    { value: 'cash', label: 'Cash' },
    { value: 'upi', label: 'UPI' },
    { value: 'card', label: 'Card' },
    { value: 'bank_transfer', label: 'Bank Transfer' },
    { value: 'credit', label: 'Credit' }
  ];

  try {
    var methodsEl = document.getElementById('hri-payment-methods-data');
    if (methodsEl) {
      var parsed = JSON.parse(methodsEl.textContent || '[]');
      if (parsed && parsed.length) {
        PAY_METHODS = parsed.map(function (row) {
          return { value: row[0], label: row[1] };
        });
      }
    }
  } catch (err) {}

  var lastRoom = null;
  var lastRoot = null;
  var lastSummary = null;
  var discountDraftType = 'pct';

  function $(sel, root) {
    return (root || document).querySelector(sel);
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

  function money(value) {
    var n = Number(value || 0);
    if (!isFinite(n)) n = 0;
    return (
      '₹' +
      n.toLocaleString('en-IN', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
      })
    );
  }

  function round2(n) {
    return Math.round((Number(n) || 0) * 100) / 100;
  }

  function escapeHtml(str) {
    return String(str == null ? '' : str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function showToast(message, isError) {
    var toast = document.getElementById('hri-toast');
    if (!toast) return;
    toast.textContent = message || '';
    toast.hidden = !message;
    toast.classList.toggle('is-visible', !!message);
    toast.classList.toggle('is-error', !!isError);
    clearTimeout(showToast._timer);
    if (!message) return;
    showToast._timer = setTimeout(function () {
      toast.hidden = true;
      toast.classList.remove('is-visible', 'is-error');
      toast.textContent = '';
    }, 2800);
  }

  function navigateTo(url) {
    if (!url) return;
    if (typeof global.deNavigateWithTransition === 'function') {
      global.deNavigateWithTransition(url);
    } else {
      global.location.href = url;
    }
  }

  function isLedgerEdit(root) {
    if (!root) return false;
    if (root.getAttribute('data-ledger-edit') === '1') return true;
    if (root.getAttribute('data-invoice-edit-open') === '1') return true;
    return root.classList.contains('is-ledger-edit');
  }

  function generateInvoiceLabel(root) {
    return isLedgerEdit(root) ? 'Modify and Generate Invoice' : 'Generate Invoice';
  }

  function generateInvoiceTitle(root) {
    return isLedgerEdit(root)
      ? 'Modify and regenerate hotel room invoice'
      : 'Generate hotel room invoice';
  }

  function actionApiUrl(root) {
    if (isLedgerEdit(root)) {
      return root.getAttribute('data-invoice-edit-api') || '';
    }
    return root.getAttribute('data-room-api') || '';
  }

  function invoiceLoadUrl(root) {
    return root.getAttribute('data-invoice-api') || '';
  }

  function guestName(stay) {
    if (!stay) return 'Guest';
    return (
      stay.guestName ||
      stay.guest_name ||
      [stay.title, stay.firstName || stay.first_name, stay.lastName || stay.last_name]
        .filter(Boolean)
        .join(' ')
        .trim() ||
      'Guest'
    );
  }

  function guestMobile(stay) {
    if (!stay) return '';
    return String(stay.mobile || stay.phone || stay.guestMobile || '').trim();
  }

  function invoiceNumber(stay) {
    return (stay && (stay.invoiceNumber || stay.invoice_number)) || '';
  }

  function stayEditUnlocked(stay) {
    if (!stay || typeof stay !== 'object') return false;
    return !!(stay.invoiceEditOpen || stay.invoice_edit_open);
  }

  function chargesEditable(stay, root) {
    root = root || lastRoot;
    if (root && isLedgerEdit(root)) return true;
    return stayEditUnlocked(stay);
  }

  function invoiceLocked(stay, root) {
    if (chargesEditable(stay, root)) return false;
    return !!(stay && stay.invoiceGenerated && invoiceNumber(stay));
  }

  function statusLabel(status) {
    return String(status || 'vacant')
      .replace(/_/g, ' ')
      .replace(/\b\w/g, function (c) {
        return c.toUpperCase();
      });
  }

  function toDateISO(value) {
    var text = String(value || '').trim();
    if (/^\d{4}-\d{2}-\d{2}/.test(text)) return text.slice(0, 10);
    return '';
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

  function billableNightsFromStay(stay) {
    var booked = Math.max(1, Number((stay && stay.nights) || 1));
    var fromStay = Number(stay && stay.billableNights);
    if (isFinite(fromStay) && fromStay >= booked) return Math.floor(fromStay);
    return Math.max(1, booked + overstayNightsFromStay(stay));
  }

  function folioLines(room, root) {
    var stay = (room && room.stay) || {};
    var unlocked = chargesEditable(stay, root);
    var lines = [];
    var bookedNights = Math.max(1, Number(stay.nights || 1));
    var overstayNights = overstayNightsFromStay(stay);
    var billableNights = billableNightsFromStay(stay);
    var roomRate = Math.max(0, Number(stay.roomRate || 0));
    var nightlyRates = Array.isArray(stay.nightlyRates) ? stay.nightlyRates : [];
    var roomLabel =
      (room && (room.roomTypeLabel || room.roomType)) || 'Room Charges';
    roomLabel = String(roomLabel).replace(/_/g, ' ');

    function sliceNightlySum(startIdx, count) {
      if (!nightlyRates.length || !(count > 0)) return null;
      var sum = 0;
      var last = roomRate;
      for (var i = 0; i < count; i++) {
        var idx = startIdx + i;
        var row =
          idx < nightlyRates.length
            ? nightlyRates[idx]
            : nightlyRates[nightlyRates.length - 1];
        if (row && row.roomRate != null) last = Math.max(0, Number(row.roomRate || 0));
        sum += last;
      }
      return round2(sum);
    }

    var bookedAmount = sliceNightlySum(0, bookedNights);
    var overstayAmount = sliceNightlySum(
      bookedNights,
      Math.max(0, billableNights - bookedNights)
    );
    if (bookedAmount == null && roomRate > 0) {
      bookedAmount = round2(roomRate * bookedNights);
    }
    if (overstayAmount == null && roomRate > 0 && overstayNights > 0) {
      overstayAmount = round2(roomRate * overstayNights);
    }

    if (bookedAmount > 0) {
      var bookedRate =
        nightlyRates.length && bookedNights
          ? round2(bookedAmount / bookedNights)
          : roomRate;
      lines.push({
        key: 'room',
        label: roomLabel,
        qty: bookedNights,
        rate: bookedRate,
        amount: bookedAmount,
        canEdit: true,
        canDelete: false,
        nameEditable: false
      });
      if (overstayAmount > 0 && billableNights > bookedNights) {
        var overRate =
          overstayNights > 0 ? round2(overstayAmount / overstayNights) : roomRate;
        lines.push({
          key: 'overstay',
          label:
            'Overstay (' +
            overstayNights +
            ' night' +
            (overstayNights === 1 ? '' : 's') +
            ')',
          qty: overstayNights,
          rate: overRate,
          amount: overstayAmount,
          canEdit: true,
          canDelete: false,
          nameEditable: false
        });
      }
    }
    [
      { key: 'extra_bed', label: 'Extra Bed', amount: Number(stay.extraBedAmount || 0) },
      {
        key: 'early_checkin',
        label: 'Early Check-in',
        amount: Number(stay.earlyCheckinAmount || 0)
      },
      {
        key: 'late_checkout',
        label: 'Late Check-out',
        amount: Number(stay.lateCheckoutAmount || 0)
      }
    ].forEach(function (row) {
      if (!(row.amount > 0)) return;
      lines.push({
        key: row.key,
        label: row.label,
        qty: 1,
        rate: row.amount,
        amount: round2(row.amount),
        canEdit: true,
        canDelete: true,
        nameEditable: false
      });
    });
    var folio = Array.isArray(stay.folioCharges) ? stay.folioCharges : [];
    folio.forEach(function (item, index) {
      if (!item) return;
      var kind = String(item.kind || '').toLowerCase();
      if (kind === 'restaurant_room_transfer' || kind === 'bar_room_transfer') return;
      var amount = Number(item.amount || 0);
      if (!(amount > 0)) return;
      var folioId = String(item.id || '').trim();
      if (!folioId && unlocked) {
        folioId = 'legacy-' + String(index + 1);
      }
      var labelFn = global.hotelFolioChargeDisplayLabel;
      lines.push({
        key: folioId ? 'folio:' + folioId : '',
        label:
          typeof labelFn === 'function'
            ? labelFn(item)
            : item.label || 'Other Charge',
        qty: 1,
        rate: amount,
        amount: round2(amount),
        canEdit: !!folioId,
        canDelete: !!folioId,
        nameEditable: true
      });
    });
    return lines;
  }

  function calcDiscountAmount(subtotal, type, value) {
    var base = Math.max(0, Number(subtotal) || 0);
    var n = Math.max(0, Number(value) || 0);
    if (!(base > 0) || !(n > 0)) return 0;
    if ((type || 'pct') === 'inr') return round2(Math.min(base, n));
    return round2(base * (Math.min(100, n) / 100));
  }

  function formatDiscountHint(type, value) {
    var n = Number(value) || 0;
    if (!(n > 0)) return '';
    if ((type || 'pct') === 'inr') return '(₹' + n.toLocaleString('en-IN') + ')';
    return '(' + n + '%)';
  }

  function discountNeedsReason(type, value, subtotal) {
    var n = Number(value);
    if (isNaN(n) || n <= 0) return false;
    if ((type || 'pct') === 'pct') return n > DISCOUNT_REASON_PCT;
    var base = Math.max(0, Number(subtotal) || 0);
    if (!(base > 0)) return false;
    return (Math.min(base, n) / base) * 100 > DISCOUNT_REASON_PCT;
  }

  function moneySummary(room, root) {
    var stay = room && room.stay && typeof room.stay === 'object' ? room.stay : null;
    var lines = folioLines(room, root);
    var subtotal = round2(
      lines.reduce(function (sum, row) {
        return sum + Number(row.amount || 0);
      }, 0)
    );
    if (!(subtotal > 0) && stay && stay.estimatedTotal != null && !(Number(stay.discountAmount) > 0)) {
      subtotal = round2(stay.estimatedTotal);
    }
    /* Prefer explicit stay gross: estimated + discount when discount was applied. */
    if (stay && stay.estimatedTotal != null && Number(stay.discountAmount) > 0) {
      var grossFromStay = round2(
        Number(stay.estimatedTotal || 0) + Number(stay.discountAmount || 0)
      );
      if (grossFromStay > subtotal) subtotal = grossFromStay;
    }
    var discountType = (stay && (stay.discountType || stay.discount_type)) || 'pct';
    var discountValue = Number(
      stay && (stay.discountValue != null ? stay.discountValue : stay.discount_value)
    );
    if (!isFinite(discountValue)) discountValue = 0;
    var discount =
      stay && stay.discountAmount != null
        ? round2(stay.discountAmount)
        : calcDiscountAmount(subtotal, discountType, discountValue);
    if (discount > subtotal) discount = subtotal;
    var taxable = round2(Math.max(0, subtotal - discount));
    var cgst = round2(taxable * CGST_RATE);
    var ugst = round2(taxable * UGST_RATE);
    var total = round2(taxable + cgst + ugst);
    var advance = Math.max(0, Number((stay && stay.advancePaid) || 0));
    var balance =
      stay && stay.combinedBalanceDue != null
        ? round2(stay.combinedBalanceDue)
        : stay && stay.balanceAmount != null
          ? round2(stay.balanceAmount)
          : Math.max(0, round2(total - advance));
    var fbTotal = round2(Number((stay && stay.fbTransferTotal) || 0));
    var fbBalance = round2(Number((stay && stay.fbTransferBalance) || 0));
    return {
      lines: lines,
      subtotal: subtotal,
      discount: discount,
      discountType: discountType,
      discountValue: discountValue,
      taxable: taxable,
      cgst: cgst,
      ugst: ugst,
      sgst: ugst,
      total: total,
      advance: advance,
      balance: balance
    };
  }

  function setText(el, text) {
    if (el) el.textContent = text;
  }

  function formatStayDate(value) {
    var raw = String(value || '').trim().slice(0, 10);
    var parts = raw.split('-');
    if (parts.length !== 3) return raw || '—';
    var months = [
      'January',
      'February',
      'March',
      'April',
      'May',
      'June',
      'July',
      'August',
      'September',
      'October',
      'November',
      'December'
    ];
    var mi = Number(parts[1]) - 1;
    var day = Number(parts[2]);
    var year = String(parts[0] || '');
    if (!isFinite(day) || mi < 0 || mi > 11 || year.length < 2) return raw || '—';
    return (
      String(day).padStart(2, '0') +
      '-' +
      months[mi] +
      '-' +
      year.slice(-2)
    );
  }

  function paintRoom(root, room) {
    lastRoot = root || lastRoot;
    lastRoom = room || null;
    var stay = room && room.stay && typeof room.stay === 'object' ? room.stay : null;
    var summary = moneySummary(room, root);
    lastSummary = summary;
    var status = String((room && room.status) || 'vacant').toLowerCase();
    var invNo = invoiceNumber(stay);

    setText($('[data-hri-guest]', root), guestName(stay));
    var roomLabel =
      typeof global.hotelInvoiceRoomLabel === 'function'
        ? global.hotelInvoiceRoomLabel(room)
        : (room && (room.mergeRoomLabel || room.mergeLabel || room.numberDisplay || room.number)) ||
          '—';
    setText($('[data-hri-room-number]', root), roomLabel || '—');
    var roomTypeLabel =
      (room && (room.roomTypeLabel || room.roomType)) ||
      '—';
    roomTypeLabel = String(roomTypeLabel).replace(/_/g, ' ').trim() || '—';
    setText($('[data-hri-room-type]', root), roomTypeLabel);

    var datesEl = $('[data-hri-dates]', root);
    if (datesEl) {
      if (stay) {
        datesEl.textContent =
          formatStayDate(stay.checkInDate || stay.check_in_date) +
          ' → ' +
          formatStayDate(stay.checkOutDate || stay.check_out_date);
      } else {
        datesEl.textContent = 'No active stay';
      }
    }

    var statusEl = $('[data-hri-status]', root);
    if (statusEl) {
      statusEl.textContent = (room && room.statusLabel) || statusLabel(status);
      statusEl.className = 'hri-status-chip hri-status-chip--' + status;
    }

    setText($('[data-hri-invoice-number]', root), invNo || '—');

    var nameInput = $('#hri-customer-name', root);
    var mobileInput = $('#hri-customer-mobile', root);
    if (nameInput) nameInput.value = guestName(stay);
    if (mobileInput) mobileInput.value = guestMobile(stay);

    var tbody = $('#hri-lines-body', root);
    var empty = $('#hri-empty', root);
    var ledgerEdit = isLedgerEdit(root);
    var editable = chargesEditable(stay, root);
    var locked = invoiceLocked(stay, root);
    if (tbody) {
      if (!summary.lines.length) {
        tbody.innerHTML = '';
        if (empty) empty.hidden = false;
      } else {
        if (empty) empty.hidden = true;
        tbody.innerHTML = summary.lines
          .map(function (row) {
            var canEdit =
              !locked &&
              !!row.key &&
              (ledgerEdit || editable || !!row.canEdit);
            var canDelete =
              !locked && (ledgerEdit || editable ? !!row.canDelete : !!row.canDelete);
            return (
              '<tr data-charge-key="' +
              escapeHtml(row.key || '') +
              '">' +
              '<td>' +
              escapeHtml(row.label) +
              '</td>' +
              '<td class="pos-inv-col-qty">' +
              escapeHtml(String(row.qty || 1)) +
              '</td>' +
              '<td class="pos-inv-col-rate">' +
              escapeHtml(money(row.rate)) +
              '</td>' +
              '<td class="pos-inv-col-amt"><span class="pos-inv-amt">' +
              escapeHtml(money(row.amount)) +
              '</span></td>' +
              '<td class="pos-inv-col-act"><div class="pos-inv-act-btns">' +
              '<button type="button" class="pos-inv-note-btn" data-hri-line-edit aria-label="Edit charge"' +
              (canEdit
                ? ' title="Edit charge"'
                : ' disabled title="' +
                  (locked
                    ? 'Invoice locked'
                    : 'This charge cannot be edited') +
                  '"') +
              '>' +
              '<svg viewBox="0 0 24 24"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>' +
              '</button>' +
              '<button type="button" class="pos-inv-del" data-hri-line-del aria-label="Remove charge"' +
              (canDelete
                ? ' title="Remove charge"'
                : ' disabled title="' +
                  (locked
                    ? 'Invoice locked'
                    : row.key === 'room'
                      ? 'Room tariff cannot be deleted'
                      : 'This charge cannot be removed') +
                  '"') +
              '>' +
              '<svg viewBox="0 0 24 24"><path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6M14 11v6"/></svg>' +
              '</button>' +
              '</div></td></tr>'
            );
          })
          .join('');
      }
    }

    setText($('#hri-sum-subtotal', root), money(summary.subtotal));
    var discRow = $('#hri-sum-discount-row', root);
    var discHint = $('#hri-sum-discount-hint', root);
    var discVal = $('#hri-sum-discount', root);
    var showDisc = Number(summary.discount) > 0 || Number(summary.discountValue) > 0;
    if (discRow) discRow.hidden = !showDisc;
    if (discHint) discHint.textContent = formatDiscountHint(summary.discountType, summary.discountValue);
    if (discVal) discVal.textContent = '−' + money(summary.discount);
    setText($('#hri-sum-cgst', root), money(summary.cgst));
    setText($('#hri-sum-ugst', root), money(summary.ugst));
    setText($('#hri-sum-advance', root), money(summary.advance));
    setText($('#hri-sum-balance', root), money(summary.balance));
    setText($('#hri-sum-total', root), money(summary.total));

    root.classList.toggle('is-invoice-generated', invoiceLocked(stay, root));
    root.classList.toggle('is-charges-editable', chargesEditable(stay, root));

    var genBtn = $('#hri-generate', root);
    var settleBtn = $('#hri-settle-bill', root);
    var printBtn = $('#hri-tool-print', root);
    var pdfBtn = $('#hri-tool-pdf', root);
    var discBtn = $('#hri-tool-discount', root);
    if (genBtn) {
      var genLabel = generateInvoiceLabel(root);
      genBtn.title = generateInvoiceTitle(root);
      if (!stay) {
        genBtn.disabled = true;
        genBtn.textContent = genLabel;
      } else if (invoiceLocked(stay, root)) {
        genBtn.disabled = true;
        genBtn.innerHTML =
          '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m8 12 3 3 5-6"/><circle cx="12" cy="12" r="9"/></svg> Invoice Generated';
      } else {
        genBtn.disabled = false;
        genBtn.innerHTML =
          '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M21 11.5a8.4 8.4 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.4 8.4 0 0 1-3.8-.9L3 21l1.9-5.7a8.4 8.4 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.4 8.4 0 0 1 3.8-.9h.5a8.5 8.5 0 0 1 8 8v.5Z"/></svg> ' +
          genLabel;
      }
    }
    if (settleBtn) {
      var canSettle = invoiceLocked(stay, root);
      settleBtn.hidden = !canSettle;
      settleBtn.disabled = !canSettle;
    }
    if (printBtn) printBtn.disabled = !stay;
    if (pdfBtn) pdfBtn.disabled = !stay;
    if (discBtn) {
      discBtn.disabled = !stay || invoiceLocked(stay, root);
      discBtn.classList.toggle('is-active', showDisc);
    }
    var customBtn = $('#hri-add-custom', root);
    if (customBtn) customBtn.disabled = !stay || invoiceLocked(stay, root);
  }

  function settleModal() {
    return document.getElementById('pos-inv-settle-modal');
  }

  function splitRows() {
    var wrap = document.getElementById('pos-inv-settle-splits');
    if (!wrap) return [];
    return Array.prototype.slice.call(
      wrap.querySelectorAll('.pos-inv-settle-split-row')
    );
  }

  function setSettleError(msg) {
    var el = document.getElementById('pos-inv-settle-error');
    if (!el) return;
    el.textContent = msg || '';
    el.classList.toggle('is-visible', !!msg);
  }

  function syncSplitRowState(row) {
    if (!row) return;
    var method = rowMethodValue(row);
    var txn = row.querySelector('.pos-inv-settle-txn');
    var needsTxn = !!METHODS_REQUIRING_TXN[method];
    row.classList.toggle('is-bank', needsTxn);
    if (txn) {
      txn.hidden = !needsTxn;
      if (!needsTxn) txn.value = '';
    }
  }

  function updateRemoveButtons() {
    var rows = splitRows();
    var multi = rows.length > 1;
    rows.forEach(function (row) {
      var removeBtn = row.querySelector('.pos-inv-settle-remove');
      var amountInput = row.querySelector('.pos-inv-settle-amount');
      if (removeBtn) removeBtn.hidden = !multi;
      if (amountInput) {
        amountInput.hidden = !multi;
        amountInput.required = multi;
      }
      row.classList.toggle('is-multi', multi);
      syncSplitRowState(row);
    });
    var addBtn = document.getElementById('pos-inv-settle-add-split');
    if (addBtn) addBtn.disabled = rows.length >= PAY_METHODS.length;
  }

  function billTarget() {
    return lastSummary ? lastSummary.balance : 0;
  }

  function refreshSplitBalance() {
    var rows = splitRows();
    var multi = rows.length > 1;
    var total = 0;
    var allFilled = true;
    rows.forEach(function (row) {
      var amountInput = row.querySelector('.pos-inv-settle-amount');
      var raw = amountInput ? String(amountInput.value || '').trim() : '';
      var amount = Number(raw);
      if (multi && (!raw || !isFinite(amount) || amount <= 0)) allFilled = false;
      total += isFinite(amount) ? amount : 0;
    });
    total = round2(total);
    if (!multi && rows.length === 1) total = billTarget();
    var target = billTarget();
    var splitTotalEl = document.getElementById('pos-inv-settle-split-total');
    var splitTargetEl = document.getElementById('pos-inv-settle-split-target');
    var balanceEl = document.getElementById('pos-inv-settle-balance');
    var payTotalEl = document.getElementById('pos-inv-settle-total');
    if (splitTotalEl) {
      splitTotalEl.setAttribute('data-amount', String(total));
      splitTotalEl.textContent = money(total);
    }
    if (splitTargetEl) {
      splitTargetEl.setAttribute('data-amount', String(target));
      splitTargetEl.textContent = money(target);
    }
    if (balanceEl) {
      balanceEl.hidden = !multi;
      balanceEl.classList.toggle(
        'is-mismatch',
        multi && (!allFilled || Math.abs(total - target) > 0.001)
      );
    }
    if (payTotalEl) {
      payTotalEl.setAttribute('data-amount', String(total));
      payTotalEl.textContent = money(total);
    }
    syncSettleSubmitEnabled();
  }

  function splitsMatchTarget() {
    var rows = splitRows();
    var target = round2(billTarget());
    if (rows.length <= 1) return target > 0.009 && !!rowMethodValue(rows[0]);
    var total = 0;
    var allFilled = true;
    var allModes = true;
    rows.forEach(function (row) {
      if (!rowMethodValue(row)) allModes = false;
      var amountInput = row.querySelector('.pos-inv-settle-amount');
      var raw = amountInput ? String(amountInput.value || '').trim() : '';
      var amount = Number(raw);
      if (!raw || !isFinite(amount) || amount <= 0) allFilled = false;
      total += isFinite(amount) ? amount : 0;
    });
    return allFilled && allModes && Math.abs(round2(total) - target) <= 0.009;
  }

  function syncSettleSubmitEnabled() {
    var submitBtn = document.getElementById('pos-inv-settle-submit');
    if (!submitBtn) return;
    var ok = splitsMatchTarget();
    if (ok) {
      splitRows().forEach(function (row) {
        var method = rowMethodValue(row);
        var txnInput = row.querySelector('.pos-inv-settle-txn');
        if (METHODS_REQUIRING_TXN[method] && !(txnInput && txnInput.value.trim())) {
          ok = false;
        }
      });
    }
    submitBtn.disabled = !ok;
    submitBtn.setAttribute('aria-disabled', ok ? 'false' : 'true');
  }

  function syncSingleAmount() {
    var rows = splitRows();
    if (rows.length !== 1) {
      refreshSplitBalance();
      return;
    }
    var amountInput = rows[0].querySelector('.pos-inv-settle-amount');
    if (amountInput) amountInput.value = String(billTarget() || '');
    refreshSplitBalance();
  }

  function syncRemainingSplitAmount(changedRow) {
    var rows = splitRows();
    if (rows.length < 2) return;
    var target = round2(billTarget());
    if (!(target > 0)) return;

    function amountRaw(row) {
      var input = row.querySelector('.pos-inv-settle-amount');
      return input ? String(input.value || '').trim() : '';
    }
    function setAmount(row, value) {
      var input = row.querySelector('.pos-inv-settle-amount');
      if (!input) return;
      input.value = value > 0 ? String(round2(value)) : '';
    }

    if (rows.length === 2) {
      var first = rows[0];
      var second = rows[1];
      if (!changedRow) {
        var firstRaw = amountRaw(first);
        var secondRaw = amountRaw(second);
        var firstAmt = Number(firstRaw);
        var secondAmt = Number(secondRaw);
        if (firstRaw && isFinite(firstAmt) && firstAmt > 0 && !secondRaw) {
          setAmount(second, target - firstAmt);
        } else if (secondRaw && isFinite(secondAmt) && secondAmt > 0 && !firstRaw) {
          setAmount(first, target - secondAmt);
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
    var hasEarlierAmount = false;
    for (var i = 0; i < rows.length - 1; i++) {
      var rawEarlier = amountRaw(rows[i]);
      var amountEarlier = Number(rawEarlier);
      if (rawEarlier && isFinite(amountEarlier) && amountEarlier > 0) {
        hasEarlierAmount = true;
        others += amountEarlier;
      }
    }
    setAmount(lastRow, hasEarlierAmount ? target - others : 0);
  }

  function rowMethodValue(row) {
    if (!row) return '';
    var hidden = row.querySelector('.pos-inv-settle-method-input');
    return hidden ? String(hidden.value || '') : '';
  }

  function methodLabel(method) {
    var key = String(method || '');
    for (var i = 0; i < PAY_METHODS.length; i++) {
      if (PAY_METHODS[i].value === key) return PAY_METHODS[i].label;
    }
    return key ? key : 'Select mode…';
  }

  function usedMethods(exceptRow) {
    var used = {};
    splitRows().forEach(function (row) {
      if (row === exceptRow) return;
      var method = rowMethodValue(row);
      if (method) used[method] = true;
    });
    return used;
  }

  function methodOptionsHtml(selected, exceptRow) {
    var used = usedMethods(exceptRow);
    return PAY_METHODS.map(function (m) {
      if (used[m.value] && m.value !== selected) return '';
      var on = m.value === selected;
      return (
        '<button type="button" class="se-filter-listbox-option' +
        (on ? ' is-selected' : '') +
        '" role="option" data-value="' +
        escapeHtml(m.value) +
        '" aria-selected="' +
        (on ? 'true' : 'false') +
        '">' +
        escapeHtml(m.label) +
        '</button>'
      );
    }).join('');
  }

  function closeMethodListbox(box) {
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

  function closeAllMethodListboxes(except) {
    var wrap = document.getElementById('pos-inv-settle-splits');
    if (!wrap) return;
    wrap.querySelectorAll('[data-se-listbox].is-open').forEach(function (box) {
      if (box !== except) closeMethodListbox(box);
    });
  }

  function openMethodListbox(box) {
    if (!box) return;
    closeAllMethodListboxes(box);
    var trigger = box.querySelector('.se-filter-chip-trigger');
    var list = box.querySelector('.se-filter-listbox');
    box.classList.add('is-open');
    if (trigger) trigger.setAttribute('aria-expanded', 'true');
    if (list) {
      list.hidden = false;
      var selected =
        list.querySelector('[aria-selected="true"]') ||
        list.querySelector('.se-filter-listbox-option');
      if (selected && selected.focus) {
        try {
          selected.focus({ preventScroll: true });
        } catch (err) {
          selected.focus();
        }
      }
    }
  }

  function refreshMethodOptionAvailability() {
    splitRows().forEach(function (row) {
      var listbox = row.querySelector('[data-se-listbox]');
      var list = row.querySelector('.se-filter-listbox');
      var selected = rowMethodValue(row);
      if (list) list.innerHTML = methodOptionsHtml(selected, row);
      if (listbox && listbox.classList.contains('is-open')) {
        var selectedOpt =
          list &&
          (list.querySelector('[aria-selected="true"]') ||
            list.querySelector('.se-filter-listbox-option'));
        if (selectedOpt && selectedOpt.focus) {
          try {
            selectedOpt.focus({ preventScroll: true });
          } catch (err) {
            selectedOpt.focus();
          }
        }
      }
      syncSplitRowState(row);
    });
    var addBtn = document.getElementById('pos-inv-settle-add-split');
    if (addBtn) addBtn.disabled = splitRows().length >= PAY_METHODS.length;
  }

  function bindMethodListbox(row) {
    var box = row && row.querySelector('[data-se-listbox]');
    if (!box || box.getAttribute('data-bound') === '1') return;
    box.setAttribute('data-bound', '1');
    var trigger = box.querySelector('.se-filter-chip-trigger');
    var list = box.querySelector('.se-filter-listbox');
    var hidden = box.querySelector('.pos-inv-settle-method-input');
    var valueEl = box.querySelector('.se-filter-chip-value');
    if (!trigger || !list || !hidden) return;

    trigger.addEventListener('click', function (e) {
      e.preventDefault();
      e.stopPropagation();
      if (box.classList.contains('is-open')) closeMethodListbox(box);
      else openMethodListbox(box);
    });
    trigger.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowDown' || e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        openMethodListbox(box);
      } else if (e.key === 'Escape') {
        closeMethodListbox(box);
      }
    });
    list.addEventListener('click', function (e) {
      var option = e.target.closest('.se-filter-listbox-option');
      if (!option || !list.contains(option)) return;
      e.preventDefault();
      var value = option.getAttribute('data-value') || '';
      var label = (option.textContent || '').trim();
      hidden.value = value;
      if (valueEl) {
        valueEl.textContent = label || 'Select mode…';
        valueEl.classList.toggle('staff-supplier-placeholder', !value);
      }
      list.querySelectorAll('.se-filter-listbox-option').forEach(function (opt) {
        var on = opt === option;
        opt.classList.toggle('is-selected', on);
        opt.setAttribute('aria-selected', on ? 'true' : 'false');
      });
      closeMethodListbox(box);
      syncSplitRowState(row);
      refreshMethodOptionAvailability();
      refreshSplitBalance();
    });
  }

  function addSplitRow(preferredMethod, amount) {
    var wrap = document.getElementById('pos-inv-settle-splits');
    if (!wrap) return;
    if (splitRows().length >= PAY_METHODS.length) return;
    var used = usedMethods(null);
    var method = preferredMethod == null ? 'cash' : String(preferredMethod || '');
    if (method && used[method]) {
      method = '';
      for (var i = 0; i < PAY_METHODS.length; i++) {
        if (!used[PAY_METHODS[i].value]) {
          method = PAY_METHODS[i].value;
          break;
        }
      }
    }
    var label = methodLabel(method);
    var uid = 'hri-settle-split-' + Date.now() + '-' + Math.floor(Math.random() * 1000);
    var row = document.createElement('div');
    row.className = 'rt-split-row pos-inv-settle-split-row';
    row.innerHTML =
      '<div class="se-filter-chip se-filter-chip--payment se-filter-chip--listbox ep-form-listbox staff-expense-payment-listbox pos-inv-settle-method-listbox" data-se-listbox>' +
      '<div class="se-filter-chip-control">' +
      '<span class="se-filter-chip-icon" aria-hidden="true">' +
      '<svg viewBox="0 0 24 24" width="18" height="18" fill="none"><rect x="2" y="5" width="20" height="14" rx="2"/><path d="M2 10h20"/></svg>' +
      '</span>' +
      '<input type="hidden" class="pos-inv-settle-method-input" value="' +
      escapeHtml(method) +
      '">' +
      '<button type="button" class="se-filter-chip-trigger" id="' +
      uid +
      '-trigger" aria-haspopup="listbox" aria-expanded="false" aria-controls="' +
      uid +
      '-list" aria-label="Payment mode">' +
      '<span class="se-filter-chip-value' +
      (method ? '' : ' staff-supplier-placeholder') +
      '">' +
      escapeHtml(label) +
      '</span>' +
      '</button>' +
      '<span class="se-filter-chip-chev" aria-hidden="true">' +
      '<svg viewBox="0 0 24 24" width="16" height="16" fill="none"><polyline points="6 9 12 15 18 9"/></svg>' +
      '</span>' +
      '</div>' +
      '<div class="se-filter-listbox" id="' +
      uid +
      '-list" role="listbox" aria-label="Payment mode" hidden>' +
      methodOptionsHtml(method, null) +
      '</div>' +
      '</div>' +
      '<input class="staff-input pos-inv-settle-amount rt-split-amount" type="number" min="0.01" step="0.01" placeholder="Amount" aria-label="Mode amount" value="' +
      escapeHtml(amount == null ? '' : String(amount)) +
      '">' +
      '<input class="staff-input pos-inv-settle-txn rt-split-txn" type="text" placeholder="Txn / UTR ID" aria-label="Transaction ID" hidden autocomplete="off">' +
      '<button type="button" class="pos-inv-settle-remove rt-split-remove" aria-label="Remove payment mode" hidden>&times;</button>';
    wrap.appendChild(row);

    var amountInput = row.querySelector('.pos-inv-settle-amount');
    var txnInput = row.querySelector('.pos-inv-settle-txn');
    var removeBtn = row.querySelector('.pos-inv-settle-remove');
    bindMethodListbox(row);
    if (amountInput) {
      amountInput.addEventListener('input', function () {
        syncRemainingSplitAmount(row);
        refreshSplitBalance();
      });
    }
    if (txnInput) txnInput.addEventListener('input', syncSettleSubmitEnabled);
    if (removeBtn) {
      removeBtn.addEventListener('click', function () {
        if (splitRows().length <= 1) return;
        closeAllMethodListboxes();
        row.remove();
        updateRemoveButtons();
        refreshMethodOptionAvailability();
        syncRemainingSplitAmount(null);
        syncSingleAmount();
      });
    }
    syncSplitRowState(row);
    updateRemoveButtons();
    refreshMethodOptionAvailability();
    refreshSplitBalance();
  }

  function resetSplits() {
    closeAllMethodListboxes();
    var wrap = document.getElementById('pos-inv-settle-splits');
    if (wrap) wrap.innerHTML = '';
    addSplitRow('cash', '');
    syncSingleAmount();
  }

  function paintAllocBody() {
    var body = document.getElementById('pos-inv-settle-alloc-body');
    var meta = document.getElementById('pos-inv-settle-alloc-meta');
    var roomNo = (lastRoom && lastRoom.number) || '—';
    var inv = invoiceNumber(lastRoom && lastRoom.stay);
    var balance = billTarget();
    if (meta) meta.textContent = inv ? 'Invoice ' + inv : 'Room ' + roomNo;
    if (body) {
      body.innerHTML =
        '<tr>' +
        '<td>Room ' +
        escapeHtml(String(roomNo)) +
        '</td>' +
        '<td class="pl-col-amount">' +
        escapeHtml(money(balance)) +
        '</td>' +
        '<td class="pl-col-amount">' +
        escapeHtml(money(balance)) +
        '</td>' +
        '</tr>';
    }
  }

  function openSettleModal() {
    if (!lastRoom || !lastRoom.stay) {
      showToast('No active stay to settle.', true);
      return;
    }
    if (!invoiceLocked(lastRoom.stay)) {
      showToast('Generate the invoice before settling.', true);
      return;
    }
    var modal = settleModal();
    if (!modal) return;
    setSettleError('');
    var notes = document.getElementById('pos-inv-settle-notes');
    if (notes) notes.value = '';
    paintAllocBody();
    resetSplits();
    modal.hidden = false;
    modal.removeAttribute('hidden');
  }

  function closeSettleModal() {
    var modal = settleModal();
    if (modal) {
      modal.hidden = true;
      modal.setAttribute('hidden', '');
    }
    closeAllMethodListboxes();
    setSettleError('');
  }

  function syncDiscountTypeUi(type) {
    discountDraftType = type === 'inr' ? 'inr' : 'pct';
    var modal = document.getElementById('hri-discount-modal');
    if (!modal) return;
    modal.querySelectorAll('[data-hri-adj-type]').forEach(function (btn) {
      btn.classList.toggle(
        'is-active',
        btn.getAttribute('data-hri-adj-type') === discountDraftType
      );
    });
    var label = document.getElementById('hri-discount-amount-label');
    if (label) {
      label.textContent =
        discountDraftType === 'inr' ? 'Amount (₹)' : 'Amount (%)';
    }
  }

  function updateDiscountPreview() {
    var amountEl = document.getElementById('hri-discount-amount');
    var preview = document.getElementById('hri-discount-preview');
    var reasonField = document.getElementById('hri-discount-reason-field');
    var reasonEl = document.getElementById('hri-discount-reason');
    var raw = amountEl ? String(amountEl.value || '').trim() : '';
    var value = raw === '' ? 0 : Number(raw);
    if (isNaN(value) || value < 0) value = 0;
    var subtotal = lastSummary ? lastSummary.subtotal : 0;
    var amount = calcDiscountAmount(subtotal, discountDraftType, value);
    if (preview) preview.textContent = 'Discount: ' + money(amount);
    var needs = discountNeedsReason(discountDraftType, value, subtotal);
    if (reasonEl) {
      reasonEl.disabled = !needs;
      reasonEl.required = needs;
      if (!needs) reasonEl.value = '';
    }
    if (reasonField) {
      reasonField.hidden = !needs;
      reasonField.classList.toggle('is-shown', needs);
    }
  }

  function openDiscountModal() {
    if (!lastRoom || !lastRoom.stay) {
      showToast('No active stay for discount.', true);
      return;
    }
    if (invoiceLocked(lastRoom.stay)) {
      showToast('Discount cannot be changed after the invoice is generated.', true);
      return;
    }
    var modal = document.getElementById('hri-discount-modal');
    if (!modal) return;
    var stay = lastRoom.stay;
    var type = stay.discountType || stay.discount_type || 'pct';
    var value = Number(
      stay.discountValue != null ? stay.discountValue : stay.discount_value || 0
    );
    syncDiscountTypeUi(type);
    var amountEl = document.getElementById('hri-discount-amount');
    if (amountEl) amountEl.value = value > 0 ? String(value) : '';
    var reasonEl = document.getElementById('hri-discount-reason');
    if (reasonEl) {
      reasonEl.value = stay.discountReason || stay.discount_reason || '';
    }
    updateDiscountPreview();
    modal.hidden = false;
    if (amountEl) {
      try {
        amountEl.focus();
      } catch (err) {}
    }
  }

  function closeDiscountModal() {
    var modal = document.getElementById('hri-discount-modal');
    if (modal) modal.hidden = true;
  }

  function openCustomModal(editLine) {
    if (!lastRoom || !lastRoom.stay) {
      showToast('No active stay for custom charges.', true);
      return;
    }
    if (invoiceLocked(lastRoom.stay)) {
      showToast('Charges cannot be changed after the invoice is generated.', true);
      return;
    }
    var modal = document.getElementById('hri-custom-modal');
    if (!modal) return;
    var titleEl = document.getElementById('hri-custom-title');
    var keyEl = document.getElementById('hri-custom-key');
    var nameEl = document.getElementById('hri-custom-name');
    var rateEl = document.getElementById('hri-custom-rate');
    var saveBtn = document.getElementById('hri-custom-save');
    var nameLabel = document.getElementById('hri-custom-name-label');
    var rateLabel = document.getElementById('hri-custom-rate-label');
    var editing = !!(editLine && editLine.key);
    if (keyEl) keyEl.value = editing ? editLine.key : '';
    if (titleEl) titleEl.textContent = editing ? 'Edit Charge' : 'Custom Charges';
    if (saveBtn) saveBtn.textContent = editing ? 'Save' : 'Add Charge';
    if (nameLabel) nameLabel.textContent = editing ? 'Item' : 'Charge name';
    if (rateLabel) {
      rateLabel.textContent =
        editing && editLine.key === 'room' ? 'Rate (₹) / night' : 'Rate (₹)';
    }
    if (nameEl) {
      nameEl.value = editing ? editLine.label || '' : '';
      nameEl.readOnly = editing ? !editLine.nameEditable : false;
      nameEl.tabIndex = nameEl.readOnly ? -1 : 0;
    }
    if (rateEl) {
      rateEl.value = editing
        ? String(
            editLine.key === 'room'
              ? editLine.rate
              : editLine.amount != null
                ? editLine.amount
                : editLine.rate || ''
          )
        : '';
    }
    modal.hidden = false;
    var focusEl = nameEl && !nameEl.readOnly ? nameEl : rateEl;
    if (focusEl) {
      try {
        focusEl.focus();
      } catch (err) {}
    }
  }

  function closeCustomModal() {
    var modal = document.getElementById('hri-custom-modal');
    if (modal) modal.hidden = true;
    var keyEl = document.getElementById('hri-custom-key');
    if (keyEl) keyEl.value = '';
  }

  function findLineByKey(key) {
    if (!lastSummary || !lastSummary.lines) return null;
    for (var i = 0; i < lastSummary.lines.length; i++) {
      if (lastSummary.lines[i].key === key) return lastSummary.lines[i];
    }
    return null;
  }

  function saveCustomCharge(root) {
    var keyEl = document.getElementById('hri-custom-key');
    var nameEl = document.getElementById('hri-custom-name');
    var rateEl = document.getElementById('hri-custom-rate');
    var chargeKey = keyEl ? String(keyEl.value || '').trim() : '';
    var label = nameEl ? String(nameEl.value || '').trim() : '';
    var rate = rateEl ? Number(rateEl.value) : 0;
    if (!(rate > 0)) {
      showToast('Enter a rate greater than zero.', true);
      return Promise.reject(new Error('rate required'));
    }
    var saveBtn = document.getElementById('hri-custom-save');
    if (saveBtn) saveBtn.disabled = true;

    var payload;
    if (chargeKey) {
      payload = {
        action: 'update_charge',
        chargeKey: chargeKey,
        label: label,
        amount: round2(rate),
        rate: round2(rate)
      };
    } else {
      if (!label) {
        showToast('Enter a charge name.', true);
        if (saveBtn) saveBtn.disabled = false;
        return Promise.reject(new Error('name required'));
      }
      payload = {
        action: 'add_custom_charge',
        label: label,
        amount: round2(rate)
      };
    }

    return putAction(root, payload)
      .then(function (result) {
        if (!result.ok || !result.data || !result.data.ok) {
          throw new Error(
            (result.data && result.data.error) ||
              (chargeKey ? 'Could not update charge.' : 'Could not add custom charge.')
          );
        }
        paintRoom(root, result.data.room);
        closeCustomModal();
        showToast(chargeKey ? 'Charge updated.' : 'Custom charge added.');
        return result.data.room;
      })
      .catch(function (err) {
        showToast(err.message || 'Could not save charge.', true);
        throw err;
      })
      .finally(function () {
        if (saveBtn) saveBtn.disabled = false;
      });
  }

  function deleteLineCharge(root, chargeKey) {
    if (!chargeKey) return Promise.reject(new Error('missing key'));
    if (invoiceLocked(lastRoom && lastRoom.stay)) {
      showToast('Charges cannot be deleted after the invoice is generated.', true);
      return Promise.reject(new Error('locked'));
    }
    var line = findLineByKey(chargeKey);
    var label = line ? line.label : 'this charge';
    var ok = true;
    try {
      ok = window.confirm('Remove “' + label + '” from this folio?');
    } catch (err) {}
    if (!ok) return Promise.resolve();
    return putAction(root, {
      action: 'delete_charge',
      chargeKey: chargeKey
    })
      .then(function (result) {
        if (!result.ok || !result.data || !result.data.ok) {
          throw new Error(
            (result.data && result.data.error) || 'Could not remove charge.'
          );
        }
        paintRoom(root, result.data.room);
        showToast('Charge removed.');
        return result.data.room;
      })
      .catch(function (err) {
        showToast(err.message || 'Could not remove charge.', true);
        throw err;
      });
  }

  function applyDiscount(root) {
    var amountEl = document.getElementById('hri-discount-amount');
    var reasonEl = document.getElementById('hri-discount-reason');
    var raw = amountEl ? String(amountEl.value || '').trim() : '';
    var value = raw === '' ? 0 : Number(raw);
    if (isNaN(value) || value < 0) {
      showToast('Enter a valid discount.', true);
      return Promise.reject(new Error('invalid discount'));
    }
    var subtotal = lastSummary ? lastSummary.subtotal : 0;
    if (discountNeedsReason(discountDraftType, value, subtotal)) {
      var reason = reasonEl ? String(reasonEl.value || '').trim() : '';
      if (!reason) {
        showToast('Enter a reason for discounts over ' + DISCOUNT_REASON_PCT + '%.', true);
        return Promise.reject(new Error('reason required'));
      }
    }
    var applyBtn = document.getElementById('hri-discount-apply');
    if (applyBtn) applyBtn.disabled = true;
    return putAction(root, {
      action: 'set_discount',
      discountType: discountDraftType,
      discountValue: value,
      discountReason: reasonEl ? String(reasonEl.value || '').trim() : ''
    })
      .then(function (result) {
        if (!result.ok || !result.data || !result.data.ok) {
          throw new Error(
            (result.data && result.data.error) || 'Could not apply discount.'
          );
        }
        paintRoom(root, result.data.room);
        closeDiscountModal();
        showToast(
          value > 0 ? 'Discount applied.' : 'Discount cleared.'
        );
        return result.data.room;
      })
      .catch(function (err) {
        showToast(err.message || 'Could not apply discount.', true);
        throw err;
      })
      .finally(function () {
        if (applyBtn) applyBtn.disabled = false;
      });
  }

  function collectSplits() {
    var rows = splitRows();
    var target = billTarget();
    var splits = [];
    var invalid = '';
    rows.forEach(function (row) {
      var method = rowMethodValue(row);
      var amountInput = row.querySelector('.pos-inv-settle-amount');
      var txnInput = row.querySelector('.pos-inv-settle-txn');
      var amount = rows.length === 1 ? target : Number(amountInput && amountInput.value);
      var reference = txnInput ? String(txnInput.value || '').trim() : '';
      if (!method) {
        invalid = 'Select a payment mode for each row.';
        return;
      }
      if (!(amount > 0)) {
        invalid = 'Enter a valid amount for each payment mode.';
        return;
      }
      if (METHODS_REQUIRING_TXN[method] && !reference) {
        invalid = 'Transaction ID is required for bank transfer.';
        return;
      }
      splits.push({
        method: method,
        amount: round2(amount),
        reference: reference
      });
    });
    if (invalid) return { splits: [], error: invalid };
    var sum = round2(
      splits.reduce(function (s, item) {
        return s + Number(item.amount || 0);
      }, 0)
    );
    if (rows.length > 1 && Math.abs(sum - target) > 0.009) {
      return {
        splits: [],
        error:
          'Modes total ₹' +
          sum.toFixed(2) +
          ' must match balance due ₹' +
          target.toFixed(2) +
          '.'
      };
    }
    if (sum > target + 0.009) {
      return {
        splits: [],
        error:
          'Modes total ₹' +
          sum.toFixed(2) +
          ' exceeds balance due ₹' +
          target.toFixed(2) +
          '.'
      };
    }
    if (!(sum > 0)) {
      return { splits: [], error: 'Enter a payment amount.' };
    }
    return { splits: splits, error: '' };
  }

  function putAction(root, body) {
    var api = actionApiUrl(root);
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

  function generateInvoice(root) {
    var genBtn = $('#hri-generate', root);
    if (genBtn) genBtn.disabled = true;
    var note = (($('#hri-notes', root) || {}).value || '').trim();
    return putAction(root, {
      action: 'generate_invoice',
      payment_splits: [],
      note: note
    })
      .then(function (result) {
        if (!result.ok || !result.data || !result.data.ok) {
          throw new Error(
            (result.data && result.data.error) || 'Could not generate invoice.'
          );
        }
        paintRoom(root, result.data.room);
        var inv = invoiceNumber(result.data.room && result.data.room.stay);
        showToast(inv ? 'Invoice ' + inv + ' updated.' : 'Invoice updated.');
        if (isLedgerEdit(root)) {
          var backUrl = root.getAttribute('data-ledger-back-url') || '/hotel/invoice-ledger';
          window.setTimeout(function () {
            navigateTo(backUrl);
          }, 600);
        }
        return result.data.room;
      })
      .catch(function (err) {
        showToast(err.message || 'Could not generate invoice.', true);
        paintRoom(root, lastRoom);
        throw err;
      });
  }

  function recordPayment(root) {
    if (!splitsMatchTarget()) {
      setSettleError('Modes total must match the balance due.');
      syncSettleSubmitEnabled();
      return Promise.reject(new Error('mismatch'));
    }
    var collected = collectSplits();
    if (collected.error) {
      setSettleError(collected.error);
      return Promise.reject(new Error(collected.error));
    }
    var note = (
      (document.getElementById('pos-inv-settle-notes') || {}).value || ''
    ).trim();
    var saveBtn = document.getElementById('pos-inv-settle-submit');
    if (saveBtn) saveBtn.disabled = true;
    setSettleError('');
    return putAction(root, {
      action: 'record_payment',
      payment_splits: collected.splits,
      note: note
    })
      .then(function (result) {
        if (!result.ok || !result.data || !result.data.ok) {
          throw new Error(
            (result.data && result.data.error) || 'Could not record payment.'
          );
        }
        paintRoom(root, result.data.room);
        closeSettleModal();
        showToast('Payment recorded.');
        return result.data.room;
      })
      .catch(function (err) {
        setSettleError(err.message || 'Could not record payment.');
        throw err;
      })
      .finally(function () {
        syncSettleSubmitEnabled();
      });
  }

  function printInvoice(opts) {
    opts = opts || {};
    if (!lastRoom || !lastRoom.stay) {
      showToast('No active stay to preview.', true);
      return;
    }
    if (typeof global.openHotelRoomInvoice !== 'function') {
      showToast('Invoice preview is unavailable.', true);
      return;
    }
    if (!global.openHotelRoomInvoice(lastRoom, { autoPrint: !!opts.autoPrint })) {
      showToast('Allow pop-ups to view the invoice.', true);
      return;
    }
    if (opts.skipAgent) return;
    if (typeof global.HotelPrintAgent === 'object' && global.HotelPrintAgent.print) {
      var html =
        typeof global.buildHotelRoomInvoiceHtml === 'function'
          ? global.buildHotelRoomInvoiceHtml(lastRoom, {})
          : '';
      if (html) {
        global.HotelPrintAgent.print({
          printerRole: 'hotel_invoice',
          documentType: 'invoice',
          contentType: 'html',
          contentEncoding: 'utf8',
          content: html,
          idempotencyKey:
            'hotel-inv-' +
            (invoiceNumber(lastRoom.stay) || lastRoom.id || 'preview')
        }).catch(function () {});
      }
    }
  }

  function bindNotes(root) {
    var notes = $('#hri-notes', root);
    var count = $('#hri-notes-count', root);
    if (!notes || notes.__hriNotesBound) return;
    notes.__hriNotesBound = true;
    function sync() {
      var len = (notes.value || '').length;
      if (count) count.textContent = len + ' / 200';
    }
    notes.addEventListener('input', sync);
    sync();
  }

  function bindEvents(root) {
    if (!root || root.__hriBound) return;
    root.__hriBound = true;

    root.addEventListener('click', function (event) {
      var back = event.target.closest('[data-hri-back]');
      if (back && root.contains(back)) {
        event.preventDefault();
        navigateTo(
          back.getAttribute('href') || root.getAttribute('data-room-detail-url')
        );
        return;
      }
      var actionEl = event.target.closest('[data-hri-action]');
      if (actionEl && root.contains(actionEl)) {
        var action = actionEl.getAttribute('data-hri-action');
        event.preventDefault();
        if (action === 'generate') generateInvoice(root);
        else if (action === 'settle-bill') openSettleModal();
        else if (action === 'discount') openDiscountModal();
        else if (action === 'add-custom') openCustomModal(null);
        else if (action === 'print') printInvoice({ autoPrint: false });
        else if (action === 'pdf') printInvoice({ autoPrint: false, skipAgent: true });
        return;
      }
      var editBtn = event.target.closest('[data-hri-line-edit]');
      if (editBtn && root.contains(editBtn)) {
        event.preventDefault();
        if (editBtn.disabled) return;
        var editRow = editBtn.closest('tr');
        var editKey = editRow ? editRow.getAttribute('data-charge-key') : '';
        openCustomModal(findLineByKey(editKey));
        return;
      }
      var delBtn = event.target.closest('[data-hri-line-del]');
      if (delBtn && root.contains(delBtn)) {
        event.preventDefault();
        if (delBtn.disabled) return;
        var delRow = delBtn.closest('tr');
        var delKey = delRow ? delRow.getAttribute('data-charge-key') : '';
        deleteLineCharge(root, delKey);
        return;
      }
      if (event.target.closest('[data-hri-discount-close]')) {
        event.preventDefault();
        closeDiscountModal();
        return;
      }
      if (event.target.closest('[data-hri-custom-close]')) {
        event.preventDefault();
        closeCustomModal();
        return;
      }
      var adjTypeBtn = event.target.closest('[data-hri-adj-type]');
      if (adjTypeBtn && root.contains(adjTypeBtn)) {
        event.preventDefault();
        syncDiscountTypeUi(adjTypeBtn.getAttribute('data-hri-adj-type'));
        updateDiscountPreview();
        return;
      }
      if (event.target.closest('#hri-discount-apply')) {
        event.preventDefault();
        applyDiscount(root);
        return;
      }
      if (event.target.closest('#hri-custom-save')) {
        event.preventDefault();
        saveCustomCharge(root);
        return;
      }
      if (event.target.closest('[data-hri-settle-close], [data-hotel-settle-close]')) {
        event.preventDefault();
        closeSettleModal();
        return;
      }
      if (event.target.closest('#pos-inv-settle-add-split')) {
        event.preventDefault();
        closeAllMethodListboxes();
        if (splitRows().length === 1) {
          var firstAmount = splitRows()[0].querySelector('.pos-inv-settle-amount');
          if (firstAmount) firstAmount.value = '';
        }
        addSplitRow('', '');
        syncRemainingSplitAmount(null);
        updateRemoveButtons();
        refreshMethodOptionAvailability();
        refreshSplitBalance();
        return;
      }
      if (event.target.closest('#pos-inv-settle-submit')) {
        event.preventDefault();
        recordPayment(root);
      }
    });

    document.addEventListener('click', function (event) {
      if (!root.contains(event.target)) {
        closeAllMethodListboxes();
        return;
      }
      if (!event.target.closest('#pos-inv-settle-splits [data-se-listbox]')) {
        closeAllMethodListboxes();
      }
    });

    var amountEl = document.getElementById('hri-discount-amount');
    if (amountEl && !amountEl.__hriDiscBound) {
      amountEl.__hriDiscBound = true;
      amountEl.addEventListener('input', updateDiscountPreview);
    }
  }

  function loadRoom(root) {
    var bootstrap = root.getAttribute('data-room-bootstrap') || '';
    if (bootstrap) {
      try {
        paintRoom(root, JSON.parse(bootstrap));
      } catch (err) {}
    }
    if (isLedgerEdit(root)) {
      var invoiceUrl = invoiceLoadUrl(root);
      if (!invoiceUrl) return Promise.resolve();
      return fetch(invoiceUrl, {
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
          if (result.ok && result.data && result.data.ok && result.data.room) {
            paintRoom(root, result.data.room);
          }
        })
        .catch(function () {});
    }
    var api = root.getAttribute('data-room-api') || '';
    if (!api) return Promise.resolve();
    return fetch(api, {
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
        if (result.ok && result.data && result.data.ok && result.data.room) {
          paintRoom(root, result.data.room);
        }
      })
      .catch(function () {});
  }

  function initHotelRoomInvoicePage() {
    var root = document.getElementById('hotel-room-invoice-page');
    if (!root) return;
    lastRoot = root;
    bindEvents(root);
    bindNotes(root);
    loadRoom(root).then(function () {
      if (root.getAttribute('data-open-settle') === '1') {
        if (invoiceLocked(lastRoom && lastRoom.stay)) {
          openSettleModal();
        }
      }
    });
  }

  global.initHotelRoomInvoicePage = initHotelRoomInvoicePage;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initHotelRoomInvoicePage);
  } else {
    initHotelRoomInvoicePage();
  }
})(window);
