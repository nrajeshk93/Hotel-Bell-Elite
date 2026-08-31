/**
 * Hotel Settings — independent from Restaurant/Bar POS settings.
 * Soft-nav safe: expose window.initHotelSettingsPage.
 */
(function (global) {
  'use strict';

  var ROOMS_API = '/hotel/api/rooms';
  var SETTINGS_API = '/hotel/api/settings';
  var PAIRING_API = '/hotel/api/print-agent/pairing-code';
  var PRINTERS_KEY = 'hbe_hotel_printers_v1';
  var SECTION_STORAGE_KEY = 'hbe_hotel_settings_section';
  var VALID_SECTIONS = ['floor', 'rooms', 'tariff', 'taxes', 'invoice', 'payment', 'printers', 'asia_tech'];

  var layout = { floors: [], rooms: [] };
  var hotelSettings = {};
  var roomTypes = [];
  var toastTimer = null;
  var settingsSaveTimer = null;
  var layoutSaveTimer = null;
  var settingsLoadGen = 0;
  var layoutLoadGen = 0;

  function $(sel, root) {
    return (root || document).querySelector(sel);
  }

  function $all(sel, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(sel));
  }

  function pageRoot() {
    return document.getElementById('hotel-settings-page') || document.querySelector('[data-hotel-settings]');
  }

  function syncApiPaths() {
    var el = pageRoot();
    var base = (el && el.getAttribute('data-hotel-api-base')) || '/hotel';
    base = String(base).replace(/\/$/, '') || '/hotel';
    ROOMS_API = base + '/api/rooms';
    SETTINGS_API = base + '/api/settings';
    PAIRING_API = base + '/api/print-agent/pairing-code';
  }

  function uid(prefix) {
    return prefix + '_' + Math.random().toString(36).slice(2, 9);
  }

  function showToast(msg) {
    var el = $('#hotel-set-toast');
    if (!el) return;
    el.textContent = msg || '';
    el.hidden = !msg;
    if (toastTimer) clearTimeout(toastTimer);
    if (msg) {
      toastTimer = setTimeout(function () {
        el.hidden = true;
      }, 2200);
    }
  }

  function normalizeSectionKey(key) {
    key = String(key || '')
      .replace(/^#/, '')
      .trim()
      .toLowerCase();
    return VALID_SECTIONS.indexOf(key) >= 0 ? key : '';
  }

  function readStoredSection() {
    if (global.HBE_HOTEL_SETTINGS && typeof global.HBE_HOTEL_SETTINGS.readStoredSection === 'function') {
      return normalizeSectionKey(global.HBE_HOTEL_SETTINGS.readStoredSection()) || 'floor';
    }
    try {
      var fromHash = normalizeSectionKey(global.location.hash);
      if (fromHash) return fromHash;
      return normalizeSectionKey(sessionStorage.getItem(SECTION_STORAGE_KEY)) || 'floor';
    } catch (e) {
      return 'floor';
    }
  }

  function persistSection(key) {
    key = normalizeSectionKey(key) || 'floor';
    try {
      sessionStorage.setItem(SECTION_STORAGE_KEY, key);
    } catch (e) {}
    try {
      var nextUrl =
        (window.location.pathname || '/') + (window.location.search || '') + '#' + key;
      var currentUrl =
        window.location.pathname + window.location.search + window.location.hash;
      if (currentUrl !== nextUrl && window.history && window.history.replaceState) {
        window.history.replaceState(window.history.state, '', nextUrl);
      }
    } catch (e2) {}
  }

  function showSection(key, opts) {
    opts = opts || {};
    var page = pageRoot();
    if (!page) return;
    key = normalizeSectionKey(key) || 'floor';
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
    if (!opts.skipPersist) persistSection(key);
    if (key === 'floor') renderFloors();
    if (key === 'rooms') renderRooms();
  }

  function loadRoomTypes() {
    var el = $('#hotel-set-room-types');
    if (!el) {
      roomTypes = [
        { key: 'premium_without_balcony', label: 'Premium Room' },
        { key: 'premium_deluxe_balcony', label: 'Deluxe with Balcony' },
        { key: 'premium_suite_tub', label: 'Suite Room' }
      ];
      return;
    }
    try {
      roomTypes = JSON.parse(el.textContent || '[]') || [];
    } catch (e) {
      roomTypes = [];
    }
    if (!roomTypes.length) {
      roomTypes = [
        { key: 'premium_without_balcony', label: 'Premium Room' },
        { key: 'premium_deluxe_balcony', label: 'Deluxe with Balcony' },
        { key: 'premium_suite_tub', label: 'Suite Room' }
      ];
    }
  }

  function typeLabel(key) {
    var i;
    for (i = 0; i < roomTypes.length; i++) {
      if (roomTypes[i].key === key) return roomTypes[i].label || key;
    }
    return key || '';
  }

  function floorName(floorId) {
    var i;
    for (i = 0; i < (layout.floors || []).length; i++) {
      if (layout.floors[i].id === floorId) return layout.floors[i].name || floorId;
    }
    return floorId || '';
  }

  function renderFloors() {
    var grid = $('#hotel-set-floors-grid');
    if (!grid) return;
    var floors = layout.floors || [];
    if (!floors.length) {
      grid.innerHTML = '<p class="pos-menu-empty">No floors yet. Add a floor to begin.</p>';
      return;
    }
    grid.innerHTML = floors
      .map(function (floor, idx) {
        return (
          '<article class="pos-set-card hotel-set-floor-card" data-floor-id="' +
          escapeAttr(floor.id) +
          '">' +
          '<h3>Floor ' +
          (idx + 1) +
          '</h3>' +
          '<div class="pos-set-fields">' +
          '<label class="pos-set-field"><span>Name</span>' +
          '<input type="text" data-hotel-floor-name value="' +
          escapeAttr(floor.name || '') +
          '" autocomplete="off"></label>' +
          '</div>' +
          '<div class="hotel-set-floor-actions">' +
          (idx > 0
            ? '<button type="button" data-hotel-floor-move="-1">Move up</button>'
            : '') +
          (idx < floors.length - 1
            ? '<button type="button" data-hotel-floor-move="1">Move down</button>'
            : '') +
          '<button type="button" class="is-danger" data-hotel-floor-delete>Delete</button>' +
          '</div></article>'
        );
      })
      .join('');
  }

  function renderRooms() {
    var body = $('#hotel-set-rooms-body');
    if (!body) return;
    var rooms = (layout.rooms || []).slice().sort(function (a, b) {
      var fa = String(a.floorId || '');
      var fb = String(b.floorId || '');
      if (fa !== fb) return fa < fb ? -1 : 1;
      return String(a.number || '').localeCompare(String(b.number || ''), undefined, {
        numeric: true
      });
    });
    if (!rooms.length) {
      body.innerHTML =
        '<tr><td colspan="4"><p class="pos-menu-empty">No rooms yet. Add a room to begin.</p></td></tr>';
      return;
    }
    body.innerHTML = rooms
      .map(function (room) {
        var status = String(room.status || 'vacant');
        var locked = status === 'occupied' || status === 'reserved';
        var floorSelect = (layout.floors || [])
          .map(function (f) {
            return (
              '<option value="' +
              escapeAttr(f.id) +
              '"' +
              (f.id === room.floorId ? ' selected' : '') +
              '>' +
              escapeHtml(f.name || f.id) +
              '</option>'
            );
          })
          .join('');
        var typeSelect = roomTypes
          .map(function (t) {
            return (
              '<option value="' +
              escapeAttr(t.key) +
              '"' +
              (t.key === room.roomType ? ' selected' : '') +
              '>' +
              escapeHtml(t.label || t.key) +
              '</option>'
            );
          })
          .join('');
        return (
          '<tr data-room-id="' +
          escapeAttr(room.id) +
          '">' +
          '<td><input type="text" data-hotel-room-number value="' +
          escapeAttr(room.number || '') +
          '" autocomplete="off"></td>' +
          '<td><select data-hotel-room-floor>' +
          floorSelect +
          '</select></td>' +
          '<td><select data-hotel-room-type>' +
          typeSelect +
          '</select></td>' +
          '<td><button type="button" class="hotel-set-room-del" data-hotel-room-delete' +
          (locked ? ' disabled title="Cannot delete while ' + escapeAttr(status) + '"' : '') +
          '>Delete</button></td>' +
          '</tr>'
        );
      })
      .join('');
  }

  function escapeHtml(text) {
    return String(text || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function escapeAttr(text) {
    return escapeHtml(text).replace(/'/g, '&#39;');
  }

  function loadLayout(done) {
    var gen = ++layoutLoadGen;
    fetch(ROOMS_API, {
      credentials: 'same-origin',
      headers: { Accept: 'application/json' },
      cache: 'no-store'
    })
      .then(function (resp) {
        if (!resp.ok) throw new Error('load failed');
        return resp.json();
      })
      .then(function (data) {
        if (gen !== layoutLoadGen) return;
        if (!data || !data.ok) throw new Error((data && data.error) || 'load failed');
        layout = {
          floors: Array.isArray(data.floors) ? data.floors : [],
          rooms: Array.isArray(data.rooms) ? data.rooms : []
        };
        renderFloors();
        renderRooms();
        if (typeof done === 'function') done();
      })
      .catch(function () {
        if (gen !== layoutLoadGen) return;
        showToast('Could not load hotel rooms layout');
        if (typeof done === 'function') done();
      });
  }

  function scheduleLayoutSave() {
    if (layoutSaveTimer) clearTimeout(layoutSaveTimer);
    layoutSaveTimer = setTimeout(persistLayout, 350);
  }

  function persistLayout() {
    fetch(ROOMS_API, {
      method: 'PUT',
      credentials: 'same-origin',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        floors: layout.floors || [],
        rooms: layout.rooms || []
      })
    })
      .then(function (resp) {
        return resp.json().then(function (data) {
          return { ok: resp.ok, data: data };
        });
      })
      .then(function (result) {
        if (!result.ok || !result.data || !result.data.ok) {
          showToast((result.data && result.data.error) || 'Could not save layout');
          loadLayout();
          return;
        }
        layout = {
          floors: Array.isArray(result.data.floors) ? result.data.floors : layout.floors,
          rooms: Array.isArray(result.data.rooms) ? result.data.rooms : layout.rooms
        };
        showToast('Saved');
        renderFloors();
        renderRooms();
      })
      .catch(function () {
        showToast('Could not save layout');
      });
  }

  function fieldSnapshot(el) {
    if (!el) return null;
    if (el.type === 'checkbox') {
      return { kind: 'checkbox', value: !!el.checked };
    }
    return { kind: el.tagName === 'TEXTAREA' ? 'textarea' : 'text', value: el.value || '' };
  }

  function collectPanelFields(panel) {
    var values = {};
    $all('[data-hotel-set-field]', panel).forEach(function (el) {
      var key = el.getAttribute('data-hotel-set-key');
      if (!key) return;
      values[key] = fieldSnapshot(el);
    });
    return { values: values };
  }

  function applyPanelFields(panel, fields) {
    if (!panel || !fields) return;
    var values = fields.values && typeof fields.values === 'object' ? fields.values : fields;
    $all('[data-hotel-set-field]', panel).forEach(function (el) {
      var key = el.getAttribute('data-hotel-set-key');
      if (!key || !(key in values)) return;
      var field = values[key];
      var raw = field && typeof field === 'object' ? field.value : field;
      if (el.type === 'checkbox') {
        el.checked = !!raw;
      } else {
        el.value = raw == null ? '' : String(raw);
      }
    });
  }

  function applySettings(settings) {
    hotelSettings = settings && typeof settings === 'object' ? settings : {};
    var panels =
      hotelSettings.panels && typeof hotelSettings.panels === 'object'
        ? hotelSettings.panels
        : {};
    var page = pageRoot();
    if (!page) return;
    Object.keys(panels).forEach(function (key) {
      var panel = page.querySelector('.pos-set-panel[data-panel="' + key + '"]');
      if (panel) applyPanelFields(panel, panels[key]);
    });
  }

  function captureSettingsFromDom() {
    var page = pageRoot();
    var next = { panels: {} };
    if (!page) return next;
    $all('.pos-set-panel', page).forEach(function (panel) {
      var key = panel.getAttribute('data-panel');
      if (!key || key === 'floor' || key === 'rooms' || key === 'printers') return;
      next.panels[key] = collectPanelFields(panel);
    });
    return next;
  }

  function loadSettings() {
    var gen = ++settingsLoadGen;
    fetch(SETTINGS_API, {
      credentials: 'same-origin',
      headers: { Accept: 'application/json' },
      cache: 'no-store'
    })
      .then(function (resp) {
        if (!resp.ok) throw new Error('load failed');
        return resp.json();
      })
      .then(function (data) {
        if (gen !== settingsLoadGen) return;
        if (!data || !data.ok) throw new Error('load failed');
        applySettings(data.settings || {});
        if (!data.settings || !data.settings.panels) {
          /* Seed defaults into DOM then persist once so tax rates exist server-side. */
          var seeded = captureSettingsFromDom();
          if (data.taxRates) {
            seeded.panels = seeded.panels || {};
            seeded.panels.taxes = seeded.panels.taxes || { values: {} };
            seeded.panels.taxes.values = seeded.panels.taxes.values || {};
            if (!seeded.panels.taxes.values.cgst_pct) {
              seeded.panels.taxes.values.cgst_pct = {
                kind: 'text',
                value: String(data.taxRates.cgst_pct != null ? data.taxRates.cgst_pct : 2.5)
              };
            }
            if (!seeded.panels.taxes.values.ugst_pct) {
              seeded.panels.taxes.values.ugst_pct = {
                kind: 'text',
                value: String(data.taxRates.ugst_pct != null ? data.taxRates.ugst_pct : 2.5)
              };
            }
            if (!seeded.panels.taxes.values.cgst_pct_above) {
              seeded.panels.taxes.values.cgst_pct_above = {
                kind: 'text',
                value: String(
                  data.taxRates.cgst_pct_above != null ? data.taxRates.cgst_pct_above : 9
                )
              };
            }
            if (!seeded.panels.taxes.values.ugst_pct_above) {
              seeded.panels.taxes.values.ugst_pct_above = {
                kind: 'text',
                value: String(
                  data.taxRates.ugst_pct_above != null ? data.taxRates.ugst_pct_above : 9
                )
              };
            }
            applySettings(seeded);
          }
        }
      })
      .catch(function () {
        if (gen !== settingsLoadGen) return;
        showToast('Could not load hotel settings');
      });
  }

  function scheduleSettingsSave() {
    if (settingsSaveTimer) clearTimeout(settingsSaveTimer);
    settingsSaveTimer = setTimeout(persistSettings, 350);
  }

  function persistSettings() {
    var payload = captureSettingsFromDom();
    hotelSettings = payload;
    fetch(SETTINGS_API, {
      method: 'PUT',
      credentials: 'same-origin',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ settings: payload })
    })
      .then(function (resp) {
        return resp.json().then(function (data) {
          return { ok: resp.ok, data: data };
        });
      })
      .then(function (result) {
        if (!result.ok || !result.data || !result.data.ok) {
          showToast((result.data && result.data.error) || 'Could not save settings');
          return;
        }
        hotelSettings = result.data.settings || payload;
        showToast('Saved');
      })
      .catch(function () {
        showToast('Could not save settings');
      });
  }

  function readPrinters() {
    try {
      var raw = localStorage.getItem(PRINTERS_KEY);
      var parsed = raw ? JSON.parse(raw) : {};
      return parsed && typeof parsed === 'object' ? parsed : {};
    } catch (e) {
      return {};
    }
  }

  function writePrinters(data) {
    try {
      localStorage.setItem(PRINTERS_KEY, JSON.stringify(data || {}));
    } catch (e) {}
  }

  function applyPrinters() {
    var page = pageRoot();
    if (!page) return;
    var data = readPrinters();
    $all('[data-hotel-pc-printer]', page).forEach(function (el) {
      var key = el.getAttribute('data-hotel-pc-printer');
      if (!key) return;
      el.value = data[key] != null ? String(data[key]) : '';
    });
  }


  function formatPairingExpiry(ttlSeconds, expiresAt) {
    var ttl = Number(ttlSeconds);
    var mins;
    if (ttl > 0) {
      mins = Math.max(1, Math.round(ttl / 60));
      return 'Expires in ' + mins + ' minute' + (mins === 1 ? '' : 's');
    }
    if (expiresAt) return 'Expires ' + String(expiresAt);
    return '';
  }

  function bindPairing(page) {
    var btn = page.querySelector('[data-hotel-action="print-agent-pair"]');
    if (!btn || btn.getAttribute('data-bound') === '1') return;
    btn.setAttribute('data-bound', '1');
    var result = page.querySelector('[data-hotel-pairing-result]');
    var codeEl = page.querySelector('[data-hotel-pairing-code]');
    var expiryEl = page.querySelector('[data-hotel-pairing-expiry]');
    var copyBtn = page.querySelector('[data-hotel-pairing-copy]');
    function showCode(code, ttl, expiresAt) {
      if (codeEl) {
        codeEl.value = code || '';
        try {
          codeEl.focus();
          codeEl.select();
        } catch (e) {}
      }
      if (expiryEl) expiryEl.textContent = formatPairingExpiry(ttl, expiresAt);
      if (result) result.hidden = !code;
    }
    btn.addEventListener('click', function () {
      btn.disabled = true;
      fetch(PAIRING_API, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          Accept: 'application/json',
          'Content-Type': 'application/json'
        },
        body: '{}'
      })
        .then(function (resp) {
          return resp.json().then(function (data) {
            return { ok: resp.ok, status: resp.status, data: data };
          });
        })
        .then(function (resultWrap) {
          var data = resultWrap.data || {};
          if (!resultWrap.ok || !data.ok) {
            showToast(data.error || 'Could not generate pairing code');
            return;
          }
          showCode(data.pairingCode, data.ttlSeconds, data.expiresAt);
          showToast('Pairing code ready');
        })
        .catch(function () {
          showToast('Could not generate pairing code');
        })
        .then(function () {
          btn.disabled = false;
        });
    });
    if (copyBtn && copyBtn.getAttribute('data-bound') !== '1') {
      copyBtn.setAttribute('data-bound', '1');
      copyBtn.addEventListener('click', function () {
        var code = codeEl ? String(codeEl.value || '') : '';
        if (!code) return;
        function copied() {
          showToast('Copied');
        }
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(code).then(copied).catch(function () {
            try {
              codeEl.select();
              document.execCommand('copy');
              copied();
            } catch (e) {}
          });
          return;
        }
        try {
          codeEl.select();
          document.execCommand('copy');
          copied();
        } catch (e2) {}
      });
    }
  }

  function bindPrinters(page) {
    $all('[data-hotel-pc-printer]', page).forEach(function (el) {
      if (el.getAttribute('data-bound') === '1') return;
      el.setAttribute('data-bound', '1');
      el.addEventListener('change', function () {
        var data = readPrinters();
        $all('[data-hotel-pc-printer]', page).forEach(function (input) {
          var key = input.getAttribute('data-hotel-pc-printer');
          if (key) data[key] = input.value || '';
        });
        writePrinters(data);
        showToast('Saved on this PC');
      });
    });
  }

  function bindSearch(page) {
    var input = $('#hotel-set-search', page);
    if (!input || input.getAttribute('data-bound') === '1') return;
    input.setAttribute('data-bound', '1');
    input.addEventListener('input', function () {
      var q = String(input.value || '').trim();
      var any = false;
      var items = $all('.pos-set-nav-item', page);
      var parent = items.length ? items[0].parentNode : null;
      var ranked = items.map(function (btn) {
        var score = q ? window.hbeBestSearchScore([btn.getAttribute('data-search') || '', btn.textContent || ''], q) : 0;
        return { btn: btn, score: score };
      });
      if (q) ranked.sort(function (a, b) { return b.score - a.score; });
      ranked.forEach(function (entry) {
        var show = !q || entry.score >= 0;
        entry.btn.classList.toggle('is-hidden', !show);
        if (show) any = true;
        if (q && parent) parent.appendChild(entry.btn);
      });
      var empty = $('#hotel-set-nav-empty', page);
      if (empty) empty.hidden = any;
    });
  }

  function bindNav(page) {
    $all('.pos-set-nav-item', page).forEach(function (btn) {
      if (btn.getAttribute('data-bound') === '1') return;
      btn.setAttribute('data-bound', '1');
      btn.addEventListener('click', function () {
        showSection(btn.getAttribute('data-section') || 'floor');
      });
    });
  }

  function bindSettingsFields(page) {
    $all('[data-hotel-set-field]', page).forEach(function (el) {
      if (el.getAttribute('data-bound') === '1') return;
      el.setAttribute('data-bound', '1');
      el.addEventListener('change', scheduleSettingsSave);
      el.addEventListener('input', scheduleSettingsSave);
    });
  }

  function bindFloorActions(page) {
    var addBtn = page.querySelector('[data-hotel-action="add-floor"]');
    if (addBtn && addBtn.getAttribute('data-bound') !== '1') {
      addBtn.setAttribute('data-bound', '1');
      addBtn.addEventListener('click', function () {
        var n = (layout.floors || []).length + 1;
        layout.floors = layout.floors || [];
        layout.floors.push({ id: uid('floor'), name: 'Floor ' + n });
        renderFloors();
        scheduleLayoutSave();
      });
    }
    var grid = $('#hotel-set-floors-grid', page);
    if (grid && grid.getAttribute('data-bound') !== '1') {
      grid.setAttribute('data-bound', '1');
      grid.addEventListener('change', function (ev) {
        var input = ev.target.closest('[data-hotel-floor-name]');
        if (!input) return;
        var card = input.closest('[data-floor-id]');
        if (!card) return;
        var id = card.getAttribute('data-floor-id');
        layout.floors.forEach(function (f) {
          if (f.id === id) f.name = input.value || f.name;
        });
        scheduleLayoutSave();
      });
      grid.addEventListener('click', function (ev) {
        var card = ev.target.closest('[data-floor-id]');
        if (!card) return;
        var id = card.getAttribute('data-floor-id');
        var moveBtn = ev.target.closest('[data-hotel-floor-move]');
        if (moveBtn) {
          var dir = Number(moveBtn.getAttribute('data-hotel-floor-move') || 0);
          var idx = -1;
          layout.floors.forEach(function (f, i) {
            if (f.id === id) idx = i;
          });
          var next = idx + dir;
          if (idx < 0 || next < 0 || next >= layout.floors.length) return;
          var tmp = layout.floors[idx];
          layout.floors[idx] = layout.floors[next];
          layout.floors[next] = tmp;
          renderFloors();
          scheduleLayoutSave();
          return;
        }
        if (ev.target.closest('[data-hotel-floor-delete]')) {
          var roomsOnFloor = (layout.rooms || []).filter(function (r) {
            return r.floorId === id;
          });
          var blocked = roomsOnFloor.some(function (r) {
            return r.status === 'occupied' || r.status === 'reserved';
          });
          if (blocked) {
            showToast('Cannot delete a floor with occupied or reserved rooms');
            return;
          }
          if (roomsOnFloor.length) {
            showToast('Move or delete rooms on this floor first');
            return;
          }
          layout.floors = (layout.floors || []).filter(function (f) {
            return f.id !== id;
          });
          renderFloors();
          scheduleLayoutSave();
        }
      });
    }
  }

  function bindRoomActions(page) {
    var addBtn = page.querySelector('[data-hotel-action="add-room"]');
    if (addBtn && addBtn.getAttribute('data-bound') !== '1') {
      addBtn.setAttribute('data-bound', '1');
      addBtn.addEventListener('click', function () {
        var floors = layout.floors || [];
        if (!floors.length) {
          showToast('Add a floor before adding rooms');
          return;
        }
        var type = (roomTypes[0] && roomTypes[0].key) || 'premium_deluxe_balcony';
        layout.rooms = layout.rooms || [];
        var number = String(100 + layout.rooms.length + 1);
        layout.rooms.push({
          id: uid('room'),
          number: number,
          floorId: floors[0].id,
          roomType: type,
          roomTypeLabel: typeLabel(type),
          status: 'vacant'
        });
        renderRooms();
        scheduleLayoutSave();
      });
    }
    var body = $('#hotel-set-rooms-body', page);
    if (body && body.getAttribute('data-bound') !== '1') {
      body.setAttribute('data-bound', '1');
      body.addEventListener('change', function (ev) {
        var row = ev.target.closest('[data-room-id]');
        if (!row) return;
        var id = row.getAttribute('data-room-id');
        var room = null;
        (layout.rooms || []).forEach(function (r) {
          if (r.id === id) room = r;
        });
        if (!room) return;
        var numberEl = row.querySelector('[data-hotel-room-number]');
        var floorEl = row.querySelector('[data-hotel-room-floor]');
        var typeEl = row.querySelector('[data-hotel-room-type]');
        if (numberEl) room.number = numberEl.value || room.number;
        if (floorEl) room.floorId = floorEl.value || room.floorId;
        if (typeEl) {
          room.roomType = typeEl.value || room.roomType;
          room.roomTypeLabel = typeLabel(room.roomType);
        }
        scheduleLayoutSave();
      });
      body.addEventListener('click', function (ev) {
        var del = ev.target.closest('[data-hotel-room-delete]');
        if (!del || del.disabled) return;
        var row = del.closest('[data-room-id]');
        if (!row) return;
        var id = row.getAttribute('data-room-id');
        layout.rooms = (layout.rooms || []).filter(function (r) {
          return r.id !== id;
        });
        renderRooms();
        scheduleLayoutSave();
      });
    }
  }

  function initHotelSettingsPage() {
    var page = pageRoot();
    if (!page) return;
    syncApiPaths();
    loadRoomTypes();
    bindSearch(page);
    bindNav(page);
    bindSettingsFields(page);
    bindPrinters(page);
    bindPairing(page);
    bindFloorActions(page);
    bindRoomActions(page);
    applyPrinters();
    showSection(readStoredSection(), { skipPersist: false });
    loadLayout();
    loadSettings();
  }

  global.initHotelSettingsPage = initHotelSettingsPage;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initHotelSettingsPage);
  } else {
    initHotelSettingsPage();
  }
})(window);
