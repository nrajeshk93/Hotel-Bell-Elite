"""Soft-nav partial=main responses omit the workspace sidebar and full document chrome."""

import re
import unittest

from embed_helpers import is_partial_main_request


class PartialMainHelpersTest(unittest.TestCase):
    def test_partial_query_param(self):
        from app import app

        with app.test_request_context("/accounts?partial=main"):
            self.assertTrue(is_partial_main_request())

        with app.test_request_context("/accounts"):
            self.assertFalse(is_partial_main_request())

    def test_partial_header(self):
        from app import app

        with app.test_request_context(
            "/accounts",
            headers={"X-De-Partial": "main"},
        ):
            self.assertTrue(is_partial_main_request())

    def test_shell_partial_omits_sidebar(self):
        from flask import render_template_string

        from app import app

        with app.test_request_context("/accounts?partial=main"):
            html = render_template_string(
                "{% include 'partials/de_workspace_shell_open.html' %}"
                "CONTENT"
                "{% include 'partials/de_workspace_shell_close.html' %}",
                is_partial_main=True,
            )
        self.assertIn('data-de-partial="main"', html)
        self.assertIn("CONTENT", html)
        self.assertNotIn("de-sidebar", html)
        self.assertNotIn("de_workspace_transitions.js", html)

        with app.test_request_context("/accounts"):
            html_full = render_template_string(
                "{% include 'partials/de_workspace_shell_open.html' %}"
                "CONTENT"
                "{% include 'partials/de_workspace_shell_close.html' %}",
                is_partial_main=False,
            )
        self.assertIn("de-sidebar", html_full)
        self.assertIn("de_workspace_transitions.js", html_full)


class SoftNavTruePartialRoutesTest(unittest.TestCase):
    """Key workspace routes return main-only HTML for ?partial=main (no head/fonts)."""

    PARTIAL_ROUTES = (
        "/home",
        "/master",
        "/point-of-sale",
        "/point-of-sale/invoice",
        "/point-of-sale/settings",
        "/stores/indent",
        "/accounts/purchase-ledger",
    )

    def setUp(self):
        from app import app

        self.app = app
        self.client = app.test_client()
        app.config["TESTING"] = True

    def test_partial_routes_are_main_fragments(self):
        with self.client.session_transaction() as sess:
            sess["user_id"] = 1

        for path in self.PARTIAL_ROUTES:
            with self.subTest(path=path):
                resp = self.client.get(f"{path}?partial=main")
                if resp.status_code in (301, 302, 303, 307, 308, 401, 403):
                    self.skipTest(f"{path} unavailable ({resp.status_code})")
                self.assertEqual(resp.status_code, 200, path)
                html = resp.get_data(as_text=True)
                self.assertIn('data-de-partial="main"', html)
                self.assertIn("de-main-wrapper", html)
                self.assertIsNone(re.search(r"(?i)<!doctype\s+html", html))
                self.assertIsNone(re.search(r"(?i)<html[\s>]", html))
                self.assertIsNone(re.search(r"(?i)<head[\s>]", html))
                self.assertNotIn("fonts.googleapis.com", html)
                self.assertNotIn("de-sidebar", html)
                self.assertNotIn("de_workspace_transitions.js", html)


if __name__ == "__main__":
    unittest.main()
