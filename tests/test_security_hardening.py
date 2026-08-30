"""Focused tests for SECRET_KEY loading and WhatsApp webhook HMAC."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import secret_key as secret_key_mod
import whatsapp_webhook as wa_hook


class SecretKeyTests(unittest.TestCase):
    def test_env_secret_is_used_and_public_default_is_rejected(self):
        with mock.patch.dict(os.environ, {"SECRET_KEY": "unit-test-secret-key-value"}, clear=False):
            self.assertEqual(secret_key_mod.get_secret_key("/tmp/unused-secret"), "unit-test-secret-key-value")

        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "secret_key")
            env = os.environ.copy()
            env.pop("SECRET_KEY", None)
            with mock.patch.dict(os.environ, env, clear=True):
                first = secret_key_mod.get_secret_key(path)
                second = secret_key_mod.get_secret_key(path)
            self.assertTrue(first)
            self.assertEqual(first, second)
            self.assertNotEqual(first, secret_key_mod.PUBLIC_DEFAULT_SECRET_KEY)
            self.assertEqual(Path(path).read_text(encoding="utf-8").strip(), first)

        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "secret_key")
            env = {"SECRET_KEY": secret_key_mod.PUBLIC_DEFAULT_SECRET_KEY}
            with mock.patch.dict(os.environ, env, clear=False):
                generated = secret_key_mod.get_secret_key(path)
            self.assertNotEqual(generated, secret_key_mod.PUBLIC_DEFAULT_SECRET_KEY)
            self.assertTrue(generated)


class WhatsAppWebhookSignatureTests(unittest.TestCase):
    def test_verify_token_uses_compare_digest(self):
        class Req:
            args = {
                "hub.mode": "subscribe",
                "hub.verify_token": "verify-me",
                "hub.challenge": "challenge-token",
            }

        with mock.patch.dict(os.environ, {"WHATSAPP_VERIFY_TOKEN": "verify-me"}, clear=False):
            body, status, _headers = wa_hook.handle_verification_get(Req())
        self.assertEqual(status, 200)
        self.assertEqual(body, "challenge-token")

        with mock.patch.dict(os.environ, {"WHATSAPP_VERIFY_TOKEN": "verify-me"}, clear=False):
            Req.args = {
                "hub.mode": "subscribe",
                "hub.verify_token": "wrong",
                "hub.challenge": "challenge-token",
            }
            _body, status, _headers = wa_hook.handle_verification_get(Req())
        self.assertEqual(status, 403)

    def test_post_passthrough_when_app_secret_unset(self):
        raw = b'{"object":"whatsapp_business_account"}'

        class Req:
            headers = {}

            def get_data(self, as_text=False, cache=True):
                return raw.decode("utf-8") if as_text else raw

            def get_json(self, silent=True):
                return {"object": "whatsapp_business_account"}

        env = os.environ.copy()
        env.pop("WHATSAPP_APP_SECRET", None)
        env.pop("META_APP_SECRET", None)
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertFalse(wa_hook.verify_webhook_signature(Req()))

    def test_post_rejects_invalid_signature_when_secret_set(self):
        raw = b'{"object":"whatsapp_business_account"}'
        secret = "meta-app-secret-for-tests"
        digest = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()

        class Req:
            def __init__(self, header):
                self.headers = {"X-Hub-Signature-256": header}

            def get_data(self, as_text=False, cache=True):
                return raw.decode("utf-8") if as_text else raw

        with mock.patch.dict(os.environ, {"WHATSAPP_APP_SECRET": secret}, clear=False):
            self.assertTrue(wa_hook.verify_webhook_signature(Req("sha256=" + digest)))
            self.assertFalse(wa_hook.verify_webhook_signature(Req("sha256=deadbeef")))
            self.assertFalse(wa_hook.verify_webhook_signature(Req("")))


class CsrfAndHeaderSmokeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db_path = self.tmp.name
        import db as db_mod

        self.db_mod = db_mod
        self._orig_path = db_mod.DATABASE_PATH
        db_mod.DATABASE_PATH = self.db_path
        db_mod.init_db()
        import app as app_mod

        self.app_mod = app_mod
        self.app = app_mod.app
        self._prev_testing = self.app.config.get("TESTING")
        self.app.config["TESTING"] = False
        self.client = self.app.test_client()

    def tearDown(self):
        self.app.config["TESTING"] = self._prev_testing
        self.db_mod.DATABASE_PATH = self._orig_path
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def test_security_headers_on_login_page(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(resp.headers.get("Referrer-Policy"), "same-origin")
        self.assertEqual(resp.headers.get("X-Frame-Options"), "SAMEORIGIN")
        self.assertNotIn("Content-Security-Policy", resp.headers)

    def test_logout_get_does_not_clear_session(self):
        with self.client.session_transaction() as sess:
            sess["user_id"] = 1
        resp = self.client.get("/logout")
        self.assertEqual(resp.status_code, 405)
        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get("user_id"), 1)

    def test_mirror_export_requires_login(self):
        resp = self.client.get("/communication-hub/api/mirror-export", follow_redirects=False)
        self.assertIn(resp.status_code, (302, 303, 401))
        self.assertNotEqual(resp.status_code, 410)

    def test_csrf_blocks_authenticated_post_without_token(self):
        with self.client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["_csrf_token"] = "expected-csrf-token"
        resp = self.client.post("/logout")
        self.assertEqual(resp.status_code, 400)
        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get("user_id"), 1)

    def test_csrf_allows_authenticated_post_with_token(self):
        with self.client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["_csrf_token"] = "expected-csrf-token"
        resp = self.client.post(
            "/logout",
            data={"csrf_token": "expected-csrf-token"},
            headers={"X-CSRFToken": "expected-csrf-token"},
        )
        self.assertIn(resp.status_code, (302, 303))
        with self.client.session_transaction() as sess:
            self.assertNotIn("user_id", sess)


class PiiAndSecretsLockdownTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db_path = self.tmp.name
        import db as db_mod

        self.db_mod = db_mod
        self._orig_path = db_mod.DATABASE_PATH
        db_mod.DATABASE_PATH = self.db_path
        db_mod.init_db()
        self.doc_tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.doc_tmp.cleanup)
        import hotel_id_documents as docs

        self.docs = docs
        self._orig_docs_root = docs.hotel_id_docs_root
        docs.hotel_id_docs_root = lambda: Path(self.doc_tmp.name)
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
        self.admin = {
            "id": self.admin_id,
            "username": "admin",
            "full_name": "Administrator",
            "is_admin": True,
            "is_active": True,
            "dashboard_access": set(),
            "hotel_rooms_access": set(),
            "point_of_sale_access": set(),
        }
        self._get_user_patch = mock.patch.object(
            app_mod, "get_current_user", return_value=self.admin
        )
        self._get_user_patch.start()
        self._asia_env = mock.patch.dict(
            os.environ,
            {
                "ASIA_TECH_PASSWORD": "",
                "ASIA_TECH_CM_PASSWORD": "",
                "ASIA_TECH_USERNAME": "",
            },
            clear=False,
        )
        self._asia_env.start()

    def tearDown(self):
        self._asia_env.stop()
        self._get_user_patch.stop()
        self.docs.hotel_id_docs_root = self._orig_docs_root
        self.db_mod.DATABASE_PATH = self._orig_path
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def test_id_document_denied_for_unrelated_user(self):
        stored = "cccccccccccccccccccccccccccccccc.pdf"
        path = Path(self.doc_tmp.name) / stored
        path.write_bytes(b"%PDF-1.4 guest-id\n%%EOF\n")
        self.docs.persist_id_document_bytes(
            stored, path.read_bytes(), owner_user_id=self.admin_id
        )
        ok = self.client.get("/hotel/api/id-documents/" + stored)
        self.assertEqual(ok.status_code, 200)

        other = {
            "id": 99,
            "username": "posonly",
            "is_admin": False,
            "is_active": True,
            "dashboard_access": {"point_of_sale"},
            "hotel_rooms_access": set(),
            "point_of_sale_access": {"invoice"},
        }
        self._get_user_patch.stop()
        with mock.patch.object(self.app_mod, "get_current_user", return_value=other):
            denied = self.client.get("/hotel/api/id-documents/" + stored)
        self._get_user_patch.start()
        self.assertIn(denied.status_code, (302, 303, 401, 403, 404))
        self.assertNotIn(b"%PDF", denied.data)

        fo_other = {
            "id": 100,
            "username": "fo2",
            "is_admin": False,
            "is_active": True,
            "dashboard_access": {"hotel_rooms"},
            "hotel_rooms_access": {"rooms"},
        }
        self._get_user_patch.stop()
        with mock.patch.object(self.app_mod, "get_current_user", return_value=fo_other):
            orphan = self.client.get("/hotel/api/id-documents/" + stored)
        self._get_user_patch.start()
        self.assertEqual(orphan.status_code, 404)
        self.assertNotIn(b"%PDF", orphan.data)

    def test_settings_get_masks_asia_tech_password(self):
        secret = "asia-tech-unit-secret-value"
        put = self.client.put(
            "/hotel/api/settings",
            json={
                "settings": {
                    "panels": {
                        "asia_tech": {
                            "values": {
                                "asia_tech_username": {
                                    "kind": "text",
                                    "value": "hoteluser",
                                },
                                "asia_tech_hotel_id": {"kind": "text", "value": "42"},
                                "asia_tech_password": {
                                    "kind": "text",
                                    "value": secret,
                                },
                                "asia_tech_cm_password": {
                                    "kind": "text",
                                    "value": secret + "-cm",
                                },
                            }
                        }
                    }
                }
            },
        )
        self.assertEqual(put.status_code, 200)
        put_text = put.get_data(as_text=True)
        self.assertNotIn(secret, put_text)
        get_resp = self.client.get("/hotel/api/settings")
        self.assertEqual(get_resp.status_code, 200)
        body = get_resp.get_data(as_text=True)
        self.assertNotIn(secret, body)
        settings = (get_resp.get_json() or {}).get("settings") or {}
        state = settings.get("asia_tech_state") or {}
        self.assertNotEqual(state.get("password"), secret)
        self.assertNotEqual(state.get("cm_password"), secret + "-cm")
        self.assertNotEqual(state.get("api_key"), secret)
        conn = self.db_mod.get_db()
        try:
            stored = self.db_mod.get_hotel_settings(conn)
        finally:
            conn.close()
        stored_state = stored.get("asia_tech_state") or {}
        stored_pw = str(stored_state.get("password") or "")
        self.assertTrue(stored_pw.startswith("enc1$"))
        self.assertNotEqual(stored_pw, secret)
        import asia_tech_client

        self.assertEqual(asia_tech_client.get_api_key(stored), secret)
        self.assertEqual(asia_tech_client.get_cm_password(stored), secret + "-cm")

    def test_settings_get_seals_leftover_plaintext_asia_tech_secrets(self):
        secret = "leftover-plain-asia-tech-secret"
        conn = self.db_mod.get_db()
        try:
            self.db_mod.ensure_hotel_rooms_schema(conn)
            conn.execute(
                """
                INSERT INTO hotel_settings (id, payload, updated_at)
                VALUES (1, ?, datetime('now','localtime'))
                ON CONFLICT(id) DO UPDATE SET payload = excluded.payload
                """,
                (
                    json.dumps(
                        {
                            "asia_tech_state": {
                                "username": "front-office",
                                "password": secret,
                                "api_key": secret,
                                "cm_password": secret + "-cm",
                            }
                        }
                    ),
                ),
            )
            conn.commit()
        finally:
            conn.close()
        get_resp = self.client.get("/hotel/api/settings")
        self.assertEqual(get_resp.status_code, 200)
        self.assertNotIn(secret, get_resp.get_data(as_text=True))
        conn = self.db_mod.get_db()
        try:
            stored = self.db_mod.get_hotel_settings(conn)
        finally:
            conn.close()
        stored_pw = str((stored.get("asia_tech_state") or {}).get("password") or "")
        self.assertTrue(stored_pw.startswith("enc1$"))
        import asia_tech_client

        self.assertEqual(asia_tech_client.get_api_key(stored), secret)
        self.assertEqual(asia_tech_client.get_cm_password(stored), secret + "-cm")
        self.assertEqual((stored.get("asia_tech_state") or {}).get("username"), "front-office")

    def test_preview_cors_does_not_reflect_evil_origin(self):
        resp = self.client.get(
            "/preview-api/health",
            headers={"Origin": "https://evil.example"},
        )
        self.assertEqual(resp.status_code, 200)
        acao = resp.headers.get("Access-Control-Allow-Origin") or ""
        self.assertNotEqual(acao, "https://evil.example")
        self.assertNotEqual(acao, "*")
        if acao:
            self.assertNotEqual(
                resp.headers.get("Access-Control-Allow-Credentials"), "true"
            )

    def test_print_agent_register_without_session_or_pairing_fails(self):
        self._get_user_patch.stop()
        try:
            with self.client.session_transaction() as sess:
                sess.clear()
            reg = self.client.post(
                "/api/print-agent/register",
                json={
                    "agentId": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                    "businessId": "biz-demo",
                },
            )
            self.assertEqual(reg.status_code, 401)
            self.assertFalse((reg.get_json() or {}).get("ok"))
        finally:
            self._get_user_patch.start()

    def test_debug_default_is_false(self):
        self.assertFalse(self.app_mod.flask_debug_enabled(""))
        self.assertFalse(self.app_mod.flask_debug_enabled("0"))
        self.assertFalse(self.app_mod.flask_debug_enabled("false"))
        self.assertTrue(self.app_mod.flask_debug_enabled("1"))
        env = os.environ.copy()
        env.pop("FLASK_DEBUG", None)
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertFalse(self.app_mod.flask_debug_enabled())



if __name__ == "__main__":
    unittest.main()
