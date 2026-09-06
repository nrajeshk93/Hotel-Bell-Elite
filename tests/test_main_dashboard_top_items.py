"""Unit tests for main dashboard top selling items ranking and outlet split."""

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
)
from main_dashboard_data import build_top_selling_items


class TopSellingItemsTests(unittest.TestCase):
    def test_ranks_by_qty_aggregates_outlets_and_limits_to_five(self):
        rows = [
            {"menu_item_id": 1, "item_name": "Butter Chicken", "qty_sold": 2, "sale_value": 400},
            {"menu_item_id": 1, "item_name": "Butter Chicken", "qty_sold": 3, "sale_value": 600},
            {"menu_item_id": 2, "item_name": "Naan", "qty_sold": 10, "sale_value": 500},
            {"menu_item_id": 3, "item_name": "Dal", "qty_sold": 8, "sale_value": 800},
            {"menu_item_id": 4, "item_name": "Rice", "qty_sold": 7, "sale_value": 350},
            {"menu_item_id": 5, "item_name": "Salad", "qty_sold": 6, "sale_value": 300},
            {"menu_item_id": 6, "item_name": "Soup", "qty_sold": 4, "sale_value": 400},
            {"menu_item_id": 7, "item_name": "Lassi", "qty_sold": 1, "sale_value": 80},
        ]
        out = build_top_selling_items(rows, limit=5)
        self.assertEqual(len(out), 5)
        self.assertEqual([r["name"] for r in out], ["Naan", "Dal", "Rice", "Salad", "Butter Chicken"])
        self.assertEqual([r["rank"] for r in out], [1, 2, 3, 4, 5])
        self.assertEqual(out[0]["qty"], 10)
        self.assertEqual(out[4]["qty"], 5)
        self.assertEqual(out[4]["sale_value"], 1000.0)
        self.assertEqual(out[4]["unit_price"], 200.0)
        self.assertEqual(out[4]["qty_label"], "5")
        self.assertEqual(out[4]["qty_display"], "5 sold")
        self.assertTrue(out[0]["sale_value_compact"].startswith("₹"))
        self.assertTrue(out[0]["unit_price_compact"].startswith("₹"))

    def test_fallback_name_key_when_menu_id_missing(self):
        rows = [
            {"menu_item_id": 0, "item_name": "Special Thali", "qty_sold": 2, "sale_value": 400},
            {"menu_item_id": 0, "item_name": "special thali", "qty_sold": 3, "sale_value": 600},
            {"menu_item_id": 0, "item_name": "Tea", "qty_sold": 4, "sale_value": 80},
        ]
        out = build_top_selling_items(rows, limit=5)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["name"], "Special Thali")
        self.assertEqual(out[0]["qty"], 5)
        self.assertEqual(out[0]["sale_value"], 1000.0)
        self.assertEqual(out[0]["unit_price"], 200.0)
        self.assertEqual(out[0]["qty_display"], "5 sold")
        self.assertEqual(out[1]["name"], "Tea")

    def test_sort_by_revenue(self):
        rows = [
            {"menu_item_id": 1, "item_name": "Cheap Popular", "qty_sold": 10, "sale_value": 100},
            {"menu_item_id": 2, "item_name": "Expensive Rare", "qty_sold": 2, "sale_value": 900},
        ]
        by_qty = build_top_selling_items(rows, limit=5, sort_by="qty")
        by_rev = build_top_selling_items(rows, limit=5, sort_by="revenue")
        self.assertEqual(by_qty[0]["name"], "Cheap Popular")
        self.assertEqual(by_rev[0]["name"], "Expensive Rare")
        self.assertEqual(by_rev[0]["sale_value"], 900.0)

    def test_skips_zero_qty_and_empty_input(self):
        self.assertEqual(build_top_selling_items([]), [])
        self.assertEqual(
            build_top_selling_items(
                [{"menu_item_id": 1, "item_name": "X", "qty_sold": 0, "sale_value": 0}]
            ),
            [],
        )


class MainDashboardTopItemsOutletSplitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db_path = self.tmp.name
        self._orig_path = db_mod.DATABASE_PATH
        db_mod.DATABASE_PATH = self.db_path
        db_mod.init_db()
        self.conn = db_mod.get_db()
        db_mod.ensure_pos_schema(self.conn)
        self.day = date(2026, 8, 1)
        self.day_iso = "2026-08-01"

        rest_cat = db_mod.save_pos_menu_category(
            self.conn, name="Mains", outlet=db_mod.POS_OUTLET_RESTAURANT
        )
        bar_cat = db_mod.save_pos_menu_category(
            self.conn, name="Spirits", outlet=db_mod.POS_OUTLET_BAR
        )
        self.butter = db_mod.save_pos_menu_item(
            self.conn,
            category_id=rest_cat["id"],
            name="Chicken Butter Masala",
            rate=320,
            outlet=db_mod.POS_OUTLET_RESTAURANT,
        )
        self.whisky = db_mod.save_pos_menu_item(
            self.conn,
            category_id=bar_cat["id"],
            name="Whisky Peg",
            rate=250,
            outlet=db_mod.POS_OUTLET_BAR,
            item_kind="liquor",
            menu_type="liquor",
        )
        self._settled_line(
            outlet=db_mod.POS_OUTLET_RESTAURANT,
            order_no="SPC/TI/R1",
            menu_id=self.butter["id"],
            name="Chicken Butter Masala",
            rate=320,
            qty=3,
        )
        self._settled_line(
            outlet=db_mod.POS_OUTLET_BAR,
            order_no="BEB/TI/B1",
            menu_id=self.whisky["id"],
            name="Whisky Peg",
            rate=250,
            qty=5,
        )
        self.conn.commit()

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

    def _settled_line(self, *, outlet, order_no, menu_id, name, rate, qty):
        total = round(float(rate) * float(qty), 2)
        cur = self.conn.execute(
            """
            INSERT INTO pos_invoices
               (order_no, order_date, order_type, table_label, customer_name, customer_mobile,
                captain, status, outlet, subtotal, discount_amount, gst_amount, service_amount,
                tip, round_off, grand_total, saved_at, is_active, customer_bill_sent, settled_at)
            VALUES (?, ?, 'dine_in', 'T1', 'Guest', '', '', 'closed', ?,
                    ?, 0, 0, 0, 0, 0, ?, ?, 0, 1, ?)
            """,
            (
                order_no,
                self.day_iso,
                outlet,
                total,
                total,
                self.day_iso + " 18:00:00",
                self.day_iso + " 18:30:00",
            ),
        )
        invoice_id = cur.lastrowid
        self.conn.execute(
            """
            INSERT INTO pos_invoice_lines
                (invoice_id, line_uid, menu_item_id, name, variant, rate, qty,
                 line_total, sort_order, sent_qty, notes)
            VALUES (?, '1', ?, ?, '', ?, ?, ?, 0, 0, '')
            """,
            (invoice_id, menu_id, name, rate, qty, total),
        )
        self.conn.execute(
            """
            INSERT INTO pos_invoice_payments
                (invoice_id, payment_date, payment_method, amount, transaction_id)
            VALUES (?, ?, 'cash', ?, '')
            """,
            (invoice_id, self.day_iso, total),
        )

    def _names(self, rows):
        return {r["name"] for r in (rows or [])}

    def test_all_location_splits_restaurant_and_bar(self):
        payload = _build_main_dashboard_payload(self.conn, self.day, self.day, location=None)
        dash = payload["dashboard"]
        self.assertNotIn("dow_avg", dash)
        self.assertEqual(self._names(dash["top_selling_items_restaurant"]), {"Chicken Butter Masala"})
        self.assertEqual(self._names(dash["top_selling_items_bar"]), {"Whisky Peg"})
        self.assertEqual(self._names(dash["top_selling_items"]), {"Chicken Butter Masala"})
        self.assertEqual(
            self._names(dash["top_selling_items_by_revenue"]), {"Chicken Butter Masala"}
        )
        self.assertNotIn("Whisky Peg", self._names(dash["top_selling_items"]))

    def test_restaurant_filter_hides_bar_list(self):
        payload = _build_main_dashboard_payload(
            self.conn, self.day, self.day, location=OUTLET_RESTAURANT
        )
        dash = payload["dashboard"]
        self.assertEqual(self._names(dash["top_selling_items_restaurant"]), {"Chicken Butter Masala"})
        self.assertEqual(dash["top_selling_items_bar"], [])
        self.assertEqual(dash["top_selling_items_bar_by_revenue"], [])

    def test_bar_filter_hides_restaurant_list(self):
        payload = _build_main_dashboard_payload(
            self.conn, self.day, self.day, location=OUTLET_BAR
        )
        dash = payload["dashboard"]
        self.assertEqual(dash["top_selling_items_restaurant"], [])
        self.assertEqual(self._names(dash["top_selling_items_bar"]), {"Whisky Peg"})
        self.assertEqual(dash["top_selling_items"], [])

    def test_restaurant_bar_combo_includes_both(self):
        payload = _build_main_dashboard_payload(
            self.conn,
            self.day,
            self.day,
            location=DASHBOARD_FILTER_LOCATION_RESTAURANT_BAR,
        )
        dash = payload["dashboard"]
        self.assertEqual(self._names(dash["top_selling_items_restaurant"]), {"Chicken Butter Masala"})
        self.assertEqual(self._names(dash["top_selling_items_bar"]), {"Whisky Peg"})

    def test_hotel_filter_clears_both(self):
        payload = _build_main_dashboard_payload(
            self.conn, self.day, self.day, location=OUTLET_HOTEL
        )
        dash = payload["dashboard"]
        self.assertEqual(dash["top_selling_items_restaurant"], [])
        self.assertEqual(dash["top_selling_items_bar"], [])

    def test_bar_menu_on_restaurant_invoice_counts_as_bar(self):
        """Bar catalog drinks sold on a restaurant bill belong on the Bar card."""
        self._settled_line(
            outlet=db_mod.POS_OUTLET_RESTAURANT,
            order_no="SPC/TI/BARONREST",
            menu_id=self.whisky["id"],
            name="Whisky Peg",
            rate=250,
            qty=4,
        )
        self.conn.commit()

        payload = _build_main_dashboard_payload(self.conn, self.day, self.day, location=None)
        dash = payload["dashboard"]
        self.assertEqual(self._names(dash["top_selling_items_restaurant"]), {"Chicken Butter Masala"})
        self.assertEqual(self._names(dash["top_selling_items_bar"]), {"Whisky Peg"})
        whisky = next(r for r in dash["top_selling_items_bar"] if r["name"] == "Whisky Peg")
        self.assertEqual(whisky["qty"], 9.0)  # 5 on bar bill + 4 on restaurant bill

        rest_only = _build_main_dashboard_payload(
            self.conn, self.day, self.day, location=OUTLET_RESTAURANT
        )["dashboard"]
        self.assertEqual(
            self._names(rest_only["top_selling_items_restaurant"]),
            {"Chicken Butter Masala"},
        )
        self.assertEqual(rest_only["top_selling_items_bar"], [])


if __name__ == "__main__":
    unittest.main()
