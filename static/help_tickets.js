(function () {
  var page = document.getElementById('help-tickets-page');
  if (!page) return;
  var listUrl = page.getAttribute('data-list-url');
  var createUrl = page.getAttribute('data-create-url');
  var tbody = document.getElementById('ht-tbody');
  var modal = document.getElementById('ht-create-modal');
  var form = document.getElementById('ht-create-form');
  var errEl = document.getElementById('ht-form-error');
  var state = { type: 'all', status: '', q: '' };

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function typeIcon(t) {
    if (t === 'improvement') {
      return '<span class="ht-type-badge ht-type-badge--improvement" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M9 18h6"/><path d="M10 22h4"/><path d="M12 2a7 7 0 0 0-4 12.7V17h8v-2.3A7 7 0 0 0 12 2z"/></svg></span>';
    }
    return '<span class="ht-type-badge ht-type-badge--issue" aria-hidden="true"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8"/><path d="M12 8v5"/><path d="M12 16h.01"/></svg></span>';
  }

  function renderRows(tickets) {
    if (!tickets.length) {
      tbody.innerHTML = '<tr class="ht-empty"><td colspan="8">No tickets found.</td></tr>';
      return;
    }
    tbody.innerHTML = tickets.map(function (t, i) {
      return (
        '<tr>' +
        '<td>' + (i + 1) + '</td>' +
        '<td><span class="ht-type">' + typeIcon(t.ticket_type) + esc(t.type_label) + '</span></td>' +
        '<td>' + esc(t.subject) + '</td>' +
        '<td>' + esc(t.module || '—') + '</td>' +
        '<td><span class="ht-priority"><span class="ht-dot ht-dot--' + esc(t.priority) + '"></span>' + esc(t.priority_label) + '</span></td>' +
        '<td><span class="ht-status ht-status--' + esc(t.status) + '">' + esc(t.status_label) + '</span></td>' +
        '<td>' + esc(t.created_on) + '</td>' +
        '<td>' + esc(t.updated_on) + '</td>' +
                '</tr>'
      );
    }).join('');
  }

  function loadTickets() {
    var url = listUrl + '?type=' + encodeURIComponent(state.type) +
      '&status=' + encodeURIComponent(state.status) +
      '&q=' + encodeURIComponent(state.q);
    tbody.innerHTML = '<tr class="ht-loading-row"><td colspan="8">Loading tickets…</td></tr>';
    fetch(url, { credentials: 'same-origin', headers: { Accept: 'application/json' } })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (!data || !data.ok) throw new Error((data && data.error) || 'Failed to load');
        renderRows(data.tickets || []);
      })
      .catch(function (e) {
        tbody.innerHTML = '<tr class="ht-empty"><td colspan="8">' + esc(e.message || 'Failed to load') + '</td></tr>';
      });
  }

  function openModal() {
    modal.hidden = false;
    modal.setAttribute('aria-hidden', 'false');
    errEl.hidden = true;
    errEl.textContent = '';
    form.reset();
    document.getElementById('ht-email').value = page.getAttribute('data-contact-email') || '';
    var pri = document.getElementById('ht-priority');
    if (pri) pri.value = 'medium';
    var priVal = document.getElementById('ht-priority-value');
    if (priVal) priVal.textContent = 'Medium';
    var priBox = document.getElementById('ht-priority-listbox');
    if (priBox) {
      priBox.querySelectorAll('.se-filter-listbox-option').forEach(function (opt) {
        var on = opt.getAttribute('data-value') === 'medium';
        opt.classList.toggle('is-selected', on);
        opt.setAttribute('aria-selected', on ? 'true' : 'false');
      });
    }
    var mod = document.getElementById('ht-module');
    if (mod) mod.value = '';
    var modVal = document.getElementById('ht-module-value');
    if (modVal) {
      modVal.textContent = 'Select module';
      modVal.classList.add('is-placeholder');
    }
    var modBox = document.getElementById('ht-module-listbox');
    if (modBox) {
      modBox.querySelectorAll('.se-filter-listbox-option').forEach(function (opt) {
        var on = (opt.getAttribute('data-value') || '') === '';
        opt.classList.toggle('is-selected', on);
        opt.setAttribute('aria-selected', on ? 'true' : 'false');
      });
    }
    document.querySelectorAll('.ht-type-card').forEach(function (card) {
      card.classList.toggle('is-selected', card.querySelector('input').checked);
    });
    document.getElementById('ht-char-count').textContent = '0/1000';
    setTimeout(function () { document.getElementById('ht-subject').focus(); }, 50);
  }

  function closeModal() {
    modal.hidden = true;
    modal.setAttribute('aria-hidden', 'true');
  }

  document.getElementById('ht-open-create').addEventListener('click', openModal);
  modal.querySelectorAll('[data-ht-close]').forEach(function (el) {
    el.addEventListener('click', closeModal);
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && !modal.hidden) closeModal();
  });

  document.querySelectorAll('.ht-tab').forEach(function (tab) {
    tab.addEventListener('click', function () {
      document.querySelectorAll('.ht-tab').forEach(function (t) {
        t.classList.toggle('is-active', t === tab);
        t.setAttribute('aria-selected', t === tab ? 'true' : 'false');
      });
      state.type = tab.getAttribute('data-type') || 'all';
      loadTickets();
    });
  });

  var searchTimer = null;
  document.getElementById('ht-search').addEventListener('input', function (e) {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(function () {
      state.q = e.target.value || '';
      loadTickets();
    }, 200);
  });
  window.htStatusChanged = function (root, value, label) {
    state.status = value || '';
    loadTickets();
  };
  var statusHidden = document.getElementById('ht-status');
  if (statusHidden) {
    statusHidden.addEventListener('change', function (e) {
      state.status = e.target.value || '';
      loadTickets();
    });
  }


  document.querySelectorAll('.ht-type-card').forEach(function (card) {
    card.addEventListener('click', function () {
      document.querySelectorAll('.ht-type-card').forEach(function (c) { c.classList.remove('is-selected'); });
      card.classList.add('is-selected');
      card.querySelector('input').checked = true;
    });
  });

  var desc = document.getElementById('ht-description');
  var counter = document.getElementById('ht-char-count');
  desc.addEventListener('input', function () {
    counter.textContent = String(desc.value.length) + '/1000';
  });

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    errEl.hidden = true;
    var fd = new FormData(form);
    var files = document.getElementById('ht-files').files;
    for (var i = 0; i < files.length; i++) fd.append('files', files[i]);
    var btn = document.getElementById('ht-submit');
    btn.disabled = true;
    fetch(createUrl, { method: 'POST', body: fd, credentials: 'same-origin' })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
      .then(function (res) {
        if (!res.ok || !res.j.ok) throw new Error((res.j && res.j.error) || 'Could not create ticket');
        closeModal();
        loadTickets();
      })
      .catch(function (err) {
        errEl.textContent = err.message || 'Could not create ticket';
        errEl.hidden = false;
      })
      .finally(function () { btn.disabled = false; });
  });

  loadTickets();
})();
