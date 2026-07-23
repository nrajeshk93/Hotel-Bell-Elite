"""Send indent_approval WhatsApp templates when an indent awaits approval."""

from __future__ import annotations

import logging
import os
import tempfile
from typing import Any

import whatsapp_client as wa
from indent_approval_pdf import build_indent_approval_pdf, format_indent_total_amount

log = logging.getLogger(__name__)

# Hard default: at most 10 successful indent-approval WhatsApp sends per rolling 24 hours.
_DEFAULT_DAILY_CAP = 10


def indent_approval_template_name() -> str:
    return (os.environ.get("WHATSAPP_INDENT_APPROVAL_TEMPLATE") or "indent_approval_v2").strip()


def indent_approval_template_language() -> str:
    return (os.environ.get("WHATSAPP_INDENT_APPROVAL_TEMPLATE_LANGUAGE") or "en").strip() or "en"


def indent_approver_numbers() -> list[str]:
    return wa.parse_whatsapp_recipients(
        os.environ.get("WHATSAPP_INDENT_APPROVER_NUMBERS") or ""
    )


def indent_approver_name() -> str:
    return (os.environ.get("WHATSAPP_INDENT_APPROVER_NAME") or "Neeraj").strip() or "Neeraj"


def indent_whatsapp_daily_cap() -> int:
    """Max successful indent-approval WhatsApp sends allowed in a rolling 24-hour window."""
    raw = (os.environ.get("WHATSAPP_INDENT_DAILY_CAP") or str(_DEFAULT_DAILY_CAP)).strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return _DEFAULT_DAILY_CAP


def count_todays_indent_whatsapp_sends(conn) -> int:
    """Successful approval sends in the last 24 hours (local), including later-superseded ones."""
    row = conn.execute(
        """
        SELECT COUNT(*) AS c
        FROM store_indent_whatsapp_messages
        WHERE status IN ('sent', 'superseded')
          AND datetime(created_at) >= datetime('now', 'localtime', '-24 hours')
        """
    ).fetchone()
    return int(row["c"] if row and row["c"] is not None else 0)


def remaining_indent_whatsapp_daily_quota(conn) -> int:
    cap = indent_whatsapp_daily_cap()
    used = count_todays_indent_whatsapp_sends(conn)
    return max(0, cap - used)


def _record_send(
    conn,
    *,
    indent_id: int,
    recipient_phone: str,
    wa_message_id: str,
    template_name: str,
    status: str,
    error_message: str = "",
) -> None:
    conn.execute(
        """
        INSERT INTO store_indent_whatsapp_messages
            (indent_id, recipient_phone, wa_message_id, template_name, status, error_message)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            indent_id,
            recipient_phone,
            wa_message_id or "",
            template_name,
            status,
            (error_message or "")[:500],
        ),
    )


def _already_sent_approval(
    conn,
    *,
    indent_id: int,
    recipient_phone: str,
) -> bool:
    """True if this indent+approver already got a successful send for the current round."""
    phone = (recipient_phone or "").strip()
    if not phone:
        return False
    row = conn.execute(
        """
        SELECT 1
        FROM store_indent_whatsapp_messages
        WHERE indent_id = ?
          AND recipient_phone = ?
          AND status = 'sent'
        LIMIT 1
        """,
        (indent_id, phone),
    ).fetchone()
    return row is not None


def supersede_indent_whatsapp_sends(conn, indent_id: int) -> None:
    """Mark prior successful sends as superseded so a new approval round can notify again."""
    conn.execute(
        """
        UPDATE store_indent_whatsapp_messages
        SET status = 'superseded'
        WHERE indent_id = ?
          AND status = 'sent'
        """,
        (indent_id,),
    )


def notify_indent_pending_whatsapp(
    conn,
    indent_id: int,
    *,
    outlet_label: str = "",
    force: bool = False,
) -> tuple[bool, str]:
    """Build PDF + send indent_approval template to configured approvers.

    Idempotent per indent+approver for the current approval round: skips recipients
    that already have a successful ``sent`` row unless ``force`` is True.
    Callers starting a new round (e.g. reject → resubmit) should call
    ``supersede_indent_whatsapp_sends`` first.

    Enforces a rolling 24-hour send cap (default 10; ``WHATSAPP_INDENT_DAILY_CAP``).
    Extra indents can still be created; only WhatsApp notify is blocked past the cap.

    Returns (ok, message). Caller owns commit. Failures do not raise.
    """
    if not wa.whatsapp_configured():
        return False, "WhatsApp is not configured."
    recipients = indent_approver_numbers()
    if not recipients:
        return False, "No WhatsApp indent approver numbers configured."

    indent = conn.execute(
        """
        SELECT i.*, u.full_name AS created_by_name
        FROM store_indents i
        LEFT JOIN users u ON u.id = i.created_by
        WHERE i.id = ?
        """,
        (indent_id,),
    ).fetchone()
    if not indent:
        return False, "Indent not found."
    if (indent["status"] or "") != "pending":
        return False, "Indent is not waiting for approval."

    if not force:
        recipients = [
            phone
            for phone in recipients
            if not _already_sent_approval(
                conn,
                indent_id=indent_id,
                recipient_phone=phone,
            )
        ]
    if not recipients:
        return True, "WhatsApp approval request already sent."

    remaining = remaining_indent_whatsapp_daily_quota(conn)
    cap = indent_whatsapp_daily_cap()
    if remaining <= 0:
        log.warning(
            "WhatsApp indent approval blocked by daily cap indent_id=%s used=%s cap=%s",
            indent_id,
            count_todays_indent_whatsapp_sends(conn),
            cap,
        )
        return (
            False,
            f"WhatsApp indent approval limit reached ({cap} messages / 24 hours). "
            "More indents can still be created; WhatsApp notify resumes after the window resets "
            "or raise WHATSAPP_INDENT_DAILY_CAP.",
        )
    if len(recipients) > remaining:
        # Prefer sending what quota allows rather than failing the whole notify.
        recipients = recipients[:remaining]
        log.warning(
            "WhatsApp indent approval truncated to remaining daily quota indent_id=%s remaining=%s",
            indent_id,
            remaining,
        )

    lines = [
        dict(row)
        for row in conn.execute(
            """
            SELECT item_name, quantity, unit, notes, approximate_price
            FROM store_indent_lines
            WHERE indent_id = ?
            ORDER BY id
            """,
            (indent_id,),
        ).fetchall()
    ]
    if not lines:
        return False, "Indent has no items."

    indent_data = dict(indent)
    pdf_bytes = build_indent_approval_pdf(
        indent_data,
        lines,
        requested_by=indent_data.get("created_by_name") or "",
        outlet_label=outlet_label or str(indent_data.get("outlet") or ""),
    )
    indent_no = indent_data.get("indent_no") or f"IND-{indent_id}"
    filename = f"Indent_{indent_no}.pdf".replace(" ", "_")
    template_name = indent_approval_template_name()
    language = indent_approval_template_language()
    body_params = {
        "approver_name": indent_approver_name(),
        "indent_id": str(indent_no),
        "total_amount": format_indent_total_amount(lines),
    }

    tmp_path = ""
    sent = 0
    failed = 0
    last_error = ""
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(pdf_bytes)
            tmp_path = tmp.name
        ok, err, media_body = wa.upload_media_file(tmp_path, "application/pdf")
        if not ok:
            for phone in recipients:
                _record_send(
                    conn,
                    indent_id=indent_id,
                    recipient_phone=phone,
                    wa_message_id="",
                    template_name=template_name,
                    status="failed",
                    error_message=err or "Media upload failed",
                )
            return False, err or "Could not upload indent PDF to WhatsApp."
        media_id = str((media_body or {}).get("id") or "").strip()
        if not media_id:
            return False, "WhatsApp media upload returned no media id."

        for phone in recipients:
            ok_send, send_err, send_body = wa.send_template_message(
                phone,
                template_name,
                language,
                body_params,
                header_document_id=media_id,
                header_document_filename=filename,
            )
            if ok_send:
                sent += 1
                _record_send(
                    conn,
                    indent_id=indent_id,
                    recipient_phone=phone,
                    wa_message_id=wa.first_message_id(send_body),
                    template_name=template_name,
                    status="sent",
                )
            else:
                failed += 1
                last_error = send_err or "Send failed"
                _record_send(
                    conn,
                    indent_id=indent_id,
                    recipient_phone=phone,
                    wa_message_id="",
                    template_name=template_name,
                    status="failed",
                    error_message=last_error,
                )
                log.warning(
                    "WhatsApp indent_approval failed indent_id=%s to=%s err=%s",
                    indent_id,
                    phone,
                    last_error,
                )
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    if sent and not failed:
        return True, f"WhatsApp approval request sent to {sent} recipient(s)."
    if sent and failed:
        return True, f"WhatsApp sent to {sent}; {failed} failed. {last_error}".strip()
    return False, last_error or "WhatsApp approval request failed."
