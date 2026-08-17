"""Nill-series customer bills omit GST and FSSAI registration lines."""

import json
import os
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BILL_JS = ROOT / "static" / "pos_customer_bill.js"


def _node_available():
    try:
        subprocess.run(["node", "-v"], check=True, capture_output=True)
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


_BUILD_SCRIPT = r"""
const fs = require('fs');
const vm = require('vm');
const sandbox = { console, globalThis: null };
sandbox.globalThis = sandbox;
const code = fs.readFileSync(process.env.BILL_JS, 'utf8');
vm.runInNewContext(code, sandbox);
const invoice = JSON.parse(process.env.INVOICE_JSON);
process.stdout.write(sandbox.buildPosCustomerBillHtml(invoice));
"""


@unittest.skipUnless(_node_available(), "node is required to render customer bill HTML")
class PosNillReceiptHeaderTests(unittest.TestCase):
    def _html(self, invoice):
        result = subprocess.run(
            ["node", "-e", _BUILD_SCRIPT],
            check=True,
            capture_output=True,
            text=True,
            cwd=str(ROOT),
            env={**os.environ, "BILL_JS": str(BILL_JS), "INVOICE_JSON": json.dumps(invoice)},
        )
        return result.stdout

    def _invoice(self, order_no, gst=0, vat=0, total=50000, outlet="restaurant"):
        return {
            "order_no": order_no,
            "outlet": outlet,
            "table_label": "Table 1",
            "lines": [
                {
                    "name": "banquet",
                    "qty": 1,
                    "rate": 50000,
                    "line_total": 50000,
                }
            ],
            "subtotal": 50000,
            "gst": gst,
            "vat": vat,
            "grand_total": total,
        }

    def test_nill_restaurant_omits_gst_and_fssai(self):
        html = self._html(self._invoice("SPC/26-27/Nill/1"))
        self.assertIn("SPC/26-27/Nill/1", html)
        self.assertNotIn("GST ", html)
        self.assertNotIn("FSSAI", html)

    def test_nill_bar_omits_gst_and_fssai(self):
        html = self._html(self._invoice("INV/26-27/Nill/1", outlet="bar"))
        self.assertIn("INV/26-27/Nill/1", html)
        self.assertNotIn("GST ", html)
        self.assertNotIn("FSSAI", html)

    def test_taxable_series_keeps_gst_and_fssai(self):
        html = self._html(self._invoice("SPC/26-27/1", gst=5000, total=55000))
        self.assertIn("SPC/26-27/1", html)
        self.assertIn("GST ", html)
        self.assertIn("FSSAI", html)
