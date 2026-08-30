"""HTTP + WebSocket routes for unified print jobs."""

from __future__ import annotations

from flask import jsonify, request

from print_agent_store import verify_print_agent_bearer
from print_job_service import (
    create_print_job,
    deliver_pending_jobs_for_agent,
    get_print_job,
    job_ws_payload,
    list_pending_jobs,
    recover_stale_print_jobs,
    update_job_status,
)


def _json(data, status=200):
    return jsonify(data), status


def _bearer_token() -> str:
    auth = (request.headers.get("Authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


def _agent_auth(conn) -> tuple[str, dict | None]:
    payload = request.get_json(silent=True) or {}
    agent_id = str(
        payload.get("agentId")
        or payload.get("agent_id")
        or request.args.get("agentId")
        or request.args.get("agent_id")
        or ""
    ).strip()
    token = _bearer_token()
    if not agent_id or not verify_print_agent_bearer(conn, agent_id, token):
        return "", {"ok": False, "error": "Invalid agent credentials."}
    return agent_id, None


def _user_can_create_print_job(user) -> bool:
    if not user:
        return False
    if user.get("is_admin"):
        return True
    try:
        import app as app_module

        if app_module.user_can_access_dashboard(user, "point_of_sale"):
            return True
        if app_module.user_can_access_dashboard(user, "point_of_sale_bar"):
            return True
        if app_module.user_can_access_dashboard(user, "hotel_rooms"):
            return True
    except Exception:
        pass
    return False


def _handle_agent_ws_message(agent_id: str, msg: dict) -> None:
    from db import get_db

    msg_type = str(msg.get("type") or "").strip().lower()
    if msg_type != "job_ack":
        return
    job_id = str(msg.get("jobId") or msg.get("job_id") or "").strip()
    status = str(msg.get("status") or "").upper()
    if not job_id or not status:
        return
    conn = get_db()
    try:
        update_job_status(
            conn,
            job_id,
            status,
            error=str(msg.get("error") or msg.get("message") or "") or None,
            agent_id=agent_id,
        )
    finally:
        conn.close()


def register_print_jobs(app) -> None:
    @app.route("/api/print-jobs", methods=["POST"], endpoint="print_jobs_create")
    def print_jobs_create():
        from app import get_current_user
        from db import get_db

        user = get_current_user()
        if not _user_can_create_print_job(user):
            return _json({"ok": False, "error": "Not authorized."}, 403)
        payload = request.get_json(silent=True) or {}
        conn = get_db()
        try:
            job = create_print_job(conn, payload, user_id=int(user.get("id") or 0))
            if job.get("error") and not job.get("jobId"):
                return _json(job, 400)
            return _json({"ok": True, "job": job, "duplicate": bool(job.get("duplicate"))})
        finally:
            conn.close()

    @app.route("/api/print-jobs/<job_id>", methods=["GET"], endpoint="print_jobs_get")
    def print_jobs_get(job_id: str):
        from app import get_current_user
        from db import get_db

        user = get_current_user()
        if not user:
            return _json({"ok": False, "error": "Not signed in."}, 401)
        conn = get_db()
        try:
            job = get_print_job(conn, job_id)
            if not job:
                return _json({"ok": False, "error": "Print job not found."}, 404)
            return _json({"ok": True, "job": job})
        finally:
            conn.close()

    @app.route("/api/print-jobs/<job_id>/ack", methods=["POST"], endpoint="print_jobs_ack")
    def print_jobs_ack(job_id: str):
        from db import get_db

        conn = get_db()
        try:
            agent_id, err = _agent_auth(conn)
            if err:
                return _json(err, 401)
            payload = request.get_json(silent=True) or {}
            status = str(payload.get("status") or "").upper()
            if not status:
                return _json({"ok": False, "error": "status is required."}, 400)
            result = update_job_status(
                conn,
                job_id,
                status,
                error=str(payload.get("error") or payload.get("message") or "") or None,
                agent_id=agent_id,
            )
            code = 200 if result.get("ok") else 400
            return _json(result, code)
        finally:
            conn.close()

    @app.route("/api/print-jobs/pending", methods=["GET"], endpoint="print_jobs_pending")
    def print_jobs_pending():
        from db import get_db

        conn = get_db()
        try:
            agent_id, err = _agent_auth(conn)
            if err:
                return _json(err, 401)
            recover_stale_print_jobs(conn)
            jobs = list_pending_jobs(conn, agent_id)
            payloads = [job_ws_payload(job) for job in jobs]
            deliver_pending_jobs_for_agent(conn, agent_id)
            return _json({"ok": True, "jobs": payloads, "agentId": agent_id})
        finally:
            conn.close()

    @app.route("/ws/print-agent", endpoint="print_agent_ws")
    def print_agent_ws_route():
        try:
            from simple_websocket import Server, ConnectionClosed
        except ImportError:
            return _json(
                {
                    "ok": False,
                    "error": "WebSocket support is not installed on this server.",
                },
                501,
            )
        from db import get_db
        from print_agent_ws import handle_agent_ws_connection

        agent_id = str(
            request.args.get("agentId")
            or request.args.get("agent_id")
            or request.headers.get("X-Print-Agent-Id")
            or ""
        ).strip()
        token = _bearer_token()
        conn = get_db()
        try:
            if not agent_id or not verify_print_agent_bearer(conn, agent_id, token):
                return _json({"ok": False, "error": "Invalid agent credentials."}, 401)
        finally:
            conn.close()
        try:
            ws = Server(request.environ)
        except Exception:
            return _json({"ok": False, "error": "WebSocket upgrade failed."}, 400)
        try:
            handle_agent_ws_connection(
                ws,
                agent_id=agent_id,
                on_message=_handle_agent_ws_message,
            )
        except ConnectionClosed:
            pass
        return ""
