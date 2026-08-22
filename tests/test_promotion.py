"""Tests for Communication Hub Promotion (WhatsApp template blasts)."""

import io
import os
import tempfile
import unittest
from unittest import mock

from openpyxl import Workbook

import db as db_mod
import promotion as promo_mod
import whatsapp_client as wa
from workspace_access import get_endpoint_dashboard_module


def _xlsx_bytes(rows):
    wb = Workbook()
    ws = wb.active
    for row in rows:
        ws.append(list(row))
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


class PromotionUnitTests(unittest.TestCase):
    def test_analyze_template_body_params_and_sendable(self):
        simple = wa.analyze_message_template(
            {
                "name": "hello",
                "language": "en",
                "status": "APPROVED",
                "components": [
                    {"type": "BODY", "text": "Hello {{1}}, welcome aboard."},
                ],
            }
        )
        self.assertEqual(simple["body_param_count"], 1)
        self.assertTrue(simple["sendable"])

        media = wa.analyze_message_template(
            {
                "name": "flyer",
                "language": "en",
                "status": "APPROVED",
                "components": [
                    {"type": "HEADER", "format": "IMAGE"},
                    {"type": "BODY", "text": "Hi"},
                ],
            }
        )
        self.assertFalse(media["sendable"])
        self.assertTrue(media["needs_header_media"])

        multi = wa.analyze_message_template(
            {
                "name": "multi",
                "language": "en",
                "status": "APPROVED",
                "components": [
                    {"type": "BODY", "text": "Hi {{1}} and {{2}}"},
                ],
            }
        )
        self.assertEqual(multi["body_param_count"], 2)
        self.assertFalse(multi["sendable"])

    def test_parse_promotion_excel_valid_and_skips(self):
        buf = _xlsx_bytes(
            [
                ("Name", "Mobile"),
                ("Anita", "9876543210"),
                ("Bad", "123"),
                ("Dup", "9876543210"),
                ("Ravi", "919876543211"),
                ("", ""),
            ]
        )
        buf.name = "sample.xlsx"
        valid, skipped = promo_mod.parse_promotion_excel(buf)
        self.assertEqual(len(valid), 2)
        self.assertEqual(valid[0]["phone"], "919876543210")
        self.assertEqual(valid[0]["name"], "Anita")
        self.assertEqual(valid[1]["phone"], "919876543211")
        reasons = {s["reason"] for s in skipped}
        self.assertIn("Invalid mobile number", reasons)
        self.assertIn("Duplicate mobile in file", reasons)


class PromotionRouteTests(unittest.TestCase):
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
        os.environ["WHATSAPP_DRY_RUN"] = "1"
        os.environ["WHATSAPP_ACCESS_TOKEN"] = "test-token"
        os.environ["WHATSAPP_PHONE_NUMBER_ID"] = "123456"
        os.environ["WHATSAPP_WABA_ID"] = "999"

    def tearDown(self):
        self._get_user_patch.stop()
        db_mod.DATABASE_PATH = self._orig_path
        for key in (
            "WHATSAPP_DRY_RUN",
            "WHATSAPP_ACCESS_TOKEN",
            "WHATSAPP_PHONE_NUMBER_ID",
            "WHATSAPP_WABA_ID",
            "WHATSAPP_ALLOW_IN_TESTS",
        ):
            os.environ.pop(key, None)
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def test_endpoints_map_to_communication_hub(self):
        for endpoint in (
            "communication_hub_promotion",
            "communication_hub_api_promotion_templates",
            "communication_hub_api_promotion_preview",
            "communication_hub_api_promotion_send",
            "communication_hub_api_promotion_sample",
        ):
            self.assertEqual(get_endpoint_dashboard_module(endpoint), "communication_hub")

    def test_page_renders_marker_and_nav(self):
        resp = self.client.get("/communication-hub/promotion")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn('id="ch-promotion-page"', html)
        self.assertIn("data-communication-hub-promotion", html)
        self.assertIn("de-nav-communication-hub-promotion", html)
        self.assertIn(">Promotion<", html)

    def test_sample_xlsx_download(self):
        resp = self.client.get("/communication-hub/api/promotion/sample.xlsx")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(
            "spreadsheetml",
            (resp.headers.get("Content-Type") or "").lower(),
        )

    def test_templates_api(self):
        fake = [
            {
                "name": "promo_hello",
                "language": "en",
                "status": "APPROVED",
                "body_param_count": 1,
                "needs_header_media": False,
                "has_dynamic_buttons": False,
                "sendable": True,
                "block_reason": "",
                "category": "MARKETING",
            }
        ]
        with mock.patch.object(
            wa, "list_approved_message_templates", return_value=(True, "", fake)
        ):
            resp = self.client.get("/communication-hub/api/promotion/templates")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["templates"][0]["name"], "promo_hello")

    def test_preview_api(self):
        buf = _xlsx_bytes([("Name", "Mobile"), ("Anita", "9876543210"), ("Bad", "12")])
        data = {
            "file": (buf, "recipients.xlsx"),
        }
        resp = self.client.post(
            "/communication-hub/api/promotion/preview",
            data=data,
            content_type="multipart/form-data",
        )
        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["valid_count"], 1)
        self.assertGreaterEqual(payload["skipped_count"], 1)

    def test_send_api_mocked(self):
        template = {
            "name": "promo_hello",
            "language": "en",
            "status": "APPROVED",
            "body_param_count": 1,
            "needs_header_media": False,
            "has_dynamic_buttons": False,
            "sendable": True,
            "block_reason": "",
            "category": "MARKETING",
        }

        def fake_send(phone, name, language, body_parameters=None, **kwargs):
            return True, "", {"messages": [{"id": f"wamid.{phone}"}]}

        with mock.patch.object(
            wa, "list_approved_message_templates", return_value=(True, "", [template])
        ), mock.patch.object(wa, "send_template_message", side_effect=fake_send) as send_mock:
            resp = self.client.post(
                "/communication-hub/api/promotion/send",
                json={
                    "template_name": "promo_hello",
                    "template_language": "en",
                    "rows": [
                        {"row_number": 2, "name": "Anita", "phone": "9876543210"},
                        {"row_number": 3, "name": "Ravi", "phone": "919876543211"},
                    ],
                },
            )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["sent"], 2)
        self.assertEqual(data["failed"], 0)
        self.assertEqual(send_mock.call_count, 2)
        first = send_mock.call_args_list[0]
        self.assertEqual(first.args[0], "919876543210")
        self.assertEqual(first.args[1], "promo_hello")
        self.assertEqual(first.args[3], ["Anita"])

        conn = db_mod.get_db()
        try:
            camp = conn.execute(
                "SELECT * FROM wa_promo_campaigns WHERE id = ?",
                (data["campaign_id"],),
            ).fetchone()
            self.assertEqual(camp["sent_count"], 2)
            recs = conn.execute(
                "SELECT status FROM wa_promo_recipients WHERE campaign_id = ?",
                (data["campaign_id"],),
            ).fetchall()
            self.assertEqual(len(recs), 2)
            self.assertTrue(all(r["status"] == "sent" for r in recs))
        finally:
            conn.close()

    def test_send_blocks_unsupported_template(self):
        template = {
            "name": "with_image",
            "language": "en",
            "status": "APPROVED",
            "body_param_count": 0,
            "needs_header_media": True,
            "has_dynamic_buttons": False,
            "sendable": False,
            "block_reason": "This template needs header media (image/video/document).",
            "category": "MARKETING",
        }
        with mock.patch.object(
            wa, "list_approved_message_templates", return_value=(True, "", [template])
        ):
            resp = self.client.post(
                "/communication-hub/api/promotion/send",
                json={
                    "template_name": "with_image",
                    "template_language": "en",
                    "rows": [{"row_number": 1, "name": "A", "phone": "9876543210"}],
                },
            )
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(resp.get_json()["ok"])


if __name__ == "__main__":
    unittest.main()
