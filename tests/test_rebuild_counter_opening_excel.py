"""Bar counter opening Excel + POS sales rebuild."""

import os
import tempfile
import unittest
from unittest import mock

from openpyxl import Workbook

import db as db_mod


class RebuildCounterFromOpeningExcelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db_path = self.tmp.name
        self._orig_path = db_mod.DATABASE_PATH
        db_mod.DATABASE_PATH = self.db_path
        db_mod.init_db()

        # Import after DATABASE_PATH is set.
        import scripts.rebuild_counter_from_opening_excel as rebuild_mod

        self.rebuild = rebuild_mod

        self.conn = db_mod.get_db()
        db_mod.ensure_pos_schema(self.conn)
        db_mod.ensure_stores_schema(self.conn)

        cat = self.conn.execute(
            "SELECT id FROM store_product_categories WHERE is_active = 1 ORDER BY id LIMIT 1"
        ).fetchone()
        if not cat:
            self.conn.execute(
                "INSERT INTO store_product_categories (name, sort_order, is_active) VALUES ('Beer', 10, 1)"
            )
            cat_id = self.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        else:
            cat_id = cat["id"]

        self.conn.execute(
            """
            INSERT INTO store_products
                (category_id, name, default_unit, outlet, approximate_price, is_active, sort_order)
            VALUES (?, 'Kingfisher Strong', 'Bottle', 'bar', 120, 1, 1)
            """,
            (cat_id,),
        )
        self.product_id = self.conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        self.conn.execute(
            """
            INSERT INTO store_products
                (category_id, name, default_unit, outlet, approximate_price, is_active, sort_order)
            VALUES (?, 'Paneer Cube', 'kg', 'restaurant', 300, 1, 2)
            """,
            (cat_id,),
        )
        self.rest_product_id = self.conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        self.conn.execute(
            """
            INSERT INTO pos_menu_categories (name, sort_order, is_visible, is_active, outlet)
            VALUES ('Beer', 1, 1, 1, 'bar')
            """
        )
        self.menu_cat_id = self.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        self.conn.execute(
            """
            INSERT INTO pos_menu_items
                (category_id, product_id, name, code, variant, rate, sort_order, is_active, outlet)
            VALUES (?, ?, 'Kingfisher Strong Bottle', 'KS1', 'Regular', 150, 1, 1, 'bar')
            """,
            (self.menu_cat_id, self.product_id),
        )
        self.menu_item_id = self.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        self.conn.execute(
            """
            INSERT INTO pos_menu_recipe_lines (menu_item_id, product_id, qty, unit, sort_order)
            VALUES (?, ?, 1, 'Bottle', 1)
            """,
            (self.menu_item_id, self.product_id),
        )

        self.conn.execute(
            """
            INSERT INTO pos_menu_categories (name, sort_order, is_visible, is_active, outlet)
            VALUES ('Mains', 2, 1, 1, 'restaurant')
            """
        )
        rest_cat = self.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        self.conn.execute(
            """
            INSERT INTO pos_menu_items
                (category_id, product_id, name, code, variant, rate, sort_order, is_active, outlet)
            VALUES (?, ?, 'Paneer Dish', 'PD1', 'Regular', 220, 1, 1, 'restaurant')
            """,
            (rest_cat, self.rest_product_id),
        )
        self.rest_menu_id = self.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        self.conn.execute(
            """
            INSERT INTO pos_menu_recipe_lines (menu_item_id, product_id, qty, unit, sort_order)
            VALUES (?, ?, 0.2, 'kg', 1)
            """,
            (self.rest_menu_id, self.rest_product_id),
        )

        # Seed counter rows that will be overwritten by opening.
        self.conn.execute(
            """
            INSERT INTO store_stock_items
                (outlet, place, item_name, unit, qty_on_hand, updated_at)
            VALUES ('bar', 'counter', 'Kingfisher Strong', 'Bottle', 1.0, datetime('now','localtime'))
            """
        )
        self.conn.execute(
            """
            INSERT INTO store_stock_items
                (outlet, place, item_name, unit, qty_on_hand, updated_at)
            VALUES ('restaurant', 'counter', 'Paneer Cube', 'kg', 0.0, datetime('now','localtime'))
            """
        )
        self.conn.commit()

        xlsx = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
        xlsx.close()
        self.xlsx_path = xlsx.name
        self._write_mini_xlsx(self.xlsx_path, closing_qty=10)

    def tearDown(self):
        self.conn.close()
        db_mod.DATABASE_PATH = self._orig_path
        for path in (self.db_path, self.xlsx_path):
            try:
                os.unlink(path)
            except OSError:
                pass

    def _write_mini_xlsx(self, path, *, closing_qty):
        wb = Workbook()
        ws = wb.active
        ws.title = "BAR COUNTER  OPENING STOCK FOR "
        # Row 2 headers — closing balance at column index 66 (BP)
        headers = [None] * 68
        headers[0] = "SL NO"
        headers[1] = "Item Type"
        headers[2] = "Item Name"
        headers[3] = "Opening Stock as on 1st AUG 2026"
        headers[66] = "Clossing Balance"
        ws.append(["BAR COUNTER  OPENING STOCK FOR THE MONTH SEPTEMBER"])
        ws.append(headers)
        ws.append([None] * 68)
        ws.append(["BELOW ITEMS IN BOTTELS"])
        data = [None] * 68
        data[0] = 1
        data[1] = "Beer"
        data[2] = "KINGFISHER STRONG"
        data[3] = 99  # Aug 1 opening — must be ignored
        data[66] = closing_qty
        ws.append(data)
        wb.save(path)

    def _insert_closed_invoice(
        self, *, outlet, menu_item_id, qty, order_date, order_no, stock_deducted_at="2026-09-02 12:00:00"
    ):
        self.conn.execute(
            """
            INSERT INTO pos_invoices
                (order_no, saved_at, order_date, outlet, status, is_active,
                 customer_name, customer_mobile, subtotal, grand_total,
                 stock_deducted_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'closed', 0, 'Guest', '9000000001', 100, 100,
                    ?, datetime('now','localtime'), datetime('now','localtime'))
            """,
            (order_no, f"{order_date} 18:00:00", order_date, outlet, stock_deducted_at),
        )
        invoice_id = self.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        self.conn.execute(
            """
            INSERT INTO pos_invoice_lines
                (invoice_id, menu_item_id, name, variant, rate, qty, line_total, sort_order)
            VALUES (?, ?, 'Item', 'Regular', 100, ?, ?, 1)
            """,
            (invoice_id, menu_item_id, qty, 100 * qty),
        )
        # Stale sale movement from prior deduction (will be cleared by rebuild).
        self.conn.execute(
            """
            INSERT INTO store_stock_movements
                (outlet, place, item_name, unit, qty_delta, movement_type, ref_type, ref_id,
                 notes, created_by, created_at)
            VALUES (?, 'counter', 'x', 'Bottle', -1, 'sale', 'pos_invoice', ?, 'stale',
                    NULL, datetime('now','localtime'))
            """,
            (outlet, invoice_id),
        )
        self.conn.commit()
        return invoice_id

    def test_parse_uses_closing_balance_not_aug_opening(self):
        rows = self.rebuild.parse_bar_counter_opening_xlsx(self.xlsx_path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["excel_name"], "KINGFISHER STRONG")
        self.assertEqual(rows[0]["opening_qty"], 10.0)
        self.assertEqual(rows[0]["unit_hint"], "Bottle")

    def test_name_normalize_matches_product_master(self):
        rows = self.rebuild.parse_bar_counter_opening_xlsx(self.xlsx_path)
        match = self.rebuild.match_opening_to_products(self.conn, rows, outlet="bar")
        self.assertEqual(len(match["matched"]), 1)
        self.assertEqual(match["matched"][0]["product_name"], "Kingfisher Strong")
        self.assertEqual(match["matched"][0]["unit"], "Bottle")
        self.assertEqual(match["matched"][0]["opening_qty"], 10.0)

    def test_rebuild_sets_opening_minus_bar_sales_and_restaurant_sales(self):
        self._insert_closed_invoice(
            outlet="bar",
            menu_item_id=self.menu_item_id,
            qty=3,
            order_date="2026-09-02",
            order_no="BAR-R1",
        )
        self._insert_closed_invoice(
            outlet="restaurant",
            menu_item_id=self.rest_menu_id,
            qty=2,
            order_date="2026-09-03",
            order_no="REST-R1",
        )

        report = self.rebuild.rebuild_counter_from_opening_excel(
            self.conn,
            xlsx_path=self.xlsx_path,
            from_date="2026-09-01",
            to_date="2026-09-10",
            dry_run=False,
        )
        self.conn.commit()
        self.assertTrue(report["ok"])
        self.assertEqual(report["matched"], 1)
        self.assertEqual(report["replay"]["replayed"], 2)

        bar_qty = self.conn.execute(
            """
            SELECT qty_on_hand FROM store_stock_items
            WHERE outlet = 'bar' AND place = 'counter'
              AND lower(item_name) = 'kingfisher strong'
            """
        ).fetchone()
        self.assertIsNotNone(bar_qty)
        # Opening 10 bottles − 3 sold = 7
        self.assertAlmostEqual(float(bar_qty["qty_on_hand"]), 7.0, places=3)

        rest_qty = self.conn.execute(
            """
            SELECT qty_on_hand FROM store_stock_items
            WHERE outlet = 'restaurant' AND place = 'counter'
              AND lower(item_name) = 'paneer cube'
            """
        ).fetchone()
        self.assertIsNotNone(rest_qty)
        # Restaurant opening 0 − (2 × 0.2 kg) = −0.4
        self.assertAlmostEqual(float(rest_qty["qty_on_hand"]), -0.4, places=3)

        products = self.conn.execute("SELECT COUNT(*) AS c FROM store_products").fetchone()
        self.assertGreaterEqual(int(products["c"]), 2)


if __name__ == "__main__":
    unittest.main()
