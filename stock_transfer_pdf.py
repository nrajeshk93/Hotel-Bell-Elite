"""Generate a printable stock transfer/return slip (TRF-…) for handover / Inward verify.

Visual reference: hotel room invoice
(``static/hotel_room_invoice.js`` + ``static/hotel_room_invoice.css``) — same
mark, navy/gold palette, masthead + contact block, large document title with
meta list + route panel (Bill-To sibling), navy item table, notes card, and
sign lines. Reportlab twin of that HTML invoice family (see also
``purchase_order_pdf.py``).
"""

from __future__ import annotations

import io
import os
import re
from datetime import datetime
from typing import Any

# Kept in step with the HOTEL block in static/hotel_room_invoice.js
# and :root tokens in static/hotel_room_invoice.css.
HOTEL_NAME = "HOTEL BELL ELITE"
HOTEL_TAGLINE = "COMFORT. ELEGANCE. HOSPITALITY."
HOTEL_ADDRESS = "Gurudwara Line, Aberdeen Bazar, Port Blair - 744101, Andaman India"
HOTEL_PHONE = "03192218267"
HOTEL_EMAIL = "hotelbellelite@gmail.com"
HOTEL_WEBSITE = "www.hotelbellelite.in"
HOTEL_GST = "35AANFH8592H1ZS"
# Invoice uses hbe_mark_form.png; form_sm is the compact PDF sibling.
HOTEL_MARK = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "static", "hbe_mark_form_sm.png"
)

# hotel_room_invoice.css :root
NAVY = "#142A4A"
GOLD = "#C89B3C"
INK = "#0F172A"
MUTED = "#64748B"
HAIRLINE = "#E2E8F0"
ROW = "#F8FAFC"
BILLTO_BORDER = "#D8DEE8"


def _qty(value) -> str:
    try:
        n = float(value or 0)
    except (TypeError, ValueError):
        return "0"
    if abs(n - round(n)) < 0.0001:
        return str(int(round(n)))
    return f"{n:g}"


def _format_dt(value) -> str:
    raw = str(value or "").strip()
    if not raw:
        return datetime.now().strftime("%d-%b-%Y %H:%M")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            chunk = raw[:19] if " " in raw else raw[:10]
            return datetime.strptime(chunk, fmt).strftime(
                "%d-%b-%Y %H:%M" if " " in fmt else "%d-%b-%Y"
            )
        except ValueError:
            continue
    return raw


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


def _is_stock_return(transfer: dict[str, Any]) -> bool:
    """True for Counter → Warehouse (Return); False for Warehouse → Counter."""
    direction = str((transfer or {}).get("direction") or "").strip().lower()
    if direction in ("to_warehouse", "counter_to_warehouse"):
        return True
    if direction in ("to_counter", "warehouse_to_counter"):
        return False
    from_place = str((transfer or {}).get("from_place") or "").strip().lower()
    to_place = str((transfer or {}).get("to_place") or "").strip().lower()
    return from_place == "counter" and to_place == "warehouse"


def _slip_title(transfer: dict[str, Any]) -> str:
    return "STOCK RETURN" if _is_stock_return(transfer) else "STOCK TRANSFER"


def transfer_pdf_filename(transfer_no: str, transfer: dict[str, Any] | None = None) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", str(transfer_no or "TRF").strip()) or "TRF"
    suffix = "return" if transfer is not None and _is_stock_return(transfer) else "transfer"
    return f"{safe}_{suffix}.pdf"


def build_stock_transfer_pdf(
    transfer: dict[str, Any],
    lines: list[dict[str, Any]],
    *,
    created_by_name: str = "",
    route_label: str = "",
) -> bytes:
    """Build an A4 stock transfer/return slip PDF (reportlab), hotel-invoice styled.

    Counter→Warehouse uses title STOCK RETURN; Warehouse→Counter uses STOCK TRANSFER.
    Masthead, ROUTE panel, navy table, and QTY BASE match the transfer redesign.
    """
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        HRFlowable,
        Image,
        KeepTogether,
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
    ink = colors.HexColor(INK)
    row_bg = colors.HexColor(ROW)
    billto_border = colors.HexColor(BILLTO_BORDER)

    buf = io.BytesIO()
    transfer_no = str(transfer.get("transfer_no") or f"#{transfer.get('id') or ''}").strip()
    is_return = _is_stock_return(transfer)
    slip_title = _slip_title(transfer)
    slip_kind = "Stock Return" if is_return else "Stock Transfer"
    id_label = "Return ID" if is_return else "Transfer ID"
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=14 * mm,
        bottomMargin=18 * mm,
        title=f"{slip_kind} {transfer_no}".strip(),
        author=HOTEL_NAME.title(),
    )
    content_width = doc.width

    styles = getSampleStyleSheet()
    brand_style = ParagraphStyle(
        "TrfBrand",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=21,
        textColor=navy,
        # Approximate .hri-brand-name letter-spacing via thin spaces in content.
    )
    tagline_style = ParagraphStyle(
        "TrfTagline",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=7.5,
        leading=10,
        textColor=gold,  # invoice tagline is gold, not grey
    )
    contact_style = ParagraphStyle(
        "TrfContact",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8,
        leading=11.5,
        alignment=TA_LEFT,
        textColor=muted,
    )
    contact_strong = ParagraphStyle(
        "TrfContactStrong",
        parent=contact_style,
        textColor=navy,
        fontName="Helvetica-Bold",
    )
    title_style = ParagraphStyle(
        "TrfTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=22,
        leading=26,
        textColor=navy,
        spaceAfter=10,
    )
    meta_key_style = ParagraphStyle(
        "TrfMetaKey",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=9.5,
        leading=14,
        textColor=navy,
    )
    meta_val_style = ParagraphStyle(
        "TrfMetaVal",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9.5,
        leading=14,
        textColor=ink,
    )
    panel_head_style = ParagraphStyle(
        "TrfPanelHead",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8.5,
        leading=11,
        textColor=navy,
    )
    panel_name_style = ParagraphStyle(
        "TrfPanelName",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=15,
        textColor=navy,
    )
    panel_body_style = ParagraphStyle(
        "TrfPanelBody",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=12,
        textColor=muted,
    )
    th_style = ParagraphStyle(
        "TrfTh",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8.2,
        leading=11,
        textColor=colors.white,
    )
    th_center_style = ParagraphStyle(
        "TrfThCenter", parent=th_style, alignment=TA_CENTER
    )
    td_style = ParagraphStyle(
        "TrfTd",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9.5,
        leading=12.5,
        textColor=ink,
        alignment=TA_LEFT,
    )
    td_bold_style = ParagraphStyle(
        "TrfTdBold", parent=td_style, fontName="Helvetica-Bold", textColor=ink
    )
    td_center_style = ParagraphStyle(
        "TrfTdCenter", parent=td_style, alignment=TA_CENTER
    )
    notes_style = ParagraphStyle(
        "TrfNotes",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=12.5,
        textColor=muted,
    )
    sign_label_style = ParagraphStyle(
        "TrfSignLabel",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=12,
        textColor=navy,
        alignment=TA_CENTER,
    )
    sign_sub_style = ParagraphStyle(
        "TrfSignSub",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8,
        leading=11,
        textColor=muted,
        alignment=TA_CENTER,
    )
    sign_body_style = ParagraphStyle(
        "TrfSignBody",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8,
        leading=14,
        textColor=muted,
    )
    ref_style = ParagraphStyle(
        "TrfRef",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=7.2,
        leading=10,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#94A3B8"),
    )

    status = str(transfer.get("status") or "pending").strip().title()
    when = _format_dt(transfer.get("created_at"))
    route = (route_label or transfer.get("route_label") or "").strip() or "—"
    note = str(transfer.get("note") or "").strip() or "—"
    creator = (created_by_name or "").strip() or "—"
    from_bit = (
        f"{str(transfer.get('from_outlet') or '').title()} "
        f"{str(transfer.get('from_place') or '').title()}"
    ).strip() or "—"
    to_bit = (
        f"{str(transfer.get('to_outlet') or '').title()} "
        f"{str(transfer.get('to_place') or '').title()}"
    ).strip() or "—"

    # —— Masthead (invoiceBrandHeaderHtml) ——
    brand_cell = [
        Paragraph(_esc(HOTEL_NAME), brand_style),
        Spacer(1, 3),
        Paragraph(_spaced(HOTEL_TAGLINE), tagline_style),
    ]

    contact_lines = [
        Paragraph(_esc(HOTEL_ADDRESS), contact_style),
        Paragraph(_esc(HOTEL_PHONE), contact_style),
        Paragraph(_esc(HOTEL_EMAIL), contact_style),
        Paragraph(_esc(HOTEL_WEBSITE), contact_style),
        Paragraph(f"<b>GST:</b> {_esc(HOTEL_GST)}", contact_strong),
    ]
    contact_cell = contact_lines

    mark_cell: Any = ""
    if os.path.exists(HOTEL_MARK):
        try:
            mark_cell = Image(HOTEL_MARK, width=18 * mm, height=18 * mm)
        except Exception:  # noqa: BLE001 - missing/corrupt logo must not block slip
            mark_cell = ""
    elif os.path.exists(
        os.path.join(os.path.dirname(HOTEL_MARK), "hbe_mark_sm.png")
    ):
        try:
            mark_cell = Image(
                os.path.join(os.path.dirname(HOTEL_MARK), "hbe_mark_sm.png"),
                width=18 * mm,
                height=18 * mm,
            )
        except Exception:  # noqa: BLE001
            mark_cell = ""

    masthead = Table(
        [[mark_cell, brand_cell, contact_cell]],
        colWidths=[20 * mm, 78 * mm, content_width - 98 * mm],
    )
    masthead.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (1, 0), "MIDDLE"),
                ("VALIGN", (2, 0), (2, 0), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (1, 0), (1, 0), 8),
            ]
        )
    )

    # —— Title + meta list | Route panel (invoice meta-row / Bill To) ——
    meta_pairs = [
        (id_label, transfer_no or "—"),
        ("Date / time", when),
        ("Status", status),
        ("Created by", creator),
    ]
    meta_table = Table(
        [
            [
                Paragraph(_esc(k), meta_key_style),
                Paragraph(_esc(v), meta_val_style),
            ]
            for k, v in meta_pairs
        ],
        colWidths=[28 * mm, content_width * 0.42 - 28 * mm],
    )
    meta_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "BASELINE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 1.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
                ("LINEBELOW", (0, 1), (-1, 1), 0.5, hairline),
                ("TOPPADDING", (0, 2), (-1, 2), 6),
            ]
        )
    )

    left_col = [
        Paragraph(slip_title, title_style),
        meta_table,
    ]

    route_body = [
        Paragraph(_esc(route), panel_name_style),
        Spacer(1, 4),
        Paragraph(f"<b>From</b>  {_esc(from_bit)}", panel_body_style),
        Paragraph(f"<b>To</b>  {_esc(to_bit)}", panel_body_style),
        Paragraph(f"<b>Note</b>  {_esc(note)}", panel_body_style),
    ]
    route_panel = Table(
        [
            [Paragraph(_spaced("ROUTE"), panel_head_style)],
            [route_body],
        ],
        colWidths=[content_width * 0.48],
    )
    route_panel.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                ("BOX", (0, 0), (-1, -1), 0.8, billto_border),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (0, 0), 10),
                ("BOTTOMPADDING", (0, 0), (0, 0), 2),
                ("TOPPADDING", (0, 1), (0, 1), 4),
                ("BOTTOMPADDING", (0, 1), (0, 1), 10),
            ]
        )
    )

    left_w = content_width * 0.50
    right_w = content_width - left_w
    meta_row = Table(
        [[left_col, route_panel]],
        colWidths=[left_w, right_w],
    )
    meta_row.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (0, 0), 0),
                ("RIGHTPADDING", (0, 0), (0, 0), 10),
                ("LEFTPADDING", (1, 0), (1, 0), 0),
                ("RIGHTPADDING", (1, 0), (1, 0), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )

    # —— Items (navy colhead like .hri-colhead) ——
    table_data = [
        [
            Paragraph("#", th_center_style),
            Paragraph(_spaced("ITEM"), th_style),
            Paragraph(_spaced("OUTLET"), th_style),
            Paragraph(_spaced("UNIT"), th_center_style),
            # No parentheses — letter-spaced "QTY (BASE)" orphaned ")" on wrap.
            Paragraph(_spaced("QTY BASE"), th_center_style),
        ]
    ]
    for idx, line in enumerate(lines or [], start=1):
        table_data.append(
            [
                Paragraph(str(idx), td_center_style),
                Paragraph(_esc(line.get("item_name") or "—"), td_bold_style),
                Paragraph(_esc(str(line.get("outlet") or "—").title()), td_style),
                Paragraph(_esc(line.get("unit") or "pcs"), td_center_style),
                Paragraph(_qty(line.get("qty_base")), td_center_style),
            ]
        )
    if len(table_data) == 1:
        table_data.append(
            [
                Paragraph("—", td_center_style),
                Paragraph("No lines", td_style),
                Paragraph("—", td_style),
                Paragraph("—", td_center_style),
                Paragraph("—", td_center_style),
            ]
        )

    col_widths = [
        12 * mm,
        content_width - 12 * mm - 32 * mm - 20 * mm - 38 * mm,
        32 * mm,
        20 * mm,
        38 * mm,  # wide enough for letter-spaced "QTY BASE" on one line
    ]
    items = Table(table_data, colWidths=col_widths, repeatRows=1)
    items_style = [
        ("BACKGROUND", (0, 0), (-1, 0), navy),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, 0), 9),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 9),
        ("TOPPADDING", (0, 1), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("LINEBELOW", (0, 1), (-1, -1), 0.6, hairline),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("ALIGN", (3, 0), (-1, -1), "CENTER"),
        # Soft rounded look on header ends via padding only (reportlab has no radius).
    ]
    for row_index in range(2, len(table_data), 2):
        items_style.append(("BACKGROUND", (0, row_index), (-1, row_index), row_bg))
    items.setStyle(TableStyle(items_style))

    # —— Verify note (invoice notes card) ——
    notes_panel = Table(
        [
            [Paragraph(_spaced("VERIFY NOTE"), panel_head_style)],
            [
                Paragraph(
                    "Qty is stored in base units (Pack mode multiplies pack size at create). "
                    "Stock moves only after <b>Stock Inward → Transfers → Verify &amp; Receive</b>. "
                    "Hand this slip to the receiving outlet with the goods.",
                    notes_style,
                )
            ],
        ],
        colWidths=[content_width],
    )
    notes_panel.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                ("BOX", (0, 0), (-1, -1), 0.8, billto_border),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (0, 0), 10),
                ("BOTTOMPADDING", (0, 0), (0, 0), 2),
                ("TOPPADDING", (0, 1), (0, 1), 4),
                ("BOTTOMPADDING", (0, 1), (0, 1), 10),
            ]
        )
    )

    # —— Dual sign blocks (transfer-specific; gold rule like .hri-sign-line) ——
    def _sign_block(title: str) -> list:
        return [
            Spacer(1, 10),
            HRFlowable(
                width="85%",
                thickness=1.4,
                color=gold,
                spaceBefore=0,
                spaceAfter=6,
                hAlign="CENTER",
            ),
            Paragraph(_spaced(title), sign_label_style),
            Paragraph("Hotel Bell Elite", sign_sub_style),
            Spacer(1, 6),
            Paragraph("Name: ________________________", sign_body_style),
            Paragraph("Sign / Date: __________________", sign_body_style),
        ]

    sign_half = content_width / 2
    sign = Table(
        [[_sign_block("VERIFIED BY (RECEIVER)"), _sign_block("CARRIER / HANDED BY")]],
        colWidths=[sign_half, sign_half],
    )
    sign.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )

    def _page_furniture(canvas, document):
        canvas.saveState()
        canvas.setStrokeColor(gold)
        canvas.setLineWidth(0.9)
        y = 12 * mm
        canvas.line(document.leftMargin, y, document.pagesize[0] - document.rightMargin, y)
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(muted)
        canvas.drawString(
            document.leftMargin,
            y - 4.5 * mm,
            f"{HOTEL_NAME.title()} · {slip_kind} {transfer_no}",
        )
        canvas.drawRightString(
            document.pagesize[0] - document.rightMargin,
            y - 4.5 * mm,
            f"Page {canvas.getPageNumber()}",
        )
        canvas.restoreState()

    story = [
        masthead,
        # Gold rule under header — matches .hri-header border-bottom
        HRFlowable(width="100%", thickness=1.5, color=gold, spaceBefore=0, spaceAfter=14),
        meta_row,
        Spacer(1, 14),
        items,
        Spacer(1, 12),
        notes_panel,
        Spacer(1, 16),
        KeepTogether([sign]),
        Spacer(1, 10),
        Paragraph(
            f"Ref: {_esc(transfer_no or '—')} · For {_esc(HOTEL_NAME.title())}",
            ref_style,
        ),
    ]
    doc.build(story, onFirstPage=_page_furniture, onLaterPages=_page_furniture)
    return buf.getvalue()
