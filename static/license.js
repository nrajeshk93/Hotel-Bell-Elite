(function () {
  function csrfToken() {
    try {
      if (window.HbeCsrf && typeof window.HbeCsrf.token === 'function') {
        return window.HbeCsrf.token() || '';
      }
    } catch (e) {}
    var meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? (meta.getAttribute('content') || '') : '';
  }

  function qs(root, sel) {
    return (root || document).querySelector(sel);
  }

  function qsAll(root, sel) {
    return Array.prototype.slice.call((root || document).querySelectorAll(sel));
  }

  function setText(el, text) {
    if (el) el.textContent = text == null ? '' : String(text);
  }

  function applyLicense(root, license) {
    if (!root || !license) return;
    var status = license.status || 'expired';
    var badge = qs(root, '[data-lic-status-badge]');
    if (badge) {
      badge.className = 'lic-status-badge lic-status-badge--' + status;
    }
    setText(qs(root, '[data-lic-status-label]'), license.status_label);
    setText(qs(root, '[data-lic-status-message]'), license.status_message);
    setText(qs(root, '[data-lic-expires-on]'), license.valid_to_display);
    setText(qs(root, '[data-lic-remaining-label]'), license.remaining_label);
    setText(qs(root, '[data-lic-type]'), license.license_type);
    setText(qs(root, '[data-lic-key]'), license.license_key);
    setText(qs(root, '[data-lic-from]'), license.valid_from_display);
    setText(qs(root, '[data-lic-to]'), license.valid_to_display);
    var detailStatus = qs(root, '[data-lic-detail-status]');
    if (detailStatus) {
      detailStatus.className = 'lic-inline-badge lic-status-badge--' + status;
      detailStatus.textContent = license.status_label || '';
    }
    setText(qs(root, '[data-lic-created]'), license.created_at_display);
    setText(qs(root, '[data-lic-updated]'), license.updated_at_display);

    var form = qs(root, '[data-lic-update-form]');
    if (form) {
      if (form.valid_from) form.valid_from.value = license.valid_from || '';
      if (form.valid_to) form.valid_to.value = license.valid_to || '';
      if (form.license_type) form.license_type.value = license.license_type || '';
      if (form.license_key) form.license_key.value = license.license_key || '';
    }
  }

  function renderHistory(root, renewals) {
    var list = qs(root, '[data-lic-history-list]');
    if (!list) return;
    list.innerHTML = '';
    if (!renewals || !renewals.length) {
      list.innerHTML = '<p class="lic-history-empty">No renewal history yet.</p>';
      return;
    }
    renewals.forEach(function (row) {
      var item = document.createElement('article');
      item.className = 'lic-history-item';
      var dates = document.createElement('div');
      dates.className = 'lic-history-dates';
      dates.textContent = (row.valid_from_display || '') + ' → ' + (row.valid_to_display || '');
      item.appendChild(dates);
      var meta = document.createElement('div');
      meta.className = 'lic-history-meta';
      if (row.updated_by) {
        var by = document.createElement('span');
        by.textContent = row.updated_by;
        meta.appendChild(by);
      }
      var when = document.createElement('span');
      when.textContent = row.created_at_display || '';
      meta.appendChild(when);
      item.appendChild(meta);
      if (row.note) {
        var note = document.createElement('p');
        note.className = 'lic-history-note';
        note.textContent = row.note;
        item.appendChild(note);
      }
      list.appendChild(item);
    });
  }

  function openModal(modal) {
    if (!modal) return;
    modal.hidden = false;
  }

  function closeModal(modal) {
    if (!modal) return;
    modal.hidden = true;
  }

  function initLicensePage(root) {
    if (!root || root.getAttribute('data-lic-bound') === '1') return;
    root.setAttribute('data-lic-bound', '1');
    var api = root.getAttribute('data-license-api') || '/license/api';
    var modal = qs(root, '#lic-history-modal') || document.getElementById('lic-history-modal');

    qsAll(root, '[data-lic-history-open]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        openModal(modal);
      });
    });
    qsAll(document, '[data-lic-history-close]').forEach(function (el) {
      el.addEventListener('click', function () {
        closeModal(modal);
      });
    });

    var form = qs(root, '[data-lic-update-form]');
    if (!form) return;

    form.addEventListener('submit', function (ev) {
      ev.preventDefault();
      var statusEl = qs(root, '[data-lic-update-status]');
      var saveBtn = qs(root, '[data-lic-save]');
      var body = {
        valid_from: (form.valid_from && form.valid_from.value) || '',
        valid_to: (form.valid_to && form.valid_to.value) || '',
        license_type: (form.license_type && form.license_type.value) || '',
        license_key: (form.license_key && form.license_key.value) || '',
        note: (form.note && form.note.value) || ''
      };
      if (saveBtn) saveBtn.disabled = true;
      if (statusEl) {
        statusEl.hidden = false;
        statusEl.classList.remove('is-error');
        statusEl.textContent = 'Saving…';
      }
      var headers = {
        'Content-Type': 'application/json',
        Accept: 'application/json',
        'X-Requested-With': 'XMLHttpRequest'
      };
      var token = csrfToken();
      if (token) headers['X-CSRFToken'] = token;

      fetch(api, {
        method: 'PUT',
        credentials: 'same-origin',
        headers: headers,
        body: JSON.stringify(body)
      })
        .then(function (resp) {
          return resp.json().then(function (data) {
            return { ok: resp.ok, status: resp.status, data: data || {} };
          });
        })
        .then(function (result) {
          if (!result.ok || !result.data.ok) {
            throw new Error((result.data && result.data.error) || 'Could not update license.');
          }
          applyLicense(root, result.data.license);
          renderHistory(root, result.data.renewals || []);
          if (form.note) form.note.value = '';
          if (statusEl) {
            statusEl.classList.remove('is-error');
            statusEl.textContent = 'License updated.';
          }
        })
        .catch(function (err) {
          if (statusEl) {
            statusEl.classList.add('is-error');
            statusEl.textContent = (err && err.message) || 'Could not update license.';
          }
        })
        .finally(function () {
          if (saveBtn) saveBtn.disabled = false;
        });
    });
  }

  function boot() {
    var root = document.getElementById('license-page') || document.querySelector('[data-license]');
    if (root) initLicensePage(root);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }

  document.addEventListener('de:soft-nav-ready', boot);
})();
