"""Generate Indent Request PDF for WhatsApp approval."""

from __future__ import annotations

import io
from datetime import datetime
from typing import Any


def _money(value) -> str:
    try:
        n = float(value or 0)
    except (TypeError, ValueError):
        n = 0.0
    return f"₹{n:,.0f}" if abs(n - round(n)) < 0.001 else f"₹{n:,.2f}"


def _qty(value) -> str:
    try:
        n = float(value or 0)
    except (TypeError, ValueError):
        return "0"
    if abs(n - round(n)) < 0.0001:
        return str(int(round(n)))
    return f"{n:g}"


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


def build_indent_approval_pdf(
    indent: dict[str, Any],
    lines: list[dict[str, Any]],
    *,
    requested_by: str = "",
    outlet_label: str = "",
) -> bytes:
    """Build an A4 Indent Request PDF (layout aligned with Hotel Bell Elite template)."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "IndentTitle",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=18,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#0F172A"),
        spaceAfter=14,
    )
    label_style = ParagraphStyle(
        "IndentLabel",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        textColor=colors.HexColor("#64748B"),
    )
    value_style = ParagraphStyle(
        "IndentValue",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=11,
        textColor=colors.HexColor("#0F172A"),
    )
    body_style = ParagraphStyle(
        "IndentBody",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10,
        textColor=colors.HexColor("#334155"),
        leading=14,
    )
    right_style = ParagraphStyle(
        "IndentRight",
        parent=value_style,
        alignment=TA_RIGHT,
    )

    indent_no = indent.get("indent_no") or f"#{indent.get('id') or ''}"
    date_label = _format_date(indent.get("submitted_at") or indent.get("created_at"))
    requester = (requested_by or "").strip() or "—"
    department = (outlet_label or "").strip() or str(indent.get("outlet") or "—")
    status_label = "Pending Approval"
    remarks = (indent.get("notes") or "").strip() or (
        "Please review and approve this indent request. "
        "Upon approval, a Purchase Order will be generated automatically."
    )

    total = 0.0
    table_data = [[
        Paragraph("<b>Item</b>", body_style),
        Paragraph("<b>Qty</b>", body_style),
        Paragraph("<b>Unit</b>", body_style),
        Paragraph("<b>Approx. Price</b>", right_style),
    ]]
    for line in lines:
        qty = float(line.get("quantity") or 0)
        try:
            price = float(line.get("approximate_price") or 0)
        except (TypeError, ValueError):
            price = 0.0
        amount = qty * price
        total += amount
        table_data.append([
            Paragraph(str(line.get("item_name") or ""), body_style),
            Paragraph(_qty(qty), body_style),
            Paragraph(str(line.get("unit") or ""), body_style),
            Paragraph(_money(price), right_style),
        ])
    table_data.append([
        "",
        "",
        Paragraph("<b>Total</b>", body_style),
        Paragraph(f"<b>{_money(total)}</b>", right_style),
    ])

    meta = Table(
        [
            [
                Paragraph("Indent ID", label_style),
                Paragraph(str(indent_no), value_style),
                Paragraph("Date", label_style),
                Paragraph(date_label, value_style),
            ],
            [
                Paragraph("Requested By", label_style),
                Paragraph(requester, value_style),
                Paragraph("Department", label_style),
                Paragraph(department, value_style),
            ],
            [
                Paragraph("Supplier", label_style),
                Paragraph("________________", value_style),
                Paragraph("Priority", label_style),
                Paragraph("Normal", value_style),
            ],
            [
                Paragraph("Status", label_style),
                Paragraph(status_label, value_style),
                "",
                "",
            ],
        ],
        colWidths=[28 * mm, 55 * mm, 28 * mm, 55 * mm],
    )
    meta.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))

    items = Table(table_data, colWidths=[85 * mm, 22 * mm, 22 * mm, 37 * mm])
    items.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F1F5F9")),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.HexColor("#CBD5E1")),
        ("LINEBELOW", (0, 1), (-1, -2), 0.4, colors.HexColor("#E2E8F0")),
        ("LINEABOVE", (0, -1), (-1, -1), 0.8, colors.HexColor("#94A3B8")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("ALIGN", (1, 0), (2, -1), "CENTER"),
        ("ALIGN", (3, 0), (3, -1), "RIGHT"),
    ]))

    sign = Table(
        [[
            Paragraph("Requested By<br/><br/>__________________", body_style),
            Paragraph("Approved By<br/><br/>__________________", ParagraphStyle(
                "SignRight", parent=body_style, alignment=TA_RIGHT
            )),
        ]],
        colWidths=[83 * mm, 83 * mm],
    )

    story = [
        Paragraph("INDENT REQUEST", title_style),
        meta,
        Spacer(1, 10),
        items,
        Spacer(1, 14),
        Paragraph("<b>Remarks</b>", value_style),
        Spacer(1, 4),
        Paragraph(remarks.replace("\n", "<br/>"), body_style),
        Spacer(1, 28),
        sign,
    ]
    doc.build(story)
    return buf.getvalue()


def format_indent_total_amount(lines: list[dict[str, Any]]) -> str:
    total = 0.0
    for line in lines:
        try:
            qty = float(line.get("quantity") or 0)
            price = float(line.get("approximate_price") or 0)
        except (TypeError, ValueError):
            continue
        total += qty * price
    return f"{total:,.0f}" if abs(total - round(total)) < 0.001 else f"{total:,.2f}"
