/**
 * Customer Master ù View / Print hotel guest ID saved against a customer mobile.
 */
(function () {
  'use strict';

  function qs(sel, root) {
    return (root || document).querySelector(sel);
  }

  function ensureModalOnBody(modal) {
    if (!modal) return;
    if (modal.parentNode !== document.body) {
      modal.__smIdPreviewHome = modal.parentNode;
    }
    // Always park on <body> as the last child so it paints above #md-master-modal.
    document.body.appendChild(modal);
  }

  function closePreview() {
    var modal = qs('#sm-id-preview-modal');
    var body = qs('#sm-id-preview-body');
    if (!modal) return;
    modal.hidden = true;
    modal.setAttribute('aria-hidden', 'true');
    if (body) body.innerHTML = '';
    // Keep on body while the Master embed is open; only restore if home still exists
    // outside a stacking modal (standalone Customer Master page).
    var home = modal.__smIdPreviewHome;
    if (
      home &&
      home.isConnected &&
      modal.parentNode === document.body &&
      !home.closest('#md-master-modal, #st-product-master-modal')
    ) {
      try {
        home.appendChild(modal);
      } catch (e) {}
    }
  }

  function openPreview(url, name, mime) {
    var modal = qs('#sm-id-preview-modal');
    var body = qs('#sm-id-preview-body');
    var sub = qs('#sm-id-preview-sub');
    if (!url) return;
    if (!modal || !body) {
      try {
        window.open(url, '_blank', 'noopener,noreferrer');
      } catch (e) {}
      return;
    }
    ensureModalOnBody(modal);
    if (sub) {
      var label = String(name || '').trim();
      sub.textContent = label && label.toLowerCase().indexOf('.pdf') === -1 ? label : '';
    }
    body.innerHTML = '';
    var kind = String(mime || '').toLowerCase();
    if (kind.indexOf('image/') === 0) {
      var img = document.createElement('img');
      img.src = url;
      img.alt = name || 'Guest ID';
      img.className = 'sm-id-preview-img';
      body.appendChild(img);
    } else {
      var frame = document.createElement('iframe');
      frame.src = url;
      frame.title = name || 'Guest ID';
      frame.className = 'sm-id-preview-frame';
      body.appendChild(frame);
    }
    modal.hidden = false;
    modal.setAttribute('aria-hidden', 'false');
  }

  function printPreview() {
    var body = qs('#sm-id-preview-body');
    if (!body) return;
    var frame = qs('iframe.sm-id-preview-frame', body);
    if (frame && frame.contentWindow) {
      try {
        frame.contentWindow.focus();
        frame.contentWindow.print();
        return;
      } catch (e) {}
    }
    var img = qs('img.sm-id-preview-img', body);
    if (img && img.src) {
      var win = window.open('', '_blank', 'noopener,noreferrer');
      if (!win) return;
      win.document.write(
        '<!DOCTYPE html><html><head><title>Guest ID</title>' +
          '<style>html,body{margin:0;padding:0}img{max-width:100%;height:auto;display:block;margin:0 auto}</style>' +
          '</head><body><img src="' +
          String(img.src).replace(/"/g, '&quot;') +
          '" alt="Guest ID" onload="window.focus();window.print();"></body></html>'
      );
      win.document.close();
    }
  }

  function onClick(ev) {
    var btn = ev.target && ev.target.closest ? ev.target.closest('.sm-view-id-btn') : null;
    if (!btn) return;
    ev.preventDefault();
    ev.stopPropagation();
    openPreview(
      btn.getAttribute('data-id-url') || '',
      btn.getAttribute('data-id-name') || 'Guest ID',
      btn.getAttribute('data-id-mime') || ''
    );
  }

  function bind() {
    if (document.documentElement.getAttribute('data-sm-id-preview-bound') === '1') return;
    document.documentElement.setAttribute('data-sm-id-preview-bound', '1');
    document.addEventListener('click', onClick);
    document.addEventListener('click', function (ev) {
      if (ev.target && ev.target.closest && ev.target.closest('[data-sm-id-preview-close]')) {
        ev.preventDefault();
        closePreview();
      }
      if (ev.target && ev.target.id === 'sm-id-preview-print') {
        ev.preventDefault();
        printPreview();
      }
      var modal = qs('#sm-id-preview-modal');
      if (modal && !modal.hidden && ev.target === modal) {
        closePreview();
      }
    });
    document.addEventListener('keydown', function (ev) {
      if (ev.key !== 'Escape') return;
      var modal = qs('#sm-id-preview-modal');
      if (modal && !modal.hidden) closePreview();
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bind);
  } else {
    bind();
  }
})();
