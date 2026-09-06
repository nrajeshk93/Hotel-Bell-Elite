"""Generate a POS invoice PDF for WhatsApp document-header templates.

Layout source of truth: the printed restaurant/bar customer bill built by
``static/pos_customer_bill.js`` → ``buildSpiceCustomerBillHtml`` (same HTML the
POS Print button / Hotel Print Agent invoice path uses via
``static/pos_invoice.js`` → ``printCustomerBill``).

Restaurant and Bar share that thermal Spice layout; branding (logo, name,
address, GST, FSSAI, user label) comes from the POS receipt config.
"""

from __future__ import annotations

import io
import os
import re
from datetime import datetime
from typing import Any

_ROOT = os.path.dirname(os.path.abspath(__file__))

# Mirrors static/pos_customer_bill.js DEFAULT_RECEIPT_CONFIG / BAR_RECEIPT_CONFIG.
_DEFAULT_RECEIPT = {
    "business_name": "SPICE MULTICUISINE",
    "address": "Gurudwara Lane, Aberdeen bazar, Sri Vijaya Puram, Andaman & Nicobar 744101",
    "gst": "35AANFH8592H1ZS",
    "fssai": "12922101000132",
    "logo_url": "/static/pos/spice-receipt-logo.jpg",
    "user_label": "RESTAURANT",
}
_BAR_RECEIPT = {
    "business_name": "IRISH BARREL HOUSE BAR",
    "address": "Gurudwara Lane, Aberdeen bazar, Sri Vijaya Puram, Andaman & Nicobar 744101",
    "gst": "35AANFH8592H1ZS",
    "fssai": "12922101000132",
    "logo_url": "/static/pos/irish-barrel-house-logo.png",
    "user_label": "BAR",
}

_GST_NUMBER_CORRECTIONS = {
    "35AAANFH8592H1ZS": "35AANFH8592H1ZS",
}

_DEFAULT_CGST_PCT = 2.5
_DEFAULT_UGST_PCT = 2.5
_DEFAULT_VAT_PCT = 10.0


def _money_thermal(value) -> str:
    """Match formatThermalAmount — two decimal places, no currency glyph."""
    try:
        n = float(value or 0)
    except (TypeError, ValueError):
        n = 0.0
    n = round(n * 100) / 100
    return f"{n:.2f}"


def _qty(value) -> str:
    try:
        n = float(value or 0)
    except (TypeError, ValueError):
        return "0"
    if abs(n - round(n)) < 0.0001:
        return str(int(round(n)))
    return f"{n:g}"


def _esc(text) -> str:
    return (
        str(text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _normalize_gst(value: str, fallback: str = "") -> str:
    gst = str(value if value is not None else "").strip() or str(fallback or "").strip()
    return _GST_NUMBER_CORRECTIONS.get(gst, gst)


def is_nill_series_order_no(order_no: str) -> bool:
    return bool(re.match(r"^(SPC|INV)/\d{2}-\d{2}/Nill/\d+$", str(order_no or "").strip(), re.I))


def _format_spice_date(value) -> str:
    """Match formatSpiceDate: ``5-Sep-2026 12:00 PM``."""
    raw = str(value or "").strip()
    dt = None
    if raw:
        for fmt, chunk_len in (
            ("%Y-%m-%d %H:%M:%S", 19),
            ("%Y-%m-%d %H:%M", 16),
            ("%Y-%m-%dT%H:%M:%S", 19),
            ("%Y-%m-%d", 10),
        ):
            piece = raw[:chunk_len]
            try:
                dt = datetime.strptime(piece, fmt)
                break
            except ValueError:
                continue
    if dt is None:
        dt = datetime.now()
    h = dt.hour
    ap = "PM" if h >= 12 else "AM"
    h12 = h % 12 or 12
    return f"{dt.day}-{dt.strftime('%b')}-{dt.year} {h12}:{dt.minute:02d} {ap}"


def _format_tax_pct(rate_frac_or_pct, *, as_fraction: bool = True) -> str:
    """Match formatBillTaxPct — trim trailing zeros."""
    try:
        n = float(rate_frac_or_pct or 0)
    except (TypeError, ValueError):
        n = 0.0
    pct = n * 100.0 if as_fraction else n
    if pct < 0 or pct != pct:  # NaN
        pct = 0.0
    pct = round(pct * 1000) / 1000
    text = f"{pct:g}" if abs(pct - round(pct)) > 1e-9 else str(int(round(pct)))
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _line_merge_key(line: dict[str, Any]) -> str:
    menu_id = line.get("menu_item_id")
    if menu_id is None:
        menu_id = line.get("menuId")
    name = re.sub(r"\s+", " ", str(line.get("name") or "")).strip().lower()
    variant = re.sub(r"\s+", " ", str(line.get("variant") or "")).strip().lower()
    try:
        rate = round(float(line.get("rate") or 0) * 100) / 100
    except (TypeError, ValueError):
        rate = 0.0
    return f"{'' if menu_id is None else menu_id}|{name}|{variant}|{rate}"


def _group_bill_lines(lines: list) -> list[dict[str, Any]]:
    """Match groupBillLines in pos_customer_bill.js."""
    out: list[dict[str, Any]] = []
    index: dict[str, int] = {}
    for line in lines or []:
        if not isinstance(line, dict):
            continue
        key = _line_merge_key(line)
        try:
            qty = float(line.get("qty") if line.get("qty") is not None else line.get("quantity") or 0)
        except (TypeError, ValueError):
            qty = 0.0
        rate = line.get("rate")
        if rate is None:
            rate = line.get("unit_price")
        try:
            rate_n = float(rate or 0)
        except (TypeError, ValueError):
            rate_n = 0.0
        if line.get("line_total") is not None:
            try:
                add_total = float(line.get("line_total") or 0)
            except (TypeError, ValueError):
                add_total = rate_n * qty
        elif line.get("amount") is not None:
            try:
                add_total = float(line.get("amount") or 0)
            except (TypeError, ValueError):
                add_total = rate_n * qty
        else:
            add_total = rate_n * qty
        if key in index:
            target = out[index[key]]
            target["qty"] = float(target.get("qty") or 0) + qty
            target["line_total"] = float(target.get("line_total") or 0) + add_total
        else:
            index[key] = len(out)
            out.append(
                {
                    "name": str(line.get("name") or "").strip() or "Item",
                    "variant": line.get("variant"),
                    "rate": rate_n,
                    "qty": qty,
                    "line_total": add_total,
                }
            )
    return out


def _resolve_logo_path(logo_url: str = "", outlet: str = "") -> str:
    candidates = []
    url = str(logo_url or "").strip()
    if url.startswith("/static/"):
        candidates.append(os.path.join(_ROOT, url.lstrip("/")))
    elif url and not url.startswith("http"):
        candidates.append(url if os.path.isabs(url) else os.path.join(_ROOT, url))
    key = str(outlet or "").strip().lower()
    fallback = (
        "static/pos/irish-barrel-house-logo.png"
        if key == "bar"
        else "static/pos/spice-receipt-logo.jpg"
    )
    candidates.append(os.path.join(_ROOT, fallback))
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return ""


def _receipt_defaults(outlet: str = "") -> dict[str, str]:
    return dict(_BAR_RECEIPT if str(outlet or "").strip().lower() == "bar" else _DEFAULT_RECEIPT)


def _resolve_user_label(invoice: dict[str, Any], user_label: str = "", cfg_label: str = "") -> str:
    from_arg = str(user_label or "").strip()
    if from_arg and not re.match(r"^(restaurant|bar)$", from_arg, re.I):
        return from_arg
    from_cfg = str(cfg_label or "").strip()
    if from_cfg and not re.match(r"^(restaurant|bar)$", from_cfg, re.I):
        return from_cfg
    from_inv = str((invoice or {}).get("created_by") or "").strip()
    if from_inv:
        return from_inv
    if from_arg:
        return from_arg
    if from_cfg:
        return from_cfg
    return "User"


def _tax_pcts(invoice: dict[str, Any]) -> tuple[float, float, float]:
    """Return (cgst_pct, ugst_pct, vat_pct) as percentage points."""
    cgst = _DEFAULT_CGST_PCT
    ugst = _DEFAULT_UGST_PCT
    vat = _DEFAULT_VAT_PCT
    inv = invoice or {}
    for key, attr in (("tax_cgst_pct", "cgst"), ("taxCgstPct", "cgst")):
        raw = inv.get(key)
        if raw is not None:
            try:
                cgst = float(raw)
                break
            except (TypeError, ValueError):
                pass
    for key in ("tax_ugst_pct", "taxUgstPct"):
        raw = inv.get(key)
        if raw is not None:
            try:
                ugst = float(raw)
                break
            except (TypeError, ValueError):
                pass
    return cgst, ugst, vat


def _normalize_totals(invoice: dict[str, Any]) -> dict[str, float]:
    inv = invoice or {}
    try:
        gst = float(inv.get("gst") or 0)
    except (TypeError, ValueError):
        gst = 0.0
    cgst_raw = inv.get("cgst")
    ugst_raw = inv.get("ugst")
    try:
        cgst = float(cgst_raw) if cgst_raw is not None else gst / 2.0
    except (TypeError, ValueError):
        cgst = gst / 2.0
    try:
        ugst = float(ugst_raw) if ugst_raw is not None else gst / 2.0
    except (TypeError, ValueError):
        ugst = gst / 2.0

    def _f(key, *alts):
        for k in (key, *alts):
            if inv.get(k) is not None:
                try:
                    return float(inv.get(k) or 0)
                except (TypeError, ValueError):
                    return 0.0
        return 0.0

    grand = _f("grand_total", "total")
    return {
        "subtotal": _f("subtotal"),
        "discount": _f("discount"),
        "discount_value": _f("discount_value"),
        "gst": gst,
        "vat": _f("vat"),
        "cgst": cgst,
        "ugst": ugst,
        "service": _f("service"),
        "service_value": _f("service_value"),
        "tip": _f("tip"),
        "round_off": _f("round_off"),
        "total": grand,
    }



def _logo_pdf_bytes(path: str) -> bytes:
    """Downscale receipt logos so WhatsApp PDFs stay small.

    Transparent PNG logos (e.g. Irish Barrel) are composited onto white before
    JPEG encode — bare ``RGBA → RGB`` fills alpha with black and paints a black
    box on the thermal bill.
    """
    try:
        from PIL import Image as PILImage
    except ImportError:
        return b""
    try:
        with PILImage.open(path) as im:
            if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
                rgba = im.convert("RGBA")
                background = PILImage.new("RGB", rgba.size, (255, 255, 255))
                background.paste(rgba, mask=rgba.split()[-1])
                im = background
            else:
                im = im.convert("RGB")
            im.thumbnail((520, 220), PILImage.Resampling.LANCZOS)
            out = io.BytesIO()
            im.save(out, format="JPEG", quality=72, optimize=True)
            return out.getvalue()
    except Exception:
        return b""


def pos_invoice_pdf_filename(order_no: str, invoice_id: int | None = None) -> str:
    stem = re.sub(r"[^\w.\-]+", "-", str(order_no or "").strip()) or "invoice"
    stem = stem.strip("-") or "invoice"
    if invoice_id and stem == "invoice":
        stem = f"invoice-{int(invoice_id)}"
    return f"{stem[:80]}.pdf"


def build_pos_invoice_pdf(
    invoice: dict[str, Any],
    *,
    business_name: str = "",
    address: str = "",
    gst: str = "",
    fssai: str = "",
    logo_url: str = "",
    user_label: str = "",
    outlet: str = "",
) -> bytes:
    """Build a thermal Spice-style customer bill PDF (WhatsApp DOCUMENT header).

    Matches ``buildPosCustomerBillHtml`` / Print button output — not the older
    navy A4 “TAX INVOICE” layout.
    """
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        HRFlowable,
        Image,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    inv = invoice or {}
    outlet_key = str(outlet or inv.get("outlet") or "").strip().lower()
    defaults = _receipt_defaults(outlet_key)

    brand = (business_name or "").strip() or defaults["business_name"]
    addr = (address or "").strip() or defaults["address"]
    gstin = _normalize_gst(gst, defaults["gst"])
    fssai_no = (fssai or "").strip() or defaults["fssai"]
    logo = _resolve_logo_path(logo_url or defaults["logo_url"], outlet_key)
    cashier = _resolve_user_label(inv, user_label=user_label, cfg_label=defaults.get("user_label", ""))

    order_no = str(inv.get("order_no") or inv.get("id") or "").strip() or "—"
    table = str(inv.get("table_label") or inv.get("table") or "").strip() or "—"
    order_date = _format_spice_date(
        inv.get("saved_at") or inv.get("customer_bill_at") or inv.get("created_at") or inv.get("order_date")
    )
    lines = _group_bill_lines(list(inv.get("lines") or []))
    totals = _normalize_totals(inv)
    cgst_pct, ugst_pct, vat_pct = _tax_pcts(inv)
    is_cancelled = str(inv.get("status") or "").strip().lower() == "cancelled"
    cancel_reason = str(inv.get("cancel_reason") or "").strip()
    hide_gst_fssai = is_nill_series_order_no(order_no)

    # Thermal strip width (~340px CSS ≈ 90mm); tall page like a receipt roll.
    page_w = 90 * mm
    page_h = 297 * mm
    margin = 6 * mm

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=(page_w, page_h),
        leftMargin=margin,
        rightMargin=margin,
        topMargin=8 * mm,
        bottomMargin=8 * mm,
    )

    ink = colors.HexColor("#111111")
    rule = colors.HexColor("#333333")
    content_w = page_w - 2 * margin

    brand_style = ParagraphStyle(
        "SpiceBrand",
        fontName="Courier-Bold",
        fontSize=11,
        alignment=TA_CENTER,
        textColor=ink,
        leading=14,
        spaceAfter=2,
    )
    center_style = ParagraphStyle(
        "SpiceCenter",
        fontName="Courier",
        fontSize=8,
        alignment=TA_CENTER,
        textColor=ink,
        leading=11,
        spaceAfter=1,
    )
    body = ParagraphStyle(
        "SpiceBody",
        fontName="Courier",
        fontSize=8,
        alignment=TA_LEFT,
        textColor=ink,
        leading=11,
    )
    body_bold = ParagraphStyle(
        "SpiceBodyBold",
        parent=body,
        fontName="Courier-Bold",
    )
    right = ParagraphStyle(
        "SpiceRight",
        parent=body,
        alignment=TA_RIGHT,
    )
    right_bold = ParagraphStyle(
        "SpiceRightBold",
        parent=body_bold,
        alignment=TA_RIGHT,
    )
    th = ParagraphStyle(
        "SpiceTh",
        fontName="Courier-Bold",
        fontSize=7,
        textColor=ink,
        leading=9,
    )
    th_right = ParagraphStyle(
        "SpiceThRight",
        parent=th,
        alignment=TA_RIGHT,
    )
    th_center = ParagraphStyle(
        "SpiceThCenter",
        parent=th,
        alignment=TA_CENTER,
    )
    item_style = ParagraphStyle(
        "SpiceItem",
        fontName="Courier",
        fontSize=8,
        textColor=ink,
        leading=10,
    )
    foot = ParagraphStyle(
        "SpiceFoot",
        fontName="Courier",
        fontSize=8,
        textColor=ink,
        leading=11,
        spaceBefore=6,
    )

    def dashed_rule():
        return HRFlowable(
            width="100%",
            thickness=0.6,
            color=rule,
            dash=(1.5, 1.5),
            spaceBefore=4,
            spaceAfter=4,
        )

    story: list = []

    if logo:
        try:
            logo_bytes = _logo_pdf_bytes(logo)
            img = Image(io.BytesIO(logo_bytes)) if logo_bytes else Image(logo)
            # Cap logo like CSS max-width:260px on a 340px bill (~76% of content).
            max_w = content_w * 0.85
            max_h = 28 * mm
            iw, ih = float(img.imageWidth), float(img.imageHeight)
            if iw > 0 and ih > 0:
                scale = min(max_w / iw, max_h / ih, 1.0)
                img.drawWidth = iw * scale
                img.drawHeight = ih * scale
            img.hAlign = "CENTER"
            story.append(img)
            story.append(Spacer(1, 3 * mm))
        except Exception:
            pass

    story.append(Paragraph(_esc(brand), brand_style))
    story.append(Paragraph(_esc(addr), center_style))
    if not hide_gst_fssai:
        gst_line = f"GST {_esc(gstin)}"
        if fssai_no:
            gst_line += f"  |  FSSAI No - {_esc(fssai_no)}"
        story.append(Paragraph(gst_line, center_style))

    story.append(dashed_rule())

    meta_rows = [
        [Paragraph("Invoice", body), Paragraph(_esc(order_no), right)],
        [Paragraph("Date", body), Paragraph(_esc(order_date), right)],
        [Paragraph("Table", body), Paragraph(_esc(table), right)],
    ]
    if is_cancelled:
        meta_rows.append([Paragraph("Status", body), Paragraph("Cancelled", right)])
        if cancel_reason:
            meta_rows.append(
                [Paragraph("Reason", body), Paragraph(_esc(cancel_reason), right)]
            )
    meta = Table(meta_rows, colWidths=[28 * mm, content_w - 28 * mm])
    meta.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 1),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    story.append(meta)
    story.append(dashed_rule())

    col_item = content_w - 48 * mm
    col_qty = 12 * mm
    col_rate = 18 * mm
    col_amt = 18 * mm
    table_data = [
        [
            Paragraph("ITEMS", th),
            Paragraph("QTY", th_center),
            Paragraph("RATE", th_right),
            Paragraph("AMOUNT", th_right),
        ]
    ]
    if not lines:
        table_data.append(
            [
                Paragraph("No items", item_style),
                Paragraph("", item_style),
                Paragraph("", item_style),
                Paragraph("", item_style),
            ]
        )
    else:
        for line in lines:
            table_data.append(
                [
                    Paragraph(_esc(line.get("name") or "Item"), item_style),
                    Paragraph(_qty(line.get("qty")), ParagraphStyle("q", parent=item_style, alignment=TA_CENTER)),
                    Paragraph(_money_thermal(line.get("rate")), ParagraphStyle("r", parent=item_style, alignment=TA_RIGHT)),
                    Paragraph(_money_thermal(line.get("line_total")), ParagraphStyle("a", parent=item_style, alignment=TA_RIGHT)),
                ]
            )

    items = Table(table_data, colWidths=[col_item, col_qty, col_rate, col_amt])
    items.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("LINEBELOW", (0, 0), (-1, 0), 0.8, rule),
                ("LINEBELOW", (0, 1), (-1, -1), 0.4, colors.HexColor("#DDDDDD")),
            ]
        )
    )
    story.append(items)
    story.append(dashed_rule())

    totals_rows = []
    totals_rows.append(
        [
            Paragraph("Sub-Total", body),
            Paragraph(_money_thermal(totals["subtotal"]), right),
        ]
    )
    if abs(totals["discount"]) > 0.005 or abs(totals["discount_value"]) > 0.005:
        totals_rows.append(
            [
                Paragraph("Discount", body),
                Paragraph(f"-{_money_thermal(totals['discount'])}", right),
            ]
        )
    if abs(totals["cgst"]) > 0.005:
        totals_rows.append(
            [
                Paragraph(f"CGST @ {_format_tax_pct(cgst_pct, as_fraction=False)}%", body),
                Paragraph(_money_thermal(totals["cgst"]), right),
            ]
        )
    if abs(totals["ugst"]) > 0.005:
        totals_rows.append(
            [
                Paragraph(f"UGST @ {_format_tax_pct(ugst_pct, as_fraction=False)}%", body),
                Paragraph(_money_thermal(totals["ugst"]), right),
            ]
        )
    if abs(totals["vat"]) > 0.005:
        totals_rows.append(
            [
                Paragraph(f"VAT @ {_format_tax_pct(vat_pct, as_fraction=False)}%", body),
                Paragraph(_money_thermal(totals["vat"]), right),
            ]
        )
    if abs(totals["service"]) > 0.005 or abs(totals["service_value"]) > 0.005:
        totals_rows.append(
            [
                Paragraph("Service Charge", body),
                Paragraph(_money_thermal(totals["service"]), right),
            ]
        )
    if abs(totals["tip"]) > 0.005:
        totals_rows.append(
            [
                Paragraph("Tip", body),
                Paragraph(_money_thermal(totals["tip"]), right),
            ]
        )
    if abs(totals["round_off"]) > 0.005:
        totals_rows.append(
            [
                Paragraph("Round-Off", body),
                Paragraph(_money_thermal(totals["round_off"]), right),
            ]
        )
    totals_rows.append(
        [
            Paragraph("Total", body_bold),
            Paragraph(_money_thermal(totals["total"]), right_bold),
        ]
    )
    totals_tbl = Table(totals_rows, colWidths=[content_w - 28 * mm, 28 * mm])
    totals_tbl.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 1),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("LINEABOVE", (0, -1), (-1, -1), 0.8, rule),
                ("TOPPADDING", (0, -1), (-1, -1), 4),
            ]
        )
    )
    story.append(totals_tbl)

    payments = list(inv.get("payments") or [])
    tender = []
    for pay in payments:
        if not isinstance(pay, dict):
            continue
        try:
            amt = float(pay.get("amount") or 0)
        except (TypeError, ValueError):
            amt = 0.0
        if abs(amt) < 0.005:
            continue
        label = str(
            pay.get("payment_method_label")
            or str(pay.get("payment_method") or "Cash").replace("_", " ").title()
        )
        tender.append((label, amt))
    if tender:
        story.append(Spacer(1, 3 * mm))
        pay_data = [
            [
                Paragraph("PAY MODE", th),
                Paragraph("AMOUNT", th_right),
            ]
        ]
        for label, amt in tender:
            pay_data.append(
                [
                    Paragraph(_esc(label), body),
                    Paragraph(_money_thermal(amt), right),
                ]
            )
        pay_tbl = Table(pay_data, colWidths=[content_w - 28 * mm, 28 * mm])
        pay_tbl.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("TOPPADDING", (0, 0), (-1, -1), 1),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("LINEBELOW", (0, 0), (-1, 0), 0.8, rule),
                ]
            )
        )
        story.append(pay_tbl)
        story.append(
            Paragraph(_money_thermal(totals["total"]), ParagraphStyle("pt", parent=right_bold, spaceBefore=3))
        )

    story.append(Paragraph(f"User : {_esc(cashier)}", foot))

    if is_cancelled:
        # Lightweight notice (HTML uses a rotated watermark; PDF uses a clear banner).
        story.insert(
            0,
            Paragraph(
                "<b>CANCELLED</b>",
                ParagraphStyle(
                    "CancelledBanner",
                    fontName="Courier-Bold",
                    fontSize=14,
                    alignment=TA_CENTER,
                    textColor=colors.HexColor("#B91C1C"),
                    spaceAfter=4,
                ),
            ),
        )

    doc.build(story)
    return buf.getvalue()
