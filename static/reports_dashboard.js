(function (global) {
  'use strict';

  var rdInitAbort = null;
  var CATEGORY_STORAGE_KEY = 'rd-active-category';

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
      var name = (card.getAttribute('data-report-name') || '').toLowerCase();
      var category = card.getAttribute('data-report-category') || '';
      var matchesSearch = !searchTerm || name.indexOf(searchTerm) !== -1;
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

        sectionCards.forEach(function (card) {
          var show = cardMatches(card);
          card.classList.toggle('is-hidden', !show);
          if (show) visibleInSection += 1;
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
        searchTerm = String(searchInput.value || '').trim().toLowerCase();
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

    setActivePill(activeCategory);
    applyFilters();
  }

  global.initReportsDashboard = initReportsDashboard;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initReportsDashboard);
  } else {
    initReportsDashboard();
  }
})(window);
