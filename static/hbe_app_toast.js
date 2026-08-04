/**
 * Global WhatsApp / home notification toast (macOS-style, top-right, 5s).
 * Lives outside soft-nav main swaps so it works on every workspace page.
 */
(function () {
  'use strict';

  if (window.__hbeAppToastInit) return;
  window.__hbeAppToastInit = true;

  var POLL_MS = 8000;
  var SHOW_MS = 5000;
  var STORAGE_FP = 'hbe-app-toast-fp';
  var apiUrl = '';
  var timer = 0;
  var hideTimer = 0;
  var host = null;
  var audioCtx = null;
  var audioUnlockBound = false;

  function getAudioContext() {
    var Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return null;
    if (!audioCtx) audioCtx = new Ctx();
    return audioCtx;
  }

  function unlockAudio() {
    var ctx = getAudioContext();
    if (!ctx) return;
    if (ctx.state === 'suspended') {
      ctx.resume().catch(function () {});
    }
  }

  function bindAudioUnlock() {
    if (audioUnlockBound) return;
    audioUnlockBound = true;
    var unlock = function () {
      unlockAudio();
      document.removeEventListener('pointerdown', unlock, true);
      document.removeEventListener('keydown', unlock, true);
      document.removeEventListener('touchstart', unlock, true);
    };
    document.addEventListener('pointerdown', unlock, true);
    document.addEventListener('keydown', unlock, true);
    document.addEventListener('touchstart', unlock, true);
  }

  /** Short rising trill — WhatsApp-like, synthesized (no asset / copyright). */
  function playNotificationSound() {
    try {
      var ctx = getAudioContext();
      if (!ctx) return;
      var schedule = function () {
        if (ctx.state !== 'running') return;
        var now = ctx.currentTime;
        // Classic WA-style ascending ding: D5 → F#5 → A5
        var notes = [
          { freq: 587.33, start: 0, dur: 0.09, peak: 0.16 },
          { freq: 739.99, start: 0.08, dur: 0.09, peak: 0.15 },
          { freq: 880.0, start: 0.16, dur: 0.14, peak: 0.13 },
        ];
        notes.forEach(function (note) {
          var osc = ctx.createOscillator();
          var gain = ctx.createGain();
          osc.type = 'triangle';
          osc.frequency.setValueAtTime(note.freq, now + note.start);
          var t0 = now + note.start;
          gain.gain.setValueAtTime(0.0001, t0);
          gain.gain.exponentialRampToValueAtTime(note.peak, t0 + 0.012);
          gain.gain.exponentialRampToValueAtTime(0.0001, t0 + note.dur);
          osc.connect(gain);
          gain.connect(ctx.destination);
          osc.start(t0);
          osc.stop(t0 + note.dur + 0.02);
        });
      };
      if (ctx.state === 'suspended') {
        ctx.resume().then(schedule).catch(function () {});
        return;
      }
      schedule();
    } catch (_err) {
      /* Autoplay blocked or Audio unavailable — ignore. */
    }
  }

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function fingerprint(items) {
    return (items || [])
      .map(function (item) {
        return String(item.id || '') + '|' + String(item.title || '') + '|' + String(item.body || '');
      })
      .join('||');
  }

  function ensureHost() {
    host = document.getElementById('hbe-app-toast-host');
    if (host) return host;
    var root =
      document.getElementById('de-fs-app') ||
      document.getElementById('ep-workspace') ||
      document.body;
    host = document.createElement('div');
    host.id = 'hbe-app-toast-host';
    host.setAttribute('aria-live', 'polite');
    host.setAttribute('aria-relevant', 'additions');
    root.appendChild(host);
    return host;
  }

  function dismissToast(node) {
    if (!node || !node.parentNode) return;
    node.classList.remove('is-in');
    node.classList.add('is-out');
    window.setTimeout(function () {
      if (node.parentNode) node.parentNode.removeChild(node);
    }, 340);
  }

  function showToast(item) {
    var wrap = ensureHost();
    var existing = wrap.querySelector('.hbe-app-toast');
    if (existing) dismissToast(existing);

    var card = document.createElement('div');
    card.className = 'hbe-app-toast';
    card.setAttribute('role', 'status');
    card.innerHTML =
      '<div class="hbe-app-toast-icon" aria-hidden="true">' +
      '<svg viewBox="0 0 24 24"><path d="M10.268 21a2 2 0 0 0 3.464 0"/><path d="M3.262 15.326A1 1 0 0 0 4 17h16a1 1 0 0 0 .74-1.673C19.41 13.956 18 12.499 18 8A6 6 0 0 0 6 8c0 4.499-1.411 5.956-2.738 7.326"/></svg>' +
      '</div>' +
      '<div class="hbe-app-toast-copy">' +
      '<p class="hbe-app-toast-app">Hotel Bell Elite</p>' +
      '<p class="hbe-app-toast-title">' +
      esc(item.title || 'New notification') +
      '</p>' +
      (item.body
        ? '<p class="hbe-app-toast-body">' + esc(item.body) + '</p>'
        : '') +
      '</div>' +
      '<button type="button" class="hbe-app-toast-close" aria-label="Dismiss">' +
      '<svg viewBox="0 0 24 24"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>' +
      '</button>';

    var href = item.href || '';
    card.addEventListener('click', function (e) {
      if (e.target.closest('.hbe-app-toast-close')) {
        e.preventDefault();
        e.stopPropagation();
        dismissToast(card);
        return;
      }
      if (href) {
        var a = document.createElement('a');
        a.href = href;
        a.setAttribute('data-hbe-toast-nav', '1');
        document.body.appendChild(a);
        a.click();
        if (a.parentNode) a.parentNode.removeChild(a);
        dismissToast(card);
      }
    });

    wrap.appendChild(card);
    playNotificationSound();
    requestAnimationFrame(function () {
      card.classList.add('is-in');
    });

    if (hideTimer) clearTimeout(hideTimer);
    hideTimer = window.setTimeout(function () {
      dismissToast(card);
    }, SHOW_MS);

    // #region agent log
    fetch('http://127.0.0.1:7764/ingest/3c15e9d7-8289-4a1b-877f-c72ceeda0753',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'42fa9a'},body:JSON.stringify({sessionId:'42fa9a',runId:'toast-pre',hypothesisId:'T1',location:'hbe_app_toast.js:showToast',message:'toast shown',data:{id:item.id||'',title:item.title||'',host:location.host,href:href},timestamp:Date.now()})}).catch(function(){});
    // #endregion
  }

  function maybeAnnounce(items) {
    var list = items || [];
    var hubItems = list.filter(function (item) {
      return String(item.id || '').indexOf('communication-hub') === 0;
    });
    var prefer = hubItems.length ? hubItems : list;
    if (!prefer.length) {
      try {
        sessionStorage.setItem(STORAGE_FP, '');
      } catch (e) {}
      return;
    }
    var fp = fingerprint(prefer);
    var prev = '';
    try {
      prev = sessionStorage.getItem(STORAGE_FP) || '';
    } catch (e2) {}
    if (fp === prev) return;
    try {
      sessionStorage.setItem(STORAGE_FP, fp);
    } catch (e3) {}
    showToast(prefer[0]);
  }

  function poll() {
    if (!apiUrl) return;
    if (document.hidden) return;
    fetch(apiUrl, {
      credentials: 'same-origin',
      headers: { Accept: 'application/json' },
    })
      .then(function (res) {
        return res.json().then(function (data) {
          return { ok: res.ok, data: data || {} };
        });
      })
      .then(function (res) {
        // #region agent log
        fetch('http://127.0.0.1:7764/ingest/3c15e9d7-8289-4a1b-877f-c72ceeda0753',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'42fa9a'},body:JSON.stringify({sessionId:'42fa9a',runId:'toast-pre',hypothesisId:'T2',location:'hbe_app_toast.js:poll',message:'toast poll',data:{httpOk:!!res.ok,ok:!!(res.data&&res.data.ok),count:((res.data&&res.data.notifications)||[]).length,host:location.host},timestamp:Date.now()})}).catch(function(){});
        // #endregion
        if (!res.data || !res.data.ok) return;
        maybeAnnounce(res.data.notifications || []);
      })
      .catch(function () {});
  }

  function start() {
    apiUrl =
      (window.__HBE_NOTIF_URL || '').trim() ||
      '/home/api/notifications';
    ensureHost();
    bindAudioUnlock();
    if (timer) clearInterval(timer);
    timer = window.setInterval(poll, POLL_MS);
    poll();
    document.addEventListener('visibilitychange', function () {
      if (!document.hidden) poll();
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
