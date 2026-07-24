/**
 * Restaurant Settings — Menu categories & items (Product Master linked).
 * Soft-nav safe: window.initPosMenuSettings.
 */
(function (global) {
  'use strict';

  var CATEGORIES_API = '/point-of-sale/api/menu/categories';
  var ITEMS_API = '/point-of-sale/api/menu/items';
  var PRODUCTS_API = '/point-of-sale/api/menu/products';

  var categories = [];
  var items = [];
  var products = [];
  var productsById = {};
  var selectedCategoryId = null;
  var productsLoaded = false;
  var busy = false;

  function $(sel, root) {
    return (root || document).querySelector(sel);
  }

  function escapeHtml(str) {
    return String(str == null ? '' : str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function formatRate(n) {
    var v = Number(n);
    if (!isFinite(v)) return '—';
    return '₹' + v.toLocaleString('en-IN', { minimumFractionDigits: 0, maximumFractionDigits: 2 });
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

  /** Units allowed for a recipe line based on Product Master default unit. */
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
      '<div class="se-filter-chip se-filter-chip--payment se-filter-chip--listbox ep-form-listbox pos-menu-unit-listbox" data-se-listbox id="' +
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
    setTimeout(function () {
      var rows = document.querySelectorAll('#pos-menu-recipe-list [data-recipe-qty]');
      var last = rows[rows.length - 1];
      if (last) last.focus();
    }, 20);
  }

  function collectRecipePayload() {
    syncRecipeDraftFromDom();
    var out = [];
    for (var i = 0; i < recipeDraft.length; i++) {
      var line = recipeDraft[i];
      var label = line.product_name || 'ingredient';
      var rawQty = line.qty;
      if (rawQty === '' || rawQty == null) {
        return { error: 'Enter quantity for ' + label + '.' };
      }
      var qty = Number(rawQty);
      if (!isFinite(qty) || qty <= 0) {
        return { error: 'Quantity for ' + label + ' must be greater than zero.' };
      }
      var unit = coerceRecipeUnit(line.product_unit, line.unit);
      var allowed = recipeUnitsForProduct(line.product_unit);
      if (allowed.indexOf(unit) === -1) {
        return { error: 'Choose a valid unit for ' + label + '.' };
      }
      out.push({ product_id: Number(line.product_id), qty: qty, unit: unit });
    }
    return { recipe: out };
  }

  function $all(sel, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(sel));
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

  function renderCategories() {
    var list = $('#pos-menu-cat-list');
    var empty = $('#pos-menu-cat-empty');
    var count = $('#pos-menu-cat-count');
    if (!list) return;
    if (count) count.textContent = categories.length ? categories.length + ' total' : '—';
    if (!categories.length) {
      list.innerHTML = '';
      if (empty) empty.hidden = false;
      return;
    }
    if (empty) empty.hidden = true;
    list.innerHTML = categories
      .map(function (c) {
        var selected = Number(c.id) === Number(selectedCategoryId);
        var n = Number(c.item_count || 0);
        var badge = c.is_visible
          ? '<span class="pos-set-badge">Visible</span>'
          : '<span class="pos-set-badge pos-set-badge--muted">Hidden</span>';
        return (
          '<li class="' +
          (selected ? 'is-selected' : '') +
          '" role="option" aria-selected="' +
          (selected ? 'true' : 'false') +
          '" data-category-id="' +
          escapeHtml(c.id) +
          '" tabindex="0">' +
          '<div class="pos-menu-row-main"><strong>' +
          escapeHtml(c.name) +
          '</strong><small>' +
          n +
          (n === 1 ? ' item' : ' items') +
          '</small></div>' +
          '<div class="pos-menu-row-actions">' +
          badge +
          '<button type="button" class="pos-menu-icon-btn" data-pos-menu-action="edit-category" data-category-id="' +
          escapeHtml(c.id) +
          '" title="Edit category" aria-label="Edit category">' +
          '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>' +
          '</button></div></li>'
        );
      })
      .join('');
  }

  function renderItems() {
    var list = $('#pos-menu-item-list');
    var empty = $('#pos-menu-item-empty');
    var title = $('#pos-menu-items-title');
    var count = $('#pos-menu-item-count');
    var addBtn = $('#pos-menu-add-item');
    var cat = findCategory(selectedCategoryId);
    if (addBtn) addBtn.disabled = !cat;
    if (title) title.textContent = cat ? cat.name : 'Items';
    if (!list) return;
    if (!cat) {
      list.innerHTML = '';
      if (count) count.textContent = 'Select a category';
      if (empty) {
        empty.hidden = false;
        empty.textContent = 'Select a category to view and add items.';
      }
      return;
    }
    if (count) count.textContent = items.length + (items.length === 1 ? ' item' : ' items');
    if (!items.length) {
      list.innerHTML = '';
      if (empty) {
        empty.hidden = false;
        empty.textContent = 'No items yet. Add a menu item and its ingredients.';
      }
      return;
    }
    if (empty) empty.hidden = true;
    list.innerHTML = items
      .map(function (it) {
        var meta = [];
        if (it.code) meta.push(it.code);
        if (it.variant) meta.push(it.variant);
        var recipeCount = Array.isArray(it.recipe) ? it.recipe.length : 0;
        if (recipeCount) meta.push(recipeCount === 1 ? '1 ingredient' : recipeCount + ' ingredients');
        meta.push(formatRate(it.rate));
        return (
          '<li data-item-id="' +
          escapeHtml(it.id) +
          '" tabindex="0">' +
          '<div class="pos-menu-row-main"><strong>' +
          escapeHtml(it.name) +
          '</strong><small>' +
          escapeHtml(meta.join(' · ')) +
          '</small></div>' +
          '<div class="pos-menu-row-actions">' +
          '<button type="button" class="pos-menu-icon-btn" data-pos-menu-action="edit-item" data-item-id="' +
          escapeHtml(it.id) +
          '" title="Edit item" aria-label="Edit item">' +
          '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>' +
          '</button>' +
          '<button type="button" class="pos-menu-icon-btn pos-menu-icon-btn--danger" data-pos-menu-action="delete-item" data-item-id="' +
          escapeHtml(it.id) +
          '" title="Delete item" aria-label="Delete item">' +
          '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M9 7V5h6v2M8 7l1 12h6l1-12"/></svg>' +
          '</button></div></li>'
        );
      })
      .join('');
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
    renderCategories();
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

  function fetchItemsThen(categoryId, cb) {
    if (categoryId == null) {
      items = [];
      renderItems();
      if (typeof cb === 'function') cb();
      return;
    }
    fetch(ITEMS_API + '?category_id=' + encodeURIComponent(categoryId), {
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
        renderItems();
        if (typeof cb === 'function') cb();
      })
      .catch(function (err) {
        items = [];
        renderItems();
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

  function selectCategory(id) {
    selectedCategoryId = id == null ? null : Number(id);
    renderCategories();
    fetchItemsThen(selectedCategoryId);
  }

  function openModal(id) {
    var modal = document.getElementById(id);
    if (modal) modal.classList.add('active');
  }

  function closeModal(id) {
    var modal = document.getElementById(id);
    if (modal) modal.classList.remove('active');
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

  function openItemModal(item) {
    var cat = findCategory(selectedCategoryId);
    if (!cat) {
      showToast('Select a category first.');
      return;
    }
    var isEdit = !!(item && item.id);
    $('#pos-menu-item-title').textContent = isEdit ? 'Edit menu item' : 'Add menu item';
    $('#pos-menu-item-copy').textContent =
      'Category: ' + cat.name + '. Add ingredients below with the quantity required per serving.';
    $('#pos-menu-item-id').value = isEdit ? String(item.id) : '';
    $('#pos-menu-item-category-id').value = String(cat.id);
    $('#pos-menu-item-name').value = isEdit ? item.name || '' : '';
    $('#pos-menu-item-code').value = isEdit ? item.code || '' : '';
    $('#pos-menu-item-rate').value = isEdit ? String(item.rate != null ? item.rate : '') : '';
    $('#pos-menu-item-variant').value = isEdit ? item.variant || '' : '';
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
  }

  global.onPosMenuProductPicked = function (root, value) {
    if (!value) return;
    addRecipeLine(value);
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
        fetchItemsThen(selectedCategoryId);
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
        fetchItemsThen(selectedCategoryId);
      })
      .catch(function () {
        busy = false;
        setErr($('#pos-menu-cat-err'), 'Could not delete category.');
      });
  }

  function saveItem(e) {
    if (e) {
      e.preventDefault();
      e.stopPropagation();
    }
    if (busy) return;
    var err = $('#pos-menu-item-err');
    var idVal = ($('#pos-menu-item-id').value || '').trim();
    var categoryId = ($('#pos-menu-item-category-id').value || '').trim();
    var name = ($('#pos-menu-item-name').value || '').trim();
    var code = ($('#pos-menu-item-code').value || '').trim();
    var variant = ($('#pos-menu-item-variant').value || '').trim();
    var rate = ($('#pos-menu-item-rate').value || '').trim();
    if (!categoryId || !isFinite(Number(categoryId))) {
      setErr(err, 'Select a category first.');
      showToast('Select a category first.');
      return;
    }
    if (!name) {
      setErr(err, 'Menu name is required.');
      showToast('Menu name is required.');
      return;
    }
    if (rate === '' || Number(rate) < 0 || !isFinite(Number(rate))) {
      setErr(err, 'Enter a valid rate.');
      showToast('Enter a valid rate.');
      return;
    }
    var recipeResult = collectRecipePayload();
    if (recipeResult.error) {
      setErr(err, recipeResult.error);
      showToast(recipeResult.error);
      return;
    }
    busy = true;
    setErr(err, '');
    var payload = {
      category_id: Number(categoryId),
      product_id: null,
      name: name,
      code: code,
      variant: variant,
      rate: Number(rate),
      recipe: recipeResult.recipe
    };
    if (idVal) payload.id = Number(idVal);
    fetch(ITEMS_API, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
      body: JSON.stringify(payload)
    })
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
        busy = false;
        if (!res.ok || !res.data || !res.data.ok) {
          var msg = (res.data && res.data.error) || 'Could not save item.';
          setErr(err, msg);
          showToast(msg);
          return;
        }
        if (res.data.categories) applyCategories(res.data.categories, selectedCategoryId);
        items = Array.isArray(res.data.items) ? res.data.items : items;
        renderCategories();
        renderItems();
        closeModal('pos-menu-item-modal');
        showToast(idVal ? 'Item updated' : 'Item added');
      })
      .catch(function () {
        busy = false;
        setErr(err, 'Could not save item.');
        showToast('Could not save item.');
      });
  }

  function deleteItem(itemId) {
    var id = itemId || ($('#pos-menu-item-id').value || '').trim();
    if (!id || busy) return;
    if (!window.confirm('Delete this menu item?')) return;
    busy = true;
    var url =
      ITEMS_API +
      '/' +
      encodeURIComponent(id) +
      '/delete' +
      (selectedCategoryId != null ? '?category_id=' + encodeURIComponent(selectedCategoryId) : '');
    fetch(url, {
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
        if (Array.isArray(res.data.items)) {
          items = res.data.items;
        } else {
          items = items.filter(function (it) {
            return Number(it.id) !== Number(id);
          });
        }
        renderCategories();
        renderItems();
        closeModal('pos-menu-item-modal');
        showToast('Item deleted');
      })
      .catch(function () {
        busy = false;
        showToast('Could not delete item.');
      });
  }

  function bindPage(page) {
    if (!page || page.getAttribute('data-pos-menu-bound') === '1') return;
    page.setAttribute('data-pos-menu-bound', '1');

    page.addEventListener('click', function (e) {
      var t = e.target;
      if (!t) return;
      var dismiss = t.closest('[data-pos-menu-dismiss]');
      if (dismiss) {
        var which = dismiss.getAttribute('data-pos-menu-dismiss');
        if (which === 'cat') closeModal('pos-menu-cat-modal');
        if (which === 'item') closeModal('pos-menu-item-modal');
        return;
      }
      var actionBtn = t.closest('[data-pos-menu-action]');
      if (actionBtn) {
        var action = actionBtn.getAttribute('data-pos-menu-action');
        if (action === 'add-category') {
          openCategoryModal(null);
          return;
        }
        if (action === 'add-item') {
          openItemModal(null);
          return;
        }
        if (action === 'edit-category') {
          e.stopPropagation();
          openCategoryModal(findCategory(actionBtn.getAttribute('data-category-id')));
          return;
        }
        if (action === 'edit-item') {
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
          return;
        }
        if (action === 'delete-item') {
          e.stopPropagation();
          deleteItem(actionBtn.getAttribute('data-item-id'));
          return;
        }
      }
      var catRow = t.closest('#pos-menu-cat-list li[data-category-id]');
      if (catRow && !t.closest('[data-pos-menu-action]')) {
        selectCategory(catRow.getAttribute('data-category-id'));
        return;
      }
      var itemRow = t.closest('#pos-menu-item-list li[data-item-id]');
      if (itemRow && !t.closest('[data-pos-menu-action]')) {
        openItemModal(findItem(itemRow.getAttribute('data-item-id')));
      }
    });

    var catForm = $('#pos-menu-cat-form');
    if (catForm) catForm.addEventListener('submit', saveCategory);
    var itemForm = $('#pos-menu-item-form');
    if (itemForm) itemForm.addEventListener('submit', saveItem);
    var itemSave = $('#pos-menu-item-save');
    if (itemSave && itemSave.getAttribute('data-save-bound') !== '1') {
      itemSave.setAttribute('data-save-bound', '1');
      itemSave.addEventListener('click', function (e) {
        e.preventDefault();
        saveItem(e);
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

    ['pos-menu-cat-modal', 'pos-menu-item-modal'].forEach(function (id) {
      var modal = document.getElementById(id);
      if (!modal || modal.getAttribute('data-overlay-bound') === '1') return;
      modal.setAttribute('data-overlay-bound', '1');
      modal.addEventListener('click', function (e) {
        if (e.target === modal) closeModal(id);
      });
    });
  }

  function initPosMenuSettings() {
    var page = document.getElementById('pos-settings-page');
    if (!page) return;
    bindPage(page);
    productsLoaded = false;
    fetchCategoriesThen(function () {
      fetchItemsThen(selectedCategoryId);
    });
  }

  global.initPosMenuSettings = initPosMenuSettings;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initPosMenuSettings);
  } else if (!global.__deSoftNavInProgress) {
    /* Soft-nav: settings page init calls initPosMenuSettings once — avoid double category/item fetch. */
    initPosMenuSettings();
  }
})(window);
