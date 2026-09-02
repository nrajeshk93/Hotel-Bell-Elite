"""Unified print job queue — web and mobile share the same pipeline."""

from __future__ import annotations

import json
import sqlite3
import os
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Any, Optional

from print_content import (
    build_kot_print_payload,
    build_kot_ticket_model,
    kot_printer_role,
)
from print_agent_store import ensure_print_agent_schema

PRINT_JOB_STATUSES = (
    "CREATED",
    "QUEUED",
    "SENT_TO_AGENT",
    "PRINTING",
    "PRINTED",
    "FAILED",
)

_STATUS_TRANSITIONS = {
    "CREATED": {"QUEUED", "FAILED"},
    "QUEUED": {"SENT_TO_AGENT", "FAILED"},
    "SENT_TO_AGENT": {"PRINTING", "QUEUED", "FAILED"},
    "PRINTING": {"PRINTED", "FAILED"},
    "PRINTED": set(),
    "FAILED": set(),
}

AGENT_ONLINE_TTL_SECONDS = int(os.environ.get("PRINT_AGENT_ONLINE_TTL_SECONDS", "120") or 120)
STALE_SENT_MINUTES = int(os.environ.get("PRINT_JOB_STALE_SENT_MINUTES", "5") or 5)
DEFAULT_BUSINESS_ID = (os.environ.get("PRINT_AGENT_DEFAULT_BUSINESS_ID") or "hotel-bell-elite").strip()


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def ensure_print_job_schema(conn) -> None:
    ensure_print_agent_schema(conn)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS print_jobs (
            job_id TEXT PRIMARY KEY,
            business_id TEXT NOT NULL DEFAULT '',
            location_id TEXT NOT NULL DEFAULT '',
            agent_id TEXT NOT NULL DEFAULT '',
            printer_id TEXT NOT NULL DEFAULT '',
            printer_role TEXT NOT NULL DEFAULT '',
            document_type TEXT NOT NULL DEFAULT '',
            document_id INTEGER NOT NULL DEFAULT 0,
            copies INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'CREATED',
            content_type TEXT NOT NULL DEFAULT 'text',
            content_encoding TEXT NOT NULL DEFAULT 'utf8',
            content TEXT NOT NULL DEFAULT '',
            idempotency_key TEXT NOT NULL DEFAULT '',
            error_message TEXT NOT NULL DEFAULT '',
            meta_json TEXT NOT NULL DEFAULT '{}',
            created_by INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT '',
            sent_at TEXT NOT NULL DEFAULT '',
            printed_at TEXT NOT NULL DEFAULT ''
        )
        """
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_print_jobs_idempotency
        ON print_jobs(idempotency_key)
        WHERE idempotency_key != ''
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_print_jobs_agent_status
        ON print_jobs(agent_id, status)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_print_jobs_status_created
        ON print_jobs(status, created_at)
        """
    )
    conn.commit()


def _parse_meta(raw: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def _job_row_to_dict(row) -> dict[str, Any]:
    if not row:
        return {}
    meta = _parse_meta(row["meta_json"] if "meta_json" in row.keys() else "{}")
    return {
        "ok": True,
        "jobId": row["job_id"],
        "job_id": row["job_id"],
        "organizationId": row["business_id"],
        "business_id": row["business_id"],
        "locationId": row["location_id"],
        "location_id": row["location_id"],
        "agentId": row["agent_id"] or None,
        "agent_id": row["agent_id"] or None,
        "printerId": row["printer_id"] or None,
        "printer_id": row["printer_id"] or None,
        "printerRole": row["printer_role"],
        "printer_role": row["printer_role"],
        "documentType": row["document_type"],
        "document_type": row["document_type"],
        "documentId": int(row["document_id"] or 0),
        "document_id": int(row["document_id"] or 0),
        "copies": int(row["copies"] or 1),
        "status": row["status"],
        "contentType": row["content_type"],
        "content_type": row["content_type"],
        "contentEncoding": row["content_encoding"],
        "content_encoding": row["content_encoding"],
        "content": row["content"],
        "idempotencyKey": row["idempotency_key"] or None,
        "idempotency_key": row["idempotency_key"] or None,
        "error": row["error_message"] or None,
        "error_message": row["error_message"] or None,
        "meta": meta,
        "createdBy": int(row["created_by"] or 0),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
        "sentAt": row["sent_at"] or None,
        "printedAt": row["printed_at"] or None,
    }


def get_print_job(conn, job_id: str) -> Optional[dict[str, Any]]:
    ensure_print_job_schema(conn)
    row = conn.execute(
        "SELECT * FROM print_jobs WHERE job_id = ?",
        (str(job_id or "").strip(),),
    ).fetchone()
    return _job_row_to_dict(row) if row else None


def _find_existing_job(conn, job_id: str, idempotency_key: str) -> Optional[dict[str, Any]]:
    ensure_print_job_schema(conn)
    key = (idempotency_key or "").strip()
    if key:
        row = conn.execute(
            "SELECT * FROM print_jobs WHERE idempotency_key = ?",
            (key,),
        ).fetchone()
        if row:
            return _job_row_to_dict(row)
    jid = (job_id or "").strip()
    if jid:
        row = conn.execute(
            "SELECT * FROM print_jobs WHERE job_id = ?",
            (jid,),
        ).fetchone()
        if row:
            return _job_row_to_dict(row)
    return None


def _can_transition(current: str, new: str) -> bool:
    cur = str(current or "").upper()
    nxt = str(new or "").upper()
    if cur == nxt:
        return True
    return nxt in _STATUS_TRANSITIONS.get(cur, set())


def update_job_status(
    conn,
    job_id: str,
    status: str,
    *,
    error: str | None = None,
    agent_id: str | None = None,
) -> dict[str, Any]:
    ensure_print_job_schema(conn)
    row = conn.execute(
        "SELECT * FROM print_jobs WHERE job_id = ?",
        (str(job_id or "").strip(),),
    ).fetchone()
    if not row:
        return {"ok": False, "error": "Print job not found."}
    new_status = str(status or "").upper()
    if not _can_transition(row["status"], new_status):
        return {
            "ok": False,
            "error": f"Invalid status transition {row['status']} -> {new_status}.",
        }
    stamp = _now()
    sent_at = row["sent_at"] or ""
    printed_at = row["printed_at"] or ""
    if new_status == "SENT_TO_AGENT" and not sent_at:
        sent_at = stamp
    if new_status == "PRINTED":
        printed_at = stamp
    resolved_agent = (agent_id or row["agent_id"] or "").strip()
    conn.execute(
        """
        UPDATE print_jobs
        SET status = ?,
            error_message = COALESCE(?, error_message),
            agent_id = CASE WHEN ? != '' THEN ? ELSE agent_id END,
            updated_at = ?,
            sent_at = ?,
            printed_at = ?
        WHERE job_id = ?
        """,
        (
            new_status,
            (error or "")[:500] if error else None,
            resolved_agent,
            resolved_agent,
            stamp,
            sent_at,
            printed_at,
            row["job_id"],
        ),
    )
    conn.commit()
    return {"ok": True, "job": get_print_job(conn, row["job_id"])}


def _agent_last_seen_online(last_seen_at: str) -> bool:
    text = (last_seen_at or "").strip()
    if not text:
        return False
    try:
        seen = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return False
    return datetime.now() - seen <= timedelta(seconds=AGENT_ONLINE_TTL_SECONDS)


def is_agent_online(agent_id: str) -> bool:
    from print_agent_ws import is_agent_ws_connected

    aid = str(agent_id or "").strip()
    if not aid:
        return False
    if is_agent_ws_connected(aid):
        return True
    return False


def _load_mapped_printers(raw: str) -> dict[str, str]:
    try:
        parsed = json.loads(raw or "{}")
        if isinstance(parsed, dict):
            return {str(k): str(v or "") for k, v in parsed.items()}
    except (TypeError, ValueError, json.JSONDecodeError):
        pass
    return {}


def resolve_agent_for_role(
    conn,
    *,
    business_id: str,
    printer_role: str,
) -> tuple[str, str]:
    """Return (agent_id, printer_id) for a role, or ('', '') when none online."""
    ensure_print_agent_schema(conn)
    role = str(printer_role or "").strip()
    biz = (business_id or DEFAULT_BUSINESS_ID).strip()
    rows = conn.execute(
        """
        SELECT agent_id, business_id, mapped_printers_json, last_seen_at
        FROM print_agents
        WHERE revoked = 0
        ORDER BY datetime(last_seen_at) DESC, datetime(updated_at) DESC
        """
    ).fetchall()
    candidates: list[tuple[str, str, bool, bool]] = []
    for row in rows:
        row_biz = (row["business_id"] or "").strip()
        if biz and row_biz and row_biz != biz:
            continue
        mapped = _load_mapped_printers(row["mapped_printers_json"])
        printer_name = (mapped.get(role) or "").strip()
        if not printer_name:
            continue
        ws_online = is_agent_online(row["agent_id"])
        hb_online = _agent_last_seen_online(row["last_seen_at"])
        candidates.append((row["agent_id"], printer_name, ws_online, hb_online))
    for agent_id, printer_name, ws_online, hb_online in candidates:
        if ws_online:
            return agent_id, printer_name
    for agent_id, printer_name, ws_online, hb_online in candidates:
        if hb_online:
            return agent_id, printer_name
    return "", ""


def route_print_job(conn, job: dict[str, Any]) -> dict[str, Any]:
    ensure_print_job_schema(conn)
    job_id = job.get("jobId") or job.get("job_id")
    role = job.get("printerRole") or job.get("printer_role") or "billing"
    business_id = job.get("businessId") or job.get("business_id") or DEFAULT_BUSINESS_ID
    agent_id, printer_id = resolve_agent_for_role(
        conn, business_id=business_id, printer_role=role
    )
    stamp = _now()
    if agent_id:
        conn.execute(
            """
            UPDATE print_jobs
            SET agent_id = ?, printer_id = ?, status = 'QUEUED', updated_at = ?
            WHERE job_id = ?
            """,
            (agent_id, printer_id, stamp, job_id),
        )
    else:
        conn.execute(
            """
            UPDATE print_jobs
            SET status = 'QUEUED', updated_at = ?
            WHERE job_id = ?
            """,
            (stamp, job_id),
        )
    conn.commit()
    refreshed = get_print_job(conn, job_id)
    if refreshed:
        _dispatch_job(refreshed)
    return refreshed or job


def job_ws_payload(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "print_job",
        "jobId": job.get("jobId") or job.get("job_id"),
        "printerRole": job.get("printerRole") or job.get("printer_role"),
        "printerId": job.get("printerId") or job.get("printer_id"),
        "documentType": job.get("documentType") or job.get("document_type"),
        "contentType": job.get("contentType") or job.get("content_type"),
        "contentEncoding": job.get("contentEncoding") or job.get("content_encoding"),
        "content": job.get("content") or "",
        "copies": int(job.get("copies") or 1),
    }


def _dispatch_job(job: dict[str, Any]) -> bool:
    from print_agent_ws import push_print_job_to_agent

    agent_id = (job.get("agentId") or job.get("agent_id") or "").strip()
    if not agent_id:
        return False
    pushed = push_print_job_to_agent(agent_id, job_ws_payload(job))
    if pushed:
        from db import get_db

        conn = get_db()
        try:
            update_job_status(conn, job["jobId"], "SENT_TO_AGENT", agent_id=agent_id)
        finally:
            conn.close()
    return pushed


def list_pending_jobs(conn, agent_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
    ensure_print_job_schema(conn)
    aid = str(agent_id or "").strip()
    rows = conn.execute(
        """
        SELECT * FROM print_jobs
        WHERE agent_id = ?
          AND status IN ('QUEUED', 'SENT_TO_AGENT')
        ORDER BY datetime(created_at) ASC, job_id ASC
        LIMIT ?
        """,
        (aid, int(limit or 50)),
    ).fetchall()
    return [_job_row_to_dict(row) for row in rows]


def recover_stale_print_jobs(conn) -> int:
    ensure_print_job_schema(conn)
    cutoff = (datetime.now() - timedelta(minutes=STALE_SENT_MINUTES)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    rows = conn.execute(
        """
        SELECT job_id FROM print_jobs
        WHERE status = 'SENT_TO_AGENT'
          AND datetime(updated_at) < datetime(?)
        """,
        (cutoff,),
    ).fetchall()
    count = 0
    for row in rows:
        update_job_status(conn, row["job_id"], "QUEUED")
        job = get_print_job(conn, row["job_id"])
        if job:
            _dispatch_job(job)
            count += 1
    return count


def _normalize_payload(data: dict[str, Any]) -> dict[str, Any]:
    payload = data if isinstance(data, dict) else {}
    job_id = str(
        payload.get("jobId")
        or payload.get("job_id")
        or payload.get("id")
        or ""
    ).strip()
    if not job_id:
        job_id = f"job-{uuid.uuid4().hex}"
    idempotency = str(
        payload.get("idempotencyKey") or payload.get("idempotency_key") or job_id
    ).strip()
    location_id = str(
        payload.get("locationId")
        or payload.get("location_id")
        or payload.get("outlet")
        or ""
    ).strip().lower()
    document_type = str(
        payload.get("documentType") or payload.get("document_type") or "kot"
    ).strip().lower()
    printer_role = str(
        payload.get("printerRole")
        or payload.get("printer_role")
        or kot_printer_role(location_id)
    ).strip()
    try:
        document_id = int(payload.get("documentId") or payload.get("document_id") or 0)
    except (TypeError, ValueError):
        document_id = 0
    try:
        copies = max(1, int(payload.get("copies") or 1))
    except (TypeError, ValueError):
        copies = 1
    business_id = str(
        payload.get("businessId")
        or payload.get("business_id")
        or payload.get("organizationId")
        or payload.get("organization_id")
        or DEFAULT_BUSINESS_ID
    ).strip()
    return {
        "job_id": job_id,
        "idempotency_key": idempotency,
        "business_id": business_id,
        "location_id": location_id,
        "document_type": document_type,
        "document_id": document_id,
        "printer_role": printer_role,
        "copies": copies,
        "content_type": str(payload.get("contentType") or payload.get("content_type") or "text"),
        "content_encoding": str(
            payload.get("contentEncoding") or payload.get("content_encoding") or "utf8"
        ),
        "content": str(payload.get("content") or ""),
        "meta": payload.get("meta") if isinstance(payload.get("meta"), dict) else {},
        "resend": bool(payload.get("resend")),
        "items": payload.get("items") if isinstance(payload.get("items"), list) else None,
    }


def build_document_content(
    conn,
    *,
    document_type: str,
    document_id: int,
    location_id: str,
    meta: dict[str, Any] | None = None,
    items: list[dict[str, Any]] | None = None,
    resend: bool = False,
) -> dict[str, str]:
    meta = meta or {}
    doc_type = str(document_type or "").lower()
    if doc_type == "kot":
        from db import get_pos_invoice

        invoice = get_pos_invoice(conn, document_id)
        if not invoice:
            raise ValueError("Invoice not found for KOT print.")
        outlet = location_id or str(invoice.get("outlet") or "restaurant").lower()
        kot_items = items
        if kot_items is None:
            kot_items = []
            for line in invoice.get("lines") or []:
                try:
                    sent = float(line.get("sent_qty") or 0)
                except (TypeError, ValueError):
                    sent = 0.0
                if sent <= 0:
                    continue
                line_outlet = str(line.get("outlet") or outlet).lower()
                if outlet in ("restaurant", "bar") and line_outlet != outlet:
                    continue
                kot_items.append(
                    {
                        "name": line.get("name") or "Item",
                        "qty": sent,
                        "variant": line.get("variant") or "",
                        "notes": line.get("notes") or "",
                    }
                )
        if not kot_items:
            raise ValueError("No kitchen items to print.")
        model = build_kot_ticket_model(
            invoice,
            kot_items,
            menu_outlet=outlet,
            resend=resend,
            user_label=str(meta.get("userLabel") or meta.get("user_label") or ""),
        )
        return build_kot_print_payload(model)
    raise ValueError(f"Unsupported document type: {document_type}")


def create_print_job(conn, payload: dict[str, Any], *, user_id: int = 0) -> dict[str, Any]:
    ensure_print_job_schema(conn)
    norm = _normalize_payload(payload)
    existing = _find_existing_job(conn, norm["job_id"], norm["idempotency_key"])
    if existing:
        existing["duplicate"] = True
        return existing

    content = norm["content"]
    content_type = norm["content_type"]
    content_encoding = norm["content_encoding"]
    if not content:
        built = build_document_content(
            conn,
            document_type=norm["document_type"],
            document_id=norm["document_id"],
            location_id=norm["location_id"],
            meta=norm["meta"],
            items=norm["items"],
            resend=norm["resend"],
        )
        content = built["content"]
        content_type = built["content_type"]
        content_encoding = built["content_encoding"]

    stamp = _now()
    try:
        conn.execute(
            """
            INSERT INTO print_jobs (
                job_id, business_id, location_id, agent_id, printer_id, printer_role,
                document_type, document_id, copies, status,
                content_type, content_encoding, content,
                idempotency_key, error_message, meta_json,
                created_by, created_at, updated_at
            ) VALUES (?, ?, ?, '', '', ?, ?, ?, ?, 'CREATED', ?, ?, ?, ?, '', ?, ?, ?, ?)
            """,
            (
                norm["job_id"],
                norm["business_id"],
                norm["location_id"],
                norm["printer_role"],
                norm["document_type"],
                norm["document_id"],
                norm["copies"],
                content_type,
                content_encoding,
                content,
                norm["idempotency_key"],
                json.dumps(norm["meta"]),
                int(user_id or 0),
                stamp,
                stamp,
            ),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
        existing = _find_existing_job(conn, norm["job_id"], norm["idempotency_key"])
        if existing:
            existing["duplicate"] = True
            return existing
        raise
    job = get_print_job(conn, norm["job_id"])
    if not job:
        return {"ok": False, "error": "Could not create print job."}
    return route_print_job(conn, job)


def enqueue_kot_jobs_for_invoice(
    conn,
    invoice: dict[str, Any],
    pending_items: list[dict[str, Any]],
    *,
    user_id: int = 0,
    resend: bool = False,
) -> list[dict[str, Any]]:
    """Create one print job per menu outlet group (restaurant / bar)."""
    if not invoice or not pending_items:
        return []
    invoice_id = int(invoice.get("id") or 0)
    if invoice_id <= 0:
        return []
    groups: dict[str, list[dict[str, Any]]] = {}
    for entry in pending_items:
        line = entry.get("line") if isinstance(entry, dict) and entry.get("line") else entry
        if not isinstance(line, dict):
            continue
        try:
            delta = float(entry.get("delta_qty") if isinstance(entry, dict) else line.get("qty") or 0)
        except (TypeError, ValueError):
            delta = 0.0
        if delta <= 0:
            try:
                qty = float(line.get("qty") or 0)
                sent = float(line.get("sent_qty") or 0)
                delta = max(0.0, qty - sent)
            except (TypeError, ValueError):
                delta = 0.0
        if delta <= 0 and not resend:
            continue
        menu_outlet = str(line.get("outlet") or invoice.get("outlet") or "restaurant").lower()
        groups.setdefault(menu_outlet, []).append(
            {
                "name": line.get("name") or "Item",
                "qty": delta if not resend else float(line.get("sent_qty") or line.get("qty") or 0),
                "variant": line.get("variant") or "",
                "notes": line.get("notes") or "",
            }
        )
    created: list[dict[str, Any]] = []
    base = f"kot-{invoice_id}-{int(datetime.now().timestamp() * 1000)}"
    for idx, (menu_outlet, items) in enumerate(sorted(groups.items())):
        if not items:
            continue
        job_id = f"{base}-{menu_outlet}-{idx}"
        job = create_print_job(
            conn,
            {
                "jobId": job_id,
                "idempotencyKey": job_id,
                "documentType": "kot",
                "documentId": invoice_id,
                "locationId": menu_outlet,
                "printerRole": kot_printer_role(menu_outlet),
                "resend": resend,
                "items": items,
            },
            user_id=user_id,
        )
        if job:
            created.append(job)
    return created


def assign_queued_jobs_for_agent(conn, agent_id: str) -> int:
    """Attach unassigned QUEUED jobs to a newly online agent when roles match."""
    ensure_print_job_schema(conn)
    aid = str(agent_id or "").strip()
    if not aid:
        return 0
    row = conn.execute(
        "SELECT mapped_printers_json, business_id FROM print_agents WHERE agent_id = ? AND revoked = 0",
        (aid,),
    ).fetchone()
    if not row:
        return 0
    mapped = _load_mapped_printers(row["mapped_printers_json"])
    if not mapped:
        return 0
    roles = set(mapped.keys())
    rows = conn.execute(
        """
        SELECT job_id, printer_role, business_id
        FROM print_jobs
        WHERE status = 'QUEUED' AND (agent_id = '' OR agent_id IS NULL)
        ORDER BY datetime(created_at) ASC
        """
    ).fetchall()
    assigned = 0
    biz = (row["business_id"] or "").strip()
    for job_row in rows:
        role = (job_row["printer_role"] or "").strip()
        if role not in roles:
            continue
        job_biz = (job_row["business_id"] or "").strip()
        if biz and job_biz and biz != job_biz:
            continue
        printer_id = mapped.get(role) or ""
        stamp = _now()
        conn.execute(
            """
            UPDATE print_jobs
            SET agent_id = ?, printer_id = ?, updated_at = ?
            WHERE job_id = ?
            """,
            (aid, printer_id, stamp, job_row["job_id"]),
        )
        assigned += 1
    if assigned:
        conn.commit()
        deliver_pending_jobs_for_agent(conn, aid)
    return assigned


def deliver_pending_jobs_for_agent(conn, agent_id: str) -> int:
    jobs = list_pending_jobs(conn, agent_id)
    sent = 0
    for job in jobs:
        if _dispatch_job(job):
            sent += 1
    return sent
