"""POS restaurant-grade table occupancy — KOT-driven state machine.

Covers:
- A brand-new dine-in bill must not be openable against a table the Tables
  page already shows as occupied (save_pos_invoice() reads the same
  /point-of-sale/api/floor source of truth used there).
- Occupancy flips on the *first KOT sent* for an order, not on a plain save.
- Occupied != locked: resuming/updating the same order (by order_no) is never
  blocked, and neither is a further KOT for that same bill.
- get_open_pos_invoice_for_table() resumes an open dine-in bill by table.
- Close & Free Table frees the table directly (no cleaning buffer).
- Clear all tables frees every table and closes any dangling open bills.
"""

import os
import tempfile
import unittest
from unittest import mock

import db as db_mod


class PosTableOccupancyTests(unittest.TestCase):
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

        # Floor: T1 available, T3 occupied (no order behind it — simulates a
        # manually-forced occupied tile) — same layout the Tables page renders from.
        put = self.client.put(
            "/point-of-sale/api/floor",
            json={
                "areas": [{"id": "area_1", "type": "area", "name": "Main Hall"}],
                "tables": [
                    {
                        "id": "t1",
                        "type": "table",
                        "name": "T1",
                        "seats": 4,
                        "shape": "square",
                        "status": "available",
                        "areaId": "area_1",
                    },
                    {
                        "id": "t3",
                        "type": "table",
                        "name": "T3",
                        "seats": 6,
                        "shape": "rect",
                        "status": "occupied",
                        "areaId": "area_1",
                    },
                ],
            },
        )
        self.assertEqual(put.status_code, 200)

    def tearDown(self):
        self._get_user_patch.stop()
        db_mod.DATABASE_PATH = self._orig_path
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def _floor_status(self, name):
        res = self.client.get("/point-of-sale/api/floor")
        for t in res.get_json()["tables"]:
            if t["name"] == name:
                return t["status"]
        return None

    def _payload(self, order_no, table, order_type="dine_in", kot_send=False, **overrides):
        data = {
            "orderNo": order_no,
            "savedAt": "2026-07-22 18:00:00",
            "orderType": order_type,
            "table": table,
            "captain": "",
            "customerName": "Guest One",
            "customerMobile": "9876543210",
            "notes": "",
            "kotSend": kot_send,
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
                    "variant": "",
                    "rate": 100,
                    "qty": 2,
                    "kotSentQty": 2 if kot_send else 0,
                },
            ],
            "totals": {
                "subtotal": 200,
                "discount": 0,
                "discountType": "pct",
                "discountValue": 0,
                "gst": 10,
                "service": 0,
                "serviceType": "pct",
                "serviceValue": 0,
                "tip": 0,
                "roundOff": 0,
                "total": 210,
            },
        }
        data.update(overrides)
        return data

    # -- Blocking a brand-new bill on an occupied table -----------------------

    def test_new_bill_blocked_for_occupied_table(self):
        res = self.client.post("/point-of-sale/api/invoices", json=self._payload("ORD-2607-0010", "T3"))
        self.assertEqual(res.status_code, 400)
        body = res.get_json()
        self.assertFalse(body["ok"])
        self.assertIn("occupied", body["error"].lower())
        self.assertIn("T3", body["error"])

        # Table stays occupied — nothing was created against it.
        self.assertEqual(self._floor_status("T3"), "occupied")

    def test_new_kot_send_also_blocked_for_occupied_table(self):
        res = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload("ORD-2607-0010b", "T3", kot_send=True),
        )
        self.assertEqual(res.status_code, 400)
        self.assertFalse(res.get_json()["ok"])

    # -- Occupancy is KOT-driven, not save-driven ------------------------------

    def test_plain_save_does_not_flip_occupancy(self):
        self.assertEqual(self._floor_status("T1"), "available")

        res = self.client.post("/point-of-sale/api/invoices", json=self._payload("ORD-2607-0011", "T1"))
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        invoice = res.get_json()["invoice"]
        self.assertFalse(invoice["kot_sent"])

        # A plain save (no KOT yet) must never claim the table.
        self.assertEqual(self._floor_status("T1"), "available")

    def test_first_kot_send_flips_table_occupied(self):
        self.assertEqual(self._floor_status("T1"), "available")

        res = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload("ORD-2607-0012", "T1", kot_send=True),
        )
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        invoice = res.get_json()["invoice"]
        self.assertTrue(invoice["kot_sent"])
        self.assertTrue(invoice["first_kot_at"])
        self.assertEqual(invoice["lines"][0]["sent_qty"], 2)

        self.assertEqual(self._floor_status("T1"), "occupied")

    def test_second_kot_send_does_not_force_status_back_to_occupied(self):
        first = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload("ORD-2607-0013", "T1", kot_send=True),
        )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(self._floor_status("T1"), "occupied")

        # Staff manually moves the table to cleaning between KOTs (edge case) —
        # a second KOT for the *same* bill must not force it back to occupied.
        put = self.client.put(
            "/point-of-sale/api/floor",
            json={
                "areas": [{"id": "area_1", "type": "area", "name": "Main Hall"}],
                "tables": [
                    {"id": "t1", "type": "table", "name": "T1", "seats": 4, "shape": "square", "status": "cleaning", "areaId": "area_1"},
                    {"id": "t3", "type": "table", "name": "T3", "seats": 6, "shape": "rect", "status": "occupied", "areaId": "area_1"},
                ],
            },
        )
        self.assertEqual(put.status_code, 200)

        again = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload(
                "ORD-2607-0013",
                "T1",
                kot_send=True,
                lines=[
                    {"uid": "1", "menuId": None, "name": "Filter Coffee", "variant": "", "rate": 100, "qty": 2, "kotSentQty": 2},
                    {"uid": "2", "menuId": None, "name": "Sandwich", "variant": "", "rate": 150, "qty": 1, "kotSentQty": 1},
                ],
            ),
        )
        self.assertEqual(again.status_code, 200, again.get_data(as_text=True))
        self.assertEqual(self._floor_status("T1"), "cleaning")

    # -- Occupied != locked: resuming/updating the same bill is never blocked --

    def test_resuming_same_order_no_is_never_blocked(self):
        first = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload("ORD-2607-0014", "T1", kot_send=True),
        )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(self._floor_status("T1"), "occupied")

        # Same order_no again (e.g. adding items on the now-occupied table) must
        # succeed even though this exact bill is what marked the table occupied.
        again = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload("ORD-2607-0014", "T1", customerName="Guest Updated"),
        )
        self.assertEqual(again.status_code, 200, again.get_data(as_text=True))
        self.assertEqual(again.get_json()["invoice"]["customer_name"], "Guest Updated")

    def test_takeaway_order_ignores_table_occupancy(self):
        res = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload("ORD-2607-0015", "T3", order_type="takeaway", kot_send=True),
        )
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        # Takeaway never claims a table, so occupancy is left untouched.
        self.assertEqual(self._floor_status("T3"), "occupied")

    # -- Resume lookup ----------------------------------------------------------

    def test_by_table_lookup_finds_open_order_even_without_kot(self):
        res = self.client.get("/point-of-sale/api/invoices/by-table?table=T1")
        self.assertEqual(res.status_code, 200)
        self.assertIsNone(res.get_json()["invoice"])

        self.client.post("/point-of-sale/api/invoices", json=self._payload("ORD-2607-0016", "T1"))
        # Plain save has no KOT yet, but the invoice IS open/dine-in — resume
        # lookup should still surface it (occupancy state and resumability are
        # independent: an unsent order on an available table should still open
        # back up if the staff navigates away and back).
        res = self.client.get("/point-of-sale/api/invoices/by-table?table=T1")
        found = res.get_json()["invoice"]
        self.assertIsNotNone(found)
        self.assertEqual(found["order_no"], "ORD-2607-0016")

    def test_by_table_lookup_case_insensitive_and_after_close_is_gone(self):
        saved = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload("ORD-2607-0017", "T1", kot_send=True),
        )
        invoice_id = saved.get_json()["invoice"]["id"]

        res = self.client.get("/point-of-sale/api/invoices/by-table?table=t1")
        self.assertEqual(res.get_json()["invoice"]["order_no"], "ORD-2607-0017")

        close = self.client.post(f"/point-of-sale/api/invoices/{invoice_id}/close")
        self.assertEqual(close.status_code, 200, close.get_data(as_text=True))

        res = self.client.get("/point-of-sale/api/invoices/by-table?table=T1")
        self.assertIsNone(res.get_json()["invoice"])

    # -- Close & Free Table -------------------------------------------------

    def test_close_and_free_table_frees_directly_no_cleaning_buffer(self):
        saved = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload("ORD-2607-0018", "T1", kot_send=True),
        )
        invoice_id = saved.get_json()["invoice"]["id"]
        self.assertEqual(self._floor_status("T1"), "occupied")

        close = self.client.post(f"/point-of-sale/api/invoices/{invoice_id}/close")
        self.assertEqual(close.status_code, 200, close.get_data(as_text=True))
        closed_invoice = close.get_json()["invoice"]
        self.assertEqual(closed_invoice["status"], "closed")

        # Directly available — no mandatory "cleaning" buffer.
        self.assertEqual(self._floor_status("T1"), "available")

    def test_close_missing_invoice_returns_error(self):
        res = self.client.post("/point-of-sale/api/invoices/999999/close")
        self.assertEqual(res.status_code, 400)
        self.assertFalse(res.get_json()["ok"])

    def test_new_bill_allowed_on_table_after_close(self):
        saved = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload("ORD-2607-0019", "T1", kot_send=True),
        )
        invoice_id = saved.get_json()["invoice"]["id"]
        self.client.post(f"/point-of-sale/api/invoices/{invoice_id}/close")

        # A totally new party can now open a fresh bill on the freed table.
        res = self.client.post("/point-of-sale/api/invoices", json=self._payload("ORD-2607-0020", "T1"))
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))

    # -- Clear all tables -----------------------------------------------------

    def test_clear_all_tables_frees_everything_and_closes_dangling_bills(self):
        saved = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload("ORD-2607-0021", "T1", kot_send=True),
        )
        invoice_id = saved.get_json()["invoice"]["id"]
        self.assertEqual(self._floor_status("T1"), "occupied")
        self.assertEqual(self._floor_status("T3"), "occupied")

        res = self.client.post("/point-of-sale/api/floor/clear-all")
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        for t in res.get_json()["tables"]:
            self.assertEqual(t["status"], "available")

        self.assertEqual(self._floor_status("T1"), "available")
        self.assertEqual(self._floor_status("T3"), "available")

        # The open bill behind T1 is closed, not left dangling as "open".
        conn = db_mod.get_db()
        try:
            invoice = db_mod.get_pos_invoice(conn, invoice_id)
        finally:
            conn.close()
        self.assertEqual(invoice["status"], "closed")

        # And its table can no longer be "resumed" from a stale open order.
        res = self.client.get("/point-of-sale/api/invoices/by-table?table=T1")
        self.assertIsNone(res.get_json()["invoice"])


if __name__ == "__main__":
    unittest.main()
