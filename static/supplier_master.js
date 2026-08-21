(function (global) {
  'use strict';

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
    var form = document.getElementById('sm-supplier-form');
    if (form) {
      global.setTimeout(function () {
        var focusEl = document.getElementById('supplier-name');
        if (focusEl) focusEl.focus();
      }, 0);
    }
  };
})(typeof window !== 'undefined' ? window : this);
