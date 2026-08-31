(function () {
  'use strict';

  var page = document.getElementById('back-office-receipt-page');
  if (!page) return;

  var addUrl = page.getAttribute('data-add-url') || '';
  var editUrl = page.getAttribute('data-edit-url') || '';
  var deleteUrl = page.getAttribute('data-delete-url') || '';
  var agencies = [];
  try {
    var raw = document.getElementById('bor-agencies-json');
    if (raw && raw.textContent) agencies = JSON.parse(raw.textContent) || [];
  } catch (e) {
    agencies = [];
  }

  function formatAmounts() {
    function formatInr(amount) {
      if (typeof window.formatInr === 'function') return window.formatInr(amount, 0);
      var n = Number(amount || 0);
      if (!isFinite(n)) return '₹0';
      return '₹' + Math.abs(n).toLocaleString('en-IN', { maximumFractionDigits: 0 });
    }
    page.querySelectorAll('.pl-amount[data-amount], .pl-summary-value[data-amount]').forEach(function (el) {
      el.textContent = formatInr(el.getAttribute('data-amount'));
    });
  }

  function initDateRange() {
    var form = document.getElementById('bor-filter-form');
    if (!form || !window.SalesDateRangePicker) return;
    var dateFromInput = document.getElementById('bor-date-from');
    var dateToInput = document.getElementById('bor-date-to');
    var clearUrl = String(form.getAttribute('data-clear-url') || form.action || '');
    SalesDateRangePicker.init({
      wrapId: 'bor-date-range-wrap',
      triggerId: 'bor-date-range-trigger',
      backdropId: 'bor-date-range-backdrop',
      panelId: 'bor-date-range-panel',
      displayId: 'bor-date-range-display',
      fromInputId: 'bor-date-from',
      toInputId: 'bor-date-to',
      formId: 'bor-filter-form',
      applyId: 'bor-date-range-apply',
      prevId: 'bor-cal-prev',
      nextId: 'bor-cal-next',
      title0Id: 'bor-cal-title0',
      title1Id: 'bor-cal-title1',
      grid0Id: 'bor-cal-grid0',
      grid1Id: 'bor-cal-grid1',
      emptyLabel: 'Date',
      onBeforeSubmit: function () {
        if (dateFromInput && !dateFromInput.value) dateFromInput.removeAttribute('name');
        if (dateToInput && !dateToInput.value) dateToInput.removeAttribute('name');
      }
    });
    var clearBtn = document.getElementById('bor-date-range-clear');
    if (clearBtn && clearBtn.getAttribute('data-bor-clear-bound') !== '1') {
      clearBtn.setAttribute('data-bor-clear-bound', '1');
      clearBtn.addEventListener('click', function () {
        if (clearUrl) window.location.href = clearUrl;
      });
    }
  }

  function initClientSearch() {
    var input = document.getElementById('bor-search');
    var table = document.getElementById('bor-ledger-table');
    var countEl = document.getElementById('bor-entry-count');
    var searchChip = input ? input.closest('.bor-search-chip') : null;
    if (!input || !table || input.getAttribute('data-bor-search-bound') === '1') return;
    input.setAttribute('data-bor-search-bound', '1');

    function rowHaystack(row) {
      return String(row.getAttribute('data-search') || row.textContent || '')
        .toLowerCase()
        .replace(/\s+/g, ' ')
        .trim();
    }

    function tokensMatch(hay, needle) {
      if (!needle) return true;
      var parts = needle.split(/\s+/).filter(Boolean);
      if (!parts.length) return true;
      for (var i = 0; i < parts.length; i += 1) {
        if (hay.indexOf(parts[i]) === -1) return false;
      }
      return true;
    }

    function apply() {
      var q = String(input.value || '').trim();
      if (searchChip) searchChip.classList.toggle('is-active', !!q);
      var rows = Array.prototype.slice.call(
        table.querySelectorAll('tbody tr.bor-ledger-row')
      );
      var shown = 0;
      var tbody = table.tBodies[0];
      if (!q) {
        rows.forEach(function (row) { row.hidden = false; shown += 1; });
      } else {
        var ranked = rows.map(function (row) {
          return { row: row, score: window.hbeBestSearchScore([row.getAttribute('data-search') || row.textContent || ''], q) };
        }).sort(function (a, b) { return b.score - a.score; });
        ranked.forEach(function (entry) {
          var ok = entry.score >= 0;
          entry.row.hidden = !ok;
          if (ok) {
            shown += 1;
            if (tbody) tbody.appendChild(entry.row);
          }
        });
      }
      if (countEl) {
        countEl.textContent = shown + ' entr' + (shown === 1 ? 'y' : 'ies');
      }
    }

    input.addEventListener('input', apply);
    input.addEventListener('search', apply);
    input.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') {
        input.value = '';
        apply();
        input.blur();
      }
      // Keep filtering client-side; do not soft-nav/submit the filter form.
      if (e.key === 'Enter') e.preventDefault();
    });
    apply();
  }

  var modal = document.getElementById('bor-add-modal');
  var errEl = document.getElementById('bor-add-error');
  var amountEl = document.getElementById('bor-amount');
  var modeInput = document.getElementById('bor-payment');
  var instrumentFields = document.getElementById('bor-instrument-fields');
  var submitBtn = document.getElementById('bor-add-submit');
  var submitLabel = document.getElementById('bor-add-submit-label');
  var titleEl = document.getElementById('bor-add-title');
  var noticeEl = document.getElementById('bor-required-notice');
  var editIdEl = document.getElementById('bor-edit-id');
  var agencyIdInput = document.getElementById('bor-agency');
  var agencyTrigger = document.getElementById('bor-agency-trigger');
  var dateEl = document.getElementById('bor-receipt-date');
  var instrumentNoEl = document.getElementById('bor-instrument-no');
  var instrumentDateEl = document.getElementById('bor-instrument-date');
  var towardsEl = document.getElementById('bor-towards');
  var todayIso = page.getAttribute('data-today') || '';
  var editingId = '';

  function setError(msg) {
    if (!errEl) return;
    errEl.textContent = msg || '';
    errEl.style.display = msg ? 'block' : 'none';
  }

  function setModalMode(isEdit) {
    if (titleEl) titleEl.textContent = isEdit ? 'Edit receipt' : 'Add receipt';
    if (submitLabel) submitLabel.textContent = 'Save';
    if (noticeEl) {
      noticeEl.textContent = isEdit
        ? 'Fill all the mandatory fields to save changes'
        : 'Fill all the mandatory fields to save a receipt';
    }
  }

  function payerName() {
    var agencyId = agencyIdInput ? String(agencyIdInput.value || '').trim() : '';
    if (agencyId) {
      for (var i = 0; i < agencies.length; i += 1) {
        if (String(agencies[i].id) === agencyId) {
          return String(agencies[i].name || '').trim();
        }
      }
    }
    return ((agencyTrigger && agencyTrigger.value) || '').trim();
  }

  function syncInstrumentVisibility() {
    var mode = (modeInput && modeInput.value) || 'cash';
    if (instrumentFields) instrumentFields.hidden = mode === 'cash';
  }

  function canSave() {
    var receiptDate = dateEl ? String(dateEl.value || '').trim() : '';
    var amount = Number(amountEl && amountEl.value);
    var mode = (modeInput && modeInput.value) || 'cash';
    var instrumentNo = instrumentNoEl ? String(instrumentNoEl.value || '').trim() : '';
    if (!receiptDate) return false;
    if (!payerName()) return false;
    if (!(amount > 0)) return false;
    if (!mode) return false;
    if (mode !== 'cash' && !instrumentNo) return false;
    return true;
  }

  function syncSaveUi() {
    var ok = canSave();
    var saving = !!(submitBtn && submitBtn.getAttribute('data-bor-saving') === '1');
    var showButton = saving || ok;
    if (noticeEl) {
      noticeEl.hidden = showButton;
      noticeEl.setAttribute('aria-hidden', showButton ? 'true' : 'false');
    }
    if (!submitBtn) return;
    submitBtn.hidden = !showButton;
    submitBtn.setAttribute('aria-hidden', showButton ? 'false' : 'true');
    submitBtn.disabled = saving ? true : !ok;
  }

  window.borAddFieldChanged = function () {
    syncSaveUi();
  };

  window.borPaymentChanged = function () {
    syncInstrumentVisibility();
    syncSaveUi();
  };

  function resetHotelDate(fieldId, iso) {
    if (typeof window.setHotelDateValue === 'function') {
      window.setHotelDateValue(fieldId, iso || '');
      return;
    }
    var input = document.getElementById(fieldId);
    if (input) input.value = iso || '';
  }

  function setAgencyField(agencyId, payerLabel) {
    var id = String(agencyId || '').trim();
    var label = String(payerLabel || '').trim();
    if (typeof window.resetEpListbox === 'function') {
      if (id) {
        window.resetEpListbox('bor-agency', id, label);
      } else {
        window.resetEpListbox('bor-agency', '', '');
        if (agencyTrigger && label) {
          agencyTrigger.value = label;
          agencyTrigger.classList.remove('is-placeholder');
          if (agencyIdInput) agencyIdInput.value = '';
        }
      }
      return;
    }
    if (agencyIdInput) agencyIdInput.value = id;
    if (agencyTrigger) {
      agencyTrigger.value = label;
      agencyTrigger.classList.toggle('is-placeholder', !label);
    }
  }

  function resetForm() {
    editingId = '';
    if (editIdEl) editIdEl.value = '';
    setModalMode(false);
    setError('');
    if (typeof window.initHotelDatePickers === 'function') {
      window.initHotelDatePickers(modal);
    }
    resetHotelDate('bor-receipt-date', todayIso);
    setAgencyField('', '');
    if (typeof window.resetEpListbox === 'function') {
      window.resetEpListbox('bor-payment', 'cash', 'Cash');
    } else if (modeInput) {
      modeInput.value = 'cash';
      var modeValue = document.getElementById('bor-payment-value');
      if (modeValue) modeValue.textContent = 'Cash';
    }
    if (amountEl) amountEl.value = '';
    if (instrumentNoEl) instrumentNoEl.value = '';
    resetHotelDate('bor-instrument-date', '');
    if (towardsEl) towardsEl.value = '';
    if (submitBtn) submitBtn.removeAttribute('data-bor-saving');
    syncInstrumentVisibility();
    syncSaveUi();
  }

  function openAddModal() {
    if (!modal) return;
    resetForm();
    modal.classList.add('open');
    modal.setAttribute('aria-hidden', 'false');
    if (agencyTrigger) agencyTrigger.focus();
  }

  function openEditModal(btn) {
    if (!modal || !btn) return;
    resetForm();
    editingId = btn.getAttribute('data-id') || '';
    if (editIdEl) editIdEl.value = editingId;
    setModalMode(true);
    resetHotelDate('bor-receipt-date', btn.getAttribute('data-date') || todayIso);
    setAgencyField(btn.getAttribute('data-agency-id') || '', btn.getAttribute('data-payer-name') || '');
    if (amountEl) amountEl.value = btn.getAttribute('data-amount') || '';
    var mode = btn.getAttribute('data-payment-mode') || 'cash';
    var modeLabel = btn.getAttribute('data-payment-mode-label') || mode;
    if (typeof window.resetEpListbox === 'function') {
      window.resetEpListbox('bor-payment', mode, modeLabel);
    } else if (modeInput) {
      modeInput.value = mode;
      var modeValue = document.getElementById('bor-payment-value');
      if (modeValue) modeValue.textContent = modeLabel;
    }
    if (instrumentNoEl) instrumentNoEl.value = btn.getAttribute('data-instrument-no') || '';
    resetHotelDate('bor-instrument-date', btn.getAttribute('data-instrument-date') || '');
    if (towardsEl) towardsEl.value = btn.getAttribute('data-towards') || '';
    syncInstrumentVisibility();
    syncSaveUi();
    modal.classList.add('open');
    modal.setAttribute('aria-hidden', 'false');
    if (agencyTrigger) agencyTrigger.focus();
  }

  function closeModal() {
    if (!modal) return;
    modal.classList.remove('open');
    modal.setAttribute('aria-hidden', 'true');
    editingId = '';
    if (editIdEl) editIdEl.value = '';
    if (typeof window.closeHotelDatePickers === 'function') {
      window.closeHotelDatePickers();
    }
    if (typeof window.closeAllEpListboxes === 'function') {
      window.closeAllEpListboxes();
    }
  }

  function bindModal() {
    if (!modal || modal.getAttribute('data-bor-modal-bound') === '1') return;
    modal.setAttribute('data-bor-modal-bound', '1');
    var openBtn = document.getElementById('bor-open-add');
    var cancelBtn = document.getElementById('bor-add-cancel');
    if (openBtn) openBtn.addEventListener('click', openAddModal);
    if (cancelBtn) cancelBtn.addEventListener('click', closeModal);
    if (modal) {
      modal.addEventListener('click', function (ev) {
        if (ev.target === modal) closeModal();
      });
    }
    if (amountEl) {
      amountEl.addEventListener('input', syncSaveUi);
    }
    if (agencyTrigger) {
      agencyTrigger.addEventListener('input', syncSaveUi);
      agencyTrigger.addEventListener('change', syncSaveUi);
    }
    if (instrumentNoEl) instrumentNoEl.addEventListener('input', syncSaveUi);
    if (dateEl) {
      dateEl.addEventListener('change', syncSaveUi);
      dateEl.addEventListener('input', syncSaveUi);
    }
    if (submitBtn) {
      submitBtn.addEventListener('click', function () {
        if (!canSave()) return;
        var isEdit = !!editingId;
        var url = isEdit ? editUrl : addUrl;
        if (!url) return;
        setError('');
        submitBtn.setAttribute('data-bor-saving', '1');
        syncSaveUi();
        var agencyId = agencyIdInput ? String(agencyIdInput.value || '').trim() : '';
        var payload = {
          receipt_date: dateEl ? String(dateEl.value || '').trim() : '',
          payer_name: payerName(),
          agency_id: agencyId || null,
          amount: Number(amountEl.value),
          payment_mode: (modeInput && modeInput.value) || 'cash',
          instrument_no: instrumentNoEl ? String(instrumentNoEl.value || '').trim() : '',
          instrument_date: instrumentDateEl ? String(instrumentDateEl.value || '').trim() : '',
          towards: towardsEl ? String(towardsEl.value || '').trim() : ''
        };
        if (isEdit) payload.id = Number(editingId);
        fetch(url, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
          body: JSON.stringify(payload),
          credentials: 'same-origin'
        })
          .then(function (res) {
            return res.json().then(function (data) {
              return { ok: res.ok, data: data };
            });
          })
          .then(function (result) {
            if (!result.ok || !result.data || !result.data.ok) {
              setError((result.data && result.data.error) || 'Could not save receipt.');
              submitBtn.removeAttribute('data-bor-saving');
              syncSaveUi();
              return;
            }
            window.location.reload();
          })
          .catch(function () {
            setError('Could not save receipt.');
            submitBtn.removeAttribute('data-bor-saving');
            syncSaveUi();
          });
      });
    }
  }

  function bindRowActions() {
    Array.prototype.forEach.call(document.querySelectorAll('.bor-edit-btn'), function (btn) {
      if (btn.getAttribute('data-bor-action-bound') === '1') return;
      btn.setAttribute('data-bor-action-bound', '1');
      btn.addEventListener('click', function () {
        openEditModal(btn);
      });
    });
    Array.prototype.forEach.call(document.querySelectorAll('.bor-delete-btn'), function (btn) {
      if (btn.getAttribute('data-bor-action-bound') === '1') return;
      btn.setAttribute('data-bor-action-bound', '1');
      btn.addEventListener('click', function () {
        var id = btn.getAttribute('data-id');
        var no = btn.getAttribute('data-receipt-no') || '';
        if (!id || !deleteUrl) return;
        if (!window.confirm('Delete receipt ' + no + '?')) return;
        fetch(deleteUrl, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
          body: JSON.stringify({ id: Number(id) }),
          credentials: 'same-origin'
        })
          .then(function (res) {
            return res.json().then(function (data) {
              return { ok: res.ok, data: data };
            });
          })
          .then(function (result) {
            if (!result.ok || !result.data || !result.data.ok) {
              window.alert((result.data && result.data.error) || 'Could not delete receipt.');
              return;
            }
            window.location.reload();
          })
          .catch(function () {
            window.alert('Could not delete receipt.');
          });
      });
    });
  }

  formatAmounts();
  initDateRange();
  initClientSearch();
  if (typeof window.initHotelDatePickers === 'function') {
    window.initHotelDatePickers(modal || document);
  }
  bindModal();
  bindRowActions();
})();
