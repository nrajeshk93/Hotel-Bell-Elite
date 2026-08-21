"""Banquet-only CGST/UGST percent override for administrators."""

import os
import tempfile
import unittest
from unittest import mock

import db as db_mod


class PosBanquetTaxTests(unittest.TestCase):
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
            db_mod.save_pos_restaurant_settings(
                conn,
                {
                    "panels": {
                        "taxes": {
                            "values": {
                                "prices_include_tax": {
                                    "kind": "checkbox",
                                    "checked": False,
                                }
                            }
                        }
                    }
                },
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

    def _payload(self, *, order_no, lines, tax_cgst_pct=None, tax_ugst_pct=None, gst=0, total=None, **overrides):
        subtotal = sum(float(line["rate"]) * float(line["qty"]) for line in lines)
        if total is None:
            total = subtotal + float(gst)
        data = {
            "orderNo": order_no,
            "savedAt": "2026-08-13 12:00:00",
            "orderDate": "2026-08-13",
            "orderType": "takeaway",
            "table": "",
            "customerName": "Guest",
            "customerMobile": "",
            "lines": lines,
            "totals": {
                "subtotal": subtotal,
                "discount": 0,
                "gst": gst,
                "vat": 0,
                "service": 0,
                "tip": 0,
                "roundOff": 0,
                "total": total,
            },
        }
        if tax_cgst_pct is not None:
            data["taxCgstPct"] = tax_cgst_pct
        if tax_ugst_pct is not None:
            data["taxUgstPct"] = tax_ugst_pct
        data.update(overrides)
        return data

    def test_admin_banquet_only_stores_custom_percents(self):
        res = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload(
                order_no="SPC/BANQ01/2026-27",
                lines=[{"uid": "L1", "name": "Banquet", "rate": 50000, "qty": 1}],
                tax_cgst_pct=9,
                tax_ugst_pct=9,
                gst=9000,
                total=59000,
            ),
        )
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        inv = res.get_json()["invoice"]
        self.assertEqual(inv["tax_cgst_pct"], 9.0)
        self.assertEqual(inv["tax_ugst_pct"], 9.0)
        self.assertAlmostEqual(inv["gst"], 9000.0)
        conn = db_mod.get_db()
        try:
            money = db_mod._recompute_pos_invoice_money_from_lines(conn, inv["id"])
            self.assertAlmostEqual(money["gst"], 9000.0)
            row = conn.execute(
                "SELECT tax_cgst_pct, tax_ugst_pct, gst_amount FROM pos_invoices WHERE id = ?",
                (inv["id"],),
            ).fetchone()
            self.assertEqual(float(row["tax_cgst_pct"]), 9.0)
            self.assertEqual(float(row["tax_ugst_pct"]), 9.0)
            self.assertAlmostEqual(float(row["gst_amount"]), 9000.0)
        finally:
            conn.close()

    def test_banquet_name_match_is_case_insensitive(self):
        res = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload(
                order_no="SPC/BANQ02/2026-27",
                lines=[{"uid": "L1", "name": "banquet", "rate": 50000, "qty": 1}],
                tax_cgst_pct=9,
                tax_ugst_pct=9,
                gst=9000,
                total=59000,
            ),
        )
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        inv = res.get_json()["invoice"]
        self.assertEqual(inv["tax_cgst_pct"], 9.0)
        self.assertEqual(inv["tax_ugst_pct"], 9.0)

    def test_non_admin_custom_percents_are_ignored(self):
        locked = {
            "id": self.admin_id,
            "username": "cashier",
            "full_name": "Cashier",
            "is_admin": False,
            "is_active": True,
            "dashboard_access": {"point_of_sale"},
            "stores_access": set(),
        }
        with mock.patch.object(self.app_mod, "get_current_user", return_value=locked):
            res = self.client.post(
                "/point-of-sale/api/invoices",
                json=self._payload(
                    order_no="SPC/BANQ03/2026-27",
                    lines=[{"uid": "L1", "name": "Banquet", "rate": 50000, "qty": 1}],
                    tax_cgst_pct=9,
                    tax_ugst_pct=9,
                    gst=9000,
                    total=59000,
                ),
            )
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        inv = res.get_json()["invoice"]
        self.assertIsNone(inv.get("tax_cgst_pct"))
        self.assertIsNone(inv.get("tax_ugst_pct"))

    def test_mixed_products_do_not_store_override(self):
        res = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload(
                order_no="SPC/BANQ04/2026-27",
                lines=[
                    {"uid": "L1", "name": "Banquet", "rate": 50000, "qty": 1},
                    {"uid": "L2", "name": "Coffee", "rate": 100, "qty": 1},
                ],
                tax_cgst_pct=9,
                tax_ugst_pct=9,
                gst=9000,
            ),
        )
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        inv = res.get_json()["invoice"]
        self.assertIsNone(inv.get("tax_cgst_pct"))
        self.assertIsNone(inv.get("tax_ugst_pct"))
        conn = db_mod.get_db()
        try:
            money = db_mod._recompute_pos_invoice_money_from_lines(conn, inv["id"])
            self.assertAlmostEqual(money["gst"], 2505.0)
        finally:
            conn.close()

    def test_invoice_page_has_tax_editors(self):
        res = self.client.get("/point-of-sale/invoice")
        self.assertEqual(res.status_code, 200)
        html = res.get_data()
        self.assertIn(b'id="pos-inv-sum-cgst-pct"', html)
        self.assertIn(b'id="pos-inv-sum-ugst-pct"', html)
        self.assertIn(b'data-pos-is-admin="1"', html)

    def test_banquet_zero_tax_generate_uses_nill_series(self):
        res = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload(
                order_no="SPC/BANQ00/26-27",
                lines=[{"uid": "L1", "name": "Banquet", "rate": 50000, "qty": 1}],
                tax_cgst_pct=0,
                tax_ugst_pct=0,
                gst=0,
                total=50000,
                customerBill=True,
            ),
        )
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        inv = res.get_json()["invoice"]
        self.assertEqual(inv["order_no"], "SPC/26-27/Nill/1")
        self.assertTrue(inv.get("customer_bill_sent"))
        self.assertAlmostEqual(float(inv["gst"]), 0.0)
        self.assertEqual(inv["tax_cgst_pct"], 0.0)
        self.assertEqual(inv["tax_ugst_pct"], 0.0)

    def test_banquet_taxed_generate_uses_taxable_series(self):
        res = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload(
                order_no="SPC/BANQ05/26-27",
                lines=[{"uid": "L1", "name": "Banquet", "rate": 50000, "qty": 1}],
                tax_cgst_pct=9,
                tax_ugst_pct=9,
                gst=9000,
                total=59000,
                customerBill=True,
            ),
        )
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        inv = res.get_json()["invoice"]
        self.assertEqual(inv["order_no"], "SPC/26-27/1")
        self.assertTrue(inv.get("customer_bill_sent"))
