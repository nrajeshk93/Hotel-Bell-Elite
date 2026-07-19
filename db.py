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
        CREATE TABLE IF NOT EXISTS store_settings (
            outlet                      TEXT    NOT NULL PRIMARY KEY,
            verification_interval_days  INTEGER NOT NULL DEFAULT 7,
            updated_at                  TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        )
    """)
    for outlet in ("bar", "kitchen"):
        cursor.execute(
            "INSERT OR IGNORE INTO store_settings (outlet, verification_interval_days) VALUES (?, 7)",
            (outlet,),
        )
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
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS store_indent_lines (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            indent_id  INTEGER NOT NULL,
            item_name  TEXT    NOT NULL,
            quantity   REAL    NOT NULL DEFAULT 0,
            unit       TEXT    NOT NULL DEFAULT 'pcs',
            notes      TEXT    NOT NULL DEFAULT '',
            FOREIGN KEY (indent_id) REFERENCES store_indents(id) ON DELETE CASCADE
        )
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
            created_by    INTEGER,
            created_at    TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (created_by) REFERENCES users(id)
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_store_movements_outlet
        ON store_stock_movements(outlet, created_at DESC)
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS store_counter_transfers (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            outlet       TEXT    NOT NULL,
            transfer_no  TEXT    NOT NULL UNIQUE,
            notes        TEXT    NOT NULL DEFAULT '',
            created_by   INTEGER,
            created_at   TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (created_by) REFERENCES users(id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS store_counter_transfer_lines (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            transfer_id INTEGER NOT NULL,
            item_name   TEXT    NOT NULL,
            unit        TEXT    NOT NULL DEFAULT 'pcs',
            quantity    REAL    NOT NULL DEFAULT 0,
            FOREIGN KEY (transfer_id) REFERENCES store_counter_transfers(id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS store_stock_issues (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            outlet      TEXT    NOT NULL,
            issue_no    TEXT    NOT NULL UNIQUE,
            invoice_ref TEXT    NOT NULL DEFAULT '',
            notes       TEXT    NOT NULL DEFAULT '',
            created_by  INTEGER,
            created_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (created_by) REFERENCES users(id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS store_stock_issue_lines (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            issue_id  INTEGER NOT NULL,
            item_name TEXT    NOT NULL,
            unit      TEXT    NOT NULL DEFAULT 'pcs',
            quantity  REAL    NOT NULL DEFAULT 0,
            FOREIGN KEY (issue_id) REFERENCES store_stock_issues(id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS store_stock_verifications (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            outlet      TEXT    NOT NULL,
            verified_at TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            verified_by INTEGER,
            notes       TEXT    NOT NULL DEFAULT '',
            FOREIGN KEY (verified_by) REFERENCES users(id)
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_store_verifications_outlet
        ON store_stock_verifications(outlet, verified_at DESC)
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS store_stock_verification_lines (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            verification_id INTEGER NOT NULL,
            item_name       TEXT    NOT NULL,
            unit            TEXT    NOT NULL DEFAULT 'pcs',
            system_qty      REAL    NOT NULL DEFAULT 0,
            counted_qty     REAL    NOT NULL DEFAULT 0,
            FOREIGN KEY (verification_id) REFERENCES store_stock_verifications(id) ON DELETE CASCADE
        )
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
        CREATE TABLE IF NOT EXISTS store_products (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            category_id   INTEGER NOT NULL,
            name          TEXT    NOT NULL,
            default_unit  TEXT    NOT NULL DEFAULT 'kg',
            is_active     INTEGER NOT NULL DEFAULT 1,
            sort_order    INTEGER NOT NULL DEFAULT 0,
            created_at    TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at    TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            UNIQUE(category_id, name),
            FOREIGN KEY (category_id) REFERENCES store_product_categories(id)
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_store_products_category
        ON store_products(category_id, is_active, sort_order, name)
    """)
    _seed_store_product_master(cursor)
    cursor.execute(
        "UPDATE store_products SET default_unit = 'liter' WHERE lower(default_unit) = 'ltr'"
    )
    conn.commit()


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
                    (category_id, name, default_unit, is_active, sort_order)
                VALUES (?, ?, ?, 1, ?)
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
            created_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE CASCADE
        )
    """)
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
