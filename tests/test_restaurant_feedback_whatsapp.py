"""Restaurant (Spices) Generate Invoice feedback WhatsApp."""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime
from unittest import mock

import db as db_mod
import restaurant_feedback_whatsapp as rfw
from workspace_access import (
    get_endpoint_dashboard_module,
    get_endpoint_point_of_sale_submodules,
)


class RestaurantFeedbackWhatsAppUnitTests(unittest.TestCase):
    def test_template_name_default(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("WHATSAPP_SPICES_FEEDBACK_TEMPLATE", None)
            os.environ.pop("WHATSAPP_SPICES_FEEDBACK_TEMPLATE_LANGUAGE", None)
            name, lang = rfw.spices_feedback_template_config()
        self.assertEqual(name, "spices_feedback_link")
        self.assertEqual(lang, "en")

    def test_header_image_file_exists(self):
        path = rfw.spices_feedback_header_image_path()
        self.assertTrue(os.path.isfile(path), path)


class RestaurantFeedbackWhatsAppSendTests(unittest.TestCase):
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
        with mock.patch.dict(os.environ, {"WHATSAPP_DRY_RUN": "1"}, clear=False):
            result = rfw.send_restaurant_feedback_whatsapp(
                {
                    "customer_name": "Rajesh",
                    "mobile": "9876543210",
                    "mobile_country": "+91",
                    "outlet": "restaurant",
                    "order_no": "SPC/25-26/1",
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
        self.assertEqual(invite.get("source"), "restaurant")
        self.assertEqual(invite.get("expires_in_hours"), 24)
        self.assertEqual(result.get("template_name"), "spices_feedback_link")
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
        result = rfw.send_restaurant_feedback_whatsapp(
            {"customer_name": "Rajesh", "mobile": ""}
        )
        self.assertFalse(result.get("ok"))
        self.assertEqual(result.get("status"), 400)
        self.assertIn("mobile", (result.get("error") or "").lower())


class RestaurantFeedbackWhatsAppApiTests(unittest.TestCase):
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

    def test_endpoint_maps_to_point_of_sale_invoice(self):
        self.assertEqual(
            get_endpoint_dashboard_module("point_of_sale_api_feedback_send_whatsapp"),
            "point_of_sale",
        )
        self.assertIn(
            "invoice",
            get_endpoint_point_of_sale_submodules(
                "point_of_sale_api_feedback_send_whatsapp"
            ),
        )

    def test_api_dry_run_ok(self):
        with mock.patch.dict(os.environ, {"WHATSAPP_DRY_RUN": "1"}, clear=False):
            resp = self.client.post(
                "/point-of-sale/api/feedback/send-whatsapp",
                json={
                    "customer_name": "Anita",
                    "mobile": "9123456780",
                    "mobile_country": "+91",
                    "outlet": "restaurant",
                },
            )
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        body = resp.get_json()
        self.assertTrue(body.get("ok"))
        self.assertTrue(body.get("dry_run"))
        self.assertEqual(body.get("template_name"), "spices_feedback_link")
        self.assertIn("/f/", body.get("share_url") or "")
        self.assertEqual((body.get("invite") or {}).get("source"), "restaurant")

    def test_api_missing_mobile(self):
        resp = self.client.post(
            "/point-of-sale/api/feedback/send-whatsapp",
            json={"customer_name": "Anita", "mobile": ""},
        )
        self.assertEqual(resp.status_code, 400)
        body = resp.get_json()
        self.assertFalse(body.get("ok"))
        self.assertIn("mobile", (body.get("error") or "").lower())


if __name__ == "__main__":
    unittest.main()
