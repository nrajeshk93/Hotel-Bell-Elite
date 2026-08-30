"""Server-side print payload builders (KOT slips for Print Agent queue)."""

from __future__ import annotations

import base64
from datetime import datetime
from typing import Any

KOT_COLS = 42

OUTLET_META = {
    "restaurant": {
        "brand": "HOTEL BELL ELITE",
        "business": "SPICE MULTICUISINE",
        "user_label": "RESTAURANT",
        "kitchen_label": "KITCHEN",
    },
    "bar": {
        "brand": "HOTEL BELL ELITE",
        "business": "IRISH BARREL HOUSE BAR",
        "user_label": "BAR",
        "kitchen_label": "BAR",
    },
}


def kot_printer_role(outlet: str) -> str:
    return "bar" if str(outlet or "").strip().lower() == "bar" else "kitchen1"


def _kot_rule() -> str:
    return ("-" * KOT_COLS)[:KOT_COLS]


def _kot_pad(left: str, right: str) -> str:
    left = str(left or "")
    right = str(right or "")
    gap = KOT_COLS - len(left) - len(right)
    if gap < 1:
        left = left[: max(0, KOT_COLS - len(right) - 1)]
        gap = max(1, KOT_COLS - len(left) - len(right))
    return left + (" " * gap) + right


def _kot_center(text: str) -> str:
    text = str(text or "")
    if len(text) >= KOT_COLS:
        return text[:KOT_COLS]
    pad = (KOT_COLS - len(text)) // 2
    return (" " * pad) + text


def _kot_table_no(label: str) -> str:
    raw = str(label or "").strip()
    for token in raw.split():
        if token.isdigit():
            return token
    cleaned = raw.replace("Table", "").replace("table", "").strip()
    return cleaned or raw or "—"


def _kot_format_date(when: datetime | None = None) -> str:
    dt = when or datetime.now()
    months = [
        "Jan",
        "Feb",
        "Mar",
        "Apr",
        "May",
        "Jun",
        "Jul",
        "Aug",
        "Sep",
        "Oct",
        "Nov",
        "Dec",
    ]
    hour = dt.hour % 12 or 12
    ampm = "AM" if dt.hour < 12 else "PM"
    return (
        f"{dt.day:02d}-{months[dt.month - 1]}-{dt.year} "
        f"{hour:02d}:{dt.minute:02d} {ampm}"
    )


def _esc_pos_ascii(text: str) -> str:
    out = []
    for ch in str(text or ""):
        out.append(ch if ord(ch) < 128 else "?")
    return "".join(out)


def build_kot_ticket_model(
    invoice: dict[str, Any],
    items: list[dict[str, Any]],
    *,
    menu_outlet: str,
    resend: bool = False,
    user_label: str = "",
) -> dict[str, Any]:
    outlet = str(menu_outlet or invoice.get("outlet") or "restaurant").strip().lower()
    meta = OUTLET_META.get(outlet, OUTLET_META["restaurant"])
    order_type = str(invoice.get("order_type") or "dine_in").replace("_", " ").title()
    if not order_type:
        order_type = "Dine In"
    return {
        "menuOutlet": outlet,
        "outlet": outlet,
        "orderNo": invoice.get("kot_no") or invoice.get("order_no") or "—",
        "orderType": order_type,
        "tableLabel": invoice.get("table_label") or "—",
        "when": datetime.now(),
        "items": [
            {
                "name": it.get("name") or "Item",
                "qty": it.get("qty") or it.get("sent_qty") or 0,
                "variant": it.get("variant") or "",
                "notes": it.get("notes") or "",
            }
            for it in items
        ],
        "resend": bool(resend),
        "userLabel": user_label or meta["user_label"],
        "meta": meta,
    }


def format_kot_ticket_text(model: dict[str, Any]) -> str:
    outlet = str(model.get("menuOutlet") or model.get("outlet") or "restaurant").lower()
    meta = model.get("meta") or OUTLET_META.get(outlet, OUTLET_META["restaurant"])
    when = model.get("when")
    if not isinstance(when, datetime):
        when = datetime.now()
    rule = _kot_rule()
    lines = [
        _kot_center(meta["brand"]),
        _kot_center(str(meta["business"]).upper()),
        rule,
        f"Order No. : {model.get('orderNo') or '—'}",
        f"Order Type : {model.get('orderType') or 'Dine In'}",
        f"Date : {_kot_format_date(when)}",
        f"Table No. : {_kot_table_no(str(model.get('tableLabel') or ''))}",
        f"Kitchen : {meta['kitchen_label']}",
        f"User : {model.get('userLabel') or meta['user_label']}",
        rule,
    ]
    if model.get("resend"):
        lines.extend([_kot_center("REPRINT / RESEND"), rule])
    lines.extend([_kot_center("ORDER TICKET"), rule, _kot_pad("Items", "Qty"), rule])
    total_qty = 0.0
    for item in model.get("items") or []:
        try:
            qty = float(item.get("qty") or 0)
        except (TypeError, ValueError):
            qty = 0.0
        total_qty += qty
        name = str(item.get("name") or "Item").strip().upper()
        lines.append(_kot_pad(name, str(int(qty)) if qty == int(qty) else str(qty)))
        variant = str(item.get("variant") or "").strip()
        notes = str(item.get("notes") or "").strip()
        if variant:
            lines.append(f"  {variant}")
        if notes:
            lines.append(f"  Note: {notes}")
    lines.extend([rule, _kot_pad("Total Items", str(int(total_qty) if total_qty == int(total_qty) else total_qty)), rule, ""])
    return "\n".join(lines)


def format_kot_ticket_escpos(model: dict[str, Any]) -> bytes:
    """ESC/POS bytes compatible with Hotel Print Agent contentType=escpos."""
    ESC = b"\x1b"
    GS = b"\x1d"
    outlet = str(model.get("menuOutlet") or model.get("outlet") or "restaurant").lower()
    meta = model.get("meta") or OUTLET_META.get(outlet, OUTLET_META["restaurant"])
    when = model.get("when")
    if not isinstance(when, datetime):
        when = datetime.now()
    rule = _kot_rule()
    parts: list[bytes] = []

    def raw(data: bytes) -> None:
        parts.append(data)

    def line(text: str) -> None:
        parts.append(_esc_pos_ascii(text).encode("ascii", errors="replace") + b"\n")

    def center(on: bool) -> None:
        raw(ESC + b"a" + (b"\x01" if on else b"\x00"))

    raw(ESC + b"@")
    center(True)
    line(meta["brand"])
    line(str(meta["business"]).upper())
    center(False)
    line(rule)
    line(f"Order No. : {model.get('orderNo') or '—'}")
    line(f"Order Type : {model.get('orderType') or 'Dine In'}")
    line(f"Date : {_kot_format_date(when)}")
    line(f"Table No. : {_kot_table_no(str(model.get('tableLabel') or ''))}")
    line(f"Kitchen : {meta['kitchen_label']}")
    line(f"User : {model.get('userLabel') or meta['user_label']}")
    line(rule)
    if model.get("resend"):
        center(True)
        line("REPRINT / RESEND")
        center(False)
        line(rule)
    center(True)
    line("ORDER TICKET")
    center(False)
    line(rule)
    line(_kot_pad("Items", "Qty"))
    line(rule)
    total_qty = 0.0
    for item in model.get("items") or []:
        try:
            qty = float(item.get("qty") or 0)
        except (TypeError, ValueError):
            qty = 0.0
        total_qty += qty
        name = str(item.get("name") or "Item").strip().upper()
        line(_kot_pad(name, str(int(qty)) if qty == int(qty) else str(qty)))
        variant = str(item.get("variant") or "").strip()
        notes = str(item.get("notes") or "").strip()
        if variant:
            line(f"  {variant}")
        if notes:
            line(f"  Note: {notes}")
    line(rule)
    line(_kot_pad("Total Items", str(int(total_qty) if total_qty == int(total_qty) else total_qty)))
    line(rule)
    raw(b"\n\n")
    raw(GS + b"V" + b"\x01")
    return b"".join(parts)


def build_kot_print_payload(model: dict[str, Any]) -> dict[str, str]:
    """Return content fields for a print job."""
    try:
        esc = format_kot_ticket_escpos(model)
        if esc:
            return {
                "content_type": "escpos",
                "content_encoding": "base64",
                "content": base64.b64encode(esc).decode("ascii"),
            }
    except Exception:
        pass
    text = format_kot_ticket_text(model)
    return {
        "content_type": "text",
        "content_encoding": "utf8",
        "content": text,
    }
