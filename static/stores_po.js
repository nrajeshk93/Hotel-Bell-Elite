/* Purchase Order — Send to Supplier client logic */
(function () {
  'use strict';

  function softNavigate(url) {
    if (!url) return;
    if (typeof window.deNavigateWithTransition === 'function') {
      window.deNavigateWithTransition(url);
    } else if (typeof window.deSoftRefresh === 'function') {
      window.deSoftRefresh(url);
    } else {
      window.location.assign(url);
    }
  }

  // A hard reload drops out of full screen (the browser only grants it on a
  // user gesture), so re-render the current URL through the soft-nav shell.
  function softReload() {
    if (typeof window.deInvalidateSoftNavCache === 'function') {
      try { window.deInvalidateSoftNavCache(window.location.href); } catch (e) {}
    }
    if (typeof window.deSoftRefresh === 'function') {
      window.deSoftRefresh();
    } else {
      window.location.reload();
    }
  }

  window.stPoIndentChanged = function (root, value) {
    if (!root || !value) return;
    var outlet = root.getAttribute('data-st-po-outlet') || '';
    try {
      var url = new URL('/stores/orders/' + encodeURIComponent(String(value)), window.location.origin);
      if (outlet) url.searchParams.set('outlet', outlet);
      softNavigate(url.pathname + url.search);
    } catch (e) {
      var qs = outlet ? ('?outlet=' + encodeURIComponent(outlet)) : '';
      softNavigate('/stores/orders/' + encodeURIComponent(String(value)) + qs);
    }
  };

  // Legacy compose supplier picker — compose preview was removed.
  window.stPoSupplierPicked = function () {};

  function toast(message, kind) {
    var text = String(message || '').trim();
    if (!text) return;
    if (typeof window.hbeToast === 'function') {
      window.hbeToast(text, kind || 'ok');
      return;
    }
    var host =
      document.querySelector('.st-po-page .st-list-card') ||
      document.querySelector('.st-po-page') ||
      document.querySelector('.se-content') ||
      document.body;
    if (!host) {
      if (kind === 'error') window.alert(text);
      return;
    }
    var existing = host.querySelector('[data-st-po-toast]');
    if (existing && existing.parentNode) existing.parentNode.removeChild(existing);
    var el = document.createElement('div');
    el.className = 'st-flash st-flash--' + (kind === 'error' ? 'error' : 'ok');
    el.setAttribute('data-st-po-toast', '1');
    el.setAttribute('data-st-flash-auto', '1');
    el.setAttribute('role', 'status');
    el.textContent = text;
    var insertAt = host.querySelector('.st-card-body, .st-list-body') || host;
    if (insertAt.firstChild) {
      insertAt.insertBefore(el, insertAt.firstChild);
    } else {
      insertAt.appendChild(el);
    }
    window.setTimeout(function () {
      if (!el.parentNode) return;
      el.classList.add('is-leaving');
      window.setTimeout(function () {
        if (el.parentNode) el.parentNode.removeChild(el);
      }, 320);
    }, 4200);
  }

  function safeJson(el) {
    if (!el) return null;
    try {
      return JSON.parse(el.textContent || 'null');
    } catch (err) {
      return null;
    }
  }

  function pdfUrlFor(shell, supplierId) {
    var base = shell.getAttribute('data-pdf-url-base') || '';
    return base.replace(/\/0(\/?$)/, '/' + encodeURIComponent(String(supplierId)) + '$1');
  }

  function modalHost() {
    return document.getElementById('de-fs-app') || document.body;
  }

  function mountPoPdfModal(modal) {
    if (!modal) return;
    var host = modalHost();
    if (host && modal.parentElement !== host) host.appendChild(modal);
  }

  function closePoPdfModal() {
    var modal = document.getElementById('st-po-pdf-modal');
    if (!modal) return;
    modal.classList.remove('open');
    modal.setAttribute('aria-hidden', 'true');
    var frame = document.getElementById('st-po-pdf-frame');
    if (frame) frame.src = 'about:blank';
  }

  function openPoPdfModal(url, title) {
    var modal = document.getElementById('st-po-pdf-modal');
    var frame = document.getElementById('st-po-pdf-frame');
    var titleEl = document.getElementById('st-po-pdf-title');
    var subEl = document.getElementById('st-po-pdf-sub');
    var download = document.getElementById('st-po-pdf-download');
    if (!modal || !frame || !url) return;
    mountPoPdfModal(modal);
    var label = String(title || '').trim() || 'Purchase Order';
    if (titleEl) titleEl.textContent = label;
    if (subEl) {
      subEl.hidden = true;
      subEl.textContent = '';
    }
    if (download) {
      download.href = url;
      download.setAttribute('download', '');
    }
    // Cache-bust so a previously viewed PO does not stick in the iframe.
    var sep = url.indexOf('?') >= 0 ? '&' : '?';
    frame.src = url + sep + '_=' + Date.now();
    modal.classList.add('open');
    modal.setAttribute('aria-hidden', 'false');
  }

  function initPoPdfModal() {
    var page = document.querySelector('[data-st-po-page]');
    if (!page || page.getAttribute('data-st-po-pdf-bound') === '1') return;
    page.setAttribute('data-st-po-pdf-bound', '1');

    document.addEventListener('click', function (event) {
      var openLink = event.target.closest('[data-st-po-pdf]');
      if (openLink) {
        var href = openLink.getAttribute('href') || '';
        if (!href || href === '#') return;
        event.preventDefault();
        event.stopPropagation();
        openPoPdfModal(href, openLink.getAttribute('data-po-title') || openLink.getAttribute('aria-label') || '');
        return;
      }
      if (event.target.closest('#st-po-pdf-close')) {
        event.preventDefault();
        closePoPdfModal();
        return;
      }
      var modal = document.getElementById('st-po-pdf-modal');
      if (modal && modal.classList.contains('open') && event.target === modal) {
        closePoPdfModal();
      }
    }, true);

    document.addEventListener('keydown', function (event) {
      if (event.key !== 'Escape') return;
      var modal = document.getElementById('st-po-pdf-modal');
      if (modal && modal.classList.contains('open')) closePoPdfModal();
    });
  }

  var poResendHandler = null;

  function removeSentPoRow(btn) {
    var page = document.querySelector('[data-st-po-page]');
    if (!page || page.getAttribute('data-po-tab') !== 'send') return;
    var row = btn && btn.closest ? btn.closest('tr[data-sort-row], tr') : null;
    if (!row || !row.parentElement) return;
    row.parentElement.removeChild(row);

    var countEl = document.getElementById('st-indent-list-count');
    var tbody = document.querySelector('#st-indent-list-table tbody');
    var remaining = tbody ? tbody.querySelectorAll('tr').length : 0;
    if (countEl) countEl.textContent = String(remaining);

    if (remaining > 0) return;

    var wrap = document.querySelector('.st-po-page .st-detail-table-wrap');
    var listBody = document.querySelector('.st-po-page .st-list-body');
    if (wrap) wrap.remove();
    var searchEmpty = document.getElementById('st-indent-search-empty');
    if (searchEmpty) searchEmpty.remove();
    if (listBody && !listBody.querySelector('.st-empty')) {
      var empty = document.createElement('div');
      empty.className = 'st-empty';
      empty.innerHTML =
        '<strong>No purchase orders waiting to send</strong>' +
        '<p>Generated purchase orders appear here until they are sent to the supplier or the indent is fully stocked inward.</p>';
      listBody.appendChild(empty);
    }
  }

  function sendPoFromButton(btn) {
    if (!btn || btn.disabled) return;
    var sendUrl = btn.getAttribute('data-send-url') || '';
    var supplierId = btn.getAttribute('data-supplier-id') || '';
    var poNo = btn.getAttribute('data-po-no') || '';
    var fallbackName = (btn.getAttribute('data-supplier-name') || '').trim() || 'Supplier';
    if (!sendUrl || !supplierId) {
      toast('Could not send purchase order.', 'error');
      return;
    }
    btn.disabled = true;
    toast('Sending purchase order to ' + fallbackName + '…', 'ok');
    var controller = typeof AbortController === 'function' ? new AbortController() : null;
    var abortTimer = 0;
    if (controller) {
      abortTimer = window.setTimeout(function () {
        try { controller.abort(); } catch (e) {}
      }, 60000);
    }
    fetch(sendUrl, {
      method: 'POST',
      credentials: 'same-origin',
      signal: controller ? controller.signal : undefined,
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json'
      },
      body: JSON.stringify({
        supplier_id: Number(supplierId),
        po_no: poNo,
        include_pdf: true
      })
    }).then(function (res) {
      return res.json().then(function (payload) {
        return { ok: res.ok && payload && payload.ok, httpStatus: res.status, payload: payload || {} };
      }).catch(function () {
        return { ok: false, httpStatus: res.status, payload: { error: 'Could not send purchase order.' } };
      });
    }).then(function (res) {
      if (abortTimer) window.clearTimeout(abortTimer);
      if (!res.ok) {
        btn.disabled = false;
        toast((res.payload && res.payload.error) || 'Could not send purchase order.', 'error');
        return;
      }
      var supplierName = String(
        (res.payload && res.payload.supplier_name) || fallbackName || 'Supplier'
      ).trim() || 'Supplier';
      var phone = String((res.payload && res.payload.phone) || '').trim();
      var note = res.payload && res.payload.dry_run ? ' (dry run)' : '';
      var meta = String((res.payload && res.payload.meta_status) || '').trim();
      var phoneNote = phone ? ' (+' + phone + ')' : '';
      var metaNote = meta && !note ? ' — Meta: ' + meta : '';
      toast(
        'Purchase Order has been sent to ' + supplierName + phoneNote + note + metaNote + '.',
        'ok'
      );
      // Update status pill on Purchase Orders tab (row is not removed there).
      var row = btn.closest('tr');
      if (row) {
        var pill = row.querySelector('.cp-status-pill');
        if (pill) {
          pill.className = 'cp-status-pill cp-status-pill--approved';
          pill.textContent = res.payload && res.payload.dry_run ? 'Sent (dry run)' : 'Sent';
        }
      }
      removeSentPoRow(btn);
      btn.disabled = false;
      if (typeof window.deInvalidateSoftNavCache === 'function') {
        try { window.deInvalidateSoftNavCache(window.location.href); } catch (e) {}
      }
    }).catch(function (err) {
      if (abortTimer) window.clearTimeout(abortTimer);
      btn.disabled = false;
      var aborted = err && (err.name === 'AbortError' || String(err).indexOf('AbortError') !== -1);
      toast(
        aborted
          ? 'Send timed out. Check WhatsApp connection and try again.'
          : 'Could not send purchase order.',
        'error'
      );
    });
  }

  function initPoResend() {
    // Wire each button on every soft-nav boot (idempotent per node).
    var buttons = document.querySelectorAll('[data-st-po-resend]');
    Array.prototype.forEach.call(buttons, function (btn) {
      // Clear stuck disabled state from a previous hung send attempt.
      if (btn.disabled && !btn.hasAttribute('data-st-po-send-locked')) {
        btn.disabled = false;
      }
      if (btn.getAttribute('data-st-po-resend-wired') === '1') return;
      btn.setAttribute('data-st-po-resend-wired', '1');
      btn.addEventListener('click', function (event) {
        event.preventDefault();
        event.stopPropagation();
        sendPoFromButton(btn);
      });
    });

    // Also keep one document-level delegate for dynamically swapped rows.
    if (!poResendHandler) {
      poResendHandler = function (event) {
        var target = event.target;
        if (target && target.nodeType === 3) target = target.parentElement;
        var btn = target && target.closest ? target.closest('[data-st-po-resend]') : null;
        if (!btn) return;
        // Prefer the per-button listener when already wired.
        if (btn.getAttribute('data-st-po-resend-wired') === '1') return;
        event.preventDefault();
        event.stopPropagation();
        sendPoFromButton(btn);
      };
      document.addEventListener('click', poResendHandler);
    }
  }

  window.stPoSendFromButton = sendPoFromButton;

  function escapeHtml(text) {
    return String(text == null ? '' : text)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function initPoSendConfirmModal() {
    var modal = document.getElementById('st-po-send-confirm-modal');
    if (!modal || modal.getAttribute('data-st-po-send-confirm-bound') === '1') return;
    modal.setAttribute('data-st-po-send-confirm-bound', '1');

    var listEl = document.getElementById('st-po-send-confirm-list');
    var sendBtn = document.getElementById('st-po-send-confirm-send');
    var skipBtn = document.getElementById('st-po-send-confirm-skip');
    var closeBtn = document.getElementById('st-po-send-confirm-close');
    var state = { issued: [], redirect: '', sending: false };

    function syncSendBtn() {
      if (!sendBtn || !listEl) return;
      var checked = listEl.querySelectorAll('.st-po-send-confirm-check:checked:not(:disabled)');
      sendBtn.disabled = state.sending || !checked.length;
    }

    function closeModal() {
      modal.classList.remove('open');
      modal.setAttribute('aria-hidden', 'true');
    }

    function finishAndNavigate() {
      closeModal();
      var url = state.redirect || '/stores/orders?tab=send';
      softNavigate(url);
    }

    function openModal(issued, redirect) {
      state.issued = Array.isArray(issued) ? issued : [];
      state.redirect = redirect || '/stores/orders?tab=send';
      state.sending = false;
      if (!listEl) return;
      if (!state.issued.length) {
        finishAndNavigate();
        return;
      }
      listEl.innerHTML = state.issued.map(function (row, idx) {
        var canSend = !!row.can_send;
        var phone = String(row.phone || '').trim();
        var name = String(row.supplier_name || 'Supplier');
        var poNo = String(row.po_no || '');
        var items = Number(row.item_count || 0);
        var itemLabel = items === 1 ? '1 item' : (items + ' items');
        return (
          '<li class="st-po-send-confirm-row' + (canSend ? '' : ' is-disabled') + '">' +
            '<label class="st-po-send-confirm-label">' +
              '<input type="checkbox" class="st-po-send-confirm-check"' +
                ' data-idx="' + idx + '"' +
                (canSend ? ' checked' : ' disabled') +
                ' aria-label="Send ' + escapeHtml(poNo) + ' to ' + escapeHtml(name) + '">' +
              '<span class="st-po-send-confirm-meta">' +
                '<strong class="st-po-send-confirm-name">' + escapeHtml(name) + '</strong>' +
                '<span class="st-po-send-confirm-po">' + escapeHtml(poNo) +
                  (items ? ' · ' + escapeHtml(itemLabel) : '') + '</span>' +
                '<span class="st-po-send-confirm-phone">' +
                  (phone ? escapeHtml(phone) : 'No phone on file') +
                '</span>' +
              '</span>' +
            '</label>' +
          '</li>'
        );
      }).join('');
      syncSendBtn();
      modal.classList.add('open');
      modal.setAttribute('aria-hidden', 'false');
    }

    listEl && listEl.addEventListener('change', function (event) {
      if (event.target && event.target.classList.contains('st-po-send-confirm-check')) {
        syncSendBtn();
      }
    });

    if (skipBtn) skipBtn.addEventListener('click', finishAndNavigate);
    if (closeBtn) closeBtn.addEventListener('click', finishAndNavigate);
    modal.addEventListener('click', function (event) {
      if (event.target === modal) finishAndNavigate();
    });

    if (sendBtn) {
      sendBtn.addEventListener('click', function () {
        if (state.sending || !listEl) return;
        var checks = listEl.querySelectorAll('.st-po-send-confirm-check:checked:not(:disabled)');
        var jobs = [];
        Array.prototype.forEach.call(checks, function (box) {
          var idx = Number(box.getAttribute('data-idx'));
          var row = state.issued[idx];
          if (!row || !row.can_send) return;
          jobs.push(row);
        });
        if (!jobs.length) {
          toast('Select at least one supplier to send.', 'error');
          return;
        }
        state.sending = true;
        syncSendBtn();
        sendBtn.textContent = 'Sending…';

        var okCount = 0;
        var failCount = 0;
        var dryRun = false;

        function sendOne(row) {
          var sendUrl = '/stores/orders/' + encodeURIComponent(String(row.indent_id)) + '/send';
          return fetch(sendUrl, {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
              'Content-Type': 'application/json',
              Accept: 'application/json'
            },
            body: JSON.stringify({
              supplier_id: Number(row.supplier_id),
              po_no: String(row.po_no || ''),
              include_pdf: true
            })
          }).then(function (res) {
            return res.json().then(function (payload) {
              return { ok: res.ok && payload && payload.ok, payload: payload || {} };
            });
          }).then(function (res) {
            if (res.ok) {
              okCount += 1;
              if (res.payload.dry_run) dryRun = true;
            } else {
              failCount += 1;
            }
          }).catch(function () {
            failCount += 1;
          });
        }

        var chain = Promise.resolve();
        jobs.forEach(function (row) {
          chain = chain.then(function () { return sendOne(row); });
        });
        chain.then(function () {
          state.sending = false;
          sendBtn.textContent = 'Send selected';
          syncSendBtn();
          if (okCount) {
            var note = dryRun ? ' (dry run)' : '';
            toast(
              okCount + ' purchase order' + (okCount === 1 ? '' : 's') +
              ' sent via WhatsApp' + note + '.',
              'ok'
            );
          }
          if (failCount) {
            toast(
              failCount + ' purchase order' + (failCount === 1 ? '' : 's') +
              ' could not be sent.',
              'error'
            );
          }
          finishAndNavigate();
        });
      });
    }

    window.stPoOpenSendConfirm = openModal;
  }
  function initPoSend() {
    var shell = document.getElementById('st-po-send-shell');
    if (!shell || shell.getAttribute('data-st-po-bound') === '1') return;
    shell.setAttribute('data-st-po-bound', '1');

    var data = safeJson(document.getElementById('st-po-send-data')) || {};
    var groups = Array.isArray(data.groups) ? data.groups : [];
    var linesUrl = shell.getAttribute('data-lines-url') || '';
    var sendUrl = shell.getAttribute('data-send-url') || '';

    var supplierInput = document.getElementById('st-po-supplier');
    var messageEl = document.getElementById('st-po-message-preview');
    var attachmentEl = document.getElementById('st-po-attachment');
    var includePdf = document.getElementById('st-po-include-pdf');
    var previewBtn = document.getElementById('st-po-preview-pdf');
    var editBtn = document.getElementById('st-po-edit-items');
    var sendBtn = document.getElementById('st-po-send-wa');
    var editing = false;
    var savingEdits = false;
    var selectedSupplierId = '';

    function findGroup(supplierId) {
      var sid = String(supplierId || '');
      for (var i = 0; i < groups.length; i += 1) {
        var g = groups[i];
        if (String(g.supplier_id || '') === sid && !g.is_unassigned) return g;
      }
      return null;
    }

    var nextBtn = document.getElementById('st-po-next-btn');
    var selectAllBtn = document.getElementById('st-po-select-all');
    var selectNoneBtn = document.getElementById('st-po-select-none');
    var itemsForm = document.getElementById('st-po-items-form');
    var ordersUrl = shell.getAttribute('data-orders-url') || '/stores/orders?tab=send';
    var generating = false;
    var selectedCountEl = document.getElementById('st-po-selected-count');

    function formatPoQty(value) {
      var n = Number(value);
      if (!isFinite(n)) return '';
      if (Math.abs(n - Math.round(n)) < 0.0001) return String(Math.round(n));
      return String(Math.round(n * 1000) / 1000);
    }

    function collectLineEdits() {
      var out = [];
      Array.prototype.forEach.call(shell.querySelectorAll('[data-po-line]'), function (row) {
        var lineId = row.getAttribute('data-line-id');
        if (!lineId) return;
        var rateVal = String(row.getAttribute('data-rate') || '').trim();
        var supplierSelect = row.querySelector('.st-po-line-supplier');
        var supplierVal = supplierSelect ? String(supplierSelect.value || '').trim() : '';
        var qtyInput = row.querySelector('.st-po-line-qty');
        var qtyVal = qtyInput ? String(qtyInput.value || '').trim() : '';
        var maxQty = Number(row.getAttribute('data-indent-qty') || (qtyInput && qtyInput.getAttribute('max')) || 0);
        if (qtyInput && qtyVal !== '') {
          var n = Number(qtyVal);
          if (!isFinite(n) || n <= 0) {
            qtyVal = '';
          } else if (maxQty > 0 && n > maxQty) {
            qtyVal = formatPoQty(maxQty);
            qtyInput.value = qtyVal;
          } else {
            qtyVal = formatPoQty(n);
            qtyInput.value = qtyVal;
          }
        }
        out.push({
          line_id: Number(lineId),
          rate: rateVal === '' ? null : Number(rateVal),
          supplier_id: supplierVal === '' ? null : Number(supplierVal),
          quantity: qtyVal === '' ? null : Number(qtyVal)
        });
      });
      return out;
    }

    function groupCheckboxes() {
      return shell.querySelectorAll('.st-po-group-checkbox');
    }

    function selectedGroupCount() {
      var count = 0;
      Array.prototype.forEach.call(groupCheckboxes(), function (box) {
        if (box.checked) count += 1;
      });
      return count;
    }

    function anyGroupSelected() {
      return selectedGroupCount() > 0;
    }

    function anyLineAssigned() {
      var rows = shell.querySelectorAll('[data-po-line]');
      for (var i = 0; i < rows.length; i += 1) {
        var supplierSelect = rows[i].querySelector('.st-po-line-supplier');
        if (supplierSelect && String(supplierSelect.value || '').trim()) return true;
      }
      return false;
    }

    function hasUnassignedLines() {
      var rows = shell.querySelectorAll('[data-po-line]');
      for (var i = 0; i < rows.length; i += 1) {
        var supplierSelect = rows[i].querySelector('.st-po-line-supplier');
        if (!supplierSelect || !String(supplierSelect.value || '').trim()) return true;
      }
      return false;
    }

    function syncSelectedUi() {
      Array.prototype.forEach.call(shell.querySelectorAll('[data-po-group]'), function (card) {
        var box = card.querySelector('.st-po-group-checkbox');
        card.classList.toggle('is-selected', !!(box && box.checked));
      });
      if (selectedCountEl) {
        var n = selectedGroupCount();
        var total = groupCheckboxes().length;
        selectedCountEl.textContent = total
          ? (n + ' of ' + total + ' selected')
          : '';
      }
    }

    function syncNextBtn() {
      if (!nextBtn) return;
      var hasChecks = groupCheckboxes().length > 0;
      var ok = hasChecks ? anyGroupSelected() : anyLineAssigned();
      nextBtn.classList.toggle('is-disabled', !ok);
      nextBtn.disabled = !ok;
      syncSelectedUi();
    }

    function setGroupSelection(checked) {
      Array.prototype.forEach.call(groupCheckboxes(), function (box) {
        box.checked = !!checked;
      });
      syncNextBtn();
    }

    function setEditing(next) {
      editing = !!next;
      shell.classList.toggle('is-editing', editing);
      if (editBtn) {
        editBtn.setAttribute('aria-label', editing ? 'Close item editing' : 'Edit items');
        editBtn.setAttribute('data-tip', editing ? 'Close' : 'Edit');
      }
      syncNextBtn();
    }

    function saveEdits(opts) {
      opts = opts || {};
      if (!linesUrl || savingEdits) return Promise.resolve(false);
      savingEdits = true;
      shell.setAttribute('aria-busy', 'true');
      if (editBtn) editBtn.disabled = true;
      return fetch(linesUrl, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'application/json'
        },
        body: JSON.stringify({ lines: collectLineEdits() })
      }).then(function (res) {
        return res.json().then(function (payload) {
          return { ok: res.ok && payload && payload.ok, payload: payload || {}, status: res.status };
        });
      }).then(function (res) {
        if (!res.ok) {
          toast((res.payload && res.payload.error) || 'Could not save item edits.', 'error');
          return false;
        }
        toast(opts.auto ? 'Saved.' : 'Item edits saved.', 'ok');
        if (opts.redirectUrl) softNavigate(opts.redirectUrl);
        else if (!opts.stay) softReload();
        return true;
      }).catch(function () {
        toast('Could not save item edits.', 'error');
        return false;
      }).finally(function () {
        savingEdits = false;
        shell.removeAttribute('aria-busy');
        if (editBtn) editBtn.disabled = false;
      });
    }

    shell.addEventListener('click', function (event) {
      var toggle = event.target.closest('[data-po-toggle-group]');
      if (toggle) {
        event.preventDefault();
        var card = toggle.closest('[data-po-group]');
        if (!card) return;
        var open = !card.classList.contains('is-expanded');
        card.classList.toggle('is-expanded', open);
        var body = card.querySelector('.st-po-group-body');
        if (body) body.hidden = !open;
        toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
      }
    });

    shell.addEventListener('change', function (event) {
      var box = event.target.closest('.st-po-group-checkbox');
      if (box) {
        syncNextBtn();
        return;
      }
      var qty = event.target.closest('.st-po-line-qty');
      if (!qty) return;
      var row = qty.closest('[data-po-line]');
      var maxQty = Number((row && row.getAttribute('data-indent-qty')) || qty.getAttribute('max') || 0);
      var n = Number(qty.value);
      if (!isFinite(n) || n <= 0) {
        toast('Quantity must be greater than zero.', 'error');
        if (maxQty > 0) qty.value = formatPoQty(maxQty);
        return;
      }
      if (maxQty > 0 && n > maxQty) {
        qty.value = formatPoQty(maxQty);
        toast('Quantity cannot exceed indent qty (' + formatPoQty(maxQty) + ').', 'error');
      }
      else {
        qty.value = formatPoQty(n);
      }
      saveEdits({ auto: true });
    });

    if (selectAllBtn) {
      selectAllBtn.addEventListener('click', function () {
        setGroupSelection(true);
      });
    }
    if (selectNoneBtn) {
      selectNoneBtn.addEventListener('click', function () {
        setGroupSelection(false);
      });
    }

    // ep_form_listbox calls window.stPoSupplierPicked (module-level) for navigation.

    // Line-item supplier picks (items step) — persist immediately, then refresh.
    window.stPoLineSupplierPicked = function (root, value) {
      var hidden = root && root.querySelector('.st-po-line-supplier');
      if (hidden) hidden.value = value == null ? '' : String(value);
      var row = root && root.closest('[data-po-line]');
      if (row) row.setAttribute('data-supplier-id', value == null ? '' : String(value));
      syncNextBtn();
      saveEdits({ auto: true });
    };

    if (nextBtn) {
      nextBtn.addEventListener('click', function (event) {
        var hasChecks = groupCheckboxes().length > 0;
        if (hasChecks && !anyGroupSelected()) {
          event.preventDefault();
          syncNextBtn();
          toast('Select at least one supplier before generating.', 'error');
          return;
        }
        if (!anyLineAssigned()) {
          event.preventDefault();
          syncNextBtn();
          toast('Assign a supplier before generating.', 'error');
        }
      });
    }

    if (itemsForm && itemsForm.getAttribute('data-st-po-generate-bound') !== '1') {
      itemsForm.setAttribute('data-st-po-generate-bound', '1');
      itemsForm.addEventListener('submit', function (event) {
        event.preventDefault();
        event.stopPropagation();
        if (generating) return;
        var hasChecks = groupCheckboxes().length > 0;
        if (hasChecks && !anyGroupSelected()) {
          syncNextBtn();
          toast('Select at least one supplier before generating.', 'error');
          return;
        }
        if (!anyLineAssigned()) {
          syncNextBtn();
          toast('Assign a supplier before generating.', 'error');
          return;
        }
        generating = true;
        if (nextBtn) {
          nextBtn.disabled = true;
          nextBtn.classList.add('is-disabled');
        }
        var action = itemsForm.getAttribute('action') || '';
        var body = new FormData(itemsForm);

        function unlock() {
          generating = false;
          syncNextBtn();
        }

        Promise.resolve(saveEdits({ auto: true, stay: true })).then(function () {
          return fetch(action, {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
              Accept: 'application/json',
              'X-Requested-With': 'XMLHttpRequest'
            },
            body: body
          });
        }).then(function (res) {
          return res.json().then(function (payload) {
            return { ok: res.ok && payload && payload.ok, payload: payload || {}, status: res.status };
          });
        }).then(function (res) {
          unlock();
          if (!res.ok) {
            toast((res.payload && res.payload.error) || 'Could not generate purchase order.', 'error');
            return;
          }
          var issued = (res.payload && res.payload.issued) || [];
          var redirect = (res.payload && (res.payload.redirect || res.payload.continue_url)) || ordersUrl;
          if (typeof window.stPoOpenSendConfirm === 'function') {
            window.stPoOpenSendConfirm(issued, redirect);
          } else {
            toast(
              issued.length
                ? (issued.length + ' purchase order' + (issued.length === 1 ? '' : 's') + ' generated.')
                : 'Purchase orders generated.',
              'ok'
            );
            softNavigate(redirect);
          }
        }).catch(function () {
          unlock();
          toast('Could not generate purchase order.', 'error');
        });
      });
    }

    if (includePdf) {
      includePdf.addEventListener('change', function () {
        if (attachmentEl) attachmentEl.hidden = !(includePdf.checked && selectedSupplierId);
      });
    }

    if (previewBtn) {
      previewBtn.addEventListener('click', function () {
        if (!selectedSupplierId) return;
        openPoPdfModal(
          pdfUrlFor(shell, selectedSupplierId),
          shell.getAttribute('data-indent-no') || 'Purchase Order'
        );
      });
    }

    if (editBtn) {
      editBtn.addEventListener('click', function () {
        setEditing(!editing);
      });
    }

    if (sendBtn) {
      sendBtn.addEventListener('click', function () {
        if (!selectedSupplierId || !sendUrl) return;
        var group = findGroup(selectedSupplierId);
        if (!group) return;
        if (!group.can_send) {
          toast('Add a valid phone number for this supplier first.', 'error');
          return;
        }
        sendBtn.disabled = true;
        var messageNode = messageEl && (messageEl.querySelector('.st-po-message-text') || messageEl);
        var message = messageNode ? String(messageNode.textContent || '').trim() : '';
        fetch(sendUrl, {
          method: 'POST',
          credentials: 'same-origin',
          headers: {
            'Content-Type': 'application/json',
            Accept: 'application/json'
          },
          body: JSON.stringify({
            supplier_id: Number(selectedSupplierId),
            include_pdf: !!(includePdf && includePdf.checked),
            message: message
          })
        }).then(function (res) {
          return res.json().then(function (payload) {
            return { ok: res.ok && payload && payload.ok, payload: payload || {}, status: res.status };
          });
        }).then(function (res) {
          sendBtn.disabled = false;
          if (!res.ok) {
            toast((res.payload && res.payload.error) || 'Could not send purchase order.', 'error');
            return;
          }
          var note = res.payload.dry_run ? ' (dry run)' : '';
          toast('Purchase order sent via WhatsApp' + note + '.', 'ok');
        }).catch(function () {
          sendBtn.disabled = false;
          toast('Could not send purchase order.', 'error');
        });
      });
    }

    // Seed from the server-rendered hidden input (compose step).
    if (supplierInput && String(supplierInput.value || '').trim()) {
      selectedSupplierId = String(supplierInput.value || '').trim();
    }
    setEditing(hasUnassignedLines());
    syncNextBtn();
  }

  function boot() {
    initPoPdfModal();
    initPoSendConfirmModal();
    initPoResend();
    initPoSend();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }

  // Soft-nav re-entry
  document.addEventListener('de:softnav:ready', boot);
  window.initStoresPoPage = boot;
})();
