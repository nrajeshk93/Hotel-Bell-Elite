"""Tests for Bar/Restaurant sales Excel parsers."""

import unittest
from datetime import date
from pathlib import Path

from sales_report_parser import (
    OUTLET_BAR,
    OUTLET_RESTAURANT,
    map_ledger,
    parse_collections_report,
    parse_order_invoice_report,
    parse_sales_report,
)

COLLECTIONS_SAMPLE = Path("/Users/rajesh/Downloads/report-collections.xlsx")
ORDER_INVOICE_SAMPLE = Path("/Users/rajesh/Downloads/report-order-invoice (1).xlsx")


class CollectionsReportParserTest(unittest.TestCase):
    def test_map_ledger_room_credit_before_card(self):
        self.assertEqual(map_ledger("Room Credit | Room - 103 | Folio - 567"), "room_credit")
        self.assertEqual(map_ledger("Credit & Debit Card"), "card")

    @unittest.skipUnless(COLLECTIONS_SAMPLE.exists(), "collections sample xlsx not available")
    def test_collections_sample_totals(self):
        with COLLECTIONS_SAMPLE.open("rb") as fh:
            result = parse_collections_report(fh, date(2026, 7, 9))

        bar = result[OUTLET_BAR]
        rest = result[OUTLET_RESTAURANT]

        self.assertEqual(bar["total_sales"], 25065.0)
        self.assertEqual(bar["cash"], 2410.0)
        self.assertEqual(bar["card"], 0.0)
        self.assertEqual(bar["upi"], 22487.0)
        self.assertEqual(bar["room_credit"], 168.0)

        self.assertEqual(rest["total_sales"], 12042.0)
        self.assertEqual(rest["cash"], 2079.0)
        self.assertEqual(rest["card"], 5814.0)
        self.assertEqual(rest["upi"], 2983.0)
        self.assertEqual(rest["room_credit"], 1166.0)

        self.assertEqual(result["meta"]["rows_bar"], 14)
        self.assertEqual(result["meta"]["rows_restaurant"], 7)
        self.assertEqual(result["meta"]["rows_room_transfer"], 3)
        self.assertEqual(len(result["room_transfer_lines"]), 3)
        self.assertEqual(result["room_transfer_lines"][0]["payment_status"], "unpaid")
        self.assertEqual(result["room_transfer_lines"][0]["amount"], 168.0)

    @unittest.skipUnless(COLLECTIONS_SAMPLE.exists(), "collections sample xlsx not available")
    def test_parse_sales_report_auto_detects_collections(self):
        with COLLECTIONS_SAMPLE.open("rb") as fh:
            result = parse_sales_report(fh, date(2026, 7, 9))
        self.assertEqual(result["meta"]["format"], "collections")
        self.assertEqual(result[OUTLET_BAR]["total_sales"], 25065.0)


    @unittest.skipUnless(COLLECTIONS_SAMPLE.exists(), "collections sample xlsx not available")
    def test_collections_no_rows_for_wrong_date(self):
        with COLLECTIONS_SAMPLE.open("rb") as fh:
            result = parse_collections_report(fh, date(2026, 7, 10))
        self.assertEqual(result["meta"]["rows_bar"], 0)
        self.assertEqual(result["meta"]["rows_restaurant"], 0)
        self.assertIn("2026-07-09", result["meta"]["available_dates"])


class OrderInvoiceReportParserTest(unittest.TestCase):
    @unittest.skipUnless(ORDER_INVOICE_SAMPLE.exists(), "order-invoice sample xlsx not available")
    def test_sample_report_totals(self):
        with ORDER_INVOICE_SAMPLE.open("rb") as fh:
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
