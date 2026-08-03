"""Tests for Communication Hub (WhatsApp inbox)."""

import os
import tempfile
import unittest
from unittest import mock

import db as db_mod
from workspace_access import get_endpoint_dashboard_module


class CommunicationHubTests(unittest.TestCase):
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

    def tearDown(self):
        self._get_user_patch.stop()
        db_mod.DATABASE_PATH = self._orig_path
        for key in ("WHATSAPP_DRY_RUN", "WHATSAPP_ACCESS_TOKEN", "WHATSAPP_PHONE_NUMBER_ID"):
            os.environ.pop(key, None)
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def test_endpoints_map_to_communication_hub(self):
        for endpoint in (
            "communication_hub",
            "communication_hub_api_conversations",
            "communication_hub_api_conversation_create",
            "communication_hub_api_messages",
            "communication_hub_api_message_send",
        ):
            self.assertEqual(get_endpoint_dashboard_module(endpoint), "communication_hub")

    def test_page_renders_marker(self):
        resp = self.client.get("/communication-hub")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn('id="communication-hub-page"', html)
        self.assertIn("Communication Hub", html)
        self.assertIn("data-communication-hub", html)

    def test_create_conversation_and_send_persists(self):
        create = self.client.post(
            "/communication-hub/api/conversations",
            json={"phone": "9876543210", "display_name": "Test Vendor"},
        )
        self.assertEqual(create.status_code, 200, create.get_data(as_text=True))
        payload = create.get_json()
        self.assertTrue(payload.get("ok"))
        conv = payload["conversation"]
        self.assertEqual(conv["phone"], "919876543210")
        self.assertEqual(conv["display_name"], "Test Vendor")

        with mock.patch(
            "whatsapp_client.send_text_message",
            return_value=(True, "", {"messages": [{"id": "wamid.test.1"}]}),
        ):
            send = self.client.post(
                f"/communication-hub/api/conversations/{conv['id']}/messages",
                json={"text": "Hello from Hub"},
            )
        self.assertEqual(send.status_code, 200, send.get_data(as_text=True))
        send_body = send.get_json()
        self.assertTrue(send_body.get("ok"))
        self.assertEqual(send_body["message"]["body"], "Hello from Hub")
        self.assertEqual(send_body["message"]["direction"], "out")
        self.assertEqual(send_body["message"]["status"], "sent")

        thread = self.client.get(
            f"/communication-hub/api/conversations/{conv['id']}/messages"
        )
        self.assertEqual(thread.status_code, 200)
        messages = thread.get_json()["messages"]
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["wa_message_id"], "wamid.test.1")

    def test_webhook_inbound_creates_conversation(self):
        from whatsapp_webhook import process_hub_inbound_messages

        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "metadata": {"phone_number_id": "123456"},
                                "contacts": [
                                    {
                                        "wa_id": "919999888777",
                                        "profile": {"name": "Inbound Guest"},
                                    }
                                ],
                                "messages": [
                                    {
                                        "from": "919999888777",
                                        "id": "wamid.inbound.1",
                                        "type": "text",
                                        "text": {"body": "Rate update please"},
                                    }
                                ],
                            }
                        }
                    ]
                }
            ]
        }
        conn = db_mod.get_db()
        try:
            db_mod.ensure_communication_hub_schema(conn)
            results = process_hub_inbound_messages(conn, payload)
            conn.commit()
            self.assertTrue(any("hub_in" in r for r in results), results)
            rows = conn.execute(
                "SELECT phone_e164, display_name, last_preview, unread_count FROM wa_conversations"
            ).fetchall()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["phone_e164"], "919999888777")
            self.assertEqual(rows[0]["display_name"], "Inbound Guest")
            self.assertIn("Rate update", rows[0]["last_preview"])
            self.assertEqual(rows[0]["unread_count"], 1)
            msgs = conn.execute("SELECT body, direction FROM wa_messages").fetchall()
            self.assertEqual(len(msgs), 1)
            self.assertEqual(msgs[0]["direction"], "in")
            self.assertEqual(msgs[0]["body"], "Rate update please")
        finally:
            conn.close()

    def test_webhook_skips_indent_button_for_hub_duplicate(self):
        from whatsapp_webhook import process_hub_inbound_messages

        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "metadata": {"phone_number_id": "123456"},
                                "messages": [
                                    {
                                        "from": "919111222333",
                                        "id": "wamid.btn.1",
                                        "type": "interactive",
                                        "interactive": {
                                            "type": "button_reply",
                                            "button_reply": {
                                                "id": "approve_abc-token-123",
                                                "title": "Approve",
                                            },
                                        },
                                    }
                                ],
                            }
                        }
                    ]
                }
            ]
        }
        conn = db_mod.get_db()
        try:
            db_mod.ensure_communication_hub_schema(conn)
            results = process_hub_inbound_messages(conn, payload)
            conn.commit()
            count = conn.execute("SELECT COUNT(*) AS n FROM wa_conversations").fetchone()["n"]
            self.assertEqual(count, 0)
            self.assertEqual(results, [])
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
