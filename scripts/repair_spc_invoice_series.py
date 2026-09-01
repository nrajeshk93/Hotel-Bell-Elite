#!/usr/bin/env python3
"""Renumber mistaken early Restaurant SPC bills (SPC/1..5/FY → migration floor).

Usage (repo root):
  .venv/bin/python scripts/repair_spc_invoice_series.py
  .venv/bin/python scripts/repair_spc_invoice_series.py --db /path/to/bell_elite.db
  .venv/bin/python scripts/repair_spc_invoice_series.py --force  # rerun even if marked done
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
        "--db",
        default=db_mod.DATABASE_PATH,
        help="SQLite database path (default: bell_elite.db beside db.py)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Clear the one-shot repair flag and run again",
    )
    args = parser.parse_args()

    db_mod.DATABASE_PATH = os.path.abspath(os.path.expanduser(args.db))
    conn = db_mod.get_db()
    try:
        if args.force:
            conn.execute("DROP TABLE IF EXISTS pos_spc_series_floor_repair")
            conn.commit()
        result = db_mod.repair_restaurant_spc_migrated_series_order_nos(conn)
        conn.commit()
    finally:
        conn.close()

    print(result)
    return 0 if result.get("changed") or not args.force else 0


if __name__ == "__main__":
    raise SystemExit(main())
