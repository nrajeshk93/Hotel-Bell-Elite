"""Bar POS invoice numbers: INV/{n}/{FY}."""

import os
import tempfile
import unittest
from unittest import mock

import db as db_mod


class PosBarInvoiceNoTests(unittest.TestCase):
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

    def _payload(self, order_no, **overrides):
        data = {
            "orderNo": order_no,
            "savedAt": "2026-07-29 12:00:00",
            "orderDate": "2026-07-29",
            "orderType": "takeaway",
            "table": "",
            "customerName": "Guest",
            "customerMobile": "",
            "lines": [{"uid": "1", "name": "Beer", "rate": 200, "qty": 1}],
            "totals": {
                "subtotal": 200,
                "discount": 0,
                "gst": 0,
                "vat": 20,
                "service": 0,
                "tip": 0,
                "roundOff": 0,
                "total": 220,
            },
        }
        data.update(overrides)
        return data

    def test_client_inv_number_persists(self):
        res = self.client.post(
            "/bar-point-of-sale/api/invoices",
            json=self._payload("INV/7/2026-27"),
        )
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        body = res.get_json()
        self.assertEqual(body["invoice"]["order_no"], "INV/7/2026-27")
        self.assertEqual(body["invoice"]["outlet"], "bar")

    def test_offline_draft_is_replaced_with_sequence(self):
        res = self.client.post(
            "/bar-point-of-sale/api/invoices",
            json=self._payload("INV/A1B2C3/2026-27"),
        )
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        body = res.get_json()
        self.assertEqual(body["invoice"]["order_no"], "INV/1/2026-27")

    def test_sequences_increment_within_fy(self):
        first = self.client.post(
            "/bar-point-of-sale/api/invoices",
            json=self._payload("INV/BBBBBB/2026-27"),
        ).get_json()["invoice"]["order_no"]
        second = self.client.post(
            "/bar-point-of-sale/api/invoices",
            json=self._payload("INV/CCCCCC/2026-27"),
        ).get_json()["invoice"]["order_no"]
        self.assertEqual(first, "INV/1/2026-27")
        self.assertEqual(second, "INV/2/2026-27")

    def test_bar_and_restaurant_sequences_are_independent(self):
        bar = self.client.post(
            "/bar-point-of-sale/api/invoices",
            json=self._payload("INV/ZZZZZZ/2026-27"),
        ).get_json()["invoice"]["order_no"]
        rest = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload("SPC/ZZZZZZ/2026-27"),
        ).get_json()["invoice"]["order_no"]
        self.assertEqual(bar, "INV/1/2026-27")
        self.assertEqual(rest, "SPC/1/2026-27")
