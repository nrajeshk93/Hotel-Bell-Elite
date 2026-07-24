/**
 * Point of Sale — Tables page interactions (filter / view / KPI).
 * Soft-nav safe: expose window.initPosTablesPage and re-bind idempotently.
 * Floor tiles load from /point-of-sale/api/floor (SQLite); in-memory cache only.
 */
(function (global) {
  'use strict';

  var FLOOR_API = '/point-of-sale/api/floor';
  var LEGACY_STORAGE_KEY = 'hbe_pos_floor_demo';
  var MIGRATE_FLAG = 'hbe_pos_floor_db_migrated';
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
    return fetch('/point-of-sale/api/invoices/' + encodeURIComponent(invoiceId) + '/send-kot', {
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
    return fetch('/point-of-sale/api/kot-pending/send-all', {
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

  function loadFloorDataCached() {
    if (currentFloor && Array.isArray(currentFloor.areas) && Array.isArray(currentFloor.tables)) {
      return {
        areas: currentFloor.areas,
        tables: currentFloor.tables
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

  function saveFloorData(data) {
    currentFloor = data;
    if (floorSaveTimer) clearTimeout(floorSaveTimer);
    floorSaveTimer = setTimeout(function () {
      floorSaveTimer = null;
      putFloor(data).catch(function () {
        /* keep in-memory state */
      });
    }, 280);
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
          paintKotPendingBanner(data.kot_pending);
        } else {
          payload = emptyFloor();
          currentFloor = payload;
          paintKotPendingBanner(emptyKotPending());
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
    return '/point-of-sale/invoice?table=' + encodeURIComponent(table);
  }

  function navigateToInvoice(name) {
    var url = invoiceUrlForTable(name);
    if (typeof global.deNavigateWithTransition === 'function') {
      global.deNavigateWithTransition(url);
      return;
    }
    global.location.href = url;
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
    });
    $all('.pos-table-more[aria-expanded="true"]').forEach(function (btn) {
      btn.setAttribute('aria-expanded', 'false');
    });
    $all('.pos-table-tile.is-menu-open').forEach(function (tile) {
      tile.classList.remove('is-menu-open');
    });
  }

  function positionTableMenu(btn, menu) {
    /* Fixed to the viewport so neighboring tiles / overflow:auto shells cannot
       clip or paint over the dropdown (common on lower/right tiles). */
    var rect = btn.getBoundingClientRect();
    menu.style.position = 'fixed';
    menu.style.right = 'auto';
    menu.style.bottom = 'auto';
    menu.style.zIndex = '120';
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
    tile.classList.add('is-menu-open');
    menu.hidden = false;
    btn.setAttribute('aria-expanded', 'true');
    positionTableMenu(btn, menu);
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
      if (!el || !key) return;
      el.textContent = String(counts[key] != null ? counts[key] : 0);
    });
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
      var seats = normalize(tile.getAttribute('data-seats'));
      var matchArea = !area || tileArea === area;
      var matchStatus = !statusFilter || tileStatus === statusFilter;
      var matchQuery = !query || tileName.indexOf(query) !== -1 || seats.indexOf(query) !== -1;
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

  function renderFloor(root, data) {
    var floor = $('#pos-floor', root);
    if (!floor) return;
    var view = floor.getAttribute('data-view') || 'grid';
    var areas = data.areas || [];
    var tables = data.tables || [];
    var areaOrder = areas.map(function (a) {
      return a.id;
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
    tables.forEach(function (t) {
      var aid = t.areaId || '_unassigned';
      pushSection(aid, areaNameById(areas, t.areaId) || 'Unassigned');
    });

    sections.forEach(function (sec) {
      sec.tables = tables.filter(function (t) {
        return (t.areaId || '_unassigned') === sec.id;
      });
    });
    sections = sections.filter(function (sec) {
      return sec.tables.length > 0;
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

    var html = '';
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
        var status = mapStatus(t.status);
        var shape = normalize(t.shape) || 'square';
        var seats = t.seats != null ? t.seats : '';
        var name = t.name || 'Table';
        var areaKey = t.areaId || sec.id;
        html +=
          '<article class="pos-table-tile pos-table-tile--' +
          escapeHtml(status) +
          ' pos-table-tile--' +
          escapeHtml(shape) +
          '" data-table-tile data-name="' +
          escapeHtml(name) +
          '" data-status="' +
          escapeHtml(status) +
          '" data-area="' +
          escapeHtml(areaKey) +
          '" data-seats="' +
          escapeHtml(seats) +
          '" data-id="' +
          escapeHtml(t.id || '') +
          '" tabindex="0">' +
          '<div class="pos-table-tile-top">' +
          '<span class="pos-table-shape-icon" aria-hidden="true">' +
          shapeIcon(shape) +
          '</span>' +
          '<button type="button" class="pos-table-more" aria-label="Table actions" aria-haspopup="menu" aria-expanded="false">' +
          '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="5" r="1.5"/><circle cx="12" cy="12" r="1.5"/><circle cx="12" cy="19" r="1.5"/></svg>' +
          '</button>' +
          '<div class="pos-table-menu" role="menu" hidden>' +
          '<button type="button" class="pos-table-menu-item" role="menuitem" data-table-action="open">Open</button>' +
          '<button type="button" class="pos-table-menu-item" role="menuitem" data-table-action="reserve">Reserve</button>' +
          '<button type="button" class="pos-table-menu-item" role="menuitem" data-table-action="occupied">Occupy</button>' +
          '<button type="button" class="pos-table-menu-item" role="menuitem" data-table-action="cleaning">Mark cleaning</button>' +
          '<button type="button" class="pos-table-menu-item" role="menuitem" data-table-action="available">Set available</button>' +
          '</div>' +
          '</div>' +
          '<div class="pos-table-tile-name">' +
          escapeHtml(name) +
          '</div>' +
          (seats !== ''
            ? '<div class="pos-table-tile-seats">' + escapeHtml(seats) + ' Seater</div>'
            : '') +
          '<div class="pos-table-badge pos-table-badge--' +
          escapeHtml(status) +
          '">' +
          escapeHtml(STATUS_LABELS[status] || status) +
          '</div>' +
          '</article>';
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

  function handleTableAction(root, tile, action) {
    if (!tile || !action) return;
    var name = tile.getAttribute('data-name') || 'Table';
    var id = tile.getAttribute('data-id') || '';
    closeTableMenu();
    if (action === 'open') {
      /* Occupied tables resume their open order on the invoice page instead of
         being blocked here — see resumeOrderForTable() in pos_invoice.js. */
      navigateToInvoice(name);
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
    }
  }

  function bindTileInteractions(root) {
    if (root.getAttribute('data-tile-bound') === '1') return;
    root.setAttribute('data-tile-bound', '1');

    root.addEventListener('click', function (event) {
      var actionBtn = event.target.closest('[data-table-action]');
      if (actionBtn && root.contains(actionBtn)) {
        event.preventDefault();
        event.stopPropagation();
        var actionTile = actionBtn.closest('[data-table-tile]');
        handleTableAction(root, actionTile, actionBtn.getAttribute('data-table-action'));
        return;
      }

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

      var tile = event.target.closest('[data-table-tile]');
      if (!tile || !root.contains(tile)) return;
      if (event.target.closest('.pos-table-menu')) return;
      var tileName = tile.getAttribute('data-name') || 'Table';
      /* Occupied tables resume their open order on the invoice page instead of
         being blocked here — see resumeOrderForTable() in pos_invoice.js. */
      navigateToInvoice(tileName);
    });

    root.addEventListener('keydown', function (event) {
      var tile = event.target.closest('[data-table-tile]');
      if (!tile || !root.contains(tile)) return;
      if (event.target.closest('.pos-table-more, .pos-table-menu')) return;
      if (event.key !== 'Enter' && event.key !== ' ') return;
      event.preventDefault();
      var tileName = tile.getAttribute('data-name') || 'Table';
      navigateToInvoice(tileName);
    });

    if (!document.__posTableMenuDocBound) {
      document.__posTableMenuDocBound = true;
      document.addEventListener('click', function (event) {
        if (event.target.closest('[data-table-tile] .pos-table-more, [data-table-tile] .pos-table-menu')) {
          return;
        }
        closeTableMenu();
      });
      document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape') closeTableMenu();
      });
      /* Fixed menus must close on scroll/resize or they float off the button. */
      document.addEventListener(
        'scroll',
        function () {
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

  function printKotTokenTicket(token, selectedLines) {
    try {
      var allLines = (token && token.lines) || [];
      var lines =
        selectedLines && selectedLines.length ? selectedLines : allLines;
      if (!lines.length) {
        toast('No kitchen items to resend for this table.');
        return;
      }
      var win = global.open('', '_blank', 'width=380,height=600');
      if (!win) {
        toast('Could not open the KOT window. Check your pop-up blocker.');
        return;
      }
      var now = new Date();
      var orderNo = (token && (token.kot_no || token.order_no)) || '—';
      var table = (token && token.name) || '—';
      var totalCount = allLines.length;
      var selectedCount = lines.length;
      var subsetNote =
        selectedCount < totalCount
          ? selectedCount + ' of ' + totalCount + ' items'
          : selectedCount + (selectedCount === 1 ? ' item' : ' items');
      var rows = lines
        .map(function (line) {
          var qty = Number(line.sent_qty != null ? line.sent_qty : line.qty) || 0;
          return (
            '<tr><td class="qty">' +
            qty +
            '</td><td class="name">' +
            escapeHtml(line.name || '') +
            (line.variant ? '<div class="variant">' + escapeHtml(line.variant) + '</div>' : '') +
            '</td></tr>'
          );
        })
        .join('');
      var html =
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
        '.foot{margin-top:12px;text-align:center;font-size:11px;color:#555}' +
        '</style></head><body>' +
        '<h1>KITCHEN ORDER TOKEN</h1>' +
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
        '<div class="foot">-- Resent for kitchen --</div>' +
        '</body></html>';
      win.document.write(html);
      win.document.close();
      win.focus();
      setTimeout(function () {
        try {
          win.print();
        } catch (err) {
          /* Best-effort print */
        }
      }, 250);
    } catch (err) {
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

  function syncKotTokenQtyButtons(row) {
    if (!row) return;
    var qtyEl = row.querySelector('[data-kot-line-qty]');
    if (!qtyEl) return;
    var locked = row.classList.contains('is-locked');
    var maxQty = Number(row.getAttribute('data-kot-max-qty')) || 1;
    var cur = Number(qtyEl.getAttribute('data-kot-line-qty')) || 1;
    var dec = row.querySelector('[data-kot-qty-dec]');
    var inc = row.querySelector('[data-kot-qty-inc]');
    if (dec) dec.disabled = locked || cur <= 1;
    if (inc) inc.disabled = locked || cur >= maxQty;
  }

  function syncKotTokenPanelActions(tokenIdx) {
    var modal = document.getElementById('pos-kot-tokens-modal');
    if (!modal) return;
    var panel = modal.querySelector('[data-kot-token-panel="' + tokenIdx + '"]');
    if (!panel) return;
    var token = currentKotTokens[tokenIdx];
    var billSent = !!(token && token.customer_bill_sent);
    var boxes = panel.querySelectorAll('input[data-kot-line-id]');
    var checked = panel.querySelectorAll('input[data-kot-line-id]:checked');
    var resendBtn = panel.querySelector('[data-kot-resend-selected]');
    if (resendBtn) resendBtn.disabled = billSent || checked.length === 0;
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
    var subEl = document.getElementById('pos-kot-tokens-sub');
    var metaEl = document.getElementById('pos-kot-tokens-meta');
    var tables = (payload && Array.isArray(payload.tables) ? payload.tables : []) || [];
    var count = tables.length;

    if (subEl) {
      subEl.textContent =
        count === 0
          ? 'No kitchen tokens yet. Send a KOT from Create Invoice first.'
          : count === 1
            ? '1 table has a kitchen token ready to resend.'
            : count + ' tables have kitchen tokens ready to resend.';
    }
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
      return;
    }
    if (wrap) wrap.hidden = false;
    if (emptyEl) emptyEl.hidden = true;

    var chevronSvg =
      '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>';
    var bellSvg =
      '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true">' +
      '<path d="M18 8a6 6 0 1 0-12 0c0 4-1.5 5.5-1.5 6.5h15C18.5 13.5 18 11 18 8z"/>' +
      '<path d="M10.5 17a1.5 1.5 0 0 0 3 0"/></svg>';

    rowsEl.innerHTML = tables
      .map(function (t, idx) {
        var status = mapStatus(t.table_status || 'occupied');
        var seats = t.seats != null && t.seats !== '' ? String(t.seats) + ' Seater' : '';
        var when = formatKotPendingWhen(t.sent_at);
        var items = Number(t.sent_qty) > 0 ? Number(t.sent_qty) : Number(t.sent_items) || 0;
        var kotNo = t.kot_no || t.order_no || '—';
        var lines = Array.isArray(t.lines) ? t.lines : [];
        var expanded = !!kotTokenExpanded[idx];
        var billSent = !!t.customer_bill_sent;
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
              (billSent ? ' is-locked' : '') +
              '" data-kot-max-qty="' +
              escapeHtml(qty) +
              '">' +
              '<label class="pos-kot-token-line-check">' +
              '<input type="checkbox" data-kot-line-id="' +
              escapeHtml(line.id) +
              '"' +
              (billSent ? '' : ' checked') +
              (billSent ? ' disabled' : '') +
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
              (billSent || qty <= 1 ? ' disabled' : '') +
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
          (seats ? '<div class="pos-kot-table-cell-meta">' + escapeHtml(seats) + '</div>' : '') +
          '<span class="pos-kot-table-status is-' +
          escapeHtml(status) +
          '">' +
          escapeHtml(STATUS_LABELS[status] || status) +
          '</span>' +
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
          '<td>' +
          '<div class="pos-kot-token-actions">' +
          '<button type="button" class="pos-kot-token-toggle' +
          (expanded ? ' is-open' : '') +
          '" data-kot-toggle-idx="' +
          idx +
          '" aria-expanded="' +
          (expanded ? 'true' : 'false') +
          '">' +
          chevronSvg +
          '<span>Select items</span></button>' +
          '<button type="button" class="pos-kot-token-resend-all" data-kot-resend-all-idx="' +
          idx +
          '"' +
          (billSent
            ? ' disabled title="Bill sent — resend disabled"'
            : ' title="Resend every item on this token"') +
          '>' +
          bellSvg +
          '<span>Resend all</span></button>' +
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
          '" data-kot-token-panel="' +
          idx +
          '">' +
          (billSent
            ? '<p class="pos-kot-token-bill-lock">Bill sent — resend disabled</p>'
            : '') +
          '<div class="pos-kot-token-panel-tools">' +
          '<button type="button" class="pos-kot-token-link" data-kot-select-all="' +
          idx +
          '"' +
          (billSent ? ' disabled' : '') +
          '>Select all</button>' +
          '<button type="button" class="pos-kot-token-link" data-kot-clear-all="' +
          idx +
          '"' +
          (billSent ? ' disabled' : '') +
          '>Clear</button>' +
          '<span class="pos-kot-token-selected" data-kot-selected-count>' +
          (billSent ? '0' : lines.length) +
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
          (billSent || !lines.length ? ' disabled' : '') +
          (billSent ? ' title="Bill sent — resend disabled"' : '') +
          '>' +
          bellSvg +
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
    fetch('/point-of-sale/api/kot-tokens', {
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
        if (qtyToken && qtyToken.customer_bill_sent) return;
        var qtyEl = qtyRow.querySelector('[data-kot-line-qty]');
        if (!qtyEl) return;
        var maxQty = Number(qtyRow.getAttribute('data-kot-max-qty')) || 1;
        var cur = Number(qtyEl.getAttribute('data-kot-line-qty')) || 1;
        if (qtyInc) cur = Math.min(maxQty, cur + 1);
        if (qtyDec) cur = Math.max(1, cur - 1);
        qtyEl.setAttribute('data-kot-line-qty', String(cur));
        qtyEl.textContent = String(cur);
        syncKotTokenQtyButtons(qtyRow);
        return;
      }

      var selectAll = event.target.closest('[data-kot-select-all]');
      if (selectAll && modal.contains(selectAll)) {
        event.preventDefault();
        if (selectAll.disabled) return;
        var sIdx = Number(selectAll.getAttribute('data-kot-select-all'));
        if (currentKotTokens[sIdx] && currentKotTokens[sIdx].customer_bill_sent) return;
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
        if (currentKotTokens[cIdx] && currentKotTokens[cIdx].customer_bill_sent) return;
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
        if (resendAll.disabled) return;
        var aIdx = Number(resendAll.getAttribute('data-kot-resend-all-idx'));
        var aToken = currentKotTokens[aIdx];
        if (!aToken) {
          toast('KOT not found. Refresh and try again.');
          return;
        }
        if (aToken.customer_bill_sent) {
          toast('Bill sent — resend disabled for this order.');
          return;
        }
        /* Resend all uses full kitchen sent_qty on each line. */
        printKotTokenTicket(aToken);
        toast('KOT resent for ' + (aToken.name || 'table') + '.');
        return;
      }

      var resendSel = event.target.closest('[data-kot-resend-selected]');
      if (resendSel && modal.contains(resendSel)) {
        event.preventDefault();
        if (resendSel.disabled) return;
        var rIdx = Number(resendSel.getAttribute('data-kot-resend-selected'));
        var rToken = currentKotTokens[rIdx];
        if (!rToken) {
          toast('KOT not found. Refresh and try again.');
          return;
        }
        if (rToken.customer_bill_sent) {
          toast('Bill sent — resend disabled for this order.');
          return;
        }
        var selected = selectedKotTokenLines(rIdx);
        if (!selected.length) {
          toast('Select at least one product to resend.');
          return;
        }
        printKotTokenTicket(rToken, selected);
        toast(
          selected.length === 1
            ? '1 item resent for ' + (rToken.name || 'table') + '.'
            : selected.length + ' items resent for ' + (rToken.name || 'table') + '.'
        );
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
  var ORDER_TYPE_LABELS = {
    dine_in: 'Dine In',
    takeaway: 'Takeaway',
    delivery: 'Delivery'
  };
  var INVOICE_STATUS_LABELS = {
    open: 'Open',
    closed: 'Closed'
  };
  var GST_RATE = 0.05;

  function formatInvoiceMoney(n) {
    var v = Math.round((Number(n) || 0) * 100) / 100;
    return (
      '₹' +
      v.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    );
  }

  function formatAdjHint(type, value) {
    var n = Number(value) || 0;
    if (!n) return '';
    if (String(type || '') === 'amt') return '(₹' + n + ')';
    return '(' + n + '%)';
  }

  function invoiceWorkspaceUrl(invoiceId) {
    return '/point-of-sale/invoice?invoice=' + encodeURIComponent(invoiceId);
  }

  function navigateToInvoiceById(invoiceId) {
    if (!invoiceId) return;
    var url = invoiceWorkspaceUrl(invoiceId);
    if (typeof global.deNavigateWithTransition === 'function') {
      global.deNavigateWithTransition(url);
      return;
    }
    global.location.href = url;
  }

  function printCustomerBillFromInvoice(invoice) {
    try {
      if (!invoice) {
        toast('Invoice not found.');
        return;
      }
      var win = global.open('', '_blank', 'width=420,height=680');
      if (!win) {
        toast('Could not open the bill window. Check your pop-up blocker.');
        return;
      }
      var now = new Date();
      var orderNo = invoice.order_no || '—';
      var table = invoice.table_label || invoice.table || '—';
      var orderTypeValue = invoice.order_type || 'dine_in';
      var orderType = ORDER_TYPE_LABELS[orderTypeValue] || orderTypeValue;
      var customerName = invoice.customer_name || '';
      var customerMobile = invoice.customer_mobile || '';
      var lines = Array.isArray(invoice.lines) ? invoice.lines : [];
      var totals = {
        discountType: invoice.discount_type,
        discountValue: invoice.discount_value,
        serviceType: invoice.service_type,
        serviceValue: invoice.service_value,
        subtotal: invoice.subtotal,
        discount: invoice.discount,
        gst: invoice.gst,
        service: invoice.service,
        tip: invoice.tip,
        roundOff: invoice.round_off,
        total: invoice.grand_total
      };
      var rows = lines
        .map(function (line) {
          var qty = Number(line.qty) || 0;
          var rate = Number(line.rate) || 0;
          var amt = line.line_total != null ? Number(line.line_total) : rate * qty;
          return (
            '<tr><td class="name">' +
            escapeHtml(line.name) +
            (line.variant
              ? '<div class="variant">' + escapeHtml(line.variant) + '</div>'
              : '') +
            '</td><td class="qty">' +
            qty +
            '</td><td class="rate">' +
            formatInvoiceMoney(rate) +
            '</td><td class="amt">' +
            formatInvoiceMoney(amt) +
            '</td></tr>'
          );
        })
        .join('');
      var discHint = formatAdjHint(totals.discountType, totals.discountValue);
      var svcHint = formatAdjHint(totals.serviceType, totals.serviceValue);
      var custRow = customerName
        ? '<div><span>Customer</span><span>' +
          escapeHtml(customerName) +
          (customerMobile ? ' · +91 ' + escapeHtml(customerMobile) : '') +
          '</span></div>'
        : '';
      var when = formatKotPendingWhen(invoice.saved_at || invoice.created_at);
      var dateLabel = when.date || when.time || '';
      var html =
        '<!DOCTYPE html><html><head><meta charset="utf-8"><title>Bill ' +
        escapeHtml(orderNo) +
        '</title><style>' +
        'body{font-family:"Courier New",monospace;padding:16px;color:#111;width:340px;margin:0 auto}' +
        'h1{font-size:16px;margin:0 0 4px;text-align:center;letter-spacing:.04em}' +
        '.sub{font-size:11px;text-align:center;color:#555;margin-bottom:10px}' +
        '.meta{font-size:12px;margin-bottom:10px;border-bottom:1px dashed #333;padding-bottom:8px}' +
        '.meta div{display:flex;justify-content:space-between;margin:2px 0;gap:8px}' +
        'table.items{width:100%;border-collapse:collapse;font-size:12px}' +
        'table.items th{text-align:left;font-size:11px;border-bottom:1px solid #333;padding:4px 0}' +
        'table.items td{padding:4px 0;border-bottom:1px dashed #ddd;vertical-align:top}' +
        'table.items td.qty,table.items th.qty{width:30px;text-align:center}' +
        'table.items td.rate,table.items th.rate,table.items td.amt,table.items th.amt{width:64px;text-align:right}' +
        '.variant{font-size:10px;color:#555}' +
        '.totals{margin-top:10px;font-size:12px}' +
        '.totals div{display:flex;justify-content:space-between;margin:2px 0}' +
        '.totals .grand{font-size:15px;font-weight:700;border-top:1px solid #333;margin-top:6px;padding-top:6px}' +
        '.foot{margin-top:14px;text-align:center;font-size:11px;color:#555}' +
        '</style></head><body>' +
        '<h1>Hotel Bell Elite</h1>' +
        '<div class="sub">Customer Bill</div>' +
        '<div class="meta">' +
        '<div><span>Order</span><span>' +
        escapeHtml(orderNo) +
        '</span></div>' +
        '<div><span>Table</span><span>' +
        escapeHtml(table) +
        '</span></div>' +
        '<div><span>Type</span><span>' +
        escapeHtml(orderType) +
        '</span></div>' +
        '<div><span>Date</span><span>' +
        escapeHtml(dateLabel || now.toLocaleString()) +
        (when.time && when.date ? ' ' + escapeHtml(when.time) : '') +
        '</span></div>' +
        custRow +
        '</div>' +
        '<table class="items"><thead><tr><th>Item</th><th class="qty">Qty</th><th class="rate">Rate</th><th class="amt">Amt</th></tr></thead>' +
        '<tbody>' +
        (rows ||
          '<tr><td colspan="4" style="text-align:center;color:#555">No items</td></tr>') +
        '</tbody></table>' +
        '<div class="totals">' +
        '<div><span>Subtotal</span><span>' +
        formatInvoiceMoney(totals.subtotal) +
        '</span></div>' +
        '<div><span>Discount' +
        (discHint ? ' ' + discHint : '') +
        '</span><span>-' +
        formatInvoiceMoney(totals.discount) +
        '</span></div>' +
        '<div><span>GST (' +
        GST_RATE * 100 +
        '%)</span><span>' +
        formatInvoiceMoney(totals.gst) +
        '</span></div>' +
        '<div><span>Service Charge' +
        (svcHint ? ' ' + svcHint : '') +
        '</span><span>' +
        formatInvoiceMoney(totals.service) +
        '</span></div>' +
        '<div><span>Tip</span><span>' +
        formatInvoiceMoney(totals.tip) +
        '</span></div>' +
        '<div><span>Round Off</span><span>' +
        formatInvoiceMoney(totals.roundOff) +
        '</span></div>' +
        '<div class="grand"><span>Total</span><span>' +
        formatInvoiceMoney(totals.total) +
        '</span></div>' +
        '</div>' +
        '<div class="foot">Thank you for dining with us!</div>' +
        '</body></html>';
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
    } catch (err) {
      toast('Could not print bill. Try again.');
    }
  }

  function printTodayInvoice(invoiceId, btn) {
    if (!invoiceId) return;
    if (btn) btn.disabled = true;
    fetch('/point-of-sale/api/invoices/' + encodeURIComponent(invoiceId), {
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

  function paintTodayInvoicesModal(payload) {
    var rowsEl = document.getElementById('pos-today-invoices-rows');
    var emptyEl = document.getElementById('pos-today-invoices-empty');
    var wrap = document.getElementById('pos-today-invoices-table-wrap');
    var subEl = document.getElementById('pos-today-invoices-sub');
    var metaEl = document.getElementById('pos-today-invoices-meta');
    var invoices =
      (payload && Array.isArray(payload.invoices) ? payload.invoices : []) || [];
    var count = invoices.length;

    if (subEl) {
      subEl.textContent =
        count === 0
          ? 'No invoices created today yet.'
          : count === 1
            ? '1 invoice created today — view or reprint the bill.'
            : count + ' invoices created today — view or reprint a bill.';
    }
    if (metaEl) {
      metaEl.textContent =
        count === 0
          ? 'Showing 0 invoices'
          : 'Showing ' + count + ' of ' + count + ' invoice' + (count === 1 ? '' : 's');
    }
    if (!rowsEl) return;

    if (!count) {
      rowsEl.innerHTML = '';
      if (wrap) wrap.hidden = true;
      if (emptyEl) emptyEl.hidden = false;
      currentTodayInvoices = [];
      return;
    }
    if (wrap) wrap.hidden = false;
    if (emptyEl) emptyEl.hidden = true;

    var viewSvg =
      '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true">' +
      '<path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7S1 12 1 12z"/>' +
      '<circle cx="12" cy="12" r="3"/></svg>';
    var printSvg =
      '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true">' +
      '<path d="M6 9V2h12v7"/><path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/>' +
      '<path d="M6 14h12v8H6z"/></svg>';

    rowsEl.innerHTML = invoices
      .map(function (inv) {
        var statusKey = String(inv.status || 'open').toLowerCase();
        if (statusKey !== 'closed') statusKey = 'open';
        var statusLabel = INVOICE_STATUS_LABELS[statusKey] || statusKey;
        var typeKey = inv.order_type || 'dine_in';
        var typeLabel =
          inv.order_type_label || ORDER_TYPE_LABELS[typeKey] || typeKey;
        var table = inv.table_label || inv.table || '—';
        var when = formatKotPendingWhen(inv.saved_at || inv.created_at);
        var id = inv.id;
        return (
          '<tr data-today-invoice-id="' +
          escapeHtml(id) +
          '">' +
          '<td><span class="pos-today-invoice-order">' +
          escapeHtml(inv.order_no || '—') +
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
          '<td><span class="pos-kot-table-status is-' +
          escapeHtml(statusKey) +
          '">' +
          escapeHtml(statusLabel) +
          '</span></td>' +
          '<td>' +
          '<div class="pos-today-invoice-actions">' +
          '<button type="button" class="pos-today-invoice-btn pos-today-invoice-btn--view" data-today-invoice-view="' +
          escapeHtml(id) +
          '" title="Open in invoice workspace">' +
          viewSvg +
          '<span>View</span></button>' +
          '<button type="button" class="pos-today-invoice-btn pos-today-invoice-btn--print" data-today-invoice-print="' +
          escapeHtml(id) +
          '" title="Reprint customer bill">' +
          printSvg +
          '<span>Print</span></button>' +
          '</div>' +
          '</td>' +
          '</tr>'
        );
      })
      .join('');

    currentTodayInvoices = invoices;
  }

  function closeTodayInvoicesModal() {
    var modal = document.getElementById('pos-today-invoices-modal');
    if (!modal || modal.hidden) return;
    modal.hidden = true;
    modal.setAttribute('hidden', '');
    modal.setAttribute('aria-hidden', 'true');
  }

  function openTodayInvoicesModal() {
    var modal = document.getElementById('pos-today-invoices-modal');
    if (!modal) return;
    modal.hidden = false;
    modal.removeAttribute('hidden');
    modal.setAttribute('aria-hidden', 'false');
    paintTodayInvoicesModal({ invoices: currentTodayInvoices || [] });
    fetch('/point-of-sale/api/today-invoices', {
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
          toast((data && data.error) || 'Could not load today’s invoices.');
          return;
        }
        currentTodayInvoices = data.invoices || [];
        paintTodayInvoicesModal(data);
      })
      .catch(function () {
        toast('Could not load today’s invoices. Check your connection.');
      });
    var closeBtn = modal.querySelector('.pos-kot-modal-close');
    if (closeBtn) closeBtn.focus();
  }

  function bindTodayInvoicesModal() {
    var openBtn = document.getElementById('pos-quick-today-invoices');
    if (openBtn && openBtn.getAttribute('data-bound') !== '1') {
      openBtn.setAttribute('data-bound', '1');
      openBtn.addEventListener('click', function () {
        openTodayInvoicesModal();
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
        navigateToInvoiceById(viewBtn.getAttribute('data-today-invoice-view'));
        return;
      }

      var printBtn = event.target.closest('[data-today-invoice-print]');
      if (printBtn && modal.contains(printBtn)) {
        event.preventDefault();
        if (printBtn.disabled) return;
        printTodayInvoice(printBtn.getAttribute('data-today-invoice-print'), printBtn);
      }
    });
  }

  function initPosTablesPage() {
    var root = document.getElementById('pos-tables-page');
    if (!root) return;
    /* Soft-nav: paint cache first, then refresh from SQLite API */
    paintTablesPage(root, loadFloorDataCached());
    paintKotPendingBanner(currentKotPending);
    if (typeof global.initEpListboxes === 'function') {
      global.initEpListboxes();
    }
    bindAreaPills(root);
    bindViewToggle(root);
    bindSearch(root);
    bindTileInteractions(root);
    bindKotPendingBanner();
    bindKotTokensModal();
    bindTodayInvoicesModal();
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
  }
})(window);
