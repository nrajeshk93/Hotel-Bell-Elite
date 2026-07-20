import os
import tempfile
import unittest
from unittest import mock

import db as db_mod


class WhatsAppIndentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db_path = self.tmp.name
        self._orig_path = db_mod.DATABASE_PATH
        db_mod.DATABASE_PATH = self.db_path
        db_mod.init_db()

        import app as app_mod
        import stores as stores_mod

        self.app_mod = app_mod
        self.stores_mod = stores_mod
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
        self._get_user_patch = mock.patch.object(app_mod, "get_current_user", return_value=self.user)
        self._stores_user_patch = mock.patch.object(stores_mod, "_get_user", return_value=self.user)
        self._get_user_patch.start()
        self._stores_user_patch.start()

        self.env = mock.patch.dict(
            os.environ,
            {
                "WHATSAPP_ACCESS_TOKEN": "test-token",
                "WHATSAPP_PHONE_NUMBER_ID": "1241737459022736",
                "WHATSAPP_GRAPH_API_VERSION": "v21.0",
                "WHATSAPP_INDENT_APPROVAL_TEMPLATE": "indent_approval",
                "WHATSAPP_INDENT_APPROVER_NUMBERS": "8940651222",
                "WHATSAPP_INDENT_APPROVER_NAME": "Rajesh",
                "WHATSAPP_VERIFY_TOKEN": "verify-me",
            },
            clear=False,
        )
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self._get_user_patch.stop()
        self._stores_user_patch.stop()
        db_mod.DATABASE_PATH = self._orig_path
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def _create_pending_indent(self):
        create = self.client.post(
            "/stores/indent?outlet=bar",
            data={
                "outlet": "bar",
                "action": "submit",
                "notes": "Need stock",
                "item_name": ["Onion"],
                "quantity": ["2"],
                "unit": ["kg"],
                "approximate_price": ["50"],
            },
            follow_redirects=False,
        )
        self.assertEqual(create.status_code, 302)
        conn = db_mod.get_db()
        try:
            indent = conn.execute(
                "SELECT id, indent_no, status FROM store_indents ORDER BY id DESC LIMIT 1"
            ).fetchone()
            return dict(indent)
        finally:
            conn.close()

    @mock.patch("whatsapp_indent.wa.send_template_message")
    @mock.patch("whatsapp_indent.wa.upload_media_file")
    def test_send_for_approval_sends_whatsapp_template(self, upload_mock, send_mock):
        upload_mock.return_value = (True, "", {"id": "media-1"})
        send_mock.return_value = (True, "", {"messages": [{"id": "wamid.ABC"}]})

        indent = self._create_pending_indent()
        self.assertEqual(indent["status"], "pending")

        upload_mock.assert_called()
        send_mock.assert_called()
        args, kwargs = send_mock.call_args
        self.assertEqual(args[0], "918940651222")
        self.assertEqual(args[1], "indent_approval")
        self.assertEqual(kwargs.get("header_document_id"), "media-1")
        body = args[3]
        self.assertEqual(body["approver_name"], "Rajesh")
        self.assertEqual(body["indent_id"], indent["indent_no"])
        self.assertEqual(body["total_amount"], "100")

        conn = db_mod.get_db()
        try:
            row = conn.execute(
                """
                SELECT wa_message_id, status, recipient_phone
                FROM store_indent_whatsapp_messages
                WHERE indent_id = ?
                """,
                (indent["id"],),
            ).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["status"], "sent")
            self.assertEqual(row["wa_message_id"], "wamid.ABC")
            self.assertEqual(row["recipient_phone"], "918940651222")
        finally:
            conn.close()

    @mock.patch("whatsapp_webhook.wa.send_text_message", return_value=(True, "", {}))
    def test_webhook_approve_updates_indent(self, _text_mock):
        with mock.patch("whatsapp_indent.wa.upload_media_file", return_value=(True, "", {"id": "m1"})):
            with mock.patch(
                "whatsapp_indent.wa.send_template_message",
                return_value=(True, "", {"messages": [{"id": "wamid.APPROVE_ME"}]}),
            ):
                indent = self._create_pending_indent()

        payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "metadata": {"phone_number_id": "1241737459022736"},
                        "messages": [{
                            "from": "919999999999",
                            "type": "interactive",
                            "context": {"id": "wamid.APPROVE_ME"},
                            "interactive": {
                                "type": "button_reply",
                                "button_reply": {"id": "approve", "title": "Approve"},
                            },
                        }],
                    }
                }]
            }]
        }
        res = self.client.post("/webhook/whatsapp", json=payload)
        self.assertEqual(res.status_code, 200)

        conn = db_mod.get_db()
        try:
            status = conn.execute(
                "SELECT status, decision_note FROM store_indents WHERE id = ?",
                (indent["id"],),
            ).fetchone()
            self.assertEqual(status["status"], "approved")
            self.assertIn("WhatsApp", status["decision_note"])
        finally:
            conn.close()

    @mock.patch("whatsapp_webhook.wa.send_text_message", return_value=(True, "", {}))
    def test_webhook_reject_updates_indent(self, _text_mock):
        with mock.patch("whatsapp_indent.wa.upload_media_file", return_value=(True, "", {"id": "m1"})):
            with mock.patch(
                "whatsapp_indent.wa.send_template_message",
                return_value=(True, "", {"messages": [{"id": "wamid.REJECT_ME"}]}),
            ):
                indent = self._create_pending_indent()

        payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "metadata": {"phone_number_id": "1241737459022736"},
                        "messages": [{
                            "from": "919999999999",
                            "type": "interactive",
                            "context": {"id": "wamid.REJECT_ME"},
                            "interactive": {
                                "type": "button_reply",
                                "button_reply": {"id": "reject", "title": "Reject"},
                            },
                        }],
                    }
                }]
            }]
        }
        res = self.client.post("/webhook/whatsapp", json=payload)
        self.assertEqual(res.status_code, 200)

        conn = db_mod.get_db()
        try:
            status = conn.execute(
                "SELECT status, decision_note FROM store_indents WHERE id = ?",
                (indent["id"],),
            ).fetchone()
            self.assertEqual(status["status"], "rejected")
            self.assertEqual(status["decision_note"], "Rejected via WhatsApp")
        finally:
            conn.close()

    def test_webhook_verify(self):
        res = self.client.get(
            "/webhook/whatsapp",
            query_string={
                "hub.mode": "subscribe",
                "hub.verify_token": "verify-me",
                "hub.challenge": "12345",
            },
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data, b"12345")

    @mock.patch("whatsapp_webhook.wa.send_text_message", return_value=(True, "", {}))
    def test_webhook_text_approved_updates_indent(self, _text_mock):
        with mock.patch("whatsapp_indent.wa.upload_media_file", return_value=(True, "", {"id": "m1"})):
            with mock.patch(
                "whatsapp_indent.wa.send_template_message",
                return_value=(True, "", {"messages": [{"id": "wamid.TEXT_APPROVE"}]}),
            ):
                indent = self._create_pending_indent()

        payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "metadata": {"phone_number_id": "1241737459022736"},
                        "messages": [{
                            "from": "918940651222",
                            "type": "text",
                            "context": {"id": "wamid.TEXT_APPROVE"},
                            "text": {"body": "Approved"},
                        }],
                    }
                }]
            }]
        }
        res = self.client.post("/webhook/whatsapp", json=payload)
        self.assertEqual(res.status_code, 200)

        conn = db_mod.get_db()
        try:
            status = conn.execute(
                "SELECT status, decision_note FROM store_indents WHERE id = ?",
                (indent["id"],),
            ).fetchone()
            self.assertEqual(status["status"], "approved")
            self.assertEqual(status["decision_note"], "Approved via WhatsApp")
        finally:
            conn.close()

    @mock.patch("whatsapp_webhook.wa.send_text_message", return_value=(True, "", {}))
    def test_webhook_text_rejected_fallback_by_sender(self, _text_mock):
        """No reply-context: still resolve latest pending indent sent to that phone."""
        with mock.patch("whatsapp_indent.wa.upload_media_file", return_value=(True, "", {"id": "m1"})):
            with mock.patch(
                "whatsapp_indent.wa.send_template_message",
                return_value=(True, "", {"messages": [{"id": "wamid.TEXT_REJECT"}]}),
            ):
                indent = self._create_pending_indent()

        payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "metadata": {"phone_number_id": "1241737459022736"},
                        "messages": [{
                            "from": "918940651222",
                            "type": "text",
                            "text": {"body": "rejected"},
                        }],
                    }
                }]
            }]
        }
        res = self.client.post("/webhook/whatsapp", json=payload)
        self.assertEqual(res.status_code, 200)

        conn = db_mod.get_db()
        try:
            status = conn.execute(
                "SELECT status FROM store_indents WHERE id = ?",
                (indent["id"],),
            ).fetchone()["status"]
            self.assertEqual(status, "rejected")
        finally:
            conn.close()

    def test_indent_pdf_builds(self):
        from indent_approval_pdf import build_indent_approval_pdf

        pdf = build_indent_approval_pdf(
            {
                "indent_no": "IND-BAR-1",
                "outlet": "bar",
                "notes": "Test",
                "submitted_at": "2026-07-19 10:00:00",
            },
            [{"item_name": "Onion", "quantity": 2, "unit": "kg", "approximate_price": 50}],
            requested_by="Admin",
            outlet_label="Bar",
        )
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertGreater(len(pdf), 500)


if __name__ == "__main__":
    unittest.main()
