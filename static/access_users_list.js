(function(){
  'use strict';

  function byId(id){ return document.getElementById(id); }

  function refreshIcons(){
    if(window.lucide && typeof window.lucide.createIcons === 'function'){
      window.lucide.createIcons({ attrs: { 'stroke-width': 1.75 } });
    }
  }

  function closeAllMenus(except){
    document.querySelectorAll('.am-user-menu.is-open').forEach(function(menu){
      if(except && menu === except) return;
      menu.classList.remove('is-open');
      var btn = menu.querySelector('.am-user-menu-btn');
      var panel = menu.querySelector('.am-user-menu-panel');
      if(btn) btn.setAttribute('aria-expanded', 'false');
      if(panel) panel.hidden = true;
    });
  }

  function initAccessUsersList(){
    var listEl = byId('am-users-list');
    if(!listEl) return;
    if(listEl.getAttribute('data-am-users-ready') === '1') return;
    listEl.setAttribute('data-am-users-ready', '1');

    var searchEl = byId('am-users-search');
    var searchChip = byId('am-users-search-chip');
    var roleFilterEl = byId('am-users-role-filter');
    var statusFilterEl = byId('am-users-status-filter');
    var countEl = byId('am-users-count');
    var emptyFilterEl = byId('am-users-empty-filter');
    var paginationEl = byId('am-users-pagination');
    var gridWrap = byId('am-users-grid-wrap') || listEl.closest('.am-users-grid-wrap');

    var rows = Array.prototype.slice.call(listEl.querySelectorAll('.am-user-row'));
    var pageSize = 12;
    var currentPage = 1;

    function getFilteredRows(){
      var query = (searchEl && searchEl.value || '').trim().toLowerCase();
      var role = roleFilterEl ? roleFilterEl.value : 'all';
      var status = statusFilterEl ? statusFilterEl.value : 'all';

      return rows.filter(function(row){
        var searchData = row.getAttribute('data-search') || '';
        var rowRole = row.getAttribute('data-role') || '';
        var rowStatus = row.getAttribute('data-status') || '';
        var matchesSearch = !query || searchData.indexOf(query) !== -1;
        var matchesRole = role === 'all' || rowRole === role;
        var matchesStatus = status === 'all' || rowStatus === status;
        return matchesSearch && matchesRole && matchesStatus;
      });
    }

    function sortRows(filtered){
      return filtered.slice().sort(function(a, b){
        var nameA = a.getAttribute('data-name') || '';
        var nameB = b.getAttribute('data-name') || '';
        if(nameA < nameB) return -1;
        if(nameA > nameB) return 1;
        return 0;
      });
    }

    function renderPagination(totalPages){
      if(!paginationEl) return;
      if(totalPages <= 1){
        paginationEl.hidden = true;
        paginationEl.innerHTML = '';
        return;
      }
      paginationEl.hidden = false;
      paginationEl.innerHTML = '';

      var prevBtn = document.createElement('button');
      prevBtn.type = 'button';
      prevBtn.className = 'am-page-btn';
      prevBtn.setAttribute('aria-label', 'Previous page');
      prevBtn.disabled = currentPage <= 1;
      prevBtn.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><polyline points="15 18 9 12 15 6"/></svg>';
      prevBtn.addEventListener('click', function(){
        if(currentPage > 1){
          currentPage -= 1;
          applyFilters();
        }
      });
      paginationEl.appendChild(prevBtn);

      for(var page = 1; page <= totalPages; page += 1){
        var pageBtn = document.createElement('button');
        pageBtn.type = 'button';
        pageBtn.className = 'am-page-btn' + (page === currentPage ? ' is-active' : '');
        pageBtn.textContent = String(page);
        pageBtn.setAttribute('aria-label', 'Page ' + page);
        pageBtn.addEventListener('click', (function(targetPage){
          return function(){
            currentPage = targetPage;
            applyFilters();
          };
        })(page));
        paginationEl.appendChild(pageBtn);
      }

      var nextBtn = document.createElement('button');
      nextBtn.type = 'button';
      nextBtn.className = 'am-page-btn';
      nextBtn.setAttribute('aria-label', 'Next page');
      nextBtn.disabled = currentPage >= totalPages;
      nextBtn.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><polyline points="9 18 15 12 9 6"/></svg>';
      nextBtn.addEventListener('click', function(){
        if(currentPage < totalPages){
          currentPage += 1;
          applyFilters();
        }
      });
      paginationEl.appendChild(nextBtn);
    }

    function applyFilters(){
      var filtered = sortRows(getFilteredRows());
      var totalPages = Math.max(1, Math.ceil(filtered.length / pageSize));
      if(currentPage > totalPages) currentPage = totalPages;

      rows.forEach(function(row){
        row.classList.add('is-hidden');
        listEl.appendChild(row);
      });

      var visible = filtered.slice((currentPage - 1) * pageSize, currentPage * pageSize);
      visible.forEach(function(row){
        row.classList.remove('is-hidden');
        listEl.appendChild(row);
      });

      if(countEl){
        var suffix = filtered.length === 1 ? ' account' : ' accounts';
        var totalSuffix = rows.length === 1 ? ' account' : ' accounts';
        if(filtered.length === rows.length){
          countEl.textContent = filtered.length + suffix;
        }else{
          countEl.textContent = filtered.length + ' of ' + rows.length + totalSuffix;
        }
      }

      if(emptyFilterEl){
        emptyFilterEl.classList.toggle('hidden', filtered.length > 0);
      }
      if(gridWrap){
        gridWrap.hidden = filtered.length === 0;
      }
      if(searchChip){
        searchChip.classList.toggle('is-active', !!(searchEl && (searchEl.value || '').trim()));
      }

      renderPagination(totalPages);
    }

    function onFilterChange(){
      currentPage = 1;
      applyFilters();
    }

    window.amOnUsersFilterChange = function(){
      onFilterChange();
    };

    if(searchEl){
      searchEl.addEventListener('input', onFilterChange);
    }

    function goEdit(card){
      var href = card && card.getAttribute('data-edit-href');
      if(!href) return;
      if(typeof window.deNavigateWithTransition === 'function'){
        window.deNavigateWithTransition(href);
      } else {
        window.location.href = href;
      }
    }

    listEl.addEventListener('click', function(e){
      var btn = e.target.closest('.am-user-menu-btn');
      if(btn && listEl.contains(btn)){
        e.preventDefault();
        e.stopPropagation();
        var menu = btn.closest('.am-user-menu');
        var panel = menu && menu.querySelector('.am-user-menu-panel');
        var willOpen = menu && !menu.classList.contains('is-open');
        closeAllMenus();
        if(willOpen && menu && panel){
          menu.classList.add('is-open');
          btn.setAttribute('aria-expanded', 'true');
          panel.hidden = false;
        }
        return;
      }

      if(e.target.closest('.am-user-menu')){
        e.stopPropagation();
        return;
      }

      var card = e.target.closest('.am-user-card[data-edit-href]');
      if(card && listEl.contains(card)){
        goEdit(card);
      }
    });

    listEl.addEventListener('keydown', function(e){
      if(e.key !== 'Enter' && e.key !== ' ') return;
      if(e.target.closest('.am-user-menu')) return;
      var card = e.target.closest('.am-user-card[data-edit-href]');
      if(!card || !listEl.contains(card) || e.target !== card) return;
      e.preventDefault();
      goEdit(card);
    });

    document.addEventListener('click', function(){
      closeAllMenus();
    });
    document.addEventListener('keydown', function(e){
      if(e.key === 'Escape') closeAllMenus();
    });

    if(typeof window.initEpListboxes === 'function'){
      try{ window.initEpListboxes(); }catch(err){}
    }

    applyFilters();
    refreshIcons();
  }

  window.initAccessUsersList = initAccessUsersList;

  if(document.readyState === 'loading'){
    document.addEventListener('DOMContentLoaded', initAccessUsersList);
  } else {
    initAccessUsersList();
  }
})();
