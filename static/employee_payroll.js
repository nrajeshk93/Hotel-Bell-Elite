/**
 * Employee Payroll UI helpers.
 * Soft-nav only swaps .de-main-wrapper — keep these on window and re-init after every swap.
 */
(function () {
  'use strict';

  function pageConfig() {
    var el = document.getElementById('ep-page-config');
    if (!el) return { year: '', month: '', lockUrl: '/lock_payroll_month' };
    try {
      return JSON.parse(el.textContent || '{}') || {};
    } catch (e) {
      return { year: '', month: '', lockUrl: '/lock_payroll_month' };
    }
  }

  function byId(id) {
    return document.getElementById(id);
  }

  window.openImportModal = function openImportModal() {
    var modal = byId('import-modal');
    if (modal) modal.classList.add('active');
  };

  window.closeImportModal = function closeImportModal() {
    var modal = byId('import-modal');
    if (modal) modal.classList.remove('active');
  };

  window.onFileChosen = function onFileChosen(input) {
    var lbl = byId('file-chosen-label');
    var btn = byId('import-submit-btn');
    if (!lbl || !btn) return;
    if (input && input.files && input.files[0]) {
      lbl.textContent = input.files[0].name;
      lbl.style.display = 'block';
      btn.disabled = false;
    } else {
      lbl.style.display = 'none';
      btn.disabled = true;
    }
  };

  window.toggleExempt = function toggleExempt(type) {
    var cb = byId(type + '_exempt');
    var inp = byId(type + '_amount');
    if (!cb || !inp) return;
    if (cb.checked) {
      inp.disabled = true;
      inp.value = '';
      inp.style.opacity = '0.45';
      inp.style.background = 'var(--bg)';
      inp.placeholder = 'No ' + type.toUpperCase() + ' — full amount to Basic';
    } else {
      inp.disabled = false;
      inp.style.opacity = '';
      inp.style.background = '';
      inp.placeholder = type === 'epf'
        ? 'Auto: 12% of Actual Gross (max ₹1,800)'
        : 'Auto: 0.75% of Gross (₹158 if Gross > ₹21,000)';
    }
    window.calcPreview();
  };

  window.calcPreview = function calcPreview() {
    var inp = byId('gross_salary');
    if (!inp) return;
    var gross = parseFloat(inp.value) || 0;
    var preview = byId('salary-preview');
    var warn = byId('salary-warning');
    if (!preview) return;
    if (gross <= 0) {
      preview.style.display = 'none';
      if (warn) warn.style.display = 'none';
      return;
    }
    preview.style.display = 'grid';
    var customBasic = parseFloat((byId('basic_salary') || {}).value) || 0;
    var customEpf = parseFloat((byId('epf_amount') || {}).value) || 0;
    var customEsic = parseFloat((byId('esic_amount') || {}).value) || 0;
    var crEl = byId('credit_repayment');
    var creditRepay = crEl ? (parseFloat(crEl.value) || 0) : 0;
    var crItem = byId('pv-cr-item');
    if (crItem) crItem.style.display = crEl ? '' : 'none';
    var epfExempt = byId('epf_exempt') && byId('epf_exempt').checked;
    var esicExempt = byId('esic_exempt') && byId('esic_exempt').checked;
    var esic = 0;
    var esicLabel = 'ESIC (auto .75%)';
    if (esicExempt) {
      esic = 0;
      esicLabel = 'ESIC (exempt ₹0)';
    } else if (customEsic > 0) {
      esic = customEsic;
      esicLabel = 'ESIC (custom)';
    } else if (gross > 21000) {
      esic = 158;
      esicLabel = 'ESIC (fixed ₹158 > ₹21k)';
    } else {
      esic = Math.round(gross * 0.0075 * 100) / 100;
      esicLabel = 'ESIC (auto .75%)';
    }
    var epf = 0;
    if (epfExempt) {
      epf = 0;
    } else if (customEpf > 0) {
      epf = Math.min(1800, customEpf);
    } else {
      epf = Math.min(1800, Math.round(gross * 0.12 * 100) / 100);
    }
    var basic = Math.max(0, Math.round((gross - epf - esic) * 100) / 100);
    var netRaw = Math.round((gross - epf - esic - creditRepay) * 100) / 100;
    var net = Math.max(0, netRaw);
    var fmt = typeof window.fmtInr === 'function' ? window.fmtInr : function (v) { return String(v); };
    var setText = function (id, text) {
      var el = byId(id);
      if (el) el.textContent = text;
    };
    setText('pv-gross', fmt(gross, 0));
    setText('pv-basic', fmt(basic, 0));
    setText('pv-epf', fmt(epf, 0));
    setText('pv-esic', fmt(esic, 0));
    setText('pv-cr', fmt(creditRepay, 0));
    setText('pv-net', fmt(net, 0));
    setText('pv-basic-label', epfExempt ? 'Basic (EPF exempt)' : (customBasic > 0 ? 'Basic (custom)' : 'Basic (auto)'));
    setText('pv-epf-label', epfExempt ? 'EPF (exempt ₹0)' : (customEpf > 0 ? 'EPF (custom, max ₹1,800)' : 'EPF (12% of Gross, max ₹1,800)'));
    setText('pv-esic-label', esicLabel);
    setText('pv-cr-label', creditRepay > 0 ? 'Credit Repay' : 'Credit Repay (0)');
    var warnings = [];
    if (customBasic > 0 && customBasic > gross) warnings.push('Basic Pay exceeds Gross Salary');
    if (!epfExempt) {
      var comp = Math.round((basic + epf + esic) * 100) / 100;
      if (Math.abs(comp - gross) > 0.01) {
        warnings.push('Gross mismatch: Basic+EPF+ESIC = ' + comp.toFixed(2) + ', Gross = ' + gross.toFixed(2));
      }
    }
    if (epf + esic + creditRepay > gross) warnings.push('Total deductions exceed Gross Salary');
    if (netRaw < 0) warnings.push('Net is 0 — deductions exceed Gross');
    if (warn) {
      if (warnings.length) {
        warn.style.display = 'block';
        warn.textContent = warnings.join('. ');
      } else {
        warn.style.display = 'none';
      }
    }
  };

  var _openSd = null;
  window.toggleSd = function toggleSd(trigger) {
    if (!trigger) return;
    var wrap = trigger.closest('.sd-wrap');
    if (!wrap) return;
    var panel = wrap.querySelector('.sd-panel');
    if (!panel) return;
    var isOpen = panel.style.display === 'block';
    window.closeAllSd();
    if (!isOpen) {
      panel.style.display = 'block';
      trigger.classList.add('open');
      _openSd = wrap;
      var srch = panel.querySelector('.sd-search');
      if (srch) {
        srch.value = '';
        window.filterSd(srch);
        setTimeout(function () { srch.focus(); }, 30);
      }
    }
  };

  window.closeAllSd = function closeAllSd() {
    document.querySelectorAll('.sd-wrap').forEach(function (w) {
      var panel = w.querySelector('.sd-panel');
      var trigger = w.querySelector('.sd-trigger');
      if (panel) panel.style.display = 'none';
      if (trigger) trigger.classList.remove('open');
    });
    _openSd = null;
  };

  window.filterSd = function filterSd(searchInput) {
    if (!searchInput) return;
    var panel = searchInput.closest('.sd-panel');
    if (!panel) return;
    var list = panel.querySelector('.sd-list');
    if (!list) return;
    var q = searchInput.value.toLowerCase();
    var items = list.querySelectorAll('.sd-item');
    var any = false;
    items.forEach(function (item) {
      var m = String(item.dataset.value || '').toLowerCase().includes(q);
      item.style.display = m ? '' : 'none';
      if (m) any = true;
    });
    var empty = list.querySelector('.sd-empty');
    if (!any) {
      if (!empty) {
        empty = document.createElement('div');
        empty.className = 'sd-empty';
        empty.textContent = 'No matches';
        list.appendChild(empty);
      }
      empty.style.display = '';
    } else if (empty) {
      empty.style.display = 'none';
    }
  };

  window.selectSd = function selectSd(el) {
    if (!el) return;
    var wrap = el.closest('.sd-wrap');
    if (!wrap) return;
    var field = wrap.dataset.field;
    var input = field ? byId(field) : null;
    if (input) input.value = el.dataset.value;
    var display = wrap.querySelector('.sd-display');
    if (display) display.textContent = el.dataset.value;
    wrap.querySelectorAll('.sd-item').forEach(function (i) {
      i.classList.remove('selected', 'active');
    });
    el.classList.add('selected');
    window.closeAllSd();
  };

  window.sdNav = function sdNav(e, searchInput) {
    if (!e || !searchInput) return;
    var panel = searchInput.closest('.sd-panel');
    if (!panel) return;
    var list = panel.querySelector('.sd-list');
    if (!list) return;
    var visible = Array.from(list.querySelectorAll('.sd-item')).filter(function (i) {
      return i.style.display !== 'none';
    });
    var active = list.querySelector('.sd-item.active');
    var idx = visible.indexOf(active);
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      idx = Math.min(idx + 1, visible.length - 1);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      idx = Math.max(idx - 1, 0);
    } else if (e.key === 'Enter' && active) {
      e.preventDefault();
      window.selectSd(active);
      return;
    } else if (e.key === 'Escape') {
      window.closeAllSd();
      return;
    } else {
      return;
    }
    if (active) active.classList.remove('active');
    if (visible[idx]) {
      visible[idx].classList.add('active');
      visible[idx].scrollIntoView({ block: 'nearest' });
    }
  };

  var attEmpId = '';
  var attDate = '';

  window.openAttPopup = function openAttPopup(empId, dateStr, dayNum, currentStatus) {
    var popup = byId('att-popup');
    if (!popup) return;
    var todayStr = new Date().toISOString().split('T')[0];
    if (dateStr > todayStr) return;
    attEmpId = empId;
    attDate = dateStr;
    var isSunday = (new Date(dateStr + 'T12:00:00')).getDay() === 0;
    var title = byId('att-popup-title');
    if (title) {
      title.textContent = 'Day ' + dayNum + ' — ' + dateStr + (isSunday ? ' (Sunday)' : '');
    }
    var ab = byId('att-absent-btn');
    if (ab) ab.style.display = '';
    popup.classList.add('active');
  };

  window.closeAttPopup = function closeAttPopup() {
    var popup = byId('att-popup');
    if (popup) popup.classList.remove('active');
  };

  window.markAtt = function markAtt(status) {
    var cfg = pageConfig();
    var form = document.createElement('form');
    form.method = 'POST';
    form.action = '/mark_attendance';
    var fields = {
      employee_id: attEmpId,
      date: attDate,
      status: status,
      year: cfg.year,
      month: cfg.month
    };
    Object.keys(fields).forEach(function (k) {
      var inp = document.createElement('input');
      inp.type = 'hidden';
      inp.name = k;
      inp.value = fields[k];
      form.appendChild(inp);
    });
    document.body.appendChild(form);
    form.submit();
  };

  window.showEditCredit = function showEditCredit(id) {
    var row = byId('cr-row-' + id);
    var edit = byId('cr-edit-' + id);
    if (row) row.hidden = true;
    if (edit) edit.hidden = false;
  };

  window.hideEditCredit = function hideEditCredit(id) {
    var row = byId('cr-row-' + id);
    var edit = byId('cr-edit-' + id);
    if (row) row.hidden = false;
    if (edit) edit.hidden = true;
  };

  window.submitEditCredit = function submitEditCredit(id) {
    var cfg = pageConfig();
    var form = document.createElement('form');
    form.method = 'POST';
    form.action = '/edit_credit/' + id;
    var fields = {
      date: (byId('cr-date-' + id) || {}).value || '',
      description: (byId('cr-desc-' + id) || {}).value || '',
      amount: (byId('cr-amt-' + id) || {}).value || '',
      year: cfg.year,
      month: cfg.month
    };
    Object.keys(fields).forEach(function (k) {
      var inp = document.createElement('input');
      inp.type = 'hidden';
      inp.name = k;
      inp.value = fields[k];
      form.appendChild(inp);
    });
    document.body.appendChild(form);
    form.submit();
  };

  window.submitPayrollLock = function submitPayrollLock(year, month, label) {
    if (!window.confirm(
      'Lock ' + label + '? After locking, NO edits are allowed for this month — attendance, credits, repayments, tip incentive, and wage fields — including for administrators. This cannot be undone from here.'
    )) return;
    var cfg = pageConfig();
    var form = document.createElement('form');
    form.method = 'POST';
    form.action = cfg.lockUrl || '/lock_payroll_month';
    var fields = { year: year, month: month, lock_action: 'manual_lock' };
    Object.keys(fields).forEach(function (k) {
      var inp = document.createElement('input');
      inp.type = 'hidden';
      inp.name = k;
      inp.value = fields[k];
      form.appendChild(inp);
    });
    document.body.appendChild(form);
    form.submit();
  };

  window.filterCreditTable = function filterCreditTable() {
    var q = ((byId('cd-search') || {}).value || '').toLowerCase().trim();
    var location = ((byId('cd-location') || {}).value || '').toLowerCase();
    var rows = document.querySelectorAll('#credit-emp-table tbody tr');
    var visible = 0;
    rows.forEach(function (row) {
      var name = row.dataset.name || '';
      var loc = row.dataset.location || '';
      var show = (!q || name.indexOf(q) !== -1) && (!location || loc === location);
      row.style.display = show ? '' : 'none';
      if (show) visible++;
    });
    var noRes = byId('cd-no-results');
    if (noRes) noRes.hidden = !(visible === 0 && rows.length > 0);
    var badge = byId('cd-count-badge');
    if (badge) badge.textContent = visible + ' employee' + (visible !== 1 ? 's' : '');
  };

  window.toggleCreditPaymentFields = function toggleCreditPaymentFields() {
    var payEl = byId('acm-payment');
    var txnWrap = byId('acm-txn-wrap');
    if (!payEl || !txnWrap) return;
    var isBank = payEl.value === 'bank_transfer';
    txnWrap.hidden = !isBank;
    var txnEl = byId('acm-txn');
    if (txnEl) txnEl.required = isBank;
  };

  window.openAddCreditModal = function openAddCreditModal(type) {
    var modal = byId('add-credit-modal');
    if (!modal) return false;
    type = type === 'repayment' ? 'repayment' : 'credit';
    var typeEl = byId('acm-type');
    var dateEl = byId('acm-date');
    var amountEl = byId('acm-amount');
    var descEl = byId('acm-desc');
    if (!typeEl || !dateEl || !amountEl || !descEl) return false;

    var lockedEmp = document.querySelector('.acm-locked-emp');
    var today = new Date().toISOString().split('T')[0];
    typeEl.value = type;
    dateEl.value = today;
    amountEl.value = '';
    descEl.value = type === 'repayment' ? 'Repayment' : '';

    if (typeof window.resetEpListbox === 'function') {
      window.resetEpListbox('acm-payment', 'cash', 'Cash');
    } else {
      var payEl = byId('acm-payment');
      if (payEl) payEl.value = 'cash';
    }
    var txnEl = byId('acm-txn');
    if (txnEl) txnEl.value = '';
    var payFields = byId('acm-payment-fields');
    if (payFields) payFields.style.display = type === 'repayment' ? 'none' : 'grid';
    window.toggleCreditPaymentFields();

    if (!lockedEmp && typeof window.resetEpListbox === 'function') {
      window.resetEpListbox('acm-emp-hidden', '', 'Select employee…');
    }

    var errEl = byId('acm-err');
    if (errEl) errEl.style.display = 'none';
    var title = byId('acm-title');
    if (title) title.textContent = type === 'repayment' ? 'Add Repayment' : 'Add Credit / Advance';
    var submitLabel = byId('acm-submit-label');
    if (submitLabel) submitLabel.textContent = type === 'repayment' ? 'Repayment' : 'Add Credit';
    if (typeof window.initEpListboxes === 'function') {
      window.initEpListboxes();
    }
    modal.classList.add('active');
    return true;
  };

  window.closeAddCreditModal = function closeAddCreditModal() {
    var modal = byId('add-credit-modal');
    if (modal) modal.classList.remove('active');
  };

  window.submitAddCredit = function submitAddCredit() {
    var form = byId('add-credit-form');
    var errEl = byId('acm-err');
    if (!form || !errEl) return;
    var empId = (byId('acm-emp-hidden') || {}).value || '';
    var date = (byId('acm-date') || {}).value || '';
    var amount = (byId('acm-amount') || {}).value || '';
    var type = (byId('acm-type') || {}).value || 'credit';
    if (!empId) {
      errEl.textContent = 'Please select an employee.';
      errEl.style.display = 'block';
      return;
    }
    if (!date) {
      errEl.textContent = 'Please select a date.';
      errEl.style.display = 'block';
      return;
    }
    if (!amount || parseFloat(amount) <= 0) {
      errEl.textContent = 'Please enter a valid amount greater than 0.';
      errEl.style.display = 'block';
      return;
    }
    if (type !== 'repayment') {
      var payEl = byId('acm-payment');
      var txnEl = byId('acm-txn');
      if (payEl && payEl.value === 'bank_transfer' && (!txnEl || !txnEl.value.trim())) {
        errEl.textContent = 'Transaction ID is required for bank transfer.';
        errEl.style.display = 'block';
        return;
      }
    }
    errEl.style.display = 'none';
    form.submit();
  };

  window.saveSalary = function saveSalary(empId) {
    var crEl = byId('cr-' + empId);
    if (!crEl) return;
    var cfg = pageConfig();
    var fmt = typeof window.fmtInr === 'function' ? window.fmtInr : function (v) { return String(v); };
    crEl.className = 'inline-sal saving';
    fetch('/update_salary/' + empId, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        credit_repayment: crEl.value || '0',
        year: cfg.year,
        month: cfg.month
      })
    })
      .then(function (r) {
        return r.json().then(function (d) {
          if (!r.ok) throw d;
          return d;
        });
      })
      .then(function (d) {
        if (d.ok) {
          crEl.value = d.credit_repayment || '';
          crEl.className = 'inline-sal saved';
          var netEl = byId('net-' + empId);
          if (netEl) netEl.textContent = fmt(d.net, 0);
          var cbEl = byId('cb-' + empId);
          if (cbEl && typeof d.credit_balance !== 'undefined') {
            var bal = d.credit_balance;
            cbEl.textContent = fmt(bal, 2);
            cbEl.className = 'num ' + (bal > 0 ? 'orange' : '');
            cbEl.style.color = bal <= 0 ? 'var(--txt3)' : '';
            cbEl.style.transition = 'color .3s';
            cbEl.style.color = 'var(--ok)';
            setTimeout(function () {
              cbEl.style.color = bal <= 0 ? 'var(--txt3)' : '';
            }, 1200);
          }
          setTimeout(function () { crEl.className = 'inline-sal'; }, 2000);
        } else {
          crEl.className = 'inline-sal error';
        }
      })
      .catch(function (err) {
        crEl.className = 'inline-sal error';
        if (err && err.max_repayment !== undefined) {
          crEl.value = err.max_repayment || '';
        }
        if (err && err.error) {
          window.alert(err.error);
        }
      });
  };

  function bindOverlayOnce(el, closeFn) {
    if (!el || el.getAttribute('data-ep-overlay-bound') === '1') return;
    el.setAttribute('data-ep-overlay-bound', '1');
    el.addEventListener('click', function (e) {
      if (e.target === el) closeFn();
    });
  }

  function ensureDelegates() {
    if (window.__epPayrollDelegatesBound) return;
    window.__epPayrollDelegatesBound = true;

    document.addEventListener('click', function (e) {
      if (_openSd && !_openSd.contains(e.target)) {
        window.closeAllSd();
      }

      var openCredit = e.target.closest('[data-ep-action="open-credit-modal"]');
      if (openCredit) {
        e.preventDefault();
        window.openAddCreditModal(openCredit.getAttribute('data-ep-credit-type') || 'credit');
        return;
      }
      var closeCredit = e.target.closest('[data-ep-action="close-credit-modal"]');
      if (closeCredit) {
        e.preventDefault();
        window.closeAddCreditModal();
        return;
      }
      var submitCredit = e.target.closest('[data-ep-action="submit-credit-modal"]');
      if (submitCredit) {
        e.preventDefault();
        window.submitAddCredit();
        return;
      }
      var openImport = e.target.closest('[data-ep-action="open-import-modal"]');
      if (openImport) {
        e.preventDefault();
        window.openImportModal();
        return;
      }
      var closeImport = e.target.closest('[data-ep-action="close-import-modal"]');
      if (closeImport) {
        e.preventDefault();
        window.closeImportModal();
      }
    });
  }

  window.initEmployeePayrollPage = function initEmployeePayrollPage() {
    ensureDelegates();
    bindOverlayOnce(byId('add-credit-modal'), window.closeAddCreditModal);
    bindOverlayOnce(byId('import-modal'), window.closeImportModal);
    var popup = byId('att-popup');
    if (popup && popup.getAttribute('data-ep-overlay-bound') !== '1') {
      popup.setAttribute('data-ep-overlay-bound', '1');
      popup.addEventListener('click', function (e) {
        if (e.target === popup) window.closeAttPopup();
      });
    }
    var gross = byId('gross_salary');
    if (gross && gross.value) window.calcPreview();
    if (window.lucide && typeof window.lucide.createIcons === 'function') {
      window.lucide.createIcons({ attrs: { 'stroke-width': 1.75 } });
    }
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', window.initEmployeePayrollPage);
  } else {
    window.initEmployeePayrollPage();
  }
})();
