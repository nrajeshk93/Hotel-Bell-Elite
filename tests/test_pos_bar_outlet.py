"""Bar POS outlet isolation — floor seed + Restaurant vs Bar bills."""

import os
import tempfile
import unittest
from unittest import mock

import db as db_mod


class PosBarOutletTests(unittest.TestCase):
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

    def test_bar_floor_seeded_from_venue_sheet(self):
        res = self.client.get("/bar-point-of-sale/api/floor")
        self.assertEqual(res.status_code, 200)
        payload = res.get_json()
        self.assertTrue(payload["ok"])
        area_names = {a["name"] for a in payload["areas"]}
        self.assertEqual(area_names, {"Tables", "Counter"})
        tables = payload["tables"]
        self.assertEqual(len(tables), 22)
        by_name = {t["name"]: t for t in tables}
        self.assertEqual(by_name["Table 1"]["seats"], 4)
        self.assertEqual(by_name["Table 16"]["seats"], 4)
        self.assertEqual(by_name["Chair 1"]["seats"], 1)
        self.assertEqual(by_name["Chair 6"]["seats"], 1)

    def test_restaurant_floor_empty_independent_of_bar(self):
        res = self.client.get("/point-of-sale/api/floor")
        self.assertEqual(res.status_code, 200)
        payload = res.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["areas"], [])
        self.assertEqual(payload["tables"], [])

    def test_same_table_name_isolated_by_outlet(self):
        # Restaurant floor with Table 1
        put = self.client.put(
            "/point-of-sale/api/floor",
            json={
                "areas": [{"id": "main", "type": "area", "name": "Main"}],
                "tables": [
                    {
                        "id": "rt1",
                        "type": "table",
                        "name": "Table 1",
                        "seats": 4,
                        "shape": "square",
                        "status": "available",
                        "areaId": "main",
                    }
                ],
            },
        )
        self.assertEqual(put.status_code, 200)

        # Occupy Restaurant Table 1 via open bill
        save = self.client.post(
            "/point-of-sale/api/invoices",
            json={
                "orderNo": "ORD-REST-T1",
                "orderType": "dine_in",
                "table": "Table 1",
                "customerName": "Guest",
                "lines": [{"name": "Tea", "rate": 50, "qty": 1}],
                "totals": {"subtotal": 50, "total": 50},
            },
        )
        self.assertEqual(save.status_code, 200, save.get_json())

        rest_floor = self.client.get("/point-of-sale/api/floor").get_json()
        rest_t1 = next(t for t in rest_floor["tables"] if t["name"] == "Table 1")
        self.assertEqual(rest_t1["status"], "occupied")

        bar_floor = self.client.get("/bar-point-of-sale/api/floor").get_json()
        bar_t1 = next(t for t in bar_floor["tables"] if t["name"] == "Table 1")
        self.assertEqual(bar_t1["status"], "available")

        # Bar can still open its own Table 1 bill
        bar_save = self.client.post(
            "/bar-point-of-sale/api/invoices",
            json={
                "orderNo": "ORD-BAR-T1",
                "orderType": "dine_in",
                "table": "Table 1",
                "customerName": "Guest",
                "lines": [{"name": "Beer", "rate": 200, "qty": 1}],
                "totals": {"subtotal": 200, "total": 200},
            },
        )
        self.assertEqual(bar_save.status_code, 200, bar_save.get_json())

        bar_open = self.client.get(
            "/bar-point-of-sale/api/invoices/by-table?table=Table%201"
        ).get_json()
        self.assertIsNotNone(bar_open.get("invoice"))
        self.assertEqual(bar_open["invoice"]["order_no"], "ORD-BAR-T1")
        self.assertEqual(bar_open["invoice"]["outlet"], "bar")

        rest_open = self.client.get(
            "/point-of-sale/api/invoices/by-table?table=Table%201"
        ).get_json()
        self.assertEqual(rest_open["invoice"]["order_no"], "ORD-REST-T1")
        self.assertEqual(rest_open["invoice"]["outlet"], "restaurant")

    def test_cross_outlet_menu_include(self):
        """Restaurant and Bar POS catalogs can include each other's menu items."""
        rest_cat = self.client.post(
            "/point-of-sale/api/menu/categories",
            json={"name": "Restaurant Mains", "is_visible": True},
        ).get_json()["category"]
        bar_cat = self.client.post(
            "/bar-point-of-sale/api/menu/categories",
            json={"name": "Bar Spirits", "is_visible": True},
        ).get_json()["category"]

        rest_item = self.client.post(
            "/point-of-sale/api/menu/items",
            json={
                "category_id": rest_cat["id"],
                "name": "Butter Chicken",
                "code": "BC01",
                "rate": 320,
                "item_kind": "food",
            },
        ).get_json()["item"]
        bar_item = self.client.post(
            "/bar-point-of-sale/api/menu/items",
            json={
                "category_id": bar_cat["id"],
                "name": "Old Monk Rum",
                "code": "OM60",
                "rate": 180,
                "item_kind": "liquor",
                "menu_type": "liquor",
            },
        ).get_json()["item"]

        default_rest = self.client.get("/point-of-sale/api/menu/items").get_json()
        self.assertTrue(default_rest["ok"])
        default_rest_ids = {row["id"] for row in default_rest["items"]}
        self.assertIn(rest_item["id"], default_rest_ids)
        self.assertNotIn(bar_item["id"], default_rest_ids)

        rest_combined = self.client.get(
            "/point-of-sale/api/menu/items?include_outlets=bar"
        ).get_json()
        self.assertTrue(rest_combined["ok"])
        rest_by_id = {row["id"]: row for row in rest_combined["items"]}
        self.assertIn(rest_item["id"], rest_by_id)
        self.assertIn(bar_item["id"], rest_by_id)
        self.assertEqual(rest_by_id[rest_item["id"]]["outlet"], "restaurant")
        self.assertEqual(rest_by_id[bar_item["id"]]["outlet"], "bar")

        rest_cats = self.client.get(
            "/point-of-sale/api/menu/categories?include_outlets=bar"
        ).get_json()
        self.assertTrue(rest_cats["ok"])
        rest_cat_ids = {row["id"] for row in rest_cats["categories"]}
        self.assertIn(rest_cat["id"], rest_cat_ids)
        self.assertIn(bar_cat["id"], rest_cat_ids)

        default_bar = self.client.get("/bar-point-of-sale/api/menu/items").get_json()
        self.assertTrue(default_bar["ok"])
        default_bar_ids = {row["id"] for row in default_bar["items"]}
        self.assertIn(bar_item["id"], default_bar_ids)
        self.assertNotIn(rest_item["id"], default_bar_ids)

        bar_combined = self.client.get(
            "/bar-point-of-sale/api/menu/items?include_outlets=restaurant"
        ).get_json()
        self.assertTrue(bar_combined["ok"])
        bar_by_id = {row["id"]: row for row in bar_combined["items"]}
        self.assertIn(bar_item["id"], bar_by_id)
        self.assertIn(rest_item["id"], bar_by_id)
        self.assertEqual(bar_by_id[bar_item["id"]]["outlet"], "bar")
        self.assertEqual(bar_by_id[rest_item["id"]]["outlet"], "restaurant")

        bar_cats = self.client.get(
            "/bar-point-of-sale/api/menu/categories?include_outlets=restaurant"
        ).get_json()
        self.assertTrue(bar_cats["ok"])
        bar_cat_ids = {row["id"] for row in bar_cats["categories"]}
        self.assertIn(bar_cat["id"], bar_cat_ids)
        self.assertIn(rest_cat["id"], bar_cat_ids)

        # Wrong peer flag is ignored (Bar cannot include itself via include_outlets=bar).
        bar_self = self.client.get(
            "/bar-point-of-sale/api/menu/items?include_outlets=bar"
        ).get_json()
        bar_self_ids = {row["id"] for row in bar_self["items"]}
        self.assertIn(bar_item["id"], bar_self_ids)
        self.assertNotIn(rest_item["id"], bar_self_ids)

    def test_bar_invoice_save_uses_bar_outlet(self):
        """Bar POS POST must persist outlet=bar (same logic as Restaurant, scoped path)."""
        # Seed a free Bar table so dine-in save is allowed.
        put = self.client.put(
            "/bar-point-of-sale/api/floor",
            json={
                "areas": [{"id": "main", "type": "area", "name": "Main"}],
                "tables": [
                    {
                        "id": "bt1",
                        "type": "table",
                        "name": "Table 1",
                        "seats": 4,
                        "shape": "square",
                        "status": "available",
                        "areaId": "main",
                    }
                ],
            },
        )
        self.assertEqual(put.status_code, 200, put.get_json())

        save = self.client.post(
            "/bar-point-of-sale/api/invoices",
            json={
                "orderNo": "ORD-BAR-SAVE-1",
                "orderType": "dine_in",
                "table": "Table 1",
                "customerName": "Guest",
                "lines": [{"name": "Beer", "rate": 200, "qty": 1}],
                "totals": {"subtotal": 200, "total": 220, "vat": 20},
            },
        )
        self.assertEqual(save.status_code, 200, save.get_json())
        body = save.get_json()
        self.assertTrue(body["ok"])
        inv = body["invoice"]
        self.assertEqual(inv["outlet"], "bar")
        self.assertEqual(inv["order_no"], "ORD-BAR-SAVE-1")
        self.assertEqual(inv["table_label"], "Table 1")

        by_table = self.client.get(
            "/bar-point-of-sale/api/invoices/by-table?table=Table%201"
        ).get_json()
        self.assertIsNotNone(by_table.get("invoice"))
        self.assertEqual(by_table["invoice"]["id"], inv["id"])
        self.assertEqual(by_table["invoice"]["outlet"], "bar")

        # Restaurant must not see the Bar open bill for the same table name.
        rest_open = self.client.get(
            "/point-of-sale/api/invoices/by-table?table=Table%201"
        ).get_json()
        self.assertIsNone(rest_open.get("invoice"))

    def test_bar_page_renders_outlet_context(self):
        res = self.client.get("/bar-point-of-sale")
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertIn('data-pos-outlet="bar"', html)
        self.assertIn('data-pos-api-base="/bar-point-of-sale"', html)

    def test_access_module_mapping(self):
        from workspace_access import get_endpoint_dashboard_module

        self.assertEqual(get_endpoint_dashboard_module("bar_point_of_sale"), "point_of_sale_bar")
        self.assertEqual(get_endpoint_dashboard_module("point_of_sale"), "point_of_sale")


if __name__ == "__main__":
    unittest.main()
