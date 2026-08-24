(function (global) {
  'use strict';

  var toastTimer = null;
  var mdInitAbort = null;
  var masterLoadAbort = null;

  var MASTER_FALLBACK_URLS = {
    supplier: '/suppliers',
    customer: '/customers',
    agency: '/agencies',
    product: '/stores/product-master',
    menu: '/point-of-sale/menu',
    category: '/masters/categories',
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

  function isMasterHubPath(pathname) {
    var path = String(pathname || '').replace(/\/+$/, '') || '/';
    return path === '/master';
  }

  function getMasterOpenIdFromUrl() {
    try {
      if (!isMasterHubPath(window.location.pathname)) return '';
      return String(new URL(window.location.href).searchParams.get('open') || '').trim();
    } catch (err) {
      return '';
    }
  }

  function syncMasterOpenUrl(masterId) {
    try {
      if (!isMasterHubPath(window.location.pathname)) return;
      var parsed = new URL(window.location.href);
      var nextId = String(masterId || '').trim();
      if (nextId) parsed.searchParams.set('open', nextId);
      else parsed.searchParams.delete('open');
      var next = parsed.pathname + parsed.search + parsed.hash;
      var current = window.location.pathname + window.location.search + window.location.hash;
      if (next !== current) {
        history.replaceState(history.state, '', next);
      }
    } catch (err) {
      /* ignore */
    }
  }

  function findMasterCardById(masterId) {
    var id = String(masterId || '').trim();
    if (!id) return null;
    var cards = document.querySelectorAll('.md-master-card[data-master-id]');
    for (var i = 0; i < cards.length; i += 1) {
      if (String(cards[i].getAttribute('data-master-id') || '').trim() === id) {
        return cards[i];
      }
    }
    return null;
  }

  function restoreMasterOpenFromUrl() {
    var openId = getMasterOpenIdFromUrl();
    if (!openId) return;
    var card = findMasterCardById(openId);
    if (!card || isMasterCardStub(card)) return;
    openMasterModal(
      card.getAttribute('data-master-name') || 'Master',
      getMasterCardUrl(card),
      openId
    );
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

  /** Load page <script src> tags that sit outside the embed fragment (e.g. pos_menu.js). */
  function loadMissingPageScripts(doc) {
    if (!doc) return Promise.resolve();
    var needed = Array.prototype.slice.call(doc.querySelectorAll('script[src]')).filter(function (node) {
      var src = node.getAttribute('src') || '';
      if (!/\/pos_menu\.js(\?|$)/.test(src)) return false;
      if (typeof global.initPosMenuPage === 'function') return false;
      if (document.querySelector('script[src="' + src.replace(/"/g, '\\"') + '"]')) return false;
      /* Match by path without relying on exact query string. */
      var path = src.split('?')[0];
      var existing = Array.prototype.slice.call(document.scripts).some(function (s) {
        return s.src && s.src.indexOf(path) !== -1;
      });
      return !existing;
    });
    if (!needed.length) {
      if (typeof global.initPosMenuPage === 'function') return Promise.resolve();
      /* Script tag already present but init missing — wait briefly or force reload. */
      var stuck = Array.prototype.slice.call(document.scripts).find(function (s) {
        return s.src && /\/pos_menu\.js(\?|$)/.test(s.src);
      });
      if (stuck) return Promise.resolve();
      needed = Array.prototype.slice.call(doc.querySelectorAll('script[src]')).filter(function (node) {
        return /\/pos_menu\.js(\?|$)/.test(node.getAttribute('src') || '');
      });
    }
    if (!needed.length) return Promise.resolve();
    return Promise.all(
      needed.map(function (node) {
        return new Promise(function (resolve) {
          var src = node.getAttribute('src');
          var el = document.createElement('script');
          el.src = src;
          el.onload = function () {
            resolve();
          };
          el.onerror = function () {
            if (typeof console !== 'undefined' && console.error) {
              console.error('Failed to load', src);
            }
            resolve();
          };
          document.body.appendChild(el);
        });
      })
    );
  }

  function ensureEmbedClose() {
    /* Only Menu Master lacks a back chevron; page-shell masters close via ←. */
    stripPageShellEmbedCloseButtons();
    var tools = document.querySelector('#md-master-modal #pos-menu-page .pos-menu-header-actions');
    if (!tools || tools.querySelector('[data-md-menu-close]')) return;
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'md-master-modal-close pos-menu-embed-close';
    btn.setAttribute('data-md-menu-close', '1');
    btn.setAttribute('aria-label', 'Close master');
    btn.innerHTML =
      '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>';
    btn.addEventListener('click', function (e) {
      e.preventDefault();
      closeMasterModal();
    });
    tools.appendChild(btn);
  }

  function stripPageShellEmbedCloseButtons() {
    document
      .querySelectorAll(
        '#md-master-modal .md-master-embed--page-shell .md-master-embed-header-actions [data-md-menu-close]'
      )
      .forEach(function (btn) {
        if (btn && btn.parentNode) btn.parentNode.removeChild(btn);
      });
  }

  function remountEmbedFullscreen() {
    try {
      if (global.deFullscreen && typeof global.deFullscreen.reinit === 'function') {
        global.deFullscreen.reinit();
      }
    } catch (err) {
      if (typeof global.console !== 'undefined' && global.console.error) {
        global.console.error('Master embed fullscreen remount failed', err);
      }
    }
  }

  function bootPosMenuAfterEmbed() {
    ensureEmbedClose();
    remountEmbedFullscreen();
    if (typeof global.initPosMenuPage === 'function') {
      try {
        global.initPosMenuPage();
      } catch (err) {
        if (typeof console !== 'undefined' && console.error) {
          console.error('Menu Master init failed', err);
        }
      }
      return;
    }
    if (typeof console !== 'undefined' && console.warn) {
      console.warn('initPosMenuPage missing after script load');
    }
  }

  function shouldLeaveModal(link) {
    if (!link) return true;
    if (link.hasAttribute('download')) return true;
    if (link.target && link.target !== '_self') return true;
    if (link.hasAttribute('data-md-full-nav')) return true;
    if (link.closest('[data-md-full-nav]')) return true;
    return false;
  }

  function preserveFullscreenForEmbedNav() {
    if (!global.deFullscreen) return;
    if (typeof global.deFullscreen.armForSoftNav === 'function') {
      global.deFullscreen.armForSoftNav();
    }
    if (typeof global.deFullscreen.preserveForNavigation === 'function') {
      global.deFullscreen.preserveForNavigation();
    }
  }

  function prepareEmbedForms(inject) {
    if (!inject) return;
    /* Keep supplier/category POSTs inside the Masters modal (hard nav exits fullscreen). */
    inject.querySelectorAll('form[data-md-full-nav]').forEach(function (form) {
      form.removeAttribute('data-md-full-nav');
      form.setAttribute('data-md-embed-form', '1');
    });
  }

  function paintMasterEmbedHtml(html, loading, empty) {
    var inject = getInjectHost();
    if (!inject) throw new Error('missing inject host');

    var doc = new DOMParser().parseFromString(html, 'text/html');
    var fragment = doc.querySelector('.md-master-embed') ||
      doc.querySelector('.main-wrapper') ||
      doc.body;

    inject.innerHTML = fragment === doc.body ? fragment.innerHTML : fragment.outerHTML;
    prepareEmbedForms(inject);

    var titleEl = document.getElementById('md-master-modal-title');
    var embedRoot = inject.querySelector('[data-md-modal-title]');
    if (titleEl && embedRoot) {
      var nextTitle = String(embedRoot.getAttribute('data-md-modal-title') || '').trim();
      if (nextTitle) titleEl.textContent = nextTitle;
    }

    /* Show content immediately so Product Master feels as snappy as other masters. */
    showPanel(loading, false);
    showPanel(empty, false);
    showPanel(inject, true);

    executeEmbedScripts(inject);

    var afterPaint = function () {
      try {
        if (typeof global.initEpListboxes === 'function') {
          global.initEpListboxes();
        }
      } catch (err) {
        if (typeof global.console !== 'undefined' && global.console.error) {
          global.console.error('Masters listbox init failed', err);
        }
      }
      if (inject.querySelector('#pos-menu-page')) {
        loadMissingPageScripts(doc).then(function () {
          setTimeout(bootPosMenuAfterEmbed, 0);
        }).catch(function () {
          setTimeout(bootPosMenuAfterEmbed, 0);
        });
        return;
      }
      if (!inject.querySelector('.md-master-embed--page-shell')) return;
      ensureEmbedClose();
      remountEmbedFullscreen();
      try {
        if (typeof global.initHbeTableScroll === 'function') {
          global.initHbeTableScroll();
        }
        if (inject.querySelector('#st-product-modal') && typeof global.initStoresPage === 'function') {
          global.initStoresPage();
        }
        if (inject.querySelector('#sm-supplier-list-panel, #sm-supplier-form') && typeof global.initSupplierMasterPage === 'function') {
          global.initSupplierMasterPage();
        }
        if (inject.querySelector('#cm-category-modal') && typeof global.initCategoryMasterPage === 'function') {
          global.initCategoryMasterPage();
        }
        if (inject.querySelector('#emp-main-table') && typeof global.initEmpMasterTableSort === 'function') {
          global.initEmpMasterTableSort();
        }
      } catch (err) {
        if (typeof global.console !== 'undefined' && global.console.error) {
          global.console.error('Stores product embed init failed', err);
        }
      }
    };

    if (typeof global.requestAnimationFrame === 'function') {
      global.requestAnimationFrame(function () {
        global.requestAnimationFrame(afterPaint);
      });
    } else {
      setTimeout(afterPaint, 0);
    }
  }

  function submitMasterEmbedForm(form, submitter) {
    if (!form || !reloadMasterEmbed) return false;
    var loading = document.getElementById('md-master-modal-loading');
    var empty = document.getElementById('md-master-modal-empty');
    var inject = getInjectHost();
    var action = form.getAttribute('action') || window.location.href;
    var method = String(form.getAttribute('method') || form.method || 'get').toLowerCase() || 'get';

    preserveFullscreenForEmbedNav();

    if (method === 'get') {
      try {
        var getUrl = new URL(action, window.location.origin);
        new FormData(form).forEach(function (value, key) {
          if (value != null && String(value) !== '') getUrl.searchParams.set(key, value);
        });
        reloadMasterEmbed(getUrl.pathname + getUrl.search);
      } catch (err) {
        reloadMasterEmbed(action);
      }
      return true;
    }

    var body;
    try {
      body = submitter ? new FormData(form, submitter) : new FormData(form);
    } catch (err) {
      body = new FormData(form);
    }
    if (submitter && submitter.name) {
      body.set(submitter.name, submitter.value != null ? String(submitter.value) : '');
    }
    if (!body.get('embed')) body.set('embed', '1');

    showPanel(empty, false);
    showPanel(inject, false);
    showPanel(loading, true);

    abortMasterLoad();
    masterLoadAbort = new AbortController();
    var signal = masterLoadAbort.signal;
    var postUrl = buildEmbedUrl(action);

    fetch(postUrl, {
      method: 'POST',
      body: body,
      credentials: 'same-origin',
      headers: { Accept: 'text/html' },
      redirect: 'follow',
      signal: signal
    }).then(function (response) {
      /* Validation errors return 400 with embed HTML — still paint them. */
      if (!response.ok && response.status !== 400) throw new Error('embed post failed');
      return response.text();
    }).then(function (html) {
      preserveFullscreenForEmbedNav();
      paintMasterEmbedHtml(html, loading, empty);
    }).catch(function (err) {
      if (err && err.name === 'AbortError') return;
      showPanel(loading, false);
      showPanel(empty, true);
      showPanel(inject, false);
    });
    return true;
  }

  function bindInjectNavigation(inject, getReloadFn, signal) {
    if (!inject || inject.__mdEmbedNavBound) return;
    inject.__mdEmbedNavBound = true;

    var listenerOpts = signal ? { signal: signal } : undefined;
    if (signal) {
      signal.addEventListener('abort', function () {
        inject.__mdEmbedNavBound = false;
      });
    }

    inject.addEventListener('click', function (e) {
      var reloadFn = getReloadFn();
      if (!reloadFn) return;
      var link = e.target.closest('a[href]');
      if (!link || shouldLeaveModal(link)) return;
      // In-page AJAX actions (e.g. Product Master delete) — do not reload embed.
      if (link.hasAttribute('data-de-no-soft-nav') || link.hasAttribute('data-st-product-delete')) return;
      var href = link.getAttribute('href');
      if (!href || href.charAt(0) === '#') return;
      e.preventDefault();
      preserveFullscreenForEmbedNav();
      reloadFn(href);
    }, listenerOpts);

    inject.addEventListener('submit', function (e) {
      var reloadFn = getReloadFn();
      if (!reloadFn) return;
      var form = e.target;
      if (!form || form.tagName !== 'FORM') return;
      e.preventDefault();
      submitMasterEmbedForm(form, e.submitter || null);
    }, listenerOpts);
  }

  var reloadMasterEmbed = null;

  function loadMasterEmbed(url, loading, empty) {
    abortMasterLoad();
    masterLoadAbort = new AbortController();
    var signal = masterLoadAbort.signal;
    var fetchUrl = buildEmbedUrl(url);

    preserveFullscreenForEmbedNav();

    return fetch(fetchUrl, {
      credentials: 'same-origin',
      headers: { Accept: 'text/html' },
      signal: signal
    }).then(function (response) {
      if (!response.ok) throw new Error('fetch failed');
      return response.text();
    }).then(function (html) {
      preserveFullscreenForEmbedNav();
      paintMasterEmbedHtml(html, loading, empty);
    });
  }

  function openMasterModal(name, url, masterId) {
    var modal = document.getElementById('md-master-modal');
    var titleEl = document.getElementById('md-master-modal-title');
    var loading = document.getElementById('md-master-modal-loading');
    var empty = document.getElementById('md-master-modal-empty');
    var inject = getInjectHost();
    if (!modal) return;

    abortMasterLoad();
    clearInjectHost();

    if (titleEl) titleEl.textContent = name || 'Master';

    var openId = String(masterId || '').trim();
    if (!openId && url) {
      try {
        var hrefPath = new URL(url, window.location.origin).pathname.replace(/\/+$/, '');
        Object.keys(MASTER_FALLBACK_URLS).some(function (key) {
          var fallback = String(MASTER_FALLBACK_URLS[key] || '').replace(/\/+$/, '');
          if (fallback && hrefPath === fallback) {
            openId = key;
            return true;
          }
          return false;
        });
      } catch (err) {
        openId = '';
      }
    }
    modal.setAttribute('data-md-open-id', openId);
    syncMasterOpenUrl(openId);

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

  function closeMasterModal(opts) {
    opts = opts || {};
    abortMasterLoad();
    clearInjectHost();

    var modal = document.getElementById('md-master-modal');
    var loading = document.getElementById('md-master-modal-loading');
    var empty = document.getElementById('md-master-modal-empty');
    if (!modal) return;

    var wasOpen = modal.classList.contains('open');
    modal.classList.remove('open');
    modal.setAttribute('aria-hidden', 'true');
    modal.removeAttribute('data-md-open-id');
    setBodyScrollLocked(false);

    showPanel(loading, false);
    showPanel(empty, false);

    if (opts.clearUrl !== false) {
      syncMasterOpenUrl('');
    }
    if (wasOpen) {
      try {
        document.dispatchEvent(new CustomEvent('md-master-modal-closed'));
      } catch (err) {
        /* ignore */
      }
    }
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

    bindInjectNavigation(inject, function () { return reloadMasterEmbed; }, signal);

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
    var categoryModal = document.getElementById('cm-category-modal');
    if (categoryModal && categoryModal.classList.contains('active')) {
      e.preventDefault();
      if (typeof global.closeCategoryMasterModal === 'function') {
        global.closeCategoryMasterModal({ navigate: true, reset: true });
      } else {
        categoryModal.classList.remove('active');
        categoryModal.setAttribute('aria-hidden', 'true');
      }
      return;
    }
    var productModal = document.getElementById('st-product-modal');
    if (productModal && productModal.classList.contains('active')) {
      e.preventDefault();
      if (typeof global.closeProductModal === 'function') {
        global.closeProductModal();
      } else {
        productModal.classList.remove('active');
      }
      return;
    }
    var masterModal = document.getElementById('md-master-modal');
    if (masterModal && masterModal.classList.contains('open')) {
      e.preventDefault();
      e.stopPropagation();
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

    closeMasterModal({ clearUrl: false });

    var searchInput = document.getElementById('md-search-input');
    var filterBtn = document.getElementById('md-search-filter');
    var pillsHost = document.getElementById('md-category-pills');
    var grid = document.getElementById('md-master-grid');
    var emptyState = document.getElementById('md-empty-state');
    var createModal = document.getElementById('md-create-modal');
    var createSubmit = document.getElementById('md-create-submit');

    /* Modal works from Masters hub and from pages that only embed the dialog
       (e.g. hotel room check-in Agency button). */
    bindMasterModal(signal);
    document.addEventListener('keydown', function (e) {
      onDocumentKeydown(e, createModal);
    }, { signal: signal });

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
      var masterId = String(card.getAttribute('data-master-id') || '').trim();
      openMasterModal(name, isMasterCardStub(card) ? null : url, masterId);
    }, { signal: signal, capture: true });

    bindCreateModal(
      createModal,
      [
        document.getElementById('md-new-master-btn')
      ],
      ['#md-create-cancel'],
      signal
    );

    if (createSubmit) {
      createSubmit.addEventListener('click', function () {
        closeCreateModal(createModal);
        showToast('Master creation will be available soon.');
      }, { signal: signal });
    }

    applyFilters();
    restoreMasterOpenFromUrl();
  }

  global.initMastersDashboard = initMastersDashboard;
  global.openMasterModal = openMasterModal;
  global.closeMasterModal = closeMasterModal;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initMastersDashboard);
  } else {
    initMastersDashboard();
  }
})(window);
