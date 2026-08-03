/**
 * Communication Hub — conversation list + WhatsApp thread.
 */
(function () {
  'use strict';

  var POLL_MS = 8000;
  var page = null;
  var state = {
    conversations: [],
    activeId: null,
    messages: [],
    pollTimer: 0,
    sending: false,
  };

  function $(sel, root) {
    return (root || document).querySelector(sel);
  }

  function $all(sel, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(sel));
  }

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function initials(label) {
    var parts = String(label || '?').trim().split(/\s+/).filter(Boolean);
    if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
    return (parts[0] || '?').slice(0, 2).toUpperCase();
  }

  function formatTime(iso) {
    var raw = String(iso || '');
    if (raw.length >= 16) return raw.slice(11, 16);
    return raw;
  }

  function formatDay(iso) {
    var raw = String(iso || '');
    if (raw.length >= 10) return raw.slice(0, 10);
    return '';
  }

  function messagesUrl(id) {
    var tpl = page.getAttribute('data-messages-url-template') || '';
    return tpl.replace(/\/0(\/messages)?$/, '/' + id + '$1').replace(/\/0$/, '/' + id);
  }

  function loadBootstrap() {
    var el = document.getElementById('ch-bootstrap');
    if (!el) return [];
    try {
      return JSON.parse(el.textContent || '[]') || [];
    } catch (e) {
      return [];
    }
  }

  function openModal() {
    var modal = $('#ch-new-modal');
    if (!modal) return;
    modal.classList.add('open');
    modal.setAttribute('aria-hidden', 'false');
    var err = $('#ch-new-error');
    if (err) {
      err.hidden = true;
      err.textContent = '';
    }
    var phone = $('#ch-new-phone');
    if (phone) {
      phone.value = '';
      setTimeout(function () {
        phone.focus();
      }, 30);
    }
    var name = $('#ch-new-name');
    if (name) name.value = '';
  }

  function closeModal() {
    var modal = $('#ch-new-modal');
    if (!modal) return;
    modal.classList.remove('open');
    modal.setAttribute('aria-hidden', 'true');
  }

  function setSendError(msg) {
    var el = $('#ch-send-error');
    if (!el) return;
    if (msg) {
      el.hidden = false;
      el.textContent = msg;
    } else {
      el.hidden = true;
      el.textContent = '';
    }
  }

  function renderList(filter) {
    var list = $('#ch-conv-list');
    if (!list) return;
    var q = String(filter || '').trim().toLowerCase();
    var items = state.conversations.filter(function (c) {
      if (!q) return true;
      var blob = [c.label, c.phone, c.display_name, c.last_preview].join(' ').toLowerCase();
      return blob.indexOf(q) !== -1;
    });
    var countEl = $('#ch-conv-count');
    if (countEl) countEl.textContent = String(state.conversations.length);

    if (!items.length) {
      list.innerHTML =
        '<div class="ch-empty-list" id="ch-empty-list">No conversations match. Start a new chat.</div>';
      return;
    }

    list.innerHTML = items
      .map(function (c) {
        var active = String(c.id) === String(state.activeId) ? ' is-active' : '';
        var unread =
          c.unread_count > 0
            ? '<span class="ch-unread">' + esc(c.unread_count) + '</span>'
            : '';
        return (
          '<button type="button" class="ch-conv-item' +
          active +
          '" role="listitem" data-id="' +
          esc(c.id) +
          '">' +
          '<span class="ch-avatar" aria-hidden="true">' +
          esc(initials(c.label)) +
          '</span>' +
          '<span class="ch-conv-main">' +
          '<span class="ch-conv-top">' +
          '<span class="ch-conv-name">' +
          esc(c.label) +
          '</span>' +
          '<span class="ch-conv-time">' +
          esc(formatTime(c.last_message_at)) +
          '</span>' +
          '</span>' +
          '<span class="ch-conv-bottom">' +
          '<span class="ch-conv-preview">' +
          esc(c.last_preview || 'No messages yet') +
          '</span>' +
          unread +
          '</span>' +
          '</span>' +
          '</button>'
        );
      })
      .join('');
  }

  function renderMessages() {
    var host = $('#ch-messages');
    if (!host) return;
    var html = [];
    var lastDay = '';
    state.messages.forEach(function (m) {
      var day = formatDay(m.created_at);
      if (day && day !== lastDay) {
        lastDay = day;
        html.push('<div class="ch-day-sep">' + esc(day) + '</div>');
      }
      var dir = m.direction === 'out' ? 'out' : 'in';
      var failed = m.status === 'failed' ? ' is-failed' : '';
      var file = '';
      if (m.message_type === 'document' || m.message_type === 'image') {
        file =
          '<div class="ch-file-chip">' +
          esc(m.media_filename || m.message_type) +
          (m.media_mime ? ' · ' + esc(m.media_mime) : '') +
          '</div>';
      }
      var err =
        m.status === 'failed' && m.error
          ? '<div class="ch-bubble-error">' + esc(m.error) + '</div>'
          : '';
      html.push(
        '<div class="ch-bubble-row is-' +
          dir +
          '">' +
          '<div class="ch-bubble' +
          failed +
          '">' +
          file +
          esc(m.body || '') +
          '<div class="ch-bubble-meta">' +
          esc(formatTime(m.created_at)) +
          (dir === 'out' ? (m.status === 'failed' ? ' · failed' : ' · ✓✓') : '') +
          '</div>' +
          err +
          '</div>' +
          '</div>'
      );
    });
    host.innerHTML = html.join('') || '<div class="ch-day-sep">No messages yet</div>';
    host.scrollTop = host.scrollHeight;
  }

  function showThread(conversation) {
    var empty = $('#ch-thread-empty');
    var active = $('#ch-thread-active');
    if (empty) empty.hidden = true;
    if (active) active.hidden = false;
    $('#ch-peer-name').textContent = conversation.label || conversation.phone || '—';
    $('#ch-peer-phone').textContent = conversation.phone || '—';
    $('#ch-peer-avatar').textContent = initials(conversation.label || conversation.phone);
    setSendError('');
  }

  function hideThread() {
    state.activeId = null;
    state.messages = [];
    var empty = $('#ch-thread-empty');
    var active = $('#ch-thread-active');
    if (empty) empty.hidden = false;
    if (active) active.hidden = true;
    renderList(($('#ch-list-search') || {}).value || ($('#ch-global-search') || {}).value || '');
  }

  function fetchJson(url, opts) {
    return fetch(url, Object.assign({ credentials: 'same-origin' }, opts || {})).then(
      function (res) {
        return res.json().then(function (data) {
          return { ok: res.ok, status: res.status, data: data || {} };
        });
      }
    );
  }

  function refreshConversations() {
    var url = page.getAttribute('data-conversations-url') || '';
    var q = (($('#ch-list-search') || {}).value || '').trim();
    if (q) url += (url.indexOf('?') >= 0 ? '&' : '?') + 'q=' + encodeURIComponent(q);
    return fetchJson(url).then(function (res) {
      if (res.data && res.data.ok && Array.isArray(res.data.conversations)) {
        state.conversations = res.data.conversations;
        renderList(q);
      }
    });
  }

  function openConversation(id) {
    id = Number(id);
    if (!id) return;
    state.activeId = id;
    var conv = state.conversations.find(function (c) {
      return Number(c.id) === id;
    });
    if (conv) showThread(conv);
    renderList(($('#ch-list-search') || {}).value || '');
    return fetchJson(messagesUrl(id)).then(function (res) {
      if (!res.data || !res.data.ok) {
        setSendError((res.data && res.data.error) || 'Unable to load messages.');
        return;
      }
      if (res.data.conversation) {
        var idx = state.conversations.findIndex(function (c) {
          return Number(c.id) === Number(res.data.conversation.id);
        });
        if (idx >= 0) state.conversations[idx] = res.data.conversation;
        else state.conversations.unshift(res.data.conversation);
        showThread(res.data.conversation);
      }
      state.messages = res.data.messages || [];
      renderMessages();
      renderList(($('#ch-list-search') || {}).value || '');
    });
  }

  function createConversation() {
    var phone = (($('#ch-new-phone') || {}).value || '').trim();
    var name = (($('#ch-new-name') || {}).value || '').trim();
    var err = $('#ch-new-error');
    if (!phone) {
      if (err) {
        err.hidden = false;
        err.textContent = 'Enter a phone number.';
      }
      return;
    }
    var url = page.getAttribute('data-create-url') || '';
    fetchJson(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ phone: phone, display_name: name }),
    }).then(function (res) {
      if (!res.data || !res.data.ok) {
        if (err) {
          err.hidden = false;
          err.textContent = (res.data && res.data.error) || 'Unable to open chat.';
        }
        return;
      }
      var conv = res.data.conversation;
      var idx = state.conversations.findIndex(function (c) {
        return Number(c.id) === Number(conv.id);
      });
      if (idx >= 0) state.conversations[idx] = conv;
      else state.conversations.unshift(conv);
      closeModal();
      openConversation(conv.id);
    });
  }

  function sendMessage(ev) {
    if (ev) ev.preventDefault();
    if (state.sending || !state.activeId) return;
    var input = $('#ch-composer-input');
    var text = (input && input.value ? input.value : '').trim();
    if (!text) return;
    state.sending = true;
    setSendError('');
    var btn = $('#ch-send-btn');
    if (btn) btn.disabled = true;
    fetchJson(messagesUrl(state.activeId), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ text: text }),
    })
      .then(function (res) {
        if (!res.data || !res.data.ok) {
          setSendError((res.data && res.data.error) || 'Send failed.');
          if (res.data && res.data.message) {
            state.messages.push(res.data.message);
            renderMessages();
          }
          if (res.data && res.data.conversation) {
            var idx = state.conversations.findIndex(function (c) {
              return Number(c.id) === Number(res.data.conversation.id);
            });
            if (idx >= 0) state.conversations[idx] = res.data.conversation;
            renderList(($('#ch-list-search') || {}).value || '');
          }
          return;
        }
        if (input) input.value = '';
        if (res.data.message) state.messages.push(res.data.message);
        if (res.data.conversation) {
          var i = state.conversations.findIndex(function (c) {
            return Number(c.id) === Number(res.data.conversation.id);
          });
          if (i >= 0) state.conversations[i] = res.data.conversation;
          else state.conversations.unshift(res.data.conversation);
        }
        renderMessages();
        renderList(($('#ch-list-search') || {}).value || '');
      })
      .catch(function () {
        setSendError('Network error while sending.');
      })
      .then(function () {
        state.sending = false;
        if (btn) btn.disabled = false;
        if (input) input.focus();
      });
  }

  function startPolling() {
    if (state.pollTimer) clearInterval(state.pollTimer);
    state.pollTimer = setInterval(function () {
      if (!document.getElementById('communication-hub-page')) return;
      refreshConversations().then(function () {
        if (state.activeId) openConversation(state.activeId);
      });
    }, POLL_MS);
  }

  function bind() {
    var list = $('#ch-conv-list');
    if (list) {
      list.addEventListener('click', function (e) {
        var item = e.target.closest('.ch-conv-item');
        if (!item) return;
        openConversation(item.getAttribute('data-id'));
      });
    }
    ['ch-list-search', 'ch-global-search'].forEach(function (id) {
      var el = document.getElementById(id);
      if (!el) return;
      el.addEventListener('input', function () {
        var val = el.value || '';
        if (id === 'ch-global-search' && $('#ch-list-search')) {
          $('#ch-list-search').value = val;
        }
        if (id === 'ch-list-search' && $('#ch-global-search')) {
          $('#ch-global-search').value = val;
        }
        renderList(val);
      });
    });
    document.addEventListener('keydown', function (e) {
      if ((e.metaKey || e.ctrlKey) && String(e.key || '').toLowerCase() === 'k') {
        var search = $('#ch-global-search') || $('#ch-list-search');
        if (search && document.getElementById('communication-hub-page')) {
          e.preventDefault();
          search.focus();
        }
      }
    });
    var composer = $('#ch-composer');
    if (composer) composer.addEventListener('submit', sendMessage);
    ['ch-new-chat-btn', 'ch-empty-new-btn'].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.addEventListener('click', openModal);
    });
    ['ch-new-close', 'ch-new-cancel'].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.addEventListener('click', closeModal);
    });
    var submit = $('#ch-new-submit');
    if (submit) submit.addEventListener('click', createConversation);
    var modal = $('#ch-new-modal');
    if (modal) {
      modal.addEventListener('click', function (e) {
        if (e.target === modal) closeModal();
      });
    }
  }

  function initCommunicationHubPage() {
    page = document.getElementById('communication-hub-page');
    if (!page || page.__chBound) return;
    page.__chBound = true;
    state.conversations = loadBootstrap();
    bind();
    renderList('');
    hideThread();
    startPolling();
  }

  window.initCommunicationHubPage = initCommunicationHubPage;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initCommunicationHubPage);
  } else {
    initCommunicationHubPage();
  }

  var orig = window.deWorkspaceReinit;
  if (typeof orig === 'function' && !orig.__chWrapped) {
    var wrapped = function () {
      var result = orig.apply(this, arguments);
      var p = document.getElementById('communication-hub-page');
      if (p) {
        p.__chBound = false;
        initCommunicationHubPage();
      }
      return result;
    };
    wrapped.__chWrapped = true;
    window.deWorkspaceReinit = wrapped;
  }
})();
