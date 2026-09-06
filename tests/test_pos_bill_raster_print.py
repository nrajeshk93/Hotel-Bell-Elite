"""Wiring checks for View-bill raster thermal printing (DejaVu text + Consolas numbers + ink stroke for digit 6)."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _print_invoice_html_body(src: str) -> str:
    m = re.search(
        r"function printInvoiceHtml\(html, opts\)\s*\{(.*?)\n  function ",
        src,
        flags=re.S,
    )
    assert m, "printInvoiceHtml function body not found"
    return m.group(1)


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
        self.assertIn("THERMAL_DOTS = 512", src)
        self.assertIn("CAPTURE_SUPERSAMPLE", src)
        self.assertIn("pos-il-bill-frame", src)
        self.assertIn("doc.fonts.ready", src)
        self.assertIn("doc.fonts.load", src)

    def test_customer_bill_print_is_raster_only_no_text_fallback(self):
        """Restaurant/bar customer invoices must not silently print text ESC/POS."""
        src = (ROOT / "static" / "pos_printers.js").read_text(encoding="utf-8")
        self.assertIn("Customer bills are raster-only", src)
        body = _print_invoice_html_body(src)
        self.assertIn("renderCustomerBillRasterEscPos", body)
        self.assertIn("viaRaster = true", body)
        self.assertIn("rasterOnlyFailure", body)
        # Text ESC/POS silent fallback must not be wired for this document type.
        self.assertNotIn("sendLogoTextFallback", body)
        self.assertNotIn("formatCustomerBillEscPos", body)
        self.assertNotIn("sendTextEscPosJob", body)
        self.assertNotIn("formatCustomerBillText", body)
        # Browser print only when allowBrowserFallback is already true.
        self.assertIn("allowBrowserFallback", src[
            src.find("function printInvoiceHtml") : src.find("function applyToPanel")
        ])
        self.assertIn("if (allowBrowser)", body)

    def test_thermal_capture_css_crisp_and_nn_downscale(self):
        """Digit-6 tip: DejaVu text + Consolas numbers + ink stroke + crisp + NN."""
        src = (ROOT / "static" / "pos_printers.js").read_text(encoding="utf-8")
        self.assertIn("-webkit-font-smoothing:none", src)
        self.assertIn("font-smooth:never", src)
        self.assertNotIn("-webkit-font-smoothing:antialiased", src)
        self.assertIn("imageSmoothingEnabled = false", src)
        self.assertIn("nearest-neighbor", src)
        self.assertIn("6-tip preservation", src)
        self.assertIn("threshold at hi-res", src)
        self.assertIn("CAPTURE_SUPERSAMPLE = 4", src)
        # Text DejaVu (vendored) + numbers Consolas; ink stroke preserves thin tip.
        self.assertIn('font-family:"DejaVu Sans",sans-serif', src)
        self.assertIn("DejaVuSans.ttf", src)
        self.assertIn("DejaVuSans-Bold.ttf", src)
        self.assertIn("font-family:Consolas,monospace", src)
        self.assertIn(".bill-num", src)
        self.assertIn("""doc.fonts.load('400 13.5px "DejaVu Sans"')""", src)
        self.assertIn("""doc.fonts.load('700 13.5px "DejaVu Sans"')""", src)
        self.assertIn("""doc.fonts.load('800 16px "DejaVu Sans"')""", src)
        self.assertIn("doc.fonts.load('400 13.5px Consolas')", src)
        self.assertIn("doc.fonts.load('700 13.5px Consolas')", src)
        self.assertIn("doc.fonts.load('800 16px Consolas')", src)
        self.assertIn("-webkit-text-stroke:0.35px #000", src)
        self.assertIn("paint-order:stroke fill", src)
        self.assertIn("text-shadow:0 0 0.25px #000", src)
        self.assertIn(".totals .grand", src)
        self.assertIn("tipSharpenUpperRight", src)

    def test_customer_bill_html_uses_dejavu_text_consolas_numbers(self):
        bill = (ROOT / "static" / "pos_customer_bill.js").read_text(encoding="utf-8")
        self.assertIn("receiptDejaVuSansFaceCss", bill)
        self.assertIn("DejaVuSans.ttf", bill)
        self.assertIn("DejaVuSans-Bold.ttf", bill)
        self.assertIn('font-family:"DejaVu Sans",sans-serif', bill)
        self.assertIn("font-family:Consolas,monospace", bill)
        self.assertIn(".bill-num", bill)
        self.assertNotIn("receiptNotoSansFaceCss", bill)
        self.assertNotIn('font-family:"Noto Sans"', bill)
        fonts_dir = ROOT / "static" / "fonts"
        self.assertTrue((fonts_dir / "DejaVuSans.ttf").is_file())
        self.assertTrue((fonts_dir / "DejaVuSans-Bold.ttf").is_file())
        self.assertGreater((fonts_dir / "DejaVuSans.ttf").stat().st_size, 100_000)

    def test_ledger_passes_created_by_user_label(self):

        src = (ROOT / "static" / "pos_invoice_ledger.js").read_text(encoding="utf-8")
        self.assertIn("userLabel: String((invoice && invoice.created_by)", src)


if __name__ == "__main__":
    unittest.main()
