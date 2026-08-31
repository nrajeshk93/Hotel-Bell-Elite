(function (global) {
  'use strict';

  var rdInitAbort = null;
  var CATEGORY_STORAGE_KEY = 'rd-active-category';
  var HUB_SCROLL_KEY = 'rd-hub-scroll-v1';

  function readStoredCategory(validKeys) {
    try {
      var stored = String(global.sessionStorage.getItem(CATEGORY_STORAGE_KEY) || '').trim();
      if (stored && validKeys.indexOf(stored) !== -1) return stored;
    } catch (err) {
      /* ignore */
    }
    return 'all';
  }

  function writeStoredCategory(category) {
    try {
      global.sessionStorage.setItem(CATEGORY_STORAGE_KEY, category || 'all');
    } catch (err) {
      /* ignore */
    }
  }

  function mainScroller() {
    return (
      document.querySelector('.de-main-wrapper') ||
      document.querySelector('.de-main-scroll') ||
      document.scrollingElement ||
      document.documentElement
    );
  }

  function captureReportsHubScroll(card) {
    var main = mainScroller();
    var section = card && card.closest ? card.closest('.rd-category-section') : null;
    var payload = {
      top: main ? Number(main.scrollTop) || 0 : 0,
      section: section ? String(section.getAttribute('data-rd-section') || '') : '',
      reportId: card ? String(card.getAttribute('data-report-id') || '') : '',
      ts: Date.now()
    };
    try {
      global.sessionStorage.setItem(HUB_SCROLL_KEY, JSON.stringify(payload));
    } catch (err) {
      /* ignore */
    }
  }

  function restoreReportsHubScroll() {
    if (!document.getElementById('rd-report-sections')) return false;
    var raw = '';
    try {
      raw = global.sessionStorage.getItem(HUB_SCROLL_KEY) || '';
    } catch (err) {
      return false;
    }
    if (!raw) return false;
    var payload;
    try {
      payload = JSON.parse(raw);
    } catch (err) {
      return false;
    }
    if (!payload || typeof payload !== 'object') return false;

    function apply() {
      var main = mainScroller();
      if (!main) return;
      var sectionKey = String(payload.section || '').trim();
      var section = sectionKey
        ? document.querySelector(
            '.rd-category-section[data-rd-section="' + sectionKey + '"]'
          )
        : null;
      if (
        section &&
        !section.hidden &&
        !section.classList.contains('is-hidden')
      ) {
        var mainRect = main.getBoundingClientRect();
        var secRect = section.getBoundingClientRect();
        main.scrollTop = Math.max(
          0,
          (Number(main.scrollTop) || 0) + (secRect.top - mainRect.top) - 16
        );
        return;
      }
      if (typeof payload.top === 'number' && isFinite(payload.top)) {
        main.scrollTop = Math.max(0, payload.top);
      }
    }

    requestAnimationFrame(function () {
      requestAnimationFrame(apply);
    });
    return true;
  }

  function bindReportCardScrollCapture(signal) {
    document.addEventListener(
      'click',
      function (e) {
        var card = e.target.closest('a.rd-report-card');
        if (!card) return;
        if (!document.getElementById('rd-report-sections')) return;
        captureReportsHubScroll(card);
        // Keep the hub category filter the user was on (do not switch to the
        // report's own category — that made Back land on Restaurant, etc.).
        var activePill = document.querySelector(
          '#rd-category-pills .md-category-pill.is-active'
        );
        var category = activePill
          ? String(activePill.getAttribute('data-rd-category') || '').trim()
          : '';
        if (category) writeStoredCategory(category);
      },
      { capture: true, signal: signal }
    );
  }

  function initReportsDashboard() {
    if (rdInitAbort) rdInitAbort.abort();
    rdInitAbort = new AbortController();
    var signal = rdInitAbort.signal;

    var searchInput = document.getElementById('rd-search-input');
    var filterBtn = document.getElementById('rd-search-filter');
    var pillsHost = document.getElementById('rd-category-pills');
    var sectionsHost = document.getElementById('rd-report-sections');
    var emptyState = document.getElementById('rd-empty-state');
    if (!sectionsHost) return;

    var sections = Array.prototype.slice.call(
      sectionsHost.querySelectorAll('.rd-category-section')
    );
    var validCategories = ['all'];
    if (pillsHost) {
      pillsHost.querySelectorAll('.md-category-pill[data-rd-category]').forEach(function (pill) {
        var key = pill.getAttribute('data-rd-category') || '';
        if (key && validCategories.indexOf(key) === -1) validCategories.push(key);
      });
    }
    var activeCategory = readStoredCategory(validCategories);
    var searchTerm = '';

    function setActivePill(category) {
      if (!pillsHost) return;
      pillsHost.querySelectorAll('.md-category-pill').forEach(function (pill) {
        var isActive = pill.getAttribute('data-rd-category') === category;
        pill.classList.toggle('is-active', isActive);
        pill.setAttribute('aria-selected', isActive ? 'true' : 'false');
      });
    }

    function cardMatches(card) {
      var name = card.getAttribute('data-report-name') || '';
      var category = card.getAttribute('data-report-category') || '';
      var matchesSearch = !searchTerm || window.hbeBestSearchScore([name], searchTerm) >= 0;
      var matchesCategory = activeCategory === 'all' || category === activeCategory;
      return matchesSearch && matchesCategory;
    }

    function applyFilters() {
      var visibleTotal = 0;

      sections.forEach(function (section) {
        var sectionKey = section.getAttribute('data-rd-section') || '';
        var sectionCards = Array.prototype.slice.call(
          section.querySelectorAll('.rd-report-card')
        );
        var visibleInSection = 0;

        var ranked = sectionCards.map(function (card) {
          var score = searchTerm ? window.hbeBestSearchScore([card.getAttribute('data-report-name') || ''], searchTerm) : 0;
          return { card: card, score: score, show: cardMatches(card) };
        });
        if (searchTerm) ranked.sort(function (a, b) { return b.score - a.score; });
        ranked.forEach(function (entry) {
          entry.card.classList.toggle('is-hidden', !entry.show);
          if (entry.show) {
            visibleInSection += 1;
            if (searchTerm && entry.card.parentNode) entry.card.parentNode.appendChild(entry.card);
          }
        });

        var showSection =
          visibleInSection > 0 &&
          (activeCategory === 'all' || activeCategory === sectionKey);
        section.classList.toggle('is-hidden', !showSection);
        section.hidden = !showSection;

        var countEl = section.querySelector('[data-rd-section-count]');
        if (countEl) {
          countEl.textContent =
            visibleInSection + ' report' + (visibleInSection === 1 ? '' : 's');
        }

        visibleTotal += showSection ? visibleInSection : 0;
      });

      if (emptyState) emptyState.hidden = visibleTotal > 0;
    }

    if (searchInput) {
      searchInput.addEventListener('input', function () {
        searchTerm = String(searchInput.value || '').trim();
        applyFilters();
      }, { signal: signal });
    }

    if (filterBtn) {
      filterBtn.addEventListener('click', function () {
        activeCategory = 'all';
        searchTerm = '';
        if (searchInput) searchInput.value = '';
        writeStoredCategory(activeCategory);
        setActivePill('all');
        applyFilters();
      }, { signal: signal });
    }

    if (pillsHost) {
      pillsHost.addEventListener('click', function (e) {
        var pill = e.target.closest('.md-category-pill');
        if (!pill || !pillsHost.contains(pill)) return;
        activeCategory = pill.getAttribute('data-rd-category') || 'all';
        writeStoredCategory(activeCategory);
        setActivePill(activeCategory);
        applyFilters();
      }, { signal: signal });
    }

    bindReportCardScrollCapture(signal);
    setActivePill(activeCategory);
    applyFilters();
    restoreReportsHubScroll();
  }

  global.initReportsDashboard = initReportsDashboard;
  global.deRestoreReportsHubScroll = restoreReportsHubScroll;
  global.deCaptureReportsHubScroll = captureReportsHubScroll;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initReportsDashboard);
  } else {
    initReportsDashboard();
  }
})(window);
