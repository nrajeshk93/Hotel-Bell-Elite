import os
import tempfile
import unittest
from unittest import mock

import db as db_mod


class StoresFlowTests(unittest.TestCase):
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

        # CRITICAL: never hit live Meta/WhatsApp while exercising indent submit flows.
        # .env may load real credentials; each pending indent would otherwise send paid messages.
        self._wa_buttons_patch = mock.patch(
            "whatsapp_indent.wa.send_interactive_buttons",
            return_value=(True, "", {"messages": [{"id": "wamid.BTN"}]}),
        )
        self._wa_buttons_patch.start()

    def tearDown(self):
        self._wa_buttons_patch.stop()
        self._get_user_patch.stop()
        self._stores_user_patch.stop()
        db_mod.DATABASE_PATH = self._orig_path
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def test_format_stores_dt(self):
        fmt = self.stores_mod._format_stores_dt
        self.assertEqual(fmt("2026-07-19 10:05:57"), "19-July 10.05 AM")
        self.assertEqual(fmt("2026-07-19 13:18:06"), "19-July 1.18 PM")
        self.assertEqual(fmt("2026-07-19"), "19-July")
        self.assertEqual(fmt(""), "")
        self.assertEqual(fmt(None), "")
        self.assertEqual(
            self.stores_mod._format_stores_date_line("2026-07-19 10:05:57"),
            "19 July",
        )
        self.assertEqual(
            self.stores_mod._format_stores_time_line("2026-07-19 10:05:57"),
            "10:05 AM",
        )

    def test_indent_no_format_per_outlet_fiscal_year(self):
        from datetime import date

        fy = db_mod.indian_fiscal_year_label(date(2026, 7, 29))
        self.assertEqual(fy, "2026-27")
        next_no = self.stores_mod._next_indent_no
        conn = db_mod.get_db()
        try:
            bar1 = next_no(conn, "bar", when=date(2026, 7, 29))
            self.assertEqual(bar1, "IND/Bar/1/2026-27")
            conn.execute(
                """
                INSERT INTO store_indents
                    (outlet, indent_no, status, notes, created_at)
                VALUES ('bar', ?, 'draft', '', datetime('now','localtime'))
                """,
                (bar1,),
            )
            bar2 = next_no(conn, "bar", when=date(2026, 7, 29))
            self.assertEqual(bar2, "IND/Bar/2/2026-27")
            rest1 = next_no(conn, "restaurant", when=date(2026, 7, 29))
            self.assertEqual(rest1, "IND/Restaurant/1/2026-27")
            # Prior FY does not advance current-year series
            conn.execute(
                """
                INSERT INTO store_indents
                    (outlet, indent_no, status, notes, created_at)
                VALUES ('bar', 'IND/Bar/9/2025-26', 'draft', '', datetime('now','localtime'))
                """,
            )
            bar_still_2 = next_no(conn, "bar", when=date(2026, 7, 29))
            self.assertEqual(bar_still_2, "IND/Bar/2/2026-27")
        finally:
            conn.close()

        create_bar = self.client.post(
            "/stores/indent?outlet=bar",
            data={
                "outlet": "bar",
                "action": "submit",
                "notes": "Indent no format bar",
                "item_name": ["Onion"],
                "quantity": ["1"],
                "unit": ["kg"],
                "approximate_price": ["10"],
            },
            follow_redirects=False,
        )
        self.assertEqual(create_bar.status_code, 302)
        create_rest = self.client.post(
            "/stores/indent?outlet=restaurant",
            data={
                "outlet": "restaurant",
                "action": "submit",
                "notes": "Indent no format restaurant",
                "item_name": ["Onion"],
                "quantity": ["1"],
                "unit": ["kg"],
                "approximate_price": ["10"],
            },
            follow_redirects=False,
        )
        self.assertEqual(create_rest.status_code, 302)
        conn = db_mod.get_db()
        try:
            bar = conn.execute(
                "SELECT indent_no FROM store_indents WHERE notes = 'Indent no format bar'"
            ).fetchone()
            rest = conn.execute(
                "SELECT indent_no FROM store_indents WHERE notes = 'Indent no format restaurant'"
            ).fetchone()
            self.assertIsNotNone(bar)
            self.assertIsNotNone(rest)
            self.assertRegex(bar["indent_no"], r"^IND/Bar/\d+/2026-27$")
            self.assertRegex(rest["indent_no"], r"^IND/Restaurant/\d+/2026-27$")
        finally:
            conn.close()

    def test_product_master_seeded(self):
        conn = db_mod.get_db()
        try:
            cats = {
                row["name"]: row["id"]
                for row in conn.execute("SELECT id, name FROM store_product_categories").fetchall()
            }
            self.assertIn("Non-Veg", cats)
            self.assertIn("Dairy Products", cats)
            self.assertIn("Vegetable", cats)
            count = conn.execute("SELECT COUNT(*) AS c FROM store_products").fetchone()["c"]
            self.assertGreaterEqual(count, 60)
        finally:
            conn.close()

        page = self.client.get("/stores/product-master")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Products", page.data)
        self.assertIn(b"Non-Veg", page.data)
        self.assertIn(b"Outlet", page.data)
        self.assertIn(b'id="st-outlet-listbox"', page.data)
        self.assertIn(b"All", page.data)
        self.assertIn(b"Approximate Price", page.data)
        self.assertIn(b"Restaurant", page.data)
        self.assertIn(b"Edit", page.data)
        self.assertIn(b"Delete", page.data)

        bar_page = self.client.get("/stores/product-master?outlet=bar")
        self.assertEqual(bar_page.status_code, 200)
        self.assertIn(b'id="st-outlet-listbox"', bar_page.data)
        self.assertIn(b'data-value="bar"', bar_page.data)
        self.assertRegex(bar_page.data, rb'id="st-outlet-value"[^>]*>\s*Bar')

        conn = db_mod.get_db()
        try:
            product = conn.execute(
                """
                SELECT id, name, category_id, default_unit
                FROM store_products WHERE is_active = 1 ORDER BY id LIMIT 1
                """
            ).fetchone()
            self.assertIsNotNone(product)
            pid = product["id"]
            category_id = product["category_id"]
            unit = product["default_unit"] or "kg"
        finally:
            conn.close()

        edit_page = self.client.get(f"/stores/product-master?edit={pid}")
        self.assertEqual(edit_page.status_code, 200)
        self.assertIn(b"Edit product", edit_page.data)
        self.assertIn(b"Pack variants", edit_page.data)
        self.assertNotIn(b'id="st-product-approx-price"', edit_page.data)

        update = self.client.post(
            "/stores/product-master",
            data={
                "action": "save_product",
                "product_id": str(pid),
                "category_id": str(category_id),
                "name": "Updated Product Name",
                "outlet": "bar",
                "variant_qty": ["1"],
                "variant_unit": [unit],
                "variant_approximate_price": ["250"],
            },
            follow_redirects=True,
        )
        self.assertEqual(update.status_code, 200)
        self.assertIn(b"Product updated", update.data)
        self.assertIn(b"Bar", update.data)
        self.assertIn(b"\xe2\x82\xb9250", update.data)  # ₹250

        conn = db_mod.get_db()
        try:
            saved = conn.execute(
                "SELECT outlet, approximate_price FROM store_products WHERE id = ?", (pid,)
            ).fetchone()
            self.assertEqual(saved["outlet"], "bar")
            self.assertEqual(float(saved["approximate_price"]), 250.0)
        finally:
            conn.close()

        delete = self.client.get(f"/stores/product-master/{pid}/delete", follow_redirects=True)
        self.assertEqual(delete.status_code, 200)
        conn = db_mod.get_db()
        try:
            gone = conn.execute(
                "SELECT is_active FROM store_products WHERE id = ?", (pid,)
            ).fetchone()
            self.assertEqual(int(gone["is_active"]), 0)
        finally:
            conn.close()

    def test_product_delete_json_stays_ok(self):
        conn = db_mod.get_db()
        try:
            category = conn.execute(
                "SELECT id FROM store_product_categories WHERE is_active = 1 ORDER BY id LIMIT 1"
            ).fetchone()
            self.assertIsNotNone(category)
            category_id = category["id"]
            conn.execute(
                """
                INSERT INTO store_products
                  (category_id, name, default_unit, outlet, approximate_price, is_active, created_at, updated_at)
                VALUES (?, 'Ajax Delete Me', 'kg', 'restaurant', 10, 1, datetime('now'), datetime('now'))
                """,
                (category_id,),
            )
            conn.commit()
            pid = conn.execute(
                "SELECT id FROM store_products WHERE lower(name)=lower('Ajax Delete Me') AND is_active=1"
            ).fetchone()["id"]
        finally:
            conn.close()

        resp = self.client.post(
            f"/stores/product-master/{pid}/delete",
            headers={
                "Accept": "application/json",
                "X-Requested-With": "XMLHttpRequest",
            },
        )
        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json()
        self.assertTrue(payload.get("ok"))
        self.assertEqual(int(payload.get("product_id")), pid)
        conn = db_mod.get_db()
        try:
            gone = conn.execute(
                "SELECT is_active FROM store_products WHERE id = ?", (pid,)
            ).fetchone()
            self.assertEqual(int(gone["is_active"]), 0)
        finally:
            conn.close()

    def test_product_pack_variants_save_and_reload(self):
        conn = db_mod.get_db()
        try:
            category = conn.execute(
                "SELECT id FROM store_product_categories WHERE is_active = 1 ORDER BY id LIMIT 1"
            ).fetchone()
            self.assertIsNotNone(category)
            category_id = category["id"]
        finally:
            conn.close()

        create = self.client.post(
            "/stores/product-master",
            data={
                "action": "save_product",
                "category_id": str(category_id),
                "name": "Test Masala Pack",
                "outlet": "restaurant",
                "variant_qty": ["200", "500"],
                "variant_unit": ["gram", "gram"],
                "variant_approximate_price": ["40", "90"],
            },
            follow_redirects=True,
        )
        self.assertEqual(create.status_code, 200)
        self.assertIn(b"Product added to master", create.data)
        self.assertIn(b"2 packs", create.data)

        conn = db_mod.get_db()
        try:
            product = conn.execute(
                """
                SELECT id, default_unit, approximate_price FROM store_products
                WHERE lower(name) = lower('Test Masala Pack') AND is_active = 1
                """
            ).fetchone()
            self.assertIsNotNone(product)
            pid = product["id"]
            self.assertEqual(product["default_unit"], "kg")
            # 500 gram @ ₹90 → ₹180 / kg (largest pack anchors product price)
            self.assertAlmostEqual(float(product["approximate_price"]), 180.0)
            variants = conn.execute(
                """
                SELECT label, qty_in_base, approximate_price
                FROM store_product_variants
                WHERE product_id = ? AND is_active = 1
                ORDER BY sort_order, id
                """,
                (pid,),
            ).fetchall()
            self.assertEqual(len(variants), 2)
            self.assertEqual(variants[0]["label"], "200 gram")
            self.assertAlmostEqual(float(variants[0]["qty_in_base"]), 0.2)
            self.assertAlmostEqual(float(variants[0]["approximate_price"]), 40.0)
            self.assertEqual(variants[1]["label"], "500 gram")
            self.assertAlmostEqual(float(variants[1]["qty_in_base"]), 0.5)
        finally:
            conn.close()

        edit_page = self.client.get(f"/stores/product-master?edit={pid}")
        self.assertEqual(edit_page.status_code, 200)
        self.assertIn(b'name="variant_qty"', edit_page.data)
        self.assertIn(b'value="200"', edit_page.data)
        self.assertIn(b'value="500"', edit_page.data)
        self.assertIn(b'value="gram"', edit_page.data)
        self.assertIn(b"Pack variants", edit_page.data)
        self.assertNotIn(b'id="st-product-unit-listbox"', edit_page.data)
        self.assertNotIn(b'id="st-product-approx-price"', edit_page.data)

        update = self.client.post(
            "/stores/product-master",
            data={
                "action": "save_product",
                "product_id": str(pid),
                "category_id": str(category_id),
                "name": "Test Masala Pack",
                "outlet": "restaurant",
                "variant_qty": ["500", "1"],
                "variant_unit": ["gram", "kg"],
                "variant_approximate_price": ["90", "170"],
            },
            follow_redirects=True,
        )
        self.assertEqual(update.status_code, 200)
        self.assertIn(b"Product updated", update.data)

        conn = db_mod.get_db()
        try:
            active = conn.execute(
                """
                SELECT label, qty_in_base FROM store_product_variants
                WHERE product_id = ? AND is_active = 1
                ORDER BY sort_order, id
                """,
                (pid,),
            ).fetchall()
            self.assertEqual([row["label"] for row in active], ["500 gram", "1 kg"])
            self.assertAlmostEqual(float(active[0]["qty_in_base"]), 0.5)
            self.assertAlmostEqual(float(active[1]["qty_in_base"]), 1.0)
            inactive = conn.execute(
                """
                SELECT label FROM store_product_variants
                WHERE product_id = ? AND is_active = 0 AND lower(label) = lower('200 gram')
                """,
                (pid,),
            ).fetchone()
            self.assertIsNotNone(inactive)
        finally:
            conn.close()

        # Alphanumeric pack size is allowed and counts as 1 of the pack unit.
        alpha = self.client.post(
            "/stores/product-master",
            data={
                "action": "save_product",
                "category_id": str(category_id),
                "name": "Test Paneer Pack Alpha",
                "outlet": "restaurant",
                "variant_qty": ["Half"],
                "variant_unit": ["kg"],
                "variant_approximate_price": ["120"],
            },
            follow_redirects=True,
        )
        self.assertEqual(alpha.status_code, 200)
        self.assertIn(b"Product added to master", alpha.data)
        conn = db_mod.get_db()
        try:
            alpha_row = conn.execute(
                """
                SELECT v.label, v.qty_in_base
                FROM store_product_variants v
                JOIN store_products p ON p.id = v.product_id
                WHERE lower(p.name) = lower('Test Paneer Pack Alpha')
                  AND v.is_active = 1 AND p.is_active = 1
                """
            ).fetchone()
            self.assertIsNotNone(alpha_row)
            self.assertEqual(alpha_row["label"], "Half kg")
            self.assertAlmostEqual(float(alpha_row["qty_in_base"]), 1.0)
        finally:
            conn.close()

        # Product with no variants still saves cleanly.
        plain = self.client.post(
            "/stores/product-master",
            data={
                "action": "save_product",
                "category_id": str(category_id),
                "name": "Plain No Pack Product",
                "outlet": "bar",
                "variant_qty": [""],
                "variant_unit": ["gram"],
                "variant_approximate_price": [""],
            },
            follow_redirects=True,
        )
        self.assertEqual(plain.status_code, 200)
        self.assertIn(b"Product added to master", plain.data)
        conn = db_mod.get_db()
        try:
            plain_row = conn.execute(
                """
                SELECT id FROM store_products
                WHERE lower(name) = lower('Plain No Pack Product') AND is_active = 1
                """
            ).fetchone()
            count = conn.execute(
                """
                SELECT COUNT(*) AS c FROM store_product_variants
                WHERE product_id = ? AND is_active = 1
                """,
                (plain_row["id"],),
            ).fetchone()["c"]
            self.assertEqual(count, 0)
        finally:
            conn.close()

    def test_indent_pack_converts_to_base_qty_on_stock_receive(self):
        from datetime import date

        conn = db_mod.get_db()
        try:
            category = conn.execute(
                "SELECT id FROM store_product_categories WHERE is_active = 1 ORDER BY id LIMIT 1"
            ).fetchone()
            category_id = category["id"]
            cur = conn.execute(
                """
                INSERT INTO store_products
                    (category_id, name, default_unit, outlet, approximate_price, is_active, sort_order)
                VALUES (?, 'Pack Convert Masala', 'kg', 'bar', 100, 1, 9990)
                """,
                (category_id,),
            )
            product_id = cur.lastrowid
            conn.execute(
                """
                INSERT INTO store_product_variants
                    (product_id, label, qty_in_base, approximate_price, sort_order, is_active)
                VALUES (?, '500 gram', 0.5, 90, 10, 1)
                """,
                (product_id,),
            )
            conn.execute(
                "INSERT INTO suppliers (name) VALUES (?)",
                ("Pack Inward Supplier",),
            )
            supplier_id = conn.execute(
                "SELECT id FROM suppliers WHERE name = 'Pack Inward Supplier'"
            ).fetchone()["id"]
            conn.execute(
                "INSERT INTO cash_ledger_loads (company, load_date, description, amount) VALUES (?,?,?,?)",
                ("HBE", date.today().isoformat(), "Pack test float", 5000),
            )
            conn.commit()
        finally:
            conn.close()

        create = self.client.post(
            "/stores/indent?outlet=bar",
            data={
                "outlet": "bar",
                "action": "submit",
                "notes": "Pack inward",
                "item_name": ["Pack Convert Masala"],
                "quantity": ["2"],
                "unit": ["kg"],
                "approximate_price": ["90"],
                "pack_label": ["500 gram"],
                "pack_qty_in_base": ["0.5"],
            },
            follow_redirects=False,
        )
        self.assertEqual(create.status_code, 302)

        conn = db_mod.get_db()
        try:
            indent = conn.execute(
                "SELECT id FROM store_indents WHERE notes = 'Pack inward' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            self.assertIsNotNone(indent)
            indent_id = indent["id"]
            line = conn.execute(
                """
                SELECT id, quantity, unit, pack_label, pack_qty_in_base
                FROM store_indent_lines WHERE indent_id = ?
                """,
                (indent_id,),
            ).fetchone()
            self.assertEqual(float(line["quantity"]), 2.0)
            self.assertEqual(line["unit"], "kg")
            self.assertEqual(line["pack_label"], "500 gram")
            self.assertAlmostEqual(float(line["pack_qty_in_base"]), 0.5)
            line_id = int(line["id"])
        finally:
            conn.close()

        decide = self.client.post(
            f"/stores/indent/{indent_id}/decide",
            data={"outlet": "bar", "decision": "approved", "decision_note": ""},
            follow_redirects=False,
        )
        self.assertEqual(decide.status_code, 302)

        confirm = self.client.post(
            "/stores/purchase-requests/confirm-with-expense",
            json={
                "indent_id": indent_id,
                "notes": "",
                "lines": [
                    {
                        "line_id": line_id,
                        "received_qty": 2,
                        "unit_price": 95,
                        "tax_percent": 0,
                    }
                ],
                "date": date.today().isoformat(),
                "description": "Pack stock inward",
                "amount": 190,
                "payment_type": "cash",
                "category": "grocery",
                "supplier_id": supplier_id,
            },
        )
        self.assertEqual(confirm.status_code, 200, confirm.data)
        payload = confirm.get_json()
        self.assertTrue(payload.get("ok"), payload)

        conn = db_mod.get_db()
        try:
            stock = conn.execute(
                """
                SELECT qty_on_hand, unit FROM store_stock_items
                WHERE outlet = 'bar' AND lower(item_name) = lower('Pack Convert Masala')
                """
            ).fetchone()
            self.assertIsNotNone(stock)
            self.assertEqual(stock["unit"], "kg")
            # 2 packs × 0.5 kg = 1 kg stock
            self.assertAlmostEqual(float(stock["qty_on_hand"]), 1.0)
            movement = conn.execute(
                """
                SELECT qty_delta, unit_cost FROM store_stock_movements
                WHERE outlet = 'bar' AND lower(item_name) = lower('Pack Convert Masala')
                ORDER BY id DESC LIMIT 1
                """
            ).fetchone()
            self.assertAlmostEqual(float(movement["qty_delta"]), 1.0)
            # ₹95 / pack ÷ 0.5 kg = ₹190 per kg
            self.assertAlmostEqual(float(movement["unit_cost"]), 190.0)
            variant = conn.execute(
                """
                SELECT approximate_price FROM store_product_variants
                WHERE product_id = ? AND lower(label) = lower('500 gram') AND is_active = 1
                """,
                (product_id,),
            ).fetchone()
            self.assertAlmostEqual(float(variant["approximate_price"]), 95.0)
            product = conn.execute(
                "SELECT approximate_price FROM store_products WHERE id = ?",
                (product_id,),
            ).fetchone()
            self.assertAlmostEqual(float(product["approximate_price"]), 190.0)
        finally:
            conn.close()

        # Ordering in base unit (no pack) still receives 1:1 into stock.
        create2 = self.client.post(
            "/stores/indent?outlet=bar",
            data={
                "outlet": "bar",
                "action": "submit",
                "notes": "No pack inward",
                "item_name": ["Pack Convert Masala"],
                "quantity": ["3"],
                "unit": ["kg"],
                "approximate_price": ["100"],
                "pack_label": [""],
                "pack_qty_in_base": [""],
            },
            follow_redirects=False,
        )
        self.assertEqual(create2.status_code, 302)
        conn = db_mod.get_db()
        try:
            indent2 = conn.execute(
                "SELECT id FROM store_indents WHERE notes = 'No pack inward' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            indent2_id = indent2["id"]
            line2 = conn.execute(
                """
                SELECT id FROM store_indent_lines WHERE indent_id = ?
                """,
                (indent2_id,),
            ).fetchone()
            line2_id = int(line2["id"])
            before = conn.execute(
                """
                SELECT COALESCE(qty_on_hand, 0) AS qty FROM store_stock_items
                WHERE outlet = 'bar' AND lower(item_name) = lower('Pack Convert Masala') AND lower(unit) = 'kg'
                """
            ).fetchone()
            before_qty = float(before["qty"]) if before else 0.0
        finally:
            conn.close()
        self.client.post(
            f"/stores/indent/{indent2_id}/decide",
            data={"outlet": "bar", "decision": "approved", "decision_note": ""},
            follow_redirects=False,
        )
        confirm2 = self.client.post(
            "/stores/purchase-requests/confirm-with-expense",
            json={
                "indent_id": indent2_id,
                "notes": "",
                "lines": [
                    {
                        "line_id": line2_id,
                        "received_qty": 3,
                        "unit_price": 100,
                        "tax_percent": 0,
                    }
                ],
                "date": date.today().isoformat(),
                "description": "Base unit inward",
                "amount": 300,
                "payment_type": "cash",
                "category": "grocery",
                "supplier_id": supplier_id,
            },
        )
        self.assertEqual(confirm2.status_code, 200, confirm2.data)
        self.assertTrue(confirm2.get_json().get("ok"), confirm2.get_json())
        conn = db_mod.get_db()
        try:
            after = conn.execute(
                """
                SELECT qty_on_hand FROM store_stock_items
                WHERE outlet = 'bar' AND lower(item_name) = lower('Pack Convert Masala') AND lower(unit) = 'kg'
                """
            ).fetchone()
            self.assertAlmostEqual(float(after["qty_on_hand"]), before_qty + 3.0)
        finally:
            conn.close()

    def test_indent_to_stock_happy_path(self):
        # Create + submit indent
        resp = self.client.post(
            "/stores/indent?outlet=bar",
            data={
                "outlet": "bar",
                "action": "submit",
                "notes": "Evening bar needs",
                "item_name": ["Onion", "Potato"],
                "quantity": ["10", "24"],
                "unit": ["kg", "kg"],
                "approximate_price": ["30", "20"],
            },
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 302)

        conn = db_mod.get_db()
        try:
            indent = conn.execute(
                "SELECT * FROM store_indents WHERE outlet = 'bar' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            self.assertIsNotNone(indent)
            self.assertEqual(indent["status"], "pending")
            indent_id = indent["id"]
        finally:
            conn.close()

        # Approve
        resp = self.client.post(
            f"/stores/indent/{indent_id}/decide",
            data={"outlet": "bar", "decision": "approved", "decision_note": ""},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 302)

        # Create PR from indent
        resp = self.client.post(
            "/stores/purchase-requests?outlet=bar",
            data={
                "outlet": "bar",
                "action": "create_from_indent",
                "indent_id": str(indent_id),
            },
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 302)

        conn = db_mod.get_db()
        try:
            pr = conn.execute(
                "SELECT * FROM store_purchase_requests WHERE indent_id = ?",
                (indent_id,),
            ).fetchone()
            self.assertIsNotNone(pr)
            pr_id = pr["id"]
        finally:
            conn.close()

        # Receive into stock
        resp = self.client.post(
            f"/stores/purchase-requests/{pr_id}/receive",
            data={"outlet": "bar"},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 302)

        conn = db_mod.get_db()
        try:
            stock = {
                (row["item_name"], row["unit"]): row["qty_on_hand"]
                for row in conn.execute(
                    "SELECT item_name, unit, qty_on_hand FROM store_stock_items WHERE outlet = 'bar'"
                ).fetchall()
            }
            self.assertEqual(stock[("Onion", "kg")], 10)
            self.assertEqual(stock[("Potato", "kg")], 24)
        finally:
            conn.close()

        # Pages render
        for path in (
            "/stores/indent?outlet=bar",
            "/stores/approvals?outlet=bar",
            "/stores/purchase-requests?outlet=bar",
            "/stores/stock?outlet=bar",
            "/stores?outlet=restaurant",
            "/stores?outlet=kitchen",  # legacy alias → restaurant
        ):
            page = self.client.get(path, follow_redirects=True)
            self.assertEqual(page.status_code, 200, path)

        inward_page = self.client.get("/stores/purchase-requests?outlet=bar", follow_redirects=True)
        self.assertIn(b"Stock Inward", inward_page.data)

    def test_stock_inward_confirms_into_stock_with_cash_expense(self):
        from datetime import date

        conn = db_mod.get_db()
        try:
            conn.execute(
                "INSERT INTO suppliers (name) VALUES (?)",
                ("Inward Cash Supplier",),
            )
            supplier_id = conn.execute(
                "SELECT id FROM suppliers WHERE name = 'Inward Cash Supplier'"
            ).fetchone()["id"]
            conn.execute(
                "INSERT INTO cash_ledger_loads (company, load_date, description, amount) VALUES (?,?,?,?)",
                ("HBE", date.today().isoformat(), "Test cash float", 5000),
            )
            conn.commit()
        finally:
            conn.close()

        create = self.client.post(
            "/stores/indent?outlet=bar",
            data={
                "outlet": "bar",
                "action": "submit",
                "notes": "Inward me",
                "item_name": ["Onion", "Potato"],
                "quantity": ["10", "24"],
                "unit": ["kg", "kg"],
                "approximate_price": ["30", "20"],
            },
            follow_redirects=False,
        )
        self.assertEqual(create.status_code, 302)
        conn = db_mod.get_db()
        try:
            indent = conn.execute(
                "SELECT id, indent_no FROM store_indents WHERE notes = 'Inward me' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            self.assertIsNotNone(indent)
            indent_id = indent["id"]
            lines = conn.execute(
                "SELECT id, item_name, quantity FROM store_indent_lines WHERE indent_id = ? ORDER BY id",
                (indent_id,),
            ).fetchall()
            self.assertEqual(len(lines), 2)
            line_ids = [int(row["id"]) for row in lines]
        finally:
            conn.close()

        decide = self.client.post(
            f"/stores/indent/{indent_id}/decide",
            data={"outlet": "bar", "decision": "approved", "decision_note": ""},
            follow_redirects=False,
        )
        self.assertEqual(decide.status_code, 302)

        page = self.client.get(
            f"/stores/purchase-requests?outlet=bar&indent={indent_id}",
            follow_redirects=True,
        )
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Confirm Stock Inward", page.data)
        self.assertIn(b"st-inward-expense-modal", page.data)
        self.assertIn(b"Confirm stock &amp; expense", page.data)

        form_blocked = self.client.post(
            "/stores/purchase-requests?outlet=bar",
            data={
                "outlet": "bar",
                "action": "confirm_stock_inward",
                "indent_id": str(indent_id),
                "notes": "",
                "selected_line": [str(line_ids[0]), str(line_ids[1])],
                f"received_qty_{line_ids[0]}": "10",
                f"received_qty_{line_ids[1]}": "20",
            },
            follow_redirects=True,
        )
        self.assertEqual(form_blocked.status_code, 200)
        self.assertIn(b"expense popup", form_blocked.data)

        empty = self.client.post(
            "/stores/purchase-requests/confirm-with-expense",
            json={
                "indent_id": indent_id,
                "lines": [],
                "date": date.today().isoformat(),
                "description": "Stock inward",
                "amount": 700,
                "payment_type": "cash",
                "category": "grocery",
                "supplier_id": supplier_id,
            },
        )
        self.assertEqual(empty.status_code, 400)
        self.assertIn(b"Select at least one item", empty.data)

        confirm = self.client.post(
            "/stores/purchase-requests/confirm-with-expense",
            json={
                "indent_id": indent_id,
                "notes": "Received evening delivery",
                "lines": [
                    {"line_id": line_ids[0], "received_qty": 10},
                    {"line_id": line_ids[1], "received_qty": 24},
                ],
                "date": date.today().isoformat(),
                "description": "Stock inward cash",
                "amount": 780,
                "payment_type": "cash",
                "category": "grocery",
                "supplier_id": supplier_id,
            },
        )
        self.assertEqual(confirm.status_code, 200)
        payload = confirm.get_json()
        self.assertTrue(payload.get("ok"))
        self.assertIn("/stores/stock", payload.get("redirect", ""))

        conn = db_mod.get_db()
        try:
            status = conn.execute(
                "SELECT status FROM store_indents WHERE id = ?", (indent_id,)
            ).fetchone()["status"]
            self.assertEqual(status, "stocked")
            stock = {
                (row["item_name"], row["unit"]): float(row["qty_on_hand"])
                for row in conn.execute(
                    "SELECT item_name, unit, qty_on_hand FROM store_stock_items WHERE outlet = 'bar'"
                ).fetchall()
            }
            self.assertEqual(stock[("Onion", "kg")], 10.0)
            self.assertEqual(stock[("Potato", "kg")], 24.0)
            movement = conn.execute(
                """
                SELECT COUNT(*) AS c FROM store_stock_movements
                WHERE ref_type = 'stock_inward' AND ref_id = ?
                """,
                (indent_id,),
            ).fetchone()["c"]
            self.assertEqual(int(movement), 2)
            expense = conn.execute(
                """
                SELECT id, amount, payment_type, location, description
                FROM sales_update_expenses
                WHERE id = ?
                """,
                (payload["expense_id"],),
            ).fetchone()
            self.assertIsNotNone(expense)
            self.assertEqual(float(expense["amount"]), 780.0)
            self.assertEqual(expense["payment_type"], "cash")
            self.assertEqual(expense["location"], "Hotel")
            self.assertIn("Stock inward cash", expense["description"])
        finally:
            conn.close()

        gone = self.client.get(
            f"/stores/purchase-requests?outlet=bar&indent={indent_id}",
            follow_redirects=True,
        )
        self.assertEqual(gone.status_code, 200)
        self.assertIn(b"No approved indents waiting", gone.data)

    def test_stock_inward_partial_keeps_remaining_on_page(self):
        from datetime import date

        conn = db_mod.get_db()
        try:
            conn.execute(
                "INSERT INTO suppliers (name) VALUES (?)",
                ("Inward Partial Supplier",),
            )
            supplier_id = conn.execute(
                "SELECT id FROM suppliers WHERE name = 'Inward Partial Supplier'"
            ).fetchone()["id"]
            conn.execute(
                "INSERT INTO cash_ledger_loads (company, load_date, description, amount) VALUES (?,?,?,?)",
                ("HBE", date.today().isoformat(), "Partial inward float", 5000),
            )
            conn.commit()
        finally:
            conn.close()

        create = self.client.post(
            "/stores/indent?outlet=bar",
            data={
                "outlet": "bar",
                "action": "submit",
                "notes": "Partial inward indent",
                "item_name": ["Onion", "Potato"],
                "quantity": ["10", "24"],
                "unit": ["kg", "kg"],
                "approximate_price": ["30", "20"],
            },
            follow_redirects=False,
        )
        self.assertEqual(create.status_code, 302)
        conn = db_mod.get_db()
        try:
            indent = conn.execute(
                "SELECT id FROM store_indents WHERE notes = 'Partial inward indent' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            indent_id = indent["id"]
            lines = conn.execute(
                "SELECT id, item_name FROM store_indent_lines WHERE indent_id = ? ORDER BY id",
                (indent_id,),
            ).fetchall()
            line_ids = [int(row["id"]) for row in lines]
        finally:
            conn.close()

        decide = self.client.post(
            f"/stores/indent/{indent_id}/decide",
            data={"outlet": "bar", "decision": "approved", "decision_note": ""},
            follow_redirects=False,
        )
        self.assertEqual(decide.status_code, 302)

        # Receive only first line fully; leave Potato pending.
        partial = self.client.post(
            "/stores/purchase-requests/confirm-with-expense",
            json={
                "indent_id": indent_id,
                "notes": "First delivery",
                "lines": [{"line_id": line_ids[0], "received_qty": 10}],
                "date": date.today().isoformat(),
                "description": "Partial stock inward",
                "amount": 300,
                "payment_type": "cash",
                "category": "grocery",
                "supplier_id": supplier_id,
            },
        )
        self.assertEqual(partial.status_code, 200)
        payload = partial.get_json()
        self.assertTrue(payload.get("ok"))
        self.assertTrue(payload.get("partial"))
        self.assertIn("/stores/purchase-requests", payload.get("redirect", ""))

        conn = db_mod.get_db()
        try:
            status = conn.execute(
                "SELECT status FROM store_indents WHERE id = ?", (indent_id,)
            ).fetchone()["status"]
            self.assertEqual(status, "approved")
            rows = {
                int(row["id"]): float(row["quantity_received"] or 0)
                for row in conn.execute(
                    "SELECT id, quantity_received FROM store_indent_lines WHERE indent_id = ?",
                    (indent_id,),
                ).fetchall()
            }
            self.assertEqual(rows[line_ids[0]], 10.0)
            self.assertEqual(rows[line_ids[1]], 0.0)
        finally:
            conn.close()

        page = self.client.get(
            f"/stores/purchase-requests?outlet=bar&indent={indent_id}",
            follow_redirects=True,
        )
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'st-inward-item-name">Potato', page.data)
        self.assertNotIn(b'st-inward-item-name">Onion', page.data)

        # Over-remaining should fail.
        over = self.client.post(
            "/stores/purchase-requests/confirm-with-expense",
            json={
                "indent_id": indent_id,
                "lines": [{"line_id": line_ids[1], "received_qty": 25}],
                "date": date.today().isoformat(),
                "description": "Too much",
                "amount": 500,
                "payment_type": "cash",
                "category": "grocery",
                "supplier_id": supplier_id,
            },
        )
        self.assertEqual(over.status_code, 400)

        # Finish remaining.
        finish = self.client.post(
            "/stores/purchase-requests/confirm-with-expense",
            json={
                "indent_id": indent_id,
                "lines": [{"line_id": line_ids[1], "received_qty": 24}],
                "date": date.today().isoformat(),
                "description": "Remainder stock inward",
                "amount": 480,
                "payment_type": "cash",
                "category": "grocery",
                "supplier_id": supplier_id,
            },
        )
        self.assertEqual(finish.status_code, 200)
        finish_payload = finish.get_json()
        self.assertTrue(finish_payload.get("ok"))
        self.assertFalse(finish_payload.get("partial"))
        self.assertIn("/stores/stock", finish_payload.get("redirect", ""))

        conn = db_mod.get_db()
        try:
            status = conn.execute(
                "SELECT status FROM store_indents WHERE id = ?", (indent_id,)
            ).fetchone()["status"]
            self.assertEqual(status, "stocked")
        finally:
            conn.close()

        gone = self.client.get(
            f"/stores/purchase-requests?outlet=bar&indent={indent_id}",
            follow_redirects=True,
        )
        self.assertEqual(gone.status_code, 200)
        self.assertIn(b"No approved indents waiting", gone.data)

    def test_stock_inward_confirms_into_stock_with_credit_expense(self):
        from datetime import date

        conn = db_mod.get_db()
        try:
            conn.execute(
                "INSERT INTO suppliers (name) VALUES (?)",
                ("Inward Credit Supplier",),
            )
            supplier_id = conn.execute(
                "SELECT id FROM suppliers WHERE name = 'Inward Credit Supplier'"
            ).fetchone()["id"]
            conn.commit()
        finally:
            conn.close()

        create = self.client.post(
            "/stores/indent?outlet=bar",
            data={
                "outlet": "bar",
                "action": "submit",
                "notes": "Inward credit",
                "item_name": ["Tomato"],
                "quantity": ["5"],
                "unit": ["kg"],
                "approximate_price": ["40"],
            },
            follow_redirects=False,
        )
        self.assertEqual(create.status_code, 302)
        conn = db_mod.get_db()
        try:
            indent = conn.execute(
                "SELECT id FROM store_indents WHERE notes = 'Inward credit' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            indent_id = indent["id"]
            line_id = conn.execute(
                "SELECT id FROM store_indent_lines WHERE indent_id = ?",
                (indent_id,),
            ).fetchone()["id"]
        finally:
            conn.close()

        decide = self.client.post(
            f"/stores/indent/{indent_id}/decide",
            data={"outlet": "bar", "decision": "approved", "decision_note": ""},
            follow_redirects=False,
        )
        self.assertEqual(decide.status_code, 302)

        confirm = self.client.post(
            "/stores/purchase-requests/confirm-with-expense",
            json={
                "indent_id": indent_id,
                "notes": "credit delivery",
                "lines": [{"line_id": int(line_id), "received_qty": 5}],
                "date": date.today().isoformat(),
                "description": "Stock inward credit",
                "amount": 200,
                "payment_type": "credit",
                "category": "grocery",
                "supplier_id": supplier_id,
            },
        )
        self.assertEqual(confirm.status_code, 200)
        payload = confirm.get_json()
        self.assertTrue(payload.get("ok"))
        expense_id = payload["expense_id"]

        conn = db_mod.get_db()
        try:
            status = conn.execute(
                "SELECT status FROM store_indents WHERE id = ?", (indent_id,)
            ).fetchone()["status"]
            self.assertEqual(status, "stocked")
            expense = conn.execute(
                "SELECT amount, payment_type, location FROM sales_update_expenses WHERE id = ?",
                (expense_id,),
            ).fetchone()
            self.assertEqual(float(expense["amount"]), 200.0)
            self.assertEqual(expense["payment_type"], "credit")
            self.assertEqual(expense["location"], "Hotel")
            verified = conn.execute(
                """
                SELECT COALESCE(SUM(amount), 0) AS total
                FROM purchase_verification_allocations
                WHERE expense_id = ?
                """,
                (expense_id,),
            ).fetchone()["total"]
            self.assertEqual(float(verified), 200.0)
            pending = self.app_mod._pending_purchase_verifications(conn)
            self.assertFalse(any(int(row["id"]) == int(expense_id) for row in pending))
            outstanding = self.app_mod._outstanding_credit_expenses(conn)
            match = [row for row in outstanding if int(row["id"]) == int(expense_id)]
            self.assertEqual(len(match), 1)
            self.assertEqual(float(match[0]["balance"]), 200.0)
            stock_qty = conn.execute(
                """
                SELECT qty_on_hand FROM store_stock_items
                WHERE outlet = 'bar' AND item_name = 'Tomato' AND unit = 'kg'
                """
            ).fetchone()["qty_on_hand"]
            self.assertEqual(float(stock_qty), 5.0)
        finally:
            conn.close()

    def test_stock_inward_credit_over_approved_goes_to_purchase_verification(self):
        from datetime import date

        conn = db_mod.get_db()
        try:
            conn.execute(
                "INSERT INTO suppliers (name) VALUES (?)",
                ("Inward Over Approved Supplier",),
            )
            supplier_id = conn.execute(
                "SELECT id FROM suppliers WHERE name = 'Inward Over Approved Supplier'"
            ).fetchone()["id"]
            conn.commit()
        finally:
            conn.close()

        create = self.client.post(
            "/stores/indent?outlet=bar",
            data={
                "outlet": "bar",
                "action": "submit",
                "notes": "Inward over approved",
                "item_name": ["Potato"],
                "quantity": ["5"],
                "unit": ["kg"],
                "approximate_price": ["40"],
            },
            follow_redirects=False,
        )
        self.assertEqual(create.status_code, 302)
        conn = db_mod.get_db()
        try:
            indent = conn.execute(
                "SELECT id FROM store_indents WHERE notes = 'Inward over approved' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            indent_id = indent["id"]
            line_id = conn.execute(
                "SELECT id FROM store_indent_lines WHERE indent_id = ?",
                (indent_id,),
            ).fetchone()["id"]
        finally:
            conn.close()

        decide = self.client.post(
            f"/stores/indent/{indent_id}/decide",
            data={"outlet": "bar", "decision": "approved", "decision_note": ""},
            follow_redirects=False,
        )
        self.assertEqual(decide.status_code, 302)

        # Approved total = 5 × 40 = 200; amount 201 must not auto-verify.
        confirm = self.client.post(
            "/stores/purchase-requests/confirm-with-expense",
            json={
                "indent_id": indent_id,
                "notes": "over price delivery",
                "lines": [{"line_id": int(line_id), "received_qty": 5}],
                "date": date.today().isoformat(),
                "description": "Stock inward over approved",
                "amount": 201,
                "payment_type": "credit",
                "category": "grocery",
                "supplier_id": supplier_id,
            },
        )
        self.assertEqual(confirm.status_code, 200)
        payload = confirm.get_json()
        self.assertTrue(payload.get("ok"))
        expense_id = payload["expense_id"]

        conn = db_mod.get_db()
        try:
            status = conn.execute(
                "SELECT status FROM store_indents WHERE id = ?", (indent_id,)
            ).fetchone()["status"]
            self.assertEqual(status, "stocked")
            expense = conn.execute(
                "SELECT amount, payment_type FROM sales_update_expenses WHERE id = ?",
                (expense_id,),
            ).fetchone()
            self.assertEqual(float(expense["amount"]), 201.0)
            self.assertEqual(expense["payment_type"], "credit")
            verified = conn.execute(
                """
                SELECT COALESCE(SUM(amount), 0) AS total
                FROM purchase_verification_allocations
                WHERE expense_id = ?
                """,
                (expense_id,),
            ).fetchone()["total"]
            self.assertEqual(float(verified), 0.0)
            pending = self.app_mod._pending_purchase_verifications(conn)
            self.assertTrue(any(int(row["id"]) == int(expense_id) for row in pending))
            outstanding = self.app_mod._outstanding_credit_expenses(conn)
            self.assertFalse(any(int(row["id"]) == int(expense_id) for row in outstanding))
        finally:
            conn.close()

    def test_stock_inward_rejects_non_approved(self):
        from datetime import date

        conn = db_mod.get_db()
        try:
            conn.execute(
                "INSERT INTO suppliers (name) VALUES (?)",
                ("Inward Reject Supplier",),
            )
            supplier_id = conn.execute(
                "SELECT id FROM suppliers WHERE name = 'Inward Reject Supplier'"
            ).fetchone()["id"]
            conn.commit()
        finally:
            conn.close()

        create = self.client.post(
            "/stores/indent?outlet=bar",
            data={
                "outlet": "bar",
                "action": "submit",
                "notes": "Still pending",
                "item_name": ["Onion"],
                "quantity": ["1"],
                "unit": ["kg"],
                "approximate_price": ["10"],
            },
            follow_redirects=False,
        )
        self.assertEqual(create.status_code, 302)
        conn = db_mod.get_db()
        try:
            indent = conn.execute(
                "SELECT id FROM store_indents WHERE notes = 'Still pending' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            indent_id = indent["id"]
            line_id = conn.execute(
                "SELECT id FROM store_indent_lines WHERE indent_id = ?",
                (indent_id,),
            ).fetchone()["id"]
        finally:
            conn.close()

        bad = self.client.post(
            "/stores/purchase-requests/confirm-with-expense",
            json={
                "indent_id": indent_id,
                "lines": [{"line_id": int(line_id), "received_qty": 1}],
                "date": date.today().isoformat(),
                "description": "Should fail",
                "amount": 10,
                "payment_type": "credit",
                "category": "grocery",
                "supplier_id": supplier_id,
            },
        )
        self.assertEqual(bad.status_code, 400)
        self.assertIn(b"Select an approved indent", bad.data)

    def test_indent_approved_view_includes_approver(self):
        create = self.client.post(
            "/stores/indent?outlet=bar",
            data={
                "outlet": "bar",
                "action": "submit",
                "notes": "Approve me",
                "item_name": ["Onion"],
                "quantity": ["1"],
                "unit": ["kg"],
                "approximate_price": ["10"],
            },
            follow_redirects=False,
        )
        self.assertEqual(create.status_code, 302)
        conn = db_mod.get_db()
        try:
            indent = conn.execute(
                "SELECT id FROM store_indents WHERE notes = 'Approve me' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            self.assertIsNotNone(indent)
            indent_id = indent["id"]
        finally:
            conn.close()

        decide = self.client.post(
            f"/stores/indent/{indent_id}/decide",
            data={"outlet": "bar", "decision": "approved", "decision_note": ""},
            follow_redirects=False,
        )
        self.assertEqual(decide.status_code, 302)

        page = self.client.get("/stores/indent?outlet=bar&view=approved")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'"decided_by_name": "Administrator"', page.data)
        self.assertIn(b'"decided_by_username": "admin"', page.data)
        self.assertIn(b'"decided_at":', page.data)

    def test_indent_defaults_to_all_outlet(self):
        page = self.client.get("/stores/indent")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'id="st-outlet-value">All</span>', page.data)
        self.assertIn(b'data-value="both"', page.data)
        self.assertIn(b"Pending Approval", page.data)
        self.assertIn(b"Approved", page.data)
        self.assertIn(b"Rejected", page.data)
        self.assertIn(b"cp-view-tabs", page.data)

    def test_indent_rejected_tab_allows_edit_and_resubmit(self):
        create = self.client.post(
            "/stores/indent?outlet=bar",
            data={
                "outlet": "bar",
                "action": "submit",
                "notes": "Reject then fix",
                "item_name": ["Onion"],
                "quantity": ["1"],
                "unit": ["kg"],
                "approximate_price": ["10"],
            },
            follow_redirects=False,
        )
        self.assertEqual(create.status_code, 302)
        conn = db_mod.get_db()
        try:
            indent = conn.execute(
                "SELECT id FROM store_indents WHERE notes = 'Reject then fix' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            self.assertIsNotNone(indent)
            indent_id = indent["id"]
        finally:
            conn.close()

        self.client.post(
            f"/stores/indent/{indent_id}/decide",
            data={"outlet": "bar", "decision": "rejected", "decision_note": "Wrong qty"},
            follow_redirects=False,
        )

        rejected_page = self.client.get("/stores/indent?outlet=bar&view=rejected")
        self.assertEqual(rejected_page.status_code, 200)
        self.assertIn(b"Reject then fix", rejected_page.data)
        self.assertIn(b"Wrong qty", rejected_page.data)
        self.assertIn(b'data-st-edit-indent="%d"' % indent_id, rejected_page.data)

        save = self.client.post(
            f"/stores/indent?outlet=bar&edit={indent_id}",
            data={
                "outlet": "bar",
                "indent_id": str(indent_id),
                "action": "save",
                "notes": "Reject then fix",
                "item_name": ["Onion"],
                "quantity": ["4"],
                "unit": ["kg"],
                "approximate_price": ["10"],
            },
            follow_redirects=False,
        )
        self.assertEqual(save.status_code, 302)
        self.assertIn("view=pending", save.headers.get("Location", ""))

        conn = db_mod.get_db()
        try:
            row = conn.execute(
                "SELECT status, decision_note, decided_at FROM store_indents WHERE id = ?",
                (indent_id,),
            ).fetchone()
            self.assertEqual(row["status"], "pending")
            self.assertEqual(row["decision_note"] or "", "")
            self.assertFalse(row["decided_at"])
            qty = conn.execute(
                "SELECT quantity FROM store_indent_lines WHERE indent_id = ?",
                (indent_id,),
            ).fetchone()
            self.assertEqual(float(qty["quantity"]), 4.0)
        finally:
            conn.close()

        pending_page = self.client.get("/stores/indent?outlet=bar&view=pending")
        self.assertIn(b"Reject then fix", pending_page.data)
        rejected_again = self.client.get("/stores/indent?outlet=bar&view=rejected")
        self.assertNotIn(b"Reject then fix", rejected_again.data)

    def test_stores_outlet_filter_includes_all(self):
        for path in (
            "/stores/approvals",
            "/stores/purchase-requests",
            "/stores/stock",
        ):
            page = self.client.get(path)
            self.assertEqual(page.status_code, 200, path)
            self.assertIn(b'data-value="both"', page.data, path)
            self.assertIn(b">All</button>", page.data, path)

    def test_approvals_table_is_sortable(self):
        create = self.client.post(
            "/stores/indent?outlet=bar",
            data={
                "outlet": "bar",
                "action": "submit",
                "notes": "Sort me",
                "item_name": ["Onion"],
                "quantity": ["2"],
                "unit": ["kg"],
                "approximate_price": ["10"],
            },
            follow_redirects=False,
        )
        self.assertEqual(create.status_code, 302)
        page = self.client.get("/stores/approvals?outlet=bar")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'id="st-approvals-pending-table"', page.data)
        self.assertIn(b"pl-sortable", page.data)
        self.assertIn(b'data-sort="indent"', page.data)
        self.assertIn(b'data-sort="submitted"', page.data)
        self.assertIn(b'data-sort-row', page.data)
        self.assertIn(b"pl-list-panel--scroll", page.data)
        self.assertIn(b"hbe-scroll-panel", page.data)
        self.assertIn(b"Click to sort", page.data)
        self.assertIn(b"Approx. price", page.data)
        self.assertIn(b"\xe2\x82\xb920", page.data)  # ₹20 (2 × 10)
        self.assertIn(b"Indents awaiting your approval", page.data)
        self.assertIn(b"st-appr-btn--approve", page.data)
        self.assertRegex(page.data.decode("utf-8"), r"\d{1,2} [A-Za-z]+")
        self.assertRegex(page.data.decode("utf-8"), r"\d{1,2}:\d{2} (AM|PM)")
        self.assertNotRegex(page.data.decode("utf-8", errors="ignore"), r">\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}<")
        self.assertNotIn(b"st-appr-icon--cal", page.data)

    def test_home_shows_approvals_notification_only_for_approvers(self):
        create = self.client.post(
            "/stores/indent?outlet=bar",
            data={
                "outlet": "bar",
                "action": "submit",
                "notes": "Notify approvers",
                "item_name": ["Onion"],
                "quantity": ["2"],
                "unit": ["kg"],
                "approximate_price": ["10"],
            },
            follow_redirects=False,
        )
        self.assertEqual(create.status_code, 302)

        home = self.client.get("/home")
        self.assertEqual(home.status_code, 200)
        self.assertIn(b"Indents awaiting approval", home.data)
        self.assertIn(b"has-unread", home.data)
        self.assertIn(b'href="/stores/approvals"', home.data)

        viewer = {
            "id": self.admin_id,
            "username": "storeclerk",
            "full_name": "Store Clerk",
            "is_admin": False,
            "is_active": True,
            "dashboard_access": {"stores"},
            "stores_access": {"indent", "stock"},
            "sales_analytics_access": set(),
            "user_access": set(),
            "payroll_access": set(),
            "accounts_access": set(),
        }
        with mock.patch.object(self.app_mod, "get_current_user", return_value=viewer):
            denied = self.client.get("/home")
        self.assertEqual(denied.status_code, 200)
        self.assertNotIn(b"Indents awaiting approval", denied.data)
        self.assertNotIn(b"has-unread", denied.data)

    def test_approvals_reject_popup_and_reopen(self):
        create = self.client.post(
            "/stores/indent?outlet=bar",
            data={
                "outlet": "bar",
                "action": "submit",
                "notes": "Needs decision",
                "item_name": ["Onion"],
                "quantity": ["3"],
                "unit": ["kg"],
                "approximate_price": ["12"],
            },
            follow_redirects=False,
        )
        self.assertEqual(create.status_code, 302)
        page = self.client.get("/stores/approvals?outlet=bar")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'data-st-reject-open', page.data)
        self.assertIn(b'id="st-reject-modal"', page.data)
        self.assertIn(b'name="decision_note"', page.data)
        self.assertIn(b'name="decision" value="approved"', page.data)

        conn = db_mod.get_db()
        try:
            indent = conn.execute(
                "SELECT id FROM store_indents WHERE notes = 'Needs decision' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            self.assertIsNotNone(indent)
            indent_id = indent["id"]
        finally:
            conn.close()

        blocked = self.client.post(
            f"/stores/indent/{indent_id}/decide",
            data={"outlet": "bar", "decision": "rejected", "decision_note": ""},
            follow_redirects=False,
        )
        self.assertEqual(blocked.status_code, 302)
        conn = db_mod.get_db()
        try:
            row = conn.execute(
                "SELECT status FROM store_indents WHERE id = ?",
                (indent_id,),
            ).fetchone()
            self.assertEqual(row["status"], "pending")
        finally:
            conn.close()

        rejected = self.client.post(
            f"/stores/indent/{indent_id}/decide",
            data={"outlet": "bar", "decision": "rejected", "decision_note": "Out of season"},
            follow_redirects=False,
        )
        self.assertEqual(rejected.status_code, 302)
        conn = db_mod.get_db()
        try:
            row = conn.execute(
                "SELECT status, decision_note FROM store_indents WHERE id = ?",
                (indent_id,),
            ).fetchone()
            self.assertEqual(row["status"], "rejected")
            self.assertEqual(row["decision_note"], "Out of season")
        finally:
            conn.close()

        recent = self.client.get("/stores/approvals?outlet=bar")
        self.assertIn(b"Return to waiting", recent.data)

        reopened = self.client.post(
            f"/stores/indent/{indent_id}/reopen",
            data={"outlet": "bar"},
            follow_redirects=False,
        )
        self.assertEqual(reopened.status_code, 302)
        conn = db_mod.get_db()
        try:
            row = conn.execute(
                "SELECT status, decision_note, decided_at FROM store_indents WHERE id = ?",
                (indent_id,),
            ).fetchone()
            self.assertEqual(row["status"], "pending")
            self.assertEqual(row["decision_note"] or "", "")
            self.assertFalse(row["decided_at"])
        finally:
            conn.close()

        waiting = self.client.get("/stores/approvals?outlet=bar")
        self.assertIn(b"Needs decision", waiting.data)

    def test_indent_list_view_filters_by_status(self):
        draft = self.client.post(
            "/stores/indent?outlet=bar",
            data={
                "outlet": "bar",
                "action": "save",
                "notes": "Draft only",
                "item_name": ["Onion"],
                "quantity": ["1"],
                "unit": ["kg"],
                "approximate_price": ["10"],
            },
            follow_redirects=False,
        )
        self.assertEqual(draft.status_code, 302)
        pending = self.client.post(
            "/stores/indent?outlet=bar",
            data={
                "outlet": "bar",
                "action": "submit",
                "notes": "Waiting",
                "item_name": ["Onion"],
                "quantity": ["2"],
                "unit": ["kg"],
                "approximate_price": ["20"],
            },
            follow_redirects=False,
        )
        self.assertEqual(pending.status_code, 302)

        conn = db_mod.get_db()
        try:
            waiting = conn.execute(
                "SELECT id FROM store_indents WHERE notes = 'Waiting' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            self.assertIsNotNone(waiting)
            conn.execute(
                "UPDATE store_indents SET status = 'approved' WHERE id = ?",
                (waiting["id"],),
            )
            conn.commit()
        finally:
            conn.close()

        pending_page = self.client.get("/stores/indent?outlet=bar&view=pending")
        self.assertEqual(pending_page.status_code, 200)
        self.assertIn(b"Draft only", pending_page.data)
        self.assertNotIn(b"Waiting", pending_page.data)

        approved_page = self.client.get("/stores/indent?outlet=bar&view=approved")
        self.assertEqual(approved_page.status_code, 200)
        self.assertIn(b"Waiting", approved_page.data)
        self.assertNotIn(b"Draft only", approved_page.data)
        self.assertIn(b"Download PO", approved_page.data)
        self.assertIn(b"/purchase-order", approved_page.data)

    def test_indent_purchase_order_download(self):
        create = self.client.post(
            "/stores/indent?outlet=bar",
            data={
                "outlet": "bar",
                "action": "submit",
                "notes": "PO export",
                "item_name": ["Onion", "Potato"],
                "quantity": ["10", "5"],
                "unit": ["kg", "kg"],
                "approximate_price": ["30", "20"],
            },
            follow_redirects=False,
        )
        self.assertEqual(create.status_code, 302)

        conn = db_mod.get_db()
        try:
            indent = conn.execute(
                "SELECT id, indent_no FROM store_indents WHERE notes = 'PO export' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            self.assertIsNotNone(indent)
            indent_id = indent["id"]
            indent_no = indent["indent_no"]
            conn.execute(
                "UPDATE store_indents SET status = 'approved' WHERE id = ?",
                (indent_id,),
            )
            conn.commit()
        finally:
            conn.close()

        approved_page = self.client.get("/stores/indent?outlet=bar&view=approved")
        self.assertEqual(approved_page.status_code, 200)
        self.assertIn(indent_no.encode(), approved_page.data)
        self.assertIn(f"/stores/indent/{indent_id}/purchase-order".encode(), approved_page.data)

        po = self.client.get(f"/stores/indent/{indent_id}/purchase-order")
        self.assertEqual(po.status_code, 200)
        self.assertIn(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            po.content_type,
        )
        self.assertTrue(po.data[:2] == b"PK")

        pending_blocked = self.client.post(
            "/stores/indent?outlet=bar",
            data={
                "outlet": "bar",
                "action": "save",
                "notes": "Draft blocked",
                "item_name": ["Onion"],
                "quantity": ["1"],
                "unit": ["kg"],
                "approximate_price": ["10"],
            },
            follow_redirects=False,
        )
        self.assertEqual(pending_blocked.status_code, 302)
        conn = db_mod.get_db()
        try:
            draft = conn.execute(
                "SELECT id FROM store_indents WHERE notes = 'Draft blocked' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            self.assertIsNotNone(draft)
            draft_id = draft["id"]
        finally:
            conn.close()
        blocked = self.client.get(
            f"/stores/indent/{draft_id}/purchase-order",
            follow_redirects=False,
        )
        self.assertEqual(blocked.status_code, 302)

    def test_indent_product_list_filters_by_outlet(self):
        conn = db_mod.get_db()
        try:
            db_mod.ensure_stores_schema(conn)
            cat = conn.execute(
                "SELECT id FROM store_product_categories WHERE is_active = 1 ORDER BY id LIMIT 1"
            ).fetchone()
            self.assertIsNotNone(cat)
            cat_id = cat["id"]
            conn.execute(
                """
                INSERT INTO store_products
                    (category_id, name, default_unit, outlet, is_active, sort_order, updated_at)
                VALUES (?, 'Bar Only Mixer', 'bottle', 'bar', 1, 9990, datetime('now','localtime'))
                """,
                (cat_id,),
            )
            conn.execute(
                """
                INSERT INTO store_products
                    (category_id, name, default_unit, outlet, is_active, sort_order, updated_at)
                VALUES (?, 'Restaurant Only Herb', 'bunch', 'restaurant', 1, 9991, datetime('now','localtime'))
                """,
                (cat_id,),
            )
            conn.execute(
                """
                INSERT INTO store_products
                    (category_id, name, default_unit, outlet, is_active, sort_order, updated_at)
                VALUES (?, 'Shared Oil', 'liter', 'both', 1, 9992, datetime('now','localtime'))
                """,
                (cat_id,),
            )
            conn.commit()
        finally:
            conn.close()

        bar_form = self.client.get("/stores/indent?outlet=bar&focus=form")
        self.assertEqual(bar_form.status_code, 200)
        self.assertIn(b"Bar Only Mixer", bar_form.data)
        self.assertIn(b"Shared Oil", bar_form.data)
        self.assertNotIn(b"Restaurant Only Herb", bar_form.data)
        # Create form: Bar/Restaurant only — All is list/view filter.
        self.assertNotIn(b'data-value="both"', bar_form.data)
        self.assertIn(b'data-value="bar"', bar_form.data)
        self.assertIn(b'data-value="restaurant"', bar_form.data)

        rest_form = self.client.get("/stores/indent?outlet=restaurant&focus=form")
        self.assertEqual(rest_form.status_code, 200)
        self.assertIn(b"Restaurant Only Herb", rest_form.data)
        self.assertIn(b"Shared Oil", rest_form.data)
        self.assertNotIn(b"Bar Only Mixer", rest_form.data)
        self.assertNotIn(b'data-value="both"', rest_form.data)

        # No default outlet — user must select Bar or Restaurant.
        unset_form = self.client.get("/stores/indent?focus=form")
        self.assertEqual(unset_form.status_code, 200)
        self.assertIn(b"Select outlet", unset_form.data)
        self.assertIn(b"is-placeholder", unset_form.data)
        self.assertNotIn(b"Bar Only Mixer", unset_form.data)
        self.assertNotIn(b"Restaurant Only Herb", unset_form.data)
        self.assertNotIn(b'data-value="both"', unset_form.data)

        both_form = self.client.get("/stores/indent?outlet=both&focus=form")
        self.assertEqual(both_form.status_code, 200)
        self.assertIn(b"Select outlet", both_form.data)
        self.assertNotIn(b"Bar Only Mixer", both_form.data)
        self.assertNotIn(b"Restaurant Only Herb", both_form.data)

    def test_indent_list_view_edit_delete_actions(self):
        create = self.client.post(
            "/stores/indent?outlet=bar",
            data={
                "outlet": "bar",
                "action": "save",
                "notes": "Editable draft",
                "item_name": ["Onion"],
                "quantity": ["2"],
                "unit": ["kg"],
                "approximate_price": ["40"],
            },
            follow_redirects=False,
        )
        self.assertEqual(create.status_code, 302)

        conn = db_mod.get_db()
        try:
            indent = conn.execute(
                "SELECT id, indent_no FROM store_indents WHERE outlet = 'bar' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            self.assertIsNotNone(indent)
            indent_id = indent["id"]
            line = conn.execute(
                "SELECT approximate_price FROM store_indent_lines WHERE indent_id = ?",
                (indent_id,),
            ).fetchone()
            self.assertEqual(float(line["approximate_price"]), 40.0)
        finally:
            conn.close()

        listing = self.client.get("/stores/indent?outlet=bar")
        self.assertEqual(listing.status_code, 200)
        self.assertIn(b'data-st-view-indent=', listing.data)
        self.assertIn(b'id="st-indent-view-modal"', listing.data)
        self.assertIn(b'data-st-edit-indent=', listing.data)
        self.assertIn(b'id="st-indent-edit-modal"', listing.data)
        # Soft-nav only executes scripts inside .de-main-wrapper; stores.js must
        # appear before the shell close scripts or View/Edit never bind.
        stores_js_idx = listing.data.find(b"/static/stores.js")
        shell_nav_idx = listing.data.find(b"/static/de_workspace_nav.js")
        self.assertGreaterEqual(stores_js_idx, 0)
        self.assertGreaterEqual(shell_nav_idx, 0)
        self.assertLess(stores_js_idx, shell_nav_idx)
        self.assertIn(b'Approximate Price', listing.data)
        self.assertIn(b'pl-sortable', listing.data)
        self.assertIn(b'data-sort="indent"', listing.data)
        self.assertIn(b'data-tip="Edit"', listing.data)
        self.assertIn(b'data-tip="Delete"', listing.data)

        edit_page = self.client.get(f"/stores/indent?outlet=bar&edit={indent_id}&focus=form")
        self.assertEqual(edit_page.status_code, 200)
        self.assertIn(b'id="st-indent-edit-modal"', edit_page.data)
        self.assertIn(f'data-st-open-edit="{indent_id}"'.encode(), edit_page.data)
        self.assertIn(b"Edit indent", edit_page.data)
        self.assertIn(b"Onion", edit_page.data)

        update = self.client.post(
            "/stores/indent?outlet=bar",
            data={
                "outlet": "bar",
                "indent_id": str(indent_id),
                "action": "save",
                "notes": "Updated note",
                "item_name": ["Potato"],
                "quantity": ["5"],
                "unit": ["kg"],
                "approximate_price": ["55"],
            },
            follow_redirects=True,
        )
        self.assertEqual(update.status_code, 200)
        self.assertIn(b"Indent sent for approval", update.data)
        self.assertIn(b"Waiting approval", update.data)

        delete = self.client.get(
            f"/stores/indent/{indent_id}/delete?outlet=bar",
            follow_redirects=True,
        )
        self.assertEqual(delete.status_code, 200)
        self.assertIn(b"Deleted", delete.data)
        conn = db_mod.get_db()
        try:
            gone = conn.execute(
                "SELECT id FROM store_indents WHERE id = ?", (indent_id,)
            ).fetchone()
            self.assertIsNone(gone)
        finally:
            conn.close()

    def test_edit_save_sends_draft_for_approval(self):
        create = self.client.post(
            "/stores/indent?outlet=bar",
            data={
                "outlet": "bar",
                "action": "save",
                "notes": "Editable draft",
                "item_name": ["Onion"],
                "quantity": ["2"],
                "unit": ["kg"],
                "approximate_price": ["40"],
            },
            follow_redirects=False,
        )
        self.assertEqual(create.status_code, 302)

        conn = db_mod.get_db()
        try:
            indent = conn.execute(
                "SELECT id, status FROM store_indents WHERE outlet = 'bar' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            self.assertIsNotNone(indent)
            self.assertEqual(indent["status"], "draft")
            indent_id = indent["id"]
        finally:
            conn.close()

        # Edit modal Save is the final save → Waiting approval.
        update = self.client.post(
            "/stores/indent?outlet=bar",
            data={
                "outlet": "bar",
                "indent_id": str(indent_id),
                "action": "save",
                "notes": "Ready for approval",
                "item_name": ["Onion"],
                "quantity": ["3"],
                "unit": ["kg"],
                "approximate_price": ["45"],
            },
            follow_redirects=True,
        )
        self.assertEqual(update.status_code, 200)
        self.assertIn(b"Indent sent for approval", update.data)

        conn = db_mod.get_db()
        try:
            row = conn.execute(
                "SELECT status, notes, submitted_at FROM store_indents WHERE id = ?",
                (indent_id,),
            ).fetchone()
            self.assertEqual(row["status"], "pending")
            self.assertEqual(row["notes"], "Ready for approval")
            self.assertTrue(row["submitted_at"])
            line = conn.execute(
                "SELECT quantity, approximate_price FROM store_indent_lines WHERE indent_id = ?",
                (indent_id,),
            ).fetchone()
            self.assertEqual(float(line["quantity"]), 3.0)
            self.assertEqual(float(line["approximate_price"]), 45.0)
        finally:
            conn.close()

        # Soft-nav can drop the hidden field — ?edit= on the action URL must still update.
        update_via_query = self.client.post(
            f"/stores/indent?outlet=bar&edit={indent_id}",
            data={
                "outlet": "bar",
                "action": "save",
                "notes": "Via query edit id",
                "item_name": ["Onion"],
                "quantity": ["4"],
                "unit": ["kg"],
                "approximate_price": ["50"],
            },
            follow_redirects=True,
        )
        self.assertEqual(update_via_query.status_code, 200)
        self.assertIn(b"Indent updated", update_via_query.data)
        conn = db_mod.get_db()
        try:
            row = conn.execute(
                "SELECT status, notes FROM store_indents WHERE id = ?",
                (indent_id,),
            ).fetchone()
            self.assertEqual(row["status"], "pending")
            self.assertEqual(row["notes"], "Via query edit id")
            count = conn.execute(
                "SELECT COUNT(*) AS c FROM store_indents WHERE outlet = 'bar'"
            ).fetchone()["c"]
            self.assertEqual(count, 1)
        finally:
            conn.close()

    def test_admin_delete_approved_indent_removes_non_inwarded_only(self):
        from datetime import date

        conn = db_mod.get_db()
        try:
            conn.execute(
                "INSERT INTO suppliers (name) VALUES (?)",
                ("Approved Delete Supplier",),
            )
            supplier_id = conn.execute(
                "SELECT id FROM suppliers WHERE name = 'Approved Delete Supplier'"
            ).fetchone()["id"]
            conn.execute(
                "INSERT INTO cash_ledger_loads (company, load_date, description, amount) VALUES (?,?,?,?)",
                ("HBE", date.today().isoformat(), "Approved delete float", 5000),
            )
            conn.commit()
        finally:
            conn.close()

        create = self.client.post(
            "/stores/indent?outlet=bar",
            data={
                "outlet": "bar",
                "action": "submit",
                "notes": "Admin delete approved partial",
                "item_name": ["Onion", "Potato", "Tomato"],
                "quantity": ["10", "24", "8"],
                "unit": ["kg", "kg", "kg"],
                "approximate_price": ["30", "20", "15"],
            },
            follow_redirects=False,
        )
        self.assertEqual(create.status_code, 302)
        conn = db_mod.get_db()
        try:
            indent = conn.execute(
                "SELECT id, indent_no FROM store_indents WHERE notes = 'Admin delete approved partial' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            indent_id = indent["id"]
            lines = {
                row["item_name"]: int(row["id"])
                for row in conn.execute(
                    "SELECT id, item_name FROM store_indent_lines WHERE indent_id = ?",
                    (indent_id,),
                ).fetchall()
            }
        finally:
            conn.close()

        decide = self.client.post(
            f"/stores/indent/{indent_id}/decide",
            data={"outlet": "bar", "decision": "approved", "decision_note": ""},
            follow_redirects=False,
        )
        self.assertEqual(decide.status_code, 302)

        # Fully receive Onion; partially receive Potato (10 of 24); leave Tomato pending.
        partial = self.client.post(
            "/stores/purchase-requests/confirm-with-expense",
            json={
                "indent_id": indent_id,
                "notes": "First delivery before cancel",
                "lines": [
                    {"line_id": lines["Onion"], "received_qty": 10},
                    {"line_id": lines["Potato"], "received_qty": 10},
                ],
                "date": date.today().isoformat(),
                "description": "Partial before approved delete",
                "amount": 500,
                "payment_type": "cash",
                "category": "grocery",
                "supplier_id": supplier_id,
            },
        )
        self.assertEqual(partial.status_code, 200)
        self.assertTrue(partial.get_json().get("ok"))

        conn = db_mod.get_db()
        try:
            stock_before = {
                (row["item_name"], row["unit"]): float(row["qty_on_hand"])
                for row in conn.execute(
                    "SELECT item_name, unit, qty_on_hand FROM store_stock_items WHERE outlet = 'bar'"
                ).fetchall()
            }
            movements_before = conn.execute(
                """
                SELECT COUNT(*) AS c FROM store_stock_movements
                WHERE ref_type = 'stock_inward' AND ref_id = ?
                """,
                (indent_id,),
            ).fetchone()["c"]
        finally:
            conn.close()
        self.assertEqual(stock_before[("Onion", "kg")], 10.0)
        self.assertEqual(stock_before[("Potato", "kg")], 10.0)
        self.assertNotIn(("Tomato", "kg"), stock_before)

        approved_list = self.client.get("/stores/indent?outlet=bar&view=approved")
        self.assertEqual(approved_list.status_code, 200)
        self.assertIn(b'data-tip="Delete remaining"', approved_list.data)
        self.assertIn(b"Already inwarded stock will not be changed", approved_list.data)

        delete = self.client.get(
            f"/stores/indent/{indent_id}/delete?outlet=bar",
            follow_redirects=True,
        )
        self.assertEqual(delete.status_code, 200)
        self.assertIn(b"Inwarded stock unchanged", delete.data)

        conn = db_mod.get_db()
        try:
            indent_row = conn.execute(
                "SELECT status FROM store_indents WHERE id = ?", (indent_id,)
            ).fetchone()
            self.assertIsNotNone(indent_row)
            # Remains approved so PO download stays available; open qty is gone.
            self.assertEqual(indent_row["status"], "approved")
            line_rows = {
                row["item_name"]: (
                    float(row["quantity"]),
                    float(row["quantity_received"] or 0),
                )
                for row in conn.execute(
                    "SELECT item_name, quantity, quantity_received FROM store_indent_lines WHERE indent_id = ?",
                    (indent_id,),
                ).fetchall()
            }
            self.assertEqual(set(line_rows), {"Onion", "Potato"})
            self.assertEqual(line_rows["Onion"], (10.0, 10.0))
            self.assertEqual(line_rows["Potato"], (10.0, 10.0))
            self.assertNotIn("Tomato", line_rows)

            stock_after = {
                (row["item_name"], row["unit"]): float(row["qty_on_hand"])
                for row in conn.execute(
                    "SELECT item_name, unit, qty_on_hand FROM store_stock_items WHERE outlet = 'bar'"
                ).fetchall()
            }
            movements_after = conn.execute(
                """
                SELECT COUNT(*) AS c FROM store_stock_movements
                WHERE ref_type = 'stock_inward' AND ref_id = ?
                """,
                (indent_id,),
            ).fetchone()["c"]
        finally:
            conn.close()

        self.assertEqual(stock_after[("Onion", "kg")], 10.0)
        self.assertEqual(stock_after[("Potato", "kg")], 10.0)
        self.assertNotIn(("Tomato", "kg"), stock_after)
        self.assertEqual(movements_after, movements_before)

        # Nothing left to cancel — clear error, indent and stock unchanged.
        blocked = self.client.get(
            f"/stores/indent/{indent_id}/delete?outlet=bar",
            follow_redirects=True,
        )
        self.assertEqual(blocked.status_code, 200)
        self.assertIn(b"fully inwarded", blocked.data)
        self.assertIn(b"nothing left to delete", blocked.data)

    def test_non_admin_cannot_delete_approved_indent(self):
        create = self.client.post(
            "/stores/indent?outlet=bar",
            data={
                "outlet": "bar",
                "action": "submit",
                "notes": "Non-admin approved delete",
                "item_name": ["Onion"],
                "quantity": ["5"],
                "unit": ["kg"],
                "approximate_price": ["25"],
            },
            follow_redirects=False,
        )
        self.assertEqual(create.status_code, 302)
        conn = db_mod.get_db()
        try:
            indent_id = conn.execute(
                "SELECT id FROM store_indents WHERE notes = 'Non-admin approved delete' ORDER BY id DESC LIMIT 1"
            ).fetchone()["id"]
        finally:
            conn.close()

        decide = self.client.post(
            f"/stores/indent/{indent_id}/decide",
            data={"outlet": "bar", "decision": "approved", "decision_note": ""},
            follow_redirects=False,
        )
        self.assertEqual(decide.status_code, 302)

        clerk = {
            "id": self.admin_id,
            "username": "storeclerk",
            "full_name": "Store Clerk",
            "is_admin": False,
            "is_active": True,
            "dashboard_access": {"stores"},
            "stores_access": {"indent", "stock", "purchase_requests", "approvals"},
            "sales_analytics_access": set(),
            "user_access": set(),
            "payroll_access": set(),
            "accounts_access": set(),
        }
        with mock.patch.object(self.app_mod, "get_current_user", return_value=clerk), mock.patch.object(
            self.stores_mod, "_get_user", return_value=clerk
        ):
            listing = self.client.get("/stores/indent?outlet=bar&view=approved")
            self.assertEqual(listing.status_code, 200)
            self.assertIn(b'data-tip="Download PO"', listing.data)
            self.assertNotIn(b'data-tip="Delete remaining"', listing.data)

            denied = self.client.get(
                f"/stores/indent/{indent_id}/delete?outlet=bar",
                follow_redirects=True,
            )
            self.assertEqual(denied.status_code, 200)
            self.assertIn(b"Only administrators can delete approved indents", denied.data)

        conn = db_mod.get_db()
        try:
            row = conn.execute(
                "SELECT status FROM store_indents WHERE id = ?", (indent_id,)
            ).fetchone()
            self.assertEqual(row["status"], "approved")
            line = conn.execute(
                "SELECT quantity, COALESCE(quantity_received, 0) AS quantity_received FROM store_indent_lines WHERE indent_id = ?",
                (indent_id,),
            ).fetchone()
            self.assertEqual(float(line["quantity"]), 5.0)
            self.assertEqual(float(line["quantity_received"]), 0.0)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
