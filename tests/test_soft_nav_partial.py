"""Soft-nav partial=main responses omit the workspace sidebar."""

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


if __name__ == "__main__":
    unittest.main()
