(function (global) {
  'use strict';

  var promoInitAbort = null;
  var loadedTemplates = [];
  var previewRows = [];

  function $(sel, root) {
    return (root || document).querySelector(sel);
  }

  function showError(el, msg) {
    if (!el) return;
    var text = String(msg || '').trim();
    el.hidden = !text;
    el.textContent = text;
  }

  function selectedTemplate() {
    var sel = $('#ch-promo-template');
    if (!sel || !sel.value) return null;
    var parts = String(sel.value).split('::');
    var name = parts[0] || '';
    var language = parts.slice(1).join('::') || '';
    for (var i = 0; i < loadedTemplates.length; i++) {
      var t = loadedTemplates[i];
      if (t.name === name && t.language === language) return t;
    }
    return null;
  }

  function updateTemplateMeta(page) {
    var meta = $('#ch-promo-template-meta', page);
    var sendBtn = $('#ch-promo-send', page);
    var t = selectedTemplate();
    if (!meta) return;
    if (!t) {
      meta.hidden = true;
      meta.textContent = '';
      meta.classList.remove('is-warn');
      if (sendBtn) sendBtn.disabled = true;
      return;
    }
    var bits = [];
    bits.push('Language: ' + t.language);
    if (t.category) bits.push(t.category);
    bits.push(
      t.body_param_count
        ? 'Uses customer name as {{1}}'
        : 'No body variables'
    );
    if (!t.sendable && t.block_reason) {
      bits.push(t.block_reason);
      meta.classList.add('is-warn');
    } else {
      meta.classList.remove('is-warn');
    }
    meta.textContent = bits.join(' · ');
    meta.hidden = false;
    syncSendEnabled(page);
  }

  function syncSendEnabled(page) {
    var sendBtn = $('#ch-promo-send', page);
    if (!sendBtn) return;
    var t = selectedTemplate();
    var ready =
      !!t &&
      !!t.sendable &&
      previewRows.length > 0 &&
      sendBtn.getAttribute('data-sending') !== '1';
    sendBtn.disabled = !ready;
  }

  function fillTemplateSelect(page, templates, errorMsg) {
    var sel = $('#ch-promo-template', page);
    if (!sel) return;
    loadedTemplates = templates || [];
    sel.textContent = '';
    if (errorMsg) {
      var errOpt = document.createElement('option');
      errOpt.value = '';
      errOpt.textContent = errorMsg;
      sel.appendChild(errOpt);
      updateTemplateMeta(page);
      return;
    }
    var placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = loadedTemplates.length
      ? 'Select a template…'
      : 'No approved templates found';
    sel.appendChild(placeholder);
    loadedTemplates.forEach(function (t) {
      var opt = document.createElement('option');
      opt.value = t.name + '::' + t.language;
      var label = t.name + ' (' + t.language + ')';
      if (!t.sendable) label += ' — not supported';
      opt.textContent = label;
      sel.appendChild(opt);
    });
    updateTemplateMeta(page);
  }

  async function loadTemplates(page, force) {
    var url = page.getAttribute('data-templates-url') || '';
    if (!url) return;
    if (force) url += (url.indexOf('?') >= 0 ? '&' : '?') + 'refresh=1';
    var sel = $('#ch-promo-template', page);
    if (sel) {
      sel.textContent = '';
      var loading = document.createElement('option');
      loading.value = '';
      loading.textContent = 'Loading templates…';
      sel.appendChild(loading);
    }
    try {
      var res = await fetch(url, { credentials: 'same-origin' });
      var data = await res.json();
      if (!res.ok || !data.ok) {
        fillTemplateSelect(
          page,
          [],
          (data && data.error) || 'Could not load templates'
        );
        return;
      }
      fillTemplateSelect(page, data.templates || [], '');
    } catch (err) {
      fillTemplateSelect(page, [], 'Network error loading templates');
    }
  }

  function renderPreview(page, payload) {
    var box = $('#ch-promo-preview', page);
    var stats = $('#ch-promo-preview-stats', page);
    var wrap = $('#ch-promo-preview-table-wrap', page);
    var body = $('#ch-promo-preview-body', page);
    previewRows = (payload && payload.rows) || [];
    if (!box || !stats) return;
    box.hidden = false;
    var valid = Number((payload && payload.valid_count) || previewRows.length || 0);
    var skipped = Number((payload && payload.skipped_count) || 0);
    stats.textContent =
      valid +
      ' valid recipient' +
      (valid === 1 ? '' : 's') +
      (skipped ? ' · ' + skipped + ' skipped' : '');
    if (body) {
      body.textContent = '';
      previewRows.slice(0, 25).forEach(function (row) {
        var tr = document.createElement('tr');
        tr.innerHTML =
          '<td>' +
          (row.row_number || '') +
          '</td><td>' +
          escapeHtml(row.name || '') +
          '</td><td>' +
          escapeHtml(row.phone_display || row.phone || '') +
          '</td>';
        body.appendChild(tr);
      });
    }
    if (wrap) wrap.hidden = previewRows.length === 0;
    syncSendEnabled(page);
  }

  function escapeHtml(s) {
    return String(s || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  async function previewFile(page) {
    var errEl = $('#ch-promo-error', page);
    var fileInput = $('#ch-promo-file', page);
    var url = page.getAttribute('data-preview-url') || '';
    showError(errEl, '');
    previewRows = [];
    syncSendEnabled(page);
    if (!fileInput || !fileInput.files || !fileInput.files[0]) {
      var box = $('#ch-promo-preview', page);
      if (box) box.hidden = true;
      return;
    }
    var fd = new FormData();
    fd.append('file', fileInput.files[0]);
    try {
      var res = await fetch(url, { method: 'POST', body: fd, credentials: 'same-origin' });
      var data = await res.json();
      if (!res.ok || !data.ok) {
        showError(errEl, (data && data.error) || 'Could not preview Excel.');
        var preview = $('#ch-promo-preview', page);
        if (preview) preview.hidden = true;
        return;
      }
      renderPreview(page, data);
    } catch (err) {
      showError(errEl, 'Network error while reading Excel.');
    }
  }

  function renderResults(page, data) {
    var box = $('#ch-promo-results', page);
    var stats = $('#ch-promo-results-stats', page);
    var body = $('#ch-promo-results-body', page);
    if (!box || !stats || !body) return;
    box.hidden = false;
    stats.textContent =
      'Campaign #' +
      (data.campaign_id || '') +
      ' · Sent ' +
      (data.sent || 0) +
      ' · Failed ' +
      (data.failed || 0) +
      ' · Total ' +
      (data.total || 0);
    body.textContent = '';
    (data.outcomes || []).forEach(function (row) {
      var tr = document.createElement('tr');
      var status = String(row.status || '');
      tr.innerHTML =
        '<td>' +
        (row.row_number || '') +
        '</td><td>' +
        escapeHtml(row.name || '') +
        '</td><td>' +
        escapeHtml(row.phone || '') +
        '</td><td class="ch-promo-status-' +
        escapeHtml(status) +
        '">' +
        escapeHtml(status) +
        '</td><td>' +
        escapeHtml(row.error || row.wa_message_id || '') +
        '</td>';
      body.appendChild(tr);
    });
  }

  async function sendCampaign(page) {
    var errEl = $('#ch-promo-error', page);
    var sendBtn = $('#ch-promo-send', page);
    var t = selectedTemplate();
    showError(errEl, '');
    if (!t || !t.sendable) {
      showError(errEl, (t && t.block_reason) || 'Select a supported template.');
      return;
    }
    if (!previewRows.length) {
      showError(errEl, 'Upload and preview an Excel file first.');
      return;
    }
    var url = page.getAttribute('data-send-url') || '';
    if (!url) return;
    if (sendBtn) {
      sendBtn.setAttribute('data-sending', '1');
      sendBtn.disabled = true;
      var label = sendBtn.querySelector('span');
      if (label) label.textContent = 'Sending…';
    }
    try {
      var res = await fetch(url, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          template_name: t.name,
          template_language: t.language,
          rows: previewRows
        })
      });
      var data = await res.json();
      if (!res.ok || !data.ok) {
        showError(errEl, (data && data.error) || 'Could not send campaign.');
        return;
      }
      renderResults(page, data);
    } catch (err) {
      showError(errEl, 'Network error while sending campaign.');
    } finally {
      if (sendBtn) {
        sendBtn.removeAttribute('data-sending');
        var span = sendBtn.querySelector('span');
        if (span) span.textContent = 'Send';
        syncSendEnabled(page);
      }
    }
  }

  function initPromotionPage() {
    if (promoInitAbort) promoInitAbort.abort();
    promoInitAbort = new AbortController();
    var signal = promoInitAbort.signal;
    var page = document.getElementById('ch-promotion-page');
    if (!page) return;

    previewRows = [];
    loadTemplates(page, false);

    var sel = $('#ch-promo-template', page);
    if (sel) {
      sel.addEventListener('change', function () {
        updateTemplateMeta(page);
      }, { signal: signal });
    }
    var fileInput = $('#ch-promo-file', page);
    if (fileInput) {
      fileInput.addEventListener('change', function () {
        previewFile(page);
      }, { signal: signal });
    }
    var refreshBtn = $('#ch-promo-refresh-templates', page);
    if (refreshBtn) {
      refreshBtn.addEventListener('click', function () {
        loadTemplates(page, true);
      }, { signal: signal });
    }
    var sendBtn = $('#ch-promo-send', page);
    if (sendBtn) {
      sendBtn.addEventListener('click', function () {
        sendCampaign(page);
      }, { signal: signal });
    }
  }

  global.initPromotionPage = initPromotionPage;
  global.initCommunicationHubPromotionPage = initPromotionPage;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initPromotionPage);
  } else {
    initPromotionPage();
  }
})(window);
