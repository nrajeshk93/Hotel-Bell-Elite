"""Hotel Credit page — agency collections from Invoice Ledger Credit settlements."""

import os
import tempfile
import unittest
from datetime import date, datetime, timedelta
from unittest import mock

import db as db_mod


class HotelCreditTests(unittest.TestCase):
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
        self._get_user_patch = mock.patch.object(app_mod, "get_current_user", return_value=self.user)
        self._get_user_patch.start()

    def tearDown(self):
        self._get_user_patch.stop()
        db_mod.DATABASE_PATH = self._orig_path
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def _checkin_agency(self, room_id, agency, first="Asha", last="Iyer", mobile="9000000077"):
        check_in, check_out = self._stay_window(nights=1)
        res = self.client.put(
            f"/hotel/api/rooms/{room_id}",
            json={
                "action": "checkin",
                "stay": {
                    "firstName": first,
                    "lastName": last,
                    "mobile": mobile,
                    "checkInDate": check_in,
                    "checkOutDate": check_out,
                    "nights": 1,
                    "roomRate": 2000,
                    "advancePaid": 0,
                    "agencyName": agency,
                    "agencyBilling": True,
                },
            },
        )
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        return res.get_json()["room"]

    def _credit_invoice(self, room_id, amount=None):
        room = self.client.get(f"/hotel/api/rooms/{room_id}").get_json()["room"]
        balance = float(room["stay"]["balanceAmount"])
        pay = round(float(amount if amount is not None else balance), 2)
        res = self.client.put(
            f"/hotel/api/rooms/{room_id}",
            json={
                "action": "generate_invoice",
                "payment_splits": [{"payment_method": "credit", "amount": pay}],
            },
        )
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        stay = res.get_json()["room"]["stay"]
        inv_no = stay["invoiceNumber"]
        self.assertTrue(inv_no)
        return inv_no, pay

    def _credit_row(self, invoice_number):
        conn = db_mod.get_db()
        try:
            row = conn.execute(
                """SELECT id, invoice_number, agency_name, credit_amount
                   FROM hotel_invoice_credits WHERE invoice_number = ?""",
                (invoice_number,),
            ).fetchone()
        finally:
            conn.close()
        self.assertIsNotNone(row, f"missing hotel credit for {invoice_number}")
        return dict(row)

    def test_sidebar_and_outstanding_list_credit_settlements(self):
        inv_no, amount = self._credit_invoice(
            self._checkin_agency("room-101", "Travel Desk Co")["id"]
        )
        page = self.client.get("/hotel/credit")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn("de-nav-hotel-credit", html)
        self.assertIn("de-nav-hotel-invoice-ledger", html)
        self.assertIn('id="de-nav-hotel-credit"', html)
        self.assertIn("is-active", html)
        self.assertIn("Outstanding Credit", html)
        self.assertIn("Agency", html)
        self.assertIn("Travel Desk Co", html)
        self.assertIn(inv_no, html)
        self.assertIn("Clear Payment", html)
        self.assertNotIn('aria-label="Meat category balance"', html)
        self.assertNotIn('id="credit-payment-kind-tabs"', html)
        row = self._credit_row(inv_no)
        self.assertAlmostEqual(float(row["credit_amount"]), amount, places=2)

    def test_credit_settlement_updates_guest_credit_sales_entry(self):
        _inv_no, amount = self._credit_invoice(
            self._checkin_agency("room-101", "Travel Desk Co")["id"]
        )
        today = date.today().isoformat()
        conn = db_mod.get_db()
        try:
            bundle = self.app_mod._load_outlet_entry_bundle(
                conn,
                self.user,
                self.app_mod.DEFAULT_COMPANY,
                self.app_mod.OUTLET_HOTEL,
                today,
                today,
                overlay_invoices=True,
            )
        finally:
            conn.close()
        self.assertAlmostEqual(bundle["sales_entry_values"]["room_credit"], amount, places=2)
        page = self.client.get(f"/hotel/sales-update?date={today}")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn('data-sales-entry="room_credit"', html)
        self.assertIn(f'value="{bundle["sales_entry_values"]["room_credit"]}"', html)
        self.assertIn("Back Office Receipt", html)
        self.assertIn('data-sales-entry="bor"', html)

    def test_ledger_settle_credit_appears_on_credit_page(self):
        room = self._checkin_agency("room-101", "Coastal Tours")
        gen = self.client.put(
            "/hotel/api/rooms/room-101",
            json={
                "action": "generate_invoice",
                "payment": {"amount": 200, "method": "cash"},
            },
        )
        self.assertEqual(gen.status_code, 200, gen.get_data(as_text=True))
        inv_no = gen.get_json()["room"]["stay"]["invoiceNumber"]
        api = self.client.get(f"/hotel/invoice-ledger/api/{inv_no}")
        self.assertEqual(api.status_code, 200)
        balance = float(api.get_json()["invoice"]["balance_amount"])
        self.assertGreater(balance, 0)
        settle = self.client.post(
            f"/hotel/invoice-ledger/api/{inv_no}/settle",
            json={"payment_splits": [{"method": "credit", "amount": balance}]},
        )
        self.assertEqual(settle.status_code, 200, settle.get_data(as_text=True))
        html = self.client.get("/hotel/credit").get_data(as_text=True)
        self.assertIn(inv_no, html)
        self.assertIn("Coastal Tours", html)
        self.assertIn("/hotel/credit/export", html)
        self.assertIn(">Export</a>", html)

        export = self.client.get("/hotel/credit/export?view=outstanding")
        self.assertEqual(export.status_code, 200)
        self.assertIn(
            "spreadsheetml.sheet",
            export.headers.get("Content-Type", ""),
        )
        self.assertTrue(
            (export.headers.get("Content-Disposition") or "").startswith("attachment")
        )

    def test_partial_and_multi_invoice_payment_same_agency(self):
        inv_a, amount_a = self._credit_invoice(
            self._checkin_agency("room-101", "Travel Desk Co", mobile="9000000101")["id"]
        )
        inv_b, amount_b = self._credit_invoice(
            self._checkin_agency(
                "room-102", "Travel Desk Co", first="Ravi", last="Menon", mobile="9000000102"
            )["id"]
        )
        row_a = self._credit_row(inv_a)
        row_b = self._credit_row(inv_b)
        partial = round(min(amount_a, 250.0), 2)
        created = self.client.post(
            "/hotel/credit/create",
            json={
                "payment_date": date.today().isoformat(),
                "payment_method": "cash",
                "allocations": [
                    {"expense_id": row_a["id"], "amount": partial},
                    {"expense_id": row_b["id"], "amount": amount_b},
                ],
            },
        )
        self.assertEqual(created.status_code, 200, created.get_data(as_text=True))
        payload = created.get_json()
        self.assertTrue(payload["ok"])
        payment_id = payload["payment"]["id"]
        self.assertAlmostEqual(float(payload["payment"]["total_amount"]), partial + amount_b, places=2)

        remaining = round(amount_a - partial, 2)
        html = self.client.get("/hotel/credit").get_data(as_text=True)
        self.assertIn(inv_a, html)
        self.assertNotIn(inv_b, html)

        over = self.client.post(
            "/hotel/credit/create",
            json={
                "payment_date": date.today().isoformat(),
                "payment_method": "upi",
                "allocations": [{"expense_id": row_a["id"], "amount": remaining + 1}],
            },
        )
        self.assertEqual(over.status_code, 400)

        finish = self.client.post(
            "/hotel/credit/create",
            json={
                "payment_date": date.today().isoformat(),
                "payment_method": "upi",
                "allocations": [{"expense_id": row_a["id"], "amount": remaining}],
            },
        )
        self.assertEqual(finish.status_code, 200, finish.get_data(as_text=True))
        outstanding = self.client.get("/hotel/credit").get_data(as_text=True)
        self.assertNotIn(inv_a, outstanding)

        history = self.client.get("/hotel/credit?view=history")
        self.assertEqual(history.status_code, 200)
        history_html = history.get_data(as_text=True)
        self.assertIn("Payment History", history_html)
        self.assertIn(inv_a, history_html)
        self.assertIn(inv_b, history_html)

        reverted = self.client.post(
            "/hotel/credit/delete",
            json={"payment_id": payment_id},
        )
        self.assertEqual(reverted.status_code, 200, reverted.get_data(as_text=True))
        restored = self.client.get("/hotel/credit").get_data(as_text=True)
        self.assertIn(inv_b, restored)

    def test_mixed_agency_payment_rejected(self):
        inv_a, amount_a = self._credit_invoice(
            self._checkin_agency("room-101", "Travel Desk Co", mobile="9000000201")["id"]
        )
        inv_b, amount_b = self._credit_invoice(
            self._checkin_agency(
                "room-102", "Hill Agency", first="Neha", last="Shah", mobile="9000000202"
            )["id"]
        )
        row_a = self._credit_row(inv_a)
        row_b = self._credit_row(inv_b)
        mixed = self.client.post(
            "/hotel/credit/create",
            json={
                "payment_date": date.today().isoformat(),
                "payment_method": "cash",
                "allocations": [
                    {"expense_id": row_a["id"], "amount": amount_a},
                    {"expense_id": row_b["id"], "amount": amount_b},
                ],
            },
        )
        self.assertEqual(mixed.status_code, 400)
        self.assertIn("agency", mixed.get_json().get("error", "").lower())

    def test_payment_mode_is_required(self):
        inv_no, amount = self._credit_invoice(
            self._checkin_agency("room-101", "Travel Desk Co")["id"]
        )
        row = self._credit_row(inv_no)
        missing = self.client.post(
            "/hotel/credit/create",
            json={
                "payment_date": date.today().isoformat(),
                "allocations": [{"expense_id": row["id"], "amount": amount}],
            },
        )
        self.assertEqual(missing.status_code, 400)
        self.assertIn("payment mode", missing.get_json().get("error", "").lower())
        html = self.client.get("/hotel/credit").get_data(as_text=True)
        self.assertIn('id="cp-payment-method"', html)
        self.assertIn('id="cp-payment-method-listbox"', html)
        self.assertIn("Select payment mode", html)
        self.assertNotIn("cp-method-toggle", html)
        self.assertRegex(html, r'id="cp-payment-method"[^>]*value=""')

    def test_bank_transfer_requires_transaction_id(self):
        inv_no, amount = self._credit_invoice(
            self._checkin_agency("room-101", "Travel Desk Co")["id"]
        )
        row = self._credit_row(inv_no)
        missing = self.client.post(
            "/hotel/credit/create",
            json={
                "payment_date": date.today().isoformat(),
                "payment_method": "bank_transfer",
                "allocations": [{"expense_id": row["id"], "amount": amount}],
            },
        )
        self.assertEqual(missing.status_code, 400)
        ok = self.client.post(
            "/hotel/credit/create",
            json={
                "payment_date": date.today().isoformat(),
                "payment_method": "bank_transfer",
                "transaction_id": "UTR123456",
                "allocations": [{"expense_id": row["id"], "amount": amount}],
            },
        )
        self.assertEqual(ok.status_code, 200, ok.get_data(as_text=True))
        detail = self.client.get(f"/hotel/credit/{ok.get_json()['payment']['id']}")
        self.assertEqual(detail.status_code, 200)
        payment = detail.get_json()["payment"]
        self.assertEqual(payment["transaction_id"], "UTR123456")
        self.assertEqual(payment["payment_method"], "bank_transfer")

    def test_cash_collection_feeds_cash_ledger(self):
        inv_no, amount = self._credit_invoice(
            self._checkin_agency("room-101", "Travel Desk Co")["id"]
        )
        row = self._credit_row(inv_no)
        created = self.client.post(
            "/hotel/credit/create",
            json={
                "payment_date": date.today().isoformat(),
                "payment_method": "cash",
                "allocations": [{"expense_id": row["id"], "amount": amount}],
            },
        )
        self.assertEqual(created.status_code, 200, created.get_data(as_text=True))
        conn = db_mod.get_db()
        try:
            entries = self.app_mod._cash_ledger_credit_rows(
                conn, "HBE", date.today(), date.today()
            )
        finally:
            conn.close()
        hotel_rows = [item for item in entries if str(item.get("id") or "").startswith("hotel-credit-")]
        self.assertEqual(len(hotel_rows), 1)
        self.assertAlmostEqual(float(hotel_rows[0]["amount"]), amount, places=2)
        self.assertIn(inv_no, hotel_rows[0]["description"])

    def test_bill_of_receipt_payment_and_split(self):
        from back_office_receipt import (
            create_back_office_receipt,
            list_pending_back_office_receipts_for_agency,
        )

        inv_no, amount = self._credit_invoice(
            self._checkin_agency("room-101", "ATPI India Pvt. Ltd")["id"]
        )
        row = self._credit_row(inv_no)
        conn = db_mod.get_db()
        try:
            db_mod.ensure_agencies_schema(conn)
            existing = conn.execute(
                "SELECT id FROM agencies WHERE lower(trim(name)) = lower(?)",
                ("ATPI India Pvt. Ltd",),
            ).fetchone()
            if existing:
                agency_id = int(existing["id"])
            else:
                agency_id = conn.execute(
                    "INSERT INTO agencies (name) VALUES (?)",
                    ("ATPI India Pvt. Ltd",),
                ).lastrowid
            receipt = create_back_office_receipt(
                conn,
                receipt_date=date.today(),
                payer_name="ATPI India Pvt. Ltd",
                agency_id=agency_id,
                amount=1200,
                payment_mode="cash",
                towards="Advance",
                user_id=self.admin_id,
            )
            conn.commit()
        finally:
            conn.close()

        page = self.client.get("/hotel/credit")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn("Back Office Receipt", html)
        self.assertIn("Split Payment", html)
        self.assertIn('id="cp-bor-receipts"', html)

        pending = self.client.get(
            f"/hotel/credit/pending-receipts?agency_name=ATPI%20India%20Pvt.%20Ltd"
        )
        self.assertEqual(pending.status_code, 200)
        receipts = pending.get_json()["receipts"]
        self.assertEqual(len(receipts), 1)
        self.assertAlmostEqual(float(receipts[0]["pending_amount"]), 1200, places=2)

        created = self.client.post(
            "/hotel/credit/create",
            json={
                "payment_date": date.today().isoformat(),
                "payment_method": "split",
                "allocations": [{"expense_id": row["id"], "amount": amount}],
                "payment_splits": [
                    {
                        "method": "bor",
                        "amount": 1200,
                        "receipt_id": receipt["id"],
                    },
                    {"method": "cash", "amount": round(amount - 1200, 2)},
                ],
            },
        )
        self.assertEqual(created.status_code, 200, created.get_data(as_text=True))
        payment = created.get_json()["payment"]
        self.assertEqual(payment["payment_method"], "split")
        self.assertIn("Back Office Receipt", payment["payment_method_label"])
        self.assertIn("Cash", payment["payment_method_label"])
        self.assertNotEqual(payment["payment_method_label"], "Split")
        self.assertAlmostEqual(
            float((payment.get("payment_amounts") or {}).get("bor") or 0), 1200, places=2
        )
        cash_amt = round(amount - 1200, 2)
        self.assertAlmostEqual(
            float((payment.get("payment_amounts") or {}).get("cash") or 0),
            cash_amt,
            places=2,
        )

        history = self.client.get("/hotel/credit?view=history")
        self.assertEqual(history.status_code, 200)
        history_html = history.get_data(as_text=True)
        self.assertIn('data-sort="pay_cash"', history_html)
        self.assertIn('data-sort="pay_bor"', history_html)
        self.assertIn(payment["payment_method_label"], history_html)

        conn = db_mod.get_db()
        try:
            left = list_pending_back_office_receipts_for_agency(
                conn, agency_id=agency_id
            )
            self.assertEqual(left, [])
        finally:
            conn.close()

        reverted = self.client.post(
            "/hotel/credit/delete",
            json={"payment_id": payment["id"]},
        )
        self.assertEqual(reverted.status_code, 200, reverted.get_data(as_text=True))
        conn = db_mod.get_db()
        try:
            restored = list_pending_back_office_receipts_for_agency(
                conn, agency_id=agency_id
            )
            self.assertEqual(len(restored), 1)
            self.assertAlmostEqual(float(restored[0]["pending_amount"]), 1200, places=2)
        finally:
            conn.close()

    def test_hotel_credit_access_gate(self):
        from workspace_access import get_endpoint_dashboard_module

        self.assertEqual(get_endpoint_dashboard_module("hotel_credit"), "hotel_rooms")
        self.assertEqual(
            get_endpoint_dashboard_module("export_hotel_credit_report"), "hotel_rooms"
        )
        self.assertEqual(
            get_endpoint_dashboard_module("create_hotel_credit_payment"), "hotel_rooms"
        )
        self.assertEqual(
            get_endpoint_dashboard_module("delete_hotel_credit_payment"), "hotel_rooms"
        )
        self.assertEqual(
            get_endpoint_dashboard_module("hotel_credit_payment_detail"), "hotel_rooms"
        )
        self.assertEqual(
            get_endpoint_dashboard_module("hotel_credit_pending_receipts"), "hotel_rooms"
        )

        viewer = {
            "id": self.admin_id,
            "username": "posonly",
            "full_name": "POS Only",
            "is_admin": False,
            "is_active": True,
            "dashboard_access": {"point_of_sale"},
            "stores_access": set(),
            "sales_analytics_access": set(),
            "user_access": set(),
            "payroll_access": set(),
            "accounts_access": set(),
        }
        with mock.patch.object(self.app_mod, "get_current_user", return_value=viewer):
            denied = self.client.get("/hotel/credit")
        self.assertIn(denied.status_code, (302, 403))

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
            allowed = self.client.get("/hotel/credit")
        self.assertEqual(allowed.status_code, 200)
        self.assertIn("Clear Payment", allowed.get_data(as_text=True))
