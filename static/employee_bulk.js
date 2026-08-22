(function (global) {
  'use strict';

  var empBulkAbort = null;

  function $(sel, root) {
    return (root || document).querySelector(sel);
  }

  function escapeHtml(s) {
    return String(s || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function setBulkStatus(el, html, isError) {
    if (!el) return;
    el.innerHTML = html || '';
    el.classList.toggle('is-error', !!isError && !!html);
  }

  function setBulkError(el, msg) {
    if (!el) return;
    var text = String(msg || '').trim();
    el.hidden = !text;
    el.textContent = text;
  }

  function setEmpAddMode(mode) {
    var bulk = String(mode || '') === 'bulk';
    var host = $('#ep-emp-mode-host');
    if (!host) return;

    var panel = host.closest('.ep-emp-form-panel') || document.querySelector('.ep-emp-form-panel');
    var embed = document.querySelector('.md-master-embed--employee-form');
    if (panel) panel.classList.toggle('is-emp-bulk', bulk);
    if (embed) embed.classList.toggle('is-emp-bulk', bulk);
    document.documentElement.classList.toggle('is-emp-bulk', bulk);
    document.body.classList.toggle('is-emp-bulk', bulk);

    var form = $('#employee-form');
    var bulkEl = $('#ep-emp-bulk');
    var title =
      (embed && embed.querySelector('.su-title-row h1')) ||
      document.querySelector('.su-title-row h1');
    var submitBtns = document.querySelectorAll(
      'button[form="employee-form"], #employee-form button[type="submit"]'
    );

    if (form) form.hidden = bulk;
    if (bulkEl) bulkEl.hidden = !bulk;
    submitBtns.forEach(function (btn) {
      btn.hidden = bulk;
      if (bulk) btn.setAttribute('aria-hidden', 'true');
      else btn.removeAttribute('aria-hidden');
    });

    host.querySelectorAll('[data-ep-emp-mode]').forEach(function (btn) {
      var on = btn.getAttribute('data-ep-emp-mode') === (bulk ? 'bulk' : 'single');
      btn.classList.toggle('is-active', on);
      btn.setAttribute('aria-selected', on ? 'true' : 'false');
    });

    if (title) {
      var isEdit = !!(form && String(form.getAttribute('action') || '').indexOf('edit_employee') !== -1);
      if (!isEdit) title.textContent = bulk ? 'Bulk employee upload' : 'Add Employee';
    }
  }

  function downloadTemplate(host) {
    var url = (host.getAttribute('data-template-url') || '') +
      (String(host.getAttribute('data-template-url') || '').indexOf('?') >= 0 ? '&' : '?') +
      '_=' + Date.now();
    var status = $('#ep-emp-bulk-status');
    var err = $('#ep-emp-bulk-error');
    setBulkError(err, '');
    setBulkStatus(status, 'Downloading…');
    fetch(url, {
      credentials: 'same-origin',
      cache: 'no-store',
      headers: {
        Accept: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
      }
    })
      .then(function (r) {
        if (!r.ok) throw new Error('Could not download template.');
        var disp = r.headers.get('Content-Disposition') || '';
        var match = /filename\*?=(?:UTF-8'')?["']?([^";]+)/i.exec(disp);
        var fallback = 'Employee_Import_Template.xlsx';
        var name = match ? decodeURIComponent(match[1].replace(/"/g, '').trim()) : fallback;
        return r.blob().then(function (blob) {
          return { blob: blob, name: name || fallback };
        });
      })
      .then(function (res) {
        var href = URL.createObjectURL(res.blob);
        var a = document.createElement('a');
        a.href = href;
        a.download = res.name;
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(function () {
          URL.revokeObjectURL(href);
        }, 800);
        setBulkStatus(status, '');
      })
      .catch(function () {
        setBulkStatus(status, 'Could not download template.', true);
      });
  }

  function uploadFile(host, file) {
    var status = $('#ep-emp-bulk-status');
    var err = $('#ep-emp-bulk-error');
    var uploadUrl = host.getAttribute('data-upload-url') || '';
    if (!file) {
      setBulkStatus(status, 'Choose an Excel file first.', true);
      return;
    }
    var fd = new FormData();
    fd.append('file', file);
    setBulkError(err, '');
    setBulkStatus(status, 'Uploading…');
    fetch(uploadUrl, {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        Accept: 'application/json',
        'X-Requested-With': 'XMLHttpRequest'
      },
      body: fd
    })
      .then(function (r) {
        return r.json().then(function (data) {
          return { ok: r.ok, data: data };
        });
      })
      .then(function (res) {
        var data = res.data || {};
        if (!res.ok || !data.ok) {
          var msg = data.error || 'Could not import employees.';
          setBulkError(err, msg);
          setBulkStatus(status, escapeHtml(msg), true);
          return;
        }
        var created = Number(data.created_count || 0);
        var skipped = Number(data.skipped_count || 0);
        var failed = Number(data.error_count || 0);
        var parts = [];
        if (created) parts.push(created + (created === 1 ? ' employee added' : ' employees added'));
        if (skipped) parts.push(skipped + ' skipped');
        if (failed && !skipped) parts.push(failed + ' with errors');
        var html = parts.length ? parts.join(' · ') : 'No rows imported.';
        var errs = data.errors || [];
        if (errs.length) {
          html += '<ul>';
          errs.slice(0, 8).forEach(function (row) {
            html +=
              '<li>Row ' +
              escapeHtml(row.row) +
              (row.name ? ' (' + escapeHtml(row.name) + ')' : '') +
              ': ' +
              escapeHtml((row.errors || []).join('; ')) +
              '</li>';
          });
          html += '</ul>';
        }
        setBulkStatus(status, html, failed > 0 && created === 0);
        var fileInput = $('#ep-emp-bulk-file');
        if (fileInput) fileInput.value = '';
      })
      .catch(function () {
        setBulkStatus(status, 'Network error while importing.', true);
      });
  }

  function initEmployeeBulkPage() {
    if (empBulkAbort) empBulkAbort.abort();
    empBulkAbort = new AbortController();
    var signal = empBulkAbort.signal;
    var host = document.getElementById('ep-emp-mode-host');
    if (!host) return;

    setEmpAddMode('single');

    host.addEventListener(
      'click',
      function (e) {
        var tab = e.target.closest('[data-ep-emp-mode]');
        if (!tab || !host.contains(tab)) return;
        setEmpAddMode(tab.getAttribute('data-ep-emp-mode'));
      },
      { signal: signal }
    );

    var tplBtn = document.getElementById('ep-emp-bulk-template');
    if (tplBtn) {
      tplBtn.addEventListener(
        'click',
        function () {
          downloadTemplate(host);
        },
        { signal: signal }
      );
    }

    var fileInput = document.getElementById('ep-emp-bulk-file');
    if (fileInput) {
      fileInput.addEventListener(
        'change',
        function () {
          var file = fileInput.files && fileInput.files[0];
          if (file) uploadFile(host, file);
        },
        { signal: signal }
      );
    }
  }

  global.initEmployeeBulkPage = initEmployeeBulkPage;
  global.setEmpAddMode = setEmpAddMode;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initEmployeeBulkPage);
  } else {
    initEmployeeBulkPage();
  }
})(window);
