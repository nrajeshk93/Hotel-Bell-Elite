"""Tests for ROOM SALES.xlsx → invoices + agencies migration mapping."""

import os
import tempfile
import unittest
import zipfile
from xml.etree.ElementTree import Element, SubElement, tostring

import db as db_mod
import room_sales_import


def _col_letters(n: int) -> str:
    out = []
    while n:
        n, rem = divmod(n - 1, 26)
        out.append(chr(65 + rem))
    return "".join(reversed(out))


def _write_minimal_xlsx(path: str, headers: list[str], rows: list[list[str]]) -> None:
    """Write a tiny xlsx (inline strings) openpyxl-free for parser tests."""
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    workbook = Element("workbook", xmlns=ns)
    sheets = SubElement(workbook, "sheets")
    SubElement(sheets, "sheet", name="Sheet1", sheetId="1", id="rId1")

    worksheet = Element("worksheet", xmlns=ns)
    sheet_data = SubElement(worksheet, "sheetData")

    def add_row(row_idx: int, values: list[str]):
        row_el = SubElement(sheet_data, "row", r=str(row_idx))
        for col_idx, value in enumerate(values, 1):
            ref = f"{_col_letters(col_idx)}{row_idx}"
            cell = SubElement(row_el, "c", r=ref, t="inlineStr")
            is_el = SubElement(cell, "is")
            t_el = SubElement(is_el, "t")
            t_el.text = str(value)

    add_row(1, headers)
    for i, row in enumerate(rows, 2):
        add_row(i, row)

    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>
"""
    rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>
"""
    wb_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>
"""
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels)
        zf.writestr(
            "xl/workbook.xml",
            tostring(workbook, encoding="utf-8", xml_declaration=True),
        )
        zf.writestr("xl/_rels/workbook.xml.rels", wb_rels)
        zf.writestr(
            "xl/worksheets/sheet1.xml",
            tostring(worksheet, encoding="utf-8", xml_declaration=True),
        )


HEADERS = [
    "ID",
    "AGENT NAME",
    "INVOICE DATE",
    "GUEST NAME",
    "GSTIN",
    "INVOICE NUMBER",
    "ROOM NUMBER",
    "NO OF DAYS",
    "PAX",
    "ROOM RENT",
    "PLAN",
    "TAXABLE VALUE",
    "CGST",
    "UGST",
    "TOTAL GST",
    "TOTAL",
    "ROUND OFF",
    "FINAL AMOUNT",
    "TAC Amount",
    "GST (18 %)",
    "COMMISSION",
    "TCS",
    "TDS",
    "Agent to Pay @ Hotel",
    "CASH",
    "UPI",
    "BANK",
    "ROOM SERVICE",
    "BALANCE",
    "ACTION",
]


class RoomSalesMappingTests(unittest.TestCase):
    def test_clean_gstin_strips_prefix(self):
        self.assertEqual(
            room_sales_import.clean_gstin("GST 35AESPT7481E1ZU"),
            "35AESPT7481E1ZU",
        )
        self.assertEqual(room_sales_import.clean_gstin("not-a-gst"), "")
        self.assertEqual(db_mod.sanitize_agency_gst_for_import("GST:35AACCF5694A1ZS"), "35AACCF5694A1ZS")

    def test_parse_room_numbers_multi(self):
        self.assertEqual(
            room_sales_import.parse_room_numbers("101,103"),
            ["101", "103"],
        )
        self.assertEqual(room_sales_import.parse_room_numbers("207"), ["207"])

    def test_map_multi_room_open_agency_balance(self):
        row = {
            "INVOICE NUMBER": "HBE/26-27/00001",
            "INVOICE DATE": "01-04-2026",
            "GUEST NAME": "Yudhvir Singh Mihas",
            "AGENT NAME": "Lazy Yatra",
            "GSTIN": "08BKSPJ2127C1ZA",
            "ROOM NUMBER": "101,103",
            "NO OF DAYS": "1",
            "PAX": "4",
            "PLAN": "CP",
            "FINAL AMOUNT": "8000.00",
            "CASH": "0",
            "UPI": "0",
            "BANK": "0",
            "ROOM SERVICE": "0",
            "BALANCE": "8000",
            "Agent to Pay @ Hotel": "8000",
        }
        snap = room_sales_import.map_row_to_invoice_room(row)
        self.assertIsNotNone(snap)
        stay = snap["stay"]
        self.assertEqual(snap["number"], "101")
        self.assertEqual(stay["mergeRoomNumbers"], ["101", "103"])
        self.assertEqual(stay["mergeRoomLabel"], "101,103")
        self.assertEqual(stay["checkInDate"], "2026-03-31")
        self.assertEqual(stay["checkOutDate"], "2026-04-01")
        self.assertEqual(stay["ratePlan"], "CP")
        self.assertEqual(stay["estimatedTotal"], 8000.0)
        self.assertEqual(stay["balanceAmount"], 8000.0)
        self.assertEqual(stay["advancePaid"], 0.0)
        self.assertTrue(stay["agencyBilling"])
        self.assertTrue(stay["agencyRoomBilling"])
        self.assertTrue(stay["agencyFbBilling"])
        self.assertEqual(stay["agencyName"], "Lazy Yatra")
        self.assertEqual(stay["agencyGst"], "08BKSPJ2127C1ZA")
        self.assertEqual(stay["paymentMethod"], "credit")

    def test_map_settled_when_balance_zero(self):
        row = {
            "INVOICE NUMBER": "HBE/26-27/00999",
            "INVOICE DATE": "04-05-2026",
            "GUEST NAME": "Walk In Guest",
            "AGENT NAME": "",
            "GSTIN": "",
            "ROOM NUMBER": "105",
            "NO OF DAYS": "2",
            "PAX": "2",
            "PLAN": "EP",
            "FINAL AMOUNT": "7000",
            "CASH": "4000",
            "UPI": "3000",
            "BANK": "0",
            "ROOM SERVICE": "0",
            "BALANCE": "0",
        }
        snap = room_sales_import.map_row_to_invoice_room(row)
        stay = snap["stay"]
        self.assertEqual(stay["advancePaid"], 7000.0)
        self.assertEqual(stay["balanceAmount"], 0.0)
        self.assertEqual(len(stay["payments"]), 2)
        self.assertFalse(stay["agencyBilling"])
        self.assertFalse(stay["agencyRoomBilling"])
        self.assertFalse(stay["agencyFbBilling"])


class RoomSalesImportDbTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db_path = self.tmp.name
        self._orig = db_mod.DATABASE_PATH
        db_mod.DATABASE_PATH = self.db_path
        db_mod.init_db()
        self.conn = db_mod.get_db()

    def tearDown(self):
        self.conn.close()
        db_mod.DATABASE_PATH = self._orig
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def test_import_fixture_xlsx(self):
        xlsx = self.db_path + ".xlsx"
        rows = [
            [
                "1",
                "Lazy Yatra",
                "01-04-2026",
                "Yudhvir Singh Mihas",
                "08BKSPJ2127C1ZA",
                "HBE/26-27/00001",
                "101,103",
                "1",
                "4",
                "7619.04",
                "CP",
                "7619.04",
                "190.48",
                "190.48",
                "380.95",
                "8000.00",
                "0.00",
                "8000.00",
                "0",
                "0",
                "0",
                "0",
                "0",
                "8000",
                "0",
                "0",
                "0",
                "0",
                "8000",
                "",
            ],
            [
                "2",
                "Andaman Waves Tours and Travels",
                "02-04-2026",
                "Test Guest",
                "GST 35AESPT7481E1ZU",
                "HBE/26-27/00002",
                "105",
                "1",
                "2",
                "4000",
                "MAP",
                "4000",
                "100",
                "100",
                "200",
                "4200",
                "0",
                "4200",
                "0",
                "0",
                "0",
                "0",
                "0",
                "0",
                "4200",
                "0",
                "0",
                "0",
                "0",
                "",
            ],
        ]
        _write_minimal_xlsx(xlsx, HEADERS, rows)
        try:
            stats = room_sales_import.import_room_sales(self.conn, xlsx, commit=True)
            self.assertEqual(stats["rows_read"], 2)
            self.assertEqual(stats["invoices_created"], 2)
            self.assertEqual(stats["invoices_open"], 1)
            self.assertEqual(stats["invoices_settled"], 1)
            self.assertEqual(stats["agencies_created"], 2)

            inv = db_mod.get_hotel_room_invoice(self.conn, "HBE/26-27/00001")
            self.assertIsNotNone(inv)
            self.assertEqual(inv["status"], "open")
            self.assertEqual(inv["room_number"], "101,103")
            self.assertEqual(inv["guest_name"], "Yudhvir Singh Mihas")
            self.assertAlmostEqual(inv["balance_amount"], 8000.0)

            settled = db_mod.get_hotel_room_invoice(self.conn, "HBE/26-27/00002")
            self.assertEqual(settled["status"], "settled")

            agencies = {a["name"]: a for a in db_mod.list_agencies(self.conn)}
            self.assertIn("Lazy Yatra", agencies)
            self.assertEqual(agencies["Lazy Yatra"]["gst"], "08BKSPJ2127C1ZA")
            self.assertEqual(
                agencies["Andaman Waves Tours and Travels"]["gst"],
                "35AESPT7481E1ZU",
            )

            # Floor board unchanged / still vacant seed.
            layout = db_mod.get_hotel_rooms_layout(self.conn)
            occupied = [
                r
                for r in layout["rooms"]
                if str(r.get("status") or "").lower() == "occupied"
            ]
            self.assertEqual(occupied, [])

            # Idempotent re-import.
            stats2 = room_sales_import.import_room_sales(self.conn, xlsx, commit=True)
            self.assertEqual(stats2["invoices_created"], 0)
            self.assertEqual(stats2["invoices_updated"], 2)
        finally:
            try:
                os.unlink(xlsx)
            except OSError:
                pass


if __name__ == "__main__":
    unittest.main()
