#!/usr/bin/env python3
"""Rebuild Bar Counter from Excel Closing Balance + replay POS sales.

1. Parse BAR COUNTER opening workbook — use **Closing Balance** as Sep 1 opening
   (Aug register end). Column D (1st AUG opening) is ignored.
2. Set Bar Counter on-hand to those openings (Product Master unchanged).
3. Clear ``stock_deducted_at`` + ``pos_invoice`` sale movements for closed
   bar/restaurant invoices from ``--from-date`` through today, then re-run
   ``deduct_stock_for_pos_invoice`` so counter = opening − sales.

Usage (repo root):
  PYTHONPATH=. .venv/bin/python scripts/rebuild_counter_from_opening_excel.py --dry-run
  PYTHONPATH=. .venv/bin/python scripts/rebuild_counter_from_opening_excel.py
  PYTHONPATH=. .venv/bin/python scripts/rebuild_counter_from_opening_excel.py \\
      --xlsx "/path/to/file.xlsx" --db /path/to/bell_elite.db
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import date, datetime
from typing import Any

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import db as db_mod
import stores as stores_mod

DEFAULT_XLSX = (
    "/Users/rajesh/Documents/Hotel Bell elite/"
    "BAR COUNTER  OPENING STOCK FOR THE MONTH SEPTEMBER (1).xlsx"
)
CLOSING_BALANCE_COL = 66  # 0-based: "Clossing Balance"
ITEM_NAME_COL = 2
ITEM_TYPE_COL = 1


def _normalize_match_name(name: str) -> str:
    return re.sub(r"\s+", " ", str(name or "").strip()).lower()


def _as_float(value) -> float | None:
    if value is None or value == "":
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if not text:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return None


def parse_bar_counter_opening_xlsx(path: str) -> list[dict[str, Any]]:
    """Return opening lines from Closing Balance column + section unit hints."""
    from openpyxl import load_workbook

    wb = load_workbook(path, data_only=True)
    ws = wb.active
    section = ""
    unit_hint = "Bottle"
    rows: list[dict[str, Any]] = []
    for idx, row in enumerate(ws.iter_rows(values_only=True), start=1):
        cells = list(row) if row else []
        a = cells[0] if len(cells) > 0 else None
        b = cells[ITEM_TYPE_COL] if len(cells) > ITEM_TYPE_COL else None
        c = cells[ITEM_NAME_COL] if len(cells) > ITEM_NAME_COL else None
        closing = cells[CLOSING_BALANCE_COL] if len(cells) > CLOSING_BALANCE_COL else None

        if isinstance(a, str) and a.strip() and c is None:
            section = a.strip().upper()
            if "BOTTEL" in section or "BOTTLE" in section:
                unit_hint = "Bottle"
            elif " ML" in f" {section}" or section.endswith("ML") or "IN ML" in section:
                unit_hint = "mL"
            continue

        if not isinstance(c, str) or not c.strip():
            continue
        name = c.strip()
        if name.lower() in ("item name", "clossing balance", "closing balance"):
            continue
        qty = _as_float(closing)
        if qty is None:
            continue
        rows.append(
            {
                "excel_row": idx,
                "section": section,
                "item_type": (str(b).strip() if b is not None else ""),
                "excel_name": name,
                "opening_qty": round(float(qty), 3),
                "unit_hint": unit_hint,
            }
        )
    return rows


def match_opening_to_products(
    conn, opening_rows: list[dict[str, Any]], *, outlet: str = "bar"
) -> dict[str, Any]:
    """Match Excel names to active Product Master rows for ``outlet``."""
    outlet = stores_mod._normalize_outlet_key(outlet)
    products = conn.execute(
        """
        SELECT id, name, default_unit, outlet
        FROM store_products
        WHERE is_active = 1
          AND lower(trim(coalesce(outlet, ''))) IN (?, 'both', '')
        ORDER BY id ASC
        """,
        (outlet,),
    ).fetchall()
    by_name: dict[str, list] = {}
    for row in products:
        key = _normalize_match_name(row["name"])
        if not key:
            continue
        by_name.setdefault(key, []).append(row)

    matched: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []
    for line in opening_rows:
        key = _normalize_match_name(line["excel_name"])
        candidates = by_name.get(key) or []
        # Prefer exact outlet match over both/blank.
        chosen = None
        for row in candidates:
            if stores_mod._normalize_outlet_key(row["outlet"] or outlet) == outlet:
                chosen = row
                break
        if chosen is None and candidates:
            chosen = candidates[0]
        if chosen is None:
            unmatched.append(dict(line))
            continue
        unit = (str(chosen["default_unit"] or "").strip() or line["unit_hint"] or "pcs")
        matched.append(
            {
                **line,
                "product_id": int(chosen["id"]),
                "product_name": chosen["name"],
                "unit": unit,
                "match_key": key,
            }
        )
    return {"matched": matched, "unmatched": unmatched, "product_count": len(products)}


def _set_counter_qty_absolute(
    conn,
    *,
    outlet: str,
    item_name: str,
    unit: str,
    target_qty: float,
    ref_type: str,
    notes: str,
    user_id=None,
) -> float:
    """Move counter on-hand to ``target_qty`` via a single adjustment delta."""
    place = stores_mod.STOCK_PLACE_COUNTER
    current = stores_mod._stock_qty_on_hand(conn, outlet, place, item_name, unit)
    delta = round(float(target_qty) - float(current), 3)
    if abs(delta) < 0.0001:
        return 0.0
    return float(
        stores_mod._adjust_stock(
            conn,
            outlet=outlet,
            place=place,
            item_name=item_name,
            unit=unit,
            qty_delta=delta,
            movement_type="adjustment",
            ref_type=ref_type,
            ref_id=0,
            notes=notes,
            user_id=user_id,
            allow_shortfall=True,
            allow_negative=True,
        )
        or 0.0
    )


def apply_bar_counter_openings(
    conn,
    matched: list[dict[str, Any]],
    *,
    as_of: str,
    dry_run: bool = False,
    user_id=None,
) -> dict[str, Any]:
    """Zero all bar counter rows, then set matched openings."""
    outlet = "bar"
    place = stores_mod.STOCK_PLACE_COUNTER
    existing = conn.execute(
        """
        SELECT id, item_name, unit, qty_on_hand
        FROM store_stock_items
        WHERE outlet = ? AND place = ?
        ORDER BY id ASC
        """,
        (outlet, place),
    ).fetchall()
    applied: list[dict[str, Any]] = []
    if dry_run:
        for line in matched:
            applied.append(
                {
                    "product_name": line["product_name"],
                    "unit": line["unit"],
                    "opening_qty": line["opening_qty"],
                    "excel_name": line["excel_name"],
                }
            )
        return {
            "dry_run": True,
            "existing_bar_counter_rows": len(existing),
            "openings_to_apply": len(matched),
            "applied": applied,
        }

    # Zero every existing bar counter row first.
    for row in existing:
        _set_counter_qty_absolute(
            conn,
            outlet=outlet,
            item_name=row["item_name"],
            unit=row["unit"],
            target_qty=0.0,
            ref_type="opening_import",
            notes=f"Bar counter zero before opening import as of {as_of}",
            user_id=user_id,
        )

    for line in matched:
        delta = _set_counter_qty_absolute(
            conn,
            outlet=outlet,
            item_name=line["product_name"],
            unit=line["unit"],
            target_qty=float(line["opening_qty"]),
            ref_type="opening_import",
            notes=f"Bar counter opening as of {as_of} (Excel Closing Balance)",
            user_id=user_id,
        )
        applied.append(
            {
                "product_name": line["product_name"],
                "unit": line["unit"],
                "opening_qty": line["opening_qty"],
                "excel_name": line["excel_name"],
                "delta": round(delta, 3),
            }
        )
    return {
        "dry_run": False,
        "existing_bar_counter_rows": len(existing),
        "openings_applied": len(applied),
        "applied": applied,
    }


def list_closed_invoices_for_replay(
    conn, *, from_date: str, to_date: str
) -> list[int]:
    """Closed bar/restaurant invoices in date range (exclude cancelled / import-skip)."""
    rows = conn.execute(
        """
        SELECT id
        FROM pos_invoices
        WHERE lower(trim(coalesce(outlet, ''))) IN ('bar', 'restaurant')
          AND order_date >= ?
          AND order_date <= ?
          AND trim(coalesce(cancelled_at, '')) = ''
          AND lower(trim(coalesce(status, ''))) = 'closed'
          AND lower(trim(coalesce(stock_deducted_at, ''))) != 'import-skip'
        ORDER BY order_date ASC, id ASC
        """,
        (from_date, to_date),
    ).fetchall()
    return [int(r["id"]) for r in rows]


def clear_sale_deductions_for_invoices(conn, invoice_ids: list[int]) -> dict[str, int]:
    """Delete pos_invoice sale movements and clear stock_deducted_at."""
    if not invoice_ids:
        return {"movements_deleted": 0, "invoices_cleared": 0}
    deleted = 0
    cleared = 0
    chunk = 400
    for i in range(0, len(invoice_ids), chunk):
        part = invoice_ids[i : i + chunk]
        placeholders = ",".join("?" for _ in part)
        cur = conn.execute(
            f"""
            DELETE FROM store_stock_movements
            WHERE ref_type = 'pos_invoice' AND ref_id IN ({placeholders})
            """,
            part,
        )
        deleted += int(cur.rowcount or 0)
        cur2 = conn.execute(
            f"""
            UPDATE pos_invoices
            SET stock_deducted_at = '', updated_at = datetime('now','localtime')
            WHERE id IN ({placeholders})
            """,
            part,
        )
        cleared += int(cur2.rowcount or 0)
    return {"movements_deleted": deleted, "invoices_cleared": cleared}


def replay_pos_stock_deductions(
    conn, invoice_ids: list[int], *, dry_run: bool = False, user_id=None
) -> dict[str, Any]:
    if dry_run:
        return {"dry_run": True, "invoice_count": len(invoice_ids), "replayed": 0}
    replayed = 0
    skipped = 0
    errors: list[dict[str, Any]] = []
    for invoice_id in invoice_ids:
        result = stores_mod.deduct_stock_for_pos_invoice(
            conn, invoice_id, user_id=user_id, allow_inactive=True
        )
        # ``skipped`` on success is a list of line-level skips; idempotent skip
        # uses boolean True + reason already_deducted / movements_exist.
        if result.get("ok") and result.get("skipped") is True:
            skipped += 1
        elif result.get("ok"):
            replayed += 1
        else:
            errors.append({"invoice_id": invoice_id, "result": result})
    return {
        "dry_run": False,
        "invoice_count": len(invoice_ids),
        "replayed": replayed,
        "skipped": skipped,
        "errors": errors,
    }


def rebuild_counter_from_opening_excel(
    conn,
    *,
    xlsx_path: str,
    from_date: str = "2026-09-01",
    to_date: str | None = None,
    dry_run: bool = False,
    user_id=None,
) -> dict[str, Any]:
    """Full rebuild: parse → match → open bar counter → clear → replay sales."""
    db_mod.ensure_pos_schema(conn)
    db_mod.ensure_stores_schema(conn)
    to_date = to_date or date.today().isoformat()

    opening_rows = parse_bar_counter_opening_xlsx(xlsx_path)
    match_info = match_opening_to_products(conn, opening_rows, outlet="bar")
    invoice_ids = list_closed_invoices_for_replay(
        conn, from_date=from_date, to_date=to_date
    )

    report: dict[str, Any] = {
        "ok": True,
        "dry_run": bool(dry_run),
        "xlsx_path": xlsx_path,
        "from_date": from_date,
        "to_date": to_date,
        "excel_rows": len(opening_rows),
        "matched": len(match_info["matched"]),
        "unmatched": match_info["unmatched"],
        "invoice_ids": invoice_ids,
        "invoice_count": len(invoice_ids),
    }

    if dry_run:
        report["opening_preview"] = apply_bar_counter_openings(
            conn, match_info["matched"], as_of=from_date, dry_run=True
        )
        report["replay_preview"] = replay_pos_stock_deductions(
            conn, invoice_ids, dry_run=True
        )
        return report

    report["opening"] = apply_bar_counter_openings(
        conn,
        match_info["matched"],
        as_of=from_date,
        dry_run=False,
        user_id=user_id,
    )
    report["clear"] = clear_sale_deductions_for_invoices(conn, invoice_ids)
    report["replay"] = replay_pos_stock_deductions(
        conn, invoice_ids, dry_run=False, user_id=user_id
    )

    bar_nonzero = conn.execute(
        """
        SELECT COUNT(*) AS c, COALESCE(SUM(qty_on_hand), 0) AS qty
        FROM store_stock_items
        WHERE outlet = 'bar' AND place = 'counter'
        """
    ).fetchone()
    rest_nonzero = conn.execute(
        """
        SELECT COUNT(*) AS c, COALESCE(SUM(qty_on_hand), 0) AS qty
        FROM store_stock_items
        WHERE outlet = 'restaurant' AND place = 'counter'
        """
    ).fetchone()
    report["bar_counter"] = {
        "rows": int(bar_nonzero["c"] or 0),
        "sum_qty": round(float(bar_nonzero["qty"] or 0), 3),
    }
    report["restaurant_counter"] = {
        "rows": int(rest_nonzero["c"] or 0),
        "sum_qty": round(float(rest_nonzero["qty"] or 0), 3),
    }
    report["product_master_count"] = int(
        conn.execute("SELECT COUNT(*) AS c FROM store_products").fetchone()["c"] or 0
    )
    return report


def _print_report(report: dict[str, Any]) -> None:
    prefix = "DRY-RUN " if report.get("dry_run") else ""
    print(
        f"{prefix}excel_rows={report.get('excel_rows')} matched={report.get('matched')} "
        f"unmatched={len(report.get('unmatched') or [])} "
        f"invoices={report.get('invoice_count')} "
        f"from={report.get('from_date')} to={report.get('to_date')}"
    )
    unmatched = report.get("unmatched") or []
    if unmatched:
        print("Unmatched Excel names:")
        for line in unmatched[:40]:
            print(
                f"  row {line.get('excel_row')}: {line.get('excel_name')} "
                f"opening={line.get('opening_qty')} hint={line.get('unit_hint')}"
            )
        if len(unmatched) > 40:
            print(f"  … {len(unmatched) - 40} more")

    if report.get("dry_run"):
        preview = (report.get("opening_preview") or {}).get("applied") or []
        print(f"Opening matches to apply: {len(preview)}")
        for line in preview[:25]:
            print(
                f"  {line['excel_name']} → {line['product_name']} "
                f"({line['unit']}) = {line['opening_qty']}"
            )
        if len(preview) > 25:
            print(f"  … {len(preview) - 25} more")
        return

    opening = report.get("opening") or {}
    clear = report.get("clear") or {}
    replay = report.get("replay") or {}
    print(
        f"openings_applied={opening.get('openings_applied')} "
        f"movements_deleted={clear.get('movements_deleted')} "
        f"invoices_cleared={clear.get('invoices_cleared')} "
        f"replayed={replay.get('replayed')} skipped={replay.get('skipped')}"
    )
    print(
        f"bar_counter rows={report.get('bar_counter', {}).get('rows')} "
        f"sum_qty={report.get('bar_counter', {}).get('sum_qty')} | "
        f"restaurant_counter rows={report.get('restaurant_counter', {}).get('rows')} "
        f"sum_qty={report.get('restaurant_counter', {}).get('sum_qty')} | "
        f"product_master={report.get('product_master_count')}"
    )
    for line in (opening.get("applied") or [])[:15]:
        if float(line.get("opening_qty") or 0) == 0:
            continue
        print(
            f"  open {line['product_name']} ({line['unit']}) = {line['opening_qty']}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xlsx", default=DEFAULT_XLSX, help="Path to opening Excel")
    parser.add_argument(
        "--db",
        default=db_mod.DATABASE_PATH,
        help="SQLite database path (default: app DATABASE_PATH)",
    )
    parser.add_argument(
        "--from-date",
        default="2026-09-01",
        help="First sales date to replay (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--to-date",
        default="",
        help="Last sales date to replay (default: today)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse/match/report only; write nothing",
    )
    args = parser.parse_args()

    xlsx_path = os.path.abspath(os.path.expanduser(args.xlsx))
    if not os.path.isfile(xlsx_path):
        print(f"Excel not found: {xlsx_path}", file=sys.stderr)
        return 1
    try:
        datetime.strptime(args.from_date, "%Y-%m-%d")
    except ValueError:
        print(f"Invalid --from-date: {args.from_date}", file=sys.stderr)
        return 1
    to_date = (args.to_date or "").strip() or date.today().isoformat()
    try:
        datetime.strptime(to_date, "%Y-%m-%d")
    except ValueError:
        print(f"Invalid --to-date: {to_date}", file=sys.stderr)
        return 1

    db_mod.DATABASE_PATH = os.path.abspath(os.path.expanduser(args.db))
    conn = db_mod.get_db()
    try:
        report = rebuild_counter_from_opening_excel(
            conn,
            xlsx_path=xlsx_path,
            from_date=args.from_date,
            to_date=to_date,
            dry_run=args.dry_run,
        )
        if not args.dry_run:
            conn.commit()
        # sample current bar counter after live run
        if not args.dry_run:
            sample = conn.execute(
                """
                SELECT item_name, unit, qty_on_hand
                FROM store_stock_items
                WHERE outlet = 'bar' AND place = 'counter'
                  AND abs(coalesce(qty_on_hand, 0)) > 0.0001
                ORDER BY lower(item_name)
                LIMIT 20
                """
            ).fetchall()
            report["bar_counter_sample"] = [dict(r) for r in sample]
    finally:
        conn.close()

    _print_report(report)
    if report.get("bar_counter_sample"):
        print("Bar counter non-zero sample:")
        for row in report["bar_counter_sample"]:
            print(f"  {row['item_name']} ({row['unit']}) = {row['qty_on_hand']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
