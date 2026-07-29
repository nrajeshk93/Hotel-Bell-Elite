"""POS invoice discount scoped to selected line uids."""

import os
import tempfile
import unittest
from unittest import mock

import db as db_mod


class PosDiscountLineScopeTests(unittest.TestCase):
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

    def _payload(self, **overrides):
        data = {
            "orderNo": "SPC/ZZZZZZ/2026-27",
            "savedAt": "2026-07-29 12:00:00",
            "orderDate": "2026-07-29",
            "orderType": "takeaway",
            "table": "",
            "customerName": "Guest",
            "customerMobile": "",
            "discountType": "pct",
            "discountValue": 10,
            "discountLineUids": ["L1", "L2"],
            "lines": [
                {"uid": "L1", "name": "Coffee", "rate": 100, "qty": 1},
                {"uid": "L2", "name": "Tea", "rate": 50, "qty": 1},
                {"uid": "L3", "name": "Juice", "rate": 150, "qty": 1},
            ],
            "totals": {
                "subtotal": 300,
                "discount": 15,
                "gst": 0,
                "vat": 0,
                "service": 0,
                "tip": 0,
                "roundOff": 0,
                "total": 285,
                "discountType": "pct",
                "discountValue": 10,
            },
        }
        data.update(overrides)
        return data

    def test_scoped_percent_discount_persists_and_reloads(self):
        res = self.client.post("/point-of-sale/api/invoices", json=self._payload())
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        body = res.get_json()
        inv = body["invoice"]
        self.assertEqual(inv["discount"], 15.0)
        self.assertEqual(sorted(inv["discount_line_uids"]), ["L1", "L2"])
        line_uids = [line["uid"] for line in inv["lines"]]
        self.assertEqual(line_uids, ["L1", "L2", "L3"])

        again = self.client.get(f"/point-of-sale/api/invoices/{inv['id']}")
        self.assertEqual(again.status_code, 200)
        loaded = again.get_json()["invoice"]
        self.assertEqual(loaded["discount"], 15.0)
        self.assertEqual(sorted(loaded["discount_line_uids"]), ["L1", "L2"])

    def test_empty_scope_uses_full_bill_discount(self):
        res = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload(
                discountLineUids=[],
                totals={
                    "subtotal": 300,
                    "discount": 30,
                    "gst": 0,
                    "vat": 0,
                    "service": 0,
                    "tip": 0,
                    "roundOff": 0,
                    "total": 270,
                    "discountType": "pct",
                    "discountValue": 10,
                },
            ),
        )
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        inv = res.get_json()["invoice"]
        self.assertEqual(inv["discount"], 30.0)
        self.assertEqual(inv["discount_line_uids"], [])

    def test_selecting_all_lines_clears_scope(self):
        res = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload(discountLineUids=["L1", "L2", "L3"]),
        )
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        inv = res.get_json()["invoice"]
        self.assertEqual(inv["discount_line_uids"], [])

    def test_recompute_respects_discount_line_uids(self):
        res = self.client.post("/point-of-sale/api/invoices", json=self._payload())
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        inv_id = res.get_json()["invoice"]["id"]
        conn = db_mod.get_db()
        try:
            money = db_mod._recompute_pos_invoice_money_from_lines(conn, inv_id)
            row = conn.execute(
                "SELECT discount_amount FROM pos_invoices WHERE id = ?",
                (inv_id,),
            ).fetchone()
            self.assertEqual(float(row["discount_amount"]), 15.0)
            self.assertIsNotNone(money)
        finally:
            conn.close()
