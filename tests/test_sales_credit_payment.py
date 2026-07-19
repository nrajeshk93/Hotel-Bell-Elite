"""Tests for Sales Credit receivables (Hotel FO credit only)."""

import sqlite3
import unittest

import app as app_module


def _memory_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE hotel_sales_ledger_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company TEXT NOT NULL,
            location TEXT NOT NULL,
            sales_date TEXT NOT NULL,
            invoice_number TEXT NOT NULL DEFAULT '',
            room TEXT NOT NULL DEFAULT '',
            room_type TEXT NOT NULL DEFAULT '',
            reserve_number TEXT NOT NULL DEFAULT '',
            guest_name TEXT NOT NULL DEFAULT '',
            company_name TEXT NOT NULL DEFAULT '',
            travel_agent TEXT NOT NULL DEFAULT '',
            pax TEXT NOT NULL DEFAULT '',
            room_plan TEXT NOT NULL DEFAULT '',
            tariff REAL NOT NULL DEFAULT 0,
            discount REAL NOT NULL DEFAULT 0,
            extra_amount REAL NOT NULL DEFAULT 0,
            amount REAL NOT NULL DEFAULT 0,
            payment_mode TEXT NOT NULL DEFAULT '',
            sort_order INTEGER NOT NULL DEFAULT 0,
            source_row INTEGER,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );
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


def _insert_rt_entry(conn, **overrides):
    values = {
        "company": "HBE",
        "location": "Bar",
        "sales_date": "2026-07-10",
        "invoice_number": "SPC/1",
        "outlet_name": "Bar",
        "table_room": "101",
        "guest_name": "Guest",
        "ledger_detail": "",
        "amount": 500,
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


class SalesCreditSyncTests(unittest.TestCase):
    def test_hotel_room_credit_syncs_into_entries(self):
        conn = _memory_conn()
        conn.execute(
            """INSERT INTO hotel_sales_ledger_entries
               (company, location, sales_date, invoice_number, room, guest_name,
                company_name, amount, payment_mode, sort_order)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("HBE", "Hotel", "2026-07-10", "INV-1", "204", "Ada", "Corp", 1500, "room_credit", 1),
        )
        conn.execute(
            """INSERT INTO hotel_sales_ledger_entries
               (company, location, sales_date, invoice_number, room, guest_name,
                amount, payment_mode, sort_order)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("HBE", "Hotel", "2026-07-10", "INV-2", "205", "Cash Guest", 900, "cash", 2),
        )
        conn.commit()

        app_module.sync_hotel_credit_entries(conn, "HBE", "Hotel", "2026-07-10")
        conn.commit()

        rows = conn.execute(
            "SELECT location, invoice_number, table_room, guest_name, amount, payment_status "
            "FROM room_transfer_entries ORDER BY id"
        ).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["location"], "Hotel")
        self.assertEqual(rows[0]["invoice_number"], "INV-1")
        self.assertEqual(rows[0]["table_room"], "204")
        self.assertEqual(rows[0]["guest_name"], "Ada")
        self.assertEqual(rows[0]["amount"], 1500)
        self.assertEqual(rows[0]["payment_status"], "unpaid")
        conn.close()

    def test_bar_sync_does_not_wipe_hotel_entries(self):
        conn = _memory_conn()
        hotel_id = _insert_rt_entry(
            conn,
            location="Hotel",
            invoice_number="H-1",
            outlet_name="Hotel",
            table_room="101",
            amount=1000,
        )
        bar_id = _insert_rt_entry(
            conn,
            location="Bar",
            invoice_number="B-1",
            amount=400,
        )
        conn.commit()

        app_module.sync_room_transfer_entries(
            conn,
            "HBE",
            "2026-07-10",
            [
                {
                    "location": "Bar",
                    "invoice_number": "B-2",
                    "outlet_name": "Bar",
                    "table_room": "12",
                    "guest_name": "New",
                    "ledger_detail": "",
                    "amount": 250,
                    "payment_status": "unpaid",
                    "sort_order": 1,
                    "source_row": 1,
                }
            ],
        )
        conn.commit()

        hotel = conn.execute(
            "SELECT id, invoice_number FROM room_transfer_entries WHERE location = 'Hotel'"
        ).fetchone()
        bars = conn.execute(
            "SELECT invoice_number, amount FROM room_transfer_entries WHERE location = 'Bar'"
        ).fetchall()
        self.assertIsNotNone(hotel)
        self.assertEqual(hotel["id"], hotel_id)
        self.assertEqual(hotel["invoice_number"], "H-1")
        self.assertEqual(len(bars), 1)
        self.assertEqual(bars[0]["invoice_number"], "B-2")
        self.assertEqual(bars[0]["amount"], 250)
        self.assertIsNone(
            conn.execute(
                "SELECT id FROM room_transfer_entries WHERE id = ?", (bar_id,)
            ).fetchone()
        )
        conn.close()

    def test_credit_loader_hotel_only_excludes_room_transfer(self):
        conn = _memory_conn()
        _insert_rt_entry(conn, location="Hotel", invoice_number="H-1", amount=100)
        _insert_rt_entry(conn, location="Bar", invoice_number="B-1", amount=200)
        _insert_rt_entry(conn, location="Restaurant", invoice_number="R-1", amount=300)
        conn.commit()

        credit_entries = app_module.load_room_transfer_entries_by_status(
            conn,
            "HBE",
            "all",
            "All",
            allowed_locations=app_module.CREDIT_OUTLET_LOCATIONS,
        )
        rt_entries = app_module.load_room_transfer_entries_by_status(
            conn,
            "HBE",
            "all",
            "All",
            allowed_locations=app_module.ROOM_TRANSFER_OUTLET_LOCATIONS,
        )
        credit_locations = {e["location"] for e in credit_entries}
        rt_locations = {e["location"] for e in rt_entries}
        self.assertEqual(credit_locations, {"Hotel"})
        self.assertEqual(rt_locations, {"Bar", "Restaurant"})
        self.assertEqual(app_module.rollup_room_transfer_entries(credit_entries)["total_amount"], 100)
        self.assertEqual(app_module.rollup_room_transfer_entries(rt_entries)["total_amount"], 500)
        conn.close()


class SalesCreditPaymentTests(unittest.TestCase):
    def test_create_and_reverse_hotel_credit_payment(self):
        conn = _memory_conn()
        entry_id = _insert_rt_entry(
            conn,
            location="Hotel",
            invoice_number="INV-9",
            outlet_name="Corp",
            table_room="301",
            guest_name="Guest Nine",
            amount=1019,
        )
        conn.commit()

        payload, errors = app_module._validate_room_transfer_payment_payload(
            conn,
            {
                "company": "HBE",
                "payment_date": "2026-07-11",
                "payment_method": "cash",
                "notes": "",
                "allocations": [{"entry_id": entry_id, "amount": 1019}],
            },
        )
        self.assertEqual(errors, [])
        self.assertEqual(payload["payment_splits"][0]["payment_method"], "cash")

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
        for eid in touched:
            app_module._sync_room_transfer_status_after_payment(conn, eid)
        conn.commit()

        status = conn.execute(
            "SELECT payment_status FROM room_transfer_entries WHERE id = ?",
            (entry_id,),
        ).fetchone()["payment_status"]
        self.assertEqual(status, "paid")

        reversed_ids = app_module._reverse_room_transfer_entry_payments(conn, [entry_id])
        conn.commit()
        self.assertEqual(reversed_ids, [entry_id])
        status = conn.execute(
            "SELECT payment_status FROM room_transfer_entries WHERE id = ?",
            (entry_id,),
        ).fetchone()["payment_status"]
        self.assertEqual(status, "unpaid")
        conn.close()


class SalesCreditRouteTests(unittest.TestCase):
    def test_credit_routes_registered(self):
        rules = {rule.rule: rule.endpoint for rule in app_module.app.url_map.iter_rules()}
        self.assertEqual(rules.get("/sales_update/credit"), "sales_update_credit")
        self.assertEqual(
            rules.get("/sales_update/credit/create_payment"),
            "create_sales_credit_payment",
        )
        self.assertEqual(
            rules.get("/sales_update/credit/reverse_payment"),
            "reverse_sales_credit_payment",
        )

    def test_credit_access_mapped(self):
        from workspace_access import _SALES_ANALYTICS_ENDPOINT_GROUPS, _SALES_ANALYTICS_SUBMODULES

        keys = {item["key"] for item in _SALES_ANALYTICS_SUBMODULES}
        self.assertIn("credit", keys)
        self.assertIn("sales_update_credit", _SALES_ANALYTICS_ENDPOINT_GROUPS["credit"])
        self.assertIn(
            "create_sales_credit_payment",
            _SALES_ANALYTICS_ENDPOINT_GROUPS["credit"],
        )


if __name__ == "__main__":
    unittest.main()
