"""POS floor layout API — no demo seed on empty database."""

import os
import tempfile
import unittest
from unittest import mock

import db as db_mod


class PosFloorTests(unittest.TestCase):
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

    def test_floor_empty_on_fresh_db(self):
        res = self.client.get("/point-of-sale/api/floor")
        self.assertEqual(res.status_code, 200)
        payload = res.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["areas"], [])
        self.assertEqual(payload["tables"], [])

        conn = db_mod.get_db()
        try:
            row = conn.execute("SELECT id FROM pos_floor_layout WHERE id = 1").fetchone()
        finally:
            conn.close()
        self.assertIsNone(row)

    def test_floor_save_and_load(self):
        body = {
            "areas": [{"id": "area_1", "type": "area", "name": "Main Hall"}],
            "tables": [
                {
                    "id": "t1",
                    "type": "table",
                    "name": "T1",
                    "seats": 4,
                    "shape": "square",
                    "status": "available",
                    "areaId": "area_1",
                }
            ],
        }
        put = self.client.put("/point-of-sale/api/floor", json=body)
        self.assertEqual(put.status_code, 200)
        saved = put.get_json()
        self.assertTrue(saved["ok"])
        self.assertEqual(len(saved["areas"]), 1)
        self.assertEqual(saved["areas"][0]["name"], "Main Hall")
        self.assertEqual(len(saved["tables"]), 1)
        self.assertEqual(saved["tables"][0]["name"], "T1")

        get = self.client.get("/point-of-sale/api/floor")
        self.assertEqual(get.status_code, 200)
        loaded = get.get_json()
        self.assertTrue(loaded["ok"])
        self.assertEqual(loaded["areas"][0]["id"], "area_1")
        self.assertEqual(loaded["tables"][0]["seats"], 4)


if __name__ == "__main__":
    unittest.main()
