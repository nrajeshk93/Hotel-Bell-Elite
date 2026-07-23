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
        || document;
    }
    var lines = root.querySelectorAll ? root.querySelectorAll('.st-line') : [];
    var grand = 0;
    lines.forEach(function (line) {
      var qtyEl = line.querySelector('input[name="quantity"]');
      var priceEl = line.querySelector('[data-st-approx-price], input[name="approximate_price"]');
      var totalEl = line.querySelector('[data-st-line-total]');
      var qty = qtyEl ? parseFloat(qtyEl.value) : 0;
      var price = priceEl ? parseFloat(priceEl.value) : 0;
      var lineTotal = (isFinite(qty) && qty > 0 && isFinite(price) && price > 0)
        ? Math.round(qty * price * 100) / 100
        : 0;
      if (totalEl) {
        totalEl.textContent = lineTotal > 0 ? formatIndentMoney(lineTotal) : '—';
        totalEl.classList.toggle('is-empty', lineTotal <= 0);
      }
      grand += lineTotal;
    });
    var grandEl = root.querySelector
      ? root.querySelector('[data-st-indent-grand-total]')
      : null;
    if (!grandEl && root !== document) {
      var wrap = (root.closest && root.closest('.st-lines-wrap')) || root;
      grandEl = wrap.querySelector ? wrap.querySelector('[data-st-indent-grand-total]') : null;
    }
    if (grandEl) grandEl.textContent = grand > 0 ? formatIndentMoney(grand) : '—';
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
    syncIndentLineTotals(line.closest('.st-lines-wrap'));

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
    ['st-indent-view-modal', 'st-indent-edit-modal', 'st-reject-modal', 'st-stores-ledger-modal', 'st-ledger-pending-modal', 'st-approvals-modal'].forEach(function (id) {
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
    body.querySelectorAll('table.pl-table').forEach(initPlSortableTable);
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

  function submitApprovalsModalForm(form) {
    if (!form) return;
    var action = form.getAttribute('action') || window.location.href;
    var method = (form.getAttribute('method') || 'post').toUpperCase();
    var body = method === 'GET' ? null : new FormData(form);
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
        var itemName = line.item_name || '';
        var unit = line.unit || '';
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
    var approvalsModal = document.getElementById('st-approvals-modal');
    if (
      approvalsModal
      && approvalsModal.classList.contains('open')
      && (approvalsModal.contains(form) || form.id === 'st-reject-form')
    ) {
      event.preventDefault();
      event.stopPropagation();
      submitApprovalsModalForm(form);
      return;
    }
    if (form.id !== 'st-indent-edit-form') return;
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
    if (!table) return;
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

  function initStoresSortableTables() {
    document.querySelectorAll('table.pl-table').forEach(initPlSortableTable);
    applyStockDefaultSort(document.getElementById('st-stock-table'));
    applyMovementsDefaultSort(document.getElementById('st-stock-movements-table'));
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
    if (tax) tax.disabled = !on;
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
        tax_percent: taxPercent
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
    setInwardApprovedHint(0);
    if (dateEl) dateEl.value = todayIso;
    if (descriptionEl) descriptionEl.value = '';
    if (amountEl) amountEl.value = '';
    if (amountEl) amountEl.removeAttribute('data-approved-total');
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
    var amountEl = document.getElementById('st-inward-expense-amount');
    var approvedTotal = computeInwardApproxTotal(lines);
    var enteredTotal = computeInwardEnteredTotal(lines);
    if (amountEl) {
      amountEl.setAttribute('data-approved-total', String(Math.round(approvedTotal || 0)));
      // Prefill Value from user-entered inward prices only (not approved defaults).
      if (enteredTotal > 0) {
        amountEl.value = String(Math.round(enteredTotal));
      }
    }
    setInwardApprovedHint(approvedTotal);
    syncInwardAmountWarn();
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
    roundInwardExpenseAmount();
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
        return {
          line_id: line.line_id,
          received_qty: line.received_qty,
          unit_price: line.unit_price,
          tax_percent: line.tax_percent
        };
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
  }

  function applyInwardBulkTax(rawTax) {
    var form = document.getElementById('st-inward-form');
    if (!form) return;
    var tax = parseInwardQty(rawTax);
    if (!isFinite(tax) || tax < 0) tax = 0;
    if (tax > 100) tax = 100;
    var taxText = String(tax);
    var updated = false;
    form.querySelectorAll('[data-st-inward-row]').forEach(function (row) {
      var check = row.querySelector('.st-inward-row-check');
      var taxInput = row.querySelector('[data-st-inward-tax]');
      if (!check || !check.checked || !taxInput || taxInput.disabled) return;
      taxInput.value = taxText;
      updated = true;
    });
    if (updated) syncInwardConfirm();
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
    if (target.matches('[data-st-inward-qty], [data-st-inward-price], [data-st-inward-tax]')) {
      syncInwardConfirm();
      return;
    }
    if (target.matches('[data-st-notes-counter]')) syncNotesCounter();
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
    syncInwardPaymentVisibility();
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
    var reset = opts.reset !== false && !opts.keepValues;

    if (reset) {
      var idEl = document.getElementById('st-product-id');
      if (idEl) idEl.value = '';
      var nameEl = document.getElementById('st-product-name');
      if (nameEl) nameEl.value = '';
      var priceEl = document.getElementById('st-product-approx-price');
      if (priceEl) priceEl.value = '';
      var errEl = document.getElementById('st-product-modal-err');
      if (errEl) {
        errEl.style.display = 'none';
        errEl.textContent = '';
      }
      window.closeCategoryModal();
      window.closeUnitModal();

      if (typeof window.resetEpListbox === 'function') {
        window.resetEpListbox('st-product-category', '', 'Select category…');
        window.resetEpListbox('st-product-outlet', '', 'Select outlet…');
        window.resetEpListbox('st-product-unit', 'kg', 'kg');
      }
      modal.setAttribute('data-st-editing', '0');
    }

    var title = document.getElementById('st-product-modal-title');
    var submitLabel = document.getElementById('st-product-submit-label');
    var editing = modal.getAttribute('data-st-editing') === '1' || !!(document.getElementById('st-product-id') || {}).value;
    if (title) title.textContent = editing ? 'Edit product' : 'Add product';
    if (submitLabel) submitLabel.textContent = editing ? 'Save changes' : 'Save product';

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

  window.closeProductModal = function closeProductModal() {
    var modal = document.getElementById('st-product-modal');
    if (!modal) return;
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
        } else if (action === 'close-product-modal') {
          e.preventDefault();
          window.closeProductModal();
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

  function initProductMasterSearch() {
    var searchInput = document.getElementById('st-product-search');
    if (!searchInput || searchInput.getAttribute('data-st-search-bound') === '1') return;
    searchInput.setAttribute('data-st-search-bound', '1');
    var searchChip = searchInput.closest('.st-product-search-chip');
    var countEl = document.getElementById('st-product-count');
    var table = document.getElementById('st-products-table');
    var tableWrap = table && table.closest('.pl-table-wrap');
    var emptyEl = document.getElementById('st-products-search-empty');

    function applyProductSearch() {
      var needle = String(searchInput.value || '').trim().toLowerCase();
      if (searchChip) searchChip.classList.toggle('is-active', !!needle);
      if (!table) return;
      var rows = Array.from(table.querySelectorAll('tbody tr[data-sort-row]'));
      var visible = 0;
      rows.forEach(function (row) {
        var hay = String(row.getAttribute('data-search') || row.textContent || '').toLowerCase();
        var match = !needle || hay.indexOf(needle) !== -1;
        row.hidden = !match;
        if (match) visible += 1;
      });
      if (countEl) {
        countEl.textContent = visible + ' product' + (visible === 1 ? '' : 's');
      }
      if (emptyEl) emptyEl.hidden = !(needle && visible === 0);
      if (tableWrap) tableWrap.hidden = !!(needle && visible === 0);
    }

    searchInput.addEventListener('input', applyProductSearch);
    searchInput.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') {
        searchInput.value = '';
        applyProductSearch();
        searchInput.blur();
      }
      if (e.key === 'Enter') e.preventDefault();
    });
    applyProductSearch();
  }

  function initIndentListSearch() {
    var searchInput = document.getElementById('st-indent-search');
    if (!searchInput || searchInput.getAttribute('data-st-search-bound') === '1') return;
    searchInput.setAttribute('data-st-search-bound', '1');
    var searchChip = searchInput.closest('.st-indent-search-chip');
    var countEl = document.getElementById('st-indent-list-count');
    var table = document.getElementById('st-indent-list-table');
    var tableWrap = table && table.closest('.st-detail-table-wrap');
    var emptyEl = document.getElementById('st-indent-search-empty');

    function applyIndentSearch() {
      var needle = String(searchInput.value || '').trim().toLowerCase();
      if (searchChip) searchChip.classList.toggle('is-active', !!needle);
      if (!table) return;
      var rows = Array.from(table.querySelectorAll('tbody tr[data-sort-row]'));
      var visible = 0;
      rows.forEach(function (row) {
        var hay = String(row.getAttribute('data-search') || row.textContent || '').toLowerCase();
        var match = !needle || hay.indexOf(needle) !== -1;
        row.hidden = !match;
        if (match) visible += 1;
      });
      if (countEl) countEl.textContent = String(visible);
      if (emptyEl) emptyEl.hidden = !(needle && visible === 0);
      if (tableWrap) tableWrap.hidden = !!(needle && visible === 0);
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
        var exportBtn = t.closest('#st-stock-export');
        if (!exportBtn) return;
        e.preventDefault();
        var table = getTable();
        var page = getPage();
        if (!table) return;
        var rows = matchedRows();
        var hasPrices = page && page.getAttribute('data-has-prices') === '1';
        var lines = [
          hasPrices
            ? ['Product', 'Category', 'On hand', 'Unit', 'Status', 'Value']
            : ['Product', 'Category', 'On hand', 'Unit', 'Status']
        ];
        rows.forEach(function (row) {
          var nameEl = row.querySelector('.st-stock-product-name, .pl-name');
          var badge = row.querySelector('.st-stock-badge');
          var cells = row.querySelectorAll('td');
          var line = [
            nameEl ? nameEl.textContent.trim() : '',
            cells[1] ? cells[1].textContent.trim() : String(row.getAttribute('data-category') || ''),
            String(row.getAttribute('data-qty') || ''),
            cells[3] ? cells[3].textContent.trim() : '',
            badge ? badge.textContent.trim() : ''
          ];
          if (hasPrices) line.push(cells[5] ? cells[5].textContent.trim() : '—');
          lines.push(line);
        });
        var csv = lines.map(function (cols) {
          return cols.map(function (c) {
            var s = String(c == null ? '' : c);
            if (/[",\n]/.test(s)) return '"' + s.replace(/"/g, '""') + '"';
            return s;
          }).join(',');
        }).join('\n');
        var blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
        var url = URL.createObjectURL(blob);
        var a = document.createElement('a');
        a.href = url;
        a.download = 'stock-export.csv';
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(function () { URL.revokeObjectURL(url); }, 500);
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
    initIndentListSearch();
    initStockSearch();
    syncIndentLineTotals(document.getElementById('st-indent-form'));
    if (
      !document.getElementById('st-indent-view-modal')
      && !document.getElementById('st-indent-edit-modal')
      && !document.getElementById('st-reject-modal')
      && !document.getElementById('st-stores-ledger-modal')
      && !document.getElementById('st-ledger-pending-modal')
      && !document.getElementById('st-approvals-modal')
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
