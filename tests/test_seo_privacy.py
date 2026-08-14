"""Search engines must not list the private accounts site."""

import os
import tempfile
import unittest

import db as db_mod


class SeoPrivacyTests(unittest.TestCase):
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

    def test_robots_txt_disallows_crawling_without_login(self):
        resp = self.client.get("/robots.txt")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"User-agent: *", resp.data)
        self.assertIn(b"Disallow: /", resp.data)
        self.assertFalse(resp.headers.get("Location"))

    def test_login_page_asks_search_engines_not_to_index(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        robots = (resp.headers.get("X-Robots-Tag") or "").lower()
        self.assertIn("noindex", robots)
        self.assertIn("nofollow", robots)
        self.assertIn(b'name="robots"', resp.data)
        self.assertIn(b"noindex", resp.data)
        self.assertIn("no-store", (resp.headers.get("Cache-Control") or "").lower())
        self.assertIn("Cookie", resp.headers.get("Vary") or "")

    def test_sitemap_is_not_published(self):
        resp = self.client.get("/sitemap.xml")
        self.assertEqual(resp.status_code, 404)
        self.assertIn("noindex", (resp.headers.get("X-Robots-Tag") or "").lower())
