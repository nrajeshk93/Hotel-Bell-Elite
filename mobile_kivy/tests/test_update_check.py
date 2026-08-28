"""OTA version compare + API URL switching (no Kivy window)."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from hbe_mobile import config
from hbe_mobile.update_check import (
    is_remote_newer,
    parse_manifest,
    resolve_apk_url,
    sha256_matches,
    version_tuple,
)
from hbe_mobile.updater import start_background_updater
from hbe_mobile.version import APP_VERSION, APP_VERSION_CODE


class VersionCompareTests(unittest.TestCase):
    def test_same_build_is_not_newer(self):
        self.assertFalse(
            is_remote_newer(
                local_version="0.1.0",
                local_version_code=1,
                remote_version="0.1.0",
                remote_version_code=1,
            )
        )

    def test_version_code_wins(self):
        self.assertTrue(
            is_remote_newer(
                local_version="0.9.0",
                local_version_code=1,
                remote_version="0.2.0",
                remote_version_code=2,
            )
        )
        self.assertFalse(
            is_remote_newer(
                local_version="0.2.0",
                local_version_code=3,
                remote_version="9.0.0",
                remote_version_code=2,
            )
        )

    def test_version_string_when_codes_equal(self):
        self.assertTrue(
            is_remote_newer(
                local_version="0.1.0",
                local_version_code=1,
                remote_version="0.1.1",
                remote_version_code=1,
            )
        )
        self.assertFalse(
            is_remote_newer(
                local_version="0.1.1",
                local_version_code=1,
                remote_version="0.1.0",
                remote_version_code=1,
            )
        )

    def test_missing_remote_code_uses_version_string(self):
        self.assertTrue(
            is_remote_newer(
                local_version="0.1.0",
                local_version_code=1,
                remote_version="0.2.0",
                remote_version_code=None,
            )
        )

    def test_version_tuple(self):
        self.assertEqual(version_tuple("0.1.0"), (0, 1, 0))
        self.assertEqual(version_tuple("1.2.10-debug"), (1, 2, 10))

    def test_parse_manifest_and_apk_url(self):
        parsed = parse_manifest(
            {
                "version": "0.2.0",
                "versionCode": "3",
                "apk_url": "/api/mobile/hbemobile.apk",
                "sha256": "ABC",
                "force": 0,
            }
        )
        self.assertEqual(parsed["versionCode"], 3)
        self.assertEqual(parsed["sha256"], "abc")
        self.assertEqual(
            resolve_apk_url("https://belleliteaccounts.com", parsed["apk_url"]),
            "https://belleliteaccounts.com/api/mobile/hbemobile.apk",
        )
        self.assertEqual(
            resolve_apk_url("http://10.0.2.2:8002", "https://cdn.example/app.apk"),
            "http://10.0.2.2:8002/api/mobile/hbemobile.apk",
        )
        self.assertEqual(
            resolve_apk_url(
                "https://belleliteaccounts.com",
                "https://evil.example/x.apk",
            ),
            "https://belleliteaccounts.com/api/mobile/hbemobile.apk",
        )
        self.assertEqual(
            resolve_apk_url(
                "https://belleliteaccounts.com",
                "//evil.example/x.apk",
            ),
            "https://belleliteaccounts.com/api/mobile/hbemobile.apk",
        )
        self.assertEqual(
            resolve_apk_url(
                "https://belleliteaccounts.com",
                "http://belleliteaccounts.com/api/mobile/hbemobile.apk",
            ),
            "https://belleliteaccounts.com/api/mobile/hbemobile.apk",
        )
        self.assertEqual(
            resolve_apk_url(
                "https://belleliteaccounts.com",
                "https://belleliteaccounts.com/api/mobile/hbemobile.apk",
            ),
            "https://belleliteaccounts.com/api/mobile/hbemobile.apk",
        )

    def test_sha256_matches(self):
        with tempfile.NamedTemporaryFile(delete=False) as handle:
            handle.write(b"abc")
            path = handle.name
        try:
            self.assertTrue(
                sha256_matches(
                    path, "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
                )
            )
            self.assertFalse(sha256_matches(path, ""))
            self.assertFalse(sha256_matches(path, "deadbeef"))
        finally:
            os.unlink(path)

    def test_client_version_matches_buildozer_baseline(self):
        self.assertEqual(APP_VERSION, "0.1.0")
        self.assertEqual(APP_VERSION_CODE, 1)


class ApiUrlSwitchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patch = mock.patch.dict(
            os.environ,
            {"HBE_MOBILE_CONFIG_DIR": self.tmp.name, "HBE_API_BASE_URL": ""},
            clear=False,
        )
        patch.start()
        self.addCleanup(patch.stop)

    def test_desktop_default(self):
        with mock.patch.object(config, "is_android", return_value=False):
            self.assertEqual(config.get_api_base_url(), "http://127.0.0.1:8002")

    def test_android_debug_default(self):
        with mock.patch.object(config, "is_android", return_value=True):
            with mock.patch.object(config, "is_android_debuggable", return_value=True):
                self.assertEqual(
                    config.get_api_base_url(), "https://belleliteaccounts.com"
                )

    def test_android_release_default(self):
        with mock.patch.object(config, "is_android", return_value=True):
            with mock.patch.object(config, "is_android_debuggable", return_value=False):
                self.assertEqual(
                    config.get_api_base_url(), "https://belleliteaccounts.com"
                )

    def test_pyjnius_failure_falls_back_to_production(self):
        with mock.patch.object(config, "is_android", return_value=True):
            with mock.patch.object(config, "is_android_debuggable", return_value=None):
                self.assertEqual(
                    config.get_api_base_url(), "https://belleliteaccounts.com"
                )

    def test_env_override(self):
        with mock.patch.dict(os.environ, {"HBE_API_BASE_URL": "http://192.168.1.20:8002"}):
            with mock.patch.object(config, "is_android", return_value=True):
                with mock.patch.object(config, "is_android_debuggable", return_value=True):
                    self.assertEqual(config.get_api_base_url(), "http://192.168.1.20:8002")

    def test_settings_json_wins_over_env_and_platform(self):
        settings = Path(self.tmp.name) / "settings.json"
        settings.write_text(
            json.dumps({"api_base_url": "https://belleliteaccounts.com"}),
            encoding="utf-8",
        )
        with mock.patch.dict(os.environ, {"HBE_API_BASE_URL": "http://10.0.2.2:8002"}):
            with mock.patch.object(config, "is_android", return_value=True):
                with mock.patch.object(config, "is_android_debuggable", return_value=True):
                    self.assertEqual(
                        config.get_api_base_url(), "https://belleliteaccounts.com"
                    )

    def test_desktop_updater_is_noop(self):
        with mock.patch.object(config, "is_android", return_value=False):
            start_background_updater()

    def test_request_update_check_desktop_noop(self):
        from hbe_mobile.updater import request_update_check

        with mock.patch.object(config, "is_android", return_value=False):
            request_update_check(delay_s=0)


if __name__ == "__main__":
    unittest.main()
