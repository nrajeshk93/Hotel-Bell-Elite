"""Stores module — simple Bar/Kitchen indent-to-stock flow."""

from __future__ import annotations

import io
import re
import sqlite3
import uuid
from datetime import date, datetime
from typing import Any

from flask import Blueprint, flash, jsonify, redirect, render_template, request, send_file, url_for

from db import ensure_stores_schema, get_db
from embed_helpers import is_embed_request
from whatsapp_indent import (
    assign_fresh_approval_token,
    notify_indent_pending_whatsapp,
    supersede_indent_whatsapp_sends,
)
from workspace_access import user_can_access_stores_submodule

STORES_OUTLETS = (
    {"key": "bar", "label": "Bar"},
    {"key": "restaurant", "label": "Restaurant"},
)
OUTLET_KEYS = {item["key"] for item in STORES_OUTLETS}
# Indent filter can also use "All" (key stays "both" for existing URLs/data).
STORES_FILTER_OUTLETS = (
    {"key": "both", "label": "All"},
) + STORES_OUTLETS
PRODUCT_OUTLETS = (
    {"key": "both", "label": "Both"},
    {"key": "bar", "label": "Bar"},
    {"key": "restaurant", "label": "Restaurant"},
)
PRODUCT_OUTLET_KEYS = {item["key"] for item in PRODUCT_OUTLETS}
FILTER_OUTLET_KEYS = {item["key"] for item in STORES_FILTER_OUTLETS}
DEFAULT_UNITS = ("kg", "pcs", "liter", "dozen", "bunch", "bottle", "case", "pack")

STATUS_LABELS = {
    "draft": "Draft",
    "pending": "Waiting approval",
    "approved": "Approved",
    "rejected": "Rejected",
    "stocked": "Stocked",
    "open": "Open",
    "received": "Received in stock",
    "cancelled": "Cancelled",
}

INDENT_LIST_VIEWS = (
    ("pending", "Pending Approval"),
    ("approved", "Approved"),
    ("rejected", "Rejected"),
)
INDENT_LIST_VIEW_STATUSES = {
    "pending": ("draft", "pending"),
    "approved": ("approved",),
    "rejected": ("rejected",),
}
EDITABLE_INDENT_STATUSES = ("draft", "pending", "rejected")


def _parse_indent_list_view(raw: str | None) -> str:
    key = (raw or "").strip().lower()
    if key in INDENT_LIST_VIEW_STATUSES:
        return key
    return "pending"


PAGE_META = {
    "product_master": {
        "title": "Products",
        "subtitle": "Categories and products used when raising indents for Bar and Restaurant.",
        "step": "Master",
        "list_endpoint": "stores_product_master",
        "cta": "Add product",
        "cta_endpoint": "stores_product_master",
        "cta_args": {"focus": "form"},
        "show_outlet_tabs": True,
    },
    "indent": {
        "title": "Indent",
        "subtitle": "",
        "step": "1 · Indent",
        "list_endpoint": "stores_indent",
        "cta": "New Indent",
        "cta_endpoint": "stores_indent",
        "cta_args": {"focus": "form"},
    },
    "approvals": {
        "title": "Approvals",
        "subtitle": "Review waiting indents. Approve to buy, or reject.",
        "step": "2 · Approvals",
        "list_endpoint": "stores_approvals",
        "cta": None,
    },
    "purchase_requests": {
        "title": "Stock Inward",
        "subtitle": "",
        "step": "3 · Stock Inward",
        "list_endpoint": "stores_purchase_requests",
        "cta": None,
    },
    "stock": {
        "title": "Stock",
        "subtitle": "What is currently in the store for this outlet.",
        "step": "4 · Stock",
        "list_endpoint": "stores_stock",
        "cta": None,
    },
}

stores_bp = Blueprint("stores", __name__)

_pop_auth_notice = None
_get_user = None


def _bind_helpers(pop_auth_notice, get_user):
    global _pop_auth_notice, _get_user
    _pop_auth_notice = pop_auth_notice
    _get_user = get_user


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _whatsapp_indent_host_allowed() -> tuple[bool, str]:
    """Block live WhatsApp sends when this app host is not the webhook host.

    Meta delivers Approve/Reject webhooks to production only. Submitting from a
    local preview with live credentials creates tokens in the local DB that
    production cannot find (unknown_token). Set ``WHATSAPP_INDENT_PUBLIC_HOST``
    (e.g. belleliteaccounts.com) so off-host live sends fail with a clear flash.
    """
    import os

    expected = (os.environ.get("WHATSAPP_INDENT_PUBLIC_HOST") or "").strip().lower()
    if not expected:
        return True, ""
    try:
        from whatsapp_client import whatsapp_live_sends_allowed

        if not whatsapp_live_sends_allowed():
            return True, ""
    except Exception:
        pass
    host = (request.host or "").split(":")[0].strip().lower()
    if not host:
        return True, ""
    if host == expected or host.endswith("." + expected):
        return True, ""
    return (
        False,
        f"WhatsApp approval must be sent from {expected} (where webhooks arrive). "
        "Open Indent on that site and Send for Approval again — local preview "
        "cannot receive Approve/Reject clicks.",
    )


def _notify_indent_pending_whatsapp(conn, indent_id: int, outlet: str) -> None:
    """Best-effort WhatsApp indent_approval notify; never blocks indent save.

    Success is silent in the UI (indent flash already says sent for approval).
    Failures still surface so staff know WhatsApp did not go out.
    """
    allowed, host_msg = _whatsapp_indent_host_allowed()
    if not allowed:
        flash(host_msg, "error")
        return
    try:
        ok, message = notify_indent_pending_whatsapp(
            conn,
            int(indent_id),
            outlet_label=_outlet_label(outlet),
        )
        conn.commit()
        if not ok and message:
            flash(message, "error")
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        flash("Indent saved, but WhatsApp approval notify failed.", "error")


def _format_stores_dt(value: Any) -> str:
    """Display datetimes as ``19-July 10.05 AM`` (date-only → ``19-July``)."""
    if value is None:
        return ""
    text = str(value).strip()
    if not text or text in {"—", "-", "never"}:
        return text
    parsed = _parse_stores_dt(text)
    if parsed is None:
        return text
    day_month = f"{parsed.day}-{parsed.strftime('%B')}"
    if len(text) <= 10:
        return day_month
    hour12 = parsed.hour % 12 or 12
    ampm = "AM" if parsed.hour < 12 else "PM"
    return f"{day_month} {hour12}.{parsed.minute:02d} {ampm}"


def _parse_stores_dt(text: str) -> datetime | None:
    for fmt, length in (
        ("%Y-%m-%d %H:%M:%S", 19),
        ("%Y-%m-%d %H:%M", 16),
        ("%Y-%m-%d", 10),
    ):
        chunk = text[:length]
        if len(chunk) < length:
            continue
        try:
            return datetime.strptime(chunk, fmt)
        except ValueError:
            continue
    return None


def _format_stores_date_line(value: Any) -> str:
    """``19 July`` for multi-line submitted cells."""
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    parsed = _parse_stores_dt(text)
    if parsed is None:
        return text
    return f"{parsed.day} {parsed.strftime('%B')}"


def _format_stores_time_line(value: Any) -> str:
    """``10:05 AM`` for multi-line submitted cells."""
    if value is None:
        return ""
    text = str(value).strip()
    if not text or len(text) <= 10:
        return ""
    parsed = _parse_stores_dt(text)
    if parsed is None:
        return ""
    hour12 = parsed.hour % 12 or 12
    ampm = "AM" if parsed.hour < 12 else "PM"
    return f"{hour12}:{parsed.minute:02d} {ampm}"


def _parse_optional_price(raw: str | None) -> tuple[float | None, str | None]:
    text = str(raw or "").strip().replace(",", "")
    if not text:
        return None, None
    try:
        value = float(text)
    except (TypeError, ValueError):
        return None, "Approximate price must be a number."
    if value < 0:
        return None, "Approximate price cannot be negative."
    return round(value, 2), None


def _format_optional_price(value: Any) -> str:
    if value is None or value == "":
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    if number != number:  # NaN
        return ""
    if number == int(number):
        return str(int(number))
    return f"{number:.2f}".rstrip("0").rstrip(".")


def _normalize_outlet_key(raw: str | None) -> str:
    key = (raw or "").strip().lower()
    # Legacy stores key — keep old bookmarks working.
    if key == "kitchen":
        return "restaurant"
    return key


def _parse_outlet(raw: str | None) -> str:
    """Operational outlet used for stock / saved indents (never 'both')."""
    key = _normalize_outlet_key(raw or "bar")
    return key if key in OUTLET_KEYS else "bar"


def _parse_outlet_filter(raw: str | None) -> str:
    """Outlet filter for Stores list UI — All, Bar, or Restaurant. Defaults to All."""
    if raw is None or not str(raw).strip():
        return "both"
    key = _normalize_outlet_key(raw)
    return key if key in FILTER_OUTLET_KEYS else "both"


def _outlet_label(outlet: str) -> str:
    for item in STORES_FILTER_OUTLETS:
        if item["key"] == outlet:
            return item["label"]
    return outlet.title()


def _outlet_match_sql(column: str, outlet: str) -> tuple[str, tuple[Any, ...]]:
    """SQL fragment + params for list filters (supports All)."""
    if outlet == "both":
        return f"{column} IN ('bar', 'restaurant')", ()
    return f"{column} = ?", (outlet,)


def _parse_product_outlet(raw: str | None) -> str:
    key = _normalize_outlet_key(raw or "restaurant")
    return key if key in PRODUCT_OUTLET_KEYS else "restaurant"


def _product_outlet_label(outlet: str) -> str:
    key = _parse_product_outlet(outlet)
    for item in PRODUCT_OUTLETS:
        if item["key"] == key:
            return item["label"]
    return "Restaurant"


def _status_label(status: str) -> str:
    return STATUS_LABELS.get(status, status.replace("_", " ").title())


def _next_doc_no(conn, table: str, column: str, prefix: str, outlet: str) -> str:
    day = date.today().strftime("%Y%m%d")
    outlet_code = outlet.upper()[:3]
    like = f"{prefix}-{outlet_code}-{day}-%"
    row = conn.execute(
        f"SELECT {column} AS doc_no FROM {table} WHERE {column} LIKE ? ORDER BY id DESC LIMIT 1",
        (like,),
    ).fetchone()
    seq = 1
    if row and row["doc_no"]:
        try:
            seq = int(str(row["doc_no"]).rsplit("-", 1)[-1]) + 1
        except ValueError:
            seq = 1
    return f"{prefix}-{outlet_code}-{day}-{seq:03d}"


def _parse_lines_from_form(form) -> list[dict[str, Any]]:
    names = form.getlist("item_name")
    qtys = form.getlist("quantity")
    units = form.getlist("unit")
    prices = form.getlist("approximate_price")
    lines = []
    for idx, name in enumerate(names):
        item_name = (name or "").strip()
        if not item_name:
            continue
        try:
            qty = float(qtys[idx] if idx < len(qtys) else 0)
        except (TypeError, ValueError, IndexError):
            qty = 0
        if qty <= 0:
            continue
        unit = (units[idx] if idx < len(units) else "pcs") or "pcs"
        unit = unit.strip() or "pcs"
        price_raw = prices[idx] if idx < len(prices) else ""
        approx_price, _price_err = _parse_optional_price(price_raw)
        lines.append({
            "item_name": item_name,
            "quantity": qty,
            "unit": unit,
            "notes": "",
            "approximate_price": approx_price,
        })
    return lines


def _unit_cost_with_tax(unit_price: Any, tax_percent: Any) -> float | None:
    """Unit cost including tax: price × (1 + tax%/100)."""
    try:
        price = float(unit_price)
    except (TypeError, ValueError):
        return None
    if price <= 0 or price != price:
        return None
    try:
        tax = float(tax_percent or 0)
    except (TypeError, ValueError):
        tax = 0.0
    if tax < 0:
        tax = 0.0
    return round(price * (1.0 + tax / 100.0), 4)


def _adjust_stock(
    conn,
    *,
    outlet,
    item_name,
    unit,
    qty_delta,
    movement_type,
    ref_type,
    ref_id,
    notes,
    user_id,
    unit_cost=None,
):
    existing = conn.execute(
        """
        SELECT id, qty_on_hand FROM store_stock_items
        WHERE outlet = ? AND lower(item_name) = lower(?) AND lower(unit) = lower(?)
        """,
        (outlet, item_name, unit),
    ).fetchone()
    if existing:
        new_qty = float(existing["qty_on_hand"] or 0) + float(qty_delta)
        if new_qty < -0.0001:
            raise ValueError(f"Not enough stock for {item_name} ({unit}).")
        conn.execute(
            """
            UPDATE store_stock_items
            SET qty_on_hand = ?, item_name = ?, unit = ?, updated_at = ?
            WHERE id = ?
            """,
            (round(new_qty, 3), item_name, unit, _now(), existing["id"]),
        )
    else:
        if qty_delta < 0:
            raise ValueError(f"Not enough stock for {item_name} ({unit}).")
        conn.execute(
            """
            INSERT INTO store_stock_items (outlet, item_name, unit, qty_on_hand, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (outlet, item_name, unit, round(float(qty_delta), 3), _now()),
        )
    cost_value = None
    if unit_cost is not None:
        try:
            cost_value = float(unit_cost)
            if cost_value <= 0 or cost_value != cost_value:
                cost_value = None
        except (TypeError, ValueError):
            cost_value = None
    conn.execute(
        """
        INSERT INTO store_stock_movements
            (outlet, item_name, unit, qty_delta, movement_type, ref_type, ref_id,
             notes, unit_cost, created_by, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            outlet,
            item_name,
            unit,
            float(qty_delta),
            movement_type,
            ref_type,
            ref_id,
            notes or "",
            cost_value,
            user_id,
            _now(),
        ),
    )


def _load_product_catalog(conn, stores_outlet: str | None = None):
    """Load product master.

    When stores_outlet is Bar/Restaurant, include that outlet's products plus Both.
    When stores_outlet is Both (or omitted), include every active product.
    """
    filter_outlet = _parse_outlet_filter(stores_outlet) if stores_outlet else None
    params: list[Any] = []
    outlet_sql = ""
    if filter_outlet and filter_outlet != "both":
        outlet_sql = " AND lower(coalesce(p.outlet, '')) IN (?, 'both')"
        params.append(filter_outlet)
    rows = conn.execute(
        f"""
        SELECT c.id AS category_id, c.name AS category_name, c.sort_order AS category_sort,
               p.id AS product_id, p.name AS product_name, p.default_unit, p.outlet,
               p.approximate_price, p.is_active, p.sort_order
        FROM store_product_categories c
        LEFT JOIN store_products p
          ON p.category_id = c.id AND p.is_active = 1{outlet_sql}
        WHERE c.is_active = 1
        ORDER BY c.sort_order, c.name, p.sort_order, p.name
        """,
        params,
    ).fetchall()
    categories = []
    by_id = {}
    for row in rows:
        cat_id = row["category_id"]
        if cat_id not in by_id:
            node = {
                "id": cat_id,
                "name": row["category_name"],
                "products": [],
            }
            by_id[cat_id] = node
            categories.append(node)
        if row["product_id"]:
            by_id[cat_id]["products"].append({
                "id": row["product_id"],
                "name": row["product_name"],
                "default_unit": row["default_unit"],
                "outlet": _parse_product_outlet(row["outlet"]),
                "outlet_label": _product_outlet_label(row["outlet"]),
                "approximate_price": row["approximate_price"],
                "approximate_price_display": _format_optional_price(row["approximate_price"]),
            })
    if filter_outlet:
        categories = [cat for cat in categories if cat["products"]]
    return categories


def _product_names_for_outlet(conn, stores_outlet: str) -> set[str]:
    catalog = _load_product_catalog(conn, stores_outlet=stores_outlet)
    names: set[str] = set()
    for cat in catalog:
        for product in cat["products"]:
            names.add(str(product["name"]).strip().lower())
    return names


def _format_ledger_qty(value: Any) -> str:
    try:
        n = float(value or 0)
    except (TypeError, ValueError):
        return "0"
    if abs(n - round(n)) < 0.0001:
        return str(int(round(n)))
    return ("%g" % (round(n * 1000) / 1000))


def _stores_ledger_payload(conn, outlet: str) -> dict[str, Any]:
    """Indent → inward progress ledger for the Indent page popup."""
    outlet_key = _parse_outlet_filter(outlet)
    outlet_sql, outlet_params = _outlet_match_sql("i.outlet", outlet_key)
    rows = conn.execute(
        f"""
        SELECT i.id, i.indent_no, i.outlet, i.status, i.created_at,
               COALESCE((
                   SELECT COUNT(*) FROM store_indent_lines l WHERE l.indent_id = i.id
               ), 0) AS line_count,
               COALESCE((
                   SELECT SUM(COALESCE(l.quantity, 0)) FROM store_indent_lines l WHERE l.indent_id = i.id
               ), 0) AS qty_ordered,
               COALESCE((
                   SELECT SUM(COALESCE(l.quantity_received, 0)) FROM store_indent_lines l WHERE l.indent_id = i.id
               ), 0) AS qty_received,
               COALESCE((
                   SELECT SUM(
                       CASE
                         WHEN COALESCE(l.quantity, 0) - COALESCE(l.quantity_received, 0) > 0.0001
                         THEN COALESCE(l.quantity, 0) - COALESCE(l.quantity_received, 0)
                         ELSE 0
                       END
                   )
                   FROM store_indent_lines l WHERE l.indent_id = i.id
               ), 0) AS qty_pending
        FROM store_indents i
        WHERE {outlet_sql}
        ORDER BY i.created_at DESC, i.id DESC
        LIMIT 100
        """,
        outlet_params,
    ).fetchall()

    indent_ids = [int(row["id"]) for row in rows]
    pending_lines_by_id: dict[int, list[dict[str, Any]]] = {iid: [] for iid in indent_ids}
    received_lines_by_id: dict[int, list[dict[str, Any]]] = {iid: [] for iid in indent_ids}
    item_names_by_id: dict[int, list[str]] = {iid: [] for iid in indent_ids}
    if indent_ids:
        placeholders = ",".join("?" for _ in indent_ids)
        line_rows = conn.execute(
            f"""
            SELECT indent_id, item_name, quantity, quantity_received, unit
            FROM store_indent_lines
            WHERE indent_id IN ({placeholders})
            ORDER BY id
            """,
            indent_ids,
        ).fetchall()
        for line in line_rows:
            try:
                ordered = float(line["quantity"] or 0)
            except (TypeError, ValueError):
                ordered = 0.0
            try:
                received = float(line["quantity_received"] or 0)
            except (TypeError, ValueError, KeyError):
                received = 0.0
            pending = ordered - received
            if pending < 0:
                pending = 0.0
            iid = int(line["indent_id"])
            item_name = (line["item_name"] or "").strip()
            if item_name:
                item_names_by_id.setdefault(iid, []).append(item_name)
            line_payload = {
                "item_name": item_name,
                "unit": line["unit"] or "",
                "qty_ordered": ordered,
                "qty_received": received,
                "qty_pending": pending if pending > 0.0001 else 0.0,
                "qty_ordered_display": _format_ledger_qty(ordered),
                "qty_received_display": _format_ledger_qty(received),
                "qty_pending_display": _format_ledger_qty(pending if pending > 0.0001 else 0.0),
            }
            if pending > 0.0001:
                pending_lines_by_id.setdefault(iid, []).append(line_payload)
            if received > 0.0001:
                received_lines_by_id.setdefault(iid, []).append(line_payload)

    ledger_rows: list[dict[str, Any]] = []
    indents_created = 0
    qty_ordered_sum = 0.0
    qty_received_sum = 0.0
    qty_pending_sum = 0.0
    for row in rows:
        indents_created += 1
        try:
            ordered = float(row["qty_ordered"] or 0)
        except (TypeError, ValueError):
            ordered = 0.0
        try:
            received = float(row["qty_received"] or 0)
        except (TypeError, ValueError):
            received = 0.0
        try:
            pending = float(row["qty_pending"] or 0)
        except (TypeError, ValueError):
            pending = 0.0
        if pending < 0:
            pending = 0.0
        qty_ordered_sum += ordered
        qty_received_sum += received
        qty_pending_sum += pending
        outlet_val = _normalize_outlet_key(row["outlet"] or "restaurant")
        if outlet_val not in ("bar", "restaurant"):
            outlet_val = "restaurant"
        iid = int(row["id"])
        status = row["status"] or ""
        pending_lines = pending_lines_by_id.get(iid, [])
        received_lines = received_lines_by_id.get(iid, [])
        item_names = item_names_by_id.get(iid, [])
        can_view_pending = status == "approved" and pending > 0.0001 and bool(pending_lines)
        can_view_received = received > 0.0001 and bool(received_lines)
        indent_no = row["indent_no"] or ""
        status_label = _status_label(status)
        created_at = _format_stores_dt(row["created_at"] or "")
        outlet_label = _outlet_label(outlet_val)
        qty_ordered_display = _format_ledger_qty(ordered)
        qty_received_display = _format_ledger_qty(received)
        qty_pending_display = _format_ledger_qty(pending)
        search_parts = [
            indent_no,
            outlet_val,
            outlet_label,
            status,
            status_label,
            created_at,
            qty_ordered_display,
            qty_received_display,
            qty_pending_display,
            *item_names,
        ]
        search_text = " ".join(str(part or "").lower() for part in search_parts if part)
        ledger_rows.append({
            "id": iid,
            "indent_no": indent_no,
            "outlet": outlet_val,
            "outlet_label": outlet_label,
            "status": status,
            "status_label": status_label,
            "created_at": created_at,
            "line_count": int(row["line_count"] or 0),
            "qty_ordered": ordered,
            "qty_received": received,
            "qty_pending": pending,
            "qty_ordered_display": qty_ordered_display,
            "qty_received_display": qty_received_display,
            "qty_pending_display": qty_pending_display,
            "can_view_pending": can_view_pending,
            "can_view_received": can_view_received,
            "pending_lines": pending_lines if can_view_pending else [],
            "received_lines": received_lines if can_view_received else [],
            "item_names": item_names,
            "search_text": search_text,
            "inward_url": (
                url_for("stores_purchase_requests", outlet=outlet_val, indent=iid)
                if can_view_pending
                else ""
            ),
        })

    return {
        "summary": {
            "indents_created": indents_created,
            "qty_ordered": qty_ordered_sum,
            "qty_received": qty_received_sum,
            "qty_pending": qty_pending_sum,
            "qty_ordered_display": _format_ledger_qty(qty_ordered_sum),
            "qty_received_display": _format_ledger_qty(qty_received_sum),
            "qty_pending_display": _format_ledger_qty(qty_pending_sum),
        },
        "rows": ledger_rows,
    }


def _indent_view_payload(conn, indents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Serialize indent rows + lines for the list-page view modal."""
    if not indents:
        return []
    indent_ids = [int(row["id"]) for row in indents if row.get("id") is not None]
    lines_by_id: dict[int, list[dict[str, Any]]] = {iid: [] for iid in indent_ids}
    if indent_ids:
        placeholders = ",".join("?" for _ in indent_ids)
        line_rows = conn.execute(
            f"""
            SELECT indent_id, item_name, quantity, unit, notes, approximate_price
            FROM store_indent_lines
            WHERE indent_id IN ({placeholders})
            ORDER BY id
            """,
            indent_ids,
        ).fetchall()
        for line in line_rows:
            approx = line["approximate_price"] if "approximate_price" in line.keys() else None
            lines_by_id.setdefault(int(line["indent_id"]), []).append({
                "item_name": line["item_name"],
                "quantity": line["quantity"],
                "unit": line["unit"] or "",
                "notes": line["notes"] or "",
                "approximate_price": approx,
                "approximate_price_display": _format_optional_price(approx),
            })
    payload = []
    for row in indents:
        iid = int(row["id"])
        outlet_key = _parse_outlet(row.get("outlet"))
        payload.append({
            "id": iid,
            "indent_no": row.get("indent_no") or "",
            "outlet": outlet_key,
            "outlet_label": _outlet_label(outlet_key),
            "status": row.get("status") or "",
            "status_label": _status_label(row.get("status") or ""),
            "notes": row.get("notes") or "",
            "decision_note": row.get("decision_note") or "",
            "created_at": _format_stores_dt(row.get("created_at") or ""),
            "created_by_name": row.get("created_by_name") or "",
            "decided_at": _format_stores_dt(row.get("decided_at") or ""),
            "decided_by_name": row.get("decided_by_name") or "",
            "decided_by_username": row.get("decided_by_username") or "",
            "line_count": int(row.get("line_count") or 0),
            "total_qty": row.get("total_qty") or 0,
            "lines": lines_by_id.get(iid, []),
            "can_mutate": (row.get("status") or "") in EDITABLE_INDENT_STATUSES,
            "can_download_po": (row.get("status") or "") == "approved",
            "po_url": url_for("stores_indent_purchase_order", indent_id=iid)
            if (row.get("status") or "") == "approved"
            else "",
            "edit_url": url_for(
                "stores_indent",
                outlet=outlet_key,
                edit=iid,
                focus="form",
            ),
        })
    return payload


def _load_flat_products(conn, stores_outlet: str | None = None) -> list[dict[str, Any]]:
    filter_outlet = _parse_outlet_filter(stores_outlet) if stores_outlet else None
    params: list[Any] = []
    outlet_sql = ""
    if filter_outlet and filter_outlet != "both":
        outlet_sql = " AND lower(coalesce(p.outlet, '')) IN (?, 'both')"
        params.append(filter_outlet)
    rows = conn.execute(
        f"""
        SELECT p.id, p.name, p.default_unit, p.outlet, p.approximate_price, p.category_id,
               c.name AS category_name, c.sort_order AS category_sort, p.sort_order
        FROM store_products p
        JOIN store_product_categories c ON c.id = p.category_id
        WHERE p.is_active = 1 AND c.is_active = 1{outlet_sql}
        ORDER BY c.sort_order, c.name, p.sort_order, p.name
        """,
        params,
    ).fetchall()
    products = []
    for row in rows:
        item = dict(row)
        item["outlet"] = _parse_product_outlet(item.get("outlet"))
        item["outlet_label"] = _product_outlet_label(item["outlet"])
        item["approximate_price_display"] = _format_optional_price(item.get("approximate_price"))
        products.append(item)
    return products


def _first_stores_endpoint(user) -> str | None:
    preferred = (
        "product_master",
        "indent",
        "approvals",
        "purchase_requests",
        "stock",
    )
    endpoint_map = {
        "product_master": "stores_product_master",
        "indent": "stores_indent",
        "approvals": "stores_approvals",
        "purchase_requests": "stores_purchase_requests",
        "stock": "stores_stock",
    }
    for key in preferred:
        if user_can_access_stores_submodule(user, key):
            return endpoint_map[key]
    return None


def _page_render(page_key: str, **kwargs):
    user = _get_user() if _get_user else None
    raw_outlet = kwargs.pop("outlet", None) or request.args.get("outlet")
    # List filters use All/Bar/Restaurant across Stores pages (including Product Master).
    outlet = _parse_outlet_filter(raw_outlet)
    outlets_for_ui = STORES_FILTER_OUTLETS
    meta = PAGE_META[page_key]
    cta_url = None
    if meta.get("cta_endpoint"):
        args = dict(meta.get("cta_args") or {})
        if args.get("focus") == "form":
            # Create forms need a concrete outlet — only carry Bar/Restaurant.
            if outlet in OUTLET_KEYS:
                args["outlet"] = outlet
        else:
            args["outlet"] = outlet
        cta_url = url_for(meta["cta_endpoint"], **args)
    kwargs.setdefault("auth_notice", _pop_auth_notice() if _pop_auth_notice else None)
    if page_key == "indent":
        kwargs.setdefault("indent_write_outlets", STORES_OUTLETS)
    indent_form_unset = bool(kwargs.pop("indent_form_unset", False))
    selected_outlet = "" if indent_form_unset else outlet
    selected_outlet_label = "Select outlet" if indent_form_unset else _outlet_label(outlet)
    return render_template(
        "stores_page.html",
        de_nav_section="stores",
        de_nav_stores_view=page_key,
        stores_outlets=outlets_for_ui,
        selected_outlet=selected_outlet,
        selected_outlet_label=selected_outlet_label,
        indent_form_unset=indent_form_unset,
        page_key=page_key,
        page_title=meta["title"],
        page_subtitle=meta["subtitle"],
        page_list_endpoint=meta["list_endpoint"],
        page_cta=meta.get("cta"),
        page_cta_url=cta_url,
        show_outlet_tabs=meta.get("show_outlet_tabs", True),
        status_label=_status_label,
        stores_dt=_format_stores_dt,
        stores_date=_format_stores_date_line,
        stores_time=_format_stores_time_line,
        default_units=kwargs.pop("default_units", DEFAULT_UNITS),
        product_outlets=PRODUCT_OUTLETS,
        current_user=user,
        **kwargs,
    )


@stores_bp.route("/stores/product-master", methods=["GET", "POST"])
def stores_product_master():
    user = _get_user()
    outlet = _parse_outlet_filter(
        request.args.get("outlet") or request.form.get("list_outlet")
    )
    edit_id = request.args.get("edit") or request.form.get("product_id") or ""
    try:
        edit_id_int = int(edit_id) if str(edit_id).strip() else 0
    except (TypeError, ValueError):
        edit_id_int = 0
    focus = (
        request.args.get("focus") == "form"
        or request.method == "POST"
        or bool(edit_id_int)
    )
    errors: list[str] = []
    show_category_modal = False
    show_unit_modal = False
    category_form_name = ""
    unit_form_name = ""
    form = {
        "product_id": "",
        "category_id": "",
        "name": "",
        "default_unit": "kg",
        "outlet": "",
        "approximate_price": "",
    }

    def _pm_redirect(**extra):
        args = {"outlet": outlet}
        args.update(extra)
        return redirect(url_for("stores_product_master", **args))

    conn = get_db()
    try:
        ensure_stores_schema(conn)
        if request.method == "POST":
            action = (request.form.get("action") or "save_product").strip()
            if action == "save_category":
                cat_name = (request.form.get("category_name") or "").strip()
                category_form_name = cat_name
                if not cat_name:
                    errors.append("Category name is required.")
                    show_category_modal = True
                else:
                    exists = conn.execute(
                        "SELECT id FROM store_product_categories WHERE lower(name) = lower(?)",
                        (cat_name,),
                    ).fetchone()
                    if exists:
                        errors.append("That category already exists.")
                        show_category_modal = True
                    else:
                        max_sort = conn.execute(
                            "SELECT COALESCE(MAX(sort_order), 0) AS m FROM store_product_categories"
                        ).fetchone()["m"]
                        cursor = conn.execute(
                            """
                            INSERT INTO store_product_categories (name, sort_order, is_active)
                            VALUES (?, ?, 1)
                            """,
                            (cat_name, int(max_sort) + 10),
                        )
                        conn.commit()
                        flash("Category added.", "ok")
                        return _pm_redirect(focus="form", category=cursor.lastrowid)
            elif action == "save_unit":
                unit_name = (request.form.get("unit_name") or "").strip()
                unit_form_name = unit_name
                if not unit_name:
                    errors.append("Unit name is required.")
                    show_unit_modal = True
                else:
                    exists = conn.execute(
                        "SELECT id FROM store_product_units WHERE lower(name) = lower(?)",
                        (unit_name,),
                    ).fetchone()
                    if exists:
                        errors.append("That unit already exists.")
                        show_unit_modal = True
                    else:
                        max_sort = conn.execute(
                            "SELECT COALESCE(MAX(sort_order), 0) AS m FROM store_product_units"
                        ).fetchone()["m"]
                        conn.execute(
                            """
                            INSERT INTO store_product_units (name, sort_order, is_active)
                            VALUES (?, ?, 1)
                            """,
                            (unit_name, int(max_sort) + 10),
                        )
                        conn.commit()
                        flash("Unit added.", "ok")
                        return _pm_redirect(focus="form", unit=unit_name)
            else:
                form["name"] = (request.form.get("name") or "").strip()
                form["default_unit"] = (request.form.get("default_unit") or "kg").strip() or "kg"
                raw_outlet = (request.form.get("outlet") or "").strip().lower()
                form["outlet"] = raw_outlet if raw_outlet in PRODUCT_OUTLET_KEYS else ""
                form["category_id"] = (request.form.get("category_id") or "").strip()
                form["product_id"] = (request.form.get("product_id") or "").strip()
                approx_price, price_error = _parse_optional_price(request.form.get("approximate_price"))
                form["approximate_price"] = _format_optional_price(approx_price) if approx_price is not None else (request.form.get("approximate_price") or "").strip()
                try:
                    category_id = int(form["category_id"])
                except (TypeError, ValueError):
                    category_id = 0
                try:
                    product_id = int(form["product_id"]) if form["product_id"] else 0
                except (TypeError, ValueError):
                    product_id = 0
                if not form["name"]:
                    errors.append("Product name is required.")
                if not category_id:
                    errors.append("Choose a category.")
                if not form["outlet"]:
                    errors.append("Choose an outlet.")
                if price_error:
                    errors.append(price_error)
                if not errors:
                    exists = conn.execute(
                        """
                        SELECT id FROM store_products
                        WHERE category_id = ? AND lower(name) = lower(?) AND is_active = 1
                          AND (? = 0 OR id != ?)
                        """,
                        (category_id, form["name"], product_id, product_id),
                    ).fetchone()
                    if exists:
                        errors.append("That product already exists in this category.")
                    elif product_id:
                        row = conn.execute(
                            "SELECT id FROM store_products WHERE id = ? AND is_active = 1",
                            (product_id,),
                        ).fetchone()
                        if not row:
                            errors.append("Product not found.")
                        else:
                            conn.execute(
                                """
                                UPDATE store_products
                                SET category_id = ?, name = ?, default_unit = ?, outlet = ?,
                                    approximate_price = ?, updated_at = ?
                                WHERE id = ?
                                """,
                                (
                                    category_id,
                                    form["name"],
                                    form["default_unit"],
                                    form["outlet"],
                                    approx_price,
                                    _now(),
                                    product_id,
                                ),
                            )
                            conn.commit()
                            flash("Product updated.", "ok")
                            return _pm_redirect()
                    else:
                        max_sort = conn.execute(
                            """
                            SELECT COALESCE(MAX(sort_order), 0) AS m
                            FROM store_products WHERE category_id = ?
                            """,
                            (category_id,),
                        ).fetchone()["m"]
                        conn.execute(
                            """
                            INSERT INTO store_products
                                (category_id, name, default_unit, outlet, approximate_price,
                                 is_active, sort_order, updated_at)
                            VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                            """,
                            (
                                category_id,
                                form["name"],
                                form["default_unit"],
                                form["outlet"],
                                approx_price,
                                int(max_sort) + 10,
                                _now(),
                            ),
                        )
                        conn.commit()
                        flash("Product added to master.", "ok")
                        return _pm_redirect()

        if edit_id_int and request.method == "GET":
            row = conn.execute(
                """
                SELECT id, category_id, name, default_unit, outlet, approximate_price
                FROM store_products
                WHERE id = ? AND is_active = 1
                """,
                (edit_id_int,),
            ).fetchone()
            if row:
                form["product_id"] = str(row["id"])
                form["category_id"] = str(row["category_id"])
                form["name"] = row["name"]
                form["default_unit"] = row["default_unit"] or "kg"
                form["outlet"] = _parse_product_outlet(row["outlet"] if "outlet" in row.keys() else None)
                form["approximate_price"] = _format_optional_price(
                    row["approximate_price"] if "approximate_price" in row.keys() else None
                )
            else:
                flash("Product not found.", "error")
                return _pm_redirect()
        elif request.method == "GET" and not form["category_id"]:
            preselect = (request.args.get("category") or "").strip()
            if preselect.isdigit():
                form["category_id"] = preselect
        if request.method == "GET":
            preselect_unit = (request.args.get("unit") or "").strip()
            if preselect_unit:
                form["default_unit"] = preselect_unit

        catalog = _load_product_catalog(conn, stores_outlet=outlet)
        products = _load_flat_products(conn, stores_outlet=outlet)
        categories = conn.execute(
            """
            SELECT id, name FROM store_product_categories
            WHERE is_active = 1
            ORDER BY sort_order, name
            """
        ).fetchall()
        unit_rows = conn.execute(
            """
            SELECT name FROM store_product_units
            WHERE is_active = 1
            ORDER BY sort_order, name
            """
        ).fetchall()
        product_units = [row["name"] for row in unit_rows]
        if not product_units:
            product_units = list(DEFAULT_UNITS)
        if form.get("default_unit") and form["default_unit"] not in product_units:
            product_units = list(product_units) + [form["default_unit"]]
        product_count = len(products)
    finally:
        conn.close()

    if request.method == "GET" and is_embed_request():
        return render_template(
            "partials/master_embed/product.html",
            stores_outlets=STORES_FILTER_OUTLETS,
            selected_outlet=outlet,
            selected_outlet_label=_outlet_label(outlet),
            products=products,
            product_count=product_count,
        )

    return _page_render(
        "product_master",
        outlet=outlet,
        catalog=catalog,
        products=products,
        categories=[dict(row) for row in categories],
        default_units=product_units,
        product_count=product_count,
        show_form=focus or bool(errors) or show_category_modal or show_unit_modal,
        show_category_modal=show_category_modal,
        show_unit_modal=show_unit_modal,
        category_form_name=category_form_name,
        unit_form_name=unit_form_name,
        form=form,
        errors=errors,
        editing=bool(form.get("product_id")),
    )


@stores_bp.route("/stores/product-master/<int:product_id>/delete", methods=["GET", "POST"])
def stores_product_delete(product_id: int):
    _get_user()
    outlet = _parse_outlet_filter(request.args.get("outlet"))
    conn = get_db()
    try:
        ensure_stores_schema(conn)
        row = conn.execute(
            "SELECT id, name FROM store_products WHERE id = ? AND is_active = 1",
            (product_id,),
        ).fetchone()
        if not row:
            flash("Product not found.", "error")
        else:
            conn.execute(
                """
                UPDATE store_products
                SET is_active = 0, updated_at = ?
                WHERE id = ?
                """,
                (_now(), product_id),
            )
            conn.commit()
            flash(f"Deleted {row['name']}.", "ok")
    finally:
        conn.close()
    return redirect(url_for("stores_product_master", outlet=outlet))

@stores_bp.route("/stores")
def stores():
    user = _get_user()
    endpoint = _first_stores_endpoint(user)
    if not endpoint:
        flash("No Procurement & Inventory pages are available for this account.", "error")
        return redirect(url_for("home"))
    return redirect(
        url_for(endpoint, outlet=request.args.get("outlet") or "both")
    )


@stores_bp.route("/stores/indent", methods=["GET", "POST"])
def stores_indent():
    outlet = _parse_outlet_filter(request.args.get("outlet") or request.form.get("outlet"))
    list_view = _parse_indent_list_view(request.args.get("view") or request.form.get("view"))
    user = _get_user()
    edit_raw = request.args.get("edit") or request.form.get("indent_id") or ""
    try:
        edit_id = int(edit_raw) if str(edit_raw).strip() else 0
    except (TypeError, ValueError):
        edit_id = 0
    # Edit opens in a list-page modal; full-page form is for New Indent / POST errors.
    focus = (
        request.args.get("focus") == "form"
        or request.method == "POST"
    )
    open_edit_id = 0
    errors: list[str] = []
    form = {
        "indent_id": "",
        "notes": "",
        "submission_token": "",
        "lines": [{"item_name": "", "quantity": "", "unit": "kg", "notes": "", "approximate_price": ""}],
    }

    conn = get_db()
    try:
        ensure_stores_schema(conn)
        if request.method == "POST":
            form["notes"] = (request.form.get("notes") or "").strip()
            form["indent_id"] = (request.form.get("indent_id") or "").strip()
            form["submission_token"] = (request.form.get("submission_token") or "").strip()
            lines = _parse_lines_from_form(request.form)
            form["lines"] = lines or [{"item_name": "", "quantity": "", "unit": "kg", "notes": "", "approximate_price": ""}]
            for line in form["lines"]:
                line["approximate_price_display"] = _format_optional_price(line.get("approximate_price"))
            action = (request.form.get("action") or "save").strip()
            form_outlet_raw = (request.form.get("outlet") or "").strip()
            if not form_outlet_raw or _parse_outlet_filter(form_outlet_raw) == "both":
                errors.append("Choose Bar or Restaurant before saving this indent.")
                write_outlet = ""
            else:
                write_outlet = _parse_outlet(form_outlet_raw)
            # Edit modal may send indent_id in the body and/or ?edit= on the action URL.
            indent_id_raw = (
                form.get("indent_id")
                or request.form.get("indent_id")
                or request.args.get("edit")
                or ""
            ).strip()
            try:
                indent_id = int(indent_id_raw) if indent_id_raw else 0
            except (TypeError, ValueError):
                indent_id = 0
            form["indent_id"] = str(indent_id) if indent_id else ""
            existing = None
            if indent_id:
                existing = conn.execute(
                    "SELECT * FROM store_indents WHERE id = ?",
                    (indent_id,),
                ).fetchone()
                if not existing:
                    errors.append("Indent not found.")
                    indent_id = 0
                elif existing["status"] not in EDITABLE_INDENT_STATUSES:
                    errors.append("Only draft, waiting, or rejected indents can be edited.")
                else:
                    write_outlet = _parse_outlet(existing["outlet"])
                    outlet = write_outlet
            if not lines:
                errors.append("Add at least one item with a quantity.")
            else:
                missing_price = [
                    line["item_name"]
                    for line in lines
                    if line.get("approximate_price") is None
                    or float(line.get("approximate_price") or 0) <= 0
                ]
                if missing_price:
                    errors.append("Enter an approximate price greater than 0 for each item.")
            if not errors and lines and write_outlet:
                allowed = _product_names_for_outlet(conn, write_outlet)
                if allowed:
                    bad = sorted({
                        line["item_name"]
                        for line in lines
                        if str(line.get("item_name") or "").strip().lower() not in allowed
                    })
                    if bad:
                        errors.append(
                            "These items are not in the "
                            f"{_outlet_label(write_outlet)} product master: {', '.join(bad)}."
                        )
            if not errors and write_outlet:
                # Create form: save=draft, submit=pending.
                # Edit modal Save is the final save → always Waiting approval (pending).
                if indent_id and existing:
                    status = "pending"
                else:
                    status = "pending" if action == "submit" else "draft"
                if indent_id and existing:
                    prior_status = (existing["status"] or "")
                    # Fresh submitted_at only when (re)entering pending so WhatsApp
                    # idempotency treats reject→resubmit as a new approval round.
                    if status == "pending" and prior_status != "pending":
                        submitted_at = _now()
                    elif status == "pending":
                        submitted_at = existing["submitted_at"] or _now()
                    else:
                        submitted_at = None
                    # Bind the WHERE to the status we read earlier so a concurrent duplicate
                    # request (e.g. an overlapping double-submit) can't both win a "new
                    # approval round" transition and each fire off their own WhatsApp send.
                    update_cur = conn.execute(
                        """
                        UPDATE store_indents
                        SET notes = ?,
                            status = ?,
                            decided_by = NULL,
                            decided_at = NULL,
                            decision_note = '',
                            submitted_at = ?
                        WHERE id = ? AND status = ?
                        """,
                        (
                            form["notes"],
                            status,
                            submitted_at,
                            indent_id,
                            prior_status,
                        ),
                    )
                    won_transition = update_cur.rowcount > 0
                    if not won_transition:
                        # Someone else changed this indent between our read and write
                        # (rare race). Still apply this request's edits so they aren't
                        # silently dropped, just without re-triggering the approval flow.
                        conn.execute(
                            """
                            UPDATE store_indents
                            SET notes = ?, status = ?, submitted_at = ?
                            WHERE id = ?
                            """,
                            (form["notes"], status, submitted_at, indent_id),
                        )
                    conn.execute(
                        "DELETE FROM store_indent_lines WHERE indent_id = ?",
                        (indent_id,),
                    )
                    for line in lines:
                        conn.execute(
                            """
                            INSERT INTO store_indent_lines
                                (indent_id, item_name, quantity, unit, notes, approximate_price)
                            VALUES (?, ?, ?, ?, ?, ?)
                            """,
                            (
                                indent_id,
                                line["item_name"],
                                line["quantity"],
                                line["unit"],
                                line.get("notes") or "",
                                line.get("approximate_price"),
                            ),
                        )
                    # New approval round: allow WhatsApp notify again after reject/draft.
                    is_new_round = won_transition and status == "pending" and prior_status != "pending"
                    if is_new_round:
                        supersede_indent_whatsapp_sends(conn, indent_id)
                        assign_fresh_approval_token(conn, indent_id)
                    conn.commit()
                    if prior_status == "rejected":
                        msg = "Indent updated and sent for approval."
                    elif prior_status != "pending":
                        msg = "Indent sent for approval."
                    else:
                        msg = "Indent updated."
                    flash(msg, "ok")
                    # Only notify when entering pending (draft/rejected → pending).
                    # Editing an already-pending indent must not re-spam WhatsApp.
                    if is_new_round:
                        _notify_indent_pending_whatsapp(conn, indent_id, write_outlet)
                    return redirect(url_for("stores_indent", outlet=write_outlet, view="pending"))

                # Guard against duplicate indents from a double form submit (double-click,
                # soft-nav retry, browser resubmit): the same rendered form carries a
                # one-time token, so a repeat POST is recognised and short-circuited here
                # instead of creating a second indent + sending a second approval request.
                submission_token = form["submission_token"]
                dup_indent = None
                if submission_token:
                    dup_indent = conn.execute(
                        "SELECT id, outlet, status FROM store_indents WHERE submission_token = ?",
                        (submission_token,),
                    ).fetchone()
                if dup_indent:
                    flash(
                        "Indent sent for approval." if status == "pending" else "Indent saved as draft.",
                        "ok",
                    )
                    return redirect(
                        url_for(
                            "stores_indent",
                            outlet=dup_indent["outlet"] or write_outlet,
                            view="pending" if dup_indent["status"] == "pending" else list_view,
                        )
                    )

                indent_no = _next_doc_no(conn, "store_indents", "indent_no", "IND", write_outlet)
                try:
                    cur = conn.execute(
                        """
                        INSERT INTO store_indents
                            (outlet, indent_no, status, notes, created_by, created_at, submitted_at, submission_token)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            write_outlet,
                            indent_no,
                            status,
                            form["notes"],
                            user["id"] if user else None,
                            _now(),
                            _now() if status == "pending" else None,
                            submission_token,
                        ),
                    )
                except sqlite3.IntegrityError:
                    # Lost the race to a concurrent duplicate submit with the same token.
                    conn.rollback()
                    dup_indent = conn.execute(
                        "SELECT id, outlet, status FROM store_indents WHERE submission_token = ?",
                        (submission_token,),
                    ).fetchone()
                    flash(
                        "Indent sent for approval." if status == "pending" else "Indent saved as draft.",
                        "ok",
                    )
                    return redirect(
                        url_for(
                            "stores_indent",
                            outlet=(dup_indent["outlet"] if dup_indent else write_outlet),
                            view="pending" if (dup_indent and dup_indent["status"] == "pending") else list_view,
                        )
                    )
                new_id = cur.lastrowid
                for line in lines:
                    conn.execute(
                        """
                        INSERT INTO store_indent_lines
                            (indent_id, item_name, quantity, unit, notes, approximate_price)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            new_id,
                            line["item_name"],
                            line["quantity"],
                            line["unit"],
                            line.get("notes") or "",
                            line.get("approximate_price"),
                        ),
                    )
                if status == "pending":
                    assign_fresh_approval_token(conn, new_id)
                conn.commit()
                msg = "Indent sent for approval." if status == "pending" else "Indent saved as draft."
                flash(msg, "ok")
                if status == "pending":
                    _notify_indent_pending_whatsapp(conn, new_id, write_outlet)
                return redirect(
                    url_for(
                        "stores_indent",
                        outlet=write_outlet,
                        view="pending" if status == "pending" else list_view,
                    )
                )

        if edit_id and request.method == "GET":
            row = conn.execute(
                """
                SELECT * FROM store_indents WHERE id = ?
                """,
                (edit_id,),
            ).fetchone()
            if not row:
                flash("Indent not found.", "error")
                return redirect(url_for("stores_indent", outlet=outlet, view=list_view))
            if row["status"] not in EDITABLE_INDENT_STATUSES:
                flash("Only draft, waiting, or rejected indents can be edited.", "error")
                return redirect(url_for("stores_indent", outlet=row["outlet"], view="rejected" if row["status"] == "rejected" else "approved"))
            outlet = _parse_outlet(row["outlet"])
            open_edit_id = edit_id
            list_view = "rejected" if row["status"] == "rejected" else "pending"

        # Create form: no default outlet — user must pick Bar or Restaurant.
        indent_form_unset = bool(
            ((focus and not open_edit_id) or request.method == "POST")
            and outlet == "both"
            and not open_edit_id
        )
        if indent_form_unset:
            catalog = []
        else:
            catalog = _load_product_catalog(conn, stores_outlet=outlet)
        status_keys = INDENT_LIST_VIEW_STATUSES[list_view]
        status_placeholders = ",".join("?" for _ in status_keys)
        stores_ledger_data = {
            "summary": {
                "indents_created": 0,
                "qty_ordered": 0,
                "qty_received": 0,
                "qty_pending": 0,
                "qty_ordered_display": "0",
                "qty_received_display": "0",
                "qty_pending_display": "0",
            },
            "rows": [],
        }
        if outlet == "both":
            rows = conn.execute(
                f"""
                SELECT i.*, u.full_name AS created_by_name,
                       d.full_name AS decided_by_name,
                       d.username AS decided_by_username,
                       (SELECT COUNT(*) FROM store_indent_lines l WHERE l.indent_id = i.id) AS line_count,
                       (SELECT COALESCE(SUM(l.quantity), 0) FROM store_indent_lines l WHERE l.indent_id = i.id) AS total_qty
                FROM store_indents i
                LEFT JOIN users u ON u.id = i.created_by
                LEFT JOIN users d ON d.id = i.decided_by
                WHERE i.outlet IN ('bar', 'restaurant')
                  AND i.status IN ({status_placeholders})
                ORDER BY i.created_at DESC, i.id DESC
                """,
                status_keys,
            ).fetchall()
        else:
            rows = conn.execute(
                f"""
                SELECT i.*, u.full_name AS created_by_name,
                       d.full_name AS decided_by_name,
                       d.username AS decided_by_username,
                       (SELECT COUNT(*) FROM store_indent_lines l WHERE l.indent_id = i.id) AS line_count,
                       (SELECT COALESCE(SUM(l.quantity), 0) FROM store_indent_lines l WHERE l.indent_id = i.id) AS total_qty
                FROM store_indents i
                LEFT JOIN users u ON u.id = i.created_by
                LEFT JOIN users d ON d.id = i.decided_by
                WHERE i.outlet = ?
                  AND i.status IN ({status_placeholders})
                ORDER BY i.created_at DESC, i.id DESC
                """,
                (outlet, *status_keys),
            ).fetchall()
        indents = [dict(row) for row in rows]
        indent_view_data = _indent_view_payload(conn, indents)
        stores_ledger_data = _stores_ledger_payload(conn, "both")
    finally:
        conn.close()

    show_form = (focus and not open_edit_id) or bool(errors)
    indent_form_unset = bool(show_form and outlet == "both" and not open_edit_id)
    # Fresh "New Indent" form: mint a one-time token so a resubmitted POST (double
    # click, soft-nav retry) can be recognised server-side and de-duplicated.
    if show_form and not form.get("indent_id") and not form.get("submission_token"):
        form["submission_token"] = uuid.uuid4().hex

    return _page_render(
        "indent",
        outlet=outlet,
        indents=indents,
        indent_view_data=indent_view_data,
        stores_ledger_data=stores_ledger_data,
        product_catalog=catalog,
        show_form=show_form,
        open_edit_id=open_edit_id,
        indent_form_unset=indent_form_unset,
        form=form,
        errors=errors,
        editing=bool(form.get("indent_id")),
        indent_list_views=INDENT_LIST_VIEWS,
        selected_indent_view=list_view,
    )


def _build_indent_purchase_order_xlsx(indent: dict[str, Any], lines: list[dict[str, Any]]) -> io.BytesIO:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font

    wb = Workbook()
    ws = wb.active
    ws.title = "Purchase Order"

    title_font = Font(bold=True, size=16)
    header_font = Font(bold=True)
    label_font = Font(bold=True)

    ws["A1"] = "Hotel Bell Elite"
    ws["A1"].font = title_font
    ws["A2"] = "Purchase Order"
    ws["A2"].font = Font(bold=True, size=13)

    meta = [
        ("Indent No", indent.get("indent_no") or ""),
        ("Outlet", _outlet_label(_parse_outlet(indent.get("outlet")))),
        ("Status", _status_label(indent.get("status") or "")),
        ("Created", _format_stores_dt(indent.get("created_at"))),
        ("Created by", indent.get("created_by_name") or ""),
        ("Notes", indent.get("notes") or ""),
    ]
    row_idx = 4
    for label, value in meta:
        ws.cell(row=row_idx, column=1, value=label).font = label_font
        ws.cell(row=row_idx, column=2, value=value)
        row_idx += 1

    row_idx += 1
    headers = ("#", "Item", "Qty", "Unit", "Approx. price", "Amount")
    for col, title in enumerate(headers, start=1):
        cell = ws.cell(row=row_idx, column=col, value=title)
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center" if col != 2 else "left")

    total_amount = 0.0
    has_amount = False
    for idx, line in enumerate(lines, start=1):
        row_idx += 1
        qty = float(line.get("quantity") or 0)
        price = line.get("approximate_price")
        try:
            price_num = float(price) if price is not None and price != "" else None
        except (TypeError, ValueError):
            price_num = None
        amount = None
        if price_num is not None:
            amount = round(qty * price_num, 2)
            total_amount += amount
            has_amount = True
        ws.cell(row=row_idx, column=1, value=idx)
        ws.cell(row=row_idx, column=2, value=line.get("item_name") or "")
        ws.cell(row=row_idx, column=3, value=qty)
        ws.cell(row=row_idx, column=4, value=line.get("unit") or "")
        ws.cell(row=row_idx, column=5, value=price_num if price_num is not None else "")
        ws.cell(row=row_idx, column=6, value=amount if amount is not None else "")

    if has_amount:
        row_idx += 1
        ws.cell(row=row_idx, column=5, value="Total").font = header_font
        ws.cell(row=row_idx, column=6, value=round(total_amount, 2)).font = header_font

    widths = (6, 32, 10, 10, 14, 12)
    for idx, width in enumerate(widths, start=1):
        ws.column_dimensions[chr(64 + idx)].width = width

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


@stores_bp.route("/stores/indent/<int:indent_id>/purchase-order")
def stores_indent_purchase_order(indent_id: int):
    """Excel purchase order for an approved indent."""
    conn = get_db()
    try:
        ensure_stores_schema(conn)
        indent = conn.execute(
            """
            SELECT i.*, u.full_name AS created_by_name
            FROM store_indents i
            LEFT JOIN users u ON u.id = i.created_by
            WHERE i.id = ?
            """,
            (indent_id,),
        ).fetchone()
        if not indent:
            flash("Indent not found.", "error")
            return redirect(url_for("stores_indent", view="approved"))
        if indent["status"] != "approved":
            flash("Purchase orders are available for approved indents only.", "error")
            return redirect(url_for("stores_indent", outlet=indent["outlet"], view="pending"))
        lines = [
            dict(row)
            for row in conn.execute(
                """
                SELECT item_name, quantity, unit, approximate_price, notes
                FROM store_indent_lines
                WHERE indent_id = ?
                ORDER BY id
                """,
                (indent_id,),
            ).fetchall()
        ]
        indent_data = dict(indent)
    finally:
        conn.close()

    buf = _build_indent_purchase_order_xlsx(indent_data, lines)
    safe_no = re.sub(r"[^\w.-]+", "_", str(indent_data.get("indent_no") or indent_id))
    fname = f"PO_{safe_no}.xlsx"
    return send_file(
        buf,
        as_attachment=True,
        download_name=fname,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@stores_bp.route("/stores/indent/<int:indent_id>/delete", methods=["GET", "POST"])
def stores_indent_delete(indent_id: int):
    outlet = _parse_outlet_filter(request.args.get("outlet") or request.form.get("outlet"))
    conn = get_db()
    try:
        ensure_stores_schema(conn)
        indent = conn.execute(
            "SELECT id, indent_no, outlet, status FROM store_indents WHERE id = ?",
            (indent_id,),
        ).fetchone()
        if not indent:
            flash("Indent not found.", "error")
            return redirect(url_for("stores_indent", outlet=outlet))
        outlet = _parse_outlet(indent["outlet"])
        if indent["status"] not in ("draft", "pending"):
            flash("Only draft or waiting indents can be deleted.", "error")
            return redirect(url_for("stores_indent", outlet=outlet))
        conn.execute("DELETE FROM store_indent_lines WHERE indent_id = ?", (indent_id,))
        conn.execute("DELETE FROM store_indents WHERE id = ?", (indent_id,))
        conn.commit()
        flash(f"Deleted {indent['indent_no']}.", "ok")
    finally:
        conn.close()
    return redirect(url_for("stores_indent", outlet=outlet))


@stores_bp.route("/stores/indent/<int:indent_id>")
def stores_indent_detail(indent_id: int):
    outlet = _parse_outlet(request.args.get("outlet"))
    conn = get_db()
    try:
        ensure_stores_schema(conn)
        indent = conn.execute(
            """
            SELECT i.*, u.full_name AS created_by_name,
                   d.full_name AS decided_by_name,
                   d.username AS decided_by_username
            FROM store_indents i
            LEFT JOIN users u ON u.id = i.created_by
            LEFT JOIN users d ON d.id = i.decided_by
            WHERE i.id = ?
            """,
            (indent_id,),
        ).fetchone()
        if not indent:
            flash("Indent not found.", "error")
            return redirect(url_for("stores_indent", outlet=outlet))
        outlet = indent["outlet"]
        lines = conn.execute(
            "SELECT * FROM store_indent_lines WHERE indent_id = ? ORDER BY id",
            (indent_id,),
        ).fetchall()
        detail_lines = []
        for line in lines:
            item = dict(line)
            item["approximate_price_display"] = _format_optional_price(item.get("approximate_price"))
            detail_lines.append(item)
    finally:
        conn.close()
    return _page_render(
        "indent",
        outlet=outlet,
        indents=[],
        show_form=False,
        detail=dict(indent),
        detail_lines=detail_lines,
        form=None,
        errors=[],
    )


@stores_bp.route("/stores/indent/<int:indent_id>/submit", methods=["POST"])
def stores_indent_submit(indent_id: int):
    outlet = _parse_outlet(request.form.get("outlet") or request.args.get("outlet"))
    conn = get_db()
    try:
        ensure_stores_schema(conn)
        indent = conn.execute("SELECT * FROM store_indents WHERE id = ?", (indent_id,)).fetchone()
        if not indent:
            flash("Indent not found.", "error")
            return redirect(url_for("stores_indent", outlet=outlet))
        outlet = indent["outlet"]
        if indent["status"] != "draft":
            flash("Only draft indents can be sent for approval.", "error")
            return redirect(url_for("stores_indent", outlet=outlet))
        line_count = conn.execute(
            "SELECT COUNT(*) AS c FROM store_indent_lines WHERE indent_id = ?",
            (indent_id,),
        ).fetchone()["c"]
        if not line_count:
            flash("Add items before sending for approval.", "error")
            return redirect(url_for("stores_indent_detail", indent_id=indent_id, outlet=outlet))
        # Bind the WHERE to status='draft' so a concurrent duplicate submit (double
        # click, retried request) can't both flip the row and each send an approval.
        update_cur = conn.execute(
            "UPDATE store_indents SET status = 'pending', submitted_at = ? WHERE id = ? AND status = 'draft'",
            (_now(), indent_id),
        )
        if update_cur.rowcount == 0:
            conn.commit()
            flash("Indent already sent for approval.", "ok")
            return redirect(url_for("stores_indent", outlet=outlet))
        supersede_indent_whatsapp_sends(conn, indent_id)
        assign_fresh_approval_token(conn, indent_id)
        conn.commit()
        flash("Indent sent for approval.", "ok")
        _notify_indent_pending_whatsapp(conn, indent_id, outlet)
    finally:
        conn.close()
    return redirect(url_for("stores_indent", outlet=outlet))


@stores_bp.route("/stores/approvals")
def stores_approvals():
    outlet = _parse_outlet_filter(request.args.get("outlet"))
    outlet_sql, outlet_params = _outlet_match_sql("i.outlet", outlet)
    conn = get_db()
    try:
        ensure_stores_schema(conn)
        pending = conn.execute(
            f"""
            SELECT i.*, u.full_name AS created_by_name,
                   (SELECT COUNT(*) FROM store_indent_lines l WHERE l.indent_id = i.id) AS line_count,
                   (SELECT COALESCE(SUM(
                        COALESCE(l.quantity, 0) * COALESCE(l.approximate_price, 0)
                    ), 0)
                    FROM store_indent_lines l WHERE l.indent_id = i.id) AS approximate_total
            FROM store_indents i
            LEFT JOIN users u ON u.id = i.created_by
            WHERE {outlet_sql} AND i.status = 'pending'
            ORDER BY i.submitted_at ASC, i.id ASC
            """,
            outlet_params,
        ).fetchall()
        recent = conn.execute(
            f"""
            SELECT i.*, u.full_name AS created_by_name, d.full_name AS decided_by_name
            FROM store_indents i
            LEFT JOIN users u ON u.id = i.created_by
            LEFT JOIN users d ON d.id = i.decided_by
            WHERE {outlet_sql} AND i.status IN ('approved', 'rejected')
            ORDER BY i.decided_at DESC, i.id DESC
            LIMIT 20
            """,
            outlet_params,
        ).fetchall()
    finally:
        conn.close()
    pending_rows = []
    for row in pending:
        item = dict(row)
        total = item.get("approximate_total")
        try:
            total_num = float(total or 0)
        except (TypeError, ValueError):
            total_num = 0.0
        item["approximate_total"] = total_num
        item["approximate_total_display"] = (
            _format_optional_price(total_num) if total_num > 0 else ""
        )
        pending_rows.append(item)
    return _page_render(
        "approvals",
        outlet=outlet,
        pending=pending_rows,
        recent=[dict(row) for row in recent],
    )


@stores_bp.route("/stores/indent/<int:indent_id>/decide", methods=["POST"])
def stores_indent_decide(indent_id: int):
    user = _get_user()
    decision = (request.form.get("decision") or "").strip().lower()
    note = (request.form.get("decision_note") or "").strip()
    outlet = _parse_outlet(request.form.get("outlet"))
    if decision not in {"approved", "rejected"}:
        flash("Choose approve or reject.", "error")
        return redirect(url_for("stores_approvals", outlet=outlet))
    if decision == "rejected" and not note:
        flash("Add a short reason when rejecting.", "error")
        return redirect(url_for("stores_approvals", outlet=outlet))

    conn = get_db()
    try:
        ensure_stores_schema(conn)
        indent = conn.execute("SELECT * FROM store_indents WHERE id = ?", (indent_id,)).fetchone()
        if not indent or indent["status"] != "pending":
            flash("This indent is not waiting for approval.", "error")
            return redirect(url_for("stores_approvals", outlet=outlet))
        outlet = indent["outlet"]
        conn.execute(
            """
            UPDATE store_indents
            SET status = ?, decided_by = ?, decided_at = ?, decision_note = ?
            WHERE id = ?
            """,
            (decision, user["id"] if user else None, _now(), note, indent_id),
        )
        conn.commit()
    finally:
        conn.close()
    flash("Indent approved." if decision == "approved" else "Indent rejected.", "ok")
    return redirect(url_for("stores_approvals", outlet=outlet))


@stores_bp.route("/stores/indent/<int:indent_id>/reopen", methods=["POST"])
def stores_indent_reopen(indent_id: int):
    """Return a rejected indent to Waiting for approval."""
    outlet = _parse_outlet_filter(request.form.get("outlet") or request.args.get("outlet"))
    conn = get_db()
    try:
        ensure_stores_schema(conn)
        indent = conn.execute(
            "SELECT id, outlet, status, indent_no FROM store_indents WHERE id = ?",
            (indent_id,),
        ).fetchone()
        if not indent:
            flash("Indent not found.", "error")
            return redirect(url_for("stores_approvals", outlet=outlet))
        outlet = _parse_outlet(indent["outlet"])
        if indent["status"] != "rejected":
            flash("Only rejected indents can be returned to waiting.", "error")
            return redirect(url_for("stores_approvals", outlet=outlet))
        conn.execute(
            """
            UPDATE store_indents
            SET status = 'pending',
                decided_by = NULL,
                decided_at = NULL,
                decision_note = '',
                submitted_at = COALESCE(submitted_at, ?)
            WHERE id = ?
            """,
            (_now(), indent_id),
        )
        conn.commit()
        flash(f"{indent['indent_no']} returned to waiting approval.", "ok")
    finally:
        conn.close()
    return redirect(url_for("stores_approvals", outlet=outlet))


@stores_bp.route("/stores/purchase-requests", methods=["GET", "POST"])
def stores_purchase_requests():
    outlet = _parse_outlet_filter(request.args.get("outlet") or request.form.get("outlet"))
    user = _get_user()

    if request.method == "POST" and request.form.get("action") == "create_from_indent":
        try:
            indent_id = int(request.form.get("indent_id") or 0)
        except (TypeError, ValueError):
            indent_id = 0
        conn = get_db()
        try:
            ensure_stores_schema(conn)
            indent = conn.execute(
                "SELECT * FROM store_indents WHERE id = ? AND status = 'approved'",
                (indent_id,),
            ).fetchone()
            if not indent:
                flash("Select an approved indent.", "error")
                return redirect(url_for("stores_purchase_requests", outlet=outlet))
            write_outlet = _parse_outlet(indent["outlet"])
            existing = conn.execute(
                "SELECT id FROM store_purchase_requests WHERE indent_id = ?",
                (indent_id,),
            ).fetchone()
            if existing:
                flash("A purchase request already exists for this indent.", "error")
                return redirect(url_for("stores_purchase_requests", outlet=write_outlet))
            lines = conn.execute(
                "SELECT * FROM store_indent_lines WHERE indent_id = ? ORDER BY id",
                (indent_id,),
            ).fetchall()
            if not lines:
                flash("This indent has no items.", "error")
                return redirect(url_for("stores_purchase_requests", outlet=write_outlet))
            pr_no = _next_doc_no(conn, "store_purchase_requests", "pr_no", "PR", write_outlet)
            cur = conn.execute(
                """
                INSERT INTO store_purchase_requests
                    (indent_id, outlet, pr_no, status, notes, created_by, created_at)
                VALUES (?, ?, ?, 'open', ?, ?, ?)
                """,
                (
                    indent_id,
                    write_outlet,
                    pr_no,
                    (request.form.get("notes") or "").strip(),
                    user["id"] if user else None,
                    _now(),
                ),
            )
            pr_id = cur.lastrowid
            for line in lines:
                conn.execute(
                    """
                    INSERT INTO store_purchase_request_lines (pr_id, item_name, quantity, unit, notes)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (pr_id, line["item_name"], line["quantity"], line["unit"], line["notes"] or ""),
                )
            conn.commit()
        finally:
            conn.close()
        flash("Purchase request created.", "ok")
        return redirect(url_for("stores_purchase_requests", outlet=write_outlet))

    if request.method == "POST" and request.form.get("action") == "confirm_stock_inward":
        # Stock + expense must go through the expense modal / JSON endpoint.
        flash("Confirm stock inward from the expense popup.", "error")
        try:
            indent_id = int(request.form.get("indent_id") or 0)
        except (TypeError, ValueError):
            indent_id = 0
        redirect_kwargs = {"outlet": outlet}
        if indent_id:
            redirect_kwargs["indent"] = indent_id
        return redirect(url_for("stores_purchase_requests", **redirect_kwargs))

    outlet_sql, outlet_params = _outlet_match_sql("i.outlet", outlet)
    # Lazy import avoids circular import with app.register_stores
    import app as app_module

    conn = get_db()
    expense_categories = app_module.EXPENSE_CATEGORIES
    try:
        ensure_stores_schema(conn)
        approved_rows = conn.execute(
            f"""
            SELECT i.*, u.full_name AS created_by_name,
                   d.full_name AS decided_by_name,
                   d.username AS decided_by_username,
                   (SELECT COUNT(*) FROM store_indent_lines l WHERE l.indent_id = i.id) AS line_count,
                   (SELECT COALESCE(SUM(l.quantity), 0) FROM store_indent_lines l WHERE l.indent_id = i.id) AS total_qty
            FROM store_indents i
            LEFT JOIN users u ON u.id = i.created_by
            LEFT JOIN users d ON d.id = i.decided_by
            WHERE {outlet_sql} AND i.status = 'approved'
              AND EXISTS (
                SELECT 1 FROM store_indent_lines l
                WHERE l.indent_id = i.id
                  AND COALESCE(l.quantity, 0) - COALESCE(l.quantity_received, 0) > 0.0001
              )
            ORDER BY i.decided_at DESC, i.id DESC
            """,
            outlet_params,
        ).fetchall()
        approved_indents = [dict(row) for row in approved_rows]
        selected_indent = None
        selected_lines: list[dict[str, Any]] = []
        try:
            selected_id = int(request.args.get("indent") or 0)
        except (TypeError, ValueError):
            selected_id = 0
        if selected_id:
            for row in approved_indents:
                if int(row["id"]) == selected_id:
                    selected_indent = row
                    break
        if selected_indent is None and len(approved_indents) == 1:
            selected_indent = approved_indents[0]
        if selected_indent is not None:
            line_rows = conn.execute(
                """
                SELECT id, item_name, quantity, quantity_received, unit, notes, approximate_price
                FROM store_indent_lines
                WHERE indent_id = ?
                ORDER BY id
                """,
                (int(selected_indent["id"]),),
            ).fetchall()
            for line in line_rows:
                approx = line["approximate_price"]
                try:
                    qty_val = float(line["quantity"] or 0)
                except (TypeError, ValueError):
                    qty_val = 0.0
                try:
                    received_val = float(line["quantity_received"] or 0)
                except (KeyError, TypeError, ValueError):
                    received_val = 0.0
                remaining_val = qty_val - received_val
                if remaining_val <= 0.0001:
                    continue
                if abs(qty_val - round(qty_val)) < 0.0001:
                    qty_display = str(int(round(qty_val)))
                else:
                    qty_display = ("%g" % qty_val)
                if abs(remaining_val - round(remaining_val)) < 0.0001:
                    remaining_display = str(int(round(remaining_val)))
                else:
                    remaining_display = ("%g" % remaining_val)
                if abs(received_val - round(received_val)) < 0.0001:
                    received_display = str(int(round(received_val)))
                else:
                    received_display = ("%g" % received_val)
                try:
                    rate_val = float(approx) if approx is not None and approx != "" else 0.0
                except (TypeError, ValueError):
                    rate_val = 0.0
                selected_lines.append({
                    "id": int(line["id"]),
                    "item_name": line["item_name"],
                    "quantity": qty_val,
                    "quantity_display": qty_display,
                    "quantity_received": received_val,
                    "quantity_received_display": received_display,
                    "remaining": remaining_val,
                    "remaining_display": remaining_display,
                    "unit": line["unit"] or "",
                    "notes": line["notes"] or "",
                    "approximate_price": approx,
                    "approximate_price_display": _format_optional_price(approx),
                    "rate_value": rate_val,
                    "initial": (line["item_name"] or "?")[:1].upper(),
                })
            selected_indent = {
                **selected_indent,
                "outlet": _parse_outlet(selected_indent.get("outlet")),
                "outlet_label": _outlet_label(_parse_outlet(selected_indent.get("outlet"))),
            }
        indent_view_data = _indent_view_payload(
            conn,
            [selected_indent] if selected_indent else [],
        )
        suppliers = app_module._all_suppliers(conn)
        today = date.today()
        available_cash = app_module._cash_ledger_available_as_of(
            conn, app_module.DEFAULT_COMPANY, today
        )
        expense_categories = app_module._expense_category_choices(conn)
    finally:
        conn.close()

    return _page_render(
        "purchase_requests",
        outlet=outlet,
        approved_indents=approved_indents,
        selected_indent=selected_indent,
        selected_lines=selected_lines,
        indent_view_data=indent_view_data,
        suppliers=suppliers,
        expense_categories=expense_categories,
        expense_payment_types=app_module.EXPENSE_PAYMENT_TYPES,
        available_cash=available_cash,
        available_cash_url=url_for("cash_ledger_available"),
        supplier_create_url=url_for("create_supplier"),
        default_company=app_module.DEFAULT_COMPANY,
        default_location=app_module.OUTLET_HOTEL,
        today_iso=today.isoformat(),
        inward_confirm_url=url_for("stores_confirm_stock_inward_expense"),
        inward_save_category_url=url_for("stores_save_expense_category"),
    )


@stores_bp.route("/stores/purchase-requests/expense-category", methods=["POST"])
def stores_save_expense_category():
    """Add a custom expense category for Inward / Expense Ledger dropdowns."""
    user = _get_user()
    if not user:
        return jsonify({"ok": False, "error": "You must be logged in."}), 401

    import app as app_module
    import re

    data = request.get_json(silent=True) or {}
    name = (data.get("category_name") or data.get("name") or "").strip()
    if not name:
        return jsonify({"ok": False, "error": "Category name is required."}), 400
    if len(name) > 80:
        return jsonify({"ok": False, "error": "Category name must be 80 characters or fewer."}), 400

    key = app_module._slugify_expense_category_key(name)
    if not key or not re.fullmatch(r"[a-z][a-z0-9_]{0,79}", key):
        return jsonify({"ok": False, "error": "Enter a valid category name."}), 400

    # Prefer builtin key when the name matches an existing label (case-insensitive).
    for builtin_key, builtin_label in app_module.EXPENSE_CATEGORIES:
        if builtin_label.casefold() == name.casefold() or builtin_key == key:
            return jsonify({
                "ok": True,
                "category_key": builtin_key,
                "category_label": builtin_label,
                "existing": True,
            })

    conn = get_db()
    try:
        ensure_stores_schema(conn)
        # Schema for expense_categories lives in init_db path; ensure via pragma/create.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS expense_categories (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                category_key  TEXT    NOT NULL UNIQUE,
                name          TEXT    NOT NULL COLLATE NOCASE,
                sort_order    INTEGER NOT NULL DEFAULT 0,
                is_active     INTEGER NOT NULL DEFAULT 1,
                created_at    TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
            )
        """)
        by_key = conn.execute(
            "SELECT category_key, name, is_active FROM expense_categories WHERE category_key = ?",
            (key,),
        ).fetchone()
        by_name = conn.execute(
            "SELECT category_key, name, is_active FROM expense_categories WHERE lower(name) = lower(?)",
            (name,),
        ).fetchone()
        existing = by_name or by_key
        if existing:
            if int(existing["is_active"] or 0) != 1:
                conn.execute(
                    "UPDATE expense_categories SET is_active = 1, name = ? WHERE category_key = ?",
                    (name, existing["category_key"]),
                )
                conn.commit()
            return jsonify({
                "ok": True,
                "category_key": existing["category_key"],
                "category_label": name if int(existing["is_active"] or 0) != 1 else existing["name"],
                "existing": True,
            })

        max_sort = conn.execute(
            "SELECT COALESCE(MAX(sort_order), 0) AS m FROM expense_categories"
        ).fetchone()["m"]
        conn.execute(
            """
            INSERT INTO expense_categories (category_key, name, sort_order, is_active)
            VALUES (?, ?, ?, 1)
            """,
            (key, name, int(max_sort) + 10),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        return jsonify({"ok": False, "error": "Could not save category."}), 500
    finally:
        conn.close()

    return jsonify({
        "ok": True,
        "category_key": key,
        "category_label": name,
        "existing": False,
    })


@stores_bp.route("/stores/purchase-requests/confirm-with-expense", methods=["POST"])
def stores_confirm_stock_inward_expense():
    """Confirm stock inward and record Hotel expense in one transaction."""
    user = _get_user()
    if not user:
        return jsonify({"ok": False, "error": "You must be logged in."}), 401

    import app as app_module

    data = request.get_json(silent=True) or {}
    try:
        indent_id = int(data.get("indent_id") or 0)
    except (TypeError, ValueError):
        indent_id = 0
    notes = (data.get("notes") or "").strip()[:500]
    raw_lines = data.get("lines") or []
    if not isinstance(raw_lines, list):
        raw_lines = []

    # line_id -> (received_qty, unit_price, tax_percent)
    selected: dict[int, tuple[float, float | None, float | None]] = {}
    for raw in raw_lines:
        if not isinstance(raw, dict):
            continue
        try:
            line_id = int(raw.get("line_id") or raw.get("id") or 0)
            qty = float(raw.get("received_qty") or raw.get("quantity") or 0)
        except (TypeError, ValueError):
            continue
        if line_id <= 0 or qty <= 0:
            continue
        unit_price = None
        tax_percent = None
        try:
            if raw.get("unit_price") not in (None, ""):
                unit_price = float(raw.get("unit_price"))
        except (TypeError, ValueError):
            unit_price = None
        try:
            if raw.get("tax_percent") not in (None, ""):
                tax_percent = float(raw.get("tax_percent"))
        except (TypeError, ValueError):
            tax_percent = None
        selected[line_id] = (qty, unit_price, tax_percent)

    if not indent_id:
        return jsonify({"ok": False, "error": "Select an approved indent."}), 400
    if not selected:
        return jsonify({"ok": False, "error": "Select at least one item with a received quantity."}), 400

    conn = get_db()
    write_outlet = "bar"
    try:
        ensure_stores_schema(conn)
        indent = conn.execute(
            "SELECT * FROM store_indents WHERE id = ?",
            (indent_id,),
        ).fetchone()
        if not indent or indent["status"] != "approved":
            return jsonify({"ok": False, "error": "Select an approved indent."}), 400
        write_outlet = _parse_outlet(indent["outlet"])
        lines = conn.execute(
            "SELECT * FROM store_indent_lines WHERE indent_id = ? ORDER BY id",
            (indent_id,),
        ).fetchall()
        if not lines:
            return jsonify({"ok": False, "error": "This indent has no items."}), 400

        lines_by_id = {int(row["id"]): row for row in lines}
        received_pairs: list[tuple[Any, float, float | None]] = []
        for line_id, (received_qty, unit_price, tax_percent) in selected.items():
            line = lines_by_id.get(line_id)
            if not line:
                return jsonify({"ok": False, "error": "One or more selected lines were not found."}), 400
            ordered = float(line["quantity"] or 0)
            try:
                already = float(line["quantity_received"] or 0)
            except (KeyError, TypeError, ValueError):
                already = 0.0
            remaining = ordered - already
            if remaining <= 0.0001:
                return jsonify({
                    "ok": False,
                    "error": f"{line['item_name']} is already fully received.",
                }), 400
            if received_qty - remaining > 0.0001:
                return jsonify({
                    "ok": False,
                    "error": (
                        f"Received quantity for {line['item_name']} cannot exceed "
                        f"remaining qty ({remaining:g})."
                    ),
                }), 400
            unit_cost = _unit_cost_with_tax(unit_price, tax_percent)
            if unit_cost is None:
                # Fall back to approved indent price (ex-tax) when UI omits entered rate.
                unit_cost = _unit_cost_with_tax(line["approximate_price"], 0)
            received_pairs.append((line, received_qty, unit_cost))

        expense_data = {
            "company": data.get("company") or app_module.DEFAULT_COMPANY,
            "location": app_module.OUTLET_HOTEL,
            "date": data.get("date") or date.today().isoformat(),
            "description": (data.get("description") or "").strip()
            or f"Stock inward {indent['indent_no']}",
            "amount": data.get("amount"),
            "payment_type": data.get("payment_type"),
            "category": data.get("category"),
            "transaction_id": data.get("transaction_id"),
            "invoice_number": data.get("invoice_number"),
            "supplier_id": data.get("supplier_id"),
        }
        expense_result, expense_error = app_module._create_sales_expense(
            conn,
            user,
            expense_data,
            default_location=app_module.OUTLET_HOTEL,
        )
        if expense_error:
            conn.rollback()
            return jsonify({"ok": False, "error": expense_error}), 400

        payment_type = app_module._normalize_expense_payment_type(expense_data.get("payment_type"))
        expense_amount = app_module.parse_money(expense_data.get("amount"))
        approved_total = 0.0
        for line, received_qty, _unit_cost in received_pairs:
            try:
                unit_price = float(line["approximate_price"] or 0)
            except (TypeError, ValueError):
                unit_price = 0.0
            approved_total += float(received_qty) * unit_price
        approved_total = app_module.round_half_up(approved_total, 2)
        # Credit ≤ approved total skips Purchase Verification; any overage must be verified.
        if (
            payment_type == app_module.EXPENSE_PAYMENT_CREDIT
            and expense_amount - approved_total <= 0.001
        ):
            verify_notes = f"Auto-verified from stock inward {indent['indent_no']}"
            if notes:
                verify_notes = f"{verify_notes}: {notes}"
            _, verify_error = app_module._auto_verify_expense(
                conn,
                expense_id=expense_result["expense_id"],
                supplier_id=expense_data["supplier_id"],
                amount=expense_amount,
                company=expense_data["company"],
                user=user,
                notes=verify_notes,
            )
            if verify_error:
                conn.rollback()
                return jsonify({"ok": False, "error": verify_error}), 400

        movement_note = f"Stock inward from {indent['indent_no']}"
        if notes:
            movement_note = f"{movement_note}: {notes}"
        for line, received_qty, unit_cost in received_pairs:
            _adjust_stock(
                conn,
                outlet=write_outlet,
                item_name=line["item_name"],
                unit=line["unit"] or "",
                qty_delta=received_qty,
                movement_type="receive",
                ref_type="stock_inward",
                ref_id=indent_id,
                notes=movement_note,
                user_id=user["id"] if user else None,
                unit_cost=unit_cost,
            )
            try:
                already = float(line["quantity_received"] or 0)
            except (KeyError, TypeError, ValueError):
                already = 0.0
            conn.execute(
                """
                UPDATE store_indent_lines
                SET quantity_received = ?
                WHERE id = ?
                """,
                (already + float(received_qty), int(line["id"])),
            )

        # Refresh remaining after this confirm.
        remaining_rows = conn.execute(
            """
            SELECT COALESCE(quantity, 0) - COALESCE(quantity_received, 0) AS remaining
            FROM store_indent_lines
            WHERE indent_id = ?
            """,
            (indent_id,),
        ).fetchall()
        still_open = any(float(row["remaining"] or 0) > 0.0001 for row in remaining_rows)
        if still_open:
            # Keep approved so the indent stays on Stock Inward.
            conn.execute(
                "UPDATE store_indents SET status = 'approved' WHERE id = ?",
                (indent_id,),
            )
            redirect_url = url_for(
                "stores_purchase_requests",
                outlet=write_outlet,
                indent=indent_id,
            )
            message = "Partial stock inward recorded. Remaining items stay on Stock Inward."
        else:
            conn.execute(
                "UPDATE store_indents SET status = 'stocked' WHERE id = ?",
                (indent_id,),
            )
            redirect_url = url_for("stores_stock", outlet=write_outlet)
            message = "Stock inward and expense recorded."

        conn.commit()
    except ValueError as exc:
        conn.rollback()
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return jsonify({
        "ok": True,
        "redirect": redirect_url,
        "expense_id": expense_result["expense_id"],
        "expense_code": expense_result.get("expense_code"),
        "message": message,
        "partial": still_open,
    })


@stores_bp.route("/stores/purchase-requests/<int:pr_id>")
def stores_pr_detail(pr_id: int):
    outlet = _parse_outlet(request.args.get("outlet"))
    conn = get_db()
    try:
        ensure_stores_schema(conn)
        pr = conn.execute(
            """
            SELECT p.*, i.indent_no
            FROM store_purchase_requests p
            LEFT JOIN store_indents i ON i.id = p.indent_id
            WHERE p.id = ?
            """,
            (pr_id,),
        ).fetchone()
        if not pr:
            flash("Purchase request not found.", "error")
            return redirect(url_for("stores_purchase_requests", outlet=outlet))
        outlet = pr["outlet"]
        lines = conn.execute(
            "SELECT * FROM store_purchase_request_lines WHERE pr_id = ? ORDER BY id",
            (pr_id,),
        ).fetchall()
    finally:
        conn.close()
    return _page_render(
        "purchase_requests",
        outlet=outlet,
        detail=dict(pr),
        detail_lines=[dict(line) for line in lines],
    )


@stores_bp.route("/stores/purchase-requests/<int:pr_id>/receive", methods=["POST"])
def stores_pr_receive(pr_id: int):
    user = _get_user()
    outlet = _parse_outlet(request.form.get("outlet"))
    conn = get_db()
    try:
        ensure_stores_schema(conn)
        pr = conn.execute("SELECT * FROM store_purchase_requests WHERE id = ?", (pr_id,)).fetchone()
        if not pr:
            flash("Purchase request not found.", "error")
            return redirect(url_for("stores_purchase_requests", outlet=outlet))
        outlet = pr["outlet"]
        if pr["status"] != "open":
            flash("This purchase request was already received.", "error")
            return redirect(url_for("stores_purchase_requests", outlet=outlet))
        lines = conn.execute(
            "SELECT * FROM store_purchase_request_lines WHERE pr_id = ? ORDER BY id",
            (pr_id,),
        ).fetchall()
        for line in lines:
            _adjust_stock(
                conn,
                outlet=outlet,
                item_name=line["item_name"],
                unit=line["unit"],
                qty_delta=float(line["quantity"]),
                movement_type="receive",
                ref_type="purchase_request",
                ref_id=pr_id,
                notes=f"Received from {pr['pr_no']}",
                user_id=user["id"] if user else None,
            )
        conn.execute(
            "UPDATE store_purchase_requests SET status = 'received', received_at = ? WHERE id = ?",
            (_now(), pr_id),
        )
        conn.commit()
    except ValueError as exc:
        conn.rollback()
        flash(str(exc), "error")
        return redirect(url_for("stores_purchase_requests", outlet=outlet))
    finally:
        conn.close()
    flash("Items received into stock.", "ok")
    return redirect(url_for("stores_stock", outlet=outlet))


def _inward_weighted_unit_costs(
    conn,
    outlet_sql: str,
    outlet_params: tuple[Any, ...],
) -> dict[tuple[str, str, str], float]:
    """Weighted-average unit cost (incl. tax when stored) from receive movements.

    Prefers ``store_stock_movements.unit_cost`` (inward price + tax). Falls back to
    the matching indent line ``approximate_price`` for older receipts without cost.
    """
    rows = conn.execute(
        f"""
        SELECT m.outlet,
               lower(m.item_name) AS name_key,
               lower(m.unit) AS unit_key,
               SUM(
                 m.qty_delta * COALESCE(
                   m.unit_cost,
                   (
                     SELECT l.approximate_price
                     FROM store_indent_lines l
                     WHERE m.ref_type = 'stock_inward'
                       AND l.indent_id = m.ref_id
                       AND lower(l.item_name) = lower(m.item_name)
                     ORDER BY l.id
                     LIMIT 1
                   )
                 )
               ) AS cost_total,
               SUM(
                 CASE
                   WHEN COALESCE(
                     m.unit_cost,
                     (
                       SELECT l.approximate_price
                       FROM store_indent_lines l
                       WHERE m.ref_type = 'stock_inward'
                         AND l.indent_id = m.ref_id
                         AND lower(l.item_name) = lower(m.item_name)
                       ORDER BY l.id
                       LIMIT 1
                     )
                   ) IS NOT NULL THEN m.qty_delta
                   ELSE 0
                 END
               ) AS qty_priced
        FROM store_stock_movements m
        WHERE m.movement_type = 'receive'
          AND m.qty_delta > 0
          AND {outlet_sql}
        GROUP BY m.outlet, lower(m.item_name), lower(m.unit)
        """,
        outlet_params,
    ).fetchall()
    costs: dict[tuple[str, str, str], float] = {}
    for row in rows:
        try:
            qty_priced = float(row["qty_priced"] or 0)
            cost_total = float(row["cost_total"] or 0)
        except (TypeError, ValueError):
            continue
        if qty_priced <= 0.0001 or cost_total <= 0:
            continue
        key = (
            (row["outlet"] or "").strip().lower(),
            (row["name_key"] or "").strip().lower(),
            (row["unit_key"] or "").strip().lower(),
        )
        costs[key] = round(cost_total / qty_priced, 4)
    return costs


def _enrich_stock_items(
    conn,
    items: list[dict[str, Any]],
    *,
    inward_costs: dict[tuple[str, str, str], float] | None = None,
) -> list[dict[str, Any]]:
    """Attach category + unit price for Stock display (inward WAC preferred)."""
    if not items:
        return items
    products = conn.execute(
        """
        SELECT p.name, p.outlet, p.default_unit, p.approximate_price,
               c.name AS category_name
        FROM store_products p
        LEFT JOIN store_product_categories c
          ON c.id = p.category_id AND c.is_active = 1
        WHERE p.is_active = 1
        """
    ).fetchall()
    by_name: dict[str, list[dict[str, Any]]] = {}
    for row in products:
        key = (row["name"] or "").strip().lower()
        if not key:
            continue
        by_name.setdefault(key, []).append(dict(row))

    costs = inward_costs or {}
    for item in items:
        name_key = (item.get("item_name") or "").strip().lower()
        unit_key = (item.get("unit") or "").strip().lower()
        outlet_key = (item.get("outlet") or "").strip().lower()
        candidates = by_name.get(name_key) or []
        match = None
        for preferred in (
            lambda p: (p.get("outlet") or "").strip().lower() == outlet_key
            and (p.get("default_unit") or "").strip().lower() == unit_key,
            lambda p: (p.get("outlet") or "").strip().lower() == outlet_key,
            lambda p: (p.get("outlet") or "").strip().lower() == "both"
            and (p.get("default_unit") or "").strip().lower() == unit_key,
            lambda p: (p.get("outlet") or "").strip().lower() == "both",
            lambda p: True,
        ):
            for cand in candidates:
                if preferred(cand):
                    match = cand
                    break
            if match:
                break
        if match:
            item["category_name"] = match.get("category_name") or ""
        else:
            item.setdefault("category_name", "")

        inward_price = costs.get((outlet_key, name_key, unit_key))
        if inward_price is not None and inward_price > 0:
            item["approximate_price"] = inward_price
            item["approximate_price_display"] = _format_optional_price(inward_price)
            item["price_source"] = "inward"
        elif match and match.get("approximate_price") is not None:
            price = match.get("approximate_price")
            item["approximate_price"] = price
            item["approximate_price_display"] = _format_optional_price(price)
            item["price_source"] = "product"
        else:
            item.setdefault("approximate_price", None)
            item.setdefault("approximate_price_display", "")
            item.setdefault("price_source", None)
    return items


@stores_bp.route("/stores/stock")
def stores_stock():
    outlet = _parse_outlet_filter(request.args.get("outlet"))
    outlet_sql, outlet_params = _outlet_match_sql("outlet", outlet)
    outlet_sql_m, outlet_params_m = _outlet_match_sql("m.outlet", outlet)
    conn = get_db()
    try:
        ensure_stores_schema(conn)
        items = conn.execute(
            f"""
            SELECT * FROM store_stock_items
            WHERE {outlet_sql}
            ORDER BY lower(item_name), lower(unit)
            """,
            outlet_params,
        ).fetchall()
        inward_costs = _inward_weighted_unit_costs(conn, outlet_sql_m, outlet_params_m)
        stock_items = _enrich_stock_items(
            conn,
            [dict(row) for row in items],
            inward_costs=inward_costs,
        )
        movements = conn.execute(
            f"""
            SELECT m.*, u.full_name AS created_by_name
            FROM store_stock_movements m
            LEFT JOIN users u ON u.id = m.created_by
            WHERE {outlet_sql_m}
            ORDER BY m.created_at DESC, m.id DESC
            LIMIT 25
            """,
            outlet_params_m,
        ).fetchall()
    finally:
        conn.close()
    categories = sorted(
        {
            (item.get("category_name") or "").strip()
            for item in stock_items
            if (item.get("category_name") or "").strip()
        },
        key=lambda name: name.lower(),
    )
    has_prices = any(item.get("approximate_price") is not None for item in stock_items)
    has_inward_prices = any(item.get("price_source") == "inward" for item in stock_items)
    return _page_render(
        "stock",
        outlet=outlet,
        stock_items=stock_items,
        stock_categories=categories,
        stock_has_prices=has_prices,
        stock_has_inward_prices=has_inward_prices,
        movements=[dict(row) for row in movements],
    )


def register_stores(app, *, pop_auth_notice, get_user):
    _bind_helpers(pop_auth_notice, get_user)
    app.register_blueprint(stores_bp)
    app.jinja_env.filters["stores_dt"] = _format_stores_dt
    for rule in list(app.url_map.iter_rules()):
        if not rule.endpoint.startswith("stores."):
            continue
        bare = rule.endpoint.split(".", 1)[1]
        if bare in app.view_functions:
            continue
        app.add_url_rule(
            rule.rule,
            endpoint=bare,
            view_func=app.view_functions[rule.endpoint],
            methods=rule.methods,
        )
