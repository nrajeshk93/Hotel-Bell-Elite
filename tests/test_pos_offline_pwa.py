"""App shell + POS offline PWA smoke checks."""

import os
import re
import tempfile
import unittest

import db as db_mod


class AppShellPwaTests(unittest.TestCase):
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

    def test_service_worker_is_public_app_shell(self):
        resp = self.client.get("/sw.js")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("Service-Worker-Allowed"), "/")
        body = resp.get_data(as_text=True)
        resp.close()
        self.assertRegex(body, r"CACHE_VERSION\s*=\s*'hbe-app-v\d+'")
        self.assertIn("GET_CACHE_VERSION", body)
        self.assertIn("isWorkspaceHtml", body)
        self.assertIn("partial", body)
        self.assertIn("networkFirstStatic", body)
        self.assertIn("networkOnlyFloor", body)
        self.assertIn("Occupancy may be slightly stale offline", body)
        self.assertIn("networkFirstHtml", body)
        self.assertIn("FLOOR_API_PATHS", body)
        self.assertIn("/home", body)
        self.assertIn("de_workspace_transitions.js", body)
        self.assertIn("de_workspace_shell.css", body)
        self.assertIn("/bar-point-of-sale/invoice", body)
        self.assertIn("offline_login.html", body)
        self.assertIn("offline_auth.js", body)
        self.assertIn("'/login'", body)
        self.assertIn("loginNav", body)
        self.assertIn("loginPostNav", body)
        self.assertIn("Intercepting POST navigate to login", body)
        self.assertIn("logoutPassthrough", body)
        self.assertIn("Do NOT intercept /logout", body)
        self.assertIn("login_premium.css", body)
        self.assertIn("matchLoginShellOffline", body)
        self.assertIn("OFFLINE_LOGIN_URL", body)
        self.assertIn("syntheticOfflineLoginResponse", body)
        self.assertIn("responseLooksLikeModernOfflineLogin", body)
        self.assertIn("hbe_home_premium.css", body)
        self.assertIn("matchStaticCache", body)
        self.assertIn("CRITICAL_STATIC_ALIASES", body)
        self.assertIn("offline_login.html?v=10", body)
        self.assertIn("hbe_logo_sm.png", body)
        self.assertIn("isLoginShellPath", body)
        self.assertIn("offlineNavigateFallback", body)
        # Bare /home must not be filled from partial=main offline snapshots.
        self.assertIn("Never overwrite the bare navigate URL", body)
        self.assertIn("Full navigations must not use a partial=main", body)
        self.assertNotIn("client.navigate", body)
        self.assertNotIn(
            "'/point-of-sale/api/floor',\n  '/point-of-sale/api/menu/items'",
            body,
        )
        self.assertIn("/point-of-sale/api/menu/items", body)
        self.assertIn("/point-of-sale/api/floor", body)

    def test_offline_login_shell_is_public(self):
        resp = self.client.get("/static/offline_login.html")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        resp.close()
        self.assertIn("login-panel", html)
        self.assertIn("login-shell", html)
        self.assertIn("offline_auth.js", html)
        self.assertIn("HbeOfflineAuth", html)
        self.assertIn("You can still sign in with your password on this device.", html)
        self.assertIn('action="/login"', html)
        self.assertIn("de_pwa.js", html)
        self.assertIn("offline_login.html?v=10", html)
        self.assertNotIn("Reconnect to sign in.", html)

    def test_get_login_serves_sign_in_page(self):
        self.client.get("/logout", follow_redirects=False)
        resp = self.client.get("/login")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        resp.close()
        self.assertIn("login-panel", html)
        self.assertIn("offline_auth.js", html)

    def test_sign_in_page_registers_pwa_and_offline_guard(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        resp.close()
        self.assertIn("login-panel", html)
        self.assertIn("de_pwa.js", html)
        self.assertIn("offline_auth.js", html)
        self.assertIn("login-offline-notice", html)
        self.assertIn("HbeOfflineAuth", html)
        self.assertIn("You can still sign in with your password on this device.", html)
        self.assertNotIn("Reconnect to sign in.", html)

    def test_offline_auth_module_exposes_local_unlock(self):
        resp = self.client.get("/static/offline_auth.js?v=11")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_data(as_text=True)
        resp.close()
        self.assertIn("HbeOfflineAuth", body)
        self.assertIn("saveCredentials", body)
        self.assertIn("verifyCredentials", body)
        self.assertIn("bindLoginForm", body)
        self.assertIn("PBKDF2", body)
        self.assertIn("clearAllVerifiers", body)
        self.assertIn("putCachedHtml", body)
        self.assertIn("findCachedAppShell", body)
        self.assertIn("offline logout", body)
        self.assertIn("/home", body)

    def test_de_pwa_prunes_app_and_legacy_pos_caches(self):
        resp = self.client.get("/static/de_pwa.js")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_data(as_text=True)
        resp.close()
        self.assertNotIn("key !== 'hbe-pos-v40'", body)
        self.assertNotRegex(body, r"key !== 'hbe-pos-v\d+'")
        self.assertIn("GET_CACHE_VERSION", body)
        self.assertIn("hbe-app-", body)
        self.assertIn("pruneStaleAppCaches", body)
        self.assertIn("key === keepName", body)

    def test_pos_offline_has_seven_day_prune(self):
        resp = self.client.get("/static/pos_offline.js")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_data(as_text=True)
        resp.close()
        self.assertIn("MAX_OFFLINE_AGE_MS", body)
        self.assertIn("pruneExpiredOfflineData", body)
        self.assertIn("7 * 24 * 60 * 60 * 1000", body)

    def test_soft_nav_has_offline_fallback(self):
        resp = self.client.get("/static/de_workspace_transitions.js")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_data(as_text=True)
        resp.close()
        self.assertIn("notifyShellOffline", body)
        self.assertIn("de-shell-offline-chip", body)
        self.assertIn("isBrowserOffline", body)

    def test_manifest_starts_at_home(self):
        resp = self.client.get("/static/manifest.webmanifest")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        resp.close()
        self.assertEqual(data.get("start_url"), "/home")
        self.assertEqual(data.get("display"), "standalone")
        self.assertIn("Hotel Bell Elite", data.get("name") or "")

    def _assert_invoice_offline_assets(self, html):
        self.assertIn("pos_offline.js", html)
        self.assertIn("pos-inv-offline-banner", html)
        self.assertIn("manifest.webmanifest", html)
        self.assertIn("de_pwa.js", html)
        self.assertRegex(
            html,
            re.compile(r"Install the app|HTTPS|open POS once online", re.I),
        )

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
        self._assert_invoice_offline_assets(html)

    def test_bar_invoice_page_includes_offline_assets_when_logged_in(self):
        login = self.client.post(
            "/login",
            data={"username": "admin", "password": "admin"},
            follow_redirects=False,
        )
        self.assertIn(login.status_code, (302, 303))
        page = self.client.get("/bar-point-of-sale/invoice")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self._assert_invoice_offline_assets(html)
        self.assertIn('data-pos-outlet="bar"', html)

    def test_pos_invoice_offline_occupancy_guard_allows_own_session(self):
        resp = self.client.get("/static/pos_invoice.js")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_data(as_text=True)
        resp.close()
        self.assertIn("sessionOwnsSelectedTable", body)
        self.assertIn("Offline saves mark the table occupied locally", body)
        self.assertNotIn("!state.invoiceId && tableBlocksNewBill", body)

        login = self.client.post(
            "/login",
            data={"username": "admin", "password": "admin"},
            follow_redirects=False,
        )
        self.assertIn(login.status_code, (302, 303))
        page = self.client.get("/settings")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn("sd-pwa-hint", html)
        self.assertRegex(html, re.compile(r"HTTPS|Install this app", re.I))


if __name__ == "__main__":
    unittest.main()
