"""Tests for order-invoice Excel parser."""

import unittest
from datetime import date
from pathlib import Path

from sales_report_parser import OUTLET_BAR, OUTLET_RESTAURANT, parse_order_invoice_report

SAMPLE = Path("/Users/rajesh/Downloads/report-order-invoice (1).xlsx")


class SalesReportParserTest(unittest.TestCase):
    @unittest.skipUnless(SAMPLE.exists(), "sample xlsx not available")
    def test_sample_report_totals(self):
        with SAMPLE.open("rb") as fh:
            result = parse_order_invoice_report(fh, date(2026, 6, 27))

        bar = result[OUTLET_BAR]
        rest = result[OUTLET_RESTAURANT]

        self.assertEqual(bar["total_sales"], 6771.0)
        self.assertEqual(bar["cash"], 913.0)
        self.assertEqual(bar["card"], 1214.0)
        self.assertEqual(bar["upi"], 4644.0)
        self.assertEqual(bar["room_credit"], 0.0)

        self.assertEqual(rest["total_sales"], 19734.0)
        self.assertEqual(rest["cash"], 1884.0)
        self.assertEqual(rest["card"], 872.0)
        self.assertEqual(rest["upi"], 15591.0)
        self.assertEqual(rest["room_credit"], 1387.0)

        self.assertEqual(result["meta"]["rows_bar"], 7)
        self.assertEqual(result["meta"]["rows_restaurant"], 14)


if __name__ == "__main__":
    unittest.main()
