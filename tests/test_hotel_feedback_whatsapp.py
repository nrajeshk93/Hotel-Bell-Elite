"""Hotel checkout feedback WhatsApp (Meta template hotel_feedback)."""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime
from unittest import mock

import db as db_mod
import hotel_feedback_whatsapp as hfw
from workspace_access import get_endpoint_dashboard_module, get_endpoint_hotel_rooms_submodules


class HotelFeedbackWhatsAppUnitTests(unittest.TestCase):
    def test_template_name_default(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("WHATSAPP_HOTEL_FEEDBACK_TEMPLATE", None)
            os.environ.pop("WHATSAPP_HOTEL_FEEDBACK_TEMPLATE_LANGUAGE", None)
            name, lang = hfw.hotel_feedback_template_config()
        self.assertEqual(name, "hotel_feedback_link")
        self.assertEqual(lang, "en")

    def test_guest_name_keeps_title_prefix(self):
        self.assertEqual(
            hfw.format_hotel_feedback_guest_name(
                {"customer_name": "Mr Rajesh Kumar"}
            ),
            "Mr Rajesh Kumar",
        )
        self.assertEqual(
            hfw.format_hotel_feedback_guest_name(
                {"title": "Mrs", "first_name": "Anita", "last_name": "Sharma"}
            ),
            "Mrs Anita Sharma",
        )
        self.assertEqual(
            hfw.format_hotel_feedback_guest_name(
                {"title": "Mr", "customer_name": "Rajesh"}
            ),
            "Mr Rajesh",
        )
        self.assertEqual(hfw.format_hotel_feedback_guest_name({}), "Guest")

    def test_rejects_missing_mobile(self):
        phone, err = hfw.resolve_hotel_feedback_mobile(
            {"customer_name": "Guest", "mobile": ""}
        )
        self.assertEqual(phone, "")
        self.assertIn("mobile", err.lower())

    def test_resolves_mobile_with_country(self):
        phone, err = hfw.resolve_hotel_feedback_mobile(
            {"mobile": "9876543210", "mobile_country": "+91"}
        )
        self.assertEqual(err, "")
        self.assertEqual(phone, "919876543210")

    def test_url_button_suffix_uses_token(self):
        self.assertEqual(
            hfw.feedback_url_button_suffix(
                "https://belleliteaccounts.com/f/abcTOKEN", "abcTOKEN"
            ),
            "abcTOKEN",
        )
        self.assertEqual(
            hfw.feedback_url_button_suffix(
                "https://belleliteaccounts.com/f/xyzOnly"
            ),
            "xyzOnly",
        )

    def test_payload_shape_has_image_header_body_and_url_button(self):
        payload = hfw.build_hotel_feedback_template_payload_shape(
            phone="919876543210",
            template_name="hotel_feedback_link",
            template_language="en",
            body_parameters=["Mr Rajesh"],
            header_image_id="media-img-1",
            url_button_suffix="tok123",
        )
        self.assertEqual(payload["type"], "template")
        self.assertEqual(payload["template"]["name"], "hotel_feedback_link")
        comps = payload["template"]["components"]
        self.assertEqual(comps[0]["type"], "header")
        self.assertEqual(comps[0]["parameters"][0]["type"], "image")
        self.assertEqual(comps[0]["parameters"][0]["image"]["id"], "media-img-1")
        self.assertEqual(comps[1]["type"], "body")
        self.assertEqual(comps[1]["parameters"][0]["text"], "Mr Rajesh")
        self.assertEqual(comps[2]["type"], "button")
        self.assertEqual(comps[2]["sub_type"], "url")
        self.assertEqual(comps[2]["index"], "0")
        self.assertEqual(comps[2]["parameters"][0]["text"], "tok123")

    def test_header_image_file_exists(self):
        path = hfw.feedback_header_image_path()
        self.assertTrue(os.path.isfile(path), path)


class HotelFeedbackWhatsAppSendTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db_path = self.tmp.name
        self._orig_path = db_mod.DATABASE_PATH
        db_mod.DATABASE_PATH = self.db_path
        db_mod.init_db()

    def tearDown(self):
        db_mod.DATABASE_PATH = self._orig_path
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def test_dry_run_mints_24h_invite_and_payload(self):
        with mock.patch.dict(
            os.environ, {"WHATSAPP_DRY_RUN": "1"}, clear=False
        ):
            result = hfw.send_hotel_feedback_whatsapp(
                {
                    "customer_name": "Mr Rajesh",
                    "mobile": "9876543210",
                    "mobile_country": "+91",
                    "room_number": "101",
                }
            )
        self.assertTrue(result.get("ok"), result)
        self.assertTrue(result.get("dry_run"))
        invite = result.get("invite") or {}
        self.assertTrue(invite.get("token"))
        self.assertTrue(
            str(result.get("share_url") or "").startswith(
                "https://belleliteaccounts.com/f/"
            ),
            result.get("share_url"),
        )
        self.assertEqual(invite.get("source"), "hotel")
        self.assertEqual(invite.get("expires_in_hours"), 24)
        expires = datetime.strptime(invite["expires_at"], "%Y-%m-%d %H:%M:%S")
        created = datetime.strptime(invite["created_at"], "%Y-%m-%d %H:%M:%S")
        self.assertAlmostEqual(
            (expires - created).total_seconds(),
            24 * 3600,
            delta=5,
        )
        comps = (result.get("payload") or {}).get("template", {}).get("components") or []
        types = [c.get("type") for c in comps]
        self.assertIn("header", types)
        self.assertIn("body", types)
        self.assertIn("button", types)
        button = next(c for c in comps if c.get("type") == "button")
        self.assertEqual(button.get("sub_type"), "url")
        self.assertEqual(button["parameters"][0]["text"], invite["token"])
        self.assertIn(invite["token"], str(result.get("share_url") or ""))
        self.assertEqual(result.get("send_path"), "dry_run")

    def test_missing_phone_returns_clear_error(self):
        result = hfw.send_hotel_feedback_whatsapp(
            {"customer_name": "Mr Rajesh", "mobile": ""}
        )
        self.assertFalse(result.get("ok"))
        self.assertEqual(result.get("status"), 400)
        self.assertIn("mobile", (result.get("error") or "").lower())


class HotelFeedbackWhatsAppApiTests(unittest.TestCase):
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

    def test_endpoint_maps_to_hotel_rooms(self):
        self.assertEqual(
            get_endpoint_dashboard_module("hotel_feedback_send_whatsapp"),
            "hotel_rooms",
        )
        self.assertIn(
            "rooms",
            get_endpoint_hotel_rooms_submodules("hotel_feedback_send_whatsapp"),
        )

    def test_api_dry_run_ok(self):
        with mock.patch.dict(os.environ, {"WHATSAPP_DRY_RUN": "1"}, clear=False):
            resp = self.client.post(
                "/hotel/api/feedback/send-whatsapp",
                json={
                    "customer_name": "Mrs Anita",
                    "mobile": "9123456780",
                    "mobile_country": "+91",
                    "room_number": "205",
                },
            )
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        body = resp.get_json()
        self.assertTrue(body.get("ok"))
        self.assertTrue(body.get("dry_run"))
        self.assertIn("/f/", body.get("share_url") or "")

    def test_api_missing_mobile(self):
        resp = self.client.post(
            "/hotel/api/feedback/send-whatsapp",
            json={"customer_name": "Mrs Anita", "mobile": ""},
        )
        self.assertEqual(resp.status_code, 400)
        body = resp.get_json()
        self.assertFalse(body.get("ok"))
        self.assertIn("mobile", (body.get("error") or "").lower())


class WhatsAppClientUrlButtonTests(unittest.TestCase):
    def test_send_template_includes_url_button_component(self):
        import whatsapp_client as wa

        captured = {}

        def fake_send(payload):
            captured["payload"] = payload
            return True, "", {"messages": [{"id": "wamid.x"}]}

        with mock.patch.object(wa, "send_payload", side_effect=fake_send):
            ok, err, _ = wa.send_template_message(
                "919876543210",
                "hotel_feedback_link",
                "en",
                body_parameters=["Mr Rajesh"],
                header_image_id="img-1",
                url_button_parameters="tokABC",
            )
        self.assertTrue(ok)
        self.assertEqual(err, "")
        comps = captured["payload"]["template"]["components"]
        button = comps[-1]
        self.assertEqual(button["type"], "button")
        self.assertEqual(button["sub_type"], "url")
        self.assertEqual(button["index"], "0")
        self.assertEqual(button["parameters"][0]["text"], "tokABC")


if __name__ == "__main__":
    unittest.main()
