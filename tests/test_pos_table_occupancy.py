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

    def test_kot_tokens_mark_customer_bill_sent_after_send_to_customer(self):
        """After Send to Customer (customerBill), token stays listed but flagged.

        UI uses customer_bill_sent to disable Resend all / Resend selected.
        Tokens are still returned so the modal can show “Bill sent — resend disabled”.
        """
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
        self.assertEqual(after["token_count"], 1)
        row = after["tables"][0]
        self.assertEqual(row["name"], "T1")
        self.assertTrue(row["customer_bill_sent"])
        self.assertTrue(row.get("customer_bill_at"))
        self.assertEqual(row["sent_qty"], 2)
        self.assertTrue(row["lines"])

        # Flag is sticky: a later plain save must not clear it.
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
        self.assertEqual(again.status_code, 200, again.get_data(as_text=True))
        sticky = self.client.get("/point-of-sale/api/kot-tokens").get_json()
        self.assertTrue(sticky["tables"][0]["customer_bill_sent"])

    def test_non_admin_cannot_reduce_or_remove_kitchen_sent_lines(self):
        save = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload("ORD-2607-0080", "T1", kot_send=True),
        )
        self.assertEqual(save.status_code, 200, save.get_data(as_text=True))

        conn = db_mod.get_db()
        try:
            # Non-admin cannot drop qty below kitchen-sent amount.
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
                    actor_is_admin=False,
                )
            self.assertIn("administrator", str(cut.exception).lower())
            conn.rollback()

            # Non-admin cannot remove the kitchen-sent line.
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
                    actor_is_admin=False,
                )
            self.assertIn("administrator", str(removed.exception).lower())
            conn.rollback()

            # Administrator can reduce after KOT.
            saved = db_mod.save_pos_invoice(
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
            )
            conn.commit()
            self.assertEqual(saved["lines"][0]["qty"], 1)
        finally:
            conn.close()
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


if __name__ == "__main__":
    unittest.main()
