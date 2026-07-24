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

  function isOrphanTable(table, areas) {
    if (!table) return true;
    if (!table.areaId) return true;
    return !(areas || []).some(function (a) {
      return a.id === table.areaId;
    });
  }

  function tableGroupIndices(tables, areas, table) {
    var indices = [];
    var assigned =
      table &&
      table.areaId &&
      (areas || []).some(function (a) {
        return a.id === table.areaId;
      });
    var i;
    for (i = 0; i < (tables || []).length; i++) {
      var t = tables[i];
      if (assigned) {
        if (t.areaId === table.areaId) indices.push(i);
      } else if (isOrphanTable(t, areas)) {
        indices.push(i);
      }
    }
    return indices;
  }

  function swapTablesAt(ia, ib) {
    var s = ensureState();
    if (ia < 0 || ib < 0 || ia >= s.tables.length || ib >= s.tables.length) return false;
    var tmp = s.tables[ia];
    s.tables[ia] = s.tables[ib];
    s.tables[ib] = tmp;
    persistState();
    renderFloorList();
    return true;
  }

  function moveTableInArea(tableId, direction) {
    var s = ensureState();
    var table = findItem(tableId);
    if (!table || table.type !== 'table') return false;
    var indices = tableGroupIndices(s.tables, s.areas, table);
    var pos = -1;
    var i;
    for (i = 0; i < indices.length; i++) {
      if (s.tables[indices[i]].id === tableId) {
        pos = i;
        break;
      }
    }
    if (pos < 0) return false;
    var swapWith = direction === 'up' ? pos - 1 : pos + 1;
    if (swapWith < 0 || swapWith >= indices.length) return false;
    return swapTablesAt(indices[pos], indices[swapWith]);
  }

  /** Move a table to a new index in the Tables settings master list. */
  function moveTableToIndex(tableId, newIndex) {
    var s = ensureState();
    var from = -1;
    var i;
    for (i = 0; i < s.tables.length; i++) {
      if (s.tables[i].id === tableId) {
        from = i;
        break;
      }
    }
    if (from < 0) return false;
    newIndex = Math.max(0, Math.min(s.tables.length - 1, newIndex));
    if (from === newIndex) return false;
    var item = s.tables.splice(from, 1)[0];
    s.tables.splice(newIndex, 0, item);
    persistState();
    renderFloorList();
    return true;
  }

  function floorTableRowHtml(table, indexInGroup, groupLen, selected) {
    var canUp = indexInGroup > 0;
    var canDown = indexInGroup < groupLen - 1;
    return (
      '<div class="pos-floor-table-row' +
      (selected ? ' is-selected' : '') +
      '" role="listitem" data-id="' +
      escapeHtml(table.id) +
      '" data-kind="table" data-select-id="' +
      escapeHtml(table.id) +
      '" tabindex="0">' +
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
      '<span class="pos-floor-table-row-order">' +
      '<button type="button" class="pos-floor-order-btn" data-floor-action="move-table-up" data-table-id="' +
      escapeHtml(table.id) +
      '" title="Move up" aria-label="Move ' +
      escapeHtml(table.name) +
      ' up"' +
      (canUp ? '' : ' disabled') +
      '>' +
      '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 14l6-6 6 6"/></svg>' +
      '</button>' +
      '<button type="button" class="pos-floor-order-btn" data-floor-action="move-table-down" data-table-id="' +
      escapeHtml(table.id) +
      '" title="Move down" aria-label="Move ' +
      escapeHtml(table.name) +
      ' down"' +
      (canDown ? '' : ' disabled') +
      '>' +
      '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 10l6 6 6-6"/></svg>' +
      '</button>' +
      '</span>' +
      '</div>'
    );
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
            '<span>Table</span><span>Seats</span><span>Shape</span><span>Status</span><span>Order</span>' +
            '</div>';
          tables.forEach(function (table, idx) {
            html += floorTableRowHtml(table, idx, tables.length, s.selectedId === table.id);
          });
          html += '</div>';
        }
        html += '</section>';
      });

      var orphan = s.tables.filter(function (t) {
        return isOrphanTable(t, s.areas);
      });
      if (orphan.length) {
        html +=
          '<section class="pos-floor-area-block pos-floor-area-block--orphan">' +
          '<header class="pos-floor-area-head"><div class="pos-floor-area-head-copy"><h3>Unassigned</h3><p>' +
          orphan.length +
          ' table' +
          (orphan.length === 1 ? '' : 's') +
          '</p></div></header>' +
          '<div class="pos-floor-table-rows" role="list">' +
          '<div class="pos-floor-table-row pos-floor-table-row--head" aria-hidden="true">' +
          '<span>Table</span><span>Seats</span><span>Shape</span><span>Status</span><span>Order</span>' +
          '</div>';
        orphan.forEach(function (table, idx) {
          html += floorTableRowHtml(table, idx, orphan.length, s.selectedId === table.id);
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

  var TABLES_LIST_GRIP_SVG =
    '<svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">' +
    '<circle cx="5" cy="3.5" r="1.35"/><circle cx="11" cy="3.5" r="1.35"/>' +
    '<circle cx="5" cy="8" r="1.35"/><circle cx="11" cy="8" r="1.35"/>' +
    '<circle cx="5" cy="12.5" r="1.35"/><circle cx="11" cy="12.5" r="1.35"/>' +
    '</svg>';

  function tablesListDragHandleCellHtml(table) {
    return (
      '<td class="pos-set-table-drag-col">' +
      '<span class="pos-set-table-drag-handle" role="button" tabindex="0" ' +
      'data-table-drag-handle="1" data-table-id="' +
      escapeHtml(table.id) +
      '" title="Drag to reorder" aria-label="Drag to reorder ' +
      escapeHtml(table.name) +
      '">' +
      TABLES_LIST_GRIP_SVG +
      '</span>' +
      '</td>'
    );
  }

  function renderTablesList() {
    var tbody = $('#pos-set-tables-list tbody');
    if (!tbody) return;
    var s = ensureState();
    if (!s.tables.length) {
      tbody.innerHTML =
        '<tr class="pos-set-table-empty"><td colspan="6">No tables yet. Add areas and tables on the Floor Layout tab.</td></tr>';
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
          tablesListDragHandleCellHtml(t) +
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
      else if (action === 'move-table-up' || action === 'move-table-down') {
        e.preventDefault();
        e.stopPropagation();
        moveTableInArea(
          btn.getAttribute('data-table-id'),
          action === 'move-table-up' ? 'up' : 'down'
        );
      }
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
    wrap.addEventListener('keydown', function (e) {
      if (e.key !== 'Enter' && e.key !== ' ') return;
      if (e.target.closest('[data-floor-action]')) return;
      var row = e.target.closest('.pos-floor-table-row[data-select-id]');
      if (!row || !wrap.contains(row)) return;
      e.preventDefault();
      selectItem(row.getAttribute('data-select-id'));
    });
  }

  function prefersTablesListReducedMotion() {
    try {
      return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    } catch (err) {
      return false;
    }
  }

  /**
   * Pointer-based Tables list reorder with floating ghost + FLIP sibling shifts.
   * Handle-only; persists via moveTableToIndex → tables[] floor PUT.
   */
  function bindTablesListDrag(table) {
    var DRAG_THRESHOLD_PX = 5;
    var FLIP_MS = 240;
    var SETTLE_MS = 280;
    var FLIP_EASE = 'cubic-bezier(0.22, 1, 0.36, 1)';
    var session = null;
    var suppressRowClickUntil = 0;

    function dataRows() {
      return $all('tbody > tr[data-id]', table);
    }

    function clearTdMotion(row) {
      $all('td', row).forEach(function (td) {
        td.style.transition = '';
        td.style.transform = '';
      });
    }

    function captureRowTops(list) {
      var map = typeof Map === 'function' ? new Map() : null;
      var fallback = [];
      list.forEach(function (row, i) {
        var rect = row.getBoundingClientRect();
        if (map) map.set(row, rect);
        else fallback[i] = { row: row, rect: rect };
      });
      return map || fallback;
    }

    function prevTop(captured, row) {
      if (captured && typeof captured.get === 'function') {
        var rect = captured.get(row);
        return rect ? rect.top : null;
      }
      var i;
      for (i = 0; i < captured.length; i++) {
        if (captured[i].row === row) return captured[i].rect.top;
      }
      return null;
    }

    function flipSiblingRows(captured, excludeRow, animate) {
      var list = dataRows();
      if (!animate) {
        list.forEach(function (row) {
          if (row !== excludeRow) clearTdMotion(row);
        });
        return;
      }
      /* Clear in-flight transforms so Last rects are layout positions. */
      list.forEach(function (row) {
        if (row === excludeRow) return;
        $all('td', row).forEach(function (td) {
          td.style.transition = 'none';
          td.style.transform = '';
        });
      });
      void table.offsetHeight;
      list.forEach(function (row) {
        if (row === excludeRow) return;
        var top = prevTop(captured, row);
        if (top == null) return;
        var dy = top - row.getBoundingClientRect().top;
        if (Math.abs(dy) < 0.5) return;
        $all('td', row).forEach(function (td) {
          td.style.transform = 'translate3d(0,' + dy + 'px,0)';
        });
      });
      void table.offsetHeight;
      list.forEach(function (row) {
        if (row === excludeRow) return;
        $all('td', row).forEach(function (td) {
          td.style.transition = 'transform ' + FLIP_MS + 'ms ' + FLIP_EASE;
          td.style.transform = '';
        });
      });
    }

    function createGhost(row, clientX, clientY) {
      var rect = row.getBoundingClientRect();
      var ghost = document.createElement('table');
      ghost.className = 'pos-set-table pos-set-tables-drag-ghost';
      ghost.setAttribute('aria-hidden', 'true');
      ghost.style.width = rect.width + 'px';
      var body = document.createElement('tbody');
      var clone = row.cloneNode(true);
      clone.classList.remove('is-selected', 'is-drag-placeholder');
      var srcCells = row.children;
      var cloneCells = clone.children;
      var i;
      for (i = 0; i < srcCells.length; i++) {
        if (cloneCells[i]) {
          cloneCells[i].style.width = srcCells[i].getBoundingClientRect().width + 'px';
        }
      }
      body.appendChild(clone);
      ghost.appendChild(body);
      document.body.appendChild(ghost);
      return {
        el: ghost,
        offsetX: clientX - rect.left,
        offsetY: clientY - rect.top,
        width: rect.width,
        height: rect.height
      };
    }

    function positionGhost(ghost, clientX, clientY, settling) {
      var x = clientX - ghost.offsetX;
      var y = clientY - ghost.offsetY;
      ghost.el.style.left = x + 'px';
      ghost.el.style.top = y + 'px';
      if (!settling) {
        ghost.el.style.transform = session && session.reduced ? 'none' : 'scale(1.012)';
      }
    }

    function autoScrollWrap(clientY) {
      var wrap = table.closest('.pos-set-table-wrap');
      if (!wrap) return;
      var rect = wrap.getBoundingClientRect();
      var edge = 40;
      var step = 0;
      if (clientY < rect.top + edge) step = -10;
      else if (clientY > rect.bottom - edge) step = 10;
      if (step) wrap.scrollTop += step;
    }

    function rowUnderPoint(clientX, clientY, placeholder) {
      var stack = document.elementsFromPoint
        ? document.elementsFromPoint(clientX, clientY)
        : [];
      var i;
      var el;
      var row;
      for (i = 0; i < stack.length; i++) {
        el = stack[i];
        if (el.closest && el.closest('.pos-set-tables-drag-ghost')) continue;
        row = el.closest ? el.closest('#pos-set-tables-list tr[data-id]') : null;
        if (row && table.contains(row) && row !== placeholder) return row;
      }
      /* Fallback: geometric hit against current row boxes. */
      var list = dataRows();
      for (i = 0; i < list.length; i++) {
        row = list[i];
        if (row === placeholder) continue;
        var r = row.getBoundingClientRect();
        if (clientY >= r.top && clientY <= r.bottom) return row;
      }
      return null;
    }

    function movePlaceholderToward(clientY) {
      if (!session || !session.placeholder) return;
      var target = rowUnderPoint(session.lastX, clientY, session.placeholder);
      var list = dataRows();
      var tbody = session.placeholder.parentNode;
      if (!tbody) return;

      var beforeRects = captureRowTops(list);
      var nextNode = null;

      if (!target) {
        var first = null;
        var last = null;
        list.forEach(function (row) {
          if (row === session.placeholder) return;
          if (!first) first = row;
          last = row;
        });
        if (!first) return;
        var firstTop = first.getBoundingClientRect().top;
        var lastBottom = last.getBoundingClientRect().bottom;
        if (clientY < firstTop) nextNode = first;
        else if (clientY > lastBottom) nextNode = null;
        else return;
      } else {
        var rect = target.getBoundingClientRect();
        var after = clientY - rect.top > rect.height / 2;
        nextNode = after ? target.nextElementSibling : target;
        if (nextNode === session.placeholder) return;
        if (!after && target.previousElementSibling === session.placeholder) return;
      }

      if (nextNode === session.placeholder) return;
      if (
        (nextNode == null && session.placeholder === tbody.lastElementChild) ||
        (nextNode && session.placeholder.nextElementSibling === nextNode)
      ) {
        return;
      }

      tbody.insertBefore(session.placeholder, nextNode);
      flipSiblingRows(beforeRects, session.placeholder, !session.reduced);
    }

    function teardownMotionStyles() {
      dataRows().forEach(function (row) {
        row.classList.remove('is-drag-placeholder', 'is-dragging', 'is-drag-settling');
        clearTdMotion(row);
      });
      table.classList.remove('is-reordering');
      document.documentElement.classList.remove('pos-set-tables-dragging');
    }

    function finishDrag(commit) {
      if (!session) return;
      var current = session;
      session = null;

      var ghost = current.ghost;
      var placeholder = current.placeholder;
      var movedId = current.id;
      var fromIndex = current.fromIndex;
      var newIndex = dataRows().indexOf(placeholder);
      if (newIndex < 0) newIndex = fromIndex;

      function cleanupAndPersist() {
        if (ghost && ghost.el && ghost.el.parentNode) ghost.el.parentNode.removeChild(ghost.el);
        teardownMotionStyles();
        suppressRowClickUntil = Date.now() + 450;
        if (commit && current.didDrag && newIndex !== fromIndex && movedId) {
          moveTableToIndex(movedId, newIndex);
        }
      }

      if (!current.didDrag || !ghost || !placeholder) {
        cleanupAndPersist();
        return;
      }

      if (current.reduced) {
        cleanupAndPersist();
        return;
      }

      var dest = placeholder.getBoundingClientRect();
      ghost.el.classList.add('is-settling');
      ghost.el.style.left = dest.left + 'px';
      ghost.el.style.top = dest.top + 'px';
      ghost.el.style.transform = 'scale(1)';
      placeholder.classList.add('is-drag-settling');

      var settled = false;
      function settleDone() {
        if (settled) return;
        settled = true;
        cleanupAndPersist();
      }
      ghost.el.addEventListener('transitionend', function onEnd(e) {
        if (e.target !== ghost.el) return;
        if (e.propertyName && e.propertyName !== 'top' && e.propertyName !== 'transform' && e.propertyName !== 'left') {
          return;
        }
        ghost.el.removeEventListener('transitionend', onEnd);
        settleDone();
      });
      setTimeout(settleDone, SETTLE_MS + 80);
    }

    function unbindDocListeners() {
      document.removeEventListener('pointermove', onPointerMove);
      document.removeEventListener('pointerup', onPointerUp);
      document.removeEventListener('pointercancel', onPointerUp);
    }

    function onPointerMove(e) {
      if (!session || e.pointerId !== session.pointerId) return;
      session.lastX = e.clientX;
      session.lastY = e.clientY;

      var dy = e.clientY - session.startY;
      var dx = e.clientX - session.startX;
      if (!session.didDrag) {
        if (Math.abs(dy) < DRAG_THRESHOLD_PX && Math.abs(dx) < DRAG_THRESHOLD_PX) return;
        session.didDrag = true;
        session.reduced = prefersTablesListReducedMotion();
        table.classList.add('is-reordering');
        document.documentElement.classList.add('pos-set-tables-dragging');
        session.placeholder.classList.add('is-drag-placeholder');
        session.ghost = createGhost(session.placeholder, session.startX, session.startY);
        positionGhost(session.ghost, e.clientX, e.clientY, false);
        try {
          session.handle.setPointerCapture(e.pointerId);
        } catch (err) {
          /* ignore */
        }
      }

      e.preventDefault();
      autoScrollWrap(e.clientY);
      positionGhost(session.ghost, e.clientX, e.clientY, false);
      movePlaceholderToward(e.clientY);
    }

    function onPointerUp(e) {
      if (!session || e.pointerId !== session.pointerId) return;
      unbindDocListeners();
      try {
        if (session.handle.releasePointerCapture) {
          session.handle.releasePointerCapture(e.pointerId);
        }
      } catch (err) {
        /* ignore */
      }
      finishDrag(true);
    }

    table.addEventListener('pointerdown', function (e) {
      if (session) return;
      if (e.pointerType === 'mouse' && e.button !== 0) return;
      var handle = e.target.closest('[data-table-drag-handle]');
      if (!handle || !table.contains(handle)) return;
      var row = handle.closest('tr[data-id]');
      if (!row || !table.contains(row)) return;
      var list = dataRows();
      var fromIndex = list.indexOf(row);
      if (fromIndex < 0) return;

      session = {
        pointerId: e.pointerId,
        handle: handle,
        placeholder: row,
        id: row.getAttribute('data-id'),
        fromIndex: fromIndex,
        startX: e.clientX,
        startY: e.clientY,
        lastX: e.clientX,
        lastY: e.clientY,
        didDrag: false,
        reduced: false,
        ghost: null
      };
      document.addEventListener('pointermove', onPointerMove, { passive: false });
      document.addEventListener('pointerup', onPointerUp);
      document.addEventListener('pointercancel', onPointerUp);
      e.preventDefault();
    });

    table.__posTablesSuppressClick = function () {
      return Date.now() < suppressRowClickUntil;
    };
  }

  function bindLists(page) {
    var table = $('#pos-set-tables-list', page);
    if (table && table.getAttribute('data-bound') !== '1') {
      table.setAttribute('data-bound', '1');
      bindTablesListDrag(table);
      table.addEventListener('click', function (e) {
        if (e.target.closest('[data-table-drag-handle]')) {
          e.preventDefault();
          e.stopPropagation();
          return;
        }
        if (table.__posTablesSuppressClick && table.__posTablesSuppressClick()) {
          e.preventDefault();
          e.stopPropagation();
          return;
        }
        if (e.target.closest('[data-floor-action]')) return;
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
  } else if (!global.__deSoftNavInProgress) {
    /* Soft-nav: deWorkspaceReinit calls init once after scripts load — avoid double API fetch. */
    initPosSettingsPage();
  }
})(window);
