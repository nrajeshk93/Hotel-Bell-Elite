"""Purchase / Expense category master — separate from POS menu categories."""

from __future__ import annotations

import re
import sqlite3

LEDGER_MODULE_PURCHASE = "purchase"
LEDGER_MODULE_EXPENSE = "expense"
LEDGER_MODULES = (LEDGER_MODULE_PURCHASE, LEDGER_MODULE_EXPENSE)

POS_MODULE_RESTAURANT = "restaurant"
POS_MODULE_BAR = "bar"

CATEGORY_MASTER_MODULES = (
    (POS_MODULE_RESTAURANT, "Restaurant"),
    (POS_MODULE_BAR, "Bar"),
    (LEDGER_MODULE_PURCHASE, "Purchase"),
    (LEDGER_MODULE_EXPENSE, "Expense"),
)
CATEGORY_MASTER_MODULE_LABELS = dict(CATEGORY_MASTER_MODULES)
LEDGER_MODULE_LABELS = {
    LEDGER_MODULE_PURCHASE: "Purchase",
    LEDGER_MODULE_EXPENSE: "Expense",
}

SOURCE_POS = "pos"
SOURCE_LEDGER = "pe"


def slugify_ledger_category_key(name):
    value = (name or "").strip().lower()
    value = value.replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    if not value:
        return ""
    if value[0].isdigit():
        value = "cat_" + value
    return value[:80]


def encode_category_master_id(source, raw_id):
    return f"{source}:{int(raw_id)}"


def parse_category_master_id(raw):
    value = str(raw or "").strip()
    if value.startswith("pos:"):
        try:
            return SOURCE_POS, int(value[4:])
        except (TypeError, ValueError):
            return None, None
    if value.startswith("pe:"):
        try:
            return SOURCE_LEDGER, int(value[3:])
        except (TypeError, ValueError):
            return None, None
    if value.isdigit():
        return SOURCE_POS, int(value)
    return None, None


def normalize_ledger_module(module):
    value = str(module or "").strip().lower()
    if value in LEDGER_MODULES:
        return value
    return ""


def normalize_category_master_module(module):
    value = str(module or "").strip().lower()
    if value in CATEGORY_MASTER_MODULE_LABELS:
        return value
    return POS_MODULE_RESTAURANT


def _table_columns(conn, table):
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    names = []
    for row in rows:
        if isinstance(row, sqlite3.Row):
            names.append(row["name"])
        else:
            names.append(row[1])
    return names


def _row_value(row, key, index=0):
    if row is None:
        return None
    if isinstance(row, sqlite3.Row):
        try:
            return row[key]
        except (IndexError, KeyError):
            return row[index]
    if isinstance(row, dict):
        return row.get(key)
    return row[index]


def ensure_expense_category_modules(conn, builtin_categories=None):
    """Migrate expense_categories onto (module, category_key) and seed builtins."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS expense_categories (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            category_key  TEXT    NOT NULL,
            name          TEXT    NOT NULL COLLATE NOCASE,
            module        TEXT    NOT NULL DEFAULT 'expense',
            sort_order    INTEGER NOT NULL DEFAULT 0,
            is_active     INTEGER NOT NULL DEFAULT 1,
            created_at    TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        )
        """
    )
    cols = _table_columns(conn, "expense_categories")
    if "module" not in cols:
        conn.execute(
            """
            CREATE TABLE expense_categories_cm_new (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                category_key  TEXT    NOT NULL,
                name          TEXT    NOT NULL COLLATE NOCASE,
                module        TEXT    NOT NULL DEFAULT 'expense',
                sort_order    INTEGER NOT NULL DEFAULT 0,
                is_active     INTEGER NOT NULL DEFAULT 1,
                created_at    TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
            )
            """
        )
        conn.execute(
            """
            INSERT INTO expense_categories_cm_new
                (id, category_key, name, module, sort_order, is_active, created_at)
            SELECT id, category_key, name, 'expense', sort_order, is_active, created_at
            FROM expense_categories
            """
        )
        conn.execute(
            """
            INSERT INTO expense_categories_cm_new
                (category_key, name, module, sort_order, is_active, created_at)
            SELECT category_key, name, 'purchase', sort_order, is_active, created_at
            FROM expense_categories
            """
        )
        conn.execute("DROP TABLE expense_categories")
        conn.execute("ALTER TABLE expense_categories_cm_new RENAME TO expense_categories")
    conn.execute("DROP INDEX IF EXISTS idx_expense_categories_name")
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_expense_categories_module_key
        ON expense_categories(module, category_key)
        """
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_expense_categories_module_name
        ON expense_categories(module, lower(name))
        """
    )
    _clone_expense_rows_into_purchase(conn)
    if builtin_categories:
        seed_builtin_ledger_categories(conn, builtin_categories)


def _clone_expense_rows_into_purchase(conn):
    """If purchase module is empty but expense has rows, clone them once."""
    purchase_n = conn.execute(
        "SELECT COUNT(*) AS n FROM expense_categories WHERE module = ?",
        (LEDGER_MODULE_PURCHASE,),
    ).fetchone()
    if int(_row_value(purchase_n, "n", 0) or 0) > 0:
        return
    expense_n = conn.execute(
        "SELECT COUNT(*) AS n FROM expense_categories WHERE module = ?",
        (LEDGER_MODULE_EXPENSE,),
    ).fetchone()
    if int(_row_value(expense_n, "n", 0) or 0) == 0:
        return
    conn.execute(
        """
        INSERT INTO expense_categories
            (category_key, name, module, sort_order, is_active, created_at)
        SELECT category_key, name, 'purchase', sort_order, is_active, created_at
        FROM expense_categories
        WHERE module = 'expense'
        """
    )


def seed_builtin_ledger_categories(conn, builtin_categories):
    for module in LEDGER_MODULES:
        max_row = conn.execute(
            "SELECT COALESCE(MAX(sort_order), 0) AS m FROM expense_categories WHERE module = ?",
            (module,),
        ).fetchone()
        sort_order = int(_row_value(max_row, "m", 0) or 0)
        for key, label in builtin_categories:
            key = (key or "").strip()
            label = (label or "").strip()
            if not key or not label:
                continue
            existing = conn.execute(
                """
                SELECT id FROM expense_categories
                WHERE module = ? AND category_key = ?
                """,
                (module, key),
            ).fetchone()
            if existing:
                continue
            sort_order += 10
            conn.execute(
                """
                INSERT INTO expense_categories
                    (category_key, name, module, sort_order, is_active)
                VALUES (?, ?, ?, ?, 1)
                """,
                (key, label, module, sort_order),
            )


def ledger_usage_count(conn, category_key, module):
    key = (category_key or "").strip()
    module = normalize_ledger_module(module)
    if not key or not module:
        return 0
    try:
        row = conn.execute(
            """
            SELECT COUNT(*) AS n
            FROM sales_update_expenses
            WHERE TRIM(category) = ?
              AND COALESCE(NULLIF(TRIM(entry_kind), ''), 'expense') = ?
            """,
            (key, module),
        ).fetchone()
    except sqlite3.OperationalError:
        return 0
    return int(_row_value(row, "n", 0) or 0)


def list_ledger_categories(conn, module=None, include_inactive=False):
    ensure_expense_category_modules(conn)
    clauses = []
    params = []
    wanted = normalize_ledger_module(module) if module else ""
    if wanted:
        clauses.append("c.module = ?")
        params.append(wanted)
    else:
        clauses.append("c.module IN (?, ?)")
        params.extend(LEDGER_MODULES)
    if not include_inactive:
        clauses.append("c.is_active = 1")
    where = "WHERE " + " AND ".join(clauses)
    rows = conn.execute(
        f"""
        SELECT
            c.id,
            c.category_key,
            c.name,
            c.module,
            c.sort_order,
            c.is_active
        FROM expense_categories c
        {where}
        ORDER BY c.module ASC, c.sort_order ASC, lower(c.name) ASC, c.id ASC
        """,
        params,
    ).fetchall()
    items = []
    for row in rows:
        key = row["category_key"] if isinstance(row, sqlite3.Row) else row[1]
        module_value = row["module"] if isinstance(row, sqlite3.Row) else row[3]
        items.append(
            {
                "id": int(row["id"] if isinstance(row, sqlite3.Row) else row[0]),
                "category_key": key or "",
                "name": (row["name"] if isinstance(row, sqlite3.Row) else row[2]) or "",
                "module": module_value,
                "module_label": LEDGER_MODULE_LABELS.get(module_value, module_value),
                "sort_order": int(
                    (row["sort_order"] if isinstance(row, sqlite3.Row) else row[4]) or 0
                ),
                "is_active": bool(
                    row["is_active"] if isinstance(row, sqlite3.Row) else row[5]
                ),
                "item_count": ledger_usage_count(conn, key, module_value),
            }
        )
    return items


def get_ledger_category(conn, category_id, include_inactive=False):
    ensure_expense_category_modules(conn)
    try:
        raw_id = int(category_id)
    except (TypeError, ValueError):
        return None
    sql = """
        SELECT id, category_key, name, module, sort_order, is_active
        FROM expense_categories
        WHERE id = ?
    """
    params = [raw_id]
    if not include_inactive:
        sql += " AND is_active = 1"
    row = conn.execute(sql, params).fetchone()
    if not row:
        return None
    key = row["category_key"] if isinstance(row, sqlite3.Row) else row[1]
    module_value = row["module"] if isinstance(row, sqlite3.Row) else row[3]
    return {
        "id": int(row["id"] if isinstance(row, sqlite3.Row) else row[0]),
        "category_key": key or "",
        "name": (row["name"] if isinstance(row, sqlite3.Row) else row[2]) or "",
        "module": module_value,
        "module_label": LEDGER_MODULE_LABELS.get(module_value, module_value),
        "sort_order": int((row["sort_order"] if isinstance(row, sqlite3.Row) else row[4]) or 0),
        "is_active": bool(row["is_active"] if isinstance(row, sqlite3.Row) else row[5]),
        "item_count": ledger_usage_count(conn, key, module_value),
    }


def save_ledger_category(conn, *, category_id=None, name="", module=LEDGER_MODULE_EXPENSE):
    """Create or rename a purchase/expense category. Module cannot change on edit."""
    ensure_expense_category_modules(conn)
    clean_name = " ".join(str(name or "").split()).strip()
    if not clean_name:
        raise ValueError("Category name is required.")
    if len(clean_name) > 80:
        raise ValueError("Category name must be 80 characters or fewer.")

    if category_id:
        existing = get_ledger_category(conn, category_id)
        if not existing:
            raise ValueError("Category not found.")
        module = existing["module"]
        dup = conn.execute(
            """
            SELECT id FROM expense_categories
            WHERE is_active = 1 AND module = ? AND id != ? AND lower(name) = lower(?)
            """,
            (module, int(existing["id"]), clean_name),
        ).fetchone()
        if dup:
            raise ValueError("A category with this name already exists.")
        conn.execute(
            """
            UPDATE expense_categories
            SET name = ?
            WHERE id = ?
            """,
            (clean_name, int(existing["id"])),
        )
        return get_ledger_category(conn, existing["id"])

    module = normalize_ledger_module(module)
    if not module:
        raise ValueError("Select a module.")
    key = slugify_ledger_category_key(clean_name)
    if not key or not re.fullmatch(r"[a-z][a-z0-9_]{0,79}", key):
        raise ValueError("Enter a valid category name.")
    dup_name = conn.execute(
        """
        SELECT id FROM expense_categories
        WHERE is_active = 1 AND module = ? AND lower(name) = lower(?)
        """,
        (module, clean_name),
    ).fetchone()
    if dup_name:
        raise ValueError("A category with this name already exists.")
    dup_key = conn.execute(
        """
        SELECT id FROM expense_categories
        WHERE is_active = 1 AND module = ? AND category_key = ?
        """,
        (module, key),
    ).fetchone()
    if dup_key:
        raise ValueError("A category with this name already exists.")
    max_row = conn.execute(
        "SELECT COALESCE(MAX(sort_order), 0) AS m FROM expense_categories WHERE module = ?",
        (module,),
    ).fetchone()
    sort_order = int(_row_value(max_row, "m", 0) or 0) + 10
    cur = conn.execute(
        """
        INSERT INTO expense_categories (category_key, name, module, sort_order, is_active)
        VALUES (?, ?, ?, ?, 1)
        """,
        (key, clean_name, module, sort_order),
    )
    return get_ledger_category(conn, cur.lastrowid)


def soft_delete_ledger_category(conn, category_id):
    existing = get_ledger_category(conn, category_id)
    if not existing:
        raise ValueError("Category not found.")
    if existing["item_count"] > 0:
        label = existing["module_label"]
        raise ValueError(
            f"This category is used on {label.lower()} bills. Remove or recategorize those entries first."
        )
    conn.execute(
        "UPDATE expense_categories SET is_active = 0 WHERE id = ?",
        (int(existing["id"]),),
    )
    return True


def ledger_category_choices(conn, module):
    """Active (key, name) pairs for one purchase/expense module."""
    module = normalize_ledger_module(module)
    if not module:
        return []
    ensure_expense_category_modules(conn)
    rows = conn.execute(
        """
        SELECT category_key, name
        FROM expense_categories
        WHERE is_active = 1 AND module = ?
        ORDER BY sort_order, lower(name), id
        """,
        (module,),
    ).fetchall()
    items = []
    seen = set()
    for row in rows:
        key = (row["category_key"] if isinstance(row, sqlite3.Row) else row[0] or "").strip()
        label = (row["name"] if isinstance(row, sqlite3.Row) else row[1] or "").strip()
        if not key or not label or key in seen:
            continue
        items.append((key, label))
        seen.add(key)
    return items
