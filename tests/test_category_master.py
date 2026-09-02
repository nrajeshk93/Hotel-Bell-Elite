"""Category Master — Restaurant/Bar POS plus Purchase/Expense ledger modules."""

import os
import sqlite3
import tempfile
import unittest

import db as db_mod
from db import (
    POS_OUTLET_RESTAURANT,
    ensure_pos_schema,
    get_db,
    list_pos_menu_categories,
    save_pos_menu_category,
)
from ledger_categories import (
    LEDGER_MODULE_EXPENSE,
    LEDGER_MODULE_PURCHASE,
    SOURCE_LEDGER,
    SOURCE_POS,
    encode_category_master_id,
    ensure_expense_category_modules,
    list_ledger_categories,
    parse_category_master_id,
    save_ledger_category,
    soft_delete_ledger_category,
)


def _builtins():
    return (
        ("grocery", "Grocery"),
        ("vegetables", "Vegetables"),
        ("salary", "Salary"),
        ("other", "Other"),
    )


class CategoryMasterLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db_path = self.tmp.name
        self._orig_path = db_mod.DATABASE_PATH
        db_mod.DATABASE_PATH = self.db_path
        db_mod.init_db()
        self.conn = get_db()
        ensure_pos_schema(self.conn)
        ensure_expense_category_modules(self.conn, builtin_categories=_builtins())
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        db_mod.DATABASE_PATH = self._orig_path
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def test_seed_copies_builtins_into_both_modules(self):
        purchase = {row["category_key"]: row["name"] for row in list_ledger_categories(self.conn, LEDGER_MODULE_PURCHASE)}
        expense = {row["category_key"]: row["name"] for row in list_ledger_categories(self.conn, LEDGER_MODULE_EXPENSE)}
        for key, label in _builtins():
            self.assertEqual(purchase.get(key), label)
            self.assertEqual(expense.get(key), label)

    def test_purchase_only_category_stays_off_expense_list(self):
        saved = save_ledger_category(self.conn, name="Hotel Linen", module=LEDGER_MODULE_PURCHASE)
        self.conn.commit()
        purchase_keys = {row["category_key"] for row in list_ledger_categories(self.conn, LEDGER_MODULE_PURCHASE)}
        expense_keys = {row["category_key"] for row in list_ledger_categories(self.conn, LEDGER_MODULE_EXPENSE)}
        self.assertIn(saved["category_key"], purchase_keys)
        self.assertNotIn(saved["category_key"], expense_keys)

    def test_expense_only_category_stays_off_purchase_list(self):
        saved = save_ledger_category(self.conn, name="Staff Welfare", module=LEDGER_MODULE_EXPENSE)
        self.conn.commit()
        purchase_keys = {row["category_key"] for row in list_ledger_categories(self.conn, LEDGER_MODULE_PURCHASE)}
        expense_keys = {row["category_key"] for row in list_ledger_categories(self.conn, LEDGER_MODULE_EXPENSE)}
        self.assertIn(saved["category_key"], expense_keys)
        self.assertNotIn(saved["category_key"], purchase_keys)

    def test_same_name_allowed_in_purchase_and_expense(self):
        purchase = save_ledger_category(self.conn, name="Dairy Products", module=LEDGER_MODULE_PURCHASE)
        expense = save_ledger_category(self.conn, name="Dairy Products", module=LEDGER_MODULE_EXPENSE)
        self.conn.commit()
        self.assertEqual(purchase["category_key"], expense["category_key"])
        self.assertNotEqual(purchase["id"], expense["id"])
        self.assertEqual(purchase["module"], LEDGER_MODULE_PURCHASE)
        self.assertEqual(expense["module"], LEDGER_MODULE_EXPENSE)

    def test_rename_purchase_does_not_change_expense(self):
        purchase = next(
            row for row in list_ledger_categories(self.conn, LEDGER_MODULE_PURCHASE)
            if row["category_key"] == "grocery"
        )
        expense_before = next(
            row for row in list_ledger_categories(self.conn, LEDGER_MODULE_EXPENSE)
            if row["category_key"] == "grocery"
        )
        save_ledger_category(self.conn, category_id=purchase["id"], name="Kitchen Grocery")
        self.conn.commit()
        expense_after = next(
            row for row in list_ledger_categories(self.conn, LEDGER_MODULE_EXPENSE)
            if row["category_key"] == "grocery"
        )
        self.assertEqual(expense_after["name"], expense_before["name"])
        renamed = next(
            row for row in list_ledger_categories(self.conn, LEDGER_MODULE_PURCHASE)
            if row["id"] == purchase["id"]
        )
        self.assertEqual(renamed["name"], "Kitchen Grocery")
        self.assertEqual(renamed["category_key"], "grocery")

    def test_delete_unused_purchase_custom_leaves_expense(self):
        saved = save_ledger_category(self.conn, name="One Off Purchase", module=LEDGER_MODULE_PURCHASE)
        self.conn.commit()
        soft_delete_ledger_category(self.conn, saved["id"])
        self.conn.commit()
        purchase_keys = {row["category_key"] for row in list_ledger_categories(self.conn, LEDGER_MODULE_PURCHASE)}
        self.assertNotIn(saved["category_key"], purchase_keys)
        expense_keys = {row["category_key"] for row in list_ledger_categories(self.conn, LEDGER_MODULE_EXPENSE)}
        self.assertIn("grocery", expense_keys)

    def test_delete_in_use_purchase_refused(self):
        saved = save_ledger_category(self.conn, name="Used Purchase", module=LEDGER_MODULE_PURCHASE)
        self.conn.execute(
            """
            INSERT INTO sales_update_expenses
                (company, location, sales_date, description, amount, category, entry_kind)
            VALUES ('HBE', 'Hotel', '2026-09-01', 'Rice', 10, ?, 'purchase')
            """,
            (saved["category_key"],),
        )
        self.conn.commit()
        with self.assertRaises(ValueError) as ctx:
            soft_delete_ledger_category(self.conn, saved["id"])
        self.assertIn("purchase", str(ctx.exception).lower())

    def test_pos_category_not_in_ledger_lists(self):
        row = save_pos_menu_category(self.conn, name="Main Course", outlet=POS_OUTLET_RESTAURANT)
        self.conn.commit()
        self.assertTrue(row["id"])
        names = {c["name"] for c in list_pos_menu_categories(self.conn, outlet=POS_OUTLET_RESTAURANT)}
        self.assertIn("Main Course", names)
        purchase_names = {c["name"] for c in list_ledger_categories(self.conn, LEDGER_MODULE_PURCHASE)}
        expense_names = {c["name"] for c in list_ledger_categories(self.conn, LEDGER_MODULE_EXPENSE)}
        self.assertNotIn("Main Course", purchase_names)
        self.assertNotIn("Main Course", expense_names)

    def test_pos_delete_blocked_when_items_exist(self):
        category = save_pos_menu_category(self.conn, name="Starters", outlet=POS_OUTLET_RESTAURANT)
        self.conn.execute(
            """
            INSERT INTO pos_menu_items (category_id, name, outlet, is_active, rate)
            VALUES (?, 'Soup', ?, 1, 100)
            """,
            (category["id"], POS_OUTLET_RESTAURANT),
        )
        self.conn.commit()
        import app as app_module
        count = app_module._pos_menu_category_item_count(self.conn, category["id"])
        self.assertGreater(count, 0)

    def test_normalize_old_grocery_key(self):
        import app as app_module
        self.assertEqual(app_module._normalize_expense_category("grocery"), "grocery")
        self.assertEqual(app_module._normalize_expense_category("Grocery"), "grocery")

    def test_edit_cannot_change_module(self):
        saved = save_ledger_category(self.conn, name="Keep Module", module=LEDGER_MODULE_PURCHASE)
        updated = save_ledger_category(
            self.conn,
            category_id=saved["id"],
            name="Keep Module Renamed",
            module=LEDGER_MODULE_EXPENSE,
        )
        self.assertEqual(updated["module"], LEDGER_MODULE_PURCHASE)
        self.assertEqual(updated["name"], "Keep Module Renamed")

    def test_composite_ids(self):
        self.assertEqual(parse_category_master_id("pos:12"), (SOURCE_POS, 12))
        self.assertEqual(parse_category_master_id("pe:9"), (SOURCE_LEDGER, 9))
        self.assertEqual(parse_category_master_id("15"), (SOURCE_POS, 15))
        self.assertEqual(encode_category_master_id(SOURCE_LEDGER, 4), "pe:4")

    def test_app_choices_are_module_scoped(self):
        import app as app_module
        save_ledger_category(self.conn, name="Only Purchase Cat", module=LEDGER_MODULE_PURCHASE)
        self.conn.commit()
        purchase = dict(app_module._expense_category_choices(self.conn, module="purchase"))
        expense = dict(app_module._expense_category_choices(self.conn, module="expense"))
        self.assertIn("only_purchase_cat", purchase)
        self.assertNotIn("only_purchase_cat", expense)
        self.assertIn("grocery", purchase)
        self.assertIn("grocery", expense)


class CategoryMasterMigrationTests(unittest.TestCase):
    def test_old_unique_key_table_is_cloned_to_purchase(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            """
            CREATE TABLE expense_categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category_key TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL COLLATE NOCASE,
                sort_order INTEGER NOT NULL DEFAULT 0,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
            )
            """
        )
        conn.execute(
            "INSERT INTO expense_categories (category_key, name, sort_order, is_active) VALUES ('linen', 'Linen', 10, 1)"
        )
        conn.commit()
        ensure_expense_category_modules(conn, builtin_categories=_builtins())
        cols = [row["name"] for row in conn.execute("PRAGMA table_info(expense_categories)").fetchall()]
        self.assertIn("module", cols)
        purchase = list_ledger_categories(conn, LEDGER_MODULE_PURCHASE)
        expense = list_ledger_categories(conn, LEDGER_MODULE_EXPENSE)
        self.assertTrue(any(row["category_key"] == "linen" for row in purchase))
        self.assertTrue(any(row["category_key"] == "linen" for row in expense))
        self.assertTrue(any(row["category_key"] == "grocery" for row in purchase))
        conn.close()


if __name__ == "__main__":
    unittest.main()
