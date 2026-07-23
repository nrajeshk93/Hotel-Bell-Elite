/**
 * Restaurant Settings — section nav, floor layout editor, SQLite persistence.
 * Soft-nav safe: expose window.initPosSettingsPage and bind idempotently.
 * Floor layout is shared with Tables / Invoice via /point-of-sale/api/floor.
 */
(function (global) {
  'use strict';

  var FLOOR_API = '/point-of-sale/api/floor';
  var SETTINGS_API = '/point-of-sale/api/settings';
  var LEGACY_STORAGE_KEY = 'hbe_pos_floor_demo';
  var MIGRATE_FLAG = 'hbe_pos_floor_db_migrated';
  var state = null;
  var restaurantSettings = {};
  var toastTimer = null;
  var saveTimer = null;
  var saveSeq = 0;
  var floorReady = false;

  var SHAPE_LABELS = { round: 'Round', square: 'Square', rect: 'Rectangle' };
  var STATUS_LABELS = {
    available: 'Available',
    occupied: 'Occupied',
    reserved: 'Reserved',
    blocked: 'Blocked'
  };

  function $(sel, root) {
    return (root || document).querySelector(sel);
  }

  function $all(sel, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(sel));
  }

  function uid(prefix) {
    return prefix + '_' + Math.random().toString(36).slice(2, 9);
  }

  function emptyState() {
    return { selectedId: null, areas: [], tables: [] };
  }

  function cloneFloorPayload(s) {
    return {
      areas: (s.areas || []).map(function (a) {
        return { id: a.id, type: 'area', name: a.name };
      }),
      tables: (s.tables || []).map(function (t) {
        return {
          id: t.id,
          type: 'table',
          name: t.name,
          seats: t.seats,
          shape: t.shape,
          status: t.status,
          areaId: t.areaId
        };
      })
    };
  }

  function applyFloorPayload(payload) {
    var base =
      payload && Array.isArray(payload.areas) && Array.isArray(payload.tables)
        ? payload
        : emptyState();
    state = {
      selectedId: state && state.selectedId ? state.selectedId : null,
      areas: base.areas,
      tables: base.tables
    };
    return state;
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

  function setSaveStatus(text, visible, isError) {
    var labelText = text || 'Saved';
    var chip = $('#pos-set-save-status');
    var label = $('#pos-set-save-status-text');
    var floorEl = $('#pos-floor-saved-indicator');
    if (label) label.textContent = labelText;
    if (chip) {
      chip.hidden = !visible;
      chip.classList.toggle('is-error', !!isError);
      chip.classList.toggle('pos-set-chip--muted', !!isError);
    }
    if (floorEl) {
      floorEl.textContent = labelText;
      floorEl.classList.toggle('is-error', !!isError);
      floorEl.classList.toggle('is-visible', !!visible);
    }
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

  function showToast(message) {
    var el = $('#pos-set-toast');
    if (!el) return;
    el.textContent = message;
    el.hidden = false;
    el.classList.add('is-visible');
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(function () {
      el.classList.remove('is-visible');
    }, 2200);
  }

  function putFloor(payload, opts) {
    opts = opts || {};
    var seq = ++saveSeq;
    if (!opts.silent) setSaveStatus('Saving…', true, false);
    return fetch(FLOOR_API, {
      method: 'PUT',
      credentials: 'same-origin',
      headers: apiHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({
        areas: payload.areas || [],
        tables: payload.tables || []
      })
    })
      .then(function (res) {
        return res.json().then(function (data) {
          return { ok: res.ok && data && data.ok, data: data, status: res.status };
        });
      })
      .then(function (result) {
        if (seq !== saveSeq) return result;
        if (!result.ok) {
          setSaveStatus('Save failed', true, true);
          if (!opts.silent) showToast((result.data && result.data.error) || 'Could not save floor');
          return result;
        }
        applyFloorPayload(result.data);
        setSaveStatus('Saved', true, false);
        if (opts.toast) showToast(opts.toast);
        window.setTimeout(function () {
          if (seq === saveSeq) setSaveStatus('Saved', false, false);
        }, 1600);
        return result;
      })
      .catch(function () {
        if (seq !== saveSeq) return { ok: false };
        setSaveStatus('Save failed', true, true);
        if (!opts.silent) showToast('Could not save floor');
        return { ok: false };
      });
  }

  function scheduleFloorSave(opts) {
    if (!floorReady || !state) return;
    if (saveTimer) clearTimeout(saveTimer);
    setSaveStatus('Saving…', true, false);
    saveTimer = setTimeout(function () {
      putFloor(cloneFloorPayload(state), opts || { silent: true });
    }, 350);
  }

  function persistState(opts) {
    scheduleFloorSave(opts);
  }

  function ensureState() {
    if (state) return state;
    state = emptyState();
    return state;
  }

  function fetchFloorThen(cb) {
    fetch(FLOOR_API, {
      credentials: 'same-origin',
      headers: apiHeaders()
    })
      .then(function (res) {
        return res.json().then(function (data) {
          return { ok: res.ok && data && data.ok, data: data };
        });
      })
      .then(function (result) {
        var server = result.ok
          ? { areas: result.data.areas || [], tables: result.data.tables || [] }
          : emptyState();
        clearLegacyFloor();
        applyFloorPayload(server);
        floorReady = true;
        cb();
      })
      .catch(function () {
        applyFloorPayload(emptyState());
        floorReady = true;
        showToast('Could not load floor layout');
        cb();
      });
  }

  var settingsReady = false;
  var settingsHydrating = false;
  var settingsDirty = {};
  var settingsSaveTimers = {};
  var settingsLoadGen = 0;

  function panelSettingsFields(panel) {
    /* Exclude listbox hiddens — those are keyed by id separately. */
    return $all('[data-pos-set-field]', panel).filter(function (el) {
      return !(el.closest && el.closest('.pos-set-listbox'));
    });
  }

  function ensureFieldKeys(panel) {
    if (!panel) return;
    panelSettingsFields(panel).forEach(function (el, i) {
      if (!el.getAttribute('data-pos-set-key')) {
        el.setAttribute('data-pos-set-key', 'f' + i);
      }
    });
  }

  function syncHoursRow(row) {
    if (!row) return;
    var toggle = row.querySelector('.pos-set-toggle input[type="checkbox"]');
    if (!toggle) return;
    var on = !!toggle.checked;
    $all('input[type="time"]', row).forEach(function (input) {
      input.disabled = !on;
    });
  }

  function syncAllHoursRows(page) {
    $all('.pos-set-hours-row', page || document).forEach(syncHoursRow);
  }

  function applyListboxValue(lb, value) {
    if (!lb) return;
    lb.value = value || '';
    var root = document.getElementById(lb.id + '-listbox');
    var valueEl = root && root.querySelector('.se-filter-chip-value');
    if (!valueEl) return;
    var label = value || '';
    var want = String(value || '');
    var opts = root.querySelectorAll('.se-filter-listbox-option');
    var oi;
    for (oi = 0; oi < opts.length; oi++) {
      if (String(opts[oi].getAttribute('data-value') || '') === want) {
        label = opts[oi].getAttribute('data-label') || opts[oi].textContent || label;
        break;
      }
    }
    valueEl.textContent = label;
    valueEl.classList.toggle('is-placeholder', !value);
  }

  function fetchSettingsThen(cb) {
    var gen = ++settingsLoadGen;
    settingsHydrating = true;
    fetch(SETTINGS_API, {
      credentials: 'same-origin',
      headers: apiHeaders()
    })
      .then(function (res) {
        return res.json().then(function (data) {
          return { ok: res.ok && data && data.ok, data: data };
        });
      })
      .then(function (result) {
        if (gen !== settingsLoadGen) return;
        restaurantSettings =
          result.ok && result.data && result.data.settings && typeof result.data.settings === 'object'
            ? result.data.settings
            : {};
        /* Never clobber panels the user already edited while load was in flight. */
        applyRestaurantSettings(restaurantSettings, { skipDirty: true });
        settingsHydrating = false;
        settingsReady = true;
        flushDirtySettings();
        cb();
      })
      .catch(function () {
        if (gen !== settingsLoadGen) return;
        restaurantSettings = {};
        settingsHydrating = false;
        settingsReady = true;
        flushDirtySettings();
        cb();
      });
  }

  function collectPanelFields(panel) {
    ensureFieldKeys(panel);
    var fields = { v: 2, values: {}, listboxes: {} };
    panelSettingsFields(panel).forEach(function (el) {
      var key = el.getAttribute('data-pos-set-key');
      if (!key) return;
      if (el.type === 'checkbox') {
        fields.values[key] = { kind: 'checkbox', checked: !!el.checked };
      } else {
        fields.values[key] = { kind: 'value', value: el.value };
      }
    });
    $all('.pos-set-listbox input[type="hidden"]', panel).forEach(function (el) {
      if (!el.id) return;
      fields.listboxes[el.id] = el.value;
    });
    return fields;
  }

  function applyPanelFields(panel, fields) {
    if (!panel || fields == null) return;
    ensureFieldKeys(panel);
    var settingsEls = panelSettingsFields(panel);

    /* Legacy index arrays — skip corrupt/short payloads that wiped toggles. */
    if (Array.isArray(fields)) {
      var legacyValues = fields.filter(function (f) {
        return f && typeof f === 'object' && f.kind !== 'listbox';
      });
      if (legacyValues.length !== settingsEls.length) {
        return;
      }
      legacyValues.forEach(function (field, i) {
        var el = settingsEls[i];
        if (!el) return;
        if (field.kind === 'checkbox' || el.type === 'checkbox') el.checked = !!field.checked;
        else el.value = field.value != null ? field.value : '';
      });
      fields.forEach(function (field) {
        if (field && field.kind === 'listbox' && field.id) {
          applyListboxValue(document.getElementById(field.id), field.value);
        }
      });
      syncAllHoursRows(panel);
      return;
    }

    if (typeof fields !== 'object') return;
    var values = fields.values && typeof fields.values === 'object' ? fields.values : fields;
    var listboxes = fields.listboxes && typeof fields.listboxes === 'object' ? fields.listboxes : {};
    settingsEls.forEach(function (el) {
      var key = el.getAttribute('data-pos-set-key');
      var field = key && values[key];
      if (!field || typeof field !== 'object') return;
      if (field.kind === 'checkbox' || el.type === 'checkbox') el.checked = !!field.checked;
      else el.value = field.value != null ? field.value : '';
    });
    Object.keys(listboxes).forEach(function (id) {
      applyListboxValue(document.getElementById(id), listboxes[id]);
    });
    syncAllHoursRows(panel);
  }

  function applyRestaurantSettings(settings, opts) {
    opts = opts || {};
    var panels = settings && settings.panels && typeof settings.panels === 'object' ? settings.panels : null;
    if (!panels) return;
    Object.keys(panels).forEach(function (key) {
      if (opts.skipDirty && settingsDirty[key]) return;
      var panel = document.querySelector('#pos-settings-page [data-panel="' + key + '"]');
      if (panel) applyPanelFields(panel, panels[key]);
    });
  }

  function savePanelSettings(section, opts) {
    opts = opts || {};
    var panel = document.querySelector('#pos-settings-page [data-panel="' + section + '"]');
    if (!panel || section === 'floor' || section === 'tables' || section === 'areas') return;
    syncAllHoursRows(panel);
    var next = Object.assign({}, restaurantSettings);
    if (!next.panels || typeof next.panels !== 'object') next.panels = {};
    next.panels[section] = collectPanelFields(panel);
    setSaveStatus('Saving…', true, false);
    fetch(SETTINGS_API, {
      method: 'PUT',
      credentials: 'same-origin',
      headers: apiHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ settings: next })
    })
      .then(function (res) {
        return res.json().then(function (data) {
          return { ok: res.ok && data && data.ok, data: data };
        });
      })
      .then(function (result) {
        if (!result.ok) {
          setSaveStatus('Save failed', true, true);
          if (!opts.silent) showToast((result.data && result.data.error) || 'Could not save settings');
          return;
        }
        restaurantSettings = (result.data && result.data.settings) || next;
        delete settingsDirty[section];
        setSaveStatus('Saved', true, false);
        if (opts.toast) showToast(opts.toast);
        window.setTimeout(function () {
          setSaveStatus('Saved', false, false);
        }, 1600);
      })
      .catch(function () {
        setSaveStatus('Save failed', true, true);
        if (!opts.silent) showToast('Could not save settings');
      });
  }

  function flushDirtySettings() {
    Object.keys(settingsDirty).forEach(function (section) {
      if (settingsDirty[section]) savePanelSettings(section, { silent: true });
    });
  }

  function scheduleSettingsSave(section, immediate) {
    if (!section) return;
    settingsDirty[section] = true;
    if (!settingsReady || settingsHydrating) return;
    if (settingsSaveTimers[section]) {
      clearTimeout(settingsSaveTimers[section]);
      settingsSaveTimers[section] = null;
    }
    if (immediate) {
      savePanelSettings(section, { silent: true });
      return;
    }
    settingsSaveTimers[section] = setTimeout(function () {
      settingsSaveTimers[section] = null;
      savePanelSettings(section, { silent: true });
    }, 400);
  }

  function findItem(id) {
    var s = ensureState();
    var i;
    for (i = 0; i < s.areas.length; i++) if (s.areas[i].id === id) return s.areas[i];
    for (i = 0; i < s.tables.length; i++) if (s.tables[i].id === id) return s.tables[i];
    return null;
  }

  function escapeHtml(str) {
    return String(str || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function shapeLabel(shape) {
    return SHAPE_LABELS[shape] || shape || '—';
  }

  function statusLabel(status) {
    return STATUS_LABELS[status] || status || 'Available';
  }

  function statusClass(status) {
    if (status === 'occupied') return 'pos-set-badge--warn';
    if (status === 'reserved') return 'pos-set-badge--muted';
    if (status === 'blocked') return 'pos-set-badge--muted';
    return '';
  }

  function updateSelectionChrome() {
    var s = ensureState();
    var delBtn = $('#pos-floor-delete-btn');
    var dupBtn = $('#pos-floor-duplicate-btn');
    if (delBtn) delBtn.disabled = !s.selectedId;
    if (dupBtn) dupBtn.disabled = !s.selectedId;
  }

  function renderFloorList() {
    var list = $('#pos-floor-list');
    if (!list) return;
    var s = ensureState();
    var html = '';

    if (!s.areas.length) {
      html =
        '<div class="pos-floor-list-empty">' +
        '<h3>No areas yet</h3>' +
        '<p>Add an area, then add tables under it.</p>' +
        '</div>';
    } else {
      s.areas.forEach(function (area) {
        var tables = s.tables.filter(function (t) {
          return t.areaId === area.id;
        });
        var areaSelected = s.selectedId === area.id;
        html +=
          '<section class="pos-floor-area-block' +
          (areaSelected ? ' is-selected' : '') +
          '" data-id="' +
          escapeHtml(area.id) +
          '" data-kind="area" role="listitem">' +
          '<header class="pos-floor-area-head" data-select-id="' +
          escapeHtml(area.id) +
          '">' +
          '<div class="pos-floor-area-head-copy">' +
          '<h3>' +
          escapeHtml(area.name) +
          '</h3>' +
          '<p>' +
          tables.length +
          ' table' +
          (tables.length === 1 ? '' : 's') +
          '</p>' +
          '</div>' +
          '<button type="button" class="pos-set-btn pos-set-btn--ghost pos-floor-area-add" data-floor-action="add-table-in-area" data-area-id="' +
          escapeHtml(area.id) +
          '">+ Table</button>' +
          '</header>';

        if (!tables.length) {
          html +=
            '<div class="pos-floor-area-empty">No tables in this area.</div>';
        } else {
          html +=
            '<div class="pos-floor-table-rows" role="list">' +
            '<div class="pos-floor-table-row pos-floor-table-row--head" aria-hidden="true">' +
            '<span>Table</span><span>Seats</span><span>Shape</span><span>Status</span>' +
            '</div>';
          tables.forEach(function (table) {
            var selected = s.selectedId === table.id;
            html +=
              '<button type="button" class="pos-floor-table-row' +
              (selected ? ' is-selected' : '') +
              '" role="listitem" data-id="' +
              escapeHtml(table.id) +
              '" data-kind="table" data-select-id="' +
              escapeHtml(table.id) +
              '">' +
              '<span class="pos-floor-table-row-name">' +
              escapeHtml(table.name) +
              '</span>' +
              '<span>' +
              escapeHtml(String(table.seats || 0)) +
              '</span>' +
              '<span>' +
              escapeHtml(shapeLabel(table.shape)) +
              '</span>' +
              '<span><span class="pos-set-badge ' +
              statusClass(table.status) +
              '">' +
              escapeHtml(statusLabel(table.status)) +
              '</span></span>' +
              '</button>';
          });
          html += '</div>';
        }
        html += '</section>';
      });

      var orphan = s.tables.filter(function (t) {
        return !t.areaId || !s.areas.some(function (a) {
          return a.id === t.areaId;
        });
      });
      if (orphan.length) {
        html +=
          '<section class="pos-floor-area-block pos-floor-area-block--orphan">' +
          '<header class="pos-floor-area-head"><div class="pos-floor-area-head-copy"><h3>Unassigned</h3><p>' +
          orphan.length +
          ' table' +
          (orphan.length === 1 ? '' : 's') +
          '</p></div></header>' +
          '<div class="pos-floor-table-rows" role="list">';
        orphan.forEach(function (table) {
          var selected = s.selectedId === table.id;
          html +=
            '<button type="button" class="pos-floor-table-row' +
            (selected ? ' is-selected' : '') +
            '" role="listitem" data-id="' +
            escapeHtml(table.id) +
            '" data-kind="table" data-select-id="' +
            escapeHtml(table.id) +
            '">' +
            '<span class="pos-floor-table-row-name">' +
            escapeHtml(table.name) +
            '</span>' +
            '<span>' +
            escapeHtml(String(table.seats || 0)) +
            '</span>' +
            '<span>' +
            escapeHtml(shapeLabel(table.shape)) +
            '</span>' +
            '<span><span class="pos-set-badge ' +
            statusClass(table.status) +
            '">' +
            escapeHtml(statusLabel(table.status)) +
            '</span></span>' +
            '</button>';
        });
        html += '</div></section>';
      }
    }

    list.innerHTML = html;
    updateSelectionChrome();
    renderTablesList();
    renderAreasGrid();
  }

  function isPropsModalOpen() {
    var modal = $('#pos-floor-props-modal');
    return !!(modal && modal.classList.contains('active'));
  }

  function setListboxValue(fieldId, value, label) {
    if (typeof global.resetEpListbox === 'function') {
      global.resetEpListbox(fieldId, value, label);
      return;
    }
    var input = document.getElementById(fieldId);
    if (input) input.value = value || '';
    var root = document.getElementById(fieldId + '-listbox');
    if (!root) return;
    var valueEl = root.querySelector('.se-filter-chip-value');
    if (valueEl) {
      valueEl.textContent = label || value || '';
      valueEl.classList.toggle('is-placeholder', !value);
    }
  }

  function rebuildAreaListbox(selectedAreaId) {
    var list = $('#pos-floor-prop-area-list');
    var s = ensureState();
    if (!list) return;
    var selected = selectedAreaId || (s.areas[0] ? s.areas[0].id : '');
    var selectedLabel = 'Select area…';
    list.innerHTML = s.areas
      .map(function (a) {
        var on = a.id === selected;
        if (on) selectedLabel = a.name;
        return (
          '<button type="button" class="se-filter-listbox-option' +
          (on ? ' is-selected' : '') +
          '" role="option" data-value="' +
          a.id +
          '" data-name="' +
          escapeHtml(String(a.name || '').toLowerCase()) +
          '" data-label="' +
          escapeHtml(a.name) +
          '" aria-selected="' +
          (on ? 'true' : 'false') +
          '">' +
          escapeHtml(a.name) +
          '</button>'
        );
      })
      .join('');
    setListboxValue('pos-floor-prop-area', selected, selectedLabel);
  }

  function fillPropsModal() {
    var s = ensureState();
    var item = s.selectedId ? findItem(s.selectedId) : null;
    if (!item) return false;
    var title = $('#pos-floor-props-title');
    if (title) title.textContent = item.type === 'area' ? 'Area' : 'Table';
    var name = $('#pos-floor-prop-name');
    var seats = $('#pos-floor-prop-seats');
    var shape = $('#pos-floor-prop-shape');
    var status = $('#pos-floor-prop-status');
    var tableFields = $('#pos-floor-prop-table-fields');
    if (name) name.value = item.name || '';
    var isTable = item.type === 'table';
    if (tableFields) tableFields.hidden = !isTable;
    if (isTable) {
      if (seats) seats.value = String(item.seats || 2);
      var shapeVal = item.shape || 'square';
      var statusVal = item.status || 'available';
      if (shape) shape.value = shapeVal;
      if (status) status.value = statusVal;
      setListboxValue('pos-floor-prop-shape', shapeVal, shapeLabel(shapeVal));
      setListboxValue('pos-floor-prop-status', statusVal, statusLabel(statusVal));
      rebuildAreaListbox(item.areaId);
    }
    return true;
  }

  function openPropsModal() {
    var modal = $('#pos-floor-props-modal');
    if (!modal || !fillPropsModal()) return;
    modal.classList.add('active');
  }

  function closePropsModal() {
    var modal = $('#pos-floor-props-modal');
    if (modal) modal.classList.remove('active');
  }

  function renderTablesList() {
    var tbody = $('#pos-set-tables-list tbody');
    if (!tbody) return;
    var s = ensureState();
    if (!s.tables.length) {
      tbody.innerHTML =
        '<tr class="pos-set-table-empty"><td colspan="5">No tables yet. Add areas and tables on the Floor Layout tab.</td></tr>';
      return;
    }
    var areaMap = {};
    s.areas.forEach(function (a) {
      areaMap[a.id] = a.name;
    });
    tbody.innerHTML = s.tables
      .map(function (t) {
        return (
          '<tr data-id="' +
          t.id +
          '"' +
          (s.selectedId === t.id ? ' class="is-selected"' : '') +
          '>' +
          '<td>' +
          escapeHtml(t.name) +
          '</td>' +
          '<td>' +
          escapeHtml(areaMap[t.areaId] || '—') +
          '</td>' +
          '<td>' +
          t.seats +
          '</td>' +
          '<td>' +
          escapeHtml(shapeLabel(t.shape)) +
          '</td>' +
          '<td><span class="pos-set-badge ' +
          statusClass(t.status) +
          '">' +
          escapeHtml(statusLabel(t.status)) +
          '</span></td>' +
          '</tr>'
        );
      })
      .join('');
  }

  function renderAreasGrid() {
    var grid = $('#pos-set-areas-grid');
    if (!grid) return;
    var s = ensureState();
    if (!s.areas.length) {
      grid.innerHTML =
        '<p class="pos-menu-empty">No areas yet. Add one from the Floor Layout tab or use Add area above.</p>';
      return;
    }
    grid.innerHTML = s.areas
      .map(function (a) {
        var count = s.tables.filter(function (t) {
          return t.areaId === a.id;
        }).length;
        return (
          '<article class="pos-set-card" data-id="' +
          a.id +
          '">' +
          '<h3>' +
          escapeHtml(a.name) +
          '</h3>' +
          '<p class="pos-set-card-copy">' +
          count +
          ' table' +
          (count === 1 ? '' : 's') +
          '</p>' +
          '<button type="button" class="pos-set-btn pos-set-btn--ghost" data-select-id="' +
          a.id +
          '">Edit on floor</button>' +
          '</article>'
        );
      })
      .join('');
  }

  function selectItem(id) {
    ensureState().selectedId = id || null;
    renderFloorList();
    if (id) openPropsModal();
    else closePropsModal();
  }

  function addTable(areaId) {
    var s = ensureState();
    var n = s.tables.length + 1;
    var resolvedArea = areaId || (s.areas[0] ? s.areas[0].id : null);
    var table = {
      id: uid('t'),
      type: 'table',
      name: 'T' + n,
      seats: 4,
      shape: 'square',
      status: 'available',
      areaId: resolvedArea
    };
    s.tables.push(table);
    persistState();
    showSection('floor');
    selectItem(table.id);
  }

  function addArea() {
    var s = ensureState();
    var n = s.areas.length + 1;
    var area = {
      id: uid('area'),
      type: 'area',
      name: 'Area ' + n
    };
    s.areas.push(area);
    persistState();
    showSection('floor');
    selectItem(area.id);
  }

  function duplicateSelected() {
    var s = ensureState();
    if (!s.selectedId) return;
    var item = findItem(s.selectedId);
    if (!item) return;
    var newId = null;
    if (item.type === 'table') {
      var copy = {
        id: uid('t'),
        type: 'table',
        name: item.name + ' copy',
        seats: item.seats,
        shape: item.shape,
        status: item.status || 'available',
        areaId: item.areaId
      };
      s.tables.push(copy);
      newId = copy.id;
    } else if (item.type === 'area') {
      var areaCopy = {
        id: uid('area'),
        type: 'area',
        name: item.name + ' copy'
      };
      s.areas.push(areaCopy);
      newId = areaCopy.id;
    }
    if (newId) {
      persistState();
      selectItem(newId);
    }
  }

  function deleteSelected() {
    var s = ensureState();
    if (!s.selectedId) return;
    var id = s.selectedId;
    s.tables = s.tables.filter(function (t) {
      return t.id !== id;
    });
    s.areas = s.areas.filter(function (a) {
      return a.id !== id;
    });
    s.tables.forEach(function (t) {
      if (t.areaId === id) t.areaId = s.areas[0] ? s.areas[0].id : null;
    });
    s.selectedId = null;
    persistState();
    closePropsModal();
    renderFloorList();
  }

  var SECTION_STORAGE_KEY = 'hbe_pos_settings_section';
  var VALID_SECTIONS = [
    'general',
    'floor',
    'tables',
    'areas',
    'kitchen',
    'taxes',
    'invoice',
    'payment',
    'menu',
    'printers',
    'integrations'
  ];

  function normalizeSectionKey(key) {
    key = String(key || '')
      .replace(/^#/, '')
      .trim()
      .toLowerCase();
    return VALID_SECTIONS.indexOf(key) >= 0 ? key : '';
  }

  function validSectionKey(key) {
    return !!normalizeSectionKey(key);
  }

  function readStoredSection() {
    var fromHash = '';
    try {
      fromHash = normalizeSectionKey(window.location.hash);
    } catch (err) {
      fromHash = '';
    }
    if (fromHash) return fromHash;
    try {
      var stored = normalizeSectionKey(sessionStorage.getItem(SECTION_STORAGE_KEY));
      if (stored) return stored;
    } catch (err2) {}
    return 'general';
  }

  function sectionUrl(key) {
    var path = window.location.pathname || '/';
    var search = window.location.search || '';
    return path + search + '#' + key;
  }

  function persistSection(key) {
    key = normalizeSectionKey(key) || 'general';
    try {
      sessionStorage.setItem(SECTION_STORAGE_KEY, key);
    } catch (err) {}
    try {
      var nextUrl = sectionUrl(key);
      var currentUrl = window.location.pathname + window.location.search + window.location.hash;
      if (currentUrl !== nextUrl) {
        if (window.history && typeof window.history.replaceState === 'function') {
          window.history.replaceState(window.history.state, '', nextUrl);
        } else {
          window.location.hash = key;
        }
      }
    } catch (err2) {}
  }

  function showSection(key, opts) {
    opts = opts || {};
    var page = $('#pos-settings-page');
    if (!page) return;
    key = normalizeSectionKey(key) || 'general';
    $all('.pos-set-nav-item', page).forEach(function (btn) {
      var active = btn.getAttribute('data-section') === key;
      btn.classList.toggle('is-active', active);
      btn.setAttribute('aria-selected', active ? 'true' : 'false');
    });
    $all('.pos-set-panel', page).forEach(function (panel) {
      var match = panel.getAttribute('data-panel') === key;
      panel.classList.toggle('is-active', match);
      panel.hidden = !match;
    });
    if (key !== 'floor' && key !== 'tables' && key !== 'areas') {
      closePropsModal();
    }
    if (key === 'floor' || key === 'tables' || key === 'areas') {
      renderFloorList();
    }
    if (!opts.skipPersist) persistSection(key);
  }

  function bindSearch(page) {
    var input = $('#pos-set-search', page);
    if (!input || input.getAttribute('data-bound') === '1') return;
    input.setAttribute('data-bound', '1');
    input.addEventListener('input', function () {
      var q = String(input.value || '')
        .trim()
        .toLowerCase();
      var any = false;
      $all('.pos-set-nav-item', page).forEach(function (btn) {
        var hay = (
          (btn.getAttribute('data-search') || '') +
          ' ' +
          (btn.textContent || '')
        ).toLowerCase();
        var show = !q || hay.indexOf(q) !== -1;
        btn.classList.toggle('is-hidden', !show);
        if (show) any = true;
      });
      var empty = $('#pos-set-nav-empty', page);
      if (empty) empty.hidden = any;
    });
  }

  function bindNav(page) {
    $all('.pos-set-nav-item', page).forEach(function (btn) {
      if (btn.getAttribute('data-bound') === '1') return;
      btn.setAttribute('data-bound', '1');
      btn.addEventListener('click', function () {
        showSection(btn.getAttribute('data-section') || 'general');
      });
    });
  }

  function bindSettingsAutoSave(page) {
    if (page.getAttribute('data-settings-autosave') === '1') return;
    page.setAttribute('data-settings-autosave', '1');
    function sectionFromTarget(target) {
      var panel = target && target.closest('[data-panel]');
      return panel ? panel.getAttribute('data-panel') || '' : '';
    }
    page.addEventListener('change', function (e) {
      var t = e.target;
      if (!t) return;
      var hoursRow = t.closest('.pos-set-hours-row');
      if (hoursRow && t.matches('input[type="checkbox"]')) {
        syncHoursRow(hoursRow);
      }
      if (t.matches('[data-pos-set-field]') || t.closest('.pos-set-listbox')) {
        var immediate = t.type === 'checkbox' || t.type === 'hidden';
        scheduleSettingsSave(sectionFromTarget(t), immediate);
      }
    });
    page.addEventListener('input', function (e) {
      var t = e.target;
      if (!t || !t.matches('[data-pos-set-field]')) return;
      if (t.type === 'checkbox') return;
      if (t.disabled) return;
      scheduleSettingsSave(sectionFromTarget(t));
    });
  }

  function bindFloorActions(page) {
    if (page.getAttribute('data-floor-actions-bound') === '1') return;
    page.setAttribute('data-floor-actions-bound', '1');
    page.addEventListener('click', function (e) {
      var btn = e.target.closest('[data-floor-action]');
      if (!btn || !page.contains(btn)) return;
      var action = btn.getAttribute('data-floor-action');
      if (action === 'add-table') addTable();
      else if (action === 'add-table-in-area') addTable(btn.getAttribute('data-area-id'));
      else if (action === 'add-area') addArea();
      else if (action === 'delete') deleteSelected();
      else if (action === 'duplicate') duplicateSelected();
    });
  }

  function applyPropsFromForm() {
    var s = ensureState();
    var item = s.selectedId ? findItem(s.selectedId) : null;
    if (!item) return false;
    var name = $('#pos-floor-prop-name');
    var seats = $('#pos-floor-prop-seats');
    var shape = $('#pos-floor-prop-shape');
    var status = $('#pos-floor-prop-status');
    var area = $('#pos-floor-prop-area');
    if (name) item.name = name.value || item.name;
    if (item.type === 'table') {
      if (seats) item.seats = Math.max(1, parseInt(seats.value, 10) || 2);
      if (shape) item.shape = shape.value || 'square';
      if (status) item.status = status.value || 'available';
      if (area) item.areaId = area.value;
    }
    return true;
  }

  function bindPropsModal(page) {
    var modal = $('#pos-floor-props-modal', page);
    if (!modal || modal.getAttribute('data-bound') === '1') return;
    modal.setAttribute('data-bound', '1');

    modal.addEventListener('click', function (e) {
      if (e.target === modal) {
        closePropsModal();
        return;
      }
      var actionBtn = e.target.closest('[data-floor-props-action]');
      if (!actionBtn || !modal.contains(actionBtn)) return;
      var action = actionBtn.getAttribute('data-floor-props-action');
      if (action === 'cancel') {
        e.preventDefault();
        closePropsModal();
      } else if (action === 'duplicate') {
        e.preventDefault();
        duplicateSelected();
      } else if (action === 'delete') {
        e.preventDefault();
        deleteSelected();
      }
    });

    var form = $('#pos-floor-props-form', modal);
    if (form && form.getAttribute('data-bound') !== '1') {
      form.setAttribute('data-bound', '1');
      form.addEventListener('submit', function (e) {
        e.preventDefault();
        if (!applyPropsFromForm()) return;
        persistState();
        closePropsModal();
        renderFloorList();
      });
    }

    if (document.documentElement.getAttribute('data-pos-floor-esc-bound') !== '1') {
      document.documentElement.setAttribute('data-pos-floor-esc-bound', '1');
      document.addEventListener('keydown', function (e) {
        if (e.key !== 'Escape') return;
        if (!isPropsModalOpen()) return;
        if (document.querySelector('#pos-settings-page [data-se-listbox].is-open')) return;
        closePropsModal();
      });
    }
  }

  function bindFloorList(page) {
    var wrap = $('#pos-floor-canvas-wrap', page);
    if (!wrap || wrap.getAttribute('data-bound') === '1') return;
    wrap.setAttribute('data-bound', '1');
    wrap.addEventListener('click', function (e) {
      if (e.target.closest('[data-floor-action]')) return;
      var target = e.target.closest('[data-select-id]');
      if (!target || !wrap.contains(target)) {
        if (e.target === wrap || e.target.id === 'pos-floor-list') selectItem(null);
        return;
      }
      selectItem(target.getAttribute('data-select-id'));
    });
  }

  function bindLists(page) {
    var table = $('#pos-set-tables-list', page);
    if (table && table.getAttribute('data-bound') !== '1') {
      table.setAttribute('data-bound', '1');
      table.addEventListener('click', function (e) {
        var row = e.target.closest('tr[data-id]');
        if (!row) return;
        selectItem(row.getAttribute('data-id'));
        showSection('floor');
      });
    }
    var areas = $('#pos-set-areas-grid', page);
    if (areas && areas.getAttribute('data-bound') !== '1') {
      areas.setAttribute('data-bound', '1');
      areas.addEventListener('click', function (e) {
        var btn = e.target.closest('[data-select-id]');
        if (!btn) return;
        selectItem(btn.getAttribute('data-select-id'));
        showSection('floor');
      });
    }
  }

  function initPosSettingsPage() {
    var page = document.getElementById('pos-settings-page');
    if (!page) return;
    var section = readStoredSection();
    /* Restore tab before bindings/async work so refresh and soft-nav never flash General. */
    showSection(section, { skipPersist: true });
    floorReady = false;
    settingsReady = false;
    settingsHydrating = true;
    settingsDirty = {};
    state = null;
    $all('[data-panel]', page).forEach(ensureFieldKeys);
    /* Soft-nav replaces DOM — restore last known settings before network round-trip. */
    if (restaurantSettings && restaurantSettings.panels) {
      applyRestaurantSettings(restaurantSettings);
    }
    syncAllHoursRows(page);
    bindSearch(page);
    bindNav(page);
    bindSettingsAutoSave(page);
    bindFloorActions(page);
    bindPropsModal(page);
    bindFloorList(page);
    bindLists(page);
    try {
      if (typeof global.initEpListboxes === 'function') {
        global.initEpListboxes();
      }
      if (typeof global.initPosMenuSettings === 'function') {
        global.initPosMenuSettings();
      }
    } catch (err) {
      /* Never leave the page on General if a widget init throws. */
    }
    showSection(section);
    if (document.documentElement.getAttribute('data-pos-set-hash-bound') !== '1') {
      document.documentElement.setAttribute('data-pos-set-hash-bound', '1');
      window.addEventListener('hashchange', function () {
        if (!document.getElementById('pos-settings-page')) return;
        showSection(readStoredSection());
      });
    }
    fetchFloorThen(function () {
      renderFloorList();
      fetchSettingsThen(function () {});
    });
  }

  global.HBE_POS_FLOOR_STORAGE_KEY = LEGACY_STORAGE_KEY;
  global.HBE_POS_SETTINGS = global.HBE_POS_SETTINGS || {};
  global.HBE_POS_SETTINGS.SECTION_STORAGE_KEY = SECTION_STORAGE_KEY;
  global.HBE_POS_SETTINGS.VALID_SECTIONS = VALID_SECTIONS;
  global.HBE_POS_SETTINGS.readStoredSection = readStoredSection;
  global.HBE_POS_SETTINGS.persistSection = persistSection;
  global.initPosSettingsPage = initPosSettingsPage;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initPosSettingsPage);
  } else {
    initPosSettingsPage();
  }
})(window);
