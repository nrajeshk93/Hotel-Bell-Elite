"""Agency Master CRUD."""

import os
import tempfile
import unittest
from unittest import mock

import db as db_mod
from db import (
    ensure_agencies_schema,
    get_agency,
    get_db,
    list_agencies,
    save_agency_record,
    upsert_agency_by_name,
)


class AgencyMasterDbTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db_path = self.tmp.name
        self._orig_path = db_mod.DATABASE_PATH
        db_mod.DATABASE_PATH = self.db_path
        db_mod.init_db()
        self.conn = get_db()
        ensure_agencies_schema(self.conn)

    def tearDown(self):
        self.conn.close()
        db_mod.DATABASE_PATH = self._orig_path
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def test_save_list_and_upsert(self):
        saved_id, errors = save_agency_record(
            self.conn,
            "MakeMyTrip",
            "27AAAAA0000A1Z5",
            "Mumbai",
            bank_account_number="1234567890",
            bank_name="HDFC Bank",
            ifsc_code="HDFC0001234",
        )
        self.assertEqual(errors, [])
        self.assertIsNotNone(saved_id)
        self.conn.commit()

        agencies = list_agencies(self.conn)
        self.assertEqual(len(agencies), 1)
        self.assertEqual(agencies[0]["name"], "MakeMyTrip")
        self.assertEqual(agencies[0]["bank_account_number"], "1234567890")
        self.assertEqual(agencies[0]["bank_name"], "HDFC Bank")
        self.assertEqual(agencies[0]["ifsc_code"], "HDFC0001234")
        self.assertEqual(agencies[0].get("phone") or "", "")

        saved_phone_id, phone_errors = save_agency_record(
            self.conn,
            "Yatra",
            "",
            "",
            phone="98765 43210",
        )
        self.assertEqual(phone_errors, [])
        self.assertIsNotNone(saved_phone_id)
        self.conn.commit()
        self.assertEqual(get_agency(self.conn, saved_phone_id)["phone"], "9876543210")

        dup_id, dup_errors = save_agency_record(self.conn, "makemytrip", "X", "Y")
        self.assertIsNone(dup_id)
        self.assertTrue(any("already exists" in e.lower() for e in dup_errors))

        updated = upsert_agency_by_name(self.conn, "MakeMyTrip", "27BBBBB0000B1Z5", "")
        self.assertEqual(updated["gst"], "27BBBBB0000B1Z5")
        self.assertEqual(updated["address"], "Mumbai")
        self.assertEqual(updated["bank_name"], "HDFC Bank")
        self.assertEqual(get_agency(self.conn, saved_id)["gst"], "27BBBBB0000B1Z5")

        filled = upsert_agency_by_name(self.conn, "MakeMyTrip", "not-a-gstin", "Andaman")
        self.assertEqual(filled["gst"], "27BBBBB0000B1Z5")
        self.assertEqual(filled["address"], "Andaman")

        bad_ifsc_id, bad_ifsc_errors = save_agency_record(
            self.conn,
            "Goibibo",
            "",
            "",
            ifsc_code="BAD",
        )
        self.assertIsNone(bad_ifsc_id)
        self.assertTrue(any("ifsc" in e.lower() for e in bad_ifsc_errors))


class AgencyMasterRouteTests(unittest.TestCase):
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

    def test_create_and_list_api(self):
        created = self.client.post(
            "/agencies/create",
            json={"name": "Booking.com", "gst": "29CCCCC0000C1Z5", "address": "Bengaluru"},
        )
        self.assertEqual(created.status_code, 200)
        body = created.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["agency"]["name"], "Booking.com")

        listed = self.client.get("/agencies/api")
        self.assertEqual(listed.status_code, 200)
        agencies = listed.get_json()["agencies"]
        self.assertTrue(any(a["name"] == "Booking.com" for a in agencies))

        page = self.client.get("/agencies")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn("Agency Master", html)
        self.assertIn("Booking.com", html)
        self.assertIn("Mobile", html)
        self.assertIn("Bank Account", html)
        self.assertIn("Bank Name", html)
        self.assertIn("IFSC Code", html)

    def test_delete_agency_allowed(self):
        created = self.client.post(
            "/agencies/create",
            json={"name": "EasyTrip", "gst": "", "address": ""},
        )
        self.assertEqual(created.status_code, 200)
        agency_id = created.get_json()["agency"]["id"]

        page = self.client.get("/agencies")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn('aria-label="Delete EasyTrip"', html)
        self.assertIn("/agencies/delete", html)

        deleted = self.client.post(
            "/agencies/delete",
            data={"agency_id": agency_id},
            follow_redirects=True,
        )
        self.assertEqual(deleted.status_code, 200)
        self.assertIn("Agency deleted successfully.", deleted.get_data(as_text=True))
        conn = db_mod.get_db()
        try:
            self.assertIsNone(db_mod.get_agency(conn, agency_id))
        finally:
            conn.close()

    def test_delete_agency_blocked_with_pending_credit(self):
        created = self.client.post(
            "/agencies/create",
            json={"name": "CreditAgency", "gst": "", "address": ""},
        )
        self.assertEqual(created.status_code, 200)
        agency_id = created.get_json()["agency"]["id"]

        conn = db_mod.get_db()
        try:
            db_mod.ensure_hotel_invoice_credits_schema(conn)
            conn.execute(
                """INSERT INTO hotel_invoice_credits
                   (invoice_number, agency_name, guest_name, room_number, credit_date, credit_amount)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                ("HBE/99-00/1", "CreditAgency", "Guest", "101", "2026-08-01", 1500.0),
            )
            conn.commit()
        finally:
            conn.close()

        page = self.client.get("/agencies")
        html = page.get_data(as_text=True)
        self.assertIn("pending credit", html.lower())
        self.assertIn("is-disabled", html)

        blocked = self.client.post(
            "/agencies/delete",
            data={"agency_id": agency_id},
            follow_redirects=True,
        )
        self.assertEqual(blocked.status_code, 200)
        body = blocked.get_data(as_text=True).lower()
        self.assertIn("pending credit", body)
        conn = db_mod.get_db()
        try:
            self.assertIsNotNone(db_mod.get_agency(conn, agency_id))
        finally:
            conn.close()

    def test_save_agency_bank_fields(self):
        created = self.client.post(
            "/agencies/save",
            data={
                "name": "Cleartrip",
                "phone": "9988776655",
                "gst": "29DDDDD0000D1Z5",
                "address": "Pune",
                "bank_account_number": "9988776655",
                "bank_name": "SBI",
                "ifsc_code": "SBIN0004321",
            },
            follow_redirects=True,
        )
        self.assertEqual(created.status_code, 200)
        html = created.get_data(as_text=True)
        self.assertIn("Cleartrip", html)
        self.assertIn("9988776655", html)
        self.assertIn("SBI", html)
        self.assertIn("SBIN0004321", html)

    def test_master_hub_includes_agency_card(self):
        page = self.client.get("/master")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn("Agency Master", html)
        self.assertIn("/agencies", html)


if __name__ == "__main__":
    unittest.main()
