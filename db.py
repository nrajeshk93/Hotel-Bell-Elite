import json
import os
import re
import sqlite3
from datetime import date, datetime, timedelta

import auth_security

DATABASE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bell_elite.db")
SQL_NOW = "datetime('now','localtime')"

_POS_LIQUOR_CATEGORY_RE = re.compile(
    r"\b(liquou?r|alcohol|whisky|whiskey|beer|wine|vodka|gin|rum|brandy|"
    r"spirit|spirits|imfl|cocktail|cocktails|shots?|scotch|tequila|"
    r"champagne|cider|liqueur|aperitif)\b",
    re.IGNORECASE,
)


def is_pos_liquor_category(name):
    """True when a POS menu category is treated as liquor (VAT 10%)."""
    return bool(_POS_LIQUOR_CATEGORY_RE.search(str(name or "").strip()))


def get_db():
    conn = sqlite3.connect(DATABASE_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# POS workspace outlets (path/nav keys). Distinct from Sales Update OUTLET_* labels.
POS_OUTLET_RESTAURANT = "restaurant"
POS_OUTLET_BAR = "bar"
POS_OUTLETS = (POS_OUTLET_RESTAURANT, POS_OUTLET_BAR)


def normalize_pos_outlet(value):
    """Return restaurant|bar; unknown/empty → restaurant."""
    key = str(value or "").strip().lower()
    if key in ("bar",):
        return POS_OUTLET_BAR
    return POS_OUTLET_RESTAURANT


_SPC_FY_ORDER_RE = re.compile(r"^SPC/(\d+)/(\d{4}-\d{2})$", re.IGNORECASE)
_SPC_LEGACY_ORDER_RE = re.compile(r"^SPC/(\d+)$", re.IGNORECASE)
_INV_FY_ORDER_RE = re.compile(r"^INV/(\d+)/(\d{4}-\d{2})$", re.IGNORECASE)
_INV_LEGACY_ORDER_RE = re.compile(r"^INV/(\d+)$", re.IGNORECASE)


def indian_fiscal_year_label(value=None):
    """Indian FY label (Apr–Mar), e.g. 2026-07-29 → '2026-27'."""
    if value is None:
        d = datetime.now().date()
    elif isinstance(value, datetime):
        d = value.date()
    elif hasattr(value, "year") and hasattr(value, "month") and not isinstance(value, str):
        d = value
    else:
        text = str(value or "").strip()
        if len(text) >= 10 and text[4] == "-" and text[7] == "-":
            try:
                d = datetime.strptime(text[:10], "%Y-%m-%d").date()
            except ValueError:
                d = datetime.now().date()
        else:
            d = datetime.now().date()
    if d.month >= 4:
        start_year = d.year
    else:
        start_year = d.year - 1
    return f"{start_year}-{str(start_year + 1)[-2:]}"


def is_restaurant_spc_order_no(order_no, fiscal_year=None):
    """True when order_no is SPC/{n}/{fy} (optionally matching a specific FY)."""
    match = _SPC_FY_ORDER_RE.match(str(order_no or "").strip())
    if not match:
        return False
    if fiscal_year and match.group(2) != str(fiscal_year):
        return False
    return True


def is_bar_inv_order_no(order_no, fiscal_year=None):
    """True when order_no is INV/{n}/{fy} (optionally matching a specific FY)."""
    match = _INV_FY_ORDER_RE.match(str(order_no or "").strip())
    if not match:
        return False
    if fiscal_year and match.group(2) != str(fiscal_year):
        return False
    return True


def is_provisional_pos_order_no(order_no, outlet=None):
    """Client placeholders that should be replaced on first outlet save."""
    text = str(order_no or "").strip()
    if not text:
        return True
    outlet_key = normalize_pos_outlet(outlet) if outlet is not None else None
    upper = text.upper()
    # Offline-local drafts (ORD-L-…) become SPC|INV/{n}/{fy} on first sync.
    if upper.startswith("ORD-L-"):
        return True
    # Offline drafts: PREFIX/{hex}/{fy}; numeric PREFIX/{n}/{fy} is final.
    if upper.startswith("SPC/") and not is_restaurant_spc_order_no(text):
        if outlet_key in (None, POS_OUTLET_RESTAURANT):
            return bool(re.match(r"^SPC/[^/]+/\d{4}-\d{2}$", text, re.IGNORECASE))
    if upper.startswith("INV/") and not is_bar_inv_order_no(text):
        if outlet_key in (None, POS_OUTLET_BAR):
            return bool(re.match(r"^INV/[^/]+/\d{4}-\d{2}$", text, re.IGNORECASE))
    return False


def _next_prefixed_invoice_seq(conn, outlet, prefix, fy_re, legacy_re, fiscal_year):
    """Next numeric sequence for PREFIX/{n}/{fy} within an outlet + FY."""
    fy = str(fiscal_year or "").strip()
    prefix = str(prefix or "").strip().upper()
    max_n = 0
    rows = conn.execute(
        """
        SELECT order_no, order_date
        FROM pos_invoices
        WHERE outlet = ?
          AND upper(order_no) LIKE ?
        """,
        (normalize_pos_outlet(outlet), f"{prefix}/%"),
    ).fetchall()
    for row in rows:
        order_no = str(row["order_no"] or "").strip()
        match = fy_re.match(order_no)
        if match and match.group(2) == fy:
            max_n = max(max_n, int(match.group(1)))
            continue
        legacy = legacy_re.match(order_no)
        if legacy:
            try:
                row_fy = indian_fiscal_year_label(row["order_date"] if "order_date" in row.keys() else None)
            except Exception:
                row_fy = ""
            if row_fy == fy:
                max_n = max(max_n, int(legacy.group(1)))
    return max_n + 1


def next_restaurant_invoice_seq(conn, fiscal_year):
    """Next SPC sequence for Restaurant within the given FY."""
    return _next_prefixed_invoice_seq(
        conn,
        POS_OUTLET_RESTAURANT,
        "SPC",
        _SPC_FY_ORDER_RE,
        _SPC_LEGACY_ORDER_RE,
        fiscal_year,
    )


def next_bar_invoice_seq(conn, fiscal_year):
    """Next INV sequence for Bar within the given FY."""
    return _next_prefixed_invoice_seq(
        conn,
        POS_OUTLET_BAR,
        "INV",
        _INV_FY_ORDER_RE,
        _INV_LEGACY_ORDER_RE,
        fiscal_year,
    )


def allocate_pos_restaurant_order_no(conn, order_date=None):
    """Allocate SPC/{n}/{fy} for a new Restaurant invoice."""
    fy = indian_fiscal_year_label(order_date)
    seq = next_restaurant_invoice_seq(conn, fy)
    return f"SPC/{seq}/{fy}"


def allocate_pos_bar_order_no(conn, order_date=None):
    """Allocate INV/{n}/{fy} for a new Bar invoice."""
    fy = indian_fiscal_year_label(order_date)
    seq = next_bar_invoice_seq(conn, fy)
    return f"INV/{seq}/{fy}"


def resolve_pos_outlets(outlet=None, outlets=None):
    """Return a unique tuple of restaurant|bar outlets for list queries."""
    if outlets is not None:
        if isinstance(outlets, (str, bytes)):
            raw = [outlets]
        else:
            try:
                raw = list(outlets)
            except TypeError:
                raw = [outlets]
        resolved = []
        seen = set()
        for value in raw:
            key = normalize_pos_outlet(value)
            if key in seen:
                continue
            seen.add(key)
            resolved.append(key)
        if resolved:
            return tuple(resolved)
    return (normalize_pos_outlet(outlet),)


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
        merge_group_id = str(raw.get("mergeGroupId") or "").strip() or None
        merge_primary = bool(raw.get("mergePrimary")) if merge_group_id else False
        clean_tables.append(
            {
                "id": table_id,
                "type": "table",
                "name": str(raw.get("name") or "").strip() or table_id,
                "seats": seats,
                "shape": shape,
                "status": status,
                "areaId": area_id,
                "mergeGroupId": merge_group_id,
                "mergePrimary": merge_primary,
            }
        )
    return {"areas": clean_areas, "tables": clean_tables}


def default_bar_pos_floor_payload():
    """Bar Tables 1–16 (4 seats) + Counter Chairs 1–6 (1 seat) from venue sheet."""
    areas = [
        {"id": "bar_tables", "type": "area", "name": "Tables"},
        {"id": "bar_counter", "type": "area", "name": "Counter"},
    ]
    tables = []
    for i in range(1, 17):
        tables.append(
            {
                "id": f"bar_t{i}",
                "type": "table",
                "name": f"Table {i}",
                "seats": 4,
                "shape": "square",
                "status": "available",
                "areaId": "bar_tables",
                "mergeGroupId": None,
                "mergePrimary": False,
            }
        )
    for i in range(1, 7):
        tables.append(
            {
                "id": f"bar_c{i}",
                "type": "table",
                "name": f"Chair {i}",
                "seats": 1,
                "shape": "square",
                "status": "available",
                "areaId": "bar_counter",
                "mergeGroupId": None,
                "mergePrimary": False,
            }
        )
    return _normalize_pos_floor_payload(areas, tables)


def ensure_pos_schema(conn):
    """Create lean POS floor, settings, and menu tables (soft migration)."""
    cursor = conn.cursor()
    # --- Floor layout: migrate singleton id=1 → outlet-keyed rows ---
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='pos_floor_layout'"
    )
    if not cursor.fetchone():
        cursor.execute(
            """
            CREATE TABLE pos_floor_layout (
                outlet     TEXT    NOT NULL PRIMARY KEY,
                payload    TEXT    NOT NULL,
                updated_at TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
            )
            """
        )
    else:
        floor_cols = {
            row[1] for row in cursor.execute("PRAGMA table_info(pos_floor_layout)").fetchall()
        }
        if "outlet" not in floor_cols:
            cursor.execute("ALTER TABLE pos_floor_layout RENAME TO pos_floor_layout_legacy")
            cursor.execute(
                """
                CREATE TABLE pos_floor_layout (
                    outlet     TEXT    NOT NULL PRIMARY KEY,
                    payload    TEXT    NOT NULL,
                    updated_at TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
                )
                """
            )
            cursor.execute(
                """
                INSERT INTO pos_floor_layout (outlet, payload, updated_at)
                SELECT ?, payload, COALESCE(NULLIF(updated_at, ''), datetime('now','localtime'))
                FROM pos_floor_layout_legacy
                """,
                (POS_OUTLET_RESTAURANT,),
            )
            cursor.execute("DROP TABLE pos_floor_layout_legacy")

    # --- Settings: same outlet migration ---
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='pos_restaurant_settings'"
    )
    if not cursor.fetchone():
        cursor.execute(
            """
            CREATE TABLE pos_restaurant_settings (
                outlet     TEXT    NOT NULL PRIMARY KEY,
                payload    TEXT    NOT NULL DEFAULT '{}',
                updated_at TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
            )
            """
        )
    else:
        settings_cols = {
            row[1]
            for row in cursor.execute("PRAGMA table_info(pos_restaurant_settings)").fetchall()
        }
        if "outlet" not in settings_cols:
            cursor.execute(
                "ALTER TABLE pos_restaurant_settings RENAME TO pos_restaurant_settings_legacy"
            )
            cursor.execute(
                """
                CREATE TABLE pos_restaurant_settings (
                    outlet     TEXT    NOT NULL PRIMARY KEY,
                    payload    TEXT    NOT NULL DEFAULT '{}',
                    updated_at TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
                )
                """
            )
            cursor.execute(
                """
                INSERT INTO pos_restaurant_settings (outlet, payload, updated_at)
                SELECT ?, payload, COALESCE(NULLIF(updated_at, ''), datetime('now','localtime'))
                FROM pos_restaurant_settings_legacy
                """,
                (POS_OUTLET_RESTAURANT,),
            )
            cursor.execute("DROP TABLE pos_restaurant_settings_legacy")

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
        "item_kind": "TEXT NOT NULL DEFAULT 'food'",
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
    # Idempotency marker: stock was reduced once for this closed invoice (POS sale).
    if "stock_deducted_at" not in invoice_cols:
        cursor.execute(
            "ALTER TABLE pos_invoices ADD COLUMN stock_deducted_at TEXT NOT NULL DEFAULT ''"
        )
    if "vat_amount" not in invoice_cols:
        cursor.execute(
            "ALTER TABLE pos_invoices ADD COLUMN vat_amount REAL NOT NULL DEFAULT 0"
        )
    if "discount_line_uids" not in invoice_cols:
        cursor.execute(
            "ALTER TABLE pos_invoices ADD COLUMN discount_line_uids TEXT NOT NULL DEFAULT ''"
        )
    if "discount_reason" not in invoice_cols:
        cursor.execute(
            "ALTER TABLE pos_invoices ADD COLUMN discount_reason TEXT NOT NULL DEFAULT ''"
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
    if "notes" not in line_cols:
        cursor.execute(
            "ALTER TABLE pos_invoice_lines ADD COLUMN notes TEXT NOT NULL DEFAULT ''"
        )
    if "line_uid" not in line_cols:
        cursor.execute(
            "ALTER TABLE pos_invoice_lines ADD COLUMN line_uid TEXT NOT NULL DEFAULT ''"
        )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_pos_invoice_lines_invoice
        ON pos_invoice_lines(invoice_id, sort_order)
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS pos_invoice_payments (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_id      INTEGER NOT NULL,
            payment_date    TEXT    NOT NULL,
            payment_method  TEXT    NOT NULL,
            amount          REAL    NOT NULL DEFAULT 0,
            transaction_id  TEXT    NOT NULL DEFAULT '',
            notes           TEXT    NOT NULL DEFAULT '',
            created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (invoice_id) REFERENCES pos_invoices(id)
        )
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_pos_invoice_payments_invoice
        ON pos_invoice_payments(invoice_id, id)
        """
    )
    invoice_cols = {
        row[1] for row in cursor.execute("PRAGMA table_info(pos_invoices)").fetchall()
    }
    if "payment_notes" not in invoice_cols:
        cursor.execute(
            "ALTER TABLE pos_invoices ADD COLUMN payment_notes TEXT NOT NULL DEFAULT ''"
        )
    if "settled_at" not in invoice_cols:
        cursor.execute(
            "ALTER TABLE pos_invoices ADD COLUMN settled_at TEXT NOT NULL DEFAULT ''"
        )

    # Outlet columns (default restaurant for existing rows)
    cat_cols = {
        row[1] for row in cursor.execute("PRAGMA table_info(pos_menu_categories)").fetchall()
    }
    if "outlet" not in cat_cols:
        cursor.execute(
            "ALTER TABLE pos_menu_categories ADD COLUMN outlet TEXT NOT NULL DEFAULT 'restaurant'"
        )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_pos_menu_categories_outlet
        ON pos_menu_categories(outlet, is_active, sort_order)
        """
    )
    item_cols = {
        row[1] for row in cursor.execute("PRAGMA table_info(pos_menu_items)").fetchall()
    }
    if "outlet" not in item_cols:
        cursor.execute(
            "ALTER TABLE pos_menu_items ADD COLUMN outlet TEXT NOT NULL DEFAULT 'restaurant'"
        )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_pos_menu_items_outlet
        ON pos_menu_items(outlet, category_id, is_active)
        """
    )
    invoice_cols = {
        row[1] for row in cursor.execute("PRAGMA table_info(pos_invoices)").fetchall()
    }
    if "outlet" not in invoice_cols:
        cursor.execute(
            "ALTER TABLE pos_invoices ADD COLUMN outlet TEXT NOT NULL DEFAULT 'restaurant'"
        )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_pos_invoices_outlet_table_open
        ON pos_invoices(outlet, table_label, status, order_type, is_active)
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_pos_invoices_outlet_date
        ON pos_invoices(outlet, order_date, is_active)
        """
    )

    # Seed Bar floor once (never overwrite a saved Bar layout)
    bar_row = cursor.execute(
        "SELECT outlet FROM pos_floor_layout WHERE outlet = ?",
        (POS_OUTLET_BAR,),
    ).fetchone()
    if not bar_row:
        bar_payload = default_bar_pos_floor_payload()
        blob = json.dumps(bar_payload, separators=(",", ":"))
        cursor.execute(
            f"""
            INSERT INTO pos_floor_layout (outlet, payload, updated_at)
            VALUES (?, ?, {SQL_NOW})
            """,
            (POS_OUTLET_BAR, blob),
        )
        cursor.execute(
            f"""
            INSERT OR IGNORE INTO pos_restaurant_settings (outlet, payload, updated_at)
            VALUES (?, '{{}}', {SQL_NOW})
            """,
            (POS_OUTLET_BAR,),
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


def ensure_agencies_schema(conn):
    """Agency Master for hotel travel/corporate agencies."""
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS agencies (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT    NOT NULL DEFAULT '',
            gst         TEXT    NOT NULL DEFAULT '',
            address     TEXT    NOT NULL DEFAULT '',
            created_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        )
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_agencies_name
        ON agencies(LOWER(name))
        """
    )


def _normalize_agency_name(value):
    return " ".join(str(value or "").split()).strip()


def _normalize_agency_gst(value):
    return " ".join(str(value or "").split()).strip().upper()


def _normalize_agency_address(value):
    return " ".join(str(value or "").split()).strip()


def agency_row_to_dict(row):
    if not row:
        return None
    return {
        "id": row["id"],
        "name": row["name"] or "",
        "gst": row["gst"] or "",
        "address": row["address"] or "",
    }


def list_agencies(conn):
    ensure_agencies_schema(conn)
    rows = conn.execute(
        """
        SELECT id, name, gst, address
        FROM agencies
        ORDER BY LOWER(name), id
        """
    ).fetchall()
    return [agency_row_to_dict(row) for row in rows]


def get_agency(conn, agency_id):
    ensure_agencies_schema(conn)
    if not agency_id:
        return None
    try:
        agency_id = int(agency_id)
    except (TypeError, ValueError):
        return None
    row = conn.execute(
        "SELECT id, name, gst, address FROM agencies WHERE id = ?",
        (agency_id,),
    ).fetchone()
    return agency_row_to_dict(row)


def save_agency_record(conn, name, gst="", address="", agency_id=None):
    """Insert/update Agency Master. Returns (saved_id, errors)."""
    ensure_agencies_schema(conn)
    name = _normalize_agency_name(name)
    gst = _normalize_agency_gst(gst)
    address = _normalize_agency_address(address)
    errors = []
    if not name:
        errors.append("Agency name is required.")
    else:
        existing = conn.execute(
            "SELECT id FROM agencies WHERE LOWER(name) = LOWER(?) LIMIT 1",
            (name,),
        ).fetchone()
        if existing and (agency_id is None or int(existing["id"]) != int(agency_id)):
            errors.append("An agency with this name already exists.")
    if errors:
        return None, errors

    if agency_id:
        try:
            agency_id = int(agency_id)
        except (TypeError, ValueError):
            return None, ["Agency not found."]
        cursor = conn.execute(
            f"""
            UPDATE agencies
            SET name = ?, gst = ?, address = ?, updated_at = {SQL_NOW}
            WHERE id = ?
            """,
            (name, gst, address, agency_id),
        )
        if cursor.rowcount <= 0:
            return None, ["Agency not found."]
        return agency_id, []

    cursor = conn.execute(
        f"""
        INSERT INTO agencies (name, gst, address, created_at, updated_at)
        VALUES (?, ?, ?, {SQL_NOW}, {SQL_NOW})
        """,
        (name, gst, address),
    )
    return int(cursor.lastrowid), []


def upsert_agency_by_name(conn, name, gst="", address=""):
    """Create or update an agency matched by case-insensitive name."""
    ensure_agencies_schema(conn)
    name = _normalize_agency_name(name)
    if not name:
        return None
    gst = _normalize_agency_gst(gst)
    address = _normalize_agency_address(address)
    existing = conn.execute(
        "SELECT id, gst, address FROM agencies WHERE LOWER(name) = LOWER(?) LIMIT 1",
        (name,),
    ).fetchone()
    if existing:
        next_gst = gst or (existing["gst"] or "")
        next_address = address or (existing["address"] or "")
        conn.execute(
            f"""
            UPDATE agencies
            SET name = ?, gst = ?, address = ?, updated_at = {SQL_NOW}
            WHERE id = ?
            """,
            (name, next_gst, next_address, existing["id"]),
        )
        return get_agency(conn, existing["id"])
    saved_id, errors = save_agency_record(conn, name, gst, address)
    if errors:
        return None
    return get_agency(conn, saved_id)


def delete_agency_record(conn, agency_id):
    ensure_agencies_schema(conn)
    try:
        agency_id = int(agency_id)
    except (TypeError, ValueError):
        return False
    cursor = conn.execute("DELETE FROM agencies WHERE id = ?", (agency_id,))
    return cursor.rowcount > 0


def list_pos_menu_categories(
    conn, include_inactive=False, outlet=POS_OUTLET_RESTAURANT, outlets=None
):
    """Return menu categories with active item counts for one or more outlets."""
    ensure_pos_schema(conn)
    outlet_list = resolve_pos_outlets(outlet=outlet, outlets=outlets)
    placeholders = ", ".join("?" for _ in outlet_list)
    clauses = [f"c.outlet IN ({placeholders})"]
    params = list(outlet_list)
    if not include_inactive:
        clauses.append("c.is_active = 1")
    where = "WHERE " + " AND ".join(clauses)
    rows = conn.execute(
        f"""
        SELECT
            c.id,
            c.name,
            c.outlet,
            c.sort_order,
            c.is_visible,
            c.is_active,
            COALESCE(SUM(CASE WHEN i.is_active = 1 THEN 1 ELSE 0 END), 0) AS item_count
        FROM pos_menu_categories c
        LEFT JOIN pos_menu_items i ON i.category_id = c.id AND i.outlet = c.outlet
        {where}
        GROUP BY c.id
        ORDER BY c.outlet ASC, c.sort_order ASC, c.name COLLATE NOCASE ASC, c.id ASC
        """,
        params,
    ).fetchall()
    return [
        {
            "id": int(r["id"]),
            "name": r["name"] or "",
            "outlet": normalize_pos_outlet(r["outlet"]),
            "sort_order": int(r["sort_order"] or 0),
            "is_visible": bool(r["is_visible"]),
            "is_active": bool(r["is_active"]),
            "item_count": int(r["item_count"] or 0),
        }
        for r in rows
    ]


def save_pos_menu_category(conn, *, category_id=None, name="", is_visible=True, sort_order=None, outlet=POS_OUTLET_RESTAURANT):
    """Create or update a menu category. Returns the saved row dict."""
    ensure_pos_schema(conn)
    outlet = normalize_pos_outlet(outlet)
    clean_name = " ".join(str(name or "").split()).strip()
    if not clean_name:
        raise ValueError("Category name is required.")
    if len(clean_name) > 80:
        raise ValueError("Category name must be 80 characters or fewer.")

    visible = 1 if is_visible else 0
    if category_id:
        existing = conn.execute(
            "SELECT id FROM pos_menu_categories WHERE id = ? AND is_active = 1 AND outlet = ?",
            (int(category_id), outlet),
        ).fetchone()
        if not existing:
            raise ValueError("Category not found.")
        dup = conn.execute(
            """
            SELECT id FROM pos_menu_categories
            WHERE is_active = 1 AND outlet = ? AND id != ? AND lower(name) = lower(?)
            """,
            (outlet, int(category_id), clean_name),
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
            WHERE is_active = 1 AND outlet = ? AND lower(name) = lower(?)
            """,
            (outlet, clean_name),
        ).fetchone()
        if dup:
            raise ValueError("A category with this name already exists.")
        if sort_order is None:
            max_row = conn.execute(
                "SELECT COALESCE(MAX(sort_order), 0) AS m FROM pos_menu_categories WHERE is_active = 1 AND outlet = ?",
                (outlet,),
            ).fetchone()
            sort_order = int(max_row["m"] or 0) + 10
        cur = conn.execute(
            f"""
            INSERT INTO pos_menu_categories (name, sort_order, is_visible, is_active, outlet, created_at, updated_at)
            VALUES (?, ?, ?, 1, ?, {SQL_NOW}, {SQL_NOW})
            """,
            (clean_name, int(sort_order), visible, outlet),
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
    product_outlet = ""
    if "product_outlet" in row.keys() and row["product_outlet"] is not None:
        product_outlet = str(row["product_outlet"] or "").strip().lower()
    line_cost = recipe_line_food_cost(qty, unit, product_unit, price_val)
    return {
        "id": int(row["id"]),
        "menu_item_id": int(row["menu_item_id"]),
        "product_id": int(row["product_id"]),
        "product_name": (row["product_name"] if "product_name" in row.keys() else None) or "",
        "product_unit": product_unit,
        "product_outlet": product_outlet or "restaurant",
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
            p.outlet AS product_outlet,
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
        "item_kind": (
            "liquor"
            if str(_text("item_kind") or "food").strip().lower()
            in ("liquor", "liquour", "alcohol", "bar")
            else "food"
        ),
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
        "outlet": normalize_pos_outlet(row["outlet"] if "outlet" in keys else None),
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
            i.outlet,
            i.menu_type,
            i.item_kind,
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


def list_pos_menu_items(
    conn, category_id=None, include_inactive=False, outlet=POS_OUTLET_RESTAURANT, outlets=None
):
    """Return menu items, optionally filtered by category and one or more outlets."""
    ensure_pos_schema(conn)
    ensure_stores_schema(conn)
    outlet_list = resolve_pos_outlets(outlet=outlet, outlets=outlets)
    placeholders = ", ".join("?" for _ in outlet_list)
    clauses = [f"i.outlet IN ({placeholders})"]
    params = list(outlet_list)
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
        ORDER BY i.outlet ASC, i.sort_order ASC, i.name COLLATE NOCASE ASC, i.id ASC
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
    item_kind=None,
    portion_size=None,
    prep_time_mins=None,
    shelf_life=None,
    notes=None,
    target_margin_pct=None,
    updated_by=None,
    price_change_reason="",
    outlet=POS_OUTLET_RESTAURANT,
):
    """Create or update a menu item; optional recipe[] replaces ingredient lines."""
    ensure_pos_schema(conn)
    ensure_stores_schema(conn)
    outlet = normalize_pos_outlet(outlet)

    try:
        cat_id = int(category_id) if category_id not in (None, "") else None
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid category.") from exc
    if not cat_id:
        raise ValueError("Category is required.")
    cat = conn.execute(
        "SELECT id FROM pos_menu_categories WHERE id = ? AND is_active = 1 AND outlet = ?",
        (cat_id, outlet),
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
            SELECT id, rate, menu_type, item_kind, portion_size, prep_time_mins, shelf_life,
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
        cur_item_kind = (
            (existing_row["item_kind"] or "food") if "item_kind" in existing_row.keys() else "food"
        )
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
        cur_item_kind = "food"
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
    if clean_menu_type in ("liquour", "alcohol"):
        clean_menu_type = "liquor"
    if clean_menu_type not in ("", "veg", "non_veg", "liquor"):
        raise ValueError("Menu type must be Veg, Non-Veg, or Liquor.")
    clean_menu_type = clean_menu_type[:20]

    if item_kind is None:
        # Liquor menu type implies liquor tax class when kind wasn't sent.
        if clean_menu_type == "liquor":
            clean_item_kind = "liquor"
        else:
            clean_item_kind = str(cur_item_kind or "food").strip().lower()
    else:
        clean_item_kind = str(item_kind or "food").strip().lower()
    if clean_menu_type == "liquor":
        clean_item_kind = "liquor"
    if clean_item_kind in ("liquour", "alcohol", "bar"):
        clean_item_kind = "liquor"
    if clean_item_kind not in ("food", "liquor"):
        raise ValueError("Item type must be Food or Liquor.")

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
                    variant = ?, rate = ?, menu_type = ?, item_kind = ?, portion_size = ?,
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
                    clean_item_kind,
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
                    variant = ?, rate = ?, sort_order = ?, menu_type = ?, item_kind = ?,
                    portion_size = ?,
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
                    clean_item_kind,
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
                sort_order, is_active, menu_type, item_kind, portion_size, prep_time_mins,
                shelf_life, notes, target_margin_pct, updated_by, outlet,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, {SQL_NOW}, {SQL_NOW})
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
                clean_item_kind,
                clean_portion,
                clean_prep,
                clean_shelf,
                clean_notes,
                clean_target,
                clean_updated_by,
                outlet,
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
            qty if mtype in ("issue", "adjust", "waste", "transfer", "sale", "consume") else 0
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


def get_pos_floor_layout(conn, outlet=POS_OUTLET_RESTAURANT):
    """Load floor areas/tables JSON for an outlet; returns empty lists when unset."""
    ensure_pos_schema(conn)
    outlet = normalize_pos_outlet(outlet)
    row = conn.execute(
        "SELECT payload FROM pos_floor_layout WHERE outlet = ?",
        (outlet,),
    ).fetchone()
    if not row:
        if outlet == POS_OUTLET_BAR:
            return default_bar_pos_floor_payload()
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


def save_pos_floor_layout(conn, areas, tables, outlet=POS_OUTLET_RESTAURANT):
    """Replace floor layout payload for an outlet."""
    ensure_pos_schema(conn)
    outlet = normalize_pos_outlet(outlet)
    payload = _normalize_pos_floor_payload(areas, tables)
    blob = json.dumps(payload, separators=(",", ":"))
    conn.execute(
        f"""
        INSERT INTO pos_floor_layout (outlet, payload, updated_at)
        VALUES (?, ?, {SQL_NOW})
        ON CONFLICT(outlet) DO UPDATE SET
            payload = excluded.payload,
            updated_at = {SQL_NOW}
        """
    , (outlet, blob))
    return payload


def _new_pos_merge_group_id():
    return f"mg_{datetime.now().strftime('%Y%m%d%H%M%S')}_{os.getpid() % 10000:04d}"


def _pos_find_table_by_name(tables, table_label):
    needle = str(table_label or "").strip().lower()
    if not needle:
        return None
    for t in tables or []:
        if str(t.get("name") or "").strip().lower() == needle:
            return t
    return None


def format_pos_merged_table_label(names):
    """Human label for a merged group, e.g. 'Table 1 and Table 2'."""
    clean = []
    seen = set()
    for raw in names or []:
        name = str(raw or "").strip()
        key = name.lower()
        if not name or key in seen:
            continue
        seen.add(key)
        clean.append(name)
    if not clean:
        return ""
    if len(clean) == 1:
        return clean[0]
    if len(clean) == 2:
        return f"{clean[0]} and {clean[1]}"
    return ", ".join(clean[:-1]) + f" and {clean[-1]}"


def link_pos_floor_tables_as_merged(conn, primary_label, member_labels, outlet=POS_OUTLET_RESTAURANT):
    """Visually join floor tables under one merge group.

    ``primary_label`` is the host tile (usually the bill destination). Members
    are hidden on the floor and shown together on the primary as
    \"Table 1 and Table 2\". Returns the updated layout payload.
    """
    ensure_pos_schema(conn)
    outlet = normalize_pos_outlet(outlet)
    primary_name = str(primary_label or "").strip()
    members = []
    for raw in member_labels or []:
        name = str(raw or "").strip()
        if name and name.lower() != primary_name.lower():
            members.append(name)
    if not primary_name:
        raise ValueError("Primary table is required.")
    if not members:
        return get_pos_floor_layout(conn, outlet)

    layout = get_pos_floor_layout(conn, outlet)
    tables = layout.get("tables") or []
    primary = _pos_find_table_by_name(tables, primary_name)
    if not primary:
        raise ValueError(f"Table {primary_name} was not found on the floor.")

    group_ids = set()
    if primary.get("mergeGroupId"):
        group_ids.add(str(primary["mergeGroupId"]))
    member_tiles = []
    for member_name in members:
        tile = _pos_find_table_by_name(tables, member_name)
        if not tile:
            raise ValueError(f"Table {member_name} was not found on the floor.")
        member_tiles.append(tile)
        if tile.get("mergeGroupId"):
            group_ids.add(str(tile["mergeGroupId"]))

    group_id = next(iter(group_ids), None) or _new_pos_merge_group_id()
    involved_ids = {str(primary.get("id") or "")}
    for tile in member_tiles:
        involved_ids.add(str(tile.get("id") or ""))
    if group_ids:
        for t in tables:
            if str(t.get("mergeGroupId") or "") in group_ids:
                involved_ids.add(str(t.get("id") or ""))

    primary_id = str(primary.get("id") or "")
    for t in tables:
        tid = str(t.get("id") or "")
        if tid not in involved_ids:
            continue
        t["mergeGroupId"] = group_id
        t["mergePrimary"] = tid == primary_id

    return save_pos_floor_layout(conn, layout.get("areas") or [], tables, outlet)


def unmerge_pos_floor_tables(conn, table_label, outlet=POS_OUTLET_RESTAURANT):
    """Split a visual merge group back into separate floor tiles.

    Does not move or close any open bill — the invoice stays on its current
    ``table_label``. Returns ``{layout, group_names, primary_name, label}``.
    """
    ensure_pos_schema(conn)
    outlet = normalize_pos_outlet(outlet)
    name = str(table_label or "").strip()
    if not name:
        raise ValueError("Table is required.")
    layout = get_pos_floor_layout(conn, outlet)
    tables = layout.get("tables") or []
    tile = _pos_find_table_by_name(tables, name)
    if not tile:
        raise ValueError(f"Table {name} was not found on the floor.")
    group_id = str(tile.get("mergeGroupId") or "").strip()
    if not group_id:
        raise ValueError(f"{name} is not part of a merged group.")

    group_names = []
    primary_name = name
    for t in tables:
        if str(t.get("mergeGroupId") or "") != group_id:
            continue
        group_names.append(str(t.get("name") or "").strip())
        if t.get("mergePrimary"):
            primary_name = str(t.get("name") or "").strip() or primary_name
        t["mergeGroupId"] = None
        t["mergePrimary"] = False

    payload = save_pos_floor_layout(conn, layout.get("areas") or [], tables, outlet)
    return {
        "layout": payload,
        "group_names": group_names,
        "primary_name": primary_name,
        "label": format_pos_merged_table_label(group_names),
    }


def enrich_pos_floor_tables_for_display(tables):
    """Attach display helpers for merged groups (does not mutate storage shape).

    Returns a new list of table dicts with:
    - ``displayName`` — \"Table 1 and Table 2\" for primaries
    - ``mergedNames`` — list of names in the group
    - ``mergedSeats`` — sum of seats in the group
    - ``hiddenInMerge`` — True for non-primary members (skip in floor grid)
    """
    tables = [dict(t) for t in (tables or []) if isinstance(t, dict)]
    by_group = {}
    for t in tables:
        gid = str(t.get("mergeGroupId") or "").strip()
        if not gid:
            t["displayName"] = str(t.get("name") or "").strip()
            t["mergedNames"] = [t["displayName"]] if t["displayName"] else []
            t["mergedSeats"] = int(t.get("seats") or 0) or None
            t["hiddenInMerge"] = False
            continue
        by_group.setdefault(gid, []).append(t)

    for gid, group in by_group.items():
        names = []
        seats_total = 0
        primary = None
        for t in group:
            n = str(t.get("name") or "").strip()
            if n:
                names.append(n)
            try:
                seats_total += max(0, int(t.get("seats") or 0))
            except (TypeError, ValueError):
                pass
            if t.get("mergePrimary"):
                primary = t
        if primary is None and group:
            primary = group[0]
            primary["mergePrimary"] = True
        primary_name = str((primary or {}).get("name") or "").strip()
        others = sorted(
            [n for n in names if n.lower() != primary_name.lower()],
            key=lambda s: s.lower(),
        )
        ordered = ([primary_name] if primary_name else []) + others
        label = format_pos_merged_table_label(ordered)
        for t in group:
            is_primary = bool(t.get("mergePrimary"))
            t["displayName"] = label if is_primary else str(t.get("name") or "").strip()
            t["mergedNames"] = ordered
            t["mergedSeats"] = seats_total or None
            t["hiddenInMerge"] = not is_primary

    return tables


def get_pos_restaurant_settings(conn, outlet=POS_OUTLET_RESTAURANT):
    """Load outlet settings JSON blob (empty dict when unset)."""
    ensure_pos_schema(conn)
    outlet = normalize_pos_outlet(outlet)
    row = conn.execute(
        "SELECT payload FROM pos_restaurant_settings WHERE outlet = ?",
        (outlet,),
    ).fetchone()
    if not row:
        return {}
    try:
        parsed = json.loads(row["payload"] or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def save_pos_restaurant_settings(conn, settings, outlet=POS_OUTLET_RESTAURANT):
    """Replace outlet settings JSON."""
    ensure_pos_schema(conn)
    outlet = normalize_pos_outlet(outlet)
    if not isinstance(settings, dict):
        settings = {}
    blob = json.dumps(settings, separators=(",", ":"))
    conn.execute(
        f"""
        INSERT INTO pos_restaurant_settings (outlet, payload, updated_at)
        VALUES (?, ?, {SQL_NOW})
        ON CONFLICT(outlet) DO UPDATE SET
            payload = excluded.payload,
            updated_at = {SQL_NOW}
        """
    , (outlet, blob))
    return settings


# Defaults match long-standing Create Invoice hardcoded rates (percent).
POS_DEFAULT_CGST_PCT = 2.5
POS_DEFAULT_UGST_PCT = 2.5
POS_DEFAULT_VAT_PCT = 10.0


def _pos_settings_panel_values(settings, panel_key):
    """Return the values map for a settings panel (supports legacy array shape)."""
    if not isinstance(settings, dict):
        return {}
    panels = settings.get("panels")
    if not isinstance(panels, dict):
        return {}
    fields = panels.get(panel_key)
    if fields is None:
        return {}
    if isinstance(fields, dict):
        values = fields.get("values")
        if isinstance(values, dict):
            return values
        return {k: v for k, v in fields.items() if k not in ("v", "listboxes")}
    if isinstance(fields, list):
        out = {}
        idx = 0
        for field in fields:
            if not isinstance(field, dict) or field.get("kind") == "listbox":
                continue
            out[f"f{idx}"] = field
            idx += 1
        return out
    return {}


def _pos_settings_pct(values, named_key, legacy_index, default_pct):
    """Parse a percent field from settings values (named key or legacy fN)."""
    if not isinstance(values, dict):
        return float(default_pct)
    field = values.get(named_key)
    if field is None:
        field = values.get(f"f{int(legacy_index)}")
    raw = None
    if isinstance(field, dict):
        raw = field.get("value")
    elif field is not None:
        raw = field
    try:
        pct = float(raw)
    except (TypeError, ValueError):
        return float(default_pct)
    if pct != pct or pct < 0:  # NaN / negative
        return float(default_pct)
    if pct > 100:
        pct = 100.0
    return round(pct, 4)


def get_pos_tax_rates(conn, outlet=POS_OUTLET_RESTAURANT):
    """Return CGST/UGST/VAT fractions (0–1) from outlet Taxes settings."""
    settings = get_pos_restaurant_settings(conn, outlet)
    values = _pos_settings_panel_values(settings, "taxes")
    cgst_pct = _pos_settings_pct(values, "cgst_pct", 0, POS_DEFAULT_CGST_PCT)
    ugst_pct = _pos_settings_pct(values, "ugst_pct", 1, POS_DEFAULT_UGST_PCT)
    vat_pct = _pos_settings_pct(values, "vat_pct", 2, POS_DEFAULT_VAT_PCT)
    return {
        "cgst_pct": cgst_pct,
        "ugst_pct": ugst_pct,
        "vat_pct": vat_pct,
        "cgst": round(cgst_pct / 100.0, 6),
        "ugst": round(ugst_pct / 100.0, 6),
        "vat": round(vat_pct / 100.0, 6),
    }


POS_INVOICE_ORDER_TYPES = (
    ("dine_in", "Dine In"),
    ("takeaway", "Takeaway"),
    ("delivery", "Delivery"),
)
POS_INVOICE_ORDER_TYPE_LABELS = dict(POS_INVOICE_ORDER_TYPES)

POS_INVOICE_SETTLEMENT_STATUSES = (
    ("settled", "Settled"),
    ("unsettled", "Un Settled"),
)
POS_INVOICE_SETTLEMENT_STATUS_LABELS = dict(POS_INVOICE_SETTLEMENT_STATUSES)


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


def _parse_discount_line_uids(raw):
    """Return unique line uid strings from JSON array text (or empty list)."""
    text = str(raw or "").strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    out = []
    for item in data:
        uid = str(item or "").strip()
        if uid and uid not in out:
            out.append(uid)
    return out


def _serialize_discount_line_uids(uids):
    cleaned = []
    for item in uids or []:
        uid = str(item or "").strip()
        if uid and uid not in cleaned:
            cleaned.append(uid)
    return json.dumps(cleaned) if cleaned else ""


def _pos_invoice_line_dicts(conn, invoice_id):
    rows = conn.execute(
        """
        SELECT
            l.id,
            l.sort_order,
            l.menu_item_id,
            l.name,
            l.variant,
            l.rate,
            l.qty,
            l.line_total,
            l.sent_qty,
            l.notes,
            l.line_uid,
            m.outlet AS menu_outlet
        FROM pos_invoice_lines l
        LEFT JOIN pos_menu_items m ON m.id = l.menu_item_id
        WHERE l.invoice_id = ?
        ORDER BY l.sort_order ASC, l.id ASC
        """,
        (int(invoice_id),),
    ).fetchall()
    lines = []
    for idx, row in enumerate(rows):
        qty = _pos_money(row["qty"])
        sent_qty = _pos_money(row["sent_qty"])
        if sent_qty > qty:
            sent_qty = qty
        keys = row.keys()
        notes = (row["notes"] if "notes" in keys else "") or ""
        line_uid = ""
        if "line_uid" in keys:
            line_uid = str(row["line_uid"] or "").strip()
        if not line_uid:
            line_uid = f"L{idx + 1}"
        menu_outlet = "restaurant"
        if "menu_outlet" in keys:
            menu_outlet = normalize_pos_outlet(row["menu_outlet"])
        lines.append(
            {
                "id": int(row["id"]),
                "uid": line_uid,
                "line_uid": line_uid,
                "sort_order": int(row["sort_order"] or 0),
                "menu_item_id": int(row["menu_item_id"]) if row["menu_item_id"] is not None else None,
                "name": row["name"] or "",
                "variant": row["variant"] or "",
                "rate": _pos_money(row["rate"]),
                "qty": qty,
                "line_total": _pos_money(row["line_total"]),
                "sent_qty": sent_qty,
                "notes": str(notes).strip()[:200],
                "outlet": menu_outlet,
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
        "discount_line_uids": _parse_discount_line_uids(
            row["discount_line_uids"] if "discount_line_uids" in row.keys() else ""
        ),
        "discount_reason": (row["discount_reason"] or "")
        if "discount_reason" in row.keys()
        else "",
        "subtotal": _pos_money(row["subtotal"]),
        "discount": _pos_money(row["discount_amount"]),
        "gst": _pos_money(row["gst_amount"]),
        "vat": _pos_money(row["vat_amount"]) if "vat_amount" in row.keys() else 0.0,
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
        "stock_deducted_at": (row["stock_deducted_at"] or "") if "stock_deducted_at" in row.keys() else "",
        "outlet": normalize_pos_outlet(row["outlet"]) if "outlet" in row.keys() else POS_OUTLET_RESTAURANT,
        "item_count": int(row["item_count"]) if "item_count" in row.keys() else 0,
        "payment_modes": [],
        "payment_mode_label": "Unsettled",
    }
    if include_lines:
        item["lines"] = _pos_invoice_line_dicts(conn, invoice_id)
        if not item["item_count"]:
            item["item_count"] = len(item["lines"])
    return item


def _pos_payment_mode_labels_from_methods(methods):
    """Unique display labels in settlement order (Cash + UPI, etc.)."""
    labels = []
    seen = set()
    for raw in methods or []:
        key = _normalize_pos_payment_method(raw) or str(raw or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        labels.append(POS_PAYMENT_METHOD_LABELS.get(key, key.replace("_", " ").title()))
    return labels


def _apply_pos_invoice_payment_modes(conn, invoice):
    """Attach payment_modes / payment_mode_label from pos_invoice_payments."""
    if not invoice or not invoice.get("id"):
        return invoice
    payments = list_pos_invoice_payments(conn, invoice["id"])
    methods = [p.get("payment_method") for p in payments]
    labels = _pos_payment_mode_labels_from_methods(methods)
    unique_modes = []
    seen = set()
    for raw in methods:
        key = _normalize_pos_payment_method(raw) or str(raw or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        unique_modes.append(key)
    invoice["payment_modes"] = unique_modes
    invoice["payment_mode_label"] = " + ".join(labels) if labels else "Unsettled"
    return invoice


def _enrich_pos_invoices_payment_modes(conn, invoices):
    """Batch-fill payment mode labels for ledger lists."""
    ensure_pos_schema(conn)
    rows = list(invoices or [])
    if not rows:
        return rows
    ids = [int(inv["id"]) for inv in rows if inv and inv.get("id") is not None]
    if not ids:
        return rows
    placeholders = ",".join("?" for _ in ids)
    pay_rows = conn.execute(
        f"""
        SELECT invoice_id, payment_method
        FROM pos_invoice_payments
        WHERE invoice_id IN ({placeholders})
        ORDER BY id ASC
        """,
        ids,
    ).fetchall()
    by_id = {}
    for pay in pay_rows:
        by_id.setdefault(int(pay["invoice_id"]), []).append(pay["payment_method"])
    for inv in rows:
        methods = by_id.get(int(inv["id"]), [])
        labels = _pos_payment_mode_labels_from_methods(methods)
        unique_modes = []
        seen = set()
        for raw in methods:
            key = _normalize_pos_payment_method(raw) or str(raw or "").strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            unique_modes.append(key)
        inv["payment_modes"] = unique_modes
        inv["payment_mode_label"] = " + ".join(labels) if labels else "Unsettled"
    return rows


def _pos_floor_table_status(layout, table_label):
    """Case-insensitive floor status lookup for a table name; None when not on the floor."""
    needle = str(table_label or "").strip().lower()
    if not needle:
        return None
    for t in (layout or {}).get("tables") or []:
        if str(t.get("name") or "").strip().lower() == needle:
            return str(t.get("status") or "available").strip().lower() or "available"
    return None


def _pos_mark_table_occupied(conn, table_label, outlet=POS_OUTLET_RESTAURANT):
    """Flip a table to occupied when a dine-in bill claims it (save / autosave / KOT).

    Best-effort: only advances tables that are currently available — never
    overrides reserved/cleaning/inactive set deliberately from the Tables page.
    """
    needle = str(table_label or "").strip().lower()
    if not needle:
        return
    outlet = normalize_pos_outlet(outlet)
    layout = get_pos_floor_layout(conn, outlet)
    tables = layout.get("tables") or []
    changed = False
    for t in tables:
        if str(t.get("name") or "").strip().lower() == needle:
            if str(t.get("status") or "available").strip().lower() in ("", "available"):
                t["status"] = "occupied"
                changed = True
            break
    if changed:
        save_pos_floor_layout(conn, layout.get("areas") or [], tables, outlet)


def _pos_mark_table_available(conn, table_label, outlet=POS_OUTLET_RESTAURANT):
    """Free a table back to available — used when a bill is explicitly closed.
    Unlike _pos_mark_table_occupied this is an unconditional override: closing a
    bill is a deliberate staff action, so it wins over whatever status the table
    was showing."""
    needle = str(table_label or "").strip().lower()
    if not needle:
        return
    outlet = normalize_pos_outlet(outlet)
    layout = get_pos_floor_layout(conn, outlet)
    tables = layout.get("tables") or []
    changed = False
    for t in tables:
        if str(t.get("name") or "").strip().lower() == needle:
            if str(t.get("status") or "").strip().lower() != "available":
                t["status"] = "available"
                changed = True
            break
    if changed:
        save_pos_floor_layout(conn, layout.get("areas") or [], tables, outlet)


def sync_pos_floor_occupancy_from_open_orders(conn, outlet=POS_OUTLET_RESTAURANT):
    """Align floor tiles with active (pre-invoice) dine-in bills.

    - Available → Occupied when an open bill exists that has not yet had its
      customer invoice generated.
    - Occupied → Available when no such bill exists (repairs stale tiles after
      Generate Invoice, table moves, closes, or bad saves). Reserved / cleaning /
      inactive are never changed.

    Once Generate Invoice (customer_bill_sent) runs, the table is free for the
    next party even if Settle Bill is still pending.
    """
    ensure_pos_schema(conn)
    outlet = normalize_pos_outlet(outlet)
    rows = conn.execute(
        """
        SELECT DISTINCT table_label
        FROM pos_invoices
        WHERE is_active = 1
          AND status = 'open'
          AND order_type = 'dine_in'
          AND outlet = ?
          AND TRIM(COALESCE(table_label, '')) != ''
          AND COALESCE(customer_bill_sent, 0) = 0
        """,
        (outlet,),
    ).fetchall()
    occupied_labels = set()
    for row in rows:
        label = str((row["table_label"] if row else "") or "").strip()
        if not label:
            continue
        occupied_labels.add(label.lower())
        _pos_mark_table_occupied(conn, label, outlet)

    layout = get_pos_floor_layout(conn, outlet)
    tables = layout.get("tables") or []
    changed = False
    for t in tables:
        name = str(t.get("name") or "").strip()
        if not name:
            continue
        status = str(t.get("status") or "available").strip().lower() or "available"
        if status != "occupied":
            continue
        if name.lower() not in occupied_labels:
            t["status"] = "available"
            changed = True
    if changed:
        save_pos_floor_layout(conn, layout.get("areas") or [], tables, outlet)


def get_open_pos_invoice_for_table(conn, table_label, outlet=POS_OUTLET_RESTAURANT):
    """Return the most recent active (pre-invoice) open dine-in bill for a table.

    Invoices that already had Generate Invoice (customer_bill_sent) no longer
    claim the table — settle continues from the locked bill / ledger, while the
    floor tile is free for a new party.
    """
    ensure_pos_schema(conn)
    outlet = normalize_pos_outlet(outlet)
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
          AND i.outlet = ?
          AND LOWER(i.table_label) = LOWER(?)
          AND COALESCE(i.customer_bill_sent, 0) = 0
        ORDER BY i.id DESC
        LIMIT 1
        """,
        (outlet, needle),
    ).fetchone()
    return _pos_invoice_row_to_dict(conn, row, include_lines=True)


def transfer_pos_invoice_table(conn, from_table, to_table, outlet=POS_OUTLET_RESTAURANT):
    """Move an open dine-in bill from one floor table to another available table.

    Updates ``pos_invoices.table_label``, frees the source tile, and marks the
    destination occupied. Raises ``ValueError`` with a staff-facing message on
    validation failure.
    """
    ensure_pos_schema(conn)
    outlet = normalize_pos_outlet(outlet)
    from_label = str(from_table or "").strip()
    to_label = str(to_table or "").strip()
    if not from_label:
        raise ValueError("Source table is required.")
    if not to_label:
        raise ValueError("Destination table is required.")
    if from_label.lower() == to_label.lower():
        raise ValueError("Choose a different destination table.")

    invoice = get_open_pos_invoice_for_table(conn, from_label, outlet)
    if not invoice:
        raise ValueError(f"No open bill on {from_label}.")

    if get_open_pos_invoice_for_table(conn, to_label, outlet):
        raise ValueError(f"{to_label} already has an open bill.")

    layout = get_pos_floor_layout(conn, outlet)
    tables = layout.get("tables") or []
    dest = None
    for t in tables:
        if str(t.get("name") or "").strip().lower() == to_label.lower():
            dest = t
            break
    if not dest:
        raise ValueError(f"Table {to_label} was not found on the floor.")
    dest_status = str(dest.get("status") or "available").strip().lower() or "available"
    if dest_status == "blocked":
        dest_status = "inactive"
    if dest_status != "available":
        raise ValueError(f"{to_label} is not available.")

    to_canonical = str(dest.get("name") or to_label).strip()
    from_canonical = str(invoice.get("table_label") or from_label).strip()

    conn.execute(
        "UPDATE pos_invoices SET table_label = ? WHERE id = ?",
        (to_canonical, int(invoice["id"])),
    )
    _pos_mark_table_available(conn, from_canonical, outlet)
    _pos_mark_table_occupied(conn, to_canonical, outlet)
    return get_pos_invoice(conn, int(invoice["id"]))


def _recompute_pos_invoice_money_from_lines(conn, invoice_id):
    """Recalculate subtotal/discount/gst/vat/service/tip/total from current lines.

    Uses the destination invoice's stored discount/service/tip settings.
    Food / non-alcohol lines: 5% GST (CGST+UGST). Bar Alcohol (bar-outlet liquor): 10% VAT.
    Round half to nearest rupee — same rule as the Create Invoice UI.
    """
    ensure_pos_schema(conn)
    try:
        invoice_id = int(invoice_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid invoice id.") from exc
    row = conn.execute(
        """
        SELECT id, outlet, discount_type, discount_value, service_type, service_value, tip, tip_amount,
               discount_line_uids
        FROM pos_invoices
        WHERE id = ? AND is_active = 1
        """,
        (invoice_id,),
    ).fetchone()
    if not row:
        raise ValueError("Invoice not found.")

    line_rows = conn.execute(
        """
        SELECT l.rate, l.qty, l.menu_item_id, l.variant, l.line_uid, c.name AS category_name,
               i.item_kind, i.menu_type, i.outlet AS menu_outlet
        FROM pos_invoice_lines l
        LEFT JOIN pos_menu_items i ON i.id = l.menu_item_id
        LEFT JOIN pos_menu_categories c ON c.id = i.category_id
        WHERE l.invoice_id = ?
        """,
        (invoice_id,),
    ).fetchall()
    subtotal = 0.0
    bar_alcohol_subtotal = 0.0
    scoped_uids = set(
        _parse_discount_line_uids(
            row["discount_line_uids"] if "discount_line_uids" in row.keys() else ""
        )
    )
    discount_base = 0.0
    for line in line_rows:
        line_total = _pos_money(line["rate"]) * _pos_money(line["qty"])
        subtotal += line_total
        line_uid = ""
        if "line_uid" in line.keys() and line["line_uid"]:
            line_uid = str(line["line_uid"] or "").strip()
        if not scoped_uids or (line_uid and line_uid in scoped_uids):
            discount_base += line_total
        keys = line.keys()
        menu_outlet = "restaurant"
        if "menu_outlet" in keys and line["menu_outlet"]:
            menu_outlet = normalize_pos_outlet(line["menu_outlet"])
        kind = ""
        if "item_kind" in keys and line["item_kind"]:
            kind = str(line["item_kind"] or "").strip().lower()
        if kind in ("liquour", "alcohol", "bar"):
            kind = "liquor"
        menu_type = ""
        if "menu_type" in keys and line["menu_type"]:
            menu_type = str(line["menu_type"] or "").strip().lower()
        if menu_type in ("liquour", "alcohol"):
            menu_type = "liquor"
        cat = ""
        if "category_name" in keys and line["category_name"]:
            cat = line["category_name"]
        elif line["variant"]:
            cat = line["variant"]
        is_liquor = kind == "liquor" or menu_type == "liquor" or is_pos_liquor_category(cat)
        if menu_outlet == POS_OUTLET_BAR and is_liquor:
            bar_alcohol_subtotal += line_total
    subtotal = _pos_money(subtotal)
    bar_alcohol_subtotal = _pos_money(bar_alcohol_subtotal)
    discount_base = _pos_money(discount_base if scoped_uids else subtotal)

    discount_type = str(row["discount_type"] or "pct").strip().lower() or "pct"
    service_type = str(row["service_type"] or "pct").strip().lower() or "pct"
    discount_value = _pos_money(row["discount_value"])
    service_value = _pos_money(row["service_value"])
    tip = _pos_money(row["tip"] if row["tip"] is not None else row["tip_amount"])

    if discount_type == "inr":
        discount = min(max(0.0, discount_base), max(0.0, discount_value))
        discount = min(discount, max(0.0, subtotal))
    else:
        pct = min(100.0, max(0.0, discount_value))
        discount = _pos_money(max(0.0, discount_base) * (pct / 100.0))
        discount = min(discount, max(0.0, subtotal))
    after_discount = max(0.0, subtotal - discount)
    bar_share = (bar_alcohol_subtotal / subtotal) if subtotal > 0 else 0.0
    bar_after = _pos_money(after_discount * bar_share)
    food_after = max(0.0, after_discount - bar_after)
    inv_outlet = normalize_pos_outlet(row["outlet"] if "outlet" in row.keys() else None)
    rates = get_pos_tax_rates(conn, inv_outlet)
    gst = _pos_money(food_after * (rates["cgst"] + rates["ugst"]))
    vat = _pos_money(bar_after * rates["vat"])
    if service_type == "inr":
        service = min(max(0.0, after_discount), max(0.0, service_value))
    else:
        pct = min(100.0, max(0.0, service_value))
        service = _pos_money(max(0.0, after_discount) * (pct / 100.0))
    tip = max(0.0, tip)
    before_round = after_discount + gst + vat + service + tip
    rounded = float(round(before_round))
    round_off = _pos_money(rounded - before_round)
    grand_total = _pos_money(rounded)

    conn.execute(
        f"""
        UPDATE pos_invoices SET
            subtotal = ?,
            discount_amount = ?,
            gst_amount = ?,
            vat_amount = ?,
            service_amount = ?,
            tip = ?,
            tip_amount = ?,
            round_off = ?,
            grand_total = ?,
            updated_at = {SQL_NOW}
        WHERE id = ?
        """,
        (
            subtotal,
            discount,
            gst,
            vat,
            service,
            tip,
            tip,
            round_off,
            grand_total,
            invoice_id,
        ),
    )
    return get_pos_invoice(conn, invoice_id)


def merge_pos_invoice_tables(conn, from_table, to_table, outlet=POS_OUTLET_RESTAURANT):
    """Merge two floor tables onto the destination (“Merge into”).

    - Both have open bills: combine lines onto dest, soft-delete source, free
      source tile, then visually join the tiles.
    - Only source has an open bill: move that invoice onto dest, free source,
      occupy dest, then visually join.
    - Only dest has an open bill (or neither): visually join the tiles under
      the destination host — no bill move required.

    Always creates/updates a floor ``mergeGroupId`` so the UI shows
    \"Table 1 and Table 2\". Returns the resulting open invoice dict, or
    ``None`` when the merge was visual-only (no open bill on either table).
    """
    ensure_pos_schema(conn)
    outlet = normalize_pos_outlet(outlet)
    from_label = str(from_table or "").strip()
    to_label = str(to_table or "").strip()
    if not from_label:
        raise ValueError("Source table is required.")
    if not to_label:
        raise ValueError("Destination table is required.")
    if from_label.lower() == to_label.lower():
        raise ValueError("Choose a different destination table.")

    source = get_open_pos_invoice_for_table(conn, from_label, outlet)
    dest = get_open_pos_invoice_for_table(conn, to_label, outlet)

    layout = get_pos_floor_layout(conn, outlet)
    tables = layout.get("tables") or []
    dest_tile = None
    source_tile = None
    for t in tables:
        name = str(t.get("name") or "").strip()
        if name.lower() == to_label.lower():
            dest_tile = t
        if name.lower() == from_label.lower():
            source_tile = t
    if not dest_tile:
        raise ValueError(f"Table {to_label} was not found on the floor.")
    if not source_tile:
        raise ValueError(f"Table {from_label} was not found on the floor.")

    to_canonical = str(dest_tile.get("name") or to_label).strip()
    from_canonical = str(source_tile.get("name") or from_label).strip()

    # Visual-only (or dest already holds the only bill): join tiles, keep bill.
    if not source:
        link_pos_floor_tables_as_merged(conn, to_canonical, [from_canonical], outlet)
        if dest:
            return get_pos_invoice(conn, int(dest["id"]))
        return None

    from_canonical = str(source.get("table_label") or from_canonical).strip()
    source_id = int(source["id"])

    # Empty destination: move the whole source invoice onto that table.
    if not dest:
        conn.execute(
            "UPDATE pos_invoices SET table_label = ? WHERE id = ?",
            (to_canonical, source_id),
        )
        _pos_mark_table_available(conn, from_canonical, outlet)
        _pos_mark_table_occupied(conn, to_canonical, outlet)
        try:
            link_pos_floor_tables_as_merged(conn, to_canonical, [from_canonical], outlet)
        except ValueError:
            pass
        return get_pos_invoice(conn, source_id)

    dest_id = int(dest["id"])
    if source_id == dest_id:
        raise ValueError("Choose a different destination table.")

    max_sort = conn.execute(
        "SELECT COALESCE(MAX(sort_order), 0) AS m FROM pos_invoice_lines WHERE invoice_id = ?",
        (dest_id,),
    ).fetchone()
    sort_base = int(max_sort["m"] if max_sort else 0)

    source_lines = conn.execute(
        """
        SELECT id, sort_order
        FROM pos_invoice_lines
        WHERE invoice_id = ?
        ORDER BY sort_order ASC, id ASC
        """,
        (source_id,),
    ).fetchall()
    for idx, line in enumerate(source_lines, start=1):
        conn.execute(
            """
            UPDATE pos_invoice_lines
            SET invoice_id = ?, sort_order = ?
            WHERE id = ?
            """,
            (dest_id, sort_base + idx, int(line["id"])),
        )

    src_notes = str(source.get("notes") or "").strip()
    dest_notes = str(dest.get("notes") or "").strip()
    if src_notes:
        merged_notes = (
            f"{dest_notes}\n[Merged from {from_canonical}] {src_notes}".strip()
            if dest_notes
            else f"[Merged from {from_canonical}] {src_notes}"
        )
        conn.execute(
            "UPDATE pos_invoices SET notes = ? WHERE id = ?",
            (merged_notes[:2000], dest_id),
        )

    soft_delete_pos_invoice(conn, source_id)
    _pos_mark_table_available(conn, from_canonical, outlet)
    _pos_mark_table_occupied(conn, to_canonical, outlet)
    try:
        link_pos_floor_tables_as_merged(conn, to_canonical, [from_canonical], outlet)
    except ValueError:
        pass
    return _recompute_pos_invoice_money_from_lines(conn, dest_id)


def list_pos_kot_pending_summary(conn, outlet=POS_OUTLET_RESTAURANT):
    """Open dine-in orders with unsents (qty > sent_qty) — same rule as the
    invoice page KOT pending check. Powers the Tables page Kitchen Orders
    Pending banner and details modal.

    Includes tables with a plain save (kot_sent=0, sent_qty=0) and Occupied
    tables with later qty bumps — occupancy / kot_sent is intentionally not a
    filter here.
    """
    ensure_pos_schema(conn)
    outlet = normalize_pos_outlet(outlet)
    layout = get_pos_floor_layout(conn, outlet)
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
          AND i.outlet = ?
          AND TRIM(COALESCE(i.table_label, '')) != ''
        GROUP BY i.id, i.order_no, i.table_label, i.saved_at, i.updated_at, i.first_kot_at
        ORDER BY i.id ASC
        """,
        (outlet,),
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
        SELECT id, order_no, table_label, order_type, kot_sent, first_kot_at, status, outlet
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
    inv_outlet = normalize_pos_outlet(row["outlet"] if "outlet" in row.keys() else None)
    if table_label and order_type == "dine_in":
        _pos_mark_table_occupied(conn, table_label, inv_outlet)

    return get_pos_invoice(conn, invoice_id)


def list_pos_kot_tokens(conn, outlet=POS_OUTLET_RESTAURANT):
    """Open dine-in bills that already have kitchen-sent qty — Tables KOT hub.

    Used to resend / reprint a token when kitchen missed the slip. Only lines with
    sent_qty > 0 are included (the last confirmed kitchen copy).
    """
    ensure_pos_schema(conn)
    outlet = normalize_pos_outlet(outlet)
    layout = get_pos_floor_layout(conn, outlet)
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
          AND i.outlet = ?
          AND TRIM(COALESCE(i.table_label, '')) != ''
        GROUP BY
            i.id, i.order_no, i.table_label, i.order_type,
            i.first_kot_at, i.saved_at, i.updated_at,
            i.customer_bill_sent, i.customer_bill_at
        ORDER BY i.table_label ASC, i.id ASC
        """,
        (outlet,),
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
            SELECT
                l.id,
                l.name,
                l.variant,
                l.qty,
                COALESCE(l.sent_qty, 0) AS sent_qty,
                COALESCE(l.notes, '') AS notes,
                m.outlet AS menu_outlet
            FROM pos_invoice_lines l
            LEFT JOIN pos_menu_items m ON m.id = l.menu_item_id
            WHERE l.invoice_id = ?
              AND COALESCE(l.sent_qty, 0) > 0
            ORDER BY l.sort_order ASC, l.id ASC
            """,
            (invoice_id,),
        ).fetchall()
        lines = []
        for line in line_rows:
            sent_qty = float(line["sent_qty"] or 0)
            keys = line.keys()
            menu_outlet = "restaurant"
            if "menu_outlet" in keys:
                menu_outlet = normalize_pos_outlet(line["menu_outlet"])
            lines.append(
                {
                    "id": int(line["id"]),
                    "name": (line["name"] or "").strip(),
                    "variant": (line["variant"] or "").strip(),
                    "qty": sent_qty,
                    "sent_qty": sent_qty,
                    "notes": (line["notes"] or "").strip() if "notes" in keys else "",
                    "outlet": menu_outlet,
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


def close_pos_invoice_and_free_table(conn, invoice_id, *, user_id=None):
    """Close a bill (status -> 'closed') and free its table, if any. Decoupled
    from real payment for now — this is the 'Close & Free Table' action.

    On close, recipe ingredients for sold lines are deducted from store stock
    once (idempotent via stock_deducted_at / movement ref). Stock shortfalls
    never block closing the bill.
    """
    ensure_pos_schema(conn)
    try:
        invoice_id = int(invoice_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid invoice id.") from exc
    row = conn.execute(
        "SELECT id, table_label, order_type, outlet FROM pos_invoices WHERE id = ? AND is_active = 1",
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
    inv_outlet = normalize_pos_outlet(row["outlet"] if "outlet" in row.keys() else None)
    if table_label and order_type == "dine_in":
        _pos_mark_table_available(conn, table_label, inv_outlet)
    try:
        from stores import deduct_stock_for_pos_invoice

        deduct_stock_for_pos_invoice(conn, invoice_id, user_id=user_id)
    except Exception:
        import logging

        logging.getLogger(__name__).exception(
            "POS stock deduction failed for invoice_id=%s (bill still closed)",
            invoice_id,
        )
    return get_pos_invoice(conn, invoice_id)


POS_PAYMENT_METHODS = (
    ("cash", "Cash"),
    ("upi", "UPI"),
    ("card", "Card"),
    ("room_transfer", "Room Transfer"),
    ("bank_transfer", "Bank Transfer"),
)
POS_PAYMENT_METHOD_LABELS = dict(POS_PAYMENT_METHODS)
# Kept for historical settlements that still show in Invoice Ledger.
POS_PAYMENT_METHOD_LABELS["credit"] = "Credit"
POS_PAYMENT_METHODS_REQUIRING_TXN = frozenset({"bank_transfer"})


def _normalize_pos_payment_method(payment_method):
    value = str(payment_method or "").strip().lower()
    if value in ("bank_transfer", "bank", "bank transfer"):
        return "bank_transfer"
    if value == "upi":
        return "upi"
    if value in ("card", "credit card", "debit card"):
        return "card"
    if value == "cash":
        return "cash"
    if value in ("room_transfer", "room transfer"):
        return "room_transfer"
    # Historical ledger rows only — not offered for new settlements.
    if value == "credit":
        return "credit"
    return None


def _parse_pos_payment_splits(raw_splits, target_total):
    """Validate payment_splits the same way Room Transfer Clear Payment does."""
    target = _pos_money(target_total)
    if target < 0:
        raise ValueError("Bill total cannot be negative.")
    if not isinstance(raw_splits, list) or not raw_splits:
        if target <= 0:
            return [{"payment_method": "cash", "amount": 0.0, "transaction_id": ""}]
        raise ValueError("Add at least one payment mode.")

    parsed = []
    seen = set()
    for raw in raw_splits:
        if not isinstance(raw, dict):
            raise ValueError("Each payment split must be an object.")
        method = _normalize_pos_payment_method(raw.get("payment_method"))
        allowed = {key for key, _label in POS_PAYMENT_METHODS}
        if not method or method not in allowed:
            raise ValueError("Select a valid payment mode for each row.")
        if method in seen:
            raise ValueError("Each payment mode can only be used once.")
        seen.add(method)
        amount = _pos_money(raw.get("amount"))
        if amount <= 0 and target > 0:
            raise ValueError("Enter a valid amount for each payment mode.")
        if amount < 0:
            raise ValueError("Payment amounts cannot be negative.")
        txn = str(raw.get("transaction_id") or "").strip()
        if method in POS_PAYMENT_METHODS_REQUIRING_TXN and not txn:
            raise ValueError("Transaction ID is required for bank transfer.")
        if method not in POS_PAYMENT_METHODS_REQUIRING_TXN:
            txn = ""
        parsed.append(
            {
                "payment_method": method,
                "amount": amount,
                "transaction_id": txn,
            }
        )

    split_total = _pos_money(sum(item["amount"] for item in parsed))
    if abs(split_total - target) > 0.001:
        raise ValueError("Modes total must equal the bill total before settling.")
    return parsed


def settle_pos_invoice(
    conn,
    invoice_id,
    *,
    payment_splits=None,
    payment_date=None,
    notes="",
    user_id=None,
    hotel_room_id=None,
):
    """Record payment (with optional split modes) and close the bill / free table.

    Mirrors Sales Analytics → Room Transfer → Clear Payment: modes must sum to
    the bill total; bank transfer requires a transaction id.

    When any split uses room_transfer, hotel_room_id must reference an occupied
    hotel room; the room-transfer amount is posted onto that stay's folio.
    """
    ensure_pos_schema(conn)
    try:
        invoice_id = int(invoice_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid invoice id.") from exc

    row = conn.execute(
        """
        SELECT id, status, grand_total, settled_at, outlet, order_no
        FROM pos_invoices
        WHERE id = ? AND is_active = 1
        """,
        (invoice_id,),
    ).fetchone()
    if not row:
        raise ValueError("Invoice not found.")
    if str(row["status"] or "").strip().lower() == "closed":
        raise ValueError("This bill is already settled.")

    target = _pos_money(row["grand_total"])
    splits = _parse_pos_payment_splits(payment_splits, target)
    room_transfer_total = round(
        sum(
            float(s["amount"])
            for s in splits
            if s.get("payment_method") == "room_transfer"
        ),
        2,
    )
    hotel_room_id = str(hotel_room_id or "").strip()
    if room_transfer_total > 0 and not hotel_room_id:
        raise ValueError("Select a hotel room for Room Transfer payment.")

    pay_date = str(payment_date or "").strip()
    if not pay_date:
        pay_date = conn.execute("SELECT date('now','localtime')").fetchone()[0]
    notes_clean = str(notes or "").strip()

    # Replace any prior draft payments (should be empty for open bills).
    conn.execute("DELETE FROM pos_invoice_payments WHERE invoice_id = ?", (invoice_id,))
    for split in splits:
        conn.execute(
            """
            INSERT INTO pos_invoice_payments
                (invoice_id, payment_date, payment_method, amount, transaction_id, notes)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                invoice_id,
                pay_date,
                split["payment_method"],
                split["amount"],
                split["transaction_id"],
                notes_clean,
            ),
        )

    conn.execute(
        f"""
        UPDATE pos_invoices
        SET payment_notes = ?, settled_at = {SQL_NOW}, updated_at = {SQL_NOW}
        WHERE id = ?
        """,
        (notes_clean, invoice_id),
    )

    invoice = close_pos_invoice_and_free_table(conn, invoice_id, user_id=user_id)
    payments = list_pos_invoice_payments(conn, invoice_id)
    invoice["payments"] = payments
    invoice["payment_notes"] = notes_clean

    if room_transfer_total > 0:
        outlet = str(row["outlet"] or (invoice or {}).get("outlet") or "")
        order_no = str(row["order_no"] or (invoice or {}).get("order_no") or "")
        kind = _hotel_folio_kind_for_outlet(outlet)
        label = {
            "restaurant_room_transfer": "Restaurant Room Transfer",
            "bar_room_transfer": "Bar Room Transfer",
            "other": "Room Transfer",
        }.get(kind, "Room Transfer")
        if order_no:
            label = f"{label} · {order_no}"
        folio_result = append_hotel_room_folio_charge(
            conn,
            hotel_room_id,
            amount=room_transfer_total,
            kind=kind,
            label=label,
            source="pos",
            invoice_id=str(invoice_id),
            outlet=outlet,
            note=notes_clean,
        )
        invoice["hotel_room"] = folio_result.get("room")
        invoice["folio_charge"] = folio_result.get("charge")
    return invoice


def list_pos_invoice_payments(conn, invoice_id):
    ensure_pos_schema(conn)
    try:
        invoice_id = int(invoice_id)
    except (TypeError, ValueError):
        return []
    rows = conn.execute(
        """
        SELECT id, payment_date, payment_method, amount, transaction_id, notes, created_at
        FROM pos_invoice_payments
        WHERE invoice_id = ?
        ORDER BY id ASC
        """,
        (invoice_id,),
    ).fetchall()
    out = []
    for row in rows:
        method = row["payment_method"] or "cash"
        out.append(
            {
                "id": row["id"],
                "payment_date": row["payment_date"] or "",
                "payment_method": method,
                "payment_method_label": POS_PAYMENT_METHOD_LABELS.get(method, method),
                "amount": _pos_money(row["amount"]),
                "transaction_id": row["transaction_id"] or "",
                "notes": row["notes"] or "",
                "created_at": row["created_at"] or "",
            }
        )
    return out


def clear_all_pos_tables(conn, *, user_id=None, outlet=POS_OUTLET_RESTAURANT):
    """Bulk-free every table on the floor back to available (Tables page 'Clear
    all tables'). Also closes any dangling open dine-in bills tied to those
    tables so a later resume lookup can't resurrect a stale order."""
    ensure_pos_schema(conn)
    outlet = normalize_pos_outlet(outlet)
    layout = get_pos_floor_layout(conn, outlet)
    tables = layout.get("tables") or []
    closed_ids = []
    for t in tables:
        label = str(t.get("name") or "").strip()
        if label:
            open_rows = conn.execute(
                """
                SELECT id FROM pos_invoices
                WHERE is_active = 1 AND status = 'open' AND order_type = 'dine_in'
                  AND outlet = ?
                  AND LOWER(table_label) = LOWER(?)
                """,
                (outlet, label),
            ).fetchall()
            for open_row in open_rows:
                closed_ids.append(int(open_row["id"]))
            conn.execute(
                f"""
                UPDATE pos_invoices SET status = 'closed', updated_at = {SQL_NOW}
                WHERE is_active = 1 AND status = 'open' AND order_type = 'dine_in'
                  AND outlet = ?
                  AND LOWER(table_label) = LOWER(?)
                """,
                (outlet, label),
            )
        t["status"] = "available"
        t["mergeGroupId"] = None
        t["mergePrimary"] = False
    if closed_ids:
        try:
            from stores import deduct_stock_for_pos_invoice

            for inv_id in closed_ids:
                try:
                    deduct_stock_for_pos_invoice(conn, inv_id, user_id=user_id)
                except Exception:
                    import logging

                    logging.getLogger(__name__).exception(
                        "POS stock deduction failed for invoice_id=%s during clear-all",
                        inv_id,
                    )
        except Exception:
            import logging

            logging.getLogger(__name__).exception(
                "POS stock deduction unavailable during clear-all"
            )
    return save_pos_floor_layout(conn, layout.get("areas") or [], tables, outlet)


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

    outlet = normalize_pos_outlet(payload.get("outlet") or payload.get("posOutlet"))
    order_no = " ".join(str(payload.get("orderNo") or payload.get("order_no") or "").split()).strip()
    if not order_no and outlet not in (POS_OUTLET_RESTAURANT, POS_OUTLET_BAR):
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

    # Restaurant: SPC/{n}/{FY}. Bar: INV/{n}/{FY}.
    # Mint when empty or offline hex draft; keep client PREFIX/{n}/{fy} and legacy ORD-*.
    if outlet in (POS_OUTLET_RESTAURANT, POS_OUTLET_BAR):
        existing_probe = None
        if order_no:
            existing_probe = conn.execute(
                """
                SELECT id FROM pos_invoices
                WHERE order_no = ? AND is_active = 1
                LIMIT 1
                """,
                (order_no,),
            ).fetchone()
        if not existing_probe and (
            not order_no or is_provisional_pos_order_no(order_no, outlet)
        ):
            if outlet == POS_OUTLET_BAR:
                order_no = allocate_pos_bar_order_no(conn, order_date)
            else:
                order_no = allocate_pos_restaurant_order_no(conn, order_date)

    customer_mobile = "".join(
        ch for ch in str(payload.get("customerMobile") or payload.get("customer_mobile") or "") if ch.isdigit()
    )[:10]
    table_label = str(payload.get("table") or payload.get("table_label") or "").strip()
    captain = str(payload.get("captain") or "").strip()
    notes = str(payload.get("notes") or "").strip()
    if order_type == "dine_in" and not table_label:
        raise ValueError("Select a table before saving a dine-in order.")
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
    raw_discount_uids = payload.get("discountLineUids")
    if raw_discount_uids is None:
        raw_discount_uids = payload.get("discount_line_uids")
    if isinstance(raw_discount_uids, str):
        discount_line_uids = _parse_discount_line_uids(raw_discount_uids)
    elif isinstance(raw_discount_uids, (list, tuple)):
        discount_line_uids = _parse_discount_line_uids(json.dumps(list(raw_discount_uids)))
    else:
        discount_line_uids = []
    discount_reason = str(
        payload.get("discountReason") or payload.get("discount_reason") or ""
    ).strip()[:200]

    subtotal = _pos_money(totals.get("subtotal"))
    discount_amount = _pos_money(totals.get("discount"))
    gst_amount = _pos_money(totals.get("gst"))
    vat_amount = _pos_money(totals.get("vat"))
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
        line_notes = " ".join(str(line.get("notes") or "").split()).strip()[:200]
        line_uid = str(line.get("uid") or line.get("line_uid") or "").strip()
        if not line_uid:
            line_uid = f"L{idx + 1}"
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
                "notes": line_notes,
                "line_uid": line_uid,
            }
        )
    if not normalized_lines:
        raise ValueError("Add at least one item before saving.")
    if subtotal <= 0:
        subtotal = _pos_money(computed_subtotal)

    # Keep only uids that still exist on this save; empty = whole-bill discount.
    live_uids = {line["line_uid"] for line in normalized_lines}
    discount_line_uids = [uid for uid in discount_line_uids if uid in live_uids]
    # Selecting every line is equivalent to whole-bill scope.
    if discount_line_uids and len(discount_line_uids) >= len(normalized_lines):
        discount_line_uids = []
    discount_line_uids_json = _serialize_discount_line_uids(discount_line_uids)
    if discount_amount <= 0 or discount_value <= 0:
        discount_reason = ""
    elif discount_type == "pct" and discount_value <= 15:
        discount_reason = ""
    elif discount_type == "inr" and subtotal > 0:
        effective_pct = (discount_amount / subtotal) * 100.0
        if effective_pct <= 15:
            discount_reason = ""

    # A KOT send persists the order and marks lines as sent to the kitchen.
    # Occupancy is claimed on any dine-in save with a table (see below).
    kot_send = bool(payload.get("kotSend") or payload.get("kot_send"))

    existing = conn.execute(
        """
        SELECT id, kot_sent, first_kot_at, customer_bill_sent, customer_bill_at, outlet
        FROM pos_invoices
        WHERE order_no = ? AND is_active = 1
        LIMIT 1
        """,
        (order_no,),
    ).fetchone()
    if existing:
        existing_outlet = normalize_pos_outlet(
            existing["outlet"] if "outlet" in existing.keys() else None
        )
        # Never rewrite a Restaurant bill from Bar (or vice versa) — order numbers
        # are globally unique, so a mismatched outlet is a conflict, not an update.
        if existing_outlet != outlet:
            raise ValueError(
                f'Order "{order_no}" already exists for {existing_outlet}. '
                "Use a new order number or open that outlet's POS."
            )
        outlet = existing_outlet

    # A brand-new dine-in bill must not be openable against a table the Tables
    # page already shows as occupied — same floor/tables source of truth used
    # there. Editing an already-saved order (existing order_no) is a resume of
    # that same bill, so it is never blocked here.
    if not existing and table_label and order_type == "dine_in":
        floor_status = _pos_floor_table_status(get_pos_floor_layout(conn, outlet), table_label)
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
    if was_bill_sent:
        raise ValueError("Invoice already generated; settle the bill instead.")
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
                discount_line_uids = ?,
                discount_reason = ?,
                subtotal = ?,
                discount_amount = ?,
                gst_amount = ?,
                vat_amount = ?,
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
                discount_line_uids_json,
                discount_reason,
                subtotal,
                discount_amount,
                gst_amount,
                vat_amount,
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
                tip_amount, coupon_code, discount_line_uids, discount_reason,
                subtotal, discount_amount, gst_amount, vat_amount, service_amount, tip,
                round_off, grand_total, created_by, status, kot_sent, first_kot_at,
                customer_bill_sent, customer_bill_at, outlet,
                is_active, created_at, updated_at
            ) VALUES (
                ?, ?, ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?,
                ?, ?, ?, 'open', ?, ?,
                ?, ?, ?,
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
                discount_line_uids_json,
                discount_reason,
                subtotal,
                discount_amount,
                gst_amount,
                vat_amount,
                service_amount,
                tip,
                round_off,
                grand_total,
                creator,
                next_kot_sent,
                first_kot_at,
                next_bill_sent,
                customer_bill_at,
                outlet,
            ),
        )
        invoice_id = int(cursor.lastrowid)

    for line in normalized_lines:
        conn.execute(
            """
            INSERT INTO pos_invoice_lines (
                invoice_id, sort_order, menu_item_id, name, variant, rate, qty, line_total, sent_qty, notes, line_uid
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                line.get("notes") or "",
                line.get("line_uid") or "",
            ),
        )

    # Claim the table while the dine-in bill is in progress. Generate Invoice
    # (customer_bill_sent) frees it immediately so the next party can sit —
    # Settle Bill can finish without holding the floor tile.
    if table_label and order_type == "dine_in":
        if next_bill_sent:
            _pos_mark_table_available(conn, table_label, outlet)
        else:
            _pos_mark_table_occupied(conn, table_label, outlet)

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
    invoice = _pos_invoice_row_to_dict(conn, row, include_lines=True)
    if invoice:
        _apply_pos_invoice_payment_modes(conn, invoice)
        invoice["payments"] = list_pos_invoice_payments(conn, invoice_id)
    return invoice


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
    settlement=None,
    q="",
    outlet=None,
):
    """List active invoices with optional filters (newest first)."""
    ensure_pos_schema(conn)
    clauses = ["i.is_active = 1"]
    params = []
    if outlet is not None:
        clauses.append("i.outlet = ?")
        params.append(normalize_pos_outlet(outlet))
    if date_from:
        clauses.append("i.order_date >= ?")
        params.append(str(date_from))
    if date_to:
        clauses.append("i.order_date <= ?")
        params.append(str(date_to))
    if order_type and str(order_type).strip().lower() not in ("", "all"):
        clauses.append("i.order_type = ?")
        params.append(_normalize_pos_order_type(order_type))
    settlement_key = str(settlement or "").strip().lower()
    if settlement_key == "settled":
        clauses.append(
            """
            (
                EXISTS (
                    SELECT 1 FROM pos_invoice_payments p WHERE p.invoice_id = i.id
                )
                OR TRIM(COALESCE(i.settled_at, '')) != ''
            )
            """
        )
    elif settlement_key == "unsettled":
        clauses.append(
            """
            NOT EXISTS (
                SELECT 1 FROM pos_invoice_payments p WHERE p.invoice_id = i.id
            )
            AND TRIM(COALESCE(i.settled_at, '')) = ''
            """
        )
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
    invoices = [_pos_invoice_row_to_dict(conn, row, include_lines=False) for row in rows]
    return _enrich_pos_invoices_payment_modes(conn, invoices)


def list_pos_today_invoices(conn, *, today=None, outlet=POS_OUTLET_RESTAURANT):
    """Active POS invoices for the business day — Tables Invoice hub.

    Includes dine-in and other order types created today (open and closed).
    Newest first via list_pos_invoices ordering (saved_at / id).
    """
    if today is None:
        today = datetime.now().strftime("%Y-%m-%d")
    else:
        today = str(today)
    invoices = list_pos_invoices(
        conn, date_from=today, date_to=today, outlet=normalize_pos_outlet(outlet)
    )
    unsettled = pos_unsettled_today_summary_from_invoices(invoices)
    sales_total = 0.0
    for inv in invoices:
        sales_total += _pos_money(inv.get("grand_total"))
    return {
        "date": today,
        "invoice_count": len(invoices),
        "invoices": invoices,
        "sales_total": _pos_money(sales_total),
        "sales_count": len(invoices),
        "unsettled_count": unsettled["unsettled_count"],
        "unsettled_total": unsettled["unsettled_total"],
    }


def pos_unsettled_today_summary_from_invoices(invoices):
    """Sum open (not closed) invoice totals from a today-invoice list."""
    total = 0.0
    count = 0
    for inv in invoices or []:
        status = str((inv or {}).get("status") or "open").lower()
        if status == "closed":
            continue
        count += 1
        total += _pos_money((inv or {}).get("grand_total"))
    return {
        "unsettled_count": count,
        "unsettled_total": _pos_money(total),
    }


def pos_unsettled_today_summary(conn, *, today=None, outlet=POS_OUTLET_RESTAURANT):
    """Today's open POS invoices — count + grand total for Tables KPI."""
    payload = list_pos_today_invoices(conn, today=today, outlet=outlet)
    return {
        "unsettled_count": payload["unsettled_count"],
        "unsettled_total": payload["unsettled_total"],
    }


def pos_today_sales_summary(conn, *, today=None, outlet=POS_OUTLET_RESTAURANT):
    """Today's POS invoice sales — grand total + count for Tables KPI."""
    payload = list_pos_today_invoices(conn, today=today, outlet=outlet)
    return {
        "sales_total": payload["sales_total"],
        "sales_count": payload["sales_count"],
        "unsettled_count": payload["unsettled_count"],
        "unsettled_total": payload["unsettled_total"],
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
    if "pack_label" not in indent_line_cols:
        cursor.execute(
            "ALTER TABLE store_indent_lines ADD COLUMN pack_label TEXT NOT NULL DEFAULT ''"
        )
    if "pack_qty_in_base" not in indent_line_cols:
        cursor.execute(
            "ALTER TABLE store_indent_lines ADD COLUMN pack_qty_in_base REAL"
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
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS store_product_variants (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id         INTEGER NOT NULL,
            label              TEXT    NOT NULL,
            qty_in_base        REAL    NOT NULL,
            approximate_price  REAL,
            sort_order         INTEGER NOT NULL DEFAULT 0,
            is_active          INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY (product_id) REFERENCES store_products(id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_store_product_variants_product
        ON store_product_variants(product_id, is_active, sort_order, id)
    """)
    pr_line_cols = {
        row[1]
        for row in cursor.execute("PRAGMA table_info(store_purchase_request_lines)").fetchall()
    }
    if "pack_label" not in pr_line_cols:
        cursor.execute(
            "ALTER TABLE store_purchase_request_lines ADD COLUMN pack_label TEXT NOT NULL DEFAULT ''"
        )
    if "pack_qty_in_base" not in pr_line_cols:
        cursor.execute(
            "ALTER TABLE store_purchase_request_lines ADD COLUMN pack_qty_in_base REAL"
        )
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
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS store_stock_audits (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            outlet       TEXT    NOT NULL,
            status       TEXT    NOT NULL DEFAULT 'open',
            label        TEXT    NOT NULL DEFAULT '',
            started_at   TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            completed_at TEXT,
            started_by   INTEGER,
            FOREIGN KEY (started_by) REFERENCES users(id)
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_store_stock_audits_outlet_status
        ON store_stock_audits(outlet, status, started_at DESC)
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS store_stock_audit_lines (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            audit_id       INTEGER NOT NULL,
            stock_item_id  INTEGER,
            item_name      TEXT    NOT NULL,
            unit           TEXT    NOT NULL DEFAULT 'pcs',
            category_name  TEXT    NOT NULL DEFAULT '',
            system_qty     REAL    NOT NULL DEFAULT 0,
            actual_qty     REAL,
            variance_qty   REAL,
            variance_value REAL,
            status         TEXT    NOT NULL DEFAULT 'pending',
            reason         TEXT    NOT NULL DEFAULT '',
            remarks        TEXT    NOT NULL DEFAULT '',
            unit_cost      REAL,
            verified_at    TEXT,
            verified_by    INTEGER,
            FOREIGN KEY (audit_id) REFERENCES store_stock_audits(id) ON DELETE CASCADE,
            FOREIGN KEY (verified_by) REFERENCES users(id)
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_store_stock_audit_lines_audit
        ON store_stock_audit_lines(audit_id, status, id)
    """)
    conn.commit()


def _seed_store_product_units(cursor):
    """Seed default product units used on Product Master (idempotent)."""
    defaults = ("kg", "gram", "pcs", "liter", "mL", "bunch", "bottle", "pack")
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
                ("Banana", "pcs"),
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


# ---------------------------------------------------------------------------
# Hotel Rooms floor board (front office occupancy — not Sales Update Hotel)
# ---------------------------------------------------------------------------

HOTEL_ROOM_STATUSES = (
    "vacant",
    "occupied",
    "reserved",
    "dirty",
    "out_of_order",
)

HOTEL_ROOM_STATUS_LABELS = {
    "vacant": "Vacant",
    "occupied": "Occupied",
    "reserved": "Reserved",
    "dirty": "Dirty",
    "out_of_order": "Out of order",
}

HOTEL_ROOM_TYPE_LABELS = {
    "premium_without_balcony": "Premium Room",
    "premium_deluxe_balcony": "Deluxe with Balcony",
    "premium_suite_tub": "Suite Room",
}

# Seed inventory from ROOM DETAILS spreadsheet (hardcoded — no Excel at runtime).
_HOTEL_ROOMS_SEED_SPEC = (
    # (room_number, room_type_key)
    ("101", "premium_deluxe_balcony"),
    ("102", "premium_without_balcony"),
    ("103", "premium_deluxe_balcony"),
    ("104", "premium_deluxe_balcony"),
    ("105", "premium_without_balcony"),
    ("106", "premium_deluxe_balcony"),
    ("201", "premium_deluxe_balcony"),
    ("202", "premium_without_balcony"),
    ("203", "premium_deluxe_balcony"),
    ("204", "premium_deluxe_balcony"),
    ("205", "premium_without_balcony"),
    ("206", "premium_deluxe_balcony"),
    ("207", "premium_suite_tub"),
    ("301", "premium_deluxe_balcony"),
    ("302", "premium_without_balcony"),
    ("303", "premium_deluxe_balcony"),
    ("304", "premium_deluxe_balcony"),
    ("305", "premium_without_balcony"),
    ("306", "premium_deluxe_balcony"),
    ("307", "premium_suite_tub"),
)


def ensure_hotel_rooms_schema(conn):
    """Create singleton hotel_rooms_layout JSON table if missing."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS hotel_rooms_layout (
            id         INTEGER PRIMARY KEY CHECK (id = 1),
            payload    TEXT    NOT NULL,
            updated_at TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS hotel_guest_profiles (
            mobile     TEXT PRIMARY KEY,
            profile    TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS hotel_room_invoice_seq (
            fiscal_year TEXT PRIMARY KEY,
            last_seq    INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS hotel_settings (
            id         INTEGER PRIMARY KEY CHECK (id = 1),
            payload    TEXT    NOT NULL DEFAULT '{}',
            updated_at TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        )
        """
    )
    ensure_hotel_room_invoices_schema(conn)


HOTEL_DEFAULT_CGST_PCT = 2.5
HOTEL_DEFAULT_UGST_PCT = 2.5

HOTEL_DEFAULT_TARIFF_RATES = {
    "premium_without_balcony": 3500.0,
    "premium_deluxe_balcony": 4500.0,
    "premium_suite_tub": 7500.0,
    "extra_mattress": 1000.0,
    "early_checkin": 500.0,
    "late_checkout": 500.0,
    "airport_pickup": 1500.0,
}


def get_hotel_settings(conn):
    """Return hotel settings JSON blob (independent from POS outlet settings)."""
    ensure_hotel_rooms_schema(conn)
    row = conn.execute("SELECT payload FROM hotel_settings WHERE id = 1").fetchone()
    if not row:
        return {}
    try:
        parsed = json.loads(row["payload"] or "{}")
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def save_hotel_settings(conn, settings):
    """Replace hotel settings JSON blob."""
    ensure_hotel_rooms_schema(conn)
    if not isinstance(settings, dict):
        settings = {}
    blob = json.dumps(settings, ensure_ascii=False, separators=(",", ":"))
    conn.execute(
        f"""
        INSERT INTO hotel_settings (id, payload, updated_at)
        VALUES (1, ?, {SQL_NOW})
        ON CONFLICT(id) DO UPDATE SET
            payload = excluded.payload,
            updated_at = {SQL_NOW}
        """,
        (blob,),
    )
    return settings


def get_hotel_tax_rates(conn):
    """Return CGST/UGST fractions (0–1) from Hotel Settings → Taxes."""
    settings = get_hotel_settings(conn)
    values = _pos_settings_panel_values(settings, "taxes")
    cgst_pct = _pos_settings_pct(values, "cgst_pct", 0, HOTEL_DEFAULT_CGST_PCT)
    ugst_pct = _pos_settings_pct(values, "ugst_pct", 1, HOTEL_DEFAULT_UGST_PCT)
    return {
        "cgst_pct": cgst_pct,
        "ugst_pct": ugst_pct,
        "cgst": round(cgst_pct / 100.0, 6),
        "ugst": round(ugst_pct / 100.0, 6),
    }


def _hotel_settings_money(values, key, default_amount):
    """Parse a non-negative money amount from settings panel values."""
    if not isinstance(values, dict):
        return float(default_amount)
    field = values.get(key)
    raw = None
    if isinstance(field, dict):
        raw = field.get("value")
    elif field is not None:
        raw = field
    try:
        amount = float(raw)
    except (TypeError, ValueError):
        return float(default_amount)
    if amount != amount or amount < 0:
        return float(default_amount)
    return round(amount, 2)


def get_hotel_tariff_rates(conn):
    """Return default hotel tariffs from Hotel Settings → Tariff."""
    settings = get_hotel_settings(conn)
    values = _pos_settings_panel_values(settings, "tariff")
    defaults = HOTEL_DEFAULT_TARIFF_RATES
    return {
        "premium_without_balcony": _hotel_settings_money(
            values, "rate_premium_without_balcony", defaults["premium_without_balcony"]
        ),
        "premium_deluxe_balcony": _hotel_settings_money(
            values, "rate_premium_deluxe_balcony", defaults["premium_deluxe_balcony"]
        ),
        "premium_suite_tub": _hotel_settings_money(
            values, "rate_premium_suite_tub", defaults["premium_suite_tub"]
        ),
        "extra_mattress": _hotel_settings_money(
            values, "rate_extra_mattress", defaults["extra_mattress"]
        ),
        "early_checkin": _hotel_settings_money(
            values, "rate_early_checkin", defaults["early_checkin"]
        ),
        "late_checkout": _hotel_settings_money(
            values, "rate_late_checkout", defaults["late_checkout"]
        ),
        "airport_pickup": _hotel_settings_money(
            values, "rate_airport_pickup", defaults["airport_pickup"]
        ),
    }


def _hotel_tax_rates_or_default(tax_rates=None):
    if isinstance(tax_rates, dict) and "cgst" in tax_rates and "ugst" in tax_rates:
        try:
            cgst = float(tax_rates["cgst"])
            ugst = float(tax_rates["ugst"])
        except (TypeError, ValueError):
            cgst = HOTEL_DEFAULT_CGST_PCT / 100.0
            ugst = HOTEL_DEFAULT_UGST_PCT / 100.0
        if cgst != cgst or cgst < 0:
            cgst = HOTEL_DEFAULT_CGST_PCT / 100.0
        if ugst != ugst or ugst < 0:
            ugst = HOTEL_DEFAULT_UGST_PCT / 100.0
        return {"cgst": cgst, "ugst": ugst}
    return {
        "cgst": HOTEL_DEFAULT_CGST_PCT / 100.0,
        "ugst": HOTEL_DEFAULT_UGST_PCT / 100.0,
    }


def ensure_hotel_room_invoices_schema(conn):
    """Archive of generated room stay invoices (survives checkout)."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS hotel_room_invoices (
            invoice_number       TEXT PRIMARY KEY,
            room_id              TEXT NOT NULL DEFAULT '',
            room_number          TEXT NOT NULL DEFAULT '',
            room_type_label      TEXT NOT NULL DEFAULT '',
            guest_name           TEXT NOT NULL DEFAULT '',
            booking_number       TEXT NOT NULL DEFAULT '',
            check_in_date        TEXT NOT NULL DEFAULT '',
            check_out_date       TEXT NOT NULL DEFAULT '',
            invoice_generated_at TEXT NOT NULL DEFAULT '',
            estimated_total      REAL NOT NULL DEFAULT 0,
            advance_paid         REAL NOT NULL DEFAULT 0,
            balance_amount       REAL NOT NULL DEFAULT 0,
            status               TEXT NOT NULL DEFAULT 'open',
            payload_json         TEXT NOT NULL DEFAULT '{}',
            updated_at           TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_hotel_room_invoices_generated
        ON hotel_room_invoices(invoice_generated_at DESC)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_hotel_room_invoices_status
        ON hotel_room_invoices(status)
        """
    )


_HOTEL_RM_INVOICE_RE = re.compile(r"^HBE/RM/(\d+)/(\d{4}-\d{2})$", re.IGNORECASE)
HOTEL_ROOM_PAYMENT_METHODS = ("cash", "upi", "card", "bank_transfer", "credit")
HOTEL_ROOM_PAYMENT_METHOD_LABELS = {
    "cash": "Cash",
    "upi": "UPI",
    "card": "Card",
    "bank_transfer": "Bank Transfer",
    "credit": "Credit",
}


def next_hotel_room_invoice_seq(conn, fiscal_year):
    """Next HBE/RM sequence for the given Indian fiscal year."""
    ensure_hotel_rooms_schema(conn)
    fy = str(fiscal_year or "").strip()
    if not fy:
        fy = indian_fiscal_year_label()
    row = conn.execute(
        "SELECT last_seq FROM hotel_room_invoice_seq WHERE fiscal_year = ?",
        (fy,),
    ).fetchone()
    current = int(row["last_seq"]) if row else 0
    nxt = current + 1
    conn.execute(
        """
        INSERT INTO hotel_room_invoice_seq (fiscal_year, last_seq)
        VALUES (?, ?)
        ON CONFLICT(fiscal_year) DO UPDATE SET last_seq = excluded.last_seq
        """,
        (fy, nxt),
    )
    return nxt


def allocate_hotel_room_invoice_number(conn, when=None):
    """Allocate HBE/RM/{n}/{fy} for a room stay invoice."""
    fy = indian_fiscal_year_label(when)
    seq = next_hotel_room_invoice_seq(conn, fy)
    return f"HBE/RM/{seq}/{fy}"


def _hotel_invoice_status(balance_amount):
    bal = round(float(balance_amount or 0), 2)
    return "settled" if bal <= 0.009 else "open"


def _hotel_invoice_guest_name(stay):
    if not isinstance(stay, dict):
        return ""
    name = _hotel_str(stay.get("guestName") or stay.get("guest_name"), 160)
    if name:
        return name
    first = _hotel_str(stay.get("firstName") or stay.get("first_name"), 80)
    last = _hotel_str(stay.get("lastName") or stay.get("last_name"), 80)
    return f"{first} {last}".strip()


def upsert_hotel_room_invoice_from_room(conn, room):
    """Persist / refresh a ledger row from an occupied (or snapshot) room dict."""
    if not isinstance(room, dict):
        return None
    room = dict(room)
    # Prefer peers from the live layout when available so invoice archives
    # capture every merged room number before checkout demerges them.
    try:
        layout_rooms = get_hotel_rooms_layout(conn).get("rooms") or []
    except Exception:
        layout_rooms = None
    _hotel_snapshot_merge_rooms_on_stay(room, layout_rooms)
    stay = room.get("stay") if isinstance(room.get("stay"), dict) else None
    if not stay:
        return None
    stay = _normalize_hotel_room_stay(stay)
    room["stay"] = stay
    invoice_number = _hotel_str(stay.get("invoiceNumber") or stay.get("invoice_number"), 60)
    if not invoice_number:
        return None
    ensure_hotel_room_invoices_schema(conn)

    estimated = round(float(stay.get("estimatedTotal") or 0), 2)
    advance = round(float(stay.get("advancePaid") or 0), 2)
    balance = round(float(stay.get("balanceAmount") or 0), 2)
    status = _hotel_invoice_status(balance)
    generated_at = _hotel_str(
        stay.get("invoiceGeneratedAt") or stay.get("invoice_generated_at"), 40
    ) or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    room_number_display = _hotel_str(
        stay.get("mergeRoomLabel") or room.get("number"), 80
    ) or _hotel_str(room.get("number"), 20)
    payload = {
        "id": room.get("id") or "",
        "number": room.get("number") or "",
        "roomType": room.get("roomType") or room.get("room_type") or "",
        "roomTypeLabel": room.get("roomTypeLabel")
        or room.get("room_type_label")
        or "",
        "floorId": room.get("floorId") or room.get("floor_id") or "",
        "status": room.get("status") or "occupied",
        "mergeRoomNumbers": list(stay.get("mergeRoomNumbers") or []),
        "mergeRoomLabel": stay.get("mergeRoomLabel") or "",
        "stay": stay,
    }
    blob = json.dumps(payload, separators=(",", ":"))
    conn.execute(
        """
        INSERT INTO hotel_room_invoices (
            invoice_number, room_id, room_number, room_type_label,
            guest_name, booking_number, check_in_date, check_out_date,
            invoice_generated_at, estimated_total, advance_paid, balance_amount,
            status, payload_json, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now','localtime'))
        ON CONFLICT(invoice_number) DO UPDATE SET
            room_id = excluded.room_id,
            room_number = excluded.room_number,
            room_type_label = excluded.room_type_label,
            guest_name = excluded.guest_name,
            booking_number = excluded.booking_number,
            check_in_date = excluded.check_in_date,
            check_out_date = excluded.check_out_date,
            invoice_generated_at = COALESCE(
                NULLIF(excluded.invoice_generated_at, ''),
                hotel_room_invoices.invoice_generated_at
            ),
            estimated_total = excluded.estimated_total,
            advance_paid = excluded.advance_paid,
            balance_amount = excluded.balance_amount,
            status = excluded.status,
            payload_json = excluded.payload_json,
            updated_at = datetime('now','localtime')
        """,
        (
            invoice_number,
            _hotel_str(room.get("id"), 40),
            room_number_display,
            _hotel_str(
                room.get("roomTypeLabel") or room.get("room_type_label"), 80
            ),
            _hotel_invoice_guest_name(stay),
            _hotel_str(stay.get("bookingNumber") or stay.get("booking_number"), 40),
            _hotel_str(stay.get("checkInDate") or stay.get("check_in_date"), 10),
            _hotel_str(stay.get("checkOutDate") or stay.get("check_out_date"), 10),
            generated_at,
            estimated,
            advance,
            balance,
            status,
            blob,
        ),
    )
    return invoice_number


def backfill_hotel_room_invoices_from_layout(conn):
    """Upsert any in-layout stays that already have invoice numbers."""
    ensure_hotel_room_invoices_schema(conn)
    layout = get_hotel_rooms_layout(conn)
    count = 0
    for room in layout.get("rooms") or []:
        if not isinstance(room, dict):
            continue
        stay = room.get("stay") if isinstance(room.get("stay"), dict) else None
        if not stay:
            continue
        if not (stay.get("invoiceNumber") or stay.get("invoice_number")):
            continue
        if upsert_hotel_room_invoice_from_room(conn, room):
            count += 1
    return count


def _hotel_invoice_row_to_dict(row):
    if not row:
        return None
    item = dict(row)
    item["estimated_total"] = round(float(item.get("estimated_total") or 0), 2)
    item["advance_paid"] = round(float(item.get("advance_paid") or 0), 2)
    item["balance_amount"] = round(float(item.get("balance_amount") or 0), 2)
    item["status"] = "settled" if item.get("status") == "settled" else "open"
    return item


def list_hotel_room_invoices(
    conn,
    *,
    q="",
    status="",
    date_from=None,
    date_to=None,
    limit=500,
):
    """List archived room invoices newest-first."""
    ensure_hotel_room_invoices_schema(conn)
    backfill_hotel_room_invoices_from_layout(conn)

    clauses = []
    params = []
    status_key = str(status or "").strip().lower()
    if status_key in ("open", "settled"):
        clauses.append("status = ?")
        params.append(status_key)
    if date_from:
        clauses.append("substr(invoice_generated_at, 1, 10) >= ?")
        params.append(str(date_from)[:10])
    if date_to:
        clauses.append("substr(invoice_generated_at, 1, 10) <= ?")
        params.append(str(date_to)[:10])
    needle = str(q or "").strip().lower()
    if needle:
        clauses.append(
            """
            (
              lower(invoice_number) LIKE ?
              OR lower(guest_name) LIKE ?
              OR lower(room_number) LIKE ?
              OR lower(booking_number) LIKE ?
              OR lower(room_type_label) LIKE ?
            )
            """
        )
        like = f"%{needle}%"
        params.extend([like, like, like, like, like])

    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = conn.execute(
        f"""
        SELECT invoice_number, room_id, room_number, room_type_label,
               guest_name, booking_number, check_in_date, check_out_date,
               invoice_generated_at, estimated_total, advance_paid,
               balance_amount, status, updated_at
        FROM hotel_room_invoices
        {where}
        ORDER BY invoice_generated_at DESC, invoice_number DESC
        LIMIT ?
        """,
        (*params, int(limit)),
    ).fetchall()
    return [_hotel_invoice_row_to_dict(row) for row in rows]


def hotel_room_invoice_kpis(rows):
    """KPI totals for invoice ledger rows."""
    total = len(rows or [])
    open_count = 0
    settled_count = 0
    outstanding = 0.0
    amount_sum = 0.0
    for row in rows or []:
        amount_sum += float(row.get("estimated_total") or 0)
        bal = float(row.get("balance_amount") or 0)
        if (row.get("status") or "") == "settled" or bal <= 0.009:
            settled_count += 1
        else:
            open_count += 1
            outstanding += bal
    return {
        "total": total,
        "open": open_count,
        "settled": settled_count,
        "outstanding": round(outstanding, 2),
        "amount_sum": round(amount_sum, 2),
    }


def get_hotel_room_invoice(conn, invoice_number):
    """Return ledger row + reconstructed room payload for print/view."""
    ensure_hotel_room_invoices_schema(conn)
    number = _hotel_str(invoice_number, 60)
    if not number:
        return None
    row = conn.execute(
        """
        SELECT invoice_number, room_id, room_number, room_type_label,
               guest_name, booking_number, check_in_date, check_out_date,
               invoice_generated_at, estimated_total, advance_paid,
               balance_amount, status, payload_json, updated_at
        FROM hotel_room_invoices
        WHERE invoice_number = ?
        """,
        (number,),
    ).fetchone()
    if not row:
        return None
    item = _hotel_invoice_row_to_dict(row)
    try:
        payload = json.loads(row["payload_json"] or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    stay = payload.get("stay") if isinstance(payload.get("stay"), dict) else {}
    merge_numbers = payload.get("mergeRoomNumbers") or stay.get("mergeRoomNumbers") or []
    if not isinstance(merge_numbers, list):
        merge_numbers = []
    merge_label = (
        payload.get("mergeRoomLabel")
        or stay.get("mergeRoomLabel")
        or ""
    )
    room = {
        "id": payload.get("id") or item.get("room_id") or "",
        "number": payload.get("number") or "",
        "roomType": payload.get("roomType") or "",
        "roomTypeLabel": payload.get("roomTypeLabel")
        or item.get("room_type_label")
        or "",
        "floorId": payload.get("floorId") or "",
        "status": payload.get("status") or "occupied",
        "mergeRoomNumbers": merge_numbers,
        "mergeRoomLabel": merge_label,
        "mergePartnerNumbers": [
            n for n in merge_numbers if str(n) != str(payload.get("number") or "")
        ],
        "mergeLabel": merge_label
        or (payload.get("number") or item.get("room_number") or ""),
        "stay": stay,
    }
    # Display label for UI when ledger column already stores "101 + 106".
    if merge_label:
        room["numberDisplay"] = merge_label
    elif item.get("room_number"):
        room["numberDisplay"] = item.get("room_number")
    item["room"] = room
    return item


def _normalize_hotel_payment_method(value):
    key = str(value or "").strip().lower().replace(" ", "_").replace("-", "_")
    if key in ("bank", "banktransfer", "neft", "rtgs", "imps"):
        key = "bank_transfer"
    if key in ("agent_credit", "agency_credit", "on_credit"):
        key = "credit"
    if key not in HOTEL_ROOM_PAYMENT_METHODS:
        return ""
    return key


def _hotel_stay_has_agency(stay):
    """True when an agency/agent is attached to the stay (enables Credit pay)."""
    if not isinstance(stay, dict):
        return False
    name = _hotel_str(stay.get("agencyName") or stay.get("agency_name"), 160)
    return bool(name)



def _hotel_floor_id_for_number(number):
    digits = re.sub(r"\D", "", str(number or ""))
    if not digits:
        return "floor-1"
    return f"floor-{digits[0]}"


def default_hotel_rooms_layout():
    """Build the seeded 3-floor / 20-room board from the spreadsheet inventory."""
    floors = [
        {"id": "floor-1", "name": "Floor 1"},
        {"id": "floor-2", "name": "Floor 2"},
        {"id": "floor-3", "name": "Floor 3"},
    ]
    rooms = []
    for number, type_key in _HOTEL_ROOMS_SEED_SPEC:
        rooms.append(
            {
                "id": f"room-{number}",
                "number": str(number),
                "floorId": _hotel_floor_id_for_number(number),
                "roomType": type_key,
                "roomTypeLabel": HOTEL_ROOM_TYPE_LABELS.get(type_key, type_key),
                "status": "vacant",
            }
        )
    return {"floors": floors, "rooms": rooms}


def _normalize_hotel_room_status(status):
    key = str(status or "").strip().lower().replace(" ", "_").replace("-", "_")
    if key in ("ooo", "out_of_service", "oos"):
        key = "out_of_order"
    if key in ("available", "free", "clean"):
        key = "vacant"
    if key not in HOTEL_ROOM_STATUSES:
        return "vacant"
    return key


def _hotel_room_has_inhouse_stay(room):
    """True when the room still has an in-house guest stay (not a bare reservation)."""
    if not isinstance(room, dict):
        return False
    stay = room.get("stay") if isinstance(room.get("stay"), dict) else None
    if not stay:
        return False
    # Explicit reservation inventory is not in-house yet.
    if _normalize_hotel_room_status(room.get("status")) == "reserved":
        return False
    if stay.get("checkedInAt") or stay.get("checked_in_at"):
        return True
    guest = _hotel_str(
        stay.get("guestName")
        or stay.get("guest_name")
        or " ".join(
            p
            for p in (
                stay.get("firstName") or stay.get("first_name") or "",
                stay.get("lastName") or stay.get("last_name") or "",
            )
            if p
        ),
        160,
    )
    check_in = _hotel_str(stay.get("checkInDate") or stay.get("check_in_date"), 10)
    if guest and check_in:
        return True
    if guest and (stay.get("folioCharges") or stay.get("payments")):
        return True
    # Merge role alone is not in-house — empty shells must not look Occupied.
    return False


_HOTEL_MERGE_SHARED_GUEST_KEYS = (
    "title",
    "firstName",
    "lastName",
    "guestName",
    "gender",
    "dateOfBirth",
    "nationality",
    "mobileCountry",
    "mobile",
    "email",
    "address",
    "city",
    "state",
    "country",
    "pin",
    "purposeOfVisit",
    "vipStatus",
    "returningGuest",
    "idType",
    "idNumber",
    "idIssueDate",
    "idExpiryDate",
    "idPlaceOfIssue",
    "idDocumentName",
    "idDocumentPath",
    "idDocumentMime",
    "agencyName",
    "agencyGst",
    "agencyAddress",
    "agencyBilling",
    "invoiceTo",
    "billingName",
    "profession",
    "company",
    "loyaltyNumber",
    "notes",
    "checkInDate",
    "checkInTime",
    "checkOutDate",
    "nights",
    "adults",
    "children",
    "bookingNumber",
    "bookingDate",
    "checkedInAt",
    "specialRequests",
    "additionalRequests",
    "additionalGuests",
)

_HOTEL_MERGE_SHARED_BILL_KEYS = (
    "ratePlan",
    "roomRate",
    "totalRate",
    "paymentMethod",
    "advancePaid",
    "checkInAdvancePaid",
    "paymentReference",
    "balanceAmount",
    "invoiceNumber",
    "invoiceGenerated",
    "invoiceGeneratedAt",
    "payments",
    "extraBedQty",
    "extraBedRate",
    "extraBedNights",
    "extraBedAmount",
    "extraBedNote",
    "earlyCheckinQty",
    "earlyCheckinRate",
    "earlyCheckinNights",
    "earlyCheckinAmount",
    "earlyCheckinNote",
    "lateCheckoutQty",
    "lateCheckoutRate",
    "lateCheckoutNights",
    "lateCheckoutAmount",
    "lateCheckoutNote",
    "folioCharges",
    "discountType",
    "discountValue",
    "discountAmount",
    "discountReason",
    "estimatedTotal",
)


def _hotel_stay_guest_richness(stay):
    if not isinstance(stay, dict):
        return 0
    score = 0
    if stay.get("guestName") or stay.get("firstName") or stay.get("lastName"):
        score += 20
    if stay.get("mobile"):
        score += 8
    if stay.get("checkInDate") or stay.get("check_in_date"):
        score += 8
    if stay.get("checkedInAt") or stay.get("checked_in_at"):
        score += 6
    if stay.get("bookingNumber") or stay.get("booking_number"):
        score += 4
    if stay.get("email"):
        score += 2
    folio = stay.get("folioCharges") or []
    if isinstance(folio, list) and folio:
        score += 10
    try:
        if float(stay.get("roomRate") or 0) > 0:
            score += 5
    except (TypeError, ValueError):
        pass
    try:
        if float(stay.get("estimatedTotal") or 0) > 0:
            score += 5
    except (TypeError, ValueError):
        pass
    return score


def _hotel_copy_stay_fields(dest, source, keys):
    if not isinstance(dest, dict) or not isinstance(source, dict):
        return dest
    for key in keys:
        val = source.get(key)
        if val in (None, "", [], {}):
            continue
        dest[key] = val
    return dest


def _hotel_sync_merge_group_shared_data(rooms):
    """Replicate guest identity across a merge group; keep bill money on primary.

    Every merged room should show the same customer details. Folio/payments stay
    on the billing primary; members keep mergeRole/billingRoomId.
    """
    if not isinstance(rooms, list):
        return
    groups = {}
    for room in rooms:
        if not isinstance(room, dict):
            continue
        gid = str(room.get("mergeGroupId") or "").strip()
        if not gid:
            continue
        groups.setdefault(gid, []).append(room)

    for peers in groups.values():
        if len(peers) < 2:
            continue
        primary = next((r for r in peers if r.get("mergePrimary")), None)
        if not primary:
            primary = peers[0]
            primary["mergePrimary"] = True
        source = max(
            peers,
            key=lambda r: (
                _hotel_stay_guest_richness(r.get("stay")),
                1 if r.get("id") == primary.get("id") else 0,
            ),
        )
        source_stay = source.get("stay") if isinstance(source.get("stay"), dict) else {}
        primary_stay = (
            dict(primary.get("stay"))
            if isinstance(primary.get("stay"), dict)
            else {}
        )
        _hotel_copy_stay_fields(primary_stay, source_stay, _HOTEL_MERGE_SHARED_GUEST_KEYS)
        # If the richest stay was a member that still held money (pre-absorb),
        # fold bill fields onto primary when primary is empty.
        if (
            _hotel_stay_guest_richness(source_stay)
            and source.get("id") != primary.get("id")
        ):
            primary_has_folio = bool(primary_stay.get("folioCharges"))
            source_has_folio = bool(source_stay.get("folioCharges"))
            try:
                primary_rate = float(primary_stay.get("roomRate") or 0)
            except (TypeError, ValueError):
                primary_rate = 0.0
            try:
                source_rate = float(source_stay.get("roomRate") or 0)
            except (TypeError, ValueError):
                source_rate = 0.0
            if not primary_has_folio and source_has_folio:
                _hotel_copy_stay_fields(
                    primary_stay, source_stay, _HOTEL_MERGE_SHARED_BILL_KEYS
                )
            elif primary_rate <= 0 and source_rate > 0:
                for key in ("roomRate", "totalRate", "nights", "ratePlan"):
                    if not primary_stay.get(key) and source_stay.get(key) not in (
                        None,
                        "",
                        [],
                        {},
                    ):
                        primary_stay[key] = source_stay.get(key)
        primary_stay["mergeRole"] = "primary"
        primary_stay["billingRoomId"] = ""
        primary["stay"] = primary_stay
        primary["mergePrimary"] = True
        force_occupied = any(
            _hotel_room_has_inhouse_stay(r)
            or _hotel_stay_guest_richness(r.get("stay")) > 0
            for r in peers
        ) or _hotel_stay_guest_richness(primary_stay) > 0
        if force_occupied:
            primary["status"] = "occupied"
        elif _normalize_hotel_room_status(primary.get("status")) == "occupied":
            primary["status"] = "vacant"

        for room in peers:
            if room.get("id") == primary.get("id"):
                continue
            member_stay = (
                dict(room.get("stay"))
                if isinstance(room.get("stay"), dict)
                else {}
            )
            _hotel_copy_stay_fields(
                member_stay, primary_stay, _HOTEL_MERGE_SHARED_GUEST_KEYS
            )
            member_stay["mergeRole"] = "member"
            member_stay["billingRoomId"] = str(primary.get("id") or "")
            # Display-only rate/nights so board/detail aren't blank; money is primary.
            for key in ("roomRate", "nights", "ratePlan", "adults", "children"):
                if primary_stay.get(key) not in (None, "", [], {}):
                    member_stay[key] = primary_stay.get(key)
            room["stay"] = member_stay
            room["mergePrimary"] = False
            room["mergeGroupId"] = primary.get("mergeGroupId")
            if force_occupied:
                room["status"] = "occupied"
            elif _normalize_hotel_room_status(room.get("status")) == "occupied":
                room["status"] = "vacant"


def _hotel_overlay_merge_shared_bill_view(room, rooms):
    """API/UI helper: members see the primary's folio and totals."""
    if not isinstance(room, dict):
        return room
    stay = room.get("stay") if isinstance(room.get("stay"), dict) else {}
    is_member = bool(
        room.get("isMergeMember")
        or stay.get("mergeRole") == "member"
        or stay.get("billingRoomId")
    )
    if not is_member:
        return room
    group_id = str(room.get("mergeGroupId") or "").strip()
    primary = None
    billing_id = str(stay.get("billingRoomId") or room.get("billingRoomId") or "").strip()
    for peer in rooms or []:
        if not isinstance(peer, dict):
            continue
        if billing_id and (
            peer.get("id") == billing_id or peer.get("number") == billing_id
        ):
            primary = peer
            break
        if group_id and str(peer.get("mergeGroupId") or "").strip() == group_id and peer.get(
            "mergePrimary"
        ):
            primary = peer
            break
    if not primary:
        return room
    pstay = primary.get("stay") if isinstance(primary.get("stay"), dict) else {}
    if not pstay:
        return room
    view = dict(stay)
    _hotel_copy_stay_fields(view, pstay, _HOTEL_MERGE_SHARED_GUEST_KEYS)
    _hotel_copy_stay_fields(view, pstay, _HOTEL_MERGE_SHARED_BILL_KEYS)
    view["mergeRole"] = "member"
    view["billingRoomId"] = str(primary.get("id") or billing_id)
    room["stay"] = view
    return room


def _hotel_heal_merge_group_occupancy(rooms):
    """Restore Occupied for in-house stays and merge groups with occupied peers.

    Checked-in guests must not display as Vacant until FO checkout clears the stay.
    Empty merge shells (no guest on any peer) must not display as Occupied.
    """
    if not isinstance(rooms, list):
        return
    # 1) Orphan stay with vacant/dirty inventory → occupied
    for room in rooms:
        if not isinstance(room, dict):
            continue
        status = _normalize_hotel_room_status(room.get("status"))
        if status in ("vacant", "dirty") and _hotel_room_has_inhouse_stay(room):
            room["status"] = "occupied"

    # 2) Merge groups: occupy together only when a real guest exists
    groups = {}
    for room in rooms:
        if not isinstance(room, dict):
            continue
        gid = str(room.get("mergeGroupId") or "").strip()
        if not gid:
            continue
        groups.setdefault(gid, []).append(room)
    for peers in groups.values():
        primary = next((r for r in peers if r.get("mergePrimary")), None)
        # Orphan members (primary unmerged with scope=one) stay hidden on the
        # board via isMergeMember — dissolve invalid / singleton groups.
        if primary is None or len(peers) < 2:
            for room in peers:
                stay = room.get("stay") if isinstance(room.get("stay"), dict) else None
                if stay:
                    stay = dict(stay)
                    stay["billingRoomId"] = ""
                    stay["mergeRole"] = ""
                    room["stay"] = _normalize_hotel_room_stay(stay)
                _hotel_clear_room_merge_fields(room)
            continue
        has_guest = any(
            _hotel_stay_guest_richness(r.get("stay")) > 0 or _hotel_room_has_inhouse_stay(r)
            for r in peers
        )
        if has_guest:
            for room in peers:
                status = _normalize_hotel_room_status(room.get("status"))
                if status not in ("vacant", "dirty", "occupied"):
                    continue
                room["status"] = "occupied"
                stay = room.get("stay") if isinstance(room.get("stay"), dict) else {}
                stay = dict(stay)
                if room.get("mergePrimary") or (
                    primary and room.get("id") == primary.get("id")
                ):
                    stay["mergeRole"] = "primary"
                    stay["billingRoomId"] = ""
                    for peer in peers:
                        if peer.get("id") == room.get("id"):
                            continue
                        pstay = (
                            peer.get("stay")
                            if isinstance(peer.get("stay"), dict)
                            else None
                        )
                        if not pstay:
                            continue
                        for key in (
                            "checkInDate",
                            "checkOutDate",
                            "checkedInAt",
                            "nights",
                            "firstName",
                            "lastName",
                            "guestName",
                            "mobile",
                        ):
                            if not stay.get(key) and pstay.get(key) not in (
                                None,
                                "",
                                [],
                                {},
                            ):
                                stay[key] = pstay.get(key)
                else:
                    stay["mergeRole"] = "member"
                    stay["billingRoomId"] = str((primary or {}).get("id") or "")
                room["stay"] = stay
        else:
            # Linked rooms with no guest — keep merge, drop false Occupied
            for room in peers:
                if _normalize_hotel_room_status(room.get("status")) != "occupied":
                    continue
                if _hotel_room_has_inhouse_stay(room):
                    continue
                if _hotel_stay_guest_richness(room.get("stay")) > 0:
                    continue
                room["status"] = "vacant"

    # 2b) Member flags without a merge group id (board would still hide them)
    for room in rooms:
        if not isinstance(room, dict):
            continue
        if str(room.get("mergeGroupId") or "").strip():
            continue
        stay = room.get("stay") if isinstance(room.get("stay"), dict) else None
        if not stay:
            continue
        role = str(stay.get("mergeRole") or "").strip().lower()
        billing = str(stay.get("billingRoomId") or "").strip()
        if role != "member" and not billing:
            continue
        stay = dict(stay)
        stay["billingRoomId"] = ""
        stay["mergeRole"] = ""
        room["stay"] = _normalize_hotel_room_stay(stay)

    # 3) Same guest identity on every room in the merge group
    _hotel_sync_merge_group_shared_data(rooms)


def _normalize_hotel_rooms_payload(floors, rooms, tax_rates=None):
    """Sanitize floors/rooms lists into a stable layout payload."""
    rates = _hotel_tax_rates_or_default(tax_rates)
    norm_floors = []
    seen_floor = set()
    if isinstance(floors, list):
        for idx, raw in enumerate(floors):
            if not isinstance(raw, dict):
                continue
            fid = str(raw.get("id") or "").strip() or f"floor-{idx + 1}"
            if fid in seen_floor:
                continue
            seen_floor.add(fid)
            name = str(raw.get("name") or fid).strip() or fid
            norm_floors.append({"id": fid, "name": name})
    if not norm_floors:
        norm_floors = [
            {"id": "floor-1", "name": "Floor 1"},
            {"id": "floor-2", "name": "Floor 2"},
            {"id": "floor-3", "name": "Floor 3"},
        ]

    floor_ids = {f["id"] for f in norm_floors}
    norm_rooms = []
    seen_room = set()
    if isinstance(rooms, list):
        for raw in rooms:
            if not isinstance(raw, dict):
                continue
            number = str(raw.get("number") or "").strip()
            if not number:
                continue
            rid = str(raw.get("id") or "").strip() or f"room-{number}"
            if rid in seen_room:
                continue
            seen_room.add(rid)
            floor_id = str(raw.get("floorId") or "").strip() or _hotel_floor_id_for_number(number)
            if floor_id not in floor_ids:
                floor_id = _hotel_floor_id_for_number(number)
                if floor_id not in floor_ids:
                    floor_id = norm_floors[0]["id"]
            type_key = str(raw.get("roomType") or "").strip() or "premium_deluxe_balcony"
            type_label = HOTEL_ROOM_TYPE_LABELS.get(type_key) or str(
                raw.get("roomTypeLabel") or ""
            ).strip()
            if not type_label:
                type_label = type_key
            room_obj = {
                "id": rid,
                "number": number,
                "floorId": floor_id,
                "roomType": type_key,
                "roomTypeLabel": type_label,
                "status": _normalize_hotel_room_status(raw.get("status")),
            }
            merge_group_id = str(raw.get("mergeGroupId") or raw.get("merge_group_id") or "").strip()
            if merge_group_id:
                room_obj["mergeGroupId"] = merge_group_id[:60]
                room_obj["mergePrimary"] = bool(
                    raw.get("mergePrimary")
                    if "mergePrimary" in raw
                    else raw.get("merge_primary")
                )
            stay = raw.get("stay")
            if isinstance(stay, dict) and stay:
                room_obj["stay"] = _normalize_hotel_room_stay(stay, tax_rates=rates)
            norm_rooms.append(room_obj)
    _hotel_heal_merge_group_occupancy(norm_rooms)
    norm_rooms.sort(key=lambda r: (r["floorId"], r["number"]))
    return {"floors": norm_floors, "rooms": norm_rooms}


def hotel_rooms_status_counts(layout, *, as_of=None):
    """KPI counts for the rooms board.

    expected_checkout = occupied (non-merge-member) rooms whose expected
    check-out date matches as_of (defaults to today).
    """
    rooms = (layout or {}).get("rooms") or []
    counts = {key: 0 for key in HOTEL_ROOM_STATUSES}
    counts["total"] = 0
    counts["expected_checkout"] = 0
    day = str(as_of or date.today().isoformat())[:10]
    for room in rooms:
        if not isinstance(room, dict):
            continue
        counts["total"] += 1
        status = _normalize_hotel_room_status(room.get("status"))
        counts[status] = counts.get(status, 0) + 1
        if status != "occupied" or room.get("isMergeMember"):
            continue
        stay = room.get("stay") if isinstance(room.get("stay"), dict) else {}
        checkout = str(
            stay.get("checkOutDate")
            or stay.get("check_out_date")
            or stay.get("expectedCheckOut")
            or ""
        )[:10]
        if checkout == day:
            counts["expected_checkout"] += 1
    return counts


def _hotel_merge_occupancy_drift(raw_rooms, healed_rooms):
    """True when heal/sync changed status or shared guest fields vs stored payload."""
    if not isinstance(raw_rooms, list) or not isinstance(healed_rooms, list):
        return False
    raw_by_id = {
        str(r.get("id") or ""): r
        for r in raw_rooms
        if isinstance(r, dict) and r.get("id")
    }
    for healed in healed_rooms:
        if not isinstance(healed, dict):
            continue
        raw = raw_by_id.get(str(healed.get("id") or ""))
        if not raw:
            continue
        if _normalize_hotel_room_status(raw.get("status")) != _normalize_hotel_room_status(
            healed.get("status")
        ):
            return True
        if str(raw.get("mergeGroupId") or "") != str(healed.get("mergeGroupId") or ""):
            return True
        if bool(raw.get("mergePrimary")) != bool(healed.get("mergePrimary")):
            return True
        hstay = healed.get("stay") if isinstance(healed.get("stay"), dict) else {}
        rstay = raw.get("stay") if isinstance(raw.get("stay"), dict) else {}
        for key in (
            "guestName",
            "firstName",
            "lastName",
            "mobile",
            "email",
            "checkInDate",
            "bookingNumber",
            "mergeRole",
            "billingRoomId",
        ):
            if (hstay.get(key) or "") != (rstay.get(key) or ""):
                return True
    return False


def get_hotel_rooms_layout(conn):
    """Load hotel rooms layout JSON; seed 20 rooms when empty."""
    ensure_hotel_rooms_schema(conn)
    rates = get_hotel_tax_rates(conn)
    row = conn.execute(
        "SELECT payload FROM hotel_rooms_layout WHERE id = 1"
    ).fetchone()
    if not row:
        payload = default_hotel_rooms_layout()
        save_hotel_rooms_layout(conn, payload.get("floors"), payload.get("rooms"))
        return _normalize_hotel_rooms_payload(
            payload.get("floors"), payload.get("rooms"), tax_rates=rates
        )
    try:
        parsed = json.loads(row["payload"] or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}
    floors = parsed.get("floors")
    rooms = parsed.get("rooms")
    if not isinstance(floors, list) or not isinstance(rooms, list) or not rooms:
        payload = default_hotel_rooms_layout()
        save_hotel_rooms_layout(conn, payload.get("floors"), payload.get("rooms"))
        return _normalize_hotel_rooms_payload(
            payload.get("floors"), payload.get("rooms"), tax_rates=rates
        )
    layout = _normalize_hotel_rooms_payload(floors, rooms, tax_rates=rates)
    if _hotel_merge_occupancy_drift(rooms, layout.get("rooms") or []):
        layout = save_hotel_rooms_layout(
            conn, layout.get("floors") or [], layout.get("rooms") or []
        )
    return layout


def save_hotel_rooms_layout(conn, floors, rooms):
    """Replace hotel rooms layout payload (singleton row)."""
    ensure_hotel_rooms_schema(conn)
    rates = get_hotel_tax_rates(conn)
    existing_row = conn.execute(
        "SELECT payload FROM hotel_rooms_layout WHERE id = 1"
    ).fetchone()
    if existing_row:
        try:
            existing = json.loads(existing_row["payload"] or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            existing = {}
        if isinstance(existing, dict) and isinstance(existing.get("rooms"), list):
            existing_by_id = {
                str(r.get("id") or ""): r
                for r in existing["rooms"]
                if isinstance(r, dict) and r.get("id")
            }
            new_ids = set()
            for r in rooms or []:
                if not isinstance(r, dict):
                    continue
                number = str(r.get("number") or "").strip()
                if not number:
                    continue
                new_ids.add(str(r.get("id") or "").strip() or f"room-{number}")
            for rid, prev in existing_by_id.items():
                if rid in new_ids:
                    continue
                status = _normalize_hotel_room_status(prev.get("status"))
                if status in ("occupied", "reserved"):
                    raise ValueError(
                        f"Cannot remove room {prev.get('number') or rid} while it is {status}."
                    )
    payload = _normalize_hotel_rooms_payload(floors, rooms, tax_rates=rates)
    blob = json.dumps(payload, separators=(",", ":"))
    conn.execute(
        f"""
        INSERT INTO hotel_rooms_layout (id, payload, updated_at)
        VALUES (1, ?, {SQL_NOW})
        ON CONFLICT(id) DO UPDATE SET
            payload = excluded.payload,
            updated_at = {SQL_NOW}
        """,
        (blob,),
    )
    return payload


def _hotel_str(value, max_len=200):
    return str(value or "").strip()[:max_len]


def _hotel_parse_iso_date(value):
    text = str(value or "").strip()[:10]
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def _hotel_overstay_extra_nights(stay, as_of=None):
    """Extra billable nights after expected check-out while guest is still in-house.

    Expected check-out on Aug 1 and still in-house on Aug 2 → 1 night.
    Each further calendar day past expected check-out adds another night.
    """
    if not isinstance(stay, dict):
        return 0
    out_date = _hotel_parse_iso_date(
        stay.get("checkOutDate")
        or stay.get("check_out_date")
        or stay.get("expectedCheckOut")
    )
    if out_date is None:
        in_date = _hotel_parse_iso_date(
            stay.get("checkInDate") or stay.get("check_in_date")
        )
        try:
            booked = max(1, int(float(stay.get("nights") or 1)))
        except (TypeError, ValueError):
            booked = 1
        if in_date is not None:
            out_date = in_date + timedelta(days=booked)
    if out_date is None:
        return 0
    if as_of is None:
        as_of_date = datetime.now().date()
    elif hasattr(as_of, "date") and callable(as_of.date):
        as_of_date = as_of.date()
    else:
        as_of_date = _hotel_parse_iso_date(as_of) or datetime.now().date()
    if as_of_date <= out_date:
        return 0
    return (as_of_date - out_date).days


def _normalize_hotel_room_stay(stay, tax_rates=None):
    """Sanitize guest/booking payload stored on a room."""
    if not isinstance(stay, dict):
        return {}
    special = stay.get("specialRequests") or stay.get("special_requests") or []
    if isinstance(special, str):
        special = [s.strip() for s in special.split(",") if s.strip()]
    if not isinstance(special, list):
        special = []
    special = [_hotel_str(s, 40) for s in special if _hotel_str(s, 40)][:20]

    def _num(value, default=0):
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    adults = int(_num(stay.get("adults"), 1) or 1)
    children = int(_num(stay.get("children"), 0) or 0)
    nights = int(_num(stay.get("nights"), 1) or 1)
    room_rate = round(_num(stay.get("roomRate") or stay.get("room_rate"), 0), 2)
    advance = round(_num(stay.get("advancePaid") or stay.get("advance_paid"), 0), 2)
    total_rate = stay.get("totalRate") or stay.get("total_rate")
    total_rate = round(_num(total_rate, room_rate * nights), 2)
    # balance recomputed after folio/extras below
    balance = 0.0

    title = _hotel_str(stay.get("title"), 20)
    first = _hotel_str(stay.get("firstName") or stay.get("first_name"), 80)
    last = _hotel_str(stay.get("lastName") or stay.get("last_name"), 80)
    guest_name = _hotel_str(stay.get("guestName") or stay.get("guest_name"), 160)
    if not guest_name:
        guest_name = " ".join(p for p in (title, first, last) if p).strip()

    out = {
        "bookingNumber": _hotel_str(
            stay.get("bookingNumber") or stay.get("booking_number"), 40
        ),
        "bookingDate": _hotel_str(stay.get("bookingDate") or stay.get("booking_date"), 20),
        "title": title,
        "firstName": first,
        "lastName": last,
        "guestName": guest_name,
        "gender": _hotel_str(stay.get("gender"), 20),
        "dateOfBirth": _hotel_str(stay.get("dateOfBirth") or stay.get("date_of_birth"), 20),
        "nationality": _hotel_str(stay.get("nationality"), 60),
        "mobileCountry": _hotel_str(stay.get("mobileCountry") or stay.get("mobile_country"), 8)
        or "+91",
        "mobile": _hotel_str(stay.get("mobile"), 30),
        "email": _hotel_str(stay.get("email"), 120),
        "address": _hotel_str(stay.get("address"), 300),
        "city": _hotel_str(stay.get("city"), 80),
        "state": _hotel_str(stay.get("state"), 80),
        "country": _hotel_str(stay.get("country"), 80),
        "pin": _hotel_str(stay.get("pin") or stay.get("postalCode") or stay.get("postal_code"), 20),
        "purposeOfVisit": _hotel_str(
            stay.get("purposeOfVisit") or stay.get("purpose_of_visit"), 80
        ),
        "vipStatus": _hotel_str(stay.get("vipStatus") or stay.get("vip_status"), 40),
        "returningGuest": _hotel_str(
            stay.get("returningGuest") or stay.get("returning_guest"), 20
        ),
        "idType": _hotel_str(stay.get("idType") or stay.get("id_type"), 40),
        "idNumber": _hotel_str(stay.get("idNumber") or stay.get("id_number"), 160),
        "idIssueDate": _hotel_str(stay.get("idIssueDate") or stay.get("id_issue_date"), 20),
        "idExpiryDate": _hotel_str(
            stay.get("idExpiryDate") or stay.get("id_expiry_date"), 20
        ),
        "idPlaceOfIssue": _hotel_str(
            stay.get("idPlaceOfIssue") or stay.get("id_place_of_issue"), 80
        ),
        "idDocumentName": _hotel_str(
            stay.get("idDocumentName") or stay.get("id_document_name"), 120
        ),
        "idDocumentPath": _hotel_str(
            stay.get("idDocumentPath") or stay.get("id_document_path"), 160
        ),
        "idDocumentMime": _hotel_str(
            stay.get("idDocumentMime") or stay.get("id_document_mime"), 60
        ),
        "additionalGuests": [],
        "agencyName": _hotel_str(stay.get("agencyName") or stay.get("agency_name"), 160),
        "agencyGst": _hotel_str(stay.get("agencyGst") or stay.get("agency_gst"), 40),
        "agencyAddress": _hotel_str(
            stay.get("agencyAddress") or stay.get("agency_address"), 300
        ),
        "agencyBilling": bool(
            stay.get("agencyBilling")
            if "agencyBilling" in stay
            else stay.get("agency_billing")
        ),
        "invoiceTo": _hotel_str(stay.get("invoiceTo") or stay.get("invoice_to"), 160),
        "billingName": _hotel_str(stay.get("billingName") or stay.get("billing_name"), 160),
        "profession": _hotel_str(stay.get("profession"), 80),
        "company": _hotel_str(stay.get("company"), 120),
        "loyaltyNumber": _hotel_str(
            stay.get("loyaltyNumber") or stay.get("loyalty_number"), 60
        ),
        "notes": _hotel_str(stay.get("notes"), 500),
        "checkInDate": _hotel_str(stay.get("checkInDate") or stay.get("check_in_date"), 20),
        "checkInTime": _hotel_str(stay.get("checkInTime") or stay.get("check_in_time"), 20),
        "checkOutDate": _hotel_str(
            stay.get("checkOutDate") or stay.get("check_out_date"), 20
        ),
        "nights": max(1, nights),
        "overstayNights": 0,
        "billableNights": max(1, nights),
        "adults": max(1, adults),
        "children": max(0, children),
        "ratePlan": _hotel_str(stay.get("ratePlan") or stay.get("rate_plan"), 60),
        "roomRate": room_rate,
        "totalRate": total_rate,
        "paymentMethod": _hotel_str(
            stay.get("paymentMethod") or stay.get("payment_method"), 40
        ),
        "advancePaid": advance,
        "checkInAdvancePaid": round(
            _num(
                stay.get("checkInAdvancePaid")
                if "checkInAdvancePaid" in stay
                else stay.get("check_in_advance_paid"),
                -1,
            ),
            2,
        ),
        "paymentReference": _hotel_str(
            stay.get("paymentReference") or stay.get("payment_reference"), 80
        ),
        "balanceAmount": balance,
        "invoiceNumber": _hotel_str(
            stay.get("invoiceNumber") or stay.get("invoice_number"), 60
        ),
        "invoiceGenerated": bool(
            stay.get("invoiceGenerated")
            if "invoiceGenerated" in stay
            else stay.get("invoice_generated")
        ),
        "invoiceGeneratedAt": _hotel_str(
            stay.get("invoiceGeneratedAt") or stay.get("invoice_generated_at"), 40
        ),
        "payments": [],
        "specialRequests": special,
        "additionalRequests": _hotel_str(
            stay.get("additionalRequests") or stay.get("additional_requests"), 400
        ),
        "extraBedQty": max(0, int(_num(stay.get("extraBedQty") or stay.get("extra_bed_qty"), 0))),
        "extraBedRate": round(_num(stay.get("extraBedRate") or stay.get("extra_bed_rate"), 0), 2),
        "extraBedNights": max(0, int(_num(stay.get("extraBedNights") or stay.get("extra_bed_nights"), 0))),
        "extraBedAmount": round(_num(stay.get("extraBedAmount") or stay.get("extra_bed_amount"), 0), 2),
        "extraBedNote": _hotel_str(stay.get("extraBedNote") or stay.get("extra_bed_note"), 200),
        "earlyCheckinQty": max(
            0, int(_num(stay.get("earlyCheckinQty") or stay.get("early_checkin_qty"), 0))
        ),
        "earlyCheckinRate": round(
            _num(stay.get("earlyCheckinRate") or stay.get("early_checkin_rate"), 0), 2
        ),
        "earlyCheckinNights": max(
            0, int(_num(stay.get("earlyCheckinNights") or stay.get("early_checkin_nights"), 0))
        ),
        "earlyCheckinAmount": round(
            _num(stay.get("earlyCheckinAmount") or stay.get("early_checkin_amount"), 0), 2
        ),
        "earlyCheckinNote": _hotel_str(
            stay.get("earlyCheckinNote") or stay.get("early_checkin_note"), 200
        ),
        "lateCheckoutQty": max(
            0, int(_num(stay.get("lateCheckoutQty") or stay.get("late_checkout_qty"), 0))
        ),
        "lateCheckoutRate": round(
            _num(stay.get("lateCheckoutRate") or stay.get("late_checkout_rate"), 0), 2
        ),
        "lateCheckoutNights": max(
            0, int(_num(stay.get("lateCheckoutNights") or stay.get("late_checkout_nights"), 0))
        ),
        "lateCheckoutAmount": round(
            _num(stay.get("lateCheckoutAmount") or stay.get("late_checkout_amount"), 0), 2
        ),
        "lateCheckoutNote": _hotel_str(
            stay.get("lateCheckoutNote") or stay.get("late_checkout_note"), 200
        ),
        "folioCharges": [],
        "discountType": "pct",
        "discountValue": 0.0,
        "discountAmount": 0.0,
        "discountReason": "",
        "estimatedTotal": 0.0,
        "checkedInAt": _hotel_str(
            stay.get("checkedInAt") or stay.get("checked_in_at"), 40
        ),
        "transferCount": max(0, int(_num(stay.get("transferCount") or stay.get("transfer_count"), 0))),
        "transferHistory": [],
        "billingRoomId": _hotel_str(
            stay.get("billingRoomId") or stay.get("billing_room_id"), 40
        ),
        "mergeRole": _hotel_str(stay.get("mergeRole") or stay.get("merge_role"), 20).lower(),
        "mergeRoomNumbers": [],
        "mergeRoomLabel": "",
    }
    if out["mergeRole"] not in ("member", "primary"):
        out["mergeRole"] = "member" if out["billingRoomId"] else ""
    merge_nums_raw = (
        stay.get("mergeRoomNumbers")
        or stay.get("merge_room_numbers")
        or []
    )
    merge_numbers = []
    if isinstance(merge_nums_raw, (list, tuple)):
        for item in merge_nums_raw[:20]:
            num = _hotel_str(item, 20)
            if num and num not in merge_numbers:
                merge_numbers.append(num)
    elif isinstance(merge_nums_raw, str) and merge_nums_raw.strip():
        for part in re.split(r"[,+/|]+", merge_nums_raw):
            num = _hotel_str(part.strip(), 20)
            if num and num not in merge_numbers:
                merge_numbers.append(num)
    out["mergeRoomNumbers"] = merge_numbers
    label = _hotel_str(
        stay.get("mergeRoomLabel") or stay.get("merge_room_label"), 120
    )
    if not label and merge_numbers:
        label = " + ".join(merge_numbers)
    out["mergeRoomLabel"] = label
    history = stay.get("transferHistory") or stay.get("transfer_history") or []
    if isinstance(history, list):
        cleaned = []
        for item in history[-20:]:
            if not isinstance(item, dict):
                continue
            cleaned.append(
                {
                    "fromRoomId": _hotel_str(item.get("fromRoomId") or item.get("from_room_id"), 40),
                    "fromRoomNumber": _hotel_str(
                        item.get("fromRoomNumber") or item.get("from_room_number"), 20
                    ),
                    "toRoomId": _hotel_str(item.get("toRoomId") or item.get("to_room_id"), 40),
                    "toRoomNumber": _hotel_str(
                        item.get("toRoomNumber") or item.get("to_room_number"), 20
                    ),
                    "at": _hotel_str(item.get("at"), 40),
                    "note": _hotel_str(item.get("note"), 200),
                }
            )
        out["transferHistory"] = cleaned
        if cleaned and not out["transferCount"]:
            out["transferCount"] = len(cleaned)
    if out.get("agencyBilling") and out.get("agencyName"):
        if not out.get("invoiceTo"):
            out["invoiceTo"] = out["agencyName"]
        if not out.get("billingName"):
            out["billingName"] = out["agencyName"]
    elif not out.get("agencyBilling"):
        out["invoiceTo"] = ""
        out["billingName"] = ""

    extra_guests = stay.get("additionalGuests") or stay.get("additional_guests") or []
    cleaned_guests = []
    if isinstance(extra_guests, list):
        for item in extra_guests[:12]:
            if not isinstance(item, dict):
                continue
            name = _hotel_str(item.get("name") or item.get("guestName"), 160)
            id_type = _hotel_str(item.get("idType") or item.get("id_type"), 40)
            doc_name = _hotel_str(
                item.get("idDocumentName") or item.get("id_document_name"), 120
            )
            doc_path = _hotel_str(
                item.get("idDocumentPath") or item.get("id_document_path"), 160
            )
            doc_mime = _hotel_str(
                item.get("idDocumentMime") or item.get("id_document_mime"), 60
            )
            if not name and not id_type and not doc_path:
                continue
            cleaned_guests.append(
                {
                    "name": name,
                    "idType": id_type,
                    "idDocumentName": doc_name,
                    "idDocumentPath": doc_path,
                    "idDocumentMime": doc_mime,
                }
            )
    out["additionalGuests"] = cleaned_guests
    # Keep adult count at least primary + additional guests.
    out["adults"] = max(out["adults"], 1 + len(cleaned_guests))

    folio_raw = stay.get("folioCharges") or stay.get("folio_charges") or []
    cleaned_folio = []
    if isinstance(folio_raw, list):
        allowed_kinds = {
            "restaurant_room_transfer",
            "bar_room_transfer",
            "other",
        }
        for item in folio_raw[:100]:
            if not isinstance(item, dict):
                continue
            amount = round(_num(item.get("amount"), 0), 2)
            if amount <= 0:
                continue
            kind = _hotel_str(item.get("kind"), 40).lower().replace(" ", "_")
            if kind not in allowed_kinds:
                kind = "other"
            cleaned_folio.append(
                {
                    "id": _hotel_str(item.get("id"), 40),
                    "kind": kind,
                    "label": _hotel_str(item.get("label"), 120)
                    or kind.replace("_", " ").title(),
                    "amount": amount,
                    "source": _hotel_str(item.get("source"), 40),
                    "invoiceId": _hotel_str(
                        item.get("invoiceId") or item.get("invoice_id"), 40
                    ),
                    "outlet": _hotel_str(item.get("outlet"), 40),
                    "at": _hotel_str(item.get("at"), 40),
                    "note": _hotel_str(item.get("note"), 200),
                    "sourceRoomId": _hotel_str(
                        item.get("sourceRoomId") or item.get("source_room_id"), 40
                    ),
                    "sourceRoomNumber": _hotel_str(
                        item.get("sourceRoomNumber") or item.get("source_room_number"), 20
                    ),
                }
            )
    out["folioCharges"] = cleaned_folio

    payments_raw = stay.get("payments") or []
    cleaned_payments = []
    payments_total = 0.0
    if isinstance(payments_raw, list):
        for item in payments_raw[:100]:
            if not isinstance(item, dict):
                continue
            amount = round(_num(item.get("amount"), 0), 2)
            if amount <= 0:
                continue
            method = _normalize_hotel_payment_method(
                item.get("method") or item.get("paymentMethod") or item.get("payment_method")
            )
            if not method:
                method = "cash"
            cleaned_payments.append(
                {
                    "id": _hotel_str(item.get("id"), 40)
                    or f"pay-{len(cleaned_payments) + 1}",
                    "amount": amount,
                    "method": method,
                    "reference": _hotel_str(
                        item.get("reference") or item.get("paymentReference"), 80
                    ),
                    "note": _hotel_str(item.get("note"), 200),
                    "at": _hotel_str(item.get("at"), 40),
                }
            )
            payments_total = round(payments_total + amount, 2)
    out["payments"] = cleaned_payments

    # checkInAdvancePaid is the advance captured at check-in (before invoice payments).
    check_in_advance = out["checkInAdvancePaid"]
    if check_in_advance < 0:
        check_in_advance = round(max(0.0, advance - payments_total), 2)
    out["checkInAdvancePaid"] = round(max(0.0, check_in_advance), 2)
    out["advancePaid"] = round(out["checkInAdvancePaid"] + payments_total, 2)

    if out["invoiceNumber"]:
        out["invoiceGenerated"] = True
    elif out["invoiceGenerated"] and not out["invoiceNumber"]:
        out["invoiceGenerated"] = False

    # Fill expected check-out when only nights were provided.
    if not out["checkOutDate"] and out["checkInDate"]:
        in_date = _hotel_parse_iso_date(out["checkInDate"])
        if in_date is not None:
            out["checkOutDate"] = (in_date + timedelta(days=out["nights"])).isoformat()

    overstay_nights = _hotel_overstay_extra_nights(out)
    billable_nights = max(1, out["nights"] + overstay_nights)
    out["overstayNights"] = overstay_nights
    out["billableNights"] = billable_nights
    room_charges = round(out["roomRate"] * billable_nights, 2)
    out["totalRate"] = room_charges
    hotel_extras = round(
        out["extraBedAmount"]
        + out["earlyCheckinAmount"]
        + out["lateCheckoutAmount"],
        2,
    )
    folio_total = round(sum(item["amount"] for item in cleaned_folio), 2)
    # Merge members are display-only for money — billing lives on primary.
    if out.get("mergeRole") == "member" or out.get("billingRoomId"):
        out["mergeRole"] = "member"
        out["invoiceNumber"] = ""
        out["invoiceGenerated"] = False
        out["invoiceGeneratedAt"] = ""
        out["discountType"] = "pct"
        out["discountValue"] = 0.0
        out["discountAmount"] = 0.0
        out["discountReason"] = ""
        estimated = round(folio_total, 2)
        out["estimatedTotal"] = estimated
        out["balanceAmount"] = 0.0
        return out

    discount_type = str(
        stay.get("discountType") or stay.get("discount_type") or "pct"
    ).strip().lower()
    if discount_type not in ("pct", "inr"):
        discount_type = "pct"
    discount_value = round(
        _num(stay.get("discountValue") if "discountValue" in stay else stay.get("discount_value"), 0),
        2,
    )
    if discount_value < 0:
        discount_value = 0.0
    gross = round(room_charges + hotel_extras + folio_total, 2)
    if discount_type == "inr":
        discount_amount = round(min(gross, discount_value), 2)
    else:
        pct = min(100.0, discount_value)
        discount_value = pct
        discount_amount = round(gross * (pct / 100.0), 2)
    if discount_amount <= 0 or discount_value <= 0:
        discount_type = "pct"
        discount_value = 0.0
        discount_amount = 0.0
        discount_reason = ""
    else:
        discount_reason = _hotel_str(
            stay.get("discountReason") or stay.get("discount_reason"), 200
        )
        effective_pct = (
            discount_value
            if discount_type == "pct"
            else ((discount_amount / gross) * 100.0 if gross > 0 else 0.0)
        )
        if effective_pct <= 15:
            discount_reason = ""
    out["discountType"] = discount_type
    out["discountValue"] = discount_value
    out["discountAmount"] = discount_amount
    out["discountReason"] = discount_reason
    taxable = round(max(gross - discount_amount, 0), 2)
    rates = _hotel_tax_rates_or_default(tax_rates)
    cgst = round(taxable * rates["cgst"], 2)
    ugst = round(taxable * rates["ugst"], 2)
    estimated = round(taxable + cgst + ugst, 2)
    out["estimatedTotal"] = estimated
    # Prefer computed balance so folio posts stay in sync.
    out["balanceAmount"] = round(max(estimated - out["advancePaid"], 0), 2)
    return out


def _hotel_folio_kind_for_outlet(outlet):
    value = str(outlet or "").strip().lower()
    if value in ("bar", "bars"):
        return "bar_room_transfer"
    if value in ("restaurant", "resto", "dining"):
        return "restaurant_room_transfer"
    return "other"


def update_hotel_room_charge(
    conn,
    room_id,
    *,
    charge_key,
    label="",
    amount=None,
    rate=None,
):
    """Edit a stay charge line (room rate, extras, or folio entry)."""
    room_id = str(room_id or "").strip()
    key = str(charge_key or "").strip()
    if not room_id:
        raise ValueError("Hotel room is required.")
    if not key:
        raise ValueError("Charge key is required.")

    layout = get_hotel_rooms_layout(conn)
    rooms = list(layout.get("rooms") or [])
    target = None
    for room in rooms:
        if str(room.get("id") or "") == room_id or str(room.get("number") or "") == room_id:
            target = room
            break
    if not target:
        raise ValueError("Hotel room not found.")
    stay = target.get("stay")
    if _normalize_hotel_room_status(target.get("status")) != "occupied" or not isinstance(
        stay, dict
    ):
        raise ValueError("Select an occupied room with an active stay.")
    stay = _normalize_hotel_room_stay(stay)
    if stay.get("invoiceGenerated") and stay.get("invoiceNumber"):
        raise ValueError("Charges cannot be edited after the invoice is generated.")
    if stay.get("mergeRole") == "member" or stay.get("billingRoomId"):
        raise ValueError(
            "This room is merged for billing. Open the primary room to edit charges."
        )

    try:
        amt = None if amount is None else round(float(amount), 2)
    except (TypeError, ValueError) as exc:
        raise ValueError("Enter a valid amount.") from exc
    try:
        rate_val = None if rate is None else round(float(rate), 2)
    except (TypeError, ValueError) as exc:
        raise ValueError("Enter a valid rate.") from exc
    if amt is not None and amt < 0:
        raise ValueError("Amount cannot be negative.")
    if rate_val is not None and rate_val < 0:
        raise ValueError("Rate cannot be negative.")
    new_label = _hotel_str(label, 120)

    if key == "room":
        nights = max(1, int(stay.get("nights") or 1))
        if rate_val is None and amt is not None:
            rate_val = round(amt / nights, 2) if nights else amt
        if rate_val is None or rate_val <= 0:
            raise ValueError("Enter a room rate greater than zero.")
        stay["roomRate"] = rate_val
        stay["totalRate"] = round(rate_val * nights, 2)
    elif key == "extra_bed":
        if amt is None:
            raise ValueError("Enter an amount.")
        stay["extraBedAmount"] = amt
        if amt <= 0:
            stay["extraBedQty"] = 0
            stay["extraBedRate"] = 0.0
            stay["extraBedNights"] = 0
        elif not stay.get("extraBedQty"):
            stay["extraBedQty"] = 1
            stay["extraBedRate"] = amt
            stay["extraBedNights"] = 1
    elif key == "early_checkin":
        if amt is None:
            raise ValueError("Enter an amount.")
        stay["earlyCheckinAmount"] = amt
        if amt <= 0:
            stay["earlyCheckinQty"] = 0
            stay["earlyCheckinRate"] = 0.0
            stay["earlyCheckinNights"] = 0
        elif not stay.get("earlyCheckinQty"):
            stay["earlyCheckinQty"] = 1
            stay["earlyCheckinRate"] = amt
            stay["earlyCheckinNights"] = 1
    elif key == "late_checkout":
        if amt is None:
            raise ValueError("Enter an amount.")
        stay["lateCheckoutAmount"] = amt
        if amt <= 0:
            stay["lateCheckoutQty"] = 0
            stay["lateCheckoutRate"] = 0.0
            stay["lateCheckoutNights"] = 0
        elif not stay.get("lateCheckoutQty"):
            stay["lateCheckoutQty"] = 1
            stay["lateCheckoutRate"] = amt
            stay["lateCheckoutNights"] = 1
    elif key in ("restaurant_room_transfer", "bar_room_transfer"):
        if amt is None or amt <= 0:
            raise ValueError("Enter an amount greater than zero.")
        folio = [
            item
            for item in (stay.get("folioCharges") or [])
            if str(item.get("kind") or "").lower() != key
        ]
        folio.append(
            {
                "id": "fc" + str(abs(hash(f"{room_id}:{key}:{amt}")))[:8],
                "kind": key,
                "label": new_label
                or (
                    "Restaurant Room Transfer"
                    if key.startswith("restaurant")
                    else "Bar Room Transfer"
                ),
                "amount": amt,
                "source": "hotel_invoice",
                "invoiceId": "",
                "outlet": "",
                "at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "note": "",
            }
        )
        stay["folioCharges"] = folio
    elif key.startswith("folio:"):
        folio_id = key.split(":", 1)[1].strip()
        if not folio_id:
            raise ValueError("Folio charge not found.")
        if amt is None or amt <= 0:
            raise ValueError("Enter an amount greater than zero.")
        found = False
        folio = []
        for item in stay.get("folioCharges") or []:
            if str(item.get("id") or "") != folio_id:
                folio.append(item)
                continue
            found = True
            updated = dict(item)
            updated["amount"] = amt
            if new_label:
                updated["label"] = new_label
            folio.append(updated)
        if not found:
            raise ValueError("Folio charge not found.")
        stay["folioCharges"] = folio
    else:
        raise ValueError("Unsupported charge line.")

    stay = _normalize_hotel_room_stay(stay)
    target["stay"] = stay
    save_hotel_rooms_layout(conn, layout.get("floors") or [], rooms)
    refreshed = get_hotel_room(conn, target.get("id") or room_id)
    return {"room": refreshed or target}


def delete_hotel_room_charge(conn, room_id, *, charge_key):
    """Remove a stay charge line (extras or folio). Room tariff cannot be deleted."""
    room_id = str(room_id or "").strip()
    key = str(charge_key or "").strip()
    if not room_id:
        raise ValueError("Hotel room is required.")
    if not key:
        raise ValueError("Charge key is required.")
    if key == "room":
        raise ValueError("Room tariff cannot be deleted.")

    layout = get_hotel_rooms_layout(conn)
    rooms = list(layout.get("rooms") or [])
    target = None
    for room in rooms:
        if str(room.get("id") or "") == room_id or str(room.get("number") or "") == room_id:
            target = room
            break
    if not target:
        raise ValueError("Hotel room not found.")
    stay = target.get("stay")
    if _normalize_hotel_room_status(target.get("status")) != "occupied" or not isinstance(
        stay, dict
    ):
        raise ValueError("Select an occupied room with an active stay.")
    stay = _normalize_hotel_room_stay(stay)
    if stay.get("invoiceGenerated") and stay.get("invoiceNumber"):
        raise ValueError("Charges cannot be deleted after the invoice is generated.")
    if stay.get("mergeRole") == "member" or stay.get("billingRoomId"):
        raise ValueError(
            "This room is merged for billing. Open the primary room to delete charges."
        )

    if key == "extra_bed":
        stay["extraBedAmount"] = 0.0
        stay["extraBedQty"] = 0
        stay["extraBedRate"] = 0.0
        stay["extraBedNights"] = 0
    elif key == "early_checkin":
        stay["earlyCheckinAmount"] = 0.0
        stay["earlyCheckinQty"] = 0
        stay["earlyCheckinRate"] = 0.0
        stay["earlyCheckinNights"] = 0
    elif key == "late_checkout":
        stay["lateCheckoutAmount"] = 0.0
        stay["lateCheckoutQty"] = 0
        stay["lateCheckoutRate"] = 0.0
        stay["lateCheckoutNights"] = 0
    elif key in ("restaurant_room_transfer", "bar_room_transfer"):
        stay["folioCharges"] = [
            item
            for item in (stay.get("folioCharges") or [])
            if str(item.get("kind") or "").lower() != key
        ]
    elif key.startswith("folio:"):
        folio_id = key.split(":", 1)[1].strip()
        before = len(stay.get("folioCharges") or [])
        stay["folioCharges"] = [
            item
            for item in (stay.get("folioCharges") or [])
            if str(item.get("id") or "") != folio_id
        ]
        if len(stay.get("folioCharges") or []) == before:
            raise ValueError("Folio charge not found.")
    else:
        raise ValueError("Unsupported charge line.")

    stay = _normalize_hotel_room_stay(stay)
    target["stay"] = stay
    save_hotel_rooms_layout(conn, layout.get("floors") or [], rooms)
    refreshed = get_hotel_room(conn, target.get("id") or room_id)
    return {"room": refreshed or target}


def append_hotel_room_folio_charge(
    conn,
    room_id,
    *,
    amount,
    kind=None,
    label="",
    source="pos",
    invoice_id="",
    outlet="",
    note="",
    at=None,
):
    """Append a folio line to an occupied room stay and recompute balance."""
    room_id = str(room_id or "").strip()
    if not room_id:
        raise ValueError("Hotel room is required.")
    amount = round(float(amount or 0), 2)
    if amount <= 0:
        raise ValueError("Folio charge amount must be greater than zero.")

    layout = get_hotel_rooms_layout(conn)
    rooms = list(layout.get("rooms") or [])
    target = None
    for room in rooms:
        if str(room.get("id") or "") == room_id or str(room.get("number") or "") == room_id:
            target = room
            break
    if not target:
        raise ValueError("Hotel room not found.")
    status = str(target.get("status") or "").strip().lower()
    stay = target.get("stay")
    if status != "occupied" or not isinstance(stay, dict) or not stay:
        raise ValueError("Select an occupied room with an active stay.")

    # Merged members bill on the primary room.
    billing_id = str(stay.get("billingRoomId") or "").strip()
    if (stay.get("mergeRole") == "member" or billing_id) and billing_id:
        primary = None
        for room in rooms:
            if str(room.get("id") or "") == billing_id or str(room.get("number") or "") == billing_id:
                primary = room
                break
        if not primary or _normalize_hotel_room_status(primary.get("status")) != "occupied":
            raise ValueError("Shared billing room is not available for folio charges.")
        target = primary
        room_id = str(primary.get("id") or "")
        stay = primary.get("stay")
        if not isinstance(stay, dict) or not stay:
            raise ValueError("Shared billing room has no active stay.")

    folio_kind = kind or _hotel_folio_kind_for_outlet(outlet)
    if folio_kind not in (
        "restaurant_room_transfer",
        "bar_room_transfer",
        "other",
    ):
        folio_kind = "other"
    default_label = {
        "restaurant_room_transfer": "Restaurant Room Transfer",
        "bar_room_transfer": "Bar Room Transfer",
        "other": "Other Charge",
    }.get(folio_kind, "Other Charge")
    stamp = str(at or "").strip()
    if not stamp:
        stamp = conn.execute("SELECT datetime('now','localtime')").fetchone()[0]
    line_id = "fc" + str(abs(hash(f"{room_id}:{invoice_id}:{amount}:{stamp}")))[:8]
    line = {
        "id": line_id,
        "kind": folio_kind,
        "label": str(label or default_label).strip()[:120] or default_label,
        "amount": amount,
        "source": str(source or "pos").strip()[:40],
        "invoiceId": str(invoice_id or "").strip()[:40],
        "outlet": str(outlet or "").strip()[:40],
        "at": stamp[:40],
        "note": str(note or "").strip()[:200],
    }
    folio = list(stay.get("folioCharges") or stay.get("folio_charges") or [])
    folio.append(line)
    stay = dict(stay)
    stay["folioCharges"] = folio
    target["stay"] = _normalize_hotel_room_stay(stay)
    saved = save_hotel_rooms_layout(conn, layout.get("floors") or [], rooms)
    room = None
    for item in saved.get("rooms") or []:
        if str(item.get("id") or "") == room_id:
            room = item
            break
    return {"room": room, "charge": line}


def _hotel_mobile_digits(value):
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def _hotel_guest_profile_key(mobile):
    digits = _hotel_mobile_digits(mobile)
    if len(digits) >= 10:
        return digits[-10:]
    return digits if len(digits) >= 8 else ""


_HOTEL_GUEST_PROFILE_KEYS = (
    "title",
    "firstName",
    "lastName",
    "guestName",
    "gender",
    "dateOfBirth",
    "nationality",
    "mobileCountry",
    "mobile",
    "email",
    "address",
    "city",
    "state",
    "country",
    "pin",
    "purposeOfVisit",
    "vipStatus",
    "idType",
    "idNumber",
    "idIssueDate",
    "idExpiryDate",
    "idPlaceOfIssue",
    "agencyName",
    "agencyGst",
    "agencyAddress",
    "agencyBilling",
)


def save_hotel_guest_profile(conn, stay):
    """Persist guest contact/ID fields keyed by mobile for returning-guest autofill."""
    if not isinstance(stay, dict):
        return
    ensure_hotel_rooms_schema(conn)
    key = _hotel_guest_profile_key(stay.get("mobile"))
    if not key:
        return
    profile = {k: stay.get(k) for k in _HOTEL_GUEST_PROFILE_KEYS if k in stay}
    profile["mobile"] = key
    profile["returningGuest"] = "Yes"
    blob = json.dumps(profile, ensure_ascii=False)
    conn.execute(
        f"""
        INSERT INTO hotel_guest_profiles (mobile, profile, updated_at)
        VALUES (?, ?, {SQL_NOW})
        ON CONFLICT(mobile) DO UPDATE SET
            profile = excluded.profile,
            updated_at = {SQL_NOW}
        """,
        (key, blob),
    )


def get_hotel_guest_profile(conn, mobile):
    """Load a saved hotel guest profile by mobile digits."""
    ensure_hotel_rooms_schema(conn)
    key = _hotel_guest_profile_key(mobile)
    if not key:
        return None
    row = conn.execute(
        "SELECT profile FROM hotel_guest_profiles WHERE mobile = ?",
        (key,),
    ).fetchone()
    if not row:
        # Also try full digit string if stored that way historically.
        digits = _hotel_mobile_digits(mobile)
        if digits and digits != key:
            row = conn.execute(
                "SELECT profile FROM hotel_guest_profiles WHERE mobile = ?",
                (digits,),
            ).fetchone()
    if not row:
        return None
    try:
        data = json.loads(row["profile"] if isinstance(row, dict) else row[0])
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    data["returningGuest"] = "Yes"
    return data


def find_hotel_guest_by_mobile(conn, mobile):
    """Return guest profile for autofill by mobile number.

    Prefers an in-house stay, then saved hotel guest profiles, then Customer Master.
    """
    digits = _hotel_mobile_digits(mobile)
    if len(digits) < 8:
        return None

    layout = get_hotel_rooms_layout(conn)
    best = None
    best_key = ""
    for room in layout.get("rooms") or []:
        stay = room.get("stay")
        if not isinstance(stay, dict) or not stay:
            continue
        stay_digits = _hotel_mobile_digits(stay.get("mobile"))
        if not stay_digits:
            continue
        # Match full number or last 10 digits (country code variants).
        if stay_digits != digits and not (
            len(digits) >= 10
            and len(stay_digits) >= 10
            and stay_digits[-10:] == digits[-10:]
        ):
            continue
        key = str(
            stay.get("checkedInAt")
            or stay.get("checkInDate")
            or stay.get("bookingDate")
            or ""
        )
        if key >= best_key:
            best_key = key
            best = dict(stay)
            best["_matchedRoomId"] = room.get("id")
            best["_matchedRoomNumber"] = room.get("number")

    if best:
        best["returningGuest"] = "Yes"
        best.pop("_matchedRoomId", None)
        best.pop("_matchedRoomNumber", None)
        return best

    saved = get_hotel_guest_profile(conn, mobile)
    if saved:
        return saved

    try:
        ensure_customers_schema(conn)
        mobile10 = digits[-10:] if len(digits) >= 10 else digits
        row = conn.execute(
            """
            SELECT first_name, mobile
            FROM customers
            WHERE mobile != '' AND (mobile = ? OR mobile LIKE ?)
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
            """,
            (mobile10, "%" + mobile10),
        ).fetchone()
    except Exception:
        row = None
    if not row:
        return None
    first = _normalize_customer_first_name(row["first_name"] if row else "")
    return {
        "firstName": first,
        "mobile": row["mobile"] or mobile10,
        "mobileCountry": "+91",
        "returningGuest": "Yes",
    }


def save_hotel_room_checkin(conn, room_id, stay, status="occupied"):
    """Save guest stay on a room and set status (default occupied)."""
    layout = get_hotel_rooms_layout(conn)
    rooms = layout.get("rooms") or []
    target = str(room_id or "").strip()
    next_status = _normalize_hotel_room_status(status)
    found = False
    normalized_stay = None
    for room in rooms:
        if room.get("id") == target or room.get("number") == target:
            prev = room.get("stay") if isinstance(room.get("stay"), dict) else {}
            incoming = dict(stay or {})
            # Preserve invoice lock / payments across guest edits unless cleared.
            for key in (
                "invoiceNumber",
                "invoiceGenerated",
                "invoiceGeneratedAt",
                "payments",
                "checkInAdvancePaid",
                "folioCharges",
            ):
                if key not in incoming and key in prev:
                    incoming[key] = prev.get(key)
            if prev.get("invoiceGenerated") or prev.get("invoiceNumber"):
                # Locked folio: keep money fields from the generated stay.
                for key in (
                    "roomRate",
                    "nights",
                    "totalRate",
                    "extraBedQty",
                    "extraBedRate",
                    "extraBedNights",
                    "extraBedAmount",
                    "extraBedNote",
                    "earlyCheckinQty",
                    "earlyCheckinRate",
                    "earlyCheckinNights",
                    "earlyCheckinAmount",
                    "earlyCheckinNote",
                    "lateCheckoutQty",
                    "lateCheckoutRate",
                    "lateCheckoutNights",
                    "lateCheckoutAmount",
                    "lateCheckoutNote",
                    "checkInAdvancePaid",
                    "advancePaid",
                    "payments",
                    "folioCharges",
                    "invoiceNumber",
                    "invoiceGenerated",
                    "invoiceGeneratedAt",
                ):
                    if key in prev:
                        incoming[key] = prev.get(key)
            elif "checkInAdvancePaid" not in incoming and "check_in_advance_paid" not in incoming:
                # Fresh check-in / edit before invoice: treat form advance as check-in advance.
                incoming["checkInAdvancePaid"] = incoming.get("advancePaid") or incoming.get(
                    "advance_paid"
                ) or 0
                incoming["payments"] = []
            room["stay"] = _normalize_hotel_room_stay(incoming)
            if not room["stay"].get("bookingNumber"):
                room["stay"]["bookingNumber"] = (
                    f"BK{datetime.now().strftime('%Y%m%d%H%M%S')}"
                )
            if not room["stay"].get("checkedInAt") and next_status == "occupied":
                room["stay"]["checkedInAt"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            room["status"] = next_status
            normalized_stay = room["stay"]
            found = True
            break
    if not found:
        raise ValueError("Room not found.")
    _hotel_sync_merge_group_shared_data(rooms)
    if normalized_stay:
        # Prefer the post-sync stay on the target room for guest profile save.
        for room in rooms:
            if room.get("id") == target or room.get("number") == target:
                if isinstance(room.get("stay"), dict):
                    normalized_stay = room["stay"]
                break
        try:
            save_hotel_guest_profile(conn, normalized_stay)
        except Exception:
            pass
    saved = save_hotel_rooms_layout(conn, layout.get("floors") or [], rooms)
    for room in saved.get("rooms") or []:
        if room.get("id") == target or room.get("number") == target:
            return room
    raise ValueError("Room not found.")


def _hotel_room_payment_payload(payment, *, allow_credit=False):
    """Validate and normalize a payment dict for generate/record actions."""
    raw = payment if isinstance(payment, dict) else {}
    try:
        amount = round(float(raw.get("amount") or 0), 2)
    except (TypeError, ValueError) as exc:
        raise ValueError("Payment amount is invalid.") from exc
    if amount < 0:
        raise ValueError("Payment amount cannot be negative.")
    method = _normalize_hotel_payment_method(
        raw.get("method") or raw.get("paymentMethod") or raw.get("payment_method")
    )
    if method == "credit" and not allow_credit:
        raise ValueError("Credit is only allowed when an agency is on this stay.")
    if amount > 0 and not method:
        raise ValueError("Payment method is required.")
    if amount > 0 and method == "credit" and not allow_credit:
        raise ValueError("Credit is only allowed when an agency is on this stay.")
    reference = _hotel_str(
        raw.get("reference")
        or raw.get("transaction_id")
        or raw.get("transactionId")
        or raw.get("paymentReference")
        or raw.get("payment_reference"),
        80,
    )
    if method == "bank_transfer" and amount > 0 and not reference:
        raise ValueError("Transaction / reference id is required for bank transfer.")
    note = _hotel_str(raw.get("note") or raw.get("notes"), 200)
    return {
        "amount": amount,
        "method": method or "cash",
        "reference": reference,
        "note": note,
    }


def _parse_hotel_room_payment_splits(
    raw_splits, max_total, *, require_positive=False, allow_credit=False
):
    """Validate split modes for room invoice payment (sum may be ≤ balance)."""
    try:
        ceiling = round(float(max_total or 0), 2)
    except (TypeError, ValueError):
        ceiling = 0.0
    if ceiling < 0:
        raise ValueError("Balance due cannot be negative.")

    if not isinstance(raw_splits, list) or not raw_splits:
        if require_positive:
            raise ValueError("Add at least one payment mode.")
        return []

    allowed = set(HOTEL_ROOM_PAYMENT_METHODS)
    if not allow_credit:
        allowed.discard("credit")

    parsed = []
    seen = set()
    for raw in raw_splits:
        if not isinstance(raw, dict):
            raise ValueError("Each payment split must be an object.")
        method = _normalize_hotel_payment_method(
            raw.get("payment_method")
            or raw.get("paymentMethod")
            or raw.get("method")
        )
        if method == "credit" and not allow_credit:
            raise ValueError("Credit is only allowed when an agency is on this stay.")
        if not method or method not in allowed:
            raise ValueError("Select a valid payment mode for each row.")
        if method in seen:
            raise ValueError("Each payment mode can only be used once.")
        seen.add(method)
        try:
            amount = round(float(raw.get("amount") or 0), 2)
        except (TypeError, ValueError) as exc:
            raise ValueError("Enter a valid amount for each payment mode.") from exc
        if amount < 0:
            raise ValueError("Payment amounts cannot be negative.")
        if amount <= 0:
            raise ValueError("Enter a valid amount for each payment mode.")
        reference = _hotel_str(
            raw.get("transaction_id")
            or raw.get("transactionId")
            or raw.get("reference")
            or raw.get("paymentReference"),
            80,
        )
        if method == "bank_transfer" and not reference:
            raise ValueError("Transaction ID is required for bank transfer.")
        if method != "bank_transfer":
            reference = ""
        parsed.append(
            {
                "amount": amount,
                "method": method,
                "reference": reference,
                "note": _hotel_str(raw.get("note") or raw.get("notes"), 200),
            }
        )

    split_total = round(sum(item["amount"] for item in parsed), 2)
    if split_total - ceiling > 0.009:
        raise ValueError(
            f"Modes total ₹{split_total:.2f} exceeds balance due ₹{ceiling:.2f}."
        )
    if require_positive and split_total <= 0:
        raise ValueError("Payment amount must be greater than zero.")
    return parsed


def _append_hotel_room_payment(stay, payment, at=None, *, allow_credit=False):
    """Append a payment onto stay and return the payment record (mutates stay)."""
    payload = _hotel_room_payment_payload(payment, allow_credit=allow_credit)
    amount = payload["amount"]
    if amount <= 0:
        return None
    balance = round(float(stay.get("balanceAmount") or 0), 2)
    if amount - balance > 0.009:
        raise ValueError(
            f"Payment ₹{amount:.2f} exceeds balance due ₹{balance:.2f}."
        )
    stamp = _hotel_str(at, 40) or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    payments = list(stay.get("payments") or [])
    record = {
        "id": f"pay-{int(datetime.now().timestamp())}-{len(payments) + 1}",
        "amount": amount,
        "method": payload["method"],
        "reference": payload["reference"],
        "note": payload["note"],
        "at": stamp,
    }
    payments.append(record)
    stay["payments"] = payments
    if not stay.get("paymentMethod"):
        stay["paymentMethod"] = payload["method"]
    if payload["reference"] and not stay.get("paymentReference"):
        stay["paymentReference"] = payload["reference"]
    return record


def _apply_hotel_room_payment_splits(stay, splits, note="", at=None):
    """Append one payment record per split (mutates stay). Returns records."""
    if not splits:
        return []
    stamp = _hotel_str(at, 40) or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    shared_note = _hotel_str(note, 200)
    balance = round(float(stay.get("balanceAmount") or 0), 2)
    total = round(sum(float(s.get("amount") or 0) for s in splits), 2)
    if total - balance > 0.009:
        raise ValueError(
            f"Modes total ₹{total:.2f} exceeds balance due ₹{balance:.2f}."
        )
    records = []
    payments = list(stay.get("payments") or [])
    for split in splits:
        amount = round(float(split.get("amount") or 0), 2)
        if amount <= 0:
            continue
        method = _normalize_hotel_payment_method(split.get("method")) or "cash"
        reference = _hotel_str(split.get("reference"), 80)
        record = {
            "id": f"pay-{int(datetime.now().timestamp())}-{len(payments) + 1}",
            "amount": amount,
            "method": method,
            "reference": reference,
            "note": _hotel_str(split.get("note"), 200) or shared_note,
            "at": stamp,
        }
        payments.append(record)
        records.append(record)
        if not stay.get("paymentMethod"):
            stay["paymentMethod"] = method
        if reference and not stay.get("paymentReference"):
            stay["paymentReference"] = reference
    stay["payments"] = payments
    return records


def set_hotel_room_discount(
    conn, room_id, discount_type="pct", discount_value=0, discount_reason=""
):
    """Apply a stay folio discount (pct or fixed ₹) before invoice generation."""
    layout = get_hotel_rooms_layout(conn)
    rooms = layout.get("rooms") or []
    target = str(room_id or "").strip()
    room = None
    for item in rooms:
        if item.get("id") == target or item.get("number") == target:
            room = item
            break
    if not room:
        raise ValueError("Room not found.")
    if _normalize_hotel_room_status(room.get("status")) != "occupied":
        raise ValueError("Only occupied rooms can set a discount.")
    stay = room.get("stay") if isinstance(room.get("stay"), dict) else None
    if not stay:
        raise ValueError("No guest stay on this room.")
    stay = _normalize_hotel_room_stay(stay)
    if stay.get("mergeRole") == "member" or stay.get("billingRoomId"):
        raise ValueError(
            "This room is merged for billing. Open the primary room to set the discount."
        )
    if stay.get("invoiceGenerated") and stay.get("invoiceNumber"):
        raise ValueError("Discount cannot be changed after the invoice is generated.")

    dtype = str(discount_type or "pct").strip().lower()
    if dtype not in ("pct", "inr"):
        dtype = "pct"
    try:
        dvalue = round(float(discount_value or 0), 2)
    except (TypeError, ValueError) as exc:
        raise ValueError("Enter a valid discount amount.") from exc
    if dvalue < 0:
        raise ValueError("Discount cannot be negative.")
    reason = _hotel_str(discount_reason, 200)

    # Validate against current gross (before discount) so reason rules match UI.
    room_charges = round(float(stay.get("roomRate") or 0) * float(stay.get("nights") or 1), 2)
    extras = round(
        float(stay.get("extraBedAmount") or 0)
        + float(stay.get("earlyCheckinAmount") or 0)
        + float(stay.get("lateCheckoutAmount") or 0),
        2,
    )
    folio_total = round(
        sum(float(item.get("amount") or 0) for item in (stay.get("folioCharges") or [])),
        2,
    )
    # Stay already has discount applied in estimatedTotal — rebuild gross from components.
    gross = round(room_charges + extras + folio_total, 2)
    if dtype == "inr":
        amount = round(min(gross, dvalue), 2)
        effective_pct = (amount / gross * 100.0) if gross > 0 else 0.0
    else:
        dvalue = min(100.0, dvalue)
        amount = round(gross * (dvalue / 100.0), 2)
        effective_pct = dvalue
    if amount <= 0 or dvalue <= 0:
        dtype = "pct"
        dvalue = 0.0
        amount = 0.0
        reason = ""
    elif effective_pct > 15 and not reason:
        raise ValueError("Enter a reason for discounts over 15%.")
    elif effective_pct <= 15:
        reason = ""

    stay["discountType"] = dtype
    stay["discountValue"] = dvalue
    stay["discountAmount"] = amount
    stay["discountReason"] = reason
    stay = _normalize_hotel_room_stay(stay)
    room["stay"] = stay
    save_hotel_rooms_layout(conn, layout.get("floors") or [], rooms)
    refreshed = get_hotel_room(conn, room.get("id") or target)
    return {"room": refreshed or room}


def generate_hotel_room_invoice(conn, room_id, payment=None, payment_splits=None, note=""):
    """Mint a stay invoice number (once) and optionally record payment split(s)."""
    layout = get_hotel_rooms_layout(conn)
    rooms = layout.get("rooms") or []
    target = str(room_id or "").strip()
    room = None
    for item in rooms:
        if item.get("id") == target or item.get("number") == target:
            room = item
            break
    if not room:
        raise ValueError("Room not found.")
    if _normalize_hotel_room_status(room.get("status")) != "occupied":
        raise ValueError("Only occupied rooms can generate an invoice.")
    stay = room.get("stay") if isinstance(room.get("stay"), dict) else None
    if not stay:
        raise ValueError("No guest stay on this room.")

    stay = _normalize_hotel_room_stay(stay)
    if stay.get("mergeRole") == "member" or stay.get("billingRoomId"):
        raise ValueError(
            "This room is merged for billing. Open the primary room to generate the invoice."
        )
    if float(stay.get("estimatedTotal") or 0) <= 0 and not stay.get("folioCharges"):
        raise ValueError("No charges to invoice yet.")

    minted = False
    if not stay.get("invoiceGenerated") or not stay.get("invoiceNumber"):
        stay["invoiceNumber"] = allocate_hotel_room_invoice_number(conn)
        stay["invoiceGenerated"] = True
        stay["invoiceGeneratedAt"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        minted = True

    balance = round(float(stay.get("balanceAmount") or 0), 2)
    allow_credit = _hotel_stay_has_agency(stay)
    payment_records = []
    if payment_splits is not None:
        splits = _parse_hotel_room_payment_splits(
            payment_splits,
            balance,
            require_positive=False,
            allow_credit=allow_credit,
        )
        payment_records = _apply_hotel_room_payment_splits(stay, splits, note=note)
    elif payment is not None:
        record = _append_hotel_room_payment(
            stay, payment, allow_credit=allow_credit
        )
        if record:
            payment_records = [record]

    stay = _normalize_hotel_room_stay(stay)
    room["stay"] = stay
    _hotel_snapshot_merge_rooms_on_stay(room, rooms)
    stay = _normalize_hotel_room_stay(room.get("stay") or {})
    room["stay"] = stay
    saved = save_hotel_rooms_layout(conn, layout.get("floors") or [], rooms)
    for item in saved.get("rooms") or []:
        if item.get("id") == target or item.get("number") == target:
            upsert_hotel_room_invoice_from_room(conn, item)
            return {
                "room": item,
                "minted": minted,
                "payment": payment_records[0] if payment_records else None,
                "payments": payment_records,
            }
    raise ValueError("Room not found.")


def record_hotel_room_payment(conn, room_id, payment=None, payment_splits=None, note=""):
    """Record a partial/full payment against an already-generated room invoice."""
    layout = get_hotel_rooms_layout(conn)
    rooms = layout.get("rooms") or []
    target = str(room_id or "").strip()
    room = None
    for item in rooms:
        if item.get("id") == target or item.get("number") == target:
            room = item
            break
    if not room:
        raise ValueError("Room not found.")
    if _normalize_hotel_room_status(room.get("status")) != "occupied":
        raise ValueError("Only occupied rooms can record payment.")
    stay = room.get("stay") if isinstance(room.get("stay"), dict) else None
    if not stay:
        raise ValueError("No guest stay on this room.")
    stay = _normalize_hotel_room_stay(stay)
    if stay.get("mergeRole") == "member" or stay.get("billingRoomId"):
        raise ValueError(
            "This room is merged for billing. Open the primary room to record payment."
        )
    if not stay.get("invoiceGenerated") or not stay.get("invoiceNumber"):
        raise ValueError("Generate the invoice before recording payment.")
    if float(stay.get("balanceAmount") or 0) <= 0:
        raise ValueError("Balance due is already settled.")

    balance = round(float(stay.get("balanceAmount") or 0), 2)
    allow_credit = _hotel_stay_has_agency(stay)
    payment_records = []
    if payment_splits is not None:
        splits = _parse_hotel_room_payment_splits(
            payment_splits,
            balance,
            require_positive=True,
            allow_credit=allow_credit,
        )
        payment_records = _apply_hotel_room_payment_splits(stay, splits, note=note)
    else:
        record = _append_hotel_room_payment(
            stay, payment or {}, allow_credit=allow_credit
        )
        if not record:
            raise ValueError("Payment amount must be greater than zero.")
        payment_records = [record]

    stay = _normalize_hotel_room_stay(stay)
    room["stay"] = stay
    saved = save_hotel_rooms_layout(conn, layout.get("floors") or [], rooms)
    for item in saved.get("rooms") or []:
        if item.get("id") == target or item.get("number") == target:
            upsert_hotel_room_invoice_from_room(conn, item)
            return {
                "room": item,
                "payment": payment_records[0] if payment_records else None,
                "payments": payment_records,
            }
    raise ValueError("Room not found.")


def save_hotel_room_reservation(
    conn, room_id, check_in_date, check_out_date=None, stay_fields=None
):
    """Reserve a room for a date window; merges into existing stay when present."""
    room = get_hotel_room(conn, room_id)
    if not room:
        raise ValueError("Room not found.")
    status = _normalize_hotel_room_status(room.get("status"))
    stay_existing = room.get("stay") if isinstance(room.get("stay"), dict) else None
    if status == "occupied" and stay_existing:
        raise ValueError("Check out the guest before reserving this room.")

    check_in = str(check_in_date or "").strip()[:10]
    if not check_in:
        raise ValueError("From date is required.")
    check_out = str(check_out_date or "").strip()[:10]
    if not check_out:
        try:
            base = datetime.strptime(check_in, "%Y-%m-%d")
            check_out = (base + timedelta(days=1)).strftime("%Y-%m-%d")
        except ValueError as exc:
            raise ValueError("From date is invalid.") from exc
    else:
        check_out = check_out[:10]
    if check_out <= check_in:
        raise ValueError("To date must be after from date.")

    stay = dict(stay_existing or {})
    fields = stay_fields if isinstance(stay_fields, dict) else {}
    merge_keys = (
        "guestName",
        "firstName",
        "lastName",
        "mobile",
        "mobileCountry",
        "email",
        "agencyName",
        "agencyGst",
        "agencyAddress",
        "agencyBilling",
        "invoiceTo",
        "billingName",
    )
    for key in merge_keys:
        if key in fields:
            stay[key] = fields[key]

    guest_name = _hotel_str(stay.get("guestName") or stay.get("guest_name"), 160)
    first = _hotel_str(stay.get("firstName") or stay.get("first_name"), 80)
    last = _hotel_str(stay.get("lastName") or stay.get("last_name"), 80)
    if guest_name and not (first or last):
        parts = guest_name.split()
        first = parts[0] if parts else ""
        last = " ".join(parts[1:]) if len(parts) > 1 else ""
        stay["firstName"] = first
        stay["lastName"] = last
    if not guest_name and (first or last):
        guest_name = " ".join(p for p in (first, last) if p).strip()
        stay["guestName"] = guest_name

    stay["checkInDate"] = check_in
    stay["checkOutDate"] = check_out
    try:
        start = datetime.strptime(check_in, "%Y-%m-%d")
        end = datetime.strptime(check_out, "%Y-%m-%d")
        stay["nights"] = max(1, (end - start).days)
    except ValueError:
        stay["nights"] = max(1, int(stay.get("nights") or 1))

    if stay.get("agencyBilling") and stay.get("agencyName"):
        stay["invoiceTo"] = stay.get("invoiceTo") or stay.get("agencyName")
        stay["billingName"] = stay.get("billingName") or stay.get("agencyName")

    return save_hotel_room_checkin(conn, room_id, stay, status="reserved")


def _new_hotel_merge_group_id():
    return f"hmg_{datetime.now().strftime('%Y%m%d%H%M%S')}_{os.getpid() % 10000:04d}"


def _hotel_find_room(rooms, room_id):
    target = str(room_id or "").strip()
    if not target:
        return None
    for room in rooms or []:
        if not isinstance(room, dict):
            continue
        if room.get("id") == target or room.get("number") == target:
            return room
    return None


def _hotel_room_merge_group_id(room):
    if not isinstance(room, dict):
        return ""
    return str(room.get("mergeGroupId") or "").strip()


def _hotel_rooms_in_merge_group(rooms, group_id):
    gid = str(group_id or "").strip()
    if not gid:
        return []
    return [
        r
        for r in (rooms or [])
        if isinstance(r, dict) and str(r.get("mergeGroupId") or "").strip() == gid
    ]


def _hotel_clear_room_merge_fields(room):
    if not isinstance(room, dict):
        return
    room.pop("mergeGroupId", None)
    room.pop("mergePrimary", None)


def _hotel_member_stay_from_occupied(stay, billing_room_id):
    """Keep guest display fields; strip billing to the primary room."""
    member = dict(stay) if isinstance(stay, dict) else {}
    member["billingRoomId"] = str(billing_room_id or "").strip()
    member["mergeRole"] = "member"
    member["folioCharges"] = []
    member["payments"] = []
    member["advancePaid"] = 0
    member["checkInAdvancePaid"] = 0
    member["invoiceNumber"] = ""
    member["invoiceGenerated"] = False
    member["invoiceGeneratedAt"] = ""
    # Room rate kept for display on board; normalize zeros money via mergeRole.
    return _normalize_hotel_room_stay(member)


def _hotel_stay_room_charge_amount(stay):
    stay = stay if isinstance(stay, dict) else {}
    try:
        nights = max(1, int(float(stay.get("nights") or 1)))
    except (TypeError, ValueError):
        nights = 1
    overstay = _hotel_overstay_extra_nights(stay)
    billable = max(1, nights + overstay)
    try:
        rate = float(stay.get("roomRate") or 0)
    except (TypeError, ValueError):
        rate = 0.0
    extras = 0.0
    for key in ("extraBedAmount", "earlyCheckinAmount", "lateCheckoutAmount"):
        try:
            extras += float(stay.get(key) or 0)
        except (TypeError, ValueError):
            pass
    return round(rate * billable + extras, 2)


def enrich_hotel_room_merge_fields(room, rooms=None):
    """Attach merge display helpers onto a room dict (mutates a copy-friendly dict)."""
    if not isinstance(room, dict):
        return room
    result = room
    group_id = _hotel_room_merge_group_id(result)
    stay = result.get("stay") if isinstance(result.get("stay"), dict) else {}
    billing_id = str(stay.get("billingRoomId") or "").strip()
    is_member = bool(stay.get("mergeRole") == "member" or billing_id)
    is_primary = bool(group_id and result.get("mergePrimary") and not is_member)
    result["isMergeMember"] = is_member
    result["isMergePrimary"] = is_primary
    result["billingRoomId"] = billing_id or (result.get("id") if is_primary else "")
    result["billingRoomNumber"] = ""
    result["mergeLabel"] = ""
    result["mergePartnerNumbers"] = []
    if not group_id and not is_member:
        return result
    peers = _hotel_rooms_in_merge_group(rooms, group_id) if rooms is not None else []
    if rooms is None and group_id:
        # Caller didn't pass layout rooms — leave partners empty.
        peers = [result]
    numbers = []
    primary_number = ""
    for peer in peers:
        num = str(peer.get("number") or "").strip()
        if num:
            numbers.append(num)
        if peer.get("mergePrimary"):
            primary_number = num or primary_number
        if billing_id and (
            peer.get("id") == billing_id or peer.get("number") == billing_id
        ):
            result["billingRoomNumber"] = num
    if is_primary:
        result["billingRoomNumber"] = str(result.get("number") or "")
        partners = [n for n in numbers if n != str(result.get("number") or "")]
        result["mergePartnerNumbers"] = partners
        if partners:
            result["mergeLabel"] = f"{result.get('number')} + {' + '.join(partners)}"
        else:
            result["mergeLabel"] = str(result.get("number") or "")
    elif is_member:
        if not result["billingRoomNumber"] and primary_number:
            result["billingRoomNumber"] = primary_number
        result["mergePartnerNumbers"] = [
            n for n in numbers if n != str(result.get("number") or "")
        ]
        bill = result.get("billingRoomNumber") or primary_number or "—"
        result["mergeLabel"] = f"Bill: {bill}"
    if rooms is not None and (is_member or is_primary):
        _hotel_overlay_merge_shared_bill_view(result, rooms)
    return result


def _hotel_snapshot_merge_rooms_on_stay(room, rooms=None):
    """Persist merged room numbers onto the stay for invoice/print after demerge.

    Prefer live merge peers when available; otherwise keep an existing snapshot.
    """
    if not isinstance(room, dict):
        return room
    stay = room.get("stay") if isinstance(room.get("stay"), dict) else None
    if not stay:
        return room
    stay = dict(stay)
    primary_num = _hotel_str(room.get("number"), 20)
    numbers = []
    enriched = enrich_hotel_room_merge_fields(dict(room), rooms)
    partners = list(enriched.get("mergePartnerNumbers") or [])
    if primary_num:
        numbers.append(primary_num)
    for partner in partners:
        num = _hotel_str(partner, 20)
        if num and num not in numbers:
            numbers.append(num)
    if len(numbers) <= 1:
        existing = stay.get("mergeRoomNumbers") or stay.get("merge_room_numbers") or []
        if isinstance(existing, (list, tuple)) and len(existing) > 1:
            numbers = []
            for item in existing[:20]:
                num = _hotel_str(item, 20)
                if num and num not in numbers:
                    numbers.append(num)
        elif stay.get("mergeRoomLabel") or stay.get("merge_room_label"):
            # Keep prior label/numbers if still present after normalize.
            room["stay"] = stay
            return room
    if len(numbers) > 1:
        stay["mergeRoomNumbers"] = numbers
        stay["mergeRoomLabel"] = " + ".join(numbers)
    room["stay"] = stay
    return room


def merge_hotel_room_billing(conn, from_room_id, to_room_id, note=""):
    """Combine two rooms onto ``to_room_id`` as the billing primary.

    Any rooms may be merged (vacant included). Folio/payments/room charges from
    the member (from) move onto the primary (to) when a stay exists.
    Unmerge later does not reverse the folio combine.
    """
    layout = get_hotel_rooms_layout(conn)
    rooms = layout.get("rooms") or []
    source = _hotel_find_room(rooms, from_room_id)
    primary = _hotel_find_room(rooms, to_room_id)
    if not source:
        raise ValueError("Source room not found.")
    if not primary:
        raise ValueError("Destination room not found.")
    if source.get("id") == primary.get("id"):
        raise ValueError("Choose two different rooms to merge.")
    source_stay = source.get("stay") if isinstance(source.get("stay"), dict) else None
    primary_stay = primary.get("stay") if isinstance(primary.get("stay"), dict) else None
    if source_stay and (
        source_stay.get("mergeRole") == "member" or source_stay.get("billingRoomId")
    ):
        raise ValueError(
            f"Room {source.get('number')} is already billed with another room. Unmerge it first."
        )
    if primary_stay and (
        primary_stay.get("mergeRole") == "member" or primary_stay.get("billingRoomId")
    ):
        raise ValueError(
            f"Room {primary.get('number')} is a merge member. Make it primary or unmerge first."
        )
    if source.get("mergePrimary") is False and _hotel_room_merge_group_id(source):
        raise ValueError(
            f"Room {source.get('number')} is already billed with another room. Unmerge it first."
        )
    if primary.get("mergePrimary") is False and _hotel_room_merge_group_id(primary):
        raise ValueError(
            f"Room {primary.get('number')} is a merge member. Make it primary or unmerge first."
        )

    # Primary always holds the shared bill — create an empty stay shell if needed.
    if not primary_stay:
        primary_stay = _normalize_hotel_room_stay({})
    else:
        primary_stay = _normalize_hotel_room_stay(primary_stay)
    if source_stay:
        source_stay = _normalize_hotel_room_stay(source_stay)

    # Absorb existing primary group if any; reject if source is already a different primary with members
    # without absorbing — we absorb source's group members onto this primary too.
    source_group = _hotel_room_merge_group_id(source)
    primary_group = _hotel_room_merge_group_id(primary)
    absorb_ids = {str(source.get("id"))}
    if source_group:
        for r in _hotel_rooms_in_merge_group(rooms, source_group):
            absorb_ids.add(str(r.get("id")))
    if primary_group:
        for r in _hotel_rooms_in_merge_group(rooms, primary_group):
            absorb_ids.add(str(r.get("id")))

    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    note_text = _hotel_str(note, 200)
    folio = list(primary_stay.get("folioCharges") or [])
    payments = list(primary_stay.get("payments") or [])

    def _absorb_member_charges(member_room, member_stay):
        nonlocal folio, payments, primary_stay
        if member_room.get("id") == primary.get("id"):
            return
        member_stay = _normalize_hotel_room_stay(member_stay)
        if member_stay.get("mergeRole") == "member":
            # Already stripped — just re-link.
            return
        room_charge = _hotel_stay_room_charge_amount(member_stay)
        for line in member_stay.get("folioCharges") or []:
            moved = dict(line)
            moved["sourceRoomId"] = member_room.get("id") or ""
            moved["sourceRoomNumber"] = member_room.get("number") or ""
            existing_note = moved.get("note") or ""
            tag = f"Merged from Room {member_room.get('number')}"
            moved["note"] = (existing_note + " | " if existing_note else "") + tag
            moved["note"] = moved["note"][:200]
            folio.append(moved)
        if room_charge > 0:
            folio.append(
                {
                    "id": f"mrg-{member_room.get('id')}-{stamp.replace(' ', '')}",
                    "kind": "other",
                    "label": f"Room {member_room.get('number')} — stay charges",
                    "amount": room_charge,
                    "source": "room_merge",
                    "invoiceId": "",
                    "outlet": "",
                    "at": stamp,
                    "note": note_text or f"Merged from Room {member_room.get('number')}",
                    "sourceRoomId": member_room.get("id") or "",
                    "sourceRoomNumber": member_room.get("number") or "",
                }
            )
        for pay in member_stay.get("payments") or []:
            payments.append(dict(pay))
        # Fold check-in advance into primary check-in advance.
        try:
            member_adv = float(member_stay.get("checkInAdvancePaid") or 0)
        except (TypeError, ValueError):
            member_adv = 0.0
        try:
            primary_adv = float(primary_stay.get("checkInAdvancePaid") or 0)
        except (TypeError, ValueError):
            primary_adv = 0.0
        if member_adv > 0:
            primary_stay["checkInAdvancePaid"] = round(primary_adv + member_adv, 2)

    # Absorb every non-primary room in the combined set.
    for rid in list(absorb_ids):
        member_room = _hotel_find_room(rooms, rid)
        if not member_room or member_room.get("id") == primary.get("id"):
            continue
        mstay = member_room.get("stay") if isinstance(member_room.get("stay"), dict) else None
        if not mstay:
            continue
        # If this room was already a member of primary's group, skip charge move.
        if (
            _hotel_room_merge_group_id(member_room) == primary_group
            and primary_group
            and not member_room.get("mergePrimary")
        ):
            continue
        _absorb_member_charges(member_room, mstay)

    primary_stay["folioCharges"] = folio
    primary_stay["payments"] = payments
    primary_stay["mergeRole"] = "primary"
    primary_stay["billingRoomId"] = ""

    # Fill missing guest / stay-window fields from absorbed members.
    for rid in list(absorb_ids):
        member_room = _hotel_find_room(rooms, rid)
        if not member_room or member_room.get("id") == primary.get("id"):
            continue
        mstay = member_room.get("stay") if isinstance(member_room.get("stay"), dict) else None
        if not mstay:
            continue
        for key in (
            "title",
            "firstName",
            "lastName",
            "guestName",
            "mobile",
            "mobileCountry",
            "email",
            "address",
            "city",
            "state",
            "country",
            "pin",
            "idType",
            "idNumber",
            "agencyName",
            "agencyGst",
            "agencyAddress",
            "agencyBilling",
            "invoiceTo",
            "billingName",
            "checkInDate",
            "checkInTime",
            "checkOutDate",
            "nights",
            "adults",
            "children",
            "bookingNumber",
            "bookingDate",
            "checkedInAt",
        ):
            if not primary_stay.get(key) and mstay.get(key) not in (None, "", [], {}):
                primary_stay[key] = mstay.get(key)

    primary_stay = _normalize_hotel_room_stay(primary_stay)
    primary["stay"] = primary_stay
    occupy = (
        _hotel_stay_guest_richness(primary_stay) > 0
        or _hotel_room_has_inhouse_stay({"stay": primary_stay, "status": "occupied"})
    )
    primary["status"] = "occupied" if occupy else "vacant"

    group_id = primary_group or source_group or _new_hotel_merge_group_id()
    primary["mergeGroupId"] = group_id
    primary["mergePrimary"] = True

    for rid in absorb_ids:
        member_room = _hotel_find_room(rooms, rid)
        if not member_room:
            continue
        if member_room.get("id") == primary.get("id"):
            continue
        mstay = member_room.get("stay") if isinstance(member_room.get("stay"), dict) else {}
        member_room["stay"] = _hotel_member_stay_from_occupied(mstay, primary.get("id"))
        member_room["mergeGroupId"] = group_id
        member_room["mergePrimary"] = False
        member_room["status"] = "occupied" if occupy else "vacant"

    _hotel_sync_merge_group_shared_data(rooms)

    saved = save_hotel_rooms_layout(conn, layout.get("floors") or [], rooms)
    primary_out = get_hotel_room(conn, primary.get("id"))
    source_out = get_hotel_room(conn, source.get("id"))
    if primary_out:
        enrich_hotel_room_merge_fields(primary_out, saved.get("rooms"))
    if source_out:
        enrich_hotel_room_merge_fields(source_out, saved.get("rooms"))
    return {
        "primaryRoom": primary_out,
        "memberRoom": source_out,
        "room": primary_out,
        "layout": saved,
    }


def unmerge_hotel_rooms(conn, room_id, scope="one"):
    """Clear merge links. Does not reverse folio combine on the primary."""
    layout = get_hotel_rooms_layout(conn)
    rooms = layout.get("rooms") or []
    room = _hotel_find_room(rooms, room_id)
    if not room:
        raise ValueError("Room not found.")
    group_id = _hotel_room_merge_group_id(room)
    stay = room.get("stay") if isinstance(room.get("stay"), dict) else {}
    if not group_id and not stay.get("billingRoomId") and stay.get("mergeRole") != "member":
        raise ValueError("Room is not part of a merge group.")

    scope_key = str(scope or "one").strip().lower()
    was_primary = bool(room.get("mergePrimary"))
    # Unmerging the billing primary must dissolve the whole group. Clearing only
    # the primary leaves members with mergeRole=member, which hides them on the board.
    dissolve_group = scope_key in ("group", "all", "everything") or (
        was_primary and bool(group_id)
    )
    if dissolve_group:
        targets = _hotel_rooms_in_merge_group(rooms, group_id) if group_id else [room]
    else:
        targets = [room]

    for target in targets:
        tstay = target.get("stay") if isinstance(target.get("stay"), dict) else None
        if tstay:
            tstay = dict(tstay)
            tstay["billingRoomId"] = ""
            tstay["mergeRole"] = ""
            target["stay"] = _normalize_hotel_room_stay(tstay)
        _hotel_clear_room_merge_fields(target)

    # If we removed only a member, leave the rest of the group intact.
    if not dissolve_group and group_id and not was_primary:
        remaining = _hotel_rooms_in_merge_group(rooms, group_id)
        if len(remaining) <= 1:
            for peer in remaining:
                pstay = peer.get("stay") if isinstance(peer.get("stay"), dict) else None
                if pstay:
                    pstay = dict(pstay)
                    pstay["billingRoomId"] = ""
                    pstay["mergeRole"] = ""
                    peer["stay"] = _normalize_hotel_room_stay(pstay)
                _hotel_clear_room_merge_fields(peer)

    saved = save_hotel_rooms_layout(conn, layout.get("floors") or [], rooms)
    out = get_hotel_room(conn, room.get("id"))
    if out:
        enrich_hotel_room_merge_fields(out, saved.get("rooms"))
    return {"room": out, "layout": saved}


def set_hotel_merge_primary(conn, room_id):
    """Make an occupied merge member the new billing primary; move folio/invoice."""
    layout = get_hotel_rooms_layout(conn)
    rooms = layout.get("rooms") or []
    new_primary = _hotel_find_room(rooms, room_id)
    if not new_primary:
        raise ValueError("Room not found.")
    group_id = _hotel_room_merge_group_id(new_primary)
    if not group_id:
        raise ValueError("Room is not part of a merge group.")
    if _normalize_hotel_room_status(new_primary.get("status")) != "occupied":
        raise ValueError("Only occupied rooms can become the billing primary.")
    new_stay = new_primary.get("stay") if isinstance(new_primary.get("stay"), dict) else None
    if not new_stay:
        raise ValueError("Room has no active stay.")
    if new_primary.get("mergePrimary") and new_stay.get("mergeRole") != "member":
        return {"room": get_hotel_room(conn, new_primary.get("id")), "layout": layout}

    old_primary = None
    for peer in _hotel_rooms_in_merge_group(rooms, group_id):
        if peer.get("mergePrimary"):
            old_primary = peer
            break
    if not old_primary:
        raise ValueError("Could not find the current billing primary.")
    if old_primary.get("id") == new_primary.get("id"):
        return {"room": get_hotel_room(conn, new_primary.get("id")), "layout": layout}

    old_stay = old_primary.get("stay") if isinstance(old_primary.get("stay"), dict) else {}
    old_stay = _normalize_hotel_room_stay(old_stay)
    # Move billing payload onto the new primary while keeping its guest identity.
    guest_keys = (
        "title",
        "firstName",
        "lastName",
        "guestName",
        "gender",
        "dateOfBirth",
        "nationality",
        "mobileCountry",
        "mobile",
        "email",
        "address",
        "city",
        "state",
        "country",
        "pin",
        "purposeOfVisit",
        "vipStatus",
        "returningGuest",
        "idType",
        "idNumber",
        "idIssueDate",
        "idExpiryDate",
        "idPlaceOfIssue",
        "idDocumentName",
        "idDocumentPath",
        "idDocumentMime",
        "additionalGuests",
        "agencyName",
        "agencyGst",
        "agencyAddress",
        "agencyBilling",
        "invoiceTo",
        "billingName",
        "profession",
        "company",
        "loyaltyNumber",
        "notes",
        "checkInDate",
        "checkInTime",
        "checkOutDate",
        "nights",
        "adults",
        "children",
        "ratePlan",
        "roomRate",
        "totalRate",
        "specialRequests",
        "additionalRequests",
        "extraBedQty",
        "extraBedRate",
        "extraBedNights",
        "extraBedAmount",
        "extraBedNote",
        "earlyCheckinQty",
        "earlyCheckinRate",
        "earlyCheckinNights",
        "earlyCheckinAmount",
        "earlyCheckinNote",
        "lateCheckoutQty",
        "lateCheckoutRate",
        "lateCheckoutNights",
        "lateCheckoutAmount",
        "lateCheckoutNote",
        "checkedInAt",
        "transferCount",
        "transferHistory",
        "bookingNumber",
        "bookingDate",
    )
    display = _normalize_hotel_room_stay(new_stay)
    moved = dict(old_stay)
    for key in guest_keys:
        if key in display:
            moved[key] = display.get(key)
    moved["billingRoomId"] = ""
    moved["mergeRole"] = "primary"
    new_primary["stay"] = _normalize_hotel_room_stay(moved)
    new_primary["mergeGroupId"] = group_id
    new_primary["mergePrimary"] = True

    old_primary["stay"] = _hotel_member_stay_from_occupied(old_stay, new_primary.get("id"))
    old_primary["mergeGroupId"] = group_id
    old_primary["mergePrimary"] = False

    for peer in _hotel_rooms_in_merge_group(rooms, group_id):
        if peer.get("id") in (new_primary.get("id"), old_primary.get("id")):
            continue
        pstay = peer.get("stay") if isinstance(peer.get("stay"), dict) else {}
        pstay = dict(pstay)
        pstay["billingRoomId"] = new_primary.get("id")
        pstay["mergeRole"] = "member"
        peer["stay"] = _normalize_hotel_room_stay(pstay)
        peer["mergePrimary"] = False

    if old_stay.get("invoiceNumber"):
        upsert_hotel_room_invoice_from_room(conn, new_primary)

    saved = save_hotel_rooms_layout(conn, layout.get("floors") or [], rooms)
    out = get_hotel_room(conn, new_primary.get("id"))
    if out:
        enrich_hotel_room_merge_fields(out, saved.get("rooms"))
    return {"room": out, "layout": saved}


def clear_hotel_room_stay(conn, room_id, status="dirty"):
    """Clear stay data and set post-checkout status.

    Primary checkout clears the entire merge group. Member checkout unmerges
    that room only, then clears it (primary bill unchanged).
    """
    layout = get_hotel_rooms_layout(conn)
    rooms = layout.get("rooms") or []
    target = _hotel_find_room(rooms, room_id)
    if not target:
        raise ValueError("Room not found.")

    group_id = _hotel_room_merge_group_id(target)
    stay = target.get("stay") if isinstance(target.get("stay"), dict) else None
    is_member = bool(
        stay and (stay.get("mergeRole") == "member" or stay.get("billingRoomId"))
    )
    is_primary = bool(group_id and target.get("mergePrimary") and not is_member)

    to_clear = [target]
    if is_primary and group_id:
        to_clear = _hotel_rooms_in_merge_group(rooms, group_id)
    elif is_member:
        # Leave shared bill; drop this room from the group first.
        if stay:
            stay = dict(stay)
            stay["billingRoomId"] = ""
            stay["mergeRole"] = ""
            target["stay"] = stay
        _hotel_clear_room_merge_fields(target)
        remaining = _hotel_rooms_in_merge_group(rooms, group_id) if group_id else []
        if len(remaining) <= 1:
            for peer in remaining:
                pstay = peer.get("stay") if isinstance(peer.get("stay"), dict) else None
                if pstay:
                    pstay = dict(pstay)
                    pstay["billingRoomId"] = ""
                    pstay["mergeRole"] = ""
                    peer["stay"] = pstay
                _hotel_clear_room_merge_fields(peer)

    for room in to_clear:
        stay = room.get("stay") if isinstance(room.get("stay"), dict) else None
        if stay and (stay.get("invoiceNumber") or stay.get("invoice_number")):
            upsert_hotel_room_invoice_from_room(conn, room)
        room.pop("stay", None)
        _hotel_clear_room_merge_fields(room)
        room["status"] = _normalize_hotel_room_status(status)
    return save_hotel_rooms_layout(conn, layout.get("floors") or [], rooms)


def transfer_hotel_room_stay(conn, from_room_id, to_room_id, note=""):
    """Move an in-house stay to another vacant room.

    Source becomes dirty (cleared). Destination becomes occupied with the stay.
    Only vacant rooms are accepted as transfer targets.

    Merge-aware:
    - Member transfer keeps billingRoomId and remaps mergeGroupId onto the new room.
    - Primary transfer remaps mergePrimary and all members' billingRoomId.
    """
    layout = get_hotel_rooms_layout(conn)
    rooms = layout.get("rooms") or []
    from_id = str(from_room_id or "").strip()
    to_id = str(to_room_id or "").strip()
    if not from_id or not to_id:
        raise ValueError("Source and destination rooms are required.")
    if from_id == to_id:
        raise ValueError("Choose a different room to transfer to.")

    source = _hotel_find_room(rooms, from_id)
    destination = _hotel_find_room(rooms, to_id)

    if not source:
        raise ValueError("Source room not found.")
    if not destination:
        raise ValueError("Destination room not found.")

    source_status = _normalize_hotel_room_status(source.get("status"))
    stay = source.get("stay")
    if source_status != "occupied" or not isinstance(stay, dict) or not stay:
        raise ValueError("Only occupied rooms with a checked-in guest can be transferred.")

    dest_status = _normalize_hotel_room_status(destination.get("status"))
    if dest_status != "vacant":
        raise ValueError("Guest can only be transferred to a vacant room.")
    if isinstance(destination.get("stay"), dict) and destination.get("stay"):
        raise ValueError("Destination room already has guest details.")

    moved = _normalize_hotel_room_stay(dict(stay))
    note_text = _hotel_str(note, 400)
    if note_text:
        existing = moved.get("notes") or ""
        moved["notes"] = (
            (existing + " | " if existing else "") + "Transfer: " + note_text
        )[:500]
    history = moved.get("transferHistory")
    if not isinstance(history, list):
        history = []
    history.append(
        {
            "fromRoomId": source.get("id"),
            "fromRoomNumber": source.get("number"),
            "toRoomId": destination.get("id"),
            "toRoomNumber": destination.get("number"),
            "at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "note": note_text,
        }
    )
    moved["transferHistory"] = history[-20:]
    moved["transferCount"] = len(moved["transferHistory"])

    group_id = _hotel_room_merge_group_id(source)
    was_primary = bool(source.get("mergePrimary") and moved.get("mergeRole") != "member")
    was_member = bool(moved.get("mergeRole") == "member" or moved.get("billingRoomId"))

    if was_primary and group_id:
        # Remap members to the new primary room id.
        for peer in _hotel_rooms_in_merge_group(rooms, group_id):
            if peer.get("id") == source.get("id"):
                continue
            pstay = peer.get("stay") if isinstance(peer.get("stay"), dict) else None
            if not pstay:
                continue
            pstay = dict(pstay)
            pstay["billingRoomId"] = destination.get("id")
            pstay["mergeRole"] = "member"
            peer["stay"] = _normalize_hotel_room_stay(pstay)
        destination["mergeGroupId"] = group_id
        destination["mergePrimary"] = True
        moved["mergeRole"] = "primary"
        moved["billingRoomId"] = ""
    elif was_member and group_id:
        destination["mergeGroupId"] = group_id
        destination["mergePrimary"] = False
        # billingRoomId already on stay
    else:
        _hotel_clear_room_merge_fields(destination)

    destination["stay"] = moved
    destination["status"] = "occupied"
    if moved.get("invoiceNumber"):
        upsert_hotel_room_invoice_from_room(conn, destination)

    source.pop("stay", None)
    _hotel_clear_room_merge_fields(source)
    source["status"] = "dirty"

    saved = save_hotel_rooms_layout(conn, layout.get("floors") or [], rooms)
    from_room = None
    to_room = None
    for room in saved.get("rooms") or []:
        if room.get("id") == source.get("id"):
            from_room = room
        if room.get("id") == destination.get("id"):
            to_room = room
    if not from_room or not to_room:
        raise ValueError("Transfer failed.")
    floors = {f.get("id"): f for f in (saved.get("floors") or []) if isinstance(f, dict)}
    for room in (from_room, to_room):
        floor = floors.get(room.get("floorId")) or {}
        room["floorName"] = floor.get("name") or room.get("floorId") or ""
        room["statusLabel"] = HOTEL_ROOM_STATUS_LABELS.get(
            room.get("status"), room.get("status")
        )
        enrich_hotel_room_merge_fields(room, saved.get("rooms"))
    return {"fromRoom": from_room, "toRoom": to_room}


def update_hotel_room_status(conn, room_id, status, extras=None):
    """Update one room's status; returns normalized layout.

    For reserved, optional extras may include checkInDate / checkOutDate / asOf
    so the reservation covers the night the operator is viewing.

    Occupied → Dirty is allowed: it checks the guest out and leaves the room Dirty
    (same end state as checkout). Vacant while checked-in remains blocked.
    """
    layout = get_hotel_rooms_layout(conn)
    rooms = layout.get("rooms") or []
    target = str(room_id or "").strip()
    next_status = _normalize_hotel_room_status(status)
    extras = extras if isinstance(extras, dict) else {}
    found = False
    for room in rooms:
        if room.get("id") == target or room.get("number") == target:
            prev_status = _normalize_hotel_room_status(room.get("status"))
            in_house = prev_status == "occupied" or _hotel_room_has_inhouse_stay(room)
            # Dirty while occupied = force checkout + dirty housekeeping.
            if next_status == "dirty" and in_house:
                return clear_hotel_room_stay(conn, room_id, status="dirty")
            # Other status changes stay blocked until FO checkout clears the stay.
            if next_status != "occupied" and in_house:
                raise ValueError(
                    "Guest is still checked in. Check out the room before changing status."
                )
            group_id = str(room.get("mergeGroupId") or "").strip()
            if next_status in ("vacant", "dirty") and group_id:
                peers = [
                    r
                    for r in rooms
                    if isinstance(r, dict)
                    and str(r.get("mergeGroupId") or "").strip() == group_id
                ]
                occupied_others = [
                    r
                    for r in peers
                    if r.get("id") != room.get("id")
                    and _normalize_hotel_room_status(r.get("status")) == "occupied"
                ]
                if occupied_others:
                    numbers = ", ".join(
                        str(r.get("number") or r.get("id") or "")
                        for r in occupied_others
                        if r.get("number") or r.get("id")
                    )
                    raise ValueError(
                        "This room is merged with occupied Room "
                        f"{numbers}. Unmerge or check out those rooms before "
                        "marking it vacant or dirty."
                    )
                # Empty merge group becoming vacant/dirty — drop merge links.
                if room.get("mergePrimary") or next_status == "vacant":
                    for peer in peers:
                        peer.pop("mergeGroupId", None)
                        peer.pop("mergePrimary", None)
                        pstay = peer.get("stay") if isinstance(peer.get("stay"), dict) else None
                        if pstay:
                            pstay = dict(pstay)
                            pstay["billingRoomId"] = ""
                            pstay["mergeRole"] = ""
                            peer["stay"] = _normalize_hotel_room_stay(pstay)
                        if peer.get("id") != room.get("id"):
                            peer["status"] = next_status
            room["status"] = next_status
            if next_status == "reserved":
                check_in = _hotel_str(
                    extras.get("checkInDate")
                    or extras.get("check_in_date")
                    or extras.get("asOf")
                    or extras.get("as_of"),
                    20,
                )[:10]
                check_out = _hotel_str(
                    extras.get("checkOutDate") or extras.get("check_out_date"),
                    20,
                )[:10]
                if check_in and len(check_in) >= 10:
                    check_in = check_in[:10]
                    if not check_out or len(check_out) < 10:
                        try:
                            base = datetime.strptime(check_in, "%Y-%m-%d")
                            check_out = (base + timedelta(days=1)).strftime("%Y-%m-%d")
                        except ValueError:
                            check_out = ""
                    else:
                        check_out = check_out[:10]
                    stay = room.get("stay") if isinstance(room.get("stay"), dict) else {}
                    stay = dict(stay)
                    stay["checkInDate"] = check_in
                    if check_out:
                        stay["checkOutDate"] = check_out
                    room["stay"] = _normalize_hotel_room_stay(stay)
            found = True
            break
    if not found:
        raise ValueError("Room not found.")
    return save_hotel_rooms_layout(conn, layout.get("floors") or [], rooms)


def get_hotel_room(conn, room_id):
    """Return one room dict plus floor name, or None."""
    layout = get_hotel_rooms_layout(conn)
    target = str(room_id or "").strip()
    if not target:
        return None
    floors = {f.get("id"): f for f in (layout.get("floors") or []) if isinstance(f, dict)}
    for room in layout.get("rooms") or []:
        if not isinstance(room, dict):
            continue
        if room.get("id") == target or room.get("number") == target:
            floor = floors.get(room.get("floorId")) or {}
            result = dict(room)
            result["floorName"] = floor.get("name") or room.get("floorId") or ""
            result["statusLabel"] = HOTEL_ROOM_STATUS_LABELS.get(
                result.get("status"), result.get("status")
            )
            enrich_hotel_room_merge_fields(result, layout.get("rooms"))
            return result
    return None


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
            email           TEXT    NOT NULL DEFAULT '',
            failed_login_attempts INTEGER NOT NULL DEFAULT 0,
            captcha_required INTEGER NOT NULL DEFAULT 0,
            locked_at       TEXT,
            unlock_token_hash TEXT,
            unlock_token_expires_at TEXT,
            created_at      TEXT    NOT NULL,
            updated_at      TEXT    NOT NULL
        )
    """)
    existing_user_cols = {
        row["name"] for row in cursor.execute("PRAGMA table_info(users)").fetchall()
    }
    if "email" not in existing_user_cols:
        cursor.execute("ALTER TABLE users ADD COLUMN email TEXT NOT NULL DEFAULT ''")
    if "failed_login_attempts" not in existing_user_cols:
        cursor.execute(
            "ALTER TABLE users ADD COLUMN failed_login_attempts INTEGER NOT NULL DEFAULT 0"
        )
    if "captcha_required" not in existing_user_cols:
        cursor.execute(
            "ALTER TABLE users ADD COLUMN captcha_required INTEGER NOT NULL DEFAULT 0"
        )
    if "locked_at" not in existing_user_cols:
        cursor.execute("ALTER TABLE users ADD COLUMN locked_at TEXT")
    if "unlock_token_hash" not in existing_user_cols:
        cursor.execute("ALTER TABLE users ADD COLUMN unlock_token_hash TEXT")
    if "unlock_token_expires_at" not in existing_user_cols:
        cursor.execute("ALTER TABLE users ADD COLUMN unlock_token_expires_at TEXT")

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
            ("admin", "Administrator", auth_security.hash_password("admin"), now, now),
        )

    ensure_hotel_rooms_schema(conn)
    get_hotel_rooms_layout(conn)
    ensure_agencies_schema(conn)

    conn.commit()
    conn.close()
