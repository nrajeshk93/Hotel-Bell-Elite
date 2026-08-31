"""Unit Master — product units (bottle, liter, milliliter, …)."""

import os
import tempfile
import unittest
from unittest import mock

import db as db_mod
from db import (
    ensure_stores_schema,
    get_db,
    list_store_product_units,
    save_store_product_unit,
    soft_delete_store_product_unit,
)
from workspace_access import user_can_access_unit_master


class UnitMasterDbTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db_path = self.tmp.name
        self._orig_path = db_mod.DATABASE_PATH
        db_mod.DATABASE_PATH = self.db_path
        db_mod.init_db()
        self.conn = get_db()
        ensure_stores_schema(self.conn)

    def tearDown(self):
        self.conn.close()
        db_mod.DATABASE_PATH = self._orig_path
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def test_seed_includes_bar_restaurant_units(self):
        units = list_store_product_units(self.conn)
        names = {str(u["name"]).lower() for u in units}
        for expected in ("bottle", "liter", "milliliter", "ml", "kg", "pcs"):
            self.assertIn(expected, names)

    def test_create_rename_and_delete(self):
        unit_id = save_store_product_unit(self.conn, name="Case")
        self.conn.commit()
        self.assertTrue(any(u["id"] == unit_id and u["name"] == "Case" for u in list_store_product_units(self.conn)))

        save_store_product_unit(self.conn, unit_id=unit_id, name="Crate")
        self.conn.commit()
        row = next(u for u in list_store_product_units(self.conn) if u["id"] == unit_id)
        self.assertEqual(row["name"], "Crate")

        soft_delete_store_product_unit(self.conn, unit_id)
        self.conn.commit()
        self.assertFalse(any(u["id"] == unit_id for u in list_store_product_units(self.conn)))

    def test_duplicate_rejected(self):
        save_store_product_unit(self.conn, name="Pint")
        self.conn.commit()
        with self.assertRaises(ValueError) as ctx:
            save_store_product_unit(self.conn, name="pint")
        self.assertIn("already exists", str(ctx.exception).lower())

    def test_rename_updates_product_default_unit(self):
        unit_id = save_store_product_unit(self.conn, name="Jigger")
        category = self.conn.execute(
            "SELECT id FROM store_product_categories WHERE is_active = 1 ORDER BY id LIMIT 1"
        ).fetchone()
        self.assertIsNotNone(category)
        self.conn.execute(
            """
            INSERT INTO store_products (category_id, name, outlet, default_unit, is_active)
            VALUES (?, 'Test Spirit', 'bar', 'Jigger', 1)
            """,
            (category["id"],),
        )
        self.conn.commit()

        save_store_product_unit(self.conn, unit_id=unit_id, name="Shot")
        self.conn.commit()
        product = self.conn.execute(
            "SELECT default_unit FROM store_products WHERE name = 'Test Spirit'"
        ).fetchone()
        self.assertEqual(product["default_unit"], "Shot")

    def test_delete_blocked_when_product_uses_unit(self):
        unit_id = save_store_product_unit(self.conn, name="Can")
        category = self.conn.execute(
            "SELECT id FROM store_product_categories WHERE is_active = 1 ORDER BY id LIMIT 1"
        ).fetchone()
        self.assertIsNotNone(category)
        self.conn.execute(
            """
            INSERT INTO store_products (category_id, name, outlet, default_unit, is_active)
            VALUES (?, 'Test Beer', 'bar', 'Can', 1)
            """,
            (category["id"],),
        )
        self.conn.commit()
        with self.assertRaises(ValueError) as ctx:
            soft_delete_store_product_unit(self.conn, unit_id)
        self.assertIn("used by", str(ctx.exception).lower())


class UnitMasterAccessTests(unittest.TestCase):
    def test_admin_and_grants(self):
        self.assertTrue(user_can_access_unit_master({"is_admin": True}))
        self.assertTrue(
            user_can_access_unit_master(
                {"is_admin": False, "master_access": {"unit"}}
            )
        )
        self.assertTrue(
            user_can_access_unit_master(
                {"is_admin": False, "stores_access": {"product_master"}}
            )
        )
        self.assertFalse(
            user_can_access_unit_master(
                {"is_admin": False, "master_access": {"category"}, "stores_access": set()}
            )
        )


class UnitMasterRouteTests(unittest.TestCase):
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
        self._get_user_patch = mock.patch.object(app_mod, "get_current_user", return_value=self.user)
        self._get_user_patch.start()

    def tearDown(self):
        self._get_user_patch.stop()
        db_mod.DATABASE_PATH = self._orig_path
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def test_page_lists_seeded_units(self):
        page = self.client.get("/masters/units")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn("Unit Master", html)
        self.assertIn("bottle", html)
        self.assertIn("liter", html)
        self.assertIn("milliliter", html)

    def test_create_edit_delete_flow(self):
        created = self.client.post(
            "/masters/units/save",
            data={"name": "Barrel"},
            follow_redirects=True,
        )
        self.assertEqual(created.status_code, 200)
        html = created.get_data(as_text=True)
        self.assertIn("Unit created successfully.", html)
        self.assertIn("Barrel", html)

        conn = db_mod.get_db()
        try:
            unit = conn.execute(
                "SELECT id FROM store_product_units WHERE name = 'Barrel' AND is_active = 1"
            ).fetchone()
            self.assertIsNotNone(unit)
            unit_id = unit["id"]
        finally:
            conn.close()

        updated = self.client.post(
            "/masters/units/save",
            data={"unit_id": unit_id, "name": "Keg"},
            follow_redirects=True,
        )
        self.assertEqual(updated.status_code, 200)
        self.assertIn("Unit updated successfully.", updated.get_data(as_text=True))
        self.assertIn("Keg", updated.get_data(as_text=True))

        deleted = self.client.post(
            "/masters/units/delete",
            data={"unit_id": unit_id},
            follow_redirects=True,
        )
        self.assertEqual(deleted.status_code, 200)
        self.assertIn("Unit deleted successfully.", deleted.get_data(as_text=True))

    def test_embed_page(self):
        page = self.client.get("/masters/units?embed=1")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn("md-master-embed", html)
        self.assertIn("um-unit-modal", html)

    def test_denied_without_access(self):
        self.user["is_admin"] = False
        self.user["master_access"] = set()
        self.user["stores_access"] = set()
        page = self.client.get("/masters/units")
        self.assertIn(page.status_code, (403, 302))


if __name__ == "__main__":
    unittest.main()
