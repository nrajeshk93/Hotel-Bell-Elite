"""CSRF for cookie-authenticated state-changing requests.

Double-submit cookie + session token. Same-origin fetch/XHR/forms send the
token automatically from static/csrf.js. Public and API-key endpoints are
exempt so login, WhatsApp, and the print agent keep working.
"""

from __future__ import annotations

import hmac
import secrets

from flask import abort, request, session

CSRF_SESSION_KEY = "_csrf_token"
CSRF_COOKIE_NAME = "hbe_csrf"
CSRF_FORM_FIELD = "csrf_token"
CSRF_HEADERS = ("X-CSRFToken", "X-CSRF-Token")

_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Endpoint names that must never require a CSRF token.
EXEMPT_ENDPOINTS = frozenset(
    {
        "index",
        "login",
        "login_get",
        "login_captcha",
        "login_resend_unlock",
        "unlock_account",
        "whatsapp_webhook",
        "print_agent_heartbeat",
        "print_agent_updates_latest",
        "print_jobs_pending",
        "print_jobs_ack",
        "static",
        "favicon",
        "service_worker",
        "robots_txt",
        "sitemap_xml",
    }
)

AUTH_USER_SESSION_KEY = "user_id"


def _tokens_match(left: str, right: str) -> bool:
    a = (left or "").encode("utf-8")
    b = (right or "").encode("utf-8")
    if not a or not b or len(a) != len(b):
        return False
    return hmac.compare_digest(a, b)


def get_csrf_token() -> str:
    """Stable per-session token for templates and the CSRF cookie."""
    token = session.get(CSRF_SESSION_KEY) or ""
    if not token:
        token = secrets.token_urlsafe(32)
        session[CSRF_SESSION_KEY] = token
    return token


def _submitted_token() -> str:
    for header in CSRF_HEADERS:
        value = (request.headers.get(header) or "").strip()
        if value:
            return value
    form_value = (request.form.get(CSRF_FORM_FIELD) or "").strip()
    if form_value:
        return form_value
    if request.is_json:
        payload = request.get_json(silent=True) or {}
        if isinstance(payload, dict):
            value = str(payload.get(CSRF_FORM_FIELD) or payload.get("csrfToken") or "").strip()
            if value:
                return value
    return ""


def _path_is_exempt() -> bool:
    path = request.path or ""
    if path.startswith("/webhook/"):
        return True
    # Existing enrolled agents POST heartbeat with a bearer token, not a CSRF cookie.
    if path.startswith("/api/print-agent/heartbeat"):
        return True
    if path.startswith("/api/print-agent/updates/"):
        return True
    if path.startswith("/api/print-jobs/") and path.endswith("/ack"):
        return True
    if path == "/api/print-jobs/pending":
        return True
    if path.startswith("/static/"):
        return True
    if path.startswith("/preview-api/"):
        return True
    return False


def csrf_should_check(app) -> bool:
    if request.method not in _UNSAFE_METHODS:
        return False
    if app.config.get("TESTING"):
        return False
    if request.endpoint in EXEMPT_ENDPOINTS:
        return False
    if _path_is_exempt():
        return False
    # Cookie-authenticated requests only — login/unlock/webhook have no user session.
    if not session.get(AUTH_USER_SESSION_KEY):
        return False
    return True


def csrf_protect_request(app) -> None:
    if not csrf_should_check(app):
        return
    expected = session.get(CSRF_SESSION_KEY) or ""
    submitted = _submitted_token()
    cookie = (request.cookies.get(CSRF_COOKIE_NAME) or "").strip()
    if expected and submitted and _tokens_match(submitted, expected):
        return
    if submitted and cookie and _tokens_match(submitted, cookie):
        return
    abort(400, description="CSRF token missing or invalid.")


def set_csrf_cookie(response, *, secure: bool) -> None:
    """Expose the token to JS (not HttpOnly) for fetch/XHR auto-send.

    HttpOnly stays off on purpose: static/csrf.js reads the hbe_csrf cookie as a
    fallback when meta[name=csrf-token] is missing (double-submit). Setting
    HttpOnly would break CSRF on pages that rely on the cookie.
    """
    try:
        token = session.get(CSRF_SESSION_KEY) or ""
    except RuntimeError:
        return
    if not token:
        return
    response.set_cookie(
        CSRF_COOKIE_NAME,
        token,
        httponly=False,
        samesite="Lax",
        secure=bool(secure),
        path="/",
    )
