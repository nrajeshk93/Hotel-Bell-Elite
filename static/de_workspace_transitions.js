(function(){
  var TRANSITION_MS = 40;
  var OVERLAY_OPACITY = '.22';
  var HIDE_MS = 80;
  var NAV_FLAG = 'de-nav-transition';
  var FS_KEY = 'de-fullscreen-active';
  var PREFETCH_TTL_MS = 45000;
  var PREFETCH_MAX = 12;
  var SKIP_SCRIPT_PARTS = [
    'de_fullscreen.js',
    'de_workspace_nav.js',
    'de_workspace_transitions.js'
  ];
  /** @type {Map<string, {html?: string, promise?: Promise<string>, ts: number}>} */
  var prefetchCache = new Map();

  function prefersReducedMotion(){
    return window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  }

  function getOverlay(){
    return document.getElementById('page-transition');
  }

  function showOverlay(done){
    var ov = getOverlay();
    if(!ov || prefersReducedMotion()){
      if(done) done();
      return;
    }
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
    ov.style.opacity = '0';
    setTimeout(function(){
      ov.style.display = 'none';
    }, HIDE_MS);
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
    var method = String(form.getAttribute('method') || form.method || 'get').toLowerCase();
    if(method && method !== 'get' && method !== 'post') return false;
    var enctype = String(form.getAttribute('enctype') || form.enctype || '').toLowerCase();
    if(enctype.indexOf('multipart') !== -1) return false;
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

    showOverlay();
    var postUrl = withPartialMain(actionUrl);
    fetch(postUrl, {
      method: 'POST',
      body: fd,
      credentials: 'same-origin',
      headers: {
        'Accept': 'text/html',
        'X-De-Partial': 'main'
      },
      redirect: 'follow'
    }).then(function(response){
      if(!response.ok) throw new Error('post soft submit failed');
      var contentType = (response.headers.get('content-type') || '').toLowerCase();
      if(contentType.indexOf('text/html') === -1) throw new Error('non-html response');
      var finalUrl = stripPartialParam(response.url || actionUrl);
      return response.text().then(function(html){
        return { html: html, url: finalUrl };
      });
    }).then(function(result){
      try{ history.pushState({ deSoftNav: true }, '', result.url); } catch(e){}
      if(window.deFullscreen && typeof window.deFullscreen.preserveForNavigation === 'function'){
        window.deFullscreen.preserveForNavigation();
      }
      var doc = new DOMParser().parseFromString(result.html, 'text/html');
      // Swapped-in HTML brings its own fresh (unlocked) form, but unlock the
      // old node too in case anything still references it.
      unlockFormSubmit(form);
      applySoftSwap(doc, result.url, hideOverlay, sidebarScroll);
    }).catch(function(){
      markMainLoading(false);
      setSoftNavFlag(false);
      hideOverlay();
      unlockFormSubmit(form);
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

      if(!shouldSoftSubmitForm(form)) return;
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
      if(target.pathname.indexOf('/sales_update') === -1) return url;

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
    prefetchCache.set(key, { html: html, ts: Date.now() });
    prunePrefetchCache();
  }

  function prefetchSoftNav(url){
    if(!url || !shouldSoftNavigate()) return;
    if(isEmbedFragmentUrl(url)) return;
    url = withSalesScope(url);
    url = urlWithPosSettingsSection(url);
    if(sameAppUrl(url, window.location.href)) return;
    try{
      var path = new URL(url, window.location.href).pathname.toLowerCase();
      if(path.indexOf('/export') !== -1 || path.indexOf('/download_') !== -1 || path.indexOf('/report') !== -1) return;
      if(/\.(xlsx|xls|docx|doc|csv|pdf|zip)(\?|$)/.test(path)) return;
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
      redirect: 'follow'
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

  function takePrefetchedHtml(url){
    var key = navCacheKey(url);
    var entry = prefetchCache.get(key);
    if(!entry) return null;
    if(entry.html && (Date.now() - entry.ts) < PREFETCH_TTL_MS){
      prefetchCache.delete(key);
      return Promise.resolve(entry.html);
    }
    if(entry.promise){
      return entry.promise.then(function(html){
        if(!html) return null;
        prefetchCache.delete(key);
        return html;
      });
    }
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
      var valid = ['general','floor','tables','areas','kitchen','taxes','invoice','payment','menu','printers','integrations'];
      return valid.indexOf(key) >= 0 ? key : '';
    } catch(e){
      return '';
    }
  }

  function urlWithPosSettingsSection(url){
    try{
      var target = new URL(url, window.location.href);
      if(target.pathname.indexOf('/point-of-sale/settings') === -1) return url;
      if(target.hash && target.hash.length > 1) return target.toString();
      var stored = posSettingsSectionFromStorage();
      if(stored && stored !== 'general') target.hash = stored;
      return target.toString();
    } catch(e){
      return url;
    }
  }

  function rememberSidebarState(){
    try{
      var pinned = false;
      var expanded = false;
      document.querySelectorAll('.de-sidebar').forEach(function(sidebar){
        if(sidebar.classList.contains('is-pinned')) pinned = true;
        if(sidebar.classList.contains('is-expanded') || sidebar.classList.contains('is-pinned')){
          expanded = true;
        }
      });
      persistOpenNavGroups();
      if(pinned){
        localStorage.setItem('de-sidebar-pinned', '1');
        sessionStorage.setItem('de-sidebar-expanded', '1');
      } else if(expanded){
        sessionStorage.setItem('de-sidebar-expanded', '1');
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

  function mergeHeadAssets(sourceDoc){
    document.head.querySelectorAll('style[data-de-soft-nav]').forEach(function(el){
      el.parentNode.removeChild(el);
    });
    sourceDoc.head.querySelectorAll('link[rel="stylesheet"]').forEach(function(link){
      var href = link.getAttribute('href');
      if(!href) return;
      var exists = Array.from(document.head.querySelectorAll('link[rel="stylesheet"]')).some(function(existing){
        return existing.getAttribute('href') === href;
      });
      if(exists) return;
      document.head.appendChild(link.cloneNode(true));
    });
    sourceDoc.head.querySelectorAll('style').forEach(function(style){
      var clone = style.cloneNode(true);
      clone.setAttribute('data-de-soft-nav', '1');
      document.head.appendChild(clone);
    });
  }

  function loadExternalScript(old){
    return new Promise(function(resolve){
      var external = document.createElement('script');
      Array.from(old.attributes).forEach(function(attr){
        external.setAttribute(attr.name, attr.value);
      });
      external.onload = external.onerror = function(){ resolve(); };
      document.body.appendChild(external);
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
        if(loaded[candidateSrc]){
          index++;
          continue;
        }
        batch.push(candidate);
        index++;
      }

      if(batch.length){
        Promise.all(batch.map(function(old){
          var src = old.getAttribute('src');
          loaded[src] = true;
          return loadExternalScript(old);
        })).then(next);
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
        if(loaded[src]){
          next();
          return;
        }
        loaded[src] = true;
        loadExternalScript(old).then(next);
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
    Array.from(sourceBody.childNodes).forEach(function(node){
      if(isExecutableScript(node)){
        scripts.push(node);
      } else if(node.nodeType === 1 && node.id === 'de-fs-app'){
        Array.from(node.childNodes).forEach(function(child){
          if(isExecutableScript(child)) scripts.push(child);
          else nodes.push(child);
        });
      } else if(node.nodeType === 1 || node.nodeType === 3){
        if(node.nodeType === 3 && !String(node.textContent || '').trim()) return;
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
    if(!Array.isArray(ids)) return;
    var idSet = {};
    ids.forEach(function(id){
      if(id) idSet[id] = true;
    });
    sidebar.querySelectorAll('.de-nav-group').forEach(function(group){
      if(!group.id) return;
      // Keep the current-page section open; otherwise match persisted ids exactly.
      var shouldOpen = !!idSet[group.id] || group.classList.contains('is-child-active');
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
  function mergeMissingSidebarLinks(curSidebar, nextSidebar){
    if(!curSidebar || !nextSidebar) return false;
    var addedAny = false;
    var curNav = curSidebar.querySelector('.de-sb-nav');
    var nextNav = nextSidebar.querySelector('.de-sb-nav');
    if(curNav && nextNav){
      Array.from(nextNav.children).forEach(function(nextNode){
        if(!nextNode.id) return;
        if(document.getElementById(nextNode.id)) return;
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
          var curPrev = prev.id ? document.getElementById(prev.id) : null;
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
            var curNext = next.id ? document.getElementById(next.id) : null;
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
    var nextSidebar = doc.querySelector('#de-sidebar, .de-sidebar');
    if(!curSidebar) return;
    if(!nextSidebar){
      syncSidebarActiveFromUrl(url || window.location.href);
      return;
    }

    persistOpenNavGroups(curSidebar);
    mergeMissingSidebarLinks(curSidebar, nextSidebar);
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
    var snapshot = {
      sidebarTop: sidebar.scrollTop || 0,
      navTop: nav ? (nav.scrollTop || 0) : 0
    };
    try{
      sessionStorage.setItem(SIDEBAR_SCROLL_KEY, JSON.stringify(snapshot));
    } catch(e){}
    return snapshot;
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

  function onSidebarScrollLockEvent(event){
    if(!isSidebarScrollLocked()) return;
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

  function lockSidebarScroll(snapshot){
    lockedSidebarScroll = snapshot || lockedSidebarScroll || captureSidebarScroll();
    if(!lockedSidebarScroll) return;
    // Keep restoring through soft-nav + late layout (icons, fonts, focus).
    sidebarScrollLockUntil = Date.now() + 2500;
    if(sidebarScrollReleaseTimer){
      clearTimeout(sidebarScrollReleaseTimer);
      sidebarScrollReleaseTimer = null;
    }
    if(!window.__deSidebarScrollLockBound){
      window.__deSidebarScrollLockBound = true;
      document.addEventListener('scroll', onSidebarScrollLockEvent, true);
    }
    restoreSidebarScroll(lockedSidebarScroll);
    if(sidebarScrollLockTimer) clearInterval(sidebarScrollLockTimer);
    sidebarScrollLockTimer = setInterval(function(){
      if(!lockedSidebarScroll) return;
      if(!isSidebarScrollLocked()){
        clearInterval(sidebarScrollLockTimer);
        sidebarScrollLockTimer = null;
        return;
      }
      restoreSidebarScroll(lockedSidebarScroll);
    }, 50);
  }

  function releaseSidebarScrollLock(delayMs){
    if(sidebarScrollReleaseTimer) clearTimeout(sidebarScrollReleaseTimer);
    sidebarScrollReleaseTimer = setTimeout(function(){
      sidebarScrollReleaseTimer = null;
      restoreSidebarScroll(lockedSidebarScroll);
      // Keep active item on-screen without jumping the rail to the top.
      try{
        var active = document.querySelector('#de-sidebar a.is-active, #de-sidebar a[aria-current="page"]');
        if(active && typeof window.ensureVisibleInScroller === 'function'){
          window.ensureVisibleInScroller(active, { behavior: 'auto', padding: 12 });
        }
      } catch(e){}
      lockedSidebarScroll = null;
      sidebarScrollLockUntil = 0;
      if(sidebarScrollLockTimer){
        clearInterval(sidebarScrollLockTimer);
        sidebarScrollLockTimer = null;
      }
    }, typeof delayMs === 'number' ? delayMs : 0);
  }

  function restoreSidebarScrollAfterLayout(snapshot){
    if(snapshot) lockedSidebarScroll = snapshot;
    // Extend lock — do not shorten or clear here (late page scripts still run).
    sidebarScrollLockUntil = Math.max(sidebarScrollLockUntil, Date.now() + 1200);
    restoreSidebarScroll(lockedSidebarScroll || snapshot);
    requestAnimationFrame(function(){
      restoreSidebarScroll(lockedSidebarScroll || snapshot);
      requestAnimationFrame(function(){
        restoreSidebarScroll(lockedSidebarScroll || snapshot);
      });
    });
    setTimeout(function(){
      restoreSidebarScroll(lockedSidebarScroll || snapshot);
    }, 100);
    setTimeout(function(){
      restoreSidebarScroll(lockedSidebarScroll || snapshot);
    }, 400);
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
      // Final restores after soft-nav flag drops, then release the lock.
      restoreSidebarScroll(lockedSidebarScroll);
      sidebarScrollLockUntil = Math.max(sidebarScrollLockUntil, Date.now() + 400);
      releaseSidebarScrollLock(450);
    }
  }

  function clearNavigatingLinks(){
    document.querySelectorAll('.de-sidebar a.is-navigating, .sidebar a.is-navigating').forEach(function(el){
      el.classList.remove('is-navigating');
    });
  }

  function finalizeSoftNav(){
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
    // Keep soft-nav flag briefly so late fullscreenchange events do not clear the lock.
    setTimeout(function(){
      setSoftNavFlag(false);
      if(window.deFullscreen && typeof window.deFullscreen.updateUi === 'function'){
        window.deFullscreen.updateUi();
      }
    }, 600);
  }

  function applySoftSwap(doc, url, done, sidebarScroll){
    if(typeof window.closeMasterModal === 'function'){
      window.closeMasterModal();
    }
    var curMain = document.querySelector('.de-main-wrapper');
    var nextMain = doc.querySelector('.de-main-wrapper');
    if(!sidebarScroll) sidebarScroll = lockedSidebarScroll || captureSidebarScroll();
    lockSidebarScroll(sidebarScroll);

    document.title = doc.title;
    if(doc.body && doc.body.className){
      document.body.className = doc.body.className;
    }
    mergeHeadAssets(doc);
    syncSidebarFromDoc(doc, url);
    restoreSidebarScroll(sidebarScroll);

    if(curMain && nextMain){
      var content = collectNodesAndScripts(nextMain);
      curMain.classList.remove('is-soft-nav-loading');
      curMain.innerHTML = '';
      content.nodes.forEach(function(node){
        curMain.appendChild(document.importNode(node, true));
      });
      scrollMainToTop();
      restoreSidebarScroll(sidebarScroll);
      runScriptNodes(content.scripts, function(){
        // URL already pushed during the click gesture; keep history in sync if needed.
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
        finalizeSoftNav();
        restoreSidebarScrollAfterLayout(sidebarScroll);
        markMainLoading(false);
        if(done) done();
      });
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
    return !!link.closest(
      '#md-master-modal, .md-master-modal, #md-master-modal-inject, .md-master-embed'
    );
  }

  function softNavigate(url, done){
    setSoftNavFlag(true);
    markMainLoading(true);
    var sidebarScroll = lockedSidebarScroll || captureSidebarScroll();
    lockSidebarScroll(sidebarScroll);
    if(window.deFullscreen && typeof window.deFullscreen.ensureRoot === 'function'){
      window.deFullscreen.ensureRoot();
    }

    var prefetched = takePrefetchedHtml(url);
    var htmlPromise = prefetched || fetch(withPartialMain(url), {
      credentials: 'same-origin',
      headers: {
        'Accept': 'text/html',
        'X-De-Partial': 'main'
      },
      redirect: 'follow'
    }).then(function(response){
      if(!response.ok) throw new Error('soft nav failed');
      var contentType = (response.headers.get('content-type') || '').toLowerCase();
      if(contentType.indexOf('text/html') === -1){
        throw new Error('non-html response');
      }
      return response.text();
    });

    htmlPromise.then(function(html){
      if(!html) throw new Error('empty soft nav html');
      var parser = new DOMParser();
      var doc = parser.parseFromString(html, 'text/html');
      if(!doc.querySelector('.de-main-wrapper')){
        throw new Error('missing main wrapper for soft nav');
      }
      applySoftSwap(doc, url, done, sidebarScroll);
    }).catch(function(){
      // Keep captured rail scroll in sessionStorage for hard-nav boot restore.
      if(sidebarScroll){
        try{ sessionStorage.setItem(SIDEBAR_SCROLL_KEY, JSON.stringify(sidebarScroll)); } catch(e){}
      }
      markMainLoading(false);
      setSoftNavFlag(false);
      if(typeof done === 'function') done();
      // Soft-nav already pushState'd the target URL. Failing silently leaves a stale
      // page (month/year filters look broken until a manual refresh). Always hard-nav.
      window.location.href = url;
    });
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
    url = withSalesScope(url);
    url = urlWithPosSettingsSection(url);
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
      showOverlay();
      softNavigate(url, hideOverlay);
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
    var url = withSalesScope(link.href);
    if(!url) return false;
    // Same page: block default navigation so a hard reload cannot exit fullscreen.
    if(sameAppUrl(url, window.location.href)){
      event.preventDefault();
      event.stopPropagation();
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
    if(path.indexOf('/export') !== -1 || path.indexOf('/download_') !== -1 || path.indexOf('/report') !== -1 || path.indexOf('/purchase-order') !== -1) return true;
    if(/\.(xlsx|xls|docx|doc|csv|pdf|zip)(\?|$)/.test(path) || /\.(xlsx|xls|docx|doc|csv|pdf|zip)(\?|$)/.test(rawHref)){
      return true;
    }
    return false;
  }

  function handleWorkspaceLink(event, link){
    if(link.closest('.de-sidebar, .sidebar')) return false;
    if(link.hasAttribute('data-de-no-soft-nav')) return false;
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

  function prefetchFromSidebarEvent(event){
    var link = event.target && event.target.closest
      ? event.target.closest('.de-sidebar a[href], .sidebar a[href], a[href]')
      : null;
    if(!link) return;
    if(link.closest && !link.closest('.de-sidebar, .sidebar') && event.type === 'mouseover') return;
    var rawHref = link.getAttribute('href') || '';
    if(!rawHref || rawHref.indexOf('javascript:') === 0) return;
    if(!isSameOriginLink(link)) return;
    if(isFileDownloadLink(link)) return;
    if(isMasterModalLink(link)) return;
    if(isEmbedFragmentUrl(link.href || rawHref)) return;
    prefetchSoftNav(withSalesScope(link.href));
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
      var link = event.target.closest('.de-sidebar a[href], .sidebar a[href]');
      if(!link) return;
      handleSidebarLink(event, link);
    }, true);
    document.addEventListener('click', function(event){
      var link = event.target.closest('a[href]');
      if(!link) return;
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
  /** Soft-reload current (or given) URL without a hard navigation, so fullscreen can stay. */
  window.deSoftRefresh = function(url){
    url = withSalesScope(url || window.location.href);
    rememberSidebarState();
    try{
      sessionStorage.setItem(NAV_FLAG, '1');
    } catch(e){}

    setSoftNavFlag(true);
    if(window.deFullscreen && typeof window.deFullscreen.armForSoftNav === 'function'){
      window.deFullscreen.armForSoftNav();
    }
    if(window.deFullscreen && typeof window.deFullscreen.preserveForNavigation === 'function'){
      window.deFullscreen.preserveForNavigation();
    }

    if(shouldSoftNavigate()){
      showOverlay();
      softNavigate(url, hideOverlay);
      return;
    }

    if(window.deFullscreen && typeof window.deFullscreen.isPreferred === 'function' && window.deFullscreen.isPreferred()){
      showOverlay();
      softNavigate(url, hideOverlay);
      return;
    }

    window.location.href = url;
  };
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
    if(typeof window.initEmployeePayrollPage === 'function'){
      window.initEmployeePayrollPage();
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
    if(typeof window.initPosTablesPage === 'function'){
      window.initPosTablesPage();
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
    if(typeof window.initMastersDashboard === 'function'){
      window.initMastersDashboard();
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
    var snapshot = readStoredSidebarScroll();
    if(!snapshot) return;
    lockedSidebarScroll = snapshot;
    restoreSidebarScroll(snapshot);
    requestAnimationFrame(function(){
      restoreSidebarScroll(snapshot);
      requestAnimationFrame(function(){
        restoreSidebarScroll(snapshot);
        // Drop boot lock so the user can scroll freely after first paint.
        lockedSidebarScroll = null;
      });
    });
  }

  function init(){
    installFormSubmitGuards();
    initDeSidebarPageTransitions();
    initPageEnterTransition();
    bootRestoreSidebarScroll();
  }

  if(document.readyState === 'loading'){
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
