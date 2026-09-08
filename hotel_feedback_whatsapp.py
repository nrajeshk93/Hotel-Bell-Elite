"""Send hotel checkout feedback invite via WhatsApp Meta template ``hotel_feedback``.

Meta template (approved): ``hotel_feedback_link``
  HEADER: IMAGE (HD feedback art)
  BODY: one variable — guest display name with title (e.g. Mr Rajesh)
  BUTTON: URL CTA ``Share Your Feedback`` → ``https://belleliteaccounts.com/f/{{1}}``
          ({{1}} = Communication Hub invite token)

Env (optional overrides):
  WHATSAPP_HOTEL_FEEDBACK_TEMPLATE=hotel_feedback_link
  WHATSAPP_HOTEL_FEEDBACK_TEMPLATE_LANGUAGE=en

Uses existing WHATSAPP_ACCESS_TOKEN / WHATSAPP_PHONE_NUMBER_ID. Live Meta HTTP is
gated by ``whatsapp_client.whatsapp_live_sends_allowed`` (DRY_RUN / TESTING).
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any
from urllib.parse import urlparse

import whatsapp_client as wa
from db import get_db
from feedback import _public_feedback_url, create_feedback_invite

log = logging.getLogger(__name__)

DEFAULT_TEMPLATE_NAME = "hotel_feedback_link"
DEFAULT_TEMPLATE_LANGUAGE = "en"
HEADER_IMAGE_REL = os.path.join("static", "feedback_whatsapp_header.png")


def hotel_feedback_template_config() -> tuple[str, str]:
    name = (
        os.environ.get("WHATSAPP_HOTEL_FEEDBACK_TEMPLATE") or DEFAULT_TEMPLATE_NAME
    ).strip()
    lang = (
        os.environ.get("WHATSAPP_HOTEL_FEEDBACK_TEMPLATE_LANGUAGE")
        or DEFAULT_TEMPLATE_LANGUAGE
    ).strip()
    return name or DEFAULT_TEMPLATE_NAME, lang or DEFAULT_TEMPLATE_LANGUAGE


def feedback_header_image_path() -> str:
    """Absolute path to the HD PNG uploaded as the template IMAGE header."""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, HEADER_IMAGE_REL)


def format_hotel_feedback_guest_name(payload: dict[str, Any] | None) -> str:
    """Body {{1}} — check-in display name with Mr/Mrs (or Ms/Dr) title when known."""
    data = payload if isinstance(payload, dict) else {}
    explicit = str(
        data.get("customer_name")
        or data.get("guest_name")
        or data.get("guestName")
        or ""
    ).strip()
    title = str(data.get("title") or "").strip()
    first = str(data.get("first_name") or data.get("firstName") or "").strip()
    last = str(data.get("last_name") or data.get("lastName") or "").strip()
    if not explicit:
        explicit = " ".join(p for p in (title, first, last) if p).strip()
    if not explicit and (first or last):
        explicit = " ".join(p for p in (first, last) if p).strip()
    if not explicit:
        return "Guest"
    # If title is separate and not already prefixed on the display name, prepend it.
    title_norm = re.sub(r"\.+$", "", title).strip()
    if title_norm and not re.match(
        rf"^(Mr|Mrs|Ms|Miss|Dr|Mx)\.?\s+", explicit, flags=re.IGNORECASE
    ):
        title_map = {
            "mr": "Mr",
            "mrs": "Mrs",
            "ms": "Ms",
            "miss": "Ms",
            "dr": "Dr",
            "mx": "Mx",
        }
        pretty = title_map.get(title_norm.lower(), title_norm)
        explicit = f"{pretty} {explicit}".strip()
    return explicit[:200] or "Guest"


def resolve_hotel_feedback_mobile(payload: dict[str, Any] | None) -> tuple[str, str]:
    """Return (e164_digits, error). Prefer stay mobile + country."""
    data = payload if isinstance(payload, dict) else {}
    mobile = str(
        data.get("mobile") or data.get("phone") or data.get("customer_mobile") or ""
    ).strip()
    country = str(
        data.get("mobile_country")
        or data.get("mobileCountry")
        or data.get("country_code")
        or ""
    ).strip()
    if not mobile:
        return "", "Guest mobile number is missing. Update the stay mobile and try again."
    raw = mobile
    # Combine country dial code when mobile looks local (no leading + / country digits).
    if country and not mobile.startswith("+") and not re.match(r"^\+?\d{11,15}$", mobile):
        raw = f"{country}{mobile}"
    phone = wa.normalise_whatsapp_number(raw)
    if not phone:
        # Retry with mobile alone (normaliser already prefixes 91 for 10-digit IN).
        phone = wa.normalise_whatsapp_number(mobile)
    if not phone:
        return "", "Guest mobile number is missing or invalid."
    return phone, ""


def feedback_url_button_suffix(share_url: str, token: str = "") -> str:
    """Dynamic URL button text for Meta (suffix after the template's static base).

    Template URL is expected as ``https://belleliteaccounts.com/f/{{1}}``, so the
    parameter is the invite token. Falls back to parsing ``/f/<token>`` from the
    share URL when token is empty.
    """
    tok = str(token or "").strip()
    if tok:
        return tok
    raw = str(share_url or "").strip()
    if not raw:
        return ""
    try:
        path = urlparse(raw if "://" in raw else f"https://{raw}").path or ""
    except Exception:
        path = ""
    parts = [p for p in path.split("/") if p]
    if len(parts) >= 2 and parts[-2].lower() == "f":
        return parts[-1]
    if parts:
        return parts[-1]
    return raw


def build_hotel_feedback_template_payload_shape(
    *,
    phone: str,
    template_name: str,
    template_language: str,
    body_parameters: list[str],
    header_image_id: str = "",
    url_button_suffix: str = "",
) -> dict[str, Any]:
    """Meta Cloud API template payload shape (dry-run / tests)."""
    components: list[dict[str, Any]] = []
    if header_image_id:
        components.append(
            {
                "type": "header",
                "parameters": [
                    {
                        "type": "image",
                        "image": {"id": str(header_image_id)},
                    }
                ],
            }
        )
    if body_parameters:
        components.append(
            {
                "type": "body",
                "parameters": [{"type": "text", "text": str(v)} for v in body_parameters],
            }
        )
    suffix = str(url_button_suffix or "").strip()
    if suffix:
        components.append(
            {
                "type": "button",
                "sub_type": "url",
                "index": "0",
                "parameters": [{"type": "text", "text": suffix[:2000]}],
            }
        )
    payload: dict[str, Any] = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": phone,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": template_language},
        },
    }
    if components:
        payload["template"]["components"] = components
    return payload


def send_hotel_feedback_whatsapp(
    stay_snapshot: dict[str, Any],
    *,
    user_id=None,
    note: str = "",
) -> dict[str, Any]:
    """Mint a 24h hotel feedback invite and send the ``hotel_feedback`` template.

    ``stay_snapshot`` should include guest display name + mobile captured before
    checkout clears the stay (``customer_name`` / ``mobile`` / ``mobile_country``).
    """
    data = stay_snapshot if isinstance(stay_snapshot, dict) else {}
    phone, mobile_err = resolve_hotel_feedback_mobile(data)
    if mobile_err:
        return {"ok": False, "error": mobile_err, "status": 400}

    guest_name = format_hotel_feedback_guest_name(data)
    template_name, template_lang = hotel_feedback_template_config()
    outlet = str(data.get("outlet") or data.get("room_number") or data.get("roomNumber") or "").strip()
    room_id = str(data.get("room_id") or data.get("roomId") or "").strip()
    note_clean = (note or str(data.get("note") or "")).strip()
    if not note_clean:
        bits = ["hotel checkout feedback"]
        if room_id:
            bits.append(f"room={room_id}")
        if outlet:
            bits.append(f"#{outlet}")
        note_clean = " ".join(bits)

    image_path = feedback_header_image_path()
    if not os.path.isfile(image_path):
        return {
            "ok": False,
            "error": "Feedback WhatsApp header image is missing on the server.",
            "status": 500,
            "image_path": image_path,
        }

    conn = get_db()
    try:
        invite = create_feedback_invite(
            conn,
            customer_name=guest_name,
            phone=phone,
            source="hotel",
            outlet=outlet[:80],
            note=note_clean[:500],
            user_id=user_id,
        )
    finally:
        conn.close()

    token = str(invite.get("token") or "").strip()
    share_url = str(invite.get("url") or "").strip() or _public_feedback_url(token)
    # Always prefer production-style public URL helper (never localhost).
    if token:
        share_url = _public_feedback_url(token)
    button_suffix = feedback_url_button_suffix(share_url, token)
    body_params = [guest_name]
    payload_preview = build_hotel_feedback_template_payload_shape(
        phone=phone,
        template_name=template_name,
        template_language=template_lang,
        body_parameters=body_params,
        header_image_id="{{media_id}}",
        url_button_suffix=button_suffix,
    )

    live = wa.whatsapp_live_sends_allowed()
    if not live:
        return {
            "ok": True,
            "dry_run": True,
            "phone": phone,
            "guest_name": guest_name,
            "template_name": template_name,
            "template_language": template_lang,
            "template_params": body_params,
            "url_button_suffix": button_suffix,
            "invite": invite,
            "share_url": share_url,
            "image_path": image_path,
            "image_bytes_len": os.path.getsize(image_path),
            "payload": payload_preview,
            "send_path": "dry_run",
        }

    if not wa.whatsapp_configured():
        return {
            "ok": False,
            "error": (
                "WhatsApp API is not configured. "
                "Set WHATSAPP_ACCESS_TOKEN and WHATSAPP_PHONE_NUMBER_ID."
            ),
            "status": 400,
            "invite": invite,
            "share_url": share_url,
            "template_name": template_name,
            "template_params": body_params,
        }

    ok_up, err_up, body_up = wa.upload_media_file(image_path, "image/png")
    media_id = ""
    if isinstance(body_up, dict):
        media_id = str(body_up.get("id") or "").strip()
    if not (ok_up and media_id):
        return {
            "ok": False,
            "error": err_up or "Could not upload feedback image to WhatsApp.",
            "status": 502,
            "invite": invite,
            "share_url": share_url,
            "template_name": template_name,
            "template_params": body_params,
        }

    ok, err, result = wa.send_template_message(
        phone,
        template_name,
        template_lang,
        body_parameters=body_params,
        header_image_id=media_id,
        url_button_parameters=button_suffix,
    )
    if not ok:
        return {
            "ok": False,
            "error": err or "WhatsApp send failed.",
            "status": 502,
            "invite": invite,
            "share_url": share_url,
            "template_name": template_name,
            "template_params": body_params,
            "media_id": media_id,
            "url_button_suffix": button_suffix,
        }

    return {
        "ok": True,
        "dry_run": False,
        "phone": phone,
        "guest_name": guest_name,
        "template_name": template_name,
        "template_language": template_lang,
        "template_params": body_params,
        "url_button_suffix": button_suffix,
        "invite": invite,
        "share_url": share_url,
        "media_id": media_id,
        "wa_message_id": wa.first_message_id(result) if isinstance(result, dict) else "",
        "link_sent": True,
        "link_error": "",
        "link_wa_message_id": "",
        "payload": build_hotel_feedback_template_payload_shape(
            phone=phone,
            template_name=template_name,
            template_language=template_lang,
            body_parameters=body_params,
            header_image_id=media_id,
            url_button_suffix=button_suffix,
        ),
        "send_path": "template_url_button",
    }
