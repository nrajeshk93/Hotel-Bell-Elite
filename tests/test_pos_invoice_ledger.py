"""POS Invoice Ledger — save, list, KPI, upsert, delete."""

import os
import tempfile
import unittest
from unittest import mock

import db as db_mod


class PosInvoiceLedgerTests(unittest.TestCase):
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
        self._get_user_patch = mock.patch.object(app_mod, "get_current_user", return_value=self.user)
        self._get_user_patch.start()

    def tearDown(self):
        self._get_user_patch.stop()
        db_mod.DATABASE_PATH = self._orig_path
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def _payload(self, order_no="ORD-2607-0001", total=500, **overrides):
        data = {
            "orderNo": order_no,
            "savedAt": "2026-07-22 18:00:00",
            "orderType": "dine_in",
            "table": "T1",
            "captain": "",
            "customerName": "Guest One",
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

    def test_save_list_kpi_upsert_delete(self):
        save = self.client.post("/point-of-sale/api/invoices", json=self._payload())
        self.assertEqual(save.status_code, 200, save.get_data(as_text=True))
        body = save.get_json()
        self.assertTrue(body["ok"])
        invoice_id = body["invoice"]["id"]
        self.assertEqual(body["invoice"]["order_no"], "ORD-2607-0001")
        self.assertEqual(len(body["invoice"]["lines"]), 2)
        self.assertEqual(body["invoice"]["grand_total"], 500)

        page = self.client.get("/point-of-sale/invoice-ledger")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn("ORD-2607-0001", html)
        self.assertIn("Invoice Ledger", html)
        self.assertIn("Guest One", html)

        save2 = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload(total=550, customerName="Guest Updated"),
        )
        self.assertEqual(save2.status_code, 200)
        body2 = save2.get_json()
        self.assertTrue(body2["ok"])
        self.assertEqual(body2["invoice"]["id"], invoice_id)
        self.assertEqual(body2["invoice"]["customer_name"], "Guest Updated")
        self.assertEqual(body2["invoice"]["grand_total"], 550)

        detail = self.client.get(f"/point-of-sale/api/invoices/{invoice_id}")
        self.assertEqual(detail.status_code, 200)
        detail_body = detail.get_json()
        self.assertTrue(detail_body["ok"])
        self.assertEqual(detail_body["invoice"]["customer_name"], "Guest Updated")

        # Second invoice for KPI count
        save_b = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload(order_no="ORD-2607-0002", total=200, customerName="Guest Two"),
        )
        self.assertEqual(save_b.status_code, 200)

        conn = db_mod.get_db()
        try:
            rows = db_mod.list_pos_invoices(conn)
            kpis = db_mod.pos_invoice_kpis(conn, rows, today="2026-07-22")
        finally:
            conn.close()
        self.assertEqual(kpis["invoice_count"], 2)
        self.assertEqual(kpis["total_sales"], 750)
        self.assertEqual(kpis["average_bill"], 375)
        self.assertEqual(kpis["today_sales"], 750)

        deleted = self.client.post(f"/point-of-sale/api/invoices/{invoice_id}/delete")
        self.assertEqual(deleted.status_code, 200)
        self.assertTrue(deleted.get_json()["ok"])

        missing = self.client.get(f"/point-of-sale/api/invoices/{invoice_id}")
        self.assertEqual(missing.status_code, 404)

        page2 = self.client.get("/point-of-sale/invoice-ledger")
        html2 = page2.get_data(as_text=True)
        self.assertNotIn("ORD-2607-0001", html2)
        self.assertIn("ORD-2607-0002", html2)

    def test_export_report(self):
        save = self.client.post("/point-of-sale/api/invoices", json=self._payload())
        self.assertEqual(save.status_code, 200)
        export = self.client.get("/point-of-sale/invoice-ledger/report")
        self.assertEqual(export.status_code, 200)
        self.assertIn(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            export.content_type or "",
        )
        self.assertIn(b"PK", export.data[:4])

    def test_save_validation(self):
        empty = self.client.post(
            "/point-of-sale/api/invoices",
            json={"orderNo": "ORD-X", "customerName": "A", "lines": [], "totals": {}},
        )
        self.assertEqual(empty.status_code, 400)

        no_name = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload(customerName=""),
        )
        self.assertEqual(no_name.status_code, 400)

    def test_today_invoices_lists_todays_bills_newest_first(self):
        from datetime import datetime, timedelta

        empty = self.client.get("/point-of-sale/api/today-invoices")
        self.assertEqual(empty.status_code, 200)
        body = empty.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["invoice_count"], 0)
        self.assertEqual(body["invoices"], [])
        today = body["date"]
        self.assertEqual(today, datetime.now().strftime("%Y-%m-%d"))

        # Older day must not appear in the hub.
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload(
                order_no="ORD-OLD-0001",
                savedAt=f"{yesterday} 10:00:00",
                table="T9",
            ),
        )

        older = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload(
                order_no="ORD-TODAY-0001",
                savedAt=f"{today} 09:00:00",
                orderType="takeaway",
                table="",
            ),
        )
        self.assertEqual(older.status_code, 200, older.get_data(as_text=True))
        newer = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload(
                order_no="ORD-TODAY-0002",
                savedAt=f"{today} 18:30:00",
                orderType="dine_in",
                table="T2",
            ),
        )
        self.assertEqual(newer.status_code, 200, newer.get_data(as_text=True))

        res = self.client.get("/point-of-sale/api/today-invoices")
        self.assertEqual(res.status_code, 200)
        payload = res.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["date"], today)
        self.assertEqual(payload["invoice_count"], 2)
        orders = [inv["order_no"] for inv in payload["invoices"]]
        self.assertEqual(orders, ["ORD-TODAY-0002", "ORD-TODAY-0001"])
        first = payload["invoices"][0]
        self.assertEqual(first["table_label"], "T2")
        self.assertEqual(first["order_type"], "dine_in")
        self.assertEqual(first["status"], "open")
        self.assertIn("grand_total", first)
        self.assertIn("saved_at", first)


if __name__ == "__main__":
    unittest.main()
