(function(){
  var TRANSITION_MS = 150;
  var OVERLAY_OPACITY = '.78';
  var NAV_FLAG = 'de-nav-transition';

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

  function navigateWithTransition(url){
    if(!url || url === window.location.href) return;
    try{
      document.querySelectorAll('.de-sidebar').forEach(function(sidebar){
        if(sidebar.classList.contains('is-expanded') || sidebar.classList.contains('is-pinned')){
          sessionStorage.setItem('de-sidebar-expanded', '1');
        }
      });
      sessionStorage.setItem(NAV_FLAG, '1');
    } catch(e){}
    showOverlay(function(){
      window.location.href = url;
    });
  }

  function initDeSidebarPageTransitions(){
    document.querySelectorAll('.de-sidebar').forEach(function(sidebar){
      sidebar.addEventListener('click', function(event){
      var link = event.target.closest('a[href]');
      if(!link) return;
      var rawHref = link.getAttribute('href') || '';
      if(!rawHref || rawHref.indexOf('javascript:') === 0) return;
      if(event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) return;
      var url = link.href;
      if(!url || url === window.location.href) return;
      event.preventDefault();
      link.classList.add('is-navigating');
      navigateWithTransition(url);
    });
    });
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
    });
  }

  window.deNavigateWithTransition = navigateWithTransition;
  window.deHidePageTransition = hideOverlay;

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
