"""Warehouse vs Counter stock ledgers: inward, transfer, Store page, audit, export."""

import io
import os
import tempfile
import unittest
from datetime import date
from unittest import mock

import db as db_mod


class StockPlaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db_path = self.tmp.name
        self._orig_path = db_mod.DATABASE_PATH
        db_mod.DATABASE_PATH = self.db_path
        db_mod.init_db()

        import app as app_mod
        import stores as stores_mod

        self.app_mod = app_mod
        self.stores_mod = stores_mod
        self.app = app_mod.app
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

        conn = db_mod.get_db()
        try:
            admin = conn.execute("SELECT id FROM users WHERE username = 'admin'").fetchone()
            self.admin_id = admin["id"]
        finally:
            conn.close()

        self.user = {
            "id": self.admin_id,
            "username": "admin",
            "full_name": "Administrator",
            "is_admin": True,
            "is_active": True,
            "dashboard_access": set(),
            "stores_access": set(),
        }
        self._get_user_patch = mock.patch.object(app_mod, "get_current_user", return_value=self.user)
        self._stores_user_patch = mock.patch.object(stores_mod, "_get_user", return_value=self.user)
        self._get_user_patch.start()
        self._stores_user_patch.start()

    def tearDown(self):
        self._get_user_patch.stop()
        self._stores_user_patch.stop()
        db_mod.DATABASE_PATH = self._orig_path
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def _qty(self, outlet, item_name, unit, place):
        conn = db_mod.get_db()
        try:
            row = conn.execute(
                """
                SELECT qty_on_hand FROM store_stock_items
                WHERE outlet = ? AND place = ?
                  AND lower(item_name) = lower(?) AND lower(unit) = lower(?)
                """,
                (outlet, place, item_name, unit),
            ).fetchone()
            return float(row["qty_on_hand"]) if row else 0.0
        finally:
            conn.close()

    def _insert_stock(self, *, outlet, place, item_name, unit, qty):
        conn = db_mod.get_db()
        try:
            db_mod.ensure_stores_schema(conn)
            conn.execute(
                """
                INSERT INTO store_stock_items
                    (outlet, place, item_name, unit, qty_on_hand, updated_at)
                VALUES (?, ?, ?, ?, ?, datetime('now','localtime'))
                """,
                (outlet, place, item_name, unit, qty),
            )
            conn.commit()
        finally:
            conn.close()

    def _supplier_id(self, name="Place Test Supplier"):
        conn = db_mod.get_db()
        try:
            conn.execute("INSERT INTO suppliers (name) VALUES (?)", (name,))
            sid = conn.execute(
                "SELECT id FROM suppliers WHERE name = ? ORDER BY id DESC LIMIT 1",
                (name,),
            ).fetchone()["id"]
            conn.commit()
            return int(sid)
        finally:
            conn.close()

    def test_demo_seed_skipped_during_pytest(self):
        conn = db_mod.get_db()
        try:
            count = conn.execute("SELECT COUNT(*) AS c FROM store_stock_items").fetchone()["c"]
            self.assertEqual(int(count), 0)
        finally:
            conn.close()

    def test_inward_credits_warehouse_only(self):
        supplier_id = self._supplier_id()
        confirm = self.client.post(
            "/stores/purchase-requests/confirm-direct-with-expense",
            json={
                "outlet": "restaurant",
                "notes": "Warehouse receive",
                "lines": [
                    {
                        "item_name": "Onion",
                        "qty": 4,
                        "unit": "kg",
                        "unit_price": 20,
                        "tax_percent": 0,
                    }
                ],
                "date": date.today().isoformat(),
                "description": "Stock inward without indent approval",
                "amount": 80,
                "payment_type": "credit",
                "category": "grocery",
                "supplier_id": supplier_id,
            },
        )
        self.assertEqual(confirm.status_code, 200, confirm.get_data(as_text=True))
        self.assertTrue(confirm.get_json().get("ok"))
        self.assertIn("warehouse", (confirm.get_json().get("message") or "").lower())
        self.assertAlmostEqual(self._qty("restaurant", "Onion", "kg", "warehouse"), 4.0)
        self.assertAlmostEqual(self._qty("restaurant", "Onion", "kg", "counter"), 0.0)
        conn = db_mod.get_db()
        try:
            move = conn.execute(
                """
                SELECT place, movement_type FROM store_stock_movements
                WHERE movement_type = 'receive' AND lower(item_name) = lower('Onion')
                ORDER BY id DESC LIMIT 1
                """
            ).fetchone()
            self.assertEqual(move["place"], "warehouse")
        finally:
            conn.close()

    def test_transfer_warehouse_to_counter(self):
        self._insert_stock(
            outlet="restaurant",
            place="warehouse",
            item_name="Tomato",
            unit="kg",
            qty=10.0,
        )
        res = self.client.post(
            "/stores/stock/transfer",
            json={
                "outlet": "restaurant",
                "item_name": "Tomato",
                "unit": "kg",
                "qty": 5,
                "direction": "to_counter",
            },
        )
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        payload = res.get_json()
        self.assertTrue(payload.get("ok"))
        self.assertAlmostEqual(self._qty("restaurant", "Tomato", "kg", "warehouse"), 5.0)
        self.assertAlmostEqual(self._qty("restaurant", "Tomato", "kg", "counter"), 5.0)
        conn = db_mod.get_db()
        try:
            moves = conn.execute(
                """
                SELECT place, qty_delta, movement_type FROM store_stock_movements
                WHERE movement_type = 'transfer' AND lower(item_name) = lower('Tomato')
                ORDER BY id ASC
                """
            ).fetchall()
            self.assertEqual(len(moves), 2)
            by_place = {row["place"]: float(row["qty_delta"]) for row in moves}
            self.assertAlmostEqual(by_place["warehouse"], -5.0)
            self.assertAlmostEqual(by_place["counter"], 5.0)
            self.assertAlmostEqual(sum(by_place.values()), 0.0)
        finally:
            conn.close()

    def test_transfer_to_other_outlet_counter(self):
        self._insert_stock(
            outlet="restaurant",
            place="warehouse",
            item_name="Onion",
            unit="kg",
            qty=10.0,
        )
        res = self.client.post(
            "/stores/stock/transfer",
            json={
                "direction": "to_counter",
                "to_outlet": "bar",
                "items": [
                    {
                        "outlet": "restaurant",
                        "item_name": "Onion",
                        "unit": "kg",
                        "qty": 4,
                    }
                ],
            },
        )
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        payload = res.get_json()
        self.assertTrue(payload.get("ok"))
        self.assertEqual(payload.get("to_outlet"), "bar")
        self.assertAlmostEqual(self._qty("restaurant", "Onion", "kg", "warehouse"), 6.0)
        self.assertAlmostEqual(self._qty("restaurant", "Onion", "kg", "counter"), 0.0)
        self.assertAlmostEqual(self._qty("bar", "Onion", "kg", "counter"), 4.0)
        self.assertAlmostEqual(self._qty("bar", "Onion", "kg", "warehouse"), 0.0)

    def test_transfer_more_than_source_returns_400(self):
        self._insert_stock(
            outlet="restaurant",
            place="warehouse",
            item_name="Tomato",
            unit="kg",
            qty=2.0,
        )
        res = self.client.post(
            "/stores/stock/transfer",
            json={
                "outlet": "restaurant",
                "item_name": "Tomato",
                "unit": "kg",
                "qty": 5,
                "direction": "to_counter",
            },
        )
        self.assertEqual(res.status_code, 400)
        self.assertFalse((res.get_json() or {}).get("ok"))
        self.assertAlmostEqual(self._qty("restaurant", "Tomato", "kg", "warehouse"), 2.0)
        self.assertAlmostEqual(self._qty("restaurant", "Tomato", "kg", "counter"), 0.0)

    def test_batch_transfer_custom_qtys(self):
        self._insert_stock(
            outlet="restaurant",
            place="warehouse",
            item_name="Onion",
            unit="kg",
            qty=25.0,
        )
        self._insert_stock(
            outlet="restaurant",
            place="warehouse",
            item_name="Potato",
            unit="kg",
            qty=40.0,
        )
        res = self.client.post(
            "/stores/stock/transfer",
            json={
                "direction": "to_counter",
                "items": [
                    {
                        "outlet": "restaurant",
                        "item_name": "Onion",
                        "unit": "kg",
                        "qty": 5,
                    },
                    {
                        "outlet": "restaurant",
                        "item_name": "Potato",
                        "unit": "kg",
                        "qty": 12,
                    },
                ],
            },
        )
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        payload = res.get_json()
        self.assertTrue(payload.get("ok"))
        self.assertEqual(payload.get("count"), 2)
        self.assertAlmostEqual(self._qty("restaurant", "Onion", "kg", "warehouse"), 20.0)
        self.assertAlmostEqual(self._qty("restaurant", "Onion", "kg", "counter"), 5.0)
        self.assertAlmostEqual(self._qty("restaurant", "Potato", "kg", "warehouse"), 28.0)
        self.assertAlmostEqual(self._qty("restaurant", "Potato", "kg", "counter"), 12.0)
        conn = db_mod.get_db()
        try:
            moves = conn.execute(
                """
                SELECT place, qty_delta FROM store_stock_movements
                WHERE movement_type = 'transfer'
                  AND lower(item_name) IN ('onion', 'potato')
                ORDER BY id ASC
                """
            ).fetchall()
            self.assertEqual(len(moves), 4)
            self.assertAlmostEqual(sum(float(row["qty_delta"]) for row in moves), 0.0)
        finally:
            conn.close()

    def test_batch_transfer_over_qty_rolls_back(self):
        self._insert_stock(
            outlet="restaurant",
            place="warehouse",
            item_name="Onion",
            unit="kg",
            qty=25.0,
        )
        self._insert_stock(
            outlet="restaurant",
            place="warehouse",
            item_name="Potato",
            unit="kg",
            qty=4.0,
        )
        res = self.client.post(
            "/stores/stock/transfer",
            json={
                "direction": "to_counter",
                "items": [
                    {
                        "outlet": "restaurant",
                        "item_name": "Onion",
                        "unit": "kg",
                        "qty": 5,
                    },
                    {
                        "outlet": "restaurant",
                        "item_name": "Potato",
                        "unit": "kg",
                        "qty": 12,
                    },
                ],
            },
        )
        self.assertEqual(res.status_code, 400)
        body = res.get_json() or {}
        self.assertFalse(body.get("ok"))
        self.assertIn("Potato", body.get("error") or "")
        self.assertAlmostEqual(self._qty("restaurant", "Onion", "kg", "warehouse"), 25.0)
        self.assertAlmostEqual(self._qty("restaurant", "Onion", "kg", "counter"), 0.0)
        self.assertAlmostEqual(self._qty("restaurant", "Potato", "kg", "warehouse"), 4.0)
        self.assertAlmostEqual(self._qty("restaurant", "Potato", "kg", "counter"), 0.0)

    def test_stock_page_filters_by_place(self):
        self._insert_stock(
            outlet="restaurant",
            place="warehouse",
            item_name="Warehouse Only Flour",
            unit="kg",
            qty=8.0,
        )
        self._insert_stock(
            outlet="restaurant",
            place="counter",
            item_name="Counter Only Cream",
            unit="liter",
            qty=2.0,
        )
        warehouse = self.client.get("/stores/stock?outlet=restaurant&place=warehouse")
        self.assertEqual(warehouse.status_code, 200)
        self.assertIn(b"Warehouse Only Flour", warehouse.data)
        self.assertNotIn(b"Counter Only Cream", warehouse.data)
        self.assertIn(b'data-place="warehouse"', warehouse.data)
        self.assertIn(b'st-stock-row-check', warehouse.data)
        self.assertIn(b'id="st-stock-transfer-selected"', warehouse.data)
        self.assertIn(b'data-st-transfer="to_counter"', warehouse.data)

        counter = self.client.get("/stores/stock?outlet=restaurant&place=counter")
        self.assertEqual(counter.status_code, 200)
        self.assertIn(b"Counter Only Cream", counter.data)
        self.assertNotIn(b"Warehouse Only Flour", counter.data)
        self.assertIn(b'data-place="counter"', counter.data)
        self.assertIn(b"Return", counter.data)
        self.assertIn(b'data-st-transfer="to_warehouse"', counter.data)
        self.assertIn(b'id="st-stock-transfer-lines"', counter.data)
        self.assertIn(b'id="st-stock-transfer-to-outlet"', warehouse.data)
        self.assertIn(b'id="st-stock-transfer-to-outlet" name="to_outlet" value=""', warehouse.data)
        self.assertIn(b"Restaurant Counter", warehouse.data)
        self.assertIn(b"Bar Counter", warehouse.data)
        self.assertIn(
            b'id="st-stock-transfer-dest-restaurant" aria-selected="false"',
            warehouse.data,
        )
        self.assertIn(
            b'id="st-stock-transfer-dest-bar" aria-selected="false"',
            warehouse.data,
        )
        self.assertIn(
            b'id="st-stock-transfer-submit" disabled',
            warehouse.data,
        )

    def test_export_respects_place(self):
        self._insert_stock(
            outlet="restaurant",
            place="warehouse",
            item_name="Warehouse Only Flour",
            unit="kg",
            qty=8.0,
        )
        self._insert_stock(
            outlet="restaurant",
            place="counter",
            item_name="Counter Only Cream",
            unit="liter",
            qty=2.0,
        )
        from openpyxl import load_workbook

        warehouse = self.client.get("/stores/stock/export?outlet=restaurant&place=warehouse")
        self.assertEqual(warehouse.status_code, 200)
        self.assertIn(
            "Store Warehouse",
            warehouse.headers.get("Content-Disposition", ""),
        )
        wb = load_workbook(io.BytesIO(warehouse.data))
        names = [ws.cell(r, 1).value for ws in [wb.active] for r in range(2, wb.active.max_row + 1)]
        self.assertIn("Warehouse Only Flour", names)
        self.assertNotIn("Counter Only Cream", names)
        self.assertEqual(wb.active.cell(1, 9).value, "Place")

        counter = self.client.get("/stores/stock/export?outlet=restaurant&place=counter")
        self.assertEqual(counter.status_code, 200)
        self.assertIn(
            "Store Counter",
            counter.headers.get("Content-Disposition", ""),
        )
        wb2 = load_workbook(io.BytesIO(counter.data))
        names2 = [wb2.active.cell(r, 1).value for r in range(2, wb2.active.max_row + 1)]
        self.assertIn("Counter Only Cream", names2)
        self.assertNotIn("Warehouse Only Flour", names2)

    def test_audit_verify_adjusts_selected_place_only(self):
        self._insert_stock(
            outlet="restaurant",
            place="warehouse",
            item_name="Tomato",
            unit="kg",
            qty=10.0,
        )
        self._insert_stock(
            outlet="restaurant",
            place="counter",
            item_name="Tomato",
            unit="kg",
            qty=4.0,
        )
        page = self.client.get("/stores/stock-audit?outlet=restaurant&place=counter")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Tomato", page.data)

        conn = db_mod.get_db()
        try:
            line = conn.execute(
                """
                SELECT l.id, l.system_qty, a.place
                FROM store_stock_audit_lines l
                JOIN store_stock_audits a ON a.id = l.audit_id
                WHERE a.outlet = 'restaurant' AND a.status = 'open'
                  AND a.place = 'counter' AND l.item_name = 'Tomato'
                ORDER BY l.id DESC LIMIT 1
                """
            ).fetchone()
            self.assertIsNotNone(line)
            self.assertAlmostEqual(float(line["system_qty"]), 4.0)
            line_id = int(line["id"])
        finally:
            conn.close()

        verify = self.client.post(
            "/stores/stock-audit/verify",
            json={
                "line_id": line_id,
                "actual_qty": 3.0,
                "reason": "kitchen_wastage",
                "remarks": "Prep",
            },
        )
        self.assertEqual(verify.status_code, 200, verify.get_data(as_text=True))
        self.assertTrue(verify.get_json().get("ok"))
        self.assertAlmostEqual(self._qty("restaurant", "Tomato", "kg", "counter"), 3.0)
        self.assertAlmostEqual(self._qty("restaurant", "Tomato", "kg", "warehouse"), 10.0)

    def test_schema_rebuild_moves_existing_on_hand_to_warehouse(self):
        conn = db_mod.get_db()
        try:
            conn.execute("DROP TABLE store_stock_items")
            conn.execute(
                """
                CREATE TABLE store_stock_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    outlet TEXT NOT NULL,
                    item_name TEXT NOT NULL,
                    unit TEXT NOT NULL DEFAULT 'pcs',
                    qty_on_hand REAL NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                    UNIQUE(outlet, item_name, unit)
                )
                """
            )
            conn.execute(
                """
                INSERT INTO store_stock_items (outlet, item_name, unit, qty_on_hand, updated_at)
                VALUES ('restaurant', 'Legacy Onion', 'kg', 7.5, datetime('now','localtime'))
                """
            )
            conn.commit()
            db_mod.ensure_stores_schema(conn)
            conn.commit()
            row = conn.execute(
                """
                SELECT place, qty_on_hand FROM store_stock_items
                WHERE outlet = 'restaurant' AND item_name = 'Legacy Onion'
                """
            ).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["place"], "warehouse")
            self.assertAlmostEqual(float(row["qty_on_hand"]), 7.5)
            sql = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='store_stock_items'"
            ).fetchone()[0]
            compact = "".join(sql.lower().split())
            self.assertIn("unique(outlet,place,item_name,unit)", compact)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
