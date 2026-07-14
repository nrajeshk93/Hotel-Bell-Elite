"""Tests for FO Invoice Tax Excel parser."""

import unittest
from pathlib import Path

from fo_invoice_tax_parser import parse_fo_invoice_tax_report

SAMPLE = Path("/Users/rajesh/Downloads/report-fo-invoice-tax (2).xlsx")


class FoInvoiceTaxParserTest(unittest.TestCase):
    @unittest.skipUnless(SAMPLE.exists(), "sample xlsx not available")
    def test_sample_report_imports_invoice_lines_by_report_date(self):
        with SAMPLE.open("rb") as fh:
            result = parse_fo_invoice_tax_report(fh)

        lines = result["lines"]
        self.assertEqual(len(lines), 7)
        self.assertEqual(result["meta"]["imported_dates"], ["2026-07-10"])
        self.assertEqual(result["meta"]["counts_by_date"]["2026-07-10"], 7)
        self.assertEqual(result["meta"]["total_amount"], 37600.0)

        first = lines[0]
        self.assertEqual(first["sales_date"], "2026-07-10")
        self.assertEqual(first["invoice_number"], "HBE/483/2026-27")
        self.assertEqual(first["guest_name"], "Mr. Satya Kumar")
        self.assertEqual(first["amount"], 5000.0)
        self.assertEqual(first["payment_mode"], "room_credit")

        self.assertEqual(lines[2]["payment_mode"], "card")
        self.assertEqual(lines[4]["payment_mode"], "upi")

    def test_blank_and_unknown_payment_modes_are_credit(self):
        from io import BytesIO

        import openpyxl

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Report - FO Invoices Tax"
        ws.append(["Report - FO Invoices Tax"])
        ws.append([
            "Date", "Invoice #", "Reserve No.", "Guest", "Company", "GST", "Tariff",
            "Disc. B/T", "Extra Charge", "Other Charge", "Taxable Amount", "Disc. A/T",
            "CGST @ 2.5%", "UGST @ 2.5%", "Total Tax", "Other Charge N/T", "Allowance",
            "Room Credit", "Post To Room", "Total Bill Amount", "Pay Modes",
        ])
        ws.append(["2026-07-12", "HBE/1", "1", "Guest 1", "", "", 0, 0, 0, 0, 1000, 0, 0, 0, 200, 0, 0, 0, 0, 1200, ""])
        ws.append(["2026-07-12", "HBE/2", "2", "Guest 2", "", "", 0, 0, 0, 0, 800, 0, 0, 0, 100, 0, 0, 0, 0, 900, "Cheque"])
        ws.append(["Total", None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, 2100, None])
        buf = BytesIO()
        wb.save(buf)
        buf.seek(0)

        result = parse_fo_invoice_tax_report(buf)

        self.assertEqual(len(result["lines"]), 2)
        self.assertEqual([line["amount"] for line in result["lines"]], [1200.0, 900.0])
        self.assertEqual([line["payment_mode"] for line in result["lines"]], ["room_credit", "room_credit"])
        self.assertEqual(result["lines_by_date"]["2026-07-12"][1]["invoice_number"], "HBE/2")


if __name__ == "__main__":
    unittest.main()
