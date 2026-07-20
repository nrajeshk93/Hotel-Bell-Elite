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
      var indentView = root.getAttribute('data-st-indent-view') || '';
      if (!indentView) {
        try { indentView = new URL(window.location.href).searchParams.get('view') || ''; } catch (err) {}
      }
      if (indentView) url.searchParams.set('view', indentView);
      // Stock Inward: changing outlet clears indent selection.
      if (document.getElementById('st-inward-page') || document.getElementById('st-inward-indent-listbox')) {
        url.searchParams.delete('indent');
      }
      window.location.assign(url.pathname + url.search);
    } catch (e) {
      var qs = 'outlet=' + encodeURIComponent(value);
      if (document.getElementById('st-indent-form')) qs += '&focus=form';
      var view = root.getAttribute('data-st-indent-view') || '';
      if (view) qs += '&view=' + encodeURIComponent(view);
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

  function setApproxPrice(line, price) {
    if (!line) return;
    var input = line.querySelector('[data-st-approx-price], input[name="approximate_price"]');
    if (!input) return;
    input.value = price == null || price === '' ? '' : String(price);
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
      setUnitListbox(line, 'kg');
      setApproxPrice(line, '');
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
    ['st-indent-view-modal', 'st-indent-edit-modal', 'st-reject-modal'].forEach(function (id) {
      var live = main ? main.querySelector('#' + id) : null;
      Array.from(document.querySelectorAll('#' + id)).forEach(function (el) {
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
    modal.classList.add('open');
    modal.setAttribute('aria-hidden', 'false');
  }

  function openIndentViewModal(indentId) {
    var modal = document.getElementById('st-indent-view-modal');
    var data = loadIndentViewMap()[String(indentId)];
    if (!modal || !data) return;

    mountModal(modal);

    var title = document.getElementById('st-indent-view-title');
    var sub = document.getElementById('st-indent-view-sub');
    var status = document.getElementById('st-indent-view-status');
    var notes = document.getElementById('st-indent-view-notes');
    var decision = document.getElementById('st-indent-view-decision');
    var tbody = document.getElementById('st-indent-view-lines');
    var empty = document.getElementById('st-indent-view-empty');
    var editBtn = document.getElementById('st-indent-view-edit');
    var poBtn = document.getElementById('st-indent-view-po');

    if (title) title.textContent = data.indent_no || 'Indent';
    if (sub) {
      var bits = [];
      if (data.outlet_label) bits.push(data.outlet_label);
      if (data.created_by_name) bits.push('Created by ' + data.created_by_name);
      if (data.created_at) bits.push(data.created_at);
      if (data.status === 'approved' || data.status === 'rejected') {
        var decisionVerb = data.status === 'approved' ? 'Approved' : 'Rejected';
        var who = data.decided_by_name || '';
        if (data.decided_by_username) {
          who = who
            ? (who + ' (' + data.decided_by_username + ')')
            : data.decided_by_username;
        }
        if (who) bits.push(decisionVerb + ' by ' + who);
        else bits.push(decisionVerb);
        if (data.decided_at) bits.push(data.decided_at);
      }
      sub.textContent = bits.join(' · ');
    }
    if (status) {
      status.textContent = data.status_label || data.status || '';
      status.className = 'cp-status-pill cp-status-pill--' + (data.status || 'draft');
    }
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
      var lines = Array.isArray(data.lines) ? data.lines : [];
      tbody.innerHTML = lines.map(function (line) {
        var priceText = line.approximate_price_display
          ? ('₹' + line.approximate_price_display)
          : (line.approximate_price != null && line.approximate_price !== ''
            ? ('₹' + line.approximate_price)
            : '—');
        return '<tr>'
          + '<td>' + escapeHtml(line.item_name) + '</td>'
          + '<td>' + escapeHtml(line.quantity) + '</td>'
          + '<td>' + escapeHtml(line.unit) + '</td>'
          + '<td>' + escapeHtml(priceText) + '</td>'
          + '</tr>';
      }).join('');
      if (empty) empty.hidden = lines.length > 0;
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
    if (target.closest('#st-indent-view-close, #st-indent-view-dismiss')) {
      event.preventDefault();
      closeIndentViewModal();
      return;
    }
    if (target.closest('#st-indent-edit-close')) {
      event.preventDefault();
      closeIndentEditModal();
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
    var dec = target.closest('[data-st-qty-dec]');
    if (dec) {
      event.preventDefault();
      adjustQty(dec.closest('.st-qty-stepper') && dec.closest('.st-qty-stepper').querySelector('input[name="quantity"]'), -1);
      return;
    }
    var inc = target.closest('[data-st-qty-inc]');
    if (inc) {
      event.preventDefault();
      adjustQty(inc.closest('.st-qty-stepper') && inc.closest('.st-qty-stepper').querySelector('input[name="quantity"]'), 1);
    }
  }

  function onStoresKeydown(event) {
    if (event.key !== 'Escape') return;
    var rejectModal = document.getElementById('st-reject-modal');
    if (rejectModal && rejectModal.classList.contains('open')) {
      closeRejectModal();
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
    if (event.target && event.target.matches('[data-st-notes-counter]')) syncNotesCounter();
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
    if (!form || form.id !== 'st-indent-edit-form') return;
    var indentId = syncEditFormIndentId(form);
    if (!indentId) {
      event.preventDefault();
      event.stopPropagation();
      window.alert('Could not save — missing indent id. Close and open Edit again.');
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
    document.addEventListener('submit', onStoresSubmit, true);
  }

  function bootIndentModals() {
    syncNotesCounter();
    var editModal = document.getElementById('st-indent-edit-modal');
    var openId = editModal && editModal.getAttribute('data-st-open-edit');
    if (openId) openIndentEditModal(openId);
  }

  function initPlSortableTable(table) {
    if (!table || table.getAttribute('data-st-sort-bound') === '1') return;
    var tbody = table.tBodies[0];
    if (!tbody) return;
    var headers = Array.from(table.querySelectorAll('th.pl-sortable'));
    if (!headers.length) return;
    table.setAttribute('data-st-sort-bound', '1');
    var activeKey = '';
    var ascending = true;

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

    function sortBy(th) {
      var key = th.getAttribute('data-sort') || '';
      var type = th.getAttribute('data-sort-type') || 'text';
      var colIndex = Array.from(th.parentNode.children).indexOf(th);
      if (colIndex < 0) return;

      if (activeKey === key) ascending = !ascending;
      else {
        activeKey = key;
        ascending = true;
      }

      var rows = Array.from(tbody.querySelectorAll('tr[data-sort-row]'));
      rows.sort(function (a, b) {
        var av = cellSortValue(a, colIndex, type);
        var bv = cellSortValue(b, colIndex, type);
        var cmp = 0;
        if (type === 'number') cmp = av - bv;
        else cmp = String(av).localeCompare(String(bv), undefined, { numeric: true, sensitivity: 'base' });
        return ascending ? cmp : -cmp;
      });
      rows.forEach(function (row) { tbody.appendChild(row); });

      headers.forEach(function (header) {
        header.classList.remove('is-sorted-asc', 'is-sorted-desc');
        header.setAttribute('aria-sort', 'none');
      });
      th.classList.add(ascending ? 'is-sorted-asc' : 'is-sorted-desc');
      th.setAttribute('aria-sort', ascending ? 'ascending' : 'descending');
    }

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

  function initStoresSortableTables() {
    document.querySelectorAll('table.pl-table').forEach(initPlSortableTable);
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

  function syncInwardRowState(row) {
    if (!row) return;
    var check = row.querySelector('.st-inward-row-check');
    var on = !!(check && check.checked);
    row.classList.toggle('is-deselected', !on);
    var qty = row.querySelector('[data-st-inward-qty]');
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
    row.querySelectorAll('.st-inward-step').forEach(function (btn) {
      btn.disabled = !on;
    });
  }

  function syncInwardConfirm() {
    var form = document.getElementById('st-inward-form');
    var confirmBtn = document.getElementById('st-inward-confirm');
    if (!form || !confirmBtn) return;
    var ready = false;
    form.querySelectorAll('[data-st-inward-row]').forEach(function (row) {
      var check = row.querySelector('.st-inward-row-check');
      var qtyInput = row.querySelector('[data-st-inward-qty]');
      if (check && check.checked && qtyInput && parseInwardQty(qtyInput.value) > 0) {
        ready = true;
      }
    });
    confirmBtn.disabled = !ready;
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

  function syncAllInwardRows() {
    var form = document.getElementById('st-inward-form');
    if (!form) return;
    form.querySelectorAll('[data-st-inward-row]').forEach(syncInwardRowState);
    syncInwardSelectAllState();
    syncInwardConfirm();
  }

  window.stInwardIndentChanged = function (root, value) {
    if (!root) return;
    var endpoint = root.getAttribute('data-st-inward-endpoint') || '/stores/purchase-requests';
    var outlet = root.getAttribute('data-st-inward-outlet') || '';
    try {
      var url = new URL(endpoint, window.location.origin);
      if (outlet) url.searchParams.set('outlet', outlet);
      if (value) url.searchParams.set('indent', value);
      else url.searchParams.delete('indent');
      window.location.assign(url.pathname + url.search);
    } catch (e) {
      var qs = [];
      if (outlet) qs.push('outlet=' + encodeURIComponent(outlet));
      if (value) qs.push('indent=' + encodeURIComponent(value));
      window.location.href = endpoint + (qs.length ? ('?' + qs.join('&')) : '');
    }
  };

  function selectedInwardLines() {
    var form = document.getElementById('st-inward-form');
    var lines = [];
    if (!form) return lines;
    form.querySelectorAll('[data-st-inward-row]').forEach(function (row) {
      var check = row.querySelector('.st-inward-row-check');
      var qtyInput = row.querySelector('[data-st-inward-qty]');
      if (!check || !check.checked || !qtyInput) return;
      var qty = parseInwardQty(qtyInput.value);
      if (qty <= 0) return;
      var lineId = parseInt(check.value, 10);
      if (!lineId) return;
      var rate = parseInwardQty(row.getAttribute('data-rate'));
      lines.push({ line_id: lineId, received_qty: qty, rate: rate });
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

  function setInwardAmountWarn(msg) {
    var warnEl = document.getElementById('st-inward-amount-warn');
    if (!warnEl) return;
    if (msg) {
      warnEl.textContent = msg;
      warnEl.hidden = false;
    } else {
      warnEl.textContent = '';
      warnEl.hidden = true;
    }
  }

  function syncInwardAmountWarn() {
    var amountEl = document.getElementById('st-inward-expense-amount');
    var amount = amountEl ? Number(amountEl.value) : 0;
    if (!isFinite(amount) || amount <= 0) {
      setInwardAmountWarn('');
      return;
    }
    var approx = computeInwardApproxTotal();
    if (approx > 0 && amount - approx > 0.001) {
      setInwardAmountWarn(
        'Entered value is more than approximate price (' +
          formatInwardAvailableCash(approx) +
          ').'
      );
      return;
    }
    setInwardAmountWarn('');
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
    el.classList.remove('open');
    el.setAttribute('aria-hidden', 'true');
  }

  function setInwardListboxValue(prefix, value, label, placeholder) {
    var hidden = document.getElementById(prefix + '-input');
    var valueEl = document.getElementById(prefix + '-value');
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
    if (list) {
      list.querySelectorAll('.se-filter-listbox-option').forEach(function (opt) {
        var selected = String(opt.getAttribute('data-value') || '') === String(value || '');
        opt.classList.toggle('is-selected', selected);
        opt.setAttribute('aria-selected', selected ? 'true' : 'false');
      });
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
    setInwardExpenseError('');
    setInwardAmountWarn('');
    if (dateEl) dateEl.value = todayIso;
    if (descriptionEl) descriptionEl.value = '';
    if (amountEl) amountEl.value = '';
    if (invoiceEl) invoiceEl.value = '';
    if (transactionEl) transactionEl.value = '';
    setInwardListboxValue('st-inward-supplier', '', '', 'Select supplier');
    setInwardListboxValue('st-inward-category', '', '', 'Select category');
    setInwardListboxValue('st-inward-payment', '', '', 'Select payment type');
    syncInwardPaymentVisibility();
    refreshInwardAvailableCash();
  }

  function openInwardExpenseModal() {
    var modal = document.getElementById('st-inward-expense-modal');
    var confirmBtn = document.getElementById('st-inward-confirm');
    if (!modal || !confirmBtn || confirmBtn.disabled) return;
    var lines = selectedInwardLines();
    if (!lines.length) return;
    resetInwardExpenseForm();
    var indentNo = confirmBtn.getAttribute('data-st-inward-indent-no') || '';
    var notesEl = document.getElementById('st-inward-notes');
    var notes = notesEl ? String(notesEl.value || '').trim() : '';
    var description = 'Stock inward ' + indentNo;
    if (notes) description += ' — ' + notes;
    var descriptionEl = document.getElementById('st-inward-expense-description');
    if (descriptionEl) descriptionEl.value = description;
    openInwardModal(modal);
    if (descriptionEl) descriptionEl.focus();
  }

  async function submitInwardExpense() {
    var confirmBtn = document.getElementById('st-inward-confirm');
    var saveBtn = document.getElementById('st-inward-expense-save');
    var modal = document.getElementById('st-inward-expense-modal');
    if (!confirmBtn) return;
    var lines = selectedInwardLines();
    if (!lines.length) {
      setInwardExpenseError('Select at least one item with a received quantity.');
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
    var amountRaw = amountEl ? amountEl.value : '';
    var supplierId = document.getElementById('st-inward-supplier-input')
      ? document.getElementById('st-inward-supplier-input').value
      : '';
    var category = document.getElementById('st-inward-category-input')
      ? document.getElementById('st-inward-category-input').value
      : '';
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
      setInwardExpenseError('Please select a supplier.');
      return;
    }
    if (!category) {
      setInwardExpenseError('Please select a category.');
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
      indent_id: indentEl ? indentEl.value : '',
      notes: notesEl ? String(notesEl.value || '').trim() : '',
      lines: lines.map(function (line) {
        return { line_id: line.line_id, received_qty: line.received_qty };
      }),
      company: confirmBtn.getAttribute('data-st-default-company') || '',
      location: confirmBtn.getAttribute('data-st-default-location') || '',
      date: purchaseDate,
      description: description,
      amount: amountRaw,
      payment_type: paymentType,
      category: category,
      transaction_id: paymentType === 'bank_transfer' ? transactionId : '',
      invoice_number: invoiceNumber,
      supplier_id: supplierId
    };
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

    var stepBtn = target.closest('[data-st-inward-step]');
    if (stepBtn) {
      event.preventDefault();
      var row = stepBtn.closest('[data-st-inward-row]');
      var input = row && row.querySelector('[data-st-inward-qty]');
      if (!input || input.disabled) return;
      var delta = parseInwardQty(stepBtn.getAttribute('data-st-inward-step'));
      var ordered = row ? parseInwardQty(row.getAttribute('data-ordered')) : 0;
      var next = parseInwardQty(input.value) + delta;
      if (next < 0) next = 0;
      if (ordered > 0 && next > ordered) next = ordered;
      if (Math.abs(next - Math.round(next)) < 0.0001) next = Math.round(next);
      else next = Math.round(next * 1000) / 1000;
      input.value = String(next);
      syncInwardConfirm();
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
    }
  }

  function onInwardInput(event) {
    var target = event.target;
    if (!target) return;
    var page = document.getElementById('st-inward-page');
    if (!page || !page.contains(target)) return;
    if (target.matches('[data-st-inward-qty]')) {
      syncInwardConfirm();
      return;
    }
    if (target.matches('[data-st-notes-counter]')) syncNotesCounter();
  }

  function initStockInward() {
    var page = document.getElementById('st-inward-page');
    if (!page) return;
    applyInwardOrderedDefaults();
    syncAllInwardRows();
    syncNotesCounter();
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
      amountEl.addEventListener('change', syncInwardAmountWarn);
    }
    var form = document.getElementById('st-inward-form');
    if (form && !form.__stInwardSubmitBound) {
      form.__stInwardSubmitBound = true;
      form.addEventListener('submit', function (e) {
        e.preventDefault();
        openInwardExpenseModal();
      });
    }
    syncInwardPaymentVisibility();
  }

  window.initStoresPage = function () {
    bindStoresEvents();
    cleanupHostedIndentModals();
    initStoresSortableTables();
    initStockInward();
    if (
      !document.getElementById('st-indent-view-modal')
      && !document.getElementById('st-indent-edit-modal')
      && !document.getElementById('st-reject-modal')
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
