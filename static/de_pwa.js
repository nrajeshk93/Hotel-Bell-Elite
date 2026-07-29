/**
 * Register the POS offline service worker once per browser session.
 * Forces activation of a new SW (cache version bumps) so floor data is not stale.
 */
(function () {
  'use strict';
  if (!('serviceWorker' in navigator)) return;
  if (window.__dePwaRegistered) return;
  window.__dePwaRegistered = true;

  function register() {
    navigator.serviceWorker
      .register('/sw.js', { scope: '/' })
      .then(function (reg) {
        if (reg && typeof reg.update === 'function') {
          try {
            reg.update();
          } catch (e) {}
        }
        if (reg && reg.waiting) {
          try {
            reg.waiting.postMessage({ type: 'SKIP_WAITING' });
          } catch (e) {}
        }
        if (reg) {
          reg.addEventListener('updatefound', function () {
            var installing = reg.installing;
            if (!installing) return;
            installing.addEventListener('statechange', function () {
              if (installing.state === 'installed' && navigator.serviceWorker.controller) {
                /* New SW ready — claim happens via skipWaiting in sw.js install. */
              }
            });
          });
        }
      })
      .catch(function () {
        /* Ignore — HTTPS / localhost required; silent in unsupported hosts. */
      });
  }

  if (document.readyState === 'complete') {
    register();
  } else {
    window.addEventListener('load', register);
  }
})();
