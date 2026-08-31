(function(){
  'use strict';

  function byId(id){ return document.getElementById(id); }

  function amLogsDbg(hypothesisId, location, message, data){
    // #region agent log
    fetch('http://127.0.0.1:7764/ingest/3c15e9d7-8289-4a1b-877f-c72ceeda0753',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'7ee333'},body:JSON.stringify({sessionId:'7ee333',runId:'post-fix',hypothesisId:hypothesisId||'',location:location,message:message,data:data||{},timestamp:Date.now()})}).catch(function(){});
    // #endregion
  }

  function startLogsVibrationProbe(page){
    if(!page || page.getAttribute('data-am-logs-probe') === '1') return;
    page.setAttribute('data-am-logs-probe', '1');
    var header = page.querySelector('.se-sales-header-filters');
    var sidebar = document.querySelector('.de-sidebar');
    var main = document.querySelector('.de-main-wrapper');
    var wrap = byId('am-logs-table-wrap');
    var progress = document.getElementById('de-soft-nav-progress');
    var back = page.querySelector('.su-page-back');
    var titleRow = page.querySelector('.su-title-row');
    var title = page.querySelector('.su-title-row h1');
    var pin = page.querySelector('.sb-pin-btn.de-sb-pin-btn');
    var backSvg = back && back.querySelector('svg');
    var shifts = {sidebar:0, header:0, scroll:0, html:0, progress:0, back:0, title:0, pin:0, margin:0};
    var last = {};
    var n = 0;
    var max = 180;

    function snap(){
      var hr = header ? header.getBoundingClientRect() : {top:0,height:0};
      var sr = sidebar ? sidebar.getBoundingClientRect() : {width:0};
      var mr = main ? main.getBoundingClientRect() : {left:0,width:0};
      var br = back ? back.getBoundingClientRect() : {left:0,top:0};
      var tr = title ? title.getBoundingClientRect() : {left:0};
      var trow = titleRow ? titleRow.getBoundingClientRect() : {left:0,width:0};
      var svg = backSvg ? backSvg.getBoundingClientRect() : {width:0,height:0};
      var pinCs = pin ? getComputedStyle(pin) : null;
      var pageCs = getComputedStyle(page);
      return {
        n: n,
        filterTop: Math.round(hr.top || 0),
        filterH: Math.round(hr.height || 0),
        sbW: Math.round(sr.width || 0),
        mainL: Math.round(mr.left || 0),
        mainW: Math.round(mr.width || 0),
        backL: Math.round(br.left || 0),
        h1L: Math.round(tr.left || 0),
        titleL: Math.round(trow.left || 0),
        titleW: Math.round(trow.width || 0),
        svgW: Math.round(svg.width || 0),
        pinDisplay: pinCs ? pinCs.display : 'missing',
        pageML: pageCs.marginLeft || '',
        scrollW: window.innerWidth - document.documentElement.clientWidth,
        sbExp: !!(sidebar && sidebar.classList.contains('is-expanded')),
        sbPin: !!(sidebar && sidebar.classList.contains('is-pinned')),
        sbHoverSup: !!(sidebar && sidebar.classList.contains('de-sidebar--suppress-hover')),
        htmlClass: document.documentElement.className,
        wrapHidden: wrap ? !!wrap.hidden : null,
        progressOn: !!(progress && progress.classList.contains('is-active')),
        mainEnter: !!(main && main.classList.contains('de-main-enter')),
        sheetCount: document.querySelectorAll('link[rel="stylesheet"]').length
      };
    }

    function tick(){
      n += 1;
      var data = snap();
      if(n > 1){
        var sidebarChanged = last.sbW !== data.sbW || last.mainL !== data.mainL || last.sbExp !== data.sbExp || last.sbHoverSup !== data.sbHoverSup;
        var headerChanged = last.filterH !== data.filterH || last.filterTop !== data.filterTop;
        var scrollChanged = last.scrollW !== data.scrollW;
        var htmlChanged = last.htmlClass !== data.htmlClass;
        var progressChanged = last.progressOn !== data.progressOn || last.mainEnter !== data.mainEnter;
        var backChanged = last.backL !== data.backL || last.h1L !== data.h1L || last.svgW !== data.svgW;
        var titleChanged = last.titleL !== data.titleL || last.titleW !== data.titleW;
        var pinChanged = last.pinDisplay !== data.pinDisplay;
        var marginChanged = last.pageML !== data.pageML;
        if(sidebarChanged || headerChanged || scrollChanged || htmlChanged || progressChanged || backChanged || titleChanged || pinChanged || marginChanged){
          if(sidebarChanged) shifts.sidebar += 1;
          if(headerChanged) shifts.header += 1;
          if(scrollChanged) shifts.scroll += 1;
          if(htmlChanged) shifts.html += 1;
          if(progressChanged) shifts.progress += 1;
          if(backChanged) shifts.back += 1;
          if(titleChanged) shifts.title += 1;
          if(pinChanged) shifts.pin += 1;
          if(marginChanged) shifts.margin += 1;
          amLogsDbg('D', 'access_login_logs.js:probe', 'layout shift', data);
        }
      }
      last = data;
      if(n < max){
        requestAnimationFrame(tick);
      } else {
        amLogsDbg('A', 'access_login_logs.js:probe', 'probe summary', {frames:n, shifts:shifts, last:data});
      }
    }
    requestAnimationFrame(tick);

    if(sidebar && !sidebar.__amLogsMo){
      sidebar.__amLogsMo = new MutationObserver(function(){
        amLogsDbg('A', 'access_login_logs.js:sidebarMO', 'sidebar class', {
          className: sidebar.className,
          w: Math.round(sidebar.getBoundingClientRect().width)
        });
      });
      sidebar.__amLogsMo.observe(sidebar, {attributes:true, attributeFilter:['class']});
    }
  }

  function currentFilterFromUrl(){
    try{
      var value = new URL(window.location.href).searchParams.get('result') || 'all';
      if(value === 'success' || value === 'failed') return value;
    }catch(e){}
    return 'all';
  }

  function currentUserFromUrl(){
    try{
      return (new URL(window.location.href).searchParams.get('user') || '').trim();
    }catch(e){}
    return '';
  }

  function initAccessLoginLogs(){
    var page = byId('access-login-logs-page');
    if(!page) return;
    if(page.getAttribute('data-am-logs-ready') === '1'){
      // #region agent log
      amLogsDbg('B', 'access_login_logs.js:init', 'init skipped already ready', {url: String(location.pathname + location.search)});
      // #endregion
      return;
    }
    page.setAttribute('data-am-logs-ready', '1');

    var tabs = page.querySelectorAll('[data-am-logs-filter]');
    var userInput = page.querySelector('[data-am-logs-user]');
    var searchEl = byId('am-logs-search');
    var searchChip = byId('am-logs-search-chip');
    var tbody = page.querySelector('#am-logs-table-wrap tbody');
    var wrap = byId('am-logs-table-wrap');
    var emptyEl = byId('am-logs-empty');
    var emptyText = byId('am-logs-empty-text');
    var countEl = byId('am-logs-count');
    var rows = page.querySelectorAll('tr[data-success]');
    var total = rows.length;
    var successCount = 0;
    for(var i = 0; i < rows.length; i++){
      if(rows[i].getAttribute('data-success') === '1') successCount += 1;
    }
    var failedCount = total - successCount;
    var activeResult = 'all';
    var activeUser = '';
    var activeSearch = '';
    var searchTimer = null;

    function knownUsernames(){
      var names = [];
      var list = byId('am-logs-user-list');
      if(!list) return names;
      list.querySelectorAll('.se-filter-listbox-option').forEach(function(opt){
        var value = (opt.getAttribute('data-value') || '').trim();
        if(value) names.push(value);
      });
      return names;
    }

    function syncUserListbox(user){
      var label = user || 'All users';
      if(typeof window.resetEpListbox === 'function'){
        window.resetEpListbox('am-logs-user', user || '', label);
        return;
      }
      if(userInput) userInput.value = user || '';
      var valueEl = byId('am-logs-user-value');
      if(valueEl) valueEl.textContent = label;
      var list = byId('am-logs-user-list');
      if(!list) return;
      list.querySelectorAll('.se-filter-listbox-option').forEach(function(opt){
        var on = (opt.getAttribute('data-value') || '') === String(user || '');
        opt.classList.toggle('is-selected', on);
        opt.setAttribute('aria-selected', on ? 'true' : 'false');
      });
    }

    function emptyMessage(filter, user, search){
      if(!total) return 'No sign-in attempts recorded yet.';
      if(search){
        if(user || filter !== 'all') return 'No matching sign-in attempts for the current filters.';
        return 'No sign-in attempts match your search.';
      }
      if(user){
        if(filter === 'success') return 'No successful sign-ins for this user.';
        if(filter === 'failed') return 'No failed sign-in attempts for this user.';
        return 'No sign-in attempts for this user.';
      }
      if(filter === 'success') return 'No successful sign-ins recorded yet.';
      if(filter === 'failed') return 'No failed sign-in attempts recorded yet.';
      return 'No sign-in attempts recorded yet.';
    }

    function rowMatches(row, filter, user, search){
      if(filter === 'success' && row.getAttribute('data-success') !== '1') return false;
      if(filter === 'failed' && row.getAttribute('data-success') !== '0') return false;
      if(user){
        var name = (row.getAttribute('data-username') || '').trim();
        if(name.toLowerCase() !== user.toLowerCase()) return false;
      }
      if(search){
        if(window.hbeBestSearchScore([row.getAttribute('data-search') || row.textContent || ''], search) < 0) return false;
      }
      return true;
    }

    function applyFilters(writeUrl, source){
      var shown = 0;
      var successShown = 0;
      var failedShown = 0;
      var rowList = Array.prototype.slice.call(rows);
      if(activeSearch){
        rowList.sort(function(a, b){
          return window.hbeBestSearchScore([b.getAttribute('data-search') || b.textContent || ''], activeSearch)
            - window.hbeBestSearchScore([a.getAttribute('data-search') || a.textContent || ''], activeSearch);
        });
        if(tbody) rowList.forEach(function(row){ tbody.appendChild(row); });
      }
      for(var r = 0; r < rowList.length; r++){
        var match = rowMatches(rowList[r], activeResult, activeUser, activeSearch);
        rowList[r].classList.toggle('am-logs-row-hidden', !match);
        if(match){
          shown += 1;
          if(rowList[r].getAttribute('data-success') === '1') successShown += 1;
          else failedShown += 1;
        }
      }
      // #region agent log
      amLogsDbg('B', 'access_login_logs.js:applyFilter', 'apply filter', {
        source: source || 'unknown',
        filter: activeResult,
        user: activeUser,
        search: activeSearch,
        writeUrl: !!writeUrl,
        shown: shown,
        wrapHiddenBefore: wrap ? !!wrap.hidden : null,
        historySoft: !!(window.history && window.history.state && window.history.state.deSoftNav)
      });
      // #endregion
      if(tbody) tbody.setAttribute('data-filter', activeResult);
      for(var t = 0; t < tabs.length; t++){
        var active = tabs[t].getAttribute('data-am-logs-filter') === activeResult;
        tabs[t].classList.toggle('is-active', active);
        tabs[t].setAttribute('aria-pressed', active ? 'true' : 'false');
        tabs[t].setAttribute('aria-selected', active ? 'true' : 'false');
      }
      syncUserListbox(activeUser);
      if(searchChip) searchChip.classList.toggle('is-active', !!activeSearch);
      if(countEl){
        var label = shown + ' shown';
        if(activeResult === 'all' && !activeUser && !activeSearch && total){
          label += ' · ' + successCount + ' successful · ' + failedCount + ' failed';
        } else if(activeResult === 'all' && shown && (activeUser || activeSearch)){
          label += ' · ' + successShown + ' successful · ' + failedShown + ' failed';
        }
        countEl.textContent = label;
      }
      var showEmpty = shown === 0;
      if(wrap) wrap.hidden = showEmpty;
      if(emptyEl) emptyEl.hidden = !showEmpty;
      if(emptyText) emptyText.textContent = emptyMessage(activeResult, activeUser, activeSearch);
      if(writeUrl){
        try{
          var url = new URL(window.location.href);
          if(activeResult === 'all') url.searchParams.delete('result');
          else url.searchParams.set('result', activeResult);
          if(!activeUser) url.searchParams.delete('user');
          else url.searchParams.set('user', activeUser);
          if(!activeSearch) url.searchParams.delete('q');
          else url.searchParams.set('q', activeSearch);
          if(window.history && window.history.replaceState){
            window.history.replaceState(window.history.state, '', url.pathname + url.search);
          }
        }catch(e){}
      }
    }

    function currentSearchFromUrl(){
      try{
        return (new URL(window.location.href).searchParams.get('q') || '').trim().toLowerCase();
      }catch(e){}
      return '';
    }

    for(var n = 0; n < tabs.length; n++){
      tabs[n].addEventListener('click', function(ev){
        ev.preventDefault();
        ev.stopPropagation();
        activeResult = this.getAttribute('data-am-logs-filter') || 'all';
        applyFilters(true, 'click');
      });
    }

    window.amLogsUserChanged = function(_root, value){
      activeUser = String(value || '').trim();
      applyFilters(true, 'user');
    };

    if(searchEl){
      searchEl.addEventListener('input', function(){
        var next = String(this.value || '').trim().toLowerCase();
        if(searchTimer) clearTimeout(searchTimer);
        searchTimer = setTimeout(function(){
          activeSearch = next;
          applyFilters(true, 'search');
        }, 120);
      });
      searchEl.addEventListener('search', function(){
        activeSearch = String(this.value || '').trim().toLowerCase();
        applyFilters(true, 'search');
      });
    }

    var tabInfo = [];
    for(var ti = 0; ti < tabs.length; ti++){
      tabInfo.push({
        tag: tabs[ti].tagName,
        href: tabs[ti].getAttribute('href') || '',
        filter: tabs[ti].getAttribute('data-am-logs-filter') || ''
      });
    }
    // #region agent log
    amLogsDbg('C', 'access_login_logs.js:init', 'logs page init', {
      url: String(location.pathname + location.search),
      tabs: tabInfo,
      total: total,
      successCount: successCount,
      failedCount: failedCount,
      userOptions: knownUsernames().length + 1,
      pinDisplay: (function(){
        var pin = page.querySelector('.sb-pin-btn.de-sb-pin-btn');
        return pin ? getComputedStyle(pin).display : 'missing';
      })(),
      pageML: getComputedStyle(page).marginLeft,
      htmlClass: document.documentElement.className
    });
    // #endregion
    startLogsVibrationProbe(page);
    if(!page.__amLogsPopBound){
      page.__amLogsPopBound = true;
      window.addEventListener('popstate', function(){
        // #region agent log
        amLogsDbg('C', 'access_login_logs.js:popstate', 'popstate on logs', {
          url: String(location.pathname + location.search),
          deSoftNav: !!(history.state && history.state.deSoftNav)
        });
        // #endregion
        activeResult = currentFilterFromUrl();
        activeUser = currentUserFromUrl();
        activeSearch = currentSearchFromUrl();
        if(searchEl && searchEl.value !== activeSearch) searchEl.value = activeSearch;
        applyFilters(false, 'popstate');
      });
    }
    activeResult = currentFilterFromUrl();
    activeUser = currentUserFromUrl();
    activeSearch = currentSearchFromUrl();
    if(searchEl && activeSearch) searchEl.value = activeSearch;
    if(activeUser){
      var names = knownUsernames();
      var hasOpt = false;
      for(var o = 0; o < names.length; o++){
        if(names[o] === activeUser){ hasOpt = true; break; }
      }
      if(!hasOpt) activeUser = '';
    }
    applyFilters(false, 'init');
  }

  window.initAccessLoginLogs = initAccessLoginLogs;

  if(document.readyState === 'loading'){
    document.addEventListener('DOMContentLoaded', initAccessLoginLogs);
  } else {
    initAccessLoginLogs();
  }
})();
