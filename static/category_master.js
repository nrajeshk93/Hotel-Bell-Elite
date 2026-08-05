(function (global) {
  'use strict';

  function getModal() {
    return document.getElementById('cm-category-modal');
  }

  function getForm() {
    return document.getElementById('cm-category-form');
  }

  function setEditing(editing) {
    var modal = getModal();
    if (!modal) return;
    modal.setAttribute('data-cm-editing', editing ? '1' : '0');
    var title = document.getElementById('cm-category-modal-title');
    if (title) title.textContent = editing ? 'Edit category' : 'Add category';
    var saveBtn = document.getElementById('cm-category-save-btn');
    if (saveBtn) saveBtn.textContent = editing ? 'Update category' : 'Save category';
    var deleteForm = document.getElementById('cm-category-delete-form');
    if (deleteForm) {
      if (editing) deleteForm.removeAttribute('hidden');
      else deleteForm.setAttribute('hidden', '');
    }
  }

  function clearForm() {
    var idEl = document.getElementById('cm-category-id');
    if (idEl) idEl.value = '';
    var deleteId = document.getElementById('cm-category-delete-id');
    if (deleteId) deleteId.value = '';
    var nameEl = document.getElementById('cm-category-name');
    if (nameEl) nameEl.value = '';
    var visibleEl = document.getElementById('cm-category-visible');
    if (visibleEl) visibleEl.checked = true;
    if (typeof global.resetEpListbox === 'function') {
      global.resetEpListbox('cm-category-outlet', 'restaurant', 'Restaurant');
    }
    var deleteOutlet = document.getElementById('cm-category-delete-outlet');
    if (deleteOutlet) deleteOutlet.value = 'restaurant';
    var err = document.getElementById('cm-category-modal-err');
    if (err) {
      err.innerHTML = '';
      err.hidden = true;
    }
    setEditing(false);
  }

  function fillFromRow(row) {
    if (!row) return;
    var id = row.getAttribute('data-category-id') || '';
    var name = row.getAttribute('data-category-name') || '';
    var outlet = row.getAttribute('data-category-outlet') || 'restaurant';
    var visible = row.getAttribute('data-category-visible') === '1';
    var idEl = document.getElementById('cm-category-id');
    if (idEl) idEl.value = id;
    var deleteId = document.getElementById('cm-category-delete-id');
    if (deleteId) deleteId.value = id;
    var nameEl = document.getElementById('cm-category-name');
    if (nameEl) nameEl.value = name;
    var visibleEl = document.getElementById('cm-category-visible');
    if (visibleEl) visibleEl.checked = visible;
    var outletLabel = outlet === 'bar' ? 'Bar' : 'Restaurant';
    if (typeof global.resetEpListbox === 'function') {
      global.resetEpListbox('cm-category-outlet', outlet, outletLabel);
    }
    var deleteOutlet = document.getElementById('cm-category-delete-outlet');
    if (deleteOutlet) deleteOutlet.value = outlet;
    setEditing(true);
  }

  function navigateList() {
    var modal = getModal();
    var url = modal && modal.getAttribute('data-cm-list-url');
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

  global.openCategoryMasterModal = function openCategoryMasterModal(opts) {
    var modal = getModal();
    var form = getForm();
    if (!modal || !form) return false;
    opts = opts || {};
    if (opts.row) fillFromRow(opts.row);
    else if (opts.reset !== false) clearForm();
    modal.classList.add('active');
    modal.setAttribute('aria-hidden', 'false');
    if (typeof global.initEpListboxes === 'function') global.initEpListboxes();
    global.setTimeout(function () {
      var focusEl = document.getElementById('cm-category-name');
      if (focusEl) focusEl.focus();
    }, 0);
    return true;
  };

  global.closeCategoryMasterModal = function closeCategoryMasterModal(opts) {
    opts = opts || {};
    var modal = getModal();
    if (!modal) return;
    var wasEditing = modal.getAttribute('data-cm-editing') === '1';
    if (opts.navigate !== false && wasEditing) {
      navigateList();
      if (opts.reset !== false) clearForm();
      return;
    }
    modal.classList.remove('active');
    modal.setAttribute('aria-hidden', 'true');
    if (opts.reset !== false) clearForm();
  };

  function initCategoryTableSort() {
    var table = document.getElementById('cm-category-table');
    if (!table || table.getAttribute('data-cm-sort-bound') === '1') return;
    table.setAttribute('data-cm-sort-bound', '1');
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

  global.initCategoryMasterPage = function initCategoryMasterPage() {
    initCategoryTableSort();
    var modal = getModal();
    if (!modal) return;

    if (!document.documentElement.getAttribute('data-cm-category-modal-bound')) {
      document.documentElement.setAttribute('data-cm-category-modal-bound', '1');

      document.addEventListener('click', function (e) {
        var actionEl = e.target.closest('[data-cm-action]');
        if (!actionEl) {
          if (e.target === getModal()) {
            global.closeCategoryMasterModal({ navigate: true, reset: true });
          }
          return;
        }
        var action = actionEl.getAttribute('data-cm-action');
        if (action === 'open-category-modal') {
          e.preventDefault();
          global.openCategoryMasterModal({ reset: true });
        } else if (action === 'edit-category') {
          e.preventDefault();
          var row = actionEl.closest('tr[data-category-id]');
          global.openCategoryMasterModal({ row: row });
        } else if (action === 'close-category-modal') {
          e.preventDefault();
          global.closeCategoryMasterModal({ navigate: true, reset: true });
        }
      });

      document.addEventListener('keydown', function (e) {
        if (e.key !== 'Escape') return;
        var openModal = getModal();
        if (openModal && openModal.classList.contains('active')) {
          e.preventDefault();
          e.stopPropagation();
          global.closeCategoryMasterModal({ navigate: true, reset: true });
        }
      }, true);
    }

    if (modal.classList.contains('active')) {
      modal.setAttribute('aria-hidden', 'false');
      if (typeof global.initEpListboxes === 'function') global.initEpListboxes();
      global.setTimeout(function () {
        var focusEl = document.getElementById('cm-category-name');
        if (focusEl) focusEl.focus();
      }, 0);
    }
  };
})(typeof window !== 'undefined' ? window : this);
