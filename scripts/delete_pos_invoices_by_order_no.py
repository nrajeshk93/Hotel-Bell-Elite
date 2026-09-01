#!/usr/bin/env python3
"""Delete or cancel POS invoices by order number (production maintenance).

Provisional unsettled drafts are soft-deleted; issued numbers are cancelled.

Usage (repo root):
  .venv/bin/python scripts/delete_pos_invoices_by_order_no.py SPC/889589/26-27
  .venv/bin/python scripts/delete_pos_invoices_by_order_no.py --db /path/to/bell_elite.db \\
      SPC/889589/26-27 SPC/3A4E1A/26-27
  .venv/bin/python scripts/delete_pos_invoices_by_order_no.py --dry-run SPC/889589/26-27
"""

from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import db as db_mod


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "order_nos",
        nargs="+",
        help="POS invoice order_no values to remove (e.g. SPC/889589/26-27)",
    )
    parser.add_argument(
        "--db",
        default=db_mod.DATABASE_PATH,
        help="SQLite database path (default: bell_elite.db beside db.py)",
    )
    parser.add_argument(
        "--reason",
        default="Admin cleanup",
        help="Cancellation reason when the invoice cannot be soft-deleted",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report matches without changing the database",
    )
    args = parser.parse_args()

    db_mod.DATABASE_PATH = os.path.abspath(os.path.expanduser(args.db))
    conn = db_mod.get_db()
    try:
        db_mod.ensure_pos_schema(conn)
        for order_no in args.order_nos:
            text = str(order_no or "").strip()
            if not text:
                print({"order_no": order_no, "status": "skipped", "error": "empty order_no"})
                continue
            row = conn.execute(
                """
                SELECT id, order_no, status, outlet, customer_bill_sent, is_active
                FROM pos_invoices
                WHERE order_no = ?
                ORDER BY is_active DESC, id DESC
                LIMIT 1
                """,
                (text,),
            ).fetchone()
            if not row:
                print({"order_no": text, "status": "not_found"})
                continue
            if not row["is_active"]:
                print(
                    {
                        "order_no": text,
                        "status": "already_inactive",
                        "id": row["id"],
                    }
                )
                continue
            if args.dry_run:
                print(
                    {
                        "order_no": text,
                        "status": "would_remove",
                        "id": row["id"],
                        "invoice_status": row["status"],
                    }
                )
                continue
            try:
                result = db_mod.cancel_pos_invoice(
                    conn,
                    row["id"],
                    reason=args.reason,
                    cancelled_by="delete_pos_invoices_by_order_no.py",
                )
                db_mod.sync_pos_floor_occupancy_from_open_orders(
                    conn, row["outlet"] if "outlet" in row.keys() else None
                )
                conn.commit()
                print(
                    {
                        "order_no": text,
                        "status": result.get("mode"),
                        "id": row["id"],
                    }
                )
            except ValueError as exc:
                conn.rollback()
                print(
                    {
                        "order_no": text,
                        "status": "error",
                        "id": row["id"],
                        "error": str(exc),
                    }
                )
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
