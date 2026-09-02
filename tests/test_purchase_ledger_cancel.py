"""Purchase Ledger cancel (soft status) and monotonic expense codes."""

import sqlite3
import unittest
from datetime import date, datetime, timedelta
from unittest.mock import patch

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
        CREATE UNIQUE INDEX idx_sales_update_expenses_code
            ON sales_update_expenses(expense_code) WHERE expense_code != '';
        CREATE TABLE sales_update_expense_code_seq (
            company TEXT NOT NULL,
            kind TEXT NOT NULL,
            last_num INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (company, kind)
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
        CREATE TABLE purchase_verification_allocations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            purchase_verification_id INTEGER NOT NULL,
            expense_id INTEGER NOT NULL,
            amount REAL NOT NULL DEFAULT 0
        );
        """
    )
    return conn


def _seed_supplier(conn, name="Acme Foods", gst="29AAAAA0000A1Z5"):
    cur = conn.execute("INSERT INTO suppliers (name, gst) VALUES (?, ?)", (name, gst))
    return cur.lastrowid


def _seed_entry(
    conn,
    supplier_id,
    *,
    amount=100,
    entry_kind="purchase",
    code="HBE-PU-1",
    payment_type="cash",
    invoice_number="INV-1",
    sales_date=None,
    created_at=None,
):
    sales_date = sales_date or date.today().isoformat()
    created_at = created_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur = conn.execute(
        """INSERT INTO sales_update_expenses
           (company, location, sales_date, description, amount, payment_type,
            supplier_id, category, expense_code, entry_kind, invoice_number, created_at)
           VALUES ('HBE', 'Hotel', ?, 'Stock', ?, ?, ?, 'grocery', ?, ?, ?, ?)""",
        (
            sales_date,
            amount,
            payment_type,
            supplier_id,
            code,
            entry_kind,
            invoice_number,
            created_at,
        ),
    )
    return cur.lastrowid


class PurchaseLedgerCancelTests(unittest.TestCase):
    def setUp(self):
        self.conn = _memory_conn()
        self.supplier = _seed_supplier(self.conn)
        self.super_admin = {"id": 1, "username": "admin", "is_admin": True}
        self.staff = {"id": 2, "username": "clerk", "is_admin": False}
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_cash_create_status_cleared(self):
        result, error = app_module._create_sales_expense(
            self.conn,
            self.super_admin,
            {
                "company": "HBE",
                "location": "Hotel",
                "date": date.today().isoformat(),
                "description": "Rice",
                "amount": 80,
                "payment_type": "cash",
                "category": "grocery",
                "supplier_id": self.supplier,
                "invoice_number": "INV-CASH-1",
                "entry_kind": "purchase",
            },
            skip_cash_check=True,
        )
        self.assertIsNone(error)
        row = self.conn.execute(
            "SELECT payment_type, cancelled_at FROM sales_update_expenses WHERE id = ?",
            (result["expense_id"],),
        ).fetchone()
        self.assertEqual(row["payment_type"], "cash")
        self.assertFalse(row["cancelled_at"])
        self.assertEqual(
            app_module._credit_settlement_status(row["payment_type"], 80, 0), "cleared"
        )

    def test_bank_create_status_cleared(self):
        result, error = app_module._create_sales_expense(
            self.conn,
            self.super_admin,
            {
                "company": "HBE",
                "location": "Hotel",
                "date": date.today().isoformat(),
                "description": "Oil",
                "amount": 40,
                "payment_type": "bank",
                "transaction_id": "TXN-1",
                "category": "grocery",
                "supplier_id": self.supplier,
                "invoice_number": "INV-BANK-1",
                "entry_kind": "expense",
            },
            skip_cash_check=True,
        )
        self.assertIsNone(error)
        self.assertEqual(
            app_module._credit_settlement_status("bank", 40, 0), "cleared"
        )

    def test_any_user_edits_cleared_inside_4h(self):
        expense_id = _seed_entry(
            self.conn, self.supplier, payment_type="cash", code="HBE-PU-1"
        )
        self.conn.commit()
        result, error = app_module._update_purchase_ledger_expense(
            self.conn,
            self.staff,
            {
                "id": expense_id,
                "date": date.today().isoformat(),
                "description": "Updated rice",
                "amount": 120,
                "payment_type": "cash",
                "category": "grocery",
                "supplier_id": self.supplier,
                "invoice_number": "INV-1",
                "entry_kind": "purchase",
            },
        )
        self.assertIsNone(error)
        self.assertEqual(result["expense_id"], expense_id)
        row = self.conn.execute(
            "SELECT description, amount FROM sales_update_expenses WHERE id = ?",
            (expense_id,),
        ).fetchone()
        self.assertEqual(row["description"], "Updated rice")
        self.assertEqual(row["amount"], 120)

    def test_cannot_edit_after_windows(self):
        old = (datetime.now() - timedelta(hours=5)).strftime("%Y-%m-%d %H:%M:%S")
        expense_id = _seed_entry(
            self.conn, self.supplier, payment_type="cash", code="HBE-PU-2",
            created_at=old, sales_date=(date.today() - timedelta(days=40)).isoformat(),
        )
        self.conn.commit()
        result, error = app_module._update_purchase_ledger_expense(
            self.conn,
            self.super_admin,
            {
                "id": expense_id,
                "date": date.today().isoformat(),
                "description": "Too late",
                "amount": 120,
                "payment_type": "cash",
                "category": "grocery",
                "supplier_id": self.supplier,
                "invoice_number": "INV-1",
                "entry_kind": "purchase",
            },
        )
        self.assertIsNone(result)
        self.assertEqual(error, app_module.PURCHASE_LEDGER_EDIT_WINDOW_MESSAGE)

    def test_non_admin_cannot_cancel(self):
        expense_id = _seed_entry(self.conn, self.supplier, code="HBE-PU-3")
        self.conn.commit()
        result, error = app_module._delete_purchase_ledger_expense(
            self.conn, self.staff, {"id": expense_id}
        )
        self.assertIsNone(result)
        self.assertEqual(error, app_module.PURCHASE_LEDGER_CANCEL_FORBIDDEN_MESSAGE)
        row = self.conn.execute(
            "SELECT cancelled_at FROM sales_update_expenses WHERE id = ?",
            (expense_id,),
        ).fetchone()
        self.assertIsNone(row["cancelled_at"])

    def test_non_admin_cancel_api_403(self):
        expense_id = _seed_entry(self.conn, self.supplier, code="HBE-PU-4")
        self.conn.commit()
        with app_module.app.test_request_context(
            "/accounts/purchase-ledger/delete",
            method="POST",
            json={"expense_id": expense_id},
        ):
            with patch.object(app_module, "get_current_user", return_value=self.staff):
                with patch.object(app_module, "get_db", return_value=self.conn):
                    resp = app_module.purchase_ledger_delete()
        if isinstance(resp, tuple):
            body, status = resp[0], resp[1]
        else:
            body, status = resp, resp.status_code
        data = body.get_json()
        self.assertEqual(status, 403)
        self.assertFalse(data["ok"])
        self.assertEqual(data["error"], app_module.PURCHASE_LEDGER_CANCEL_FORBIDDEN_MESSAGE)

    def test_super_admin_cancel_keeps_row_and_code(self):
        expense_id = _seed_entry(
            self.conn, self.supplier, code="HBE-PU-10", entry_kind="purchase"
        )
        self.conn.execute(
            """INSERT INTO sales_update_expense_code_seq (company, kind, last_num)
               VALUES ('HBE', 'purchase', 10)"""
        )
        self.conn.execute(
            "INSERT INTO credit_payment_allocations (credit_payment_id, expense_id, amount) VALUES (1, ?, 10)",
            (expense_id,),
        )
        self.conn.execute(
            "INSERT INTO purchase_verification_allocations (purchase_verification_id, expense_id, amount) VALUES (1, ?, 10)",
            (expense_id,),
        )
        self.conn.commit()
        with patch(
            "stores.reverse_stock_for_deleted_purchase_expense", return_value=None
        ) as reverse:
            result, error = app_module._delete_purchase_ledger_expense(
                self.conn, self.super_admin, {"id": expense_id}
            )
        self.assertIsNone(error)
        reverse.assert_called_once()
        row = self.conn.execute(
            """SELECT expense_code, cancelled_at, cancelled_by
               FROM sales_update_expenses WHERE id = ?""",
            (expense_id,),
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["expense_code"], "HBE-PU-10")
        self.assertTrue(row["cancelled_at"])
        self.assertEqual(row["cancelled_by"], 1)
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) AS n FROM credit_payment_allocations WHERE expense_id = ?",
                (expense_id,),
            ).fetchone()["n"],
            0,
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) AS n FROM purchase_verification_allocations WHERE expense_id = ?",
                (expense_id,),
            ).fetchone()["n"],
            0,
        )
        nxt = app_module._next_expense_code(self.conn, "HBE", "purchase")
        self.assertEqual(nxt, "HBE-PU-11")

    def test_super_admin_cannot_cancel_after_windows(self):
        old = (datetime.now() - timedelta(hours=5)).strftime("%Y-%m-%d %H:%M:%S")
        expense_id = _seed_entry(
            self.conn, self.supplier, code="HBE-PU-12", created_at=old,
            sales_date=(date.today() - timedelta(days=40)).isoformat(),
        )
        self.conn.commit()
        result, error = app_module._delete_purchase_ledger_expense(
            self.conn, self.super_admin, {"id": expense_id}
        )
        self.assertIsNone(result)
        self.assertEqual(error, app_module.PURCHASE_LEDGER_EDIT_WINDOW_MESSAGE)

    def test_already_cancelled_errors(self):
        expense_id = _seed_entry(self.conn, self.supplier, code="HBE-PU-13")
        self.conn.execute(
            "UPDATE sales_update_expenses SET cancelled_at = datetime('now','localtime') WHERE id = ?",
            (expense_id,),
        )
        self.conn.commit()
        result, error = app_module._delete_purchase_ledger_expense(
            self.conn, self.super_admin, {"id": expense_id}
        )
        self.assertIsNone(result)
        self.assertEqual(error, app_module.PURCHASE_LEDGER_ALREADY_CANCELLED_MESSAGE)
        result, error = app_module._update_purchase_ledger_expense(
            self.conn,
            self.super_admin,
            {
                "id": expense_id,
                "date": date.today().isoformat(),
                "description": "Nope",
                "amount": 10,
                "payment_type": "cash",
                "category": "grocery",
                "supplier_id": self.supplier,
                "invoice_number": "INV-X",
                "entry_kind": "purchase",
            },
        )
        self.assertIsNone(result)
        self.assertEqual(error, app_module.PURCHASE_LEDGER_CANCELLED_EDIT_MESSAGE)

    def test_cancelled_in_list_excluded_from_cash_and_credit(self):
        live_id = _seed_entry(
            self.conn,
            self.supplier,
            code="HBE-PU-20",
            payment_type="cash",
            amount=50,
            invoice_number="INV-LIVE",
        )
        cancelled_id = _seed_entry(
            self.conn,
            self.supplier,
            code="HBE-PU-21",
            payment_type="cash",
            amount=75,
            invoice_number="INV-CAN",
        )
        credit_cancelled = _seed_entry(
            self.conn,
            self.supplier,
            code="HBE-PU-22",
            payment_type="credit",
            amount=90,
            invoice_number="INV-CC",
        )
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.conn.execute(
            "UPDATE sales_update_expenses SET cancelled_at = ? WHERE id IN (?, ?)",
            (now, cancelled_id, credit_cancelled),
        )
        self.conn.commit()
        today = date.today()
        entries = app_module._purchase_ledger_entries(self.conn, today, today)
        by_id = {row["id"]: row for row in entries}
        self.assertIn(cancelled_id, by_id)
        self.assertEqual(by_id[cancelled_id]["settlement_status"], "cancelled")
        self.assertEqual(by_id[live_id]["settlement_status"], "cleared")
        cash_rows = app_module._cash_ledger_expense_rows(
            self.conn, "HBE", today, today, location="Hotel"
        )
        cash_ids = {row["source_id"] for row in cash_rows}
        self.assertIn(live_id, cash_ids)
        self.assertNotIn(cancelled_id, cash_ids)
        outstanding = app_module._outstanding_credit_expenses(
            self.conn, today, today, company="HBE"
        )
        self.assertNotIn(credit_cancelled, {row["id"] for row in outstanding})
        dup = app_module._duplicate_expense_invoice(
            self.conn, self.supplier, "INV-CAN"
        )
        self.assertIsNone(dup)

    def test_seq_does_not_reuse_after_hard_delete(self):
        _seed_entry(self.conn, self.supplier, code="HBE-EX-3", entry_kind="expense")
        first = app_module._next_expense_code(self.conn, "HBE", "expense")
        self.assertEqual(first, "HBE-EX-4")
        self.conn.execute("DELETE FROM sales_update_expenses WHERE expense_code = 'HBE-EX-3'")
        second = app_module._next_expense_code(self.conn, "HBE", "expense")
        self.assertEqual(second, "HBE-EX-5")


if __name__ == "__main__":
    unittest.main()


class PurchaseLedgerFlaskClientTests(unittest.TestCase):
    """HTTP test_client checks for Purchases & Expenses cancel/edit window."""

    def setUp(self):
        import os
        import tempfile
        import db as db_mod

        self.db_mod = db_mod
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db_path = self.tmp.name
        self._orig_path = db_mod.DATABASE_PATH
        db_mod.DATABASE_PATH = self.db_path
        db_mod.init_db()

        self.app = app_module.app
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

        conn = db_mod.get_db()
        try:
            admin = conn.execute("SELECT id FROM users WHERE username = 'admin'").fetchone()
            self.admin_id = admin["id"] if admin else 1
            cur = conn.execute(
                """INSERT INTO suppliers
                   (name, gst, bank_account_number, ifsc_code)
                   VALUES (?, ?, ?, ?)""",
                ("Client Vendor", "29CCCCC0000C1Z5", "111122223333", "HDFC0009999"),
            )
            self.supplier_id = cur.lastrowid
            today = date.today().isoformat()
            conn.execute(
                """INSERT INTO cash_ledger_loads
                   (company, load_date, description, amount)
                   VALUES ('HBE', ?, 'seed cash', 100000)""",
                (today,),
            )
            conn.commit()
        finally:
            conn.close()

        self.admin_user = {
            "id": self.admin_id,
            "username": "admin",
            "full_name": "Administrator",
            "is_admin": True,
            "is_active": True,
            "dashboard_access": {"accounts", "approval"},
            "stores_access": set(),
        }
        self.staff_user = {
            "id": self.admin_id,
            "username": "clerk",
            "full_name": "Clerk",
            "is_admin": False,
            "is_active": True,
            "dashboard_access": {"accounts"},
            "stores_access": set(),
        }

    def tearDown(self):
        import os
        self.db_mod.DATABASE_PATH = self._orig_path
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def _payload(self, **overrides):
        data = {
            "company": "HBE",
            "location": "Hotel",
            "date": date.today().isoformat(),
            "description": "Client cash stock",
            "amount": 80,
            "payment_type": "cash",
            "category": "grocery",
            "supplier_id": self.supplier_id,
            "invoice_number": "INV-CLIENT-1",
            "entry_kind": "purchase",
        }
        data.update(overrides)
        return data

    def _create_cash(self, user=None, **overrides):
        user = user or self.admin_user
        with patch.object(app_module, "get_current_user", return_value=user):
            resp = self.client.post(
                "/accounts/purchase-ledger/add",
                json=self._payload(**overrides),
            )
        return resp

    def test_client_cash_create_is_cleared(self):
        resp = self._create_cash()
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        body = resp.get_json()
        self.assertTrue(body.get("ok"))
        expense_id = body["expense_id"]
        conn = self.db_mod.get_db()
        try:
            row = conn.execute(
                """SELECT payment_type, amount, cancelled_at, expense_code
                   FROM sales_update_expenses WHERE id = ?""",
                (expense_id,),
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(row["payment_type"], "cash")
        self.assertFalse(row["cancelled_at"])
        self.assertEqual(
            app_module._credit_settlement_status(row["payment_type"], row["amount"], 0),
            "cleared",
        )

    def test_client_non_admin_cannot_cancel(self):
        created = self._create_cash(invoice_number="INV-CLIENT-2")
        self.assertEqual(created.status_code, 200, created.get_data(as_text=True))
        expense_id = created.get_json()["expense_id"]
        with patch.object(app_module, "get_current_user", return_value=self.staff_user):
            denied = self.client.post(
                "/accounts/purchase-ledger/delete",
                json={"expense_id": expense_id},
            )
        self.assertEqual(denied.status_code, 403)
        body = denied.get_json()
        self.assertFalse(body.get("ok"))
        self.assertEqual(body.get("error"), app_module.PURCHASE_LEDGER_CANCEL_FORBIDDEN_MESSAGE)

    def test_client_admin_cancel_keeps_code_and_mints_next(self):
        created = self._create_cash(invoice_number="INV-CLIENT-3")
        self.assertEqual(created.status_code, 200, created.get_data(as_text=True))
        body = created.get_json()
        expense_id = body["expense_id"]
        code = body["expense_code"]
        with patch.object(app_module, "get_current_user", return_value=self.admin_user):
            cancelled = self.client.post(
                "/accounts/purchase-ledger/delete",
                json={"expense_id": expense_id},
            )
        self.assertEqual(cancelled.status_code, 200, cancelled.get_data(as_text=True))
        self.assertTrue(cancelled.get_json().get("ok"))
        conn = self.db_mod.get_db()
        try:
            row = conn.execute(
                """SELECT expense_code, cancelled_at FROM sales_update_expenses WHERE id = ?""",
                (expense_id,),
            ).fetchone()
            nxt = app_module._next_expense_code(conn, "HBE", "purchase")
            today = date.today()
            listed = app_module._purchase_ledger_entries(conn, today, today)
            cash_rows = app_module._cash_ledger_expense_rows(
                conn, "HBE", today, today, location="Hotel"
            )
        finally:
            conn.close()
        self.assertIsNotNone(row)
        self.assertEqual(row["expense_code"], code)
        self.assertTrue(row["cancelled_at"])
        prefix, _, num = code.rpartition("-")
        self.assertEqual(nxt, f"{prefix}-{int(num) + 1}")
        by_id = {item["id"]: item for item in listed}
        self.assertEqual(by_id[expense_id]["settlement_status"], "cancelled")
        self.assertNotIn(expense_id, {item["source_id"] for item in cash_rows})

    def test_client_edit_inside_4h_and_blocked_after(self):
        created = self._create_cash(invoice_number="INV-CLIENT-4")
        self.assertEqual(created.status_code, 200, created.get_data(as_text=True))
        expense_id = created.get_json()["expense_id"]
        edit_payload = self._payload(
            id=expense_id,
            invoice_number="INV-CLIENT-4",
            description="Edited inside window",
            amount=90,
        )
        with patch.object(app_module, "get_current_user", return_value=self.staff_user):
            inside = self.client.post("/accounts/purchase-ledger/edit", json=edit_payload)
        self.assertEqual(inside.status_code, 200, inside.get_data(as_text=True))
        old = (datetime.now() - timedelta(hours=5)).strftime("%Y-%m-%d %H:%M:%S")
        old_date = (date.today() - timedelta(days=40)).isoformat()
        conn = self.db_mod.get_db()
        try:
            conn.execute(
                "UPDATE sales_update_expenses SET created_at = ?, sales_date = ? WHERE id = ?",
                (old, old_date, expense_id),
            )
            conn.commit()
        finally:
            conn.close()
        with patch.object(app_module, "get_current_user", return_value=self.admin_user):
            outside = self.client.post(
                "/accounts/purchase-ledger/edit",
                json=self._payload(
                    id=expense_id,
                    invoice_number="INV-CLIENT-4",
                    description="Too late",
                    amount=95,
                ),
            )
        self.assertEqual(outside.status_code, 403)
        self.assertEqual(
            outside.get_json().get("error"),
            app_module.PURCHASE_LEDGER_EDIT_WINDOW_MESSAGE,
        )
