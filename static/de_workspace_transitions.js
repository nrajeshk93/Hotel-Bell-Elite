(function(){
  var TRANSITION_MS = 20;
  var OVERLAY_OPACITY = '1';
  var HIDE_MS = 70;
  var MAIN_ENTER_MS = 280;
  var NAV_FLAG = 'de-nav-transition';
  var FS_KEY = 'de-fullscreen-active';
  var PREFETCH_TTL_MS = 90000;
  var PREFETCH_MAX = 48;
  var IDLE_PREFETCH_PATHS = [
    '/home',
    '/main-dashboard',
    '/accounts',
    '/accounts/purchase-ledger',
    '/accounts/cash-ledger',
    '/accounts/back-office-receipt',
    '/master',
    '/stores/indent',
    '/stores/orders',
    '/point-of-sale',
    '/point-of-sale/invoice',
    '/hotel/rooms',
    '/hotel/reservations',
    '/communication-hub',
    '/communication-hub/promotion',
    '/access-management',
    '/employees',
    '/settings'
  ];
  var SKIP_SCRIPT_PARTS = [
    'de_fullscreen.js',
    'de_workspace_nav.js',
    'de_workspace_transitions.js'
  ];
  /** @type {Map<string, {html?: string, promise?: Promise<string>, ts: number}>} */
  var prefetchCache = new Map();
  var softNavToken = 0;
  /** @type {AbortController|null} */
  var softNavAbort = null;
  var overlayHideToken = 0;

  function prefersReducedMotion(){
    return window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  }

  function getOverlay(){
    return document.getElementById('page-transition');
  }

  function beginSoftNavGeneration(){
    softNavToken += 1;
    if(softNavAbort){
      try{ softNavAbort.abort(); } catch(e){}
    }
    softNavAbort = (typeof AbortController !== 'undefined') ? new AbortController() : null;
    // Do NOT add de-soft-navigating here — that freezes the old page and feels like a stall.
    return {
      token: softNavToken,
      signal: softNavAbort ? softNavAbort.signal : undefined
    };
  }

  function isCurrentSoftNav(token){
    return token == null || token === softNavToken;
  }

  function ensureSoftNavProgress(){
    var el = document.getElementById('de-soft-nav-progress');
    if(el) return el;
    el = document.createElement('div');
    el.id = 'de-soft-nav-progress';
    el.setAttribute('aria-hidden', 'true');
    el.innerHTML = '<span></span>';
    (document.body || document.documentElement).appendChild(el);
    return el;
  }

  function showSoftNavProgress(){
    var el = ensureSoftNavProgress();
    el.classList.add('is-active');
  }

  function hideSoftNavProgress(){
    var el = document.getElementById('de-soft-nav-progress');
    if(el) el.classList.remove('is-active');
  }

  function showOverlay(done){
    // Full-screen veil is for hard navigations only (covers white flash of full reload).
    var ov = getOverlay();
    if(!ov || prefersReducedMotion()){
      if(done) done();
      return;
    }
    overlayHideToken += 1;
    ov.style.pointerEvents = 'auto';
    ov.style.display = 'block';
    ov.style.opacity = '0';
    requestAnimationFrame(function(){
      ov.style.opacity = OVERLAY_OPACITY;
      if(done){
        setTimeout(done, TRANSITION_MS);
      }
    });
  }

  function hideOverlay(){
    var ov = getOverlay();
    if(!ov) return;
    var token = ++overlayHideToken;
    ov.style.opacity = '0';
    ov.style.pointerEvents = 'none';
    setTimeout(function(){
      if(token !== overlayHideToken) return;
      ov.style.display = 'none';
    }, HIDE_MS);
  }

  /** Finish soft-nav UI after the swapped content has painted (no blank veil). */
  function finishSoftNavUi(done, token){
    requestAnimationFrame(function(){
      requestAnimationFrame(function(){
        if(!isCurrentSoftNav(token)) return;
        markMainLoading(false);
        hideSoftNavProgress();
        try{ sessionStorage.removeItem(NAV_FLAG); } catch(e){}
        if(typeof done === 'function') done();
      });
    });
  }

  function endSoftNavigatingClass(){
    // Keep suppression briefly so enter keyframes do not restart from opacity:0 after reveal.
    setTimeout(function(){
      document.documentElement.classList.remove('de-soft-navigating');
      // Persist for the session so Restaurant enter-fades do not replay on every swap.
      document.documentElement.classList.add('de-soft-nav-session');
    }, 120);
  }

  var FLOOR_SESSION_KEY = 'hbe_pos_floor_snapshot';
  var FLOOR_SESSION_KEY_BAR = 'hbe_pos_floor_snapshot_bar';

  function writePosFloorSnapshot(data, outlet){
    if(!data || !Array.isArray(data.areas) || !Array.isArray(data.tables)) return false;
    var key = outlet === 'bar' ? FLOOR_SESSION_KEY_BAR : FLOOR_SESSION_KEY;
    try{
      sessionStorage.setItem(key, JSON.stringify({
        areas: data.areas,
        tables: data.tables
      }));
    } catch(e){
      return false;
    }
    try{
      localStorage.setItem(key + '_local', JSON.stringify({
        areas: data.areas,
        tables: data.tables,
        savedAt: Date.now()
      }));
    } catch(e2){}
    return true;
  }

  /** Fetch Tables floor JSON and persist for sync paint on first soft-nav (avoids empty SSR). */
  function warmPosFloorSnapshot(signal, outlet){
    outlet = outlet === 'bar' ? 'bar' : 'restaurant';
    var apiBase = outlet === 'bar' ? '/bar-point-of-sale' : '/point-of-sale';
    var opts = {
      credentials: 'same-origin',
      headers: { Accept: 'application/json' }
    };
    if(signal) opts.signal = signal;
    return fetch(apiBase + '/api/floor', opts).then(function(res){
      return res.json().catch(function(){ return null; });
    }).then(function(data){
      if(data && data.ok && Array.isArray(data.areas) && Array.isArray(data.tables)){
        writePosFloorSnapshot({ areas: data.areas, tables: data.tables }, outlet);
        return data;
      }
      return null;
    }).catch(function(){ return null; });
  }

  function isPosTablesUrl(url){
    try{
      var path = new URL(url, window.location.href).pathname.replace(/\/$/, '') || '/';
      return path === '/point-of-sale' || path === '/bar-point-of-sale';
    } catch(e){
      return false;
    }
  }

  function prefetchRestaurantGroup(){
    if(!shouldSoftNavigate()) return;
    var group = document.getElementById('de-nav-pos-group');
    if(!group) return;
    var links = group.querySelectorAll('a.de-nav-subitem[href]');
    for(var i = 0; i < links.length; i++){
      var href = links[i].getAttribute('href') || '';
      if(!href || href.indexOf('javascript:') === 0) continue;
      prefetchSoftNav(withSalesScope(links[i].href || href));
    }
    // Warm Restaurant JSON + persist floor snapshot so first Tables soft-nav paints tiles.
    if(!window.__dePosApiWarm){
      window.__dePosApiWarm = true;
      warmPosFloorSnapshot(null, 'restaurant');
      ['/point-of-sale/api/menu/items?include_outlets=bar', '/point-of-sale/api/menu/categories?include_outlets=bar'].forEach(function(apiUrl){
        try{
          fetch(apiUrl, {
            credentials: 'same-origin',
            headers: { Accept: 'application/json' }
          }).catch(function(){});
        } catch(e){}
      });
    }
  }

  function prefetchBarPosGroup(){
    if(!shouldSoftNavigate()) return;
    var group = document.getElementById('de-nav-bar-pos-group');
    if(!group) return;
    var links = group.querySelectorAll('a.de-nav-subitem[href]');
    for(var i = 0; i < links.length; i++){
      var href = links[i].getAttribute('href') || '';
      if(!href || href.indexOf('javascript:') === 0) continue;
      prefetchSoftNav(withSalesScope(links[i].href || href));
    }
    if(!window.__deBarPosApiWarm){
      window.__deBarPosApiWarm = true;
      warmPosFloorSnapshot(null, 'bar');
      ['/bar-point-of-sale/api/menu/items?include_outlets=restaurant', '/bar-point-of-sale/api/menu/categories?include_outlets=restaurant'].forEach(function(apiUrl){
        try{
          fetch(apiUrl, {
            credentials: 'same-origin',
            headers: { Accept: 'application/json' }
          }).catch(function(){});
        } catch(e){}
      });
    }
  }

  function prefetchFromSidebarEvent(event){
    var target = event.target && event.target.closest ? event.target : null;
    if(!target) return;
    if(target.closest('#de-nav-pos-group, #de-nav-pos-toggle, #de-nav-pos-sub')){
      prefetchRestaurantGroup();
    }
    if(target.closest('#de-nav-bar-pos-group, #de-nav-bar-pos-toggle, #de-nav-bar-pos-sub')){
      prefetchBarPosGroup();
    }
    var link = target.closest('.de-sidebar a[href], .sidebar a[href], a[href]');
    if(!link) return;
    /* Hover-prefetch sidebar + report hub cards (pointerdown still warms everything). */
    if(link.closest && !link.closest('.de-sidebar, .sidebar') && event.type === 'mouseover'){
      if(!link.classList.contains('rd-report-card') && !link.closest('.db-home-card, .db-home')) return;
    }
    var rawHref = link.getAttribute('href') || '';
    if(!rawHref || rawHref.indexOf('javascript:') === 0) return;
    if(link.hasAttribute('data-de-no-soft-nav')) return;
    if(!isSameOriginLink(link)) return;
    if(isFileDownloadLink(link)) return;
    if(isMasterModalLink(link)) return;
    if(isEmbedFragmentUrl(link.href || rawHref)) return;
    if(isLogoutUrl(link.href || rawHref)) return;
    prefetchSoftNav(withSalesScope(link.href));
  }

  function isFullscreenActive(){
    return !!(
      document.fullscreenElement
      || document.webkitFullscreenElement
      || document.mozFullScreenElement
      || document.msFullscreenElement
    );
  }

  function isFullscreenPreferred(){
    try{
      return sessionStorage.getItem(FS_KEY) === '1';
    } catch(e){
      return false;
    }
  }

  function hasWorkspaceShell(){
    return !!document.querySelector('.de-main-wrapper');
  }

  function shouldSoftNavigate(){
    return hasWorkspaceShell() || isFullscreenActive() || isFullscreenPreferred();
  }

  /** Sign-in / password forms — soft-submit must request a FULL shell document.
   *  Partial=main after login left Applications with no left nav until refresh. */
  function isAuthShellForm(form){
    if(!form) return false;
    if(form.id === 'login-form' || form.classList.contains('login-form')) return true;
    if(document.body && document.body.classList.contains('login-page') && form.closest('.login-panel, .login-shell')){
      return true;
    }
    try{
      var action = form.getAttribute('action') || '';
      var path = new URL(action, window.location.href).pathname.replace(/\/$/, '') || '/';
      return path === '/login' || path === '/change-password';
    } catch(e){
      return false;
    }
  }

  function formToGetUrl(form){
    var url = new URL(form.getAttribute('action') || window.location.href, window.location.href);
    var params = new URLSearchParams();
    var fd = new FormData(form);
    fd.forEach(function(value, key){
      if(typeof File !== 'undefined' && value instanceof File) return;
      params.append(key, String(value));
    });
    url.search = params.toString();
    return withSalesScope(url.toString());
  }

  function shouldSoftSubmitForm(form){
    if(!form || form.nodeName !== 'FORM') return false;
    if(form.getAttribute('data-de-hard-nav') === '1') return false;
    if(form.hasAttribute('data-de-hard-nav')) return false;
    if(form.hasAttribute('data-md-full-nav') || form.closest('[data-md-full-nav]')) return false;
    if(form.closest('#md-master-modal, .md-master-modal, #md-master-modal-inject, .md-master-embed')) return false;
    // Modal / dialog forms are handled by page JS (JSON APIs); soft-nav must not steal submit.
    // Opt in with data-de-allow-soft-submit when the modal posts HTML (credit dashboard).
    if(form.getAttribute('data-de-allow-soft-submit') !== '1' && form.closest(
      '.modal-overlay, .modal-backdrop, .hrd-modal-overlay, .hrd-dialog-overlay, [role="dialog"][aria-modal="true"]'
    )) return false;
    // Communication Hub composer posts via fetch JSON — never soft-navigate on Send.
    if(form.id === 'ch-composer' || form.closest('#communication-hub-page form.ch-composer')) return false;
    if(form.hasAttribute('data-st-decide-form') || form.id === 'st-reject-form') return false;
    var method = String(form.getAttribute('method') || form.method || 'get').toLowerCase();
    if(method && method !== 'get' && method !== 'post') return false;
    // Multipart (e.g. access-management photo) is fine: softSubmitForm posts FormData
    // via fetch, which sets the boundary Content-Type. Hard submit would exit fullscreen.
    return shouldSoftNavigate();
  }

  function formMethod(form){
    return String(form.getAttribute('method') || form.method || 'get').toLowerCase() || 'get';
  }

  function appendSubmitter(fd, submitter){
    if(!fd || !submitter || !submitter.name) return;
    try{
      fd.set(submitter.name, submitter.value != null ? String(submitter.value) : '');
    } catch(e){
      fd.append(submitter.name, submitter.value != null ? String(submitter.value) : '');
    }
  }

  function hardSubmitFallback(form, submitter){
    try{
      form.setAttribute('data-de-hard-nav', '1');
      if(submitter && submitter.name){
        var ghost = document.createElement('input');
        ghost.type = 'hidden';
        ghost.name = submitter.name;
        ghost.value = submitter.value != null ? String(submitter.value) : '';
        ghost.setAttribute('data-de-soft-submitter', '1');
        form.appendChild(ghost);
      }
      HTMLFormElement.prototype.submit.call(form);
    } catch(e){
      form.submit();
    }
  }

  /**
   * Guard against duplicate POSTs from a double-click / double-tap / double
   * Enter on a submit button (which previously fired two overlapping
   * fetch-based soft submits — e.g. two "send for approval" requests). Only
   * POST forms are locked; idempotent GET soft-nav (search/filter) forms are
   * left untouched.
   */
  var SUBMIT_LOCK_ATTR = 'data-de-submit-lock';

  function isFormSubmitLocked(form){
    return !!form && form.getAttribute(SUBMIT_LOCK_ATTR) === '1';
  }

  function lockFormSubmit(form){
    if(!form) return;
    form.setAttribute(SUBMIT_LOCK_ATTR, '1');
    var controls = form.querySelectorAll('button[type="submit"], input[type="submit"]');
    for(var i = 0; i < controls.length; i++){
      var btn = controls[i];
      if(btn.disabled) continue;
      btn.setAttribute('data-de-lock-reenable', '1');
      btn.disabled = true;
    }
  }

  function unlockFormSubmit(form){
    if(!form) return;
    form.removeAttribute(SUBMIT_LOCK_ATTR);
    var controls = form.querySelectorAll('[data-de-lock-reenable]');
    for(var i = 0; i < controls.length; i++){
      controls[i].disabled = false;
      controls[i].removeAttribute('data-de-lock-reenable');
    }
  }

  function stripPartialParam(url){
    try{
      var target = new URL(url, window.location.href);
      target.searchParams.delete('partial');
      return target.toString();
    } catch(e){
      return url;
    }
  }

  /** Soft-submit GET/POST forms so fullscreen and the workspace shell survive. */
  function softSubmitForm(form, submitter){
    if(!shouldSoftSubmitForm(form)) return false;
    var method = formMethod(form);

    if(method === 'get'){
      navigateWithTransition(formToGetUrl(form));
      return true;
    }

    rememberSidebarState();
    try{ sessionStorage.setItem(NAV_FLAG, '1'); } catch(e){}
    var nav = beginSoftNavGeneration();
    setSoftNavFlag(true);
    markMainLoading(true);
    var sidebarScroll = captureSidebarScroll();
    if(window.deFullscreen && typeof window.deFullscreen.armForSoftNav === 'function'){
      window.deFullscreen.armForSoftNav();
    } else if(window.deFullscreen && typeof window.deFullscreen.preserveForNavigation === 'function'){
      window.deFullscreen.preserveForNavigation();
    }
    if(window.deFullscreen && typeof window.deFullscreen.preserveForNavigation === 'function'){
      window.deFullscreen.preserveForNavigation();
    }

    var actionUrl = form.getAttribute('action') || window.location.href;
    var fd = new FormData(form);
    appendSubmitter(fd, submitter);

    showSoftNavProgress();
    /* Auth (login / change-password) must fetch a full workspace document so
       swapDocumentInsideFullscreen can restore #ep-workspace + sidebar. */
    var authShellPost = isAuthShellForm(form);
    var postUrl = authShellPost ? actionUrl : withPartialMain(actionUrl);
    var fetchHeaders = {
      'Accept': 'text/html'
    };
    if(!authShellPost){
      fetchHeaders['X-De-Partial'] = 'main';
    }
    var fetchOpts = {
      method: 'POST',
      body: fd,
      credentials: 'same-origin',
      headers: fetchHeaders,
      redirect: 'follow',
      cache: 'no-store'
    };
    if(nav.signal) fetchOpts.signal = nav.signal;
    // Once the server has accepted the POST, never hard-resubmit — that previously
    // could double-fire expensive side effects (e.g. WhatsApp indent approval).
    var serverAccepted = false;
    var followedUrl = '';
    fetch(postUrl, fetchOpts).then(function(response){
      serverAccepted = true;
      followedUrl = stripPartialParam(response.url || actionUrl);
      if(!response.ok) throw new Error('post soft submit failed');
      var contentType = (response.headers.get('content-type') || '').toLowerCase();
      if(contentType.indexOf('text/html') === -1) throw new Error('non-html response');
      return response.text().then(function(html){
        return { html: html, url: followedUrl };
      });
    }).then(function(result){
      if(!isCurrentSoftNav(nav.token)){
        unlockFormSubmit(form);
        return;
      }
      try{
        var followedPath = new URL(result.url, window.location.href).pathname.replace(/\/$/, '') || '/';
        invalidatePrefetch(result.url);
        invalidatePrefetchByPath(followedPath);
        if(followedPath.indexOf('/access-management') === 0){
          invalidatePrefetchByPath('/access-management');
        }
      } catch(eInv){}
      try{ history.pushState({ deSoftNav: true }, '', result.url); } catch(e){}
      if(window.deFullscreen && typeof window.deFullscreen.preserveForNavigation === 'function'){
        window.deFullscreen.preserveForNavigation();
      }
      var doc = new DOMParser().parseFromString(result.html, 'text/html');
      // Swapped-in HTML brings its own fresh (unlocked) form, but unlock the
      // old node too in case anything still references it.
      unlockFormSubmit(form);
      applySoftSwap(doc, result.url, hideSoftNavProgress, sidebarScroll, nav.token);
    }).catch(function(err){
      if(err && err.name === 'AbortError'){
        unlockFormSubmit(form);
        markMainLoading(false);
        hideSoftNavProgress();
        return;
      }
      if(!isCurrentSoftNav(nav.token)){
        unlockFormSubmit(form);
        markMainLoading(false);
        hideSoftNavProgress();
        return;
      }
      markMainLoading(false);
      setSoftNavFlag(false);
      document.documentElement.classList.remove('de-soft-navigating');
      hideSoftNavProgress();
      unlockFormSubmit(form);
      try{ sessionStorage.removeItem(NAV_FLAG); } catch(e){}
      if(serverAccepted){
        // POST already ran; never GET the POST-only action URL (Method Not Allowed).
        try{
          var fallbackUrl = followedUrl || window.location.href;
          window.location.assign(stripPartialParam(fallbackUrl));
        } catch(e){}
        return;
      }
      hardSubmitFallback(form, submitter);
    });
    return true;
  }

  function installFormSubmitGuards(){
    if(window.__deFormSubmitGuards) return;
    window.__deFormSubmitGuards = true;

    document.addEventListener('submit', function(event){
      var form = event.target;
      if(!form || form.nodeName !== 'FORM') return;
      var isPost = formMethod(form) === 'post';

      // Only soft-nav POST forms are locked. Modal/JS-handled forms (approvals decide,
      // etc.) must keep their submitter enabled so FormData includes decision=approved.
      if(!shouldSoftSubmitForm(form)){
        return;
      }


      if(isPost){
        if(isFormSubmitLocked(form)){
          // A prior submit for this exact form is still in flight (double
          // click / double Enter) — drop this duplicate instead of firing a
          // second POST (which previously meant a second approval request).
          event.preventDefault();
          event.stopPropagation();
          return;
        }
        lockFormSubmit(form);
      }

      event.preventDefault();
      event.stopPropagation();
      if(!softSubmitForm(form, event.submitter || null) && isPost){
        unlockFormSubmit(form);
      }
    }, true);

    try{
      var originalSubmit = HTMLFormElement.prototype.submit;
      HTMLFormElement.prototype.submit = function(){
        var isPost = formMethod(this) === 'post';
        if(isPost){
          if(isFormSubmitLocked(this)) return;
          lockFormSubmit(this);
        }
        if(softSubmitForm(this, null)) return;
        if(isPost) unlockFormSubmit(this);
        return originalSubmit.call(this);
      };
    } catch(e){}

    // Back/forward-cache restores can bring back a page with buttons left
    // disabled from an in-flight submit that never resolved; clear them.
    window.addEventListener('pageshow', function(){
      var locked = document.querySelectorAll('[' + SUBMIT_LOCK_ATTR + ']');
      for(var i = 0; i < locked.length; i++) unlockFormSubmit(locked[i]);
    });
  }

  function withSalesScope(url){
    try{
      var target = new URL(url, window.location.origin);
      var path = target.pathname.replace(/\/$/, '') || '/';
      var isSalesUpdate =
        path.indexOf('/sales_update') === 0
        || path === '/point-of-sale/sales-update'
        || path === '/bar-point-of-sale/sales-update'
        || path === '/hotel/sales-update';
      if(!isSalesUpdate) return url;

      var params = new URLSearchParams(window.location.search);
      var dateEl = document.getElementById('se-filter-date');
      var companyEl = document.getElementById('sales-company');
      var date = (dateEl && dateEl.value) || params.get('date') || '';
      var company = (companyEl && companyEl.value) || params.get('company') || '';

      if(!date){
        try{ date = sessionStorage.getItem('hbe.salesUpdate.date') || ''; } catch(e){}
      }

      if(date && !target.searchParams.get('date')) target.searchParams.set('date', date);
      if(company && !target.searchParams.get('company')) target.searchParams.set('company', company);

      return target.toString();
    } catch(e){
      return url;
    }
  }

  function navCacheKey(url){
    try{
      var target = new URL(url, window.location.href);
      target.searchParams.delete('partial');
      target.hash = '';
      return target.pathname + target.search;
    } catch(e){
      return String(url || '');
    }
  }

  /** Lists that change after a write — never paint a hover-prefetch snapshot. */
  function mustFetchLiveSoftNavPath(path){
    path = String(path || '').replace(/\/$/, '') || '/';
    return (
      path === '/communication-hub' ||
      path === '/communication-hub/promotion' ||
      path === '/access-management/roles' ||
      path === '/access-management/logs' ||
      path === '/point-of-sale/invoice-ledger' ||
      path === '/bar-point-of-sale/invoice-ledger' ||
      path === '/hotel/invoice-ledger' ||
      path === '/hotel/room-transfer-invoices' ||
      path === '/hotel/credit' ||
      path === '/credits' ||
      path.indexOf('/credits/') === 0 ||
      /* Sales reports (agency billing, invoice sales, etc.) change as invoices settle. */
      path.indexOf('/reports/sales/') === 0
    );
  }

  function invalidatePrefetch(url){
    try{
      prefetchCache.delete(navCacheKey(url));
    } catch(e){}
  }

  /** Drop every soft-nav prefetch whose pathname matches (with or without trailing slash). */
  function invalidatePrefetchByPath(pathname){
    try{
      var want = String(pathname || '').replace(/\/$/, '') || '/';
      Array.from(prefetchCache.keys()).forEach(function(key){
        var path = String(key || '').split('?')[0].replace(/\/$/, '') || '/';
        if(path === want || path.indexOf(want + '/') === 0){
          prefetchCache.delete(key);
        }
      });
    } catch(e){}
  }

  /** Fetch URL for soft-nav: same page, but only .de-main-wrapper from the server. */
  function withPartialMain(url){
    try{
      var target = new URL(url, window.location.href);
      target.searchParams.set('partial', 'main');
      target.hash = '';
      return target.toString();
    } catch(e){
      var base = String(url || '');
      return base + (base.indexOf('?') >= 0 ? '&' : '?') + 'partial=main';
    }
  }

  function prunePrefetchCache(){
    if(prefetchCache.size <= PREFETCH_MAX) return;
    var entries = Array.from(prefetchCache.entries()).sort(function(a, b){
      return (a[1].ts || 0) - (b[1].ts || 0);
    });
    while(entries.length && prefetchCache.size > PREFETCH_MAX){
      var oldest = entries.shift();
      if(oldest) prefetchCache.delete(oldest[0]);
    }
  }

  function storePrefetchHtml(key, html){
    if(!html || htmlLooksLikeAuthShell(html)){
      prefetchCache.delete(key);
      return;
    }
    prefetchCache.set(key, { html: html, ts: Date.now() });
    prunePrefetchCache();
    /* Warm destination stylesheets early so soft-nav does not paint before CSS. */
    try{
      warmStylesheetsFromHtml(html);
    } catch(e){}
  }

  function htmlLooksLikeAuthShell(html){
    if(!html) return true;
    return html.indexOf('login-page') !== -1 || html.indexOf('id="login-form"') !== -1;
  }

  function warmStylesheetsFromHtml(html){
    if(!html) return;
    var re = /<link[^>]+rel=["']stylesheet["'][^>]*>/gi;
    var tag;
    while((tag = re.exec(html))){
      var hrefMatch = tag[0].match(/href=["']([^"']+)["']/i);
      if(!hrefMatch) continue;
      var href = hrefMatch[1];
      if(!href || href.indexOf('/static/') === -1) continue;
      var exists = Array.from(document.querySelectorAll('link[rel="stylesheet"], link[rel="preload"][as="style"]')).some(function(el){
        var current = el.getAttribute('href') || '';
        if(current === href) return true;
        try{
          return new URL(current, window.location.href).pathname === new URL(href, window.location.href).pathname;
        } catch(err){
          return false;
        }
      });
      if(exists) continue;
      /* Apply as stylesheet (not preload-only) so soft-nav merge finds a ready sheet. */
      var link = document.createElement('link');
      link.rel = 'stylesheet';
      link.href = href;
      document.head.appendChild(link);
    }
  }

  function prefetchSoftNav(url){
    if(!url || !shouldSoftNavigate()) return;
    if(isEmbedFragmentUrl(url)) return;
    if(isLogoutUrl(url)) return;
    url = withSalesScope(url);
    url = urlWithPosSettingsSection(url);
    if(sameAppUrl(url, window.location.href)) return;
    try{
      var path = new URL(url, window.location.href).pathname.toLowerCase();
      if(path.indexOf('/export') !== -1 || path.indexOf('/download_') !== -1) return;
      if(path === '/accounts/credit-payment/report' || path === '/accounts/purchase-verification/report') return;
      if(path === '/accounts/purchase-ledger/report' || path === '/accounts/cash-ledger/report') return;
      if(path === '/accounts/back-office-receipt/report') return;
      /* Payroll HTML /report — not a file download. Do not treat /reports hub as export. */
      if(/\.(xlsx|xls|docx|doc|csv|pdf|zip)(\?|$)/.test(path)) return;
      if(mustFetchLiveSoftNavPath(path)) return;
    } catch(e){}
    var key = navCacheKey(url);
    var existing = prefetchCache.get(key);
    if(existing && existing.html && (Date.now() - existing.ts) < PREFETCH_TTL_MS) return;
    if(existing && existing.promise) return;

    var promise = fetch(withPartialMain(url), {
      credentials: 'same-origin',
      headers: {
        'Accept': 'text/html',
        'X-De-Partial': 'main'
      },
      redirect: 'follow',
      cache: 'no-store'
    }).then(function(response){
      if(!response.ok) throw new Error('prefetch failed');
      var contentType = (response.headers.get('content-type') || '').toLowerCase();
      if(contentType.indexOf('text/html') === -1) throw new Error('non-html prefetch');
      return response.text();
    }).then(function(html){
      storePrefetchHtml(key, html);
      return html;
    }).catch(function(){
      prefetchCache.delete(key);
      return '';
    });

    prefetchCache.set(key, { promise: promise, ts: Date.now() });
  }

  function prefetchHtmlReady(url){
    try{
      var key = navCacheKey(withSalesScope(urlWithPosSettingsSection(url)));
      var entry = prefetchCache.get(key);
      return !!(entry && entry.html && (Date.now() - entry.ts) < PREFETCH_TTL_MS);
    } catch(e){
      return false;
    }
  }

  function takePrefetchedHtml(url){
    var key = navCacheKey(url);
    var entry = prefetchCache.get(key);
    if(!entry){
      return null;
    }
    if(entry.html && (Date.now() - entry.ts) < PREFETCH_TTL_MS){
      /* Keep cache entry so Back / re-open stays instant within TTL. */
      try{
        var path = new URL(url, window.location.href).pathname.replace(/\/$/, '') || '/';
        /* Inbox / invoice ledgers / roles mutate after writes — a hover prefetch
           would hide the newest row until a hard refresh. */
        if(mustFetchLiveSoftNavPath(path)){
          prefetchCache.delete(key);
          return null;
        }
        /* Indent / inward forms embed Product Master packs — stale prefetch
           leaves Pack stuck on "Base unit" after variants are edited. */
        if(path === '/stores/indent' || path === '/stores/inward'){
          try{
            var focus = new URL(url, window.location.href).searchParams.get('focus') || '';
            if(focus === 'form' || path === '/stores/inward'){
              prefetchCache.delete(key);
              return null;
            }
          } catch(eFocus){
            prefetchCache.delete(key);
            return null;
          }
        }
        /* Generate PO mutates line suppliers then soft-reloads — never paint a
           cached pre-save page that looks like the pick did not stick. */
        if(/^\/stores\/orders\/\d+/.test(path)){
          prefetchCache.delete(key);
          return null;
        }
        if(path === '/point-of-sale' && (
          entry.html.indexOf('pos-kot-tokens-modal') === -1 ||
          entry.html.indexOf('pos-today-invoices-modal') === -1
        )){
          prefetchCache.delete(key);
          return null;
        }
      } catch(e){}
      return Promise.resolve(entry.html);
    }
    if(entry.promise){
      return entry.promise.then(function(html){
        if(!html) return null;
        try{
          var path = new URL(url, window.location.href).pathname.replace(/\/$/, '') || '/';
          if(mustFetchLiveSoftNavPath(path)){
            return null;
          }
          if(path === '/stores/indent' || path === '/stores/inward'){
            try{
              var focusPending = new URL(url, window.location.href).searchParams.get('focus') || '';
              if(focusPending === 'form' || path === '/stores/inward') return null;
            } catch(eFocusPending){
              return null;
            }
          }
          if(/^\/stores\/orders\/\d+/.test(path)){
            return null;
          }
          if(path === '/point-of-sale' && (
            html.indexOf('pos-kot-tokens-modal') === -1 ||
            html.indexOf('pos-today-invoices-modal') === -1
          )){
            return null;
          }
        } catch(e){}
        return html;
      });
    }
    prefetchCache.delete(key);
    return null;
  }

  function markMainLoading(active){
    var main = document.querySelector('.de-main-wrapper');
    if(!main) return;
    main.classList.toggle('is-soft-nav-loading', !!active);
  }

  function posSettingsSectionFromStorage(){
    try{
      var key = String(sessionStorage.getItem('hbe_pos_settings_section') || '').trim().toLowerCase();
      var valid = ['general','floor','tables','areas','taxes','invoice','payment','printers'];
      return valid.indexOf(key) >= 0 ? key : '';
    } catch(e){
      return '';
    }
  }

  function isPosSettingsPath(pathname){
    var path = String(pathname || '').replace(/\/$/, '') || '/';
    return path === '/point-of-sale/settings' || path === '/bar-point-of-sale/settings';
  }

  function urlWithPosSettingsSection(url){
    try{
      var target = new URL(url, window.location.href);
      /* Exact path match — do NOT use indexOf (bar-point-of-sale/settings contains
         the restaurant path as a substring and was wrongly rewritten). */
      if(!isPosSettingsPath(target.pathname)) return url;
      if(target.hash && target.hash.length > 1) return target.toString();
      var stored = posSettingsSectionFromStorage();
      if(stored && stored !== 'general') target.hash = stored;
      return target.toString();
    } catch(e){
      return url;
    }
  }

  /** Detect soft-nav that updated the URL but left stale main content. */
  function softNavMainH1(main){
    var h = main && main.querySelector('h1');
    return h ? String(h.textContent || '').replace(/\s+/g, ' ').trim() : '';
  }

  function softNavSalesLocation(main){
    var el = main && (main.querySelector('#sales-location') || main.querySelector('[data-location]'));
    if(!el) return '';
    return String(el.value || el.getAttribute('data-location') || '').trim().toLowerCase();
  }

  function softNavContentMatchesUrl(url){
    try{
      var path = new URL(url, window.location.href).pathname.replace(/\/$/, '') || '/';
      var main = document.querySelector('.de-main-wrapper');
      if(!main) return false;
      var h1 = softNavMainH1(main);

      /* POS — restaurant + bar */
      if(path === '/point-of-sale/settings' || path === '/bar-point-of-sale/settings'){
        return !!main.querySelector('#pos-settings-page, [data-pos-settings]');
      }
      if(path === '/point-of-sale/menu' || path === '/bar-point-of-sale/menu'){
        return !!main.querySelector('#pos-menu-page, [data-pos-menu]');
      }
      if(path === '/point-of-sale/invoice' || path === '/bar-point-of-sale/invoice'){
        return !!main.querySelector('#pos-invoice-page, [data-pos-invoice]');
      }
      if(path === '/point-of-sale/invoice-ledger' || path === '/bar-point-of-sale/invoice-ledger'){
        return !!main.querySelector('#pos-invoice-ledger-page, [data-pos-invoice-ledger]');
      }
      if(path === '/point-of-sale/sales-update' || path === '/bar-point-of-sale/sales-update'){
        return softNavSalesLocation(main) === (path.indexOf('/bar-') === 0 ? 'bar' : 'restaurant');
      }
      if(path === '/point-of-sale' || path === '/bar-point-of-sale'){
        return !!main.querySelector('#pos-tables-page, [data-pos-tables]');
      }

      /* Hotel rooms */
      if(path === '/hotel/rooms'){
        return !!main.querySelector('#hotel-rooms-page, [data-hotel-rooms]');
      }
      if(path === '/hotel/reservations'){
        return !!main.querySelector('#hotel-reservations-page, [data-hotel-reservations]');
      }
      if(path === '/hotel/settings'){
        return !!main.querySelector('#hotel-settings-page, [data-hotel-settings]');
      }
      if(path === '/hotel/invoice-ledger'){
        return !!main.querySelector('#hotel-invoice-ledger-page, [data-hotel-invoice-ledger]');
      }
      if(path === '/hotel/credit'){
        return !!main.querySelector('#credit-payment-page') && /^credit$/i.test(h1);
      }
      if(path === '/hotel/sales-update'){
        return softNavSalesLocation(main) === 'hotel';
      }
      if(path.indexOf('/hotel/rooms/') === 0){
        return !!main.querySelector('#hotel-room-detail-page, [data-hotel-room-detail]');
      }

      /* Communication Hub */
      if(path === '/communication-hub'){
        return !!main.querySelector('#communication-hub-page, [data-communication-hub]');
      }
      if(path === '/communication-hub/promotion'){
        return !!main.querySelector('#ch-promotion-page, [data-communication-hub-promotion]');
      }

      /* Home / masters / reports / access */
      if(path === '/home') return !!main.querySelector('#dashboard-home-panel, .db-home');
      if(path === '/main-dashboard') return !!main.querySelector('#main-dashboard-page, #main-dashboard-title');
      if(path === '/dashboard') return !!main.querySelector('#dashboard-coming-soon-title');
      if(path === '/master') return !!main.querySelector('#md-master-grid, #md-search-input');
      if(path === '/reports') return !!main.querySelector('#rd-report-sections, #rd-search-input');
      if(path.indexOf('/reports/sales/') === 0){
        return !!main.querySelector(
          '#sales-report-page, [data-sales-report], '
          + '#menu-sales-report-page, [data-menu-sales-report], '
          + '#customer-insights-report-page, [data-customer-insights-report], '
          + '#manager-insight-report-page, [data-manager-insight-report]'
        );
      }
      if(path === '/settings') return !!main.querySelector('#settings-page, [data-settings], #sd-settings-sections');
      if(path === '/access-management') return !!main.querySelector('#am-users-filter-form, #am-users-search');

      /* Accounts */
      if(path === '/accounts/purchase-ledger'){
        return !!main.querySelector('#purchase-ledger-filter-form, #pl-open-add-purchase');
      }
      if(path === '/accounts/cash-ledger') return !!main.querySelector('#cash-ledger-page');
      if(path === '/accounts/back-office-receipt') return !!main.querySelector('#back-office-receipt-page');
      if(path === '/accounts/credit-payment'){
        return !!main.querySelector('#credit-payment-page') && /credit payment/i.test(h1);
      }
      if(path === '/accounts/purchase-verification'){
        return !!main.querySelector('#credit-payment-page') && /approvals/i.test(h1);
      }
      if(path === '/suppliers') return !!main.querySelector('#sm-supplier-table, #sm-supplier-list-panel');
      if(path === '/agencies') return !!main.querySelector('#sm-agency-table, #sm-agency-list-panel');
      if(path === '/customers') return !!main.querySelector('#sm-customer-table, #sm-customer-list-panel');

      /* Sales analytics */
      if(path === '/sales_update/hotel' || path === '/hotel/sales-update') return softNavSalesLocation(main) === 'hotel';
      if(path === '/sales_update/bar' || path === '/bar-point-of-sale/sales-update') return softNavSalesLocation(main) === 'bar';
      if(path === '/sales_update/restaurant' || path === '/point-of-sale/sales-update') return softNavSalesLocation(main) === 'restaurant';
      if(path === '/sales_update/room_transfer'){
        return !!main.querySelector('#room-transfer-page') && /room transfer/i.test(h1);
      }
      if(path === '/sales_update/credit'){
        return !!main.querySelector('#room-transfer-page') && /^credit$/i.test(h1);
      }
      if(path === '/sales_update/tips'){
        return !!main.querySelector('#tips-analytics-page, #tips-filter-form, #tips-search');
      }

      /* Payroll */
      if(path === '/employees'){
        return !!main.querySelector('#emp-search-chip, #emp-main-table');
      }
      if(path === '/attendance_overview' || path === '/attendance_date' || path.indexOf('/attendance/') === 0){
        return !!main.querySelector('#attendance-search-chip, #emp-attendance-overview-table, .ep-att-header');
      }
      if(path === '/credits' || path.indexOf('/credits/') === 0){
        return !!main.querySelector('#credits-dashboard-filter-form, #credits-dashboard-form, #cd-search, #emp-credit-history-table');
      }
      if(path === '/report'){
        return !!main.querySelector('#report-month-form, #emp-salary-breakdown-table');
      }

      /* Stores — Indent and Purchase Order share search/count IDs; distinguish by PO marker. */
      if(path === '/stores/indent' || /^\/stores\/indent\/\d+/.test(path)){
        return !!main.querySelector('.st-indent-page') && !main.querySelector('[data-st-po-page], .st-po-page');
      }
      if(path === '/stores/orders' || path === '/stores/orders/history' || /^\/stores\/orders\/\d+/.test(path)){
        return !!main.querySelector('[data-st-po-page], .st-po-page');
      }
      if(path === '/stores/purchase-requests') return !!main.querySelector('#st-inward-page, #st-inward-indent, #st-inward-indent-listbox, #st-inward-direct-lines');
      if(path === '/stores/stock') return !!main.querySelector('#st-stock-search, #st-stock-page');
      if(path === '/stores/stock-audit') return !!main.querySelector('#st-audit-page, #st-audit-queue, #st-audit-search');
      if(path === '/stores/stock-audit/report') return !!main.querySelector('#st-audit-report-page, #st-audit-report-filter-form');
    } catch(e){}
    return true;
  }

  function rememberSidebarState(){
    try{
      var pinned = false;
      document.querySelectorAll('.de-sidebar').forEach(function(sidebar){
        if(sidebar.classList.contains('is-pinned')) pinned = true;
      });
      persistOpenNavGroups();
      /* Only persist pin ON from DOM. Never clear pin here — soft-nav / hover
         races can briefly drop is-pinned and would wipe the user preference. */
      if(pinned){
        localStorage.setItem('de-sidebar-pinned', '1');
        sessionStorage.setItem('de-sidebar-expanded', '1');
      } else {
        sessionStorage.removeItem('de-sidebar-expanded');
      }
      if(isFullscreenActive() || isFullscreenPreferred()){
        sessionStorage.setItem(FS_KEY, '1');
      }
      if(window.deFullscreen && typeof window.deFullscreen.prepareNavigation === 'function'){
        window.deFullscreen.prepareNavigation();
      }
      if(window.deFullscreen && typeof window.deFullscreen.ensureRoot === 'function'){
        window.deFullscreen.ensureRoot();
      }
    } catch(e){}
  }

  function shouldSkipScript(scriptEl){
    var src = scriptEl.getAttribute('src') || '';
    if(!src) return false;
    for(var i = 0; i < SKIP_SCRIPT_PARTS.length; i++){
      if(src.indexOf(SKIP_SCRIPT_PARTS[i]) !== -1) return true;
    }
    return false;
  }

  function shouldRerunScript(scriptEl){
    return !!(scriptEl && scriptEl.getAttribute('data-de-rerun') === '1');
  }

  function mergeStylesheetLink(link, addedLinks, staleLinks){
    var href = link.getAttribute('href');
    if(!href) return;
    var path = '';
    try{ path = new URL(href, window.location.href).pathname; } catch(e){ path = String(href).split('?')[0]; }
    var exists = false;
    /* Check head + body — shell partials may leave sheets outside <head>. */
    Array.from(document.querySelectorAll('link[rel="stylesheet"]')).forEach(function(existing){
      var eh = existing.getAttribute('href') || '';
      if(eh === href){ exists = true; return; }
      /* Same file, different ?v= — keep the live sheet until the new one is ready.
         Removing it immediately unstyles the current page (modal-backdrops become
         visible; transparent #de-fs-app shows the webview's black background). */
      try{
        if(path && new URL(eh, window.location.href).pathname === path){
          if(staleLinks && staleLinks.indexOf(existing) === -1) staleLinks.push(existing);
          for(var i = addedLinks.length - 1; i >= 0; i--){
            if(addedLinks[i] === existing) addedLinks.splice(i, 1);
          }
        }
      } catch(err){}
    });
    if(exists) return;
    var clone = link.cloneNode(true);
    document.head.appendChild(clone);
    addedLinks.push(clone);
  }

  function dropStaleStylesheets(staleLinks){
    (staleLinks || []).forEach(function(el){
      try{
        if(el && el.parentNode) el.parentNode.removeChild(el);
      } catch(e){}
    });
  }

  function dropStaleWhenReady(staleLinks, addedLinks){
    if(!staleLinks || !staleLinks.length) return;
    var pending = (addedLinks || []).filter(function(link){
      try{ return !link.sheet; } catch(e){ return true; }
    });
    if(!pending.length){
      dropStaleStylesheets(staleLinks);
      return;
    }
    var left = pending.length;
    function done(){
      left -= 1;
      if(left <= 0) dropStaleStylesheets(staleLinks);
    }
    pending.forEach(function(link){
      link.addEventListener('load', done, { once: true });
      link.addEventListener('error', done, { once: true });
    });
  }

  function mergeHeadAssets(sourceDoc, mainEl){
    var addedLinks = [];
    var staleLinks = [];
    if(sourceDoc && sourceDoc.head){
      sourceDoc.head.querySelectorAll('link[rel="stylesheet"]').forEach(function(link){
        mergeStylesheetLink(link, addedLinks, staleLinks);
      });
    }
    /* True partial=main fragments carry page CSS inside .de-main-wrapper (no <head>). */
    if(mainEl){
      mainEl.querySelectorAll('link[rel="stylesheet"]').forEach(function(link){
        mergeStylesheetLink(link, addedLinks, staleLinks);
      });
    }
    var oldSoftStyles = Array.from(document.head.querySelectorAll('style[data-de-soft-nav]'));
    if(sourceDoc && sourceDoc.head){
      sourceDoc.head.querySelectorAll('style').forEach(function(style){
        var clone = style.cloneNode(true);
        clone.setAttribute('data-de-soft-nav', '1');
        document.head.appendChild(clone);
      });
    }
    if(mainEl){
      mainEl.querySelectorAll('style').forEach(function(style){
        var clone = style.cloneNode(true);
        clone.setAttribute('data-de-soft-nav', '1');
        document.head.appendChild(clone);
      });
    }
    // Remove previous page inline styles only after new ones are attached (avoids FOUC/line flashes).
    oldSoftStyles.forEach(function(el){
      if(el.parentNode) el.parentNode.removeChild(el);
    });
    return { addedLinks: addedLinks, staleLinks: staleLinks };
  }

  function waitForStylesheets(links, timeoutMs){
    if(!links || !links.length) return Promise.resolve();
    /* Destination CSS is warmed as real stylesheets during prefetch. Cap the
       swap wait so a cold sheet cannot freeze the old module for seconds. */
    var limit = timeoutMs == null ? 160 : timeoutMs;
    function sheetReady(link){
      try{
        if(link.sheet) return true;
      } catch(e){}
      return false;
    }
    function waitOne(link){
      return new Promise(function(resolve){
        if(sheetReady(link)){ resolve(); return; }
        var settled = false;
        var timer = null;
        function finish(){
          if(settled) return;
          settled = true;
          if(timer) clearInterval(timer);
          resolve();
        }
        link.addEventListener('load', finish, { once: true });
        link.addEventListener('error', finish, { once: true });
        var polls = 0;
        timer = setInterval(function(){
          polls++;
          if(sheetReady(link) || polls > 100) finish();
        }, 20);
      });
    }
    var allReady = Promise.all(links.map(waitOne)).then(function(){ return 'ready'; });
    var timedOut = new Promise(function(resolve){ setTimeout(function(){ resolve('timeout'); }, limit); });
    return Promise.race([allReady, timedOut]);
  }

  function scriptPathname(src){
    if(!src) return '';
    try{
      return new URL(src, window.location.href).pathname;
    } catch(e){
      return String(src).split('?')[0];
    }
  }

  function loadExternalScript(old){
    return new Promise(function(resolve){
      var src = old.getAttribute('src') || '';
      var path = scriptPathname(src);
      var loaded = window.__deSoftNavScripts = window.__deSoftNavScripts || {};
      /* Drop older ?v= copies of the same file so the latest IIFE wins. */
      if(path){
        Array.from(document.querySelectorAll('script[src]')).forEach(function(el){
          var existing = el.getAttribute('src') || '';
          if(!existing || existing === src) return;
          if(scriptPathname(existing) !== path) return;
          try{
            if(el.parentNode) el.parentNode.removeChild(el);
          } catch(err){}
          try{ delete loaded[existing]; } catch(err2){}
        });
      }
      var external = document.createElement('script');
      Array.from(old.attributes).forEach(function(attr){
        external.setAttribute(attr.name, attr.value);
      });
      external.onload = external.onerror = function(){ resolve(); };
      document.body.appendChild(external);
    });
  }

  /** Load destination external scripts while the previous page stays visible. */
  function preloadExternalScripts(scriptNodes, done){
    var loaded = window.__deSoftNavScripts = window.__deSoftNavScripts || {};
    var pending = [];
    (scriptNodes || []).forEach(function(old){
      if(shouldSkipScript(old)) return;
      var src = old.getAttribute('src');
      if(!src || loaded[src]) return;
      loaded[src] = true;
      pending.push(loadExternalScript(old));
    });
    if(!pending.length){
      if(typeof done === 'function') done();
      return;
    }
    /* Cap wait so slow CF revalidation cannot freeze soft-nav before paint. */
    Promise.race([
      Promise.all(pending),
      new Promise(function(resolve){ setTimeout(resolve, 900); })
    ]).then(function(){
      if(typeof done === 'function') done();
    }).catch(function(){
      if(typeof done === 'function') done();
    });
  }

  function runScriptNodes(scriptNodes, done){
    var loaded = window.__deSoftNavScripts = window.__deSoftNavScripts || {};
    var index = 0;

    function next(){
      while(index < scriptNodes.length && shouldSkipScript(scriptNodes[index])){
        index++;
      }
      if(index >= scriptNodes.length){
        done();
        return;
      }

      var batch = [];
      while(index < scriptNodes.length){
        var candidate = scriptNodes[index];
        if(shouldSkipScript(candidate)){
          index++;
          continue;
        }
        var candidateSrc = candidate.getAttribute('src');
        if(!candidateSrc) break;
        if(loaded[candidateSrc] && !shouldRerunScript(candidate)){
          index++;
          continue;
        }
        batch.push(candidate);
        index++;
      }

      if(batch.length){
        Promise.race([
          Promise.all(batch.map(function(old){
            var src = old.getAttribute('src');
            loaded[src] = true;
            return loadExternalScript(old);
          })),
          new Promise(function(resolve){ setTimeout(resolve, 1200); })
        ]).then(next);
        return;
      }

      var old = scriptNodes[index++];
      if(!old){
        done();
        return;
      }
      if(shouldSkipScript(old)){
        next();
        return;
      }
      var src = old.getAttribute('src');
      if(src){
        if(loaded[src] && !shouldRerunScript(old)){
          next();
          return;
        }
        loaded[src] = true;
        Promise.race([
          loadExternalScript(old),
          new Promise(function(resolve){ setTimeout(resolve, 1200); })
        ]).then(next);
        return;
      }
      try{
        var inline = document.createElement('script');
        inline.text = old.textContent;
        document.body.appendChild(inline);
      } catch(e){}
      next();
    }

    next();
  }

  function isExecutableScript(node){
    if(!node || node.nodeName !== 'SCRIPT') return false;
    var type = (node.getAttribute('type') || '').trim().toLowerCase();
    if(!type) return true;
    return (
      type === 'text/javascript'
      || type === 'application/javascript'
      || type === 'module'
      || type === 'text/ecmascript'
      || type === 'application/ecmascript'
    );
  }

  function extractNestedScripts(element, scripts){
    if(!element || element.nodeType !== 1) return;
    Array.from(element.querySelectorAll('script')).forEach(function(scriptEl){
      if(!isExecutableScript(scriptEl)) return;
      scripts.push(scriptEl.cloneNode(true));
      if(scriptEl.parentNode) scriptEl.parentNode.removeChild(scriptEl);
    });
  }

  function collectNodesAndScripts(rootEl){
    var scripts = [];
    var nodes = [];
    Array.from(rootEl.childNodes).forEach(function(node){
      if(isExecutableScript(node)){
        scripts.push(node);
      } else if(node.nodeType === 1 || node.nodeType === 3){
        if(node.nodeType === 3 && !String(node.textContent || '').trim()) return;
        if(node.nodeType === 1) extractNestedScripts(node, scripts);
        nodes.push(node);
      }
    });
    return { nodes: nodes, scripts: scripts };
  }

  function collectBodyContent(sourceBody){
    var scripts = [];
    var nodes = [];
    if(!sourceBody) return { nodes: nodes, scripts: scripts };
    Array.from(sourceBody.childNodes).forEach(function(node){
      if(isExecutableScript(node)){
        scripts.push(node);
      } else if(node.nodeType === 1 && node.id === 'de-fs-app'){
        Array.from(node.childNodes).forEach(function(child){
          if(isExecutableScript(child)) scripts.push(child);
          else if(child.nodeType === 1 || child.nodeType === 3){
            if(child.nodeType === 3 && !String(child.textContent || '').trim()) return;
            if(child.nodeType === 1) extractNestedScripts(child, scripts);
            nodes.push(child);
          }
        });
      } else if(node.nodeType === 1 || node.nodeType === 3){
        if(node.nodeType === 3 && !String(node.textContent || '').trim()) return;
        if(node.nodeType === 1) extractNestedScripts(node, scripts);
        nodes.push(node);
      }
    });
    return { nodes: nodes, scripts: scripts };
  }

  var OPEN_NAV_GROUPS_KEY = 'de-nav-open-groups';

  function navLinkPathname(href){
    if(!href) return '';
    try{
      return new URL(href, window.location.origin).pathname;
    } catch(e){
      return String(href).split('?')[0];
    }
  }

  /** Path + search so /access-management and /access-management?focus=form stay distinct. */
  function navLinkKey(href){
    if(!href) return '';
    try{
      var url = new URL(href, window.location.origin);
      return url.pathname + url.search;
    } catch(e){
      return String(href);
    }
  }

  function findSidebarLink(sidebar, nextLink){
    if(!sidebar || !nextLink) return null;
    var id = nextLink.id;
    if(id){
      var byId = document.getElementById(id);
      if(byId && sidebar.contains(byId)) return byId;
    }
    var href = nextLink.getAttribute('href') || '';
    var key = navLinkKey(href);
    if(!key) return null;
    var candidates = sidebar.querySelectorAll('a.de-nav-subitem, a.de-nav-item');
    for(var i = 0; i < candidates.length; i++){
      if(navLinkKey(candidates[i].getAttribute('href') || '') === key){
        return candidates[i];
      }
    }
    // Period filters change ?year=&month=; match by pathname inside the same group.
    var group = nextLink.closest('.de-nav-group');
    var groupId = group && group.id;
    var curGroup = groupId ? document.getElementById(groupId) : null;
    if(curGroup && sidebar.contains(curGroup)){
      var path = navLinkPathname(href);
      if(path){
        var groupLinks = curGroup.querySelectorAll('a.de-nav-subitem, a.de-nav-item');
        var pathMatches = [];
        for(var j = 0; j < groupLinks.length; j++){
          if(navLinkPathname(groupLinks[j].getAttribute('href') || '') === path){
            pathMatches.push(groupLinks[j]);
          }
        }
        if(pathMatches.length === 1) return pathMatches[0];
        var label = (nextLink.textContent || '').replace(/\s+/g, ' ').trim().toLowerCase();
        for(var k = 0; k < pathMatches.length; k++){
          var curLabel = (pathMatches[k].textContent || '').replace(/\s+/g, ' ').trim().toLowerCase();
          if(curLabel === label) return pathMatches[k];
        }
      }
    }
    return null;
  }

  /** Remove duplicate subitems created by older soft-nav merges (same id or same path+label). */
  function dedupeSidebarSubitems(sidebar){
    if(!sidebar) return;
    sidebar.querySelectorAll('.de-nav-sub').forEach(function(sub){
      var seenIds = {};
      var seenKeys = {};
      Array.from(sub.querySelectorAll('a.de-nav-subitem')).forEach(function(link){
        var id = link.id || '';
        if(id){
          if(seenIds[id]){
            link.remove();
            return;
          }
          seenIds[id] = true;
          return;
        }
        var path = navLinkPathname(link.getAttribute('href') || '');
        var label = (link.textContent || '').replace(/\s+/g, ' ').trim().toLowerCase();
        var key = path + '|' + label;
        if(seenKeys[key]){
          link.remove();
          return;
        }
        seenKeys[key] = true;
      });
    });
  }

  function persistOpenNavGroups(sidebar){
    sidebar = sidebar || document.querySelector('#de-sidebar, .de-sidebar');
    if(!sidebar) return;
    var ids = [];
    sidebar.querySelectorAll('.de-nav-group.is-open').forEach(function(group){
      if(group.id) ids.push(group.id);
    });
    /* Accordion: only one top-level module may stay expanded. */
    if(ids.length > 1) ids = [ids[ids.length - 1]];
    try{
      sessionStorage.setItem(OPEN_NAV_GROUPS_KEY, JSON.stringify(ids));
    } catch(e){}
  }

  function restoreOpenNavGroups(sidebar){
    sidebar = sidebar || document.querySelector('#de-sidebar, .de-sidebar');
    if(!sidebar) return;
    var ids = [];
    try{
      ids = JSON.parse(sessionStorage.getItem(OPEN_NAV_GROUPS_KEY) || '[]') || [];
    } catch(e){
      ids = [];
    }
    if(!Array.isArray(ids)) ids = [];
    var preferredId = '';
    try{
      var locPath = window.location.pathname || '';
      sidebar.querySelectorAll('a.de-nav-subitem.is-active, a.de-nav-subitem[aria-current="page"]').forEach(function(link){
        if(preferredId) return;
        if(navLinkPathname(link.getAttribute('href') || '') === locPath){
          var matchedGroup = link.closest('.de-nav-group');
          if(matchedGroup && matchedGroup.id) preferredId = matchedGroup.id;
        }
      });
    } catch(ePref){}
    if(!preferredId){
      var activeGroup = sidebar.querySelector('.de-nav-group.is-child-active');
      preferredId = activeGroup && activeGroup.id ? activeGroup.id : '';
    }
    if(!preferredId){
      // Accordion: restore at most one persisted group (most recent).
      for(var i = ids.length - 1; i >= 0; i--){
        if(!ids[i]) continue;
        var persisted = document.getElementById(ids[i]);
        if(persisted && sidebar.contains(persisted)){
          preferredId = ids[i];
          break;
        }
      }
    }
    sidebar.querySelectorAll('.de-nav-group').forEach(function(group){
      if(!group.id) return;
      var shouldOpen = preferredId ? group.id === preferredId : group.classList.contains('is-child-active');
      group.classList.toggle('is-open', shouldOpen);
      if(!shouldOpen) group.classList.remove('is-flyout-active');
      var toggle = group.querySelector('.de-nav-group-toggle');
      if(toggle) toggle.setAttribute('aria-expanded', shouldOpen ? 'true' : 'false');
    });
  }

  /**
   * Pull any new nav links from the destination page into the live sidebar
   * without replacing the whole nav (keeps open sections / scroll / pin state).
   * Needed when modules are added mid-session (e.g. Tips) while soft-nav
   * keeps the previous sidebar DOM.
   */
  function sidebarElById(sidebar, id){
    if(!sidebar || !id) return null;
    var el = document.getElementById(id);
    return (el && sidebar.contains(el)) ? el : null;
  }

  function pruneRemovedSidebarLinks(sidebar){
    sidebar = sidebar || document.querySelector('#de-sidebar, .de-sidebar');
    if(!sidebar) return;
    /* Outlet Settings live under the main Settings hub only — drop legacy module links. */
    [
      'de-nav-pos-settings',
      'de-nav-bar-pos-settings',
      'de-nav-hotel-settings'
    ].forEach(function(id){
      var el = document.getElementById(id);
      if(el && sidebar.contains(el) && el.parentNode) el.parentNode.removeChild(el);
    });
  }

  function mergeMissingSidebarLinks(curSidebar, nextSidebar){
    if(!curSidebar || !nextSidebar) return false;
    var addedAny = false;
    var curNav = curSidebar.querySelector('.de-sb-nav');
    var nextNav = nextSidebar.querySelector('.de-sb-nav');
    if(curNav && nextNav){
      Array.from(nextNav.children).forEach(function(nextNode){
        if(!nextNode.id) return;
        /* Scope to the live sidebar — ignore hidden soft-nav merge snapshots. */
        if(sidebarElById(curSidebar, nextNode.id)) return;
        var imported = document.importNode(nextNode, true);
        imported.querySelectorAll('a.is-active, a[aria-current="page"]').forEach(function(a){
          a.classList.remove('is-active');
          a.removeAttribute('aria-current');
        });
        if(imported.classList && imported.classList.contains('de-nav-group')){
          imported.classList.remove('is-open', 'is-child-active', 'is-flyout-active');
          var toggle = imported.querySelector('.de-nav-group-toggle');
          if(toggle) toggle.setAttribute('aria-expanded', 'false');
        }
        var placed = false;
        var prev = nextNode.previousElementSibling;
        while(prev){
          var curPrev = prev.id ? sidebarElById(curSidebar, prev.id) : null;
          if(curPrev && curNav.contains(curPrev)){
            curPrev.insertAdjacentElement('afterend', imported);
            placed = true;
            break;
          }
          prev = prev.previousElementSibling;
        }
        if(!placed){
          var next = nextNode.nextElementSibling;
          while(next){
            var curNext = next.id ? sidebarElById(curSidebar, next.id) : null;
            if(curNext && curNav.contains(curNext)){
              curNext.insertAdjacentElement('beforebegin', imported);
              placed = true;
              break;
            }
            next = next.nextElementSibling;
          }
        }
        if(!placed) curNav.appendChild(imported);
        addedAny = true;
      });
    }
    nextSidebar.querySelectorAll('.de-nav-group').forEach(function(nextGroup){
      if(!nextGroup.id) return;
      var curGroup = document.getElementById(nextGroup.id);
      if(!curGroup || !curSidebar.contains(curGroup)) return;
      var curSub = curGroup.querySelector('.de-nav-sub');
      var nextSub = nextGroup.querySelector('.de-nav-sub');
      if(!curSub || !nextSub) return;

      nextSub.querySelectorAll('a.de-nav-subitem').forEach(function(nextLink){
        var existing = findSidebarLink(curSidebar, nextLink);
        if(existing){
          var nextHref = nextLink.getAttribute('href');
          if(nextHref) existing.setAttribute('href', nextHref);
          return;
        }
        var imported = document.importNode(nextLink, true);
        imported.classList.remove('is-active');
        imported.removeAttribute('aria-current');

        var placed = false;
        var prev = nextLink.previousElementSibling;
        while(prev){
          var curPrev = findSidebarLink(curSidebar, prev);
          if(curPrev && curSub.contains(curPrev)){
            curPrev.insertAdjacentElement('afterend', imported);
            placed = true;
            break;
          }
          prev = prev.previousElementSibling;
        }
        if(!placed){
          var next = nextLink.nextElementSibling;
          while(next){
            var curNext = findSidebarLink(curSidebar, next);
            if(curNext && curSub.contains(curNext)){
              curNext.insertAdjacentElement('beforebegin', imported);
              placed = true;
              break;
            }
            next = next.nextElementSibling;
          }
        }
        if(!placed) curSub.appendChild(imported);
        addedAny = true;
      });
    });
    // Tips moved from Sales Analytics → Employee Payroll; drop the old link if present.
    var legacyTips = document.getElementById('de-nav-sales-tips');
    if(legacyTips) legacyTips.remove();
    // Point of Sale became a nav group; drop the old flat launcher link.
    var legacyPos = document.getElementById('de-nav-point-of-sale');
    if(legacyPos && legacyPos.tagName === 'A' && document.getElementById('de-nav-pos-group')){
      legacyPos.remove();
    }
    return addedAny;
  }

  /**
   * Keep the left nav DOM stable across soft navigations.
   * Only sync active/current page state and open the destination section —
   * never replace .de-sb-nav (that collapses other sections and drops items
   * the user still needs, e.g. Sales Analytics → Credit while on Payroll).
   */
    function syncSidebarActiveFromUrl(url){
    var curSidebar = document.querySelector('#de-sidebar, .de-sidebar');
    if(!curSidebar || !url) return;

    persistOpenNavGroups(curSidebar);

    curSidebar.querySelectorAll('a.is-active, a[aria-current="page"], .de-nav-item.is-active').forEach(function(el){
      el.classList.remove('is-active');
      el.removeAttribute('aria-current');
    });
    curSidebar.querySelectorAll('.de-nav-group.is-child-active').forEach(function(group){
      group.classList.remove('is-child-active');
    });

    /* Reports hub drill-ins (?from_hub=reports) stay on Report — never jump to the
       destination module (e.g. Menu & Margin → Restaurant POS). */
    try{
      var hubTarget = new URL(url, window.location.origin);
      if((hubTarget.searchParams.get('from_hub') || '').toLowerCase() === 'reports'){
        var reportHome =
          curSidebar.querySelector('#de-nav-report-home') ||
          curSidebar.querySelector('#de-nav-report-group a.de-nav-subitem');
        if(reportHome){
          reportHome.classList.add('is-active');
          reportHome.setAttribute('aria-current', 'page');
          var reportGroup = reportHome.closest('.de-nav-group');
          if(reportGroup){
            reportGroup.classList.add('is-open', 'is-child-active');
            var reportToggle = reportGroup.querySelector('.de-nav-group-toggle');
            if(reportToggle) reportToggle.setAttribute('aria-expanded', 'true');
          }
          restoreOpenNavGroups(curSidebar);
          persistOpenNavGroups(curSidebar);
          return;
        }
      }
    } catch(eHub){}

    var key = navLinkKey(url);
    var path = navLinkPathname(url);
    var candidates = curSidebar.querySelectorAll('a.de-nav-subitem, a.de-nav-item');
    var match = null;
    var pathMatches = [];
    for(var i = 0; i < candidates.length; i++){
      var href = candidates[i].getAttribute('href') || '';
      if(key && navLinkKey(href) === key){
        match = candidates[i];
        break;
      }
      if(path && navLinkPathname(href) === path){
        pathMatches.push(candidates[i]);
      }
    }
    if(!match && pathMatches.length === 1) match = pathMatches[0];
    if(!match && pathMatches.length > 1){
      // Prefer the link whose search params overlap most with the target.
      var bestScore = -1;
      try{
        var target = new URL(url, window.location.origin);
        pathMatches.forEach(function(link){
          var linkUrl = new URL(link.getAttribute('href') || '', window.location.origin);
          var score = 0;
          linkUrl.searchParams.forEach(function(value, name){
            if(target.searchParams.get(name) === value) score += 1;
          });
          if(score > bestScore){
            bestScore = score;
            match = link;
          }
        });
      } catch(e){
        match = pathMatches[0];
      }
    }
    if(!match){
      restoreOpenNavGroups(curSidebar);
      return;
    }

    match.classList.add('is-active');
    match.setAttribute('aria-current', 'page');
    var group = match.closest('.de-nav-group');
    if(group){
      group.classList.add('is-open', 'is-child-active');
      var toggle = group.querySelector('.de-nav-group-toggle');
      if(toggle) toggle.setAttribute('aria-expanded', 'true');
    }
    restoreOpenNavGroups(curSidebar);
    persistOpenNavGroups(curSidebar);
  }

  function syncSidebarFromDoc(doc, url){
    var curSidebar = document.querySelector('#de-sidebar, .de-sidebar');
    var nextSidebar =
      doc.querySelector('#de-sidebar, .de-sidebar') ||
      (doc.querySelector('[data-de-soft-nav-merge-root] #de-sidebar') || null);
    if(!curSidebar) return;
    if(!nextSidebar){
      syncSidebarActiveFromUrl(url || window.location.href);
      return;
    }

    persistOpenNavGroups(curSidebar);
    mergeMissingSidebarLinks(curSidebar, nextSidebar);
    pruneRemovedSidebarLinks(curSidebar);
    dedupeSidebarSubitems(curSidebar);

    curSidebar.querySelectorAll('a.is-active, a[aria-current="page"], .de-nav-item.is-active').forEach(function(el){
      el.classList.remove('is-active');
      el.removeAttribute('aria-current');
    });
    curSidebar.querySelectorAll('.de-nav-group.is-child-active').forEach(function(group){
      group.classList.remove('is-child-active');
    });

    nextSidebar.querySelectorAll('a.is-active, a[aria-current="page"]').forEach(function(a){
      var match = findSidebarLink(curSidebar, a);
      if(!match) return;
      var nextHref = a.getAttribute('href');
      if(nextHref) match.setAttribute('href', nextHref);
      match.classList.add('is-active');
      match.setAttribute('aria-current', 'page');
      var group = match.closest('.de-nav-group');
      if(group){
        group.classList.add('is-open', 'is-child-active');
        var toggle = group.querySelector('.de-nav-group-toggle');
        if(toggle) toggle.setAttribute('aria-expanded', 'true');
      }
    });

    restoreOpenNavGroups(curSidebar);
    persistOpenNavGroups(curSidebar);
  }

  function scrollMainToTop(){
    // Only the right-panel scroller — never a nested .main-wrapper or the sidebar.
    var main = document.querySelector('.de-main-wrapper');
    if(main) main.scrollTop = 0;
    var nested = main && main.querySelector('.de-main-scroll');
    if(nested) nested.scrollTop = 0;
    try{ window.scrollTo({ top: 0, left: 0, behavior: 'auto' }); }
    catch(e){ window.scrollTo(0, 0); }
  }

  /** Prefer restoring Reports hub scroll (Sales / Restaurant / Bar) over jumping to top. */
  function scrollMainAfterSoftNav(url){
    try{
      var path = new URL(url, window.location.href).pathname.replace(/\/$/, '') || '/';
      if(path === '/reports' && typeof window.deRestoreReportsHubScroll === 'function'){
        if(window.deRestoreReportsHubScroll()) return;
      }
    } catch(e){}
    scrollMainToTop();
  }

  var SIDEBAR_SCROLL_KEY = 'de-sidebar-nav-scroll';
  var lockedSidebarScroll = null;
  var sidebarScrollLockTimer = null;
  var sidebarScrollLockUntil = 0;
  var sidebarScrollReleaseTimer = null;

  function readStoredSidebarScroll(){
    try{
      var raw = sessionStorage.getItem(SIDEBAR_SCROLL_KEY);
      if(!raw) return null;
      var parsed = JSON.parse(raw);
      if(!parsed || typeof parsed !== 'object') return null;
      return {
        sidebarTop: typeof parsed.sidebarTop === 'number' ? parsed.sidebarTop : 0,
        navTop: typeof parsed.navTop === 'number' ? parsed.navTop : 0
      };
    } catch(e){
      return null;
    }
  }

  function captureSidebarScroll(){
    var sidebar = document.querySelector('#de-sidebar, .de-sidebar');
    if(!sidebar) return lockedSidebarScroll || readStoredSidebarScroll();
    var nav = sidebar.querySelector('.de-sb-nav');
    return {
      sidebarTop: sidebar.scrollTop || 0,
      navTop: nav ? (nav.scrollTop || 0) : 0
    };
  }

  function restoreSidebarScroll(snapshot){
    snapshot = snapshot || lockedSidebarScroll || readStoredSidebarScroll();
    if(!snapshot) return;
    var sidebar = document.querySelector('#de-sidebar, .de-sidebar');
    if(!sidebar) return;
    var nav = sidebar.querySelector('.de-sb-nav');
    if(typeof snapshot.sidebarTop === 'number'){
      sidebar.scrollTop = snapshot.sidebarTop;
    }
    if(nav && typeof snapshot.navTop === 'number'){
      nav.scrollTop = snapshot.navTop;
    }
  }

  function isSidebarScrollLocked(){
    return !!(lockedSidebarScroll && (window.__deSoftNavInProgress || Date.now() <= sidebarScrollLockUntil));
  }

  function isSidebarExpandedForScroll(){
    var sidebar = document.querySelector('#de-sidebar, .de-sidebar');
    if(!sidebar) return false;
    if(sidebar.classList.contains('is-expanded') || sidebar.classList.contains('is-pinned')) return true;
    try{ return sidebar.matches(':hover'); } catch(e){ return false; }
  }

  function onSidebarScrollLockEvent(event){
    if(!isSidebarScrollLocked()) return;
    if(isSidebarExpandedForScroll()) return;
    var target = event && event.target;
    if(!target) return;
    var sidebar = document.querySelector('#de-sidebar, .de-sidebar');
    if(!sidebar) return;
    var nav = sidebar.querySelector('.de-sb-nav');
    if(target !== sidebar && target !== nav) return;
    restoreSidebarScroll(lockedSidebarScroll);
  }

  function rememberSidebarScrollForNav(){
    lockedSidebarScroll = captureSidebarScroll();
    return lockedSidebarScroll;
  }

  function clearSidebarScrollLock(){
    lockedSidebarScroll = null;
    sidebarScrollLockUntil = 0;
    if(sidebarScrollLockTimer){
      clearInterval(sidebarScrollLockTimer);
      sidebarScrollLockTimer = null;
    }
    if(sidebarScrollReleaseTimer){
      clearTimeout(sidebarScrollReleaseTimer);
      sidebarScrollReleaseTimer = null;
    }
  }

  function lockSidebarScroll(snapshot){
    lockedSidebarScroll = snapshot || lockedSidebarScroll || captureSidebarScroll();
    if(!lockedSidebarScroll) return;
    sidebarScrollLockUntil = Date.now() + 900;
    if(sidebarScrollReleaseTimer){
      clearTimeout(sidebarScrollReleaseTimer);
      sidebarScrollReleaseTimer = null;
    }
    if(!window.__deSidebarScrollLockBound){
      window.__deSidebarScrollLockBound = true;
      document.addEventListener('scroll', onSidebarScrollLockEvent, true);
    }
    restoreSidebarScroll(lockedSidebarScroll);
  }

  function releaseSidebarScrollLock(delayMs){
    if(sidebarScrollReleaseTimer) clearTimeout(sidebarScrollReleaseTimer);
    sidebarScrollReleaseTimer = setTimeout(function(){
      sidebarScrollReleaseTimer = null;
      clearSidebarScrollLock();
      /* Do NOT preflightActiveNavScroll here. Expanding the live rail (even with
         visibility:hidden) still changes flex width and makes the unpinned panel
         open/close a second time after soft-nav. Scroll cache is already warmed
         while the user hovered/clicked the nav. */
    }, typeof delayMs === 'number' ? delayMs : 0);
  }

  function restoreSidebarScrollAfterLayout(snapshot){
    if(snapshot) lockedSidebarScroll = snapshot;
    sidebarScrollLockUntil = Math.max(sidebarScrollLockUntil, Date.now() + 600);
  }

  function setSoftNavFlag(active){
    window.__deSoftNavInProgress = !!active;
    if(active && window._deSidebarCollapseTimer){
      clearTimeout(window._deSidebarCollapseTimer);
      window._deSidebarCollapseTimer = null;
    }
    if(window.deFullscreen && typeof window.deFullscreen.setSoftNavInProgress === 'function'){
      window.deFullscreen.setSoftNavInProgress(!!active);
    }
    if(!active){
      sidebarScrollLockUntil = Math.max(sidebarScrollLockUntil, Date.now() + 200);
      /* If the pointer is still on the unpinned rail, keep it expanded and skip
         hover-suppress. Forcing collapse while :hover is true shrinks the hit
         area under the cursor → mouseleave → later re-expand (double open/close). */
      var sbEnd = document.querySelector('#de-sidebar, .de-sidebar');
      var keepHoverExpand = false;
      try{
        keepHoverExpand = !!(sbEnd && !sbEnd.classList.contains('is-pinned') && sbEnd.matches(':hover'));
      } catch(eHover){
        keepHoverExpand = false;
      }
      if(keepHoverExpand){
        sbEnd.classList.add('is-expanded');
      } else if(typeof window.suppressSidebarHoverExpand === 'function'){
        window.suppressSidebarHoverExpand(220);
      }
      releaseSidebarScrollLock(400);
      if(typeof window.syncDeSidebarPointerState === 'function'){
        window.requestAnimationFrame(function(){
          window.syncDeSidebarPointerState();
        });
      }
    }
  }

  function clearNavigatingLinks(){
    document.querySelectorAll('a.is-navigating').forEach(function(el){
      el.classList.remove('is-navigating');
    });
  }

  /** Session-ending routes must not hard-nav while fullscreen — that always
   *  exits the Fullscreen API. Prefetch GET /logout still must not clear the
   *  session; a real click uses POST (see logoutWhileKeepingFullscreen). */
  function isLogoutUrl(url){
    try{
      var path = new URL(url, window.location.href).pathname.replace(/\/$/, '') || '/';
      return path === '/logout';
    } catch(e){
      return false;
    }
  }

  function shouldKeepFullscreen(){
    return isFullscreenActive() || isFullscreenPreferred();
  }

  function keepFullscreenGesture(){
    if(window.deFullscreen && typeof window.deFullscreen.armForSoftNav === 'function'){
      window.deFullscreen.armForSoftNav();
    }
    if(window.deFullscreen && typeof window.deFullscreen.preserveForNavigation === 'function'){
      window.deFullscreen.preserveForNavigation();
    } else if(window.deFullscreen && typeof window.deFullscreen.ensureRoot === 'function'){
      window.deFullscreen.ensureRoot();
    }
  }

  /**
   * Replace #de-fs-app contents (never remove the fullscreen element / <html>)
   * so Sign In / full-document shells can paint without exiting fullscreen.
   */
  function swapDocumentInsideFullscreen(doc, url, done, navToken){
    if(navToken != null && !isCurrentSoftNav(navToken)) return;
    if(typeof window.closeMasterModal === 'function'){
      try{ window.closeMasterModal(); } catch(eModal){}
    }
    if(window.deFullscreen && typeof window.deFullscreen.ensureRoot === 'function'){
      window.deFullscreen.ensureRoot();
    }
    keepFullscreenGesture();
    var host = document.getElementById('de-fs-app') || document.body;
    var nextBodyClass = (doc.body && doc.body.className) ? doc.body.className : '';
    var nextTitle = doc.title || '';
    var mergedAssets = mergeHeadAssets(doc, doc.body);
    var addedLinks = mergedAssets.addedLinks || [];
    var staleLinks = mergedAssets.staleLinks || [];
    var content = collectBodyContent(doc.body);
    var frag = document.createDocumentFragment();
    content.nodes.forEach(function(node){
      if(node.nodeType === 1 && node.tagName === 'LINK' && (node.getAttribute('rel') || '') === 'stylesheet'){
        return;
      }
      if(node.nodeType === 1 && node.tagName === 'STYLE') return;
      if(node.nodeType === 1 && node.id === 'de-fs-app') return;
      frag.appendChild(document.importNode(node, true));
    });

    var finishSwap = function(){
      if(navToken != null && !isCurrentSoftNav(navToken)) return;
      document.documentElement.classList.add('de-soft-navigating');
      if(nextTitle) document.title = nextTitle;
      if(nextBodyClass) document.body.className = nextBodyClass;
      if(typeof host.replaceChildren === 'function'){
        host.replaceChildren(frag);
      } else {
        while(host.firstChild) host.removeChild(host.firstChild);
        host.appendChild(frag);
      }
      dropStaleWhenReady(staleLinks, addedLinks);
      var syncUrl = urlWithPosSettingsSection(url);
      try{
        var current = new URL(window.location.href);
        var next = new URL(syncUrl, window.location.href);
        if(current.pathname !== next.pathname || current.search !== next.search || current.hash !== next.hash){
          keepFullscreenGesture();
          history.replaceState({ deSoftNav: true }, '', syncUrl);
          keepFullscreenGesture();
        }
      } catch(eSync){}
      keepFullscreenGesture();
      runScriptNodes(content.scripts, function(){
        if(navToken != null && !isCurrentSoftNav(navToken)) return;
        try{
          finalizeSoftNav();
        } catch(err){
          try{ console.error('de fullscreen document swap failed', err); } catch(eLog){}
        } finally {
          markMainLoading(false);
          finishSoftNavUi(done, navToken);
          endSoftNavigatingClass();
          keepFullscreenGesture();
        }
      });
    };

    waitForStylesheets(addedLinks).then(finishSwap);
  }

  function logoutWhileKeepingFullscreen(url){
    var logoutUrl = url || '/logout';
    var nav = beginSoftNavGeneration();
    setSoftNavFlag(true);
    markMainLoading(true);
    document.documentElement.classList.add('de-soft-nav-session');
    keepFullscreenGesture();
    if(window.deFullscreen && typeof window.deFullscreen.ensureRoot === 'function'){
      window.deFullscreen.ensureRoot();
    }
    /* pushState during the click — after fetch, the browser will not re-enter FS. */
    try{ history.pushState({ deSoftNav: true }, '', '/'); } catch(ePush){}
    keepFullscreenGesture();
    showSoftNavProgress();

    function finishOfflineLogout(){
      markMainLoading(false);
      setSoftNavFlag(false);
      hideSoftNavProgress();
      try{ sessionStorage.removeItem(NAV_FLAG); } catch(eFlag){}
      try{
        if(window.HbeOfflineAuth && typeof window.HbeOfflineAuth.clearOfflineSessionFlag === 'function'){
          window.HbeOfflineAuth.clearOfflineSessionFlag();
        } else {
          sessionStorage.removeItem('hbe_offline_session');
        }
      } catch(eSess){}
      /* `/static/offline_login.html` is the versioned offline Sign In shell. */
      window.location.replace('/static/offline_login.html?v=10');
    }

    if(typeof navigator !== 'undefined' && navigator.onLine === false){
      finishOfflineLogout();
      return;
    }

    fetch(logoutUrl, {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        Accept: 'text/html',
        'X-Requested-With': 'XMLHttpRequest',
        'X-De-Logout': '1'
      },
      redirect: 'follow',
      cache: 'no-store'
    }).then(function(response){
      if(!response.ok) throw new Error('logout failed');
      var contentType = (response.headers.get('content-type') || '').toLowerCase();
      if(contentType.indexOf('text/html') === -1) throw new Error('non-html logout response');
      return response.text().then(function(html){
        return { html: html, url: stripPartialParam(response.url || '/') };
      });
    }).then(function(result){
      if(!isCurrentSoftNav(nav.token)){
        markMainLoading(false);
        hideSoftNavProgress();
        return;
      }
      if(!result.html) throw new Error('empty logout html');
      keepFullscreenGesture();
      var doc = new DOMParser().parseFromString(result.html, 'text/html');
      swapDocumentInsideFullscreen(doc, result.url || '/', hideSoftNavProgress, nav.token);
    }).catch(function(){
      finishOfflineLogout();
    });
  }

  function handleLogoutLink(event, link){
    if(!link) return false;
    var href = link.href || link.getAttribute('href') || '';
    if(!isLogoutUrl(href)) return false;
    if(event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) return false;
    if(!shouldKeepFullscreen()) return false;
    event.preventDefault();
    event.stopPropagation();
    logoutWhileKeepingFullscreen(link.href || href);
    return true;
  }

  function finalizeSoftNav(){
    try{
      if(typeof window.reinitDeWorkspaceSidebar === 'function'){
        window.reinitDeWorkspaceSidebar();
      } else if(typeof window.applyDeSidebarBootState === 'function'){
        window.applyDeSidebarBootState();
      }
      if(window.deFullscreen && typeof window.deFullscreen.reinit === 'function'){
        window.deFullscreen.reinit();
      }
      if(window.deWorkspaceReinit){
        window.deWorkspaceReinit();
      } else {
        initDeSidebarPageTransitions();
      }
      if(window.deFullscreen && typeof window.deFullscreen.updateUi === 'function'){
        window.deFullscreen.updateUi();
      }
      // Restore while soft-nav flag is still set so accidental exits are not treated as user exits.
      if(window.deFullscreen && typeof window.deFullscreen.restoreAfterNavigation === 'function'){
        window.deFullscreen.restoreAfterNavigation();
      }
      if(typeof window.initHbeTableScroll === 'function'){
        window.initHbeTableScroll();
      }
      clearNavigatingLinks();
    } catch(err){
      try{ console.error('de soft-nav page reinit failed', err); } catch(eLog){}
      try{ clearNavigatingLinks(); } catch(eClear){}
    }
    // Keep soft-nav flag briefly so late fullscreenchange events do not clear the lock.
    setTimeout(function(){
      setSoftNavFlag(false);
      if(window.deFullscreen && typeof window.deFullscreen.updateUi === 'function'){
        window.deFullscreen.updateUi();
      }
    }, 120);
  }

  function prefersReducedMotion(){
    try{
      return !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
    } catch(e){
      return false;
    }
  }

  function playMainEnterReveal(main){
    if(main) main.classList.remove('de-main-enter');
  }

  function applySoftSwap(doc, url, done, sidebarScroll, navToken){
    if(!isCurrentSoftNav(navToken)) return;
    if(typeof window.closeMasterModal === 'function'){
      window.closeMasterModal();
    }
    var curMain = document.querySelector('.de-main-wrapper');
    var nextMain = doc.querySelector('.de-main-wrapper');
    if(!sidebarScroll) sidebarScroll = lockedSidebarScroll || captureSidebarScroll();
    lockSidebarScroll(sidebarScroll);

    var softTitle = nextMain && nextMain.getAttribute('data-de-page-title');
    var softBodyClass = nextMain && nextMain.getAttribute('data-de-body-class');
    var nextBodyClass = softBodyClass || ((doc.body && doc.body.className) ? doc.body.className : '');
    var nextTitle = softTitle || doc.title || '';
    /* Do NOT change body class / title before swap. Home (and others) scope CSS on
       body.home-module etc. — flipping body early while old DOM remains paints a
       plain gray box for the whole stylesheet-wait window (worst on first cold open). */
    var mergedAssets = mergeHeadAssets(doc, nextMain);
    var addedLinks = mergedAssets.addedLinks || [];
    var staleLinks = mergedAssets.staleLinks || [];
    syncSidebarFromDoc(doc, url);

    if(curMain && nextMain){
      var content = collectNodesAndScripts(nextMain);
      // Build off-DOM first; wait for new CSS; then swap in one shot under no veil.
      var frag = document.createDocumentFragment();
      content.nodes.forEach(function(node){
        /* Page CSS for true partials is lifted into <head>; do not leave <link> in main. */
        if(node.nodeType === 1 && node.tagName === 'LINK' && (node.getAttribute('rel') || '') === 'stylesheet'){
          return;
        }
        if(node.nodeType === 1 && node.tagName === 'STYLE'){
          return;
        }
        frag.appendChild(document.importNode(node, true));
      });

      var finishSwap = function(){
        if(!isCurrentSoftNav(navToken)) return;
        /* Paint DOM immediately. Do NOT preloadExternalScripts before runScriptNodes —
           that marks src as loaded and makes runScriptNodes skip waiting, so page
           inits (e.g. initPosTablesPage) can run before the script exists. */
        document.documentElement.classList.add('de-soft-navigating');
        if(nextTitle) document.title = nextTitle;
        if(nextBodyClass) document.body.className = nextBodyClass;
        if(typeof curMain.replaceChildren === 'function'){
          curMain.replaceChildren(frag);
        } else {
          while(curMain.firstChild) curMain.removeChild(curMain.firstChild);
          curMain.appendChild(frag);
        }
        dropStaleWhenReady(staleLinks, addedLinks);
        scrollMainAfterSoftNav(url);

        var syncUrl = urlWithPosSettingsSection(url);
        try{
          var current = new URL(window.location.href);
          var next = new URL(syncUrl, window.location.href);
          if(current.pathname !== next.pathname || current.search !== next.search || current.hash !== next.hash){
            history.replaceState({ deSoftNav: true }, '', syncUrl);
          }
        } catch(e){
          if(window.location.href !== syncUrl){
            try{ history.replaceState({ deSoftNav: true }, '', syncUrl); } catch(err){}
          }
        }
        runScriptNodes(content.scripts, function(){
          if(!isCurrentSoftNav(navToken)) return;
          try{
            finalizeSoftNav();
            restoreSidebarScrollAfterLayout(sidebarScroll);
          } catch(err){
            try{ console.error('de soft-nav finalize failed', err); } catch(eLog){}
          } finally {
            markMainLoading(false);
            finishSoftNavUi(done, navToken);
            endSoftNavigatingClass();
            try{ playMainEnterReveal(curMain); } catch(eReveal){}
            /* Re-warm common destinations after each open (prefetch is no longer one-shot). */
            try{ idlePrefetchSidebarDestinations(); } catch(e2){}
          }
        });
      };

      waitForStylesheets(addedLinks).then(finishSwap);
      return;
    }

    /* Login / missing-shell documents: keep <html> / #de-fs-app so fullscreen survives.
       Never paint a partial=main fragment here — that is only .de-main-wrapper and
       leaves Applications with no left panel until a hard refresh. */
    var nextHasShell = !!(
      doc.querySelector('#ep-workspace') ||
      doc.querySelector('.de-app-shell')
    );
    if(shouldKeepFullscreen()){
      if(nextMain && !nextHasShell){
        markMainLoading(false);
        setSoftNavFlag(false);
        document.documentElement.classList.remove('de-soft-navigating');
        hideSoftNavProgress();
        try{ sessionStorage.removeItem(NAV_FLAG); } catch(eFlag){}
        window.location.assign(stripPartialParam(url));
        return;
      }
      swapDocumentInsideFullscreen(doc, url, done, navToken);
      return;
    }

    // Do NOT wipe #de-fs-app / body — that exits browser fullscreen.
    // Fall back to a full navigation only when the shell structure is missing.
    throw new Error('missing main wrapper for soft nav');
  }

  function isEmbedFragmentUrl(url){
    try{
      var target = new URL(url, window.location.href);
      return target.searchParams.get('embed') === '1';
    } catch(e){
      return /(?:\?|&)embed=1(?:&|$)/.test(String(url || ''));
    }
  }

  function stripEmbedParam(url){
    try{
      var target = new URL(url, window.location.href);
      target.searchParams.delete('embed');
      return target.pathname + target.search + target.hash;
    } catch(e){
      return String(url || '').replace(/([?&])embed=1(&|$)/, function(_, sep, end){
        if(sep === '?' && end === '&') return '?';
        if(sep === '?' && !end) return '';
        return end || '';
      });
    }
  }

  function isMasterModalLink(link){
    if(!link || !link.closest) return false;
    // Full-page master shells (e.g. Employee Master) use .md-master-embed but
    // must soft-nav normally — only the Masters modal stays fragment-bound.
    if(link.closest('#md-master-modal, .md-master-modal, #md-master-modal-inject, #st-product-master-modal, #st-product-master-modal-inject')){
      return true;
    }
    if(link.closest('.md-master-embed--page-shell') && !link.closest('#md-master-modal, #st-product-master-modal')){
      return false;
    }
    return !!link.closest('.md-master-embed');
  }

  /** Pages may register leave flushes (e.g. POS invoice autosave) so dirty state
   *  is persisted before the main DOM is swapped away. Handlers may return a
   *  Promise; soft-nav waits (in parallel with HTML fetch) before applySoftSwap. */
  function runBeforeSoftNavHandlers(){
    var list = window.__deBeforeSoftNavHandlers;
    if(!list || !list.length) return Promise.resolve();
    return Promise.all(list.map(function(fn){
      try{
        return Promise.resolve(typeof fn === 'function' ? fn() : null).catch(function(){
          return null;
        });
      } catch(e){
        return Promise.resolve(null);
      }
    }));
  }

  function isBrowserOffline(){
    return typeof navigator !== 'undefined' && navigator.onLine === false;
  }

  function ensureShellOfflineChip(){
    var chip = document.getElementById('de-shell-offline-chip');
    if(chip) return chip;
    var shell = document.querySelector('.de-app-shell') || document.getElementById('ep-workspace') || document.body;
    if(!shell) return null;
    chip = document.createElement('div');
    chip.id = 'de-shell-offline-chip';
    chip.className = 'de-shell-offline-chip';
    chip.setAttribute('role', 'status');
    chip.setAttribute('aria-live', 'polite');
    chip.hidden = true;
    chip.textContent = 'Offline';
    shell.appendChild(chip);
    return chip;
  }

  function updateShellOfflineChip(){
    var chip = ensureShellOfflineChip();
    if(!chip) return;
    var offline = isBrowserOffline();
    chip.hidden = !offline;
    document.documentElement.classList.toggle('de-shell-is-offline', offline);
  }

  function notifyShellOffline(message){
    updateShellOfflineChip();
    var text = message || 'Offline — open this page once while online to use it offline.';
    var existing = document.getElementById('de-shell-offline-toast');
    if(existing && existing.parentNode) existing.parentNode.removeChild(existing);
    var toast = document.createElement('div');
    toast.id = 'de-shell-offline-toast';
    toast.className = 'de-shell-offline-toast';
    toast.setAttribute('role', 'status');
    toast.textContent = text;
    document.body.appendChild(toast);
    requestAnimationFrame(function(){
      toast.classList.add('is-in');
    });
    window.setTimeout(function(){
      toast.classList.remove('is-in');
      window.setTimeout(function(){
        if(toast.parentNode) toast.parentNode.removeChild(toast);
      }, 220);
    }, 4200);
  }

  function bindShellOfflineListeners(){
    if(window.__deShellOfflineBound) return;
    window.__deShellOfflineBound = true;
    window.addEventListener('online', updateShellOfflineChip);
    window.addEventListener('offline', function(){
      updateShellOfflineChip();
    });
    updateShellOfflineChip();
  }

  function softNavigate(url, done){
    var nav = beginSoftNavGeneration();
    setSoftNavFlag(true);
    markMainLoading(true);
    /* First soft-nav in a session previously lacked this class until after reveal,
       so opacity:0 enter styles could still paint a plain box on first module open. */
    document.documentElement.classList.add('de-soft-nav-session');
    var sidebarScroll = lockedSidebarScroll || captureSidebarScroll();
    lockSidebarScroll(sidebarScroll);
    if(window.deFullscreen && typeof window.deFullscreen.ensureRoot === 'function'){
      window.deFullscreen.ensureRoot();
    }

    var prefetched = takePrefetchedHtml(url);
    var fetchOpts = {
      credentials: 'same-origin',
      headers: {
        'Accept': 'text/html',
        'X-Requested-With': 'XMLHttpRequest',
        'X-De-Partial': 'main'
      },
      redirect: 'follow',
      cache: 'no-store'
    };
    if(!prefetched && nav.signal) fetchOpts.signal = nav.signal;

    /* Start leave saves immediately so they overlap the destination HTML fetch. */
    var leavePromise = runBeforeSoftNavHandlers();
    /* Tables: warm floor snapshot in parallel with HTML so first paint is not empty SSR. */
    var floorOutlet = (function(){
      try{
        var p = new URL(url, window.location.href).pathname || '';
        return p.indexOf('/bar-point-of-sale') === 0 ? 'bar' : 'restaurant';
      } catch(e){
        return 'restaurant';
      }
    })();
    var floorPromise = isPosTablesUrl(url) ? warmPosFloorSnapshot(nav.signal, floorOutlet) : Promise.resolve(null);

    /* SW network-first serves cached partial HTML when offline after a prior visit. */
    var htmlPromise = prefetched || fetch(withPartialMain(url), fetchOpts).then(function(response){
      if(!response.ok) throw new Error('soft nav failed');
      var contentType = (response.headers.get('content-type') || '').toLowerCase();
      if(contentType.indexOf('text/html') === -1){
        throw new Error('non-html response');
      }
      /* Follow redirects to the final document URL (e.g. finished Generate PO bounce). */
      var finalUrl = stripPartialParam(response.url || url);
      var redirected = !!response.redirected;
      return response.text().then(function(html){
        return { html: html, url: finalUrl, redirected: redirected };
      });
    });

    Promise.all([htmlPromise, leavePromise, floorPromise]).then(function(results){
      if(!isCurrentSoftNav(nav.token)){
        markMainLoading(false);
        hideSoftNavProgress();
        if(typeof done === 'function') done();
        return;
      }
      var payload = results[0];
      var html = typeof payload === 'string' ? payload : (payload && payload.html);
      var swapUrl = (payload && typeof payload === 'object' && payload.url) ? payload.url : url;
      if(!html) throw new Error('empty soft nav html');
      var parser = new DOMParser();
      var doc = parser.parseFromString(html, 'text/html');
      var authShell = false;
      try{
        var finalPath = new URL(swapUrl, window.location.href).pathname.replace(/\/$/, '') || '/';
        if(finalPath === '/' || finalPath === '/login') authShell = true;
      } catch(ePath){}
      if(!authShell && (doc.body && doc.body.classList.contains('login-page'))) authShell = true;
      if(authShell || !doc.querySelector('.de-main-wrapper')){
        if(shouldKeepFullscreen()){
          applySoftSwap(doc, swapUrl, done, sidebarScroll, nav.token);
          return;
        }
        throw new Error(authShell ? 'auth-shell' : 'missing main wrapper for soft nav');
      }
      applySoftSwap(doc, swapUrl, done, sidebarScroll, nav.token);
    }).catch(function(err){
      if(err && err.name === 'AbortError'){
        markMainLoading(false);
        hideSoftNavProgress();
        if(typeof done === 'function') done();
        return;
      }
      if(!isCurrentSoftNav(nav.token)){
        markMainLoading(false);
        hideSoftNavProgress();
        if(typeof done === 'function') done();
        return;
      }
      // Keep captured rail scroll in sessionStorage for hard-nav boot restore.
      if(sidebarScroll){
        try{ sessionStorage.setItem(SIDEBAR_SCROLL_KEY, JSON.stringify(sidebarScroll)); } catch(e){}
      }
      markMainLoading(false);
      setSoftNavFlag(false);
      document.documentElement.classList.remove('de-soft-navigating');
      hideSoftNavProgress();
      /* Disarm hard-nav #page-transition veil — soft-nav failure must not flash blank. */
      try{ sessionStorage.removeItem(NAV_FLAG); } catch(e){}
      if(typeof done === 'function') done();
      var errMsg = String(err && err.message || err || '');
      var authFail = errMsg.indexOf('auth-shell') !== -1;
      /* Auth redirect: do NOT hard-nav to the target (that paints Sign In and looks like logout).
         Restore the previous history entry so the user stays on the last good page. */
      if(authFail){
        try{ history.back(); } catch(eBack){}
        return;
      }
      /* Offline with no cached partial: keep sidebar, do not hard-nav into a blank error. */
      if(isBrowserOffline()){
        notifyShellOffline('Offline — open this page once while online to use it offline.');
        return;
      }
      // Soft-nav already pushState'd the target URL. Failing silently leaves a stale
      // page (month/year filters look broken until a manual refresh). Always hard-nav.
      window.location.href = url;
    });
  }

  function isPosInvoiceAppUrl(url){
    try{
      var path = new URL(url, window.location.href).pathname.replace(/\/$/, '') || '/';
      return path === '/point-of-sale/invoice' || path === '/bar-point-of-sale/invoice';
    } catch(e){
      return false;
    }
  }

  /** POS Create Invoice: fullscreen + unpinned rail for maximum billing space.
   *  Call from a user-gesture click so browsers allow requestFullscreen. */
  function applyPosInvoiceImmersiveMode(){
    try{
      if(typeof window.setDeSidebarPinned === 'function'){
        window.setDeSidebarPinned(false);
      } else {
        document.querySelectorAll('.de-sidebar').forEach(function(sb){
          sb.classList.remove('is-pinned', 'is-expanded');
        });
        try{ localStorage.setItem('de-sidebar-pinned', '0'); } catch(e0){}
      }
    } catch(e1){}
    try{
      if(window.deFullscreen && typeof window.deFullscreen.enter === 'function'){
        window.deFullscreen.enter().catch(function(){});
      }
    } catch(e2){}
  }

  function sameAppUrl(a, b){
    try{
      var ua = new URL(a, window.location.href);
      var ub = new URL(b, window.location.href);
      return ua.pathname === ub.pathname && ua.search === ub.search;
    } catch(e){
      return a === b;
    }
  }

  function navigateWithTransition(url){
    if(!url) return;
    // Masters modal fragments are shell-free — never soft-nav or hard-load them as pages.
    if(isEmbedFragmentUrl(url)){
      window.location.href = stripEmbedParam(url);
      return;
    }
    /* Logout hard-nav always exits browser fullscreen. While FS is on, POST
       the session clear and swap Sign In into #de-fs-app instead. */
    if(isLogoutUrl(url)){
      if(shouldKeepFullscreen()){
        logoutWhileKeepingFullscreen(url);
        return;
      }
      window.location.href = url;
      return;
    }
    url = withSalesScope(url);
    url = urlWithPosSettingsSection(url);
    if(isPosInvoiceAppUrl(url)){
      applyPosInvoiceImmersiveMode();
    }
    // Already on this page — do not soft-refresh / hard-reload (that exits fullscreen).
    if(sameAppUrl(url, window.location.href)) return;
    rememberSidebarState();
    try{
      sessionStorage.setItem(NAV_FLAG, '1');
    } catch(e){}

    if(shouldSoftNavigate()){
      // Mark soft-nav BEFORE any fullscreen churn so exit events keep the preference.
      setSoftNavFlag(true);
      // Arm while still fullscreen — pushState often drops FS immediately after.
      if(window.deFullscreen && typeof window.deFullscreen.armForSoftNav === 'function'){
        window.deFullscreen.armForSoftNav();
      } else if(window.deFullscreen && typeof window.deFullscreen.preserveForNavigation === 'function'){
        window.deFullscreen.preserveForNavigation();
      }
      try{
        history.pushState({ deSoftNav: true }, '', url);
      } catch(e){}
      // Re-enter during the same click gesture if pushState exited fullscreen.
      if(window.deFullscreen && typeof window.deFullscreen.preserveForNavigation === 'function'){
        window.deFullscreen.preserveForNavigation();
      }
      // Immediate sidebar feedback — old main stays visible until HTML arrives (no blank veil).
      try{ syncSidebarActiveFromUrl(url); } catch(e){}
      if(!prefetchHtmlReady(url)) showSoftNavProgress();
      softNavigate(url, hideSoftNavProgress);
      return;
    }

    if(window.deFullscreen && typeof window.deFullscreen.armForSoftNav === 'function'){
      window.deFullscreen.armForSoftNav();
    } else if(window.deFullscreen && typeof window.deFullscreen.preserveForNavigation === 'function'){
      window.deFullscreen.preserveForNavigation();
    }
    showOverlay();
    window.location.href = url;
  }

  function isSameOriginLink(link){
    try{
      var url = new URL(link.href, window.location.href);
      return url.origin === window.location.origin;
    } catch(e){
      return false;
    }
  }

  function handleSidebarLink(event, link){
    var rawHref = link.getAttribute('href') || '';
    if(!rawHref || rawHref.indexOf('javascript:') === 0) return false;
    if(event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) return false;
    if(!isSameOriginLink(link)) return false;
    if(link.hasAttribute('data-de-no-soft-nav') || isLogoutUrl(link.href || rawHref)) return false;
    var url = withSalesScope(link.href);
    if(!url) return false;
    if(isPosInvoiceAppUrl(url)){
      applyPosInvoiceImmersiveMode();
    }
    // Same page: block default navigation so a hard reload cannot exit fullscreen.
    // If a prior soft-nav left a stale main panel, force soft-refresh instead of no-op.
    if(sameAppUrl(url, window.location.href)){
      event.preventDefault();
      event.stopPropagation();
      if(!softNavContentMatchesUrl(url)){
        lockSidebarScroll(lockedSidebarScroll || captureSidebarScroll());
        link.classList.add('is-navigating');
        softNavigate(url, hideSoftNavProgress);
      }
      return true;
    }
    event.preventDefault();
    event.stopPropagation();
    lockSidebarScroll(lockedSidebarScroll || captureSidebarScroll());
    try{
      if(typeof link.focus === 'function') link.focus({ preventScroll: true });
    } catch(e){
      try{ link.focus(); } catch(err){}
    }
    link.classList.add('is-navigating');
    navigateWithTransition(url);
    return true;
  }

  function isFileDownloadLink(link){
    if(link.hasAttribute('download')) return true;
    if(link.classList.contains('rtc-dl')) return true;
    var rawHref = (link.getAttribute('href') || '').toLowerCase();
    var path = rawHref;
    try{
      path = new URL(link.href, window.location.href).pathname.toLowerCase();
    } catch(e){}
    if(path.indexOf('/export') !== -1 || path.indexOf('/download_') !== -1 || path.indexOf('/purchase-order') !== -1) return true;
    if(path.indexOf('/export/') !== -1) return true;
    /* Purchase Order PDF binary endpoint — never soft-nav into the shell. */
    if(/\/stores\/orders\/\d+\/pdf\/\d+(\/?$|\?)/.test(path)) return true;
    /* Accounts Excel downloads (not HTML report pages). */
    if(path === '/accounts/credit-payment/report' || path === '/accounts/purchase-verification/report') return true;
    if(path === '/accounts/purchase-ledger/report' || path === '/accounts/cash-ledger/report') return true;
    if(path === '/accounts/back-office-receipt/report') return true;
    if(/\.(xlsx|xls|docx|doc|csv|pdf|zip)(\?|$)/.test(path) || /\.(xlsx|xls|docx|doc|csv|pdf|zip)(\?|$)/.test(rawHref)){
      return true;
    }
    return false;
  }

  function handleWorkspaceLink(event, link){
    if(link.closest('.de-sidebar, .sidebar')) return false;
    if(link.hasAttribute('data-de-no-soft-nav')) return false;
    if(isLogoutUrl(link.href || link.getAttribute('href') || '')) return false;
    if(isMasterModalLink(link)) return false;
    if(isEmbedFragmentUrl(link.href || link.getAttribute('href') || '')) return false;
    if(isFileDownloadLink(link)) return false;
    if(!shouldSoftNavigate()) return false;
    return handleSidebarLink(event, link);
  }

  function captureSidebarScrollFromEvent(event){
    var link = event.target && event.target.closest
      ? event.target.closest('.de-sidebar a[href], .sidebar a[href]')
      : null;
    if(!link) return;
    rememberSidebarScrollForNav();
    // Stop the browser from scrolling the rail to the focused link.
    try{
      if(typeof link.focus === 'function') link.focus({ preventScroll: true });
    } catch(e){}
  }

  function initDeSidebarPageTransitions(){
    if(document.__deSidebarNavBound) return;
    document.__deSidebarNavBound = true;
    // Capture scroll before focus can move the rail (pointerdown/mousedown).
    document.addEventListener('pointerdown', captureSidebarScrollFromEvent, true);
    document.addEventListener('mousedown', captureSidebarScrollFromEvent, true);
    // Prefetch destination HTML on hover / press so clicks often hit cache.
    document.addEventListener('pointerdown', prefetchFromSidebarEvent, true);
    document.addEventListener('mouseover', prefetchFromSidebarEvent, true);
    document.addEventListener('click', function(event){
      var anyLink = event.target.closest('a[href]');
      if(anyLink && handleLogoutLink(event, anyLink)) return;
      var link = event.target.closest('.de-sidebar a[href], .sidebar a[href]');
      if(!link) return;
      handleSidebarLink(event, link);
    }, true);
    document.addEventListener('click', function(event){
      var link = event.target.closest('a[href]');
      if(!link) return;
      if(handleLogoutLink(event, link)) return;
      handleWorkspaceLink(event, link);
    }, true);
  }

  function initPageEnterTransition(){
    var ov = getOverlay();
    if(!ov) return;
    var pending = false;
    try{
      pending = sessionStorage.getItem(NAV_FLAG) === '1';
      if(pending) sessionStorage.removeItem(NAV_FLAG);
    } catch(e){}
    if(!pending) return;
    ov.style.display = 'block';
    ov.style.opacity = OVERLAY_OPACITY;
    requestAnimationFrame(function(){
      hideOverlay();
      if(window.deFullscreen && typeof window.deFullscreen.restoreAfterNavigation === 'function'){
        window.deFullscreen.restoreAfterNavigation();
      }
    });
  }

  window.deNavigateWithTransition = navigateWithTransition;
  window.deHidePageTransition = hideOverlay;
  window.deSoftSubmitForm = softSubmitForm;
  window.clearSidebarScrollLock = clearSidebarScrollLock;
  /** Soft-reload current (or given) URL without a hard navigation, so fullscreen can stay. */
  window.deSoftRefresh = function(url){
    url = withSalesScope(url || window.location.href);
    /* Always fetch fresh HTML — callers soft-refresh after writes (PO supplier
       picks, filters, etc.) and a warm prefetch would restore pre-mutation UI. */
    invalidatePrefetch(url);
    rememberSidebarState();
    try{
      sessionStorage.setItem(NAV_FLAG, '1');
    } catch(e){}

    var useSoft = shouldSoftNavigate()
      || (window.deFullscreen && typeof window.deFullscreen.isPreferred === 'function' && window.deFullscreen.isPreferred());
    if(!useSoft){
      window.location.href = url;
      return;
    }

    // Match navigateWithTransition: pushState + re-enter FS in the same user gesture.
    // Deferred pushState (after fetch) cannot restore fullscreen without a gesture.
    setSoftNavFlag(true);
    if(window.deFullscreen && typeof window.deFullscreen.armForSoftNav === 'function'){
      window.deFullscreen.armForSoftNav();
    } else if(window.deFullscreen && typeof window.deFullscreen.preserveForNavigation === 'function'){
      window.deFullscreen.preserveForNavigation();
    }
    if(!sameAppUrl(url, window.location.href)){
      try{
        history.pushState({ deSoftNav: true }, '', url);
      } catch(e){}
      if(window.deFullscreen && typeof window.deFullscreen.preserveForNavigation === 'function'){
        window.deFullscreen.preserveForNavigation();
      }
      try{ syncSidebarActiveFromUrl(url); } catch(e){}
    }
    if(!prefetchHtmlReady(url)) showSoftNavProgress();
    softNavigate(url, hideSoftNavProgress);
  };
  window.deInvalidateSoftNavCache = invalidatePrefetch;
  window.deInvalidateSoftNavCacheByPath = invalidatePrefetchByPath;
  window.deWorkspaceReinit = function(){
    initDeSidebarPageTransitions();
    if(typeof window.initSuFilterListboxes === 'function'){
      window.initSuFilterListboxes();
    }
    if(typeof window.initEpListboxes === 'function'){
      window.initEpListboxes();
    }
    if(typeof window.initStoresPage === 'function'){
      window.initStoresPage();
    }
    if(typeof window.initStoresPoPage === 'function'){
      window.initStoresPoPage();
    }
    if(typeof window.initEmployeePayrollPage === 'function'){
      window.initEmployeePayrollPage();
    }
    if(typeof window.initEmployeeBulkPage === 'function'){
      window.initEmployeeBulkPage();
    }
    if(typeof window.initPurchaseLedgerFilters === 'function'){
      window.initPurchaseLedgerFilters();
    }
    if(typeof window.initCreditPaymentFilters === 'function'){
      window.initCreditPaymentFilters();
    }
    if(typeof window.initModuleAccess === 'function'){
      window.initModuleAccess();
    }
    if(typeof window.initAccessUsersList === 'function'){
      window.initAccessUsersList();
    }
    if(typeof window.initAccessLoginLogs === 'function'){
      window.initAccessLoginLogs();
    }
    if(typeof window.initPosTablesPage === 'function'){
      window.initPosTablesPage();
    }
    if(typeof window.initHotelRoomsPage === 'function'){
      window.initHotelRoomsPage();
    }
    if(typeof window.initHotelReservationsPage === 'function'){
      window.initHotelReservationsPage();
    }
    if(typeof window.initHotelRoomDetailPage === 'function'){
      window.initHotelRoomDetailPage();
    }
    if(typeof window.initHotelSettingsPage === 'function'){
      window.initHotelSettingsPage();
    }
    if(typeof window.initHotelRoomInvoicePage === 'function'){
      window.initHotelRoomInvoicePage();
    }
    if(typeof window.initHotelInvoiceLedgerPage === 'function'){
      window.initHotelInvoiceLedgerPage();
    }
    if(typeof window.initCommunicationHubPage === 'function'){
      window.initCommunicationHubPage();
    }
    if(typeof window.initPromotionPage === 'function'){
      window.initPromotionPage();
    }
    if(typeof window.initPosSettingsPage === 'function'){
      window.initPosSettingsPage();
    }
    if(typeof window.initPosInvoicePage === 'function'){
      window.initPosInvoicePage();
    }
    if(typeof window.initPosInvoiceLedgerPage === 'function'){
      window.initPosInvoiceLedgerPage();
    }
    if(typeof window.initPosMenuPage === 'function'){
      window.initPosMenuPage();
    }
    if(typeof window.initMastersDashboard === 'function'){
      window.initMastersDashboard();
    }
    if(typeof window.initReportsDashboard === 'function'){
      window.initReportsDashboard();
    }
    if(typeof window.initSalesReportPage === 'function'){
      window.initSalesReportPage();
    }
    if(typeof window.initMenuSalesReportPage === 'function'){
      window.initMenuSalesReportPage();
    }
    if(typeof window.initCustomerInsightsReportPage === 'function'){
      window.initCustomerInsightsReportPage();
    }
    if(typeof window.initManagerInsightReportPage === 'function'){
      window.initManagerInsightReportPage();
    }
    if(typeof window.initStockAuditReportPage === 'function'){
      window.initStockAuditReportPage();
    }
    if(typeof window.initMainDashboardFilters === 'function'){
      window.initMainDashboardFilters();
    }
    if(typeof window.initMainDashboardCharts === 'function'){
      try{
        window.initMainDashboardCharts();
      } catch(eCharts){}
    }
    if(window.SalesDateRangePicker && typeof window.SalesDateRangePicker.syncChipDisplays === 'function'){
      window.SalesDateRangePicker.syncChipDisplays();
    }
    if(window.lucide && typeof window.lucide.createIcons === 'function'){
      window.lucide.createIcons({ attrs: { 'stroke-width': 1.75 } });
    }
  };

  window.addEventListener('popstate', function(){
    if(history.state && history.state.deSoftNav){
      if(typeof window.deSoftRefresh === 'function') window.deSoftRefresh();
      else window.location.reload();
    }
  });

  function bootRestoreSidebarScroll(){
    try{ if('scrollRestoration' in history) history.scrollRestoration = 'manual'; } catch(e){}
    clearSidebarScrollLock();
    if(typeof window.scheduleActiveNavIntoView === 'function'){
      window.scheduleActiveNavIntoView({ behavior: 'auto' });
    }
  }

  var idlePrefetchScheduled = false;
  function idlePrefetchSidebarDestinations(){
    if(!shouldSoftNavigate()) return;
    if(idlePrefetchScheduled) return;
    idlePrefetchScheduled = true;
    var schedule = window.requestIdleCallback || function(cb){
      return setTimeout(function(){ cb({ didTimeout: false, timeRemaining: function(){ return 0; } }); }, 50);
    };
    schedule(function(){
      idlePrefetchScheduled = false;
      var seen = {};
      function queue(href){
        if(!href || seen[href]) return;
        seen[href] = 1;
        prefetchSoftNav(href);
      }
      document.querySelectorAll('.de-sidebar a[href], .sidebar a[href], .db-home a[href], a.rd-report-card[href]').forEach(function(link){
        var raw = link.getAttribute('href') || '';
        if(!raw || raw.indexOf('javascript:') === 0) return;
        if(link.hasAttribute('data-de-no-soft-nav')) return;
        if(!isSameOriginLink(link)) return;
        if(isFileDownloadLink(link)) return;
        if(isMasterModalLink(link)) return;
        if(isLogoutUrl(link.href || raw)) return;
        queue(withSalesScope(link.href || raw));
      });
      IDLE_PREFETCH_PATHS.forEach(function(path){
        try{
          queue(withSalesScope(new URL(path, window.location.origin).toString()));
        } catch(e){}
      });
      prefetchRestaurantGroup();
      prefetchBarPosGroup();
      /* Apply module CSS now so the first click does not wait on a cold sheet. */
      [
        '/static/masters_dashboard.css?v=56',
        '/static/main_dashboard.css?v=32',
        '/static/main_dashboard_analytics.css?v=15',
        '/static/hbe_kpi.css?v=13',
        '/static/sales_entry_dashboard.css?v=34',
        '/static/sales_update_header.css?v=12',
        '/static/sales_update_premium.css?v=29',
        '/static/de_workspace_shell.css?v=55',
        '/static/stores.css?v=131',
        '/static/ep_form_listbox.css?v=29',
        '/static/pos_tables.css?v=72',
        '/static/pos_invoice.css?v=66',
        '/static/purchase_ledger.css?v=57',
        '/static/cash_ledger.css?v=26',
        '/static/communication_hub.css?v=12',
        '/static/communication_hub_promotion.css?v=1',
        '/static/hotel_rooms.css?v=73',
        '/static/hotel_reservations.css?v=46',
        '/static/hotel_date_picker.css?v=9',
        '/static/access_management_premium.css?v=32',
        '/static/hbe_home_premium.css?v=20',
        '/static/sales_report.css?v=19',
        '/static/sales_date_range.css?v=2',
        '/static/reports_page_scroll.css?v=5'
      ].forEach(function(href){
        try{
          var exists = Array.from(document.head.querySelectorAll('link[rel="stylesheet"]')).some(function(el){
            var current = el.getAttribute('href') || '';
            if(current === href) return true;
            try{
              return new URL(current, window.location.href).pathname === new URL(href, window.location.href).pathname;
            } catch(err){
              return false;
            }
          });
          if(exists) return;
          var link = document.createElement('link');
          link.rel = 'stylesheet';
          link.href = href;
          document.head.appendChild(link);
        } catch(e){}
      });
    }, { timeout: 200 });
  }

  /**
   * Soft-nav sessions keep a sticky sidebar. When a new module ships (Settings),
   * pull one partial of the current page and merge missing nav groups in.
   */
  function syncMissingSidebarModules(){
    var curSidebar = document.querySelector('#de-sidebar, .de-sidebar');
    if(!curSidebar) return;
    if(sidebarElById(curSidebar, 'de-nav-settings-group')) return;
    if(!shouldSoftNavigate()) return;
    var url = withPartialMain(window.location.href);
    fetch(url, {
      credentials: 'same-origin',
      headers: {
        Accept: 'text/html',
        'X-Requested-With': 'XMLHttpRequest',
        'X-De-Partial': 'main'
      },
      cache: 'no-store'
    })
      .then(function(resp){
        if(!resp || !resp.ok) return null;
        return resp.text();
      })
      .then(function(html){
        if(!html) return;
        var doc = new DOMParser().parseFromString(html, 'text/html');
        var nextSidebar =
          doc.querySelector('#de-sidebar, .de-sidebar') ||
          doc.querySelector('[data-de-soft-nav-merge-root] #de-sidebar');
        if(!nextSidebar) return;
        persistOpenNavGroups(curSidebar);
        mergeMissingSidebarLinks(curSidebar, nextSidebar);
        pruneRemovedSidebarLinks(curSidebar);
        dedupeSidebarSubitems(curSidebar);
        restoreOpenNavGroups(curSidebar);
      })
      .catch(function(){});
  }

  function init(){
    installFormSubmitGuards();
    initDeSidebarPageTransitions();
    initPageEnterTransition();
    bootRestoreSidebarScroll();
    bindShellOfflineListeners();
    /* Soft-nav session paint rules from first interaction-capable paint. */
    document.documentElement.classList.add('de-soft-nav-session');
    pruneRemovedSidebarLinks();
    syncMissingSidebarModules();
    idlePrefetchSidebarDestinations();
  }

  if(document.readyState === 'loading'){
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
