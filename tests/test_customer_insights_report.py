"""Customer Insights report — per-mobile aggregation, page, export."""

import json
import os
import tempfile
import unittest
from unittest import mock

import db as db_mod


class CustomerInsightsReportTests(unittest.TestCase):
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
            db_mod.ensure_pos_schema(conn)
            cat = db_mod.save_pos_menu_category(
                conn, name="Mains", outlet=db_mod.POS_OUTLET_RESTAURANT
            )
            bar_cat = db_mod.save_pos_menu_category(
                conn, name="Spirits", outlet=db_mod.POS_OUTLET_BAR
            )
            self.butter = db_mod.save_pos_menu_item(
                conn,
                category_id=cat["id"],
                name="Chicken Butter Masala",
                rate=320,
                outlet=db_mod.POS_OUTLET_RESTAURANT,
            )
            self.whisky = db_mod.save_pos_menu_item(
                conn,
                category_id=bar_cat["id"],
                name="Whisky Peg",
                rate=250,
                outlet=db_mod.POS_OUTLET_BAR,
                item_kind="liquor",
                menu_type="liquor",
            )
            conn.commit()
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

    def _pos_invoice(
        self,
        *,
        outlet,
        order_no,
        menu_id,
        name,
        rate,
        qty,
        customer_name,
        customer_mobile,
    ):
        line_total = round(rate * qty, 2)
        payload = {
            "outlet": outlet,
            "orderNo": order_no,
            "savedAt": "2026-08-01 18:00:00",
            "orderType": "dine_in",
            "table": "T1" if outlet == "restaurant" else "B1",
            "captain": "",
            "customerName": customer_name,
            "customerMobile": customer_mobile,
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
                    "menuId": menu_id,
                    "name": name,
                    "variant": "",
                    "rate": rate,
                    "qty": qty,
                }
            ],
            "totals": {
                "subtotal": line_total,
                "discount": 0,
                "discountType": "pct",
                "discountValue": 0,
                "gst": 0,
                "service": 0,
                "serviceType": "pct",
                "serviceValue": 0,
                "tip": 0,
                "roundOff": 0,
                "total": line_total,
            },
        }
        conn = db_mod.get_db()
        try:
            inv = db_mod.save_pos_invoice(conn, payload)
            conn.commit()
            return inv
        finally:
            conn.close()

    def _hotel_invoice(self, *, invoice_number, guest_name, mobile, total, status="settled"):
        conn = db_mod.get_db()
        try:
            db_mod.ensure_hotel_room_invoices_schema(conn)
            payload = {
                "id": "r101",
                "number": "101",
                "stay": {
                    "guestName": guest_name,
                    "mobile": mobile,
                    "invoiceNumber": invoice_number,
                },
            }
            conn.execute(
                """
                INSERT INTO hotel_room_invoices (
                    invoice_number, room_id, room_number, room_type_label,
                    guest_name, booking_number, check_in_date, check_out_date,
                    invoice_generated_at, estimated_total, advance_paid,
                    balance_amount, status, payload_json
                ) VALUES (?, 'r101', '101', 'Deluxe', ?, '', '2026-08-01', '2026-08-02',
                          '2026-08-02 10:00:00', ?, 0, 0, ?, ?)
                """,
                (
                    invoice_number,
                    guest_name,
                    float(total),
                    status,
                    json.dumps(payload),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def test_list_customer_insights_merges_pos_and_hotel(self):
        self._pos_invoice(
            outlet="restaurant",
            order_no="ORD-CI-01",
            menu_id=self.butter["id"],
            name="Chicken Butter Masala",
            rate=320,
            qty=2,
            customer_name="Rajesh",
            customer_mobile="9876543210",
        )
        self._pos_invoice(
            outlet="bar",
            order_no="ORD-CI-02",
            menu_id=self.whisky["id"],
            name="Whisky Peg",
            rate=250,
            qty=1,
            customer_name="Rajesh",
            customer_mobile="9876543210",
        )
        self._hotel_invoice(
            invoice_number="HBE/RM/1/2026-27",
            guest_name="Rajesh Kumar",
            mobile="9876543210",
            total=4500,
        )

        conn = db_mod.get_db()
        try:
            rows = db_mod.list_customer_insights(
                conn,
                date_from="2026-08-01",
                date_to="2026-08-08",
                channel="all",
            )
            kpis = db_mod.customer_insights_kpis(rows)
        finally:
            conn.close()

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["mobile"], "9876543210")
        self.assertEqual(row["order_count"], 3)
        self.assertEqual(row["top_item"], "Chicken Butter Masala")
        self.assertEqual(row["restaurant_value"], 640.0)
        self.assertEqual(row["bar_value"], 250.0)
        self.assertEqual(row["hotel_value"], 4500.0)
        self.assertEqual(row["total_value"], 5390.0)
        self.assertEqual(kpis["customer_count"], 1)
        self.assertEqual(kpis["total_value_sum"], 5390.0)

    def test_named_customers_without_mobile_are_included(self):
        self._pos_invoice(
            outlet="restaurant",
            order_no="ORD-CI-NM-01",
            menu_id=self.butter["id"],
            name="Chicken Butter Masala",
            rate=320,
            qty=1,
            customer_name="Mr. Baborsekh",
            customer_mobile="",
        )
        self._pos_invoice(
            outlet="bar",
            order_no="ORD-CI-NM-02",
            menu_id=self.whisky["id"],
            name="Whisky Peg",
            rate=250,
            qty=2,
            customer_name="Mr. Baborsekh",
            customer_mobile="",
        )
        self._pos_invoice(
            outlet="restaurant",
            order_no="ORD-CI-NM-03",
            menu_id=self.butter["id"],
            name="Chicken Butter Masala",
            rate=320,
            qty=1,
            customer_name="Guest",
            customer_mobile="",
        )
        conn = db_mod.get_db()
        try:
            rows = db_mod.list_customer_insights(
                conn,
                date_from="2026-08-01",
                date_to="2026-08-08",
                channel="all",
            )
        finally:
            conn.close()
        by_name = {row["customer_name"]: row for row in rows}
        self.assertIn("Mr. Baborsekh", by_name)
        named = by_name["Mr. Baborsekh"]
        self.assertEqual(named["mobile"], "")
        self.assertEqual(named["order_count"], 2)
        self.assertEqual(named["restaurant_value"], 320.0)
        self.assertEqual(named["bar_value"], 500.0)
        self.assertEqual(named["top_item"], "Whisky Peg")
        self.assertIn("Guest", by_name)
        self.assertEqual(by_name["Guest"]["order_count"], 1)

    def test_channel_filter_hotel_only(self):
        self._pos_invoice(
            outlet="restaurant",
            order_no="ORD-CI-03",
            menu_id=self.butter["id"],
            name="Chicken Butter Masala",
            rate=320,
            qty=1,
            customer_name="Asha",
            customer_mobile="9123456780",
        )
        self._hotel_invoice(
            invoice_number="HBE/RM/2/2026-27",
            guest_name="Asha",
            mobile="9123456780",
            total=2000,
        )
        conn = db_mod.get_db()
        try:
            rows = db_mod.list_customer_insights(
                conn,
                date_from="2026-08-01",
                date_to="2026-08-08",
                channel="hotel",
            )
        finally:
            conn.close()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["hotel_value"], 2000.0)
        self.assertEqual(rows[0]["restaurant_value"], 0.0)
        self.assertEqual(rows[0]["top_item"], "")

    def test_page_and_export(self):
        from datetime import date, datetime

        today = date.today()
        # Invoice must fall in the default FY window used when hub opens with no dates.
        conn = db_mod.get_db()
        try:
            payload = {
                "outlet": "restaurant",
                "orderNo": "ORD-CI-04",
                "savedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "orderDate": today.isoformat(),
                "orderType": "dine_in",
                "table": "T1",
                "captain": "",
                "customerName": "Meera",
                "customerMobile": "9000011111",
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
                        "menuId": self.butter["id"],
                        "name": "Chicken Butter Masala",
                        "variant": "",
                        "rate": 320,
                        "qty": 1,
                    }
                ],
                "totals": {
                    "subtotal": 320,
                    "discount": 0,
                    "discountType": "pct",
                    "discountValue": 0,
                    "gst": 0,
                    "service": 0,
                    "serviceType": "pct",
                    "serviceValue": 0,
                    "tip": 0,
                    "roundOff": 0,
                    "total": 320,
                },
            }
            db_mod.save_pos_invoice(conn, payload)
            payload["orderNo"] = "ORD-CI-05"
            payload["customerName"] = "Mr. Baborsekh"
            payload["customerMobile"] = ""
            db_mod.save_pos_invoice(conn, payload)
            conn.commit()
        finally:
            conn.close()

        page = self.client.get("/reports/sales/customer-insights")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn("Customer Insights", html)
        self.assertIn("Unique customers", html)
        self.assertIn("Meera", html)
        self.assertIn("9000011111", html)
        self.assertIn("Mr. Baborsekh", html)
        fy_start_year = today.year if today.month >= 4 else today.year - 1
        self.assertIn(f'value="{date(fy_start_year, 4, 1).isoformat()}"', html)
        self.assertIn(f'value="{today.isoformat()}"', html)

        export = self.client.get("/reports/sales/customer-insights/export")
        self.assertEqual(export.status_code, 200)
        cd = export.headers.get("Content-Disposition") or ""
        fy_start, fy_today = db_mod.indian_fiscal_year_bounds()
        from reports import report_export_filename

        expected_name = report_export_filename(
            "Customer Insights",
            date_from=fy_start,
            date_to=fy_today,
            date_filter_active=True,
        )
        self.assertIn(expected_name, cd)

        from io import BytesIO
        from openpyxl import load_workbook

        wb = load_workbook(BytesIO(export.data))
        self.assertEqual(wb.sheetnames, ["Customer Insights"])
        ws = wb["Customer Insights"]
        self.assertEqual(ws["A1"].value, "Hotel Bell Elite — Customer Insights")


if __name__ == "__main__":
    unittest.main()
