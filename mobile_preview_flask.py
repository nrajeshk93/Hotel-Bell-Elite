"""Mobile preview UI + /preview-api on the main Flask app (production phones)."""

from __future__ import annotations

import importlib.util
import sys
import os
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from flask import Blueprint, jsonify, make_response, request, send_from_directory

from mailer import app_base_url

REPO_ROOT = Path(__file__).resolve().parent
PREVIEW_DIR = REPO_ROOT / "mobile_kivy" / "preview"
bp = Blueprint("mobile_preview", __name__)
_serve = None


def _preview_serve():
    global _serve
    if _serve is not None:
        return _serve
    path = PREVIEW_DIR / "serve.py"
    spec = importlib.util.spec_from_file_location("hbe_mobile_preview_serve", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["hbe_mobile_preview_serve"] = module
    spec.loader.exec_module(module)
    _serve = module
    return module


def _sync_base() -> None:
    ps = _preview_serve()
    ps.FLASK_BASE = app_base_url().rstrip("/")


def _token() -> str:
    auth = (request.headers.get("Authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return (request.headers.get("X-Preview-Token") or "").strip()


def _bind():
    ps = _preview_serve()
    _sync_base()
    session = ps.preview_session_from_token(_token())
    if session:
        ps._set_request_preview_user(int(session["user_id"]), session.get("access") or {})
        try:
            ps._flask.impersonate(int(session["user_id"]))
        except Exception:
            pass
        return session

    user = _flask_session_user()
    if user:
        access = ps.mobile_access_for_user(user)
        uid = int(user["id"])
        ps._set_request_preview_user(uid, access)
        try:
            ps._flask.impersonate(uid)
        except Exception:
            pass
        return {
            "ok": True,
            "user_id": uid,
            "username": str(user.get("username") or ""),
            "display_name": str(user.get("display_name") or user.get("username") or ""),
            "role_name": str(user.get("role_name") or ""),
            "must_change_password": bool(user.get("must_change_password")),
            "access": access,
        }

    ps._set_request_preview_user(None, None)
    return None


def _flask_session_user():
    try:
        from app import get_current_user

        return get_current_user()
    except Exception:
        return None


def preview_authenticate_credentials(username: str, password: str):
    ps = _preview_serve()
    _sync_base()
    return ps.preview_authenticate(username, password)


def _deny(access_key: str):
    _bind()
    return _preview_serve()._require_preview_access(access_key)


def _json(data, status=200):
    return jsonify(data), status


_PREVIEW_CORS_HEADERS = {
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Preview-Token, X-CSRF-Token, X-CSRFToken",
}


def _origin_from_url(url: str) -> str:
    text = (url or "").strip().rstrip("/")
    if not text:
        return ""
    parsed = urlparse(text if "://" in text else "https://" + text)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


def _preview_allowed_origins() -> set[str]:
    """Same-host app + explicit localhost preview ports. Never reflect arbitrary Origins."""
    origins = {
        "https://belleliteaccounts.com",
        "https://www.belleliteaccounts.com",
        "http://127.0.0.1:8002",
        "http://localhost:8002",
        "http://127.0.0.1:8765",
        "http://localhost:8765",
        "http://[::1]:8002",
        "http://[::1]:8765",
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    }
    for env_key in ("APP_BASE_URL", "PREVIEW_CORS_ORIGINS", "MOBILE_PREVIEW_CORS_ORIGINS"):
        raw = os.environ.get(env_key) or ""
        for item in raw.split(","):
            origin = _origin_from_url(item.strip())
            if origin:
                origins.add(origin)
    try:
        base = _origin_from_url(app_base_url())
        if base:
            origins.add(base)
    except Exception:
        pass
    try:
        host_origin = _origin_from_url(request.host_url or "")
        if host_origin:
            origins.add(host_origin)
    except RuntimeError:
        pass
    return origins


def _preview_cors_headers():
    origin = (request.headers.get("Origin") or "").strip().rstrip("/")
    headers = dict(_PREVIEW_CORS_HEADERS)
    if origin and origin in _preview_allowed_origins():
        headers["Access-Control-Allow-Origin"] = origin
        headers["Access-Control-Allow-Credentials"] = "true"
        headers["Vary"] = "Origin"
    return headers


@bp.before_request
def _preview_api_cors_preflight():
    if request.method != "OPTIONS" or not (request.path or "").startswith("/preview-api/"):
        return None
    resp = make_response("", 204)
    resp.headers.update(_preview_cors_headers())
    return resp


@bp.after_request
def _preview_api_cors(response):
    if (request.path or "").startswith("/preview-api/") or (request.path or "").startswith("/api/mobile/"):
        for key, value in _preview_cors_headers().items():
            response.headers[key] = value
    return response


@bp.route("/mobile-app/")
@bp.route("/mobile-app/<path:filename>")
def mobile_app_files(filename="mobile_ui_preview.html"):
    name = "mobile_ui_preview.html" if not filename or filename.endswith("/") else Path(filename).name
    if name != filename or ".." in filename:
        return _json({"ok": False, "error": "Not found"}, 404)
    return send_from_directory(PREVIEW_DIR, name)


@bp.route("/preview-api/session", methods=["GET"])
def preview_session_route():
    _sync_base()
    session = _bind()
    if not session:
        return _json({"ok": False, "error": "Not signed in"}, 401)
    return _json(session)


@bp.route("/preview-api/login", methods=["POST"])
def preview_login_route():
    ps = _preview_serve()
    _sync_base()
    payload = request.get_json(silent=True) or {}
    status, data = ps.preview_authenticate(
        str(payload.get("username") or ""),
        str(payload.get("password") or ""),
    )
    return _json(data, status)


@bp.route("/preview-api/logout", methods=["POST"])
def preview_logout_route():
    ps = _preview_serve()
    payload = request.get_json(silent=True) or {}
    token = str(payload.get("token") or "") or _token()
    return _json(ps.preview_logout(token))


@bp.route("/preview-api/health", methods=["GET"])
def preview_health_route():
    ps = _preview_serve()
    _sync_base()
    version = getattr(ps, "MOBILE_PREVIEW_API_VERSION", "unknown")
    return _json(
        {
            "ok": True,
            "flask_base": app_base_url().rstrip("/"),
            "api_version": version,
            "approvals_mode": "direct_db",
        }
    )


@bp.route("/preview-api/approvals", methods=["GET"])
def preview_approvals_route():
    denied = _deny("approvals")
    if denied:
        return _json(denied, 403)
    ps = _preview_serve()
    qs = parse_qs(request.query_string.decode("utf-8"))
    view = (qs.get("view") or ["pending"])[0].strip().lower()
    try:
        limit = int((qs.get("limit") or ["0"])[0])
    except ValueError:
        limit = 0
    try:
        payload = ps.fetch_approved(limit) if view in ("approved", "history") else ps.fetch_pending(limit)
        return _json(payload)
    except Exception as exc:  # noqa: BLE001
        return _json({"ok": False, "error": str(exc)}, 500)


@bp.route("/preview-api/indents", methods=["GET"])
def preview_indents_route():
    denied = _deny("indent_approvals")
    if denied:
        return _json(denied, 403)
    ps = _preview_serve()
    qs = parse_qs(request.query_string.decode("utf-8"))
    view = (qs.get("view") or ["pending"])[0].strip().lower()
    try:
        limit = int((qs.get("limit") or ["0"])[0])
    except ValueError:
        limit = 0
    try:
        if view in ("recent", "approved", "rejected", "history"):
            payload = ps.fetch_indent_recent(limit if limit > 0 else 20)
        else:
            payload = ps.fetch_indent_pending(limit)
        return _json(payload)
    except Exception as exc:  # noqa: BLE001
        return _json({"ok": False, "error": str(exc)}, 500)


@bp.route("/preview-api/notifications", methods=["GET"])
def preview_notifications_route():
    ps = _preview_serve()
    _bind()
    try:
        return _json(ps.fetch_notifications())
    except Exception as exc:  # noqa: BLE001
        return _json({"ok": False, "error": str(exc)}, 500)


@bp.route("/preview-api/dashboard", methods=["GET"])
def preview_dashboard_route():
    denied = _deny("main_dashboard")
    if denied:
        return _json(denied, 403)
    ps = _preview_serve()
    qs = parse_qs(request.query_string.decode("utf-8"))
    period = (qs.get("period") or ["today"])[0]
    location = (qs.get("location") or ["All"])[0]
    date_from = (qs.get("date_from") or [""])[0].strip()
    date_to = (qs.get("date_to") or [""])[0].strip()
    try:
        return _json(
            ps.fetch_main_dashboard(
                period=period,
                location=location,
                date_from=date_from,
                date_to=date_to,
            )
        )
    except Exception as exc:  # noqa: BLE001
        return _json({"ok": False, "error": str(exc)}, 500)


@bp.route("/preview-api/purchase-ledger", methods=["GET"])
def preview_purchase_ledger_route():
    denied = _deny("purchase_ledger")
    if denied:
        return _json(denied, 403)
    ps = _preview_serve()
    qs = parse_qs(request.query_string.decode("utf-8"))
    kind = (qs.get("kind") or ["all"])[0]
    date_from = (qs.get("date_from") or [""])[0].strip()
    date_to = (qs.get("date_to") or [""])[0].strip()
    clear_dates = (qs.get("clear") or ["0"])[0].strip().lower() in ("1", "true", "yes")
    try:
        limit = int((qs.get("limit") or ["0"])[0] or 0)
    except ValueError:
        limit = 0
    try:
        payload = ps.fetch_purchase_ledger(
            kind=kind,
            limit=limit,
            date_from="" if clear_dates else date_from,
            date_to="" if clear_dates else date_to,
            default_fy=(not clear_dates and not date_from and not date_to),
        )
        return _json(payload)
    except Exception as exc:  # noqa: BLE001
        return _json({"ok": False, "error": str(exc), "flask_base": ps.FLASK_BASE}, 500)



@bp.route("/preview-api/store", methods=["GET"])
def preview_store_route():
    denied = _deny("store")
    if denied:
        return _json(denied, 403)
    ps = _preview_serve()
    qs = parse_qs(request.query_string.decode("utf-8"))
    outlet = (qs.get("outlet") or ["both"])[0]
    place = (qs.get("place") or ["warehouse"])[0]
    try:
        payload = ps.fetch_store_stock(outlet=outlet, place=place)
        return _json(payload)
    except Exception as exc:  # noqa: BLE001
        return _json({"ok": False, "error": str(exc), "flask_base": ps.FLASK_BASE}, 500)


@bp.route("/preview-api/stock-audit", methods=["GET"])
def preview_stock_audit_route():
    denied = _deny("stock_audit")
    if denied:
        return _json(denied, 403)
    ps = _preview_serve()
    qs = parse_qs(request.query_string.decode("utf-8"))
    outlet = (qs.get("outlet") or ["both"])[0]
    place = (qs.get("place") or ["warehouse"])[0]
    try:
        payload = ps.fetch_stock_audit(outlet=outlet, place=place)
        return _json(payload)
    except Exception as exc:  # noqa: BLE001
        return _json({"ok": False, "error": str(exc), "flask_base": ps.FLASK_BASE}, 500)


@bp.route("/preview-api/stock-audit/history", methods=["GET"])
def preview_stock_audit_history_route():
    denied = _deny("stock_audit")
    if denied:
        return _json(denied, 403)
    ps = _preview_serve()
    qs = parse_qs(request.query_string.decode("utf-8"))
    outlet = (qs.get("outlet") or ["both"])[0]
    place = (qs.get("place") or ["warehouse"])[0]
    try:
        payload = ps.fetch_stock_audit_history(outlet=outlet, place=place)
        return _json(payload)
    except Exception as exc:  # noqa: BLE001
        return _json({"ok": False, "error": str(exc), "flask_base": ps.FLASK_BASE}, 500)


@bp.route("/preview-api/stock-audit/verify", methods=["POST"])
def preview_stock_audit_verify_route():
    denied = _deny("stock_audit")
    if denied:
        return _json(denied, 403)
    ps = _preview_serve()
    payload = request.get_json(silent=True) or {}
    try:
        status, data = ps.verify_stock_audit(payload)
        return _json(data, status or 200)
    except Exception as exc:  # noqa: BLE001
        return _json({"ok": False, "error": str(exc)}, 500)


@bp.route("/preview-api/stock-audit/skip", methods=["POST"])
def preview_stock_audit_skip_route():
    denied = _deny("stock_audit")
    if denied:
        return _json(denied, 403)
    ps = _preview_serve()
    payload = request.get_json(silent=True) or {}
    try:
        status, data = ps.skip_stock_audit(payload)
        return _json(data, status or 200)
    except Exception as exc:  # noqa: BLE001
        return _json({"ok": False, "error": str(exc)}, 500)


@bp.route("/preview-api/stock-audit/new", methods=["POST"])
def preview_stock_audit_new_route():
    denied = _deny("stock_audit")
    if denied:
        return _json(denied, 403)
    ps = _preview_serve()
    payload = request.get_json(silent=True) or {}
    try:
        status, data = ps.new_stock_audit(payload)
        return _json(data, status or 200)
    except Exception as exc:  # noqa: BLE001
        return _json({"ok": False, "error": str(exc)}, 500)


@bp.route("/preview-api/cash-ledger", methods=["GET"])
def preview_cash_ledger_route():
    denied = _deny("cash_ledger")
    if denied:
        return _json(denied, 403)
    ps = _preview_serve()
    qs = parse_qs(request.query_string.decode("utf-8"))
    location = (qs.get("location") or ["All"])[0]
    date_from = (qs.get("date_from") or [""])[0].strip()
    date_to = (qs.get("date_to") or [""])[0].strip()
    clear_dates = (qs.get("clear") or ["0"])[0].strip().lower() in ("1", "true", "yes")
    try:
        payload = ps.fetch_cash_ledger(
            location=location,
            date_from="" if clear_dates else date_from,
            date_to="" if clear_dates else date_to,
            default_fy=(not clear_dates and not date_from and not date_to),
        )
        return _json(payload)
    except Exception as exc:  # noqa: BLE001
        return _json({"ok": False, "error": str(exc), "flask_base": ps.FLASK_BASE}, 500)


@bp.route("/preview-api/approvals/expense/<int:expense_id>", methods=["GET"])
def preview_expense_detail_route(expense_id: int):
    denied = _deny("approvals")
    if denied:
        return _json(denied, 403)
    ps = _preview_serve()
    try:
        payload = ps.fetch_expense_detail(expense_id)
        return _json(payload, 200 if payload.get("ok") else 404)
    except Exception as exc:  # noqa: BLE001
        return _json({"ok": False, "error": str(exc)}, 500)


@bp.route("/preview-api/approvals/verification/<int:verification_id>", methods=["GET"])
def preview_verification_detail_route(verification_id: int):
    denied = _deny("approvals")
    if denied:
        return _json(denied, 403)
    ps = _preview_serve()
    try:
        payload = ps.fetch_verification_detail(verification_id)
        return _json(payload, 200 if payload.get("ok") else 404)
    except Exception as exc:  # noqa: BLE001
        return _json({"ok": False, "error": str(exc)}, 500)


@bp.route("/preview-api/pos/tables", methods=["GET"])
def preview_pos_tables_route():
    denied = _deny("pos")
    if denied:
        return _json(denied, 403)
    ps = _preview_serve()
    outlet = (request.args.get("outlet") or "restaurant").strip()
    try:
        return _json(ps.fetch_pos_tables(outlet=outlet))
    except Exception as exc:  # noqa: BLE001
        return _json({"ok": False, "error": str(exc)}, 500)


@bp.route("/preview-api/pos/menu", methods=["GET"])
def preview_pos_menu_route():
    ps = _preview_serve()
    outlet = (request.args.get("outlet") or "restaurant").strip()
    access_key = "pos_bar" if outlet.lower() == "bar" else "pos"
    denied = _deny(access_key)
    if denied:
        return _json(denied, 403)
    try:
        return _json(ps.fetch_pos_menu(outlet=outlet))
    except Exception as exc:  # noqa: BLE001
        return _json({"ok": False, "error": str(exc)}, 500)


@bp.route("/preview-api/pos/invoice-by-table", methods=["GET"])
def preview_pos_invoice_by_table_route():
    ps = _preview_serve()
    outlet = (request.args.get("outlet") or "restaurant").strip()
    access_key = "pos_bar" if outlet.lower() == "bar" else "pos"
    denied = _deny(access_key)
    if denied:
        return _json(denied, 403)
    table = (request.args.get("table") or request.args.get("table_id") or "").strip()
    try:
        payload = ps.fetch_pos_invoice_by_table(table, outlet=outlet)
        return _json(payload, 200 if payload.get("ok") is not False else 404)
    except Exception as exc:  # noqa: BLE001
        return _json({"ok": False, "error": str(exc)}, 500)


@bp.route("/preview-api/pos/kot-tokens", methods=["GET"])
def preview_pos_kot_tokens_route():
    ps = _preview_serve()
    outlet = (request.args.get("outlet") or "restaurant").strip()
    access_key = "kot_bar" if outlet.lower() == "bar" else "kot"
    denied = _deny(access_key)
    if denied:
        return _json(denied, 403)
    try:
        payload = ps.fetch_pos_kot_tokens(outlet)
        return _json(payload, 200 if payload.get("ok") is not False else 502)
    except Exception as exc:  # noqa: BLE001
        return _json({"ok": False, "error": str(exc)}, 500)


@bp.route("/preview-api/approvals/approve", methods=["POST"])
def preview_approve_route():
    denied = _deny("can_approve")
    if denied:
        return _json(denied, 403)
    ps = _preview_serve()
    payload = request.get_json(silent=True) or {}
    try:
        status, data = ps.approve_expense(payload)
        return _json(data, status or 200)
    except Exception as exc:  # noqa: BLE001
        return _json({"ok": False, "error": str(exc)}, 500)


@bp.route("/preview-api/approvals/revert", methods=["POST"])
def preview_revert_route():
    denied = _deny("can_approve")
    if denied:
        return _json(denied, 403)
    ps = _preview_serve()
    payload = request.get_json(silent=True) or {}
    try:
        status, data = ps.revert_verification(payload)
        return _json(data, status or 200)
    except Exception as exc:  # noqa: BLE001
        return _json({"ok": False, "error": str(exc)}, 500)


@bp.route("/preview-api/indents/decide", methods=["POST"])
def preview_indent_decide_route():
    denied = _deny("indent_approvals")
    if denied:
        return _json(denied, 403)
    ps = _preview_serve()
    payload = request.get_json(silent=True) or {}
    status, data = ps.decide_indent(payload)
    return _json(data, status or 200)


@bp.route("/preview-api/pos/invoices", methods=["POST"])
def preview_pos_invoices_route():
    ps = _preview_serve()
    payload = request.get_json(silent=True) or {}
    outlet = str(payload.get("outlet") or "restaurant")
    access_key = "pos_bar" if outlet.lower() == "bar" else "pos"
    denied = _deny(access_key)
    if denied:
        return _json(denied, 403)
    status, data = ps.pos_save_invoice(payload, outlet)
    return _json(data, status or 200)


@bp.route("/preview-api/pos/send-kot", methods=["POST"])
def preview_pos_send_kot_route():
    ps = _preview_serve()
    payload = request.get_json(silent=True) or {}
    invoice_id = int(payload.get("invoice_id") or payload.get("id") or 0)
    if invoice_id <= 0:
        return _json({"ok": False, "error": "invoice_id required"}, 400)
    outlet = str(payload.get("outlet") or "restaurant")
    access_key = "pos_bar" if outlet.lower() == "bar" else "pos"
    denied = _deny(access_key)
    if denied:
        return _json(denied, 403)
    status, data = ps.pos_send_kot(invoice_id, outlet)
    return _json(data, status or 200)


@bp.route("/preview-api/pos/kot-tokens/reduce", methods=["POST"])
def preview_pos_kot_reduce_route():
    ps = _preview_serve()
    payload = dict(request.get_json(silent=True) or {})
    outlet = str(payload.pop("outlet", None) or "restaurant")
    access_key = "kot_bar" if outlet.lower() == "bar" else "kot"
    denied = _deny(access_key)
    if denied:
        return _json(denied, 403)
    status, data = ps.pos_reduce_kot_tokens(payload, outlet)
    return _json(data, status or 200)


@bp.route("/preview-api/pos/settle", methods=["POST"])
def preview_pos_settle_route():
    ps = _preview_serve()
    payload = dict(request.get_json(silent=True) or {})
    invoice_id = int(payload.pop("invoice_id", None) or payload.pop("id", None) or 0)
    if invoice_id <= 0:
        return _json({"ok": False, "error": "invoice_id required"}, 400)
    outlet = str(payload.pop("outlet", None) or "restaurant")
    access_key = "pos_bar" if outlet.lower() == "bar" else "pos"
    denied = _deny(access_key)
    if denied:
        return _json(denied, 403)
    status, data = ps.pos_settle_invoice(invoice_id, payload or None, outlet)
    return _json(data, status or 200)


@bp.route("/preview-api/print-jobs", methods=["POST"])
def preview_print_jobs_create_route():
    denied = _deny("pos")
    if denied:
        denied = _deny("pos_bar")
    if denied:
        denied = _deny("kot")
    if denied:
        denied = _deny("kot_bar")
    if denied:
        return _json(denied, 403)
    from db import get_db
    from print_job_service import create_print_job

    payload = request.get_json(silent=True) or {}
    conn = get_db()
    try:
        user = _flask_session_user()
        uid = int(user.get("id") or 0) if user else 0
        job = create_print_job(conn, payload, user_id=uid)
        if job.get("error") and not job.get("jobId"):
            return _json(job, 400)
        return _json({"ok": True, "job": job, "duplicate": bool(job.get("duplicate"))})
    finally:
        conn.close()


@bp.route("/preview-api/print-jobs/<job_id>", methods=["GET"])
def preview_print_jobs_get_route(job_id: str):
    denied = _deny("pos")
    if denied:
        denied = _deny("pos_bar")
    if denied:
        denied = _deny("kot")
    if denied:
        denied = _deny("kot_bar")
    if denied:
        return _json(denied, 403)
    from db import get_db
    from print_job_service import get_print_job

    conn = get_db()
    try:
        job = get_print_job(conn, job_id)
        if not job:
            return _json({"ok": False, "error": "Print job not found."}, 404)
        return _json({"ok": True, "job": job})
    finally:
        conn.close()


@bp.route("/preview-api/payroll/<path:subpath>", methods=["GET", "POST"])
def preview_payroll_route(subpath: str):
    """Proxy Employee Payroll mobile JSON through serve.py → /api/mobile/payroll/*."""
    ps = _preview_serve()
    preview_path = f"/preview-api/payroll/{subpath}"
    access_key = ps._payroll_preview_access_key(preview_path)
    if not access_key:
        return _json({"ok": False, "error": "Not found"}, 404)
    denied = _deny(access_key)
    if denied:
        return _json(denied, 403)
    query = request.query_string.decode("utf-8")
    if request.method == "GET":
        status, data = ps.proxy_payroll_mobile("GET", preview_path, query)
    else:
        payload = request.get_json(silent=True) or {}
        status, data = ps.proxy_payroll_mobile("POST", preview_path, query, payload)
    return _json(data, status or 200)


def register_mobile_preview_routes(app) -> None:
    app.register_blueprint(bp)

    @app.before_request
    def _mobile_api_cors_preflight():
        path = request.path or ""
        if request.method != "OPTIONS" or not path.startswith("/api/mobile/"):
            return None
        resp = make_response("", 204)
        resp.headers.update(_preview_cors_headers())
        return resp

    @app.after_request
    def _mobile_api_cors(response):
        path = request.path or ""
        if path.startswith("/api/mobile/"):
            for key, value in _preview_cors_headers().items():
                response.headers[key] = value
        return response
