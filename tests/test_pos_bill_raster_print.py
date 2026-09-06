"""Wiring checks for View-bill raster thermal printing (clear Noto digits)."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PosBillRasterPrintWiringTests(unittest.TestCase):
    def test_html2canvas_vendored_and_loaded_via_asset(self):
        vendor = ROOT / "static" / "html2canvas.min.js"
        self.assertTrue(vendor.is_file(), "html2canvas.min.js must be vendored under static/")
        self.assertGreater(vendor.stat().st_size, 10_000)

        for rel in (
            "templates/point_of_sale_invoice_ledger.html",
            "templates/point_of_sale_invoice.html",
            "templates/point_of_sale.html",
            "templates/point_of_sale_settings.html",
        ):
            text = (ROOT / rel).read_text(encoding="utf-8")
            self.assertIn("asset('html2canvas.min.js')", text, rel)
            self.assertNotIn("cdn.jsdelivr", text)
            self.assertNotIn("unpkg.com", text)

    def test_printers_prefer_full_bill_raster(self):
        src = (ROOT / "static" / "pos_printers.js").read_text(encoding="utf-8")
        self.assertIn("function renderCustomerBillRasterEscPos", src)
        self.assertIn("function canvasToEscPosRasterBands", src)
        self.assertIn("renderCustomerBillRasterEscPos(invoice", src)
        self.assertIn("viaRaster", src)
        self.assertIn("renderCustomerBillRasterEscPos: renderCustomerBillRasterEscPos", src)

    def test_ledger_passes_created_by_user_label(self):
        src = (ROOT / "static" / "pos_invoice_ledger.js").read_text(encoding="utf-8")
        self.assertIn("userLabel: String((invoice && invoice.created_by)", src)


if __name__ == "__main__":
    unittest.main()
