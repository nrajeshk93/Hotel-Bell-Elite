"""Employee payroll credits post to Expense Ledger as staff-advance expenses."""

import sqlite3
import unittest
from datetime import date

import app as app_module
from employee_payroll import (
    _delete_credit_advance_expense,
    _post_credit_advance_expense,
    _sync_credit_advance_expense,
)


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
        CREATE TABLE employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL
        );
        CREATE TABLE credits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            amount REAL NOT NULL DEFAULT 0,
            entry_type TEXT NOT NULL DEFAULT 'manual',
            expense_id INTEGER,
            FOREIGN KEY (employee_id) REFERENCES employees(id)
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
            supplier_id INTEGER,
            category TEXT NOT NULL DEFAULT '',
            expense_code TEXT NOT NULL DEFAULT '',
            invoice_number TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE cash_ledger_loads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company TEXT NOT NULL,
            load_date TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            amount REAL NOT NULL DEFAULT 0
        );
        CREATE TABLE cash_ledger_transfers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company TEXT NOT NULL,
            transfer_date TEXT NOT NULL,
            destination TEXT NOT NULL DEFAULT 'bank',
            description TEXT NOT NULL DEFAULT '',
            amount REAL NOT NULL DEFAULT 0
        );
        CREATE TABLE sales_updates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company TEXT NOT NULL,
            location TEXT NOT NULL,
            sales_date TEXT NOT NULL,
            sales_entry_values TEXT NOT NULL DEFAULT '{}'
        );
        """
    )
    return conn


class EmployeeCreditExpenseTests(unittest.TestCase):
    def setUp(self):
        self.conn = _memory_conn()
        self.user = {"id": 1, "is_admin": True}
        self.conn.execute("INSERT INTO employees (name) VALUES (?)", ("Ravi Kumar",))
        self.conn.execute(
            "INSERT INTO cash_ledger_loads (company, load_date, description, amount) VALUES (?,?,?,?)",
            (app_module.DEFAULT_COMPANY, "2026-07-01", "Float", 50000),
        )
        self.conn.commit()
        self.emp = self.conn.execute("SELECT id, name FROM employees WHERE id=1").fetchone()
        self.today = date.today().isoformat()

    def tearDown(self):
        self.conn.close()

    def _insert_credit(self, amount=2500, description="Emergency advance"):
        cursor = self.conn.execute(
            """INSERT INTO credits (employee_id, date, description, amount, entry_type)
               VALUES (?,?,?,?,?)""",
            (1, self.today, description, amount, "manual"),
        )
        self.conn.commit()
        return cursor.lastrowid

    def test_post_creates_expense_ledger_row(self):
        credit_id = self._insert_credit()
        result, error = _post_credit_advance_expense(
            self.conn,
            self.user,
            employee=self.emp,
            credit_id=credit_id,
            cr_date=self.today,
            description="Emergency advance",
            amount=2500,
            payment_type=app_module.EXPENSE_PAYMENT_CASH,
        )
        self.assertIsNone(error)
        self.assertIsNotNone(result)
        self.conn.commit()

        credit = self.conn.execute(
            "SELECT expense_id FROM credits WHERE id=?", (credit_id,)
        ).fetchone()
        self.assertEqual(credit["expense_id"], result["expense_id"])

        expense = self.conn.execute(
            "SELECT * FROM sales_update_expenses WHERE id=?",
            (result["expense_id"],),
        ).fetchone()
        self.assertEqual(expense["location"], app_module.OUTLET_HOTEL)
        self.assertEqual(expense["category"], "salary")
        self.assertEqual(expense["amount"], 2500)
        self.assertEqual(expense["payment_type"], "cash")
        self.assertIn("Ravi Kumar", expense["description"])
        self.assertEqual(expense["invoice_number"], f"EMP-ADV-{credit_id}")

        supplier = self.conn.execute(
            "SELECT name FROM suppliers WHERE id=?", (expense["supplier_id"],)
        ).fetchone()
        self.assertEqual(supplier["name"], "Staff Advances")

    def test_repayment_path_not_required_here_but_cash_validation_blocks(self):
        credit_id = self._insert_credit(amount=60000)
        result, error = _post_credit_advance_expense(
            self.conn,
            self.user,
            employee=self.emp,
            credit_id=credit_id,
            cr_date=self.today,
            description="Too large",
            amount=60000,
            payment_type=app_module.EXPENSE_PAYMENT_CASH,
        )
        self.assertIsNone(result)
        self.assertIn("available cash", error.lower())

    def test_bank_transfer_posts_without_cash_balance(self):
        credit_id = self._insert_credit(amount=60000)
        result, error = _post_credit_advance_expense(
            self.conn,
            self.user,
            employee=self.emp,
            credit_id=credit_id,
            cr_date=self.today,
            description="Bank advance",
            amount=60000,
            payment_type=app_module.EXPENSE_PAYMENT_BANK,
            transaction_id="UTR123",
        )
        self.assertIsNone(error)
        expense = self.conn.execute(
            "SELECT payment_type, transaction_id, amount FROM sales_update_expenses WHERE id=?",
            (result["expense_id"],),
        ).fetchone()
        self.assertEqual(expense["payment_type"], "bank_transfer")
        self.assertEqual(expense["transaction_id"], "UTR123")
        self.assertEqual(expense["amount"], 60000)

    def test_sync_and_delete_keep_expense_in_lockstep(self):
        credit_id = self._insert_credit()
        result, error = _post_credit_advance_expense(
            self.conn,
            self.user,
            employee=self.emp,
            credit_id=credit_id,
            cr_date=self.today,
            description="Emergency advance",
            amount=2500,
            payment_type=app_module.EXPENSE_PAYMENT_CASH,
        )
        self.assertIsNone(error)
        expense_id = result["expense_id"]
        self.conn.commit()

        sync_error = _sync_credit_advance_expense(
            self.conn,
            self.user,
            expense_id=expense_id,
            cr_date=self.today,
            description="Updated note",
            amount=3000,
            employee_name="Ravi Kumar",
        )
        self.assertIsNone(sync_error)
        self.conn.commit()
        expense = self.conn.execute(
            "SELECT amount, description FROM sales_update_expenses WHERE id=?",
            (expense_id,),
        ).fetchone()
        self.assertEqual(expense["amount"], 3000)
        self.assertIn("Updated note", expense["description"])

        delete_error = _delete_credit_advance_expense(self.conn, self.user, expense_id)
        self.assertIsNone(delete_error)
        self.conn.commit()
        gone = self.conn.execute(
            "SELECT id FROM sales_update_expenses WHERE id=?", (expense_id,)
        ).fetchone()
        self.assertIsNone(gone)


if __name__ == "__main__":
    unittest.main()
