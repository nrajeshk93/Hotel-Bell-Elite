(function(){
  var TRANSITION_MS = 150;
  var OVERLAY_OPACITY = '.78';
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
      setTimeout(function(){
        if(done) done();
      }, TRANSITION_MS);
    });
  }

  function hideOverlay(){
    var ov = getOverlay();
    if(!ov) return;
    ov.style.opacity = '0';
    setTimeout(function(){
      ov.style.display = 'none';
    }, 180);
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

  function shouldSoftNavigate(){
    return isFullscreenActive() || isFullscreenPreferred();
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

  function runScriptNodes(scriptNodes, done){
    var loaded = window.__deSoftNavScripts = window.__deSoftNavScripts || {};
    var index = 0;

    function next(){
      if(index >= scriptNodes.length){
        done();
        return;
      }
      var old = scriptNodes[index++];
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
        var external = document.createElement('script');
        Array.from(old.attributes).forEach(function(attr){
          external.setAttribute(attr.name, attr.value);
        });
        external.onload = external.onerror = next;
        document.body.appendChild(external);
        return;
      }
      var inline = document.createElement('script');
      inline.text = old.textContent;
      document.body.appendChild(inline);
      next();
    }

    next();
  }

  function collectBodyContent(sourceBody){
    var scripts = [];
    var nodes = [];
    Array.from(sourceBody.childNodes).forEach(function(node){
      if(node.nodeName === 'SCRIPT'){
        scripts.push(node);
      } else if(node.nodeType === 1 && node.id === 'de-fs-app'){
        Array.from(node.childNodes).forEach(function(child){
          if(child.nodeName === 'SCRIPT') scripts.push(child);
          else nodes.push(child);
        });
      } else if(node.nodeType === 1 || node.nodeType === 3){
        if(node.nodeType === 3 && !String(node.textContent || '').trim()) return;
        nodes.push(node);
      }
    });
    return { nodes: nodes, scripts: scripts };
  }

  function finalizeSoftNav(){
    if(window.deFullscreen && typeof window.deFullscreen.setSoftNavInProgress === 'function'){
      window.deFullscreen.setSoftNavInProgress(false);
    }
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
    // Re-bind payroll listboxes (month/year/department) after soft page swaps —
    // ep_form_listbox.js only auto-inits once because soft-nav skips already-loaded scripts.
    if(typeof window.initEpListboxes === 'function'){
      window.initEpListboxes();
    }
    // Re-fill sales date chips after soft nav (display can stay blank if init races).
    if(window.SalesDateRangePicker && typeof window.SalesDateRangePicker.syncChipDisplays === 'function'){
      window.SalesDateRangePicker.syncChipDisplays();
    }
    if(window.deFullscreen && typeof window.deFullscreen.updateUi === 'function'){
      window.deFullscreen.updateUi();
    }
    if(window.deFullscreen && typeof window.deFullscreen.restoreAfterNavigation === 'function'){
      window.deFullscreen.restoreAfterNavigation();
    }
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
      // Never soft-swap binary downloads (xlsx/docx/pdf) into the page.
      if(contentType.indexOf('text/html') === -1){
        throw new Error('non-html response');
      }
      return response.text();
    }).then(function(html){
      var parser = new DOMParser();
      var doc = parser.parseFromString(html, 'text/html');
      var swapRoot = (window.deFullscreen && window.deFullscreen.getSwapRoot)
        ? window.deFullscreen.getSwapRoot()
        : document.body;
      var content = collectBodyContent(doc.body);

      document.title = doc.title;
      if(doc.body && doc.body.className){
        document.body.className = doc.body.className;
      }
      mergeHeadAssets(doc);

      swapRoot.innerHTML = '';
      content.nodes.forEach(function(node){
        swapRoot.appendChild(document.importNode(node, true));
      });

      runScriptNodes(content.scripts, function(){
        history.pushState({ deSoftNav: true }, '', url);
        finalizeSoftNav();
        if(done) done();
      });
    }).catch(function(){
      if(window.deFullscreen && typeof window.deFullscreen.setSoftNavInProgress === 'function'){
        window.deFullscreen.setSoftNavInProgress(false);
      }
      window.location.href = url;
    });
  }

  function navigateWithTransition(url){
    if(!url || url === window.location.href) return;
    url = withSalesScope(url);
    rememberSidebarState();
    try{
      sessionStorage.setItem(NAV_FLAG, '1');
    } catch(e){}

    if(shouldSoftNavigate()){
      showOverlay(function(){
        softNavigate(url, hideOverlay);
      });
      return;
    }

    showOverlay(function(){
      window.location.href = url;
    });
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
    if(path.indexOf('/export') !== -1 || path.indexOf('/download_') !== -1) return true;
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
  window.deWorkspaceReinit = function(){
    initDeSidebarPageTransitions();
    if(typeof window.initEpListboxes === 'function'){
      window.initEpListboxes();
    }
    if(window.SalesDateRangePicker && typeof window.SalesDateRangePicker.syncChipDisplays === 'function'){
      window.SalesDateRangePicker.syncChipDisplays();
    }
  };

  window.addEventListener('popstate', function(){
    if(history.state && history.state.deSoftNav){
      window.location.reload();
    }
  });

  function init(){
    initDeSidebarPageTransitions();
    initPageEnterTransition();
  }

  if(document.readyState === 'loading'){
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
