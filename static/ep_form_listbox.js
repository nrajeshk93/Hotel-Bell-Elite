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
      options.forEach(function(option){
        option.classList.remove('is-filtered-out');
      });
      return;
    }

    var ranked = options.map(function(option){
      return { option: option, score: scoreSearchOption(option, needle) };
    }).filter(function(entry){
      return entry.score >= 0;
    });

    ranked.sort(function(a, b){
      return b.score - a.score || (a.option.getAttribute('data-name') || '').localeCompare(b.option.getAttribute('data-name') || '');
    });

    var best = ranked.length ? [ranked[0]] : [];
    options.forEach(function(option){ option.classList.add('is-filtered-out'); });
    best.forEach(function(entry){ entry.option.classList.remove('is-filtered-out'); });
  }

  function visibleOptions(root){
    var optionsWrap = optionsWrapFor(root);
    if (!optionsWrap) return [];
    return Array.from(optionsWrap.querySelectorAll('.se-filter-listbox-option:not(.is-filtered-out)'));
  }

  function closeListbox(root){
    if (!root) return;
    var trigger = root.querySelector('.se-filter-chip-trigger');
    var list = root.querySelector('.se-filter-listbox');
    var search = root.querySelector('.ep-listbox-search');
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
  }

  function closeAllListboxes(except){
    document.querySelectorAll('body.ep-module [data-se-listbox].is-open').forEach(function(root){
      if (root !== except) closeListbox(root);
    });
  }

  function positionFixedListbox(root, list){
    if (!root || !list || !root.classList.contains('ep-toolbar-listbox')) return;
    var control = root.querySelector('.se-filter-chip-control') || root;
    var rect = control.getBoundingClientRect();
    var width = Math.max(rect.width, 140);
    var left = Math.min(rect.left, Math.max(8, window.innerWidth - width - 8));
    var maxHeight = Math.min(260, Math.max(120, window.innerHeight - rect.bottom - 16));
    list.style.position = 'fixed';
    list.style.left = left + 'px';
    list.style.right = 'auto';
    list.style.top = (rect.bottom + 6) + 'px';
    list.style.width = width + 'px';
    list.style.minWidth = width + 'px';
    list.style.maxHeight = maxHeight + 'px';
    list.style.zIndex = '4000';
  }

  function clearFixedListbox(list){
    if (!list) return;
    list.style.position = '';
    list.style.left = '';
    list.style.right = '';
    list.style.top = '';
    list.style.width = '';
    list.style.minWidth = '';
    list.style.maxHeight = '';
    list.style.zIndex = '';
    list.style.paddingBottom = '';
    list.scrollTop = 0;
  }

  /** Scroll selected to the top when the list overflows; shrink height so no empty gap under the last option. */
  function scrollSelectedToTop(list){
    if (!list) return;
    var selected = list.querySelector('.se-filter-listbox-option.is-selected, .se-filter-listbox-option[aria-selected="true"]');
    if (!selected || selected.classList.contains('is-filtered-out')) return;
    list.style.paddingBottom = '';
    requestAnimationFrame(function(){
      var searchWrap = list.querySelector('.ep-listbox-search-wrap, .pl-supplier-search-wrap, .staff-supplier-search-wrap');
      var topPad = searchWrap ? searchWrap.offsetHeight : 0;
      var cap = parseFloat(list.style.maxHeight) || list.clientHeight || 260;

      // Short list: size to content only (no tall empty tray).
      if (list.scrollHeight <= cap + 1) {
        list.style.maxHeight = list.scrollHeight + 'px';
        list.scrollTop = 0;
        return;
      }

      var target = Math.max(0, selected.offsetTop - topPad);
      var naturalMax = Math.max(0, list.scrollHeight - cap);
      if (target > naturalMax) {
        list.style.paddingBottom = (target - naturalMax) + 'px';
      }
      list.style.maxHeight = cap + 'px';
      list.scrollTop = target;

      // After pinning selection at the top, trim leftover blank space under the last year/option.
      requestAnimationFrame(function(){
        var last = null;
        var options = list.querySelectorAll('.se-filter-listbox-option:not(.is-filtered-out)');
        if (options.length) last = options[options.length - 1];
        if (!last) return;
        var gap = list.getBoundingClientRect().bottom - last.getBoundingClientRect().bottom;
        if (gap > 10) {
          list.style.maxHeight = Math.max(88, list.clientHeight - gap + 4) + 'px';
        }
      });
    });
  }

  function openListbox(root){
    if (!root || root.classList.contains('is-disabled')) return;
    closeAllListboxes(root);
    var trigger = root.querySelector('.se-filter-chip-trigger');
    var list = root.querySelector('.se-filter-listbox');
    var search = root.querySelector('.ep-listbox-search');
    root.classList.add('is-open');
    if (trigger) trigger.setAttribute('aria-expanded', 'true');
    if (list) {
      list.hidden = false;
      positionFixedListbox(root, list);
      if (root.hasAttribute('data-se-listbox-searchable')) {
        filterSearchableOptions(root, '');
        scrollSelectedToTop(list);
        if (search) {
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
    else openListbox(root);
  }

  function updateDisplay(root, label, value){
    var valueEl = root.querySelector('.se-filter-chip-value');
    var input = root.querySelector('input[type="hidden"]');
    if (input) input.value = value;
    if (valueEl) {
      valueEl.textContent = label;
      valueEl.classList.toggle('is-placeholder', !value);
    }
  }

  function selectOption(root, option){
    if (!root || !option || option.classList.contains('is-filtered-out')) return;
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
        form.submit();
      }
      return;
    }

    var changeHandler = root.getAttribute('data-se-listbox-change');
    if (changeHandler && typeof window[changeHandler] === 'function') {
      window[changeHandler](root, value, label);
    }
  }

  function bindListbox(root){
    if (!root || root.__epListboxBound) return;
    root.__epListboxBound = true;
    var trigger = root.querySelector('.se-filter-chip-trigger');
    var control = root.querySelector('.se-filter-chip-control');
    var list = root.querySelector('.se-filter-listbox');
    var optionsWrap = optionsWrapFor(root);
    var search = root.querySelector('.ep-listbox-search');
    if (!trigger || !list) return;

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

    if (search) {
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

    var clickTarget = optionsWrap || list;
    clickTarget.addEventListener('click', function(e){
      var option = e.target.closest('.se-filter-listbox-option');
      if (!option || !clickTarget.contains(option) || option.classList.contains('is-filtered-out')) return;
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
    document.querySelectorAll('body.ep-module [data-se-listbox]').forEach(bindListbox);
  }

  document.addEventListener('click', function(e){
    document.querySelectorAll('body.ep-module [data-se-listbox].is-open').forEach(function(root){
      if (!root.contains(e.target)) closeListbox(root);
    });
  });
  document.addEventListener('keydown', function(e){
    if (e.key !== 'Escape') return;
    document.querySelectorAll('body.ep-module [data-se-listbox].is-open').forEach(closeListbox);
  });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initEpListboxes);
  } else {
    initEpListboxes();
  }

  window.initEpListboxes = initEpListboxes;

  window.resetEpListbox = function(fieldId, value, label){
    var root = document.getElementById(fieldId + '-listbox');
    if (!root) return;
    var input = document.getElementById(fieldId);
    if (input) input.value = value;
    var valueEl = root.querySelector('.se-filter-chip-value');
    if (valueEl) {
      valueEl.textContent = label;
      valueEl.classList.toggle('is-placeholder', !value);
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
