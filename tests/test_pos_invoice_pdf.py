"""WhatsApp POS invoice PDF matches printed Spice thermal bill."""

from __future__ import annotations

import io
import os
import unittest

from PIL import Image
from pypdf import PdfReader

from pos_invoice_pdf import (
    _logo_pdf_bytes,
    build_pos_invoice_pdf,
    is_nill_series_order_no,
    pos_invoice_pdf_filename,
)


def _pdf_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


class PosInvoicePdfTests(unittest.TestCase):
    def test_filename(self):
        self.assertEqual(
            pos_invoice_pdf_filename("SPC/2260/2026-27", 12),
            "SPC-2260-2026-27.pdf",
        )

    def test_nill_series_detection(self):
        self.assertTrue(is_nill_series_order_no("SPC/26-27/Nill/3"))
        self.assertFalse(is_nill_series_order_no("SPC/2260/2026-27"))

    def test_spice_thermal_layout_not_navy_tax_invoice(self):
        invoice = {
            "id": 12,
            "order_no": "SPC/2260/2026-27",
            "saved_at": "2026-09-05 12:00:00",
            "table_label": "T-05",
            "created_by": "admin",
            "outlet": "restaurant",
            "lines": [
                {"name": "Butter Chicken", "rate": 450, "qty": 2, "line_total": 900},
                {"name": "Butter Chicken", "rate": 450, "qty": 1, "line_total": 450},
                {"name": "Naan", "rate": 60, "qty": 4, "line_total": 240},
            ],
            "subtotal": 1590,
            "discount": 0,
            "gst": 79.5,
            "vat": 0,
            "service": 0,
            "tip": 0,
            "round_off": 0.5,
            "grand_total": 1670,
            "payments": [{"payment_method": "cash", "amount": 1670}],
        }
        pdf = build_pos_invoice_pdf(
            invoice,
            business_name="SPICE MULTICUISINE",
            address="Gurudwara Lane, Aberdeen bazar, Sri Vijaya Puram, Andaman & Nicobar 744101",
            gst="35AANFH8592H1ZS",
            fssai="12922101000132",
            logo_url="/static/pos/spice-receipt-logo.jpg",
            user_label="admin",
            outlet="restaurant",
        )
        self.assertTrue(pdf.startswith(b"%PDF"))
        text = _pdf_text(pdf)
        self.assertIn("SPICE MULTICUISINE", text)
        self.assertIn("GST 35AANFH8592H1ZS", text)
        self.assertIn("FSSAI", text)
        self.assertIn("SPC/2260/2026-27", text)
        self.assertIn("T-05", text)
        self.assertIn("Sub-Total", text)
        self.assertIn("CGST @ 2.5%", text)
        self.assertIn("UGST @ 2.5%", text)
        self.assertIn("Round-Off", text)
        self.assertIn("Total", text)
        self.assertIn("PAY MODE", text)
        self.assertIn("User : admin", text)
        self.assertIn("Butter Chicken", text)
        # Merged duplicate lines → qty 3
        self.assertRegex(text, r"Butter Chicken\s+3\b")
        # Old WhatsApp A4 navy layout markers must not appear
        self.assertNotIn("TAX INVOICE", text)
        self.assertNotIn("sent via WhatsApp", text)
        self.assertNotIn("Grand Total", text)
        self.assertNotIn("Thank you for dining with us", text)

    def test_bar_branding(self):
        invoice = {
            "id": 3,
            "order_no": "IBH/1/2026-27",
            "saved_at": "2026-09-05 18:30:00",
            "table_label": "B-2",
            "outlet": "bar",
            "created_by": "barman",
            "lines": [{"name": "Beer", "rate": 200, "qty": 1, "line_total": 200}],
            "subtotal": 200,
            "gst": 0,
            "vat": 20,
            "grand_total": 220,
        }
        pdf = build_pos_invoice_pdf(invoice, outlet="bar")
        text = _pdf_text(pdf)
        self.assertIn("IRISH BARREL HOUSE BAR", text)
        self.assertIn("VAT @ 10%", text)
        self.assertIn("User : barman", text)
        self.assertNotIn("TAX INVOICE", text)

    def test_transparent_bar_logo_composites_onto_white(self):
        """Irish Barrel PNG has transparent corners; PDF must not flatten to black."""
        logo_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "static",
            "pos",
            "irish-barrel-house-logo.png",
        )
        logo_path = os.path.abspath(logo_path)
        self.assertTrue(os.path.isfile(logo_path))
        raw = _logo_pdf_bytes(logo_path)
        self.assertTrue(raw)
        with Image.open(io.BytesIO(raw)) as im:
            rgb = im.convert("RGB")
            w, h = rgb.size
            for xy in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
                self.assertEqual(rgb.getpixel(xy), (255, 255, 255), msg=xy)

    def test_nill_series_hides_gst_fssai(self):
        invoice = {
            "id": 9,
            "order_no": "SPC/26-27/Nill/1",
            "saved_at": "2026-09-05 10:00:00",
            "table_label": "—",
            "lines": [{"name": "Tea", "rate": 40, "qty": 1, "line_total": 40}],
            "subtotal": 40,
            "gst": 2,
            "grand_total": 42,
        }
        pdf = build_pos_invoice_pdf(
            invoice,
            business_name="SPICE MULTICUISINE",
            gst="35AANFH8592H1ZS",
            fssai="12922101000132",
            outlet="restaurant",
        )
        text = _pdf_text(pdf)
        self.assertIn("SPICE MULTICUISINE", text)
        self.assertNotIn("35AANFH8592H1ZS", text)
        self.assertNotIn("FSSAI", text)


if __name__ == "__main__":
    unittest.main()
