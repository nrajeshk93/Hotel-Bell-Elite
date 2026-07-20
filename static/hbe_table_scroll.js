/**
 * Horizontal edge auto-scroll for dense ledger/list tables.
 * When the cursor nears the left/right edge of a scroll wrap, pan to reveal clipped columns.
 */
(function (global) {
  var SELECTOR = [
    '.hbe-scroll-panel .pl-table-wrap',
    '.hbe-scroll-panel .emp-table-wrap',
    '.hbe-scroll-panel .sm-table-wrap',
    '.pl-list-panel--scroll .pl-table-wrap',
    '.emp-list-panel--scroll .emp-table-wrap',
    '.sm-list-panel--scroll .sm-table-wrap',
  ].join(',');

  var EDGE = 64;
  var MAX_SPEED = 16;

  function bindEdgeScroll(wrap) {
    if (!wrap || wrap.__hbeEdgeScrollBound) return;
    wrap.__hbeEdgeScrollBound = true;

    var dir = 0;
    var speed = 0;
    var raf = 0;

    function maxScrollLeft() {
      return Math.max(0, wrap.scrollWidth - wrap.clientWidth);
    }

    function tick() {
      raf = 0;
      if (!dir || !speed) return;
      var next = wrap.scrollLeft + dir * speed;
      var max = maxScrollLeft();
      wrap.scrollLeft = Math.max(0, Math.min(max, next));
      if ((dir < 0 && wrap.scrollLeft <= 0) || (dir > 0 && wrap.scrollLeft >= max)) {
        dir = 0;
        speed = 0;
        wrap.classList.remove('is-edge-scroll-left', 'is-edge-scroll-right');
        return;
      }
      raf = requestAnimationFrame(tick);
    }

    function stop() {
      dir = 0;
      speed = 0;
      wrap.classList.remove('is-edge-scroll-left', 'is-edge-scroll-right');
      if (raf) {
        cancelAnimationFrame(raf);
        raf = 0;
      }
    }

    wrap.addEventListener('mousemove', function (e) {
      if (maxScrollLeft() <= 1) {
        stop();
        return;
      }
      // Actions sit on the right edge — edge-pan steals hover and hides data-tip tags.
      if (e.target && e.target.closest && e.target.closest('.act-grp, .act-btn, .pl-col-actions')) {
        stop();
        return;
      }
      var rect = wrap.getBoundingClientRect();
      var x = e.clientX - rect.left;
      var width = rect.width || 1;
      var nextDir = 0;
      var nextSpeed = 0;

      if (x >= width - EDGE) {
        nextDir = 1;
        nextSpeed = Math.max(2, Math.ceil(MAX_SPEED * ((x - (width - EDGE)) / EDGE)));
      } else if (x <= EDGE) {
        nextDir = -1;
        nextSpeed = Math.max(2, Math.ceil(MAX_SPEED * ((EDGE - x) / EDGE)));
      }

      dir = nextDir;
      speed = nextSpeed;
      wrap.classList.toggle('is-edge-scroll-left', dir < 0);
      wrap.classList.toggle('is-edge-scroll-right', dir > 0);
      if (dir && !raf) raf = requestAnimationFrame(tick);
      if (!dir && raf) {
        cancelAnimationFrame(raf);
        raf = 0;
      }
    });

    wrap.addEventListener('mouseleave', stop);
    wrap.addEventListener('blur', stop);
  }

  function initHbeTableScroll() {
    document.querySelectorAll(SELECTOR).forEach(bindEdgeScroll);
  }

  global.initHbeTableScroll = initHbeTableScroll;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initHbeTableScroll);
  } else {
    initHbeTableScroll();
  }

  // Soft-nav remounts main content — rebind after swaps.
  document.addEventListener('DOMContentLoaded', function () {
    var orig = global.deWorkspaceReinit;
    if (typeof orig === 'function' && !orig.__hbeTableScrollWrapped) {
      var wrapped = function () {
        var result = orig.apply(this, arguments);
        initHbeTableScroll();
        return result;
      };
      wrapped.__hbeTableScrollWrapped = true;
      global.deWorkspaceReinit = wrapped;
    }
  });
})(window);
