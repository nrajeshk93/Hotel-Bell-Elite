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
    el.style.display = text ? 'block' : 'none';
    el.textContent = text;
  }

  function syncFileName(page) {
    var fileInput = $('#ch-promo-file', page);
    var nameEl = $('#ch-promo-file-name', page);
    if (!nameEl) return;
    var file = fileInput && fileInput.files && fileInput.files[0];
    if (file) {
      nameEl.textContent = file.name;
      nameEl.classList.add('has-file');
    } else {
      nameEl.textContent = 'No file chosen';
      nameEl.classList.remove('has-file');
    }
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

  function templateListboxRoot(page) {
    return (
      (page && page.querySelector('#ch-promo-template-listbox')) ||
      document.getElementById('ch-promo-template-listbox')
    );
  }

  function templateOptionsWrap(page) {
    var root = templateListboxRoot(page);
    if (!root) return null;
    var list =
      (root.__epPortaledList && root.__epPortaledList.isConnected
        ? root.__epPortaledList
        : null) || root.querySelector('.se-filter-listbox');
    if (!list) return null;
    return list.querySelector('.ep-listbox-options') || list;
  }

  function setTemplateListboxValue(page, value, label) {
    if (typeof global.resetEpListbox === 'function') {
      global.resetEpListbox('ch-promo-template', value || '', label || 'Select a template…');
      return;
    }
    var hidden = $('#ch-promo-template', page);
    if (hidden) hidden.value = value || '';
    var root = templateListboxRoot(page);
    if (!root) return;
    var trigger = root.querySelector('.se-filter-chip-trigger');
    if (trigger) {
      if (trigger.tagName === 'INPUT') {
        trigger.value = value ? label : '';
        trigger.classList.toggle('is-placeholder', !value);
        trigger.placeholder = label || 'Select a template…';
      } else {
        var display = trigger.querySelector('.se-filter-chip-value');
        if (display) {
          display.textContent = label || 'Select a template…';
          display.classList.toggle('is-placeholder', !value);
        }
      }
    }
  }

  function fillTemplateSelect(page, templates, errorMsg) {
    var optionsWrap = templateOptionsWrap(page);
    if (!optionsWrap) return;
    loadedTemplates = (templates || []).filter(function (t) {
      return !!(t && t.sendable);
    });
    optionsWrap.textContent = '';

    var placeholderLabel = errorMsg
      ? errorMsg
      : loadedTemplates.length
        ? 'Select a template…'
        : 'No supported templates found';

    if (!errorMsg) {
      loadedTemplates.forEach(function (t) {
        var value = t.name + '::' + t.language;
        var label = t.name + ' (' + t.language + ')';
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'se-filter-listbox-option';
        btn.setAttribute('role', 'option');
        btn.setAttribute('data-value', value);
        btn.setAttribute('data-name', label.toLowerCase());
        btn.setAttribute('data-label', label);
        btn.setAttribute('aria-selected', 'false');
        btn.textContent = label;
        optionsWrap.appendChild(btn);
      });
    }

    setTemplateListboxValue(page, '', placeholderLabel);
    updateTemplateMeta(page);
  }

  async function loadTemplates(page, force) {
    var url = page.getAttribute('data-templates-url') || '';
    if (!url) return;
    if (force) url += (url.indexOf('?') >= 0 ? '&' : '?') + 'refresh=1';
    setTemplateListboxValue(page, '', 'Loading templates…');
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
    syncFileName(page);
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
    if (typeof global.initEpListboxes === 'function') {
      try {
        global.initEpListboxes();
      } catch (err) {}
    }
    loadTemplates(page, false);

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

  global.chPromoTemplateChanged = function () {
    var page = document.getElementById('ch-promotion-page');
    if (page) updateTemplateMeta(page);
  };

  global.initPromotionPage = initPromotionPage;
  global.initCommunicationHubPromotionPage = initPromotionPage;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initPromotionPage);
  } else {
    initPromotionPage();
  }
})(window);
