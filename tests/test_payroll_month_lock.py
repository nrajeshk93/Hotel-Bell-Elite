"""Payroll month lock freezes edits for everyone, including admin."""

import sqlite3
import unittest
from datetime import date

from employee_payroll import (
    _can_modify_attendance_record,
    _employee_has_locked_month_data,
    _get_payroll_month_state,
    _is_credit_date_locked,
    _is_payroll_month_locked,
    _payroll_month_frozen_message,
    _wage_fields_changed,
)


def _memory_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE payroll_month_locks (
            year INTEGER NOT NULL,
            month INTEGER NOT NULL,
            locked_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            PRIMARY KEY (year, month)
        );
        CREATE TABLE employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            gross_salary REAL NOT NULL DEFAULT 0,
            basic_salary REAL NOT NULL DEFAULT 0,
            epf_amount REAL NOT NULL DEFAULT 0,
            esic_amount REAL NOT NULL DEFAULT 0,
            epf_exempt INTEGER NOT NULL DEFAULT 0,
            esic_exempt INTEGER NOT NULL DEFAULT 0,
            total_off INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE attendance (
            employee_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            status TEXT NOT NULL,
            updated_at TEXT
        );
        CREATE TABLE credits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            description TEXT,
            amount REAL NOT NULL DEFAULT 0
        );
        CREATE TABLE tip_incentive_payouts (
            company TEXT NOT NULL,
            year INTEGER NOT NULL,
            month INTEGER NOT NULL,
            employee_id INTEGER NOT NULL,
            amount REAL NOT NULL DEFAULT 0
        );
        """
    )
    return conn


class PayrollMonthLockTests(unittest.TestCase):
    def setUp(self):
        self.conn = _memory_conn()
        self.conn.execute("INSERT INTO employees (name, gross_salary) VALUES (?, ?)", ("Asha", 20000))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_locked_state_blocks_can_edit(self):
        self.conn.execute("INSERT INTO payroll_month_locks (year, month) VALUES (2026, 7)")
        self.conn.commit()
        state = _get_payroll_month_state(self.conn, 2026, 7)
        self.assertTrue(state["locked"])
        self.assertFalse(state["can_edit"])
        self.assertIn("administrators", state["message"].lower())

    def test_admin_cannot_modify_attendance_when_payroll_locked(self):
        admin = {"is_admin": True}
        att_dt = date(2026, 7, 10)
        self.assertTrue(_can_modify_attendance_record(admin, att_dt, payroll_locked=False))
        self.assertFalse(_can_modify_attendance_record(admin, att_dt, payroll_locked=True))

    def test_credit_date_lock(self):
        self.conn.execute("INSERT INTO payroll_month_locks (year, month) VALUES (2026, 7)")
        self.conn.commit()
        self.assertTrue(_is_payroll_month_locked(self.conn, 2026, 7))
        self.assertTrue(_is_credit_date_locked(self.conn, "2026-07-15"))
        self.assertFalse(_is_credit_date_locked(self.conn, "2026-08-01"))

    def test_employee_has_locked_month_data(self):
        self.conn.execute("INSERT INTO payroll_month_locks (year, month) VALUES (2026, 7)")
        self.conn.execute(
            "INSERT INTO attendance (employee_id, date, status) VALUES (1, '2026-07-05', 'present')"
        )
        self.conn.commit()
        self.assertTrue(_employee_has_locked_month_data(self.conn, 1))
        self.assertFalse(_employee_has_locked_month_data(self.conn, 999))

    def test_wage_fields_changed(self):
        existing = {
            "gross_salary": 20000,
            "basic_salary": 0,
            "epf_amount": 0,
            "esic_amount": 0,
            "epf_exempt": 0,
            "esic_exempt": 0,
            "total_off": 4,
        }
        self.assertFalse(_wage_fields_changed(existing, {
            "gross_salary": 20000,
            "basic_salary": 0,
            "epf_amount": 0,
            "esic_amount": 0,
            "epf_exempt": 0,
            "esic_exempt": 0,
            "total_off": 4,
        }))
        self.assertTrue(_wage_fields_changed(existing, {
            "gross_salary": 21000,
            "basic_salary": 0,
            "epf_amount": 0,
            "esic_amount": 0,
            "epf_exempt": 0,
            "esic_exempt": 0,
            "total_off": 4,
        }))

    def test_frozen_message_mentions_modules(self):
        msg = _payroll_month_frozen_message(2026, 7).lower()
        self.assertIn("attendance", msg)
        self.assertIn("credit", msg)
        self.assertIn("administrators", msg)


if __name__ == "__main__":
    unittest.main()
