"""In-process WebSocket registry for Windows Print Agents."""

from __future__ import annotations

import json
import threading
from typing import Any, Callable, Optional

_lock = threading.RLock()
_connections: dict[str, Any] = {}
_connection_meta: dict[str, dict[str, Any]] = {}


def register_agent_connection(agent_id: str, ws, *, meta: dict[str, Any] | None = None) -> None:
    aid = str(agent_id or "").strip()
    if not aid:
        return
    with _lock:
        _connections[aid] = ws
        _connection_meta[aid] = dict(meta or {})
        _connection_meta[aid]["agentId"] = aid


def unregister_agent_connection(agent_id: str) -> None:
    aid = str(agent_id or "").strip()
    if not aid:
        return
    with _lock:
        _connections.pop(aid, None)
        _connection_meta.pop(aid, None)


def is_agent_ws_connected(agent_id: str) -> bool:
    aid = str(agent_id or "").strip()
    with _lock:
        return aid in _connections


def list_connected_agent_ids() -> list[str]:
    with _lock:
        return list(_connections.keys())


def _send_ws(ws, payload: dict[str, Any]) -> bool:
    try:
        ws.send(json.dumps(payload))
        return True
    except Exception:
        return False


def push_print_job_to_agent(agent_id: str, payload: dict[str, Any]) -> bool:
    aid = str(agent_id or "").strip()
    with _lock:
        ws = _connections.get(aid)
    if not ws:
        return False
    return _send_ws(ws, payload)


def push_message_to_agent(agent_id: str, payload: dict[str, Any]) -> bool:
    return push_print_job_to_agent(agent_id, payload)


def handle_agent_ws_connection(
    ws,
    *,
    agent_id: str,
    on_message: Optional[Callable[[str, dict[str, Any]], None]] = None,
) -> None:
    """Run a blocking WebSocket session for one Print Agent."""
    from simple_websocket import ConnectionClosed

    register_agent_connection(agent_id, ws, meta={"connectedAt": __import__("time").time()})
    try:
        from db import get_db
        from print_job_service import deliver_pending_jobs_for_agent

        conn = get_db()
        try:
            deliver_pending_jobs_for_agent(conn, agent_id)
            from print_job_service import assign_queued_jobs_for_agent

            assign_queued_jobs_for_agent(conn, agent_id)
        finally:
            conn.close()
        while True:
            raw = ws.receive()
            if raw is None:
                break
            try:
                msg = json.loads(raw)
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if not isinstance(msg, dict):
                continue
            msg_type = str(msg.get("type") or "").strip().lower()
            if msg_type == "ping":
                _send_ws(ws, {"type": "pong"})
                continue
            if on_message:
                on_message(agent_id, msg)
    except ConnectionClosed:
        pass
    finally:
        unregister_agent_connection(agent_id)
