"""Tests for Collections report upload date handling."""

import io
import os
import tempfile
import unittest
from datetime import date
from unittest import mock

import openpyxl

import db as db_mod


def _collections_bytes(rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Report - Collections"
    ws.append([
        "Date", "Invoice #", "Outlet", "Ref. #", "Table/Room", "Guest",
        "Ledger", "Amount", "Discount", "Tips", "Username",
    ])
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


class SalesUploadReportTests(unittest.TestCase):
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
            self.user = {
                "id": admin["id"],
                "username": "admin",
                "full_name": "Administrator",
                "is_admin": True,
                "is_active": True,
                "dashboard_access": set(),
                "stores_access": set(),
            }
        finally:
            conn.close()

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

    def test_pick_report_fallback_date_closest(self):
        pick = self.app_mod._pick_report_fallback_date
        # Equal distance: prefer the later report date.
        self.assertEqual(
            pick(["2026-08-06", "2026-08-10"], date(2026, 8, 8)),
            date(2026, 8, 10),
        )
        self.assertEqual(
            pick(["2026-08-06"], date(2026, 8, 8)),
            date(2026, 8, 6),
        )
        self.assertEqual(
            pick(["2026-08-01", "2026-08-06"], date(2026, 8, 8)),
            date(2026, 8, 6),
        )
        self.assertIsNone(pick([], date(2026, 8, 8)))

    def test_upload_uses_report_date_when_page_date_empty(self):
        buf = _collections_bytes([
            ["06-Aug-2026", "SPC/1/2026-27", "Dining", "", "", "A", "ZOMATO", 268, 0, 0, "RESTAURANT"],
            ["06-Aug-2026", "INV/1/2026-27", "Bar", "", "", "B", "Cash", 100, 0, 0, "BAR"],
        ])
        resp = self.client.post(
            "/sales_update/upload_report",
            data={
                "date": "2026-08-08",
                "location": "Restaurant",
                "report_file": (buf, "report-collections.xlsx"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["ok"])
        self.assertTrue(data["date_adjusted"])
        self.assertEqual(data["date"], "2026-08-06")
        self.assertEqual(data["requested_date"], "2026-08-08")
        self.assertEqual(data["restaurant"]["online_order"], 268.0)
        self.assertEqual(data["bar"]["cash"], 100.0)


if __name__ == "__main__":
    unittest.main()
