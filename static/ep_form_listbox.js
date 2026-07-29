(function(){
  'use strict';

  function optionsWrapFor(root){
    return root.querySelector('.ep-listbox-options') || root.querySelector('.se-filter-listbox');
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

  function filterSearchableOptions(root, query){
    var optionsWrap = optionsWrapFor(root);
    if (!optionsWrap) return;
    var needle = String(query || '').trim().toLowerCase();
    var options = Array.from(optionsWrap.querySelectorAll('.se-filter-listbox-option'));

    if (!needle) {
      options.sort(function(a, b){
        var aAll = (a.getAttribute('data-value') || '') === 'all';
        var bAll = (b.getAttribute('data-value') || '') === 'all';
        if (aAll && !bAll) return -1;
        if (bAll && !aAll) return 1;
        var aLabel = (a.getAttribute('data-label') || a.getAttribute('data-name') || a.textContent || '').trim();
        var bLabel = (b.getAttribute('data-label') || b.getAttribute('data-name') || b.textContent || '').trim();
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
    ranked.forEach(function(entry){ entry.option.classList.remove('is-filtered-out'); });
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

  function closeListbox(root){
    if (!root) return;
    var trigger = root.querySelector('.se-filter-chip-trigger');
    var list = root.querySelector('.se-filter-listbox');
    var search = root.querySelector('.ep-listbox-search');
    var wasOpen = root.classList.contains('is-open');
    root.classList.remove('is-open');
    if (trigger) trigger.setAttribute('aria-expanded', 'false');
    if (list) {
      list.hidden = true;
      clearFixedListbox(list);
    }
    if (search) search.value = '';
    if (root.hasAttribute('data-se-listbox-searchable')) {
      filterSearchableOptions(root, '');
    }
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
    var selected = root.querySelector('.se-filter-listbox-option.is-selected');
    var label = selected
      ? (selected.getAttribute('data-label') || selected.textContent || '').trim()
      : '';
    if (!label) {
      var hidden = root.querySelector('input[type="hidden"]');
      label = hidden ? String(hidden.value || '').trim() : '';
    }
    input.value = label;
  }

  function listboxRoots(selector){
    return document.querySelectorAll(
      'body.ep-module ' + selector + ', body.su-module ' + selector + ', body.pos-module ' + selector
    );
  }

  function closeAllListboxes(except){
    listboxRoots('[data-se-listbox].is-open').forEach(function(root){
      if (root !== except) closeListbox(root);
    });
  }

  function shouldUseFixedListbox(root){
    if (!root) return false;
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
       Fixed positioning escapes overflow so product/unit panels stay visible. */
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
      return true;
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
    if (root.classList.contains('ep-form-listbox') && root.closest('#st-indent-edit-modal, #st-indent-view-modal, #st-stores-ledger-modal, #st-ledger-pending-modal, #st-product-modal, #st-category-modal, #st-unit-modal')) {
      return true;
    }
    return false;
  }

  function positionFixedListbox(root, list){
    if (!root || !list || !shouldUseFixedListbox(root)) return;
    var control = root.querySelector('.se-filter-chip-control') || root;
    var rect = control.getBoundingClientRect();
    var width = Math.max(rect.width, 140);
    var left = Math.min(rect.left, Math.max(8, window.innerWidth - width - 8));
    var spaceBelow = window.innerHeight - rect.bottom - 12;
    var spaceAbove = rect.top - 12;
    var openUp = spaceBelow < 180 && spaceAbove > spaceBelow;
    var maxHeight = Math.min(260, Math.max(120, openUp ? spaceAbove : spaceBelow));
    list.style.position = 'fixed';
    list.style.left = left + 'px';
    list.style.right = 'auto';
    list.style.width = width + 'px';
    list.style.minWidth = width + 'px';
    list.style.maxHeight = maxHeight + 'px';
    list.style.zIndex = root.closest('#st-stores-ledger-modal, #st-ledger-pending-modal, #st-indent-edit-modal, #st-indent-view-modal, #st-product-modal, #st-category-modal, #st-unit-modal, #pos-menu-item-modal, #pl-add-purchase-modal, #sales-expense-modal') ? '10100' : (root.classList.contains('pos-inv-header-listbox') ? '200' : '10090');
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
    list.scrollTop = 0;
  }

  /** Scroll selected into view when the list overflows; never pad below the last option. */
  function scrollSelectedToTop(list){
    if (!list) return;
    var selected = list.querySelector('.se-filter-listbox-option.is-selected, .se-filter-listbox-option[aria-selected="true"]');
    if (!selected || selected.classList.contains('is-filtered-out')) return;
    list.style.paddingBottom = '';
    requestAnimationFrame(function(){
      var searchWrap = list.querySelector('.ep-listbox-search-wrap, .pl-supplier-search-wrap, .staff-supplier-search-wrap');
      var topPad = searchWrap ? searchWrap.offsetHeight : 0;
      var cap = parseFloat(list.style.maxHeight) || list.clientHeight || 260;
      var options = list.querySelectorAll('.se-filter-listbox-option:not(.is-filtered-out)');

      // Short list: size to content only (no tall empty tray).
      // Never collapse to padding-only height while options exist (layout race → 14px sliver).
      if (list.scrollHeight <= cap + 1) {
        var contentH = list.scrollHeight;
        if (options.length && contentH < 48) {
          list.style.maxHeight = cap + 'px';
          list.scrollTop = 0;
          return;
        }
        list.style.maxHeight = Math.max(contentH, options.length ? 88 : contentH) + 'px';
        list.scrollTop = 0;
        return;
      }

      // Prefer selected near the top, but never invent blank scroll space under the last row.
      var target = Math.max(0, selected.offsetTop - topPad);
      var naturalMax = Math.max(0, list.scrollHeight - cap);
      list.style.paddingBottom = '';
      list.style.maxHeight = cap + 'px';
      list.scrollTop = Math.min(target, naturalMax);

      // Trim leftover blank space under the last option (viewport taller than needed).
      requestAnimationFrame(function(){
        var last = null;
        var visible = list.querySelectorAll('.se-filter-listbox-option:not(.is-filtered-out)');
        if (visible.length) last = visible[visible.length - 1];
        if (!last) return;
        var gap = list.getBoundingClientRect().bottom - last.getBoundingClientRect().bottom;
        if (gap > 10) {
          list.style.maxHeight = Math.max(88, list.clientHeight - gap + 4) + 'px';
        }
      });
    });
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
    var list = root.querySelector('.se-filter-listbox');
    var search = root.querySelector('.ep-listbox-search');
    var combo = comboboxInput(root);
    root.classList.add('is-open');
    if (trigger) trigger.setAttribute('aria-expanded', 'true');
    if (list) {
      list.hidden = false;
      if (shouldUseFixedListbox(root)) {
        positionFixedListbox(root, list);
      } else {
        clearFixedListbox(list);
      }
      if (root.hasAttribute('data-se-listbox-searchable')) {
        var query = '';
        if (isCombobox(root) && combo && opts.keepQuery) {
          query = combo.value;
        }
        filterSearchableOptions(root, query);
        if (!isCombobox(root) || !opts.keepQuery) {
          scrollSelectedToTop(list);
        }
        if (isCombobox(root)) {
          if (combo && opts.selectAll) {
            try { combo.select(); } catch (err) {}
          }
        } else if (search) {
          search.value = '';
          search.focus();
        }
      } else {
        var selected = list.querySelector('[aria-selected="true"]') || list.querySelector('.se-filter-listbox-option');
        scrollSelectedToTop(list);
        if (selected) selected.focus({ preventScroll: true });
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
      combo.value = label || '';
      combo.classList.toggle('is-placeholder', !value);
    }
    if (valueEl) {
      valueEl.textContent = label;
      if (value) {
        valueEl.classList.remove('is-placeholder', 'staff-supplier-placeholder');
      } else {
        valueEl.classList.add('is-placeholder', 'staff-supplier-placeholder');
      }
    }
  }

  function isOptionDisabled(option){
    return !!option && option.getAttribute('aria-disabled') === 'true';
  }

  function selectOption(root, option){
    if (!root || !option || option.classList.contains('is-filtered-out') || isOptionDisabled(option)) return;
    var list = root.querySelector('.se-filter-listbox');
    var value = option.getAttribute('data-value') || '';
    var label = (option.getAttribute('data-label') || option.textContent || '').trim();
    updateDisplay(root, label, value);
    if (list) {
      list.querySelectorAll('.se-filter-listbox-option').forEach(function(opt){
        var on = opt === option;
        opt.classList.toggle('is-selected', on);
        opt.setAttribute('aria-selected', on ? 'true' : 'false');
      });
    }
    closeListbox(root);

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
      window[changeHandler](root, value, label);
    }
  }

  function bindListbox(root){
    // Skip chips already owned by sales / purchase / credit-payment filter listbox scripts.
    if (!root || root.__epListboxBound || root.__suFilterListboxBound || root.__plFilterListboxBound) return;
    if (root.closest('#purchase-ledger-filter-form')) return;
    if (root.id === 'credit-payment-supplier-listbox') return;
    root.__epListboxBound = true;
    var trigger = root.querySelector('.se-filter-chip-trigger');
    var control = root.querySelector('.se-filter-chip-control');
    var list = root.querySelector('.se-filter-listbox');
    var search = root.querySelector('.ep-listbox-search');
    var combo = isCombobox(root) ? comboboxInput(root) : null;
    if (!trigger || !list) return;

    if (combo) {
      combo.addEventListener('mousedown', function(e){
        e.stopPropagation();
        if (!root.classList.contains('is-open')) {
          openListbox(root, { selectAll: true });
        }
      });
      combo.addEventListener('focus', function(){
        if (!root.classList.contains('is-open')) {
          openListbox(root, { selectAll: true });
        }
      });
      combo.addEventListener('click', function(e){
        e.stopPropagation();
      });
      combo.addEventListener('input', function(){
        if (!root.classList.contains('is-open')) {
          openListbox(root, { keepQuery: true });
        } else {
          filterSearchableOptions(root, combo.value);
          if (shouldUseFixedListbox(root)) positionFixedListbox(root, list);
        }
      });
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
      });
      // Keep focus in the field when choosing an option with the mouse.
      list.addEventListener('mousedown', function(e){
        if (e.target.closest('.se-filter-listbox-option')) e.preventDefault();
      });
    } else {
      function onTriggerClick(e){
        e.preventDefault();
        e.stopPropagation();
        toggleListbox(root);
      }
      trigger.addEventListener('click', onTriggerClick);
      // Chevron / icon sit outside the button — still toggle the menu.
      if (control) {
        control.addEventListener('click', function(e){
          if (e.target.closest('.se-filter-chip-trigger')) return;
          if (e.target.closest('.se-filter-listbox')) return;
          onTriggerClick(e);
        });
      }
      trigger.addEventListener('keydown', function(e){
        if (e.key === 'ArrowDown' || e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          openListbox(root);
        } else if (e.key === 'Escape') {
          closeListbox(root);
        }
      });
    }

    if (control && combo) {
      control.addEventListener('click', function(e){
        if (e.target.closest('.se-filter-chip-trigger')) return;
        if (e.target.closest('.se-filter-listbox')) return;
        e.preventDefault();
        e.stopPropagation();
        combo.focus();
        if (!root.classList.contains('is-open')) openListbox(root, { selectAll: true });
      });
    }

    if (search && !combo) {
      search.addEventListener('input', function(){
        filterSearchableOptions(root, search.value);
      });
      search.addEventListener('click', function(e){ e.stopPropagation(); });
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
      });
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
    });

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
    });
  }

  function initEpListboxes(){
    listboxRoots('[data-se-listbox]').forEach(bindListbox);
  }

  function rebindEpListbox(root){
    if (!root) return;
    root.__epListboxBound = false;
    root.__suFilterListboxBound = false;
    root.__plFilterListboxBound = false;
    bindListbox(root);
  }

  document.addEventListener('click', function(e){
    listboxRoots('[data-se-listbox].is-open').forEach(function(root){
      if (!root.contains(e.target)) closeListbox(root);
    });
  });
  document.addEventListener('keydown', function(e){
    if (e.key !== 'Escape') return;
    listboxRoots('[data-se-listbox].is-open').forEach(closeListbox);
  });

  function repositionOpenFixedListboxes(){
    listboxRoots('[data-se-listbox].is-open').forEach(function(root){
      var list = root.querySelector('.se-filter-listbox');
      if (list) positionFixedListbox(root, list);
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
      combo.value = label || '';
      combo.classList.toggle('is-placeholder', !value);
    }
    var valueEl = root.querySelector('.se-filter-chip-value');
    if (valueEl) {
      valueEl.textContent = label;
      if (value) {
        valueEl.classList.remove('is-placeholder', 'staff-supplier-placeholder');
      } else {
        valueEl.classList.add('is-placeholder', 'staff-supplier-placeholder');
      }
    }
    var list = root.querySelector('.se-filter-listbox');
    if (list) {
      list.querySelectorAll('.se-filter-listbox-option').forEach(function(opt){
        var on = (opt.getAttribute('data-value') || '') === String(value);
        opt.classList.toggle('is-selected', on);
        opt.setAttribute('aria-selected', on ? 'true' : 'false');
      });
    }
  };
})();
