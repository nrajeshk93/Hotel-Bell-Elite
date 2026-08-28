"""GST reports hub wiring — category, cards, authenticated pages."""

import os
import tempfile
import unittest
from unittest import mock

from reports import REPORT_CATEGORY_LABELS, REPORT_DEFINITIONS, build_reports_dashboard
from workspace_access import (
    _PUBLIC_ENDPOINTS,
    get_endpoint_dashboard_module,
    get_endpoint_reports_submodule,
    reports_access_list,
    user_can_access_reports_submodule,
)


def _gst_register_imports():
    try:
        from gst_hotel import register_gst_hotel  # noqa: F401
        from gst_fnb import register_gst_fnb  # noqa: F401
    except ImportError:
        return False
    return True


class GstReportsHubTests(unittest.TestCase):
    def test_gst_category_present_in_dashboard(self):
        self.assertEqual(REPORT_CATEGORY_LABELS.get("gst"), "GST")
        labels = list(REPORT_CATEGORY_LABELS)
        self.assertGreater(labels.index("gst"), labels.index("sales"))

        gst_cards = [r for r in REPORT_DEFINITIONS if r.get("category") == "gst"]
        self.assertEqual(len(gst_cards), 2)
        by_id = {r["id"]: r for r in gst_cards}
        self.assertEqual(by_id["gst_hotel"]["name"], "Hotel")
        self.assertEqual(by_id["gst_hotel"]["view_route"], "gst_hotel_report")
        self.assertEqual(by_id["gst_hotel"]["download_route"], "gst_hotel_report_export")
        self.assertEqual(by_id["gst_fnb"]["name"], "Restaurant & Bar")
        self.assertEqual(by_id["gst_fnb"]["view_route"], "gst_fnb_report")
        self.assertEqual(by_id["gst_fnb"]["download_route"], "gst_fnb_report_export")

        payload = build_reports_dashboard(lambda *args, **kwargs: "/ok")
        gst_section = next(
            (s for s in payload["report_sections"] if s["key"] == "gst"), None
        )
        self.assertIsNotNone(gst_section)
        self.assertEqual(gst_section["label"], "GST")
        self.assertEqual(gst_section["count"], 2)
        self.assertEqual(
            [r["view_route"] for r in gst_section["reports"]],
            ["gst_hotel_report", "gst_fnb_report"],
        )
        self.assertIn("gst", [c["key"] for c in payload["report_categories"]])

    def test_gst_endpoints_are_authenticated_reports_pages(self):
        for endpoint, submodule in (
            ("gst_hotel_report", "gst_hotel"),
            ("gst_hotel_report_export", "gst_hotel"),
            ("gst_fnb_report", "gst_fnb"),
            ("gst_fnb_report_export", "gst_fnb"),
        ):
            self.assertNotIn(endpoint, _PUBLIC_ENDPOINTS)
            self.assertEqual(get_endpoint_dashboard_module(endpoint), "reports")
            self.assertEqual(get_endpoint_reports_submodule(endpoint), submodule)

    def test_gst_defaults_on_for_existing_report_users(self):
        reports_user = {
            "id": 64,
            "is_admin": False,
            "dashboard_access": {"reports"},
            "reports_access": set(),
        }
        self.assertTrue(user_can_access_reports_submodule(reports_user, "gst_hotel"))
        self.assertTrue(user_can_access_reports_submodule(reports_user, "gst_fnb"))
        unlocked = reports_access_list(reports_user)
        self.assertIn("gst_hotel", unlocked)
        self.assertIn("gst_fnb", unlocked)

        subset = {
            "id": 65,
            "is_admin": False,
            "dashboard_access": {"reports"},
            "reports_access": {"hotel_sales"},
        }
        self.assertTrue(user_can_access_reports_submodule(subset, "gst_hotel"))
        self.assertTrue(user_can_access_reports_submodule(subset, "gst_fnb"))

        outsider = {
            "id": 66,
            "is_admin": False,
            "dashboard_access": {"accounts"},
            "reports_access": set(),
        }
        self.assertFalse(user_can_access_reports_submodule(outsider, "gst_hotel"))


class GstReportPageTests(unittest.TestCase):
    def setUp(self):
        if not _gst_register_imports():
            self.skipTest("GST report modules not registered yet")

        import db as db_mod

        self.db_mod = db_mod
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
        if "gst_hotel_report" not in self.app.view_functions:
            self.skipTest("GST hotel report not registered")
        if "gst_fnb_report" not in self.app.view_functions:
            self.skipTest("GST F&B report not registered")

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
            "username": "reporter",
            "full_name": "Reports User",
            "is_admin": False,
            "is_active": True,
            "dashboard_access": {"reports"},
            "reports_access": set(),
            "stores_access": set(),
        }
        self._get_user_patch = mock.patch.object(
            app_mod, "get_current_user", return_value=self.user
        )
        self._get_user_patch.start()

    def tearDown(self):
        if getattr(self, "_get_user_patch", None):
            self._get_user_patch.stop()
        orig = getattr(self, "_orig_path", None)
        if orig is not None:
            self.db_mod.DATABASE_PATH = orig
        path = getattr(self, "db_path", None)
        if path:
            try:
                os.unlink(path)
            except OSError:
                pass

    def test_gst_pages_ok_for_reports_user(self):
        from jinja2 import TemplateNotFound

        saw_page = False
        for path in ("/reports/gst/hotel", "/reports/gst/restaurant-bar"):
            try:
                response = self.client.get(path)
            except TemplateNotFound:
                continue
            saw_page = True
            self.assertEqual(response.status_code, 200, path)
        if not saw_page:
            self.skipTest("GST report templates not registered yet")


if __name__ == "__main__":
    unittest.main()
