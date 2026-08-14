/**
 * Edge auto-scroll for dense ledger/list tables.
 * Cursor toward the right/bottom (or left/top) pans clipped columns and rows.
 */
(function (global) {
  var SELECTOR = [
    '.hbe-scroll-panel .pl-table-wrap',
    '.hbe-scroll-panel .emp-table-wrap',
    '.hbe-scroll-panel .sm-table-wrap',
    '.hbe-scroll-panel .hres-table-wrap',
    '.pl-list-panel--scroll .pl-table-wrap',
    '.emp-list-panel--scroll .emp-table-wrap',
    '.sm-list-panel--scroll .sm-table-wrap',
  ].join(',');

  var EDGE_MIN = 96;
  var EDGE_MAX = 220;
  var EDGE_RATIO = 0.3;
  var MAX_SPEED = 22;
  var CUE_CLASSES = 'is-edge-scroll-left is-edge-scroll-right is-edge-scroll-top is-edge-scroll-bottom';

  function bindEdgeScroll(wrap) {
    if (!wrap || wrap.__hbeEdgeScrollBound) return;
    wrap.__hbeEdgeScrollBound = true;

    var dirX = 0;
    var dirY = 0;
    var speedX = 0;
    var speedY = 0;
    var raf = 0;

    function maxScrollLeft() {
      return Math.max(0, wrap.scrollWidth - wrap.clientWidth);
    }

    function maxScrollTop() {
      return Math.max(0, wrap.scrollHeight - wrap.clientHeight);
    }

    function edgeSize(size) {
      return Math.max(EDGE_MIN, Math.min(EDGE_MAX, Math.round(size * EDGE_RATIO)));
    }

    function syncCues() {
      wrap.classList.toggle('is-edge-scroll-left', dirX < 0);
      wrap.classList.toggle('is-edge-scroll-right', dirX > 0);
      wrap.classList.toggle('is-edge-scroll-top', dirY < 0);
      wrap.classList.toggle('is-edge-scroll-bottom', dirY > 0);
    }

    function tick() {
      raf = 0;
      if ((!dirX || !speedX) && (!dirY || !speedY)) return;
      var maxX = maxScrollLeft();
      var maxY = maxScrollTop();
      if (dirX && speedX) {
        wrap.scrollLeft = Math.max(0, Math.min(maxX, wrap.scrollLeft + dirX * speedX));
        if ((dirX < 0 && wrap.scrollLeft <= 0) || (dirX > 0 && wrap.scrollLeft >= maxX)) {
          dirX = 0;
          speedX = 0;
        }
      }
      if (dirY && speedY) {
        wrap.scrollTop = Math.max(0, Math.min(maxY, wrap.scrollTop + dirY * speedY));
        if ((dirY < 0 && wrap.scrollTop <= 0) || (dirY > 0 && wrap.scrollTop >= maxY)) {
          dirY = 0;
          speedY = 0;
        }
      }
      syncCues();
      if ((dirX && speedX) || (dirY && speedY)) raf = requestAnimationFrame(tick);
    }

    function stop() {
      dirX = 0;
      dirY = 0;
      speedX = 0;
      speedY = 0;
      wrap.classList.remove.apply(wrap.classList, CUE_CLASSES.split(' '));
      if (raf) {
        cancelAnimationFrame(raf);
        raf = 0;
      }
    }

    function onMove(e) {
      var maxX = maxScrollLeft();
      var maxY = maxScrollTop();
      if (maxX <= 1 && maxY <= 1) {
        stop();
        return;
      }
      var rect = wrap.getBoundingClientRect();
      if (
        e.clientX < rect.left ||
        e.clientX > rect.right ||
        e.clientY < rect.top ||
        e.clientY > rect.bottom
      ) {
        stop();
        return;
      }
      var x = e.clientX - rect.left;
      var y = e.clientY - rect.top;
      var width = rect.width || 1;
      var height = rect.height || 1;
      var edgeX = edgeSize(width);
      var edgeY = edgeSize(height);
      var nextDirX = 0;
      var nextSpeedX = 0;
      var nextDirY = 0;
      var nextSpeedY = 0;

      if (maxX > 1) {
        if (x >= width - edgeX) {
          nextDirX = 1;
          nextSpeedX = Math.max(2, Math.ceil(MAX_SPEED * ((x - (width - edgeX)) / edgeX)));
        } else if (x <= edgeX) {
          nextDirX = -1;
          nextSpeedX = Math.max(2, Math.ceil(MAX_SPEED * ((edgeX - x) / edgeX)));
        }
      }
      if (maxY > 1) {
        if (y >= height - edgeY) {
          nextDirY = 1;
          nextSpeedY = Math.max(2, Math.ceil(MAX_SPEED * ((y - (height - edgeY)) / edgeY)));
        } else if (y <= edgeY) {
          nextDirY = -1;
          nextSpeedY = Math.max(2, Math.ceil(MAX_SPEED * ((edgeY - y) / edgeY)));
        }
      }

      dirX = nextDirX;
      speedX = nextSpeedX;
      dirY = nextDirY;
      speedY = nextSpeedY;
      syncCues();
      if ((dirX || dirY) && !raf) raf = requestAnimationFrame(tick);
      if (!dirX && !dirY && raf) {
        cancelAnimationFrame(raf);
        raf = 0;
      }
    }

    wrap.addEventListener('mousemove', onMove, true);
    wrap.addEventListener('mouseleave', stop);
    wrap.addEventListener('blur', stop);
  }

  function initHbeTableScroll() {
    document.querySelectorAll(SELECTOR).forEach(bindEdgeScroll);
  }

  function wrapReinit() {
    var orig = global.deWorkspaceReinit;
    if (typeof orig !== 'function' || orig.__hbeTableScrollWrapped) return;
    var wrapped = function () {
      var result = orig.apply(this, arguments);
      initHbeTableScroll();
      return result;
    };
    wrapped.__hbeTableScrollWrapped = true;
    global.deWorkspaceReinit = wrapped;
  }

  global.initHbeTableScroll = initHbeTableScroll;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initHbeTableScroll);
  } else {
    initHbeTableScroll();
  }
  wrapReinit();
})(window);
