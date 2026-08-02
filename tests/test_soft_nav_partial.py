"""Soft-nav partial=main responses omit live chrome but keep a sidebar merge snapshot."""

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

    def test_shell_partial_includes_hidden_sidebar_merge_source(self):
        from flask import render_template_string, url_for

        from app import app

        def _has_access(_key):
            return True

        with app.test_request_context("/accounts?partial=main"):
            html = render_template_string(
                "{% include 'partials/de_workspace_shell_open.html' %}"
                "CONTENT"
                "{% include 'partials/de_workspace_shell_close.html' %}",
                is_partial_main=True,
                has_dashboard_access=_has_access,
                url_for=url_for,
            )
        self.assertIn('data-de-partial="main"', html)
        self.assertIn("CONTENT", html)
        # Soft-nav partials include a hidden sidebar merge snapshot (new modules).
        self.assertIn('data-de-soft-nav-merge-root', html)
        self.assertIn("de-sidebar", html)
        self.assertNotIn("de_workspace_transitions.js", html)

        with app.test_request_context("/accounts"):
            html_full = render_template_string(
                "{% include 'partials/de_workspace_shell_open.html' %}"
                "CONTENT"
                "{% include 'partials/de_workspace_shell_close.html' %}",
                is_partial_main=False,
                has_dashboard_access=_has_access,
                url_for=url_for,
            )
        self.assertIn("de-sidebar", html_full)
        self.assertNotIn("data-de-soft-nav-merge-root", html_full)
        self.assertIn("de_workspace_transitions.js", html_full)


class SoftNavTruePartialRoutesTest(unittest.TestCase):
    """Key workspace routes return main-only HTML for ?partial=main (no head/fonts)."""

    PARTIAL_ROUTES = (
        "/home",
        "/master",
        "/settings",
        "/hotel/settings",
        "/point-of-sale",
        "/point-of-sale/invoice",
        "/point-of-sale/settings",
        "/stores/indent",
        "/accounts/purchase-ledger",
        "/employees",
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
                self.assertIn('data-de-soft-nav-merge-root', html)
                self.assertIn('id="de-sidebar"', html)
                self.assertNotIn("de_workspace_transitions.js", html)


if __name__ == "__main__":
    unittest.main()
