"""Send bar (Irish Barrel) feedback invite via WhatsApp Meta template ``bar_feedback``.

Meta template (approved): ``bar_feedback``
  HEADER: IMAGE (HD bar feedback art)
  BODY: one variable — guest display name
  BUTTON: URL CTA ``Share Your Feedback`` → ``https://belleliteaccounts.com/f/{{1}}``

Env (optional overrides):
  WHATSAPP_BAR_FEEDBACK_TEMPLATE=bar_feedback_link
  WHATSAPP_BAR_FEEDBACK_TEMPLATE_LANGUAGE=en

Uses existing WHATSAPP_ACCESS_TOKEN / WHATSAPP_PHONE_NUMBER_ID. Live Meta HTTP is
gated by ``whatsapp_client.whatsapp_live_sends_allowed`` (DRY_RUN / TESTING).

Shares invite mint / URL-button / payload helpers with ``hotel_feedback_whatsapp``.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import whatsapp_client as wa
from db import get_db
from feedback import _public_feedback_url, create_feedback_invite
from hotel_feedback_whatsapp import (
    build_hotel_feedback_template_payload_shape,
    feedback_url_button_suffix,
    format_hotel_feedback_guest_name,
    resolve_hotel_feedback_mobile,
)

log = logging.getLogger(__name__)

DEFAULT_TEMPLATE_NAME = "bar_feedback_link"
DEFAULT_TEMPLATE_LANGUAGE = "en"
HEADER_IMAGE_REL = os.path.join("static", "bar_feedback_whatsapp_header.png")


def bar_feedback_template_config() -> tuple[str, str]:
    name = (
        os.environ.get("WHATSAPP_BAR_FEEDBACK_TEMPLATE") or DEFAULT_TEMPLATE_NAME
    ).strip()
    lang = (
        os.environ.get("WHATSAPP_BAR_FEEDBACK_TEMPLATE_LANGUAGE")
        or DEFAULT_TEMPLATE_LANGUAGE
    ).strip()
    return name or DEFAULT_TEMPLATE_NAME, lang or DEFAULT_TEMPLATE_LANGUAGE


def bar_feedback_header_image_path() -> str:
    """Absolute path to the HD PNG uploaded as the template IMAGE header."""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, HEADER_IMAGE_REL)


def send_bar_feedback_whatsapp(
    bill_snapshot: dict[str, Any],
    *,
    user_id=None,
    note: str = "",
) -> dict[str, Any]:
    """Mint a 24h bar feedback invite and send ``bar_feedback`` template.

    ``bill_snapshot`` should include guest display name + mobile from the POS
    invoice (``customer_name`` / ``mobile`` / ``mobile_country``).
    """
    data = bill_snapshot if isinstance(bill_snapshot, dict) else {}
    phone, mobile_err = resolve_hotel_feedback_mobile(data)
    if mobile_err:
        return {"ok": False, "error": mobile_err, "status": 400}

    guest_name = format_hotel_feedback_guest_name(data)
    template_name, template_lang = bar_feedback_template_config()
    location = str(
        data.get("location")
        or data.get("table")
        or data.get("table_label")
        or data.get("tableLabel")
        or data.get("table_number")
        or data.get("tableNumber")
        or ""
    ).strip()
    order_no = str(data.get("order_no") or data.get("orderNo") or "").strip()
    invoice_id = str(data.get("invoice_id") or data.get("invoiceId") or "").strip()
    note_clean = (note or str(data.get("note") or "")).strip()
    if not note_clean:
        bits = ["bar generate-invoice feedback"]
        if location:
            bits.append(f"table={location}")
        if order_no:
            bits.append(f"order={order_no}")
        if invoice_id:
            bits.append(f"invoice={invoice_id}")
        note_clean = " ".join(bits)

    image_path = bar_feedback_header_image_path()
    if not os.path.isfile(image_path):
        return {
            "ok": False,
            "error": "Bar feedback WhatsApp header image is missing on the server.",
            "status": 500,
            "image_path": image_path,
        }

    conn = get_db()
    try:
        invite = create_feedback_invite(
            conn,
            customer_name=guest_name,
            phone=phone,
            source="bar",
            outlet="bar",
            location=location[:80],
            note=note_clean[:500],
            user_id=user_id,
        )
    finally:
        conn.close()

    token = str(invite.get("token") or "").strip()
    share_url = str(invite.get("url") or "").strip() or _public_feedback_url(token)
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
