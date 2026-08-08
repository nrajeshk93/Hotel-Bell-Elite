(function () {
  'use strict';

  function stSoftNavigate(url) {
    if (!url) return;
    // Soft-nav during the click gesture keeps browser fullscreen (hard assign exits it).
    if (typeof window.deNavigateWithTransition === 'function') {
      window.deNavigateWithTransition(url);
    } else if (typeof window.deSoftRefresh === 'function') {
      window.deSoftRefresh(url);
    } else {
      window.location.assign(url);
    }
  }

  window.stOutletChanged = function (root, value) {
    if (!root || !value) return;
    var endpoint = root.getAttribute('data-st-list-endpoint') || window.location.pathname;
    try {
      var url = new URL(endpoint, window.location.origin);
      url.searchParams.set('outlet', value);
      if (document.getElementById('st-indent-form') || /(?:\?|&)focus=form(?:&|$)/.test(window.location.search)) {
        url.searchParams.set('focus', 'form');
      }
      var indentView = root.getAttribute('data-st-indent-view') || '';
      if (!indentView) {
        try { indentView = new URL(window.location.href).searchParams.get('view') || ''; } catch (err) {}
      }
      if (indentView) url.searchParams.set('view', indentView);
      // Stock Inward / Purchase Order: changing outlet clears PO / indent / supplier.
      if (
        document.getElementById('st-inward-page') ||
        document.getElementById('st-inward-indent-listbox') ||
        document.getElementById('st-po-indent-listbox')
      ) {
        url.searchParams.delete('indent');
        url.searchParams.delete('po');
        url.searchParams.delete('po_id');
        url.searchParams.delete('supplier_id');
      }
      stSoftNavigate(url.pathname + url.search);
    } catch (e) {
      var qs = 'outlet=' + encodeURIComponent(value);
      if (document.getElementById('st-indent-form')) qs += '&focus=form';
      var view = root.getAttribute('data-st-indent-view') || '';
      if (view) qs += '&view=' + encodeURIComponent(view);
      stSoftNavigate(endpoint + (endpoint.indexOf('?') >= 0 ? '&' : '?') + qs);
    }
  };

  /* Product Master embed (Indent popup / Masters modal) — keep outlet changes inside the embed. */
  window.stProductMasterOutletChanged = function (root, value) {
    if (!root || !value) return;
    var endpoint = root.getAttribute('data-st-list-endpoint') || '/stores/product-master';
    var next = '';
    try {
      var url = new URL(endpoint, window.location.origin);
      url.searchParams.set('outlet', value);
      url.searchParams.set('embed', '1');
      next = url.pathname + url.search + url.hash;
    } catch (err) {
      next = endpoint + (endpoint.indexOf('?') >= 0 ? '&' : '?') +
        'outlet=' + encodeURIComponent(value) + '&embed=1';
    }
    var indentPm = document.getElementById('st-product-master-modal');
    if (indentPm && indentPm.classList.contains('open')) {
      loadProductMasterModal(true, next);
      return;
    }
    var masterModal = document.getElementById('md-master-modal');
    var masterInject = document.getElementById('md-master-modal-inject');
    if (masterModal && masterModal.classList.contains('open') && masterInject) {
      var link = document.createElement('a');
      link.setAttribute('href', next);
      masterInject.appendChild(link);
      link.click();
      if (link.parentNode) link.parentNode.removeChild(link);
      return;
    }
    stSoftNavigate(next);
  };

  function setUnitListbox(line, unit) {
    if (!line || !unit) return;
    var unitRoot = line.querySelector('[data-st-unit-listbox]');
    var unitInput = line.querySelector('[data-st-unit]');
    if (!unitRoot || !unitInput) return;
    if (typeof window.resetEpListbox === 'function' && unitInput.id) {
      window.resetEpListbox(unitInput.id, unit, unit);
      return;
    }
    unitInput.value = unit;
    var valueEl = unitRoot.querySelector('.se-filter-chip-value');
    if (valueEl) {
      valueEl.textContent = unit;
      valueEl.classList.remove('is-placeholder');
    }
    unitRoot.querySelectorAll('.se-filter-listbox-option').forEach(function (opt) {
      var on = (opt.getAttribute('data-value') || '') === unit;
      opt.classList.toggle('is-selected', on);
      opt.setAttribute('aria-selected', on ? 'true' : 'false');
    });
  }

  function productUnitForLine(line) {
    if (!line) return 'kg';
    var productSelected = line.querySelector('.st-product-listbox .se-filter-listbox-option.is-selected');
    var unit = productSelected && productSelected.getAttribute('data-unit');
    if (unit) return String(unit);
    var unitInput = line.querySelector('[data-st-unit]');
    return (unitInput && String(unitInput.value || '').trim()) || 'kg';
  }

  function syncUnitForPack(line) {
    if (!line) return;
    var labelInput = line.querySelector('[data-st-pack-label]');
    var qtyInput = line.querySelector('[data-st-pack-qty]');
    var packLabel = labelInput ? String(labelInput.value || '').trim() : '';
    var packQty = qtyInput ? String(qtyInput.value || '').trim() : '';
    var baseUnit = productUnitForLine(line);
    var unitRoot = line.querySelector('[data-st-unit-listbox]');
    var unitInput = line.querySelector('[data-st-unit]');
    if (!unitRoot || !unitInput) return;

    // Stock always stays in the product base unit; pack selection only changes display.
    unitInput.value = baseUnit;
    unitRoot.querySelectorAll('.se-filter-listbox-option').forEach(function (opt) {
      var on = (opt.getAttribute('data-value') || '') === baseUnit;
      opt.classList.toggle('is-selected', on);
      opt.setAttribute('aria-selected', on ? 'true' : 'false');
    });

    var valueEl = unitRoot.querySelector('.se-filter-chip-value');
    if (!valueEl) return;
    valueEl.textContent = baseUnit;
    valueEl.classList.remove('is-placeholder');
    if (packLabel && packQty !== '') {
      unitRoot.classList.add('is-pack-locked');
    } else {
      unitRoot.classList.remove('is-pack-locked');
    }
  }

  function lineHasProduct(line) {
    if (!line) return false;
    var hidden = line.querySelector('input[name="item_name"]');
    return !!(hidden && String(hidden.value || '').trim());
  }

  function lineHasValidQty(line) {
    if (!line) return false;
    var qtyEl = line.querySelector('input[name="quantity"]');
    var qty = qtyEl ? parseFloat(qtyEl.value) : NaN;
    return isFinite(qty) && qty > 0;
  }

  function indentFormCanSendForApproval(form) {
    if (!form) return false;
    var lines = form.querySelectorAll('.st-line');
    var productCount = 0;
    for (var i = 0; i < lines.length; i++) {
      var line = lines[i];
      if (!lineHasProduct(line)) continue;
      productCount += 1;
      if (!lineHasValidQty(line)) return false;
    }
    return productCount > 0;
  }

  function syncIndentSendButtons(scope) {
    var forms = [];
    if (scope) {
      var form = (scope.id === 'st-indent-form' || scope.id === 'st-indent-edit-form')
        ? scope
        : (scope.closest && scope.closest('#st-indent-form, #st-indent-edit-form'));
      if (form) forms.push(form);
    } else {
      var mainForm = document.getElementById('st-indent-form');
      var editForm = document.getElementById('st-indent-edit-form');
      if (mainForm) forms.push(mainForm);
      if (editForm) forms.push(editForm);
    }
    forms.forEach(function (form) {
      var canSend = indentFormCanSendForApproval(form);
      form.querySelectorAll('[data-st-indent-send]').forEach(function (btn) {
        btn.disabled = !canSend;
        btn.setAttribute('aria-disabled', canSend ? 'false' : 'true');
        if (!canSend) {
          btn.title = 'Enter a quantity for each item before sending for approval.';
        } else {
          btn.removeAttribute('title');
        }
      });
      form.querySelectorAll('.st-line').forEach(function (line) {
        var qtyEl = line.querySelector('input[name="quantity"]');
        if (!qtyEl) return;
        var needsQty = lineHasProduct(line);
        qtyEl.setAttribute('aria-required', needsQty ? 'true' : 'false');
        line.classList.toggle('is-qty-missing', needsQty && !lineHasValidQty(line));
      });
    });
  }

  function syncUnitVisibility(line) {
    if (!line) return;
    var hasProduct = lineHasProduct(line);
    line.classList.toggle('is-product-selected', hasProduct);
    var unitRoot = line.querySelector('[data-st-unit-listbox]');
    if (!unitRoot) return;
    var valueEl = unitRoot.querySelector('.se-filter-chip-value');
    var unitInput = line.querySelector('[data-st-unit]');
    if (!hasProduct && valueEl) {
      valueEl.textContent = 'Select unit';
      valueEl.classList.add('is-placeholder');
      if (unitInput && !unitInput.value) unitInput.value = 'kg';
    }
  }

  function appendEmptyLine(list) {
    if (!list) return null;
    var wrap = list.closest('.st-lines-wrap');
    var template = wrap && wrap.querySelector('template');
    if (!template) return null;
    var node = template.content.cloneNode(true);
    var line = node.querySelector('.st-line');
    if (line) rewireListboxIds(line);
    list.appendChild(node);
    if (typeof window.initEpListboxes === 'function') window.initEpListboxes();
    return list.querySelector('.st-line:last-child');
  }

  function ensureTrailingEmptyLine(list) {
    if (!list) return null;
    var lines = list.querySelectorAll('.st-line');
    var last = lines[lines.length - 1];
    if (last && !lineHasProduct(last)) return null;
    return appendEmptyLine(list);
  }

  function setApproxPrice(line, price) {
    if (!line) return;
    var input = line.querySelector('[data-st-approx-price], input[name="approximate_price"]');
    if (!input) return;
    // Direct Stock Inward: leave Price blank so the user must enter it.
    // Still allow clears (empty price) when the product/pack is reset.
    var isDirect = !!(
      input.hasAttribute('data-st-direct-price')
      || line.matches('[data-st-inward-direct-row], .st-inward-direct-line')
      || line.closest('#st-inward-direct-lines, .st-inward-direct-lines-wrap')
    );
    if (isDirect && price != null && String(price).trim() !== '') {
      return;
    }
    input.value = price == null || price === '' ? '' : String(price);
    syncIndentLineTotals(line.closest('.st-lines-wrap') || line.closest('.st-lines'));
  }

  function formatIndentMoney(amount) {
    var n = Number(amount || 0);
    if (!isFinite(n) || n <= 0) return '—';
    if (typeof window.formatINR === 'function') return window.formatINR(n, 2);
    return '₹' + n.toLocaleString('en-IN', { minimumFractionDigits: 0, maximumFractionDigits: 2 });
  }

  function syncIndentLineTotals(scope) {
    var root = scope;
    if (root && root.classList && root.classList.contains('st-lines')) {
      root = root.closest('.st-lines-wrap') || root.parentElement;
    }
    if (!root) {
      root = document.querySelector('#st-indent-edit-modal.open .st-lines-wrap')
        || document.querySelector('#st-indent-form .st-lines-wrap')
        || document.querySelector('#st-inward-form .st-lines-wrap')
        || document;
    }
    var lines = root.querySelectorAll ? root.querySelectorAll('.st-line') : [];
    var grand = 0;
    lines.forEach(function (line) {
      var qtyEl = line.querySelector('input[name="quantity"]');
      var priceEl = line.querySelector('[data-st-approx-price], input[name="approximate_price"], input[name="unit_price"]');
      var taxEl = line.querySelector('[data-st-direct-tax], input[name="tax_percent"]');
      var totalEl = line.querySelector('[data-st-line-total]');
      var qty = qtyEl ? parseFloat(qtyEl.value) : 0;
      var price = priceEl ? parseFloat(priceEl.value) : 0;
      var tax = taxEl ? parseFloat(taxEl.value) : 0;
      if (!isFinite(tax) || tax < 0) tax = 0;
      var lineTotal = 0;
      if (isFinite(qty) && qty > 0 && isFinite(price) && price > 0) {
        lineTotal = Math.round(qty * price * (1 + tax / 100) * 100) / 100;
      }
      if (totalEl) {
        totalEl.textContent = lineTotal > 0 ? formatIndentMoney(lineTotal) : '—';
        totalEl.classList.toggle('is-empty', lineTotal <= 0);
      }
      grand += lineTotal;
    });
    var grandEl = root.querySelector
      ? (root.querySelector('[data-st-indent-grand-total]')
        || root.querySelector('[data-st-inward-direct-grand-total]'))
      : null;
    if (!grandEl && root !== document) {
      var wrap = (root.closest && root.closest('.st-lines-wrap')) || root;
      grandEl = wrap.querySelector
        ? (wrap.querySelector('[data-st-indent-grand-total]')
          || wrap.querySelector('[data-st-inward-direct-grand-total]'))
        : null;
    }
    if (grandEl) grandEl.textContent = grand > 0 ? formatIndentMoney(grand) : '—';
    try {
      if (typeof isDirectInwardMode === 'function' && isDirectInwardMode()) {
        var directConfirm = document.getElementById('st-inward-confirm');
        if (directConfirm && typeof selectedDirectInwardLines === 'function') {
          directConfirm.disabled = selectedDirectInwardLines().length === 0;
        }
      }
    } catch (err) { /* ignore */ }
    try {
      syncIndentSendButtons(root);
    } catch (err2) { /* ignore */ }
  }

  window.stProductPicked = function (root) {
    if (!root) return;
    var line = root.closest('.st-line');
    if (!line) return;
    var selected = root.querySelector('.se-filter-listbox-option.is-selected');
    var unit = selected && selected.getAttribute('data-unit');
    var price = selected ? selected.getAttribute('data-price') : '';
    setUnitListbox(line, unit);
    setApproxPrice(line, price || '');
    syncPackOptions(line, selected, '');
    syncUnitVisibility(line);
    syncIndentLineTotals(line.closest('.st-lines-wrap'));
    syncIndentSendButtons(line.closest('form') || line.closest('.st-lines-wrap'));

    if (!lineHasProduct(line)) return;
    var list = line.closest('.st-lines');
    var next = ensureTrailingEmptyLine(list);
    if (next) syncUnitVisibility(next);
    if (next) {
      var qty = line.querySelector('input[name="quantity"]');
      if (qty && !String(qty.value || '').trim()) {
        try { qty.focus(); } catch (e) {}
      }
    }
  };

  window.stPackPicked = function (root) {
    if (!root) return;
    var line = root.closest('.st-line');
    if (!line) return;
    var selected = root.querySelector('.se-filter-listbox-option.is-selected');
    var packLabel = selected ? (selected.getAttribute('data-value') || '') : '';
    var packQty = selected ? (selected.getAttribute('data-qty') || '') : '';
    var packPrice = selected ? (selected.getAttribute('data-price') || '') : '';
    var labelInput = line.querySelector('[data-st-pack-label]');
    var qtyInput = line.querySelector('[data-st-pack-qty]');
    if (labelInput) labelInput.value = packLabel;
    if (qtyInput) qtyInput.value = packLabel ? packQty : '';
    if (packLabel && packPrice) {
      setApproxPrice(line, packPrice);
    } else if (!packLabel) {
      var productSelected = line.querySelector('.st-product-listbox .se-filter-listbox-option.is-selected');
      var productPrice = productSelected ? productSelected.getAttribute('data-price') : '';
      setApproxPrice(line, productPrice || '');
    }
    syncUnitForPack(line);
    syncIndentLineTotals(line.closest('.st-lines-wrap'));
  };

  function parseVariantsAttr(raw) {
    if (!raw) return [];
    try {
      var parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed : [];
    } catch (e) {
      return [];
    }
  }

  function syncPackOptions(line, productOption, preferredLabel, opts) {
    if (!line) return;
    opts = opts || {};
    var variants = parseVariantsAttr(productOption && productOption.getAttribute('data-variants'));
    var packRoot = line.querySelector('[data-st-pack-listbox]');
    var optionsWrap = packRoot && packRoot.querySelector('[data-st-pack-options]');
    var labelInput = line.querySelector('[data-st-pack-label]');
    var qtyInput = line.querySelector('[data-st-pack-qty]');
    line.classList.toggle('has-packs', variants.length > 0);
    if (!optionsWrap) return;

    var html = '<button type="button" class="se-filter-listbox-option" role="option" data-value="" data-name="base unit" data-label="Base unit" data-qty="" data-price="" aria-selected="false">Base unit</button>';
    variants.forEach(function (variant) {
      var label = String((variant && variant.label) || '');
      if (!label) return;
      var qty = variant.qty_in_base_display != null && variant.qty_in_base_display !== ''
        ? variant.qty_in_base_display
        : (variant.qty_in_base != null ? variant.qty_in_base : '');
      var price = variant.approximate_price_display != null
        ? variant.approximate_price_display
        : (variant.approximate_price != null ? variant.approximate_price : '');
      html += '<button type="button" class="se-filter-listbox-option" role="option" data-value="'
        + escapeHtml(label) + '" data-name="' + escapeHtml(label.toLowerCase())
        + '" data-label="' + escapeHtml(label) + '" data-qty="' + escapeHtml(String(qty))
        + '" data-price="' + escapeHtml(String(price || ''))
        + '" aria-selected="false">' + escapeHtml(label) + '</button>';
    });
    optionsWrap.innerHTML = html;

    var choose = preferredLabel || '';
    if (choose) {
      var hasPreferred = false;
      optionsWrap.querySelectorAll('.se-filter-listbox-option').forEach(function (opt) {
        if ((opt.getAttribute('data-value') || '') === choose) hasPreferred = true;
      });
      if (!hasPreferred) choose = '';
    }
    if (!choose && variants.length && !opts.keepBaseWhenEmpty) {
      // Default to first pack when product has variants.
      choose = String(variants[0].label || '');
    }
    var selectedOpt = null;
    optionsWrap.querySelectorAll('.se-filter-listbox-option').forEach(function (opt) {
      if (selectedOpt) return;
      if ((opt.getAttribute('data-value') || '') === choose) selectedOpt = opt;
    });
    if (!selectedOpt) selectedOpt = optionsWrap.querySelector('.se-filter-listbox-option');
    optionsWrap.querySelectorAll('.se-filter-listbox-option').forEach(function (opt) {
      var on = opt === selectedOpt;
      opt.classList.toggle('is-selected', on);
      opt.setAttribute('aria-selected', on ? 'true' : 'false');
    });
    var valueEl = packRoot.querySelector('.se-filter-chip-value');
    var selectedLabel = selectedOpt
      ? (selectedOpt.getAttribute('data-label') || selectedOpt.textContent || 'Base unit')
      : 'Pack';
    var selectedValue = selectedOpt ? (selectedOpt.getAttribute('data-value') || '') : '';
    var selectedQty = selectedOpt ? (selectedOpt.getAttribute('data-qty') || '') : '';
    var selectedPrice = selectedOpt ? (selectedOpt.getAttribute('data-price') || '') : '';
    if (labelInput) labelInput.value = selectedValue;
    if (qtyInput) qtyInput.value = selectedValue ? selectedQty : '';
    if (valueEl) {
      valueEl.textContent = selectedLabel;
      valueEl.classList.toggle('is-placeholder', !selectedValue && !variants.length);
    }
    if (selectedValue && selectedPrice) {
      setApproxPrice(line, selectedPrice);
    }
    syncUnitForPack(line);
    // Do not re-bind the pack listbox here — resetting __epListboxBound and calling
    // initEpListboxes() stacks click handlers so the menu opens then immediately closes.
  }

  function uniqueId(prefix) {
    return (prefix || 'st-item-') + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
  }

  function rewireOneListbox(root, opts) {
    if (!root) return;
    var fid = uniqueId(opts.prefix);
    root.id = fid + '-listbox';
    root.__epListboxBound = false;

    var label = root.querySelector('.se-filter-chip-label');
    var trigger = root.querySelector('.se-filter-chip-trigger');
    var valueEl = root.querySelector('.se-filter-chip-value');
    var list = root.querySelector('.se-filter-listbox');
    var hidden = root.querySelector('input[type="hidden"]');
    var isCombo = root.hasAttribute('data-se-listbox-combobox');

    if (label) {
      label.id = fid + '-label';
      label.setAttribute('for', fid + '-trigger');
    }
    if (trigger) {
      trigger.id = fid + '-trigger';
      trigger.setAttribute('aria-controls', fid + '-list');
      trigger.setAttribute('aria-expanded', 'false');
      if (isCombo) {
        trigger.setAttribute('aria-labelledby', fid + '-label');
        trigger.value = opts.defaultValue || '';
        trigger.placeholder = opts.placeholder || 'Search product…';
        trigger.classList.toggle('is-placeholder', !opts.defaultValue);
      } else {
        trigger.setAttribute('aria-labelledby', fid + '-label ' + fid + '-value');
      }
    }
    if (valueEl) {
      valueEl.id = fid + '-value';
      valueEl.textContent = opts.placeholder || opts.defaultValue || '';
      valueEl.classList.toggle('is-placeholder', !!opts.placeholder);
    }
    if (list) {
      list.id = fid + '-list';
      list.hidden = true;
      if (label) list.setAttribute('aria-labelledby', fid + '-label');
      list.querySelectorAll('.se-filter-listbox-option').forEach(function (opt) {
        var on = opts.defaultValue
          ? (opt.getAttribute('data-value') || '') === opts.defaultValue
          : false;
        opt.classList.toggle('is-selected', on);
        opt.setAttribute('aria-selected', on ? 'true' : 'false');
      });
    }
    if (hidden) {
      hidden.id = fid;
      hidden.value = opts.defaultValue || '';
    }
    root.classList.remove('is-open');
  }

  function rewireListboxIds(line) {
    rewireOneListbox(line.querySelector('.st-product-listbox'), {
      prefix: 'st-item-',
      placeholder: 'Select Product'
    });
    rewireOneListbox(line.querySelector('.st-unit-listbox'), {
      prefix: 'st-unit-',
      defaultValue: 'kg',
      placeholder: 'Select unit'
    });
    rewireOneListbox(line.querySelector('.st-pack-listbox'), {
      prefix: 'st-pack-',
      defaultValue: '',
      placeholder: 'Pack'
    });
    var qty = line.querySelector('input[name="quantity"]');
    if (qty) qty.value = '';
    var packLabel = line.querySelector('[data-st-pack-label]');
    var packQty = line.querySelector('[data-st-pack-qty]');
    if (packLabel) packLabel.value = '';
    if (packQty) packQty.value = '';
    line.classList.remove('has-packs');
    setApproxPrice(line, '');
    syncUnitVisibility(line);
  }

  function addLine(btn) {
    var wrap = btn.closest('.st-lines-wrap');
    if (!wrap) return;
    var list = wrap.querySelector('.st-lines');
    appendEmptyLine(list);
  }

  function removeLine(btn) {
    var line = btn.closest('.st-line');
    var list = btn.closest('.st-lines');
    if (!line || !list) return;
    if (list.querySelectorAll('.st-line').length <= 1) {
      var productRoot = line.querySelector('.st-product-listbox');
      if (productRoot && typeof window.resetEpListbox === 'function') {
        var productHidden = productRoot.querySelector('input[type="hidden"]');
        if (productHidden) window.resetEpListbox(productHidden.id, '', 'Select Product');
      }
      line.querySelectorAll('input[type="number"], input[type="text"]').forEach(function (field) {
        field.value = '';
      });
      var packLabel = line.querySelector('[data-st-pack-label]');
      var packQty = line.querySelector('[data-st-pack-qty]');
      if (packLabel) packLabel.value = '';
      if (packQty) packQty.value = '';
      line.classList.remove('has-packs');
      setUnitListbox(line, 'kg');
      setApproxPrice(line, '');
      syncUnitVisibility(line);
      syncIndentLineTotals(list.closest('.st-lines-wrap') || list);
      return;
    }
    line.remove();
    syncIndentLineTotals(list.closest('.st-lines-wrap') || list);
  }

  function syncNotesCounter() {
    var root = document.querySelector('#st-indent-edit-modal.open') || document;
    var area = root.querySelector('[data-st-notes-counter]');
    var countEl = root.querySelector('[data-st-notes-count]');
    if (!area || !countEl) return;
    countEl.textContent = String((area.value || '').length);
  }

  function escapeHtml(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function loadIndentViewMap() {
    var el = document.getElementById('st-indent-view-data');
    if (!el) return {};
    try {
      var rows = JSON.parse(el.textContent || '[]') || [];
      var map = {};
      rows.forEach(function (row) {
        if (row && row.id != null) map[String(row.id)] = row;
      });
      return map;
    } catch (e) {
      return {};
    }
  }

  function modalHost() {
    return document.getElementById('de-fs-app') || document.body;
  }

  function purgeOtherModals(modal) {
    if (!modal || !modal.id) return;
    Array.from(document.querySelectorAll('#' + modal.id)).forEach(function (el) {
      if (el !== modal && el.parentNode) el.parentNode.removeChild(el);
    });
  }

  function mountModal(modal) {
    if (!modal) return;
    var host = modalHost();
    if (!host) return;
    purgeOtherModals(modal);
    if (modal.parentElement !== host) host.appendChild(modal);
  }

  function cleanupHostedIndentModals() {
    var host = modalHost();
    var main = document.querySelector('.de-main-wrapper');
    if (!host) return;
    ['st-indent-view-modal', 'st-indent-edit-modal', 'st-reject-modal', 'st-stores-ledger-modal', 'st-ledger-pending-modal', 'st-approvals-modal', 'st-product-master-modal', 'st-po-pdf-modal'].forEach(function (id) {
      var live = main ? main.querySelector('#' + id) : null;
      Array.from(document.querySelectorAll('#' + id)).forEach(function (el) {
        // Keep overlays that are open (mountModal moves them onto #de-fs-app).
        if (el.classList.contains('open') || el.classList.contains('active')) return;
        if (live && el === live) return;
        if (!live && el.parentElement === host) {
          el.parentNode.removeChild(el);
          return;
        }
        if (live && el !== live && el.parentNode) el.parentNode.removeChild(el);
      });
    });
  }

  function closeIndentViewModal() {
    var modal = document.getElementById('st-indent-view-modal');
    if (!modal) return;
    modal.classList.remove('open');
    modal.setAttribute('aria-hidden', 'true');
  }

  function closeIndentEditModal() {
    var modal = document.getElementById('st-indent-edit-modal');
    if (!modal) return;
    modal.classList.remove('open');
    modal.setAttribute('aria-hidden', 'true');
  }

  function loadStoresLedgerData() {
    var el = document.getElementById('st-stores-ledger-data');
    if (!el) return { summary: {}, rows: [] };
    try {
      var data = JSON.parse(el.textContent || '{}');
      if (!data || typeof data !== 'object') return { summary: {}, rows: [] };
      return {
        summary: data.summary || {},
        rows: Array.isArray(data.rows) ? data.rows : []
      };
    } catch (err) {
      return { summary: {}, rows: [] };
    }
  }

  function closeStoresLedgerModal() {
    var modal = document.getElementById('st-stores-ledger-modal');
    if (!modal) return;
    closeLedgerPendingModal();
    modal.classList.remove('open');
    modal.setAttribute('aria-hidden', 'true');
  }

  function getApprovalsModalOutlet() {
    var modalOutlet = document.getElementById('st-approvals-outlet');
    if (modalOutlet) {
      var fromModal = String(modalOutlet.value || '').trim();
      if (fromModal) return fromModal;
    }
    var pageOutlet = document.getElementById('st-outlet');
    if (pageOutlet) {
      var fromPage = String(pageOutlet.value || '').trim();
      if (fromPage) return fromPage;
    }
    try {
      return new URL(window.location.href).searchParams.get('outlet') || '';
    } catch (e) {
      return '';
    }
  }

  function approvalsModalUrl(baseUrl) {
    var url;
    try {
      url = new URL(baseUrl || '/stores/approvals', window.location.origin);
    } catch (err) {
      return '/stores/approvals';
    }
    var outlet = getApprovalsModalOutlet();
    if (outlet && outlet !== 'both') url.searchParams.set('outlet', outlet);
    else url.searchParams.delete('outlet');
    return url.pathname + url.search;
  }

  window.stApprovalsOutletChanged = function () {
    loadApprovalsModal(true);
  };

  function closeApprovalsModal() {
    var modal = document.getElementById('st-approvals-modal');
    if (!modal) return;
    closeRejectModal();
    modal.classList.remove('open');
    modal.setAttribute('aria-hidden', 'true');
  }

  function buildProductMasterEmbedUrl(url) {
    try {
      var parsed = new URL(url || '/stores/product-master', window.location.origin);
      if (parsed.origin !== window.location.origin) return url;
      parsed.searchParams.set('embed', '1');
      return parsed.pathname + parsed.search + parsed.hash;
    } catch (err) {
      var raw = String(url || '/stores/product-master');
      if (raw.indexOf('embed=1') !== -1) return raw;
      return raw + (raw.indexOf('?') === -1 ? '?' : '&') + 'embed=1';
    }
  }

  function productMasterOpenUrl() {
    var openBtn = document.getElementById('st-product-master-open')
      || document.getElementById('st-product-master-open-inline');
    return buildProductMasterEmbedUrl(
      (openBtn && openBtn.getAttribute('data-st-product-master-url')) || '/stores/product-master?embed=1'
    );
  }

  var productMasterCatalogDirty = false;

  function invalidateStoresProductCatalogCaches() {
    try {
      if (typeof window.deInvalidateSoftNavCacheByPath === 'function') {
        window.deInvalidateSoftNavCacheByPath('/stores/indent');
        window.deInvalidateSoftNavCacheByPath('/stores/inward');
        window.deInvalidateSoftNavCacheByPath('/stores/orders');
      }
    } catch (err) { /* ignore */ }
  }

  function buildProductCatalogRefreshUrl() {
    var outlet = '';
    try {
      var outletHidden = document.querySelector('#st-outlet-listbox input[type="hidden"]')
        || document.querySelector('.st-outlet-listbox input[type="hidden"]');
      if (outletHidden) outlet = String(outletHidden.value || '').trim();
    } catch (err) { /* ignore */ }
    if (!outlet) {
      try { outlet = new URL(window.location.href).searchParams.get('outlet') || ''; } catch (e2) {}
    }
    if (!outlet || outlet === 'both') return '';
    try {
      var cur = new URL(window.location.href);
      if (cur.pathname.indexOf('/stores/') === 0) {
        cur.searchParams.set('outlet', outlet);
        if (document.getElementById('st-indent-form')) cur.searchParams.set('focus', 'form');
        cur.searchParams.delete('partial');
        return cur.pathname + cur.search;
      }
    } catch (e3) { /* ignore */ }
    return '/stores/indent?outlet=' + encodeURIComponent(outlet) + '&focus=form';
  }

  function applyFreshProductOptions(srcHtml, dest) {
    if (!dest || !srcHtml) return;
    var selected = dest.querySelector('.is-selected');
    var selVal = selected ? (selected.getAttribute('data-value') || '') : '';
    dest.innerHTML = srcHtml;
    dest.querySelectorAll('.se-filter-listbox-option').forEach(function (opt) {
      var on = !!selVal && (opt.getAttribute('data-value') || '') === selVal;
      opt.classList.toggle('is-selected', on);
      opt.setAttribute('aria-selected', on ? 'true' : 'false');
    });
  }

  function refreshStoresProductPickers() {
    var url = buildProductCatalogRefreshUrl();
    if (!url) return;
    invalidateStoresProductCatalogCaches();
    var fetchUrl = url;
    try {
      var parsed = new URL(url, window.location.origin);
      parsed.searchParams.set('partial', 'main');
      fetchUrl = parsed.pathname + parsed.search;
    } catch (err) {
      fetchUrl = url + (url.indexOf('?') >= 0 ? '&' : '?') + 'partial=main';
    }
    fetch(fetchUrl, {
      credentials: 'same-origin',
      headers: { Accept: 'text/html', 'X-De-Partial': 'main' },
      cache: 'no-store'
    }).then(function (response) {
      if (!response.ok) throw new Error('catalog refresh failed');
      return response.text();
    }).then(function (html) {
      var doc = new DOMParser().parseFromString(html, 'text/html');
      var src = doc.querySelector('.st-product-listbox .ep-listbox-options');
      if (!src) return;
      var srcHtml = src.innerHTML;
      document.querySelectorAll('.st-product-listbox .ep-listbox-options').forEach(function (dest) {
        // Skip Product Master / other embeds that are not indent/inward lines.
        if (dest.closest('#st-product-master-modal, #md-master-modal')) return;
        applyFreshProductOptions(srcHtml, dest);
      });
      document.querySelectorAll('template').forEach(function (tpl) {
        applyFreshProductOptions(
          srcHtml,
          tpl.content.querySelector('.st-product-listbox .ep-listbox-options')
        );
      });
      document.querySelectorAll('.st-line').forEach(function (line) {
        if (line.closest('#st-product-master-modal, #md-master-modal')) return;
        var productSelected = line.querySelector('.st-product-listbox .se-filter-listbox-option.is-selected');
        if (!productSelected) return;
        var packLabel = line.querySelector('[data-st-pack-label]');
        var preferred = packLabel ? String(packLabel.value || '') : '';
        syncPackOptions(line, productSelected, preferred, { keepBaseWhenEmpty: true });
        syncUnitVisibility(line);
      });
    }).catch(function () { /* ignore */ });
  }
  window.refreshStoresProductPickers = refreshStoresProductPickers;

  function closeProductMasterModal() {
    var modal = document.getElementById('st-product-master-modal');
    if (!modal) return;
    modal.classList.remove('open');
    modal.setAttribute('aria-hidden', 'true');
    if (productMasterCatalogDirty) {
      productMasterCatalogDirty = false;
      refreshStoresProductPickers();
    }
  }
  window.closeProductMasterModal = closeProductMasterModal;

  function ensureProductMasterEmbedClose(inject) {
    if (!inject) return;
    var tools = inject.querySelector('.md-master-embed--page-shell .md-master-embed-header-actions');
    if (!tools || tools.querySelector('[data-st-pm-close]')) return;
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'md-master-modal-close pos-menu-embed-close';
    btn.setAttribute('data-st-pm-close', '1');
    btn.setAttribute('aria-label', 'Close Product Master');
    btn.innerHTML =
      '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>';
    btn.addEventListener('click', function (e) {
      e.preventDefault();
      closeProductMasterModal();
    });
    tools.appendChild(btn);
  }

  function bindProductMasterEmbedNav(inject) {
    if (!inject || inject.__stPmNavBound) return;
    inject.__stPmNavBound = true;
    inject.addEventListener('click', function (e) {
      var link = e.target && e.target.closest ? e.target.closest('a[href]') : null;
      if (!link || !inject.contains(link)) return;
      if (link.hasAttribute('download')) return;
      if (link.target && link.target !== '_self') return;
      if (link.hasAttribute('data-de-no-soft-nav') || link.hasAttribute('data-st-product-delete')) return;
      var href = link.getAttribute('href');
      if (!href || href.charAt(0) === '#') return;
      e.preventDefault();
      e.stopPropagation();
      loadProductMasterModal(true, href);
    });
  }

  function paintProductMasterModal(html) {
    var body = document.getElementById('st-product-master-modal-body');
    var inject = document.getElementById('st-product-master-modal-inject');
    var loading = document.getElementById('st-product-master-modal-loading');
    if (!body || !inject) return false;
    var doc = new DOMParser().parseFromString(html, 'text/html');
    var fragment = doc.querySelector('.md-master-embed')
      || doc.querySelector('.main-wrapper')
      || doc.body;
    if (!fragment) {
      inject.hidden = true;
      if (loading) {
        loading.hidden = false;
        loading.className = 'st-product-master-modal-error';
        loading.textContent = 'Could not load Product Master.';
      }
      return false;
    }
    inject.innerHTML = fragment === doc.body ? fragment.innerHTML : fragment.outerHTML;
    inject.querySelectorAll('script').forEach(function (oldScript) {
      var script = document.createElement('script');
      Array.prototype.slice.call(oldScript.attributes).forEach(function (attr) {
        script.setAttribute(attr.name, attr.value);
      });
      script.textContent = oldScript.textContent;
      oldScript.parentNode.replaceChild(script, oldScript);
    });
    // Keep POSTs inside this popup (embed forms use data-md-full-nav for Masters).
    inject.querySelectorAll('form[data-md-full-nav]').forEach(function (form) {
      form.removeAttribute('data-md-full-nav');
      form.setAttribute('data-st-pm-embed-form', '1');
    });
    if (loading) loading.hidden = true;
    inject.hidden = false;
    ensureProductMasterEmbedClose(inject);
    bindProductMasterEmbedNav(inject);
    try {
      if (typeof window.initEpListboxes === 'function') window.initEpListboxes();
    } catch (err) { /* ignore */ }
    try {
      if (typeof window.initStoresPage === 'function') window.initStoresPage();
    } catch (err) { /* ignore */ }
    var titleEl = document.getElementById('st-product-master-modal-title');
    var embedRoot = inject.querySelector('[data-md-modal-title]');
    if (titleEl && embedRoot) {
      var nextTitle = String(embedRoot.getAttribute('data-md-modal-title') || '').trim();
      if (nextTitle) titleEl.textContent = nextTitle;
    }
    return true;
  }

  function loadProductMasterModal(force, urlOverride) {
    var modal = document.getElementById('st-product-master-modal');
    var body = document.getElementById('st-product-master-modal-body');
    var inject = document.getElementById('st-product-master-modal-inject');
    var loading = document.getElementById('st-product-master-modal-loading');
    if (!modal || !body) return;
    var url = buildProductMasterEmbedUrl(urlOverride || productMasterOpenUrl());
    if (!force && body.getAttribute('data-st-loaded') === url && inject && !inject.hidden) return;
    body.setAttribute('data-st-loaded', '');
    if (inject) {
      inject.hidden = true;
      inject.innerHTML = '';
      inject.__stPmNavBound = false;
    }
    if (loading) {
      loading.hidden = false;
      loading.className = 'st-product-master-modal-loading';
      loading.textContent = 'Loading Product Master…';
    }
    fetch(url, {
      credentials: 'same-origin',
      headers: { Accept: 'text/html' },
      redirect: 'follow'
    }).then(function (response) {
      if (!response.ok) throw new Error('product master fetch failed');
      return response.text();
    }).then(function (html) {
      if (paintProductMasterModal(html)) body.setAttribute('data-st-loaded', url);
    }).catch(function () {
      if (inject) inject.hidden = true;
      if (loading) {
        loading.hidden = false;
        loading.className = 'st-product-master-modal-error';
        loading.innerHTML = 'Could not load Product Master. <a href="' +
          String(url).replace(/"/g, '&quot;') + '">Open full page</a>';
      }
    });
  }

  function openProductMasterModal() {
    var modal = document.getElementById('st-product-master-modal');
    if (!modal) return;
    mountModal(modal);
    modal.classList.add('open');
    modal.setAttribute('aria-hidden', 'false');
    loadProductMasterModal(true);
  }

  function submitProductMasterModalForm(form, submitter) {
    if (!form) return;
    var action = form.getAttribute('action') || productMasterOpenUrl();
    var method = (form.getAttribute('method') || 'post').toUpperCase();
    var body = null;
    if (method === 'GET') {
      try {
        var getUrl = new URL(action, window.location.origin);
        new FormData(form).forEach(function (value, key) {
          if (value != null && String(value) !== '') getUrl.searchParams.set(key, value);
        });
        loadProductMasterModal(true, getUrl.pathname + getUrl.search);
      } catch (err) {
        loadProductMasterModal(true, action);
      }
      return;
    }
    try {
      body = submitter ? new FormData(form, submitter) : new FormData(form);
    } catch (err) {
      body = new FormData(form);
    }
    if (submitter && submitter.name) {
      body.set(submitter.name, submitter.value != null ? String(submitter.value) : '');
    }
    if (!body.get('embed')) body.set('embed', '1');
    fetch(action, {
      method: method,
      body: body,
      credentials: 'same-origin',
      headers: { Accept: 'text/html' },
      redirect: 'follow'
    }).then(function (response) {
      if (!response.ok) throw new Error('product master action failed');
      return response.text();
    }).then(function (html) {
      paintProductMasterModal(html);
      productMasterCatalogDirty = true;
      var modalBody = document.getElementById('st-product-master-modal-body');
      if (modalBody) modalBody.setAttribute('data-st-loaded', productMasterOpenUrl());
    }).catch(function () {
      window.location.href = action;
    });
  }

  function extractApprovalsContent(html) {
    var parser = new DOMParser();
    var doc = parser.parseFromString(html, 'text/html');
    var content = doc.querySelector('.se-content');
    if (!content) return null;
    var wrap = document.createElement('div');
    Array.from(content.children).forEach(function (child) {
      wrap.appendChild(document.importNode(child, true));
    });
    return wrap;
  }

  function paintApprovalsModal(html) {
    var body = document.getElementById('st-approvals-modal-body');
    if (!body) return false;
    var wrap = extractApprovalsContent(html);
    if (!wrap) {
      body.innerHTML = '<div class="st-approvals-modal-error">Could not load approvals.</div>';
      return false;
    }
    // Drop nested reject dialog from the scroll body; openRejectModal remounts the live one.
    var nestedReject = wrap.querySelector('#st-reject-modal');
    if (nestedReject && nestedReject.parentNode) nestedReject.parentNode.removeChild(nestedReject);
    body.innerHTML = '';
    while (wrap.firstChild) body.appendChild(wrap.firstChild);
    // Ensure a single reject modal exists for Approve/Reject actions.
    if (nestedReject) {
      var host = modalHost();
      var existing = document.getElementById('st-reject-modal');
      if (existing && existing.parentNode) existing.parentNode.removeChild(existing);
      nestedReject.classList.remove('open');
      nestedReject.setAttribute('aria-hidden', 'true');
      if (host) host.appendChild(nestedReject);
      else document.body.appendChild(nestedReject);
    }
    body.querySelectorAll('table.pl-table').forEach(function (table) {
      initPlSortableTable(table);
    });
    applyApprovalsDefaultSort(document.getElementById('st-approvals-pending-table'));
    applyApprovalsRecentDefaultSort(document.getElementById('st-approvals-recent-table'));
    if (typeof window.initHbeTableScroll === 'function') window.initHbeTableScroll();
    initStFlashAutoDismiss();
    return true;
  }

  function loadApprovalsModal(force) {
    var modal = document.getElementById('st-approvals-modal');
    var body = document.getElementById('st-approvals-modal-body');
    var openBtn = document.getElementById('st-approvals-open');
    if (!modal || !body) return;
    var url = approvalsModalUrl(openBtn && openBtn.getAttribute('data-st-approvals-url'));
    if (!force && body.getAttribute('data-st-loaded') === url) return;
    body.setAttribute('data-st-loaded', '');
    body.innerHTML = '<div class="st-approvals-modal-loading" id="st-approvals-modal-loading">Loading approvals…</div>';
    fetch(url, {
      credentials: 'same-origin',
      headers: { Accept: 'text/html' },
      redirect: 'follow'
    }).then(function (response) {
      if (!response.ok) throw new Error('approvals fetch failed');
      return response.text();
    }).then(function (html) {
      if (paintApprovalsModal(html)) body.setAttribute('data-st-loaded', url);
    }).catch(function () {
      body.innerHTML = '<div class="st-approvals-modal-error">Could not load approvals. <a href="' +
        url.replace(/"/g, '&quot;') + '">Open full page</a></div>';
    });
  }

  function openApprovalsModal() {
    var modal = document.getElementById('st-approvals-modal');
    if (!modal) return;
    mountModal(modal);
    modal.classList.add('open');
    modal.setAttribute('aria-hidden', 'false');
    loadApprovalsModal(true);
  }

  function submitApprovalsModalForm(form, submitter) {
    if (!form) return;
    var action = form.getAttribute('action') || window.location.href;
    var method = (form.getAttribute('method') || 'post').toUpperCase();
    var body = null;
    if (method !== 'GET') {
      try {
        body = submitter ? new FormData(form, submitter) : new FormData(form);
      } catch (err) {
        body = new FormData(form);
      }
      // Named submit buttons (Approve / Reject) are omitted from FormData(form)
      // unless the submitter is passed — always attach decision explicitly.
      if (submitter && submitter.name) {
        body.set(submitter.name, submitter.value != null ? String(submitter.value) : '');
      }
      if (!body.get('decision') && form.getAttribute('data-st-decision')) {
        body.set('decision', form.getAttribute('data-st-decision'));
      }
    }
    if (form.id === 'st-reject-form') closeRejectModal();
    fetch(action, {
      method: method,
      body: body,
      credentials: 'same-origin',
      headers: { Accept: 'text/html' },
      redirect: 'follow'
    }).then(function (response) {
      if (!response.ok) throw new Error('approvals action failed');
      return response.text();
    }).then(function (html) {
      paintApprovalsModal(html);
      var openBtn = document.getElementById('st-approvals-open');
      var url = approvalsModalUrl(openBtn && openBtn.getAttribute('data-st-approvals-url'));
      var modalBody = document.getElementById('st-approvals-modal-body');
      if (modalBody) modalBody.setAttribute('data-st-loaded', url);
    }).catch(function () {
      window.location.href = action;
    });
  }

  function closeLedgerPendingModal() {
    var modal = document.getElementById('st-ledger-pending-modal');
    if (!modal) return;
    modal.classList.remove('open');
    modal.setAttribute('aria-hidden', 'true');
  }

  function findLedgerRowById(indentId) {
    var data = loadStoresLedgerData();
    var rows = data.rows || [];
    var key = String(indentId || '');
    for (var i = 0; i < rows.length; i += 1) {
      if (String(rows[i].id) === key) return rows[i];
    }
    return null;
  }

  function openLedgerPendingModal(indentId) {
    openLedgerDetailModal(indentId, 'pending');
  }

  function openLedgerReceivedModal(indentId) {
    openLedgerDetailModal(indentId, 'received');
  }

  function openLedgerDetailModal(indentId, mode) {
    var modal = document.getElementById('st-ledger-pending-modal');
    if (!modal) return;
    var row = findLedgerRowById(indentId);
    var isReceived = mode === 'received';
    if (!row) return;
    if (isReceived && !row.can_view_received) return;
    if (!isReceived && !row.can_view_pending) return;
    mountModal(modal);
    var lines = isReceived
      ? (Array.isArray(row.received_lines) ? row.received_lines : [])
      : (Array.isArray(row.pending_lines) ? row.pending_lines : []);
    var title = document.getElementById('st-ledger-pending-title');
    var sub = document.getElementById('st-ledger-pending-sub');
    var qtyLabel = modal.querySelector('.st-indent-view-stat-label[data-st-ledger-detail-qty-label]');
    if (title) title.textContent = isReceived ? 'Inward list' : 'Pending inward';
    if (qtyLabel) qtyLabel.textContent = isReceived ? 'Qty received' : 'Qty pending';
    if (sub) {
      var parts = [];
      if (row.indent_no) parts.push(row.indent_no);
      if (row.outlet_label) parts.push(row.outlet_label);
      sub.textContent = parts.length ? parts.join(' · ') : '';
    }
    var itemsStat = document.getElementById('st-ledger-pending-stat-items');
    var qtyStat = document.getElementById('st-ledger-pending-stat-qty');
    if (itemsStat) itemsStat.textContent = String(lines.length);
    if (qtyStat) {
      qtyStat.textContent = isReceived
        ? (row.qty_received_display || '0')
        : (row.qty_pending_display || '0');
    }

    var tbody = document.getElementById('st-ledger-pending-lines');
    var empty = document.getElementById('st-ledger-pending-empty');
    var tableWrap = modal.querySelector('.st-ledger-pending-body .st-indent-view-table-wrap');
    if (tbody) {
      tbody.innerHTML = lines.map(function (line) {
        return '<tr data-sort-row>'
          + '<td class="pl-name" data-sort-value="' + escapeHtml(line.item_name || '') + '">' + escapeHtml(line.item_name || '—') + '</td>'
          + '<td data-sort-value="' + escapeHtml(line.unit || '') + '">' + escapeHtml(line.unit || '—') + '</td>'
          + '<td class="pl-col-amount" data-sort-value="' + escapeHtml(String(line.qty_ordered != null ? line.qty_ordered : 0)) + '">' + escapeHtml(line.qty_ordered_display || '0') + '</td>'
          + '<td class="pl-col-amount" data-sort-value="' + escapeHtml(String(line.qty_received != null ? line.qty_received : 0)) + '">' + escapeHtml(line.qty_received_display || '0') + '</td>'
          + '<td class="pl-col-amount" data-sort-value="' + escapeHtml(String(line.qty_pending != null ? line.qty_pending : 0)) + '">' + escapeHtml(line.qty_pending_display || '0') + '</td>'
          + '</tr>';
      }).join('');
      if (empty) {
        empty.hidden = lines.length > 0;
        empty.textContent = isReceived
          ? 'No inwarded items for this indent.'
          : 'No pending items for this indent.';
      }
      if (tableWrap) tableWrap.hidden = lines.length === 0;
      var table = document.getElementById('st-ledger-pending-table') || tbody.closest('table');
      if (table && lines.length) initPlSortableTable(table);
    }

    var inwardLink = document.getElementById('st-ledger-pending-inward');
    if (inwardLink) {
      if (!isReceived && row.inward_url) {
        inwardLink.href = row.inward_url;
        inwardLink.hidden = false;
      } else {
        inwardLink.href = '#';
        inwardLink.hidden = true;
      }
    }

    modal.classList.add('open');
    modal.setAttribute('aria-hidden', 'false');
  }

  function getLedgerFilterOutlet() {
    var el = document.getElementById('st-ledger-outlet');
    return el ? String(el.value || 'both').toLowerCase() : 'both';
  }

  function getLedgerFilterStatus() {
    var el = document.getElementById('st-ledger-status');
    return el ? String(el.value || 'all').toLowerCase() : 'all';
  }

  function ledgerStatusMatches(rowStatus, filterStatus) {
    var status = String(rowStatus || '').toLowerCase();
    var key = String(filterStatus || 'all').toLowerCase();
    if (!key || key === 'all') return true;
    if (key === 'pending') return status === 'pending' || status === 'draft';
    return status === key;
  }

  function getLedgerFilterSearch() {
    var el = document.getElementById('st-ledger-search');
    return el ? String(el.value || '').trim().toLowerCase() : '';
  }

  function ledgerRowSearchBlob(row) {
    if (row && row.search_text) return String(row.search_text).toLowerCase();
    var itemNames = Array.isArray(row && row.item_names) ? row.item_names : [];
    return [
      row.indent_no,
      row.outlet_label,
      row.outlet,
      row.status_label,
      row.status,
      row.created_at,
      row.qty_ordered_display,
      row.qty_received_display,
      row.qty_pending_display
    ].concat(itemNames).map(function (part) {
      return String(part == null ? '' : part).toLowerCase();
    }).join(' ');
  }

  function filterLedgerRows(rows) {
    var outlet = getLedgerFilterOutlet();
    var status = getLedgerFilterStatus();
    var search = getLedgerFilterSearch();
    return (rows || []).filter(function (row) {
      var rowOutlet = String(row.outlet || '').toLowerCase();
      var outletOk = !outlet || outlet === 'both' || rowOutlet === outlet;
      if (!outletOk || !ledgerStatusMatches(row.status, status)) return false;
      if (!search) return true;
      return ledgerRowSearchBlob(row).indexOf(search) !== -1;
    });
  }

  function ledgerStatusRank(status) {
    var key = String(status || '').toLowerCase();
    if (key === 'approved') return 0;
    if (key === 'stocked') return 1;
    if (key === 'pending' || key === 'draft') return 2;
    if (key === 'rejected') return 3;
    return 9;
  }

  function sortLedgerRowsDefault(rows) {
    return (rows || []).slice().sort(function (a, b) {
      var rankDiff = ledgerStatusRank(a.status) - ledgerStatusRank(b.status);
      if (rankDiff !== 0) return rankDiff;
      return String(b.created_at || '').localeCompare(String(a.created_at || ''), undefined, {
        numeric: true,
        sensitivity: 'base'
      });
    });
  }

  function applyLedgerDefaultSort(table) {
    if (!table || typeof table.__stSortBy !== 'function') return;
    var statusTh = table.querySelector('th.pl-sortable[data-sort="status"]');
    if (statusTh) table.__stSortBy(statusTh, true);
  }

  function renderStoresLedgerTable(rows) {
    var modal = document.getElementById('st-stores-ledger-modal');
    var searchChip = document.getElementById('st-ledger-search-chip');
    var searchInput = document.getElementById('st-ledger-search');
    if (searchChip && searchInput) {
      searchChip.classList.toggle('is-active', !!String(searchInput.value || '').trim());
    }

    var tbody = document.getElementById('st-stores-ledger-lines');
    var empty = document.getElementById('st-stores-ledger-empty');
    var tableWrap = modal && modal.querySelector('.st-stores-ledger-body .st-indent-view-table-wrap');
    if (!tbody) return;
    var sortedRows = sortLedgerRowsDefault(rows || []);
    tbody.innerHTML = sortedRows.map(function (row) {
      var status = row.status || '';
      var statusLabel = row.status_label || status;
      var statusSort = String(ledgerStatusRank(status)).padStart(2, '0') + '|' + statusLabel;
      return '<tr data-sort-row>'
        + '<td class="pl-name" data-sort-value="' + escapeHtml(row.indent_no || '') + '">' + escapeHtml(row.indent_no || '—') + '</td>'
        + '<td data-sort-value="' + escapeHtml(row.outlet_label || row.outlet || '') + '">' + escapeHtml(row.outlet_label || row.outlet || '—') + '</td>'
        + '<td data-sort-value="' + escapeHtml(statusSort) + '"><span class="cp-status-pill cp-status-pill--' + escapeHtml(status || 'draft') + '">' + escapeHtml(statusLabel) + '</span></td>'
        + '<td data-sort-value="' + escapeHtml(row.created_at || '') + '">' + escapeHtml(row.created_at || '—') + '</td>'
        + '<td class="pl-col-amount" data-sort-value="' + escapeHtml(String(row.line_count != null ? row.line_count : 0)) + '">' + escapeHtml(String(row.line_count != null ? row.line_count : 0)) + '</td>'
        + '<td class="pl-col-amount" data-sort-value="' + escapeHtml(String(row.qty_ordered != null ? row.qty_ordered : 0)) + '">' + escapeHtml(row.qty_ordered_display || '0') + '</td>'
        + '<td class="pl-col-amount" data-sort-value="' + escapeHtml(String(row.qty_received != null ? row.qty_received : 0)) + '">'
        + (row.can_view_received
          ? '<button type="button" class="st-ledger-pending-btn" data-st-ledger-received="' + escapeHtml(String(row.id)) + '" title="View inward list">' + escapeHtml(row.qty_received_display || '0') + '</button>'
          : escapeHtml(row.qty_received_display || '0'))
        + '</td>'
        + '<td class="pl-col-amount" data-sort-value="' + escapeHtml(String(row.qty_pending != null ? row.qty_pending : 0)) + '">'
        + (row.can_view_pending
          ? '<button type="button" class="st-ledger-pending-btn" data-st-ledger-pending="' + escapeHtml(String(row.id)) + '" title="View pending inward items">' + escapeHtml(row.qty_pending_display || '0') + '</button>'
          : escapeHtml(row.qty_pending_display || '0'))
        + '</td>'
        + '</tr>';
    }).join('');
    if (empty) {
      empty.hidden = sortedRows.length > 0;
      empty.textContent = getLedgerFilterSearch()
        ? 'No indents match your search.'
        : 'No indents found for this outlet.';
    }
    if (tableWrap) tableWrap.hidden = sortedRows.length === 0;
    var table = document.getElementById('st-stores-ledger-table') || tbody.closest('table');
    if (table && sortedRows.length) {
      initPlSortableTable(table);
      applyLedgerDefaultSort(table);
    }
  }

  function refreshStoresLedgerView() {
    var data = loadStoresLedgerData();
    renderStoresLedgerTable(filterLedgerRows(data.rows || []));
  }

  function openStoresLedgerModal() {
    var modal = document.getElementById('st-stores-ledger-modal');
    if (!modal) return;
    mountModal(modal);
    refreshStoresLedgerView();
    modal.classList.add('open');
    modal.setAttribute('aria-hidden', 'false');
  }

  window.stLedgerFilterChanged = function () {
    refreshStoresLedgerView();
  };

  function filterEditProductOptions(list, outlet) {
    if (!list) return;
    var key = String(outlet || '').toLowerCase();
    list.querySelectorAll('.st-product-listbox .se-filter-listbox-option').forEach(function (opt) {
      var po = String(opt.getAttribute('data-outlet') || 'both').toLowerCase();
      var show = !key || po === 'both' || po === key;
      opt.hidden = !show;
      if (!show) {
        opt.classList.remove('is-selected');
        opt.setAttribute('aria-selected', 'false');
      }
    });
  }

  function fillEditLine(line, lineData, outlet) {
    if (!line) return;
    filterEditProductOptions(line, outlet);
    var name = (lineData && lineData.item_name) || '';
    var unit = (lineData && lineData.unit) || 'kg';
    var productRoot = line.querySelector('.st-product-listbox');
    var productHidden = productRoot && productRoot.querySelector('input[type="hidden"]');
    if (productHidden && typeof window.resetEpListbox === 'function') {
      window.resetEpListbox(productHidden.id, name, name || 'Select Product');
    } else if (productHidden) {
      productHidden.value = name;
      var combo = productRoot.querySelector('input.se-filter-chip-combobox, input.se-filter-chip-trigger');
      if (combo) {
        combo.value = name || '';
        combo.classList.toggle('is-placeholder', !name);
      }
      var valueEl = productRoot.querySelector('.se-filter-chip-value');
      if (valueEl) {
        valueEl.textContent = name || 'Select Product';
        valueEl.classList.toggle('is-placeholder', !name);
      }
    }
    setUnitListbox(line, unit);
    var qty = line.querySelector('input[name="quantity"]');
    if (qty) qty.value = lineData && lineData.quantity != null ? String(lineData.quantity) : '';
    var price = '';
    if (lineData) {
      if (lineData.approximate_price_display != null && lineData.approximate_price_display !== '') {
        price = lineData.approximate_price_display;
      } else if (lineData.approximate_price != null && lineData.approximate_price !== '') {
        price = String(lineData.approximate_price);
      }
    }
    setApproxPrice(line, price);
    var productSelected = productRoot && productRoot.querySelector('.se-filter-listbox-option.is-selected');
    if (!productSelected && productRoot && name) {
      productSelected = Array.prototype.find.call(
        productRoot.querySelectorAll('.se-filter-listbox-option'),
        function (opt) { return (opt.getAttribute('data-value') || '') === name; }
      );
      if (productSelected) {
        productSelected.classList.add('is-selected');
        productSelected.setAttribute('aria-selected', 'true');
      }
    }
    syncPackOptions(line, productSelected, (lineData && lineData.pack_label) || '');
    syncUnitVisibility(line);
  }

  function openIndentEditModal(indentId) {
    var modal = document.getElementById('st-indent-edit-modal');
    var form = document.getElementById('st-indent-edit-form');
    var data = loadIndentViewMap()[String(indentId)];
    if (!modal || !form || !data || !data.can_mutate) return;

    closeIndentViewModal();
    mountModal(modal);

    var title = document.getElementById('st-indent-edit-title');
    var sub = document.getElementById('st-indent-edit-sub');
    var outletInput = document.getElementById('st-indent-edit-outlet');
    var idInput = document.getElementById('st-indent-edit-id');
    var outletLabel = document.getElementById('st-indent-edit-outlet-label');
    var notes = document.getElementById('st-indent-edit-notes');
    var list = document.getElementById('st-indent-edit-lines');

    if (title) title.textContent = 'Edit indent';
    if (sub) {
      var bits = [data.indent_no || ''];
      if (data.status_label) bits.push(data.status_label);
      sub.textContent = bits.filter(Boolean).join(' · ');
    }
    if (outletInput) outletInput.value = data.outlet || '';
    if (idInput) idInput.value = String(data.id || '');
    form.setAttribute('data-st-editing-id', String(data.id || ''));
    if (outletLabel) outletLabel.textContent = data.outlet_label || data.outlet || '—';
    if (notes) notes.value = data.notes || '';

    try {
      var url = new URL(form.getAttribute('action') || window.location.pathname, window.location.origin);
      url.searchParams.set('outlet', data.outlet || '');
      // Keep edit id on the action URL so soft-submit cannot drop it.
      if (data.id != null && data.id !== '') url.searchParams.set('edit', String(data.id));
      else url.searchParams.delete('edit');
      form.setAttribute('action', url.pathname + url.search);
    } catch (e) {
      var oid = encodeURIComponent(data.outlet || '');
      var eid = data.id != null && data.id !== '' ? '&edit=' + encodeURIComponent(String(data.id)) : '';
      form.setAttribute('action', '/stores/indent?outlet=' + oid + eid);
    }

    if (list) {
      list.innerHTML = '';
      var lines = Array.isArray(data.lines) ? data.lines.slice() : [];
      if (!lines.length) lines.push({ item_name: '', quantity: '', unit: 'kg', approximate_price: '' });
      lines.forEach(function (lineData) {
        var row = appendEmptyLine(list);
        fillEditLine(row, lineData, data.outlet);
      });
      ensureTrailingEmptyLine(list);
      list.querySelectorAll('.st-line').forEach(function (row) {
        filterEditProductOptions(row, data.outlet);
      });
    }

    syncNotesCounter();
    syncIndentLineTotals(modal);
    modal.classList.add('open');
    modal.setAttribute('aria-hidden', 'false');
  }

  function openIndentViewModal(indentId) {
    var modal = document.getElementById('st-indent-view-modal');
    var data = loadIndentViewMap()[String(indentId)];
    if (!modal || !data) return;

    mountModal(modal);

    var title = document.getElementById('st-indent-view-title');
    var notes = document.getElementById('st-indent-view-notes');
    var decision = document.getElementById('st-indent-view-decision');
    var tbody = document.getElementById('st-indent-view-lines');
    var empty = document.getElementById('st-indent-view-empty');
    var editBtn = document.getElementById('st-indent-view-edit');
    var poBtn = document.getElementById('st-indent-view-po');

    if (title) title.textContent = data.indent_no || 'Indent';
    if (notes) {
      if (data.notes) {
        notes.hidden = false;
        notes.textContent = data.notes;
      } else {
        notes.hidden = true;
        notes.textContent = '';
      }
    }
    if (decision) {
      if (data.decision_note) {
        decision.hidden = false;
        decision.textContent = 'Decision note: ' + data.decision_note;
      } else {
        decision.hidden = true;
        decision.textContent = '';
      }
    }
    if (tbody) {
      var lines = Array.isArray(data.lines) ? data.lines.slice() : [];
      var approvedQtySum = 0;
      var approvedAmountSum = 0;
      tbody.innerHTML = lines.map(function (line) {
        var qty = parseFloat(line.quantity);
        if (!isFinite(qty)) qty = 0;
        var unitPrice = null;
        if (line.approximate_price_display != null && line.approximate_price_display !== '') {
          unitPrice = parseFloat(line.approximate_price_display);
        } else if (line.approximate_price != null && line.approximate_price !== '') {
          unitPrice = parseFloat(line.approximate_price);
        }
        if (!isFinite(unitPrice) || unitPrice <= 0) unitPrice = 0;
        if (qty > 0) approvedQtySum += qty;
        if (qty > 0 && unitPrice > 0) {
          approvedAmountSum += Math.round(qty * unitPrice * 100) / 100;
        }
        var priceText = unitPrice > 0
          ? ('₹' + (line.approximate_price_display || line.approximate_price))
          : '—';
        var lineTotal = (qty > 0 && unitPrice > 0) ? Math.round(qty * unitPrice * 100) / 100 : 0;
        var totalText = lineTotal > 0
          ? (typeof window.formatINR === 'function'
            ? window.formatINR(lineTotal, 2)
            : ('₹' + lineTotal.toLocaleString('en-IN', { minimumFractionDigits: 0, maximumFractionDigits: 2 })))
          : '—';
        var itemName = line.display_name || line.item_name || '';
        var unit = line.unit || line.display_unit || '';
        return '<tr data-sort-row>'
          + '<td class="pl-name" data-sort-value="' + escapeHtml(itemName) + '">' + escapeHtml(itemName) + '</td>'
          + '<td class="pl-col-amount" data-sort-value="' + escapeHtml(String(qty)) + '">' + escapeHtml(line.quantity) + '</td>'
          + '<td data-sort-value="' + escapeHtml(unit) + '">' + escapeHtml(unit) + '</td>'
          + '<td class="pl-col-amount pl-amount" data-sort-value="' + escapeHtml(String(unitPrice || '')) + '">' + escapeHtml(priceText) + '</td>'
          + '<td class="pl-col-amount pl-amount" data-sort-value="' + escapeHtml(String(lineTotal || '')) + '">' + escapeHtml(totalText) + '</td>'
          + '</tr>';
      }).join('');
      if (empty) empty.hidden = lines.length > 0;
      var qtyStat = document.getElementById('st-indent-view-approved-qty');
      var amountStat = document.getElementById('st-indent-view-approved-amount');
      if (qtyStat) {
        qtyStat.textContent = formatInwardQty(approvedQtySum);
      }
      if (amountStat) {
        amountStat.textContent = approvedAmountSum > 0
          ? (typeof window.formatINR === 'function'
            ? window.formatINR(approvedAmountSum, 2)
            : ('₹' + approvedAmountSum.toLocaleString('en-IN', { minimumFractionDigits: 0, maximumFractionDigits: 2 })))
          : '—';
      }
      var viewTable = document.getElementById('st-indent-view-table') || tbody.closest('table');
      if (viewTable) {
        initPlSortableTable(viewTable);
        applyIndentViewDefaultSort(viewTable);
      }
    }
    if (editBtn) {
      if (data.can_mutate) {
        editBtn.hidden = false;
        editBtn.removeAttribute('hidden');
        editBtn.setAttribute('data-st-edit-indent', String(data.id));
      } else {
        editBtn.hidden = true;
        editBtn.setAttribute('hidden', '');
        editBtn.removeAttribute('data-st-edit-indent');
      }
    }
    if (poBtn) {
      if (data.can_download_po && data.po_url) {
        poBtn.hidden = false;
        poBtn.removeAttribute('hidden');
        poBtn.setAttribute('href', data.po_url);
      } else {
        poBtn.hidden = true;
        poBtn.setAttribute('hidden', '');
        poBtn.setAttribute('href', '#');
      }
    }

    modal.classList.add('open');
    modal.setAttribute('aria-hidden', 'false');
  }

  function eventElement(event) {
    var target = event && event.target;
    if (!target) return null;
    if (target.nodeType === 3) target = target.parentElement;
    if (target && target.correspondingUseElement) target = target.correspondingUseElement;
    if (target && !target.closest && target.parentElement) target = target.parentElement;
    return target && typeof target.closest === 'function' ? target : null;
  }

  function closeRejectModal() {
    var modal = document.getElementById('st-reject-modal');
    if (!modal) return;
    modal.classList.remove('open');
    modal.setAttribute('aria-hidden', 'true');
    var note = document.getElementById('st-reject-note');
    if (note) note.value = '';
  }

  function openRejectModal(btn) {
    var modal = document.getElementById('st-reject-modal');
    var form = document.getElementById('st-reject-form');
    if (!modal || !form || !btn) return;
    mountModal(modal);
    form.setAttribute('action', btn.getAttribute('data-st-reject-action') || '#');
    var outlet = document.getElementById('st-reject-outlet');
    if (outlet) outlet.value = btn.getAttribute('data-st-reject-outlet') || '';
    var noEl = document.getElementById('st-reject-indent-no');
    if (noEl) noEl.textContent = btn.getAttribute('data-st-reject-no') || 'indent';
    var note = document.getElementById('st-reject-note');
    if (note) note.value = '';
    modal.classList.add('open');
    modal.setAttribute('aria-hidden', 'false');
    if (note) {
      try { note.focus(); } catch (err) {}
    }
  }

  function onStoresClick(event) {
    var target = eventElement(event);
    if (!target) return;

    var rejectOpen = target.closest('[data-st-reject-open]');
    if (rejectOpen) {
      event.preventDefault();
      openRejectModal(rejectOpen);
      return;
    }
    if (target.closest('#st-reject-close, #st-reject-cancel')) {
      event.preventDefault();
      closeRejectModal();
      return;
    }
    var rejectModal = document.getElementById('st-reject-modal');
    if (rejectModal && rejectModal.classList.contains('open') && event.target === rejectModal) {
      closeRejectModal();
      return;
    }

    if (target.closest('#st-stores-ledger-open')) {
      event.preventDefault();
      openStoresLedgerModal();
      return;
    }
    if (target.closest('#st-approvals-open')) {
      event.preventDefault();
      openApprovalsModal();
      return;
    }
    if (target.closest('#st-product-master-open, #st-product-master-open-inline')) {
      event.preventDefault();
      openProductMasterModal();
      return;
    }
    if (target.closest('#st-product-master-close, [data-st-pm-close]')) {
      event.preventDefault();
      closeProductMasterModal();
      return;
    }
    if (target.closest('#st-approvals-close, #st-approvals-dismiss')) {
      event.preventDefault();
      closeApprovalsModal();
      return;
    }
    var pendingBtn = target.closest('[data-st-ledger-pending]');
    if (pendingBtn) {
      event.preventDefault();
      openLedgerPendingModal(pendingBtn.getAttribute('data-st-ledger-pending'));
      return;
    }
    var receivedBtn = target.closest('[data-st-ledger-received]');
    if (receivedBtn) {
      event.preventDefault();
      openLedgerReceivedModal(receivedBtn.getAttribute('data-st-ledger-received'));
      return;
    }
    if (target.closest('#st-ledger-pending-close, #st-ledger-pending-dismiss')) {
      event.preventDefault();
      closeLedgerPendingModal();
      return;
    }
    if (target.closest('#st-stores-ledger-close, #st-stores-ledger-dismiss')) {
      event.preventDefault();
      closeStoresLedgerModal();
      return;
    }
    var editBtn = target.closest('[data-st-edit-indent]');
    if (editBtn) {
      event.preventDefault();
      openIndentEditModal(editBtn.getAttribute('data-st-edit-indent'));
      return;
    }
    var viewBtn = target.closest('[data-st-view-indent]');
    if (viewBtn) {
      event.preventDefault();
      openIndentViewModal(viewBtn.getAttribute('data-st-view-indent'));
      return;
    }
    if (target.closest('#st-indent-view-close')) {
      event.preventDefault();
      closeIndentViewModal();
      return;
    }
    if (target.closest('#st-indent-edit-close')) {
      event.preventDefault();
      closeIndentEditModal();
      return;
    }
    var ledgerPendingModal = document.getElementById('st-ledger-pending-modal');
    if (ledgerPendingModal && ledgerPendingModal.classList.contains('open') && event.target === ledgerPendingModal) {
      closeLedgerPendingModal();
      return;
    }
    var productMasterModal = document.getElementById('st-product-master-modal');
    if (productMasterModal && productMasterModal.classList.contains('open') && event.target === productMasterModal) {
      closeProductMasterModal();
      return;
    }
    var approvalsModal = document.getElementById('st-approvals-modal');
    if (approvalsModal && approvalsModal.classList.contains('open') && event.target === approvalsModal) {
      closeApprovalsModal();
      return;
    }
    var ledgerModal = document.getElementById('st-stores-ledger-modal');
    if (ledgerModal && ledgerModal.classList.contains('open') && event.target === ledgerModal) {
      closeStoresLedgerModal();
      return;
    }
    var viewModal = document.getElementById('st-indent-view-modal');
    if (viewModal && viewModal.classList.contains('open') && event.target === viewModal) {
      closeIndentViewModal();
      return;
    }
    var editModal = document.getElementById('st-indent-edit-modal');
    if (editModal && editModal.classList.contains('open') && event.target === editModal) {
      closeIndentEditModal();
      return;
    }
    var addBtn = target.closest('[data-st-add-line]');
    if (addBtn) {
      event.preventDefault();
      addLine(addBtn);
      return;
    }
    var removeBtn = target.closest('[data-st-remove-line]');
    if (removeBtn) {
      event.preventDefault();
      removeLine(removeBtn);
      return;
    }
  }

  function onStoresKeydown(event) {
    if (event.key !== 'Escape') return;
    var rejectModal = document.getElementById('st-reject-modal');
    if (rejectModal && rejectModal.classList.contains('open')) {
      closeRejectModal();
      return;
    }
    var ledgerPendingModal = document.getElementById('st-ledger-pending-modal');
    if (ledgerPendingModal && ledgerPendingModal.classList.contains('open')) {
      closeLedgerPendingModal();
      return;
    }
    var productMasterModal = document.getElementById('st-product-master-modal');
    if (productMasterModal && productMasterModal.classList.contains('open')) {
      var nestedProduct = document.getElementById('st-product-modal');
      var nestedCategory = document.getElementById('st-category-modal');
      var nestedUnit = document.getElementById('st-unit-modal');
      if (
        (nestedProduct && nestedProduct.classList.contains('active'))
        || (nestedCategory && nestedCategory.classList.contains('active'))
        || (nestedUnit && nestedUnit.classList.contains('active'))
      ) {
        return;
      }
      closeProductMasterModal();
      return;
    }
    var approvalsModal = document.getElementById('st-approvals-modal');
    if (approvalsModal && approvalsModal.classList.contains('open')) {
      closeApprovalsModal();
      return;
    }
    var ledgerModal = document.getElementById('st-stores-ledger-modal');
    if (ledgerModal && ledgerModal.classList.contains('open')) {
      closeStoresLedgerModal();
      return;
    }
    var editModal = document.getElementById('st-indent-edit-modal');
    if (editModal && editModal.classList.contains('open')) {
      closeIndentEditModal();
      return;
    }
    var modal = document.getElementById('st-indent-view-modal');
    if (modal && modal.classList.contains('open')) closeIndentViewModal();
  }

  function onStoresInput(event) {
    var target = event.target;
    if (!target) return;
    if (target.id === 'st-ledger-search') {
      refreshStoresLedgerView();
      return;
    }
    if (target.matches('[data-st-notes-counter]')) syncNotesCounter();
    if (
      target.matches('input[name="quantity"]')
      || target.matches('[data-st-approx-price]')
      || target.matches('input[name="approximate_price"]')
    ) {
      var wrap = target.closest('.st-lines-wrap');
      if (wrap) syncIndentLineTotals(wrap);
      else syncIndentSendButtons(target.closest('form'));
    }
  }

  function syncEditFormIndentId(form) {
    if (!form) return '';
    var idInput = form.querySelector('#st-indent-edit-id, input[name="indent_id"]');
    var editingId = form.getAttribute('data-st-editing-id') || '';
    if (idInput) {
      if (!String(idInput.value || '').trim() && editingId) idInput.value = editingId;
      return String(idInput.value || '').trim();
    }
    return String(editingId || '').trim();
  }

  function onStoresSubmit(event) {
    var form = event.target;
    if (!form) return;
    var productMasterModal = document.getElementById('st-product-master-modal');
    if (
      productMasterModal
      && productMasterModal.classList.contains('open')
      && productMasterModal.contains(form)
    ) {
      event.preventDefault();
      event.stopPropagation();
      submitProductMasterModalForm(form, event.submitter || null);
      return;
    }
    var approvalsModal = document.getElementById('st-approvals-modal');
    if (
      approvalsModal
      && approvalsModal.classList.contains('open')
      && (approvalsModal.contains(form) || form.id === 'st-reject-form')
    ) {
      event.preventDefault();
      event.stopPropagation();
      submitApprovalsModalForm(form, event.submitter || null);
      return;
    }
    if (form.id !== 'st-indent-edit-form') return;
    var indentId = syncEditFormIndentId(form);
    if (!indentId) {
      event.preventDefault();
      event.stopPropagation();
      window.alert('Could not save — missing indent id. Close and open Edit again.');
      return;
    }
    // Edit modal bypasses soft-nav submit locks — disable to prevent double WhatsApp notify.
    if (form.getAttribute('data-st-submit-lock') === '1') {
      event.preventDefault();
      event.stopPropagation();
      return;
    }
    form.setAttribute('data-st-submit-lock', '1');
    var controls = form.querySelectorAll('button[type="submit"], input[type="submit"]');
    for (var i = 0; i < controls.length; i++) {
      controls[i].disabled = true;
    }
  }

  function bindStoresEvents() {
    if (window.__stStoresEventsBound) return;
    window.__stStoresEventsBound = true;
    document.addEventListener('click', onStoresClick);
    document.addEventListener('click', onInwardClick);
    document.addEventListener('change', onInwardChange);
    document.addEventListener('keydown', onStoresKeydown);
    document.addEventListener('input', onStoresInput);
    document.addEventListener('input', onInwardInput);
    document.addEventListener('focusin', onInwardBulkTaxFocus);
    document.addEventListener('focusout', onInwardBulkTaxFocus);
    document.addEventListener('submit', onStoresSubmit, true);
  }

  function bootIndentModals() {
    syncNotesCounter();
    var editModal = document.getElementById('st-indent-edit-modal');
    var openId = editModal && editModal.getAttribute('data-st-open-edit');
    if (openId) openIndentEditModal(openId);
  }

  function initPlSortableTable(table) {
    if (!table) return;
    /* Product master uses pack-aware sort + pagination in initProductMasterSearch. */
    if (table.id === 'st-products-table') return;
    var tbody = table.tBodies[0];
    if (!tbody) return;
    var headers = Array.from(table.querySelectorAll('th.pl-sortable'));
    if (!headers.length) return;

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

    function sortBy(th, forceAscending) {
      var key = th.getAttribute('data-sort') || '';
      var type = th.getAttribute('data-sort-type') || 'text';
      var colIndex = Array.from(th.parentNode.children).indexOf(th);
      if (colIndex < 0) return;

      var state = table.__stSortState || { activeKey: '', ascending: true };
      if (forceAscending === true) {
        state.activeKey = key;
        state.ascending = true;
      } else if (forceAscending === false) {
        state.activeKey = key;
        state.ascending = false;
      } else if (state.activeKey === key) {
        state.ascending = !state.ascending;
      } else {
        state.activeKey = key;
        state.ascending = true;
      }
      table.__stSortState = state;

      var rows = Array.from(tbody.querySelectorAll('tr[data-sort-row]'));
      rows.sort(function (a, b) {
        var av = cellSortValue(a, colIndex, type);
        var bv = cellSortValue(b, colIndex, type);
        var cmp = 0;
        if (type === 'number') cmp = av - bv;
        else cmp = String(av).localeCompare(String(bv), undefined, { numeric: true, sensitivity: 'base' });
        return state.ascending ? cmp : -cmp;
      });
      rows.forEach(function (row) { tbody.appendChild(row); });

      headers.forEach(function (header) {
        header.classList.remove('is-sorted-asc', 'is-sorted-desc');
        header.setAttribute('aria-sort', 'none');
      });
      th.classList.add(state.ascending ? 'is-sorted-asc' : 'is-sorted-desc');
      th.setAttribute('aria-sort', state.ascending ? 'ascending' : 'descending');
    }

    table.__stSortBy = sortBy;

    if (table.getAttribute('data-st-sort-bound') === '1') return;
    table.setAttribute('data-st-sort-bound', '1');

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

  function applyIndentViewDefaultSort(table) {
    if (!table || typeof table.__stSortBy !== 'function') return;
    var itemTh = table.querySelector('th.pl-sortable[data-sort="item"]');
    if (itemTh) table.__stSortBy(itemTh, true);
  }

  function applyStockDefaultSort(table) {
    if (!table || typeof table.__stSortBy !== 'function') return;
    var productTh = table.querySelector('th.pl-sortable[data-sort="product"]');
    if (productTh) table.__stSortBy(productTh, true);
  }

  function applyMovementsDefaultSort(table) {
    if (!table || typeof table.__stSortBy !== 'function') return;
    var whenTh = table.querySelector('th.pl-sortable[data-sort="when"]');
    if (whenTh) table.__stSortBy(whenTh, false);
  }

  function applyApprovalsDefaultSort(table) {
    if (!table || typeof table.__stSortBy !== 'function') return;
    var submittedTh = table.querySelector('th.pl-sortable[data-sort="submitted"]');
    if (submittedTh) table.__stSortBy(submittedTh, false);
  }

  function applyApprovalsRecentDefaultSort(table) {
    if (!table || typeof table.__stSortBy !== 'function') return;
    var whenTh = table.querySelector('th.pl-sortable[data-sort="when"]');
    if (whenTh) table.__stSortBy(whenTh, false);
  }

  function initStoresSortableTables() {
    document.querySelectorAll('table.pl-table').forEach(function (table) {
      /* Weekly Stock Audit owns sort + KPI reorder in stores_stock_audit.js */
      if (table.classList.contains('st-audit-queue-table')) return;
      initPlSortableTable(table);
    });
    applyStockDefaultSort(document.getElementById('st-stock-table'));
    applyMovementsDefaultSort(document.getElementById('st-stock-movements-table'));
    applyApprovalsDefaultSort(document.getElementById('st-approvals-pending-table'));
    applyApprovalsRecentDefaultSort(document.getElementById('st-approvals-recent-table'));
    if (typeof window.initHbeTableScroll === 'function') window.initHbeTableScroll();
  }

  function parseInwardQty(value) {
    var n = parseFloat(value);
    return isNaN(n) ? 0 : n;
  }

  function clampInwardQty(input) {
    if (!input) return 0;
    var row = input.closest('[data-st-inward-row]');
    var ordered = row ? parseInwardQty(row.getAttribute('data-ordered')) : 0;
    var qty = parseInwardQty(input.value);
    if (qty < 0) qty = 0;
    if (ordered > 0 && qty > ordered) qty = ordered;
    // Keep integers when ordered is integer; otherwise round to 3 decimals.
    if (Math.abs(qty - Math.round(qty)) < 0.0001) qty = Math.round(qty);
    else qty = Math.round(qty * 1000) / 1000;
    input.value = String(qty);
    return qty;
  }

  function formatInwardQty(n) {
    if (!isFinite(n)) return '0';
    if (Math.abs(n - Math.round(n)) < 0.0001) return String(Math.round(n));
    return String(Math.round(n * 1000) / 1000);
  }

  function applyInwardOrderedDefaults() {
    var form = document.getElementById('st-inward-form');
    if (!form) return;
    form.querySelectorAll('[data-st-inward-row]').forEach(function (row) {
      var check = row.querySelector('.st-inward-row-check');
      var qty = row.querySelector('[data-st-inward-qty]');
      if (!check || !check.checked || !qty) return;
      var ordered = parseInwardQty(row.getAttribute('data-ordered'));
      if (ordered <= 0) return;
      var formatted = formatInwardQty(ordered);
      qty.value = formatted;
      qty.defaultValue = formatted;
      qty.setAttribute('value', formatted);
      qty.setAttribute('max', formatted);
    });
  }

  function formatInwardMoney(amount) {
    var n = Number(amount || 0);
    if (!isFinite(n) || n <= 0) return '—';
    n = Math.round(n);
    if (typeof window.formatINR === 'function') return window.formatINR(n, 0);
    return '₹' + n.toLocaleString('en-IN', { minimumFractionDigits: 0, maximumFractionDigits: 0 });
  }

  function inwardLineTotal(qty, price, taxPercent) {
    if (!(qty > 0 && price > 0)) return 0;
    var tax = Number(taxPercent);
    if (!isFinite(tax) || tax < 0) tax = 0;
    var base = qty * price;
    return Math.round(base * (1 + tax / 100) * 100) / 100;
  }

  function syncInwardLineTotals() {
    var form = document.getElementById('st-inward-form');
    if (!form) return;
    var grand = 0;
    var qtySum = 0;
    var approvedQtySum = 0;
    var approvedAmountSum = 0;
    var selectedApprovedAmountSum = 0;
    form.querySelectorAll('[data-st-inward-row]').forEach(function (row) {
      var check = row.querySelector('.st-inward-row-check');
      var qtyInput = row.querySelector('[data-st-inward-qty]');
      var priceInput = row.querySelector('[data-st-inward-price]');
      var taxInput = row.querySelector('[data-st-inward-tax]');
      var totalEl = row.querySelector('[data-st-inward-line-total]');
      var selected = !!(check && check.checked);
      var qty = selected && qtyInput ? parseInwardQty(qtyInput.value) : 0;
      var price = selected && priceInput ? parseInwardQty(priceInput.value) : 0;
      var tax = selected && taxInput ? parseInwardQty(taxInput.value) : 0;
      var lineTotal = inwardLineTotal(qty, price, tax);
      var approvedQty = parseInwardQty(row.getAttribute('data-ordered'));
      var approvedRate = parseInwardQty(row.getAttribute('data-rate'));
      if (approvedQty > 0) approvedQtySum += approvedQty;
      if (approvedQty > 0 && approvedRate > 0) {
        approvedAmountSum += Math.round(approvedQty * approvedRate * 100) / 100;
      }
      if (selected && qty > 0 && approvedRate > 0) {
        selectedApprovedAmountSum += Math.round(qty * approvedRate * 100) / 100;
      }
      if (totalEl) {
        totalEl.textContent = lineTotal > 0 ? formatInwardMoney(lineTotal) : '';
        totalEl.classList.toggle('is-empty', lineTotal <= 0);
      }
      var totalCard = row.querySelector('.st-inward-total-card');
      if (totalCard) {
        // Over when entered unit price exceeds approved rate, or line total
        // (qty × price + tax) exceeds approved amount for the inward qty.
        var approvedLineAmount = (qty > 0 && approvedRate > 0)
          ? Math.round(qty * approvedRate * 100) / 100
          : 0;
        var overApproved = selected && (
          (price > 0 && approvedRate > 0 && price > approvedRate + 0.0001) ||
          (lineTotal > 0 && approvedLineAmount > 0 && lineTotal > approvedLineAmount + 0.005)
        );
        totalCard.classList.toggle('is-over-approved', overApproved);
      }
      var approvedPriceMeta = row.querySelector('[data-st-inward-approved-price]');
      if (approvedPriceMeta) {
        var showApprovedPrice = selected && price > 0 && approvedRate > 0 && price > approvedRate + 0.0001;
        approvedPriceMeta.hidden = !showApprovedPrice;
      }
      if (selected && qty > 0) qtySum += qty;
      grand += lineTotal;
    });
    var grandEl = form.querySelector('[data-st-inward-grand-total]');
    if (grandEl) grandEl.textContent = grand > 0 ? formatInwardMoney(grand) : '—';
    var grandCard = form.querySelector('.st-inward-summary-total');
    if (grandCard) {
      var overGrand = grand > 0 && selectedApprovedAmountSum > 0
        && grand > selectedApprovedAmountSum + 0.005;
      grandCard.classList.toggle('is-over-approved', overGrand);
    }

    var approvedEl = form.querySelector('[data-st-inward-stat-approved-qty]');
    if (approvedEl) approvedEl.textContent = formatInwardQty(approvedQtySum);
    var approvedAmountEl = form.querySelector('[data-st-inward-stat-approved-amount]');
    if (approvedAmountEl) {
      approvedAmountEl.textContent = approvedAmountSum > 0
        ? formatInwardMoney(approvedAmountSum)
        : '—';
    }
    var qtyEl = form.querySelector('[data-st-inward-stat-qty]');
    if (qtyEl) qtyEl.textContent = formatInwardQty(qtySum);
  }

  function syncInwardConfirm() {
    var form = document.getElementById('st-inward-form');
    var confirmBtn = document.getElementById('st-inward-confirm');
    if (!form || !confirmBtn) return;
    if (isDirectInwardMode()) {
      confirmBtn.disabled = selectedDirectInwardLines().length === 0;
      return;
    }
    var selectedCount = 0;
    var incomplete = false;
    form.querySelectorAll('[data-st-inward-row]').forEach(function (row) {
      var check = row.querySelector('.st-inward-row-check');
      if (!check || !check.checked) return;
      selectedCount += 1;
      var qtyInput = row.querySelector('[data-st-inward-qty]');
      var priceInput = row.querySelector('[data-st-inward-price]');
      var qty = qtyInput ? parseInwardQty(qtyInput.value) : 0;
      var price = priceInput ? parseInwardQty(priceInput.value) : 0;
      if (!(qty > 0) || !(price > 0)) incomplete = true;
    });
    confirmBtn.disabled = selectedCount === 0 || incomplete;
    syncInwardLineTotals();
  }

  function syncInwardSelectAllState() {
    var all = document.getElementById('st-inward-select-all');
    var form = document.getElementById('st-inward-form');
    if (!all || !form) return;
    var checks = Array.from(form.querySelectorAll('.st-inward-row-check'));
    if (!checks.length) {
      all.checked = false;
      all.indeterminate = false;
      return;
    }
    var checkedCount = checks.filter(function (c) { return c.checked; }).length;
    all.checked = checkedCount === checks.length;
    all.indeterminate = checkedCount > 0 && checkedCount < checks.length;
  }

  function isInwardBulkTaxLocked() {
    var bulk = document.getElementById('st-inward-bulk-tax');
    if (!bulk) return false;
    if (document.activeElement === bulk) return true;
    return String(bulk.value || '').trim() !== '';
  }

  function syncInwardLineTaxLockState() {
    var form = document.getElementById('st-inward-form');
    if (!form) return;
    var locked = isInwardBulkTaxLocked();
    form.classList.toggle('is-inward-bulk-tax-locked', locked);
    form.querySelectorAll('[data-st-inward-row]').forEach(function (row) {
      var check = row.querySelector('.st-inward-row-check');
      var on = !!(check && check.checked);
      var tax = row.querySelector('[data-st-inward-tax]');
      if (!tax) return;
      var card = tax.closest('.st-inward-cell-card--tax');
      if (card) card.classList.toggle('is-bulk-locked', locked && on);
      if (!on) {
        tax.disabled = true;
        tax.readOnly = locked;
        tax.tabIndex = -1;
        return;
      }
      tax.disabled = false;
      if (locked) {
        tax.readOnly = true;
        tax.tabIndex = -1;
        tax.setAttribute('aria-readonly', 'true');
        tax.title = 'Overall Tax % is set — clear it to edit line tax';
      } else {
        tax.readOnly = false;
        tax.tabIndex = 0;
        tax.removeAttribute('aria-readonly');
        tax.title = 'Tax percent for this line';
      }
    });
  }

  function syncInwardRowState(row) {
    if (!row) return;
    var check = row.querySelector('.st-inward-row-check');
    var on = !!(check && check.checked);
    row.classList.toggle('is-deselected', !on);
    var qty = row.querySelector('[data-st-inward-qty]');
    var price = row.querySelector('[data-st-inward-price]');
    var tax = row.querySelector('[data-st-inward-tax]');
    if (qty) {
      qty.disabled = !on;
      if (on) {
        var ordered = parseInwardQty(row.getAttribute('data-ordered'));
        if (ordered > 0 && parseInwardQty(qty.value) <= 0) {
          var formatted = formatInwardQty(ordered);
          qty.value = formatted;
          qty.setAttribute('value', formatted);
        }
      }
    }
    if (price) price.disabled = !on;
    if (tax) {
      // Editable by default; locked/blacked out when overall Tax % is set or focused.
      var locked = isInwardBulkTaxLocked();
      var card = tax.closest('.st-inward-cell-card--tax');
      if (card) card.classList.toggle('is-bulk-locked', locked && on);
      if (!on) {
        tax.disabled = true;
        tax.readOnly = locked;
        tax.tabIndex = -1;
      } else {
        tax.disabled = false;
        tax.readOnly = locked;
        tax.tabIndex = locked ? -1 : 0;
        if (locked) {
          tax.setAttribute('aria-readonly', 'true');
          tax.title = 'Overall Tax % is set — clear it to edit line tax';
        } else {
          tax.removeAttribute('aria-readonly');
          tax.title = 'Tax percent for this line';
        }
      }
    }
  }

  function applyInwardBulkTax(rawTax) {
    var form = document.getElementById('st-inward-form');
    if (!form) return false;
    var taxText = String(rawTax == null ? '' : rawTax).trim();
    var tax = parseInwardQty(taxText);
    if (!isFinite(tax) || tax < 0) tax = 0;
    if (tax > 100) {
      tax = 100;
      taxText = '100';
      var bulk = form.querySelector('[data-st-inward-bulk-tax]');
      if (bulk && String(bulk.value || '').trim() !== taxText) bulk.value = taxText;
    }
    // Only push onto lines while overall tax is actively set; clearing unlocks line edits.
    if (taxText !== '') {
      form.querySelectorAll('[data-st-inward-row]').forEach(function (row) {
        var check = row.querySelector('.st-inward-row-check');
        var taxInput = row.querySelector('[data-st-inward-tax]');
        if (!check || !check.checked || !taxInput) return;
        taxInput.value = taxText;
        taxInput.setAttribute('value', taxText);
      });
    }
    syncInwardLineTaxLockState();
    syncInwardConfirm();
    return true;
  }

  function syncSelectedLinesFromBulkTax() {
    var bulk = document.getElementById('st-inward-bulk-tax');
    if (!bulk) return;
    applyInwardBulkTax(bulk.value);
  }

  function syncAllInwardRows() {
    var form = document.getElementById('st-inward-form');
    if (!form) return;
    form.querySelectorAll('[data-st-inward-row]').forEach(syncInwardRowState);
    syncInwardSelectAllState();
    syncSelectedLinesFromBulkTax();
  }

  window.stInwardSupplierChanged = function (root, value) {
    if (!root) return;
    var endpoint = root.getAttribute('data-st-inward-endpoint') || '/stores/purchase-requests';
    var outlet = root.getAttribute('data-st-inward-outlet') || '';
    var view = root.getAttribute('data-st-inward-view') || 'approved';
    try {
      var url = new URL(endpoint, window.location.origin);
      if (outlet) url.searchParams.set('outlet', outlet);
      if (view) url.searchParams.set('view', view);
      url.searchParams.delete('indent');
      url.searchParams.delete('po');
      url.searchParams.delete('po_id');
      if (value) url.searchParams.set('supplier_id', value);
      else url.searchParams.delete('supplier_id');
      stSoftNavigate(url.pathname + url.search);
    } catch (e) {
      var qs = [];
      if (outlet) qs.push('outlet=' + encodeURIComponent(outlet));
      if (view) qs.push('view=' + encodeURIComponent(view));
      if (value) qs.push('supplier_id=' + encodeURIComponent(value));
      stSoftNavigate(endpoint + (qs.length ? ('?' + qs.join('&')) : ''));
    }
  };

  window.stInwardPoChanged = function (root, value) {
    if (!root) return;
    var endpoint = root.getAttribute('data-st-inward-endpoint') || '/stores/purchase-requests';
    var outlet = root.getAttribute('data-st-inward-outlet') || '';
    var view = root.getAttribute('data-st-inward-view') || 'approved';
    var supplierId = root.getAttribute('data-st-inward-supplier') || '';
    // Prefer the selected PO's own outlet so Bar/Restaurant filter matches the PO.
    // Keep "All" when that filter is active — write outlet still comes from the indent.
    if (value) {
      var opt = root.querySelector(
        '.se-filter-listbox-option[data-value="' + String(value).replace(/"/g, '\\"') + '"]'
      );
      var poOutlet = opt && opt.getAttribute('data-outlet');
      if (poOutlet && outlet !== 'both') outlet = poOutlet;
      var poSupplier = opt && opt.getAttribute('data-supplier-id');
      if (poSupplier) supplierId = poSupplier;
    }
    try {
      var url = new URL(endpoint, window.location.origin);
      if (outlet) url.searchParams.set('outlet', outlet);
      if (view) url.searchParams.set('view', view);
      url.searchParams.delete('indent');
      url.searchParams.delete('po');
      if (value) url.searchParams.set('po_id', value);
      else url.searchParams.delete('po_id');
      if (supplierId) url.searchParams.set('supplier_id', supplierId);
      else url.searchParams.delete('supplier_id');
      stSoftNavigate(url.pathname + url.search);
    } catch (e) {
      var qs = [];
      if (outlet) qs.push('outlet=' + encodeURIComponent(outlet));
      if (view) qs.push('view=' + encodeURIComponent(view));
      if (value) qs.push('po_id=' + encodeURIComponent(value));
      if (supplierId) qs.push('supplier_id=' + encodeURIComponent(supplierId));
      stSoftNavigate(endpoint + (qs.length ? ('?' + qs.join('&')) : ''));
    }
  };

  // Legacy alias — older soft-nav caches may still reference this name.
  window.stInwardIndentChanged = window.stInwardPoChanged;

  function isDirectInwardMode() {
    var page = document.getElementById('st-inward-page');
    var confirmBtn = document.getElementById('st-inward-confirm');
    if (confirmBtn && confirmBtn.getAttribute('data-st-inward-mode') === 'direct') return true;
    return !!(page && page.getAttribute('data-st-inward-view') === 'direct');
  }

  function selectedDirectInwardLines() {
    var form = document.getElementById('st-inward-form');
    var lines = [];
    if (!form) return lines;
    form.querySelectorAll('[data-st-inward-direct-row]').forEach(function (row) {
      var itemEl = row.querySelector('[data-st-direct-item], input[name="item_name"]');
      var itemName = itemEl ? String(itemEl.value || '').trim() : '';
      if (!itemName) return;
      var qtyEl = row.querySelector('[data-st-direct-qty], input[name="quantity"]');
      var priceEl = row.querySelector('[data-st-direct-price], [data-st-approx-price]');
      var qty = qtyEl ? parseInwardQty(qtyEl.value) : 0;
      var price = priceEl ? parseInwardQty(priceEl.value) : 0;
      if (qty <= 0 || price <= 0) return;
      var taxEl = row.querySelector('[data-st-direct-tax]');
      var tax = taxEl ? parseInwardQty(taxEl.value) : 0;
      if (tax < 0) tax = 0;
      var unitEl = row.querySelector('[data-st-unit], input[name="unit"]');
      var packLabel = row.querySelector('[data-st-pack-label]');
      var packQty = row.querySelector('[data-st-pack-qty]');
      var packQtyVal = null;
      if (packQty && String(packQty.value || '') !== '') {
        packQtyVal = parseInwardQty(packQty.value);
        if (!(packQtyVal > 0)) packQtyVal = null;
      }
      lines.push({
        item_name: itemName,
        qty: qty,
        unit: unitEl ? String(unitEl.value || 'kg') : 'kg',
        unit_price: price,
        tax_percent: tax,
        pack_label: packLabel ? String(packLabel.value || '') : '',
        pack_qty_in_base: packQtyVal,
        product_category: (function () {
          var productRoot = row.querySelector('.st-product-listbox');
          var selected = productRoot
            ? productRoot.querySelector('.se-filter-listbox-option.is-selected')
            : null;
          if (selected) return String(selected.getAttribute('data-category') || '').trim();
          if (!productRoot) return '';
          var match = null;
          productRoot.querySelectorAll('.se-filter-listbox-option').forEach(function (opt) {
            if (String(opt.getAttribute('data-value') || '') === itemName) match = opt;
          });
          return match ? String(match.getAttribute('data-category') || '').trim() : '';
        })()
      });
    });
    return lines;
  }

  function selectedInwardLines() {
    var form = document.getElementById('st-inward-form');
    var lines = [];
    if (!form) return lines;
    form.querySelectorAll('[data-st-inward-row]').forEach(function (row) {
      var check = row.querySelector('.st-inward-row-check');
      var qtyInput = row.querySelector('[data-st-inward-qty]');
      var priceInput = row.querySelector('[data-st-inward-price]');
      if (!check || !check.checked || !qtyInput) return;
      var qty = parseInwardQty(qtyInput.value);
      if (qty <= 0) return;
      var lineId = parseInt(check.value, 10);
      if (!lineId) return;
      var approvedRate = parseInwardQty(row.getAttribute('data-rate'));
      var unitPrice = priceInput ? parseInwardQty(priceInput.value) : 0;
      if (unitPrice <= 0) return;
      var taxInput = row.querySelector('[data-st-inward-tax]');
      var taxPercent = taxInput ? parseInwardQty(taxInput.value) : 0;
      if (taxPercent < 0) taxPercent = 0;
      lines.push({
        line_id: lineId,
        received_qty: qty,
        rate: approvedRate,
        unit_price: unitPrice,
        tax_percent: taxPercent,
        product_category: String(row.getAttribute('data-product-category') || '').trim()
      });
    });
    return lines;
  }

  function computeInwardApproxTotal(lines) {
    var total = 0;
    (lines || selectedInwardLines()).forEach(function (line) {
      total += (Number(line.received_qty) || 0) * (Number(line.rate) || 0);
    });
    return Math.round(total * 100) / 100;
  }

  function computeInwardEnteredTotal(lines) {
    var total = 0;
    (lines || selectedInwardLines()).forEach(function (line) {
      total += inwardLineTotal(
        Number(line.received_qty) || 0,
        Number(line.unit_price) || 0,
        Number(line.tax_percent) || 0
      );
    });
    return Math.round(total * 100) / 100;
  }

  function formatInwardApprovedHint(amount) {
    var n = Number(amount || 0);
    if (!isFinite(n) || n <= 0) return '';
    n = Math.round(n);
    if (typeof window.formatINR === 'function') return window.formatINR(n, 0);
    return '₹' + n.toLocaleString('en-IN', { minimumFractionDigits: 0, maximumFractionDigits: 0 });
  }

  function setInwardApprovedHint(approvedTotal) {
    var hintEl = document.getElementById('st-inward-approved-hint');
    if (!hintEl) return;
    var total = Number(approvedTotal || 0);
    if (isFinite(total) && total > 0) {
      hintEl.textContent = 'Approved Price: ' + formatInwardApprovedHint(total);
      hintEl.removeAttribute('hidden');
    } else {
      hintEl.textContent = '';
      hintEl.setAttribute('hidden', '');
    }
  }

  function setInwardAmountWarn(msg) {
    var warnEl = document.getElementById('st-inward-amount-warn');
    if (!warnEl) return;
    if (msg) {
      warnEl.textContent = msg;
      warnEl.removeAttribute('hidden');
      warnEl.classList.add('is-visible');
    } else {
      warnEl.textContent = '';
      warnEl.setAttribute('hidden', '');
      warnEl.classList.remove('is-visible');
    }
  }

  function syncInwardAmountWarn() {
    var amountEl = document.getElementById('st-inward-expense-amount');
    var amount = amountEl ? Number(amountEl.value) : 0;
    if (!isFinite(amount) || amount <= 0) {
      setInwardAmountWarn('');
      return;
    }
    var approx = 0;
    if (amountEl) {
      approx = Number(amountEl.getAttribute('data-approved-total') || 0);
    }
    if (!isFinite(approx) || approx <= 0) {
      approx = computeInwardApproxTotal();
    }
    if (approx > 0 && amount - approx > 0.001) {
      setInwardAmountWarn('Value is more than the approved price');
      return;
    }
    setInwardAmountWarn('');
  }

  function roundInwardExpenseAmount() {
    var amountEl = document.getElementById('st-inward-expense-amount');
    if (!amountEl) return;
    var amount = Number(amountEl.value);
    if (!isFinite(amount) || amount <= 0) return;
    var rounded = Math.round(amount);
    if (String(amountEl.value) !== String(rounded)) {
      amountEl.value = String(rounded);
    }
    syncInwardAmountWarn();
  }

  function formatInwardAvailableCash(amount) {
    if (typeof window.formatINR === 'function') return window.formatINR(amount, 0);
    var n = Number(amount || 0);
    return isFinite(n) ? ('₹' + n.toLocaleString('en-IN', { maximumFractionDigits: 0 })) : '₹0';
  }

  function setInwardExpenseError(msg) {
    var errorEl = document.getElementById('st-inward-expense-error');
    if (!errorEl) return;
    if (msg) {
      errorEl.textContent = msg;
      errorEl.style.display = 'block';
      try {
        errorEl.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      } catch (err) {
        try { errorEl.scrollIntoView(true); } catch (err2) { /* ignore */ }
      }
      var box = errorEl.closest('.st-inward-expense-box, .staff-credit-box');
      if (box && typeof box.scrollTo === 'function') {
        box.scrollTo({ top: 0, behavior: 'smooth' });
      } else if (box) {
        box.scrollTop = 0;
      }
    } else {
      errorEl.textContent = '';
      errorEl.style.display = 'none';
    }
  }

  function openInwardModal(el) {
    if (!el) return;
    el.classList.add('open');
    el.setAttribute('aria-hidden', 'false');
  }

  function closeInwardModal(el) {
    if (!el) return;
    closeInwardCategoryModal();
    el.classList.remove('open');
    el.setAttribute('aria-hidden', 'true');
  }

  function setInwardListboxValue(prefix, value, label, placeholder) {
    var hidden = document.getElementById(prefix + '-input');
    var valueEl = document.getElementById(prefix + '-value');
    var trigger = document.getElementById(prefix + '-trigger');
    var list = document.getElementById(prefix + '-list');
    if (hidden) hidden.value = value || '';
    if (valueEl) {
      if (value) {
        valueEl.textContent = label || value;
        valueEl.classList.remove('staff-supplier-placeholder', 'is-placeholder');
      } else {
        valueEl.textContent = placeholder || 'Select';
        valueEl.classList.add('staff-supplier-placeholder', 'is-placeholder');
      }
    }
    // Combobox triggers (e.g. inward supplier) store the label on the input itself.
    if (trigger && trigger.tagName === 'INPUT') {
      if (value) {
        trigger.value = label || value;
        trigger.classList.remove('is-placeholder', 'staff-supplier-placeholder');
      } else {
        trigger.value = '';
        trigger.placeholder = placeholder || 'Select';
        trigger.classList.add('is-placeholder');
      }
    }
    if (list) {
      list.querySelectorAll('.se-filter-listbox-option').forEach(function (opt) {
        var selected = String(opt.getAttribute('data-value') || '') === String(value || '');
        opt.classList.toggle('is-selected', selected);
        opt.setAttribute('aria-selected', selected ? 'true' : 'false');
      });
    }
  }

  function slugifyInwardCategoryKey(name) {
    var value = String(name || '').trim().toLowerCase()
      .replace(/&/g, ' and ')
      .replace(/[^a-z0-9]+/g, '_')
      .replace(/_+/g, '_')
      .replace(/^_|_$/g, '');
    if (!value) return '';
    if (/^\d/.test(value)) value = 'cat_' + value;
    return value.slice(0, 80);
  }

  function formatInwardBreakdownMoney(amount) {
    var n = Number(amount || 0);
    if (!isFinite(n)) n = 0;
    n = Math.round(n * 100) / 100;
    if (typeof window.formatINR === 'function') {
      try {
        return window.formatINR(n, 2);
      } catch (err) { /* fall through */ }
    }
    return '₹' + n.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  function buildInwardCategoryGroups(lines) {
    var groups = [];
    var byKey = {};
    var missing = [];
    (lines || []).forEach(function (line) {
      var cat = String(line.product_category || '').trim();
      if (!cat) {
        var item = String(line.item_name || '').trim() || 'Item';
        if (missing.indexOf(item) === -1) missing.push(item);
        return;
      }
      var key = cat.toLowerCase();
      if (!Object.prototype.hasOwnProperty.call(byKey, key)) {
        byKey[key] = {
          category_label: cat,
          category_key: slugifyInwardCategoryKey(cat),
          amount: 0,
          lines: []
        };
        groups.push(byKey[key]);
      }
      var qty = Number(line.qty || line.received_qty || 0) || 0;
      var price = Number(line.unit_price || 0) || 0;
      var tax = Number(line.tax_percent || 0) || 0;
      var lineTotal = inwardLineTotal(qty, price, tax);
      byKey[key].amount += lineTotal;
      byKey[key].lines.push(line);
    });
    groups.forEach(function (g) {
      g.amount = Math.round(g.amount * 100) / 100;
    });
    var grand = groups.reduce(function (sum, g) { return sum + g.amount; }, 0);
    return {
      groups: groups,
      grandTotal: Math.round(grand * 100) / 100,
      missing: missing
    };
  }

  function renderInwardCategoryBreakdown(lines) {
    var wrap = document.getElementById('st-inward-cat-breakdown');
    var note = document.getElementById('st-inward-cat-breakdown-note');
    var amountEl = document.getElementById('st-inward-expense-amount');
    var built = buildInwardCategoryGroups(lines);
    if (wrap) {
      wrap.innerHTML = '';
      if (!built.groups.length) {
        var empty = document.createElement('div');
        empty.className = 'st-inward-cat-breakdown-empty';
        empty.id = 'st-inward-cat-breakdown-empty';
        empty.textContent = built.missing.length
          ? 'Products need a Product Master category'
          : 'From invoice lines';
        wrap.appendChild(empty);
      } else {
        built.groups.forEach(function (group) {
          var row = document.createElement('div');
          row.className = 'st-inward-cat-breakdown-row';
          row.setAttribute('role', 'listitem');
          var label = document.createElement('span');
          label.className = 'st-inward-cat-breakdown-label';
          label.textContent = group.category_label;
          var amount = document.createElement('span');
          amount.className = 'st-inward-cat-breakdown-amount';
          amount.textContent = formatInwardBreakdownMoney(group.amount);
          row.appendChild(label);
          row.appendChild(amount);
          wrap.appendChild(row);
        });
      }
    }
    if (note) note.hidden = built.groups.length < 2;
    if (amountEl) {
      if (built.grandTotal > 0) {
        amountEl.value = String(Math.round(built.grandTotal));
      } else {
        amountEl.value = '';
      }
    }
    return built;
  }

  function findInwardExpenseCategoryOption(productCategoryName) {
    var options = document.getElementById('st-inward-category-options');
    if (!options || !productCategoryName) return null;
    var raw = String(productCategoryName).trim();
    var rawFold = raw.toLowerCase();
    var slug = slugifyInwardCategoryKey(raw);
    var aliasSlug = slug === 'vegetable' ? 'vegetables' : slug;
    var found = null;
    options.querySelectorAll('.se-filter-listbox-option').forEach(function (opt) {
      if (found) return;
      var key = String(opt.getAttribute('data-value') || '');
      var label = String(opt.getAttribute('data-label') || opt.textContent || '').trim();
      if (label.toLowerCase() === rawFold || key === slug || key === aliasSlug) {
        found = { key: key, label: label || raw };
      }
    });
    return found;
  }

  async function ensureInwardExpenseCategory(productCategoryName) {
    var existing = findInwardExpenseCategoryOption(productCategoryName);
    if (existing) return existing;
    var confirmBtn = document.getElementById('st-inward-confirm');
    var modal = document.getElementById('st-inward-category-modal');
    var url = (modal && modal.getAttribute('data-st-save-category-url'))
      || (confirmBtn && confirmBtn.getAttribute('data-st-inward-save-category-url'))
      || '';
    if (!url || !productCategoryName) return null;
    try {
      var res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ category_name: productCategoryName })
      });
      var data = await res.json().catch(function () { return {}; });
      if (!res.ok || !data.ok) return null;
      var key = data.category_key || slugifyInwardCategoryKey(productCategoryName);
      var label = data.category_label || productCategoryName;
      upsertInwardCategoryOption(key, label);
      return { key: key, label: label };
    } catch (err) {
      return null;
    }
  }

  var inwardAvailableCash = 0;
  var inwardAvailableFetchToken = 0;

  function syncInwardPaymentVisibility() {
    var paymentInput = document.getElementById('st-inward-payment-input');
    var method = paymentInput ? (paymentInput.value || '') : '';
    var transactionWrap = document.getElementById('st-inward-transaction-wrap');
    var transactionEl = document.getElementById('st-inward-transaction-id');
    var availableWrap = document.getElementById('st-inward-available-wrap');
    var availableCashEl = document.getElementById('st-inward-available-cash');
    if (transactionWrap) transactionWrap.hidden = method !== 'bank_transfer';
    if (method !== 'bank_transfer' && transactionEl) transactionEl.value = '';
    if (availableWrap) availableWrap.hidden = method !== 'cash';
    if (availableCashEl) availableCashEl.textContent = formatInwardAvailableCash(inwardAvailableCash);
  }

  window.stInwardPaymentChanged = function () {
    syncInwardPaymentVisibility();
  };

  async function refreshInwardAvailableCash() {
    var confirmBtn = document.getElementById('st-inward-confirm');
    var dateEl = document.getElementById('st-inward-expense-date');
    var availableCashUrl = confirmBtn ? (confirmBtn.getAttribute('data-st-available-cash-url') || '') : '';
    var defaultCompany = confirmBtn ? (confirmBtn.getAttribute('data-st-default-company') || '') : '';
    var todayIso = confirmBtn ? (confirmBtn.getAttribute('data-st-today') || '') : '';
    if (!availableCashUrl) {
      syncInwardPaymentVisibility();
      return;
    }
    var token = ++inwardAvailableFetchToken;
    var purchaseDate = dateEl && dateEl.value ? dateEl.value : todayIso;
    try {
      var url = new URL(availableCashUrl, window.location.origin);
      url.searchParams.set('company', defaultCompany);
      url.searchParams.set('date', purchaseDate);
      var res = await fetch(url.toString(), { headers: { Accept: 'application/json' } });
      var data = await res.json().catch(function () { return {}; });
      if (token !== inwardAvailableFetchToken) return;
      if (res.ok && data.ok) inwardAvailableCash = Number(data.available_cash || 0);
    } catch (err) {
      /* keep last known available cash */
    }
    if (token === inwardAvailableFetchToken) syncInwardPaymentVisibility();
  }

  function resetInwardExpenseForm() {
    var confirmBtn = document.getElementById('st-inward-confirm');
    var todayIso = confirmBtn ? (confirmBtn.getAttribute('data-st-today') || '') : '';
    var dateEl = document.getElementById('st-inward-expense-date');
    var descriptionEl = document.getElementById('st-inward-expense-description');
    var amountEl = document.getElementById('st-inward-expense-amount');
    var invoiceEl = document.getElementById('st-inward-invoice-number');
    var transactionEl = document.getElementById('st-inward-transaction-id');
    var breakdown = document.getElementById('st-inward-cat-breakdown');
    var note = document.getElementById('st-inward-cat-breakdown-note');
    setInwardExpenseError('');
    setInwardAmountWarn('');
    setInwardApprovedHint(0);
    if (dateEl) dateEl.value = todayIso;
    if (descriptionEl) descriptionEl.value = '';
    if (amountEl) amountEl.value = '';
    if (amountEl) amountEl.removeAttribute('data-approved-total');
    if (invoiceEl) invoiceEl.value = '';
    if (transactionEl) transactionEl.value = '';
    if (breakdown) {
      breakdown.innerHTML = '<div class="st-inward-cat-breakdown-empty" id="st-inward-cat-breakdown-empty">From invoice lines</div>';
    }
    if (note) note.hidden = true;
    var directMode = isDirectInwardMode();
    var supplierField = document.getElementById('st-inward-supplier-field');
    if (supplierField) supplierField.hidden = !directMode;
    if (directMode) {
      setInwardListboxValue('st-inward-supplier', '', '', 'Search by name or GST…');
    } else if (confirmBtn) {
      var poSupplierId = confirmBtn.getAttribute('data-st-supplier-id') || '';
      var poSupplierName = confirmBtn.getAttribute('data-st-supplier-name') || '';
      setInwardListboxValue(
        'st-inward-supplier',
        poSupplierId,
        poSupplierName,
        'Search by name or GST…'
      );
    } else {
      setInwardListboxValue('st-inward-supplier', '', '', 'Search by name or GST…');
    }
    setInwardListboxValue('st-inward-payment', '', '', 'Select payment type');
    syncInwardPaymentVisibility();
    refreshInwardAvailableCash();
  }

  async function openInwardExpenseModal() {
    var modal = document.getElementById('st-inward-expense-modal');
    var confirmBtn = document.getElementById('st-inward-confirm');
    if (!modal || !confirmBtn || confirmBtn.disabled) return;
    var directMode = isDirectInwardMode();
    var lines = directMode ? selectedDirectInwardLines() : selectedInwardLines();
    if (!lines.length) return;
    resetInwardExpenseForm();
    var amountEl = document.getElementById('st-inward-expense-amount');
    var approvedTotal = directMode ? 0 : computeInwardApproxTotal(lines);
    var built = renderInwardCategoryBreakdown(lines);
    if (amountEl) {
      amountEl.setAttribute('data-approved-total', String(Math.round(approvedTotal || 0)));
    }
    setInwardApprovedHint(approvedTotal);
    syncInwardAmountWarn();
    var descriptionEl = document.getElementById('st-inward-expense-description');
    if (directMode) {
      var notesEl = document.getElementById('st-inward-notes');
      var notes = notesEl ? String(notesEl.value || '').trim() : '';
      var description = 'Stock inward without indent approval';
      if (notes) description += ' — ' + notes;
      if (descriptionEl) descriptionEl.value = description;
    } else {
      var indentNo = confirmBtn.getAttribute('data-st-inward-indent-no') || '';
      var notesEl2 = document.getElementById('st-inward-notes');
      var notes2 = notesEl2 ? String(notesEl2.value || '').trim() : '';
      var description2 = 'Stock inward ' + indentNo;
      if (notes2) description2 += ' — ' + notes2;
      if (descriptionEl) descriptionEl.value = description2;
    }
    if (!built.groups.length || built.missing.length) {
      setInwardExpenseError('Products need a Product Master category before confirming.');
    } else {
      setInwardExpenseError('');
    }
    openInwardModal(modal);
    if (descriptionEl) descriptionEl.focus();
  }

  async function submitInwardExpense() {
    var confirmBtn = document.getElementById('st-inward-confirm');
    var saveBtn = document.getElementById('st-inward-expense-save');
    var modal = document.getElementById('st-inward-expense-modal');
    if (!confirmBtn) return;
    var directMode = isDirectInwardMode();
    var lines = directMode ? selectedDirectInwardLines() : selectedInwardLines();
    if (!lines.length) {
      setInwardExpenseError(directMode
        ? 'Add at least one product with quantity and price.'
        : 'Select at least one item with a received quantity.');
      return;
    }
    var indentEl = document.getElementById('st-inward-indent-id');
    var dateEl = document.getElementById('st-inward-expense-date');
    var descriptionEl = document.getElementById('st-inward-expense-description');
    var amountEl = document.getElementById('st-inward-expense-amount');
    var invoiceEl = document.getElementById('st-inward-invoice-number');
    var transactionEl = document.getElementById('st-inward-transaction-id');
    var notesEl = document.getElementById('st-inward-notes');
    var purchaseDate = dateEl ? dateEl.value : '';
    var description = descriptionEl ? descriptionEl.value.trim() : '';
    var built = renderInwardCategoryBreakdown(lines);
    roundInwardExpenseAmount();
    var amountRaw = amountEl ? amountEl.value : '';
    var supplierId = document.getElementById('st-inward-supplier-input')
      ? document.getElementById('st-inward-supplier-input').value
      : '';
    if (!directMode && !supplierId && confirmBtn) {
      supplierId = confirmBtn.getAttribute('data-st-supplier-id') || '';
    }
    var paymentType = document.getElementById('st-inward-payment-input')
      ? document.getElementById('st-inward-payment-input').value
      : '';
    var transactionId = transactionEl ? transactionEl.value.trim() : '';
    var invoiceNumber = invoiceEl ? invoiceEl.value.trim() : '';

    if (!purchaseDate) {
      setInwardExpenseError('Please select a purchase date.');
      return;
    }
    if (!supplierId) {
      setInwardExpenseError(directMode
        ? 'Please select a supplier.'
        : 'This purchase order has no supplier.');
      return;
    }
    if (!built.groups.length || built.missing.length) {
      setInwardExpenseError('Products need a Product Master category before confirming.');
      return;
    }
    if (!description) {
      setInwardExpenseError('Please enter an expense description.');
      return;
    }
    if (!amountRaw || Number(amountRaw) <= 0) {
      setInwardExpenseError('Please enter a value greater than 0.');
      return;
    }
    if (!paymentType) {
      setInwardExpenseError('Please select a payment type.');
      return;
    }
    if (paymentType === 'bank_transfer' && !transactionId) {
      setInwardExpenseError('Please enter the bank transaction ID.');
      return;
    }
    if (paymentType === 'cash' && Number(amountRaw) - Number(inwardAvailableCash) > 0.001) {
      setInwardExpenseError(
        'Cash expense cannot be more than available cash (' +
          formatInwardAvailableCash(inwardAvailableCash) +
          ').'
      );
      return;
    }

    var confirmUrl = confirmBtn.getAttribute('data-st-inward-confirm-url') || '';
    if (!confirmUrl) {
      setInwardExpenseError('Missing confirm endpoint.');
      return;
    }
    setInwardExpenseError('');
    if (saveBtn) saveBtn.disabled = true;
    var payload = {
      notes: notesEl ? String(notesEl.value || '').trim() : '',
      company: confirmBtn.getAttribute('data-st-default-company') || '',
      location: confirmBtn.getAttribute('data-st-default-location') || '',
      date: purchaseDate,
      description: description,
      amount: amountRaw,
      payment_type: paymentType,
      transaction_id: paymentType === 'bank_transfer' ? transactionId : '',
      invoice_number: invoiceNumber,
      supplier_id: supplierId
    };
    if (directMode) {
      payload.outlet = confirmBtn.getAttribute('data-st-outlet')
        || (document.getElementById('st-outlet') || {}).value
        || '';
      payload.lines = lines.map(function (line) {
        return {
          item_name: line.item_name,
          qty: line.qty,
          unit: line.unit,
          unit_price: line.unit_price,
          tax_percent: line.tax_percent,
          pack_label: line.pack_label,
          pack_qty_in_base: line.pack_qty_in_base
        };
      });
    } else {
      payload.indent_id = indentEl ? indentEl.value : '';
      var poEl = document.getElementById('st-inward-po-id');
      if (poEl && String(poEl.value || '').trim()) {
        payload.po_id = String(poEl.value || '').trim();
      }
      payload.lines = lines.map(function (line) {
        return {
          line_id: line.line_id,
          received_qty: line.received_qty,
          unit_price: line.unit_price,
          tax_percent: line.tax_percent
        };
      });
    }
    try {
      var res = await fetch(confirmUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify(payload)
      });
      var data = await res.json().catch(function () { return {}; });
      if (!res.ok || !data.ok) {
        throw new Error(data.error || 'Could not confirm stock inward.');
      }
      closeInwardModal(modal);
      if (data.redirect) window.location.href = data.redirect;
      else if (typeof window.deSoftRefresh === 'function') window.deSoftRefresh();
      else window.location.reload();
    } catch (err) {
      setInwardExpenseError(err.message || 'Could not confirm stock inward.');
      var invoiceElFocus = document.getElementById('st-inward-invoice-number');
      if (
        invoiceElFocus
        && /invoice number already exists/i.test(String(err && err.message || ''))
      ) {
        try { invoiceElFocus.focus(); invoiceElFocus.select(); } catch (focusErr) { /* ignore */ }
      }
    } finally {
      if (saveBtn) saveBtn.disabled = false;
    }
  }

  function onInwardClick(event) {
    var target = eventElement(event);
    if (!target) return;

    if (target.closest('#st-inward-expense-cancel')) {
      event.preventDefault();
      closeInwardModal(document.getElementById('st-inward-expense-modal'));
      return;
    }
    if (target.closest('#st-inward-expense-save')) {
      event.preventDefault();
      submitInwardExpense();
      return;
    }
    var expenseModal = document.getElementById('st-inward-expense-modal');
    if (expenseModal && target === expenseModal) {
      closeInwardModal(expenseModal);
      return;
    }

    var page = document.getElementById('st-inward-page');
    if (!page || !page.contains(target)) return;

    if (target.closest('#st-inward-confirm')) {
      event.preventDefault();
      openInwardExpenseModal();
      return;
    }
  }

  function onInwardChange(event) {
    var target = event.target;
    if (!target) return;
    var page = document.getElementById('st-inward-page');
    if (!page || !page.contains(target)) return;

    if (target.id === 'st-inward-select-all') {
      page.querySelectorAll('.st-inward-row-check').forEach(function (check) {
        check.checked = !!target.checked;
      });
      syncAllInwardRows();
      return;
    }
    if (target.classList.contains('st-inward-row-check')) {
      syncAllInwardRows();
      return;
    }
    if (target.matches('[data-st-inward-qty]')) {
      clampInwardQty(target);
      syncInwardConfirm();
      return;
    }
    if (target.matches('[data-st-inward-bulk-tax]')) {
      applyInwardBulkTax(target.value);
      return;
    }
    if (target.matches('[data-st-inward-price], [data-st-inward-tax]')) {
      syncInwardConfirm();
    }
  }

  function onInwardInput(event) {
    var target = event.target;
    if (!target) return;
    var page = document.getElementById('st-inward-page');
    if (!page || !page.contains(target)) return;
    if (target.id === 'st-inward-expense-amount') {
      syncInwardAmountWarn();
      return;
    }
    if (target.matches('[data-st-inward-bulk-tax]')) {
      applyInwardBulkTax(target.value);
      return;
    }
    if (
      target.matches('[data-st-direct-qty], [data-st-direct-price], [data-st-direct-tax], [data-st-approx-price]')
      || (target.closest('[data-st-inward-direct-row]') && (
        target.name === 'quantity' || target.name === 'tax_percent' || target.name === 'unit_price'
      ))
    ) {
      syncIndentLineTotals(target.closest('.st-lines-wrap') || page);
      return;
    }
    if (target.matches('[data-st-inward-qty], [data-st-inward-price], [data-st-inward-tax]')) {
      syncInwardConfirm();
      return;
    }
    if (target.matches('[data-st-notes-counter]')) syncNotesCounter();
  }

  function onInwardBulkTaxFocus(event) {
    var target = event.target;
    if (!target || !target.matches || !target.matches('[data-st-inward-bulk-tax]')) return;
    var page = document.getElementById('st-inward-page');
    if (!page || !page.contains(target)) return;
    // Defer focusout so activeElement has updated before we re-evaluate lock.
    if (event.type === 'focusout') {
      setTimeout(function () {
        syncInwardLineTaxLockState();
        if (isInwardBulkTaxLocked()) applyInwardBulkTax(target.value);
        else syncInwardConfirm();
      }, 0);
      return;
    }
    syncInwardLineTaxLockState();
  }

  function upsertInwardCategoryOption(key, label) {
    var options = document.getElementById('st-inward-category-options');
    if (!options || !key) return;
    var existing = null;
    options.querySelectorAll('.se-filter-listbox-option').forEach(function (opt) {
      if (String(opt.getAttribute('data-value') || '') === String(key)) existing = opt;
    });
    if (existing) {
      existing.setAttribute('data-label', label || key);
      existing.setAttribute('data-name', String(label || key).toLowerCase());
      existing.textContent = label || key;
      return existing;
    }
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'se-filter-listbox-option staff-category-option';
    btn.setAttribute('role', 'option');
    btn.setAttribute('data-value', key);
    btn.setAttribute('data-label', label || key);
    btn.setAttribute('data-name', String(label || key).toLowerCase());
    btn.setAttribute('aria-selected', 'false');
    btn.textContent = label || key;
    options.appendChild(btn);
    return btn;
  }

  window.openInwardCategoryModal = function openInwardCategoryModal() {
    var modal = document.getElementById('st-inward-category-modal');
    if (!modal) return false;
    var errEl = document.getElementById('st-inward-category-modal-err');
    if (errEl) {
      errEl.style.display = 'none';
      errEl.textContent = '';
    }
    var nameEl = document.getElementById('st-inward-category-name');
    if (nameEl && !modal.classList.contains('active')) {
      nameEl.value = '';
    }
    modal.classList.add('active');
    window.setTimeout(function () {
      if (nameEl) {
        nameEl.focus();
        nameEl.select();
      }
    }, 0);
    return true;
  };

  window.closeInwardCategoryModal = function closeInwardCategoryModal() {
    var modal = document.getElementById('st-inward-category-modal');
    if (!modal) return;
    modal.classList.remove('active');
    var errEl = document.getElementById('st-inward-category-modal-err');
    if (errEl) {
      errEl.style.display = 'none';
      errEl.textContent = '';
    }
    var nameEl = document.getElementById('st-inward-category-name');
    if (nameEl) nameEl.value = '';
    var addBtn = document.getElementById('st-inward-add-category-btn');
    if (addBtn) addBtn.focus();
  };

  function closeInwardCategoryModal() {
    window.closeInwardCategoryModal();
  }

  async function submitInwardCategoryForm(e) {
    if (e) e.preventDefault();
    var nameEl = document.getElementById('st-inward-category-name');
    var errEl = document.getElementById('st-inward-category-modal-err');
    var submitBtn = document.getElementById('st-inward-category-submit');
    var modal = document.getElementById('st-inward-category-modal');
    var confirmBtn = document.getElementById('st-inward-confirm');
    var name = ((nameEl && nameEl.value) || '').trim();
    if (!name) {
      if (errEl) {
        errEl.textContent = 'Category name is required.';
        errEl.style.display = 'block';
      }
      if (nameEl) nameEl.focus();
      return;
    }
    var url = (modal && modal.getAttribute('data-st-save-category-url'))
      || (confirmBtn && confirmBtn.getAttribute('data-st-inward-save-category-url'))
      || '';
    if (!url) {
      if (errEl) {
        errEl.textContent = 'Missing save category endpoint.';
        errEl.style.display = 'block';
      }
      return;
    }
    if (submitBtn) submitBtn.disabled = true;
    try {
      var res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ category_name: name })
      });
      var data = await res.json().catch(function () { return {}; });
      if (!res.ok || !data.ok) {
        throw new Error(data.error || 'Could not save category.');
      }
      var key = data.category_key || '';
      var label = data.category_label || name;
      upsertInwardCategoryOption(key, label);
      setInwardListboxValue('st-inward-category', key, label, 'Select category');
      closeInwardCategoryModal();
    } catch (err) {
      if (errEl) {
        errEl.textContent = err.message || 'Could not save category.';
        errEl.style.display = 'block';
      }
    } finally {
      if (submitBtn) submitBtn.disabled = false;
    }
  }

  function initInwardCategoryModal() {
    if (!document.getElementById('st-inward-category-modal')) return;

    if (document.documentElement.getAttribute('data-st-inward-cat-bound') !== '1') {
      document.documentElement.setAttribute('data-st-inward-cat-bound', '1');

      document.addEventListener('click', function (e) {
        var actionEl = e.target && e.target.closest ? e.target.closest('[data-st-action]') : null;
        if (!actionEl) {
          var catModal = document.getElementById('st-inward-category-modal');
          if (catModal && e.target === catModal) {
            closeInwardCategoryModal();
          }
          return;
        }
        var action = actionEl.getAttribute('data-st-action');
        if (action === 'open-inward-category-modal') {
          e.preventDefault();
          window.openInwardCategoryModal();
        } else if (action === 'close-inward-category-modal') {
          e.preventDefault();
          closeInwardCategoryModal();
        }
      });

      document.addEventListener('keydown', function (e) {
        if (e.key !== 'Escape') return;
        var catModal = document.getElementById('st-inward-category-modal');
        if (catModal && catModal.classList.contains('active')) {
          closeInwardCategoryModal();
          e.stopPropagation();
        }
      });
    }

    var form = document.getElementById('st-inward-add-category-form');
    if (form && form.getAttribute('data-bound') !== '1') {
      form.setAttribute('data-bound', '1');
      form.addEventListener('submit', submitInwardCategoryForm);
    }
  }

  function initStockInward() {
    var page = document.getElementById('st-inward-page');
    if (!page) return;
    applyInwardOrderedDefaults();
    syncAllInwardRows();
    syncNotesCounter();
    initInwardCategoryModal();
    var confirmBtn = document.getElementById('st-inward-confirm');
    if (confirmBtn) {
      inwardAvailableCash = Number(confirmBtn.getAttribute('data-st-available-cash') || 0);
    }
    var dateEl = document.getElementById('st-inward-expense-date');
    if (dateEl && !dateEl.__stInwardCashBound) {
      dateEl.__stInwardCashBound = true;
      dateEl.addEventListener('change', refreshInwardAvailableCash);
    }
    var amountEl = document.getElementById('st-inward-expense-amount');
    if (amountEl && !amountEl.__stInwardAmountWarnBound) {
      amountEl.__stInwardAmountWarnBound = true;
      amountEl.addEventListener('input', syncInwardAmountWarn);
      amountEl.addEventListener('change', roundInwardExpenseAmount);
      amountEl.addEventListener('blur', roundInwardExpenseAmount);
    }
    var form = document.getElementById('st-inward-form');
    if (form && !form.__stInwardSubmitBound) {
      form.__stInwardSubmitBound = true;
      form.addEventListener('submit', function (e) {
        e.preventDefault();
        openInwardExpenseModal();
      });
    }
    var expenseSaveBtn = document.getElementById('st-inward-expense-save');
    if (expenseSaveBtn && !expenseSaveBtn.__stInwardSaveBound) {
      expenseSaveBtn.__stInwardSaveBound = true;
      expenseSaveBtn.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        submitInwardExpense();
      });
    }
    var expenseCancelBtn = document.getElementById('st-inward-expense-cancel');
    if (expenseCancelBtn && !expenseCancelBtn.__stInwardCancelBound) {
      expenseCancelBtn.__stInwardCancelBound = true;
      expenseCancelBtn.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        closeInwardModal(document.getElementById('st-inward-expense-modal'));
      });
    }
    syncInwardPaymentVisibility();
    if (isDirectInwardMode()) {
      syncIndentLineTotals(page.querySelector('.st-inward-direct-lines-wrap') || page);
      syncInwardConfirm();
    }
  }

  function initStFlashAutoDismiss() {
    var flashes = document.querySelectorAll('[data-st-flash-auto]');
    if (!flashes.length) return;
    var reduceMotion = false;
    try {
      reduceMotion = !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
    } catch (e) {}
    flashes.forEach(function (el) {
      if (el.getAttribute('data-st-flash-bound') === '1') return;
      el.setAttribute('data-st-flash-bound', '1');
      window.setTimeout(function () {
        if (!el.parentNode) return;
        if (reduceMotion) {
          el.parentNode.removeChild(el);
          return;
        }
        el.classList.add('is-leaving');
        window.setTimeout(function () {
          if (el.parentNode) el.parentNode.removeChild(el);
        }, 320);
      }, 10000);
    });
  }

  function navigateProductMasterList() {
    var modal = document.getElementById('st-product-modal');
    var url = modal && modal.getAttribute('data-st-list-url');
    if (!url) return;
    /* Stay inside Masters / Indent Product Master popup — just dismiss the form overlay. */
    var masterModal = document.getElementById('md-master-modal');
    if (masterModal && masterModal.classList.contains('open')) {
      if (modal) modal.classList.remove('active');
      return;
    }
    var indentPm = document.getElementById('st-product-master-modal');
    if (indentPm && indentPm.classList.contains('open')) {
      if (modal) modal.classList.remove('active');
      return;
    }
    if (typeof window.deSoftRefresh === 'function') {
      window.deSoftRefresh(url);
    } else if (typeof window.deNavigateWithTransition === 'function') {
      window.deNavigateWithTransition(url);
    } else {
      window.location.href = url;
    }
  }

  window.openCategoryModal = function openCategoryModal() {
    var modal = document.getElementById('st-category-modal');
    if (!modal) return false;
    var errEl = document.getElementById('st-category-modal-err');
    if (errEl && !errEl.textContent.trim()) {
      errEl.style.display = 'none';
    }
    var nameEl = document.getElementById('st-category-name');
    if (nameEl && !modal.classList.contains('active')) {
      nameEl.value = '';
    }
    modal.classList.add('active');
    window.setTimeout(function () {
      if (nameEl) {
        nameEl.focus();
        nameEl.select();
      }
    }, 0);
    return true;
  };

  window.closeCategoryModal = function closeCategoryModal() {
    var modal = document.getElementById('st-category-modal');
    if (!modal) return;
    modal.classList.remove('active');
    var errEl = document.getElementById('st-category-modal-err');
    if (errEl) {
      errEl.style.display = 'none';
      errEl.textContent = '';
    }
    var nameEl = document.getElementById('st-category-name');
    if (nameEl) nameEl.value = '';
    var addBtn = document.getElementById('st-add-category-btn');
    if (addBtn) addBtn.focus();
  };

  window.openUnitModal = function openUnitModal() {
    var modal = document.getElementById('st-unit-modal');
    if (!modal) return false;
    var errEl = document.getElementById('st-unit-modal-err');
    if (errEl && !errEl.textContent.trim()) {
      errEl.style.display = 'none';
    }
    var nameEl = document.getElementById('st-unit-name');
    if (nameEl && !modal.classList.contains('active')) {
      nameEl.value = '';
    }
    modal.classList.add('active');
    window.setTimeout(function () {
      if (nameEl) {
        nameEl.focus();
        nameEl.select();
      }
    }, 0);
    return true;
  };

  window.closeUnitModal = function closeUnitModal() {
    var modal = document.getElementById('st-unit-modal');
    if (!modal) return;
    modal.classList.remove('active');
    var errEl = document.getElementById('st-unit-modal-err');
    if (errEl) {
      errEl.style.display = 'none';
      errEl.textContent = '';
    }
    var nameEl = document.getElementById('st-unit-name');
    if (nameEl) nameEl.value = '';
    var addBtn = document.getElementById('st-add-unit-btn');
    if (addBtn) addBtn.focus();
  };

  window.openProductModal = function openProductModal(opts) {
    var modal = document.getElementById('st-product-modal');
    var form = document.getElementById('st-product-form');
    if (!modal || !form) return false;
    opts = opts || {};
    // Never wipe a server-rendered edit form (preferred suppliers, etc.).
    var alreadyEditing = modal.getAttribute('data-st-editing') === '1'
      || !!(document.getElementById('st-product-id') || {}).value;
    var reset = opts.reset !== false && !opts.keepValues && !alreadyEditing;

    if (reset) {
      var idEl = document.getElementById('st-product-id');
      if (idEl) idEl.value = '';
      var nameEl = document.getElementById('st-product-name');
      if (nameEl) nameEl.value = '';
      var errEl = document.getElementById('st-product-modal-err');
      if (errEl) {
        errEl.style.display = 'none';
        errEl.textContent = '';
      }
      window.closeCategoryModal();
      window.closeUnitModal();
      resetVariantRows();

      if (typeof window.resetEpListbox === 'function') {
        window.resetEpListbox('st-product-category', '', 'Select category…');
        window.resetEpListbox('st-product-outlet', '', 'Select outlet…');
        window.resetEpListbox('st-product-supplier-1', '', 'Select supplier…');
        window.resetEpListbox('st-product-supplier-2', '', 'Select supplier…');
        window.resetEpListbox('st-product-supplier-3', '', 'Select supplier…');
      }
      modal.setAttribute('data-st-editing', '0');
    }

    var title = document.getElementById('st-product-modal-title');
    var editing = modal.getAttribute('data-st-editing') === '1' || !!(document.getElementById('st-product-id') || {}).value;
    if (title) title.textContent = editing ? 'Edit product' : 'Add product';

    if (typeof window.initEpListboxes === 'function') {
      window.initEpListboxes();
    }
    modal.classList.add('active');
    window.setTimeout(function () {
      var focusEl = document.getElementById('st-product-name');
      if (focusEl) focusEl.focus();
    }, 0);
    return true;
  };

  function productFormHasContent() {
    var nameEl = document.getElementById('st-product-name');
    return !!(((nameEl && nameEl.value) || '').trim());
  }

  function submitProductForm() {
    var form = document.getElementById('st-product-form');
    if (!form) return false;
    if (typeof form.requestSubmit === 'function') {
      form.requestSubmit();
    } else {
      form.submit();
    }
    return true;
  }

  window.doneProductModal = function doneProductModal() {
    window.closeCategoryModal();
    window.closeUnitModal();
    if (productFormHasContent()) {
      submitProductForm();
      return;
    }
    window.closeProductModal({ discard: true });
  };

  function resetVariantRows() {
    var wrap = document.getElementById('st-product-variants');
    var tpl = document.getElementById('st-product-variant-template');
    if (!wrap || !tpl) return;
    wrap.innerHTML = '';
    var node = tpl.content.cloneNode(true);
    wrap.appendChild(node);
    var row = wrap.querySelector('[data-st-variant-row]');
    rewireVariantUnitListbox(row);
    if (typeof window.initEpListboxes === 'function') window.initEpListboxes();
  }

  function defaultVariantUnit() {
    var tpl = document.getElementById('st-product-variant-template');
    if (!tpl) return 'gram';
    var hidden = tpl.content.querySelector('input[name="variant_unit"]');
    return (hidden && hidden.value) || 'gram';
  }

  function rewireVariantUnitListbox(row) {
    if (!row) return;
    var root = row.querySelector('[data-st-variant-unit-listbox]');
    if (!root) return;
    var hidden = root.querySelector('input[name="variant_unit"]');
    var current = (hidden && hidden.value) || defaultVariantUnit();
    rewireOneListbox(root, {
      prefix: 'st-vunit-',
      defaultValue: current
    });
    // rewireOneListbox leaves display as placeholder text when placeholder is set;
    // with only defaultValue, sync visible label to the selected option.
    var valueEl = root.querySelector('.se-filter-chip-value');
    var selected = root.querySelector('.se-filter-listbox-option.is-selected');
    if (valueEl) {
      valueEl.textContent = selected
        ? (selected.getAttribute('data-label') || selected.textContent || current)
        : current;
      valueEl.classList.remove('is-placeholder');
    }
  }

  function addVariantRow() {
    var wrap = document.getElementById('st-product-variants');
    var tpl = document.getElementById('st-product-variant-template');
    if (!wrap || !tpl) return;
    var node = tpl.content.cloneNode(true);
    wrap.appendChild(node);
    var rows = wrap.querySelectorAll('[data-st-variant-row]');
    var last = rows[rows.length - 1];
    rewireVariantUnitListbox(last);
    if (typeof window.initEpListboxes === 'function') window.initEpListboxes();
    var focusEl = last && last.querySelector('input[name="variant_qty"]');
    if (focusEl) {
      try { focusEl.focus(); } catch (e) {}
    }
  }

  function removeVariantRow(btn) {
    var wrap = document.getElementById('st-product-variants');
    var row = btn && btn.closest ? btn.closest('[data-st-variant-row]') : null;
    if (!wrap || !row) return;
    var rows = wrap.querySelectorAll('[data-st-variant-row]');
    if (rows.length <= 1) {
      row.querySelectorAll('input[name="variant_qty"], input[name="variant_approximate_price"]').forEach(function (input) {
        input.value = '';
      });
      return;
    }
    row.remove();
  }

  window.addProductVariantRow = addVariantRow;
  window.removeProductVariantRow = removeVariantRow;

  function ensureProductPackRows(row) {
    if (!row || row.getAttribute('data-packs-ready') === '1') return;
    var raw = row.getAttribute('data-packs');
    if (!raw) {
      row.setAttribute('data-packs-ready', '1');
      return;
    }
    var packs;
    try {
      packs = JSON.parse(raw);
    } catch (err) {
      packs = [];
    }
    row.removeAttribute('data-packs');
    row.setAttribute('data-packs-ready', '1');
    if (!packs || !packs.length) return;

    var productId = row.getAttribute('data-product-id') || '';
    var nameCell = row.querySelector('.st-product-name-text');
    var productName = nameCell ? String(nameCell.textContent || '').trim() : '';
    var catPill = row.querySelector('.st-cat-pill');
    var catName = catPill ? String(catPill.textContent || '').trim() : '';
    var outletPill = row.querySelector('.st-outlet-pill');
    var outletLabel = outletPill ? String(outletPill.textContent || '').trim() : '';
    var outletClass = '';
    if (outletPill && outletPill.className) {
      var match = String(outletPill.className).match(/st-outlet-pill--(\S+)/);
      if (match) outletClass = match[1];
    }
    var unitCell = row.cells[3];
    var defaultUnit = unitCell ? String(unitCell.getAttribute('data-sort-value') || unitCell.textContent || '').trim() : '';
    var editLink = row.querySelector('a.act-btn.edit');
    var editHref = editLink ? editLink.getAttribute('href') || '' : '';
    var delBtn = row.querySelector('[data-st-product-delete]');
    var deleteUrl = delBtn ? delBtn.getAttribute('data-delete-url') || '' : '';
    var frag = document.createDocumentFragment();

    packs.forEach(function (variant) {
      var label = String((variant && variant.label) || '').trim();
      var qtyDisplay = String((variant && variant.qty_in_base_display) || '').trim();
      var priceRaw = variant && variant.approximate_price != null ? variant.approximate_price : '';
      var priceDisplay = String((variant && variant.approximate_price_display) || '').trim();
      var tr = document.createElement('tr');
      tr.className = 'st-product-pack-row';
      tr.setAttribute('data-pack-parent', productId);
      tr.hidden = true;
      tr.innerHTML =
        '<td data-sort-value="' + escapeHtml(catName) + '"><span class="st-cat-pill">' + escapeHtml(catName) + '</span></td>' +
        '<td class="pl-name" data-sort-value="' + escapeHtml(productName + ' — ' + label) + '">' +
          '<span class="st-product-pack-name">' + escapeHtml(productName) + ' — ' + escapeHtml(label) + '</span>' +
        '</td>' +
        '<td data-sort-value="' + escapeHtml(outletLabel) + '">' +
          '<span class="st-outlet-pill' + (outletClass ? ' st-outlet-pill--' + escapeHtml(outletClass) : '') + '">' + escapeHtml(outletLabel) + '</span>' +
        '</td>' +
        '<td data-sort-value="' + escapeHtml(qtyDisplay + (defaultUnit ? ' ' + defaultUnit : '')) + '">' +
          escapeHtml(qtyDisplay + (defaultUnit ? ' ' + defaultUnit : '')) +
        '</td>' +
        '<td class="st-approx-price" data-sort-value="' + escapeHtml(priceRaw === '' || priceRaw == null ? '' : String(priceRaw)) + '">' +
          (priceDisplay ? ('₹' + escapeHtml(priceDisplay)) : '—') +
        '</td>' +
        '<td class="pl-col-actions"><div class="act-grp">' +
          '<a href="' + escapeHtml(editHref) + '" class="act-btn edit" data-tip="Edit" aria-label="Edit ' + escapeHtml(productName) + '">' +
            '<svg viewBox="0 0 24 24" aria-hidden="true"><use href="#st-icon-edit"/></svg></a>' +
          '<button type="button" class="act-btn del" data-tip="Delete" aria-label="Delete ' + escapeHtml(productName) + '"' +
            ' data-st-product-delete data-delete-url="' + escapeHtml(deleteUrl) + '"' +
            ' data-product-id="' + escapeHtml(productId) + '" data-product-name="' + escapeHtml(productName) + '">' +
            '<svg viewBox="0 0 24 24" aria-hidden="true"><use href="#st-icon-del"/></svg></button>' +
        '</div></td>';
      frag.appendChild(tr);
    });
    if (row.parentNode) row.parentNode.insertBefore(frag, row.nextSibling);
  }

  function setProductPackRowsVisible(productId, open) {
    if (!productId) return;
    var table = document.getElementById('st-products-table');
    var main = table && table.querySelector('tbody tr[data-st-product-row][data-product-id="' + productId + '"]');
    if (main) ensureProductPackRows(main);
    var packs = document.querySelectorAll(
      '#st-products-table tr.st-product-pack-row[data-pack-parent="' + productId + '"]'
    );
    packs.forEach(function (packRow) {
      if (open) packRow.removeAttribute('hidden');
      else packRow.setAttribute('hidden', '');
    });
  }

  function toggleProductPackRow(row) {
    if (!row || row.getAttribute('data-has-packs') !== '1') return;
    var productId = row.getAttribute('data-product-id');
    if (!productId) return;
    var open = row.getAttribute('aria-expanded') !== 'true';
    row.setAttribute('aria-expanded', open ? 'true' : 'false');
    row.classList.toggle('is-packs-open', open);
    var badge = row.querySelector('.st-pack-badge');
    if (badge) badge.classList.toggle('is-open', open);
    setProductPackRowsVisible(productId, open);
  }

  window.toggleProductPackRow = toggleProductPackRow;

  function initProductPackRowToggle() {
    var table = document.getElementById('st-products-table');
    if (!table || table.getAttribute('data-st-pack-toggle-bound') === '1') return;
    table.setAttribute('data-st-pack-toggle-bound', '1');

    table.addEventListener('click', function (e) {
      if (e.target && e.target.closest && e.target.closest('.act-grp a, a.act-btn, button.act-btn')) return;
      var row = e.target && e.target.closest
        ? e.target.closest('tr[data-st-product-row][data-has-packs="1"]')
        : null;
      if (!row || !table.contains(row)) return;
      e.preventDefault();
      toggleProductPackRow(row);
    });

    table.addEventListener('keydown', function (e) {
      if (e.key !== 'Enter' && e.key !== ' ') return;
      var row = e.target && e.target.closest
        ? e.target.closest('tr[data-st-product-row][data-has-packs="1"]')
        : null;
      if (!row || e.target !== row) return;
      e.preventDefault();
      toggleProductPackRow(row);
    });
  }

  function updateProductMasterCount(visibleOverride, totalOverride) {
    var countEl = document.getElementById('st-product-count');
    var table = document.getElementById('st-products-table');
    if (!countEl || !table) return;
    var rows = Array.from(table.querySelectorAll('tbody tr[data-sort-row]'));
    var total = typeof totalOverride === 'number' ? totalOverride : rows.length;
    var visible = typeof visibleOverride === 'number'
      ? visibleOverride
      : rows.filter(function (row) { return !row.hidden; }).length;
    if (visible === total) {
      countEl.textContent = visible + ' product' + (visible === 1 ? '' : 's');
    } else {
      countEl.textContent = visible + ' of ' + total + ' product' + (total === 1 ? '' : 's');
    }
    var tableWrap = table.closest('.pl-table-wrap');
    var emptyEl = document.getElementById('st-products-search-empty');
    var searchInput = document.getElementById('st-product-search');
    var needle = searchInput ? String(searchInput.value || '').trim() : '';
    if (emptyEl) emptyEl.hidden = !(needle && visible === 0);
    if (tableWrap) {
      if (rows.length === 0) {
        tableWrap.hidden = true;
        if (emptyEl) {
          emptyEl.hidden = false;
          var title = emptyEl.querySelector('strong');
          if (title) title.textContent = 'No products yet';
        }
      } else {
        tableWrap.hidden = !!(needle && visible === 0);
      }
    }
  }

  function removeProductMasterRows(productId) {
    if (!productId) return;
    var table = document.getElementById('st-products-table');
    if (!table) return;
    var main = table.querySelector('tbody tr[data-st-product-row][data-product-id="' + productId + '"]');
    if (main) main.remove();
    Array.from(table.querySelectorAll(
      'tbody tr.st-product-pack-row[data-pack-parent="' + productId + '"]'
    )).forEach(function (packRow) { packRow.remove(); });
    if (typeof table.__stProductApplyPage === 'function') table.__stProductApplyPage();
    else updateProductMasterCount();
  }

  function initProductMasterDelete() {
    if (document.documentElement.getAttribute('data-st-product-delete-bound') === '1') return;
    document.documentElement.setAttribute('data-st-product-delete-bound', '1');
    document.addEventListener('click', function (e) {
      var btn = e.target && e.target.closest
        ? e.target.closest('[data-st-product-delete]')
        : null;
      if (!btn) return;
      e.preventDefault();
      e.stopPropagation();
      if (typeof e.stopImmediatePropagation === 'function') e.stopImmediatePropagation();
      var productId = btn.getAttribute('data-product-id') || '';
      var productName = btn.getAttribute('data-product-name') || 'this product';
      var href = btn.getAttribute('data-delete-url') || btn.getAttribute('href') || '';
      if (!href || !productId) return;
      if (!window.confirm('Delete ' + productName + '? This cannot be undone.')) return;
      if (btn.getAttribute('data-st-deleting') === '1') return;
      btn.setAttribute('data-st-deleting', '1');
      btn.setAttribute('aria-disabled', 'true');
      if ('disabled' in btn) btn.disabled = true;
      fetch(href, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          Accept: 'application/json',
          'X-Requested-With': 'XMLHttpRequest'
        }
      })
        .then(function (res) {
          return res.json().then(function (data) {
            return { ok: res.ok, status: res.status, data: data || {} };
          }).catch(function () {
            return { ok: false, status: res.status, data: {} };
          });
        })
        .then(function (result) {
          if (!result.ok || !result.data.ok) {
            window.alert((result.data && result.data.error) || 'Could not delete product.');
            btn.removeAttribute('data-st-deleting');
            btn.removeAttribute('aria-disabled');
            if ('disabled' in btn) btn.disabled = false;
            return;
          }
          removeProductMasterRows(String(result.data.product_id || productId));
        })
        .catch(function () {
          window.alert('Could not delete product.');
          btn.removeAttribute('data-st-deleting');
          btn.removeAttribute('aria-disabled');
          if ('disabled' in btn) btn.disabled = false;
        });
    }, true);
  }

  function initProductMasterSearch() {
    var table = document.getElementById('st-products-table');
    if (!table || table.getAttribute('data-st-product-list-bound') === '1') return;
    table.setAttribute('data-st-product-list-bound', '1');

    var searchInput = document.getElementById('st-product-search');
    var searchChip =
      document.getElementById('st-product-search-chip') ||
      (searchInput && searchInput.closest('.st-product-search-chip, .pl-search-chip'));
    var clearBtn = document.getElementById('st-product-search-clear');
    var emptyEl = document.getElementById('st-products-search-empty');
    var tableWrap = table.closest('.pl-table-wrap');
    var tbody = table.tBodies[0];
    var headers = Array.from(table.querySelectorAll('th.pl-sortable'));
    var searchTimer = 0;

    function productRows() {
      return Array.from(table.querySelectorAll('tbody tr[data-sort-row]'));
    }

    function packRowsFor(pid) {
      return Array.from(table.querySelectorAll(
        'tbody tr.st-product-pack-row[data-pack-parent="' + pid + '"]'
      ));
    }

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

    function sortBy(th, forceAscending) {
      if (!tbody || !th) return;
      var key = th.getAttribute('data-sort') || '';
      var type = th.getAttribute('data-sort-type') || 'text';
      var colIndex = Array.from(th.parentNode.children).indexOf(th);
      if (colIndex < 0) return;

      var state = table.__stSortState || { activeKey: '', ascending: true };
      if (forceAscending === true) {
        state.activeKey = key;
        state.ascending = true;
      } else if (forceAscending === false) {
        state.activeKey = key;
        state.ascending = false;
      } else if (state.activeKey === key) {
        state.ascending = !state.ascending;
      } else {
        state.activeKey = key;
        state.ascending = true;
      }
      table.__stSortState = state;

      var rows = productRows();
      rows.sort(function (a, b) {
        var av = cellSortValue(a, colIndex, type);
        var bv = cellSortValue(b, colIndex, type);
        var cmp = 0;
        if (type === 'number') cmp = av - bv;
        else cmp = String(av).localeCompare(String(bv), undefined, { numeric: true, sensitivity: 'base' });
        return state.ascending ? cmp : -cmp;
      });
      rows.forEach(function (row) {
        tbody.appendChild(row);
        var pid = row.getAttribute('data-product-id');
        if (!pid) return;
        packRowsFor(pid).forEach(function (packRow) { tbody.appendChild(packRow); });
      });

      headers.forEach(function (header) {
        header.classList.remove('is-sorted-asc', 'is-sorted-desc');
        header.setAttribute('aria-sort', 'none');
      });
      th.classList.add(state.ascending ? 'is-sorted-asc' : 'is-sorted-desc');
      th.setAttribute('aria-sort', state.ascending ? 'ascending' : 'descending');
      applyFilter();
    }

    table.__stSortBy = sortBy;

    headers.forEach(function (th) {
      th.addEventListener('click', function () { sortBy(th); });
      th.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          sortBy(th);
        }
      });
    });

    function applyFilter() {
      var needle = searchInput ? String(searchInput.value || '').trim().toLowerCase() : '';
      if (searchChip) searchChip.classList.toggle('is-active', !!needle);
      if (clearBtn) clearBtn.hidden = !needle;

      var rows = productRows();
      var visible = 0;
      rows.forEach(function (row) {
        var match = !needle
          || String(row.getAttribute('data-search') || '').indexOf(needle) !== -1;
        row.hidden = !match;
        if (match) visible += 1;
        var pid = row.getAttribute('data-product-id');
        if (!pid) return;
        var expanded = match && row.getAttribute('aria-expanded') === 'true';
        if (expanded) ensureProductPackRows(row);
        packRowsFor(pid).forEach(function (packRow) {
          packRow.hidden = !expanded;
        });
      });

      updateProductMasterCount(visible, rows.length);
      if (emptyEl) emptyEl.hidden = !(needle && visible === 0);
      if (tableWrap) tableWrap.hidden = !!(needle && visible === 0);
    }

    table.__stProductApplyPage = applyFilter;

    function scheduleSearch() {
      if (searchTimer) window.clearTimeout(searchTimer);
      searchTimer = window.setTimeout(function () {
        searchTimer = 0;
        applyFilter();
      }, 80);
    }

    if (searchInput && searchInput.getAttribute('data-st-search-bound') !== '1') {
      searchInput.setAttribute('data-st-search-bound', '1');
      searchInput.addEventListener('input', scheduleSearch);
      searchInput.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') {
          searchInput.value = '';
          applyFilter();
          searchInput.blur();
        }
        if (e.key === 'Enter') e.preventDefault();
      });
    }
    if (clearBtn) {
      clearBtn.addEventListener('click', function (e) {
        e.preventDefault();
        if (searchInput) searchInput.value = '';
        applyFilter();
        if (searchInput) searchInput.focus();
      });
    }

    applyFilter();
  }

  window.closeProductModal = function closeProductModal(opts) {
    var modal = document.getElementById('st-product-modal');
    if (!modal) return;
    opts = opts || {};
    // Closing with content auto-saves (Done / backdrop / Escape), unless discard.
    if (!opts.discard && productFormHasContent()) {
      window.doneProductModal();
      return;
    }
    window.closeCategoryModal();
    window.closeUnitModal();
    var wasEditing = modal.getAttribute('data-st-editing') === '1'
      || !!(document.getElementById('st-product-id') || {}).value;
    modal.classList.remove('active');
    var qs = window.location.search || '';
    if (wasEditing && /[?&]edit=/.test(qs)) {
      navigateProductMasterList();
    } else if (/[?&]focus=form/.test(qs)) {
      navigateProductMasterList();
    }
  };

  function initProductMasterModal() {
    var modal = document.getElementById('st-product-modal');
    if (!modal) return;

    if (modal.getAttribute('data-st-variant-delegate') !== '1') {
      modal.setAttribute('data-st-variant-delegate', '1');
      modal.addEventListener('click', function (e) {
        var actionEl = e.target && e.target.closest ? e.target.closest('[data-st-action]') : null;
        if (!actionEl || !modal.contains(actionEl)) return;
        var action = actionEl.getAttribute('data-st-action');
        if (action === 'add-variant-row') {
          e.preventDefault();
          e.stopPropagation();
          addVariantRow();
        } else if (action === 'remove-variant-row') {
          e.preventDefault();
          e.stopPropagation();
          removeVariantRow(actionEl);
        }
      });
    }

    if (!document.documentElement.getAttribute('data-st-product-modal-bound')) {
      document.documentElement.setAttribute('data-st-product-modal-bound', '1');
      document.addEventListener('click', function (e) {
        var actionEl = e.target && e.target.closest ? e.target.closest('[data-st-action]') : null;
        if (!actionEl) {
          var unitModal = document.getElementById('st-unit-modal');
          if (unitModal && e.target === unitModal) {
            window.closeUnitModal();
            return;
          }
          var catModal = document.getElementById('st-category-modal');
          if (catModal && e.target === catModal) {
            window.closeCategoryModal();
            return;
          }
          var liveModal = document.getElementById('st-product-modal');
          if (liveModal && e.target === liveModal) {
            window.closeProductModal();
          }
          return;
        }
        var action = actionEl.getAttribute('data-st-action');
        if (action === 'open-product-modal') {
          e.preventDefault();
          window.openProductModal({ reset: true });
        } else if (action === 'done-product-modal') {
          e.preventDefault();
          window.doneProductModal();
        } else if (action === 'close-product-modal') {
          e.preventDefault();
          window.closeProductModal({ discard: true });
        } else if (action === 'add-variant-row') {
          e.preventDefault();
          addVariantRow();
        } else if (action === 'remove-variant-row') {
          e.preventDefault();
          removeVariantRow(actionEl);
        } else if (action === 'open-category-modal') {
          e.preventDefault();
          window.openCategoryModal();
        } else if (action === 'close-category-modal') {
          e.preventDefault();
          window.closeCategoryModal();
        } else if (action === 'open-unit-modal') {
          e.preventDefault();
          window.openUnitModal();
        } else if (action === 'close-unit-modal') {
          e.preventDefault();
          window.closeUnitModal();
        }
      });
      document.addEventListener('keydown', function (e) {
        if (e.key !== 'Escape') return;
        var unitModal = document.getElementById('st-unit-modal');
        if (unitModal && unitModal.classList.contains('active')) {
          window.closeUnitModal();
          return;
        }
        var catModal = document.getElementById('st-category-modal');
        if (catModal && catModal.classList.contains('active')) {
          window.closeCategoryModal();
          return;
        }
        var openModal = document.getElementById('st-product-modal');
        if (openModal && openModal.classList.contains('active')) {
          window.closeProductModal();
        }
      });
    }

    if (modal.classList.contains('active')) {
      if (typeof window.initEpListboxes === 'function') {
        window.initEpListboxes();
      }
    }

    var addCatBtn = document.getElementById('st-add-category-btn');
    if (addCatBtn && addCatBtn.getAttribute('data-st-cat-bound') !== '1') {
      addCatBtn.setAttribute('data-st-cat-bound', '1');
      addCatBtn.addEventListener('click', function (e) {
        e.preventDefault();
        window.openCategoryModal();
      });
    }

    var addUnitBtn = document.getElementById('st-add-unit-btn');
    if (addUnitBtn && addUnitBtn.getAttribute('data-st-unit-bound') !== '1') {
      addUnitBtn.setAttribute('data-st-unit-bound', '1');
      addUnitBtn.addEventListener('click', function (e) {
        e.preventDefault();
        window.openUnitModal();
      });
    }

    var openProdBtn = document.getElementById('st-open-product-modal');
    if (openProdBtn && openProdBtn.getAttribute('data-st-prod-bound') !== '1') {
      openProdBtn.setAttribute('data-st-prod-bound', '1');
      openProdBtn.addEventListener('click', function (e) {
        e.preventDefault();
        window.openProductModal({ reset: true });
      });
    }

    var addVariantBtn = document.getElementById('st-add-variant-btn');
    if (addVariantBtn && addVariantBtn.getAttribute('data-st-variant-bound') !== '1') {
      addVariantBtn.setAttribute('data-st-variant-bound', '1');
      addVariantBtn.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        addVariantRow();
      });
    }

    var catForm = document.getElementById('st-add-category-form');
    if (catForm && catForm.getAttribute('data-bound') !== '1') {
      catForm.setAttribute('data-bound', '1');
      catForm.addEventListener('submit', function (e) {
        var nameEl = document.getElementById('st-category-name');
        var name = ((nameEl && nameEl.value) || '').trim();
        if (!name) {
          e.preventDefault();
          var errEl = document.getElementById('st-category-modal-err');
          if (errEl) {
            errEl.textContent = 'Category name is required.';
            errEl.style.display = 'block';
          }
          window.openCategoryModal();
          if (nameEl) nameEl.focus();
          return;
        }
        if (nameEl) nameEl.value = name;
      });
    }

    var unitForm = document.getElementById('st-add-unit-form');
    if (unitForm && unitForm.getAttribute('data-bound') !== '1') {
      unitForm.setAttribute('data-bound', '1');
      unitForm.addEventListener('submit', function (e) {
        var nameEl = document.getElementById('st-unit-name');
        var name = ((nameEl && nameEl.value) || '').trim();
        if (!name) {
          e.preventDefault();
          var errEl = document.getElementById('st-unit-modal-err');
          if (errEl) {
            errEl.textContent = 'Unit name is required.';
            errEl.style.display = 'block';
          }
          window.openUnitModal();
          if (nameEl) nameEl.focus();
          return;
        }
        if (nameEl) nameEl.value = name;
      });
    }
  }

  function initIndentListSearch() {
    var searchInput = document.getElementById('st-indent-search');
    if (!searchInput || searchInput.getAttribute('data-st-search-bound') === '1') return;
    searchInput.setAttribute('data-st-search-bound', '1');
    var searchChip = searchInput.closest('.st-indent-search-chip');
    var countEl = document.getElementById('st-indent-list-count');
    var poPage = document.querySelector('[data-st-po-page]');
    var tables = Array.from(document.querySelectorAll('.st-po-search-table'));
    if (!tables.length) {
      var single = document.getElementById('st-indent-list-table');
      if (single) tables = [single];
    }
    var emptyEl = document.getElementById('st-indent-search-empty');

    function applyIndentSearch() {
      var needle = String(searchInput.value || '').trim().toLowerCase();
      if (searchChip) searchChip.classList.toggle('is-active', !!needle);
      if (!tables.length) return;
      var totalVisible = 0;
      tables.forEach(function (table) {
        var rows = Array.from(table.querySelectorAll('tbody tr[data-sort-row]'));
        var visible = 0;
        rows.forEach(function (row) {
          var hay = String(row.getAttribute('data-search') || row.textContent || '').toLowerCase();
          var match = !needle || hay.indexOf(needle) !== -1;
          row.hidden = !match;
          if (match) visible += 1;
        });
        totalVisible += visible;
        var block = table.getAttribute('data-st-po-block') || '';
        var blockCount = block
          ? document.querySelector('[data-st-po-block-count="' + block + '"]')
          : null;
        if (blockCount) blockCount.textContent = String(visible);
        else if (countEl && tables.length === 1) countEl.textContent = String(visible);
        var tableWrap = table.closest('.st-detail-table-wrap');
        var blockEmpty = block
          ? document.querySelector('[data-st-po-search-empty="' + block + '"]')
          : emptyEl;
        if (blockEmpty) blockEmpty.hidden = !(needle && visible === 0);
        if (tableWrap) tableWrap.hidden = !!(needle && visible === 0 && rows.length);
      });
      if (countEl && tables.length === 1 && !poPage) {
        countEl.textContent = String(totalVisible);
      }
      if (emptyEl && tables.length === 1) {
        emptyEl.hidden = !(needle && totalVisible === 0);
      }
    }

    searchInput.addEventListener('input', applyIndentSearch);
    searchInput.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') {
        searchInput.value = '';
        applyIndentSearch();
        searchInput.blur();
      }
      if (e.key === 'Enter') e.preventDefault();
    });
    applyIndentSearch();
  }

  function initStockSearch() {
    var searchInput = document.getElementById('st-stock-search');
    if (!searchInput) return;

    function getPage() { return document.getElementById('st-stock-page'); }
    function getTable() { return document.getElementById('st-stock-table'); }

    function getCategory() {
      var el = document.getElementById('st-stock-category');
      return el ? String(el.value || 'all').toLowerCase() : 'all';
    }

    function getStatus() {
      var el = document.getElementById('st-stock-status');
      return el ? String(el.value || 'all').toLowerCase() : 'all';
    }

    function setStockStatusFilter(status) {
      var next = String(status || 'all').toLowerCase();
      var root = document.getElementById('st-stock-status-listbox');
      var input = document.getElementById('st-stock-status');
      var valueEl = document.getElementById('st-stock-status-value');
      var option = root && root.querySelector('.se-filter-listbox-option[data-value="' + next + '"]');
      var label = option
        ? String(option.getAttribute('data-label') || option.textContent || '').trim()
        : (next === 'out' ? 'Out' : 'All statuses');
      if (input) input.value = next;
      if (valueEl) {
        valueEl.textContent = label;
        valueEl.classList.remove('is-placeholder', 'staff-supplier-placeholder');
      }
      if (root) {
        root.querySelectorAll('.se-filter-listbox-option').forEach(function (opt) {
          var on = String(opt.getAttribute('data-value') || '') === next;
          opt.classList.toggle('is-selected', on);
          opt.setAttribute('aria-selected', on ? 'true' : 'false');
        });
      }
      syncOutOfStockButton();
      applyStockFilters();
    }

    function syncOutOfStockButton() {
      var btn = document.getElementById('st-stock-out-filter');
      if (!btn) return;
      var active = getStatus() === 'out';
      btn.setAttribute('aria-pressed', active ? 'true' : 'false');
      btn.title = active ? 'Show all stock items' : 'Show only out-of-stock items';
    }

    function syncStockExportLink() {
      var link = document.getElementById('st-stock-export');
      if (!link || !link.href) return;
      try {
        var url = new URL(link.href, window.location.origin);
        var searchEl = document.getElementById('st-stock-search');
        var category = getCategory();
        var status = getStatus();
        var q = String((searchEl && searchEl.value) || '').trim();
        if (category && category !== 'all') url.searchParams.set('category', category);
        else url.searchParams.delete('category');
        if (status && status !== 'all') url.searchParams.set('status', status);
        else url.searchParams.delete('status');
        if (q) url.searchParams.set('q', q);
        else url.searchParams.delete('q');
        link.href = url.pathname + url.search;
      } catch (err) {}
    }

    function formatQty(n) {
      if (!isFinite(n)) return '0';
      var rounded = Math.round(n * 100) / 100;
      if (Math.abs(rounded - Math.round(rounded)) < 0.0001) return String(Math.round(rounded));
      return String(rounded);
    }

    function formatValue(n) {
      if (!isFinite(n)) return '—';
      return '₹' + Math.round(n).toLocaleString('en-IN');
    }

    function matchedRows() {
      var table = getTable();
      var searchEl = document.getElementById('st-stock-search');
      if (!table) return [];
      var needle = String((searchEl && searchEl.value) || '').trim().toLowerCase();
      var category = getCategory();
      var status = getStatus();
      return Array.from(table.querySelectorAll('tbody tr[data-sort-row]')).filter(function (row) {
        var hay = String(row.getAttribute('data-search') || row.textContent || '').toLowerCase();
        var searchOk = !needle || hay.indexOf(needle) !== -1;
        var cat = String(row.getAttribute('data-category') || '').toLowerCase();
        var categoryOk = category === 'all' || cat === category;
        var rowStatus = String(row.getAttribute('data-status') || '').toLowerCase();
        var statusOk = status === 'all' || rowStatus === status;
        return searchOk && categoryOk && statusOk;
      });
    }

    function updateKpis(rows) {
      var available = 0;
      var low = 0;
      var out = 0;
      var value = 0;
      var hasValue = false;
      rows.forEach(function (row) {
        var qty = parseFloat(row.getAttribute('data-qty') || '0') || 0;
        var status = String(row.getAttribute('data-status') || '');
        var priceRaw = row.getAttribute('data-price');
        available += qty;
        if (status === 'out') out += 1;
        else if (status === 'low') low += 1;
        if (priceRaw !== null && priceRaw !== '') {
          var price = parseFloat(priceRaw);
          if (isFinite(price)) {
            hasValue = true;
            value += qty * price;
          }
        }
      });
      var setText = function (id, text) {
        var el = document.getElementById(id);
        if (el) el.textContent = text;
      };
      setText('st-stock-kpi-items', String(rows.length));
      setText('st-stock-kpi-available', formatQty(available));
      setText('st-stock-kpi-low', String(low));
      setText('st-stock-kpi-out', String(out));
      setText('st-stock-kpi-value', hasValue ? formatValue(value) : '—');
    }

    function applyStockFilters() {
      var table = getTable();
      var searchEl = document.getElementById('st-stock-search');
      var searchChip = searchEl && searchEl.closest('.st-stock-search-chip');
      var countEl = document.getElementById('st-stock-count');
      var tableWrap = document.getElementById('st-stock-table-wrap') || (table && table.closest('.pl-table-wrap, .st-table-wrap'));
      var emptyEl = document.getElementById('st-stock-search-empty');
      var needle = String((searchEl && searchEl.value) || '').trim().toLowerCase();
      if (searchChip) searchChip.classList.toggle('is-active', !!needle);
      if (!table) return;

      var rows = matchedRows();
      var total = rows.length;
      Array.from(table.querySelectorAll('tbody tr[data-sort-row]')).forEach(function (row) {
        row.hidden = true;
      });
      rows.forEach(function (row) {
        row.hidden = false;
      });

      if (countEl) countEl.textContent = total + ' item' + (total === 1 ? '' : 's');
      var noMatch = total === 0 && (!!needle || getCategory() !== 'all' || getStatus() !== 'all');
      if (emptyEl) emptyEl.hidden = !noMatch;
      if (tableWrap) tableWrap.hidden = !!noMatch;
      updateKpis(rows);
      syncStockExportLink();
    }

    window.stStockApplyFilters = applyStockFilters;
    window.stStockCategoryChanged = function () { applyStockFilters(); };
    window.stStockStatusChanged = function () {
      syncOutOfStockButton();
      applyStockFilters();
    };
    window.stStockSetStatusFilter = setStockStatusFilter;

    if (searchInput.getAttribute('data-st-search-bound') !== '1') {
      searchInput.setAttribute('data-st-search-bound', '1');
      searchInput.addEventListener('input', function () { applyStockFilters(); });
      searchInput.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') {
          searchInput.value = '';
          applyStockFilters();
          searchInput.blur();
        }
        if (e.key === 'Enter') e.preventDefault();
      });
    }

    if (!window.__stStockClickBound) {
      window.__stStockClickBound = true;
      document.addEventListener('click', function (e) {
        if (!document.getElementById('st-stock-page')) return;
        var t = e.target;
        if (!t || !t.closest) return;
        var outBtn = t.closest('#st-stock-out-filter');
        if (outBtn) {
          e.preventDefault();
          setStockStatusFilter(getStatus() === 'out' ? 'all' : 'out');
          return;
        }
      });
    }

    syncOutOfStockButton();
    applyStockFilters();
  }

  window.initStoresPage = function () {
    bindStoresEvents();
    cleanupHostedIndentModals();
    initStoresSortableTables();
    initStockInward();
    initStFlashAutoDismiss();
    initProductMasterModal();
    initProductMasterSearch();
    initProductMasterDelete();
    initProductPackRowToggle();
    initIndentListSearch();
    initStockSearch();
    if (typeof window.initStockAudit === 'function') window.initStockAudit();
    syncIndentLineTotals(document.getElementById('st-indent-form'));
    syncIndentSendButtons();
    document.querySelectorAll('.st-line.has-packs').forEach(function (line) {
      syncUnitForPack(line);
    });
    if (
      !document.getElementById('st-indent-view-modal')
      && !document.getElementById('st-indent-edit-modal')
      && !document.getElementById('st-reject-modal')
      && !document.getElementById('st-stores-ledger-modal')
      && !document.getElementById('st-ledger-pending-modal')
      && !document.getElementById('st-approvals-modal')
      && !document.getElementById('st-product-master-modal')
    ) {
      return;
    }
    bootIndentModals();
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', window.initStoresPage);
  } else {
    window.initStoresPage();
  }
})();
