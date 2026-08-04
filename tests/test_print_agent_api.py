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


if __name__ == "__main__":
    unittest.main()
