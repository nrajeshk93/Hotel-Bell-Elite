"""Hotel / Restaurant / Bar Sales report pages — hub, pages, export, access."""

import os
import tempfile
import unittest
from unittest import mock

import db as db_mod
from reports import REPORT_DEFINITIONS, build_reports_dashboard
from workspace_access import get_endpoint_dashboard_module


class SalesReportsTests(unittest.TestCase):
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

    def _pos_payload(self, *, outlet="restaurant", order_no="ORD-SR-0001", total=500, **overrides):
        data = {
            "outlet": outlet,
            "orderNo": order_no,
            "savedAt": "2026-07-22 18:00:00",
            "orderType": "dine_in",
            "table": "T1",
            "captain": "",
            "customerName": "Sales Guest",
            "customerMobile": "9876543210",
            "notes": "",
            "discountType": "pct",
            "discountValue": 0,
            "serviceType": "pct",
            "serviceValue": 0,
            "tipAmount": 0,
            "couponCode": "",
            "lines": [
                {
                    "uid": "1",
                    "menuId": None,
                    "name": "Filter Coffee",
                    "variant": "Hot",
                    "rate": 100,
                    "qty": 2,
                },
                {
                    "uid": "2",
                    "menuId": None,
                    "name": "Masala Dosa",
                    "variant": "",
                    "rate": 150,
                    "qty": 2,
                },
            ],
            "totals": {
                "subtotal": 500,
                "discount": 0,
                "discountType": "pct",
                "discountValue": 0,
                "gst": 25,
                "service": 0,
                "serviceType": "pct",
                "serviceValue": 0,
                "tip": 0,
                "roundOff": 0,
                "total": total,
            },
        }
        data.update(overrides)
        return data

    def test_sales_definitions_and_hub_cards(self):
        sales = [r for r in REPORT_DEFINITIONS if r.get("category") == "sales"]
        self.assertEqual(
            [r["id"] for r in sales],
            ["hotel_sales", "restaurant_sales", "bar_sales", "menu_sales"],
        )
        self.assertEqual(sales[0]["view_route"], "sales_report_hotel")
        self.assertEqual(sales[1]["view_route"], "sales_report_restaurant")
        self.assertEqual(sales[2]["view_route"], "sales_report_bar")
        self.assertEqual(sales[3]["view_route"], "sales_report_menu")

        with self.app.test_request_context():
            from flask import url_for

            payload = build_reports_dashboard(url_for)
        sales_section = next(
            (s for s in payload["report_sections"] if s["key"] == "sales"), None
        )
        self.assertIsNotNone(sales_section)
        self.assertEqual(sales_section["count"], 4)
        names = [r["name"] for r in sales_section["reports"]]
        self.assertEqual(
            names, ["Hotel Sales", "Restaurant Sales", "Bar Sales", "Menu Sales"]
        )

        hub = self.client.get("/reports")
        self.assertEqual(hub.status_code, 200)
        html = hub.get_data(as_text=True)
        self.assertIn("Hotel Sales", html)
        self.assertIn("Restaurant Sales", html)
        self.assertIn("Bar Sales", html)
        self.assertIn("Menu Sales", html)
        self.assertIn('data-report-category="sales"', html)
        self.assertIn("/reports/sales/hotel", html)
        self.assertIn("/reports/sales/restaurant", html)
        self.assertIn("/reports/sales/bar", html)
        self.assertIn("/reports/sales/menu", html)

    def test_sales_report_pages_and_export(self):
        # Seed one restaurant + one bar invoice so POS pages have rows.
        rest_save = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._pos_payload(outlet="restaurant", order_no="ORD-SR-REST"),
        )
        self.assertEqual(rest_save.status_code, 200, rest_save.get_data(as_text=True))
        bar_save = self.client.post(
            "/bar-point-of-sale/api/invoices",
            json=self._pos_payload(outlet="bar", order_no="", table="B1"),
        )
        self.assertEqual(bar_save.status_code, 200, bar_save.get_data(as_text=True))
        self.assertTrue((bar_save.get_json() or {}).get("ok"))

        cases = (
            (
                "/reports/sales/hotel",
                "/reports/sales/hotel/export",
                "Hotel Sales",
                "Invoice No",
                "hotel_sales",
            ),
            (
                "/reports/sales/restaurant",
                "/reports/sales/restaurant/export",
                "Restaurant Sales",
                "Order No",
                "restaurant_sales",
            ),
            (
                "/reports/sales/bar",
                "/reports/sales/bar/export",
                "Bar Sales",
                "Order No",
                "bar_sales",
            ),
        )
        for page_url, export_url, title, col_marker, export_prefix in cases:
            page = self.client.get(f"{page_url}?from_hub=reports")
            self.assertEqual(page.status_code, 200, page_url)
            html = page.get_data(as_text=True)
            self.assertIn(title, html)
            self.assertIn('id="sales-report-page"', html)
            self.assertIn("Export Excel", html)
            self.assertIn('aria-label="Back to Reports"', html)
            self.assertTrue(
                'id="sr-table"' in html or "No invoices match these filters." in html,
                f"expected table or empty state on {page_url}",
            )
            if 'id="sr-table"' in html:
                self.assertIn(col_marker, html)

            export = self.client.get(export_url)
            self.assertEqual(export.status_code, 200, export_url)
            self.assertIn(
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                export.content_type or "",
            )
            self.assertTrue(export.data[:2] == b"PK")
            cd = export.headers.get("Content-Disposition") or ""
            self.assertIn(export_prefix, cd)

        rest_page = self.client.get("/reports/sales/restaurant")
        rest_html = rest_page.get_data(as_text=True)
        self.assertIn('id="sr-table"', rest_html)
        self.assertIn("Order No", rest_html)
        self.assertIn("ORD-SR-REST", rest_html)
        self.assertIn("Sales Guest", rest_html)

        bar_page = self.client.get("/reports/sales/bar")
        bar_html = bar_page.get_data(as_text=True)
        self.assertIn('id="sr-table"', bar_html)
        self.assertIn("Order No", bar_html)
        self.assertIn("Sales Guest", bar_html)

    def test_sales_report_endpoints_map_to_reports_module(self):
        for endpoint in (
            "sales_report_hotel",
            "sales_report_hotel_export",
            "sales_report_restaurant",
            "sales_report_restaurant_export",
            "sales_report_bar",
            "sales_report_bar_export",
            "sales_report_menu",
            "sales_report_menu_export",
        ):
            self.assertEqual(get_endpoint_dashboard_module(endpoint), "reports")

    def test_sales_report_access_gate(self):
        viewer = {
            "id": self.admin_id,
            "username": "noreports",
            "full_name": "No Reports",
            "is_admin": False,
            "is_active": True,
            "dashboard_access": {"hotel_rooms", "point_of_sale"},
            "stores_access": set(),
            "sales_analytics_access": set(),
            "user_access": set(),
            "payroll_access": set(),
            "accounts_access": set(),
        }
        with mock.patch.object(self.app_mod, "get_current_user", return_value=viewer):
            for path in (
                "/reports",
                "/reports/sales/hotel",
                "/reports/sales/restaurant",
                "/reports/sales/bar",
                "/reports/sales/menu",
                "/reports/sales/hotel/export",
                "/reports/sales/menu/export",
            ):
                denied = self.client.get(path)
                self.assertIn(denied.status_code, (302, 403), path)
                if denied.status_code == 302:
                    self.assertNotIn(b'id="sales-report-page"', denied.data)
                    self.assertNotIn(b'id="menu-sales-report-page"', denied.data)


if __name__ == "__main__":
    unittest.main()
