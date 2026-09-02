"""POS local-store overlay: restaurant + bar share the same tables/ledger/guest path."""

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest

import db as db_mod

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*parts):
    path = os.path.join(ROOT, *parts)
    with open(path, encoding="utf-8") as fh:
        return fh.read()


class PosOfflineLocalOverlaySourceTests(unittest.TestCase):
    def test_sw_does_not_cache_floor_occupancy(self):
        sw = _read("static", "sw.js")
        self.assertIn("__HBE_CACHE_VERSION__", sw)
        self.assertIn("__HBE_PRECACHE__", sw)
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
            "orderHasServerInvoiceId",
            "applyUnsyncedOrdersToFloorTables",
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
        self.assertIn("floorLoadGen", js)
        self.assertIn("nextFloorLoadGen", js)
        self.assertIn("cacheGen !== floorLoadGen", js)
        self.assertIn("gen !== floorLoadGen", js)

    def test_tables_cache_merge_does_not_persist_stale_occupancy(self):
        js = _read("static", "pos_tables.js")
        init = js[js.find("function initPosTablesPage") : js.find("global.posTablesStatusChanged")]
        self.assertIn("function initPosTablesPage", init)
        merge_block = init[init.find("mergePendingFloor") : init.find("paintKotPendingBanner")]
        self.assertIn("cacheGen !== floorLoadGen", merge_block)
        self.assertNotIn("writeFloorLocalSnapshot", merge_block)
        self.assertNotIn("writeFloorSessionSnapshot", merge_block)
        self.assertIn("loadFloorFromApi", init)

    def test_visibility_refetches_floor_when_online(self):
        js = _read("static", "pos_tables.js")
        bind = js[js.find("function bindLocalOccupancySync") : js.find("function initPosTablesPage")]
        self.assertIn("loadFloorFromApi", bind)
        self.assertIn("isNavigatorOnline", bind)
        self.assertIn("onPageVisible", bind)
        self.assertIn("pageshow", bind)
        self.assertIn("currentFloor || readFloorSessionSnapshot()", bind)
        refresh_local = bind[
            bind.find("function refreshFromLocal") : bind.find("function refreshOccupancyFromServer")
        ]
        self.assertNotIn("writeFloorLocalSnapshot", refresh_local)
        self.assertNotIn("writeFloorSessionSnapshot", refresh_local)

    def test_apply_pending_skips_synced_drafts_in_source(self):
        js = _read("static", "pos_offline.js")
        fn = js[
            js.find("function applyUnsyncedOrdersToFloorTables") : js.find("function applyPendingToFloor")
        ]
        self.assertIn("orderHasServerInvoiceId(order)", fn)
        self.assertIn("customerBill", fn)

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
        self.assertIn("__posIlViewDelegated", js)
        self.assertIn("posIlViewClick", js)

    def test_ledger_view_button_opens_modal_not_pos(self):
        ledger = _read("templates", "point_of_sale_invoice_ledger.html")
        self.assertIn("pos-il-view-modal", ledger)
        self.assertIn("posIlViewClick", ledger)
        self.assertRegex(
            ledger,
            r'pos-il-view-btn[^>]*onclick="return window\.posIlViewClick && window\.posIlViewClick\(this\)"',
        )

    def test_shared_templates_load_overlay_before_page_scripts(self):
        tables = _read("templates", "point_of_sale.html")
        invoice = _read("templates", "point_of_sale_invoice.html")
        ledger = _read("templates", "point_of_sale_invoice_ledger.html")
        for html in (tables, invoice, ledger):
            self.assertIn("pos_offline.js", html)
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


class PosOccupancyOverlayBehaviorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.node = shutil.which("node")

    def _run_overlay(self, tables, orders, want="restaurant"):
        if not self.node:
            self.skipTest("node is not available")
        helper = os.path.join(ROOT, "tests", "run_pos_occupancy_overlay.js")
        js_path = os.path.join(ROOT, "static", "pos_offline.js")
        payload = json.dumps({"tables": tables, "orders": orders, "want": want})
        proc = subprocess.run(
            [self.node, helper, js_path, payload],
            capture_output=True,
            text=True,
            cwd=ROOT,
            check=False,
        )
        if proc.returncode != 0:
            self.fail("node overlay helper failed: %s\n%s" % (proc.stderr, proc.stdout))
        return json.loads(proc.stdout)

    def test_synced_draft_does_not_occupy_available_table(self):
        tables = [
            {"name": "Table 2", "status": "available", "customerName": ""},
            {"name": "Table 1", "status": "available", "customerName": ""},
        ]
        orders = [
            {
                "invoiceId": 4412,
                "payload": {
                    "table": "Table 2",
                    "customerName": "Rajesh",
                    "orderType": "dine_in",
                    "outlet": "restaurant",
                    "lines": [{"name": "Tea"}],
                },
            }
        ]
        out = self._run_overlay(tables, orders)
        t2 = [t for t in out if t["name"] == "Table 2"][0]
        self.assertEqual(t2["status"], "available")
        self.assertEqual(t2.get("customerName") or "", "")

    def test_unsynced_outbox_still_occupies_table(self):
        tables = [
            {"name": "Table 2", "status": "available", "customerName": ""},
        ]
        orders = [
            {
                "invoiceId": None,
                "payload": {
                    "table": "Table 2",
                    "customerName": "Rajesh",
                    "orderType": "dine_in",
                    "outlet": "restaurant",
                    "lines": [{"name": "Tea"}],
                },
            }
        ]
        out = self._run_overlay(tables, orders)
        t2 = out[0]
        self.assertEqual(t2["status"], "occupied")
        self.assertEqual(t2["customerName"], "Rajesh")

    def test_unsynced_customer_bill_frees_occupied_table(self):
        tables = [
            {"name": "Table 2", "status": "occupied", "customerName": "Rajesh"},
        ]
        orders = [
            {
                "payload": {
                    "table": "Table 2",
                    "customerName": "Rajesh",
                    "orderType": "dine_in",
                    "outlet": "restaurant",
                    "customerBill": True,
                    "lines": [{"name": "Tea"}],
                },
            }
        ]
        out = self._run_overlay(tables, orders)
        self.assertEqual(out[0]["status"], "available")
        self.assertEqual(out[0].get("customerName") or "", "")


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
        self.assertRegex(html, re.compile(r"pos_offline\.js\?v=[a-f0-9]{8,}"))
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
