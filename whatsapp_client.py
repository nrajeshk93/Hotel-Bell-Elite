"""WhatsApp Cloud API helpers for Hotel Bell Elite (shared WABA with Neeraj Textile).

Outbound Cloud API "from" is the Meta ``phone_number_id`` in the URL path
(``WHATSAPP_PHONE_NUMBER_ID``), not digits in the HTTP body. Hotel Bell Elite
sends (POS invoice, PO, indent, hub, promotions) must use the phone number id
for **+91 96112 32344** (E.164 ``+919611232344`` / digits ``919611232344``).
"""

from __future__ import annotations

import logging
import os
import re
import time

import requests

log = logging.getLogger(__name__)

# Meta Cloud API phone_number_id for Hotel Bell Elite display number +91 96112 32344
# (discovered via Graph GET /{WABA_ID}/phone_numbers). Not a secret.
HBE_WHATSAPP_PHONE_NUMBER_ID = "1241737459022736"
HBE_WHATSAPP_SENDER_E164 = "+919611232344"
HBE_WHATSAPP_SENDER_DIGITS = "919611232344"

# Short-lived cache for GET /{phone_number_id} display-number verification.
_sender_display_cache: dict = {"phone_number_id": "", "digits": "", "ts": 0.0}
_SENDER_DISPLAY_CACHE_TTL_SEC = 300.0


def whatsapp_access_token() -> str:
    return (os.environ.get("WHATSAPP_ACCESS_TOKEN") or "").strip()


def whatsapp_phone_number_id() -> str:
    """Meta phone_number_id used as the Cloud API sender (URL path).

    Prefer ``WHATSAPP_PHONE_NUMBER_ID``. When unset, fall back to the known
    Hotel Bell Elite id for +91 96112 32344 (``HBE_WHATSAPP_PHONE_NUMBER_ID``).
    """
    configured = (os.environ.get("WHATSAPP_PHONE_NUMBER_ID") or "").strip()
    return configured or HBE_WHATSAPP_PHONE_NUMBER_ID


def whatsapp_sender_e164() -> str:
    """Expected sender E.164 for HBE (default ``+919611232344``).

    Set ``WHATSAPP_SENDER_E164`` to override. Empty string disables display-number
    mismatch checks (id-only mode). Use the default in production so sends refuse
    when the configured phone_number_id belongs to a different number.
    """
    raw = os.environ.get("WHATSAPP_SENDER_E164")
    if raw is None:
        return HBE_WHATSAPP_SENDER_E164
    return str(raw).strip()


def whatsapp_sender_digits() -> str:
    """Digits-only form of ``whatsapp_sender_e164()`` (e.g. ``919611232344``)."""
    e164 = whatsapp_sender_e164()
    if not e164:
        return ""
    return normalise_whatsapp_number(e164)


def whatsapp_waba_id() -> str:
    return (os.environ.get("WHATSAPP_WABA_ID") or "").strip()


def whatsapp_graph_api_version() -> str:
    return (os.environ.get("WHATSAPP_GRAPH_API_VERSION") or "v21.0").strip()


def whatsapp_configured() -> bool:
    return bool(whatsapp_access_token() and whatsapp_phone_number_id())


def whatsapp_templates_configured() -> bool:
    return bool(whatsapp_access_token() and whatsapp_waba_id())


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


def clear_sender_display_cache() -> None:
    """Reset cached Graph display-number lookup (tests / after env change)."""
    _sender_display_cache["phone_number_id"] = ""
    _sender_display_cache["digits"] = ""
    _sender_display_cache["ts"] = 0.0


def fetch_phone_number_display_digits(phone_number_id: str = "") -> tuple[bool, str, str]:
    """GET Meta phone number metadata; return (ok, digits_or_empty, error).

    On success ``digits`` is the normalised display number (no +). Does not
    print or return the access token. Soft-fails (ok=False) when token/id
    missing or Graph is unreachable — callers treat that as "cannot verify".
    """
    pnid = (phone_number_id or whatsapp_phone_number_id()).strip()
    token = whatsapp_access_token()
    if not pnid:
        return False, "", "WhatsApp phone number ID is not configured."
    if not token:
        return False, "", "WhatsApp access token is not configured."

    now = time.time()
    if (
        _sender_display_cache.get("phone_number_id") == pnid
        and (now - float(_sender_display_cache.get("ts") or 0)) < _SENDER_DISPLAY_CACHE_TTL_SEC
        and _sender_display_cache.get("digits")
    ):
        return True, str(_sender_display_cache["digits"]), ""

    url = (
        f"https://graph.facebook.com/{whatsapp_graph_api_version()}/"
        f"{pnid}"
    )
    headers = {"Authorization": f"Bearer {token}"}
    params = {"fields": "id,display_phone_number,verified_name"}
    try:
        response = requests.get(url, headers=headers, params=params, timeout=20)
    except requests.RequestException as exc:
        return False, "", str(exc)
    if not (200 <= response.status_code < 300):
        return False, "", (response.text or "")[:300]
    try:
        body = response.json()
    except ValueError:
        return False, "", "Invalid phone number metadata from Meta."
    display = str((body or {}).get("display_phone_number") or "").strip()
    digits = normalise_whatsapp_number(display)
    if not digits:
        return False, "", "Meta phone number has no display_phone_number."
    _sender_display_cache["phone_number_id"] = pnid
    _sender_display_cache["digits"] = digits
    _sender_display_cache["ts"] = now
    return True, digits, ""


def validate_configured_sender(*, verify_via_api: bool = True) -> tuple[bool, str]:
    """Ensure Cloud API sender id is usable and matches ``WHATSAPP_SENDER_E164``.

    Returns ``(True, "")`` when OK. When ``WHATSAPP_SENDER_E164`` is set and
    Graph can return the display number for ``WHATSAPP_PHONE_NUMBER_ID``, refuse
    if digits do not match (prevents HBE traffic going out as Neeraj Tex / etc.).
    If Graph cannot be reached, do not block solely on mismatch — still require
    a configured phone_number_id.
    """
    pnid = whatsapp_phone_number_id()
    if not pnid:
        return False, "WhatsApp phone number ID is not configured."
    expected = whatsapp_sender_digits()
    if not expected:
        return True, ""
    if not verify_via_api:
        return True, ""
    skip = (os.environ.get("WHATSAPP_SKIP_SENDER_VERIFY") or "").strip().lower()
    if skip in {"1", "true", "yes", "on"}:
        return True, ""
    ok, actual, err = fetch_phone_number_display_digits(pnid)
    if not ok:
        # Cannot verify — allow send; log once at warning for operators.
        log.warning(
            "WhatsApp sender E.164 check skipped (could not verify phone_number_id=%s): %s",
            pnid,
            err or "unknown",
        )
        return True, ""
    if actual != expected:
        return (
            False,
            (
                f"WhatsApp sender mismatch: phone_number_id {pnid} is {actual}, "
                f"but WHATSAPP_SENDER_E164 requires {expected} "
                f"(Hotel Bell Elite +91 96112 32344). "
                f"Set WHATSAPP_PHONE_NUMBER_ID={HBE_WHATSAPP_PHONE_NUMBER_ID}."
            ),
        )
    return True, ""


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


def _record_outbound_quota_send(payload: dict, response_body: dict) -> None:
    """Best-effort: count a successful live Cloud API message against the install limit."""
    try:
        from db import get_db, record_whatsapp_outbound_send

        phone = normalise_whatsapp_number((payload or {}).get("to") or "")
        msg_type = str((payload or {}).get("type") or "").strip().lower()
        wa_id = first_message_id(response_body or {})
        conn = get_db()
        try:
            conn.execute("PRAGMA busy_timeout=3000")
            record_whatsapp_outbound_send(
                conn,
                wa_message_id=wa_id,
                to_phone=phone,
                message_type=msg_type,
                source="send_payload",
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        log.exception("WhatsApp outbound quota record failed")


def _quota_exhausted_error(quota: dict) -> str:
    sent = int((quota or {}).get("sent") or 0)
    limit = int((quota or {}).get("limit") or 0)
    return (
        f"WhatsApp message limit reached ({sent}/{limit}). "
        "Contact support to increase the limit."
    )


def _check_outbound_quota_before_send() -> tuple[bool, str]:
    """Return (ok, error). Fail closed if the quota table cannot be read."""
    try:
        from db import get_db, whatsapp_outbound_quota

        conn = get_db()
        try:
            conn.execute("PRAGMA busy_timeout=3000")
            quota = whatsapp_outbound_quota(conn)
        finally:
            conn.close()
    except Exception:
        log.exception("WhatsApp outbound quota check failed")
        return False, "WhatsApp message limit could not be verified. Try again."
    if quota.get("exhausted"):
        return False, _quota_exhausted_error(quota)
    return True, ""


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
    sender_ok, sender_err = validate_configured_sender(verify_via_api=True)
    if not sender_ok:
        log.error(sender_err)
        return False, sender_err, {}
    quota_ok, quota_err = _check_outbound_quota_before_send()
    if not quota_ok:
        return False, quota_err, {}
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
        _record_outbound_quota_send(payload, body)
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
    sender_ok, sender_err = validate_configured_sender(verify_via_api=True)
    if not sender_ok:
        log.error(sender_err)
        return False, sender_err, {}
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


_BODY_VAR_RE = re.compile(r"\{\{\s*\d+\s*\}\}")


def _template_body_param_count(components) -> int:
    """Count body placeholders ({{n}} or example body_text slots)."""
    for comp in components or []:
        if not isinstance(comp, dict):
            continue
        if str(comp.get("type") or "").strip().upper() != "BODY":
            continue
        text = str(comp.get("text") or "")
        found = {m.group(0) for m in _BODY_VAR_RE.finditer(text)}
        if found:
            return len(found)
        example = comp.get("example") or {}
        if isinstance(example, dict):
            body_text = example.get("body_text") or []
            if body_text and isinstance(body_text, list) and body_text[0]:
                row = body_text[0]
                if isinstance(row, (list, tuple)):
                    return len(row)
        return 0
    return 0


def _template_needs_header_media(components) -> bool:
    for comp in components or []:
        if not isinstance(comp, dict):
            continue
        if str(comp.get("type") or "").strip().upper() != "HEADER":
            continue
        fmt = str(comp.get("format") or "").strip().upper()
        if fmt in {"IMAGE", "VIDEO", "DOCUMENT"}:
            return True
    return False


def _template_has_dynamic_buttons(components) -> bool:
    for comp in components or []:
        if not isinstance(comp, dict):
            continue
        if str(comp.get("type") or "").strip().upper() != "BUTTONS":
            continue
        for btn in comp.get("buttons") or []:
            if not isinstance(btn, dict):
                continue
            btn_type = str(btn.get("type") or "").strip().upper()
            if btn_type == "URL" and _BODY_VAR_RE.search(str(btn.get("url") or "")):
                return True
            if btn_type == "COPY_CODE":
                return True
    return False


def analyze_message_template(raw: dict) -> dict:
    """Normalize a Graph message_templates row for Promotion UI."""
    components = raw.get("components") or []
    if not isinstance(components, list):
        components = []
    body_params = _template_body_param_count(components)
    needs_header = _template_needs_header_media(components)
    has_dyn_buttons = _template_has_dynamic_buttons(components)
    sendable = (not needs_header) and (not has_dyn_buttons) and body_params <= 1
    block_reason = ""
    if needs_header:
        block_reason = "This template needs header media (image/video/document)."
    elif has_dyn_buttons:
        block_reason = "This template has dynamic button variables."
    elif body_params > 1:
        block_reason = "This template needs more than one body variable (v1 supports 0 or 1)."
    return {
        "name": str(raw.get("name") or "").strip(),
        "language": str(raw.get("language") or "").strip(),
        "status": str(raw.get("status") or "").strip().upper(),
        "category": str(raw.get("category") or "").strip(),
        "body_param_count": int(body_params),
        "needs_header_media": bool(needs_header),
        "has_dynamic_buttons": bool(has_dyn_buttons),
        "sendable": bool(sendable),
        "block_reason": block_reason,
    }


def list_approved_message_templates(*, force_refresh: bool = False) -> tuple[bool, str, list[dict]]:
    """Fetch APPROVED WhatsApp message templates for the configured WABA."""
    token = whatsapp_access_token()
    waba_id = whatsapp_waba_id()
    if not token:
        return False, "WhatsApp access token is not configured.", []
    if not waba_id:
        return False, "WhatsApp WABA ID is not configured.", []

    cache = getattr(list_approved_message_templates, "_cache", None)
    now_ts = __import__("time").time()
    if (
        not force_refresh
        and isinstance(cache, dict)
        and cache.get("waba_id") == waba_id
        and (now_ts - float(cache.get("ts") or 0)) < 300
        and isinstance(cache.get("items"), list)
    ):
        return True, "", list(cache["items"])

    headers = {"Authorization": f"Bearer {token}"}
    url = (
        f"https://graph.facebook.com/{whatsapp_graph_api_version()}/"
        f"{waba_id}/message_templates"
    )
    params = {
        "fields": "name,status,language,category,components",
        "limit": 100,
    }
    items: list[dict] = []
    next_url = url
    next_params = params
    try:
        while next_url:
            response = requests.get(
                next_url,
                headers=headers,
                params=next_params,
                timeout=30,
            )
            if not (200 <= response.status_code < 300):
                return False, (response.text or "")[:500], []
            try:
                body = response.json()
            except ValueError:
                return False, "Invalid template list response from Meta.", []
            for row in body.get("data") or []:
                if not isinstance(row, dict):
                    continue
                analyzed = analyze_message_template(row)
                if analyzed["status"] != "APPROVED":
                    continue
                if not analyzed["name"] or not analyzed["language"]:
                    continue
                items.append(analyzed)
            paging = body.get("paging") or {}
            next_url = str((paging.get("next") or "")).strip() or ""
            next_params = None
    except requests.RequestException as exc:
        return False, str(exc), []

    items.sort(key=lambda t: (t.get("name") or "", t.get("language") or ""))
    list_approved_message_templates._cache = {
        "waba_id": waba_id,
        "ts": now_ts,
        "items": list(items),
    }
    return True, "", items
