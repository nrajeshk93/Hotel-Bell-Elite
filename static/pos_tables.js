/**
 * Point of Sale — Tables page interactions (filter / view / KPI).
 * Soft-nav safe: expose window.initPosTablesPage and re-bind idempotently.
 * Floor tiles load from {posApiBase}/api/floor (SQLite); in-memory cache only.
 */
(function (global) {
  'use strict';

  var FLOOR_API = '/point-of-sale/api/floor';
  var FLOOR_SESSION_KEY = 'hbe_pos_floor_snapshot';
  var INVOICE_BY_TABLE_API = '/point-of-sale/api/invoices/by-table';
  var TRANSFER_TABLE_API = '/point-of-sale/api/invoices/transfer-table';
  var MERGE_TABLES_API = '/point-of-sale/api/invoices/merge-tables';
  var UNMERGE_TABLES_API = '/point-of-sale/api/floor/unmerge-tables';
  var INVOICE_PAGE_BASE = '/point-of-sale/invoice';
  var LEGACY_STORAGE_KEY = 'hbe_pos_floor_demo';
  var MIGRATE_FLAG = 'hbe_pos_floor_db_migrated';

  function resolvePosApiBase() {
    var el =
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

  function resolvePosOutlet() {
    var el =
      document.getElementById('pos-tables-page') ||
      document.querySelector('[data-pos-outlet]');
    var outlet = (el && el.getAttribute('data-pos-outlet')) || '';
    if (!outlet) {
      outlet =
        (window.location.pathname || '').indexOf('/bar-point-of-sale') === 0
          ? 'bar'
          : 'restaurant';
    }
    return outlet;
  }

  /** Cancellation Access (module tree) — edit KOT lines even after bill sent. */
  function canCancelKotLines() {
    var root =
      document.getElementById('pos-tables-page') ||
      document.querySelector('[data-pos-can-cancel-kot]');
    return !!(root && root.getAttribute('data-pos-can-cancel-kot') === '1');
  }

  function kotTokenLinesLocked(token) {
    return !!(token && token.customer_bill_sent && !canCancelKotLines());
  }

  function syncPosApiPaths() {
    var base = resolvePosApiBase();
    var outlet = resolvePosOutlet();
    FLOOR_API = base + '/api/floor';
    INVOICE_BY_TABLE_API = base + '/api/invoices/by-table';
    TRANSFER_TABLE_API = base + '/api/invoices/transfer-table';
    MERGE_TABLES_API = base + '/api/invoices/merge-tables';
    UNMERGE_TABLES_API = base + '/api/floor/unmerge-tables';
    INVOICE_PAGE_BASE = base + '/invoice';
    FLOOR_SESSION_KEY =
      outlet === 'bar' ? 'hbe_pos_floor_snapshot_bar' : 'hbe_pos_floor_snapshot';
    LEGACY_STORAGE_KEY =
      outlet === 'bar' ? 'hbe_pos_floor_demo_bar' : 'hbe_pos_floor_demo';
    MIGRATE_FLAG =
      outlet === 'bar' ? 'hbe_pos_floor_db_migrated_bar' : 'hbe_pos_floor_db_migrated';
  }

  var STATUS_KEYS = ['available', 'occupied', 'reserved', 'cleaning', 'inactive'];
  var STATUS_LABELS = {
    available: 'Available',
    occupied: 'Occupied',
    reserved: 'Reserved',
    cleaning: 'Cleaning',
    inactive: 'Inactive',
    blocked: 'Inactive'
  };
  var floorSaveTimer = null;
  var currentFloor = null;
  var currentKotPending = { pending_table_count: 0, pending_item_count: 0, tables: [] };

  function $(sel, root) {
    return (root || document).querySelector(sel);
  }

  function $all(sel, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(sel));
  }

  function normalize(value) {
    return String(value || '').trim().toLowerCase();
  }

  function escapeHtml(str) {
    return String(str || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function apiHeaders(extra) {
    var headers = {
      Accept: 'application/json',
      'X-Requested-With': 'XMLHttpRequest'
    };
    if (extra) {
      Object.keys(extra).forEach(function (k) {
        headers[k] = extra[k];
      });
    }
    return headers;
  }

  function emptyFloor() {
    return { areas: [], tables: [] };
  }

  function emptyKotPending() {
    return { pending_table_count: 0, pending_item_count: 0, tables: [] };
  }

  function normalizeKotPending(summary) {
    if (!summary || typeof summary !== 'object') return emptyKotPending();
    var tables = Array.isArray(summary.tables) ? summary.tables : [];
    return {
      pending_table_count: Number(summary.pending_table_count) || 0,
      pending_item_count: Number(summary.pending_item_count) || 0,
      tables: tables
    };
  }

  function paintKotPendingBanner(summary) {
    var banner = document.getElementById('pos-kot-pending-banner');
    if (!banner) return;
    var data = normalizeKotPending(summary);
    currentKotPending = data;
    var count = data.pending_table_count;
    if (count <= 0) {
      banner.hidden = true;
      banner.setAttribute('hidden', '');
      banner.classList.remove('is-shown');
      banner.setAttribute('aria-hidden', 'true');
      closeKotPendingModal();
      return;
    }
    banner.hidden = false;
    banner.removeAttribute('hidden');
    banner.classList.add('is-shown');
    banner.setAttribute('aria-hidden', 'false');
    var badge = banner.querySelector('[data-kot-pending-count]');
    var copy = banner.querySelector('[data-kot-pending-copy]');
    if (badge) badge.textContent = String(count);
    if (copy) {
      copy.textContent =
        count === 1
          ? '1 table has orders that are not yet sent to kitchen.'
          : count + ' tables have orders that are not yet sent to kitchen.';
    }
    var modal = document.getElementById('pos-kot-pending-modal');
    if (modal && !modal.hidden) paintKotPendingModal(data);
  }

  function formatKotPendingWhen(raw) {
    var s = String(raw || '').trim();
    if (!s) return { time: '—', date: '' };
    var d = new Date(s);
    if (isNaN(d.getTime())) {
      /* SQLite local "YYYY-MM-DD HH:MM:SS" */
      var m = s.match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/);
      if (m) {
        d = new Date(
          Number(m[1]),
          Number(m[2]) - 1,
          Number(m[3]),
          Number(m[4]),
          Number(m[5])
        );
      }
    }
    if (isNaN(d.getTime())) return { time: s, date: '' };
    var time = d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
    var date = d.toLocaleDateString(undefined, { day: '2-digit', month: 'short', year: 'numeric' });
    return { time: time, date: date };
  }

  function paintKotPendingModal(summary) {
    var data = normalizeKotPending(summary || currentKotPending);
    var rowsEl = document.getElementById('pos-kot-modal-rows');
    var emptyEl = document.getElementById('pos-kot-modal-empty');
    var subEl = document.getElementById('pos-kot-modal-sub');
    var metaEl = document.getElementById('pos-kot-modal-meta');
    var sendAllLabel = document.getElementById('pos-kot-modal-send-all-label');
    var sendAllBtn = document.getElementById('pos-kot-modal-send-all');
    var wrap = rowsEl && rowsEl.closest('.pos-kot-modal-table-wrap');
    var tables = data.tables || [];
    var count = tables.length;

    if (subEl) {
      subEl.textContent =
        count === 1
          ? '1 table has orders that are not yet sent to kitchen.'
          : count + ' tables have orders that are not yet sent to kitchen.';
    }
    if (metaEl) {
      metaEl.textContent =
        count === 0
          ? 'No pending tables'
          : 'Showing ' + count + ' of ' + count + ' pending table' + (count === 1 ? '' : 's');
    }
    if (sendAllLabel) {
      sendAllLabel.textContent = count ? 'Send All to Kitchen (' + count + ')' : 'Send All to Kitchen';
    }
    if (sendAllBtn) sendAllBtn.disabled = count === 0;

    if (!rowsEl) return;
    if (!count) {
      rowsEl.innerHTML = '';
      if (wrap) wrap.hidden = true;
      if (emptyEl) emptyEl.hidden = false;
      return;
    }
    if (wrap) wrap.hidden = false;
    if (emptyEl) emptyEl.hidden = true;

    var bellSvg =
      '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true">' +
      '<path d="M18 8a6 6 0 1 0-12 0c0 4-1.5 5.5-1.5 6.5h15C18.5 13.5 18 11 18 8z"/>' +
      '<path d="M10.5 17a1.5 1.5 0 0 0 3 0"/></svg>';

    rowsEl.innerHTML = tables
      .map(function (t) {
        var status = mapStatus(t.table_status || 'occupied');
        var seats = t.seats != null && t.seats !== '' ? String(t.seats) + ' Seater' : '';
        var when = formatKotPendingWhen(t.saved_at);
        var items = Number(t.pending_qty) > 0 ? Number(t.pending_qty) : Number(t.pending_items) || 0;
        var kotNo = t.kot_no || t.order_no || '—';
        return (
          '<tr data-kot-invoice-id="' +
          escapeHtml(t.invoice_id) +
          '">' +
          '<td>' +
          '<div class="pos-kot-table-cell-name">' +
          escapeHtml(t.name || 'Table') +
          '</div>' +
          (seats ? '<div class="pos-kot-table-cell-meta">' + escapeHtml(seats) + '</div>' : '') +
          '<span class="pos-kot-table-status is-' +
          escapeHtml(status) +
          '">' +
          escapeHtml(STATUS_LABELS[status] || status) +
          '</span>' +
          '</td>' +
          '<td><span class="pos-kot-table-kot">' +
          escapeHtml(kotNo) +
          '</span></td>' +
          '<td><span class="pos-kot-table-items">' +
          escapeHtml(items) +
          (items === 1 ? ' item' : ' items') +
          '</span></td>' +
          '<td><div class="pos-kot-table-time">' +
          escapeHtml(when.time) +
          (when.date ? '<small>' + escapeHtml(when.date) + '</small>' : '') +
          '</div></td>' +
          '<td>' +
          '<button type="button" class="pos-kot-row-send" data-kot-send-one="' +
          escapeHtml(t.invoice_id) +
          '">' +
          bellSvg +
          '<span>Send to Kitchen</span></button>' +
          '</td>' +
          '</tr>'
        );
      })
      .join('');
  }

  function openKotPendingModal() {
    var modal = document.getElementById('pos-kot-pending-modal');
    if (!modal) return;
    paintKotPendingModal(currentKotPending);
    modal.hidden = false;
    modal.removeAttribute('hidden');
    modal.setAttribute('aria-hidden', 'false');
    var closeBtn = modal.querySelector('.pos-kot-modal-close');
    if (closeBtn) closeBtn.focus();
  }

  function closeKotPendingModal() {
    var modal = document.getElementById('pos-kot-pending-modal');
    if (!modal || modal.hidden) return;
    modal.hidden = true;
    modal.setAttribute('hidden', '');
    modal.setAttribute('aria-hidden', 'true');
  }

  function refreshFloorAfterKot(kotPending) {
    paintKotPendingBanner(kotPending);
    loadFloorFromApi(function (data) {
      var root = document.getElementById('pos-tables-page');
      if (root) paintTablesPage(root, data || loadFloorDataCached());
    });
  }

  function sendKotForInvoice(invoiceId, btn) {
    if (!invoiceId) return Promise.resolve();
    if (btn) btn.disabled = true;
    return fetch(resolvePosApiBase() + '/api/invoices/' + encodeURIComponent(invoiceId) + '/send-kot', {
      method: 'POST',
      credentials: 'same-origin',
      headers: apiHeaders()
    })
      .then(function (res) {
        return res.json().catch(function () {
          return {};
        }).then(function (body) {
          return { ok: res.ok && body && body.ok, body: body || {} };
        });
      })
      .then(function (result) {
        if (!result.ok) {
          toast((result.body && result.body.error) || 'Could not send KOT.');
          return;
        }
        toast('KOT sent to kitchen.');
        refreshFloorAfterKot(result.body.kot_pending);
      })
      .catch(function () {
        toast('Could not send KOT. Check your connection and try again.');
      })
      .then(function () {
        if (btn) btn.disabled = false;
      });
  }

  function sendAllPendingKot(btn) {
    var count = ((currentKotPending && currentKotPending.tables) || []).length;
    if (!count) return;
    if (btn) btn.disabled = true;
    return fetch(resolvePosApiBase() + '/api/kot-pending/send-all', {
      method: 'POST',
      credentials: 'same-origin',
      headers: apiHeaders()
    })
      .then(function (res) {
        return res.json().catch(function () {
          return {};
        }).then(function (body) {
          return { ok: res.ok && body && body.ok, body: body || {} };
        });
      })
      .then(function (result) {
        if (!result.ok) {
          toast((result.body && result.body.error) || 'Could not send KOTs.');
          return;
        }
        var sent = Number(result.body.sent_count) || 0;
        toast(sent === 1 ? 'KOT sent for 1 table.' : 'KOT sent for ' + sent + ' tables.');
        refreshFloorAfterKot(result.body.kot_pending);
      })
      .catch(function () {
        toast('Could not send KOTs. Check your connection and try again.');
      })
      .then(function () {
        if (btn) btn.disabled = false;
      });
  }

  function bindKotPendingBanner() {
    var btn = document.getElementById('pos-kot-pending-view');
    if (btn && btn.getAttribute('data-bound') !== '1') {
      btn.setAttribute('data-bound', '1');
      btn.addEventListener('click', function () {
        var tables = (currentKotPending && currentKotPending.tables) || [];
        if (!tables.length) return;
        openKotPendingModal();
      });
    }

    var modal = document.getElementById('pos-kot-pending-modal');
    if (!modal || modal.getAttribute('data-bound') === '1') return;
    modal.setAttribute('data-bound', '1');

    modal.addEventListener('click', function (event) {
      if (event.target.closest('[data-kot-modal-close]')) {
        closeKotPendingModal();
        return;
      }
      var sendOne = event.target.closest('[data-kot-send-one]');
      if (sendOne && modal.contains(sendOne)) {
        event.preventDefault();
        sendKotForInvoice(sendOne.getAttribute('data-kot-send-one'), sendOne);
      }
    });

    var sendAll = document.getElementById('pos-kot-modal-send-all');
    if (sendAll) {
      sendAll.addEventListener('click', function () {
        sendAllPendingKot(sendAll);
      });
    }

    if (!document.__posKotModalEscBound) {
      document.__posKotModalEscBound = true;
      document.addEventListener('keydown', function (event) {
        if (event.key !== 'Escape') return;
        var open = document.getElementById('pos-kot-pending-modal');
        if (open && !open.hidden) closeKotPendingModal();
      });
    }
  }

  function readLegacyFloor() {
    return null;
  }

  function clearLegacyFloor() {
    try {
      localStorage.setItem(MIGRATE_FLAG, '1');
      localStorage.removeItem(LEGACY_STORAGE_KEY);
    } catch (err) {
      /* ignore */
    }
  }

  function readFloorSessionSnapshot() {
    try {
      var raw = sessionStorage.getItem(FLOOR_SESSION_KEY);
      if (!raw) return null;
      var parsed = JSON.parse(raw);
      if (
        parsed &&
        Array.isArray(parsed.areas) &&
        Array.isArray(parsed.tables)
      ) {
        return { areas: parsed.areas, tables: parsed.tables };
      }
    } catch (e) {}
    return null;
  }

  function writeFloorSessionSnapshot(data) {
    if (!data || !Array.isArray(data.areas) || !Array.isArray(data.tables)) return;
    try {
      sessionStorage.setItem(
        FLOOR_SESSION_KEY,
        JSON.stringify({ areas: data.areas, tables: data.tables })
      );
    } catch (e) {}
  }

  function loadFloorDataCached() {
    if (currentFloor && Array.isArray(currentFloor.areas) && Array.isArray(currentFloor.tables)) {
      return {
        areas: currentFloor.areas,
        tables: currentFloor.tables
      };
    }
    var snap = readFloorSessionSnapshot();
    if (snap) {
      currentFloor = snap;
      return {
        areas: snap.areas,
        tables: snap.tables
      };
    }
    clearLegacyFloor();
    currentFloor = emptyFloor();
    return currentFloor;
  }

  function putFloor(data) {
    return fetch(FLOOR_API, {
      method: 'PUT',
      credentials: 'same-origin',
      headers: apiHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({
        areas: data.areas || [],
        tables: data.tables || []
      })
    }).then(function (res) {
      return res.json().then(function (body) {
        return { ok: res.ok && body && body.ok, body: body };
      });
    });
  }

  function cancelPendingFloorSave() {
    if (floorSaveTimer) {
      clearTimeout(floorSaveTimer);
      floorSaveTimer = null;
    }
  }

  function saveFloorData(data) {
    currentFloor = data;
    cancelPendingFloorSave();
    floorSaveTimer = setTimeout(function () {
      floorSaveTimer = null;
      putFloor(data).catch(function () {
        /* keep in-memory state */
      });
    }, 280);
  }

  function refreshFloorAfterMutation(done) {
    cancelPendingFloorSave();
    loadFloorFromApi(function (data) {
      var root = document.getElementById('pos-tables-page');
      if (root) paintTablesPage(root, data || loadFloorDataCached());
      if (typeof done === 'function') done(data);
    });
  }

  function loadFloorFromApi(done) {
    fetch(FLOOR_API, {
      method: 'GET',
      credentials: 'same-origin',
      headers: apiHeaders()
    })
      .then(function (res) {
        return res.json().catch(function () {
          return null;
        });
      })
      .then(function (data) {
        clearLegacyFloor();
        var payload;
        if (data && data.ok && Array.isArray(data.areas) && Array.isArray(data.tables)) {
          payload = { areas: data.areas, tables: data.tables };
          currentFloor = payload;
          writeFloorSessionSnapshot(payload);
          paintKotPendingBanner(data.kot_pending);
          paintInvoiceKpis(document.getElementById('pos-tables-page'), data);
        } else {
          payload = emptyFloor();
          currentFloor = payload;
          paintKotPendingBanner(emptyKotPending());
          paintInvoiceKpis(document.getElementById('pos-tables-page'), {
            sales_count: 0,
            sales_total: 0,
            unsettled_count: 0,
            unsettled_total: 0
          });
        }
        if (typeof done === 'function') done(payload);
      })
      .catch(function () {
        paintKotPendingBanner(emptyKotPending());
        if (typeof done === 'function') done(emptyFloor());
      });
  }

  function toast(msg) {
    var el = document.getElementById('pos-tables-toast');
    if (!el) return;
    el.hidden = false;
    el.textContent = msg;
    el.classList.add('is-visible');
    clearTimeout(toast._t);
    toast._t = setTimeout(function () {
      el.classList.remove('is-visible');
      setTimeout(function () {
        el.hidden = true;
      }, 200);
    }, 2400);
  }

  function invoiceUrlForTable(name) {
    var table = String(name || '').trim() || 'Table';
    return INVOICE_PAGE_BASE + '?table=' + encodeURIComponent(table);
  }

  function navigateToInvoice(name) {
    var url = invoiceUrlForTable(name);
    if (typeof global.deNavigateWithTransition === 'function') {
      global.deNavigateWithTransition(url);
      return;
    }
    global.location.href = url;
  }

  function navigateToInvoiceById(invoiceId) {
    var id = String(invoiceId || '').trim();
    if (!id) return;
    var url = INVOICE_PAGE_BASE + '?invoice=' + encodeURIComponent(id);
    if (typeof global.deNavigateWithTransition === 'function') {
      global.deNavigateWithTransition(url);
      return;
    }
    global.location.href = url;
  }

  var transferSourceTable = '';
  var transferBusy = false;

  function transferModalEl() {
    return document.getElementById('pos-transfer-table-modal');
  }

  function setTransferError(msg) {
    var el = document.getElementById('pos-transfer-table-error');
    if (!el) return;
    if (!msg) {
      el.hidden = true;
      el.textContent = '';
      return;
    }
    el.hidden = false;
    el.textContent = msg;
  }

  function closeTransferTableModal() {
    var modal = transferModalEl();
    if (!modal) return;
    modal.hidden = true;
    transferSourceTable = '';
    transferBusy = false;
    setTransferError('');
    var confirmBtn = document.getElementById('pos-transfer-table-confirm');
    if (confirmBtn) confirmBtn.disabled = false;
    if (typeof global.resetEpListbox === 'function') {
      global.resetEpListbox('pos-transfer-dest', '', 'Select table…');
    }
  }

  function availableTransferDestinations(sourceName) {
    var source = normalize(sourceName);
    var tables = ((currentFloor && currentFloor.tables) || []).slice();
    return tables
      .filter(function (t) {
        var name = String(t.name || '').trim();
        if (!name || normalize(name) === source) return false;
        return mapStatus(t.status) === 'available';
      })
      .sort(function (a, b) {
        return String(a.name || '').localeCompare(String(b.name || ''), undefined, { numeric: true });
      });
  }

  function populateTransferDestinations(sourceName) {
    var optionsWrap = document.getElementById('pos-transfer-dest-options');
    if (!optionsWrap) return 0;
    var dests = availableTransferDestinations(sourceName);
    var html = '';
    dests.forEach(function (t) {
      var name = String(t.name || 'Table');
      var seats = t.seats != null ? t.seats : '';
      var label = seats !== '' ? name + ' (' + seats + ' Seats)' : name;
      html +=
        '<button type="button" class="se-filter-listbox-option" role="option" data-value="' +
        escapeHtml(name) +
        '" data-name="' +
        escapeHtml(name.toLowerCase()) +
        '" data-label="' +
        escapeHtml(label) +
        '" aria-selected="false">' +
        escapeHtml(label) +
        '</button>';
    });
    if (!dests.length) {
      html =
        '<div class="se-filter-listbox-status" role="presentation">No available tables to transfer to.</div>';
    }
    optionsWrap.innerHTML = html;
    if (typeof global.resetEpListbox === 'function') {
      global.resetEpListbox('pos-transfer-dest', '', 'Select table…');
    } else {
      var input = document.getElementById('pos-transfer-dest');
      var valueEl = document.getElementById('pos-transfer-dest-value');
      if (input) input.value = '';
      if (valueEl) {
        valueEl.textContent = 'Select table…';
        valueEl.classList.add('is-placeholder');
      }
    }
    if (typeof global.initEpListboxes === 'function') {
      global.initEpListboxes();
    }
    return dests.length;
  }

  function showTransferTableModal(sourceName) {
    var modal = transferModalEl();
    if (!modal) return;
    transferSourceTable = sourceName;
    var lead = document.getElementById('pos-transfer-table-lead');
    if (lead) {
      lead.innerHTML =
        'Move the open bill from <strong>' + escapeHtml(sourceName) + '</strong> to another table.';
    }
    setTransferError('');
    var count = populateTransferDestinations(sourceName);
    modal.hidden = false;
    if (!count) {
      setTransferError('No available tables to transfer to.');
    }
    var trigger = document.getElementById('pos-transfer-dest-trigger');
    if (trigger && count) {
      setTimeout(function () {
        try {
          trigger.focus();
        } catch (err) {}
      }, 0);
    }
  }

  function openTransferTableModal(root, sourceName) {
    var name = String(sourceName || '').trim();
    if (!name) return;
    fetch(INVOICE_BY_TABLE_API + '?table=' + encodeURIComponent(name), {
      method: 'GET',
      credentials: 'same-origin',
      headers: apiHeaders()
    })
      .then(function (res) {
        return res.json().catch(function () {
          return null;
        });
      })
      .then(function (data) {
        if (!data || !data.ok || !data.invoice) {
          toast('No open bill on ' + name + ' to transfer.');
          return;
        }
        showTransferTableModal(data.invoice.table_label || data.invoice.table || name);
      })
      .catch(function () {
        toast('Could not check the open bill for ' + name + '.');
      });
  }

  function confirmTransferTable() {
    if (transferBusy) return;
    var fromTable = String(transferSourceTable || '').trim();
    var destInput = document.getElementById('pos-transfer-dest');
    var toTable = destInput ? String(destInput.value || '').trim() : '';
    if (!fromTable) {
      closeTransferTableModal();
      return;
    }
    if (!toTable) {
      setTransferError('Select a destination table.');
      return;
    }
    transferBusy = true;
    setTransferError('');
    var confirmBtn = document.getElementById('pos-transfer-table-confirm');
    if (confirmBtn) confirmBtn.disabled = true;
    fetch(TRANSFER_TABLE_API, {
      method: 'POST',
      credentials: 'same-origin',
      headers: apiHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ from_table: fromTable, to_table: toTable })
    })
      .then(function (res) {
        return res.json().catch(function () {
          return null;
        }).then(function (data) {
          return { okHttp: res.ok, data: data };
        });
      })
      .then(function (result) {
        transferBusy = false;
        if (confirmBtn) confirmBtn.disabled = false;
        var data = result && result.data;
        if (!result || !result.okHttp || !data || !data.ok) {
          setTransferError((data && data.error) || 'Transfer failed.');
          return;
        }
        closeTransferTableModal();
        refreshFloorAfterMutation(function () {
          toast('Transferred bill to ' + toTable + '.');
        });
      })
      .catch(function () {
        transferBusy = false;
        if (confirmBtn) confirmBtn.disabled = false;
        setTransferError('Transfer failed. Try again.');
      });
  }

  function bindTransferTableModal() {
    var modal = transferModalEl();
    if (!modal || modal.getAttribute('data-bound') === '1') return;
    modal.setAttribute('data-bound', '1');
    modal.addEventListener('click', function (event) {
      if (event.target.closest('[data-transfer-modal-close]')) {
        event.preventDefault();
        closeTransferTableModal();
      }
    });
    var confirmBtn = document.getElementById('pos-transfer-table-confirm');
    if (confirmBtn) {
      confirmBtn.addEventListener('click', function (event) {
        event.preventDefault();
        confirmTransferTable();
      });
    }
    if (!document.__posTransferEscBound) {
      document.__posTransferEscBound = true;
      document.addEventListener('keydown', function (event) {
        if (event.key !== 'Escape') return;
        var open = transferModalEl();
        if (open && !open.hidden) closeTransferTableModal();
      });
    }
  }

  var mergeSourceTable = '';
  var mergePickSource = false;
  var mergeBusy = false;

  function mergeModalEl() {
    return document.getElementById('pos-merge-tables-modal');
  }

  function setMergeError(msg) {
    var el = document.getElementById('pos-merge-tables-error');
    if (!el) return;
    if (!msg) {
      el.hidden = true;
      el.textContent = '';
      return;
    }
    el.hidden = false;
    el.textContent = msg;
  }

  function mergeTableCandidates(excludeName, opts) {
    /* Any floor status by default. Pass requireOccupied to limit to tables
       that likely hold an open bill (source picker). */
    opts = opts || {};
    var exclude = normalize(excludeName);
    var tables = ((currentFloor && currentFloor.tables) || []).slice();
    return tables
      .filter(function (t) {
        var name = String(t.name || '').trim();
        if (!name) return false;
        if (exclude && normalize(name) === exclude) return false;
        if (opts.requireOccupied && mapStatus(t.status) !== 'occupied') return false;
        return true;
      })
      .sort(function (a, b) {
        return String(a.name || '').localeCompare(String(b.name || ''), undefined, {
          numeric: true,
          sensitivity: 'base'
        });
      });
  }

  function renderMergeOptionsHtml(tables, emptyMsg) {
    if (!tables.length) {
      return '<div class="se-filter-listbox-status" role="presentation">' + escapeHtml(emptyMsg) + '</div>';
    }
    return tables
      .map(function (t) {
        var name = String(t.name || 'Table');
        var seats = t.seats != null ? t.seats : '';
        var status = mapStatus(t.status);
        var statusLabel = STATUS_LABELS[status] || status;
        var label = name;
        if (seats !== '') label += ' (' + seats + ' Seats)';
        if (statusLabel) label += ' · ' + statusLabel;
        return (
          '<button type="button" class="se-filter-listbox-option" role="option" data-value="' +
          escapeHtml(name) +
          '" data-name="' +
          escapeHtml(name.toLowerCase()) +
          '" data-label="' +
          escapeHtml(label) +
          '" aria-selected="false">' +
          escapeHtml(label) +
          '</button>'
        );
      })
      .join('');
  }

  function resetMergeListbox(listboxId, inputId, valueId, placeholder) {
    if (typeof global.resetEpListbox === 'function') {
      global.resetEpListbox(listboxId, '', placeholder);
      return;
    }
    var input = document.getElementById(inputId);
    var valueEl = document.getElementById(valueId);
    if (input) input.value = '';
    if (valueEl) {
      valueEl.textContent = placeholder;
      valueEl.classList.add('is-placeholder');
    }
  }

  function closeMergeTablesModal() {
    var modal = mergeModalEl();
    if (!modal) return;
    modal.hidden = true;
    mergeSourceTable = '';
    mergePickSource = false;
    mergeBusy = false;
    setMergeError('');
    var confirmBtn = document.getElementById('pos-merge-tables-confirm');
    if (confirmBtn) confirmBtn.disabled = false;
    var sourceField = document.getElementById('pos-merge-source-field');
    if (sourceField) sourceField.hidden = true;
    resetMergeListbox('pos-merge-source', 'pos-merge-source', 'pos-merge-source-value', 'Select table…');
    resetMergeListbox('pos-merge-dest', 'pos-merge-dest', 'pos-merge-dest-value', 'Select table…');
  }

  function populateMergeSourceOptions(excludeName) {
    var optionsWrap = document.getElementById('pos-merge-source-options');
    if (!optionsWrap) return 0;
    /* Any other floor table — visual merge does not require an open bill. */
    var sources = mergeTableCandidates(excludeName || '');
    optionsWrap.innerHTML = renderMergeOptionsHtml(
      sources,
      'No other tables on the floor to merge.'
    );
    resetMergeListbox('pos-merge-source', 'pos-merge-source', 'pos-merge-source-value', 'Select table…');
    if (typeof global.initEpListboxes === 'function') global.initEpListboxes();
    return sources.length;
  }

  function populateMergeDestinations(sourceName) {
    var optionsWrap = document.getElementById('pos-merge-dest-options');
    if (!optionsWrap) return 0;
    var dests = mergeTableCandidates(sourceName);
    optionsWrap.innerHTML = renderMergeOptionsHtml(
      dests,
      'No other tables to merge into.'
    );
    resetMergeListbox('pos-merge-dest', 'pos-merge-dest', 'pos-merge-dest-value', 'Select table…');
    if (typeof global.initEpListboxes === 'function') global.initEpListboxes();
    return dests.length;
  }

  function showMergeTablesModal(sourceName, pickSource, prefDestName) {
    var modal = mergeModalEl();
    if (!modal) return;
    mergePickSource = !!pickSource;
    mergeSourceTable = pickSource ? '' : String(sourceName || '').trim();
    var preferredDest = String(prefDestName || '').trim();
    var sourceField = document.getElementById('pos-merge-source-field');
    if (sourceField) sourceField.hidden = !mergePickSource;
    var lead = document.getElementById('pos-merge-tables-lead');
    if (lead) {
      if (mergePickSource && preferredDest) {
        lead.innerHTML =
          'Join another table with <strong>' +
          escapeHtml(preferredDest) +
          '</strong> — pick Table 2 (or any other table) below. An open bill is optional.';
      } else if (mergePickSource) {
        lead.textContent =
          'Pick two tables to join on the floor. If one has an open bill, it stays on Merge into.';
      } else {
        lead.innerHTML =
          'Merge <strong>' +
          escapeHtml(mergeSourceTable) +
          '</strong> into another table — empty tables are allowed.';
      }
    }
    setMergeError('');
    var destCount = 0;
    if (mergePickSource) {
      var sourceCount = populateMergeSourceOptions(preferredDest);
      destCount = populateMergeDestinations(preferredDest || '');
      if (preferredDest) {
        setMergeListboxValue('pos-merge-dest', preferredDest);
      }
      if (sourceCount < 1) {
        setMergeError('No other tables on the floor to merge with.');
      }
    } else {
      destCount = populateMergeDestinations(mergeSourceTable);
      if (!destCount) {
        setMergeError('No other tables to merge into.');
      }
    }
    modal.hidden = false;
    var focusId = mergePickSource ? 'pos-merge-source-trigger' : 'pos-merge-dest-trigger';
    var trigger = document.getElementById(focusId);
    if (trigger && (mergePickSource || destCount)) {
      setTimeout(function () {
        try {
          trigger.focus();
        } catch (err) {}
      }, 0);
    }
  }

  function setMergeListboxValue(fieldId, tableName) {
    var name = String(tableName || '').trim();
    if (!name) return;
    var tables = (currentFloor && currentFloor.tables) || [];
    var match = null;
    for (var i = 0; i < tables.length; i++) {
      if (normalize(tables[i].name) === normalize(name)) {
        match = tables[i];
        break;
      }
    }
    var label = name;
    if (match) {
      var seats = match.seats != null ? match.seats : '';
      var status = mapStatus(match.status);
      var statusLabel = STATUS_LABELS[status] || status;
      if (seats !== '') label += ' (' + seats + ' Seats)';
      if (statusLabel) label += ' · ' + statusLabel;
    }
    if (typeof global.resetEpListbox === 'function') {
      global.resetEpListbox(fieldId, name, label);
      return;
    }
    var input = document.getElementById(fieldId);
    var valueEl = document.getElementById(fieldId + '-value');
    if (input) input.value = name;
    if (valueEl) {
      valueEl.textContent = label;
      valueEl.classList.remove('is-placeholder');
    }
  }

  function openMergeTablesModal(root, sourceName) {
    var name = String(sourceName || '').trim();
    if (!name) {
      showMergeTablesModal('', true);
      return;
    }
    fetch(INVOICE_BY_TABLE_API + '?table=' + encodeURIComponent(name), {
      method: 'GET',
      credentials: 'same-origin',
      headers: apiHeaders()
    })
      .then(function (res) {
        return res.json().catch(function () {
          return null;
        });
      })
      .then(function (data) {
        if (!data || !data.ok || !data.invoice) {
          /* Available / reserved / etc. without a bill — this table is the
             destination; staff pick which occupied table to bring in. */
          showMergeTablesModal('', true, name);
          return;
        }
        showMergeTablesModal(data.invoice.table_label || data.invoice.table || name, false);
      })
      .catch(function () {
        showMergeTablesModal('', true, name);
      });
  }

  function confirmMergeTables() {
    if (mergeBusy) return;
    var sourceInput = document.getElementById('pos-merge-source');
    var fromTable = mergePickSource
      ? sourceInput
        ? String(sourceInput.value || '').trim()
        : ''
      : String(mergeSourceTable || '').trim();
    var destInput = document.getElementById('pos-merge-dest');
    var toTable = destInput ? String(destInput.value || '').trim() : '';
    if (!fromTable) {
      setMergeError(mergePickSource ? 'Select a source table.' : 'Source table is missing.');
      return;
    }
    if (!toTable) {
      setMergeError('Select a destination table.');
      return;
    }
    if (normalize(fromTable) === normalize(toTable)) {
      setMergeError('Choose a different destination table.');
      return;
    }
    mergeBusy = true;
    setMergeError('');
    var confirmBtn = document.getElementById('pos-merge-tables-confirm');
    if (confirmBtn) confirmBtn.disabled = true;
    fetch(MERGE_TABLES_API, {
      method: 'POST',
      credentials: 'same-origin',
      headers: apiHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ from_table: fromTable, to_table: toTable })
    })
      .then(function (res) {
        return res.json().catch(function () {
          return null;
        }).then(function (data) {
          return { okHttp: res.ok, data: data };
        });
      })
      .then(function (result) {
        mergeBusy = false;
        if (confirmBtn) confirmBtn.disabled = false;
        var data = result && result.data;
        if (!result || !result.okHttp || !data || !data.ok) {
          setMergeError((data && data.error) || 'Merge failed.');
          return;
        }
        closeMergeTablesModal();
        var landed =
          (data.invoice && (data.invoice.table_label || data.invoice.table)) || toTable;
        refreshFloorAfterMutation(function () {
          toast('Merged into ' + landed + '.');
        });
      })
      .catch(function () {
        mergeBusy = false;
        if (confirmBtn) confirmBtn.disabled = false;
        setMergeError('Merge failed. Try again.');
      });
  }

  var unmergeBusy = false;

  function confirmUnmergeTables(tableName) {
    var name = String(tableName || '').trim();
    if (!name || unmergeBusy) return;
    unmergeBusy = true;
    fetch(UNMERGE_TABLES_API, {
      method: 'POST',
      credentials: 'same-origin',
      headers: apiHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ table: name })
    })
      .then(function (res) {
        return res.json().catch(function () {
          return null;
        }).then(function (data) {
          return { okHttp: res.ok, data: data };
        });
      })
      .then(function (result) {
        unmergeBusy = false;
        var data = result && result.data;
        if (!result || !result.okHttp || !data || !data.ok) {
          toast((data && data.error) || 'Unmerge failed.');
          return;
        }
        refreshFloorAfterMutation(function () {
          var label = data.label || name;
          toast('Unmerged ' + label + '.');
        });
      })
      .catch(function () {
        unmergeBusy = false;
        toast('Unmerge failed. Try again.');
      });
  }

  function bindMergeTablesModal() {
    var modal = mergeModalEl();
    if (!modal || modal.getAttribute('data-bound') === '1') return;
    modal.setAttribute('data-bound', '1');
    modal.addEventListener('click', function (event) {
      if (event.target.closest('[data-merge-modal-close]')) {
        event.preventDefault();
        closeMergeTablesModal();
      }
    });
    var confirmBtn = document.getElementById('pos-merge-tables-confirm');
    if (confirmBtn) {
      confirmBtn.addEventListener('click', function (event) {
        event.preventDefault();
        confirmMergeTables();
      });
    }
    var sourceListbox = document.getElementById('pos-merge-source-listbox');
    if (sourceListbox && sourceListbox.getAttribute('data-merge-source-bound') !== '1') {
      sourceListbox.setAttribute('data-merge-source-bound', '1');
      sourceListbox.addEventListener('click', function (event) {
        var opt = event.target.closest('.se-filter-listbox-option');
        if (!opt || !sourceListbox.contains(opt)) return;
        var value = opt.getAttribute('data-value') || '';
        setTimeout(function () {
          mergeSourceTable = value;
          var destCount = populateMergeDestinations(value);
          if (!destCount) {
            setMergeError('No other tables to merge into.');
          } else {
            setMergeError('');
          }
        }, 0);
      });
    }
    if (!document.__posMergeEscBound) {
      document.__posMergeEscBound = true;
      document.addEventListener('keydown', function (event) {
        if (event.key !== 'Escape') return;
        var open = mergeModalEl();
        if (open && !open.hidden) closeMergeTablesModal();
      });
    }
  }

  function bindTableMergeQuickCard() {
    var btn = document.getElementById('pos-quick-table-merge');
    if (!btn || btn.getAttribute('data-bound') === '1') return;
    btn.setAttribute('data-bound', '1');
    btn.addEventListener('click', function (event) {
      event.preventDefault();
      openMergeTablesModal(document.getElementById('pos-tables-page'), '');
    });
  }

  var tableMenuScrollGuardUntil = 0;

  function restoreTableMenuHome(menu) {
    if (!menu) return;
    var home = menu.__posMenuHome;
    if (home && menu.parentNode !== home) {
      try {
        home.appendChild(menu);
      } catch (err) {}
    }
    menu.__posMenuHome = null;
    menu.__posMenuTile = null;
  }

  function closeTableMenu() {
    $all('.pos-table-menu').forEach(function (menu) {
      menu.hidden = true;
      menu.classList.remove('is-fixed-open');
      menu.style.position = '';
      menu.style.top = '';
      menu.style.left = '';
      menu.style.right = '';
      menu.style.bottom = '';
      menu.style.zIndex = '';
      restoreTableMenuHome(menu);
    });
    $all('.pos-table-more[aria-expanded="true"]').forEach(function (btn) {
      btn.setAttribute('aria-expanded', 'false');
    });
    $all('.pos-table-tile.is-menu-open').forEach(function (tile) {
      tile.classList.remove('is-menu-open');
    });
  }

  function positionTableMenu(btn, menu) {
    /* Fixed to the viewport (menu is portaled to body) so tile transforms /
       overflow:auto shells cannot clip or steal hits. */
    var rect = btn.getBoundingClientRect();
    menu.style.position = 'fixed';
    menu.style.right = 'auto';
    menu.style.bottom = 'auto';
    menu.style.zIndex = '5000';
    menu.classList.add('is-fixed-open');

    var pad = 8;
    var width = menu.offsetWidth || 156;
    var height = menu.offsetHeight || 180;
    var left = rect.right - width;
    if (left < pad) left = pad;
    if (left + width > window.innerWidth - pad) {
      left = Math.max(pad, window.innerWidth - width - pad);
    }
    var top = rect.bottom + 4;
    if (top + height > window.innerHeight - pad) {
      top = Math.max(pad, rect.top - height - 4);
    }
    menu.style.left = left + 'px';
    menu.style.top = top + 'px';
  }

  function openTableMenu(btn, tile) {
    closeTableMenu();
    var menu = tile && tile.querySelector('.pos-table-menu');
    if (!menu || !btn) return;
    /* Portal out of the tile — hover transform creates a containing block that
       breaks position:fixed and makes the menu appear "not clickable". */
    menu.__posMenuHome = menu.parentNode;
    menu.__posMenuTile = tile;
    var host = document.getElementById('de-fs-app') || document.body;
    host.appendChild(menu);
    tile.classList.add('is-menu-open');
    menu.hidden = false;
    btn.setAttribute('aria-expanded', 'true');
    positionTableMenu(btn, menu);
    /* Opening can nudge scrollIntoView / layout; ignore that brief scroll. */
    tableMenuScrollGuardUntil = Date.now() + 450;
  }

  function tileForTableMenu(menu) {
    if (!menu) return null;
    if (menu.__posMenuTile && menu.__posMenuTile.isConnected) return menu.__posMenuTile;
    if (menu.__posMenuHome) return menu.__posMenuHome.closest('[data-table-tile]');
    return menu.closest('[data-table-tile]');
  }

  function setTableStatus(root, tableId, nextStatus) {
    if (!tableId || !nextStatus) return;
    var data = loadFloorDataCached();
    var tables = data.tables || [];
    var i;
    var found = false;
    for (i = 0; i < tables.length; i++) {
      if (tables[i].id === tableId) {
        tables[i].status = mapStatus(nextStatus);
        found = true;
        break;
      }
    }
    if (!found) return;
    saveFloorData(data);
    renderFloor(root, data);
    updateKpis(root);
    applyFilters(root);
  }

  function mapStatus(status) {
    var s = normalize(status) || 'available';
    if (s === 'blocked') return 'inactive';
    return s;
  }

  function shapeIcon(shape) {
    if (shape === 'round') {
      return '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="7"/><path d="M12 5v2M12 17v2M5 12h2M17 12h2"/></svg>';
    }
    if (shape === 'rect') {
      return '<svg viewBox="0 0 24 24"><rect x="4" y="8" width="16" height="8" rx="2"/><path d="M7 8V6M17 8V6M7 16v2M17 16v2"/></svg>';
    }
    return '<svg viewBox="0 0 24 24"><rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 6V4M15 6V4M9 18v2M15 18v2"/></svg>';
  }

  function tableGuestName(table) {
    if (!table || typeof table !== 'object') return '';
    var name = String(table.customerName || table.customer_name || '').trim();
    if (!name || name.toLowerCase() === 'guest') return '';
    return name;
  }

  function tableSubtitle(table) {
    var status = mapStatus(table && table.status);
    var guest = tableGuestName(table);
    if (guest && status === 'occupied') {
      return { text: guest, isGuest: true };
    }
    var seats =
      table && table.seats != null && table.seats !== ''
        ? table.seats
        : table && table.mergedSeats != null && table.mergedSeats !== ''
          ? table.mergedSeats
          : '';
    if (seats !== '') {
      return { text: String(seats) + ' Seater', isGuest: false };
    }
    return null;
  }

  function areaNameById(areas, areaId) {
    var i;
    for (i = 0; i < areas.length; i++) {
      if (areas[i].id === areaId) return areas[i].name || areas[i].id;
    }
    return areaId || 'Floor';
  }

  function statusFilterValue(root) {
    var status = normalize(($('#pos-tables-status-filter', root) || {}).value);
    return !status || status === 'all' ? '' : status;
  }

  function updateKpis(root) {
    var tiles = $all('[data-table-tile]', root);
    var counts = { total: tiles.length };
    var availableSeats = 0;
    STATUS_KEYS.forEach(function (key) {
      counts[key] = 0;
    });
    tiles.forEach(function (tile) {
      var status = normalize(tile.getAttribute('data-status'));
      if (counts[status] != null) counts[status] += 1;
      if (status === 'available') {
        var seats = parseInt(tile.getAttribute('data-seats'), 10);
        if (!isNaN(seats) && seats > 0) availableSeats += seats;
      }
    });
    /* "available" KPI shows dining seat capacity on free tables, not table count */
    counts.available = availableSeats;
    $all('.pos-kpi', root).forEach(function (card) {
      var key = card.getAttribute('data-kpi');
      var el = card.querySelector('[data-kpi-value]');
      if (!el || !key || key === 'sales' || key === 'unsettled') return;
      el.textContent = String(counts[key] != null ? counts[key] : 0);
    });
  }

  function summarizeSalesFromInvoices(invoices) {
    var total = 0;
    var count = 0;
    (invoices || []).forEach(function (inv) {
      count += 1;
      total += Number((inv && inv.grand_total) || 0) || 0;
    });
    return {
      sales_count: count,
      sales_total: Math.round(total * 100) / 100
    };
  }

  function summarizeUnsettledFromInvoices(invoices) {
    var total = 0;
    var count = 0;
    (invoices || []).forEach(function (inv) {
      var statusKey = String((inv && inv.status) || 'open').toLowerCase();
      if (statusKey === 'closed' || statusKey === 'cancelled') return;
      count += 1;
      total += Number((inv && inv.grand_total) || 0) || 0;
    });
    return {
      unsettled_count: count,
      unsettled_total: Math.round(total * 100) / 100
    };
  }

  function paintMoneyKpiCard(card, total, count, label) {
    if (!card) return;
    var valueEl = card.querySelector('[data-kpi-value]');
    var metaEl = card.querySelector('[data-kpi-meta]');
    if (valueEl) {
      valueEl.setAttribute('data-amount', String(total));
      valueEl.textContent = formatKpiMoney(total);
    }
    if (metaEl) {
      metaEl.textContent =
        count === 1 ? '1 invoice' : count + ' invoices';
    }
    card.setAttribute(
      'aria-label',
      label +
        ' ' +
        formatKpiMoney(total) +
        ', ' +
        (count === 1 ? '1 invoice' : count + ' invoices')
    );
  }

  function paintUnsettledKpi(root, payload) {
    root = root || document.getElementById('pos-tables-page');
    if (!root) return;
    var card = root.querySelector('.pos-kpi[data-kpi="unsettled"]');
    var section = root.querySelector('.pos-tables-kpis');
    if (!card) return;
    var count =
      payload && payload.unsettled_count != null
        ? Number(payload.unsettled_count) || 0
        : 0;
    var total =
      payload && payload.unsettled_total != null
        ? Number(payload.unsettled_total) || 0
        : 0;
    if (
      payload &&
      Array.isArray(payload.invoices) &&
      payload.unsettled_count == null
    ) {
      var summed = summarizeUnsettledFromInvoices(payload.invoices);
      count = summed.unsettled_count;
      total = summed.unsettled_total;
    }
    var show = count > 0;
    card.hidden = !show;
    if (show) {
      card.removeAttribute('hidden');
    } else {
      card.setAttribute('hidden', '');
    }
    if (section) section.classList.toggle('has-unsettled-kpi', show);
    if (show) paintMoneyKpiCard(card, total, count, 'Unsettled');
    card.classList.toggle('is-clickable', show);
    if (show) {
      card.setAttribute(
        'title',
        'View unsettled invoices'
      );
    } else {
      card.removeAttribute('title');
    }
  }

  function paintSalesKpi(root, payload) {
    root = root || document.getElementById('pos-tables-page');
    if (!root) return;
    var card = root.querySelector('.pos-kpi[data-kpi="sales"]');
    if (!card) return;
    var count =
      payload && payload.sales_count != null
        ? Number(payload.sales_count) || 0
        : payload && payload.invoice_count != null
          ? Number(payload.invoice_count) || 0
          : 0;
    var total =
      payload && payload.sales_total != null
        ? Number(payload.sales_total) || 0
        : 0;
    if (
      payload &&
      Array.isArray(payload.invoices) &&
      payload.sales_total == null
    ) {
      var summed = summarizeSalesFromInvoices(payload.invoices);
      count = summed.sales_count;
      total = summed.sales_total;
    }
    paintMoneyKpiCard(card, total, count, 'Total sales');
  }

  function paintInvoiceKpis(root, payload) {
    paintUnsettledKpi(root, payload);
    paintSalesKpi(root, payload);
  }

  function applyFilters(root) {
    var area = normalize(($('#pos-area-pills .pos-area-pill.is-active', root) || {}).getAttribute
      ? $('#pos-area-pills .pos-area-pill.is-active', root).getAttribute('data-area')
      : '');
    var statusFilter = statusFilterValue(root);
    var query = normalize(($('#pos-tables-search', root) || {}).value);
    var tiles = $all('[data-table-tile]', root);
    var visible = 0;

    tiles.forEach(function (tile) {
      var tileArea = normalize(tile.getAttribute('data-area'));
      var tileStatus = normalize(tile.getAttribute('data-status'));
      var tileName = normalize(tile.getAttribute('data-name'));
      var tileDisplay = normalize(tile.getAttribute('data-display-name'));
      var tileSearch = normalize(tile.getAttribute('data-search-names'));
      var guestName = normalize(tile.getAttribute('data-guest-name'));
      var seats = normalize(tile.getAttribute('data-seats'));
      var matchArea = !area || tileArea === area;
      var matchStatus = !statusFilter || tileStatus === statusFilter;
      var matchQuery =
        !query ||
        tileName.indexOf(query) !== -1 ||
        tileDisplay.indexOf(query) !== -1 ||
        tileSearch.indexOf(query) !== -1 ||
        guestName.indexOf(query) !== -1 ||
        seats.indexOf(query) !== -1;
      var show = matchArea && matchStatus && matchQuery;
      tile.classList.toggle('is-hidden', !show);
      if (show) visible += 1;
    });

    $all('.pos-floor-section', root).forEach(function (section) {
      var any = section.querySelector('[data-table-tile]:not(.is-hidden)');
      section.hidden = !any;
    });

    var filteredEmpty = $('#pos-floor-filtered-empty', root);
    var floor = $('#pos-floor', root);
    var hasTiles = tiles.length > 0;
    if (filteredEmpty) {
      filteredEmpty.hidden = !(hasTiles && visible === 0);
    }
    if (floor) {
      floor.hidden = hasTiles && visible === 0;
    }
  }

  function renderAreaPills(root, areas) {
    var wrap = $('#pos-area-pills', root);
    if (!wrap) return;
    var prevActive = normalize(($('.pos-area-pill.is-active', wrap) || {}).getAttribute
      ? $('.pos-area-pill.is-active', wrap).getAttribute('data-area')
      : '');
    var hasMatch = !prevActive;
    if (prevActive) {
      hasMatch = areas.some(function (area) {
        return normalize(area.id || area.name || '') === prevActive;
      });
    }
    var active = hasMatch ? prevActive : '';
    var html =
      '<button type="button" class="pos-area-pill' +
      (!active ? ' is-active' : '') +
      '" data-area="" role="tab" aria-selected="' +
      (!active ? 'true' : 'false') +
      '">All Areas</button>';
    areas.forEach(function (area) {
      var key = area.id || area.name || '';
      var label = area.name || area.id || 'Area';
      var isActive = active && normalize(key) === active;
      html +=
        '<button type="button" class="pos-area-pill' +
        (isActive ? ' is-active' : '') +
        '" data-area="' +
        escapeHtml(key) +
        '" role="tab" aria-selected="' +
        (isActive ? 'true' : 'false') +
        '">' +
        escapeHtml(label) +
        '</button>';
    });
    wrap.innerHTML = html;
  }

  function tableTileHtml(t, fallbackAreaId) {
    var status = mapStatus(t.status);
    var shape = normalize(t.shape) || 'square';
    var mergeGroupId = String(t.mergeGroupId || '').trim();
    var isPrimary = !!(mergeGroupId && t.mergePrimary);
    var isMember = !!(mergeGroupId && !t.mergePrimary);
    var isMerged = !!mergeGroupId;
    var seats = t.seats != null && t.seats !== '' ? t.seats : '';
    var name = t.name || 'Table';
    var displayName = t.displayName || name;
    var billingTable = t.billingTableName || (isPrimary ? name : '') || name;
    var mergeLabel = t.mergeLabel || '';
    var mergedNames = Array.isArray(t.mergedNames) ? t.mergedNames : [name];
    var areaKey = t.areaId || fallbackAreaId || '';
    var guestName = tableGuestName(t);
    var subtitle = tableSubtitle(t);
    var menuHtml =
      '<button type="button" class="pos-table-menu-item" role="menuitem" data-table-action="transfer">Transfer table</button>' +
      (isMerged
        ? '<button type="button" class="pos-table-menu-item" role="menuitem" data-table-action="unmerge">Unmerge tables</button>'
        : '<button type="button" class="pos-table-menu-item" role="menuitem" data-table-action="merge">Merge tables</button>') +
      '<button type="button" class="pos-table-menu-item" role="menuitem" data-table-action="reserve">Reserve</button>' +
      '<button type="button" class="pos-table-menu-item" role="menuitem" data-table-action="occupied">Occupy</button>' +
      '<button type="button" class="pos-table-menu-item" role="menuitem" data-table-action="available">Set available</button>' +
      '<button type="button" class="pos-table-menu-item" role="menuitem" data-table-action="inactive">Inactive</button>';
    return (
      '<article class="pos-table-tile pos-table-tile--' +
      escapeHtml(status) +
      ' pos-table-tile--' +
      escapeHtml(shape) +
      (isMerged ? ' pos-table-tile--merged' : '') +
      (isMember ? ' pos-table-tile--merge-member' : '') +
      '" data-table-tile data-name="' +
      escapeHtml(name) +
      '" data-display-name="' +
      escapeHtml(displayName) +
      '" data-billing-table="' +
      escapeHtml(billingTable) +
      '" data-search-names="' +
      escapeHtml(mergedNames.join(' ') + (guestName ? ' ' + guestName : '')) +
      '" data-status="' +
      escapeHtml(status) +
      '" data-area="' +
      escapeHtml(areaKey) +
      '" data-seats="' +
      escapeHtml(seats) +
      '" data-guest-name="' +
      escapeHtml(guestName) +
      '" data-id="' +
      escapeHtml(t.id || '') +
      '" data-merge-group="' +
      escapeHtml(mergeGroupId) +
      '" data-merged="' +
      (isMerged ? '1' : '0') +
      '" data-merge-primary="' +
      (isPrimary ? '1' : '0') +
      '" data-merge-member="' +
      (isMember ? '1' : '0') +
      '" tabindex="0">' +
      '<div class="pos-table-tile-top">' +
      '<span class="pos-table-shape-icon" aria-hidden="true">' +
      shapeIcon(shape) +
      '</span>' +
      '<button type="button" class="pos-table-more" aria-label="Table actions" aria-haspopup="menu" aria-expanded="false">' +
      '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="5" r="1.5"/><circle cx="12" cy="12" r="1.5"/><circle cx="12" cy="19" r="1.5"/></svg>' +
      '</button>' +
      '<div class="pos-table-menu" role="menu" hidden>' +
      menuHtml +
      '</div>' +
      '</div>' +
      '<div class="pos-table-tile-name">' +
      escapeHtml(displayName) +
      '</div>' +
      (subtitle
        ? '<div class="pos-table-tile-seats' +
          (subtitle.isGuest ? ' pos-table-tile-seats--guest' : '') +
          '">' +
          escapeHtml(subtitle.text) +
          '</div>'
        : '') +
      (mergeLabel
        ? '<div class="pos-table-merge-tag">' + escapeHtml(mergeLabel) + '</div>'
        : '') +
      '<div class="pos-table-tile-foot">' +
      '<div class="pos-table-badge pos-table-badge--' +
      escapeHtml(status) +
      '">' +
      escapeHtml(STATUS_LABELS[status] || status) +
      '</div>' +
      '</div>' +
      '</article>'
    );
  }

  function renderFloor(root, data) {
    var floor = $('#pos-floor', root);
    if (!floor) return;
    closeTableMenu();
    var view = floor.getAttribute('data-view') || 'grid';
    var areas = data.areas || [];
    var tables = data.tables || [];
    var areaOrder = areas.map(function (a) {
      return a.id;
    });

    if (!tables.length) {
      floor.innerHTML =
        '<div class="pos-floor-empty" role="status">' +
        '<div class="pos-floor-empty-icon" aria-hidden="true">' +
        '<svg viewBox="0 0 24 24"><rect x="3" y="10" width="18" height="8" rx="2"/><path d="M7 10V8a2 2 0 0 1 2-2h6a2 2 0 0 1 2 2v2"/><path d="M7 18v2M17 18v2"/></svg>' +
        '</div>' +
        '<h2>No tables configured</h2>' +
        '<p>Add tables in Restaurant Settings to see them on the floor.</p>' +
        '</div>';
      floor.setAttribute('data-view', view);
      floor.hidden = false;
      return;
    }

    /* Room-page pattern: merged tables leave area sections and sit in a
       titled shell; each physical table remains its own tile. */
    var mergeGroups = {};
    var standalone = [];
    tables.forEach(function (t) {
      if (!t) return;
      var gid = String(t.mergeGroupId || '').trim();
      if (gid) {
        if (!mergeGroups[gid]) mergeGroups[gid] = [];
        mergeGroups[gid].push(t);
      } else {
        standalone.push(t);
      }
    });

    var mergeSectionList = Object.keys(mergeGroups)
      .map(function (gid) {
        var groupTables = mergeGroups[gid].slice().sort(function (a, b) {
          if (!!b.mergePrimary !== !!a.mergePrimary) return a.mergePrimary ? -1 : 1;
          return String(a.name || '').localeCompare(String(b.name || ''));
        });
        var primary =
          groupTables.find(function (t) {
            return t && t.mergePrimary;
          }) || groupTables[0];
        var names = Array.isArray(primary && primary.mergedNames)
          ? primary.mergedNames
          : groupTables
              .map(function (t) {
                return t.name || '';
              })
              .filter(Boolean);
        var title =
          names.length > 1
            ? names.slice(0, -1).join(', ') + ' and ' + names[names.length - 1]
            : (primary && (primary.name || primary.displayName)) || 'Tables';
        return { id: gid, title: title, tables: groupTables };
      })
      .filter(function (sec) {
        return sec.tables.length > 0;
      })
      .sort(function (a, b) {
        return String(a.title).localeCompare(String(b.title));
      });

    var seen = {};
    var sections = [];
    function pushSection(areaId, title) {
      if (seen[areaId]) return;
      seen[areaId] = true;
      sections.push({ id: areaId, title: title, tables: [] });
    }
    areaOrder.forEach(function (id) {
      pushSection(id, areaNameById(areas, id));
    });
    standalone.forEach(function (t) {
      var aid = t.areaId || '_unassigned';
      pushSection(aid, areaNameById(areas, t.areaId) || 'Unassigned');
    });
    sections.forEach(function (sec) {
      sec.tables = standalone.filter(function (t) {
        return (t.areaId || '_unassigned') === sec.id;
      });
    });
    sections = sections.filter(function (sec) {
      return sec.tables.length > 0;
    });

    var html = '';
    mergeSectionList.forEach(function (sec) {
      html +=
        '<section class="pos-floor-section pos-merge-section" data-area-section="merge:' +
        escapeHtml(sec.id) +
        '" data-merge-section="' +
        escapeHtml(sec.id) +
        '">' +
        '<h2 class="pos-floor-section-title pos-merge-section-title">Merged Tables — ' +
        escapeHtml(sec.title) +
        '</h2>' +
        '<div class="pos-merge-box"><div class="pos-floor-grid">';
      sec.tables.forEach(function (t) {
        html += tableTileHtml(t, t.areaId || '');
      });
      html += '</div></div></section>';
    });

    sections.forEach(function (sec) {
      html +=
        '<section class="pos-floor-section" data-area-section="' +
        escapeHtml(sec.id) +
        '">' +
        '<h2 class="pos-floor-section-title">' +
        escapeHtml(sec.title) +
        '</h2>' +
        '<div class="pos-floor-grid">';
      sec.tables.forEach(function (t) {
        html += tableTileHtml(t, sec.id);
      });
      html += '</div></section>';
    });

    floor.innerHTML = html;
    floor.setAttribute('data-view', view);
    floor.hidden = false;
  }

  function bindAreaPills(root) {
    /* Delegate on the pills container (not individual pills): renderAreaPills()
       rebuilds pill buttons via innerHTML on every repaint (initial cache paint,
       then again once the floor API responds), which would detach any listeners
       bound directly to the old button nodes. Binding on the stable wrapper once
       keeps clicks working across those repaints and across soft-nav reinit. */
    var wrap = $('#pos-area-pills', root);
    if (!wrap || wrap.getAttribute('data-bound') === '1') return;
    wrap.setAttribute('data-bound', '1');
    wrap.addEventListener('click', function (event) {
      var pill = event.target.closest('.pos-area-pill');
      if (!pill || !wrap.contains(pill)) return;
      $all('.pos-area-pill', wrap).forEach(function (p) {
        var active = p === pill;
        p.classList.toggle('is-active', active);
        p.setAttribute('aria-selected', active ? 'true' : 'false');
      });
      applyFilters(root);
    });
  }

  function bindViewToggle(root) {
    var floor = $('#pos-floor', root);
    var buttons = $all('.pos-view-btn', root);
    buttons.forEach(function (btn) {
      if (btn.getAttribute('data-bound') === '1') return;
      btn.setAttribute('data-bound', '1');
      btn.addEventListener('click', function () {
        var view = btn.getAttribute('data-view') || 'grid';
        buttons.forEach(function (b) {
          var active = b === btn;
          b.classList.toggle('is-active', active);
          b.setAttribute('aria-pressed', active ? 'true' : 'false');
        });
        if (floor) floor.setAttribute('data-view', view);
      });
    });
  }

  function bindSearch(root) {
    var search = $('#pos-tables-search', root);
    if (search && search.getAttribute('data-bound') !== '1') {
      search.setAttribute('data-bound', '1');
      search.addEventListener('input', function () {
        applyFilters(root);
      });
    }
  }

  function billingTableNameForTile(tile) {
    if (!tile) return 'Table';
    return (
      tile.getAttribute('data-billing-table') ||
      tile.getAttribute('data-name') ||
      'Table'
    );
  }

  function handleTableAction(root, tile, action) {
    if (!tile || !action) return;
    var name = tile.getAttribute('data-name') || 'Table';
    var id = tile.getAttribute('data-id') || '';
    closeTableMenu();
    if (action === 'open') {
      /* Occupied tables resume their open order on the invoice page instead of
         being blocked here — see resumeOrderForTable() in pos_invoice.js.
         Merge members open the primary / billing table. */
      navigateToInvoice(billingTableNameForTile(tile));
      return;
    }
    if (action === 'transfer') {
      openTransferTableModal(root, name);
      return;
    }
    if (action === 'merge') {
      openMergeTablesModal(root, name);
      return;
    }
    if (action === 'unmerge') {
      confirmUnmergeTables(name);
      return;
    }
    if (action === 'reserve') {
      setTableStatus(root, id, 'reserved');
      return;
    }
    if (action === 'occupied') {
      setTableStatus(root, id, 'occupied');
      return;
    }
    if (action === 'cleaning') {
      setTableStatus(root, id, 'cleaning');
      return;
    }
    if (action === 'available') {
      setTableStatus(root, id, 'available');
      return;
    }
    if (action === 'inactive') {
      setTableStatus(root, id, 'inactive');
    }
  }

  function bindTileInteractions(root) {
    if (root.getAttribute('data-tile-bound') === '1') return;
    root.setAttribute('data-tile-bound', '1');

    root.addEventListener('click', function (event) {
      var moreBtn = event.target.closest('.pos-table-more');
      if (moreBtn && root.contains(moreBtn)) {
        event.preventDefault();
        event.stopPropagation();
        var moreTile = moreBtn.closest('[data-table-tile]');
        if (!moreTile) return;
        if (moreBtn.getAttribute('aria-expanded') === 'true') {
          closeTableMenu();
        } else {
          openTableMenu(moreBtn, moreTile);
        }
        return;
      }

      var actionBtn = event.target.closest('[data-table-action]');
      if (actionBtn && root.contains(actionBtn)) {
        event.preventDefault();
        event.stopPropagation();
        var actionTile = actionBtn.closest('[data-table-tile]');
        handleTableAction(root, actionTile, actionBtn.getAttribute('data-table-action'));
        return;
      }

      var tile = event.target.closest('[data-table-tile]');
      if (!tile || !root.contains(tile)) return;
      if (event.target.closest('.pos-table-menu')) return;
      /* Occupied tables resume their open order on the invoice page instead of
         being blocked here — see resumeOrderForTable() in pos_invoice.js.
         Merge members open the primary / billing table. */
      navigateToInvoice(billingTableNameForTile(tile));
    });

    root.addEventListener('keydown', function (event) {
      var tile = event.target.closest('[data-table-tile]');
      if (!tile || !root.contains(tile)) return;
      if (event.target.closest('.pos-table-more, .pos-table-menu')) return;
      if (event.key !== 'Enter' && event.key !== ' ') return;
      event.preventDefault();
      navigateToInvoice(billingTableNameForTile(tile));
    });

    if (!document.__posTableMenuDocBound) {
      document.__posTableMenuDocBound = true;
      document.addEventListener('click', function (event) {
        /* Portaled menus live outside the tile — still treat as menu UI. */
        var actionBtn = event.target.closest('.pos-table-menu [data-table-action]');
        if (actionBtn) {
          event.preventDefault();
          event.stopPropagation();
          var menu = actionBtn.closest('.pos-table-menu');
          var actionTile = tileForTableMenu(menu);
          var page = document.getElementById('pos-tables-page');
          if (page && actionTile) {
            handleTableAction(page, actionTile, actionBtn.getAttribute('data-table-action'));
          } else {
            closeTableMenu();
          }
          return;
        }
        if (event.target.closest('.pos-table-more, .pos-table-menu')) return;
        closeTableMenu();
      });
      document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape') closeTableMenu();
      });
      /* Fixed menus must close on scroll/resize or they float off the button. */
      document.addEventListener(
        'scroll',
        function () {
          if (Date.now() < tableMenuScrollGuardUntil) return;
          closeTableMenu();
        },
        true
      );
      global.addEventListener('resize', function () {
        closeTableMenu();
      });
    }
  }

  function posTablesStatusChanged() {
    var root = document.getElementById('pos-tables-page');
    if (root) applyFilters(root);
  }

  function paintTablesPage(root, data) {
    renderAreaPills(root, data.areas || []);
    renderFloor(root, data);
    updateKpis(root);
    applyFilters(root);
  }

  function openBlankPrintWindow(width, height) {
    var features = 'width=' + (width || 380) + ',height=' + (height || 600);
    try {
      return global.open('', '_blank', features);
    } catch (err) {
      return null;
    }
  }

  function writeHtmlAndPrint(win, html) {
    if (!win) return false;
    try {
      win.document.open();
      win.document.write(html);
      win.document.close();
      try {
        win.focus();
      } catch (err) {}
      setTimeout(function () {
        try {
          win.print();
        } catch (err) {}
      }, 250);
      return true;
    } catch (err) {
      try {
        win.close();
      } catch (closeErr) {}
      return false;
    }
  }

  function closeInAppPrintPage() {
    var overlay = document.getElementById('pos-inapp-print-page');
    if (overlay && overlay.parentNode) overlay.parentNode.removeChild(overlay);
  }

  /**
   * Visible print/view page inside #de-fs-app — required when Element Fullscreen
   * (or an embedded preview) blocks / hides window.open tabs.
   * opts.autoPrint (default true) — set false for eye/view without print dialog.
   */
  function openInAppPrintPage(html, opts) {
    opts = opts || {};
    var autoPrint = opts.autoPrint !== false;
    var title = opts.title || (autoPrint ? 'Print preview' : 'Invoice');
    closeInAppPrintPage();
    var host = document.getElementById('de-fs-app') || document.body;
    var overlay = document.createElement('div');
    overlay.id = 'pos-inapp-print-page';
    overlay.className = 'pos-inapp-print-page';
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    overlay.setAttribute('aria-label', title);
    overlay.innerHTML =
      '<div class="pos-inapp-print-toolbar">' +
      '<span class="pos-inapp-print-title">' +
      escapeHtml(title) +
      '</span>' +
      '<div class="pos-inapp-print-actions">' +
      '<button type="button" class="pos-inapp-print-btn" data-pos-inapp-print>Print</button>' +
      '<button type="button" class="pos-inapp-print-btn pos-inapp-print-btn--ghost" data-pos-inapp-close>Close</button>' +
      '</div></div>' +
      '<iframe class="pos-inapp-print-frame" title="' +
      escapeHtml(title) +
      '"></iframe>';
    host.appendChild(overlay);

    var frame = overlay.querySelector('iframe');
    var idoc = frame && (frame.contentDocument || (frame.contentWindow && frame.contentWindow.document));
    if (!idoc) {
      closeInAppPrintPage();
      return false;
    }
    idoc.open();
    idoc.write(html);
    idoc.close();

    function doPrint() {
      try {
        if (frame.contentWindow) {
          frame.contentWindow.focus();
          frame.contentWindow.print();
        }
      } catch (err) {}
    }

    overlay.addEventListener('click', function (event) {
      if (event.target.closest('[data-pos-inapp-close]')) {
        closeInAppPrintPage();
        return;
      }
      if (event.target.closest('[data-pos-inapp-print]')) {
        doPrint();
      }
    });
    if (autoPrint) setTimeout(doPrint, 300);
    return true;
  }

  function openHtmlPrintWindow(html, opts) {
    opts = opts || {};
    var width = opts.width || 380;
    var height = opts.height || 600;
    var win = opts.preOpened || null;

    /* Prefer a real tab/window (what staff expect as the “print page”). */
    if (!win) {
      win = openBlankPrintWindow(width, height);
    }
    if (writeHtmlAndPrint(win, html)) return true;
    if (win) {
      try {
        win.close();
      } catch (err) {}
    }

    /* Blob URL — works when about:blank write is locked (some WebViews). */
    try {
      var blob = new Blob([html], { type: 'text/html' });
      var url = URL.createObjectURL(blob);
      try {
        win = global.open(url, '_blank', 'width=' + width + ',height=' + height);
      } catch (err) {
        win = null;
      }
      if (win) {
        setTimeout(function () {
          try {
            win.focus();
            win.print();
          } catch (err) {}
          setTimeout(function () {
            URL.revokeObjectURL(url);
          }, 60000);
        }, 300);
        return true;
      }
      URL.revokeObjectURL(url);
    } catch (err) {}

    /* Fullscreen-safe visible print page (never a silent 0×0 iframe). */
    return openInAppPrintPage(html);
  }

  function lineMenuOutlet(line) {
    var raw = String((line && line.outlet) || '')
      .trim()
      .toLowerCase();
    return raw === 'bar' ? 'bar' : 'restaurant';
  }

  function buildKotTokenHtml(token, lines, allLines, opts) {
    opts = opts || {};
    var now = new Date();
    var orderNo = (token && (token.kot_no || token.order_no)) || '—';
    var table = (token && token.name) || '—';
    var totalCount = (allLines || lines || []).length;
    var selectedCount = (lines || []).length;
    var subsetNote =
      selectedCount < totalCount
        ? selectedCount + ' of ' + totalCount + ' items'
        : selectedCount + (selectedCount === 1 ? ' item' : ' items');
    var isBar = opts.menuOutlet === 'bar';
    var heading = isBar ? 'BAR ORDER TOKEN' : 'KITCHEN ORDER TOKEN';
    var foot = isBar ? '-- Resent for bar --' : '-- Resent for kitchen --';
    var rows = (lines || [])
      .map(function (line) {
        var qty = Number(line.sent_qty != null ? line.sent_qty : line.qty) || 0;
        var note = String(line.notes || '').trim();
        return (
          '<tr><td class="qty">' +
          qty +
          '</td><td class="name">' +
          escapeHtml(line.name || '') +
          (line.variant ? '<div class="variant">' + escapeHtml(line.variant) + '</div>' : '') +
          (note ? '<div class="note">' + escapeHtml(note) + '</div>' : '') +
          '</td></tr>'
        );
      })
      .join('');
    return (
      '<!DOCTYPE html><html><head><meta charset="utf-8"><title>KOT ' +
      escapeHtml(orderNo) +
      '</title><style>' +
      'body{font-family:"Courier New",monospace;padding:16px;color:#111;width:300px;margin:0 auto}' +
      'h1{font-size:16px;margin:0 0 4px;text-align:center;letter-spacing:.04em}' +
      '.banner{text-align:center;font-size:11px;font-weight:700;margin:0 0 8px;padding:4px;border:1px solid #333}' +
      '.meta{font-size:12px;margin-bottom:10px;border-bottom:1px dashed #333;padding-bottom:8px}' +
      '.meta div{display:flex;justify-content:space-between;margin:2px 0}' +
      'table{width:100%;border-collapse:collapse;font-size:13px}' +
      'td{padding:4px 0;border-bottom:1px dashed #ddd;vertical-align:top}' +
      'td.qty{width:34px;font-weight:700}' +
      '.variant{font-size:11px;color:#555}' +
      '.note{font-size:11px;color:#333;font-style:italic;margin-top:2px}' +
      '.foot{margin-top:12px;text-align:center;font-size:11px;color:#555}' +
      '@media print{body{width:auto;margin:0}}' +
      '</style></head><body>' +
      '<h1>' +
      heading +
      '</h1>' +
      '<div class="banner">REPRINT / RESEND</div>' +
      '<div class="meta">' +
      '<div><span>Order</span><span>' +
      escapeHtml(orderNo) +
      '</span></div>' +
      '<div><span>Table</span><span>' +
      escapeHtml(table) +
      '</span></div>' +
      '<div><span>Type</span><span>Dine In</span></div>' +
      '<div><span>Items</span><span>' +
      escapeHtml(subsetNote) +
      '</span></div>' +
      '<div><span>Time</span><span>' +
      escapeHtml(now.toLocaleString()) +
      '</span></div>' +
      '</div>' +
      '<table><tbody>' +
      rows +
      '</tbody></table>' +
      '<div class="foot">' +
      foot +
      '</div>' +
      '</body></html>'
    );
  }

  function buildKotTokenModel(token, lines, opts) {
    opts = opts || {};
    return {
      menuOutlet: opts.menuOutlet,
      orderNo: (token && (token.kot_no || token.order_no)) || '—',
      orderType: 'Dine In',
      tableLabel: (token && token.name) || '—',
      when: new Date(),
      items: (lines || []).map(function (line) {
        return {
          qty: Number(line.sent_qty != null ? line.sent_qty : line.qty) || 0,
          name: line.name,
          variant: line.variant,
          notes: line.notes
        };
      }),
      resend: true
    };
  }

  function buildKotTokenText(token, lines, allLines, opts) {
    var model = buildKotTokenModel(token, lines, opts);
    if (
      global.hbePosPrinterPrefs &&
      typeof global.hbePosPrinterPrefs.formatKotTicketText === 'function'
    ) {
      return global.hbePosPrinterPrefs.formatKotTicketText(model);
    }
    return '';
  }

  function printKotTokenTicket(token, selectedLines, preOpenedWin) {
    var earlyWin = preOpenedWin || null;
    try {
      var allLines = (token && token.lines) || [];
      var lines =
        selectedLines && selectedLines.length ? selectedLines : allLines;
      if (!lines.length) {
        if (earlyWin) {
          try {
            earlyWin.close();
          } catch (err) {}
        }
        toast('No kitchen items to resend for this table.');
        return;
      }

      /* Silent print via agent — close any gesture popup; never open Chrome dialog. */
      if (earlyWin) {
        try {
          earlyWin.close();
        } catch (closeEarly) {}
        earlyWin = null;
      }

      var restaurantLines = [];
      var barLines = [];
      lines.forEach(function (line) {
        if (lineMenuOutlet(line) === 'bar') barLines.push(line);
        else restaurantLines.push(line);
      });
      var groups = [];
      if (restaurantLines.length) {
        groups.push({ menuOutlet: 'restaurant', lines: restaurantLines });
      }
      if (barLines.length) {
        groups.push({ menuOutlet: 'bar', lines: barLines });
      }

      var canAgent =
        global.hbePosPrinterPrefs &&
        typeof global.hbePosPrinterPrefs.printKotHtml === 'function';
      if (!canAgent) {
        toast(
          'Hotel Print Agent is required for silent KOT printing. Install and open it on this PC.'
        );
        return;
      }

      var baseId = String(
        (token && (token.invoice_id || token.kot_no)) || Date.now()
      );

      groups.forEach(function (group, idx) {
        var html = buildKotTokenHtml(token, group.lines, allLines, {
          menuOutlet: group.menuOutlet
        });
        var kot = buildKotTokenModel(token, group.lines, {
          menuOutlet: group.menuOutlet
        });
        var text = buildKotTokenText(token, group.lines, allLines, {
          menuOutlet: group.menuOutlet
        });
        var jobId =
          'kot-resend-' + group.menuOutlet + '-' + baseId + '-' + Date.now() + '-' + idx;

        global.hbePosPrinterPrefs
          .printKotHtml(html, {
            menuOutlet: group.menuOutlet,
            jobId: jobId,
            kot: kot,
            text: text,
            allowBrowserFallback: false
          })
          .then(function (result) {
            if (result && result.via === 'failed') {
              toast(
                (result.error && result.error.message) ||
                  'KOT print failed. Open Hotel Print Agent and map Restaurant / Bar KOT.'
              );
            }
          });
      });
    } catch (err) {
      if (earlyWin) {
        try {
          earlyWin.close();
        } catch (closeErr) {}
      }
      toast('Could not print KOT. Try again.');
    }
  }

  var currentKotTokens = [];
  var kotTokenExpanded = {};

  function selectedKotTokenLines(tokenIdx) {
    var token = currentKotTokens[tokenIdx];
    if (!token || !token.lines || !token.lines.length) return [];
    var modal = document.getElementById('pos-kot-tokens-modal');
    if (!modal) return token.lines.slice();
    var panel = modal.querySelector('[data-kot-token-panel="' + tokenIdx + '"]');
    if (!panel) return token.lines.slice();
    var checked = panel.querySelectorAll('input[data-kot-line-id]:checked');
    if (!checked.length) return [];
    var byId = {};
    token.lines.forEach(function (line) {
      byId[String(line.id)] = line;
    });
    var out = [];
    Array.prototype.forEach.call(checked, function (el) {
      var line = byId[String(el.getAttribute('data-kot-line-id'))];
      if (!line) return;
      var maxQty = Number(line.sent_qty != null ? line.sent_qty : line.qty) || 0;
      var row = el.closest('.pos-kot-token-line');
      var qtyEl = row && row.querySelector('[data-kot-line-qty]');
      var customQty = qtyEl
        ? Number(qtyEl.getAttribute('data-kot-line-qty') || qtyEl.textContent)
        : maxQty;
      if (!isFinite(customQty) || customQty < 1) customQty = 1;
      if (customQty > maxQty) customQty = maxQty;
      out.push({
        id: line.id,
        name: line.name,
        variant: line.variant,
        qty: customQty,
        sent_qty: customQty
      });
    });
    return out;
  }

  function kotTokenQtyMin() {
    return canCancelKotLines() ? 0 : 1;
  }

  function syncKotTokenQtyButtons(row) {
    if (!row) return;
    var qtyEl = row.querySelector('[data-kot-line-qty]');
    if (!qtyEl) return;
    var locked = row.classList.contains('is-locked');
    var maxQty = Number(row.getAttribute('data-kot-max-qty')) || 1;
    var cur = Number(qtyEl.getAttribute('data-kot-line-qty'));
    if (!isFinite(cur)) cur = 1;
    var minQty = kotTokenQtyMin();
    var dec = row.querySelector('[data-kot-qty-dec]');
    var inc = row.querySelector('[data-kot-qty-inc]');
    if (dec) dec.disabled = locked || cur <= minQty;
    if (inc) inc.disabled = locked || cur >= maxQty;
  }

  function collectKotTokenReductions() {
    var modal = document.getElementById('pos-kot-tokens-modal');
    if (!modal) return [];
    var changes = [];
    modal.querySelectorAll('[data-kot-token-panel]').forEach(function (panel) {
      var tokenIdx = Number(panel.getAttribute('data-kot-token-panel'));
      var token = currentKotTokens[tokenIdx];
      if (!token || !token.invoice_id) return;
      panel.querySelectorAll('.pos-kot-token-line').forEach(function (row) {
        var input = row.querySelector('input[data-kot-line-id]');
        var qtyEl = row.querySelector('[data-kot-line-qty]');
        if (!input || !qtyEl) return;
        var lineId = Number(input.getAttribute('data-kot-line-id'));
        var maxQty = Number(row.getAttribute('data-kot-max-qty')) || 0;
        var cur = Number(qtyEl.getAttribute('data-kot-line-qty'));
        if (!isFinite(cur)) cur = maxQty;
        if (cur + 1e-9 >= maxQty) return;
        if (cur < 0) cur = 0;
        changes.push({
          invoice_id: Number(token.invoice_id),
          line_id: lineId,
          sent_qty: cur
        });
      });
    });
    return changes;
  }

  function syncKotTokensSaveButton() {
    var btn = document.getElementById('pos-kot-tokens-save');
    if (!btn) return;
    var changes = collectKotTokenReductions();
    var hasChanges = changes.length > 0;
    btn.hidden = !hasChanges;
    btn.disabled = !hasChanges;
    if (hasChanges) {
      btn.removeAttribute('hidden');
      btn.title =
        'Save ' +
        changes.length +
        ' kitchen quantity change' +
        (changes.length === 1 ? '' : 's');
    } else {
      btn.setAttribute('hidden', '');
      btn.title = '';
    }
  }

  function saveKotTokenReductions() {
    var btn = document.getElementById('pos-kot-tokens-save');
    var changes = collectKotTokenReductions();
    if (!changes.length) {
      toast('No kitchen quantities were reduced.');
      return;
    }
    if (!canCancelKotLines()) {
      toast('Cancellation Access is required to reduce kitchen-sent items.');
      syncKotTokensSaveButton();
      return;
    }
    if (btn) btn.disabled = true;
    fetch(resolvePosApiBase() + '/api/kot-tokens/reduce', {
      method: 'POST',
      credentials: 'same-origin',
      headers: apiHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ changes: changes })
    })
      .then(function (res) {
        return res.json().catch(function () {
          return {};
        }).then(function (data) {
          return { ok: res.ok, status: res.status, data: data };
        });
      })
      .then(function (result) {
        if (!result.ok || !(result.data && result.data.ok)) {
          toast(
            (result.data && result.data.error) ||
              'Could not save kitchen quantity changes.'
          );
          syncKotTokensSaveButton();
          return;
        }
        var cancelled = Number(result.data.cancelled_count) || 0;
        var invoices = (result.data && result.data.invoices) || [];
        if (!cancelled && invoices.length) {
          cancelled = invoices.filter(function (inv) {
            return inv && inv.cancelled;
          }).length;
        }
        var count = Number(result.data.updated_count) || changes.length;
        if (cancelled > 0 && cancelled >= count) {
          toast(
            cancelled === 1
              ? 'Order cancelled — table is now available.'
              : cancelled + ' orders cancelled — tables are now available.'
          );
        } else if (cancelled > 0) {
          toast(
            'Kitchen quantities updated; ' +
              cancelled +
              (cancelled === 1 ? ' order cancelled.' : ' orders cancelled.')
          );
        } else {
          toast(
            count === 1
              ? 'Kitchen quantities updated on 1 order.'
              : 'Kitchen quantities updated on ' + count + ' orders.'
          );
        }
        paintKotTokensModal(result.data);
        refreshFloorAfterKot(null);
      })
      .catch(function () {
        toast('Could not save kitchen quantity changes. Check your connection.');
        syncKotTokensSaveButton();
      });
  }

  function syncKotTokenPanelActions(tokenIdx) {
    var modal = document.getElementById('pos-kot-tokens-modal');
    if (!modal) return;
    var panel = modal.querySelector('[data-kot-token-panel="' + tokenIdx + '"]');
    if (!panel) return;
    var token = currentKotTokens[tokenIdx];
    var locked = kotTokenLinesLocked(token);
    var boxes = panel.querySelectorAll('input[data-kot-line-id]');
    var checked = panel.querySelectorAll('input[data-kot-line-id]:checked');
    var resendBtn = panel.querySelector('[data-kot-resend-selected]');
    if (resendBtn) resendBtn.disabled = locked || checked.length === 0;
    var countEl = panel.querySelector('[data-kot-selected-count]');
    if (countEl) {
      countEl.textContent =
        checked.length + ' of ' + boxes.length + ' selected';
    }
  }

  function paintKotTokensModal(payload) {
    var rowsEl = document.getElementById('pos-kot-tokens-rows');
    var emptyEl = document.getElementById('pos-kot-tokens-empty');
    var wrap = document.getElementById('pos-kot-tokens-table-wrap');
    var metaEl = document.getElementById('pos-kot-tokens-meta');
    var tables = (payload && Array.isArray(payload.tables) ? payload.tables : []) || [];
    var count = tables.length;

    if (metaEl) {
      metaEl.textContent =
        count === 0
          ? 'Showing 0 tokens'
          : 'Showing ' + count + ' of ' + count + ' token' + (count === 1 ? '' : 's');
    }
    if (!rowsEl) return;

    if (!count) {
      rowsEl.innerHTML = '';
      kotTokenExpanded = {};
      if (wrap) wrap.hidden = true;
      if (emptyEl) emptyEl.hidden = false;
      currentKotTokens = [];
      syncKotTokensSaveButton();
      return;
    }
    if (wrap) wrap.hidden = false;
    if (emptyEl) emptyEl.hidden = true;

    var chevronDownSvg =
      '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>';
    var chevronUpSvg =
      '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m18 15-6-6-6 6"/></svg>';
    /* Refresh arrows — clearer “resend” than a notification bell */
    var resendSvg =
      '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true">' +
      '<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/>' +
      '<path d="M21 3v5h-5"/>' +
      '<path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/>' +
      '<path d="M8 16H3v5"/>' +
      '</svg>';

    rowsEl.innerHTML = tables
      .map(function (t, idx) {
        var when = formatKotPendingWhen(t.sent_at);
        var items = Number(t.sent_qty) > 0 ? Number(t.sent_qty) : Number(t.sent_items) || 0;
        var kotNo = t.kot_no || t.order_no || '—';
        var lines = Array.isArray(t.lines) ? t.lines : [];
        var expanded = !!kotTokenExpanded[idx];
        var billSent = !!t.customer_bill_sent;
        var linesLocked = kotTokenLinesLocked(t);
        var lineChecks = lines
          .map(function (line) {
            var qty = Number(line.sent_qty != null ? line.sent_qty : line.qty) || 0;
            var label =
              (line.name || 'Item') +
              (line.variant ? ' (' + line.variant + ')' : '') +
              ' × ' +
              qty;
            return (
              '<div class="pos-kot-token-line' +
              (linesLocked ? ' is-locked' : '') +
              '" data-kot-max-qty="' +
              escapeHtml(qty) +
              '">' +
              '<label class="pos-kot-token-line-check">' +
              '<input type="checkbox" data-kot-line-id="' +
              escapeHtml(line.id) +
              '"' +
              (linesLocked ? '' : ' checked') +
              (linesLocked ? ' disabled' : '') +
              '>' +
              '<span class="pos-kot-token-line-name">' +
              escapeHtml(line.name || 'Item') +
              (line.variant
                ? '<small>' + escapeHtml(line.variant) + '</small>'
                : '') +
              '</span>' +
              '<span class="pos-sr-only">' +
              escapeHtml(label) +
              '</span>' +
              '</label>' +
              '<span class="pos-kot-token-qty-stepper" data-kot-qty-stepper>' +
              '<button type="button" class="pos-kot-token-qty-btn" data-kot-qty-dec' +
              (linesLocked || qty <= kotTokenQtyMin() ? ' disabled' : '') +
              ' aria-label="Decrease quantity">−</button>' +
              '<span class="pos-kot-token-line-qty" data-kot-line-qty="' +
              escapeHtml(qty) +
              '">' +
              escapeHtml(qty) +
              '</span>' +
              '<button type="button" class="pos-kot-token-qty-btn" data-kot-qty-inc' +
              ' disabled' +
              ' aria-label="Increase quantity">+</button>' +
              '</span>' +
              '</div>'
            );
          })
          .join('');

        return (
          '<tr class="pos-kot-token-summary' +
          (expanded ? ' is-expanded' : '') +
          (billSent ? ' is-bill-sent' : '') +
          '" data-kot-token-idx="' +
          idx +
          '">' +
          '<td>' +
          '<div class="pos-kot-table-cell-name">' +
          escapeHtml(t.name || 'Table') +
          '</div>' +
          (billSent
            ? '<span class="pos-kot-table-bill-lock">Bill sent</span>'
            : '') +
          '</td>' +
          '<td><span class="pos-kot-table-kot">' +
          escapeHtml(kotNo) +
          '</span></td>' +
          '<td><span class="pos-kot-table-items">' +
          escapeHtml(items) +
          (items === 1 ? ' item' : ' items') +
          '</span></td>' +
          '<td><div class="pos-kot-table-time">' +
          escapeHtml(when.time) +
          (when.date ? '<small>' + escapeHtml(when.date) + '</small>' : '') +
          '</div></td>' +
          '<td class="pos-kot-token-actions-cell">' +
          '<div class="pos-kot-token-actions act-grp">' +
          '<button type="button" class="act-btn pos-kot-token-toggle' +
          (expanded ? ' is-open' : '') +
          '" data-kot-toggle-idx="' +
          idx +
          '" aria-expanded="' +
          (expanded ? 'true' : 'false') +
          '" data-tip="' +
          (expanded ? 'Hide items' : 'Select items') +
          '" aria-label="' +
          (expanded ? 'Hide items' : 'Select items') +
          '">' +
          (expanded ? chevronUpSvg : chevronDownSvg) +
          '</button>' +
          '<button type="button" class="act-btn pos-kot-token-resend-all" data-kot-resend-all-idx="' +
          idx +
          '"' +
          (linesLocked
            ? ' disabled data-tip="Bill sent — resend disabled" aria-label="Bill sent — resend disabled"'
            : ' data-tip="Resend all" aria-label="Resend every item on this token"') +
          '>' +
          resendSvg +
          '</button>' +
          '</div>' +
          '</td>' +
          '</tr>' +
          '<tr class="pos-kot-token-detail' +
          (expanded ? ' is-open' : '') +
          '" data-kot-token-detail="' +
          idx +
          '"' +
          (expanded ? '' : ' hidden') +
          '>' +
          '<td colspan="5">' +
          '<div class="pos-kot-token-panel' +
          (billSent ? ' is-bill-sent' : '') +
          (linesLocked ? '' : billSent ? ' is-cancel-unlocked' : '') +
          '" data-kot-token-panel="' +
          idx +
          '">' +
          (linesLocked
            ? '<p class="pos-kot-token-bill-lock">Bill sent — resend disabled</p>'
            : billSent
              ? '<p class="pos-kot-token-bill-lock is-soft">Bill sent — Cancellation Access can still edit</p>'
              : '') +
          '<div class="pos-kot-token-panel-tools">' +
          '<button type="button" class="pos-kot-token-link" data-kot-select-all="' +
          idx +
          '"' +
          (linesLocked ? ' disabled' : '') +
          '>Select all</button>' +
          '<button type="button" class="pos-kot-token-link" data-kot-clear-all="' +
          idx +
          '"' +
          (linesLocked ? ' disabled' : '') +
          '>Clear</button>' +
          '<span class="pos-kot-token-selected" data-kot-selected-count>' +
          (linesLocked ? '0' : lines.length) +
          ' of ' +
          lines.length +
          ' selected</span>' +
          '</div>' +
          '<div class="pos-kot-token-lines">' +
          (lineChecks ||
            '<p class="pos-kot-token-lines-empty">No sent items on this token.</p>') +
          '</div>' +
          '<div class="pos-kot-token-panel-footer">' +
          '<button type="button" class="pos-kot-row-send" data-kot-resend-selected="' +
          idx +
          '"' +
          (linesLocked || !lines.length ? ' disabled' : '') +
          (linesLocked ? ' title="Bill sent — resend disabled"' : '') +
          '>' +
          resendSvg +
          '<span>Resend selected</span></button>' +
          '</div>' +
          '</div>' +
          '</td>' +
          '</tr>'
        );
      })
      .join('');

    currentKotTokens = tables;
    tables.forEach(function (_t, idx) {
      if (kotTokenExpanded[idx]) syncKotTokenPanelActions(idx);
    });
    syncKotTokensSaveButton();
  }

  function closeKotTokensModal() {
    var modal = document.getElementById('pos-kot-tokens-modal');
    if (!modal || modal.hidden) return;
    modal.hidden = true;
    modal.setAttribute('hidden', '');
    modal.setAttribute('aria-hidden', 'true');
    kotTokenExpanded = {};
  }

  function openKotTokensModal() {
    var modal = document.getElementById('pos-kot-tokens-modal');
    if (!modal) return;
    kotTokenExpanded = {};
    modal.hidden = false;
    modal.removeAttribute('hidden');
    modal.setAttribute('aria-hidden', 'false');
    paintKotTokensModal({ tables: currentKotTokens || [] });
    fetch(resolvePosApiBase() + '/api/kot-tokens', {
      method: 'GET',
      credentials: 'same-origin',
      headers: apiHeaders()
    })
      .then(function (res) {
        return res.json().catch(function () {
          return {};
        });
      })
      .then(function (data) {
        if (!data || !data.ok) {
          toast((data && data.error) || 'Could not load kitchen tokens.');
          return;
        }
        currentKotTokens = data.tables || [];
        paintKotTokensModal(data);
      })
      .catch(function () {
        toast('Could not load kitchen tokens. Check your connection.');
      });
    var closeBtn = modal.querySelector('.pos-kot-modal-close');
    if (closeBtn) closeBtn.focus();
  }

  function bindKotTokensModal() {
    var openBtn = document.getElementById('pos-quick-kot-tokens');
    if (openBtn && openBtn.getAttribute('data-bound') !== '1') {
      openBtn.setAttribute('data-bound', '1');
      openBtn.addEventListener('click', function () {
        openKotTokensModal();
      });
    }

    var modal = document.getElementById('pos-kot-tokens-modal');
    if (!modal || modal.getAttribute('data-bound') === '1') return;
    modal.setAttribute('data-bound', '1');

    modal.addEventListener('click', function (event) {
      if (event.target.closest('[data-kot-tokens-close]')) {
        closeKotTokensModal();
        return;
      }

      var toggle = event.target.closest('[data-kot-toggle-idx]');
      if (toggle && modal.contains(toggle)) {
        event.preventDefault();
        var tIdx = Number(toggle.getAttribute('data-kot-toggle-idx'));
        kotTokenExpanded[tIdx] = !kotTokenExpanded[tIdx];
        paintKotTokensModal({ tables: currentKotTokens });
        return;
      }

      var qtyDec = event.target.closest('[data-kot-qty-dec]');
      var qtyInc = event.target.closest('[data-kot-qty-inc]');
      if ((qtyDec || qtyInc) && modal.contains(event.target)) {
        event.preventDefault();
        event.stopPropagation();
        var qtyBtn = qtyDec || qtyInc;
        if (qtyBtn.disabled) return;
        var qtyRow = qtyBtn.closest('.pos-kot-token-line');
        var qtyPanel = qtyBtn.closest('[data-kot-token-panel]');
        if (!qtyRow || !qtyPanel) return;
        var qtyTokenIdx = Number(qtyPanel.getAttribute('data-kot-token-panel'));
        var qtyToken = currentKotTokens[qtyTokenIdx];
        if (kotTokenLinesLocked(qtyToken)) return;
        var qtyEl = qtyRow.querySelector('[data-kot-line-qty]');
        if (!qtyEl) return;
        var maxQty = Number(qtyRow.getAttribute('data-kot-max-qty')) || 1;
        var cur = Number(qtyEl.getAttribute('data-kot-line-qty'));
        if (!isFinite(cur)) cur = maxQty;
        if (qtyInc) cur = Math.min(maxQty, cur + 1);
        if (qtyDec) cur = Math.max(kotTokenQtyMin(), cur - 1);
        qtyEl.setAttribute('data-kot-line-qty', String(cur));
        qtyEl.textContent = String(cur);
        syncKotTokenQtyButtons(qtyRow);
        syncKotTokensSaveButton();
        return;
      }

      var saveBtn = event.target.closest('[data-kot-tokens-save]');
      if (saveBtn && modal.contains(saveBtn)) {
        event.preventDefault();
        if (saveBtn.disabled) return;
        saveKotTokenReductions();
        return;
      }

      var selectAll = event.target.closest('[data-kot-select-all]');
      if (selectAll && modal.contains(selectAll)) {
        event.preventDefault();
        if (selectAll.disabled) return;
        var sIdx = Number(selectAll.getAttribute('data-kot-select-all'));
        if (kotTokenLinesLocked(currentKotTokens[sIdx])) return;
        var sPanel = modal.querySelector('[data-kot-token-panel="' + sIdx + '"]');
        if (sPanel) {
          sPanel.querySelectorAll('input[data-kot-line-id]').forEach(function (el) {
            if (!el.disabled) el.checked = true;
          });
          syncKotTokenPanelActions(sIdx);
        }
        return;
      }

      var clearAll = event.target.closest('[data-kot-clear-all]');
      if (clearAll && modal.contains(clearAll)) {
        event.preventDefault();
        if (clearAll.disabled) return;
        var cIdx = Number(clearAll.getAttribute('data-kot-clear-all'));
        if (kotTokenLinesLocked(currentKotTokens[cIdx])) return;
        var cPanel = modal.querySelector('[data-kot-token-panel="' + cIdx + '"]');
        if (cPanel) {
          cPanel.querySelectorAll('input[data-kot-line-id]').forEach(function (el) {
            if (!el.disabled) el.checked = false;
          });
          syncKotTokenPanelActions(cIdx);
        }
        return;
      }

      var resendAll = event.target.closest('[data-kot-resend-all-idx]');
      if (resendAll && modal.contains(resendAll)) {
        event.preventDefault();
        event.stopPropagation();
        if (resendAll.disabled) return;
        var aIdx = Number(resendAll.getAttribute('data-kot-resend-all-idx'));
        var aToken = currentKotTokens[aIdx];
        if (!aToken) {
          toast('KOT not found. Refresh and try again.');
          return;
        }
        if (kotTokenLinesLocked(aToken)) {
          toast('Bill sent — resend disabled for this order.');
          return;
        }
        /* Resend all uses full kitchen sent_qty on each line. */
        printKotTokenTicket(aToken, null, null);
        toast('KOT resent for ' + (aToken.name || 'table') + '.');
        return;
      }

      var resendSel = event.target.closest('[data-kot-resend-selected]');
      if (resendSel && modal.contains(resendSel)) {
        event.preventDefault();
        event.stopPropagation();
        if (resendSel.disabled) return;
        var rIdx = Number(resendSel.getAttribute('data-kot-resend-selected'));
        var rToken = currentKotTokens[rIdx];
        if (!rToken) {
          toast('KOT not found. Refresh and try again.');
          return;
        }
        if (kotTokenLinesLocked(rToken)) {
          toast('Bill sent — resend disabled for this order.');
          return;
        }
        var selected = selectedKotTokenLines(rIdx);
        if (!selected.length) {
          toast('Select at least one product to resend.');
          return;
        }
        printKotTokenTicket(rToken, selected, null);
        toast(
          selected.length === 1
            ? '1 item resent for ' + (rToken.name || 'table') + '.'
            : selected.length + ' items resent for ' + (rToken.name || 'table') + '.'
        );
        return;
      }
    });

    modal.addEventListener('change', function (event) {
      var input = event.target.closest('input[data-kot-line-id]');
      if (!input || !modal.contains(input)) return;
      var panel = input.closest('[data-kot-token-panel]');
      if (!panel) return;
      syncKotTokenPanelActions(Number(panel.getAttribute('data-kot-token-panel')));
    });

    if (!document.__posKotTokensEscBound) {
      document.__posKotTokensEscBound = true;
      document.addEventListener('keydown', function (event) {
        if (event.key !== 'Escape') return;
        var settleOpen = document.getElementById('pos-inv-settle-modal');
        if (settleOpen && !settleOpen.hidden) return;
        var invoicesOpen = document.getElementById('pos-today-invoices-modal');
        if (invoicesOpen && !invoicesOpen.hidden) {
          closeTodayInvoicesModal();
          return;
        }
        var open = document.getElementById('pos-kot-tokens-modal');
        if (open && !open.hidden) closeKotTokensModal();
      });
    }
  }

  var currentTodayInvoices = [];
  var todayInvoicesFilter = 'all';
  var ORDER_TYPE_LABELS = {
    dine_in: 'Dine In',
    takeaway: 'Takeaway',
    delivery: 'Delivery'
  };
  var INVOICE_STATUS_LABELS = {
    open: 'Unsettled',
    closed: 'Settled',
    cancelled: 'Cancelled'
  };
  var GST_RATE = 0.05;
  var CGST_RATE = 0.025;
  var UGST_RATE = 0.025;

  function formatInvoiceMoney(n) {
    var v = Math.round((Number(n) || 0) * 100) / 100;
    return (
      '₹' +
      v.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    );
  }

  function formatKpiMoney(n) {
    if (typeof global.formatKpiInr === 'function') return global.formatKpiInr(n);
    if (typeof global.formatInr === 'function') return global.formatInr(n, 0);
    var v = Math.round(Number(n) || 0);
    return (
      '₹' +
      v.toLocaleString('en-IN', { maximumFractionDigits: 0 })
    );
  }

  function formatAdjHint(type, value) {
    var n = Number(value) || 0;
    if (!n) return '';
    if (String(type || '') === 'amt') return '(₹' + n + ')';
    return '(' + n + '%)';
  }

  function viewCustomerBillFromInvoice(invoice) {
    try {
      if (!invoice) {
        toast('Invoice not found.');
        return;
      }
      if (typeof global.buildPosCustomerBillHtml !== 'function') {
        toast('Could not open invoice. Try again.');
        return;
      }
      var html = global.buildPosCustomerBillHtml(invoice, {});
      var orderNo = invoice.order_no || 'Invoice';
      openInAppPrintPage(html, {
        autoPrint: false,
        title: 'Invoice ' + orderNo
      });
    } catch (err) {
      toast('Could not open invoice. Try again.');
    }
  }

  function viewTodayInvoice(invoiceId, btn) {
    if (!invoiceId) return;
    if (btn) btn.disabled = true;
    fetch(resolvePosApiBase() + '/api/invoices/' + encodeURIComponent(invoiceId), {
      method: 'GET',
      credentials: 'same-origin',
      headers: apiHeaders()
    })
      .then(function (res) {
        return res.json().catch(function () {
          return {};
        });
      })
      .then(function (data) {
        if (!data || !data.ok || !data.invoice) {
          toast((data && data.error) || 'Could not load invoice.');
          return;
        }
        viewCustomerBillFromInvoice(data.invoice);
      })
      .catch(function () {
        toast('Could not load invoice. Check your connection.');
      })
      .then(function () {
        if (btn) btn.disabled = false;
      });
  }

  function printCustomerBillFromInvoice(invoice) {
    try {
      if (!invoice) {
        toast('Invoice not found.');
        return;
      }
      if (typeof global.buildPosCustomerBillHtml !== 'function') {
        toast('Could not print bill. Try again.');
        return;
      }
      var html = global.buildPosCustomerBillHtml(invoice, {});
      var page = document.getElementById('pos-tables-page');
      var outlet = (page && page.getAttribute('data-pos-outlet')) || undefined;
      var jobId =
        'inv-' +
        String(invoice.id || invoice.order_no || Date.now()) +
        '-' +
        Date.now();

      function browserPrint() {
        var win = global.open('', '_blank', 'width=420,height=680');
        if (!win) {
          toast('Could not open the bill window. Check your pop-up blocker.');
          return;
        }
        win.document.write(html);
        win.document.close();
        win.focus();
        setTimeout(function () {
          try {
            win.print();
          } catch (err) {
            /* Best-effort print. */
          }
        }, 250);
      }

      if (
        global.hbePosPrinterPrefs &&
        typeof global.hbePosPrinterPrefs.printInvoiceHtml === 'function'
      ) {
        global.hbePosPrinterPrefs
          .printInvoiceHtml(html, {
            outlet: outlet,
            jobId: jobId,
            invoice: invoice,
            allowBrowserFallback: false
          })
          .then(function (result) {
            if (result && result.via === 'failed') {
              toast(
                (result.error && result.error.message) ||
                  'Bill print failed. Open Hotel Print Agent and map Restaurant Invoice.'
              );
            }
          });
        return;
      }
      toast(
        'Hotel Print Agent is required for silent bill printing. Install and open it on this PC.'
      );
    } catch (err) {
      toast('Could not print bill. Try again.');
    }
  }

  function printTodayInvoice(invoiceId, btn) {
    if (!invoiceId) return;
    if (btn) btn.disabled = true;
    fetch(resolvePosApiBase() + '/api/invoices/' + encodeURIComponent(invoiceId), {
      method: 'GET',
      credentials: 'same-origin',
      headers: apiHeaders()
    })
      .then(function (res) {
        return res.json().catch(function () {
          return {};
        });
      })
      .then(function (data) {
        if (!data || !data.ok || !data.invoice) {
          toast((data && data.error) || 'Could not load invoice for printing.');
          return;
        }
        printCustomerBillFromInvoice(data.invoice);
        toast('Bill ready for ' + (data.invoice.order_no || 'order') + '.');
      })
      .catch(function () {
        toast('Could not print bill. Check your connection.');
      })
      .then(function () {
        if (btn) btn.disabled = false;
      });
  }

  function editTodayInvoice(invoiceId, btn) {
    if (!invoiceId) return;
    if (!canCancelKotLines()) {
      toast('Cancellation Access is required to edit unsettled invoices.');
      return;
    }
    if (btn) btn.disabled = true;
    fetch(
      resolvePosApiBase() +
        '/api/invoices/' +
        encodeURIComponent(invoiceId) +
        '/reopen-edit',
      {
        method: 'POST',
        credentials: 'same-origin',
        headers: apiHeaders({ 'Content-Type': 'application/json' })
      }
    )
      .then(function (res) {
        return res.json().catch(function () {
          return {};
        }).then(function (data) {
          return { ok: res.ok, status: res.status, data: data || {} };
        });
      })
      .then(function (result) {
        if (!result.ok || !result.data.ok) {
          toast(
            (result.data && result.data.error) ||
              'Could not open invoice for editing.'
          );
          return;
        }
        closeTodayInvoicesModal();
        navigateToInvoiceById(invoiceId);
      })
      .catch(function () {
        toast('Could not open invoice for editing. Check your connection.');
      })
      .then(function () {
        if (btn) btn.disabled = false;
      });
  }

  var pendingCancelInvoice = null;

  function cancelInvoiceModalEl() {
    return document.getElementById('pos-cancel-invoice-modal');
  }

  function closeCancelInvoiceModal() {
    var modal = cancelInvoiceModalEl();
    if (!modal) return;
    modal.hidden = true;
    modal.setAttribute('hidden', '');
    pendingCancelInvoice = null;
    var reason = document.getElementById('pos-cancel-invoice-reason');
    var err = document.getElementById('pos-cancel-invoice-error');
    var confirmBtn = document.getElementById('pos-cancel-invoice-confirm');
    if (reason) reason.value = '';
    if (err) {
      err.hidden = true;
      err.textContent = '';
    }
    if (confirmBtn) confirmBtn.disabled = false;
  }

  function openCancelInvoiceModal(invoiceId, btn) {
    if (!invoiceId) return;
    if (!canCancelKotLines()) {
      toast('Cancellation Access is required to cancel invoices.');
      return;
    }
    var inv = findTodayInvoiceById(invoiceId);
    if (!inv) {
      toast('Invoice not found.');
      return;
    }
    var statusKey = String(inv.status || 'open').toLowerCase();
    if (statusKey === 'closed') {
      toast('Settled invoices cannot be cancelled.');
      return;
    }
    if (statusKey === 'cancelled') {
      toast('This invoice is already cancelled.');
      return;
    }
    pendingCancelInvoice = {
      id: String(invoiceId),
      orderNo: inv.order_no || 'this invoice',
      btn: btn || null
    };
    var modal = cancelInvoiceModalEl();
    var lead = document.getElementById('pos-cancel-invoice-lead');
    var reason = document.getElementById('pos-cancel-invoice-reason');
    var err = document.getElementById('pos-cancel-invoice-error');
    if (lead) {
      lead.textContent =
        'Cancel ' +
        pendingCancelInvoice.orderNo +
        '? Enter a reason. This cannot be undone.';
    }
    if (reason) reason.value = '';
    if (err) {
      err.hidden = true;
      err.textContent = '';
    }
    if (modal) {
      modal.hidden = false;
      modal.removeAttribute('hidden');
    }
    setTimeout(function () {
      if (reason) reason.focus();
    }, 30);
  }

  function submitCancelInvoiceModal() {
    if (!pendingCancelInvoice || !pendingCancelInvoice.id) return;
    var reasonEl = document.getElementById('pos-cancel-invoice-reason');
    var err = document.getElementById('pos-cancel-invoice-error');
    var confirmBtn = document.getElementById('pos-cancel-invoice-confirm');
    var reason = reasonEl ? String(reasonEl.value || '').trim() : '';
    if (!reason) {
      if (err) {
        err.hidden = false;
        err.textContent = 'Enter a reason for cancellation.';
      }
      if (reasonEl) reasonEl.focus();
      return;
    }
    var invoiceId = pendingCancelInvoice.id;
    var orderNo = pendingCancelInvoice.orderNo;
    var btn = pendingCancelInvoice.btn;
    if (confirmBtn) confirmBtn.disabled = true;
    if (btn) btn.disabled = true;
    fetch(
      resolvePosApiBase() +
        '/api/invoices/' +
        encodeURIComponent(invoiceId) +
        '/delete',
      {
        method: 'POST',
        credentials: 'same-origin',
        headers: apiHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({ reason: reason })
      }
    )
      .then(function (res) {
        return res
          .json()
          .catch(function () {
            return {};
          })
          .then(function (data) {
            return { ok: res.ok, data: data || {} };
          });
      })
      .then(function (result) {
        if (!result.ok || !result.data.ok) {
          var msg =
            (result.data && result.data.error) || 'Could not cancel invoice.';
          if (err) {
            err.hidden = false;
            err.textContent = msg;
          } else {
            toast(msg);
          }
          return;
        }
        closeCancelInvoiceModal();
        toast('Invoice ' + orderNo + ' cancelled.');
        refreshTodayInvoicesList();
        loadFloorFromApi(function (data) {
          var root = document.getElementById('pos-tables-page');
          if (root) paintTablesPage(root, data || loadFloorDataCached());
        });
      })
      .catch(function () {
        if (err) {
          err.hidden = false;
          err.textContent = 'Could not cancel invoice. Check your connection.';
        } else {
          toast('Could not cancel invoice. Check your connection.');
        }
      })
      .then(function () {
        if (confirmBtn) confirmBtn.disabled = false;
        if (btn) btn.disabled = false;
      });
  }

  function cancelTodayInvoice(invoiceId, btn) {
    openCancelInvoiceModal(invoiceId, btn);
  }

  function bindCancelInvoiceModal() {
    var modal = cancelInvoiceModalEl();
    if (!modal || modal.getAttribute('data-bound') === '1') return;
    modal.setAttribute('data-bound', '1');
    modal.addEventListener('click', function (event) {
      if (event.target.closest('[data-cancel-invoice-close]')) {
        event.preventDefault();
        closeCancelInvoiceModal();
        return;
      }
      if (event.target.closest('#pos-cancel-invoice-confirm')) {
        event.preventDefault();
        submitCancelInvoiceModal();
      }
    });
    var reason = document.getElementById('pos-cancel-invoice-reason');
    if (reason) {
      reason.addEventListener('keydown', function (event) {
        if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
          event.preventDefault();
          submitCancelInvoiceModal();
        }
      });
    }
  }

  function isTodayInvoiceUnsettled(inv) {
    var status = String((inv && inv.status) || 'open').toLowerCase();
    return status === 'open';
  }

  function paintTodayInvoicesModal(payload) {
    var rowsEl = document.getElementById('pos-today-invoices-rows');
    var emptyEl = document.getElementById('pos-today-invoices-empty');
    var wrap = document.getElementById('pos-today-invoices-table-wrap');
    var metaEl = document.getElementById('pos-today-invoices-meta');
    var titleEl = document.getElementById('pos-today-invoices-title');
    var modal = document.getElementById('pos-today-invoices-modal');
    if (payload && Array.isArray(payload.invoices)) {
      currentTodayInvoices = payload.invoices;
    }
    var allInvoices = currentTodayInvoices || [];
    var unsettledOnly = todayInvoicesFilter === 'unsettled';
    var invoices = unsettledOnly
      ? allInvoices.filter(isTodayInvoiceUnsettled)
      : allInvoices.slice();
    var count = invoices.length;
    var totalCount = allInvoices.length;

    if (titleEl) {
      titleEl.textContent = unsettledOnly ? 'Unsettled Invoices' : 'Today’s Invoices';
    }
    if (modal) {
      modal.classList.toggle('is-unsettled-only', unsettledOnly);
    }
    if (metaEl) {
      if (unsettledOnly) {
        metaEl.textContent =
          count === 0
            ? 'Showing 0 unsettled'
            : 'Showing ' +
              count +
              ' unsettled of ' +
              totalCount +
              ' invoice' +
              (totalCount === 1 ? '' : 's');
      } else {
        metaEl.textContent =
          count === 0
            ? 'Showing 0 invoices'
            : 'Showing ' +
              count +
              ' of ' +
              count +
              ' invoice' +
              (count === 1 ? '' : 's');
      }
    }
    if (!rowsEl) return;

    if (!count) {
      rowsEl.innerHTML = '';
      if (wrap) wrap.hidden = true;
      if (emptyEl) {
        emptyEl.hidden = false;
        emptyEl.textContent = unsettledOnly
          ? 'No unsettled invoices right now.'
          : 'No invoices created today yet. Use New Order or Create Invoice to start a bill.';
      }
      return;
    }
    if (wrap) wrap.hidden = false;
    if (emptyEl) emptyEl.hidden = true;

    var viewSvg =
      '<svg viewBox="0 0 24 24" aria-hidden="true">' +
      '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>' +
      '<circle cx="12" cy="12" r="3"/></svg>';
    var printSvg =
      '<svg viewBox="0 0 24 24" aria-hidden="true">' +
      '<path d="M6 9V2h12v7"/><path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/>' +
      '<path d="M6 14h12v8H6z"/></svg>';
    var editSvg =
      '<svg viewBox="0 0 24 24" aria-hidden="true">' +
      '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>';
    var cancelSvg =
      '<svg viewBox="0 0 24 24" aria-hidden="true">' +
      '<circle cx="12" cy="12" r="9"/><path d="m9 9 6 6M15 9l-6 6"/></svg>';
    var showMutate = canCancelKotLines();

    rowsEl.innerHTML = invoices
      .map(function (inv) {
        var statusRaw = String(inv.status || 'open').toLowerCase();
        var statusKey =
          statusRaw === 'closed'
            ? 'closed'
            : statusRaw === 'cancelled'
              ? 'cancelled'
              : 'open';
        var statusLabel = INVOICE_STATUS_LABELS[statusKey] || statusKey;
        var typeKey = inv.order_type || 'dine_in';
        var typeLabel =
          inv.order_type_label || ORDER_TYPE_LABELS[typeKey] || typeKey;
        var table = inv.table_label || inv.table || '—';
        var when = formatKotPendingWhen(inv.saved_at || inv.created_at);
        var id = inv.id;
        var orderNo = inv.order_no || '—';
        var unsettled = statusKey === 'open';
        var statusCss =
          statusKey === 'closed'
            ? 'settled'
            : statusKey === 'cancelled'
              ? 'cancelled'
              : 'unsettled';
        var rowClass =
          statusKey === 'closed'
            ? ' is-settled'
            : statusKey === 'cancelled'
              ? ' is-cancelled'
              : ' is-unsettled';
        var mutateBtns =
          showMutate && unsettled
            ? '<button type="button" class="act-btn edit pos-today-invoice-btn--edit" data-today-invoice-edit="' +
              escapeHtml(id) +
              '" data-tip="Edit" aria-label="Edit invoice ' +
              escapeHtml(orderNo) +
              '">' +
              editSvg +
              '</button>' +
              '<button type="button" class="act-btn cancel pos-today-invoice-btn--cancel" data-today-invoice-cancel="' +
              escapeHtml(id) +
              '" data-tip="Cancel" aria-label="Cancel invoice ' +
              escapeHtml(orderNo) +
              '">' +
              cancelSvg +
              '</button>'
            : '';
        return (
          '<tr class="pos-today-invoice-row' +
          rowClass +
          '" data-today-invoice-id="' +
          escapeHtml(id) +
          '"' +
          (unsettled
            ? ' tabindex="0" role="button" aria-label="Settle invoice ' +
              escapeHtml(orderNo) +
              '"'
            : '') +
          '>' +
          '<td><span class="pos-today-invoice-order">' +
          escapeHtml(orderNo) +
          '</span></td>' +
          '<td>' +
          escapeHtml(table) +
          '</td>' +
          '<td>' +
          escapeHtml(typeLabel) +
          '</td>' +
          '<td><span class="pos-today-invoice-total">' +
          escapeHtml(formatInvoiceMoney(inv.grand_total)) +
          '</span></td>' +
          '<td><div class="pos-kot-table-time">' +
          escapeHtml(when.time) +
          (when.date ? '<small>' + escapeHtml(when.date) + '</small>' : '') +
          '</div></td>' +
          '<td class="pos-today-invoice-status-cell"><span class="pos-today-invoice-status is-' +
          escapeHtml(statusCss) +
          '">' +
          escapeHtml(statusLabel) +
          '</span></td>' +
          '<td class="pos-today-invoice-actions-cell">' +
          '<div class="pos-today-invoice-actions act-grp">' +
          mutateBtns +
          '<button type="button" class="act-btn edit pos-today-invoice-btn--view" data-today-invoice-view="' +
          escapeHtml(id) +
          '" data-tip="View" aria-label="View invoice ' +
          escapeHtml(orderNo) +
          '">' +
          viewSvg +
          '</button>' +
          '<button type="button" class="act-btn print pos-today-invoice-btn--print" data-today-invoice-print="' +
          escapeHtml(id) +
          '" data-tip="Print" aria-label="Print invoice ' +
          escapeHtml(orderNo) +
          '">' +
          printSvg +
          '</button>' +
          '</div>' +
          '</td>' +
          '</tr>'
        );
      })
      .join('');
  }

  function findTodayInvoiceById(invoiceId) {
    var id = String(invoiceId || '');
    if (!id) return null;
    var list = currentTodayInvoices || [];
    for (var i = 0; i < list.length; i++) {
      if (String(list[i].id) === id) return list[i];
    }
    return null;
  }

  function refreshTodayInvoicesList(done) {
    fetch(resolvePosApiBase() + '/api/today-invoices', {
      method: 'GET',
      credentials: 'same-origin',
      headers: apiHeaders()
    })
      .then(function (res) {
        return res.json().catch(function () {
          return {};
        });
      })
      .then(function (data) {
        if (!data || !data.ok) {
          if (typeof done === 'function') done(null);
          return;
        }
        currentTodayInvoices = data.invoices || [];
        paintTodayInvoicesModal(data);
        paintInvoiceKpis(document.getElementById('pos-tables-page'), data);
        if (typeof done === 'function') done(data);
      })
      .catch(function () {
        if (typeof done === 'function') done(null);
      });
  }

  function openSettleFromTodayInvoice(invoiceId) {
    if (typeof navigator !== 'undefined' && navigator.onLine === false) {
      toast('Settle Bill requires an internet connection.');
      return;
    }
    var inv = findTodayInvoiceById(invoiceId);
    if (!inv) {
      toast('Invoice not found.');
      return;
    }
    var statusKey = String(inv.status || 'open').toLowerCase();
    if (statusKey === 'closed') {
      toast('This invoice is already settled.');
      return;
    }
    if (statusKey === 'cancelled') {
      toast('This invoice was cancelled.');
      return;
    }
    if (typeof global.openPosSettleModal !== 'function') {
      toast('Settle dialog is not available.');
      return;
    }
    global.openPosSettleModal({
      invoiceId: inv.id,
      orderNo: inv.order_no || '—',
      tableLabel: inv.table_label || inv.table || '',
      grandTotal: inv.grand_total,
      apiBase: resolvePosApiBase(),
      onSettled: function (settledInvoice, meta) {
        var table = (meta && meta.tableLabel) || inv.table_label || inv.table || '';
        toast(
          table
            ? 'Bill settled. ' + table + ' is now available.'
            : 'Bill settled successfully.'
        );
        refreshFloorAfterMutation();
        refreshTodayInvoicesList();
      }
    });
  }

  function closeTodayInvoicesModal() {
    var modal = document.getElementById('pos-today-invoices-modal');
    if (!modal || modal.hidden) return;
    modal.hidden = true;
    modal.setAttribute('hidden', '');
    modal.setAttribute('aria-hidden', 'true');
    todayInvoicesFilter = 'all';
    modal.classList.remove('is-unsettled-only');
  }

  function openTodayInvoicesModal(opts) {
    opts = opts || {};
    todayInvoicesFilter = opts.filter === 'unsettled' ? 'unsettled' : 'all';
    var modal = document.getElementById('pos-today-invoices-modal');
    if (!modal) return;
    modal.hidden = false;
    modal.removeAttribute('hidden');
    modal.setAttribute('aria-hidden', 'false');
    paintTodayInvoicesModal({ invoices: currentTodayInvoices || [] });
    refreshTodayInvoicesList(function (data) {
      if (!data) toast('Could not load today’s invoices. Check your connection.');
    });
    var closeBtn = modal.querySelector('.pos-kot-modal-close');
    if (closeBtn) closeBtn.focus();
  }

  function bindTodayInvoicesModal() {
    var openBtn = document.getElementById('pos-quick-today-invoices');
    if (openBtn && openBtn.getAttribute('data-bound') !== '1') {
      openBtn.setAttribute('data-bound', '1');
      openBtn.addEventListener('click', function () {
        openTodayInvoicesModal({ filter: 'all' });
      });
    }

    var root = document.getElementById('pos-tables-page');
    var unsettledKpi = root && root.querySelector('.pos-kpi[data-kpi="unsettled"]');
    if (unsettledKpi && unsettledKpi.getAttribute('data-bound') !== '1') {
      unsettledKpi.setAttribute('data-bound', '1');
      unsettledKpi.setAttribute('role', 'button');
      unsettledKpi.setAttribute('tabindex', '0');
      unsettledKpi.setAttribute(
        'aria-haspopup',
        'dialog'
      );
      unsettledKpi.setAttribute('aria-controls', 'pos-today-invoices-modal');
      function openUnsettledFromKpi() {
        if (unsettledKpi.hidden) return;
        openTodayInvoicesModal({ filter: 'unsettled' });
      }
      unsettledKpi.addEventListener('click', openUnsettledFromKpi);
      unsettledKpi.addEventListener('keydown', function (event) {
        if (event.key !== 'Enter' && event.key !== ' ') return;
        event.preventDefault();
        openUnsettledFromKpi();
      });
    }

    var modal = document.getElementById('pos-today-invoices-modal');
    if (!modal || modal.getAttribute('data-bound') === '1') return;
    modal.setAttribute('data-bound', '1');

    modal.addEventListener('click', function (event) {
      if (event.target.closest('[data-today-invoices-close]')) {
        closeTodayInvoicesModal();
        return;
      }

      var viewBtn = event.target.closest('[data-today-invoice-view]');
      if (viewBtn && modal.contains(viewBtn)) {
        event.preventDefault();
        if (viewBtn.disabled) return;
        viewTodayInvoice(viewBtn.getAttribute('data-today-invoice-view'), viewBtn);
        return;
      }

      var printBtn = event.target.closest('[data-today-invoice-print]');
      if (printBtn && modal.contains(printBtn)) {
        event.preventDefault();
        if (printBtn.disabled) return;
        printTodayInvoice(printBtn.getAttribute('data-today-invoice-print'), printBtn);
        return;
      }

      var editBtn = event.target.closest('[data-today-invoice-edit]');
      if (editBtn && modal.contains(editBtn)) {
        event.preventDefault();
        if (editBtn.disabled) return;
        editTodayInvoice(editBtn.getAttribute('data-today-invoice-edit'), editBtn);
        return;
      }

      var cancelBtn = event.target.closest('[data-today-invoice-cancel]');
      if (cancelBtn && modal.contains(cancelBtn)) {
        event.preventDefault();
        event.stopPropagation();
        if (cancelBtn.disabled) return;
        cancelTodayInvoice(cancelBtn.getAttribute('data-today-invoice-cancel'), cancelBtn);
        return;
      }

      var unsettledRow = event.target.closest('tr.pos-today-invoice-row.is-unsettled');
      if (
        unsettledRow &&
        modal.contains(unsettledRow) &&
        !event.target.closest('.pos-today-invoice-actions-cell, .act-grp, .act-btn')
      ) {
        event.preventDefault();
        openSettleFromTodayInvoice(unsettledRow.getAttribute('data-today-invoice-id'));
      }
    });

    modal.addEventListener('keydown', function (event) {
      if (event.key !== 'Enter' && event.key !== ' ') return;
      var row = event.target.closest
        ? event.target.closest('tr.pos-today-invoice-row.is-unsettled')
        : null;
      if (!row || event.target !== row) return;
      event.preventDefault();
      openSettleFromTodayInvoice(row.getAttribute('data-today-invoice-id'));
    });
  }

  function initPosTablesPage() {
    syncPosApiPaths();
    var root = document.getElementById('pos-tables-page');
    if (!root) return;
    /* Soft-nav: paint cache first, then refresh from SQLite API */
    var cached = loadFloorDataCached();
    paintTablesPage(root, cached);
    paintKotPendingBanner(currentKotPending);
    if (typeof global.initEpListboxes === 'function') {
      global.initEpListboxes();
    }
    bindAreaPills(root);
    bindViewToggle(root);
    bindSearch(root);
    bindTileInteractions(root);
    bindTransferTableModal();
    bindMergeTablesModal();
    bindTableMergeQuickCard();
    bindKotPendingBanner();
    bindKotTokensModal();
    bindTodayInvoicesModal();
    bindCancelInvoiceModal();
    if (typeof global.bindPosSettleModal === 'function') {
      global.bindPosSettleModal();
    }
    loadFloorFromApi(function (data) {
      paintTablesPage(root, data || loadFloorDataCached());
    });
  }

  global.posTablesStatusChanged = posTablesStatusChanged;
  global.initPosTablesPage = initPosTablesPage;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initPosTablesPage);
  } else if (!global.__deSoftNavInProgress) {
    /* Soft-nav: deWorkspaceReinit calls init once after scripts load — avoid double API fetch. */
    initPosTablesPage();
  } else {
    /* Soft-nav in progress: still init once the current stack clears if reinit missed us. */
    setTimeout(function () {
      if (!document.getElementById('pos-tables-page')) return;
      if (document.querySelector('#pos-floor [data-table-tile]')) return;
      initPosTablesPage();
    }, 0);
  }
})(window);
