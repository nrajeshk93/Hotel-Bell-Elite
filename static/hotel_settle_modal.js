/**
 * Hotel Payment Details settle modal — shared by Invoice Ledger (and openable elsewhere).
 * Soft-nav safe: window.bindHotelSettleModal / window.openHotelSettleModal.
 */
(function (global) {
  'use strict';

  var METHODS_REQUIRING_TXN = { bank_transfer: true };
  var DEFAULT_METHODS = [
    { value: 'cash', label: 'Cash' },
    { value: 'upi', label: 'UPI' },
    { value: 'card', label: 'Card' },
    { value: 'bank_transfer', label: 'Bank Transfer' },
    { value: 'credit', label: 'Credit' }
  ];
  var PAY_METHODS = DEFAULT_METHODS.slice();
  var settleCtx = null;
  var bound = false;

  function money(value) {
    var n = Number(value || 0);
    if (!isFinite(n)) n = 0;
    if (typeof global.formatInr === 'function') return global.formatInr(n, 2);
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

  function loadPayMethods(allowCredit) {
    PAY_METHODS = DEFAULT_METHODS.slice();
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
    if (!allowCredit) {
      PAY_METHODS = PAY_METHODS.filter(function (m) {
        return m.value !== 'credit';
      });
    }
  }

  function settleModal() {
    return document.getElementById('pos-inv-settle-modal');
  }

  function mountSettleModal(modal) {
    if (!modal) return null;
    var host = document.getElementById('de-fs-app') || document.body;
    if (!host) return modal;
    Array.prototype.slice
      .call(host.querySelectorAll('#pos-inv-settle-modal'))
      .forEach(function (el) {
        if (el !== modal) el.parentNode && el.parentNode.removeChild(el);
      });
    if (modal.parentNode !== host) host.appendChild(modal);
    return modal;
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

  function billTarget() {
    return settleCtx ? Number(settleCtx.balance || 0) : 0;
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
    var uid = 'hil-settle-split-' + Date.now() + '-' + Math.floor(Math.random() * 1000);
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
    var items = settleCtx && settleCtx.items;
    if (items && items.length > 1) {
      if (meta) meta.textContent = items.length + ' invoices';
      if (body) {
        body.innerHTML = items
          .map(function (item) {
            var roomNo = item.roomLabel || '—';
            var inv = item.invoiceNumber || '';
            var label = 'Room ' + roomNo;
            if (inv) label += ' · ' + inv;
            var balance = Number(item.balance || 0);
            return (
              '<tr>' +
              '<td>' +
              escapeHtml(label) +
              '</td>' +
              '<td class="pl-col-amount">' +
              escapeHtml(money(balance)) +
              '</td>' +
              '<td class="pl-col-amount">' +
              escapeHtml(money(balance)) +
              '</td>' +
              '</tr>'
            );
          })
          .join('');
      }
      return;
    }
    var room = settleCtx && settleCtx.room;
    var roomNo =
      (items && items[0] && items[0].roomLabel) ||
      (room && (room.numberDisplay || room.mergeRoomLabel || room.number)) ||
      '—';
    var inv =
      (items && items[0] && items[0].invoiceNumber) ||
      (settleCtx && settleCtx.invoiceNumber) ||
      (room && room.stay && (room.stay.invoiceNumber || room.stay.invoice_number)) ||
      '';
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

  function closeHotelSettleModal() {
    var modal = settleModal();
    if (modal) {
      modal.hidden = true;
      modal.setAttribute('hidden', '');
    }
    closeAllMethodListboxes();
    setSettleError('');
    settleCtx = null;
  }

  function openHotelSettleModal(opts) {
    opts = opts || {};
    var modal = mountSettleModal(settleModal());
    if (!modal) return false;
    var items = Array.isArray(opts.items)
      ? opts.items.filter(function (item) {
          return item && Number(item.balance || 0) > 0.009;
        })
      : [];
    var room = opts.room || null;
    var stay = room && room.stay ? room.stay : null;
    var balance = Number(
      opts.balance != null
        ? opts.balance
        : items.length
          ? items.reduce(function (sum, item) {
              return sum + Number(item.balance || 0);
            }, 0)
          : stay && stay.balanceAmount != null
            ? stay.balanceAmount
            : 0
    );
    if (items.length) {
      balance = items.reduce(function (sum, item) {
        return sum + Number(item.balance || 0);
      }, 0);
    }
    if (!(balance > 0.009)) {
      if (typeof opts.onError === 'function') opts.onError('Invoice is already settled.');
      return false;
    }
    var agency =
      stay &&
      String(stay.agencyName || stay.agency_name || '').trim();
    var allowCredit =
      opts.allowCredit != null
        ? !!opts.allowCredit
        : items.length
          ? items.every(function (item) {
              return !!item.allowCredit;
            })
          : !!agency;
    loadPayMethods(allowCredit);
    var first = items[0] || null;
    var settleUrl = opts.settleUrl || (first && first.settleUrl) || '';
    if (items.length > 1) {
      settleUrl = opts.settleSelectedUrl || settleUrl;
    }
    settleCtx = {
      room: room,
      balance: round2(balance),
      invoiceNumber:
        opts.invoiceNumber || (first && first.invoiceNumber) || '',
      settleUrl: settleUrl,
      items: items,
      onSuccess: opts.onSuccess || null,
      onError: opts.onError || null
    };
    setSettleError('');
    var notes = document.getElementById('pos-inv-settle-notes');
    if (notes) notes.value = '';
    paintAllocBody();
    resetSplits();
    bindAddSplitButton();
    modal.hidden = false;
    modal.removeAttribute('hidden');
    return true;
  }

  function handleAddSplitClick(ev) {
    if (ev) ev.preventDefault();
    if (!settleCtx) return;
    var modal = settleModal();
    if (!modal || modal.hidden) return;
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
  }

  function bindAddSplitButton() {
    var addBtn = document.getElementById('pos-inv-settle-add-split');
    if (!addBtn || addBtn.getAttribute('data-hil-add-split-bound') === '1') return;
    addBtn.setAttribute('data-hil-add-split-bound', '1');
    addBtn.addEventListener('click', handleAddSplitClick);
  }

  function submitSettle() {
    if (!settleCtx || !settleCtx.settleUrl) {
      setSettleError('Settle endpoint is unavailable.');
      return;
    }
    if (!splitsMatchTarget()) {
      setSettleError('Modes total must match the balance due.');
      syncSettleSubmitEnabled();
      return;
    }
    var collected = collectSplits();
    if (collected.error) {
      setSettleError(collected.error);
      return;
    }
    var note = (
      (document.getElementById('pos-inv-settle-notes') || {}).value || ''
    ).trim();
    var saveBtn = document.getElementById('pos-inv-settle-submit');
    if (saveBtn) saveBtn.disabled = true;
    setSettleError('');
    var payload = {
      payment_splits: collected.splits,
      note: note
    };
    if (settleCtx.items && settleCtx.items.length > 1) {
      payload.invoice_numbers = settleCtx.items.map(function (item) {
        return item.invoiceNumber;
      });
    }
    fetch(settleCtx.settleUrl, {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
        'X-Requested-With': 'XMLHttpRequest'
      },
      body: JSON.stringify(payload)
    })
      .then(function (resp) {
        return resp.json().then(function (data) {
          return { ok: resp.ok, data: data || {} };
        });
      })
      .then(function (result) {
        if (!result.ok || !result.data.ok) {
          throw new Error(
            (result.data && result.data.error) || 'Could not record payment.'
          );
        }
        var cb = settleCtx && settleCtx.onSuccess;
        closeHotelSettleModal();
        if (typeof cb === 'function') cb(result.data);
      })
      .catch(function (err) {
        setSettleError(err.message || 'Could not record payment.');
        if (settleCtx && typeof settleCtx.onError === 'function') {
          settleCtx.onError(err.message || 'Could not record payment.');
        }
      })
      .finally(function () {
        syncSettleSubmitEnabled();
      });
  }

  function bindHotelSettleModal() {
    if (document.__hotelSettleDocClick) {
      document.removeEventListener('click', document.__hotelSettleDocClick, true);
      document.removeEventListener('click', document.__hotelSettleDocClick);
    }
    if (document.__hotelSettleDocKey) {
      document.removeEventListener('keydown', document.__hotelSettleDocKey);
    }
    document.__hotelSettleDocClick = function (ev) {
      var modal = settleModal();
      if (!modal || modal.hidden) return;
      var closeEl =
        ev.target && ev.target.closest
          ? ev.target.closest(
              '[data-hotel-settle-close], [data-hri-settle-close], [data-settle-close]'
            )
          : null;
      if (closeEl && modal.contains(closeEl)) {
        ev.preventDefault();
        ev.stopPropagation();
        closeHotelSettleModal();
        return;
      }
      /* Submit / listboxes only when this script opened the dialog. */
      if (!settleCtx) return;
      if (
        ev.target.closest &&
        ev.target.closest('#pos-inv-settle-submit') &&
        modal.contains(ev.target)
      ) {
        ev.preventDefault();
        submitSettle();
        return;
      }
      if (!modal.contains(ev.target)) {
        closeAllMethodListboxes();
        return;
      }
      if (!ev.target.closest('#pos-inv-settle-splits [data-se-listbox]')) {
        closeAllMethodListboxes();
      }
    };
    document.__hotelSettleDocKey = function (ev) {
      if (ev.key !== 'Escape') return;
      var modal = settleModal();
      if (!modal || modal.hidden) return;
      closeHotelSettleModal();
    };
    document.addEventListener('click', document.__hotelSettleDocClick);
    document.addEventListener('keydown', document.__hotelSettleDocKey);
    document.documentElement.setAttribute('data-hotel-settle-doc-bound', '1');
    bound = true;
    bindAddSplitButton();
  }

  global.bindHotelSettleModal = bindHotelSettleModal;
  global.openHotelSettleModal = openHotelSettleModal;
  global.closeHotelSettleModal = closeHotelSettleModal;
})(window);
