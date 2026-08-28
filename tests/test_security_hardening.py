"""Focused tests for SECRET_KEY loading and WhatsApp webhook HMAC."""

from __future__ import annotations

import hashlib
import hmac
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


if __name__ == "__main__":
    unittest.main()
