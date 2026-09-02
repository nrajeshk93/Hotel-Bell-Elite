"""Unit Insight report — recipe-based ingredient units sold."""

import os
import tempfile
import unittest
from unittest import mock

import db as db_mod


class UnitInsightsReportDbTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db_path = self.tmp.name
        self._orig_path = db_mod.DATABASE_PATH
        db_mod.DATABASE_PATH = self.db_path
        db_mod.init_db()
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
            VALUES (?, 'Kingfisher Premium', 'bottle', 'bar', 120, 1, 1)
            """,
            (cat_id,),
        )
        self.product_id = self.conn.execute("SELECT last_insert_rowid()").fetchone()[0]

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
            VALUES (?, ?, 'Kingfisher Peg', 'KF1', 'Regular', 250, 1, 1, 'bar')
            """,
            (self.menu_cat_id, self.product_id),
        )
        self.menu_item_id = self.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        self.conn.execute(
            """
            INSERT INTO pos_menu_recipe_lines (menu_item_id, product_id, qty, unit, sort_order)
            VALUES (?, ?, 1, 'bottle', 1)
            """,
            (self.menu_item_id, self.product_id),
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        db_mod.DATABASE_PATH = self._orig_path
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def _insert_invoice(self, *, order_no, qty, settled=False, order_date="2026-08-01"):
        line_total = 250 * qty
        self.conn.execute(
            """
            INSERT INTO pos_invoices
                (order_no, saved_at, order_date, outlet, status, is_active,
                 customer_name, customer_mobile, subtotal, grand_total,
                 created_at, updated_at)
            VALUES (?, ?, ?, 'bar', 'open', 1, 'Guest', '9000000001', ?, ?,
                    datetime('now','localtime'), datetime('now','localtime'))
            """,
            (order_no, f"{order_date} 18:00:00", order_date, line_total, line_total),
        )
        invoice_id = self.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        self.conn.execute(
            """
            INSERT INTO pos_invoice_lines
                (invoice_id, menu_item_id, name, variant, rate, qty, line_total, sort_order)
            VALUES (?, ?, 'Kingfisher Peg', 'Regular', 250, ?, ?, 1)
            """,
            (invoice_id, self.menu_item_id, qty, 250 * qty),
        )
        if settled:
            self.conn.execute(
                """
                INSERT INTO pos_invoice_payments
                    (invoice_id, payment_method, amount, payment_date, created_at)
                VALUES (?, 'cash', ?, ?, datetime('now','localtime'))
                """,
                (invoice_id, 250 * qty, order_date),
            )
        self.conn.commit()
        return invoice_id

    def test_bottle_units_from_recipe_and_invoice_qty(self):
        self._insert_invoice(order_no="UIR-1", qty=3, settled=True)
        rows = db_mod.list_pos_unit_insights(
            self.conn,
            date_from="2026-08-01",
            date_to="2026-08-01",
            outlet="bar",
            settlement="settled",
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["product_name"], "Kingfisher Premium")
        self.assertEqual(rows[0]["units_sold"], 3.0)
        self.assertEqual(rows[0]["units_sold_display"], "3 bottle")

    def test_gram_to_kg_conversion(self):
        self.conn.execute(
            """
            INSERT INTO store_products
                (category_id, name, default_unit, outlet, approximate_price, is_active, sort_order)
            VALUES ((SELECT category_id FROM store_products WHERE id = ?), 'Paneer Block', 'kg', 'restaurant', 300, 1, 2)
            """,
            (self.product_id,),
        )
        paneer_id = self.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        self.conn.execute(
            """
            INSERT INTO pos_menu_categories (name, sort_order, is_visible, is_active, outlet)
            VALUES ('Mains', 2, 1, 1, 'restaurant')
            """
        )
        rest_cat_id = self.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        self.conn.execute(
            """
            INSERT INTO pos_menu_items
                (category_id, product_id, name, code, variant, rate, sort_order, is_active, outlet)
            VALUES (?, ?, 'Paneer Tikka', 'PT1', 'Regular', 320, 1, 1, 'restaurant')
            """,
            (rest_cat_id, paneer_id),
        )
        rest_menu_id = self.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        self.conn.execute(
            """
            INSERT INTO pos_menu_recipe_lines (menu_item_id, product_id, qty, unit, sort_order)
            VALUES (?, ?, 200, 'g', 1)
            """,
            (rest_menu_id, paneer_id),
        )
        self.conn.execute(
            """
            INSERT INTO pos_invoices
                (order_no, saved_at, order_date, outlet, status, is_active,
                 customer_name, customer_mobile, subtotal, grand_total,
                 created_at, updated_at)
            VALUES ('UIR-2', '2026-08-01 18:00:00', '2026-08-01', 'restaurant', 'open', 1,
                    'Guest', '9000000002', 640, 640,
                    datetime('now','localtime'), datetime('now','localtime'))
            """
        )
        invoice_id = self.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        self.conn.execute(
            """
            INSERT INTO pos_invoice_lines
                (invoice_id, menu_item_id, name, variant, rate, qty, line_total, sort_order)
            VALUES (?, ?, 'Paneer Tikka', 'Regular', 320, 2, 640, 1)
            """,
            (invoice_id, rest_menu_id),
        )
        self.conn.execute(
            """
            INSERT INTO pos_invoice_payments
                (invoice_id, payment_method, amount, payment_date, created_at)
            VALUES (?, 'cash', 640, '2026-08-01', datetime('now','localtime'))
            """,
            (invoice_id,),
        )
        self.conn.commit()

        rows = db_mod.list_pos_unit_insights(
            self.conn,
            date_from="2026-08-01",
            date_to="2026-08-01",
            outlet="restaurant",
            settlement="settled",
        )
        paneer = next((r for r in rows if r["product_name"] == "Paneer Block"), None)
        self.assertIsNotNone(paneer)
        self.assertAlmostEqual(float(paneer["units_sold"]), 0.4)

    def test_settlement_filter_excludes_unsettled(self):
        self._insert_invoice(order_no="UIR-3", qty=2, settled=False)
        rows = db_mod.list_pos_unit_insights(
            self.conn,
            date_from="2026-08-01",
            date_to="2026-08-01",
            outlet="bar",
            settlement="settled",
        )
        self.assertEqual(rows, [])

    def test_cancelled_invoice_does_not_count_as_sold(self):
        invoice_id = self._insert_invoice(order_no="UIR-4", qty=4, settled=True)
        self.conn.execute(
            """
            UPDATE pos_invoices
            SET status = 'cancelled',
                cancelled_at = '2026-08-01 19:00:00',
                cancel_reason = 'Guest left'
            WHERE id = ?
            """,
            (invoice_id,),
        )
        self.conn.commit()
        rows = db_mod.list_pos_unit_insights(
            self.conn,
            date_from="2026-08-01",
            date_to="2026-08-01",
            outlet="bar",
        )
        self.assertEqual(rows, [])

    def test_soft_deleted_invoice_does_not_count_as_sold(self):
        invoice_id = self._insert_invoice(order_no="UIR-5", qty=2, settled=True)
        self.conn.execute(
            "UPDATE pos_invoices SET is_active = 0 WHERE id = ?",
            (invoice_id,),
        )
        self.conn.commit()
        rows = db_mod.list_pos_unit_insights(
            self.conn,
            date_from="2026-08-01",
            date_to="2026-08-01",
            outlet="bar",
        )
        self.assertEqual(rows, [])

    def test_kpis_split_bottle_and_ml(self):
        self._insert_invoice(order_no="UIR-6", qty=3, settled=True)
        cat_id = self.conn.execute(
            "SELECT category_id FROM store_products WHERE id = ?",
            (self.product_id,),
        ).fetchone()[0]
        self.conn.execute(
            """
            INSERT INTO store_products
                (category_id, name, default_unit, outlet, approximate_price, is_active, sort_order)
            VALUES (?, 'Soda Water', 'milliliter', 'bar', 20, 1, 3)
            """,
            (cat_id,),
        )
        soda_id = self.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        self.conn.execute(
            """
            INSERT INTO pos_menu_items
                (category_id, product_id, name, code, variant, rate, sort_order, is_active, outlet)
            VALUES (?, ?, 'Soda Splash', 'SS1', 'Regular', 80, 2, 1, 'bar')
            """,
            (self.menu_cat_id, soda_id),
        )
        soda_menu_id = self.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        self.conn.execute(
            """
            INSERT INTO pos_menu_recipe_lines (menu_item_id, product_id, qty, unit, sort_order)
            VALUES (?, ?, 200, 'ml', 1)
            """,
            (soda_menu_id, soda_id),
        )
        self.conn.execute(
            """
            INSERT INTO pos_invoices
                (order_no, saved_at, order_date, outlet, status, is_active,
                 customer_name, customer_mobile, subtotal, grand_total,
                 created_at, updated_at)
            VALUES ('UIR-7', '2026-08-01 18:00:00', '2026-08-01', 'bar', 'open', 1,
                    'Guest', '9000000007', 80, 80,
                    datetime('now','localtime'), datetime('now','localtime'))
            """
        )
        soda_invoice_id = self.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        self.conn.execute(
            """
            INSERT INTO pos_invoice_lines
                (invoice_id, menu_item_id, name, variant, rate, qty, line_total, sort_order)
            VALUES (?, ?, 'Soda Splash', 'Regular', 80, 1, 80, 1)
            """,
            (soda_invoice_id, soda_menu_id),
        )
        self.conn.execute(
            """
            INSERT INTO pos_invoice_payments
                (invoice_id, payment_method, amount, payment_date, created_at)
            VALUES (?, 'cash', 80, '2026-08-01', datetime('now','localtime'))
            """,
            (soda_invoice_id,),
        )
        self.conn.commit()
        rows = db_mod.list_pos_unit_insights(
            self.conn,
            date_from="2026-08-01",
            date_to="2026-08-01",
            outlet="bar",
            settlement="settled",
        )
        kpis = db_mod.pos_unit_insights_kpis(rows)
        labels = [item["label"] for item in kpis["unit_kpis"]]
        self.assertIn("Bottles sold", labels)
        self.assertIn("ML sold", labels)
        by_unit = {item["unit"]: item for item in kpis["unit_kpis"]}
        self.assertEqual(by_unit["bottle"]["qty_display"], "3 bottle")
        self.assertEqual(by_unit["ml"]["qty_display"], "200 ml")


class UnitInsightsReportRouteTests(unittest.TestCase):
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

    def test_page_loads(self):
        page = self.client.get("/reports/sales/units?from_hub=reports")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn("Unit Insight", html)
        self.assertIn("Product Name", html)
        self.assertIn("Units sold", html)
        self.assertIn("unit-insights-report-page", html)

    def test_export_returns_xlsx(self):
        res = self.client.get("/reports/sales/units/export?from_hub=reports")
        self.assertEqual(res.status_code, 200)
        self.assertIn(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            res.content_type,
        )
        self.assertTrue(len(res.data) > 100)
        self.assertTrue(res.data[:2] == b"PK")


if __name__ == "__main__":
    unittest.main()
