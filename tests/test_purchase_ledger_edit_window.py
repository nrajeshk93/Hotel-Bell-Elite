"""Purchase Ledger edit window: 4h created_at OR 7/30-day sales_date."""

import unittest
from datetime import datetime, timedelta

import app as app_module


class PurchaseLedgerEditWindowHelpersTests(unittest.TestCase):
    def setUp(self):
        self.super_admin = {"id": 1, "username": "admin", "is_admin": True}
        self.admin = {"id": 2, "username": "clerk", "is_admin": False}
        self.now = datetime.now().replace(microsecond=0)

    def _created(self, **delta):
        return (self.now - timedelta(**delta)).strftime("%Y-%m-%d %H:%M:%S")

    def _entry(
        self,
        *,
        hours_ago=0,
        minutes_ago=0,
        days_ago=0,
        payment_type="cash",
        settlement_status=None,
        amount=100,
        paid_amount=0,
        cancelled_at=None,
    ):
        created_at = self._created(hours=hours_ago, minutes=minutes_ago)
        entry = {
            "id": 1,
            "sales_date": (self.now.date() - timedelta(days=days_ago)).isoformat(),
            "created_at": created_at,
            "payment_type": payment_type,
            "amount": amount,
            "paid_amount": paid_amount,
            "cancelled_at": cancelled_at,
        }
        if settlement_status is not None:
            entry["settlement_status"] = settlement_status
        else:
            entry["settlement_status"] = app_module._credit_settlement_status(
                payment_type, amount, paid_amount
            )
        return entry

    def test_cash_and_bank_status_is_cleared(self):
        self.assertEqual(app_module._credit_settlement_status("cash", 50, 0), "cleared")
        self.assertEqual(app_module._credit_settlement_status("bank", 50, 0), "cleared")

    def test_cleared_today_still_editable_after_4h(self):
        """Bill date in the 7-day window keeps Edit even if created_at is older than 4h."""
        entry = self._entry(hours_ago=5, payment_type="cash")
        self.assertEqual(entry["settlement_status"], "cleared")
        self.assertTrue(app_module._purchase_ledger_entry_can_edit(self.admin, entry))
        self.assertTrue(app_module._purchase_ledger_entry_can_edit(self.super_admin, entry))
        self.assertTrue(app_module._purchase_ledger_entry_can_cancel(self.super_admin, entry))
        self.assertFalse(app_module._purchase_ledger_entry_can_cancel(self.admin, entry))

    def test_staff_7_days_admin_30_days(self):
        staff_ok = self._entry(hours_ago=5, days_ago=6, payment_type="cash")
        staff_out = self._entry(hours_ago=5, days_ago=8, payment_type="cash")
        admin_ok = self._entry(hours_ago=5, days_ago=20, payment_type="cash")
        admin_out = self._entry(hours_ago=5, days_ago=31, payment_type="cash")
        self.assertTrue(app_module._purchase_ledger_entry_can_edit(self.admin, staff_ok))
        self.assertFalse(app_module._purchase_ledger_entry_can_edit(self.admin, staff_out))
        self.assertTrue(app_module._purchase_ledger_entry_can_edit(self.super_admin, admin_ok))
        self.assertFalse(app_module._purchase_ledger_entry_can_edit(self.super_admin, admin_out))

    def test_backdated_bill_still_editable_inside_4h(self):
        entry = self._entry(hours_ago=1, days_ago=40, payment_type="cash")
        self.assertTrue(app_module._purchase_ledger_entry_can_edit(self.admin, entry))

    def test_cleared_cash_inside_window_can_edit(self):
        entry = self._entry(hours_ago=1, payment_type="cash")
        self.assertEqual(entry["settlement_status"], "cleared")
        self.assertTrue(app_module._purchase_ledger_entry_can_edit(self.admin, entry))
        self.assertTrue(app_module._purchase_ledger_entry_can_edit(self.super_admin, entry))

    def test_cleared_credit_inside_window_can_edit(self):
        entry = self._entry(
            hours_ago=1,
            payment_type="credit",
            settlement_status="cleared",
            amount=100,
            paid_amount=100,
        )
        self.assertTrue(app_module._purchase_ledger_entry_can_edit(self.admin, entry))
        self.assertTrue(app_module._purchase_ledger_entry_can_edit(self.super_admin, entry))
        self.assertIsNone(app_module._purchase_ledger_edit_guard_error(self.super_admin, entry))

    def test_partial_credit_inside_window_can_edit(self):
        entry = self._entry(
            hours_ago=1,
            payment_type="credit",
            settlement_status="partial",
            amount=100,
            paid_amount=40,
        )
        self.assertTrue(app_module._purchase_ledger_entry_can_edit(self.admin, entry))

    def test_cancelled_never_editable(self):
        entry = self._entry(hours_ago=1, cancelled_at=self.now.strftime("%Y-%m-%d %H:%M:%S"))
        entry["settlement_status"] = "cancelled"
        self.assertFalse(app_module._purchase_ledger_entry_can_edit(self.admin, entry))
        self.assertFalse(app_module._purchase_ledger_entry_can_edit(self.super_admin, entry))
        self.assertEqual(
            app_module._purchase_ledger_edit_guard_error(self.super_admin, entry),
            app_module.PURCHASE_LEDGER_CANCELLED_EDIT_MESSAGE,
        )

    def test_guard_rejects_outside_window(self):
        entry = self._entry(hours_ago=5, days_ago=8, payment_type="cash")
        self.assertEqual(
            app_module._purchase_ledger_edit_guard_error(self.admin, entry),
            app_module.PURCHASE_LEDGER_EDIT_WINDOW_MESSAGE,
        )

    def test_cancel_only_super_admin_inside_window(self):
        entry = self._entry(hours_ago=1, payment_type="cash")
        self.assertTrue(app_module._purchase_ledger_entry_can_cancel(self.super_admin, entry))
        self.assertFalse(app_module._purchase_ledger_entry_can_cancel(self.admin, entry))

    def test_super_admin_cannot_cancel_after_windows(self):
        entry = self._entry(hours_ago=5, days_ago=31, payment_type="cash")
        self.assertFalse(app_module._purchase_ledger_entry_can_cancel(self.super_admin, entry))


if __name__ == "__main__":
    unittest.main()
