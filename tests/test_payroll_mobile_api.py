import os
import tempfile
import unittest
from datetime import date, timedelta
from unittest import mock

import db as db_mod


class PayrollMobileApiTests(unittest.TestCase):
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
            "payroll_access": set(),
        }
        self._get_user_patch = mock.patch.object(app_mod, "get_current_user", return_value=self.user)
        self._get_user_patch.start()

        self.emp_id = self._insert_employee("Anita Rao", "9876543210", "FO")

    def tearDown(self):
        self._get_user_patch.stop()
        db_mod.DATABASE_PATH = self._orig_path
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def _insert_employee(self, name, mobile, location, gross=20000):
        conn = db_mod.get_db()
        try:
            cur = conn.execute(
                """INSERT INTO employees (emp_code, name, company, location, mobile, gross_salary, status)
                   VALUES (?, ?, ?, ?, ?, ?, 'active')""",
                (f"HBE{name[:2].upper()}{mobile[-4:]}", name, "Hotel Bell Elite", location, mobile, gross),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()

    def test_employees_list_200(self):
        resp = self.client.get("/api/mobile/payroll/employees?status=active")
        self.assertEqual(resp.status_code, 200, resp.get_json())
        data = resp.get_json()
        self.assertTrue(data.get("ok"))
        self.assertIn("period_label", data)
        names = [e["name"] for e in data.get("employees") or []]
        self.assertIn("Anita Rao", names)
        row = next(e for e in data["employees"] if e["name"] == "Anita Rao")
        self.assertEqual(row["mobile"], "9876543210")
        self.assertIn("gross_salary", row)

    def test_employee_detail_and_create(self):
        resp = self.client.get(f"/api/mobile/payroll/employees/{self.emp_id}")
        self.assertEqual(resp.status_code, 200, resp.get_json())
        self.assertEqual(resp.get_json()["name"], "Anita Rao")

        created = self.client.post(
            "/api/mobile/payroll/employees",
            json={
                "name": "Ravi Kumar",
                "mobile": "9123456789",
                "location": "HK",
                "company": "Hotel Bell Elite",
                "gross_salary": 18000,
            },
        )
        self.assertEqual(created.status_code, 200, created.get_json())
        body = created.get_json()
        self.assertTrue(body.get("ok"))
        self.assertTrue(body.get("emp_code"))
        self.assertEqual(body["mobile"], "9123456789")

    def test_employee_create_rejects_bad_mobile(self):
        resp = self.client.post(
            "/api/mobile/payroll/employees",
            json={"name": "Bad Phone", "mobile": "12345"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(resp.get_json().get("ok"))

    def test_employee_update_core_fields(self):
        resp = self.client.post(
            f"/api/mobile/payroll/employees/{self.emp_id}",
            json={"name": "Anita R", "mobile": "9876543210", "location": "FO"},
        )
        self.assertEqual(resp.status_code, 200, resp.get_json())
        self.assertEqual(resp.get_json()["name"], "Anita R")

    def test_attendance_date_list_default_today(self):
        today = date.today().isoformat()
        resp = self.client.get("/api/mobile/payroll/attendance")
        self.assertEqual(resp.status_code, 200, resp.get_json())
        data = resp.get_json()
        self.assertTrue(data.get("ok"))
        self.assertEqual(data.get("view"), "date")
        self.assertEqual(data.get("date"), today)
        ids = [e["id"] for e in data.get("employees") or []]
        self.assertIn(self.emp_id, ids)

    def test_attendance_mark_present_and_clear(self):
        today = date.today().isoformat()
        mark = self.client.post(
            "/api/mobile/payroll/attendance/mark",
            json={"employee_id": self.emp_id, "date": today, "status": "present"},
        )
        self.assertEqual(mark.status_code, 200, mark.get_json())
        self.assertTrue(mark.get_json().get("ok"))

        listed = self.client.get(f"/api/mobile/payroll/attendance?date={today}")
        row = next(e for e in listed.get_json()["employees"] if e["id"] == self.emp_id)
        self.assertEqual(row["date_status"], "present")

        cleared = self.client.post(
            "/api/mobile/payroll/attendance/mark",
            json={"employee_id": self.emp_id, "date": today, "status": ""},
        )
        self.assertEqual(cleared.status_code, 200, cleared.get_json())
        listed = self.client.get(f"/api/mobile/payroll/attendance?date={today}")
        row = next(e for e in listed.get_json()["employees"] if e["id"] == self.emp_id)
        self.assertEqual(row["date_status"], "")

    def test_attendance_rejects_future(self):
        future = (date.today() + timedelta(days=2)).isoformat()
        resp = self.client.post(
            "/api/mobile/payroll/attendance/mark",
            json={"employee_id": self.emp_id, "date": future, "status": "present"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Future", resp.get_json().get("error") or "")

    def test_credits_list_and_add(self):
        listed = self.client.get("/api/mobile/payroll/credits")
        self.assertEqual(listed.status_code, 200, listed.get_json())
        self.assertTrue(listed.get_json().get("ok"))
        picker_ids = [e["id"] for e in listed.get_json().get("all_employees") or []]
        self.assertIn(self.emp_id, picker_ids)

        today = date.today().isoformat()
        added = self.client.post(
            "/api/mobile/payroll/credits",
            json={
                "employee_id": self.emp_id,
                "date": today,
                "description": "Advance",
                "amount": 500,
                "transaction_type": "credit",
                "payment_type": "bank_transfer",
                "transaction_id": "UTR-TEST-1",
            },
        )
        self.assertEqual(added.status_code, 200, added.get_json())
        self.assertTrue(added.get_json().get("ok"))
        self.assertEqual(added.get_json()["amount"], 500)

        conn = db_mod.get_db()
        try:
            credit = conn.execute(
                "SELECT amount, entry_type FROM credits WHERE employee_id=?",
                (self.emp_id,),
            ).fetchone()
            self.assertIsNotNone(credit)
            self.assertEqual(float(credit["amount"]), 500)
            expense = conn.execute(
                "SELECT COUNT(*) AS n FROM sales_update_expenses WHERE description LIKE ?",
                ("%Anita%",),
            ).fetchone()
            self.assertGreaterEqual(int(expense["n"]), 1)
        finally:
            conn.close()

    def test_credit_employee_history(self):
        today = date.today().isoformat()
        self.client.post(
            "/api/mobile/payroll/credits",
            json={
                "employee_id": self.emp_id,
                "date": today,
                "description": "Advance A",
                "amount": 300,
                "transaction_type": "credit",
                "payment_type": "cash",
            },
        )
        self.client.post(
            "/api/mobile/payroll/credits",
            json={
                "employee_id": self.emp_id,
                "date": today,
                "description": "Repay B",
                "amount": 100,
                "transaction_type": "repayment",
                "payment_type": "cash",
            },
        )
        hist = self.client.get(f"/api/mobile/payroll/credits/{self.emp_id}")
        self.assertEqual(hist.status_code, 200, hist.get_json())
        data = hist.get_json()
        self.assertTrue(data.get("ok"))
        self.assertEqual(data.get("employee", {}).get("id"), self.emp_id)
        self.assertEqual(float(data.get("credit_balance") or 0), 200)
        self.assertGreaterEqual(int(data.get("entry_count") or 0), 2)
        amounts = [float(e.get("amount") or 0) for e in (data.get("entries") or [])]
        self.assertIn(300.0, amounts)
        self.assertIn(-100.0, amounts)

    def test_credit_bank_requires_transaction_id(self):
        resp = self.client.post(
            "/api/mobile/payroll/credits",
            json={
                "employee_id": self.emp_id,
                "date": date.today().isoformat(),
                "description": "Bank advance",
                "amount": 200,
                "transaction_type": "credit",
                "payment_type": "bank_transfer",
            },
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Transaction ID", resp.get_json().get("error") or "")

    def test_tips_get_and_add(self):
        listed = self.client.get("/api/mobile/payroll/tips")
        self.assertEqual(listed.status_code, 200, listed.get_json())
        data = listed.get_json()
        self.assertTrue(data.get("ok"))
        self.assertIn("grand_total", data)

        added = self.client.post(
            "/api/mobile/payroll/tips",
            json={
                "company": "HBE",
                "location": "Hotel",
                "date": date.today().isoformat(),
                "employee_id": self.emp_id,
                "description": "Evening",
                "amount": 150,
            },
        )
        self.assertEqual(added.status_code, 200, added.get_json())
        self.assertTrue(added.get_json().get("ok"))
        self.assertEqual(added.get_json()["amount"], 150)

        listed = self.client.get("/api/mobile/payroll/tips?location=Hotel")
        self.assertGreaterEqual(listed.get_json().get("grand_total") or 0, 150)

    def test_tips_incentive_get(self):
        today = date.today()
        resp = self.client.get(
            f"/api/mobile/payroll/tips/incentive?company=HBE&year={today.year}&month={today.month}"
        )
        self.assertEqual(resp.status_code, 200, resp.get_json())
        self.assertTrue(resp.get_json().get("ok"))

    def test_unauthenticated_401(self):
        with mock.patch.object(self.app_mod, "get_current_user", return_value=None):
            resp = self.client.get("/api/mobile/payroll/employees")
        self.assertEqual(resp.status_code, 401)
        self.assertFalse(resp.get_json().get("ok"))

    def test_preview_api_employees_proxy(self):
        resp = self.client.get("/preview-api/payroll/employees?status=active")
        self.assertEqual(resp.status_code, 200, resp.get_json())
        data = resp.get_json()
        self.assertTrue(data.get("ok"))
        names = [e["name"] for e in data.get("employees") or []]
        self.assertIn("Anita Rao", names)
