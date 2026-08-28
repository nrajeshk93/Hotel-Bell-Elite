"""Public mobile APK / version manifest (no login)."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import db as db_mod


def _load_publish_mod():
    path = Path(__file__).resolve().parents[1] / "scripts" / "publish_mobile_apk.py"
    spec = importlib.util.spec_from_file_location("publish_mobile_apk", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class MobileOtaRouteTests(unittest.TestCase):
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
        self._prev_testing = self.app.config.get("TESTING")
        self.app.config["TESTING"] = False
        self.client = self.app.test_client()

    def tearDown(self):
        self.app.config["TESTING"] = self._prev_testing
        db_mod.DATABASE_PATH = self._orig_path
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def test_endpoints_are_listed_public(self):
        from workspace_access import _PUBLIC_ENDPOINTS

        self.assertIn("mobile_ota_manifest", _PUBLIC_ENDPOINTS)
        self.assertIn("mobile_ota_apk", _PUBLIC_ENDPOINTS)

    def test_manifest_is_public_json(self):
        resp = self.client.get("/api/mobile/version", follow_redirects=False)
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        self.assertFalse(resp.headers.get("Location"))
        cache = (resp.headers.get("Cache-Control") or "").lower()
        self.assertTrue("no-store" in cache or "no-cache" in cache)
        self.assertEqual((resp.headers.get("Surrogate-Control") or "").lower(), "no-store")
        data = resp.get_json()
        self.assertEqual(data.get("version"), "0.1.0")
        self.assertEqual(data.get("versionCode"), 1)
        self.assertIn("apk_url", data)
        self.assertIn("sha256", data)
        self.assertIn("apk_available", data)
        self.assertIn("/api/mobile/hbemobile.apk", data.get("apk_url") or "")

    def test_apk_missing_is_public_404(self):
        import mobile_ota

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(mobile_ota, "MOBILE_DIR", Path(tmp)):
                resp = self.client.get("/api/mobile/hbemobile.apk", follow_redirects=False)
        self.assertEqual(resp.status_code, 404)
        self.assertFalse(resp.headers.get("Location"))
        body = resp.get_json() or {}
        self.assertFalse(body.get("ok", True))

    def test_apk_present_is_public_200(self):
        import mobile_ota

        payload = b"PK\x03\x04fake-apk-bytes"
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            apk = directory / "hbemobile.apk"
            apk.write_bytes(payload)
            with mock.patch.object(mobile_ota, "MOBILE_DIR", directory):
                resp = self.client.get("/api/mobile/hbemobile.apk", follow_redirects=False)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.headers.get("Location"))
        self.assertEqual(resp.data, payload)
        self.assertIn(
            "android.package-archive",
            (resp.headers.get("Content-Type") or "").lower(),
        )

    def test_print_agent_updates_stub_untouched(self):
        resp = self.client.get("/api/print-agent/updates/latest?current=1.0.0")
        # Existing stub is not a public OTA route; login redirect is OK.
        self.assertIn(resp.status_code, (200, 302, 303))


class PublishMobileApkTests(unittest.TestCase):
    def test_parse_repo_buildozer_spec(self):
        mod = _load_publish_mod()
        spec = Path(__file__).resolve().parents[1] / "mobile_kivy" / "buildozer.spec"
        version, code = mod.parse_buildozer_spec(spec)
        self.assertEqual(version, "0.1.0")
        self.assertEqual(code, 1)

    def test_copies_apk_and_writes_manifest(self):
        mod = _load_publish_mod()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            apk = tmp_path / "built.apk"
            raw = b"hello-hbe-apk"
            apk.write_bytes(raw)
            dest = tmp_path / "out"
            rc = mod.main(["--apk", str(apk), "--dest-dir", str(dest)])
            self.assertEqual(rc, 0)
            copied = dest / "hbemobile.apk"
            self.assertEqual(copied.read_bytes(), raw)
            manifest = json.loads((dest / "version.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["version"], "0.1.0")
            self.assertEqual(manifest["versionCode"], 1)
            self.assertEqual(manifest["apk_url"], "/api/mobile/hbemobile.apk")
            self.assertEqual(manifest["sha256"], hashlib.sha256(raw).hexdigest())
            self.assertFalse(manifest["force"])


if __name__ == "__main__":
    unittest.main()
