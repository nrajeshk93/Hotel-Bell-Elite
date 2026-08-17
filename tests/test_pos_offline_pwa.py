"""POS offline PWA smoke checks — service worker + invoice page assets."""

import os
import tempfile
import unittest

import db as db_mod


class PosOfflinePwaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db_path = self.tmp.name
        self._orig_path = db_mod.DATABASE_PATH
        db_mod.DATABASE_PATH = self.db_path
        db_mod.init_db()

        import app as app_mod

        self.app = app_mod.app
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def tearDown(self):
        db_mod.DATABASE_PATH = self._orig_path
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def test_service_worker_is_public(self):
        resp = self.client.get("/sw.js")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("Service-Worker-Allowed"), "/")
        body = resp.get_data(as_text=True)
        resp.close()
        self.assertIn("hbe-pos-v40", body)
        self.assertIn("networkFirstStatic", body)
        self.assertIn("isPosCachedStatic", body)
        self.assertIn("networkOnlyFloor", body)
        self.assertIn("networkFirstHtml", body)
        self.assertIn("FLOOR_API_PATHS", body)
        self.assertNotIn("client.navigate", body)
        self.assertNotIn(
            "'/point-of-sale/api/floor',\n  '/point-of-sale/api/menu/items'",
            body,
        )
        self.assertIn("/point-of-sale/api/menu/items", body)

    def test_manifest_starts_at_invoice(self):
        resp = self.client.get("/static/manifest.webmanifest")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        resp.close()
        self.assertEqual(data.get("start_url"), "/point-of-sale/invoice")
        self.assertEqual(data.get("display"), "standalone")

    def test_invoice_page_includes_offline_assets_when_logged_in(self):
        login = self.client.post(
            "/login",
            data={"username": "admin", "password": "admin"},
            follow_redirects=False,
        )
        self.assertIn(login.status_code, (302, 303))
        page = self.client.get("/point-of-sale/invoice")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn("pos_offline.js", html)
        self.assertIn("pos-inv-offline-banner", html)
        self.assertIn("manifest.webmanifest", html)
        self.assertIn("de_pwa.js", html)


if __name__ == "__main__":
    unittest.main()
