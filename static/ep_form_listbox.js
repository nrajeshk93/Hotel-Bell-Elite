(function (global) {
  'use strict';

  function listEl(root){
    if (!root) return null;
    if (root.__epPortaledList && root.__epPortaledList.isConnected) {
      return root.__epPortaledList;
    }
    return root.querySelector('.se-filter-listbox');
  }

  function optionsWrapFor(root){
    var list = listEl(root);
    if (!list) return null;
    return list.querySelector('.ep-listbox-options') || list;
  }

  function portalHost(){
    return document.getElementById('de-fs-app') || document.body;
  }

  function portalFixedListbox(root, list){
    if (!root || !list) return;
    var host = portalHost();
    if (!host) return;
    if (!list.__epPortalHome) list.__epPortalHome = list.parentNode;
    if (list.parentNode !== host) host.appendChild(list);
    list.classList.add('ep-listbox-portaled');
    list.setAttribute('data-ep-listbox-portaled', '1');
    root.__epPortaledList = list;
    list.__epPortalRoot = root;
  }

  function unportalListbox(root, list){
    list = list || listEl(root);
    if (!list) return;
    var home = list.__epPortalHome;
    if (home && home.isConnected) {
      home.appendChild(list);
    } else if (root && root.isConnected) {
      root.appendChild(list);
    }
    list.classList.remove('ep-listbox-portaled');
    list.removeAttribute('data-ep-listbox-portaled');
    list.__epPortalHome = null;
    list.__epPortalRoot = null;
    if (root) root.__epPortaledList = null;
  }

  function scoreSearchOption(option, needle){
    if (!needle) return 0;
    var name = (option.getAttribute('data-name') || option.textContent || '').toLowerCase().trim();
    var terms = needle.split(/\s+/).filter(Boolean);
    var score = 0;
    for (var i = 0; i < terms.length; i++) {
      var term = terms[i];
      if (name === term) score += 120;
      else if (name.indexOf(term) === 0) score += 90;
      else if (name.indexOf(term) !== -1) score += 60;
      else return -1;
    }
    return score;
  }

  function isPinnedAllOption(option){
    var value = String(option.getAttribute('data-value') || '').trim().toLowerCase();
    // Empty = "All …" / placeholder; "all" and "both" are the shared All keys.
    if (!value || value === 'all' || value === 'both') return true;
    var label = String(
      option.getAttribute('data-label')
      || option.getAttribute('data-name')
      || option.textContent
      || ''
    ).trim().toLowerCase();
    return label === 'all' || label.indexOf('all ') === 0;
  }

  function filterSearchableOptions(root, query){
    var optionsWrap = optionsWrapFor(root);
    if (!optionsWrap) return;
    var needle = String(query || '').trim().toLowerCase();
    var options = Array.from(optionsWrap.querySelectorAll('.se-filter-listbox-option'));

    if (!needle) {
      options.sort(function(a, b){
        var aPin = isPinnedAllOption(a) || (isCountryPickerListbox(root) && a.classList.contains('is-selected'));
        var bPin = isPinnedAllOption(b) || (isCountryPickerListbox(root) && b.classList.contains('is-selected'));
        if (aPin && !bPin) return -1;
        if (bPin && !aPin) return 1;
        var aLabel = (a.getAttribute('data-name') || a.getAttribute('data-label') || a.textContent || '').trim();
        var bLabel = (b.getAttribute('data-name') || b.getAttribute('data-label') || b.textContent || '').trim();
        return aLabel.localeCompare(bLabel, undefined, { sensitivity: 'base', numeric: true });
      });
      options.forEach(function(option){
        option.classList.remove('is-filtered-out');
        optionsWrap.appendChild(option);
      });
      return;
    }

    var ranked = options.map(function(option){
      return { option: option, score: scoreSearchOption(option, needle) };
    }).filter(function(entry){
      return entry.score >= 0;
    });

    ranked.sort(function(a, b){
      return b.score - a.score
        || (a.option.getAttribute('data-label') || a.option.getAttribute('data-name') || '').localeCompare(
          b.option.getAttribute('data-label') || b.option.getAttribute('data-name') || '',
          undefined,
          { sensitivity: 'base', numeric: true }
        );
    });

    options.forEach(function(option){ option.classList.add('is-filtered-out'); });
    ranked.forEach(function(entry){
      entry.option.classList.remove('is-filtered-out');
      optionsWrap.appendChild(entry.option);
    });
    options.forEach(function(option){
      if (option.classList.contains('is-filtered-out')) optionsWrap.appendChild(option);
    });
  }

  function visibleOptions(root){
    var optionsWrap = optionsWrapFor(root);
    if (!optionsWrap) return [];
    return Array.from(optionsWrap.querySelectorAll('.se-filter-listbox-option:not(.is-filtered-out)'));
  }

  function isCombobox(root){
    return !!(root && root.hasAttribute('data-se-listbox-combobox'));
  }

  function comboboxInput(root){
    if (!root) return null;
    return root.querySelector('input.se-filter-chip-trigger, input.se-filter-chip-combobox');
  }

  function optionDisplayLabel(option){
    if (!option) return '';
    var labelled = String(option.getAttribute('data-label') || '').trim();
    if (labelled) return labelled;
    var title = option.querySelector(
      '.ep-listbox-option-title, .staff-supplier-option-name'
    );
    if (title) {
      var titled = String(title.textContent || '').replace(/\s+/g, ' ').trim();
      if (titled) return titled;
    }
    return String(option.textContent || '').replace(/\s+/g, ' ').trim();
  }

  function selectedOption(root){
    var list = listEl(root);
    if (list) {
      return (
        list.querySelector('.se-filter-listbox-option.is-selected') ||
        list.querySelector('.se-filter-listbox-option[aria-selected="true"]')
      );
    }
    return root
      ? root.querySelector('.se-filter-listbox-option.is-selected')
      : null;
  }

  function optionMatchingValue(root, value){
    var list = listEl(root);
    if (!list || value == null || value === '') return null;
    var wanted = String(value);
    var opts = list.querySelectorAll('.se-filter-listbox-option');
    for (var i = 0; i < opts.length; i++) {
      if (String(opts[i].getAttribute('data-value') || '') === wanted) return opts[i];
    }
    return null;
  }

  function searchEl(root){
    var list = listEl(root);
    return (list && list.querySelector('.ep-listbox-search')) ||
      (root && root.querySelector('.ep-listbox-search'));
  }

  var LISTBOX_CLOSE_MS = 200;

  function prefersReducedMotion(){
    try{
      return !!(global.matchMedia && global.matchMedia('(prefers-reduced-motion: reduce)').matches);
    } catch (err) {
      return false;
    }
  }

  function closeListbox(root, opts){
    if (!root) return;
    opts = opts || {};
    var trigger = root.querySelector('.se-filter-chip-trigger');
    var list = listEl(root);
    var search = searchEl(root);
    var wasOpen = root.classList.contains('is-open');
    var portaled = !!(list && list.classList.contains('ep-listbox-portaled'));
    /* Portaled panels use opacity:1 !important, so the close fade never shows —
       waiting LISTBOX_CLOSE_MS just delays the chosen label. */
    var immediate = !!(opts.immediate || portaled || prefersReducedMotion());
    root.classList.remove('is-open');
    if (trigger) trigger.setAttribute('aria-expanded', 'false');
    function finishHide(){
      root.classList.remove('is-closing');
      if (list) {
        list.hidden = true;
        unportalListbox(root, list);
        clearFixedListbox(list);
        resetListboxPanelSize(list);
        var emptyStatus = list.querySelector('.se-filter-listbox-status[data-ep-empty]');
        if (emptyStatus) emptyStatus.hidden = true;
      }
      if (root.hasAttribute('data-se-listbox-searchable')) {
        filterSearchableOptions(root, '');
      }
    }
    if (list && wasOpen && !immediate) {
      root.classList.add('is-closing');
      global.clearTimeout(root._epCloseTimer);
      root._epCloseTimer = global.setTimeout(finishHide, LISTBOX_CLOSE_MS);
    } else {
      global.clearTimeout(root._epCloseTimer);
      finishHide();
    }
    if (search) search.value = '';
    if (wasOpen && isCombobox(root)) {
      var combo = comboboxInput(root);
      var typed = combo ? String(combo.value || '').trim() : '';
      if (!typed) {
        var hidden = root.querySelector('input[type="hidden"]');
        var hadValue = !!(hidden && String(hidden.value || '').trim());
        if (list) {
          list.querySelectorAll('.se-filter-listbox-option').forEach(function(opt){
            opt.classList.remove('is-selected');
            opt.setAttribute('aria-selected', 'false');
          });
        }
        updateDisplay(root, '', '');
        if (hadValue) {
          var changeHandler = root.getAttribute('data-se-listbox-change');
          if (changeHandler && typeof window[changeHandler] === 'function') {
            window[changeHandler](root, '', '');
          }
        }
      } else {
        restoreComboboxLabel(root);
      }
    }
  }

  function restoreComboboxLabel(root){
    var input = comboboxInput(root);
    if (!input) return;
    var hidden = root.querySelector('input[type="hidden"]');
    var hiddenVal = hidden ? String(hidden.value || '').trim() : '';
    var selected = selectedOption(root) || optionMatchingValue(root, hiddenVal);
    var label = optionDisplayLabel(selected);
    if (!label) {
      var current = String(input.value || '').trim();
      /* Never show the stored id (e.g. "37") as the combobox caption. */
      label = current && current !== hiddenVal ? current : '';
    }
    input.value = label;
    input.classList.toggle('is-placeholder', !hiddenVal);
    if (root) root.classList.toggle('has-value', !!hiddenVal);
    if (label) input.setAttribute('title', label);
    else input.setAttribute('title', input.getAttribute('placeholder') || '');
  }

  function listboxRoots(selector){
    /* Match by attribute globally — do not require body.*-module classes.
       Soft-nav can keep a stale body class or script closure; scoping to
       ep/su/pos/hotel modules previously left Hotel check-in listboxes unbound. */
    return document.querySelectorAll(selector);
  }

  function closeAllListboxes(except){
    listboxRoots('[data-se-listbox].is-open').forEach(function(root){
      if (root !== except) closeListbox(root);
    });
  }

  /* transform/filter/perspective (and will-change:transform) make position:fixed
     relative to that ancestor while getBoundingClientRect stays viewport-based. */
  function hasFixedContainingBlockAncestor(el){
    var node = el && el.parentElement;
    while (node && node !== document.documentElement) {
      var style = window.getComputedStyle(node);
      if (!style) break;
      if (style.transform && style.transform !== 'none') return true;
      if (style.perspective && style.perspective !== 'none') return true;
      if (style.filter && style.filter !== 'none') return true;
      if (style.backdropFilter && style.backdropFilter !== 'none') return true;
      if ((style.willChange || '').indexOf('transform') !== -1) return true;
      if ((style.contain || '').indexOf('paint') !== -1 ||
          (style.contain || '').indexOf('layout') !== -1 ||
          (style.contain || '').indexOf('strict') !== -1 ||
          (style.contain || '').indexOf('content') !== -1) {
        return true;
      }
      node = node.parentElement;
    }
    return false;
  }

  function shouldUseFixedListbox(root){
    if (!root) return false;
    /* PO line supplier sits in overflow:auto group cards under a transformed
       workspace — fixed + getBoundingClientRect misaligns the panel so options
       cannot be chosen. Absolute under the chip (with overflow:visible when open)
       matches Indent product pickers. */
    if (root.classList.contains('st-po-line-supplier-listbox')) {
      return false;
    }
    /* POS invoice header table/order pills — fixed escapes sibling action-button overlap. */
    if (root.classList.contains('pos-inv-header-listbox')) {
      return true;
    }
    // Invoice meta fields keep absolute positioning under their chip.
    if (root.closest('#pos-invoice-page, .pos-inv-header, .pos-inv-header-actions, .pos-inv-meta')) {
      return false;
    }
    // Tables toolbar uses the same posFadeUp transform fill — fixed coords land elsewhere.
    if (root.closest('#pos-tables-page, .pos-tables-toolbar, .pos-status-filter-listbox')) {
      return false;
    }
    /* Menu item modal listboxes sit in a scrollable body — absolute menus get clipped.
       Fixed positioning escapes overflow so product/unit panels stay visible.
       Skip fixed when nested under Masters / transformed shells: fixed then uses
       that ancestor as containing block while getBoundingClientRect is viewport,
       so the panel lands far from the chip. */
    if (
      root.closest('#pos-menu-item-modal') &&
      (root.id === 'pos-menu-item-product-listbox' ||
        root.id === 'pos-menu-item-menu-type-listbox' ||
        root.id === 'pos-menu-item-category-listbox' ||
        root.classList.contains('pos-menu-unit-listbox') ||
        root.classList.contains('pos-menu-listbox') ||
        root.classList.contains('pos-menu-field-listbox') ||
        root.classList.contains('ep-combobox-listbox'))
    ) {
      if (root.closest('#md-master-modal, #st-product-master-modal')) return false;
      /* Modal box uses transform + overflow:hidden, so in-tree panels clip.
         Portal+fixed onto body / #de-fs-app escapes both. Do not skip just
         because the chip still has a transformed ancestor. */
      return true;
    }
    /* Product / category / unit overlays sit under a transformed workspace.
       Must run BEFORE the generic combobox+dialog rule — searchable Supplier
       listboxes are ep-combobox-listbox inside role=dialog, and fixed coords
       land nowhere near the chip. Absolute under the chip stays aligned. */
    if (root.closest('#st-product-modal, #st-category-modal, #st-unit-modal')) {
      return false;
    }
    if (root.classList.contains('ep-combobox-listbox') && root.closest('.modal-backdrop, .modal-overlay, .staff-credit-box, .pos-inv-modal, [role="dialog"]')) {
      return true;
    }
    if (root.classList.contains('ep-combobox-listbox') && root.closest('#credit-payment-filter-form, #purchase-ledger-filter-form')) {
      return true;
    }
    // Floor props + category modals keep overflow:visible — absolute under the chip stays
    // aligned. Fixed + transformed workspace/page ancestors rebases coords and collapses
    // the panel to a thin strip above the modal actions.
    if (root.closest('#pos-menu-item-modal, #pos-floor-props-modal, #pos-menu-cat-modal')) {
      return false;
    }
    if (root.classList.contains('ep-toolbar-listbox')) return true;
    // Indent edit / similar modals clip absolute menus via overflow:auto/hidden.
    if (root.classList.contains('ep-form-listbox') && root.closest('#st-indent-edit-modal, #st-indent-view-modal, #st-stores-ledger-modal, #st-ledger-pending-modal')) {
      return true;
    }
    /* Hotel New Check-In / Room Transfer / Edit Reservation — modal body scrolls and clips absolute menus. */
    if (
      root.classList.contains('ep-form-listbox') &&
      root.closest('#hrd-checkin-modal, #hrd-transfer-modal, #hr-transfer-modal, #hres-edit-modal, .hrd-modal, .hrd-dialog, .hr-dialog, .hres-dialog')
    ) {
      return true;
    }
    return false;
  }

  var COMPACT_PERIOD_ROWS = 4;

  function isCompactPeriodListbox(root){
    if (!root) return false;
    return !!(
      root.querySelector('input[type="hidden"][name="month"]') ||
      root.querySelector('input[type="hidden"][name="year"]')
    );
  }

  function isCountryPickerListbox(root){
    return !!(root && (
      root.classList.contains('hrd-form-listbox--code') ||
      root.classList.contains('hrd-form-listbox--countries')
    ));
  }

  function rotateSelectedFirst(list){
    if (!list) return;
    var wrap = list.querySelector('.ep-listbox-options') || list;
    var selected = wrap.querySelector('.se-filter-listbox-option.is-selected, .se-filter-listbox-option[aria-selected="true"]');
    if (!selected) return;
    var opts = Array.prototype.slice.call(wrap.querySelectorAll('.se-filter-listbox-option'));
    var idx = opts.indexOf(selected);
    if (idx <= 0) return;
    var i;
    for (i = idx; i < opts.length; i++) wrap.appendChild(opts[i]);
    for (i = 0; i < idx; i++) wrap.appendChild(opts[i]);
  }

  function compactPeriodMaxHeight(list){
    var opt = list.querySelector('.se-filter-listbox-option:not(.is-filtered-out)');
    var optH = (opt && opt.offsetHeight) ? opt.offsetHeight : 40;
    var pad = 12;
    try {
      var cs = global.getComputedStyle(list);
      pad = (parseFloat(cs.paddingTop) || 0) + (parseFloat(cs.paddingBottom) || 0);
    } catch (err) {}
    return Math.round(pad + COMPACT_PERIOD_ROWS * optH);
  }

  function positionFixedListbox(root, list){
    if (!root || !list || !shouldUseFixedListbox(root)) return;
    portalFixedListbox(root, list);
    var control = root.querySelector('.se-filter-chip-control') || root;
    var rect = control.getBoundingClientRect();
    var width = Math.max(rect.width, 140);
    if (isCountryPickerListbox(root)) {
      width = Math.max(width, 320);
    }
    var left = Math.min(rect.left, Math.max(8, window.innerWidth - width - 8));
    var spaceBelow = window.innerHeight - rect.bottom - 12;
    var spaceAbove = rect.top - 12;
    var compactPicker = isCompactPeriodListbox(root);
    if (compactPicker) rotateSelectedFirst(list);
    var openUp = compactPicker
      ? (spaceBelow < 180 && spaceAbove > spaceBelow)
      : (spaceBelow < 220 && spaceAbove > spaceBelow);
    var maxHeight = compactPicker
      ? Math.min(compactPeriodMaxHeight(list), Math.max(80, openUp ? spaceAbove : spaceBelow))
      : Math.min(320, Math.max(160, openUp ? spaceAbove : spaceBelow));
    if (isCountryPickerListbox(root)) {
      maxHeight = Math.min(360, Math.max(280, openUp ? spaceAbove : spaceBelow));
    }
    list.classList.toggle('ep-period-compact', compactPicker);
    list.style.position = 'fixed';
    list.style.left = left + 'px';
    list.style.right = 'auto';
    list.style.width = width + 'px';
    list.style.minWidth = width + 'px';
    list.style.maxHeight = maxHeight + 'px';
    list.style.zIndex = root.closest('#st-stores-ledger-modal, #st-ledger-pending-modal, #st-indent-edit-modal, #st-indent-view-modal, #st-product-modal, #st-category-modal, #st-unit-modal, #pos-menu-item-modal, #pl-add-purchase-modal, #sales-expense-modal, #hrd-checkin-modal, #hrd-transfer-modal, #hr-transfer-modal, #hres-edit-modal') ? '11250' : (root.classList.contains('pos-inv-header-listbox') ? '200' : '12050');
    if (openUp) {
      list.style.top = 'auto';
      list.style.bottom = (window.innerHeight - rect.top + 6) + 'px';
    } else {
      list.style.bottom = 'auto';
      list.style.top = (rect.bottom + 6) + 'px';
    }
  }

  function clearFixedListbox(list){
    if (!list) return;
    list.style.position = '';
    list.style.left = '';
    list.style.right = '';
    list.style.top = '';
    list.style.bottom = '';
    list.style.width = '';
    list.style.minWidth = '';
    list.style.maxHeight = '';
    list.style.zIndex = '';
    list.style.paddingBottom = '';
    list.classList.remove('ep-period-compact', 'ep-month-compact');
    list.scrollTop = 0;
  }

  function resetListboxPanelSize(list){
    if (!list) return;
    list.style.maxHeight = '';
    list.style.paddingBottom = '';
  }

  /** Keep the selected row in view without hiding earlier options above the fold. */
  function scrollSelectedToTop(list){
    if (!list) return;
    var root = list.__epPortalRoot;
    if (isCompactPeriodListbox(root)) {
      rotateSelectedFirst(list);
      list.style.paddingBottom = '';
      var periodCap = compactPeriodMaxHeight(list);
      var periodContent = list.scrollHeight;
      list.style.maxHeight = (periodContent <= periodCap + 1 ? periodContent : periodCap) + 'px';
      list.scrollTop = 0;
      return;
    }
    var selected = list.querySelector('.se-filter-listbox-option.is-selected, .se-filter-listbox-option[aria-selected="true"]');
    if (!selected || selected.classList.contains('is-filtered-out')) {
      resetListboxPanelSize(list);
      return;
    }
    list.style.paddingBottom = '';
    requestAnimationFrame(function(){
      var cssCap = parseFloat(list.style.maxHeight);
      var naturalCap = 320;
      var cap = (cssCap && cssCap >= 48) ? cssCap : Math.max(list.clientHeight || 0, naturalCap);
      var options = list.querySelectorAll('.se-filter-listbox-option:not(.is-filtered-out)');
      if (!options.length) {
        resetListboxPanelSize(list);
        return;
      }

      var contentH = list.scrollHeight;
      /* Short list: hug content — do not force a tall empty tray. */
      if (contentH <= cap + 1) {
        if (contentH < 40) {
          resetListboxPanelSize(list);
          list.scrollTop = 0;
          return;
        }
        list.style.maxHeight = contentH + 'px';
        list.scrollTop = 0;
        return;
      }

      list.style.paddingBottom = '';
      list.style.maxHeight = cap + 'px';
      try {
        selected.scrollIntoView({ block: 'nearest', inline: 'nearest' });
      } catch (err) {
        var scroller = list.querySelector('.ep-listbox-options') || list;
        var topPad = 0;
        var target = Math.max(0, selected.offsetTop - topPad);
        var naturalMax = Math.max(0, list.scrollHeight - cap);
        scroller.scrollTop = Math.min(target, naturalMax);
      }
    });
  }

  function syncListboxEmptyState(root){
    var list = listEl(root);
    if (!list) return;
    var optionsWrap = optionsWrapFor(root) || list;
    var visible = visibleOptions(root);
    var status = list.querySelector('.se-filter-listbox-status[data-ep-empty]');
    if (visible.length) {
      if (status) status.hidden = true;
      return;
    }
    if (!status) {
      status = document.createElement('div');
      status.className = 'se-filter-listbox-status';
      status.setAttribute('data-ep-empty', '1');
      status.setAttribute('role', 'status');
      optionsWrap.appendChild(status);
    }
    status.hidden = false;
    status.textContent = root.hasAttribute('data-se-listbox-searchable')
      ? 'No matches'
      : 'No options';
  }

  function openListbox(root, opts){
    if (!root || root.classList.contains('is-disabled')) return;
    opts = opts || {};
    var dateWrapId = root.getAttribute('data-se-listbox-close-date-wrap');
    if (dateWrapId && global.SalesDateRangePicker && typeof global.SalesDateRangePicker.closeIfOpen === 'function') {
      global.SalesDateRangePicker.closeIfOpen(dateWrapId);
    }
    closeAllListboxes(root);
    try {
      document.dispatchEvent(new CustomEvent('ep-listbox-opened', { detail: { root: root } }));
    } catch (err) {}
    var trigger = root.querySelector('.se-filter-chip-trigger');
    var list = listEl(root);
    var search = searchEl(root);
    var combo = comboboxInput(root);
    global.clearTimeout(root._epCloseTimer);
    root.classList.remove('is-closing');
    if (list) {
      list.hidden = false;
      resetListboxPanelSize(list);
      if (isCompactPeriodListbox(root)) rotateSelectedFirst(list);
      if (shouldUseFixedListbox(root)) {
        positionFixedListbox(root, list);
      } else {
        clearFixedListbox(list);
      }
    }
    /* Open immediately for comboboxes / indent lines so opacity isn't 0 during
       measure (delayed is-open caused a locked ~14px empty panel). Header
       filter chips also need an immediate paint. */
    if (
      isCombobox(root) ||
      root.classList.contains('ep-toolbar-listbox') ||
      root.closest(
        '.st-indent-page, #st-indent-edit-modal, #st-indent-form, ' +
        '#room-transfer-filter-form, #purchase-ledger-filter-form, #credits-dashboard-filter-form, ' +
        '#pos-menu-item-modal'
      )
    ) {
      root.classList.add('is-open');
    } else {
      global.requestAnimationFrame(function () {
        root.classList.add('is-open');
      });
    }
    if (trigger) trigger.setAttribute('aria-expanded', 'true');
    if (list) {
      if (root.hasAttribute('data-se-listbox-searchable')) {
        var query = '';
        if (isCombobox(root) && combo && opts.keepQuery) {
          query = combo.value;
        }
        filterSearchableOptions(root, query);
        syncListboxEmptyState(root);
        if (!isCombobox(root) || !opts.keepQuery) {
          if (isCountryPickerListbox(root)) {
            var wrap = optionsWrapFor(root);
            list.scrollTop = 0;
            if (wrap && wrap !== list) wrap.scrollTop = 0;
          } else {
            scrollSelectedToTop(list);
          }
        }
        if (isCombobox(root)) {
          if (combo && opts.selectAll) {
            var hidden = root.querySelector('input[type="hidden"]');
            var hasValue = !!(hidden && String(hidden.value || '').trim());
            if (!hasValue) {
              // Empty field: clear so the first click is ready to type-to-search
              // (do not leave placeholder copy in the value for the user to delete).
              combo.value = '';
              combo.classList.add('is-placeholder');
            } else {
              try { combo.select(); } catch (err) {}
            }
          }
        } else if (search) {
          search.value = '';
          search.focus();
        }
      } else {
        var selected =
          list.querySelector('.se-filter-listbox-option[aria-selected="true"]:not([hidden])') ||
          list.querySelector('.se-filter-listbox-option:not([hidden])');
        scrollSelectedToTop(list);
        if (selected) {
          try { selected.focus({ preventScroll: true }); } catch (err) {}
        }
      }
    }
  }

  function toggleListbox(root){
    if (!root) return;
    if (root.classList.contains('is-open')) closeListbox(root);
    else openListbox(root, { selectAll: isCombobox(root) });
  }

  function updateDisplay(root, label, value){
    var valueEl = root.querySelector('.se-filter-chip-value');
    var input = root.querySelector('input[type="hidden"]');
    var combo = comboboxInput(root);
    if (input) input.value = value;
    if (combo) {
      // Keep real labels in the value; never copy placeholder text into the input.
      combo.value = value ? (label || '') : '';
      combo.classList.toggle('is-placeholder', !value);
      var tip = value ? (label || '') : (combo.getAttribute('placeholder') || '');
      if (tip) combo.setAttribute('title', tip);
      else combo.removeAttribute('title');
    }
    if (valueEl) {
      valueEl.textContent = label;
      if (value) {
        valueEl.classList.remove('is-placeholder', 'staff-supplier-placeholder');
      } else {
        valueEl.classList.add('is-placeholder', 'staff-supplier-placeholder');
      }
    }
    if (root) root.classList.toggle('has-value', !!value);
  }

  function isOptionDisabled(option){
    return !!option && option.getAttribute('aria-disabled') === 'true';
  }

  function selectOption(root, option){
    if (
      !root ||
      !option ||
      option.hidden ||
      option.classList.contains('is-filtered-out') ||
      isOptionDisabled(option)
    ) return;
    var list = listEl(root);
    var value = option.getAttribute('data-value') || '';
    var label = optionDisplayLabel(option);
    updateDisplay(root, label, value);
    if (list) {
      list.querySelectorAll('.se-filter-listbox-option').forEach(function(opt){
        var on = opt === option;
        opt.classList.toggle('is-selected', on);
        opt.setAttribute('aria-selected', on ? 'true' : 'false');
      });
    }
    closeListbox(root, { immediate: true });

    var submitFormId = root.getAttribute('data-se-listbox-submit');
    if (submitFormId) {
      var form = document.getElementById(submitFormId);
      if (form) {
        // Prefer soft-submit helper so GET payroll filters keep the workspace shell.
        if (typeof window.deSoftSubmitForm === 'function' && window.deSoftSubmitForm(form)) return;
        // requestSubmit fires the submit event so Masters modal inject handlers can
        // intercept (native form.submit() does not).
        if (typeof form.requestSubmit === 'function') {
          form.requestSubmit();
        } else {
          form.submit();
        }
      }
      return;
    }

    var changeHandler = root.getAttribute('data-se-listbox-change');
    if (changeHandler && typeof window[changeHandler] === 'function') {
      window[changeHandler](root, value, label, option);
    }
  }

  function bindListbox(root){
    // Skip chips already owned by sales / purchase / credit-payment filter listbox scripts.
    if (!root || root.__epListboxBound || root.__suFilterListboxBound || root.__plFilterListboxBound) return;
    if (root.closest('#purchase-ledger-filter-form')) return;
    if (root.id === 'credit-payment-supplier-listbox') return;
    // Expense / tips modals own their searchable listboxes (custom GST / employee search).
    if (root.closest('#sales-expense-modal, #sales-tips-modal')) return;
    var trigger = root.querySelector('.se-filter-chip-trigger');
    var control = root.querySelector('.se-filter-chip-control');
    var list = listEl(root);
    var search = searchEl(root);
    var combo = isCombobox(root) ? comboboxInput(root) : null;
    if (!trigger || !list) return;

    /* AbortController lets rebindEpListbox drop prior handlers instead of stacking
       toggles (open → immediate close) when modals re-init on each open. */
    if (root.__epListboxAbort) {
      try { root.__epListboxAbort.abort(); } catch (err) {}
    }
    var ac = typeof AbortController !== 'undefined' ? new AbortController() : null;
    var signal = ac ? ac.signal : undefined;
    var listenOpts = signal ? { signal: signal } : undefined;
    root.__epListboxAbort = ac;
    root.__epListboxBound = true;

    if (combo) {
      restoreComboboxLabel(root);
      combo.addEventListener('mousedown', function(e){
        e.stopPropagation();
        if (!root.classList.contains('is-open')) {
          openListbox(root, { selectAll: true });
        }
      }, listenOpts);
      combo.addEventListener('focus', function(){
        if (!root.classList.contains('is-open')) {
          openListbox(root, { selectAll: true });
        }
      }, listenOpts);
      combo.addEventListener('click', function(e){
        e.stopPropagation();
      }, listenOpts);
      combo.addEventListener('input', function(){
        if (!root.classList.contains('is-open')) {
          openListbox(root, { keepQuery: true });
        } else {
          resetListboxPanelSize(list);
          filterSearchableOptions(root, combo.value);
          syncListboxEmptyState(root);
          if (shouldUseFixedListbox(root)) positionFixedListbox(root, list);
        }
      }, listenOpts);
      combo.addEventListener('keydown', function(e){
        var options = visibleOptions(root);
        if (e.key === 'Escape') {
          e.preventDefault();
          closeListbox(root);
          return;
        }
        if (e.key === 'ArrowDown') {
          e.preventDefault();
          if (!root.classList.contains('is-open')) {
            openListbox(root, { keepQuery: true });
            options = visibleOptions(root);
          }
          if (options[0]) options[0].focus();
          return;
        }
        if (e.key === 'ArrowUp') {
          e.preventDefault();
          if (root.classList.contains('is-open') && options.length) {
            options[options.length - 1].focus();
          }
          return;
        }
        if (e.key === 'Enter') {
          e.preventDefault();
          if (!root.classList.contains('is-open')) {
            openListbox(root, { keepQuery: true });
            return;
          }
          var firstMatch = visibleOptions(root)[0];
          if (firstMatch) selectOption(root, firstMatch);
        }
      }, listenOpts);
      // Keep focus in the field when choosing an option with the mouse.
      list.addEventListener('mousedown', function(e){
        if (e.target.closest('.se-filter-listbox-option')) e.preventDefault();
      }, listenOpts);
    } else {
      function onTriggerClick(e){
        e.preventDefault();
        e.stopPropagation();
        toggleListbox(root);
      }
      trigger.addEventListener('click', onTriggerClick, listenOpts);
      // Chevron / icon sit outside the button — still toggle the menu.
      if (control) {
        control.addEventListener('click', function(e){
          if (e.target.closest('.se-filter-chip-trigger')) return;
          if (e.target.closest('.se-filter-listbox')) return;
          onTriggerClick(e);
        }, listenOpts);
      }
      trigger.addEventListener('keydown', function(e){
        if (e.key === 'ArrowDown' || e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          openListbox(root);
        } else if (e.key === 'Escape') {
          closeListbox(root);
        }
      }, listenOpts);
    }

    if (control && combo) {
      control.addEventListener('click', function(e){
        if (e.target.closest('.se-filter-chip-trigger')) return;
        if (e.target.closest('.se-filter-listbox')) return;
        e.preventDefault();
        e.stopPropagation();
        combo.focus();
        if (!root.classList.contains('is-open')) openListbox(root, { selectAll: true });
      }, listenOpts);
    }

    if (search && !combo) {
      search.addEventListener('input', function(){
        resetListboxPanelSize(list);
        filterSearchableOptions(root, search.value);
        syncListboxEmptyState(root);
      }, listenOpts);
      search.addEventListener('click', function(e){ e.stopPropagation(); }, listenOpts);
      search.addEventListener('keydown', function(e){
        e.stopPropagation();
        if (e.key === 'Escape') {
          e.preventDefault();
          closeListbox(root);
          trigger.focus();
        } else if (e.key === 'Enter') {
          e.preventDefault();
          var firstMatch = visibleOptions(root)[0];
          if (firstMatch) selectOption(root, firstMatch);
        } else if (e.key === 'ArrowDown') {
          e.preventDefault();
          var first = visibleOptions(root)[0];
          if (first) first.focus();
        }
      }, listenOpts);
    }

    /* Always bind to the listbox panel itself. Dynamic populators (e.g. POS
       populateTables) replace list.innerHTML and would detach .ep-listbox-options
       — leaving the click listener on a dead node so options look unclickable. */
    var clickTarget = list;
    clickTarget.addEventListener('click', function(e){
      var option = e.target.closest('.se-filter-listbox-option');
      if (!option || !clickTarget.contains(option) || option.classList.contains('is-filtered-out') || isOptionDisabled(option)) return;
      e.preventDefault();
      selectOption(root, option);
    }, listenOpts);

    clickTarget.addEventListener('keydown', function(e){
      var options = root.hasAttribute('data-se-listbox-searchable')
        ? visibleOptions(root)
        : Array.from(list.querySelectorAll('.se-filter-listbox-option'));
      if (!options.length) return;
      var idx = options.indexOf(document.activeElement);
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        options[Math.min(options.length - 1, Math.max(0, idx) + 1)].focus();
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        if (idx <= 0 && combo) {
          combo.focus();
          return;
        }
        options[Math.max(0, (idx < 0 ? 0 : idx) - 1)].focus();
      } else if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        if (idx >= 0) selectOption(root, options[idx]);
      } else if (e.key === 'Escape') {
        e.preventDefault();
        closeListbox(root);
        trigger.focus();
      }
    }, listenOpts);
  }

  function initEpListboxes(){
    listboxRoots('[data-se-listbox]').forEach(bindListbox);
  }

  function rebindEpListbox(root){
    if (!root || !root.parentNode) return root || null;
    closeListbox(root);
    /* Clone-replace strips every prior listener (soft-nav can load multiple
       ep_form_listbox.js versions; AbortController only covers the latest bind). */
    var clone = root.cloneNode(true);
    root.parentNode.replaceChild(clone, root);
    clone.__epListboxBound = false;
    clone.__suFilterListboxBound = false;
    clone.__plFilterListboxBound = false;
    clone.__epListboxAbort = null;
    clone.__epPortaledList = null;
    bindListbox(clone);
    return clone;
  }

  document.addEventListener('click', function(e){
    listboxRoots('[data-se-listbox].is-open').forEach(function(root){
      var list = listEl(root);
      if (root.contains(e.target) || (list && list.contains(e.target))) return;
      closeListbox(root);
    });
  });
  document.addEventListener('keydown', function(e){
    if (e.key !== 'Escape') return;
    listboxRoots('[data-se-listbox].is-open').forEach(closeListbox);
  });

  function repositionOpenFixedListboxes(e){
    var target = e && e.target;
    listboxRoots('[data-se-listbox].is-open').forEach(function(root){
      var list = listEl(root);
      if (!list) return;
      if (target && (list === target || list.contains(target))) return;
      positionFixedListbox(root, list);
    });
  }
  window.addEventListener('resize', repositionOpenFixedListboxes);
  document.addEventListener('scroll', repositionOpenFixedListboxes, true);

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initEpListboxes);
  } else {
    initEpListboxes();
  }

  window.initEpListboxes = initEpListboxes;
  window.rebindEpListbox = rebindEpListbox;
  window.closeAllEpListboxes = function(except){
    closeAllListboxes(except || null);
  };

  window.resetEpListbox = function(fieldId, value, label){
    var root = document.getElementById(fieldId + '-listbox');
    if (!root) return;
    var input = document.getElementById(fieldId);
    if (input) input.value = value;
    var combo = comboboxInput(root);
    if (combo) {
      var display = '';
      if (value) {
        display = String(label || '').trim();
        if (!display || display === String(value)) {
          display = optionDisplayLabel(optionMatchingValue(root, value)) || (
            display !== String(value) ? display : ''
          );
        }
      }
      combo.value = display;
      combo.classList.toggle('is-placeholder', !value);
      var tip = display || combo.getAttribute('placeholder') || '';
      if (tip) combo.setAttribute('title', tip);
      else combo.removeAttribute('title');
    }
    root.classList.toggle('has-value', !!value);
    var valueEl = root.querySelector('.se-filter-chip-value');
    if (valueEl) {
      valueEl.textContent = label;
      if (value) {
        valueEl.classList.remove('is-placeholder', 'staff-supplier-placeholder');
      } else {
        valueEl.classList.add('is-placeholder', 'staff-supplier-placeholder');
      }
    }
    var list = listEl(root);
    if (list) {
      list.querySelectorAll('.se-filter-listbox-option').forEach(function(opt){
        var on = (opt.getAttribute('data-value') || '') === String(value);
        opt.classList.toggle('is-selected', on);
        opt.setAttribute('aria-selected', on ? 'true' : 'false');
      });
    }
  };
})(window);
