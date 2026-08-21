import os
import tempfile
import unittest

import db as db_mod
from workspace_access import (
    access_module_tree_ui,
    accounts_access_list,
    build_user_context,
    dashboard_access_list,
    delete_access_role,
    ensure_access_roles_schema,
    get_endpoint_accounts_submodule,
    get_endpoint_dashboard_module,
    get_endpoint_sales_analytics_submodules,
    get_endpoint_user_access_submodule,
    is_built_in_administrator_role,
    reconcile_super_admin_only_dashboard_modules,
    save_access_role_record,
    save_access_user_record,
    sales_analytics_access_list,
    set_user_permissions,
    user_can_access_accounts_submodule,
    user_can_access_dashboard,
    user_can_access_endpoint_accounts,
    user_can_access_endpoint_sales_analytics,
    user_can_access_sales_analytics_submodule,
    user_can_access_supplier_master,
    user_can_access_user_access_submodule,
    user_can_approve_transactions,
    user_can_edit_kot_sent_lines,
    user_can_edit_unsettled_invoices,
    user_has_assigned_access_role,
    validate_access_role_form,
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
        self.assertEqual(
            labels,
            [
                "Dashboard",
                "Sales Analytics",
                "User & Access",
                "Accounts",
                "Employee Payroll",
                "Restaurant",
                "Bar",
                "Hotel",
                "Communication Hub",
                "Purchase & Inventory",
                "Master",
                "Report",
                "Settings",
                "Approval",
                "Cancellation",
                "Edit",
            ],
        )
        stores = next(node for node in tree if node["label"] == "Purchase & Inventory")
        stores_children = [child["label"] for child in stores["children"]]
        self.assertEqual(
            stores_children,
            [
                "Indent",
                "Approvals",
                "Stock Inward",
                "Store",
                "Stock Audit",
            ],
        )
        indent_node = next(child for child in stores["children"] if child["label"] == "Indent")
        self.assertEqual(
            [child["label"] for child in indent_node["children"]],
            ["Products"],
        )
        self.assertEqual(indent_node["children"][0]["id"], "stores.product_master")
        self.assertEqual(indent_node["children"][0]["fieldValue"], "product_master")
        main_dashboard = next(node for node in tree if node["label"] == "Dashboard")
        self.assertEqual(main_dashboard["id"], "main_dashboard")
        self.assertEqual(main_dashboard["children"], [])
        sales = next(node for node in tree if node["label"] == "Sales Analytics")
        sales_children = [child["label"] for child in sales["children"]]
        self.assertEqual(
            sales_children,
            [
                "Dashboard",
                "Sales Update - Hotel",
                "Sales Update - Bar",
                "Sales Update - Restaurant",
                "Room Transfer",
                "Credit",
            ],
        )
        user_access = next(node for node in tree if node["label"] == "User & Access")
        self.assertEqual(
            [child["label"] for child in user_access["children"]],
            ["Users", "Add User", "Roles", "Logs"],
        )
        settings = next(node for node in tree if node["label"] == "Settings")
        self.assertEqual(settings["id"], "settings")
        self.assertEqual(settings["icon"], "settings")
        self.assertEqual(settings["children"], [])
        approval = next(node for node in tree if node["label"] == "Approval")
        self.assertEqual(approval["id"], "approval")
        self.assertEqual(approval["icon"], "badge-check")
        self.assertEqual(approval["children"], [])
        self.assertTrue(approval.get("superAdminOnly"))
        self.assertIn("Super Administrator", approval.get("description") or "")
        cancellation = next(node for node in tree if node["label"] == "Cancellation")
        self.assertEqual(cancellation["id"], "cancellation_access")
        self.assertEqual(cancellation["icon"], "ban")
        self.assertEqual(cancellation["children"], [])
        self.assertTrue(cancellation.get("superAdminOnly"))
        self.assertIn("Kitchen Order", cancellation.get("description") or "")
        self.assertIn("Super Administrator", cancellation.get("description") or "")
        edit = next(node for node in tree if node["label"] == "Edit")
        self.assertEqual(edit["id"], "edit_access")
        self.assertEqual(edit["icon"], "pencil")
        self.assertEqual(edit["children"], [])
        self.assertTrue(edit.get("superAdminOnly"))
        self.assertIn("folio", (edit.get("description") or "").lower())
        self.assertIn("Super Administrator", edit.get("description") or "")
        accounts = next(node for node in tree if node["label"] == "Accounts")
        accounts_children = [child["label"] for child in accounts["children"]]
        self.assertEqual(
            accounts_children,
            [
                "Purchases & Expenses",
                "Cash Ledger",
                "Approvals",
                "Credit Payment",
                "Supplier Master",
            ],
        )
        pos = next(node for node in tree if node["label"] == "Restaurant")
        self.assertEqual(pos["dashboardKey"], "point_of_sale")
        self.assertEqual(pos["children"], [])
        stores = next(node for node in tree if node["label"] == "Purchase & Inventory")
        self.assertEqual(stores["dashboardKey"], "stores")
        self.assertEqual(len(stores["children"]), 5)
        master = next(node for node in tree if node["label"] == "Master")
        self.assertEqual(master["dashboardKey"], "master")
        self.assertEqual(master["children"], [])
        report = next(node for node in tree if node["label"] == "Report")
        self.assertEqual(report["dashboardKey"], "reports")
        self.assertEqual(report["children"], [])

    def test_cancellation_access_unlocks_kot_sent_line_edits(self):
        locked = {
            "id": 11,
            "is_admin": False,
            "dashboard_access": {"point_of_sale"},
        }
        unlocked = {
            "id": 12,
            "is_admin": False,
            "dashboard_access": {"point_of_sale", "cancellation_access"},
        }
        admin = {"id": 1, "is_admin": True, "dashboard_access": set()}
        self.assertFalse(user_can_edit_kot_sent_lines(locked))
        self.assertTrue(user_can_edit_kot_sent_lines(unlocked))
        self.assertTrue(user_can_edit_kot_sent_lines(admin))

    def test_edit_access_unlocks_unsettled_invoice_edits(self):
        locked = {
            "id": 13,
            "is_admin": False,
            "dashboard_access": {"point_of_sale"},
        }
        unlocked = {
            "id": 14,
            "is_admin": False,
            "dashboard_access": {"point_of_sale", "edit_access"},
        }
        admin = {"id": 1, "is_admin": True, "dashboard_access": set()}
        self.assertFalse(user_can_edit_unsettled_invoices(locked))
        self.assertTrue(user_can_edit_unsettled_invoices(unlocked))
        self.assertTrue(user_can_edit_unsettled_invoices(admin))

    def test_approval_access_unlocks_purchase_verification_actions(self):
        locked = {
            "id": 21,
            "is_admin": False,
            "dashboard_access": {"accounts"},
        }
        unlocked = {
            "id": 22,
            "is_admin": False,
            "dashboard_access": {"accounts", "approval"},
        }
        admin = {"id": 1, "is_admin": True, "dashboard_access": set()}
        self.assertFalse(user_can_approve_transactions(locked))
        self.assertTrue(user_can_approve_transactions(unlocked))
        self.assertTrue(user_can_approve_transactions(admin))

    def test_indent_approvals_require_approval_module(self):
        from workspace_access import user_can_access_stores_submodule

        stores_only = {
            "id": 31,
            "is_admin": False,
            "dashboard_access": {"stores"},
            "stores_access": {"indent", "approvals", "stock"},
        }
        with_approval = {
            "id": 32,
            "is_admin": False,
            "dashboard_access": {"stores", "approval"},
            "stores_access": {"indent", "stock"},
        }
        self.assertFalse(user_can_access_stores_submodule(stores_only, "approvals"))
        self.assertFalse(user_can_approve_transactions(stores_only))
        self.assertTrue(user_can_access_stores_submodule(with_approval, "approvals"))
        self.assertTrue(user_can_approve_transactions(with_approval))
        self.assertTrue(user_can_access_stores_submodule(with_approval, "indent"))

    def test_supplier_master_uses_accounts_access(self):
        user = {
            "id": 4,
            "is_admin": False,
            "dashboard_access": {"accounts"},
            "sales_analytics_access": set(),
            "user_access": set(),
            "accounts_access": set(),
        }
        self.assertTrue(user_can_access_supplier_master(user))
        self.assertEqual(get_endpoint_dashboard_module("supplier_master"), "accounts")
        self.assertEqual(get_endpoint_dashboard_module("cash_ledger"), "accounts")
        self.assertEqual(get_endpoint_dashboard_module("cash_ledger_available"), "accounts")
        self.assertEqual(get_endpoint_dashboard_module("cash_ledger_load"), "accounts")
        self.assertEqual(get_endpoint_dashboard_module("cash_ledger_transfer"), "accounts")
        self.assertEqual(get_endpoint_dashboard_module("export_cash_ledger_report"), "accounts")
        self.assertEqual(get_endpoint_dashboard_module("export_purchase_ledger_report"), "accounts")
        self.assertEqual(get_endpoint_dashboard_module("export_supplier_report"), "accounts")

    def test_accounts_submodule_grants_only_selected_pages(self):
        user = {
            "id": 6,
            "is_admin": False,
            "dashboard_access": {"accounts"},
            "accounts_access": {"cash_ledger"},
            "sales_analytics_access": set(),
            "user_access": set(),
        }
        self.assertTrue(user_can_access_dashboard(user, "accounts"))
        self.assertTrue(user_can_access_accounts_submodule(user, "cash_ledger"))
        self.assertFalse(user_can_access_accounts_submodule(user, "purchase_ledger"))
        self.assertTrue(user_can_access_endpoint_accounts(user, "cash_ledger"))
        self.assertFalse(user_can_access_endpoint_accounts(user, "purchase_ledger"))
        self.assertEqual(get_endpoint_accounts_submodule("purchase_ledger"), "purchase_ledger")
        self.assertEqual(accounts_access_list(user), ["cash_ledger"])

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
        self.assertTrue(user_can_access_endpoint_sales_analytics(user, "save_sales_update"))
        user["sales_analytics_access"] = {"room_transfer"}
        self.assertFalse(user_can_access_endpoint_sales_analytics(user, "save_sales_update"))
        pos_user = {
            "id": 4,
            "is_admin": False,
            "dashboard_access": {"point_of_sale"},
            "sales_analytics_access": set(),
        }
        self.assertTrue(user_can_access_endpoint_sales_analytics(pos_user, "save_sales_update"))
        self.assertTrue(user_can_access_endpoint_sales_analytics(pos_user, "sales_update_add_tip"))

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
        self.assertEqual(get_endpoint_dashboard_module("purchase_ledger_delete"), "accounts")
        self.assertEqual(get_endpoint_dashboard_module("export_purchase_ledger_report"), "accounts")
        self.assertEqual(get_endpoint_dashboard_module("export_credit_payment_report"), "accounts")
        self.assertEqual(get_endpoint_dashboard_module("export_purchase_verification_report"), "accounts")
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
        self.assertEqual(get_endpoint_dashboard_module("export_supplier_report"), "accounts")
        self.assertEqual(get_endpoint_dashboard_module("hotel_rooms"), "hotel_rooms")
        self.assertEqual(get_endpoint_dashboard_module("hotel_credit"), "hotel_rooms")
        self.assertEqual(get_endpoint_dashboard_module("communication_hub"), "communication_hub")
        self.assertEqual(get_endpoint_dashboard_module("communication_hub_api_conversations"), "communication_hub")
        self.assertEqual(get_endpoint_dashboard_module("stores"), "stores")
        self.assertEqual(get_endpoint_dashboard_module("stores_indent"), "stores")
        self.assertEqual(get_endpoint_dashboard_module("point_of_sale"), "point_of_sale")
        self.assertEqual(get_endpoint_dashboard_module("point_of_sale_invoice"), "point_of_sale")
        self.assertEqual(get_endpoint_dashboard_module("point_of_sale_invoice_ledger"), "point_of_sale")
        self.assertEqual(get_endpoint_dashboard_module("point_of_sale_sales_update"), "point_of_sale")
        self.assertEqual(get_endpoint_dashboard_module("export_pos_invoice_ledger_report"), "point_of_sale")
        self.assertEqual(get_endpoint_dashboard_module("point_of_sale_settings"), "point_of_sale")
        self.assertEqual(get_endpoint_dashboard_module("point_of_sale_api_floor"), "point_of_sale")
        self.assertEqual(get_endpoint_dashboard_module("point_of_sale_api_settings"), "point_of_sale")
        self.assertEqual(get_endpoint_dashboard_module("point_of_sale_api_menu_categories"), "point_of_sale")
        self.assertEqual(get_endpoint_dashboard_module("point_of_sale_api_menu_items"), "point_of_sale")
        self.assertEqual(get_endpoint_dashboard_module("point_of_sale_api_menu_items_bulk"), "point_of_sale")
        self.assertEqual(get_endpoint_dashboard_module("point_of_sale_api_menu_items_bulk_template"), "point_of_sale")
        self.assertEqual(get_endpoint_dashboard_module("point_of_sale_api_menu_products"), "point_of_sale")
        self.assertEqual(get_endpoint_dashboard_module("point_of_sale_api_invoices_save"), "point_of_sale")
        self.assertEqual(get_endpoint_dashboard_module("point_of_sale_api_invoice_detail"), "point_of_sale")
        self.assertEqual(get_endpoint_dashboard_module("point_of_sale_api_invoice_delete"), "point_of_sale")
        self.assertEqual(get_endpoint_dashboard_module("master"), "master")
        self.assertEqual(get_endpoint_dashboard_module("reports"), "reports")
        self.assertEqual(get_endpoint_dashboard_module("sales_report_hotel"), "reports")
        self.assertEqual(get_endpoint_dashboard_module("sales_report_hotel_export"), "reports")
        self.assertEqual(get_endpoint_dashboard_module("sales_report_manager_insight"), "reports")
        self.assertEqual(get_endpoint_dashboard_module("sales_report_manager_insight_export"), "reports")
        self.assertEqual(get_endpoint_dashboard_module("sales_report_meal_plan"), "reports")
        self.assertEqual(get_endpoint_dashboard_module("sales_report_meal_plan_export"), "reports")
        self.assertEqual(get_endpoint_dashboard_module("sales_report_restaurant"), "reports")
        self.assertEqual(get_endpoint_dashboard_module("sales_report_restaurant_export"), "reports")
        self.assertEqual(get_endpoint_dashboard_module("sales_report_bar"), "reports")
        self.assertEqual(get_endpoint_dashboard_module("sales_report_bar_export"), "reports")
        self.assertEqual(get_endpoint_dashboard_module("settings"), "settings")
        self.assertEqual(
            get_endpoint_sales_analytics_submodules("save_sales_update"),
            ["hotel", "bar", "restaurant"],
        )
        self.assertEqual(get_endpoint_dashboard_module("access_roles"), "access_management")
        self.assertEqual(get_endpoint_dashboard_module("save_access_role"), "access_management")
        self.assertEqual(get_endpoint_dashboard_module("delete_access_role"), "access_management")
        self.assertEqual(get_endpoint_user_access_submodule("access_roles"), "roles")
        self.assertEqual(get_endpoint_user_access_submodule("save_access_role"), "roles")
        self.assertEqual(get_endpoint_user_access_submodule("delete_access_role"), "roles")
        self.assertEqual(get_endpoint_user_access_submodule("access_login_logs"), "logs")
        self.assertEqual(get_endpoint_dashboard_module("access_login_logs"), "access_management")
        self.assertEqual(get_endpoint_user_access_submodule("toggle_access_user_active"), "users")
        self.assertEqual(
            get_endpoint_dashboard_module("toggle_access_user_active"),
            "access_management",
        )


class RoleBasedAccessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db_path = self.tmp.name
        self._orig_path = db_mod.DATABASE_PATH
        db_mod.DATABASE_PATH = self.db_path
        db_mod.init_db()
        self.conn = db_mod.get_db()

    def tearDown(self):
        self.conn.close()
        db_mod.DATABASE_PATH = self._orig_path
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def test_migration_assigns_administrator_to_seeded_admin(self):
        row = self.conn.execute(
            "SELECT * FROM users WHERE username = ?",
            ("admin",),
        ).fetchone()
        user = build_user_context(self.conn, row)
        self.assertTrue(user["is_admin"])
        self.assertEqual(user["role_name"], "Super Administrator")
        self.assertTrue(user_can_access_dashboard(user, "settings"))
        self.assertTrue(user_can_access_user_access_submodule(user, "roles"))
        self.assertTrue(user_can_access_user_access_submodule(user, "logs"))

    def test_only_super_administrator_role_can_have_full_authority(self):
        actor = {"id": 1, "is_admin": True, "user_access": {"roles"}}
        errors, _ = validate_access_role_form(
            self.conn,
            actor=actor,
            role_id=None,
            name="Night Manager",
            is_admin=True,
            dashboard_modules=[],
            sales_analytics_modules=[],
            user_access_modules=[],
        )
        self.assertTrue(any("full authority" in e.lower() for e in errors))

        admin_role = self.conn.execute(
            "SELECT * FROM access_roles WHERE LOWER(name) = LOWER(?)",
            ("Super Administrator",),
        ).fetchone()
        self.assertIsNotNone(admin_role)
        ok_errors, _ = validate_access_role_form(
            self.conn,
            actor=actor,
            role_id=int(admin_role["id"]),
            name="Super Administrator",
            is_admin=True,
            dashboard_modules=[],
            sales_analytics_modules=[],
            user_access_modules=[],
        )
        self.assertFalse(any("full authority" in e.lower() for e in ok_errors))

        # Demoting Super Administrator is allowed when another active admin exists.
        other_role_id, _ = save_access_role_record(
            self.conn,
            role_id=None,
            name="Backup Admin",
            description="",
            is_admin=True,
            is_active=True,
            dashboard_modules=[],
            sales_analytics_modules=[],
            user_access_modules=[],
            sql_now="datetime('now','localtime')",
        )
        save_access_user_record(
            self.conn,
            user_id=None,
            username="backup_admin",
            full_name="Backup Admin",
            email="backup@example.com",
            password="Password1!",
            role_id=other_role_id,
            sql_now="datetime('now','localtime')",
        )
        demote_errors, _ = validate_access_role_form(
            self.conn,
            actor=actor,
            role_id=int(admin_role["id"]),
            name="Super Administrator",
            is_admin=False,
            dashboard_modules=["reports"],
            sales_analytics_modules=[],
            user_access_modules=[],
        )
        self.assertFalse(any("active administrator must remain" in e for e in demote_errors))
        self.assertFalse(any("full authority" in e.lower() for e in demote_errors))

    def test_legacy_administrator_role_renames_to_super_administrator(self):
        self.conn.execute(
            """UPDATE access_roles
               SET name = 'Administrator'
               WHERE LOWER(name) = LOWER('Super Administrator')"""
        )
        ensure_access_roles_schema(self.conn)
        row = self.conn.execute(
            "SELECT name, is_admin FROM access_roles WHERE is_admin = 1 LIMIT 1"
        ).fetchone()
        self.assertEqual(row["name"], "Super Administrator")
        self.assertTrue(bool(row["is_admin"]))

    def test_custom_administrator_role_survives_schema_ensure(self):
        """Custom role named Administrator must not be deleted when Super Admin exists."""
        role_id, _ = save_access_role_record(
            self.conn,
            role_id=None,
            name="Administrator",
            description="Desk admin",
            is_admin=False,
            is_active=True,
            dashboard_modules=["reports"],
            sales_analytics_modules=[],
            user_access_modules=[],
            sql_now="datetime('now','localtime')",
        )
        ensure_access_roles_schema(self.conn)
        row = self.conn.execute(
            "SELECT id, name, is_admin FROM access_roles WHERE id = ?",
            (role_id,),
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["name"], "Administrator")
        self.assertFalse(bool(row["is_admin"]))
        self.assertFalse(is_built_in_administrator_role(dict(row)))

    def test_user_is_admin_not_stripped_by_non_admin_role(self):
        role_id, _ = save_access_role_record(
            self.conn,
            role_id=None,
            name="Desk Administrator",
            description="",
            is_admin=False,
            is_active=True,
            dashboard_modules=["reports"],
            sales_analytics_modules=[],
            user_access_modules=[],
            sql_now="datetime('now','localtime')",
        )
        admin_id = self.conn.execute(
            "SELECT id FROM users WHERE username = ?",
            ("admin",),
        ).fetchone()["id"]
        self.conn.execute(
            "UPDATE users SET role_id = ?, is_admin = 1 WHERE id = ?",
            (role_id, admin_id),
        )
        row = self.conn.execute(
            "SELECT * FROM users WHERE id = ?",
            (admin_id,),
        ).fetchone()
        user = build_user_context(self.conn, row)
        self.assertTrue(user["is_admin"])
        self.assertTrue(user_can_access_dashboard(user, "settings"))
        self.assertTrue(user_can_access_dashboard(user, "access_management"))

    def test_ensure_schema_reattaches_admin_users_to_super_admin_role(self):
        role_id, _ = save_access_role_record(
            self.conn,
            role_id=None,
            name="Desk Administrator",
            description="",
            is_admin=False,
            is_active=True,
            dashboard_modules=["reports"],
            sales_analytics_modules=[],
            user_access_modules=[],
            sql_now="datetime('now','localtime')",
        )
        admin_id = self.conn.execute(
            "SELECT id FROM users WHERE username = ?",
            ("admin",),
        ).fetchone()["id"]
        self.conn.execute(
            "UPDATE users SET role_id = ?, is_admin = 1 WHERE id = ?",
            (role_id, admin_id),
        )
        ensure_access_roles_schema(self.conn)
        row = self.conn.execute(
            """
            SELECT r.name, r.is_admin AS role_is_admin, u.is_admin
              FROM users u
              JOIN access_roles r ON r.id = u.role_id
             WHERE u.id = ?
            """,
            (admin_id,),
        ).fetchone()
        self.assertEqual(row["name"], "Super Administrator")
        self.assertTrue(bool(row["role_is_admin"]))
        self.assertTrue(bool(row["is_admin"]))

    def test_approval_module_only_super_admin_can_grant(self):
        non_admin = {"id": 9, "is_admin": False, "user_access": {"roles"}}
        admin = {"id": 1, "is_admin": True, "user_access": {"roles"}}

        stripped = reconcile_super_admin_only_dashboard_modules(
            non_admin, ["reports", "approval", "cancellation_access", "edit_access"], []
        )
        self.assertEqual(stripped, ["reports"])

        preserved = reconcile_super_admin_only_dashboard_modules(
            non_admin,
            ["reports"],
            ["reports", "approval", "cancellation_access", "edit_access"],
        )
        self.assertEqual(preserved[0], "reports")
        self.assertEqual(
            set(preserved),
            {"reports", "approval", "cancellation_access", "edit_access"},
        )

        granted = reconcile_super_admin_only_dashboard_modules(
            admin, ["reports", "approval", "cancellation_access", "edit_access"], []
        )
        self.assertEqual(
            granted, ["reports", "approval", "cancellation_access", "edit_access"]
        )
        revoked = reconcile_super_admin_only_dashboard_modules(
            admin,
            ["reports"],
            ["reports", "approval", "cancellation_access", "edit_access"],
        )
        self.assertEqual(revoked, ["reports"])

    def test_editing_role_keeps_its_own_name(self):
        actor = {"id": 1, "is_admin": True, "user_access": {"roles"}}
        role_id, _ = save_access_role_record(
            self.conn,
            role_id=None,
            name="Night Auditor",
            description="First pass",
            is_admin=False,
            is_active=True,
            dashboard_modules=["reports"],
            sales_analytics_modules=[],
            user_access_modules=[],
            sql_now="datetime('now','localtime')",
        )
        errors, _ = validate_access_role_form(
            self.conn,
            actor=actor,
            role_id=role_id,
            name="Night Auditor",
            is_admin=False,
            dashboard_modules=["reports"],
            sales_analytics_modules=[],
            user_access_modules=[],
        )
        self.assertFalse(any("already in use" in e.lower() for e in errors))

        # Saving an update with the same name must succeed.
        saved_id, flag = save_access_role_record(
            self.conn,
            role_id=role_id,
            name="Night Auditor",
            description="Updated",
            is_admin=False,
            is_active=True,
            dashboard_modules=["reports"],
            sales_analytics_modules=[],
            user_access_modules=[],
            sql_now="datetime('now','localtime')",
        )
        self.assertEqual(saved_id, role_id)
        self.assertEqual(flag, "updated")

    def test_admin_role_grants_full_access(self):
        role_id, _ = save_access_role_record(
            self.conn,
            role_id=None,
            name="Ops Admin",
            description="",
            is_admin=True,
            is_active=True,
            dashboard_modules=[],
            sales_analytics_modules=[],
            user_access_modules=[],
            sql_now="datetime('now','localtime')",
        )
        user_id, _ = save_access_user_record(
            self.conn,
            user_id=None,
            username="ops_admin",
            full_name="Ops Admin",
            password="Secret123!",
            role_id=role_id,
            sql_now="datetime('now','localtime')",
            email="ops@example.com",
        )
        row = self.conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        user = build_user_context(self.conn, row)
        self.assertTrue(user["is_admin"])
        self.assertTrue(user_can_access_dashboard(user, "accounts"))
        self.assertTrue(user_can_access_dashboard(user, "point_of_sale"))

    def test_named_role_permissions_grant_dashboard_and_submodules(self):
        role_id, _ = save_access_role_record(
            self.conn,
            role_id=None,
            name="Cashier",
            description="",
            is_admin=False,
            is_active=True,
            dashboard_modules=["sales_analytics"],
            sales_analytics_modules=["hotel", "bar"],
            user_access_modules=[],
            sql_now="datetime('now','localtime')",
        )
        user_id, _ = save_access_user_record(
            self.conn,
            user_id=None,
            username="cashier1",
            full_name="Cashier One",
            password="Secret123!",
            role_id=role_id,
            sql_now="datetime('now','localtime')",
            email="cashier@example.com",
        )
        row = self.conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        user = build_user_context(self.conn, row)
        self.assertFalse(user["is_admin"])
        self.assertEqual(user["role_name"], "Cashier")
        self.assertTrue(user_can_access_dashboard(user, "sales_analytics"))
        self.assertTrue(user_can_access_sales_analytics_submodule(user, "hotel"))
        self.assertFalse(user_can_access_sales_analytics_submodule(user, "credit"))
        self.assertFalse(user_can_access_dashboard(user, "settings"))

    def test_user_without_role_is_denied(self):
        self.conn.execute(
            """INSERT INTO users
               (username, full_name, email, password_hash, is_admin, role_id, is_active, created_at, updated_at)
               VALUES (?, ?, ?, ?, 0, NULL, 1, datetime('now','localtime'), datetime('now','localtime'))""",
            ("norole", "No Role", "norole@example.com", "x"),
        )
        row = self.conn.execute(
            "SELECT * FROM users WHERE username = ?",
            ("norole",),
        ).fetchone()
        user = build_user_context(self.conn, row)
        self.assertIsNone(user["role_id"])
        self.assertFalse(user_has_assigned_access_role(user))
        self.assertFalse(user_can_access_dashboard(user, "sales_analytics"))
        self.assertFalse(user_can_access_dashboard(user, "access_management"))

    def test_delete_role_blocked_when_assigned(self):
        role_id, _ = save_access_role_record(
            self.conn,
            role_id=None,
            name="Assigned Role",
            description="",
            is_admin=False,
            is_active=True,
            dashboard_modules=["reports"],
            sales_analytics_modules=[],
            user_access_modules=[],
            sql_now="datetime('now','localtime')",
        )
        save_access_user_record(
            self.conn,
            user_id=None,
            username="assigned_user",
            full_name="Assigned",
            password="Secret123!",
            role_id=role_id,
            sql_now="datetime('now','localtime')",
            email="assigned@example.com",
        )
        ok, message = delete_access_role(self.conn, role_id)
        self.assertFalse(ok)
        self.assertIn("Reassign", message)

    def test_legacy_permissions_migrate_into_imported_role(self):
        self.conn.execute(
            """INSERT INTO users
               (username, full_name, email, password_hash, is_admin, role_id, is_active, created_at, updated_at)
               VALUES (?, ?, ?, ?, 0, NULL, 1, datetime('now','localtime'), datetime('now','localtime'))""",
            ("legacy", "Legacy User", "legacy@example.com", "x"),
        )
        user_id = self.conn.execute(
            "SELECT id FROM users WHERE username = ?",
            ("legacy",),
        ).fetchone()["id"]
        set_user_permissions(
            self.conn,
            user_id,
            ["accounts"],
            [],
            [],
            [],
            ["cash_ledger"],
            [],
        )
        ensure_access_roles_schema(self.conn)
        row = self.conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        user = build_user_context(self.conn, row)
        self.assertEqual(user["role_name"], "Imported — legacy")
        self.assertTrue(user_can_access_dashboard(user, "accounts"))
        self.assertTrue(user_can_access_accounts_submodule(user, "cash_ledger"))
        self.assertFalse(user_can_access_accounts_submodule(user, "purchase_ledger"))


if __name__ == "__main__":
    unittest.main()
