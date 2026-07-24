/**
 * Restaurant Menu & Margin Calculator.
 * Soft-nav safe: window.initPosMenuSettings / window.initPosMenuPage.
 *
 * Margin % badges (must match db.py):
 *   ≥60% healthy (green), 30–60% moderate (orange), <30% low (red).
 * Food cost uses Product Master approximate_price × recipe qty (unit-converted).
 * Row click opens Menu Details popup (not the ⋮ actions menu).
 */
(function (global) {
  'use strict';

  var CATEGORIES_API = '/point-of-sale/api/menu/categories';
  var ITEMS_API = '/point-of-sale/api/menu/items';
  var PRODUCTS_API = '/point-of-sale/api/menu/products';

  /** Margin band thresholds — keep in sync with db.POS_MENU_MARGIN_* */
  var MARGIN_HEALTHY_PCT = 60;
  var MARGIN_MODERATE_PCT = 30;

  var categories = [];
  var items = [];
  var products = [];
  var productsById = {};
  var selectedCategoryId = null;
  var productsLoaded = false;
  var busy = false;
  var detailsItem = null;
  var detailsBusy = false;
  var detailsTab = 'overview';
  var openMenuItemId = null;

  /** Debounced item-modal persist (invoice-style). */
  var ITEM_AUTOSAVE_DELAY_MS = 450;
  var itemAutosaveTimer = null;
  var itemDirty = false;
  var itemDirtyEpoch = 0;
  var itemSaveInflight = null;

  var filterSearch = '';
  var filterCategory = '';
  var filterStatus = '';
  /** Active column sort — persists across filter / table re-renders (Expense Ledger pattern). */
  var sortKey = '';
  var sortAscending = true;

  function $(sel, root) {
    return (root || document).querySelector(sel);
  }

  function $all(sel, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(sel));
  }

  function escapeHtml(str) {
    return String(str == null ? '' : str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function formatMoney(n) {
    if (n == null || n === '') return '—';
    var v = Number(n);
    if (!isFinite(v)) return '—';
    return '₹' + v.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  function formatPct(n) {
    if (n == null || n === '') return '—';
    var v = Number(n);
    if (!isFinite(v)) return '—';
    return v.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + '%';
  }

  function showToast(message) {
    if (typeof global.showPosSettingsToast === 'function') {
      global.showPosSettingsToast(message);
      return;
    }
    var el = $('#pos-set-toast');
    if (!el) return;
    el.textContent = message || '';
    el.hidden = false;
    el.classList.add('is-visible');
    clearTimeout(showToast._t);
    showToast._t = setTimeout(function () {
      el.classList.remove('is-visible');
    }, 2200);
  }

  function setErr(el, msg) {
    if (!el) return;
    if (msg) {
      el.hidden = false;
      el.textContent = msg;
    } else {
      el.hidden = true;
      el.textContent = '';
    }
  }

  function findCategory(id) {
    var sid = id == null ? null : Number(id);
    for (var i = 0; i < categories.length; i++) {
      if (Number(categories[i].id) === sid) return categories[i];
    }
    return null;
  }

  function findItem(id) {
    var sid = id == null ? null : Number(id);
    for (var i = 0; i < items.length; i++) {
      if (Number(items[i].id) === sid) return items[i];
    }
    return null;
  }

  function marginBand(pct) {
    if (pct == null || pct === '' || !isFinite(Number(pct))) return null;
    var v = Number(pct);
    if (v >= MARGIN_HEALTHY_PCT) return 'healthy';
    if (v >= MARGIN_MODERATE_PCT) return 'moderate';
    return 'low';
  }

  var PRODUCT_PLACEHOLDER = 'Add ingredient…';
  var recipeDraft = [];

  function setListboxValue(fieldId, value, label) {
    if (typeof global.resetEpListbox === 'function') {
      global.resetEpListbox(fieldId, value || '', label || PRODUCT_PLACEHOLDER);
      return;
    }
    var input = document.getElementById(fieldId);
    if (input) input.value = value || '';
  }

  function productLabel(p) {
    if (!p) return '';
    return String(p.name || '').trim();
  }

  function normalizeProductUnit(productUnit) {
    var u = String(productUnit || '').trim().toLowerCase();
    if (u === 'ltr' || u === 'l' || u === 'litre') return 'liter';
    if (u === 'gram' || u === 'grams') return 'g';
    if (u === 'kilogram' || u === 'kgs') return 'kg';
    if (u === 'pc' || u === 'piece' || u === 'pieces') return 'pcs';
    return u || 'pcs';
  }

  function recipeUnitsForProduct(productUnit) {
    var u = normalizeProductUnit(productUnit);
    if (u === 'kg' || u === 'g') return ['g', 'kg'];
    if (u === 'liter' || u === 'ml') return ['ml', 'liter'];
    if (u === 'dozen') return ['pcs', 'dozen'];
    if (u === 'bunch' || u === 'bottle' || u === 'pack' || u === 'case' || u === 'pcs') {
      return [u];
    }
    return [u];
  }

  function defaultRecipeUnit(productUnit) {
    var u = normalizeProductUnit(productUnit);
    if (u === 'kg' || u === 'g') return 'g';
    if (u === 'liter' || u === 'ml') return 'ml';
    if (u === 'dozen') return 'pcs';
    return u || 'pcs';
  }

  function coerceRecipeUnit(productUnit, selected) {
    var allowed = recipeUnitsForProduct(productUnit);
    var want = String(selected || '').trim();
    if (want && allowed.indexOf(want) !== -1) return want;
    var lower = want.toLowerCase();
    for (var i = 0; i < allowed.length; i++) {
      if (allowed[i].toLowerCase() === lower) return allowed[i];
    }
    return defaultRecipeUnit(productUnit);
  }

  function recipeUnitLabel(unit) {
    var u = String(unit || '').trim().toLowerCase();
    if (u === 'g' || u === 'gram' || u === 'grams') return 'Gram';
    if (u === 'kg' || u === 'kilogram' || u === 'kgs') return 'Kg';
    if (u === 'ml') return 'ml';
    if (u === 'liter' || u === 'ltr' || u === 'l' || u === 'litre') return 'Liter';
    if (u === 'pcs' || u === 'pc') return 'Pcs';
    if (u === 'dozen') return 'Dozen';
    if (u === 'bunch') return 'Bunch';
    if (u === 'bottle') return 'Bottle';
    if (u === 'pack') return 'Pack';
    if (u === 'case') return 'Case';
    return String(unit || '').trim() || 'Unit';
  }

  function unitListboxHtml(productId, productUnit, selected) {
    var fid = 'pos-menu-recipe-unit-' + String(productId);
    var units = recipeUnitsForProduct(productUnit);
    var want = coerceRecipeUnit(productUnit, selected);
    var wantLabel = recipeUnitLabel(want);
    if (units.indexOf(want) === -1) units = [want].concat(units);
    var options = units
      .map(function (u) {
        var on = u === want;
        var label = recipeUnitLabel(u);
        return (
          '<button type="button" class="se-filter-listbox-option' +
          (on ? ' is-selected' : '') +
          '" role="option" data-value="' +
          escapeHtml(u) +
          '" data-name="' +
          escapeHtml(String(label).toLowerCase()) +
          '" data-label="' +
          escapeHtml(label) +
          '" aria-selected="' +
          (on ? 'true' : 'false') +
          '">' +
          escapeHtml(label) +
          '</button>'
        );
      })
      .join('');
    return (
      '<div class="se-filter-chip se-filter-chip--payment se-filter-chip--listbox ep-form-listbox pos-menu-unit-listbox" data-se-listbox data-se-listbox-change="onPosMenuRecipeUnitChanged" id="' +
      escapeHtml(fid) +
      '-listbox">' +
      '<span class="se-filter-chip-label visually-hidden" id="' +
      escapeHtml(fid) +
      '-label">Unit</span>' +
      '<div class="se-filter-chip-control">' +
      '<input type="hidden" id="' +
      escapeHtml(fid) +
      '" data-recipe-unit value="' +
      escapeHtml(want) +
      '">' +
      '<button type="button" class="se-filter-chip-trigger" id="' +
      escapeHtml(fid) +
      '-trigger" aria-haspopup="listbox" aria-expanded="false" aria-controls="' +
      escapeHtml(fid) +
      '-list" aria-labelledby="' +
      escapeHtml(fid) +
      '-label ' +
      escapeHtml(fid) +
      '-value">' +
      '<span class="se-filter-chip-value" id="' +
      escapeHtml(fid) +
      '-value">' +
      escapeHtml(wantLabel) +
      '</span>' +
      '</button>' +
      '<span class="se-filter-chip-chev" aria-hidden="true">' +
      '<svg viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg>' +
      '</span>' +
      '</div>' +
      '<div class="se-filter-listbox" id="' +
      escapeHtml(fid) +
      '-list" role="listbox" aria-labelledby="' +
      escapeHtml(fid) +
      '-label" hidden>' +
      options +
      '</div></div>'
    );
  }

  function syncRecipeDraftFromDom() {
    var list = $('#pos-menu-recipe-list');
    if (!list) return;
    var next = [];
    $all('.pos-menu-recipe-row', list).forEach(function (row) {
      var pid = row.getAttribute('data-product-id');
      var qtyEl = row.querySelector('[data-recipe-qty]');
      var unitEl = row.querySelector('[data-recipe-unit]');
      if (!pid) return;
      next.push({
        product_id: Number(pid),
        product_name: row.getAttribute('data-product-name') || '',
        product_unit: row.getAttribute('data-product-unit') || '',
        qty: qtyEl ? qtyEl.value : '',
        unit: unitEl ? unitEl.value : 'g'
      });
    });
    recipeDraft = next;
  }

  function renderRecipeRows() {
    var list = $('#pos-menu-recipe-list');
    var empty = $('#pos-menu-recipe-empty');
    if (!list) return;
    if (!recipeDraft.length) {
      list.innerHTML = '';
      if (empty) empty.hidden = false;
      return;
    }
    if (empty) empty.hidden = true;
    list.innerHTML = recipeDraft
      .map(function (line) {
        var name = line.product_name || (productsById[String(line.product_id)] || {}).name || 'Product';
        var hint = line.product_unit || (productsById[String(line.product_id)] || {}).default_unit || '';
        var qty = line.qty != null && line.qty !== '' ? String(line.qty) : '';
        var unit = coerceRecipeUnit(hint, line.unit);
        var qtyPh = unit === 'g' || unit === 'ml' ? 'e.g. 150' : 'Qty';
        return (
          '<li class="pos-menu-recipe-row" data-product-id="' +
          escapeHtml(line.product_id) +
          '" data-product-name="' +
          escapeHtml(name) +
          '" data-product-unit="' +
          escapeHtml(hint) +
          '">' +
          '<div class="pos-menu-recipe-row-main">' +
          '<strong>' +
          escapeHtml(name) +
          '</strong>' +
          (hint ? '<small>' + escapeHtml(hint) + '</small>' : '') +
          '</div>' +
          '<div class="pos-menu-recipe-row-qty">' +
          '<label class="pos-menu-recipe-qty-label"><span class="visually-hidden">Quantity</span>' +
          '<input type="number" min="0.001" step="any" data-recipe-qty placeholder="' +
          escapeHtml(qtyPh) +
          '" value="' +
          escapeHtml(qty) +
          '"></label>' +
          unitListboxHtml(line.product_id, hint, unit) +
          '</div>' +
          '<button type="button" class="pos-menu-icon-btn pos-menu-icon-btn--danger" data-pos-menu-action="remove-recipe" title="Remove ingredient" aria-label="Remove ingredient">' +
          '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18 6 6 18M6 6l12 12"/></svg>' +
          '</button>' +
          '</li>'
        );
      })
      .join('');
    if (typeof global.initEpListboxes === 'function') {
      global.initEpListboxes();
    }
  }

  function addRecipeLine(productId, qty, unit) {
    var pid = Number(productId);
    if (!isFinite(pid)) return;
    syncRecipeDraftFromDom();
    for (var i = 0; i < recipeDraft.length; i++) {
      if (Number(recipeDraft[i].product_id) === pid) {
        showToast('That product is already in the recipe.');
        setListboxValue('pos-menu-item-product', '', PRODUCT_PLACEHOLDER);
        return;
      }
    }
    var p = productsById[String(pid)];
    var productUnit = (p && p.default_unit) || '';
    recipeDraft.push({
      product_id: pid,
      product_name: (p && p.name) || '',
      product_unit: productUnit,
      qty: qty != null && qty !== '' ? qty : '',
      unit: coerceRecipeUnit(productUnit, unit)
    });
    renderRecipeRows();
    setListboxValue('pos-menu-item-product', '', PRODUCT_PLACEHOLDER);
    markItemDirty();
    setTimeout(function () {
      var rows = document.querySelectorAll('#pos-menu-recipe-list [data-recipe-qty]');
      var last = rows[rows.length - 1];
      if (last) last.focus();
    }, 20);
  }

  function collectRecipePayload(opts) {
    opts = opts || {};
    var skipIncomplete = !!opts.skipIncomplete;
    syncRecipeDraftFromDom();
    var out = [];
    for (var i = 0; i < recipeDraft.length; i++) {
      var line = recipeDraft[i];
      var label = line.product_name || 'ingredient';
      var rawQty = line.qty;
      if (rawQty === '' || rawQty == null) {
        if (skipIncomplete) continue;
        return { error: 'Enter quantity for ' + label + '.' };
      }
      var qty = Number(rawQty);
      if (!isFinite(qty) || qty <= 0) {
        if (skipIncomplete) continue;
        return { error: 'Quantity for ' + label + ' must be greater than zero.' };
      }
      var unit = coerceRecipeUnit(line.product_unit, line.unit);
      var allowed = recipeUnitsForProduct(line.product_unit);
      if (allowed.indexOf(unit) === -1) {
        if (skipIncomplete) continue;
        return { error: 'Choose a valid unit for ' + label + '.' };
      }
      out.push({ product_id: Number(line.product_id), qty: qty, unit: unit });
    }
    return { recipe: out };
  }

  function rebuildProductListbox() {
    var list = $('#pos-menu-item-product-list');
    if (!list) return;
    var wrap = list.querySelector('.ep-listbox-options');
    if (!wrap) {
      var searchWrap = list.querySelector('.ep-listbox-search-wrap');
      if (!searchWrap) {
        list.innerHTML =
          '<div class="ep-listbox-search-wrap">' +
          '<input type="search" class="ep-listbox-search" placeholder="Search…" autocomplete="off" aria-label="Search Product Master">' +
          '</div><div class="ep-listbox-options"></div>';
        var root = list.closest('[data-se-listbox]');
        if (root) root.__epListboxBound = false;
      } else if (!list.querySelector('.ep-listbox-options')) {
        var options = document.createElement('div');
        options.className = 'ep-listbox-options';
        list.appendChild(options);
      }
      wrap = list.querySelector('.ep-listbox-options') || list;
    }
    var html = products
      .map(function (p) {
        var id = String(p.id);
        var label = productLabel(p);
        return (
          '<button type="button" class="se-filter-listbox-option" role="option" data-value="' +
          escapeHtml(id) +
          '" data-name="' +
          escapeHtml(String(label).toLowerCase()) +
          '" data-label="' +
          escapeHtml(label) +
          '" data-product-name="' +
          escapeHtml(p.name || '') +
          '" data-product-unit="' +
          escapeHtml(p.default_unit || '') +
          '" aria-selected="false">' +
          escapeHtml(label) +
          '</button>'
        );
      })
      .join('');
    wrap.innerHTML = html || '<div class="pos-menu-empty" style="padding:10px 12px">No products in Product Master.</div>';
    setListboxValue('pos-menu-item-product', '', PRODUCT_PLACEHOLDER);
  }

  function clearFilterListboxPlaceholder(root) {
    if (!root) return;
    var valueEl = root.querySelector('.se-filter-chip-value');
    if (valueEl) valueEl.classList.remove('is-placeholder', 'staff-supplier-placeholder');
  }

  function fillCategoryFilterListbox(filterVal) {
    var wrap = $('#pos-menu-filter-category-options');
    var root = $('#pos-menu-filter-category-listbox');
    var want = filterVal == null ? filterCategory : filterVal;
    want = want == null ? '' : String(want);
    if (want && !categories.some(function (c) { return String(c.id) === want; })) {
      want = '';
      filterCategory = '';
    }
    if (!wrap) return;
    var html =
      '<button type="button" class="se-filter-listbox-option' +
      (!want ? ' is-selected' : '') +
      '" role="option" data-value="" data-name="all categories" data-label="All Categories" aria-selected="' +
      (!want ? 'true' : 'false') +
      '">All Categories</button>' +
      categories
        .map(function (c) {
          var id = String(c.id);
          var on = id === want;
          var name = c.name || '';
          return (
            '<button type="button" class="se-filter-listbox-option' +
            (on ? ' is-selected' : '') +
            '" role="option" data-value="' +
            escapeHtml(id) +
            '" data-name="' +
            escapeHtml(String(name).toLowerCase()) +
            '" data-label="' +
            escapeHtml(name) +
            '" aria-selected="' +
            (on ? 'true' : 'false') +
            '">' +
            escapeHtml(name) +
            '</button>'
          );
        })
        .join('');
    wrap.innerHTML = html;
    var label = 'All Categories';
    if (want) {
      var cat = findCategory(want);
      label = (cat && cat.name) || 'All Categories';
      if (!cat) want = '';
    }
    setListboxValue('pos-menu-filter-category', want, label);
    if (!want) clearFilterListboxPlaceholder(root);
  }

  function fillCategorySelects() {
    var filter = $('#pos-menu-filter-category');
    var modal = $('#pos-menu-item-category');
    var filterVal = filterCategory || (filter ? filter.value : '') || '';
    var modalVal = modal ? modal.value : '';
    fillCategoryFilterListbox(filterVal);
    if (modal) {
      modal.innerHTML =
        '<option value="">Select category…</option>' +
        categories
          .map(function (c) {
            return (
              '<option value="' +
              escapeHtml(c.id) +
              '">' +
              escapeHtml(c.name) +
              '</option>'
            );
          })
          .join('');
      if (modalVal) modal.value = modalVal;
    }
  }

  function itemStatus(it) {
    if (it.status) return it.status === 'hidden' ? 'hidden' : 'visible';
    if (it.category_visible === false) return 'hidden';
    var cat = findCategory(it.category_id);
    if (cat && !cat.is_visible) return 'hidden';
    return 'visible';
  }

  function filteredItems() {
    var q = String(filterSearch || '')
      .trim()
      .toLowerCase();
    return items.filter(function (it) {
      if (filterCategory && Number(it.category_id) !== Number(filterCategory)) return false;
      var st = itemStatus(it);
      if (filterStatus && st !== filterStatus) return false;
      if (!q) return true;
      var hay = [it.name, it.code, it.variant, it.category_name, (findCategory(it.category_id) || {}).name]
        .filter(Boolean)
        .join(' ')
        .toLowerCase();
      return hay.indexOf(q) !== -1;
    });
  }

  function itemCategoryName(it) {
    return it.category_name || (findCategory(it.category_id) || {}).name || '';
  }

  function itemSortValue(it, key, type) {
    var raw = '';
    if (key === 'name') raw = it.name || '';
    else if (key === 'category') raw = itemCategoryName(it);
    else if (key === 'rate') raw = it.rate;
    else if (key === 'food_cost') raw = it.food_cost;
    else if (key === 'gross_margin') raw = it.gross_margin;
    else if (key === 'margin_pct') raw = it.margin_pct;
    else if (key === 'status') raw = itemStatus(it) === 'hidden' ? 'Hidden' : 'Visible';
    else raw = '';
    if (type === 'number') {
      var n = Number(raw);
      return isFinite(n) ? n : 0;
    }
    return String(raw == null ? '' : raw).toLowerCase();
  }

  function sortedFilteredItems() {
    var rows = filteredItems().slice();
    if (!sortKey) return rows;
    var table = $('#pos-menu-table');
    var th = table && table.querySelector('th.pl-sortable[data-sort="' + sortKey + '"]');
    var type = (th && th.getAttribute('data-sort-type')) || 'text';
    rows.sort(function (a, b) {
      var av = itemSortValue(a, sortKey, type);
      var bv = itemSortValue(b, sortKey, type);
      var cmp = 0;
      if (type === 'number') cmp = av - bv;
      else cmp = String(av).localeCompare(String(bv), undefined, { numeric: true, sensitivity: 'base' });
      return sortAscending ? cmp : -cmp;
    });
    return rows;
  }

  function updateSortHeaderUi() {
    var table = $('#pos-menu-table');
    if (!table) return;
    $all('th.pl-sortable', table).forEach(function (header) {
      header.classList.remove('is-sorted-asc', 'is-sorted-desc');
      header.setAttribute('aria-sort', 'none');
      var key = header.getAttribute('data-sort') || '';
      if (key && key === sortKey) {
        header.classList.add(sortAscending ? 'is-sorted-asc' : 'is-sorted-desc');
        header.setAttribute('aria-sort', sortAscending ? 'ascending' : 'descending');
      }
    });
  }

  function bindTableSort() {
    var table = $('#pos-menu-table');
    if (!table || table.getAttribute('data-pl-sort-bound') === '1') return;
    table.setAttribute('data-pl-sort-bound', '1');
    var headers = $all('th.pl-sortable', table);
    if (!headers.length) return;

    function sortBy(th) {
      var key = th.getAttribute('data-sort') || '';
      if (!key) return;
      if (sortKey === key) sortAscending = !sortAscending;
      else {
        sortKey = key;
        sortAscending = true;
      }
      renderTable();
    }

    headers.forEach(function (th) {
      th.addEventListener('click', function () {
        sortBy(th);
      });
      th.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          sortBy(th);
        }
      });
    });
  }

  function renderKpis(rows) {
    var totalEl = $('#pos-menu-kpi-total');
    var costEl = $('#pos-menu-kpi-food-cost');
    var marginEl = $('#pos-menu-kpi-margin');
    var lowEl = $('#pos-menu-kpi-low');
    var totalMeta = $('#pos-menu-kpi-total-meta');
    var countEl = $('#pos-menu-entry-count');
    var total = rows.length;
    if (totalEl) totalEl.textContent = String(total);
    if (totalMeta) {
      totalMeta.textContent =
        total === 1 ? '1 item in current filters' : total + ' items in current filters';
    }
    if (countEl) {
      countEl.textContent = total === 1 ? '1 item' : total + ' items';
    }

    var costSum = 0;
    var costN = 0;
    var marginSum = 0;
    var marginN = 0;
    var low = 0;
    rows.forEach(function (it) {
      if (it.food_cost_pct != null && isFinite(Number(it.food_cost_pct))) {
        costSum += Number(it.food_cost_pct);
        costN += 1;
      }
      var band = it.margin_band || marginBand(it.margin_pct);
      if (it.margin_pct != null && isFinite(Number(it.margin_pct))) {
        marginSum += Number(it.margin_pct);
        marginN += 1;
        if (band === 'low') low += 1;
      }
    });
    if (costEl) costEl.textContent = costN ? formatPct(costSum / costN) : '—';
    if (marginEl) marginEl.textContent = marginN ? formatPct(marginSum / marginN) : '—';
    if (lowEl) lowEl.textContent = String(low);
  }

  function badgeHtml(it) {
    var band = it.margin_band || marginBand(it.margin_pct);
    if (!band || it.margin_pct == null) {
      return '<span class="pos-menu-badge pos-menu-badge--na">—</span>';
    }
    return (
      '<span class="pos-menu-badge pos-menu-badge--' +
      escapeHtml(band) +
      '">' +
      escapeHtml(formatPct(it.margin_pct)) +
      '</span>'
    );
  }

  function statusHtml(it) {
    var st = itemStatus(it);
    var label = st === 'hidden' ? 'Hidden' : 'Visible';
    return (
      '<span class="pos-menu-status pos-menu-status--' +
      st +
      '"><span class="pos-menu-status-dot" aria-hidden="true"></span>' +
      label +
      '</span>'
    );
  }

  function renderTable() {
    var body = $('#pos-menu-table-body');
    if (!body) return;
    var rows = sortedFilteredItems();
    renderKpis(rows);
    updateSortHeaderUi();

    if (!rows.length) {
      body.innerHTML =
        '<tr class="pos-menu-table-empty-row"><td colspan="8">' +
        (items.length
          ? 'No menu items match your filters.'
          : 'No menu items yet. Add a category, then Add Menu.') +
        '</td></tr>';
      return;
    }

    var editSvg =
      '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>';
    var delSvg =
      '<svg viewBox="0 0 24 24" aria-hidden="true"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/></svg>';

    body.innerHTML = rows
      .map(function (it) {
        var catName = itemCategoryName(it) || '—';
        var meta = [];
        if (it.code) meta.push(it.code);
        if (it.variant) meta.push(it.variant);
        var st = itemStatus(it);
        var statusLabel = st === 'hidden' ? 'Hidden' : 'Visible';
        var itemId = escapeHtml(it.id);
        return (
          '<tr class="pos-menu-data-row" data-sort-row data-item-id="' +
          itemId +
          '" tabindex="0" role="button" aria-label="Open details for ' +
          escapeHtml(it.name || 'menu item') +
          '">' +
          '<td data-sort-value="' +
          escapeHtml(it.name || '') +
          '"><span class="pl-name pos-menu-item-name">' +
          escapeHtml(it.name || '—') +
          '</span>' +
          (meta.length
            ? '<span class="pl-meta pos-menu-item-meta">' + escapeHtml(meta.join(' · ')) + '</span>'
            : '') +
          '</td>' +
          '<td data-sort-value="' +
          escapeHtml(catName === '—' ? '' : catName) +
          '">' +
          escapeHtml(catName) +
          '</td>' +
          '<td class="pos-menu-num pl-col-amount" data-sort-value="' +
          escapeHtml(it.rate != null ? String(it.rate) : '') +
          '">' +
          escapeHtml(formatMoney(it.rate)) +
          '</td>' +
          '<td class="pos-menu-num pl-col-amount" data-sort-value="' +
          escapeHtml(it.food_cost != null ? String(it.food_cost) : '') +
          '">' +
          escapeHtml(formatMoney(it.food_cost)) +
          '</td>' +
          '<td class="pos-menu-num pl-col-amount" data-sort-value="' +
          escapeHtml(it.gross_margin != null ? String(it.gross_margin) : '') +
          '">' +
          escapeHtml(formatMoney(it.gross_margin)) +
          '</td>' +
          '<td class="pos-menu-num pl-col-amount" data-sort-value="' +
          escapeHtml(it.margin_pct != null ? String(it.margin_pct) : '') +
          '">' +
          badgeHtml(it) +
          '</td>' +
          '<td data-sort-value="' +
          escapeHtml(statusLabel) +
          '">' +
          statusHtml(it) +
          '</td>' +
          '<td class="pl-col-actions pos-menu-actions-col">' +
          '<div class="act-grp">' +
          '<button type="button" class="act-btn edit" data-tip="Edit" aria-label="Edit item" ' +
          'data-pos-menu-action="edit-item" data-item-id="' +
          itemId +
          '">' +
          editSvg +
          '</button>' +
          '<div class="act-sep" aria-hidden="true"></div>' +
          '<button type="button" class="act-btn del" data-tip="Delete" aria-label="Delete item" ' +
          'data-pos-menu-action="delete-item" data-item-id="' +
          itemId +
          '">' +
          delSvg +
          '</button>' +
          '</div></td></tr>'
        );
      })
      .join('');
  }

  /** Open Menu Details popup for a table row (not action buttons). */
  function onMenuRowActivate(item) {
    if (!item || !item.id) return;
    openMenuDetails(item.id);
  }

  /** Public hook — same as row activate (soft-nav / external callers). */
  global.onPosMenuRowActivate = onMenuRowActivate;

  function isMenuActionTarget(t) {
    if (!t || !t.closest) return false;
    return !!(
      t.closest('.act-grp') ||
      t.closest('.act-btn') ||
      t.closest('.pos-menu-actions-col') ||
      t.closest('[data-pos-menu-action]')
    );
  }

  function menuRowFromEventTarget(t) {
    if (!t || !t.closest) return null;
    if (isMenuActionTarget(t)) return null;
    if (t.closest('#pos-menu-table thead') || t.closest('th.pl-sortable')) return null;
    var row = t.closest('#pos-menu-table-body tr[data-item-id]');
    if (!row) {
      row = t.closest('tr.pos-menu-data-row[data-item-id]');
      if (row && !row.closest('#pos-menu-table-body')) row = null;
    }
    return row;
  }

  function bindMenuRowClickOnce() {
    if (document.documentElement.getAttribute('data-pos-menu-row-click') === '1') return;
    document.documentElement.setAttribute('data-pos-menu-row-click', '1');
    document.addEventListener('click', function (e) {
      var row = menuRowFromEventTarget(e.target);
      if (!row) return;
      var id = row.getAttribute('data-item-id');
      if (!id) return;
      e.preventDefault();
      onMenuRowActivate(findItem(id) || { id: id });
    });
    document.addEventListener('keydown', function (e) {
      if (e.key !== 'Enter' && e.key !== ' ') return;
      if (!e.target || e.target.tagName !== 'TR') return;
      if (!e.target.getAttribute('data-item-id')) return;
      if (!e.target.closest('#pos-menu-table-body')) return;
      e.preventDefault();
      var id = e.target.getAttribute('data-item-id');
      onMenuRowActivate(findItem(id) || { id: id });
    });
  }

  function menuTypeLabel(type) {
    var t = String(type || '').toLowerCase();
    if (t === 'veg') return 'Veg';
    if (t === 'non_veg') return 'Non-Veg';
    return '—';
  }

  function formatDateTime(value) {
    if (!value) return '—';
    var s = String(value);
    return s.length > 16 ? s.slice(0, 16) : s;
  }

  function formatDateShort(value) {
    if (!value) return '—';
    return String(value).slice(0, 10);
  }

  function marginStatusLabel(status) {
    var map = {
      excellent: 'Excellent',
      good: 'Good',
      average: 'Average',
      low: 'Low',
      critical: 'Critical'
    };
    return map[status] || (status ? String(status) : '—');
  }

  function kpiIcon(kind) {
    if (kind === 'price') {
      return '<span class="pos-md-kpi-rupee" aria-hidden="true">₹</span>';
    }
    if (kind === 'cost') {
      return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 3h18v4H3zM3 10h18v11H3z"/><path d="M8 14h.01M12 14h.01M16 14h.01"/></svg>';
    }
    if (kind === 'margin') {
      return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 17 9 11l4 4 8-8"/><path d="M14 7h7v7"/></svg>';
    }
    return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>';
  }

  function setDetailsTab(tab) {
    detailsTab = tab || 'overview';
    $all('#pos-menu-details-modal [data-pos-md-tab]').forEach(function (btn) {
      var on = btn.getAttribute('data-pos-md-tab') === detailsTab;
      btn.classList.toggle('is-active', on);
      btn.setAttribute('aria-selected', on ? 'true' : 'false');
    });
    $all('#pos-menu-details-modal [data-pos-md-panel]').forEach(function (panel) {
      var on = panel.getAttribute('data-pos-md-panel') === detailsTab;
      panel.classList.toggle('is-active', on);
      if (on) panel.removeAttribute('hidden');
      else panel.setAttribute('hidden', '');
    });
  }

  function closeMenuDetails() {
    var modal = $('#pos-menu-details-modal');
    if (modal) {
      modal.classList.remove('active');
      modal.setAttribute('hidden', '');
    }
    var pop = $('#pos-md-more-pop');
    if (pop) pop.hidden = true;
    detailsItem = null;
    detailsBusy = false;
    setErr($('#pos-md-err'), '');
  }

  function openMenuDetails(itemId) {
    var id = Number(itemId);
    if (!id || detailsBusy) return;
    detailsBusy = true;
    setErr($('#pos-md-err'), '');
    fetch(ITEMS_API + '/' + encodeURIComponent(id), {
      credentials: 'same-origin',
      headers: { Accept: 'application/json' }
    })
      .then(function (r) {
        return r.json().then(function (data) {
          return { ok: r.ok, data: data };
        });
      })
      .then(function (res) {
        detailsBusy = false;
        if (!res.ok || !res.data || !res.data.ok || !res.data.item) {
          showToast((res.data && res.data.error) || 'Could not load menu details.');
          return;
        }
        detailsItem = res.data.item;
        renderMenuDetails(detailsItem);
        setDetailsTab('overview');
        var modal = $('#pos-menu-details-modal');
        if (modal) {
          modal.removeAttribute('hidden');
          modal.classList.add('active');
        }
      })
      .catch(function () {
        detailsBusy = false;
        showToast('Could not load menu details.');
      });
  }

  function renderMenuDetails(item) {
    if (!item) return;
    var title = $('#pos-md-title');
    if (title) title.textContent = item.name || 'Menu item';

    var status = item.status === 'hidden' ? 'hidden' : 'visible';
    var statusEl = $('#pos-md-status');
    if (statusEl) statusEl.setAttribute('data-status', status);
    var statusLabel = $('#pos-md-status-label');
    if (statusLabel) statusLabel.textContent = status === 'hidden' ? 'Hidden' : 'Visible';

    var chips = $('#pos-md-chips');
    if (chips) {
      var portion = item.portion_size || item.variant || '—';
      chips.innerHTML =
        '<span class="pos-md-chip">Category <strong>' +
        escapeHtml(item.category_name || '—') +
        '</strong></span>' +
        '<span class="pos-md-chip">Selling Price <strong>' +
        escapeHtml(formatMoney(item.rate)) +
        '</strong></span>' +
        '<span class="pos-md-chip">Menu Type <strong>' +
        escapeHtml(menuTypeLabel(item.menu_type)) +
        '</strong></span>' +
        '<span class="pos-md-chip">Portion Size <strong>' +
        escapeHtml(portion || '—') +
        '</strong></span>';
    }

    var displayCost =
      item.display_food_cost != null ? item.display_food_cost : item.food_cost;
    var analysis = item.analysis || {};
    var costSource = analysis.cost_source === 'fifo' ? 'FIFO' : 'Approx.';
    var kpis = $('#pos-md-kpis');
    if (kpis) {
      kpis.innerHTML =
        '<div class="pos-md-kpi"><span class="pos-md-kpi-icon">' +
        kpiIcon('price') +
        '</span><span class="pos-md-kpi-body"><span class="pos-md-kpi-label">Selling Price</span><span class="pos-md-kpi-value">' +
        escapeHtml(formatMoney(item.rate)) +
        '</span><span class="pos-md-kpi-sub">Menu rate</span></span></div>' +
        '<div class="pos-md-kpi"><span class="pos-md-kpi-icon">' +
        kpiIcon('cost') +
        '</span><span class="pos-md-kpi-body"><span class="pos-md-kpi-label">Food Cost (FIFO)</span><span class="pos-md-kpi-value">' +
        escapeHtml(formatMoney(displayCost)) +
        '</span><span class="pos-md-kpi-sub">' +
        escapeHtml(costSource) +
        ' recipe cost</span></span></div>' +
        '<div class="pos-md-kpi"><span class="pos-md-kpi-icon">' +
        kpiIcon('margin') +
        '</span><span class="pos-md-kpi-body"><span class="pos-md-kpi-label">Gross Margin</span><span class="pos-md-kpi-value">' +
        escapeHtml(formatMoney(item.gross_margin != null ? item.gross_margin : analysis.gross_profit)) +
        '</span><span class="pos-md-kpi-sub">Price − food cost</span></span></div>' +
        '<div class="pos-md-kpi"><span class="pos-md-kpi-icon">' +
        kpiIcon('pct') +
        '</span><span class="pos-md-kpi-body"><span class="pos-md-kpi-label">Margin %</span><span class="pos-md-kpi-value">' +
        escapeHtml(formatPct(item.margin_pct != null ? item.margin_pct : analysis.margin_pct)) +
        '</span><span class="pos-md-kpi-sub">' +
        escapeHtml(marginStatusLabel(item.margin_status || analysis.margin_status)) +
        '</span></span></div>';
    }

    renderOverviewFields(item);
    renderRecipeTable(item);
    renderFifoTable(item);
    renderMarginAnalysis(item);
    renderPriceHistory(item);

    var notes = $('#pos-md-notes');
    if (notes) notes.value = item.notes || '';

    var updatedAt = $('#pos-md-updated-at');
    if (updatedAt) updatedAt.textContent = formatDateTime(item.updated_at);
    var updatedBy = $('#pos-md-updated-by');
    if (updatedBy) updatedBy.textContent = item.updated_by || '—';

    var inv = $('#pos-md-view-inventory');
    if (inv) inv.href = item.inventory_url || '/stores/stock?outlet=restaurant';
  }

  function renderOverviewFields(item) {
    var grid = $('#pos-md-overview-grid');
    if (!grid) return;
    var portion = item.portion_size || item.variant || '';
    grid.innerHTML =
      '<div class="pos-md-field-card"><label for="pos-md-prep">Prep Time (mins)</label><input type="number" id="pos-md-prep" min="0" step="1" value="' +
      escapeHtml(item.prep_time_mins != null ? String(item.prep_time_mins) : '') +
      '" placeholder="—"></div>' +
      '<div class="pos-md-field-card"><label for="pos-md-shelf">Shelf Life</label><input type="text" id="pos-md-shelf" maxlength="80" value="' +
      escapeHtml(item.shelf_life || '') +
      '" placeholder="e.g. 2 days"></div>' +
      '<div class="pos-md-field-card"><label for="pos-md-portion">Portion Size</label><input type="text" id="pos-md-portion" maxlength="80" value="' +
      escapeHtml(portion) +
      '" placeholder="e.g. Full / 300g"></div>' +
      '<div class="pos-md-field-card"><label for="pos-md-menu-type">Menu Type</label><select id="pos-md-menu-type"><option value="">—</option><option value="veg"' +
      (item.menu_type === 'veg' ? ' selected' : '') +
      '>Veg</option><option value="non_veg"' +
      (item.menu_type === 'non_veg' ? ' selected' : '') +
      '>Non-Veg</option></select></div>' +
      '<div class="pos-md-field-card"><label>Last Updated</label><div class="pos-md-field-value' +
      (item.updated_at ? '' : ' is-muted') +
      '">' +
      escapeHtml(formatDateTime(item.updated_at)) +
      '</div></div>' +
      '<div class="pos-md-field-card"><label>Updated By</label><div class="pos-md-field-value' +
      (item.updated_by ? '' : ' is-muted') +
      '">' +
      escapeHtml(item.updated_by || '—') +
      '</div></div>' +
      '<div class="pos-md-field-card"><label for="pos-md-target">Target Margin %</label><input type="number" id="pos-md-target" min="0" max="99.99" step="0.01" value="' +
      escapeHtml(
        item.target_margin_pct != null ? String(item.target_margin_pct) : String(MARGIN_HEALTHY_PCT)
      ) +
      '"></div>';
  }

  function renderRecipeTable(item) {
    var body = $('#pos-md-recipe-body');
    var totalEl = $('#pos-md-recipe-total');
    if (!body) return;
    var recipe = item.recipe || [];
    var fifoBatches = (item.fifo && item.fifo.batches) || [];
    function fifoUnitForProduct(name) {
      for (var i = 0; i < fifoBatches.length; i++) {
        if (
          (fifoBatches[i].ingredient || fifoBatches[i].product_name) === name &&
          fifoBatches[i].unit_cost != null
        ) {
          return fifoBatches[i].unit_cost;
        }
      }
      return null;
    }
    if (!recipe.length) {
      body.innerHTML =
        '<tr><td colspan="5"><div class="pos-md-empty">No recipe ingredients yet. Use Edit Menu to add products.</div></td></tr>';
      if (totalEl) totalEl.textContent = '—';
      return;
    }
    body.innerHTML = recipe
      .map(function (line) {
        var fifoUnit = fifoUnitForProduct(line.product_name);
        var unitCost = fifoUnit != null ? fifoUnit : line.approximate_price;
        return (
          '<tr><td>' +
          escapeHtml(line.product_name || '—') +
          '</td><td class="pos-md-num">' +
          escapeHtml(line.qty != null ? String(line.qty) : '—') +
          '</td><td>' +
          escapeHtml(line.unit || '—') +
          '</td><td class="pos-md-num">' +
          escapeHtml(formatMoney(unitCost)) +
          '</td><td class="pos-md-num">' +
          escapeHtml(formatMoney(line.line_cost)) +
          '</td></tr>'
        );
      })
      .join('');
    if (totalEl) {
      totalEl.textContent = formatMoney(
        item.recipe_total_cost != null ? item.recipe_total_cost : item.food_cost
      );
    }
  }

  function renderFifoTable(item) {
    var body = $('#pos-md-fifo-body');
    var totalEl = $('#pos-md-fifo-total');
    var banner = $('#pos-md-fifo-banner');
    var fifo = item.fifo || {};
    if (banner) {
      banner.textContent =
        fifo.note ||
        'FIFO allocates recipe quantity against the oldest stock receive batches first.';
      banner.classList.toggle('is-warn', !fifo.fifo_available);
    }
    if (!body) return;
    var batches = fifo.batches || [];
    if (!batches.length) {
      body.innerHTML =
        '<tr><td colspan="7"><div class="pos-md-empty">No FIFO batch rows available. Food cost falls back to Product Master approximate price.</div></td></tr>';
    } else {
      body.innerHTML = batches
        .map(function (b) {
          return (
            '<tr><td>' +
            escapeHtml(b.batch_no || '—') +
            '</td><td>' +
            escapeHtml(formatDateShort(b.purchase_date)) +
            '</td><td>' +
            escapeHtml(b.supplier || '—') +
            '</td><td class="pos-md-num">' +
            escapeHtml(
              b.available_qty != null
                ? String(b.available_qty) + (b.unit ? ' ' + b.unit : '')
                : '—'
            ) +
            '</td><td class="pos-md-num">' +
            escapeHtml(formatMoney(b.unit_cost)) +
            '</td><td class="pos-md-num">' +
            escapeHtml(b.qty_used != null ? String(b.qty_used) : '—') +
            '</td><td class="pos-md-num">' +
            escapeHtml(formatMoney(b.cost_used)) +
            '</td></tr>'
          );
        })
        .join('');
    }
    if (totalEl) {
      var fifoCost =
        fifo.fifo_food_cost != null
          ? fifo.fifo_food_cost
          : item.display_food_cost != null
            ? item.display_food_cost
            : item.food_cost;
      totalEl.textContent = formatMoney(fifoCost);
    }
  }

  function renderMarginAnalysis(item) {
    var grid = $('#pos-md-analysis-grid');
    if (!grid) return;
    var a = item.analysis || {};
    var status = a.margin_status || item.margin_status || '';
    function card(label, value, extra) {
      return (
        '<div class="pos-md-analysis-card"><span class="pos-md-kpi-label">' +
        escapeHtml(label) +
        '</span><span class="pos-md-kpi-value">' +
        escapeHtml(value) +
        '</span>' +
        (extra || '') +
        '</div>'
      );
    }
    var statusHtml = status
      ? '<span class="pos-md-status-pill" data-status="' +
        escapeHtml(status) +
        '">' +
        escapeHtml(marginStatusLabel(status)) +
        '</span>'
      : '';
    grid.innerHTML =
      card('Selling Price', formatMoney(a.selling_price != null ? a.selling_price : item.rate)) +
      card('FIFO Food Cost', formatMoney(a.fifo_food_cost != null ? a.fifo_food_cost : item.display_food_cost)) +
      card('Gross Profit', formatMoney(a.gross_profit != null ? a.gross_profit : item.gross_margin), statusHtml) +
      card('Margin %', formatPct(a.margin_pct != null ? a.margin_pct : item.margin_pct), statusHtml) +
      card('Food Cost %', formatPct(a.food_cost_pct != null ? a.food_cost_pct : item.food_cost_pct)) +
      card(
        'Target Margin',
        formatPct(a.target_margin_pct != null ? a.target_margin_pct : item.target_margin_pct)
      ) +
      card('Recommended Selling Price', formatMoney(a.recommended_selling_price)) +
      card(
        'Profit per Portion',
        formatMoney(a.profit_per_portion != null ? a.profit_per_portion : item.gross_margin)
      );
  }

  function renderPriceHistory(item) {
    var body = $('#pos-md-history-body');
    if (!body) return;
    var rows = item.price_history || [];
    if (!rows.length) {
      body.innerHTML =
        '<tr><td colspan="5"><div class="pos-md-empty">No price changes recorded yet. History is saved when the selling price changes.</div></td></tr>';
      return;
    }
    body.innerHTML = rows
      .map(function (h) {
        return (
          '<tr><td>' +
          escapeHtml(formatDateTime(h.created_at)) +
          '</td><td class="pos-md-num">' +
          escapeHtml(formatMoney(h.old_price)) +
          '</td><td class="pos-md-num">' +
          escapeHtml(formatMoney(h.new_price)) +
          '</td><td>' +
          escapeHtml(h.reason || '—') +
          '</td><td>' +
          escapeHtml(h.updated_by || '—') +
          '</td></tr>'
        );
      })
      .join('');
  }

  function collectDetailsPayload() {
    if (!detailsItem || !detailsItem.id) return null;
    var prepVal = ($('#pos-md-prep') && $('#pos-md-prep').value) || '';
    var targetVal = ($('#pos-md-target') && $('#pos-md-target').value) || '';
    return {
      id: Number(detailsItem.id),
      category_id: detailsItem.category_id,
      product_id: detailsItem.product_id,
      name: detailsItem.name,
      code: detailsItem.code || '',
      barcode: detailsItem.barcode || '',
      variant: detailsItem.variant || '',
      rate: detailsItem.rate,
      recipe: (detailsItem.recipe || []).map(function (line) {
        return {
          product_id: line.product_id,
          qty: line.qty,
          unit: line.unit
        };
      }),
      menu_type: ($('#pos-md-menu-type') && $('#pos-md-menu-type').value) || '',
      portion_size: ($('#pos-md-portion') && $('#pos-md-portion').value) || '',
      prep_time_mins: prepVal === '' ? '' : Number(prepVal),
      shelf_life: ($('#pos-md-shelf') && $('#pos-md-shelf').value) || '',
      notes: ($('#pos-md-notes') && $('#pos-md-notes').value) || '',
      target_margin_pct: targetVal === '' ? null : Number(targetVal)
    };
  }

  function saveMenuDetails() {
    if (detailsBusy || busy) return;
    var payload = collectDetailsPayload();
    var err = $('#pos-md-err');
    if (!payload) {
      setErr(err, 'Nothing to save.');
      return;
    }
    detailsBusy = true;
    setErr(err, '');
    fetch(ITEMS_API, {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json',
        'X-Requested-With': 'XMLHttpRequest'
      },
      body: JSON.stringify(payload)
    })
      .then(function (r) {
        return r.json().then(function (data) {
          return { ok: r.ok, data: data };
        });
      })
      .then(function (res) {
        detailsBusy = false;
        if (!res.ok || !res.data || !res.data.ok) {
          var msg = (res.data && res.data.error) || 'Could not save changes.';
          setErr(err, msg);
          showToast(msg);
          return;
        }
        if (res.data.categories) applyCategories(res.data.categories, Number(payload.category_id));
        showToast('Menu details saved');
        fetchAllItemsThen(function () {
          openMenuDetails(payload.id);
        });
      })
      .catch(function () {
        detailsBusy = false;
        setErr(err, 'Could not save changes.');
        showToast('Could not save changes.');
      });
  }

  function exportCsv() {
    var rows = sortedFilteredItems();
    var header = [
      'Menu Item',
      'Category',
      'Selling Price',
      'Food Cost',
      'Gross Margin',
      'Margin %',
      'Status'
    ];
    function cell(v) {
      var s = v == null ? '' : String(v);
      if (/[",\n]/.test(s)) return '"' + s.replace(/"/g, '""') + '"';
      return s;
    }
    var lines = [header.join(',')];
    rows.forEach(function (it) {
      var catName = itemCategoryName(it);
      lines.push(
        [
          cell(it.name),
          cell(catName),
          cell(it.rate != null ? Number(it.rate).toFixed(2) : ''),
          cell(it.food_cost != null ? Number(it.food_cost).toFixed(2) : ''),
          cell(it.gross_margin != null ? Number(it.gross_margin).toFixed(2) : ''),
          cell(it.margin_pct != null ? Number(it.margin_pct).toFixed(2) : ''),
          cell(itemStatus(it) === 'hidden' ? 'Hidden' : 'Visible')
        ].join(',')
      );
    });
    var blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8' });
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = 'menu-margin-export.csv';
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(function () {
      URL.revokeObjectURL(url);
    }, 500);
    showToast('Exported ' + rows.length + ' row' + (rows.length === 1 ? '' : 's'));
  }

  function applyCategories(next, preferId) {
    categories = Array.isArray(next) ? next : [];
    if (preferId != null && findCategory(preferId)) {
      selectedCategoryId = Number(preferId);
    } else if (selectedCategoryId != null && !findCategory(selectedCategoryId)) {
      selectedCategoryId = categories.length ? Number(categories[0].id) : null;
    } else if (selectedCategoryId == null && categories.length) {
      selectedCategoryId = Number(categories[0].id);
    }
    fillCategorySelects();
  }

  function fetchCategoriesThen(cb) {
    fetch(CATEGORIES_API, { credentials: 'same-origin', headers: { Accept: 'application/json' } })
      .then(function (r) {
        return r.json().then(function (data) {
          return { ok: r.ok, data: data };
        });
      })
      .then(function (res) {
        if (!res.ok || !res.data || !res.data.ok) {
          throw new Error((res.data && res.data.error) || 'Could not load categories.');
        }
        applyCategories(res.data.categories);
        if (typeof cb === 'function') cb();
      })
      .catch(function (err) {
        showToast(err.message || 'Could not load categories.');
        if (typeof cb === 'function') cb(err);
      });
  }

  function fetchAllItemsThen(cb) {
    fetch(ITEMS_API, {
      credentials: 'same-origin',
      headers: { Accept: 'application/json' }
    })
      .then(function (r) {
        return r.json().then(function (data) {
          return { ok: r.ok, data: data };
        });
      })
      .then(function (res) {
        if (!res.ok || !res.data || !res.data.ok) {
          throw new Error((res.data && res.data.error) || 'Could not load items.');
        }
        items = Array.isArray(res.data.items) ? res.data.items : [];
        renderTable();
        if (typeof cb === 'function') cb();
      })
      .catch(function (err) {
        items = [];
        renderTable();
        showToast(err.message || 'Could not load items.');
        if (typeof cb === 'function') cb(err);
      });
  }

  function fetchProductsThen(cb) {
    if (productsLoaded && products.length) {
      if (typeof cb === 'function') cb();
      return;
    }
    fetch(PRODUCTS_API, { credentials: 'same-origin', headers: { Accept: 'application/json' } })
      .then(function (r) {
        return r.json().then(function (data) {
          return { ok: r.ok, data: data };
        });
      })
      .then(function (res) {
        if (!res.ok || !res.data || !res.data.ok) {
          throw new Error((res.data && res.data.error) || 'Could not load products.');
        }
        products = Array.isArray(res.data.products) ? res.data.products : [];
        productsById = {};
        products.forEach(function (p) {
          productsById[String(p.id)] = p;
        });
        productsLoaded = true;
        if (typeof cb === 'function') cb();
      })
      .catch(function (err) {
        showToast(err.message || 'Could not load Product Master.');
        if (typeof cb === 'function') cb(err);
      });
  }

  function openModal(id) {
    var modal = document.getElementById(id);
    if (modal) modal.classList.add('active');
  }

  function closeModal(id) {
    var modal = document.getElementById(id);
    if (modal) modal.classList.remove('active');
  }

  function cancelItemAutosaveTimer() {
    if (itemAutosaveTimer) {
      clearTimeout(itemAutosaveTimer);
      itemAutosaveTimer = null;
    }
  }

  function resetItemAutosaveState() {
    cancelItemAutosaveTimer();
    itemDirty = false;
    itemDirtyEpoch = 0;
  }

  function markItemDirty() {
    var modal = $('#pos-menu-item-modal');
    if (!modal || !modal.classList.contains('active')) return;
    itemDirtyEpoch += 1;
    itemDirty = true;
    scheduleItemAutosave();
  }

  function clearItemDirtyAfterPersist(epochAtStart) {
    if (itemDirtyEpoch !== epochAtStart) {
      itemDirty = true;
      scheduleItemAutosave();
      return;
    }
    itemDirty = false;
  }

  function readItemFormFields() {
    syncCategoryHiddenFromSelect();
    return {
      idVal: ($('#pos-menu-item-id').value || '').trim(),
      categoryId: ($('#pos-menu-item-category-id').value || '').trim(),
      name: ($('#pos-menu-item-name').value || '').trim(),
      code: ($('#pos-menu-item-code').value || '').trim(),
      variant: ($('#pos-menu-item-variant').value || '').trim(),
      menuType: ($('#pos-menu-item-menu-type') && $('#pos-menu-item-menu-type').value) || '',
      rate: ($('#pos-menu-item-rate').value || '').trim()
    };
  }

  function itemRequiredFieldsValid(fields) {
    fields = fields || readItemFormFields();
    if (!fields.categoryId || !isFinite(Number(fields.categoryId))) return false;
    if (!fields.name) return false;
    if (fields.rate === '' || Number(fields.rate) < 0 || !isFinite(Number(fields.rate))) return false;
    return true;
  }

  function recipeReadyForAutosave() {
    var result = collectRecipePayload({ skipIncomplete: false });
    return !result.error;
  }

  function scheduleItemAutosave() {
    cancelItemAutosaveTimer();
    if (!itemDirty) return;
    itemAutosaveTimer = setTimeout(function () {
      itemAutosaveTimer = null;
      if (!itemDirty) return;
      if (!itemRequiredFieldsValid()) return;
      if (!recipeReadyForAutosave()) return;
      persistMenuItem({ silent: true });
    }, ITEM_AUTOSAVE_DELAY_MS);
  }

  function flushItemAutosave(opts) {
    cancelItemAutosaveTimer();
    if (!itemDirty) return Promise.resolve({ ok: true, skipped: true });
    if (!itemRequiredFieldsValid()) {
      /* Incomplete Add draft — nothing persisted yet; abandon quietly. */
      itemDirty = false;
      return Promise.resolve({ ok: true, skipped: true });
    }
    return persistMenuItem(
      Object.assign({ silent: true, skipIncompleteRecipe: true }, opts || {})
    );
  }

  function closeItemModal() {
    return flushItemAutosave().finally(function () {
      resetItemAutosaveState();
      closeModal('pos-menu-item-modal');
    });
  }

  function openCategoryModal(cat) {
    var isEdit = !!(cat && cat.id);
    $('#pos-menu-cat-title').textContent = isEdit ? 'Edit category' : 'Add category';
    $('#pos-menu-cat-id').value = isEdit ? String(cat.id) : '';
    $('#pos-menu-cat-name').value = isEdit ? cat.name || '' : '';
    $('#pos-menu-cat-visible').checked = isEdit ? !!cat.is_visible : true;
    var del = $('#pos-menu-cat-delete');
    if (del) del.hidden = !isEdit;
    setErr($('#pos-menu-cat-err'), '');
    openModal('pos-menu-cat-modal');
    setTimeout(function () {
      var name = $('#pos-menu-cat-name');
      if (name) name.focus();
    }, 30);
  }

  function syncCategoryHiddenFromSelect() {
    var sel = $('#pos-menu-item-category');
    var hidden = $('#pos-menu-item-category-id');
    if (sel && hidden) hidden.value = sel.value || '';
  }

  function openItemModal(item) {
    var isEdit = !!(item && item.id);
    resetItemAutosaveState();
    var catId =
      isEdit && item.category_id != null
        ? Number(item.category_id)
        : filterCategory
          ? Number(filterCategory)
          : selectedCategoryId;
    if (!categories.length) {
      showToast('Add a category first.');
      openCategoryModal(null);
      return;
    }
    if (!catId || !findCategory(catId)) {
      catId = Number(categories[0].id);
    }
    var cat = findCategory(catId);
    fillCategorySelects();
    $('#pos-menu-item-title').textContent = isEdit ? 'Edit menu item' : 'Add menu item';
    $('#pos-menu-item-copy').textContent =
      'Set the menu name and rate, then add ingredients with the quantity required.';
    $('#pos-menu-item-id').value = isEdit ? String(item.id) : '';
    var catSel = $('#pos-menu-item-category');
    if (catSel) catSel.value = String(catId);
    $('#pos-menu-item-category-id').value = String(catId);
    $('#pos-menu-item-name').value = isEdit ? item.name || '' : '';
    $('#pos-menu-item-code').value = isEdit ? item.code || '' : '';
    $('#pos-menu-item-rate').value = isEdit ? String(item.rate != null ? item.rate : '') : '';
    $('#pos-menu-item-variant').value = isEdit ? item.variant || '' : '';
    var menuTypeSel = $('#pos-menu-item-menu-type');
    if (menuTypeSel) {
      var mt = isEdit ? String(item.menu_type || '').toLowerCase() : '';
      if (mt === 'non-veg' || mt === 'nonveg' || mt === 'non veg') mt = 'non_veg';
      menuTypeSel.value = mt === 'veg' || mt === 'non_veg' ? mt : '';
    }
    recipeDraft = [];
    if (isEdit && Array.isArray(item.recipe)) {
      recipeDraft = item.recipe.map(function (line) {
        return {
          product_id: Number(line.product_id),
          product_name: line.product_name || '',
          product_unit: line.product_unit || '',
          qty: line.qty != null ? line.qty : '',
          unit: coerceRecipeUnit(line.product_unit, line.unit)
        };
      });
    }
    renderRecipeRows();
    var del = $('#pos-menu-item-delete');
    if (del) del.hidden = !isEdit;
    setErr($('#pos-menu-item-err'), '');
    fetchProductsThen(function () {
      rebuildProductListbox();
      openModal('pos-menu-item-modal');
      if (typeof global.initEpListboxes === 'function') global.initEpListboxes();
      setTimeout(function () {
        var name = $('#pos-menu-item-name');
        if (name) name.focus();
      }, 30);
    });
    if (cat) selectedCategoryId = Number(cat.id);
  }

  global.onPosMenuProductPicked = function (root, value) {
    if (!value) return;
    addRecipeLine(value);
  };

  global.onPosMenuRecipeUnitChanged = function () {
    markItemDirty();
  };

  function saveCategory(e) {
    if (e) e.preventDefault();
    if (busy) return;
    var idVal = ($('#pos-menu-cat-id').value || '').trim();
    var name = ($('#pos-menu-cat-name').value || '').trim();
    var visible = !!($('#pos-menu-cat-visible') && $('#pos-menu-cat-visible').checked);
    var err = $('#pos-menu-cat-err');
    if (!name) {
      setErr(err, 'Category name is required.');
      return;
    }
    busy = true;
    var payload = { name: name, is_visible: visible };
    if (idVal) payload.id = Number(idVal);
    fetch(CATEGORIES_API, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify(payload)
    })
      .then(function (r) {
        return r.json().then(function (data) {
          return { ok: r.ok, data: data };
        });
      })
      .then(function (res) {
        busy = false;
        if (!res.ok || !res.data || !res.data.ok) {
          setErr(err, (res.data && res.data.error) || 'Could not save category.');
          return;
        }
        var savedId = res.data.category && res.data.category.id;
        applyCategories(res.data.categories, savedId);
        closeModal('pos-menu-cat-modal');
        showToast(idVal ? 'Category updated' : 'Category added');
        fetchAllItemsThen();
      })
      .catch(function () {
        busy = false;
        setErr(err, 'Could not save category.');
      });
  }

  function deleteCategory() {
    var idVal = ($('#pos-menu-cat-id').value || '').trim();
    if (!idVal || busy) return;
    if (!window.confirm('Delete this category and its menu items?')) return;
    busy = true;
    fetch(CATEGORIES_API + '/' + encodeURIComponent(idVal) + '/delete', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { Accept: 'application/json' }
    })
      .then(function (r) {
        return r.json().then(function (data) {
          return { ok: r.ok, data: data };
        });
      })
      .then(function (res) {
        busy = false;
        if (!res.ok || !res.data || !res.data.ok) {
          setErr($('#pos-menu-cat-err'), (res.data && res.data.error) || 'Could not delete.');
          return;
        }
        selectedCategoryId = null;
        applyCategories(res.data.categories);
        closeModal('pos-menu-cat-modal');
        showToast('Category deleted');
        fetchAllItemsThen();
      })
      .catch(function () {
        busy = false;
        setErr($('#pos-menu-cat-err'), 'Could not delete category.');
      });
  }

  function persistMenuItem(opts) {
    opts = opts || {};
    var silent = !!opts.silent;
    var skipIncompleteRecipe = !!opts.skipIncompleteRecipe;
    var toastOnSuccess = opts.toastOnSuccess != null ? !!opts.toastOnSuccess : !silent;
    var keepalive = !!opts.keepalive;
    var err = $('#pos-menu-item-err');
    var fields = readItemFormFields();

    if (!itemRequiredFieldsValid(fields)) {
      if (!silent) {
        if (!fields.categoryId || !isFinite(Number(fields.categoryId))) {
          setErr(err, 'Select a category first.');
          showToast('Select a category first.');
        } else if (!fields.name) {
          setErr(err, 'Menu name is required.');
          showToast('Menu name is required.');
        } else {
          setErr(err, 'Enter a valid rate.');
          showToast('Enter a valid rate.');
        }
      }
      return Promise.resolve({ ok: false, skipped: true });
    }

    var recipeResult = collectRecipePayload({ skipIncomplete: skipIncompleteRecipe });
    if (recipeResult.error) {
      if (!silent) {
        setErr(err, recipeResult.error);
        showToast(recipeResult.error);
      }
      return Promise.resolve({ ok: false, skipped: true });
    }

    if (itemSaveInflight) {
      return itemSaveInflight.then(function () {
        if (itemDirty || opts.force) return persistMenuItem(opts);
        return { ok: true, skipped: true };
      });
    }

    var wasCreate = !fields.idVal;
    var epochAtStart = itemDirtyEpoch;
    var payload = {
      category_id: Number(fields.categoryId),
      product_id: null,
      name: fields.name,
      code: fields.code,
      variant: fields.variant,
      menu_type: fields.menuType || '',
      rate: Number(fields.rate),
      recipe: recipeResult.recipe
    };
    if (fields.idVal) payload.id = Number(fields.idVal);

    if (!silent) busy = true;
    setErr(err, '');

    var fetchOpts = {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json',
        'X-Requested-With': 'XMLHttpRequest'
      },
      body: JSON.stringify(payload)
    };
    if (keepalive) fetchOpts.keepalive = true;

    itemSaveInflight = fetch(ITEMS_API, fetchOpts)
      .then(function (r) {
        return r
          .json()
          .then(function (data) {
            return { ok: r.ok, data: data };
          })
          .catch(function () {
            return { ok: false, data: { error: 'Could not save item (invalid server response).' } };
          });
      })
      .then(function (res) {
        if (!silent) busy = false;
        if (!res.ok || !res.data || !res.data.ok) {
          var msg = (res.data && res.data.error) || 'Could not save item.';
          setErr(err, msg);
          showToast(msg);
          return { ok: false, error: msg };
        }
        var saved = res.data.item;
        if (saved && saved.id) {
          var idEl = $('#pos-menu-item-id');
          if (idEl) idEl.value = String(saved.id);
          var del = $('#pos-menu-item-delete');
          if (del) del.hidden = false;
          var title = $('#pos-menu-item-title');
          if (title) title.textContent = 'Edit menu item';
        }
        if (res.data.categories) applyCategories(res.data.categories, Number(fields.categoryId));
        selectedCategoryId = Number(fields.categoryId);
        clearItemDirtyAfterPersist(epochAtStart);
        if (toastOnSuccess) {
          showToast(wasCreate ? 'Item added' : 'Item updated');
        } else if (silent && wasCreate) {
          showToast('Item saved');
        }
        fetchAllItemsThen();
        return { ok: true, item: saved, created: wasCreate };
      })
      .catch(function () {
        if (!silent) busy = false;
        setErr(err, 'Could not save item.');
        showToast('Could not save item.');
        return { ok: false, error: 'network' };
      })
      .then(
        function (outcome) {
          itemSaveInflight = null;
          return outcome;
        },
        function (errOut) {
          itemSaveInflight = null;
          throw errOut;
        }
      );

    return itemSaveInflight;
  }

  function deleteItem(itemId) {
    var id = itemId || ($('#pos-menu-item-id').value || '').trim();
    if (!id || busy) return;
    if (!window.confirm('Delete this menu item?')) return;
    resetItemAutosaveState();
    var runDelete = function () {
      busy = true;
      fetch(ITEMS_API + '/' + encodeURIComponent(id) + '/delete', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { Accept: 'application/json' }
      })
        .then(function (r) {
          return r.json().then(function (data) {
            return { ok: r.ok, data: data };
          });
        })
        .then(function (res) {
          busy = false;
          if (!res.ok || !res.data || !res.data.ok) {
            setErr($('#pos-menu-item-err'), (res.data && res.data.error) || 'Could not delete.');
            showToast((res.data && res.data.error) || 'Could not delete item.');
            return;
          }
          if (res.data.categories) applyCategories(res.data.categories, selectedCategoryId);
          closeModal('pos-menu-item-modal');
          showToast('Item deleted');
          fetchAllItemsThen();
        })
        .catch(function () {
          busy = false;
          showToast('Could not delete item.');
        });
    };
    if (itemSaveInflight) {
      itemSaveInflight.finally(runDelete);
    } else {
      runDelete();
    }
  }

  function filterPageRoot() {
    return (
      document.getElementById('pos-menu-page') ||
      document.getElementById('pos-set-panel-menu') ||
      document
    );
  }

  function syncFilterChipState(page) {
    page = page || filterPageRoot();
    var search = $('#pos-menu-search', page);
    var searchChip = search && search.closest('.pos-menu-search-chip');
    if (searchChip) {
      searchChip.classList.toggle('is-active', !!(search.value || '').trim());
    }
    var catFilter = $('#pos-menu-filter-category', page);
    var catChip = catFilter && catFilter.closest('.pos-menu-filter-listbox');
    if (catChip) catChip.classList.toggle('is-filtered', !!(catFilter.value || '').trim());
    var statusFilter = $('#pos-menu-filter-status', page);
    var statusChip = statusFilter && statusFilter.closest('.pos-menu-filter-listbox');
    if (statusChip) {
      statusChip.classList.toggle('is-filtered', !!(statusFilter.value || '').trim());
    }
  }

  function onCategoryFilterChanged(root, value) {
    filterCategory = value || '';
    if (!filterCategory) clearFilterListboxPlaceholder(root || $('#pos-menu-filter-category-listbox'));
    syncFilterChipState();
    renderTable();
  }

  function onStatusFilterChanged(root, value) {
    filterStatus = value || '';
    if (!filterStatus) clearFilterListboxPlaceholder(root || $('#pos-menu-filter-status-listbox'));
    syncFilterChipState();
    renderTable();
  }

  global.posMenuCategoryFilterChanged = onCategoryFilterChanged;
  global.posMenuStatusFilterChanged = onStatusFilterChanged;

  function bindFilters(page) {
    var search = $('#pos-menu-search', page);
    if (search && search.getAttribute('data-filter-bound') !== '1') {
      search.setAttribute('data-filter-bound', '1');
      search.addEventListener('input', function () {
        filterSearch = search.value || '';
        syncFilterChipState(page);
        renderTable();
      });
    }
    /* Category / Status use ep_form_listbox (data-se-listbox-change). */
    if (typeof global.initEpListboxes === 'function') global.initEpListboxes();
    clearFilterListboxPlaceholder($('#pos-menu-filter-category-listbox', page));
    clearFilterListboxPlaceholder($('#pos-menu-filter-status-listbox', page));
    syncFilterChipState(page);
    var catSel = $('#pos-menu-item-category');
    if (catSel && catSel.getAttribute('data-cat-sync') !== '1') {
      catSel.setAttribute('data-cat-sync', '1');
      catSel.addEventListener('change', syncCategoryHiddenFromSelect);
    }
  }

  function bindPage(page) {
    if (!page) return;
    /* Table may be re-injected on soft-nav; bindTableSort self-guards via data-pl-sort-bound. */
    bindTableSort();
    bindMenuRowClickOnce();
    if (page.getAttribute('data-pos-menu-bound') === '1') {
      /* Soft-nav revisit: still rebind details modal if DOM was swapped. */
      var detailsModalEarly = $('#pos-menu-details-modal');
      if (detailsModalEarly && detailsModalEarly.getAttribute('data-md-bound') !== '1') {
        detailsModalEarly.setAttribute('data-md-bound', '1');
        detailsModalEarly.addEventListener('click', function (ev) {
          var tabBtn = ev.target && ev.target.closest
            ? ev.target.closest('[data-pos-md-tab]')
            : null;
          if (tabBtn) {
            ev.preventDefault();
            setDetailsTab(tabBtn.getAttribute('data-pos-md-tab'));
          }
        });
      }
      return;
    }
    page.setAttribute('data-pos-menu-bound', '1');
    bindFilters(page);

    page.addEventListener('click', function (e) {
      var t = e.target;
      if (!t) return;

      var dismiss = t.closest('[data-pos-menu-dismiss]');
      if (dismiss) {
        var which = dismiss.getAttribute('data-pos-menu-dismiss');
        if (which === 'cat') closeModal('pos-menu-cat-modal');
        if (which === 'item') closeItemModal();
        return;
      }

      var actionBtn = t.closest('[data-pos-menu-action]');
      if (actionBtn) {
        var action = actionBtn.getAttribute('data-pos-menu-action');
        if (action === 'export') {
          exportCsv();
          return;
        }
        if (action === 'add-category') {
          openCategoryModal(null);
          return;
        }
        if (action === 'add-item') {
          openItemModal(null);
          return;
        }
        if (action === 'edit-category') {
          e.preventDefault();
          e.stopPropagation();
          openCategoryModal(findCategory(actionBtn.getAttribute('data-category-id')));
          return;
        }
        if (action === 'edit-item') {
          e.preventDefault();
          e.stopPropagation();
          openItemModal(findItem(actionBtn.getAttribute('data-item-id')));
          return;
        }
        if (action === 'remove-recipe') {
          e.preventDefault();
          e.stopPropagation();
          var row = actionBtn.closest('.pos-menu-recipe-row');
          if (!row) return;
          syncRecipeDraftFromDom();
          var pid = Number(row.getAttribute('data-product-id'));
          recipeDraft = recipeDraft.filter(function (line) {
            return Number(line.product_id) !== pid;
          });
          renderRecipeRows();
          markItemDirty();
          return;
        }
        if (action === 'delete-item') {
          e.preventDefault();
          e.stopPropagation();
          deleteItem(actionBtn.getAttribute('data-item-id'));
          return;
        }
        if (action === 'details-close') {
          e.preventDefault();
          e.stopPropagation();
          closeMenuDetails();
          return;
        }
        if (action === 'details-save') {
          e.preventDefault();
          e.stopPropagation();
          saveMenuDetails();
          return;
        }
        if (action === 'details-edit') {
          e.preventDefault();
          e.stopPropagation();
          var editTarget = detailsItem || findItem(actionBtn.getAttribute('data-item-id'));
          closeMenuDetails();
          if (editTarget) openItemModal(editTarget);
          return;
        }
        if (action === 'details-delete') {
          e.preventDefault();
          e.stopPropagation();
          var delId = detailsItem && detailsItem.id;
          var pop = $('#pos-md-more-pop');
          if (pop) pop.hidden = true;
          if (delId) {
            closeMenuDetails();
            deleteItem(delId);
          }
          return;
        }
        if (action === 'details-more') {
          e.preventDefault();
          e.stopPropagation();
          var morePop = $('#pos-md-more-pop');
          if (morePop) morePop.hidden = !morePop.hidden;
          return;
        }
      }

      /* Action cluster handled above; do not also treat as row activate here. */
    });

    bindMenuRowClickOnce();

    var detailsModal = $('#pos-menu-details-modal');
    if (detailsModal && detailsModal.getAttribute('data-md-bound') !== '1') {
      detailsModal.setAttribute('data-md-bound', '1');
      detailsModal.addEventListener('click', function (ev) {
        var tabBtn = ev.target && ev.target.closest
          ? ev.target.closest('[data-pos-md-tab]')
          : null;
        if (tabBtn) {
          ev.preventDefault();
          setDetailsTab(tabBtn.getAttribute('data-pos-md-tab'));
        }
      });
    }

    var catForm = $('#pos-menu-cat-form');
    if (catForm) catForm.addEventListener('submit', saveCategory);
    var itemForm = $('#pos-menu-item-form');
    if (itemForm && itemForm.getAttribute('data-autosave-bound') !== '1') {
      itemForm.setAttribute('data-autosave-bound', '1');
      itemForm.addEventListener('submit', function (e) {
        e.preventDefault();
        e.stopPropagation();
        flushItemAutosave();
      });
      itemForm.addEventListener('input', function (ev) {
        var t = ev.target;
        if (!t) return;
        if (
          t.id === 'pos-menu-item-name' ||
          t.id === 'pos-menu-item-code' ||
          t.id === 'pos-menu-item-rate' ||
          t.id === 'pos-menu-item-variant' ||
          t.hasAttribute('data-recipe-qty')
        ) {
          markItemDirty();
        }
      });
      itemForm.addEventListener('change', function (ev) {
        var t = ev.target;
        if (!t) return;
        if (
          t.id === 'pos-menu-item-category' ||
          t.id === 'pos-menu-item-menu-type' ||
          t.hasAttribute('data-recipe-unit')
        ) {
          if (t.id === 'pos-menu-item-category') syncCategoryHiddenFromSelect();
          markItemDirty();
        }
      });
    }
    var catDel = $('#pos-menu-cat-delete');
    if (catDel) catDel.addEventListener('click', deleteCategory);
    var itemDel = $('#pos-menu-item-delete');
    if (itemDel) {
      itemDel.addEventListener('click', function () {
        deleteItem();
      });
    }

    ['pos-menu-item-name', 'pos-menu-item-rate'].forEach(function (id) {
      var el = document.getElementById(id);
      if (el && el.getAttribute('data-touch-bound') !== '1') {
        el.setAttribute('data-touch-bound', '1');
        el.addEventListener('input', function () {
          el.dataset.touched = '1';
        });
      }
    });

    ['pos-menu-cat-modal', 'pos-menu-item-modal', 'pos-menu-details-modal'].forEach(function (id) {
      var modal = document.getElementById(id);
      if (!modal || modal.getAttribute('data-overlay-bound') === '1') return;
      modal.setAttribute('data-overlay-bound', '1');
      modal.addEventListener('click', function (ev) {
        if (ev.target !== modal) return;
        if (id === 'pos-menu-details-modal') closeMenuDetails();
        else if (id === 'pos-menu-item-modal') closeItemModal();
        else closeModal(id);
      });
    });

    if (document.documentElement.getAttribute('data-pos-md-esc') !== '1') {
      document.documentElement.setAttribute('data-pos-md-esc', '1');
      document.addEventListener('keydown', function (ev) {
        if (ev.key !== 'Escape') return;
        var md = $('#pos-menu-details-modal');
        if (md && md.classList.contains('active')) {
          closeMenuDetails();
          return;
        }
        var itemModal = $('#pos-menu-item-modal');
        if (itemModal && itemModal.classList.contains('active')) {
          closeItemModal();
          return;
        }
        var catModal = $('#pos-menu-cat-modal');
        if (catModal && catModal.classList.contains('active')) closeModal('pos-menu-cat-modal');
      });
    }
  }

  function getMenuPageRoot() {
    return document.getElementById('pos-menu-page') || document.getElementById('pos-settings-page');
  }

  function initPosMenuSettings() {
    var page = getMenuPageRoot();
    if (!page) return;
    bindPage(page);
    productsLoaded = false;
    fetchCategoriesThen(function () {
      fetchAllItemsThen();
    });
  }

  /** Soft-nav entry for the dedicated /point-of-sale/menu page (not Settings). */
  function initPosMenuPage() {
    if (!document.getElementById('pos-menu-page')) return;
    initPosMenuSettings();
    if (typeof global.initEpListboxes === 'function') {
      try {
        global.initEpListboxes();
      } catch (err) {}
    }
  }

  global.initPosMenuSettings = initPosMenuSettings;
  global.initPosMenuPage = initPosMenuPage;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initPosMenuSettings);
  } else if (!global.__deSoftNavInProgress) {
    /* Soft-nav: settings/menu page init calls once — avoid double category/item fetch. */
    initPosMenuSettings();
  }
})(window);
