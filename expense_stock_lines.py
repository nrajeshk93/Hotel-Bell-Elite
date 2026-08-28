"""Resolve stock-in product lines for a ledger expense (indent or direct).

Used by purchase-verification / mobile Approvals detail. Ledger-only purchases
(no store_stock_movements link) return an empty lines list with source "none".
"""

from __future__ import annotations

import re
from typing import Any, Optional

_INDENT_RE = re.compile(r"\b(IND-[A-Z0-9-]+)\b", re.IGNORECASE)


def _money(value: object) -> float:
    try:
        return round(float(value or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def _movement_lines(conn, ref_type: str, ref_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT item_name, unit, qty_delta, unit_cost, notes
        FROM store_stock_movements
        WHERE ref_type = ? AND ref_id = ? AND movement_type = 'receive'
        ORDER BY id ASC
        """,
        (ref_type, int(ref_id)),
    ).fetchall()
    lines: list[dict[str, Any]] = []
    for row in rows:
        qty = abs(float(row["qty_delta"] or 0))
        unit_cost = _money(row["unit_cost"])
        lines.append(
            {
                "item_name": str(row["item_name"] or "").strip() or "—",
                "unit": str(row["unit"] or "").strip(),
                "qty": qty,
                "unit_cost": unit_cost,
                "amount": round(qty * unit_cost, 2),
                "notes": str(row["notes"] or ""),
            }
        )
    return lines


def _indent_lines_fallback(conn, indent_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT item_name, unit, quantity, quantity_received, approximate_price,
               pack_label
        FROM store_indent_lines
        WHERE indent_id = ?
        ORDER BY id ASC
        """,
        (int(indent_id),),
    ).fetchall()
    lines: list[dict[str, Any]] = []
    for row in rows:
        received = row["quantity_received"]
        qty = abs(float(received if received is not None else (row["quantity"] or 0)))
        unit_cost = _money(row["approximate_price"])
        pack = str(row["pack_label"] or "").strip()
        name = str(row["item_name"] or "").strip() or "—"
        if pack:
            name = f"{name} ({pack})"
        lines.append(
            {
                "item_name": name,
                "unit": str(row["unit"] or "").strip(),
                "qty": qty,
                "unit_cost": unit_cost,
                "amount": round(qty * unit_cost, 2),
                "notes": "",
            }
        )
    return lines


def _find_indent(conn, description: str) -> tuple[Optional[int], Optional[str]]:
    match = _INDENT_RE.search(description or "")
    if not match:
        return None, None
    indent_no = match.group(1).upper()
    row = conn.execute(
        "SELECT id, indent_no FROM store_indents WHERE UPPER(indent_no) = ?",
        (indent_no,),
    ).fetchone()
    if not row:
        return None, indent_no
    return int(row["id"]), str(row["indent_no"] or indent_no)


def expense_stock_detail(conn, expense_id: int) -> Optional[dict[str, Any]]:
    """Return expense header + product lines, or None if expense missing."""
    row = conn.execute(
        """
        SELECT e.id, e.expense_code, e.sales_date, e.description, e.amount,
               e.category, e.supplier_id, e.entry_kind, e.invoice_number,
               e.payment_type, e.transaction_id, e.company, e.location,
               s.name AS supplier_name,
               COALESCE((
                   SELECT SUM(a.amount) FROM purchase_verification_allocations a
                   WHERE a.expense_id = e.id
               ), 0) AS paid_amount
        FROM sales_update_expenses e
        LEFT JOIN suppliers s ON s.id = e.supplier_id
        WHERE e.id = ?
        """,
        (int(expense_id),),
    ).fetchone()
    if not row:
        return None

    amount = _money(row["amount"])
    paid = _money(row["paid_amount"])
    balance = round(amount - paid, 2)
    description = str(row["description"] or "")
    desc_l = description.lower()

    lines = _movement_lines(conn, "stock_inward_direct", int(row["id"]))
    source = "direct" if lines else "none"
    indent_id: Optional[int] = None
    indent_no: Optional[str] = None

    if not lines:
        indent_id, indent_no = _find_indent(conn, description)
        if indent_id:
            lines = _movement_lines(conn, "stock_inward", indent_id)
            if not lines:
                lines = _indent_lines_fallback(conn, indent_id)
            source = "indent" if lines else "indent_empty"

    if source == "direct" or "without indent" in desc_l:
        stock_mode = "Stock in · without indent"
    elif source in ("indent", "indent_empty"):
        stock_mode = "Stock in · with indent"
        if indent_no:
            stock_mode = f"{stock_mode} · {indent_no}"
    else:
        stock_mode = "Purchase"

    lines_total = round(sum(_money(line.get("amount")) for line in lines), 2)

    return {
        "ok": True,
        "expense": {
            "id": int(row["id"]),
            "expense_code": str(row["expense_code"] or ""),
            "sales_date": str(row["sales_date"] or ""),
            "description": description,
            "amount": amount,
            "balance": balance,
            "paid_amount": paid,
            "category": str(row["category"] or ""),
            "supplier_id": int(row["supplier_id"] or 0),
            "supplier_name": str(row["supplier_name"] or ""),
            "entry_kind": str(row["entry_kind"] or "expense"),
            "invoice_number": str(row["invoice_number"] or ""),
            "payment_type": str(row["payment_type"] or ""),
            "transaction_id": str(row["transaction_id"] or ""),
            "company": str(row["company"] or ""),
            "location": str(row["location"] or ""),
        },
        "lines": lines,
        "lines_total": lines_total,
        "source": source,
        "stock_mode": stock_mode,
        "indent_id": indent_id,
        "indent_no": indent_no,
    }
