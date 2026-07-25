"""POS invoice close → automatic store stock deduction from menu recipes."""

import os
import tempfile
import unittest
from unittest import mock

import db as db_mod


class PosStockDeductionTests(unittest.TestCase):
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

            # Dedicated product + stock so unit math is deterministic.
            cat = conn.execute(
                "SELECT id FROM store_product_categories WHERE is_active = 1 ORDER BY id LIMIT 1"
            ).fetchone()
            if not cat:
                conn.execute(
                    "INSERT INTO store_product_categories (name, sort_order, is_active) VALUES ('Dairy', 10, 1)"
                )
                cat_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            else:
                cat_id = cat["id"]

            conn.execute(
                """
                INSERT INTO store_products
                    (category_id, name, default_unit, outlet, approximate_price, is_active, sort_order)
                VALUES (?, 'Strawberry Ice Cream', 'kg', 'restaurant', 250, 1, 1)
                """,
                (cat_id,),
            )
            self.product_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.execute(
                """
                INSERT INTO store_stock_items (outlet, item_name, unit, qty_on_hand, updated_at)
                VALUES ('restaurant', 'Strawberry Ice Cream', 'kg', 5.0, datetime('now','localtime'))
                """
            )
            conn.execute(
                """
                INSERT INTO store_stock_movements
                    (outlet, item_name, unit, qty_delta, movement_type, ref_type, ref_id,
                     notes, created_by, created_at)
                VALUES ('restaurant', 'Strawberry Ice Cream', 'kg', 5.0, 'receive',
                        'test_seed', NULL, 'test seed', ?, datetime('now','localtime'))
                """,
                (self.admin_id,),
            )

            conn.execute(
                """
                INSERT INTO pos_menu_categories (name, sort_order, is_visible, is_active)
                VALUES ('Desserts', 1, 1, 1)
                """
            )
            self.category_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.execute(
                """
                INSERT INTO pos_menu_items
                    (category_id, product_id, name, code, variant, rate, sort_order, is_active)
                VALUES (?, ?, 'Strawberry Scoop', 'SS1', 'Regular', 120, 1, 1)
                """,
                (self.category_id, self.product_id),
            )
            self.menu_item_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            # Recipe: 150 g per portion → 0.15 kg in product units.
            conn.execute(
                """
                INSERT INTO pos_menu_recipe_lines (menu_item_id, product_id, qty, unit, sort_order)
                VALUES (?, ?, 150, 'g', 1)
                """,
                (self.menu_item_id, self.product_id),
            )
            conn.commit()
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

    def _payload(self, order_no, qty=2, *, menu_id=None):
        mid = self.menu_item_id if menu_id is None else menu_id
        line_total = 120 * qty
        return {
            "orderNo": order_no,
            "savedAt": "2026-07-25 10:00:00",
            "orderType": "dine_in",
            "table": "T1",
            "captain": "",
            "customerName": "Guest",
            "customerMobile": "9876543210",
            "notes": "",
            "discountType": "pct",
            "discountValue": 0,
            "serviceType": "pct",
            "serviceValue": 0,
            "tipAmount": 0,
            "couponCode": "",
            "lines": [
                {
                    "uid": "1",
                    "menuId": mid,
                    "name": "Strawberry Scoop",
                    "variant": "Regular",
                    "rate": 120,
                    "qty": qty,
                }
            ],
            "totals": {
                "subtotal": line_total,
                "discount": 0,
                "discountType": "pct",
                "discountValue": 0,
                "gst": 0,
                "service": 0,
                "serviceType": "pct",
                "serviceValue": 0,
                "tip": 0,
                "roundOff": 0,
                "total": line_total,
            },
        }

    def _on_hand(self, name="Strawberry Ice Cream", unit="kg", outlet="restaurant"):
        conn = db_mod.get_db()
        try:
            row = conn.execute(
                """
                SELECT qty_on_hand FROM store_stock_items
                WHERE outlet = ? AND lower(item_name) = lower(?) AND lower(unit) = lower(?)
                """,
                (outlet, name, unit),
            ).fetchone()
            return float(row["qty_on_hand"]) if row else None
        finally:
            conn.close()

    def _sale_movements(self, invoice_id):
        conn = db_mod.get_db()
        try:
            return conn.execute(
                """
                SELECT * FROM store_stock_movements
                WHERE ref_type = 'pos_invoice' AND ref_id = ?
                ORDER BY id ASC
                """,
                (invoice_id,),
            ).fetchall()
        finally:
            conn.close()

    def test_close_deducts_recipe_ingredients_and_records_sale_movement(self):
        saved = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload("ORD-STOCK-0001", qty=2),
        )
        self.assertEqual(saved.status_code, 200, saved.get_data(as_text=True))
        invoice_id = saved.get_json()["invoice"]["id"]
        self.assertEqual(self._on_hand(), 5.0)

        # Saving alone must not deduct.
        self.assertEqual(len(self._sale_movements(invoice_id)), 0)

        close = self.client.post(f"/point-of-sale/api/invoices/{invoice_id}/close")
        self.assertEqual(close.status_code, 200, close.get_data(as_text=True))
        closed = close.get_json()["invoice"]
        self.assertEqual(closed["status"], "closed")
        self.assertTrue(closed.get("stock_deducted_at"))

        # 2 portions × 150 g = 300 g = 0.3 kg
        self.assertAlmostEqual(self._on_hand(), 4.7, places=3)

        moves = self._sale_movements(invoice_id)
        self.assertEqual(len(moves), 1)
        self.assertEqual(moves[0]["movement_type"], "sale")
        self.assertAlmostEqual(float(moves[0]["qty_delta"]), -0.3, places=3)
        self.assertEqual(moves[0]["item_name"], "Strawberry Ice Cream")
        self.assertIn("ORD-STOCK-0001", moves[0]["notes"] or "")

    def test_close_is_idempotent_no_double_deduct(self):
        saved = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload("ORD-STOCK-0002", qty=2),
        )
        invoice_id = saved.get_json()["invoice"]["id"]

        self.client.post(f"/point-of-sale/api/invoices/{invoice_id}/close")
        self.assertAlmostEqual(self._on_hand(), 4.7, places=3)

        # Second close (reprint / re-save path) must not deduct again.
        again = self.client.post(f"/point-of-sale/api/invoices/{invoice_id}/close")
        self.assertEqual(again.status_code, 200)
        self.assertAlmostEqual(self._on_hand(), 4.7, places=3)
        self.assertEqual(len(self._sale_movements(invoice_id)), 1)

    def test_insufficient_stock_partial_deduct_does_not_block_close(self):
        conn = db_mod.get_db()
        try:
            conn.execute(
                """
                UPDATE store_stock_items
                SET qty_on_hand = 0.1
                WHERE outlet = 'restaurant' AND lower(item_name) = lower('Strawberry Ice Cream')
                """
            )
            conn.commit()
        finally:
            conn.close()

        saved = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload("ORD-STOCK-0003", qty=2),
        )
        invoice_id = saved.get_json()["invoice"]["id"]

        close = self.client.post(f"/point-of-sale/api/invoices/{invoice_id}/close")
        self.assertEqual(close.status_code, 200)
        self.assertEqual(close.get_json()["invoice"]["status"], "closed")
        # Needed 0.3 kg; only 0.1 available → clamp to zero on hand.
        self.assertAlmostEqual(self._on_hand(), 0.0, places=3)
        moves = self._sale_movements(invoice_id)
        self.assertEqual(len(moves), 1)
        self.assertAlmostEqual(float(moves[0]["qty_delta"]), -0.1, places=3)

    def test_missing_recipe_still_closes_without_crash(self):
        conn = db_mod.get_db()
        try:
            conn.execute(
                """
                INSERT INTO pos_menu_items
                    (category_id, product_id, name, code, variant, rate, sort_order, is_active)
                VALUES (?, NULL, 'Plain Toast', 'PT1', '', 40, 2, 1)
                """,
                (self.category_id,),
            )
            bare_menu_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.commit()
        finally:
            conn.close()

        saved = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload("ORD-STOCK-0004", qty=1, menu_id=bare_menu_id),
        )
        invoice_id = saved.get_json()["invoice"]["id"]
        before = self._on_hand()

        close = self.client.post(f"/point-of-sale/api/invoices/{invoice_id}/close")
        self.assertEqual(close.status_code, 200)
        self.assertEqual(close.get_json()["invoice"]["status"], "closed")
        self.assertTrue(close.get_json()["invoice"].get("stock_deducted_at"))
        self.assertEqual(self._on_hand(), before)
        self.assertEqual(len(self._sale_movements(invoice_id)), 0)

    def test_open_save_does_not_deduct(self):
        saved = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload("ORD-STOCK-0005", qty=3),
        )
        self.assertEqual(saved.status_code, 200)
        invoice_id = saved.get_json()["invoice"]["id"]
        self.assertEqual(saved.get_json()["invoice"]["status"], "open")
        self.assertEqual(self._on_hand(), 5.0)
        self.assertEqual(len(self._sale_movements(invoice_id)), 0)


if __name__ == "__main__":
    unittest.main()
