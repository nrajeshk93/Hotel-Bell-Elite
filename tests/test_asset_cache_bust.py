"""Guards for the permanent cache-bust.

A hardcoded ?v=N pin in a template goes stale the moment the file changes and
only the in-flight rewrite hook saved it, so a response that skipped that hook
shipped a pinned asset (this is how sales_report.css?v=19 stuck). Templates
must stamp the live content hash with asset() instead, and these tests fail if
anyone reintroduces a pin.
"""

import io
import os
import re
import tempfile
import unittest

import asset_digest
import db as db_mod

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATES_DIR = os.path.join(PROJECT_ROOT, "templates")

# `}}?v=` is the url_for(...)+pin form; `/static/x.js?v=` is the raw-string form.
PIN_PATTERNS = (
    re.compile(r"\}\}\s*\?v="),
    re.compile(r"/static/[A-Za-z0-9_./-]+\?v="),
)


class TemplatePinTests(unittest.TestCase):
    def test_no_hardcoded_version_pins_in_templates(self):
        offenders = []
        for dirpath, dirs, files in os.walk(TEMPLATES_DIR):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for fn in sorted(files):
                if not fn.endswith(".html"):
                    continue
                path = os.path.join(dirpath, fn)
                with io.open(path, encoding="utf-8") as fh:
                    for lineno, line in enumerate(fh, 1):
                        for pat in PIN_PATTERNS:
                            if pat.search(line):
                                rel = os.path.relpath(path, PROJECT_ROOT)
                                offenders.append(
                                    "%s:%d: %s" % (rel, lineno, line.strip())
                                )
                                break
        self.assertEqual(
            offenders,
            [],
            "Hardcoded ?v= pins found. Use {{ asset('file.css') }} so the live "
            "content hash is stamped at render time:\n" + "\n".join(offenders),
        )



CDN_SCRIPT_PATTERNS = (
    re.compile(r"""src=["']https?://[^"']*(?:unpkg\.com|cdn\.jsdelivr\.net|cdnjs\.cloudflare\.com|ajax\.googleapis\.com)""", re.I),
    re.compile(r"""src=["']https?://[^"']*@latest[^"']*["']""", re.I),
)


class TemplateCdnScriptTests(unittest.TestCase):
    def test_no_public_cdn_scripts_in_templates(self):
        """App JS must be vendored under static/ and loaded via asset().

        unpkg@latest Lucide hung Employee Payroll and Access Management when
        the CDN stalled; soft-nav then looked like a cache bug.
        """
        offenders = []
        for dirpath, dirs, files in os.walk(TEMPLATES_DIR):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for fn in sorted(files):
                if not fn.endswith(".html"):
                    continue
                path = os.path.join(dirpath, fn)
                with io.open(path, encoding="utf-8") as fh:
                    for lineno, line in enumerate(fh, 1):
                        for pat in CDN_SCRIPT_PATTERNS:
                            if pat.search(line):
                                rel = os.path.relpath(path, PROJECT_ROOT)
                                offenders.append(
                                    "%s:%d: %s" % (rel, lineno, line.strip())
                                )
                                break
        self.assertEqual(
            offenders,
            [],
            "Public CDN <script> tags found. Vendor the file under static/ and "
            "use {{ asset('file.js') }}:\n" + "\n".join(offenders),
        )


class SoftNavPrefetchPolicyTests(unittest.TestCase):
    def test_idle_prefetch_is_light_hubs_only(self):
        js_path = os.path.join(PROJECT_ROOT, "static", "de_workspace_transitions.js")
        with io.open(js_path, encoding="utf-8") as fh:
            src = fh.read()
        # Extract the IDLE_PREFETCH_PATHS array body.
        start = src.find("var IDLE_PREFETCH_PATHS = [")
        self.assertGreaterEqual(start, 0, "IDLE_PREFETCH_PATHS missing")
        end = src.find("];", start)
        block = src[start:end]
        forbidden = (
            "/employees",
            "/access-management",
            "/point-of-sale",
            "/hotel/rooms",
            "/accounts",
            "/stores/",
            "/communication-hub",
        )
        for path in forbidden:
            self.assertNotIn(
                "'%s'" % path,
                block,
                "Do not idle-prefetch heavy module %s (see AGENTS.md)" % path,
            )
        for path in ("/home", "/main-dashboard", "/master", "/settings", "/license"):
            self.assertIn("'%s'" % path, block)

    def test_must_fetch_live_covers_payroll_and_access(self):
        js_path = os.path.join(PROJECT_ROOT, "static", "de_workspace_transitions.js")
        with io.open(js_path, encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn("function mustFetchLiveSoftNavPath", src)
        for needle in (
            "/employees",
            "/access-management",
            "/point-of-sale/invoice-ledger",
            "/accounts",
            "/stores",
            "/communication-hub",
        ):
            self.assertIn(needle, src, "mustFetchLiveSoftNavPath must mention %s" % needle)

    def test_restaurant_shell_is_prefetchable(self):
        """Blanket live-only on /point-of-sale made Restaurant wait on every open."""
        js_path = os.path.join(PROJECT_ROOT, "static", "de_workspace_transitions.js")
        with io.open(js_path, encoding="utf-8") as fh:
            src = fh.read()
        start = src.find("function mustFetchLiveSoftNavPath")
        end = src.find("\n  function ", start + 10)
        block = src[start:end]
        self.assertNotIn(
            "path === '/point-of-sale' || path.indexOf('/point-of-sale/') === 0",
            block,
        )
        self.assertNotIn(
            "path === '/bar-point-of-sale' || path.indexOf('/bar-point-of-sale/') === 0",
            block,
        )
        self.assertIn("function syncSoftNavBuildId", src)
        self.assertIn("function warmAssetsFromHtml", src)
        self.assertIn("prefetchRestaurantGroup", src)



class TemplateFontCdnTests(unittest.TestCase):
    def test_no_google_fonts_in_templates_or_static_ui(self):
        offenders = []
        roots = (
            TEMPLATES_DIR,
            os.path.join(PROJECT_ROOT, "static"),
        )
        for root in roots:
            for dirpath, dirs, files in os.walk(root):
                dirs[:] = [d for d in dirs if d != "__pycache__"]
                for fn in files:
                    if not fn.endswith((".html", ".css", ".js")):
                        continue
                    path = os.path.join(dirpath, fn)
                    with io.open(path, encoding="utf-8", errors="ignore") as fh:
                        for lineno, line in enumerate(fh, 1):
                            if "fonts.googleapis" in line or "fonts.gstatic" in line:
                                rel = os.path.relpath(path, PROJECT_ROOT)
                                offenders.append("%s:%d" % (rel, lineno))
                                break
        self.assertEqual(
            offenders,
            [],
            "Google Fonts CDN found. Use partials/hbe_fonts.html / hbe_login_fonts.css:\n"
            + "\n".join(offenders),
        )

class AssetHelperTests(unittest.TestCase):

    def test_critical_module_warm_and_instant_shells(self):
        js_path = os.path.join(PROJECT_ROOT, "static", "de_workspace_transitions.js")
        with io.open(js_path, encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn("function scheduleCriticalModuleWarm", src)
        self.assertIn("function prefetchHotelGroup", src)
        self.assertIn("function isInstantShellUrl", src)
        self.assertIn("function warmAssetsFromHtml", src)
        # Instant shells must include Restaurant Tables for lightning open.
        start = src.find("function isInstantShellUrl")
        end = src.find("\n  function ", start + 10)
        block = src[start:end]
        self.assertIn("'/point-of-sale'", block)
        self.assertIn("'/hotel/rooms'", block)


    def setUp(self):
        import app as app_mod

        self.app_mod = app_mod
        self.app = app_mod.app
        self.static_dir = self.app.static_folder

    def tearDown(self):
        asset_digest.reset_digest()

    def _asset(self, name):
        with self.app.test_request_context("/"):
            return self.app.jinja_env.globals["asset"](name)

    def test_asset_stamps_live_content_hash(self):
        url = self._asset("de_pwa.js")
        expected = asset_digest.current_static_hash("de_pwa.js", self.static_dir)
        self.assertTrue(expected, "de_pwa.js should have a content hash")
        self.assertEqual(url, "/static/de_pwa.js?v=%s" % expected)

    def test_hash_changes_when_file_bytes_change(self):
        fd, path = tempfile.mkstemp(
            suffix=".css", prefix="hbe_cache_guard_", dir=self.static_dir
        )
        os.close(fd)
        name = os.path.basename(path)
        try:
            with io.open(path, "w", encoding="utf-8") as fh:
                fh.write("/* one */\n")
            asset_digest.reset_digest()
            first = self._asset(name)

            with io.open(path, "w", encoding="utf-8") as fh:
                fh.write("/* two, different bytes */\n")
            asset_digest.reset_digest()
            second = self._asset(name)

            self.assertTrue(first.endswith(tuple("0123456789abcdef")))
            self.assertNotEqual(
                first, second, "editing a static file must change its hashed URL"
            )
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass
            asset_digest.reset_digest()

    def test_url_for_static_is_hashed_too(self):
        # A plain url_for('static', ...) must be safe on its own, so nobody has
        # to remember to reach for asset().
        from flask import url_for

        with self.app.test_request_context("/"):
            url = url_for("static", filename="de_pwa.js")
        expected = asset_digest.current_static_hash("de_pwa.js", self.static_dir)
        self.assertEqual(url, "/static/de_pwa.js?v=%s" % expected)

    def test_explicit_version_is_left_alone(self):
        from flask import url_for

        with self.app.test_request_context("/"):
            url = url_for("static", filename="de_pwa.js", v="pinned")
        self.assertEqual(url, "/static/de_pwa.js?v=pinned")

    def test_unknown_file_falls_back_to_plain_static_path(self):
        self.assertEqual(
            self._asset("definitely_not_a_real_file_9f2b.css"),
            "/static/definitely_not_a_real_file_9f2b.css",
        )

    def test_templates_are_never_served_from_a_stale_compiled_cache(self):
        # Under gunicorn there is no reloader; without this a template-only
        # deploy keeps rendering the previous HTML until a manual restart.
        self.assertTrue(self.app.jinja_env.auto_reload)
        self.assertTrue(self.app.config.get("TEMPLATES_AUTO_RELOAD"))


class RenderedPageHashTests(unittest.TestCase):
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

    def test_login_page_static_refs_all_carry_the_live_hash(self):
        resp = self.client.get("/login")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        resp.close()

        refs = re.findall(r"/static/([A-Za-z0-9_./-]+\.(?:css|js))(\?v=([^\"'&\s]+))?", html)
        self.assertTrue(refs, "login page should reference static assets")
        for name, _q, version in refs:
            expected = asset_digest.current_static_hash(name, self.app.static_folder)
            if not expected:
                continue
            self.assertEqual(
                version,
                expected,
                "%s must be stamped with its live content hash" % name,
            )


if __name__ == "__main__":
    unittest.main()
