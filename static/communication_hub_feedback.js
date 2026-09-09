(function (global) {
  'use strict';

  var STAR_FILLED = '\u2605';
  var STAR_EMPTY = '\u2606';
  var feedbackOutletFilter = 'all';
  var feedbackDateFrom = '';
  var feedbackDateTo = '';

  function $(sel, root) {
    return (root || document).querySelector(sel);
  }

  function currentOutletFilter(page) {
    var root = page || pageRoot();
    var active =
      root &&
      root.querySelector('#ch-fb-type-filter-tabs .ch-fb-type-filter-tab.is-active');
    if (active) {
      feedbackOutletFilter = String(active.getAttribute('data-fb-filter') || 'all');
    }
    return feedbackOutletFilter || 'all';
  }

  function syncDateChipState(page) {
    var root = page || pageRoot();
    if (!root) return;
    var fromEl = $('#ch-fb-date-from', root);
    var toEl = $('#ch-fb-date-to', root);
    var display = $('#ch-fb-date-range-display', root);
    var chip = root.querySelector('.ch-fb-date-chip');
    feedbackDateFrom = fromEl ? String(fromEl.value || '').trim() : '';
    feedbackDateTo = toEl ? String(toEl.value || '').trim() : '';
    var active = !!(feedbackDateFrom || feedbackDateTo);
    if (chip) chip.classList.toggle('is-filtered', active);
    if (display && !active) display.textContent = 'Select date…';
    if (
      active &&
      global.SalesDateRangePicker &&
      typeof global.SalesDateRangePicker.syncChipDisplays === 'function'
    ) {
      global.SalesDateRangePicker.syncChipDisplays();
    }
  }

  function currentDateFilter(page) {
    syncDateChipState(page);
    return { from: feedbackDateFrom || '', to: feedbackDateTo || '' };
  }

  function filterQuery(page) {
    var outlet = currentOutletFilter(page);
    var dates = currentDateFilter(page);
    var parts = ['outlet=' + encodeURIComponent(outlet)];
    if (dates.from) parts.push('date_from=' + encodeURIComponent(dates.from));
    if (dates.to) parts.push('date_to=' + encodeURIComponent(dates.to));
    return parts.join('&');
  }

  function setOutletFilter(value, page) {
    var next = String(value || 'all').trim().toLowerCase();
    if (next !== 'hotel' && next !== 'restaurant' && next !== 'bar') next = 'all';
    feedbackOutletFilter = next;
    var root = page || pageRoot();
    var tabs = root ? root.querySelectorAll('#ch-fb-type-filter-tabs [data-fb-filter]') : [];
    for (var i = 0; i < tabs.length; i++) {
      var on = String(tabs[i].getAttribute('data-fb-filter') || '') === next;
      tabs[i].classList.toggle('is-active', on);
      tabs[i].setAttribute('aria-selected', on ? 'true' : 'false');
    }
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

  var MONTH_SHORT = [
    'Jan',
    'Feb',
    'Mar',
    'Apr',
    'May',
    'Jun',
    'Jul',
    'Aug',
    'Sep',
    'Oct',
    'Nov',
    'Dec'
  ];

  function formatWhen(value) {
    var raw = String(value || '').trim();
    if (!raw) return '';
    var m = raw.match(/^(\d{4})-(\d{2})-(\d{2})/);
    if (!m) return raw;
    var year = parseInt(m[1], 10);
    var month = parseInt(m[2], 10);
    var day = parseInt(m[3], 10);
    if (!year || !month || !day || month < 1 || month > 12) return raw;
    var yy = String(year % 100).padStart(2, '0');
    return day + '-' + MONTH_SHORT[month - 1] + '-' + yy;
  }

  /** Display phone with an explicit dial code, e.g. "+91 9679544061". */
  function formatFeedbackPhone(value) {
    var raw = String(value || '').trim();
    if (!raw) return '';
    var digits = raw.replace(/\D+/g, '');
    if (!digits) return raw;
    var cc = '';
    var local = '';
    if (digits.length === 10) {
      cc = '91';
      local = digits;
    } else if (digits.length >= 11 && digits.indexOf('91') === 0 && digits.length <= 13) {
      cc = '91';
      local = digits.slice(2);
    } else if (digits.length >= 11 && digits.length <= 15) {
      // Prefer common 1–3 digit country codes; default to leading 2 for IN/region.
      if (digits.charAt(0) === '1' && digits.length === 11) {
        cc = '1';
        local = digits.slice(1);
      } else {
        cc = digits.slice(0, 2);
        local = digits.slice(2);
      }
    } else {
      return '+' + digits;
    }
    if (!local) return '+' + cc;
    return '+' + cc + ' ' + local;
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

  var feedbackRowsCache = [];
  var feedbackSort = { key: 'when', ascending: false };
  var feedbackSearchQuery = '';

  function feedbackSearchFields(row) {
    var phone = String((row && row.phone) || '');
    return [
      (row && row.customer_name) || '',
      phone,
      formatFeedbackPhone(phone),
      phone.replace(/\D+/g, ''),
      (row && row.rating) != null ? String(row.rating) : '',
      (row && (row.source_label || row.source)) || '',
      (row && row.location) || '',
      (row && row.comment) || '',
      (row && row.submitted_at) || '',
      formatWhen((row && row.submitted_at) || ''),
      (row && row.outlet) || ''
    ];
  }

  function rowMatchesSearch(row, query) {
    var q = String(query || '').trim();
    if (!q) return true;
    var fields = feedbackSearchFields(row);
    if (typeof global.hbeBestSearchScore === 'function') {
      return global.hbeBestSearchScore(fields, q) >= 0;
    }
    var needle = q.toLowerCase();
    for (var i = 0; i < fields.length; i++) {
      if (String(fields[i] || '').toLowerCase().indexOf(needle) >= 0) return true;
    }
    return false;
  }

  function visibleFeedbackRows() {
    var sorted = sortedFeedbackRows(feedbackRowsCache);
    var q = String(feedbackSearchQuery || '').trim();
    if (!q) return sorted;
    if (typeof global.hbeBestSearchScore === 'function') {
      var ranked = sorted
        .map(function (row) {
          return {
            row: row,
            score: global.hbeBestSearchScore(feedbackSearchFields(row), q)
          };
        })
        .filter(function (entry) {
          return entry.score >= 0;
        });
      ranked.sort(function (a, b) {
        return b.score - a.score;
      });
      return ranked.map(function (entry) {
        return entry.row;
      });
    }
    return sorted.filter(function (row) {
      return rowMatchesSearch(row, q);
    });
  }

  function parseNaturalCode(value) {
    var raw = String(value == null ? '' : value).trim();
    var match = raw.match(/^(.*?)(\d+)\s*$/);
    if (!match) {
      return { prefix: raw.toLowerCase(), num: null };
    }
    return {
      prefix: String(match[1] || '').toLowerCase(),
      num: parseInt(match[2], 10)
    };
  }

  function compareNaturalCode(a, b) {
    var av = parseNaturalCode(a);
    var bv = parseNaturalCode(b);
    var cmp = av.prefix.localeCompare(bv.prefix, undefined, { sensitivity: 'base' });
    if (cmp) return cmp;
    if (av.num == null && bv.num == null) {
      return String(a || '').localeCompare(String(b || ''), undefined, {
        sensitivity: 'base'
      });
    }
    if (av.num == null) return 1;
    if (bv.num == null) return -1;
    return av.num - bv.num;
  }

  function feedbackSortValue(row, key) {
    if (!row) return '';
    if (key === 'when') return String(row.submitted_at || '');
    if (key === 'guest') return String(row.customer_name || '');
    if (key === 'mobile') return String(row.phone || '').replace(/\D+/g, '');
    if (key === 'rating') {
      var n = Number(row.rating);
      return isFinite(n) ? n : 0;
    }
    if (key === 'source') return String(row.source_label || row.source || '');
    if (key === 'location') return String(row.location || '').trim();
    if (key === 'comment') return String(row.comment || '');
    return '';
  }

  function sortedFeedbackRows(rows) {
    var list = Array.isArray(rows) ? rows.slice() : [];
    var key = feedbackSort.key || 'when';
    var ascending = !!feedbackSort.ascending;
    var type =
      key === 'rating' ? 'number' : key === 'location' ? 'natural' : 'text';
    list.sort(function (a, b) {
      var av = feedbackSortValue(a, key);
      var bv = feedbackSortValue(b, key);
      var cmp = 0;
      if (type === 'number') cmp = av - bv;
      else if (type === 'natural') cmp = compareNaturalCode(av, bv);
      else
        cmp = String(av).localeCompare(String(bv), undefined, {
          numeric: true,
          sensitivity: 'base'
        });
      // Empty locations/comments sink to the bottom in either direction.
      if (key === 'location' || key === 'comment' || key === 'guest') {
        var aEmpty = !String(av || '').trim();
        var bEmpty = !String(bv || '').trim();
        if (aEmpty !== bEmpty) return aEmpty ? 1 : -1;
      }
      return ascending ? cmp : -cmp;
    });
    return list;
  }

  function updateSortHeaders(page) {
    var root = page || pageRoot();
    if (!root) return;
    var headers = root.querySelectorAll('.ch-fb-table th.ch-fb-sortable');
    for (var i = 0; i < headers.length; i++) {
      var th = headers[i];
      var key = th.getAttribute('data-sort') || '';
      th.classList.remove('is-sorted-asc', 'is-sorted-desc');
      if (key && key === feedbackSort.key) {
        th.classList.add(feedbackSort.ascending ? 'is-sorted-asc' : 'is-sorted-desc');
        th.setAttribute(
          'aria-sort',
          feedbackSort.ascending ? 'ascending' : 'descending'
        );
      } else {
        th.setAttribute('aria-sort', 'none');
      }
    }
  }

  function bindTableSort(page) {
    var root = page || pageRoot();
    if (!root) return;
    var table = root.querySelector('table.ch-fb-table');
    if (!table || table.getAttribute('data-ch-fb-sort-bound') === '1') return;
    table.setAttribute('data-ch-fb-sort-bound', '1');

    function onSort(th) {
      var key = th.getAttribute('data-sort') || '';
      if (!key) return;
      if (feedbackSort.key === key) {
        feedbackSort.ascending = !feedbackSort.ascending;
      } else {
        feedbackSort.key = key;
        feedbackSort.ascending = key === 'when' ? false : true;
      }
      renderRows(root, feedbackRowsCache);
    }

    var headers = table.querySelectorAll('th.ch-fb-sortable');
    for (var i = 0; i < headers.length; i++) {
      (function (th) {
        th.addEventListener('click', function () {
          onSort(th);
        });
        th.addEventListener('keydown', function (e) {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            onSort(th);
          }
        });
      })(headers[i]);
    }
  }

  function renderRows(page, rows) {
    var tbody = $('#ch-fb-rows', page);
    if (!tbody) return;
    if (arguments.length > 1) {
      feedbackRowsCache = Array.isArray(rows) ? rows.slice() : [];
    }
    updateSortHeaders(page);
    var searchChip = page && page.querySelector('#ch-fb-search-chip');
    var hasSearch = !!String(feedbackSearchQuery || '').trim();
    if (searchChip) searchChip.classList.toggle('is-active', hasSearch);
    if (!feedbackRowsCache.length) {
      tbody.innerHTML =
        '<tr class="ch-fb-empty"><td colspan="7">No feedback yet. Create a link and send it to a guest.</td></tr>';
      return;
    }
    var visible = visibleFeedbackRows();
    if (!visible.length) {
      tbody.innerHTML =
        '<tr class="ch-fb-empty"><td colspan="7">No feedback matches your search.</td></tr>';
      return;
    }
    tbody.innerHTML = visible
      .map(function (row) {
        var guestName = row.customer_name || 'Guest';
        var sourceLabel = row.source_label || row.source || '';
        var location = String(row.location || '').trim();
        var phone = formatFeedbackPhone(row.phone);
        var phoneParts = phone ? phone.split(/\s+/) : [];
        var phoneHtml = '—';
        if (phoneParts.length >= 2) {
          phoneHtml =
            '<span class="ch-fb-mobile-cc">' +
            esc(phoneParts[0]) +
            '</span> ' +
            esc(phoneParts.slice(1).join(' '));
        } else if (phone) {
          phoneHtml = esc(phone);
        }
        var whenRaw = String(row.submitted_at || '');
        var phoneDigits = String(row.phone || '').replace(/\D+/g, '');
        return (
          '<tr class="ch-fb-row">' +
          '<td class="ch-fb-when" data-label="When" data-sort-value="' +
          esc(whenRaw) +
          '" title="' +
          esc(whenRaw) +
          '">' +
          esc(formatWhen(row.submitted_at)) +
          '</td>' +
          '<td data-label="Guest" data-sort-value="' +
          esc(guestName) +
          '"><div class="ch-fb-guest-cell">' +
          GUEST_ICON +
          '<span>' +
          esc(guestName) +
          '</span></div></td>' +
          '<td class="ch-fb-mobile" data-label="Mobile" data-sort-value="' +
          esc(phoneDigits) +
          '" title="' +
          esc(phone || '') +
          '">' +
          phoneHtml +
          '</td>' +
          '<td class="ch-fb-stars" data-label="Rating" data-sort-value="' +
          esc(row.rating) +
          '" title="' +
          esc(row.rating) +
          '/5">' +
          stars(row.rating) +
          '</td>' +
          '<td class="ch-fb-source" data-label="Source" data-sort-value="' +
          esc(sourceLabel) +
          '">' +
          esc(sourceLabel || '—') +
          '</td>' +
          '<td class="ch-fb-location" data-label="Location" data-sort-value="' +
          esc(location) +
          '">' +
          esc(location || '—') +
          '</td>' +
          '<td class="ch-fb-comment" data-label="Comment" data-sort-value="' +
          esc(row.comment || '') +
          '">' +
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
    var q = filterQuery(page);
    var sumUrl = summaryUrl + (summaryUrl.indexOf('?') >= 0 ? '&' : '?') + q;
    var listUrl =
      responsesUrl +
      (responsesUrl.indexOf('?') >= 0 ? '&' : '?') +
      q +
      '&limit=75';
    return Promise.all([
      fetch(sumUrl, {
        credentials: 'same-origin',
        headers: { Accept: 'application/json', 'X-Requested-With': 'XMLHttpRequest' }
      }).then(function (r) {
        return r.json();
      }),
      fetch(listUrl, {
        credentials: 'same-origin',
        headers: { Accept: 'application/json', 'X-Requested-With': 'XMLHttpRequest' }
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

  function readCsrfToken() {
    try {
      if (global.HbeCsrf && typeof global.HbeCsrf.getToken === 'function') {
        var t = String(global.HbeCsrf.getToken() || '').trim();
        if (t) return t;
      }
      var meta = document.querySelector('meta[name="csrf-token"]');
      if (meta && meta.content) return String(meta.content).trim();
      var m = document.cookie.match(/(?:^|; )hbe_csrf=([^;]*)/);
      if (m && m[1]) return decodeURIComponent(m[1]);
    } catch (e) {}
    return '';
  }

  function copyText(urlInput, text) {
    if (!text) return;
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).catch(function () {
        if (urlInput && urlInput.select) urlInput.select();
        try {
          document.execCommand('copy');
        } catch (e2) {}
      });
    } else if (urlInput) {
      urlInput.select();
      try {
        document.execCommand('copy');
      } catch (e3) {}
    }
  }

  function bindInvite(page) {
    var createBtn = $('#ch-fb-create-link', page);
    var errTop = $('#ch-fb-error', page);
    var inviteUrl = page.getAttribute('data-invite-url') || '';
    var pending = false;
    var modal = document.getElementById('ch-fb-link-modal');
    var modalErr = document.getElementById('ch-fb-link-error');
    var waOutlet = '';

    function showInviteError(msg) {
      showError(errTop, msg);
    }

    function showModalError(msg, isOk) {
      showError(modalErr, msg);
      if (!modalErr) return;
      if (isOk) {
        modalErr.style.background = '#ECFDF5';
        modalErr.style.borderColor = 'rgba(22,163,74,.25)';
        modalErr.style.color = '#15803D';
      } else {
        modalErr.style.background = '';
        modalErr.style.borderColor = '';
        modalErr.style.color = '';
      }
    }

    function setStep(name) {
      modal = document.getElementById('ch-fb-link-modal');
      if (!modal) return;
      var steps = modal.querySelectorAll('[data-fb-step]');
      var i;
      for (i = 0; i < steps.length; i++) {
        var step = steps[i];
        var on = step.getAttribute('data-fb-step') === name;
        step.hidden = !on;
      }
      var titleLogo = document.getElementById('ch-fb-link-title-logo');
      if (titleLogo) {
        var showWaLogo = name === 'wa-phone';
        titleLogo.hidden = !showWaLogo;
        if (showWaLogo) titleLogo.removeAttribute('hidden');
        else titleLogo.setAttribute('hidden', '');
      }
      var titleBack = document.getElementById('ch-fb-link-title-back');
      if (titleBack) {
        var showBack = name === 'wa-phone' || name === 'create';
        titleBack.hidden = !showBack;
        if (showBack) titleBack.removeAttribute('hidden');
        else titleBack.setAttribute('hidden', '');
      }
      showModalError('');
    }

    function syncLocationFields(outlet) {
      var key = String(outlet || '').trim().toLowerCase();
      var isHotel = key === 'hotel';
      var isTable = key === 'restaurant' || key === 'bar';
      var show = isHotel || isTable;
      var label = isHotel ? 'Room number' : 'Table number';
      var placeholder = isHotel ? 'e.g. 101' : 'e.g. T12';
      var createField = document.getElementById('ch-fb-create-location-field');
      var createLabel = document.getElementById('ch-fb-create-location-label');
      var createInput = document.getElementById('ch-fb-modal-create-location');
      var waField = document.getElementById('ch-fb-wa-location-field');
      var waLabel = document.getElementById('ch-fb-wa-location-label');
      var waInput = document.getElementById('ch-fb-modal-wa-location');
      if (createField) {
        createField.hidden = !show;
        if (show) createField.removeAttribute('hidden');
        else createField.setAttribute('hidden', '');
      }
      if (createLabel) createLabel.textContent = label;
      if (createInput) createInput.placeholder = placeholder;
      if (waField) {
        waField.hidden = !show;
        if (show) waField.removeAttribute('hidden');
        else waField.setAttribute('hidden', '');
      }
      if (waLabel) waLabel.textContent = label;
      if (waInput) waInput.placeholder = placeholder;
    }

    function selectOutlet(outlet) {
      waOutlet = String(outlet || '').trim();
      var live = document.getElementById('ch-fb-link-modal');
      var outlets = live ? live.querySelectorAll('[data-fb-outlet]') : [];
      for (var j = 0; j < outlets.length; j++) {
        var on = String(outlets[j].getAttribute('data-fb-outlet') || '') === waOutlet;
        outlets[j].classList.toggle('is-active', on);
        outlets[j].setAttribute('aria-selected', on ? 'true' : 'false');
        outlets[j].setAttribute('aria-pressed', on ? 'true' : 'false');
      }
      var sendBtn = document.getElementById('ch-fb-modal-wa-send');
      if (sendBtn) sendBtn.disabled = !waOutlet;
      var createSubmit = document.getElementById('ch-fb-modal-create-submit');
      if (createSubmit) createSubmit.disabled = !waOutlet;
      syncLocationFields(waOutlet);
      showModalError('');
    }

    global._chFbSelectOutlet = selectOutlet;
    global._chFbSetLinkStep = setStep;

    function resetModal() {
      selectOutlet('');
      var createName = document.getElementById('ch-fb-modal-create-name');
      var waName = document.getElementById('ch-fb-modal-wa-name');
      var waPhone = document.getElementById('ch-fb-modal-wa-phone');
      var createLoc = document.getElementById('ch-fb-modal-create-location');
      var waLoc = document.getElementById('ch-fb-modal-wa-location');
      if (createName) createName.value = '';
      if (waName) waName.value = '';
      if (waPhone) waPhone.value = '';
      if (createLoc) createLoc.value = '';
      if (waLoc) waLoc.value = '';
      var modalResult = document.getElementById('ch-fb-modal-link-result');
      var modalUrl = document.getElementById('ch-fb-modal-link-url');
      var modalExpiry = document.getElementById('ch-fb-modal-link-expiry');
      if (modalResult) {
        modalResult.hidden = true;
        modalResult.setAttribute('hidden', '');
      }
      if (modalUrl) modalUrl.value = '';
      if (modalExpiry) {
        modalExpiry.hidden = true;
        modalExpiry.textContent = '';
      }
      setStep('choose');
    }

    function ensureModalDelegate() {
      var live = document.getElementById('ch-fb-link-modal');
      if (!live || live.getAttribute('data-fb-delegate') === '1') return;
      live.setAttribute('data-fb-delegate', '1');
      live.addEventListener('click', function (ev) {
        if (ev.target === live) {
          closeModal();
          return;
        }
        var outletBtn =
          ev.target && ev.target.closest
            ? ev.target.closest('[data-fb-outlet]')
            : null;
        if (outletBtn && live.contains(outletBtn)) {
          selectOutlet(outletBtn.getAttribute('data-fb-outlet'));
          return;
        }
        var choiceWa =
          ev.target && ev.target.closest
            ? ev.target.closest('#ch-fb-choice-whatsapp')
            : null;
        if (choiceWa) {
          setStep('wa-phone');
          var phoneEl = document.getElementById('ch-fb-modal-wa-phone');
          if (phoneEl) {
            try {
              phoneEl.focus();
            } catch (eW) {}
          }
          return;
        }
        var choiceCreate =
          ev.target && ev.target.closest
            ? ev.target.closest('#ch-fb-choice-create')
            : null;
        if (choiceCreate) {
          setStep('create');
          return;
        }
        var backBtn =
          ev.target && ev.target.closest
            ? ev.target.closest('[data-fb-back]')
            : null;
        if (backBtn && live.contains(backBtn)) {
          var target = backBtn.getAttribute('data-fb-back');
          if (target && target !== 'true' && target !== '') setStep(target);
          else setStep('choose');
          return;
        }
        var sendBtn =
          ev.target && ev.target.closest
            ? ev.target.closest('#ch-fb-modal-wa-send')
            : null;
        if (sendBtn) {
          sendWhatsApp();
          return;
        }
        var createSubmit =
          ev.target && ev.target.closest
            ? ev.target.closest('#ch-fb-modal-create-submit')
            : null;
        if (createSubmit) {
          submitCreateLink();
          return;
        }
        var closeBtn =
          ev.target && ev.target.closest
            ? ev.target.closest('#ch-fb-link-close')
            : null;
        if (closeBtn) closeModal();
      });
      live.addEventListener('keydown', function (ev) {
        if (ev.target && ev.target.id === 'ch-fb-modal-wa-phone' && ev.key === 'Enter') {
          ev.preventDefault();
          sendWhatsApp();
        }
      });
    }

    function submitCreateLink() {
      if (!waOutlet) {
        showModalError('Choose Hotel, Restaurant, or Bar before creating a link.');
        return;
      }
      var location = String(
        (document.getElementById('ch-fb-modal-create-location') || {}).value || ''
      ).trim();
      createInvite({
        fromModal: true,
        payload: {
          customer_name: String((document.getElementById('ch-fb-modal-create-name') || {}).value || '').trim(),
          phone: '',
          source: waOutlet,
          outlet: waOutlet,
          location: location,
          room_number: waOutlet === 'hotel' ? location : '',
          table: waOutlet !== 'hotel' ? location : '',
          table_label: waOutlet !== 'hotel' ? location : ''
        }
      });
    }
    global._chFbSubmitCreateLink = submitCreateLink;

    function openModal() {
      var live = document.getElementById('ch-fb-link-modal');
      if (!live) return;
      modal = live;
      modalErr = document.getElementById('ch-fb-link-error');
      ensureModalDelegate();
      resetModal();
      live.classList.add('open');
      live.setAttribute('aria-hidden', 'false');
    }

    function closeModal() {
      var live = document.getElementById('ch-fb-link-modal');
      if (!live) return;
      live.classList.remove('open');
      live.setAttribute('aria-hidden', 'true');
      showModalError('');
    }

    function paintInviteResult(invite) {
      var targetResult = document.getElementById('ch-fb-modal-link-result');
      var targetUrl = document.getElementById('ch-fb-modal-link-url');
      var targetExpiry = document.getElementById('ch-fb-modal-link-expiry');
      if (targetResult) {
        targetResult.hidden = false;
        targetResult.removeAttribute('hidden');
        targetResult.style.display = 'block';
      }
      if (targetUrl) {
        targetUrl.value = invite.url || '';
        try {
          targetUrl.focus();
          targetUrl.select();
        } catch (eSel) {}
      }
      if (targetExpiry) {
        var expiresAt = invite.expires_at || '';
        var hours =
          invite.expires_in_hours != null ? invite.expires_in_hours : 24;
        targetExpiry.hidden = false;
        targetExpiry.textContent = expiresAt
          ? 'Valid for ' + hours + ' hours — expires ' + expiresAt + ' (belleliteaccounts.com).'
          : 'Valid for ' + hours + ' hours on belleliteaccounts.com.';
      }
    }

    function createInvite(opts) {
      opts = opts || {};
      if (pending) return Promise.resolve();
      showInviteError('');
      showModalError('');
      if (!inviteUrl) {
        showModalError('Invite API URL is missing. Refresh the page.');
        return Promise.resolve();
      }
      var payload = opts.payload || {
        customer_name: '',
        phone: '',
        source: 'manual'
      };
      var csrf = readCsrfToken();
      if (csrf) payload.csrf_token = csrf;
      payload.action = 'create_invite';
      var headers = {
        Accept: 'application/json',
        'Content-Type': 'application/json',
        'X-Requested-With': 'XMLHttpRequest'
      };
      if (csrf) {
        headers['X-CSRFToken'] = csrf;
        headers['X-CSRF-Token'] = csrf;
      }
      var fallbackUrl = page.getAttribute('data-invite-fallback-url') || '';
      pending = true;
      if (createBtn) createBtn.disabled = true;
      var modalCreateBtn = document.getElementById('ch-fb-modal-create-submit');
      if (modalCreateBtn) modalCreateBtn.disabled = true;

      function postInvite(url) {
        return fetch(url, {
          method: 'POST',
          credentials: 'same-origin',
          headers: headers,
          body: JSON.stringify(payload)
        }).then(parseJsonSafe);
      }

      return postInvite(inviteUrl)
        .then(function (res) {
          if (res.okHttp && res.data && res.data.ok && res.data.invite) return res;
          var status = res.status || 0;
          var looksBlocked =
            !res.data ||
            status === 403 ||
            status === 429 ||
            status === 502 ||
            status === 503 ||
            status >= 500 ||
            (res.text && /cloudflare|attention required|just a moment/i.test(res.text));
          if (fallbackUrl && fallbackUrl !== inviteUrl && looksBlocked) {
            return postInvite(fallbackUrl);
          }
          return res;
        })
        .then(function (res) {
          if (!res.okHttp || !res.data || !res.data.ok || !res.data.invite) {
            throw new Error(inviteHttpErrorMessage(res));
          }
          paintInviteResult(res.data.invite || {});
          loadAll(page);
        })
        .catch(function (e) {
          showModalError((e && e.message) || 'Could not create link.');
        })
        .then(function () {
          pending = false;
          if (createBtn) createBtn.disabled = false;
          if (modalCreateBtn) modalCreateBtn.disabled = !waOutlet;
        });
    }

    function sendWhatsApp() {
      if (pending) return;
      showModalError('');
      var sendUrl = page.getAttribute('data-send-whatsapp-url') || '';
      var fallbackUrl = page.getAttribute('data-send-whatsapp-fallback-url') || '';
      if (!sendUrl) {
        showModalError('WhatsApp send URL is missing. Refresh the page.');
        return;
      }
      var phone = String((document.getElementById('ch-fb-modal-wa-phone') || {}).value || '').trim();
      if (!phone) {
        showModalError('Enter a WhatsApp number.');
        var phoneEl = document.getElementById('ch-fb-modal-wa-phone');
        if (phoneEl) {
          try {
            phoneEl.focus();
          } catch (eF) {}
        }
        return;
      }
      if (!waOutlet) {
        showModalError('Choose Hotel, Restaurant, or Bar before sending.');
        return;
      }
      var location = String(
        (document.getElementById('ch-fb-modal-wa-location') || {}).value || ''
      ).trim();
      var payload = {
        customer_name: String((document.getElementById('ch-fb-modal-wa-name') || {}).value || '').trim(),
        phone: phone,
        mobile: phone,
        outlet: waOutlet,
        source: waOutlet,
        location: location,
        room_number: waOutlet === 'hotel' ? location : '',
        table: waOutlet !== 'hotel' ? location : '',
        table_label: waOutlet !== 'hotel' ? location : '',
        action: 'send_whatsapp'
      };
      var csrf = readCsrfToken();
      if (csrf) payload.csrf_token = csrf;
      var headers = {
        Accept: 'application/json',
        'Content-Type': 'application/json',
        'X-Requested-With': 'XMLHttpRequest'
      };
      if (csrf) {
        headers['X-CSRFToken'] = csrf;
        headers['X-CSRF-Token'] = csrf;
      }
      pending = true;
      var sendBtn = document.getElementById('ch-fb-modal-wa-send');
      if (sendBtn) {
        sendBtn.disabled = true;
        sendBtn.setAttribute('aria-busy', 'true');
      }
      if (createBtn) createBtn.disabled = true;

      function postSend(url) {
        return fetch(url, {
          method: 'POST',
          credentials: 'same-origin',
          headers: headers,
          body: JSON.stringify(payload)
        }).then(parseJsonSafe);
      }

      postSend(sendUrl)
        .then(function (res) {
          if (res.okHttp && res.data && res.data.ok) return res;
          var status = res.status || 0;
          var looksBlocked =
            !res.data ||
            status === 403 ||
            status === 429 ||
            status === 502 ||
            status === 503 ||
            status >= 500 ||
            (res.text && /cloudflare|attention required|just a moment/i.test(res.text));
          if (fallbackUrl && fallbackUrl !== sendUrl && looksBlocked) {
            return postSend(fallbackUrl);
          }
          return res;
        })
        .then(function (res) {
          if (!res.okHttp || !res.data || !res.data.ok) {
            throw new Error(inviteHttpErrorMessage(res) || 'Could not send on WhatsApp.');
          }
          var invite = (res.data && res.data.invite) || {};
          var dry = !!(res.data && res.data.dry_run);
          paintInviteResult(invite);
          showInviteError('');
          showModalError(
            dry
              ? 'WhatsApp dry-run OK — feedback invite created.'
              : 'Feedback link sent on WhatsApp.',
            true
          );
          loadAll(page);
        })
        .catch(function (e) {
          showModalError((e && e.message) || 'Could not send on WhatsApp.');
        })
        .then(function () {
          pending = false;
          if (sendBtn) {
            sendBtn.disabled = !waOutlet;
            sendBtn.removeAttribute('aria-busy');
          }
          if (createBtn) createBtn.disabled = false;
        });
    }

    global._chFbSendWhatsApp = sendWhatsApp;
    global._chFbCloseLinkModal = closeModal;

    if (createBtn) {
      createBtn.addEventListener('click', function () {
        openModal();
      });
    }
    global._chFbOpenLinkModal = openModal;
    ensureModalDelegate();

    if (modal) {
      var modalCopy = document.getElementById('ch-fb-modal-copy-link');
      var modalUrl = document.getElementById('ch-fb-modal-link-url');
      if (modalCopy && modalUrl) {
        modalCopy.addEventListener('click', function () {
          copyText(modalUrl, modalUrl.value || '');
        });
      }
    }

    document.addEventListener('keydown', function (ev) {
      var live = document.getElementById('ch-fb-link-modal');
      if (!live || !live.classList.contains('open')) return;
      if (ev.key === 'Escape') {
        ev.preventDefault();
        closeModal();
      }
    });
  }

  function bindDateRange(page) {
    var root = page || pageRoot();
    if (!root) return;
    var wrap = $('#ch-fb-date-range-wrap', root);
    if (!wrap) return;
    if (wrap.getAttribute('data-sdr-bound') === '1') {
      syncDateChipState(root);
      return;
    }
    if (
      !global.SalesDateRangePicker ||
      typeof global.SalesDateRangePicker.init !== 'function'
    ) {
      if (!root.getAttribute('data-ch-fb-date-retry')) {
        root.setAttribute('data-ch-fb-date-retry', '1');
        window.setTimeout(function () {
          root.removeAttribute('data-ch-fb-date-retry');
          bindDateRange(root);
        }, 0);
      }
      return;
    }

    if (!wrap.getAttribute('data-max-date')) {
      var today = new Date();
      var yyyy = today.getFullYear();
      var mm = String(today.getMonth() + 1).padStart(2, '0');
      var dd = String(today.getDate()).padStart(2, '0');
      wrap.setAttribute('data-max-date', yyyy + '-' + mm + '-' + dd);
    }

    global.SalesDateRangePicker.init({
      wrapId: 'ch-fb-date-range-wrap',
      triggerId: 'ch-fb-date-range-trigger',
      backdropId: 'ch-fb-date-range-backdrop',
      panelId: 'ch-fb-date-range-panel',
      displayId: 'ch-fb-date-range-display',
      fromInputId: 'ch-fb-date-from',
      toInputId: 'ch-fb-date-to',
      applyId: 'ch-fb-date-range-apply',
      prevId: 'ch-fb-cal-prev',
      nextId: 'ch-fb-cal-next',
      title0Id: 'ch-fb-cal-title0',
      title1Id: 'ch-fb-cal-title1',
      grid0Id: 'ch-fb-cal-grid0',
      grid1Id: 'ch-fb-cal-grid1',
      emptyLabel: 'Select date…',
      onApply: function () {
        syncDateChipState(root);
        loadAll(root);
      }
    });

    var clearBtn = $('#ch-fb-date-range-clear', root);
    if (clearBtn && clearBtn.getAttribute('data-ch-fb-clear-bound') !== '1') {
      clearBtn.setAttribute('data-ch-fb-clear-bound', '1');
      clearBtn.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        var fromEl = $('#ch-fb-date-from', root);
        var toEl = $('#ch-fb-date-to', root);
        var display = $('#ch-fb-date-range-display', root);
        var chip = root.querySelector('.ch-fb-date-chip');
        if (fromEl) fromEl.value = '';
        if (toEl) toEl.value = '';
        feedbackDateFrom = '';
        feedbackDateTo = '';
        if (display) display.textContent = 'Select date…';
        if (chip) chip.classList.remove('is-filtered');
        if (wrap) wrap.classList.remove('open');
        var panel = $('#ch-fb-date-range-panel', root);
        var trigger = $('#ch-fb-date-range-trigger', root);
        if (panel) {
          panel.setAttribute('hidden', 'hidden');
          if (
            global.SalesDateRangePicker &&
            typeof global.SalesDateRangePicker.clearPanelPosition === 'function'
          ) {
            global.SalesDateRangePicker.clearPanelPosition(panel);
          }
        }
        if (trigger) trigger.setAttribute('aria-expanded', 'false');
        loadAll(root);
      });
    }
    syncDateChipState(root);
  }

  function bindSearch(page) {
    var root = page || pageRoot();
    if (!root) return;
    var input = $('#ch-fb-search', root);
    if (!input || input.getAttribute('data-ch-fb-search-bound') === '1') return;
    input.setAttribute('data-ch-fb-search-bound', '1');

    function applySearch() {
      feedbackSearchQuery = String(input.value || '');
      renderRows(root);
    }

    input.addEventListener('input', applySearch);
    input.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') {
        input.value = '';
        applySearch();
        input.blur();
      }
      if (e.key === 'Enter') e.preventDefault();
    });
    feedbackSearchQuery = String(input.value || '');
  }

  function initFeedbackPage() {
    var page = pageRoot();
    if (!page) return;
    var already = page.getAttribute('data-ch-fb-bound') === '1';
    if (!already) {
      page.setAttribute('data-ch-fb-bound', '1');
      bindInvite(page);
      bindTableSort(page);
      bindSearch(page);
    }
    bindDateRange(page);
    currentOutletFilter(page);
    loadAll(page);
    startAutoRefresh();
  }

  global._chFbSetOutletFilter = function (value) {
    var page = pageRoot();
    if (!page) return;
    setOutletFilter(value, page);
    loadAll(page);
  };
  global._chFbLoadAll = function () {
    var page = pageRoot();
    if (page) loadAll(page);
  };

  var AUTO_REFRESH_MS = 30000;

  function stopAutoRefresh() {
    if (global._chFbAutoRefreshTimer) {
      clearInterval(global._chFbAutoRefreshTimer);
      global._chFbAutoRefreshTimer = null;
    }
  }

  function startAutoRefresh() {
    stopAutoRefresh();
    global._chFbAutoRefreshTimer = setInterval(function () {
      var page = pageRoot();
      if (!page) {
        stopAutoRefresh();
        return;
      }
      if (document.hidden) return;
      loadAll(page);
    }, AUTO_REFRESH_MS);
  }

  if (!global._chFbAutoRefreshVisBound) {
    global._chFbAutoRefreshVisBound = true;
    document.addEventListener('visibilitychange', function () {
      if (document.hidden) return;
      var page = pageRoot();
      if (!page) return;
      loadAll(page);
    });
  }

  global.initFeedbackPage = initFeedbackPage;
  global.initCommunicationHubFeedbackPage = initFeedbackPage;
  global._chFbStarsPlain = starsPlain;

  if (!global._chFbTypeFilterDelegateBound) {
    global._chFbTypeFilterDelegateBound = true;
    document.addEventListener('click', function (ev) {
      var btn =
        ev.target && ev.target.closest
          ? ev.target.closest('#ch-fb-type-filter-tabs [data-fb-filter]')
          : null;
      if (!btn) return;
      var page = pageRoot();
      if (!page || !page.contains(btn)) return;
      var value = btn.getAttribute('data-fb-filter');
      if (typeof global._chFbSetOutletFilter === 'function') {
        global._chFbSetOutletFilter(value);
      } else {
        setOutletFilter(value, page);
        loadAll(page);
      }
    });
  }

  if (!global._chFbLinkModalDelegateBound) {
    global._chFbLinkModalDelegateBound = true;
    document.addEventListener('click', function (ev) {
      var t = ev.target && ev.target.closest ? ev.target.closest('#ch-fb-create-link') : null;
      if (t) {
        if (typeof global._chFbOpenLinkModal === 'function') global._chFbOpenLinkModal();
        return;
      }
      var live = document.getElementById('ch-fb-link-modal');
      if (!live || !live.classList.contains('open')) return;
      if (ev.target === live) {
        if (typeof global._chFbCloseLinkModal === 'function') global._chFbCloseLinkModal();
        return;
      }
      var outletBtn =
        ev.target && ev.target.closest
          ? ev.target.closest('[data-fb-outlet]')
          : null;
      if (outletBtn && live.contains(outletBtn)) {
        if (typeof global._chFbSelectOutlet === 'function') {
          global._chFbSelectOutlet(outletBtn.getAttribute('data-fb-outlet'));
        }
        return;
      }
      var choiceWa =
        ev.target && ev.target.closest
          ? ev.target.closest('#ch-fb-choice-whatsapp')
          : null;
      if (choiceWa && typeof global._chFbSetLinkStep === 'function') {
        global._chFbSetLinkStep('wa-phone');
        var phoneEl = document.getElementById('ch-fb-modal-wa-phone');
        if (phoneEl) {
          try {
            phoneEl.focus();
          } catch (eW) {}
        }
        return;
      }
      var choiceCreate =
        ev.target && ev.target.closest
          ? ev.target.closest('#ch-fb-choice-create')
          : null;
      if (choiceCreate && typeof global._chFbSetLinkStep === 'function') {
        global._chFbSetLinkStep('create');
        return;
      }
      var backBtn =
        ev.target && ev.target.closest
          ? ev.target.closest('[data-fb-back]')
          : null;
      if (backBtn && live.contains(backBtn) && typeof global._chFbSetLinkStep === 'function') {
        var target = backBtn.getAttribute('data-fb-back');
        if (target && target !== 'true' && target !== '') global._chFbSetLinkStep(target);
        else global._chFbSetLinkStep('choose');
        return;
      }
      var sendBtn =
        ev.target && ev.target.closest
          ? ev.target.closest('#ch-fb-modal-wa-send')
          : null;
      if (sendBtn && typeof global._chFbSendWhatsApp === 'function') {
        global._chFbSendWhatsApp();
        return;
      }
      var createSubmit =
        ev.target && ev.target.closest
          ? ev.target.closest('#ch-fb-modal-create-submit')
          : null;
      if (createSubmit && typeof global._chFbSubmitCreateLink === 'function') {
        global._chFbSubmitCreateLink();
      }
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initFeedbackPage);
  } else {
    initFeedbackPage();
  }
})(typeof window !== 'undefined' ? window : this);
