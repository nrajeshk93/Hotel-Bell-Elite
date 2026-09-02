"""Activity audit log coverage for auth, deletes, registry, and page access."""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest

import db as db_mod
from werkzeug.security import generate_password_hash

import activity_audit
import auth_security


class ActivityLogTests(unittest.TestCase):
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
            self.admin_id = conn.execute(
                "SELECT id FROM users WHERE username='admin'"
            ).fetchone()["id"]
            self.limited_user_id = conn.execute(
                "SELECT id FROM users WHERE username='locke'"
            ).fetchone()["id"]
            conn.commit()
        finally:
            conn.close()

    def tearDown(self):
        db_mod.DATABASE_PATH = self._orig_path
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def _activity_rows(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT action, module, username, summary, entity_type, entity_id
            FROM activity_log
            ORDER BY id
            """
        ).fetchall()
        conn.close()
        return rows

    def test_login_success_and_failure_create_activity_rows(self):
        with self.client.session_transaction() as sess:
            sess.clear()

        bad = self.client.post(
            "/login",
            data={"username": "admin", "password": "wrong-password"},
        )
        self.assertIn(bad.status_code, (200, 401))
        failed_rows = self._activity_rows()
        self.assertEqual(len(failed_rows), 1)
        self.assertEqual(failed_rows[0]["action"], "login_failed")
        self.assertEqual(failed_rows[0]["module"], "auth")
        self.assertEqual(failed_rows[0]["username"], "admin")

        ok = self.client.post(
            "/login",
            data={"username": "admin", "password": "admin"},
        )
        self.assertEqual(ok.status_code, 302)
        rows = self._activity_rows()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]["action"], "login")
        self.assertEqual(rows[1]["module"], "auth")
        self.assertEqual(rows[1]["username"], "admin")
        self.assertIn("signed in", rows[1]["summary"])

    def test_delete_employee_writes_audit_before_row_removed(self):
        with self.client.session_transaction() as sess:
            sess[self.app_mod.AUTH_USER_SESSION_KEY] = self.admin_id

        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """
            INSERT INTO employees (emp_code, name, company, location, status)
            VALUES ('50001', 'A NISHA', 'HBE', 'Port Blair', 'active')
            """
        )
        emp_id = conn.execute(
            "SELECT id FROM employees WHERE emp_code=?",
            ("50001",),
        ).fetchone()[0]
        conn.commit()
        conn.close()

        resp = self.client.get(f"/delete_employee/{emp_id}")
        self.assertEqual(resp.status_code, 302)

        rows = self._activity_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["action"], "delete")
        self.assertEqual(rows[0]["module"], "payroll")
        self.assertEqual(rows[0]["entity_type"], "employee")
        self.assertEqual(str(rows[0]["entity_id"]), str(emp_id))
        self.assertIn("A NISHA", rows[0]["summary"])

    def test_registry_covers_save_access_user_and_delete_employee_is_explicit(self):
        self.assertIn("save_access_user", activity_audit.MUTATION_REGISTRY)
        self.assertNotIn("delete_employee", activity_audit.MUTATION_REGISTRY)
        self.assertIn("delete_employee", activity_audit._ACTIVITY_EXPLICIT_ONLY)

    def test_logs_page_access_control(self):
        with self.client.session_transaction() as sess:
            sess[self.app_mod.AUTH_USER_SESSION_KEY] = self.admin_id

        admin_resp = self.client.get("/access-management/logs")
        self.assertEqual(admin_resp.status_code, 200)
        self.assertIn(b"Activity Logs", admin_resp.data)
        self.assertIn(b"de-nav-access-logs", admin_resp.data)

        with self.client.session_transaction() as sess:
            sess[self.app_mod.AUTH_USER_SESSION_KEY] = self.limited_user_id

        denied = self.client.get("/access-management/logs")
        self.assertEqual(denied.status_code, 302)

    def test_fetch_activity_logs_filters_by_action(self):
        conn = db_mod.get_db()
        try:
            activity_audit.record_activity_log(
                "login",
                "auth",
                "Admin signed in",
                conn=conn,
                user_id=self.admin_id,
                username="admin",
                commit=True,
            )
            activity_audit.record_activity_log(
                "update",
                "hotel",
                "Updated room 101",
                conn=conn,
                user_id=self.admin_id,
                username="admin",
                commit=True,
            )
            logs, total, pages, _users = activity_audit.fetch_activity_logs(
                conn, {"action": "login"}, 1
            )
        finally:
            conn.close()
        self.assertEqual(total, 1)
        self.assertEqual(logs[0]["action"], "login")
        self.assertGreaterEqual(pages, 1)


if __name__ == "__main__":
    unittest.main()
