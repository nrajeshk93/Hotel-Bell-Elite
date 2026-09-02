"""Login lockout, CAPTCHA, and email unlock security tests."""

import os
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest import mock

import db as db_mod
from werkzeug.security import generate_password_hash

import auth_security


class LoginSecurityTests(unittest.TestCase):
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
        auth_security.reset_ip_throttle_for_tests()

        conn = db_mod.get_db()
        try:
            conn.execute(
                """
                UPDATE users
                   SET email = ?, password_hash = ?
                 WHERE username = 'admin'
                """,
                ("admin@example.com", generate_password_hash("admin")),
            )
            conn.execute(
                """
                INSERT INTO users
                  (username, full_name, email, password_hash, is_admin, is_active, created_at, updated_at)
                VALUES (?, ?, ?, ?, 0, 1, datetime('now','localtime'), datetime('now','localtime'))
                """,
                ("locke", "Locke User", "locke@example.com", generate_password_hash("secret123")),
            )
            conn.execute(
                """INSERT INTO access_roles
                   (name, description, is_admin, is_active, created_at, updated_at)
                   VALUES (?, ?, 0, 1, datetime('now','localtime'), datetime('now','localtime'))""",
                ("Staff", "Test staff role"),
            )
            staff_role_id = conn.execute(
                "SELECT id FROM access_roles WHERE name = ?",
                ("Staff",),
            ).fetchone()["id"]
            conn.execute(
                "UPDATE users SET role_id = ? WHERE username = ?",
                (staff_role_id, "locke"),
            )
            conn.commit()
            self.user_id = conn.execute(
                "SELECT id FROM users WHERE username = 'locke'"
            ).fetchone()["id"]
        finally:
            conn.close()

    def tearDown(self):
        db_mod.DATABASE_PATH = self._orig_path
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def _user_row(self):
        conn = db_mod.get_db()
        try:
            return dict(
                conn.execute(
                    "SELECT * FROM users WHERE id = ?", (self.user_id,)
                ).fetchone()
            )
        finally:
            conn.close()

    def test_captcha_required_after_two_failures(self):
        resp = None
        for _ in range(2):
            resp = self.client.post(
                "/login",
                data={"username": "locke", "password": "wrong"},
                follow_redirects=False,
            )
            self.assertEqual(resp.status_code, 200)
            self.assertIn(b"Invalid username or password", resp.data)

        row = self._user_row()
        self.assertEqual(row["failed_login_attempts"], 2)
        self.assertEqual(row["captcha_required"], 1)
        self.assertFalse(row["locked_at"])
        self.assertIn(b"CAPTCHA", resp.data)
        self.assertIn(b'name="captcha"', resp.data)

        # Correct password without CAPTCHA is rejected and counts as another failure → lock.
        resp = self.client.post(
            "/login",
            data={"username": "locke", "password": "secret123"},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"account is locked", resp.data)
        row = self._user_row()
        self.assertEqual(row["failed_login_attempts"], 3)
        self.assertTrue(row["locked_at"])

    def test_lock_after_three_failures_and_unlock_token(self):
        sent = []

        def fake_send(**kwargs):
            sent.append(kwargs)
            return True

        with mock.patch("app.send_account_unlock_email", side_effect=fake_send):
            for _ in range(3):
                self.client.post(
                    "/login",
                    data={"username": "locke", "password": "wrong", "captcha": "XXXXX"},
                )

        row = self._user_row()
        self.assertEqual(row["failed_login_attempts"], 3)
        self.assertTrue(row["locked_at"])
        self.assertTrue(row["unlock_token_hash"])
        self.assertEqual(len(sent), 1)
        self.assertIn("unlock-account?token=", sent[0]["unlock_url"])

        # Locked account cannot log in even with correct password.
        resp = self.client.post(
            "/login",
            data={"username": "locke", "password": "secret123"},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"account is locked", resp.data)

        # Extract token by re-issuing via helper and unlock.
        conn = db_mod.get_db()
        try:
            token = auth_security.issue_unlock_token(conn, self.user_id)
            conn.commit()
        finally:
            conn.close()

        resp = self.client.get(f"/unlock-account?token={token}", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)

        row = self._user_row()
        self.assertFalse(row["locked_at"])
        self.assertEqual(row["failed_login_attempts"], 0)
        self.assertEqual(row["captcha_required"], 0)

        resp = self.client.post(
            "/login",
            data={"username": "locke", "password": "secret123"},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.headers["Location"].endswith("/home"))

    def test_unlock_token_single_use_and_expiry(self):
        conn = db_mod.get_db()
        try:
            token = auth_security.issue_unlock_token(conn, self.user_id)
            conn.execute(
                "UPDATE users SET locked_at = ? WHERE id = ?",
                (auth_security.sql_now(), self.user_id),
            )
            conn.commit()
            first = auth_security.verify_and_consume_unlock_token(conn, token)
            conn.commit()
            self.assertEqual(first, self.user_id)
            second = auth_security.verify_and_consume_unlock_token(conn, token)
            self.assertIsNone(second)

            token2 = auth_security.issue_unlock_token(conn, self.user_id)
            expired = (datetime.now() - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
            conn.execute(
                "UPDATE users SET unlock_token_expires_at = ? WHERE id = ?",
                (expired, self.user_id),
            )
            conn.commit()
            self.assertIsNone(auth_security.verify_and_consume_unlock_token(conn, token2))
        finally:
            conn.close()

    def test_captcha_endpoint_returns_png(self):
        resp = self.client.get("/login/captcha")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.mimetype, "image/png")
        self.assertTrue(resp.data.startswith(b"\x89PNG"))

    def test_successful_login_clears_failures(self):
        conn = db_mod.get_db()
        try:
            conn.execute(
                """
                UPDATE users
                   SET failed_login_attempts = 2, captcha_required = 1
                 WHERE id = ?
                """,
                (self.user_id,),
            )
            conn.commit()
        finally:
            conn.close()

        with self.client.session_transaction() as sess:
            sess[auth_security.CAPTCHA_SESSION_ANSWER] = "ABC12"
            sess[auth_security.CAPTCHA_SESSION_EXPIRES] = 9999999999

        resp = self.client.post(
            "/login",
            data={"username": "locke", "password": "secret123", "captcha": "abc12"},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 302)
        row = self._user_row()
        self.assertEqual(row["failed_login_attempts"], 0)
        self.assertEqual(row["captcha_required"], 0)

    def test_admin_unlock_route(self):
        conn = db_mod.get_db()
        try:
            conn.execute(
                """
                UPDATE users
                   SET failed_login_attempts = 3,
                       locked_at = ?,
                       captcha_required = 0
                 WHERE id = ?
                """,
                (auth_security.sql_now(), self.user_id),
            )
            admin_id = conn.execute(
                "SELECT id FROM users WHERE username = 'admin'"
            ).fetchone()["id"]
            conn.commit()
        finally:
            conn.close()

        with mock.patch.object(self.app_mod, "get_current_user") as get_user:
            get_user.return_value = {
                "id": admin_id,
                "username": "admin",
                "is_admin": True,
                "is_active": True,
                "user_access": {"users", "add"},
                "dashboard_access": set(),
            }
            resp = self.client.post(
                f"/access-management/unlock/{self.user_id}",
                follow_redirects=False,
            )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue((resp.headers.get("Location") or "").endswith("/access-management"))
        row = self._user_row()
        self.assertFalse(row["locked_at"])
        self.assertEqual(row["failed_login_attempts"], 0)

        conn = db_mod.get_db()
        try:
            conn.execute(
                """
                UPDATE users
                   SET failed_login_attempts = 3,
                       locked_at = ?,
                       captcha_required = 0
                 WHERE id = ?
                """,
                (auth_security.sql_now(), self.user_id),
            )
            conn.commit()
        finally:
            conn.close()

        with mock.patch.object(self.app_mod, "get_current_user") as get_user:
            get_user.return_value = {
                "id": admin_id,
                "username": "admin",
                "is_admin": True,
                "is_active": True,
                "user_access": {"users", "add"},
                "dashboard_access": set(),
            }
            locked_form = self.client.get(
                f"/access-management?user_id={self.user_id}&focus=form"
            )
            self.assertEqual(locked_form.status_code, 200)
            locked_html = locked_form.get_data(as_text=True)
            self.assertIn("Unlock", locked_html)
            self.assertIn("am-unlock-form", locked_html)
            self.assertIn("Locked", locked_html)
            self.assertIn("cannot sign in", locked_html)

            unlocked = self.client.post(
                f"/access-management/unlock/{self.user_id}",
                data={"return_to": "form"},
                follow_redirects=False,
            )
        self.assertEqual(unlocked.status_code, 302)
        location = unlocked.headers.get("Location") or ""
        self.assertIn(f"user_id={self.user_id}", location)
        self.assertIn("focus=form", location)
        row = self._user_row()
        self.assertFalse(row["locked_at"])

        with mock.patch.object(self.app_mod, "get_current_user") as get_user:
            get_user.return_value = {
                "id": admin_id,
                "username": "admin",
                "is_admin": True,
                "is_active": True,
                "user_access": {"users", "add"},
                "dashboard_access": set(),
            }
            after_form = self.client.get(
                f"/access-management?user_id={self.user_id}&focus=form"
            )
        after_html = after_form.get_data(as_text=True)
        self.assertEqual(after_form.status_code, 200)
        self.assertNotIn("am-unlock-form", after_html)
        self.assertIn("Unlocked", after_html)
        self.assertIn("can sign in", after_html)

    def test_toggle_access_user_active_route(self):
        conn = db_mod.get_db()
        try:
            admin_id = conn.execute(
                "SELECT id FROM users WHERE username = 'admin'"
            ).fetchone()["id"]
            conn.commit()
        finally:
            conn.close()

        admin_ctx = {
            "id": admin_id,
            "username": "admin",
            "is_admin": True,
            "is_active": True,
            "user_access": {"users", "add"},
            "dashboard_access": set(),
        }

        with mock.patch.object(self.app_mod, "get_current_user") as get_user:
            get_user.return_value = admin_ctx
            resp = self.client.post(
                f"/access-management/active/{self.user_id}",
                follow_redirects=False,
            )
        self.assertEqual(resp.status_code, 303)
        row = self._user_row()
        self.assertEqual(int(row["is_active"]), 0)

        with mock.patch.object(self.app_mod, "get_current_user") as get_user:
            get_user.return_value = admin_ctx
            resp = self.client.post(
                f"/access-management/active/{self.user_id}",
                follow_redirects=False,
            )
        self.assertEqual(resp.status_code, 303)
        row = self._user_row()
        self.assertEqual(int(row["is_active"]), 1)

        with mock.patch.object(self.app_mod, "get_current_user") as get_user:
            get_user.return_value = admin_ctx
            resp = self.client.post(
                f"/access-management/active/{admin_id}",
                follow_redirects=False,
            )
        self.assertEqual(resp.status_code, 303)
        conn = db_mod.get_db()
        try:
            admin_row = conn.execute(
                "SELECT is_active FROM users WHERE id = ?", (admin_id,)
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(int(admin_row["is_active"]), 1)

        # Last active admin cannot be deactivated even when acted on by another admin.
        conn = db_mod.get_db()
        try:
            conn.execute(
                """
                INSERT INTO users
                  (username, full_name, email, password_hash, is_admin, is_active,
                   created_at, updated_at)
                VALUES (?, ?, ?, ?, 1, 1, datetime('now','localtime'), datetime('now','localtime'))
                """,
                ("admin2", "Admin Two", "admin2@example.com", generate_password_hash("secret123")),
            )
            other_admin_id = conn.execute(
                "SELECT id FROM users WHERE username = 'admin2'"
            ).fetchone()["id"]
            # Seeded admin is the only Super Admin role user; mark other as admin flag only.
            # Deactivate other_admin first so seeded admin is sole active admin.
            conn.execute(
                "UPDATE users SET is_active = 0 WHERE id = ?", (other_admin_id,)
            )
            conn.commit()
        finally:
            conn.close()

        other_admin_ctx = {
            "id": other_admin_id,
            "username": "admin2",
            "is_admin": True,
            "is_active": True,
            "user_access": {"users", "add"},
            "dashboard_access": set(),
        }
        # Reactivate other_admin in DB for actor identity, but keep only one active admin
        # when attempting to deactivate the last remaining active admin (seeded admin).
        # other_admin is inactive in DB; patch get_current_user so permission checks pass.
        with mock.patch.object(self.app_mod, "get_current_user") as get_user:
            get_user.return_value = other_admin_ctx
            resp = self.client.post(
                f"/access-management/active/{admin_id}",
                follow_redirects=False,
            )
        self.assertEqual(resp.status_code, 303)
        conn = db_mod.get_db()
        try:
            admin_row = conn.execute(
                "SELECT is_active FROM users WHERE id = ?", (admin_id,)
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(int(admin_row["is_active"]), 1)

    def test_password_complexity_rules(self):
        self.assertTrue(auth_security.password_meets_complexity("Password1!"))
        self.assertIsNone(auth_security.password_complexity_error("Abcd123!"))
        self.assertFalse(auth_security.password_meets_complexity("short1!"))
        self.assertFalse(auth_security.password_meets_complexity("alllowercase1!"))
        self.assertFalse(auth_security.password_meets_complexity("ALLUPPERCASE1!"))
        self.assertFalse(auth_security.password_meets_complexity("NoNumber!"))
        self.assertFalse(auth_security.password_meets_complexity("NoSpecial1"))
        self.assertEqual(
            auth_security.password_complexity_error("weak"),
            auth_security.PASSWORD_COMPLEXITY_MESSAGE,
        )

    def test_create_user_rejects_weak_password(self):
        conn = db_mod.get_db()
        try:
            admin_id = conn.execute(
                "SELECT id FROM users WHERE username = 'admin'"
            ).fetchone()["id"]
            staff_role_id = conn.execute(
                "SELECT id FROM access_roles WHERE name = ?",
                ("Staff",),
            ).fetchone()["id"]
        finally:
            conn.close()

        with mock.patch.object(self.app_mod, "get_current_user") as get_user:
            get_user.return_value = {
                "id": admin_id,
                "username": "admin",
                "is_admin": True,
                "is_active": True,
                "user_access": {"users", "add"},
                "dashboard_access": set(),
            }
            weak = self.client.post(
                "/access-management/save",
                data={
                    "username": "newstaff",
                    "full_name": "New Staff",
                    "email": "newstaff@example.com",
                    "password": "password",
                    "role_id": str(staff_role_id),
                },
            )
            self.assertEqual(weak.status_code, 400)
            self.assertIn(auth_security.PASSWORD_COMPLEXITY_MESSAGE, weak.get_data(as_text=True))
            strong = self.client.post(
                "/access-management/save",
                data={
                    "username": "newstaff",
                    "full_name": "New Staff",
                    "email": "newstaff@example.com",
                    "password": "Password1!",
                    "role_id": str(staff_role_id),
                },
                follow_redirects=False,
            )
        self.assertEqual(strong.status_code, 303)
        conn = db_mod.get_db()
        try:
            created = conn.execute(
                "SELECT id FROM users WHERE username = ?",
                ("newstaff",),
            ).fetchone()
        finally:
            conn.close()
        self.assertIsNotNone(created)

    def test_hash_password_uses_argon2id(self):
        encoded = auth_security.hash_password("fresh-secret")
        self.assertTrue(encoded.startswith("$argon2id$"))
        self.assertTrue(auth_security.verify_password(encoded, "fresh-secret"))
        self.assertFalse(auth_security.verify_password(encoded, "wrong"))
        self.assertFalse(auth_security.password_needs_rehash(encoded))

    def test_legacy_werkzeug_login_upgrades_to_argon2id(self):
        row = self._user_row()
        self.assertFalse(str(row["password_hash"]).startswith("$argon2"))
        self.assertTrue(auth_security.password_needs_rehash(row["password_hash"]))

        resp = self.client.post(
            "/login",
            data={"username": "locke", "password": "secret123"},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 302)

        row = self._user_row()
        self.assertTrue(str(row["password_hash"]).startswith("$argon2id$"))
        self.assertTrue(auth_security.verify_password(row["password_hash"], "secret123"))
        self.assertFalse(auth_security.password_needs_rehash(row["password_hash"]))

        # Second login still works with the upgraded hash.
        self.client.post("/logout", follow_redirects=False)
        resp = self.client.post(
            "/login",
            data={"username": "locke", "password": "secret123"},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 302)

    def test_access_user_create_and_reset_store_argon2id(self):
        import workspace_access

        conn = db_mod.get_db()
        try:
            role_id, _ = workspace_access.save_access_role_record(
                conn,
                role_id=None,
                name="Argon Role",
                description="",
                is_admin=False,
                is_active=True,
                dashboard_modules=["reports"],
                sales_analytics_modules=[],
                user_access_modules=[],
                sql_now="datetime('now','localtime')",
            )
            user_id, flag = workspace_access.save_access_user_record(
                conn,
                user_id=None,
                username="argon_user",
                full_name="Argon User",
                password="ArgonPass1!",
                role_id=role_id,
                sql_now="datetime('now','localtime')",
                email="argon@example.com",
            )
            self.assertEqual(flag, "created")
            stored = conn.execute(
                "SELECT password_hash FROM users WHERE id = ?", (user_id,)
            ).fetchone()["password_hash"]
            self.assertTrue(str(stored).startswith("$argon2id$"))
            self.assertTrue(auth_security.verify_password(stored, "ArgonPass1!"))
            self.assertEqual(
                conn.execute(
                    "SELECT must_change_password FROM users WHERE id = ?", (user_id,)
                ).fetchone()["must_change_password"],
                0,
            )

            workspace_access.save_access_user_record(
                conn,
                user_id=user_id,
                username="argon_user",
                full_name="Argon User",
                password="ResetPass2!",
                role_id=role_id,
                sql_now="datetime('now','localtime')",
                email="argon@example.com",
                must_change_password=True,
            )
            reset_row = conn.execute(
                "SELECT password_hash, must_change_password FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
            reset = reset_row["password_hash"]
            self.assertTrue(str(reset).startswith("$argon2id$"))
            self.assertTrue(auth_security.verify_password(reset, "ResetPass2!"))
            self.assertFalse(auth_security.verify_password(reset, "ArgonPass1!"))
            self.assertEqual(reset_row["must_change_password"], 1)

            conn.execute(
                "UPDATE users SET must_change_password = 0 WHERE id = ?", (user_id,)
            )
            workspace_access.save_access_user_record(
                conn,
                user_id=user_id,
                username="argon_user",
                full_name="Argon User",
                password="",
                role_id=role_id,
                sql_now="datetime('now','localtime')",
                email="argon@example.com",
            )
            kept = conn.execute(
                "SELECT password_hash, must_change_password FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
            self.assertTrue(auth_security.verify_password(kept["password_hash"], "ResetPass2!"))
            self.assertEqual(kept["must_change_password"], 0)

            workspace_access.save_access_user_record(
                conn,
                user_id=user_id,
                username="argon_user",
                full_name="Argon User",
                password="KeepPass3!",
                role_id=role_id,
                sql_now="datetime('now','localtime')",
                email="argon@example.com",
                must_change_password=False,
            )
            permanent = conn.execute(
                "SELECT password_hash, must_change_password FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
            self.assertTrue(auth_security.verify_password(permanent["password_hash"], "KeepPass3!"))
            self.assertEqual(permanent["must_change_password"], 0)
            conn.commit()
        finally:
            conn.close()

    def test_temp_password_forces_change_on_first_login(self):
        import workspace_access

        conn = db_mod.get_db()
        try:
            role_id, _ = workspace_access.save_access_role_record(
                conn,
                role_id=None,
                name="Temp Pass Role",
                description="",
                is_admin=False,
                is_active=True,
                dashboard_modules=["reports"],
                sales_analytics_modules=[],
                user_access_modules=[],
                sql_now="datetime('now','localtime')",
            )
            workspace_access.save_access_user_record(
                conn,
                user_id=None,
                username="temp_user",
                full_name="Temp User",
                password="TempPass1!",
                role_id=role_id,
                sql_now="datetime('now','localtime')",
                email="temp@example.com",
                must_change_password=True,
            )
            conn.commit()
        finally:
            conn.close()

        login = self.client.post(
            "/login",
            data={"username": "temp_user", "password": "TempPass1!"},
            follow_redirects=False,
        )
        self.assertEqual(login.status_code, 302)
        self.assertTrue(login.headers["Location"].endswith("/change-password"))

        blocked = self.client.get("/home", follow_redirects=False)
        self.assertEqual(blocked.status_code, 302)
        self.assertTrue(blocked.headers["Location"].endswith("/change-password"))

        page = self.client.get("/change-password")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Change password", page.data)

        same = self.client.post(
            "/change-password",
            data={"new_password": "TempPass1!", "confirm_password": "TempPass1!"},
            follow_redirects=False,
        )
        self.assertEqual(same.status_code, 200)
        self.assertIn(b"different from your temporary password", same.data)

        mismatch = self.client.post(
            "/change-password",
            data={"new_password": "NewPass2!", "confirm_password": "OtherPass"},
            follow_redirects=False,
        )
        self.assertEqual(mismatch.status_code, 200)
        self.assertIn(b"do not match", mismatch.data)

        changed = self.client.post(
            "/change-password",
            data={"new_password": "NewPass2!", "confirm_password": "NewPass2!"},
            follow_redirects=False,
        )
        self.assertEqual(changed.status_code, 302)
        self.assertTrue(changed.headers["Location"].endswith("/home"))

        conn = db_mod.get_db()
        try:
            flag = conn.execute(
                "SELECT must_change_password FROM users WHERE username = 'temp_user'"
            ).fetchone()["must_change_password"]
        finally:
            conn.close()
        self.assertEqual(flag, 0)

        home = self.client.get("/home", follow_redirects=False)
        self.assertEqual(home.status_code, 200)

        self.client.post("/logout")
        again = self.client.post(
            "/login",
            data={"username": "temp_user", "password": "NewPass2!"},
            follow_redirects=False,
        )
        self.assertEqual(again.status_code, 302)
        self.assertTrue(again.headers["Location"].endswith("/home"))

    def test_failed_and_successful_logins_are_recorded(self):
        self.client.post("/login", data={"username": "locke", "password": "wrong"})
        self.client.post("/login", data={"username": "ghost", "password": "x"})
        self.client.post("/login", data={"username": "locke", "password": "secret123"})
        conn = db_mod.get_db()
        try:
            rows = list(
                conn.execute(
                    "SELECT username, success, reason FROM login_logs ORDER BY id"
                )
            )
        finally:
            conn.close()
        self.assertEqual(
            [(row["username"], int(row["success"]), row["reason"]) for row in rows],
            [
                ("locke", 0, "invalid_password"),
                ("ghost", 0, "unknown_user"),
                ("locke", 1, "success"),
            ],
        )

    def test_logs_page_lists_attempts_for_admin(self):
        self.client.post("/login", data={"username": "locke", "password": "wrong"})
        self.client.post("/login", data={"username": "admin", "password": "admin"})
        page = self.client.get("/access-management/logs")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Activity Logs", page.data)
        self.assertIn(b"de-nav-access-logs", page.data)
        self.assertIn(b"locke", page.data)
        self.assertIn(b"Login failed", page.data)
        self.assertIn(b"Login", page.data)
        self.assertIn(b'name="action"', page.data)
        self.assertIn(b'name="module"', page.data)
        self.assertIn(b'name="date_from"', page.data)

    def test_logs_page_action_filter_limits_rows(self):
        self.client.post("/login", data={"username": "locke", "password": "wrong"})
        self.client.post("/login", data={"username": "admin", "password": "admin"})
        page = self.client.get("/access-management/logs?action=login_failed")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Failed sign-in for locke", page.data)
        self.assertNotIn(b"admin signed in", page.data.lower())

    def test_logs_page_denied_for_non_admin(self):
        self.client.post("/login", data={"username": "locke", "password": "secret123"})
        page = self.client.get("/access-management/logs")
        self.assertIn(page.status_code, (302, 303))

    def test_admin_seed_uses_argon2id(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        path = tmp.name
        orig = db_mod.DATABASE_PATH
        try:
            db_mod.DATABASE_PATH = path
            db_mod.init_db()
            conn = db_mod.get_db()
            try:
                stored = conn.execute(
                    "SELECT password_hash FROM users WHERE username = 'admin'"
                ).fetchone()["password_hash"]
            finally:
                conn.close()
            self.assertTrue(str(stored).startswith("$argon2id$"))
            self.assertTrue(auth_security.verify_password(stored, "admin"))
        finally:
            db_mod.DATABASE_PATH = orig
            try:
                os.unlink(path)
            except OSError:
                pass

    def test_logout_prefetch_does_not_clear_admin_session(self):
        login = self.client.post(
            "/login",
            data={"username": "admin", "password": "admin"},
            follow_redirects=False,
        )
        self.assertEqual(login.status_code, 302)
        home = self.client.get("/home", follow_redirects=False)
        self.assertEqual(home.status_code, 200)
        self.assertIn(b"db-avatar", home.data)
        self.assertIn(b"Administrator", home.data)

        prefetch = self.client.get(
            "/logout",
            headers={
                "X-De-Partial": "main",
                "X-Requested-With": "XMLHttpRequest",
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
            },
            follow_redirects=False,
        )
        self.assertEqual(prefetch.status_code, 204)

        again = self.client.get("/home", follow_redirects=False)
        self.assertEqual(again.status_code, 200)
        self.assertIn(b"Administrator", again.data)
        self.assertIn("no-store", (again.headers.get("Cache-Control") or "").lower())

    def test_real_logout_still_clears_session(self):
        self.client.post(
            "/login",
            data={"username": "admin", "password": "admin"},
            follow_redirects=False,
        )
        resp = self.client.post("/logout", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        home = self.client.get("/home", follow_redirects=False)
        self.assertEqual(home.status_code, 302)
        self.assertTrue((home.headers.get("Location") or "").endswith("/"))

    def test_post_logout_clears_session(self):
        self.client.post(
            "/login",
            data={"username": "admin", "password": "admin"},
            follow_redirects=False,
        )
        resp = self.client.post(
            "/logout",
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
            },
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 302)
        home = self.client.get("/home", follow_redirects=False)
        self.assertEqual(home.status_code, 302)
        self.assertTrue((home.headers.get("Location") or "").endswith("/"))

    def test_home_requires_login(self):
        home = self.client.get("/home", follow_redirects=False)
        self.assertEqual(home.status_code, 302)
        self.assertTrue((home.headers.get("Location") or "").endswith("/"))

    def test_http_session_cookie_is_not_secure(self):
        login = self.client.post(
            "/login",
            data={"username": "admin", "password": "admin"},
            follow_redirects=False,
        )
        self.assertEqual(login.status_code, 302)
        cookie = login.headers.get("Set-Cookie") or ""
        flags = {part.strip().lower() for part in cookie.split(";")}
        self.assertNotIn("secure", flags)
        home = self.client.get("/home", follow_redirects=False)
        self.assertEqual(home.status_code, 200)
        self.assertIn(b"Administrator", home.data)
        again = self.client.get("/home", follow_redirects=False)
        self.assertEqual(again.status_code, 200)
        self.assertIn(b"Administrator", again.data)

    def test_login_rejected_without_access_role(self):
        conn = db_mod.get_db()
        try:
            conn.execute(
                """INSERT INTO users
                   (username, full_name, email, password_hash, is_admin, role_id,
                    is_active, created_at, updated_at)
                   VALUES (?, ?, ?, ?, 0, NULL, 1, datetime('now','localtime'), datetime('now','localtime'))""",
                (
                    "norole",
                    "No Role",
                    "norole@example.com",
                    generate_password_hash("secret123"),
                ),
            )
            conn.commit()
        finally:
            conn.close()
        resp = self.client.post(
            "/login",
            data={"username": "norole", "password": "secret123"},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"assign a role", resp.data)
        home = self.client.get("/home", follow_redirects=False)
        self.assertEqual(home.status_code, 302)

    def test_home_profile_shows_access_role_not_generic_user(self):
        self.client.post(
            "/login",
            data={"username": "admin", "password": "admin"},
            follow_redirects=False,
        )
        home = self.client.get("/home")
        self.assertEqual(home.status_code, 200)
        self.assertIn(b'db-profile-role', home.data)
        self.assertIn(b"Super Administrator", home.data)
        self.assertNotIn(b">User</div>", home.data)

        self.client.post("/logout", follow_redirects=False)
        self.client.post(
            "/login",
            data={"username": "locke", "password": "secret123"},
            follow_redirects=False,
        )
        staff_home = self.client.get("/home")
        self.assertEqual(staff_home.status_code, 200)
        self.assertIn(b">Staff</div>", staff_home.data)
        self.assertNotIn(b">User</div>", staff_home.data)


if __name__ == "__main__":
    unittest.main()
