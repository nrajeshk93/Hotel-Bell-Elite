"""Import legacy ROOM SALES.xlsx rows into hotel invoices + Agency Master.

Parses xlsx via zip/XML because some exports have styles openpyxl cannot load.
Does not change the live Rooms floor board.
"""

from __future__ import annotations

import re
import zipfile
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from xml.etree import ElementTree as ET

import db as db_mod

_SSML_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
_COL_REF_RE = re.compile(r"^([A-Z]+)(\d+)$")
_RATE_PLANS = {"EP", "CP", "MAP", "AP"}

ROOM_TYPE_BY_NUMBER = {
    str(number): type_key for number, type_key in db_mod._HOTEL_ROOMS_SEED_SPEC
}


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


def parse_room_sales_xlsx(path: str) -> List[Dict[str, Any]]:
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
    if amount != amount:  # NaN
        return 0.0
    return round(amount, 2)


def parse_int(value: Any, default: int = 0) -> int:
    text = str(value or "").strip()
    if not text:
        return default
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return default


def parse_invoice_date(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%y"):
        try:
            return datetime.strptime(text[:10], fmt)
        except ValueError:
            continue
    return None


def parse_room_numbers(value: Any) -> List[str]:
    text = str(value or "").strip()
    if not text:
        return []
    parts = re.split(r"[,/;]+", text)
    out: List[str] = []
    seen = set()
    for part in parts:
        number = str(part or "").strip()
        if not number or number in seen:
            continue
        seen.add(number)
        out.append(number)
    return out


def normalize_rate_plan(value: Any) -> str:
    plan = str(value or "").strip().upper()
    if plan in _RATE_PLANS:
        return plan
    return "EP"


def clean_gstin(value: Any) -> str:
    return db_mod.sanitize_agency_gst_for_import(value)


def map_row_to_invoice_room(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Map one ROOM SALES row to a room+stay snapshot for invoice upsert."""
    if not isinstance(row, dict):
        return None
    invoice_number = str(row.get("INVOICE NUMBER") or "").strip()
    guest_name = str(row.get("GUEST NAME") or "").strip()
    rooms = parse_room_numbers(row.get("ROOM NUMBER"))
    if not invoice_number or not rooms:
        return None

    primary = rooms[0]
    type_key = ROOM_TYPE_BY_NUMBER.get(primary, "premium_deluxe_balcony")
    type_label = db_mod.HOTEL_ROOM_TYPE_LABELS.get(type_key, type_key)
    nights = max(1, parse_int(row.get("NO OF DAYS"), 1))
    pax = max(1, parse_int(row.get("PAX"), 1))
    invoice_dt = parse_invoice_date(row.get("INVOICE DATE"))
    if invoice_dt:
        check_out = invoice_dt.date()
        check_in = check_out - timedelta(days=nights)
        generated_at = invoice_dt.strftime("%Y-%m-%d %H:%M:%S")
        check_in_s = check_in.isoformat()
        check_out_s = check_out.isoformat()
    else:
        generated_at = ""
        check_in_s = ""
        check_out_s = ""

    final_amount = parse_money(row.get("FINAL AMOUNT"))
    if final_amount <= 0:
        final_amount = parse_money(row.get("TOTAL"))
    balance = parse_money(row.get("BALANCE"))
    cash = parse_money(row.get("CASH"))
    upi = parse_money(row.get("UPI"))
    bank = parse_money(row.get("BANK"))
    room_service = parse_money(row.get("ROOM SERVICE"))
    advance = round(cash + upi + bank, 2)

    room_count = max(1, len(rooms))
    # Combined inclusive stay total on the primary room (multi-room merge label).
    room_portion = max(0.0, round(final_amount - room_service, 2))
    room_rate = round(room_portion / nights, 2) if nights else room_portion
    rate_plan = normalize_rate_plan(row.get("PLAN"))
    agency_name = str(row.get("AGENT NAME") or "").strip()
    agency_gst = clean_gstin(row.get("GSTIN")) if agency_name else ""
    guest_gst = clean_gstin(row.get("GSTIN")) if not agency_name else ""

    payments: List[Dict[str, Any]] = []
    pay_idx = 1
    for amount, method in (
        (cash, "cash"),
        (upi, "upi"),
        (bank, "bank_transfer"),
    ):
        if amount > 0.009:
            payments.append(
                {
                    "id": f"pay-{pay_idx}",
                    "amount": amount,
                    "method": method,
                    "reference": "",
                    "note": "Imported from ROOM SALES",
                    "at": generated_at,
                }
            )
            pay_idx += 1

    folio_charges: List[Dict[str, Any]] = []
    if room_service > 0.009:
        folio_charges.append(
            {
                "id": "folio-1",
                "kind": "other",
                "label": "Room Service",
                "amount": room_service,
                "source": "room_sales_import",
                "note": "Imported ROOM SERVICE column",
                "at": generated_at,
            }
        )

    note_bits = []
    for label, key in (
        ("TAC", "TAC Amount"),
        ("Commission", "COMMISSION"),
        ("TCS", "TCS"),
        ("TDS", "TDS"),
        ("Round off", "ROUND OFF"),
    ):
        amount = parse_money(row.get(key))
        if abs(amount) >= 0.005:
            note_bits.append(f"{label}: {amount}")
    taxable = parse_money(row.get("TAXABLE VALUE"))
    cgst = parse_money(row.get("CGST"))
    ugst = parse_money(row.get("UGST"))
    if taxable or cgst or ugst:
        note_bits.append(f"Taxable {taxable}; CGST {cgst}; UGST {ugst}")
    if room_count > 1:
        note_bits.append(f"Rooms: {','.join(rooms)}")
    notes = "; ".join(note_bits)

    merge_label = ",".join(rooms) if len(rooms) > 1 else ""
    if agency_name and balance > 0.009:
        payment_method = "credit"
    elif upi >= cash and upi >= bank and upi > 0:
        payment_method = "upi"
    elif bank >= cash and bank > 0:
        payment_method = "bank_transfer"
    elif cash > 0:
        payment_method = "cash"
    else:
        payment_method = "credit" if agency_name else "cash"

    stay: Dict[str, Any] = {
        "guestName": guest_name or "Guest",
        "adults": pax,
        "children": 0,
        "nights": nights,
        "checkInDate": check_in_s,
        "checkOutDate": check_out_s,
        "checkInTime": "14:00",
        "checkOutTime": "11:00",
        "ratePlan": rate_plan,
        "roomRate": room_rate,
        "totalRate": room_portion,
        "estimatedTotal": final_amount,
        "advancePaid": advance,
        "checkInAdvancePaid": advance,
        "balanceAmount": balance,
        "invoiceNumber": invoice_number,
        "invoiceGenerated": True,
        "invoiceGeneratedAt": generated_at,
        "bookingNumber": invoice_number,
        "agencyName": agency_name,
        "agencyGst": agency_gst or guest_gst,
        "agencyBilling": bool(agency_name),
        "invoiceTo": agency_name if agency_name else guest_name,
        "billingName": agency_name if agency_name else guest_name,
        "paymentMethod": payment_method,
        "payments": payments,
        "folioCharges": folio_charges,
        "mergeRoomNumbers": rooms if len(rooms) > 1 else [],
        "mergeRoomLabel": merge_label,
        "mergeRole": "primary" if len(rooms) > 1 else "",
        "notes": notes[:500],
        "source": "room_sales_import",
    }

    return {
        "id": f"room-{primary}",
        "number": primary,
        "floorId": db_mod._hotel_floor_id_for_number(primary),
        "roomType": type_key,
        "roomTypeLabel": type_label,
        "status": "checked_out",
        "importedFrom": "room_sales_xlsx",
        "stay": stay,
    }


def import_room_sales(
    conn,
    path: str,
    *,
    commit: bool = True,
) -> Dict[str, Any]:
    """Parse workbook and upsert agencies + hotel_room_invoices."""
    rows = parse_room_sales_xlsx(path)
    stats: Dict[str, Any] = {
        "rows_read": len(rows),
        "agencies_created": 0,
        "agencies_updated": 0,
        "agencies_skipped": 0,
        "invoices_created": 0,
        "invoices_updated": 0,
        "invoices_open": 0,
        "invoices_settled": 0,
        "invoices_skipped": 0,
        "skipped_reasons": [],
    }

    # Agencies first (unique by name).
    seen_agents: Dict[str, str] = {}
    for row in rows:
        name = str(row.get("AGENT NAME") or "").strip()
        if not name:
            continue
        key = name.casefold()
        gst = clean_gstin(row.get("GSTIN"))
        if key not in seen_agents:
            seen_agents[key] = gst
        elif gst and not seen_agents[key]:
            seen_agents[key] = gst

    for name_key, gst in seen_agents.items():
        # Recover original casing from first matching row.
        display = next(
            (
                str(r.get("AGENT NAME") or "").strip()
                for r in rows
                if str(r.get("AGENT NAME") or "").strip().casefold() == name_key
            ),
            name_key,
        )
        normalized = " ".join(display.split()).strip()
        before = conn.execute(
            "SELECT id, gst FROM agencies WHERE LOWER(name) = LOWER(?) LIMIT 1",
            (normalized,),
        ).fetchone()
        saved = db_mod.upsert_agency_for_import(conn, display, gst, "")
        if not saved:
            stats["agencies_skipped"] += 1
            continue
        if before is None:
            stats["agencies_created"] += 1
        else:
            stats["agencies_updated"] += 1

    for row in rows:
        snapshot = map_row_to_invoice_room(row)
        if not snapshot:
            stats["invoices_skipped"] += 1
            inv = str(row.get("INVOICE NUMBER") or "").strip() or "(blank)"
            stats["skipped_reasons"].append(f"Missing invoice/rooms: {inv}")
            continue
        result = db_mod.import_hotel_room_invoice_snapshot(conn, snapshot)
        if not result:
            stats["invoices_skipped"] += 1
            continue
        if result.get("created"):
            stats["invoices_created"] += 1
        else:
            stats["invoices_updated"] += 1
        if result.get("status") == "settled":
            stats["invoices_settled"] += 1
        else:
            stats["invoices_open"] += 1

    if commit:
        conn.commit()
    return stats
