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
  }

  function bindKotPendingBanner() {
    var btn = document.getElementById('pos-kot-pending-view');
    if (!btn || btn.getAttribute('data-bound') === '1') return;
    btn.setAttribute('data-bound', '1');
    btn.addEventListener('click', function () {
      var tables = (currentKotPending && currentKotPending.tables) || [];
      if (!tables.length) return;
      var first = tables[0];
      navigateToInvoice(first && first.name);
    });
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
    });
    $all('.pos-table-more[aria-expanded="true"]').forEach(function (btn) {
      btn.setAttribute('aria-expanded', 'false');
    });
  }

  function openTableMenu(btn, tile) {
    closeTableMenu();
    var menu = tile && tile.querySelector('.pos-table-menu');
    if (!menu || !btn) return;
    menu.hidden = false;
    btn.setAttribute('aria-expanded', 'true');
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

  function bindClearAllTables(root) {
    var btn = document.getElementById('pos-tables-clear-all');
    if (!btn || btn.getAttribute('data-bound') === '1') return;
    btn.setAttribute('data-bound', '1');
    btn.addEventListener('click', function () {
      if (!global.confirm('Free every table back to available? This closes any open orders still tied to a table.')) {
        return;
      }
      btn.disabled = true;
      fetch(FLOOR_API + '/clear-all', {
        method: 'POST',
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
            toast('Could not clear tables. Try again.');
            return;
          }
          currentFloor = { areas: data.areas || [], tables: data.tables || [] };
          paintTablesPage(root, currentFloor);
          paintKotPendingBanner(data.kot_pending || emptyKotPending());
          toast('All tables are now available.');
        })
        .catch(function () {
          toast('Could not clear tables. Check your connection and try again.');
        })
        .then(function () {
          btn.disabled = false;
        });
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
    bindClearAllTables(root);
    bindKotPendingBanner();
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
