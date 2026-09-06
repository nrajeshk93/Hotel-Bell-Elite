"""Source + node overlay contracts for ghost-cart permanent hardening."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


class GhostCartSourceTests(unittest.TestCase):
    def test_invoice_handles_local_should_drop(self):
        js = _read("static", "pos_invoice.js")
        fn = js[
            js.find("function resumeOrderForTable") : js.find(
                "function invoiceFromOfflinePayload"
            )
        ]
        self.assertIn("localShouldDrop", fn)
        self.assertIn("purgeLocalOrderDrafts", fn)
        self.assertIn("onlyServerLinked", fn)

    def test_offline_zombie_purge_and_pick_skips_invoice_id(self):
        js = _read("static", "pos_offline.js")
        self.assertIn("purgeLegacyServerDraftZombies", js)
        pick = js[
            js.find("function pickPendingResumeForTable") : js.find(
                "function findPendingForTable"
            )
        ]
        self.assertIn("orderHasServerInvoiceId(order)", pick)
        self.assertIn("orderHasCustomerBill(order)", pick)

    def test_fix_a_print_generates_customer_bill(self):
        tables = _read("static", "pos_tables.js")
        self.assertIn("ensureCustomerBillGenerated", tables)
        print_fn = tables[
            tables.find("function printTodayInvoice") : tables.find(
                "function printTodayInvoice"
            )
            + 900
        ]
        self.assertIn("ensureCustomerBillGenerated", print_fn)

    def test_unique_preinvoice_index_still_defined(self):
        self.assertIn("idx_pos_one_active_preinvoice_per_table", _read("db.py"))

    def test_settle_sets_inactive_in_close_path(self):
        db = _read("db.py")
        close = db[
            db.find("def close_pos_invoice_and_free_table") : db.find(
                "POS_PAYMENT_METHODS ="
            )
        ]
        self.assertIn("is_active = 0", close)


class OverlayPickPendingNullHydrateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.node = shutil.which("node")

    def test_available_draft_with_invoice_id_pick_null(self):
        if not self.node:
            self.skipTest("node not available")
        runner = os.path.join(ROOT, "tests", "run_pos_occupancy_overlay.js")
        offline = os.path.join(ROOT, "static", "pos_offline.js")
        payload = {
            "mode": "pickPending",
            "table": "T1",
            "want": "restaurant",
            "orders": [
                {
                    "localId": "x1",
                    "invoiceId": 42,
                    "_stamp": 2,
                    "payload": {
                        "table": "T1",
                        "orderType": "dine_in",
                        "outlet": "restaurant",
                        "lines": [{"name": "Tea"}],
                    },
                }
            ],
        }
        proc = subprocess.run(
            [self.node, runner, offline, json.dumps(payload)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout or "null")
        self.assertIsNone(out)


if __name__ == "__main__":
    unittest.main()
