import unittest

from workspace_access import (
    access_module_tree_ui,
    build_user_context,
    dashboard_access_list,
    get_endpoint_dashboard_module,
    get_endpoint_sales_analytics_submodules,
    sales_analytics_access_list,
    set_user_permissions,
    user_can_access_dashboard,
    user_can_access_endpoint_sales_analytics,
    user_can_access_sales_analytics_submodule,
    user_can_access_supplier_master,
)


class _FakeConn:
    def __init__(self, permissions=None):
        self.permissions = permissions or []
        self.executed = []

    def execute(self, sql, params=()):
        self.executed.append((sql, params))
        if "FROM user_permissions" in sql:
            return _FakeRows(self.permissions)
        return _FakeRows([])


class _FakeRows:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class WorkspaceAccessTests(unittest.TestCase):
    def test_registry_drives_access_tree(self):
        tree = access_module_tree_ui()
        labels = [node["label"] for node in tree]
        self.assertEqual(labels, ["Sales Analytics", "User & Access", "Accounts", "Employee Payroll"])
        sales_children = [child["label"] for child in tree[0]["children"]]
        self.assertEqual(
            sales_children,
            [
                "Dashboard",
                "Sales Update - Hotel",
                "Sales Update - Bar",
                "Sales Update - Restaurant",
                "Room Transfer",
            ],
        )

    def test_supplier_master_uses_accounts_access(self):
        user = {
            "id": 4,
            "is_admin": False,
            "dashboard_access": {"accounts"},
            "sales_analytics_access": set(),
            "user_access": set(),
        }
        self.assertTrue(user_can_access_supplier_master(user))
        self.assertEqual(get_endpoint_dashboard_module("supplier_master"), "accounts")

    def test_submodule_grants_parent_dashboard_access(self):
        user = {
            "id": 2,
            "is_admin": False,
            "dashboard_access": set(),
            "sales_analytics_access": {"hotel"},
            "user_access": set(),
        }
        self.assertTrue(user_can_access_dashboard(user, "sales_analytics"))
        self.assertFalse(user_can_access_dashboard(user, "access_management"))

    def test_shared_outlet_endpoint_allows_bar_or_restaurant(self):
        user = {
            "id": 3,
            "is_admin": False,
            "sales_analytics_access": {"bar"},
        }
        self.assertTrue(user_can_access_endpoint_sales_analytics(user, "save_sales_update"))
        user["sales_analytics_access"] = {"restaurant"}
        self.assertTrue(user_can_access_endpoint_sales_analytics(user, "save_sales_update"))
        user["sales_analytics_access"] = {"hotel"}
        self.assertFalse(user_can_access_endpoint_sales_analytics(user, "save_sales_update"))

    def test_set_user_permissions_auto_adds_parent_module(self):
        conn = _FakeConn()
        set_user_permissions(
            conn,
            user_id=5,
            dashboard_modules=[],
            sales_analytics_modules=["bar"],
            user_access_modules=[],
        )
        scopes = [params for sql, params in conn.executed if "INSERT INTO user_permissions" in sql]
        dashboard_rows = [row for row in scopes if row[1] == "dashboard"]
        sales_rows = [row for row in scopes if row[1] == "sales_analytics"]
        self.assertIn(("sales_analytics",), {(row[2],) for row in dashboard_rows})
        self.assertIn(("bar",), {(row[2],) for row in sales_rows})

    def test_endpoint_dashboard_mapping(self):
        self.assertEqual(get_endpoint_dashboard_module("dashboard"), "sales_analytics")
        self.assertEqual(get_endpoint_dashboard_module("access_management"), "access_management")
        self.assertEqual(get_endpoint_dashboard_module("accounts"), "accounts")
        self.assertEqual(get_endpoint_dashboard_module("purchase_ledger"), "accounts")
        self.assertEqual(get_endpoint_dashboard_module("purchase_ledger_add"), "accounts")
        self.assertEqual(get_endpoint_dashboard_module("purchase_ledger_edit"), "accounts")
        self.assertEqual(get_endpoint_dashboard_module("export_credit_payment_report"), "accounts")
        self.assertEqual(get_endpoint_dashboard_module("credit_payment"), "accounts")
        self.assertEqual(get_endpoint_dashboard_module("purchase_verification"), "accounts")
        self.assertEqual(get_endpoint_dashboard_module("create_credit_payment"), "accounts")
        self.assertEqual(get_endpoint_dashboard_module("delete_credit_payment"), "accounts")
        self.assertEqual(get_endpoint_dashboard_module("credit_payment_detail"), "accounts")
        self.assertEqual(get_endpoint_dashboard_module("create_purchase_verification"), "accounts")
        self.assertEqual(get_endpoint_dashboard_module("delete_purchase_verification"), "accounts")
        self.assertEqual(get_endpoint_dashboard_module("purchase_verification_detail"), "accounts")
        self.assertEqual(get_endpoint_dashboard_module("supplier_master"), "accounts")
        self.assertEqual(get_endpoint_dashboard_module("save_supplier"), "accounts")
        self.assertEqual(get_endpoint_sales_analytics_submodules("save_sales_update"), ["bar", "restaurant"])


if __name__ == "__main__":
    unittest.main()
