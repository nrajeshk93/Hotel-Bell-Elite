"""Purchase Ledger role-based edit window (Super Admin 30d / Admin 7d)."""

import unittest
from datetime import date, timedelta

import app as app_module


class PurchaseLedgerEditWindowHelpersTests(unittest.TestCase):
    def setUp(self):
        self.super_admin = {"id": 1, "username": "admin", "is_admin": True}
        self.admin = {"id": 2, "username": "clerk", "is_admin": False}
        self.today = date.today()

    def _entry(self, *, days_ago, payment_type="cash", settlement_status=None, amount=100, paid_amount=0):
        sales_date = (self.today - timedelta(days=days_ago)).isoformat()
        entry = {
            "id": 1,
            "sales_date": sales_date,
            "payment_type": payment_type,
            "amount": amount,
            "paid_amount": paid_amount,
        }
        if settlement_status is not None:
            entry["settlement_status"] = settlement_status
        else:
            entry["settlement_status"] = app_module._credit_settlement_status(
                payment_type, amount, paid_amount
            )
        return entry

    def test_window_days_by_role(self):
        self.assertEqual(
            app_module._purchase_ledger_edit_window_days(self.super_admin), 30
        )
        self.assertEqual(app_module._purchase_ledger_edit_window_days(self.admin), 7)

    def test_super_admin_day_29_editable(self):
        entry = self._entry(days_ago=29, payment_type="cash")
        self.assertTrue(
            app_module._purchase_ledger_entry_in_edit_window(
                self.super_admin, entry["sales_date"]
            )
        )
        self.assertTrue(app_module._purchase_ledger_entry_can_edit(self.super_admin, entry))

    def test_super_admin_day_30_locked(self):
        entry = self._entry(days_ago=30, payment_type="cash")
        self.assertFalse(
            app_module._purchase_ledger_entry_in_edit_window(
                self.super_admin, entry["sales_date"]
            )
        )
        self.assertFalse(app_module._purchase_ledger_entry_can_edit(self.super_admin, entry))

    def test_admin_day_6_editable(self):
        entry = self._entry(days_ago=6, payment_type="cash")
        self.assertTrue(
            app_module._purchase_ledger_entry_in_edit_window(self.admin, entry["sales_date"])
        )
        self.assertTrue(app_module._purchase_ledger_entry_can_edit(self.admin, entry))

    def test_admin_day_7_locked(self):
        entry = self._entry(days_ago=7, payment_type="cash")
        self.assertFalse(
            app_module._purchase_ledger_entry_in_edit_window(self.admin, entry["sales_date"])
        )
        self.assertFalse(app_module._purchase_ledger_entry_can_edit(self.admin, entry))

    def test_cash_inside_window_can_edit(self):
        entry = self._entry(days_ago=1, payment_type="cash")
        self.assertEqual(entry["settlement_status"], "cleared")
        self.assertTrue(app_module._purchase_ledger_entry_can_edit(self.admin, entry))
        self.assertTrue(app_module._purchase_ledger_entry_can_edit(self.super_admin, entry))

    def test_outstanding_credit_inside_window_can_edit(self):
        entry = self._entry(
            days_ago=1,
            payment_type="credit",
            settlement_status="outstanding",
            paid_amount=0,
        )
        self.assertTrue(app_module._purchase_ledger_entry_can_edit(self.admin, entry))

    def test_cleared_credit_cannot_edit_even_inside_window(self):
        entry = self._entry(
            days_ago=1,
            payment_type="credit",
            settlement_status="cleared",
            amount=100,
            paid_amount=100,
        )
        self.assertFalse(app_module._purchase_ledger_entry_can_edit(self.admin, entry))
        self.assertFalse(app_module._purchase_ledger_entry_can_edit(self.super_admin, entry))
        self.assertEqual(
            app_module._purchase_ledger_edit_guard_error(self.super_admin, entry),
            app_module.PURCHASE_LEDGER_CREDIT_SETTLED_EDIT_MESSAGE,
        )

    def test_partial_credit_cannot_edit_even_inside_window(self):
        entry = self._entry(
            days_ago=1,
            payment_type="credit",
            settlement_status="partial",
            amount=100,
            paid_amount=40,
        )
        self.assertFalse(app_module._purchase_ledger_entry_can_edit(self.admin, entry))
        self.assertEqual(
            app_module._purchase_ledger_edit_guard_error(self.admin, entry),
            app_module.PURCHASE_LEDGER_CREDIT_SETTLED_EDIT_MESSAGE,
        )

    def test_guard_rejects_outside_window(self):
        entry = self._entry(days_ago=10, payment_type="cash")
        self.assertEqual(
            app_module._purchase_ledger_edit_guard_error(self.admin, entry),
            app_module.PURCHASE_LEDGER_EDIT_WINDOW_MESSAGE,
        )

    def test_guard_rejects_new_sales_date_outside_window(self):
        entry = self._entry(days_ago=1, payment_type="cash")
        new_date = (self.today - timedelta(days=10)).isoformat()
        self.assertEqual(
            app_module._purchase_ledger_edit_guard_error(
                self.admin, entry, new_sales_date=new_date
            ),
            app_module.PURCHASE_LEDGER_EDIT_WINDOW_MESSAGE,
        )


if __name__ == "__main__":
    unittest.main()
