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

  function scheduleDeSidebarCollapse(sidebar){
    clearDeSidebarCollapseTimer();
    sidebar = sidebar || getSidebar();
    if(!sidebar || isDeSidebarPinned(sidebar) || hasActiveDeFlyout(sidebar)) return;
    window._deSidebarCollapseTimer = setTimeout(function(){
      window._deSidebarCollapseTimer = null;
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
    if(!ids.length) return;
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
    ids.forEach(function(id){
      var group = document.getElementById(id);
      if(!group) return;
      group.classList.add('is-open');
      var toggle = group.querySelector('.de-nav-group-toggle');
      if(toggle) toggle.setAttribute('aria-expanded', 'true');
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

  if(document.readyState === 'loading'){
    document.addEventListener('DOMContentLoaded', initDeWorkspaceSidebar);
  } else {
    initDeWorkspaceSidebar();
  }
})();
