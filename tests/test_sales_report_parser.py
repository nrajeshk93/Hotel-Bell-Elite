"""Tests for Bar/Restaurant sales Excel parsers."""

import io
import unittest
from datetime import date
from pathlib import Path

import openpyxl

from sales_report_parser import (
    OUTLET_BAR,
    OUTLET_RESTAURANT,
    classify_outlet_from_username,
    map_ledger,
    parse_collections_report,
    parse_order_invoice_report,
    parse_sales_report,
)

COLLECTIONS_SAMPLE = Path("/Users/rajesh/Downloads/report-collections.xlsx")
ORDER_INVOICE_SAMPLE = Path("/Users/rajesh/Downloads/report-order-invoice (1).xlsx")


def _collections_workbook_bytes(rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Report - Collections"
    ws.append([
        "Date", "Invoice #", "Outlet", "Ref. #", "Table/Room", "Guest",
        "Ledger", "Amount", "Discount", "Tips", "Username",
    ])
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


class CollectionsReportParserTest(unittest.TestCase):
    def test_map_ledger_room_credit_before_card(self):
        self.assertEqual(map_ledger("Room Credit | Room - 103 | Folio - 567"), "room_credit")
        self.assertEqual(map_ledger("Credit & Debit Card"), "card")

    def test_map_ledger_online_order(self):
        self.assertEqual(map_ledger("ZOMATO"), "online_order")
        self.assertEqual(map_ledger("Swiggy"), "online_order")
        self.assertEqual(map_ledger("zomato delivery"), "online_order")
        self.assertEqual(map_ledger("Room Credit | Room - 103"), "room_credit")
        self.assertEqual(map_ledger("Credit & Debit Card"), "card")

    def test_classify_outlet_from_username(self):
        self.assertEqual(classify_outlet_from_username("BAR"), OUTLET_BAR)
        self.assertEqual(classify_outlet_from_username("restaurant"), OUTLET_RESTAURANT)
        self.assertIsNone(classify_outlet_from_username("kitchen"))

    def test_online_order_sums_by_column_k(self):
        buf = _collections_workbook_bytes([
            ["08-Aug-2026", "SPC/1/2026-27", "Dining", "", "T1", "A", "Cash", 100, 0, 0, "RESTAURANT"],
            ["08-Aug-2026", "SPC/2/2026-27", "Dining", "", "", "B", "ZOMATO", 268, 0, 0, "RESTAURANT"],
            ["08-Aug-2026", "INV/1/2026-27", "Bar", "", "", "C", "Swiggy", 150, 0, 0, "BAR"],
            ["08-Aug-2026", "SPC/3/2026-27", "Dining", "", "", "D", "ZOMATO", 90, 0, 0, "BAR"],
            ["08-Aug-2026", "INV/2/2026-27", "Bar", "", "", "E", "UPI", 40, 0, 0, "BAR"],
        ])
        result = parse_collections_report(buf, date(2026, 8, 8))

        bar = result[OUTLET_BAR]
        rest = result[OUTLET_RESTAURANT]

        self.assertEqual(bar["online_order"], 240.0)
        self.assertEqual(bar["upi"], 40.0)
        self.assertEqual(bar["total_sales"], 280.0)

        self.assertEqual(rest["online_order"], 268.0)
        self.assertEqual(rest["cash"], 100.0)
        self.assertEqual(rest["total_sales"], 368.0)
        self.assertEqual(result["meta"]["rows_online_order"], 3)

    @unittest.skipUnless(COLLECTIONS_SAMPLE.exists(), "collections sample xlsx not available")
    def test_collections_sample_totals(self):
        with COLLECTIONS_SAMPLE.open("rb") as fh:
            result = parse_collections_report(fh, date(2026, 8, 6))

        bar = result[OUTLET_BAR]
        rest = result[OUTLET_RESTAURANT]

        self.assertEqual(bar["total_sales"], 10795.0)
        self.assertEqual(bar["cash"], 6492.0)
        self.assertEqual(bar["card"], 0.0)
        self.assertEqual(bar["upi"], 4303.0)
        self.assertEqual(bar["room_credit"], 0.0)
        self.assertEqual(bar["online_order"], 0.0)

        self.assertEqual(rest["total_sales"], 22170.0)
        self.assertEqual(rest["cash"], 2964.0)
        self.assertEqual(rest["card"], 0.0)
        self.assertEqual(rest["upi"], 18938.0)
        self.assertEqual(rest["room_credit"], 0.0)
        self.assertEqual(rest["online_order"], 268.0)

        self.assertEqual(result["meta"]["rows_bar"], 8)
        self.assertEqual(result["meta"]["rows_restaurant"], 11)
        self.assertEqual(result["meta"]["rows_room_transfer"], 0)
        self.assertEqual(result["meta"]["rows_online_order"], 1)
        self.assertEqual(len(result["room_transfer_lines"]), 0)

    @unittest.skipUnless(COLLECTIONS_SAMPLE.exists(), "collections sample xlsx not available")
    def test_parse_sales_report_auto_detects_collections(self):
        with COLLECTIONS_SAMPLE.open("rb") as fh:
            result = parse_sales_report(fh, date(2026, 8, 6))
        self.assertEqual(result["meta"]["format"], "collections")
        self.assertEqual(result[OUTLET_BAR]["total_sales"], 10795.0)
        self.assertEqual(result[OUTLET_RESTAURANT]["online_order"], 268.0)

    @unittest.skipUnless(COLLECTIONS_SAMPLE.exists(), "collections sample xlsx not available")
    def test_collections_no_rows_for_wrong_date(self):
        with COLLECTIONS_SAMPLE.open("rb") as fh:
            result = parse_collections_report(fh, date(2026, 8, 7))
        self.assertEqual(result["meta"]["rows_bar"], 0)
        self.assertEqual(result["meta"]["rows_restaurant"], 0)
        self.assertIn("2026-08-06", result["meta"]["available_dates"])


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
