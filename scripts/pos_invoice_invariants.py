#!/usr/bin/env python3
"""Dev/admin diagnostic counts for POS invoice invariants (localhost).

Reports:
  - multi_preinvoice: open dine-in pre-invoices sharing a table (expect 0)
  - generated_unsettled: customer_bill_sent=1 still status=open
  - hex_open_drafts: open active rows with provisional hex-shaped order_no

Usage (repo root):
  PYTHONPATH=. .venv/bin/python scripts/pos_invoice_invariants.py
"""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import db as db_mod  # noqa: E402


def collect(conn):
    multi = conn.execute(
        """
        SELECT outlet, lower(trim(table_label)) AS tkey, COUNT(*) AS n
        FROM pos_invoices
        WHERE is_active = 1
          AND status = 'open'
          AND order_type = 'dine_in'
          AND COALESCE(customer_bill_sent, 0) = 0
          AND trim(COALESCE(customer_bill_at, '')) = ''
          AND trim(COALESCE(table_label, '')) != ''
        GROUP BY outlet, lower(trim(table_label))
        HAVING COUNT(*) > 1
        """
    ).fetchall()
    generated_unsettled = conn.execute(
        """
        SELECT COUNT(*) AS n
        FROM pos_invoices
        WHERE is_active = 1
          AND status = 'open'
          AND COALESCE(customer_bill_sent, 0) = 1
        """
    ).fetchone()["n"]
    hex_open = conn.execute(
        """
        SELECT COUNT(*) AS n
        FROM pos_invoices
        WHERE is_active = 1
          AND status = 'open'
          AND COALESCE(customer_bill_sent, 0) = 0
          AND (
            upper(order_no) GLOB 'SPC/[0-9A-F][0-9A-F][0-9A-F][0-9A-F][0-9A-F][0-9A-F]/*'
            OR upper(order_no) GLOB 'INV/[0-9A-F][0-9A-F][0-9A-F][0-9A-F][0-9A-F][0-9A-F]/*'
          )
        """
    ).fetchone()["n"]
    return {
        "multi_preinvoice": int(len(multi)),
        "multi_preinvoice_rows": [
            {"outlet": r["outlet"], "table": r["tkey"], "count": int(r["n"])}
            for r in multi
        ],
        "generated_unsettled": int(generated_unsettled or 0),
        "hex_open_drafts": int(hex_open or 0),
    }


def main():
    conn = db_mod.get_db()
    try:
        db_mod.ensure_pos_schema(conn)
        payload = collect(conn)
        print(json.dumps(payload, indent=2))
        return 0 if payload["multi_preinvoice"] == 0 else 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
