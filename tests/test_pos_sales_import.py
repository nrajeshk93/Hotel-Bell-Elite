"""Tests for Restaurant/Bar sales → settled POS invoice migration."""

import os
import tempfile
import unittest
import zipfile
from xml.etree.ElementTree import Element, SubElement, tostring

import db as db_mod
import pos_sales_import


def _col_letters(n: int) -> str:
    out = []
    while n:
        n, rem = divmod(n - 1, 26)
        out.append(chr(65 + rem))
    return "".join(reversed(out))


def _write_minimal_xlsx(path: str, headers: list[str], rows: list[list[str]]) -> None:
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
    "INVOICE NUMBER",
    "INVOICE DATE",
    "LIQUOR",
    "VAT",
    "RESTAURANT",
    "GST",
    "DISCOUNT",
    "TOTAL",
    "CASH",
    "CARD",
    "UPI",
    "CREDIT",
    "SWIGGY",
    "ZOMATO",
    "ROOM TRANSFER",
    "ROOM NO",
    "GUEST NAME",
    "PAYMENT DATE",
    "PAYMENT STATUS",
]


class PosSalesMappingTests(unittest.TestCase):
    def test_normalize_order_no(self):
        spc = pos_sales_import.normalize_legacy_order_no("SPC-26-27-00001")
        self.assertEqual(spc["order_no"], "SPC/26-27/1")
        self.assertEqual(spc["outlet"], "restaurant")
        inv = pos_sales_import.normalize_legacy_order_no("INV-26-27-00042")
        self.assertEqual(inv["order_no"], "INV/26-27/42")
        self.assertEqual(inv["outlet"], "bar")
        self.assertIsNone(pos_sales_import.normalize_legacy_order_no("HBE/26-27/1"))

    def test_room_transfer_duplicate_uses_non_rt(self):
        splits = pos_sales_import.build_tender_splits(
            total=849.0,
            cash=0,
            card=849.0,
            upi=0,
            credit=0,
            swiggy=0,
            zomato=0,
            room_transfer=849.0,
        )
        self.assertEqual(splits, [{"payment_method": "card", "amount": 849.0}])

    def test_room_transfer_only(self):
        splits = pos_sales_import.build_tender_splits(
            total=2000.0,
            cash=0,
            card=0,
            upi=0,
            credit=0,
            swiggy=0,
            zomato=0,
            room_transfer=2000.0,
        )
        self.assertEqual(
            splits, [{"payment_method": "room_transfer", "amount": 2000.0}]
        )

    def test_unpaid_forced_settle_snapshot(self):
        row = {
            "INVOICE NUMBER": "SPC-26-27-00022",
            "INVOICE DATE": "02-04-2026",
            "LIQUOR": "0",
            "VAT": "0",
            "RESTAURANT": "252.38",
            "GST": "12.62",
            "DISCOUNT": "0",
            "TOTAL": "265.00",
            "CASH": "0",
            "CARD": "0",
            "UPI": "0",
            "CREDIT": "0",
            "SWIGGY": "265.00",
            "ZOMATO": "0",
            "ROOM TRANSFER": "0",
            "ROOM NO": "",
            "GUEST NAME": "",
            "PAYMENT DATE": "",
            "PAYMENT STATUS": "Unpaid",
        }
        snap = pos_sales_import.map_row_to_snapshot(row)
        self.assertEqual(snap["order_no"], "SPC/26-27/22")
        self.assertEqual(snap["outlet"], "restaurant")
        self.assertEqual(snap["order_type"], "takeaway")
        self.assertEqual(snap["grand_total"], 265.0)
        self.assertEqual(snap["payments"][0]["payment_method"], "swiggy")
        self.assertIn("Unpaid", snap["notes"])

    def test_order_type_zomato_takeaway(self):
        row = {
            "INVOICE NUMBER": "SPC-26-27-00039",
            "INVOICE DATE": "02-04-2026",
            "LIQUOR": "0",
            "VAT": "0",
            "RESTAURANT": "238.10",
            "GST": "11.90",
            "DISCOUNT": "0",
            "TOTAL": "250.00",
            "CASH": "0",
            "CARD": "0",
            "UPI": "0",
            "CREDIT": "0",
            "SWIGGY": "0",
            "ZOMATO": "250.00",
            "ROOM TRANSFER": "0",
            "ROOM NO": "",
            "GUEST NAME": "",
            "PAYMENT DATE": "02-04-2026",
            "PAYMENT STATUS": "Paid",
        }
        snap = pos_sales_import.map_row_to_snapshot(row)
        self.assertEqual(snap["order_type"], "takeaway")
        self.assertEqual(snap["payments"][0]["payment_method"], "zomato")

    def test_order_type_upi_dine_in(self):
        row = {
            "INVOICE NUMBER": "INV-26-27-00002",
            "INVOICE DATE": "01-04-2026",
            "LIQUOR": "1340.00",
            "VAT": "134.00",
            "RESTAURANT": "378",
            "GST": "18.90",
            "DISCOUNT": "42.00",
            "TOTAL": "1871.00",
            "CASH": "0",
            "CARD": "0",
            "UPI": "1871.00",
            "CREDIT": "0",
            "SWIGGY": "0",
            "ZOMATO": "0",
            "ROOM TRANSFER": "0",
            "ROOM NO": "",
            "GUEST NAME": "",
            "PAYMENT DATE": "01-04-2026",
            "PAYMENT STATUS": "Paid",
        }
        snap = pos_sales_import.map_row_to_snapshot(row)
        self.assertEqual(snap["order_type"], "dine_in")
        self.assertEqual(snap["outlet"], "bar")

    def test_order_type_room_transfer_dine_in(self):
        splits = pos_sales_import.build_tender_splits(
            total=2000.0,
            cash=0,
            card=0,
            upi=0,
            credit=0,
            swiggy=0,
            zomato=0,
            room_transfer=2000.0,
        )
        self.assertEqual(splits[0]["payment_method"], "room_transfer")
        row = {
            "INVOICE NUMBER": "SPC-26-27-00001",
            "INVOICE DATE": "01-04-2026",
            "LIQUOR": "0",
            "VAT": "0",
            "RESTAURANT": "1905",
            "GST": "95.25",
            "DISCOUNT": "0",
            "TOTAL": "2000.00",
            "CASH": "0",
            "CARD": "0",
            "UPI": "0",
            "CREDIT": "0",
            "SWIGGY": "0",
            "ZOMATO": "0",
            "ROOM TRANSFER": "2000.00",
            "ROOM NO": "102",
            "GUEST NAME": "Guest",
            "PAYMENT DATE": "",
            "PAYMENT STATUS": "Unpaid",
        }
        snap = pos_sales_import.map_row_to_snapshot(row)
        self.assertEqual(snap["order_type"], "dine_in")


class PosSalesImportDbTests(unittest.TestCase):
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
            # SPC restaurant, RT duplicate of UPI
            [
                "1",
                "SPC-26-27-00002",
                "01-04-2026",
                "0.00",
                "0.00",
                "220",
                "11.00",
                "0.00",
                "231.00",
                "0",
                "0",
                "231.00",
                "0",
                "0",
                "0",
                "231.00",
                "301",
                "Ankit",
                "03-04-2026",
                "Paid",
            ],
            # INV bar, unpaid → still settled
            [
                "2",
                "INV-26-27-00001",
                "01-04-2026",
                "600.00",
                "60.00",
                "180",
                "9.00",
                "0.00",
                "849.00",
                "0",
                "849.00",
                "0",
                "0",
                "0",
                "0",
                "849.00",
                "105",
                "Mr. Tarun Sahu",
                "",
                "Unpaid",
            ],
        ]
        _write_minimal_xlsx(xlsx, HEADERS, rows)
        try:
            stats = pos_sales_import.import_pos_sales(self.conn, xlsx, commit=True)
            self.assertEqual(stats["rows_read"], 2)
            self.assertEqual(stats["restaurant_created"], 1)
            self.assertEqual(stats["bar_created"], 1)
            self.assertEqual(stats["skipped"], 0)

            rest = db_mod.list_pos_invoices(self.conn, outlet="restaurant")
            self.assertEqual(len(rest), 1)
            self.assertEqual(rest[0]["order_no"], "SPC/26-27/2")
            self.assertEqual(rest[0]["status"], "closed")
            self.assertEqual(rest[0]["order_type"], "dine_in")
            row = self.conn.execute(
                "SELECT settled_at FROM pos_invoices WHERE id = ?",
                (rest[0]["id"],),
            ).fetchone()
            self.assertTrue(str(row["settled_at"] or "").strip())
            pays = db_mod.list_pos_invoice_payments(self.conn, rest[0]["id"])
            self.assertEqual([p["payment_method"] for p in pays], ["upi"])

            bar = db_mod.list_pos_invoices(self.conn, outlet="bar")
            self.assertEqual(len(bar), 1)
            self.assertEqual(bar[0]["order_no"], "INV/26-27/1")
            self.assertEqual(bar[0]["status"], "closed")
            self.assertEqual(bar[0]["order_type"], "dine_in")
            self.assertEqual(bar[0]["customer_name"], "Mr. Tarun Sahu")
            bar_pays = db_mod.list_pos_invoice_payments(self.conn, bar[0]["id"])
            self.assertEqual([p["payment_method"] for p in bar_pays], ["card"])

            # Idempotent
            stats2 = pos_sales_import.import_pos_sales(self.conn, xlsx, commit=True)
            self.assertEqual(stats2["restaurant_created"], 0)
            self.assertEqual(stats2["restaurant_updated"], 1)
            self.assertEqual(stats2["bar_updated"], 1)
            self.assertEqual(len(db_mod.list_pos_invoices(self.conn, outlet="restaurant")), 1)
        finally:
            try:
                os.unlink(xlsx)
            except OSError:
                pass


if __name__ == "__main__":
    unittest.main()
