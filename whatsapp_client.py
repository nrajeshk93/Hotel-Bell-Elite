"""WhatsApp Cloud API helpers for Hotel Bell Elite (shared WABA with Neeraj Textile)."""

from __future__ import annotations

import os
import re

import requests


def whatsapp_access_token() -> str:
    return (os.environ.get("WHATSAPP_ACCESS_TOKEN") or "").strip()


def whatsapp_phone_number_id() -> str:
    return (os.environ.get("WHATSAPP_PHONE_NUMBER_ID") or "").strip()


def whatsapp_graph_api_version() -> str:
    return (os.environ.get("WHATSAPP_GRAPH_API_VERSION") or "v21.0").strip()


def whatsapp_configured() -> bool:
    return bool(whatsapp_access_token() and whatsapp_phone_number_id())


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


def send_payload(payload: dict) -> tuple[bool, str, dict]:
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
        response = requests.post(graph_messages_url(), headers=headers, json=payload, timeout=30)
    except requests.RequestException as exc:
        return False, str(exc), {}
    if 200 <= response.status_code < 300:
        try:
            body = response.json()
        except ValueError:
            body = {}
        return True, "", body
    return False, (response.text or "")[:500], {}


def upload_media_file(file_path: str, mime_type: str = "application/pdf") -> tuple[bool, str, dict]:
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


def first_message_id(response_body: dict) -> str:
    messages = (response_body or {}).get("messages") or []
    if not messages:
        return ""
    return str(messages[0].get("id") or "").strip()
