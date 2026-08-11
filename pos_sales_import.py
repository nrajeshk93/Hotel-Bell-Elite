"""Import legacy RESTAURANT AND BAR SALES.xlsx into settled POS invoices.

SPC-* → restaurant (SPC/{yy-yy}/{n}); INV-* → bar (INV/{yy-yy}/{n}).
All rows are imported as closed/settled. Does not occupy tables or post hotel folio.
"""

from __future__ import annotations

import re
import zipfile
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from xml.etree import ElementTree as ET

import db as db_mod

_SSML_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
_COL_REF_RE = re.compile(r"^([A-Z]+)(\d+)$")
_LEGACY_ORDER_RE = re.compile(
    r"^(SPC|INV)[-/](\d{2})-(\d{2})[-/]0*(\d+)$",
    re.IGNORECASE,
)
_MONEY_EPS = 0.05


def _col_row(ref: str) -> Tuple[int, int]:
    match = _COL_REF_RE.match(str(ref or "").strip())
    if not match:
        raise ValueError(f"Bad cell ref: {ref!r}")
    col_letters, row_s = match.group(1), match.group(2)
    col = 0
    for ch in col_letters:
        col = col * 26 + (ord(ch) - 64)
    return col, int(row_s)


def _cell_value(cell: ET.Element, shared_strings: List[str]) -> Any:
    cell_type = cell.get("t")
    value_el = cell.find("m:v", _SSML_NS)
    inline = cell.find("m:is", _SSML_NS)
    if cell_type == "inlineStr" and inline is not None:
        return "".join(t.text or "" for t in inline.findall(".//m:t", _SSML_NS))
    if cell_type == "s" and value_el is not None and value_el.text is not None:
        idx = int(value_el.text)
        return shared_strings[idx] if 0 <= idx < len(shared_strings) else value_el.text
    if value_el is not None:
        return value_el.text
    return None


def parse_pos_sales_xlsx(path: str) -> List[Dict[str, Any]]:
    """Return list of row dicts keyed by header name (Sheet1)."""
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        shared_strings: List[str] = []
        if "xl/sharedStrings.xml" in names:
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            for si in root.findall("m:si", _SSML_NS):
                shared_strings.append(
                    "".join(t.text or "" for t in si.findall(".//m:t", _SSML_NS))
                )
        sheet_name = "xl/worksheets/sheet1.xml"
        if sheet_name not in names:
            raise FileNotFoundError(f"No Sheet1 in workbook: {path}")
        root = ET.fromstring(archive.read(sheet_name))
        grid: Dict[int, Dict[int, Any]] = {}
        for cell in root.findall(".//m:sheetData/m:row/m:c", _SSML_NS):
            ref = cell.get("r")
            if not ref:
                continue
            col, row = _col_row(ref)
            grid.setdefault(row, {})[col] = _cell_value(cell, shared_strings)

    if 1 not in grid:
        return []
    max_col = max(grid[1]) if grid[1] else 0
    headers = [str(grid[1].get(c) or "").strip() for c in range(1, max_col + 1)]
    rows: List[Dict[str, Any]] = []
    for row_idx in sorted(r for r in grid if r > 1):
        item: Dict[str, Any] = {}
        empty = True
        for c, header in enumerate(headers, 1):
            if not header:
                continue
            raw = grid[row_idx].get(c)
            if raw is None or str(raw).strip() == "":
                item[header] = ""
            else:
                item[header] = raw
                empty = False
        if not empty:
            rows.append(item)
    return rows


def parse_money(value: Any) -> float:
    text = str(value or "").strip().replace(",", "")
    if not text:
        return 0.0
    try:
        amount = float(text)
    except (TypeError, ValueError):
        return 0.0
    if amount != amount:
        return 0.0
    return round(amount, 2)


def parse_invoice_date(value: Any) -> Optional[str]:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%y"):
        try:
            return datetime.strptime(text[:10], fmt).date().isoformat()
        except ValueError:
            continue
    return None


def normalize_legacy_order_no(value: Any) -> Optional[Dict[str, str]]:
    """Map SPC-26-27-00001 / INV-26-27-00001 → order_no + outlet."""
    text = str(value or "").strip().upper().replace(" ", "")
    match = _LEGACY_ORDER_RE.match(text)
    if not match:
        return None
    prefix, yy, y2, seq = match.groups()
    prefix = prefix.upper()
    outlet = (
        db_mod.POS_OUTLET_BAR if prefix == "INV" else db_mod.POS_OUTLET_RESTAURANT
    )
    order_no = f"{prefix}/{yy}-{y2}/{int(seq)}"
    return {"order_no": order_no, "outlet": outlet, "prefix": prefix}


def build_tender_splits(
    *,
    total: float,
    cash: float,
    card: float,
    upi: float,
    credit: float,
    swiggy: float,
    zomato: float,
    room_transfer: float,
) -> List[Dict[str, Any]]:
    """Apply tender selection rules from the migration plan."""
    non_rt = [
        ("cash", round(cash, 2)),
        ("card", round(card, 2)),
        ("upi", round(upi, 2)),
        ("credit", round(credit, 2)),
        ("swiggy", round(swiggy, 2)),
        ("zomato", round(zomato, 2)),
    ]
    non_rt_sum = round(sum(a for _m, a in non_rt if a > 0.009), 2)
    rt = round(room_transfer, 2)
    total = round(total, 2)

    chosen: List[Tuple[str, float]] = []
    if non_rt_sum > 0.009 and abs(non_rt_sum - total) <= _MONEY_EPS:
        chosen = [(m, a) for m, a in non_rt if a > 0.009]
    elif rt > 0.009 and abs(rt - total) <= _MONEY_EPS:
        chosen = [("room_transfer", rt)]
    else:
        combined = [(m, a) for m, a in non_rt if a > 0.009]
        if rt > 0.009:
            combined.append(("room_transfer", rt))
        combined_sum = round(sum(a for _m, a in combined), 2)
        if combined and abs(combined_sum - total) <= _MONEY_EPS:
            chosen = combined
        elif total > 0.009:
            chosen = [("cash", total)]
        else:
            chosen = [("cash", 0.0)]

    # Collapse duplicate methods if any.
    merged: Dict[str, float] = {}
    for method, amount in chosen:
        merged[method] = round(merged.get(method, 0.0) + amount, 2)
    return [
        {"payment_method": method, "amount": amount}
        for method, amount in merged.items()
        if amount > 0.009 or total <= 0.009
    ]


def map_row_to_snapshot(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Map one sales ledger row to import_settled_pos_invoice_snapshot payload."""
    if not isinstance(row, dict):
        return None
    meta = normalize_legacy_order_no(row.get("INVOICE NUMBER"))
    if not meta:
        return None
    order_date = parse_invoice_date(row.get("INVOICE DATE"))
    if not order_date:
        return None
    pay_date = parse_invoice_date(row.get("PAYMENT DATE")) or order_date

    liquor = parse_money(row.get("LIQUOR"))
    vat = parse_money(row.get("VAT"))
    restaurant = parse_money(row.get("RESTAURANT"))
    gst = parse_money(row.get("GST"))
    discount = parse_money(row.get("DISCOUNT"))
    total = parse_money(row.get("TOTAL"))
    guest = str(row.get("GUEST NAME") or "").strip() or "Guest"
    room_no = str(row.get("ROOM NO") or "").strip()

    lines: List[Dict[str, Any]] = []
    if restaurant > 0.009:
        lines.append(
            {
                "name": "Restaurant",
                "rate": restaurant,
                "qty": 1,
                "line_total": restaurant,
            }
        )
    if liquor > 0.009:
        lines.append(
            {
                "name": "Liquor",
                "rate": liquor,
                "qty": 1,
                "line_total": liquor,
            }
        )
    if not lines and total > 0.009:
        lines.append(
            {
                "name": "Imported sale",
                "rate": total,
                "qty": 1,
                "line_total": total,
            }
        )

    splits = build_tender_splits(
        total=total,
        cash=parse_money(row.get("CASH")),
        card=parse_money(row.get("CARD")),
        upi=parse_money(row.get("UPI")),
        credit=parse_money(row.get("CREDIT")),
        swiggy=parse_money(row.get("SWIGGY")),
        zomato=parse_money(row.get("ZOMATO")),
        room_transfer=parse_money(row.get("ROOM TRANSFER")),
    )
    payments = []
    for split in splits:
        payments.append(
            {
                "payment_method": split["payment_method"],
                "amount": split["amount"],
                "payment_date": pay_date,
                "transaction_id": "",
                "notes": "Imported from RESTAURANT AND BAR SALES",
            }
        )
    delivery_modes = {"swiggy", "zomato"}
    order_type = (
        "takeaway"
        if any(s.get("payment_method") in delivery_modes for s in splits)
        else "dine_in"
    )

    note_bits = []
    status = str(row.get("PAYMENT STATUS") or "").strip()
    if status:
        note_bits.append(f"Source status: {status}")
    if room_no:
        note_bits.append(f"Room {room_no}")
    if abs(discount) >= 0.005:
        note_bits.append(f"Discount {discount}")

    saved_at = f"{order_date} 12:00:00"
    settled_at = f"{pay_date} 12:00:00"
    return {
        "order_no": meta["order_no"],
        "outlet": meta["outlet"],
        "order_type": order_type,
        "order_date": order_date,
        "saved_at": saved_at,
        "settled_at": settled_at,
        "customer_name": guest,
        "notes": "; ".join(note_bits)[:500],
        "payment_notes": "Imported from RESTAURANT AND BAR SALES",
        "subtotal": round(restaurant + liquor, 2),
        "discount_amount": discount,
        "gst_amount": gst,
        "vat_amount": vat,
        "grand_total": total,
        "lines": lines,
        "payments": payments,
    }


def import_pos_sales(
    conn,
    path: str,
    *,
    commit: bool = True,
) -> Dict[str, Any]:
    """Parse workbook and upsert settled restaurant/bar invoices."""
    rows = parse_pos_sales_xlsx(path)
    stats: Dict[str, Any] = {
        "rows_read": len(rows),
        "restaurant_created": 0,
        "restaurant_updated": 0,
        "bar_created": 0,
        "bar_updated": 0,
        "skipped": 0,
        "skipped_reasons": [],
    }
    for row in rows:
        snapshot = map_row_to_snapshot(row)
        if not snapshot:
            stats["skipped"] += 1
            inv = str(row.get("INVOICE NUMBER") or "").strip() or "(blank)"
            stats["skipped_reasons"].append(f"Unmapped invoice: {inv}")
            continue
        result = db_mod.import_settled_pos_invoice_snapshot(conn, snapshot)
        outlet = result.get("outlet")
        created = bool(result.get("created"))
        if outlet == db_mod.POS_OUTLET_BAR:
            if created:
                stats["bar_created"] += 1
            else:
                stats["bar_updated"] += 1
        else:
            if created:
                stats["restaurant_created"] += 1
            else:
                stats["restaurant_updated"] += 1
    if commit:
        conn.commit()
    return stats
