import json
import os
import sqlite3
from datetime import datetime

from werkzeug.security import generate_password_hash

DATABASE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bell_elite.db")
SQL_NOW = "datetime('now','localtime')"


def get_db():
    conn = sqlite3.connect(DATABASE_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def empty_pos_floor_payload():
    """Empty floor layout when nothing is saved yet."""
    return {"areas": [], "tables": []}


def _normalize_pos_floor_payload(areas, tables):
    """Return a lean, validated floor payload (areas + tables)."""
    clean_areas = []
    seen_area = set()
    for raw in areas or []:
        if not isinstance(raw, dict):
            continue
        area_id = str(raw.get("id") or "").strip()
        name = str(raw.get("name") or "").strip() or "Area"
        if not area_id or area_id in seen_area:
            continue
        seen_area.add(area_id)
        clean_areas.append({"id": area_id, "type": "area", "name": name})

    clean_tables = []
    seen_table = set()
    for raw in tables or []:
        if not isinstance(raw, dict):
            continue
        table_id = str(raw.get("id") or "").strip()
        if not table_id or table_id in seen_table:
            continue
        seen_table.add(table_id)
        seats = raw.get("seats", 2)
        try:
            seats = max(1, int(seats))
        except (TypeError, ValueError):
            seats = 2
        shape = str(raw.get("shape") or "square").strip() or "square"
        status = str(raw.get("status") or "available").strip() or "available"
        area_id = raw.get("areaId")
        if area_id is not None:
            area_id = str(area_id).strip() or None
        clean_tables.append(
            {
                "id": table_id,
                "type": "table",
                "name": str(raw.get("name") or "").strip() or table_id,
                "seats": seats,
                "shape": shape,
                "status": status,
                "areaId": area_id,
            }
        )
    return {"areas": clean_areas, "tables": clean_tables}


def ensure_pos_schema(conn):
    """Create lean POS floor, settings, and menu tables (soft migration)."""
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS pos_floor_layout (
            id          INTEGER PRIMARY KEY CHECK (id = 1),
            payload     TEXT    NOT NULL,
            updated_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS pos_restaurant_settings (
            id          INTEGER PRIMARY KEY CHECK (id = 1),
            payload     TEXT    NOT NULL DEFAULT '{}',
            updated_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS pos_menu_categories (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT    NOT NULL,
            sort_order  INTEGER NOT NULL DEFAULT 0,
            is_visible  INTEGER NOT NULL DEFAULT 1,
            is_active   INTEGER NOT NULL DEFAULT 1,
            created_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS pos_menu_items (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            category_id   INTEGER NOT NULL,
            product_id    INTEGER,
            name          TEXT    NOT NULL,
            code          TEXT    NOT NULL DEFAULT '',
            barcode       TEXT    NOT NULL DEFAULT '',
            variant       TEXT    NOT NULL DEFAULT '',
            rate          REAL    NOT NULL DEFAULT 0,
            sort_order    INTEGER NOT NULL DEFAULT 0,
            is_active     INTEGER NOT NULL DEFAULT 1,
            created_at    TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at    TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (category_id) REFERENCES pos_menu_categories(id)
        )
        """
    )
    item_cols = {
        row[1] for row in cursor.execute("PRAGMA table_info(pos_menu_items)").fetchall()
    }
    if "product_id" not in item_cols:
        cursor.execute("ALTER TABLE pos_menu_items ADD COLUMN product_id INTEGER")
    _pos_menu_item_extra_cols = {
        "menu_type": "TEXT NOT NULL DEFAULT ''",
        "portion_size": "TEXT NOT NULL DEFAULT ''",
        "prep_time_mins": "INTEGER",
        "shelf_life": "TEXT NOT NULL DEFAULT ''",
        "notes": "TEXT NOT NULL DEFAULT ''",
        "target_margin_pct": "REAL",
        "updated_by": "TEXT NOT NULL DEFAULT ''",
    }
    for col_name, col_ddl in _pos_menu_item_extra_cols.items():
        if col_name not in item_cols:
            cursor.execute(f"ALTER TABLE pos_menu_items ADD COLUMN {col_name} {col_ddl}")
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_pos_menu_items_category
        ON pos_menu_items(category_id, is_active)
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_pos_menu_items_product
        ON pos_menu_items(product_id, is_active)
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS pos_menu_recipe_lines (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            menu_item_id  INTEGER NOT NULL,
            product_id    INTEGER NOT NULL,
            qty           REAL    NOT NULL,
            unit          TEXT    NOT NULL DEFAULT 'g',
            sort_order    INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (menu_item_id) REFERENCES pos_menu_items(id)
        )
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_pos_menu_recipe_item
        ON pos_menu_recipe_lines(menu_item_id, sort_order)
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS pos_menu_price_history (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            menu_item_id  INTEGER NOT NULL,
            old_price     REAL    NOT NULL,
            new_price     REAL    NOT NULL,
            reason        TEXT    NOT NULL DEFAULT '',
            updated_by    TEXT    NOT NULL DEFAULT '',
            created_at    TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (menu_item_id) REFERENCES pos_menu_items(id)
        )
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_pos_menu_price_history_item
        ON pos_menu_price_history(menu_item_id, created_at DESC, id DESC)
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS pos_invoices (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            order_no         TEXT    NOT NULL,
            saved_at         TEXT    NOT NULL,
            order_date       TEXT    NOT NULL,
            order_type       TEXT    NOT NULL DEFAULT 'dine_in',
            table_label      TEXT    NOT NULL DEFAULT '',
            captain          TEXT    NOT NULL DEFAULT '',
            customer_name    TEXT    NOT NULL DEFAULT '',
            customer_mobile  TEXT    NOT NULL DEFAULT '',
            notes            TEXT    NOT NULL DEFAULT '',
            discount_type    TEXT    NOT NULL DEFAULT 'pct',
            discount_value   REAL    NOT NULL DEFAULT 0,
            service_type     TEXT    NOT NULL DEFAULT 'pct',
            service_value    REAL    NOT NULL DEFAULT 0,
            tip_amount       REAL    NOT NULL DEFAULT 0,
            coupon_code      TEXT    NOT NULL DEFAULT '',
            subtotal         REAL    NOT NULL DEFAULT 0,
            discount_amount  REAL    NOT NULL DEFAULT 0,
            gst_amount       REAL    NOT NULL DEFAULT 0,
            service_amount   REAL    NOT NULL DEFAULT 0,
            tip              REAL    NOT NULL DEFAULT 0,
            round_off        REAL    NOT NULL DEFAULT 0,
            grand_total      REAL    NOT NULL DEFAULT 0,
            created_by       TEXT    NOT NULL DEFAULT '',
            is_active        INTEGER NOT NULL DEFAULT 1,
            created_at       TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at       TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        )
        """
    )
    cursor.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_pos_invoices_order_no
        ON pos_invoices(order_no)
        WHERE is_active = 1
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_pos_invoices_date
        ON pos_invoices(order_date, is_active)
        """
    )
    invoice_cols = {
        row[1] for row in cursor.execute("PRAGMA table_info(pos_invoices)").fetchall()
    }
    # Bill lifecycle ('open' -> 'closed') and KOT tracking — occupancy flips when a
    # dine-in bill with a table is saved (items on the table); closing frees it.
    if "status" not in invoice_cols:
        cursor.execute("ALTER TABLE pos_invoices ADD COLUMN status TEXT NOT NULL DEFAULT 'open'")
    if "kot_sent" not in invoice_cols:
        cursor.execute("ALTER TABLE pos_invoices ADD COLUMN kot_sent INTEGER NOT NULL DEFAULT 0")
    if "first_kot_at" not in invoice_cols:
        cursor.execute("ALTER TABLE pos_invoices ADD COLUMN first_kot_at TEXT NOT NULL DEFAULT ''")
    if "customer_bill_sent" not in invoice_cols:
        cursor.execute(
            "ALTER TABLE pos_invoices ADD COLUMN customer_bill_sent INTEGER NOT NULL DEFAULT 0"
        )
    if "customer_bill_at" not in invoice_cols:
        cursor.execute(
            "ALTER TABLE pos_invoices ADD COLUMN customer_bill_at TEXT NOT NULL DEFAULT ''"
        )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_pos_invoices_table_open
        ON pos_invoices(table_label, status, order_type, is_active)
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS pos_invoice_lines (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_id    INTEGER NOT NULL,
            sort_order    INTEGER NOT NULL DEFAULT 0,
            menu_item_id  INTEGER,
            name          TEXT    NOT NULL DEFAULT '',
            variant       TEXT    NOT NULL DEFAULT '',
            rate          REAL    NOT NULL DEFAULT 0,
            qty           REAL    NOT NULL DEFAULT 0,
            line_total    REAL    NOT NULL DEFAULT 0,
            FOREIGN KEY (invoice_id) REFERENCES pos_invoices(id)
        )
        """
    )
    line_cols = {
        row[1] for row in cursor.execute("PRAGMA table_info(pos_invoice_lines)").fetchall()
    }
    if "sent_qty" not in line_cols:
        cursor.execute("ALTER TABLE pos_invoice_lines ADD COLUMN sent_qty REAL NOT NULL DEFAULT 0")
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_pos_invoice_lines_invoice
        ON pos_invoice_lines(invoice_id, sort_order)
        """
    )
    ensure_customers_schema(conn)
    conn.commit()


def _normalize_customer_mobile(value):
    return "".join(ch for ch in str(value or "") if ch.isdigit())[:10]


def _normalize_customer_first_name(value):
    return " ".join(str(value or "").split()).strip()


def ensure_customers_schema(conn):
    """Customer Master table shared with POS Customer Details (unique mobile)."""
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS customers (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            first_name  TEXT    NOT NULL DEFAULT '',
            mobile      TEXT    NOT NULL DEFAULT '',
            created_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        )
        """
    )
    cursor.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_customers_mobile_unique
        ON customers(mobile) WHERE mobile != ''
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_customers_name
        ON customers(LOWER(first_name))
        """
    )
    _backfill_customers_from_invoices(conn)


def _backfill_customers_from_invoices(conn):
    """Seed Customer Master once from existing POS invoices (latest name per mobile)."""
    try:
        count_row = conn.execute("SELECT COUNT(*) AS n FROM customers").fetchone()
        if count_row and int(count_row["n"] if isinstance(count_row, dict) else count_row[0]):
            return
        # Prefer the most recent invoice name for each mobile.
        rows = conn.execute(
            """
            SELECT customer_mobile, customer_name
            FROM pos_invoices
            WHERE TRIM(COALESCE(customer_mobile, '')) != ''
              AND is_active = 1
            ORDER BY id DESC
            """
        ).fetchall()
    except Exception:
        return

    seen = set()
    for row in rows:
        mobile = _normalize_customer_mobile(row["customer_mobile"] if row else "")
        if len(mobile) != 10 or mobile in seen:
            continue
        seen.add(mobile)
        first_name = _normalize_customer_first_name(
            row["customer_name"] if row else ""
        ) or "Guest"
        try:
            conn.execute(
                f"""
                INSERT INTO customers (first_name, mobile, created_at, updated_at)
                VALUES (?, ?, {SQL_NOW}, {SQL_NOW})
                """,
                (first_name, mobile),
            )
        except Exception:
            continue


def customer_row_to_dict(row):
    if not row:
        return None
    return {
        "id": row["id"],
        "first_name": row["first_name"] or "",
        "name": row["first_name"] or "",  # POS autocomplete expects .name
        "mobile": row["mobile"] or "",
    }


def list_customers(conn):
    ensure_customers_schema(conn)
    rows = conn.execute(
        """
        SELECT id, first_name, mobile
        FROM customers
        ORDER BY LOWER(first_name), mobile, id
        """
    ).fetchall()
    return [customer_row_to_dict(row) for row in rows]


def get_customer(conn, customer_id):
    ensure_customers_schema(conn)
    if not customer_id:
        return None
    try:
        customer_id = int(customer_id)
    except (TypeError, ValueError):
        return None
    row = conn.execute(
        "SELECT id, first_name, mobile FROM customers WHERE id = ?",
        (customer_id,),
    ).fetchone()
    return customer_row_to_dict(row)


def search_customers(conn, query, limit=8):
    """Match by mobile digits prefix or first-name contains."""
    ensure_customers_schema(conn)
    q = str(query or "").strip()
    digits = _normalize_customer_mobile(q)
    name_q = _normalize_customer_first_name(q).lower()
    if len(digits) < 2 and len(name_q) < 2:
        return []
    try:
        limit = max(1, min(int(limit), 20))
    except (TypeError, ValueError):
        limit = 8

    if len(digits) >= 2:
        rows = conn.execute(
            """
            SELECT id, first_name, mobile
            FROM customers
            WHERE mobile != '' AND mobile LIKE ?
            ORDER BY mobile ASC, LOWER(first_name) ASC, id ASC
            LIMIT ?
            """,
            (digits + "%", limit),
        ).fetchall()
        return [customer_row_to_dict(row) for row in rows]

    rows = conn.execute(
        """
        SELECT id, first_name, mobile
        FROM customers
        WHERE LOWER(first_name) LIKE ?
        ORDER BY LOWER(first_name) ASC, mobile ASC, id ASC
        LIMIT ?
        """,
        ("%" + name_q + "%", limit),
    ).fetchall()
    return [customer_row_to_dict(row) for row in rows]


def upsert_customer(conn, first_name, mobile):
    """Create or update Customer Master from POS (requires 10-digit mobile).

    Unique by normalized mobile. If the mobile already exists, update first name
    when a new name is provided (or fill when the stored name is blank). Incomplete
    mobiles are ignored so partial POS input does not create junk rows.
    """
    ensure_customers_schema(conn)
    mobile = _normalize_customer_mobile(mobile)
    first_name = _normalize_customer_first_name(first_name)
    if len(mobile) != 10:
        return None

    existing = conn.execute(
        "SELECT id, first_name, mobile FROM customers WHERE mobile = ?",
        (mobile,),
    ).fetchone()
    if existing:
        existing_name = _normalize_customer_first_name(existing["first_name"])
        # Update / fill only when POS supplies a name that should replace blank or prior.
        if first_name and first_name != existing_name:
            conn.execute(
                f"""
                UPDATE customers
                SET first_name = ?, updated_at = {SQL_NOW}
                WHERE id = ?
                """,
                (first_name, existing["id"]),
            )
        return get_customer(conn, existing["id"])

    if not first_name:
        first_name = "Guest"
    cursor = conn.execute(
        f"""
        INSERT INTO customers (first_name, mobile, created_at, updated_at)
        VALUES (?, ?, {SQL_NOW}, {SQL_NOW})
        """,
        (first_name, mobile),
    )
    return get_customer(conn, cursor.lastrowid)


def save_customer_record(conn, first_name, mobile, customer_id=None):
    """Insert/update Customer Master. Returns (saved_id, errors)."""
    ensure_customers_schema(conn)
    first_name = _normalize_customer_first_name(first_name)
    mobile = _normalize_customer_mobile(mobile)
    errors = []
    if not first_name:
        errors.append("First name is required.")
    if not mobile:
        errors.append("Mobile number is required.")
    elif len(mobile) != 10:
        errors.append("Mobile number must be a 10-digit number.")
    else:
        existing = conn.execute(
            "SELECT id FROM customers WHERE mobile = ?",
            (mobile,),
        ).fetchone()
        if existing and (customer_id is None or int(existing["id"]) != int(customer_id)):
            errors.append("A customer with this mobile number already exists.")
    if errors:
        return None, errors

    if customer_id:
        conn.execute(
            f"""
            UPDATE customers
            SET first_name = ?, mobile = ?, updated_at = {SQL_NOW}
            WHERE id = ?
            """,
            (first_name, mobile, customer_id),
        )
        return customer_id, []

    cursor = conn.execute(
        f"""
        INSERT INTO customers (first_name, mobile, created_at, updated_at)
        VALUES (?, ?, {SQL_NOW}, {SQL_NOW})
        """,
        (first_name, mobile),
    )
    return int(cursor.lastrowid), []


def delete_customer_record(conn, customer_id):
    ensure_customers_schema(conn)
    try:
        customer_id = int(customer_id)
    except (TypeError, ValueError):
        return False
    cursor = conn.execute("DELETE FROM customers WHERE id = ?", (customer_id,))
    return cursor.rowcount > 0


def list_pos_menu_categories(conn, include_inactive=False):
    """Return menu categories with active item counts."""
    ensure_pos_schema(conn)
    where = "" if include_inactive else "WHERE c.is_active = 1"
    rows = conn.execute(
        f"""
        SELECT
            c.id,
            c.name,
            c.sort_order,
            c.is_visible,
            c.is_active,
            COALESCE(SUM(CASE WHEN i.is_active = 1 THEN 1 ELSE 0 END), 0) AS item_count
        FROM pos_menu_categories c
        LEFT JOIN pos_menu_items i ON i.category_id = c.id
        {where}
        GROUP BY c.id
        ORDER BY c.sort_order ASC, c.name COLLATE NOCASE ASC, c.id ASC
        """
    ).fetchall()
    return [
        {
            "id": int(r["id"]),
            "name": r["name"] or "",
            "sort_order": int(r["sort_order"] or 0),
            "is_visible": bool(r["is_visible"]),
            "is_active": bool(r["is_active"]),
            "item_count": int(r["item_count"] or 0),
        }
        for r in rows
    ]


def save_pos_menu_category(conn, *, category_id=None, name="", is_visible=True, sort_order=None):
    """Create or update a menu category. Returns the saved row dict."""
    ensure_pos_schema(conn)
    clean_name = " ".join(str(name or "").split()).strip()
    if not clean_name:
        raise ValueError("Category name is required.")
    if len(clean_name) > 80:
        raise ValueError("Category name must be 80 characters or fewer.")

    visible = 1 if is_visible else 0
    if category_id:
        existing = conn.execute(
            "SELECT id FROM pos_menu_categories WHERE id = ? AND is_active = 1",
            (int(category_id),),
        ).fetchone()
        if not existing:
            raise ValueError("Category not found.")
        dup = conn.execute(
            """
            SELECT id FROM pos_menu_categories
            WHERE is_active = 1 AND id != ? AND lower(name) = lower(?)
            """,
            (int(category_id), clean_name),
        ).fetchone()
        if dup:
            raise ValueError("A category with this name already exists.")
        if sort_order is None:
            conn.execute(
                f"""
                UPDATE pos_menu_categories
                SET name = ?, is_visible = ?, updated_at = {SQL_NOW}
                WHERE id = ?
                """,
                (clean_name, visible, int(category_id)),
            )
        else:
            conn.execute(
                f"""
                UPDATE pos_menu_categories
                SET name = ?, is_visible = ?, sort_order = ?, updated_at = {SQL_NOW}
                WHERE id = ?
                """,
                (clean_name, visible, int(sort_order), int(category_id)),
            )
        saved_id = int(category_id)
    else:
        dup = conn.execute(
            """
            SELECT id FROM pos_menu_categories
            WHERE is_active = 1 AND lower(name) = lower(?)
            """,
            (clean_name,),
        ).fetchone()
        if dup:
            raise ValueError("A category with this name already exists.")
        if sort_order is None:
            max_row = conn.execute(
                "SELECT COALESCE(MAX(sort_order), 0) AS m FROM pos_menu_categories WHERE is_active = 1"
            ).fetchone()
            sort_order = int(max_row["m"] or 0) + 10
        cur = conn.execute(
            f"""
            INSERT INTO pos_menu_categories (name, sort_order, is_visible, is_active, created_at, updated_at)
            VALUES (?, ?, ?, 1, {SQL_NOW}, {SQL_NOW})
            """,
            (clean_name, int(sort_order), visible),
        )
        saved_id = int(cur.lastrowid)

    row = conn.execute(
        """
        SELECT
            c.id,
            c.name,
            c.sort_order,
            c.is_visible,
            c.is_active,
            COALESCE(SUM(CASE WHEN i.is_active = 1 THEN 1 ELSE 0 END), 0) AS item_count
        FROM pos_menu_categories c
        LEFT JOIN pos_menu_items i ON i.category_id = c.id
        WHERE c.id = ?
        GROUP BY c.id
        """,
        (saved_id,),
    ).fetchone()
    return {
        "id": int(row["id"]),
        "name": row["name"] or "",
        "sort_order": int(row["sort_order"] or 0),
        "is_visible": bool(row["is_visible"]),
        "is_active": bool(row["is_active"]),
        "item_count": int(row["item_count"] or 0),
    }


def soft_delete_pos_menu_category(conn, category_id):
    """Soft-delete a menu category (and its items)."""
    ensure_pos_schema(conn)
    existing = conn.execute(
        "SELECT id FROM pos_menu_categories WHERE id = ? AND is_active = 1",
        (int(category_id),),
    ).fetchone()
    if not existing:
        raise ValueError("Category not found.")
    conn.execute(
        f"""
        UPDATE pos_menu_items
        SET is_active = 0, updated_at = {SQL_NOW}
        WHERE category_id = ? AND is_active = 1
        """,
        (int(category_id),),
    )
    conn.execute(
        """
        DELETE FROM pos_menu_recipe_lines
        WHERE menu_item_id IN (
            SELECT id FROM pos_menu_items WHERE category_id = ?
        )
        """,
        (int(category_id),),
    )
    conn.execute(
        f"""
        UPDATE pos_menu_categories
        SET is_active = 0, updated_at = {SQL_NOW}
        WHERE id = ?
        """,
        (int(category_id),),
    )
    return True


# Margin % badge thresholds for Menu & Margin Calculator UI.
# ≥60% healthy (green), 30–60% moderate (orange), <30% low (red).
POS_MENU_MARGIN_HEALTHY_PCT = 60.0
POS_MENU_MARGIN_MODERATE_PCT = 30.0


def _normalize_pos_menu_unit(unit):
    """Normalize product/recipe unit aliases for cost conversion."""
    u = str(unit or "").strip().lower()
    if u in ("ltr", "l", "litre", "liters", "litres"):
        return "liter"
    if u in ("gram", "grams"):
        return "g"
    if u in ("kilogram", "kilograms", "kgs"):
        return "kg"
    if u in ("pc", "piece", "pieces"):
        return "pcs"
    return u or "pcs"


def _qty_in_product_units(qty, recipe_unit, product_unit):
    """Convert a recipe quantity into Product Master default-unit quantity.

    Returns None when units are incompatible (cannot cost the line).
    """
    try:
        amount = float(qty)
    except (TypeError, ValueError):
        return None
    if amount <= 0 or amount != amount:
        return None
    ru = _normalize_pos_menu_unit(recipe_unit)
    pu = _normalize_pos_menu_unit(product_unit)

    # Weight family
    if pu in ("kg", "g") and ru in ("kg", "g"):
        grams = amount * 1000.0 if ru == "kg" else amount
        return grams / 1000.0 if pu == "kg" else grams
    # Volume family
    if pu in ("liter", "ml") and ru in ("liter", "ml"):
        ml = amount * 1000.0 if ru == "liter" else amount
        return ml / 1000.0 if pu == "liter" else ml
    # Count family
    if pu in ("pcs", "dozen") and ru in ("pcs", "dozen"):
        pieces = amount * 12.0 if ru == "dozen" else amount
        return pieces / 12.0 if pu == "dozen" else pieces
    # Same unit (bunch, bottle, pack, case, …)
    if pu == ru:
        return amount
    return None


def recipe_line_food_cost(qty, recipe_unit, product_unit, unit_price):
    """Cost of one recipe line: qty × unit price after unit conversion.

    ``unit_price`` is Product Master approximate_price per default unit.
    Returns None when price or units are missing/incompatible.
    """
    try:
        price = float(unit_price) if unit_price is not None else None
    except (TypeError, ValueError):
        price = None
    if price is None or price < 0 or price != price:
        return None
    converted = _qty_in_product_units(qty, recipe_unit, product_unit)
    if converted is None:
        return None
    return round(converted * price, 4)


def margin_band_for_pct(margin_pct):
    """Return 'healthy' | 'moderate' | 'low' | None for a margin percentage."""
    if margin_pct is None:
        return None
    try:
        pct = float(margin_pct)
    except (TypeError, ValueError):
        return None
    if pct != pct:  # NaN
        return None
    if pct >= POS_MENU_MARGIN_HEALTHY_PCT:
        return "healthy"
    if pct >= POS_MENU_MARGIN_MODERATE_PCT:
        return "moderate"
    return "low"


def margin_status_for_pct(margin_pct):
    """Return Excellent/Good/Average/Low/Critical label for margin analysis UI."""
    if margin_pct is None:
        return None
    try:
        pct = float(margin_pct)
    except (TypeError, ValueError):
        return None
    if pct != pct:
        return None
    if pct >= 70.0:
        return "excellent"
    if pct >= POS_MENU_MARGIN_HEALTHY_PCT:
        return "good"
    if pct >= 45.0:
        return "average"
    if pct >= POS_MENU_MARGIN_MODERATE_PCT:
        return "low"
    return "critical"


def recommended_selling_price(food_cost, target_margin_pct):
    """Selling price needed to hit target margin % given food cost."""
    try:
        cost = float(food_cost)
        target = float(target_margin_pct)
    except (TypeError, ValueError):
        return None
    if cost < 0 or cost != cost or target != target:
        return None
    if target >= 100.0 or target < 0:
        return None
    denom = 1.0 - (target / 100.0)
    if denom <= 0:
        return None
    return round(cost / denom, 2)


def compute_pos_menu_item_margins(selling_price, food_cost):
    """Derive gross margin ₹ / % and badge band from selling price + food cost.

    Missing food cost → food_cost 0 treated as unknown (None metrics) when
    recipe has no priced ingredients; callers pass food_cost=None for that case.
    """
    try:
        price = float(selling_price or 0)
    except (TypeError, ValueError):
        price = 0.0
    if food_cost is None:
        return {
            "food_cost": None,
            "gross_margin": None,
            "margin_pct": None,
            "food_cost_pct": None,
            "margin_band": None,
            "margin_status": None,
        }
    try:
        cost = float(food_cost)
    except (TypeError, ValueError):
        cost = 0.0
    if cost < 0 or cost != cost:
        cost = 0.0
    cost = round(cost, 2)
    if price <= 0:
        return {
            "food_cost": cost,
            "gross_margin": None,
            "margin_pct": None,
            "food_cost_pct": None,
            "margin_band": None,
            "margin_status": None,
        }
    gross = round(price - cost, 2)
    margin_pct = round((gross / price) * 100.0, 2)
    food_cost_pct = round((cost / price) * 100.0, 2)
    return {
        "food_cost": cost,
        "gross_margin": gross,
        "margin_pct": margin_pct,
        "food_cost_pct": food_cost_pct,
        "margin_band": margin_band_for_pct(margin_pct),
        "margin_status": margin_status_for_pct(margin_pct),
    }


def _pos_menu_recipe_line_dict(row):
    """Normalize a recipe join row."""
    price = row["approximate_price"] if "approximate_price" in row.keys() else None
    try:
        price_val = float(price) if price is not None else None
    except (TypeError, ValueError):
        price_val = None
    qty = float(row["qty"] or 0)
    unit = (row["unit"] or "g").strip() or "g"
    product_unit = (row["product_unit"] if "product_unit" in row.keys() else None) or ""
    line_cost = recipe_line_food_cost(qty, unit, product_unit, price_val)
    return {
        "id": int(row["id"]),
        "menu_item_id": int(row["menu_item_id"]),
        "product_id": int(row["product_id"]),
        "product_name": (row["product_name"] if "product_name" in row.keys() else None) or "",
        "product_unit": product_unit,
        "approximate_price": price_val,
        "qty": qty,
        "unit": unit,
        "sort_order": int(row["sort_order"] or 0),
        "line_cost": line_cost,
    }


def list_pos_menu_recipe_lines(conn, menu_item_ids=None):
    """Return recipe lines for one or many menu items (keyed later by caller)."""
    ensure_pos_schema(conn)
    ensure_stores_schema(conn)
    if menu_item_ids is None:
        return []
    if isinstance(menu_item_ids, (int, str)):
        ids = [int(menu_item_ids)]
    else:
        ids = [int(x) for x in menu_item_ids if x is not None]
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"""
        SELECT
            r.id,
            r.menu_item_id,
            r.product_id,
            r.qty,
            r.unit,
            r.sort_order,
            p.name AS product_name,
            p.default_unit AS product_unit,
            p.approximate_price AS approximate_price
        FROM pos_menu_recipe_lines r
        LEFT JOIN store_products p ON p.id = r.product_id
        WHERE r.menu_item_id IN ({placeholders})
        ORDER BY r.menu_item_id ASC, r.sort_order ASC, r.id ASC
        """,
        ids,
    ).fetchall()
    return [_pos_menu_recipe_line_dict(r) for r in rows]


def _attach_pos_menu_recipes(conn, items):
    """Attach recipe[] and margin fields onto each menu item dict."""
    if not items:
        return items
    by_id = {int(it["id"]): it for it in items}
    for it in items:
        it["recipe"] = []
    lines = list_pos_menu_recipe_lines(conn, list(by_id.keys()))
    for line in lines:
        mid = int(line["menu_item_id"])
        if mid in by_id:
            by_id[mid]["recipe"].append(line)
    for it in items:
        recipe = it.get("recipe") or []
        if not recipe:
            margins = compute_pos_menu_item_margins(it.get("rate"), None)
        else:
            costs = [line.get("line_cost") for line in recipe]
            if any(c is None for c in costs):
                # Partial pricing: sum known lines; still show a cost when any priced.
                known = [c for c in costs if c is not None]
                food_cost = round(sum(known), 2) if known else None
            else:
                food_cost = round(sum(costs), 2)
            margins = compute_pos_menu_item_margins(it.get("rate"), food_cost)
        it.update(margins)
    return items


def _default_recipe_unit(product_unit):
    """Weight/volume products default recipe qty to grams."""
    unit = (product_unit or "").strip().lower()
    if unit in ("kg", "liter", "ltr", "l", "litre"):
        return "g"
    return (product_unit or "g").strip() or "g"


def replace_pos_menu_recipe_lines(conn, menu_item_id, recipe):
    """Replace all recipe lines for a menu item. Returns the saved lines."""
    ensure_pos_schema(conn)
    ensure_stores_schema(conn)
    mid = int(menu_item_id)
    existing = conn.execute(
        "SELECT id FROM pos_menu_items WHERE id = ?",
        (mid,),
    ).fetchone()
    if not existing:
        raise ValueError("Menu item not found.")

    conn.execute("DELETE FROM pos_menu_recipe_lines WHERE menu_item_id = ?", (mid,))

    if not recipe:
        return []
    if not isinstance(recipe, list):
        raise ValueError("Recipe must be a list of ingredients.")

    seen = set()
    sort_i = 0
    for raw in recipe:
        if not isinstance(raw, dict):
            continue
        try:
            product_id = int(raw.get("product_id"))
        except (TypeError, ValueError) as exc:
            raise ValueError("Invalid recipe product.") from exc
        if product_id in seen:
            raise ValueError("Each product can only appear once in the recipe.")
        product_row = conn.execute(
            """
            SELECT id, name, default_unit
            FROM store_products
            WHERE id = ? AND is_active = 1
            """,
            (product_id,),
        ).fetchone()
        if not product_row:
            raise ValueError("Recipe product not found in Product Master.")

        try:
            qty = float(raw.get("qty"))
        except (TypeError, ValueError) as exc:
            raise ValueError("Recipe quantity must be a number.") from exc
        if qty <= 0:
            raise ValueError("Recipe quantity must be greater than zero.")

        unit = " ".join(str(raw.get("unit") or "").split()).strip()
        if not unit:
            unit = _default_recipe_unit(product_row["default_unit"])
        if len(unit) > 40:
            raise ValueError("Recipe unit is too long.")

        conn.execute(
            """
            INSERT INTO pos_menu_recipe_lines (menu_item_id, product_id, qty, unit, sort_order)
            VALUES (?, ?, ?, ?, ?)
            """,
            (mid, product_id, qty, unit, sort_i),
        )
        seen.add(product_id)
        sort_i += 1

    return list_pos_menu_recipe_lines(conn, mid)


def _pos_menu_item_dict(row):
    """Normalize a pos_menu_items join row to a JSON-friendly dict."""
    product_id = row["product_id"]
    rate = row["rate"]
    category_visible = True
    if "category_visible" in row.keys() and row["category_visible"] is not None:
        category_visible = bool(row["category_visible"])
    keys = row.keys()

    def _text(col, default=""):
        if col not in keys or row[col] is None:
            return default
        return str(row[col] or default)

    prep_time = None
    if "prep_time_mins" in keys and row["prep_time_mins"] is not None:
        try:
            prep_time = int(row["prep_time_mins"])
        except (TypeError, ValueError):
            prep_time = None

    target_margin = None
    if "target_margin_pct" in keys and row["target_margin_pct"] is not None:
        try:
            target_margin = float(row["target_margin_pct"])
        except (TypeError, ValueError):
            target_margin = None

    portion = _text("portion_size")
    if not portion:
        portion = _text("variant")

    return {
        "id": int(row["id"]),
        "category_id": int(row["category_id"]),
        "category_name": (row["category_name"] if "category_name" in keys else None) or "",
        "category_visible": category_visible,
        "product_id": int(product_id) if product_id not in (None, "") else None,
        "product_name": (row["product_name"] if "product_name" in keys else None) or "",
        "product_unit": (row["product_unit"] if "product_unit" in keys else None) or "",
        "name": row["name"] or "",
        "code": row["code"] or "",
        "barcode": row["barcode"] or "",
        "variant": row["variant"] or "",
        "menu_type": _text("menu_type"),
        "portion_size": portion,
        "prep_time_mins": prep_time,
        "shelf_life": _text("shelf_life"),
        "notes": _text("notes"),
        "target_margin_pct": target_margin if target_margin is not None else POS_MENU_MARGIN_HEALTHY_PCT,
        "updated_by": _text("updated_by"),
        "created_at": _text("created_at") if "created_at" in keys else "",
        "updated_at": _text("updated_at") if "updated_at" in keys else "",
        "rate": float(rate or 0),
        "sort_order": int(row["sort_order"] or 0),
        "is_active": bool(row["is_active"]),
        "status": "visible" if category_visible else "hidden",
        "recipe": [],
        "food_cost": None,
        "gross_margin": None,
        "margin_pct": None,
        "food_cost_pct": None,
        "margin_band": None,
        "margin_status": None,
    }


_POS_MENU_ITEM_SELECT = """
            i.id,
            i.category_id,
            i.product_id,
            i.name,
            i.code,
            i.barcode,
            i.variant,
            i.rate,
            i.sort_order,
            i.is_active,
            i.menu_type,
            i.portion_size,
            i.prep_time_mins,
            i.shelf_life,
            i.notes,
            i.target_margin_pct,
            i.updated_by,
            i.created_at,
            i.updated_at,
            c.name AS category_name,
            c.is_visible AS category_visible,
            p.name AS product_name,
            p.default_unit AS product_unit
"""


def list_pos_menu_items(conn, category_id=None, include_inactive=False):
    """Return menu items, optionally filtered by category."""
    ensure_pos_schema(conn)
    ensure_stores_schema(conn)
    clauses = []
    params = []
    if not include_inactive:
        clauses.append("i.is_active = 1")
    if category_id is not None:
        clauses.append("i.category_id = ?")
        params.append(int(category_id))
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f"""
        SELECT
            {_POS_MENU_ITEM_SELECT}
        FROM pos_menu_items i
        LEFT JOIN pos_menu_categories c ON c.id = i.category_id
        LEFT JOIN store_products p ON p.id = i.product_id
        {where}
        ORDER BY i.sort_order ASC, i.name COLLATE NOCASE ASC, i.id ASC
        """,
        params,
    ).fetchall()
    items = [_pos_menu_item_dict(r) for r in rows]
    return _attach_pos_menu_recipes(conn, items)


def get_pos_menu_item(conn, item_id):
    """Return one active menu item with recipe + margin fields, or None."""
    ensure_pos_schema(conn)
    ensure_stores_schema(conn)
    row = conn.execute(
        f"""
        SELECT
            {_POS_MENU_ITEM_SELECT}
        FROM pos_menu_items i
        LEFT JOIN pos_menu_categories c ON c.id = i.category_id
        LEFT JOIN store_products p ON p.id = i.product_id
        WHERE i.id = ? AND i.is_active = 1
        """,
        (int(item_id),),
    ).fetchone()
    if not row:
        return None
    return _attach_pos_menu_recipes(conn, [_pos_menu_item_dict(row)])[0]


def save_pos_menu_item(
    conn,
    *,
    item_id=None,
    category_id=None,
    product_id=None,
    name="",
    code="",
    barcode="",
    variant="",
    rate=0,
    sort_order=None,
    recipe=None,
    menu_type=None,
    portion_size=None,
    prep_time_mins=None,
    shelf_life=None,
    notes=None,
    target_margin_pct=None,
    updated_by=None,
    price_change_reason="",
):
    """Create or update a menu item; optional recipe[] replaces ingredient lines."""
    ensure_pos_schema(conn)
    ensure_stores_schema(conn)

    try:
        cat_id = int(category_id) if category_id not in (None, "") else None
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid category.") from exc
    if not cat_id:
        raise ValueError("Category is required.")
    cat = conn.execute(
        "SELECT id FROM pos_menu_categories WHERE id = ? AND is_active = 1",
        (cat_id,),
    ).fetchone()
    if not cat:
        raise ValueError("Category not found.")

    prod_id = None
    product_row = None
    if product_id not in (None, ""):
        try:
            prod_id = int(product_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("Invalid product.") from exc
        product_row = conn.execute(
            """
            SELECT id, name, default_unit, approximate_price, outlet
            FROM store_products
            WHERE id = ? AND is_active = 1
            """,
            (prod_id,),
        ).fetchone()
        if not product_row:
            raise ValueError("Product not found in Product Master.")

    clean_name = " ".join(str(name or "").split()).strip()
    if not clean_name and product_row:
        clean_name = (product_row["name"] or "").strip()
    if not clean_name:
        raise ValueError("Item name is required.")
    if len(clean_name) > 120:
        raise ValueError("Item name must be 120 characters or fewer.")

    clean_code = " ".join(str(code or "").split()).strip()[:40]
    clean_barcode = " ".join(str(barcode or "").split()).strip()[:64]
    clean_variant = " ".join(str(variant or "").split()).strip()[:80]

    try:
        rate_val = float(rate if rate not in (None, "") else 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("Rate must be a number.") from exc
    if rate_val < 0:
        raise ValueError("Rate cannot be negative.")
    if rate_val == 0 and product_row and product_row["approximate_price"] is not None:
        try:
            approx = float(product_row["approximate_price"])
            if approx > 0:
                rate_val = approx
        except (TypeError, ValueError):
            pass

    existing_row = None
    if item_id:
        existing_row = conn.execute(
            """
            SELECT id, rate, menu_type, portion_size, prep_time_mins, shelf_life,
                   notes, target_margin_pct, updated_by, variant
            FROM pos_menu_items
            WHERE id = ? AND is_active = 1
            """,
            (int(item_id),),
        ).fetchone()
        if not existing_row:
            raise ValueError("Menu item not found.")

    if existing_row:
        cur_menu_type = (existing_row["menu_type"] or "") if "menu_type" in existing_row.keys() else ""
        cur_portion = (existing_row["portion_size"] or "") if "portion_size" in existing_row.keys() else ""
        cur_prep = existing_row["prep_time_mins"] if "prep_time_mins" in existing_row.keys() else None
        cur_shelf = (existing_row["shelf_life"] or "") if "shelf_life" in existing_row.keys() else ""
        cur_notes = (existing_row["notes"] or "") if "notes" in existing_row.keys() else ""
        cur_target = (
            existing_row["target_margin_pct"] if "target_margin_pct" in existing_row.keys() else None
        )
        cur_updated_by = (existing_row["updated_by"] or "") if "updated_by" in existing_row.keys() else ""
    else:
        cur_menu_type = ""
        cur_portion = ""
        cur_prep = None
        cur_shelf = ""
        cur_notes = ""
        cur_target = POS_MENU_MARGIN_HEALTHY_PCT
        cur_updated_by = ""

    if menu_type is None:
        clean_menu_type = cur_menu_type
    else:
        clean_menu_type = str(menu_type or "").strip().lower()
    if clean_menu_type in ("non-veg", "nonveg", "non veg"):
        clean_menu_type = "non_veg"
    if clean_menu_type not in ("", "veg", "non_veg"):
        raise ValueError("Menu type must be Veg or Non-Veg.")
    clean_menu_type = clean_menu_type[:20]

    if portion_size is not None:
        clean_portion = " ".join(str(portion_size or "").split()).strip()[:80]
    elif not existing_row and clean_variant:
        clean_portion = clean_variant
    else:
        clean_portion = cur_portion or ""
    if (
        portion_size is not None
        and clean_portion
        and (not existing_row or not (existing_row["variant"] or "").strip())
        and not clean_variant
    ):
        clean_variant = clean_portion

    if prep_time_mins is None:
        clean_prep = cur_prep
    elif prep_time_mins in ("",):
        clean_prep = None
    else:
        try:
            clean_prep = int(prep_time_mins)
        except (TypeError, ValueError) as exc:
            raise ValueError("Prep time must be a whole number of minutes.") from exc
        if clean_prep < 0:
            raise ValueError("Prep time cannot be negative.")

    clean_shelf = (
        " ".join(str(shelf_life or "").split()).strip()[:80]
        if shelf_life is not None
        else cur_shelf
    )
    clean_notes = str(notes) if notes is not None else cur_notes
    if clean_notes is None:
        clean_notes = ""
    if len(clean_notes) > 8000:
        raise ValueError("Notes are too long.")

    if target_margin_pct is None:
        clean_target = cur_target if cur_target is not None else POS_MENU_MARGIN_HEALTHY_PCT
    elif target_margin_pct in ("",):
        clean_target = POS_MENU_MARGIN_HEALTHY_PCT
    else:
        try:
            clean_target = float(target_margin_pct)
        except (TypeError, ValueError) as exc:
            raise ValueError("Target margin must be a number.") from exc
        if clean_target < 0 or clean_target >= 100:
            raise ValueError("Target margin must be between 0 and 100.")

    clean_updated_by = (
        " ".join(str(updated_by or "").split()).strip()[:120]
        if updated_by is not None
        else cur_updated_by
    )

    if item_id:
        old_rate = float(existing_row["rate"] or 0)
        if sort_order is None:
            conn.execute(
                f"""
                UPDATE pos_menu_items
                SET category_id = ?, product_id = ?, name = ?, code = ?, barcode = ?,
                    variant = ?, rate = ?, menu_type = ?, portion_size = ?,
                    prep_time_mins = ?, shelf_life = ?, notes = ?,
                    target_margin_pct = ?, updated_by = ?, updated_at = {SQL_NOW}
                WHERE id = ?
                """,
                (
                    cat_id,
                    prod_id,
                    clean_name,
                    clean_code,
                    clean_barcode,
                    clean_variant,
                    rate_val,
                    clean_menu_type,
                    clean_portion,
                    clean_prep,
                    clean_shelf,
                    clean_notes,
                    clean_target,
                    clean_updated_by,
                    int(item_id),
                ),
            )
        else:
            conn.execute(
                f"""
                UPDATE pos_menu_items
                SET category_id = ?, product_id = ?, name = ?, code = ?, barcode = ?,
                    variant = ?, rate = ?, sort_order = ?, menu_type = ?, portion_size = ?,
                    prep_time_mins = ?, shelf_life = ?, notes = ?,
                    target_margin_pct = ?, updated_by = ?, updated_at = {SQL_NOW}
                WHERE id = ?
                """,
                (
                    cat_id,
                    prod_id,
                    clean_name,
                    clean_code,
                    clean_barcode,
                    clean_variant,
                    rate_val,
                    int(sort_order),
                    clean_menu_type,
                    clean_portion,
                    clean_prep,
                    clean_shelf,
                    clean_notes,
                    clean_target,
                    clean_updated_by,
                    int(item_id),
                ),
            )
        saved_id = int(item_id)
        if abs(old_rate - rate_val) > 0.0001:
            record_pos_menu_price_change(
                conn,
                saved_id,
                old_price=old_rate,
                new_price=rate_val,
                reason=price_change_reason or "Rate updated",
                updated_by=clean_updated_by,
            )
    else:
        if sort_order is None:
            max_row = conn.execute(
                """
                SELECT COALESCE(MAX(sort_order), 0) AS m
                FROM pos_menu_items
                WHERE category_id = ? AND is_active = 1
                """,
                (cat_id,),
            ).fetchone()
            sort_order = int(max_row["m"] or 0) + 10
        cur = conn.execute(
            f"""
            INSERT INTO pos_menu_items (
                category_id, product_id, name, code, barcode, variant, rate,
                sort_order, is_active, menu_type, portion_size, prep_time_mins,
                shelf_life, notes, target_margin_pct, updated_by,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, {SQL_NOW}, {SQL_NOW})
            """,
            (
                cat_id,
                prod_id,
                clean_name,
                clean_code,
                clean_barcode,
                clean_variant,
                rate_val,
                int(sort_order),
                clean_menu_type,
                clean_portion,
                clean_prep,
                clean_shelf,
                clean_notes,
                clean_target,
                clean_updated_by,
            ),
        )
        saved_id = int(cur.lastrowid)

    if recipe is not None:
        replace_pos_menu_recipe_lines(conn, saved_id, recipe)
    elif not item_id:
        replace_pos_menu_recipe_lines(conn, saved_id, [])

    item = get_pos_menu_item(conn, saved_id)
    if not item:
        raise ValueError("Menu item not found after save.")
    return item


def record_pos_menu_price_change(
    conn, menu_item_id, *, old_price, new_price, reason="", updated_by=""
):
    """Append a selling-price history row."""
    ensure_pos_schema(conn)
    try:
        old_v = float(old_price)
        new_v = float(new_price)
    except (TypeError, ValueError):
        return None
    conn.execute(
        f"""
        INSERT INTO pos_menu_price_history (
            menu_item_id, old_price, new_price, reason, updated_by, created_at
        )
        VALUES (?, ?, ?, ?, ?, {SQL_NOW})
        """,
        (
            int(menu_item_id),
            round(old_v, 2),
            round(new_v, 2),
            " ".join(str(reason or "").split()).strip()[:200],
            " ".join(str(updated_by or "").split()).strip()[:120],
        ),
    )
    return True


def list_pos_menu_price_history(conn, menu_item_id, limit=50):
    """Return newest-first price history for a menu item."""
    ensure_pos_schema(conn)
    try:
        lim = max(1, min(int(limit or 50), 200))
    except (TypeError, ValueError):
        lim = 50
    rows = conn.execute(
        """
        SELECT id, menu_item_id, old_price, new_price, reason, updated_by, created_at
        FROM pos_menu_price_history
        WHERE menu_item_id = ?
        ORDER BY created_at DESC, id DESC
        LIMIT ?
        """,
        (int(menu_item_id), lim),
    ).fetchall()
    out = []
    for r in rows:
        out.append(
            {
                "id": int(r["id"]),
                "menu_item_id": int(r["menu_item_id"]),
                "old_price": float(r["old_price"] or 0),
                "new_price": float(r["new_price"] or 0),
                "reason": r["reason"] or "",
                "updated_by": r["updated_by"] or "",
                "created_at": r["created_at"] or "",
            }
        )
    return out


def _fifo_remaining_layers(conn, item_name, unit):
    """Rebuild remaining receive layers for a stock item using FIFO drain.

    Returns list of dicts: batch_no, purchase_date, supplier, available_qty,
    unit_cost, unit, movement_id.
    """
    ensure_stores_schema(conn)
    name = " ".join(str(item_name or "").split()).strip()
    unit_key = " ".join(str(unit or "").split()).strip()
    if not name:
        return []
    rows = conn.execute(
        """
        SELECT id, qty_delta, movement_type, unit_cost, notes, created_at, unit
        FROM store_stock_movements
        WHERE lower(item_name) = lower(?)
          AND lower(unit) = lower(?)
        ORDER BY created_at ASC, id ASC
        """,
        (name, unit_key),
    ).fetchall()
    layers = []
    for row in rows:
        try:
            qty = float(row["qty_delta"] or 0)
        except (TypeError, ValueError):
            continue
        mtype = (row["movement_type"] or "").strip().lower()
        if mtype == "receive" and qty > 0:
            try:
                unit_cost = float(row["unit_cost"]) if row["unit_cost"] is not None else None
            except (TypeError, ValueError):
                unit_cost = None
            supplier = ""
            notes = (row["notes"] or "").strip()
            if notes.lower().startswith("received from "):
                supplier = notes[14:].strip()
            elif notes:
                supplier = notes[:80]
            layers.append(
                {
                    "movement_id": int(row["id"]),
                    "purchase_date": (row["created_at"] or "")[:10],
                    "supplier": supplier or "—",
                    "available_qty": qty,
                    "unit_cost": unit_cost,
                    "unit": row["unit"] or unit_key,
                }
            )
            continue
        drain = abs(qty) if qty < 0 else (
            qty if mtype in ("issue", "adjust", "waste", "transfer") else 0
        )
        if drain <= 0:
            continue
        remaining = drain
        for layer in layers:
            if remaining <= 0:
                break
            take = min(layer["available_qty"], remaining)
            layer["available_qty"] = round(layer["available_qty"] - take, 4)
            remaining = round(remaining - take, 4)
        layers = [layer for layer in layers if layer["available_qty"] > 0.0001]
    out = []
    for idx, layer in enumerate(layers, start=1):
        out.append(
            {
                "batch_no": f"B-{layer['movement_id']}",
                "batch_index": idx,
                "purchase_date": layer["purchase_date"],
                "supplier": layer["supplier"],
                "available_qty": round(layer["available_qty"], 4),
                "unit_cost": layer["unit_cost"],
                "unit": layer["unit"],
                "movement_id": layer["movement_id"],
            }
        )
    return out


def allocate_fifo_for_qty(layers, qty_needed):
    """Allocate qty_needed across FIFO layers. Returns (rows, total_cost, fully_covered)."""
    try:
        need = float(qty_needed)
    except (TypeError, ValueError):
        return [], None, False
    if need <= 0:
        return [], 0.0, True
    rows = []
    remaining = need
    total_cost = 0.0
    priced_ok = True
    for layer in layers:
        if remaining <= 0:
            break
        avail = float(layer.get("available_qty") or 0)
        if avail <= 0:
            continue
        take = min(avail, remaining)
        unit_cost = layer.get("unit_cost")
        cost_used = None
        if unit_cost is not None:
            try:
                cost_used = round(take * float(unit_cost), 4)
                total_cost += cost_used
            except (TypeError, ValueError):
                priced_ok = False
                cost_used = None
        else:
            priced_ok = False
        rows.append(
            {
                "batch_no": layer.get("batch_no") or "",
                "purchase_date": layer.get("purchase_date") or "",
                "supplier": layer.get("supplier") or "—",
                "available_qty": round(avail, 4),
                "unit_cost": unit_cost,
                "qty_used": round(take, 4),
                "cost_used": cost_used,
                "unit": layer.get("unit") or "",
                "product_name": layer.get("product_name") or "",
            }
        )
        remaining = round(remaining - take, 4)
    fully = remaining <= 0.0001
    if not rows:
        return [], None, False
    if not priced_ok:
        return rows, None, fully
    return rows, round(total_cost, 4), fully


def build_pos_menu_fifo_costing(conn, recipe_lines):
    """FIFO batch usage for a recipe. Falls back when stock batches are missing.

    Returns dict with batches, fifo_food_cost, fifo_available, note.
    """
    ensure_stores_schema(conn)
    batches = []
    line_costs = []
    any_layers = False
    all_covered = True
    if not recipe_lines:
        return {
            "batches": [],
            "fifo_food_cost": None,
            "fifo_available": False,
            "fifo_partial": False,
            "note": "No recipe ingredients to cost.",
        }

    for line in recipe_lines:
        product_name = (line.get("product_name") or "").strip()
        product_unit = (line.get("product_unit") or "").strip() or "pcs"
        qty = line.get("qty")
        recipe_unit = line.get("unit") or "g"
        converted = _qty_in_product_units(qty, recipe_unit, product_unit)
        layers = _fifo_remaining_layers(conn, product_name, product_unit) if product_name else []
        for layer in layers:
            layer["product_name"] = product_name
        if layers:
            any_layers = True
        if converted is None:
            all_covered = False
            continue
        rows, cost, fully = allocate_fifo_for_qty(layers, converted)
        for row in rows:
            row["ingredient"] = product_name
            row["required_qty"] = float(qty or 0)
            row["required_unit"] = recipe_unit
            batches.append(row)
        if cost is None or not fully:
            all_covered = False
        elif cost is not None:
            line_costs.append(cost)

    if not any_layers:
        return {
            "batches": [],
            "fifo_food_cost": None,
            "fifo_available": False,
            "fifo_partial": False,
            "note": (
                "FIFO batches unavailable — no stock receive movements found for these "
                "ingredients. Showing approximate Product Master food cost instead."
            ),
        }

    fifo_available = bool(line_costs and all_covered)
    fifo_food_cost = round(sum(line_costs), 2) if line_costs else None
    if fifo_available:
        note = "Food cost allocated from oldest stock receive batches (FIFO)."
    else:
        note = (
            "Partial FIFO coverage — some ingredients lack priced batches or stock. "
            "Use approximate food cost where FIFO is incomplete."
        )
    return {
        "batches": batches,
        "fifo_food_cost": fifo_food_cost,
        "fifo_available": fifo_available,
        "fifo_partial": bool(any_layers and not all_covered and line_costs),
        "note": note,
    }


def get_pos_menu_item_details(conn, item_id):
    """Rich payload for Menu Details popup (recipe, FIFO, history, analysis)."""
    item = get_pos_menu_item(conn, item_id)
    if not item:
        return None

    recipe = item.get("recipe") or []
    fifo = build_pos_menu_fifo_costing(conn, recipe)
    approx_food_cost = item.get("food_cost")
    fifo_cost = fifo.get("fifo_food_cost")
    display_food_cost = (
        fifo_cost if fifo.get("fifo_available") and fifo_cost is not None else approx_food_cost
    )
    margins = compute_pos_menu_item_margins(item.get("rate"), display_food_cost)
    target = item.get("target_margin_pct")
    if target is None:
        target = POS_MENU_MARGIN_HEALTHY_PCT
    recommended = recommended_selling_price(display_food_cost, target)

    analysis = {
        "selling_price": float(item.get("rate") or 0),
        "fifo_food_cost": display_food_cost,
        "approximate_food_cost": approx_food_cost,
        "gross_profit": margins.get("gross_margin"),
        "margin_pct": margins.get("margin_pct"),
        "food_cost_pct": margins.get("food_cost_pct"),
        "target_margin_pct": target,
        "recommended_selling_price": recommended,
        "profit_per_portion": margins.get("gross_margin"),
        "margin_status": margins.get("margin_status"),
        "margin_band": margins.get("margin_band"),
        "cost_source": "fifo" if fifo.get("fifo_available") else "approximate",
    }

    detail = dict(item)
    detail.update(margins)
    detail["food_cost"] = approx_food_cost
    detail["display_food_cost"] = display_food_cost
    detail["fifo"] = fifo
    detail["analysis"] = analysis
    detail["price_history"] = list_pos_menu_price_history(conn, item_id)
    detail["recipe_total_cost"] = approx_food_cost
    detail["inventory_url"] = "/stores/stock?outlet=restaurant"
    return detail


def soft_delete_pos_menu_item(conn, item_id):
    """Soft-delete a menu item and clear its recipe lines."""
    ensure_pos_schema(conn)
    existing = conn.execute(
        "SELECT id FROM pos_menu_items WHERE id = ? AND is_active = 1",
        (int(item_id),),
    ).fetchone()
    if not existing:
        raise ValueError("Menu item not found.")
    conn.execute("DELETE FROM pos_menu_recipe_lines WHERE menu_item_id = ?", (int(item_id),))
    conn.execute(
        f"""
        UPDATE pos_menu_items
        SET is_active = 0, updated_at = {SQL_NOW}
        WHERE id = ?
        """,
        (int(item_id),),
    )
    return True


def list_store_products_lite(conn, *, outlets=None, q=""):
    """Active Product Master rows for pickers (id, name, unit, outlet, price)."""
    ensure_stores_schema(conn)
    clauses = ["p.is_active = 1"]
    params = []
    if outlets:
        keys = [str(o or "").strip().lower() for o in outlets if str(o or "").strip()]
        if keys:
            placeholders = ",".join("?" for _ in keys)
            clauses.append(f"lower(p.outlet) IN ({placeholders})")
            params.extend(keys)
    needle = " ".join(str(q or "").split()).strip().lower()
    if needle:
        clauses.append("lower(p.name) LIKE ?")
        params.append(f"%{needle}%")
    where = " AND ".join(clauses)
    rows = conn.execute(
        f"""
        SELECT
            p.id,
            p.name,
            p.default_unit,
            p.outlet,
            p.approximate_price,
            c.name AS category_name
        FROM store_products p
        LEFT JOIN store_product_categories c
          ON c.id = p.category_id AND c.is_active = 1
        WHERE {where}
        ORDER BY
            CASE lower(p.outlet)
                WHEN 'restaurant' THEN 0
                WHEN 'both' THEN 1
                ELSE 2
            END,
            p.name COLLATE NOCASE ASC,
            p.id ASC
        LIMIT 500
        """,
        params,
    ).fetchall()
    result = []
    for r in rows:
        price = r["approximate_price"]
        try:
            price_val = float(price) if price is not None else None
        except (TypeError, ValueError):
            price_val = None
        result.append(
            {
                "id": int(r["id"]),
                "name": r["name"] or "",
                "default_unit": r["default_unit"] or "",
                "outlet": (r["outlet"] or "").strip().lower() or "restaurant",
                "approximate_price": price_val,
                "category_name": r["category_name"] or "",
            }
        )
    return result


def get_pos_floor_layout(conn):
    """Load floor areas/tables JSON; returns empty lists when unset."""
    ensure_pos_schema(conn)
    row = conn.execute("SELECT payload FROM pos_floor_layout WHERE id = 1").fetchone()
    if not row:
        return empty_pos_floor_payload()
    try:
        parsed = json.loads(row["payload"] or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}
    areas = parsed.get("areas")
    tables = parsed.get("tables")
    if not isinstance(areas, list) or not isinstance(tables, list):
        return empty_pos_floor_payload()
    return _normalize_pos_floor_payload(areas, tables)


def save_pos_floor_layout(conn, areas, tables):
    """Replace singleton floor layout payload."""
    ensure_pos_schema(conn)
    payload = _normalize_pos_floor_payload(areas, tables)
    blob = json.dumps(payload, separators=(",", ":"))
    conn.execute(
        f"""
        INSERT INTO pos_floor_layout (id, payload, updated_at)
        VALUES (1, ?, {SQL_NOW})
        ON CONFLICT(id) DO UPDATE SET
            payload = excluded.payload,
            updated_at = {SQL_NOW}
        """
    , (blob,))
    return payload


def get_pos_restaurant_settings(conn):
    """Load restaurant settings JSON blob (empty dict when unset)."""
    ensure_pos_schema(conn)
    row = conn.execute("SELECT payload FROM pos_restaurant_settings WHERE id = 1").fetchone()
    if not row:
        return {}
    try:
        parsed = json.loads(row["payload"] or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def save_pos_restaurant_settings(conn, settings):
    """Replace singleton restaurant settings JSON."""
    ensure_pos_schema(conn)
    if not isinstance(settings, dict):
        settings = {}
    blob = json.dumps(settings, separators=(",", ":"))
    conn.execute(
        f"""
        INSERT INTO pos_restaurant_settings (id, payload, updated_at)
        VALUES (1, ?, {SQL_NOW})
        ON CONFLICT(id) DO UPDATE SET
            payload = excluded.payload,
            updated_at = {SQL_NOW}
        """
    , (blob,))
    return settings


POS_INVOICE_ORDER_TYPES = (
    ("dine_in", "Dine In"),
    ("takeaway", "Takeaway"),
    ("delivery", "Delivery"),
)
POS_INVOICE_ORDER_TYPE_LABELS = dict(POS_INVOICE_ORDER_TYPES)


def _pos_money(value, default=0.0):
    try:
        n = float(value)
    except (TypeError, ValueError):
        return float(default)
    if n != n:  # NaN
        return float(default)
    return round(n, 2)


def _normalize_pos_order_type(value):
    key = str(value or "").strip().lower().replace(" ", "_").replace("-", "_")
    if key in ("dinein", "dine"):
        key = "dine_in"
    if key not in POS_INVOICE_ORDER_TYPE_LABELS:
        return "dine_in"
    return key


def _pos_invoice_line_dicts(conn, invoice_id):
    rows = conn.execute(
        """
        SELECT id, sort_order, menu_item_id, name, variant, rate, qty, line_total, sent_qty
        FROM pos_invoice_lines
        WHERE invoice_id = ?
        ORDER BY sort_order ASC, id ASC
        """,
        (int(invoice_id),),
    ).fetchall()
    lines = []
    for row in rows:
        qty = _pos_money(row["qty"])
        sent_qty = _pos_money(row["sent_qty"])
        if sent_qty > qty:
            sent_qty = qty
        lines.append(
            {
                "id": int(row["id"]),
                "sort_order": int(row["sort_order"] or 0),
                "menu_item_id": int(row["menu_item_id"]) if row["menu_item_id"] is not None else None,
                "name": row["name"] or "",
                "variant": row["variant"] or "",
                "rate": _pos_money(row["rate"]),
                "qty": qty,
                "line_total": _pos_money(row["line_total"]),
                "sent_qty": sent_qty,
            }
        )
    return lines


def _pos_invoice_row_to_dict(conn, row, *, include_lines=False):
    if not row:
        return None
    invoice_id = int(row["id"])
    order_type = _normalize_pos_order_type(row["order_type"])
    item = {
        "id": invoice_id,
        "order_no": row["order_no"] or "",
        "saved_at": row["saved_at"] or "",
        "order_date": row["order_date"] or "",
        "order_type": order_type,
        "order_type_label": POS_INVOICE_ORDER_TYPE_LABELS.get(order_type, order_type),
        "table": row["table_label"] or "",
        "table_label": row["table_label"] or "",
        "captain": row["captain"] or "",
        "customer_name": row["customer_name"] or "",
        "customer_mobile": row["customer_mobile"] or "",
        "notes": row["notes"] or "",
        "discount_type": row["discount_type"] or "pct",
        "discount_value": _pos_money(row["discount_value"]),
        "service_type": row["service_type"] or "pct",
        "service_value": _pos_money(row["service_value"]),
        "tip_amount": _pos_money(row["tip_amount"]),
        "coupon_code": row["coupon_code"] or "",
        "subtotal": _pos_money(row["subtotal"]),
        "discount": _pos_money(row["discount_amount"]),
        "gst": _pos_money(row["gst_amount"]),
        "service": _pos_money(row["service_amount"]),
        "tip": _pos_money(row["tip"]),
        "round_off": _pos_money(row["round_off"]),
        "grand_total": _pos_money(row["grand_total"]),
        "created_by": row["created_by"] or "",
        "created_at": row["created_at"] or "",
        "updated_at": row["updated_at"] or "",
        "status": row["status"] or "open",
        "kot_sent": bool(row["kot_sent"]),
        "first_kot_at": row["first_kot_at"] or "",
        "customer_bill_sent": bool(row["customer_bill_sent"]) if "customer_bill_sent" in row.keys() else False,
        "customer_bill_at": (row["customer_bill_at"] or "") if "customer_bill_at" in row.keys() else "",
        "item_count": int(row["item_count"]) if "item_count" in row.keys() else 0,
    }
    if include_lines:
        item["lines"] = _pos_invoice_line_dicts(conn, invoice_id)
        if not item["item_count"]:
            item["item_count"] = len(item["lines"])
    return item


def _pos_floor_table_status(layout, table_label):
    """Case-insensitive floor status lookup for a table name; None when not on the floor."""
    needle = str(table_label or "").strip().lower()
    if not needle:
        return None
    for t in (layout or {}).get("tables") or []:
        if str(t.get("name") or "").strip().lower() == needle:
            return str(t.get("status") or "available").strip().lower() or "available"
    return None


def _pos_mark_table_occupied(conn, table_label):
    """Flip a table to occupied when a dine-in bill claims it (save / autosave / KOT).

    Best-effort: only advances tables that are currently available — never
    overrides reserved/cleaning/inactive set deliberately from the Tables page.
    """
    needle = str(table_label or "").strip().lower()
    if not needle:
        return
    layout = get_pos_floor_layout(conn)
    tables = layout.get("tables") or []
    changed = False
    for t in tables:
        if str(t.get("name") or "").strip().lower() == needle:
            if str(t.get("status") or "available").strip().lower() in ("", "available"):
                t["status"] = "occupied"
                changed = True
            break
    if changed:
        save_pos_floor_layout(conn, layout.get("areas") or [], tables)


def _pos_mark_table_available(conn, table_label):
    """Free a table back to available — used when a bill is explicitly closed.
    Unlike _pos_mark_table_occupied this is an unconditional override: closing a
    bill is a deliberate staff action, so it wins over whatever status the table
    was showing."""
    needle = str(table_label or "").strip().lower()
    if not needle:
        return
    layout = get_pos_floor_layout(conn)
    tables = layout.get("tables") or []
    changed = False
    for t in tables:
        if str(t.get("name") or "").strip().lower() == needle:
            if str(t.get("status") or "").strip().lower() != "available":
                t["status"] = "available"
                changed = True
            break
    if changed:
        save_pos_floor_layout(conn, layout.get("areas") or [], tables)


def sync_pos_floor_occupancy_from_open_orders(conn):
    """Mark Available tables Occupied when they already have an open dine-in bill.

    Repairs tiles that still show Available after items were saved under the
    older KOT-only occupancy rule, and keeps floor status aligned with open orders.
    """
    ensure_pos_schema(conn)
    rows = conn.execute(
        """
        SELECT DISTINCT table_label
        FROM pos_invoices
        WHERE is_active = 1
          AND status = 'open'
          AND order_type = 'dine_in'
          AND TRIM(COALESCE(table_label, '')) != ''
        """
    ).fetchall()
    for row in rows:
        _pos_mark_table_occupied(conn, row["table_label"] if row else "")



def get_open_pos_invoice_for_table(conn, table_label):
    """Return the most recent open dine-in invoice for a table (with lines), or
    None. This is the shared lookup behind 'resume this table's order' on both
    the Tables page and the Create Invoice table picker."""
    ensure_pos_schema(conn)
    needle = str(table_label or "").strip()
    if not needle:
        return None
    row = conn.execute(
        """
        SELECT
            i.*,
            (
                SELECT COUNT(*) FROM pos_invoice_lines l WHERE l.invoice_id = i.id
            ) AS item_count
        FROM pos_invoices i
        WHERE i.is_active = 1
          AND i.status = 'open'
          AND i.order_type = 'dine_in'
          AND LOWER(i.table_label) = LOWER(?)
        ORDER BY i.id DESC
        LIMIT 1
        """,
        (needle,),
    ).fetchone()
    return _pos_invoice_row_to_dict(conn, row, include_lines=True)


def list_pos_kot_pending_summary(conn):
    """Open dine-in orders with unsents (qty > sent_qty) — same rule as the
    invoice page KOT pending check. Powers the Tables page Kitchen Orders
    Pending banner and details modal.

    Includes tables with a plain save (kot_sent=0, sent_qty=0) and Occupied
    tables with later qty bumps — occupancy / kot_sent is intentionally not a
    filter here.
    """
    ensure_pos_schema(conn)
    layout = get_pos_floor_layout(conn)
    floor_by_name = {}
    for t in (layout or {}).get("tables") or []:
        key = str(t.get("name") or "").strip().lower()
        if key:
            floor_by_name[key] = t

    rows = conn.execute(
        """
        SELECT
            i.id AS invoice_id,
            i.order_no AS order_no,
            i.table_label AS name,
            i.saved_at AS saved_at,
            i.updated_at AS updated_at,
            i.first_kot_at AS first_kot_at,
            COUNT(l.id) AS pending_items,
            COALESCE(SUM(l.qty - COALESCE(l.sent_qty, 0)), 0) AS pending_qty
        FROM pos_invoices i
        JOIN pos_invoice_lines l
          ON l.invoice_id = i.id
         AND l.qty > COALESCE(l.sent_qty, 0)
        WHERE i.is_active = 1
          AND i.status = 'open'
          AND i.order_type = 'dine_in'
          AND TRIM(COALESCE(i.table_label, '')) != ''
        GROUP BY i.id, i.order_no, i.table_label, i.saved_at, i.updated_at, i.first_kot_at
        ORDER BY i.id ASC
        """
    ).fetchall()
    tables = []
    pending_item_count = 0
    for row in rows:
        pending_items = int(row["pending_items"] or 0)
        pending_qty = int(float(row["pending_qty"] or 0))
        pending_item_count += pending_items
        name = (row["name"] or "").strip()
        floor = floor_by_name.get(name.lower()) or {}
        seats = floor.get("seats")
        try:
            seats = int(seats) if seats is not None and str(seats).strip() != "" else None
        except (TypeError, ValueError):
            seats = None
        table_status = str(floor.get("status") or "available").strip().lower() or "available"
        order_no = (row["order_no"] or "").strip()
        kot_no = order_no
        if kot_no.upper().startswith("ORD-"):
            kot_no = "KOT-" + kot_no[4:]
        elif kot_no and not kot_no.upper().startswith("KOT-"):
            kot_no = "KOT-" + kot_no
        saved_at = (row["saved_at"] or row["updated_at"] or "").strip()
        tables.append(
            {
                "name": name,
                "invoice_id": int(row["invoice_id"]),
                "order_no": order_no,
                "kot_no": kot_no,
                "pending_items": pending_items,
                "pending_qty": pending_qty,
                "seats": seats,
                "table_status": table_status,
                "saved_at": saved_at,
            }
        )
    return {
        "pending_table_count": len(tables),
        "pending_item_count": pending_item_count,
        "tables": tables,
    }


def send_pos_invoice_pending_kot(conn, invoice_id):
    """Mark every unsent line qty as sent for an open invoice (Tables KOT modal).

    Returns the updated invoice dict. Raises ValueError when there is nothing to send.
    """
    ensure_pos_schema(conn)
    try:
        invoice_id = int(invoice_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid invoice id.") from exc

    row = conn.execute(
        """
        SELECT id, order_no, table_label, order_type, kot_sent, first_kot_at, status
        FROM pos_invoices
        WHERE id = ? AND is_active = 1
        """,
        (invoice_id,),
    ).fetchone()
    if not row:
        raise ValueError("Invoice not found.")
    if str(row["status"] or "").strip().lower() != "open":
        raise ValueError("Only open invoices can be sent to kitchen.")

    pending = conn.execute(
        """
        SELECT id, qty, COALESCE(sent_qty, 0) AS sent_qty
        FROM pos_invoice_lines
        WHERE invoice_id = ?
          AND qty > COALESCE(sent_qty, 0)
        """,
        (invoice_id,),
    ).fetchall()
    if not pending:
        raise ValueError("Nothing new to send — kitchen is already up to date.")

    for line in pending:
        conn.execute(
            "UPDATE pos_invoice_lines SET sent_qty = ? WHERE id = ?",
            (float(line["qty"] or 0), int(line["id"])),
        )

    first_kot_at = (row["first_kot_at"] or "").strip()
    if not first_kot_at:
        first_kot_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        f"""
        UPDATE pos_invoices
        SET kot_sent = 1,
            first_kot_at = ?,
            updated_at = {SQL_NOW}
        WHERE id = ?
        """,
        (first_kot_at, invoice_id),
    )

    table_label = (row["table_label"] or "").strip()
    order_type = _normalize_pos_order_type(row["order_type"])
    if table_label and order_type == "dine_in":
        _pos_mark_table_occupied(conn, table_label)

    return get_pos_invoice(conn, invoice_id)


def list_pos_kot_tokens(conn):
    """Open dine-in bills that already have kitchen-sent qty — Tables KOT hub.

    Used to resend / reprint a token when kitchen missed the slip. Only lines with
    sent_qty > 0 are included (the last confirmed kitchen copy).
    """
    ensure_pos_schema(conn)
    layout = get_pos_floor_layout(conn)
    floor_by_name = {}
    for t in (layout or {}).get("tables") or []:
        key = str(t.get("name") or "").strip().lower()
        if key:
            floor_by_name[key] = t

    rows = conn.execute(
        """
        SELECT
            i.id AS invoice_id,
            i.order_no AS order_no,
            i.table_label AS name,
            i.order_type AS order_type,
            i.first_kot_at AS first_kot_at,
            i.saved_at AS saved_at,
            i.updated_at AS updated_at,
            COALESCE(i.customer_bill_sent, 0) AS customer_bill_sent,
            COALESCE(i.customer_bill_at, '') AS customer_bill_at,
            COUNT(l.id) AS sent_items,
            COALESCE(SUM(COALESCE(l.sent_qty, 0)), 0) AS sent_qty
        FROM pos_invoices i
        JOIN pos_invoice_lines l
          ON l.invoice_id = i.id
         AND COALESCE(l.sent_qty, 0) > 0
        WHERE i.is_active = 1
          AND i.status = 'open'
          AND i.order_type = 'dine_in'
          AND TRIM(COALESCE(i.table_label, '')) != ''
        GROUP BY
            i.id, i.order_no, i.table_label, i.order_type,
            i.first_kot_at, i.saved_at, i.updated_at,
            i.customer_bill_sent, i.customer_bill_at
        ORDER BY i.table_label ASC, i.id ASC
        """
    ).fetchall()

    tables = []
    for row in rows:
        name = (row["name"] or "").strip()
        floor = floor_by_name.get(name.lower()) or {}
        seats = floor.get("seats")
        try:
            seats = int(seats) if seats is not None and str(seats).strip() != "" else None
        except (TypeError, ValueError):
            seats = None
        table_status = str(floor.get("status") or "occupied").strip().lower() or "occupied"
        order_no = (row["order_no"] or "").strip()
        kot_no = order_no
        if kot_no.upper().startswith("ORD-"):
            kot_no = "KOT-" + kot_no[4:]
        elif kot_no and not kot_no.upper().startswith("KOT-"):
            kot_no = "KOT-" + kot_no
        sent_at = (row["first_kot_at"] or row["updated_at"] or row["saved_at"] or "").strip()
        invoice_id = int(row["invoice_id"])
        line_rows = conn.execute(
            """
            SELECT id, name, variant, qty, COALESCE(sent_qty, 0) AS sent_qty
            FROM pos_invoice_lines
            WHERE invoice_id = ?
              AND COALESCE(sent_qty, 0) > 0
            ORDER BY sort_order ASC, id ASC
            """,
            (invoice_id,),
        ).fetchall()
        lines = []
        for line in line_rows:
            sent_qty = float(line["sent_qty"] or 0)
            lines.append(
                {
                    "id": int(line["id"]),
                    "name": (line["name"] or "").strip(),
                    "variant": (line["variant"] or "").strip(),
                    "qty": sent_qty,
                    "sent_qty": sent_qty,
                }
            )
        tables.append(
            {
                "name": name,
                "invoice_id": invoice_id,
                "order_no": order_no,
                "kot_no": kot_no,
                "order_type": _normalize_pos_order_type(row["order_type"]),
                "sent_items": int(row["sent_items"] or 0),
                "sent_qty": int(float(row["sent_qty"] or 0)),
                "seats": seats,
                "table_status": table_status,
                "sent_at": sent_at,
                "customer_bill_sent": bool(row["customer_bill_sent"]),
                "customer_bill_at": (row["customer_bill_at"] or "").strip(),
                "lines": lines,
            }
        )
    return {
        "token_count": len(tables),
        "tables": tables,
    }


def close_pos_invoice_and_free_table(conn, invoice_id):
    """Close a bill (status -> 'closed') and free its table, if any. Decoupled
    from real payment for now — this is the 'Close & Free Table' action."""
    ensure_pos_schema(conn)
    try:
        invoice_id = int(invoice_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid invoice id.") from exc
    row = conn.execute(
        "SELECT id, table_label, order_type FROM pos_invoices WHERE id = ? AND is_active = 1",
        (invoice_id,),
    ).fetchone()
    if not row:
        raise ValueError("Invoice not found.")
    conn.execute(
        f"""
        UPDATE pos_invoices SET status = 'closed', updated_at = {SQL_NOW}
        WHERE id = ?
        """,
        (invoice_id,),
    )
    table_label = row["table_label"] or ""
    order_type = _normalize_pos_order_type(row["order_type"])
    if table_label and order_type == "dine_in":
        _pos_mark_table_available(conn, table_label)
    return get_pos_invoice(conn, invoice_id)


def clear_all_pos_tables(conn):
    """Bulk-free every table on the floor back to available (Tables page 'Clear
    all tables'). Also closes any dangling open dine-in bills tied to those
    tables so a later resume lookup can't resurrect a stale order."""
    ensure_pos_schema(conn)
    layout = get_pos_floor_layout(conn)
    tables = layout.get("tables") or []
    for t in tables:
        label = str(t.get("name") or "").strip()
        if label:
            conn.execute(
                f"""
                UPDATE pos_invoices SET status = 'closed', updated_at = {SQL_NOW}
                WHERE is_active = 1 AND status = 'open' AND order_type = 'dine_in'
                  AND LOWER(table_label) = LOWER(?)
                """,
                (label,),
            )
        t["status"] = "available"
    return save_pos_floor_layout(conn, layout.get("areas") or [], tables)


def _pos_invoice_line_kitchen_key(menu_item_id, name, variant):
    return (
        str(menu_item_id if menu_item_id is not None else ""),
        str(name or "").strip().lower(),
        str(variant or "").strip().lower(),
    )


def _enforce_pos_kot_line_protections(conn, invoice_id, normalized_lines, *, actor_is_admin):
    """Block non-admins from cutting kitchen-sent qty or removing sent lines."""
    if actor_is_admin or not invoice_id:
        return
    old_rows = conn.execute(
        """
        SELECT menu_item_id, name, variant, qty, COALESCE(sent_qty, 0) AS sent_qty
        FROM pos_invoice_lines
        WHERE invoice_id = ?
          AND COALESCE(sent_qty, 0) > 0
        """,
        (invoice_id,),
    ).fetchall()
    if not old_rows:
        return

    required = {}
    for row in old_rows:
        key = _pos_invoice_line_kitchen_key(row["menu_item_id"], row["name"], row["variant"])
        required[key] = required.get(key, 0.0) + float(row["sent_qty"] or 0)

    available = {}
    for line in normalized_lines:
        key = _pos_invoice_line_kitchen_key(line.get("menu_item_id"), line.get("name"), line.get("variant"))
        available[key] = available.get(key, 0.0) + float(line.get("qty") or 0)

    for key, need in required.items():
        have = available.get(key, 0.0)
        if have + 1e-9 < need:
            raise ValueError(
                "Only an administrator can reduce or remove items after they were sent to the kitchen."
            )


def save_pos_invoice(conn, payload, *, created_by="", actor_is_admin=False):
    """Create or update a POS invoice by order_no. Returns the saved invoice dict.

    Non-administrators cannot reduce qty below kitchen-sent amounts or remove
    lines that already have sent_qty > 0 (post-KOT protection).
    """
    ensure_pos_schema(conn)
    if not isinstance(payload, dict):
        raise ValueError("Invalid invoice payload.")

    order_no = " ".join(str(payload.get("orderNo") or payload.get("order_no") or "").split()).strip()
    if not order_no:
        raise ValueError("Order number is required.")

    customer_name = " ".join(
        str(payload.get("customerName") or payload.get("customer_name") or "").split()
    ).strip()
    if not customer_name:
        raise ValueError("Customer name is required.")

    raw_lines = payload.get("lines")
    if not isinstance(raw_lines, list) or not raw_lines:
        raise ValueError("Add at least one item before saving.")

    totals = payload.get("totals") if isinstance(payload.get("totals"), dict) else {}
    order_type = _normalize_pos_order_type(payload.get("orderType") or payload.get("order_type"))
    saved_at = str(payload.get("savedAt") or payload.get("saved_at") or "").strip()
    if not saved_at:
        saved_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    order_date = str(payload.get("orderDate") or payload.get("order_date") or "").strip()
    if not order_date:
        # ISO or local datetime → date portion
        order_date = saved_at[:10] if len(saved_at) >= 10 else datetime.now().strftime("%Y-%m-%d")
    if "T" in order_date:
        order_date = order_date.split("T", 1)[0]

    customer_mobile = "".join(
        ch for ch in str(payload.get("customerMobile") or payload.get("customer_mobile") or "") if ch.isdigit()
    )[:10]
    table_label = str(payload.get("table") or payload.get("table_label") or "").strip()
    captain = str(payload.get("captain") or "").strip()
    notes = str(payload.get("notes") or "").strip()
    # Keep Customer Master in sync with POS Customer Details (unique 10-digit mobile).
    # Shared by Save, Send to Kitchen, Send to Customer, and any autosave that posts
    # to the same invoice API — incomplete mobiles are intentionally skipped.
    if len(customer_mobile) == 10:
        upsert_customer(conn, customer_name, customer_mobile)
    discount_type = str(
        payload.get("discountType") or totals.get("discountType") or "pct"
    ).strip().lower() or "pct"
    if discount_type not in ("pct", "inr"):
        discount_type = "pct"
    service_type = str(
        payload.get("serviceType") or totals.get("serviceType") or "pct"
    ).strip().lower() or "pct"
    if service_type not in ("pct", "inr"):
        service_type = "pct"
    discount_value = _pos_money(payload.get("discountValue", totals.get("discountValue")))
    service_value = _pos_money(payload.get("serviceValue", totals.get("serviceValue")))
    tip_amount = _pos_money(payload.get("tipAmount", totals.get("tip")))
    coupon_code = str(payload.get("couponCode") or payload.get("coupon_code") or "").strip()

    subtotal = _pos_money(totals.get("subtotal"))
    discount_amount = _pos_money(totals.get("discount"))
    gst_amount = _pos_money(totals.get("gst"))
    service_amount = _pos_money(totals.get("service"))
    tip = _pos_money(totals.get("tip", tip_amount))
    round_off = _pos_money(totals.get("roundOff") or totals.get("round_off"))
    grand_total = _pos_money(totals.get("total") or totals.get("grand_total"))

    normalized_lines = []
    computed_subtotal = 0.0
    for idx, line in enumerate(raw_lines):
        if not isinstance(line, dict):
            continue
        name = " ".join(str(line.get("name") or "").split()).strip()
        if not name:
            continue
        rate = _pos_money(line.get("rate"))
        qty = _pos_money(line.get("qty"))
        if qty <= 0:
            continue
        line_total = _pos_money(rate * qty)
        computed_subtotal += line_total
        menu_item_id = line.get("menuId") if "menuId" in line else line.get("menu_item_id")
        try:
            menu_item_id = int(menu_item_id) if menu_item_id not in (None, "") else None
        except (TypeError, ValueError):
            menu_item_id = None
        sent_qty = _pos_money(line.get("kotSentQty", line.get("sent_qty")))
        if sent_qty < 0:
            sent_qty = 0.0
        if sent_qty > qty:
            sent_qty = qty
        normalized_lines.append(
            {
                "sort_order": idx,
                "menu_item_id": menu_item_id,
                "name": name,
                "variant": str(line.get("variant") or "").strip(),
                "rate": rate,
                "qty": qty,
                "line_total": line_total,
                "sent_qty": sent_qty,
            }
        )
    if not normalized_lines:
        raise ValueError("Add at least one item before saving.")
    if subtotal <= 0:
        subtotal = _pos_money(computed_subtotal)

    # A KOT send persists the order and marks lines as sent to the kitchen.
    # Occupancy is claimed on any dine-in save with a table (see below).
    kot_send = bool(payload.get("kotSend") or payload.get("kot_send"))

    existing = conn.execute(
        """
        SELECT id, kot_sent, first_kot_at, customer_bill_sent, customer_bill_at
        FROM pos_invoices
        WHERE order_no = ? AND is_active = 1
        LIMIT 1
        """,
        (order_no,),
    ).fetchone()

    # A brand-new dine-in bill must not be openable against a table the Tables
    # page already shows as occupied — same floor/tables source of truth used
    # there. Editing an already-saved order (existing order_no) is a resume of
    # that same bill, so it is never blocked here.
    if not existing and table_label and order_type == "dine_in":
        floor_status = _pos_floor_table_status(get_pos_floor_layout(conn), table_label)
        if floor_status == "occupied":
            raise ValueError(
                f'Table "{table_label}" is occupied. Free it on the Tables page or choose another table.'
            )

    was_kot_sent = bool(existing["kot_sent"]) if existing else False
    next_kot_sent = 1 if (kot_send or was_kot_sent) else 0
    first_kot_at = (existing["first_kot_at"] if existing else "") or ""
    if kot_send and not first_kot_at:
        first_kot_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    customer_bill = bool(payload.get("customerBill") or payload.get("customer_bill"))
    was_bill_sent = bool(existing["customer_bill_sent"]) if existing else False
    next_bill_sent = 1 if (customer_bill or was_bill_sent) else 0
    customer_bill_at = (existing["customer_bill_at"] if existing else "") or ""
    if customer_bill and not customer_bill_at:
        customer_bill_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if existing:
        _enforce_pos_kot_line_protections(
            conn,
            int(existing["id"]),
            normalized_lines,
            actor_is_admin=bool(actor_is_admin),
        )

    creator = str(created_by or "").strip()
    if existing:
        invoice_id = int(existing["id"])
        conn.execute(
            f"""
            UPDATE pos_invoices SET
                saved_at = ?,
                order_date = ?,
                order_type = ?,
                table_label = ?,
                captain = ?,
                customer_name = ?,
                customer_mobile = ?,
                notes = ?,
                discount_type = ?,
                discount_value = ?,
                service_type = ?,
                service_value = ?,
                tip_amount = ?,
                coupon_code = ?,
                subtotal = ?,
                discount_amount = ?,
                gst_amount = ?,
                service_amount = ?,
                tip = ?,
                round_off = ?,
                grand_total = ?,
                kot_sent = ?,
                first_kot_at = ?,
                customer_bill_sent = ?,
                customer_bill_at = ?,
                updated_at = {SQL_NOW}
            WHERE id = ?
            """,
            (
                saved_at,
                order_date,
                order_type,
                table_label,
                captain,
                customer_name,
                customer_mobile,
                notes,
                discount_type,
                discount_value,
                service_type,
                service_value,
                tip_amount,
                coupon_code,
                subtotal,
                discount_amount,
                gst_amount,
                service_amount,
                tip,
                round_off,
                grand_total,
                next_kot_sent,
                first_kot_at,
                next_bill_sent,
                customer_bill_at,
                invoice_id,
            ),
        )
        conn.execute("DELETE FROM pos_invoice_lines WHERE invoice_id = ?", (invoice_id,))
    else:
        cursor = conn.execute(
            f"""
            INSERT INTO pos_invoices (
                order_no, saved_at, order_date, order_type, table_label, captain,
                customer_name, customer_mobile, notes,
                discount_type, discount_value, service_type, service_value,
                tip_amount, coupon_code,
                subtotal, discount_amount, gst_amount, service_amount, tip,
                round_off, grand_total, created_by, status, kot_sent, first_kot_at,
                customer_bill_sent, customer_bill_at,
                is_active, created_at, updated_at
            ) VALUES (
                ?, ?, ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?, ?, 'open', ?, ?,
                ?, ?,
                1, {SQL_NOW}, {SQL_NOW}
            )
            """,
            (
                order_no,
                saved_at,
                order_date,
                order_type,
                table_label,
                captain,
                customer_name,
                customer_mobile,
                notes,
                discount_type,
                discount_value,
                service_type,
                service_value,
                tip_amount,
                coupon_code,
                subtotal,
                discount_amount,
                gst_amount,
                service_amount,
                tip,
                round_off,
                grand_total,
                creator,
                next_kot_sent,
                first_kot_at,
                next_bill_sent,
                customer_bill_at,
            ),
        )
        invoice_id = int(cursor.lastrowid)

    for line in normalized_lines:
        conn.execute(
            """
            INSERT INTO pos_invoice_lines (
                invoice_id, sort_order, menu_item_id, name, variant, rate, qty, line_total, sent_qty
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                invoice_id,
                line["sort_order"],
                line["menu_item_id"],
                line["name"],
                line["variant"],
                line["rate"],
                line["qty"],
                line["line_total"],
                line["sent_qty"],
            ),
        )

    # Claim the table as soon as a dine-in bill with items is saved (Save,
    # autosave, Send to Kitchen, Send to Customer). Available → occupied only;
    # reserved/cleaning/inactive are left alone.
    if table_label and order_type == "dine_in":
        _pos_mark_table_occupied(conn, table_label)

    return get_pos_invoice(conn, invoice_id)


def get_pos_invoice(conn, invoice_id):
    """Return one active invoice with lines, or None."""
    ensure_pos_schema(conn)
    try:
        invoice_id = int(invoice_id)
    except (TypeError, ValueError):
        return None
    row = conn.execute(
        """
        SELECT
            i.*,
            (
                SELECT COUNT(*) FROM pos_invoice_lines l WHERE l.invoice_id = i.id
            ) AS item_count
        FROM pos_invoices i
        WHERE i.id = ? AND i.is_active = 1
        """,
        (invoice_id,),
    ).fetchone()
    return _pos_invoice_row_to_dict(conn, row, include_lines=True)


def soft_delete_pos_invoice(conn, invoice_id):
    """Soft-delete an invoice. Raises ValueError if missing."""
    ensure_pos_schema(conn)
    try:
        invoice_id = int(invoice_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid invoice id.") from exc
    row = conn.execute(
        "SELECT id FROM pos_invoices WHERE id = ? AND is_active = 1",
        (invoice_id,),
    ).fetchone()
    if not row:
        raise ValueError("Invoice not found.")
    conn.execute(
        f"""
        UPDATE pos_invoices
        SET is_active = 0, updated_at = {SQL_NOW}
        WHERE id = ?
        """,
        (invoice_id,),
    )
    return True


def list_pos_invoices(
    conn,
    *,
    date_from=None,
    date_to=None,
    order_type=None,
    q="",
):
    """List active invoices with optional filters (newest first)."""
    ensure_pos_schema(conn)
    clauses = ["i.is_active = 1"]
    params = []
    if date_from:
        clauses.append("i.order_date >= ?")
        params.append(str(date_from))
    if date_to:
        clauses.append("i.order_date <= ?")
        params.append(str(date_to))
    if order_type and str(order_type).strip().lower() not in ("", "all"):
        clauses.append("i.order_type = ?")
        params.append(_normalize_pos_order_type(order_type))
    needle = " ".join(str(q or "").split()).strip().lower()
    if needle:
        like = f"%{needle}%"
        clauses.append(
            """
            (
                lower(i.order_no) LIKE ?
                OR lower(i.customer_name) LIKE ?
                OR lower(i.customer_mobile) LIKE ?
                OR lower(i.table_label) LIKE ?
                OR lower(i.captain) LIKE ?
            )
            """
        )
        params.extend([like, like, like, like, like])
    where = " AND ".join(clauses)
    rows = conn.execute(
        f"""
        SELECT
            i.*,
            (
                SELECT COUNT(*) FROM pos_invoice_lines l WHERE l.invoice_id = i.id
            ) AS item_count
        FROM pos_invoices i
        WHERE {where}
        ORDER BY i.order_date DESC, i.saved_at DESC, i.id DESC
        """,
        params,
    ).fetchall()
    return [_pos_invoice_row_to_dict(conn, row, include_lines=False) for row in rows]


def list_pos_today_invoices(conn, *, today=None):
    """Active POS invoices for the business day — Tables Invoice hub.

    Includes dine-in and other order types created today (open and closed).
    Newest first via list_pos_invoices ordering (saved_at / id).
    """
    if today is None:
        today = datetime.now().strftime("%Y-%m-%d")
    else:
        today = str(today)
    invoices = list_pos_invoices(conn, date_from=today, date_to=today)
    return {
        "date": today,
        "invoice_count": len(invoices),
        "invoices": invoices,
    }


def pos_invoice_kpis(conn, invoices, *, today=None):
    """Compute ledger KPIs from an already-filtered invoice list."""
    ensure_pos_schema(conn)
    if today is None:
        today = datetime.now().strftime("%Y-%m-%d")
    else:
        today = str(today)
    total_sales = 0.0
    today_sales = 0.0
    today_count = 0
    for inv in invoices or []:
        amount = _pos_money(inv.get("grand_total"))
        total_sales += amount
        if str(inv.get("order_date") or "") == today:
            today_sales += amount
            today_count += 1
    count = len(invoices or [])
    average = (total_sales / count) if count else 0.0
    return {
        "total_sales": _pos_money(total_sales),
        "invoice_count": count,
        "average_bill": _pos_money(average),
        "today_sales": _pos_money(today_sales),
        "today_count": today_count,
    }


def _migrate_suppliers_optional_gst(cursor):
    """Allow blank GST on multiple suppliers; keep uniqueness only when GST is set."""
    row = cursor.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='suppliers'"
    ).fetchone()
    if not row:
        return
    compact = " ".join((row["sql"] or "").split()).upper()
    if "GST TEXT NOT NULL UNIQUE" not in compact:
        return

    cursor.execute("""
        CREATE TABLE suppliers__gst_optional (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            name                TEXT    NOT NULL,
            gst                 TEXT    NOT NULL DEFAULT '',
            address             TEXT    NOT NULL DEFAULT '',
            phone               TEXT    NOT NULL DEFAULT '',
            bank_name           TEXT    NOT NULL DEFAULT '',
            bank_account_number TEXT    NOT NULL DEFAULT '',
            ifsc_code           TEXT    NOT NULL DEFAULT '',
            created_at          TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at          TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        )
    """)
    cursor.execute("""
        INSERT INTO suppliers__gst_optional
            (id, name, gst, address, phone, bank_name, bank_account_number, ifsc_code, created_at, updated_at)
        SELECT id, name, COALESCE(gst, ''), address, phone, bank_name, bank_account_number, ifsc_code,
               created_at, updated_at
        FROM suppliers
    """)
    cursor.execute("DROP TABLE suppliers")
    cursor.execute("ALTER TABLE suppliers__gst_optional RENAME TO suppliers")


def ensure_cash_ledger_schema(conn):
    """Create cash ledger load/transfer tables if missing (e.g. after DB restore)."""
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cash_ledger_loads (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            company     TEXT    NOT NULL,
            load_date   TEXT    NOT NULL,
            description TEXT    NOT NULL DEFAULT '',
            amount      REAL    NOT NULL DEFAULT 0,
            created_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_cash_ledger_loads_scope
        ON cash_ledger_loads(company, load_date)
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cash_ledger_transfers (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            company       TEXT    NOT NULL,
            transfer_date TEXT    NOT NULL,
            destination   TEXT    NOT NULL DEFAULT 'bank',
            description   TEXT    NOT NULL DEFAULT '',
            amount        REAL    NOT NULL DEFAULT 0,
            created_at    TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at    TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_cash_ledger_transfers_scope
        ON cash_ledger_transfers(company, transfer_date)
    """)
    conn.commit()


def ensure_stores_schema(conn):
    """Create Stores inventory workflow tables if missing."""
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS store_indents (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            outlet        TEXT    NOT NULL,
            indent_no     TEXT    NOT NULL UNIQUE,
            status        TEXT    NOT NULL DEFAULT 'draft',
            notes         TEXT    NOT NULL DEFAULT '',
            created_by    INTEGER,
            created_at    TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            submitted_at  TEXT,
            decided_by    INTEGER,
            decided_at    TEXT,
            decision_note TEXT    NOT NULL DEFAULT '',
            FOREIGN KEY (created_by) REFERENCES users(id),
            FOREIGN KEY (decided_by) REFERENCES users(id)
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_store_indents_outlet_status
        ON store_indents(outlet, status, created_at DESC)
    """)
    indent_cols = {
        row[1] for row in cursor.execute("PRAGMA table_info(store_indents)").fetchall()
    }
    if "submission_token" not in indent_cols:
        cursor.execute(
            "ALTER TABLE store_indents ADD COLUMN submission_token TEXT NOT NULL DEFAULT ''"
        )
    cursor.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_store_indents_submission_token
        ON store_indents(submission_token) WHERE submission_token != ''
    """)
    # Refresh columns after possible ALTER above.
    indent_cols = {
        row[1] for row in cursor.execute("PRAGMA table_info(store_indents)").fetchall()
    }
    if "approval_token" not in indent_cols:
        cursor.execute(
            "ALTER TABLE store_indents ADD COLUMN approval_token TEXT NOT NULL DEFAULT ''"
        )
    if "wa_decided_by" not in indent_cols:
        cursor.execute(
            "ALTER TABLE store_indents ADD COLUMN wa_decided_by TEXT NOT NULL DEFAULT ''"
        )
    if "wa_decision_message_id" not in indent_cols:
        cursor.execute(
            "ALTER TABLE store_indents ADD COLUMN wa_decision_message_id TEXT NOT NULL DEFAULT ''"
        )
    if "wa_template_message_id" not in indent_cols:
        cursor.execute(
            "ALTER TABLE store_indents ADD COLUMN wa_template_message_id TEXT NOT NULL DEFAULT ''"
        )
    if "wa_interactive_message_id" not in indent_cols:
        cursor.execute(
            "ALTER TABLE store_indents ADD COLUMN wa_interactive_message_id TEXT NOT NULL DEFAULT ''"
        )
    if "wa_notify_lock" not in indent_cols:
        cursor.execute(
            "ALTER TABLE store_indents ADD COLUMN wa_notify_lock INTEGER NOT NULL DEFAULT 0"
        )
    if "wa_notify_lock_at" not in indent_cols:
        cursor.execute(
            "ALTER TABLE store_indents ADD COLUMN wa_notify_lock_at TEXT NOT NULL DEFAULT ''"
        )
    cursor.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_store_indents_approval_token
        ON store_indents(approval_token) WHERE approval_token != ''
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS store_indent_lines (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            indent_id          INTEGER NOT NULL,
            item_name          TEXT    NOT NULL,
            quantity           REAL    NOT NULL DEFAULT 0,
            quantity_received  REAL    NOT NULL DEFAULT 0,
            unit               TEXT    NOT NULL DEFAULT 'pcs',
            notes              TEXT    NOT NULL DEFAULT '',
            approximate_price  REAL,
            FOREIGN KEY (indent_id) REFERENCES store_indents(id) ON DELETE CASCADE
        )
    """)
    indent_line_cols = {
        row[1] for row in cursor.execute("PRAGMA table_info(store_indent_lines)").fetchall()
    }
    if "approximate_price" not in indent_line_cols:
        cursor.execute(
            "ALTER TABLE store_indent_lines ADD COLUMN approximate_price REAL"
        )
    if "quantity_received" not in indent_line_cols:
        cursor.execute(
            "ALTER TABLE store_indent_lines ADD COLUMN quantity_received REAL NOT NULL DEFAULT 0"
        )
        # Backfill from stock movements for partially received indents wrongly closed as stocked.
        cursor.execute(
            """
            UPDATE store_indent_lines
            SET quantity_received = COALESCE((
                SELECT SUM(m.qty_delta)
                FROM store_stock_movements m
                WHERE m.ref_type = 'stock_inward'
                  AND m.ref_id = store_indent_lines.indent_id
                  AND m.item_name = store_indent_lines.item_name
                  AND m.movement_type = 'receive'
            ), 0)
            WHERE EXISTS (
                SELECT 1 FROM store_indents i
                WHERE i.id = store_indent_lines.indent_id
                  AND i.status = 'stocked'
            )
            """
        )
        cursor.execute(
            """
            UPDATE store_indents
            SET status = 'approved'
            WHERE status = 'stocked'
              AND EXISTS (
                SELECT 1 FROM store_indent_lines l
                WHERE l.indent_id = store_indents.id
                  AND COALESCE(l.quantity, 0) - COALESCE(l.quantity_received, 0) > 0.0001
              )
            """
        )
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS store_indent_whatsapp_messages (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            indent_id        INTEGER NOT NULL,
            recipient_phone  TEXT    NOT NULL DEFAULT '',
            wa_message_id    TEXT    NOT NULL DEFAULT '',
            template_name    TEXT    NOT NULL DEFAULT '',
            status           TEXT    NOT NULL DEFAULT '',
            error_message    TEXT    NOT NULL DEFAULT '',
            created_at       TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (indent_id) REFERENCES store_indents(id) ON DELETE CASCADE
        )
    """)
    wa_msg_cols = {
        row[1] for row in cursor.execute("PRAGMA table_info(store_indent_whatsapp_messages)").fetchall()
    }
    if "approval_token" not in wa_msg_cols:
        cursor.execute(
            "ALTER TABLE store_indent_whatsapp_messages "
            "ADD COLUMN approval_token TEXT NOT NULL DEFAULT ''"
        )
    if "send_kind" not in wa_msg_cols:
        cursor.execute(
            "ALTER TABLE store_indent_whatsapp_messages "
            "ADD COLUMN send_kind TEXT NOT NULL DEFAULT ''"
        )
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_store_indent_wa_message
        ON store_indent_whatsapp_messages(wa_message_id)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_store_indent_wa_indent
        ON store_indent_whatsapp_messages(indent_id, created_at DESC)
    """)
    # One attempt per indent approval round + recipient + kind (template|interactive).
    # Superseded rows fall outside the partial index so a new round can notify again.
    cursor.execute("DROP INDEX IF EXISTS idx_store_indent_wa_send_claim")
    cursor.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_store_indent_wa_send_claim
        ON store_indent_whatsapp_messages(
            indent_id, recipient_phone, approval_token, send_kind
        )
        WHERE status IN ('sending', 'sent', 'failed')
          AND approval_token != ''
          AND send_kind != ''
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS store_purchase_requests (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            indent_id   INTEGER,
            outlet      TEXT    NOT NULL,
            pr_no       TEXT    NOT NULL UNIQUE,
            status      TEXT    NOT NULL DEFAULT 'open',
            notes       TEXT    NOT NULL DEFAULT '',
            created_by  INTEGER,
            created_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            received_at TEXT,
            FOREIGN KEY (indent_id) REFERENCES store_indents(id),
            FOREIGN KEY (created_by) REFERENCES users(id)
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_store_prs_outlet_status
        ON store_purchase_requests(outlet, status, created_at DESC)
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS store_purchase_request_lines (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            pr_id   INTEGER NOT NULL,
            item_name TEXT  NOT NULL,
            quantity  REAL  NOT NULL DEFAULT 0,
            unit      TEXT  NOT NULL DEFAULT 'pcs',
            notes     TEXT  NOT NULL DEFAULT '',
            FOREIGN KEY (pr_id) REFERENCES store_purchase_requests(id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS store_stock_items (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            outlet      TEXT    NOT NULL,
            item_name   TEXT    NOT NULL,
            unit        TEXT    NOT NULL DEFAULT 'pcs',
            qty_on_hand REAL    NOT NULL DEFAULT 0,
            updated_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            UNIQUE(outlet, item_name, unit)
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_store_stock_outlet
        ON store_stock_items(outlet, item_name)
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS store_stock_movements (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            outlet        TEXT    NOT NULL,
            item_name     TEXT    NOT NULL,
            unit          TEXT    NOT NULL DEFAULT 'pcs',
            qty_delta     REAL    NOT NULL,
            movement_type TEXT    NOT NULL,
            ref_type      TEXT    NOT NULL DEFAULT '',
            ref_id        INTEGER,
            notes         TEXT    NOT NULL DEFAULT '',
            unit_cost     REAL,
            created_by    INTEGER,
            created_at    TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (created_by) REFERENCES users(id)
        )
    """)
    movement_cols = {
        row[1] for row in cursor.execute("PRAGMA table_info(store_stock_movements)").fetchall()
    }
    if "unit_cost" not in movement_cols:
        cursor.execute("ALTER TABLE store_stock_movements ADD COLUMN unit_cost REAL")
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_store_movements_outlet
        ON store_stock_movements(outlet, created_at DESC)
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS store_product_categories (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT    NOT NULL UNIQUE,
            sort_order INTEGER NOT NULL DEFAULT 0,
            is_active  INTEGER NOT NULL DEFAULT 1,
            created_at TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS store_product_units (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT    NOT NULL UNIQUE COLLATE NOCASE,
            sort_order INTEGER NOT NULL DEFAULT 0,
            is_active  INTEGER NOT NULL DEFAULT 1,
            created_at TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        )
    """)
    _seed_store_product_units(cursor)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS store_products (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            category_id        INTEGER NOT NULL,
            name               TEXT    NOT NULL,
            default_unit       TEXT    NOT NULL DEFAULT 'kg',
            outlet             TEXT    NOT NULL DEFAULT 'restaurant',
            approximate_price  REAL,
            is_active          INTEGER NOT NULL DEFAULT 1,
            sort_order         INTEGER NOT NULL DEFAULT 0,
            created_at         TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at         TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            UNIQUE(category_id, name),
            FOREIGN KEY (category_id) REFERENCES store_product_categories(id)
        )
    """)
    product_cols = {
        row[1] for row in cursor.execute("PRAGMA table_info(store_products)").fetchall()
    }
    if "outlet" not in product_cols:
        cursor.execute(
            "ALTER TABLE store_products ADD COLUMN outlet TEXT NOT NULL DEFAULT 'restaurant'"
        )
    if "approximate_price" not in product_cols:
        cursor.execute(
            "ALTER TABLE store_products ADD COLUMN approximate_price REAL"
        )
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_store_products_category
        ON store_products(category_id, is_active, sort_order, name)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_store_products_outlet
        ON store_products(outlet, is_active, name)
    """)
    _seed_store_product_master(cursor)
    _seed_store_product_units(cursor)  # re-run to sync units from seeded products
    cursor.execute(
        "UPDATE store_products SET default_unit = 'liter' WHERE lower(default_unit) = 'ltr'"
    )
    cursor.execute(
        """
        UPDATE store_products
        SET outlet = 'restaurant'
        WHERE outlet IS NULL OR trim(outlet) = ''
           OR lower(outlet) NOT IN ('bar', 'restaurant', 'both')
        """
    )
    # Migrate legacy "kitchen" outlet key → "restaurant" across stores tables.
    for table in (
        "store_indents",
        "store_purchase_requests",
        "store_stock_items",
        "store_stock_movements",
    ):
        cursor.execute(
            f"UPDATE {table} SET outlet = 'restaurant' WHERE lower(outlet) = 'kitchen'"
        )
    conn.commit()


def _seed_store_product_units(cursor):
    """Seed default product units used on Product Master (idempotent)."""
    defaults = ("kg", "pcs", "liter", "dozen", "bunch", "bottle", "case", "pack")
    for idx, name in enumerate(defaults, start=1):
        cursor.execute(
            """
            INSERT OR IGNORE INTO store_product_units (name, sort_order, is_active)
            VALUES (?, ?, 1)
            """,
            (name, idx * 10),
        )
    # Pull any units already used on products into the master list.
    tables = {
        row[0]
        for row in cursor.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    if "store_products" not in tables:
        return
    for row in cursor.execute(
        """
        SELECT DISTINCT default_unit AS name
        FROM store_products
        WHERE default_unit IS NOT NULL AND trim(default_unit) != ''
        """
    ).fetchall():
        unit_name = str(row["name"] if hasattr(row, "keys") else row[0] or "").strip()
        if not unit_name:
            continue
        cursor.execute(
            """
            INSERT OR IGNORE INTO store_product_units (name, sort_order, is_active)
            VALUES (?, ?, 1)
            """,
            (unit_name, 1000),
        )


def _seed_store_product_master(cursor):
    """Seed Hotel Bell Elite daily perishables catalogue (idempotent)."""
    catalog = (
        (
            "Non-Veg",
            10,
            (
                ("T.D. Chicken", "kg"),
                ("Chicken Whole", "kg"),
                ("Staff Chicken", "kg"),
                ("B/L Chicken", "kg"),
                ("Chi-Drumstick", "kg"),
                ("Chi-Lolly Pop", "kg"),
                ("Mutton", "kg"),
                ("B/L Mutton", "kg"),
                ("Prawns", "kg"),
                ("Lobster", "kg"),
                ("Crabs", "kg"),
                ("B/L Fish", "kg"),
                ("Staff Fish", "kg"),
                ("Eggs", "pcs"),
                ("Bread", "pcs"),
            ),
        ),
        (
            "Dairy Products",
            20,
            (
                ("Fresh Paneer", "kg"),
                ("Butter", "kg"),
                ("Vanilla Ice Cream (1 Ltr)", "liter"),
                ("Butter Scotch (1 Ltr)", "liter"),
                ("Strawberry Ice Cream (1 Ltr)", "liter"),
                ("Chocolate Ice Cream (1 Ltr)", "liter"),
                ("Vanilla Ice Cream (4 Ltr)", "liter"),
                ("Butter Scotch (4 Ltr)", "liter"),
                ("Strawberry Ice Cream (4 Ltr)", "liter"),
                ("Chocolate Ice Cream (4 Ltr)", "liter"),
                ("Apple", "kg"),
                ("Anar", "kg"),
                ("Banana", "dozen"),
                ("Curd", "kg"),
                ("Coffee Powder 200 gm", "pcs"),
                ("Besan Powder 1 Kg", "kg"),
            ),
        ),
        (
            "Vegetable",
            30,
            (
                ("Arbi", "kg"),
                ("Beet Root", "kg"),
                ("Bitter Gourd", "kg"),
                ("Brinjal", "kg"),
                ("Carrot", "kg"),
                ("Cauliflower", "kg"),
                ("Capsicum", "kg"),
                ("Capsicum R/Y", "kg"),
                ("Cabbage", "kg"),
                ("Coconut", "pcs"),
                ("Cucumber", "kg"),
                ("Curry Leaves", "bunch"),
                ("Drum Stick", "kg"),
                ("French Beans", "kg"),
                ("French Fry", "kg"),
                ("Green Chilly", "kg"),
                ("Ginger", "kg"),
                ("Garlic", "kg"),
                ("Kundru", "kg"),
                ("Long Beans", "kg"),
                ("Lemon", "kg"),
                ("Mint Leaves", "bunch"),
                ("Mooli Bhaji", "kg"),
                ("Pumpkin", "kg"),
                ("Mursa Bhaji", "kg"),
                ("Nali Bhaji", "kg"),
                ("Onion", "kg"),
                ("Potato", "kg"),
                ("Palak Bhaji", "kg"),
                ("Poi Bhaji", "kg"),
                ("Potal", "kg"),
                ("Ridge Gourd", "kg"),
                ("Spring Onion", "kg"),
                ("Snake Gourd", "kg"),
                ("Tomato", "kg"),
                ("Thupi", "kg"),
                ("Coriander Leaves", "bunch"),
                ("Raw Banana", "kg"),
                ("Ladies Finger", "kg"),
                ("Staff Veg.", "kg"),
            ),
        ),
    )
    for cat_name, cat_sort, products in catalog:
        cursor.execute(
            """
            INSERT OR IGNORE INTO store_product_categories (name, sort_order, is_active)
            VALUES (?, ?, 1)
            """,
            (cat_name, cat_sort),
        )
        row = cursor.execute(
            "SELECT id FROM store_product_categories WHERE name = ?",
            (cat_name,),
        ).fetchone()
        if not row:
            continue
        category_id = row["id"] if hasattr(row, "keys") else row[0]
        for idx, (product_name, unit) in enumerate(products, start=1):
            cursor.execute(
                """
                INSERT OR IGNORE INTO store_products
                    (category_id, name, default_unit, outlet, is_active, sort_order)
                VALUES (?, ?, ?, 'restaurant', 1, ?)
                """,
                (category_id, product_name, unit, idx * 10),
            )


def init_db():
    conn = get_db()
    conn.execute("PRAGMA journal_mode=WAL")
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            username        TEXT    NOT NULL UNIQUE,
            full_name       TEXT    NOT NULL DEFAULT '',
            password_hash   TEXT    NOT NULL,
            is_admin        INTEGER NOT NULL DEFAULT 0,
            is_active       INTEGER NOT NULL DEFAULT 1,
            created_at      TEXT    NOT NULL,
            updated_at      TEXT    NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_permissions (
            user_id  INTEGER NOT NULL,
            scope    TEXT    NOT NULL,
            item_key TEXT    NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sales_updates (
            id                      INTEGER PRIMARY KEY AUTOINCREMENT,
            company                 TEXT    NOT NULL,
            location                TEXT    NOT NULL,
            sales_date              TEXT    NOT NULL,
            sales_entry_values      TEXT    NOT NULL DEFAULT '{}',
            sales_entry_total       REAL    NOT NULL DEFAULT 0,
            petty_cash_counts       TEXT    NOT NULL DEFAULT '{}',
            petty_cash_total        REAL    NOT NULL DEFAULT 0,
            cash_denomination_counts TEXT   NOT NULL DEFAULT '{}',
            created_by_user_id      INTEGER,
            updated_by_user_id      INTEGER,
            created_at              TEXT    NOT NULL,
            updated_at              TEXT    NOT NULL,
            UNIQUE(company, location, sales_date)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sales_update_expenses (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            company         TEXT    NOT NULL,
            location        TEXT    NOT NULL,
            sales_date      TEXT    NOT NULL,
            description     TEXT    NOT NULL DEFAULT '',
            amount          REAL    NOT NULL DEFAULT 0,
            payment_type    TEXT    NOT NULL DEFAULT 'cash',
            transaction_id  TEXT    NOT NULL DEFAULT '',
            expense_code    TEXT    NOT NULL DEFAULT '',
            created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        )
    """)
    existing_expense_cols = {
        row["name"] for row in cursor.execute("PRAGMA table_info(sales_update_expenses)").fetchall()
    }
    if "payment_type" not in existing_expense_cols:
        cursor.execute("ALTER TABLE sales_update_expenses ADD COLUMN payment_type TEXT NOT NULL DEFAULT 'cash'")
    if "transaction_id" not in existing_expense_cols:
        cursor.execute("ALTER TABLE sales_update_expenses ADD COLUMN transaction_id TEXT NOT NULL DEFAULT ''")
    if "supplier_id" not in existing_expense_cols:
        cursor.execute("ALTER TABLE sales_update_expenses ADD COLUMN supplier_id INTEGER")
    if "category" not in existing_expense_cols:
        cursor.execute("ALTER TABLE sales_update_expenses ADD COLUMN category TEXT NOT NULL DEFAULT ''")
    if "expense_code" not in existing_expense_cols:
        cursor.execute("ALTER TABLE sales_update_expenses ADD COLUMN expense_code TEXT NOT NULL DEFAULT ''")
        rows = cursor.execute(
            """SELECT id, company FROM sales_update_expenses
               WHERE expense_code IS NULL OR expense_code = ''
               ORDER BY id"""
        ).fetchall()
        company_counters = {}
        for row in rows:
            company = (row["company"] or "HBE").strip() or "HBE"
            company_counters[company] = company_counters.get(company, 0) + 1
            code = f"{company}-EX-{company_counters[company]}"
            cursor.execute(
                "UPDATE sales_update_expenses SET expense_code = ? WHERE id = ?",
                (code, row["id"]),
            )
    if "invoice_number" not in existing_expense_cols:
        cursor.execute("ALTER TABLE sales_update_expenses ADD COLUMN invoice_number TEXT NOT NULL DEFAULT ''")
    cursor.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_sales_update_expenses_code
        ON sales_update_expenses(expense_code)
        WHERE expense_code != ''
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS expense_categories (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            category_key  TEXT    NOT NULL UNIQUE,
            name          TEXT    NOT NULL COLLATE NOCASE,
            sort_order    INTEGER NOT NULL DEFAULT 0,
            is_active     INTEGER NOT NULL DEFAULT 1,
            created_at    TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        )
    """)
    cursor.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_expense_categories_name
        ON expense_categories(lower(name))
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS suppliers (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            name                TEXT    NOT NULL,
            gst                 TEXT    NOT NULL DEFAULT '',
            address             TEXT    NOT NULL DEFAULT '',
            phone               TEXT    NOT NULL DEFAULT '',
            bank_name           TEXT    NOT NULL DEFAULT '',
            bank_account_number TEXT    NOT NULL DEFAULT '',
            ifsc_code           TEXT    NOT NULL DEFAULT '',
            created_at          TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at          TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        )
    """)
    _migrate_suppliers_optional_gst(cursor)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_suppliers_name
        ON suppliers(LOWER(name))
    """)
    cursor.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_suppliers_gst_unique
        ON suppliers(gst) WHERE gst != ''
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sales_update_cash_transfers (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            company     TEXT    NOT NULL,
            location    TEXT    NOT NULL,
            sales_date  TEXT    NOT NULL,
            destination TEXT    NOT NULL DEFAULT 'bank',
            description TEXT    NOT NULL DEFAULT '',
            amount      REAL    NOT NULL DEFAULT 0,
            created_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sales_update_pending_bills (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            company              TEXT    NOT NULL,
            location             TEXT    NOT NULL,
            recorded_sales_date  TEXT    NOT NULL,
            invoice_number       TEXT    NOT NULL DEFAULT '',
            amount               REAL    NOT NULL DEFAULT 0,
            status               TEXT    NOT NULL DEFAULT 'open',
            cleared_sales_date   TEXT,
            created_at           TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at           TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sales_update_bill_payments (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            company         TEXT    NOT NULL,
            location        TEXT    NOT NULL,
            sales_date      TEXT    NOT NULL,
            pending_bill_id INTEGER NOT NULL,
            amount          REAL    NOT NULL DEFAULT 0,
            created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        )
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_sales_updates_scope_date
        ON sales_updates(company, location, sales_date)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_sales_update_expenses_scope
        ON sales_update_expenses(company, location, sales_date)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_sales_update_cash_transfers_scope
        ON sales_update_cash_transfers(company, location, sales_date)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_sales_update_pending_bills_scope
        ON sales_update_pending_bills(company, location, status, recorded_sales_date)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_sales_update_bill_payments_scope
        ON sales_update_bill_payments(company, location, sales_date)
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS credit_payments (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            company         TEXT    NOT NULL,
            supplier_id     INTEGER NOT NULL,
            payment_date    TEXT    NOT NULL,
            payment_method  TEXT    NOT NULL DEFAULT 'cash',
            transaction_id  TEXT    NOT NULL DEFAULT '',
            total_amount    REAL    NOT NULL DEFAULT 0,
            notes           TEXT    NOT NULL DEFAULT '',
            created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS credit_payment_allocations (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            credit_payment_id   INTEGER NOT NULL,
            expense_id          INTEGER NOT NULL,
            amount              REAL    NOT NULL DEFAULT 0,
            created_at          TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_credit_payments_scope
        ON credit_payments(company, supplier_id, payment_date)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_credit_payment_allocations_payment
        ON credit_payment_allocations(credit_payment_id)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_credit_payment_allocations_expense
        ON credit_payment_allocations(expense_id)
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS purchase_verifications (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            company             TEXT    NOT NULL,
            supplier_id         INTEGER NOT NULL,
            verification_date   TEXT    NOT NULL,
            verification_method TEXT    NOT NULL DEFAULT 'cash',
            verification_account TEXT   NOT NULL DEFAULT '',
            transaction_id      TEXT    NOT NULL DEFAULT '',
            total_amount        REAL    NOT NULL DEFAULT 0,
            notes               TEXT    NOT NULL DEFAULT '',
            created_at          TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at          TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS purchase_verification_allocations (
            id                      INTEGER PRIMARY KEY AUTOINCREMENT,
            purchase_verification_id INTEGER NOT NULL,
            expense_id              INTEGER NOT NULL,
            amount                  REAL    NOT NULL DEFAULT 0,
            created_at              TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_purchase_verifications_scope
        ON purchase_verifications(company, supplier_id, verification_date)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_purchase_verification_allocations_verification
        ON purchase_verification_allocations(purchase_verification_id)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_purchase_verification_allocations_expense
        ON purchase_verification_allocations(expense_id)
    """)
    ensure_cash_ledger_schema(conn)
    ensure_stores_schema(conn)
    ensure_pos_schema(conn)

    existing_pv_cols = {
        row["name"] for row in cursor.execute("PRAGMA table_info(purchase_verifications)").fetchall()
    }
    if "verification_account" not in existing_pv_cols:
        cursor.execute(
            "ALTER TABLE purchase_verifications ADD COLUMN verification_account TEXT NOT NULL DEFAULT ''"
        )

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS hotel_sales_ledger_entries (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            company         TEXT    NOT NULL,
            location        TEXT    NOT NULL,
            sales_date      TEXT    NOT NULL,
            invoice_number  TEXT    NOT NULL DEFAULT '',
            room            TEXT    NOT NULL DEFAULT '',
            room_type       TEXT    NOT NULL DEFAULT '',
            reserve_number  TEXT    NOT NULL DEFAULT '',
            guest_name      TEXT    NOT NULL DEFAULT '',
            company_name    TEXT    NOT NULL DEFAULT '',
            travel_agent    TEXT    NOT NULL DEFAULT '',
            pax             TEXT    NOT NULL DEFAULT '',
            room_plan       TEXT    NOT NULL DEFAULT '',
            tariff          REAL    NOT NULL DEFAULT 0,
            discount        REAL    NOT NULL DEFAULT 0,
            extra_amount    REAL    NOT NULL DEFAULT 0,
            amount          REAL    NOT NULL DEFAULT 0,
            payment_mode    TEXT    NOT NULL DEFAULT '',
            sort_order      INTEGER NOT NULL DEFAULT 0,
            source_row      INTEGER,
            created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_hotel_sales_ledger_scope
        ON hotel_sales_ledger_entries(company, location, sales_date, sort_order)
    """)
    existing_hotel_cols = {
        row["name"] for row in cursor.execute("PRAGMA table_info(hotel_sales_ledger_entries)").fetchall()
    }
    if "invoice_number" not in existing_hotel_cols:
        cursor.execute("ALTER TABLE hotel_sales_ledger_entries ADD COLUMN invoice_number TEXT NOT NULL DEFAULT ''")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS room_transfer_entries (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            company         TEXT    NOT NULL,
            location        TEXT    NOT NULL,
            sales_date      TEXT    NOT NULL,
            invoice_number  TEXT    NOT NULL DEFAULT '',
            outlet_name     TEXT    NOT NULL DEFAULT '',
            table_room      TEXT    NOT NULL DEFAULT '',
            guest_name      TEXT    NOT NULL DEFAULT '',
            ledger_detail   TEXT    NOT NULL DEFAULT '',
            amount          REAL    NOT NULL DEFAULT 0,
            payment_status  TEXT    NOT NULL DEFAULT 'unpaid',
            sort_order      INTEGER NOT NULL DEFAULT 0,
            source_row      INTEGER,
            created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_room_transfer_scope
        ON room_transfer_entries(company, sales_date, location, sort_order)
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS room_transfer_payments (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            company         TEXT    NOT NULL,
            payment_date    TEXT    NOT NULL,
            payment_method  TEXT    NOT NULL DEFAULT 'cash',
            transaction_id  TEXT    NOT NULL DEFAULT '',
            total_amount    REAL    NOT NULL DEFAULT 0,
            notes           TEXT    NOT NULL DEFAULT '',
            created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS room_transfer_payment_allocations (
            id                       INTEGER PRIMARY KEY AUTOINCREMENT,
            room_transfer_payment_id INTEGER NOT NULL,
            room_transfer_entry_id   INTEGER NOT NULL,
            amount                   REAL    NOT NULL DEFAULT 0,
            invoice_number           TEXT    NOT NULL DEFAULT '',
            guest_name               TEXT    NOT NULL DEFAULT '',
            location                 TEXT    NOT NULL DEFAULT '',
            sales_date               TEXT    NOT NULL DEFAULT '',
            created_at               TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_room_transfer_payments_scope
        ON room_transfer_payments(company, payment_date)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_room_transfer_payment_allocations_payment
        ON room_transfer_payment_allocations(room_transfer_payment_id)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_room_transfer_payment_allocations_entry
        ON room_transfer_payment_allocations(room_transfer_entry_id)
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS employees (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            emp_code     TEXT    NOT NULL DEFAULT '',
            name         TEXT    NOT NULL,
            company      TEXT    NOT NULL DEFAULT '',
            location     TEXT    NOT NULL DEFAULT '',
            mobile           TEXT    NOT NULL DEFAULT '',
            guardian_mobile  TEXT    NOT NULL DEFAULT '',
            sex          TEXT    NOT NULL DEFAULT '',
            address      TEXT    NOT NULL DEFAULT '',
            aadhar       TEXT    NOT NULL DEFAULT '',
            pan          TEXT    NOT NULL DEFAULT '',
            epf_number   TEXT    NOT NULL DEFAULT '',
            esic_number  TEXT    NOT NULL DEFAULT '',
            gross_salary REAL    NOT NULL DEFAULT 0,
            basic_salary REAL    NOT NULL DEFAULT 0,
            epf_amount   REAL    NOT NULL DEFAULT 0,
            esic_amount  REAL    NOT NULL DEFAULT 0,
            credit_repayment REAL    NOT NULL DEFAULT 0,
            epf_exempt   INTEGER NOT NULL DEFAULT 0,
            esic_exempt  INTEGER NOT NULL DEFAULT 0,
            weekday_shift TEXT    NOT NULL DEFAULT '',
            sunday_shift  TEXT    NOT NULL DEFAULT '',
            bank_name         TEXT    NOT NULL DEFAULT '',
            account_holder_name TEXT  NOT NULL DEFAULT '',
            account_number    TEXT    NOT NULL DEFAULT '',
            ifsc_code         TEXT    NOT NULL DEFAULT '',
            total_off         INTEGER NOT NULL DEFAULT 0,
            status       TEXT    NOT NULL DEFAULT 'active',
            created_at   TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at   TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS attendance (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL,
            date        TEXT    NOT NULL,
            status      TEXT    NOT NULL DEFAULT 'present',
            created_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE CASCADE,
            UNIQUE(employee_id, date)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS credits (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL,
            date        TEXT    NOT NULL,
            description TEXT    NOT NULL DEFAULT '',
            amount      REAL    NOT NULL DEFAULT 0,
            entry_type  TEXT    NOT NULL DEFAULT 'manual',
            payroll_year INTEGER,
            payroll_month INTEGER,
            expense_id  INTEGER,
            created_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE CASCADE
        )
    """)
    existing_credit_cols = {
        row["name"] for row in cursor.execute("PRAGMA table_info(credits)").fetchall()
    }
    if "expense_id" not in existing_credit_cols:
        cursor.execute("ALTER TABLE credits ADD COLUMN expense_id INTEGER")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sales_update_tips (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            company      TEXT    NOT NULL,
            location     TEXT    NOT NULL,
            sales_date   TEXT    NOT NULL,
            employee_id  INTEGER NOT NULL,
            amount       REAL    NOT NULL DEFAULT 0,
            description  TEXT    NOT NULL DEFAULT '',
            created_at   TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at   TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_sales_update_tips_scope
        ON sales_update_tips(company, location, sales_date)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_sales_update_tips_employee
        ON sales_update_tips(employee_id, sales_date)
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tip_incentive_payouts (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            company      TEXT    NOT NULL,
            year         INTEGER NOT NULL,
            month        INTEGER NOT NULL,
            employee_id  INTEGER NOT NULL,
            amount       REAL    NOT NULL DEFAULT 0,
            updated_at   TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            UNIQUE(company, year, month, employee_id),
            FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_tip_incentive_payouts_period
        ON tip_incentive_payouts(company, year, month)
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS payroll_month_locks (
            year      INTEGER NOT NULL,
            month     INTEGER NOT NULL,
            locked_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            PRIMARY KEY (year, month)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS companies (
            id   INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS locations (
            id   INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_att_emp_date ON attendance(employee_id, date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_credits_emp ON credits(employee_id)")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_credits_emp_period "
        "ON credits(employee_id, entry_type, payroll_year, payroll_month)"
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_emp_status ON employees(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_emp_company ON employees(company)")
    cursor.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_emp_code_unique "
        "ON employees(emp_code) WHERE emp_code <> ''"
    )
    existing_employee_cols = {
        row["name"] for row in cursor.execute("PRAGMA table_info(employees)").fetchall()
    }
    if "total_off" not in existing_employee_cols:
        cursor.execute("ALTER TABLE employees ADD COLUMN total_off INTEGER NOT NULL DEFAULT 0")
    for company_name in ("Hotel Bell Elite", "HBE"):
        cursor.execute(
            "INSERT OR IGNORE INTO companies (name) VALUES (?)",
            (company_name,),
        )
    payroll_departments = (
        "OM",
        "FO",
        "F&B",
        "KITCHEN",
        "UTILITY",
        "BAR",
        "HK",
        "MAINTENANCE",
        "SECURITY",
    )
    for location_name in payroll_departments:
        cursor.execute(
            "INSERT OR IGNORE INTO locations (name) VALUES (?)",
            (location_name,),
        )

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    row = cursor.execute("SELECT id FROM users WHERE username = ?", ("admin",)).fetchone()
    if not row:
        cursor.execute(
            """INSERT INTO users (username, full_name, password_hash, is_admin, is_active, created_at, updated_at)
               VALUES (?, ?, ?, 1, 1, ?, ?)""",
            ("admin", "Administrator", generate_password_hash("admin"), now, now),
        )

    conn.commit()
    conn.close()
