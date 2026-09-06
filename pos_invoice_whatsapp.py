"""Send restaurant/bar POS invoices via WhatsApp Cloud API.

Meta template (approved): ``hotel_bell_elite_invoice``
  HEADER: DOCUMENT (PDF)
  BODY (exact text that must be approved in Meta Business Manager — blank
  lines and WhatsApp bold ``*…*`` are part of the template, not the code):

    Dear {{1}},

    Thank you for dining at *{{2}}*.

    Invoice: *{{3}}*

    Amount: *₹{{4}}*

    We look forward to serving you again!

  Body params supplied by code (4 slots; never put the whole letter in one var):
    {{1}} guest first/name only (e.g. Rajesh)
    {{2}} brand display title case (e.g. Spice Multicuisine)
    {{3}} invoice / order_no
    {{4}} amount digits only with thousands separators (e.g. 6,362.00) —
         template already has ₹ inside the bold markers

  See ``docs/whatsapp_pos_invoice_template.md``. Meta templates cannot be
  synced from this repo — update the approved body in Business Manager.
  If Graph shows this template as PENDING, guest bubble text still uses the
  last APPROVED body until Meta finishes review (PDF header can already be fine).

Env (optional overrides; defaults match the approved Meta template):
  WHATSAPP_POS_INVOICE_TEMPLATE=hotel_bell_elite_invoice
  WHATSAPP_POS_INVOICE_TEMPLATE_LANGUAGE=en

Uses existing WHATSAPP_ACCESS_TOKEN / WHATSAPP_PHONE_NUMBER_ID. Sender must be
Hotel Bell Elite **+91 96112 32344** (phone_number_id ``1241737459022736``;
optional ``WHATSAPP_SENDER_E164=+919611232344``). Live Meta HTTP is gated by
``whatsapp_client.whatsapp_live_sends_allowed`` (DRY_RUN / TESTING).
"""

from __future__ import annotations

import logging
import os
import tempfile
from typing import Any

import whatsapp_client as wa
from pos_invoice_pdf import build_pos_invoice_pdf, pos_invoice_pdf_filename

log = logging.getLogger(__name__)

DEFAULT_TEMPLATE_NAME = "hotel_bell_elite_invoice"
DEFAULT_TEMPLATE_LANGUAGE = "en"


def pos_invoice_template_config() -> tuple[str, str]:
    name = (os.environ.get("WHATSAPP_POS_INVOICE_TEMPLATE") or DEFAULT_TEMPLATE_NAME).strip()
    lang = (
        os.environ.get("WHATSAPP_POS_INVOICE_TEMPLATE_LANGUAGE") or DEFAULT_TEMPLATE_LANGUAGE
    ).strip()
    return name or DEFAULT_TEMPLATE_NAME, lang or DEFAULT_TEMPLATE_LANGUAGE


def format_pos_invoice_guest_name(value) -> str:
    """Body {{1}} — first name / first token only for ``Dear {{1}},``."""
    raw = str(value or "").strip()
    if not raw:
        return "Guest"
    # Take the first whitespace-separated token; drop trailing commas.
    first = raw.replace(",", " ").split()[0].strip()
    return first or "Guest"


def format_pos_invoice_brand_display(value) -> str:
    """Body {{2}} — brand for WhatsApp; title case, not ALL CAPS dump.

    Receipt config stores thermal ALL CAPS names (``SPICE MULTICUISINE``);
    WhatsApp copy should read like ``Spice Multicuisine`` / ``Irish Barrel
    House Bar``. Already mixed-case brands are still title-cased for
    consistency. Known display overrides win when the ALL CAPS form matches.
    """
    raw = str(value or "").strip() or "Hotel Bell Elite"
    known = {
        "SPICE MULTICUISINE": "Spice Multicuisine",
        "IRISH BARREL HOUSE BAR": "Irish Barrel House Bar",
        "HOTEL BELL ELITE": "Hotel Bell Elite",
    }
    key = " ".join(raw.upper().split())
    if key in known:
        return known[key]
    # Title-case word-by-word; collapse internal whitespace.
    return " ".join(part.capitalize() for part in raw.split())


def format_pos_invoice_amount(value) -> str:
    """Body {{4}} — numeric amount only; template text already includes ₹."""
    try:
        n = float(value or 0)
    except (TypeError, ValueError):
        n = 0.0
    return f"{n:,.2f}"


def build_pos_invoice_template_params(
    invoice: dict[str, Any],
    *,
    business_name: str = "",
) -> list[str]:
    """Positional body params matching Meta template hotel_bell_elite_invoice.

    Returns exactly four strings: guest, brand, invoice no, amount (no ₹).
    Bold markers and currency glyph live in the approved Meta template body.
    """
    guest = format_pos_invoice_guest_name((invoice or {}).get("customer_name"))
    outlet = format_pos_invoice_brand_display(business_name)
    order_no = str((invoice or {}).get("order_no") or (invoice or {}).get("id") or "").strip() or "—"
    amount = format_pos_invoice_amount((invoice or {}).get("grand_total"))
    return [guest, outlet, order_no, amount]


def resolve_pos_invoice_mobile(invoice: dict[str, Any]) -> tuple[str, str]:
    """Return (e164_digits, error). Error is set when mobile is missing/invalid."""
    raw = str((invoice or {}).get("customer_mobile") or "").strip()
    if not raw:
        return "", "Customer mobile number is required to send the invoice on WhatsApp."
    phone = wa.normalise_whatsapp_number(raw)
    if not phone:
        return "", "Customer mobile number is missing or invalid."
    return phone, ""


def build_template_send_payload_shape(
    *,
    phone: str,
    template_name: str,
    template_language: str,
    body_parameters: list[str],
    header_document_id: str = "",
    header_document_filename: str = "",
) -> dict[str, Any]:
    """Meta Cloud API template payload shape (for dry-run / tests)."""
    components: list[dict[str, Any]] = []
    if header_document_id:
        document: dict[str, Any] = {"id": str(header_document_id)}
        if header_document_filename:
            document["filename"] = str(header_document_filename)[:240]
        components.append(
            {
                "type": "header",
                "parameters": [{"type": "document", "document": document}],
            }
        )
    if body_parameters:
        components.append(
            {
                "type": "body",
                "parameters": [{"type": "text", "text": str(v)} for v in body_parameters],
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


def send_pos_invoice_whatsapp(
    invoice: dict[str, Any],
    *,
    business_name: str = "",
    address: str = "",
    gst: str = "",
    fssai: str = "",
    logo_url: str = "",
    user_label: str = "",
    outlet: str = "",
) -> dict[str, Any]:
    """Send one POS invoice via the hotel_bell_elite_invoice template.

    Returns a dict with at least ``ok`` (bool). On failure includes ``error`` and
    usually ``status`` (HTTP-ish code for the Flask layer).
    """
    inv = invoice if isinstance(invoice, dict) else {}
    if not inv.get("id"):
        return {"ok": False, "error": "Invoice not found.", "status": 404}

    bill_sent = bool(inv.get("customer_bill_sent"))
    status = str(inv.get("status") or "open").strip().lower() or "open"
    if not bill_sent and status != "closed":
        return {
            "ok": False,
            "error": "Generate the invoice before sending it on WhatsApp.",
            "status": 400,
        }

    phone, mobile_err = resolve_pos_invoice_mobile(inv)
    if mobile_err:
        return {"ok": False, "error": mobile_err, "status": 400}

    template_name, template_lang = pos_invoice_template_config()
    body_params = build_pos_invoice_template_params(inv, business_name=business_name)
    pdf_name = pos_invoice_pdf_filename(str(inv.get("order_no") or ""), inv.get("id"))
    try:
        pdf_bytes = build_pos_invoice_pdf(
            inv,
            business_name=business_name,
            address=address,
            gst=gst,
            fssai=fssai,
            logo_url=logo_url,
            user_label=user_label,
            outlet=outlet or str(inv.get("outlet") or ""),
        )
    except Exception as exc:
        log.exception("POS invoice PDF build failed invoice_id=%s", inv.get("id"))
        return {
            "ok": False,
            "error": f"Could not build invoice PDF: {exc}",
            "status": 500,
        }

    payload_preview = build_template_send_payload_shape(
        phone=phone,
        template_name=template_name,
        template_language=template_lang,
        body_parameters=body_params,
        header_document_id="{{media_id}}",
        header_document_filename=pdf_name,
    )

    live = wa.whatsapp_live_sends_allowed()
    if not live:
        return {
            "ok": True,
            "dry_run": True,
            "phone": phone,
            "template_name": template_name,
            "template_language": template_lang,
            "template_params": body_params,
            "pdf_name": pdf_name,
            "pdf_bytes_len": len(pdf_bytes),
            "payload": payload_preview,
            "send_path": "dry_run",
        }

    if not wa.whatsapp_configured():
        return {
            "ok": False,
            "error": "WhatsApp API is not configured. Set WHATSAPP_ACCESS_TOKEN and WHATSAPP_PHONE_NUMBER_ID.",
            "status": 400,
            "template_name": template_name,
            "template_params": body_params,
        }

    media_id = ""
    tmp_path = ""
    try:
        fd, tmp_path = tempfile.mkstemp(suffix=".pdf")
        with os.fdopen(fd, "wb") as handle:
            handle.write(pdf_bytes)
        ok_up, err_up, body_up = wa.upload_media_file(tmp_path, "application/pdf")
        if isinstance(body_up, dict):
            media_id = str(body_up.get("id") or "").strip()
        if not (ok_up and media_id):
            return {
                "ok": False,
                "error": err_up or "Could not upload invoice PDF to WhatsApp.",
                "status": 502,
                "template_name": template_name,
                "template_params": body_params,
            }
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    ok, err, result = wa.send_template_message(
        phone,
        template_name,
        template_lang,
        body_parameters=body_params,
        header_document_id=media_id,
        header_document_filename=pdf_name,
    )
    if not ok:
        return {
            "ok": False,
            "error": err or "WhatsApp send failed.",
            "status": 502,
            "template_name": template_name,
            "template_params": body_params,
            "media_id": media_id,
        }

    return {
        "ok": True,
        "dry_run": False,
        "phone": phone,
        "template_name": template_name,
        "template_language": template_lang,
        "template_params": body_params,
        "pdf_name": pdf_name,
        "media_id": media_id,
        "wa_message_id": wa.first_message_id(result) if isinstance(result, dict) else "",
        "payload": build_template_send_payload_shape(
            phone=phone,
            template_name=template_name,
            template_language=template_lang,
            body_parameters=body_params,
            header_document_id=media_id,
            header_document_filename=pdf_name,
        ),
        "send_path": "template",
    }
