"""Central activity audit log — registry, writes, fetch, and after_request hook."""

from __future__ import annotations

import json
import logging
from typing import Any

from flask import g, request

from auth_security import sql_now
from db import get_db
from workspace_access import (
    _ACCESS_MANAGEMENT_ENDPOINTS,
    _ACCOUNTS_ENDPOINTS,
    _COMMUNICATION_HUB_ENDPOINTS,
    _HOTEL_ROOMS_ENDPOINTS,
    _MASTER_ENDPOINTS,
    _PAYROLL_PARENT_ENDPOINTS,
    _POINT_OF_SALE_BAR_ENDPOINTS,
    _POINT_OF_SALE_ENDPOINTS,
    _REPORTS_ENDPOINTS,
    _SALES_ANALYTICS_PARENT_ENDPOINTS,
    _STORES_ENDPOINTS,
)

logger = logging.getLogger(__name__)

ACTIVITY_LOG_PAGE_SIZE = 50
ACTIVITY_LOG_RETENTION_DAYS = 60

ACTIVITY_LOG_ACTIONS = (
    "login",
    "login_failed",
    "logout",
    "create",
    "update",
    "delete",
    "bulk_import",
    "lock",
    "send",
)

ACTIVITY_LOG_MODULES = (
    "auth",
    "user_access",
    "hotel",
    "pos_restaurant",
    "pos_bar",
    "payroll",
    "accounts",
    "stores",
    "master",
    "reports",
    "analytics",
    "comm_hub",
)

ACTIVITY_LOG_ACTION_LABELS = {
    "login": "Login",
    "login_failed": "Login failed",
    "logout": "Logout",
    "create": "Create",
    "update": "Update",
    "delete": "Delete",
    "bulk_import": "Bulk import",
    "lock": "Lock",
    "send": "Send",
}

ACTIVITY_LOG_MODULE_LABELS = {
    "auth": "Auth",
    "user_access": "User & Access",
    "hotel": "Hotel",
    "pos_restaurant": "POS Restaurant",
    "pos_bar": "POS Bar",
    "payroll": "Payroll",
    "accounts": "Accounts",
    "stores": "Stores",
    "master": "Master",
    "reports": "Reports",
    "analytics": "Sales Analytics",
    "comm_hub": "Communication Hub",
}

LOGIN_ACTIVITY_REASON_LABELS = {
    "success": "Successful sign-in",
    "invalid_password": "Wrong password",
    "unknown_user": "Unknown username",
    "locked": "Account locked",
    "captcha": "CAPTCHA failed",
    "throttled": "Too many attempts",
    "no_access_role": "No access role assigned",
}

_ACTIVITY_SKIP_ENDPOINTS = {
    "static",
    "favicon",
    "access_management_logs",
    "access_login_logs",
    "whatsapp_webhook",
    "mobile_ota_manifest",
    "mobile_ota_apk",
    "mobile_shell_ota_manifest",
    "mobile_shell_ota_apk",
    "print_agent_register",
    "print_agent_poll",
    "print_agent_ack",
    "print_agent_jobs",
    "print_agent_health",
    "main_dashboard",
    "home",
    "index",
    "login_get",
    "login_captcha",
    "login_resend_unlock",
    "unlock_account",
    "change_password",
    "license_page",
    "license_api",
}

_ACTIVITY_GET_MUTATIONS = {
    "delete_employee",
    "delete_credit",
    "payroll.delete_employee",
    "payroll.delete_credit",
}

_ACTIVITY_EXPLICIT_ONLY = {
    "login",
    "login_get",
    "logout",
    "mobile_login",
    "delete_access_user",
    "delete_employee",
    "delete_credit",
    "payroll.delete_employee",
    "payroll.delete_credit",
}

_ACTIVITY_ACTION_OVERRIDES = {
    "save_access_user": "update",
    "save_access_role": "update",
    "save_customer": "update",
    "save_agency": "update",
    "save_category_master": "update",
    "save_unit_master": "update",
    "save_supplier": "update",
    "save_sales_update": "update",
    "upload_employees": "bulk_import",
    "upload_report": "bulk_import",
    "upload_sales_report": "bulk_import",
    "upload_hotel_occupancy_report": "bulk_import",
    "lock_payroll_month": "lock",
    "mark_attendance": "update",
    "bulk_attendance": "update",
    "update_salary": "update",
    "send_whatsapp_report": "send",
    "communication_hub_api_promotion_send": "send",
    "stores_orders_send": "send",
    "stores_orders_send_wa": "send",
    "unlock_access_user": "update",
    "toggle_access_user_active": "update",
}


def _infer_activity_action(endpoint: str) -> str:
    bare = normalize_endpoint(endpoint)
    if bare in _ACTIVITY_ACTION_OVERRIDES:
        return _ACTIVITY_ACTION_OVERRIDES[bare]
    if endpoint in _ACTIVITY_ACTION_OVERRIDES:
        return _ACTIVITY_ACTION_OVERRIDES[endpoint]
    if "delete" in bare or "delete" in endpoint:
        return "delete"
    if bare.startswith("add_") or "_add_" in bare or bare.startswith("create_"):
        return "create"
    if bare.startswith("upload_"):
        return "bulk_import"
    if bare.startswith("lock_"):
        return "lock"
    if bare.endswith("_send") or bare.startswith("send_"):
        return "send"
    return "update"


def _infer_entity_type(endpoint: str, default: str) -> str:
    bare = normalize_endpoint(endpoint)
    if "invoice" in bare:
        return "invoice"
    if "menu" in bare:
        return "menu_item"
    if "role" in bare:
        return "role"
    if "user" in bare or "access" in bare:
        return "user"
    if "employee" in bare or bare in {"employees", "add_employee", "edit_employee"}:
        return "employee"
    if "credit" in bare:
        return "credit"
    if "attendance" in bare:
        return "attendance"
    if "indent" in bare or "purchase" in bare:
        return "purchase"
    if "customer" in bare:
        return "customer"
    if "agency" in bare:
        return "agency"
    if "supplier" in bare:
        return "supplier"
    if "reservation" in bare or "room" in bare:
        return "room"
    if "promotion" in bare:
        return "promotion"
    if "conversation" in bare or "message" in bare:
        return "message"
    return default or "record"


def normalize_endpoint(endpoint: str | None) -> str:
    raw = str(endpoint or "").strip()
    if not raw:
        return ""
    if "." in raw:
        prefix, bare = raw.split(".", 1)
        if prefix in {"payroll", "stores"}:
            return bare
    return raw


def _register_group(registry: dict, endpoints: set[str] | frozenset[str], module: str, entity_type: str = "") -> None:
    for endpoint in endpoints:
        if not endpoint or endpoint in _ACTIVITY_SKIP_ENDPOINTS or endpoint in _ACTIVITY_EXPLICIT_ONLY:
            continue
        if endpoint.endswith("_export") or endpoint.startswith("export_"):
            continue
        meta = {
            "action": _infer_activity_action(endpoint),
            "module": module,
            "entity_type": _infer_entity_type(endpoint, entity_type or module),
        }
        registry[endpoint] = meta
        if module == "payroll":
            registry[f"payroll.{endpoint}"] = meta
        if module == "stores" and not endpoint.startswith("stores."):
            registry[f"stores.{endpoint}"] = meta


def build_mutation_registry() -> dict[str, dict[str, str]]:
    registry: dict[str, dict[str, str]] = {}
    _register_group(registry, _ACCESS_MANAGEMENT_ENDPOINTS, "user_access", "user")
    _register_group(registry, _HOTEL_ROOMS_ENDPOINTS, "hotel", "hotel")
    _register_group(registry, _POINT_OF_SALE_ENDPOINTS, "pos_restaurant", "pos")
    _register_group(registry, _POINT_OF_SALE_BAR_ENDPOINTS, "pos_bar", "pos")
    _register_group(registry, _PAYROLL_PARENT_ENDPOINTS, "payroll", "employee")
    _register_group(registry, _ACCOUNTS_ENDPOINTS, "accounts", "accounts")
    _register_group(registry, _STORES_ENDPOINTS, "stores", "stores")
    _register_group(registry, _MASTER_ENDPOINTS, "master", "master")
    _register_group(registry, _REPORTS_ENDPOINTS, "reports", "report")
    _register_group(registry, _SALES_ANALYTICS_PARENT_ENDPOINTS, "analytics", "sales")
    _register_group(registry, _COMMUNICATION_HUB_ENDPOINTS, "comm_hub", "message")
    return registry


MUTATION_REGISTRY = build_mutation_registry()


def client_ip_from_request(req=None) -> str:
    req = req or request
    forwarded = (req.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
    return forwarded or (req.remote_addr or "")


def purge_old_activity_logs(conn, *, days: int = ACTIVITY_LOG_RETENTION_DAYS, commit: bool = False) -> int:
    """Drop activity_log rows older than ``days``. Returns rows deleted."""
    try:
        keep_days = max(1, int(days))
    except (TypeError, ValueError):
        keep_days = ACTIVITY_LOG_RETENTION_DAYS
    cur = conn.execute(
        """
        DELETE FROM activity_log
         WHERE datetime(created_at) < datetime('now', 'localtime', ?)
        """,
        (f"-{keep_days} days",),
    )
    deleted = int(cur.rowcount or 0)
    if commit and deleted:
        conn.commit()
    return deleted


def record_activity_log(
    action: str,
    module: str,
    summary: str,
    *,
    conn=None,
    user_id=None,
    username: str = "",
    entity_type: str = "",
    entity_id=None,
    details=None,
    endpoint: str = "",
    method: str = "",
    path: str = "",
    ip_address: str = "",
    status_code=None,
    commit: bool | None = None,
) -> None:
    own_conn = conn is None
    if own_conn:
        conn = get_db()
        commit = True if commit is None else commit
    elif commit is None:
        commit = False
    try:
        if details is not None and not isinstance(details, str):
            details_json = json.dumps(details, sort_keys=True, default=str)[:4000]
        else:
            details_json = (details or "")[:4000]
        conn.execute(
            """
            INSERT INTO activity_log (
                user_id, username, action, module, entity_type, entity_id,
                summary, details_json, endpoint, method, path, ip_address,
                status_code, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                (username or "")[:120],
                (action or "")[:40],
                (module or "")[:40],
                (entity_type or "")[:40],
                str(entity_id) if entity_id is not None else None,
                (summary or "")[:500],
                details_json,
                (endpoint or "")[:120],
                (method or "")[:12],
                (path or "")[:500],
                (ip_address or "")[:120],
                status_code,
                sql_now(),
            ),
        )
        if commit:
            conn.commit()
        purge_old_activity_logs(conn, commit=commit)
    except Exception:
        logger.exception("Failed to write activity log")
    finally:
        if own_conn:
            try:
                conn.close()
            except Exception:
                pass


def set_activity_audit(summary: str, details: Any = None, entity_id: Any = None) -> None:
    g.audit_summary = (summary or "")[:500]
    if details is not None:
        g.audit_details = details
    if entity_id is not None:
        g.audit_entity_id = entity_id


_ACTIVITY_CODE_KEYS = (
    "expense_code",
    "order_no",
    "pos_order_no",
    "invoice_no",
    "invoice_number",
    "reservation_no",
    "emp_code",
    "employee_code",
    "code",
)
_ACTIVITY_ID_KEYS = (
    "expense_id",
    "invoice_id",
    "emp_id",
    "credit_id",
    "user_id",
    "role_id",
    "item_id",
    "category_id",
    "room_id",
    "payment_id",
    "transfer_id",
    "row_id",
    "pending_bill_id",
    "ticket_id",
    "id",
)


def _request_activity_payload(req=None) -> dict:
    req = req or request
    payload: dict[str, Any] = {}
    if req.view_args:
        payload.update(req.view_args)
    try:
        if req.args:
            payload.update(req.args.to_dict(flat=True))
    except Exception:
        pass
    try:
        if req.form:
            payload.update(req.form.to_dict(flat=True))
    except Exception:
        pass
    try:
        data = req.get_json(silent=True)
    except Exception:
        data = None
    if isinstance(data, dict):
        payload.update(data)
    return payload


def _first_payload_value(payload: dict, keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key not in payload:
            continue
        value = payload.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def activity_entity_id_from_request(req=None) -> Any:
    payload = _request_activity_payload(req)
    return _first_payload_value(payload, _ACTIVITY_CODE_KEYS + _ACTIVITY_ID_KEYS)


def default_activity_summary(endpoint: str, meta: dict[str, str]) -> str:
    action = meta.get("action", "update")
    entity = (meta.get("entity_type") or "record").replace("_", " ")
    entity_id = activity_entity_id_from_request()
    label = normalize_endpoint(endpoint).replace("_", " ") or endpoint.replace("_", " ")
    if entity_id is not None:
        return f"{action.title()} {entity} {entity_id} ({label})"
    return f"{action.title()} {entity} ({label})"


def should_log_request(endpoint: str, method: str) -> bool:
    bare = normalize_endpoint(endpoint)
    keys = [endpoint, bare]
    if endpoint.startswith("payroll."):
        keys.append(endpoint)
    if not any(key in MUTATION_REGISTRY for key in keys if key):
        return False
    if endpoint in _ACTIVITY_GET_MUTATIONS or bare in _ACTIVITY_GET_MUTATIONS:
        return method == "GET"
    return method in {"POST", "PUT", "PATCH", "DELETE"}


def registry_meta_for_endpoint(endpoint: str) -> dict[str, str] | None:
    bare = normalize_endpoint(endpoint)
    return MUTATION_REGISTRY.get(endpoint) or MUTATION_REGISTRY.get(bare)


def record_auth_activity(
    *,
    conn,
    username: str,
    success: bool,
    reason: str = "",
    user_id=None,
    ip_address: str = "",
    user_agent: str = "",
    source: str = "web",
) -> None:
    action = "login" if success else "login_failed"
    reason_key = (reason or "").strip()
    reason_label = LOGIN_ACTIVITY_REASON_LABELS.get(reason_key, reason_key.replace("_", " "))
    if success:
        summary = f"{username} signed in"
    else:
        summary = f"Failed sign-in for {username or 'unknown user'}"
        if reason_label:
            summary = f"{summary} ({reason_label})"
    record_activity_log(
        action,
        "auth",
        summary,
        conn=conn,
        user_id=user_id,
        username=username,
        entity_type="session",
        details={
            "reason": reason_key,
            "reason_label": reason_label,
            "user_agent": (user_agent or "")[:250],
            "source": source,
        },
        endpoint="login",
        method="POST",
        path="/login",
        ip_address=ip_address,
        status_code=200 if success else 401,
        commit=False,
    )


def parse_activity_log_page(raw_page) -> int:
    try:
        return max(1, int(raw_page))
    except (TypeError, ValueError):
        return 1


def fetch_activity_logs(conn, filters: dict, page: int, page_size: int = ACTIVITY_LOG_PAGE_SIZE):
    purge_old_activity_logs(conn, commit=True)
    where = ["1=1"]
    params: list[Any] = []
    date_from = (filters.get("date_from") or "").strip()
    date_to = (filters.get("date_to") or "").strip()
    user_id_raw = (filters.get("user_id") or "").strip()
    action = (filters.get("action") or "").strip()
    module = (filters.get("module") or "").strip()
    search = (filters.get("q") or "").strip()

    if date_from:
        where.append("date(created_at) >= date(?)")
        params.append(date_from)
    if date_to:
        where.append("date(created_at) <= date(?)")
        params.append(date_to)
    if user_id_raw:
        try:
            where.append("user_id = ?")
            params.append(int(user_id_raw))
        except (TypeError, ValueError):
            pass
    if action in ACTIVITY_LOG_ACTIONS:
        where.append("action = ?")
        params.append(action)
    if module in ACTIVITY_LOG_MODULES:
        where.append("module = ?")
        params.append(module)
    if search:
        where.append(
            "(summary LIKE ? OR IFNULL(username, '') LIKE ? OR IFNULL(entity_id, '') LIKE ?)"
        )
        needle = f"%{search}%"
        params.extend([needle, needle, needle])

    where_sql = " AND ".join(where)
    offset = (page - 1) * page_size
    total = int(
        conn.execute(
            f"SELECT COUNT(*) FROM activity_log WHERE {where_sql}",
            tuple(params),
        ).fetchone()[0]
    )
    rows = conn.execute(
        f"""
        SELECT id, user_id, username, action, module, entity_type, entity_id,
               summary, ip_address, created_at
        FROM activity_log
        WHERE {where_sql}
        ORDER BY datetime(created_at) DESC, id DESC
        LIMIT ? OFFSET ?
        """,
        tuple(params) + (page_size, offset),
    ).fetchall()
    user_options = conn.execute(
        """
        SELECT DISTINCT user_id, username
        FROM activity_log
        WHERE user_id IS NOT NULL AND COALESCE(username, '') <> ''
        ORDER BY LOWER(username)
        """
    ).fetchall()
    logs = [dict(row) for row in rows]
    total_pages = max(1, (total + page_size - 1) // page_size)
    return logs, total, total_pages, [dict(row) for row in user_options]


def register_after_request(app, get_current_user_fn) -> None:
    @app.after_request
    def _audit_activity_after_request(response):
        try:
            endpoint = request.endpoint or ""
            if endpoint in _ACTIVITY_EXPLICIT_ONLY:
                return response
            if not should_log_request(endpoint, request.method):
                return response
            if response.status_code >= 400:
                return response
            meta = registry_meta_for_endpoint(endpoint)
            if not meta:
                return response
            user = get_current_user_fn()
            entity_id = getattr(g, "audit_entity_id", None) or activity_entity_id_from_request()
            summary = getattr(g, "audit_summary", None) or default_activity_summary(endpoint, meta)
            if entity_id is not None and str(entity_id) not in (summary or ""):
                summary = f"{summary} {entity_id}".strip()
            details = getattr(g, "audit_details", None)
            record_activity_log(
                meta["action"],
                meta["module"],
                summary,
                user_id=user.get("id") if user else None,
                username=user.get("username") if user else "",
                entity_type=meta.get("entity_type", ""),
                entity_id=entity_id,
                details=details,
                endpoint=endpoint,
                method=request.method,
                path=request.path,
                ip_address=client_ip_from_request(),
                status_code=response.status_code,
            )
        except Exception:
            logger.exception("Activity audit after_request failed")
        return response
