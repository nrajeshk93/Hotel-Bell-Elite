"""Meta WhatsApp webhook — verify + indent Approve/Reject replies."""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime

import whatsapp_client as wa

log = logging.getLogger(__name__)

_WEBHOOK_LOG = os.path.join(os.path.dirname(__file__), "logs", "whatsapp_webhook.log")

WHATSAPP_REJECT_NOTE = "Rejected via WhatsApp"
WHATSAPP_APPROVE_NOTE = "Approved via WhatsApp"

_APPROVE_WORDS = {
    "approve",
    "approved",
    "yes",
    "ok",
    "okay",
    "accept",
    "accepted",
}
_REJECT_WORDS = {
    "reject",
    "rejected",
    "no",
    "deny",
    "denied",
    "decline",
    "declined",
}


def whatsapp_verify_token() -> str:
    return (os.environ.get("WHATSAPP_VERIFY_TOKEN") or "").strip()


def _append_webhook_log(line: str) -> None:
    try:
        os.makedirs(os.path.dirname(_WEBHOOK_LOG), exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(_WEBHOOK_LOG, "a", encoding="utf-8") as fh:
            fh.write(f"[{stamp}] {line}\n")
    except OSError:
        pass


def handle_verification_get(request):
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    expected = whatsapp_verify_token()
    if mode == "subscribe" and expected and token == expected:
        log.info("WhatsApp webhook verified successfully.")
        return (challenge or ""), 200, {"Content-Type": "text/plain"}
    log.warning("WhatsApp webhook verify rejected.")
    return "Forbidden", 403


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _normalise_reply_text(value: str) -> str:
    cleaned = re.sub(r"[^\w\s]", " ", (value or "").strip().lower())
    return " ".join(cleaned.split())


def _decision_from_reply(title: str, payload: str) -> str:
    """Map button/text replies to approved | rejected."""
    title_n = _normalise_reply_text(title)
    payload_n = _normalise_reply_text(payload)
    for candidate in (title_n, payload_n, f"{title_n} {payload_n}".strip()):
        if not candidate:
            continue
        if candidate in _REJECT_WORDS or candidate.startswith("reject"):
            return "rejected"
        if candidate in _APPROVE_WORDS or candidate.startswith("approve"):
            return "approved"
    tokens = set(f"{title_n} {payload_n}".split())
    if tokens & _REJECT_WORDS:
        return "rejected"
    if tokens & _APPROVE_WORDS:
        return "approved"
    return ""


def _indent_id_from_payload(payload: str) -> int:
    raw = (payload or "").strip()
    if ":" in raw:
        raw = raw.split(":", 1)[1].strip()
    if not re.fullmatch(r"\d+", raw):
        return 0
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def _lookup_indent_id(
    conn,
    *,
    context_message_id: str,
    payload: str,
    sender_phone: str = "",
) -> int:
    """Resolve indent from reply-to context, payload, or latest pending sent to sender."""
    from_payload = _indent_id_from_payload(payload)
    if from_payload:
        return from_payload

    context_message_id = (context_message_id or "").strip()
    if context_message_id:
        row = conn.execute(
            """
            SELECT indent_id FROM store_indent_whatsapp_messages
            WHERE wa_message_id = ? AND status = 'sent'
            ORDER BY id DESC LIMIT 1
            """,
            (context_message_id,),
        ).fetchone()
        if row:
            return int(row["indent_id"])

    phone = wa.normalise_whatsapp_number(sender_phone)
    if not phone:
        return 0
    # Fallback: most recent pending indent whose approval WhatsApp was sent to this number.
    row = conn.execute(
        """
        SELECT m.indent_id
        FROM store_indent_whatsapp_messages m
        JOIN store_indents i ON i.id = m.indent_id
        WHERE m.recipient_phone = ?
          AND m.status = 'sent'
          AND i.status = 'pending'
        ORDER BY m.id DESC
        LIMIT 1
        """,
        (phone,),
    ).fetchone()
    return int(row["indent_id"]) if row else 0


def _apply_whatsapp_decision(conn, indent_id: int, decision: str) -> tuple[bool, str]:
    indent = conn.execute(
        "SELECT id, indent_no, status FROM store_indents WHERE id = ?",
        (indent_id,),
    ).fetchone()
    if not indent:
        return False, "Indent not found."
    if (indent["status"] or "") != "pending":
        return False, f"Indent {indent['indent_no']} is no longer waiting for approval."
    note = WHATSAPP_APPROVE_NOTE if decision == "approved" else WHATSAPP_REJECT_NOTE
    conn.execute(
        """
        UPDATE store_indents
        SET status = ?, decided_by = NULL, decided_at = ?, decision_note = ?
        WHERE id = ? AND status = 'pending'
        """,
        (decision, _now(), note, indent_id),
    )
    return True, f"Indent {indent['indent_no']} {decision}."


def _iter_inbound_messages(payload: dict):
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            metadata = value.get("metadata") or {}
            phone_number_id = str(metadata.get("phone_number_id") or "")
            for message in value.get("messages") or []:
                yield phone_number_id, message


def _extract_reply(message: dict) -> tuple[str, str, str]:
    """Return (title, payload, context_id) for button or text replies."""
    msg_type = (message.get("type") or "").strip().lower()
    context_id = str((message.get("context") or {}).get("id") or "").strip()
    if msg_type == "interactive":
        interactive = message.get("interactive") or {}
        button = interactive.get("button_reply") or interactive.get("list_reply") or {}
        return (
            str(button.get("title") or "").strip(),
            str(button.get("id") or button.get("payload") or "").strip(),
            context_id,
        )
    if msg_type == "button":
        button = message.get("button") or {}
        return (
            str(button.get("text") or "").strip(),
            str(button.get("payload") or "").strip(),
            context_id,
        )
    if msg_type == "text":
        body = str((message.get("text") or {}).get("body") or "").strip()
        return body, body, context_id
    return "", "", context_id


def process_indent_button_replies(conn, payload: dict) -> list[str]:
    """Apply Approve/Reject from inbound WhatsApp button or text replies."""
    results = []
    expected_phone_id = wa.whatsapp_phone_number_id()
    for phone_number_id, message in _iter_inbound_messages(payload):
        if expected_phone_id and phone_number_id and phone_number_id != expected_phone_id:
            continue
        title, payload_text, context_id = _extract_reply(message)
        decision = _decision_from_reply(title, payload_text)
        if not decision:
            continue
        sender = str(message.get("from") or "")
        indent_id = _lookup_indent_id(
            conn,
            context_message_id=context_id,
            payload=payload_text,
            sender_phone=sender,
        )
        if not indent_id:
            results.append(f"no_indent from={sender} title={title!r}")
            if sender:
                wa.send_text_message(
                    sender,
                    "Could not match that reply to a waiting indent. "
                    "Please reply Approved or Rejected to the indent approval message.",
                )
            continue
        ok, msg = _apply_whatsapp_decision(conn, indent_id, decision)
        results.append(msg if ok else f"skip: {msg}")
        if sender:
            wa.send_text_message(sender, msg if ok else f"Could not update indent: {msg}")
    return results


def handle_events_post(request, get_db, ensure_stores_schema):
    payload = request.get_json(silent=True)
    if payload is None:
        try:
            raw = request.get_data(as_text=True) or ""
            payload = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:
            payload = {"_raw": (request.get_data(as_text=True) or "")[:500]}

    if not isinstance(payload, dict):
        payload = {}

    summary_bits = []
    conn = get_db()
    try:
        ensure_stores_schema(conn)
        results = process_indent_button_replies(conn, payload)
        if results:
            conn.commit()
            summary_bits.extend(results)
        else:
            for entry in payload.get("entry") or []:
                for change in entry.get("changes") or []:
                    value = change.get("value") or {}
                    for status in value.get("statuses") or []:
                        summary_bits.append(
                            f"status={status.get('status')} id={str(status.get('id') or '')[:40]}"
                        )
                    for message in value.get("messages") or []:
                        summary_bits.append(
                            f"inbound from={message.get('from')} type={message.get('type')}"
                        )
    except Exception:
        conn.rollback()
        log.exception("WhatsApp webhook processing failed")
        _append_webhook_log("error processing webhook")
        return "OK", 200
    finally:
        conn.close()

    payload_text = json.dumps(payload, default=str)[:4000]
    log.info("WhatsApp webhook POST: %s", payload_text)
    if summary_bits:
        for line in summary_bits:
            _append_webhook_log(line)
            log.info("WhatsApp webhook: %s", line)
    else:
        _append_webhook_log(f"event {payload_text[:500]}")
    return "OK", 200
