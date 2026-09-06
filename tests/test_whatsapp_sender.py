"""Hotel Bell Elite WhatsApp Cloud API sender (phone_number_id / E.164)."""

from __future__ import annotations

import os
import unittest
from unittest import mock

import whatsapp_client as wa


class WhatsAppSenderConfigTests(unittest.TestCase):
    def tearDown(self):
        wa.clear_sender_display_cache()

    def test_hbe_constants_match_9611232344(self):
        self.assertEqual(wa.HBE_WHATSAPP_PHONE_NUMBER_ID, "1241737459022736")
        self.assertEqual(wa.HBE_WHATSAPP_SENDER_E164, "+919611232344")
        self.assertEqual(wa.HBE_WHATSAPP_SENDER_DIGITS, "919611232344")
        self.assertEqual(
            wa.normalise_whatsapp_number(wa.HBE_WHATSAPP_SENDER_E164),
            "919611232344",
        )
        self.assertEqual(
            wa.normalise_whatsapp_number("+91 96112 32344"),
            "919611232344",
        )

    def test_phone_number_id_prefers_env(self):
        with mock.patch.dict(
            os.environ,
            {"WHATSAPP_PHONE_NUMBER_ID": "999888777"},
            clear=False,
        ):
            self.assertEqual(wa.whatsapp_phone_number_id(), "999888777")

    def test_phone_number_id_falls_back_to_hbe_constant(self):
        env = os.environ.copy()
        env.pop("WHATSAPP_PHONE_NUMBER_ID", None)
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(
                wa.whatsapp_phone_number_id(),
                wa.HBE_WHATSAPP_PHONE_NUMBER_ID,
            )

    def test_graph_messages_url_uses_configured_sender_id(self):
        with mock.patch.dict(
            os.environ,
            {
                "WHATSAPP_PHONE_NUMBER_ID": wa.HBE_WHATSAPP_PHONE_NUMBER_ID,
                "WHATSAPP_GRAPH_API_VERSION": "v21.0",
            },
            clear=False,
        ):
            url = wa.graph_messages_url()
        self.assertIn(f"/{wa.HBE_WHATSAPP_PHONE_NUMBER_ID}/messages", url)
        self.assertTrue(url.startswith("https://graph.facebook.com/v21.0/"))

    def test_sender_e164_default_and_empty_disables(self):
        env = os.environ.copy()
        env.pop("WHATSAPP_SENDER_E164", None)
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(wa.whatsapp_sender_e164(), "+919611232344")
            self.assertEqual(wa.whatsapp_sender_digits(), "919611232344")
        with mock.patch.dict(os.environ, {"WHATSAPP_SENDER_E164": ""}, clear=False):
            self.assertEqual(wa.whatsapp_sender_e164(), "")
            self.assertEqual(wa.whatsapp_sender_digits(), "")


class WhatsAppSenderValidationTests(unittest.TestCase):
    def tearDown(self):
        wa.clear_sender_display_cache()

    def test_validate_refuses_when_display_digits_mismatch(self):
        with mock.patch.dict(
            os.environ,
            {
                "WHATSAPP_PHONE_NUMBER_ID": "1213272865195663",
                "WHATSAPP_SENDER_E164": "+919611232344",
                "WHATSAPP_SKIP_SENDER_VERIFY": "0",
            },
            clear=False,
        ):
            with mock.patch.object(
                wa,
                "fetch_phone_number_display_digits",
                return_value=(True, "919474241325", ""),
            ):
                ok, err = wa.validate_configured_sender(verify_via_api=True)
        self.assertFalse(ok)
        self.assertIn("mismatch", err.lower())
        self.assertIn("919474241325", err)
        self.assertIn("919611232344", err)

    def test_validate_ok_when_display_matches_hbe(self):
        with mock.patch.dict(
            os.environ,
            {
                "WHATSAPP_PHONE_NUMBER_ID": wa.HBE_WHATSAPP_PHONE_NUMBER_ID,
                "WHATSAPP_SENDER_E164": "+919611232344",
            },
            clear=False,
        ):
            with mock.patch.object(
                wa,
                "fetch_phone_number_display_digits",
                return_value=(True, "919611232344", ""),
            ):
                ok, err = wa.validate_configured_sender(verify_via_api=True)
        self.assertTrue(ok)
        self.assertEqual(err, "")

    def test_validate_skips_mismatch_when_api_cannot_verify(self):
        with mock.patch.dict(
            os.environ,
            {
                "WHATSAPP_PHONE_NUMBER_ID": "1213272865195663",
                "WHATSAPP_SENDER_E164": "+919611232344",
            },
            clear=False,
        ):
            with mock.patch.object(
                wa,
                "fetch_phone_number_display_digits",
                return_value=(False, "", "network down"),
            ):
                ok, err = wa.validate_configured_sender(verify_via_api=True)
        self.assertTrue(ok)
        self.assertEqual(err, "")

    def test_send_payload_uses_hbe_phone_number_id_in_url(self):
        captured = {}

        def fake_post(url, headers=None, json=None, timeout=None):
            captured["url"] = url
            captured["json"] = json
            resp = mock.Mock()
            resp.status_code = 200
            resp.json.return_value = {"messages": [{"id": "wamid.test"}]}
            resp.text = ""
            return resp

        env = {
            "WHATSAPP_ACCESS_TOKEN": "test-token-not-real",
            "WHATSAPP_PHONE_NUMBER_ID": wa.HBE_WHATSAPP_PHONE_NUMBER_ID,
            "WHATSAPP_SENDER_E164": "+919611232344",
            "WHATSAPP_GRAPH_API_VERSION": "v21.0",
            "WHATSAPP_DRY_RUN": "0",
            "WHATSAPP_ALLOW_IN_TESTS": "1",
            "WHATSAPP_SKIP_SENDER_VERIFY": "0",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            with mock.patch.object(
                wa,
                "fetch_phone_number_display_digits",
                return_value=(True, "919611232344", ""),
            ):
                with mock.patch.object(wa.requests, "post", side_effect=fake_post):
                    with mock.patch.object(wa, "_mirror_outbound_to_hub"):
                        ok, err, body = wa.send_payload(
                            {
                                "messaging_product": "whatsapp",
                                "to": "919876543210",
                                "type": "text",
                                "text": {"body": "hi"},
                            }
                        )
        self.assertTrue(ok, err)
        self.assertIn(wa.HBE_WHATSAPP_PHONE_NUMBER_ID, captured["url"])
        self.assertIn("/messages", captured["url"])
        # Body must not invent a from= digits field; sender is URL id only.
        self.assertNotIn("from", captured["json"] or {})

    def test_send_payload_refuses_on_sender_mismatch(self):
        with mock.patch.dict(
            os.environ,
            {
                "WHATSAPP_ACCESS_TOKEN": "test-token-not-real",
                "WHATSAPP_PHONE_NUMBER_ID": "1213272865195663",
                "WHATSAPP_SENDER_E164": "+919611232344",
                "WHATSAPP_DRY_RUN": "0",
                "WHATSAPP_ALLOW_IN_TESTS": "1",
            },
            clear=False,
        ):
            with mock.patch.object(
                wa,
                "fetch_phone_number_display_digits",
                return_value=(True, "919474241325", ""),
            ):
                with mock.patch.object(wa.requests, "post") as post_mock:
                    ok, err, body = wa.send_payload(
                        {
                            "messaging_product": "whatsapp",
                            "to": "919876543210",
                            "type": "text",
                            "text": {"body": "hi"},
                        }
                    )
        self.assertFalse(ok)
        self.assertIn("mismatch", err.lower())
        post_mock.assert_not_called()
        self.assertEqual(body, {})


if __name__ == "__main__":
    unittest.main()
