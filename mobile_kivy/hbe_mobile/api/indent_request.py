"""Stores Indent Request — catalog + create via JSON APIs."""

from __future__ import annotations

from typing import Any, Optional

from hbe_mobile.api.client import ApiClient, ApiError


def flatten_catalog(catalog: Any) -> list[dict[str, Any]]:
    """Flatten {categories: [{name, products: [...]}]} into product dicts with category_name."""
    if isinstance(catalog, dict):
        categories = catalog.get("categories") or []
    elif isinstance(catalog, list):
        categories = catalog
    else:
        categories = []
    products: list[dict[str, Any]] = []
    for cat in categories:
        if not isinstance(cat, dict):
            continue
        cat_name = str(cat.get("name") or "")
        for row in cat.get("products") or []:
            if not isinstance(row, dict):
                continue
            item = dict(row)
            item["category_name"] = str(item.get("category_name") or cat_name)
            products.append(item)
    return products


def line_total(qty: Any, price: Any) -> float:
    try:
        q = float(qty or 0)
        p = float(price or 0)
    except (TypeError, ValueError):
        return 0.0
    return round(q * p, 2)


def validate_lines(lines: Any) -> Optional[str]:
    """Return a user-facing error, or None if lines can be POSTed."""
    if not isinstance(lines, list) or not lines:
        return "Add at least one item with a quantity."
    for line in lines:
        if not isinstance(line, dict):
            return "Add at least one item with a quantity."
        name = str(line.get("item_name") or "").strip()
        if not name:
            return "Item is required."
        try:
            qty = float(line.get("quantity") or 0)
        except (TypeError, ValueError):
            qty = 0
        if qty <= 0:
            return "Enter a quantity greater than 0 for each item."
        try:
            price = float(line.get("approximate_price") or 0)
        except (TypeError, ValueError):
            price = 0
        if price <= 0:
            return "Enter an approximate price greater than 0 for each item."
    return None


def fetch_catalog(client: ApiClient, outlet: str) -> dict[str, Any]:
    key = (outlet or "").strip().lower() or "restaurant"
    data = client.get_json("/stores/api/indent-catalog", params={"outlet": key})
    if not isinstance(data, dict) or not data.get("ok"):
        raise ApiError(
            str((data or {}).get("error") if isinstance(data, dict) else "Failed to load catalog")
        )
    return data


def submit_indent(
    client: ApiClient,
    *,
    outlet: str,
    notes: str,
    action: str,
    lines: list[dict[str, Any]],
) -> dict[str, Any]:
    error = validate_lines(lines)
    if error:
        raise ApiError(error)
    action_key = "submit" if str(action or "").strip().lower() == "submit" else "save"
    payload = {
        "outlet": (outlet or "").strip().lower() or "restaurant",
        "notes": (notes or "").strip(),
        "action": action_key,
        "lines": [
            {
                "item_name": str(line.get("item_name") or "").strip(),
                "quantity": line.get("quantity"),
                "unit": str(line.get("unit") or "pcs").strip() or "pcs",
                "approximate_price": line.get("approximate_price"),
                "pack_label": str(line.get("pack_label") or "").strip(),
                "pack_qty_in_base": line.get("pack_qty_in_base"),
            }
            for line in lines
        ],
    }
    data = client.post_json("/stores/api/indent", payload)
    if not isinstance(data, dict) or not data.get("ok"):
        raise ApiError(
            str((data or {}).get("error") if isinstance(data, dict) else "Could not save indent")
        )
    return data
