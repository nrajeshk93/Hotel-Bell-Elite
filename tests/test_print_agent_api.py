"""Print Agent SaaS registration / heartbeat / updates."""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

import db as db_mod


class PrintAgentApiTests(unittest.TestCase):
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
        self._get_user_patch = mock.patch.object(app_mod, "get_current_user", return_value=self.user)
        self._get_user_patch.start()

    def tearDown(self):
        self._get_user_patch.stop()
        db_mod.DATABASE_PATH = self._orig_path
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def test_register_and_heartbeat(self):
        reg = self.client.post(
            "/api/print-agent/register",
            json={
                "agentId": "11111111-2222-3333-4444-555555555555",
                "businessId": "biz-demo",
                "deviceName": "FRONT-DESK-PC",
                "windowsUsername": "frontdesk",
                "installedPrinters": ["Epson TM-T82", "TVS RP3200"],
                "agentVersion": "1.0.0",
            },
        )
        self.assertEqual(reg.status_code, 200, reg.get_data(as_text=True))
        body = reg.get_json()
        self.assertTrue(body.get("ok"))
        self.assertTrue(body.get("token"))
        self.assertTrue(body.get("apiKey"))
        stored = db_mod.get_db()
        try:
            row = stored.execute(
                "SELECT api_key, api_key_hash FROM print_agents WHERE agent_id = ?",
                ("11111111-2222-3333-4444-555555555555",),
            ).fetchone()
        finally:
            stored.close()
        self.assertTrue((row["api_key"] or "").startswith("enc1$"))
        self.assertNotEqual(row["api_key"], body.get("apiKey"))
        self.assertTrue(row["api_key_hash"])
        self.assertIn("http://127.0.0.1:8002", body.get("allowedOrigins") or [])
        self.assertIn("https://belleliteaccounts.com", body.get("allowedOrigins") or [])

        hb = self.client.post(
            "/api/print-agent/heartbeat",
            headers={"Authorization": f"Bearer {body['token']}"},
            json={
                "agentId": "11111111-2222-3333-4444-555555555555",
                "businessId": "biz-demo",
                "version": "1.0.0",
                "printers": {"billing": "Epson TM-T82"},
                "installedPrinters": ["Epson TM-T82"],
            },
        )
        self.assertEqual(hb.status_code, 200, hb.get_data(as_text=True))
        self.assertTrue(hb.get_json().get("ok"))
        self.assertIn("https://belleliteaccounts.com", hb.get_json().get("allowedOrigins") or [])

        denied = self.client.post(
            "/api/print-agent/heartbeat",
            headers={"Authorization": "Bearer wrong"},
            json={"agentId": "11111111-2222-3333-4444-555555555555"},
        )
        self.assertEqual(denied.status_code, 401)

        pair = self.client.get(
            "/api/print-agent/browser-pair"
            "?businessId=biz-demo&agentId=11111111-2222-3333-4444-555555555555"
        )
        self.assertEqual(pair.status_code, 200, pair.get_data(as_text=True))
        pair_body = pair.get_json()
        self.assertTrue(pair_body.get("ok"))
        self.assertEqual(pair_body.get("apiKey"), body.get("apiKey"))
        self.assertEqual(pair_body.get("agentId"), "11111111-2222-3333-4444-555555555555")
        self.assertEqual(pair_body.get("localBaseUrl"), "http://127.0.0.1:4567")
        self.assertEqual(
            (pair_body.get("mappedPrinters") or {}).get("billing"),
            "Epson TM-T82",
        )

        miss = self.client.get(
            "/api/print-agent/browser-pair?agentId=00000000-0000-0000-0000-000000000000"
        )
        self.assertEqual(miss.status_code, 404)
        self.assertFalse((miss.get_json() or {}).get("ok"))

    def test_updates_and_config(self):
        upd = self.client.get("/api/print-agent/updates/latest?current=1.0.0")
        self.assertEqual(upd.status_code, 200)
        self.assertIn("latestVersion", upd.get_json())

        cfg = self.client.get("/api/print-agent/config")
        self.assertEqual(cfg.status_code, 200)
        data = cfg.get_json()
        self.assertTrue(data.get("ok"))
        self.assertIn("billing", data.get("roles") or [])
        self.assertIn("kitchen1", data.get("roles") or [])
        self.assertIn("bar", data.get("roles") or [])
        self.assertIn("hotel_folio", data.get("roles") or [])
        self.assertIn("hotel_invoice", data.get("roles") or [])
        self.assertIn("https://belleliteaccounts.com", data.get("allowedOrigins") or [])
        self.assertEqual(data.get("cloudOrigin"), "https://belleliteaccounts.com")
        self.assertIn("serverPrintQueue", data)
        self.assertIn("printQueuePrimary", data)

    def test_register_rejected_without_session_or_pairing(self):
        self._get_user_patch.stop()
        try:
            with self.client.session_transaction() as sess:
                sess.clear()
            reg = self.client.post(
                "/api/print-agent/register",
                json={
                    "agentId": "99999999-8888-7777-6666-555555555555",
                    "businessId": "biz-demo",
                },
            )
            self.assertEqual(reg.status_code, 401)
        finally:
            self._get_user_patch.start()

    def test_pairing_code_allows_new_register_and_heartbeat_without_session(self):
        minted = self.client.post("/hotel/api/print-agent/pairing-code")
        self.assertEqual(minted.status_code, 200, minted.get_data(as_text=True))
        minted_body = minted.get_json() or {}
        code = minted_body.get("pairingCode")
        self.assertTrue(code)
        self.assertTrue(minted_body.get("expiresAt"))
        self.assertGreaterEqual(int(minted_body.get("ttlSeconds") or 0), 60)
        self._get_user_patch.stop()
        try:
            with self.client.session_transaction() as sess:
                sess.clear()
            cfg = self.client.get("/api/print-agent/config")
            self.assertEqual(cfg.status_code, 401)
            reg = self.client.post(
                "/api/print-agent/register",
                json={
                    "agentId": "aaaaaaaa-bbbb-cccc-dddd-ffffffffffff",
                    "businessId": "biz-demo",
                    "pairingCode": code,
                    "deviceName": "NEW-PC",
                },
            )
            self.assertEqual(reg.status_code, 200, reg.get_data(as_text=True))
            body = reg.get_json() or {}
            self.assertTrue(body.get("ok"))
            hb = self.client.post(
                "/api/print-agent/heartbeat",
                headers={"Authorization": "Bearer " + body["token"]},
                json={"agentId": "aaaaaaaa-bbbb-cccc-dddd-ffffffffffff"},
            )
            self.assertEqual(hb.status_code, 200, hb.get_data(as_text=True))
            self.assertTrue((hb.get_json() or {}).get("ok"))
            reused = self.client.post(
                "/api/print-agent/register",
                json={
                    "agentId": "bbbbbbbb-cccc-dddd-eeee-ffffffffffff",
                    "businessId": "biz-demo",
                    "pairingCode": code,
                },
            )
            self.assertEqual(reused.status_code, 401)
        finally:
            self._get_user_patch.start()



if __name__ == "__main__":
    unittest.main()
