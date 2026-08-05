(function (global) {
  'use strict';

  function getModal() {
    return document.getElementById('sm-supplier-modal');
  }

  function getForm() {
    return document.getElementById('sm-supplier-form');
  }

  function setEditing(editing) {
    var modal = getModal();
    if (!modal) return;
    modal.setAttribute('data-sm-editing', editing ? '1' : '0');
    var title = document.getElementById('sm-supplier-modal-title');
    if (title) title.textContent = editing ? 'Edit supplier' : 'Add supplier';
    var saveBtn = document.getElementById('sm-supplier-save-btn');
    if (saveBtn) saveBtn.textContent = editing ? 'Update supplier' : 'Save supplier';
    var deleteForm = document.getElementById('sm-supplier-delete-form');
    if (deleteForm) {
      if (editing) deleteForm.removeAttribute('hidden');
      else deleteForm.setAttribute('hidden', '');
    }
  }

  function clearForm() {
    var form = getForm();
    if (!form) return;
    var idEl = document.getElementById('sm-supplier-id');
    if (idEl) idEl.value = '';
    var deleteId = document.getElementById('sm-supplier-delete-id');
    if (deleteId) deleteId.value = '';
    ['supplier-name', 'supplier-gst', 'supplier-address', 'supplier-phone',
      'supplier-bank-name', 'supplier-bank-account', 'supplier-ifsc'].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.value = '';
    });
    var err = document.getElementById('sm-supplier-modal-err');
    if (err) {
      err.innerHTML = '';
      err.hidden = true;
    }
    setEditing(false);
  }

  function navigateSupplierList() {
    var modal = getModal();
    var url = modal && modal.getAttribute('data-sm-list-url');
    var masterModal = document.getElementById('md-master-modal');
    if (masterModal && masterModal.classList.contains('open')) {
      if (modal) {
        modal.classList.remove('active');
        modal.setAttribute('aria-hidden', 'true');
      }
      return;
    }
    if (!url) return;
    if (typeof global.deSoftRefresh === 'function') {
      global.deSoftRefresh(url);
    } else if (typeof global.deNavigateWithTransition === 'function') {
      global.deNavigateWithTransition(url);
    } else {
      global.location.href = url;
    }
  }

  global.openSupplierModal = function openSupplierModal(opts) {
    var modal = getModal();
    var form = getForm();
    if (!modal || !form) return false;
    opts = opts || {};
    if (opts.reset !== false) clearForm();
    setEditing(!!(opts.editing || (document.getElementById('sm-supplier-id') || {}).value));
    modal.classList.add('active');
    modal.setAttribute('aria-hidden', 'false');
    global.setTimeout(function () {
      var focusEl = document.getElementById('supplier-name');
      if (focusEl) focusEl.focus();
    }, 0);
    return true;
  };

  global.closeSupplierModal = function closeSupplierModal(opts) {
    opts = opts || {};
    var modal = getModal();
    if (!modal) return;
    var wasEditing = modal.getAttribute('data-sm-editing') === '1';
    if (opts.navigate !== false && wasEditing) {
      navigateSupplierList();
      if (opts.reset !== false) clearForm();
      return;
    }
    modal.classList.remove('active');
    modal.setAttribute('aria-hidden', 'true');
    if (opts.reset !== false) clearForm();
  };

  function initSupplierTableSort() {
    var table = document.getElementById('sm-supplier-table');
    if (!table || table.getAttribute('data-sm-sort-bound') === '1') return;
    table.setAttribute('data-sm-sort-bound', '1');
    var tbody = table.tBodies[0];
    if (!tbody) return;
    var headers = Array.from(table.querySelectorAll('th.pl-sortable'));
    if (!headers.length) return;
    var activeKey = '';
    var ascending = true;

    function cellSortValue(row, colIndex, type) {
      var cell = row.cells[colIndex];
      if (!cell) return type === 'number' ? 0 : '';
      var raw = cell.getAttribute('data-sort-value');
      if (raw == null || raw === '') raw = (cell.textContent || '').trim();
      if (type === 'number') {
        var n = Number(raw);
        return isFinite(n) ? n : 0;
      }
      return String(raw).toLowerCase();
    }

    function sortBy(th) {
      var key = th.getAttribute('data-sort') || '';
      var type = th.getAttribute('data-sort-type') || 'text';
      var colIndex = Array.from(th.parentNode.children).indexOf(th);
      if (colIndex < 0) return;

      if (activeKey === key) ascending = !ascending;
      else {
        activeKey = key;
        ascending = true;
      }

      var rows = Array.from(tbody.querySelectorAll('tr[data-sort-row]'));
      rows.sort(function (a, b) {
        var av = cellSortValue(a, colIndex, type);
        var bv = cellSortValue(b, colIndex, type);
        var cmp = 0;
        if (type === 'number') cmp = av - bv;
        else cmp = String(av).localeCompare(String(bv), undefined, { numeric: true, sensitivity: 'base' });
        return ascending ? cmp : -cmp;
      });
      rows.forEach(function (row) { tbody.appendChild(row); });

      headers.forEach(function (header) {
        header.classList.remove('is-sorted-asc', 'is-sorted-desc');
        header.setAttribute('aria-sort', 'none');
      });
      th.classList.add(ascending ? 'is-sorted-asc' : 'is-sorted-desc');
      th.setAttribute('aria-sort', ascending ? 'ascending' : 'descending');
    }

    headers.forEach(function (th) {
      th.addEventListener('click', function () { sortBy(th); });
      th.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          sortBy(th);
        }
      });
    });
  }

  global.initSupplierMasterPage = function initSupplierMasterPage() {
    initSupplierTableSort();

    var modal = getModal();
    if (!modal) return;

    if (!document.documentElement.getAttribute('data-sm-supplier-modal-bound')) {
      document.documentElement.setAttribute('data-sm-supplier-modal-bound', '1');

      document.addEventListener('click', function (e) {
        var actionEl = e.target.closest('[data-sm-action]');
        if (!actionEl) {
          if (e.target === getModal()) {
            global.closeSupplierModal({ navigate: true, reset: true });
          }
          return;
        }
        var action = actionEl.getAttribute('data-sm-action');
        if (action === 'open-supplier-modal') {
          e.preventDefault();
          global.openSupplierModal({ reset: true });
        } else if (action === 'close-supplier-modal') {
          e.preventDefault();
          global.closeSupplierModal({ navigate: true, reset: true });
        }
      });

      document.addEventListener('keydown', function (e) {
        if (e.key !== 'Escape') return;
        var openModal = getModal();
        if (openModal && openModal.classList.contains('active')) {
          e.preventDefault();
          e.stopPropagation();
          global.closeSupplierModal({ navigate: true, reset: true });
        }
      }, true);
    }

    if (modal.classList.contains('active')) {
      modal.setAttribute('aria-hidden', 'false');
      global.setTimeout(function () {
        var focusEl = document.getElementById('supplier-name');
        if (focusEl) focusEl.focus();
      }, 0);
    }
  };
})(typeof window !== 'undefined' ? window : this);
