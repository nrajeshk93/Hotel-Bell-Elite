"""Meta WhatsApp webhook — verify + indent Approve/Reject via interactive button ids."""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime

import whatsapp_client as wa

log = logging.getLogger(__name__)

_WEBHOOK_LOG = os.path.join(os.path.dirname(__file__), "logs", "whatsapp_webhook.log")
# #region agent log
_AGENT_DEBUG_LOGS = (
    os.path.join(os.path.dirname(__file__), "logs", "debug-5137c6.log"),
    os.path.join(os.path.dirname(__file__), ".cursor", "debug-5137c6.log"),
    "/Users/rajesh/Documents/New project/Hotel Bell elite/.cursor/debug-5137c6.log",
)


def _agent_dbg(hypothesis_id: str, location: str, message: str, data=None, run_id: str = "pre-fix") -> None:
    import time

    payload = {
        "sessionId": "5137c6",
        "runId": run_id,
        "hypothesisId": hypothesis_id,
        "location": location,
        "message": message,
        "data": data or {},
        "timestamp": int(time.time() * 1000),
    }
    line = json.dumps(payload, default=str) + "\n"
    for path in _AGENT_DEBUG_LOGS:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(line)
        except OSError:
            pass
# #endregion

WHATSAPP_REJECT_NOTE = "Rejected via WhatsApp"
WHATSAPP_APPROVE_NOTE = "Approved via WhatsApp"

# approve_<token> / reject_<token> (token may contain hyphens; case-insensitive prefix)
_TOKEN_BUTTON_RE = re.compile(r"^(approve|reject)_(.+)$", re.IGNORECASE)


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
    return "Forbidden", 403, {"Content-Type": "text/plain"}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def parse_token_button_id(button_id: str) -> tuple[str, str]:
    """Parse ``approve_<token>`` / ``reject_<token>`` → (decision, token).

    Returns ("", "") when the id is missing or is only a visible title echo
    without a real approval token.
    """
    raw = (button_id or "").strip().strip('"').strip("'")
    match = _TOKEN_BUTTON_RE.match(raw)
    if not match:
        return "", ""
    action = match.group(1).lower()
    token = match.group(2).strip()
    # Meta occasionally echoes the visible title as id ("Approve" / "Reject").
    if not token or token.lower() in {"approve", "approved", "reject", "rejected"}:
        return "", ""
    return ("approved" if action == "approve" else "rejected"), token


def _lookup_indent_by_token(conn, token: str):
    token = (token or "").strip()
    if not token:
        return None
    return conn.execute(
        """
        SELECT id, indent_no, status, approval_token
        FROM store_indents
        WHERE approval_token = ?
           OR lower(approval_token) = lower(?)
        ORDER BY id DESC
        LIMIT 1
        """,
        (token, token),
    ).fetchone()


def _status_label(status: str) -> str:
    status = (status or "").strip().lower()
    if status == "approved":
        return "Approved"
    if status == "rejected":
        return "Rejected"
    return status or "processed"


def _already_processed_message(indent_no: str, status: str) -> str:
    return f"This indent was already {_status_label(status)}."


def _apply_whatsapp_decision(
    conn,
    indent_id: int,
    decision: str,
    *,
    decided_by_label: str = "",
    wa_message_id: str = "",
) -> tuple[bool, str]:
    indent = conn.execute(
        "SELECT id, indent_no, status FROM store_indents WHERE id = ?",
        (indent_id,),
    ).fetchone()
    if not indent:
        return False, "Indent not found."
    current = (indent["status"] or "").strip().lower()
    if current != "pending":
        return False, _already_processed_message(indent["indent_no"], current)
    by_label = (decided_by_label or "").strip()
    note = WHATSAPP_APPROVE_NOTE if decision == "approved" else WHATSAPP_REJECT_NOTE
    if by_label:
        note = f"{note} ({by_label})"
    cur = conn.execute(
        """
        UPDATE store_indents
        SET status = ?,
            decided_by = NULL,
            decided_at = ?,
            decision_note = ?,
            wa_decided_by = ?,
            wa_decision_message_id = ?
        WHERE id = ? AND status = 'pending'
        """,
        (
            decision,
            _now(),
            note,
            by_label,
            (wa_message_id or "").strip()[:200],
            indent_id,
        ),
    )
    if cur.rowcount == 0:
        # Lost a race to a concurrent decision.
        refreshed = conn.execute(
            "SELECT status FROM store_indents WHERE id = ?",
            (indent_id,),
        ).fetchone()
        status = (refreshed["status"] if refreshed else "") or ""
        return False, _already_processed_message(indent["indent_no"], status)
    return True, f"Indent {indent['indent_no']} {decision}."


def _iter_inbound_messages(payload: dict):
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            metadata = value.get("metadata") or {}
            phone_number_id = str(metadata.get("phone_number_id") or "")
            contacts = value.get("contacts") or []
            for message in value.get("messages") or []:
                yield phone_number_id, message, contacts


def _profile_name_for_sender(contacts, sender_phone: str) -> str:
    sender_digits = wa.normalise_whatsapp_number(sender_phone)
    for contact in contacts or []:
        wa_id = wa.normalise_whatsapp_number(contact.get("wa_id") or "")
        if sender_digits and wa_id and wa_id != sender_digits:
            continue
        name = str((contact.get("profile") or {}).get("name") or "").strip()
        if name:
            return name
    return ""


def _decided_by_label(sender_phone: str, profile_name: str = "") -> str:
    phone = wa.normalise_whatsapp_number(sender_phone) or (sender_phone or "").strip()
    name = (profile_name or "").strip()
    if name and phone:
        return f"{name} / {phone}"
    return name or phone or "WhatsApp"


def _button_dict_id_title(button: dict) -> tuple[str, str]:
    if not isinstance(button, dict):
        return "", ""
    button_id = str(
        button.get("id")
        or button.get("payload")
        or button.get("button_id")
        or ""
    ).strip()
    title = str(
        button.get("title")
        or button.get("text")
        or button.get("button_text")
        or ""
    ).strip()
    return button_id, title


def _extract_button_reply(message: dict) -> tuple[str, str, bool]:
    """Return ``(button_id, title, is_button_click)`` from Meta inbound shapes.

    Supported shapes (never uses ``message.text`` / ``message.body``):
    - ``type=interactive`` + ``interactive.button_reply``
    - ``interactive.button_reply`` even if type is missing/odd
    - ``type=button`` + ``button.payload`` / ``button.text`` (legacy quick-reply)

    ``is_button_click`` is True when the inbound message is an interactive/button
    click shape (so missing ids can be logged as errors without text matching).
    """
    if not isinstance(message, dict):
        return "", "", False

    msg_type = (message.get("type") or "").strip().lower()
    interactive = message.get("interactive")
    if not isinstance(interactive, dict):
        interactive = {}

    # Primary: interactive button_reply (standard Cloud API reply buttons).
    button_reply = interactive.get("button_reply")
    if isinstance(button_reply, dict):
        button_id, title = _button_dict_id_title(button_reply)
        return button_id, title, True

    # Some payloads nest reply under interactive.button / interactive.nfm_reply-like keys.
    nested_button = interactive.get("button")
    if isinstance(nested_button, dict) and (
        nested_button.get("id") or nested_button.get("payload") or nested_button.get("title")
    ):
        button_id, title = _button_dict_id_title(nested_button)
        return button_id, title, True

    # Legacy / alternate: type=button with payload as the opaque id we sent.
    if msg_type == "button":
        button = message.get("button") or {}
        button_id, title = _button_dict_id_title(button if isinstance(button, dict) else {})
        return button_id, title, True

    if msg_type == "interactive":
        # Interactive inbound without button_reply — still a button-shaped event.
        return "", "", True

    return "", "", False


def process_indent_button_replies(conn, payload: dict) -> list[str]:
    """Apply Approve/Reject from inbound WhatsApp interactive button clicks only.

    Sole decision path: ``button_reply.id`` (or ``button.payload``) → parse
    ``approve_<token>`` / ``reject_<token>`` → lookup by ApprovalToken → update.
    Never matches ``message.body`` / text titles for indent approval.
    """
    results = []
    expected_phone_id = wa.whatsapp_phone_number_id()
    for phone_number_id, message, contacts in _iter_inbound_messages(payload):
        if expected_phone_id and phone_number_id and phone_number_id != expected_phone_id:
            continue

        sender = str(message.get("from") or "")
        inbound_id = str(message.get("id") or "").strip()
        msg_type = (message.get("type") or "").strip().lower()
        stamp = _now()
        interactive = message.get("interactive") if isinstance(message.get("interactive"), dict) else {}

        button_id, title, is_button_click = _extract_button_reply(message)

        log.info(
            "Webhook received type=%s message_type=%s interactive=%s "
            "button_reply.id=%r button_reply.title=%r from=%s message_id=%s at=%s",
            msg_type,
            interactive.get("type") or msg_type,
            bool(interactive),
            button_id,
            title,
            sender,
            inbound_id,
            stamp,
        )
        _append_webhook_log(
            f"Webhook received type={msg_type} button_reply.id={button_id!r} "
            f"title={title!r} from={sender} message_id={inbound_id}"
        )
        # #region agent log
        _agent_dbg(
            "B",
            "whatsapp_webhook.py:process_indent_button_replies",
            "extracted_button_reply",
            {
                "msg_type": msg_type,
                "is_button_click": is_button_click,
                "button_id_prefix": (button_id or "")[:16],
                "button_id_len": len(button_id or ""),
                "title": (title or "")[:40],
                "has_text_body": bool(((message.get("text") or {}) if isinstance(message.get("text"), dict) else {}).get("body")),
            },
        )
        # #endregion

        if not is_button_click:
            # Text / media / other — never run indent approval text matching.
            log.info(
                "WhatsApp webhook ignored non-button inbound from=%s type=%s at=%s",
                sender,
                msg_type,
                stamp,
            )
            # #region agent log
            _agent_dbg("C", "whatsapp_webhook.py:process_indent_button_replies", "ignored_non_button", {"msg_type": msg_type})
            # #endregion
            continue

        if not button_id:
            log.error(
                "WhatsApp button/interactive click missing id from=%s type=%s "
                "title=%r interactive=%s message_id=%s at=%s — not matching text",
                sender,
                msg_type,
                title,
                interactive or None,
                inbound_id,
                stamp,
            )
            _append_webhook_log(
                f"ERROR missing button id type={msg_type} title={title!r} from={sender}"
            )
            results.append(f"missing_button_id from={sender} type={msg_type}")
            # #region agent log
            _agent_dbg("D", "whatsapp_webhook.py:process_indent_button_replies", "missing_button_id", {"title": title, "msg_type": msg_type})
            # #endregion
            continue

        log.info("Button ID Received id=%r title=%r from=%s", button_id, title, sender)
        _append_webhook_log(f"Button ID Received id={button_id!r} from={sender}")

        decision, approval_token = parse_token_button_id(button_id)
        log.info(
            "Parsed button id action=%s token=%r from=%s",
            decision or "(none)",
            approval_token or "",
            sender,
        )
        # #region agent log
        _agent_dbg(
            "E",
            "whatsapp_webhook.py:process_indent_button_replies",
            "parsed_token_button",
            {
                "decision": decision or "",
                "token_len": len(approval_token or ""),
                "token_prefix": (approval_token or "")[:8],
            },
        )
        # #endregion
        if not decision or not approval_token:
            log.error(
                "WhatsApp button id not approve_/reject_<token> from=%s button_id=%r at=%s",
                sender,
                button_id,
                stamp,
            )
            _append_webhook_log(f"ERROR unparseable button_id={button_id!r} from={sender}")
            results.append(f"unparseable_button_id from={sender} id={button_id!r}")
            continue

        profile_name = _profile_name_for_sender(contacts, sender)
        by_label = _decided_by_label(sender, profile_name)

        log.info(
            "WhatsApp webhook action=%s from=%s mobile=%s token=%r button_id=%r "
            "message_id=%s at=%s",
            decision,
            by_label,
            sender,
            approval_token,
            button_id,
            inbound_id,
            stamp,
        )
        _append_webhook_log(
            f"action={decision} from={sender} token={approval_token} "
            f"button_id={button_id!r} message_id={inbound_id}"
        )

        row = _lookup_indent_by_token(conn, approval_token)
        if not row:
            msg = "Unknown or expired approval token. No indent was updated."
            log.warning(
                "WhatsApp webhook unknown approval token=%s from=%s at=%s",
                approval_token,
                sender,
                stamp,
            )
            results.append(f"unknown_token from={sender} token={approval_token}")
            # #region agent log
            _agent_dbg(
                "E",
                "whatsapp_webhook.py:process_indent_button_replies",
                "indent_not_found_for_token",
                {"token_prefix": (approval_token or "")[:8], "decision": decision},
            )
            # #endregion
            if sender:
                wa.send_text_message(sender, msg)
            # Return path for this message — no text-body fallthrough.
            continue

        indent_id = int(row["id"])
        log.info(
            "Indent found indent_id=%s indent_no=%s status=%s token=%s",
            indent_id,
            row["indent_no"],
            row["status"],
            approval_token,
        )
        # #region agent log
        _agent_dbg(
            "E",
            "whatsapp_webhook.py:process_indent_button_replies",
            "indent_found",
            {
                "indent_id": indent_id,
                "indent_no": row["indent_no"],
                "status": row["status"],
                "decision": decision,
            },
        )
        # #endregion

        ok, msg = _apply_whatsapp_decision(
            conn,
            indent_id,
            decision,
            decided_by_label=by_label,
            wa_message_id=inbound_id,
        )
        results.append(msg if ok else f"skip: {msg}")
        # #region agent log
        _agent_dbg(
            "E",
            "whatsapp_webhook.py:process_indent_button_replies",
            "indent_update_result",
            {"ok": ok, "msg": msg[:120], "decision": decision, "indent_id": indent_id},
        )
        # #endregion
        if ok:
            log.info(
                "Indent updated / approval completed indent_id=%s decision=%s "
                "by=%s message_id=%s at=%s",
                indent_id,
                decision,
                by_label,
                inbound_id,
                stamp,
            )
        else:
            log.info(
                "WhatsApp webhook skipped indent_id=%s reason=%s from=%s at=%s",
                indent_id,
                msg,
                sender,
                stamp,
            )
        if sender:
            wa.send_text_message(sender, msg)
        # Success or already-processed: done with this inbound message.
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

    # #region agent log
    _msg_summaries = []
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            for message in value.get("messages") or []:
                interactive = message.get("interactive") if isinstance(message.get("interactive"), dict) else {}
                button_reply = interactive.get("button_reply") if isinstance(interactive.get("button_reply"), dict) else {}
                button = message.get("button") if isinstance(message.get("button"), dict) else {}
                text_body = ""
                if isinstance(message.get("text"), dict):
                    text_body = str((message.get("text") or {}).get("body") or "")[:80]
                _msg_summaries.append(
                    {
                        "type": message.get("type"),
                        "has_interactive": bool(interactive),
                        "button_reply_id": str(button_reply.get("id") or "")[:80],
                        "button_reply_title": str(button_reply.get("title") or "")[:40],
                        "button_payload": str(button.get("payload") or button.get("id") or "")[:80],
                        "text_body": text_body,
                        "from": str(message.get("from") or "")[-4:],
                    }
                )
    _agent_dbg(
        "A",
        "whatsapp_webhook.py:handle_events_post",
        "webhook_post_received",
        {"message_count": len(_msg_summaries), "messages": _msg_summaries, "code_build": "token_button_only_v1"},
    )
    # #endregion

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
