"""Main dashboard Total Sales KPIs use invoice ledgers (not empty sales_updates).

Difference KPI mirrors module Sales Update pages (invoice overlay + outlet rules).
"""

import json
import os
import tempfile
import unittest
from datetime import date

import db as db_mod
from app import (
    DASHBOARD_FILTER_LOCATION_RESTAURANT_BAR,
    DEFAULT_COMPANY,
    OUTLET_BAR,
    OUTLET_HOTEL,
    OUTLET_RESTAURANT,
    _build_main_dashboard_payload,
    _dashboard_outlet_names,
    _module_sales_update_difference_total,
    _normalize_dashboard_location_filter,
    _outlet_sales_update_kpi_bundle,
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
        self.user = {"is_admin": True}

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

    def _hotel(self, number, total, day="2026-08-01", status="settled"):
        self.conn.execute(
            """
            INSERT INTO hotel_room_invoices (
                invoice_number, room_id, room_number, room_type_label,
                guest_name, booking_number, check_in_date, check_out_date,
                invoice_generated_at, estimated_total, advance_paid,
                balance_amount, status, payload_json
            ) VALUES (?, 'r1', '101', 'Deluxe', 'Guest', '',
                      ?, ?, ? || ' 10:00:00',
                      ?, 0, ?, ?, ?)
            """,
            (
                number,
                day,
                day,
                day,
                float(total),
                0.0 if status == "settled" else float(total),
                status,
                json.dumps(
                    {
                        "stay": {
                            "guestName": "Guest",
                            "payments": (
                                [{"method": "cash", "amount": float(total)}]
                                if status == "settled"
                                else []
                            ),
                        }
                    }
                ),
            ),
        )

    def _pos(self, order_no, outlet, total, method="cash", day="2026-08-01"):
        cur = self.conn.execute(
            """
            INSERT INTO pos_invoices
               (order_no, order_date, order_type, table_label, customer_name, customer_mobile,
                captain, status, outlet, subtotal, discount_amount, gst_amount, service_amount,
                tip, round_off, grand_total, saved_at, is_active)
            VALUES (?, ?, 'dine_in', 'T1', 'Guest', '', '', 'closed', ?,
                    ?, 0, 0, 0, 0, 0, ?, datetime('now'), 1)
            """,
            (order_no, day, outlet, float(total), float(total)),
        )
        self.conn.execute(
            """
            INSERT INTO pos_invoice_payments
                (invoice_id, payment_date, payment_method, amount, transaction_id)
            VALUES (?, ?, ?, ?, '')
            """,
            (cur.lastrowid, day, method, float(total)),
        )

    def _sales_update(self, location, sales_date, entries):
        self.conn.execute(
            """
            INSERT INTO sales_updates (
                company, location, sales_date, sales_entry_values, created_at, updated_at
            ) VALUES (?, ?, ?, ?, datetime('now'), datetime('now'))
            """,
            (DEFAULT_COMPANY, location, sales_date, json.dumps(entries)),
        )

    def _module_diffs(self, day):
        parts = []
        for loc in (OUTLET_HOTEL, OUTLET_RESTAURANT, OUTLET_BAR):
            kpi = _outlet_sales_update_kpi_bundle(
                self.conn,
                DEFAULT_COMPANY,
                loc,
                day,
                day,
                user=self.user,
                overlay_invoices=True,
            )
            parts.append(kpi["current"]["difference"])
        return parts

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

    def test_total_sales_excludes_unsettled_and_provisional(self):
        """TOTAL SALES matches Invoice Ledger Settled (generated_only), not open drafts."""
        day = date(2026, 8, 1)
        day_iso = "2026-08-01"
        self._hotel("HBE/MD/OPEN", 1000, status="open")
        self._pos("SPC/MD/OK", db_mod.POS_OUTLET_RESTAURANT, 2000, "upi")
        # Unsettled open bill — must not inflate TOTAL SALES.
        self.conn.execute(
            """
            INSERT INTO pos_invoices
               (order_no, order_date, order_type, table_label, customer_name, customer_mobile,
                captain, status, outlet, subtotal, discount_amount, gst_amount, service_amount,
                tip, round_off, grand_total, saved_at, is_active, customer_bill_sent)
            VALUES ('SPC/MD/OPEN', ?, 'dine_in', 'T2', 'Guest', '', '', 'open', ?,
                    9000, 0, 0, 0, 0, 0, 9000, datetime('now'), 1, 1)
            """,
            (day_iso, db_mod.POS_OUTLET_RESTAURANT),
        )
        # Provisional closed+paid draft — hidden from Invoice Ledger generated list.
        cur = self.conn.execute(
            """
            INSERT INTO pos_invoices
               (order_no, order_date, order_type, table_label, customer_name, customer_mobile,
                captain, status, outlet, subtotal, discount_amount, gst_amount, service_amount,
                tip, round_off, grand_total, saved_at, is_active, customer_bill_sent, settled_at)
            VALUES ('SPC/ABCDEF/26-27', ?, 'dine_in', 'T3', 'Guest', '', '', 'closed', ?,
                    4000, 0, 0, 0, 0, 0, 4000, datetime('now'), 1, 0, ?)
            """,
            (day_iso, db_mod.POS_OUTLET_RESTAURANT, day_iso + " 12:00:00"),
        )
        self.conn.execute(
            """
            INSERT INTO pos_invoice_payments
                (invoice_id, payment_date, payment_method, amount, transaction_id)
            VALUES (?, ?, 'cash', 4000, '')
            """,
            (cur.lastrowid, day_iso),
        )
        self.conn.commit()

        ledger = db_mod.list_pos_invoices(
            self.conn,
            date_from=day_iso,
            date_to=day_iso,
            settlement="settled",
            outlet=db_mod.POS_OUTLET_RESTAURANT,
            generated_only=True,
        )
        ledger_total = sum(float(inv.get("grand_total") or 0) for inv in ledger)
        self.assertEqual(ledger_total, 2000.0)

        payload = _build_main_dashboard_payload(
            self.conn, day, day, location=OUTLET_RESTAURANT
        )
        kpi = next(k for k in payload["dashboard"]["kpis"] if k["key"] == "actual_sales")
        self.assertEqual(kpi["value"], ledger_total)

    def test_hotel_open_invoices_count_toward_total_sales(self):
        """Hotel TOTAL SALES matches Invoice Ledger Total billed (open + settled)."""
        day = date(2026, 8, 30)
        day_iso = "2026-08-30"
        self._hotel("HBE/MD/OPEN/1", 5600, day=day_iso, status="open")
        self._hotel("HBE/MD/OPEN/2", 3000, day=day_iso, status="open")
        self._hotel(
            "HBE/MD/SET/1",
            2000,
            day=day_iso,
            status="settled",
        )
        self.conn.commit()

        from db import list_hotel_room_invoices, hotel_room_invoice_kpis

        rows = list_hotel_room_invoices(
            self.conn,
            status="",
            source="hotel",
            date_from=day_iso,
            date_to=day_iso,
            limit=500,
        )
        ledger_total = float(hotel_room_invoice_kpis(rows)["amount_sum"])
        self.assertEqual(ledger_total, 10600.0)

        payload = _build_main_dashboard_payload(
            self.conn, day, day, location=OUTLET_HOTEL
        )
        kpi = next(k for k in payload["dashboard"]["kpis"] if k["key"] == "actual_sales")
        self.assertEqual(kpi["value"], ledger_total)
        # Must not stay at ₹0 when hotel ledger has billed invoices.
        self.assertGreater(kpi["value"], 0.0)

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

    def test_difference_zero_when_modules_balanced_despite_stale_raw_cash(self):
        """Raw sales_updates can have cash=0 while actual_cash is set; modules overlay
        invoice cash so Difference is 0 — dashboard must match that, not −13520."""
        day = date(2026, 8, 30)
        day_iso = "2026-08-30"
        self._pos("SPC/MD/BAL/R", db_mod.POS_OUTLET_RESTAURANT, 3860, "cash", day=day_iso)
        self._pos("BEB/MD/BAL/B", db_mod.POS_OUTLET_BAR, 9660, "cash", day=day_iso)
        # Stale saved rows (cash wiped / not synced) — raw formula would be −13520.
        self._sales_update(
            OUTLET_RESTAURANT,
            day_iso,
            {"total_sales": 0.0, "cash": 0.0, "actual_cash": 3860.0},
        )
        self._sales_update(
            OUTLET_BAR,
            day_iso,
            {"total_sales": 0.0, "cash": 0.0, "actual_cash": 9660.0},
        )
        self._sales_update(
            OUTLET_HOTEL,
            day_iso,
            {
                "total_sales": 0.0,
                "cash": 0.0,
                "card": 0.0,
                "upi": 0.0,
                "room_credit": 0.0,
                "bor": 0.0,
            },
        )
        self.conn.commit()

        hotel_d, rest_d, bar_d = self._module_diffs(day)
        self.assertEqual(hotel_d, 0.0)
        self.assertEqual(rest_d, 0.0)
        self.assertEqual(bar_d, 0.0)

        payload = _build_main_dashboard_payload(self.conn, day, day, location=None)
        kpi = next(k for k in payload["dashboard"]["kpis"] if k["key"] == "difference")
        self.assertEqual(kpi["value"], 0.0)
        self.assertEqual(
            _module_sales_update_difference_total(self.conn, day, day),
            hotel_d + rest_d + bar_d,
        )

    def test_difference_equals_sum_of_module_sales_update_diffs(self):
        day = date(2026, 8, 1)
        day_iso = "2026-08-01"
        # Invoice cash 350 / 225; actual_cash short → Restaurant 50 + Bar 25.
        self._pos("SPC/MD/DIFF/R", db_mod.POS_OUTLET_RESTAURANT, 350, "cash", day=day_iso)
        self._pos("BEB/MD/DIFF/B", db_mod.POS_OUTLET_BAR, 225, "cash", day=day_iso)
        self._sales_update(
            OUTLET_RESTAURANT,
            day_iso,
            {"total_sales": 0.0, "cash": 0.0, "actual_cash": 300.0},
        )
        self._sales_update(
            OUTLET_BAR,
            day_iso,
            {"total_sales": 0.0, "cash": 0.0, "actual_cash": 200.0},
        )
        # Hotel open invoice with no tenders would be an invoice gap; module overlay
        # still builds sales entry from invoices — keep hotel balanced empty.
        self.conn.commit()

        hotel_d, rest_d, bar_d = self._module_diffs(day)
        expected = hotel_d + rest_d + bar_d
        self.assertEqual(rest_d, 50.0)
        self.assertEqual(bar_d, 25.0)
        self.assertEqual(expected, 75.0)

        payload = _build_main_dashboard_payload(self.conn, day, day, location=None)
        kpi = next(k for k in payload["dashboard"]["kpis"] if k["key"] == "difference")
        self.assertEqual(kpi["value"], expected)


if __name__ == "__main__":
    unittest.main()
