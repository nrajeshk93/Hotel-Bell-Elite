(function (global) {
  'use strict';

  var toastTimer = null;
  var mdInitAbort = null;
  var masterLoadAbort = null;

  var MASTER_FALLBACK_URLS = {
    supplier: '/suppliers',
    customer: '/customers',
    product: '/stores/product-master',
    employee: '/employees'
  };

  function showToast(message) {
    var toast = document.getElementById('md-toast');
    if (!toast) return;
    toast.textContent = message;
    toast.hidden = false;
    toast.classList.add('is-visible');
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(function () {
      toast.classList.remove('is-visible');
      toast.hidden = true;
    }, 3200);
  }

  function openCreateModal(modal) {
    if (!modal) return;
    modal.classList.add('open');
    modal.setAttribute('aria-hidden', 'false');
    var nameInput = document.getElementById('md-create-name');
    if (nameInput) {
      nameInput.value = '';
      nameInput.focus();
    }
  }

  function closeCreateModal(modal) {
    if (!modal) return;
    modal.classList.remove('open');
    modal.setAttribute('aria-hidden', 'true');
  }

  function setBodyScrollLocked(locked) {
    document.body.classList.toggle('md-master-modal-open', !!locked);
  }

  function showPanel(el, show) {
    if (!el) return;
    el.hidden = !show;
    el.classList.toggle('is-md-panel-visible', !!show);
  }

  function getMasterCardUrl(card) {
    if (!card) return '';
    var url = String(
      card.getAttribute('data-master-href') ||
      (card.dataset && card.dataset.masterHref) ||
      ''
    ).trim();
    if (!url || url === '#') {
      var masterId = String(card.getAttribute('data-master-id') || '').trim();
      if (masterId && MASTER_FALLBACK_URLS[masterId]) {
        url = MASTER_FALLBACK_URLS[masterId];
      }
    }
    return url;
  }

  function isMasterCardStub(card) {
    if (!card) return true;
    if (card.getAttribute('data-md-stub') === '1') return true;
    var url = getMasterCardUrl(card);
    return !url || url === '#';
  }

  function abortMasterLoad() {
    if (masterLoadAbort) {
      masterLoadAbort.abort();
      masterLoadAbort = null;
    }
  }

  function getInjectHost() {
    return document.getElementById('md-master-modal-inject');
  }

  function clearInjectHost() {
    var inject = getInjectHost();
    if (!inject) return;
    inject.innerHTML = '';
    showPanel(inject, false);
  }

  function buildEmbedUrl(url) {
    try {
      var parsed = new URL(url, window.location.origin);
      if (parsed.origin !== window.location.origin) return url;
      parsed.searchParams.set('embed', '1');
      return parsed.pathname + parsed.search + parsed.hash;
    } catch (err) {
      if (String(url).indexOf('embed=1') !== -1) return url;
      return url + (String(url).indexOf('?') === -1 ? '?' : '&') + 'embed=1';
    }
  }

  function executeEmbedScripts(container) {
    if (!container) return;
    container.querySelectorAll('script').forEach(function (oldScript) {
      var script = document.createElement('script');
      Array.prototype.slice.call(oldScript.attributes).forEach(function (attr) {
        script.setAttribute(attr.name, attr.value);
      });
      script.textContent = oldScript.textContent;
      oldScript.parentNode.replaceChild(script, oldScript);
    });
  }

  function shouldLeaveModal(link) {
    if (!link) return true;
    if (link.hasAttribute('download')) return true;
    if (link.target && link.target !== '_self') return true;
    if (link.hasAttribute('data-md-full-nav')) return true;
    if (link.closest('[data-md-full-nav]')) return true;
    return false;
  }

  function bindInjectNavigation(inject, getReloadFn) {
    if (!inject || inject.__mdEmbedNavBound) return;
    inject.__mdEmbedNavBound = true;

    inject.addEventListener('click', function (e) {
      var reloadFn = getReloadFn();
      if (!reloadFn) return;
      var link = e.target.closest('a[href]');
      if (!link || shouldLeaveModal(link)) return;
      var href = link.getAttribute('href');
      if (!href || href.charAt(0) === '#') return;
      e.preventDefault();
      reloadFn(href);
    });

    inject.addEventListener('submit', function (e) {
      var reloadFn = getReloadFn();
      if (!reloadFn) return;
      var form = e.target;
      if (!form || form.tagName !== 'FORM') return;
      if (form.hasAttribute('data-md-full-nav') || form.closest('[data-md-full-nav]')) return;
      var method = String(form.getAttribute('method') || 'get').toLowerCase();
      if (method !== 'get') return;
      e.preventDefault();
      try {
        var action = form.getAttribute('action') || window.location.pathname;
        var url = new URL(action, window.location.origin);
        new FormData(form).forEach(function (value, key) {
          if (value != null && String(value) !== '') url.searchParams.set(key, value);
        });
        reloadFn(url.pathname + url.search);
      } catch (err) {
        /* allow native submit on parse failure */
      }
    });
  }

  var reloadMasterEmbed = null;

  function loadMasterEmbed(url, loading, empty) {
    abortMasterLoad();
    masterLoadAbort = new AbortController();
    var signal = masterLoadAbort.signal;
    var fetchUrl = buildEmbedUrl(url);

    return fetch(fetchUrl, {
      credentials: 'same-origin',
      headers: { Accept: 'text/html' },
      signal: signal
    }).then(function (response) {
      if (!response.ok) throw new Error('fetch failed');
      return response.text();
    }).then(function (html) {
      var inject = getInjectHost();
      if (!inject) throw new Error('missing inject host');

      var doc = new DOMParser().parseFromString(html, 'text/html');
      var fragment = doc.querySelector('.md-master-embed') ||
        doc.querySelector('.main-wrapper') ||
        doc.body;

      inject.innerHTML = fragment === doc.body ? fragment.innerHTML : fragment.outerHTML;
      executeEmbedScripts(inject);
      // Re-bind EP listboxes after HTML inject (DOMContentLoaded already ran).
      if (typeof global.initEpListboxes === 'function') {
        global.initEpListboxes();
      }

      var titleEl = document.getElementById('md-master-modal-title');
      var embedRoot = inject.querySelector('[data-md-modal-title]');
      if (titleEl && embedRoot) {
        var nextTitle = String(embedRoot.getAttribute('data-md-modal-title') || '').trim();
        if (nextTitle) titleEl.textContent = nextTitle;
      }

      showPanel(loading, false);
      showPanel(empty, false);
      showPanel(inject, true);
    });
  }

  function openMasterModal(name, url) {
    var modal = document.getElementById('md-master-modal');
    var titleEl = document.getElementById('md-master-modal-title');
    var loading = document.getElementById('md-master-modal-loading');
    var empty = document.getElementById('md-master-modal-empty');
    var inject = getInjectHost();
    if (!modal) return;

    abortMasterLoad();
    clearInjectHost();

    if (titleEl) titleEl.textContent = name || 'Master';

    modal.classList.add('open');
    modal.setAttribute('aria-hidden', 'false');
    setBodyScrollLocked(true);

    if (!url) {
      showPanel(loading, false);
      showPanel(inject, false);
      showPanel(empty, true);
      return;
    }

    showPanel(empty, false);
    showPanel(inject, false);
    showPanel(loading, true);

    loadMasterEmbed(url, loading, empty).catch(function () {
      if (masterLoadAbort && masterLoadAbort.signal.aborted) return;
      showPanel(loading, false);
      showPanel(inject, false);
      showPanel(empty, true);
    });
  }

  function closeMasterModal() {
    abortMasterLoad();
    clearInjectHost();

    var modal = document.getElementById('md-master-modal');
    var loading = document.getElementById('md-master-modal-loading');
    var empty = document.getElementById('md-master-modal-empty');
    if (!modal) return;

    modal.classList.remove('open');
    modal.setAttribute('aria-hidden', 'true');
    setBodyScrollLocked(false);

    showPanel(loading, false);
    showPanel(empty, false);
  }

  function bindCreateModal(modal, openers, closerSelectors, signal) {
    if (!modal) return;

    openers.forEach(function (opener) {
      if (!opener) return;
      opener.addEventListener('click', function () {
        openCreateModal(modal);
      }, { signal: signal });
    });

    modal.addEventListener('click', function (e) {
      if (e.target === modal) closeCreateModal(modal);
    }, { signal: signal });

    closerSelectors.forEach(function (sel) {
      var btn = modal.querySelector(sel) || document.querySelector(sel);
      if (btn) {
        btn.addEventListener('click', function () {
          closeCreateModal(modal);
        }, { signal: signal });
      }
    });
  }

  function bindMasterModal(signal) {
    var modal = document.getElementById('md-master-modal');
    if (!modal) return;

    var loading = document.getElementById('md-master-modal-loading');
    var empty = document.getElementById('md-master-modal-empty');
    var inject = getInjectHost();
    if (inject) inject.__mdEmbedNavBound = false;

    reloadMasterEmbed = function (nextUrl) {
      showPanel(empty, false);
      showPanel(inject, false);
      showPanel(loading, true);
      loadMasterEmbed(nextUrl, loading, empty).catch(function () {
        showPanel(loading, false);
        showPanel(inject, false);
        showPanel(empty, true);
      });
    };

    bindInjectNavigation(inject, function () { return reloadMasterEmbed; });

    modal.addEventListener('click', function (e) {
      if (e.target === modal) closeMasterModal();
    }, { signal: signal });

    var closeBtn = document.getElementById('md-master-modal-close');
    if (closeBtn) {
      closeBtn.addEventListener('click', function () {
        closeMasterModal();
      }, { signal: signal });
    }

    document.addEventListener('click', function (e) {
      var link = e.target.closest('.de-sidebar a[href], .sidebar a[href]');
      if (!link) return;
      closeMasterModal();
    }, { signal: signal, capture: true });
  }

  function onDocumentKeydown(e, createModal) {
    if (e.key !== 'Escape') return;
    var masterModal = document.getElementById('md-master-modal');
    if (masterModal && masterModal.classList.contains('open')) {
      e.preventDefault();
      closeMasterModal();
      return;
    }
    if (createModal && createModal.classList.contains('open')) {
      closeCreateModal(createModal);
    }
  }

  function initMastersDashboard() {
    if (mdInitAbort) mdInitAbort.abort();
    mdInitAbort = new AbortController();
    var signal = mdInitAbort.signal;

    closeMasterModal();

    var searchInput = document.getElementById('md-search-input');
    var filterBtn = document.getElementById('md-search-filter');
    var pillsHost = document.getElementById('md-category-pills');
    var grid = document.getElementById('md-master-grid');
    var emptyState = document.getElementById('md-empty-state');
    var createModal = document.getElementById('md-create-modal');
    var createSubmit = document.getElementById('md-create-submit');

    if (!grid) return;

    var cards = Array.prototype.slice.call(grid.querySelectorAll('.md-master-card:not(.md-master-card--add)'));
    var activeCategory = 'all';
    var searchTerm = '';

    function setActivePill(category) {
      if (!pillsHost) return;
      pillsHost.querySelectorAll('.md-category-pill').forEach(function (pill) {
        var isActive = pill.getAttribute('data-md-category') === category;
        pill.classList.toggle('is-active', isActive);
        pill.setAttribute('aria-selected', isActive ? 'true' : 'false');
      });
    }

    function cardMatches(card) {
      var name = (card.getAttribute('data-master-name') || '').toLowerCase();
      var category = card.getAttribute('data-master-category') || '';
      var matchesSearch = !searchTerm || name.indexOf(searchTerm) !== -1;
      var matchesCategory = activeCategory === 'all' || category === activeCategory;
      return matchesSearch && matchesCategory;
    }

    function applyFilters() {
      var visible = 0;
      cards.forEach(function (card) {
        var show = cardMatches(card);
        card.classList.toggle('is-hidden', !show);
        if (show) visible += 1;
      });

      var addCard = document.getElementById('md-add-card');
      if (addCard) {
        var showAdd = !searchTerm && (activeCategory === 'all' || activeCategory === 'others');
        addCard.classList.toggle('is-hidden', !showAdd);
      }

      if (emptyState) {
        emptyState.hidden = visible > 0;
      }
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
        setActivePill('all');
        applyFilters();
      }, { signal: signal });
    }

    if (pillsHost) {
      pillsHost.addEventListener('click', function (e) {
        var pill = e.target.closest('.md-category-pill');
        if (!pill) return;
        activeCategory = pill.getAttribute('data-md-category') || 'all';
        setActivePill(activeCategory);
        applyFilters();
      }, { signal: signal });
    }

    grid.addEventListener('click', function (e) {
      var card = e.target.closest('.md-master-card:not(.md-master-card--add)');
      if (!card) return;
      e.preventDefault();
      e.stopImmediatePropagation();
      var name = card.getAttribute('data-master-name') || 'Master';
      var url = getMasterCardUrl(card);
      openMasterModal(name, isMasterCardStub(card) ? null : url);
    }, { signal: signal, capture: true });

    bindCreateModal(
      createModal,
      [
        document.getElementById('md-new-master-btn'),
        document.getElementById('md-add-card')
      ],
      ['#md-create-cancel'],
      signal
    );

    bindMasterModal(signal);

    document.addEventListener('keydown', function (e) {
      onDocumentKeydown(e, createModal);
    }, { signal: signal });

    if (createSubmit) {
      createSubmit.addEventListener('click', function () {
        closeCreateModal(createModal);
        showToast('Master creation will be available soon.');
      }, { signal: signal });
    }

    applyFilters();
  }

  global.initMastersDashboard = initMastersDashboard;
  global.closeMasterModal = closeMasterModal;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initMastersDashboard);
  } else {
    initMastersDashboard();
  }
})(window);
