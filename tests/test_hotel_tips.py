"""Tests for Hotel sales tip lines linked to employees."""

import sqlite3
import unittest

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
        """
    )
    return conn


class HotelTipsHelperTests(unittest.TestCase):
    def test_tip_total_and_entries_by_employee(self):
        conn = _memory_conn()
        conn.execute(
            "INSERT INTO employees (emp_code, name, status) VALUES (?, ?, ?)",
            ("E001", "Anita", "active"),
        )
        conn.execute(
            "INSERT INTO employees (emp_code, name, status) VALUES (?, ?, ?)",
            ("E002", "Ravi", "active"),
        )
        conn.execute(
            """INSERT INTO sales_update_tips
               (company, location, sales_date, employee_id, amount, description)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("HBE", "Hotel", "2026-07-18", 1, 150, "Morning"),
        )
        conn.execute(
            """INSERT INTO sales_update_tips
               (company, location, sales_date, employee_id, amount, description)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("HBE", "Hotel", "2026-07-18", 2, 75.5, ""),
        )
        conn.commit()

        total = app_module._sales_tip_total(conn, "HBE", "Hotel", "2026-07-18")
        self.assertEqual(total, 225.5)

        entries = app_module._sales_tip_entries(conn, "HBE", "Hotel", "2026-07-18")
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["employee_name"], "Anita")
        self.assertEqual(entries[0]["employee_code"], "E001")
        self.assertEqual(entries[0]["employee_id"], 1)
        self.assertEqual(entries[1]["employee_name"], "Ravi")
        self.assertEqual(entries[1]["amount"], 75.5)

        self.assertEqual(
            app_module._sales_tip_line_count(conn, "HBE", "Hotel", "2026-07-18"),
            2,
        )
        self.assertEqual(
            app_module._sales_tip_line_count(conn, "HBE", "Hotel", "2026-07-17"),
            0,
        )

        employees = app_module._active_employees_for_tips(conn)
        self.assertEqual([row["name"] for row in employees], ["Anita", "Ravi"])
        conn.close()


if __name__ == "__main__":
    unittest.main()
