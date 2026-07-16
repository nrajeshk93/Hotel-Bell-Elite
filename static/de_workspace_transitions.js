(function(){
  var TRANSITION_MS = 60;
  var OVERLAY_OPACITY = '.42';
  var HIDE_MS = 100;
  var NAV_FLAG = 'de-nav-transition';
  var FS_KEY = 'de-fullscreen-active';
  var SKIP_SCRIPT_PARTS = [
    'de_fullscreen.js',
    'de_workspace_nav.js',
    'de_workspace_transitions.js'
  ];

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
    var method = String(form.getAttribute('method') || form.method || 'get').toLowerCase();
    if(method && method !== 'get') return false;
    var enctype = String(form.getAttribute('enctype') || form.enctype || '').toLowerCase();
    if(enctype.indexOf('multipart') !== -1) return false;
    return shouldSoftNavigate();
  }

  /** Convert a GET form submit into soft-nav so fullscreen and the workspace shell survive. */
  function softSubmitForm(form){
    if(!shouldSoftSubmitForm(form)) return false;
    var url = formToGetUrl(form);
    navigateWithTransition(url);
    return true;
  }

  function installFormSubmitGuards(){
    if(window.__deFormSubmitGuards) return;
    window.__deFormSubmitGuards = true;

    document.addEventListener('submit', function(event){
      var form = event.target;
      if(!form || form.nodeName !== 'FORM') return;
      if(!shouldSoftSubmitForm(form)) return;
      event.preventDefault();
      event.stopPropagation();
      softSubmitForm(form);
    }, true);

    try{
      var originalSubmit = HTMLFormElement.prototype.submit;
      HTMLFormElement.prototype.submit = function(){
        if(softSubmitForm(this)) return;
        return originalSubmit.call(this);
      };
    } catch(e){}
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

  function syncSidebarFromDoc(doc){
    var curNav = document.querySelector('#de-sidebar .de-sb-nav, .de-sidebar .de-sb-nav');
    var nextNav = doc.querySelector('#de-sidebar .de-sb-nav, .de-sidebar .de-sb-nav');
    if(curNav && nextNav){
      curNav.replaceWith(document.importNode(nextNav, true));
      return;
    }
    var curSidebar = document.querySelector('#de-sidebar, .de-sidebar');
    var nextSidebar = doc.querySelector('#de-sidebar, .de-sidebar');
    if(!curSidebar || !nextSidebar) return;
    curSidebar.querySelectorAll('.is-active, [aria-current="page"]').forEach(function(el){
      el.classList.remove('is-active');
      el.removeAttribute('aria-current');
    });
    curSidebar.querySelectorAll('.de-nav-group').forEach(function(group){
      group.classList.remove('is-open', 'is-child-active');
      var toggle = group.querySelector('.de-nav-group-toggle');
      if(toggle) toggle.setAttribute('aria-expanded', 'false');
    });
    nextSidebar.querySelectorAll('a.is-active, a[aria-current="page"]').forEach(function(a){
      var id = a.id;
      var href = a.getAttribute('href');
      var match = null;
      if(id){
        var byId = document.getElementById(id);
        if(byId && curSidebar.contains(byId)) match = byId;
      }
      if(!match && href){
        match = curSidebar.querySelector('a[href="' + href.replace(/"/g, '\\"') + '"]');
      }
      if(!match) return;
      match.classList.add('is-active');
      if(a.getAttribute('aria-current')) match.setAttribute('aria-current', 'page');
    });
    nextSidebar.querySelectorAll('.de-nav-group.is-open, .de-nav-group.is-child-active').forEach(function(group){
      var id = group.id;
      var match = null;
      if(id){
        var byId = document.getElementById(id);
        if(byId && curSidebar.contains(byId)) match = byId;
      }
      if(!match) return;
      if(group.classList.contains('is-open')) match.classList.add('is-open');
      if(group.classList.contains('is-child-active')) match.classList.add('is-child-active');
      var toggle = match.querySelector('.de-nav-group-toggle');
      if(toggle) toggle.setAttribute('aria-expanded', match.classList.contains('is-open') ? 'true' : 'false');
    });
  }

  function scrollMainToTop(){
    var scroller = document.querySelector('.de-main-wrapper, .main-wrapper, .de-main-scroll');
    if(scroller) scroller.scrollTop = 0;
    window.scrollTo(0, 0);
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
    if(window.deFullscreen && typeof window.deFullscreen.setSoftNavInProgress === 'function'){
      window.deFullscreen.setSoftNavInProgress(false);
    }
    if(window.deFullscreen && typeof window.deFullscreen.updateUi === 'function'){
      window.deFullscreen.updateUi();
    }
  }

  function applySoftSwap(doc, url, done){
    var curMain = document.querySelector('.de-main-wrapper');
    var nextMain = doc.querySelector('.de-main-wrapper');

    document.title = doc.title;
    if(doc.body && doc.body.className){
      document.body.className = doc.body.className;
    }
    mergeHeadAssets(doc);
    syncSidebarFromDoc(doc);

    if(curMain && nextMain){
      var content = collectNodesAndScripts(nextMain);
      curMain.innerHTML = '';
      content.nodes.forEach(function(node){
        curMain.appendChild(document.importNode(node, true));
      });
      scrollMainToTop();
      runScriptNodes(content.scripts, function(){
        // URL already pushed during the click gesture; keep history in sync if needed.
        if(window.location.href !== url){
          try{ history.replaceState({ deSoftNav: true }, '', url); } catch(e){}
        }
        finalizeSoftNav();
        if(done) done();
      });
      return;
    }

    // Do NOT wipe #de-fs-app / body — that exits browser fullscreen.
    // Fall back to a full navigation only when the shell structure is missing.
    throw new Error('missing main wrapper for soft nav');
  }

  function softNavigate(url, done){
    if(window.deFullscreen && typeof window.deFullscreen.setSoftNavInProgress === 'function'){
      window.deFullscreen.setSoftNavInProgress(true);
    }
    if(window.deFullscreen && typeof window.deFullscreen.ensureRoot === 'function'){
      window.deFullscreen.ensureRoot();
    }

    fetch(url, {
      credentials: 'same-origin',
      headers: { 'Accept': 'text/html' },
      redirect: 'follow'
    }).then(function(response){
      if(!response.ok) throw new Error('soft nav failed');
      var contentType = (response.headers.get('content-type') || '').toLowerCase();
      if(contentType.indexOf('text/html') === -1){
        throw new Error('non-html response');
      }
      return response.text();
    }).then(function(html){
      var parser = new DOMParser();
      var doc = parser.parseFromString(html, 'text/html');
      applySoftSwap(doc, url, done);
    }).catch(function(){
      if(window.deFullscreen && typeof window.deFullscreen.setSoftNavInProgress === 'function'){
        window.deFullscreen.setSoftNavInProgress(false);
      }
      if(typeof done === 'function') done();
      // Soft-nav already pushState'd the target URL. Failing silently leaves a stale
      // page (month/year filters look broken until a manual refresh). Always hard-nav.
      window.location.href = url;
    });
  }

  function navigateWithTransition(url){
    if(!url) return;
    url = withSalesScope(url);
    if(url === window.location.href){
      window.deSoftRefresh(url);
      return;
    }
    rememberSidebarState();
    try{
      sessionStorage.setItem(NAV_FLAG, '1');
    } catch(e){}

    if(shouldSoftNavigate()){
      // Mark soft-nav BEFORE any fullscreen churn so exit events keep the preference.
      if(window.deFullscreen && typeof window.deFullscreen.setSoftNavInProgress === 'function'){
        window.deFullscreen.setSoftNavInProgress(true);
      }
      // Push URL during the click gesture. Some embeds exit fullscreen on pushState —
      // re-assert fullscreen immediately after while the gesture is still valid.
      try{
        history.pushState({ deSoftNav: true }, '', url);
      } catch(e){}
      if(window.deFullscreen && typeof window.deFullscreen.preserveForNavigation === 'function'){
        window.deFullscreen.preserveForNavigation();
      }
      showOverlay();
      softNavigate(url, hideOverlay);
      return;
    }

    if(window.deFullscreen && typeof window.deFullscreen.preserveForNavigation === 'function'){
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
    if(!url || url === window.location.href) return false;
    event.preventDefault();
    event.stopPropagation();
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
    if(path.indexOf('/export') !== -1 || path.indexOf('/download_') !== -1 || path.indexOf('/report') !== -1) return true;
    if(/\.(xlsx|xls|docx|doc|csv|pdf|zip)(\?|$)/.test(path) || /\.(xlsx|xls|docx|doc|csv|pdf|zip)(\?|$)/.test(rawHref)){
      return true;
    }
    return false;
  }

  function handleWorkspaceLink(event, link){
    if(link.closest('.de-sidebar, .sidebar')) return false;
    if(isFileDownloadLink(link)) return false;
    if(!shouldSoftNavigate()) return false;
    return handleSidebarLink(event, link);
  }

  function initDeSidebarPageTransitions(){
    if(document.__deSidebarNavBound) return;
    document.__deSidebarNavBound = true;
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

    if(window.deFullscreen && typeof window.deFullscreen.setSoftNavInProgress === 'function'){
      window.deFullscreen.setSoftNavInProgress(true);
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
    if(typeof window.initEpListboxes === 'function'){
      window.initEpListboxes();
    }
    if(typeof window.initModuleAccess === 'function'){
      window.initModuleAccess();
    }
    if(typeof window.initAccessUsersList === 'function'){
      window.initAccessUsersList();
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

  function init(){
    installFormSubmitGuards();
    initDeSidebarPageTransitions();
    initPageEnterTransition();
  }

  if(document.readyState === 'loading'){
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
