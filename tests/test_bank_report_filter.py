"""Bank report includes only EPF employees with complete bank details."""

import sqlite3
import unittest
from datetime import date
from unittest import mock

from employee_payroll import _load_bank_report


def _memory_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            emp_code TEXT NOT NULL DEFAULT '',
            name TEXT NOT NULL,
            location TEXT NOT NULL DEFAULT '',
            mobile TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'active',
            epf_exempt INTEGER NOT NULL DEFAULT 0,
            account_holder_name TEXT NOT NULL DEFAULT '',
            account_number TEXT NOT NULL DEFAULT '',
            ifsc_code TEXT NOT NULL DEFAULT ''
        );
        """
    )
    return conn


class BankReportFilterTests(unittest.TestCase):
    def setUp(self):
        self.conn = _memory_conn()
        self.conn.executemany(
            """INSERT INTO employees
               (emp_code, name, location, mobile, status, epf_exempt,
                account_holder_name, account_number, ifsc_code)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                ("E1", "EPF WITH BANK", "Bar", "9000000001", "active", 0, "EPF WITH BANK", "123456", "ICIC0001234"),
                ("E2", "A PARWATHI", "Utility", "9000000002", "active", 0, "", "", ""),
                ("E3", "NON EPF WITH BANK", "Security", "9000000003", "active", 1, "NON EPF", "999888", "SBIN0001111"),
                ("E4", "EPF MISSING IFSC", "Bar", "9000000004", "active", 0, "EPF MISSING IFSC", "555666", ""),
            ],
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_only_epf_with_account_and_ifsc(self):
        def fake_attach(conn, row, year, month, payroll_state=None):
            data = dict(row)
            data["net"] = 1000
            return data

        with mock.patch(
            "employee_payroll._attach_employee_month_context",
            side_effect=fake_attach,
        ):
            report = _load_bank_report(self.conn, date.today().year, date.today().month)

        names = [r["employee_name"] for r in report["rows"]]
        self.assertEqual(names, ["EPF WITH BANK"])
        self.assertEqual(report["count"], 1)
        self.assertEqual(report["ft_count"], 1)
        self.assertEqual(report["neft_count"], 0)


if __name__ == "__main__":
    unittest.main()
