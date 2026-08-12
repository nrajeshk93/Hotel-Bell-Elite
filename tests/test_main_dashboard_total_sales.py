"""Main dashboard Total Sales KPIs use invoice ledgers (not empty sales_updates)."""

import json
import os
import tempfile
import unittest
from datetime import date

import db as db_mod
from app import (
    DASHBOARD_FILTER_LOCATION_RESTAURANT_BAR,
    OUTLET_BAR,
    OUTLET_HOTEL,
    OUTLET_RESTAURANT,
    _build_main_dashboard_payload,
    _dashboard_outlet_names,
    _normalize_dashboard_location_filter,
    _resolve_main_dashboard_filters,
)


class MainDashboardTotalSalesTests(unittest.TestCase):
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

    def _hotel(self, number, total):
        self.conn.execute(
            """
            INSERT INTO hotel_room_invoices (
                invoice_number, room_id, room_number, room_type_label,
                guest_name, booking_number, check_in_date, check_out_date,
                invoice_generated_at, estimated_total, advance_paid,
                balance_amount, status, payload_json
            ) VALUES (?, 'r1', '101', 'Deluxe', 'Guest', '',
                      '2026-08-01', '2026-08-02', '2026-08-01 10:00:00',
                      ?, 0, ?, 'open', ?)
            """,
            (
                number,
                float(total),
                float(total),
                json.dumps({"stay": {"guestName": "Guest"}}),
            ),
        )

    def _pos(self, order_no, outlet, total, method="cash"):
        cur = self.conn.execute(
            """
            INSERT INTO pos_invoices
               (order_no, order_date, order_type, table_label, customer_name, customer_mobile,
                captain, status, outlet, subtotal, discount_amount, gst_amount, service_amount,
                tip, round_off, grand_total, saved_at, is_active)
            VALUES (?, '2026-08-01', 'dine_in', 'T1', 'Guest', '', '', 'closed', ?,
                    ?, 0, 0, 0, 0, 0, ?, datetime('now'), 1)
            """,
            (order_no, outlet, float(total), float(total)),
        )
        self.conn.execute(
            """
            INSERT INTO pos_invoice_payments
                (invoice_id, payment_date, payment_method, amount, transaction_id)
            VALUES (?, '2026-08-01', ?, ?, '')
            """,
            (cur.lastrowid, method, float(total)),
        )

    def test_total_sales_sums_hotel_restaurant_bar(self):
        day = date(2026, 8, 1)
        self._hotel("HBE/MD/1", 1000)
        self._pos("SPC/MD/1", db_mod.POS_OUTLET_RESTAURANT, 2000, "upi")
        self._pos("BEB/MD/1", db_mod.POS_OUTLET_BAR, 3000, "cash")
        self.conn.commit()

        payload = _build_main_dashboard_payload(self.conn, day, day, location=None)
        kpi = next(k for k in payload["dashboard"]["kpis"] if k["key"] == "actual_sales")
        self.assertEqual(kpi["value"], 6000.0)
        self.assertEqual(payload["dashboard"]["sales_contribution"]["total_sales"], 6000.0)

    def test_restaurant_and_bar_filter_excludes_hotel(self):
        day = date(2026, 8, 1)
        self._hotel("HBE/MD/2", 1000)
        self._pos("SPC/MD/2", db_mod.POS_OUTLET_RESTAURANT, 2000, "upi")
        self._pos("BEB/MD/2", db_mod.POS_OUTLET_BAR, 3000, "cash")
        self.conn.commit()

        payload = _build_main_dashboard_payload(
            self.conn, day, day, location=DASHBOARD_FILTER_LOCATION_RESTAURANT_BAR
        )
        kpi = next(k for k in payload["dashboard"]["kpis"] if k["key"] == "actual_sales")
        self.assertEqual(kpi["value"], 5000.0)
        self.assertEqual(
            _dashboard_outlet_names(DASHBOARD_FILTER_LOCATION_RESTAURANT_BAR),
            [OUTLET_RESTAURANT, OUTLET_BAR],
        )

    def test_resolve_restaurant_and_bar_location(self):
        filters = _resolve_main_dashboard_filters(
            {"location": DASHBOARD_FILTER_LOCATION_RESTAURANT_BAR, "period": "30d"}
        )
        self.assertEqual(
            filters["selected_location"], DASHBOARD_FILTER_LOCATION_RESTAURANT_BAR
        )
        self.assertEqual(filters["selected_location_label"], "Restaurant & Bar")
        self.assertEqual(
            _normalize_dashboard_location_filter(DASHBOARD_FILTER_LOCATION_RESTAURANT_BAR),
            [OUTLET_RESTAURANT, OUTLET_BAR],
        )


if __name__ == "__main__":
    unittest.main()
