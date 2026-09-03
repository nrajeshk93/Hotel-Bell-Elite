"""Same-day hotel settlement edit with POS 4-hour guardrails."""

import json
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta
from unittest import mock

import db as db_mod


class SettlementEditWindowTests(unittest.TestCase):
    def test_window_open_at_3h59_closed_at_4h01(self):
        now = datetime(2026, 9, 3, 15, 0, 0)
        self.assertTrue(
            db_mod.settlement_edit_open("2026-09-03 11:01:00", now=now)
        )
        self.assertFalse(
            db_mod.settlement_edit_open("2026-09-03 10:59:00", now=now)
        )
        self.assertFalse(db_mod.settlement_edit_open("", now=now))
        self.assertFalse(
            db_mod.settlement_edit_open("2026-09-03 16:00:00", now=now)
        )

    def test_pos_and_hotel_both_allow_same_day_only(self):
        now = datetime(2026, 9, 3, 15, 0, 0)
        pos_ok = {
            "status": "closed",
            "settled_at": "2026-09-03 10:00:00",
            "payment_modes": ["cash"],
        }
        pos_old = {
            "status": "closed",
            "settled_at": "2026-09-02 23:59:00",
            "payment_modes": ["cash"],
        }
        self.assertTrue(db_mod.pos_invoice_can_resettle(pos_ok, now=now))
        self.assertFalse(db_mod.pos_invoice_can_resettle(pos_old, now=now))
        hotel_ok = {
            "status": "settled",
            "balance_amount": 0,
            "updated_at": "2026-09-03 10:00:00",
            "room": {
                "stay": {
                    "payments": [{"at": "2026-09-03 10:00:00", "amount": 100}]
                }
            },
        }
        hotel_old = {
            "status": "settled",
            "balance_amount": 0,
            "updated_at": "2026-09-02 23:59:00",
            "room": {
                "stay": {
                    "payments": [{"at": "2026-09-02 23:59:00", "amount": 100}]
                }
            },
        }
        self.assertTrue(db_mod.hotel_invoice_can_resettle(hotel_ok, now=now))
        self.assertFalse(db_mod.hotel_invoice_can_resettle(hotel_old, now=now))


class HotelSettlementEditTests(unittest.TestCase):
    @staticmethod
    def _stay_window(nights=1, end_offset_days=1):
        nights = max(1, int(nights or 1))
        check_out = datetime.now().date() + timedelta(days=max(1, int(end_offset_days or 1)))
        check_in = check_out - timedelta(days=nights)
        return check_in.isoformat(), check_out.isoformat()

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

    def _checkin_walkin(self, room_id="room-101"):
        check_in, check_out = self._stay_window(nights=1)
        res = self.client.put(
            f"/hotel/api/rooms/{room_id}",
            json={
                "action": "checkin",
                "stay": {
                    "firstName": "Ravi",
                    "lastName": "Nair",
                    "mobile": "9000000999",
                    "checkInDate": check_in,
                    "checkOutDate": check_out,
                    "nights": 1,
                    "roomRate": 2000,
                    "advancePaid": 0,
                },
            },
        )
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        return res.get_json()["room"]

    def _settle_walkin(self, room_id="room-101"):
        room = self._checkin_walkin(room_id)
        gen = self.client.put(
            f"/hotel/api/rooms/{room_id}",
            json={
                "action": "generate_invoice",
                "payment": {"amount": 200, "method": "cash"},
            },
        )
        self.assertEqual(gen.status_code, 200, gen.get_data(as_text=True))
        inv_no = gen.get_json()["room"]["stay"]["invoiceNumber"]
        self.assertTrue(inv_no)
        api = self.client.get(f"/hotel/invoice-ledger/api/{inv_no}")
        self.assertEqual(api.status_code, 200)
        due = float(api.get_json()["invoice"]["balance_amount"])
        self.assertGreater(due, 0)
        settle = self.client.post(
            f"/hotel/invoice-ledger/api/{inv_no}/settle",
            json={"payment_splits": [{"method": "cash", "amount": due}]},
        )
        self.assertEqual(settle.status_code, 200, settle.get_data(as_text=True))
        return inv_no, room_id

    def _set_hotel_settlement_stamp(self, invoice_number, stamp):
        stamp = str(stamp)
        conn = db_mod.get_db()
        try:
            layout = db_mod.get_hotel_rooms_layout(conn)
            rooms = list(layout.get("rooms") or [])
            for room in rooms:
                stay = room.get("stay") if isinstance(room.get("stay"), dict) else None
                if not stay:
                    continue
                inv = str(stay.get("invoiceNumber") or stay.get("invoice_number") or "")
                if inv != invoice_number:
                    continue
                for pay in list(stay.get("payments") or []):
                    if isinstance(pay, dict):
                        pay["at"] = stamp
                stay["updatedAt"] = stamp
                room["stay"] = stay
            db_mod.save_hotel_rooms_layout(
                conn, layout.get("floors") or [], rooms
            )
            row = conn.execute(
                "SELECT payload_json FROM hotel_room_invoices WHERE invoice_number = ?",
                (invoice_number,),
            ).fetchone()
            if row:
                try:
                    blob = json.loads(row["payload_json"] or "{}")
                except (TypeError, ValueError, json.JSONDecodeError):
                    blob = {}
                if not isinstance(blob, dict):
                    blob = {}
                def _age_pays(container):
                    if not isinstance(container, dict):
                        return
                    for pay in list(container.get("payments") or []):
                        if isinstance(pay, dict):
                            pay["at"] = stamp
                    container["updatedAt"] = stamp
                    stay = container.get("stay")
                    if isinstance(stay, dict):
                        _age_pays(stay)
                    room = container.get("room")
                    if isinstance(room, dict):
                        _age_pays(room)
                _age_pays(blob)
                conn.execute(
                    """UPDATE hotel_room_invoices
                       SET payload_json = ?, updated_at = ?
                       WHERE invoice_number = ?""",
                    (json.dumps(blob), stamp, invoice_number),
                )
            conn.commit()
        finally:
            conn.close()
        return stamp

    def _age_hotel_settlement(self, invoice_number, hours=5):
        stamp = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
        return self._set_hotel_settlement_stamp(invoice_number, stamp)

    def test_hotel_settlement_can_be_edited_until_end_of_day(self):
        inv_no, _room_id = self._settle_walkin()
        page = self.client.get("/hotel/invoice-ledger")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        block = html.split(f'data-invoice-number="{inv_no}"', 1)[1].split("</tr>", 1)[0]
        self.assertIn("hil-resettle-btn", block)
        self.assertNotIn("hil-edit-btn", block)

        detail = self.client.get(f"/hotel/invoice-ledger/api/{inv_no}").get_json()
        estimated = float(detail["invoice"]["estimated_total"])
        self.assertGreater(estimated, 0)
        upi = round(estimated / 2, 2)
        card = round(estimated - upi, 2)
        again = self.client.post(
            f"/hotel/invoice-ledger/api/{inv_no}/settle",
            json={
                "payment_splits": [
                    {"method": "upi", "amount": upi},
                    {"method": "card", "amount": card},
                ]
            },
        )
        self.assertEqual(again.status_code, 200, again.get_data(as_text=True))
        methods = sorted(
            (p.get("method") or p.get("payment_method") or "")
            for p in (again.get_json().get("payments") or [])
        )
        self.assertEqual(methods, ["card", "upi"])

        self._age_hotel_settlement(inv_no, hours=5)
        same_day = self.client.post(
            f"/hotel/invoice-ledger/api/{inv_no}/settle",
            json={"payment_splits": [{"method": "cash", "amount": estimated}]},
        )
        self.assertEqual(same_day.status_code, 200, same_day.get_data(as_text=True))

        same_day_page = self.client.get("/hotel/invoice-ledger").get_data(as_text=True)
        same_day_block = same_day_page.split(f'data-invoice-number="{inv_no}"', 1)[1].split(
            "</tr>", 1
        )[0]
        self.assertIn("hil-resettle-btn", same_day_block)

        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d 23:59:00")
        self._set_hotel_settlement_stamp(inv_no, yesterday)
        blocked = self.client.post(
            f"/hotel/invoice-ledger/api/{inv_no}/settle",
            json={"payment_splits": [{"method": "cash", "amount": estimated}]},
        )
        self.assertEqual(blocked.status_code, 400)
        self.assertIn(
            "already settled",
            (blocked.get_json() or {}).get("error", "").lower(),
        )

        aged_page = self.client.get("/hotel/invoice-ledger").get_data(as_text=True)
        aged_block = aged_page.split(f'data-invoice-number="{inv_no}"', 1)[1].split(
            "</tr>", 1
        )[0]
        self.assertNotIn("hil-resettle-btn", aged_block)

    def test_hotel_clerk_can_edit_same_day_settlement(self):
        inv_no, _room_id = self._settle_walkin("room-102")
        detail = self.client.get(f"/hotel/invoice-ledger/api/{inv_no}").get_json()
        estimated = float(detail["invoice"]["estimated_total"])
        self._age_hotel_settlement(inv_no, hours=5)
        clerk = {
            "id": self.admin_id,
            "username": "hotelfo",
            "full_name": "Front Office",
            "is_admin": False,
            "is_active": True,
            "dashboard_access": {"hotel_rooms"},
            "stores_access": set(),
            "sales_analytics_access": set(),
            "user_access": set(),
            "payroll_access": set(),
            "accounts_access": set(),
        }
        with mock.patch.object(self.app_mod, "get_current_user", return_value=clerk):
            again = self.client.post(
                f"/hotel/invoice-ledger/api/{inv_no}/settle",
                json={"payment_splits": [{"method": "upi", "amount": estimated}]},
            )
            page = self.client.get("/hotel/invoice-ledger")
        self.assertEqual(again.status_code, 200, again.get_data(as_text=True))
        html = page.get_data(as_text=True)
        block = html.split(f'data-invoice-number="{inv_no}"', 1)[1].split("</tr>", 1)[0]
        self.assertIn("hil-resettle-btn", block)
        self.assertNotIn("hil-edit-btn", block)

    def test_cash_resettlement_updates_hotel_actual_cash_and_cash_ledger(self):
        inv_no, _room_id = self._settle_walkin("room-103")
        detail = self.client.get(f"/hotel/invoice-ledger/api/{inv_no}").get_json()
        invoice = detail["invoice"]
        sales_day = str(invoice["invoice_generated_at"])[:10]
        estimated = float(invoice["estimated_total"])

        self.app_mod.upsert_sales_row(
            self.user,
            self.app_mod.DEFAULT_COMPANY,
            self.app_mod.OUTLET_HOTEL,
            sales_day,
            self.app_mod.build_hotel_sales_entry_values({"actual_cash": estimated}),
            {},
            {},
        )

        page = self.client.get("/hotel/invoice-ledger")
        block = page.get_data(as_text=True).split(f'data-invoice-number="{inv_no}"', 1)[1].split(
            "</tr>", 1
        )[0]
        self.assertIn("hil-resettle-btn", block)

        resettle = self.client.post(
            f"/hotel/invoice-ledger/api/{inv_no}/settle",
            json={"payment_splits": [{"method": "upi", "amount": estimated}]},
        )
        self.assertEqual(resettle.status_code, 200, resettle.get_data(as_text=True))
        payload = resettle.get_json()
        self.assertEqual(payload["invoice"]["payment_modes"], ["upi"])
        self.assertAlmostEqual(float(payload["invoice"]["payment_amounts"]["cash"]), 0.0, places=2)
        self.assertAlmostEqual(float(payload["invoice"]["payment_amounts"]["upi"]), estimated, places=2)

        saved = self.app_mod.load_sales_row(
            self.app_mod.DEFAULT_COMPANY,
            self.app_mod.OUTLET_HOTEL,
            sales_day,
        )
        self.assertAlmostEqual(float(saved["sales_entry_values"]["actual_cash"]), 0.0, places=2)

        conn = db_mod.get_db()
        try:
            entries = self.app_mod._build_cash_ledger_entries(
                conn,
                self.app_mod.DEFAULT_COMPANY,
                date.fromisoformat(sales_day),
                date.fromisoformat(sales_day),
                location=self.app_mod.OUTLET_HOTEL,
            )
        finally:
            conn.close()
        totals = self.app_mod._cash_ledger_totals(entries)
        self.assertAlmostEqual(float(totals["sales_total"]), 0.0, places=2)


if __name__ == "__main__":
    unittest.main()
