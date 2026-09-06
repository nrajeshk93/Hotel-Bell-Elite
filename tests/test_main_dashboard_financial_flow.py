"""Main Dashboard Sankey financial flow payload."""

import unittest

from main_dashboard_data import build_financial_flow


class FinancialFlowBuilderTests(unittest.TestCase):
    def test_separates_purchase_and_expense_categories(self):
        flow = build_financial_flow(
            {"Hotel": 1000, "Restaurant": 600, "Bar": 400},
            [
                {"key": "grocery", "name": "Grocery", "amount": 300},
                {"key": "liquor", "name": "Liquor", "amount": 200},
            ],
            [
                {"key": "salary", "name": "Salary", "amount": 150},
                {"key": "fuel", "name": "Fuel", "amount": 50},
            ],
            tax_amount=100,
        )
        self.assertEqual(flow["total_revenue"], 2000.0)
        self.assertEqual(flow["purchase_total"], 500.0)
        self.assertEqual(flow["expense_total"], 200.0)
        self.assertEqual(flow["profit_before_tax"], 1300.0)
        self.assertEqual(flow["tax"], 100.0)
        self.assertEqual(flow["net_profit"], 1200.0)
        self.assertEqual(
            [c["name"] for c in flow["purchase_categories"]],
            ["Grocery", "Liquor"],
        )
        self.assertEqual(
            [c["name"] for c in flow["expense_categories"]],
            ["Salary", "Fuel"],
        )
        self.assertEqual(len(flow["sources"]), 3)

    def test_rolls_up_categories_beyond_top_four(self):
        purchase = [
            {"key": f"p{i}", "name": f"Purchase {i}", "amount": 100 - i}
            for i in range(8)
        ]
        expense = [
            {"key": f"e{i}", "name": f"Expense {i}", "amount": 50 - i}
            for i in range(7)
        ]
        flow = build_financial_flow(
            {"Hotel": 2000, "Restaurant": 0, "Bar": 0},
            purchase,
            expense,
            tax_amount=10,
        )
        self.assertEqual(len(flow["purchase_categories"]), 5)
        self.assertEqual(
            [c["name"] for c in flow["purchase_categories"][:4]],
            ["Purchase 0", "Purchase 1", "Purchase 2", "Purchase 3"],
        )
        self.assertEqual(flow["purchase_categories"][-1]["name"], "Other Purchase")
        self.assertEqual(
            flow["purchase_categories"][-1]["amount"],
            round(sum(100 - i for i in range(4, 8)), 2),
        )
        self.assertEqual(len(flow["expense_categories"]), 5)
        self.assertEqual(flow["expense_categories"][-1]["name"], "Other Expenses")
        self.assertEqual(
            flow["purchase_total"],
            round(sum(c["amount"] for c in flow["purchase_categories"]), 2),
        )
        self.assertEqual(
            flow["expense_total"],
            round(sum(c["amount"] for c in flow["expense_categories"]), 2),
        )

    def test_tax_capped_by_profit_before_tax(self):
        flow = build_financial_flow(
            {"Hotel": 500, "Restaurant": 0, "Bar": 0},
            [{"key": "grocery", "name": "Grocery", "amount": 200}],
            [{"key": "salary", "name": "Salary", "amount": 200}],
            tax_amount=400,
        )
        self.assertEqual(flow["profit_before_tax"], 100.0)
        self.assertEqual(flow["tax"], 100.0)
        self.assertEqual(flow["net_profit"], 0.0)
        self.assertEqual(flow["tax_collected"], 400.0)


if __name__ == "__main__":
    unittest.main()
