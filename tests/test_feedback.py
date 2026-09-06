"""Tests for Communication Hub Feedback analytics + public links."""

import os
import tempfile
import unittest
from unittest import mock

import db as db_mod
import feedback as fb_mod
from workspace_access import (
    get_endpoint_communication_hub_submodule,
    get_endpoint_dashboard_module,
)


class FeedbackAccessTests(unittest.TestCase):
    def test_feedback_endpoints_map_to_submodule(self):
        self.assertEqual(
            get_endpoint_communication_hub_submodule("communication_hub_feedback"),
            "feedback",
        )
        self.assertEqual(
            get_endpoint_communication_hub_submodule(
                "communication_hub_api_feedback_summary"
            ),
            "feedback",
        )
        self.assertEqual(
            get_endpoint_dashboard_module("communication_hub_feedback"),
            "communication_hub",
        )
        self.assertIsNone(
            get_endpoint_communication_hub_submodule("customer_feedback_public")
        )


class FeedbackUnitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        self.tmp.close()
        self.db_path = self.tmp.name
        self._orig_path = db_mod.DATABASE_PATH
        db_mod.DATABASE_PATH = self.db_path
        conn = db_mod.get_db()
        try:
            db_mod.ensure_customer_feedback_schema(conn)
            conn.commit()
        finally:
            conn.close()

    def tearDown(self):
        db_mod.DATABASE_PATH = self._orig_path
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def test_invite_submit_and_summary(self):
        conn = db_mod.get_db()
        try:
            invite = fb_mod.create_feedback_invite(
                conn,
                customer_name="Anita",
                phone="9876543210",
                source="hotel",
            )
            self.assertTrue(invite["token"])
            self.assertIn("/f/", invite["url"])

            result = fb_mod.submit_feedback(
                conn,
                invite["token"],
                rating=5,
                comment="Excellent stay",
                service_rating=5,
                food_rating=4,
            )
            self.assertTrue(result["ok"])
            self.assertEqual(result["rating"], 5)

            with self.assertRaises(ValueError):
                fb_mod.submit_feedback(conn, invite["token"], rating=3)

            summary = fb_mod.feedback_summary(conn)
            self.assertEqual(summary["invites"], 1)
            self.assertEqual(summary["responses"], 1)
            self.assertEqual(summary["avg_rating"], 5.0)
            self.assertEqual(summary["rating_distribution"]["5"], 1)

            rows = fb_mod.list_feedback_responses(conn)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["customer_name"], "Anita")
            self.assertEqual(rows[0]["comment"], "Excellent stay")
        finally:
            conn.close()


class FeedbackHttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
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
            admin = conn.execute(
                "SELECT id FROM users WHERE username = 'admin'"
            ).fetchone()
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
        self._get_user_patch = mock.patch.object(
            app_mod, "get_current_user", return_value=self.user
        )
        self._get_user_patch.start()

    def tearDown(self):
        self._get_user_patch.stop()
        db_mod.DATABASE_PATH = self._orig_path
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def test_page_renders_marker_and_nav(self):
        resp = self.client.get("/communication-hub/feedback")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn('id="ch-feedback-page"', html)
        self.assertIn("data-communication-hub-feedback", html)
        self.assertIn("de-nav-communication-hub-feedback", html)
        self.assertIn(">Feedback<", html)

    def test_summary_and_invite_apis(self):
        empty = self.client.get("/communication-hub/api/feedback/summary")
        self.assertEqual(empty.status_code, 200)
        self.assertTrue(empty.get_json()["ok"])
        self.assertEqual(empty.get_json()["summary"]["responses"], 0)

        created = self.client.post(
            "/communication-hub/api/feedback/invites",
            json={"customer_name": "Ravi", "phone": "9876543210", "source": "bar"},
        )
        self.assertEqual(created.status_code, 200)
        payload = created.get_json()
        self.assertTrue(payload["ok"])
        token = payload["invite"]["token"]
        self.assertTrue(token)

        public = self.client.get(f"/f/{token}")
        self.assertEqual(public.status_code, 200)
        self.assertIn(b"How was your experience", public.data)

        submitted = self.client.post(
            f"/f/{token}",
            data={"rating": "4", "comment": "Nice food", "service_rating": "5"},
        )
        self.assertEqual(submitted.status_code, 200)
        self.assertIn(b"Thank you", submitted.data)

        summary = self.client.get("/communication-hub/api/feedback/summary")
        data = summary.get_json()["summary"]
        self.assertEqual(data["responses"], 1)
        self.assertEqual(data["avg_rating"], 4.0)

        rows = self.client.get("/communication-hub/api/feedback/responses")
        self.assertEqual(rows.status_code, 200)
        self.assertEqual(len(rows.get_json()["responses"]), 1)
        self.assertEqual(rows.get_json()["responses"][0]["comment"], "Nice food")
