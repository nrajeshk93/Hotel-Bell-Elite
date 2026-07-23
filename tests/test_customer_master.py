"""Customer Master + POS customer sync."""

import unittest

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

    def test_customer_master_page(self):
        from app import app

        client = app.test_client()
        with client.session_transaction() as sess:
            sess["user_id"] = 1
        response = client.get("/customers?embed=1")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("md-master-embed--customer", html)
        self.assertIn("First Name", html)
        self.assertNotIn('id="de-sidebar"', html)


if __name__ == "__main__":
    unittest.main()
