"""WhatsApp Cloud API helpers for Hotel Bell Elite (shared WABA with Neeraj Textile)."""

from __future__ import annotations

import logging
import os
import re

import requests

log = logging.getLogger(__name__)


def whatsapp_access_token() -> str:
    return (os.environ.get("WHATSAPP_ACCESS_TOKEN") or "").strip()


def whatsapp_phone_number_id() -> str:
    return (os.environ.get("WHATSAPP_PHONE_NUMBER_ID") or "").strip()


def whatsapp_graph_api_version() -> str:
    return (os.environ.get("WHATSAPP_GRAPH_API_VERSION") or "v21.0").strip()


def whatsapp_configured() -> bool:
    return bool(whatsapp_access_token() and whatsapp_phone_number_id())


def whatsapp_live_sends_allowed() -> bool:
    """Gate real Meta/WhatsApp HTTP calls.

    Live sends are blocked when:
    - ``WHATSAPP_DRY_RUN`` is truthy, or
    - Flask ``TESTING`` is on (unless ``WHATSAPP_ALLOW_IN_TESTS=1``).

    This prevents unit/integration tests that create pending indents from
    burning WhatsApp budget when ``.env`` has real credentials loaded.
    """
    dry = (os.environ.get("WHATSAPP_DRY_RUN") or "").strip().lower()
    if dry in {"1", "true", "yes", "on"}:
        return False
    allow_tests = (os.environ.get("WHATSAPP_ALLOW_IN_TESTS") or "").strip().lower()
    if allow_tests in {"1", "true", "yes", "on"}:
        return True
    try:
        from flask import current_app, has_app_context

        if has_app_context() and current_app.config.get("TESTING"):
            return False
    except Exception:
        pass
    return True


def _refuse_live_send(action: str) -> tuple[bool, str, dict]:
    msg = f"WhatsApp live send blocked ({action})."
    log.warning(msg)
    return False, msg, {}


def normalise_whatsapp_number(value) -> str:
    raw = str(value or "").strip()
    if re.fullmatch(r"\d+\.0+", raw):
        raw = raw.split(".", 1)[0]
    digits = re.sub(r"\D+", "", raw)
    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) == 10:
        digits = "91" + digits
    if not (8 <= len(digits) <= 15):
        return ""
    return digits


def parse_whatsapp_recipients(raw_text) -> list[str]:
    recipients = []
    seen = set()
    for part in re.split(r"[\s,;]+", str(raw_text or "").strip()):
        phone = normalise_whatsapp_number(part)
        if not phone or phone in seen:
            continue
        seen.add(phone)
        recipients.append(phone)
    return recipients


def graph_messages_url() -> str:
    return (
        f"https://graph.facebook.com/{whatsapp_graph_api_version()}/"
        f"{whatsapp_phone_number_id()}/messages"
    )


def first_message_id(response_body: dict) -> str:
    messages = (response_body or {}).get("messages") or []
    if not messages:
        # Some Graph responses nest under "message" singular.
        single = (response_body or {}).get("message") or {}
        if isinstance(single, dict):
            return str(single.get("id") or "").strip()
        return ""
    first = messages[0] if isinstance(messages[0], dict) else {}
    return str(first.get("id") or "").strip()


def first_message_status(response_body: dict) -> str:
    """Meta Cloud API immediate status (usually ``accepted``) from a send response."""
    messages = (response_body or {}).get("messages") or []
    if not messages or not isinstance(messages[0], dict):
        return ""
    return str(messages[0].get("message_status") or "").strip().lower()


def _hub_preview_from_payload(payload: dict) -> tuple[str, str]:
    """Return (message_type, body preview) for Communication Hub mirroring."""
    msg_type = str((payload or {}).get("type") or "text").strip().lower() or "text"
    if msg_type == "text":
        body = str(((payload.get("text") or {}) if isinstance(payload.get("text"), dict) else {}).get("body") or "")
        return "text", body
    if msg_type == "template":
        tpl = payload.get("template") if isinstance(payload.get("template"), dict) else {}
        name = str((tpl or {}).get("name") or "template").strip() or "template"
        parts = [f"Template: {name}"]
        for component in (tpl or {}).get("components") or []:
            if not isinstance(component, dict):
                continue
            if str(component.get("type") or "").lower() != "body":
                continue
            for param in component.get("parameters") or []:
                if not isinstance(param, dict):
                    continue
                text = str(param.get("text") or "").strip()
                if text:
                    parts.append(text)
        return "template", "\n".join(parts)
    if msg_type == "interactive":
        interactive = payload.get("interactive") if isinstance(payload.get("interactive"), dict) else {}
        body = ""
        body_obj = (interactive or {}).get("body")
        if isinstance(body_obj, dict):
            body = str(body_obj.get("text") or "")
        return "other", body
    if msg_type == "image":
        image = payload.get("image") if isinstance(payload.get("image"), dict) else {}
        return "image", str((image or {}).get("caption") or "").strip() or "Photo"
    if msg_type == "document":
        document = payload.get("document") if isinstance(payload.get("document"), dict) else {}
        name = str((document or {}).get("filename") or "").strip()
        caption = str((document or {}).get("caption") or "").strip()
        return "document", caption or name or "Document"
    return msg_type if msg_type in {"image", "document", "audio", "text", "template"} else "other", msg_type.title()


def _mirror_outbound_to_hub(payload: dict, response_body: dict) -> None:
    """Best-effort: every successful Cloud API send appears in Communication Hub."""
    try:
        phone = normalise_whatsapp_number((payload or {}).get("to") or "")
        if not phone:
            return
        msg_type, body = _hub_preview_from_payload(payload or {})
        wa_id = first_message_id(response_body or {})
        media_filename = ""
        if msg_type == "document":
            document = payload.get("document") if isinstance(payload.get("document"), dict) else {}
            media_filename = str((document or {}).get("filename") or "").strip()
        elif msg_type == "image":
            media_filename = "Photo"
        from communication_hub import record_outbound_hub_message
        from db import get_db

        conn = get_db()
        try:
            # Fail fast if another request still holds the DB (e.g. caller forgot
            # to commit before Meta HTTP). Callers also write hub rows themselves.
            conn.execute("PRAGMA busy_timeout=3000")
            record_outbound_hub_message(
                conn,
                phone,
                body or msg_type,
                wa_message_id=wa_id,
                status="sent",
                message_type=msg_type,
                media_filename=media_filename,
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        log.exception("Communication Hub mirror of WhatsApp send failed")


def send_payload(payload: dict) -> tuple[bool, str, dict]:
    """POST one WhatsApp Cloud message. No automatic retries (avoids send storms)."""
    if not whatsapp_live_sends_allowed():
        return _refuse_live_send("messages")
    token = whatsapp_access_token()
    phone_number_id = whatsapp_phone_number_id()
    if not token:
        return False, "WhatsApp access token is not configured.", {}
    if not phone_number_id:
        return False, "WhatsApp phone number ID is not configured.", {}
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    try:
        # Explicitly no Session retry adapter — a single intentional send only.
        response = requests.post(graph_messages_url(), headers=headers, json=payload, timeout=30)
    except requests.RequestException as exc:
        return False, str(exc), {}
    if 200 <= response.status_code < 300:
        try:
            body = response.json()
        except ValueError:
            body = {}
        _mirror_outbound_to_hub(payload, body)
        return True, "", body
    return False, (response.text or "")[:500], {}


def upload_media_file(file_path: str, mime_type: str = "application/pdf") -> tuple[bool, str, dict]:
    if not whatsapp_live_sends_allowed():
        return _refuse_live_send("media_upload")
    token = whatsapp_access_token()
    phone_number_id = whatsapp_phone_number_id()
    if not token or not phone_number_id:
        return False, "WhatsApp API is not configured.", {}
    url = (
        f"https://graph.facebook.com/{whatsapp_graph_api_version()}/"
        f"{phone_number_id}/media"
    )
    try:
        with open(file_path, "rb") as media_file:
            response = requests.post(
                url,
                headers={"Authorization": f"Bearer {token}"},
                data={"messaging_product": "whatsapp", "type": mime_type},
                files={"file": (os.path.basename(file_path), media_file, mime_type)},
                timeout=60,
            )
    except OSError as exc:
        return False, str(exc), {}
    except requests.RequestException as exc:
        return False, str(exc), {}
    if 200 <= response.status_code < 300:
        try:
            return True, "", response.json()
        except ValueError:
            return True, "", {}
    return False, (response.text or "")[:500], {}


def send_template_message(
    phone: str,
    template_name: str,
    template_language: str,
    body_parameters=None,
    *,
    header_document_id: str = "",
    header_document_filename: str = "",
    header_image_id: str = "",
) -> tuple[bool, str, dict]:
    """Send a WhatsApp template. Buttons are defined on the Meta template itself."""
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": phone,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": template_language},
        },
    }
    components = []
    if header_document_id:
        document = {"id": str(header_document_id)}
        if header_document_filename:
            document["filename"] = str(header_document_filename)[:240]
        components.append({
            "type": "header",
            "parameters": [{"type": "document", "document": document}],
        })
    elif header_image_id:
        components.append({
            "type": "header",
            "parameters": [{"type": "image", "image": {"id": str(header_image_id)}}],
        })
    if body_parameters:
        if isinstance(body_parameters, dict):
            body_params = [
                {
                    "type": "text",
                    "parameter_name": str(name),
                    "text": str(value),
                }
                for name, value in body_parameters.items()
            ]
        else:
            body_params = [{"type": "text", "text": str(value)} for value in body_parameters]
        components.append({"type": "body", "parameters": body_params})
    if components:
        payload["template"]["components"] = components
    return send_payload(payload)


def send_text_message(phone: str, text: str) -> tuple[bool, str, dict]:
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": phone,
        "type": "text",
        "text": {"preview_url": False, "body": str(text or "")[:4096]},
    }
    return send_payload(payload)


def send_media_message(
    phone: str,
    *,
    media_id: str,
    media_type: str = "document",
    filename: str = "",
    caption: str = "",
) -> tuple[bool, str, dict]:
    """Send an uploaded WhatsApp media message (image or document)."""
    kind = "image" if str(media_type or "").lower() == "image" else "document"
    media_obj = {"id": str(media_id or "").strip()}
    if not media_obj["id"]:
        return False, "Media id is required.", {}
    cap = str(caption or "").strip()
    if cap:
        media_obj["caption"] = cap[:1024]
    if kind == "document" and filename:
        media_obj["filename"] = str(filename)[:240]
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": phone,
        "type": kind,
        kind: media_obj,
    }
    return send_payload(payload)


def send_interactive_buttons(
    phone: str,
    body_text: str,
    buttons: list[tuple[str, str]],
    *,
    header_document_id: str = "",
    header_document_filename: str = "",
) -> tuple[bool, str, dict]:
    """Send an interactive reply-button message.

    ``buttons`` is a list of ``(button_id, title)`` pairs (max 3). Button ids are
    opaque payloads returned as ``button_reply.id`` on webhook clicks.

    Optional ``header_document_id`` attaches a PDF/document in the same message
    (WhatsApp interactive header), so body + buttons + file are one bubble.
    """
    reply_buttons = []
    for button_id, title in (buttons or [])[:3]:
        bid = str(button_id or "").strip()[:256]
        label = str(title or "").strip()[:20]
        if not bid or not label:
            continue
        reply_buttons.append({
            "type": "reply",
            "reply": {"id": bid, "title": label},
        })
    if not reply_buttons:
        return False, "No interactive buttons provided.", {}
    interactive: dict = {
        "type": "button",
        "body": {"text": str(body_text or "")[:1024]},
        "action": {"buttons": reply_buttons},
    }
    media_id = str(header_document_id or "").strip()
    if media_id:
        document = {"id": media_id}
        fname = str(header_document_filename or "").strip()
        if fname:
            document["filename"] = fname[:240]
        interactive["header"] = {"type": "document", "document": document}
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": phone,
        "type": "interactive",
        "interactive": interactive,
    }
    return send_payload(payload)
