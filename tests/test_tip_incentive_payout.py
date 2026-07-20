"""Tests for monthly tip incentive pool, save validation, and net salary."""

import sqlite3
import unittest

import app as app_module
from employee_payroll import (
    _calc_salary,
    _get_month_tip_incentive,
    _get_payroll_month_state,
    _upsert_month_tip_incentive,
)


class _NoCloseConn:
    """Wrap a sqlite connection so route finally-blocks do not wipe :memory: DBs."""

    def __init__(self, conn):
        self._conn = conn

    def close(self):
        return None

    def __getattr__(self, name):
        return getattr(self._conn, name)


def _memory_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(
        """
        CREATE TABLE employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            emp_code TEXT NOT NULL DEFAULT '',
            name TEXT NOT NULL,
            company TEXT NOT NULL DEFAULT '',
            location TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'active',
            gross_salary REAL NOT NULL DEFAULT 0,
            basic_salary REAL NOT NULL DEFAULT 0,
            epf_amount REAL NOT NULL DEFAULT 0,
            esic_amount REAL NOT NULL DEFAULT 0,
            epf_exempt INTEGER NOT NULL DEFAULT 0,
            esic_exempt INTEGER NOT NULL DEFAULT 0,
            weekday_shift TEXT NOT NULL DEFAULT '',
            sunday_shift TEXT NOT NULL DEFAULT '',
            total_off INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE sales_update_tips (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company TEXT NOT NULL,
            location TEXT NOT NULL,
            sales_date TEXT NOT NULL,
            employee_id INTEGER NOT NULL,
            amount REAL NOT NULL DEFAULT 0,
            description TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE CASCADE
        );
        CREATE TABLE tip_incentive_payouts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company TEXT NOT NULL,
            year INTEGER NOT NULL,
            month INTEGER NOT NULL,
            employee_id INTEGER NOT NULL,
            amount REAL NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            UNIQUE(company, year, month, employee_id),
            FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE CASCADE
        );
        CREATE TABLE payroll_month_locks (
            year INTEGER NOT NULL,
            month INTEGER NOT NULL,
            locked_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            PRIMARY KEY (year, month)
        );
        """
    )
    return conn


class TipIncentivePoolTests(unittest.TestCase):
    def setUp(self):
        self.conn = _memory_conn()
        self.conn.execute(
            "INSERT INTO employees (emp_code, name, company, location) VALUES (?,?,?,?)",
            ("HBE001", "Alice", "Hotel Bell Elite", "FO"),
        )
        self.conn.execute(
            "INSERT INTO employees (emp_code, name, company, location, status) VALUES (?,?,?,?,?)",
            ("HBE002", "Bob", "Hotel Bell Elite", "BAR", "inactive"),
        )
        self.conn.executemany(
            """INSERT INTO sales_update_tips
               (company, location, sales_date, employee_id, amount)
               VALUES (?,?,?,?,?)""",
            [
                ("HBE", "Hotel", "2026-07-01", 1, 100),
                ("HBE", "Bar", "2026-07-15", 1, 50.5),
                ("HBE", "Restaurant", "2026-07-31", 1, 49.5),
                ("HBE", "Hotel", "2026-06-30", 1, 999),
                ("HBE", "Hotel", "2026-08-01", 1, 999),
            ],
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_month_tip_pool_sums_calendar_month_all_outlets(self):
        total = app_module._month_tip_pool_total(self.conn, "HBE", 2026, 7)
        self.assertEqual(total, 200.0)

    def test_available_tip_pool_spans_all_months_minus_other_payouts(self):
        # All tips: 200 (Jul) + 999 (Jun) + 999 (Aug) = 2198
        self.assertEqual(app_module._available_tip_pool_total(self.conn, "HBE", 2026, 7), 2198.0)
        _upsert_month_tip_incentive(self.conn, "HBE", 2026, 6, 1, 200)
        self.conn.commit()
        # June payout reduces available for July editing
        self.assertEqual(app_module._available_tip_pool_total(self.conn, "HBE", 2026, 7), 1998.0)
        # Current-month payout is not deducted from available (editable against Remaining)
        _upsert_month_tip_incentive(self.conn, "HBE", 2026, 7, 1, 50)
        self.conn.commit()
        self.assertEqual(app_module._available_tip_pool_total(self.conn, "HBE", 2026, 7), 1998.0)

    def test_payload_lists_active_employees_and_remaining(self):
        _upsert_month_tip_incentive(self.conn, "HBE", 2026, 7, 1, 75)
        self.conn.commit()
        payload = app_module._tips_incentive_payout_payload(self.conn, "HBE", 2026, 7)
        # Available = all tips (2198), not July-only (200)
        self.assertEqual(payload["total_tips"], 2198.0)
        self.assertEqual(payload["allocated"], 75.0)
        self.assertEqual(payload["remaining"], 2123.0)
        self.assertEqual(len(payload["employees"]), 1)
        self.assertEqual(payload["employees"][0]["id"], 1)
        self.assertEqual(payload["employees"][0]["amount"], 75.0)


class TipIncentiveSaveTests(unittest.TestCase):
    def setUp(self):
        self.conn = _memory_conn()
        self.conn.execute(
            "INSERT INTO employees (emp_code, name, company, location) VALUES (?,?,?,?)",
            ("HBE001", "Alice", "Hotel Bell Elite", "FO"),
        )
        self.conn.execute(
            """INSERT INTO sales_update_tips
               (company, location, sales_date, employee_id, amount)
               VALUES (?,?,?,?,?)""",
            ("HBE", "Hotel", "2026-07-10", 1, 100),
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_upsert_and_zero_clears(self):
        _upsert_month_tip_incentive(self.conn, "HBE", 2026, 7, 1, 40)
        self.assertEqual(_get_month_tip_incentive(self.conn, 1, 2026, 7, company="HBE"), 40.0)
        _upsert_month_tip_incentive(self.conn, "HBE", 2026, 7, 1, 0)
        self.assertEqual(_get_month_tip_incentive(self.conn, 1, 2026, 7, company="HBE"), 0.0)

    def test_delete_tip_clears_employee_incentive_payout(self):
        tip_id = self.conn.execute(
            "SELECT id FROM sales_update_tips WHERE company=? LIMIT 1",
            ("HBE",),
        ).fetchone()["id"]
        _upsert_month_tip_incentive(self.conn, "HBE", 2026, 7, 1, 100)
        self.conn.commit()
        self.assertEqual(_get_month_tip_incentive(self.conn, 1, 2026, 7, company="HBE"), 100.0)

        app_module.app.config["TESTING"] = True
        admin = {
            "id": 1,
            "username": "admin",
            "is_admin": True,
            "is_active": True,
        }
        with app_module.app.test_request_context(
            "/sales_update/delete_tip",
            method="POST",
            json={
                "id": tip_id,
                "company": "HBE",
                "location": "Hotel",
                "date": "2026-07-10",
            },
        ):
            original_get_db = app_module.get_db
            original_user = app_module.get_current_user
            wrapped = _NoCloseConn(self.conn)
            app_module.get_db = lambda: wrapped
            app_module.get_current_user = lambda: admin
            try:
                resp = app_module.sales_update_delete_tip()
                if isinstance(resp, tuple):
                    body, status = resp
                else:
                    body, status = resp, 200
                data = body.get_json()
                self.assertEqual(status, 200)
                self.assertTrue(data["ok"])
                gone = self.conn.execute(
                    "SELECT id FROM sales_update_tips WHERE id=?", (tip_id,)
                ).fetchone()
                self.assertIsNone(gone)
                self.assertEqual(
                    _get_month_tip_incentive(self.conn, 1, 2026, 7, company="HBE"),
                    0.0,
                )
            finally:
                app_module.get_db = original_get_db
                app_module.get_current_user = original_user

    def test_delete_employee_tips_clears_incentive_payout(self):
        tip_count = self.conn.execute(
            "SELECT COUNT(*) AS c FROM sales_update_tips WHERE employee_id=1 AND company=?",
            ("HBE",),
        ).fetchone()["c"]
        self.assertGreaterEqual(tip_count, 1)
        _upsert_month_tip_incentive(self.conn, "HBE", 2026, 7, 1, 100)
        self.conn.commit()

        app_module.app.config["TESTING"] = True
        admin = {"id": 1, "username": "admin", "is_admin": True, "is_active": True}
        with app_module.app.test_request_context(
            "/sales_update/tips/delete_employee",
            method="POST",
            json={
                "company": "HBE",
                "location": "All",
                "employee_id": 1,
            },
        ):
            original_get_db = app_module.get_db
            original_user = app_module.get_current_user
            wrapped = _NoCloseConn(self.conn)
            app_module.get_db = lambda: wrapped
            app_module.get_current_user = lambda: admin
            try:
                resp = app_module.sales_update_tips_delete_employee()
                if isinstance(resp, tuple):
                    body, status = resp
                else:
                    body, status = resp, 200
                data = body.get_json()
                self.assertEqual(status, 200)
                self.assertTrue(data["ok"])
                remaining = self.conn.execute(
                    "SELECT COUNT(*) AS c FROM sales_update_tips WHERE employee_id=1 AND company=?",
                    ("HBE",),
                ).fetchone()["c"]
                self.assertEqual(remaining, 0)
                self.assertEqual(
                    _get_month_tip_incentive(self.conn, 1, 2026, 7, company="HBE"),
                    0.0,
                )
            finally:
                app_module.get_db = original_get_db
                app_module.get_current_user = original_user

    def test_delete_tip_clears_overallocated_month_payouts(self):
        """If tip collector differs from payout recipient, clear month when pool breaks."""
        self.conn.execute(
            "INSERT INTO employees (emp_code, name, company, location) VALUES (?,?,?,?)",
            ("HBE002", "Bob", "Hotel Bell Elite", "BAR"),
        )
        tip_id = self.conn.execute(
            "SELECT id FROM sales_update_tips WHERE company=? LIMIT 1",
            ("HBE",),
        ).fetchone()["id"]
        # Alice collected the tip; Bob received the incentive.
        _upsert_month_tip_incentive(self.conn, "HBE", 2026, 7, 2, 100)
        self.conn.commit()

        app_module.app.config["TESTING"] = True
        admin = {"id": 1, "username": "admin", "is_admin": True, "is_active": True}
        with app_module.app.test_request_context(
            "/sales_update/delete_tip",
            method="POST",
            json={
                "id": tip_id,
                "company": "HBE",
                "location": "Hotel",
                "date": "2026-07-10",
            },
        ):
            original_get_db = app_module.get_db
            original_user = app_module.get_current_user
            wrapped = _NoCloseConn(self.conn)
            app_module.get_db = lambda: wrapped
            app_module.get_current_user = lambda: admin
            try:
                resp = app_module.sales_update_delete_tip()
                if isinstance(resp, tuple):
                    body, status = resp
                else:
                    body, status = resp, 200
                data = body.get_json()
                self.assertEqual(status, 200)
                self.assertTrue(data["ok"])
                # No tips left → available 0 → Bob's month payout must be cleared.
                self.assertEqual(
                    _get_month_tip_incentive(self.conn, 2, 2026, 7, company="HBE"),
                    0.0,
                )
            finally:
                app_module.get_db = original_get_db
                app_module.get_current_user = original_user

    def test_route_rejects_over_allocation(self):
        app_module.app.config["TESTING"] = True
        with app_module.app.test_request_context(
            "/sales_update/tips/incentive-payout",
            method="POST",
            json={
                "company": "HBE",
                "year": 2026,
                "month": 7,
                "allocations": [{"employee_id": 1, "amount": 150}],
            },
        ):
            # Patch get_db for this request so the route uses our memory DB.
            original_get_db = app_module.get_db
            wrapped = _NoCloseConn(self.conn)
            app_module.get_db = lambda: wrapped
            try:
                # Ensure month is editable under lock rules.
                state = _get_payroll_month_state(self.conn, 2026, 7)
                self.assertTrue(state["can_edit"])
                resp = app_module.tips_incentive_payout()
                if isinstance(resp, tuple):
                    body, status = resp
                else:
                    body, status = resp, resp.status_code
                data = body.get_json()
                self.assertEqual(status, 400)
                self.assertFalse(data["ok"])
                self.assertIn("exceeds available tip pool", data["error"].lower())
            finally:
                app_module.get_db = original_get_db

    def test_route_saves_within_pool(self):
        app_module.app.config["TESTING"] = True
        with app_module.app.test_request_context(
            "/sales_update/tips/incentive-payout",
            method="POST",
            json={
                "company": "HBE",
                "year": 2026,
                "month": 7,
                "allocations": [{"employee_id": 1, "amount": 80}],
            },
        ):
            original_get_db = app_module.get_db
            wrapped = _NoCloseConn(self.conn)
            app_module.get_db = lambda: wrapped
            try:
                resp = app_module.tips_incentive_payout()
                if isinstance(resp, tuple):
                    body, status = resp
                else:
                    body, status = resp, 200
                data = body.get_json()
                self.assertEqual(status, 200)
                self.assertTrue(data["ok"])
                self.assertEqual(data["allocated"], 80.0)
                self.assertEqual(data["remaining"], 20.0)
                self.assertEqual(
                    _get_month_tip_incentive(self.conn, 1, 2026, 7, company="HBE"),
                    80.0,
                )
            finally:
                app_module.get_db = original_get_db

    def test_route_rejects_locked_month(self):
        self.conn.execute(
            "INSERT INTO payroll_month_locks (year, month) VALUES (?, ?)",
            (2026, 7),
        )
        self.conn.commit()
        app_module.app.config["TESTING"] = True
        with app_module.app.test_request_context(
            "/sales_update/tips/incentive-payout",
            method="POST",
            json={
                "company": "HBE",
                "year": 2026,
                "month": 7,
                "allocations": [{"employee_id": 1, "amount": 40}],
            },
        ):
            original_get_db = app_module.get_db
            wrapped = _NoCloseConn(self.conn)
            app_module.get_db = lambda: wrapped
            try:
                state = _get_payroll_month_state(self.conn, 2026, 7)
                self.assertFalse(state["can_edit"])
                resp = app_module.tips_incentive_payout()
                if isinstance(resp, tuple):
                    body, status = resp
                else:
                    body, status = resp, resp.status_code
                data = body.get_json()
                self.assertEqual(status, 403)
                self.assertFalse(data["ok"])
                self.assertIn("locked", data["error"].lower())
                self.assertEqual(
                    _get_month_tip_incentive(self.conn, 1, 2026, 7, company="HBE"),
                    0.0,
                )
            finally:
                app_module.get_db = original_get_db


class TipIncentiveNetSalaryTests(unittest.TestCase):
    def test_calc_salary_includes_tip_incentive_in_net(self):
        salary = _calc_salary(
            20000,
            calendar_days=30,
            weekday_leave_days=0,
            total_off=0,
            tracked=True,
            tip_incentive=250,
        )
        self.assertEqual(salary["tip_incentive"], 250.0)
        expected_without_tip = salary["net"] - 250
        baseline = _calc_salary(
            20000,
            calendar_days=30,
            weekday_leave_days=0,
            total_off=0,
            tracked=True,
            tip_incentive=0,
        )
        self.assertEqual(salary["net"], baseline["net"] + 250)
        self.assertAlmostEqual(expected_without_tip, baseline["net"], places=2)


if __name__ == "__main__":
    unittest.main()
