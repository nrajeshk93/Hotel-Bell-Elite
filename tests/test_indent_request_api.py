import os
import tempfile
import unittest
from unittest import mock

import db as db_mod


class IndentRequestApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db_path = self.tmp.name
        self._orig_path = db_mod.DATABASE_PATH
        db_mod.DATABASE_PATH = self.db_path
        db_mod.init_db()

        import app as app_mod
        import stores as stores_mod

        self.app_mod = app_mod
        self.stores_mod = stores_mod
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
        self._stores_user_patch = mock.patch.object(stores_mod, "_get_user", return_value=self.user)
        self._get_user_patch.start()
        self._stores_user_patch.start()

        # CRITICAL: never hit live Meta/WhatsApp while exercising indent submit flows.
        self._wa_buttons_patch = mock.patch(
            "whatsapp_indent.wa.send_interactive_buttons",
            return_value=(True, "", {"messages": [{"id": "wamid.BTN"}]}),
        )
        self._wa_buttons_patch.start()

    def tearDown(self):
        self._wa_buttons_patch.stop()
        self._get_user_patch.stop()
        self._stores_user_patch.stop()
        db_mod.DATABASE_PATH = self._orig_path
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def _restaurant_product(self):
        conn = db_mod.get_db()
        try:
            row = conn.execute(
                """
                SELECT name, default_unit, approximate_price, outlet
                FROM store_products
                WHERE is_active = 1
                  AND lower(coalesce(outlet, '')) IN ('restaurant', 'both')
                ORDER BY id
                LIMIT 1
                """
            ).fetchone()
            self.assertIsNotNone(row)
            return dict(row)
        finally:
            conn.close()

    def test_catalog_401_without_user(self):
        with mock.patch.object(self.stores_mod, "_get_user", return_value=None):
            resp = self.client.get("/stores/api/indent-catalog?outlet=restaurant")
        self.assertEqual(resp.status_code, 401)
        data = resp.get_json()
        self.assertFalse(data.get("ok"))

    def test_catalog_400_if_outlet_missing_or_both(self):
        missing = self.client.get("/stores/api/indent-catalog")
        self.assertEqual(missing.status_code, 400)
        self.assertEqual(missing.get_json().get("error"), "Choose Bar or Restaurant.")
        both = self.client.get("/stores/api/indent-catalog?outlet=both")
        self.assertEqual(both.status_code, 400)
        self.assertEqual(both.get_json().get("error"), "Choose Bar or Restaurant.")

    def test_catalog_restaurant_includes_restaurant_and_both(self):
        resp = self.client.get("/stores/api/indent-catalog?outlet=restaurant")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("ok"))
        self.assertEqual(data.get("outlet"), "restaurant")
        products = []
        for cat in data.get("categories") or []:
            for product in cat.get("products") or []:
                products.append(product)
                self.assertIn(product.get("outlet"), ("restaurant", "both"))
                self.assertIn("approximate_price", product)
                self.assertIn("approximate_price_display", product)
                self.assertIn("variants", product)
                self.assertIsInstance(product.get("variants"), list)
        self.assertGreater(len(products), 0)

    def test_create_submit_pending_persists_line(self):
        product = self._restaurant_product()
        resp = self.client.post(
            "/stores/api/indent",
            json={
                "outlet": "restaurant",
                "notes": "mobile submit",
                "action": "submit",
                "lines": [{
                    "item_name": product["name"],
                    "quantity": 2,
                    "unit": product["default_unit"] or "kg",
                    "approximate_price": 12.5,
                    "pack_label": "",
                    "pack_qty_in_base": None,
                }],
            },
        )
        self.assertEqual(resp.status_code, 200, resp.get_json())
        data = resp.get_json()
        self.assertTrue(data.get("ok"))
        self.assertEqual(data.get("status"), "pending")
        self.assertTrue(data.get("indent_no"))
        indent_id = data["indent_id"]
        conn = db_mod.get_db()
        try:
            indent = conn.execute(
                "SELECT * FROM store_indents WHERE id = ?", (indent_id,)
            ).fetchone()
            self.assertEqual(indent["status"], "pending")
            self.assertEqual(indent["indent_no"], data["indent_no"])
            line = conn.execute(
                "SELECT * FROM store_indent_lines WHERE indent_id = ?",
                (indent_id,),
            ).fetchone()
            self.assertEqual(line["item_name"], product["name"])
            self.assertEqual(float(line["quantity"]), 2.0)
            self.assertEqual(float(line["approximate_price"]), 12.5)
        finally:
            conn.close()

    def test_create_save_draft(self):
        product = self._restaurant_product()
        resp = self.client.post(
            "/stores/api/indent",
            json={
                "outlet": "restaurant",
                "notes": "mobile draft",
                "action": "save",
                "lines": [{
                    "item_name": product["name"],
                    "quantity": 1,
                    "unit": "kg",
                    "approximate_price": 10,
                }],
            },
        )
        self.assertEqual(resp.status_code, 200, resp.get_json())
        data = resp.get_json()
        self.assertEqual(data.get("status"), "draft")
        conn = db_mod.get_db()
        try:
            indent = conn.execute(
                "SELECT status FROM store_indents WHERE id = ?",
                (data["indent_id"],),
            ).fetchone()
            self.assertEqual(indent["status"], "draft")
        finally:
            conn.close()

    def test_create_missing_price_or_qty_400(self):
        product = self._restaurant_product()
        missing_qty = self.client.post(
            "/stores/api/indent",
            json={
                "outlet": "restaurant",
                "action": "save",
                "lines": [{"item_name": product["name"], "quantity": 0, "unit": "kg", "approximate_price": 10}],
            },
        )
        self.assertEqual(missing_qty.status_code, 400)
        self.assertIn("quantity", (missing_qty.get_json().get("error") or "").lower())
        missing_price = self.client.post(
            "/stores/api/indent",
            json={
                "outlet": "restaurant",
                "action": "save",
                "lines": [{"item_name": product["name"], "quantity": 1, "unit": "kg", "approximate_price": 0}],
            },
        )
        self.assertEqual(missing_price.status_code, 400)
        self.assertIn("price", (missing_price.get_json().get("error") or "").lower())

    def test_create_unknown_item_400(self):
        resp = self.client.post(
            "/stores/api/indent",
            json={
                "outlet": "restaurant",
                "action": "save",
                "lines": [{
                    "item_name": "ZZZ_NOT_IN_MASTER_xyz",
                    "quantity": 1,
                    "unit": "kg",
                    "approximate_price": 10,
                }],
            },
        )
        self.assertEqual(resp.status_code, 400)
        error = resp.get_json().get("error") or ""
        self.assertIn("product master", error.lower())
        self.assertIn("ZZZ_NOT_IN_MASTER_xyz", error)

    def test_create_outlet_both_400(self):
        product = self._restaurant_product()
        resp = self.client.post(
            "/stores/api/indent",
            json={
                "outlet": "both",
                "action": "save",
                "lines": [{
                    "item_name": product["name"],
                    "quantity": 1,
                    "unit": "kg",
                    "approximate_price": 10,
                }],
            },
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Bar or Restaurant", resp.get_json().get("error") or "")

    def test_mobile_module_access_indent_request(self):
        from workspace_access import mobile_module_access

        admin = mobile_module_access(self.user)
        self.assertTrue(admin.get("indent_request"))
        self.assertTrue(admin.get("indent_approvals"))

        none = mobile_module_access(None)
        self.assertFalse(none.get("indent_request"))
        self.assertFalse(none.get("indent_approvals"))

        no_indent = {
            "id": 91,
            "is_admin": False,
            "is_active": True,
            "dashboard_access": set(),
            "stores_access": set(),
        }
        flags = mobile_module_access(no_indent)
        self.assertFalse(flags.get("indent_request"))

        indent_only = {
            "id": 92,
            "is_admin": False,
            "is_active": True,
            "dashboard_access": set(),
            "stores_access": {"indent"},
        }
        indent_flags = mobile_module_access(indent_only)
        self.assertTrue(indent_flags.get("indent_request"))
        self.assertFalse(indent_flags.get("indent_approvals"))

        approver = {
            "id": 93,
            "is_admin": False,
            "is_active": True,
            "dashboard_access": {"approval"},
            "stores_access": set(),
        }
        approve_flags = mobile_module_access(approver)
        self.assertFalse(approve_flags.get("indent_request"))
        self.assertTrue(approve_flags.get("indent_approvals"))


if __name__ == "__main__":
    unittest.main()
