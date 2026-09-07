(function (global) {
  'use strict';

  var STAR_FILLED = '\u2605';
  var STAR_EMPTY = '\u2606';

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
    var out = '';
    var i;
    for (i = 0; i < 5; i++) {
      if (i < v) {
        out += '<span class="ch-fb-star-filled">' + STAR_FILLED + '</span>';
      } else {
        out += '<span class="ch-fb-star-empty">' + STAR_EMPTY + '</span>';
      }
    }
    return out;
  }

  function starsPlain(n) {
    var v = Math.max(0, Math.min(5, parseInt(n, 10) || 0));
    return STAR_FILLED.repeat(v) + STAR_EMPTY.repeat(5 - v);
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

  function formatTrend(value, suffix) {
    if (value == null || value === '' || Number.isNaN(Number(value))) return '';
    var n = Number(value);
    var sign = n > 0 ? '+' : '';
    var arrow = n < 0 ? '\u2193' : '\u2191';
    return arrow + ' ' + sign + n + (suffix || '') + ' vs last month';
  }

  function setTrend(page, key, text, isDown) {
    var el = page.querySelector('[data-kpi-trend="' + key + '"]');
    if (!el) return;
    if (!text) {
      el.hidden = true;
      el.textContent = '';
      el.classList.remove('is-down');
      return;
    }
    el.hidden = false;
    el.textContent = text;
    el.classList.toggle('is-down', !!isDown);
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
    var elChip = page.querySelector('[data-kpi="responses-chip"]');
    if (elResp) elResp.textContent = String(responses);
    if (elAvg) elAvg.textContent = avg != null ? String(avg) : '-';
    if (elRate) elRate.textContent = rate != null ? rate + '%' : '-';
    if (elMonth) elMonth.textContent = String(month);
    if (elChip) elChip.textContent = String(responses);

    // Trends only when backend provides them — never invent percentages.
    var trends = summary.trends || {};
    var tResp = summary.responses_vs_last_month_pct;
    if (tResp == null && trends.responses_pct != null) tResp = trends.responses_pct;
    var tAvg = summary.avg_rating_vs_last_month;
    if (tAvg == null && trends.avg_rating != null) tAvg = trends.avg_rating;
    var tRate = summary.response_rate_vs_last_month_pct;
    if (tRate == null && trends.response_rate_pct != null) tRate = trends.response_rate_pct;
    var tMonth = summary.month_vs_last_month_pct;
    if (tMonth == null && trends.month_pct != null) tMonth = trends.month_pct;

    setTrend(page, 'responses', formatTrend(tResp, '%'), Number(tResp) < 0);
    setTrend(page, 'avg', formatTrend(tAvg, ''), Number(tAvg) < 0);
    setTrend(page, 'rate', formatTrend(tRate, '%'), Number(tRate) < 0);
    setTrend(page, 'month', formatTrend(tMonth, '%'), Number(tMonth) < 0);

    var dist = summary.rating_distribution || {};
    var total = 0;
    var i;
    for (i = 1; i <= 5; i++) {
      total += parseInt(dist[String(i)], 10) || 0;
    }
    if (total < 1) total = 0;
    var host = $('#ch-fb-dist', page);
    if (!host) return;
    var html = '';
    for (i = 5; i >= 1; i--) {
      var count = parseInt(dist[String(i)], 10) || 0;
      var share = total ? Math.round((100 * count) / total) : 0;
      var barPct = total ? Math.round((100 * count) / total) : 0;
      html +=
        '<div class="ch-fb-dist-row">' +
        '<span class="ch-fb-dist-label">' +
        i +
        ' <span class="ch-fb-dist-star" aria-hidden="true">' +
        STAR_FILLED +
        '</span></span>' +
        '<div class="ch-fb-dist-track"><div class="ch-fb-dist-fill" style="width:' +
        barPct +
        '%"></div></div>' +
        '<span class="ch-fb-dist-count">' +
        count +
        ' (' +
        share +
        '%)</span>' +
        '</div>';
    }
    host.innerHTML = html;
  }

  var GUEST_ICON =
    '<span class="ch-fb-guest-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg></span>';
  var GLOBE_ICON =
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>';
  var DOC_ICON =
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>';
  var MENU_ICON =
    '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><circle cx="12" cy="5" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="12" cy="19" r="1.6"/></svg>';

  function sourceIcon(source) {
    var s = String(source || '').toLowerCase();
    if (s === 'public' || s === 'qr' || s.indexOf('web') >= 0) return GLOBE_ICON;
    return DOC_ICON;
  }

  function renderRows(page, rows) {
    var tbody = $('#ch-fb-rows', page);
    if (!tbody) return;
    if (!rows || !rows.length) {
      tbody.innerHTML =
        '<tr class="ch-fb-empty"><td colspan="6">No feedback yet. Create a link and send it to a guest.</td></tr>';
      return;
    }
    tbody.innerHTML = rows
      .map(function (row) {
        var guestName = row.customer_name || 'Guest';
        var sourceLabel = row.source || '';
        var sourceExtra = row.outlet ? ' · ' + esc(row.outlet) : '';
        return (
          '<tr>' +
          '<td class="ch-fb-when">' +
          esc(row.submitted_at || '') +
          '</td>' +
          '<td><div class="ch-fb-guest-cell">' +
          GUEST_ICON +
          '<span>' +
          esc(guestName) +
          '</span></div>' +
          (row.phone ? '<div class="ch-fb-muted">' + esc(row.phone) + '</div>' : '') +
          '</td>' +
          '<td class="ch-fb-stars" title="' +
          esc(row.rating) +
          '/5">' +
          stars(row.rating) +
          '</td>' +
          '<td><span class="ch-fb-source-cell">' +
          sourceIcon(sourceLabel) +
          '<span>' +
          esc(sourceLabel) +
          sourceExtra +
          '</span></span></td>' +
          '<td class="ch-fb-comment">' +
          esc(row.comment || '-') +
          '</td>' +
          '<td class="ch-fb-th-action">' +
          '<button type="button" class="ch-fb-action-btn" aria-label="Row actions" title="Actions" disabled>' +
          MENU_ICON +
          '</button></td>' +
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

  function parseJsonSafe(response) {
    return response.text().then(function (text) {
      var data = null;
      if (text && String(text).trim()) {
        try {
          data = JSON.parse(text);
        } catch (eParse) {
          data = null;
        }
      }
      return {
        okHttp: response.ok,
        status: response.status,
        data: data,
        text: text || ''
      };
    });
  }

  function inviteHttpErrorMessage(res) {
    var status = res && res.status;
    var data = (res && res.data) || {};
    var serverMsg = data.error || data.message || '';
    if (status === 401) {
      return serverMsg || 'Please sign in again to create a feedback link.';
    }
    if (status === 403) {
      return (
        serverMsg ||
        'Could not create link (CSRF or permission). Refresh the page and try again.'
      );
    }
    if (status === 419) {
      return serverMsg || 'Session expired. Refresh the page and try again.';
    }
    if (status === 400) {
      return (
        serverMsg ||
        'Could not create link (CSRF). Refresh the page and try again.'
      );
    }
    if (serverMsg) return serverMsg;
    if (!res.okHttp) {
      var snippet = String((res && res.text) || '').replace(/<[^>]+>/g, ' ').trim();
      if (snippet && snippet.length < 180) return snippet;
      return 'Could not create link (HTTP ' + status + ').';
    }
    return 'Could not create link.';
  }

  function focusCreateForm(page) {
    var form = $('#ch-fb-invite-form', page);
    var panel = $('#ch-fb-create-panel', page);
    var nameField = $('#ch-fb-name', page);
    if (panel && panel.scrollIntoView) {
      panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    } else if (form && form.scrollIntoView) {
      form.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
    if (nameField) {
      try {
        nameField.focus();
      } catch (eFocus) {}
    }
  }

  function readCsrfToken() {
    try {
      var meta = document.querySelector('meta[name="csrf-token"]');
      if (meta && meta.content) return String(meta.content).trim();
      var m = document.cookie.match(/(?:^|; )hbe_csrf=([^;]*)/);
      if (m && m[1]) return decodeURIComponent(m[1]);
    } catch (e) {}
    return '';
  }

  function bindInvite(page) {
    var form = $('#ch-fb-invite-form', page);
    var createBtn = $('#ch-fb-create-link', page);
    var submitBtn = $('#ch-fb-invite-submit', page);
    var result = $('#ch-fb-link-result', page);
    var urlInput = $('#ch-fb-link-url', page);
    var expiryEl = $('#ch-fb-link-expiry', page);
    var copyBtn = $('#ch-fb-copy-link', page);
    var errTop = $('#ch-fb-error', page);
    var errLocal = $('#ch-fb-invite-error', page);
    var inviteUrl = page.getAttribute('data-invite-url') || '';
    var pending = false;

    function showInviteError(msg) {
      showError(errTop, msg);
      showError(errLocal, msg);
      if (msg && errLocal && errLocal.scrollIntoView) {
        try {
          errLocal.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        } catch (eScroll) {}
      }
    }

    function createInvite(opts) {
      opts = opts || {};
      if (pending) return;
      showInviteError('');
      if (!inviteUrl) {
        showInviteError('Invite API URL is missing. Refresh the page.');
        return;
      }
      var payload = {
        customer_name: ($('#ch-fb-name', page) || {}).value || '',
        phone: ($('#ch-fb-phone', page) || {}).value || '',
        source: ($('#ch-fb-source', page) || {}).value || 'manual'
      };
      var csrf = readCsrfToken();
      if (csrf) payload.csrf_token = csrf;
      var headers = { Accept: 'application/json', 'Content-Type': 'application/json' };
      if (csrf) {
        headers['X-CSRFToken'] = csrf;
        headers['X-CSRF-Token'] = csrf;
      }
      pending = true;
      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.setAttribute('aria-busy', 'true');
      }
      if (createBtn) createBtn.disabled = true;
      fetch(inviteUrl, {
        method: 'POST',
        credentials: 'same-origin',
        headers: headers,
        body: JSON.stringify(payload)
      })
        .then(parseJsonSafe)
        .then(function (res) {
          if (!res.okHttp || !res.data || !res.data.ok || !res.data.invite) {
            throw new Error(inviteHttpErrorMessage(res));
          }
          var invite = res.data.invite || {};
          if (result) result.hidden = false;
          if (urlInput) {
            urlInput.value = invite.url || '';
            try {
              urlInput.focus();
              urlInput.select();
            } catch (eSel) {}
          }
          if (expiryEl) {
            var expiresAt = invite.expires_at || '';
            var hours =
              invite.expires_in_hours != null ? invite.expires_in_hours : 24;
            expiryEl.hidden = false;
            expiryEl.textContent = expiresAt
              ? 'Valid for ' + hours + ' hours — expires ' + expiresAt + ' (belleliteaccounts.com).'
              : 'Valid for ' + hours + ' hours on belleliteaccounts.com.';
          }
          if (result && result.scrollIntoView) {
            try {
              result.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            } catch (eRes) {}
          }
          loadAll(page);
        })
        .catch(function (e) {
          showInviteError((e && e.message) || 'Could not create link.');
        })
        .then(function () {
          pending = false;
          if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.removeAttribute('aria-busy');
          }
          if (createBtn) createBtn.disabled = false;
        });
    }

    if (createBtn) {
      createBtn.addEventListener('click', function () {
        focusCreateForm(page);
        createInvite({ fromHeader: true });
      });
    }

    if (form) {
      form.addEventListener('submit', function (ev) {
        ev.preventDefault();
        createInvite({ fromForm: true });
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
  // Expose for light unit checks / debugging
  global._chFbStarsPlain = starsPlain;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initFeedbackPage);
  } else {
    initFeedbackPage();
  }
})(typeof window !== 'undefined' ? window : this);
