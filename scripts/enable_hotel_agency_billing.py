#!/usr/bin/env python3
"""Enable agency billing on hotel stay invoices (archived + live room).

Usage (repo root):
  .venv/bin/python scripts/enable_hotel_agency_billing.py 561 563 564
  .venv/bin/python scripts/enable_hotel_agency_billing.py HBE/561/2026-27
  .venv/bin/python scripts/enable_hotel_agency_billing.py --db /path/to/bell_elite.db 561
  .venv/bin/python scripts/enable_hotel_agency_billing.py --dry-run 561 563 564
"""

from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import db as db_mod


def _resolve_invoice_numbers(conn, tokens):
    ensure = db_mod.ensure_hotel_room_invoices_schema
    ensure(conn)
    out = []
    for raw in tokens:
        text = str(raw or "").strip()
        if not text:
            continue
        if "/" in text:
            out.append(text)
            continue
        row = conn.execute(
            """
            SELECT invoice_number
            FROM hotel_room_invoices
            WHERE invoice_number LIKE ?
            ORDER BY invoice_generated_at DESC
            LIMIT 1
            """,
            (f"%/{text}/%",),
        ).fetchone()
        if row:
            out.append(str(row["invoice_number"]))
        else:
            out.append(text)
    return out


def _enable_flags_on_stay(stay, *, room_bill=True, fb_bill=True):
    if not isinstance(stay, dict):
        return stay, False
    agency = db_mod._hotel_str(stay.get("agencyName") or stay.get("agency_name"), 160)
    if not agency:
        raise ValueError("Agency Name is required for Agency Billing.")
    patched = dict(stay)
    patched["agencyRoomBilling"] = bool(room_bill)
    patched["agencyFbBilling"] = bool(fb_bill)
    patched["agencyBilling"] = bool(room_bill or fb_bill)
    normalized = db_mod._normalize_hotel_room_stay(patched)
    before = (
        bool(stay.get("agencyRoomBilling")),
        bool(stay.get("agencyFbBilling")),
        bool(stay.get("agencyBilling")),
        str(stay.get("invoiceTo") or ""),
        str(stay.get("billingName") or ""),
    )
    after = (
        bool(normalized.get("agencyRoomBilling")),
        bool(normalized.get("agencyFbBilling")),
        bool(normalized.get("agencyBilling")),
        str(normalized.get("invoiceTo") or ""),
        str(normalized.get("billingName") or ""),
    )
    return normalized, before != after


def _patch_archived_invoice(conn, invoice_number, *, dry_run=False):
    row = conn.execute(
        """
        SELECT invoice_number, room_number, guest_name, payload_json
        FROM hotel_room_invoices
        WHERE invoice_number = ?
        LIMIT 1
        """,
        (invoice_number,),
    ).fetchone()
    if not row:
        return {"invoice_number": invoice_number, "status": "not_found"}
    payload = json.loads(row["payload_json"] or "{}")
    if not isinstance(payload, dict):
        payload = {}
    stay = payload.get("stay") if isinstance(payload.get("stay"), dict) else {}
    normalized, changed = _enable_flags_on_stay(stay)
    if not changed:
        return {
            "invoice_number": invoice_number,
            "status": "unchanged",
            "room_number": row["room_number"],
            "guest_name": row["guest_name"],
            "agencyRoomBilling": normalized.get("agencyRoomBilling"),
            "agencyFbBilling": normalized.get("agencyFbBilling"),
        }
    payload["stay"] = normalized
    if not dry_run:
        conn.execute(
            """
            UPDATE hotel_room_invoices
            SET payload_json = ?, updated_at = datetime('now','localtime')
            WHERE invoice_number = ?
            """,
            (json.dumps(payload, separators=(",", ":"), ensure_ascii=False), invoice_number),
        )
    return {
        "invoice_number": invoice_number,
        "status": "updated" if not dry_run else "would_update",
        "room_number": row["room_number"],
        "guest_name": row["guest_name"],
        "agencyRoomBilling": normalized.get("agencyRoomBilling"),
        "agencyFbBilling": normalized.get("agencyFbBilling"),
        "invoiceTo": normalized.get("invoiceTo"),
    }


def _patch_live_rooms(conn, invoice_numbers, *, dry_run=False):
    targets = {str(x).strip() for x in invoice_numbers if str(x).strip()}
    room_numbers = set()
    for inv in targets:
        row = conn.execute(
            "SELECT room_number FROM hotel_room_invoices WHERE invoice_number = ? LIMIT 1",
            (inv,),
        ).fetchone()
        if row and row["room_number"]:
            room_numbers.add(str(row["room_number"]).strip())
    layout = db_mod.get_hotel_rooms_layout(conn)
    rooms = layout.get("rooms") or []
    results = []
    changed_any = False
    for room in rooms:
        stay = room.get("stay") if isinstance(room.get("stay"), dict) else None
        if not stay:
            continue
        room_no = str(room.get("number") or room.get("id") or "").strip()
        inv = str(stay.get("invoiceNumber") or stay.get("invoice_number") or "").strip()
        if inv not in targets and room_no not in room_numbers:
            continue
        normalized, changed = _enable_flags_on_stay(stay)
        if changed:
            room["stay"] = normalized
            changed_any = True
        results.append(
            {
                "room_number": room_no,
                "invoice_number": inv or None,
                "status": "updated" if changed and not dry_run else ("would_update" if changed else "unchanged"),
                "agencyRoomBilling": normalized.get("agencyRoomBilling"),
                "agencyFbBilling": normalized.get("agencyFbBilling"),
            }
        )
    if changed_any and not dry_run:
        db_mod.save_hotel_rooms_layout(conn, layout.get("floors") or [], rooms)
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "invoice_refs",
        nargs="+",
        help="Invoice seq (561) or full number (HBE/561/2026-27)",
    )
    parser.add_argument(
        "--db",
        default=db_mod.DATABASE_PATH,
        help="SQLite database path (default: bell_elite.db beside db.py)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report changes without writing",
    )
    args = parser.parse_args()

    db_mod.DATABASE_PATH = os.path.abspath(os.path.expanduser(args.db))
    conn = db_mod.get_db()
    try:
        db_mod.ensure_hotel_rooms_schema(conn)
        invoice_numbers = _resolve_invoice_numbers(conn, args.invoice_refs)
        for inv in invoice_numbers:
            print(_patch_archived_invoice(conn, inv, dry_run=args.dry_run))
        live = _patch_live_rooms(conn, invoice_numbers, dry_run=args.dry_run)
        for row in live:
            print({"live_room": row})
        if not args.dry_run:
            conn.commit()
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
