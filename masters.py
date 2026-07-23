"""Master data dashboard configuration for Hotel Bell Elite."""

from __future__ import annotations

MASTER_CATEGORY_LABELS = {
    "all": "All",
    "restaurant": "Restaurant",
    "inventory": "Inventory",
    "accounts": "Accounts",
    "hr": "HR",
    "sales": "Sales",
    "others": "Others",
}

# Server-driven master cards. Add entries here to surface new masters on /master.
# record_count falls back to placeholder when not present in DB counts.
MASTER_DEFINITIONS = [
    {
        "id": "supplier",
        "name": "Supplier Master",
        "icon": "truck",
        "icon_tone": "blue",
        "category": "accounts",
        "route": "supplier_master",
        "path": "/suppliers",
        "record_count": 248,
        "active": True,
        "recently_updated": True,
    },
    {
        "id": "customer",
        "name": "Customer Master",
        "icon": "user",
        "icon_tone": "teal",
        "category": "sales",
        "route": "customer_master",
        "path": "/customers",
        "record_count": 0,
        "active": True,
        "recently_updated": True,
    },
    {
        "id": "product",
        "name": "Product Master",
        "icon": "package",
        "icon_tone": "amber",
        "category": "inventory",
        "route": "stores_product_master",
        "path": "/stores/product-master",
        "record_count": 512,
        "active": True,
        "recently_updated": True,
    },
    {
        "id": "category",
        "name": "Category Master",
        "icon": "tag",
        "icon_tone": "violet",
        "category": "inventory",
        "route": None,
        "record_count": 36,
        "active": True,
        "recently_updated": False,
    },
    {
        "id": "employee",
        "name": "Employee Master",
        "icon": "person",
        "icon_tone": "cyan",
        "category": "hr",
        "route": "employees",
        "path": "/employees",
        "record_count": 156,
        "active": True,
        "recently_updated": True,
    },
]

_DB_COUNT_QUERIES = {
    "supplier": "SELECT COUNT(*) AS n FROM suppliers",
    "customer": "SELECT COUNT(*) AS n FROM customers",
    "product": "SELECT COUNT(*) AS n FROM store_products",
    "employee": "SELECT COUNT(*) AS n FROM employees WHERE status = 'active'",
}


def _fetch_db_record_counts(conn):
    """Load live record counts where tables exist; ignore failures."""
    counts = {}
    if conn is None:
        return counts
    for master_id, sql in _DB_COUNT_QUERIES.items():
        try:
            row = conn.execute(sql).fetchone()
            if row is not None:
                counts[master_id] = int(row["n"] if isinstance(row, dict) else row[0])
        except Exception:
            continue
    return counts


def _resolve_href(route_name, url_for_fn, fallback_path=None):
    if route_name:
        try:
            return url_for_fn(route_name)
        except Exception:
            pass
    if fallback_path:
        return fallback_path
    return "#"


def build_masters_dashboard(url_for_fn, conn=None):
    """Build template/JSON payload for the Masters dashboard."""
    db_counts = _fetch_db_record_counts(conn)
    masters = []
    for item in MASTER_DEFINITIONS:
        master = dict(item)
        master["record_count"] = db_counts.get(item["id"], item.get("record_count", 0))
        master["href"] = _resolve_href(
            item.get("route"),
            url_for_fn,
            item.get("path"),
        )
        masters.append(master)

    total_masters = len(masters)
    active_masters = sum(1 for m in masters if m.get("active", True))
    total_records = sum(int(m.get("record_count") or 0) for m in masters)
    recently_updated = sum(1 for m in masters if m.get("recently_updated"))

    return {
        "masters": masters,
        "master_categories": [
            {"key": key, "label": label}
            for key, label in MASTER_CATEGORY_LABELS.items()
        ],
        "masters_kpis": {
            "total_masters": total_masters,
            "active_masters": active_masters,
            "total_records": total_records,
            "recently_updated": recently_updated,
        },
    }
