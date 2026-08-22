/**
 * Edge auto-scroll for dense ledger/list tables.
 * Cursor toward the right/bottom (or left/top) pans clipped columns and rows.
 * Wheel / trackpad over the table scrolls the table first (not the outer page).
 * Arrow keys also pan when the wrap is focused or last hovered (invoice-ledger style).
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

  var PANEL_SELECTOR = [
    '.hbe-scroll-panel',
    '.pl-list-panel--scroll',
    '.emp-list-panel--scroll',
    '.sm-list-panel--scroll',
  ].join(',');

  var EDGE_MIN = 72;
  var EDGE_MAX = 220;
  var EDGE_RATIO = 0.28;
  var MAX_SPEED = 28;
  var KEY_STEP_X = 80;
  var KEY_STEP_Y = 48;
  var CUE_CLASSES = 'is-edge-scroll-left is-edge-scroll-right is-edge-scroll-top is-edge-scroll-bottom';
  var activeKeyWrap = null;
  var keyNavBound = false;
  var wheelNavBound = false;
  var edgeBindings = [];
  var globalEdgePointerBound = false;

  function isEditableTarget(target) {
    if (!target || !target.closest) return false;
    return !!target.closest(
      'input, textarea, select, option, button, a, [contenteditable="true"], [role="listbox"], [role="combobox"], [role="textbox"]'
    );
  }

  function canScroll(wrap) {
    if (!wrap) return false;
    return (
      wrap.scrollWidth - wrap.clientWidth > 1 ||
      wrap.scrollHeight - wrap.clientHeight > 1
    );
  }

  function wrapFromTarget(target) {
    if (!target || !target.closest) return null;
    var wrap = target.closest(SELECTOR);
    if (wrap) return wrap;
    var panel = target.closest(PANEL_SELECTOR);
    if (!panel) return null;
    return (
      panel.querySelector('.pl-table-wrap, .emp-table-wrap, .sm-table-wrap, .hres-table-wrap') ||
      null
    );
  }

  function scrollWrapByKey(wrap, key, shiftKey) {
    if (!wrap || !canScroll(wrap)) return false;
    var maxX = Math.max(0, wrap.scrollWidth - wrap.clientWidth);
    var maxY = Math.max(0, wrap.scrollHeight - wrap.clientHeight);
    var dx = 0;
    var dy = 0;
    var stepX = shiftKey ? KEY_STEP_X * 2 : KEY_STEP_X;
    var stepY = shiftKey ? KEY_STEP_Y * 2 : KEY_STEP_Y;
    if (key === 'ArrowLeft') dx = -stepX;
    else if (key === 'ArrowRight') dx = stepX;
    else if (key === 'ArrowUp') dy = -stepY;
    else if (key === 'ArrowDown') dy = stepY;
    else return false;
    if ((dx && maxX <= 1) || (dy && maxY <= 1)) return false;
    var nextLeft = Math.max(0, Math.min(maxX, wrap.scrollLeft + dx));
    var nextTop = Math.max(0, Math.min(maxY, wrap.scrollTop + dy));
    if (nextLeft === wrap.scrollLeft && nextTop === wrap.scrollTop) return false;
    wrap.scrollLeft = nextLeft;
    wrap.scrollTop = nextTop;
    return true;
  }

  function bindKeyboardScroll(wrap) {
    if (!wrap || wrap.__hbeKeyScrollBound) return;
    wrap.__hbeKeyScrollBound = true;
    if (!wrap.hasAttribute('tabindex')) wrap.setAttribute('tabindex', '0');

    wrap.addEventListener('mouseenter', function () {
      activeKeyWrap = wrap;
    });
    wrap.addEventListener('focusin', function () {
      activeKeyWrap = wrap;
    });
    wrap.addEventListener('mousedown', function (e) {
      if (isEditableTarget(e.target)) return;
      activeKeyWrap = wrap;
      if (document.activeElement !== wrap) {
        try {
          wrap.focus({ preventScroll: true });
        } catch (err) {
          wrap.focus();
        }
      }
    });
    wrap.addEventListener('keydown', function (e) {
      if (isEditableTarget(e.target) && e.target !== wrap) return;
      if (scrollWrapByKey(wrap, e.key, e.shiftKey)) {
        e.preventDefault();
        e.stopPropagation();
      }
    });
  }

  function bindGlobalKeyNav() {
    if (keyNavBound) return;
    keyNavBound = true;
    document.addEventListener(
      'keydown',
      function (e) {
        if (
          e.key !== 'ArrowLeft' &&
          e.key !== 'ArrowRight' &&
          e.key !== 'ArrowUp' &&
          e.key !== 'ArrowDown'
        ) {
          return;
        }
        if (isEditableTarget(e.target)) return;
        var wrap = activeKeyWrap;
        if (!wrap || !wrap.isConnected || !document.contains(wrap)) {
          wrap = null;
          activeKeyWrap = null;
        }
        if (!wrap) wrap = wrapFromTarget(e.target);
        if (!wrap) return;
        if (scrollWrapByKey(wrap, e.key, e.shiftKey)) {
          e.preventDefault();
        }
      },
      true
    );
  }

  function bindGlobalWheelNav() {
    if (wheelNavBound) return;
    wheelNavBound = true;
    document.addEventListener(
      'wheel',
      function (e) {
        if (e.ctrlKey) return;
        if (isEditableTarget(e.target)) return;
        var wrap = wrapFromTarget(e.target) || activeKeyWrap;
        if (!wrap || !wrap.isConnected || !document.contains(wrap)) return;
        if (!canScroll(wrap)) return;

        var maxX = Math.max(0, wrap.scrollWidth - wrap.clientWidth);
        var maxY = Math.max(0, wrap.scrollHeight - wrap.clientHeight);
        var dx = e.deltaX || 0;
        var dy = e.deltaY || 0;
        if (e.shiftKey && !dx && dy) {
          dx = dy;
          dy = 0;
        }
        if (!dx && !dy) return;

        var atLeft = wrap.scrollLeft <= 0;
        var atRight = wrap.scrollLeft >= maxX - 1;
        var atTop = wrap.scrollTop <= 0;
        var atBottom = wrap.scrollTop >= maxY - 1;
        var useX = maxX > 1 && dx && ((dx < 0 && !atLeft) || (dx > 0 && !atRight));
        var useY = maxY > 1 && dy && ((dy < 0 && !atTop) || (dy > 0 && !atBottom));
        if (!useX && !useY) return;

        if (useX) wrap.scrollLeft = Math.max(0, Math.min(maxX, wrap.scrollLeft + dx));
        if (useY) wrap.scrollTop = Math.max(0, Math.min(maxY, wrap.scrollTop + dy));
        activeKeyWrap = wrap;
        e.preventDefault();
        e.stopPropagation();
      },
      { capture: true, passive: false }
    );
  }

  function stopEdgeBinding(binding) {
    if (!binding) return;
    binding.dirX = 0;
    binding.dirY = 0;
    binding.speedX = 0;
    binding.speedY = 0;
    if (binding.wrap) {
      binding.wrap.classList.remove.apply(binding.wrap.classList, CUE_CLASSES.split(' '));
    }
    if (binding.raf) {
      cancelAnimationFrame(binding.raf);
      binding.raf = 0;
    }
  }

  function pruneEdgeBindings() {
    edgeBindings = edgeBindings.filter(function (binding) {
      if (!binding.wrap || !binding.wrap.isConnected) {
        stopEdgeBinding(binding);
        return false;
      }
      return true;
    });
  }

  function syncEdgeCues(binding) {
    var wrap = binding.wrap;
    wrap.classList.toggle('is-edge-scroll-left', binding.dirX < 0);
    wrap.classList.toggle('is-edge-scroll-right', binding.dirX > 0);
    wrap.classList.toggle('is-edge-scroll-top', binding.dirY < 0);
    wrap.classList.toggle('is-edge-scroll-bottom', binding.dirY > 0);
  }

  function edgeTick(binding) {
    binding.raf = 0;
    var wrap = binding.wrap;
    if ((!binding.dirX || !binding.speedX) && (!binding.dirY || !binding.speedY)) return;
    var maxX = Math.max(0, wrap.scrollWidth - wrap.clientWidth);
    var maxY = Math.max(0, wrap.scrollHeight - wrap.clientHeight);
    if (binding.dirX && binding.speedX) {
      wrap.scrollLeft = Math.max(
        0,
        Math.min(maxX, wrap.scrollLeft + binding.dirX * binding.speedX)
      );
      if (
        (binding.dirX < 0 && wrap.scrollLeft <= 0) ||
        (binding.dirX > 0 && wrap.scrollLeft >= maxX)
      ) {
        binding.dirX = 0;
        binding.speedX = 0;
      }
    }
    if (binding.dirY && binding.speedY) {
      wrap.scrollTop = Math.max(
        0,
        Math.min(maxY, wrap.scrollTop + binding.dirY * binding.speedY)
      );
      if (
        (binding.dirY < 0 && wrap.scrollTop <= 0) ||
        (binding.dirY > 0 && wrap.scrollTop >= maxY)
      ) {
        binding.dirY = 0;
        binding.speedY = 0;
      }
    }
    syncEdgeCues(binding);
    if ((binding.dirX && binding.speedX) || (binding.dirY && binding.speedY)) {
      binding.raf = requestAnimationFrame(function () {
        edgeTick(binding);
      });
    }
  }

  function handleEdgePointerMove(binding, e) {
    var wrap = binding.wrap;
    var panel = binding.panel || wrap;
    var maxX = Math.max(0, wrap.scrollWidth - wrap.clientWidth);
    var maxY = Math.max(0, wrap.scrollHeight - wrap.clientHeight);
    if (maxX <= 1 && maxY <= 1) {
      stopEdgeBinding(binding);
      return;
    }
    var wrapRect = wrap.getBoundingClientRect();
    var panelRect = panel.getBoundingClientRect();
    if (
      e.clientX < panelRect.left ||
      e.clientX > panelRect.right ||
      e.clientY < panelRect.top ||
      e.clientY > panelRect.bottom
    ) {
      stopEdgeBinding(binding);
      return;
    }
    activeKeyWrap = wrap;
    var x = e.clientX - wrapRect.left;
    var y = e.clientY - panelRect.top;
    var width = wrapRect.width || 1;
    var height = panelRect.height || 1;
    var edgeX = Math.max(EDGE_MIN, Math.min(EDGE_MAX, Math.round(width * EDGE_RATIO)));
    var edgeY = Math.max(EDGE_MIN, Math.min(EDGE_MAX, Math.round(height * EDGE_RATIO)));
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

    binding.dirX = nextDirX;
    binding.speedX = nextSpeedX;
    binding.dirY = nextDirY;
    binding.speedY = nextSpeedY;
    syncEdgeCues(binding);
    if ((binding.dirX || binding.dirY) && !binding.raf) {
      binding.raf = requestAnimationFrame(function () {
        edgeTick(binding);
      });
    }
    if (!binding.dirX && !binding.dirY && binding.raf) {
      cancelAnimationFrame(binding.raf);
      binding.raf = 0;
    }
  }

  function bindGlobalEdgePointer() {
    if (globalEdgePointerBound) return;
    globalEdgePointerBound = true;
    document.addEventListener(
      'pointermove',
      function (e) {
        if (e.pointerType === 'touch') return;
        pruneEdgeBindings();
        var hit = null;
        for (var i = edgeBindings.length - 1; i >= 0; i--) {
          var binding = edgeBindings[i];
          var panel = binding.panel || binding.wrap;
          var rect = panel.getBoundingClientRect();
          if (
            e.clientX >= rect.left &&
            e.clientX <= rect.right &&
            e.clientY >= rect.top &&
            e.clientY <= rect.bottom
          ) {
            hit = binding;
            break;
          }
        }
        edgeBindings.forEach(function (binding) {
          if (binding !== hit) stopEdgeBinding(binding);
        });
        if (hit) handleEdgePointerMove(hit, e);
      },
      true
    );
  }

  function bindEdgeScroll(wrap) {
    if (!wrap) return;
    pruneEdgeBindings();
    for (var i = 0; i < edgeBindings.length; i++) {
      if (edgeBindings[i].wrap === wrap) return;
    }
    bindKeyboardScroll(wrap);
    var binding = {
      wrap: wrap,
      panel: wrap.closest(PANEL_SELECTOR),
      dirX: 0,
      dirY: 0,
      speedX: 0,
      speedY: 0,
      raf: 0,
    };
    edgeBindings.push(binding);
    bindGlobalEdgePointer();
    wrap.addEventListener('mouseenter', function () {
      activeKeyWrap = wrap;
    });
    wrap.addEventListener('blur', function () {
      stopEdgeBinding(binding);
    });
  }

  function initHbeTableScroll() {
    bindGlobalKeyNav();
    bindGlobalWheelNav();
    pruneEdgeBindings();
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
