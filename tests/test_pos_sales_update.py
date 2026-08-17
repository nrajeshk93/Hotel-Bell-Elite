"""Restaurant Sales Update from POS invoices."""

import json
import os
import tempfile
import unittest
from datetime import date
from unittest import mock

import db as db_mod


class PosSalesUpdateTests(unittest.TestCase):
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
            "username": "staff",
            "full_name": "POS Staff",
            "is_admin": False,
            "is_active": True,
            "dashboard_access": {"point_of_sale"},
            "sales_analytics_access": set(),
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

    def _insert_pos(self, conn, *, outlet, order_date, grand_total, payments):
        cur = conn.execute(
            """
            INSERT INTO pos_invoices
               (order_no, order_date, order_type, table_label, customer_name, customer_mobile,
                captain, status, outlet, subtotal, discount_amount, gst_amount, service_amount,
                tip, round_off, grand_total, saved_at, is_active)
            VALUES (?, ?, 'dine_in', 'T1', 'Guest', '', '', 'closed', ?, ?, 0, 0, 0, 0, 0, ?,
                    datetime('now'), 1)
            """,
            ("SPC/SU/1", order_date, outlet, float(grand_total), float(grand_total)),
        )
        invoice_id = cur.lastrowid
        for pay in payments:
            conn.execute(
                """
                INSERT INTO pos_invoice_payments
                    (invoice_id, payment_date, payment_method, amount, transaction_id)
                VALUES (?, ?, ?, ?, '')
                """,
                (invoice_id, order_date, pay["method"], float(pay["amount"])),
            )

    def test_analytics_bundle_keeps_saved_excel_import(self):
        conn = db_mod.get_db()
        try:
            db_mod.ensure_pos_schema(conn)
            self._insert_pos(
                conn,
                outlet=db_mod.POS_OUTLET_RESTAURANT,
                order_date="2026-08-12",
                grand_total=800.0,
                payments=[
                    {"method": "cash", "amount": 300.0},
                    {"method": "upi", "amount": 500.0},
                ],
            )
            conn.execute(
                """
                INSERT INTO sales_updates (
                    company, location, sales_date, sales_entry_values, created_at, updated_at
                ) VALUES (?, ?, ?, ?, datetime('now'), datetime('now'))
                """,
                (
                    self.app_mod.DEFAULT_COMPANY,
                    "Restaurant",
                    "2026-08-12",
                    json.dumps({
                        "total_sales": 10.0,
                        "cash": 10.0,
                        "card": 0.0,
                        "upi": 0.0,
                        "room_credit": 0.0,
                        "online_order": 0.0,
                        "actual_cash": 55.0,
                    }),
                ),
            )
            conn.commit()
            bundle = self.app_mod._load_outlet_entry_bundle(
                conn,
                self.user,
                self.app_mod.DEFAULT_COMPANY,
                "Restaurant",
                "2026-08-12",
                "2026-08-13",
            )
            overlay = self.app_mod._load_outlet_entry_bundle(
                conn,
                self.user,
                self.app_mod.DEFAULT_COMPANY,
                "Restaurant",
                "2026-08-12",
                "2026-08-13",
                overlay_invoices=True,
            )
        finally:
            conn.close()
        self.assertEqual(bundle["sales_entry_values"]["total_sales"], 10.0)
        self.assertEqual(bundle["sales_entry_values"]["cash"], 10.0)
        self.assertEqual(bundle["sales_entry_values"]["actual_cash"], 55.0)
        self.assertEqual(overlay["sales_entry_values"]["total_sales"], 800.0)
        self.assertEqual(overlay["sales_entry_values"]["cash"], 300.0)
        self.assertEqual(overlay["sales_entry_values"]["upi"], 500.0)
        self.assertEqual(overlay["sales_entry_values"]["actual_cash"], 55.0)

    def test_pos_save_does_not_overwrite_excel_import_keys(self):
        conn = db_mod.get_db()
        try:
            conn.execute(
                """
                INSERT INTO sales_updates (
                    company, location, sales_date, sales_entry_values, created_at, updated_at
                ) VALUES (?, ?, ?, ?, datetime('now'), datetime('now'))
                """,
                (
                    self.app_mod.DEFAULT_COMPANY,
                    "Restaurant",
                    "2026-08-12",
                    json.dumps({
                        "total_sales": 10.0,
                        "cash": 10.0,
                        "card": 0.0,
                        "upi": 0.0,
                        "room_credit": 0.0,
                        "online_order": 0.0,
                        "actual_cash": 55.0,
                    }),
                ),
            )
            conn.commit()
        finally:
            conn.close()
        resp = self.client.post(
            "/sales_update/save",
            json={
                "company": self.app_mod.DEFAULT_COMPANY,
                "location": "Restaurant",
                "date": "2026-08-12",
                "preserve_import": True,
                "sales_entries": {
                    "total_sales": 800.0,
                    "cash": 300.0,
                    "card": 0.0,
                    "upi": 500.0,
                    "room_credit": 0.0,
                    "online_order": 0.0,
                    "actual_cash": 77.0,
                },
                "petty_cash_counts": {},
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json().get("ok"))
        saved = self.app_mod.load_sales_row(
            self.app_mod.DEFAULT_COMPANY, "Restaurant", "2026-08-12"
        )
        self.assertEqual(saved["sales_entry_values"]["total_sales"], 10.0)
        self.assertEqual(saved["sales_entry_values"]["cash"], 10.0)
        self.assertEqual(saved["sales_entry_values"]["actual_cash"], 77.0)

    def test_restaurant_difference_kpi_is_cash_minus_actual_cash(self):
        conn = db_mod.get_db()
        try:
            db_mod.ensure_pos_schema(conn)
            self._insert_pos(
                conn,
                outlet=db_mod.POS_OUTLET_RESTAURANT,
                order_date="2026-08-14",
                grand_total=315.0,
                payments=[{"method": "cash", "amount": 315.0}],
            )
            conn.execute(
                """
                INSERT INTO sales_updates (
                    company, location, sales_date, sales_entry_values, created_at, updated_at
                ) VALUES (?, ?, ?, ?, datetime('now'), datetime('now'))
                """,
                (
                    self.app_mod.DEFAULT_COMPANY,
                    "Restaurant",
                    "2026-08-14",
                    json.dumps({
                        "total_sales": 315.0,
                        "cash": 315.0,
                        "actual_cash": 0.0,
                    }),
                ),
            )
            conn.commit()
            kpi = self.app_mod._outlet_sales_update_kpi_bundle(
                conn,
                self.app_mod.DEFAULT_COMPANY,
                "Restaurant",
                date(2026, 8, 14),
                date(2026, 8, 14),
                user=self.user,
                overlay_invoices=True,
            )
        finally:
            conn.close()
        self.assertEqual(kpi["current"]["actual_sales"], 315.0)
        self.assertEqual(kpi["current"]["cash"], 315.0)
        self.assertEqual(kpi["current"]["difference"], 315.0)

    def test_bar_keeps_saved_collections_import(self):
        conn = db_mod.get_db()
        try:
            db_mod.ensure_pos_schema(conn)
            self._insert_pos(
                conn,
                outlet=db_mod.POS_OUTLET_BAR,
                order_date="2026-08-12",
                grand_total=900.0,
                payments=[{"method": "cash", "amount": 900.0}],
            )
            conn.execute(
                """
                INSERT INTO sales_updates (
                    company, location, sales_date, sales_entry_values, created_at, updated_at
                ) VALUES (?, ?, ?, ?, datetime('now'), datetime('now'))
                """,
                (
                    self.app_mod.DEFAULT_COMPANY,
                    "Bar",
                    "2026-08-12",
                    json.dumps({
                        "total_sales": 111.0,
                        "cash": 111.0,
                        "card": 0.0,
                        "upi": 0.0,
                        "room_credit": 0.0,
                        "online_order": 0.0,
                    }),
                ),
            )
            conn.commit()
            bundle = self.app_mod._load_outlet_entry_bundle(
                conn,
                self.user,
                self.app_mod.DEFAULT_COMPANY,
                "Bar",
                "2026-08-12",
                "2026-08-13",
            )
            overlay = self.app_mod._load_outlet_entry_bundle(
                conn,
                self.user,
                self.app_mod.DEFAULT_COMPANY,
                "Bar",
                "2026-08-12",
                "2026-08-13",
                overlay_invoices=True,
            )
        finally:
            conn.close()
        self.assertEqual(bundle["sales_entry_values"]["total_sales"], 111.0)
        self.assertEqual(bundle["sales_entry_values"]["cash"], 111.0)
        self.assertEqual(overlay["sales_entry_values"]["total_sales"], 900.0)
        self.assertEqual(overlay["sales_entry_values"]["cash"], 900.0)

    def test_bar_pos_route_overlays_invoices_and_highlights_bar_nav(self):
        self.user["dashboard_access"] = {"point_of_sale_bar"}
        page = self.client.get("/bar-point-of-sale/sales-update")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn('id="de-nav-bar-pos-group"', html)
        self.assertRegex(html, r'de-nav-subitem is-active"[^>]*id="de-nav-bar-pos-sales-update"')
        self.assertIn("Sales Update - Bar", html)
        self.assertIn("from bar invoices", html.lower())
        self.assertNotIn("Upload Collections Report", html)
        self.assertIn('data-preserve-import="1"', html)
        self.assertNotRegex(
            html,
            r'class="de-nav-group is-open[^"]*" id="de-nav-sales-analytics-group"',
        )

    def test_hotel_analytics_prefers_fo_ledger_module_overlays_invoices(self):
        conn = db_mod.get_db()
        try:
            db_mod.ensure_hotel_room_invoices_schema(conn)
            conn.execute(
                """
                INSERT INTO hotel_room_invoices (
                    invoice_number, room_id, room_number, room_type_label,
                    guest_name, booking_number, check_in_date, check_out_date,
                    invoice_generated_at, estimated_total, advance_paid,
                    balance_amount, status, payload_json
                ) VALUES (?, 'r101', '101', 'Deluxe', 'Guest', '',
                          '2026-08-12', '2026-08-13', ?, ?, 0, 0, 'settled', ?)
                """,
                (
                    "HBE/RM/SU/1",
                    "2026-08-12 10:00:00",
                    800.0,
                    json.dumps({
                        "id": "r101",
                        "number": "101",
                        "stay": {
                            "payments": [{"method": "upi", "amount": 800.0}],
                        },
                    }),
                ),
            )
            self.app_mod.replace_hotel_ledger_entries(
                conn,
                self.app_mod.DEFAULT_COMPANY,
                self.app_mod.OUTLET_HOTEL,
                "2026-08-12",
                [{
                    "invoice_number": "FO-1",
                    "amount": 50.0,
                    "payment_mode": "cash",
                    "sort_order": 1,
                    "source_row": 1,
                }],
            )
            conn.commit()
            analytics = self.app_mod._load_outlet_entry_bundle(
                conn,
                self.user,
                self.app_mod.DEFAULT_COMPANY,
                self.app_mod.OUTLET_HOTEL,
                "2026-08-12",
                "2026-08-13",
                overlay_invoices=False,
            )
            module = self.app_mod._load_outlet_entry_bundle(
                conn,
                self.user,
                self.app_mod.DEFAULT_COMPANY,
                self.app_mod.OUTLET_HOTEL,
                "2026-08-12",
                "2026-08-13",
                overlay_invoices=True,
            )
        finally:
            conn.close()
        self.assertEqual(analytics["sales_entry_values"]["total_sales"], 50.0)
        self.assertEqual(analytics["sales_entry_values"]["cash"], 50.0)
        self.assertEqual(module["sales_entry_values"]["total_sales"], 800.0)
        self.assertEqual(module["sales_entry_values"]["upi"], 800.0)

    def test_hotel_credit_settlement_updates_guest_credit(self):
        conn = db_mod.get_db()
        try:
            db_mod.ensure_hotel_room_invoices_schema(conn)
            conn.execute(
                """
                INSERT INTO hotel_room_invoices (
                    invoice_number, room_id, room_number, room_type_label,
                    guest_name, booking_number, check_in_date, check_out_date,
                    invoice_generated_at, estimated_total, advance_paid,
                    balance_amount, status, payload_json
                ) VALUES (?, 'r201', '201', 'Deluxe', 'Guest', '',
                          '2026-08-12', '2026-08-13', ?, 158.0, 158.0, 0, 'settled', ?)
                """,
                (
                    "HBE/RM/SU/CREDIT",
                    "2026-08-12 11:00:00",
                    json.dumps({
                        "id": "r201",
                        "number": "201",
                        "stay": {
                            "agencyName": "ATPI India Pvt. Ltd",
                            "payments": [{"method": "credit", "amount": 158.0}],
                        },
                    }),
                ),
            )
            self.app_mod.replace_hotel_ledger_entries(
                conn,
                self.app_mod.DEFAULT_COMPANY,
                self.app_mod.OUTLET_HOTEL,
                "2026-08-12",
                [{
                    "invoice_number": "FO-CASH",
                    "amount": 50.0,
                    "payment_mode": "cash",
                    "sort_order": 1,
                    "source_row": 1,
                }],
            )
            conn.commit()
            analytics = self.app_mod._load_outlet_entry_bundle(
                conn,
                self.user,
                self.app_mod.DEFAULT_COMPANY,
                self.app_mod.OUTLET_HOTEL,
                "2026-08-12",
                "2026-08-13",
                overlay_invoices=False,
            )
            module = self.app_mod._load_outlet_entry_bundle(
                conn,
                self.user,
                self.app_mod.DEFAULT_COMPANY,
                self.app_mod.OUTLET_HOTEL,
                "2026-08-12",
                "2026-08-13",
                overlay_invoices=True,
            )
        finally:
            conn.close()
        self.assertEqual(analytics["sales_entry_values"]["cash"], 50.0)
        self.assertEqual(analytics["sales_entry_values"]["room_credit"], 158.0)
        self.assertEqual(module["sales_entry_values"]["total_sales"], 158.0)
        self.assertEqual(module["sales_entry_values"]["room_credit"], 158.0)

    def test_hotel_module_route_hides_fo_upload_and_highlights_hotel_nav(self):
        self.user["dashboard_access"] = {"hotel_rooms"}
        page = self.client.get("/hotel/sales-update")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn('id="de-nav-hotel-group"', html)
        self.assertRegex(html, r'de-nav-subitem is-active"[^>]*id="de-nav-hotel-sales-update"')
        self.assertIn("from hotel room invoices", html.lower())
        self.assertNotIn("Upload FO Invoice Tax Report", html)
        self.assertNotIn('id="se-upload-hotel"', html)
        self.assertNotRegex(
            html,
            r'class="de-nav-group is-open[^"]*" id="de-nav-sales-analytics-group"',
        )

    def test_pos_route_allowed_and_highlights_restaurant_nav(self):
        page = self.client.get("/point-of-sale/sales-update")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn('id="de-nav-pos-group"', html)
        self.assertIn("is-open is-child-active", html)
        self.assertIn('id="de-nav-pos-sales-update"', html)
        self.assertRegex(html, r'de-nav-subitem is-active"[^>]*id="de-nav-pos-sales-update"')
        self.assertIn("hbe-kpi-card", html)
        self.assertIn("vs yesterday", html)
        self.assertIn("From restaurant invoices", html)
        self.assertNotIn("Upload Collections Report", html)
        self.assertIn('data-preserve-import="1"', html)

    def test_pos_sales_update_does_not_activate_analytics_restaurant(self):
        self.user["dashboard_access"] = {"point_of_sale", "sales_analytics"}
        self.user["sales_analytics_access"] = {"restaurant"}
        page = self.client.get("/point-of-sale/sales-update")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertRegex(
            html,
            r'class="de-nav-group is-open is-child-active" id="de-nav-pos-group"',
        )
        self.assertRegex(html, r'de-nav-subitem is-active"[^>]*id="de-nav-pos-sales-update"')
        self.assertIn("Sales Update - Restaurant", html)
        self.assertNotRegex(
            html,
            r'class="de-nav-group is-open[^"]*" id="de-nav-sales-analytics-group"',
        )
        self.assertNotRegex(
            html,
            r'class="de-nav-subitem is-active"[^>]*>\s*Sales Update - Restaurant',
        )

    def test_analytics_restaurant_shows_collections_upload(self):
        self.user["sales_analytics_access"] = {"restaurant"}
        page = self.client.get("/sales_update/restaurant")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn("Upload Collections Report", html)
        self.assertNotIn("From restaurant invoices", html)
        self.assertIn('data-preserve-import="0"', html)

    def test_pos_user_cannot_open_analytics_restaurant_page(self):
        page = self.client.get("/sales_update/restaurant")
        self.assertEqual(page.status_code, 302)

    def test_user_without_pos_cannot_open_pos_sales_update(self):
        self.user["dashboard_access"] = set()
        page = self.client.get("/point-of-sale/sales-update")
        self.assertEqual(page.status_code, 302)


if __name__ == "__main__":
    unittest.main()
