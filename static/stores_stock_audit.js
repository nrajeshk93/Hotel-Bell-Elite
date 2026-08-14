/**
 * Weekly Stock Audit — queue + detail panel.
 */
(function () {
  'use strict';

  function $(sel, root) {
    return (root || document).querySelector(sel);
  }

  function $all(sel, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(sel));
  }

  function toast(message, isError) {
    var existing = document.querySelector('[data-st-flash-auto]');
    var el = document.createElement('div');
    el.className = 'st-flash st-flash--' + (isError ? 'error' : 'ok');
    el.setAttribute('data-st-flash-auto', '');
    el.textContent = message || '';
    var host = document.querySelector('.se-content') || document.body;
    host.insertBefore(el, host.firstChild);
    setTimeout(function () {
      if (el.parentNode) el.parentNode.removeChild(el);
    }, 3200);
    if (existing && existing.parentNode) {
      /* leave prior flashes alone */
    }
  }

  function csrfHeaders() {
    var headers = { 'Content-Type': 'application/json', Accept: 'application/json' };
    var meta = document.querySelector('meta[name="csrf-token"]');
    if (meta && meta.content) headers['X-CSRFToken'] = meta.content;
    return headers;
  }

  function fmtQty(n) {
    var v = Number(n);
    if (!isFinite(v)) return '0.000';
    return v.toFixed(2);
  }

  function rows(page) {
    return $all('.st-audit-row', page);
  }

  function visibleRows(page) {
    return rows(page).filter(function (row) {
      return !row.hidden && row.style.display !== 'none';
    });
  }

  function selectedRow(page) {
    return $('.st-audit-row.is-active', page);
  }

  function currentKpi(page) {
    return String(page.getAttribute('data-kpi-filter') || 'total').toLowerCase();
  }

  function rowOrder(row) {
    var n = Number(row.getAttribute('data-order') || 0);
    return isFinite(n) ? n : 0;
  }

  function matchesKpi(row, kpi) {
    var status = String(row.getAttribute('data-status') || '').toLowerCase();
    if (kpi === 'pending') return status === 'pending';
    if (kpi === 'verified') return status === 'verified';
    return true;
  }

  function sortKey(row, kpi) {
    var order = rowOrder(row);
    if (kpi === 'pending') {
      return [matchesKpi(row, 'pending') ? 0 : 1, order];
    }
    if (kpi === 'verified') {
      return [matchesKpi(row, 'verified') ? 0 : 1, order];
    }
    return [order];
  }

  function compareKeys(a, b) {
    var len = Math.max(a.length, b.length);
    for (var i = 0; i < len; i += 1) {
      var av = a[i] != null ? a[i] : 0;
      var bv = b[i] != null ? b[i] : 0;
      if (av < bv) return -1;
      if (av > bv) return 1;
    }
    return 0;
  }

  function auditQueueTable(page) {
    return page.querySelector('.st-audit-queue-table') || page.querySelector('#st-audit-queue table');
  }

  function clearAuditColumnSort(page) {
    var table = auditQueueTable(page);
    if (!table) return;
    table.__auditSortState = { activeKey: '', ascending: true };
    $all('th.pl-sortable', table).forEach(function (header) {
      header.classList.remove('is-sorted-asc', 'is-sorted-desc');
      header.setAttribute('aria-sort', 'none');
    });
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

  function sortAuditByColumn(page, th, forceAscending) {
    var table = auditQueueTable(page);
    var tbody = table && table.tBodies[0];
    if (!table || !tbody || !th) return;
    var key = th.getAttribute('data-sort') || '';
    var type = th.getAttribute('data-sort-type') || 'text';
    var colIndex = Array.prototype.indexOf.call(th.parentNode.children, th);
    if (colIndex < 0 || !key) return;

    var state = table.__auditSortState || { activeKey: '', ascending: true };
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
    table.__auditSortState = state;

    var sorted = $all('tr[data-sort-row]', tbody).slice().sort(function (a, b) {
      var av = cellSortValue(a, colIndex, type);
      var bv = cellSortValue(b, colIndex, type);
      var cmp = 0;
      if (type === 'number') cmp = av - bv;
      else cmp = String(av).localeCompare(String(bv), undefined, { numeric: true, sensitivity: 'base' });
      return state.ascending ? cmp : -cmp;
    });
    sorted.forEach(function (row) {
      tbody.appendChild(row);
    });

    $all('th.pl-sortable', table).forEach(function (header) {
      header.classList.remove('is-sorted-asc', 'is-sorted-desc');
      header.setAttribute('aria-sort', 'none');
    });
    th.classList.add(state.ascending ? 'is-sorted-asc' : 'is-sorted-desc');
    th.setAttribute('aria-sort', state.ascending ? 'ascending' : 'descending');
  }

  function reapplyAuditColumnSort(page) {
    var table = auditQueueTable(page);
    var state = table && table.__auditSortState;
    if (!table || !state || !state.activeKey) return false;
    var th = table.querySelector('th.pl-sortable[data-sort="' + state.activeKey + '"]');
    if (!th) return false;
    sortAuditByColumn(page, th, state.ascending);
    return true;
  }

  function syncKpiSelection(page) {
    var kpi = currentKpi(page);
    $all('.st-audit-kpi-row .st-audit-kpi[data-kpi]', page).forEach(function (card) {
      var on = String(card.getAttribute('data-kpi') || '') === kpi;
      card.classList.toggle('is-active', on);
      card.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
  }

  function setKpiFilter(page, kpi) {
    var next = String(kpi || 'total').toLowerCase();
    if (currentKpi(page) === next && next !== 'total') {
      next = 'total';
    }
    page.setAttribute('data-kpi-filter', next);
    clearAuditColumnSort(page);
    syncKpiSelection(page);
    applyAuditFilters(page);
  }

  function currentCategory() {
    var el = document.getElementById('st-audit-category');
    return String((el && el.value) || 'all').trim().toLowerCase();
  }

  function rowCategory(row) {
    return String((row && row.getAttribute('data-category')) || '')
      .trim()
      .toLowerCase() || 'uncategorised';
  }

  function applyAuditFilters(page) {
    var searchEl = document.getElementById('st-audit-search');
    var chip = searchEl && searchEl.closest('.st-audit-search-chip');
    var needle = String((searchEl && searchEl.value) || '').trim().toLowerCase();
    if (chip) chip.classList.toggle('is-active', !!needle);
    var kpi = currentKpi(page);
    var category = currentCategory();
    var tbody = page.querySelector('#st-audit-queue tbody');
    var all = rows(page);
    if (!reapplyAuditColumnSort(page)) {
      var sorted = all.slice().sort(function (a, b) {
        return compareKeys(sortKey(a, kpi), sortKey(b, kpi));
      });
      if (tbody) {
        sorted.forEach(function (row) {
          tbody.appendChild(row);
        });
      }
      all = sorted;
    } else {
      all = rows(page);
    }
    var shown = 0;
    all.forEach(function (row, idx) {
      var hay = String(row.getAttribute('data-search') || row.textContent || '').toLowerCase();
      var searchOk = !needle || hay.indexOf(needle) !== -1;
      var kpiOk = matchesKpi(row, kpi);
      var catOk = category === 'all' || rowCategory(row) === category;
      var match = searchOk && kpiOk && catOk;
      row.hidden = !match;
      var numCell = row.querySelector('.st-audit-col-num');
      if (numCell && match) {
        shown += 1;
        numCell.textContent = String(shown);
      } else if (numCell) {
        numCell.textContent = String(idx + 1);
      }
    });
    var emptyEl = $('#st-audit-search-empty', page);
    var queue = $('#st-audit-queue', page);
    var hasFilters = !!needle || kpi !== 'total' || category !== 'all';
    if (emptyEl) {
      emptyEl.hidden = shown > 0 || all.length === 0;
      if (!emptyEl.hidden) {
        emptyEl.textContent = needle
          ? 'No products match your search.'
          : category !== 'all'
            ? 'No products in this category.'
            : kpi === 'total'
              ? 'No products to show.'
              : 'No products in this KPI group.';
      }
    }
    if (queue) queue.hidden = shown === 0 && all.length > 0;
    var showing = $('#st-audit-showing', page);
    if (showing) {
      if (!shown) {
        showing.textContent = hasFilters ? 'No matches' : 'Showing 0 products';
      } else {
        showing.textContent = 'Showing 1 to ' + shown + ' of ' + all.length + ' products';
      }
    }
    var active = selectedRow(page);
    if (active && active.hidden) {
      var first = visibleRows(page)[0];
      if (first) selectLine(page, first.getAttribute('data-line-id'));
    }
  }

  function applyAuditSearch(page) {
    applyAuditFilters(page);
  }

  function updateKpis(page, kpis) {
    if (!kpis) return;
    var total = Number(kpis.total || 0);
    var pending = Number(kpis.pending || 0);
    var verified = Number(kpis.verified || 0);
    var el;
    el = $('#st-audit-kpi-total', page);
    if (el) el.textContent = String(total);
    el = $('#st-audit-kpi-pending', page);
    if (el) el.textContent = String(pending);
    el = $('#st-audit-kpi-verified', page);
    if (el) el.textContent = String(verified);
    el = $('#st-audit-remaining', page);
    if (el) el.textContent = 'Remaining: ' + pending + ' items';
    el = $('#st-audit-queue-count', page);
    if (el) el.textContent = total + ' product' + (total === 1 ? '' : 's');
  }

  function setReasonLocked(page, locked) {
    var root = $('#st-audit-reason-listbox', page);
    var trigger = $('#st-audit-reason-trigger', page);
    if (root) root.classList.toggle('is-disabled', !!locked);
    if (trigger) {
      trigger.disabled = !!locked;
      if (!locked) trigger.removeAttribute('disabled');
    }
  }

  function syncVariance(page) {
    var actualEl = $('#st-audit-actual', page);
    var row = selectedRow(page);
    if (!actualEl || !row) return;
    var locked = row.getAttribute('data-status') === 'verified';
    setReasonLocked(page, locked);
    // Always compare against the audit snapshot so verified/on-hand updates
    // do not collapse the variance while editing.
    var system = Number(
      row.getAttribute('data-snapshot-qty') ||
        row.getAttribute('data-system-qty') ||
        0
    );
    var actual = Number(actualEl.value);
    var box = $('#st-audit-variance', page);
    var text = $('#st-audit-variance-text', page);
    var pctEl = $('#st-audit-variance-pct', page);
    var callout = $('#st-audit-callout', page);
    var req = $('#st-audit-reason-req', page);
    var unit = row.getAttribute('data-unit') || '';
    if (!isFinite(actual)) {
      if (box) box.hidden = true;
      if (callout) callout.hidden = true;
      if (req) req.hidden = true;
      syncReasonOptions(page, 0);
      return;
    }
    var variance = Math.round((actual - system) * 1000) / 1000;
    var pct = system ? (variance / system) * 100 : variance === 0 ? 0 : 100;
    var hasVar = Math.abs(variance) >= 0.0001;
    if (box) {
      box.hidden = !hasVar;
      box.classList.toggle('is-zero', !hasVar);
      box.classList.toggle('is-positive', hasVar && variance > 0);
      box.classList.toggle('is-negative', hasVar && variance < 0);
    }
    if (text) {
      text.textContent =
        'Variance ' +
        (variance > 0 ? '+' : '') +
        fmtQty(variance) +
        (unit ? ' ' + unit : '');
    }
    if (pctEl) {
      pctEl.textContent =
        (pct > 0 ? '+' : '') + pct.toFixed(2) + '%';
    }
    if (callout) callout.hidden = !hasVar;
    if (req) req.hidden = !hasVar;
    if (!hasVar) clearReasonError(page);
    syncReasonOptions(page, hasVar ? variance : 0);
  }

  function syncReasonOptions(page, variance) {
    var root = $('#st-audit-reason-listbox', page);
    if (!root) return;
    var row = selectedRow(page);
    var locked = !!(row && row.getAttribute('data-status') === 'verified');
    setReasonLocked(page, locked);
    var options = $all('.se-filter-listbox-option[data-variance-sign]', root);
    var reason = $('#st-audit-reason', page);
    var current = reason ? String(reason.value || '').trim() : '';
    if (locked) {
      options.forEach(function (opt) {
        opt.hidden = false;
        opt.removeAttribute('hidden');
        opt.setAttribute('aria-hidden', 'false');
      });
      return;
    }
    var sign = variance > 0.0001 ? 'positive' : 'negative';
    var currentAllowed = !current;
    options.forEach(function (opt) {
      var optSign = opt.getAttribute('data-variance-sign') || 'any';
      var value = String(opt.getAttribute('data-value') || '').trim();
      var show = optSign === 'any' || optSign === sign;
      opt.hidden = !show;
      if (show) opt.removeAttribute('hidden');
      else opt.setAttribute('hidden', '');
      opt.setAttribute('aria-hidden', show ? 'false' : 'true');
      if (!show) {
        opt.classList.remove('is-selected');
        opt.setAttribute('aria-selected', 'false');
      } else if (value && value === current) {
        currentAllowed = true;
        opt.classList.add('is-selected');
        opt.setAttribute('aria-selected', 'true');
      }
    });
    if (current && !currentAllowed) {
      if (typeof window.resetEpListbox === 'function') {
        window.resetEpListbox('st-audit-reason', '', 'Select reason…');
      } else if (reason) {
        reason.value = '';
        var valueEl = $('#st-audit-reason-value', page);
        if (valueEl) {
          valueEl.textContent = 'Select reason…';
          valueEl.classList.add('is-placeholder');
        }
      }
      clearReasonError(page);
    }
  }

  function selectLine(page, lineId, opts) {
    opts = opts || {};
    var list = rows(page);
    var target = null;
    list.forEach(function (row) {
      var match = String(row.getAttribute('data-line-id')) === String(lineId);
      row.classList.toggle('is-active', match);
      if (match) target = row;
    });
    if (!target) return;
    var panel = $('#st-audit-panel', page);
    var layout = $('#st-audit-layout', page);
    if (panel) {
      panel.hidden = false;
      panel.classList.remove('is-empty');
    }
    if (layout) layout.classList.add('is-panel-open');

    var name = $('#st-audit-panel-name', page);
    var cat = $('#st-audit-panel-cat', page);
    var system = $('#st-audit-system', page);
    var unit = $('#st-audit-unit', page);
    var lineIdEl = $('#st-audit-line-id', page);
    var actual = $('#st-audit-actual', page);
    var reason = $('#st-audit-reason', page);
    var remarks = $('#st-audit-remarks', page);

    if (name) name.textContent = target.getAttribute('data-name') || '';
    if (cat) cat.textContent = target.getAttribute('data-category') || 'Uncategorised';
    if (system) {
      system.textContent =
        fmtQty(target.getAttribute('data-system-qty')) +
        ' ' +
        (target.getAttribute('data-unit') || '');
    }
    if (unit) unit.textContent = target.getAttribute('data-unit') || '';
    if (lineIdEl) lineIdEl.value = String(lineId);
    var locked = target.getAttribute('data-status') === 'verified';
    if (actual) {
      var existing = target.getAttribute('data-actual') || '';
      actual.value =
        existing !== ''
          ? existing
          : fmtQty(
              target.getAttribute('data-snapshot-qty') ||
                target.getAttribute('data-system-qty')
            );
      actual.disabled = locked;
      if (!locked) actual.removeAttribute('disabled');
    }
    if (reason) {
      var reasonVal = target.getAttribute('data-reason') || '';
      var reasonLabel = 'Select reason…';
      var reasonRoot = $('#st-audit-reason-listbox', page);
      if (reasonRoot) {
        var reasonOpt = reasonRoot.querySelector(
          '.se-filter-listbox-option[data-value="' + String(reasonVal).replace(/\\/g, '\\\\').replace(/"/g, '\\"') + '"]'
        );
        if (reasonOpt) {
          reasonLabel =
            reasonOpt.getAttribute('data-label') ||
            (reasonOpt.textContent || '').trim() ||
            reasonLabel;
        }
        reasonRoot.classList.toggle('is-disabled', locked);
        var reasonTrigger = $('#st-audit-reason-trigger', page);
        if (reasonTrigger) {
          reasonTrigger.disabled = locked;
          if (!locked) reasonTrigger.removeAttribute('disabled');
        }
      }
      if (typeof window.resetEpListbox === 'function') {
        window.resetEpListbox('st-audit-reason', reasonVal, reasonLabel);
      } else {
        reason.value = reasonVal;
      }
      setReasonLocked(page, locked);
    }
    if (remarks) {
      remarks.value = target.getAttribute('data-remarks') || '';
      remarks.disabled = locked;
      if (!locked) remarks.removeAttribute('disabled');
      var charEl = $('#st-audit-char', page);
      if (charEl) charEl.textContent = remarks.value.length + '/200';
    }
    clearReasonError(page);
    syncVariance(page);

    if (opts.pushUrl !== false) {
      try {
        var base = page.getAttribute('data-page-url') || window.location.pathname;
        var url = new URL(base, window.location.origin);
        url.searchParams.set('line_id', String(lineId));
        var outlet = page.getAttribute('data-outlet');
        if (outlet) url.searchParams.set('outlet', outlet);
        var place = page.getAttribute('data-place');
        if (place) url.searchParams.set('place', place);
        window.history.replaceState({}, '', url.pathname + url.search);
      } catch (err) {
        /* ignore */
      }
    }
  }

  function markRowStatus(row, status) {
    if (!row) return;
    var next = status === 'skipped' ? 'pending' : status;
    row.setAttribute('data-status', next);
    var badge = row.querySelector('.st-audit-badge');
    if (!badge) return;
    var statusCell = badge.closest('td');
    if (statusCell) statusCell.setAttribute('data-sort-value', next);
    badge.className = 'st-audit-badge st-audit-badge--' + next;
    badge.textContent =
      next === 'verified' ? 'Verified' : 'Pending';
  }

  function updateRowStockQty(row, qty) {
    if (!row || !isFinite(qty)) return;
    var shown = fmtQty(qty);
    row.setAttribute('data-system-qty', String(qty));
    var qtyCell = row.querySelector('.st-audit-qty');
    if (qtyCell) {
      qtyCell.textContent = shown;
      qtyCell.setAttribute('data-sort-value', String(qty));
    }
    var system = $('#st-audit-system', document.getElementById('st-audit-page'));
    if (system && row.classList.contains('is-active')) {
      system.textContent = shown + ' ' + (row.getAttribute('data-unit') || '');
    }
  }

  function postJson(url, body) {
    return fetch(url, {
      method: 'POST',
      credentials: 'same-origin',
      headers: csrfHeaders(),
      body: JSON.stringify(body || {})
    }).then(function (resp) {
      return resp.json().then(function (data) {
        return { ok: resp.ok, status: resp.status, data: data };
      });
    });
  }

  function clearReasonError(page) {
    var err = $('#st-audit-reason-error', page);
    var root = $('#st-audit-reason-listbox', page);
    if (err) err.hidden = true;
    if (root) root.classList.remove('is-invalid');
  }

  function showReasonError(page) {
    var err = $('#st-audit-reason-error', page);
    var root = $('#st-audit-reason-listbox', page);
    if (err) err.hidden = false;
    if (root) {
      root.classList.add('is-invalid');
      var trigger = $('#st-audit-reason-trigger', page);
      if (trigger) {
        try { trigger.focus(); } catch (e) {}
      }
    }
    toast('Please select reason to save', true);
  }

  function verify(page, goNext) {
    var lineId = ($('#st-audit-line-id', page) || {}).value;
    var actual = ($('#st-audit-actual', page) || {}).value;
    var reason = String(($('#st-audit-reason', page) || {}).value || '').trim();
    var remarks = ($('#st-audit-remarks', page) || {}).value;
    var url = page.getAttribute('data-verify-url');
    if (!url || !lineId) return;
    clearReasonError(page);
    var row = selectedRow(page);
    var system = row
      ? Number(
          row.getAttribute('data-snapshot-qty') ||
            row.getAttribute('data-system-qty') ||
            0
        )
      : 0;
    var actualN = Number(actual);
    var hasVar = isFinite(actualN) && Math.abs(actualN - system) >= 0.0001;
    if (hasVar && !reason) {
      showReasonError(page);
      return;
    }
    var btn = $('#st-audit-verify', page);
    if (btn) btn.disabled = true;
    postJson(url, {
      line_id: Number(lineId),
      actual_qty: actual,
      reason: reason,
      remarks: remarks,
      go_next: goNext ? '1' : '0'
    })
      .then(function (result) {
        if (!result.ok || !result.data || !result.data.ok) {
          throw new Error(
            (result.data && result.data.error) || 'Could not verify item.'
          );
        }
        var row = selectedRow(page);
        var snapshot = row
          ? Number(row.getAttribute('data-snapshot-qty') || row.getAttribute('data-system-qty') || 0)
          : 0;
        var actualN = Number(
          (result.data.line && result.data.line.actual_qty != null
            ? result.data.line.actual_qty
            : actual)
        );
        markRowStatus(row, 'verified');
        if (row) {
          row.setAttribute('data-actual', String(isFinite(actualN) ? actualN : actual));
          row.setAttribute('data-reason', reason || '');
          row.setAttribute('data-remarks', remarks || '');
          if (!row.getAttribute('data-snapshot-qty')) {
            row.setAttribute('data-snapshot-qty', String(snapshot));
          }
          var varianceQty = isFinite(actualN)
            ? Math.round((actualN - snapshot) * 1000) / 1000
            : 0;
          row.setAttribute('data-variance-qty', String(varianceQty));
          if (result.data.line && result.data.line.variance_value != null) {
            row.setAttribute('data-variance-value', String(result.data.line.variance_value));
          } else {
            row.setAttribute('data-variance-value', String(varianceQty));
          }
          var search = String(row.getAttribute('data-search') || '');
          row.setAttribute(
            'data-search',
            search.replace(/\bpending\b|\bskipped\b|\bverified\b/g, 'verified')
          );
          if (isFinite(actualN)) {
            updateRowStockQty(row, actualN);
          }
        }
        updateKpis(page, result.data.kpis);
        applyAuditFilters(page);
        toast(result.data.message || 'Verified.');
        if (goNext && result.data.next_line_id) {
          selectLine(page, result.data.next_line_id);
        } else {
          selectLine(page, lineId);
          if (goNext) toast('All remaining items are done.');
        }
      })
      .catch(function (err) {
        toast(err.message || 'Could not verify.', true);
      })
      .then(function () {
        if (btn) btn.disabled = false;
      });
  }

  function openHistory(page) {
    var modal = $('#st-audit-history-modal', page) || document.getElementById('st-audit-history-modal');
    if (!modal) return;
    modal.hidden = false;
    var url = page.getAttribute('data-history-url');
    var body = $('#st-audit-history-body', modal);
    if (!url || !body) return;
    var outlet = page.getAttribute('data-outlet') || '';
    var place = page.getAttribute('data-place') || '';
    var qs = [];
    if (outlet) qs.push('outlet=' + encodeURIComponent(outlet));
    if (place) qs.push('place=' + encodeURIComponent(place));
    fetch(url + (qs.length ? '?' + qs.join('&') : ''), {
      credentials: 'same-origin',
      headers: { Accept: 'application/json' }
    })
      .then(function (resp) {
        return resp.json();
      })
      .then(function (data) {
        if (!data || !data.ok) return;
        var rowsHtml = (data.history || [])
          .map(function (row) {
            return (
              '<tr><td>' +
              (row.label || 'Audit #' + row.id) +
              '</td><td>' +
              (row.completed_at || '—') +
              '</td><td>' +
              (row.started_by_name || '—') +
              '</td><td>' +
              (row.verified_count || 0) +
              '/' +
              (row.line_count || 0) +
              '</td></tr>'
            );
          })
          .join('');
        body.innerHTML = rowsHtml
          ? '<table class="pl-table"><thead><tr><th>Audit</th><th>Completed</th><th>By</th><th>Verified</th></tr></thead><tbody>' +
            rowsHtml +
            '</tbody></table>'
          : '<div class="pl-empty">No completed audits yet.</div>';
      })
      .catch(function () {
        /* keep existing body */
      });
  }

  function closeHistory(page) {
    var modal = $('#st-audit-history-modal', page) || document.getElementById('st-audit-history-modal');
    if (modal) modal.hidden = true;
  }

  function startNew(page) {
    var url = page.getAttribute('data-new-url');
    if (!url) return;
    if (!window.confirm('Complete the current audit and start a new queue from current stock?')) {
      return;
    }
    postJson(url, {
      outlet: page.getAttribute('data-outlet') || '',
      place: page.getAttribute('data-place') || ''
    })
      .then(function (result) {
        if (!result.ok || !result.data || !result.data.ok) {
          throw new Error(
            (result.data && result.data.error) || 'Could not start a new audit.'
          );
        }
        window.location.href = result.data.redirect || page.getAttribute('data-page-url');
      })
      .catch(function (err) {
        toast(err.message || 'Could not start a new audit.', true);
      });
  }

  function initStockAudit() {
    var page = document.getElementById('st-audit-page');
    if (!page || page.getAttribute('data-st-audit-ready') === '1') return;
    page.setAttribute('data-st-audit-ready', '1');

    page.addEventListener('click', function (event) {
      var kpiCard = event.target.closest('.st-audit-kpi-row .st-audit-kpi[data-kpi]');
      if (kpiCard && page.contains(kpiCard)) {
        event.preventDefault();
        setKpiFilter(page, kpiCard.getAttribute('data-kpi') || 'total');
        return;
      }
      var row = event.target.closest('.st-audit-row');
      if (row && page.contains(row)) {
        var id = row.getAttribute('data-line-id');
        if (id) {
          event.preventDefault();
          selectLine(page, id);
        }
        return;
      }
      if (event.target.closest('#st-audit-verify')) {
        event.preventDefault();
        verify(page, false);
        return;
      }
      if (event.target.closest('#st-audit-reason-listbox .se-filter-listbox-option')) {
        var opt = event.target.closest('.se-filter-listbox-option');
        if (opt && String(opt.getAttribute('data-value') || '').trim()) {
          clearReasonError(page);
        }
      }
      if (event.target.closest('[data-st-audit-history-close]')) {
        closeHistory(page);
        return;
      }
    });

    var historyBtn = document.getElementById('st-audit-history-btn');
    if (historyBtn && historyBtn.getAttribute('data-st-audit-bound') !== '1') {
      historyBtn.setAttribute('data-st-audit-bound', '1');
      historyBtn.addEventListener('click', function () {
        openHistory(page);
      });
    }
    var newBtn = document.getElementById('st-audit-new-btn');
    if (newBtn && newBtn.getAttribute('data-st-audit-bound') !== '1') {
      newBtn.setAttribute('data-st-audit-bound', '1');
      newBtn.addEventListener('click', function () {
        startNew(page);
      });
    }

    var form = $('#st-audit-form', page);
    if (form) {
      form.addEventListener('submit', function (event) {
        event.preventDefault();
        event.stopPropagation();
        verify(page, false);
      });
    }
    var actual = $('#st-audit-actual', page);
    if (actual) {
      actual.addEventListener('input', function () {
        syncVariance(page);
      });
    }
    var remarks = $('#st-audit-remarks', page);
    if (remarks) {
      remarks.addEventListener('input', function () {
        var charEl = $('#st-audit-char', page);
        if (charEl) charEl.textContent = remarks.value.length + '/200';
      });
    }

    var searchInput = document.getElementById('st-audit-search');
    if (searchInput && searchInput.getAttribute('data-st-audit-search-bound') !== '1') {
      searchInput.setAttribute('data-st-audit-search-bound', '1');
      searchInput.addEventListener('input', function () {
        applyAuditSearch(page);
      });
      searchInput.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') {
          searchInput.value = '';
          applyAuditSearch(page);
          searchInput.blur();
        }
        if (e.key === 'Enter') e.preventDefault();
      });
    }

    initAuditTableSort(page);
    if (typeof window.initEpListboxes === 'function') {
      window.initEpListboxes();
    }
    window.stAuditCategoryChanged = function () {
      applyAuditFilters(page);
    };
    page.setAttribute('data-kpi-filter', 'total');
    syncKpiSelection(page);
    applyAuditFilters(page);

    syncVariance(page);
  }

  function initAuditTableSort(page) {
    var table = auditQueueTable(page);
    if (!table || table.getAttribute('data-st-audit-sort-bound') === '1') return;
    table.setAttribute('data-st-audit-sort-bound', '1');
    if (!table.__auditSortState) {
      table.__auditSortState = { activeKey: '', ascending: true };
    }
    $all('th.pl-sortable', table).forEach(function (th) {
      th.addEventListener('click', function () {
        sortAuditByColumn(page, th);
        applyAuditFilters(page);
      });
      th.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          sortAuditByColumn(page, th);
          applyAuditFilters(page);
        }
      });
    });
  }

  window.initStockAudit = initStockAudit;
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initStockAudit);
  } else {
    initStockAudit();
  }
})();
