#!/usr/bin/env python3
"""Zero Warehouse or Counter on-hand qty without touching Product Master.

Updates ``store_stock_items`` for the chosen ``place`` to qty 0 and writes
``adjustment`` movements for any non-zero lines (including negatives brought
back to 0). Does not delete or edit ``store_products`` / categories / variants.

Usage (repo root):
  PYTHONPATH=. .venv/bin/python scripts/zero_warehouse_stock.py --place counter
  PYTHONPATH=. .venv/bin/python scripts/zero_warehouse_stock.py --place warehouse
  PYTHONPATH=. .venv/bin/python scripts/zero_warehouse_stock.py --place counter --db /path/to/bell_elite.db
  PYTHONPATH=. .venv/bin/python scripts/zero_warehouse_stock.py --place counter --dry-run
"""

from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import db as db_mod
import stores as stores_mod


def zero_stock_place(conn, *, place: str, dry_run: bool = False, user_id=None) -> dict:
    """Set every stock row for ``place`` to qty 0; leave Product Master alone."""
    place = stores_mod._normalize_stock_place(place)
    db_mod.ensure_stores_schema(conn)
    rows = conn.execute(
        """
        SELECT id, outlet, place, item_name, unit, qty_on_hand
        FROM store_stock_items
        WHERE lower(coalesce(place, 'warehouse')) = ?
        ORDER BY outlet ASC, lower(item_name) ASC, id ASC
        """,
        (place,),
    ).fetchall()
    touched = []
    skipped = 0
    for row in rows:
        try:
            qty = float(row["qty_on_hand"] or 0)
        except (TypeError, ValueError):
            qty = 0.0
        if abs(qty) < 0.0001:
            skipped += 1
            continue
        delta = -qty
        info = {
            "id": int(row["id"]),
            "outlet": row["outlet"],
            "item_name": row["item_name"],
            "unit": row["unit"],
            "from_qty": round(qty, 3),
            "to_qty": 0.0,
        }
        if dry_run:
            touched.append(info)
            continue
        # Negatives → 0 need a positive delta; allow_negative keeps the path open
        # if on-hand is already below zero before the write.
        stores_mod._adjust_stock(
            conn,
            outlet=row["outlet"],
            place=place,
            item_name=row["item_name"],
            unit=row["unit"],
            qty_delta=delta,
            movement_type="adjustment",
            ref_type=f"{place}_zero",
            ref_id=int(row["id"]),
            notes=f"Zero {place} stock (Product Master unchanged)",
            user_id=user_id,
            allow_shortfall=True,
            allow_negative=True,
        )
        touched.append(info)

    remaining = conn.execute(
        """
        SELECT COUNT(*) AS c
        FROM store_stock_items
        WHERE lower(coalesce(place, 'warehouse')) = ?
          AND abs(coalesce(qty_on_hand, 0)) > 0.0001
        """,
        (place,),
    ).fetchone()
    products = conn.execute("SELECT COUNT(*) AS c FROM store_products").fetchone()
    return {
        "ok": True,
        "place": place,
        "dry_run": bool(dry_run),
        "rows": len(rows),
        "zeroed": len(touched),
        "already_zero": skipped,
        "nonzero_left": int((remaining["c"] if remaining else 0) or 0),
        "product_master_count": int((products["c"] if products else 0) or 0),
        "items": touched,
    }


def zero_warehouse_stock(conn, *, dry_run: bool = False, user_id=None) -> dict:
    """Back-compat wrapper — zero warehouse only."""
    return zero_stock_place(
        conn, place=stores_mod.STOCK_PLACE_WAREHOUSE, dry_run=dry_run, user_id=user_id
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        default=db_mod.DATABASE_PATH,
        help="SQLite database path (default: app DATABASE_PATH)",
    )
    parser.add_argument(
        "--place",
        choices=("warehouse", "counter"),
        default="warehouse",
        help="Stock place to zero (default: warehouse)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List lines that would be zeroed; write nothing",
    )
    args = parser.parse_args()

    db_mod.DATABASE_PATH = os.path.abspath(os.path.expanduser(args.db))
    conn = db_mod.get_db()
    try:
        result = zero_stock_place(conn, place=args.place, dry_run=args.dry_run)
        if not args.dry_run:
            conn.commit()
    finally:
        conn.close()

    print(
        f"{'DRY-RUN ' if result['dry_run'] else ''}"
        f"place={result['place']} rows={result['rows']} "
        f"zeroed={result['zeroed']} already_zero={result['already_zero']} "
        f"nonzero_left={result['nonzero_left']} "
        f"product_master={result['product_master_count']}"
    )
    for item in result["items"]:
        print(
            f"  {item['outlet']}: {item['item_name']} ({item['unit']}) "
            f"{item['from_qty']} → {item['to_qty']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
