"""Agency Master CRUD."""

import os
import tempfile
import unittest
from unittest import mock

import db as db_mod
from db import (
    ensure_agencies_schema,
    get_agency,
    get_db,
    list_agencies,
    save_agency_record,
    upsert_agency_by_name,
)


class AgencyMasterDbTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db_path = self.tmp.name
        self._orig_path = db_mod.DATABASE_PATH
        db_mod.DATABASE_PATH = self.db_path
        db_mod.init_db()
        self.conn = get_db()
        ensure_agencies_schema(self.conn)

    def tearDown(self):
        self.conn.close()
        db_mod.DATABASE_PATH = self._orig_path
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def test_save_list_and_upsert(self):
        saved_id, errors = save_agency_record(
            self.conn, "MakeMyTrip", "27AAAAA0000A1Z5", "Mumbai"
        )
        self.assertEqual(errors, [])
        self.assertIsNotNone(saved_id)
        self.conn.commit()

        agencies = list_agencies(self.conn)
        self.assertEqual(len(agencies), 1)
        self.assertEqual(agencies[0]["name"], "MakeMyTrip")

        dup_id, dup_errors = save_agency_record(self.conn, "makemytrip", "X", "Y")
        self.assertIsNone(dup_id)
        self.assertTrue(any("already exists" in e.lower() for e in dup_errors))

        updated = upsert_agency_by_name(self.conn, "MakeMyTrip", "27BBBBB0000B1Z5", "")
        self.assertEqual(updated["gst"], "27BBBBB0000B1Z5")
        self.assertEqual(updated["address"], "Mumbai")
        self.assertEqual(get_agency(self.conn, saved_id)["gst"], "27BBBBB0000B1Z5")


class AgencyMasterRouteTests(unittest.TestCase):
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

    def test_create_and_list_api(self):
        created = self.client.post(
            "/agencies/create",
            json={"name": "Booking.com", "gst": "29CCCCC0000C1Z5", "address": "Bengaluru"},
        )
        self.assertEqual(created.status_code, 200)
        body = created.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["agency"]["name"], "Booking.com")

        listed = self.client.get("/agencies/api")
        self.assertEqual(listed.status_code, 200)
        agencies = listed.get_json()["agencies"]
        self.assertTrue(any(a["name"] == "Booking.com" for a in agencies))

        page = self.client.get("/agencies")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn("Agency Master", html)
        self.assertIn("Booking.com", html)

    def test_master_hub_includes_agency_card(self):
        page = self.client.get("/master")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn("Agency Master", html)
        self.assertIn("/agencies", html)


if __name__ == "__main__":
    unittest.main()
