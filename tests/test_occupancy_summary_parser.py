"""Tests for occupancy summary Excel parser."""

import unittest
from pathlib import Path

from occupancy_summary_parser import parse_occupancy_summary_report

SAMPLE = Path("/Users/rajesh/Downloads/report-occupancy-summary.xlsx")


class OccupancySummaryParserTest(unittest.TestCase):
    @unittest.skipUnless(SAMPLE.exists(), "sample xlsx not available")
    def test_sample_report_lines_and_total(self):
        with SAMPLE.open("rb") as fh:
            result = parse_occupancy_summary_report(fh)

        lines = result["lines"]
        self.assertEqual(len(lines), 12)
        self.assertEqual(result["meta"]["line_count"], 12)
        self.assertEqual(result["meta"]["total_amount"], 54428.53)

        first = lines[0]
        self.assertEqual(first["room"], "101")
        self.assertEqual(first["guest_name"], "Mr. Mathan Mohan")
        self.assertEqual(first["tariff"], 4000.0)
        self.assertEqual(first["discount"], 0.0)
        self.assertEqual(first["extra_amount"], 0.0)
        self.assertEqual(first["amount"], 4000.0)
        self.assertEqual(first["payment_mode"], "")

        last = lines[-1]
        self.assertEqual(last["room"], "306")
        self.assertEqual(last["amount"], 4761.9)

    def test_line_amount_is_tariff_minus_discount_plus_extra(self):
        from io import BytesIO

        import openpyxl

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Report - Occupancy Summary"
        ws.append([
            "Room", "Room Type", "Reserve #", "Guest", "Company", "Travel Agent",
            "PAX", "Room Plan", "Tariff", "Discount", "Extra Amount",
        ])
        ws.append(["101", "Deluxe", "R1", "Guest", "", "", "1", "CP", 5000, 200, 50])
        buf = BytesIO()
        wb.save(buf)
        buf.seek(0)

        result = parse_occupancy_summary_report(buf)
        self.assertEqual(len(result["lines"]), 1)
        self.assertEqual(result["lines"][0]["amount"], 4850.0)


if __name__ == "__main__":
    unittest.main()
