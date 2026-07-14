(function(){
  'use strict';

  function byId(id){ return document.getElementById(id); }

  function refreshIcons(){
    if(window.lucide && typeof window.lucide.createIcons === 'function'){
      window.lucide.createIcons({ attrs: { 'stroke-width': 1.75 } });
    }
  }

  function initAccessUsersList(){
    var listEl = byId('am-users-list');
    if(!listEl) return;
    if(listEl.getAttribute('data-am-users-ready') === '1') return;
    listEl.setAttribute('data-am-users-ready', '1');

    var searchEl = byId('am-users-search');
    var roleFilterEl = byId('am-users-role-filter');
    var statusFilterEl = byId('am-users-status-filter');
    var sortBtn = byId('am-users-sort');
    var countEl = byId('am-users-count');
    var emptyFilterEl = byId('am-users-empty-filter');
    var paginationEl = byId('am-users-pagination');
    var columnsEl = document.querySelector('.am-users-columns');

    var cards = Array.prototype.slice.call(listEl.querySelectorAll('.am-user-card'));
    var pageSize = 10;
    var currentPage = 1;
    var sortAsc = true;

    function getFilteredCards(){
      var query = (searchEl && searchEl.value || '').trim().toLowerCase();
      var role = roleFilterEl ? roleFilterEl.value : 'all';
      var status = statusFilterEl ? statusFilterEl.value : 'all';

      return cards.filter(function(card){
        var searchData = card.getAttribute('data-search') || '';
        var cardRole = card.getAttribute('data-role') || '';
        var cardStatus = card.getAttribute('data-status') || '';
        var matchesSearch = !query || searchData.indexOf(query) !== -1;
        var matchesRole = role === 'all' || cardRole === role;
        var matchesStatus = status === 'all' || cardStatus === status;
        return matchesSearch && matchesRole && matchesStatus;
      });
    }

    function sortCards(filtered){
      return filtered.slice().sort(function(a, b){
        var nameA = a.getAttribute('data-name') || '';
        var nameB = b.getAttribute('data-name') || '';
        if(nameA < nameB) return sortAsc ? -1 : 1;
        if(nameA > nameB) return sortAsc ? 1 : -1;
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
      prevBtn.innerHTML = '<i data-lucide="chevron-left"></i>';
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
      nextBtn.innerHTML = '<i data-lucide="chevron-right"></i>';
      nextBtn.addEventListener('click', function(){
        if(currentPage < totalPages){
          currentPage += 1;
          applyFilters();
        }
      });
      paginationEl.appendChild(nextBtn);
      refreshIcons();
    }

    function applyFilters(){
      var filtered = sortCards(getFilteredCards());
      var totalPages = Math.max(1, Math.ceil(filtered.length / pageSize));
      if(currentPage > totalPages) currentPage = totalPages;

      cards.forEach(function(card){
        card.classList.add('is-hidden');
        listEl.appendChild(card);
      });

      var visible = filtered.slice((currentPage - 1) * pageSize, currentPage * pageSize);
      visible.forEach(function(card){
        card.classList.remove('is-hidden');
        listEl.appendChild(card);
      });

      if(countEl){
        var suffix = filtered.length === 1 ? ' account' : ' accounts';
        var totalSuffix = cards.length === 1 ? ' account' : ' accounts';
        if(filtered.length === cards.length){
          countEl.textContent = filtered.length + suffix;
        }else{
          countEl.textContent = filtered.length + ' of ' + cards.length + totalSuffix;
        }
      }

      if(emptyFilterEl){
        emptyFilterEl.classList.toggle('hidden', filtered.length > 0);
      }
      if(columnsEl){
        columnsEl.style.display = filtered.length > 0 ? '' : 'none';
      }

      renderPagination(totalPages);
    }

    if(searchEl){
      searchEl.addEventListener('input', function(){
        currentPage = 1;
        applyFilters();
      });
    }
    if(roleFilterEl){
      roleFilterEl.addEventListener('change', function(){
        currentPage = 1;
        applyFilters();
      });
    }
    if(statusFilterEl){
      statusFilterEl.addEventListener('change', function(){
        currentPage = 1;
        applyFilters();
      });
    }
    if(sortBtn){
      sortBtn.addEventListener('click', function(){
        sortAsc = !sortAsc;
        var label = sortBtn.querySelector('span');
        if(label) label.textContent = sortAsc ? 'Sort A–Z' : 'Sort Z–A';
        applyFilters();
      });
      var sortLabel = sortBtn.querySelector('span');
      if(sortLabel) sortLabel.textContent = 'Sort A–Z';
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
