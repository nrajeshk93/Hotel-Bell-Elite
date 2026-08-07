"""Generate Purchase Order PDF for WhatsApp supplier send.

The layout mirrors the hotel room invoice (``static/hotel_room_invoice.js`` +
``hotel_room_invoice.css``): the same mark, navy/gold palette, masthead with
contact block, navy item table and signatory block.
"""

from __future__ import annotations

import io
import os
import re
from datetime import datetime
from typing import Any

# Kept in step with the HOTEL block in static/hotel_room_invoice.js.
HOTEL_NAME = "HOTEL BELL ELITE"
HOTEL_TAGLINE = "COMFORT. ELEGANCE. HOSPITALITY."
HOTEL_ADDRESS = "Gurudwara Line, Aberdeen Bazar, Port Blair - 744101, Andaman India"
HOTEL_PHONE = "03192218267"
HOTEL_EMAIL = "hotelbellelite@gmail.com"
HOTEL_WEBSITE = "www.hotelbellelite.in"
HOTEL_GST = "35AANFH8592H1ZS"
HOTEL_MARK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "hbe_mark_sm.png")

NAVY = "#0B1F3A"
GOLD = "#C9A24A"
INK = "#0F172A"
MUTED = "#64748B"
HAIRLINE = "#E2E8F0"
PANEL = "#F8FAFD"


def _qty(value) -> str:
    try:
        n = float(value or 0)
    except (TypeError, ValueError):
        return "0"
    if abs(n - round(n)) < 0.0001:
        return str(int(round(n)))
    return f"{n:g}"


def _pack_qty_in_base(line: dict[str, Any]) -> float | None:
    raw = line.get("pack_qty_in_base")
    if raw is None or raw == "":
        return None
    try:
        qty = float(raw)
    except (TypeError, ValueError):
        return None
    if qty <= 0:
        return None
    return qty


def _line_product_name(line: dict[str, Any]) -> str:
    name = str(line.get("item_name") or "").strip()
    if name:
        return name
    # Fall back when only display_name is present (may include " — pack").
    display = str(line.get("display_name") or "").strip()
    if " — " in display:
        return display.split(" — ", 1)[0].strip()
    return display


def _line_pack_label(line: dict[str, Any]) -> str:
    return str(line.get("pack_label") or "").strip()


def _line_base_unit(line: dict[str, Any]) -> str:
    return str(line.get("unit") or "").strip()


def _line_unit_display(line: dict[str, Any]) -> str:
    """Match indent: pack lines show \"{pack_qty} {unit}\", else the base unit."""
    unit = _line_base_unit(line)
    pack = _line_pack_label(line)
    pack_qty = _pack_qty_in_base(line)
    if pack and pack_qty is not None:
        return f"{_qty(pack_qty)} {unit}".strip() if unit else _qty(pack_qty)
    return unit or "—"


def _line_total_display(line: dict[str, Any]) -> str:
    """Total base quantity with unit, e.g. 3 packs × 0.5 kg → \"1.5 kg\"."""
    try:
        qty = float(line.get("quantity") or 0)
    except (TypeError, ValueError):
        qty = 0.0
    unit = _line_base_unit(line)
    pack = _line_pack_label(line)
    pack_qty = _pack_qty_in_base(line)
    if pack and pack_qty is not None:
        total = qty * pack_qty
    else:
        total = qty
    qty_label = _qty(total)
    return f"{qty_label} {unit}".strip() if unit else qty_label


def _format_date(value) -> str:
    raw = str(value or "").strip()
    if not raw:
        return datetime.now().strftime("%d-%b-%Y")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw[:19] if " " in raw else raw[:10], fmt).strftime("%d-%b-%Y")
        except ValueError:
            continue
    return raw[:16]


def _spaced(text: str) -> str:
    """Letter-spaced caps, standing in for the invoice's CSS letter-spacing."""
    words = [" ".join(word) for word in str(text or "").strip().split()]
    return "&nbsp;&nbsp;&nbsp;".join(words)


def _esc(value) -> str:
    return (
        str(value if value is not None else "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def po_pdf_filename(supplier_name: str, po_no: str) -> str:
    """Build a filesystem-safe PO PDF name like PO_ABC-Traders_HBE_PO_4_2026-27.pdf."""
    supplier = re.sub(r"[^\w.-]+", "-", str(supplier_name or "Supplier").strip()) or "Supplier"
    supplier = supplier.strip("-_") or "Supplier"
    reference = re.sub(r"[^\w.-]+", "_", str(po_no or "PO").strip()) or "PO"
    return f"PO_{supplier}_{reference}.pdf"


def build_purchase_order_pdf(
    indent: dict[str, Any],
    supplier: dict[str, Any],
    lines: list[dict[str, Any]],
    *,
    outlet_label: str = "",
    po_no: str = "",
) -> bytes:
    """Build an A4 Purchase Order PDF for one supplier group."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
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

    navy = colors.HexColor(NAVY)
    gold = colors.HexColor(GOLD)
    muted = colors.HexColor(MUTED)
    hairline = colors.HexColor(HAIRLINE)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=14 * mm,
        bottomMargin=18 * mm,
        title=f"Purchase Order {po_no}".strip(),
        author=HOTEL_NAME.title(),
    )
    content_width = doc.width

    styles = getSampleStyleSheet()
    brand_style = ParagraphStyle(
        "PoBrand",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=16,
        leading=19,
        textColor=navy,
    )
    tagline_style = ParagraphStyle(
        "PoTagline",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=6.5,
        leading=9,
        textColor=muted,
    )
    contact_style = ParagraphStyle(
        "PoContact",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=7.6,
        leading=11,
        alignment=TA_RIGHT,
        textColor=colors.HexColor("#334155"),
    )
    title_style = ParagraphStyle(
        "PoTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=15,
        leading=19,
        textColor=navy,
        spaceAfter=6,
    )
    label_style = ParagraphStyle(
        "PoLabel",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=7.6,
        leading=11,
        textColor=muted,
    )
    value_style = ParagraphStyle(
        "PoValue",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=12,
        textColor=colors.HexColor(INK),
    )
    panel_head_style = ParagraphStyle(
        "PoPanelHead",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=7.6,
        leading=10,
        textColor=navy,
    )
    panel_name_style = ParagraphStyle(
        "PoPanelName",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=10.5,
        leading=14,
        textColor=colors.HexColor(INK),
    )
    panel_body_style = ParagraphStyle(
        "PoPanelBody",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8,
        leading=11.5,
        textColor=muted,
    )
    th_style = ParagraphStyle(
        "PoTh",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=7.8,
        leading=10,
        textColor=colors.white,
    )
    td_style = ParagraphStyle(
        "PoTd",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#334155"),
    )
    td_bold_style = ParagraphStyle(
        "PoTdBold", parent=td_style, fontName="Helvetica-Bold", textColor=colors.HexColor(INK)
    )
    notes_style = ParagraphStyle(
        "PoNotes",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8.2,
        leading=12,
        textColor=muted,
    )
    thanks_style = ParagraphStyle(
        "PoThanks",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=10,
        leading=14,
        alignment=TA_CENTER,
        textColor=gold,
    )
    sign_style = ParagraphStyle(
        "PoSign",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=7.8,
        leading=11,
        alignment=TA_RIGHT,
        textColor=muted,
    )
    ref_style = ParagraphStyle(
        "PoRef",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=7.2,
        leading=10,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#94A3B8"),
    )

    indent_no = str(indent.get("indent_no") or f"#{indent.get('id') or ''}").strip()
    po_number = str(po_no or "").strip() or indent_no or "—"
    date_label = _format_date(indent.get("decided_at") or indent.get("created_at"))
    department = (outlet_label or "").strip() or str(indent.get("outlet") or "—")
    supplier_name = (supplier.get("name") or "Supplier").strip() or "Supplier"
    supplier_phone = (supplier.get("phone") or "").strip()
    supplier_gst = (supplier.get("gst") or "").strip()
    supplier_address = (supplier.get("address") or "").strip()

    # Masthead: mark + brand copy on the left, contact block on the right.
    brand_cell = [Paragraph(_esc(HOTEL_NAME), brand_style)]
    brand_cell.append(
        HRFlowable(
            width=32 * mm,
            thickness=1.1,
            color=gold,
            spaceBefore=2.5,
            spaceAfter=3,
            hAlign="LEFT",
        )
    )
    brand_cell.append(Paragraph(_spaced(HOTEL_TAGLINE), tagline_style))

    contact_cell = Paragraph(
        "<br/>".join(
            [
                _esc(HOTEL_ADDRESS),
                f"Phone {_esc(HOTEL_PHONE)}",
                _esc(HOTEL_EMAIL),
                _esc(HOTEL_WEBSITE),
                f"<b>GST</b> {_esc(HOTEL_GST)}",
            ]
        ),
        contact_style,
    )

    mark_cell: Any = ""
    if os.path.exists(HOTEL_MARK):
        try:
            mark_cell = Image(HOTEL_MARK, width=19 * mm, height=19 * mm)
        except Exception:  # noqa: BLE001 - a missing/corrupt logo must not block the PO
            mark_cell = ""

    masthead = Table(
        [[mark_cell, brand_cell, contact_cell]],
        colWidths=[22 * mm, 68 * mm, content_width - 90 * mm],
    )
    masthead.setStyle(TableStyle([
        ("VALIGN", (0, 0), (1, 0), "MIDDLE"),
        ("VALIGN", (2, 0), (2, 0), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))

    meta_rows = [
        ("PO No.", po_number),
        ("PO Date", date_label),
        ("Outlet", department),
    ]
    meta_table = Table(
        [[Paragraph(_esc(k), label_style), Paragraph(_esc(v), value_style)] for k, v in meta_rows],
        colWidths=[24 * mm, 48 * mm],
    )
    meta_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, hairline),
    ]))

    supplier_lines = [Paragraph(_esc(supplier_name), panel_name_style)]
    if supplier_address:
        supplier_lines.append(Paragraph(_esc(supplier_address), panel_body_style))
    if supplier_gst:
        supplier_lines.append(Paragraph(f"<b>GST</b> {_esc(supplier_gst)}", panel_body_style))
    if supplier_phone:
        supplier_lines.append(Paragraph(f"Phone {_esc(supplier_phone)}", panel_body_style))

    supplier_panel = Table(
        [[Paragraph(_spaced("SUPPLIER"), panel_head_style)], [supplier_lines]],
        colWidths=[content_width - 82 * mm],
    )
    supplier_panel.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(PANEL)),
        ("BOX", (0, 0), (-1, -1), 0.5, hairline),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, hairline),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))

    meta_row = Table(
        [[
            [Paragraph(_spaced("PURCHASE ORDER"), title_style), meta_table],
            supplier_panel,
        ]],
        colWidths=[82 * mm, content_width - 82 * mm],
    )
    meta_row.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (0, 0), 0),
        ("RIGHTPADDING", (0, 0), (0, 0), 10),
        ("LEFTPADDING", (1, 0), (1, 0), 0),
        ("RIGHTPADDING", (1, 0), (1, 0), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))

    table_data = [[
        Paragraph(_spaced("PRODUCT"), th_style),
        Paragraph(_spaced("PACK"), th_style),
        Paragraph(_spaced("QTY"), th_style),
        Paragraph(_spaced("UNIT"), th_style),
        Paragraph(_spaced("TOTAL"), th_style),
    ]]
    for line in lines:
        try:
            qty = float(line.get("quantity") or 0)
        except (TypeError, ValueError):
            qty = 0.0
        pack = _line_pack_label(line)
        table_data.append([
            Paragraph(_esc(_line_product_name(line)), td_bold_style),
            Paragraph(_esc(pack or "—"), td_style),
            Paragraph(_qty(qty), td_style),
            Paragraph(_esc(_line_unit_display(line)), td_style),
            Paragraph(_esc(_line_total_display(line)), td_style),
        ])

    column_count = len(table_data[0])
    items = Table(
        table_data,
        colWidths=[content_width / column_count] * column_count,
        repeatRows=1,
    )
    items_style = [
        ("BACKGROUND", (0, 0), (-1, 0), navy),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("LINEBELOW", (0, 1), (-1, -1), 0.4, hairline),
        ("BOX", (0, 1), (-1, -1), 0.5, hairline),
    ]
    for row_index in range(2, len(table_data), 2):
        items_style.append(("BACKGROUND", (0, row_index), (-1, row_index), colors.HexColor("#FBFCFE")))
    items.setStyle(TableStyle(items_style))

    notes_panel = Table(
        [
            [Paragraph(_spaced("NOTES"), panel_head_style)],
            [
                Paragraph(
                    "Please confirm availability, price and expected delivery date. "
                    "Invoice must quote this PO number. "
                    "Deliver goods to the outlet address above during working hours.",
                    notes_style,
                )
            ],
        ],
        colWidths=[content_width],
    )
    notes_panel.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(PANEL)),
        ("BOX", (0, 0), (-1, -1), 0.5, hairline),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, hairline),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))

    def _page_furniture(canvas, document):
        canvas.saveState()
        canvas.setStrokeColor(gold)
        canvas.setLineWidth(0.8)
        y = 12 * mm
        canvas.line(document.leftMargin, y, document.pagesize[0] - document.rightMargin, y)
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(muted)
        canvas.drawString(document.leftMargin, y - 4.5 * mm, f"{HOTEL_NAME.title()} · Purchase Order {po_number}")
        canvas.drawRightString(
            document.pagesize[0] - document.rightMargin,
            y - 4.5 * mm,
            f"Page {canvas.getPageNumber()}",
        )
        canvas.restoreState()

    story = [
        masthead,
        HRFlowable(width="100%", thickness=1.6, color=gold, spaceBefore=0, spaceAfter=10),
        meta_row,
        Spacer(1, 12),
        items,
        Spacer(1, 12),
        notes_panel,
        Spacer(1, 16),
        Paragraph("Thank You for Your Service!", thanks_style),
        Spacer(1, 12),
        Paragraph(
            f"For {_esc(HOTEL_NAME.title())}<br/><br/><br/>"
            "____________________________<br/>Authorised Signatory",
            sign_style,
        ),
        Spacer(1, 10),
        Paragraph(f"Ref: Indent {_esc(indent_no or '—')}", ref_style),
    ]
    doc.build(story, onFirstPage=_page_furniture, onLaterPages=_page_furniture)
    return buf.getvalue()
