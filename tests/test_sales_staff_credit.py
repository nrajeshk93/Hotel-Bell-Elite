"""Hotel Sales Entry staff credit wired to Employee Payroll credits ledger."""

import json
import os
import sqlite3
import tempfile
import unittest
from unittest import mock

import db as db_mod


class SalesStaffCreditHelperTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(
            """
            CREATE TABLE employees (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                emp_code TEXT NOT NULL DEFAULT '',
                name TEXT NOT NULL,
                company TEXT NOT NULL DEFAULT '',
                location TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active'
            );
            CREATE TABLE credits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                amount REAL NOT NULL DEFAULT 0,
                entry_type TEXT NOT NULL DEFAULT 'manual',
                sales_company TEXT,
                sales_location TEXT,
                expense_id INTEGER,
                created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                FOREIGN KEY (employee_id) REFERENCES employees(id)
            );
            """
        )
        self.conn.execute(
            "INSERT INTO employees (name, emp_code, status) VALUES (?, ?, 'active')",
            ("Ravi Kumar", "E001"),
        )
        self.conn.commit()
        import app as app_module

        self.app_module = app_module

    def tearDown(self):
        self.conn.close()

    def _insert_credit(self, *, amount, sales_company="", sales_location="", entry_type="manual"):
        return self.conn.execute(
            """INSERT INTO credits
               (employee_id, date, description, amount, entry_type, sales_company, sales_location)
               VALUES (1, '2026-08-17', 'Advance', ?, ?, ?, ?)""",
            (amount, entry_type, sales_company, sales_location),
        ).lastrowid

    def test_scoped_total_only_counts_hotel_sales_entry_credits(self):
        self._insert_credit(amount=500, sales_company="HBE", sales_location="Hotel")
        self._insert_credit(amount=300, sales_company="", sales_location="")
        self._insert_credit(amount=100, sales_company="HBE", sales_location="Hotel", entry_type="manual_repayment")
        self.conn.commit()
        total = self.app_module._sales_staff_account_total(
            self.conn, "HBE", "Hotel", "2026-08-17"
        )
        self.assertEqual(total, 500.0)
        entries = self.app_module._sales_staff_account_entries(
            self.conn, "HBE", "Hotel", "2026-08-17"
        )
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["amount"], 500.0)
        self.assertEqual(entries[0]["employee_name"], "Ravi Kumar")


class SalesStaffCreditRouteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db_path = self.tmp.name
        self._orig_path = db_mod.DATABASE_PATH
        db_mod.DATABASE_PATH = self.db_path
        db_mod.init_db()

        import app as app_mod

        self.app_mod = app_mod
        self.app = app_mod.app
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

        conn = db_mod.get_db()
        try:
            admin = conn.execute("SELECT id FROM users WHERE username = 'admin'").fetchone()
            self.admin_id = admin["id"]
            cur = conn.execute(
                """INSERT INTO employees
                   (emp_code, name, company, location, status, gross_salary, basic_salary)
                   VALUES ('E001', 'Ravi Kumar', ?, ?, 'active', 0, 0)""",
                (app_mod.DEFAULT_COMPANY, app_mod.OUTLET_HOTEL),
            )
            self.employee_id = cur.lastrowid
            conn.execute(
                """INSERT INTO cash_ledger_loads (company, load_date, description, amount)
                   VALUES (?, '2026-08-17', 'Float', 50000)""",
                (app_mod.DEFAULT_COMPANY,),
            )
            conn.commit()
        finally:
            conn.close()

        self.user = {
            "id": self.admin_id,
            "username": "admin",
            "full_name": "Admin",
            "is_admin": True,
            "is_active": True,
            "dashboard_access": set(),
            "sales_analytics_access": {"hotel"},
            "stores_access": set(),
        }
        self._get_user_patch = mock.patch.object(
            app_mod, "get_current_user", return_value=self.user
        )
        self._get_user_patch.start()

    def tearDown(self):
        self._get_user_patch.stop()
        db_mod.DATABASE_PATH = self._orig_path
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def _post(self, path, payload):
        return self.client.post(
            path,
            data=json.dumps(payload),
            content_type="application/json",
        )

    def test_add_staff_credit_creates_scoped_credit_and_expense(self):
        resp = self._post(
            "/sales_update/add_staff_credit",
            {
                "company": self.app_mod.DEFAULT_COMPANY,
                "location": "Hotel",
                "date": "2026-08-17",
                "employee_id": self.employee_id,
                "amount": 1500,
                "description": "Kitchen advance",
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["staff_account_total"], 1500.0)
        self.assertEqual(len(data["staff_account_entries"]), 1)

        conn = db_mod.get_db()
        try:
            credit = conn.execute(
                """SELECT sales_company, sales_location, amount, expense_id, entry_type
                   FROM credits WHERE employee_id=?""",
                (self.employee_id,),
            ).fetchone()
            self.assertIsNotNone(credit)
            self.assertEqual(credit["sales_company"], self.app_mod.DEFAULT_COMPANY)
            self.assertEqual(credit["sales_location"], "Hotel")
            self.assertEqual(credit["amount"], 1500.0)
            self.assertEqual(credit["entry_type"], "manual")
            self.assertIsNotNone(credit["expense_id"])
            expense = conn.execute(
                "SELECT amount, payment_type FROM sales_update_expenses WHERE id=?",
                (credit["expense_id"],),
            ).fetchone()
            self.assertIsNotNone(expense)
            self.assertEqual(expense["amount"], 1500.0)
            self.assertEqual(expense["payment_type"], "cash")
        finally:
            conn.close()

        dashboard = self.client.get("/credits")
        self.assertEqual(dashboard.status_code, 200)
        html = dashboard.get_data(as_text=True)
        self.assertIn("Kitchen advance", html)
        self.assertIn("Ravi Kumar", html)
        self.assertIn("Recent Entries", html)
        self.assertIn('data-de-allow-soft-submit="1"', html)

    def test_add_staff_credit_cannot_exceed_available_cash(self):
        resp = self._post(
            "/sales_update/add_staff_credit",
            {
                "company": self.app_mod.DEFAULT_COMPANY,
                "location": "Hotel",
                "date": "2026-08-17",
                "employee_id": self.employee_id,
                "amount": 60000,
                "description": "Too large",
            },
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("available cash", (resp.get_json() or {}).get("error", "").lower())

    def test_edit_and_delete_staff_credit(self):
        add = self._post(
            "/sales_update/add_staff_credit",
            {
                "company": self.app_mod.DEFAULT_COMPANY,
                "location": "Hotel",
                "date": "2026-08-17",
                "employee_id": self.employee_id,
                "amount": 1000,
                "description": "Advance",
            },
        )
        credit_id = add.get_json()["credit_id"]

        edit = self._post(
            "/sales_update/edit_staff_credit",
            {
                "company": self.app_mod.DEFAULT_COMPANY,
                "location": "Hotel",
                "date": "2026-08-17",
                "credit_id": credit_id,
                "employee_id": self.employee_id,
                "amount": 1200,
                "description": "Updated advance",
            },
        )
        self.assertEqual(edit.status_code, 200)
        self.assertEqual(edit.get_json()["staff_account_total"], 1200.0)

        delete = self._post(
            "/sales_update/delete_staff_credit",
            {
                "company": self.app_mod.DEFAULT_COMPANY,
                "location": "Hotel",
                "date": "2026-08-17",
                "credit_id": credit_id,
            },
        )
        self.assertEqual(delete.status_code, 200)
        self.assertEqual(delete.get_json()["staff_account_total"], 0.0)

        conn = db_mod.get_db()
        try:
            count = conn.execute("SELECT COUNT(*) AS cnt FROM credits").fetchone()["cnt"]
            self.assertEqual(count, 0)
        finally:
            conn.close()

    def test_hotel_page_renders_employee_credit_row(self):
        page = self.client.get("/sales_update/hotel?date=2026-08-17")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn("Employee Credit", html)
        self.assertIn("open-staff-credit", html)
        self.assertIn("Guest Credit", html)
        self.assertIn("staff-credit-available-cash", html)
        self.assertIn("Available Cash", html)


if __name__ == "__main__":
    unittest.main()
