"""Tests for Communication Hub Feedback analytics + public links."""

import os
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest import mock

import db as db_mod
import feedback as fb_mod
from workspace_access import (
    _PUBLIC_ENDPOINTS,
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
        self.assertIsNone(
            get_endpoint_communication_hub_submodule("customer_feedback_review")
        )

    def test_public_feedback_endpoints_exempt_from_auth(self):
        self.assertIn("customer_feedback_public", _PUBLIC_ENDPOINTS)
        self.assertIn("customer_feedback_review", _PUBLIC_ENDPOINTS)


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
            self.assertTrue(
                invite["url"].startswith("https://belleliteaccounts.com/f/"),
                invite["url"],
            )
            self.assertEqual(invite.get("expires_in_hours"), 24)
            self.assertTrue(invite.get("expires_at"))
            expires_dt = datetime.strptime(invite["expires_at"], "%Y-%m-%d %H:%M:%S")
            created_dt = datetime.strptime(invite["created_at"], "%Y-%m-%d %H:%M:%S")
            delta = expires_dt - created_dt
            self.assertAlmostEqual(delta.total_seconds(), 24 * 3600, delta=5)
            self.assertFalse(fb_mod.invite_is_expired(invite))

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
            self.assertTrue(result["redirect_google"])
            self.assertEqual(result["google_url"], fb_mod.GOOGLE_REVIEW_URL)

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

    def test_low_star_stores_without_google(self):
        conn = db_mod.get_db()
        try:
            invite = fb_mod.create_feedback_invite(conn, customer_name="Guest")
            result = fb_mod.submit_feedback(
                conn,
                invite["token"],
                rating=2,
                comment="Room was noisy",
            )
            self.assertTrue(result["ok"])
            self.assertEqual(result["rating"], 2)
            self.assertFalse(result["redirect_google"])
            self.assertIsNone(result["google_url"])
            rows = fb_mod.list_feedback_responses(conn)
            self.assertEqual(rows[0]["comment"], "Room was noisy")
        finally:
            conn.close()

    def test_google_review_url_constant(self):
        self.assertIn("placeid=ChIJSTl7KeOViDARrKxuDpxfEo8", fb_mod.GOOGLE_REVIEW_URL)
        self.assertEqual(fb_mod.GOOGLE_GATE_MIN_RATING, 4)



    def test_invite_url_never_localhost(self):
        conn = db_mod.get_db()
        try:
            with mock.patch.dict(os.environ, {"APP_BASE_URL": "http://127.0.0.1:5055"}, clear=False):
                invite = fb_mod.create_feedback_invite(conn, customer_name="Local")
            self.assertTrue(
                invite["url"].startswith("https://belleliteaccounts.com/f/"),
                invite["url"],
            )
            with mock.patch.dict(
                os.environ, {"APP_BASE_URL": "https://belleliteaccounts.com"}, clear=False
            ):
                invite2 = fb_mod.create_feedback_invite(conn, customer_name="Prod")
            self.assertTrue(
                invite2["url"].startswith("https://belleliteaccounts.com/f/"),
                invite2["url"],
            )
        finally:
            conn.close()

    def test_expired_invite_rejects_submit(self):
        conn = db_mod.get_db()
        try:
            invite = fb_mod.create_feedback_invite(conn, customer_name="Old")
            past = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
            conn.execute(
                "UPDATE customer_feedback_invites SET expires_at = ? WHERE token = ?",
                (past, invite["token"]),
            )
            conn.commit()
            row = fb_mod.get_invite_by_token(conn, invite["token"])
            self.assertTrue(fb_mod.invite_is_expired(row))
            with self.assertRaises(ValueError) as ctx:
                fb_mod.submit_feedback(conn, invite["token"], rating=5)
            self.assertIn("expired", str(ctx.exception).lower())
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

    def _anon(self):
        """Public guest routes must work without a logged-in user."""
        self._get_user_patch.stop()
        self._get_user_patch = mock.patch.object(
            self.app_mod, "get_current_user", return_value=None
        )
        self._get_user_patch.start()

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
        html = public.get_data(as_text=True)
        self.assertIn("We value your feedback", html)
        self.assertIn("★", html)
        self.assertIn("feedback_hero", html)
        self.assertIn("data-google-url", html)
        self.assertIn("placeid=ChIJSTl7KeOViDARrKxuDpxfEo8", html)
        self.assertIn("hbe_logo", html)

        # Low-star form POST stores comment (no Google redirect).
        submitted = self.client.post(
            f"/f/{token}",
            data={"rating": "3", "comment": "Service was slow"},
        )
        self.assertEqual(submitted.status_code, 200)
        self.assertIn(b"Thank you", submitted.data)
        self.assertEqual(submitted.status_code, 200)
        # Low-star must not redirect away to Google
        self.assertNotIn("Location", submitted.headers)

        summary = self.client.get("/communication-hub/api/feedback/summary")
        data = summary.get_json()["summary"]
        self.assertEqual(data["responses"], 1)
        self.assertEqual(data["avg_rating"], 3.0)

        rows = self.client.get("/communication-hub/api/feedback/responses")
        self.assertEqual(rows.status_code, 200)
        self.assertEqual(len(rows.get_json()["responses"]), 1)
        self.assertEqual(rows.get_json()["responses"][0]["comment"], "Service was slow")

    def test_high_star_json_returns_google_url_and_stores(self):
        created = self.client.post(
            "/communication-hub/api/feedback/invites",
            json={"customer_name": "Priya", "source": "hotel"},
        )
        token = created.get_json()["invite"]["token"]

        self._anon()
        resp = self.client.post(
            f"/f/{token}",
            json={"rating": 5},
            headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["ok"])
        self.assertTrue(data["redirect_google"])
        self.assertEqual(data["google_url"], fb_mod.GOOGLE_REVIEW_URL)

        # Re-auth for hub API
        self._get_user_patch.stop()
        self._get_user_patch = mock.patch.object(
            self.app_mod, "get_current_user", return_value=self.user
        )
        self._get_user_patch.start()
        rows = self.client.get("/communication-hub/api/feedback/responses").get_json()[
            "responses"
        ]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["rating"], 5)

    def test_high_star_form_redirects_to_google(self):
        created = self.client.post(
            "/communication-hub/api/feedback/invites",
            json={"customer_name": "Arun", "source": "manual"},
        )
        token = created.get_json()["invite"]["token"]
        self._anon()
        resp = self.client.post(
            f"/f/{token}",
            data={"rating": "4"},
            follow_redirects=False,
        )
        self.assertIn(resp.status_code, (302, 303))
        self.assertEqual(resp.headers.get("Location"), fb_mod.GOOGLE_REVIEW_URL)

    def test_invalid_token(self):
        self._anon()
        resp = self.client.get("/f/not-a-valid-token!!")
        self.assertEqual(resp.status_code, 404)
        self.assertIn(b"invalid or has expired", resp.data)

        bad = self.client.post(
            "/f/aaaaaaaaaaaaaaaaaaaa",
            json={"rating": 5},
            headers={"Accept": "application/json"},
        )
        self.assertEqual(bad.status_code, 404)
        self.assertFalse(bad.get_json()["ok"])

    def test_already_submitted_still_allows_google_json(self):
        created = self.client.post(
            "/communication-hub/api/feedback/invites",
            json={"customer_name": "Neha", "source": "whatsapp"},
        )
        token = created.get_json()["invite"]["token"]
        self._anon()
        first = self.client.post(
            f"/f/{token}",
            json={"rating": 5},
            headers={"Accept": "application/json"},
        )
        self.assertTrue(first.get_json()["ok"])

        again = self.client.post(
            f"/f/{token}",
            json={"rating": 5},
            headers={"Accept": "application/json"},
        )
        self.assertEqual(again.status_code, 200)
        data = again.get_json()
        self.assertTrue(data["ok"])
        self.assertTrue(data.get("already"))
        self.assertTrue(data["redirect_google"])
        self.assertEqual(data["google_url"], fb_mod.GOOGLE_REVIEW_URL)

    def test_review_route_redirects_to_invite(self):
        from urllib.parse import urlparse

        self._anon()
        resp = self.client.get("/review", follow_redirects=False)
        self.assertIn(resp.status_code, (302, 303))
        loc = resp.headers.get("Location") or ""
        path = urlparse(loc).path if loc.startswith("http") else loc
        self.assertTrue(path.startswith("/f/"), path)
        follow = self.client.get(path)
        self.assertEqual(follow.status_code, 200)
        body = follow.get_data(as_text=True)
        self.assertIn("We value your feedback", body)
        self.assertIn("feedback_hero", body)
        self.assertIn("★", body)


class FeedbackExpiryHttpTests(unittest.TestCase):
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

    def _anon(self):
        self._get_user_patch.stop()
        self._get_user_patch = mock.patch.object(
            self.app_mod, "get_current_user", return_value=None
        )
        self._get_user_patch.start()

    def test_create_invite_api_returns_prod_url_and_expiry(self):
        created = self.client.post(
            "/communication-hub/api/feedback/invites",
            json={"customer_name": "Ravi", "source": "hotel"},
        )
        self.assertEqual(created.status_code, 200)
        payload = created.get_json()
        self.assertTrue(payload["ok"])
        invite = payload["invite"]
        self.assertTrue(
            invite["url"].startswith("https://belleliteaccounts.com/f/"),
            invite["url"],
        )
        self.assertEqual(invite.get("expires_in_hours"), 24)
        self.assertTrue(invite.get("expires_at"))
        expires_dt = datetime.strptime(invite["expires_at"], "%Y-%m-%d %H:%M:%S")
        skew = abs((expires_dt - datetime.now()).total_seconds() - 24 * 3600)
        self.assertLess(skew, 10)

    def test_expired_token_get_and_post_rejected(self):
        created = self.client.post(
            "/communication-hub/api/feedback/invites",
            json={"customer_name": "Expired", "source": "manual"},
        )
        token = created.get_json()["invite"]["token"]
        past = (datetime.now() - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
        conn = db_mod.get_db()
        try:
            conn.execute(
                "UPDATE customer_feedback_invites SET expires_at = ? WHERE token = ?",
                (past, token),
            )
            conn.commit()
        finally:
            conn.close()

        self._anon()
        get_resp = self.client.get(f"/f/{token}")
        self.assertEqual(get_resp.status_code, 200)
        body = get_resp.get_data(as_text=True)
        self.assertIn("Link expired", body)
        self.assertNotIn('id="fb-form"', body)

        post_resp = self.client.post(
            f"/f/{token}",
            json={"rating": 5},
            headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"},
        )
        self.assertEqual(post_resp.status_code, 410)
        data = post_resp.get_json()
        self.assertFalse(data["ok"])
        self.assertTrue(data.get("expired"))
        self.assertIn("expired", data["error"].lower())

    def test_fresh_token_still_works(self):
        created = self.client.post(
            "/communication-hub/api/feedback/invites",
            json={"customer_name": "Fresh", "source": "manual"},
        )
        token = created.get_json()["invite"]["token"]
        self._anon()
        get_resp = self.client.get(f"/f/{token}")
        self.assertEqual(get_resp.status_code, 200)
        self.assertIn("We value your feedback", get_resp.get_data(as_text=True))
        post_resp = self.client.post(
            f"/f/{token}",
            data={"rating": "3", "comment": "ok"},
        )
        self.assertEqual(post_resp.status_code, 200)
        self.assertIn(b"Thank you", post_resp.data)
