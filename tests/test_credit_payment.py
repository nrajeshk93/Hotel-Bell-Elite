"""Tests for credit payment settlement helpers and validation."""

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
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
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
        CREATE TABLE purchase_verifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company TEXT NOT NULL,
            supplier_id INTEGER NOT NULL,
            verification_date TEXT NOT NULL,
            verification_method TEXT NOT NULL DEFAULT 'cash',
            verification_account TEXT NOT NULL DEFAULT '',
            transaction_id TEXT NOT NULL DEFAULT '',
            total_amount REAL NOT NULL DEFAULT 0,
            notes TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE purchase_verification_allocations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            purchase_verification_id INTEGER NOT NULL,
            expense_id INTEGER NOT NULL,
            amount REAL NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );
        """
    )
    return conn


def _seed_supplier(conn, name="Acme Foods", gst="29AAAAA0000A1Z5"):
    cur = conn.execute(
        "INSERT INTO suppliers (name, gst) VALUES (?, ?)",
        (name, gst),
    )
    return cur.lastrowid


def _seed_expense(conn, supplier_id, amount, payment_type="credit", code="HBE-EX-1", sales_date="2026-07-01"):
    cur = conn.execute(
        """INSERT INTO sales_update_expenses
           (company, location, sales_date, description, amount, payment_type, supplier_id, category, expense_code)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("HBE", "Hotel", sales_date, "Test expense", amount, payment_type, supplier_id, "grocery", code),
    )
    return cur.lastrowid


class CreditPaymentBalanceTests(unittest.TestCase):
    def test_balance_none_partial_full(self):
        self.assertEqual(app_module._credit_expense_balance(10000, 0), 10000)
        self.assertEqual(app_module._credit_expense_balance(10000, 2500), 7500)
        self.assertEqual(app_module._credit_expense_balance(10000, 10000), 0)
        self.assertEqual(app_module._credit_expense_balance(10000, 12000), 0)

    def test_settlement_status_labels(self):
        self.assertEqual(app_module._credit_settlement_status("credit", 100, 0), "outstanding")
        self.assertEqual(app_module._credit_settlement_status("credit", 100, 40), "partial")
        self.assertEqual(app_module._credit_settlement_status("credit", 100, 100), "cleared")
        self.assertEqual(app_module._credit_settlement_status("cash", 100, 0), "cleared")
        self.assertEqual(app_module._credit_settlement_status("bank_transfer", 100, 0), "cleared")


class CreditPaymentValidationTests(unittest.TestCase):
    def setUp(self):
        self.conn = _memory_conn()
        self.supplier_a = _seed_supplier(self.conn, "Supplier A", "29AAAAA0000A1Z5")
        self.supplier_b = _seed_supplier(self.conn, "Supplier B", "29BBBBB0000B1Z5")
        self.expense_a1 = _seed_expense(self.conn, self.supplier_a, 10000, code="HBE-EX-1")
        self.expense_a2 = _seed_expense(self.conn, self.supplier_a, 5000, code="HBE-EX-2", sales_date="2026-07-02")
        self.expense_b1 = _seed_expense(self.conn, self.supplier_b, 3000, code="HBE-EX-3")
        self.expense_cash = _seed_expense(
            self.conn, self.supplier_a, 2000, payment_type="cash", code="HBE-EX-4"
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def _create_payment(self, allocations, **overrides):
        payload = {
            "supplier_id": self.supplier_a,
            "payment_date": "2026-07-13",
            "payment_method": "cash",
            "transaction_id": "",
            "notes": "",
            "allocations": allocations,
        }
        payload.update(overrides)
        return app_module._validate_credit_payment_payload(self.conn, payload)

    def test_valid_multi_expense_same_supplier(self):
        payload, errors = self._create_payment([
            {"expense_id": self.expense_a1, "amount": 6000},
            {"expense_id": self.expense_a2, "amount": 3000},
        ])
        self.assertEqual(errors, [])
        self.assertEqual(payload["total_amount"], 9000)
        self.assertEqual(len(payload["allocations"]), 2)

    def test_reject_mixed_suppliers(self):
        payload, errors = self._create_payment([
            {"expense_id": self.expense_a1, "amount": 1000},
            {"expense_id": self.expense_b1, "amount": 1000},
        ])
        self.assertIsNone(payload)
        self.assertTrue(any("same supplier" in err.lower() for err in errors))

    def test_reject_over_allocation(self):
        payload, errors = self._create_payment([
            {"expense_id": self.expense_a1, "amount": 15000},
        ])
        self.assertIsNone(payload)
        self.assertTrue(any("exceeds outstanding" in err.lower() for err in errors))

    def test_reject_non_credit_expense(self):
        payload, errors = self._create_payment([
            {"expense_id": self.expense_cash, "amount": 500},
        ])
        self.assertIsNone(payload)
        self.assertTrue(any("credit" in err.lower() for err in errors))

    def test_reject_card_without_transaction_id(self):
        payload, errors = self._create_payment(
            [{"expense_id": self.expense_a1, "amount": 1000}],
            payment_method="card",
            transaction_id="",
        )
        self.assertIsNone(payload)
        self.assertTrue(any("transaction id" in err.lower() for err in errors))

    def test_partial_then_remaining_balance(self):
        payload, errors = self._create_payment([
            {"expense_id": self.expense_a1, "amount": 4000},
        ])
        self.assertEqual(errors, [])
        cur = self.conn.execute(
            """INSERT INTO credit_payments
               (company, supplier_id, payment_date, payment_method, transaction_id, total_amount, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                payload["company"],
                payload["supplier_id"],
                payload["payment_date"],
                payload["payment_method"],
                payload["transaction_id"],
                payload["total_amount"],
                payload["notes"],
            ),
        )
        payment_id = cur.lastrowid
        for allocation in payload["allocations"]:
            self.conn.execute(
                """INSERT INTO credit_payment_allocations (credit_payment_id, expense_id, amount)
                   VALUES (?, ?, ?)""",
                (payment_id, allocation["expense_id"], allocation["amount"]),
            )
        self.conn.commit()

        paid = app_module._credit_expense_paid_total(self.conn, self.expense_a1)
        self.assertEqual(paid, 4000)
        balance = app_module._credit_expense_balance(10000, paid)
        self.assertEqual(balance, 6000)

        payload2, errors2 = self._create_payment([
            {"expense_id": self.expense_a1, "amount": 6000},
        ])
        self.assertEqual(errors2, [])
        self.assertEqual(payload2["total_amount"], 6000)

        payload3, errors3 = self._create_payment([
            {"expense_id": self.expense_a1, "amount": 6000.01},
        ])
        self.assertIsNone(payload3)
        self.assertTrue(errors3)

    def test_outstanding_filters_cleared_expenses(self):
        cur = self.conn.execute(
            """INSERT INTO credit_payments
               (company, supplier_id, payment_date, payment_method, total_amount)
               VALUES ('HBE', ?, '2026-07-13', 'cash', 10000)""",
            (self.supplier_a,),
        )
        payment_id = cur.lastrowid
        self.conn.execute(
            """INSERT INTO credit_payment_allocations (credit_payment_id, expense_id, amount)
               VALUES (?, ?, 10000)""",
            (payment_id, self.expense_a1),
        )
        self.conn.commit()

        entries = app_module._outstanding_credit_expenses(
            self.conn, date(2026, 7, 1), date(2026, 7, 31), supplier_id=self.supplier_a
        )
        ids = {entry["id"] for entry in entries}
        self.assertNotIn(self.expense_a1, ids)
        self.assertIn(self.expense_a2, ids)

    def test_delete_restores_balance(self):
        cur = self.conn.execute(
            """INSERT INTO credit_payments
               (company, supplier_id, payment_date, payment_method, total_amount)
               VALUES ('HBE', ?, '2026-07-13', 'cash', 4000)""",
            (self.supplier_a,),
        )
        payment_id = cur.lastrowid
        self.conn.execute(
            """INSERT INTO credit_payment_allocations (credit_payment_id, expense_id, amount)
               VALUES (?, ?, 4000)""",
            (payment_id, self.expense_a1),
        )
        self.conn.commit()
        self.assertEqual(app_module._credit_expense_paid_total(self.conn, self.expense_a1), 4000)

        self.conn.execute(
            "DELETE FROM credit_payment_allocations WHERE credit_payment_id = ?",
            (payment_id,),
        )
        self.conn.execute("DELETE FROM credit_payments WHERE id = ?", (payment_id,))
        self.conn.commit()
        self.assertEqual(app_module._credit_expense_paid_total(self.conn, self.expense_a1), 0)

    def test_purchase_ledger_reflects_cleared_credit_payment_mode(self):
        cur = self.conn.execute(
            """INSERT INTO credit_payments
               (company, supplier_id, payment_date, payment_method, total_amount)
               VALUES ('HBE', ?, '2026-07-13', 'cash', 10000)""",
            (self.supplier_a,),
        )
        payment_id = cur.lastrowid
        self.conn.execute(
            """INSERT INTO credit_payment_allocations (credit_payment_id, expense_id, amount)
               VALUES (?, ?, 10000)""",
            (payment_id, self.expense_a1),
        )
        self.conn.commit()
        app_module._sync_expense_payment_after_clearance(self.conn, self.expense_a1)
        self.conn.commit()

        entries = app_module._purchase_ledger_entries(
            self.conn, date(2026, 7, 1), date(2026, 7, 31)
        )
        cleared = next(entry for entry in entries if entry["id"] == self.expense_a1)
        self.assertEqual(cleared["display_payment_type"], "cash")
        self.assertEqual(cleared["settlement_status"], "cleared")

        cash_entry = next(entry for entry in entries if entry["id"] == self.expense_cash)
        self.assertEqual(cash_entry["display_payment_type"], "cash")
        self.assertEqual(cash_entry["settlement_status"], "cleared")

    def test_update_outstanding_purchase_from_ledger(self):
        result, error = app_module._update_purchase_ledger_expense(
            self.conn,
            {"is_admin": True},
            {
                "expense_id": self.expense_a1,
                "date": "2026-07-14",
                "description": "Updated credit purchase",
                "amount": 12000,
                "payment_type": "credit",
                "category": "grocery",
                "supplier_id": self.supplier_a,
                "invoice_number": "INV-EDIT-1",
            },
        )
        self.assertIsNone(error)
        self.assertEqual(result["expense_id"], self.expense_a1)
        self.assertEqual(result["sales_date"], "2026-07-14")
        row = self.conn.execute(
            "SELECT description, amount, sales_date, invoice_number FROM sales_update_expenses WHERE id = ?",
            (self.expense_a1,),
        ).fetchone()
        self.assertEqual(row["description"], "Updated credit purchase")
        self.assertEqual(float(row["amount"]), 12000.0)
        self.assertEqual(row["sales_date"], "2026-07-14")
        self.assertEqual(row["invoice_number"], "INV-EDIT-1")

    def test_reject_edit_for_cleared_purchase(self):
        result, error = app_module._update_purchase_ledger_expense(
            self.conn,
            {"is_admin": True},
            {
                "expense_id": self.expense_cash,
                "date": "2026-07-01",
                "description": "Should fail",
                "amount": 50,
                "payment_type": "cash",
                "category": "grocery",
                "supplier_id": self.supplier_a,
            },
        )
        self.assertIsNone(result)
        self.assertIn("outstanding", (error or "").lower())

    def test_reject_duplicate_supplier_invoice(self):
        self.conn.execute(
            "UPDATE sales_update_expenses SET invoice_number = ? WHERE id = ?",
            ("INV-1001", self.expense_a1),
        )
        self.conn.commit()

        result, error = app_module._create_sales_expense(
            self.conn,
            {"is_admin": True},
            {
                "company": "HBE",
                "location": "Hotel",
                "date": "2026-07-13",
                "description": "Duplicate invoice",
                "amount": 500,
                "payment_type": "cash",
                "category": "grocery",
                "supplier_id": self.supplier_a,
                "invoice_number": "inv-1001",
            },
        )
        self.assertIsNone(result)
        self.assertIn("already exists", error.lower())

        result2, error2 = app_module._create_sales_expense(
            self.conn,
            {"is_admin": True},
            {
                "company": "HBE",
                "location": "Hotel",
                "date": "2026-07-13",
                "description": "Unique invoice",
                "amount": 500,
                "payment_type": "cash",
                "category": "grocery",
                "supplier_id": self.supplier_a,
                "invoice_number": "INV-2002",
            },
        )
        self.assertIsNotNone(result2)
        self.assertIsNone(error2)


class PurchaseVerificationIsolationTests(unittest.TestCase):
    def setUp(self):
        self.conn = _memory_conn()
        self.user = {"username": "administrator", "full_name": "Administrator"}
        self.supplier_a = _seed_supplier(self.conn, "ABC Supplies", "29ABCDE1234F1Z5")
        self.expense_credit = _seed_expense(self.conn, self.supplier_a, 100, code="HBE-EX-1")
        self.expense_cash = _seed_expense(
            self.conn, self.supplier_a, 50, payment_type="cash", code="HBE-EX-2"
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def _record_credit_payment(self, expense_id, amount):
        cur = self.conn.execute(
            """INSERT INTO credit_payments
               (company, supplier_id, payment_date, payment_method, total_amount)
               VALUES ('HBE', ?, '2026-07-13', 'card', 100)""",
            (self.supplier_a,),
        )
        payment_id = cur.lastrowid
        self.conn.execute(
            """INSERT INTO credit_payment_allocations (credit_payment_id, expense_id, amount)
               VALUES (?, ?, ?)""",
            (payment_id, expense_id, amount),
        )
        self.conn.commit()
        return payment_id

    def test_credit_payment_does_not_appear_in_verification_history(self):
        self._record_credit_payment(self.expense_credit, 100)

        history = app_module._purchase_verification_entries(
            self.conn, verification_date_from=date(2026, 7, 1), verification_date_to=date(2026, 7, 31)
        )
        self.assertEqual(history, [])

    def test_credit_payment_does_not_clear_pending_verification(self):
        self._record_credit_payment(self.expense_credit, 100)

        pending = app_module._pending_purchase_verifications(
            self.conn, date(2026, 7, 1), date(2026, 7, 31), supplier_id=self.supplier_a
        )
        ids = {entry["id"] for entry in pending}
        self.assertIn(self.expense_credit, ids)
        self.assertIn(self.expense_cash, ids)

    def test_verification_accepts_any_hotel_purchase_type(self):
        payload, errors = app_module._validate_purchase_verification_payload(
            self.conn,
            {
                "supplier_id": self.supplier_a,
                "payment_date": "2026-07-13",
                "payment_method": "cash",
                "allocations": [
                    {"expense_id": self.expense_credit, "amount": 100},
                    {"expense_id": self.expense_cash, "amount": 50},
                ],
            },
            user=self.user,
        )
        self.assertEqual(errors, [])
        self.assertEqual(payload["total_amount"], 150)
        self.assertEqual(payload["verification_account"], "administrator")

    def test_verification_requires_logged_in_user(self):
        payload, errors = app_module._validate_purchase_verification_payload(
            self.conn,
            {
                "supplier_id": self.supplier_a,
                "payment_date": "2026-07-13",
                "allocations": [{"expense_id": self.expense_credit, "amount": 100}],
            },
        )
        self.assertIsNone(payload)
        self.assertTrue(any("logged in" in err.lower() for err in errors))

    def test_verification_removes_expense_from_pending_list(self):
        payload, errors = app_module._validate_purchase_verification_payload(
            self.conn,
            {
                "supplier_id": self.supplier_a,
                "payment_date": "2026-07-13",
                "payment_method": "cash",
                "allocations": [{"expense_id": self.expense_credit, "amount": 100}],
            },
            user=self.user,
        )
        self.assertEqual(errors, [])
        cur = self.conn.execute(
            """INSERT INTO purchase_verifications
               (company, supplier_id, verification_date, verification_method, verification_account, total_amount)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                payload["company"],
                payload["supplier_id"],
                payload["verification_date"],
                payload["verification_method"],
                payload["verification_account"],
                payload["total_amount"],
            ),
        )
        verification_id = cur.lastrowid
        self.conn.execute(
            """INSERT INTO purchase_verification_allocations
               (purchase_verification_id, expense_id, amount)
               VALUES (?, ?, ?)""",
            (verification_id, self.expense_credit, 100),
        )
        self.conn.commit()

        pending = app_module._pending_purchase_verifications(
            self.conn, date(2026, 7, 1), date(2026, 7, 31), supplier_id=self.supplier_a
        )
        ids = {entry["id"] for entry in pending}
        self.assertNotIn(self.expense_credit, ids)
        self.assertIn(self.expense_cash, ids)

        history = app_module._purchase_verification_entries(
            self.conn, verification_date_from=date(2026, 7, 1), verification_date_to=date(2026, 7, 31)
        )
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["total_amount"], 100)
        self.assertEqual(history[0]["verification_account"], "administrator")
        self.assertEqual(history[0]["expense_codes"], "HBE-EX-1")


class CreditPaymentAccessTests(unittest.TestCase):
    def test_endpoints_map_to_accounts(self):
        from workspace_access import get_endpoint_dashboard_module

        for endpoint in (
            "credit_payment",
            "purchase_verification",
            "create_credit_payment",
            "delete_credit_payment",
            "credit_payment_detail",
            "create_purchase_verification",
            "delete_purchase_verification",
            "purchase_verification_detail",
        ):
            self.assertEqual(get_endpoint_dashboard_module(endpoint), "accounts")


if __name__ == "__main__":
    unittest.main()
