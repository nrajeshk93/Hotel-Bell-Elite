"""7-day Sales Update edit window (first save / Super Administrator override)."""

import os
import tempfile
import unittest
from datetime import date, datetime, timedelta
from unittest import mock

import db as db_mod

import app as app_module


class SalesEntryLockHelpersTests(unittest.TestCase):
    def test_parse_created_at_timestamp(self):
        self.assertEqual(
            app_module._parse_sales_row_created_date("2026-08-01 14:30:00"),
            date(2026, 8, 1),
        )

    def test_parse_created_at_date_only(self):
        self.assertEqual(
            app_module._parse_sales_row_created_date("2026-08-01"),
            date(2026, 8, 1),
        )

    def test_no_row_is_not_locked(self):
        self.assertFalse(
            app_module._sales_entry_locked_for_user({"is_admin": False}, None)
        )

    def test_within_window_not_locked(self):
        created = (date.today() - timedelta(days=6)).strftime("%Y-%m-%d %H:%M:%S")
        row = {"created_at": created}
        self.assertFalse(
            app_module._sales_entry_locked_for_user({"is_admin": False}, row)
        )

    def test_seven_days_locks_non_admin(self):
        created = (date.today() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
        row = {"created_at": created}
        self.assertTrue(
            app_module._sales_entry_locked_for_user({"is_admin": False}, row)
        )

    def test_seven_days_allows_super_admin(self):
        created = (date.today() - timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S")
        row = {"created_at": created}
        self.assertFalse(
            app_module._sales_entry_locked_for_user({"is_admin": True}, row)
        )


class SalesDateLockCheckTests(unittest.TestCase):
    def test_future_date_blocked(self):
        future = (date.today() + timedelta(days=1)).isoformat()
        err = app_module._check_sales_date_lock(
            {"is_admin": True}, "HBE", "Bar", future
        )
        self.assertEqual(err, "Cannot save future dates.")

    def test_missing_row_allows_non_admin(self):
        with mock.patch.object(app_module, "load_sales_row", return_value=None):
            err = app_module._check_sales_date_lock(
                {"is_admin": False}, "HBE", "Bar", date.today().isoformat()
            )
        self.assertIsNone(err)

    def test_old_row_blocks_non_admin(self):
        created = (date.today() - timedelta(days=8)).strftime("%Y-%m-%d %H:%M:%S")
        with mock.patch.object(
            app_module,
            "load_sales_row",
            return_value={"created_at": created},
        ):
            err = app_module._check_sales_date_lock(
                {"is_admin": False}, "HBE", "Bar", date.today().isoformat()
            )
        self.assertEqual(err, app_module.SALES_ENTRY_LOCK_MESSAGE)

    def test_old_row_allows_super_admin(self):
        created = (date.today() - timedelta(days=8)).strftime("%Y-%m-%d %H:%M:%S")
        with mock.patch.object(
            app_module,
            "load_sales_row",
            return_value={"created_at": created},
        ):
            err = app_module._check_sales_date_lock(
                {"is_admin": True}, "HBE", "Bar", date.today().isoformat()
            )
        self.assertIsNone(err)


class SalesEntryLockPageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db_path = self.tmp.name
        self._orig_path = db_mod.DATABASE_PATH
        db_mod.DATABASE_PATH = self.db_path
        db_mod.init_db()

        self.app = app_module.app
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

        self.non_admin = {
            "id": 99,
            "username": "clerk",
            "is_admin": False,
            "is_active": True,
            "dashboard_access": {"sales_analytics"},
            "sales_analytics_access": {"bar"},
            "must_change_password": False,
        }
        self.super_admin = {
            "id": 1,
            "username": "admin",
            "is_admin": True,
            "is_active": True,
            "dashboard_access": set(),
            "must_change_password": False,
        }

        sales_date = date.today().isoformat()
        created = (datetime.now() - timedelta(days=9)).strftime("%Y-%m-%d %H:%M:%S")
        conn = db_mod.get_db()
        try:
            conn.execute(
                """INSERT INTO sales_updates
                   (company, location, sales_date, sales_entry_values, sales_entry_total,
                    petty_cash_counts, petty_cash_total, cash_denomination_counts,
                    created_by_user_id, updated_by_user_id, created_at, updated_at)
                   VALUES (?, ?, ?, '{}', 0, '{}', 0, '{}', 1, 1, ?, ?)""",
                ("HBE", "Bar", sales_date, created, created),
            )
            conn.commit()
        finally:
            conn.close()
        self.sales_date = sales_date

    def tearDown(self):
        db_mod.DATABASE_PATH = self._orig_path
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def test_banner_shown_for_non_admin(self):
        with mock.patch.object(
            app_module, "get_current_user", return_value=self.non_admin
        ):
            resp = self.client.get(f"/sales_update/bar?date={self.sales_date}")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"se-lock-banner", resp.data)
        self.assertIn(b"Only a Super Administrator can change it", resp.data)

    def test_banner_hidden_for_super_admin(self):
        with mock.patch.object(
            app_module, "get_current_user", return_value=self.super_admin
        ):
            resp = self.client.get(f"/sales_update/bar?date={self.sales_date}")
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn(b"se-lock-banner", resp.data)
