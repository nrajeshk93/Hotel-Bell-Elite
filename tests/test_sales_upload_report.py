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

    def test_upload_stays_on_bar_page_when_pos_invoices_are_empty(self):
        buf = _collections_bytes([
            ["12-Aug-2026", "INV/1746/2026-27", "IRISH LOUNGE BAR", "", "1", "", "Cash", "1568.00", "0.00", "0.00", "BAR"],
            ["12-Aug-2026", "INV/1749/2026-27", "IRISH LOUNGE BAR", "", "1", "", "Cash", "1851.00", "0.00", "0.00", "BAR"],
            ["12-Aug-2026", "INV/1751/2026-27", "IRISH LOUNGE BAR", "", "6", "", "UPI", "5846.00", "0.00", "0.00", "BAR"],
            ["12-Aug-2026", "SPC/2048/2026-27", "SPICE MUTLICUSINE", "", "2", "swiggy", "SWIGGY", "1301.00", "0.00", "0.00", "RESTAURANT"],
        ])
        resp = self.client.post(
            "/sales_update/upload_report",
            data={
                "date": "2026-08-13",
                "location": "Bar",
                "report_file": (buf, "report-collections (2).xlsx"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["date"], "2026-08-12")
        self.assertEqual(data["bar"]["cash"], 3419.0)
        self.assertEqual(data["bar"]["upi"], 5846.0)
        self.assertEqual(data["restaurant"]["online_order"], 1301.0)

        page = self.client.get("/sales_update/bar?date=2026-08-12")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn('value="3419', html)
        self.assertIn("₹9,265", html)
        self.assertIn("₹5,846", html)
        self.assertIn("All values are from the sales entry (12 Aug 2026).", html)
        self.assertNotIn("All values are from invoices (12 Aug 2026)", html)

        conn = db_mod.get_db()
        try:
            bundle = self.app_mod._load_outlet_entry_bundle(
                conn,
                self.user,
                self.app_mod.DEFAULT_COMPANY,
                "Bar",
                "2026-08-12",
                "2026-08-13",
            )
            kpi = self.app_mod._outlet_sales_update_kpi_bundle(
                conn,
                self.app_mod.DEFAULT_COMPANY,
                "Bar",
                date(2026, 8, 12),
                date(2026, 8, 12),
            )
        finally:
            conn.close()
        self.assertEqual(bundle["sales_entry_values"]["cash"], 3419.0)
        self.assertEqual(bundle["sales_entry_values"]["total_sales"], 9265.0)
        self.assertEqual(kpi["current"]["actual_sales"], 9265.0)
        self.assertEqual(kpi["current"]["cash"], 3419.0)
        self.assertEqual(kpi["current"]["digital_transactions"], 5846.0)
        self.assertIn("sales entry", kpi["note"])

    def test_empty_bar_entry_fills_from_pos_invoices(self):
        conn = db_mod.get_db()
        try:
            db_mod.ensure_pos_schema(conn)
            cur = conn.execute(
                """
                INSERT INTO pos_invoices
                   (order_no, order_date, order_type, table_label, customer_name, customer_mobile,
                    captain, status, outlet, subtotal, discount_amount, gst_amount, service_amount,
                    tip, round_off, grand_total, saved_at, is_active)
                VALUES ('INV/POS/1', '2026-08-12', 'dine_in', 'T1', 'Guest', '', '',
                        'closed', ?, 500, 0, 0, 0, 0, 0, 500, datetime('now'), 1)
                """,
                (db_mod.POS_OUTLET_BAR,),
            )
            conn.execute(
                """
                INSERT INTO pos_invoice_payments
                    (invoice_id, payment_date, payment_method, amount, transaction_id)
                VALUES (?, '2026-08-12', 'cash', 500, '')
                """,
                (cur.lastrowid,),
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
            kpi = self.app_mod._outlet_sales_update_kpi_bundle(
                conn,
                self.app_mod.DEFAULT_COMPANY,
                "Bar",
                date(2026, 8, 12),
                date(2026, 8, 12),
            )
        finally:
            conn.close()
        self.assertEqual(bundle["sales_entry_values"]["cash"], 500.0)
        self.assertEqual(bundle["sales_entry_values"]["total_sales"], 500.0)
        self.assertEqual(kpi["current"]["actual_sales"], 500.0)
        self.assertEqual(kpi["current"]["cash"], 500.0)
        self.assertIn("sales entry", kpi["note"])

        page = self.client.get("/sales_update/bar?date=2026-08-12")
        self.assertEqual(page.status_code, 200)
        self.assertIn("₹500", page.get_data(as_text=True))

    def test_hotel_kpis_use_fo_ledger_not_invoices(self):
        conn = db_mod.get_db()
        try:
            self.app_mod.replace_hotel_ledger_entries(
                conn,
                self.app_mod.DEFAULT_COMPANY,
                "Hotel",
                "2026-08-12",
                [
                    {
                        "invoice_number": "HBE/1",
                        "room": "101",
                        "amount": 4500,
                        "payment_mode": "cash",
                        "sort_order": 1,
                    },
                    {
                        "invoice_number": "HBE/2",
                        "room": "102",
                        "amount": 2200,
                        "payment_mode": "upi",
                        "sort_order": 2,
                    },
                ],
            )
            conn.commit()
            kpi = self.app_mod._outlet_sales_update_kpi_bundle(
                conn,
                self.app_mod.DEFAULT_COMPANY,
                "Hotel",
                date(2026, 8, 12),
                date(2026, 8, 12),
                user=self.user,
            )
        finally:
            conn.close()
        self.assertEqual(kpi["current"]["actual_sales"], 6700.0)
        self.assertEqual(kpi["current"]["cash"], 4500.0)
        self.assertEqual(kpi["current"]["digital_transactions"], 2200.0)
        self.assertIn("sales entry", kpi["note"])

        page = self.client.get("/sales_update/hotel?date=2026-08-12")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn("₹6,700", html)
        self.assertIn("All values are from the sales entry (12 Aug 2026).", html)
        self.assertNotIn("All values are from invoices (12 Aug 2026)", html)


if __name__ == "__main__":
    unittest.main()
