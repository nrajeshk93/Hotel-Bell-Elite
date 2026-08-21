"""POS menu selling prices are GST-inclusive by default."""

import os
import tempfile
import unittest
from unittest import mock

import db as db_mod


class PosInclusiveTaxTests(unittest.TestCase):
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

    def _save_line(self, rate):
        payload = {
            "orderNo": "SPC/GSTINCL/26-27",
            "savedAt": "2026-08-19 12:00:00",
            "orderDate": "2026-08-19",
            "orderType": "takeaway",
            "table": "",
            "customerName": "Guest",
            "customerMobile": "",
            "lines": [{"uid": "L1", "name": "Grilled Fish", "rate": rate, "qty": 1}],
            "totals": {
                "subtotal": rate,
                "discount": 0,
                "gst": 0,
                "vat": 0,
                "service": 0,
                "tip": 0,
                "roundOff": 0,
                "total": rate,
            },
        }
        res = self.client.post("/point-of-sale/api/invoices", json=payload)
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        return res.get_json()["invoice"]["id"]

    def test_tax_rates_default_to_prices_include_tax(self):
        conn = db_mod.get_db()
        try:
            rates = db_mod.get_pos_tax_rates(conn)
        finally:
            conn.close()
        self.assertTrue(rates["prices_include_tax"])
        self.assertAlmostEqual(rates["cgst"] + rates["ugst"], 0.05)

    def test_recompute_extracts_gst_from_inclusive_menu_price(self):
        """₹514.50 incl. 5% GST → taxable ₹490, GST ₹24.50, bill stays ₹514.50."""
        inv_id = self._save_line(514.50)
        conn = db_mod.get_db()
        try:
            money = db_mod._recompute_pos_invoice_money_from_lines(conn, inv_id)
        finally:
            conn.close()
        self.assertAlmostEqual(money["gst"], 24.50, places=2)
        self.assertAlmostEqual(money["subtotal"], 490.00, places=2)
        self.assertIn(int(round(money["grand_total"])), (514, 515))

    def test_exclusive_setting_still_adds_gst_on_top(self):
        conn = db_mod.get_db()
        try:
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
        inv_id = self._save_line(514.50)
        conn = db_mod.get_db()
        try:
            money = db_mod._recompute_pos_invoice_money_from_lines(conn, inv_id)
        finally:
            conn.close()
        self.assertAlmostEqual(money["gst"], 25.73, places=2)
        self.assertGreater(money["grand_total"], 514.50)
