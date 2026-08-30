#!/usr/bin/env python3
"""Serve the Kivy mobile UI preview + live Approvals against local Flask.

List data is read from bell_elite.db (all pending/approved by default).
Approve / Revert POST to the running Flask app on HBE_API_BASE_URL (default
http://127.0.0.1:8002) using a signed session for a local admin user.
"""

from __future__ import annotations

import json
import html
import re
import os
import secrets
import sqlite3
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, urlencode, urlparse

PREVIEW_DIR = Path(__file__).resolve().parent
REPO_ROOT = PREVIEW_DIR.parents[1]
DB_PATH = REPO_ROOT / "bell_elite.db"
OUTLET_HOTEL = "Hotel"
HOST = "127.0.0.1"
PORT = int(os.environ.get("HBE_PREVIEW_PORT", "8765"))
FLASK_BASE = os.environ.get("HBE_API_BASE_URL", "http://127.0.0.1:8002").rstrip("/")
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "0:0:0:0:0:0:0:1"})
_PRODUCTION_API_HOSTS = frozenset({"belleliteaccounts.com", "www.belleliteaccounts.com"})



class PreviewSafetyError(RuntimeError):
    pass


def _is_loopback_host(host: str) -> bool:
    return (host or "").strip().lower().strip("[]") in _LOOPBACK_HOSTS


def _is_production_api_url(url: str) -> bool:
    hostname = (urlparse((url or "").strip()).hostname or "").lower()
    if not hostname:
        return False
    return hostname in _PRODUCTION_API_HOSTS or hostname.endswith(".belleliteaccounts.com")


def _is_local_preview_db(path: Path) -> bool:
    try:
        resolved = path.resolve()
        repo = REPO_ROOT.resolve()
        return resolved == (repo / "bell_elite.db").resolve() or str(resolved).startswith(
            str(repo) + os.sep
        )
    except Exception:
        return False


def assert_preview_safe(
    *,
    bind_host: str | None = None,
    flask_base: str | None = None,
    db_path: Path | None = None,
) -> None:
    host = HOST if bind_host is None else bind_host
    if not _is_loopback_host(host):
        raise PreviewSafetyError(
            f"Preview refuses to bind to {host!r}; use 127.0.0.1, localhost, or ::1."
        )
    base = FLASK_BASE if flask_base is None else flask_base
    if _is_production_api_url(base):
        raise PreviewSafetyError("Preview refuses to run against the production API.")
    db = DB_PATH if db_path is None else db_path
    if not _is_local_preview_db(db):
        raise PreviewSafetyError("Preview refuses a non-local or production database path.")


def friendly_flask_error(exc: BaseException | str) -> str:
    """User-facing message for Flask proxy failures (hide raw urlopen noise)."""
    text = str(exc or "").strip()
    lower = text.lower()
    if (
        "connection refused" in lower
        or "errno 61" in lower
        or "failed to establish" in lower
        or "nodename nor servname" in lower
        or "name or service not known" in lower
    ):
        return f"Server offline — start Flask on {FLASK_BASE}"
    if "timed out" in lower or "timeout" in lower:
        return f"Server timed out — check Flask on {FLASK_BASE}"
    if text.startswith("<urlopen error") or "urlopen error" in lower:
        return f"Cannot reach Flask on {FLASK_BASE}"
    return text or f"Cannot reach Flask on {FLASK_BASE}"


_MD_DASHBOARD_DATA_RE = re.compile(
    r'<script[^>]*id=["\']md-dashboard-data["\'][^>]*>(?P<body>.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)
DASHBOARD_PERIODS = ("today", "7d", "30d", "mtd")
DASHBOARD_LOCATIONS = ("All", "Hotel", "Restaurant", "Bar")



if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from expense_stock_lines import expense_stock_detail  # noqa: E402


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def _money(value: object) -> float:
    try:
        return round(float(value or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def fetch_pending(limit: int = 0) -> dict:
    """All pending hotel purchase verifications (no FY date filter)."""
    sql = """
        SELECT e.id, e.expense_code, e.sales_date, e.description, e.amount,
               e.category, e.supplier_id, e.entry_kind,
               s.name AS supplier_name,
               COALESCE((
                   SELECT SUM(a.amount) FROM purchase_verification_allocations a
                   WHERE a.expense_id = e.id
               ), 0) AS paid_amount
        FROM sales_update_expenses e
        LEFT JOIN suppliers s ON s.id = e.supplier_id
        WHERE e.location = ?
        ORDER BY e.sales_date DESC, e.created_at DESC, e.id DESC
    """
    rows_out: list[dict] = []
    with _connect() as conn:
        for row in conn.execute(sql, (OUTLET_HOTEL,)):
            amount = _money(row["amount"])
            paid = _money(row["paid_amount"])
            balance = round(amount - paid, 2)
            if balance <= 0.001:
                continue
            rows_out.append(
                {
                    "id": int(row["id"]),
                    "supplier_id": int(row["supplier_id"] or 0),
                    "supplier_name": str(row["supplier_name"] or ""),
                    "expense_code": str(row["expense_code"] or ""),
                    "description": str(row["description"] or ""),
                    "amount": amount,
                    "balance": balance,
                    "sales_date": str(row["sales_date"] or ""),
                    "category": str(row["category"] or ""),
                    "entry_kind": str(row["entry_kind"] or "expense"),
                }
            )
    rows = rows_out if limit <= 0 else rows_out[:limit]
    return {
        "ok": True,
        "view": "pending",
        "source": "local-db",
        "flask_base": FLASK_BASE,
        "total": len(rows_out),
        "rows": rows,
    }


def fetch_approved(limit: int = 0) -> dict:
    """All approved purchase verifications (no FY date filter)."""
    sql = """
        SELECT v.id, v.verification_date AS payment_date, v.total_amount,
               v.verification_account, s.name AS supplier_name,
               (
                   SELECT COUNT(*) FROM purchase_verification_allocations a
                   WHERE a.purchase_verification_id = v.id
               ) AS allocation_count,
               (
                   SELECT GROUP_CONCAT(
                       COALESCE(NULLIF(TRIM(e.expense_code), ''), '#' || e.id),
                       ', '
                   )
                   FROM purchase_verification_allocations a
                   LEFT JOIN sales_update_expenses e ON e.id = a.expense_id
                   WHERE a.purchase_verification_id = v.id
               ) AS expense_codes
        FROM purchase_verifications v
        LEFT JOIN suppliers s ON s.id = v.supplier_id
        ORDER BY v.verification_date DESC, v.id DESC
    """
    rows_out: list[dict] = []
    with _connect() as conn:
        for row in conn.execute(sql):
            rows_out.append(
                {
                    "id": int(row["id"]),
                    "supplier_name": str(row["supplier_name"] or ""),
                    "total_amount": _money(row["total_amount"]),
                    "payment_date": str(row["payment_date"] or ""),
                    "verification_account": str(row["verification_account"] or ""),
                    "allocation_count": int(row["allocation_count"] or 0),
                    "expense_codes": str(row["expense_codes"] or ""),
                }
            )
    rows = rows_out if limit <= 0 else rows_out[:limit]
    return {
        "ok": True,
        "view": "approved",
        "source": "local-db",
        "flask_base": FLASK_BASE,
        "total": len(rows_out),
        "rows": rows,
    }


def fetch_indent_pending(limit: int = 0) -> dict:
    """Indents waiting for approve/reject (same query as /stores/approvals)."""
    sql = """
        SELECT i.id, i.indent_no, i.outlet, i.notes, i.status,
               i.submitted_at, i.created_at,
               u.full_name AS created_by_name,
               (SELECT COUNT(*) FROM store_indent_lines l WHERE l.indent_id = i.id) AS line_count,
               (SELECT COALESCE(SUM(
                    COALESCE(l.quantity, 0) * COALESCE(l.approximate_price, 0)
                ), 0)
                FROM store_indent_lines l WHERE l.indent_id = i.id) AS approximate_total
        FROM store_indents i
        LEFT JOIN users u ON u.id = i.created_by
        WHERE i.status = 'pending'
        ORDER BY i.submitted_at ASC, i.id ASC
    """
    rows_out: list[dict] = []
    with _connect() as conn:
        for row in conn.execute(sql):
            total = _money(row["approximate_total"])
            submitted = str(row["submitted_at"] or row["created_at"] or "")
            rows_out.append(
                {
                    "id": int(row["id"]),
                    "indent_no": str(row["indent_no"] or ""),
                    "outlet": str(row["outlet"] or ""),
                    "notes": str(row["notes"] or ""),
                    "status": "pending",
                    "created_by_name": str(row["created_by_name"] or ""),
                    "line_count": int(row["line_count"] or 0),
                    "approximate_total": total,
                    "submitted_at": submitted[:19],
                }
            )
    rows = rows_out if limit <= 0 else rows_out[:limit]
    return {
        "ok": True,
        "view": "pending",
        "source": "local-db",
        "flask_base": FLASK_BASE,
        "total": len(rows_out),
        "rows": rows,
    }


def fetch_indent_recent(limit: int = 20) -> dict:
    """Recent approved/rejected indents."""
    sql = """
        SELECT i.id, i.indent_no, i.outlet, i.notes, i.status,
               i.decided_at, i.decision_note,
               u.full_name AS created_by_name,
               d.full_name AS decided_by_name,
               (SELECT COUNT(*) FROM store_indent_lines l WHERE l.indent_id = i.id) AS line_count,
               (SELECT COALESCE(SUM(
                    COALESCE(l.quantity, 0) * COALESCE(l.approximate_price, 0)
                ), 0)
                FROM store_indent_lines l WHERE l.indent_id = i.id) AS approximate_total
        FROM store_indents i
        LEFT JOIN users u ON u.id = i.created_by
        LEFT JOIN users d ON d.id = i.decided_by
        WHERE i.status IN ('approved', 'rejected')
        ORDER BY i.decided_at DESC, i.id DESC
        LIMIT ?
    """
    rows_out: list[dict] = []
    with _connect() as conn:
        for row in conn.execute(sql, (max(1, int(limit or 20)),)):
            total = _money(row["approximate_total"])
            rows_out.append(
                {
                    "id": int(row["id"]),
                    "indent_no": str(row["indent_no"] or ""),
                    "outlet": str(row["outlet"] or ""),
                    "notes": str(row["notes"] or ""),
                    "status": str(row["status"] or ""),
                    "created_by_name": str(row["created_by_name"] or ""),
                    "decided_by_name": str(row["decided_by_name"] or ""),
                    "decision_note": str(row["decision_note"] or ""),
                    "line_count": int(row["line_count"] or 0),
                    "approximate_total": total,
                    "decided_at": str(row["decided_at"] or "")[:19],
                }
            )
    return {
        "ok": True,
        "view": "recent",
        "source": "local-db",
        "flask_base": FLASK_BASE,
        "total": len(rows_out),
        "rows": rows_out,
    }


def decide_indent(payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """Approve or reject a pending indent (local DB, same rules as Flask)."""
    try:
        indent_id = int(payload.get("indent_id") or 0)
    except (TypeError, ValueError):
        indent_id = 0
    decision = str(payload.get("decision") or "").strip().lower()
    note = str(payload.get("decision_note") or "").strip()
    if not indent_id:
        return 400, {"ok": False, "error": "indent_id is required"}
    if decision not in {"approved", "rejected"}:
        return 400, {"ok": False, "error": "Choose approve or reject."}
    if decision == "rejected" and not note:
        return 400, {"ok": False, "error": "Add a short reason when rejecting."}

    user_id = _effective_preview_user_id()
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, indent_no, outlet, status FROM store_indents WHERE id = ?",
            (indent_id,),
        ).fetchone()
        if not row or str(row["status"] or "") != "pending":
            return 400, {"ok": False, "error": "This indent is not waiting for approval."}
        conn.execute(
            """
            UPDATE store_indents
            SET status = ?, decided_by = ?, decided_at = datetime('now'), decision_note = ?
            WHERE id = ?
            """,
            (decision, user_id, note if decision == "rejected" else "", indent_id),
        )
        conn.commit()
        indent_no = str(row["indent_no"] or f"#{indent_id}")
        outlet = str(row["outlet"] or "")
    msg = "Indent approved." if decision == "approved" else "Indent rejected."
    return 200, {
        "ok": True,
        "message": msg,
        "indent_id": indent_id,
        "indent_no": indent_no,
        "outlet": outlet,
        "decision": decision,
        "flask_base": FLASK_BASE,
    }


def _resolve_preview_user_id() -> int:
    env_id = (os.environ.get("HBE_PREVIEW_USER_ID") or "").strip()
    if env_id.isdigit():
        return int(env_id)
    with _connect() as conn:
        row = conn.execute(
            """SELECT id FROM users
               WHERE is_active = 1 AND is_admin = 1
               ORDER BY id ASC LIMIT 1"""
        ).fetchone()
        if not row:
            row = conn.execute(
                "SELECT id FROM users WHERE is_active = 1 ORDER BY id ASC LIMIT 1"
            ).fetchone()
        if not row:
            raise RuntimeError("No active user found in bell_elite.db for preview auth")
        return int(row["id"])


# Signed-in preview clients (HTML phone mock). Token → session payload.
_preview_sessions: dict[str, dict[str, Any]] = {}
_PREVIEW_SESSION_TTL_S = 30 * 24 * 60 * 60
_request_ctx = threading.local()


def _ensure_preview_sessions_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS mobile_preview_sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            username TEXT NOT NULL DEFAULT '',
            display_name TEXT NOT NULL DEFAULT '',
            access_json TEXT NOT NULL DEFAULT '{}',
            created_at REAL NOT NULL
        )
        """
    )


def _save_preview_session(
    token: str,
    user_id: int,
    username: str,
    display_name: str,
    access: dict[str, Any],
) -> None:
    _preview_sessions[token] = {
        "user_id": int(user_id),
        "username": username,
        "display_name": display_name,
        "access": access,
        "created_at": time.time(),
    }
    try:
        with _connect() as conn:
            _ensure_preview_sessions_table(conn)
            conn.execute(
                """
                INSERT OR REPLACE INTO mobile_preview_sessions
                    (token, user_id, username, display_name, access_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    token,
                    int(user_id),
                    username,
                    display_name,
                    json.dumps(access or {}),
                    time.time(),
                ),
            )
            conn.commit()
    except Exception:
        pass


def _delete_preview_session(token: str) -> None:
    token = (token or "").strip()
    if not token:
        return
    _preview_sessions.pop(token, None)
    try:
        with _connect() as conn:
            _ensure_preview_sessions_table(conn)
            conn.execute("DELETE FROM mobile_preview_sessions WHERE token = ?", (token,))
            conn.commit()
    except Exception:
        pass


def _preview_session_row(token: str) -> Optional[sqlite3.Row]:
    token = (token or "").strip()
    if not token:
        return None
    try:
        with _connect() as conn:
            _ensure_preview_sessions_table(conn)
            return conn.execute(
                "SELECT * FROM mobile_preview_sessions WHERE token = ?",
                (token,),
            ).fetchone()
    except Exception:
        return None


def _set_request_preview_user(user_id: Optional[int], access: Optional[dict[str, Any]] = None) -> None:
    _request_ctx.user_id = user_id
    _request_ctx.access = access or None


def _request_preview_user_id() -> Optional[int]:
    return getattr(_request_ctx, "user_id", None)


def _request_preview_access() -> Optional[dict[str, Any]]:
    return getattr(_request_ctx, "access", None)


def _effective_preview_user_id() -> int:
    req_id = _request_preview_user_id()
    if req_id:
        return int(req_id)
    return _resolve_preview_user_id()


def _load_user_by_id(user_id: int):
    from workspace_access import build_user_context

    with _connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (int(user_id),)).fetchone()
        if not row:
            return None
        return build_user_context(conn, row)


def mobile_access_for_user(user) -> dict[str, Any]:
    from workspace_access import mobile_module_access

    return mobile_module_access(user)


def preview_authenticate(username: str, password: str) -> tuple[int, dict[str, Any]]:
    """Validate credentials against bell_elite.db (same rules as web /login)."""
    import auth_security
    from workspace_access import (
        build_user_context,
        mobile_module_access,
        user_has_assigned_access_role,
    )

    username = (username or "").strip()
    password = password or ""
    if not username or not password:
        return 400, {"ok": False, "error": "Enter username and password."}

    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE LOWER(username) = LOWER(?) AND is_active = 1",
            (username,),
        ).fetchone()
        if row and auth_security.is_account_locked(row):
            return 403, {
                "ok": False,
                "error": (
                    "This account is locked after too many failed sign-in attempts. "
                    "Ask an administrator to unlock the account."
                ),
            }
        password_ok = bool(row) and auth_security.verify_password_for_row(row, password)
        if not row or not password_ok:
            if row:
                auth_security.record_failed_login(conn, int(row["id"]))
                conn.commit()
            return 401, {"ok": False, "error": "Invalid username or password."}

        user = build_user_context(conn, row)
        if not user_has_assigned_access_role(user):
            return 403, {
                "ok": False,
                "error": (
                    "This account is not in User & Access. "
                    "Ask an administrator to assign a role."
                ),
            }
        auth_security.clear_login_failures(conn, int(row["id"]))
        auth_security.upgrade_password_hash_if_needed(
            conn,
            int(row["id"]),
            password,
            row["password_hash"],
        )
        conn.commit()

    access = mobile_module_access(user)
    token = secrets.token_urlsafe(32)
    display_name = str(user.get("display_name") or user.get("username") or username).strip()
    payload = {
        "ok": True,
        "token": token,
        "user_id": int(user["id"]),
        "username": str(user.get("username") or username),
        "display_name": display_name,
        "role_name": str(user.get("role_name") or ""),
        "must_change_password": bool(user.get("must_change_password")),
        "access": access,
    }
    _save_preview_session(
        token,
        int(user["id"]),
        payload["username"],
        display_name,
        access,
    )
    return 200, payload


def preview_session_from_token(token: str) -> Optional[dict[str, Any]]:
    token = (token or "").strip()
    if not token:
        return None
    cached = _preview_sessions.get(token)
    row = _preview_session_row(token)
    if row is not None:
        age = time.time() - float(row["created_at"] or 0)
        if age < 0 or age > _PREVIEW_SESSION_TTL_S:
            _delete_preview_session(token)
            return None
        cached = {
            "user_id": int(row["user_id"]),
            "username": str(row["username"] or ""),
            "display_name": str(row["display_name"] or ""),
            "access": json.loads(row["access_json"] or "{}"),
            "created_at": float(row["created_at"] or 0),
        }
        _preview_sessions[token] = cached
    if not cached:
        return None
    user = _load_user_by_id(int(cached["user_id"]))
    if not user:
        _delete_preview_session(token)
        return None
    from workspace_access import user_has_assigned_access_role

    if not user_has_assigned_access_role(user):
        _delete_preview_session(token)
        return None
    access = mobile_access_for_user(user)
    cached["access"] = access
    cached["display_name"] = str(user.get("display_name") or user.get("username") or "")
    return {
        "ok": True,
        "token": token,
        "user_id": int(user["id"]),
        "username": str(user.get("username") or ""),
        "display_name": cached["display_name"],
        "role_name": str(user.get("role_name") or ""),
        "must_change_password": bool(user.get("must_change_password")),
        "access": access,
    }


def preview_logout(token: str) -> dict[str, Any]:
    _delete_preview_session(token)
    return {"ok": True}


def _token_from_headers(handler: SimpleHTTPRequestHandler) -> str:
    auth = (handler.headers.get("Authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return (handler.headers.get("X-Preview-Token") or "").strip()


def _bind_preview_auth(handler: SimpleHTTPRequestHandler) -> Optional[dict[str, Any]]:
    """Attach signed-in preview user to this request (Flask proxy + access gates)."""
    session = preview_session_from_token(_token_from_headers(handler))
    if session:
        _set_request_preview_user(int(session["user_id"]), session.get("access") or {})
        try:
            _flask.impersonate(int(session["user_id"]))
        except Exception:
            pass
    else:
        _set_request_preview_user(None, None)
    return session


def _require_preview_access(access_key: str) -> Optional[dict[str, Any]]:
    """Return an error payload when the signed-in preview user lacks access_key."""
    access = _request_preview_access()
    if access is None:
        return {"ok": False, "error": "Sign in required."}
    if access.get("is_admin") or access.get(access_key):
        return None
    return {"ok": False, "error": "You do not have access to this module."}


def _flask_request_inprocess(
    method: str,
    path: str,
    body: Optional[dict[str, Any]] = None,
    user_id: Optional[int] = None,
) -> Optional[tuple[int, dict[str, Any]]]:
    """Run an authenticated Flask route in-process (avoids HTTP loopback on AWS)."""
    try:
        import csrf_protect
        from app import AUTH_USER_SESSION_KEY, app as flask_app
    except Exception:
        return None

    try:
        uid = int(user_id or _effective_preview_user_id())
    except Exception:
        return None

    route = path if path.startswith("/") else f"/{path}"
    csrf = secrets.token_urlsafe(32)
    headers = {
        "Accept": "application/json, text/html;q=0.9",
        "X-Requested-With": "XMLHttpRequest",
        "X-CSRF-Token": csrf,
        "X-CSRFToken": csrf,
    }

    try:
        with flask_app.test_client() as client:
            with client.session_transaction() as sess:
                sess[AUTH_USER_SESSION_KEY] = uid
                sess[csrf_protect.CSRF_SESSION_KEY] = csrf
            if method.upper() == "POST":
                resp = client.post(route, json=body or {}, headers=headers)
            elif method.upper() == "GET":
                resp = client.get(route, headers=headers)
            else:
                return None
            payload = resp.get_json(silent=True)
            if not isinstance(payload, dict):
                text = (resp.get_data(as_text=True) or "").strip()
                lower = text[:200].lower()
                if "<html" in lower or "<!doctype" in lower or "<title>" in lower:
                    text = f"Request failed (HTTP {resp.status_code})."
                else:
                    text = (text[:280] + "…") if len(text) > 280 else text
                payload = {
                    "ok": resp.status_code < 400,
                    "error": text or f"HTTP {resp.status_code}",
                }
            return resp.status_code, payload
    except Exception:
        return None




def _payroll_preview_access_key(path: str) -> Optional[str]:
    if path == "/preview-api/payroll/employees" or path.startswith("/preview-api/payroll/employees/"):
        return "payroll_employee"
    if path == "/preview-api/payroll/attendance" or path.startswith("/preview-api/payroll/attendance/"):
        return "payroll_attendance"
    if path == "/preview-api/payroll/credits" or path.startswith("/preview-api/payroll/credits/"):
        return "payroll_credit"
    if path == "/preview-api/payroll/tips" or path.startswith("/preview-api/payroll/tips/"):
        return "payroll_tips"
    return None


def _payroll_flask_path(preview_path: str, query: str = "") -> str:
    flask_path = "/api/mobile" + preview_path[len("/preview-api"):]
    if query:
        flask_path = f"{flask_path}?{query}"
    return flask_path


def proxy_payroll_mobile(
    method: str,
    preview_path: str,
    query: str = "",
    body: Optional[dict[str, Any]] = None,
) -> tuple[int, dict[str, Any]]:
    """Proxy Employee Payroll mobile JSON APIs through Flask in-process."""
    result = _flask_request_inprocess(method, _payroll_flask_path(preview_path, query), body)
    if result is None:
        return 502, {
            "ok": False,
            "error": friendly_flask_error("Cannot reach Flask"),
            "flask_base": FLASK_BASE,
        }
    status, data = result
    if not isinstance(data, dict):
        data = {"ok": status < 400, "error": "Invalid response"}
    return status, data


def fetch_indent_catalog(outlet: str = "restaurant") -> dict[str, Any]:
    """Product catalog for Indent Request (Flask in-process, then local DB)."""
    outlet_key = (outlet or "restaurant").strip().lower() or "restaurant"
    if outlet_key not in ("bar", "restaurant"):
        return {"ok": False, "error": "Choose Bar or Restaurant."}

    result = _flask_request_inprocess(
        "GET", f"/stores/api/indent-catalog?outlet={outlet_key}"
    )
    if result is not None:
        status, data = result
        if isinstance(data, dict):
            if status < 400 and data.get("ok"):
                out = dict(data)
                out.setdefault("outlet", outlet_key)
                out["source"] = "flask-inprocess"
                out["flask_base"] = FLASK_BASE
                return out
            if data.get("ok") is False:
                return data

    categories: list[dict[str, Any]] = []
    by_id: dict[int, dict[str, Any]] = {}
    product_ids: list[int] = []
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT c.id AS category_id, c.name AS category_name,
                   c.sort_order AS category_sort,
                   p.id AS product_id, p.name AS product_name, p.default_unit, p.outlet,
                   p.approximate_price, p.sort_order
            FROM store_product_categories c
            LEFT JOIN store_products p
              ON p.category_id = c.id AND p.is_active = 1
             AND lower(coalesce(p.outlet, '')) IN (?, 'both')
            WHERE c.is_active = 1
            ORDER BY c.sort_order, c.name, p.sort_order, p.name
            """,
            (outlet_key,),
        ).fetchall()
        for row in rows:
            cat_id = int(row["category_id"])
            if cat_id not in by_id:
                node = {"id": cat_id, "name": str(row["category_name"] or ""), "products": []}
                by_id[cat_id] = node
                categories.append(node)
            if row["product_id"]:
                pid = int(row["product_id"])
                product_ids.append(pid)
                price = row["approximate_price"]
                try:
                    price_f = float(price) if price is not None and price != "" else None
                except (TypeError, ValueError):
                    price_f = None
                by_id[cat_id]["products"].append({
                    "id": pid,
                    "name": str(row["product_name"] or ""),
                    "default_unit": str(row["default_unit"] or ""),
                    "outlet": str(row["outlet"] or ""),
                    "approximate_price": price_f,
                    "approximate_price_display": (
                        f"{price_f:.2f}" if price_f is not None else ""
                    ),
                    "variants": [],
                })
        variants_by: dict[int, list[dict[str, Any]]] = {pid: [] for pid in product_ids}
        if product_ids:
            placeholders = ",".join("?" for _ in product_ids)
            for vrow in conn.execute(
                f"""
                SELECT id, product_id, label, qty_in_base, approximate_price, sort_order
                FROM store_product_variants
                WHERE is_active = 1 AND product_id IN ({placeholders})
                ORDER BY sort_order, id
                """,
                product_ids,
            ):
                pid = int(vrow["product_id"])
                try:
                    qty = float(vrow["qty_in_base"] or 0)
                except (TypeError, ValueError):
                    qty = 0.0
                try:
                    vprice = float(vrow["approximate_price"]) if vrow["approximate_price"] not in (None, "") else None
                except (TypeError, ValueError):
                    vprice = None
                variants_by.setdefault(pid, []).append({
                    "id": int(vrow["id"]),
                    "label": str(vrow["label"] or ""),
                    "qty_in_base": qty,
                    "qty_in_base_display": f"{qty:g}" if qty else "",
                    "approximate_price": vprice,
                    "approximate_price_display": (
                        f"{vprice:.2f}" if vprice is not None else ""
                    ),
                })
        for cat in categories:
            for product in cat["products"]:
                product["variants"] = variants_by.get(int(product["id"]), [])
        categories = [cat for cat in categories if cat["products"]]
    return {
        "ok": True,
        "outlet": outlet_key,
        "categories": categories,
        "source": "local-db",
        "flask_base": FLASK_BASE,
    }


def create_indent_request(payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """Create indent (draft/submit) via Flask in-process — same rules as web."""
    if not isinstance(payload, dict):
        return 400, {"ok": False, "error": "JSON object required"}
    result = _flask_request_inprocess("POST", "/stores/api/indent", payload)
    if result is None:
        return 502, {
            "ok": False,
            "error": friendly_flask_error("Cannot reach Flask"),
            "flask_base": FLASK_BASE,
        }
    return result



def _flask_get_inprocess(
    path: str,
    user_id: Optional[int] = None,
) -> Optional[tuple[int, bytes, str]]:
    """In-process authenticated GET (HTML or JSON)."""
    try:
        import csrf_protect
        from app import AUTH_USER_SESSION_KEY, app as flask_app
    except Exception:
        return None

    try:
        uid = int(user_id or _effective_preview_user_id())
    except Exception:
        return None

    route = path if path.startswith("/") else f"/{path}"
    csrf = secrets.token_urlsafe(32)
    headers = {
        "Accept": "application/json, text/html;q=0.9",
        "X-Requested-With": "XMLHttpRequest",
        "X-CSRF-Token": csrf,
        "X-CSRFToken": csrf,
    }

    try:
        with flask_app.test_client() as client:
            with client.session_transaction() as sess:
                sess[AUTH_USER_SESSION_KEY] = uid
                sess[csrf_protect.CSRF_SESSION_KEY] = csrf
            resp = client.get(route, headers=headers)
            ctype = resp.content_type or "text/html"
            return resp.status_code, resp.data, ctype
    except Exception:
        return None


class FlaskLocalClient:
    """HTTP client to the running local Flask app with a forged session cookie."""

    def __init__(self, base_url: str = FLASK_BASE):
        self.base_url = base_url.rstrip("/")
        self._cookie_header = ""
        self._csrf = ""
        self._user_id: Optional[int] = None
        self._ready = False

    def impersonate(self, user_id: int) -> None:
        """Forge a Flask session for the given user (call before proxied POSTs)."""
        user_id = int(user_id)
        if self._ready and self._user_id == user_id:
            return
        self._ready = False
        self._user_id = user_id
        self._ensure()

    def _ensure(self) -> None:
        assert_preview_safe(flask_base=self.base_url)
        desired = int(self._user_id or _effective_preview_user_id())
        if self._ready and self._user_id == desired:
            return
        try:
            from flask.sessions import SecureCookieSessionInterface

            from app import app as flask_app
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                f"Cannot talk to local Flask ({self.base_url}): {exc}. "
                "Run serve.py with the project .venv (Flask installed)."
            ) from exc

        user_id = desired
        csrf = secrets.token_urlsafe(32)
        serializer = SecureCookieSessionInterface().get_signing_serializer(flask_app)
        if serializer is None:
            raise RuntimeError("Flask session serializer unavailable")
        session_value = serializer.dumps({"user_id": user_id, "_csrf_token": csrf})
        self._cookie_header = f"session={session_value}; hbe_csrf={csrf}"
        self._csrf = csrf
        self._user_id = user_id
        self._ready = True
        # Warm CSRF path against the live site.
        try:
            self._request("GET", "/accounts/purchase-verification")
        except Exception:
            pass

    def _request(self, method: str, path: str, body: Optional[dict[str, Any]] = None) -> tuple[int, bytes, str]:
        import urllib.error
        import urllib.request

        url = self.base_url + path
        data = None
        headers = {
            "User-Agent": "HBE-Mobile-Preview/0.1",
            "Accept": "application/json, text/html;q=0.8",
            "Cookie": self._cookie_header,
            "X-Requested-With": "XMLHttpRequest",
        }
        if method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
            headers["X-CSRFToken"] = self._csrf
            headers["X-CSRF-Token"] = self._csrf
            headers["Content-Type"] = "application/json"
            data = json.dumps(body or {}).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.status, resp.read(), resp.headers.get("Content-Type") or ""
        except urllib.error.HTTPError as err:
            return err.code, err.read() or b"", err.headers.get("Content-Type") if err.headers else ""
        except urllib.error.URLError as err:
            raise ConnectionError(friendly_flask_error(err)) from err
        except TimeoutError as err:
            raise ConnectionError(friendly_flask_error(err)) from err


    def get(self, path: str) -> tuple[int, bytes, str]:
        """Authenticated GET against local Flask (HTML or JSON)."""
        inprocess = _flask_get_inprocess(path, self._user_id)
        if inprocess is not None:
            return inprocess
        self._ensure()
        return self._request("GET", path)

    def post_json(self, path: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        inprocess = _flask_request_inprocess("POST", path, body, self._user_id)
        if inprocess is not None:
            return inprocess
        self._ensure()
        status, raw, _ctype = self._request("POST", path, body)
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            payload = {"ok": False, "error": (raw.decode("utf-8", errors="replace")[:300] or f"HTTP {status}")}
        if not isinstance(payload, dict):
            payload = {"ok": False, "error": "Unexpected response from Flask"}
        return status, payload

    def health(self) -> dict[str, Any]:
        import urllib.error
        import urllib.request

        try:
            req = urllib.request.Request(self.base_url + "/login", method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                reachable = resp.status < 500
        except urllib.error.HTTPError as err:
            reachable = err.code < 500
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "flask_base": self.base_url, "error": str(exc)}
        try:
            self._ensure()
            return {
                "ok": True,
                "flask_base": self.base_url,
                "reachable": reachable,
                "preview_user_id": self._user_id,
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "flask_base": self.base_url,
                "reachable": reachable,
                "error": str(exc),
            }


_flask = FlaskLocalClient()


def _parse_md_dashboard_data(page: str) -> Optional[dict[str, Any]]:
    match = _MD_DASHBOARD_DATA_RE.search(page or "")
    if not match:
        return None
    raw = (match.group("body") or "").strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        try:
            data = json.loads(html.unescape(raw))
        except json.JSONDecodeError:
            return None
    return data if isinstance(data, dict) else None


def _dashboard_query(period: str, location: str, date_from: str = "", date_to: str = "") -> str:
    params = {"period": period, "location": location}
    if (date_from or "").strip() and (date_to or "").strip():
        params["date_from"] = date_from.strip()
        params["date_to"] = date_to.strip()
    return "/main-dashboard?" + urlencode(params)


def _fetch_main_dashboard_inprocess(
    period: str, location: str, date_from: str = "", date_to: str = ""
) -> Optional[dict[str, Any]]:
    """Build dashboard JSON inside the running Flask app (no HTTP self-proxy)."""
    try:
        from werkzeug.datastructures import MultiDict

        from app import (
            DASHBOARD_FILTER_LOCATION_ALL,
            _build_main_dashboard_payload,
            _resolve_main_dashboard_filters,
            get_db,
        )
        from mailer import app_base_url
    except Exception:
        return None

    pairs = [("period", period), ("location", location)]
    if (date_from or "").strip():
        pairs.append(("date_from", date_from.strip()))
    if (date_to or "").strip():
        pairs.append(("date_to", date_to.strip()))
    args = MultiDict(pairs)
    filters = _resolve_main_dashboard_filters(args)
    resolved_from = filters.pop("_date_from")
    resolved_to = filters.pop("_date_to")
    selected_location = filters["selected_location"]
    location_filter = (
        None if selected_location == DASHBOARD_FILTER_LOCATION_ALL else selected_location
    )
    resolved_period = filters.get("selected_period") or period

    conn = get_db()
    try:
        payload = _build_main_dashboard_payload(
            conn, resolved_from, resolved_to, location=location_filter
        )
    finally:
        conn.close()

    base = app_base_url().rstrip("/")
    path = _dashboard_query(
        resolved_period,
        location,
        filters.get("date_from") or "",
        filters.get("date_to") or "",
    )
    return {
        "ok": True,
        "period": resolved_period,
        "location": location,
        "date_from": filters.get("date_from") or "",
        "date_to": filters.get("date_to") or "",
        "flask_base": base,
        "webview_url": f"{base}{path}",
        "dashboard": payload.get("dashboard") or {},
    }


def fetch_main_dashboard(
    period: str = "today",
    location: str = "All",
    date_from: str = "",
    date_to: str = "",
) -> dict[str, Any]:
    """Load dashboard KPIs for mobile preview (in-process on production, HTTP locally)."""
    period_key = (period or "today").strip().lower()
    if period_key not in DASHBOARD_PERIODS and period_key != "custom":
        period_key = "today"
    loc = (location or "All").strip() or "All"
    if loc not in DASHBOARD_LOCATIONS:
        loc = "All"
    date_from = (date_from or "").strip()
    date_to = (date_to or "").strip()

    inprocess = _fetch_main_dashboard_inprocess(period_key, loc, date_from, date_to)
    if inprocess is not None:
        return inprocess

    path = _dashboard_query(period_key, loc, date_from, date_to)
    try:
        status, raw, _ctype = _flask.get(path)
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "error": friendly_flask_error(exc),
            "period": period_key,
            "location": loc,
            "flask_base": FLASK_BASE,
            "webview_url": FLASK_BASE + path,
        }
    page = raw.decode("utf-8", errors="replace") if isinstance(raw, (bytes, bytearray)) else str(raw or "")
    if status >= 400:
        return {
            "ok": False,
            "error": f"Flask HTTP {status}",
            "period": period_key,
            "location": loc,
            "flask_base": FLASK_BASE,
            "webview_url": FLASK_BASE + path,
        }
    data = _parse_md_dashboard_data(page)
    if not data:
        lower = page[:800].lower()
        if "login" in lower or 'name="password"' in lower:
            err = "Flask returned login page — preview session could not open /main-dashboard"
        elif "<!doctype" in lower or "<html" in lower:
            err = "Flask returned HTML without md-dashboard-data embed"
        else:
            err = "md-dashboard-data not found in /main-dashboard"
        return {
            "ok": False,
            "error": err,
            "period": period_key,
            "location": loc,
            "flask_base": FLASK_BASE,
            "webview_url": FLASK_BASE + path,
        }
    return {
        "ok": True,
        "period": period_key,
        "location": loc,
        "flask_base": FLASK_BASE,
        "webview_url": FLASK_BASE + path,
        "dashboard": data,
    }




def fetch_pos_tables(outlet: str = "restaurant") -> dict[str, Any]:
    """Live floor tables with occupancy synced from open (pre-invoice) dine-in bills.

    Matches web POS: Generate Invoice frees the tile even before Settle.
    """
    outlet_key = (outlet or "restaurant").strip().lower() or "restaurant"
    if outlet_key not in {"restaurant", "bar"}:
        outlet_key = "restaurant"
    tables: list[dict[str, Any]] = []
    try:
        from db import (  # noqa: WPS433
            ensure_pos_schema,
            get_pos_floor_layout,
            sync_pos_floor_occupancy_from_open_orders,
        )

        with _connect() as conn:
            ensure_pos_schema(conn)
            sync_pos_floor_occupancy_from_open_orders(conn, outlet_key)
            conn.commit()
            layout = get_pos_floor_layout(conn, outlet_key)
            for item in layout.get("tables") or []:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or item.get("label") or "").strip()
                if not name:
                    continue
                tables.append(
                    {
                        "id": str(item.get("id") or name),
                        "name": name,
                        "status": str(item.get("status") or "available"),
                        "seats": item.get("seats"),
                    }
                )
    except Exception:
        # Fallback: raw layout payload if db helpers are unavailable.
        with _connect() as conn:
            row = conn.execute(
                "SELECT payload FROM pos_floor_layout WHERE outlet = ?",
                (outlet_key,),
            ).fetchone()
            if row and row["payload"]:
                try:
                    payload = json.loads(row["payload"])
                except json.JSONDecodeError:
                    payload = {}
                for item in payload.get("tables") or []:
                    if not isinstance(item, dict):
                        continue
                    name = str(item.get("name") or item.get("label") or "").strip()
                    if not name:
                        continue
                    tables.append(
                        {
                            "id": str(item.get("id") or name),
                            "name": name,
                            "status": str(item.get("status") or "available"),
                            "seats": item.get("seats"),
                        }
                    )

    def _table_sort_key(row: dict[str, Any]) -> tuple[int, str]:
        name = str(row.get("name") or "")
        match = re.search(r"(\d+)\s*$", name)
        return (int(match.group(1)) if match else 10**9, name.lower())

    tables.sort(key=_table_sort_key)
    return {
        "ok": True,
        "outlet": outlet_key,
        "source": "local-db-synced",
        "flask_base": FLASK_BASE,
        "total": len(tables),
        "tables": tables,
    }


def _pos_json_get(path: str) -> dict[str, Any]:
    status, raw, _ctype = _flask.get(path)
    try:
        payload = json.loads(raw.decode("utf-8", errors="replace") or "{}")
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {"ok": False, "error": "Unexpected response"}
    if status >= 400 and "error" not in payload:
        payload = {
            "ok": False,
            "error": payload.get("error") or f"Flask HTTP {status}",
            "flask_base": FLASK_BASE,
        }
    elif "ok" not in payload:
        payload["ok"] = status < 400
    payload.setdefault("flask_base", FLASK_BASE)
    return payload


def fetch_pos_menu(outlet: str = "restaurant") -> dict[str, Any]:
    """Proxy restaurant/bar menu catalog for mobile POS search."""
    outlet_key = (outlet or "restaurant").strip().lower() or "restaurant"
    prefix = "/bar-point-of-sale" if outlet_key == "bar" else "/point-of-sale"
    try:
        payload = _pos_json_get(f"{prefix}/api/menu/items")
        items = payload.get("items") or payload.get("menu") or []
        if not isinstance(items, list):
            items = []
        if payload.get("ok") is not False and items:
            return {
                "ok": True,
                "outlet": outlet_key,
                "source": "flask",
                "flask_base": FLASK_BASE,
                "total": len(items),
                "items": items,
            }
    except Exception:
        payload = {"ok": False, "error": "flask menu unavailable"}

    # Local DB fallback (same catalog as POS admin).
    items_out: list[dict[str, Any]] = []
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT i.id, i.name, i.rate, i.code, i.barcode, i.category_id,
                   c.name AS category_name
            FROM pos_menu_items i
            LEFT JOIN pos_menu_categories c ON c.id = i.category_id
            WHERE COALESCE(i.is_active, 1) = 1
              AND (LOWER(COALESCE(i.outlet, 'restaurant')) = ? OR LOWER(COALESCE(i.outlet, '')) IN ('both', 'all', ''))
            ORDER BY c.sort_order, i.name
            """,
            (outlet_key,),
        ).fetchall()
        for row in rows:
            items_out.append(
                {
                    "id": int(row["id"]),
                    "name": str(row["name"] or ""),
                    "rate": _money(row["rate"]),
                    "code": str(row["code"] or ""),
                    "barcode": str(row["barcode"] or ""),
                    "category_id": row["category_id"],
                    "category_name": str(row["category_name"] or ""),
                }
            )
    return {
        "ok": True,
        "outlet": outlet_key,
        "source": "local-db",
        "flask_base": FLASK_BASE,
        "error": (payload or {}).get("error") if isinstance(payload, dict) else None,
        "total": len(items_out),
        "items": items_out,
    }


def fetch_pos_invoice_by_table(table: str, outlet: str = "restaurant") -> dict[str, Any]:
    from urllib.parse import quote

    table_name = (table or "").strip()
    if not table_name:
        return {"ok": False, "error": "table required", "invoice": None}
    outlet_key = (outlet or "restaurant").strip().lower() or "restaurant"
    prefix = "/bar-point-of-sale" if outlet_key == "bar" else "/point-of-sale"
    try:
        payload = _pos_json_get(
            f"{prefix}/api/invoices/by-table?table={quote(table_name)}"
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "invoice": None, "flask_base": FLASK_BASE}
    return payload


def pos_save_invoice(body: dict[str, Any], outlet: str = "restaurant") -> tuple[int, dict[str, Any]]:
    outlet_key = (outlet or "restaurant").strip().lower() or "restaurant"
    prefix = "/bar-point-of-sale" if outlet_key == "bar" else "/point-of-sale"
    return _flask.post_json(f"{prefix}/api/invoices", body)


def pos_send_kot(invoice_id: int, outlet: str = "restaurant") -> tuple[int, dict[str, Any]]:
    outlet_key = (outlet or "restaurant").strip().lower() or "restaurant"
    prefix = "/bar-point-of-sale" if outlet_key == "bar" else "/point-of-sale"
    return _flask.post_json(f"{prefix}/api/invoices/{int(invoice_id)}/send-kot", {})


def fetch_pos_kot_tokens(outlet: str = "restaurant") -> dict[str, Any]:
    """Proxy active kitchen order tokens for the mobile KOT page."""
    outlet_key = (outlet or "restaurant").strip().lower() or "restaurant"
    prefix = "/bar-point-of-sale" if outlet_key == "bar" else "/point-of-sale"
    try:
        payload = _pos_json_get(f"{prefix}/api/kot-tokens")
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "error": str(exc),
            "flask_base": FLASK_BASE,
            "token_count": 0,
            "tables": [],
        }
    if not isinstance(payload, dict):
        return {"ok": False, "error": "Unexpected response", "tables": [], "token_count": 0}
    payload.setdefault("tables", [])
    payload.setdefault("token_count", len(payload.get("tables") or []))
    payload.setdefault("flask_base", FLASK_BASE)
    return payload


def pos_reduce_kot_tokens(
    body: Optional[dict[str, Any]] = None,
    outlet: str = "restaurant",
) -> tuple[int, dict[str, Any]]:
    outlet_key = (outlet or "restaurant").strip().lower() or "restaurant"
    prefix = "/bar-point-of-sale" if outlet_key == "bar" else "/point-of-sale"
    return _flask.post_json(f"{prefix}/api/kot-tokens/reduce", body or {})


def pos_settle_invoice(
    invoice_id: int,
    body: Optional[dict[str, Any]] = None,
    outlet: str = "restaurant",
) -> tuple[int, dict[str, Any]]:
    outlet_key = (outlet or "restaurant").strip().lower() or "restaurant"
    prefix = "/bar-point-of-sale" if outlet_key == "bar" else "/point-of-sale"
    return _flask.post_json(
        f"{prefix}/api/invoices/{int(invoice_id)}/settle",
        body or {"method": "cash", "payment_splits": [{"method": "cash", "amount": None}]},
    )


def fetch_notifications() -> dict[str, Any]:
    """Pending purchase + indent approvals for the mobile preview bell."""
    items: list[dict[str, Any]] = []
    access = _request_preview_access()
    allow_purchase = access is None or bool(access.get("approvals"))
    allow_indent = access is None or bool(access.get("indent_approvals"))

    if allow_purchase:
        try:
            pending = fetch_pending(limit=0)
            count = int(pending.get("total") or 0)
        except Exception:
            count = 0
        if count > 0:
            label = "purchase" if count == 1 else "purchases"
            items.append(
                {
                    "id": "purchase-verification-pending",
                    "title": "Purchases awaiting approval",
                    "body": f"{count} {label} waiting for your review.",
                    "href": "/accounts/purchase-verification",
                    "screen": "approvals",
                    "count": count,
                }
            )

    if allow_indent:
        try:
            pending = fetch_indent_pending(limit=0)
            count = int(pending.get("total") or 0)
        except Exception:
            count = 0
        if count > 0:
            label = "indent" if count == 1 else "indents"
            items.append(
                {
                    "id": "stores-approvals-pending",
                    "title": "Indents awaiting approval",
                    "body": f"{count} {label} waiting for your review.",
                    "href": "/stores/approvals",
                    "screen": "indent-approvals",
                    "count": count,
                }
            )

    # Optional hub / other items from live Flask (non-blocking).
    try:
        status, raw, _ctype = _flask.get("/home/api/notifications")
        if status < 400:
            payload = json.loads(raw.decode("utf-8", errors="replace") or "{}")
            if isinstance(payload, dict) and payload.get("ok"):
                seen = {str(item.get("id") or "") for item in items}
                for row in payload.get("notifications") or []:
                    if not isinstance(row, dict):
                        continue
                    item_id = str(row.get("id") or "")
                    if item_id in seen:
                        continue
                    href = str(row.get("href") or "")
                    screen = ""
                    if (
                        "purchase-verification" in href
                        or "purchase_verification" in item_id
                        or item_id == "purchase-verification-pending"
                    ):
                        if not allow_purchase:
                            continue
                        screen = "approvals"
                    elif (
                        "indent" in href
                        or "stores/approvals" in href
                        or "store" in item_id
                        or item_id == "stores-approvals-pending"
                    ):
                        if not allow_indent:
                            continue
                        screen = "indent-approvals"
                    elif "communication" in href or "hub" in item_id:
                        screen = "home"
                    item = dict(row)
                    item["screen"] = screen
                    items.append(item)
                    seen.add(item_id)
    except Exception:
        pass

    return {
        "ok": True,
        "source": "local+flask",
        "flask_base": FLASK_BASE,
        "unread": bool(items),
        "notifications": items,
    }


MOBILE_PREVIEW_API_VERSION = "2026-08-28-direct-approvals"


def _approval_actor():
    user_id = _request_preview_user_id()
    if not user_id:
        return None, (401, {"ok": False, "error": "Sign in required."})
    user = _load_user_by_id(int(user_id))
    if not user:
        return None, (401, {"ok": False, "error": "Sign in required."})
    from workspace_access import user_can_approve_transactions

    if not user_can_approve_transactions(user):
        return None, (
            403,
            {"ok": False, "error": "You do not have Approval access to verify purchases."},
        )
    return user, None


def approve_expense(payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    try:
        supplier_id = int(payload.get("supplier_id") or 0)
        expense_id = int(payload.get("expense_id") or 0)
        amount = float(payload.get("amount") or 0)
    except (TypeError, ValueError):
        return 400, {"ok": False, "error": "supplier_id, expense_id, and amount are required"}
    if not supplier_id or not expense_id or amount <= 0:
        return 400, {"ok": False, "error": "supplier_id, expense_id, and amount are required"}

    user, denied = _approval_actor()
    if denied:
        return denied

    body = {
        "supplier_id": supplier_id,
        "allocations": [{"expense_id": expense_id, "amount": amount}],
        "notes": str(payload.get("notes") or "Approved from mobile app"),
    }

    try:
        from db import get_db
        from app import _purchase_verification_detail, _validate_purchase_verification_payload
    except Exception as exc:  # noqa: BLE001
        return 502, {"ok": False, "error": f"Approval service unavailable: {exc}"}

    conn = get_db()
    try:
        validated, errors = _validate_purchase_verification_payload(conn, body, user=user)
        if errors:
            return 400, {"ok": False, "error": errors[0], "errors": errors}
        cursor = conn.execute(
            """INSERT INTO purchase_verifications
               (company, supplier_id, verification_date, verification_method, verification_account,
                transaction_id, total_amount, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                validated["company"],
                validated["supplier_id"],
                validated["verification_date"],
                validated["verification_method"],
                validated["verification_account"],
                validated["transaction_id"],
                validated["total_amount"],
                validated["notes"],
            ),
        )
        verification_id = cursor.lastrowid
        for allocation in validated["allocations"]:
            conn.execute(
                """INSERT INTO purchase_verification_allocations
                   (purchase_verification_id, expense_id, amount)
                   VALUES (?, ?, ?)""",
                (verification_id, allocation["expense_id"], allocation["amount"]),
            )
        conn.commit()
        verification = _purchase_verification_detail(conn, verification_id)
    finally:
        conn.close()

    return 200, {"ok": True, "payment": verification, "flask_base": FLASK_BASE}


def revert_verification(payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    try:
        payment_id = int(payload.get("payment_id") or payload.get("id") or 0)
    except (TypeError, ValueError):
        payment_id = 0
    if not payment_id:
        return 400, {"ok": False, "error": "payment_id is required"}

    user, denied = _approval_actor()
    if denied:
        status, data = denied
        if status == 403:
            data = {
                "ok": False,
                "error": "You do not have Approval access to revert verifications.",
            }
        return status, data

    try:
        from db import get_db
    except Exception as exc:  # noqa: BLE001
        return 502, {"ok": False, "error": f"Approval service unavailable: {exc}"}

    conn = get_db()
    try:
        verification = conn.execute(
            "SELECT id FROM purchase_verifications WHERE id = ?",
            (payment_id,),
        ).fetchone()
        if not verification:
            return 404, {"ok": False, "error": "Verification was not found."}
        conn.execute(
            "DELETE FROM purchase_verification_allocations WHERE purchase_verification_id = ?",
            (payment_id,),
        )
        conn.execute("DELETE FROM purchase_verifications WHERE id = ?", (payment_id,))
        conn.commit()
    finally:
        conn.close()

    return 200, {"ok": True, "flask_base": FLASK_BASE}


def fetch_expense_detail(expense_id: int) -> dict[str, Any]:
    with _connect() as conn:
        detail = expense_stock_detail(conn, expense_id)
    if not detail:
        return {"ok": False, "error": "Expense not found"}
    detail["flask_base"] = FLASK_BASE
    return detail


def fetch_verification_detail(verification_id: int) -> dict[str, Any]:
    """Approved verification header + allocated expenses (with stock lines)."""
    sql = """
        SELECT v.id, v.verification_date AS payment_date, v.total_amount,
               v.verification_account, v.notes, v.supplier_id,
               s.name AS supplier_name
        FROM purchase_verifications v
        LEFT JOIN suppliers s ON s.id = v.supplier_id
        WHERE v.id = ?
    """
    with _connect() as conn:
        row = conn.execute(sql, (int(verification_id),)).fetchone()
        if not row:
            return {"ok": False, "error": "Verification not found"}
        allocs = conn.execute(
            """
            SELECT a.expense_id, a.amount AS allocated_amount
            FROM purchase_verification_allocations a
            WHERE a.purchase_verification_id = ?
            ORDER BY a.id ASC
            """,
            (int(verification_id),),
        ).fetchall()
        expenses: list[dict[str, Any]] = []
        for alloc in allocs:
            detail = expense_stock_detail(conn, int(alloc["expense_id"]))
            if detail:
                detail["allocated_amount"] = _money(alloc["allocated_amount"])
                expenses.append(detail)
            else:
                expenses.append(
                    {
                        "ok": False,
                        "allocated_amount": _money(alloc["allocated_amount"]),
                        "expense": {"id": int(alloc["expense_id"])},
                        "lines": [],
                        "source": "none",
                        "stock_mode": "Purchase",
                    }
                )
    return {
        "ok": True,
        "flask_base": FLASK_BASE,
        "verification": {
            "id": int(row["id"]),
            "payment_date": str(row["payment_date"] or ""),
            "total_amount": _money(row["total_amount"]),
            "verification_account": str(row["verification_account"] or ""),
            "notes": str(row["notes"] or ""),
            "supplier_id": int(row["supplier_id"] or 0),
            "supplier_name": str(row["supplier_name"] or ""),
        },
        "expenses": expenses,
    }


def _indian_fy_start(today: Optional[Any] = None):
    from datetime import date as _date

    today = today or _date.today()
    year = today.year if today.month >= 4 else today.year - 1
    return _date(year, 4, 1)


def _parse_iso_date(value: object):
    from datetime import date as _date

    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return _date.fromisoformat(raw[:10])
    except ValueError:
        return None


def fetch_purchase_ledger(
    kind: str = "all",
    limit: int = 0,
    date_from: str = "",
    date_to: str = "",
    *,
    default_fy: bool = True,
) -> dict[str, Any]:
    """Hotel purchase & expense ledger rows + totals (same source as web ledger)."""
    from datetime import date as _date

    kind_key = (kind or "all").strip().lower()
    if kind_key not in {"all", "purchase", "expense"}:
        kind_key = "all"

    today = _date.today()
    parsed_from = _parse_iso_date(date_from)
    parsed_to = _parse_iso_date(date_to)
    date_filter_active = bool(parsed_from or parsed_to)
    if not date_filter_active and default_fy:
        parsed_from = _indian_fy_start(today)
        parsed_to = today
        date_filter_active = True
    if parsed_from and parsed_to and parsed_from > parsed_to:
        parsed_from, parsed_to = parsed_to, parsed_from
    if date_filter_active:
        if not parsed_from:
            parsed_from = _date(2000, 1, 1)
        if not parsed_to:
            parsed_to = today

    sql = """
        SELECT e.id, e.expense_code, e.sales_date, e.description, e.amount,
               e.payment_type, e.category, e.invoice_number, e.supplier_id, e.entry_kind,
               s.name AS supplier_name,
               COALESCE((
                   SELECT SUM(a.amount) FROM credit_payment_allocations a
                   WHERE a.expense_id = e.id
               ), 0) AS paid_amount
        FROM sales_update_expenses e
        LEFT JOIN suppliers s ON s.id = e.supplier_id
        WHERE e.location = ?
    """
    params: list[Any] = [OUTLET_HOTEL]
    if date_filter_active and parsed_from and parsed_to:
        sql += " AND e.sales_date >= ? AND e.sales_date <= ?"
        params.extend([parsed_from.isoformat(), parsed_to.isoformat()])
    sql += " ORDER BY e.sales_date DESC, e.created_at DESC, e.id DESC"

    rows_out: list[dict[str, Any]] = []
    with _connect() as conn:
        for row in conn.execute(sql, params):
            raw_kind = str(row["entry_kind"] or "").strip().lower()
            entry_kind = "purchase" if raw_kind == "purchase" else "expense"
            if kind_key == "purchase" and entry_kind != "purchase":
                continue
            if kind_key == "expense" and entry_kind != "expense":
                continue
            amount = _money(row["amount"])
            paid = _money(row["paid_amount"])
            payment = str(row["payment_type"] or "").strip().lower()
            if payment in ("credit", "room credit", "room_credit"):
                payment = "credit"
            balance = round(max(amount - paid, 0.0), 2)
            if payment == "credit":
                if paid <= 0:
                    settlement = "outstanding"
                elif paid + 0.001 < amount:
                    settlement = "partial"
                else:
                    settlement = "cleared"
            else:
                settlement = "cleared"
                balance = 0.0
            rows_out.append(
                {
                    "id": int(row["id"]),
                    "expense_code": str(row["expense_code"] or ""),
                    "sales_date": str(row["sales_date"] or ""),
                    "description": str(row["description"] or ""),
                    "amount": amount,
                    "paid_amount": paid,
                    "balance": balance,
                    "payment_type": payment or "cash",
                    "display_payment_type": payment or "cash",
                    "category": str(row["category"] or ""),
                    "invoice_number": str(row["invoice_number"] or ""),
                    "supplier_id": int(row["supplier_id"] or 0),
                    "supplier_name": str(row["supplier_name"] or ""),
                    "entry_kind": entry_kind,
                    "settlement_status": settlement,
                }
            )

    purchase_rows = [r for r in rows_out if r["entry_kind"] == "purchase"]
    expense_rows = [r for r in rows_out if r["entry_kind"] != "purchase"]
    outstanding_rows = [r for r in rows_out if r["settlement_status"] in ("outstanding", "partial")]
    cleared_rows = [r for r in rows_out if r["settlement_status"] == "cleared"]
    totals = {
        "purchase_total": round(sum(r["amount"] for r in purchase_rows), 2),
        "purchase_count": len(purchase_rows),
        "expense_total": round(sum(r["amount"] for r in expense_rows), 2),
        "expense_count": len(expense_rows),
        "outstanding_total": round(sum(r["balance"] for r in outstanding_rows), 2),
        "outstanding_count": len(outstanding_rows),
        "cleared_total": round(sum(r["amount"] for r in cleared_rows), 2),
        "cleared_count": len(cleared_rows),
        "grand_total": round(sum(r["amount"] for r in rows_out), 2),
        "entry_count": len(rows_out),
    }
    rows = rows_out if limit <= 0 else rows_out[:limit]
    return {
        "ok": True,
        "kind": kind_key,
        "source": "local-db",
        "flask_base": FLASK_BASE,
        "date_from": parsed_from.isoformat() if parsed_from and date_filter_active else "",
        "date_to": parsed_to.isoformat() if parsed_to and date_filter_active else "",
        "date_filter_active": bool(date_filter_active),
        "totals": totals,
        "total": len(rows_out),
        "rows": rows,
    }


def fetch_cash_ledger(
    location: str = "All",
    date_from: str = "",
    date_to: str = "",
    *,
    default_fy: bool = True,
) -> dict[str, Any]:
    """Hotel cash ledger rows + totals (same builders as web Cash Ledger)."""
    from datetime import date as _date

    from app import (
        CASH_LEDGER_ENTRY_LABELS,
        CASH_LEDGER_FILTER_ALL,
        CASH_LEDGER_FILTER_LOCATIONS,
        DEFAULT_COMPANY,
        _build_cash_ledger_entries,
        _cash_ledger_totals,
        _normalize_cash_ledger_location,
    )

    selected_location = _normalize_cash_ledger_location(location)
    today = _date.today()
    parsed_from = _parse_iso_date(date_from)
    parsed_to = _parse_iso_date(date_to)
    date_filter_active = bool(parsed_from or parsed_to)
    if not date_filter_active and default_fy:
        parsed_from = _indian_fy_start(today)
        parsed_to = today
        date_filter_active = True
    if parsed_from and parsed_to and parsed_from > parsed_to:
        parsed_from, parsed_to = parsed_to, parsed_from
    if date_filter_active:
        if not parsed_from:
            parsed_from = _date(2000, 1, 1)
        if not parsed_to:
            parsed_to = today

    with _connect() as conn:
        entries = _build_cash_ledger_entries(
            conn,
            DEFAULT_COMPANY,
            parsed_from if date_filter_active else None,
            parsed_to if date_filter_active else None,
            location=selected_location,
        )
    totals = _cash_ledger_totals(entries)
    display = list(reversed(entries))
    rows = []
    for entry in display:
        kind = str(entry.get("entry_type") or "")
        rows.append(
            {
                "id": entry.get("id") or "",
                "source_id": entry.get("source_id"),
                "entry_type": kind,
                "entry_label": CASH_LEDGER_ENTRY_LABELS.get(kind, kind.replace("_", " ").title()),
                "entry_date": str(entry.get("entry_date") or ""),
                "location": str(entry.get("location") or ""),
                "detail": str(entry.get("detail") or ""),
                "expense_code": str(entry.get("expense_code") or ""),
                "description": str(entry.get("description") or ""),
                "amount": float(entry.get("amount") or 0),
                "signed_amount": float(entry.get("signed_amount") or 0),
                "running_balance": float(entry.get("running_balance") or 0),
                "supplier_name": str(entry.get("supplier_name") or ""),
            }
        )
    return {
        "ok": True,
        "source": "local-db",
        "flask_base": FLASK_BASE,
        "location": selected_location,
        "locations": list(CASH_LEDGER_FILTER_LOCATIONS),
        "date_from": parsed_from.isoformat() if parsed_from and date_filter_active else "",
        "date_to": parsed_to.isoformat() if parsed_to and date_filter_active else "",
        "date_filter_active": bool(date_filter_active),
        "totals": totals,
        "total": len(rows),
        "rows": rows,
        "filter_all": CASH_LEDGER_FILTER_ALL,
    }



def fetch_store_stock(outlet: str = "both", place: str = "warehouse") -> dict[str, Any]:
    """Current on-hand stock (same logic as web /stores/stock report)."""
    from db import ensure_stores_schema
    from stores import (
        STOCK_REPORT_LOW_THRESHOLD,
        _load_stock_report_items,
        _outlet_label,
        _parse_outlet_filter,
        _parse_stock_place,
        _stock_item_status,
        _stock_place_label,
    )

    outlet_key = _parse_outlet_filter(outlet)
    place_key = _parse_stock_place(place)
    with _connect() as conn:
        ensure_stores_schema(conn)
        raw_items = _load_stock_report_items(conn, outlet_key, place=place_key)

    items: list[dict[str, Any]] = []
    available_qty = 0.0
    low = 0
    out = 0
    value_sum = 0.0
    has_value = False
    for item in raw_items:
        try:
            qty = float(item.get("qty_on_hand") or 0)
        except (TypeError, ValueError):
            qty = 0.0
        status_key, status_label = _stock_item_status(qty)
        available_qty += qty
        if status_key == "low":
            low += 1
        elif status_key == "out":
            out += 1
        line_value = item.get("value")
        if line_value is not None:
            try:
                value_sum += float(line_value)
                has_value = True
            except (TypeError, ValueError):
                pass
        items.append(
            {
                "item_name": item.get("item_name") or "",
                "category_name": item.get("category_name") or "",
                "qty_on_hand": item.get("qty_on_hand") if item.get("qty_on_hand") is not None else qty,
                "unit": item.get("unit") or "",
                "status": status_label,
                "status_key": status_key,
                "unit_price": item.get("unit_price"),
                "value": item.get("value"),
                "outlet": item.get("outlet") or "",
                "outlet_label": item.get("outlet_label") or _outlet_label(item.get("outlet") or outlet_key),
                "place": item.get("place") or place_key,
                "place_label": item.get("place_label") or _stock_place_label(item.get("place") or place_key),
            }
        )

    low_threshold: float | int = STOCK_REPORT_LOW_THRESHOLD
    if float(low_threshold) == int(low_threshold):
        low_threshold = int(low_threshold)
    return {
        "ok": True,
        "source": "local-db",
        "flask_base": FLASK_BASE,
        "outlet": outlet_key,
        "place": place_key,
        "outlet_label": _outlet_label(outlet_key),
        "place_label": _stock_place_label(place_key),
        "low_threshold": low_threshold,
        "kpis": {
            "items": len(items),
            "available_qty": round(available_qty, 3),
            "low": low,
            "out": out,
            "value": round(value_sum, 2) if has_value else None,
        },
        "items": items,
    }



def _preview_audit_user() -> dict[str, Any]:
    """Signed-in preview user for stock-audit writes (started_by / verified_by)."""
    user_id = _effective_preview_user_id()
    user = _load_user_by_id(user_id)
    if user:
        return user
    return {"id": user_id}


def fetch_stock_audit(outlet: str = "both", place: str = "warehouse") -> dict[str, Any]:
    """Open (or create) stock audit for outlet+place — same as web /stores/stock-audit."""
    from db import ensure_stores_schema
    from stores import (
        STOCK_AUDIT_REASONS_NEGATIVE,
        STOCK_AUDIT_REASONS_POSITIVE,
        _audit_concrete_outlet,
        _audit_kpis,
        _audit_refresh_line_statuses,
        _get_or_create_open_audit,
        _last_purchase_dates,
        _load_audit_lines,
        _outlet_label,
        _parse_outlet_filter,
        _parse_stock_place,
        _seed_audit_lines,
        _serialize_audit_line,
        _stock_place_label,
        _sync_audit_lines_from_stock,
        stock_audit_history_payload,
    )

    filter_outlet = _parse_outlet_filter(outlet)
    outlet_key = _audit_concrete_outlet(filter_outlet)
    place_key = _parse_stock_place(place)
    user = _preview_audit_user()
    user_id = user.get("id")

    with _connect() as conn:
        ensure_stores_schema(conn)
        audit = _get_or_create_open_audit(conn, outlet_key, user_id, place_key)
        changed = False
        if _audit_refresh_line_statuses(conn, int(audit["id"]), outlet_key, place_key):
            changed = True
        if _sync_audit_lines_from_stock(conn, int(audit["id"]), outlet_key, place_key):
            changed = True
        if changed:
            conn.commit()
        lines = _load_audit_lines(conn, audit["id"])
        if not lines:
            _seed_audit_lines(conn, audit["id"], outlet_key, place_key)
            conn.commit()
            lines = _load_audit_lines(conn, audit["id"])
        purchases = _last_purchase_dates(conn, outlet_key, lines)
        stock_meta = {
            int(row["id"]): row["updated_at"]
            for row in conn.execute(
                "SELECT id, updated_at FROM store_stock_items WHERE outlet = ? AND place = ?",
                (outlet_key, place_key),
            ).fetchall()
            if row["id"] is not None
        }
        for line in lines:
            name_key = (line.get("item_name") or "").strip().lower()
            unit_key = (line.get("unit") or "").strip().lower()
            line["last_purchase_at"] = purchases.get((name_key, unit_key), "") or ""
            sid = line.get("stock_item_id")
            try:
                sid_i = int(sid) if sid is not None else None
            except (TypeError, ValueError):
                sid_i = None
            line["stock_updated_at"] = stock_meta.get(sid_i, "") if sid_i else ""
        kpis = _audit_kpis(lines)
        history_payload = stock_audit_history_payload(conn, outlet_key, place_key, limit=20)

    categories = sorted(
        {
            ((line.get("category_name") or "").strip() or "Uncategorised")
            for line in lines
        },
        key=lambda name: name.lower(),
    )
    return {
        "ok": True,
        "source": "local-db",
        "flask_base": FLASK_BASE,
        "outlet": outlet_key,
        "place": place_key,
        "outlet_label": _outlet_label(outlet_key),
        "place_label": _stock_place_label(place_key),
        "audit": {
            "id": audit.get("id"),
            "status": audit.get("status") or "open",
            "label": audit.get("label") or "",
            "started_at": audit.get("started_at") or "",
        },
        "kpis": kpis,
        "lines": [_serialize_audit_line(line) for line in lines],
        "reasons_negative": [
            {"key": key, "label": label} for key, label in STOCK_AUDIT_REASONS_NEGATIVE
        ],
        "reasons_positive": [
            {"key": key, "label": label} for key, label in STOCK_AUDIT_REASONS_POSITIVE
        ],
        "categories": categories,
        "history": history_payload.get("history") or [],
    }


def verify_stock_audit(payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    from db import ensure_stores_schema
    from stores import stock_audit_verify_action

    user = _preview_audit_user()
    with _connect() as conn:
        ensure_stores_schema(conn)
        return stock_audit_verify_action(conn, user, payload or {})


def skip_stock_audit(payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    from db import ensure_stores_schema
    from stores import stock_audit_skip_action

    user = _preview_audit_user()
    with _connect() as conn:
        ensure_stores_schema(conn)
        return stock_audit_skip_action(conn, user, payload or {})


def new_stock_audit(payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    from db import ensure_stores_schema
    from stores import stock_audit_new_action

    user = _preview_audit_user()
    with _connect() as conn:
        ensure_stores_schema(conn)
        return stock_audit_new_action(conn, user, payload or {})


def fetch_stock_audit_history(outlet: str = "both", place: str = "warehouse") -> dict[str, Any]:
    from db import ensure_stores_schema
    from stores import (
        _audit_concrete_outlet,
        _parse_outlet_filter,
        _parse_stock_place,
        stock_audit_history_payload,
    )

    outlet_key = _audit_concrete_outlet(_parse_outlet_filter(outlet))
    place_key = _parse_stock_place(place)
    with _connect() as conn:
        ensure_stores_schema(conn)
        return stock_audit_history_payload(conn, outlet_key, place_key, limit=50)


class PreviewHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PREVIEW_DIR), **kwargs)

    def log_message(self, fmt: str, *args) -> None:
        print("[%s] %s" % (self.log_date_time_string(), fmt % args))

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        session = _bind_preview_auth(self)
        if parsed.path in ("/preview-api/session", "/api/session"):
            if not session:
                self._send_json(401, {"ok": False, "error": "Not signed in"})
                return
            self._send_json(200, session)
            return
        if parsed.path in ("/preview-api/approvals", "/api/approvals"):
            denied = _require_preview_access("approvals")
            if denied:
                self._send_json(403, denied)
                return
            self._approvals(parsed.query)
            return
        if parsed.path in ("/preview-api/indents", "/api/indents"):
            denied = _require_preview_access("indent_approvals")
            if denied:
                self._send_json(403, denied)
                return
            self._indents(parsed.query)
            return
        if parsed.path in ("/preview-api/indent-catalog", "/api/indent-catalog"):
            denied = _require_preview_access("indent_request")
            if denied:
                self._send_json(403, denied)
                return
            qs = parse_qs(parsed.query or "")
            outlet = (qs.get("outlet") or ["restaurant"])[0]
            try:
                payload = fetch_indent_catalog(outlet)
                status = 200 if payload.get("ok") else 400
                self._send_json(status, payload)
            except Exception as exc:  # noqa: BLE001
                self._send_json(500, {"ok": False, "error": str(exc), "flask_base": FLASK_BASE})
            return
        if parsed.path in ("/preview-api/purchase-ledger", "/api/purchase-ledger"):
            denied = _require_preview_access("purchase_ledger")
            if denied:
                self._send_json(403, denied)
                return
            qs = parse_qs(parsed.query or "")
            kind = (qs.get("kind") or ["all"])[0]
            date_from = (qs.get("date_from") or [""])[0].strip()
            date_to = (qs.get("date_to") or [""])[0].strip()
            clear_dates = (qs.get("clear") or ["0"])[0].strip().lower() in ("1", "true", "yes")
            try:
                limit = int((qs.get("limit") or ["0"])[0] or 0)
            except ValueError:
                limit = 0
            try:
                payload = fetch_purchase_ledger(
                    kind=kind,
                    limit=limit,
                    date_from="" if clear_dates else date_from,
                    date_to="" if clear_dates else date_to,
                    default_fy=(not clear_dates and not date_from and not date_to),
                )
                self._send_json(200, payload)
            except Exception as exc:  # noqa: BLE001
                self._send_json(500, {"ok": False, "error": str(exc), "flask_base": FLASK_BASE})
            return
        if parsed.path in ("/preview-api/cash-ledger", "/api/cash-ledger"):
            denied = _require_preview_access("cash_ledger")
            if denied:
                self._send_json(403, denied)
                return
            qs = parse_qs(parsed.query or "")
            location = (qs.get("location") or ["All"])[0]
            date_from = (qs.get("date_from") or [""])[0].strip()
            date_to = (qs.get("date_to") or [""])[0].strip()
            clear_dates = (qs.get("clear") or ["0"])[0].strip().lower() in ("1", "true", "yes")
            try:
                payload = fetch_cash_ledger(
                    location=location,
                    date_from="" if clear_dates else date_from,
                    date_to="" if clear_dates else date_to,
                    default_fy=(not clear_dates and not date_from and not date_to),
                )
                self._send_json(200, payload)
            except Exception as exc:  # noqa: BLE001
                self._send_json(500, {"ok": False, "error": str(exc), "flask_base": FLASK_BASE})
            return
        if parsed.path in ("/preview-api/store", "/api/store"):
            denied = _require_preview_access("store")
            if denied:
                self._send_json(403, denied)
                return
            qs = parse_qs(parsed.query or "")
            outlet = (qs.get("outlet") or ["both"])[0]
            place = (qs.get("place") or ["warehouse"])[0]
            try:
                payload = fetch_store_stock(outlet=outlet, place=place)
                self._send_json(200, payload)
            except Exception as exc:  # noqa: BLE001
                self._send_json(500, {"ok": False, "error": str(exc), "flask_base": FLASK_BASE})
            return
        if parsed.path in ("/preview-api/stock-audit/history", "/api/stock-audit/history"):
            denied = _require_preview_access("stock_audit")
            if denied:
                self._send_json(403, denied)
                return
            qs = parse_qs(parsed.query or "")
            outlet = (qs.get("outlet") or ["both"])[0]
            place = (qs.get("place") or ["warehouse"])[0]
            try:
                payload = fetch_stock_audit_history(outlet=outlet, place=place)
                self._send_json(200, payload)
            except Exception as exc:  # noqa: BLE001
                self._send_json(500, {"ok": False, "error": str(exc), "flask_base": FLASK_BASE})
            return
        if parsed.path in ("/preview-api/stock-audit", "/api/stock-audit"):
            denied = _require_preview_access("stock_audit")
            if denied:
                self._send_json(403, denied)
                return
            qs = parse_qs(parsed.query or "")
            outlet = (qs.get("outlet") or ["both"])[0]
            place = (qs.get("place") or ["warehouse"])[0]
            try:
                payload = fetch_stock_audit(outlet=outlet, place=place)
                self._send_json(200, payload)
            except Exception as exc:  # noqa: BLE001
                self._send_json(500, {"ok": False, "error": str(exc), "flask_base": FLASK_BASE})
            return
        expense_prefix = "/preview-api/approvals/expense/"
        api_expense_prefix = "/api/approvals/expense/"
        if parsed.path.startswith(expense_prefix) or parsed.path.startswith(api_expense_prefix):
            denied = _require_preview_access("approvals")
            if denied:
                self._send_json(403, denied)
                return
            raw_id = parsed.path.rsplit("/", 1)[-1]
            try:
                expense_id = int(raw_id)
            except ValueError:
                self._send_json(400, {"ok": False, "error": "Invalid expense id"})
                return
            try:
                payload = fetch_expense_detail(expense_id)
                self._send_json(200 if payload.get("ok") else 404, payload)
            except Exception as exc:  # noqa: BLE001
                self._send_json(500, {"ok": False, "error": str(exc)})
            return
        ver_prefix = "/preview-api/approvals/verification/"
        api_ver_prefix = "/api/approvals/verification/"
        if parsed.path.startswith(ver_prefix) or parsed.path.startswith(api_ver_prefix):
            denied = _require_preview_access("approvals")
            if denied:
                self._send_json(403, denied)
                return
            raw_id = parsed.path.rsplit("/", 1)[-1]
            try:
                verification_id = int(raw_id)
            except ValueError:
                self._send_json(400, {"ok": False, "error": "Invalid verification id"})
                return
            try:
                payload = fetch_verification_detail(verification_id)
                self._send_json(200 if payload.get("ok") else 404, payload)
            except Exception as exc:  # noqa: BLE001
                self._send_json(500, {"ok": False, "error": str(exc)})
            return
        if parsed.path in ("/preview-api/health", "/api/health"):
            self._send_json(200, _flask.health())
            return
        if parsed.path in ("/preview-api/dashboard", "/api/dashboard"):
            denied = _require_preview_access("main_dashboard")
            if denied:
                self._send_json(403, denied)
                return
            qs = parse_qs(parsed.query or "")
            period = (qs.get("period") or ["today"])[0]
            location = (qs.get("location") or ["All"])[0]
            date_from = (qs.get("date_from") or [""])[0]
            date_to = (qs.get("date_to") or [""])[0]
            try:
                payload = fetch_main_dashboard(period, location, date_from, date_to)
                self._send_json(200 if payload.get("ok") else 502, payload)
            except Exception as exc:  # noqa: BLE001
                self._send_json(
                    500,
                    {
                        "ok": False,
                        "error": friendly_flask_error(exc),
                        "flask_base": FLASK_BASE,
                    },
                )
            return
        if parsed.path in ("/preview-api/pos/tables", "/api/pos/tables"):
            qs = parse_qs(parsed.query or "")
            outlet = (qs.get("outlet") or ["restaurant"])[0]
            access_key = "pos_bar" if str(outlet).lower() == "bar" else "pos"
            denied = _require_preview_access(access_key)
            if denied:
                self._send_json(403, denied)
                return
            try:
                payload = fetch_pos_tables(outlet)
                self._send_json(200, payload)
            except Exception as exc:  # noqa: BLE001
                self._send_json(500, {"ok": False, "error": str(exc)})
            return
        if parsed.path in ("/preview-api/pos/menu", "/api/pos/menu"):
            qs = parse_qs(parsed.query or "")
            outlet = (qs.get("outlet") or ["restaurant"])[0]
            access_key = "pos_bar" if str(outlet).lower() == "bar" else "pos"
            denied = _require_preview_access(access_key)
            if denied:
                self._send_json(403, denied)
                return
            try:
                payload = fetch_pos_menu(outlet)
                self._send_json(200 if payload.get("ok") else 502, payload)
            except Exception as exc:  # noqa: BLE001
                self._send_json(500, {"ok": False, "error": str(exc), "items": []})
            return
        if parsed.path in ("/preview-api/pos/invoice-by-table", "/api/pos/invoice-by-table"):
            qs = parse_qs(parsed.query or "")
            table = (qs.get("table") or [""])[0]
            outlet = (qs.get("outlet") or ["restaurant"])[0]
            access_key = "pos_bar" if str(outlet).lower() == "bar" else "pos"
            denied = _require_preview_access(access_key)
            if denied:
                self._send_json(403, denied)
                return
            try:
                payload = fetch_pos_invoice_by_table(table, outlet)
                self._send_json(200 if payload.get("ok") is not False else 404, payload)
            except Exception as exc:  # noqa: BLE001
                self._send_json(500, {"ok": False, "error": str(exc), "invoice": None})
            return
        if parsed.path in ("/preview-api/pos/kot-tokens", "/api/pos/kot-tokens"):
            qs = parse_qs(parsed.query or "")
            outlet = (qs.get("outlet") or ["restaurant"])[0]
            access_key = "kot_bar" if str(outlet).lower() == "bar" else "kot"
            denied = _require_preview_access(access_key)
            if denied:
                self._send_json(403, denied)
                return
            try:
                payload = fetch_pos_kot_tokens(outlet)
                self._send_json(200 if payload.get("ok") is not False else 502, payload)
            except Exception as exc:  # noqa: BLE001
                self._send_json(
                    500,
                    {
                        "ok": False,
                        "error": str(exc),
                        "tables": [],
                        "token_count": 0,
                        "flask_base": FLASK_BASE,
                    },
                )
            return
        if parsed.path in ("/preview-api/notifications", "/api/notifications"):
            try:
                payload = fetch_notifications()
                self._send_json(200, payload)
            except Exception as exc:  # noqa: BLE001
                self._send_json(500, {"ok": False, "error": str(exc), "flask_base": FLASK_BASE})
            return
        if parsed.path == "/stores/api/indent-catalog":
            denied = _require_preview_access("indent_request")
            if denied:
                self._send_json(403, denied)
                return
            route = parsed.path
            if parsed.query:
                route = f"{parsed.path}?{parsed.query}"
            result = _flask_request_inprocess("GET", route)
            if result is None:
                self._send_json(
                    502,
                    {
                        "ok": False,
                        "error": friendly_flask_error("Cannot reach Flask"),
                        "flask_base": FLASK_BASE,
                    },
                )
                return
            status, data = result
            self._send_json(status, data)
            return
        if parsed.path.startswith("/preview-api/payroll/"):
            access_key = _payroll_preview_access_key(parsed.path)
            if not access_key:
                self._send_json(404, {"ok": False, "error": "Not found"})
                return
            denied = _require_preview_access(access_key)
            if denied:
                self._send_json(403, denied)
                return
            status, data = proxy_payroll_mobile("GET", parsed.path, parsed.query or "")
            self._send_json(status, data)
            return
        if parsed.path == "/preview-api/shell/version":
            try:
                import mobile_ota
                payload = mobile_ota.load_shell_manifest()
                if isinstance(payload, dict):
                    self._send_json(200, payload)
                    return
            except Exception:
                pass
            result = _flask_request_inprocess("GET", "/api/mobile/shell/version")
            if result is None:
                self._send_json(502, {"ok": False, "error": "Cannot reach update server"})
                return
            status, data = result
            if not isinstance(data, dict):
                data = {"ok": False, "error": "Invalid response"}
            self._send_json(status, data)
            return
        if parsed.path.startswith("/preview-api/") or parsed.path.startswith("/api/"):
            self._send_json(404, {"ok": False, "error": "Not found"})
            return
        if parsed.path in ("/", ""):
            self.path = "/mobile_ui_preview.html"
        return super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self._send_json(400, {"ok": False, "error": "Invalid JSON body"})
            return
        if not isinstance(payload, dict):
            self._send_json(400, {"ok": False, "error": "JSON object required"})
            return
        if parsed.path in ("/preview-api/login", "/api/login"):
            try:
                status, data = preview_authenticate(
                    str(payload.get("username") or ""),
                    str(payload.get("password") or ""),
                )
                self._send_json(status, data)
            except Exception as exc:  # noqa: BLE001
                self._send_json(500, {"ok": False, "error": str(exc)})
            return
        if parsed.path in ("/preview-api/logout", "/api/logout"):
            token = str(payload.get("token") or "") or _token_from_headers(self)
            self._send_json(200, preview_logout(token))
            return
        _bind_preview_auth(self)
        try:
            if parsed.path in ("/preview-api/approvals/approve", "/api/approvals/approve"):
                denied = _require_preview_access("can_approve")
                if denied:
                    self._send_json(403, denied)
                    return
                status, data = approve_expense(payload)
                self._send_json(status if status else 200, data)
                return
            if parsed.path in ("/preview-api/approvals/revert", "/api/approvals/revert"):
                denied = _require_preview_access("can_approve")
                if denied:
                    self._send_json(403, denied)
                    return
                status, data = revert_verification(payload)
                self._send_json(status if status else 200, data)
                return
            if parsed.path in ("/preview-api/indents/decide", "/api/indents/decide"):
                denied = _require_preview_access("indent_approvals")
                if denied:
                    self._send_json(403, denied)
                    return
                status, data = decide_indent(payload)
                self._send_json(status if status else 200, data)
                return
            if parsed.path in ("/preview-api/indent", "/api/indent"):
                denied = _require_preview_access("indent_request")
                if denied:
                    self._send_json(403, denied)
                    return
                status, data = create_indent_request(payload)
                self._send_json(status if status else 200, data)
                return
            if parsed.path in ("/preview-api/stock-audit/verify", "/api/stock-audit/verify"):
                denied = _require_preview_access("stock_audit")
                if denied:
                    self._send_json(403, denied)
                    return
                status, data = verify_stock_audit(payload)
                self._send_json(status if status else 200, data)
                return
            if parsed.path in ("/preview-api/stock-audit/skip", "/api/stock-audit/skip"):
                denied = _require_preview_access("stock_audit")
                if denied:
                    self._send_json(403, denied)
                    return
                status, data = skip_stock_audit(payload)
                self._send_json(status if status else 200, data)
                return
            if parsed.path in ("/preview-api/stock-audit/new", "/api/stock-audit/new"):
                denied = _require_preview_access("stock_audit")
                if denied:
                    self._send_json(403, denied)
                    return
                status, data = new_stock_audit(payload)
                self._send_json(status if status else 200, data)
                return
            if parsed.path == "/stores/api/indent":
                denied = _require_preview_access("indent_request")
                if denied:
                    self._send_json(403, denied)
                    return
                result = _flask_request_inprocess("POST", parsed.path, payload)
                if result is None:
                    self._send_json(
                        502,
                        {
                            "ok": False,
                            "error": friendly_flask_error("Cannot reach Flask"),
                            "flask_base": FLASK_BASE,
                        },
                    )
                    return
                status, data = result
                self._send_json(status if status else 200, data)
                return
            if parsed.path.startswith("/preview-api/payroll/"):
                access_key = _payroll_preview_access_key(parsed.path)
                if not access_key:
                    self._send_json(404, {"ok": False, "error": "Not found"})
                    return
                denied = _require_preview_access(access_key)
                if denied:
                    self._send_json(403, denied)
                    return
                status, data = proxy_payroll_mobile(
                    "POST", parsed.path, parsed.query or "", payload
                )
                self._send_json(status if status else 200, data)
                return
            if parsed.path in ("/preview-api/pos/invoices", "/api/pos/invoices"):
                outlet = str(payload.get("outlet") or "restaurant")
                access_key = "pos_bar" if outlet.lower() == "bar" else "pos"
                denied = _require_preview_access(access_key)
                if denied:
                    self._send_json(403, denied)
                    return
                status, data = pos_save_invoice(payload, outlet)
                self._send_json(status if status else 200, data)
                return
            if parsed.path in ("/preview-api/pos/send-kot", "/api/pos/send-kot"):
                invoice_id = int(payload.get("invoice_id") or payload.get("id") or 0)
                if invoice_id <= 0:
                    self._send_json(400, {"ok": False, "error": "invoice_id required"})
                    return
                outlet = str(payload.get("outlet") or "restaurant")
                access_key = "pos_bar" if outlet.lower() == "bar" else "pos"
                denied = _require_preview_access(access_key)
                if denied:
                    self._send_json(403, denied)
                    return
                status, data = pos_send_kot(invoice_id, outlet)
                self._send_json(status if status else 200, data)
                return
            if parsed.path in (
                "/preview-api/pos/kot-tokens/reduce",
                "/api/pos/kot-tokens/reduce",
            ):
                outlet = str(payload.get("outlet") or "restaurant")
                access_key = "kot_bar" if outlet.lower() == "bar" else "kot"
                denied = _require_preview_access(access_key)
                if denied:
                    self._send_json(403, denied)
                    return
                body = dict(payload)
                body.pop("outlet", None)
                status, data = pos_reduce_kot_tokens(body, outlet)
                self._send_json(status if status else 200, data)
                return
            if parsed.path in ("/preview-api/pos/settle", "/api/pos/settle"):
                invoice_id = int(payload.get("invoice_id") or payload.get("id") or 0)
                if invoice_id <= 0:
                    self._send_json(400, {"ok": False, "error": "invoice_id required"})
                    return
                outlet = str(payload.get("outlet") or "restaurant")
                access_key = "pos_bar" if outlet.lower() == "bar" else "pos"
                denied = _require_preview_access(access_key)
                if denied:
                    self._send_json(403, denied)
                    return
                body = dict(payload)
                body.pop("invoice_id", None)
                body.pop("id", None)
                body.pop("outlet", None)
                status, data = pos_settle_invoice(invoice_id, body or None, outlet)
                self._send_json(status if status else 200, data)
                return
        except Exception as exc:  # noqa: BLE001
            self._send_json(500, {"ok": False, "error": str(exc), "flask_base": FLASK_BASE})
            return
        self._send_json(404, {"ok": False, "error": "Not found"})

    def _approvals(self, query: str) -> None:
        qs = parse_qs(query or "")
        view = (qs.get("view") or ["pending"])[0].strip().lower()
        try:
            limit = int((qs.get("limit") or ["0"])[0])
        except ValueError:
            limit = 0
        try:
            payload = fetch_approved(limit) if view in ("approved", "history") else fetch_pending(limit)
            self._send_json(200, payload)
        except Exception as exc:  # noqa: BLE001
            self._send_json(500, {"ok": False, "error": str(exc)})

    def _indents(self, query: str) -> None:
        qs = parse_qs(query or "")
        view = (qs.get("view") or ["pending"])[0].strip().lower()
        try:
            limit = int((qs.get("limit") or ["0"])[0])
        except ValueError:
            limit = 0
        try:
            if view in ("recent", "approved", "rejected", "history"):
                payload = fetch_indent_recent(limit if limit > 0 else 20)
            else:
                payload = fetch_indent_pending(limit)
            self._send_json(200, payload)
        except Exception as exc:  # noqa: BLE001
            self._send_json(500, {"ok": False, "error": str(exc)})


def main() -> None:
    try:
        assert_preview_safe()
    except PreviewSafetyError as exc:
        raise SystemExit(str(exc)) from exc
    if not DB_PATH.is_file():
        raise SystemExit(f"Database not found: {DB_PATH}")
    server = ThreadingHTTPServer((HOST, PORT), PreviewHandler)
    print(f"Preview + live Approvals + Dashboard on http://{HOST}:{PORT}/")
    print(f"Flask target: {FLASK_BASE}")
    print(f"DB: {DB_PATH}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
