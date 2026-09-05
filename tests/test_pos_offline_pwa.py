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
        cc = (resp.headers.get("Cache-Control") or "").lower()
        self.assertIn("no-store", cc)
        self.assertEqual(resp.headers.get("CDN-Cache-Control"), "no-store")
        self.assertEqual(resp.headers.get("Surrogate-Control"), "no-store")
        body = resp.get_data(as_text=True)
        resp.close()
        self.assertRegex(body, r"CACHE_VERSION\s*=\s*'hbe-app-[a-f0-9]{8,}'")
        self.assertIn("GET_CACHE_VERSION", body)
        self.assertIn("isWorkspaceHtml", body)
        self.assertIn("partial", body)
        self.assertIn("networkFirstStatic", body)
        self.assertIn("Only POS + precache shells", body)
        self.assertNotIn("Runtime network-first for page CSS/JS", body)
        self.assertIn("networkOnlyFloor", body)
        self.assertIn("PURGE_DATA_CACHES", body)
        self.assertIn("NetworkOnly", body)
        self.assertIn("networkFirstHtml", body)
        self.assertIn("shouldCacheHtmlPath", body)
        self.assertIn('"/static/de_pwa.js":', body)
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
        self.assertIn("Form POST to Sign In is mode=navigate", body)
        self.assertIn("Do NOT intercept /logout", body)
        self.assertIn("login_premium.css", body)
        self.assertIn("matchLoginShellOffline", body)
        self.assertIn("OFFLINE_LOGIN_URL", body)
        self.assertIn("syntheticOfflineLoginResponse", body)
        self.assertIn("responseLooksLikeModernOfflineLogin", body)
        self.assertIn("hbe_home_premium.css", body)
        self.assertIn("matchStaticCache", body)
        self.assertIn("CRITICAL_STATIC_ALIASES", body)
        self.assertIn("offline_login.html?v=", body)
        self.assertNotIn("__HBE_CACHE_VERSION__", body)
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
        # Business/API JSON must not be written into Cache Storage.
        nf = body[body.find("function networkFirst") : body.find("function putHtmlCache")]
        self.assertNotIn("cache.put", nf)
        floor_fn = body[
            body.find("function networkOnlyFloor") : body.find("function networkFirst")
        ]
        self.assertNotIn("caches.match", floor_fn)
        self.assertNotIn("cache.put", floor_fn)

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
        self.assertIn("offline_login.html?v=", html)
        self.assertNotIn("Reconnect to sign in.", html)

    def test_get_login_serves_sign_in_page(self):
        self.client.post("/logout", follow_redirects=False)
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
        resp = self.client.get("/static/offline_auth.js?v=12")
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
        self.assertIn("bindLogoutClearing", body)
        self.assertIn("/home", body)

    def test_de_pwa_prunes_app_and_legacy_pos_caches(self):
        resp = self.client.get("/static/de_pwa.js")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("CDN-Cache-Control"), "no-store")
        self.assertEqual(resp.headers.get("Surrogate-Control"), "no-store")
        cc = (resp.headers.get("Cache-Control") or "").lower()
        self.assertIn("no-store", cc)
        body = resp.get_data(as_text=True)
        resp.close()
        self.assertNotIn("key !== 'hbe-pos-v40'", body)
        self.assertNotRegex(body, r"key !== 'hbe-pos-v\d+'")
        self.assertIn("GET_CACHE_VERSION", body)
        self.assertIn("hbe-app-", body)
        self.assertIn("pruneStaleAppCaches", body)
        self.assertIn("key === keepName", body)
        self.assertIn("updateViaCache", body)
        self.assertIn("hbe-build.json", body)
        self.assertIn("bindReloadOnUpdate", body)
        self.assertIn("setInterval(onVisible, 15000)", body)
        self.assertNotIn("navigator.onLine === false", body)
        self.assertIn("PURGE_DATA_CACHES", body)
        self.assertIn("onReconnectFresh", body)
        self.assertIn("hbe:online-sync", body)
        self.assertIn("bindOnlineFreshSync", body)
        self.assertIn("HbeOfflineSync", body)


    def test_de_pwa_does_not_hard_reload_from_build_json_mismatch(self):
        """Build digest flips while editing; reload-from-mismatch caused refresh loops."""
        resp = self.client.get("/static/de_pwa.js")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_data(as_text=True)
        self.assertIn("hbe-build.json", body)
        self.assertIn("Intentionally no location.reload()", body)
        # Still reloads once after a new SW claims — but not on localhost/LAN.
        self.assertIn("Localhost / LAN", body)
        self.assertIn("controllerchange", body)

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
        self.assertNotIn("sd-pwa-hint", html)
        self.assertNotRegex(html, re.compile(r"Install this app over HTTPS", re.I))

    def test_html_static_urls_use_content_hash(self):
        login = self.client.post(
            "/login",
            data={"username": "admin", "password": "admin"},
            follow_redirects=False,
        )
        self.assertIn(login.status_code, (302, 303))
        page = self.client.get("/point-of-sale/invoice")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        page.close()
        import asset_digest
        asset_digest.reset_digest()
        expected = asset_digest.hashed_static_url("pos_invoice.js")
        self.assertIn(expected, html)
        self.assertNotIn("pos_invoice.js?v=156", html)
        self.assertNotIn("pos_invoice.js?v=157", html)

    def test_hbe_build_json_matches_service_worker(self):
        sw = self.client.get("/sw.js")
        body = sw.get_data(as_text=True)
        sw.close()
        build = self.client.get("/hbe-build.json")
        self.assertEqual(build.status_code, 200)
        cc = (build.headers.get("Cache-Control") or "").lower()
        self.assertIn("no-store", cc)
        data = build.get_json()
        build.close()
        version = data.get("cacheVersion") or ""
        self.assertTrue(version.startswith("hbe-app-"))
        self.assertIn("CACHE_VERSION = '%s'" % version, body)
        self.assertIn("/static/pos_offline.js?v=", body)
        precache = body.split("var PRECACHE")[1].split("var API_CACHE")[0]
        self.assertNotIn("'/home'", precache)
        self.assertNotIn("/point-of-sale/invoice", precache)


class OfflineSyncOrchestratorTests(unittest.TestCase):
    def test_orchestrator_module_is_public(self):
        import app as app_mod

        client = app_mod.app.test_client()
        resp = client.get("/static/hbe_offline_sync.js")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_data(as_text=True)
        resp.close()
        self.assertIn("HbeOfflineSync", body)
        self.assertIn("runReconnect", body)
        self.assertIn("PURGE_DATA_CACHES", body)
        self.assertIn("refreshMenuCatalog", body)
        self.assertIn("refreshFloorFromServer", body)
        self.assertIn("hbe:online-sync", body)
        self.assertIn("PERIOD_MS", body)

    def test_pos_pages_include_orchestrator(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for rel in (
            "templates/point_of_sale_invoice.html",
            "templates/point_of_sale.html",
        ):
            with open(os.path.join(root, rel), encoding="utf-8") as fh:
                html = fh.read()
            self.assertIn("hbe_offline_sync.js", html, rel)
        with open(os.path.join(root, "asset_digest.py"), encoding="utf-8") as fh:
            digest = fh.read()
        self.assertIn('"hbe_offline_sync.js"', digest)

    def test_offline_auth_only_caches_shell_paths(self):
        path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "static", "offline_auth.js"
        )
        with open(path, encoding="utf-8") as fh:
            js = fh.read()
        self.assertIn("Only login/home shells", js)
        self.assertIn("never stash reports", js)



class AssetDigestFreshnessTests(unittest.TestCase):
    def tearDown(self):
        import asset_digest

        asset_digest.reset_digest()

    def test_digest_rebuilds_when_static_file_changes(self):
        import shutil
        import tempfile

        import asset_digest

        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        probe = os.path.join(root, "probe.css")
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write("body{color:red}")
        asset_digest.reset_digest()
        first = asset_digest.get_digest(root)
        hash_a = first["hashes"]["probe.css"]
        version_a = first["version"]
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write("body{color:blue}")
        second = asset_digest.get_digest(root)
        self.assertNotEqual(hash_a, second["hashes"]["probe.css"])
        self.assertNotEqual(version_a, second["version"])

    def test_current_content_hash_is_immutable_stale_hash_is_not(self):
        import asset_digest
        import app as app_mod

        asset_digest.reset_digest()
        live = asset_digest.current_static_hash("sales_report.css", app_mod.app.static_folder)
        self.assertTrue(live)

        client = app_mod.app.test_client()
        fresh = client.get("/static/sales_report.css?v=%s" % live)
        self.assertEqual(fresh.status_code, 200)
        cc = (fresh.headers.get("Cache-Control") or "").lower()
        self.assertIn("no-store", cc)
        self.assertEqual(fresh.headers.get("CDN-Cache-Control"), "no-store")
        fresh.close()

        stale = client.get("/static/sales_report.css?v=stalehash")
        self.assertEqual(stale.status_code, 200)
        stale_cc = (stale.headers.get("Cache-Control") or "").lower()
        self.assertIn("no-store", stale_cc)
        self.assertEqual(stale.headers.get("CDN-Cache-Control"), "no-store")
        stale.close()

    def test_js_warmup_urls_are_rewritten_to_live_hash(self):
        import asset_digest
        import app as app_mod

        asset_digest.reset_digest()
        live = asset_digest.hashed_static_url(
            "sales_report.css", app_mod.app.static_folder
        )
        client = app_mod.app.test_client()
        resp = client.get("/static/de_workspace_transitions.js")
        body = resp.get_data(as_text=True)
        resp.close()
        self.assertNotIn("/static/sales_report.css?v=19", body)
        self.assertNotIn("sales_report.css?", body)
        self.assertNotRegex(body, r"/static/[\w.-]+\.css\?v=\d+")

    def test_python_change_busts_cache_version(self):
        import asset_digest

        project = os.path.dirname(os.path.abspath(asset_digest.__file__))
        probe = os.path.join(project, "_hbe_cache_probe.py")
        asset_digest.reset_digest()
        before = asset_digest.cache_version(os.path.join(project, "static"))
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write("# probe\n")
        self.addCleanup(lambda: os.path.exists(probe) and os.unlink(probe))
        asset_digest.reset_digest()
        after = asset_digest.cache_version(os.path.join(project, "static"))
        self.assertNotEqual(before, after)

    def test_service_worker_static_fetch_bypasses_http_cache(self):
        import app as app_mod

        resp = app_mod.app.test_client().get("/sw.js")
        body = resp.get_data(as_text=True)
        resp.close()
        self.assertIn("cache: 'no-store'", body)
        self.assertNotIn("cache: 'no-cache'", body)


if __name__ == "__main__":
    unittest.main()
