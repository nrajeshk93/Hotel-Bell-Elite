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
      var pinned = getAllSidebars().some(isDeSidebarPinned);
      /* Only pin persists across loads. Hover expand must not sticky-expand the rail. */
      if(expanded && pinned){
        sessionStorage.setItem('de-sidebar-expanded', '1');
      } else if(!pinned){
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

  function getNavScroller(sidebar){
    sidebar = sidebar || getSidebar();
    if(!sidebar) return null;
    return sidebar.querySelector('.de-sb-nav');
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

  var activeNavCenterTimer = null;
  var activeNavCenterFinalTimer = null;
  var NAV_CENTER_DEBOUNCE = 80;
  var NAV_EXPAND_SETTLE_MS = 260;
  /** Expanded-layout scrollTop for the active page — applied on hover before paint. */
  var cachedExpandedNavScrollTop = null;

  function readCachedExpandedNavScrollTop(){
    if(typeof cachedExpandedNavScrollTop === 'number' && isFinite(cachedExpandedNavScrollTop)){
      return cachedExpandedNavScrollTop;
    }
    try{
      var raw = sessionStorage.getItem('de-sidebar-nav-scroll');
      if(!raw) return null;
      var parsed = JSON.parse(raw);
      if(parsed && typeof parsed.navTop === 'number' && isFinite(parsed.navTop)){
        cachedExpandedNavScrollTop = parsed.navTop;
        return parsed.navTop;
      }
    } catch(e){}
    return null;
  }

  function writeCachedExpandedNavScrollTop(top, sidebar){
    if(typeof top !== 'number' || !isFinite(top)) return;
    cachedExpandedNavScrollTop = Math.max(0, top);
    sidebar = sidebar || getSidebar();
    try{
      sessionStorage.setItem(
        'de-sidebar-nav-scroll',
        JSON.stringify({
          sidebarTop: sidebar ? sidebar.scrollTop || 0 : 0,
          navTop: cachedExpandedNavScrollTop
        })
      );
    } catch(e){}
  }

  function beginSidebarSnapMeasure(sidebar){
    if(!sidebar) return;
    sidebar.classList.add('de-sidebar--snap-measure');
  }

  function endSidebarSnapMeasure(sidebar){
    if(!sidebar) return;
    sidebar.classList.remove('de-sidebar--snap-measure');
  }

  /**
   * Keep the active nav row visible in expanded layout (nearest — never force
   * vertical center). Used to warm the hover-expand scroll cache.
   */
  function snapActiveNavSync(sidebar){
    sidebar = sidebar || getSidebar();
    if(!sidebar) return null;
    var scroller = getNavScroller(sidebar);
    if(!scroller) return null;

    var active = sidebar.querySelector('a.is-active, a[aria-current="page"]');
    if(active){
      var group = active.closest('.de-nav-group');
      if(group){
        group.classList.add('is-open');
        var toggle = group.querySelector('.de-nav-group-toggle');
        if(toggle) toggle.setAttribute('aria-expanded', 'true');
        var sub = group.querySelector('.de-nav-sub');
        if(sub) markNavSubSettled(sub, true);
      }
    }

    /* Force expanded metrics (labels + open submenu) before measuring. */
    void sidebar.offsetWidth;
    void scroller.offsetHeight;

    var target = null;
    if(active && isNavLinkScrollable(active, { allowCollapsed: true })){
      target = active;
    } else {
      target = getActiveNavTarget(sidebar);
    }
    if(!target || !isNavLinkScrollable(target, { allowCollapsed: true })) return null;

    ensureVisibleInScroller(target, {
      behavior: 'auto',
      scroller: scroller,
      padding: 16
    });
    var nextTop = scroller.scrollTop;
    writeCachedExpandedNavScrollTop(nextTop, sidebar);
    return nextTop;
  }

  /**
   * While the right panel is active (rail collapsed), pre-measure the expanded
   * scroll position so the first hover does not start at the top of the rail.
   */
  function preflightActiveNavScroll(sidebar){
    sidebar = sidebar || getSidebar();
    if(!sidebar || window.innerWidth <= 760) return;
    if(document.body.classList.contains('sb-off')) return;

    /* Already wide (pinned/hovered): leave scroll alone — never re-snap on idle. */
    if(
      isDeSidebarPinned(sidebar) ||
      sidebar.classList.contains('is-expanded') ||
      (isHoverExpandAllowed() && sidebar.matches(':hover'))
    ){
      return;
    }

    beginSidebarSnapMeasure(sidebar);
    sidebar.classList.add('de-sidebar--preflight-hidden', 'is-expanded');
    void sidebar.offsetWidth;
    var top = snapActiveNavSync(sidebar);
    sidebar.classList.remove('is-expanded', 'de-sidebar--preflight-hidden');
    endSidebarSnapMeasure(sidebar);
    /* Collapsed layout clamps scrollTop — keep the expanded value in cache only. */
    if(typeof top === 'number') writeCachedExpandedNavScrollTop(top, sidebar);
  }

  /** Apply cached expanded scroll as soon as the rail is wide enough to hold it. */
  function applyCachedNavScroll(sidebar){
    sidebar = sidebar || getSidebar();
    var scroller = getNavScroller(sidebar);
    if(!scroller) return false;
    var top = readCachedExpandedNavScrollTop();
    if(typeof top !== 'number') return false;
    scroller.scrollTop = top;
    return true;
  }

  function isSidebarHoverExpandSuppressed(){
    return Date.now() < (window.__deSidebarHoverSuppressUntil || 0);
  }

  function suppressSidebarHoverExpand(ms){
    ms = typeof ms === 'number' ? ms : 1200;
    window.__deSidebarHoverSuppressUntil = Date.now() + ms;
    getAllSidebars().forEach(function(sb){
      sb.classList.add('de-sidebar--suppress-hover');
      if(!isDeSidebarPinned(sb)){
        sb.classList.remove('is-expanded');
        endSidebarSnapMeasure(sb);
      }
    });
    // #region agent log
    try{
      fetch('http://127.0.0.1:7764/ingest/3c15e9d7-8289-4a1b-877f-c72ceeda0753',{
        method:'POST',
        headers:{'Content-Type':'application/json','X-Debug-Session-Id':'42fa9a'},
        body:JSON.stringify({
          sessionId:'42fa9a',
          runId:'nav-lag-post',
          hypothesisId:'H6',
          location:'de_workspace_nav.js:suppressSidebarHoverExpand',
          message:'sidebar pointer-events suppressed',
          data:{ms:ms,path:(location.pathname||'')},
          timestamp:Date.now()
        })
      }).catch(function(){});
    } catch(e){}
    // #endregion
    if(window.__deSidebarHoverSuppressTimer) clearTimeout(window.__deSidebarHoverSuppressTimer);
    window.__deSidebarHoverSuppressTimer = setTimeout(function(){
      window.__deSidebarHoverSuppressTimer = null;
      document.querySelectorAll('.de-sidebar.de-sidebar--suppress-hover').forEach(function(sb){
        sb.classList.remove('de-sidebar--suppress-hover');
      });
      // #region agent log
      try{
        fetch('http://127.0.0.1:7764/ingest/3c15e9d7-8289-4a1b-877f-c72ceeda0753',{
          method:'POST',
          headers:{'Content-Type':'application/json','X-Debug-Session-Id':'42fa9a'},
          body:JSON.stringify({
            sessionId:'42fa9a',
            runId:'nav-lag-post',
            hypothesisId:'H6',
            location:'de_workspace_nav.js:suppressSidebarHoverExpand:end',
            message:'sidebar suppress cleared',
            data:{ms:ms,path:(location.pathname||'')},
            timestamp:Date.now()
          })
        }).catch(function(){});
      } catch(e2){}
      // #endregion
    }, ms);
  }

  function expandSidebarAndSnap(sidebar, opts){
    sidebar = sidebar || getSidebar();
    opts = opts || {};
    if(!sidebar) return;
    if(isSidebarHoverExpandSuppressed() && !isDeSidebarPinned(sidebar)){
      return;
    }
    if(typeof window.clearSidebarScrollLock === 'function'){
      window.clearSidebarScrollLock();
    }
    sidebar.classList.remove('de-sidebar--preflight-hidden');

    /*
      Only class-based width counts here — :hover is already true on mouseenter,
      so isDeSidebarExpandedState() would wrongly skip the first expand.
      Cursor re-entry on an already-wide rail must not rewrite scrollTop.
    */
    var alreadyWide =
      sidebar.classList.contains('is-expanded') ||
      sidebar.classList.contains('is-pinned');
    if(alreadyWide){
      if(opts.ensureVisible){
        var keep = getActiveNavTarget(sidebar);
        if(keep){
          ensureVisibleInScroller(keep, {
            behavior: 'auto',
            scroller: getNavScroller(sidebar),
            padding: 16
          });
        }
      }
      return;
    }

    /* Collapsed → wide: restore preflight position, then only nudge if clipped. */
    applyCachedNavScroll(sidebar);
    setDeSidebarExpanded(true, sidebar);
    void sidebar.offsetWidth;
    applyCachedNavScroll(sidebar);
    var active = getActiveNavTarget(sidebar);
    if(active){
      ensureVisibleInScroller(active, {
        behavior: 'auto',
        scroller: getNavScroller(sidebar),
        padding: 16
      });
    }
  }

  function centerInScroller(el, opts){
    if(!el || !el.getBoundingClientRect) return;
    if(window.__deSoftNavInProgress && !(opts && opts.force)) return;
    opts = opts || {};
    if(!isNavLinkScrollable(el, { allowCollapsed: !!opts.allowCollapsed })) return;
    var sidebar = el.closest ? el.closest('.de-sidebar') : getSidebar();
    var scroller = opts.scroller || getNavScroller(sidebar) || findScrollParent(el);
    if(!scroller) return;
    if(scroller === document.body || scroller === document.documentElement) return;

    var elRect = el.getBoundingClientRect();
    var scRect = scroller.getBoundingClientRect();
    var delta = (elRect.top + elRect.height / 2) - (scRect.top + scRect.height / 2);
    if(Math.abs(delta) < 1) return;

    var nextTop = scroller.scrollTop + delta;
    var maxTop = Math.max(0, scroller.scrollHeight - scroller.clientHeight);
    nextTop = Math.max(0, Math.min(maxTop, nextTop));
    if(Math.abs(nextTop - scroller.scrollTop) < 1) return;

    /* Always assign scrollTop for nav snaps — scrollTo(smooth/auto) still paints a jump. */
    scroller.scrollTop = nextTop;
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

    // Nearest: only nudge when the target is clipped. Never force a tall
    // group's top into view (that jumps the rail upward away from the active item).
    var clippedTop = topGap < pad;
    var clippedBottom = bottomGap > -pad;
    if(clippedTop && clippedBottom){
      // Taller than the scroller — leave scroll alone unless caller insists.
      if(opts.preferTop) delta = topGap - pad;
      else if(opts.preferBottom) delta = bottomGap + pad;
    } else if(clippedTop){
      delta = topGap - pad;
    } else if(clippedBottom){
      delta = bottomGap + pad;
    }

    if(!delta) return;

    var nextTop = scroller.scrollTop + delta;
    var maxTop = Math.max(0, scroller.scrollHeight - scroller.clientHeight);
    nextTop = Math.max(0, Math.min(maxTop, nextTop));
    if(Math.abs(nextTop - scroller.scrollTop) < 1) return;

    var behavior = opts.behavior || 'auto';
    if(typeof scroller.scrollTo === 'function'){
      try{
        scroller.scrollTo({ top: nextTop, behavior: behavior });
        return;
      } catch(e){}
    }
    scroller.scrollTop = nextTop;
  }

  function isNavLinkScrollable(el, opts){
    opts = opts || {};
    if(!el || !el.getBoundingClientRect) return false;
    var sidebar = el.closest ? el.closest('.de-sidebar') : null;
    if(!sidebar) return false;
    if(!opts.allowCollapsed && !isDeSidebarExpandedState(sidebar)) return false;
    var rect = el.getBoundingClientRect();
    if(rect.height < 1) return false;
    var style = window.getComputedStyle(el);
    if(style.display === 'none' || style.visibility === 'hidden') return false;
    var sub = el.closest('.de-nav-sub');
    if(sub){
      var subStyle = window.getComputedStyle(sub);
      if(subStyle.display === 'none' || parseFloat(subStyle.maxHeight) === 0) return false;
    }
    return true;
  }

  function getActiveNavTarget(sidebar){
    sidebar = sidebar || getSidebar();
    if(!sidebar) return null;
    var active = sidebar.querySelector('a.is-active, a[aria-current="page"]');
    if(!active) return null;
    if(isNavLinkScrollable(active, { allowCollapsed: true })) return active;
    /* Collapsed rail hides submenu rows — aim at the parent section icon instead. */
    var group = active.closest('.de-nav-group');
    if(group){
      var toggle = group.querySelector('.de-nav-group-toggle');
      if(toggle && isNavLinkScrollable(toggle, { allowCollapsed: true })) return toggle;
    }
    return active;
  }

  function runActiveNavCenter(opts){
    opts = opts || {};
    if(window.__deSoftNavInProgress && !opts.force) return;
    var sidebar = getSidebar();
    if(!sidebar) return;
    var allowCollapsed = !!opts.allowCollapsed || !isDeSidebarExpandedState(sidebar);
    var active = getActiveNavTarget(sidebar);
    if(!active || !isNavLinkScrollable(active, { allowCollapsed: allowCollapsed })) return;
    var scroller = getNavScroller(sidebar);
    if(!scroller) return;
    var behavior = opts.behavior || 'auto';
    /* Default nearest — centering jumps Menu to mid-rail on hover/soft-nav. */
    var block = opts.block || 'nearest';
    if(block === 'center'){
      centerInScroller(active, {
        behavior: behavior,
        force: !!opts.force,
        scroller: scroller,
        allowCollapsed: allowCollapsed
      });
      return;
    }
    ensureVisibleInScroller(active, {
      behavior: behavior,
      scroller: scroller,
      padding: typeof opts.padding === 'number' ? opts.padding : 12
    });
  }

  /** Keep the active module/submenu aligned in the nav rail (works collapsed + expanded). */
  function scheduleActiveNavIntoView(opts){
    opts = opts || {};
    if(activeNavCenterTimer) clearTimeout(activeNavCenterTimer);
    if(activeNavCenterFinalTimer) clearTimeout(activeNavCenterFinalTimer);

    var sidebar = getSidebar();
    if(!sidebar) return;

    var expanded = isDeSidebarExpandedState(sidebar);
    var behavior = opts.behavior || 'auto';
    /* Never animate while collapsed — pre-position so hover expand does not scroll from top. */
    if(!expanded) behavior = 'auto';
    var passOpts = Object.assign({}, opts, {
      behavior: behavior,
      allowCollapsed: !expanded || !!opts.allowCollapsed
    });

    activeNavCenterTimer = setTimeout(function(){
      activeNavCenterTimer = null;
      requestAnimationFrame(function(){
        requestAnimationFrame(function(){
          runActiveNavCenter(passOpts);
        });
      });
    }, NAV_CENTER_DEBOUNCE);

    activeNavCenterFinalTimer = setTimeout(function(){
      activeNavCenterFinalTimer = null;
      runActiveNavCenter(Object.assign({}, passOpts, { behavior: 'auto' }));
    }, expanded ? NAV_EXPAND_SETTLE_MS : 0);
  }

  function scheduleActiveNavCenterOnExpand(sidebar){
    expandSidebarAndSnap(sidebar || getSidebar());
  }

  function persistNavScrollerPosition(sidebar){
    sidebar = sidebar || getSidebar();
    var scroller = getNavScroller(sidebar);
    if(!scroller) return;
    writeCachedExpandedNavScrollTop(
      typeof cachedExpandedNavScrollTop === 'number' ? cachedExpandedNavScrollTop : scroller.scrollTop || 0,
      sidebar
    );
  }

  function restoreNavScrollerPosition(sidebar){
    return applyCachedNavScroll(sidebar);
  }

  var NAV_SUB_SETTLE_MS = 260;

  function markNavSubSettled(sub, settled){
    if(!sub) return;
    if(settled) sub.classList.add('de-nav-sub--settled');
    else sub.classList.remove('de-nav-sub--settled');
  }

  function settleOpenNavSub(group){
    if(!group) return;
    var sub = group.querySelector('.de-nav-sub');
    if(!sub) return;
    markNavSubSettled(sub, false);
    if(prefersReducedMotion() || group.classList.contains('is-flyout-active')){
      markNavSubSettled(sub, true);
      return;
    }
    var done = false;
    function finish(ev){
      if(done) return;
      if(ev && ev.target !== sub) return;
      if(ev && ev.propertyName && ev.propertyName !== 'max-height') return;
      done = true;
      sub.removeEventListener('transitionend', finish);
      if(group.classList.contains('is-open') && !group.classList.contains('is-flyout-active')){
        markNavSubSettled(sub, true);
      }
    }
    sub.addEventListener('transitionend', finish);
    window.setTimeout(function(){ finish(null); }, NAV_SUB_SETTLE_MS);
  }

  function scheduleEnsureNavGroupVisible(group){
    if(!group) return;
    // Flyouts sit outside the nav scroller; scrolling the rail does not help.
    if(group.classList.contains('is-flyout-active')) return;
    if(window.__deSoftNavInProgress) return;
    function reveal(){
      if(window.__deSoftNavInProgress) return;
      if(!group.classList.contains('is-open')) return;
      if(group.classList.contains('is-flyout-active')) return;
      var active = group.querySelector('a.is-active, a[aria-current="page"]');
      var sub = group.querySelector('.de-nav-sub');
      var lastItem = sub ? sub.querySelector('.de-nav-subitem:last-of-type') : null;
      /* Prefer an active child; otherwise bring the opened submenu into view
         (bottom groups like User & Access expand below the fold). */
      var target = active || lastItem || (sub && sub.lastElementChild) || group.querySelector('.de-nav-group-toggle') || group;
      /* After accordion settle: nearest visibility only — never force mid-rail. */
      ensureVisibleInScroller(target, {
        behavior: 'auto',
        padding: 16
      });
    }
    var sub = group.querySelector('.de-nav-sub');
    if(prefersReducedMotion() || !sub){
      reveal();
      return;
    }
    var scrolled = false;
    function afterMotion(ev){
      if(scrolled) return;
      if(ev && ev.target !== sub) return;
      if(ev && ev.propertyName && ev.propertyName !== 'max-height') return;
      scrolled = true;
      sub.removeEventListener('transitionend', afterMotion);
      reveal();
    }
    sub.addEventListener('transitionend', afterMotion);
    window.setTimeout(function(){ afterMotion(null); }, NAV_SUB_SETTLE_MS);
  }

  function isPointerOverSidebar(sidebar){
    sidebar = sidebar || getSidebar();
    if(!sidebar) return false;
    try{
      if(sidebar.matches(':hover')) return true;
    } catch(e){}
    var activeEl = document.activeElement;
    if(activeEl && sidebar.contains(activeEl)) return true;
    return false;
  }

  /**
   * Unpinned rail must not stay wide. Clears sticky is-expanded after soft-nav,
   * lost mouseleave events, or flyouts that previously blocked collapse.
   */
  function collapseDeSidebarIfIdle(sidebar){
    sidebar = sidebar || getSidebar();
    if(!sidebar) return false;
    if(isDeSidebarPinned(sidebar)) return false;
    if(isPointerOverSidebar(sidebar)) return false;

    var wasExpanded = sidebar.classList.contains('is-expanded');
    sidebar.querySelectorAll('.de-nav-group.is-flyout-active').forEach(function(group){
      group.classList.remove('is-flyout-active');
    });
    if(wasExpanded){
      sidebar.classList.remove('is-expanded');
      rememberDeSidebarExpanded(false);
    }
    endSidebarSnapMeasure(sidebar);
    sidebar.classList.remove('de-sidebar--preflight-hidden');
    return true;
  }

  function syncDeSidebarPointerState(){
    if(window.__deSoftNavInProgress){
      if(window._deSidebarPointerSyncTimer) clearTimeout(window._deSidebarPointerSyncTimer);
      window._deSidebarPointerSyncTimer = setTimeout(function(){
        window._deSidebarPointerSyncTimer = null;
        if(!window.__deSoftNavInProgress) syncDeSidebarPointerState();
      }, 80);
      return;
    }
    getAllSidebars().forEach(collapseDeSidebarIfIdle);
    updateDeSidebarPinButton();
  }

  function scheduleDeSidebarCollapse(sidebar){
    clearDeSidebarCollapseTimer();
    sidebar = sidebar || getSidebar();
    if(!sidebar || isDeSidebarPinned(sidebar)) return;
    if(window.__deSoftNavInProgress){
      syncDeSidebarPointerState();
      return;
    }
    if(window.deFullscreen && typeof window.deFullscreen.isSoftNavInProgress === 'function' && window.deFullscreen.isSoftNavInProgress()){
      syncDeSidebarPointerState();
      return;
    }
    window._deSidebarCollapseTimer = setTimeout(function(){
      window._deSidebarCollapseTimer = null;
      if(window.__deSoftNavInProgress){
        syncDeSidebarPointerState();
        return;
      }
      if(window.deFullscreen && typeof window.deFullscreen.isSoftNavInProgress === 'function' && window.deFullscreen.isSoftNavInProgress()){
        syncDeSidebarPointerState();
        return;
      }
      if(isDeSidebarPinned(sidebar)) return;
      persistNavScrollerPosition(sidebar);
      collapseDeSidebarIfIdle(sidebar);
      closeDeNavFlyouts(sidebar);
    }, COLLAPSE_DELAY);
  }

  function toggleDeSidebarExpandedPin(){
    setDeSidebarPinned(!isDeSidebarPinned(getSidebar()));
  }

  function setDeSidebarPinned(pinned){
    pinned = !!pinned;
    var sidebar = getSidebar();
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
      } else if(!isPointerOverSidebar(sb)){
        sb.classList.remove('is-expanded');
        endSidebarSnapMeasure(sb);
      }
    });
    if(pinned){
      rememberDeSidebarExpanded(true);
    } else {
      rememberDeSidebarExpanded(false);
    }
    try{
      localStorage.setItem('de-sidebar-pinned', pinned ? '1' : '0');
    } catch(e){}
    updateDeSidebarPinButton();
    if(pinned){
      expandSidebarAndSnap(sidebar, { ensureVisible: true });
    } else {
      syncDeSidebarPointerState();
    }
    return pinned;
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

    // Accordion: only one module expanded at a time.
    // Close siblings on the next frame so open/close max-height transitions both paint.
    if(opening){
      group.classList.add('is-open');
      group.classList.toggle('is-flyout-active', !sidebarExpanded);
      var openSub = group.querySelector('.de-nav-sub');
      if(openSub) settleOpenNavSub(group);
      window.requestAnimationFrame(function(){
        sidebar.querySelectorAll('.de-nav-group.is-open, .de-nav-group.is-flyout-active').forEach(function(other){
          if(other === group) return;
          other.classList.remove('is-open', 'is-flyout-active');
          var otherSub = other.querySelector('.de-nav-sub');
          if(otherSub) markNavSubSettled(otherSub, false);
          var otherToggle = other.querySelector('.de-nav-group-toggle');
          if(otherToggle) otherToggle.setAttribute('aria-expanded', 'false');
        });
      });
    } else {
      group.classList.remove('is-open', 'is-flyout-active');
      var subEl = group.querySelector('.de-nav-sub');
      if(subEl) markNavSubSettled(subEl, false);
    }

    var toggle = group.querySelector('.de-nav-group-toggle');
    if(toggle){
      toggle.setAttribute('aria-expanded', opening ? 'true' : 'false');
      // Browser focus scroll would jump the rail to the toggle (top of group).
      try{
        if(typeof toggle.focus === 'function') toggle.focus({ preventScroll: true });
      } catch(e){}
    }
    try{
      var openIds = [];
      sidebar.querySelectorAll('.de-nav-group.is-open').forEach(function(g){
        if(g.id) openIds.push(g.id);
      });
      sessionStorage.setItem('de-nav-open-groups', JSON.stringify(openIds));
    } catch(e){}
    if(opening){
      scheduleEnsureNavGroupVisible(group);
    } else {
      // After collapse reflow, keep the current page item visible (nearest).
      scheduleActiveNavIntoView({ behavior: 'auto' });
    }
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
      if(!expanded && sidebar.classList.contains('is-pinned')) return;
      if(!expanded){
        sidebar.querySelectorAll('.de-nav-group.is-flyout-active').forEach(function(group){
          group.classList.remove('is-flyout-active');
        });
      }
      sidebar.classList.toggle('is-expanded', expanded);
      if(!expanded) endSidebarSnapMeasure(sidebar);
    });
    rememberDeSidebarExpanded(expanded);
  }

  function applyDeSidebarBootState(){
    var pinned = false;
    try{
      pinned = localStorage.getItem('de-sidebar-pinned') === '1';
    } catch(e){}
    /* Drop stale hover-expand flags so unpinned rail collapses after soft-nav / reload. */
    try{ sessionStorage.removeItem('de-sidebar-expanded'); } catch(e2){}

    if(pinned){
      document.body.classList.remove('sb-off');
      try{ localStorage.setItem('sb-collapsed', '0'); } catch(e3){}
    } else if(localStorage.getItem('sb-collapsed') === '1'){
      document.body.classList.add('sb-off');
    } else {
      document.body.classList.remove('sb-off');
    }

    getAllSidebars().forEach(function(sidebar){
      sidebar.classList.remove('de-sidebar--preflight-hidden', 'de-sidebar--snap-measure');
      if(pinned){
        sidebar.classList.add('is-pinned', 'is-expanded');
      } else {
        sidebar.classList.remove('is-pinned');
        /* During soft-nav, ignore :hover — Back sits beside the rail and would
           leave a sticky is-expanded that sync then collapses (expand/minimize). */
        var keepHover =
          !window.__deSoftNavInProgress &&
          isHoverExpandAllowed() &&
          sidebar.matches(':hover');
        if(keepHover){
          sidebar.classList.add('is-expanded');
        } else {
          sidebar.classList.remove('is-expanded');
        }
      }
    });

    updateDeSidebarPinButton();
    document.documentElement.classList.remove('de-sidebar-wide-boot');

    if(pinned){
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
      if(isSidebarHoverExpandSuppressed() && !isDeSidebarPinned(deSidebar)) return;
      if(!isDeSidebarPinned(deSidebar)){
        deSidebar.querySelectorAll('.de-nav-group.is-flyout-active').forEach(function(group){
          group.classList.remove('is-flyout-active');
        });
      }
      expandSidebarAndSnap(deSidebar);
    });

    deSidebar.addEventListener('mouseleave', function(event){
      if(isDeSidebarPinned(deSidebar)) return;
      var related = event.relatedTarget;
      if(related && deSidebar.contains(related)) return;
      persistNavScrollerPosition(deSidebar);
      endSidebarSnapMeasure(deSidebar);
      scheduleDeSidebarCollapse(deSidebar);
    });

    deSidebar.addEventListener('focusin', function(){
      clearDeSidebarCollapseTimer();
      expandSidebarAndSnap(deSidebar);
    });

    deSidebar.addEventListener('focusout', function(event){
      if(isDeSidebarPinned(deSidebar)) return;
      if(deSidebar.contains(event.relatedTarget)) return;
      if(hasActiveDeFlyout(deSidebar)) return;
      persistNavScrollerPosition(deSidebar);
      endSidebarSnapMeasure(deSidebar);
      scheduleDeSidebarCollapse(deSidebar);
    });

    /* Do not re-snap on every click — that fights soft-nav to Settings / Menu. */
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
    /* Measure expanded Menu scroll while the user is still on the right panel. */
    getAllSidebars().forEach(function(sidebar){
      preflightActiveNavScroll(sidebar);
    });

    if(!document.__deSidebarDocClickBound){
      document.__deSidebarDocClickBound = true;
      document.addEventListener('click', function(event){
        if(event.target && event.target.closest && event.target.closest('.de-nav-group-toggle')){
          return;
        }
        /* Never interfere with sidebar link navigation. */
        if(event.target && event.target.closest && event.target.closest('.de-sidebar a[href], .sidebar a[href]')){
          return;
        }
        getAllSidebars().forEach(function(sidebar){
          if(sidebar.contains(event.target)) return;
          closeDeNavFlyouts(sidebar);
          collapseDeSidebarIfIdle(sidebar);
        });
      });
      document.addEventListener('pointerdown', function(event){
        var t = event.target;
        if(t && t.closest && t.closest('.de-sidebar a[href], .sidebar a[href]')){
          return;
        }
        getAllSidebars().forEach(function(sidebar){
          if(t && sidebar.contains(t)) return;
          collapseDeSidebarIfIdle(sidebar);
        });
      }, true);
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
      var sub = group.querySelector('.de-nav-sub');
      if(sub) markNavSubSettled(sub, shouldOpen);
      var toggle = group.querySelector('.de-nav-group-toggle');
      if(toggle) toggle.setAttribute('aria-expanded', shouldOpen ? 'true' : 'false');
    });
  }

  function reinitDeWorkspaceSidebar(){
    applyDeSidebarBootState();
    restorePersistedNavGroups();
    seedPersistedNavGroups();
    getAllSidebars().forEach(bindDeSidebarInteractions);
    getAllSidebars().forEach(function(sidebar){
      preflightActiveNavScroll(sidebar);
    });
    syncDeSidebarPointerState();
  }

  window.toggleDeNavGroup = toggleDeNavGroup;
  window.closeDeNavFlyouts = closeDeNavFlyouts;
  window.toggleDeSidebar = toggleDeSidebar;
  window.closeDeSidebar = closeDeSidebar;
  window.toggleDeSidebarPin = toggleDeSidebarPin;
  window.toggleDeSidebarExpandedPin = toggleDeSidebarExpandedPin;
  window.setDeSidebarPinned = setDeSidebarPinned;
  window.setDeSidebarExpanded = setDeSidebarExpanded;
  window.applyDeSidebarBootState = applyDeSidebarBootState;
  window.reinitDeWorkspaceSidebar = reinitDeWorkspaceSidebar;
  window.syncDeSidebarPointerState = syncDeSidebarPointerState;
  window.suppressSidebarHoverExpand = suppressSidebarHoverExpand;
  window.isSidebarHoverExpandSuppressed = isSidebarHoverExpandSuppressed;
  window.findScrollParent = findScrollParent;
  window.centerInScroller = centerInScroller;
  window.ensureVisibleInScroller = ensureVisibleInScroller;
  window.scheduleActiveNavIntoView = scheduleActiveNavIntoView;
  window.scheduleActiveNavCenterOnExpand = scheduleActiveNavCenterOnExpand;
  window.preflightActiveNavScroll = preflightActiveNavScroll;
  window.expandSidebarAndSnap = expandSidebarAndSnap;

  if(document.readyState === 'loading'){
    document.addEventListener('DOMContentLoaded', initDeWorkspaceSidebar);
  } else {
    initDeWorkspaceSidebar();
  }
})();
