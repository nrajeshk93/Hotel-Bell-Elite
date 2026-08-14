"""Workspace module registry and permission helpers for Hotel Bell Elite."""

import auth_security
from user_photos import avatar_accent_index, role_accent_index

_SALES_ANALYTICS_SUBMODULES = (
    {"key": "dashboard", "label": "Dashboard"},
    {"key": "hotel", "label": "Sales Update - Hotel"},
    {"key": "bar", "label": "Sales Update - Bar"},
    {"key": "restaurant", "label": "Sales Update - Restaurant"},
    {"key": "room_transfer", "label": "Room Transfer"},
    {"key": "credit", "label": "Credit"},
)

_USER_ACCESS_SUBMODULES = (
    {"key": "users", "label": "Users"},
    {"key": "add", "label": "Add User"},
    {"key": "roles", "label": "Roles"},
    {"key": "logs", "label": "Logs"},
)

_PAYROLL_SUBMODULES = (
    {"key": "employee", "label": "Employee"},
    {"key": "attendance", "label": "Attendance"},
    {"key": "credit", "label": "Credit"},
    {"key": "tips", "label": "Tips"},
    {"key": "report", "label": "Report"},
)

_ACCOUNTS_SUBMODULES = (
    {"key": "purchase_ledger", "label": "Purchases & Expenses"},
    {"key": "cash_ledger", "label": "Cash Ledger"},
    {"key": "purchase_verification", "label": "Approvals"},
    {"key": "credit_payment", "label": "Credit Payment"},
    {"key": "supplier_master", "label": "Supplier Master"},
)

_STORES_SUBMODULES = (
    {
        "key": "indent",
        "label": "Indent",
        "children": (
            {"key": "product_master", "label": "Products"},
        ),
    },
    {"key": "approvals", "label": "Approvals"},
    {"key": "purchase_requests", "label": "Stock Inward"},
    {"key": "stock", "label": "Store"},
    {"key": "stock_audit", "label": "Stock Audit"},
)


def _flatten_submodules(items):
    """Flat key/label list for permission checks (nested UI children included)."""
    flat = []
    for item in items:
        flat.append({"key": item["key"], "label": item["label"]})
        for child in item.get("children") or ():
            flat.append({"key": child["key"], "label": child["label"]})
    return tuple(flat)


_STORES_SUBMODULES_FLAT = _flatten_submodules(_STORES_SUBMODULES)

# Single registry aligned with the workspace sidebar and access-management UI.
# Add a new top-level module here and wire its endpoints to auto-include it everywhere.
_WORKSPACE_MODULE_REGISTRY = (
    {
        "key": "main_dashboard",
        "label": "Dashboard",
        # Top-level workspace dashboard shell; content pages will be added later.
        "permission_scope": None,
        "permission_field": None,
        "permission_children": (),
    },
    {
        "key": "sales_analytics",
        "label": "Sales Analytics",
        "permission_scope": "sales_analytics",
        "permission_field": "sales_analytics_modules",
        "permission_children": _SALES_ANALYTICS_SUBMODULES,
    },
    {
        "key": "access_management",
        "label": "User & Access",
        "permission_scope": "user_access",
        "permission_field": "user_access_modules",
        "permission_children": _USER_ACCESS_SUBMODULES,
    },
    {
        "key": "accounts",
        "label": "Accounts",
        "permission_scope": "accounts",
        "permission_field": "accounts_modules",
        "permission_children": _ACCOUNTS_SUBMODULES,
    },
    {
        "key": "employee_payroll",
        "label": "Employee Payroll",
        "permission_scope": "payroll",
        "permission_field": "payroll_modules",
        "permission_children": _PAYROLL_SUBMODULES,
    },
    {
        "key": "point_of_sale",
        "label": "Restaurant",
        # Dashboard module with sidebar sub-pages (Tables, Invoice, Settings); access is module-level.
        "permission_scope": None,
        "permission_field": None,
        "permission_children": (),
    },
    {
        "key": "point_of_sale_bar",
        "label": "Bar",
        # Parallel POS workspace for Bar (Tables, POS, Ledger, Menu, Settings).
        "permission_scope": None,
        "permission_field": None,
        "permission_children": (),
    },
    {
        "key": "hotel_rooms",
        "label": "Hotel",
        # Front-office room board (Rooms); separate from Sales Update - Hotel.
        "permission_scope": None,
        "permission_field": None,
        "permission_children": (),
    },
    {
        "key": "communication_hub",
        "label": "Communication Hub",
        # WhatsApp inbox — module-level access.
        "permission_scope": None,
        "permission_field": None,
        "permission_children": (),
    },
    {
        "key": "stores",
        "label": "Purchase & Inventory",
        "permission_scope": "stores",
        "permission_field": "stores_modules",
        "permission_children": _STORES_SUBMODULES,
    },
    {
        "key": "master",
        "label": "Master",
        # Dashboard module shell; access is module-level until sub-pages are added.
        "permission_scope": None,
        "permission_field": None,
        "permission_children": (),
    },
    {
        "key": "reports",
        "label": "Report",
        "permission_scope": None,
        "permission_field": None,
        "permission_children": (),
    },
    {
        "key": "settings",
        "label": "Settings",
        # Workspace settings shell; access is module-level until sub-pages are added.
        "permission_scope": None,
        "permission_field": None,
        "permission_children": (),
    },
    {
        "key": "approval",
        "label": "Approval",
        # Module-level grant reserved for upcoming approval workflows.
        "permission_scope": None,
        "permission_field": None,
        "permission_children": (),
    },
    {
        "key": "cancellation_access",
        "label": "Cancellation Access",
        # Module-level grant: edit/remove kitchen-sent POS lines after KOT.
        "permission_scope": None,
        "permission_field": None,
        "permission_children": (),
    },
)

_DASHBOARD_MODULES = tuple(
    {"key": module["key"], "label": module["label"]}
    for module in _WORKSPACE_MODULE_REGISTRY
)
_ACCESS_MODULE_CHILDREN = {
    module["key"]: {
        "scope": module["permission_scope"],
        "field_name": module["permission_field"],
        "submodules": module["permission_children"],
    }
    for module in _WORKSPACE_MODULE_REGISTRY
    if module.get("permission_children")
}
_DASHBOARD_MODULE_LABELS = {item["key"]: item["label"] for item in _DASHBOARD_MODULES}
# Dashboard modules only a Super Administrator (is_admin) may grant or revoke on roles.
_SUPER_ADMIN_ONLY_DASHBOARD_KEYS = frozenset({"approval", "cancellation_access"})
_SALES_ANALYTICS_SUBMODULE_LABELS = {
    item["key"]: item["label"] for item in _SALES_ANALYTICS_SUBMODULES
}
_USER_ACCESS_SUBMODULE_LABELS = {
    item["key"]: item["label"] for item in _USER_ACCESS_SUBMODULES
}
_PAYROLL_SUBMODULE_LABELS = {
    item["key"]: item["label"] for item in _PAYROLL_SUBMODULES
}
_ACCOUNTS_SUBMODULE_LABELS = {
    item["key"]: item["label"] for item in _ACCOUNTS_SUBMODULES
}
_STORES_SUBMODULE_LABELS = {
    item["key"]: item["label"] for item in _STORES_SUBMODULES_FLAT
}

_ACCESS_MODULE_UI_META = {
    "main_dashboard": {
        "icon": "layout-dashboard",
        "description": "Workspace dashboard overview for Hotel Bell Elite.",
    },
    "sales_analytics": {
        "icon": "trending-up",
        "description": "Daily sales updates, room transfers, hotel credit clearance, and analytics dashboards.",
    },
    "access_management": {
        "icon": "shield-check",
        "description": "Manage workspace users and roles that grant module access.",
    },
    "accounts": {
        "icon": "wallet",
        "description": "Ledger, payments, and financial records.",
    },
    "employee_payroll": {
        "icon": "users",
        "description": "Manage employees, payroll reports, attendance, credits, and tip analytics.",
    },
    "point_of_sale": {
        "icon": "receipt",
        "description": (
            "Counter billing and invoice workspace for guest sales. "
            "After a KOT is sent, those lines stay locked unless the role also has Cancellation Access."
        ),
    },
    "point_of_sale_bar": {
        "icon": "receipt",
        "description": (
            "Bar counter billing and invoice workspace. "
            "After a KOT is sent, those lines stay locked unless the role also has Cancellation Access."
        ),
    },

    "hotel_rooms": {
        "icon": "bed",
        "description": "Front-office room board — occupancy status by floor and room type.",
    },
    "communication_hub": {
        "icon": "message-circle",
        "description": "WhatsApp conversations with customers and vendors — send, receive, and manage messages.",
    },
    "stores": {
        "icon": "store",
        "description": "Simple indent-to-stock flow for Bar and Kitchen stores.",
    },
    "master": {
        "icon": "database",
        "description": "Central master data for Hotel Bell Elite.",
    },
    "reports": {
        "icon": "file-text",
        "description": "View and download reports across all modules.",
    },
    "settings": {
        "icon": "settings",
        "description": "Workspace and property settings for Hotel Bell Elite.",
    },
    "approval": {
        "icon": "badge-check",
        "description": (
            "Approve pending workspace requests and actions. "
            "Only a Super Administrator can grant this module to a role."
        ),
    },
    "cancellation_access": {
        "icon": "ban",
        "description": (
            "Edit or remove kitchen-sent POS lines after a KOT is sent; "
            "Kitchen Order Tokens on the Tables page update to match. "
            "Only a Super Administrator can grant this module to a role."
        ),
    },
}

# Point of Sale workspace routes (Tables + POS + Invoice Ledger + Menu + Settings). Not Sales Analytics.
_POINT_OF_SALE_ENDPOINTS = {
    "point_of_sale",
    "point_of_sale_invoice",
    "point_of_sale_invoice_ledger",
    "point_of_sale_sales_update",
    "point_of_sale_menu",
    "point_of_sale_settings",
    "export_pos_invoice_ledger_report",
    "point_of_sale_api_floor",
    "point_of_sale_api_settings",
    "point_of_sale_api_menu_categories",
    "point_of_sale_api_menu_category_delete",
    "point_of_sale_api_menu_items",
    "point_of_sale_api_menu_item_delete",
    "point_of_sale_api_menu_products",
    "point_of_sale_api_invoices_save",
    "point_of_sale_api_invoice_detail",
    "point_of_sale_api_invoice_delete",
    "point_of_sale_api_customers",
    "point_of_sale_api_invoice_settle",
    "point_of_sale_api_hotel_rooms_occupied",
    "point_of_sale_api_kot_tokens",
    "point_of_sale_api_kot_tokens_reduce",
}

_POINT_OF_SALE_BAR_ENDPOINTS = {
    "bar_point_of_sale",
    "bar_point_of_sale_invoice",
    "bar_point_of_sale_invoice_ledger",
    "bar_point_of_sale_menu",
    "bar_point_of_sale_settings",
    "bar_export_pos_invoice_ledger_report",
    "bar_point_of_sale_api_floor",
    "bar_point_of_sale_api_settings",
    "bar_point_of_sale_api_menu_categories",
    "bar_point_of_sale_api_menu_category_delete",
    "bar_point_of_sale_api_menu_items",
    "bar_point_of_sale_api_menu_item_delete",
    "bar_point_of_sale_api_menu_products",
    "bar_point_of_sale_api_invoices_save",
    "bar_point_of_sale_api_invoice_detail",
    "bar_point_of_sale_api_invoice_delete",
    "bar_point_of_sale_api_customers",
    "bar_point_of_sale_api_invoice_settle",
    "bar_point_of_sale_api_hotel_rooms_occupied",
    "bar_point_of_sale_api_kot_tokens",
    "bar_point_of_sale_api_kot_tokens_reduce",
}

_HOTEL_ROOMS_ENDPOINTS = {
    "hotel_rooms",
    "hotel_rooms_api",
    "hotel_room_detail",
    "hotel_room_detail_api",
    "hotel_room_invoice_page",
    "hotel_guest_lookup_api",
    "hotel_customers_api",
    "hotel_id_document_upload",
    "hotel_id_document_file",
    "hotel_reservations",
    "hotel_reservations_api",
    "hotel_reservation_detail_api",
    "hotel_reservation_assign_api",
    "hotel_invoice_ledger",
    "hotel_invoice_ledger_export",
    "hotel_invoice_ledger_api",
    "hotel_invoice_ledger_settle_api",
    "hotel_settings",
    "hotel_settings_api",
}

_MAIN_DASHBOARD_ENDPOINTS = {
    "main_dashboard",
}

_COMMUNICATION_HUB_ENDPOINTS = {
    "communication_hub",
    "communication_hub_api_conversations",
    "communication_hub_api_conversation_create",
    "communication_hub_api_conversation_delete",
    "communication_hub_api_messages",
    "communication_hub_api_message_send",
}

_STORES_ENDPOINT_GROUPS = {
    "product_master": {
        "stores_product_master",
    },
    "indent": {
        "stores_indent",
        "stores_indent_submit",
        "stores_indent_detail",
        "stores_indent_delete",
        "stores_indent_purchase_order",
        "stores_orders",
        "stores_orders_history",
        "stores_orders_send",
        "stores_orders_lines",
        "stores_orders_lines_next",
        "stores_orders_pdf",
        "stores_orders_send_wa",
    },
    "approvals": {
        "stores_approvals",
        "stores_indent_decide",
        "stores_indent_reopen",
    },
    "purchase_requests": {
        "stores_purchase_requests",
        "stores_pr_receive",
        "stores_pr_detail",
        "stores_confirm_stock_inward_expense",
        "stores_confirm_direct_stock_inward_expense",
        "stores_save_expense_category",
    },
    "stock": {
        "stores_stock",
        "stores_stock_export",
        "stores_stock_transfer",
    },
    "stock_audit": {
        "stores_stock_audit",
        "stores_stock_audit_verify",
        "stores_stock_audit_skip",
        "stores_stock_audit_history",
        "stores_stock_audit_new",
        "stores_stock_audit_report",
        "stores_stock_audit_report_export",
    },
}
_STORES_PARENT_ENDPOINTS = set().union(*_STORES_ENDPOINT_GROUPS.values()) | {"stores"}
_STORES_ENDPOINTS = _STORES_PARENT_ENDPOINTS

_MASTER_ENDPOINTS = {
    "master",
    "customer_master",
    "save_customer",
    "delete_customer",
    "export_customer_report",
    "agency_master",
    "save_agency",
    "delete_agency",
    "export_agency_report",
    "create_agency",
    "list_agencies_api",
    "category_master",
    "save_category_master",
    "delete_category_master",
}

_REPORTS_ENDPOINTS = {
    "reports",
    "sales_report_hotel",
    "sales_report_hotel_export",
    "sales_report_manager_insight",
    "sales_report_manager_insight_export",
    "sales_report_restaurant",
    "sales_report_restaurant_export",
    "sales_report_bar",
    "sales_report_bar_export",
    "sales_report_menu",
    "sales_report_menu_export",
    "sales_report_customer_insights",
    "sales_report_customer_insights_export",
}

_SETTINGS_ENDPOINTS = {
    "settings",
}

_PUBLIC_ENDPOINTS = {
    "index",
    "login",
    "login_captcha",
    "login_resend_unlock",
    "unlock_account",
    "logout",
    "static",
    "favicon",
    "whatsapp_webhook",
    "robots_txt",
    "sitemap_xml",
}

_OUTLET_WRITE_ENDPOINTS = {
    "save_sales_update",
    "upload_report",
    "upload_sales_report",
    "add_expense",
    "edit_expense",
    "delete_expense",
    "add_unpaid_bill",
    "delete_unpaid_bill",
    "open_pending_bills",
    "add_bill_payment",
    "delete_bill_payment",
    "add_cash_transfer",
    "delete_cash_transfer",
    "send_whatsapp_report",
}

_POS_RESTAURANT_SALES_WRITE_ENDPOINTS = {
    "save_sales_update",
    "sales_update_add_tip",
    "sales_update_edit_tip",
    "sales_update_delete_tip",
    "add_cash_transfer",
    "delete_cash_transfer",
    "sales_update_add_cash_transfer",
    "sales_update_delete_cash_transfer",
}

_SALES_ANALYTICS_ENDPOINT_GROUPS = {
    "dashboard": {"dashboard"},
    "hotel": {
        "sales_update_hotel",
        "upload_hotel_occupancy_report",
        "save_hotel_ledger",
        "clear_hotel_ledger",
        "create_supplier",
        "save_sales_update",
        "sales_update_add_expense",
        "sales_update_edit_expense",
        "sales_update_delete_expense",
        "sales_update_add_tip",
        "sales_update_edit_tip",
        "sales_update_delete_tip",
    },
    "bar": {
        "sales_update_bar",
        "sales_update",
        "sales_update_entry",
        "sales_update_add_tip",
        "sales_update_edit_tip",
        "sales_update_delete_tip",
        *_OUTLET_WRITE_ENDPOINTS,
    },
    "restaurant": {
        "sales_update_restaurant",
        "sales_update_add_tip",
        "sales_update_edit_tip",
        "sales_update_delete_tip",
        *_OUTLET_WRITE_ENDPOINTS,
    },
    "room_transfer": {
        "sales_update_room_transfer",
        "save_room_transfer_status",
        "create_room_transfer_payment",
        "reverse_room_transfer_payment",
    },
    "credit": {
        "sales_update_credit",
        "create_sales_credit_payment",
        "reverse_sales_credit_payment",
    },
}

_SALES_ANALYTICS_PARENT_ENDPOINTS = set().union(*_SALES_ANALYTICS_ENDPOINT_GROUPS.values())

_ACCESS_ENDPOINT_GROUPS = {
    "users": {"delete_access_user", "unlock_access_user", "toggle_access_user_active"},
    "add": set(),
    "roles": {
        "access_roles",
        "save_access_role",
        "delete_access_role",
    },
    "logs": {"access_login_logs"},
}
_ACCESS_MANAGEMENT_ENDPOINTS = {
    "access_management",
    "save_access_user",
    "unlock_access_user",
    "toggle_access_user_active",
    "access_roles",
    "save_access_role",
    "delete_access_role",
    "access_login_logs",
}
SUPER_ADMINISTRATOR_ROLE_NAME = "Super Administrator"
_ADMINISTRATOR_ROLE_NAME = SUPER_ADMINISTRATOR_ROLE_NAME  # seeded full-authority role
_LEGACY_ADMINISTRATOR_ROLE_NAMES = frozenset({"administrator", "super administrator"})


def _normalize_role_name(value):
    return str(value or "").strip().lower()


def is_built_in_administrator_role(role=None, *, name=None, role_id=None):
    """True for the seeded Super Administrator role (full authority / is_admin).

    A custom role may be named Administrator (is_admin=0); that is not built-in.
    Legacy rows still named Administrator with is_admin=1 are treated as built-in
    until ensure_access_roles_schema renames them.
    """
    del role_id  # Accepted for call-site clarity; name/row are authoritative.
    if role is not None:
        try:
            role_name = role["name"] if not isinstance(role, dict) else role.get("name")
            is_admin = bool(
                role.get("is_admin") if isinstance(role, dict) else role["is_admin"]
            )
        except (KeyError, TypeError, IndexError):
            role_name = None
            is_admin = False
        normalized = _normalize_role_name(role_name)
        if normalized == "super administrator":
            return True
        if normalized == "administrator" and is_admin:
            return True
        return False
    check_name = _normalize_role_name(name)
    # Name-only: Super Administrator is reserved; plain Administrator needs the row.
    return check_name == "super administrator"


_ACCOUNTS_ENDPOINT_GROUPS = {
    "purchase_ledger": {
        "purchase_ledger",
        "purchase_ledger_add",
        "purchase_ledger_edit",
        "purchase_ledger_delete",
        "export_purchase_ledger_report",
    },
    "cash_ledger": {
        "cash_ledger",
        "cash_ledger_available",
        "cash_ledger_load",
        "cash_ledger_transfer",
        "cash_ledger_delete_load",
        "cash_ledger_delete_transfer",
        "export_cash_ledger_report",
    },
    "credit_payment": {
        "credit_payment",
        "export_credit_payment_report",
        "create_credit_payment",
        "delete_credit_payment",
        "credit_payment_detail",
    },
    "purchase_verification": {
        "purchase_verification",
        "create_purchase_verification",
        "delete_purchase_verification",
        "purchase_verification_detail",
        "export_purchase_verification_report",
    },
    "supplier_master": {
        "supplier_master",
        "save_supplier",
        "delete_supplier",
        "export_supplier_report",
    },
}
_ACCOUNTS_PARENT_ENDPOINTS = set().union(*_ACCOUNTS_ENDPOINT_GROUPS.values()) | {"accounts"}
_ACCOUNTS_ENDPOINTS = _ACCOUNTS_PARENT_ENDPOINTS

_PAYROLL_ENDPOINT_GROUPS = {
    "employee": {
        "employees",
        "employee_master",
        "add_employee",
        "edit_employee",
        "delete_employee",
        "download_employee_template",
        "upload_employees",
        "export_employees",
        "export_employee_master",
    },
    "report": {
        "report",
        "monthly_payroll_report",
        "bank_report",
        "export_employees",
        "export_wage_register",
        "export_bank_report",
    },
    "attendance": {
        "attendance_overview",
        "attendance_date",
        "attendance",
        "mark_attendance",
        "bulk_attendance",
        "export_attendance_report",
        "export_attendance_register",
    },
    "credit": {
        "credits_dashboard",
        "add_credit_global",
        "employee_credits",
        "add_credit",
        "edit_credit",
        "delete_credit",
        "export_credits_report",
        "update_salary",
        "lock_payroll_month",
    },
    "tips": {
        "sales_update_tips_page",
        "export_tips_report",
        "tips_incentive_payout",
        "sales_update_tips_delete_employee",
        "sales_update_tips_employee_lines",
        "sales_update_edit_tip",
    },
}
_PAYROLL_PARENT_ENDPOINTS = set().union(*_PAYROLL_ENDPOINT_GROUPS.values())


def _permission_child_nodes(module_key, child_cfg, submodules, parent_key=None):
    nodes = []
    for child in submodules:
        node = {
            "key": child["key"],
            "label": child["label"],
            "scope": child_cfg["scope"],
            "field_name": child_cfg["field_name"],
            "parent_key": parent_key or module_key,
            "permission_children": [],
        }
        nested = child.get("children") or ()
        if nested:
            node["permission_children"] = _permission_child_nodes(
                module_key, child_cfg, nested, parent_key=child["key"]
            )
        nodes.append(node)
    return nodes


def _ui_child_nodes(module_key, child_cfg, submodules):
    nodes = []
    for child in submodules:
        nested = child.get("children") or ()
        nodes.append({
            "id": f"{module_key}.{child['key']}",
            "label": child["label"],
            "icon": "folder" if nested else "dot",
            "description": "",
            "dashboardKey": module_key,
            "fieldName": child_cfg["field_name"],
            "fieldValue": child["key"],
            "children": _ui_child_nodes(module_key, child_cfg, nested) if nested else [],
        })
    return nodes


def access_module_tree():
    tree = []
    for module in _WORKSPACE_MODULE_REGISTRY:
        node = {
            "key": module["key"],
            "label": module["label"],
            "permission_children": [],
        }
        child_cfg = _ACCESS_MODULE_CHILDREN.get(module["key"])
        if child_cfg:
            node["permission_children"] = _permission_child_nodes(
                module["key"], child_cfg, child_cfg["submodules"]
            )
        tree.append(node)
    return tree


def access_module_tree_ui():
    tree = []
    for module in _WORKSPACE_MODULE_REGISTRY:
        meta = _ACCESS_MODULE_UI_META.get(module["key"], {})
        node = {
            "id": module["key"],
            "label": module["label"],
            "icon": meta.get("icon", "layout-grid"),
            "description": meta.get(
                "description",
                "This module and all its sub-modules are enabled.",
            ),
            "dashboardKey": module["key"],
            "fieldName": "dashboard_modules",
            "fieldValue": module["key"],
            "children": [],
        }
        if module["key"] in _SUPER_ADMIN_ONLY_DASHBOARD_KEYS:
            node["superAdminOnly"] = True
        child_cfg = _ACCESS_MODULE_CHILDREN.get(module["key"])
        if child_cfg:
            node["children"] = _ui_child_nodes(
                module["key"], child_cfg, child_cfg["submodules"]
            )
        tree.append(node)
    return tree


def reconcile_super_admin_only_dashboard_modules(
    actor, dashboard_modules, original_dashboard_modules=None
):
    """Keep Super-Admin-only modules unchanged unless the actor is a Super Admin."""
    modules = [
        str(item or "").strip()
        for item in (dashboard_modules or [])
        if str(item or "").strip()
    ]
    if actor and actor.get("is_admin"):
        return modules

    original = {
        str(item or "").strip()
        for item in (original_dashboard_modules or [])
        if str(item or "").strip()
    }
    current = set(modules)
    for key in _SUPER_ADMIN_ONLY_DASHBOARD_KEYS:
        if key in current and key not in original:
            current.discard(key)
        elif key in original and key not in current:
            current.add(key)

    ordered = []
    seen = set()
    for item in modules:
        if item in current and item not in seen:
            ordered.append(item)
            seen.add(item)
    for key in _SUPER_ADMIN_ONLY_DASHBOARD_KEYS:
        if key in current and key not in seen:
            ordered.append(key)
            seen.add(key)
    return ordered


def _empty_permission_sets():
    return (set(), set(), set(), set(), set(), set())


def _permission_sets_from_rows(rows):
    dashboard_access = set()
    sales_analytics_access = set()
    user_access = set()
    payroll_access = set()
    accounts_access = set()
    stores_access = set()
    for row in rows:
        scope = (row["scope"] or "").strip()
        item_key = (row["item_key"] or "").strip()
        if scope == "dashboard" and item_key == "sales_update":
            # Legacy key from earlier builds.
            dashboard_access.add("sales_analytics")
        elif scope == "dashboard" and item_key:
            dashboard_access.add(item_key)
        elif scope == "sales_analytics" and item_key:
            sales_analytics_access.add(item_key)
        elif scope == "user_access" and item_key:
            user_access.add(item_key)
        elif scope == "payroll" and item_key:
            payroll_access.add(item_key)
        elif scope == "accounts" and item_key:
            accounts_access.add(item_key)
        elif scope == "stores" and item_key:
            stores_access.add(item_key)
    return (
        dashboard_access,
        sales_analytics_access,
        user_access,
        payroll_access,
        accounts_access,
        stores_access,
    )


def load_user_permissions(conn, user_id):
    rows = conn.execute(
        "SELECT scope, item_key FROM user_permissions WHERE user_id = ?",
        (user_id,),
    ).fetchall()
    return _permission_sets_from_rows(rows)


def load_role_permissions(conn, role_id):
    rows = conn.execute(
        "SELECT scope, item_key FROM access_role_permissions WHERE role_id = ?",
        (role_id,),
    ).fetchall()
    return _permission_sets_from_rows(rows)


def _apply_permission_sets(target, permission_sets):
    (
        dashboard_access,
        sales_analytics_access,
        user_access,
        payroll_access,
        accounts_access,
        stores_access,
    ) = permission_sets
    target["dashboard_access"] = dashboard_access
    target["sales_analytics_access"] = sales_analytics_access
    target["user_access"] = user_access
    target["payroll_access"] = payroll_access
    target["accounts_access"] = accounts_access
    target["stores_access"] = stores_access


def build_user_context(conn, row):
    if not row:
        return None
    user = dict(row)
    user["is_admin"] = bool(user.get("is_admin"))
    user["is_active"] = bool(user.get("is_active"))
    user["email"] = (user.get("email") or "").strip()
    user["is_locked"] = bool(user.get("locked_at"))
    user["failed_login_attempts"] = int(user.get("failed_login_attempts") or 0)
    user["captcha_required"] = bool(user.get("captcha_required"))
    user["must_change_password"] = bool(user.get("must_change_password"))
    user["account_status"] = (
        "locked"
        if user["is_locked"]
        else ("active" if user["is_active"] else "inactive")
    )
    user["display_name"] = (user.get("full_name") or user.get("username") or "").strip()
    user["photo_path"] = (user.get("photo_path") or "").strip()
    user["avatar_tone"] = avatar_accent_index(user.get("id") or user.get("username"))

    role_id = user.get("role_id")
    role = None
    if role_id:
        role = conn.execute(
            "SELECT * FROM access_roles WHERE id = ?",
            (role_id,),
        ).fetchone()

    if role:
        user["role_id"] = int(role["id"])
        user["role_name"] = (role["name"] or "").strip()
        user["role_is_active"] = bool(role["is_active"])
        user["role_tone"] = role_accent_index(user["role_name"])
        # Never let a non-admin role strip users.is_admin — a mismatched
        # "Administrator" role was turning Super Admin into a limited user
        # on the next full render (refresh).
        if bool(role["is_admin"]) or user["is_admin"]:
            user["is_admin"] = True
            _apply_permission_sets(user, _empty_permission_sets())
        else:
            user["is_admin"] = False
            _apply_permission_sets(user, load_role_permissions(conn, role["id"]))
    else:
        user["role_id"] = None
        user["role_name"] = None
        user["role_is_active"] = False
        user["role_tone"] = role_accent_index("unassigned")
        _apply_permission_sets(user, _empty_permission_sets())
    return user


def user_has_assigned_access_role(user):
    """True when the person is a User & Access account with an assigned role.

    There is no generic User identity. Unassigned or inactive-role staff
    cannot sign in or keep a session.
    """
    if not user:
        return False
    if user.get("is_admin"):
        return True
    if not user.get("role_id") or not (user.get("role_name") or "").strip():
        return False
    if user.get("role_is_active") is False:
        return False
    return True


def user_can_access_dashboard(user, module_key):
    if not user:
        return False
    if user.get("is_admin"):
        return True
    if module_key == "sales_analytics" and user.get("sales_analytics_access", set()):
        return True
    if module_key == "access_management" and user.get("user_access", set()):
        return True
    if module_key == "employee_payroll" and user.get("payroll_access", set()):
        return True
    if module_key == "accounts" and user.get("accounts_access", set()):
        return True
    if module_key == "stores" and user.get("stores_access", set()):
        return True
    return module_key in user.get("dashboard_access", set())


def user_can_access_sales_analytics_submodule(user, submodule_key):
    if not user:
        return False
    if user.get("is_admin"):
        return True
    return submodule_key in user.get("sales_analytics_access", set())


def user_can_access_user_access_submodule(user, submodule_key):
    if not user:
        return False
    if user.get("is_admin"):
        return True
    return submodule_key in user.get("user_access", set())


def user_can_access_payroll_submodule(user, submodule_key):
    if not user:
        return False
    if user.get("is_admin"):
        return True
    access = user.get("payroll_access", set()) or set()
    if submodule_key in access:
        return True
    # Tips analytics sits with Employee Payroll; grant to users who already had Credit.
    if submodule_key == "tips" and "credit" in access:
        return True
    return False


def _accounts_access_keys(user):
    """Resolved Accounts page keys for a user (legacy parent grant = all pages)."""
    if not user:
        return set()
    if user.get("is_admin"):
        return {item["key"] for item in _ACCOUNTS_SUBMODULES}
    access = set(user.get("accounts_access", set()) or set())
    if access:
        return access
    # Legacy: dashboard Accounts alone used to unlock every Accounts page.
    if "accounts" in user.get("dashboard_access", set()):
        return {item["key"] for item in _ACCOUNTS_SUBMODULES}
    return set()


def user_can_access_accounts_submodule(user, submodule_key):
    if not user:
        return False
    if user.get("is_admin"):
        return True
    return submodule_key in _accounts_access_keys(user)


def _stores_access_keys(user):
    if not user:
        return set()
    if user.get("is_admin"):
        return {item["key"] for item in _STORES_SUBMODULES_FLAT}
    access = set(user.get("stores_access", set()) or set())
    if access:
        return access
    if "stores" in user.get("dashboard_access", set()):
        return {item["key"] for item in _STORES_SUBMODULES_FLAT}
    return set()


def user_can_access_stores_submodule(user, submodule_key):
    if not user:
        return False
    if user.get("is_admin"):
        return True
    # Indent Approvals (header button + /stores/approvals) require Module Tree → Approval.
    if submodule_key == "approvals":
        return user_can_approve_transactions(user)
    return submodule_key in _stores_access_keys(user)


def user_can_access_supplier_master(user):
    if not user:
        return False
    if user.get("is_admin"):
        return True
    if user_can_access_accounts_submodule(user, "supplier_master"):
        return True
    return "suppliers" in user.get("sales_analytics_access", set())


def user_can_access_customer_master(user):
    """Customer Master is available to Master hub and Restaurant/POS users."""
    if not user:
        return False
    if user.get("is_admin"):
        return True
    if user_can_access_dashboard(user, "master"):
        return True
    if user_can_access_dashboard(user, "point_of_sale"):
        return True
    if user_can_access_dashboard(user, "point_of_sale_bar"):
        return True
    return False


def user_can_access_agency_master(user):
    """Agency Master is available to Master hub and Hotel Rooms users."""
    if not user:
        return False
    if user.get("is_admin"):
        return True
    if user_can_access_dashboard(user, "master"):
        return True
    if user_can_access_dashboard(user, "hotel_rooms"):
        return True
    return False


def dashboard_access_list(user):
    if not user:
        return []
    if user.get("is_admin"):
        return [item["key"] for item in _DASHBOARD_MODULES]
    dashboard_access = set(user.get("dashboard_access", set()))
    if user.get("sales_analytics_access", set()):
        dashboard_access.add("sales_analytics")
    if user.get("user_access", set()):
        dashboard_access.add("access_management")
    if user.get("payroll_access", set()):
        dashboard_access.add("employee_payroll")
    if user.get("accounts_access", set()):
        dashboard_access.add("accounts")
    if user.get("stores_access", set()):
        dashboard_access.add("stores")
    return [item["key"] for item in _DASHBOARD_MODULES if item["key"] in dashboard_access]


def payroll_access_list(user):
    if not user:
        return []
    if user.get("is_admin"):
        return [item["key"] for item in _PAYROLL_SUBMODULES]
    access = set(user.get("payroll_access", set()) or set())
    if "credit" in access:
        access.add("tips")
    return [
        item["key"]
        for item in _PAYROLL_SUBMODULES
        if item["key"] in access
    ]


def accounts_access_list(user):
    if not user:
        return []
    unlocked = _accounts_access_keys(user)
    return [item["key"] for item in _ACCOUNTS_SUBMODULES if item["key"] in unlocked]


def stores_access_list(user):
    if not user:
        return []
    return [
        item["key"]
        for item in _STORES_SUBMODULES_FLAT
        if user_can_access_stores_submodule(user, item["key"])
    ]


def sales_analytics_access_list(user):
    if not user:
        return []
    if user.get("is_admin"):
        return [item["key"] for item in _SALES_ANALYTICS_SUBMODULES]
    return [
        item["key"]
        for item in _SALES_ANALYTICS_SUBMODULES
        if item["key"] in user.get("sales_analytics_access", set())
    ]


def user_access_submodule_list(user):
    if not user:
        return []
    if user.get("is_admin"):
        return [item["key"] for item in _USER_ACCESS_SUBMODULES]
    return [
        item["key"]
        for item in _USER_ACCESS_SUBMODULES
        if item["key"] in user.get("user_access", set())
    ]


def get_endpoint_dashboard_module(endpoint):
    bare = endpoint.split(".", 1)[1] if endpoint.startswith("stores.") else endpoint
    if endpoint in _MAIN_DASHBOARD_ENDPOINTS:
        return "main_dashboard"
    if endpoint in _SALES_ANALYTICS_PARENT_ENDPOINTS:
        return "sales_analytics"
    if endpoint in _ACCESS_MANAGEMENT_ENDPOINTS:
        return "access_management"
    if endpoint in _ACCOUNTS_ENDPOINTS:
        return "accounts"
    if endpoint in _PAYROLL_PARENT_ENDPOINTS:
        return "employee_payroll"
    if endpoint in _POINT_OF_SALE_ENDPOINTS:
        return "point_of_sale"
    if endpoint in _POINT_OF_SALE_BAR_ENDPOINTS:
        return "point_of_sale_bar"
    if endpoint in _HOTEL_ROOMS_ENDPOINTS:
        return "hotel_rooms"
    if endpoint in _COMMUNICATION_HUB_ENDPOINTS:
        return "communication_hub"
    if endpoint in _STORES_ENDPOINTS or bare in _STORES_ENDPOINTS:
        return "stores"
    if endpoint in _MASTER_ENDPOINTS:
        return "master"
    if endpoint in _REPORTS_ENDPOINTS:
        return "reports"
    if endpoint in _SETTINGS_ENDPOINTS:
        return "settings"
    return None


def get_endpoint_payroll_submodule(endpoint):
    for key, endpoints in _PAYROLL_ENDPOINT_GROUPS.items():
        if endpoint in endpoints:
            return key
    return None


def get_endpoint_accounts_submodule(endpoint):
    for key, endpoints in _ACCOUNTS_ENDPOINT_GROUPS.items():
        if endpoint in endpoints:
            return key
    return None


def get_endpoint_stores_submodule(endpoint):
    bare = endpoint.split(".", 1)[1] if endpoint and endpoint.startswith("stores.") else endpoint
    for key, endpoints in _STORES_ENDPOINT_GROUPS.items():
        if endpoint in endpoints or bare in endpoints:
            return key
    return None


def user_can_access_endpoint_stores(user, endpoint):
    submodule = get_endpoint_stores_submodule(endpoint)
    if not submodule:
        return True
    return user_can_access_stores_submodule(user, submodule)


def get_endpoint_sales_analytics_submodules(endpoint):
    matches = []
    for key, endpoints in _SALES_ANALYTICS_ENDPOINT_GROUPS.items():
        if endpoint in endpoints:
            matches.append(key)
    return matches


def user_can_access_endpoint_sales_analytics(user, endpoint):
    submodules = get_endpoint_sales_analytics_submodules(endpoint)
    if not submodules:
        return True
    if (
        endpoint in _POS_RESTAURANT_SALES_WRITE_ENDPOINTS
        and user_can_access_dashboard(user, "point_of_sale")
    ):
        return True
    if len(submodules) == 1:
        return user_can_access_sales_analytics_submodule(user, submodules[0])
    return any(
        user_can_access_sales_analytics_submodule(user, submodule)
        for submodule in submodules
    )


def user_can_access_endpoint_accounts(user, endpoint):
    submodule = get_endpoint_accounts_submodule(endpoint)
    if not submodule:
        return True
    return user_can_access_accounts_submodule(user, submodule)


def get_endpoint_user_access_submodule(endpoint):
    for key, endpoints in _ACCESS_ENDPOINT_GROUPS.items():
        if endpoint in endpoints:
            return key
    return None


def normalize_username(value):
    return (value or "").strip()


def is_system_administrator(user):
    if not user:
        return False
    username = (user.get("username") or "").strip().lower()
    return username in {"admin", "admin_rajeshkumar"}


def user_can_edit_kot_sent_lines(user):
    """True when the user may change or remove kitchen-sent POS lines.

    Granted via the Cancellation Access module (administrators include all modules).
    """
    return user_can_access_dashboard(user, "cancellation_access")


def user_can_approve_transactions(user):
    """True when the user may clear/verify/revert settlement transactions
    and open Indent Approvals.

    Granted via the Approval module (administrators include all modules).
    Covers Credit Payment Clear Payment / Revert, Purchase Verification
    Verify / Approve / Revert, and Stores Indent Approvals. View access to
    settlement pages is separate.
    """
    return user_can_access_dashboard(user, "approval")


def _normalize_permission_modules(
    dashboard_modules,
    sales_analytics_modules=None,
    user_access_modules=None,
    payroll_modules=None,
    accounts_modules=None,
    stores_modules=None,
):
    dashboard_modules = sorted({
        module for module in (dashboard_modules or []) if module in _DASHBOARD_MODULE_LABELS
    })
    sales_analytics_modules = sorted({
        module
        for module in (sales_analytics_modules or [])
        if module in _SALES_ANALYTICS_SUBMODULE_LABELS
    })
    user_access_modules = sorted({
        module
        for module in (user_access_modules or [])
        if module in _USER_ACCESS_SUBMODULE_LABELS
    })
    payroll_modules = sorted({
        module
        for module in (payroll_modules or [])
        if module in _PAYROLL_SUBMODULE_LABELS
    })
    accounts_modules = sorted({
        module
        for module in (accounts_modules or [])
        if module in _ACCOUNTS_SUBMODULE_LABELS
    })
    stores_modules = sorted({
        module
        for module in (stores_modules or [])
        if module in _STORES_SUBMODULE_LABELS
    })

    if sales_analytics_modules and "sales_analytics" not in dashboard_modules:
        dashboard_modules = sorted(set(dashboard_modules + ["sales_analytics"]))
    if user_access_modules and "access_management" not in dashboard_modules:
        dashboard_modules = sorted(set(dashboard_modules + ["access_management"]))
    if payroll_modules and "employee_payroll" not in dashboard_modules:
        dashboard_modules = sorted(set(dashboard_modules + ["employee_payroll"]))
    if accounts_modules and "accounts" not in dashboard_modules:
        dashboard_modules = sorted(set(dashboard_modules + ["accounts"]))
    if stores_modules and "stores" not in dashboard_modules:
        dashboard_modules = sorted(set(dashboard_modules + ["stores"]))

    return (
        dashboard_modules,
        sales_analytics_modules,
        user_access_modules,
        payroll_modules,
        accounts_modules,
        stores_modules,
    )


def _permission_insert_rows(
    dashboard_modules,
    sales_analytics_modules,
    user_access_modules,
    payroll_modules,
    accounts_modules,
    stores_modules,
):
    rows = []
    for module_key in dashboard_modules:
        rows.append(("dashboard", module_key))
    if "sales_analytics" in dashboard_modules:
        for module_key in sales_analytics_modules:
            rows.append(("sales_analytics", module_key))
    if "access_management" in dashboard_modules:
        for module_key in user_access_modules:
            rows.append(("user_access", module_key))
    if "employee_payroll" in dashboard_modules:
        for module_key in payroll_modules:
            rows.append(("payroll", module_key))
    if "accounts" in dashboard_modules:
        for module_key in accounts_modules:
            rows.append(("accounts", module_key))
    if "stores" in dashboard_modules:
        for module_key in stores_modules:
            rows.append(("stores", module_key))
    return rows


def set_user_permissions(
    conn,
    user_id,
    dashboard_modules,
    sales_analytics_modules=None,
    user_access_modules=None,
    payroll_modules=None,
    accounts_modules=None,
    stores_modules=None,
):
    (
        dashboard_modules,
        sales_analytics_modules,
        user_access_modules,
        payroll_modules,
        accounts_modules,
        stores_modules,
    ) = _normalize_permission_modules(
        dashboard_modules,
        sales_analytics_modules,
        user_access_modules,
        payroll_modules,
        accounts_modules,
        stores_modules,
    )
    conn.execute("DELETE FROM user_permissions WHERE user_id = ?", (user_id,))
    for scope, item_key in _permission_insert_rows(
        dashboard_modules,
        sales_analytics_modules,
        user_access_modules,
        payroll_modules,
        accounts_modules,
        stores_modules,
    ):
        conn.execute(
            "INSERT INTO user_permissions (user_id, scope, item_key) VALUES (?, ?, ?)",
            (user_id, scope, item_key),
        )


def set_role_permissions(
    conn,
    role_id,
    dashboard_modules,
    sales_analytics_modules=None,
    user_access_modules=None,
    payroll_modules=None,
    accounts_modules=None,
    stores_modules=None,
):
    (
        dashboard_modules,
        sales_analytics_modules,
        user_access_modules,
        payroll_modules,
        accounts_modules,
        stores_modules,
    ) = _normalize_permission_modules(
        dashboard_modules,
        sales_analytics_modules,
        user_access_modules,
        payroll_modules,
        accounts_modules,
        stores_modules,
    )
    conn.execute("DELETE FROM access_role_permissions WHERE role_id = ?", (role_id,))
    for scope, item_key in _permission_insert_rows(
        dashboard_modules,
        sales_analytics_modules,
        user_access_modules,
        payroll_modules,
        accounts_modules,
        stores_modules,
    ):
        conn.execute(
            "INSERT INTO access_role_permissions (role_id, scope, item_key) VALUES (?, ?, ?)",
            (role_id, scope, item_key),
        )


def _access_label_bundle(entity):
    return {
        "dashboard_labels": [
            _DASHBOARD_MODULE_LABELS[key] for key in dashboard_access_list(entity)
        ],
        "sales_analytics_labels": [
            _SALES_ANALYTICS_SUBMODULE_LABELS[key]
            for key in sales_analytics_access_list(entity)
        ],
        "user_access_labels": [
            _USER_ACCESS_SUBMODULE_LABELS[key] for key in user_access_submodule_list(entity)
        ],
        "payroll_labels": [
            _PAYROLL_SUBMODULE_LABELS[key] for key in payroll_access_list(entity)
        ],
        "accounts_labels": [
            _ACCOUNTS_SUBMODULE_LABELS[key] for key in accounts_access_list(entity)
        ],
        "stores_labels": [
            _STORES_SUBMODULE_LABELS[key] for key in stores_access_list(entity)
        ],
    }


def fetch_access_management_users(conn, selected_user_id=None):
    user_rows = conn.execute(
        "SELECT * FROM users ORDER BY is_admin DESC, LOWER(username), id"
    ).fetchall()
    users = []
    for row in user_rows:
        user = build_user_context(conn, row)
        user.update(_access_label_bundle(user))
        users.append(user)

    selected_user = None
    if selected_user_id:
        for user in users:
            if int(user["id"]) == int(selected_user_id):
                selected_user = user
                break
    return users, selected_user


def get_access_role(conn, role_id):
    if not role_id:
        return None
    row = conn.execute(
        "SELECT * FROM access_roles WHERE id = ?",
        (role_id,),
    ).fetchone()
    if not row:
        return None
    role = dict(row)
    role["is_admin"] = bool(role.get("is_admin"))
    role["is_active"] = bool(role.get("is_active"))
    if role["is_admin"]:
        _apply_permission_sets(role, _empty_permission_sets())
    else:
        _apply_permission_sets(role, load_role_permissions(conn, role["id"]))
    role.update(_access_label_bundle(role))
    role["user_count"] = int(
        conn.execute(
            "SELECT COUNT(*) FROM users WHERE role_id = ?",
            (role["id"],),
        ).fetchone()[0]
    )
    return role


def list_access_roles(conn, *, active_only=False):
    sql = """
        SELECT r.*,
               (SELECT COUNT(*) FROM users u WHERE u.role_id = r.id) AS user_count
        FROM access_roles r
    """
    if active_only:
        sql += " WHERE r.is_active = 1"
    sql += " ORDER BY r.is_admin DESC, LOWER(r.name), r.id"
    roles = []
    for row in conn.execute(sql).fetchall():
        role = get_access_role(conn, row["id"])
        if role:
            role["user_count"] = int(row["user_count"] or 0)
            roles.append(role)
    return roles


def role_summary_for_ui(role):
    """JSON-safe role payload for user-form summary chips."""
    if not role:
        return None
    return {
        "id": role.get("id"),
        "name": role.get("name") or "",
        "is_admin": bool(role.get("is_admin")),
        "dashboard_labels": list(role.get("dashboard_labels") or []),
        "sales_analytics_labels": list(role.get("sales_analytics_labels") or []),
        "user_access_labels": list(role.get("user_access_labels") or []),
        "payroll_labels": list(role.get("payroll_labels") or []),
        "accounts_labels": list(role.get("accounts_labels") or []),
        "stores_labels": list(role.get("stores_labels") or []),
    }


def ensure_access_roles_schema(conn):
    """Create role tables (if needed), seed Super Administrator, and migrate legacy users."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS access_roles (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT    NOT NULL UNIQUE,
            description TEXT    NOT NULL DEFAULT '',
            is_admin    INTEGER NOT NULL DEFAULT 0,
            is_active   INTEGER NOT NULL DEFAULT 1,
            created_at  TEXT    NOT NULL,
            updated_at  TEXT    NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS access_role_permissions (
            role_id  INTEGER NOT NULL,
            scope    TEXT    NOT NULL,
            item_key TEXT    NOT NULL,
            UNIQUE(role_id, scope, item_key)
        )
    """)
    user_cols = {row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
    if "role_id" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN role_id INTEGER")
    if "photo_path" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN photo_path TEXT NOT NULL DEFAULT ''")

    now_row = conn.execute("SELECT datetime('now','localtime')").fetchone()
    now = now_row[0] if now_row else ""
    # Rename legacy full-authority "Administrator" → "Super Administrator".
    # Only is_admin=1 rows are legacy; a custom role named Administrator must stay.
    legacy_admin = conn.execute(
        """SELECT id, is_admin FROM access_roles
           WHERE LOWER(name) = LOWER(?) AND is_admin = 1""",
        ("Administrator",),
    ).fetchone()
    super_admin = conn.execute(
        "SELECT id FROM access_roles WHERE LOWER(name) = LOWER(?)",
        (_ADMINISTRATOR_ROLE_NAME,),
    ).fetchone()
    if legacy_admin and not super_admin:
        conn.execute(
            """UPDATE access_roles
               SET name = ?, description = ?, is_admin = 1,
                   updated_at = datetime('now','localtime')
               WHERE id = ?""",
            (
                _ADMINISTRATOR_ROLE_NAME,
                "Full authority across all workspace modules.",
                int(legacy_admin["id"]),
            ),
        )
    elif legacy_admin and super_admin and int(legacy_admin["id"]) != int(super_admin["id"]):
        # Both names exist after a partial migrate — fold legacy into Super Administrator.
        legacy_id = int(legacy_admin["id"])
        super_id = int(super_admin["id"])
        conn.execute(
            "UPDATE users SET role_id = ?, is_admin = 1 WHERE role_id = ?",
            (super_id, legacy_id),
        )
        conn.execute(
            "DELETE FROM access_role_permissions WHERE role_id = ?",
            (legacy_id,),
        )
        conn.execute("DELETE FROM access_roles WHERE id = ?", (legacy_id,))
    admin_role = conn.execute(
        "SELECT id FROM access_roles WHERE LOWER(name) = LOWER(?)",
        (_ADMINISTRATOR_ROLE_NAME,),
    ).fetchone()
    if not admin_role:
        leftover = conn.execute(
            """SELECT id FROM access_roles
               WHERE is_admin = 1
               ORDER BY id ASC LIMIT 1"""
        ).fetchone()
        if leftover:
            conn.execute(
                """UPDATE access_roles
                   SET name = ?, description = ?, is_admin = 1,
                       updated_at = datetime('now','localtime')
                   WHERE id = ?""",
                (
                    _ADMINISTRATOR_ROLE_NAME,
                    "Full authority across all workspace modules.",
                    int(leftover["id"]),
                ),
            )
            admin_role = leftover
        else:
            conn.execute(
                """INSERT INTO access_roles
                   (name, description, is_admin, is_active, created_at, updated_at)
                   VALUES (?, ?, 1, 1, ?, ?)""",
                (
                    _ADMINISTRATOR_ROLE_NAME,
                    "Full authority across all workspace modules.",
                    now,
                    now,
                ),
            )
            admin_role = conn.execute(
                "SELECT id FROM access_roles WHERE LOWER(name) = LOWER(?)",
                (_ADMINISTRATOR_ROLE_NAME,),
            ).fetchone()
    admin_role_id = int(admin_role["id"])
    conn.execute(
        "UPDATE access_roles SET is_admin = 1 WHERE id = ?",
        (admin_role_id,),
    )
    # Keep users.is_admin=1 on Super Administrator even if they were assigned
    # a custom non-admin role (e.g. one named "Administrator").
    conn.execute(
        """
        UPDATE users
           SET role_id = ?, is_admin = 1
         WHERE is_admin = 1
           AND (
               role_id IS NULL
               OR role_id NOT IN (SELECT id FROM access_roles WHERE is_admin = 1)
           )
        """,
        (admin_role_id,),
    )

    pending = conn.execute(
        "SELECT * FROM users WHERE role_id IS NULL ORDER BY id"
    ).fetchall()
    for row in pending:
        user = dict(row)
        if bool(user.get("is_admin")):
            conn.execute(
                "UPDATE users SET role_id = ?, is_admin = 1 WHERE id = ?",
                (admin_role_id, user["id"]),
            )
            continue

        perm_rows = conn.execute(
            "SELECT scope, item_key FROM user_permissions WHERE user_id = ?",
            (user["id"],),
        ).fetchall()
        if not perm_rows:
            continue

        username = (user.get("username") or f"user{user['id']}").strip()
        role_name = f"Imported — {username}"
        existing_imported = conn.execute(
            "SELECT id FROM access_roles WHERE LOWER(name) = LOWER(?)",
            (role_name,),
        ).fetchone()
        if existing_imported:
            role_id = int(existing_imported["id"])
        else:
            conn.execute(
                """INSERT INTO access_roles
                   (name, description, is_admin, is_active, created_at, updated_at)
                   VALUES (?, ?, 0, 1, ?, ?)""",
                (
                    role_name,
                    f"Imported permissions for {username}.",
                    now,
                    now,
                ),
            )
            role_id = int(
                conn.execute(
                    "SELECT id FROM access_roles WHERE LOWER(name) = LOWER(?)",
                    (role_name,),
                ).fetchone()["id"]
            )
            (
                dashboard_access,
                sales_analytics_access,
                user_access,
                payroll_access,
                accounts_access,
                stores_access,
            ) = _permission_sets_from_rows(perm_rows)
            set_role_permissions(
                conn,
                role_id,
                sorted(dashboard_access),
                sorted(sales_analytics_access),
                sorted(user_access),
                sorted(payroll_access),
                sorted(accounts_access),
                sorted(stores_access),
            )
        conn.execute(
            "UPDATE users SET role_id = ?, is_admin = 0 WHERE id = ?",
            (role_id, user["id"]),
        )


def _sync_users_is_admin_for_role(conn, role_id, is_admin):
    conn.execute(
        "UPDATE users SET is_admin = ? WHERE role_id = ?",
        (int(bool(is_admin)), role_id),
    )


def validate_access_user_form(
    conn,
    *,
    actor,
    user_id,
    username,
    password,
    role_id,
    email="",
):
    errors = []
    actor_is_admin = bool(actor and actor.get("is_admin"))
    role = get_access_role(conn, role_id) if role_id else None
    is_admin = bool(role and role.get("is_admin"))

    if not username:
        errors.append("Username is required.")
    email = (email or "").strip()
    if not email:
        errors.append("Email is required.")
    else:
        from auth_security import is_valid_email

        if not is_valid_email(email):
            errors.append("Enter a valid email address.")
    if not user_id and not password:
        errors.append("Password is required for a new user.")
    if not role_id:
        errors.append("Role is required.")
    elif not role:
        errors.append("Selected role was not found.")
    elif not role.get("is_active"):
        errors.append("Selected role is inactive.")

    if not actor_is_admin:
        if user_id and not user_can_access_user_access_submodule(actor, "users"):
            errors.append("You do not have permission to edit users.")
        if not user_id and not user_can_access_user_access_submodule(actor, "add"):
            errors.append("You do not have permission to create users.")

    existing = conn.execute(
        "SELECT id FROM users WHERE LOWER(username) = LOWER(?)",
        (username,),
    ).fetchone()
    if existing and (user_id is None or int(existing["id"]) != int(user_id)):
        errors.append("That username is already in use.")

    original = None
    if user_id:
        original = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not original:
            errors.append("User not found.")

    if not actor_is_admin:
        if is_admin:
            errors.append("Only Super Administrators can assign the Super Administrator role.")
        if original and bool(original["is_admin"]):
            errors.append("Only administrators can edit administrator accounts.")

    active_admin_count = int(
        conn.execute(
            "SELECT COUNT(*) FROM users WHERE is_admin = 1 AND is_active = 1"
        ).fetchone()[0]
    )
    if (
        original
        and bool(original["is_admin"])
        and bool(original["is_active"])
        and not is_admin
        and active_admin_count <= 1
    ):
        errors.append("At least one active administrator must remain in the system.")

    return errors, original, role


def save_access_user_record(
    conn,
    *,
    user_id,
    username,
    full_name,
    password,
    role_id,
    sql_now,
    email="",
    photo_path=None,
):
    email = (email or "").strip()
    role = get_access_role(conn, role_id)
    is_admin = bool(role and role.get("is_admin"))
    if user_id:
        params = [username, full_name, email, int(is_admin), role_id]
        update_sql = (
            f"UPDATE users SET username = ?, full_name = ?, email = ?, is_admin = ?, "
            f"role_id = ?, is_active = 1, updated_at = {sql_now}"
        )
        if password:
            update_sql += ", password_hash = ?, must_change_password = 1"
            params.append(auth_security.hash_password(password))
        if photo_path is not None:
            update_sql += ", photo_path = ?"
            params.append((photo_path or "").strip())
        update_sql += " WHERE id = ?"
        params.append(user_id)
        conn.execute(update_sql, tuple(params))
        saved_user_id = user_id
        result_flag = "updated"
    else:
        conn.execute(
            f"""INSERT INTO users
                (username, full_name, email, password_hash, is_admin, role_id, photo_path,
                 must_change_password, is_active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1, 1, {sql_now}, {sql_now})""",
            (
                username,
                full_name,
                email,
                auth_security.hash_password(password),
                int(is_admin),
                role_id,
                (photo_path or "").strip() if photo_path is not None else "",
            ),
        )
        saved_user_id = conn.execute(
            "SELECT id FROM users WHERE LOWER(username) = LOWER(?)",
            (username,),
        ).fetchone()["id"]
        result_flag = "created"

    # Permissions are owned by the role; clear legacy per-user rows.
    conn.execute("DELETE FROM user_permissions WHERE user_id = ?", (saved_user_id,))
    return saved_user_id, result_flag


def validate_access_role_form(
    conn,
    *,
    actor,
    role_id,
    name,
    is_admin,
    dashboard_modules,
    sales_analytics_modules,
    user_access_modules,
    payroll_modules=None,
    accounts_modules=None,
    stores_modules=None,
):
    errors = []
    actor_is_admin = bool(actor and actor.get("is_admin"))
    name = (name or "").strip()

    if not actor_is_admin and not user_can_access_user_access_submodule(actor, "roles"):
        errors.append("You do not have permission to manage roles.")
    if not name:
        errors.append("Role name is required.")

    # Exclude the row being edited so an in-use role can keep its own name.
    if role_id is not None:
        existing = conn.execute(
            """SELECT id FROM access_roles
               WHERE LOWER(name) = LOWER(?) AND id != ?""",
            (name, int(role_id)),
        ).fetchone()
    else:
        existing = conn.execute(
            "SELECT id FROM access_roles WHERE LOWER(name) = LOWER(?)",
            (name,),
        ).fetchone()
    if existing:
        errors.append("That role name is already in use.")

    original = None
    if role_id:
        original = conn.execute(
            "SELECT * FROM access_roles WHERE id = ?",
            (role_id,),
        ).fetchone()
        if not original:
            errors.append("Role not found.")

    # Full authority (is_admin) is reserved for the Super Administrator role.
    if is_admin and not is_built_in_administrator_role(original, name=name, role_id=role_id):
        errors.append("Only the Super Administrator role can have full authority.")

    if not is_admin and not dashboard_modules:
        errors.append("Select at least one dashboard module for a non-admin role.")
    if "sales_analytics" in dashboard_modules and not sales_analytics_modules and not is_admin:
        errors.append(
            "Choose at least one Sales Analytics submodule when Sales Analytics access is enabled."
        )
    if "access_management" in dashboard_modules and not user_access_modules and not is_admin:
        errors.append(
            "Choose at least one User & Access submodule when User & Access is enabled."
        )
    if "employee_payroll" in dashboard_modules and not payroll_modules and not is_admin:
        errors.append(
            "Choose at least one Employee Payroll submodule when Employee Payroll access is enabled."
        )
    if "accounts" in dashboard_modules and not accounts_modules and not is_admin:
        errors.append(
            "Choose at least one Accounts submodule when Accounts access is enabled."
        )
    if "stores" in dashboard_modules and not stores_modules and not is_admin:
        errors.append(
            "Choose at least one Purchase & Inventory submodule when Purchase & Inventory access is enabled."
        )

    if original and bool(original["is_admin"]) and not is_admin:
        assigned_active_admins = int(
            conn.execute(
                """SELECT COUNT(*) FROM users
                   WHERE role_id = ? AND is_admin = 1 AND is_active = 1""",
                (role_id,),
            ).fetchone()[0]
        )
        other_active_admins = int(
            conn.execute(
                """SELECT COUNT(*) FROM users
                   WHERE is_admin = 1 AND is_active = 1
                     AND (role_id IS NULL OR role_id != ?)""",
                (role_id,),
            ).fetchone()[0]
        )
        if assigned_active_admins and other_active_admins <= 0:
            errors.append("At least one active administrator must remain in the system.")

    return errors, original


def save_access_role_record(
    conn,
    *,
    role_id,
    name,
    description,
    is_admin,
    is_active,
    dashboard_modules,
    sales_analytics_modules,
    user_access_modules,
    payroll_modules=None,
    accounts_modules=None,
    stores_modules=None,
    sql_now,
):
    name = (name or "").strip()
    description = (description or "").strip()
    is_admin = bool(is_admin)
    is_active = bool(is_active)
    if role_id:
        conn.execute(
            f"""UPDATE access_roles
                SET name = ?, description = ?, is_admin = ?, is_active = ?, updated_at = {sql_now}
                WHERE id = ?""",
            (name, description, int(is_admin), int(is_active), role_id),
        )
        saved_role_id = role_id
        result_flag = "updated"
    else:
        conn.execute(
            f"""INSERT INTO access_roles
                (name, description, is_admin, is_active, created_at, updated_at)
                VALUES (?, ?, ?, ?, {sql_now}, {sql_now})""",
            (name, description, int(is_admin), int(is_active)),
        )
        saved_role_id = conn.execute(
            "SELECT id FROM access_roles WHERE LOWER(name) = LOWER(?)",
            (name,),
        ).fetchone()["id"]
        result_flag = "created"

    if is_admin:
        conn.execute(
            "DELETE FROM access_role_permissions WHERE role_id = ?",
            (saved_role_id,),
        )
    else:
        set_role_permissions(
            conn,
            saved_role_id,
            dashboard_modules,
            sales_analytics_modules,
            user_access_modules,
            payroll_modules,
            accounts_modules,
            stores_modules,
        )
    _sync_users_is_admin_for_role(conn, saved_role_id, is_admin)
    return saved_role_id, result_flag


def delete_access_role(conn, role_id):
    role = get_access_role(conn, role_id)
    if not role:
        return False, "Role not found."
    if int(role.get("user_count") or 0) > 0:
        return False, "Reassign users before deleting this role."
    conn.execute("DELETE FROM access_role_permissions WHERE role_id = ?", (role_id,))
    conn.execute("DELETE FROM access_roles WHERE id = ?", (role_id,))
    return True, ""
