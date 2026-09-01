"""POS local-store overlay: restaurant + bar share the same tables/ledger/guest path."""

import os
import re
import tempfile
import unittest

import db as db_mod

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*parts):
    path = os.path.join(ROOT, *parts)
    with open(path, encoding="utf-8") as fh:
        return fh.read()


class PosOfflineLocalOverlaySourceTests(unittest.TestCase):
    def test_sw_v20_does_not_cache_floor_occupancy(self):
        sw = _read("static", "sw.js")
        self.assertIn("CACHE_VERSION = 'hbe-app-v20'", sw)
        self.assertIn("pos_offline.js?v=6", sw)
        self.assertIn("pos_invoice.js?v=156", sw)
        self.assertIn("Do not cache occupancy", sw)
        self.assertIn("/point-of-sale/api/floor", sw)
        self.assertIn("/bar-point-of-sale/api/floor", sw)
        self.assertIn("/point-of-sale/api/menu/items", sw)
        self.assertIn("/bar-point-of-sale/api/menu/items", sw)
        floor_fn = sw[sw.find("function networkOnlyFloor") : sw.find("function networkFirst")]
        self.assertIn("cache: 'no-store'", floor_fn)
        self.assertNotIn("cache.put", floor_fn)

    def test_offline_store_exposes_overlay_helpers(self):
        js = _read("static", "pos_offline.js")
        for needle in (
            "rememberCustomer",
            "searchSavedCustomers",
            "applyPendingToFloor",
            "listDrafts",
            "notifyChange",
            "hbe-pos-local",
            "persistFloorSnapshot",
            "findPendingForTable",
            "pendingOrders",
            "patchFloorOccupancy",
        ):
            self.assertIn(needle, js)

    def test_tables_merges_pending_floor(self):
        js = _read("static", "pos_tables.js")
        self.assertIn("mergePendingFloor", js)
        self.assertIn("bindLocalOccupancySync", js)
        self.assertIn("cache: 'no-store'", js)

    def test_invoice_remembers_guest_and_resumes_local(self):
        js = _read("static", "pos_invoice.js")
        self.assertIn("rememberGuestFromPayload", js)
        self.assertIn("resumeOrderFromLocal", js)
        self.assertIn("invoiceFromOfflinePayload", js)
        self.assertIn("warmCustomerCatalog", js)

    def test_ledger_overlays_pending_rows(self):
        js = _read("static", "pos_invoice_ledger.js")
        self.assertIn("overlayPendingLedgerRows", js)
        self.assertIn("is-local-pending", js)

    def test_shared_templates_load_overlay_before_page_scripts(self):
        tables = _read("templates", "point_of_sale.html")
        invoice = _read("templates", "point_of_sale_invoice.html")
        ledger = _read("templates", "point_of_sale_invoice_ledger.html")
        for html in (tables, invoice, ledger):
            self.assertIn("pos_offline.js", html)
            self.assertIn("?v=6", html)
            self.assertIn("pos_outlet|default('restaurant')", html)
        self.assertLess(tables.find("pos_offline.js"), tables.find("pos_tables.js"))
        self.assertLess(invoice.find("pos_offline.js"), invoice.find("pos_invoice.js"))
        self.assertLess(
            ledger.find("pos_offline.js"), ledger.find("pos_invoice_ledger.js")
        )

    def test_hotel_pages_do_not_use_pos_offline_store(self):
        templates_dir = os.path.join(ROOT, "templates")
        for name in os.listdir(templates_dir):
            if "hotel" not in name.lower() or not name.endswith(".html"):
                continue
            html = _read("templates", name)
            self.assertNotIn(
                "pos_offline.js",
                html,
                msg="%s should not load POS offline store" % name,
            )


class PosOfflineLocalOverlayPageTests(unittest.TestCase):
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
        login = self.client.post(
            "/login",
            data={"username": "admin", "password": "admin"},
            follow_redirects=False,
        )
        self.assertIn(login.status_code, (302, 303))

    def tearDown(self):
        db_mod.DATABASE_PATH = self._orig_path
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def _assert_overlay_page(self, path, outlet):
        page = self.client.get(path)
        self.assertEqual(page.status_code, 200, path)
        html = page.get_data(as_text=True)
        page.close()
        self.assertIn("pos_offline.js", html, path)
        self.assertRegex(html, re.compile(r"pos_offline\.js[^\"']*\?v=6"))
        self.assertIn('data-pos-outlet="%s"' % outlet, html)

    def test_restaurant_and_bar_tables_share_overlay(self):
        self._assert_overlay_page("/point-of-sale", "restaurant")
        self._assert_overlay_page("/bar-point-of-sale", "bar")

    def test_restaurant_and_bar_invoice_share_overlay(self):
        self._assert_overlay_page("/point-of-sale/invoice", "restaurant")
        self._assert_overlay_page("/bar-point-of-sale/invoice", "bar")

    def test_restaurant_and_bar_ledger_share_overlay(self):
        self._assert_overlay_page("/point-of-sale/invoice-ledger", "restaurant")
        self._assert_overlay_page("/bar-point-of-sale/invoice-ledger", "bar")


if __name__ == "__main__":
    unittest.main()
