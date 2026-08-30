"""Unified print job queue tests."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest import mock

import db as db_mod
from print_agent_store import register_print_agent
from print_job_service import (
    create_print_job,
    deliver_pending_jobs_for_agent,
    enqueue_kot_jobs_for_invoice,
    get_print_job,
    recover_stale_print_jobs,
    update_job_status,
)


class PrintJobServiceTests(unittest.TestCase):
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
        }
        self._get_user_patch = mock.patch.object(app_mod, "get_current_user", return_value=self.user)
        self._get_user_patch.start()

        conn = db_mod.get_db()
        try:
            reg = register_print_agent(
                conn,
                {
                    "agentId": "agent-kitchen-001",
                    "businessId": "hotel-bell-elite",
                    "deviceName": "KITCHEN-PC",
                    "installedPrinters": ["Kitchen Printer"],
                },
            )
            self.agent_id = reg["agentId"]
            conn.execute(
                """
                UPDATE print_agents
                SET mapped_printers_json = ?, last_seen_at = ?
                WHERE agent_id = ?
                """,
                (
                    json.dumps({"kitchen1": "Kitchen Printer", "bar": "Bar Printer"}),
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    self.agent_id,
                ),
            )
            conn.commit()
        finally:
            conn.close()

        self.invoice_id = self._seed_open_invoice()

    def tearDown(self):
        self._get_user_patch.stop()
        db_mod.DATABASE_PATH = self._orig_path
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def _seed_open_invoice(self) -> int:
        stamp = datetime.now().strftime("%Y%m%d%H%M%S")
        resp = self.client.post(
            "/point-of-sale/api/invoices",
            json={
                "order_no": f"TEST-KOT-{stamp}",
                "table_label": "Table 5",
                "order_type": "dine_in",
                "outlet": "restaurant",
                "customer_name": "Walk-in Guest",
                "lines": [
                    {
                        "name": "Paneer Tikka",
                        "qty": 2,
                        "rate": 250,
                        "sent_qty": 0,
                        "variant": "",
                        "notes": "Less spicy",
                    }
                ],
            },
        )
        self.assertEqual(resp.status_code, 200, resp.get_json())
        return int(resp.get_json()["invoice"]["id"])

    def test_create_job_routes_to_agent_with_kitchen_role(self):
        conn = db_mod.get_db()
        try:
            job = create_print_job(
                conn,
                {
                    "jobId": "job-kot-1",
                    "documentType": "kot",
                    "documentId": self.invoice_id,
                    "locationId": "restaurant",
                    "printerRole": "kitchen1",
                    "items": [
                        {"name": "Paneer Tikka", "qty": 2, "variant": "", "notes": "Less spicy"}
                    ],
                },
                user_id=self.admin_id,
            )
            self.assertEqual(job.get("printerRole"), "kitchen1")
            self.assertEqual(job.get("agentId"), self.agent_id)
            self.assertEqual(job.get("printerId"), "Kitchen Printer")
            self.assertIn(job.get("status"), ("QUEUED", "SENT_TO_AGENT"))
        finally:
            conn.close()

    def test_duplicate_job_id_is_idempotent(self):
        conn = db_mod.get_db()
        try:
            payload = {
                "jobId": "dup-job-1",
                "idempotencyKey": "dup-key-1",
                "documentType": "kot",
                "documentId": self.invoice_id,
                "locationId": "restaurant",
                "items": [{"name": "Paneer Tikka", "qty": 2}],
            }
            first = create_print_job(conn, payload, user_id=self.admin_id)
            second = create_print_job(conn, payload, user_id=self.admin_id)
            self.assertTrue(second.get("duplicate"))
            self.assertEqual(first.get("jobId"), second.get("jobId"))
            count = conn.execute("SELECT COUNT(*) AS c FROM print_jobs").fetchone()["c"]
            self.assertEqual(count, 1)
        finally:
            conn.close()

    def test_send_kot_api_enqueues_print_job(self):
        resp = self.client.post(f"/point-of-sale/api/invoices/{self.invoice_id}/send-kot")
        self.assertEqual(resp.status_code, 200, resp.get_json())
        conn = db_mod.get_db()
        try:
            rows = conn.execute(
                "SELECT job_id, document_type, status FROM print_jobs"
            ).fetchall()
            self.assertGreaterEqual(len(rows), 1)
            self.assertEqual(rows[0]["document_type"], "kot")
        finally:
            conn.close()

    def test_bar_role_routes_to_bar_printer(self):
        conn = db_mod.get_db()
        try:
            conn.execute(
                "UPDATE print_agents SET last_seen_at = '2000-01-01 00:00:00' WHERE agent_id = ?",
                (self.agent_id,),
            )
            reg = register_print_agent(
                conn,
                {
                    "agentId": "agent-bar-002",
                    "businessId": "hotel-bell-elite",
                    "deviceName": "BAR-PC",
                },
            )
            conn.execute(
                """
                UPDATE print_agents
                SET mapped_printers_json = ?, last_seen_at = ?
                WHERE agent_id = ?
                """,
                (
                    json.dumps({"bar": "Bar Only Printer"}),
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    reg["agentId"],
                ),
            )
            conn.commit()
            job = create_print_job(
                conn,
                {
                    "jobId": "job-bar-1",
                    "documentType": "kot",
                    "documentId": self.invoice_id,
                    "locationId": "bar",
                    "printerRole": "bar",
                    "items": [{"name": "Whiskey", "qty": 1}],
                },
                user_id=self.admin_id,
            )
            self.assertEqual(job.get("agentId"), reg["agentId"])
            self.assertEqual(job.get("printerId"), "Bar Only Printer")
        finally:
            conn.close()

    def test_offline_agent_keeps_job_queued(self):
        conn = db_mod.get_db()
        try:
            conn.execute(
                "UPDATE print_agents SET last_seen_at = '2000-01-01 00:00:00' WHERE agent_id = ?",
                (self.agent_id,),
            )
            conn.commit()
            job = create_print_job(
                conn,
                {
                    "jobId": "offline-job-1",
                    "documentType": "kot",
                    "documentId": self.invoice_id,
                    "locationId": "restaurant",
                    "items": [{"name": "Paneer Tikka", "qty": 2}],
                },
                user_id=self.admin_id,
            )
            self.assertEqual(job.get("status"), "QUEUED")
            self.assertFalse(job.get("agentId"))
        finally:
            conn.close()

    def test_pending_jobs_list_for_agent(self):
        conn = db_mod.get_db()
        try:
            create_print_job(
                conn,
                {
                    "jobId": "pending-1",
                    "documentType": "kot",
                    "documentId": self.invoice_id,
                    "locationId": "restaurant",
                    "items": [{"name": "Paneer Tikka", "qty": 1}],
                },
                user_id=self.admin_id,
            )
            pending = conn.execute(
                "SELECT job_id FROM print_jobs WHERE agent_id = ? AND status IN ('QUEUED','SENT_TO_AGENT')",
                (self.agent_id,),
            ).fetchall()
            self.assertGreaterEqual(len(pending), 1)
        finally:
            conn.close()

    def test_recover_stale_sent_jobs(self):
        conn = db_mod.get_db()
        try:
            from print_job_service import ensure_print_job_schema

            ensure_print_job_schema(conn)
            stamp = (datetime.now() - timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
            conn.execute(
                """
                INSERT INTO print_jobs (
                    job_id, business_id, location_id, agent_id, printer_id, printer_role,
                    document_type, document_id, copies, status,
                    content_type, content_encoding, content,
                    idempotency_key, created_at, updated_at, sent_at
                ) VALUES (
                    'stale-1', 'hotel-bell-elite', 'restaurant', ?, 'Kitchen Printer', 'kitchen1',
                    'kot', ?, 1, 'SENT_TO_AGENT',
                    'text', 'utf8', 'test', 'stale-1', ?, ?, ?
                )
                """,
                (self.agent_id, self.invoice_id, stamp, stamp, stamp),
            )
            conn.commit()
            count = recover_stale_print_jobs(conn)
            self.assertGreaterEqual(count, 1)
            row = conn.execute(
                "SELECT status FROM print_jobs WHERE job_id = 'stale-1'"
            ).fetchone()
            self.assertIn(row["status"], ("QUEUED", "SENT_TO_AGENT"))
        finally:
            conn.close()

    def test_enqueue_kot_jobs_for_invoice_groups_outlets(self):
        conn = db_mod.get_db()
        try:
            invoice = db_mod.get_pos_invoice(conn, self.invoice_id)
            pending = [{"line": invoice["lines"][0], "delta_qty": 2}]
            jobs = enqueue_kot_jobs_for_invoice(conn, invoice, pending, user_id=self.admin_id)
            self.assertGreaterEqual(len(jobs), 1)
        finally:
            conn.close()

    def test_api_create_and_get_job(self):
        resp = self.client.post(
            "/api/print-jobs",
            json={
                "jobId": "api-job-1",
                "documentType": "kot",
                "documentId": self.invoice_id,
                "locationId": "restaurant",
                "items": [{"name": "Paneer Tikka", "qty": 2}],
            },
        )
        self.assertEqual(resp.status_code, 200, resp.get_json())
        body = resp.get_json()
        self.assertTrue(body.get("ok"))
        job_id = (body.get("job") or {}).get("jobId")
        got = self.client.get(f"/api/print-jobs/{job_id}")
        self.assertEqual(got.status_code, 200)
        self.assertEqual((got.get_json().get("job") or {}).get("jobId"), job_id)

    @mock.patch("print_agent_ws.push_print_job_to_agent", return_value=True)
    def test_ws_push_marks_sent_to_agent(self, _push):
        conn = db_mod.get_db()
        try:
            job = create_print_job(
                conn,
                {
                    "jobId": "ws-job-1",
                    "documentType": "kot",
                    "documentId": self.invoice_id,
                    "locationId": "restaurant",
                    "items": [{"name": "Paneer Tikka", "qty": 1}],
                },
                user_id=self.admin_id,
            )
            refreshed = get_print_job(conn, job["jobId"])
            self.assertEqual(refreshed.get("status"), "SENT_TO_AGENT")
        finally:
            conn.close()

    def test_status_transitions(self):
        conn = db_mod.get_db()
        try:
            create_print_job(
                conn,
                {
                    "jobId": "status-job-1",
                    "documentType": "kot",
                    "documentId": self.invoice_id,
                    "locationId": "restaurant",
                    "items": [{"name": "Paneer Tikka", "qty": 1}],
                },
                user_id=self.admin_id,
            )
            update_job_status(conn, "status-job-1", "SENT_TO_AGENT", agent_id=self.agent_id)
            update_job_status(conn, "status-job-1", "PRINTING", agent_id=self.agent_id)
            update_job_status(conn, "status-job-1", "PRINTED", agent_id=self.agent_id)
            job = get_print_job(conn, "status-job-1")
            self.assertEqual(job.get("status"), "PRINTED")
            self.assertTrue(job.get("printedAt"))
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
