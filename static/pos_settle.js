/**
 * Shared POS settle / Payment Details modal.
 * Used by Create Invoice and Tables → Today’s Invoices.
 */
(function (global) {
  'use strict';

  var POS_PAYMENT_METHODS = [
    ['cash', 'Cash'],
    ['upi', 'UPI'],
    ['card', 'Card'],
    ['room_transfer', 'Room Transfer'],
    ['bank_transfer', 'Bank Transfer'],
    ['swiggy', 'Swiggy'],
    ['zomato', 'Zomato']
  ];
  var POS_METHODS_REQUIRING_TXN = { bank_transfer: true };
  try {
    var methodsEl = document.getElementById('pos-inv-payment-methods-data');
    if (methodsEl) {
      var parsedMethods = JSON.parse(methodsEl.textContent || '[]');
      if (parsedMethods && parsedMethods.length) POS_PAYMENT_METHODS = parsedMethods;
    }
  } catch (err) {}

  var session = {
    invoiceId: null,
    items: [],
    settleSelectedUrl: '',
    orderNo: '',
    tableLabel: '',
    grandTotal: 0,
    apiBase: '',
    onSettled: null,
    onClose: null,
    preferredHotelRoomId: '',
    preferredHotelRoomNumber: '',
    editingSettlement: false
  };
  var occupiedRoomsState = {
    loading: false,
    loaded: false,
    rooms: []
  };

  function escapeHtml(str) {
    return String(str == null ? '' : str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function money(n) {
    var v = Math.round((Number(n) || 0) * 100) / 100;
    try {
      return (
        '₹' +
        v.toLocaleString('en-IN', {
          minimumFractionDigits: 2,
          maximumFractionDigits: 2
        })
      );
    } catch (e) {
      return '₹' + v.toFixed(2);
    }
  }

  function toast(msg) {
    if (typeof global.deToast === 'function') {
      global.deToast(msg);
      return;
    }
    var el =
      document.getElementById('pos-tables-toast') ||
      document.getElementById('pos-inv-toast');
    if (!el) {
      try {
        window.alert(msg);
      } catch (e2) {}
      return;
    }
    el.textContent = msg;
    el.hidden = false;
    clearTimeout(el.__toastTimer);
    el.__toastTimer = setTimeout(function () {
      el.hidden = true;
    }, 3200);
  }

  function isBrowserOnline() {
    return !(typeof navigator !== 'undefined' && navigator.onLine === false);
  }

  function resolveApiBase(explicit) {
    if (explicit) return String(explicit).replace(/\/$/, '');
    var el =
      document.getElementById('pos-invoice-page') ||
      document.getElementById('pos-tables-page') ||
      document.querySelector('[data-pos-api-base]');
    var base = (el && el.getAttribute('data-pos-api-base')) || '';
    if (!base) {
      base =
        (window.location.pathname || '').indexOf('/bar-point-of-sale') === 0
          ? '/bar-point-of-sale'
          : '/point-of-sale';
    }
    return String(base).replace(/\/$/, '') || '/point-of-sale';
  }

  function settleBillTotal() {
    return Math.round((Number(session.grandTotal) || 0) * 100) / 100;
  }

  function settleMoneyLabel(value) {
    return money(value);
  }

  function setSettleError(message) {
    var el = document.getElementById('pos-inv-settle-error');
    if (!el) return;
    if (message) {
      el.textContent = message;
      el.classList.add('is-visible');
    } else {
      el.textContent = '';
      el.classList.remove('is-visible');
    }
  }

  function settleSplitRows() {
    var root = document.getElementById('pos-inv-settle-splits');
    if (!root) return [];
    return Array.prototype.slice.call(
      root.querySelectorAll('.rt-split-row, .pos-inv-settle-split-row')
    );
  }

  function settleMethodLabel(method) {
    var key = String(method || '');
    for (var i = 0; i < POS_PAYMENT_METHODS.length; i++) {
      if (POS_PAYMENT_METHODS[i][0] === key) return POS_PAYMENT_METHODS[i][1];
    }
    return key ? key : 'Select mode…';
  }

  function settleRowMethodValue(row) {
    if (!row) return '';
    var hidden = row.querySelector('.pos-inv-settle-method-input');
    return hidden ? String(hidden.value || '') : '';
  }

  function settleUsedMethods(exceptRow) {
    var used = {};
    settleSplitRows().forEach(function (row) {
      if (row === exceptRow) return;
      var method = settleRowMethodValue(row);
      if (method) used[method] = true;
    });
    return used;
  }

  function settleMethodOptionsHtml(selected, exceptRow) {
    var used = settleUsedMethods(exceptRow);
    return POS_PAYMENT_METHODS.map(function (pair) {
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
    }).join('');
  }

  function closeSettleSplitListbox(root) {
    if (!root) return;
    var trigger = root.querySelector('.se-filter-chip-trigger');
    var list = root.querySelector('.se-filter-listbox');
    root.classList.remove('is-open');
    if (trigger) trigger.setAttribute('aria-expanded', 'false');
    if (list) {
      list.hidden = true;
      list.scrollTop = 0;
    }
  }

  function closeAllSettleSplitListboxes(except) {
    var root = document.getElementById('pos-inv-settle-splits');
    if (!root) return;
    root.querySelectorAll('[data-se-listbox].is-open').forEach(function (box) {
      if (box !== except) closeSettleSplitListbox(box);
    });
  }

  function closeHotelRoomListbox() {
    var box = document.getElementById('pos-inv-settle-hotel-room-listbox');
    if (!box || !box.classList.contains('is-open')) return;
    box.classList.remove('is-open');
    var trigger = box.querySelector('.se-filter-chip-trigger');
    if (trigger) trigger.setAttribute('aria-expanded', 'false');
    var list = box.__epPortaledList || box.querySelector('.se-filter-listbox');
    if (list) {
      list.hidden = true;
      list.scrollTop = 0;
      if (list.__epPortalHome && list.__epPortalHome.isConnected) {
        list.__epPortalHome.appendChild(list);
      }
      list.classList.remove('ep-listbox-portaled');
      list.removeAttribute('data-ep-listbox-portaled');
    }
    var combo =
      box.querySelector('input.se-filter-chip-combobox, input.se-filter-chip-trigger');
    if (combo && combo.tagName === 'INPUT') {
      var hidden = document.getElementById('pos-inv-settle-hotel-room');
      var selected = box.querySelector(
        '.se-filter-listbox-option.is-selected, .se-filter-listbox-option[aria-selected="true"]'
      );
      var label = selected
        ? String(selected.getAttribute('data-label') || selected.textContent || '').trim()
        : '';
      combo.value = hidden && String(hidden.value || '').trim() ? label : '';
      combo.classList.toggle('is-placeholder', !(hidden && String(hidden.value || '').trim()));
    }
  }

  function openSettleSplitListbox(root) {
    if (!root || root.classList.contains('is-disabled')) return;
    closeAllSettleSplitListboxes(root);
    closeHotelRoomListbox();
    var trigger = root.querySelector('.se-filter-chip-trigger');
    var list = root.querySelector('.se-filter-listbox');
    root.classList.add('is-open');
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

  function syncSettleRowState(row) {
    if (!row) return;
    var txn = row.querySelector('.pos-inv-settle-txn');
    var method = settleRowMethodValue(row);
    var needsTxn = !!POS_METHODS_REQUIRING_TXN[method];
    row.classList.toggle('is-bank', needsTxn);
    if (txn) {
      txn.hidden = !needsTxn;
      if (!needsTxn) txn.value = '';
    }
  }

  function updateSettleRemoveButtons() {
    var rows = settleSplitRows();
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
      syncSettleRowState(row);
    });
  }

  function refreshSettleOptionAvailability() {
    settleSplitRows().forEach(function (row) {
      var listbox = row.querySelector('[data-se-listbox]');
      var list = row.querySelector('.se-filter-listbox');
      var selected = settleRowMethodValue(row);
      if (list) list.innerHTML = settleMethodOptionsHtml(selected, row);
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
      syncSettleRowState(row);
    });
    var addBtn = document.getElementById('pos-inv-settle-add-split');
    if (addBtn) addBtn.disabled = settleSplitRows().length >= POS_PAYMENT_METHODS.length;
  }

  function bindSettleSplitListbox(row) {
    var root = row && row.querySelector('[data-se-listbox]');
    if (!root || root.getAttribute('data-bound') === '1') return;
    root.setAttribute('data-bound', '1');
    var trigger = root.querySelector('.se-filter-chip-trigger');
    var list = root.querySelector('.se-filter-listbox');
    var hidden = root.querySelector('.pos-inv-settle-method-input');
    var valueEl = root.querySelector('.se-filter-chip-value');
    if (!trigger || !list || !hidden) return;

    trigger.addEventListener('click', function (e) {
      e.preventDefault();
      e.stopPropagation();
      if (root.classList.contains('is-open')) closeSettleSplitListbox(root);
      else openSettleSplitListbox(root);
    });
    trigger.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowDown' || e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        openSettleSplitListbox(root);
      } else if (e.key === 'Escape') {
        closeSettleSplitListbox(root);
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
      closeSettleSplitListbox(root);
      syncSettleRowState(row);
      refreshSettleOptionAvailability();
      refreshSettleBalance();
    });
  }

  function roundSettleMoney(value) {
    return Math.round((Number(value) || 0) * 100) / 100;
  }

  function syncRemainingSettleAmount(changedRow) {
    var rows = settleSplitRows();
    if (rows.length < 2) return;
    var target = settleBillTotal();
    if (!(target > 0)) return;

    function amountRaw(row) {
      var input = row.querySelector('.pos-inv-settle-amount');
      return input ? String(input.value || '').trim() : '';
    }
    function setAmount(row, value) {
      var input = row.querySelector('.pos-inv-settle-amount');
      if (!input) return;
      input.value = value > 0 ? String(value) : '';
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
          setAmount(second, roundSettleMoney(target - firstAmt));
        } else if (secondRaw && isFinite(secondAmt) && secondAmt > 0 && !firstRaw) {
          setAmount(first, roundSettleMoney(target - secondAmt));
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
      setAmount(otherRow, roundSettleMoney(target - amount));
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
    if (!hasEarlierAmount) {
      setAmount(lastRow, 0);
      return;
    }
    setAmount(lastRow, roundSettleMoney(target - others));
  }

  function allSettleModesSelected() {
    var rows = settleSplitRows();
    if (!rows.length) return false;
    for (var i = 0; i < rows.length; i++) {
      if (!settleRowMethodValue(rows[i])) return false;
    }
    return true;
  }

  function settleSplitsMatchTotal() {
    var rows = settleSplitRows();
    var target = settleBillTotal();
    if (!rows.length) return false;
    if (target <= 0) return allSettleModesSelected();
    if (!allSettleModesSelected()) return false;
    if (rows.length === 1) return true;
    var total = 0;
    var complete = true;
    rows.forEach(function (row) {
      var amountInput = row.querySelector('.pos-inv-settle-amount');
      var raw = amountInput ? String(amountInput.value || '').trim() : '';
      var amount = Number(raw);
      if (!raw || !isFinite(amount) || amount <= 0) complete = false;
      total += isFinite(amount) ? amount : 0;
    });
    return complete && Math.abs(total - target) <= 0.001;
  }

  function settleUsesRoomTransfer() {
    return settleSplitRows().some(function (row) {
      return settleRowMethodValue(row) === 'room_transfer';
    });
  }

  function selectedHotelRoomId() {
    var sel = document.getElementById('pos-inv-settle-hotel-room');
    return sel ? String(sel.value || '').trim() : '';
  }

  function hotelRoomOptionLabel(room) {
    var number = String((room && room.number) || '').trim() || (room && room.id) || '';
    var guest = String((room && room.guestName) || 'Guest').trim();
    return 'Room ' + number + ' — ' + guest;
  }

  function setHotelRoomSelection(roomId, label) {
    var id = String(roomId || '').trim();
    var display = id ? String(label || '').trim() : '';
    if (typeof window.resetEpListbox === 'function') {
      window.resetEpListbox('pos-inv-settle-hotel-room', id, display);
      return;
    }
    var hidden = document.getElementById('pos-inv-settle-hotel-room');
    var combo = document.getElementById('pos-inv-settle-hotel-room-trigger');
    if (hidden) hidden.value = id;
    if (combo && combo.tagName === 'INPUT') {
      combo.value = display;
      combo.classList.toggle('is-placeholder', !id);
    }
  }

  function fillOccupiedHotelRoomSelect(rooms) {
    var hidden = document.getElementById('pos-inv-settle-hotel-room');
    var optionsWrap = document.getElementById('pos-inv-settle-hotel-room-options');
    if (!optionsWrap) return;
    var prev = hidden ? String(hidden.value || '').trim() : '';
    var preferId = String(session.preferredHotelRoomId || '').trim();
    var preferNo = String(session.preferredHotelRoomNumber || '')
      .trim()
      .toLowerCase();
    if (!prev && preferId) prev = preferId;
    var html = '';
    var kept = '';
    var keptLabel = '';
    (rooms || []).forEach(function (room) {
      if (!room || !room.id) return;
      var label = hotelRoomOptionLabel(room);
      var roomNo = String(room.number || '').trim().toLowerCase();
      var on =
        String(room.id) === prev ||
        (!kept && preferNo && roomNo === preferNo);
      if (on) {
        kept = String(room.id);
        keptLabel = label;
      }
      html +=
        '<button type="button" class="se-filter-listbox-option' +
        (on ? ' is-selected' : '') +
        '" role="option" data-value="' +
        escapeHtml(room.id) +
        '" data-name="' +
        escapeHtml((label + ' ' + room.id).toLowerCase()) +
        '" data-label="' +
        escapeHtml(label) +
        '" aria-selected="' +
        (on ? 'true' : 'false') +
        '">' +
        escapeHtml(label) +
        '</button>';
    });
    optionsWrap.innerHTML = html;
    setHotelRoomSelection(kept, keptLabel);
  }

  function loadOccupiedHotelRooms(force) {
    if (!settleUsesRoomTransfer()) return;
    if (occupiedRoomsState.loading) return;
    if (occupiedRoomsState.loaded && !force) {
      fillOccupiedHotelRoomSelect(occupiedRoomsState.rooms);
      syncSettleSubmitEnabled();
      return;
    }
    occupiedRoomsState.loading = true;
    var url = session.apiBase + '/api/hotel-rooms/occupied';
    fetch(url, {
      method: 'GET',
      credentials: 'same-origin',
      headers: { Accept: 'application/json' }
    })
      .then(function (res) {
        return res
          .json()
          .catch(function () {
            return {};
          })
          .then(function (data) {
            return { ok: res.ok, data: data };
          });
      })
      .then(function (result) {
        var rooms =
          result.ok && result.data && result.data.ok && Array.isArray(result.data.rooms)
            ? result.data.rooms
            : [];
        occupiedRoomsState.rooms = rooms;
        occupiedRoomsState.loaded = true;
        fillOccupiedHotelRoomSelect(rooms);
        if (!rooms.length && settleUsesRoomTransfer()) {
          setSettleError('No occupied hotel rooms available for Room Transfer.');
        }
      })
      .catch(function () {
        occupiedRoomsState.rooms = [];
        occupiedRoomsState.loaded = false;
        fillOccupiedHotelRoomSelect([]);
        if (settleUsesRoomTransfer()) {
          setSettleError('Could not load occupied hotel rooms.');
        }
      })
      .then(function () {
        occupiedRoomsState.loading = false;
        syncSettleSubmitEnabled();
      });
  }

  function syncRoomTransferField() {
    var field = document.getElementById('pos-inv-settle-room-field');
    var needed = settleUsesRoomTransfer();
    if (field) field.hidden = !needed;
    if (!needed) {
      setHotelRoomSelection('', '');
      return;
    }
    loadOccupiedHotelRooms(false);
  }

  function syncSettleSubmitEnabled() {
    var submitBtn = document.getElementById('pos-inv-settle-submit');
    if (!submitBtn) return;
    var rows = settleSplitRows();
    var target = settleBillTotal();
    var ok = target <= 0 ? allSettleModesSelected() : settleSplitsMatchTotal();
    if (ok) {
      rows.forEach(function (row) {
        var method = settleRowMethodValue(row);
        var txnInput = row.querySelector('.pos-inv-settle-txn');
        if (POS_METHODS_REQUIRING_TXN[method] && !(txnInput && txnInput.value.trim())) {
          ok = false;
        }
      });
    }
    if (ok && settleUsesRoomTransfer() && !selectedHotelRoomId()) {
      ok = false;
    }
    rows.forEach(function (row) {
      var listbox = row.querySelector('.pos-inv-settle-method-listbox');
      if (listbox) {
        listbox.classList.toggle('is-incomplete', !settleRowMethodValue(row));
      }
    });
    var roomField = document.getElementById('pos-inv-settle-room-field');
    var roomListbox = document.getElementById('pos-inv-settle-hotel-room-listbox');
    var roomIncomplete = settleUsesRoomTransfer() && !selectedHotelRoomId();
    if (roomField) roomField.classList.toggle('is-incomplete', roomIncomplete);
    if (roomListbox) roomListbox.classList.toggle('is-incomplete', roomIncomplete);
    submitBtn.disabled = !ok;
  }

  function refreshSettleBalance() {
    var rows = settleSplitRows();
    var multi = rows.length > 1;
    var balanceEl = document.getElementById('pos-inv-settle-balance');
    var splitTotalEl = document.getElementById('pos-inv-settle-split-total');
    var splitTargetEl = document.getElementById('pos-inv-settle-split-target');
    if (balanceEl) balanceEl.hidden = !multi;
    var total = 0;
    var allFilled = true;
    var modesSelected = true;
    rows.forEach(function (row) {
      if (!settleRowMethodValue(row)) modesSelected = false;
      var amountInput = row.querySelector('.pos-inv-settle-amount');
      var raw = amountInput ? String(amountInput.value || '').trim() : '';
      var amount = Number(raw);
      if (multi && (!raw || !isFinite(amount) || amount <= 0)) allFilled = false;
      total += isFinite(amount) ? amount : 0;
    });
    var target = settleBillTotal();
    if (splitTotalEl) {
      splitTotalEl.setAttribute('data-amount', String(total));
      splitTotalEl.textContent = settleMoneyLabel(total);
    }
    if (splitTargetEl) {
      splitTargetEl.setAttribute('data-amount', String(target));
      splitTargetEl.textContent = settleMoneyLabel(target);
    }
    if (balanceEl) {
      var mismatch =
        multi && (!allFilled || !modesSelected || Math.abs(total - target) > 0.001);
      balanceEl.classList.toggle('is-mismatch', mismatch);
    }
    syncRoomTransferField();
    syncSettleSubmitEnabled();
  }

  function syncSingleSettleAmount() {
    var rows = settleSplitRows();
    if (rows.length !== 1) {
      syncRemainingSettleAmount(null);
      refreshSettleBalance();
      return;
    }
    var amountInput = rows[0].querySelector('.pos-inv-settle-amount');
    if (amountInput) amountInput.value = String(settleBillTotal() || '');
    refreshSettleBalance();
  }

  function addSettleSplitRow(preferredMethod, amount) {
    var root = document.getElementById('pos-inv-settle-splits');
    if (!root) return;
    if (settleSplitRows().length >= POS_PAYMENT_METHODS.length) return;
    var method = preferredMethod == null ? '' : String(preferredMethod || '');
    if (method && settleUsedMethods(null)[method]) method = '';
    var label = settleMethodLabel(method);
    var uid = 'pos-settle-split-' + Date.now() + '-' + Math.floor(Math.random() * 1000);
    var row = document.createElement('div');
    row.className = 'rt-split-row pos-inv-settle-split-row';
    row.innerHTML =
      '<div class="se-filter-chip se-filter-chip--payment se-filter-chip--listbox ep-form-listbox staff-expense-payment-listbox pos-inv-settle-method-listbox" data-se-listbox>' +
      '<div class="se-filter-chip-control">' +
      '<span class="se-filter-chip-icon" aria-hidden="true">' +
      '<svg viewBox="0 0 24 24" width="18" height="18"><rect x="2" y="5" width="20" height="14" rx="2"/><path d="M2 10h20"/></svg>' +
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
      '<svg viewBox="0 0 24 24" width="16" height="16"><polyline points="6 9 12 15 18 9"/></svg>' +
      '</span>' +
      '</div>' +
      '<div class="se-filter-listbox" id="' +
      uid +
      '-list" role="listbox" aria-label="Payment mode" hidden>' +
      settleMethodOptionsHtml(method, null) +
      '</div>' +
      '</div>' +
      '<input class="staff-input pos-inv-settle-amount rt-split-amount" type="number" min="0.01" step="0.01" placeholder="Amount" aria-label="Mode amount" value="' +
      escapeHtml(amount == null ? '' : amount) +
      '">' +
      '<input class="staff-input pos-inv-settle-txn rt-split-txn" type="text" placeholder="Txn / UTR ID" aria-label="Transaction ID" hidden autocomplete="off">' +
      '<button type="button" class="pos-inv-settle-remove rt-split-remove" aria-label="Remove payment mode" hidden>&times;</button>';
    root.appendChild(row);

    var amountInput = row.querySelector('.pos-inv-settle-amount');
    var txnInput = row.querySelector('.pos-inv-settle-txn');
    var removeBtn = row.querySelector('.pos-inv-settle-remove');
    bindSettleSplitListbox(row);
    if (amountInput) {
      amountInput.addEventListener('input', function () {
        syncRemainingSettleAmount(row);
        refreshSettleBalance();
      });
    }
    if (txnInput) txnInput.addEventListener('input', syncSettleSubmitEnabled);
    if (removeBtn) {
      removeBtn.addEventListener('click', function () {
        if (settleSplitRows().length <= 1) return;
        closeAllSettleSplitListboxes();
        row.remove();
        updateSettleRemoveButtons();
        refreshSettleOptionAvailability();
        syncSingleSettleAmount();
      });
    }
    syncSettleRowState(row);
    updateSettleRemoveButtons();
    refreshSettleOptionAvailability();
    refreshSettleBalance();
  }

  function resetSettleSplits() {
    closeAllSettleSplitListboxes();
    closeHotelRoomListbox();
    var root = document.getElementById('pos-inv-settle-splits');
    if (root) root.innerHTML = '';
    addSettleSplitRow('', '');
    syncSingleSettleAmount();
    syncRoomTransferField();
  }

  function applySettleSplits(splits) {
    closeAllSettleSplitListboxes();
    closeHotelRoomListbox();
    var root = document.getElementById('pos-inv-settle-splits');
    if (root) root.innerHTML = '';
    var list = [];
    (Array.isArray(splits) ? splits : []).forEach(function (raw) {
      if (!raw) return;
      var method = String(
        raw.payment_method || raw.paymentMethod || raw.method || ''
      )
        .trim()
        .toLowerCase();
      var amount = Math.round((Number(raw.amount) || 0) * 100) / 100;
      if (!method) return;
      if (amount <= 0.009 && settleBillTotal() > 0.009) return;
      list.push({
        payment_method: method,
        amount: amount,
        transaction_id: String(
          raw.transaction_id || raw.transactionId || ''
        ).trim()
      });
    });
    if (!list.length) {
      addSettleSplitRow('', '');
      syncSingleSettleAmount();
      syncRoomTransferField();
      return;
    }
    list.forEach(function (split) {
      addSettleSplitRow(
        split.payment_method,
        list.length === 1 ? '' : String(split.amount)
      );
    });
    if (list.length === 1) {
      syncSingleSettleAmount();
    } else {
      updateSettleRemoveButtons();
      refreshSettleBalance();
    }
    var rows = settleSplitRows();
    list.forEach(function (split, idx) {
      var row = rows[idx];
      if (!row) return;
      var txn = row.querySelector('.pos-inv-settle-txn');
      if (txn && split.transaction_id) {
        txn.value = split.transaction_id;
      }
      syncSettleRowState(row);
    });
    syncRoomTransferField();
    syncSettleSubmitEnabled();
  }

  function collectSettleSplits() {
    var splits = [];
    var invalid = '';
    var rows = settleSplitRows();
    var target = settleBillTotal();
    rows.forEach(function (row) {
      if (invalid) return;
      var amountInput = row.querySelector('.pos-inv-settle-amount');
      var txnInput = row.querySelector('.pos-inv-settle-txn');
      var method = settleRowMethodValue(row);
      var amount = rows.length === 1 ? target : Number(amountInput && amountInput.value);
      var transactionId = txnInput ? txnInput.value.trim() : '';
      if (!method) {
        invalid = 'Select a payment mode for each row.';
        return;
      }
      if (target > 0 && (!amount || amount <= 0)) {
        invalid = 'Enter a valid amount for each payment mode.';
        return;
      }
      if (POS_METHODS_REQUIRING_TXN[method] && !transactionId) {
        invalid = 'Transaction ID is required for bank transfer.';
        return;
      }
      splits.push({
        payment_method: method,
        amount: amount || 0,
        transaction_id: transactionId
      });
    });
    if (invalid) return { splits: [], error: invalid };
    var splitSum = splits.reduce(function (sum, item) {
      return sum + Number(item.amount || 0);
    }, 0);
    if (Math.abs(splitSum - target) > 0.001) {
      return {
        splits: [],
        error: 'Modes total must equal the bill total before settling.'
      };
    }
    return { splits: splits, error: '' };
  }

  function todayIsoLocal() {
    var d = new Date();
    var y = d.getFullYear();
    var m = d.getMonth() + 1;
    var day = d.getDate();
    return (
      y +
      '-' +
      (m < 10 ? '0' : '') +
      m +
      '-' +
      (day < 10 ? '0' : '') +
      day
    );
  }

  function paintSettleAllocBody() {
    var metaEl = document.getElementById('pos-inv-settle-alloc-meta');
    var allocBody = document.getElementById('pos-inv-settle-alloc-body');
    var items = session.items || [];
    if (items.length > 1) {
      if (metaEl) metaEl.textContent = items.length + ' invoices';
      if (allocBody) {
        allocBody.innerHTML = items
          .map(function (item) {
            var orderNo = item.orderNo || '—';
            var sub = item.tableLabel || item.customerName || '';
            var total = Math.round((Number(item.grandTotal) || 0) * 100) / 100;
            return (
              '<tr>' +
              '<td><div class="cp-alloc-order"><span class="cp-alloc-code">' +
              escapeHtml(orderNo) +
              '</span>' +
              (sub
                ? '<span class="cp-alloc-supplier">' + escapeHtml(sub) + '</span>'
                : '') +
              '</div></td>' +
              '<td class="pl-col-amount"><span class="cp-alloc-total-value">' +
              escapeHtml(settleMoneyLabel(total)) +
              '</span></td>' +
              '<td class="pl-col-amount"><input class="cp-alloc-input" type="number" value="' +
              escapeHtml(String(total)) +
              '" disabled aria-label="Pay now amount"></td>' +
              '</tr>'
            );
          })
          .join('');
      }
      return;
    }
    var orderNo = session.orderNo;
    var table = session.tableLabel;
    var total = settleBillTotal();
    if (metaEl) metaEl.textContent = orderNo;
    if (allocBody) {
      allocBody.innerHTML =
        '<tr>' +
        '<td><div class="cp-alloc-order"><span class="cp-alloc-code">' +
        escapeHtml(orderNo) +
        '</span>' +
        (table
          ? '<span class="cp-alloc-supplier">' + escapeHtml(table) + '</span>'
          : '') +
        '</div></td>' +
        '<td class="pl-col-amount"><span class="cp-alloc-total-value">' +
        escapeHtml(settleMoneyLabel(total)) +
        '</span></td>' +
        '<td class="pl-col-amount"><input class="cp-alloc-input" type="number" value="' +
        escapeHtml(total) +
        '" disabled aria-label="Pay now amount"></td>' +
        '</tr>';
    }
  }

  function closePosSettleModal() {
    var modal = document.getElementById('pos-inv-settle-modal');
    if (!modal || modal.hidden) return;
    closeAllSettleSplitListboxes();
    closeHotelRoomListbox();
    modal.hidden = true;
    modal.setAttribute('hidden', '');
    setSettleError('');
    var onClose = session.onClose;
    session.invoiceId = null;
    session.items = [];
    session.settleSelectedUrl = '';
    session.onSettled = null;
    session.onClose = null;
    session.preferredHotelRoomId = '';
    session.preferredHotelRoomNumber = '';
    session.editingSettlement = false;
    var titleEl = document.getElementById('pos-inv-settle-title');
    if (titleEl) titleEl.textContent = 'Payment Details';
    var submitBtn = document.getElementById('pos-inv-settle-submit');
    if (submitBtn) submitBtn.textContent = 'Record Payment';
    if (typeof onClose === 'function') {
      try {
        onClose();
      } catch (e) {}
    }
  }

  function openPosSettleModal(opts) {
    opts = opts || {};
    if (!isBrowserOnline()) {
      toast('Settle Bill requires an internet connection.');
      return false;
    }
    var items = Array.isArray(opts.items)
      ? opts.items.filter(function (item) {
          return item && (item.invoiceId || item.invoice_id);
        })
      : [];
    items = items.map(function (item) {
      return {
        invoiceId: item.invoiceId || item.invoice_id,
        orderNo: item.orderNo || item.order_no || '—',
        tableLabel: item.tableLabel || item.table || '',
        customerName: item.customerName || item.customer_name || '',
        grandTotal: Math.round((Number(item.grandTotal != null ? item.grandTotal : item.grand_total) || 0) * 100) / 100
      };
    });
    var invoiceId =
      opts.invoiceId || (items.length === 1 ? items[0].invoiceId : null);
    if (!invoiceId && items.length < 2) {
      toast('Save the order before settling the bill.');
      return false;
    }
    var modal = document.getElementById('pos-inv-settle-modal');
    if (!modal) {
      toast('Settle dialog is not available on this page.');
      return false;
    }

    session.items = items;
    session.settleSelectedUrl = opts.settleSelectedUrl || opts.settle_selected_url || '';
    session.invoiceId = invoiceId;
    if (items.length > 1) {
      session.orderNo = items.length + ' invoices';
      session.tableLabel = '';
      session.grandTotal = items.reduce(function (sum, item) {
        return sum + (Number(item.grandTotal) || 0);
      }, 0);
      session.grandTotal = Math.round(session.grandTotal * 100) / 100;
    } else {
      var first = items[0] || null;
      session.orderNo = opts.orderNo || (first && first.orderNo) || '—';
      session.tableLabel =
        opts.tableLabel || opts.table || (first && first.tableLabel) || '';
      session.grandTotal = Math.round(
        (Number(
          opts.grandTotal != null
            ? opts.grandTotal
            : first
              ? first.grandTotal
              : 0
        ) || 0) * 100
      ) / 100;
    }
    session.apiBase = resolveApiBase(opts.apiBase);
    session.onSettled = typeof opts.onSettled === 'function' ? opts.onSettled : null;
    session.onClose = typeof opts.onClose === 'function' ? opts.onClose : null;
    session.preferredHotelRoomId = String(
      opts.hotelRoomId || opts.hotel_room_id || ''
    ).trim();
    session.preferredHotelRoomNumber = String(
      opts.hotelRoomNumber || opts.hotel_room_number || ''
    ).trim();
    session.editingSettlement = !!(
      opts.editingSettlement ||
      opts.editSettlement ||
      opts.resettle
    );

    setSettleError('');
    var total = settleBillTotal();
    var totalEl = document.getElementById('pos-inv-settle-total');
    if (totalEl) {
      totalEl.setAttribute('data-amount', String(total));
      totalEl.textContent = settleMoneyLabel(total);
    }
    paintSettleAllocBody();
    var titleEl = document.getElementById('pos-inv-settle-title');
    if (titleEl) {
      titleEl.textContent = session.editingSettlement
        ? 'Edit Payment Details'
        : 'Payment Details';
    }
    var submitBtn = document.getElementById('pos-inv-settle-submit');
    if (submitBtn) {
      submitBtn.textContent = session.editingSettlement
        ? 'Update Payment'
        : 'Record Payment';
    }
    var notesEl = document.getElementById('pos-inv-settle-notes');
    if (notesEl) {
      notesEl.value = String(opts.notes || opts.payment_notes || '').trim();
    }
    occupiedRoomsState.loading = false;
    occupiedRoomsState.loaded = false;
    occupiedRoomsState.rooms = [];
    fillOccupiedHotelRoomSelect([]);
    var presetSplits =
      opts.paymentSplits ||
      opts.payment_splits ||
      opts.payments ||
      null;
    if (presetSplits && presetSplits.length) {
      applySettleSplits(presetSplits);
    } else {
      resetSettleSplits();
    }
    modal.hidden = false;
    modal.removeAttribute('hidden');
    var firstTrigger = modal.querySelector(
      '.pos-inv-settle-method-listbox .se-filter-chip-trigger'
    );
    if (firstTrigger) firstTrigger.focus();
    return true;
  }

  function submitPosSettle() {
    if (!isBrowserOnline()) {
      setSettleError('Settle Bill requires an internet connection.');
      syncSettleSubmitEnabled();
      return;
    }
    if (!session.invoiceId && !(session.items && session.items.length)) return;
    var isMulti = !!(session.items && session.items.length > 1);
    var collected = collectSettleSplits();
    if (collected.error) {
      setSettleError(collected.error);
      syncSettleSubmitEnabled();
      return;
    }
    var hotelRoomId = '';
    if (settleUsesRoomTransfer()) {
      hotelRoomId = selectedHotelRoomId();
      if (!hotelRoomId) {
        setSettleError('Select a hotel room for Room Transfer payment.');
        syncSettleSubmitEnabled();
        return;
      }
    }
    var notesEl = document.getElementById('pos-inv-settle-notes');
    var submitBtn = document.getElementById('pos-inv-settle-submit');
    if (submitBtn) submitBtn.disabled = true;
    setSettleError('');

    var payload = {
      payment_date: todayIsoLocal(),
      notes: notesEl ? notesEl.value.trim() : '',
      payment_splits: collected.splits
    };
    if (hotelRoomId) {
      payload.hotel_room_id = hotelRoomId;
      payload.hotelRoomId = hotelRoomId;
    }
    var url;
    if (isMulti) {
      payload.invoice_ids = session.items.map(function (item) {
        return item.invoiceId;
      });
      url =
        session.settleSelectedUrl ||
        session.apiBase + '/api/invoices/settle-selected';
    } else {
      var invoiceId =
        session.invoiceId ||
        (session.items[0] && session.items[0].invoiceId);
      if (!invoiceId) return;
      url =
        session.apiBase +
        '/api/invoices/' +
        encodeURIComponent(invoiceId) +
        '/settle';
    }

    fetch(url, {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(payload)
    })
      .then(function (res) {
        return res
          .json()
          .catch(function () {
            return {};
          })
          .then(function (data) {
            return { ok: res.ok, data: data };
          });
      })
      .then(function (result) {
        if (!result.ok || !result.data.ok) {
          setSettleError(
            (result.data && result.data.error) || 'Could not settle the bill.'
          );
          return;
        }
        var settledInvoice =
          result.data && result.data.invoice ? result.data.invoice : null;
        var onSettled = session.onSettled;
        var table = session.tableLabel;
        var paidCount =
          (result.data && result.data.paid_count) ||
          (isMulti && session.items ? session.items.length : 1);
        closePosSettleModal();
        if (typeof onSettled === 'function') {
          try {
            onSettled(settledInvoice, {
              tableLabel: table,
              paidCount: paidCount,
              invoices: (result.data && result.data.invoices) || []
            });
          } catch (e) {}
        } else if (isMulti) {
          toast(
            paidCount === 1
              ? 'Bill settled successfully.'
              : paidCount + ' bills settled successfully.'
          );
        } else {
          toast(
            table
              ? 'Bill settled. ' + table + ' is now available.'
              : 'Bill settled successfully.'
          );
        }
      })
      .catch(function () {
        setSettleError('Could not settle the bill. Check your connection and try again.');
      })
      .then(function () {
        if (submitBtn) syncSettleSubmitEnabled();
      });
  }

  function bindPosSettleModal() {
    var modal = document.getElementById('pos-inv-settle-modal');
    if (!modal || modal.getAttribute('data-pos-settle-bound') === '1') return;
    modal.setAttribute('data-pos-settle-bound', '1');

    modal.addEventListener('click', function (event) {
      if (event.target.closest('[data-settle-close]')) {
        closePosSettleModal();
        return;
      }
      if (!event.target.closest('[data-se-listbox]')) {
        closeAllSettleSplitListboxes();
        closeHotelRoomListbox();
      }
      if (event.target.closest('#pos-inv-settle-add-split')) {
        event.preventDefault();
        if (settleSplitRows().length >= POS_PAYMENT_METHODS.length) return;
        addSettleSplitRow('', '');
        syncRemainingSettleAmount(null);
        updateSettleRemoveButtons();
        refreshSettleBalance();
        return;
      }
      if (event.target.closest('#pos-inv-settle-submit')) {
        event.preventDefault();
        submitPosSettle();
      }
    });

    if (!document.__posSettleEscBound) {
      document.__posSettleEscBound = true;
      document.addEventListener('keydown', function (event) {
        if (event.key !== 'Escape') return;
        var open = document.getElementById('pos-inv-settle-modal');
        if (!open || open.hidden) return;
        var openList = open.querySelector('[data-se-listbox].is-open');
        if (openList) {
          if (openList.id === 'pos-inv-settle-hotel-room-listbox') return;
          closeSettleSplitListbox(openList);
          return;
        }
        var roomBox = document.getElementById('pos-inv-settle-hotel-room-listbox');
        if (roomBox && roomBox.contains(event.target)) return;
        closePosSettleModal();
      });
    }
  }

  global.openPosSettleModal = openPosSettleModal;
  global.closePosSettleModal = closePosSettleModal;
  global.bindPosSettleModal = bindPosSettleModal;
  global.submitPosSettle = submitPosSettle;
  global.onPosSettleHotelRoomChanged = function () {
    setSettleError('');
    syncSettleSubmitEnabled();
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bindPosSettleModal);
  } else {
    bindPosSettleModal();
  }
})(typeof window !== 'undefined' ? window : this);
