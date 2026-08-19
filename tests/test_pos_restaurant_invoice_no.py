"""Restaurant POS invoice numbers: SPC/{yy-yy}/{n}."""

import os
import tempfile
import unittest
from datetime import date
from unittest import mock

import db as db_mod


class PosRestaurantInvoiceNoTests(unittest.TestCase):
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

    def test_fiscal_year_label(self):
        self.assertEqual(db_mod.indian_fiscal_year_label(date(2026, 7, 29)), "2026-27")
        self.assertEqual(db_mod.indian_fiscal_year_label(date(2026, 3, 31)), "2025-26")
        self.assertEqual(db_mod.indian_fiscal_year_label(date(2026, 4, 1)), "2026-27")
        self.assertEqual(db_mod.indian_fiscal_year_short_label(date(2026, 7, 29)), "26-27")
        self.assertEqual(db_mod.indian_fiscal_year_short_label("2026-27"), "26-27")

    def test_fiscal_year_bounds(self):
        self.assertEqual(
            db_mod.indian_fiscal_year_bounds(date(2026, 7, 29)),
            (date(2026, 4, 1), date(2026, 7, 29)),
        )
        self.assertEqual(
            db_mod.indian_fiscal_year_bounds(date(2026, 3, 31)),
            (date(2025, 4, 1), date(2026, 3, 31)),
        )
        self.assertEqual(
            db_mod.indian_fiscal_year_bounds(date(2026, 4, 1)),
            (date(2026, 4, 1), date(2026, 4, 1)),
        )

    def _payload(self, order_no, **overrides):
        data = {
            "orderNo": order_no,
            "savedAt": "2026-07-29 12:00:00",
            "orderDate": "2026-07-29",
            "orderType": "takeaway",
            "table": "",
            "customerName": "Guest",
            "customerMobile": "",
            "lines": [{"uid": "1", "name": "Coffee", "rate": 50, "qty": 1}],
            "totals": {
                "subtotal": 50,
                "discount": 0,
                "gst": 5,
                "vat": 0,
                "service": 0,
                "tip": 0,
                "roundOff": 0,
                "total": 55,
            },
        }
        data.update(overrides)
        return data

    def test_client_spc_number_persists(self):
        res = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload("SPC/26-27/7"),
        )
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        body = res.get_json()
        self.assertEqual(body["invoice"]["order_no"], "SPC/26-27/7")

    def test_draft_kept_until_generate_invoice(self):
        draft = "SPC/A1B2C3/26-27"
        save = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload(draft),
        )
        self.assertEqual(save.status_code, 200, save.get_data(as_text=True))
        self.assertEqual(save.get_json()["invoice"]["order_no"], draft)
        self.assertFalse(save.get_json()["invoice"].get("customer_bill_sent"))

        bill = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload(draft, customerBill=True),
        )
        self.assertEqual(bill.status_code, 200, bill.get_data(as_text=True))
        body = bill.get_json()
        self.assertEqual(body["invoice"]["order_no"], "SPC/26-27/1")
        self.assertTrue(body["invoice"].get("customer_bill_sent"))

    def test_offline_draft_is_replaced_with_sequence(self):
        res = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload("SPC/A1B2C3/26-27", customerBill=True),
        )
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        body = res.get_json()
        self.assertEqual(body["invoice"]["order_no"], "SPC/26-27/1")

    def test_legacy_long_fy_draft_is_replaced(self):
        res = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload("SPC/105868/2026-27", customerBill=True),
        )
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        body = res.get_json()
        self.assertEqual(body["invoice"]["order_no"], "SPC/26-27/1")

    def test_sequences_increment_within_fy(self):
        first = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload("SPC/BBBBBB/26-27", customerBill=True),
        ).get_json()["invoice"]["order_no"]
        second = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload("SPC/CCCCCC/26-27", customerBill=True),
        ).get_json()["invoice"]["order_no"]
        self.assertEqual(first, "SPC/26-27/1")
        self.assertEqual(second, "SPC/26-27/2")

    def test_legacy_long_fy_does_not_inflate_new_series(self):
        conn = db_mod.get_db()
        try:
            conn.execute(
                """INSERT INTO pos_invoices
                   (order_no, order_date, order_type, table_label, customer_name, customer_mobile,
                    captain, status, outlet, subtotal, discount_amount, gst_amount, service_amount,
                    tip, round_off, grand_total, saved_at, is_active)
                   VALUES ('SPC/105868/2026-27', '2026-07-28', 'takeaway', '', 'Old', '',
                           '', 'open', 'restaurant', 50, 0, 0, 0, 0, 0, 50,
                           '2026-07-28 12:00:00', 1)"""
            )
            conn.commit()
        finally:
            conn.close()

        allocated = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload("SPC/AAAAAA/26-27", customerBill=True),
        ).get_json()["invoice"]["order_no"]
        self.assertEqual(allocated, "SPC/26-27/1")

    def test_new_series_fills_from_one_despite_high_outlier(self):
        conn = db_mod.get_db()
        try:
            conn.execute(
                """INSERT INTO pos_invoices
                   (order_no, order_date, order_type, table_label, customer_name, customer_mobile,
                    captain, status, outlet, subtotal, discount_amount, gst_amount, service_amount,
                    tip, round_off, grand_total, saved_at, is_active)
                   VALUES ('SPC/26-27/105869', '2026-07-28', 'takeaway', '', 'Outlier', '',
                           '', 'open', 'restaurant', 50, 0, 0, 0, 0, 0, 50,
                           '2026-07-28 12:00:00', 1)"""
            )
            conn.commit()
        finally:
            conn.close()

        allocated = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload("SPC/BBBBBB/26-27", customerBill=True),
        ).get_json()["invoice"]["order_no"]
        self.assertEqual(allocated, "SPC/26-27/1")

    def test_resume_keeps_spc_number(self):
        save = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload("SPC/26-27/3"),
        )
        self.assertEqual(save.status_code, 200)
        again = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload(
                "SPC/26-27/3",
                customerName="Guest Updated",
                lines=[{"uid": "1", "name": "Coffee", "rate": 50, "qty": 2}],
                totals={
                    "subtotal": 100,
                    "discount": 0,
                    "gst": 0,
                    "service": 0,
                    "tip": 0,
                    "roundOff": 0,
                    "total": 100,
                },
            ),
        )
        self.assertEqual(again.status_code, 200, again.get_data(as_text=True))
        body = again.get_json()
        self.assertEqual(body["invoice"]["order_no"], "SPC/26-27/3")
        self.assertEqual(body["invoice"]["customer_name"], "Guest Updated")

    def test_nil_tax_generate_uses_nill_series(self):
        res = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload(
                "SPC/AAAAAA/26-27",
                customerBill=True,
                totals={
                    "subtotal": 50,
                    "discount": 0,
                    "gst": 0,
                    "vat": 0,
                    "service": 0,
                    "tip": 0,
                    "roundOff": 0,
                    "total": 50,
                },
            ),
        )
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        body = res.get_json()
        self.assertEqual(body["invoice"]["order_no"], "SPC/26-27/Nill/1")
        self.assertTrue(body["invoice"].get("customer_bill_sent"))

    def test_nill_series_independent_of_taxable(self):
        taxed = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload("SPC/BBBBBB/26-27", customerBill=True),
        ).get_json()["invoice"]["order_no"]
        nill_totals = {
            "subtotal": 50,
            "discount": 0,
            "gst": 0,
            "vat": 0,
            "service": 0,
            "tip": 0,
            "roundOff": 0,
            "total": 50,
        }
        nill = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload(
                "SPC/CCCCCC/26-27",
                customerBill=True,
                totals=nill_totals,
            ),
        ).get_json()["invoice"]["order_no"]
        nill2 = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload(
                "SPC/DDDDDD/26-27",
                customerBill=True,
                totals=nill_totals,
            ),
        ).get_json()["invoice"]["order_no"]
        self.assertEqual(taxed, "SPC/26-27/1")
        self.assertEqual(nill, "SPC/26-27/Nill/1")
        self.assertEqual(nill2, "SPC/26-27/Nill/2")

    def test_nill_order_no_is_final(self):
        self.assertTrue(db_mod.is_restaurant_spc_nill_order_no("SPC/26-27/Nill/1"))
        self.assertFalse(db_mod.is_restaurant_spc_order_no("SPC/26-27/Nill/1"))
        self.assertFalse(db_mod.is_provisional_pos_order_no("SPC/26-27/Nill/1"))
        self.assertTrue(db_mod.pos_invoice_is_nil_tax(0, 0))
        self.assertTrue(db_mod.pos_invoice_is_nil_tax(0.004, 0))
        self.assertFalse(db_mod.pos_invoice_is_nil_tax(5, 0))
        self.assertFalse(db_mod.pos_invoice_is_nil_tax(0, 20))

    def test_soft_deleted_official_number_stays_reserved(self):
        conn = db_mod.get_db()
        try:
            conn.execute(
                """INSERT INTO pos_invoices
                   (order_no, order_date, order_type, table_label, customer_name, customer_mobile,
                    captain, status, outlet, subtotal, discount_amount, gst_amount, service_amount,
                    tip, round_off, grand_total, saved_at, customer_bill_sent, is_active)
                   VALUES ('SPC/26-27/710', '2026-07-29', 'takeaway', '', 'Guest', '',
                           '', 'open', 'restaurant', 50, 0, 5, 0, 0, 0, 55,
                           '2026-07-29 12:00:00', 1, 0)"""
            )
            conn.commit()
        finally:
            conn.close()

        blocked = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload("SPC/BBBBBB/26-27", customerBill=True),
        )
        self.assertEqual(blocked.status_code, 400, blocked.get_data(as_text=True))
        self.assertIn("reserved", blocked.get_json()["error"].lower())

    def test_cannot_resume_cancelled_invoice_number(self):
        draft = "SPC/RESUME1/26-27"
        bill = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload(draft, customerBill=True),
        )
        self.assertEqual(bill.status_code, 200, bill.get_data(as_text=True))
        invoice = bill.get_json()["invoice"]
        order_no = invoice["order_no"]
        invoice_id = invoice["id"]

        cancel = self.client.post(
            f"/point-of-sale/api/invoices/{invoice_id}/delete",
            json={"reason": "Guest left"},
        )
        self.assertEqual(cancel.status_code, 200, cancel.get_data(as_text=True))

        resume = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload(order_no, customerBill=True),
        )
        self.assertEqual(resume.status_code, 400, resume.get_data(as_text=True))
        self.assertIn("cancelled", resume.get_json()["error"].lower())
