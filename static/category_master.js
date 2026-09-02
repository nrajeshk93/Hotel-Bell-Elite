(function (global) {
  'use strict';

  var MODULE_LABELS = {
    restaurant: 'Restaurant',
    bar: 'Bar',
    purchase: 'Purchase',
    expense: 'Expense'
  };

  function getModal() {
    return document.getElementById('cm-category-modal');
  }

  function getForm() {
    return document.getElementById('cm-category-form');
  }

  function moduleLabel(module) {
    return MODULE_LABELS[module] || 'Restaurant';
  }

  function isPosModule(module) {
    return module === 'restaurant' || module === 'bar';
  }

  function setModuleValue(module) {
    var next = MODULE_LABELS[module] ? module : 'restaurant';
    var hidden = document.getElementById('cm-category-module');
    if (hidden) hidden.value = next;
    if (typeof global.resetEpListbox === 'function') {
      global.resetEpListbox('cm-category-module', next, moduleLabel(next));
    }
  }

  function setModuleLocked(locked) {
    var field = document.getElementById('cm-category-module-field');
    if (!field) return;
    field.classList.toggle('is-locked', !!locked);
    var listbox = document.getElementById('cm-category-module-listbox');
    if (listbox) listbox.setAttribute('aria-disabled', locked ? 'true' : 'false');
  }

  function currentModule() {
    var el = document.getElementById('cm-category-module');
    return el ? String(el.value || 'restaurant') : 'restaurant';
  }

  function setEditing(editing) {
    var modal = getModal();
    if (!modal) return;
    modal.setAttribute('data-cm-editing', editing ? '1' : '0');
    var title = document.getElementById('cm-category-modal-title');
    if (title) title.textContent = editing ? 'Edit category' : 'Add category';
    var saveBtn = document.getElementById('cm-category-save-btn');
    if (saveBtn) saveBtn.textContent = 'Save';
    setModuleLocked(!!editing);
  }

  function clearForm() {
    var idEl = document.getElementById('cm-category-id');
    if (idEl) idEl.value = '';
    var nameEl = document.getElementById('cm-category-name');
    if (nameEl) nameEl.value = '';
    setModuleValue('restaurant');
    setModuleLocked(false);
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
    var module = row.getAttribute('data-category-module') || row.getAttribute('data-category-outlet') || 'restaurant';
    var idEl = document.getElementById('cm-category-id');
    if (idEl) idEl.value = id;
    var nameEl = document.getElementById('cm-category-name');
    if (nameEl) nameEl.value = name;
    setModuleValue(module);
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
        } else if (action === 'delete-category') {
          e.preventDefault();
          e.stopPropagation();
          var delRow = actionEl.closest('tr[data-category-id]');
          var delId = delRow ? delRow.getAttribute('data-category-id') || '' : '';
          var delName = delRow ? delRow.getAttribute('data-category-name') || 'this category' : 'this category';
          var delModule = delRow ? delRow.getAttribute('data-category-module') || '' : '';
          var itemCount = delRow ? Number(delRow.getAttribute('data-category-item-count') || 0) : 0;
          if (!delId) return;
          if (itemCount > 0 && isPosModule(delModule)) {
            global.alert('This category still has menu items. Remove or move them first.');
            return;
          }
          if (itemCount > 0 && (delModule === 'purchase' || delModule === 'expense')) {
            global.alert('This category is used on ' + (delModule === 'purchase' ? 'purchase' : 'expense') + ' bills. Remove or recategorize those entries first.');
            return;
          }
          var confirmMsg = 'Delete "' + delName + '"?';
          if (!global.confirm(confirmMsg)) return;
          var deleteForm = document.getElementById('cm-category-delete-form');
          var deleteIdEl = document.getElementById('cm-category-delete-id');
          if (!deleteForm || !deleteIdEl) return;
          deleteIdEl.value = delId;
          if (typeof deleteForm.requestSubmit === 'function') deleteForm.requestSubmit();
          else {
            var submitEv = new Event('submit', { bubbles: true, cancelable: true });
            if (deleteForm.dispatchEvent(submitEv)) deleteForm.submit();
          }
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
      setModuleLocked(modal.getAttribute('data-cm-editing') === '1');
      global.setTimeout(function () {
        var focusEl = document.getElementById('cm-category-name');
        if (focusEl) focusEl.focus();
      }, 0);
    }
  };
})(typeof window !== 'undefined' ? window : this);
