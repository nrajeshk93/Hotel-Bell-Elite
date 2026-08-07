/**
 * Communication Hub — conversation list + WhatsApp thread.
 */
(function () {
  'use strict';

  var POLL_MS = 8000;
  var MESSAGE_POLL_MS = 3000;
  var page = null;
  var state = {
    conversations: [],
    activeId: null,
    messages: [],
    pollTimer: 0,
    messagePollTimer: 0,
    sending: false,
    listError: '',
    messagesFingerprint: '',
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
    if (el) {
      try {
        /* Prefer <template> content (survives soft-nav importNode); fall back to text. */
        var raw = '';
        if (el.content) {
          raw = el.content.textContent || '';
        }
        if (!String(raw).trim()) raw = el.textContent || '';
        var parsed = JSON.parse(String(raw || '').trim() || '[]');
        if (Array.isArray(parsed) && parsed.length) return parsed;
      } catch (e) {}
    }
    /* Soft-nav can blank bootstrap; fall back to SSR conversation buttons. */
    var fromDom = [];
    $all('#ch-conv-list .ch-conv-item').forEach(function (btn) {
      var id = Number(btn.getAttribute('data-id') || 0);
      if (!id) return;
      fromDom.push({
        id: id,
        phone: btn.getAttribute('data-phone') || '',
        display_name: '',
        label:
          btn.getAttribute('data-label') ||
          (btn.querySelector('.ch-conv-name') || {}).textContent ||
          '',
        last_preview:
          btn.getAttribute('data-preview') ||
          (btn.querySelector('.ch-conv-preview') || {}).textContent ||
          '',
        last_message_at: btn.getAttribute('data-at') || '',
        unread_count: Number(btn.getAttribute('data-unread') || 0) || 0,
      });
    });
    return fromDom;
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
      var emptyMsg = q
        ? 'No conversations match. Start a new chat.'
        : 'No conversations yet. Start a chat with a phone number.';
      if (state.listError && !q) {
        emptyMsg = state.listError;
      }
      list.innerHTML =
        '<div class="ch-empty-list" id="ch-empty-list">' + esc(emptyMsg) + '</div>';
      return;
    }

    list.innerHTML = items
      .map(function (c) {
        var active = String(c.id) === String(state.activeId) ? ' is-active' : '';
        var unread =
          c.unread_count > 0
            ? '<span class="ch-unread">' + esc(c.unread_count) + '</span>'
            : '';
        var label = c.label || c.phone || 'chat';
        return (
          '<div class="ch-conv-item' +
          active +
          '" role="listitem" data-id="' +
          esc(c.id) +
          '" data-phone="' +
          esc(c.phone || '') +
          '" data-label="' +
          esc(c.label || '') +
          '" data-preview="' +
          esc(c.last_preview || '') +
          '" data-unread="' +
          esc(c.unread_count || 0) +
          '" data-at="' +
          esc(c.last_message_at || '') +
          '">' +
          '<button type="button" class="ch-conv-open" aria-label="Open chat with ' +
          esc(label) +
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
          '</button>' +
          '<button type="button" class="ch-conv-delete" data-ch-delete aria-label="Delete chat with ' +
          esc(label) +
          '" title="Delete chat">' +
          '<svg viewBox="0 0 24 24" aria-hidden="true"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/></svg>' +
          '</button>' +
          '</div>'
        );
      })
      .join('');
  }

  function scrollThreadToComposer(reason) {
    var host = $('#ch-messages');
    var input = $('#ch-composer-input');
    var composer = $('#ch-composer');
    if (host) host.scrollTop = host.scrollHeight;
    if (composer && typeof composer.scrollIntoView === 'function') {
      try {
        composer.scrollIntoView({ block: 'nearest', inline: 'nearest' });
      } catch (e) {}
    }
    if (input && state.activeId) {
      try {
        input.focus({ preventScroll: true });
      } catch (e2) {
        try {
          input.focus();
        } catch (e3) {}
      }
    }
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
    requestAnimationFrame(function () {
      scrollThreadToComposer('after_renderMessages.raf');
    });
  }

  function showThread(conversation) {
    var empty = $('#ch-thread-empty');
    var active = $('#ch-thread-active');
    if (empty) {
      empty.hidden = true;
      empty.setAttribute('hidden', '');
      empty.setAttribute('aria-hidden', 'true');
    }
    if (active) {
      active.hidden = false;
      active.removeAttribute('hidden');
      active.setAttribute('aria-hidden', 'false');
    }
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
    if (empty) {
      empty.hidden = false;
      empty.removeAttribute('hidden');
      empty.setAttribute('aria-hidden', 'false');
    }
    if (active) {
      active.hidden = true;
      active.setAttribute('hidden', '');
      active.setAttribute('aria-hidden', 'true');
    }
    renderList(($('#ch-list-search') || {}).value || ($('#ch-global-search') || {}).value || '');
  }

  function deleteUrl(conversationId) {
    var tpl = (page && page.getAttribute('data-delete-url-template')) || '';
    if (!tpl) return '';
    return String(tpl).replace(/\/0\/?$/, '/' + conversationId);
  }

  function deleteConversation(conversationId, label) {
    var id = Number(conversationId || 0);
    if (!id) return Promise.resolve();
    var url = deleteUrl(id);
    if (!url) {
      window.alert('Delete is unavailable. Refresh the page and try again.');
      return Promise.resolve();
    }
    var name = String(label || 'this chat').trim() || 'this chat';
    var ok = window.confirm(
      'Delete chat with ' + name + '?\n\nMessages will be removed from Communication Hub.'
    );
    if (!ok) return Promise.resolve();
    return fetchJson(url, { method: 'DELETE' })
      .then(function (res) {
        if (!res.ok || !(res.data && res.data.ok)) {
          window.alert((res.data && res.data.error) || 'Unable to delete chat.');
          return;
        }
        state.conversations = state.conversations.filter(function (c) {
          return Number(c.id) !== id;
        });
        if (Number(state.activeId) === id) hideThread();
        else renderList(($('#ch-list-search') || {}).value || ($('#ch-global-search') || {}).value || '');
      })
      .catch(function () {
        window.alert('Network error while deleting chat.');
      });
  }

  function fetchJson(url, opts) {
    return fetch(url, Object.assign({ credentials: 'same-origin' }, opts || {})).then(
      function (res) {
        return res.text().then(function (raw) {
          var data = {};
          try {
            data = raw ? JSON.parse(raw) : {};
          } catch (e) {
            data = { ok: false, error: 'Invalid JSON response' };
          }
          return { ok: res.ok, status: res.status, data: data || {} };
        });
      }
    );
  }

  function refreshConversations() {
    var url = page.getAttribute('data-conversations-url') || '';
    var q = (($('#ch-list-search') || {}).value || '').trim();
    if (q) url += (url.indexOf('?') >= 0 ? '&' : '?') + 'q=' + encodeURIComponent(q);
    return fetchJson(url)
      .then(function (res) {
        if (res.data && res.data.ok && Array.isArray(res.data.conversations)) {
          state.listError = '';
          state.conversations = res.data.conversations;
          renderList(q);
          return;
        }
        if (!state.conversations.length) {
          state.listError =
            (res.data && res.data.error) ||
            (res.status === 401 || res.status === 302
              ? 'Session expired. Refresh the page and sign in again.'
              : 'Unable to load conversations. Refresh and try again.');
          renderList(q);
        }
      })
      .catch(function () {
        if (!state.conversations.length) {
          state.listError = 'Unable to load conversations. Check your connection and refresh.';
          renderList(q);
        }
      });
  }

  function messagesFingerprint(messages) {
    return (messages || [])
      .map(function (m) {
        return String(m.id || '') + ':' + String(m.status || '') + ':' + String(m.body || '').length;
      })
      .join('|');
  }

  function applyMessages(messages, conversation) {
    var next = messages || [];
    var fp = messagesFingerprint(next);
    state.messages = next;
    if (conversation) {
      var idx = state.conversations.findIndex(function (c) {
        return Number(c.id) === Number(conversation.id);
      });
      if (idx >= 0) state.conversations[idx] = conversation;
      else state.conversations.unshift(conversation);
      showThread(conversation);
    }
    if (fp !== state.messagesFingerprint) {
      state.messagesFingerprint = fp;
      renderMessages();
    }
    renderList(($('#ch-list-search') || {}).value || '');
  }

  function refreshActiveMessages() {
    if (!state.activeId || !page) {
      return Promise.resolve();
    }
    var id = state.activeId;
    var url = messagesUrl(id);
    return fetchJson(url).then(function (res) {
      var msgs = (res.data && res.data.messages) || [];
      var fp = messagesFingerprint(msgs);
      var changed = fp !== state.messagesFingerprint;
      if (!res.data || !res.data.ok) return;
      /* Ignore stale responses if the user switched chats mid-flight. */
      if (Number(state.activeId) !== Number(id)) return;
      applyMessages(msgs, res.data.conversation || null);
    }).catch(function (err) {
    });
  }

  function openConversation(id) {
    id = Number(id);
    if (!id) return;
    state.activeId = id;
    state.messagesFingerprint = '';
    var conv = state.conversations.find(function (c) {
      return Number(c.id) === id;
    });
    if (conv) showThread(conv);
    renderList(($('#ch-list-search') || {}).value || '');
    ensureMessagePolling();
    return fetchJson(messagesUrl(id)).then(function (res) {
      if (!res.data || !res.data.ok) {
        setSendError((res.data && res.data.error) || 'Unable to load messages.');
        return;
      }
      if (Number(state.activeId) !== Number(id)) return;
      applyMessages(res.data.messages || [], res.data.conversation || null);
      requestAnimationFrame(function () {
        scrollThreadToComposer('openConversation.afterApply.raf');
      });
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
    var input = $('#ch-composer-input');
    var text = (input && input.value ? input.value : '').trim();
    var reason = '';
    if (state.sending) reason = 'sending';
    else if (!state.activeId) reason = 'no_activeId';
    else if (!text) reason = 'empty_text';
    if (reason) return;
    state.sending = true;
    setSendError('');
    var btn = $('#ch-send-btn');
    if (btn) btn.disabled = true;
    var url = messagesUrl(state.activeId);
    fetchJson(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ text: text }),
    })
      .then(function (res) {
        applySendResult(res, input);
      })
      .catch(function (err) {
        setSendError('Network error while sending.');
      })
      .then(function () {
        state.sending = false;
        if (btn) btn.disabled = false;
        if (input) input.focus();
      });
  }

  function applySendResult(res, input) {
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
  }

  var EMOJI_SET = [
    '😀','😁','😂','🤣','😊','😍','😘','😎',
    '🤔','😅','😢','😭','😡','👍','👎','👏',
    '🙏','🔥','✅','❌','⭐','🎉','💯','👋',
    '🤝','💪','❤️','🧡','💚','💙','💜','🖤',
    '☕','🍽️','🏨','🧾','📞','📌','⏰','📦'
  ];

  function closeEmojiPanel() {
    var panel = $('#ch-emoji-panel');
    var btn = $('#ch-emoji-btn');
    if (panel) panel.hidden = true;
    if (btn) btn.setAttribute('aria-expanded', 'false');
  }

  function insertEmojiAtCursor(emoji) {
    var input = $('#ch-composer-input');
    if (!input || !emoji) return;
    var start = typeof input.selectionStart === 'number' ? input.selectionStart : input.value.length;
    var end = typeof input.selectionEnd === 'number' ? input.selectionEnd : start;
    var before = String(input.value || '').slice(0, start);
    var after = String(input.value || '').slice(end);
    var next = before + emoji + after;
    if (next.length > 4096) next = next.slice(0, 4096);
    input.value = next;
    var caret = Math.min(before.length + emoji.length, next.length);
    try {
      input.setSelectionRange(caret, caret);
    } catch (e) {}
    input.focus();
  }

  function ensureEmojiPanel() {
    var panel = $('#ch-emoji-panel');
    if (!panel || panel.getAttribute('data-ready') === '1') return panel;
    panel.innerHTML = EMOJI_SET.map(function (emoji) {
      return (
        '<button type="button" role="option" aria-label="Emoji">' +
        emoji +
        '</button>'
      );
    }).join('');
    panel.setAttribute('data-ready', '1');
    panel.addEventListener('click', function (e) {
      var btn = e.target.closest('button');
      if (!btn || !panel.contains(btn)) return;
      insertEmojiAtCursor(btn.textContent || '');
      closeEmojiPanel();
    });
    return panel;
  }

  function toggleEmojiPanel() {
    var panel = ensureEmojiPanel();
    var btn = $('#ch-emoji-btn');
    if (!panel || !btn) return;
    var open = !!panel.hidden;
    panel.hidden = !open;
    btn.setAttribute('aria-expanded', open ? 'true' : 'false');
  }

  function sendAttachment(file) {
    var reason = '';
    if (state.sending) reason = 'sending';
    else if (!state.activeId) reason = 'no_activeId';
    else if (!file) reason = 'no_file';
    if (reason) {
      if (reason === 'no_activeId') setSendError('Open a conversation before attaching a file.');
      return;
    }
    state.sending = true;
    setSendError('');
    var btn = $('#ch-send-btn');
    var attachBtn = $('#ch-attach-btn');
    var input = $('#ch-composer-input');
    if (btn) btn.disabled = true;
    if (attachBtn) attachBtn.disabled = true;
    var caption = (input && input.value ? input.value : '').trim();
    var fd = new FormData();
    fd.append('file', file, file.name || 'attachment');
    if (caption) fd.append('caption', caption);
    var url = messagesUrl(state.activeId);
    fetchJson(url, {
      method: 'POST',
      headers: { Accept: 'application/json' },
      body: fd,
    })
      .then(function (res) {
        applySendResult(res, input);
      })
      .catch(function (err) {
        setSendError('Network error while uploading attachment.');
      })
      .then(function () {
        state.sending = false;
        if (btn) btn.disabled = false;
        if (attachBtn) attachBtn.disabled = false;
        var fileInput = $('#ch-attach-input');
        if (fileInput) fileInput.value = '';
        if (input) input.focus();
      });
  }

  function ensureMessagePolling() {
    if (state.messagePollTimer) return;
    state.messagePollTimer = setInterval(function () {
      if (!document.getElementById('communication-hub-page')) return;
      if (!state.activeId) return;
      if (document.hidden) return;
      refreshActiveMessages();
    }, MESSAGE_POLL_MS);
  }

  function startPolling() {
    if (state.pollTimer) clearInterval(state.pollTimer);
    state.pollTimer = setInterval(function () {
      if (!document.getElementById('communication-hub-page')) return;
      refreshConversations().then(function () {
        if (state.activeId) refreshActiveMessages();
      });
    }, POLL_MS);
    ensureMessagePolling();
  }

  function onHubVisibility() {
    if (document.hidden) return;
    if (!document.getElementById('communication-hub-page')) return;
    refreshConversations().then(function () {
      if (state.activeId) refreshActiveMessages();
    });
  }

  function bind() {
    var list = $('#ch-conv-list');
    if (list) {
      list.addEventListener('click', function (e) {
        var delBtn = e.target.closest('.ch-conv-delete, [data-ch-delete]');
        if (delBtn) {
          e.preventDefault();
          e.stopPropagation();
          if (typeof e.stopImmediatePropagation === 'function') e.stopImmediatePropagation();
          var delItem = delBtn.closest('.ch-conv-item');
          if (!delItem) return;
          deleteConversation(
            delItem.getAttribute('data-id'),
            delItem.getAttribute('data-label') || delItem.getAttribute('data-phone')
          );
          return;
        }
        if (e.target.closest('.ch-conv-delete')) return;
        var openBtn = e.target.closest('.ch-conv-open');
        var item = e.target.closest('.ch-conv-item');
        if (!item) return;
        if (openBtn || e.target === item) {
          openConversation(item.getAttribute('data-id'));
        }
      });
    }
    document.addEventListener('visibilitychange', onHubVisibility);
    window.addEventListener('focus', onHubVisibility);
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
    if (composer) {
      composer.addEventListener('submit', sendMessage);
      var sendBtn = $('#ch-send-btn');
      if (sendBtn) {
        sendBtn.addEventListener('click', function () {
        });
      }
      var attachBtn = $('#ch-attach-btn');
      var attachInput = $('#ch-attach-input');
      var emojiBtn = $('#ch-emoji-btn');
      if (emojiBtn) {
        emojiBtn.onclick = function (e) {
          e.preventDefault();
          e.stopPropagation();
          toggleEmojiPanel();
        };
      }
      if (!window.__chEmojiDocBound) {
        window.__chEmojiDocBound = true;
        document.addEventListener('click', function (e) {
          var wrap = $('.ch-emoji-wrap');
          if (!wrap) return;
          if (wrap.contains(e.target)) return;
          closeEmojiPanel();
        });
        document.addEventListener('keydown', function (e) {
          if (e.key === 'Escape') closeEmojiPanel();
        });
      }
      if (attachBtn && attachInput) {
        attachBtn.addEventListener('click', function () {
          if (state.sending || attachBtn.disabled) return;
          if (!state.activeId) {
            setSendError('Open a conversation before attaching a file.');
            return;
          }
          attachInput.click();
        });
        attachInput.addEventListener('change', function () {
          var file = attachInput.files && attachInput.files[0];
          if (file) sendAttachment(file);
        });
      }
    } else {
    }
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
    /* Always hit the API — soft-nav prefetch can serve a stale empty inbox. */
    refreshConversations();
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
