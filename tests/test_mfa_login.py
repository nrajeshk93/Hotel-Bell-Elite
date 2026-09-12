"""Opt-in TOTP MFA login flow tests."""

from __future__ import annotations

import os
import tempfile
import time
import unittest
from unittest import mock

import pyotp
from werkzeug.security import generate_password_hash

import db as db_mod
import mfa_totp


class MfaLoginTests(unittest.TestCase):
    def setUp(self):
        # Tests exercise MFA; production default is disabled via HBE_MFA_ENABLED=0.
        import os
        os.environ["HBE_MFA_ENABLED"] = "1"
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
            conn.execute(
                """
                INSERT INTO access_roles
                  (name, description, is_admin, is_active, created_at, updated_at)
                VALUES (?, ?, 0, 1, datetime('now','localtime'), datetime('now','localtime'))
                """,
                ("Staff", "Test staff role"),
            )
            staff_role_id = conn.execute(
                "SELECT id FROM access_roles WHERE name = ?",
                ("Staff",),
            ).fetchone()["id"]
            conn.execute(
                """
                INSERT INTO users
                  (username, full_name, email, password_hash, is_admin, is_active,
                   role_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, 0, 1, ?, datetime('now','localtime'), datetime('now','localtime'))
                """,
                (
                    "mfauser",
                    "MFA User",
                    "mfa@example.com",
                    generate_password_hash("Secret123!"),
                    staff_role_id,
                ),
            )
            conn.commit()
            self.user_id = conn.execute(
                "SELECT id FROM users WHERE username = 'mfauser'"
            ).fetchone()["id"]
        finally:
            conn.close()

        # Confirm MFA columns exist after init_db migration.
        cols = {
            r["name"]
            for r in db_mod.get_db()
            .execute("PRAGMA table_info(users)")
            .fetchall()
        }
        self.assertIn("mfa_enabled", cols)
        self.assertIn("mfa_secret", cols)

    def tearDown(self):
        db_mod.DATABASE_PATH = self._orig_path
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def _enable_mfa(self, *, backup_codes=None):
        secret = mfa_totp.generate_secret()
        codes = backup_codes or mfa_totp.generate_backup_codes(n=4)
        conn = db_mod.get_db()
        try:
            conn.execute(
                """
                UPDATE users
                   SET mfa_enabled = 1,
                       mfa_secret = ?,
                       mfa_backup_codes_hash = ?
                 WHERE id = ?
                """,
                (
                    mfa_totp.encrypt_secret(secret),
                    mfa_totp.backup_codes_to_storage(codes),
                    self.user_id,
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return secret, codes

    def test_login_without_mfa_goes_home(self):
        resp = self.client.post(
            "/login",
            data={"username": "mfauser", "password": "Secret123!"},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.headers["Location"].endswith("/home"))
        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get("user_id"), self.user_id)
            self.assertNotIn("mfa_pending_user_id", sess)

    def test_password_ok_with_mfa_redirects_pending(self):
        self._enable_mfa()
        resp = self.client.post(
            "/login",
            data={"username": "mfauser", "password": "Secret123!"},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.headers["Location"].endswith("/login/mfa"))
        with self.client.session_transaction() as sess:
            self.assertNotIn("user_id", sess)
            self.assertEqual(sess.get("mfa_pending_user_id"), self.user_id)

    def test_correct_totp_completes_login(self):
        secret, _codes = self._enable_mfa()
        self.client.post(
            "/login",
            data={"username": "mfauser", "password": "Secret123!"},
            follow_redirects=False,
        )
        code = pyotp.TOTP(secret).now()
        resp = self.client.post(
            "/login/mfa",
            data={"code": code},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.headers["Location"].endswith("/home"))
        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get("user_id"), self.user_id)
            self.assertNotIn("mfa_pending_user_id", sess)

    def test_wrong_totp_fails(self):
        self._enable_mfa()
        self.client.post(
            "/login",
            data={"username": "mfauser", "password": "Secret123!"},
            follow_redirects=False,
        )
        resp = self.client.post(
            "/login/mfa",
            data={"code": "000000"},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Invalid authenticator", resp.data)
        with self.client.session_transaction() as sess:
            self.assertNotIn("user_id", sess)
            self.assertEqual(sess.get("mfa_pending_user_id"), self.user_id)

    def test_backup_code_works_once(self):
        _secret, codes = self._enable_mfa()
        self.client.post(
            "/login",
            data={"username": "mfauser", "password": "Secret123!"},
            follow_redirects=False,
        )
        first = codes[0]
        resp = self.client.post(
            "/login/mfa",
            data={"code": first},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.headers["Location"].endswith("/home"))

        # Sign out and try the same backup code again — must fail.
        with self.client.session_transaction() as sess:
            sess.clear()
        self.client.post(
            "/login",
            data={"username": "mfauser", "password": "Secret123!"},
            follow_redirects=False,
        )
        resp = self.client.post(
            "/login/mfa",
            data={"code": first},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Invalid authenticator", resp.data)
        with self.client.session_transaction() as sess:
            self.assertNotIn("user_id", sess)

    def test_mobile_login_mfa_required_then_verify(self):
        secret, _codes = self._enable_mfa()
        auth_payload = {
            "ok": True,
            "user_id": self.user_id,
            "username": "mfauser",
            "display_name": "MFA User",
            "must_change_password": False,
            "access": {},
        }
        with mock.patch(
            "mobile_preview_flask.preview_authenticate_credentials",
            return_value=(200, auth_payload),
        ):
            resp = self.client.post(
                "/api/mobile/login",
                json={"username": "mfauser", "password": "Secret123!"},
            )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertFalse(body.get("ok"))
        self.assertTrue(body.get("mfa_required"))
        self.assertTrue(body.get("mfa_token"))
        with self.client.session_transaction() as sess:
            self.assertNotIn("user_id", sess)

        code = pyotp.TOTP(secret).now()
        resp2 = self.client.post(
            "/api/mobile/login/mfa",
            json={"mfa_token": body["mfa_token"], "code": code},
        )
        self.assertEqual(resp2.status_code, 200)
        body2 = resp2.get_json()
        self.assertTrue(body2.get("ok"))
        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get("user_id"), self.user_id)

    def test_pending_mfa_expires(self):
        self._enable_mfa()
        self.client.post(
            "/login",
            data={"username": "mfauser", "password": "Secret123!"},
            follow_redirects=False,
        )
        with self.client.session_transaction() as sess:
            sess["mfa_pending_expires"] = time.time() - 5
        resp = self.client.get("/login/mfa", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(
            resp.headers["Location"].endswith("/")
            or resp.headers["Location"].endswith("/login")
            or "index" in (resp.headers.get("Location") or "")
        )


if __name__ == "__main__":
    unittest.main()
