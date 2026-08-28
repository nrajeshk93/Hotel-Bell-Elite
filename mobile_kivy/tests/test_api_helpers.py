from __future__ import annotations

import json
import unittest

from hbe_mobile.api.client import extract_script_json, extract_select_options, parse_history_rows
from hbe_mobile.api.dashboard import (
    VALID_PERIODS,
    fetch_dashboard,
    format_inr,
    snapshot_from_dashboard_data,
)
from hbe_mobile.api.pos import build_invoice_payload
from hbe_mobile.api import payroll as payroll_api
from hbe_mobile.models import InvoiceLine, Product
from hbe_mobile.utils.nav import NAV_ITEMS


class ExtractHelpersTests(unittest.TestCase):
    def test_extract_script_json(self):
        html = '''
        <html><script id="cp-outstanding-data" type="application/json">
        [{"id": 1, "balance": 10.5, "supplier_id": 2, "supplier_name": "Acme",
          "expense_code": "E1", "description": "Rice", "amount": 10.5}]
        </script></html>
        '''
        data = extract_script_json(html, "cp-outstanding-data")
        self.assertIsInstance(data, list)
        self.assertEqual(data[0]["id"], 1)

    def test_extract_md_dashboard_data(self):
        payload = {"period": "today", "kpis": [{"key": "sales", "label": "Sales", "value": 100}]}
        html = f'<script id="md-dashboard-data" type="application/json">{json.dumps(payload)}</script>'
        data = extract_script_json(html, "md-dashboard-data")
        self.assertEqual(data["period"], "today")
        self.assertEqual(len(data["kpis"]), 1)

    def test_extract_select_options(self):
        html = '''
        <select id="st-product-category">
          <option value="">Select</option>
          <option value="3">Dairy</option>
          <option value="9">Produce</option>
        </select>
        '''
        opts = extract_select_options(html, "st-product-category")
        self.assertEqual(opts, [("3", "Dairy"), ("9", "Produce")])

    def test_parse_history_rows(self):
        html = '''
        <tr class="cp-history-row" data-payment-id="42" data-search="x">
          <td class="cp-col-party"><div class="pl-name">Vendor</div></td>
          <td class="pl-col-date" data-sort-value="2026-08-01">01 Aug</td>
          <td class="pl-col-amount pl-amount" data-amount="500">500</td>
        </tr>
        '''
        rows = parse_history_rows(html)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], 42)
        self.assertEqual(rows[0]["supplier_name"], "Vendor")
        self.assertEqual(rows[0]["total_amount"], 500.0)


class ModelTests(unittest.TestCase):
    def test_product_from_api(self):
        p = Product.from_api(
            {"id": 5, "name": "Milk", "default_unit": "liter", "outlet": "both", "approximate_price": "40"}
        )
        self.assertEqual(p.id, 5)
        self.assertEqual(p.approximate_price, 40.0)

    def test_build_invoice_payload(self):
        lines = [InvoiceLine(uid="1", name="Tea", rate=20, qty=2, menu_id=9)]
        payload = build_invoice_payload(order_no="MOB-1", table="T1", lines=lines)
        self.assertEqual(payload["table"], "T1")
        self.assertEqual(payload["lines"][0]["name"], "Tea")
        self.assertEqual(payload["totals"]["subtotal"], 40)
        self.assertAlmostEqual(payload["totals"]["cgst"] + payload["totals"]["ugst"], payload["totals"]["gst"])
        self.assertGreater(payload["totals"]["total"], 0)

    def test_calc_bill_totals_inclusive(self):
        from hbe_mobile.api.pos import calc_bill_totals

        lines = [InvoiceLine(uid="1", name="Tea", rate=105, qty=1, menu_id=1)]
        totals = calc_bill_totals(lines)
        self.assertEqual(totals["subtotal"], 105.0)
        self.assertAlmostEqual(totals["cgst"], 2.5, places=1)
        self.assertAlmostEqual(totals["sgst"], 2.5, places=1)
        self.assertEqual(totals["total"], 105.0)

    def test_has_pending_kot(self):
        from hbe_mobile.api.pos import has_pending_kot

        pending = [InvoiceLine(uid="1", name="Tea", rate=10, qty=2, menu_id=1, kot_sent_qty=0)]
        self.assertTrue(has_pending_kot(pending))
        sent = [InvoiceLine(uid="1", name="Tea", rate=10, qty=2, menu_id=1, kot_sent_qty=2)]
        self.assertFalse(has_pending_kot(sent))
        partial = [InvoiceLine(uid="1", name="Tea", rate=10, qty=3, menu_id=1, kot_sent_qty=1)]
        self.assertTrue(has_pending_kot(partial))
        self.assertFalse(has_pending_kot([]))

    def test_build_kot_reduce_payload(self):
        from hbe_mobile.api.pos import build_kot_reduce_payload

        payload = build_kot_reduce_payload(
            [
                {"invoice_id": 12, "line_id": 45, "sent_qty": 1},
                {"invoiceId": 12, "lineId": 46, "qty": 2},
                {"invoice_id": 0, "line_id": 1, "sent_qty": 1},
                "skip",
            ],
            reason="Guest changed mind",
        )
        self.assertEqual(
            payload["changes"],
            [
                {"invoice_id": 12, "line_id": 45, "sent_qty": 1.0},
                {"invoice_id": 12, "line_id": 46, "sent_qty": 2.0},
            ],
        )
        self.assertEqual(payload["reason"], "Guest changed mind")
        bare = build_kot_reduce_payload([])
        self.assertEqual(bare, {"changes": []})
        self.assertNotIn("reason", bare)

    def test_format_kot_slip_text(self):
        from hbe_mobile.api.pos import format_kot_slip_text

        text = format_kot_slip_text(
            {"kot_no": "KOT/1", "name": "T1"},
            [{"name": "Tea", "sent_qty": 2, "variant": "Hot", "notes": "less sugar"}],
        )
        self.assertIn("KITCHEN ORDER TOKEN", text)
        self.assertIn("REPRINT / RESEND", text)
        self.assertIn("KOT/1", text)
        self.assertIn("T1", text)
        self.assertIn("2  Tea (Hot)", text)
        self.assertIn("less sugar", text)
        self.assertIn("-- Resent for kitchen --", text)


class _FakePosClient:
    def __init__(self):
        self.calls: list[tuple[str, str, object]] = []
        self.get_response: dict = {"ok": True, "token_count": 1, "tables": []}
        self.post_response: dict = {"ok": True, "updated_count": 1}

    def get_json(self, path, *, params=None):
        self.calls.append(("GET", path, params))
        return dict(self.get_response)

    def post_json(self, path, body):
        self.calls.append(("POST", path, body))
        return dict(self.post_response)


class PosApiKotTests(unittest.TestCase):
    def test_list_and_reduce_kot_token_paths(self):
        from hbe_mobile.api.pos import PosApi

        client = _FakePosClient()
        api = PosApi(client, base="/point-of-sale")
        listed = api.list_kot_tokens()
        self.assertTrue(listed.get("ok"))
        self.assertEqual(client.calls[0][:2], ("GET", "/point-of-sale/api/kot-tokens"))

        result = api.reduce_kot_tokens(
            [{"invoice_id": 9, "line_id": 3, "sent_qty": 1}],
            reason="cancel item",
        )
        self.assertTrue(result.get("ok"))
        method, path, body = client.calls[1]
        self.assertEqual(method, "POST")
        self.assertEqual(path, "/point-of-sale/api/kot-tokens/reduce")
        self.assertEqual(body["reason"], "cancel item")
        self.assertEqual(body["changes"][0]["line_id"], 3)


class _FakeDashboardClient:
    def __init__(self, html: str = "<html></html>"):
        self.html = html
        self.last_path = None
        self.last_params = None

    def get_text(self, path, *, params=None):
        self.last_path = path
        self.last_params = params
        return self.html


def _md_dashboard_embed(payload: dict) -> str:
    return (
        '<script id="md-dashboard-data" type="application/json">'
        + json.dumps(payload)
        + "</script>"
    )


SAMPLE_MD_DASHBOARD = {
    "kpis": [
        {"key": "cash", "label": "Cash Collection", "value": 43456.78, "change_pct": -1.0},
        {
            "key": "actual_sales",
            "label": "Total Sales",
            "value": 123456.78,
            "change_pct": 5.2,
            "prior": 117353.0,
        },
        {"key": "expense", "label": "Expense", "value": 10000, "change_pct": 0.0},
        {"key": "digital_transactions", "label": "Digital Collection", "value": 80000, "change_pct": 2.0},
        {"key": "difference", "label": "Difference", "value": 50},
    ],
    "sales_trend": {
        "avg_daily": 12345.0,
        "avg_daily_compact": "₹12,345",
        "best_day": {
            "date": "2026-08-20",
            "value": 20000,
            "value_compact": "₹20,000",
            "label": "20 Aug 2026",
        },
        "lowest_day": {
            "date": "2026-08-21",
            "value": 5000,
            "value_compact": "₹5,000",
            "label": "21 Aug 2026",
        },
    },
    "company_leaderboard": [
        {"name": "Hotel", "label": "Hotel", "sales": 80000, "share_pct": 65.0},
        {"name": "Restaurant", "label": "Restaurant", "sales": 43456.78, "share_pct": 35.0},
    ],
    "digital_cash_stack": [{"date": "2026-08-20", "digital_pct": 64.8, "cash_pct": 35.2}],
    "payment_mode": {
        "digital_pct": 64.8,
        "cash_pct": 35.2,
        "digital_trend": 1.2,
        "cash_trend": -1.2,
    },
    "top_selling_items": [{"name": "Naan", "qty": 10, "sale_value": 500}],
    "top_selling_items_by_revenue": [{"name": "Butter Chicken", "qty": 5, "sale_value": 1000}],
}


class DashboardFetchTests(unittest.TestCase):
    def test_period_allowlist_rejects_week_and_month(self):
        client = _FakeDashboardClient()
        for bad in ("week", "month", "WEEK", "custom"):
            with self.assertRaises(ValueError):
                fetch_dashboard(client, period=bad)
        self.assertIsNone(client.last_path)
        self.assertEqual(
            VALID_PERIODS,
            ("today", "yesterday", "7d", "30d", "mtd", "qtd", "ytd"),
        )
        self.assertNotIn("week", VALID_PERIODS)
        self.assertNotIn("month", VALID_PERIODS)

    def test_location_query_passthrough(self):
        html = _md_dashboard_embed(SAMPLE_MD_DASHBOARD)
        client = _FakeDashboardClient(html)
        snap = fetch_dashboard(client, period="today", location="Hotel")
        self.assertEqual(client.last_path, "/main-dashboard")
        self.assertEqual(client.last_params, {"period": "today", "location": "Hotel"})
        self.assertEqual(snap.location, "Hotel")

        omitted = _FakeDashboardClient(html)
        fetch_dashboard(omitted, period="7d", location=None)
        self.assertEqual(omitted.last_params, {"period": "7d"})

        all_loc = _FakeDashboardClient(html)
        snap_all = fetch_dashboard(all_loc, period="mtd", location="All")
        self.assertEqual(all_loc.last_params, {"period": "mtd"})
        self.assertEqual(snap_all.location, "All")

    def test_kpi_order_and_key_mapping_from_md_dashboard_data(self):
        snap = snapshot_from_dashboard_data(SAMPLE_MD_DASHBOARD, period="today")
        self.assertEqual(
            [row["key"] for row in snap.kpis],
            ["actual_sales", "digital_transactions", "cash", "expense", "difference"],
        )
        self.assertEqual(
            [row["label"] for row in snap.kpis],
            ["Sales", "Digital", "Cash", "Expense", "Difference"],
        )
        by_key = {row["key"]: row for row in snap.kpis}
        self.assertEqual(by_key["actual_sales"]["value"], 123456.78)
        self.assertEqual(by_key["actual_sales"]["change_pct"], 5.2)
        self.assertEqual(by_key["actual_sales"]["prior"], 117353.0)
        self.assertEqual(by_key["digital_transactions"]["value"], 80000)
        self.assertNotIn("change_pct", by_key["difference"])
        self.assertTrue(by_key["actual_sales"]["value_display"].startswith("₹"))

        self.assertEqual(snap.sales_trend["avg"], 12345.0)
        self.assertEqual(snap.sales_trend["best"]["amount"], 20000)
        self.assertEqual(snap.sales_trend["lowest"]["label"], "21 Aug 2026")
        self.assertEqual(snap.company_leaderboard[0]["name"], "Hotel")
        self.assertEqual(snap.company_leaderboard[0]["amount"], 80000)
        self.assertEqual(snap.payment_mix["digital_pct"], 64.8)
        self.assertEqual(snap.payment_mix["cash_pct"], 35.2)
        self.assertEqual(snap.top_selling_items[0]["name"], "Naan")
        self.assertEqual(snap.top_selling_items_by_revenue[0]["name"], "Butter Chicken")

    def test_kpi_mapping_from_top_level_keys(self):
        raw = {
            "actual_sales": 10,
            "digital_transactions": 6,
            "cash": 4,
            "expense": 1,
            "difference": 0.5,
        }
        snap = snapshot_from_dashboard_data(raw, period="yesterday")
        self.assertEqual([row["key"] for row in snap.kpis], [
            "actual_sales",
            "digital_transactions",
            "cash",
            "expense",
            "difference",
        ])
        self.assertEqual(snap.kpis[0]["value"], 10.0)
        self.assertEqual(snap.period, "yesterday")

    def test_format_inr_indian_grouping(self):
        self.assertEqual(format_inr(1234567), "₹12,34,567")
        self.assertEqual(format_inr(1234.5, decimals=2), "₹1,234.50")




class _FakeIndentClient:
    def __init__(self):
        self.calls: list[tuple[str, str, object]] = []
        self.get_response: dict = {
            "ok": True,
            "outlet": "restaurant",
            "categories": [
                {
                    "id": 1,
                    "name": "Vegetable",
                    "products": [
                        {
                            "id": 9,
                            "name": "Onion",
                            "default_unit": "kg",
                            "outlet": "both",
                            "approximate_price": 40,
                            "approximate_price_display": "40",
                            "variants": [
                                {
                                    "label": "Bag 10 kg",
                                    "qty_in_base": 10,
                                    "qty_in_base_display": "10",
                                    "approximate_price": 380,
                                    "approximate_price_display": "380",
                                }
                            ],
                        }
                    ],
                }
            ],
        }
        self.post_response: dict = {"ok": True, "indent_id": 3, "indent_no": "IND/RES/26-27/1", "status": "pending"}

    def get_json(self, path, *, params=None):
        self.calls.append(("GET", path, params))
        return dict(self.get_response)

    def post_json(self, path, body):
        self.calls.append(("POST", path, body))
        return dict(self.post_response)


class IndentRequestApiHelperTests(unittest.TestCase):
    def test_flatten_validate_totals_and_submit_payload(self):
        from hbe_mobile.api import indent_request as indent_api

        client = _FakeIndentClient()
        data = indent_api.fetch_catalog(client, "restaurant")
        self.assertTrue(data.get("ok"))
        self.assertEqual(client.calls[0][:2], ("GET", "/stores/api/indent-catalog"))
        self.assertEqual(client.calls[0][2], {"outlet": "restaurant"})

        products = indent_api.flatten_catalog(data)
        self.assertEqual(len(products), 1)
        self.assertEqual(products[0]["name"], "Onion")
        self.assertEqual(products[0]["category_name"], "Vegetable")
        self.assertEqual(len(products[0]["variants"]), 1)

        self.assertEqual(indent_api.line_total(2, 12.5), 25.0)
        self.assertEqual(indent_api.line_total("3", "10"), 30.0)
        self.assertEqual(indent_api.line_total(None, 10), 0.0)

        self.assertEqual(indent_api.validate_lines([]), "Add at least one item with a quantity.")
        self.assertEqual(
            indent_api.validate_lines([{"item_name": "", "quantity": 1, "approximate_price": 10}]),
            "Item is required.",
        )
        self.assertEqual(
            indent_api.validate_lines([{"item_name": "Onion", "quantity": 0, "approximate_price": 10}]),
            "Enter a quantity greater than 0 for each item.",
        )
        self.assertEqual(
            indent_api.validate_lines([{"item_name": "Onion", "quantity": 1, "approximate_price": 0}]),
            "Enter an approximate price greater than 0 for each item.",
        )
        self.assertIsNone(
            indent_api.validate_lines([{"item_name": "Onion", "quantity": 1, "approximate_price": 10}])
        )

        lines = [{
            "item_name": "Onion",
            "quantity": 2,
            "unit": "kg",
            "approximate_price": 40,
            "pack_label": "Bag 10 kg",
            "pack_qty_in_base": 10,
        }]
        result = indent_api.submit_indent(
            client,
            outlet="restaurant",
            notes="need stock",
            action="submit",
            lines=lines,
        )
        self.assertTrue(result.get("ok"))
        method, path, body = client.calls[1]
        self.assertEqual(method, "POST")
        self.assertEqual(path, "/stores/api/indent")
        self.assertEqual(body["outlet"], "restaurant")
        self.assertEqual(body["action"], "submit")
        self.assertEqual(body["notes"], "need stock")
        self.assertEqual(body["lines"][0]["item_name"], "Onion")
        self.assertEqual(body["lines"][0]["pack_label"], "Bag 10 kg")
        self.assertEqual(body["lines"][0]["pack_qty_in_base"], 10)

        indent_api.submit_indent(
            client,
            outlet="bar",
            notes="",
            action="save",
            lines=[{"item_name": "Onion", "quantity": 1, "unit": "kg", "approximate_price": 10}],
        )
        self.assertEqual(client.calls[2][2]["action"], "save")


class PayrollHelperTests(unittest.TestCase):
    def test_validate_employee_and_credit_and_tip(self):
        self.assertEqual(payroll_api.validate_employee_payload("", "9876543210"), "Employee Name is required.")
        self.assertEqual(payroll_api.validate_employee_payload("Anita", "123"), "Mobile number must be exactly 10 digits.")
        self.assertIsNone(payroll_api.validate_employee_payload("Anita", "9876543210"))
        self.assertIsNone(payroll_api.validate_attendance_status("present"))
        self.assertIsNone(payroll_api.validate_attendance_status(""))
        self.assertIsNotNone(payroll_api.validate_attendance_status("late"))
        self.assertIn("Transaction ID", payroll_api.validate_credit_payload(1, 50, "credit", "bank_transfer", "") or "")
        self.assertIsNone(payroll_api.validate_credit_payload(1, 50, "credit", "bank_transfer", "UTR1"))
        self.assertIsNone(payroll_api.validate_tip_payload(3, 20, "Hotel"))
        self.assertIsNotNone(payroll_api.validate_tip_payload(0, 20, "Hotel"))

    def test_fetch_helpers_use_mobile_paths(self):
        client = _FakeIndentClient()
        client.get_response = {"ok": True, "employees": [], "year": 2026, "month": 8}
        payroll_api.fetch_employees(client, q="an", status="active")
        self.assertEqual(client.calls[0][1], "/api/mobile/payroll/employees")
        client.post_response = {"ok": True}
        payroll_api.mark_attendance(client, 9, "2026-08-28", "present")
        self.assertEqual(client.calls[-1][1], "/api/mobile/payroll/attendance/mark")
        payroll_api.add_credit(client, {
            "employee_id": 9, "date": "2026-08-28", "amount": 100,
            "transaction_type": "credit", "payment_type": "cash",
        })
        self.assertEqual(client.calls[-1][1], "/api/mobile/payroll/credits")
        payroll_api.add_tip(client, {"employee_id": 9, "amount": 10, "location": "Hotel", "date": "2026-08-28"})
        self.assertEqual(client.calls[-1][1], "/api/mobile/payroll/tips")

    def test_nav_includes_payroll_group(self):
        keys = {item["access_key"] for item in NAV_ITEMS}
        self.assertTrue({"payroll_employee", "payroll_attendance", "payroll_credit", "payroll_tips"} <= keys)
        groups = {item["group"] for item in NAV_ITEMS if item.get("access_key", "").startswith("payroll_")}
        self.assertEqual(groups, {"Employee Payroll"})


if __name__ == "__main__":
    unittest.main()
