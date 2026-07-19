"""Tests for room transfer payment clearance."""

import sqlite3
import unittest
from datetime import date

import app as app_module


def _memory_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE room_transfer_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company TEXT NOT NULL,
            location TEXT NOT NULL,
            sales_date TEXT NOT NULL,
            invoice_number TEXT NOT NULL DEFAULT '',
            outlet_name TEXT NOT NULL DEFAULT '',
            table_room TEXT NOT NULL DEFAULT '',
            guest_name TEXT NOT NULL DEFAULT '',
            ledger_detail TEXT NOT NULL DEFAULT '',
            amount REAL NOT NULL DEFAULT 0,
            payment_status TEXT NOT NULL DEFAULT 'unpaid',
            sort_order INTEGER NOT NULL DEFAULT 0,
            source_row INTEGER,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE room_transfer_payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company TEXT NOT NULL,
            payment_date TEXT NOT NULL,
            payment_method TEXT NOT NULL DEFAULT 'cash',
            transaction_id TEXT NOT NULL DEFAULT '',
            total_amount REAL NOT NULL DEFAULT 0,
            notes TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE room_transfer_payment_allocations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            room_transfer_payment_id INTEGER NOT NULL,
            room_transfer_entry_id INTEGER NOT NULL,
            amount REAL NOT NULL DEFAULT 0,
            invoice_number TEXT NOT NULL DEFAULT '',
            guest_name TEXT NOT NULL DEFAULT '',
            location TEXT NOT NULL DEFAULT '',
            sales_date TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );
        """
    )
    return conn


def _insert_entry(conn, **overrides):
    values = {
        "company": "HBE",
        "location": "Bar",
        "sales_date": "2026-07-10",
        "invoice_number": "SPC/1",
        "outlet_name": "Bar",
        "table_room": "101",
        "guest_name": "Guest",
        "ledger_detail": "",
        "amount": 1019,
        "payment_status": "unpaid",
        "sort_order": 1,
        "source_row": 1,
    }
    values.update(overrides)
    cur = conn.execute(
        """INSERT INTO room_transfer_entries
           (company, location, sales_date, invoice_number, outlet_name, table_room,
            guest_name, ledger_detail, amount, payment_status, sort_order, source_row)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            values["company"],
            values["location"],
            values["sales_date"],
            values["invoice_number"],
            values["outlet_name"],
            values["table_room"],
            values["guest_name"],
            values["ledger_detail"],
            values["amount"],
            values["payment_status"],
            values["sort_order"],
            values["source_row"],
        ),
    )
    return cur.lastrowid


def _record_payment(conn, payload):
    payment_ids = []
    touched = set()
    for split in payload["payment_splits"]:
        cur = conn.execute(
            """INSERT INTO room_transfer_payments
               (company, payment_date, payment_method, transaction_id, total_amount, notes)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                payload["company"],
                payload["payment_date"],
                split["payment_method"],
                split["transaction_id"],
                split["amount"],
                payload["notes"],
            ),
        )
        payment_id = cur.lastrowid
        payment_ids.append(payment_id)
        for allocation in app_module._proportion_room_transfer_allocations(
            payload["allocations"],
            split["amount"],
        ):
            entry = allocation["entry"]
            conn.execute(
                """INSERT INTO room_transfer_payment_allocations
                   (room_transfer_payment_id, room_transfer_entry_id, amount,
                    invoice_number, guest_name, location, sales_date)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    payment_id,
                    allocation["entry_id"],
                    allocation["amount"],
                    entry.get("invoice_number") or "",
                    entry.get("guest_name") or "",
                    entry.get("location") or "",
                    entry.get("sales_date") or "",
                ),
            )
            touched.add(allocation["entry_id"])
    for entry_id in touched:
        app_module._sync_room_transfer_status_after_payment(conn, entry_id)
    return payment_ids


class RoomTransferPaymentTests(unittest.TestCase):
    def test_validate_and_record_full_payment(self):
        conn = _memory_conn()
        entry_id = _insert_entry(conn)
        payload, errors = app_module._validate_room_transfer_payment_payload(
            conn,
            {
                "company": "HBE",
                "payment_date": "2026-07-16",
                "payment_method": "cash",
                "notes": "Settled",
                "allocations": [{"entry_id": entry_id, "amount": 1019}],
            },
        )
        self.assertEqual(errors, [])
        self.assertEqual(payload["total_amount"], 1019)
        self.assertEqual(len(payload["payment_splits"]), 1)
        self.assertEqual(payload["payment_splits"][0]["payment_method"], "cash")

        _record_payment(conn, payload)

        row = conn.execute(
            "SELECT payment_status FROM room_transfer_entries WHERE id = ?",
            (entry_id,),
        ).fetchone()
        self.assertEqual(row["payment_status"], "paid")

    def test_bank_transfer_requires_transaction_id(self):
        conn = _memory_conn()
        entry_id = _insert_entry(conn)
        payload, errors = app_module._validate_room_transfer_payment_payload(
            conn,
            {
                "company": "HBE",
                "payment_date": date.today().isoformat(),
                "payment_method": "bank_transfer",
                "allocations": [{"entry_id": entry_id, "amount": 1019}],
            },
        )
        self.assertIsNone(payload)
        self.assertTrue(any("Transaction ID" in err for err in errors))

    def test_split_payment_across_modes(self):
        conn = _memory_conn()
        entry_id = _insert_entry(conn, amount=1000)
        payload, errors = app_module._validate_room_transfer_payment_payload(
            conn,
            {
                "company": "HBE",
                "payment_date": "2026-07-16",
                "allocations": [{"entry_id": entry_id, "amount": 1000}],
                "payment_splits": [
                    {"payment_method": "cash", "amount": 400},
                    {"payment_method": "upi", "amount": 350},
                    {
                        "payment_method": "bank_transfer",
                        "amount": 250,
                        "transaction_id": "UTR123",
                    },
                ],
            },
        )
        self.assertEqual(errors, [])
        self.assertEqual(len(payload["payment_splits"]), 3)

        payment_ids = _record_payment(conn, payload)
        self.assertEqual(len(payment_ids), 3)

        methods = {
            row["payment_method"]: row["total_amount"]
            for row in conn.execute(
                "SELECT payment_method, total_amount FROM room_transfer_payments"
            ).fetchall()
        }
        self.assertEqual(methods["cash"], 400)
        self.assertEqual(methods["upi"], 350)
        self.assertEqual(methods["bank_transfer"], 250)

        row = conn.execute(
            "SELECT payment_status FROM room_transfer_entries WHERE id = ?",
            (entry_id,),
        ).fetchone()
        self.assertEqual(row["payment_status"], "paid")

    def test_split_amounts_must_match_payment_total(self):
        conn = _memory_conn()
        entry_id = _insert_entry(conn, amount=1000)
        payload, errors = app_module._validate_room_transfer_payment_payload(
            conn,
            {
                "company": "HBE",
                "payment_date": "2026-07-16",
                "allocations": [{"entry_id": entry_id, "amount": 1000}],
                "payment_splits": [
                    {"payment_method": "cash", "amount": 400},
                    {"payment_method": "upi", "amount": 400},
                ],
            },
        )
        self.assertIsNone(payload)
        self.assertTrue(any("equal the payment total" in err for err in errors))

    def test_partial_then_remaining_with_modes(self):
        conn = _memory_conn()
        entry_id = _insert_entry(conn, amount=1000)
        first, errors = app_module._validate_room_transfer_payment_payload(
            conn,
            {
                "company": "HBE",
                "payment_date": "2026-07-16",
                "allocations": [{"entry_id": entry_id, "amount": 600}],
                "payment_splits": [
                    {"payment_method": "cash", "amount": 300},
                    {"payment_method": "card", "amount": 300},
                ],
            },
        )
        self.assertEqual(errors, [])
        _record_payment(conn, first)
        row = conn.execute(
            "SELECT payment_status FROM room_transfer_entries WHERE id = ?",
            (entry_id,),
        ).fetchone()
        self.assertEqual(row["payment_status"], "unpaid")

        second, errors = app_module._validate_room_transfer_payment_payload(
            conn,
            {
                "company": "HBE",
                "payment_date": "2026-07-17",
                "payment_method": "upi",
                "allocations": [{"entry_id": entry_id, "amount": 400}],
            },
        )
        self.assertEqual(errors, [])
        _record_payment(conn, second)
        row = conn.execute(
            "SELECT payment_status FROM room_transfer_entries WHERE id = ?",
            (entry_id,),
        ).fetchone()
        self.assertEqual(row["payment_status"], "paid")

    def test_reverse_restores_unpaid(self):
        conn = _memory_conn()
        entry_id = _insert_entry(conn, payment_status="paid")
        cur = conn.execute(
            """INSERT INTO room_transfer_payments
               (company, payment_date, payment_method, transaction_id, total_amount, notes)
               VALUES ('HBE', '2026-07-16', 'cash', '', 1019, '')"""
        )
        payment_id = cur.lastrowid
        conn.execute(
            """INSERT INTO room_transfer_payment_allocations
               (room_transfer_payment_id, room_transfer_entry_id, amount,
                invoice_number, guest_name, location, sales_date)
               VALUES (?, ?, 1019, 'SPC/1', 'Guest', 'Bar', '2026-07-10')""",
            (payment_id, entry_id),
        )
        reversed_ids = app_module._reverse_room_transfer_entry_payments(conn, [entry_id])
        self.assertEqual(reversed_ids, [entry_id])
        row = conn.execute(
            "SELECT payment_status FROM room_transfer_entries WHERE id = ?",
            (entry_id,),
        ).fetchone()
        self.assertEqual(row["payment_status"], "unpaid")
        remaining = conn.execute(
            "SELECT COUNT(*) AS cnt FROM room_transfer_payment_allocations"
        ).fetchone()
        self.assertEqual(remaining["cnt"], 0)


if __name__ == "__main__":
    unittest.main()
