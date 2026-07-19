(function(){
  'use strict';

  var ICON_ENTER = '<svg class="de-fs-icon-enter" viewBox="0 0 24 24" aria-hidden="true"><path d="M8 3H5a2 2 0 0 0-2 2v3"/><path d="M16 3h3a2 2 0 0 1 2 2v3"/><path d="M8 21H5a2 2 0 0 1-2-2v-3"/><path d="M16 21h3a2 2 0 0 0 2-2v-3"/></svg>';
  var ICON_EXIT = '<svg class="de-fs-icon-exit" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 14h6v6"/><path d="M20 10h-6V4"/><path d="M14 10 3 21"/><path d="M10 14 21 3"/></svg>';

  var STORAGE_KEY = 'de-fullscreen-active';
  var NAV_TS_KEY = 'de-fullscreen-nav-ts';
  var FS_ROOT_ID = 'de-fs-app';

  var TOOL_CONTAINERS = [
    '.de-header-tools',
    '.am-header-tools',
    '.ba-header-tools',
    '.db-home-tools',
    '.su-header-tools',
    '.sup-header-actions',
    '.rdx-header-tools'
  ];

  var TOP_CONTAINERS = [
    '.sr-header-top',
    '.sup-header-top',
    '.rdx-header-top'
  ];

  /* Page headers that pin the control to the top-right corner when no tools row exists */
  var CORNER_HOSTS = [
    '.ep-header.topbar',
    'header.se-sales-header.su-header',
    '.am-header',
    '.db-home-header'
  ];

  var buttons = [];
  var supported = false;
  var toastTimer = null;
  var restoreTimer = null;
  var userExitIntent = false;
  var escExitPending = false;
  var pageUnloading = false;
  var softNavInProgress = false;
  var restoreDelays = [0, 120, 400];

  function loadStylesheet(){
    if(document.querySelector('link[data-de-fullscreen-css]')) return;
    var link = document.createElement('link');
    link.rel = 'stylesheet';
    link.setAttribute('data-de-fullscreen-css', '1');
    var script = document.currentScript;
    link.href = (script && script.getAttribute('data-css')) || '/static/de_fullscreen.css?v=4';
    document.head.appendChild(link);
  }

  function ensureFullscreenRoot(){
    var root = document.getElementById(FS_ROOT_ID);
    if(root) return root;
    root = document.createElement('div');
    root.id = FS_ROOT_ID;
    var nodes = Array.from(document.body.childNodes);
    nodes.forEach(function(node){
      root.appendChild(node);
    });
    document.body.appendChild(root);
    return root;
  }

  function getFullscreenTargets(){
    var root = document.getElementById(FS_ROOT_ID);
    var targets = [];
    // Prefer <html>: soft page swaps never remove it, so fullscreen survives navigation.
    if(document.documentElement) targets.push(document.documentElement);
    if(root) targets.push(root);
    if(document.body) targets.push(document.body);
    return targets;
  }

  function navRestoreWindowOpen(){
    if(softNavInProgress) return true;
    try{
      var ts = Number(sessionStorage.getItem(NAV_TS_KEY) || 0);
      return !!(ts && (Date.now() - ts) < 4000);
    } catch(e){
      return false;
    }
  }

  /** Call BEFORE history.pushState while fullscreen is still active. */
  function armForSoftNav(){
    if(!getFullscreenElement()) return false;
    setPreference(true);
    try{
      sessionStorage.setItem(NAV_TS_KEY, String(Date.now()));
    } catch(e){}
    ensureFullscreenRoot();
    return true;
  }

  /**
   * Call during the click gesture around soft-nav.
   * - If still fullscreen: keep the lock.
   * - If pushState already dropped FS but we armed via armForSoftNav: re-enter now
   *   (still within the user gesture so the browser allows it).
   * Never enter fullscreen from a cold/stale flag when the user was not in FS.
   */
  function preserveFullscreenForNavigation(){
    if(getFullscreenElement()){
      setPreference(true);
      try{ sessionStorage.setItem(NAV_TS_KEY, String(Date.now())); } catch(e){}
      ensureFullscreenRoot();
      updateButtons();
      return true;
    }
    if(getPreference() && (softNavInProgress || navRestoreWindowOpen())){
      ensureFullscreenRoot();
      if(attemptRestoreSync()) return true;
      requestAppFullscreen().then(updateButtons).catch(function(){});
      return true;
    }
    return false;
  }

  function getPreference(){
    try{
      return sessionStorage.getItem(STORAGE_KEY) === '1';
    } catch(e){
      return false;
    }
  }

  function setPreference(active){
    try{
      if(active){
        sessionStorage.setItem(STORAGE_KEY, '1');
      } else {
        sessionStorage.removeItem(STORAGE_KEY);
        sessionStorage.removeItem(NAV_TS_KEY);
      }
    } catch(e){}
  }

  function getFullscreenElement(){
    return document.fullscreenElement
      || document.webkitFullscreenElement
      || document.mozFullScreenElement
      || document.msFullscreenElement
      || null;
  }

  function requestOnNode(node){
    var fn = node.requestFullscreen
      || node.webkitRequestFullscreen
      || node.mozRequestFullScreen
      || node.msRequestFullscreen;
    if(!fn) return false;
    try{
      fn.call(node);
      return true;
    } catch(err){
      return false;
    }
  }

  function requestOnNodeAsync(node){
    var fn = node.requestFullscreen
      || node.webkitRequestFullscreen
      || node.mozRequestFullScreen
      || node.msRequestFullscreen;
    if(!fn) return Promise.reject(new Error('unsupported'));
    try{
      var result = fn.call(node);
      return result && typeof result.then === 'function' ? result : Promise.resolve();
    } catch(err){
      return Promise.reject(err);
    }
  }

  function attemptRestoreSync(){
    if(!getPreference() || !supported || getFullscreenElement()) return false;
    var targets = getFullscreenTargets();
    for(var i = 0; i < targets.length; i++){
      if(targets[i] && requestOnNode(targets[i])){
        updateButtons();
        return true;
      }
    }
    return false;
  }

  function requestAppFullscreen(){
    ensureFullscreenRoot();
    var targets = getFullscreenTargets();
    var chain = Promise.reject(new Error('unsupported'));
    targets.forEach(function(node){
      if(!node) return;
      chain = chain.catch(function(){
        return requestOnNodeAsync(node);
      });
    });
    return chain;
  }

  function exitAppFullscreen(){
    var fn = document.exitFullscreen
      || document.webkitExitFullscreen
      || document.mozCancelFullScreen
      || document.msExitFullscreen;
    if(!fn) return Promise.reject(new Error('unsupported'));
    try{
      var result = fn.call(document);
      return result && typeof result.then === 'function' ? result : Promise.resolve();
    } catch(err){
      return Promise.reject(err);
    }
  }

  function detectSupport(){
    return getFullscreenTargets().some(function(node){
      return !!(node && (
        node.requestFullscreen
        || node.webkitRequestFullscreen
        || node.mozRequestFullScreen
        || node.msRequestFullscreen
      ));
    });
  }

  function showToast(message){
    var toast = document.querySelector('.de-fullscreen-toast');
    if(!toast){
      toast = document.createElement('div');
      toast.className = 'de-fullscreen-toast';
      toast.setAttribute('role', 'status');
      toast.setAttribute('aria-live', 'polite');
      document.body.appendChild(toast);
    }
    toast.textContent = message;
    toast.classList.add('is-visible');
    if(toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(function(){
      toast.classList.remove('is-visible');
    }, 3200);
  }

  var nativeConfirm = window.confirm.bind(window);
  var confirmResolver = null;

  function ensureConfirmModal(){
    var existing = document.getElementById('de-confirm-modal');
    if(existing) return existing;
    var backdrop = document.createElement('div');
    backdrop.id = 'de-confirm-modal';
    backdrop.className = 'de-confirm-backdrop';
    backdrop.setAttribute('aria-hidden', 'true');
    backdrop.innerHTML =
      '<div class="de-confirm-box" role="dialog" aria-modal="true" aria-labelledby="de-confirm-title">' +
        '<div class="de-confirm-title" id="de-confirm-title">Please confirm</div>' +
        '<p class="de-confirm-message" id="de-confirm-message"></p>' +
        '<div class="de-confirm-actions">' +
          '<button type="button" class="btn de-confirm-cancel" id="de-confirm-cancel">Cancel</button>' +
          '<button type="button" class="btn btn-primary de-confirm-ok" id="de-confirm-ok">Confirm</button>' +
        '</div>' +
      '</div>';
    (document.getElementById(FS_ROOT_ID) || document.body).appendChild(backdrop);

    function finish(result){
      backdrop.classList.remove('open');
      backdrop.setAttribute('aria-hidden', 'true');
      var resolve = confirmResolver;
      confirmResolver = null;
      if(resolve) resolve(!!result);
    }
    backdrop.querySelector('#de-confirm-cancel').addEventListener('click', function(){ finish(false); });
    backdrop.querySelector('#de-confirm-ok').addEventListener('click', function(){ finish(true); });
    backdrop.addEventListener('click', function(event){
      if(event.target === backdrop) finish(false);
    });
    document.addEventListener('keydown', function(event){
      if(!backdrop.classList.contains('open')) return;
      if(event.key === 'Escape'){
        event.preventDefault();
        finish(false);
      } else if(event.key === 'Enter'){
        event.preventDefault();
        finish(true);
      }
    });
    return backdrop;
  }

  /**
   * In-app confirm that does NOT call window.confirm (native dialogs exit fullscreen).
   * Always preferred when fullscreen is active/locked; otherwise uses native confirm.
   */
  function confirmAsync(message){
    var text = message == null ? '' : String(message);
    if(!getPreference() && !getFullscreenElement()){
      return Promise.resolve(nativeConfirm(text));
    }
    return new Promise(function(resolve){
      if(confirmResolver){
        confirmResolver(false);
        confirmResolver = null;
      }
      var backdrop = ensureConfirmModal();
      var msg = backdrop.querySelector('#de-confirm-message');
      if(msg) msg.textContent = text;
      confirmResolver = resolve;
      backdrop.classList.add('open');
      backdrop.setAttribute('aria-hidden', 'false');
      var okBtn = backdrop.querySelector('#de-confirm-ok');
      if(okBtn) okBtn.focus();
    });
  }

  function installConfirmGuard(){
    window.confirm = function(message){
      // Native confirm always exits browser fullscreen. Block it while FS is preferred.
      // Callers must use window.deConfirm(...) / deFullscreen.confirm(...).
      if(getPreference() || getFullscreenElement()){
        return false;
      }
      return nativeConfirm(message == null ? '' : String(message));
    };
    var nativeAlert = window.alert.bind(window);
    window.alert = function(message){
      if(getPreference() || getFullscreenElement()){
        showToast(message == null ? '' : String(message));
        return;
      }
      return nativeAlert(message);
    };
  }

  function updateButtons(){
    var active = !!getFullscreenElement();
    buttons.forEach(function(btn){
      if(!btn.isConnected) return;
      btn.classList.toggle('is-fullscreen', active);
      btn.setAttribute('aria-pressed', active ? 'true' : 'false');
      btn.setAttribute('aria-label', active ? 'Exit full screen' : 'Enter full screen');
      btn.title = active ? 'Exit full screen' : 'Full screen';
    });
  }

  function attemptRestore(){
    if(!getPreference() || !supported || getFullscreenElement()) return Promise.resolve();
    return requestAppFullscreen().then(updateButtons).catch(function(){});
  }

  function scheduleRestore(){
    if(!getPreference() || !supported || softNavInProgress) return;
    if(restoreTimer) clearTimeout(restoreTimer);
    restoreTimer = setTimeout(function(){
      restoreTimer = null;
      attemptRestoreSync();
      attemptRestore();
    }, 80);
  }

  function restoreAfterNavigation(){
    // Only re-enter when soft-nav dropped an active fullscreen session.
    if(!getPreference() || !supported) return;
    if(getFullscreenElement()){
      updateButtons();
      return;
    }
    // Require that we still intend to restore (preference set while FS was live).
    attemptRestoreSync();
    restoreDelays.forEach(function(delay){
      setTimeout(function(){
        if(!getPreference() || getFullscreenElement()) return;
        attemptRestoreSync();
      }, delay);
    });
  }

  function prepareNavigation(){
    // Only mark navigation while actually fullscreen.
    if(!getFullscreenElement()) return;
    setPreference(true);
    try{
      sessionStorage.setItem(NAV_TS_KEY, String(Date.now()));
    } catch(e){}
  }

  function isIgnoredClickTarget(target){
    return !!(target && target.closest('.de-fullscreen-btn'));
  }

  function preferSoftNavigation(url){
    if(!getFullscreenElement()) return false;
    if(typeof window.deSoftRefresh !== 'function') return false;
    setPreference(true);
    window.deSoftRefresh(url || window.location.href);
    return true;
  }

  function installLocationGuards(){
    if(window.__deFsLocationGuards) return;
    window.__deFsLocationGuards = true;

    try{
      var reload = window.location.reload.bind(window.location);
      window.location.reload = function(){
        if(preferSoftNavigation()) return;
        if(getFullscreenElement()) prepareNavigation();
        return reload.apply(window.location, arguments);
      };
    } catch(e){}

    try{
      var assign = window.location.assign.bind(window.location);
      window.location.assign = function(url){
        if(preferSoftNavigation(url)) return;
        if(getFullscreenElement()) prepareNavigation();
        return assign.call(window.location, url);
      };
    } catch(e){}

    try{
      var replace = window.location.replace.bind(window.location);
      window.location.replace = function(url){
        if(preferSoftNavigation(url)) return;
        if(getFullscreenElement()) prepareNavigation();
        return replace.call(window.location, url);
      };
    } catch(e){}

    try{
      var hrefDesc = Object.getOwnPropertyDescriptor(Location.prototype, 'href');
      if(hrefDesc && hrefDesc.set && hrefDesc.get){
        Object.defineProperty(Location.prototype, 'href', {
          configurable: true,
          enumerable: hrefDesc.enumerable,
          get: function(){ return hrefDesc.get.call(this); },
          set: function(url){
            if(this === window.location && preferSoftNavigation(url)) return;
            if(this === window.location && getFullscreenElement()) prepareNavigation();
            return hrefDesc.set.call(this, url);
          }
        });
      }
    } catch(e){}
  }

  function bindNavigationPreserve(){
    document.addEventListener('pointerdown', function(event){
      var link = event.target.closest('a[href]');
      if(!link) return;
      var href = link.getAttribute('href') || '';
      if(!href || href.indexOf('javascript:') === 0 || href.charAt(0) === '#') return;
      if(link.target && link.target !== '_self') return;
      // Only preserve when currently fullscreen — never arm FS from a stale flag.
      if(!getFullscreenElement()) return;
      setPreference(true);
      prepareNavigation();
    }, true);
  }

  function bindIndexHomeLink(){
    document.addEventListener('click', function(event){
      var link = event.target.closest('.de-sidebar a[href], .sidebar a[href]');
      if(!link) return;
      var href = link.getAttribute('href') || '';
      if(href.indexOf('javascript:') !== 0) return;
      if(!getFullscreenElement()) return;
      setPreference(true);
      setTimeout(updateButtons, 220);
      setTimeout(updateButtons, 500);
    }, true);
  }

  function wrapTransitionHooks(){
    var origHide = window.deHidePageTransition;
    if(typeof origHide === 'function' && !origHide.__deFullscreenWrapped){
      var wrapped = function(){
        var result = origHide.apply(this, arguments);
        if(!softNavInProgress) updateButtons();
        return result;
      };
      wrapped.__deFullscreenWrapped = true;
      window.deHidePageTransition = wrapped;
    }
  }

  function wrapFunction(name){
    var fn = window[name];
    if(typeof fn !== 'function' || fn.__deFullscreenWrapped) return;
    var wrapped = function(){
      var wasFs = !!getFullscreenElement();
      var result = fn.apply(this, arguments);
      // Only restore if we were actually fullscreen before the view swap.
      if(wasFs){
        setPreference(true);
        setTimeout(function(){
          updateButtons();
          if(!getFullscreenElement()) attemptRestoreSync();
        }, 240);
      }
      return result;
    };
    wrapped.__deFullscreenWrapped = true;
    window[name] = wrapped;
  }

  function wrapIndexViewHelpers(){
    ['showDashboard', 'showDeWorkspace', 'openDeWorkspaceDirect', 'openApp', '_fadeInSection'].forEach(wrapFunction);
  }

  function onFullscreenChange(){
    updateButtons();
    if(getFullscreenElement()){
      escExitPending = false;
      setPreference(true);
      return;
    }
    if(pageUnloading) return;
    // Explicit Exit button — always clear.
    if(userExitIntent){
      userExitIntent = false;
      escExitPending = false;
      setPreference(false);
      return;
    }
    // Soft-nav / pushState often drops fullscreen; keep preference so restore can run.
    if(softNavInProgress || navRestoreWindowOpen()) return;
    // Esc or browser UI exit while idle — stay out; do not re-enter on nav clicks.
    escExitPending = false;
    setPreference(false);
  }

  function toggleFullscreen(){
    if(!supported){
      showToast('Full screen is not supported in this browser.');
      return;
    }
    if(getFullscreenElement()){
      userExitIntent = true;
      setPreference(false);
      exitAppFullscreen().catch(function(){
        userExitIntent = false;
        showToast('Unable to exit full screen.');
      });
      return;
    }
    setPreference(true);
    ensureFullscreenRoot();
    if(attemptRestoreSync()) return;
    requestAppFullscreen().then(updateButtons).catch(function(){
      setPreference(false);
      showToast('Unable to enter full screen.');
    });
  }

  function createButton(){
    if(!supported) return null;
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'de-fullscreen-btn';
    btn.setAttribute('aria-pressed', 'false');
    btn.setAttribute('aria-label', 'Enter full screen');
    btn.title = 'Full screen';
    btn.innerHTML = ICON_ENTER + ICON_EXIT;
    btn.addEventListener('click', toggleFullscreen);
    buttons.push(btn);
    return btn;
  }

  function preferredInsertTarget(container){
    return container.querySelector('.db-profile')
      || container.querySelector('.de-logout-btn')
      || container.querySelector('a[href*="logout"]')
      || null;
  }

  function mountInContainer(container, useTopSlot, corner){
    if(!supported || !container || container.querySelector('.de-fullscreen-btn')) return;
    var btn = createButton();
    if(!btn) return;
    if(useTopSlot){
      var slot = document.createElement('div');
      slot.className = 'de-fullscreen-slot' + (corner ? ' de-fullscreen-slot--corner' : '');
      slot.appendChild(btn);
      container.appendChild(slot);
      return;
    }
    var before = preferredInsertTarget(container);
    if(before){
      container.insertBefore(btn, before);
    } else {
      container.appendChild(btn);
    }
  }

  function topRowHasToolContainer(topRow){
    for(var i = 0; i < TOOL_CONTAINERS.length; i++){
      if(topRow.querySelector(TOOL_CONTAINERS[i])) return true;
    }
    return false;
  }

  function hostAlreadyHasFullscreen(host){
    if(!host) return false;
    if(host.querySelector('.de-fullscreen-btn')) return true;
    /* Avoid double-mount when a nested tools/top row already owns the button */
    for(var i = 0; i < TOOL_CONTAINERS.length; i++){
      if(host.querySelector(TOOL_CONTAINERS[i] + ' .de-fullscreen-btn')) return true;
    }
    for(var j = 0; j < TOP_CONTAINERS.length; j++){
      if(host.querySelector(TOP_CONTAINERS[j] + ' .de-fullscreen-btn')) return true;
    }
    return false;
  }

  function clearMisplacedButtons(){
    /* Fullscreen must not live inside wrapping filter toolbars */
    document.querySelectorAll('.topbar-actions .de-fullscreen-btn, .ep-topbar-toolbar .de-fullscreen-btn').forEach(function(btn){
      var slot = btn.closest('.de-fullscreen-slot');
      var node = slot || btn;
      if(node && node.parentNode) node.parentNode.removeChild(node);
    });
    buttons = buttons.filter(function(btn){ return btn.isConnected; });
  }

  function mountButtons(){
    if(!supported){
      document.querySelectorAll('.de-fullscreen-btn, .de-fullscreen-slot').forEach(function(node){
        if(node && node.parentNode) node.parentNode.removeChild(node);
      });
      buttons = [];
      return;
    }
    clearMisplacedButtons();
    buttons = buttons.filter(function(btn){ return btn.isConnected; });
    var seen = new Set();

    TOOL_CONTAINERS.forEach(function(selector){
      document.querySelectorAll(selector).forEach(function(container){
        if(seen.has(container)) return;
        seen.add(container);
        mountInContainer(container, false);
      });
    });

    TOP_CONTAINERS.forEach(function(selector){
      document.querySelectorAll(selector).forEach(function(container){
        if(seen.has(container) || topRowHasToolContainer(container)) return;
        if(container.querySelector('.de-fullscreen-btn')) return;
        seen.add(container);
        mountInContainer(container, true);
      });
    });

    CORNER_HOSTS.forEach(function(selector){
      document.querySelectorAll(selector).forEach(function(host){
        if(seen.has(host) || hostAlreadyHasFullscreen(host)) return;
        seen.add(host);
        mountInContainer(host, true, true);
      });
    });

    updateButtons();
  }

  function bindFullscreenEvents(){
    ['fullscreenchange', 'webkitfullscreenchange', 'mozfullscreenchange', 'MSFullscreenChange'].forEach(function(eventName){
      document.addEventListener(eventName, onFullscreenChange);
    });
    document.addEventListener('keydown', function(event){
      if(event.key === 'Escape' && getFullscreenElement()){
        escExitPending = true;
      }
    });
    window.addEventListener('pagehide', function(){
      pageUnloading = true;
    });
    window.addEventListener('pageshow', function(){
      pageUnloading = false;
      restoreAfterNavigation();
    });
  }

  function init(){
    loadStylesheet();
    supported = detectSupport();
    if(!supported){
      try{ sessionStorage.removeItem(STORAGE_KEY); } catch(e){}
      mountButtons();
      return;
    }
    // Clear stale "preferred" flag unless we are already fullscreen.
    // Prevents sidebar / page clicks from auto-entering fullscreen.
    if(!getFullscreenElement()){
      setPreference(false);
    } else {
      setPreference(true);
      ensureFullscreenRoot();
    }
    installLocationGuards();
    installConfirmGuard();
    wrapTransitionHooks();
    wrapIndexViewHelpers();
    mountButtons();
    bindFullscreenEvents();
    bindNavigationPreserve();
    bindIndexHomeLink();
    updateButtons();
    setTimeout(wrapIndexViewHelpers, 0);
    setTimeout(wrapIndexViewHelpers, 800);
    setTimeout(installLocationGuards, 0);
  }

  function reinit(){
    buttons = [];
    mountButtons();
    wrapIndexViewHelpers();
    updateButtons();
  }

  function setSoftNavInProgress(active){
    softNavInProgress = !!active;
  }

  function isSoftNavInProgress(){
    return softNavInProgress;
  }

  window.deFullscreen = {
    isActive: function(){ return !!getFullscreenElement(); },
    isPreferred: getPreference,
    ensureRoot: ensureFullscreenRoot,
    restoreIfNeeded: function(){
      attemptRestoreSync();
      return attemptRestore();
    },
    restoreAfterNavigation: restoreAfterNavigation,
    prepareNavigation: prepareNavigation,
    armForSoftNav: armForSoftNav,
    preserveForNavigation: preserveFullscreenForNavigation,
    confirm: confirmAsync,
    reinit: reinit,
    updateUi: updateButtons,
    setSoftNavInProgress: setSoftNavInProgress,
    isSoftNavInProgress: isSoftNavInProgress,
    getSwapRoot: function(){
      return getPreference() || getFullscreenElement() ? ensureFullscreenRoot() : document.body;
    }
  };
  window.deConfirm = confirmAsync;

  if(document.readyState === 'loading'){
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
