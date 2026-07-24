"""Customer Master + POS customer sync."""

import os
import tempfile
import unittest
from unittest import mock

import db as db_mod
from db import (
    ensure_customers_schema,
    get_db,
    list_customers,
    save_customer_record,
    search_customers,
    upsert_customer,
)


class CustomerMasterTest(unittest.TestCase):
    def setUp(self):
        self.conn = get_db()
        ensure_customers_schema(self.conn)
        self.conn.execute("DELETE FROM customers WHERE mobile LIKE '90000%'")
        self.conn.commit()

    def tearDown(self):
        self.conn.execute("DELETE FROM customers WHERE mobile LIKE '90000%'")
        self.conn.commit()
        self.conn.close()

    def test_mobile_must_be_unique(self):
        saved_id, errors = save_customer_record(self.conn, "Ada", "9000011111")
        self.assertEqual(errors, [])
        self.assertIsNotNone(saved_id)
        self.conn.commit()

        dup_id, dup_errors = save_customer_record(self.conn, "Other", "9000011111")
        self.assertIsNone(dup_id)
        self.assertTrue(any("already exists" in e.lower() for e in dup_errors))

    def test_pos_upsert_updates_first_name(self):
        upsert_customer(self.conn, "First", "9000022222")
        self.conn.commit()
        updated = upsert_customer(self.conn, "Updated", "9000022222")
        self.conn.commit()
        self.assertEqual(updated["first_name"], "Updated")
        self.assertEqual(updated["mobile"], "9000022222")
        matches = search_customers(self.conn, "900002")
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["name"], "Updated")

    def test_upsert_ignores_incomplete_mobile(self):
        self.assertIsNone(upsert_customer(self.conn, "Partial", "90000"))
        self.assertIsNone(upsert_customer(self.conn, "Partial", "900001234"))  # 9 digits
        self.assertIsNone(upsert_customer(self.conn, "Partial", ""))
        rows = [
            r
            for r in list_customers(self.conn)
            if str(r.get("mobile") or "").startswith("90000")
        ]
        self.assertEqual(rows, [])

    def test_upsert_fills_blank_name_without_duplicate(self):
        first = upsert_customer(self.conn, "", "9000033333")
        self.conn.commit()
        self.assertEqual(first["first_name"], "Guest")
        filled = upsert_customer(self.conn, "Priya", "9000033333")
        self.conn.commit()
        self.assertEqual(filled["id"], first["id"])
        self.assertEqual(filled["first_name"], "Priya")
        matches = search_customers(self.conn, "900003")
        self.assertEqual(len(matches), 1)

    def test_customer_master_page(self):
        from app import app

        client = app.test_client()
        with client.session_transaction() as sess:
            sess["user_id"] = 1
        response = client.get("/customers?embed=1")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("md-master-embed--customer", html)
        self.assertIn("Add customer", html)
        self.assertIn("Customers", html)
        self.assertNotIn('id="de-sidebar"', html)


class PosInvoiceCustomerSyncTests(unittest.TestCase):
    """Invoice save path upserts into Customer Master (shared with autosave/KOT)."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db_path = self.tmp.name
        self._orig_path = db_mod.DATABASE_PATH
        db_mod.DATABASE_PATH = self.db_path
        db_mod.init_db()

        import app as app_mod

        self.app_mod = app_mod
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
        self._get_user_patch.start()

    def tearDown(self):
        self._get_user_patch.stop()
        db_mod.DATABASE_PATH = self._orig_path
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def _payload(self, **overrides):
        data = {
            "orderNo": "ORD-CUST-0001",
            "savedAt": "2026-07-24 18:00:00",
            "orderType": "dine_in",
            "table": "T1",
            "captain": "",
            "customerName": "Anika",
            "customerMobile": "9000044444",
            "notes": "",
            "discountType": "pct",
            "discountValue": 0,
            "serviceType": "pct",
            "serviceValue": 0,
            "tipAmount": 0,
            "couponCode": "",
            "lines": [
                {
                    "uid": "1",
                    "menuId": None,
                    "name": "Filter Coffee",
                    "variant": "Hot",
                    "rate": 100,
                    "qty": 1,
                }
            ],
            "totals": {
                "subtotal": 100,
                "discount": 0,
                "discountType": "pct",
                "discountValue": 0,
                "gst": 5,
                "service": 0,
                "serviceType": "pct",
                "serviceValue": 0,
                "tip": 0,
                "roundOff": 0,
                "total": 105,
            },
        }
        data.update(overrides)
        return data

    def test_invoice_save_creates_customer_master_row(self):
        save = self.client.post("/point-of-sale/api/invoices", json=self._payload())
        self.assertEqual(save.status_code, 200)
        self.assertTrue(save.get_json().get("ok"))

        conn = db_mod.get_db()
        try:
            row = conn.execute(
                "SELECT first_name, mobile FROM customers WHERE mobile = ?",
                ("9000044444",),
            ).fetchone()
        finally:
            conn.close()
        self.assertIsNotNone(row)
        self.assertEqual(row["first_name"], "Anika")
        self.assertEqual(row["mobile"], "9000044444")

    def test_invoice_save_updates_existing_customer_no_duplicate(self):
        first = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload(orderNo="ORD-CUST-0001", customerName="Old Name"),
        )
        self.assertEqual(first.status_code, 200)

        second = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload(orderNo="ORD-CUST-0002", customerName="New Name"),
        )
        self.assertEqual(second.status_code, 200)

        conn = db_mod.get_db()
        try:
            rows = conn.execute(
                "SELECT first_name FROM customers WHERE mobile = ?",
                ("9000044444",),
            ).fetchall()
        finally:
            conn.close()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["first_name"], "New Name")

    def test_incomplete_mobile_does_not_create_customer(self):
        save = self.client.post(
            "/point-of-sale/api/invoices",
            json=self._payload(customerMobile="90000", customerName="Junk"),
        )
        self.assertEqual(save.status_code, 200)
        self.assertTrue(save.get_json().get("ok"))

        conn = db_mod.get_db()
        try:
            count = conn.execute(
                "SELECT COUNT(*) AS n FROM customers WHERE first_name = ? OR mobile LIKE '90000%'",
                ("Junk",),
            ).fetchone()["n"]
        finally:
            conn.close()
        self.assertEqual(count, 0)

    def test_pos_customer_search_api(self):
        self.client.post("/point-of-sale/api/invoices", json=self._payload())
        res = self.client.get("/point-of-sale/api/customers?q=900004")
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertTrue(body.get("ok"))
        customers = body.get("customers") or []
        self.assertEqual(len(customers), 1)
        self.assertEqual(customers[0]["name"], "Anika")
        self.assertEqual(customers[0]["mobile"], "9000044444")

        by_name = self.client.get("/point-of-sale/api/customers?q=Ani")
        self.assertEqual(by_name.status_code, 200)
        name_hits = by_name.get_json().get("customers") or []
        self.assertTrue(any(c.get("mobile") == "9000044444" for c in name_hits))


if __name__ == "__main__":
    unittest.main()
