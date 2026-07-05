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
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            company     TEXT    NOT NULL,
            location    TEXT    NOT NULL,
            sales_date  TEXT    NOT NULL,
            description TEXT    NOT NULL DEFAULT '',
            amount      REAL    NOT NULL DEFAULT 0,
            created_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        )
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
        CREATE TABLE IF NOT EXISTS hotel_sales_ledger_entries (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            company         TEXT    NOT NULL,
            location        TEXT    NOT NULL,
            sales_date      TEXT    NOT NULL,
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
