"""Send indent_approval WhatsApp templates when an indent awaits approval."""

from __future__ import annotations

import logging
import os
import tempfile
from typing import Any

import whatsapp_client as wa
from indent_approval_pdf import build_indent_approval_pdf, format_indent_total_amount

log = logging.getLogger(__name__)


def indent_approval_template_name() -> str:
    return (os.environ.get("WHATSAPP_INDENT_APPROVAL_TEMPLATE") or "indent_approval").strip()


def indent_approval_template_language() -> str:
    return (os.environ.get("WHATSAPP_INDENT_APPROVAL_TEMPLATE_LANGUAGE") or "en").strip() or "en"


def indent_approver_numbers() -> list[str]:
    return wa.parse_whatsapp_recipients(
        os.environ.get("WHATSAPP_INDENT_APPROVER_NUMBERS") or ""
    )


def indent_approver_name() -> str:
    return (os.environ.get("WHATSAPP_INDENT_APPROVER_NAME") or "Sir").strip() or "Sir"


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


def notify_indent_pending_whatsapp(
    conn,
    indent_id: int,
    *,
    outlet_label: str = "",
) -> tuple[bool, str]:
    """Build PDF + send indent_approval template to configured approvers.

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

        sent = 0
        failed = 0
        last_error = ""
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
