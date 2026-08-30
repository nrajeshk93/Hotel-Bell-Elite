"""Application license page, API, and expiry lockout."""

import os
import tempfile
import unittest
from datetime import date, timedelta
from unittest import mock

import db as db_mod


class AppLicenseTests(unittest.TestCase):
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
            from datetime import datetime as dt

            now = dt.now().strftime("%Y-%m-%d %H:%M:%S")
            conn.execute(
                """
                INSERT INTO users (
                    username, full_name, password_hash, is_admin, is_active,
                    created_at, updated_at
                ) VALUES (?, ?, ?, 0, 1, ?, ?)
                """,
                ("clerk", "Front Desk", "x", now, now),
            )
            conn.commit()
            clerk = conn.execute("SELECT id FROM users WHERE username = 'clerk'").fetchone()
            self.clerk_id = clerk["id"]
        finally:
            conn.close()

        self.admin = {
            "id": self.admin_id,
            "username": "admin",
            "full_name": "Administrator",
            "is_admin": True,
            "is_active": True,
            "dashboard_access": {"settings", "home"},
            "stores_access": set(),
        }
        self.clerk = {
            "id": self.clerk_id,
            "username": "clerk",
            "full_name": "Front Desk",
            "is_admin": False,
            "is_active": True,
            "dashboard_access": {"settings", "home"},
            "stores_access": set(),
        }
        self._user = self.admin
        self._get_user_patch = mock.patch.object(
            app_mod, "get_current_user", side_effect=lambda: self._user
        )
        self._get_user_patch.start()

    def tearDown(self):
        self._get_user_patch.stop()
        db_mod.DATABASE_PATH = self._orig_path
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def _expire_license(self):
        conn = db_mod.get_db()
        try:
            yesterday = (date.today() - timedelta(days=1)).isoformat()
            last_year = (date.today() - timedelta(days=400)).isoformat()
            db_mod.update_app_license(
                conn,
                valid_from=last_year,
                valid_to=yesterday,
                note="Force expire for test",
                updated_by="test",
            )
            conn.commit()
        finally:
            conn.close()

    def test_seed_license_is_active(self):
        conn = db_mod.get_db()
        try:
            row = db_mod.get_app_license(conn)
            self.assertIsNotNone(row)
            self.assertTrue(db_mod.license_is_active(conn))
            self.assertIn(row["status"], ("active", "expiring_soon"))
            renewals = db_mod.list_license_renewals(conn)
            self.assertGreaterEqual(len(renewals), 1)
        finally:
            conn.close()

    def test_admin_can_view_license_page_and_nav(self):
        self._user = self.admin
        page = self.client.get("/license")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn('id="license-page"', html)
        self.assertIn("License Status", html)
        self.assertIn("License Details", html)
        self.assertNotIn("Update license", html)
        self.assertIn("de-nav-license-group", html)
        self.assertIn("Hotel Bell Elite", html)

    def test_non_admin_blocked_when_active(self):
        self._user = self.clerk
        page = self.client.get("/license")
        self.assertIn(page.status_code, (302, 403))

    def test_admin_update_extends_and_writes_history(self):
        self._user = self.admin
        new_to = (date.today() + timedelta(days=400)).isoformat()
        resp = self.client.put(
            "/license/api",
            json={
                "valid_to": new_to,
                "valid_from": date.today().isoformat(),
                "license_type": "Business Standard",
                "license_key": "HBE-TEST-KEY",
                "note": "Renewed in test",
            },
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("ok"))
        self.assertEqual(data["license"]["valid_to"], new_to)
        self.assertEqual(data["license"]["license_key"], "HBE-TEST-KEY")
        notes = [r.get("note") for r in data.get("renewals") or []]
        self.assertIn("Renewed in test", notes)

        conn = db_mod.get_db()
        try:
            self.assertTrue(db_mod.license_is_active(conn))
            row = db_mod.get_app_license(conn)
            self.assertEqual(row["valid_to"], new_to)
        finally:
            conn.close()

    def test_non_admin_cannot_put(self):
        self._user = self.clerk
        resp = self.client.put(
            "/license/api",
            json={"valid_to": (date.today() + timedelta(days=30)).isoformat()},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        self.assertEqual(resp.status_code, 403)

    def test_expired_blocks_home_and_allows_license(self):
        self._expire_license()
        self._user = self.clerk
        blocked = self.client.get("/home")
        self.assertEqual(blocked.status_code, 302)
        self.assertIn("/license", blocked.headers.get("Location", ""))

        page = self.client.get("/license")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn("Expired", html)
        self.assertIn("de-nav-license-group", html)

        xhr = self.client.get(
            "/settings",
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        self.assertEqual(xhr.status_code, 403)
        body = xhr.get_json()
        self.assertTrue(body.get("license_expired"))

    def test_admin_can_renew_when_expired(self):
        self._expire_license()
        self._user = self.admin
        new_to = (date.today() + timedelta(days=180)).isoformat()
        resp = self.client.put(
            "/license/api",
            json={
                "valid_from": date.today().isoformat(),
                "valid_to": new_to,
                "note": "Emergency renew",
            },
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json().get("ok"))
        home = self.client.get("/home")
        self.assertEqual(home.status_code, 200)


if __name__ == "__main__":
    unittest.main()
