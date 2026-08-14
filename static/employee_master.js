/**
 * Employee Master list sorting (#emp-main-table).
 * Soft-nav clones tables via importNode; HTMLTableElement.tBodies / row.cells can
 * be empty on the reconstructed table, so we query real data rows and td children.
 */
(function (global) {
  'use strict';

  var TABLE_SEL =
    '#employee-master-page #emp-main-table, .md-master-embed--employee #emp-main-table';

  function cellAt(row, colIndex) {
    if (!row) return null;
    var kids = row.children;
    if (kids && kids.length) {
      return kids[colIndex] || null;
    }
    if (row.cells && row.cells.length) {
      return row.cells[colIndex] || null;
    }
    return null;
  }

  function rowSortValue(row, key, colIndex, type) {
    var raw = key ? row.getAttribute('data-sort-' + key) : null;
    if (raw == null || raw === '') {
      var cell = cellAt(row, colIndex);
      if (cell) {
        raw = cell.getAttribute('data-sort-value');
        if (raw == null || raw === '') raw = (cell.textContent || '').trim();
      }
    }
    if (type === 'number') {
      var n = Number(raw);
      return isFinite(n) ? n : 0;
    }
    return String(raw || '').trim();
  }

  function compareValues(av, bv, type) {
    if (type === 'number') return av - bv;
    return String(av).localeCompare(String(bv), undefined, {
      numeric: true,
      sensitivity: 'base',
    });
  }

  function bindEmpMasterTable(table) {
    if (!table || table.getAttribute('data-emp-sort-bound') === '1') return;
    table.setAttribute('data-emp-sort-bound', '1');

    function sortBy(th) {
      var key = th.getAttribute('data-sort') || '';
      var type = th.getAttribute('data-sort-type') || 'text';
      var colIndex = Array.prototype.indexOf.call(th.parentNode.children, th);
      if (colIndex < 0) return;
      var current = th.getAttribute('aria-sort');
      var dir = current === 'ascending' ? 'desc' : 'asc';

      var rows = Array.prototype.slice.call(
        table.querySelectorAll('tbody tr[data-sort-row]')
      );
      if (!rows.length) {
        rows = Array.prototype.slice.call(table.querySelectorAll('tbody tr'));
      }
      var tbody = rows.length ? rows[0].parentNode : null;
      if (!tbody) return;

      rows.sort(function (a, b) {
        var cmp = compareValues(
          rowSortValue(a, key, colIndex, type),
          rowSortValue(b, key, colIndex, type),
          type
        );
        return dir === 'asc' ? cmp : -cmp;
      });
      rows.forEach(function (row) {
        tbody.appendChild(row);
      });

      Array.prototype.forEach.call(table.querySelectorAll('th.pl-sortable'), function (header) {
        header.classList.remove('is-sorted-asc', 'is-sorted-desc');
        header.setAttribute('aria-sort', 'none');
      });
      th.classList.add(dir === 'asc' ? 'is-sorted-asc' : 'is-sorted-desc');
      th.setAttribute('aria-sort', dir === 'asc' ? 'ascending' : 'descending');
    }

    table.addEventListener('click', function (e) {
      var th = e.target && e.target.closest ? e.target.closest('th.pl-sortable') : null;
      if (!th || !table.contains(th)) return;
      sortBy(th);
    });
    table.addEventListener('keydown', function (e) {
      if (e.key !== 'Enter' && e.key !== ' ') return;
      var th = e.target && e.target.closest ? e.target.closest('th.pl-sortable') : null;
      if (!th || !table.contains(th)) return;
      e.preventDefault();
      sortBy(th);
    });
  }

  function initEmpMasterTableSort() {
    var tables = document.querySelectorAll(TABLE_SEL);
    if (!tables.length) {
      var fallback = document.getElementById('emp-main-table');
      if (
        fallback &&
        fallback.closest &&
        fallback.closest('#employee-master-page, .md-master-embed--employee')
      ) {
        tables = [fallback];
      }
    }
    Array.prototype.forEach.call(tables, bindEmpMasterTable);
  }

  global.initEmpMasterTableSort = initEmpMasterTableSort;
})(window);
