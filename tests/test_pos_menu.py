"""POS restaurant menu categories and items (Product Master linked)."""

import os
import tempfile
import unittest
from unittest import mock

import db as db_mod


class PosMenuTests(unittest.TestCase):
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
            product = conn.execute(
                """
                SELECT id, name, approximate_price
                FROM store_products
                WHERE is_active = 1
                ORDER BY id ASC
                LIMIT 1
                """
            ).fetchone()
            self.assertIsNotNone(product)
            self.product_id = int(product["id"])
            self.product_name = product["name"]
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

    def test_empty_categories_then_create_item(self):
        list_res = self.client.get("/point-of-sale/api/menu/categories")
        self.assertEqual(list_res.status_code, 200)
        payload = list_res.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["categories"], [])

        create_cat = self.client.post(
            "/point-of-sale/api/menu/categories",
            json={"name": "Kids Menu", "is_visible": True},
        )
        self.assertEqual(create_cat.status_code, 200)
        cat_payload = create_cat.get_json()
        self.assertTrue(cat_payload["ok"])
        category_id = cat_payload["category"]["id"]
        self.assertEqual(cat_payload["category"]["name"], "Kids Menu")
        self.assertEqual(cat_payload["category"]["item_count"], 0)

        create_item = self.client.post(
            "/point-of-sale/api/menu/items",
            json={
                "category_id": category_id,
                "name": "Kids Meal",
                "code": "K1",
                "rate": 199.5,
                "variant": "Full",
                "recipe": [
                    {"product_id": self.product_id, "qty": 150, "unit": "g"},
                ],
            },
        )
        self.assertEqual(create_item.status_code, 200)
        item_payload = create_item.get_json()
        self.assertTrue(item_payload["ok"])
        item = item_payload["item"]
        self.assertEqual(item["category_id"], category_id)
        self.assertEqual(item["name"], "Kids Meal")
        self.assertEqual(item["code"], "K1")
        self.assertEqual(item["variant"], "Full")
        self.assertAlmostEqual(float(item["rate"]), 199.5)
        self.assertEqual(len(item["recipe"]), 1)
        self.assertEqual(item["recipe"][0]["product_id"], self.product_id)
        self.assertAlmostEqual(float(item["recipe"][0]["qty"]), 150)
        self.assertEqual(item["recipe"][0]["unit"], "g")

        items_res = self.client.get(
            f"/point-of-sale/api/menu/items?category_id={category_id}"
        )
        self.assertEqual(items_res.status_code, 200)
        items_payload = items_res.get_json()
        self.assertTrue(items_payload["ok"])
        self.assertEqual(len(items_payload["items"]), 1)
        self.assertEqual(items_payload["items"][0]["id"], item["id"])
        self.assertEqual(len(items_payload["items"][0]["recipe"]), 1)

        cats_again = self.client.get("/point-of-sale/api/menu/categories").get_json()
        kids = next(c for c in cats_again["categories"] if c["id"] == category_id)
        self.assertEqual(kids["item_count"], 1)

    def test_recipe_multi_product_and_update(self):
        conn = db_mod.get_db()
        try:
            products = conn.execute(
                """
                SELECT id FROM store_products
                WHERE is_active = 1
                ORDER BY id ASC
                LIMIT 2
                """
            ).fetchall()
        finally:
            conn.close()
        self.assertGreaterEqual(len(products), 2)
        p1 = int(products[0]["id"])
        p2 = int(products[1]["id"])

        cat = self.client.post(
            "/point-of-sale/api/menu/categories",
            json={"name": "Recipe Cat", "is_visible": True},
        ).get_json()["category"]

        created = self.client.post(
            "/point-of-sale/api/menu/items",
            json={
                "category_id": cat["id"],
                "name": "Mixed Grill",
                "rate": 420,
                "recipe": [
                    {"product_id": p1, "qty": 100, "unit": "g"},
                    {"product_id": p2, "qty": 2, "unit": "pcs"},
                ],
            },
        )
        self.assertEqual(created.status_code, 200)
        body = created.get_json()
        self.assertTrue(body["ok"])
        item = body["item"]
        self.assertEqual(len(item["recipe"]), 2)

        updated = self.client.post(
            "/point-of-sale/api/menu/items",
            json={
                "id": item["id"],
                "category_id": cat["id"],
                "name": "Mixed Grill",
                "rate": 450,
                "recipe": [
                    {"product_id": p2, "qty": 3, "unit": "pcs"},
                ],
            },
        )
        self.assertEqual(updated.status_code, 200)
        up = updated.get_json()["item"]
        self.assertAlmostEqual(float(up["rate"]), 450)
        self.assertEqual(len(up["recipe"]), 1)
        self.assertEqual(up["recipe"][0]["product_id"], p2)
        self.assertAlmostEqual(float(up["recipe"][0]["qty"]), 3)

    def test_list_all_menu_items_without_category_filter(self):
        """Invoice search loads all active items via GET /menu/items (no category_id)."""
        cat = self.client.post(
            "/point-of-sale/api/menu/categories",
            json={"name": "Invoice Search Cat", "is_visible": True},
        ).get_json()["category"]

        created = self.client.post(
            "/point-of-sale/api/menu/items",
            json={
                "category_id": cat["id"],
                "name": "Masala Chai",
                "code": "MC99",
                "rate": 45,
                "variant": "Regular",
            },
        )
        self.assertEqual(created.status_code, 200)
        item = created.get_json()["item"]

        res = self.client.get("/point-of-sale/api/menu/items")
        self.assertEqual(res.status_code, 200)
        payload = res.get_json()
        self.assertTrue(payload["ok"])
        self.assertIsNone(payload["category_id"])
        ids = {row["id"] for row in payload["items"]}
        self.assertIn(item["id"], ids)
        match = next(row for row in payload["items"] if row["id"] == item["id"])
        self.assertEqual(match["name"], "Masala Chai")
        self.assertEqual(match["code"], "MC99")
        self.assertAlmostEqual(float(match["rate"]), 45)

    def test_products_lite_available(self):
        res = self.client.get("/point-of-sale/api/menu/products")
        self.assertEqual(res.status_code, 200)
        payload = res.get_json()
        self.assertTrue(payload["ok"])
        self.assertGreaterEqual(len(payload["products"]), 1)
        row = payload["products"][0]
        self.assertIn("id", row)
        self.assertIn("name", row)
        self.assertIn("default_unit", row)

        alt = self.client.get("/stores/api/products-lite")
        self.assertEqual(alt.status_code, 200)
        self.assertTrue(alt.get_json()["ok"])


if __name__ == "__main__":
    unittest.main()
