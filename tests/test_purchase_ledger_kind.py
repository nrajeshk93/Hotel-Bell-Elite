"""Purchase vs expense entry_kind on Purchases & Expenses ledger."""

import sqlite3
import unittest
from datetime import date

import app as app_module


def _memory_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(
        """
        CREATE TABLE suppliers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            gst TEXT NOT NULL DEFAULT '',
            address TEXT NOT NULL DEFAULT '',
            phone TEXT NOT NULL DEFAULT '',
            bank_name TEXT NOT NULL DEFAULT '',
            bank_account_number TEXT NOT NULL DEFAULT '',
            ifsc_code TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE sales_update_expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company TEXT NOT NULL,
            location TEXT NOT NULL,
            sales_date TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            amount REAL NOT NULL DEFAULT 0,
            payment_type TEXT NOT NULL DEFAULT 'cash',
            transaction_id TEXT NOT NULL DEFAULT '',
            invoice_number TEXT NOT NULL DEFAULT '',
            expense_code TEXT NOT NULL DEFAULT '',
            supplier_id INTEGER,
            category TEXT NOT NULL DEFAULT '',
            entry_kind TEXT NOT NULL DEFAULT 'expense',
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            cancelled_at TEXT,
            cancelled_by INTEGER
        );
        CREATE TABLE credit_payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company TEXT NOT NULL,
            supplier_id INTEGER NOT NULL,
            payment_date TEXT NOT NULL,
            payment_method TEXT NOT NULL DEFAULT 'cash',
            transaction_id TEXT NOT NULL DEFAULT '',
            total_amount REAL NOT NULL DEFAULT 0,
            notes TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE credit_payment_allocations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            credit_payment_id INTEGER NOT NULL,
            expense_id INTEGER NOT NULL,
            amount REAL NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );
        """
    )
    return conn


def _seed_supplier(conn, name="Acme Foods", gst="29AAAAA0000A1Z5"):
    cur = conn.execute("INSERT INTO suppliers (name, gst) VALUES (?, ?)", (name, gst))
    return cur.lastrowid


def _seed_entry(conn, supplier_id, *, amount, entry_kind, code, payment_type="credit"):
    cur = conn.execute(
        """INSERT INTO sales_update_expenses
           (company, location, sales_date, description, amount, payment_type,
            supplier_id, category, expense_code, entry_kind)
           VALUES ('HBE', 'Hotel', '2026-07-01', ?, ?, ?, ?, 'grocery', ?, ?)""",
        (f"{entry_kind} item", amount, payment_type, supplier_id, code, entry_kind),
    )
    return cur.lastrowid


class LedgerEntryKindHelperTests(unittest.TestCase):
    def test_normalize_defaults_blank_to_expense(self):
        self.assertEqual(app_module._normalize_ledger_entry_kind(""), "expense")
        self.assertEqual(app_module._normalize_ledger_entry_kind(None), "expense")
        self.assertEqual(app_module._normalize_ledger_entry_kind("PURCHASE"), "purchase")

    def test_parse_kind_filter(self):
        selected, kind = app_module._parse_purchase_ledger_kind("purchase")
        self.assertEqual(selected, "purchase")
        self.assertEqual(kind, "purchase")
        selected, kind = app_module._parse_purchase_ledger_kind("all")
        self.assertEqual(selected, "all")
        self.assertIsNone(kind)
        selected, kind = app_module._parse_purchase_ledger_kind("nope")
        self.assertEqual(selected, "all")
        self.assertIsNone(kind)

    def test_next_code_uses_kind_token(self):
        conn = _memory_conn()
        supplier = _seed_supplier(conn)
        _seed_entry(conn, supplier, amount=10, entry_kind="purchase", code="HBE-PU-1")
        _seed_entry(conn, supplier, amount=10, entry_kind="expense", code="HBE-EX-3")
        conn.commit()
        self.assertEqual(app_module._next_expense_code(conn, "HBE", "purchase"), "HBE-PU-2")
        self.assertEqual(app_module._next_expense_code(conn, "HBE", "expense"), "HBE-EX-4")
        conn.close()


class PurchaseLedgerKindFilterTests(unittest.TestCase):
    def setUp(self):
        self.conn = _memory_conn()
        self.supplier = _seed_supplier(self.conn)
        self.purchase_id = _seed_entry(
            self.conn, self.supplier, amount=100, entry_kind="purchase", code="HBE-PU-1"
        )
        self.expense_id = _seed_entry(
            self.conn, self.supplier, amount=40, entry_kind="expense", code="HBE-EX-1"
        )
        # Legacy blank kind should behave as expense
        self.legacy_id = self.conn.execute(
            """INSERT INTO sales_update_expenses
               (company, location, sales_date, description, amount, payment_type,
                supplier_id, category, expense_code, entry_kind)
               VALUES ('HBE', 'Hotel', '2026-07-01', 'Legacy', 25, 'credit', ?, 'grocery', 'HBE-EX-2', '')""",
            (self.supplier,),
        ).lastrowid
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_list_all_includes_purchase_and_expense(self):
        entries = app_module._purchase_ledger_entries(
            self.conn, date(2026, 7, 1), date(2026, 7, 31)
        )
        kinds = {row["id"]: row["entry_kind"] for row in entries}
        self.assertEqual(kinds[self.purchase_id], "purchase")
        self.assertEqual(kinds[self.expense_id], "expense")
        self.assertEqual(kinds[self.legacy_id], "expense")

    def test_filter_purchase_only(self):
        entries = app_module._purchase_ledger_entries(
            self.conn,
            date(2026, 7, 1),
            date(2026, 7, 31),
            entry_kind="purchase",
        )
        self.assertEqual([row["id"] for row in entries], [self.purchase_id])

    def test_filter_expense_includes_blank_legacy(self):
        entries = app_module._purchase_ledger_entries(
            self.conn,
            date(2026, 7, 1),
            date(2026, 7, 31),
            entry_kind="expense",
        )
        ids = {row["id"] for row in entries}
        self.assertEqual(ids, {self.expense_id, self.legacy_id})

    def test_sales_entry_expense_helpers_exclude_purchases(self):
        total = app_module._sales_expense_total(
            self.conn, "HBE", "Hotel", "2026-07-01"
        )
        entries = app_module._sales_expense_entries(
            self.conn, "HBE", "Hotel", "2026-07-01"
        )
        ids = {row["id"] for row in entries}
        self.assertEqual(total, 65.0)
        self.assertEqual(ids, {self.expense_id, self.legacy_id})
        self.assertNotIn(self.purchase_id, ids)


class CreateSalesExpenseKindTests(unittest.TestCase):
    def setUp(self):
        self.conn = _memory_conn()
        self.supplier = _seed_supplier(self.conn)
        self.user = {"is_admin": True, "username": "admin"}
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def _payload(self, **overrides):
        data = {
            "company": "HBE",
            "location": "Hotel",
            "date": "2026-07-10",
            "description": "Kitchen stock",
            "amount": 250,
            "payment_type": "credit",
            "category": "grocery",
            "supplier_id": self.supplier,
            "invoice_number": "INV-KIND-1",
        }
        data.update(overrides)
        return data

    def test_create_defaults_to_expense(self):
        result, error = app_module._create_sales_expense(
            self.conn, self.user, self._payload(), skip_cash_check=True
        )
        self.assertIsNone(error)
        self.assertEqual(result["entry_kind"], "expense")
        self.assertTrue(result["expense_code"].startswith("HBE-EX-"))

    def test_create_purchase_kind(self):
        result, error = app_module._create_sales_expense(
            self.conn,
            self.user,
            self._payload(entry_kind="purchase", invoice_number="INV-KIND-2"),
            skip_cash_check=True,
        )
        self.assertIsNone(error)
        self.assertEqual(result["entry_kind"], "purchase")
        self.assertTrue(result["expense_code"].startswith("HBE-PU-"))
        row = self.conn.execute(
            "SELECT entry_kind, expense_code FROM sales_update_expenses WHERE id = ?",
            (result["expense_id"],),
        ).fetchone()
        self.assertEqual(row["entry_kind"], "purchase")
        self.assertTrue(row["expense_code"].startswith("HBE-PU-"))


class PurchaseLedgerFilterSupplierTests(unittest.TestCase):
    def setUp(self):
        self.conn = _memory_conn()
        self.with_grocery = _seed_supplier(self.conn, name="Grocery Co", gst="29AAAAA0000A1Z1")
        self.with_alcohol = _seed_supplier(self.conn, name="Alcohol Co", gst="29AAAAA0000A1Z2")
        self.unused = _seed_supplier(self.conn, name="A.B.ELECTRONICS", gst="29AAAAA0000A1Z3")
        _seed_entry(
            self.conn,
            self.with_grocery,
            amount=100,
            entry_kind="purchase",
            code="HBE-PU-1",
        )
        self.conn.execute(
            """UPDATE sales_update_expenses SET category = 'grocery' WHERE expense_code = 'HBE-PU-1'"""
        )
        self.conn.execute(
            """INSERT INTO sales_update_expenses
               (company, location, sales_date, description, amount, payment_type,
                supplier_id, category, expense_code, entry_kind)
               VALUES ('HBE', 'Hotel', '2026-07-01', 'Bar stock', 50, 'cash', ?, 'liquor', 'HBE-EX-9', 'expense')""",
            (self.with_alcohol,),
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_filter_suppliers_excludes_unused_master_rows(self):
        names = {
            s["name"]
            for s in app_module._purchase_ledger_filter_suppliers(
                self.conn, date(2026, 4, 1), date(2027, 3, 31)
            )
        }
        self.assertIn("Grocery Co", names)
        self.assertIn("Alcohol Co", names)
        self.assertNotIn("A.B.ELECTRONICS", names)

    def test_filter_suppliers_respects_category(self):
        names = {
            s["name"]
            for s in app_module._purchase_ledger_filter_suppliers(
                self.conn,
                date(2026, 4, 1),
                date(2027, 3, 31),
                category="liquor",
            )
        }
        self.assertEqual(names, {"Alcohol Co"})

    def test_filter_categories_excludes_unused_master_keys(self):
        keys = {
            key
            for key, _label in app_module._purchase_ledger_filter_categories(
                self.conn, date(2026, 4, 1), date(2027, 3, 31)
            )
        }
        self.assertIn("grocery", keys)
        self.assertIn("liquor", keys)
        self.assertNotIn("alcopop", keys)

    def test_filter_categories_respects_supplier(self):
        keys = {
            key
            for key, _label in app_module._purchase_ledger_filter_categories(
                self.conn,
                date(2026, 4, 1),
                date(2027, 3, 31),
                supplier_id=self.with_alcohol,
            )
        }
        self.assertEqual(keys, {"liquor"})


if __name__ == "__main__":
    unittest.main()
