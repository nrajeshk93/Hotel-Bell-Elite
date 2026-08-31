(function (global) {
  'use strict';

  function getModal() {
    return document.getElementById('um-unit-modal');
  }

  function getForm() {
    return document.getElementById('um-unit-form');
  }

  function setEditing(editing) {
    var modal = getModal();
    if (!modal) return;
    modal.setAttribute('data-um-editing', editing ? '1' : '0');
    var title = document.getElementById('um-unit-modal-title');
    if (title) title.textContent = editing ? 'Edit unit' : 'Add unit';
    var saveBtn = document.getElementById('um-unit-save-btn');
    if (saveBtn) saveBtn.textContent = 'Save';
  }

  function clearForm() {
    var idEl = document.getElementById('um-unit-id');
    if (idEl) idEl.value = '';
    var nameEl = document.getElementById('um-unit-name');
    if (nameEl) nameEl.value = '';
    var err = document.getElementById('um-unit-modal-err');
    if (err) {
      err.innerHTML = '';
      err.hidden = true;
    }
    setEditing(false);
  }

  function fillFromRow(row) {
    if (!row) return;
    var id = row.getAttribute('data-unit-id') || '';
    var name = row.getAttribute('data-unit-name') || '';
    var idEl = document.getElementById('um-unit-id');
    if (idEl) idEl.value = id;
    var nameEl = document.getElementById('um-unit-name');
    if (nameEl) nameEl.value = name;
    setEditing(true);
  }

  function navigateList() {
    var modal = getModal();
    var url = modal && modal.getAttribute('data-um-list-url');
    var masterModal = document.getElementById('md-master-modal');
    if (masterModal && masterModal.classList.contains('open')) {
      if (modal) {
        modal.classList.remove('active');
        modal.setAttribute('aria-hidden', 'true');
      }
      return;
    }
    if (!url) return;
    if (typeof global.deSoftRefresh === 'function') global.deSoftRefresh(url);
    else if (typeof global.deNavigateWithTransition === 'function') global.deNavigateWithTransition(url);
    else global.location.href = url;
  }

  global.openUnitMasterModal = function openUnitMasterModal(opts) {
    var modal = getModal();
    var form = getForm();
    if (!modal || !form) return false;
    opts = opts || {};
    if (opts.row) fillFromRow(opts.row);
    else if (opts.reset !== false) clearForm();
    modal.classList.add('active');
    modal.setAttribute('aria-hidden', 'false');
    global.setTimeout(function () {
      var focusEl = document.getElementById('um-unit-name');
      if (focusEl) focusEl.focus();
    }, 0);
    return true;
  };

  global.closeUnitMasterModal = function closeUnitMasterModal(opts) {
    opts = opts || {};
    var modal = getModal();
    if (!modal) return;
    var wasEditing = modal.getAttribute('data-um-editing') === '1';
    if (opts.navigate !== false && wasEditing) {
      navigateList();
      if (opts.reset !== false) clearForm();
      return;
    }
    modal.classList.remove('active');
    modal.setAttribute('aria-hidden', 'true');
    if (opts.reset !== false) clearForm();
  };

  function initUnitTableSort() {
    var table = document.getElementById('um-unit-table');
    if (!table || table.getAttribute('data-um-sort-bound') === '1') return;
    table.setAttribute('data-um-sort-bound', '1');
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
        var cmp = type === 'number' ? av - bv
          : String(av).localeCompare(String(bv), undefined, { numeric: true, sensitivity: 'base' });
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

  global.initUnitMasterPage = function initUnitMasterPage() {
    initUnitTableSort();
    var modal = getModal();
    if (!modal) return;

    if (!document.documentElement.getAttribute('data-um-unit-modal-bound')) {
      document.documentElement.setAttribute('data-um-unit-modal-bound', '1');

      document.addEventListener('click', function (e) {
        var actionEl = e.target.closest('[data-um-action]');
        if (!actionEl) {
          if (e.target === getModal()) {
            global.closeUnitMasterModal({ navigate: true, reset: true });
          }
          return;
        }
        var action = actionEl.getAttribute('data-um-action');
        if (action === 'open-unit-modal') {
          e.preventDefault();
          global.openUnitMasterModal({ reset: true });
        } else if (action === 'edit-unit') {
          e.preventDefault();
          var row = actionEl.closest('tr[data-unit-id]');
          global.openUnitMasterModal({ row: row });
        } else if (action === 'delete-unit') {
          e.preventDefault();
          e.stopPropagation();
          var delRow = actionEl.closest('tr[data-unit-id]');
          var delId = delRow ? delRow.getAttribute('data-unit-id') || '' : '';
          var delName = delRow ? delRow.getAttribute('data-unit-name') || 'this unit' : 'this unit';
          if (!delId) return;
          if (!global.confirm('Delete "' + delName + '"? Units used by products cannot be deleted.')) {
            return;
          }
          var deleteForm = document.getElementById('um-unit-delete-form');
          var deleteIdEl = document.getElementById('um-unit-delete-id');
          if (!deleteForm || !deleteIdEl) return;
          deleteIdEl.value = delId;
          if (typeof deleteForm.requestSubmit === 'function') deleteForm.requestSubmit();
          else {
            var submitEv = new Event('submit', { bubbles: true, cancelable: true });
            if (deleteForm.dispatchEvent(submitEv)) deleteForm.submit();
          }
        } else if (action === 'close-unit-modal') {
          e.preventDefault();
          global.closeUnitMasterModal({ navigate: true, reset: true });
        }
      });

      document.addEventListener('keydown', function (e) {
        if (e.key !== 'Escape') return;
        var openModal = getModal();
        if (openModal && openModal.classList.contains('active')) {
          e.preventDefault();
          e.stopPropagation();
          global.closeUnitMasterModal({ navigate: true, reset: true });
        }
      }, true);
    }

    if (modal.classList.contains('active')) {
      modal.setAttribute('aria-hidden', 'false');
      global.setTimeout(function () {
        var focusEl = document.getElementById('um-unit-name');
        if (focusEl) focusEl.focus();
      }, 0);
    }
  };
})(typeof window !== 'undefined' ? window : this);
