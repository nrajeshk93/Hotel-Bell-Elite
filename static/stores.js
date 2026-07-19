(function () {
  'use strict';

  window.stOutletChanged = function (root, value) {
    if (!root || !value) return;
    var endpoint = root.getAttribute('data-st-list-endpoint') || window.location.pathname;
    try {
      var url = new URL(endpoint, window.location.origin);
      url.searchParams.set('outlet', value);
      if (document.getElementById('st-indent-form') || /(?:\?|&)focus=form(?:&|$)/.test(window.location.search)) {
        url.searchParams.set('focus', 'form');
      }
      window.location.assign(url.pathname + url.search);
    } catch (e) {
      var qs = 'outlet=' + encodeURIComponent(value);
      if (document.getElementById('st-indent-form')) qs += '&focus=form';
      window.location.href = endpoint + (endpoint.indexOf('?') >= 0 ? '&' : '?') + qs;
    }
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

  function lineHasProduct(line) {
    if (!line) return false;
    var hidden = line.querySelector('input[name="item_name"]');
    return !!(hidden && String(hidden.value || '').trim());
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

  window.stProductPicked = function (root) {
    if (!root) return;
    var line = root.closest('.st-line');
    if (!line) return;
    var selected = root.querySelector('.se-filter-listbox-option.is-selected');
    var unit = selected && selected.getAttribute('data-unit');
    setUnitListbox(line, unit);
    syncUnitVisibility(line);

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

    if (label) {
      label.id = fid + '-label';
      label.setAttribute('for', fid + '-trigger');
    }
    if (trigger) {
      trigger.id = fid + '-trigger';
      trigger.setAttribute('aria-controls', fid + '-list');
      trigger.setAttribute('aria-labelledby', fid + '-label ' + fid + '-value');
      trigger.setAttribute('aria-expanded', 'false');
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
    var qty = line.querySelector('input[name="quantity"]');
    if (qty) qty.value = '';
    var note = line.querySelector('input[name="line_notes"]');
    if (note) note.value = '';
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
      setUnitListbox(line, 'kg');
      syncUnitVisibility(line);
      return;
    }
    line.remove();
  }

  function adjustQty(input, delta) {
    if (!input) return;
    var step = parseFloat(input.getAttribute('step') || '1') || 1;
    var min = parseFloat(input.getAttribute('min') || '0');
    var current = parseFloat(input.value);
    if (isNaN(current) || current <= 0) current = 0;
    var next = Math.round((current + delta * step) * 1000) / 1000;
    if (!isNaN(min) && next < min && next !== 0) next = min;
    if (next <= 0) {
      input.value = '';
    } else {
      input.value = String(next);
    }
    input.dispatchEvent(new Event('input', { bubbles: true }));
  }

  function syncNotesCounter() {
    var area = document.querySelector('[data-st-notes-counter]');
    var countEl = document.querySelector('[data-st-notes-count]');
    if (!area || !countEl) return;
    countEl.textContent = String((area.value || '').length);
  }

  document.addEventListener('click', function (event) {
    var addBtn = event.target.closest('[data-st-add-line]');
    if (addBtn) {
      event.preventDefault();
      addLine(addBtn);
      return;
    }
    var removeBtn = event.target.closest('[data-st-remove-line]');
    if (removeBtn) {
      event.preventDefault();
      removeLine(removeBtn);
      return;
    }
    var dec = event.target.closest('[data-st-qty-dec]');
    if (dec) {
      event.preventDefault();
      adjustQty(dec.closest('.st-qty-stepper') && dec.closest('.st-qty-stepper').querySelector('input[name="quantity"]'), -1);
      return;
    }
    var inc = event.target.closest('[data-st-qty-inc]');
    if (inc) {
      event.preventDefault();
      adjustQty(inc.closest('.st-qty-stepper') && inc.closest('.st-qty-stepper').querySelector('input[name="quantity"]'), 1);
    }
  });

  document.addEventListener('input', function (event) {
    if (event.target && event.target.matches('[data-st-notes-counter]')) syncNotesCounter();
  });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', syncNotesCounter);
  } else {
    syncNotesCounter();
  }
})();
