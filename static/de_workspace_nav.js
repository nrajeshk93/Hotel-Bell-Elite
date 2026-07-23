(function(){
  var COLLAPSE_DELAY = 220;

  function prefersCoarsePointer(){
    try{
      return !!(window.matchMedia && (
        window.matchMedia('(pointer: coarse)').matches ||
        window.matchMedia('(hover: none)').matches
      ));
    } catch(e){
      return false;
    }
  }

  function isHoverExpandAllowed(){
    return !prefersCoarsePointer();
  }

  function getActiveWorkspaceHost(){
    var mainApp = document.getElementById('main-app');
    if(mainApp && mainApp.style.display !== 'none') return mainApp;
    var dashboard = document.getElementById('dashboard');
    if(dashboard && dashboard.classList.contains('show')) return dashboard;
    return mainApp || dashboard || null;
  }

  function getAllSidebars(){
    return Array.from(document.querySelectorAll('.de-sidebar'));
  }

  function getSidebar(){
    var host = getActiveWorkspaceHost();
    if(host){
      var sidebar = host.querySelector('.de-sidebar');
      if(sidebar) return sidebar;
    }
    return document.querySelector('.de-sidebar');
  }

  function getSbOverlay(){
    var host = getActiveWorkspaceHost();
    if(host) return host.querySelector('.de-sb-overlay');
    return document.getElementById('de-sb-overlay');
  }

  function isDeSidebarPinned(sidebar){
    sidebar = sidebar || getSidebar();
    return !!(sidebar && sidebar.classList.contains('is-pinned'));
  }

  function hasActiveDeFlyout(sidebar){
    sidebar = sidebar || getSidebar();
    return !!(sidebar && sidebar.querySelector('.de-nav-group.is-flyout-active'));
  }

  function isDeSidebarExpandedState(sidebar){
    sidebar = sidebar || getSidebar();
    if(!sidebar) return false;
    var hovered = isHoverExpandAllowed() && sidebar.matches(':hover');
    return hovered || sidebar.classList.contains('is-expanded') || sidebar.classList.contains('is-pinned');
  }

  function rememberDeSidebarExpanded(expanded){
    try{
      if(expanded){
        sessionStorage.setItem('de-sidebar-expanded', '1');
      } else if(!getAllSidebars().some(isDeSidebarPinned)){
        sessionStorage.removeItem('de-sidebar-expanded');
      }
    } catch(e){}
  }

  function updateDeSidebarPinButton(){
    var pinned = getAllSidebars().some(isDeSidebarPinned);
    document.querySelectorAll('.de-sidebar-pin-btn').forEach(function(btn){
      btn.classList.toggle('is-active', pinned);
      btn.setAttribute('aria-pressed', pinned ? 'true' : 'false');
      btn.title = pinned ? 'Unpin sidebar' : 'Pin sidebar expanded';
      btn.setAttribute('aria-label', pinned ? 'Unpin sidebar' : 'Pin sidebar expanded');
    });
  }

  function clearDeSidebarCollapseTimer(){
    if(window._deSidebarCollapseTimer){
      clearTimeout(window._deSidebarCollapseTimer);
      window._deSidebarCollapseTimer = null;
    }
  }

  function prefersReducedMotion(){
    try{
      return !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
    } catch(e){
      return false;
    }
  }

  function findScrollParent(el){
    if(!el || !el.parentElement) return null;
    var node = el.parentElement;
    while(node && node !== document.body && node !== document.documentElement){
      var style = window.getComputedStyle(node);
      var overflowY = style.overflowY;
      if(overflowY === 'auto' || overflowY === 'scroll'){
        return node;
      }
      node = node.parentElement;
    }
    var sidebar = el.closest ? el.closest('.de-sidebar') : null;
    if(sidebar){
      var nav = sidebar.querySelector('.de-sb-nav');
      if(nav) return nav;
    }
    return null;
  }

  function ensureVisibleInScroller(el, opts){
    if(!el || !el.getBoundingClientRect) return;
    // Soft-nav restores a captured scrollTop; do not fight it mid-swap.
    if(window.__deSoftNavInProgress) return;
    opts = opts || {};
    var scroller = opts.scroller || findScrollParent(el);
    if(!scroller) return;
    // Never scroll the window/body for sidebar items — only the rail scroller.
    if(scroller === document.body || scroller === document.documentElement) return;

    var pad = typeof opts.padding === 'number' ? opts.padding : 8;
    var elRect = el.getBoundingClientRect();
    var scRect = scroller.getBoundingClientRect();
    var topGap = elRect.top - scRect.top;
    var bottomGap = elRect.bottom - scRect.bottom;
    var delta = 0;

    // Prefer keeping the top (toggle) visible; then bring as much of the bottom into view.
    if(topGap < pad){
      delta = topGap - pad;
    } else if(bottomGap > -pad){
      delta = Math.min(bottomGap + pad, topGap - pad);
    }

    if(!delta) return;

    var nextTop = scroller.scrollTop + delta;
    var maxTop = Math.max(0, scroller.scrollHeight - scroller.clientHeight);
    nextTop = Math.max(0, Math.min(maxTop, nextTop));
    if(Math.abs(nextTop - scroller.scrollTop) < 1) return;

    var behavior = opts.behavior;
    if(!behavior){
      behavior = prefersReducedMotion() ? 'auto' : 'smooth';
    }
    if(typeof scroller.scrollTo === 'function'){
      try{
        scroller.scrollTo({ top: nextTop, behavior: behavior });
        return;
      } catch(e){}
    }
    scroller.scrollTop = nextTop;
  }

  function scheduleEnsureNavGroupVisible(group){
    if(!group) return;
    // Flyouts sit outside the nav scroller; scrolling the rail does not help.
    if(group.classList.contains('is-flyout-active')) return;
    requestAnimationFrame(function(){
      requestAnimationFrame(function(){
        if(!group.classList.contains('is-open')) return;
        if(group.classList.contains('is-flyout-active')) return;
        ensureVisibleInScroller(group);
      });
    });
  }

  function scheduleDeSidebarCollapse(sidebar){
    clearDeSidebarCollapseTimer();
    sidebar = sidebar || getSidebar();
    if(!sidebar || isDeSidebarPinned(sidebar) || hasActiveDeFlyout(sidebar)) return;
    if(window.__deSoftNavInProgress) return;
    if(window.deFullscreen && typeof window.deFullscreen.isSoftNavInProgress === 'function' && window.deFullscreen.isSoftNavInProgress()){
      return;
    }
    window._deSidebarCollapseTimer = setTimeout(function(){
      window._deSidebarCollapseTimer = null;
      if(window.__deSoftNavInProgress) return;
      if(window.deFullscreen && typeof window.deFullscreen.isSoftNavInProgress === 'function' && window.deFullscreen.isSoftNavInProgress()){
        return;
      }
      if(isDeSidebarPinned(sidebar) || hasActiveDeFlyout(sidebar)) return;
      setDeSidebarExpanded(false, sidebar);
      closeDeNavFlyouts(sidebar);
    }, COLLAPSE_DELAY);
  }

  function toggleDeSidebarExpandedPin(){
    var sidebar = getSidebar();
    if(!sidebar) return;
    var pinned = !isDeSidebarPinned(sidebar);
    if(pinned){
      document.body.classList.remove('sb-off');
      try{ localStorage.setItem('sb-collapsed', '0'); } catch(e){}
    }
    getAllSidebars().forEach(function(sb){
      sb.classList.toggle('is-pinned', pinned);
      if(pinned){
        sb.classList.add('is-expanded');
        sb.querySelectorAll('.de-nav-group.is-flyout-active').forEach(function(group){
          group.classList.remove('is-flyout-active');
        });
      } else if(!(isHoverExpandAllowed() && sb.matches(':hover'))){
        sb.classList.remove('is-expanded');
      }
    });
    if(pinned){
      rememberDeSidebarExpanded(true);
    }
    try{
      localStorage.setItem('de-sidebar-pinned', pinned ? '1' : '0');
    } catch(e){}
    updateDeSidebarPinButton();
  }

  function toggleDeNavGroup(event, groupId){
    if(event && typeof event.preventDefault === 'function') event.preventDefault();
    if(event && typeof event.stopPropagation === 'function') event.stopPropagation();
    clearDeSidebarCollapseTimer();

    var group = null;
    if(event && event.currentTarget && typeof event.currentTarget.closest === 'function'){
      group = event.currentTarget.closest('.de-nav-group');
    }
    if(!group && groupId){
      group = document.getElementById(groupId);
    }
    if(!group) return;

    var sidebar = group.closest('.de-sidebar') || getSidebar();
    setDeSidebarExpanded(true, sidebar);

    var sidebarExpanded = isDeSidebarExpandedState(sidebar);
    var opening = !group.classList.contains('is-open');

    // Keep other sections open so the left nav stays a stable map of the app
    // (Sales Analytics → Credit remains visible while Payroll is also open).
    if(opening){
      sidebar.querySelectorAll('.de-nav-group.is-flyout-active').forEach(function(other){
        if(other === group) return;
        other.classList.remove('is-flyout-active');
      });
    }

    group.classList.toggle('is-open', opening);
    group.classList.toggle('is-flyout-active', opening && !sidebarExpanded);
    var toggle = group.querySelector('.de-nav-group-toggle');
    if(toggle) toggle.setAttribute('aria-expanded', opening ? 'true' : 'false');
    try{
      var openIds = [];
      sidebar.querySelectorAll('.de-nav-group.is-open').forEach(function(g){
        if(g.id) openIds.push(g.id);
      });
      sessionStorage.setItem('de-nav-open-groups', JSON.stringify(openIds));
    } catch(e){}
    if(opening) scheduleEnsureNavGroupVisible(group);
  }

  function closeDeNavFlyouts(sidebar){
    sidebar = sidebar || getSidebar();
    if(!sidebar || isDeSidebarExpandedState(sidebar)) return;
    sidebar.querySelectorAll('.de-nav-group.is-flyout-active').forEach(function(group){
      group.classList.remove('is-flyout-active');
      if(!group.classList.contains('is-child-active')){
        group.classList.remove('is-open');
        var toggle = group.querySelector('.de-nav-group-toggle');
        if(toggle) toggle.setAttribute('aria-expanded', 'false');
      }
    });
  }

  function toggleDeSidebar(){
    var sidebar = getSidebar();
    var overlay = getSbOverlay();
    if(!sidebar || !overlay) return;
    sidebar.classList.toggle('open');
    overlay.classList.toggle('open');
  }

  function closeDeSidebar(){
    var sidebar = getSidebar();
    var overlay = getSbOverlay();
    if(sidebar) sidebar.classList.remove('open');
    if(overlay) overlay.classList.remove('open');
  }

  function toggleDeSidebarPin(){
    document.body.classList.toggle('sb-off');
    localStorage.setItem('sb-collapsed', document.body.classList.contains('sb-off') ? '1' : '0');
    setDeSidebarExpanded(false);
  }

  function setDeSidebarExpanded(expanded, targetSidebar){
    var sidebars = targetSidebar ? [targetSidebar] : getAllSidebars();
    sidebars.forEach(function(sidebar){
      if(!sidebar || window.innerWidth <= 760) return;
      if(document.body.classList.contains('sb-off')) return;
      if(!expanded && (sidebar.classList.contains('is-pinned') || hasActiveDeFlyout(sidebar))) return;
      sidebar.classList.toggle('is-expanded', expanded);
    });
    rememberDeSidebarExpanded(expanded);
  }

  function applyDeSidebarBootState(){
    var pinned = localStorage.getItem('de-sidebar-pinned') === '1';
    var sessionExpand = sessionStorage.getItem('de-sidebar-expanded') === '1';
    var shouldExpand = pinned || sessionExpand;

    if(pinned){
      document.body.classList.remove('sb-off');
      try{ localStorage.setItem('sb-collapsed', '0'); } catch(e){}
    } else if(localStorage.getItem('sb-collapsed') === '1'){
      document.body.classList.add('sb-off');
    } else {
      document.body.classList.remove('sb-off');
    }

    getAllSidebars().forEach(function(sidebar){
      if(pinned){
        sidebar.classList.add('is-pinned', 'is-expanded');
      } else if(sessionExpand){
        sidebar.classList.add('is-expanded');
      }
    });

    updateDeSidebarPinButton();
    document.documentElement.classList.remove('de-sidebar-wide-boot');

    if(shouldExpand){
      requestAnimationFrame(function(){
        getAllSidebars().forEach(function(sidebar){
          sidebar.classList.remove('de-sidebar-booting');
        });
      });
    }
  }

  function bindDeSidebarInteractions(deSidebar){
    if(!deSidebar || deSidebar.__deSidebarBound) return;
    deSidebar.__deSidebarBound = true;

    // Touch / coarse-pointer: no hover-expand. Use pin + ≤760px drawer only.
    if(!isHoverExpandAllowed()){
      deSidebar.classList.add('de-sidebar--touch');
      return;
    }

    deSidebar.addEventListener('mouseenter', function(){
      clearDeSidebarCollapseTimer();
      setDeSidebarExpanded(true, deSidebar);
      if(!isDeSidebarPinned(deSidebar)){
        deSidebar.querySelectorAll('.de-nav-group.is-flyout-active').forEach(function(group){
          group.classList.remove('is-flyout-active');
        });
      }
    });

    deSidebar.addEventListener('mouseleave', function(event){
      if(isDeSidebarPinned(deSidebar)) return;
      var related = event.relatedTarget;
      if(related && deSidebar.contains(related)) return;
      scheduleDeSidebarCollapse(deSidebar);
    });

    deSidebar.addEventListener('focusin', function(){
      clearDeSidebarCollapseTimer();
      setDeSidebarExpanded(true, deSidebar);
    });

    deSidebar.addEventListener('focusout', function(event){
      if(isDeSidebarPinned(deSidebar)) return;
      if(deSidebar.contains(event.relatedTarget)) return;
      if(hasActiveDeFlyout(deSidebar)) return;
      scheduleDeSidebarCollapse(deSidebar);
    });

    deSidebar.addEventListener('click', function(){
      clearDeSidebarCollapseTimer();
      setDeSidebarExpanded(true, deSidebar);
    });
  }

  function seedPersistedNavGroups(){
    var ids = [];
    document.querySelectorAll('.de-sidebar .de-nav-group.is-open').forEach(function(group){
      if(group.id) ids.push(group.id);
    });
    try{
      sessionStorage.setItem('de-nav-open-groups', JSON.stringify(ids));
    } catch(e){}
  }

  function initDeWorkspaceSidebar(){
    applyDeSidebarBootState();
    restorePersistedNavGroups();
    seedPersistedNavGroups();
    getAllSidebars().forEach(bindDeSidebarInteractions);

    if(!document.__deSidebarDocClickBound){
      document.__deSidebarDocClickBound = true;
      document.addEventListener('click', function(event){
        if(event.target && event.target.closest && event.target.closest('.de-nav-group-toggle')){
          return;
        }
        getAllSidebars().forEach(function(sidebar){
          if(sidebar.contains(event.target)) return;
          closeDeNavFlyouts(sidebar);
        });
      });
    }
  }

  function restorePersistedNavGroups(){
    var ids = [];
    try{
      ids = JSON.parse(sessionStorage.getItem('de-nav-open-groups') || '[]') || [];
    } catch(e){
      ids = [];
    }
    if(!Array.isArray(ids)) return;
    var idSet = {};
    ids.forEach(function(id){
      if(id) idSet[id] = true;
    });
    document.querySelectorAll('.de-sidebar .de-nav-group').forEach(function(group){
      if(!group.id) return;
      var shouldOpen = !!idSet[group.id] || group.classList.contains('is-child-active');
      group.classList.toggle('is-open', shouldOpen);
      if(!shouldOpen) group.classList.remove('is-flyout-active');
      var toggle = group.querySelector('.de-nav-group-toggle');
      if(toggle) toggle.setAttribute('aria-expanded', shouldOpen ? 'true' : 'false');
    });
  }

  function reinitDeWorkspaceSidebar(){
    applyDeSidebarBootState();
    restorePersistedNavGroups();
    seedPersistedNavGroups();
    getAllSidebars().forEach(bindDeSidebarInteractions);
  }

  window.toggleDeNavGroup = toggleDeNavGroup;
  window.closeDeNavFlyouts = closeDeNavFlyouts;
  window.toggleDeSidebar = toggleDeSidebar;
  window.closeDeSidebar = closeDeSidebar;
  window.toggleDeSidebarPin = toggleDeSidebarPin;
  window.toggleDeSidebarExpandedPin = toggleDeSidebarExpandedPin;
  window.setDeSidebarExpanded = setDeSidebarExpanded;
  window.applyDeSidebarBootState = applyDeSidebarBootState;
  window.reinitDeWorkspaceSidebar = reinitDeWorkspaceSidebar;
  window.findScrollParent = findScrollParent;
  window.ensureVisibleInScroller = ensureVisibleInScroller;

  if(document.readyState === 'loading'){
    document.addEventListener('DOMContentLoaded', initDeWorkspaceSidebar);
  } else {
    initDeWorkspaceSidebar();
  }
})();
