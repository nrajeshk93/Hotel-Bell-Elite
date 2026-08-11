#!/usr/bin/env python3
"""CLI: import RESTAURANT AND BAR SALES.xlsx into settled POS invoices.

Example:
  .venv/bin/python scripts/import_pos_sales.py \\
      --xlsx "/Users/rajesh/Downloads/RESTAURAND AND BAR SALES.xlsx"
"""

from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import db as db_mod  # noqa: E402
import pos_sales_import  # noqa: E402

DEFAULT_XLSX = os.path.expanduser("~/Downloads/RESTAURAND AND BAR SALES.xlsx")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--xlsx",
        default=DEFAULT_XLSX,
        help=f"Path to sales xlsx (default: {DEFAULT_XLSX})",
    )
    parser.add_argument(
        "--db",
        default=db_mod.DATABASE_PATH,
        help="SQLite database path (default: bell_elite.db)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and map only; roll back DB writes",
    )
    args = parser.parse_args(argv)

    xlsx = os.path.abspath(os.path.expanduser(args.xlsx))
    if not os.path.isfile(xlsx):
        print(f"File not found: {xlsx}", file=sys.stderr)
        return 1

    db_mod.DATABASE_PATH = os.path.abspath(os.path.expanduser(args.db))
    db_mod.init_db()
    conn = db_mod.get_db()
    try:
        stats = pos_sales_import.import_pos_sales(
            conn, xlsx, commit=not args.dry_run
        )
        if args.dry_run:
            conn.rollback()
            stats["dry_run"] = True
        print(json.dumps(stats, indent=2))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
