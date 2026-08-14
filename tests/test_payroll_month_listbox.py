"""Monthly Payroll and Attendance month listboxes include every month."""

import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import db as db_mod

MONTH_LABELS = [
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
]
ROOT = Path(__file__).resolve().parents[1]


def _listbox_values(html, list_id):
    marker = f'id="{list_id}"'
    start = html.find(marker)
    if start < 0:
        return []
    chunk = html[start : start + 8000]
    end = chunk.find("</div>", chunk.find("ep-listbox-options"))
    if end < 0:
        end = len(chunk)
    return re.findall(r'data-value="([^"]+)"[^>]*data-label="([^"]+)"', chunk[:end])


class PayrollMonthListboxTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db_path = self.tmp.name
        self._orig_path = db_mod.DATABASE_PATH
        db_mod.DATABASE_PATH = self.db_path
        db_mod.init_db()

        import app as app_mod
        import employee_payroll as payroll_mod

        self.app_mod = app_mod
        self.payroll_mod = payroll_mod
        self.app = app_mod.app
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

        conn = db_mod.get_db()
        try:
            admin = conn.execute(
                "SELECT id FROM users WHERE username = 'admin'"
            ).fetchone()
            self.admin_id = admin["id"]
        finally:
            conn.close()

        self.user = {
            "id": self.admin_id,
            "username": "admin",
            "full_name": "Administrator",
            "is_admin": True,
            "is_active": True,
            "dashboard_access": set(),
            "stores_access": set(),
        }
        self._patches = [
            mock.patch.object(app_mod, "get_current_user", return_value=self.user),
            mock.patch.object(payroll_mod, "get_current_user", return_value=self.user),
            mock.patch.object(
                payroll_mod, "_default_reporting_period", return_value=(2026, 8)
            ),
        ]
        for patcher in self._patches:
            patcher.start()

    def tearDown(self):
        for patcher in reversed(self._patches):
            patcher.stop()
        db_mod.DATABASE_PATH = self._orig_path
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def test_monthly_payroll_month_list_has_all_twelve_months(self):
        page = self.client.get("/monthly_payroll?year=2026&month=8")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        pairs = _listbox_values(html, "month-mpr-month-form-list")
        self.assertEqual([value for value, _label in pairs], [str(m) for m in range(1, 13)])
        self.assertEqual([label for _value, label in pairs], MONTH_LABELS)
        self.assertIn("Jan", html)
        self.assertIn("Jul", html)

    def test_monthly_payroll_year_list_includes_past_years(self):
        page = self.client.get("/monthly_payroll?year=2026&month=8")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        years = [value for value, _label in _listbox_values(html, "year-mpr-month-form-list")]
        self.assertIn("2026", years)
        self.assertIn("2025", years)
        self.assertIn("2021", years)

    def test_attendance_month_list_has_all_twelve_months(self):
        page = self.client.get("/attendance_overview?year=2026&month=8")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn('id="attendance-list-page"', html)
        pairs = _listbox_values(html, "month-attendance-overview-form-list")
        self.assertEqual([value for value, _label in pairs], [str(m) for m in range(1, 13)])
        self.assertEqual([label for _value, label in pairs], MONTH_LABELS)

    def test_shared_listbox_portals_and_scrolls_nearest(self):
        js = (ROOT / "static" / "ep_form_listbox.js").read_text(encoding="utf-8")
        self.assertIn("portalFixedListbox", js)
        self.assertIn("ep-listbox-portaled", js)
        self.assertIn("scrollIntoView", js)
        self.assertIn("block: 'nearest'", js)
        css = (ROOT / "static" / "ep_form_listbox.css").read_text(encoding="utf-8")
        self.assertIn(".se-filter-listbox.ep-listbox-portaled", css)
        self.assertIn("overflow-y:auto", css)
        self.assertIn("background:#fff", css)
        self.assertIn("isolation:isolate", css)
