"""Lifetime WhatsApp outbound message limit (License + send_payload choke-point)."""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

import db as db_mod
import whatsapp_client as wa


class WhatsAppMessageLimitHelpersTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db_path = self.tmp.name
        self._orig_path = db_mod.DATABASE_PATH
        db_mod.DATABASE_PATH = self.db_path
        db_mod.init_db()
        self.conn = db_mod.get_db()

    def tearDown(self):
        try:
            self.conn.close()
        except Exception:
            pass
        db_mod.DATABASE_PATH = self._orig_path
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def test_default_limit_and_empty_count(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("WHATSAPP_MESSAGE_LIMIT", None)
            self.assertEqual(db_mod.whatsapp_message_limit(), 1000)
        quota = db_mod.whatsapp_outbound_quota(self.conn)
        self.assertEqual(quota["sent"], 0)
        self.assertEqual(quota["limit"], 1000)
        self.assertEqual(quota["remaining"], 1000)
        self.assertFalse(quota["exhausted"])
        self.assertEqual(quota["display"], "1000")

    def test_record_increments_and_exhausts(self):
        with mock.patch.dict(os.environ, {"WHATSAPP_MESSAGE_LIMIT": "2"}, clear=False):
            db_mod.record_whatsapp_outbound_send(
                self.conn, wa_message_id="wamid.1", to_phone="919999999999", message_type="text"
            )
            db_mod.record_whatsapp_outbound_send(
                self.conn, wa_message_id="wamid.2", to_phone="919999999998", message_type="template"
            )
            self.conn.commit()
            quota = db_mod.whatsapp_outbound_quota(self.conn)
            self.assertEqual(quota["sent"], 2)
            self.assertEqual(quota["limit"], 2)
            self.assertEqual(quota["remaining"], 0)
            self.assertTrue(quota["exhausted"])
            self.assertEqual(quota["display"], "0")

    def test_invalid_env_falls_back_to_1000(self):
        with mock.patch.dict(os.environ, {"WHATSAPP_MESSAGE_LIMIT": "nope"}, clear=False):
            self.assertEqual(db_mod.whatsapp_message_limit(), 1000)
        with mock.patch.dict(os.environ, {"WHATSAPP_MESSAGE_LIMIT": "-5"}, clear=False):
            self.assertEqual(db_mod.whatsapp_message_limit(), 0)


class WhatsAppSendPayloadQuotaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db_path = self.tmp.name
        self._orig_path = db_mod.DATABASE_PATH
        db_mod.DATABASE_PATH = self.db_path
        db_mod.init_db()

    def tearDown(self):
        wa.clear_sender_display_cache()
        db_mod.DATABASE_PATH = self._orig_path
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def _fill_to_limit(self, n: int):
        conn = db_mod.get_db()
        try:
            for i in range(n):
                db_mod.record_whatsapp_outbound_send(
                    conn,
                    wa_message_id=f"wamid.fill.{i}",
                    to_phone="919611232344",
                    message_type="text",
                )
            conn.commit()
        finally:
            conn.close()

    def test_send_payload_refuses_when_exhausted(self):
        with mock.patch.dict(
            os.environ,
            {
                "WHATSAPP_MESSAGE_LIMIT": "1",
                "WHATSAPP_ACCESS_TOKEN": "token",
                "WHATSAPP_PHONE_NUMBER_ID": wa.HBE_WHATSAPP_PHONE_NUMBER_ID,
                "WHATSAPP_SENDER_E164": "",
                "WHATSAPP_DRY_RUN": "0",
                "WHATSAPP_ALLOW_IN_TESTS": "1",
            },
            clear=False,
        ):
            self._fill_to_limit(1)
            with mock.patch.object(wa, "validate_configured_sender", return_value=(True, "")):
                with mock.patch.object(wa.requests, "post") as post:
                    ok, err, body = wa.send_payload(
                        {
                            "messaging_product": "whatsapp",
                            "to": "919876543210",
                            "type": "text",
                            "text": {"body": "hi"},
                        }
                    )
        self.assertFalse(ok)
        self.assertIn("message limit reached", err.lower())
        self.assertIn("1/1", err)
        self.assertEqual(body, {})
        post.assert_not_called()

    def test_send_payload_records_on_success(self):
        with mock.patch.dict(
            os.environ,
            {
                "WHATSAPP_MESSAGE_LIMIT": "1000",
                "WHATSAPP_ACCESS_TOKEN": "token",
                "WHATSAPP_PHONE_NUMBER_ID": wa.HBE_WHATSAPP_PHONE_NUMBER_ID,
                "WHATSAPP_SENDER_E164": "",
                "WHATSAPP_DRY_RUN": "0",
                "WHATSAPP_ALLOW_IN_TESTS": "1",
            },
            clear=False,
        ):
            fake = mock.Mock()
            fake.status_code = 200
            fake.json.return_value = {
                "messages": [{"id": "wamid.quota.test"}],
            }
            with mock.patch.object(wa, "validate_configured_sender", return_value=(True, "")):
                with mock.patch.object(wa.requests, "post", return_value=fake):
                    with mock.patch.object(wa, "_mirror_outbound_to_hub"):
                        ok, err, body = wa.send_payload(
                            {
                                "messaging_product": "whatsapp",
                                "to": "919876543210",
                                "type": "text",
                                "text": {"body": "hi"},
                            }
                        )
        self.assertTrue(ok)
        self.assertEqual(err, "")
        self.assertEqual(body.get("messages", [{}])[0].get("id"), "wamid.quota.test")
        conn = db_mod.get_db()
        try:
            quota = db_mod.whatsapp_outbound_quota(conn)
            self.assertEqual(quota["sent"], 1)
            self.assertEqual(quota["display"], "999")
            row = conn.execute(
                "SELECT wa_message_id, to_phone, message_type FROM wa_outbound_sends"
            ).fetchone()
            self.assertEqual(row["wa_message_id"], "wamid.quota.test")
            self.assertEqual(row["to_phone"], "919876543210")
            self.assertEqual(row["message_type"], "text")
        finally:
            conn.close()

    def test_failed_meta_response_does_not_count(self):
        with mock.patch.dict(
            os.environ,
            {
                "WHATSAPP_MESSAGE_LIMIT": "1000",
                "WHATSAPP_ACCESS_TOKEN": "token",
                "WHATSAPP_PHONE_NUMBER_ID": wa.HBE_WHATSAPP_PHONE_NUMBER_ID,
                "WHATSAPP_SENDER_E164": "",
                "WHATSAPP_DRY_RUN": "0",
                "WHATSAPP_ALLOW_IN_TESTS": "1",
            },
            clear=False,
        ):
            fake = mock.Mock()
            fake.status_code = 500
            fake.text = "boom"
            with mock.patch.object(wa, "validate_configured_sender", return_value=(True, "")):
                with mock.patch.object(wa.requests, "post", return_value=fake):
                    ok, err, _body = wa.send_payload(
                        {
                            "messaging_product": "whatsapp",
                            "to": "919876543210",
                            "type": "text",
                            "text": {"body": "hi"},
                        }
                    )
        self.assertFalse(ok)
        self.assertIn("boom", err)
        conn = db_mod.get_db()
        try:
            self.assertEqual(db_mod.count_whatsapp_outbound_sends(conn), 0)
        finally:
            conn.close()


class LicenseWhatsAppLimitDisplayTests(unittest.TestCase):
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
        self.admin = {
            "id": self.admin_id,
            "username": "admin",
            "full_name": "Administrator",
            "is_admin": True,
            "is_active": True,
            "dashboard_access": {"settings", "home"},
            "stores_access": set(),
        }
        self._get_user_patch = mock.patch.object(
            app_mod, "get_current_user", side_effect=lambda: self.admin
        )
        self._get_user_patch.start()

    def tearDown(self):
        self._get_user_patch.stop()
        db_mod.DATABASE_PATH = self._orig_path
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def test_license_page_shows_whatsapp_message_limit(self):
        with mock.patch.dict(os.environ, {"WHATSAPP_MESSAGE_LIMIT": "1000"}, clear=False):
            page = self.client.get("/license")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn("WhatsApp available limit", html)
        self.assertIn('data-lic-wa-limit', html)
        self.assertIn(">1000<", html)

    def test_license_payload_reflects_sent_count(self):
        conn = db_mod.get_db()
        try:
            db_mod.record_whatsapp_outbound_send(
                conn, wa_message_id="wamid.lic", to_phone="919876543210", message_type="template"
            )
            conn.commit()
            with mock.patch.dict(os.environ, {"WHATSAPP_MESSAGE_LIMIT": "1000"}, clear=False):
                payload = self.app_mod._license_payload(conn, include_renewals=False)
        finally:
            conn.close()
        lic = payload["license"]
        self.assertEqual(lic["whatsapp_messages_sent"], 1)
        self.assertEqual(lic["whatsapp_message_limit"], 1000)
        self.assertEqual(lic["whatsapp_messages_remaining"], 999)
        self.assertEqual(lic["whatsapp_message_limit_display"], "999")


if __name__ == "__main__":
    unittest.main()
