"""POS restaurant-grade table occupancy.

Covers:
- A brand-new dine-in bill must not be openable against a table the Tables
  page already shows as occupied (save_pos_invoice() reads the same
  /point-of-sale/api/floor source of truth used there).
- Occupancy flips when a dine-in bill with a table is saved (items on table),
  including plain Save / autosave — not only on KOT send.
- Occupied != locked: resuming/updating the same order (by order_no) is never
  blocked, and neither is a further KOT for that same bill.
- get_open_pos_invoice_for_table() resumes an open dine-in bill by table.
- Close & Free Table frees the table directly (no cleaning buffer).
- Clear all tables frees every table and closes any dangling open bills.
"""

import os
import tempfile
import unittest
from datetime import date, timedelta
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

        # Floor: T1/T2 available, T3 occupied (no order behind it — simulates a
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
                        "id": "t2",
                        "type": "table",
                        "name": "T2",
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

    # -- Occupancy flips on dine-in save (items on table), not only KOT -------

    def test_plain_save_flips_table_occupied(self):
        self.assertEqual(self._floor_status("T1"), "available")

        res = self.client.post("/point-of-sale/api/invoices", json=self._payload("ORD-2607-0011", "T1"))
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        invoice = res.get_json()["invoice"]
        self.assertFalse(invoice["kot_sent"])

        # Saving items onto a dine-in table claims it as occupied immediately.
        self.assertEqual(self._floor_status("T1"), "occupied")

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
        # lookup should still surface it (and the table is now occupied).
        res = self.client.get("/point-of-sale/api/invoices/by-table?table=T1")
        found = res.get_json()["invoice"]
        self.assertIsNotNone(found)
        self.assertEqual(found["order_no"], "ORD-2607-0016")
        self.assertEqual(self._floor_status("T1"), "occupied")

    def test_plain_save_keeps_lines_for_table_resume_after_leave(self):
        """Autosave/leave equivalent: plain save of a dine-in cart must be
        resumable by table with the same menu lines still present (e.g. Butter
        Chicken with NEW / unsent KOT qty). Occupancy flips on that save.
        """
        save = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload(
                "ORD-2607-0040",
                "T1",
                customerName="Guest",
                lines=[
                    {
                        "uid": "1",
                        "menuId": None,
                        "name": "Butter Chicken",
                        "variant": "Main",
                        "rate": 320,
                        "qty": 1,
                        "kotSentQty": 0,
                    }
                ],
                totals={
                    "subtotal": 320,
                    "discount": 0,
                    "discountType": "pct",
                    "discountValue": 0,
                    "gst": 16,
                    "service": 0,
                    "serviceType": "pct",
                    "serviceValue": 0,
                    "tip": 0,
                    "roundOff": 0,
                    "total": 336,
                },
            ),
        )
        self.assertEqual(save.status_code, 200, save.get_data(as_text=True))
        self.assertEqual(self._floor_status("T1"), "occupied")

        resumed = self.client.get("/point-of-sale/api/invoices/by-table?table=T1")
        self.assertEqual(resumed.status_code, 200)
        invoice = resumed.get_json()["invoice"]
        self.assertIsNotNone(invoice)
        self.assertEqual(invoice["order_no"], "ORD-2607-0040")
        self.assertEqual(invoice["customer_name"], "Guest")
        self.assertEqual(len(invoice["lines"]), 1)
        self.assertEqual(invoice["lines"][0]["name"], "Butter Chicken")
        self.assertEqual(invoice["lines"][0]["qty"], 1)
        self.assertEqual(invoice["lines"][0]["sent_qty"], 0)

        # Adding another item via a second plain save (same order_no) must still
        # round-trip through by-table resume — mirrors autosave-after-add.
        again = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload(
                "ORD-2607-0040",
                "T1",
                customerName="Guest",
                lines=[
                    {
                        "uid": "1",
                        "menuId": None,
                        "name": "Butter Chicken",
                        "variant": "Main",
                        "rate": 320,
                        "qty": 1,
                        "kotSentQty": 0,
                    },
                    {
                        "uid": "2",
                        "menuId": None,
                        "name": "Garlic Naan",
                        "variant": "Bread",
                        "rate": 60,
                        "qty": 2,
                        "kotSentQty": 0,
                    },
                ],
                totals={
                    "subtotal": 440,
                    "discount": 0,
                    "discountType": "pct",
                    "discountValue": 0,
                    "gst": 22,
                    "service": 0,
                    "serviceType": "pct",
                    "serviceValue": 0,
                    "tip": 0,
                    "roundOff": 0,
                    "total": 462,
                },
            ),
        )
        self.assertEqual(again.status_code, 200, again.get_data(as_text=True))
        resumed2 = self.client.get("/point-of-sale/api/invoices/by-table?table=T1").get_json()["invoice"]
        names = [line["name"] for line in resumed2["lines"]]
        self.assertEqual(names, ["Butter Chicken", "Garlic Naan"])
        self.assertEqual(self._floor_status("T1"), "occupied")

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

    def test_generate_invoice_frees_table_before_settle(self):
        """Generate Invoice frees the floor tile; Settle can finish later."""
        saved = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload("ORD-2607-GenFree-01", "T1", kot_send=True),
        )
        self.assertEqual(saved.status_code, 200, saved.get_data(as_text=True))
        self.assertEqual(self._floor_status("T1"), "occupied")

        bill = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload(
                "ORD-2607-GenFree-01",
                "T1",
                customerBill=True,
                lines=[
                    {
                        "uid": "1",
                        "menuId": None,
                        "name": "Filter Coffee",
                        "variant": "",
                        "rate": 100,
                        "qty": 2,
                        "kotSentQty": 2,
                    }
                ],
            ),
        )
        self.assertEqual(bill.status_code, 200, bill.get_data(as_text=True))
        invoice = bill.get_json()["invoice"]
        self.assertTrue(invoice.get("customer_bill_sent"))
        self.assertEqual(invoice.get("status"), "open")
        self.assertEqual(self._floor_status("T1"), "available")

        # Table is free for a new party while the generated bill awaits settle.
        fresh = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload("ORD-2607-GenFree-02", "T1"),
        )
        self.assertEqual(fresh.status_code, 200, fresh.get_data(as_text=True))
        self.assertEqual(self._floor_status("T1"), "occupied")

        # Resume-by-table must pick the new pre-invoice bill, not the generated one.
        resume = self.client.get("/point-of-sale/api/invoices/by-table?table=T1")
        self.assertEqual(resume.status_code, 200)
        resumed = resume.get_json().get("invoice") or {}
        self.assertEqual(resumed.get("order_no"), fresh.get_json()["invoice"]["order_no"])
        self.assertFalse(resumed.get("customer_bill_sent"))

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
        self.assertIn(res.status_code, (400, 404))
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

    # -- Settle Bill (payment + split, Room Transfer–style) -------------------

    def test_settle_bill_with_cash_closes_and_frees_table(self):
        saved = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload("ORD-2607-Settle-01", "T1", kot_send=True),
        )
        invoice = saved.get_json()["invoice"]
        invoice_id = invoice["id"]
        total = float(invoice["grand_total"])
        self.assertEqual(self._floor_status("T1"), "occupied")

        settle = self.client.post(
            f"/point-of-sale/api/invoices/{invoice_id}/settle",
            json={
                "payment_date": "2026-07-25",
                "notes": "Paid at counter",
                "payment_splits": [{"payment_method": "cash", "amount": total}],
            },
        )
        self.assertEqual(settle.status_code, 200, settle.get_data(as_text=True))
        body = settle.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["invoice"]["status"], "closed")
        self.assertEqual(len(body["invoice"]["payments"]), 1)
        self.assertEqual(body["invoice"]["payments"][0]["payment_method"], "cash")
        self.assertEqual(self._floor_status("T1"), "available")

    def test_settle_bill_split_payment_modes(self):
        saved = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload("ORD-2607-Settle-02", "T1", kot_send=True),
        )
        invoice = saved.get_json()["invoice"]
        invoice_id = invoice["id"]
        total = float(invoice["grand_total"])
        cash_part = 100.0
        upi_part = round(total - cash_part, 2)

        settle = self.client.post(
            f"/point-of-sale/api/invoices/{invoice_id}/settle",
            json={
                "payment_date": "2026-07-25",
                "payment_splits": [
                    {"payment_method": "cash", "amount": cash_part},
                    {"payment_method": "upi", "amount": upi_part},
                ],
            },
        )
        self.assertEqual(settle.status_code, 200, settle.get_data(as_text=True))
        payments = settle.get_json()["invoice"]["payments"]
        self.assertEqual(len(payments), 2)
        by_method = {p["payment_method"]: p["amount"] for p in payments}
        self.assertEqual(by_method["cash"], cash_part)
        self.assertEqual(by_method["upi"], upi_part)
        self.assertEqual(self._floor_status("T1"), "available")

    def test_settle_bill_rejects_mismatched_split_total(self):
        saved = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload("ORD-2607-Settle-03", "T1", kot_send=True),
        )
        invoice_id = saved.get_json()["invoice"]["id"]
        settle = self.client.post(
            f"/point-of-sale/api/invoices/{invoice_id}/settle",
            json={
                "payment_splits": [
                    {"payment_method": "cash", "amount": 50},
                    {"payment_method": "upi", "amount": 50},
                ],
            },
        )
        self.assertEqual(settle.status_code, 400)
        self.assertFalse(settle.get_json()["ok"])
        self.assertEqual(self._floor_status("T1"), "occupied")

    def test_settle_bill_requires_txn_for_bank_transfer(self):
        saved = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload("ORD-2607-Settle-04", "T1", kot_send=True),
        )
        invoice = saved.get_json()["invoice"]
        invoice_id = invoice["id"]
        total = float(invoice["grand_total"])
        settle = self.client.post(
            f"/point-of-sale/api/invoices/{invoice_id}/settle",
            json={
                "payment_splits": [
                    {"payment_method": "bank_transfer", "amount": total, "transaction_id": ""},
                ],
            },
        )
        self.assertEqual(settle.status_code, 400)
        self.assertIn("transaction", settle.get_json()["error"].lower())

    def test_settle_bill_accepts_room_transfer_mode(self):
        today = date.today()
        check_in = today.isoformat()
        check_out = (today + timedelta(days=1)).isoformat()
        checkin = self.client.put(
            "/hotel/api/rooms/room-101",
            json={
                "action": "checkin",
                "stay": {
                    "firstName": "Asha",
                    "lastName": "Nair",
                    "mobile": "9000000001",
                    "checkInDate": check_in,
                    "checkOutDate": check_out,
                    "roomRate": 2000,
                    "nights": 1,
                    "advancePaid": 0,
                },
            },
        )
        self.assertEqual(checkin.status_code, 200, checkin.get_data(as_text=True))

        saved = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload("ORD-2607-Settle-05", "T1", kot_send=True),
        )
        invoice = saved.get_json()["invoice"]
        invoice_id = invoice["id"]
        total = float(invoice["grand_total"])

        missing_room = self.client.post(
            f"/point-of-sale/api/invoices/{invoice_id}/settle",
            json={
                "payment_splits": [
                    {"payment_method": "room_transfer", "amount": total},
                ],
            },
        )
        self.assertEqual(missing_room.status_code, 400)
        self.assertIn("hotel room", missing_room.get_json()["error"].lower())

        settle = self.client.post(
            f"/point-of-sale/api/invoices/{invoice_id}/settle",
            json={
                "payment_splits": [
                    {"payment_method": "room_transfer", "amount": total},
                ],
                "hotel_room_id": "room-101",
            },
        )
        self.assertEqual(settle.status_code, 200, settle.get_data(as_text=True))
        body = settle.get_json()
        methods = {p["payment_method"] for p in body["invoice"]["payments"]}
        self.assertEqual(methods, {"room_transfer"})
        self.assertEqual(self._floor_status("T1"), "available")

        charge = body["invoice"].get("folio_charge") or {}
        self.assertEqual(charge.get("kind"), "restaurant_room_transfer")
        self.assertEqual(float(charge.get("amount") or 0), total)

        room = self.client.get("/hotel/api/rooms/room-101").get_json()["room"]
        folio = room["stay"]["folioCharges"]
        self.assertEqual(len(folio), 1)
        self.assertEqual(folio[0]["kind"], "restaurant_room_transfer")
        self.assertEqual(float(folio[0]["amount"]), total)
        self.assertEqual(
            float(room["stay"]["estimatedTotal"]),
            round(2000 + total, 2),
        )
        self.assertEqual(float(room["stay"]["balanceAmount"]), round(2000 + total, 2))

    def test_settle_bill_rejects_credit_mode(self):
        saved = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload("ORD-2607-Settle-05b", "T1", kot_send=True),
        )
        invoice = saved.get_json()["invoice"]
        settle = self.client.post(
            f"/point-of-sale/api/invoices/{invoice['id']}/settle",
            json={
                "payment_splits": [
                    {"payment_method": "credit", "amount": float(invoice["grand_total"])},
                ],
            },
        )
        self.assertEqual(settle.status_code, 400)
        self.assertIn("payment mode", settle.get_json()["error"].lower())

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

    # -- Kitchen Orders Pending summary (Tables banner) -----------------------

    def test_floor_kot_pending_summary_empty_by_default(self):
        res = self.client.get("/point-of-sale/api/floor")
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        pending = body["kot_pending"]
        self.assertEqual(pending["pending_table_count"], 0)
        self.assertEqual(pending["pending_item_count"], 0)
        self.assertEqual(pending["tables"], [])

    def test_floor_kot_pending_summary_counts_unsents(self):
        # Plain save: qty=2, sent_qty=0 → pending. Table is Occupied (items
        # claimed it) — banner still counts unsents separately from occupancy.
        self.client.post("/point-of-sale/api/invoices", json=self._payload("ORD-2607-0030", "T1"))
        self.assertEqual(self._floor_status("T1"), "occupied")
        res = self.client.get("/point-of-sale/api/floor")
        pending = res.get_json()["kot_pending"]
        self.assertEqual(pending["pending_table_count"], 1)
        self.assertEqual(pending["pending_item_count"], 1)
        self.assertEqual(pending["tables"][0]["name"], "T1")
        self.assertEqual(pending["tables"][0]["pending_items"], 1)
        self.assertEqual(pending["tables"][0]["pending_qty"], 2)
        self.assertEqual(pending["tables"][0]["order_no"], "ORD-2607-0030")
        self.assertEqual(pending["tables"][0]["kot_no"], "KOT-2607-0030")
        self.assertEqual(pending["tables"][0]["table_status"], "occupied")
        self.assertEqual(pending["tables"][0]["seats"], 4)

        # Full KOT send clears pending for that order.
        invoice_id = pending["tables"][0]["invoice_id"]
        send = self.client.post(f"/point-of-sale/api/invoices/{invoice_id}/send-kot")
        self.assertEqual(send.status_code, 200, send.get_data(as_text=True))
        res = self.client.get("/point-of-sale/api/floor")
        pending = res.get_json()["kot_pending"]
        self.assertEqual(pending["pending_table_count"], 0)
        self.assertEqual(pending["pending_item_count"], 0)
        self.assertEqual(pending["tables"], [])

    def test_kot_pending_send_all(self):
        self.client.post("/point-of-sale/api/invoices", json=self._payload("ORD-2607-0060", "T1"))
        # Second table: free T3 first so a new dine-in bill can claim it.
        self.client.put(
            "/point-of-sale/api/floor",
            json={
                "areas": [{"id": "area_1", "type": "area", "name": "Main Hall"}],
                "tables": [
                    {"id": "t1", "type": "table", "name": "T1", "seats": 4, "shape": "square", "status": "occupied", "areaId": "area_1"},
                    {"id": "t3", "type": "table", "name": "T3", "seats": 6, "shape": "rect", "status": "available", "areaId": "area_1"},
                ],
            },
        )
        self.client.post("/point-of-sale/api/invoices", json=self._payload("ORD-2607-0061", "T3"))
        before = self.client.get("/point-of-sale/api/floor").get_json()["kot_pending"]
        self.assertEqual(before["pending_table_count"], 2)

        res = self.client.post("/point-of-sale/api/kot-pending/send-all")
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        body = res.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["sent_count"], 2)
        self.assertEqual(body["kot_pending"]["pending_table_count"], 0)

    def test_kot_tokens_lists_sent_orders_for_resend(self):
        empty = self.client.get("/point-of-sale/api/kot-tokens")
        self.assertEqual(empty.status_code, 200)
        self.assertEqual(empty.get_json()["token_count"], 0)

        # Plain save alone is not a kitchen token yet.
        self.client.post("/point-of-sale/api/invoices", json=self._payload("ORD-2607-0070", "T1"))
        self.assertEqual(self.client.get("/point-of-sale/api/kot-tokens").get_json()["token_count"], 0)

        self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload("ORD-2607-0070", "T1", kot_send=True),
        )
        tokens = self.client.get("/point-of-sale/api/kot-tokens").get_json()
        self.assertEqual(tokens["token_count"], 1)
        row = tokens["tables"][0]
        self.assertEqual(row["name"], "T1")
        self.assertEqual(row["kot_no"], "KOT-2607-0070")
        self.assertEqual(row["sent_qty"], 2)
        self.assertTrue(row["lines"])
        self.assertEqual(row["lines"][0]["sent_qty"], 2)
        self.assertIn("id", row["lines"][0])
        self.assertIsInstance(row["lines"][0]["id"], int)
        self.assertFalse(row.get("customer_bill_sent"))

        # Multi-line invoice returns one selectable line entry per product.
        self.client.put(
            "/point-of-sale/api/floor",
            json={
                "areas": [{"id": "area_1", "type": "area", "name": "Main Hall"}],
                "tables": [
                    {"id": "t1", "type": "table", "name": "T1", "seats": 4, "shape": "square", "status": "available", "areaId": "area_1"},
                    {"id": "t3", "type": "table", "name": "T3", "seats": 6, "shape": "rect", "status": "available", "areaId": "area_1"},
                ],
            },
        )
        self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload(
                "ORD-2607-0071",
                "T3",
                kot_send=True,
                lines=[
                    {
                        "uid": "1",
                        "menuId": None,
                        "name": "Filter Coffee",
                        "variant": "",
                        "rate": 100,
                        "qty": 2,
                        "kotSentQty": 2,
                    },
                    {
                        "uid": "2",
                        "menuId": None,
                        "name": "Sandwich",
                        "variant": "",
                        "rate": 150,
                        "qty": 1,
                        "kotSentQty": 1,
                    },
                ],
            ),
        )
        multi = self.client.get("/point-of-sale/api/kot-tokens").get_json()
        t3 = next(t for t in multi["tables"] if t["name"] == "T3")
        self.assertEqual(len(t3["lines"]), 2)
        self.assertEqual({line["name"] for line in t3["lines"]}, {"Filter Coffee", "Sandwich"})
        self.assertTrue(all(isinstance(line.get("id"), int) for line in t3["lines"]))
        self.assertFalse(t3.get("customer_bill_sent"))

    def test_kot_tokens_hidden_after_invoice_generated(self):
        """After Generate Invoice (customerBill), token leaves the KOT hub list."""
        self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload("ORD-2607-0090", "T1", kot_send=True),
        )
        before = self.client.get("/point-of-sale/api/kot-tokens").get_json()
        self.assertEqual(before["token_count"], 1)
        self.assertFalse(before["tables"][0].get("customer_bill_sent"))

        # Same order, kitchen qty preserved, customer bill flag set (Send to Customer).
        bill = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload(
                "ORD-2607-0090",
                "T1",
                customerBill=True,
                lines=[
                    {
                        "uid": "1",
                        "menuId": None,
                        "name": "Filter Coffee",
                        "variant": "",
                        "rate": 100,
                        "qty": 2,
                        "kotSentQty": 2,
                    }
                ],
            ),
        )
        self.assertEqual(bill.status_code, 200, bill.get_data(as_text=True))
        invoice = bill.get_json().get("invoice") or {}
        self.assertTrue(invoice.get("customer_bill_sent"))

        after = self.client.get("/point-of-sale/api/kot-tokens").get_json()
        self.assertEqual(after["token_count"], 0)
        self.assertEqual(after.get("tables") or [], [])

        # Flag is sticky and cart is locked: a later plain save must be rejected.
        again = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload(
                "ORD-2607-0090",
                "T1",
                lines=[
                    {
                        "uid": "1",
                        "menuId": None,
                        "name": "Filter Coffee",
                        "variant": "",
                        "rate": 100,
                        "qty": 2,
                        "kotSentQty": 2,
                    }
                ],
            ),
        )
        self.assertEqual(again.status_code, 400, again.get_data(as_text=True))
        again_body = again.get_json() or {}
        self.assertIn("already generated", (again_body.get("error") or "").lower())
        sticky = self.client.get("/point-of-sale/api/kot-tokens").get_json()
        self.assertEqual(sticky["token_count"], 0)

    def test_generated_invoice_rejects_line_edits(self):
        """After Generate Invoice (customerBill), changing lines is blocked."""
        create = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload("ORD-2607-0091", "T2", kot_send=True),
        )
        self.assertEqual(create.status_code, 200, create.get_data(as_text=True))

        bill = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload(
                "ORD-2607-0091",
                "T2",
                customerBill=True,
                lines=[
                    {
                        "uid": "1",
                        "menuId": None,
                        "name": "Filter Coffee",
                        "variant": "",
                        "rate": 100,
                        "qty": 2,
                        "kotSentQty": 2,
                    }
                ],
            ),
        )
        self.assertEqual(bill.status_code, 200, bill.get_data(as_text=True))
        self.assertTrue((bill.get_json().get("invoice") or {}).get("customer_bill_sent"))

        edited = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload(
                "ORD-2607-0091",
                "T2",
                lines=[
                    {
                        "uid": "1",
                        "menuId": None,
                        "name": "Filter Coffee",
                        "variant": "",
                        "rate": 100,
                        "qty": 5,
                        "kotSentQty": 2,
                    },
                    {
                        "uid": "2",
                        "menuId": None,
                        "name": "Sandwich",
                        "variant": "",
                        "rate": 80,
                        "qty": 1,
                        "kotSentQty": 0,
                    },
                ],
            ),
        )
        self.assertEqual(edited.status_code, 400, edited.get_data(as_text=True))
        err = (edited.get_json() or {}).get("error") or ""
        self.assertIn("already generated", err.lower())

        detail = self.client.get(
            f"/point-of-sale/api/invoices/{bill.get_json()['invoice']['id']}"
        ).get_json()
        inv = detail.get("invoice") or {}
        self.assertTrue(inv.get("customer_bill_sent"))
        self.assertEqual(len(inv.get("lines") or []), 1)
        self.assertEqual(int((inv["lines"][0].get("qty") or 0)), 2)

    def test_kitchen_sent_lines_locked_without_cancellation_access(self):
        save = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload("ORD-2607-0080", "T1", kot_send=True),
        )
        self.assertEqual(save.status_code, 200, save.get_data(as_text=True))

        conn = db_mod.get_db()
        try:
            # Cannot drop qty below kitchen-sent amount.
            with self.assertRaises(ValueError) as cut:
                db_mod.save_pos_invoice(
                    conn,
                    self._payload(
                        "ORD-2607-0080",
                        "T1",
                        lines=[
                            {
                                "uid": "1",
                                "menuId": None,
                                "name": "Filter Coffee",
                                "variant": "",
                                "rate": 100,
                                "qty": 1,
                                "kotSentQty": 1,
                            }
                        ],
                    ),
                    allow_kot_cancel=False,
                )
            self.assertIn("kitchen-sent", str(cut.exception).lower())
            conn.rollback()

            # Cannot remove the kitchen-sent line.
            with self.assertRaises(ValueError) as removed:
                db_mod.save_pos_invoice(
                    conn,
                    self._payload(
                        "ORD-2607-0080",
                        "T1",
                        lines=[
                            {
                                "uid": "2",
                                "menuId": None,
                                "name": "Sandwich",
                                "variant": "",
                                "rate": 150,
                                "qty": 1,
                                "kotSentQty": 0,
                            }
                        ],
                    ),
                    allow_kot_cancel=False,
                )
            self.assertIn("kitchen-sent", str(removed.exception).lower())
            conn.rollback()

            # Admin flag alone (legacy kw) does not bypass — needs Cancellation Access.
            with self.assertRaises(ValueError) as admin_cut:
                db_mod.save_pos_invoice(
                    conn,
                    self._payload(
                        "ORD-2607-0080",
                        "T1",
                        lines=[
                            {
                                "uid": "1",
                                "menuId": None,
                                "name": "Filter Coffee",
                                "variant": "",
                                "rate": 100,
                                "qty": 1,
                                "kotSentQty": 1,
                            }
                        ],
                    ),
                    actor_is_admin=True,
                    allow_kot_cancel=False,
                )
            self.assertIn("kitchen-sent", str(admin_cut.exception).lower())
            conn.rollback()
        finally:
            conn.close()

    def test_kot_tokens_reduce_api_updates_invoice_and_token(self):
        save = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload(
                "ORD-2607-0082",
                "T1",
                kot_send=True,
                lines=[
                    {
                        "uid": "1",
                        "menuId": None,
                        "name": "Filter Coffee",
                        "variant": "",
                        "rate": 100,
                        "qty": 2,
                        "kotSentQty": 2,
                    },
                    {
                        "uid": "2",
                        "menuId": None,
                        "name": "Sandwich",
                        "variant": "",
                        "rate": 150,
                        "qty": 1,
                        "kotSentQty": 1,
                    },
                ],
            ),
        )
        self.assertEqual(save.status_code, 200, save.get_data(as_text=True))
        invoice_id = save.get_json()["invoice"]["id"]

        tokens = self.client.get("/point-of-sale/api/kot-tokens").get_json()
        token = next(t for t in (tokens.get("tables") or []) if t.get("name") == "T1")
        coffee = next(ln for ln in token["lines"] if ln["name"] == "Filter Coffee")
        self.assertEqual(int(coffee["sent_qty"]), 2)

        reduce = self.client.post(
            "/point-of-sale/api/kot-tokens/reduce",
            json={
                "changes": [
                    {
                        "invoice_id": invoice_id,
                        "line_id": coffee["id"],
                        "sent_qty": 1,
                    }
                ]
            },
        )
        self.assertEqual(reduce.status_code, 200, reduce.get_data(as_text=True))
        body = reduce.get_json()
        self.assertTrue(body.get("ok"))
        self.assertEqual(int(body.get("updated_count") or 0), 1)

        detail = self.client.get(f"/point-of-sale/api/invoices/{invoice_id}").get_json()
        inv_lines = {ln["name"]: ln for ln in (detail.get("invoice") or {}).get("lines") or []}
        self.assertEqual(int(inv_lines["Filter Coffee"]["qty"]), 1)
        self.assertEqual(int(inv_lines["Filter Coffee"]["sent_qty"]), 1)
        self.assertEqual(int(inv_lines["Sandwich"]["qty"]), 1)

        refreshed = {t["name"]: t for t in (body.get("tables") or [])}
        self.assertIn("T1", refreshed)
        self.assertEqual(int(refreshed["T1"]["sent_qty"]), 2)

    def test_kot_tokens_reduce_api_requires_cancellation_access(self):
        save = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload("ORD-2607-0083", "T1", kot_send=True),
        )
        self.assertEqual(save.status_code, 200, save.get_data(as_text=True))
        invoice = save.get_json()["invoice"]
        line_id = invoice["lines"][0]["id"]

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
            denied = self.client.post(
                "/point-of-sale/api/kot-tokens/reduce",
                json={
                    "changes": [
                        {
                            "invoice_id": invoice["id"],
                            "line_id": line_id,
                            "sent_qty": 1,
                        }
                    ]
                },
            )
        self.assertEqual(denied.status_code, 403)
        self.assertFalse(denied.get_json().get("ok"))

    def test_kot_tokens_reduce_all_to_zero_cancels_order_and_frees_table(self):
        save = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload("ORD-2607-0084", "T1", kot_send=True),
        )
        self.assertEqual(save.status_code, 200, save.get_data(as_text=True))
        invoice = save.get_json()["invoice"]
        invoice_id = invoice["id"]
        line_id = invoice["lines"][0]["id"]
        self.assertEqual(self._floor_status("T1"), "occupied")

        reduce = self.client.post(
            "/point-of-sale/api/kot-tokens/reduce",
            json={
                "changes": [
                    {
                        "invoice_id": invoice_id,
                        "line_id": line_id,
                        "sent_qty": 0,
                    }
                ]
            },
        )
        self.assertEqual(reduce.status_code, 200, reduce.get_data(as_text=True))
        body = reduce.get_json()
        self.assertTrue(body.get("ok"))
        self.assertEqual(int(body.get("cancelled_count") or 0), 1)
        self.assertTrue(any(inv.get("cancelled") for inv in (body.get("invoices") or [])))

        detail = self.client.get(f"/point-of-sale/api/invoices/{invoice_id}")
        self.assertIn(detail.status_code, (404, 400))
        if detail.is_json:
            detail_body = detail.get_json() or {}
            self.assertFalse(detail_body.get("ok", True) and detail_body.get("invoice"))

        tokens = self.client.get("/point-of-sale/api/kot-tokens").get_json()
        names = [t.get("name") for t in (tokens.get("tables") or [])]
        self.assertNotIn("T1", names)
        self.assertEqual(self._floor_status("T1"), "available")

    def test_cancellation_access_can_edit_kitchen_sent_and_updates_kot_token(self):
        save = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload(
                "ORD-2607-0081",
                "T1",
                kot_send=True,
                lines=[
                    {
                        "uid": "1",
                        "menuId": None,
                        "name": "Filter Coffee",
                        "variant": "",
                        "rate": 100,
                        "qty": 2,
                        "kotSentQty": 2,
                    },
                    {
                        "uid": "2",
                        "menuId": None,
                        "name": "Sandwich",
                        "variant": "",
                        "rate": 150,
                        "qty": 1,
                        "kotSentQty": 1,
                    },
                ],
            ),
        )
        self.assertEqual(save.status_code, 200, save.get_data(as_text=True))

        tokens = self.client.get("/point-of-sale/api/kot-tokens").get_json()
        self.assertTrue(tokens.get("ok"))
        token_tables = {t["name"]: t for t in (tokens.get("tables") or [])}
        self.assertIn("T1", token_tables)
        self.assertEqual(int(token_tables["T1"]["sent_qty"]), 3)

        conn = db_mod.get_db()
        try:
            # Reduce sent qty — Kitchen Order Token should drop to match.
            updated = db_mod.save_pos_invoice(
                conn,
                self._payload(
                    "ORD-2607-0081",
                    "T1",
                    lines=[
                        {
                            "uid": "1",
                            "menuId": None,
                            "name": "Filter Coffee",
                            "variant": "",
                            "rate": 100,
                            "qty": 1,
                            "kotSentQty": 1,
                        },
                        {
                            "uid": "2",
                            "menuId": None,
                            "name": "Sandwich",
                            "variant": "",
                            "rate": 150,
                            "qty": 1,
                            "kotSentQty": 1,
                        },
                    ],
                ),
                allow_kot_cancel=True,
            )
            conn.commit()
            self.assertEqual(int(updated["lines"][0]["sent_qty"]), 1)
            self.assertEqual(int(updated["lines"][0]["qty"]), 1)

            # Remove the remaining sandwich line entirely.
            updated = db_mod.save_pos_invoice(
                conn,
                self._payload(
                    "ORD-2607-0081",
                    "T1",
                    lines=[
                        {
                            "uid": "1",
                            "menuId": None,
                            "name": "Filter Coffee",
                            "variant": "",
                            "rate": 100,
                            "qty": 1,
                            "kotSentQty": 1,
                        }
                    ],
                ),
                allow_kot_cancel=True,
            )
            conn.commit()
            self.assertEqual(len(updated["lines"]), 1)
            self.assertEqual(updated["lines"][0]["name"], "Filter Coffee")
        finally:
            conn.close()

        tokens = self.client.get("/point-of-sale/api/kot-tokens").get_json()
        token_tables = {t["name"]: t for t in (tokens.get("tables") or [])}
        self.assertIn("T1", token_tables)
        self.assertEqual(int(token_tables["T1"]["sent_qty"]), 1)
        line_names = [ln["name"] for ln in (token_tables["T1"].get("lines") or [])]
        self.assertEqual(line_names, ["Filter Coffee"])

    def test_invoice_line_notes_round_trip(self):
        note = "No onion, extra spicy"
        save = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload(
                "ORD-2607-0090",
                "T1",
                lines=[
                    {
                        "uid": "1",
                        "menuId": None,
                        "name": "Filter Coffee",
                        "variant": "",
                        "rate": 100,
                        "qty": 1,
                        "kotSentQty": 0,
                        "notes": note,
                    }
                ],
                totals={
                    "subtotal": 100,
                    "discount": 0,
                    "discountType": "pct",
                    "discountValue": 0,
                    "gst": 5,
                    "service": 0,
                    "serviceType": "pct",
                    "serviceValue": 0,
                    "tip": 0,
                    "roundOff": 0,
                    "total": 105,
                },
            ),
        )
        self.assertEqual(save.status_code, 200, save.get_data(as_text=True))
        body = save.get_json()
        self.assertTrue(body.get("ok"), body)
        invoice = body.get("invoice") or {}
        self.assertEqual(invoice["lines"][0]["notes"], note)

        invoice_id = invoice["id"]
        loaded = self.client.get(f"/point-of-sale/api/invoices/{invoice_id}")
        self.assertEqual(loaded.status_code, 200, loaded.get_data(as_text=True))
        again = loaded.get_json()["invoice"]
        self.assertEqual(again["lines"][0]["notes"], note)

        # Truncate / normalize on save
        long_note = "  " + ("x" * 250) + "  "
        update = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload(
                "ORD-2607-0090",
                "T1",
                lines=[
                    {
                        "uid": "1",
                        "menuId": None,
                        "name": "Filter Coffee",
                        "variant": "",
                        "rate": 100,
                        "qty": 1,
                        "kotSentQty": 0,
                        "notes": long_note,
                    }
                ],
                totals={
                    "subtotal": 100,
                    "discount": 0,
                    "discountType": "pct",
                    "discountValue": 0,
                    "gst": 5,
                    "service": 0,
                    "serviceType": "pct",
                    "serviceValue": 0,
                    "tip": 0,
                    "roundOff": 0,
                    "total": 105,
                },
            ),
        )
        self.assertEqual(update.status_code, 200, update.get_data(as_text=True))
        updated = update.get_json()["invoice"]["lines"][0]["notes"]
        self.assertEqual(len(updated), 200)
        self.assertTrue(updated.startswith("x"))

    def test_floor_kot_pending_summary_partial_line_and_ignores_takeaway(self):
        # After a first KOT, bump qty without sending — delta is pending.
        self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload("ORD-2607-0031", "T1", kot_send=True),
        )
        again = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload(
                "ORD-2607-0031",
                "T1",
                lines=[
                    {
                        "uid": "1",
                        "menuId": None,
                        "name": "Filter Coffee",
                        "variant": "",
                        "rate": 100,
                        "qty": 3,
                        "kotSentQty": 2,
                    }
                ],
            ),
        )
        self.assertEqual(again.status_code, 200, again.get_data(as_text=True))
        self.assertEqual(self._floor_status("T1"), "occupied")

        # Takeaway with unsents must not appear on the dine-in Tables banner.
        self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload("ORD-2607-0032", "T3", order_type="takeaway"),
        )

        res = self.client.get("/point-of-sale/api/floor")
        pending = res.get_json()["kot_pending"]
        self.assertEqual(pending["pending_table_count"], 1)
        self.assertEqual(pending["pending_item_count"], 1)
        self.assertEqual(pending["tables"][0]["name"], "T1")
        # Occupancy / kot_sent must not gate the banner — occupied + unsents counts.
        self.assertTrue(res.get_json()["kot_pending"]["tables"][0]["invoice_id"])

    def test_floor_get_syncs_available_table_with_open_order_to_occupied(self):
        """Older saves left Available tiles with open bills — floor GET repairs them."""
        save = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload("ORD-2607-0050", "T1"),
        )
        self.assertEqual(save.status_code, 200)
        self.assertEqual(self._floor_status("T1"), "occupied")

        # Simulate pre-fix floor state: open order exists but tile still Available.
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
        # PUT does not sync — status stays available until next GET.
        self.assertEqual(put.get_json()["tables"][0]["status"], "available")

        self.assertEqual(self._floor_status("T1"), "occupied")
        # Stale occupied-without-bill tiles are freed on floor GET sync.
        self.assertEqual(self._floor_status("T3"), "available")

    def test_floor_get_frees_occupied_table_without_open_order(self):
        """A table marked occupied with no open bill must not stay occupied."""
        put = self.client.put(
            "/point-of-sale/api/floor",
            json={
                "areas": [{"id": "area_1", "type": "area", "name": "Main Hall"}],
                "tables": [
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
        self.assertEqual(self._floor_status("T3"), "available")

    def test_dine_in_save_requires_table(self):
        res = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload("ORD-2607-0099", ""),
        )
        self.assertEqual(res.status_code, 400)
        body = res.get_json()
        self.assertFalse(body["ok"])
        self.assertIn("table", body["error"].lower())

    def test_transfer_table_moves_open_bill_and_floor_status(self):
        create = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload("ORD-2607-0060", "T1"),
        )
        self.assertEqual(create.status_code, 200, create.get_data(as_text=True))
        self.assertEqual(self._floor_status("T1"), "occupied")
        self.assertEqual(self._floor_status("T2"), "available")

        res = self.client.post(
            "/point-of-sale/api/invoices/transfer-table",
            json={"from_table": "T1", "to_table": "T2"},
        )
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        body = res.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual((body["invoice"].get("table_label") or body["invoice"].get("table")), "T2")

        self.assertEqual(self._floor_status("T1"), "available")
        self.assertEqual(self._floor_status("T2"), "occupied")

        old = self.client.get("/point-of-sale/api/invoices/by-table?table=T1")
        self.assertIsNone(old.get_json()["invoice"])
        new = self.client.get("/point-of-sale/api/invoices/by-table?table=T2")
        self.assertIsNotNone(new.get_json()["invoice"])
        self.assertEqual(new.get_json()["invoice"]["id"], body["invoice"]["id"])

    def test_transfer_table_fails_without_open_bill(self):
        res = self.client.post(
            "/point-of-sale/api/invoices/transfer-table",
            json={"from_table": "T1", "to_table": "T2"},
        )
        self.assertEqual(res.status_code, 400)
        body = res.get_json()
        self.assertFalse(body["ok"])
        self.assertIn("open bill", body["error"].lower())
        self.assertEqual(self._floor_status("T1"), "available")
        self.assertEqual(self._floor_status("T2"), "available")

    def test_transfer_table_fails_when_destination_has_open_bill(self):
        first = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload("ORD-2607-0061", "T1"),
        )
        self.assertEqual(first.status_code, 200)
        second = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload("ORD-2607-0062", "T2"),
        )
        self.assertEqual(second.status_code, 200)
        self.assertEqual(self._floor_status("T1"), "occupied")
        self.assertEqual(self._floor_status("T2"), "occupied")

        # Force T2 back to available on the floor while its open bill remains —
        # transfer must still reject based on the open invoice, not floor status alone.
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
                        "status": "occupied",
                        "areaId": "area_1",
                    },
                    {
                        "id": "t2",
                        "type": "table",
                        "name": "T2",
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

        res = self.client.post(
            "/point-of-sale/api/invoices/transfer-table",
            json={"from_table": "T1", "to_table": "T2"},
        )
        self.assertEqual(res.status_code, 400)
        body = res.get_json()
        self.assertFalse(body["ok"])
        self.assertIn("already has an open bill", body["error"].lower())

        still_t1 = self.client.get("/point-of-sale/api/invoices/by-table?table=T1")
        self.assertIsNotNone(still_t1.get_json()["invoice"])
        still_t2 = self.client.get("/point-of-sale/api/invoices/by-table?table=T2")
        self.assertIsNotNone(still_t2.get_json()["invoice"])

    # -- Merge tables (combine open bills) ------------------------------------

    def test_merge_tables_combines_open_bills_and_frees_source(self):
        first = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload("ORD-2607-Merge-01", "T1"),
        )
        self.assertEqual(first.status_code, 200, first.get_data(as_text=True))
        first_id = first.get_json()["invoice"]["id"]
        first_lines = len(first.get_json()["invoice"]["lines"])

        second = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload("ORD-2607-Merge-02", "T2"),
        )
        self.assertEqual(second.status_code, 200, second.get_data(as_text=True))
        second_id = second.get_json()["invoice"]["id"]
        second_lines = len(second.get_json()["invoice"]["lines"])
        self.assertEqual(self._floor_status("T1"), "occupied")
        self.assertEqual(self._floor_status("T2"), "occupied")

        res = self.client.post(
            "/point-of-sale/api/invoices/merge-tables",
            json={"from_table": "T1", "to_table": "T2"},
        )
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        body = res.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["invoice"]["id"], second_id)
        self.assertEqual((body["invoice"].get("table_label") or body["invoice"].get("table")), "T2")
        self.assertEqual(len(body["invoice"]["lines"]), first_lines + second_lines)

        self.assertEqual(self._floor_status("T1"), "available")
        self.assertEqual(self._floor_status("T2"), "occupied")

        old = self.client.get("/point-of-sale/api/invoices/by-table?table=T1")
        self.assertIsNone(old.get_json()["invoice"])
        new = self.client.get("/point-of-sale/api/invoices/by-table?table=T2")
        self.assertIsNotNone(new.get_json()["invoice"])
        self.assertEqual(new.get_json()["invoice"]["id"], second_id)

        conn = db_mod.get_db()
        try:
            src = conn.execute(
                "SELECT is_active FROM pos_invoices WHERE id = ?", (first_id,)
            ).fetchone()
            self.assertEqual(int(src["is_active"]), 0)
            moved = conn.execute(
                "SELECT COUNT(*) AS n FROM pos_invoice_lines WHERE invoice_id = ?",
                (second_id,),
            ).fetchone()
            self.assertEqual(int(moved["n"]), first_lines + second_lines)
        finally:
            conn.close()

    def test_merge_tables_from_occupied_onto_empty_destination(self):
        """Bring bill from Occupied T2 into empty T1 — bill lands on T1."""
        occupied = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload("ORD-2607-Merge-03", "T2"),
        )
        self.assertEqual(occupied.status_code, 200)
        inv_id = occupied.get_json()["invoice"]["id"]
        self.assertEqual(self._floor_status("T1"), "available")
        self.assertEqual(self._floor_status("T2"), "occupied")

        res = self.client.post(
            "/point-of-sale/api/invoices/merge-tables",
            json={"from_table": "T2", "to_table": "T1"},
        )
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        body = res.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["invoice"]["id"], inv_id)
        self.assertEqual((body["invoice"].get("table_label") or body["invoice"].get("table")), "T1")
        self.assertEqual(self._floor_status("T1"), "occupied")
        self.assertEqual(self._floor_status("T2"), "available")

        on_t1 = self.client.get("/point-of-sale/api/invoices/by-table?table=T1")
        self.assertIsNotNone(on_t1.get_json()["invoice"])
        self.assertEqual(on_t1.get_json()["invoice"]["id"], inv_id)
        on_t2 = self.client.get("/point-of-sale/api/invoices/by-table?table=T2")
        self.assertIsNone(on_t2.get_json()["invoice"])

    def test_merge_tables_visual_join_when_source_empty_dest_has_bill(self):
        dest = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload("ORD-2607-Merge-03b", "T2"),
        )
        self.assertEqual(dest.status_code, 200)
        dest_id = dest.get_json()["invoice"]["id"]
        res = self.client.post(
            "/point-of-sale/api/invoices/merge-tables",
            json={"from_table": "T1", "to_table": "T2"},
        )
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        body = res.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["invoice"]["id"], dest_id)
        tables = {t["name"]: t for t in body["tables"]}
        self.assertTrue(tables["T2"].get("mergePrimary"))
        self.assertEqual(tables["T2"].get("mergeGroupId"), tables["T1"].get("mergeGroupId"))
        self.assertFalse(tables["T1"].get("hiddenInMerge"))
        self.assertEqual(tables["T1"].get("mergeLabel"), "Bill: T2")
        self.assertEqual(tables["T2"].get("mergeLabel"), "Merged bill")
        self.assertEqual(self._floor_status("T2"), "occupied")

    def test_merge_tables_visual_join_when_neither_has_open_bill(self):
        res = self.client.post(
            "/point-of-sale/api/invoices/merge-tables",
            json={"from_table": "T1", "to_table": "T2"},
        )
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        body = res.get_json()
        self.assertTrue(body["ok"])
        self.assertIsNone(body.get("invoice"))
        tables = {t["name"]: t for t in body["tables"]}
        self.assertTrue(tables["T2"].get("mergePrimary"))
        self.assertEqual(tables["T2"].get("mergeGroupId"), tables["T1"].get("mergeGroupId"))
        self.assertFalse(tables["T1"].get("hiddenInMerge"))
        self.assertEqual(tables["T2"].get("displayName"), "T2")
        self.assertIn("T1", tables["T2"].get("mergedNames") or [])
        self.assertIn("T2", tables["T2"].get("mergedNames") or [])
        self.assertEqual(self._floor_status("T1"), "available")
        self.assertEqual(self._floor_status("T2"), "available")

    def test_merge_tables_visual_join_empty_onto_floor_occupied_without_bill(self):
        # T3 starts occupied on the floor with no open bill in setUp.
        res = self.client.post(
            "/point-of-sale/api/invoices/merge-tables",
            json={"from_table": "T1", "to_table": "T3"},
        )
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        body = res.get_json()
        self.assertTrue(body["ok"])
        tables = {t["name"]: t for t in body["tables"]}
        self.assertTrue(tables["T3"].get("mergePrimary"))
        self.assertEqual(tables["T3"].get("mergeGroupId"), tables["T1"].get("mergeGroupId"))
        self.assertFalse(tables["T1"].get("hiddenInMerge"))

    def test_merge_tables_onto_empty_available_destination(self):
        src = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload("ORD-2607-Merge-04", "T1"),
        )
        self.assertEqual(src.status_code, 200)
        src_id = src.get_json()["invoice"]["id"]
        self.assertEqual(self._floor_status("T1"), "occupied")
        self.assertEqual(self._floor_status("T2"), "available")

        res = self.client.post(
            "/point-of-sale/api/invoices/merge-tables",
            json={"from_table": "T1", "to_table": "T2"},
        )
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        body = res.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["invoice"]["id"], src_id)
        self.assertEqual((body["invoice"].get("table_label") or body["invoice"].get("table")), "T2")
        self.assertEqual(self._floor_status("T1"), "available")
        self.assertEqual(self._floor_status("T2"), "occupied")

        old = self.client.get("/point-of-sale/api/invoices/by-table?table=T1")
        self.assertIsNone(old.get_json()["invoice"])
        new = self.client.get("/point-of-sale/api/invoices/by-table?table=T2")
        self.assertIsNotNone(new.get_json()["invoice"])
        self.assertEqual(new.get_json()["invoice"]["id"], src_id)

    def test_merge_tables_rejects_same_table(self):
        saved = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload("ORD-2607-Merge-05", "T1"),
        )
        self.assertEqual(saved.status_code, 200)
        res = self.client.post(
            "/point-of-sale/api/invoices/merge-tables",
            json={"from_table": "T1", "to_table": "T1"},
        )
        self.assertEqual(res.status_code, 400)
        body = res.get_json()
        self.assertFalse(body["ok"])
        self.assertIn("different", body["error"].lower())

    def test_merge_tables_creates_visual_group_on_floor(self):
        first = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload("ORD-2607-Merge-Vis-01", "T1"),
        )
        second = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload("ORD-2607-Merge-Vis-02", "T2"),
        )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)

        res = self.client.post(
            "/point-of-sale/api/invoices/merge-tables",
            json={"from_table": "T1", "to_table": "T2"},
        )
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        body = res.get_json()
        tables = {t["name"]: t for t in body["tables"]}
        self.assertTrue(tables["T2"].get("mergePrimary"))
        self.assertTrue(tables["T2"].get("mergeGroupId"))
        self.assertEqual(tables["T2"].get("mergeGroupId"), tables["T1"].get("mergeGroupId"))
        self.assertFalse(tables["T1"].get("mergePrimary"))
        self.assertFalse(tables["T1"].get("hiddenInMerge"))
        self.assertFalse(tables["T2"].get("hiddenInMerge"))
        self.assertEqual(tables["T1"].get("displayName"), "T1")
        self.assertEqual(tables["T2"].get("displayName"), "T2")
        self.assertEqual(tables["T2"].get("mergeLabel"), "Merged bill")
        self.assertEqual(tables["T1"].get("mergeLabel"), "Bill: T2")
        self.assertEqual(tables["T1"].get("billingTableName"), "T2")
        names = [n.lower() for n in (tables["T2"].get("mergedNames") or [])]
        self.assertIn("t1", names)
        self.assertIn("t2", names)
        self.assertEqual(tables["T2"].get("mergedSeats"), 8)

    def test_unmerge_tables_splits_visual_group(self):
        self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload("ORD-2607-Merge-Vis-03", "T1"),
        )
        self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload("ORD-2607-Merge-Vis-04", "T2"),
        )
        merged = self.client.post(
            "/point-of-sale/api/invoices/merge-tables",
            json={"from_table": "T1", "to_table": "T2"},
        )
        self.assertEqual(merged.status_code, 200)

        res = self.client.post(
            "/point-of-sale/api/floor/unmerge-tables",
            json={"table": "T2"},
        )
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        body = res.get_json()
        self.assertTrue(body["ok"])
        tables = {t["name"]: t for t in body["tables"]}
        self.assertFalse(tables["T1"].get("mergeGroupId"))
        self.assertFalse(tables["T2"].get("mergeGroupId"))
        self.assertFalse(tables["T1"].get("hiddenInMerge"))
        self.assertFalse(tables["T2"].get("hiddenInMerge"))
        # Bill stays on destination T2 after unmerge.
        self.assertEqual(self._floor_status("T2"), "occupied")
        inv = self.client.get("/point-of-sale/api/invoices/by-table?table=T2")
        self.assertIsNotNone(inv.get_json()["invoice"])

    # -- Unsettled invoice Edit / Cancel (Cancellation Access) ---------------

    def test_reopen_edit_requires_cancellation_access(self):
        saved = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload(
                "ORD-2607-Reopen-01",
                "T1",
                kot_send=True,
                customerBill=True,
                lines=[
                    {
                        "uid": "1",
                        "menuId": None,
                        "name": "Filter Coffee",
                        "variant": "",
                        "rate": 100,
                        "qty": 2,
                        "kotSentQty": 2,
                    }
                ],
            ),
        )
        self.assertEqual(saved.status_code, 200, saved.get_data(as_text=True))
        invoice_id = saved.get_json()["invoice"]["id"]
        self.assertTrue(saved.get_json()["invoice"].get("customer_bill_sent"))

        locked = dict(self.user)
        locked["is_admin"] = False
        locked["dashboard_access"] = {"point_of_sale"}
        with mock.patch.object(self.app_mod, "get_current_user", return_value=locked):
            denied = self.client.post(f"/point-of-sale/api/invoices/{invoice_id}/reopen-edit")
        self.assertEqual(denied.status_code, 403)
        self.assertIn("Cancellation Access", denied.get_json()["error"])

        unlocked = dict(self.user)
        unlocked["is_admin"] = False
        unlocked["dashboard_access"] = {"point_of_sale", "cancellation_access"}
        with mock.patch.object(self.app_mod, "get_current_user", return_value=unlocked):
            ok = self.client.post(f"/point-of-sale/api/invoices/{invoice_id}/reopen-edit")
        self.assertEqual(ok.status_code, 200, ok.get_data(as_text=True))
        body = ok.get_json()
        self.assertTrue(body["ok"])
        self.assertFalse(body["invoice"].get("customer_bill_sent"))

    def test_cancel_unsettled_requires_cancellation_access(self):
        saved = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload("ORD-2607-Cancel-01", "T1", kot_send=True),
        )
        self.assertEqual(saved.status_code, 200, saved.get_data(as_text=True))
        invoice_id = saved.get_json()["invoice"]["id"]

        locked = dict(self.user)
        locked["is_admin"] = False
        locked["dashboard_access"] = {"point_of_sale"}
        with mock.patch.object(self.app_mod, "get_current_user", return_value=locked):
            denied = self.client.post(f"/point-of-sale/api/invoices/{invoice_id}/delete")
        self.assertEqual(denied.status_code, 403)

        unlocked = dict(self.user)
        unlocked["is_admin"] = False
        unlocked["dashboard_access"] = {"point_of_sale", "cancellation_access"}
        with mock.patch.object(self.app_mod, "get_current_user", return_value=unlocked):
            missing_reason = self.client.post(
                f"/point-of-sale/api/invoices/{invoice_id}/delete",
                json={},
            )
            self.assertEqual(missing_reason.status_code, 400)
            ok = self.client.post(
                f"/point-of-sale/api/invoices/{invoice_id}/delete",
                json={"reason": "Guest left"},
            )
        self.assertEqual(ok.status_code, 200, ok.get_data(as_text=True))
        body = ok.get_json()
        self.assertTrue(body["ok"])
        # Non-provisional ORD-* numbers are kept as cancelled (not soft-deleted).
        self.assertEqual(body.get("mode"), "cancelled")
        got = self.client.get(f"/point-of-sale/api/invoices/{invoice_id}")
        self.assertEqual(got.status_code, 200)
        self.assertEqual(got.get_json()["invoice"]["status"], "cancelled")
        self.assertEqual(got.get_json()["invoice"]["cancel_reason"], "Guest left")
        self.assertEqual(got.get_json()["invoice"]["payment_mode_label"], "Cancelled")

    def test_cancel_issued_number_is_reserved_and_excluded_from_sales(self):
        from datetime import date

        today = date.today().isoformat()
        draft = "SPC/AAAAAA/26-27"
        bill = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload(
                draft,
                "",
                order_type="takeaway",
                customerBill=True,
                orderDate=today,
                savedAt=today + " 12:00:00",
                lines=[
                    {
                        "uid": "1",
                        "menuId": None,
                        "name": "Filter Coffee",
                        "variant": "",
                        "rate": 100,
                        "qty": 2,
                        "kotSentQty": 0,
                    }
                ],
            ),
        )
        self.assertEqual(bill.status_code, 200, bill.get_data(as_text=True))
        invoice = bill.get_json()["invoice"]
        order_no = invoice["order_no"]
        invoice_id = invoice["id"]
        self.assertTrue(order_no.startswith("SPC/"))
        self.assertTrue(invoice.get("customer_bill_sent"))

        cancel = self.client.post(
            f"/point-of-sale/api/invoices/{invoice_id}/delete",
            json={"reason": "Duplicate bill"},
        )
        self.assertEqual(cancel.status_code, 200, cancel.get_data(as_text=True))
        cancel_body = cancel.get_json()
        self.assertEqual(cancel_body.get("mode"), "cancelled")
        self.assertEqual(cancel_body["invoice"]["status"], "cancelled")
        self.assertEqual(cancel_body["invoice"]["order_no"], order_no)

        today_res = self.client.get("/point-of-sale/api/today-invoices")
        self.assertEqual(today_res.status_code, 200)
        payload = today_res.get_json()
        cancelled_rows = [
            inv
            for inv in (payload.get("invoices") or [])
            if str(inv.get("id")) == str(invoice_id)
        ]
        self.assertEqual(len(cancelled_rows), 1)
        self.assertEqual(cancelled_rows[0]["status"], "cancelled")
        self.assertEqual(payload.get("sales_total"), 0)
        self.assertEqual(payload.get("sales_count"), 0)
        self.assertEqual(payload.get("unsettled_count"), 0)

        next_bill = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload(
                "SPC/BBBBBB/26-27",
                "",
                order_type="takeaway",
                customerBill=True,
                orderDate=today,
                savedAt=today + " 13:00:00",
                lines=[
                    {
                        "uid": "1",
                        "menuId": None,
                        "name": "Tea",
                        "variant": "",
                        "rate": 50,
                        "qty": 1,
                        "kotSentQty": 0,
                    }
                ],
            ),
        )
        self.assertEqual(next_bill.status_code, 200, next_bill.get_data(as_text=True))
        next_no = next_bill.get_json()["invoice"]["order_no"]
        self.assertNotEqual(next_no, order_no)
        self.assertRegex(next_no, r"^SPC/\d{2}-\d{2}/\d+$")
        first_n = int(order_no.rsplit("/", 1)[-1])
        second_n = int(next_no.rsplit("/", 1)[-1])
        self.assertEqual(second_n, first_n + 1)

    def test_cancel_provisional_draft_is_soft_deleted(self):
        draft = "SPC/CCCCCC/26-27"
        saved = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload(draft, "", order_type="takeaway"),
        )
        self.assertEqual(saved.status_code, 200, saved.get_data(as_text=True))
        invoice = saved.get_json()["invoice"]
        self.assertEqual(invoice["order_no"], draft)
        invoice_id = invoice["id"]

        cancel = self.client.post(
            f"/point-of-sale/api/invoices/{invoice_id}/delete",
            json={"reason": "Duplicate bill"},
        )
        self.assertEqual(cancel.status_code, 200, cancel.get_data(as_text=True))
        self.assertEqual(cancel.get_json().get("mode"), "deleted")
        missing = self.client.get(f"/point-of-sale/api/invoices/{invoice_id}")
        self.assertEqual(missing.status_code, 404)

    def test_cancel_settled_invoice_rejected(self):
        saved = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload("ORD-2607-Cancel-02", "T1", kot_send=True),
        )
        invoice_id = saved.get_json()["invoice"]["id"]
        close = self.client.post(f"/point-of-sale/api/invoices/{invoice_id}/close")
        self.assertEqual(close.status_code, 200, close.get_data(as_text=True))

        res = self.client.post(
            f"/point-of-sale/api/invoices/{invoice_id}/delete",
            json={"reason": "Should fail"},
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("Settled", res.get_json()["error"])

    def test_generated_provisional_shaped_number_never_soft_deleted(self):
        """customer_bill_sent forces cancel (keep row) even if order_no looks draft-like."""
        from datetime import date

        today = date.today().isoformat()
        draft = "SPC/BILL01/26-27"
        bill = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload(
                draft,
                "",
                order_type="takeaway",
                customerBill=True,
                orderDate=today,
                savedAt=today + " 12:00:00",
            ),
        )
        self.assertEqual(bill.status_code, 200, bill.get_data(as_text=True))
        invoice = bill.get_json()["invoice"]
        self.assertTrue(invoice.get("customer_bill_sent"))
        invoice_id = invoice["id"]
        # Force a provisional-shaped number while leaving the generate flag on.
        conn = db_mod.get_db()
        try:
            conn.execute(
                "UPDATE pos_invoices SET order_no = ? WHERE id = ?",
                (draft, invoice_id),
            )
            conn.commit()
        finally:
            conn.close()

        cancel = self.client.post(
            f"/point-of-sale/api/invoices/{invoice_id}/delete",
            json={"reason": "Guest cancelled"},
        )
        self.assertEqual(cancel.status_code, 200, cancel.get_data(as_text=True))
        body = cancel.get_json()
        self.assertEqual(body.get("mode"), "cancelled")
        got = self.client.get(f"/point-of-sale/api/invoices/{invoice_id}")
        self.assertEqual(got.status_code, 200)
        inv = got.get_json()["invoice"]
        self.assertEqual(inv["status"], "cancelled")
        self.assertEqual(inv["order_no"], draft)
        self.assertEqual(inv["cancel_reason"], "Guest cancelled")


if __name__ == "__main__":
    unittest.main()
