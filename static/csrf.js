/**
 * Auto-send CSRF token on same-origin state-changing requests.
 * Reads meta[name="csrf-token"] or the hbe_csrf cookie (double-submit).
 */
(function (global) {
  'use strict';

  if (global.__hbeCsrfInstalled) return;
  global.__hbeCsrfInstalled = true;

  var COOKIE = 'hbe_csrf';
  var HEADER = 'X-CSRFToken';
  var FIELD = 'csrf_token';
  var UNSAFE = { POST: 1, PUT: 1, PATCH: 1, DELETE: 1 };

  function readCookie(name) {
    try {
      var parts = ('; ' + document.cookie).split('; ' + name + '=');
      if (parts.length < 2) return '';
      return decodeURIComponent(parts.pop().split(';').shift() || '');
    } catch (e) {
      return '';
    }
  }

  function getToken() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    if (meta && meta.content) return meta.content;
    return readCookie(COOKIE);
  }

  function isSameOrigin(url) {
    try {
      var resolved = new URL(url, global.location.href);
      return resolved.origin === global.location.origin;
    } catch (e) {
      return false;
    }
  }

  function methodOf(value) {
    return String(value || 'GET').toUpperCase();
  }

  function injectFormToken(form) {
    if (!form || form.method && methodOf(form.method) === 'GET') return;
    var method = methodOf(form.getAttribute('method') || form.method || 'GET');
    if (!UNSAFE[method]) return;
    var token = getToken();
    if (!token) return;
    var existing = form.querySelector('input[name="' + FIELD + '"]');
    if (existing) {
      existing.value = token;
      return;
    }
    var input = document.createElement('input');
    input.type = 'hidden';
    input.name = FIELD;
    input.value = token;
    form.appendChild(input);
  }

  document.addEventListener(
    'submit',
    function (event) {
      injectFormToken(event.target);
    },
    true
  );

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      Array.prototype.forEach.call(document.querySelectorAll('form'), injectFormToken);
    });
  } else {
    Array.prototype.forEach.call(document.querySelectorAll('form'), injectFormToken);
  }

  var origFetch = global.fetch;
  if (typeof origFetch === 'function') {
    global.fetch = function (input, init) {
      var opts = init ? Object.assign({}, init) : {};
      var url = '';
      var method = methodOf(opts.method);
      if (typeof input === 'string') {
        url = input;
      } else if (input && typeof input === 'object') {
        url = input.url || '';
        if (!opts.method && input.method) method = methodOf(input.method);
      }
      if (UNSAFE[method] && isSameOrigin(url)) {
        var token = getToken();
        if (token) {
          var headers;
          if (opts.headers && typeof opts.headers.append === 'function') {
            headers = opts.headers;
            if (!headers.has(HEADER) && !headers.has('X-CSRF-Token')) {
              headers.set(HEADER, token);
            }
          } else {
            headers = Object.assign({}, opts.headers || {});
            var has = Object.keys(headers).some(function (k) {
              return k.toLowerCase() === 'x-csrftoken' || k.toLowerCase() === 'x-csrf-token';
            });
            if (!has) headers[HEADER] = token;
            opts.headers = headers;
          }
        }
      }
      return origFetch.call(global, input, opts);
    };
  }

  var XHR = global.XMLHttpRequest;
  if (XHR && XHR.prototype) {
    var origOpen = XHR.prototype.open;
    var origSend = XHR.prototype.send;
    XHR.prototype.open = function (method, url) {
      this.__hbeCsrfMethod = methodOf(method);
      this.__hbeCsrfUrl = url || '';
      return origOpen.apply(this, arguments);
    };
    XHR.prototype.send = function () {
      if (UNSAFE[this.__hbeCsrfMethod] && isSameOrigin(this.__hbeCsrfUrl)) {
        var token = getToken();
        if (token) {
          try {
            this.setRequestHeader(HEADER, token);
          } catch (e) {}
        }
      }
      return origSend.apply(this, arguments);
    };
  }
})(typeof window !== 'undefined' ? window : this);
