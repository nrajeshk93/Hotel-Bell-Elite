"""Invoice-backed Sales Update KPI aggregator tests."""

import json
import os
import tempfile
import unittest

import db as db_mod


class InvoiceSalesKpisTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db_path = self.tmp.name
        self._orig_path = db_mod.DATABASE_PATH
        db_mod.DATABASE_PATH = self.db_path
        db_mod.init_db()
        self.conn = db_mod.get_db()
        db_mod.ensure_hotel_room_invoices_schema(self.conn)
        db_mod.ensure_pos_schema(self.conn)

    def tearDown(self):
        try:
            self.conn.close()
        except Exception:
            pass
        db_mod.DATABASE_PATH = self._orig_path
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def _insert_hotel(self, *, invoice_number, generated_at, total, status="open", payments=None):
        stay = {
            "guestName": "Guest",
            "mobile": "9000000000",
            "invoiceNumber": invoice_number,
        }
        if payments:
            stay["payments"] = payments
        payload = {"id": "r101", "number": "101", "stay": stay}
        self.conn.execute(
            """
            INSERT INTO hotel_room_invoices (
                invoice_number, room_id, room_number, room_type_label,
                guest_name, booking_number, check_in_date, check_out_date,
                invoice_generated_at, estimated_total, advance_paid,
                balance_amount, status, payload_json
            ) VALUES (?, 'r101', '101', 'Deluxe', 'Guest', '',
                      '2026-04-01', '2026-04-02', ?, ?, 0, ?, ?, ?)
            """,
            (
                invoice_number,
                generated_at,
                float(total),
                float(total) if status == "open" else 0.0,
                status,
                json.dumps(payload),
            ),
        )

    def _insert_pos(
        self,
        *,
        order_no,
        outlet,
        order_date,
        grand_total,
        status="closed",
        payments=None,
        is_active=1,
    ):
        cur = self.conn.execute(
            """
            INSERT INTO pos_invoices
               (order_no, order_date, order_type, table_label, customer_name, customer_mobile,
                captain, status, outlet, subtotal, discount_amount, gst_amount, service_amount,
                tip, round_off, grand_total, saved_at, is_active)
            VALUES (?, ?, 'dine_in', 'T1', 'Guest', '', '', ?, ?, ?, 0, 0, 0, 0, 0, ?,
                    datetime('now'), ?)
            """,
            (
                order_no,
                order_date,
                status,
                outlet,
                float(grand_total),
                float(grand_total),
                int(is_active),
            ),
        )
        invoice_id = cur.lastrowid
        for pay in payments or []:
            self.conn.execute(
                """
                INSERT INTO pos_invoice_payments
                    (invoice_id, payment_date, payment_method, amount, transaction_id)
                VALUES (?, ?, ?, ?, '')
                """,
                (invoice_id, order_date, pay["method"], float(pay["amount"])),
            )
        return invoice_id

    def test_settled_ledger_only_excludes_unsettled(self):
        # Hotel open (unsettled payment) — still counts toward Hotel Total billed
        self._insert_hotel(
            invoice_number="HBE/RM/KPI/1",
            generated_at="2026-04-10 12:00:00",
            total=1000.0,
            status="open",
        )
        # Restaurant closed with UPI — digital (ledger settled)
        self._insert_pos(
            order_no="SPC/KPI/1",
            outlet=db_mod.POS_OUTLET_RESTAURANT,
            order_date="2026-04-15",
            grand_total=500.0,
            status="closed",
            payments=[{"method": "upi", "amount": 500.0}],
        )
        # Bar open unpaid — excluded from POS settled ledger
        self._insert_pos(
            order_no="BEB/KPI/1",
            outlet=db_mod.POS_OUTLET_BAR,
            order_date="2026-05-01",
            grand_total=200.0,
            status="open",
            payments=[],
        )
        # Out of range — ignored
        self._insert_hotel(
            invoice_number="HBE/RM/KPI/OUT",
            generated_at="2026-05-10 12:00:00",
            total=9999.0,
            status="settled",
            payments=[{"method": "cash", "amount": 9999.0}],
        )
        self._insert_pos(
            order_no="SPC/KPI/OUT",
            outlet=db_mod.POS_OUTLET_RESTAURANT,
            order_date="2026-03-31",
            grand_total=8888.0,
            status="closed",
            payments=[{"method": "cash", "amount": 8888.0}],
        )

        self.conn.commit()
        kpis = db_mod.aggregate_invoice_sales_kpis(
            self.conn, "2026-04-01", "2026-05-04"
        )

        # Hotel open 1000 + restaurant settled 500; bar open excluded
        self.assertEqual(kpis["actual_sales"], 1500.0)
        self.assertEqual(kpis["digital_transactions"], 500.0)
        self.assertEqual(kpis["cash"], 0.0)
        self.assertEqual(kpis["room_credit"], 0.0)
        # Hotel open has no tenders → difference gap 1000
        self.assertEqual(kpis["difference"], 1000.0)

    def test_cancelled_pos_excluded(self):
        self._insert_pos(
            order_no="SPC/KPI/CXL",
            outlet=db_mod.POS_OUTLET_RESTAURANT,
            order_date="2026-04-20",
            grand_total=750.0,
            status="cancelled",
            payments=[{"method": "cash", "amount": 750.0}],
        )
        self._insert_pos(
            order_no="SPC/KPI/OK",
            outlet=db_mod.POS_OUTLET_RESTAURANT,
            order_date="2026-04-20",
            grand_total=100.0,
            status="closed",
            payments=[{"method": "cash", "amount": 100.0}],
        )
        self.conn.commit()

        kpis = db_mod.aggregate_invoice_sales_kpis(
            self.conn, "2026-04-01", "2026-05-04"
        )
        self.assertEqual(kpis["actual_sales"], 100.0)
        self.assertEqual(kpis["cash"], 100.0)
        self.assertEqual(kpis["difference"], 0.0)

    def test_hotel_cash_payment_and_room_transfer(self):
        self._insert_hotel(
            invoice_number="HBE/RM/KPI/CASH",
            generated_at="2026-04-05 09:00:00",
            total=300.0,
            status="settled",
            payments=[{"method": "cash", "amount": 300.0}],
        )
        self._insert_pos(
            order_no="SPC/KPI/RT",
            outlet=db_mod.POS_OUTLET_BAR,
            order_date="2026-04-06",
            grand_total=150.0,
            status="closed",
            payments=[{"method": "room_transfer", "amount": 150.0}],
        )
        self.conn.commit()

        kpis = db_mod.aggregate_invoice_sales_kpis(
            self.conn, "2026-04-01", "2026-05-04"
        )
        self.assertEqual(kpis["actual_sales"], 450.0)
        self.assertEqual(kpis["cash"], 300.0)
        self.assertEqual(kpis["room_credit"], 150.0)
        self.assertEqual(kpis["digital_transactions"], 0.0)
        self.assertEqual(kpis["difference"], 0.0)


    def test_hotel_sales_entry_from_invoices_maps_unpaid_to_credit(self):
        self._insert_hotel(
            invoice_number="HBE/RM/ENTRY/1",
            generated_at="2026-04-12 10:00:00",
            total=1000.0,
            status="open",
        )
        self._insert_hotel(
            invoice_number="HBE/RM/ENTRY/2",
            generated_at="2026-04-12 11:00:00",
            total=500.0,
            status="settled",
            payments=[{"method": "upi", "amount": 500.0}],
        )
        self.conn.commit()
        entry = db_mod.hotel_sales_entry_from_invoices(self.conn, "2026-04-12")
        self.assertEqual(entry["total_sales"], 1500.0)
        self.assertEqual(entry["upi"], 500.0)
        self.assertEqual(entry["room_credit"], 1000.0)
        self.assertEqual(entry["cash"], 0.0)
        self.assertEqual(entry.get("bor", 0.0), 0.0)

    def test_hotel_sales_entry_from_invoices_maps_credit_settlement(self):
        self._insert_hotel(
            invoice_number="HBE/RM/ENTRY/CREDIT",
            generated_at="2026-04-12 12:00:00",
            total=158.0,
            status="settled",
            payments=[{"method": "credit", "amount": 158.0}],
        )
        self.conn.commit()
        entry = db_mod.hotel_sales_entry_from_invoices(self.conn, "2026-04-12")
        self.assertEqual(entry["total_sales"], 158.0)
        self.assertEqual(entry["room_credit"], 158.0)
        self.assertEqual(entry.get("bor", 0.0), 0.0)
        self.assertEqual(entry["cash"], 0.0)
        kpis = db_mod.aggregate_invoice_sales_kpis(
            self.conn, "2026-04-12", "2026-04-12", location="Hotel"
        )
        self.assertEqual(kpis["room_credit"], 158.0)
        self.assertEqual(kpis["cash"], 0.0)
        self.assertEqual(kpis["difference"], 0.0)

    def test_hotel_sales_entry_from_invoices_maps_bor_settlement(self):
        self._insert_hotel(
            invoice_number="HBE/RM/ENTRY/BOR",
            generated_at="2026-04-12 13:00:00",
            total=420.0,
            status="settled",
            payments=[{"method": "bor", "amount": 420.0, "receipt_id": 7}],
        )
        self._insert_hotel(
            invoice_number="HBE/RM/ENTRY/SPLIT",
            generated_at="2026-04-12 14:00:00",
            total=200.0,
            status="settled",
            payments=[
                {"method": "cash", "amount": 50.0},
                {"method": "bor", "amount": 150.0, "receipt_id": 8},
            ],
        )
        self.conn.commit()
        entry = db_mod.hotel_sales_entry_from_invoices(self.conn, "2026-04-12")
        self.assertEqual(entry["total_sales"], 620.0)
        self.assertEqual(entry["bor"], 570.0)
        self.assertEqual(entry["cash"], 50.0)
        self.assertEqual(entry["room_credit"], 0.0)

    def test_pos_sales_entry_from_invoices_by_outlet(self):
        self._insert_pos(
            order_no="SPC/ENTRY/1",
            outlet=db_mod.POS_OUTLET_RESTAURANT,
            order_date="2026-04-12",
            grand_total=300.0,
            status="closed",
            payments=[
                {"method": "cash", "amount": 100.0},
                {"method": "upi", "amount": 200.0},
            ],
        )
        self._insert_pos(
            order_no="BEB/ENTRY/1",
            outlet=db_mod.POS_OUTLET_BAR,
            order_date="2026-04-12",
            grand_total=50.0,
            status="closed",
            payments=[{"method": "card", "amount": 50.0}],
        )
        self.conn.commit()
        rest = db_mod.pos_sales_entry_from_invoices(
            self.conn, "restaurant", "2026-04-12"
        )
        bar = db_mod.pos_sales_entry_from_invoices(self.conn, "bar", "2026-04-12")
        self.assertEqual(rest["total_sales"], 300.0)
        self.assertEqual(rest["cash"], 100.0)
        self.assertEqual(rest["upi"], 200.0)
        self.assertEqual(bar["total_sales"], 50.0)
        self.assertEqual(bar["card"], 50.0)


if __name__ == "__main__":
    unittest.main()
