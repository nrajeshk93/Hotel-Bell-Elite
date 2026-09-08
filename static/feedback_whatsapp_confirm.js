/**
 * Soft-nav-safe WhatsApp feedback confirm (Hotel / Restaurant / Bar).
 * Uses static/whatsapp_feedback_icon.png for the brand mark.
 */
(function (global) {
  'use strict';

  var STYLE_ID = 'hbe-fb-wa-confirm-style-v6';
  var MODAL_ID = 'hbe-fb-wa-modal-v6';
  var OLD_STYLE_IDS = [
    'hbe-fb-wa-confirm-style',
    'hbe-fb-wa-confirm-style-v3',
    'hbe-fb-wa-confirm-style-v4',
    'hbe-fb-wa-confirm-style-v6'
  ];
  var OLD_MODAL_IDS = [
    'hbe-fb-wa-modal',
    'hbe-fb-wa-modal-v4',
    'hbe-fb-wa-modal-v6',
    'de-fb-wa-modal'
  ];
  var resolver = null;

  function iconUrl() {
    var scripts = document.getElementsByTagName('script');
    var i;
    for (i = scripts.length - 1; i >= 0; i--) {
      var src = scripts[i].src || '';
      if (src.indexOf('feedback_whatsapp_confirm.js') !== -1) {
        return src.replace(/feedback_whatsapp_confirm\.js(?:\?.*)?$/, 'whatsapp_feedback_icon.png');
      }
    }
    return '/static/whatsapp_feedback_icon.png';
  }

  function waImg(cls, alt) {
    return (
      '<img class="' +
      cls +
      '" src="' +
      iconUrl() +
      '" alt="' +
      (alt || '') +
      '" width="52" height="52" decoding="async">'
    );
  }

  var CSS_TEXT = [
    '.hbe-fb-wa-backdrop{position:fixed;inset:0;z-index:10065;display:none;align-items:center;justify-content:center;padding:24px;background:rgba(15,23,42,.48);-webkit-backdrop-filter:blur(6px);backdrop-filter:blur(6px)}',
    '.hbe-fb-wa-backdrop.open{display:flex}',
    '.hbe-fb-wa-box{position:relative;width:min(520px,calc(100vw - 48px));background:#ffffff;border:1px solid #E8EEF5;border-radius:18px;padding:26px 24px 20px;box-shadow:0 28px 64px rgba(15,23,42,.18),0 2px 8px rgba(15,23,42,.06)}',
    '.hbe-fb-wa-close{position:absolute;top:12px;right:12px;width:36px;height:36px;border:0;border-radius:10px;background:transparent;color:#64748B;cursor:pointer;display:inline-flex;align-items:center;justify-content:center;padding:0}',
    '.hbe-fb-wa-close:hover{background:#F1F5F9;color:#0F172A}',
    '.hbe-fb-wa-close svg{width:18px;height:18px;display:block}',
    '.hbe-fb-wa-row{display:flex;align-items:center;gap:16px;padding-right:32px}',
    '.hbe-fb-wa-icon{flex:0 0 auto;width:52px;height:52px;border-radius:14px;overflow:hidden;display:inline-flex;align-items:center;justify-content:center;background:transparent;box-shadow:0 8px 18px rgba(37,211,102,.22)}',
    '.hbe-fb-wa-icon-img{width:52px;height:52px;display:block;object-fit:cover;border-radius:14px}',
    '.hbe-fb-wa-copy{min-width:0;flex:1}',
    '.hbe-fb-wa-title{margin:0;font:700 20px/1.25 Inter,Segoe UI,system-ui,-apple-system,sans-serif;letter-spacing:-0.02em;color:#0B1B34}',
    '.hbe-fb-wa-actions{display:flex;justify-content:flex-end;align-items:center;gap:12px;margin-top:22px}',
    '.hbe-fb-wa-cancel{min-height:42px;padding:0 18px;border-radius:12px;border:1px solid #D8E0EA;background:#fff;color:#334155;font:600 14px/1 Inter,Segoe UI,system-ui,-apple-system,sans-serif;cursor:pointer}',
    '.hbe-fb-wa-cancel:hover{background:#F8FAFC;border-color:#CBD5E1}',
    '.hbe-fb-wa-send{min-height:42px;padding:0 18px;border-radius:12px;border:0;background:#128C7E;color:#fff;font:700 14px/1 Inter,Segoe UI,system-ui,-apple-system,sans-serif;cursor:pointer;display:inline-flex;align-items:center;gap:9px;box-shadow:0 8px 18px rgba(18,140,126,.22)}',
    '.hbe-fb-wa-send:hover{background:#0F766E}',
    '.hbe-fb-wa-send:focus-visible{outline:2px solid #0D9488;outline-offset:2px}',
    '.hbe-fb-wa-send-glyph{width:18px;height:18px;display:block;flex:0 0 auto}',
    '.hbe-fb-wa-send-glyph path{fill:#FFFFFF !important}',
    '@media (max-width:640px){.hbe-fb-wa-box{padding:22px 16px 16px;border-radius:16px}.hbe-fb-wa-title{font-size:18px}.hbe-fb-wa-row{gap:12px}}'
  ].join('');

  function purgeOld() {
    OLD_STYLE_IDS.forEach(function (id) {
      var el = document.getElementById(id);
      if (el && el.parentNode) el.parentNode.removeChild(el);
    });
    OLD_MODAL_IDS.forEach(function (id) {
      var el = document.getElementById(id);
      if (el && el.parentNode) el.parentNode.removeChild(el);
    });
  }

  function ensureStyle() {
    purgeOld();
    var style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = CSS_TEXT;
    (document.head || document.documentElement).appendChild(style);
  }

  function mountRoot() {
    var fs = document.getElementById('de-fullscreen-root');
    return fs || document.body;
  }

  function ensureModal() {
    ensureStyle();
    var backdrop = document.createElement('div');
    backdrop.id = MODAL_ID;
    backdrop.className = 'hbe-fb-wa-backdrop';
    backdrop.setAttribute('aria-hidden', 'true');
    backdrop.innerHTML =
      '<div class="hbe-fb-wa-box" role="dialog" aria-modal="true" aria-labelledby="hbe-fb-wa-title">' +
        '<button type="button" class="hbe-fb-wa-close" data-fb-wa="close" aria-label="Close">' +
          '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M18 6 6 18" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><path d="m6 6 12 12" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>' +
        '</button>' +
        '<div class="hbe-fb-wa-row">' +
          '<div class="hbe-fb-wa-icon" aria-hidden="true">' +
            waImg('hbe-fb-wa-icon-img', '') +
          '</div>' +
          '<div class="hbe-fb-wa-copy">' +
            '<div class="hbe-fb-wa-title" id="hbe-fb-wa-title">Send Feedback Link?</div>' +
          '</div>' +
        '</div>' +
        '<div class="hbe-fb-wa-actions">' +
          '<button type="button" class="hbe-fb-wa-cancel" data-fb-wa="cancel">Cancel</button>' +
          '<button type="button" class="hbe-fb-wa-send" data-fb-wa="send">' +
            '<svg class="hbe-fb-wa-send-glyph" viewBox="0 0 24 24" aria-hidden="true"><path fill="#FFFFFF" d="M12.04 2c-5.46 0-9.91 4.45-9.91 9.91 0 1.75.46 3.45 1.32 4.95L2.05 22l5.25-1.38c1.45.79 3.08 1.21 4.74 1.21 5.46 0 9.91-4.45 9.91-9.91 0-2.65-1.03-5.14-2.9-7.01A9.82 9.82 0 0 0 12.04 2zm.01 1.67c2.2 0 4.26.86 5.82 2.42a8.23 8.23 0 0 1 2.41 5.83c0 4.54-3.7 8.23-8.24 8.23-1.48 0-2.93-.39-4.19-1.15l-.3-.17-3.12.82.83-3.04-.2-.32a8.2 8.2 0 0 1-1.26-4.38c0-4.54 3.7-8.24 8.25-8.24zM8.68 7.57c-.16 0-.34.01-.52.09-.18.07-.49.24-.71.58-.22.34-.84.82-.84 2 0 1.18.86 2.32.98 2.48.12.16 1.67 2.66 4.13 3.63 2.05.8 2.47.64 2.92.6.45-.04 1.45-.59 1.65-1.16.2-.57.2-1.06.14-1.16-.06-.1-.22-.16-.46-.28-.24-.12-1.45-.72-1.67-.8-.22-.08-.39-.12-.55.12-.16.24-.63.8-.77.96-.14.16-.28.18-.52.06-.24-.12-1.01-.37-1.93-1.19-.71-.64-1.19-1.42-1.33-1.66-.14-.24-.01-.37.1-.49.11-.11.24-.28.36-.42.12-.14.16-.24.24-.4.08-.16.04-.3-.02-.42-.06-.12-.55-1.35-.76-1.85-.2-.48-.4-.4-.55-.41-.14-.01-.31-.01-.48-.01z"/></svg>' +
            '<span>Send on WhatsApp</span>' +
          '</button>' +
        '</div>' +
      '</div>';
    mountRoot().appendChild(backdrop);

    function finish(result) {
      backdrop.classList.remove('open');
      backdrop.setAttribute('aria-hidden', 'true');
      var resolve = resolver;
      resolver = null;
      if (resolve) resolve(!!result);
    }

    backdrop.addEventListener('click', function (event) {
      var t = event.target;
      if (t === backdrop) {
        finish(false);
        return;
      }
      var btn = t && t.closest ? t.closest('[data-fb-wa]') : null;
      if (!btn) return;
      if (btn.getAttribute('data-fb-wa') === 'send') finish(true);
      else finish(false);
    });
    document.addEventListener('keydown', function (event) {
      if (!backdrop.classList.contains('open')) return;
      if (event.key === 'Escape') {
        event.preventDefault();
        finish(false);
      } else if (event.key === 'Enter') {
        event.preventDefault();
        finish(true);
      }
    });
    return backdrop;
  }

  function confirmFeedbackWhatsApp(opts) {
    opts = opts || {};
    var title = opts.title != null ? String(opts.title) : 'Send Feedback Link?';
    return new Promise(function (resolve) {
      if (resolver) {
        resolver(false);
        resolver = null;
      }
      var backdrop = ensureModal();
      var titleEl = backdrop.querySelector('#hbe-fb-wa-title');
      if (titleEl) titleEl.textContent = title;
      resolver = resolve;
      var root = mountRoot();
      if (backdrop.parentNode !== root) root.appendChild(backdrop);
      backdrop.classList.add('open');
      backdrop.setAttribute('aria-hidden', 'false');
      var sendBtn = backdrop.querySelector('[data-fb-wa="send"]');
      if (sendBtn) sendBtn.focus();
    });
  }

  global.deConfirmFeedbackWhatsApp = confirmFeedbackWhatsApp;
  if (global.deFullscreen && typeof global.deFullscreen === 'object') {
    global.deFullscreen.confirmFeedbackWhatsApp = confirmFeedbackWhatsApp;
  }
})(typeof window !== 'undefined' ? window : this);
