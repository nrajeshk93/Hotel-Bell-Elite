import os
import tempfile
import unittest
from unittest import mock

import db as db_mod


class StoresFlowTests(unittest.TestCase):
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

    def tearDown(self):
        self._get_user_patch.stop()
        self._stores_user_patch.stop()
        db_mod.DATABASE_PATH = self._orig_path
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def test_product_master_seeded(self):
        conn = db_mod.get_db()
        try:
            cats = {
                row["name"]: row["id"]
                for row in conn.execute("SELECT id, name FROM store_product_categories").fetchall()
            }
            self.assertIn("Non-Veg", cats)
            self.assertIn("Dairy Products", cats)
            self.assertIn("Vegetable", cats)
            count = conn.execute("SELECT COUNT(*) AS c FROM store_products").fetchone()["c"]
            self.assertGreaterEqual(count, 60)
        finally:
            conn.close()

        page = self.client.get("/stores/product-master")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Products", page.data)
        self.assertIn(b"Non-Veg", page.data)
        self.assertIn(b"Edit", page.data)
        self.assertIn(b"Delete", page.data)

        conn = db_mod.get_db()
        try:
            product = conn.execute(
                """
                SELECT id, name, category_id, default_unit
                FROM store_products WHERE is_active = 1 ORDER BY id LIMIT 1
                """
            ).fetchone()
            self.assertIsNotNone(product)
            pid = product["id"]
            category_id = product["category_id"]
            unit = product["default_unit"] or "kg"
        finally:
            conn.close()

        edit_page = self.client.get(f"/stores/product-master?edit={pid}")
        self.assertEqual(edit_page.status_code, 200)
        self.assertIn(b"Edit product", edit_page.data)

        update = self.client.post(
            "/stores/product-master",
            data={
                "action": "save_product",
                "product_id": str(pid),
                "category_id": str(category_id),
                "name": "Updated Product Name",
                "default_unit": unit,
            },
            follow_redirects=True,
        )
        self.assertEqual(update.status_code, 200)
        self.assertIn(b"Product updated", update.data)

        delete = self.client.get(f"/stores/product-master/{pid}/delete", follow_redirects=True)
        self.assertEqual(delete.status_code, 200)
        conn = db_mod.get_db()
        try:
            gone = conn.execute(
                "SELECT is_active FROM store_products WHERE id = ?", (pid,)
            ).fetchone()
            self.assertEqual(int(gone["is_active"]), 0)
        finally:
            conn.close()

    def test_indent_to_stock_happy_path(self):
        # Create + submit indent
        resp = self.client.post(
            "/stores/indent?outlet=bar",
            data={
                "outlet": "bar",
                "action": "submit",
                "notes": "Evening bar needs",
                "item_name": ["Onion", "Potato"],
                "quantity": ["10", "24"],
                "unit": ["kg", "kg"],
                "line_notes": ["", ""],
            },
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 302)

        conn = db_mod.get_db()
        try:
            indent = conn.execute(
                "SELECT * FROM store_indents WHERE outlet = 'bar' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            self.assertIsNotNone(indent)
            self.assertEqual(indent["status"], "pending")
            indent_id = indent["id"]
        finally:
            conn.close()

        # Approve
        resp = self.client.post(
            f"/stores/indent/{indent_id}/decide",
            data={"outlet": "bar", "decision": "approved", "decision_note": ""},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 302)

        # Create PR from indent
        resp = self.client.post(
            "/stores/purchase-requests?outlet=bar",
            data={
                "outlet": "bar",
                "action": "create_from_indent",
                "indent_id": str(indent_id),
            },
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 302)

        conn = db_mod.get_db()
        try:
            pr = conn.execute(
                "SELECT * FROM store_purchase_requests WHERE indent_id = ?",
                (indent_id,),
            ).fetchone()
            self.assertIsNotNone(pr)
            pr_id = pr["id"]
        finally:
            conn.close()

        # Receive into stock
        resp = self.client.post(
            f"/stores/purchase-requests/{pr_id}/receive",
            data={"outlet": "bar"},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 302)

        conn = db_mod.get_db()
        try:
            stock = {
                (row["item_name"], row["unit"]): row["qty_on_hand"]
                for row in conn.execute(
                    "SELECT item_name, unit, qty_on_hand FROM store_stock_items WHERE outlet = 'bar'"
                ).fetchall()
            }
            self.assertEqual(stock[("Onion", "kg")], 10)
            self.assertEqual(stock[("Potato", "kg")], 24)
        finally:
            conn.close()

        # Pages render
        for path in (
            "/stores/indent?outlet=bar",
            "/stores/approvals?outlet=bar",
            "/stores/purchase-requests?outlet=bar",
            "/stores/stock?outlet=bar",
            "/stores/counter-transfer?outlet=bar",
            "/stores/stock-verification?outlet=bar",
            "/stores/stock-issues?outlet=bar",
            "/stores?outlet=kitchen",
        ):
            page = self.client.get(path, follow_redirects=True)
            self.assertEqual(page.status_code, 200, path)


if __name__ == "__main__":
    unittest.main()
