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

    def _create_pending_indent(self, notes="Need stock"):
        create = self.client.post(
            "/stores/indent?outlet=bar",
            data={
                "outlet": "bar",
                "action": "submit",
                "notes": notes,
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
                """
                SELECT id, indent_no, status, approval_token, wa_decided_by, wa_decision_message_id
                FROM store_indents
                ORDER BY id DESC LIMIT 1
                """
            ).fetchone()
            return dict(indent)
        finally:
            conn.close()

    def _token_button_payload(self, action, token, *, wa_context_id, sender="919999999999"):
        return {
            "entry": [{
                "changes": [{
                    "value": {
                        "metadata": {"phone_number_id": "1241737459022736"},
                        "contacts": [{
                            "profile": {"name": "Approver"},
                            "wa_id": sender,
                        }],
                        "messages": [{
                            "from": sender,
                            "id": f"wamid.INBOUND.{action.upper()}",
                            "type": "interactive",
                            "context": {"id": wa_context_id},
                            "interactive": {
                                "type": "button_reply",
                                "button_reply": {
                                    "id": f"{action}_{token}",
                                    "title": "Approve" if action == "approve" else "Reject",
                                },
                            },
                        }],
                    }
                }]
            }]
        }

    @mock.patch("whatsapp_indent.wa.send_template_message")
    @mock.patch("whatsapp_indent.wa.upload_media_file")
    @mock.patch("whatsapp_indent.wa.send_interactive_buttons")
    def test_notify_sends_one_interactive_message_only(
        self, buttons_mock, upload_mock, template_mock
    ):
        buttons_mock.return_value = (True, "", {"messages": [{"id": "wamid.BTN"}]})

        indent = self._create_pending_indent()
        self.assertEqual(indent["status"], "pending")
        self.assertTrue(indent["approval_token"])

        self.assertEqual(buttons_mock.call_count, 1)
        upload_mock.assert_not_called()
        template_mock.assert_not_called()

        phone, body, buttons = buttons_mock.call_args[0]
        self.assertEqual(phone, "918940651222")
        self.assertIn(indent["indent_no"], body)
        self.assertIn("Estimated Total", body)
        self.assertIn("100", body)
        self.assertIn("Approve or Reject", body)
        self.assertNotIn(indent["approval_token"], body)
        self.assertNotIn(indent["approval_token"][:8], body)
        self.assertNotIn("Token ", body)

        self.assertEqual(buttons[0][0], f"approve_{indent['approval_token']}")
        self.assertEqual(buttons[0][1], "Approve")
        self.assertEqual(buttons[1][0], f"reject_{indent['approval_token']}")
        self.assertEqual(buttons[1][1], "Reject")

        conn = db_mod.get_db()
        try:
            rows = conn.execute(
                """
                SELECT wa_message_id, status, recipient_phone, template_name, send_kind
                FROM store_indent_whatsapp_messages
                WHERE indent_id = ?
                """,
                (indent["id"],),
            ).fetchall()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["status"], "sent")
            self.assertEqual(rows[0]["wa_message_id"], "wamid.BTN")
            self.assertEqual(rows[0]["recipient_phone"], "918940651222")
            self.assertEqual(rows[0]["send_kind"], "interactive")
            self.assertEqual(rows[0]["template_name"], "interactive_approve_reject")

            ids = conn.execute(
                """
                SELECT wa_template_message_id, wa_interactive_message_id
                FROM store_indents WHERE id = ?
                """,
                (indent["id"],),
            ).fetchone()
            self.assertEqual(ids["wa_interactive_message_id"], "wamid.BTN")
            self.assertEqual(ids["wa_template_message_id"] or "", "")
        finally:
            conn.close()

    @mock.patch(
        "whatsapp_indent.wa.send_interactive_buttons",
        return_value=(True, "", {"messages": [{"id": "wamid.BTN"}]}),
    )
    def test_submit_stores_unique_approval_token(self, _buttons_mock):
        first = self._create_pending_indent(notes="First")
        second = self._create_pending_indent(notes="Second")
        self.assertTrue(first["approval_token"])
        self.assertTrue(second["approval_token"])
        self.assertNotEqual(first["approval_token"], second["approval_token"])
        self.assertRegex(
            first["approval_token"],
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        )

    @mock.patch("whatsapp_webhook.wa.send_text_message", return_value=(True, "", {}))
    @mock.patch(
        "whatsapp_indent.wa.send_interactive_buttons",
        return_value=(True, "", {"messages": [{"id": "wamid.BTN_A"}]}),
    )
    def test_webhook_approve_updates_indent(self, _buttons_mock, _text_mock):
        indent = self._create_pending_indent()

        payload = self._token_button_payload(
            "approve",
            indent["approval_token"],
            wa_context_id="wamid.BTN_A",
        )
        res = self.client.post("/webhook/whatsapp", json=payload)
        self.assertEqual(res.status_code, 200)

        conn = db_mod.get_db()
        try:
            status = conn.execute(
                """
                SELECT status, decision_note, wa_decided_by, wa_decision_message_id, decided_at
                FROM store_indents WHERE id = ?
                """,
                (indent["id"],),
            ).fetchone()
            self.assertEqual(status["status"], "approved")
            self.assertIn("WhatsApp", status["decision_note"])
            self.assertIn("919999999999", status["wa_decided_by"])
            self.assertEqual(status["wa_decision_message_id"], "wamid.INBOUND.APPROVE")
            self.assertTrue(status["decided_at"])
        finally:
            conn.close()

    @mock.patch("whatsapp_webhook.wa.send_text_message", return_value=(True, "", {}))
    @mock.patch(
        "whatsapp_indent.wa.send_interactive_buttons",
        return_value=(True, "", {"messages": [{"id": "wamid.BTN_TITLE"}]}),
    )
    def test_webhook_title_only_without_token_id_ignored(self, _buttons_mock, text_mock):
        """Title-only button_reply (no token id) must not approve or legacy-prompt."""
        indent = self._create_pending_indent()

        payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "metadata": {"phone_number_id": "1241737459022736"},
                        "contacts": [{
                            "profile": {"name": "Approver"},
                            "wa_id": "918940651222",
                        }],
                        "messages": [{
                            "from": "918940651222",
                            "id": "wamid.INBOUND.TITLE_ONLY",
                            "type": "interactive",
                            "context": {"id": "wamid.BTN_TITLE"},
                            "interactive": {
                                "type": "button_reply",
                                "button_reply": {"title": "Approve"},
                            },
                        }],
                    }
                }]
            }]
        }
        self.assertEqual(self.client.post("/webhook/whatsapp", json=payload).status_code, 200)
        conn = db_mod.get_db()
        try:
            status = conn.execute(
                "SELECT status FROM store_indents WHERE id = ?",
                (indent["id"],),
            ).fetchone()["status"]
            self.assertEqual(status, "pending")
        finally:
            conn.close()
        for call in text_mock.call_args_list:
            sent = call[0][1] if call[0] else ""
            self.assertNotIn("Could not match that reply", sent)
            self.assertNotIn("Please reply Approved or Rejected", sent)

    @mock.patch("whatsapp_webhook.wa.send_text_message", return_value=(True, "", {}))
    @mock.patch(
        "whatsapp_indent.wa.send_interactive_buttons",
        return_value=(True, "", {"messages": [{"id": "wamid.BTN_CTX"}]}),
    )
    def test_webhook_text_approve_ignored(self, _buttons_mock, text_mock):
        """Typing Approve/Approved must not approve and must not send legacy prompt."""
        indent = self._create_pending_indent()

        for body, mid in (("Approve", "wamid.INBOUND.APPROVE_TEXT"), ("Approved", "wamid.INBOUND.APPROVED_TEXT")):
            payload = {
                "entry": [{
                    "changes": [{
                        "value": {
                            "metadata": {"phone_number_id": "1241737459022736"},
                            "messages": [{
                                "from": "918940651222",
                                "id": mid,
                                "type": "text",
                                "context": {"id": "wamid.BTN_CTX"},
                                "text": {"body": body},
                            }],
                        }
                    }]
                }]
            }
            self.assertEqual(self.client.post("/webhook/whatsapp", json=payload).status_code, 200)

        conn = db_mod.get_db()
        try:
            status = conn.execute(
                "SELECT status FROM store_indents WHERE id = ?",
                (indent["id"],),
            ).fetchone()["status"]
            self.assertEqual(status, "pending")
        finally:
            conn.close()

        for call in text_mock.call_args_list:
            sent = call[0][1] if call[0] else ""
            self.assertNotIn("Could not match that reply", sent)
            self.assertNotIn("Please reply Approved or Rejected", sent)
            self.assertNotIn("waiting indent", sent.lower())

    @mock.patch("whatsapp_webhook.wa.send_text_message", return_value=(True, "", {}))
    @mock.patch(
        "whatsapp_indent.wa.send_interactive_buttons",
        return_value=(True, "", {"messages": [{"id": "wamid.BTN_BUTTON_TYPE"}]}),
    )
    def test_webhook_type_button_payload_updates_indent(self, _buttons_mock, _text_mock):
        """Meta type=button with payload approve_<token> must update the indent."""
        indent = self._create_pending_indent()
        token = indent["approval_token"]
        payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "metadata": {"phone_number_id": "1241737459022736"},
                        "contacts": [{
                            "profile": {"name": "Approver"},
                            "wa_id": "919999999999",
                        }],
                        "messages": [{
                            "from": "919999999999",
                            "id": "wamid.INBOUND.BUTTON_TYPE",
                            "type": "button",
                            "button": {
                                "payload": f"approve_{token}",
                                "text": "Approve",
                            },
                        }],
                    }
                }]
            }]
        }
        self.assertEqual(self.client.post("/webhook/whatsapp", json=payload).status_code, 200)
        conn = db_mod.get_db()
        try:
            status = conn.execute(
                "SELECT status FROM store_indents WHERE id = ?",
                (indent["id"],),
            ).fetchone()["status"]
            self.assertEqual(status, "approved")
        finally:
            conn.close()

    def test_parse_token_button_id_case_and_title_echo(self):
        import whatsapp_webhook as wh

        decision, token = wh.parse_token_button_id(
            "APPROVE_8f0d6bf4-bdcd-4d7b-ac3a-3400553df26a"
        )
        self.assertEqual(decision, "approved")
        self.assertEqual(token, "8f0d6bf4-bdcd-4d7b-ac3a-3400553df26a")
        decision, token = wh.parse_token_button_id("Approve")
        self.assertEqual(decision, "")
        self.assertEqual(token, "")
        decision, token = wh.parse_token_button_id("approve_Approve")
        self.assertEqual(decision, "")
        self.assertEqual(token, "")

    @mock.patch("whatsapp_webhook.wa.send_text_message", return_value=(True, "", {}))
    @mock.patch(
        "whatsapp_indent.wa.send_interactive_buttons",
        return_value=(True, "", {"messages": [{"id": "wamid.BTN_R"}]}),
    )
    def test_webhook_reject_updates_indent(self, _buttons_mock, _text_mock):
        indent = self._create_pending_indent()

        payload = self._token_button_payload(
            "reject",
            indent["approval_token"],
            wa_context_id="wamid.BTN_R",
        )
        res = self.client.post("/webhook/whatsapp", json=payload)
        self.assertEqual(res.status_code, 200)

        conn = db_mod.get_db()
        try:
            status = conn.execute(
                "SELECT status, decision_note, wa_decided_by FROM store_indents WHERE id = ?",
                (indent["id"],),
            ).fetchone()
            self.assertEqual(status["status"], "rejected")
            self.assertIn("Rejected via WhatsApp", status["decision_note"])
            self.assertIn("919999999999", status["wa_decided_by"])
        finally:
            conn.close()

    @mock.patch("whatsapp_webhook.wa.send_text_message", return_value=(True, "", {}))
    @mock.patch(
        "whatsapp_indent.wa.send_interactive_buttons",
        return_value=(True, "", {"messages": [{"id": "wamid.BTN"}]}),
    )
    def test_webhook_unknown_token_ignored(self, _buttons_mock, text_mock):
        indent = self._create_pending_indent()

        fake = "00000000-0000-4000-8000-000000000099"
        payload = self._token_button_payload("approve", fake, wa_context_id="wamid.BTN")
        res = self.client.post("/webhook/whatsapp", json=payload)
        self.assertEqual(res.status_code, 200)

        conn = db_mod.get_db()
        try:
            status = conn.execute(
                "SELECT status FROM store_indents WHERE id = ?",
                (indent["id"],),
            ).fetchone()["status"]
            self.assertEqual(status, "pending")
        finally:
            conn.close()
        text_mock.assert_called()
        sent = text_mock.call_args[0][1]
        self.assertIn("Unknown or expired approval token", sent)
        self.assertNotIn("Could not match that reply", sent)
        self.assertNotIn("Please reply Approved or Rejected", sent)

    @mock.patch("whatsapp_webhook.wa.send_text_message", return_value=(True, "", {}))
    @mock.patch(
        "whatsapp_indent.wa.send_interactive_buttons",
        return_value=(True, "", {"messages": [{"id": "wamid.BTN"}]}),
    )
    def test_webhook_duplicate_approve_returns_friendly_message(self, _buttons_mock, text_mock):
        indent = self._create_pending_indent()

        payload = self._token_button_payload(
            "approve",
            indent["approval_token"],
            wa_context_id="wamid.BTN",
        )
        self.assertEqual(self.client.post("/webhook/whatsapp", json=payload).status_code, 200)
        self.assertEqual(self.client.post("/webhook/whatsapp", json=payload).status_code, 200)

        conn = db_mod.get_db()
        try:
            status = conn.execute(
                "SELECT status FROM store_indents WHERE id = ?",
                (indent["id"],),
            ).fetchone()["status"]
            self.assertEqual(status, "approved")
        finally:
            conn.close()
        self.assertIn("already Approved", text_mock.call_args[0][1])

    @mock.patch("whatsapp_webhook.wa.send_text_message", return_value=(True, "", {}))
    @mock.patch("whatsapp_indent.wa.send_interactive_buttons")
    def test_webhook_token_approve_one_of_two_pending(self, buttons_mock, _text_mock):
        buttons_mock.side_effect = [
            (True, "", {"messages": [{"id": "wamid.BTNA"}]}),
            (True, "", {"messages": [{"id": "wamid.BTNB"}]}),
        ]
        first = self._create_pending_indent(notes="One")
        second = self._create_pending_indent(notes="Two")

        payload = self._token_button_payload(
            "approve",
            first["approval_token"],
            wa_context_id="wamid.BTNA",
        )
        self.assertEqual(self.client.post("/webhook/whatsapp", json=payload).status_code, 200)

        conn = db_mod.get_db()
        try:
            rows = {
                row["id"]: row["status"]
                for row in conn.execute(
                    "SELECT id, status FROM store_indents WHERE id IN (?, ?)",
                    (first["id"], second["id"]),
                ).fetchall()
            }
            self.assertEqual(rows[first["id"]], "approved")
            self.assertEqual(rows[second["id"]], "pending")
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

    @mock.patch(
        "whatsapp_indent.wa.send_interactive_buttons",
        return_value=(True, "", {"messages": [{"id": "wamid.ONCE"}]}),
    )
    def test_edit_pending_indent_does_not_resend_whatsapp(self, buttons_mock):
        """Saving an already-pending indent must not spam another approval request."""
        indent = self._create_pending_indent()
        self.assertEqual(buttons_mock.call_count, 1)
        token_before = indent["approval_token"]

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
        self.assertEqual(buttons_mock.call_count, 1)

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
                "SELECT status, notes, approval_token FROM store_indents WHERE id = ?",
                (indent["id"],),
            ).fetchone()
            self.assertEqual(status["status"], "pending")
            self.assertEqual(status["notes"], "Tweaked while waiting")
            self.assertEqual(status["approval_token"], token_before)
        finally:
            conn.close()

    @mock.patch(
        "whatsapp_indent.wa.send_interactive_buttons",
        return_value=(True, "", {"messages": [{"id": "wamid.IDEM"}]}),
    )
    def test_notify_is_idempotent_for_same_indent_approver(self, buttons_mock):
        """Direct re-notify for the same pending round must not re-send."""
        indent = self._create_pending_indent()
        self.assertEqual(buttons_mock.call_count, 1)

        import whatsapp_indent as wi

        conn = db_mod.get_db()
        try:
            ok, msg = wi.notify_indent_pending_whatsapp(conn, indent["id"], outlet_label="Bar")
            conn.commit()
            self.assertTrue(ok)
            self.assertIn("already sent", msg.lower())
            self.assertEqual(buttons_mock.call_count, 1)
        finally:
            conn.close()

    @mock.patch("whatsapp_indent.wa.send_interactive_buttons")
    def test_reject_then_resubmit_sends_whatsapp_again(self, buttons_mock):
        """A new approval round after reject should notify again."""
        buttons_mock.side_effect = [
            (True, "", {"messages": [{"id": "wamid.BTN1"}]}),
            (True, "", {"messages": [{"id": "wamid.BTN2"}]}),
        ]

        indent = self._create_pending_indent()
        token_before = indent["approval_token"]
        self.assertEqual(buttons_mock.call_count, 1)

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
        self.assertEqual(buttons_mock.call_count, 2)

        conn = db_mod.get_db()
        try:
            rows = conn.execute(
                """
                SELECT status, wa_message_id, template_name, send_kind
                FROM store_indent_whatsapp_messages
                WHERE indent_id = ?
                ORDER BY id
                """,
                (indent["id"],),
            ).fetchall()
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["status"], "superseded")
            self.assertEqual(rows[0]["wa_message_id"], "wamid.BTN1")
            self.assertEqual(rows[1]["status"], "sent")
            self.assertEqual(rows[1]["wa_message_id"], "wamid.BTN2")
            self.assertEqual(rows[1]["send_kind"], "interactive")
            row = conn.execute(
                "SELECT status, approval_token FROM store_indents WHERE id = ?",
                (indent["id"],),
            ).fetchone()
            self.assertEqual(row["status"], "pending")
            self.assertTrue(row["approval_token"])
            self.assertNotEqual(row["approval_token"], token_before)
        finally:
            conn.close()

    @mock.patch(
        "whatsapp_indent.wa.send_interactive_buttons",
        return_value=(True, "", {"messages": [{"id": "wamid.DUP"}]}),
    )
    def test_double_submit_same_token_creates_one_indent_and_one_whatsapp_send(
        self, buttons_mock
    ):
        """A repeated POST for the same rendered form must not create a second indent
        or fire a second WhatsApp approval request."""
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
                "SELECT id, status, approval_token FROM store_indents WHERE submission_token = ?",
                ("test-token-abc123",),
            ).fetchall()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["status"], "pending")
            self.assertTrue(rows[0]["approval_token"])

            wa_rows = conn.execute(
                """
                SELECT COUNT(*) AS c FROM store_indent_whatsapp_messages
                WHERE indent_id = ? AND status = 'sent'
                """,
                (rows[0]["id"],),
            ).fetchone()
            self.assertEqual(wa_rows["c"], 1)
        finally:
            conn.close()

        self.assertEqual(buttons_mock.call_count, 1)

    @mock.patch("whatsapp_indent.wa.send_interactive_buttons")
    def test_daily_cap_blocks_whatsapp_after_cap_sends(self, buttons_mock):
        """No more than 10 successful indent-approval WhatsApp sends per rolling 24h."""
        buttons_mock.return_value = (True, "", {"messages": [{"id": "wamid.CAP"}]})

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
                            (indent_id, recipient_phone, wa_message_id, template_name, status,
                             error_message, send_kind)
                        VALUES (?, ?, ?, ?, 'sent', '', 'interactive')
                        """,
                        (9000 + i, "918940651222", f"wamid.PRE{i}", "interactive_approve_reject"),
                    )
                conn.execute("PRAGMA foreign_keys = ON")
                conn.commit()
                self.assertEqual(wi.count_todays_indent_whatsapp_sends(conn), 10)
                self.assertEqual(wi.remaining_indent_whatsapp_daily_quota(conn), 0)
            finally:
                conn.close()

            indent = self._create_pending_indent()
            self.assertEqual(indent["status"], "pending")
            self.assertEqual(buttons_mock.call_count, 0)

            conn = db_mod.get_db()
            try:
                ok, msg = wi.notify_indent_pending_whatsapp(
                    conn, indent["id"], outlet_label="Bar"
                )
                conn.commit()
                self.assertFalse(ok)
                self.assertIn("WhatsApp indent approval limit", msg)
                self.assertIn("10 messages / 24 hours", msg)
                self.assertEqual(buttons_mock.call_count, 0)
            finally:
                conn.close()

    @mock.patch("whatsapp_indent.wa.send_interactive_buttons")
    def test_daily_cap_allows_send_when_under_limit(self, buttons_mock):
        buttons_mock.return_value = (True, "", {"messages": [{"id": "wamid.UNDER"}]})

        import whatsapp_indent as wi

        with mock.patch.dict(os.environ, {"WHATSAPP_INDENT_DAILY_CAP": "10"}, clear=False):
            conn = db_mod.get_db()
            try:
                conn.execute("PRAGMA foreign_keys = OFF")
                for i in range(9):
                    conn.execute(
                        """
                        INSERT INTO store_indent_whatsapp_messages
                            (indent_id, recipient_phone, wa_message_id, template_name, status,
                             error_message, send_kind)
                        VALUES (?, ?, ?, ?, 'sent', '', 'interactive')
                        """,
                        (9100 + i, "918940651222", f"wamid.U{i}", "interactive_approve_reject"),
                    )
                conn.execute("PRAGMA foreign_keys = ON")
                conn.commit()
                self.assertEqual(wi.remaining_indent_whatsapp_daily_quota(conn), 1)
            finally:
                conn.close()

            indent = self._create_pending_indent()
            self.assertEqual(buttons_mock.call_count, 1)

            conn = db_mod.get_db()
            try:
                self.assertEqual(wi.count_todays_indent_whatsapp_sends(conn), 10)
                self.assertEqual(wi.remaining_indent_whatsapp_daily_quota(conn), 0)
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

    def test_testing_mode_blocks_live_whatsapp_http(self):
        """Flask TESTING must refuse real Meta HTTP even with credentials loaded."""
        import whatsapp_client as wa

        with self.app.app_context():
            self.assertTrue(self.app.config.get("TESTING"))
            self.assertFalse(wa.whatsapp_live_sends_allowed())
            ok, err, body = wa.send_payload({"messaging_product": "whatsapp", "to": "91"})
            self.assertFalse(ok)
            self.assertIn("blocked", err.lower())
            self.assertEqual(body, {})

    @mock.patch("whatsapp_indent.wa.send_interactive_buttons")
    def test_one_submit_bounds_sends_to_one_per_approver(self, buttons_mock):
        """N approvers → exactly N interactive messages (never template+interactive)."""
        buttons_mock.side_effect = [
            (True, "", {"messages": [{"id": f"wamid.B{i}"}]}) for i in range(6)
        ]

        with mock.patch.dict(
            os.environ,
            {"WHATSAPP_INDENT_APPROVER_NUMBERS": "8940651222,9611232344,9876543210"},
            clear=False,
        ):
            indent = self._create_pending_indent(notes="Three approvers")
            self.assertEqual(buttons_mock.call_count, 3)

            import whatsapp_indent as wi

            conn = db_mod.get_db()
            try:
                for _ in range(20):
                    wi.notify_indent_pending_whatsapp(
                        conn, indent["id"], outlet_label="Bar"
                    )
                    conn.commit()
            finally:
                conn.close()

            self.assertEqual(buttons_mock.call_count, 3)

            conn = db_mod.get_db()
            try:
                rows = conn.execute(
                    """
                    SELECT send_kind, status, recipient_phone
                    FROM store_indent_whatsapp_messages
                    WHERE indent_id = ? AND status = 'sent'
                    ORDER BY id
                    """,
                    (indent["id"],),
                ).fetchall()
                self.assertEqual(len(rows), 3)
                kinds = [r["send_kind"] for r in rows]
                self.assertEqual(kinds.count("interactive"), 3)
            finally:
                conn.close()

    @mock.patch("whatsapp_indent.wa.send_interactive_buttons")
    def test_claim_before_send_blocks_concurrent_duplicate_notify(self, buttons_mock):
        """Second notify while first still 'sending' must not call Meta again."""
        buttons_mock.return_value = (True, "", {"messages": [{"id": "wamid.ONCE"}]})

        indent = self._create_pending_indent()
        self.assertEqual(buttons_mock.call_count, 1)

        import whatsapp_indent as wi

        conn = db_mod.get_db()
        try:
            wi.supersede_indent_whatsapp_sends(conn, indent["id"])
            token = wi.assign_fresh_approval_token(conn, indent["id"])
            conn.commit()
            claim = wi._claim_send(
                conn,
                indent_id=indent["id"],
                recipient_phone="918940651222",
                approval_token=token,
                send_kind=wi.SEND_KIND_INTERACTIVE,
                template_name="interactive_approve_reject",
            )
            self.assertIsNotNone(claim)

            ok, msg = wi.notify_indent_pending_whatsapp(
                conn, indent["id"], outlet_label="Bar"
            )
            conn.commit()
            self.assertTrue(ok)
            self.assertEqual(buttons_mock.call_count, 1)
            self.assertIn("already", msg.lower())
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
