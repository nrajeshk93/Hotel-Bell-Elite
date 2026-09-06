(function (global) {
  'use strict';

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

  function stars(n) {
    var v = Math.max(0, Math.min(5, parseInt(n, 10) || 0));
    return '?????'.slice(0, v) + '?????'.slice(0, 5 - v);
  }

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function pageRoot() {
    return document.getElementById('ch-feedback-page');
  }

  function renderSummary(page, summary) {
    summary = summary || {};
    var responses = summary.responses != null ? summary.responses : 0;
    var avg = summary.avg_rating;
    var rate = summary.response_rate_pct;
    var month = summary.responses_this_month != null ? summary.responses_this_month : 0;
    var elResp = page.querySelector('[data-kpi="responses"]');
    var elAvg = page.querySelector('[data-kpi="avg"]');
    var elRate = page.querySelector('[data-kpi="rate"]');
    var elMonth = page.querySelector('[data-kpi="month"]');
    if (elResp) elResp.textContent = String(responses);
    if (elAvg) elAvg.textContent = avg != null ? String(avg) : '-';
    if (elRate) elRate.textContent = rate != null ? rate + '%' : '-';
    if (elMonth) elMonth.textContent = String(month);

    var dist = summary.rating_distribution || {};
    var max = 1;
    var i;
    for (i = 1; i <= 5; i++) {
      max = Math.max(max, parseInt(dist[String(i)], 10) || 0);
    }
    var host = $('#ch-fb-dist', page);
    if (!host) return;
    var html = '';
    for (i = 5; i >= 1; i--) {
      var count = parseInt(dist[String(i)], 10) || 0;
      var pct = Math.round((100 * count) / max);
      html +=
        '<div class="ch-fb-dist-row">' +
        '<span>' +
        i +
        ' ?</span>' +
        '<div class="ch-fb-dist-track"><div class="ch-fb-dist-fill" style="width:' +
        pct +
        '%"></div></div>' +
        '<span>' +
        count +
        '</span>' +
        '</div>';
    }
    host.innerHTML = html;
  }

  function renderRows(page, rows) {
    var tbody = $('#ch-fb-rows', page);
    if (!tbody) return;
    if (!rows || !rows.length) {
      tbody.innerHTML =
        '<tr class="ch-fb-empty"><td colspan="5">No feedback yet. Create a link and send it to a guest.</td></tr>';
      return;
    }
    tbody.innerHTML = rows
      .map(function (row) {
        return (
          '<tr>' +
          '<td>' +
          esc(row.submitted_at || '') +
          '</td>' +
          '<td>' +
          esc(row.customer_name || 'Guest') +
          (row.phone ? '<div class="ch-fb-muted">' + esc(row.phone) + '</div>' : '') +
          '</td>' +
          '<td class="ch-fb-stars" title="' +
          esc(row.rating) +
          '/5">' +
          stars(row.rating) +
          '</td>' +
          '<td>' +
          esc(row.source || '') +
          (row.outlet ? ' · ' + esc(row.outlet) : '') +
          '</td>' +
          '<td class="ch-fb-comment">' +
          esc(row.comment || '-') +
          '</td>' +
          '</tr>'
        );
      })
      .join('');
  }

  function loadAll(page) {
    var err = $('#ch-fb-error', page);
    showError(err, '');
    var summaryUrl = page.getAttribute('data-summary-url') || '';
    var responsesUrl = page.getAttribute('data-responses-url') || '';
    return Promise.all([
      fetch(summaryUrl, { credentials: 'same-origin', headers: { Accept: 'application/json' } }).then(
        function (r) {
          return r.json();
        }
      ),
      fetch(responsesUrl + (responsesUrl.indexOf('?') >= 0 ? '&' : '?') + 'limit=75', {
        credentials: 'same-origin',
        headers: { Accept: 'application/json' }
      }).then(function (r) {
        return r.json();
      })
    ])
      .then(function (pair) {
        var sum = pair[0] || {};
        var list = pair[1] || {};
        if (!sum.ok) throw new Error(sum.error || 'Could not load summary.');
        if (!list.ok) throw new Error(list.error || 'Could not load responses.');
        renderSummary(page, sum.summary || {});
        renderRows(page, list.responses || []);
      })
      .catch(function (e) {
        showError(err, (e && e.message) || 'Could not load feedback analytics.');
        renderRows(page, []);
      });
  }

  function bindInvite(page) {
    var form = $('#ch-fb-invite-form', page);
    var createBtn = $('#ch-fb-create-link', page);
    var result = $('#ch-fb-link-result', page);
    var urlInput = $('#ch-fb-link-url', page);
    var copyBtn = $('#ch-fb-copy-link', page);
    var err = $('#ch-fb-error', page);
    var inviteUrl = page.getAttribute('data-invite-url') || '';

    if (createBtn && form) {
      createBtn.addEventListener('click', function () {
        var nameField = $('#ch-fb-name', page);
        if (nameField) nameField.focus();
        form.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      });
    }

    if (form) {
      form.addEventListener('submit', function (ev) {
        ev.preventDefault();
        showError(err, '');
        var payload = {
          customer_name: ($('#ch-fb-name', page) || {}).value || '',
          phone: ($('#ch-fb-phone', page) || {}).value || '',
          source: ($('#ch-fb-source', page) || {}).value || 'manual'
        };
        var headers = { Accept: 'application/json', 'Content-Type': 'application/json' };
        try {
          var csrf =
            (document.querySelector('meta[name="csrf-token"]') || {}).content ||
            (document.cookie.match(/(?:^|; )hbe_csrf=([^;]*)/) || [])[1];
          if (csrf) headers['X-CSRFToken'] = decodeURIComponent(csrf);
        } catch (eCsrf) {}
        fetch(inviteUrl, {
          method: 'POST',
          credentials: 'same-origin',
          headers: headers,
          body: JSON.stringify(payload)
        })
          .then(function (r) {
            return r.json().then(function (data) {
              return { okHttp: r.ok, data: data };
            });
          })
          .then(function (res) {
            if (!res.data || !res.data.ok || !res.data.invite) {
              throw new Error((res.data && res.data.error) || 'Could not create link.');
            }
            if (result) result.hidden = false;
            if (urlInput) {
              urlInput.value = res.data.invite.url || '';
              urlInput.select();
            }
            loadAll(page);
          })
          .catch(function (e) {
            showError(err, (e && e.message) || 'Could not create link.');
          });
      });
    }

    if (copyBtn && urlInput) {
      copyBtn.addEventListener('click', function () {
        var text = urlInput.value || '';
        if (!text) return;
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(text).catch(function () {
            urlInput.select();
            try {
              document.execCommand('copy');
            } catch (e2) {}
          });
        } else {
          urlInput.select();
          try {
            document.execCommand('copy');
          } catch (e3) {}
        }
      });
    }
  }

  function initFeedbackPage() {
    var page = pageRoot();
    if (!page || page.getAttribute('data-ch-fb-bound') === '1') return;
    page.setAttribute('data-ch-fb-bound', '1');
    bindInvite(page);
    var refresh = $('#ch-fb-refresh', page);
    if (refresh) {
      refresh.addEventListener('click', function () {
        loadAll(page);
      });
    }
    loadAll(page);
  }

  global.initFeedbackPage = initFeedbackPage;
  global.initCommunicationHubFeedbackPage = initFeedbackPage;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initFeedbackPage);
  } else {
    initFeedbackPage();
  }
})(typeof window !== 'undefined' ? window : this);
