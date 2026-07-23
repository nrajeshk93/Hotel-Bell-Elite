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
                "WHATSAPP_INDENT_APPROVAL_TEMPLATE": "indent_approval_v2",
                "WHATSAPP_INDENT_APPROVER_NUMBERS": "8940651222",
                "WHATSAPP_INDENT_APPROVER_NAME": "Neeraj",
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
        self.assertEqual(args[1], "indent_approval_v2")
        self.assertEqual(args[3].get("approver_name"), "Neeraj")
        self.assertEqual(kwargs.get("header_document_id"), "media-1")
        body = args[3]
        self.assertEqual(body["approver_name"], "Neeraj")
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

    @mock.patch("whatsapp_indent.wa.send_template_message")
    @mock.patch("whatsapp_indent.wa.upload_media_file")
    def test_edit_pending_indent_does_not_resend_whatsapp(self, upload_mock, send_mock):
        """Saving an already-pending indent must not spam another approval request."""
        upload_mock.return_value = (True, "", {"id": "media-1"})
        send_mock.return_value = (True, "", {"messages": [{"id": "wamid.ONCE"}]})

        indent = self._create_pending_indent()
        self.assertEqual(send_mock.call_count, 1)

        update = self.client.post(
            "/stores/indent?outlet=bar",
            data={
                "outlet": "bar",
                "indent_id": str(indent["id"]),
                "action": "save",
                "notes": "Tweaked while waiting",
                "item_name": ["Onion"],
                "quantity": ["3"],
                "unit": ["kg"],
                "approximate_price": ["50"],
            },
            follow_redirects=False,
        )
        self.assertEqual(update.status_code, 302)
        self.assertEqual(send_mock.call_count, 1)
        self.assertEqual(upload_mock.call_count, 1)

        conn = db_mod.get_db()
        try:
            count = conn.execute(
                """
                SELECT COUNT(*) AS c
                FROM store_indent_whatsapp_messages
                WHERE indent_id = ? AND status = 'sent'
                """,
                (indent["id"],),
            ).fetchone()["c"]
            self.assertEqual(count, 1)
            status = conn.execute(
                "SELECT status, notes FROM store_indents WHERE id = ?",
                (indent["id"],),
            ).fetchone()
            self.assertEqual(status["status"], "pending")
            self.assertEqual(status["notes"], "Tweaked while waiting")
        finally:
            conn.close()

    @mock.patch("whatsapp_indent.wa.send_template_message")
    @mock.patch("whatsapp_indent.wa.upload_media_file")
    def test_notify_is_idempotent_for_same_indent_approver(self, upload_mock, send_mock):
        """Direct re-notify for the same pending round must not re-send."""
        upload_mock.return_value = (True, "", {"id": "media-1"})
        send_mock.return_value = (True, "", {"messages": [{"id": "wamid.IDEM"}]})

        indent = self._create_pending_indent()
        self.assertEqual(send_mock.call_count, 1)

        import whatsapp_indent as wi

        conn = db_mod.get_db()
        try:
            ok, msg = wi.notify_indent_pending_whatsapp(conn, indent["id"], outlet_label="Bar")
            conn.commit()
            self.assertTrue(ok)
            self.assertIn("already sent", msg.lower())
            self.assertEqual(send_mock.call_count, 1)
            self.assertEqual(upload_mock.call_count, 1)
        finally:
            conn.close()

    @mock.patch("whatsapp_indent.wa.send_template_message")
    @mock.patch("whatsapp_indent.wa.upload_media_file")
    def test_reject_then_resubmit_sends_whatsapp_again(self, upload_mock, send_mock):
        """A new approval round after reject should notify again."""
        upload_mock.return_value = (True, "", {"id": "media-1"})
        send_mock.side_effect = [
            (True, "", {"messages": [{"id": "wamid.FIRST"}]}),
            (True, "", {"messages": [{"id": "wamid.SECOND"}]}),
        ]

        indent = self._create_pending_indent()
        self.assertEqual(send_mock.call_count, 1)

        conn = db_mod.get_db()
        try:
            conn.execute(
                """
                UPDATE store_indents
                SET status = 'rejected', decision_note = 'Rejected via test', decided_at = ?
                WHERE id = ?
                """,
                ("2026-07-21 10:00:00", indent["id"]),
            )
            conn.commit()
        finally:
            conn.close()

        resubmit = self.client.post(
            "/stores/indent?outlet=bar",
            data={
                "outlet": "bar",
                "indent_id": str(indent["id"]),
                "action": "save",
                "notes": "Resubmitted after reject",
                "item_name": ["Onion"],
                "quantity": ["2"],
                "unit": ["kg"],
                "approximate_price": ["50"],
            },
            follow_redirects=False,
        )
        self.assertEqual(resubmit.status_code, 302)
        self.assertEqual(send_mock.call_count, 2)

        conn = db_mod.get_db()
        try:
            rows = conn.execute(
                """
                SELECT status, wa_message_id
                FROM store_indent_whatsapp_messages
                WHERE indent_id = ?
                ORDER BY id
                """,
                (indent["id"],),
            ).fetchall()
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["status"], "superseded")
            self.assertEqual(rows[0]["wa_message_id"], "wamid.FIRST")
            self.assertEqual(rows[1]["status"], "sent")
            self.assertEqual(rows[1]["wa_message_id"], "wamid.SECOND")
            row = conn.execute(
                "SELECT status FROM store_indents WHERE id = ?",
                (indent["id"],),
            ).fetchone()
            self.assertEqual(row["status"], "pending")
        finally:
            conn.close()

    @mock.patch("whatsapp_indent.wa.send_template_message")
    @mock.patch("whatsapp_indent.wa.upload_media_file")
    def test_double_submit_same_token_creates_one_indent_and_one_whatsapp_send(
        self, upload_mock, send_mock
    ):
        """A repeated POST for the same rendered form (double-click, soft-nav
        retry, browser resubmit) must not create a second indent or fire a
        second WhatsApp approval request — this is the 'multiple indent
        approval request' bug."""
        upload_mock.return_value = (True, "", {"id": "media-1"})
        send_mock.return_value = (True, "", {"messages": [{"id": "wamid.DUP"}]})

        payload = {
            "outlet": "bar",
            "action": "submit",
            "notes": "Need stock urgently",
            "submission_token": "test-token-abc123",
            "item_name": ["Onion"],
            "quantity": ["2"],
            "unit": ["kg"],
            "approximate_price": ["50"],
        }

        first = self.client.post("/stores/indent?outlet=bar", data=payload, follow_redirects=False)
        self.assertEqual(first.status_code, 302)
        second = self.client.post("/stores/indent?outlet=bar", data=payload, follow_redirects=False)
        self.assertEqual(second.status_code, 302)

        conn = db_mod.get_db()
        try:
            rows = conn.execute(
                "SELECT id, status FROM store_indents WHERE submission_token = ?",
                ("test-token-abc123",),
            ).fetchall()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["status"], "pending")

            wa_rows = conn.execute(
                "SELECT COUNT(*) AS c FROM store_indent_whatsapp_messages WHERE indent_id = ? AND status = 'sent'",
                (rows[0]["id"],),
            ).fetchone()
            self.assertEqual(wa_rows["c"], 1)
        finally:
            conn.close()

        self.assertEqual(send_mock.call_count, 1)
        self.assertEqual(upload_mock.call_count, 1)

    @mock.patch("whatsapp_indent.wa.send_template_message")
    @mock.patch("whatsapp_indent.wa.upload_media_file")
    def test_daily_cap_blocks_whatsapp_after_15_sends(self, upload_mock, send_mock):
        """No more than 10 successful indent-approval WhatsApp sends per rolling 24h."""
        upload_mock.return_value = (True, "", {"id": "media-1"})
        send_mock.return_value = (True, "", {"messages": [{"id": "wamid.CAP"}]})

        import whatsapp_indent as wi

        with mock.patch.dict(os.environ, {"WHATSAPP_INDENT_DAILY_CAP": "10"}, clear=False):
            self.assertEqual(wi.indent_whatsapp_daily_cap(), 10)

            conn = db_mod.get_db()
            try:
                conn.execute("PRAGMA foreign_keys = OFF")
                for i in range(10):
                    conn.execute(
                        """
                        INSERT INTO store_indent_whatsapp_messages
                            (indent_id, recipient_phone, wa_message_id, template_name, status, error_message)
                        VALUES (?, ?, ?, ?, 'sent', '')
                        """,
                        (9000 + i, "918940651222", f"wamid.PRE{i}", "indent_approval_v2"),
                    )
                conn.execute("PRAGMA foreign_keys = ON")
                conn.commit()
                self.assertEqual(wi.count_todays_indent_whatsapp_sends(conn), 10)
                self.assertEqual(wi.remaining_indent_whatsapp_daily_quota(conn), 0)
            finally:
                conn.close()

            indent = self._create_pending_indent()
            self.assertEqual(indent["status"], "pending")
            # Cap already full — create should not send another WhatsApp.
            self.assertEqual(send_mock.call_count, 0)
            self.assertEqual(upload_mock.call_count, 0)

            conn = db_mod.get_db()
            try:
                ok, msg = wi.notify_indent_pending_whatsapp(
                    conn, indent["id"], outlet_label="Bar"
                )
                conn.commit()
                self.assertFalse(ok)
                self.assertIn("WhatsApp indent approval limit", msg)
                self.assertIn("10 messages / 24 hours", msg)
                self.assertEqual(send_mock.call_count, 0)
            finally:
                conn.close()

    @mock.patch("whatsapp_indent.wa.send_template_message")
    @mock.patch("whatsapp_indent.wa.upload_media_file")
    def test_daily_cap_allows_send_when_under_limit(self, upload_mock, send_mock):
        upload_mock.return_value = (True, "", {"id": "media-1"})
        send_mock.return_value = (True, "", {"messages": [{"id": "wamid.UNDER"}]})

        import whatsapp_indent as wi

        with mock.patch.dict(os.environ, {"WHATSAPP_INDENT_DAILY_CAP": "10"}, clear=False):
            conn = db_mod.get_db()
            try:
                conn.execute("PRAGMA foreign_keys = OFF")
                for i in range(9):
                    conn.execute(
                        """
                        INSERT INTO store_indent_whatsapp_messages
                            (indent_id, recipient_phone, wa_message_id, template_name, status, error_message)
                        VALUES (?, ?, ?, ?, 'sent', '')
                        """,
                        (9100 + i, "918940651222", f"wamid.U{i}", "indent_approval_v2"),
                    )
                conn.execute("PRAGMA foreign_keys = ON")
                conn.commit()
                self.assertEqual(wi.remaining_indent_whatsapp_daily_quota(conn), 1)
            finally:
                conn.close()

            indent = self._create_pending_indent()
            self.assertEqual(send_mock.call_count, 1)
            self.assertEqual(upload_mock.call_count, 1)

            conn = db_mod.get_db()
            try:
                self.assertEqual(wi.count_todays_indent_whatsapp_sends(conn), 10)
                self.assertEqual(wi.remaining_indent_whatsapp_daily_quota(conn), 0)
                # Indent itself still saved as pending even when later notifies are blocked.
                row = conn.execute(
                    "SELECT status FROM store_indents WHERE id = ?",
                    (indent["id"],),
                ).fetchone()
                self.assertEqual(row["status"], "pending")
            finally:
                conn.close()

    def test_indent_pdf_builds(self):
        from indent_approval_pdf import build_indent_approval_pdf, _money

        self.assertEqual(_money(50), "Rs. 50")
        self.assertEqual(_money(50.5), "Rs. 50.50")
        self.assertNotIn("₹", _money(100))

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
        self.assertNotIn("₹".encode("utf-8"), pdf)


if __name__ == "__main__":
    unittest.main()
