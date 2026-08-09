"""Unit tests for main dashboard top selling items ranking."""
import unittest

from main_dashboard_data import build_top_selling_items


class TopSellingItemsTests(unittest.TestCase):
    def test_ranks_by_qty_aggregates_outlets_and_limits_to_five(self):
        rows = [
            {"menu_item_id": 1, "item_name": "Butter Chicken", "qty_sold": 2, "sale_value": 400},
            {"menu_item_id": 1, "item_name": "Butter Chicken", "qty_sold": 3, "sale_value": 600},
            {"menu_item_id": 2, "item_name": "Naan", "qty_sold": 10, "sale_value": 500},
            {"menu_item_id": 3, "item_name": "Dal", "qty_sold": 8, "sale_value": 800},
            {"menu_item_id": 4, "item_name": "Rice", "qty_sold": 7, "sale_value": 350},
            {"menu_item_id": 5, "item_name": "Salad", "qty_sold": 6, "sale_value": 300},
            {"menu_item_id": 6, "item_name": "Soup", "qty_sold": 4, "sale_value": 400},
            {"menu_item_id": 7, "item_name": "Lassi", "qty_sold": 1, "sale_value": 80},
        ]
        out = build_top_selling_items(rows, limit=5)
        self.assertEqual(len(out), 5)
        self.assertEqual([r["name"] for r in out], ["Naan", "Dal", "Rice", "Salad", "Butter Chicken"])
        self.assertEqual([r["rank"] for r in out], [1, 2, 3, 4, 5])
        self.assertEqual(out[0]["qty"], 10)
        self.assertEqual(out[4]["qty"], 5)
        self.assertEqual(out[4]["sale_value"], 1000.0)
        self.assertEqual(out[4]["unit_price"], 200.0)
        self.assertEqual(out[4]["qty_label"], "5")
        self.assertEqual(out[4]["qty_display"], "5 sold")
        self.assertTrue(out[0]["sale_value_compact"].startswith("₹"))
        self.assertTrue(out[0]["unit_price_compact"].startswith("₹"))

    def test_fallback_name_key_when_menu_id_missing(self):
        rows = [
            {"menu_item_id": 0, "item_name": "Special Thali", "qty_sold": 2, "sale_value": 400},
            {"menu_item_id": 0, "item_name": "special thali", "qty_sold": 3, "sale_value": 600},
            {"menu_item_id": 0, "item_name": "Tea", "qty_sold": 4, "sale_value": 80},
        ]
        out = build_top_selling_items(rows, limit=5)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["name"], "Special Thali")
        self.assertEqual(out[0]["qty"], 5)
        self.assertEqual(out[0]["sale_value"], 1000.0)
        self.assertEqual(out[0]["unit_price"], 200.0)
        self.assertEqual(out[0]["qty_display"], "5 sold")
        self.assertEqual(out[1]["name"], "Tea")

    def test_sort_by_revenue(self):
        rows = [
            {"menu_item_id": 1, "item_name": "Cheap Popular", "qty_sold": 10, "sale_value": 100},
            {"menu_item_id": 2, "item_name": "Expensive Rare", "qty_sold": 2, "sale_value": 900},
        ]
        by_qty = build_top_selling_items(rows, limit=5, sort_by="qty")
        by_rev = build_top_selling_items(rows, limit=5, sort_by="revenue")
        self.assertEqual(by_qty[0]["name"], "Cheap Popular")
        self.assertEqual(by_rev[0]["name"], "Expensive Rare")
        self.assertEqual(by_rev[0]["sale_value"], 900.0)

    def test_skips_zero_qty_and_empty_input(self):
        self.assertEqual(build_top_selling_items([]), [])
        self.assertEqual(
            build_top_selling_items(
                [{"menu_item_id": 1, "item_name": "X", "qty_sold": 0, "sale_value": 0}]
            ),
            [],
        )


if __name__ == "__main__":
    unittest.main()
