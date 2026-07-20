"""Tests for multi-outlet tip lines and Tips analytics rollup."""

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
        CREATE TABLE employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            emp_code TEXT NOT NULL DEFAULT '',
            name TEXT NOT NULL,
            company TEXT NOT NULL DEFAULT '',
            location TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'active'
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
        CREATE TABLE credits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            amount REAL NOT NULL DEFAULT 0,
            entry_type TEXT NOT NULL DEFAULT 'manual',
            payroll_year INTEGER,
            payroll_month INTEGER,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );
        """
    )
    return conn


class SalesTipsAnalyticsTests(unittest.TestCase):
    def setUp(self):
        self.conn = _memory_conn()
        self.conn.execute(
            "INSERT INTO employees (emp_code, name, status) VALUES (?, ?, ?)",
            ("E001", "Anita", "active"),
        )
        self.conn.execute(
            "INSERT INTO employees (emp_code, name, status) VALUES (?, ?, ?)",
            ("E002", "Ravi", "active"),
        )
        self.conn.executemany(
            """INSERT INTO sales_update_tips
               (company, location, sales_date, employee_id, amount, description)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [
                ("HBE", "Hotel", "2026-07-10", 1, 100, ""),
                ("HBE", "Bar", "2026-07-11", 1, 50, ""),
                ("HBE", "Restaurant", "2026-07-12", 1, 25, ""),
                ("HBE", "Bar", "2026-07-12", 2, 80, ""),
            ],
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_tip_outlets_include_bar_and_restaurant(self):
        self.assertIn("Bar", app_module.TIP_OUTLET_LOCATIONS)
        self.assertIn("Restaurant", app_module.TIP_OUTLET_LOCATIONS)
        self.assertIn("Hotel", app_module.TIP_OUTLET_LOCATIONS)

    def test_apply_tip_line_total_for_bar(self):
        values = {"tips": 0, "cash": 10}
        app_module._apply_tip_line_total(self.conn, "HBE", "Bar", "2026-07-11", values)
        self.assertEqual(values["tips"], 50.0)

    def test_analytics_pivot_by_employee_and_outlet(self):
        bundle = app_module._load_tips_analytics_bundle(
            self.conn,
            "HBE",
            date(2026, 7, 1),
            date(2026, 7, 31),
            None,
        )
        self.assertEqual(bundle["grand_total"], 255.0)
        self.assertEqual(bundle["hotel_total"], 100.0)
        self.assertEqual(bundle["bar_total"], 130.0)
        self.assertEqual(bundle["restaurant_total"], 25.0)
        self.assertEqual(len(bundle["employees"]), 2)
        anita = next(row for row in bundle["employees"] if row["employee_id"] == 1)
        self.assertEqual(anita["hotel"], 100.0)
        self.assertEqual(anita["bar"], 50.0)
        self.assertEqual(anita["restaurant"], 25.0)
        self.assertEqual(anita["total"], 175.0)
        self.assertEqual(bundle["employees"][0]["employee_id"], 1)

    def test_analytics_location_filter(self):
        bundle = app_module._load_tips_analytics_bundle(
            self.conn,
            "HBE",
            date(2026, 7, 1),
            date(2026, 7, 31),
            "Bar",
        )
        self.assertEqual(bundle["grand_total"], 130.0)
        self.assertEqual(bundle["hotel_total"], 0.0)
        self.assertEqual(bundle["bar_total"], 130.0)

    def test_analytics_does_not_write_credits(self):
        before = self.conn.execute("SELECT COUNT(*) AS cnt FROM credits").fetchone()["cnt"]
        app_module._load_tips_analytics_bundle(
            self.conn,
            "HBE",
            date(2026, 7, 1),
            date(2026, 7, 31),
            None,
        )
        after = self.conn.execute("SELECT COUNT(*) AS cnt FROM credits").fetchone()["cnt"]
        self.assertEqual(before, 0)
        self.assertEqual(after, 0)

    def test_tips_detail_entries_for_report(self):
        rows = app_module._load_tips_detail_entries(
            self.conn,
            "HBE",
            date(2026, 7, 1),
            date(2026, 7, 31),
            None,
        )
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0]["sales_date"], "2026-07-10")
        self.assertEqual(rows[0]["employee_name"], "Anita")
        self.assertEqual(rows[0]["location"], "Hotel")
        self.assertEqual(rows[0]["amount"], 100.0)
        bar_only = app_module._load_tips_detail_entries(
            self.conn,
            "HBE",
            date(2026, 7, 1),
            date(2026, 7, 31),
            "Bar",
        )
        self.assertEqual(len(bar_only), 2)
        self.assertTrue(all(row["location"] == "Bar" for row in bar_only))

    def test_employee_lines_endpoint_for_edit_modal(self):
        class _NoClose:
            def __init__(self, conn):
                self._conn = conn
            def close(self):
                return None
            def __getattr__(self, name):
                return getattr(self._conn, name)

        app_module.app.config["TESTING"] = True
        with app_module.app.test_request_context(
            "/sales_update/tips/employee_lines",
            method="POST",
            json={
                "company": "HBE",
                "location": "All",
                "date_from": "2026-07-01",
                "date_to": "2026-07-31",
                "employee_id": 1,
            },
        ):
            original = app_module.get_db
            app_module.get_db = lambda: _NoClose(self.conn)
            try:
                resp = app_module.sales_update_tips_employee_lines()
                if isinstance(resp, tuple):
                    body, status = resp
                else:
                    body, status = resp, 200
                data = body.get_json()
                self.assertEqual(status, 200)
                self.assertTrue(data["ok"])
                self.assertEqual(data["employee"]["name"], "Anita")
                self.assertEqual(len(data["lines"]), 3)
                self.assertTrue(all(line["employee_id"] == 1 for line in data["lines"]))
            finally:
                app_module.get_db = original


if __name__ == "__main__":
    unittest.main()
